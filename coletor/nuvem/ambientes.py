"""Montagem dos ambientes `local`, `staging` e `production`.

Os nomes e ids de D1, Vectorize e buckets vêm de `worker/wrangler.jsonc` (produção no
nível superior, staging em `env.staging`). Credenciais:

- token da API: `CLOUDFLARE_API_TOKEN` (ou `CLOUDFLARE_API_TOKEN_DADOS`); sem eles, o login
  OAuth do wrangler (`coletor.nuvem.credenciais`), renovado com `wrangler whoami`. Com o login
  OAuth, os subprocessos do wrangler **não** recebem `CLOUDFLARE_API_TOKEN` e usam o próprio login;
- conta: `CLOUDFLARE_ACCOUNT_ID` (padrão: `account_id` do wrangler);
- R2: com `R2_ACCESS_KEY_ID` e `R2_SECRET_ACCESS_KEY`, a via S3 (`R2`, SigV4); sem elas, a API
  REST com o token Bearer (`R2Rest`). `sem_r2=True` dispensa o R2.

Todas as chamadas à API do Cloudflare de um ambiente remoto compartilham um `Ritmo` de 4
requisições por segundo (limite global de 1.200 a cada 5 minutos).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from coletor.nuvem.banco import PASTA_MIGRACOES, PASTA_WORKER, BancoLocal, BancoRemoto
from coletor.nuvem.cloudflare import D1, MODELO, Cloudflare, Vectorize, WorkersAI
from coletor.nuvem.credenciais import VARIAVEIS_TOKEN, Credencial, credencial_do_ambiente
from coletor.nuvem.local import MODELO_LOCAL, CacheEmbeddings, R2Local, VetoresLocal, embeddings_falsos
from coletor.nuvem.r2 import R2, R2Rest
from coletor.nuvem.rede import ErroNuvem, Ritmo
from coletor.nuvem.sincronizar import Ambiente
from coletor.nuvem.wrangler import TIMEOUT_WHOAMI, Wrangler, listar_vetores

REQUISICOES_POR_SEGUNDO = 4.0

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


def credencial_remota(env: Mapping[str, str] = os.environ, *, pasta_worker: Path = PASTA_WORKER,
                      executar: Callable[..., Any] = subprocess.run, comando_npx: str | None = None) -> Credencial:
    """Token das variáveis de ambiente ou login OAuth do wrangler, renovado por `wrangler whoami`."""

    def whoami() -> None:
        # sem CLOUDFLARE_API_TOKEN: o wrangler usa (e renova) o próprio login OAuth; a saída não é mostrada
        Wrangler(pasta_worker, comando_npx=comando_npx, executor=executar, remover_env=VARIAVEIS_TOKEN).executar(
            "whoami", ci=False, timeout=TIMEOUT_WHOAMI)

    return credencial_do_ambiente(env, executar_whoami=whoami)


def ambiente_remoto(nome: str, cache: Path, env: Mapping[str, str] = os.environ, *, sem_r2: bool = False,
                    pasta_worker: Path = PASTA_WORKER, executar: Callable[..., Any] = subprocess.run,
                    ritmo: Ritmo | None = None, comando_npx: str | None = None) -> Ambiente:
    if nome not in ("staging", "production"):
        raise ValueError(nome)
    cfg = config_wrangler(nome, Path(pasta_worker) / "wrangler.jsonc")
    credencial = credencial_remota(env, pasta_worker=pasta_worker, executar=executar, comando_npx=comando_npx)
    conta = env.get("CLOUDFLARE_ACCOUNT_ID") or cfg["conta"]
    if not conta:
        raise ErroNuvem("defina CLOUDFLARE_ACCOUNT_ID")
    cf = Cloudflare(conta, credencial, ritmo=ritmo or Ritmo(REQUISICOES_POR_SEGUNDO))
    env_extra = {"CLOUDFLARE_ACCOUNT_ID": conta}
    remover: tuple[str, ...] = ()
    if credencial.oauth:
        remover = ("CLOUDFLARE_API_TOKEN",)  # o wrangler usa o próprio login OAuth
    else:
        env_extra["CLOUDFLARE_API_TOKEN"] = credencial.token()
    banco = BancoRemoto(D1(cf, cfg["banco_id"]), cfg["banco"], ambiente_wrangler=cfg["env"],
                        segredos=(env.get("R2_SECRET_ACCESS_KEY") or "",), credencial=credencial,
                        env_extra=env_extra, remover_env=remover, pasta_worker=pasta_worker, executar=executar,
                        comando_npx=comando_npx)
    if sem_r2:
        r2 = None
    elif env.get("R2_ACCESS_KEY_ID") and env.get("R2_SECRET_ACCESS_KEY"):
        r2 = R2.do_ambiente(conta, env)
    else:
        r2 = R2Rest(cf)
    vetores = Vectorize(cf, cfg["indice"], listar_alternativo=lambda: listar_vetores(banco.wrangler, cfg["indice"]))
    return Ambiente(nome, banco, r2, cfg["arquivos"], cfg["exportacoes"], vetores,
                    WorkersAI(cf).embeddings, MODELO, cache_embeddings=CacheEmbeddings(cache / "embeddings", MODELO))
