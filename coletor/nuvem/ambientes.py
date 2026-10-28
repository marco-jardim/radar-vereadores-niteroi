"""Montagem dos ambientes `local`, `staging` e `production`.

Os nomes e ids de D1, Vectorize e buckets vêm de `worker/wrangler.jsonc` (produção no
nível superior, staging em `env.staging`). Credenciais só por variáveis de ambiente:
`CLOUDFLARE_API_TOKEN` (ou `CLOUDFLARE_API_TOKEN_DADOS`), `CLOUDFLARE_ACCOUNT_ID`
(padrão: `account_id` do wrangler), `R2_ACCESS_KEY_ID` e `R2_SECRET_ACCESS_KEY`.
"""
from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from pathlib import Path

from coletor.nuvem.banco import PASTA_MIGRACOES, PASTA_WORKER, BancoLocal, BancoRemoto
from coletor.nuvem.cloudflare import D1, MODELO, Cloudflare, Vectorize, WorkersAI, token_do_ambiente
from coletor.nuvem.local import MODELO_LOCAL, CacheEmbeddings, R2Local, VetoresLocal, embeddings_falsos
from coletor.nuvem.r2 import R2
from coletor.nuvem.rede import ErroNuvem
from coletor.nuvem.sincronizar import Ambiente

AMBIENTES = ("local", "staging", "production")
BUCKET_ARQUIVOS_LOCAL = "radar-niteroi-arquivos"
BUCKET_EXPORTACOES_LOCAL = "radar-niteroi-exportacoes"


def sem_comentarios(texto: str) -> str:
    """JSONC -> JSON: tira comentários `//` e `/* */` fora de strings e vírgulas finais."""
    saida: list[str] = []
    i, n = 0, len(texto)
    em_texto = False
    while i < n:
        c = texto[i]
        if em_texto:
            saida.append(c)
            if c == "\\" and i + 1 < n:
                saida.append(texto[i + 1])
                i += 2
                continue
            if c == '"':
                em_texto = False
            i += 1
            continue
        if c == '"':
            em_texto = True
            saida.append(c)
            i += 1
        elif texto.startswith("//", i):
            fim = texto.find("\n", i)
            i = n if fim < 0 else fim
        elif texto.startswith("/*", i):
            fim = texto.find("*/", i + 2)
            i = n if fim < 0 else fim + 2
        else:
            saida.append(c)
            i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(saida))


def config_wrangler(ambiente: str, caminho: Path = PASTA_WORKER / "wrangler.jsonc") -> dict:
    cfg = json.loads(sem_comentarios(Path(caminho).read_text(encoding="utf-8")))
    bloco = cfg if ambiente == "production" else cfg["env"]["staging"]
    banco = bloco["d1_databases"][0]
    buckets = {b["binding"]: b["bucket_name"] for b in bloco["r2_buckets"]}
    return {
        "conta": cfg.get("account_id"),
        "banco": banco["database_name"],
        "banco_id": banco["database_id"],
        "indice": bloco["vectorize"][0]["index_name"],
        "arquivos": buckets["ARQUIVOS"],
        "exportacoes": buckets["EXPORTACOES"],
        "env": None if ambiente == "production" else "staging",
    }


def ambiente_local(sqlite: str | os.PathLike, *, somente_leitura: bool = False,
                   pasta_migracoes: Path = PASTA_MIGRACOES) -> Ambiente:
    """SQLite no lugar do D1; `<dir>/r2/` e `<dir>/vetores.jsonl`, com `<dir>` a pasta do SQLite."""
    sqlite = Path(sqlite)
    pasta = sqlite.resolve().parent
    return Ambiente("local", BancoLocal(sqlite, somente_leitura=somente_leitura), R2Local(pasta / "r2"),
                    BUCKET_ARQUIVOS_LOCAL, BUCKET_EXPORTACOES_LOCAL, VetoresLocal(pasta / "vetores.jsonl"),
                    embeddings_falsos, MODELO_LOCAL, pasta_migracoes=pasta_migracoes)


def ambiente_remoto(nome: str, cache: Path, env: Mapping[str, str] = os.environ) -> Ambiente:
    if nome not in ("staging", "production"):
        raise ValueError(nome)
    cfg = config_wrangler(nome)
    token = token_do_ambiente(env)
    conta = env.get("CLOUDFLARE_ACCOUNT_ID") or cfg["conta"]
    if not conta:
        raise ErroNuvem("defina CLOUDFLARE_ACCOUNT_ID")
    cf = Cloudflare(conta, token)
    banco = BancoRemoto(D1(cf, cfg["banco_id"]), cfg["banco"], ambiente_wrangler=cfg["env"],
                        segredos=(token, env.get("R2_SECRET_ACCESS_KEY") or ""),
                        env_extra={"CLOUDFLARE_API_TOKEN": token, "CLOUDFLARE_ACCOUNT_ID": conta})
    r2 = R2.do_ambiente(conta, env)
    return Ambiente(nome, banco, r2, cfg["arquivos"], cfg["exportacoes"], Vectorize(cf, cfg["indice"]),
                    WorkersAI(cf).embeddings, MODELO, cache_embeddings=CacheEmbeddings(cache / "embeddings", MODELO))
