"""Sincronização do Git com D1, Vectorize e R2 (plano T2.2.1 S3, passos a–i).

Ordem de uma execução:

a. barreira de PII: `mascara.varrer` em todo trecho e ementa a enviar; uma ocorrência
   forte aborta antes de qualquer escrita (`ErroBarreira`, sem os valores);
b. migrações pendentes de `worker/migrations/`;
c. R2: originais que faltam (HEAD antes; bytes do cache `RADAR_CACHE/arquivos/<sha256>`,
   conferidos pelo hash), enviados com `If-None-Match: *`; originais removidos saem;
d. D1: diferença das tabelas-base contra o Git (gravar o que mudou, apagar o que saiu do
   Git ou entrou em `config/remocoes.json`) e o FTS dos trechos alterados;
e. Vectorize: vetores só dos trechos vetorizáveis novos ou alterados (diferença contra
   `trechos_indexados` pelo sha256) e das ementas de indicações e moções
   (`ementa:doc:<id>`); ids que saíram são apagados; espera o processamento;
f. `estado_indice`, gravado só no fim e só sem falhas;
g. `--exportar`: dump das tabelas-base, vetores em JSONL gzip (mtime 0) e `SHA256SUMS`,
   enviados com `If-None-Match: *` a `<bucket de exportações>/<versao>/`;
h. `--reconstruir`: limpa o D1 e reenvia tudo (com o cache de embeddings);
i. `--simular`: só leituras; o plano é o mesmo, sem nenhuma escrita.

Uma segunda execução sem mudanças no Git não faz nenhuma escrita.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from coletor.nuvem.banco import (COLUNAS, COMPARAR, FTS, PASTA_MIGRACOES, TABELAS_BASE, Alteracao, ler_tabela,
                                 literal, q)
from coletor.nuvem.cloudflare import DIMENSOES
from coletor.nuvem.fonte import Fonte, carregar_fonte, normalizar_busca, rowid_fts, sha256, varrer_fonte
from coletor.nuvem.local import CacheEmbeddings, como_float32, empacotar
from coletor.nuvem.rede import ErroNuvem
from coletor.trechos import VERSAO_TRECHOS

LOTE_SINCRONIZACAO = 500  # vetores por rodada de embeddings + upsert + trechos_indexados
TABELAS_GIT = tuple(t for t in TABELAS_BASE if t != "trechos_indexados")
ESCRITAS = ("migracoes", "r2_enviar", "r2_apagar", "d1_instrucoes", "vetores_upsert", "vetores_apagar",
            "estado_indice", "exportacao_enviar")
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
    """Ocorrência forte de dado pessoal num trecho ou ementa; a mensagem não traz os valores."""

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
    r2: Any
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

    @property
    def escritas(self) -> int:
        return sum(self.feitas[k] for k in ESCRITAS)

    def texto(self) -> str:
        titulo = "Plano (simulação: nada foi gravado)" if self.simulado else "Plano"
        linhas = [f"{titulo}:"]
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


# ---------------------------------------------------------------- estado atual
def ler_atual(banco) -> dict[str, Any]:
    existentes = banco.tabelas()
    atual: dict[str, Any] = {}
    for tabela in TABELAS_BASE:
        colunas, chave = COLUNAS[tabela]
        atual[tabela] = ler_tabela(banco, tabela, COMPARAR.get(tabela, colunas), chave) if tabela in existentes else {}
    atual["estado_indice"] = None
    if "estado_indice" in existentes:
        colunas = COLUNAS["estado_indice"][0]
        linhas = banco.consultar(f"SELECT {', '.join(q(c) for c in colunas)} FROM {q('estado_indice')} "
                                 f"WHERE {q('id')} = 1")
        if linhas:
            atual["estado_indice"] = tuple(linhas[0][c] for c in colunas)
    atual["fts"] = (banco.consultar(f"SELECT count(*) AS n FROM {FTS}")[0]["n"] if FTS in existentes else 0)
    return atual


# ---------------------------------------------------------------- versão e exportação
def linhas_dump(fonte: Fonte) -> Iterable[str]:
    """Dump determinístico das tabelas-base (ordem de tabela e de chave primária), sem o FTS."""
    yield "-- Radar dos Vereadores de Niterói: tabelas-base do D1 (docs/contratos/textos.md, seção 8.1).\n"
    yield "-- trechos_fts é reconstruível (python -m coletor.nuvem --reconstruir) e fica fora.\n"
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


def _valores_vetores(ambiente: Ambiente, fonte: Fonte, ids: Sequence[str]) -> dict[str, list[float]]:
    valores: dict[str, list[float]] = {}
    faltam = []
    for i in ids:
        v = ambiente.cache_embeddings.obter(fonte.vetores[i][0]) if ambiente.cache_embeddings else None
        if v is not None and len(v) == ambiente.dimensoes:
            valores[i] = v
        else:
            faltam.append(i)
    if faltam:
        for item in ambiente.vetores.obter(faltam):
            valores[item["id"]] = como_float32(item["values"])
    ausentes = [i for i in ids if i not in valores]
    if ausentes:
        raise ErroNuvem(f"{len(ausentes)} vetor(es) sem valores para a exportação (ex.: {ausentes[0]})")
    return valores


def montar_exportacao(fonte: Fonte, ambiente: Ambiente, versao: str) -> dict[str, bytes]:
    """`d1-<versao>.sql`, `vetores-<versao>.jsonl.gz` e `SHA256SUMS` (formato do sha256sum)."""
    dump = "".join(linhas_dump(fonte)).encode("utf-8")
    ids = sorted(fonte.vetores)
    valores = _valores_vetores(ambiente, fonte, ids)
    jsonl = "".join(json.dumps({"id": i, "metadata": fonte.vetores[i][1], "values": empacotar(valores[i])},
                               ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for i in ids)
    arquivos = {f"d1-{versao}.sql": dump, f"vetores-{versao}.jsonl.gz": gzip_deterministico(jsonl.encode("utf-8"))}
    arquivos["SHA256SUMS"] = "".join(f"{sha256(dados)}  {nome}\n" for nome, dados in sorted(arquivos.items())
                                     ).encode("ascii")
    return arquivos


TIPOS_EXPORTACAO = {".sql": "application/sql; charset=utf-8", ".gz": "application/gzip"}


def _exportar(fonte: Fonte, ambiente: Ambiente, versao: str, pasta: Path, rel: Relatorio, simular: bool) -> None:
    rel.plano["exportacao_arquivos"] += 3
    if simular:
        return
    arquivos = montar_exportacao(fonte, ambiente, versao)
    destino = Path(pasta) / versao
    destino.mkdir(parents=True, exist_ok=True)
    # SHA256SUMS por último: quem o encontra no bucket encontra também os arquivos que ele lista
    for nome in sorted(arquivos, key=lambda n: (n == "SHA256SUMS", n)):
        dados = arquivos[nome]
        local = destino / nome
        if not local.is_file() or local.read_bytes() != dados:
            local.write_bytes(dados)
        tipo = TIPOS_EXPORTACAO.get(Path(nome).suffix, "text/plain; charset=utf-8")
        if ambiente.r2.enviar(ambiente.bucket_exportacoes, f"{versao}/{nome}", dados, tipo, se_ausente=True):
            rel.feitas["exportacao_enviar"] += 1
        rel.exportados.append(f"{versao}/{nome}")


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


# ---------------------------------------------------------------- sincronização
def sincronizar(raiz: str | Path, textos: str | Path | None, ambiente: Ambiente, *, liberados,
                cache: str | Path, simular: bool = False, reconstruir: bool = False,
                exportar: str | Path | None = None, commit: str | None = None,
                agora: Callable[[], datetime] | None = None) -> Relatorio:
    """Leva o estado do Git à nuvem do `ambiente`; devolve o plano e o que foi feito.

    Sobe `ErroBarreira` (PII), `coletor.nuvem.fonte.ErroFonte` (Git inconsistente) ou
    `ErroNuvem` (falha de chamada); nesses casos `estado_indice` não é gravado.
    """
    agora = agora or (lambda: datetime.now(timezone.utc))
    rel = Relatorio(simulado=simular)
    fonte = carregar_fonte(raiz, textos, liberados)
    rel.avisos.extend(fonte.avisos)

    # (a) barreira de PII, antes de qualquer escrita
    fortes, rel.fracas = varrer_fonte(fonte, liberados)
    if fortes:
        raise ErroBarreira(fortes)

    banco = ambiente.banco
    # (b) migrações
    pendentes = banco.pendentes(ambiente.pasta_migracoes)
    rel.plano["migracoes"] = len(pendentes)
    if pendentes and not simular:
        rel.feitas["migracoes"] += len(banco.migrar(ambiente.pasta_migracoes))

    atual = ler_atual(banco)
    estado = atual["estado_indice"]
    if reconstruir:
        indexados_antigos = atual["trechos_indexados"]
        atual = {t: {} for t in TABELAS_BASE}
        atual.update({"estado_indice": None, "fts": 0, "trechos_indexados": indexados_antigos})

    # (c) R2: originais que faltam e originais removidos
    falhou_r2: set[str] = set()
    conhecidos = {(linha[1], linha[6]) for linha in atual["arquivos"].values()}
    candidatos = [o for _, o in sorted(fonte.originais.items()) if (o.sha256, o.chave_r2) not in conhecidos]
    rel.plano["r2_verificar"] = len(candidatos)
    rel.plano["r2_enviar"] += 0
    for original in candidatos:
        if ambiente.r2.existe(ambiente.bucket_arquivos, original.chave_r2):
            continue
        caminho = Path(cache) / "arquivos" / original.sha256
        dados = caminho.read_bytes() if caminho.is_file() else None
        if dados is None or sha256(dados) != original.sha256:
            rel.falhas.append(f"original {original.sha256} ausente ou diferente no cache "
                              f"({', '.join(sorted(original.arquivos))})")
            falhou_r2.update(original.arquivos)
            continue
        rel.plano["r2_enviar"] += 1
        if not simular:
            documentos = ",".join(sorted(original.documentos))[:MAX_META_DOCUMENTOS]
            if ambiente.r2.enviar(ambiente.bucket_arquivos, original.chave_r2, dados, tipo_conteudo(original.formato),
                                  {"documentos": documentos}, se_ausente=True):
                rel.feitas["r2_enviar"] += 1
    rel.plano["r2_apagar"] += 0
    for chave in sorted(fonte.remover_r2):
        if ambiente.r2.existe(ambiente.bucket_arquivos, chave):
            rel.plano["r2_apagar"] += 1
            if not simular:
                ambiente.r2.apagar(ambiente.bucket_arquivos, chave)
                rel.feitas["r2_apagar"] += 1

    # (d) D1: diferença das tabelas-base e FTS
    alteracoes: list[Alteracao] = []
    if reconstruir:
        alteracoes += [Alteracao.de(t, limpar=True) for t in (*TABELAS_GIT, "estado_indice")]
        alteracoes.append(Alteracao.de(FTS, limpar=True))
        rel.plano["d1_limpar"] = len(TABELAS_GIT) + 2
    gravados_trechos: list[tuple] = []
    apagados_trechos: list[tuple] = []
    for tabela in TABELAS_GIT:
        colunas, _ = COLUNAS[tabela]
        desejado = fonte.linhas[tabela]
        corrente = atual[tabela]
        if tabela == "arquivos" and falhou_r2:  # sem o original no R2, a linha do arquivo fica como está
            desejado = {k: v for k, v in desejado.items() if k[0] not in falhou_r2}
            corrente = {k: v for k, v in corrente.items() if k[0] not in falhou_r2}
        projecao = [colunas.index(c) for c in COMPARAR[tabela]] if tabela in COMPARAR else None
        gravar = [linha for chave, linha in sorted(desejado.items())
                  if corrente.get(chave) != (tuple(linha[i] for i in projecao) if projecao else linha)]
        apagar = [chave for chave in sorted(corrente) if chave not in desejado]
        rel.plano[f"d1_{tabela}_gravar"] = len(gravar)
        rel.plano[f"d1_{tabela}_apagar"] = len(apagar)
        alteracoes.append(Alteracao.de(tabela, gravar, apagar))
        if tabela == "trechos":
            gravados_trechos, apagados_trechos = gravar, apagar
    if reconstruir or atual["fts"] != len(atual["trechos"]):
        if not reconstruir:
            rel.plano["d1_fts_reconstruir"] = 1
            alteracoes.append(Alteracao.de(FTS, limpar=True))
        todos = [fonte.linhas["trechos"][k] for k in sorted(fonte.linhas["trechos"])]
        alteracoes.append(Alteracao.de(FTS, gravar=[(rowid_fts(t[0]), t[0], normalizar_busca(t[4])) for t in todos]))
        rel.plano["d1_trechos_fts_gravar"] = len(todos)
    else:
        apagar_fts = [(rowid_fts(k[0]),) for k in apagados_trechos]
        apagar_fts += [(rowid_fts(t[0]),) for t in gravados_trechos if (t[0],) in atual["trechos"]]
        gravar_fts = [(rowid_fts(t[0]), t[0], normalizar_busca(t[4])) for t in gravados_trechos]
        rel.plano["d1_trechos_fts_gravar"] = len(gravar_fts)
        rel.plano["d1_trechos_fts_apagar"] = len(apagar_fts)
        alteracoes.append(Alteracao.de(FTS, gravar=gravar_fts, apagar=apagar_fts))
    if not simular and any(not a.vazia() for a in alteracoes):
        rel.feitas["d1_instrucoes"] += banco.aplicar(alteracoes)

    # (e) Vectorize
    desejados = fonte.vetores
    indexados = {chave[0]: linha[1] for chave, linha in atual["trechos_indexados"].items()}
    reembeddar = reconstruir or (estado is not None and estado[6] != ambiente.modelo)
    novos = [i for i in sorted(desejados) if reembeddar or indexados.get(i) != desejados[i][0]]
    removidos = [i for i in sorted(indexados) if i not in desejados]
    rel.plano["vetores_upsert"] = len(novos)
    rel.plano["vetores_apagar"] = len(removidos)
    cache_emb = ambiente.cache_embeddings
    rel.plano["embeddings"] = sum(1 for i in novos if not (cache_emb and cache_emb.obter(desejados[i][0])))
    if not simular:
        ultima = None
        if removidos:
            mutacoes = ambiente.vetores.apagar(removidos)
            ultima = mutacoes[-1] if mutacoes else ultima
            rel.feitas["vetores_apagar"] += len(removidos)
            rel.feitas["d1_instrucoes"] += banco.aplicar(
                [Alteracao.de("trechos_indexados", apagar=[(i,) for i in removidos])])
        for bloco in _blocos(novos, LOTE_SINCRONIZACAO):
            valores = _embeddings(ambiente, [(desejados[i][0], desejados[i][2]) for i in bloco], rel)
            mutacoes = ambiente.vetores.upsert(
                [{"id": i, "values": v, "metadata": desejados[i][1]} for i, v in zip(bloco, valores)])
            ultima = mutacoes[-1] if mutacoes else ultima
            rel.feitas["vetores_upsert"] += len(bloco)
            # o upsert aceito é durável: o progresso fica registrado mesmo se a execução parar depois
            rel.feitas["d1_instrucoes"] += banco.aplicar(
                [Alteracao.de("trechos_indexados", gravar=[(i, desejados[i][0]) for i in bloco])])
        if ultima is not None:
            ambiente.vetores.esperar(ultima)

    # (f) estado_indice: só no fim e só sem falhas
    rel.versao = calcular_versao(fonte, ambiente.modelo)
    if rel.falhas:
        rel.avisos.append("estado_indice não gravado: a sincronização teve falhas")
        return rel
    conjunto = hashlib.sha256("".join(f"{i} {fonte.trechos[i].sha256}\n" for i in sorted(fonte.trechos))
                              .encode("utf-8")).hexdigest()
    data = agora().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    novo = (1, rel.versao, commit, fonte.sha256_manifestos, len(fonte.trechos), conjunto, ambiente.modelo,
            VERSAO_TRECHOS, data)
    if reconstruir or estado is None or tuple(estado[:8]) != novo[:8]:
        rel.plano["estado_indice"] = 1
        if not simular:
            banco.aplicar([Alteracao.de("estado_indice", gravar=[novo])])
            rel.feitas["estado_indice"] += 1
            rel.estado_gravado = True
    else:
        rel.plano["estado_indice"] = 0

    # (g) exportação
    if exportar is not None:
        _exportar(fonte, ambiente, rel.versao, Path(exportar), rel, simular)
    return rel
