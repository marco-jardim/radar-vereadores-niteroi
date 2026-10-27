"""Extração do inteiro teor dos arquivos do SISCAM.

`extrair(dados, ocr=False, ferramentas=None) -> Resultado` detecta o formato pelos
magic bytes e aplica o extrator certo:

| Formato | Extrator |
| --- | --- |
| docx | `docx.py` (zipfile + xml.etree) |
| doc (Word 97–2003) | `cfb.py` + `doc.py` (FIB e piece table) |
| rtf, html, texto | `rtf.py`, `html.py`, decodificação direta |
| pdf | `pdf.py` (pdftotext por subprocess; OCR das páginas escaneadas) |
| jpeg, png, tiff | `ocr.py` (tesseract por subprocess) |
| zip | `zip.py` (membros extraídos recursivamente, até 2 níveis) |

O texto devolvido sai normalizado por `coletor.trechos.normalizar`. Nenhuma
exceção de formato escapa: arquivo malformado vira `erro_formato`; ferramenta
ausente vira `pendente_ferramenta`. `ferramentas` mapeia o nome da ferramenta
(`pdftotext`, `pdftoppm`, `tesseract`) para o executável, uma lista de prefixo de
comando ou None (indisponível); nomes ausentes são procurados no PATH.

Somente biblioteca padrão do Python.
"""
from __future__ import annotations

import struct
import xml.etree.ElementTree as ET
import zipfile
import zlib

from ..trechos import normalizar
from . import base
from . import detectar as _detectar
from . import doc as _doc
from . import docx as _docx
from . import ferramentas as _ferramentas
from . import html as _html
from . import ocr as _ocr
from . import pdf as _pdf
from . import rtf as _rtf
from . import zip as _zip
from .base import (
    CONFIANCA_MINIMA,
    STATUS,
    VERSAO_EXTRATORES,
    ErroFerramenta,
    ErroFormato,
    ErroLimite,
    FerramentaAusente,
    Resultado,
)
from .cfb import ErroCFB

__all__ = [
    "CONFIANCA_MINIMA",
    "STATUS",
    "VERSAO_EXTRATORES",
    "ErroCFB",
    "ErroFormato",
    "ErroLimite",
    "Resultado",
    "detectar",
    "extrair",
    "ferramentas_disponiveis",
]

_ERROS_FORMATO = (
    ErroFormato, ValueError, KeyError, IndexError, struct.error, zipfile.BadZipFile,
    zlib.error, ET.ParseError, EOFError, RecursionError, OverflowError, LookupError,
    MemoryError,
)
_STATUS_COM_TEXTO = ("ok", "ok_ocr", "ocr_baixa_confianca")


def detectar(dados: bytes) -> str:
    """Formato do arquivo pelos magic bytes (veja `detectar.detectar`)."""
    return _detectar.detectar(dados)


def ferramentas_disponiveis(ferramentas=None) -> dict:
    """Versões de pdftotext, pdftoppm e tesseract (None se ausente) e idiomas do tesseract."""
    return _ferramentas.disponiveis(ferramentas)


def _decodificar_texto(dados: bytes) -> str:
    if dados.startswith(b"\xef\xbb\xbf"):
        return dados[3:].decode("utf-8", "replace")
    if dados.startswith((b"\xff\xfe", b"\xfe\xff")):
        return dados.decode("utf-16", "replace")
    try:
        return dados.decode("utf-8")
    except UnicodeDecodeError:
        return dados.decode("cp1252", "replace")


def _interno(nome: str, texto: str, formato: str | None = None) -> Resultado:
    return Resultado(formato=formato or nome, texto=texto, extrator=nome,
                     versao_extrator=VERSAO_EXTRATORES, status="ok")


def _por_formato(formato: str, dados: bytes, ocr: bool, ferramentas, profundidade: int,
                 orcamento: list[int], cache_ocr=None) -> Resultado:
    if formato == "vazio":
        return Resultado(formato="vazio", status="vazio_legitimo", detalhe="arquivo sem conteúdo")
    if formato == "docx":
        texto, cabecalhos = _docx.extrair_docx(dados, orcamento)
        resultado = _interno("docx", texto)
        resultado.cabecalhos_omitidos = cabecalhos
        return resultado
    if formato == "doc":
        texto, avisos, cabecalhos = _doc.extrair_doc(dados)
        resultado = _interno("doc", texto)
        resultado.cabecalhos_omitidos = cabecalhos
        resultado.detalhe = "; ".join(avisos)
        return resultado
    if formato == "rtf":
        return _interno("rtf", _rtf.extrair_rtf(dados))
    if formato == "html":
        return _interno("html", _html.extrair_html(dados))
    if formato == "texto":
        return _interno("texto", _decodificar_texto(dados))
    if formato == "pdf":
        return _pdf.extrair_pdf(dados, ocr, ferramentas, cache_ocr)
    if formato in ("jpeg", "png", "tiff"):
        return _ocr.extrair_imagem(dados, formato, ocr, ferramentas)
    if formato == "zip":
        def membro(d, o, f, p, orc):
            return _extrair(d, o, f, p, orc, cache_ocr)
        return _zip.extrair_zip(dados, ocr, ferramentas, profundidade, orcamento, membro)
    raise ErroFormato("formato desconhecido")


def _extrair(dados: bytes, ocr: bool, ferramentas, profundidade: int,
             orcamento: list[int], cache_ocr=None) -> Resultado:
    formato = _detectar.detectar(dados)
    try:
        resultado = _por_formato(formato, dados, ocr, ferramentas, profundidade, orcamento, cache_ocr)
    except FerramentaAusente as exc:
        resultado = Resultado(formato=formato, status="pendente_ferramenta",
                              detalhe=f"ferramenta ausente: {exc}")
    except ErroFerramenta as exc:
        resultado = Resultado(formato=formato, status="erro_formato", detalhe=str(exc))
    except _ERROS_FORMATO as exc:
        resultado = Resultado(formato=formato, status="erro_formato",
                              detalhe=f"{type(exc).__name__}: {exc}"[:300])
    resultado.texto = normalizar(resultado.texto)
    if resultado.status in _STATUS_COM_TEXTO and not resultado.texto.strip():
        resultado.status = "vazio_legitimo"
    return resultado


def extrair(dados: bytes, ocr: bool = False, ferramentas=None, cache_ocr=None) -> Resultado:
    """Extrai o texto de um arquivo; nunca levanta exceção por arquivo malformado.

    `cache_ocr` (pasta ou None) guarda o OCR de cada página de PDF, para não repetir
    páginas já lidas e retomar as adiadas pelo orçamento em outra execução.
    """
    return _extrair(bytes(dados), ocr, ferramentas, 1, [base.LIMITE_DESCOMPACTADO], cache_ocr)
