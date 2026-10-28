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
  `sha256_config` diferente (sempre) e, com `--reprocessar-versao`, as com
  `versao_*` diferente. `--max-arquivos` (0 = sem limite) e `--max-minutos` limitam
  o trabalho; o resto fica para outra execução.
- **Remoções** (seção 6.1): pela chave, sem download; pelo SHA-256, baixado só para o
  hash e descartado (sem cache).
- **Download**: `Download.aspx?id=<id>` ou a URL da ata, com o User-Agent de
  `coletor.siscam`, tentativas e espera progressiva, em `--workers` (4) linhas.
  Originais em `<cache>/arquivos/<sha256>`; mapa chave → SHA-256 em
  `<cache>/textos_sha256.json` (lidos também `siscam_arquivos_sha256.json` e
  `atas_cache_sha256.json`, do levantamento), para não baixar de novo; com
  `--sem-rede`, só o cache (sem ele, `pendente_download`).
- **Processamento** (seção 1): `extrair` (OCR com `--ocr`, páginas em
  `<cache>/ocr`) → bruto em `<cache>/texto_bruto/<sha256>.txt` → `limpeza.limpar`
  → `mascara.mascarar` → `trechos.normalizar` → `trechos.dividir`, com a barreira
  `mascara.varrer`: texto com ocorrência forte não é gravado (a chave fica como
  estava e é listada, sem o valor).
- **Duplicatas** (seção 6.2): mesmo original sob várias chaves → a menor é a
  canônica, com a união dos documentos; as outras viram `duplicata`.
- **Gravação**: `.txt` e `trechos/<tipo>/<ano>.jsonl` na branch `dados-textos`
  (`--textos DIR`) e `data/textos/manifesto-<ano>.json` por `arquivos.salvar_mapa`.
  `processado_em` só muda com a regra da seção 9. Mesma entrada, mesmos bytes.
- **Interrupção**: SIGTERM ou Ctrl+C gravam de forma atômica o que já foi concluído
  (cada grupo de chaves ligadas por duplicatas entra inteiro ou não entra): o
  manifesto, os textos e os trechos ficam coerentes entre si.
- **`--commit-textos`**: depois do processamento, roda `mascara.varrer` em todos os
  `.txt` novos ou alterados (em todos, se `sha256_config` mudou desde o último
  commit) e só faz o commit em `dados-textos` sem nenhuma ocorrência forte.
- **`--verificar [--amostra N]`**: confere `sha256_texto`, `blob_texto`, `chars` e
  os trechos de todas as entradas e reextrai uma amostra do cache, comparando
  `sha256_bruto` só quando `extrator` e `versao_extrator` coincidem com os locais
  ("não comparável" nos demais). Não grava nada. O R2 fica para `coletor.nuvem`.

Uso (na raiz):
  python -m coletor.textos [--anos 2021-2026] [--tipos pl,requerimento,pdl,resolucao,ata]
      [--max-arquivos 500] [--max-minutos N] [--ocr] [--sem-rede] [--reprocessar-versao]
      [--textos DIR] [--cache DIR] [--workers 4] [--commit-textos]
  python -m coletor.textos --verificar [--amostra 20] [--textos DIR] [--cache DIR]
Somente biblioteca padrão do Python.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import contextlib
import datetime as dt
import hashlib
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
FUSO_BRASILIA = dt.timezone(dt.timedelta(hours=-3))
MAPA_CACHE = "textos_sha256.json"  # chave do manifesto → SHA-256, gravado por este módulo
MAPA_SISCAM = "siscam_arquivos_sha256.json"  # IdArquivo → SHA-256 (levantamento da Phase 0.1)
MAPA_ATAS = "atas_cache_sha256.json"  # atas → SHA-256 (levantamento da Phase 0.1)
MARCA_COMMIT = "textos_commit.json"  # sha256_config do último commit em dados-textos


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


def processar(entrada: dict, chave: str, resultado: Resultado, ementa: str, cliches, protecao,
              liberados: Iterable[str], versao_limpeza: str,
              sha_config: str) -> tuple[str | None, list[dict], str | None]:
    """Preenche a entrada com o pipeline (seção 1) a partir do `Resultado` da extração.

    `entrada` já tem `sha256_original`. Devolve o conteúdo do `.txt` (ou None), os
    trechos e o texto bruto (ou None). BarreiraPII se o texto final tiver ocorrência
    forte de `mascara.varrer`.
    """
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
    detalhe, _ = mascara.mascarar(resultado.detalhe or "", liberados)
    entrada["detalhe"] = detalhe[:300]
    if resultado.status not in STATUS_COM_TEXTO:
        return None, [], None
    bruto = trechos.normalizar(resultado.texto)
    # páginas que vieram do OCR: as de confianca_paginas (zip: None)
    ocr_paginas = None if resultado.formato == "zip" else set(resultado.confianca_paginas)
    limpo, contagens = limpeza.limpar(bruto, cliches, protecao, ementa=ementa, ocr_paginas=ocr_paginas)
    mascarado, mascarados = mascara.mascarar(limpo, liberados)
    texto = trechos.normalizar(mascarado)
    fortes = sorted({o["tipo"] for o in mascara.varrer(texto, liberados) if o["forte"]})
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


def carregar_manifestos(raiz: Path) -> dict[str, tuple[dict, int]]:
    """Entradas de todos os `data/textos/manifesto-<ano>.json`: chave → (entrada, ano)."""
    pasta = Path(raiz) / "data" / "textos"
    entradas: dict[str, tuple[dict, int]] = {}
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
            if chave in entradas:
                raise ValueError(f"{chave} aparece em dois manifestos ({entradas[chave][1]} e {ano})")
            entradas[chave] = (entrada, ano)
    return entradas


# ---------------------------------------------------------------- download e cache
def baixar_bytes(url: str, tentativas: int = TENTATIVAS, espera: float = ESPERA, timeout: float = TIMEOUT) -> bytes:
    """Bytes de `url`, com o User-Agent de `coletor.siscam`, tentativas e espera
    progressiva; erros 4xx definitivos (exceto 408 e 429) não são repetidos."""
    from .siscam import USER_AGENT

    erro: Exception | None = None
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            erro = e
            if 400 <= e.code < 500 and e.code not in (408, 429):
                break
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            erro = e
        if i + 1 < tentativas:
            time.sleep(espera * (i + 1))
    raise RuntimeError(f"falha ao baixar {url}: {erro}")


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
        print(f"::warning::{caminho}: JSON ilegível, ignorado ({e})", file=sys.stderr)
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


# ---------------------------------------------------------------- sinais
def _interromper(sinal: int, _quadro: object) -> None:
    """Trata o SIGTERM como Ctrl+C, para que a gravação parcial aconteça."""
    raise KeyboardInterrupt(f"sinal {sinal}")


class _SinaisAdiados:
    """Adia SIGINT/SIGTERM durante a gravação final (só na thread principal)."""

    def __enter__(self) -> _SinaisAdiados:
        self.recebido: int | None = None
        self.antigos: dict = {}
        if threading.current_thread() is threading.main_thread():
            for nome in ("SIGINT", "SIGTERM"):
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
    """Opções de uma execução; `extrair`, `baixar`, `liberados`, `pessoas` e `hoje`
    substituem as dependências reais (testes e fixtures)."""

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
    `duplicata` ou `processar`, com os campos do documento principal."""

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
            "fila": 0, "trabalho": 0, "adiados_limite": 0, "do_cache": 0, "baixados": 0, "falhas_download": 0,
            "removidos_sha": 0, "processados": 0, "adiados_prazo": 0, "falhas": [], "bloqueados": [],
            "sem_bytes_mantidos": 0,
        }
        self.aquisicoes: dict[str, Aquisicao] = {}
        self.prev: dict[str, tuple[dict, int]] = {}
        self.final: dict[str, tuple[dict, int]] = {}
        self.txt_novos: dict[str, str] = {}
        self.trechos_novos: dict[str, list[dict]] = {}
        self.alterados: set[str] = set()
        self.mapa: dict[str, str] = {}
        self.mapa_novos: dict[str, str] = {}
        self.config_mudou = False

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

    # ---- mapa de cache
    def _carregar_mapa(self) -> None:
        self.mapa_siscam_legado = _ler_json_opcional(self.cache / MAPA_SISCAM)
        for nome, dados, origem in ((MAPA_SISCAM, self.mapa_siscam_legado, "siscam"),
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

    # ---- fila e trabalho
    def _precisa(self, chave: str) -> bool:
        """Se a chave entra no trabalho por si (sem contar duplicatas e mudança de principal)."""
        if chave in self.remocoes.chaves:
            return False
        anterior = self.prev.get(chave)
        if anterior is None:
            return True
        p = anterior[0]
        status, sha = p.get("status"), p.get("sha256_original")
        if status == "removido":
            return not self._removido_sha(sha)  # remoção suspensa: processa de novo
        if status in ("pendente_download", "pendente_ferramenta"):
            return True
        if status in ("escaneado_sem_ocr", "ok_parcial") and self.op.ocr:
            return True
        if status == "duplicata" or self._removido_sha(sha):
            return False
        if p.get("sha256_config") is not None and p["sha256_config"] != self.sha_config:
            self.config_mudou = True
            return True
        if self.op.reprocessar_versao and any(p.get(c) != v for c, v in self.versoes.items()):
            return True
        return False

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
        tentados = set(self.aquisicoes)
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
            for sha, membros in grupos.items():
                canonica = membros[0]
                b = basicos[canonica]
                todas = [c for m in membros for c in self.fila[m]["citacoes"]]
                documento, tipo, ano, ementa = principal(todas)
                p, ano_p = self.prev.get(canonica, (None, None))
                processado_ok = (p is not None and p.get("status") not in SEM_PROCESSAMENTO
                                 and p.get("sha256_original") == sha)
                if b.adquirido:
                    acao = "processar"
                elif processado_ok and (not tem_texto(p) or (p["documento"], p["tipo"], ano_p) == (documento, tipo, ano)):
                    acao = "atualizar"
                elif processado_ok and not self._selecionado(tipo, ano):
                    acao = "manter"  # mudou o principal, mas fora de --anos/--tipos
                else:
                    acao = "processar"
                if acao == "processar" and not self._tem_bytes(sha):
                    if canonica not in tentados and not self._esgotado():
                        faltando.append(canonica)
                        continue
                    if processado_ok:
                        acao = "manter"
                        self.estat["sem_bytes_mantidos"] += 1
                    else:
                        sem_bytes.add(canonica)
                        refazer = True
                        continue
                if acao == "manter":
                    plano[canonica] = Plano("manter")
                else:
                    plano[canonica] = Plano(acao, sha, b.bytes, sorted({c[0] for c in todas}), documento, tipo,
                                            ano, ementa, self.fila[canonica]["url"])
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
    def _extrair_sha(self, sha: str):
        if self._esgotado():
            return None
        try:
            dados = self._original(sha).read_bytes()
            if sha256(dados) != sha:
                return _Falha("o original do cache não confere com o SHA-256")
            return self.extrair(dados, ocr=self.op.ocr, cache_ocr=self.cache / "ocr")
        except Exception as e:  # noqa: BLE001 - a falha fica registrada e nada é gravado
            return _Falha(f"{type(e).__name__}: {e}"[:300])

    def _montar(self, componente: list[str], futuros: dict[str, cf.Future]):
        entradas: dict[str, tuple[dict, int] | None] = {}
        txts: dict[str, str] = {}
        novos_trechos: dict[str, list[dict]] = {}
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
                resultado = _esperar(futuros[pl.sha])
                if resultado is None:
                    raise _Adiado(k)
                if isinstance(resultado, _Falha):
                    raise _Falha(f"{k}: {resultado}")
                conteudo, lista, bruto = processar(e, k, resultado, pl.ementa, self.cliches, self.protecao,
                                                   self.liberados, self.versao_limpeza, self.sha_config)
                if bruto is not None:
                    _gravar_texto(self.cache / "texto_bruto" / f"{pl.sha}.txt", bruto + "\n")
                if conteudo is not None:
                    txts[k] = conteudo
                    novos_trechos[k] = lista
            e["processado_em"] = processado_em(e, p, self.hoje)
            entradas[k] = (e, pl.ano)
        return entradas, txts, novos_trechos

    def _executar(self) -> None:
        componentes = self._componentes()
        pedidos: list[str] = []
        for componente in componentes:
            for k in componente:
                pl = self.plano[k]
                if pl.acao == "processar" and pl.sha not in pedidos:
                    pedidos.append(pl.sha)
        (self.cache / "ocr").mkdir(parents=True, exist_ok=True)
        executor = cf.ThreadPoolExecutor(max_workers=max(1, self.op.workers))
        try:
            futuros = {sha: executor.submit(self._extrair_sha, sha) for sha in pedidos}
            for componente in componentes:
                try:
                    entradas, txts, novos_trechos = self._montar(componente, futuros)
                except _Adiado:
                    self.estat["adiados_prazo"] += 1
                    continue
                except _Falha as e:
                    self.estat["falhas"].append(str(e))
                    print(f"::warning::extração falhou, nada gravado: {e}", file=sys.stderr)
                    continue
                except BarreiraPII as e:
                    self.estat["bloqueados"].append({"chave": e.chave, "tipos": e.tipos})
                    print(f"::error::barreira de PII: {e.chave} não gravado (tipos: {', '.join(e.tipos)})",
                          file=sys.stderr)
                    continue
                for k, valor in entradas.items():
                    anterior = self.final.get(k)
                    if valor is None:
                        self.final.pop(k, None)
                    else:
                        self.final[k] = valor
                    if anterior != valor:
                        self.alterados.add(k)
                self.txt_novos.update(txts)
                self.trechos_novos.update(novos_trechos)
                self.alterados.update(txts)
                self.estat["processados"] += sum(1 for k in componente if self.plano[k].acao == "processar")
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    # ---- gravação
    def _grupo(self, chave: str) -> tuple[str, int] | None:
        valor = self.final.get(chave)
        if valor is None or not tem_texto(valor[0]):
            return None
        return valor[0]["tipo"], valor[1]

    def _finalizar(self) -> None:
        with _SinaisAdiados():
            self._gravar_textos()
            self._gravar_trechos()
            self._gravar_manifestos()
            self._salvar_mapa()

    def _gravar_textos(self) -> None:
        esperados = set()
        for k, (e, ano) in self.final.items():
            if tem_texto(e):
                esperados.add(caminho_texto(e["tipo"], ano, e["documento"], k))
        for k, conteudo in sorted(self.txt_novos.items()):
            if k in self.final:
                e, ano = self.final[k]
                _gravar_texto(self.pasta_textos / caminho_texto(e["tipo"], ano, e["documento"], k), conteudo)
        pasta = self.pasta_textos / "textos"
        if not pasta.is_dir():
            return
        for caminho in sorted(pasta.rglob("*.txt")):  # textos sem entrada no manifesto saem
            if caminho.relative_to(self.pasta_textos).as_posix() not in esperados:
                caminho.unlink()
        for diretorio in sorted((d for d in pasta.rglob("*") if d.is_dir()), key=lambda d: -len(d.parts)):
            with contextlib.suppress(OSError):
                diretorio.rmdir()  # só as pastas vazias

    def _gravar_trechos(self) -> None:
        grupos: set[tuple[str, int]] = set()
        for k in self.alterados:
            anterior = self.prev.get(k)
            if anterior is not None and tem_texto(anterior[0]):
                grupos.add((anterior[0]["tipo"], anterior[1]))
            g = self._grupo(k)
            if g is not None:
                grupos.add(g)
        for tipo, ano in sorted(grupos):
            caminho = self.pasta_textos / caminho_trechos(tipo, ano)
            lista: list[dict] = []
            if caminho.is_file():
                for linha in caminho.read_text(encoding="utf-8").splitlines():
                    if linha.strip():
                        t = json.loads(linha)
                        if t["arquivo"] not in self.trechos_novos and self._grupo(t["arquivo"]) == (tipo, ano):
                            lista.append(t)
            for k, novos in self.trechos_novos.items():
                if self._grupo(k) == (tipo, ano):
                    lista.extend(novos)
            lista.sort(key=lambda t: (t["documento"], t["arquivo"], t["posicao"]))
            if lista:
                _gravar_texto(caminho, "".join(linha_trecho(t) + "\n" for t in lista))
            elif caminho.exists():
                caminho.unlink()

    def _gravar_manifestos(self) -> None:
        por_ano: dict[int, dict] = {}
        for k, (e, ano) in self.final.items():
            por_ano.setdefault(ano, {})[k] = e
        pasta = self.raiz / "data" / "textos"
        anos_antes = {ano for _, ano in self.prev.values()}
        for ano, mapa in sorted(por_ano.items()):
            caminho = pasta / f"manifesto-{ano}.json"
            try:
                igual = caminho.read_bytes() == arquivos.texto_mapa(mapa).encode("utf-8")
            except FileNotFoundError:
                igual = False
            if not igual:
                arquivos.salvar_mapa(caminho, mapa)
        for ano in sorted(anos_antes - set(por_ano)):
            with contextlib.suppress(FileNotFoundError):
                (pasta / f"manifesto-{ano}.json").unlink()

    # ---- execução completa
    def executar(self) -> dict:
        """Processa a fila e grava manifesto, textos e trechos; devolve as estatísticas."""
        self.prev = carregar_manifestos(self.raiz)
        self.final = dict(self.prev)
        self._carregar_mapa()
        self.fila = citacoes(*carregar_registros(self.raiz))
        self.estat["fila"] = len(self.fila)
        try:
            candidatos = []
            for k in sorted(self.fila, key=ordem_chave):
                if not self._precisa(k):
                    continue
                _, tipo, ano, _ = principal(self.fila[k]["citacoes"])
                if self._selecionado(tipo, ano):
                    candidatos.append(k)
            limite = self.op.max_arquivos
            trabalho = candidatos[:limite] if limite > 0 else candidatos
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
            t = json.loads(linha)
            if linha != linha_trecho(t):
                problemas.append(f"{caminho_trechos(tipo, int(ano))}: linha fora do formato canônico")
            grupo.setdefault(t.get("arquivo", ""), []).append(t)
    return grupos, problemas


def verificar(raiz: Path = RAIZ, pasta_textos: Path | None = None, cache: Path | None = None,
              amostra: int = AMOSTRA, extrair: Callable | None = None, semente: int = 0) -> dict:
    """Integridade de textos e trechos e reextração de uma amostra (0 = todas); não grava."""
    pasta_textos = Path(pasta_textos) if pasta_textos is not None else textos_padrao()
    cache = Path(cache) if cache is not None else cache_padrao()
    extrair = extrair or extratores.extrair
    entradas = carregar_manifestos(raiz)
    trechos_grupos, problemas = _ler_trechos(pasta_textos)
    falhas: list[dict] = [{"chave": "", "motivo": p} for p in problemas]
    conferidos = 0

    def falha(chave: str, motivo: str) -> None:
        falhas.append({"chave": chave, "motivo": motivo})

    for k, (e, ano) in sorted(entradas.items(), key=lambda i: ordem_chave(i[0])):
        lista = trechos_grupos.get((e.get("tipo"), ano), {}).pop(k, [])
        if not tem_texto(e):
            if lista:
                falha(k, "trechos de uma entrada sem texto")
            continue
        caminho = pasta_textos / caminho_texto(e["tipo"], ano, e["documento"], k)
        if not caminho.is_file():
            falha(k, "texto ausente")
            continue
        dados = caminho.read_bytes()
        if sha256(dados) != e["sha256_texto"]:
            falha(k, "sha256_texto não confere (texto adulterado)")
            continue
        if blob_git(dados) != e.get("blob_texto"):
            falha(k, "blob_texto não confere")
        conteudo = dados.decode("utf-8")
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

    candidatos = sorted((k for k, (e, _) in entradas.items() if e.get("sha256_bruto") and e.get("sha256_original")),
                        key=ordem_chave)
    if amostra > 0 and len(candidatos) > amostra:
        candidatos = sorted(random.Random(semente).sample(candidatos, amostra), key=ordem_chave)
    nao_comparaveis: list[str] = []
    sem_original: list[str] = []
    reextraidos = 0
    for k in candidatos:
        e = entradas[k][0]
        original = cache / "arquivos" / e["sha256_original"]
        if not original.is_file():
            sem_original.append(k)
            continue
        dados = original.read_bytes()
        if sha256(dados) != e["sha256_original"]:
            falha(k, "original do cache não confere com sha256_original")
            continue
        r = extrair(dados, ocr=(e.get("paginas_ocr") or 0) > 0, cache_ocr=cache / "ocr")
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
        "nao_comparaveis": nao_comparaveis, "sem_original": sem_original,
        "r2": "não verificado: sem credenciais nesta etapa (coletor.nuvem)", "falhas": falhas,
    }


# ---------------------------------------------------------------- barreira e commit (S6)
def _git(pasta: Path, *args: str, entrada: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(pasta), *args], input=entrada, capture_output=True, check=True)


def alterados_git(pasta: Path) -> list[tuple[str, str]]:
    """(status XY, caminho) dos arquivos alterados em `textos/` e `trechos/`."""
    saida = _git(pasta, "status", "--porcelain", "-z", "--untracked-files=all", "--",
                 "textos", "trechos").stdout.decode("utf-8")
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
    """Chaves e tipos (nunca os valores) com ocorrência forte de `mascara.varrer`."""
    liberados = frozenset(liberados)
    bloqueios = []
    for rel in sorted(caminhos):
        conteudo = (pasta / rel).read_bytes().decode("utf-8")
        texto = conteudo[:-1] if conteudo.endswith("\n") else conteudo
        tipos = sorted({o["tipo"] for o in mascara.varrer(texto, liberados) if o["forte"]})
        if tipos:
            bloqueios.append({"chave": chave_do_caminho(rel), "caminho": rel, "tipos": tipos})
    return bloqueios


def commit_textos(pasta: Path, liberados: Iterable[str], todos: bool = False) -> int:
    """Barreira de PII e commit em `dados-textos`; 0 se commitou (ou nada a commitar)."""
    pasta = Path(pasta)
    try:
        alterados = alterados_git(pasta)
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"::error::git status falhou em {pasta}: {e}", file=sys.stderr)
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
        print(f"::error::commit em dados-textos falhou: {detalhe.decode('utf-8', 'replace').strip() or e}",
              file=sys.stderr)
        return 1
    print(f"dados-textos: commit de {n} arquivo(s)", file=sys.stderr)
    return 0


def _ler_marca(cache: Path) -> str | None:
    dados = _ler_json_opcional(Path(cache) / MARCA_COMMIT)
    return dados.get("sha256_config") if isinstance(dados, dict) else None


def _gravar_marca(cache: Path, sha_config: str) -> None:
    arquivos.salvar_json(Path(cache) / MARCA_COMMIT, {"sha256_config": sha_config})


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
    ap.add_argument("--verificar", action="store_true", help="confere a integridade; não grava nada")
    ap.add_argument("--amostra", type=int, default=AMOSTRA, help="reextrações em --verificar (0 = todas)")
    ap.add_argument("--commit-textos", action="store_true", help="barreira de PII e commit em dados-textos")
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
    try:
        anos = frozenset(intervalo_anos(args.anos)) if args.anos else None
    except ValueError as e:
        ap.error(f"--anos inválido: {e}")
    with contextlib.suppress(ValueError, OSError, AttributeError):
        signal.signal(signal.SIGTERM, _interromper)
    op = Opcoes(
        raiz=RAIZ, textos=pasta_textos, cache=cache, anos=anos, tipos=frozenset(tipos),
        max_arquivos=args.max_arquivos, ocr=args.ocr, sem_rede=args.sem_rede,
        reprocessar_versao=args.reprocessar_versao, workers=args.workers,
        prazo=time.monotonic() + 60 * args.max_minutos if args.max_minutos else None,
    )
    pipeline = Pipeline(op)
    try:
        estat = pipeline.executar()
    except BaseException as e:
        print(f"::warning::coletor.textos interrompido ({type(e).__name__}); progresso gravado", file=sys.stderr)
        raise
    print(json.dumps(estat, ensure_ascii=False, indent=1))
    codigo = 1 if estat["bloqueados"] else 0
    if args.commit_textos:
        todos = estat.get("config_mudou") or _ler_marca(cache) != pipeline.sha_config
        resultado = commit_textos(pasta_textos, pipeline.liberados, todos=todos)
        if resultado == 0:
            _gravar_marca(cache, pipeline.sha_config)
        codigo = max(codigo, resultado)
    return codigo


if __name__ == "__main__":
    sys.exit(main())
