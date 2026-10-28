"""OCR local com poppler (`pdftoppm`) e Tesseract, página a página.

Cada página escaneada de um PDF é rasterizada com
`pdftoppm -r 300 -gray -f N -l N -png -singlefile <pdf> <prefixo>` e lida com
`tesseract <imagem> <saída> -l por --psm 6 -c tessedit_create_txt=1 -c tessedit_create_tsv=1`, que grava numa única passada o
texto simples e o TSV. A confiança da página é a média das confianças (≥ 0) das
palavras do TSV. Imagens JPEG, PNG e TIFF vão direto ao tesseract.

Somente biblioteca padrão do Python; as ferramentas rodam por subprocess, sem shell.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import ferramentas as _ferr
from .base import CONFIANCA_MINIMA, ErroFerramenta, FerramentaAusente, Resultado

IDIOMA = "por"
RESOLUCAO = "300"
# Orçamento por documento: o que passar fica pendente (`ok_parcial` ou
# `escaneado_sem_ocr`), para outra execução.
MAX_PAGINAS_OCR = 300
OCR_SEGUNDOS_DOCUMENTO = 1800
_EXTENSOES = {"jpeg": ".jpg", "png": ".png", "tiff": ".tif"}


def confianca_tsv(tsv: str) -> tuple[float | None, int]:
    """Média das confianças ≥ 0 das palavras (nível 5) do TSV e número de palavras."""
    linhas = tsv.splitlines()
    if not linhas:
        return None, 0
    cabecalho = linhas[0].split("\t")
    try:
        i_nivel, i_conf, i_texto = cabecalho.index("level"), cabecalho.index("conf"), cabecalho.index("text")
    except ValueError:
        return None, 0
    confiancas: list[float] = []
    for linha in linhas[1:]:
        colunas = linha.split("\t")
        if len(colunas) <= i_conf or colunas[i_nivel] != "5":
            continue
        texto = colunas[i_texto] if len(colunas) > i_texto else ""
        try:
            conf = float(colunas[i_conf])
        except ValueError:
            continue
        if conf >= 0 and texto.strip():
            confiancas.append(conf)
    if not confiancas:
        return None, 0
    return sum(confiancas) / len(confiancas), len(confiancas)


def verificar(ferramentas=None, pdf: bool = False) -> None:
    """FerramentaAusente se faltar tesseract, o idioma `por` ou, para PDF, pdftoppm."""
    if pdf and _ferr.resolver("pdftoppm", ferramentas) is None:
        raise FerramentaAusente("pdftoppm")
    if _ferr.resolver("tesseract", ferramentas) is None:
        raise FerramentaAusente("tesseract")
    if IDIOMA not in _ferr.idiomas_tesseract(ferramentas):
        raise FerramentaAusente(f"tesseract sem o idioma {IDIOMA}")


def ocr_imagem(caminho: Path, pasta: Path, ferramentas=None) -> tuple[str, float | None, int]:
    """Texto, confiança média e número de palavras de uma imagem."""
    base = pasta / f"ocr-{caminho.stem}"
    # As variáveis -c dispensam os arquivos configs/txt e configs/tsv, ausentes em alguns tessdata (ex.: scoop).
    _ferr.executar("tesseract", [str(caminho), str(base), "-l", IDIOMA, "--psm", "6",
                                 "-c", "tessedit_create_txt=1", "-c", "tessedit_create_tsv=1"], ferramentas)
    arq_txt = base.with_name(base.name + ".txt")
    arq_tsv = base.with_name(base.name + ".tsv")
    if not arq_txt.exists() or not arq_tsv.exists():
        raise ErroFerramenta("tesseract não gravou as saídas txt/tsv")
    # o tesseract encerra cada página com \f; aqui a página é uma só
    texto = arq_txt.read_bytes().decode("utf-8", "replace").replace("\f", "\n")
    conf, palavras = confianca_tsv(arq_tsv.read_bytes().decode("utf-8", "replace"))
    for arq in (arq_txt, arq_tsv):
        arq.unlink(missing_ok=True)
    return texto, conf, palavras


@dataclass
class OcrPaginas:
    """Resultado do OCR de um PDF: páginas lidas, com falha e não tentadas (orçamento)."""

    lidas: dict[int, tuple[str, float | None, int]] = field(default_factory=dict)
    falhas: dict[int, str] = field(default_factory=dict)
    adiadas: list[int] = field(default_factory=list)


def _ocr_pagina(caminho_pdf: Path, n: int, pasta: Path, ferramentas) -> tuple[str, float | None, int]:
    prefixo = pasta / f"pagina-{n}"
    _ferr.executar("pdftoppm", ["-r", RESOLUCAO, "-gray", "-f", str(n), "-l", str(n), "-png",
                                "-singlefile", str(caminho_pdf), str(prefixo)], ferramentas)
    imagem = prefixo.with_name(prefixo.name + ".png")
    if not imagem.exists():
        candidatas = sorted(pasta.glob(f"pagina-{n}*.png"))
        if not candidatas:
            raise ErroFerramenta(f"pdftoppm não gravou a página {n}")
        imagem = candidatas[0]
    try:
        return ocr_imagem(imagem, pasta, ferramentas)
    finally:
        imagem.unlink(missing_ok=True)


def _versao_ocr(ferramentas) -> str:
    """Identifica as ferramentas e opções do OCR, para invalidar o cache quando mudam."""
    descricao = "|".join([_ferr.versao("pdftoppm", ferramentas) or "", _ferr.versao("tesseract", ferramentas) or "",
                          RESOLUCAO, IDIOMA, "psm6"])
    return hashlib.sha1(descricao.encode("utf-8")).hexdigest()[:12]


def _ler_cache(arquivo: Path) -> tuple[str, float | None, int] | None:
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
        conf = dados["confianca"]
        return str(dados["texto"]), (float(conf) if conf is not None else None), int(dados["palavras"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _gravar_cache(arquivo: Path, lido: tuple[str, float | None, int]) -> None:
    """Gravação atômica da página no cache; o temporário tem nome único (mkstemp) na
    mesma pasta, para que duas linhas de execução nunca disputem o mesmo arquivo."""
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    # A média do TSV já fica neste cache por página; reconstruir trechos reutiliza
    # o valor, sem precisar conservar TSVs nem chamar Tesseract novamente.
    texto, conf, palavras = lido
    conteudo = json.dumps({"confianca": conf, "palavras": palavras, "texto": texto},
                          ensure_ascii=False, sort_keys=True).encode("utf-8")
    fd, temporario = tempfile.mkstemp(dir=arquivo.parent, prefix=f".{arquivo.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(conteudo)
        os.replace(temporario, arquivo)
    except BaseException:
        try:
            os.unlink(temporario)
        except FileNotFoundError:
            pass
        raise


def arquivo_cache(cache_ocr: Path, sha256: str, pagina: int, versao: str) -> Path:
    """`<cache_ocr>/<sha256>-<página>-<versão>.json` (PDFs e imagens avulsas, página 1)."""
    return Path(cache_ocr) / f"{sha256}-{pagina}-{versao}.json"


def ocr_paginas_pdf(caminho_pdf: Path, paginas: list[int], pasta: Path,
                    ferramentas=None, cache_ocr: Path | None = None,
                    sha256: str | None = None) -> OcrPaginas:
    """OCR das páginas indicadas (base 1), página a página.

    Erro de ferramenta numa página (código de saída ou tempo esgotado) não perde as
    demais: a página fica em `falhas`. Depois de `MAX_PAGINAS_OCR` páginas lidas nesta
    execução ou de `OCR_SEGUNDOS_DOCUMENTO` segundos, as restantes ficam em `adiadas`.

    Com `cache_ocr`, cada página lida fica em `<cache_ocr>/<sha256>-<página>-<versão>.json`
    (versão = pdftoppm, tesseract e opções); páginas já no cache não chamam as
    ferramentas nem contam no orçamento, e as adiadas são retomadas na próxima execução.
    """
    resultado = OcrPaginas()
    inicio = time.monotonic()
    feitas = 0
    versao = _versao_ocr(ferramentas) if cache_ocr is not None else ""
    if cache_ocr is not None and sha256 is None:
        sha256 = hashlib.sha256(Path(caminho_pdf).read_bytes()).hexdigest()
    for n in paginas:
        arquivo = arquivo_cache(cache_ocr, sha256, n, versao) if cache_ocr is not None else None
        if arquivo is not None and arquivo.exists():
            guardado = _ler_cache(arquivo)
            if guardado is not None:
                resultado.lidas[n] = guardado
                continue
        if feitas >= MAX_PAGINAS_OCR or time.monotonic() - inicio >= OCR_SEGUNDOS_DOCUMENTO:
            resultado.adiadas.append(n)
            continue
        try:
            lido = _ocr_pagina(caminho_pdf, n, pasta, ferramentas)
        except ErroFerramenta as exc:
            resultado.falhas[n] = str(exc)[:200]
            continue
        feitas += 1
        resultado.lidas[n] = lido
        if arquivo is not None:
            _gravar_cache(arquivo, lido)
    return resultado


def descrever_pendencias(ocr: OcrPaginas) -> str:
    """Texto do `detalhe` com as páginas com falha e as adiadas (a refazer)."""
    partes = []
    if ocr.falhas:
        partes.append("OCR falhou nas páginas " + ", ".join(map(str, sorted(ocr.falhas))))
    if ocr.adiadas:
        partes.append(f"OCR adiado (orçamento de {MAX_PAGINAS_OCR} páginas ou "
                      f"{OCR_SEGUNDOS_DOCUMENTO} s) nas páginas "
                      + ", ".join(map(str, ocr.adiadas[:20]))
                      + (" e outras" if len(ocr.adiadas) > 20 else ""))
    return "; ".join(partes)


def status_ocr(confianca: float | None) -> str:
    if confianca is None:
        return "ok"
    return "ok_ocr" if confianca >= CONFIANCA_MINIMA else "ocr_baixa_confianca"


def extrair_imagem(dados: bytes, formato: str, ocr: bool, ferramentas=None,
                   cache_ocr: Path | None = None) -> Resultado:
    """OCR de uma imagem; sem OCR pedido, `escaneado_sem_ocr`.

    Com `cache_ocr`, a leitura fica em `<cache_ocr>/<sha256 da imagem>-1-<versão>.json`,
    o mesmo esquema das páginas de PDF (página 1): a imagem já lida não chama o tesseract.
    """
    base = Resultado(formato=formato, paginas=1, paginas_escaneadas=[1])
    if not ocr:
        base.status = "escaneado_sem_ocr"
        return base
    try:
        verificar(ferramentas)
    except FerramentaAusente as exc:
        base.status, base.detalhe = "pendente_ferramenta", f"ferramenta ausente: {exc}"
        return base
    arquivo = None
    lido = None
    if cache_ocr is not None:
        arquivo = arquivo_cache(cache_ocr, hashlib.sha256(dados).hexdigest(), 1, _versao_ocr(ferramentas))
        if arquivo.exists():
            lido = _ler_cache(arquivo)
    if lido is None:
        with tempfile.TemporaryDirectory(prefix="radar-ocr-", ignore_cleanup_errors=True) as nome_pasta:
            pasta = Path(nome_pasta)
            caminho = pasta / ("entrada" + _EXTENSOES.get(formato, ".img"))
            caminho.write_bytes(dados)
            lido = ocr_imagem(caminho, pasta, ferramentas)
        if arquivo is not None:
            _gravar_cache(arquivo, lido)
    texto, conf, _palavras = lido
    base.texto = texto
    base.extrator = "tesseract"
    base.versao_extrator = _ferr.versao("tesseract", ferramentas) or ""
    base.paginas_ocr = 1
    if conf is not None:
        base.confianca = round(conf, 2)
        base.confianca_paginas = {1: round(conf, 2)}
    base.status = status_ocr(conf)
    return base
