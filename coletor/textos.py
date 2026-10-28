"""Pipeline do inteiro teor: fila, download, extração, limpeza, máscara, trechos e manifesto.

Implementa `docs/contratos/textos.md` (o contrato prevalece sobre este resumo):

- **Fila** (seção 2.3): os `arquivos` dos PLs e dos seus substitutivos
  (`data/proposicoes/`), de requerimentos, PDLs e resoluções
  (`data/documentos/{requerimento,pdl,resolucao}/`) e as atas (`documentos_sessao` com
  `rotulo` em `ROTULOS_ATA` e `url` não nula, `data/sessoes/`). Indicações e moções
  ficam fora. Uma entrada por arquivo, com os documentos citantes e o documento
  principal (o PL para arquivos do PL ou de qualquer substitutivo).
- **Trabalho incremental**: entram as chaves fora do manifesto, as reprocessáveis
  (`pendente_download`, `pendente_ferramenta`, `escaneado_sem_ocr`/`ok_parcial` com
  `--ocr`, `removido` cuja remoção saiu de `config/remocoes.json`), as com
  `sha256_config` diferente (sempre), as com `.txt` ausente no disco (o texto é
  regenerado) e, com `--reprocessar-versao`, as com `versao_*` diferente.
  `--max-arquivos` (0 = sem limite) e `--max-minutos` limitam o trabalho; o resto
  fica para outra execução.
- **Reconstrução sem extração**: cada extração fica no cache local
  (`<cache>/texto_bruto/<sha256>.txt`, o texto bruto, e `<sha256>.json`, os demais
  campos do `Resultado`). Quando o reprocessamento vem de configuração, versão da
  limpeza/máscara/trechos, `.txt` ausente, mudança de ementa ou de documento
  principal, e `extrator`/`versao_extrator` do cache coincidem com os locais (e
  `versao_extratores` com a do código), o texto é refeito a partir do bruto, sem
  reextrair nem refazer OCR; essas chaves vêm primeiro e ficam fora de `--max-arquivos`.
- **Ementa usada na limpeza**: `<cache>/textos_ementas.json` guarda chave → SHA-256 da
  ementa passada a `limpeza.limpar`; se a ementa do principal muda, a entrada é
  reprocessada (arquivo interno do cache, fora do contrato).
- **Remoções** (seção 6.1): pela chave, sem download; pelo SHA-256, baixado só para o
  hash e descartado (sem cache). Uma entrada que vira `removido` apaga o original
  local, o texto bruto e as páginas do OCR daquele SHA-256 (se nenhuma outra entrada
  não removida usa o mesmo original).
- **Download**: `Download.aspx?id=<id>` ou a URL da ata, com o User-Agent de
  `coletor.siscam`, tentativas e espera progressiva, em `--workers` (4) linhas.
  Corpo diferente do `Content-Length`, `text/html` vindo do `Download.aspx` (página de
  erro) e `http.client.HTTPException` (como `IncompleteRead`) são tentados de novo;
  acima de `MAX_BYTES_DOWNLOAD` (250 MB), falha sem repetir.
  Originais em `<cache>/arquivos/<sha256>`; mapa chave → SHA-256 em
  `<cache>/textos_sha256.json` (lidos também `siscam_arquivos_sha256.json` e
  `atas_cache_sha256.json`, do levantamento), para não baixar de novo; com
  `--sem-rede`, só o cache (sem ele, `pendente_download`).
- **Processamento** (seção 1): `extrair` (OCR com `--ocr`, páginas e imagens em
  `<cache>/ocr`) → bruto → `limpeza.limpar` → `mascara.mascarar` →
  `trechos.normalizar` → `trechos.dividir`, com a barreira `mascara.varrer`: texto com
  ocorrência forte não é gravado (a chave fica como estava e é listada, sem o valor).
  O `detalhe` também passa por `mascarar` e, se `varrer` ainda achar algo, vira
  `"[detalhe omitido]"`. Exceções de extração e processamento são registradas só
  pelo tipo e pela chave, nunca pela mensagem.
- **Duplicatas** (seção 6.2): mesmo original sob várias chaves → a menor é a
  canônica, com a união dos documentos; as outras viram `duplicata`. Uma chave em dois
  manifestos é avisada; fica a entrada do ano do documento principal atual.
- **Gravação**: `.txt` e `trechos/<tipo>/<ano>.jsonl` na branch `dados-textos`
  (`--textos DIR`) e `data/textos/manifesto-<ano>.json` por `arquivos.salvar_mapa`.
  `processado_em` só muda com a regra da seção 9. Mesma entrada, mesmos bytes.
  Só saem os `.txt` e as linhas de trechos que pertenciam a entradas anteriores do
  manifesto e deixaram de ser esperados; arquivos e linhas desconhecidos ficam, com
  `::warning::`.
- **Travas**: `.radar-textos.lock` (criado com O_EXCL, com o pid e a raiz do
  repositório) na pasta dos textos e no cache, em todo modo que grava; trava de um
  processo encerrado só é substituída com `--forcar-trava`. `.radar-raiz` liga a pasta
  dos textos a uma raiz de repositório (caminho absoluto); outra raiz aborta, salvo com
  `--forcar-trava`. A pasta dos textos recebe `.gitattributes` com `* -text`.
- **Pontos de controle**: a cada `CHECKPOINT_COMPONENTES` (200) grupos ou
  `CHECKPOINT_SEGUNDOS` (10 min), e no fim, grava (de forma idempotente) textos novos,
  trechos e manifestos, nesta ordem, e só depois apaga os órfãos (falhas viram avisos)
  e salva os mapas do cache. SIGTERM, SIGBREAK (Windows) ou Ctrl+C gravam o que já
  foi concluído (cada grupo de chaves ligadas por duplicatas entra inteiro ou não
  entra).
- **`--so-extrair`**: só baixa e extrai para o cache (`texto_bruto`), sem limpeza,
  manifesto nem textos; a execução normal seguinte reaproveita essas extrações.
- **`--commit-textos`**: depois do processamento, roda `mascara.varrer` em todos os
  `.txt` novos ou alterados (em todos, se `sha256_config` ou `VERSAO_MASCARA` mudou
  desde o último commit, conforme `<cache>/textos_commit.json`) e só faz o commit em
  `dados-textos` sem nenhuma ocorrência forte.
  **Decisão S6**: o manifesto não guarda o SHA do commit de `dados-textos` (o
  histórico dessa branch é reescrito no expurgo, T4.2.4); cada texto é identificado
  por `blob_texto` (SHA-1 do blob do Git), que vale em qualquer commit.
- **`--verificar [--amostra N]`**: confere `sha256_texto`, `blob_texto`, `chars` e
  os trechos de todas as entradas, aponta `.txt` órfãos, roda `mascara.varrer` em
  todos os textos (ocorrência forte = falha) e reextrai uma amostra do cache,
  comparando `sha256_bruto` só quando `extrator` e `versao_extrator` coincidem com os
  locais; entradas com OCR ficam "não comparável" (o OCR não é refeito). Não grava
  nada, nem no cache. O R2 fica para `coletor.nuvem`.

Uso (na raiz):
  python -m coletor.textos [--anos 2021-2026] [--tipos pl,requerimento,pdl,resolucao,ata]
      [--max-arquivos 500] [--max-minutos N] [--ocr] [--sem-rede] [--reprocessar-versao]
      [--textos DIR] [--cache DIR] [--workers 4] [--commit-textos] [--forcar-trava]
  python -m coletor.textos --so-extrair [--anos …] [--tipos …] [--max-arquivos N] [--ocr]
  python -m coletor.textos --verificar [--amostra 20] [--textos DIR] [--cache DIR]
Somente biblioteca padrão do Python.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import contextlib
import datetime as dt
import hashlib
import http.client
import json
import os
import random
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from . import arquivos, extratores, limpeza, mascara, remocoes, trechos
from .extratores import VERSAO_EXTRATORES, Resultado

RAIZ = Path(__file__).resolve().parent.parent
ROTULOS_ATA = frozenset({"Ata"})
TIPOS_COM_TEXTO = ("requerimento", "pdl", "resolucao")  # além de PLs, substitutivos e atas
TIPOS = ("pl", "requerimento", "pdl", "resolucao", "ata")  # tipos do documento principal
PRIORIDADE_TIPO = {"pl": 0, "requerimento": 1, "pdl": 2, "resolucao": 3, "ata": 4}
STATUS_COM_TEXTO = ("ok", "ok_ocr", "ok_parcial", "ocr_baixa_confianca")
SEM_PROCESSAMENTO = ("removido", "pendente_download", "duplicata")
URL_DOWNLOAD = "https://consultaniteroi.siscam.com.br/Download.aspx?id={id}"
ESVAZIADO = "esvaziado pela limpeza"
DETALHE_OMITIDO = "[detalhe omitido]"
RE_CHAVE = re.compile(
    r"^(siscam:[1-9][0-9]*|sessao:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
)
RE_GUID = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")
RE_SHA = re.compile(r"^[0-9a-f]{64}$")
RE_MANIFESTO = re.compile(r"^manifesto-(\d{4})\.json$")
CAMPOS_PROCESSADO_EM = (
    "sha256_original", "versao_extrator", "versao_extratores", "versao_limpeza", "versao_mascara",
    "versao_trechos", "sha256_config", "status", "sha256_texto",
)
MAX_ARQUIVOS = 500
AMOSTRA = 20
TENTATIVAS = 5
ESPERA = 2.0  # segundos, multiplicados pelo número da tentativa (como coletor.siscam.baixar)
TIMEOUT = 90
MAX_BYTES_DOWNLOAD = 250 * 1024 * 1024
BLOCO_DOWNLOAD = 1 << 20
CHECKPOINT_COMPONENTES = 200
CHECKPOINT_SEGUNDOS = 600.0
FUSO_BRASILIA = dt.timezone(dt.timedelta(hours=-3))
MAPA_CACHE = "textos_sha256.json"  # chave do manifesto → SHA-256, gravado por este módulo
MAPA_SISCAM = "siscam_arquivos_sha256.json"  # IdArquivo → SHA-256 (levantamento da Phase 0.1)
MAPA_ATAS = "atas_cache_sha256.json"  # atas → SHA-256 (levantamento da Phase 0.1)
MAPA_EMENTAS = "textos_ementas.json"  # chave → SHA-256 da ementa usada na limpeza
MARCA_COMMIT = "textos_commit.json"  # sha256_config e versao_mascara do último commit em dados-textos
NOME_TRAVA = ".radar-textos.lock"
MARCA_RAIZ = ".radar-raiz"
GITATTRIBUTES = "* -text\n"
ARQUIVOS_CONTROLE = (".gitattributes", MARCA_RAIZ, NOME_TRAVA)  # na raiz da pasta dos textos
# motivos de reprocessamento que dispensam nova extração quando o cache tem o resultado
MOTIVOS_RECONSTRUIVEIS = frozenset({"config", "versao", "texto_ausente"})
EXTRATORES_PYTHON = frozenset({"docx", "doc", "rtf", "html", "texto", "zip"})


# ---------------------------------------------------------------- caminhos padrão
def cache_padrao() -> Path:
    """`RADAR_CACHE` ou, sem ela, `D:\\radar-niteroi-cache` no Windows e
    `~/.cache/radar-niteroi` nos demais sistemas."""
    if os.environ.get("RADAR_CACHE"):
        return Path(os.environ["RADAR_CACHE"])
    if os.name == "nt":
        return Path(r"D:\radar-niteroi-cache")
    return Path.home() / ".cache" / "radar-niteroi"


def textos_padrao() -> Path:
    """Worktree da branch `dados-textos`: `RADAR_TEXTOS` ou o padrão local."""
    if os.environ.get("RADAR_TEXTOS"):
        return Path(os.environ["RADAR_TEXTOS"])
    if os.name == "nt":
        return Path(r"D:\git\radar-vereadores-niteroi-textos")
    return RAIZ.parent / "radar-vereadores-niteroi-textos"


def hoje_brasilia() -> str:
    """Data `AAAA-MM-DD` em Brasília (UTC−3)."""
    return dt.datetime.now(FUSO_BRASILIA).date().isoformat()


# ---------------------------------------------------------------- regras do contrato (puras)
def sha256(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


def blob_git(dados: bytes) -> str:
    """SHA-1 do blob do Git (`git hash-object`) dos bytes."""
    return hashlib.sha1(b"blob %d\0" % len(dados) + dados).hexdigest()


def r2_chave(sha: str) -> str:
    """Chave do original no R2: sha256/<aa>/<bb>/<sha256>."""
    return f"sha256/{sha[:2]}/{sha[2:4]}/{sha}"


def ordem_chave(chave: str) -> tuple:
    """Ordem das chaves de arquivo: siscam antes de sessao; ids numéricos crescentes."""
    origem, ident = chave.split(":", 1)
    return (0, int(ident), "") if origem == "siscam" else (1, 0, ident)


def caminho_texto(tipo: str, ano: int, documento: str, chave: str) -> str:
    """textos/<tipo>/<ano>/<documento sem prefixo>/<origem>-<id>.txt"""
    return f"textos/{tipo}/{ano}/{documento.split(':', 1)[1]}/{chave.replace(':', '-', 1)}.txt"


def caminho_trechos(tipo: str, ano: int) -> str:
    return f"trechos/{tipo}/{ano}.jsonl"


def linha_trecho(trecho: dict) -> str:
    return json.dumps(trecho, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def chave_ata(url: str) -> str | None:
    """`sessao:<guid>` do nome do arquivo da URL, sem extensão e em minúsculas; None
    se o nome não for um GUID."""
    guid = url.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
    chave = f"sessao:{guid}"
    return chave if RE_CHAVE.match(chave) else None


def citacoes(proposicoes: Iterable[dict], documentos: dict[str, list[dict]],
             sessoes: Iterable[dict]) -> dict[str, dict]:
    """Fila: para cada chave de arquivo, a URL e as citações
    (documento, tipo, principal, tipo do principal, ano do principal, ementa do principal)."""
    fila: dict[str, dict] = {}

    def citar(chave: str, url: str, documento: str, tipo: str, principal_: str, tipo_principal: str,
              ano: int, ementa: str) -> None:
        item = fila.setdefault(chave, {"url": url, "citacoes": []})
        item["citacoes"].append((documento, tipo, principal_, tipo_principal, ano, ementa))

    for pl in proposicoes:
        chave_pl = f"doc:{pl['id']}"
        ementa_pl = pl.get("ementa") or ""
        for a in pl.get("arquivos") or []:
            ident = int(a["id"])
            citar(f"siscam:{ident}", URL_DOWNLOAD.format(id=ident), chave_pl, "pl", chave_pl, "pl",
                  pl["ano"], ementa_pl)
        for sub in pl.get("substitutivos") or []:
            for a in sub.get("arquivos") or []:
                # o PL é o principal de qualquer arquivo dos seus substitutivos
                ident = int(a["id"])
                citar(f"siscam:{ident}", URL_DOWNLOAD.format(id=ident), f"doc:{sub['id']}",
                      "substitutivo", chave_pl, "pl", pl["ano"], ementa_pl)
    for tipo in TIPOS_COM_TEXTO:  # indicações e moções: fora
        for d in documentos.get(tipo) or []:
            chave_doc = f"doc:{d['id']}"
            for a in d.get("arquivos") or []:
                ident = int(a["id"])
                citar(f"siscam:{ident}", URL_DOWNLOAD.format(id=ident), chave_doc, tipo, chave_doc, tipo,
                      d["ano"], d.get("ementa") or "")
    for sessao in sessoes:
        chave_sessao = f"sessao:{sessao['id']}"
        for item in sessao.get("documentos_sessao") or []:
            url = item.get("url")
            if item.get("rotulo") not in ROTULOS_ATA or not url:
                continue
            chave = chave_ata(url)
            if chave is None:
                print(f"::warning::ata da sessão {sessao['id']} com nome de arquivo fora do padrão GUID",
                      file=sys.stderr)
                continue
            citar(chave, url, chave_sessao, "ata", chave_sessao, "ata", sessao["ano"], "")
    return fila


def principal(lista: list[tuple]) -> tuple[str, str, int, str]:
    """(documento, tipo, ano, ementa) do principal: maior prioridade de tipo, menor id."""
    melhor = min(lista, key=lambda c: (PRIORIDADE_TIPO[c[3]], int(c[2].split(":", 1)[1])))
    return melhor[2], melhor[3], melhor[4], melhor[5]


def entrada_vazia(documentos: Iterable[str], documento: str, tipo: str, url: str, status: str,
                  processado_em: str) -> dict:
    """Entrada do manifesto com todos os campos, sem extração (seção 4.2)."""
    return {
        "documentos": sorted(set(documentos)), "documento": documento, "tipo": tipo, "url_origem": url,
        "sha256_original": None, "bytes": None, "formato": None, "extrator": None, "versao_extrator": None,
        "versao_extratores": None, "versao_limpeza": None, "versao_mascara": None, "versao_trechos": None,
        "sha256_config": None, "paginas": 0, "paginas_ocr": 0, "confianca": None, "cabecalhos_omitidos": 0,
        "detalhe": "", "status": status, "duplicata_de": None, "limpeza": None, "mascarados": None,
        "sha256_bruto": None, "sha256_texto": None, "blob_texto": None, "chars": 0, "trechos": 0,
        "trechos_vetorizaveis": 0, "r2_chave": None, "processado_em": processado_em,
    }


class BarreiraPII(RuntimeError):
    """O texto final ainda tem ocorrência forte de `mascara.varrer`: não é gravado."""

    def __init__(self, chave: str, tipos: list[str]) -> None:
        super().__init__(f"{chave}: ocorrência(s) forte(s) depois da máscara ({', '.join(tipos)})")
        self.chave = chave
        self.tipos = tipos


def detalhe_seguro(detalhe: str, liberados: Iterable[str]) -> str:
    """`detalhe` mascarado e limitado a 300 caracteres; com qualquer ocorrência de
    `mascara.varrer` (forte ou fraca) que tenha sobrado, `DETALHE_OMITIDO`."""
    texto, _ = mascara.mascarar(detalhe or "", liberados)
    texto = texto[:300]
    if texto and (mascara.varrer(texto, liberados) or mascara.varrer_estrito(texto, liberados)):
        return DETALHE_OMITIDO
    return texto


def processar(entrada: dict, chave: str, resultado: Resultado, ementa: str, cliches, protecao,
              liberados: Iterable[str], versao_limpeza: str,
              sha_config: str) -> tuple[str | None, list[dict], str | None]:
    """Preenche a entrada com o pipeline (seção 1) a partir do `Resultado` da extração.

    `entrada` já tem `sha256_original`. Devolve o conteúdo do `.txt` (ou None), os
    trechos e o texto bruto (ou None). BarreiraPII se o texto final tiver ocorrência
    forte de `mascara.varrer`.
    """
    liberados = frozenset(liberados)
    entrada.update({
        "formato": resultado.formato, "extrator": resultado.extrator or None,
        "versao_extrator": resultado.versao_extrator or None, "versao_extratores": VERSAO_EXTRATORES,
        "versao_limpeza": versao_limpeza, "versao_mascara": mascara.VERSAO_MASCARA,
        "versao_trechos": trechos.VERSAO_TRECHOS, "sha256_config": sha_config,
        "paginas": resultado.paginas, "paginas_ocr": resultado.paginas_ocr,
        "confianca": None if resultado.confianca is None else round(float(resultado.confianca), 1),
        "cabecalhos_omitidos": resultado.cabecalhos_omitidos,
        "status": resultado.status,
        "r2_chave": r2_chave(entrada["sha256_original"]),
    })
    entrada["detalhe"] = detalhe_seguro(resultado.detalhe or "", liberados)
    if resultado.status not in STATUS_COM_TEXTO:
        return None, [], None
    bruto = trechos.normalizar(resultado.texto)
    # páginas que vieram do OCR: as de confianca_paginas (zip: None)
    ocr_paginas = None if resultado.formato == "zip" else set(resultado.confianca_paginas)
    limpo, contagens = limpeza.limpar(bruto, cliches, protecao, ementa=ementa, ocr_paginas=ocr_paginas)
    mascarado, mascarados = mascara.mascarar(limpo, liberados, ocr_paginas=ocr_paginas)
    texto = trechos.normalizar(mascarado)
    fortes = sorted({o["tipo"] for o in mascara.varrer(texto, liberados, ocr_paginas=ocr_paginas) if o["forte"]}
                    | {o["tipo"] for o in mascara.varrer_estrito(texto, liberados)})
    if fortes:  # barreira de PII: nada é gravado com ocorrência forte
        raise BarreiraPII(chave, fortes)
    if not texto:
        entrada["status"], entrada["detalhe"] = "vazio_legitimo", ESVAZIADO
    lista = trechos.dividir(texto, entrada["documento"], chave)
    conteudo = (texto + "\n").encode("utf-8")
    entrada.update({
        "limpeza": {
            "linhas_removidas": contagens["linhas_removidas"],
            "por_regra": {regra: contagens[regra]
                          for regra in ("cabecalho_rodape", "numeracao", "ruido_ocr", "cliche")},
        },
        "mascarados": {tipo: mascarados[tipo] for tipo in mascara.TIPOS},
        "sha256_bruto": sha256(bruto.encode("utf-8")),
        "sha256_texto": sha256(conteudo),
        "blob_texto": blob_git(conteudo),
        "chars": len(texto),
        "trechos": len(lista),
        "trechos_vetorizaveis": sum(t["vetorizavel"] for t in lista),
    })
    return conteudo.decode("utf-8"), lista, bruto


def processado_em(nova: dict, anterior: dict | None, hoje: str) -> str:
    """Seção 9: a data anterior, salvo se mudou algum campo de `CAMPOS_PROCESSADO_EM`."""
    if anterior is not None and anterior.get("processado_em") and all(
            nova.get(c) == anterior.get(c) for c in CAMPOS_PROCESSADO_EM):
        return anterior["processado_em"]
    return hoje


def tem_texto(entrada: dict) -> bool:
    """Se a entrada tem `.txt` (inclusive o esvaziado pela limpeza)."""
    return entrada.get("sha256_texto") is not None


def _ordem_trecho(t: dict) -> tuple:
    """Ordem dos trechos no `.jsonl`: (documento, arquivo, posicao)."""
    posicao = t.get("posicao")
    return (0, str(t.get("documento", "")), str(t.get("arquivo", "")), posicao if isinstance(posicao, int) else 0)


# ---------------------------------------------------------------- cache das extrações
def meta_resultado(resultado: Resultado, bruto: str | None) -> dict:
    """Campos do `Resultado` (sem o texto) guardados em `<cache>/texto_bruto/<sha>.json`."""
    return {
        "cabecalhos_omitidos": resultado.cabecalhos_omitidos,
        "confianca": resultado.confianca,
        "confianca_paginas": {str(n): v for n, v in sorted(resultado.confianca_paginas.items())},
        "detalhe": resultado.detalhe or "",
        "extrator": resultado.extrator or "",
        "formato": resultado.formato,
        "paginas": resultado.paginas,
        "paginas_escaneadas": list(resultado.paginas_escaneadas),
        "paginas_ocr": resultado.paginas_ocr,
        "sha256_bruto": None if bruto is None else sha256(bruto.encode("utf-8")),
        "status": resultado.status,
        "versao_extrator": resultado.versao_extrator or "",
        "versao_extratores": VERSAO_EXTRATORES,
    }


def resultado_de_meta(meta: dict, texto: str) -> Resultado:
    return Resultado(
        formato=meta["formato"], texto=texto, extrator=meta.get("extrator") or "",
        versao_extrator=meta.get("versao_extrator") or "", paginas=int(meta.get("paginas") or 0),
        paginas_ocr=int(meta.get("paginas_ocr") or 0), confianca=meta.get("confianca"),
        status=meta["status"], paginas_escaneadas=[int(n) for n in meta.get("paginas_escaneadas") or []],
        confianca_paginas={int(n): v for n, v in (meta.get("confianca_paginas") or {}).items()},
        detalhe=meta.get("detalhe") or "", cabecalhos_omitidos=int(meta.get("cabecalhos_omitidos") or 0),
    )


# ---------------------------------------------------------------- leitura de data/
def _arquivos_de_ano(pasta: Path) -> list[Path]:
    if not pasta.is_dir():
        return []
    return sorted(p for p in pasta.glob("*.json") if re.fullmatch(r"\d{4}", p.stem))


def _ler_lista(caminho: Path) -> list[dict]:
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    if not isinstance(dados, list):
        raise ValueError(f"{caminho}: esperada uma lista de registros")
    return dados


def carregar_registros(raiz: Path) -> tuple[list[dict], dict[str, list[dict]], list[dict]]:
    """PLs, documentos com texto (por tipo) e sessões de `raiz/data`; pastas ausentes = vazio."""
    dados = Path(raiz) / "data"
    proposicoes = [r for p in _arquivos_de_ano(dados / "proposicoes") for r in _ler_lista(p)]
    documentos = {tipo: [r for p in _arquivos_de_ano(dados / "documentos" / tipo) for r in _ler_lista(p)]
                  for tipo in TIPOS_COM_TEXTO}
    sessoes = [r for p in _arquivos_de_ano(dados / "sessoes") for r in _ler_lista(p)]
    return proposicoes, documentos, sessoes


def carregar_manifestos(raiz: Path,
                        repetidas: dict[str, list[tuple[dict, int]]] | None = None) -> dict[str, tuple[dict, int]]:
    """Entradas de todos os `data/textos/manifesto-<ano>.json`: chave → (entrada, ano).

    Uma chave em mais de um manifesto fica com a primeira ocorrência (menor ano); todas
    as ocorrências vão para `repetidas` (se dado) ou geram um aviso.
    """
    pasta = Path(raiz) / "data" / "textos"
    entradas: dict[str, tuple[dict, int]] = {}
    todas: dict[str, list[tuple[dict, int]]] = {}
    if not pasta.is_dir():
        return entradas
    for caminho in sorted(pasta.glob("manifesto-*.json")):
        m = RE_MANIFESTO.match(caminho.name)
        if not m:
            continue
        ano = int(m.group(1))
        mapa = json.loads(caminho.read_text(encoding="utf-8"))
        if not isinstance(mapa, dict):
            raise ValueError(f"{caminho}: esperado um objeto")
        for chave, entrada in mapa.items():
            todas.setdefault(chave, []).append((entrada, ano))
            entradas.setdefault(chave, (entrada, ano))
    for chave, ocorrencias in sorted(todas.items()):
        if len(ocorrencias) < 2:
            continue
        if repetidas is not None:
            repetidas[chave] = ocorrencias
        else:
            print(f"::warning::{chave} aparece em mais de um manifesto ({', '.join(str(a) for _, a in ocorrencias)})",
                  file=sys.stderr)
    return entradas


# ---------------------------------------------------------------- download e cache
class ErroDownload(RuntimeError):
    """Resposta inválida do servidor; `repetir` diz se vale tentar de novo."""

    def __init__(self, motivo: str, repetir: bool = True) -> None:
        super().__init__(motivo)
        self.repetir = repetir


def _ler_resposta(resposta, url: str, limite: int) -> bytes:
    """Corpo da resposta, conferido contra o `Content-Length`, o tipo e o limite de tamanho."""
    tipo = (resposta.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
    if tipo == "text/html" and "download.aspx" in urllib.parse.urlsplit(url).path.lower():
        raise ErroDownload("Download.aspx devolveu text/html (página de erro)")
    declarado = resposta.headers.get("Content-Length")
    esperado: int | None = None
    if declarado is not None:
        try:
            esperado = int(declarado.strip())
        except ValueError:
            raise ErroDownload("Content-Length inválido") from None
        if esperado > limite:
            raise ErroDownload(f"arquivo acima do limite de {limite} bytes", repetir=False)
    partes: list[bytes] = []
    total = 0
    while True:
        bloco = resposta.read(BLOCO_DOWNLOAD)
        if not bloco:
            break
        total += len(bloco)
        if total > limite:
            raise ErroDownload(f"arquivo acima do limite de {limite} bytes", repetir=False)
        partes.append(bloco)
    if esperado is not None and total != esperado:
        raise ErroDownload(f"corpo com {total} bytes, Content-Length {esperado}")
    return b"".join(partes)


def baixar_bytes(url: str, tentativas: int = TENTATIVAS, espera: float = ESPERA, timeout: float = TIMEOUT,
                 limite: int = MAX_BYTES_DOWNLOAD) -> bytes:
    """Bytes de `url`, com o User-Agent de `coletor.siscam`, tentativas e espera
    progressiva. Erros 4xx definitivos (exceto 408 e 429) e arquivos acima de `limite`
    não são repetidos; corpo menor que o `Content-Length`, `text/html` do
    `Download.aspx` e `http.client.HTTPException` (como `IncompleteRead`) são."""
    from .siscam import USER_AGENT

    erro: Exception | None = None
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return _ler_resposta(r, url, limite)
        except urllib.error.HTTPError as e:
            erro = e
            if 400 <= e.code < 500 and e.code not in (408, 429):
                break
        except ErroDownload as e:
            erro = e
            if not e.repetir:
                break
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, ConnectionError, OSError) as e:
            erro = e
        if i + 1 < tentativas:
            time.sleep(espera * (i + 1))
    raise RuntimeError(f"falha ao baixar {url}: {type(erro).__name__}: {erro}")


def _gravar_binario(caminho: Path, dados: bytes) -> None:
    """Gravação atômica de bytes (temporário na mesma pasta + os.replace)."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_name(f".{caminho.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        temporario.write_bytes(dados)
        try:
            os.replace(temporario, caminho)
        except PermissionError:
            # Windows: outra linha gravou o mesmo original (nome = SHA-256) ao mesmo tempo
            if not caminho.is_file():
                raise
            temporario.unlink()
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            temporario.unlink()
        raise


def _gravar_texto(caminho: Path, conteudo: str) -> bool:
    """Grava `conteudo` (UTF-8, LF) se os bytes mudaram; devolve se gravou."""
    novo = conteudo.encode("utf-8")
    try:
        if caminho.read_bytes() == novo:
            return False
    except FileNotFoundError:
        pass
    arquivos.gravar_atomico(caminho, conteudo)
    return True


def _ler_json_opcional(caminho: Path):
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except ValueError as e:
        print(f"::warning::{caminho}: JSON ilegível, ignorado ({type(e).__name__})", file=sys.stderr)
        return None


def _sha_de(valor) -> str | None:
    if isinstance(valor, str):
        v = valor.strip().lower()
        return v if RE_SHA.match(v) else None
    if isinstance(valor, dict):
        return _sha_de(valor.get("sha256") or valor.get("sha") or "")
    if isinstance(valor, (list, tuple)):
        for v in valor:
            sha = _sha_de(v) if isinstance(v, str) else None
            if sha:
                return sha
    return None


def _pares(dados) -> list[tuple[str, object]]:
    if isinstance(dados, dict):
        return [(str(k), v) for k, v in dados.items()]
    if isinstance(dados, list):
        pares = []
        for item in dados:
            if isinstance(item, dict):
                for campo in ("chave", "id", "url", "guid", "arquivo", "nome"):
                    if item.get(campo) is not None:
                        pares.append((str(item[campo]), item))
                        break
        return pares
    return []


def _chave_legada(chave: str, origem: str) -> str | None:
    """Chave do manifesto a partir da chave de um mapa do levantamento: ids numéricos
    (ou `Download.aspx?id=`) no mapa do SISCAM; GUID no mapa das atas."""
    chave = chave.strip()
    if RE_CHAVE.match(chave.lower() if chave.startswith("sessao:") else chave):
        return chave.lower() if chave.startswith("sessao:") else chave
    if origem == "siscam":
        m = re.fullmatch(r"\d+", chave) or re.search(r"[?&]id=(\d+)", chave)
        if m:
            ident = int(m.group(1) if m.groups() else m.group(0))
            return f"siscam:{ident}" if ident > 0 else None
        return None
    m = RE_GUID.search(chave)
    return f"sessao:{m.group(0).lower()}" if m else None


# ---------------------------------------------------------------- travas
class ErroTrava(RuntimeError):
    """Outra execução usa a pasta, a trava ficou abandonada ou a pasta é de outra raiz."""


def _pid_vivo(pid: int) -> bool:
    """Se existe um processo com esse pid (no Windows, sem enviar sinal algum)."""
    if pid <= 0 or pid > 0xFFFFFFFF:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k32.GetExitCodeProcess.restype = wintypes.BOOL
        k32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5  # ERROR_ACCESS_DENIED: existe, de outro usuário
        try:
            codigo = wintypes.DWORD()
            if not k32.GetExitCodeProcess(handle, ctypes.byref(codigo)):
                return True
            return codigo.value == 259  # STILL_ACTIVE
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _mesmo_caminho(a: str | Path, b: str | Path) -> bool:
    return os.path.normcase(os.path.abspath(str(a))) == os.path.normcase(os.path.abspath(str(b)))


class Trava:
    """`<pasta>/.radar-textos.lock`, criada com O_EXCL e com o pid e a raiz do
    repositório. Trava de processo vivo: ErroTrava. Trava de processo encerrado (ou
    ilegível): ErroTrava, salvo com `forcar` (então é substituída, com aviso)."""

    def __init__(self, pasta: Path, raiz: Path, forcar: bool = False) -> None:
        self.caminho = Path(pasta) / NOME_TRAVA
        self.raiz = Path(raiz).resolve()
        self.forcar = forcar
        self.conteudo = ""

    def _dono(self) -> dict | None:
        try:
            dados = json.loads(self.caminho.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return dados if isinstance(dados, dict) else None

    def __enter__(self) -> Trava:
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self.conteudo = json.dumps({"pid": os.getpid(), "raiz": str(self.raiz)}, ensure_ascii=False,
                                   sort_keys=True) + "\n"
        for tentativa in range(2):
            try:
                fd = os.open(self.caminho, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0))
            except FileExistsError:
                dono = self._dono()
                pid = dono.get("pid") if dono else None
                if isinstance(pid, int) and _pid_vivo(pid):
                    raise ErroTrava(f"{self.caminho}: em uso pelo processo {pid}") from None
                if not self.forcar or tentativa:
                    raise ErroTrava(f"{self.caminho}: trava abandonada (processo {pid} encerrado); "
                                    "confira e use --forcar-trava") from None
                print(f"::warning::{self.caminho}: trava abandonada do processo {pid} substituída (--forcar-trava)",
                      file=sys.stderr)
                with contextlib.suppress(FileNotFoundError):
                    self.caminho.unlink()
                continue
            with os.fdopen(fd, "wb") as f:
                f.write(self.conteudo.encode("utf-8"))
            return self
        raise ErroTrava(f"{self.caminho}: não foi possível criar a trava")  # pragma: no cover

    def __exit__(self, tipo, valor, rastro) -> bool:
        try:
            if self.caminho.read_text(encoding="utf-8") == self.conteudo:
                self.caminho.unlink()
        except OSError:
            pass
        return False


def preparar_textos(pasta: Path, raiz: Path, forcar: bool = False) -> None:
    """Liga a pasta dos textos à raiz (`.radar-raiz`) e garante o `.gitattributes`."""
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    raiz_abs = str(Path(raiz).resolve())
    marca = pasta / MARCA_RAIZ
    try:
        atual = marca.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        atual = None
    if atual is not None and not _mesmo_caminho(atual, raiz_abs):
        if not forcar:
            raise ErroTrava(f"{pasta} está ligada a outro repositório ({atual}); confira e use --forcar-trava")
        print(f"::warning::{pasta}: ligada de novo a {raiz_abs} (antes: {atual}) por --forcar-trava",
              file=sys.stderr)
    if atual is None or not _mesmo_caminho(atual, raiz_abs):
        arquivos.gravar_atomico(marca, raiz_abs + "\n")
    atributos = pasta / ".gitattributes"
    try:
        conteudo = atributos.read_text(encoding="utf-8")
    except FileNotFoundError:
        arquivos.gravar_atomico(atributos, GITATTRIBUTES)
        return
    if "* -text" not in conteudo.splitlines():
        print(f"::warning::{atributos} sem a linha '* -text'; mantido como está", file=sys.stderr)


# ---------------------------------------------------------------- sinais
SINAIS_INTERROMPER = ("SIGTERM", "SIGBREAK")


def _interromper(sinal: int, _quadro: object) -> None:
    """Trata SIGTERM/SIGBREAK como Ctrl+C, para que a gravação parcial aconteça."""
    raise KeyboardInterrupt(f"sinal {sinal}")


class _SinaisAdiados:
    """Adia SIGINT/SIGTERM/SIGBREAK durante a gravação (só na thread principal)."""

    def __enter__(self) -> _SinaisAdiados:
        self.recebido: int | None = None
        self.antigos: dict = {}
        if threading.current_thread() is threading.main_thread():
            for nome in ("SIGINT", "SIGTERM", "SIGBREAK"):
                sinal = getattr(signal, nome, None)
                if sinal is not None:
                    with contextlib.suppress(ValueError, OSError):
                        self.antigos[sinal] = signal.signal(sinal, self._guardar)
        return self

    def _guardar(self, sinal: int, _quadro: object) -> None:
        self.recebido = sinal

    def __exit__(self, tipo, valor, rastro) -> bool:
        for sinal, tratador in self.antigos.items():
            with contextlib.suppress(ValueError, OSError, TypeError):
                signal.signal(sinal, tratador)
        if self.recebido is not None and tipo is None:
            raise KeyboardInterrupt(f"sinal {self.recebido}")
        return False


def _esperar(futuro: cf.Future):
    """`futuro.result()` interrompível por Ctrl+C também no Windows."""
    while not futuro.done():
        cf.wait([futuro], timeout=0.5)
    return futuro.result()


# ---------------------------------------------------------------- execução
@dataclass
class Opcoes:
    """Opções de uma execução; `extrair`, `baixar`, `liberados`, `pessoas`, `hoje` e
    `versoes_ferramentas` substituem as dependências reais (testes e fixtures)."""

    raiz: Path = RAIZ
    textos: Path = field(default_factory=textos_padrao)
    cache: Path = field(default_factory=cache_padrao)
    anos: frozenset[int] | None = None
    tipos: frozenset[str] | None = None
    max_arquivos: int = MAX_ARQUIVOS
    prazo: float | None = None  # instante de time.monotonic() a partir do qual nada novo começa
    ocr: bool = False
    sem_rede: bool = False
    reprocessar_versao: bool = False
    workers: int = 4
    hoje: str | None = None
    extrair: Callable | None = None
    baixar: Callable[[str], bytes] | None = None
    liberados: Iterable[str] | None = None
    pessoas: list | None = None
    forcar_trava: bool = False
    checkpoint_componentes: int = CHECKPOINT_COMPONENTES
    checkpoint_segundos: float = CHECKPOINT_SEGUNDOS
    versoes_ferramentas: dict | None = None  # {"pdftotext": "25.07.0", "tesseract": "5.5.3"}


@dataclass
class Aquisicao:
    """Resultado da obtenção dos bytes de uma chave: `ok`, `removido` (pelo SHA-256) ou `falha`."""

    tipo: str
    sha: str | None = None
    bytes: int | None = None
    origem: str = ""
    motivo: str = ""


@dataclass
class Basico:
    """Situação de uma chave antes das duplicatas: `ausente`, `manter`, `removido`, `pendente` ou `sha`."""

    tipo: str
    sha: str | None = None
    bytes: int | None = None
    adquirido: bool = False


@dataclass
class Plano:
    """Ação final de uma chave: `ausente`, `manter`, `atualizar`, `removido`, `pendente`,
    `duplicata` ou `processar`, com os campos do documento principal. `bruto`: o
    processamento usa o resultado da extração guardado no cache, sem os bytes."""

    acao: str
    sha: str | None = None
    bytes: int | None = None
    documentos: list[str] = field(default_factory=list)
    documento: str = ""
    tipo: str = ""
    ano: int = 0
    ementa: str = ""
    url: str = ""
    duplicata_de: str | None = None
    bruto: bool = False


class _Adiado(Exception):
    """A extração do componente foi adiada pelo prazo."""


class _Falha(Exception):
    """A extração do componente falhou sem gravar nada."""


class Pipeline:
    """Uma execução de `coletor.textos` (veja o docstring do módulo)."""

    def __init__(self, op: Opcoes) -> None:
        self.op = op
        self.raiz = Path(op.raiz)
        self.pasta_textos = Path(op.textos)
        self.cache = Path(op.cache)
        self.hoje = op.hoje or hoje_brasilia()
        self.extrair = op.extrair or extratores.extrair
        self.baixar = op.baixar or baixar_bytes
        self.liberados = frozenset(op.liberados if op.liberados is not None else mascara.liberados(self.raiz))
        pessoas = op.pessoas if op.pessoas is not None else limpeza.pessoas_de_config(self.raiz)
        self.protecao = limpeza.ProtecaoLimpeza(pessoas)
        self.sha_config = limpeza.hash_config_de(self.liberados, pessoas)
        self.cliches = limpeza.carregar_cliches(self.raiz / "data" / "textos" / "cliches.json")
        self.versao_limpeza = limpeza.versao_efetiva(self.raiz)
        self.versoes = {
            "versao_extratores": VERSAO_EXTRATORES, "versao_limpeza": self.versao_limpeza,
            "versao_mascara": mascara.VERSAO_MASCARA, "versao_trechos": trechos.VERSAO_TRECHOS,
        }
        remocoes.limpar_cache()
        self.remocoes = remocoes.indice(self.raiz)
        self.estat: dict = {
            "fila": 0, "trabalho": 0, "reconstruidos": 0, "adiados_limite": 0, "do_cache": 0, "baixados": 0,
            "falhas_download": 0, "removidos_sha": 0, "processados": 0, "resultados_do_cache": 0,
            "adiados_prazo": 0, "falhas": [], "bloqueados": [], "sem_bytes_mantidos": 0, "principal_adiado": 0,
            "desconhecidos": 0,
        }
        self.aquisicoes: dict[str, Aquisicao] = {}
        self.prev: dict[str, tuple[dict, int]] = {}
        self.final: dict[str, tuple[dict, int]] = {}
        self.gravado: dict[str, tuple[dict, int]] = {}  # o que está nos manifestos em disco
        self.anteriores_txt: dict[str, set[str]] = {}  # chave → .txt gravados por entradas anteriores
        self.anteriores_grupos: dict[str, set[tuple[str, int]]] = {}  # chave → (tipo, ano) dos trechos gravados
        self.txt_novos: dict[str, str] = {}
        self.trechos_novos: dict[str, list[dict]] = {}
        self.alterados: set[str] = set()
        self.anos_sujos: set[int] = set()
        self.shas_remover: set[str] = set()
        self.mapa: dict[str, str] = {}
        self.mapa_novos: dict[str, str] = {}
        self.mapa_siscam_legado = None
        self.ementas: dict[str, str] = {}
        self.ementas_disco: dict[str, str] = {}
        self.ementas_novas: dict[str, str] = {}
        self.reconstruir: set[str] = set()
        self.reprocessar: set[str] = set()
        self.fila: dict[str, dict] = {}
        self.plano: dict[str, Plano] = {}
        self.grupos: dict[str, list[str]] = {}
        self.config_mudou = False
        self._validos: dict[str, bool] = {}
        self._versoes_ferramentas: dict | None = None
        self._trava_ferramentas = threading.Lock()

    # ---- utilidades
    def _original(self, sha: str) -> Path:
        return self.cache / "arquivos" / sha

    def _tem_bytes(self, sha: str | None) -> bool:
        return bool(sha) and self._original(sha).is_file()

    def _esgotado(self) -> bool:
        return self.op.prazo is not None and time.monotonic() >= self.op.prazo

    def _removido_sha(self, sha: str | None) -> bool:
        return bool(sha) and self.remocoes.contem(sha256=sha)

    def _selecionado(self, tipo: str, ano: int) -> bool:
        return ((self.op.tipos is None or tipo in self.op.tipos)
                and (self.op.anos is None or ano in self.op.anos))

    @contextlib.contextmanager
    def _travas(self, textos: bool):
        """Travas do cache e (se `textos`) da pasta dos textos, com `.radar-raiz` e `.gitattributes`."""
        with contextlib.ExitStack() as pilha:
            pilha.enter_context(Trava(self.cache, self.raiz, self.op.forcar_trava))
            if textos:
                pilha.enter_context(Trava(self.pasta_textos, self.raiz, self.op.forcar_trava))
                preparar_textos(self.pasta_textos, self.raiz, self.op.forcar_trava)
            yield

    # ---- cache das extrações
    def _ferramentas(self) -> dict:
        with self._trava_ferramentas:
            if self._versoes_ferramentas is None:
                if self.op.versoes_ferramentas is not None:
                    self._versoes_ferramentas = dict(self.op.versoes_ferramentas)
                else:
                    self._versoes_ferramentas = extratores.ferramentas_disponiveis()
            return self._versoes_ferramentas

    def _versao_local(self, extrator: str) -> str | None:
        """`versao_extrator` que a extração local produziria com esse extrator (None se desconhecido)."""
        if not extrator:
            return ""
        if extrator in EXTRATORES_PYTHON:
            return VERSAO_EXTRATORES
        if extrator not in ("pdftotext", "pdftotext+tesseract", "tesseract"):
            return None
        v = self._ferramentas()
        pdf, tess = v.get("pdftotext") or "", v.get("tesseract") or ""
        return {"pdftotext": pdf, "pdftotext+tesseract": f"{pdf}+{tess}", "tesseract": tess}[extrator]

    def _resultado_em_cache(self, sha: str | None) -> Resultado | None:
        """Resultado da extração de `sha` no cache, se ainda vale para o código e as
        ferramentas locais (e para o pedido de OCR); None nos demais casos."""
        if not sha:
            return None
        pasta = self.cache / "texto_bruto"
        try:
            meta = json.loads((pasta / f"{sha}.json").read_text(encoding="utf-8"))
            if not isinstance(meta, dict) or meta.get("versao_extratores") != VERSAO_EXTRATORES:
                return None
            status = meta["status"]
            if status == "pendente_ferramenta":
                return None
            if self.op.ocr and status in ("escaneado_sem_ocr", "ok_parcial"):
                return None
            if (meta.get("versao_extrator") or "") != self._versao_local(meta.get("extrator") or ""):
                return None
            texto = ""
            if status in STATUS_COM_TEXTO:
                conteudo = (pasta / f"{sha}.txt").read_bytes().decode("utf-8")
                if not conteudo.endswith("\n"):
                    return None
                texto = conteudo[:-1]
                if sha256(texto.encode("utf-8")) != meta.get("sha256_bruto"):
                    return None
            return resultado_de_meta(meta, texto)
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _em_cache(self, sha: str | None) -> bool:
        if not sha:
            return False
        if sha not in self._validos:
            self._validos[sha] = self._resultado_em_cache(sha) is not None
        return self._validos[sha]

    def _gravar_resultado_cache(self, sha: str, resultado: Resultado) -> None:
        if resultado.status == "pendente_ferramenta":
            return  # não substitui uma extração anterior por uma pendência
        pasta = self.cache / "texto_bruto"
        bruto = trechos.normalizar(resultado.texto) if resultado.status in STATUS_COM_TEXTO else None
        if bruto is not None:
            _gravar_texto(pasta / f"{sha}.txt", bruto + "\n")
        _gravar_texto(pasta / f"{sha}.json", arquivos.texto_json(meta_resultado(resultado, bruto)))
        self._validos.pop(sha, None)

    # ---- mapa de cache
    def _carregar_mapa(self) -> None:
        self.mapa_siscam_legado = _ler_json_opcional(self.cache / MAPA_SISCAM)
        for _nome, dados, origem in ((MAPA_SISCAM, self.mapa_siscam_legado, "siscam"),
                                     (MAPA_ATAS, _ler_json_opcional(self.cache / MAPA_ATAS), "sessao")):
            for k, v in _pares(dados):
                chave, sha = _chave_legada(k, origem), _sha_de(v)
                if chave and sha:
                    self.mapa[chave] = sha
        for k, v in _pares(_ler_json_opcional(self.cache / MAPA_CACHE)):
            sha = _sha_de(v)
            if RE_CHAVE.match(k) and sha:
                self.mapa[k] = sha

    def _salvar_mapa(self) -> None:
        """Gravação incremental e atômica do mapa chave → SHA-256 (a cada ponto de controle)."""
        if not self.mapa_novos:
            return
        caminho = self.cache / MAPA_CACHE
        proprio = {k: v for k, v in _pares(_ler_json_opcional(caminho)) if RE_CHAVE.match(k) and _sha_de(v)}
        proprio.update(self.mapa_novos)
        arquivos.salvar_mapa(caminho, proprio)
        legado = self.mapa_siscam_legado
        simples = isinstance(legado, dict) and all(
            re.fullmatch(r"\d+", str(k)) and isinstance(v, str) for k, v in legado.items())
        novos = {k.split(":", 1)[1]: v for k, v in self.mapa_novos.items() if k.startswith("siscam:")}
        if simples and novos:  # mantém o mapa do levantamento em dia, no mesmo formato
            atual = dict(legado)
            if any(atual.get(k) != v for k, v in novos.items()):
                atual.update(novos)
                arquivos.salvar_mapa(self.cache / MAPA_SISCAM, atual)
                self.mapa_siscam_legado = atual
        self.mapa_novos.clear()

    # ---- ementas usadas na limpeza
    def _carregar_ementas(self) -> None:
        dados = _ler_json_opcional(self.cache / MAPA_EMENTAS)
        self.ementas = {str(k): v for k, v in dados.items() if isinstance(v, str)} if isinstance(dados, dict) else {}
        self.ementas_disco = dict(self.ementas)

    def _ementa_mudou(self, chave: str, ementa: str) -> bool:
        """Se a ementa do principal difere da usada na última limpeza. Sem registro
        (entradas de antes deste mapa), registra a atual sem reprocessar."""
        atual = sha256(ementa.encode("utf-8"))
        registrada = self.ementas_novas.get(chave) or self.ementas.get(chave)
        if registrada is None:
            self.ementas_novas[chave] = atual
            return False
        return registrada != atual

    def _salvar_ementas(self, final: bool) -> None:
        if not self.ementas_novas and not final:
            return
        novo = dict(self.ementas)
        novo.update(self.ementas_novas)
        if final:  # só as chaves processadas que continuam no manifesto
            vivas = {k for k, (e, _) in self.final.items() if e.get("status") not in SEM_PROCESSAMENTO}
            novo = {k: v for k, v in novo.items() if k in vivas}
        if novo != self.ementas_disco:
            arquivos.salvar_mapa(self.cache / MAPA_EMENTAS, novo)
            self.ementas_disco = dict(novo)
        self.ementas = novo
        self.ementas_novas.clear()

    # ---- estado anterior
    def _anotar_anterior(self, chave: str, entrada: dict, ano: int) -> None:
        try:
            if tem_texto(entrada):
                self.anteriores_txt.setdefault(chave, set()).add(
                    caminho_texto(entrada["tipo"], ano, entrada["documento"], chave))
                self.anteriores_grupos.setdefault(chave, set()).add((entrada["tipo"], ano))
        except (KeyError, IndexError, TypeError, AttributeError):
            pass

    def _carregar_estado(self) -> None:
        repetidas: dict[str, list[tuple[dict, int]]] = {}
        self.prev = carregar_manifestos(self.raiz, repetidas)
        self._carregar_mapa()
        self._carregar_ementas()
        self.fila = citacoes(*carregar_registros(self.raiz))
        extras: list[tuple[str, list[tuple[dict, int]]]] = []
        for chave, ocorrencias in sorted(repetidas.items()):
            ano_atual = principal(self.fila[chave]["citacoes"])[2] if chave in self.fila else None
            escolhida = next((o for o in ocorrencias if o[1] == ano_atual), ocorrencias[0])
            self.prev[chave] = escolhida
            extras.append((chave, [o for o in ocorrencias if o is not escolhida]))
            print(f"::warning::{chave} aparece nos manifestos de {', '.join(str(a) for _, a in ocorrencias)}; "
                  f"mantida a entrada de {escolhida[1]}", file=sys.stderr)
        self.final = dict(self.prev)
        self.gravado = dict(self.prev)
        for chave, (e, ano) in self.prev.items():
            self._anotar_anterior(chave, e, ano)
            if e.get("status") == "removido" and e.get("sha256_original"):
                self.shas_remover.add(e["sha256_original"])
        for chave, outras in extras:
            for e, ano in outras:
                self._anotar_anterior(chave, e, ano)
                self.anos_sujos.add(ano)
            self.anos_sujos.add(self.prev[chave][1])
            self.alterados.add(chave)
        self.estat["fila"] = len(self.fila)

    # ---- fila e trabalho
    def _motivo(self, chave: str) -> str | None:
        """Por que a chave entra no trabalho por si (sem contar duplicatas e mudança de principal)."""
        if chave in self.remocoes.chaves:
            return None
        anterior = self.prev.get(chave)
        if anterior is None:
            return "novo"
        p, ano_p = anterior
        status, sha = p.get("status"), p.get("sha256_original")
        if status == "removido":
            return None if self._removido_sha(sha) else "remocao_suspensa"
        if status in ("pendente_download", "pendente_ferramenta"):
            return "pendente"
        if status in ("escaneado_sem_ocr", "ok_parcial") and self.op.ocr:
            return "ocr"
        if status == "duplicata" or self._removido_sha(sha):
            return None
        motivo = None
        if tem_texto(p):
            try:
                ausente = not (self.pasta_textos / caminho_texto(p["tipo"], ano_p, p["documento"], chave)).is_file()
            except (KeyError, IndexError, TypeError, AttributeError):
                ausente = True
            if ausente:
                motivo = "texto_ausente"
        if p.get("sha256_config") is not None and p["sha256_config"] != self.sha_config:
            self.config_mudou = True
            motivo = motivo or "config"
        if motivo is None and self.op.reprocessar_versao and any(p.get(c) != v for c, v in self.versoes.items()):
            motivo = "versao"
        return motivo

    def _precisa(self, chave: str) -> bool:
        return self._motivo(chave) is not None

    def _obter(self, chave: str, url: str) -> Aquisicao:
        """Bytes da chave: do cache (pelo mapa) ou da rede; grava o original no cache,
        salvo se removido pelo SHA-256."""
        sha = self.mapa.get(chave)
        if sha and self._tem_bytes(sha):
            tamanho = self._original(sha).stat().st_size
            return Aquisicao("removido" if self._removido_sha(sha) else "ok", sha, tamanho, "cache")
        if self.op.sem_rede:
            return Aquisicao("falha", motivo="sem rede e sem o original no cache")
        try:
            dados = self.baixar(url)
        except Exception as e:  # noqa: BLE001 - qualquer falha de rede vira pendente_download
            return Aquisicao("falha", motivo=f"{type(e).__name__}: {e}"[:300])
        sha = sha256(dados)
        if self._removido_sha(sha):  # baixado só para o hash: descartado, sem cache
            return Aquisicao("removido", sha, len(dados), "rede")
        if not self._tem_bytes(sha):
            _gravar_binario(self._original(sha), dados)
        return Aquisicao("ok", sha, len(dados), "rede")

    def _adquirir(self, itens: list[tuple[str, str]]) -> None:
        if not itens:
            return

        def tarefa(chave: str, url: str):
            if self._esgotado():
                return chave, None
            return chave, self._obter(chave, url)

        executor = cf.ThreadPoolExecutor(max_workers=max(1, self.op.workers))
        try:
            futuros = [executor.submit(tarefa, c, u) for c, u in itens]
            for futuro in futuros:
                chave, q = _esperar(futuro)
                if q is None:
                    self.estat["adiados_prazo"] += 1
                    continue
                self.aquisicoes[chave] = q
                if q.tipo == "falha":
                    self.estat["falhas_download"] += 1
                    print(f"::warning::{chave}: sem os bytes ({q.motivo})", file=sys.stderr)
                elif q.tipo == "removido":
                    self.estat["removidos_sha"] += 1
                    if q.origem == "cache":
                        self.shas_remover.add(q.sha)
                else:
                    self.estat["do_cache" if q.origem == "cache" else "baixados"] += 1
                    if self.mapa.get(chave) != q.sha:
                        self.mapa[chave] = q.sha
                    if q.origem == "rede":
                        self.mapa_novos[chave] = q.sha
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    # ---- planejamento
    def _basico(self, chave: str, sem_bytes: set[str]) -> Basico:
        alvo = self.fila.get(chave)
        p = self.prev.get(chave, (None, None))[0]
        if alvo is None:
            if p and self.remocoes.contem(chave, p.get("sha256_original")):
                return Basico("manter")  # conserva o tombstone mesmo sem citação na coleta atual
            return Basico("ausente")
        if chave in self.remocoes.chaves:  # pela chave: não baixa; guarda o hash anterior
            return Basico("removido", p.get("sha256_original") if p else None, p.get("bytes") if p else None)
        if chave in sem_bytes:
            return Basico("pendente")
        q = self.aquisicoes.get(chave)
        if q is not None and q.tipo != "falha":
            return Basico("removido" if q.tipo == "removido" else "sha", q.sha, q.bytes, q.tipo == "ok")
        if p is None:
            return Basico("pendente") if q is not None else Basico("ausente")
        sha = p.get("sha256_original")
        if self._removido_sha(sha):
            return Basico("removido", sha, p.get("bytes"))
        if p.get("status") == "removido":
            return Basico("manter")  # remoção suspensa, mas sem os bytes nesta execução
        if not sha:
            return Basico("pendente")
        return Basico("sha", sha, p.get("bytes"))

    def _plano_proprio(self, chave: str, acao: str, b: Basico | None = None) -> Plano:
        item = self.fila[chave]
        documento, tipo, ano, ementa = principal(item["citacoes"])
        return Plano(acao, b.sha if b else None, b.bytes if b else None,
                     sorted({c[0] for c in item["citacoes"]}), documento, tipo, ano, ementa, item["url"])

    def _planejar(self) -> None:
        universo = set(self.fila) | set(self.prev)
        tentados = set(self.aquisicoes) | self.reconstruir
        sem_bytes: set[str] = set()
        while True:
            basicos = {k: self._basico(k, sem_bytes) for k in universo}
            plano: dict[str, Plano] = {}
            grupos: dict[str, list[str]] = {}
            for k in sorted(universo, key=ordem_chave):
                b = basicos[k]
                if b.tipo == "sha":
                    grupos.setdefault(b.sha, []).append(k)
                elif b.tipo in ("ausente", "manter"):
                    plano[k] = Plano(b.tipo)
                else:
                    plano[k] = self._plano_proprio(k, b.tipo, b)
            faltando: list[str] = []
            refazer = False
            mantidos: list[str] = []
            adiados: list[str] = []
            for sha, membros in grupos.items():
                canonica = membros[0]
                b = basicos[canonica]
                todas = [c for m in membros for c in self.fila[m]["citacoes"]]
                documento, tipo, ano, ementa = principal(todas)
                p, ano_p = self.prev.get(canonica, (None, None))
                processado_ok = (p is not None and p.get("status") not in SEM_PROCESSAMENTO
                                 and p.get("sha256_original") == sha)
                selecionado = self._selecionado(tipo, ano)
                mudou = bool(processado_ok and tem_texto(p) and (
                    (p.get("documento"), p.get("tipo"), ano_p) != (documento, tipo, ano)
                    or self._ementa_mudou(canonica, ementa)))
                bruto = False
                if b.adquirido:
                    acao = "processar"
                elif canonica in self.reconstruir or canonica in self.reprocessar:
                    acao = "processar"
                elif processado_ok and not mudou:
                    acao = "atualizar"
                elif processado_ok:  # mudou o principal ou a ementa
                    acao = "processar"
                    if not selecionado and not self._em_cache(sha) and not self._tem_bytes(sha):
                        acao = "manter"  # fora de --anos/--tipos e sem bytes nem bruto: fica para depois
                        adiados.append(canonica)
                else:
                    acao = "processar"
                if acao == "processar" and not b.adquirido and self._em_cache(sha):
                    bruto = True  # refeito do texto bruto do cache, sem reextrair
                if acao == "processar" and not bruto and not self._tem_bytes(sha):
                    if canonica not in tentados and not self._esgotado():
                        faltando.append(canonica)
                        continue
                    if processado_ok:
                        acao = "manter"
                        mantidos.append(canonica)
                    else:
                        sem_bytes.add(canonica)
                        refazer = True
                        continue
                if acao == "manter":
                    plano[canonica] = Plano("manter")
                else:
                    plano[canonica] = Plano(acao, sha, b.bytes, sorted({c[0] for c in todas}), documento, tipo,
                                            ano, ementa, self.fila[canonica]["url"], bruto=bruto)
                for outra in membros[1:]:
                    d = self._plano_proprio(outra, "duplicata", basicos[outra])
                    d.duplicata_de = canonica
                    plano[outra] = d
            if faltando:
                tentados.update(faltando)
                self._adquirir([(c, self.fila[c]["url"]) for c in faltando])
                continue
            if refazer:
                continue
            self.plano, self.grupos = plano, grupos
            self.estat["sem_bytes_mantidos"] = len(mantidos)
            self.estat["principal_adiado"] = len(adiados)
            if adiados:
                print(f"::warning::{len(adiados)} entrada(s) com novo documento principal ou ementa fora de "
                      f"--anos/--tipos e sem os bytes nem o texto bruto no cache; ficam para a próxima execução "
                      f"({', '.join(sorted(adiados, key=ordem_chave)[:5])})", file=sys.stderr)
            return

    def _componentes(self) -> list[list[str]]:
        """Chaves ligadas por duplicatas (antigas ou novas), em ordem da menor chave."""
        pai = {k: k for k in self.plano}

        def raiz(k: str) -> str:
            while pai[k] != k:
                pai[k] = pai[pai[k]]
                k = pai[k]
            return k

        def unir(a: str, b: str) -> None:
            ra, rb = raiz(a), raiz(b)
            if ra != rb:
                pai[max(ra, rb, key=ordem_chave)] = min(ra, rb, key=ordem_chave)

        for k in self.plano:
            p = self.prev.get(k, (None, None))[0]
            if p and p.get("duplicata_de") in pai:
                unir(k, p["duplicata_de"])
        for membros in self.grupos.values():
            for m in membros[1:]:
                unir(membros[0], m)
        componentes: dict[str, list[str]] = {}
        for k in self.plano:
            componentes.setdefault(raiz(k), []).append(k)
        return [sorted(c, key=ordem_chave) for _, c in sorted(componentes.items(), key=lambda i: ordem_chave(i[0]))]

    # ---- execução dos componentes
    def _extrair_sha(self, sha: str, so_cache: bool = False):
        """(Resultado, veio do cache) da extração de `sha`; None se o prazo acabou;
        `_Falha` (só com o tipo da exceção) se falhou."""
        if self._esgotado():
            return None
        try:
            resultado = self._resultado_em_cache(sha)
            if resultado is not None:
                return resultado, True
            if so_cache:
                return _Falha("resultado da extração ausente do cache")
            dados = self._original(sha).read_bytes()
            if sha256(dados) != sha:
                return _Falha("o original do cache não confere com o SHA-256")
            resultado = self.extrair(dados, ocr=self.op.ocr, cache_ocr=self.cache / "ocr")
            self._gravar_resultado_cache(sha, resultado)
            return resultado, False
        except Exception as e:  # noqa: BLE001 - a falha fica registrada (só o tipo) e nada é gravado
            return _Falha(type(e).__name__)

    def _montar(self, componente: list[str], futuros: dict[str, cf.Future]):
        entradas: dict[str, tuple[dict, int] | None] = {}
        txts: dict[str, str] = {}
        novos_trechos: dict[str, list[dict]] = {}
        ementas: dict[str, str] = {}
        do_cache = 0
        for k in componente:
            pl = self.plano[k]
            anterior = self.prev.get(k)
            p = anterior[0] if anterior else None
            if pl.acao == "manter":
                continue
            if pl.acao == "ausente":
                if anterior is not None:
                    entradas[k] = None
                continue
            if pl.acao == "atualizar":
                e = dict(p)
                e.update({"documentos": pl.documentos, "documento": pl.documento, "tipo": pl.tipo,
                          "url_origem": pl.url})
                entradas[k] = (e, pl.ano)
                continue
            status = {"removido": "removido", "pendente": "pendente_download", "duplicata": "duplicata",
                      "processar": "ok"}[pl.acao]
            e = entrada_vazia(pl.documentos, pl.documento, pl.tipo, pl.url, status, self.hoje)
            if pl.acao != "pendente":
                e["sha256_original"], e["bytes"] = pl.sha, pl.bytes
            e["duplicata_de"] = pl.duplicata_de
            if pl.acao == "processar":
                futuro = futuros.pop(pl.sha, None)  # cada Resultado é usado uma vez e liberado
                if futuro is None:
                    raise _Falha(f"{k}: extração não agendada")
                obtido = _esperar(futuro)
                if obtido is None:
                    raise _Adiado(k)
                if isinstance(obtido, _Falha):
                    raise _Falha(f"{k}: {obtido}")
                resultado, veio_do_cache = obtido
                do_cache += veio_do_cache
                conteudo, lista, _bruto = processar(e, k, resultado, pl.ementa, self.cliches, self.protecao,
                                                    self.liberados, self.versao_limpeza, self.sha_config)
                del resultado, obtido
                ementas[k] = sha256(pl.ementa.encode("utf-8"))
                if conteudo is not None:
                    txts[k] = conteudo
                    novos_trechos[k] = lista
            e["processado_em"] = processado_em(e, p, self.hoje)
            entradas[k] = (e, pl.ano)
        return entradas, txts, novos_trechos, ementas, do_cache

    def _aplicar(self, componente: list[str], montado) -> None:
        entradas, txts, novos_trechos, ementas, do_cache = montado
        for k, valor in entradas.items():
            anterior = self.final.get(k)
            if valor is None:
                self.final.pop(k, None)
            else:
                self.final[k] = valor
                e = valor[0]
                if e.get("status") == "removido" and e.get("sha256_original"):
                    self.shas_remover.add(e["sha256_original"])
            if anterior != valor:
                self.alterados.add(k)
        self.txt_novos.update(txts)
        self.trechos_novos.update(novos_trechos)
        self.alterados.update(txts)
        self.ementas_novas.update(ementas)
        self.estat["resultados_do_cache"] += do_cache
        self.estat["processados"] += sum(1 for k in componente if self.plano[k].acao == "processar")

    def _executar(self) -> None:
        componentes = self._componentes()
        pedidos: dict[str, bool] = {}
        for componente in componentes:
            for k in componente:
                pl = self.plano[k]
                if pl.acao == "processar" and pl.sha not in pedidos:
                    pedidos[pl.sha] = pl.bruto
        executor = cf.ThreadPoolExecutor(max_workers=max(1, self.op.workers))
        ultimo = time.monotonic()
        desde = 0
        try:
            futuros = {sha: executor.submit(self._extrair_sha, sha, bruto) for sha, bruto in pedidos.items()}
            for componente in componentes:
                desde += 1
                try:
                    montado = self._montar(componente, futuros)
                except _Adiado:
                    self.estat["adiados_prazo"] += 1
                    montado = None
                except _Falha as e:
                    self.estat["falhas"].append(str(e))
                    print(f"::warning::extração falhou, nada gravado: {e}", file=sys.stderr)
                    montado = None
                except BarreiraPII as e:
                    self.estat["bloqueados"].append({"chave": e.chave, "tipos": e.tipos})
                    print(f"::error::barreira de PII: {e.chave} não gravado (tipos: {', '.join(e.tipos)})",
                          file=sys.stderr)
                    montado = None
                except Exception as e:  # noqa: BLE001 - só o tipo e a chave, nunca a mensagem
                    falha = f"{componente[0]}: {type(e).__name__}"
                    self.estat["falhas"].append(falha)
                    print(f"::warning::processamento falhou, nada gravado: {falha}", file=sys.stderr)
                    montado = None
                if montado is not None:
                    self._aplicar(componente, montado)
                if (desde >= max(1, self.op.checkpoint_componentes)
                        or time.monotonic() - ultimo >= self.op.checkpoint_segundos):
                    self._checkpoint()
                    desde, ultimo = 0, time.monotonic()
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    # ---- gravação (pontos de controle)
    def _grupo(self, chave: str) -> tuple[str, int] | None:
        valor = self.final.get(chave)
        if valor is None or not tem_texto(valor[0]):
            return None
        return valor[0]["tipo"], valor[1]

    def _caminho_final(self, chave: str) -> str | None:
        valor = self.final.get(chave)
        if valor is None or not tem_texto(valor[0]):
            return None
        e, ano = valor
        return caminho_texto(e["tipo"], ano, e["documento"], chave)

    def _finalizar(self) -> None:
        self._checkpoint(final=True)

    def _checkpoint(self, final: bool = False) -> None:
        """Grava textos novos, trechos e manifestos (nesta ordem), depois apaga os órfãos
        e salva os mapas do cache. Idempotente: sem mudanças pendentes, não grava nada."""
        with _SinaisAdiados():
            self._gravar_textos()
            apagar = self._gravar_trechos()
            self._gravar_manifestos(final)
            self._limpar_orfaos(apagar)
            self._salvar_mapa()
            self._salvar_ementas(final)
            if final:
                self._avisar_desconhecidos()
            for k in self.alterados:
                valor = self.final.get(k)
                self.anteriores_txt.pop(k, None)
                self.anteriores_grupos.pop(k, None)
                if valor is None:
                    self.gravado.pop(k, None)
                else:
                    self.gravado[k] = valor
                    self._anotar_anterior(k, *valor)
            self.txt_novos.clear()
            self.trechos_novos.clear()
            self.alterados.clear()
            self.anos_sujos.clear()

    def _gravar_textos(self) -> None:
        for k, conteudo in sorted(self.txt_novos.items()):
            rel = self._caminho_final(k)
            if rel is not None:
                _gravar_texto(self.pasta_textos / rel, conteudo)

    def _gravar_trechos(self) -> list[str]:
        """Regrava os `.jsonl` afetados; devolve os que ficaram vazios (apagados depois)."""
        grupos: set[tuple[str, int]] = set()
        for k in self.alterados:
            grupos.update(self.anteriores_grupos.get(k, ()))
            g = self._grupo(k)
            if g is not None:
                grupos.add(g)
        apagar: list[str] = []
        for tipo, ano in sorted(grupos):
            g = (tipo, ano)
            rel = caminho_trechos(tipo, ano)
            caminho = self.pasta_textos / rel
            itens: list[tuple[tuple, str]] = []
            desconhecidas = 0
            if caminho.is_file():
                for i, linha in enumerate(caminho.read_text(encoding="utf-8").splitlines()):
                    if not linha.strip():
                        continue
                    try:
                        t = json.loads(linha)
                    except ValueError:
                        t = None
                    if not isinstance(t, dict):
                        desconhecidas += 1
                        itens.append(((1, "", "", i), linha))
                        continue
                    k = t.get("arquivo") if isinstance(t.get("arquivo"), str) else ""
                    if self._grupo(k) == g:
                        if k not in self.trechos_novos:
                            itens.append((_ordem_trecho(t), linha_trecho(t)))
                    elif g in self.anteriores_grupos.get(k, ()):
                        continue  # de uma entrada anterior que saiu deste arquivo
                    else:
                        desconhecidas += 1
                        itens.append((_ordem_trecho(t), linha))
            for k, novos in self.trechos_novos.items():
                if self._grupo(k) == g:
                    itens.extend((_ordem_trecho(t), linha_trecho(t)) for t in novos)
            if desconhecidas:
                self.estat["desconhecidos"] += desconhecidas
                print(f"::warning::{rel}: {desconhecidas} linha(s) de trechos sem entrada conhecida, mantidas",
                      file=sys.stderr)
            itens.sort(key=lambda i: i[0])
            if itens:
                _gravar_texto(caminho, "".join(linha + "\n" for _, linha in itens))
            elif caminho.exists():
                apagar.append(rel)
        return apagar

    def _gravar_manifestos(self, final: bool = False) -> None:
        anos = set(self.anos_sujos)
        for k in self.alterados:
            if k in self.gravado:
                anos.add(self.gravado[k][1])
            if k in self.final:
                anos.add(self.final[k][1])
        if final:
            anos.update(a for _, a in self.final.values())
            anos.update(a for _, a in self.gravado.values())
        if not anos:
            return
        por_ano: dict[int, dict] = {ano: {} for ano in anos}
        for k, (e, ano) in self.final.items():
            if ano in por_ano:
                por_ano[ano][k] = e
        pasta = self.raiz / "data" / "textos"
        for ano in sorted(anos):
            caminho = pasta / f"manifesto-{ano}.json"
            mapa = por_ano[ano]
            if not mapa:
                with contextlib.suppress(FileNotFoundError):
                    caminho.unlink()
                continue
            try:
                igual = caminho.read_bytes() == arquivos.texto_mapa(mapa).encode("utf-8")
            except FileNotFoundError:
                igual = False
            if not igual:
                arquivos.salvar_mapa(caminho, mapa)

    def _apagar(self, caminho: Path, pastas: set[Path] | None = None) -> None:
        try:
            caminho.unlink()
        except FileNotFoundError:
            pass
        except OSError as e:
            print(f"::warning::não foi possível apagar {caminho} ({type(e).__name__})", file=sys.stderr)
            return
        if pastas is not None:
            pastas.add(caminho.parent)

    def _limpar_orfaos(self, apagar_trechos: list[str]) -> None:
        """Apaga só o que pertencia a entradas anteriores e deixou de ser esperado."""
        pastas: set[Path] = set()
        for k in sorted(self.alterados):
            esperado = self._caminho_final(k)
            for rel in sorted(self.anteriores_txt.get(k, ())):
                if rel != esperado:
                    self._apagar(self.pasta_textos / rel, pastas)
        for rel in apagar_trechos:
            self._apagar(self.pasta_textos / rel, pastas)
        raizes = {self.pasta_textos / "textos", self.pasta_textos / "trechos", self.pasta_textos}
        for pasta in sorted(pastas, key=lambda p: -len(p.parts)):
            atual = pasta
            while atual not in raizes and self.pasta_textos in atual.parents:
                try:
                    atual.rmdir()  # só as pastas vazias
                except OSError:
                    break
                atual = atual.parent
        if self.shas_remover:
            em_uso = {e.get("sha256_original") for e, _ in self.final.values() if e.get("status") != "removido"}
            for sha in sorted(self.shas_remover - em_uso):
                alvos = [self._original(sha), self.cache / "texto_bruto" / f"{sha}.txt",
                         self.cache / "texto_bruto" / f"{sha}.json"]
                pasta_ocr = self.cache / "ocr"
                if pasta_ocr.is_dir():
                    alvos.extend(sorted(pasta_ocr.glob(f"{sha}-*.json")))
                for alvo in alvos:
                    self._apagar(alvo)
                self._validos.pop(sha, None)
            self.shas_remover.clear()

    def _avisar_desconhecidos(self) -> None:
        pasta = self.pasta_textos / "textos"
        if not pasta.is_dir():
            return
        esperados = {caminho_texto(e["tipo"], ano, e["documento"], k)
                     for k, (e, ano) in self.final.items() if tem_texto(e)}
        desconhecidos = sorted(rel for rel in (p.relative_to(self.pasta_textos).as_posix()
                                               for p in pasta.rglob("*.txt")) if rel not in esperados)
        if desconhecidos:
            self.estat["desconhecidos"] += len(desconhecidos)
            print(f"::warning::{len(desconhecidos)} .txt sem entrada no manifesto, mantidos: "
                  f"{', '.join(desconhecidos[:5])}{' …' if len(desconhecidos) > 5 else ''}", file=sys.stderr)

    # ---- execução completa
    def executar(self) -> dict:
        """Processa a fila e grava manifesto, textos e trechos; devolve as estatísticas."""
        with self._travas(textos=True):
            return self._executar_travado()

    def _executar_travado(self) -> dict:
        remocoes.aplicar_remocoes(self.raiz, self.pasta_textos, hoje=self.hoje)
        self._carregar_estado()
        try:
            candidatos = []
            for k in sorted(self.fila, key=ordem_chave):
                motivo = self._motivo(k)
                if motivo is None:
                    continue
                _, tipo, ano, _ = principal(self.fila[k]["citacoes"])
                if not self._selecionado(tipo, ano):
                    continue
                if motivo in MOTIVOS_RECONSTRUIVEIS:
                    if self._em_cache(self.prev[k][0].get("sha256_original")):
                        self.reconstruir.add(k)  # primeiro e fora de --max-arquivos
                        continue
                    self.reprocessar.add(k)
                candidatos.append(k)
            limite = self.op.max_arquivos
            trabalho = candidatos[:limite] if limite > 0 else candidatos
            self.reprocessar &= set(trabalho)
            self.estat["reconstruidos"] = len(self.reconstruir)
            self.estat["trabalho"] = len(trabalho)
            self.estat["adiados_limite"] = len(candidatos) - len(trabalho)
            self._adquirir([(k, self.fila[k]["url"]) for k in trabalho])
            self._planejar()
            self._executar()
        except BaseException as e:
            self.estat["interrompido"] = type(e).__name__
            raise
        finally:
            self._finalizar()
            contagem: dict[str, int] = {}
            for e, _ in self.final.values():
                contagem[e["status"]] = contagem.get(e["status"], 0) + 1
            self.estat["status"] = dict(sorted(contagem.items()))
            self.estat["config_mudou"] = self.config_mudou
        return self.estat

    def so_extrair(self) -> dict:
        """Só baixa e extrai para o cache (`texto_bruto`); não grava manifesto nem textos."""
        with self._travas(textos=False):
            self.prev = carregar_manifestos(self.raiz, {})
            self._carregar_mapa()
            self.fila = citacoes(*carregar_registros(self.raiz))
            self.estat["fila"] = len(self.fila)
            self.estat["extraidos"] = 0
            try:
                candidatos = []
                for k in sorted(self.fila, key=ordem_chave):
                    if k in self.remocoes.chaves:
                        continue
                    _, tipo, ano, _ = principal(self.fila[k]["citacoes"])
                    if not self._selecionado(tipo, ano):
                        continue
                    anterior = self.prev.get(k)
                    sha = self.mapa.get(k) or (anterior[0].get("sha256_original") if anterior else None)
                    if sha and (self._removido_sha(sha) or self._em_cache(sha)):
                        continue
                    candidatos.append(k)
                limite = self.op.max_arquivos
                trabalho = candidatos[:limite] if limite > 0 else candidatos
                self.estat["trabalho"] = len(trabalho)
                self.estat["adiados_limite"] = len(candidatos) - len(trabalho)
                self._adquirir([(k, self.fila[k]["url"]) for k in trabalho])
                shas: list[str] = []
                for k in trabalho:
                    q = self.aquisicoes.get(k)
                    if q is not None and q.tipo == "ok" and q.sha not in shas:
                        shas.append(q.sha)
                executor = cf.ThreadPoolExecutor(max_workers=max(1, self.op.workers))
                try:
                    futuros = [(sha, executor.submit(self._extrair_sha, sha)) for sha in shas]
                    for sha, futuro in futuros:
                        obtido = _esperar(futuro)
                        if obtido is None:
                            self.estat["adiados_prazo"] += 1
                        elif isinstance(obtido, _Falha):
                            self.estat["falhas"].append(f"{sha}: {obtido}")
                            print(f"::warning::extração falhou: {sha}: {obtido}", file=sys.stderr)
                        elif obtido[1]:
                            self.estat["resultados_do_cache"] += 1
                        else:
                            self.estat["extraidos"] += 1
                finally:
                    executor.shutdown(wait=False, cancel_futures=True)
            except BaseException as e:
                self.estat["interrompido"] = type(e).__name__
                raise
            finally:
                with _SinaisAdiados():
                    self._salvar_mapa()
        return self.estat


def executar(op: Opcoes) -> dict:
    """Atalho: `Pipeline(op).executar()`."""
    return Pipeline(op).executar()


# ---------------------------------------------------------------- verificação (S7)
def _ler_trechos(pasta_textos: Path) -> tuple[dict[tuple[str, int], dict[str, list[dict]]], list[str]]:
    grupos: dict[tuple[str, int], dict[str, list[dict]]] = {}
    problemas: list[str] = []
    for caminho in sorted((pasta_textos / "trechos").glob("*/*.jsonl")):
        tipo, ano = caminho.parent.name, caminho.stem
        if not ano.isdigit():
            problemas.append(f"{caminho.name}: nome fora do padrão")
            continue
        grupo = grupos.setdefault((tipo, int(ano)), {})
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            if not linha.strip():
                continue
            try:
                t = json.loads(linha)
            except ValueError:
                problemas.append(f"{caminho_trechos(tipo, int(ano))}: linha que não é JSON")
                continue
            if not isinstance(t, dict):
                problemas.append(f"{caminho_trechos(tipo, int(ano))}: linha que não é objeto")
                continue
            if linha != linha_trecho(t):
                problemas.append(f"{caminho_trechos(tipo, int(ano))}: linha fora do formato canônico")
            grupo.setdefault(str(t.get("arquivo", "")), []).append(t)
    return grupos, problemas


def verificar(raiz: Path = RAIZ, pasta_textos: Path | None = None, cache: Path | None = None,
              amostra: int = AMOSTRA, extrair: Callable | None = None, semente: int = 0,
              liberados: Iterable[str] | None = None) -> dict:
    """Integridade de textos e trechos, `.txt` órfãos, `mascara.varrer` em todos os
    textos e reextração de uma amostra (0 = todas). Não grava nada (nem no cache):
    a reextração é sem OCR e sem cache de OCR, e entradas com OCR ficam "não comparável"."""
    pasta_textos = Path(pasta_textos) if pasta_textos is not None else textos_padrao()
    cache = Path(cache) if cache is not None else cache_padrao()
    extrair = extrair or extratores.extrair
    liberados = frozenset(liberados if liberados is not None else mascara.liberados(Path(raiz)))
    repetidas: dict[str, list[tuple[dict, int]]] = {}
    entradas = carregar_manifestos(raiz, repetidas)
    trechos_grupos, problemas = _ler_trechos(pasta_textos)
    falhas: list[dict] = [{"chave": "", "motivo": p} for p in problemas]
    conferidos = 0
    esperados: set[str] = set()

    def falha(chave: str, motivo: str) -> None:
        falhas.append({"chave": chave, "motivo": motivo})

    for k, ocorrencias in sorted(repetidas.items()):
        falha(k, f"chave em mais de um manifesto ({', '.join(str(a) for _, a in ocorrencias)})")
    for k, (e, ano) in sorted(entradas.items(), key=lambda i: ordem_chave(i[0]) if RE_CHAVE.match(i[0])
                              else (2, 0, i[0])):
        lista = trechos_grupos.get((e.get("tipo"), ano), {}).pop(k, [])
        if not tem_texto(e):
            if lista:
                falha(k, "trechos de uma entrada sem texto")
            continue
        rel = caminho_texto(e["tipo"], ano, e["documento"], k)
        esperados.add(rel)
        caminho = pasta_textos / rel
        if not caminho.is_file():
            falha(k, "texto ausente")
            continue
        dados = caminho.read_bytes()
        try:
            conteudo = dados.decode("utf-8")
        except UnicodeDecodeError:
            falha(k, "texto fora de UTF-8")
            continue
        fortes = sorted({o["tipo"] for o in mascara.varrer(conteudo[:-1] if conteudo.endswith("\n") else conteudo,
                                                            liberados) if o["forte"]}
                        | {o["tipo"] for o in mascara.varrer_estrito(
                            conteudo[:-1] if conteudo.endswith("\n") else conteudo, liberados)})
        if fortes:
            falha(k, f"ocorrência forte de mascara.varrer ({', '.join(fortes)})")
        if sha256(dados) != e["sha256_texto"]:
            falha(k, "sha256_texto não confere (texto adulterado)")
            continue
        if blob_git(dados) != e.get("blob_texto"):
            falha(k, "blob_texto não confere")
        if not conteudo.endswith("\n"):
            falha(k, "texto sem a quebra final")
            continue
        texto = conteudo[:-1]
        if len(texto) != e.get("chars"):
            falha(k, "chars não confere")
        lista.sort(key=lambda t: t.get("posicao", 0))
        if len(lista) != e.get("trechos") or sum(bool(t.get("vetorizavel")) for t in lista) != e.get(
                "trechos_vetorizaveis"):
            falha(k, "contagem de trechos não confere com o manifesto")
        elif e.get("versao_trechos") == trechos.VERSAO_TRECHOS:
            if lista != trechos.dividir(texto, e["documento"], k):
                falha(k, "trechos não conferem com o texto")
        else:
            for t in lista:
                parte = texto[t["inicio"]:t["fim"]]
                if sha256(parte.encode("utf-8")) != t["sha256"] or t["documento"] != e["documento"]:
                    falha(k, "trecho não confere com o texto")
                    break
        conferidos += 1
    for (tipo, ano), resto in sorted(trechos_grupos.items()):
        for k in sorted(resto, key=lambda c: ordem_chave(c) if RE_CHAVE.match(c) else (2, 0, c)):
            falha(k, f"trechos em {caminho_trechos(tipo, ano)} sem entrada correspondente")
    orfaos: list[str] = []
    if (pasta_textos / "textos").is_dir():
        for p in sorted((pasta_textos / "textos").rglob("*.txt")):
            rel = p.relative_to(pasta_textos).as_posix()
            if rel in esperados:
                continue
            orfaos.append(rel)
            falha(chave_do_caminho(rel), f"texto órfão sem entrada no manifesto ({rel})")
            try:
                conteudo = p.read_bytes().decode("utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            fortes = sorted({o["tipo"] for o in mascara.varrer(conteudo, liberados) if o["forte"]}
                            | {o["tipo"] for o in mascara.varrer_estrito(conteudo, liberados)})
            if fortes:
                falha(chave_do_caminho(rel), f"ocorrência forte de mascara.varrer ({', '.join(fortes)})")

    candidatos = sorted((k for k, (e, _) in entradas.items() if e.get("sha256_bruto") and e.get("sha256_original")),
                        key=ordem_chave)
    if amostra > 0 and len(candidatos) > amostra:
        candidatos = sorted(random.Random(semente).sample(candidatos, amostra), key=ordem_chave)
    nao_comparaveis: list[str] = []
    sem_original: list[str] = []
    reextraidos = 0
    for k in candidatos:
        e = entradas[k][0]
        if (e.get("paginas_ocr") or 0) > 0:
            nao_comparaveis.append(k)  # o OCR não é refeito (nem gravado) na verificação
            print(f"{k}: não comparável (OCR não refeito na verificação)", file=sys.stderr)
            continue
        original = cache / "arquivos" / e["sha256_original"]
        if not original.is_file():
            sem_original.append(k)
            continue
        dados = original.read_bytes()
        if sha256(dados) != e["sha256_original"]:
            falha(k, "original do cache não confere com sha256_original")
            continue
        try:
            r = extrair(dados, ocr=False, cache_ocr=None)
        except Exception as erro:  # noqa: BLE001 - só o tipo
            falha(k, f"reextração falhou ({type(erro).__name__})")
            continue
        if ((r.extrator or None), (r.versao_extrator or None)) != (e.get("extrator"), e.get("versao_extrator")):
            nao_comparaveis.append(k)
            print(f"{k}: não comparável (extrator {r.extrator or '-'} {r.versao_extrator or '-'} local, "
                  f"{e.get('extrator')} {e.get('versao_extrator')} no manifesto)", file=sys.stderr)
            continue
        reextraidos += 1
        if sha256(trechos.normalizar(r.texto).encode("utf-8")) != e["sha256_bruto"]:
            falha(k, "reextração difere de sha256_bruto")
    return {
        "entradas": len(entradas), "textos_conferidos": conferidos, "reextraidos": reextraidos,
        "nao_comparaveis": nao_comparaveis, "sem_original": sem_original, "orfaos": orfaos,
        "r2": "não verificado: sem credenciais nesta etapa (coletor.nuvem)", "falhas": falhas,
    }


# ---------------------------------------------------------------- barreira e commit (S6)
def _git(pasta: Path, *args: str, entrada: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(pasta), *args], input=entrada, capture_output=True, check=True)


def alterados_git(pasta: Path) -> list[tuple[str, str]]:
    """(status XY, caminho) dos arquivos alterados em `textos/`, `trechos/` e `.gitattributes`."""
    saida = _git(pasta, "status", "--porcelain", "-z", "--untracked-files=all", "--",
                 "textos", "trechos", ".gitattributes").stdout.decode("utf-8")
    partes = saida.split("\0")
    resultado: list[tuple[str, str]] = []
    i = 0
    while i < len(partes):
        item = partes[i]
        i += 1
        if len(item) < 4:
            continue
        xy, caminho = item[:2], item[3:]
        if "R" in xy or "C" in xy:
            i += 1  # caminho de origem da renomeação
        resultado.append((xy, caminho))
    return resultado


def chave_do_caminho(caminho: str) -> str:
    """`siscam:<id>` ou `sessao:<guid>` a partir de `textos/…/<origem>-<id>.txt`."""
    return Path(caminho).stem.replace("-", ":", 1)


def barreira(pasta: Path, caminhos: Iterable[str], liberados: Iterable[str]) -> list[dict]:
    """Chaves e tipos (nunca os valores) com ocorrência forte de `mascara.varrer`.

    Sem metadados de páginas, aplica só as regras normais. Os textos produzidos por
    `processar` já passaram pela máscara e pela barreira numérica das páginas OCR.
    """
    liberados = frozenset(liberados)
    bloqueios = []
    for rel in sorted(caminhos):
        conteudo = (pasta / rel).read_bytes().decode("utf-8")
        texto = conteudo[:-1] if conteudo.endswith("\n") else conteudo
        tipos = sorted({o["tipo"] for o in mascara.varrer(texto, liberados) if o["forte"]}
                       | {o["tipo"] for o in mascara.varrer_estrito(texto, liberados)})
        if tipos:
            bloqueios.append({"chave": chave_do_caminho(rel), "caminho": rel, "tipos": tipos})
    return bloqueios


def commit_textos(pasta: Path, liberados: Iterable[str], todos: bool = False) -> int:
    """Barreira de PII e commit em `dados-textos`; 0 se commitou (ou nada a commitar)."""
    pasta = Path(pasta)
    try:
        alterados = alterados_git(pasta)
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"::error::git status falhou em {pasta} ({type(e).__name__})", file=sys.stderr)
        return 1
    txts = [c for _, c in alterados if c.startswith("textos/") and c.endswith(".txt")]
    if todos:
        conferir = sorted(p.relative_to(pasta).as_posix() for p in (pasta / "textos").rglob("*.txt"))
    else:
        conferir = [c for c in txts if (pasta / c).is_file()]
    bloqueios = barreira(pasta, conferir, liberados)
    if bloqueios:
        print(f"::error::barreira de PII: {len(bloqueios)} texto(s) com ocorrência forte; commit abortado",
              file=sys.stderr)
        for b in bloqueios:
            print(f"  {b['chave']} ({b['caminho']}): {', '.join(b['tipos'])}", file=sys.stderr)
        return 1
    if not alterados:
        print("dados-textos: nada a commitar", file=sys.stderr)
        return 0
    n = len(txts) or len(alterados)
    try:
        _git(pasta, "add", "-A", "--pathspec-from-file=-", "--pathspec-file-nul",
             entrada="\0".join(c for _, c in alterados).encode("utf-8"))
        _git(pasta, "commit", "-q", "-m", f"Atualiza textos extraídos ({n} arquivos)")
    except (OSError, subprocess.CalledProcessError) as e:
        detalhe = getattr(e, "stderr", b"") or b""
        print(f"::error::commit em dados-textos falhou: {detalhe.decode('utf-8', 'replace').strip() or type(e).__name__}",
              file=sys.stderr)
        return 1
    print(f"dados-textos: commit de {n} arquivo(s)", file=sys.stderr)
    return 0


def _ler_marca(cache: Path) -> dict | None:
    dados = _ler_json_opcional(Path(cache) / MARCA_COMMIT)
    return dados if isinstance(dados, dict) else None


def _gravar_marca(cache: Path, sha_config: str) -> None:
    arquivos.salvar_json(Path(cache) / MARCA_COMMIT,
                         {"sha256_config": sha_config, "versao_mascara": mascara.VERSAO_MASCARA})


def varrer_todos(cache: Path, sha_config: str) -> bool:
    """Se a barreira do commit precisa varrer todos os textos: `sha256_config` ou
    `VERSAO_MASCARA` diferente do último commit (ou sem marca)."""
    marca = _ler_marca(cache)
    return (marca is None or marca.get("sha256_config") != sha_config
            or marca.get("versao_mascara") != mascara.VERSAO_MASCARA)


# ---------------------------------------------------------------- CLI
def intervalo_anos(texto: str) -> list[int]:
    """"2024" ou "2021-2026" (inclusivo)."""
    ini, _, fim = texto.strip().partition("-")
    primeiro, ultimo = int(ini), int(fim or ini)
    if primeiro > ultimo:
        raise ValueError(f"intervalo de anos invertido: {texto!r}")
    return list(range(primeiro, ultimo + 1))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--anos", default=None, help="ano ou intervalo inclusivo do manifesto (padrão: todos)")
    ap.add_argument("--tipos", default=",".join(TIPOS), help="tipos do principal: " + ",".join(TIPOS))
    ap.add_argument("--max-arquivos", type=int, default=MAX_ARQUIVOS, help="arquivos por execução; 0 = sem limite")
    ap.add_argument("--max-minutos", type=float, default=None, help="prazo interno; o resto fica pendente")
    ap.add_argument("--ocr", action="store_true", help="OCR das páginas escaneadas (pdftoppm + tesseract)")
    ap.add_argument("--sem-rede", action="store_true", help="só o cache; sem ele, pendente_download")
    ap.add_argument("--reprocessar-versao", action="store_true", help="reprocessa entradas de versões antigas")
    ap.add_argument("--so-extrair", action="store_true", help="só baixa e extrai para o cache (texto bruto)")
    ap.add_argument("--verificar", action="store_true", help="confere a integridade; não grava nada")
    ap.add_argument("--amostra", type=int, default=AMOSTRA, help="reextrações em --verificar (0 = todas)")
    ap.add_argument("--commit-textos", action="store_true", help="barreira de PII e commit em dados-textos")
    ap.add_argument("--forcar-trava", action="store_true",
                    help="substitui trava abandonada e religa a pasta dos textos a esta raiz")
    ap.add_argument("--textos", type=Path, default=None, help="worktree da branch dados-textos")
    ap.add_argument("--cache", type=Path, default=None, help="cache local (padrão: RADAR_CACHE)")
    ap.add_argument("--workers", type=int, default=int(os.environ.get("COLETOR_WORKERS", 4)))
    args = ap.parse_args(argv)
    pasta_textos = args.textos or textos_padrao()
    cache = args.cache or cache_padrao()
    if args.verificar:
        relatorio = verificar(RAIZ, pasta_textos, cache, args.amostra)
        print(json.dumps(relatorio, ensure_ascii=False, indent=1))
        return 1 if relatorio["falhas"] else 0
    tipos = [t.strip() for t in args.tipos.split(",") if t.strip()]
    desconhecidos = [t for t in tipos if t not in TIPOS]
    if not tipos or desconhecidos:
        ap.error(f"tipos desconhecidos: {', '.join(desconhecidos) or '(nenhum)'}; use {','.join(TIPOS)}")
    if args.max_arquivos < 0:
        ap.error("--max-arquivos não pode ser negativo")
    if args.max_minutos is not None and args.max_minutos <= 0:
        ap.error("--max-minutos precisa ser positivo")
    if args.so_extrair and args.commit_textos:
        ap.error("--so-extrair não combina com --commit-textos")
    try:
        anos = frozenset(intervalo_anos(args.anos)) if args.anos else None
    except ValueError as e:
        ap.error(f"--anos inválido: {e}")
    for nome in SINAIS_INTERROMPER:
        sinal = getattr(signal, nome, None)
        if sinal is not None:
            with contextlib.suppress(ValueError, OSError):
                signal.signal(sinal, _interromper)
    op = Opcoes(
        raiz=RAIZ, textos=pasta_textos, cache=cache, anos=anos, tipos=frozenset(tipos),
        max_arquivos=args.max_arquivos, ocr=args.ocr, sem_rede=args.sem_rede,
        reprocessar_versao=args.reprocessar_versao, workers=args.workers, forcar_trava=args.forcar_trava,
        prazo=time.monotonic() + 60 * args.max_minutos if args.max_minutos else None,
    )
    pipeline = Pipeline(op)
    try:
        estat = pipeline.so_extrair() if args.so_extrair else pipeline.executar()
    except ErroTrava as e:
        print(f"::error::{e}", file=sys.stderr)
        return 2
    except BaseException as e:
        print(f"::warning::coletor.textos interrompido ({type(e).__name__}); progresso gravado", file=sys.stderr)
        raise
    print(json.dumps(estat, ensure_ascii=False, indent=1))
    codigo = 1 if estat["bloqueados"] else 0
    if args.commit_textos:
        try:
            with Trava(cache, RAIZ, args.forcar_trava), Trava(pasta_textos, RAIZ, args.forcar_trava):
                todos = estat.get("config_mudou") or varrer_todos(cache, pipeline.sha_config)
                resultado = commit_textos(pasta_textos, pipeline.liberados, todos=bool(todos))
                if resultado == 0:
                    _gravar_marca(cache, pipeline.sha_config)
        except ErroTrava as e:
            print(f"::error::{e}", file=sys.stderr)
            resultado = 2
        codigo = max(codigo, resultado)
    return codigo


if __name__ == "__main__":
    sys.exit(main())
