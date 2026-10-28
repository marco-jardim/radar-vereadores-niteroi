"""HTTP do cliente de nuvem: tentativas, espera progressiva, 429 e redação de segredos.

Somente biblioteca padrão. Mensagens de erro nunca levam tokens, o cabeçalho
`Authorization`, assinaturas SigV4 nem a consulta (`?…`) das URLs: `url_segura`
mantém só esquema, host e caminho, e `redigir` troca os segredos conhecidos por `***`.
"""
from __future__ import annotations

import email.utils
import json
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

TENTATIVAS = 5
TIMEOUT = 60
ESPERA_MAXIMA = 120.0  # espera progressiva (5xx e falhas de rede)
ESPERA_MAXIMA_RETRY_AFTER = 600.0  # teto para o Retry-After de um 429
RETENTAVEIS = frozenset({429, 500, 502, 503, 504})
USER_AGENT = "radar-vereadores-niteroi/nuvem (+https://github.com/marco-jardim/radar-vereadores-niteroi)"
LOCAIS = frozenset({"127.0.0.1", "localhost", "::1"})

_RE_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+")
_RE_ASSINATURA = re.compile(r"(?i)(signature=|credential=|x-amz-security-token=)[^,\s&\"']+")
_RE_URL = re.compile(r"https?://[^\s\"'<>]+")


class ErroNuvem(RuntimeError):
    """Falha de uma chamada à nuvem; a mensagem já vem redigida."""

    def __init__(self, mensagem: str, status: int | None = None) -> None:
        super().__init__(mensagem)
        self.status = status


@dataclass
class Resposta:
    status: int
    cabecalhos: dict[str, str]
    corpo: bytes

    def json(self) -> Any:
        if not self.corpo:
            return None
        return json.loads(self.corpo.decode("utf-8"))


def url_segura(url: str) -> str:
    """Esquema, host (com porta) e caminho; sem credenciais, consulta nem fragmento."""
    p = urllib.parse.urlsplit(url)
    host = p.hostname or ""
    if p.port:
        host += f":{p.port}"
    return f"{p.scheme}://{host}{p.path}"


def redigir(texto: str, segredos: Iterable[str] = ()) -> str:
    """Troca segredos conhecidos, tokens Bearer, assinaturas e consultas de URLs por `***`."""
    for segredo in segredos:
        if segredo and len(segredo) >= 4:
            texto = texto.replace(segredo, "***")
    texto = _RE_BEARER.sub(r"\1***", texto)
    texto = _RE_ASSINATURA.sub(r"\1***", texto)
    return _RE_URL.sub(lambda m: url_segura(m.group()) + ("?***" if "?" in m.group() else ""), texto)


def espera_retry_after(valor: str | None, agora: datetime | None = None) -> float | None:
    """Segundos de espera de um `Retry-After` (segundos ou data HTTP); None se ausente ou inválido."""
    if not valor:
        return None
    valor = valor.strip()
    try:
        return max(0.0, float(valor))
    except ValueError:
        pass
    try:
        data = email.utils.parsedate_to_datetime(valor)
    except (TypeError, ValueError, IndexError):
        return None
    if data is None:
        return None
    if data.tzinfo is None:
        data = data.replace(tzinfo=timezone.utc)
    return max(0.0, (data - (agora or datetime.now(timezone.utc))).total_seconds())


def data_iso(texto: Any) -> datetime | None:
    """Data ISO 8601 (com `Z` ou deslocamento; sem fuso, UTC); None se ausente ou inválida."""
    if not isinstance(texto, str) or not texto.strip():
        return None
    try:
        data = datetime.fromisoformat(texto.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return data if data.tzinfo else data.replace(tzinfo=timezone.utc)


class Ritmo:
    """No máximo `por_segundo` requisições por segundo, somadas todas as threads que o compartilham.

    O limite global da API do Cloudflare é de 1.200 requisições a cada 5 minutos por usuário
    (4 por segundo); o ambiente remoto compartilha um `Ritmo(4)` entre D1, Vectorize, Workers AI e R2 REST.
    """

    def __init__(self, por_segundo: float = 4.0, *, relogio: Callable[[], float] = time.monotonic,
                 dormir: Callable[[float], Any] = time.sleep) -> None:
        if por_segundo <= 0:
            raise ValueError("por_segundo precisa ser positivo")
        self.intervalo = 1.0 / por_segundo
        self.relogio = relogio
        self.dormir = dormir
        self._proximo: float | None = None
        self._trava = threading.Lock()

    def aguardar(self) -> None:
        with self._trava:
            agora = self.relogio()
            if self._proximo is not None and agora < self._proximo:
                self.dormir(self._proximo - agora)
                agora = self._proximo
            self._proximo = agora + self.intervalo


def _trecho(dados: bytes, limite: int = 300) -> str:
    texto = " ".join(dados.decode("utf-8", "replace").split())
    return texto[:limite]


def _abrir(req: urllib.request.Request, timeout: float):
    host = urllib.parse.urlsplit(req.full_url).hostname or ""
    if host in LOCAIS:  # servidor de teste: nunca passa por proxy
        return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout)


def requisitar(metodo: str, url: str, corpo: bytes | None = None, cabecalhos: dict[str, str] | None = None, *,
               aceitar: Iterable[int] = (), tentativas: int = TENTATIVAS, timeout: float = TIMEOUT,
               dormir: Callable[[float], Any] = time.sleep, segredos: Iterable[str] = (),
               assinar: Callable[[], dict[str, str]] | None = None) -> Resposta:
    """Faz a requisição com novas tentativas em 429, 5xx e falhas de rede.

    `aceitar`: códigos de erro devolvidos como resposta (404 num HEAD, 412 num PUT
    condicional). `assinar` é chamado a cada tentativa e devolve cabeçalhos extras
    (assinatura SigV4 com a hora daquela tentativa). Num 429, a espera é a do
    `Retry-After`; sem ele, e nos 5xx, 2, 4, 8… segundos.
    """
    aceitar = frozenset(aceitar)
    segredos = tuple(s for s in segredos if s)
    for tentativa in range(1, tentativas + 1):
        heads = {"User-Agent": USER_AGENT, **(cabecalhos or {})}
        if assinar is not None:
            heads.update(assinar())
        req = urllib.request.Request(url, data=corpo, method=metodo, headers=heads)
        try:
            with _abrir(req, timeout) as r:
                return Resposta(r.status, {k.lower(): v for k, v in r.headers.items()}, r.read())
        except urllib.error.HTTPError as e:
            try:
                dados = e.read() or b""
            except Exception:  # noqa: BLE001 - corpo ilegível não muda o tratamento
                dados = b""
            status = e.code
            cab = {k.lower(): v for k, v in (e.headers.items() if e.headers else [])}
            if status in aceitar:
                return Resposta(status, cab, dados)
            if status in RETENTAVEIS and tentativa < tentativas:
                espera = espera_retry_after(cab.get("retry-after")) if status == 429 else None
                if espera is None:
                    espera = min(ESPERA_MAXIMA, 2.0 ** tentativa)
                dormir(min(espera, ESPERA_MAXIMA_RETRY_AFTER))
                continue
            mensagem = f"{metodo} {url_segura(url)}: HTTP {status}: {_trecho(dados)}"
            raise ErroNuvem(redigir(mensagem, segredos), status) from None
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError, OSError) as e:
            if tentativa < tentativas:
                dormir(min(ESPERA_MAXIMA, 2.0 ** tentativa))
                continue
            mensagem = f"{metodo} {url_segura(url)}: falha de rede ({type(e).__name__})"
            raise ErroNuvem(redigir(mensagem, segredos)) from None
    raise ErroNuvem(f"{metodo} {url_segura(url)}: sem tentativas")  # tentativas < 1
