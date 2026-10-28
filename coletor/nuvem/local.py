"""Simulações locais do R2 e do Vectorize, embeddings falsos e cache de embeddings.

No ambiente `local`, o R2 é a pasta `<dir>/r2/<bucket>/<chave>`, o Vectorize é o
arquivo `<dir>/vetores.jsonl` (um vetor por linha, valores em float32 little-endian
codificados em base64) e os embeddings vêm de `embeddings_falsos`: determinísticos,
derivados do SHAKE-256 do texto, com 1.024 dimensões e norma 1. Nada disso acessa a
rede.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import math
import os
import struct
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from coletor.arquivos import gravar_atomico
from coletor.nuvem.cloudflare import DIMENSOES

MODELO_LOCAL = "local:shake256-1024"


def empacotar(valores: Sequence[float]) -> str:
    """float32 little-endian em base64."""
    return base64.b64encode(struct.pack(f"<{len(valores)}f", *valores)).decode("ascii")


def desempacotar(texto: str) -> list[float]:
    dados = base64.b64decode(texto)
    return list(struct.unpack(f"<{len(dados) // 4}f", dados))


def como_float32(valores: Sequence[float]) -> list[float]:
    return list(struct.unpack(f"<{len(valores)}f", struct.pack(f"<{len(valores)}f", *valores)))


def embeddings_falsos(textos: Sequence[str], dimensoes: int = DIMENSOES) -> list[list[float]]:
    """Vetores determinísticos (SHAKE-256 do texto), normalizados e já em float32."""
    saida = []
    for texto in textos:
        bruto = hashlib.shake_256(texto.encode("utf-8")).digest(4 * dimensoes)
        inteiros = struct.unpack(f"<{dimensoes}i", bruto)
        valores = [x / 2147483648.0 for x in inteiros]
        norma = math.sqrt(sum(v * v for v in valores)) or 1.0
        saida.append(como_float32([v / norma for v in valores]))
    return saida


def _gravar_bytes(caminho: Path, dados: bytes) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fd, temporario = tempfile.mkstemp(dir=caminho.parent, prefix=f".{caminho.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(dados)
        os.replace(temporario, caminho)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporario)
        raise


class R2Local:
    """Buckets como pastas: `<raiz>/<bucket>/<chave>`; `If-None-Match: *` simulado."""

    def __init__(self, raiz: str | os.PathLike) -> None:
        self.raiz = Path(raiz)

    def _caminho(self, bucket: str, chave: str) -> Path:
        partes = [bucket, *chave.split("/")]
        if any(p in ("", ".", "..") for p in partes):
            raise ValueError(f"chave inválida: {bucket}/{chave}")
        return self.raiz.joinpath(*partes)

    def enviar(self, bucket: str, chave: str, dados: bytes, tipo: str = "application/octet-stream",
               metadados: Mapping[str, str] | None = None, se_ausente: bool = True) -> bool:
        caminho = self._caminho(bucket, chave)
        if se_ausente and caminho.exists():
            return False
        _gravar_bytes(caminho, dados)
        return True

    def existe(self, bucket: str, chave: str) -> bool:
        return self._caminho(bucket, chave).is_file()

    def obter(self, bucket: str, chave: str) -> bytes | None:
        caminho = self._caminho(bucket, chave)
        return caminho.read_bytes() if caminho.is_file() else None

    def apagar(self, bucket: str, chave: str) -> None:
        with contextlib.suppress(FileNotFoundError):
            self._caminho(bucket, chave).unlink()

    def listar(self, bucket: str, prefixo: str = "") -> list[str]:
        base = self.raiz / bucket
        if not base.is_dir():
            return []
        chaves = (p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file())
        return sorted(c for c in chaves if c.startswith(prefixo) and not c.rsplit("/", 1)[-1].startswith("."))


class VetoresLocal:
    """Índice de vetores num JSONL ordenado por id; mutações síncronas."""

    def __init__(self, caminho: str | os.PathLike) -> None:
        self.caminho = Path(caminho)
        self._dados: dict[str, dict] | None = None
        self._mutacoes = 0

    def _carregar(self) -> dict[str, dict]:
        if self._dados is None:
            self._dados = {}
            if self.caminho.exists():
                for linha in self.caminho.read_text(encoding="utf-8").splitlines():
                    if linha.strip():
                        obj = json.loads(linha)
                        self._dados[obj["id"]] = obj
        return self._dados

    def _gravar(self) -> str:
        dados = self._carregar()
        texto = "".join(json.dumps(dados[i], ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
                        for i in sorted(dados))
        gravar_atomico(self.caminho, texto)
        self._mutacoes += 1
        return f"local-{self._mutacoes}"

    def upsert(self, vetores: Iterable[Mapping[str, Any]]) -> list[str]:
        dados = self._carregar()
        for v in vetores:
            dados[v["id"]] = {"id": v["id"], "metadata": dict(v.get("metadata") or {}),
                              "values": empacotar(v["values"])}
        return [self._gravar()]

    def apagar(self, ids: Sequence[str]) -> list[str]:
        dados = self._carregar()
        for i in ids:
            dados.pop(i, None)
        return [self._gravar()]

    def obter(self, ids: Sequence[str]) -> list[dict]:
        dados = self._carregar()
        return [{"id": i, "metadata": dados[i]["metadata"], "values": desempacotar(dados[i]["values"])}
                for i in ids if i in dados]

    def esperar(self, mutacao: str | None) -> dict:
        return {"processedUpToMutation": mutacao, "vectorCount": len(self._carregar())}

    def ids(self) -> list[str]:
        return sorted(self._carregar())


class CacheEmbeddings:
    """Vetores já calculados, por modelo e SHA-256 do texto: `<pasta>/<modelo>/<aa>/<sha>.f32`."""

    def __init__(self, pasta: str | os.PathLike, modelo: str) -> None:
        nome = "".join(c if c.isalnum() or c in "-_." else "_" for c in modelo)
        self.pasta = Path(pasta) / nome

    def _caminho(self, sha: str) -> Path:
        return self.pasta / sha[:2] / f"{sha}.f32"

    def obter(self, sha: str) -> list[float] | None:
        caminho = self._caminho(sha)
        if not caminho.is_file():
            return None
        dados = caminho.read_bytes()
        return list(struct.unpack(f"<{len(dados) // 4}f", dados))

    def guardar(self, sha: str, valores: Sequence[float]) -> None:
        _gravar_bytes(self._caminho(sha), struct.pack(f"<{len(valores)}f", *valores))
