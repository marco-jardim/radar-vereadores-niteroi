"""Tabelas do D1, montagem de instruções e os dois bancos: SQLite local e D1 remoto.

As alterações são descritas em `Alteracao` (apagar chaves, gravar linhas, limpar a
tabela) e viram instruções conforme o destino:

- modo `parametros`: até 100 parâmetros por instrução, NULL embutido, `CAST(? AS
  INTEGER)` no `rowid` do FTS (o D1 recebe parâmetros como texto). Usado no SQLite
  local e nos lotes REST do D1;
- modo `literal`: valores embutidos, até 100.000 bytes por instrução. Usado nos
  arquivos `.sql` aplicados com `npx wrangler d1 execute <db> --remote --file`
  (cargas grandes).

Migrações: a pasta única `worker/migrations/`; localmente, aplicadas pelo `sqlite3`
com a mesma tabela `d1_migrations` do wrangler; no D1, por
`npx wrangler d1 migrations apply <db> --remote`.
"""
from __future__ import annotations

import math
import os
import shutil
import sqlite3
import subprocess
import tempfile
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from coletor.nuvem.cloudflare import D1, MAX_BYTES_INSTRUCAO, MAX_PARAMETROS
from coletor.nuvem.rede import ErroNuvem, redigir

RAIZ = Path(__file__).resolve().parents[2]
PASTA_MIGRACOES = RAIZ / "worker" / "migrations"
PASTA_WORKER = RAIZ / "worker"

# tabela -> (colunas, chave primária); contrato, seção 8.1
COLUNAS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "documentos": (("id", "tipo", "numero", "ano", "data", "ementa", "url", "legislatura", "pl"), ("id",)),
    "autoria": (("documento", "slug", "papel"), ("documento", "slug", "papel")),
    "pessoas": (("slug", "nome", "partido_atual"), ("slug",)),
    "arquivos": (("id", "sha256", "formato", "status", "ocr", "confianca", "r2_chave"), ("id",)),
    "arquivo_documento": (("arquivo", "documento"), ("arquivo", "documento")),
    "trechos": (("id", "documento", "arquivo", "posicao", "texto", "sha256"), ("id",)),
    "remocoes": (("chave", "sha256", "motivo", "data"), ("chave", "sha256")),
    "trechos_indexados": (("id", "sha256"), ("id",)),
    "estado_indice": (("id", "versao", "commit", "sha256_manifestos", "total", "sha256_conjunto", "modelo",
                       "versao_trechos", "data"), ("id",)),
    "verificacoes": (("data", "amostra", "ok", "falhas_json"), ("data",)),
}
FTS = "trechos_fts"
COLUNAS_FTS = ("rowid", "id", "texto_norm")
# tabelas-base sincronizadas a partir do Git (estado_indice à parte; verificacoes é do Worker)
TABELAS_BASE = ("documentos", "autoria", "pessoas", "arquivos", "arquivo_documento", "trechos", "remocoes",
                "trechos_indexados")
# colunas comparadas na diferença (o texto do trecho é determinado pelo sha256, que entra no id)
COMPARAR = {"trechos": ("id", "documento", "arquivo", "posicao", "sha256")}
LIMIAR_ARQUIVO = 400  # acima disto, a carga no D1 remoto vai por arquivo .sql e wrangler
LINHAS_POR_INSTRUCAO = 500


@dataclass
class Alteracao:
    tabela: str
    colunas: tuple[str, ...] = ()
    chave: tuple[str, ...] = ()
    gravar: list[tuple] = field(default_factory=list)
    apagar: list[tuple] = field(default_factory=list)
    limpar: bool = False
    substituir: bool = True  # INSERT OR REPLACE (FTS: INSERT simples, depois de apagar)

    @classmethod
    def de(cls, tabela: str, gravar: Iterable[tuple] = (), apagar: Iterable[tuple] = (), limpar: bool = False):
        if tabela == FTS:
            return cls(FTS, COLUNAS_FTS, ("rowid",), list(gravar), list(apagar), limpar, substituir=False)
        colunas, chave = COLUNAS[tabela]
        return cls(tabela, colunas, chave, list(gravar), list(apagar), limpar)

    def vazia(self) -> bool:
        return not (self.gravar or self.apagar or self.limpar)


# ---------------------------------------------------------------- instruções
def q(nome: str) -> str:
    """Identificador entre aspas (`commit` é palavra reservada)."""
    if nome == "rowid":
        return "rowid"
    return '"' + nome.replace('"', '""') + '"'


def literal(valor: Any) -> str:
    if valor is None:
        return "NULL"
    if isinstance(valor, bool):
        return "1" if valor else "0"
    if isinstance(valor, int):
        return str(valor)
    if isinstance(valor, float):
        if not math.isfinite(valor):
            raise ValueError("número não finito")
        return repr(valor)
    if isinstance(valor, str):
        if "\x00" in valor:
            raise ValueError("texto com caractere NUL")
        return "'" + valor.replace("'", "''") + "'"
    raise TypeError(f"tipo não suportado: {type(valor).__name__}")


def _marcador(coluna: str, valor: Any, modo: str) -> tuple[str, list]:
    if modo == "literal" or valor is None:
        return literal(valor), []
    return ("CAST(? AS INTEGER)" if coluna == "rowid" else "?"), [valor]


def _agrupar(cabeca: str, itens: Iterable[tuple[str, list]], fim: str, max_parametros: int, max_bytes: int,
             max_linhas: int, tabela: str) -> list[tuple[str, tuple]]:
    saida: list[tuple[str, tuple]] = []
    partes: list[str] = []
    params: list = []
    base = len(cabeca.encode("utf-8")) + len(fim.encode("utf-8"))
    tamanho = base
    for texto, p in itens:
        peso = len(texto.encode("utf-8")) + 2
        if base + peso > max_bytes or len(p) > max_parametros:
            raise ValueError(f"{tabela}: linha grande demais para uma instrução do D1")
        if partes and (len(params) + len(p) > max_parametros or tamanho + peso > max_bytes
                       or len(partes) >= max_linhas):
            saida.append((cabeca + ", ".join(partes) + fim, tuple(params)))
            partes, params, tamanho = [], [], base
        partes.append(texto)
        params.extend(p)
        tamanho += peso
    if partes:
        saida.append((cabeca + ", ".join(partes) + fim, tuple(params)))
    return saida


def instrucoes_gravar(tabela: str, colunas: Sequence[str], linhas: Iterable[Sequence[Any]], *,
                      modo: str = "parametros", substituir: bool = True, max_parametros: int = MAX_PARAMETROS,
                      max_bytes: int = MAX_BYTES_INSTRUCAO, max_linhas: int = LINHAS_POR_INSTRUCAO
                      ) -> list[tuple[str, tuple]]:
    verbo = "INSERT OR REPLACE INTO" if substituir else "INSERT INTO"
    cabeca = f"{verbo} {q(tabela)} ({', '.join(q(c) for c in colunas)}) VALUES "

    def itens():
        for linha in linhas:
            if len(linha) != len(colunas):
                raise ValueError(f"{tabela}: linha com {len(linha)} valores para {len(colunas)} colunas")
            textos, params = [], []
            for coluna, valor in zip(colunas, linha):
                t, p = _marcador(coluna, valor, modo)
                textos.append(t)
                params.extend(p)
            yield "(" + ", ".join(textos) + ")", params

    return _agrupar(cabeca, itens(), ";", max_parametros, max_bytes, max_linhas, tabela)


def instrucoes_apagar(tabela: str, chave: Sequence[str], chaves: Iterable[Sequence[Any]], *,
                      modo: str = "parametros", max_parametros: int = MAX_PARAMETROS,
                      max_bytes: int = MAX_BYTES_INSTRUCAO, max_linhas: int = LINHAS_POR_INSTRUCAO
                      ) -> list[tuple[str, tuple]]:
    if len(chave) == 1:
        cabeca = f"DELETE FROM {q(tabela)} WHERE {q(chave[0])} IN ("
    else:
        cabeca = f"DELETE FROM {q(tabela)} WHERE ({', '.join(q(c) for c in chave)}) IN (VALUES "

    def itens():
        for valores in chaves:
            textos, params = [], []
            for coluna, valor in zip(chave, valores):
                if valor is None:
                    raise ValueError(f"{tabela}: chave nula")
                t, p = _marcador(coluna, valor, modo)
                textos.append(t)
                params.extend(p)
            yield (textos[0] if len(chave) == 1 else "(" + ", ".join(textos) + ")"), params

    return _agrupar(cabeca, itens(), ");", max_parametros, max_bytes, max_linhas, tabela)


def instrucoes(alteracoes: Iterable[Alteracao], modo: str = "parametros") -> list[tuple[str, tuple]]:
    """Instruções na ordem das alterações; em cada uma, limpar, apagar e depois gravar."""
    saida: list[tuple[str, tuple]] = []
    for a in alteracoes:
        if a.limpar:
            saida.append((f"DELETE FROM {q(a.tabela)};", ()))
        if a.apagar:
            saida.extend(instrucoes_apagar(a.tabela, a.chave, a.apagar, modo=modo))
        if a.gravar:
            saida.extend(instrucoes_gravar(a.tabela, a.colunas, a.gravar, modo=modo, substituir=a.substituir))
    return saida


def nomes_migracoes(pasta: Path = PASTA_MIGRACOES) -> list[str]:
    return sorted(p.name for p in Path(pasta).glob("*.sql"))


# ---------------------------------------------------------------- SQLite local
class BancoLocal:
    """SQLite no lugar do D1 (testes e conferência local). `somente_leitura` nunca cria nem altera o arquivo."""

    pagina: int | None = None

    def __init__(self, caminho: str | os.PathLike, *, somente_leitura: bool = False) -> None:
        self.caminho = Path(caminho)
        self.somente_leitura = somente_leitura
        self._conexao: sqlite3.Connection | None = None

    @property
    def conexao(self) -> sqlite3.Connection | None:
        """Aberta no primeiro uso: nada é criado antes de a sincronização passar pela barreira."""
        if self._conexao is None:
            if self.somente_leitura:
                if not self.caminho.exists():
                    return None
                self._conexao = sqlite3.connect(self.caminho.resolve().as_uri() + "?mode=ro", uri=True,
                                                isolation_level=None)
            else:
                self.caminho.parent.mkdir(parents=True, exist_ok=True)
                self._conexao = sqlite3.connect(self.caminho, isolation_level=None)
            self._conexao.row_factory = sqlite3.Row
        return self._conexao

    def fechar(self) -> None:
        if self._conexao is not None:
            self._conexao.close()
            self._conexao = None

    def consultar(self, sql: str, params: Sequence[Any] = ()) -> list[dict]:
        conexao = self.conexao
        if conexao is None:
            return []
        return [dict(r) for r in conexao.execute(sql, tuple(params)).fetchall()]

    def tabelas(self) -> set[str]:
        return {r["name"] for r in self.consultar("SELECT name FROM sqlite_master WHERE type = 'table'")}

    def migracoes_aplicadas(self) -> set[str]:
        if "d1_migrations" not in self.tabelas():
            return set()
        return {r["name"] for r in self.consultar("SELECT name FROM d1_migrations")}

    def pendentes(self, pasta: Path = PASTA_MIGRACOES) -> list[str]:
        aplicadas = self.migracoes_aplicadas()
        return [n for n in nomes_migracoes(pasta) if n not in aplicadas]

    def migrar(self, pasta: Path = PASTA_MIGRACOES) -> list[str]:
        if self.somente_leitura:
            raise RuntimeError("banco aberto só para leitura")
        self.conexao.execute(
            "CREATE TABLE IF NOT EXISTS d1_migrations (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, "
            "applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL)")
        aplicadas = []
        for nome in self.pendentes(pasta):
            sql = (Path(pasta) / nome).read_text(encoding="utf-8")
            nome_sql = literal(nome)
            self.conexao.executescript(
                f"BEGIN;\n{sql}\n;\nINSERT INTO d1_migrations (name) VALUES ({nome_sql});\nCOMMIT;")
            aplicadas.append(nome)
        return aplicadas

    def aplicar(self, alteracoes: Sequence[Alteracao]) -> int:
        """Aplica tudo numa transação; devolve o número de instruções."""
        if self.somente_leitura:
            raise RuntimeError("banco aberto só para leitura")
        lista = instrucoes([a for a in alteracoes if not a.vazia()])
        if not lista:
            return 0
        cur = self.conexao.cursor()
        cur.execute("BEGIN")
        try:
            for sql, params in lista:
                cur.execute(sql, params)
        except BaseException:
            cur.execute("ROLLBACK")
            raise
        cur.execute("COMMIT")
        return len(lista)


# ---------------------------------------------------------------- D1 remoto
def npx() -> str:
    caminho = shutil.which("npx") or shutil.which("npx.cmd")
    if not caminho:
        raise ErroNuvem("npx não encontrado no PATH (necessário para o wrangler)")
    return caminho


class BancoRemoto:
    """D1 pela API REST (leituras e cargas pequenas) e pelo wrangler (migrações e cargas grandes)."""

    pagina: int | None = 5000

    def __init__(self, d1: D1, nome: str, *, ambiente_wrangler: str | None = None,
                 pasta_worker: Path = PASTA_WORKER, executar: Callable[..., Any] = subprocess.run,
                 limiar_arquivo: int = LIMIAR_ARQUIVO, segredos: Sequence[str] = (),
                 env_extra: dict[str, str] | None = None, comando_npx: str | None = None) -> None:
        self.d1 = d1
        self.comando_npx = comando_npx
        self.env_extra = dict(env_extra or {})
        self.nome = nome
        self.ambiente_wrangler = ambiente_wrangler
        self.pasta_worker = Path(pasta_worker)
        self.executar = executar
        self.limiar_arquivo = limiar_arquivo
        self.segredos = tuple(segredos)
        self.comandos: list[list[str]] = []

    def fechar(self) -> None:
        pass

    def consultar(self, sql: str, params: Sequence[Any] = ()) -> list[dict]:
        return self.d1.consultar(sql, params)

    def tabelas(self) -> set[str]:
        return {r["name"] for r in self.consultar("SELECT name FROM sqlite_master WHERE type = 'table'")}

    def migracoes_aplicadas(self) -> set[str]:
        if "d1_migrations" not in self.tabelas():
            return set()
        return {r["name"] for r in self.consultar("SELECT name FROM d1_migrations")}

    def pendentes(self, pasta: Path = PASTA_MIGRACOES) -> list[str]:
        aplicadas = self.migracoes_aplicadas()
        return [n for n in nomes_migracoes(pasta) if n not in aplicadas]

    def _wrangler(self, *args: str) -> None:
        comando = [self.comando_npx or npx(), "wrangler", *args]
        if self.ambiente_wrangler:
            comando += ["--env", self.ambiente_wrangler]
        self.comandos.append(comando)
        env = {**os.environ, **self.env_extra, "CI": "true"}  # sem perguntas interativas
        r = self.executar(comando, cwd=str(self.pasta_worker), env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
        if getattr(r, "returncode", 1) != 0:
            saida = redigir(((getattr(r, "stderr", "") or "") + (getattr(r, "stdout", "") or ""))[-800:],
                            self.segredos)
            raise ErroNuvem(f"wrangler {' '.join(args[:3])} falhou ({r.returncode}): {saida}")

    def migrar(self, pasta: Path = PASTA_MIGRACOES) -> list[str]:
        pendentes = self.pendentes(pasta)
        if pendentes:
            self._wrangler("d1", "migrations", "apply", self.nome, "--remote")
        return pendentes

    def aplicar(self, alteracoes: Sequence[Alteracao]) -> int:
        validas = [a for a in alteracoes if not a.vazia()]
        lista = instrucoes(validas)
        if not lista:
            return 0
        if len(lista) <= self.limiar_arquivo:
            self.d1.lote(lista)
            return len(lista)
        literais = instrucoes(validas, modo="literal")
        with tempfile.TemporaryDirectory(prefix="radar-d1-") as pasta:
            arquivo = Path(pasta) / "carga.sql"
            arquivo.write_text("".join(sql + "\n" for sql, _ in literais), encoding="utf-8", newline="\n")
            self._wrangler("d1", "execute", self.nome, "--remote", f"--file={arquivo}")
        return len(literais)


def ler_tabela(banco, tabela: str, colunas: Sequence[str], chave: Sequence[str]) -> dict[tuple, tuple]:
    """Linhas atuais: chave primária -> valores de `colunas`, lidas em páginas no D1 remoto."""
    seletor = f"SELECT {', '.join(q(c) for c in colunas)} FROM {q(tabela)} ORDER BY {', '.join(q(c) for c in chave)}"
    linhas: list[dict] = []
    if banco.pagina is None:
        linhas = banco.consultar(seletor)
    else:
        deslocamento = 0
        while True:
            pagina = banco.consultar(f"{seletor} LIMIT {banco.pagina} OFFSET {deslocamento}")
            linhas.extend(pagina)
            if len(pagina) < banco.pagina:
                break
            deslocamento += banco.pagina
    return {tuple(r[c] for c in chave): tuple(r[c] for c in colunas) for r in linhas}
