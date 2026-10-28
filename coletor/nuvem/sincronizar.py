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
   divergirem (duas consultas `LIMIT 1`), o FTS é refeito;
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
   reenviado (e um conteúdo diferente vira aviso);
h. `--reconstruir`: limpa o D1, reenvia tudo (com o cache de embeddings) e apaga do índice
   todo vetor listado que o Git não tem;
i. `--simular`: só leituras; o plano é o mesmo, sem nenhuma escrita.

Uma segunda execução sem mudanças no Git, no mesmo commit, não faz nenhuma escrita (um commit
novo regrava `estado_indice`, que guarda o commit).
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from coletor.nuvem.banco import (COLUNAS, COMPARAR, FTS, PASTA_MIGRACOES, TABELAS_BASE, Alteracao, fts_divergente,
                                 ler_tabela, literal, q)
from coletor.nuvem.cloudflare import DIMENSOES, INDICES_METADADOS
from coletor.nuvem.fonte import (Fonte, Original, carregar_fonte, normalizar_busca, rowid_fts, sha256, sha_indexado,
                                 varrer_fonte)
from coletor.nuvem.local import CacheEmbeddings, como_float32, empacotar
from coletor.nuvem.r2 import LIMITE_ENVIO_R2_REST, R2Rest
from coletor.nuvem.rede import ErroNuvem
from coletor.trechos import VERSAO_TRECHOS

LOTE_SINCRONIZACAO = 500  # vetores por rodada de embeddings + upsert + trechos_indexados
TABELAS_GIT = tuple(t for t in TABELAS_BASE if t != "trechos_indexados")
ETAPAS = ("r2", "d1", "vetores", "exportar")
ETAPAS_PADRAO = ("r2", "d1", "vetores")
ETAPAS_COMPLETAS = frozenset({"r2", "d1", "vetores"})  # necessárias para gravar estado_indice
PENDENTE = "pendente"  # trechos_indexados.sha256 de um vetor com upsert em curso
TRABALHADORES_R2 = 4
PROGRESSO_R2 = 100  # um aviso de progresso a cada N originais
FOLGA_RELOGIO = timedelta(seconds=60)  # diferença tolerada entre o relógio local e o do Vectorize
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
    atual["fts_divergente"] = fts_divergente(banco)
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
    if faltam:  # get_by_ids em lotes de 100, no ritmo global da API
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
    for nome, dados in sorted(arquivos.items()):
        local = destino / nome
        if not local.is_file() or local.read_bytes() != dados:
            local.write_bytes(dados)
    if ambiente.r2 is None:
        rel.avisos.append(f"exportação {versao}: gravada só em {destino} (sem R2)")
        return
    rel.exportados.extend(f"{versao}/{nome}" for nome in sorted(arquivos, key=lambda n: (n == "SHA256SUMS", n)))
    no_bucket = ambiente.r2.obter(ambiente.bucket_exportacoes, f"{versao}/SHA256SUMS")
    if no_bucket is not None:  # a versão já foi publicada inteira: nada é reenviado
        if no_bucket != arquivos["SHA256SUMS"]:
            rel.avisos.append(f"exportação {versao}: o SHA256SUMS do bucket difere do gerado agora; "
                              "nada foi reenviado (confira o determinismo da exportação)")
        return
    condicional = getattr(ambiente.r2, "put_condicional", True)
    # SHA256SUMS por último: quem o encontra no bucket encontra também os arquivos que ele lista
    for nome in sorted(arquivos, key=lambda n: (n == "SHA256SUMS", n)):
        tipo = TIPOS_EXPORTACAO.get(Path(nome).suffix, "text/plain; charset=utf-8")
        if ambiente.r2.enviar(ambiente.bucket_exportacoes, f"{versao}/{nome}", arquivos[nome], tipo,
                              se_ausente=condicional):
            rel.feitas["exportacao_enviar"] += 1


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

    atual = ler_atual(banco)
    estado = atual["estado_indice"]
    if reconstruir:
        indexados_antigos = atual["trechos_indexados"]
        atual = {t: {} for t in TABELAS_BASE}
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
                VERSAO_TRECHOS, data)
        # o commit faz parte da comparação: um commit novo regrava a linha, mesmo sem outra mudança
        if reconstruir or estado is None or tuple(estado[:8]) != novo[:8]:
            rel.plano["estado_indice"] = 1
            if not simular:
                banco.aplicar([Alteracao.de("estado_indice", gravar=[novo])])
                rel.feitas["estado_indice"] += 1
                rel.estado_gravado = True
        else:
            rel.plano["estado_indice"] = 0

    # (g) exportação
    if "exportar" in pedidas:
        _exportar(fonte, ambiente, rel.versao, Path(exportar) if exportar is not None
                  else Path(cache) / "exportacoes", rel, simular)
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
