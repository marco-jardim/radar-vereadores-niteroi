"""Execução do wrangler em versão fixada: migrações e cargas grandes do D1, lista de vetores e login.

`worker/package.json` fixa a versão exata (`VERSAO_WRANGLER`). Com o pacote instalado em
`worker/node_modules` (`npm ci` em `worker/`), o comando é `npx --no-install wrangler`; sem ele,
`npx --yes wrangler@<VERSAO_WRANGLER>`. No Windows, `npx.cmd` é procurado antes de `npx`.
Cada execução tem prazo (`TIMEOUT_WRANGLER`, 900 s), recebe uma lista de argumentos (sem shell)
e, em falha, a saída vai redigida, sem tokens.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from coletor.nuvem.rede import ErroNuvem, redigir

RAIZ = Path(__file__).resolve().parents[2]
PASTA_WORKER = RAIZ / "worker"
VERSAO_WRANGLER = "4.154.0"  # igual a worker/package.json (conferido nos testes)
TIMEOUT_WRANGLER = 900.0
TIMEOUT_WHOAMI = 120.0
LISTA_VETORES = 1000


def npx(sistema: str = os.name, procurar: Callable[[str], str | None] = shutil.which) -> str:
    """Caminho do npx; no Windows, `npx.cmd` primeiro (o `npx` sem extensão é um script de shell)."""
    nomes = ("npx.cmd", "npx") if sistema == "nt" else ("npx", "npx.cmd")
    for nome in nomes:
        caminho = procurar(nome)
        if caminho:
            return caminho
    raise ErroNuvem("npx não encontrado no PATH (necessário para o wrangler)")


def prefixo(pasta_worker: Path = PASTA_WORKER, comando_npx: str | None = None) -> list[str]:
    """`[npx, --no-install, wrangler]` com o pacote instalado; senão `[npx, --yes, wrangler@<versão>]`."""
    exe = comando_npx or npx()
    if (Path(pasta_worker) / "node_modules" / "wrangler").is_dir():
        return [exe, "--no-install", "wrangler"]
    return [exe, "--yes", f"wrangler@{VERSAO_WRANGLER}"]


class Wrangler:
    """Executa `wrangler <args>` em `worker/`, com prazo, sem shell e com a saída redigida nos erros."""

    def __init__(self, pasta_worker: Path = PASTA_WORKER, *, comando_npx: str | None = None,
                 env_extra: Mapping[str, str] | None = None, remover_env: Iterable[str] = (),
                 executor: Callable[..., Any] = subprocess.run, timeout: float = TIMEOUT_WRANGLER,
                 segredos: Callable[[], Iterable[str]] | Iterable[str] = ()) -> None:
        self.pasta_worker = Path(pasta_worker)
        self.comando_npx = comando_npx
        self.env_extra = dict(env_extra or {})
        self.remover_env = tuple(remover_env)
        self.executor = executor
        self.timeout = timeout
        self._segredos = segredos
        self.comandos: list[list[str]] = []

    def segredos(self) -> tuple[str, ...]:
        fonte = self._segredos() if callable(self._segredos) else self._segredos
        return tuple(s for s in fonte if s)

    def executar(self, *args: str, ci: bool = True, timeout: float | None = None) -> str:
        """Saída padrão do comando; ErroNuvem em código diferente de zero, prazo esgotado ou npx ausente."""
        comando = [*prefixo(self.pasta_worker, self.comando_npx), *args]
        self.comandos.append(comando)
        env = {**os.environ, **self.env_extra}
        for nome in self.remover_env:
            env.pop(nome, None)
        if ci:
            env["CI"] = "true"  # sem perguntas interativas
        prazo = self.timeout if timeout is None else timeout
        rotulo = " ".join(args[:3])
        try:
            r = self.executor(comando, cwd=str(self.pasta_worker), env=env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=prazo)
        except subprocess.TimeoutExpired:
            raise ErroNuvem(f"wrangler {rotulo}: sem resposta em {prazo:.0f} s") from None
        except OSError as e:
            raise ErroNuvem(f"wrangler {rotulo}: não foi possível executar ({type(e).__name__})") from None
        if getattr(r, "returncode", 1) != 0:
            saida = redigir(((getattr(r, "stderr", "") or "") + (getattr(r, "stdout", "") or ""))[-800:],
                            self.segredos())
            raise ErroNuvem(f"wrangler {rotulo} falhou ({r.returncode}): {saida}")
        return getattr(r, "stdout", "") or ""


def json_da_saida(saida: str) -> Any:
    """Primeiro valor JSON da saída do wrangler (pode haver um aviso antes)."""
    inicios = [i for i in (saida.find("{"), saida.find("[")) if i >= 0]
    if not inicios:
        raise ErroNuvem("wrangler: saída sem JSON")
    try:
        valor, _ = json.JSONDecoder().raw_decode(saida[min(inicios):])
    except ValueError:
        raise ErroNuvem("wrangler: JSON inválido na saída") from None
    return valor


def listar_vetores(wrangler: Wrangler, indice: str) -> list[str]:
    """Todos os ids do índice por `wrangler vectorize list-vectors <índice> --json` (com cursor)."""
    ids: list[str] = []
    cursor = None
    while True:
        args = ["vectorize", "list-vectors", indice, "--count", str(LISTA_VETORES), "--json"]
        if cursor:
            args += ["--cursor", cursor]
        dados = json_da_saida(wrangler.executar(*args))
        itens = dados.get("vectors") if isinstance(dados, dict) else dados
        for item in itens or []:
            ident = item.get("id") if isinstance(item, dict) else item
            if isinstance(ident, str):
                ids.append(ident)
        cursor = dados.get("nextCursor") if isinstance(dados, dict) else None
        if not (isinstance(dados, dict) and dados.get("isTruncated") and cursor):
            return ids
