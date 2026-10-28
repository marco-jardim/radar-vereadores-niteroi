"""Tabelas do D1, montagem de instruções e os dois bancos: SQLite local e D1 remoto.

As alterações são descritas em `Alteracao` (apagar chaves, gravar linhas, limpar a
tabela) e viram instruções conforme o destino:

- modo `parametros`: até 100 parâmetros por instrução, NULL embutido, `CAST(? AS
  INTEGER)` no `rowid` do FTS (o D1 recebe parâmetros como texto). Usado no SQLite
  local e nos lotes REST do D1;
- modo `literal`: valores embutidos, até 100.000 bytes por instrução. Usado nos
  arquivos `.sql` aplicados com `wrangler d1 execute <db> --remote --yes --file`
  (só cargas muito grandes, acima de `LIMIAR_ARQUIVO` instruções: a importação
  bloqueia o banco enquanto roda).

As instruções saem em **unidades**: instruções que só valem juntas (um bloco de
trechos e as linhas correspondentes de `trechos_fts`) vão sempre na mesma requisição
de lote, que o D1 aplica de forma atômica. Assim uma falha no meio da carga nunca
deixa o FTS divergente dos trechos.

Migrações: a pasta única `worker/migrations/`; localmente, aplicadas pelo `sqlite3`
com a mesma tabela `d1_migrations` do wrangler; no D1, por
`wrangler d1 migrations apply <db> --remote` (versão fixada em `coletor.nuvem.wrangler`).
"""
from __future__ import annotations

import math
import os
import sqlite3
import subprocess
import tempfile
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from coletor.nuvem.cloudflare import D1, MAX_BYTES_INSTRUCAO, MAX_PARAMETROS
from coletor.nuvem.wrangler import PASTA_WORKER, TIMEOUT_WRANGLER, Wrangler, npx  # noqa: F401 - npx reexportado

RAIZ = Path(__file__).resolve().parents[2]
PASTA_MIGRACOES = RAIZ / "worker" / "migrations"

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
LIMIAR_ARQUIVO = 5000  # acima disto, a carga no D1 remoto vai por arquivo .sql e wrangler (bloqueia o banco)
LINHAS_POR_INSTRUCAO = 500
BYTES_UNIDADE_TRECHOS = 40_000  # texto somado de um bloco de trechos (o FTS repete o texto normalizado)


@dataclass
class Alteracao:
    tabela: str
    colunas: tuple[str, ...] = ()
    chave: tuple[str, ...] = ()
    gravar: list[tuple] = field(default_factory=list)
    apagar: list[tuple] = field(default_factory=list)
    limpar: bool = False
    substituir: bool = True  # INSERT OR REPLACE (FTS: INSERT simples, depois de apagar)
    # só em `trechos`: linha do FTS de cada linha gravada e rowid do FTS de cada chave apagada;
    # com elas, cada bloco de trechos sai numa unidade junto com o FTS correspondente
    fts_linha: Callable[[tuple], tuple] | None = None
    fts_rowid: Callable[[tuple], int] | None = None

    @classmethod
    def de(cls, tabela: str, gravar: Iterable[tuple] = (), apagar: Iterable[tuple] = (), limpar: bool = False, *,
           fts_linha: Callable[[tuple], tuple] | None = None, fts_rowid: Callable[[tuple], int] | None = None):
        if tabela == FTS:
            return cls(FTS, COLUNAS_FTS, ("rowid",), list(gravar), list(apagar), limpar, substituir=False)
        colunas, chave = COLUNAS[tabela]
        if (fts_linha is None) != (fts_rowid is None):
            raise ValueError("fts_linha e fts_rowid andam juntos")
        return cls(tabela, colunas, chave, list(gravar), list(apagar), limpar, fts_linha=fts_linha,
                   fts_rowid=fts_rowid)

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


def _blocos_chaves(chaves: Sequence[tuple], largura: int) -> Iterable[list[tuple]]:
    passo = max(1, MAX_PARAMETROS // max(1, largura))
    for i in range(0, len(chaves), passo):
        yield list(chaves[i:i + passo])


def _blocos_linhas(linhas: Sequence[tuple], largura: int, max_bytes: int | None = None) -> Iterable[list[tuple]]:
    """Blocos que cabem numa instrução (100 parâmetros) e com o texto somado até `max_bytes`."""
    max_bytes = BYTES_UNIDADE_TRECHOS if max_bytes is None else max_bytes
    passo = max(1, MAX_PARAMETROS // max(1, largura))
    bloco: list[tuple] = []
    tamanho = 0
    for linha in linhas:
        peso = sum(len(v.encode("utf-8")) for v in linha if isinstance(v, str))
        if bloco and (len(bloco) >= passo or tamanho + peso > max_bytes):
            yield bloco
            bloco, tamanho = [], 0
        bloco.append(linha)
        tamanho += peso
    if bloco:
        yield bloco


def unidades(alteracoes: Iterable[Alteracao], modo: str = "parametros") -> list[list[tuple[str, tuple]]]:
    """Unidades atômicas na ordem das alterações; em cada alteração, limpar, apagar e depois gravar.

    Sem FTS acoplado, cada instrução é uma unidade. Em `trechos` com `fts_linha`/`fts_rowid`,
    cada bloco apagado leva o DELETE do FTS, e cada bloco gravado leva o DELETE dos rowids do
    bloco no FTS (idempotente), o INSERT dos trechos e o INSERT do FTS: tudo numa só unidade.
    """
    saida: list[list[tuple[str, tuple]]] = []
    for a in alteracoes:
        if a.limpar:
            saida.append([(f"DELETE FROM {q(a.tabela)};", ())])
        if a.fts_linha is None or a.fts_rowid is None:
            if a.apagar:
                saida.extend([i] for i in instrucoes_apagar(a.tabela, a.chave, a.apagar, modo=modo))
            if a.gravar:
                saida.extend([i] for i in instrucoes_gravar(a.tabela, a.colunas, a.gravar, modo=modo,
                                                              substituir=a.substituir))
            continue
        for bloco in _blocos_chaves(a.apagar, len(a.chave)):
            saida.append(instrucoes_apagar(a.tabela, a.chave, bloco, modo=modo)
                         + instrucoes_apagar(FTS, ("rowid",), [(a.fts_rowid(k),) for k in bloco], modo=modo))
        for bloco in _blocos_linhas(a.gravar, len(a.colunas)):
            fts = [a.fts_linha(linha) for linha in bloco]
            saida.append(instrucoes_apagar(FTS, ("rowid",), [(f[0],) for f in fts], modo=modo)
                         + instrucoes_gravar(a.tabela, a.colunas, bloco, modo=modo, substituir=a.substituir)
                         + instrucoes_gravar(FTS, COLUNAS_FTS, fts, modo=modo, substituir=False))
    return saida


def instrucoes(alteracoes: Iterable[Alteracao], modo: str = "parametros") -> list[tuple[str, tuple]]:
    """Instruções na ordem das alterações (as unidades de `unidades`, em sequência)."""
    return [i for u in unidades(alteracoes, modo) for i in u]


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
class BancoRemoto:
    """D1 pela API REST (leituras e cargas em lotes atômicos) e pelo wrangler (migrações e cargas enormes).

    Até `LIMIAR_ARQUIVO` (5.000) instruções, a carga vai em lotes REST, com as unidades inteiras.
    Acima disso, num arquivo `.sql` por `wrangler d1 execute --remote --yes --file`: a importação
    bloqueia o banco (o Worker fica sem responder) enquanto roda.
    """

    pagina: int | None = 5000

    def __init__(self, d1: D1, nome: str, *, ambiente_wrangler: str | None = None,
                 pasta_worker: Path = PASTA_WORKER, executar: Callable[..., Any] = subprocess.run,
                 limiar_arquivo: int = LIMIAR_ARQUIVO, segredos: Sequence[str] = (),
                 env_extra: dict[str, str] | None = None, comando_npx: str | None = None,
                 remover_env: Sequence[str] = (), credencial=None, timeout: float = TIMEOUT_WRANGLER) -> None:
        self.d1 = d1
        self.nome = nome
        self.ambiente_wrangler = ambiente_wrangler
        self.limiar_arquivo = limiar_arquivo
        self.segredos = tuple(segredos)
        self.credencial = credencial
        self.wrangler = Wrangler(pasta_worker, comando_npx=comando_npx, env_extra=env_extra,
                                 remover_env=remover_env, executor=executar, timeout=timeout,
                                 segredos=self._segredos)

    def _segredos(self) -> tuple[str, ...]:
        return (*self.segredos, *(self.credencial.segredos() if self.credencial is not None else ()))

    @property
    def comandos(self) -> list[list[str]]:
        return self.wrangler.comandos

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

    def _wrangler(self, *args: str) -> str:
        args_env = [*args, *(["--env", self.ambiente_wrangler] if self.ambiente_wrangler else [])]
        return self.wrangler.executar(*args_env)

    def migrar(self, pasta: Path = PASTA_MIGRACOES) -> list[str]:
        pendentes = self.pendentes(pasta)
        if pendentes:
            self._wrangler("d1", "migrations", "apply", self.nome, "--remote")
        return pendentes

    def aplicar(self, alteracoes: Sequence[Alteracao]) -> int:
        validas = [a for a in alteracoes if not a.vazia()]
        lista_unidades = unidades(validas)
        total = sum(len(u) for u in lista_unidades)
        if not total:
            return 0
        if total <= self.limiar_arquivo:
            self.d1.lote_unidades(lista_unidades)
            return total
        literais = instrucoes(validas, modo="literal")
        with tempfile.TemporaryDirectory(prefix="radar-d1-") as pasta:
            arquivo = Path(pasta) / "carga.sql"
            arquivo.write_text("".join(sql + "\n" for sql, _ in literais), encoding="utf-8", newline="\n")
            # importação: bloqueia o banco enquanto roda; --yes dispensa a confirmação
            self._wrangler("d1", "execute", self.nome, "--remote", "--yes", f"--file={arquivo}")
        return len(literais)


def ler_tabela(banco, tabela: str, colunas: Sequence[str], chave: Sequence[str]) -> dict[tuple, tuple]:
    """Linhas atuais: chave primária -> valores de `colunas`.

    No D1 remoto, em páginas por conjunto de chaves (`WHERE (chave) > (última) ORDER BY chave LIMIT n`),
    sem OFFSET: cada página lê só as suas linhas, e o custo não cresce com a posição.
    """
    seletor = f"SELECT {', '.join(q(c) for c in colunas)} FROM {q(tabela)}"
    ordem = f" ORDER BY {', '.join(q(c) for c in chave)}"
    linhas: list[dict] = []
    if banco.pagina is None:
        linhas = banco.consultar(seletor + ordem)
    else:
        ultima: tuple | None = None
        while True:
            onde = ""
            if ultima is not None:
                if len(chave) == 1:
                    onde = f" WHERE {q(chave[0])} > {literal(ultima[0])}"
                else:
                    onde = (f" WHERE ({', '.join(q(c) for c in chave)}) > "
                            f"({', '.join(literal(v) for v in ultima)})")
            pagina = banco.consultar(f"{seletor}{onde}{ordem} LIMIT {banco.pagina}")
            linhas.extend(pagina)
            if len(pagina) < banco.pagina:
                break
            ultima = tuple(pagina[-1][c] for c in chave)
    return {tuple(r[c] for c in chave): tuple(r[c] for c in colunas) for r in linhas}


# ---------------------------------------------------------------- conferência do FTS
_HEX = "'0123456789abcdef'"


def sql_rowid_fts(coluna: str) -> str:
    """Expressão SQL de `int(id, 16) >> 1` para ids de 16 hexadecimais minúsculos (sem estouro de 64 bits)."""
    termos = [f"(instr({_HEX}, substr({coluna}, {k}, 1)) - 1) * {16 ** (15 - k)}" for k in range(1, 16)]
    return f"(({' + '.join(termos)}) * 8 + ((instr({_HEX}, substr({coluna}, 16, 1)) - 1) >> 1))"


def sql_fts_divergente() -> tuple[str, str]:
    """Duas consultas `LIMIT 1`: trecho sem a linha do FTS no rowid certo; linha do FTS sem trecho
    ou fora do rowid do id. Qualquer resultado indica conjuntos de ids diferentes."""
    sem_fts = (f"SELECT t.{q('id')} AS id FROM {q('trechos')} AS t WHERE NOT EXISTS (SELECT 1 FROM {FTS} AS f "
               f"WHERE f.rowid = {sql_rowid_fts('t.' + q('id'))} AND f.{q('id')} = t.{q('id')}) LIMIT 1")
    sem_trecho = (f"SELECT f.{q('id')} AS id FROM {FTS} AS f WHERE f.rowid != {sql_rowid_fts('f.' + q('id'))} "
                  f"OR NOT EXISTS (SELECT 1 FROM {q('trechos')} AS t WHERE t.{q('id')} = f.{q('id')}) LIMIT 1")
    return sem_fts, sem_trecho


def fts_divergente(banco) -> bool:
    """True se os ids de `trechos_fts` e `trechos` não são o mesmo conjunto (com os rowids do contrato)."""
    existentes = banco.tabelas()
    if FTS not in existentes or "trechos" not in existentes:
        return False
    return any(banco.consultar(sql) for sql in sql_fts_divergente())
