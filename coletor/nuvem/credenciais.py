"""Token da API do Cloudflare: variável de ambiente ou login OAuth do wrangler.

Ordem: `CLOUDFLARE_API_TOKEN`, depois `CLOUDFLARE_API_TOKEN_DADOS`; sem eles, o `oauth_token`
do arquivo de configuração do wrangler: `WRANGLER_CONFIG`, se definido; senão
`%USERPROFILE%\\.wrangler\\config\\default.toml` (Windows) ou `~/.config/.wrangler/config/default.toml`
(e `~/.wrangler/config/default.toml`). O token OAuth vencido (`expiration_time`, com 60 s de folga)
ou recusado com 401 é renovado executando `wrangler whoami` (o wrangler renova o próprio login) e
relendo o arquivo; há uma única nova tentativa por 401. O token nunca aparece em mensagens nem em `repr`.
"""
from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TypeVar

from coletor.nuvem.rede import ErroNuvem, data_iso

ORIGEM_AMBIENTE = "ambiente"
ORIGEM_OAUTH = "oauth"
FOLGA = timedelta(seconds=60)
VARIAVEIS_TOKEN = ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_API_TOKEN_DADOS")

T = TypeVar("T")


def _campo(texto: str, nome: str) -> str | None:
    m = re.search(rf'(?m)^\s*{re.escape(nome)}\s*=\s*"([^"\r\n]*)"', texto)
    return m.group(1) if m else None


def caminhos_config(env: Mapping[str, str] = os.environ) -> list[Path]:
    """Candidatos ao `default.toml` do wrangler, na ordem de procura."""
    if env.get("WRANGLER_CONFIG"):
        return [Path(env["WRANGLER_CONFIG"])]
    saida: list[Path] = []
    if env.get("USERPROFILE"):
        saida.append(Path(env["USERPROFILE"]) / ".wrangler" / "config" / "default.toml")
    if env.get("XDG_CONFIG_HOME"):
        saida.append(Path(env["XDG_CONFIG_HOME"]) / ".wrangler" / "config" / "default.toml")
    casa = Path(env["HOME"]) if env.get("HOME") else Path.home()
    saida += [casa / ".config" / ".wrangler" / "config" / "default.toml",
              casa / ".wrangler" / "config" / "default.toml"]
    unicos: list[Path] = []
    for caminho in saida:
        if caminho not in unicos:
            unicos.append(caminho)
    return unicos


def ler_oauth(caminho: Path) -> tuple[str, datetime | None]:
    """(oauth_token, expiration_time) do `default.toml`; ErroNuvem sem o token (nunca o mostra)."""
    try:
        texto = Path(caminho).read_text(encoding="utf-8")
    except OSError as e:
        raise ErroNuvem(f"{caminho}: não foi possível ler o login do wrangler ({type(e).__name__})") from None
    token = _campo(texto, "oauth_token")
    if not token:
        raise ErroNuvem(f"{caminho}: sem oauth_token (execute npx wrangler login)")
    return token, data_iso(_campo(texto, "expiration_time"))


class Credencial:
    """Token atual, origem (`ambiente` ou `oauth`) e renovação sob demanda, segura entre threads."""

    def __init__(self, token: str, origem: str = ORIGEM_AMBIENTE, *, expira: datetime | None = None,
                 renovador: Callable[[], tuple[str, datetime | None]] | None = None,
                 relogio: Callable[[], datetime] | None = None,
                 dormir: Callable[[float], Any] = time.sleep) -> None:
        if not token:
            raise ValueError("token vazio")
        self._token = token
        self.origem = origem
        self.expira = expira
        self._renovador = renovador
        self._relogio = relogio or (lambda: datetime.now(timezone.utc))
        self._dormir = dormir
        self._antigos: list[str] = []
        self._trava = threading.Lock()
        self.renovacoes = 0

    def __repr__(self) -> str:
        return f"Credencial(origem={self.origem!r})"

    @property
    def oauth(self) -> bool:
        return self.origem == ORIGEM_OAUTH

    def vencida(self) -> bool:
        return self.expira is not None and self._relogio() >= self.expira - FOLGA

    def token(self) -> str:
        if self._renovador is not None and self.vencida():
            self.renovar(self._token)
        return self._token

    def renovar(self, usado: str | None = None) -> bool:
        """Renova o token; False se não há como renovar. `usado`: o token recusado (evita renovar duas vezes)."""
        if self._renovador is None:
            return False
        with self._trava:
            if usado is not None and usado != self._token:
                return True  # outra thread já renovou
            token, expira = self._renovador()
            agora = self._relogio()
            if token == self._token and expira is not None and agora < expira <= agora + FOLGA:
                # O wrangler só renova depois que o token vence: espera o vencimento e tenta de novo.
                self._dormir((expira - agora).total_seconds() + 2)
                token, expira = self._renovador()
            if token != self._token:
                self._antigos.append(self._token)
            self._token, self.expira = token, expira
            self.renovacoes += 1
        if self.vencida():
            raise ErroNuvem("o login OAuth do wrangler continua vencido depois da renovação "
                            "(execute npx wrangler login)")
        return True

    def segredos(self) -> tuple[str, ...]:
        """Tokens a redigir nas mensagens (o atual e os já trocados)."""
        return (self._token, *self._antigos)


def com_renovacao(credencial: Credencial, chamada: Callable[[str], T]) -> T:
    """`chamada(token)`; num 401, renova a credencial (se der) e tenta uma única vez mais."""
    token = credencial.token()
    try:
        return chamada(token)
    except ErroNuvem as e:
        if e.status != 401 or not credencial.renovar(token):
            raise
    return chamada(credencial.token())


def credencial_do_ambiente(env: Mapping[str, str] = os.environ, *,
                           executar_whoami: Callable[[], Any] | None = None,
                           relogio: Callable[[], datetime] | None = None) -> Credencial:
    """Token das variáveis de ambiente; sem elas, o login OAuth do wrangler (renovado por `executar_whoami`)."""
    for nome in VARIAVEIS_TOKEN:
        if env.get(nome):
            return Credencial(env[nome], ORIGEM_AMBIENTE)
    caminho = next((c for c in caminhos_config(env) if c.is_file()), None)
    if caminho is None:
        raise ErroNuvem("defina CLOUDFLARE_API_TOKEN (ou CLOUDFLARE_API_TOKEN_DADOS) "
                        "ou faça login com npx wrangler login")
    token, expira = ler_oauth(caminho)

    def renovador() -> tuple[str, datetime | None]:
        if executar_whoami is None:
            raise ErroNuvem("login OAuth do wrangler vencido e sem como renovar (execute npx wrangler login)")
        executar_whoami()
        return ler_oauth(caminho)

    return Credencial(token, ORIGEM_OAUTH, expira=expira, renovador=renovador, relogio=relogio)
