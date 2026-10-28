"""Cliente REST do Cloudflare: D1, Vectorize v2 e Workers AI (só biblioteca padrão).

Limites seguidos (documentação de 2026):

- D1 `POST /accounts/{conta}/d1/database/{banco}/query`, com `{"sql", "params"}` ou
  `{"batch": [...]}`: até 100 parâmetros por instrução, 100.000 bytes por instrução,
  sem `BEGIN`/`COMMIT` explícitos (o lote é a unidade atômica); parâmetros vão como
  texto, e NULL vai embutido na instrução.
- Vectorize v2 `insert`/`upsert` em multipart (`vectors`, NDJSON), até 5.000 vetores e
  100 MB por requisição; `delete_by_ids`; `get_by_ids` em lotes de 100; `list` (ids, com
  cursor, até 1.000 por página); `metadata_index/list`; `info` e espera por
  `processedUpToMutation` e `processedUpToDatetime`. Toda mutação precisa devolver `mutationId`.
- Workers AI `@cf/baai/bge-m3`, 1.024 dimensões conferidas a cada resposta, lotes de 50.

429 com `Retry-After`, 5xx e falhas de rede são repetidos em `rede.requisitar`; um `Ritmo`
opcional limita as requisições por segundo. O token (`coletor.nuvem.credenciais`: variável de
ambiente ou login OAuth do wrangler, renovado num 401) nunca aparece em mensagens.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
import urllib.parse
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

from coletor.nuvem.credenciais import Credencial, com_renovacao
from coletor.nuvem.rede import (TENTATIVAS, TIMEOUT, ErroNuvem, Resposta, Ritmo, data_iso, redigir, requisitar,
                                url_segura)

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
MAX_IDS_APAGAR = 100  # delete_by_ids recusa mais de 100 ids (erro 40007)
MAX_IDS_OBTER = 100  # get_by_ids: sem limite documentado claro; 100 por requisição, recuando para 20 num 400
MIN_IDS_OBTER = 20
LOTE_EMBEDDINGS = 50
MAX_CARACTERES_EMBEDDINGS = 60_000  # o bge-m3 aceita 60 mil tokens somados por chamada
# índices de metadados exigidos (contrato, seção 8.2): nome -> tipo do índice no Vectorize
INDICES_METADADOS = {"tipo": "string", "ano": "number", "legislatura": "string"}

_RE_TRANSACAO = re.compile(r"^\s*(BEGIN|COMMIT|ROLLBACK|END|SAVEPOINT|RELEASE)\b", re.I)


def token_do_ambiente(env: Mapping[str, str] = os.environ) -> str:
    token = env.get("CLOUDFLARE_API_TOKEN") or env.get("CLOUDFLARE_API_TOKEN_DADOS")
    if not token:
        raise ErroNuvem("defina CLOUDFLARE_API_TOKEN (ou CLOUDFLARE_API_TOKEN_DADOS)")
    return token


class Cloudflare:
    """Chamadas autenticadas a `/accounts/{conta}/…`, conferindo `success`."""

    def __init__(self, conta: str, token: str | Credencial, *, base: str = API, tentativas: int = TENTATIVAS,
                 timeout: float = TIMEOUT, dormir: Callable[[float], Any] = time.sleep,
                 ritmo: Ritmo | None = None) -> None:
        if not conta or not token:
            raise ValueError("conta e token são obrigatórios")
        self.conta = conta
        self.base = base.rstrip("/")
        self.tentativas = tentativas
        self.timeout = timeout
        self.dormir = dormir
        self.ritmo = ritmo
        self.credencial = token if isinstance(token, Credencial) else Credencial(token)

    def __repr__(self) -> str:
        return f"Cloudflare(conta={self.conta!r})"

    def segredos(self) -> tuple[str, ...]:
        return self.credencial.segredos()

    def url(self, caminho: str) -> str:
        return f"{self.base}/accounts/{self.conta}/{caminho.lstrip('/')}"

    def pedir(self, metodo: str, caminho: str, *, corpo: bytes | None = None,
              cabecalhos: Mapping[str, str] | None = None, aceitar: Iterable[int] = ()) -> Resposta:
        """Requisição autenticada sem interpretar o corpo; num 401, renova o token e tenta uma vez mais."""
        url = self.url(caminho)

        def enviar(token: str) -> Resposta:
            if self.ritmo is not None:
                self.ritmo.aguardar()
            cab = {**(cabecalhos or {}), "Authorization": f"Bearer {token}"}
            return requisitar(metodo, url, corpo, cab, aceitar=aceitar, tentativas=self.tentativas,
                              timeout=self.timeout, dormir=self.dormir, segredos=self.segredos())

        return com_renovacao(self.credencial, enviar)

    def chamar(self, metodo: str, caminho: str, *, json_: Any = None, corpo: bytes | None = None,
               tipo: str | None = None) -> Any:
        url = self.url(caminho)
        cab = {"Accept": "application/json"}
        if json_ is not None:
            corpo = json.dumps(json_, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            tipo = "application/json"
        if tipo:
            cab["Content-Type"] = tipo
        r = self.pedir(metodo, caminho, corpo=corpo, cabecalhos=cab)
        try:
            dados = r.json()
        except ValueError:
            raise ErroNuvem(f"{metodo} {url_segura(url)}: resposta não é JSON", r.status) from None
        if not isinstance(dados, dict) or not dados.get("success", False):
            erros = dados.get("errors") if isinstance(dados, dict) else None
            raise ErroNuvem(redigir(f"{metodo} {url_segura(url)}: sem sucesso: {json.dumps(erros)[:300]}",
                                    self.segredos()), r.status)
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


def _peso(sql: str, params: Sequence[Any]) -> int:
    return len(sql.encode("utf-8")) + sum(len(parametro_d1(p).encode("utf-8")) + 4 for p in params) + 32


def dividir_unidades(unidades: Iterable[Sequence[tuple[str, Sequence[Any]]]],
                     max_instrucoes: int = MAX_INSTRUCOES_LOTE,
                     max_bytes: int = MAX_BYTES_LOTE) -> list[list[tuple[str, Sequence[Any]]]]:
    """Grupos para requisições de lote, sem nunca dividir uma unidade (instruções que só valem juntas,
    como um trecho e a sua linha do FTS): o lote do D1 é atômico, e a unidade também fica."""
    grupos: list[list] = []
    atual: list = []
    tamanho = 0
    for unidade in unidades:
        unidade = list(unidade)
        if not unidade:
            continue
        peso = 0
        for sql, params in unidade:
            validar_instrucao(sql, params)
            peso += _peso(sql, params)
        if len(unidade) > max_instrucoes or (len(unidade) > 1 and peso > max_bytes):
            raise ValueError(f"unidade com {len(unidade)} instruções e {peso} bytes não cabe num lote do D1")
        if atual and (len(atual) + len(unidade) > max_instrucoes or tamanho + peso > max_bytes):
            grupos.append(atual)
            atual, tamanho = [], 0
        atual.extend(unidade)
        tamanho += peso
    if atual:
        grupos.append(atual)
    return grupos


def dividir_lote(instrucoes: Sequence[tuple[str, Sequence[Any]]], max_instrucoes: int = MAX_INSTRUCOES_LOTE,
                 max_bytes: int = MAX_BYTES_LOTE) -> list[list[tuple[str, Sequence[Any]]]]:
    """Grupos de instruções para requisições de lote, validando cada instrução."""
    return dividir_unidades(([i] for i in instrucoes), max_instrucoes, max_bytes)


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
        return self.lote_unidades([[i] for i in instrucoes])

    def lote_unidades(self, unidades: Iterable[Sequence[tuple[str, Sequence[Any]]]]) -> list[list[dict]]:
        """Como `lote`, mas cada unidade vai inteira numa mesma requisição (atômica)."""
        saida: list[list[dict]] = []
        for grupo in dividir_unidades(unidades, self.max_instrucoes, self.max_bytes):
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


def _mutacao(r: Any, indice: str, operacao: str) -> str:
    mutacao = r.get("mutationId") if isinstance(r, dict) else None
    if not isinstance(mutacao, str) or not mutacao:
        raise ErroNuvem(f"Vectorize {indice}: {operacao} sem mutationId na resposta")
    return mutacao


class Vectorize:
    def __init__(self, cf: Cloudflare, indice: str, *, lote: int = LOTE_VETORES, max_bytes: int = MAX_BYTES_VETORES,
                 dormir: Callable[[float], Any] = time.sleep, relogio: Callable[[], float] = time.monotonic,
                 listar_alternativo: Callable[[], list[str]] | None = None) -> None:
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
        self.listar_alternativo = listar_alternativo  # ex.: wrangler vectorize list-vectors
        self.ids_por_obter = MAX_IDS_OBTER

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
                               tipo=f"multipart/form-data; boundary={fronteira}")
            mutacoes.append(_mutacao(r, self.indice, operacao))
        return mutacoes

    def upsert(self, vetores: Iterable[Mapping[str, Any]]) -> list[str]:
        return self._enviar("upsert", vetores)

    def inserir(self, vetores: Iterable[Mapping[str, Any]]) -> list[str]:
        return self._enviar("insert", vetores)

    def apagar(self, ids: Sequence[str]) -> list[str]:
        mutacoes = []
        for i in range(0, len(ids), MAX_IDS_APAGAR):
            r = self.cf.chamar("POST", self._caminho("delete_by_ids"), json_={"ids": list(ids[i:i + MAX_IDS_APAGAR])})
            mutacoes.append(_mutacao(r, self.indice, "delete_by_ids"))
        return mutacoes

    def obter(self, ids: Sequence[str]) -> list[dict]:
        """Vetores com valores e metadados, em lotes de 100 (20 se o índice recusar com 400)."""
        saida: list[dict] = []
        i = 0
        while i < len(ids):
            bloco = list(ids[i:i + self.ids_por_obter])
            try:
                r = self.cf.chamar("POST", self._caminho("get_by_ids"), json_={"ids": bloco})
            except ErroNuvem as e:
                if e.status == 400 and self.ids_por_obter > MIN_IDS_OBTER:
                    self.ids_por_obter = MIN_IDS_OBTER
                    continue
                raise
            saida.extend(r or [])
            i += len(bloco)
        return saida

    def listar_ids(self) -> list[str]:
        """Todos os ids do índice (`GET …/list?count=1000&cursor=…`); sem a rota, `listar_alternativo`."""
        ids: list[str] = []
        cursor = None
        while True:
            consulta = f"count={LOTE_VETORES}" + (f"&cursor={urllib.parse.quote(cursor, safe='')}" if cursor else "")
            try:
                r = self.cf.chamar("GET", self._caminho("list") + "?" + consulta) or {}
            except ErroNuvem as e:
                if self.listar_alternativo is not None and not ids and e.status in (400, 404, 405, 501):
                    return list(self.listar_alternativo())
                raise
            for item in r.get("vectors") or []:
                ident = item.get("id") if isinstance(item, dict) else item
                if isinstance(ident, str):
                    ids.append(ident)
            cursor = r.get("nextCursor")
            if not (r.get("isTruncated") and cursor):
                return ids

    def indices_metadados(self) -> dict[str, str]:
        """Índices de metadados do índice: nome da propriedade -> tipo (minúsculas)."""
        r = self.cf.chamar("GET", self._caminho("metadata_index/list")) or {}
        return {str(i.get("propertyName")): str(i.get("indexType") or "").lower()
                for i in r.get("metadataIndexes") or [] if isinstance(i, dict)}

    def info(self) -> dict:
        return self.cf.chamar("GET", self._caminho("info")) or {}

    def esperar(self, mutacao: str | None, timeout: float = 1800.0, intervalo: float = 5.0,
                desde: datetime | None = None) -> dict:
        """Espera `processedUpToMutation` = `mutacao` e, com `desde`, `processedUpToDatetime` ≥ `desde`.

        ErroNuvem ao fim do prazo (padrão: 1.800 s).
        """
        limite = self.relogio() + timeout
        while True:
            info = self.info()
            mutacao_ok = mutacao is None or info.get("processedUpToMutation") == mutacao
            processado = data_iso(info.get("processedUpToDatetime"))
            data_ok = desde is None or (processado is not None and processado >= desde)
            if mutacao_ok and data_ok:
                return info
            if self.relogio() >= limite:
                raise ErroNuvem(f"Vectorize {self.indice}: mutações ainda não processadas após {timeout:.0f} s")
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
        """Um vetor por texto, em lotes de até `lote` textos e `MAX_CARACTERES_EMBEDDINGS` caracteres;
        ErroNuvem se a quantidade ou a dimensão não baterem."""
        saida: list[list[float]] = []
        bloco: list[str] = []
        tamanho = 0
        for texto in textos:
            if bloco and (len(bloco) >= self.lote or tamanho + len(texto) > MAX_CARACTERES_EMBEDDINGS):
                saida.extend(self._bloco(bloco))
                bloco, tamanho = [], 0
            bloco.append(texto)
            tamanho += len(texto)
        if bloco:
            saida.extend(self._bloco(bloco))
        return saida

    def _bloco(self, bloco: list[str]) -> list[list[float]]:
        try:
            r = self.cf.chamar("POST", f"ai/run/{self.modelo}", json_={"text": bloco}) or {}
        except ErroNuvem as e:
            # o modelo limita o contexto somado do lote (em tokens, que o OCR ruidoso infla): divide e repete
            if len(bloco) > 1 and e.status == 400 and "context" in str(e).lower():
                meio = len(bloco) // 2
                return self._bloco(bloco[:meio]) + self._bloco(bloco[meio:])
            raise
        self.chamadas += 1
        dados = r.get("data") if isinstance(r, dict) else None
        if not isinstance(dados, list) or len(dados) != len(bloco):
            raise ErroNuvem(f"Workers AI {self.modelo}: esperados {len(bloco)} vetores")
        saida: list[list[float]] = []
        for vetor in dados:
            if not isinstance(vetor, list) or len(vetor) != self.dimensoes:
                tamanho = len(vetor) if isinstance(vetor, list) else "?"
                raise ErroNuvem(f"Workers AI {self.modelo}: vetor com {tamanho} dimensões "
                                f"(esperadas {self.dimensoes})")
            saida.append([float(v) for v in vetor])
        return saida

    __call__ = embeddings
