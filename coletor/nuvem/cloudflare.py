"""Cliente REST do Cloudflare: D1, Vectorize v2 e Workers AI (só biblioteca padrão).

Limites seguidos (documentação de 2026):

- D1 `POST /accounts/{conta}/d1/database/{banco}/query`, com `{"sql", "params"}` ou
  `{"batch": [...]}`: até 100 parâmetros por instrução, 100.000 bytes por instrução,
  sem `BEGIN`/`COMMIT` explícitos (o lote é a unidade atômica); parâmetros vão como
  texto, e NULL vai embutido na instrução.
- Vectorize v2 `insert`/`upsert` em multipart (`vectors`, NDJSON), até 5.000 vetores e
  100 MB por requisição; `delete_by_ids`; `info` e espera por `processedUpToMutation`.
- Workers AI `@cf/baai/bge-m3`, 1.024 dimensões conferidas a cada resposta, lotes de 50.

429 com `Retry-After`, 5xx e falhas de rede são repetidos em `rede.requisitar`. O token
(`CLOUDFLARE_API_TOKEN` ou `CLOUDFLARE_API_TOKEN_DADOS`) nunca aparece em mensagens.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from coletor.nuvem.rede import TENTATIVAS, TIMEOUT, ErroNuvem, redigir, requisitar, url_segura

API = "https://api.cloudflare.com/client/v4"
MODELO = "@cf/baai/bge-m3"
DIMENSOES = 1024

MAX_PARAMETROS = 100
MAX_BYTES_INSTRUCAO = 100_000
MAX_INSTRUCOES_LOTE = 50  # instruções por requisição de lote (escolha nossa)
MAX_BYTES_LOTE = 1_000_000  # corpo de uma requisição de lote (escolha nossa)

MAX_VETORES_LOTE = 5000
MAX_BYTES_VETORES = 100 * 1000 * 1000
LOTE_VETORES = 1000
MAX_IDS_APAGAR = 1000
MAX_IDS_OBTER = 20
LOTE_EMBEDDINGS = 50

_RE_TRANSACAO = re.compile(r"^\s*(BEGIN|COMMIT|ROLLBACK|END|SAVEPOINT|RELEASE)\b", re.I)


def token_do_ambiente(env: Mapping[str, str] = os.environ) -> str:
    token = env.get("CLOUDFLARE_API_TOKEN") or env.get("CLOUDFLARE_API_TOKEN_DADOS")
    if not token:
        raise ErroNuvem("defina CLOUDFLARE_API_TOKEN (ou CLOUDFLARE_API_TOKEN_DADOS)")
    return token


class Cloudflare:
    """Chamadas autenticadas a `/accounts/{conta}/…`, conferindo `success`."""

    def __init__(self, conta: str, token: str, *, base: str = API, tentativas: int = TENTATIVAS,
                 timeout: float = TIMEOUT, dormir: Callable[[float], Any] = time.sleep) -> None:
        if not conta or not token:
            raise ValueError("conta e token são obrigatórios")
        self.conta = conta
        self.base = base.rstrip("/")
        self.tentativas = tentativas
        self.timeout = timeout
        self.dormir = dormir
        self._token = token

    def __repr__(self) -> str:
        return f"Cloudflare(conta={self.conta!r})"

    def chamar(self, metodo: str, caminho: str, *, json_: Any = None, corpo: bytes | None = None,
               tipo: str | None = None) -> Any:
        url = f"{self.base}/accounts/{self.conta}/{caminho.lstrip('/')}"
        cab = {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}
        if json_ is not None:
            corpo = json.dumps(json_, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            tipo = "application/json"
        if tipo:
            cab["Content-Type"] = tipo
        r = requisitar(metodo, url, corpo, cab, tentativas=self.tentativas, timeout=self.timeout,
                       dormir=self.dormir, segredos=(self._token,))
        try:
            dados = r.json()
        except ValueError:
            raise ErroNuvem(f"{metodo} {url_segura(url)}: resposta não é JSON", r.status) from None
        if not isinstance(dados, dict) or not dados.get("success", False):
            erros = dados.get("errors") if isinstance(dados, dict) else None
            raise ErroNuvem(redigir(f"{metodo} {url_segura(url)}: sem sucesso: {json.dumps(erros)[:300]}",
                                    (self._token,)), r.status)
        return dados.get("result")


# ---------------------------------------------------------------- D1
def validar_instrucao(sql: str, params: Sequence[Any] = ()) -> None:
    """ValueError se a instrução passa dos limites do D1 ou abre uma transação explícita."""
    if len(params) > MAX_PARAMETROS:
        raise ValueError(f"instrução com {len(params)} parâmetros (máximo {MAX_PARAMETROS})")
    tamanho = len(sql.encode("utf-8"))
    if tamanho > MAX_BYTES_INSTRUCAO:
        raise ValueError(f"instrução com {tamanho} bytes (máximo {MAX_BYTES_INSTRUCAO})")
    if _RE_TRANSACAO.match(sql):
        raise ValueError("o D1 não aceita BEGIN/COMMIT explícitos; use um lote")


def parametro_d1(valor: Any) -> str:
    """Parâmetro como texto (a afinidade da coluna converte INTEGER e REAL)."""
    if valor is None:
        raise ValueError("NULL deve ir embutido na instrução")
    if isinstance(valor, bool):
        return "1" if valor else "0"
    if isinstance(valor, float):
        if not math.isfinite(valor):
            raise ValueError("número não finito")
        return repr(valor)
    if isinstance(valor, (int, str)):
        return str(valor)
    raise TypeError(f"tipo de parâmetro não suportado: {type(valor).__name__}")


def dividir_lote(instrucoes: Sequence[tuple[str, Sequence[Any]]], max_instrucoes: int = MAX_INSTRUCOES_LOTE,
                 max_bytes: int = MAX_BYTES_LOTE) -> list[list[tuple[str, Sequence[Any]]]]:
    """Grupos de instruções para requisições de lote, validando cada instrução."""
    grupos: list[list] = []
    atual: list = []
    tamanho = 0
    for sql, params in instrucoes:
        validar_instrucao(sql, params)
        peso = len(sql.encode("utf-8")) + sum(len(parametro_d1(p).encode("utf-8")) + 4 for p in params) + 32
        if atual and (len(atual) >= max_instrucoes or tamanho + peso > max_bytes):
            grupos.append(atual)
            atual, tamanho = [], 0
        atual.append((sql, params))
        tamanho += peso
    if atual:
        grupos.append(atual)
    return grupos


class D1:
    def __init__(self, cf: Cloudflare, banco_id: str, *, max_instrucoes: int = MAX_INSTRUCOES_LOTE,
                 max_bytes: int = MAX_BYTES_LOTE) -> None:
        self.cf = cf
        self.banco_id = banco_id
        self.max_instrucoes = max_instrucoes
        self.max_bytes = max_bytes

    def _caminho(self) -> str:
        return f"d1/database/{self.banco_id}/query"

    def consultar(self, sql: str, params: Sequence[Any] = ()) -> list[dict]:
        validar_instrucao(sql, params)
        r = self.cf.chamar("POST", self._caminho(),
                           json_={"sql": sql, "params": [parametro_d1(p) for p in params]})
        if not r:
            return []
        primeiro = r[0] if isinstance(r, list) else r
        return list(primeiro.get("results") or [])

    def lote(self, instrucoes: Sequence[tuple[str, Sequence[Any]]]) -> list[list[dict]]:
        """Executa em requisições de lote (cada uma atômica no D1); resultados por instrução."""
        saida: list[list[dict]] = []
        for grupo in dividir_lote(instrucoes, self.max_instrucoes, self.max_bytes):
            corpo = {"batch": [{"sql": s, "params": [parametro_d1(p) for p in ps]} for s, ps in grupo]}
            r = self.cf.chamar("POST", self._caminho(), json_=corpo) or []
            saida.extend(list(item.get("results") or []) for item in r)
        return saida


# ---------------------------------------------------------------- Vectorize
def _linha_vetor(vetor: Mapping[str, Any]) -> bytes:
    valores = vetor["values"]
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in valores):
        raise ValueError(f"vetor {vetor['id']}: valores inválidos")
    obj = {"id": vetor["id"], "values": list(valores)}
    if vetor.get("metadata"):
        obj["metadata"] = vetor["metadata"]
    return (json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _multipart(ndjson: bytes) -> tuple[bytes, str]:
    fronteira = "radar" + hashlib.sha1(ndjson).hexdigest()[:24]
    return _envelope(fronteira, ndjson), fronteira


def _envelope(fronteira: str, ndjson: bytes) -> bytes:
    return (f"--{fronteira}\r\nContent-Disposition: form-data; name=\"vectors\"; filename=\"vectors.ndjson\"\r\n"
            f"Content-Type: application/x-ndjson\r\n\r\n").encode("ascii") + ndjson + \
        f"\r\n--{fronteira}--\r\n".encode("ascii")


ENVELOPE = len(_envelope("radar" + "0" * 24, b""))


class Vectorize:
    def __init__(self, cf: Cloudflare, indice: str, *, lote: int = LOTE_VETORES, max_bytes: int = MAX_BYTES_VETORES,
                 dormir: Callable[[float], Any] = time.sleep, relogio: Callable[[], float] = time.monotonic) -> None:
        if not 1 <= lote <= MAX_VETORES_LOTE:
            raise ValueError(f"lote do Vectorize entre 1 e {MAX_VETORES_LOTE}")
        if max_bytes > MAX_BYTES_VETORES:
            raise ValueError("lote do Vectorize acima de 100 MB")
        self.cf = cf
        self.indice = indice
        self.lote = lote
        self.max_bytes = max_bytes
        self.dormir = dormir
        self.relogio = relogio

    def _caminho(self, operacao: str) -> str:
        return f"vectorize/v2/indexes/{self.indice}/{operacao}"

    def lotes(self, vetores: Iterable[Mapping[str, Any]]) -> list[bytes]:
        """Corpos NDJSON com até `lote` vetores e até `max_bytes` por requisição (multipart incluído)."""
        saida: list[bytes] = []
        linhas: list[bytes] = []
        tamanho = ENVELOPE
        for vetor in vetores:
            linha = _linha_vetor(vetor)
            if ENVELOPE + len(linha) > self.max_bytes:
                raise ValueError(f"vetor {vetor['id']} maior que o limite da requisição")
            if linhas and (len(linhas) >= self.lote or tamanho + len(linha) > self.max_bytes):
                saida.append(b"".join(linhas))
                linhas, tamanho = [], ENVELOPE
            linhas.append(linha)
            tamanho += len(linha)
        if linhas:
            saida.append(b"".join(linhas))
        return saida

    def _enviar(self, operacao: str, vetores: Iterable[Mapping[str, Any]]) -> list[str]:
        mutacoes = []
        for ndjson in self.lotes(vetores):
            corpo, fronteira = _multipart(ndjson)
            r = self.cf.chamar("POST", self._caminho(operacao), corpo=corpo,
                               tipo=f"multipart/form-data; boundary={fronteira}") or {}
            mutacoes.append(r.get("mutationId"))
        return mutacoes

    def upsert(self, vetores: Iterable[Mapping[str, Any]]) -> list[str]:
        return self._enviar("upsert", vetores)

    def inserir(self, vetores: Iterable[Mapping[str, Any]]) -> list[str]:
        return self._enviar("insert", vetores)

    def apagar(self, ids: Sequence[str]) -> list[str]:
        mutacoes = []
        for i in range(0, len(ids), MAX_IDS_APAGAR):
            r = self.cf.chamar("POST", self._caminho("delete_by_ids"), json_={"ids": list(ids[i:i + MAX_IDS_APAGAR])})
            mutacoes.append((r or {}).get("mutationId"))
        return mutacoes

    def obter(self, ids: Sequence[str]) -> list[dict]:
        saida: list[dict] = []
        for i in range(0, len(ids), MAX_IDS_OBTER):
            r = self.cf.chamar("POST", self._caminho("get_by_ids"), json_={"ids": list(ids[i:i + MAX_IDS_OBTER])})
            saida.extend(r or [])
        return saida

    def info(self) -> dict:
        return self.cf.chamar("GET", self._caminho("info")) or {}

    def esperar(self, mutacao: str | None, timeout: float = 1800.0, intervalo: float = 5.0) -> dict:
        """Espera `processedUpToMutation` chegar à mutação dada; ErroNuvem no prazo."""
        limite = self.relogio() + timeout
        while True:
            info = self.info()
            if mutacao is None or info.get("processedUpToMutation") == mutacao:
                return info
            if self.relogio() >= limite:
                raise ErroNuvem(f"Vectorize {self.indice}: mutação ainda não processada após {timeout:.0f} s")
            self.dormir(intervalo)


# ---------------------------------------------------------------- Workers AI
class WorkersAI:
    def __init__(self, cf: Cloudflare, modelo: str = MODELO, *, lote: int = LOTE_EMBEDDINGS,
                 dimensoes: int = DIMENSOES) -> None:
        self.cf = cf
        self.modelo = modelo
        self.lote = lote
        self.dimensoes = dimensoes
        self.chamadas = 0

    def embeddings(self, textos: Sequence[str]) -> list[list[float]]:
        """Um vetor por texto, em lotes; ErroNuvem se a quantidade ou a dimensão não baterem."""
        saida: list[list[float]] = []
        for i in range(0, len(textos), self.lote):
            bloco = list(textos[i:i + self.lote])
            r = self.cf.chamar("POST", f"ai/run/{self.modelo}", json_={"text": bloco}) or {}
            self.chamadas += 1
            dados = r.get("data") if isinstance(r, dict) else None
            if not isinstance(dados, list) or len(dados) != len(bloco):
                raise ErroNuvem(f"Workers AI {self.modelo}: esperados {len(bloco)} vetores")
            for vetor in dados:
                if not isinstance(vetor, list) or len(vetor) != self.dimensoes:
                    tamanho = len(vetor) if isinstance(vetor, list) else "?"
                    raise ErroNuvem(f"Workers AI {self.modelo}: vetor com {tamanho} dimensões "
                                    f"(esperadas {self.dimensoes})")
                saida.append([float(v) for v in vetor])
        return saida

    __call__ = embeddings
