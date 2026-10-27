"""OCR local com poppler (`pdftoppm`) e Tesseract, página a página.

Cada página escaneada de um PDF é rasterizada com
`pdftoppm -r 300 -gray -f N -l N -png -singlefile <pdf> <prefixo>` e lida com
`tesseract <imagem> <saída> -l por --psm 6 -c tessedit_create_txt=1 -c tessedit_create_tsv=1`, que grava numa única passada o
texto simples e o TSV. A confiança da página é a média das confianças (≥ 0) das
palavras do TSV. Imagens JPEG, PNG e TIFF vão direto ao tesseract.

Somente biblioteca padrão do Python; as ferramentas rodam por subprocess, sem shell.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from . import ferramentas as _ferr
from .base import CONFIANCA_MINIMA, ErroFerramenta, FerramentaAusente, Resultado

IDIOMA = "por"
RESOLUCAO = "300"
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
    texto = arq_txt.read_bytes().decode("utf-8", "replace")
    conf, palavras = confianca_tsv(arq_tsv.read_bytes().decode("utf-8", "replace"))
    for arq in (arq_txt, arq_tsv):
        arq.unlink(missing_ok=True)
    return texto, conf, palavras


def ocr_paginas_pdf(caminho_pdf: Path, paginas: list[int], pasta: Path,
                    ferramentas=None) -> dict[int, tuple[str, float | None, int]]:
    """OCR das páginas indicadas (base 1): {página: (texto, confiança, palavras)}."""
    resultado: dict[int, tuple[str, float | None, int]] = {}
    for n in paginas:
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
            resultado[n] = ocr_imagem(imagem, pasta, ferramentas)
        finally:
            imagem.unlink(missing_ok=True)
    return resultado


def status_ocr(confianca: float | None) -> str:
    if confianca is None:
        return "ok"
    return "ok_ocr" if confianca >= CONFIANCA_MINIMA else "ocr_baixa_confianca"


def extrair_imagem(dados: bytes, formato: str, ocr: bool, ferramentas=None) -> Resultado:
    """OCR de uma imagem; sem OCR pedido, `escaneado_sem_ocr`."""
    base = Resultado(formato=formato, paginas=1, paginas_escaneadas=[1])
    if not ocr:
        base.status = "escaneado_sem_ocr"
        return base
    try:
        verificar(ferramentas)
    except FerramentaAusente as exc:
        base.status, base.detalhe = "pendente_ferramenta", f"ferramenta ausente: {exc}"
        return base
    with tempfile.TemporaryDirectory(prefix="radar-ocr-", ignore_cleanup_errors=True) as nome_pasta:
        pasta = Path(nome_pasta)
        caminho = pasta / ("entrada" + _EXTENSOES.get(formato, ".img"))
        caminho.write_bytes(dados)
        texto, conf, _palavras = ocr_imagem(caminho, pasta, ferramentas)
    base.texto = texto
    base.extrator = "tesseract"
    base.versao_extrator = _ferr.versao("tesseract", ferramentas) or ""
    base.paginas_ocr = 1
    if conf is not None:
        base.confianca = round(conf, 2)
        base.confianca_paginas = {1: round(conf, 2)}
    base.status = status_ocr(conf)
    return base
