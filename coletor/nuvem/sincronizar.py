"""Sincronização do Git com D1, Vectorize e R2 (plano T2.2.1 S3, passos a–i).

Ordem de uma execução (etapas `r2`, `d1`, `vetores` e `exportar`, escolhidas por `etapas`):

a. barreira de PII: `mascara.varrer` em todo trecho, ementa e motivo de remoção a enviar; uma
   ocorrência forte aborta antes de qualquer escrita (`ErroBarreira`, sem os valores);
b. migrações pendentes de `worker/migrations/`;
c. `r2`: originais que faltam (verificação antes; bytes do cache `RADAR_CACHE/arquivos/<sha256>`,
   conferidos pelo hash), em até 4 envios simultâneos, com `If-None-Match: *` na via S3 (na via
   REST, PUT sem condição depois da verificação); originais removidos saem. Um original que
   falha deixa de fora, na mesma execução, a linha em `arquivos`, as de `arquivo_documento`,
   os trechos (e o FTS) e os vetores daquele arquivo: tudo ou nada por arquivo;
d. `d1`: diferença das tabelas-base contra o Git (gravar o que mudou, apagar o que saiu do
   Git ou entrou em `config/remocoes.json`). Cada bloco de trechos vai no mesmo lote atômico
   das suas linhas de `trechos_fts`; se os conjuntos de ids de `trechos` e `trechos_fts`
   divergirem (duas consultas `LIMIT 1`), o FTS é refeito. `ementas_fts` compara as
   ementas mascaradas normalizadas de todos os documentos e troca só as alteradas,
   por documento completo, com DELETE + INSERT no mesmo lote atômico;
e. `vetores`: confere o índice (1.024 dimensões e índices de metadados `tipo`, `ano`,
   `legislatura`); vetores só dos trechos vetorizáveis e das ementas de indicações e moções
   (`ementa:doc:<id>`) novos ou alterados (diferença contra `trechos_indexados`, cujo `sha256`
   cobre texto e metadados). Antes do upsert, os ids ainda não registrados entram como
   `pendente`; depois, com o hash real. Saem do índice os ids registrados que deixaram o Git, os
   trechos apagados nesta execução e as ementas dos documentos apagados; ao fim, espera
   `processedUpToMutation` e `processedUpToDatetime` ≥ início da execução;
f. `estado_indice`, gravado só no fim, só sem falhas e só com as etapas `r2`, `d1` e `vetores`;
g. `exportar`: dump das tabelas-base, vetores em JSONL gzip (mtime 0) e `SHA256SUMS`, enviados a
   `<bucket de exportações>/<versao>/`; se o `SHA256SUMS` da versão já está no bucket, nada é
   reenviado (e um conteúdo diferente vira aviso). Com remoções pendentes, inclusive sem
   `exportar`, a etapa R2 expurga exportações antes de confirmar as remoções no D1;
h. `--reconstruir`: limpa o D1, reenvia tudo (com o cache de embeddings) e apaga do índice
   todo vetor listado que o Git não tem;
i. `--simular`: só leituras; o plano é o mesmo, sem nenhuma escrita.

Uma segunda execução sem mudanças no Git, no mesmo commit, não faz nenhuma escrita (um commit
novo regrava `estado_indice`, que guarda o commit).
"""
from __future__ import annotations

import contextlib
import gzip
import hashlib
import io
import json
import re
import shutil
import sqlite3
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from coletor.arquivos import gravar_atomico
from coletor.nuvem.banco import (COLUNAS, COMPARAR, FTS, PASTA_MIGRACOES, TABELAS_BASE, Alteracao, fts_divergente,
                                 ler_tabela, literal, q)
from coletor.nuvem.cloudflare import DIMENSOES, INDICES_METADADOS
from coletor.nuvem.fonte import (Fonte, Original, carregar_fonte, normalizar_busca, rowid_fts, sha256, sha_indexado,
                                 varrer_fonte)
from coletor.nuvem.local import CacheEmbeddings, _gravar_bytes, como_float32, empacotar
from coletor.nuvem.r2 import LIMITE_ENVIO_R2_REST, R2Rest
from coletor.nuvem.rede import ErroNuvem
from coletor.trechos import VERSAO_TRECHOS

LOTE_SINCRONIZACAO = 500  # vetores por rodada de embeddings + upsert + trechos_indexados
TABELAS_GIT = tuple(t for t in TABELAS_BASE if t != "trechos_indexados") + ("ementas_fts",)
ETAPAS = ("r2", "d1", "vetores", "exportar")
ETAPAS_PADRAO = ("r2", "d1", "vetores")
ETAPAS_COMPLETAS = frozenset({"r2", "d1", "vetores"})  # necessárias para gravar estado_indice
PENDENTE = "pendente"  # trechos_indexados.sha256 de um vetor com upsert em curso
TRABALHADORES_R2 = 4
PROGRESSO_R2 = 100  # um aviso de progresso a cada N originais
FOLGA_RELOGIO = timedelta(seconds=60)  # diferença tolerada entre o relógio local e o do Vectorize
ESCRITAS = ("migracoes", "r2_enviar", "r2_apagar", "d1_instrucoes", "vetores_upsert", "vetores_apagar",
            "estado_indice", "exportacao_enviar", "exportacao_apagar", "exportacao_registro")
TIPOS_CONTEUDO = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc": "application/msword",
    "rtf": "application/rtf",
    "html": "text/html",
    "texto": "text/plain",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "tiff": "image/tiff",
    "zip": "application/zip",
}
MAX_META_DOCUMENTOS = 1500


class ErroBarreira(RuntimeError):
    """Ocorrência forte de dado pessoal num trecho, ementa ou motivo; a mensagem não traz os valores."""

    def __init__(self, ocorrencias: list[dict]) -> None:
        self.ocorrencias = ocorrencias
        linhas = [f"{o['origem']}: {o['tipo']} em [{o['inicio']}:{o['fim']}]" for o in ocorrencias[:50]]
        mais = f"\n… e mais {len(ocorrencias) - 50}" if len(ocorrencias) > 50 else ""
        super().__init__(f"barreira de PII: {len(ocorrencias)} ocorrência(s) forte(s); nada foi enviado\n"
                         + "\n".join(linhas) + mais)


@dataclass
class Ambiente:
    nome: str
    banco: Any
    r2: Any  # None: sem R2 (--sem-r2)
    bucket_arquivos: str
    bucket_exportacoes: str
    vetores: Any
    embedder: Callable[[Sequence[str]], list[list[float]]]
    modelo: str
    pasta_migracoes: Path = PASTA_MIGRACOES
    cache_embeddings: CacheEmbeddings | None = None
    dimensoes: int = DIMENSOES


@dataclass
class Relatorio:
    simulado: bool = False
    plano: Counter = field(default_factory=Counter)
    feitas: Counter = field(default_factory=Counter)
    falhas: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    fracas: int = 0
    versao: str | None = None
    estado_gravado: bool = False
    exportados: list[str] = field(default_factory=list)
    etapas: tuple[str, ...] = ()

    @property
    def escritas(self) -> int:
        return sum(self.feitas[k] for k in ESCRITAS)

    def texto(self) -> str:
        titulo = "Plano (simulação: nada foi gravado)" if self.simulado else "Plano"
        linhas = [f"{titulo}:"]
        if self.etapas:
            linhas.append(f"  etapas: {','.join(self.etapas)}")
        linhas += [f"  {k}: {v}" for k, v in sorted(self.plano.items())]
        if not self.simulado:
            linhas.append("Feito:")
            linhas += [f"  {k}: {v}" for k, v in sorted(self.feitas.items())]
            linhas.append(f"  escritas: {self.escritas}")
        linhas.append(f"Barreira de PII: 0 fortes, {self.fracas} fracas (para revisão)")
        if self.versao:
            linhas.append(f"Versão: {self.versao}")
        linhas += [f"Aviso: {a}" for a in self.avisos]
        linhas += [f"Falha: {f}" for f in self.falhas]
        return "\n".join(linhas)


def etapas_validas(etapas: Iterable[str] | str | None) -> tuple[str, ...]:
    """Etapas na ordem de execução; `"r2,d1"` ou uma sequência. ValueError com nome desconhecido."""
    if etapas is None:
        return ETAPAS_PADRAO
    if isinstance(etapas, str):
        etapas = [e.strip() for e in etapas.split(",") if e.strip()]
    pedidas = set(etapas)
    desconhecidas = sorted(pedidas - set(ETAPAS))
    if desconhecidas or not pedidas:
        raise ValueError(f"etapas inválidas: {', '.join(desconhecidas) or '(nenhuma)'} "
                         f"(use {','.join(ETAPAS)})")
    return tuple(e for e in ETAPAS if e in pedidas)


# ---------------------------------------------------------------- estado atual
def ler_atual(banco, *, sem_commit_dados_textos: bool = False) -> dict[str, Any]:
    existentes = banco.tabelas()
    atual: dict[str, Any] = {}
    for tabela in (*TABELAS_BASE, "ementas_fts"):
        colunas, chave = COLUNAS[tabela]
        atual[tabela] = ler_tabela(banco, tabela, COMPARAR.get(tabela, colunas), chave) if tabela in existentes else {}
    atual["estado_indice"] = None
    if "estado_indice" in existentes:
        colunas = COLUNAS["estado_indice"][0]
        selecao = [f"NULL AS {q(c)}" if sem_commit_dados_textos and c == "commit_dados_textos" else q(c)
                   for c in colunas]
        linhas = banco.consultar(f"SELECT {', '.join(selecao)} FROM {q('estado_indice')} "
                                 f"WHERE {q('id')} = 1")
        if linhas:
            atual["estado_indice"] = tuple(linhas[0][c] for c in colunas)
    atual["fts_divergente"] = fts_divergente(banco)
    return atual


# ---------------------------------------------------------------- versão e exportação
def linhas_dump(fonte: Fonte) -> Iterable[str]:
    """Dump determinístico das tabelas-base (ordem de tabela e de chave primária), sem o FTS."""
    yield "-- Radar dos Vereadores de Niterói: tabelas-base do D1 (docs/contratos/textos.md, seção 8.1).\n"
    yield "-- trechos_fts e ementas_fts são reconstruíveis (python -m coletor.nuvem --reconstruir) e ficam fora.\n"
    for tabela in TABELAS_BASE:
        colunas = COLUNAS[tabela][0]
        cabeca = f"INSERT INTO {q(tabela)} ({', '.join(q(c) for c in colunas)}) VALUES ("
        linhas = fonte.linhas[tabela]
        for chave in sorted(linhas):
            yield cabeca + ", ".join(literal(v) for v in linhas[chave]) + ");\n"


def _linhas_vetores_meta(fonte: Fonte) -> Iterable[bytes]:
    for i in sorted(fonte.vetores):
        sha, meta, _ = fonte.vetores[i]
        yield json.dumps([i, sha, meta], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def calcular_versao(fonte: Fonte, modelo: str) -> str:
    """16 hexadecimais do conteúdo: dump das tabelas-base, vetores (id, sha256, metadados), modelo e trechos."""
    dump = hashlib.sha256()
    for linha in linhas_dump(fonte):
        dump.update(linha.encode("utf-8"))
    vetores = hashlib.sha256()
    for linha in _linhas_vetores_meta(fonte):
        vetores.update(linha)
    base = f"radar-nuvem/1\n{dump.hexdigest()}\n{vetores.hexdigest()}\n{modelo}\n{VERSAO_TRECHOS}\n"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


def gzip_deterministico(dados: bytes) -> bytes:
    """Gzip com mtime 0 e sem nome de arquivo no cabeçalho."""
    saida = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=saida, mtime=0, compresslevel=9) as gz:
        gz.write(dados)
    return saida.getvalue()


# Margem sobre LIMITE_ENVIO_R2_REST, inclusive para exportações via S3.
LIMITE_PARTE_EXPORTACAO = 90_000_000


def _partes_exportacao(linhas: Iterable[bytes], *, comprimir: bool = False) -> list[bytes]:
    """Partes em fronteiras de linha; confere o tamanho dos bytes efetivamente enviados.

    Limitar também a entrada evita comprimir toda a exportação de uma vez. Se o
    gzip crescer, divide o bloco novamente; uma linha indivisível não cabe e falha
    antes de publicar qualquer objeto.
    """
    partes = []

    def fechar(bloco: list[bytes]) -> None:
        dados = b"".join(bloco)
        if comprimir:
            dados = gzip_deterministico(dados)
        if len(dados) <= LIMITE_PARTE_EXPORTACAO:
            partes.append(dados)
        elif len(bloco) > 1:
            meio = len(bloco) // 2
            fechar(bloco[:meio])
            fechar(bloco[meio:])
        else:
            raise ErroNuvem("exportação: linha excede o limite de uma parte")

    bloco, tamanho = [], 0
    for linha in linhas:
        if bloco and tamanho + len(linha) > LIMITE_PARTE_EXPORTACAO:
            fechar(bloco)
            bloco, tamanho = [], 0
        bloco.append(linha)
        tamanho += len(linha)
    if bloco or not partes:
        fechar(bloco)
    return partes


def _somas_exportacao(arquivos: dict[str, bytes]) -> bytes:
    return "".join(f"{sha256(dados)}  {nome}\n" for nome, dados in sorted(arquivos.items())).encode("ascii")


def _nomes_exportacao(versao: str, nomes: Iterable[str]) -> tuple[list[str], list[str]]:
    """Valida nomes locais ao prefixo, sem misturar arquivo único e partes, nem lacunas."""
    nomes = set(nomes)
    grupos = []
    for prefixo, sufixo in (("d1", ".sql"), ("vetores", ".jsonl.gz")):
        unico = f"{prefixo}-{versao}{sufixo}"
        padrao = re.compile(rf"{prefixo}-{versao}-([0-9]{{3,}}){re.escape(sufixo)}")
        partes = sorted((n for n in nomes if padrao.fullmatch(n)),
                        key=lambda n: int(padrao.fullmatch(n)[1]))
        if unico in nomes and not partes:
            grupos.append([unico])
        elif (partes and unico not in nomes
              and partes == [f"{prefixo}-{versao}-{i:03d}{sufixo}" for i in range(1, len(partes) + 1)]):
            grupos.append(partes)
        else:
            raise ErroNuvem(f"exportação {versao}: partes incompletas ou nomes inválidos")
    if nomes != set(grupos[0] + grupos[1]):
        raise ErroNuvem(f"exportação {versao}: nomes inválidos")
    return grupos[0], grupos[1]


def _ler_somas_exportacao(versao: str, dados: bytes) -> dict[str, str]:
    try:
        pares = [linha.split("  ") for linha in dados.decode("ascii").splitlines()]
        if (not pares or any(len(p) != 2 or not re.fullmatch(r"[0-9a-f]{64}", p[0]) for p in pares)
                or len({p[1] for p in pares}) != len(pares)):
            raise ValueError
        _nomes_exportacao(versao, (p[1] for p in pares))
    except (ValueError, UnicodeError, ErroNuvem):
        raise ErroNuvem(f"exportação {versao}: SHA256SUMS inválido") from None
    return {nome: soma for soma, nome in pares}


def _montar_partes_exportacao(versao: str, dump: Iterable[bytes], vetores: Iterable[bytes]) -> dict[str, bytes]:
    partes_dump = _partes_exportacao(dump)
    arquivos = {(f"d1-{versao}.sql" if len(partes_dump) == 1 else f"d1-{versao}-{i:03d}.sql"): dados
                for i, dados in enumerate(partes_dump, 1)}
    arquivos.update({f"vetores-{versao}-{i:03d}.jsonl.gz": dados
                     for i, dados in enumerate(_partes_exportacao(vetores, comprimir=True), 1)})
    arquivos["SHA256SUMS"] = _somas_exportacao(arquivos)
    return arquivos


def _valores_vetores(ambiente: Ambiente, fonte: Fonte, ids: Sequence[str]) -> dict[str, list[float]]:
    valores: dict[str, list[float]] = {}
    faltam = []
    for i in ids:
        v = ambiente.cache_embeddings.obter(fonte.vetores[i][0]) if ambiente.cache_embeddings else None
        if v is not None and len(v) == ambiente.dimensoes:
            valores[i] = v
        else:
            faltam.append(i)
    if faltam:  # get_by_ids em lotes de 100, no ritmo global da API
        for item in ambiente.vetores.obter(faltam):
            valores[item["id"]] = como_float32(item["values"])
    ausentes = [i for i in ids if i not in valores]
    if ausentes:
        raise ErroNuvem(f"{len(ausentes)} vetor(es) sem valores para a exportação (ex.: {ausentes[0]})")
    return valores


def montar_exportacao(fonte: Fonte, ambiente: Ambiente, versao: str) -> dict[str, bytes]:
    """Dump e vetores em partes limitadas, com `SHA256SUMS` no formato do sha256sum."""
    ids = sorted(fonte.vetores)
    valores = _valores_vetores(ambiente, fonte, ids)
    jsonl = ((json.dumps({"id": i, "metadata": fonte.vetores[i][1], "values": empacotar(valores[i])},
                        ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8") for i in ids)
    return _montar_partes_exportacao(versao, (l.encode("utf-8") for l in linhas_dump(fonte)), jsonl)


TIPOS_EXPORTACAO = {".sql": "application/sql; charset=utf-8", ".gz": "application/gzip"}


def _publicar_exportacao(arquivos: dict[str, bytes], ambiente: Ambiente, versao: str,
                         pasta: Path, rel: Relatorio) -> None:
    destino = pasta / versao
    destino.mkdir(parents=True, exist_ok=True)
    for nome, dados in sorted(arquivos.items()):
        local = destino / nome
        if not local.is_file() or local.read_bytes() != dados:
            _gravar_bytes(local, dados)
    if ambiente.r2 is None:
        rel.avisos.append(f"exportação {versao}: gravada só em {destino} (sem R2)")
        return
    bucket = ambiente.bucket_exportacoes
    condicional = getattr(ambiente.r2, "put_condicional", True)
    for nome in sorted(arquivos, key=lambda n: (n == "SHA256SUMS", n)):
        chave = f"{versao}/{nome}"
        existente = ambiente.r2.obter(bucket, chave)
        if existente is None:
            tipo = TIPOS_EXPORTACAO.get(Path(nome).suffix, "text/plain; charset=utf-8")
            if ambiente.r2.enviar(bucket, chave, arquivos[nome], tipo, se_ausente=condicional):
                rel.feitas["exportacao_enviar"] += 1
            existente = ambiente.r2.obter(bucket, chave)
        if existente != arquivos[nome]:
            raise ErroNuvem(f"exportação {versao}: objeto não confirmado; versão antiga preservada")
        if chave not in rel.exportados:
            rel.exportados.append(chave)


def _ler_dump(dados: bytes) -> dict[str, dict[tuple, tuple]]:
    """Lê dumps históricos sem executar comandos arbitrários vindos do bucket público.

    SQLite interpreta os literais (inclusive apóstrofos e quebras em texto), mas
    o autorizador só permite INSERT nas tabelas-base: sem SELECT, funções ou DDL.
    """
    with contextlib.closing(sqlite3.connect(":memory:")) as con:
        for tabela in TABELAS_BASE:
            con.execute(f"CREATE TABLE {q(tabela)} ({', '.join(q(c) for c in COLUNAS[tabela][0])})")
        con.set_authorizer(lambda acao, tabela, _coluna, _db, _origem:
                           sqlite3.SQLITE_OK if acao == sqlite3.SQLITE_INSERT and tabela in TABELAS_BASE
                           else sqlite3.SQLITE_DENY)
        try:
            con.executescript(dados.decode("utf-8"))
        except (sqlite3.DatabaseError, UnicodeError):
            raise ErroNuvem("exportação histórica: dump inválido; expurgo não concluído") from None
        finally:
            con.set_authorizer(None)
        linhas = {}
        for tabela in TABELAS_BASE:
            colunas, chave = COLUNAS[tabela]
            posicoes = [colunas.index(c) for c in chave]
            linhas[tabela] = {tuple(row[i] for i in posicoes): tuple(row)
                              for row in con.execute(f"SELECT * FROM {q(tabela)}")}
        return linhas


def _arquivos_removidos(fonte: Fonte, arquivos: dict[tuple, tuple]) -> set[str]:
    chaves = {k[0] for k in fonte.linhas["remocoes"]}
    hashes = {c.rsplit("/", 1)[-1] for c in fonte.remover_r2}
    return {k[0] for k, row in arquivos.items() if k[0] in chaves or row[1] in hashes}


def _exportacoes_pendentes(fonte: Fonte, atual: dict, pasta: Path, reconstruir: bool) -> bool:
    """Não consulta o bucket só porque há tombstones antigos no Git.

    O expurgo antecede a escrita de `remocoes` no D1: em caso de interrupção,
    inclusive após publicar recibos, a diferença continua pendente em outra máquina.
    Cópias locais e reconstruções também precisam conferir o histórico.
    """
    if not fonte.remover_r2:
        return False
    if reconstruir or _arquivos_removidos(fonte, atual["arquivos"]):
        return True
    novas = fonte.linhas["remocoes"].keys() - atual["remocoes"].keys()
    if novas and (atual["arquivos"] or atual["estado_indice"] is not None):
        return True
    for destino in sorted(pasta.iterdir()) if pasta.is_dir() else []:
        if destino.is_dir() and re.fullmatch(r"[0-9a-f]{16}", destino.name):
            sums = destino / "SHA256SUMS"
            if sums.is_file():
                nomes = _ler_somas_exportacao(destino.name, sums.read_bytes())
                sqls, _ = _nomes_exportacao(destino.name, nomes)
            else:
                nomes = [p.name for p in destino.iterdir()
                         if p.is_file() and not p.name.startswith(".") and not p.name.endswith(".tmp")]
                try:
                    sqls, _ = _nomes_exportacao(destino.name, nomes)
                except ErroNuvem:
                    continue  # publicação local incompleta, ainda sem manifesto
            dump = b"".join((destino / nome).read_bytes() for nome in sqls)
            if _arquivos_removidos(fonte, _ler_dump(dump)["arquivos"]):
                return True
    return False


def _filtrar_exportacao(fonte: Fonte, antiga: str, sql: bytes, vetores: bytes
                        ) -> tuple[str, dict[str, bytes]] | None:
    linhas = _ler_dump(sql)
    chaves = {k[0] for k in fonte.linhas["remocoes"]}
    removidas = _arquivos_removidos(fonte, linhas["arquivos"])
    ids = {k[0] for k, row in linhas["trechos"].items() if row[2] in removidas or row[2] in chaves}
    if not removidas and not ids:
        return None
    linhas["arquivos"] = {k: row for k, row in linhas["arquivos"].items() if k[0] not in removidas}
    linhas["arquivo_documento"] = {k: row for k, row in linhas["arquivo_documento"].items()
                                    if k[0] not in removidas and k[0] not in chaves}
    linhas["trechos"] = {k: row for k, row in linhas["trechos"].items() if k[0] not in ids}
    linhas["trechos_indexados"] = {k: row for k, row in linhas["trechos_indexados"].items() if k[0] not in ids}
    linhas["remocoes"].update(fonte.linhas["remocoes"])
    # Documentos, autoria e ementas públicas NÃO são removidos (§8.1).
    dump = "".join(linhas_dump(replace(fonte, linhas=linhas))).encode("utf-8")
    lista = [json.loads(linha) for linha in gzip.decompress(vetores).decode("utf-8").splitlines() if linha]
    jsonl = "".join(json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
                    for v in sorted(lista, key=lambda v: v["id"]) if v["id"] not in ids)
    gz = gzip_deterministico(jsonl.encode("utf-8"))
    nova = sha256(b"radar-expurgo/1\n" + antiga.encode("ascii") + b"\n" + dump + gz)[:16]
    arquivos = _montar_partes_exportacao(nova, (l.encode("utf-8") for l in linhas_dump(replace(fonte, linhas=linhas))),
                                       (l.encode("utf-8") for l in jsonl.splitlines(keepends=True)))
    return nova, arquivos


def _registrar_expurgo(raiz: Path, antiga: str, nova: str) -> None:
    caminho = raiz / "docs" / "backend.md"
    texto = caminho.read_text(encoding="utf-8") if caminho.is_file() else "# Backend\n"
    linha = f"- Exportação `{antiga}` regravada como `{nova}` por remoção; versão antiga apagada.\n"
    if linha not in texto:
        if "## Registro de expurgos de exportações" not in texto:
            texto += "\n## Registro de expurgos de exportações\n\n"
        gravar_atomico(caminho, texto + linha)


def _expurgar_exportacoes(fonte: Fonte, ambiente: Ambiente, raiz: Path, pasta: Path,
                          rel: Relatorio, simular: bool) -> None:
    """Varre também versões antigas do bucket público, mesmo sem --exportar.

    O recibo sem conteúdo pessoal permite retomar DELETEs interrompidos em outra
    máquina. Só se apaga a origem depois de confirmar todos os bytes do destino.
    """
    r2, bucket = ambiente.r2, ambiente.bucket_exportacoes
    objetos = r2.listar(bucket) if r2 is not None else []
    locais = {p.name for p in pasta.iterdir() if p.is_dir() and re.fullmatch(r"[0-9a-f]{16}", p.name)} if pasta.is_dir() else set()
    versoes = locais | {c.split("/", 1)[0] for c in objetos if re.fullmatch(r"[0-9a-f]{16}/.+", c)}
    recibos = {}
    for chave in objetos:
        if re.fullmatch(r"remocoes/[0-9a-f]{16}\.json", chave):
            try:
                recibo = json.loads(r2.obter(bucket, chave))
                if (not isinstance(recibo, dict) or set(recibo) != {"nova", "sha256sums"}
                        or not isinstance(recibo["nova"], str) or not re.fullmatch(r"[0-9a-f]{16}", recibo["nova"])
                        or not isinstance(recibo["sha256sums"], str)
                        or not re.fullmatch(r"[0-9a-f]{64}", recibo["sha256sums"])):
                    raise ValueError
            except (ValueError, TypeError):
                raise ErroNuvem("recibo de expurgo inválido") from None
            recibos[Path(chave).stem] = recibo
    # Primeiro publica todos os destinos. Só depois resolve as cadeias e apaga:
    # a ordem lexicográfica das versões não pode decidir qual recibo é válido.
    for antiga in sorted(versoes - set(recibos)):
        def obter(nome: str) -> bytes | None:
            dados = r2.obter(bucket, f"{antiga}/{nome}") if r2 is not None else None
            local = pasta / antiga / nome
            if dados is None and local.is_file():
                dados = local.read_bytes()
            return dados

        sums = obter("SHA256SUMS")
        try:
            nomes = list(_ler_somas_exportacao(antiga, sums)) if sums is not None else None
        except ErroNuvem:
            nomes = None  # preserva o aviso para versão não afetada com somas divergentes
        if nomes is None:
            nomes = {c.split("/", 1)[1] for c in objetos if c.startswith(f"{antiga}/")}
            if (pasta / antiga).is_dir():
                nomes.update(p.name for p in (pasta / antiga).iterdir() if p.is_file())
            nomes.discard("SHA256SUMS")
        sqls, vetores = _nomes_exportacao(antiga, nomes)
        arquivos = {}
        for nome in sqls + vetores:
            dados = obter(nome)
            if dados is None:
                raise ErroNuvem(f"exportação {antiga}: incompleta; expurgo não concluído")
            arquivos[nome] = dados
        filtrada = _filtrar_exportacao(fonte, antiga, b"".join(arquivos[n] for n in sqls),
                                      b"".join(arquivos[n] for n in vetores))
        esperado = _somas_exportacao(arquivos)
        if sums is not None and sums != esperado:
            if filtrada is not None:
                raise ErroNuvem(f"exportação {antiga}: SHA256SUMS divergente; expurgo não concluído")
            rel.avisos.append(f"exportação {antiga}: SHA256SUMS difere dos objetos; versão não afetada preservada")
        if filtrada is None:
            continue
        nova, novos = filtrada
        rel.plano["exportacao_regravar"] += 1
        if simular:
            continue
        _publicar_exportacao(novos, ambiente, nova, pasta, rel)
        recibo = {"nova": nova, "sha256sums": sha256(novos["SHA256SUMS"])}
        if r2 is not None:
            chave_recibo = f"remocoes/{antiga}.json"
            dados_recibo = json.dumps(recibo, sort_keys=True).encode("ascii")
            if r2.enviar(bucket, chave_recibo, dados_recibo, "application/json"):
                rel.feitas["exportacao_registro"] += 1
            if r2.obter(bucket, chave_recibo) != dados_recibo:
                raise ErroNuvem(f"exportação {antiga}: recibo do expurgo não confirmado")
        recibos[antiga] = recibo
    if simular:
        return
    for antiga, recibo in sorted(recibos.items()):
        nova = recibo["nova"]
        visitadas = {antiga}
        while True:  # remoções posteriores podem regravar também o destino de um recibo antigo
            if not re.fullmatch(r"[0-9a-f]{16}", nova) or nova in visitadas:
                raise ErroNuvem("recibo de expurgo inválido")
            visitadas.add(nova)
            if nova not in recibos:
                break
            recibo = recibos[nova]
            nova = recibo["nova"]
        if r2 is not None:
            sums = r2.obter(bucket, f"{nova}/SHA256SUMS")
            if sums is None or sha256(sums) != recibo["sha256sums"]:
                raise ErroNuvem(f"exportação {nova}: destino do expurgo não confirmado")
            for nome, soma in _ler_somas_exportacao(nova, sums).items():
                dados = r2.obter(bucket, f"{nova}/{nome}")
                if dados is None or sha256(dados) != soma:
                    raise ErroNuvem(f"exportação {nova}: destino do expurgo incompleto")
        if r2 is not None:
            for chave in sorted(c for c in objetos if c.startswith(f"{antiga}/")):
                r2.apagar(bucket, chave)
                rel.feitas["exportacao_apagar"] += 1
        if (pasta / antiga).is_dir():
            shutil.rmtree(pasta / antiga)
        _registrar_expurgo(raiz, antiga, nova)


def _exportar(fonte: Fonte, ambiente: Ambiente, versao: str, pasta: Path, rel: Relatorio, simular: bool) -> None:
    if simular:
        rel.plano["exportacao_arquivos"] += 3  # mínimo; depende dos valores ainda não buscados
        return
    arquivos = montar_exportacao(fonte, ambiente, versao)
    rel.plano["exportacao_arquivos"] += len(arquivos)
    destino = Path(pasta) / versao
    for nome, dados in arquivos.items():
        local = destino / nome
        if not local.is_file() or local.read_bytes() != dados:
            _gravar_bytes(local, dados)
    if ambiente.r2 is None:
        _publicar_exportacao(arquivos, ambiente, versao, Path(pasta), rel)
        return
    no_bucket = ambiente.r2.obter(ambiente.bucket_exportacoes, f"{versao}/SHA256SUMS")
    if no_bucket is not None:  # a versão já foi publicada inteira: nada é reenviado
        try:
            nomes = list(_ler_somas_exportacao(versao, no_bucket)) + ["SHA256SUMS"]
        except ErroNuvem:
            nomes = list(arquivos)
        rel.exportados.extend(f"{versao}/{nome}" for nome in sorted(nomes, key=lambda n: (n == "SHA256SUMS", n)))
        if no_bucket != arquivos["SHA256SUMS"]:
            rel.avisos.append(f"exportação {versao}: o SHA256SUMS do bucket difere do gerado agora; "
                              "nada foi reenviado (confira o determinismo da exportação)")
        return
    _publicar_exportacao(arquivos, ambiente, versao, Path(pasta), rel)


# ---------------------------------------------------------------- embeddings
def _embeddings(ambiente: Ambiente, pares: Sequence[tuple[str, str]], rel: Relatorio) -> list[list[float]]:
    """Vetores de (sha256, texto): do cache quando há; os demais pelo modelo, conferindo a dimensão."""
    cache = ambiente.cache_embeddings
    saida: list[list[float] | None] = [None] * len(pares)
    faltam = []
    for n, (sha, _) in enumerate(pares):
        v = cache.obter(sha) if cache else None
        if v is not None and len(v) == ambiente.dimensoes:
            saida[n] = v
        else:
            faltam.append(n)
    if faltam:
        calculados = ambiente.embedder([pares[n][1] for n in faltam])
        rel.feitas["embeddings"] += len(faltam)
        if len(calculados) != len(faltam):
            raise ErroNuvem(f"embeddings: {len(calculados)} vetores para {len(faltam)} textos")
        for n, v in zip(faltam, calculados):
            if len(v) != ambiente.dimensoes:
                raise ErroNuvem(f"embeddings: {len(v)} dimensões (esperadas {ambiente.dimensoes})")
            v = como_float32(v)
            if cache:
                cache.guardar(pares[n][0], v)
            saida[n] = v
    return saida  # type: ignore[return-value]


def _blocos(itens: Sequence[str], tamanho: int) -> Iterable[Sequence[str]]:
    for i in range(0, len(itens), tamanho):
        yield itens[i:i + tamanho]


def tipo_conteudo(formato: str | None) -> str:
    return TIPOS_CONTEUDO.get(formato or "", "application/octet-stream")


def documentos_meta(documentos: Iterable[str], limite: int = MAX_META_DOCUMENTOS) -> str:
    """Ids em ordem, separados por vírgula, até `limite` caracteres, sem nunca cortar um id ao meio."""
    saida = ""
    for doc in sorted(documentos):
        proximo = f"{saida},{doc}" if saida else doc
        if len(proximo) > limite:
            break
        saida = proximo
    return saida


def conferir_indice(ambiente: Ambiente) -> None:
    """Pré-voo do Vectorize: dimensões e índices de metadados do contrato (seção 8.2); ErroNuvem se faltar."""
    info = ambiente.vetores.info() or {}
    dimensoes = info.get("dimensions", (info.get("config") or {}).get("dimensions"))
    if dimensoes != ambiente.dimensoes:
        raise ErroNuvem(f"Vectorize: índice com {dimensoes} dimensões (esperadas {ambiente.dimensoes}); nada enviado")
    indices = ambiente.vetores.indices_metadados()
    errados = [f"{nome} ({tipo})" for nome, tipo in sorted(INDICES_METADADOS.items()) if indices.get(nome) != tipo]
    if errados:
        raise ErroNuvem("Vectorize: faltam índices de metadados " + ", ".join(errados)
                        + " (npx wrangler vectorize create-metadata-index); nada enviado")


# ---------------------------------------------------------------- R2
def _r2_originais(ambiente: Ambiente, fonte: Fonte, atual: dict, cache: Path, simular: bool, rel: Relatorio,
                  avisar: Callable[[str], Any]) -> set[str]:
    """Envia originais em paralelo e devolve os arquivos em falha; grandes via REST só perdem o download."""
    conhecidos = {(linha[1], linha[6]) for linha in atual["arquivos"].values()}
    candidatos = [o for _, o in sorted(fonte.originais.items()) if (o.sha256, o.chave_r2) not in conhecidos]
    rel.plano["r2_verificar"] = len(candidatos)
    rel.plano["r2_enviar"] += 0
    condicional = getattr(ambiente.r2, "put_condicional", True)

    def tratar(original: Original) -> tuple[Original, str]:
        caminho = Path(cache) / "arquivos" / original.sha256
        if isinstance(ambiente.r2, R2Rest) and caminho.is_file() and caminho.stat().st_size > LIMITE_ENVIO_R2_REST:
            return original, "grande_demais"
        if ambiente.r2.existe(ambiente.bucket_arquivos, original.chave_r2):
            return original, "existe"
        dados = caminho.read_bytes() if caminho.is_file() else None
        if dados is None or sha256(dados) != original.sha256:
            return original, "falha"
        if simular:
            return original, "enviar"
        gravou = ambiente.r2.enviar(ambiente.bucket_arquivos, original.chave_r2, dados,
                                    tipo_conteudo(original.formato),
                                    {"documentos": documentos_meta(original.documentos)}, se_ausente=condicional)
        return original, "enviado" if gravou else "enviar"

    falhou: set[str] = set()
    falhas: list[tuple[str, str]] = []
    grandes: list[Original] = []
    if candidatos:
        with ThreadPoolExecutor(max_workers=TRABALHADORES_R2, thread_name_prefix="radar-r2") as pool:
            futuros = [pool.submit(tratar, o) for o in candidatos]
            try:
                for n, futuro in enumerate(as_completed(futuros), 1):
                    original, estado = futuro.result()
                    if estado == "grande_demais":
                        grandes.append(original)
                    elif estado == "falha":
                        falhas.append((original.sha256, f"original {original.sha256} ausente ou diferente no cache "
                                                        f"({', '.join(sorted(original.arquivos))})"))
                        falhou.update(original.arquivos)
                    elif estado in ("enviar", "enviado"):
                        rel.plano["r2_enviar"] += 1
                        if estado == "enviado":
                            rel.feitas["r2_enviar"] += 1
                    if n % PROGRESSO_R2 == 0 or n == len(futuros):
                        avisar(f"R2: {n}/{len(futuros)} originais conferidos")
            except BaseException:
                for futuro in futuros:
                    futuro.cancel()
                raise
    rel.falhas.extend(m for _, m in sorted(falhas))
    rel.plano["originais_grandes_demais"] = len(grandes)
    if grandes:
        indisponiveis = set()
        for original in sorted(grandes, key=lambda o: o.sha256):
            tamanho = (Path(cache) / "arquivos" / original.sha256).stat().st_size
            aviso = (f"original {original.chave_r2} ({', '.join(sorted(original.arquivos))}): {tamanho} bytes "
                     f"excedem o limite REST de {LIMITE_ENVIO_R2_REST} bytes; não enviado, r2_chave NULL no D1")
            rel.avisos.append(aviso)
            print(f"::warning::{aviso}", file=sys.stderr)
            indisponiveis.update(original.arquivos)
        # Só a disponibilidade do download muda: texto, FTS e vetores continuam publicados.
        # A versão/exportação também refletem o r2_chave efetivamente publicado.
        fonte.linhas["arquivos"] = {k: v[:6] + (None,) if k[0] in indisponiveis else v
                                    for k, v in fonte.linhas["arquivos"].items()}

    rel.plano["r2_apagar"] += 0
    for chave in sorted(fonte.remover_r2):
        if ambiente.r2.existe(ambiente.bucket_arquivos, chave):
            rel.plano["r2_apagar"] += 1
            if not simular:
                ambiente.r2.apagar(ambiente.bucket_arquivos, chave)
                rel.feitas["r2_apagar"] += 1
    return falhou


# ---------------------------------------------------------------- D1
def _sem_falhas(tabela: str, linhas: dict[tuple, tuple], falhou: set[str]) -> dict[tuple, tuple]:
    """Tira as linhas dos arquivos cujo original falhou (o D1 fica como estava para eles)."""
    if not falhou:
        return linhas
    if tabela in ("arquivos", "arquivo_documento"):
        return {k: v for k, v in linhas.items() if k[0] not in falhou}
    if tabela == "trechos":  # na linha completa e na projeção de COMPARAR, `arquivo` é a 3ª coluna
        return {k: v for k, v in linhas.items() if v[2] not in falhou}
    return linhas


def _linha_fts(trecho: tuple) -> tuple:
    return rowid_fts(trecho[0]), trecho[0], normalizar_busca(trecho[4])


def _textos_trechos(banco, ids: Sequence[str]) -> list[tuple]:
    """(id, texto) dos trechos já no D1 (para refazer o FTS de arquivos mantidos como estavam)."""
    saida: list[tuple] = []
    for i in range(0, len(ids), 100):
        lista = ", ".join(literal(x) for x in ids[i:i + 100])
        saida += [(r["id"], r["texto"]) for r in
                  banco.consultar(f"SELECT {q('id')} AS id, {q('texto')} AS texto FROM {q('trechos')} "
                                  f"WHERE {q('id')} IN ({lista})")]
    return saida


# ---------------------------------------------------------------- sincronização
def sincronizar(raiz: str | Path, textos: str | Path | None, ambiente: Ambiente, *, liberados,
                cache: str | Path, simular: bool = False, reconstruir: bool = False,
                exportar: str | Path | None = None, commit: str | None = None,
                commit_dados_textos: str | None = None,
                agora: Callable[[], datetime] | None = None, etapas: Iterable[str] | str | None = None,
                progresso: Callable[[str], Any] | None = None) -> Relatorio:
    """Leva o estado do Git à nuvem do `ambiente`; devolve o plano e o que foi feito.

    `etapas`: subconjunto de `r2`, `d1`, `vetores`, `exportar` (padrão: as três primeiras;
    `exportar` entra sozinho quando há `exportar`). Sem R2 no ambiente (`--sem-r2`), a etapa
    `r2` sai. Sobe `ErroBarreira` (PII), `coletor.nuvem.fonte.ErroFonte` (Git inconsistente) ou
    `ErroNuvem` (falha de chamada); nesses casos `estado_indice` não é gravado.
    """
    agora = agora or (lambda: datetime.now(timezone.utc))
    inicio = agora().astimezone(timezone.utc)
    avisar = progresso or (lambda texto: None)
    pedidas = set(etapas_validas(etapas))
    if exportar is not None:
        pedidas.add("exportar")
    rel = Relatorio(simulado=simular)
    if ambiente.r2 is None and "r2" in pedidas:
        pedidas.discard("r2")
        rel.avisos.append("etapa r2 pulada: sem R2 neste ambiente (--sem-r2)")
    rel.etapas = tuple(e for e in ETAPAS if e in pedidas)
    fonte = carregar_fonte(raiz, textos, liberados)
    rel.avisos.extend(fonte.avisos)

    # (a) barreira de PII, antes de qualquer escrita
    fortes, rel.fracas = varrer_fonte(fonte, liberados)
    if fortes:
        raise ErroBarreira(fortes)

    banco = ambiente.banco
    # (b) migrações (as tabelas são lidas por todas as etapas e gravadas por d1 e vetores)
    pendentes = banco.pendentes(ambiente.pasta_migracoes)
    rel.plano["migracoes"] = len(pendentes)
    if pendentes and not simular and pedidas & {"d1", "vetores"}:
        rel.feitas["migracoes"] += len(banco.migrar(ambiente.pasta_migracoes))

    # Simulação e etapa só R2 não aplicam a migração: projetar a nova coluna como NULL.
    atual = ler_atual(banco, sem_commit_dados_textos=("0005_estado_commit_dados_textos.sql" in pendentes
                                                    and (simular or not pedidas & {"d1", "vetores"})))
    estado = atual["estado_indice"]
    pasta_exportacoes = Path(exportar) if exportar is not None else Path(cache) / "exportacoes"
    expurgar = (("r2" in pedidas or "exportar" in pedidas)
                and _exportacoes_pendentes(fonte, atual, pasta_exportacoes, reconstruir))
    if reconstruir:
        indexados_antigos = atual["trechos_indexados"]
        atual = {t: {} for t in (*TABELAS_BASE, "ementas_fts")}
        atual.update({"estado_indice": None, "fts_divergente": False, "trechos_indexados": indexados_antigos})

    # (c) R2: originais que faltam e originais removidos
    falhou: set[str] = set()
    nao_conferidos: set[str] = set()
    if "r2" in pedidas:
        falhou = _r2_originais(ambiente, fonte, atual, Path(cache), simular, rel, avisar)
    else:  # sem a etapa r2, `r2_chave` só vai ao D1 para originais já conferidos (invariante do D1)
        conhecidos = {(linha[1], linha[6]) for linha in atual["arquivos"].values()}
        for original in fonte.originais.values():
            if (original.sha256, original.chave_r2) not in conhecidos:
                nao_conferidos.update(original.arquivos)
        if nao_conferidos:
            rel.avisos.append(f"{len(nao_conferidos)} arquivo(s) sem r2_chave no D1: o original não foi conferido "
                              "(etapa r2 fora desta execução)")

    # (d) D1: diferença das tabelas-base e FTS (calculada sempre: os vetores usam os apagados)
    refazer_fts = reconstruir or atual["fts_divergente"]
    alteracoes: list[Alteracao] = []
    if reconstruir:
        alteracoes += [Alteracao.de(t, limpar=True) for t in (*TABELAS_GIT, "estado_indice")]
        rel.plano["d1_limpar"] = len(TABELAS_GIT) + 2
    apagados: dict[str, list[tuple]] = {}
    for tabela in TABELAS_GIT:
        colunas, _ = COLUNAS[tabela]
        desejado = _sem_falhas(tabela, fonte.linhas[tabela], falhou)
        corrente = _sem_falhas(tabela, atual[tabela], falhou)
        if tabela == "arquivos" and nao_conferidos:
            desejado = {k: (v[:6] + (None,) if k[0] in nao_conferidos else v) for k, v in desejado.items()}
        projecao = [colunas.index(c) for c in COMPARAR[tabela]] if tabela in COMPARAR else None
        gravar = [linha for chave, linha in sorted(desejado.items())
                  if corrente.get(chave) != (tuple(linha[i] for i in projecao) if projecao else linha)]
        apagar = [chave for chave in sorted(corrente) if chave not in desejado]
        rel.plano[f"d1_{tabela}_gravar"] = len(gravar)
        rel.plano[f"d1_{tabela}_apagar"] = len(apagar)
        if tabela == "ementas_fts":
            # Compara o FTS real para retomar cargas interrompidas. Cada troca usa
            # DELETE por documento + INSERT na mesma unidade atômica (sem depender de rowid).
            rel.plano["d1_ementas_fts_apagar"] += sum((linha[0],) in corrente for linha in gravar)
        apagados[tabela] = apagar
        if tabela == "trechos":
            if not refazer_fts:  # cada bloco de trechos vai no mesmo lote atômico do seu FTS
                alteracoes.append(Alteracao.de(tabela, gravar, apagar, fts_linha=_linha_fts,
                                               fts_rowid=lambda chave: rowid_fts(chave[0])))
                rel.plano["d1_trechos_fts_gravar"] = len(gravar)
                rel.plano["d1_trechos_fts_apagar"] = len(apagar) + sum(1 for t in gravar
                                                                       if (t[0],) in atual["trechos"])
                continue
        alteracoes.append(Alteracao.de(tabela, gravar, apagar))
    if refazer_fts:
        if not reconstruir:
            rel.plano["d1_fts_reconstruir"] = 1
        alteracoes.append(Alteracao.de(FTS, limpar=True))
        desejados_trechos = _sem_falhas("trechos", fonte.linhas["trechos"], falhou)
        linhas_fts = [_linha_fts(desejados_trechos[k]) for k in sorted(desejados_trechos)]
        mantidos = sorted(k[0] for k, v in atual["trechos"].items() if v[2] in falhou)
        if mantidos and "d1" in pedidas and not simular:
            # arquivos com original em falha continuam com os trechos que já tinham (texto lido do D1)
            linhas_fts += [(rowid_fts(i), i, normalizar_busca(texto)) for i, texto in _textos_trechos(banco, mantidos)]
        alteracoes.append(Alteracao.de(FTS, gravar=linhas_fts))
        rel.plano["d1_trechos_fts_gravar"] = len(desejados_trechos) + len(mantidos)
    # Não confirmar a remoção no D1/estado antes do histórico: a diferença é
    # também o sinal durável para retomar recibos em outra máquina, sem cache local.
    if expurgar:
        _expurgar_exportacoes(fonte, ambiente, Path(raiz), pasta_exportacoes, rel, simular)
    if "d1" in pedidas and not simular and any(not a.vazia() for a in alteracoes):
        rel.feitas["d1_instrucoes"] += banco.aplicar(alteracoes)

    # (e) Vectorize
    if "vetores" in pedidas:
        _vetores(ambiente, fonte, atual, estado, falhou, apagados, reconstruir, simular, inicio, rel)

    # (f) estado_indice: só no fim, sem falhas e com as etapas que formam uma sincronização completa
    rel.versao = calcular_versao(fonte, ambiente.modelo)
    if rel.falhas:
        rel.avisos.append("estado_indice não gravado: a sincronização teve falhas")
        return rel
    if not ETAPAS_COMPLETAS <= pedidas:
        rel.plano["estado_indice"] = 0
        rel.avisos.append("estado_indice não gravado: etapas parciais (" + ",".join(rel.etapas) + ")")
    else:
        conjunto = hashlib.sha256("".join(f"{i} {fonte.trechos[i].sha256}\n" for i in sorted(fonte.trechos))
                                  .encode("utf-8")).hexdigest()
        data = agora().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        novo = (1, rel.versao, commit, fonte.sha256_manifestos, len(fonte.trechos), conjunto, ambiente.modelo,
                VERSAO_TRECHOS, data, commit_dados_textos)
        # Ambos os commits entram na comparação; só a data fica fora.
        if reconstruir or estado is None or tuple(estado[:8]) + tuple(estado[9:]) != novo[:8] + novo[9:]:
            rel.plano["estado_indice"] = 1
            if not simular:
                banco.aplicar([Alteracao.de("estado_indice", gravar=[novo])])
                rel.feitas["estado_indice"] += 1
                rel.estado_gravado = True
        else:
            rel.plano["estado_indice"] = 0

    # (g) exportação
    if "exportar" in pedidas:
        _exportar(fonte, ambiente, rel.versao, pasta_exportacoes, rel, simular)
    return rel


def _vetores(ambiente: Ambiente, fonte: Fonte, atual: dict, estado, falhou: set[str],
             apagados: dict[str, list[tuple]], reconstruir: bool, simular: bool, inicio: datetime,
             rel: Relatorio) -> None:
    banco = ambiente.banco
    conferir_indice(ambiente)  # pré-voo (só leituras), antes de qualquer embedding
    # ids de arquivos com original em falha: nem enviados nem apagados nesta execução
    congelados = {t.id for t in fonte.trechos.values() if t.arquivo in falhou}
    congelados |= {k[0] for k, v in atual["trechos"].items() if v[2] in falhou}
    desejados = {i: v for i, v in fonte.vetores.items() if i not in congelados}
    alvo = {i: sha_indexado(v[0], v[1]) for i, v in desejados.items()}
    indexados = {chave[0]: linha[1] for chave, linha in atual["trechos_indexados"].items()}
    reembeddar = reconstruir or (estado is not None and estado[6] != ambiente.modelo)
    novos = [i for i in sorted(alvo) if reembeddar or indexados.get(i) != alvo[i]]
    candidatos = set(indexados)
    candidatos |= {k[0] for k in apagados.get("trechos", [])}
    candidatos |= {f"ementa:{k[0]}" for k in apagados.get("documentos", [])}
    if reconstruir:  # o índice inteiro: também vetores órfãos que nunca entraram em trechos_indexados
        candidatos |= set(ambiente.vetores.listar_ids())
    removidos = sorted(i for i in candidatos if i not in fonte.vetores and i not in congelados)
    rel.plano["vetores_upsert"] = len(novos)
    rel.plano["vetores_apagar"] = len(removidos)
    cache_emb = ambiente.cache_embeddings
    rel.plano["embeddings"] = sum(1 for i in novos if not (cache_emb and cache_emb.obter(desejados[i][0])))
    if simular:
        return
    ultima = None
    enviados: list[str] = []
    if removidos:
        mutacoes = ambiente.vetores.apagar(removidos)
        ultima = mutacoes[-1] if mutacoes else ultima
        rel.feitas["vetores_apagar"] += len(removidos)
        rel.feitas["d1_instrucoes"] += banco.aplicar(
            [Alteracao.de("trechos_indexados", apagar=[(i,) for i in removidos])])
    for bloco in _blocos(novos, LOTE_SINCRONIZACAO):
        valores = _embeddings(ambiente, [(desejados[i][0], desejados[i][2]) for i in bloco], rel)
        # registrados antes do upsert: um vetor enviado nunca fica fora de trechos_indexados (e sai
        # do índice se o Git deixar de tê-lo); os já registrados mantêm o hash antigo até o fim
        sem_registro = [(i, PENDENTE) for i in bloco if i not in indexados]
        if sem_registro:
            rel.feitas["d1_instrucoes"] += banco.aplicar([Alteracao.de("trechos_indexados", gravar=sem_registro)])
        mutacoes = ambiente.vetores.upsert(
            [{"id": i, "values": v, "metadata": desejados[i][1]} for i, v in zip(bloco, valores)])
        ultima = mutacoes[-1] if mutacoes else ultima
        rel.feitas["vetores_upsert"] += len(bloco)
        enviados.extend(bloco)
    # sempre: confere que as mutações desta execução foram processadas antes de gravar o estado
    ambiente.vetores.esperar(ultima, desde=inicio - FOLGA_RELOGIO if ultima is not None else None)
    # hashes finais só depois de o índice confirmar (e, no local, persistir) os vetores: uma
    # interrupção antes disso deixa PENDENTE ou o hash antigo, e a próxima execução reenvia
    for bloco in _blocos(enviados, LOTE_SINCRONIZACAO):
        rel.feitas["d1_instrucoes"] += banco.aplicar(
            [Alteracao.de("trechos_indexados", gravar=[(i, alvo[i]) for i in bloco])])
