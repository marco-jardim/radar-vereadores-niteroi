"""Identificação do formato de um arquivo pelos primeiros bytes (magic bytes).

Formatos: `docx`, `zip`, `pdf`, `doc` (OLE Compound File, que deve conter um
documento Word), `rtf`, `jpeg`, `png`, `tiff`, `html`, `texto`, `vazio` e
`desconhecido`. Não usa extensão nem tipo MIME do servidor.

Somente biblioteca padrão do Python.
"""
from __future__ import annotations

import io
import unicodedata
import zipfile

MAGICO_CFB = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_INICIO_HTML = (b"<!doctype html", b"<html", b"<head", b"<body", b"<meta", b"<title")


def _eh_docx(dados: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(dados)) as zf:
            nomes = set(zf.namelist())
    except (zipfile.BadZipFile, OSError, ValueError, EOFError):
        return False
    if "word/document.xml" in nomes:
        return True
    return "[Content_Types].xml" in nomes and any(n.startswith("word/") for n in nomes)


def _cabeca_texto(dados: bytes) -> bytes:
    cabeca = dados[:2048]
    for bom in (b"\xef\xbb\xbf",):
        if cabeca.startswith(bom):
            cabeca = cabeca[len(bom):]
    if cabeca.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            cabeca = cabeca.decode("utf-16").encode("utf-8", "replace")
        except UnicodeDecodeError:
            return b""
    return cabeca.lstrip().lower()


def _eh_html(cabeca: bytes) -> bool:
    if cabeca.startswith(_INICIO_HTML):
        return True
    if cabeca.startswith(b"<?xml") or cabeca.startswith(b"<!--"):
        return b"<html" in cabeca
    return False


def _eh_texto(dados: bytes) -> bool:
    amostra = dados[:8192]
    if b"\x00" in amostra:
        return False
    try:
        texto = amostra.decode("utf-8")
    except UnicodeDecodeError as exc:
        if exc.start < len(amostra) - 4:  # erro só no corte final é aceito
            try:
                texto = amostra.decode("cp1252")
            except UnicodeDecodeError:
                return False
        else:
            texto = amostra[:exc.start].decode("utf-8")
    if not texto.strip():
        return False
    ruins = sum(1 for c in texto
                if unicodedata.category(c) in ("Cc", "Cs", "Co", "Cn") and c not in "\r\n\t\f")
    return ruins / len(texto) <= 0.03


def detectar(dados: bytes) -> str:
    """Formato do arquivo a partir do conteúdo."""
    if not dados:
        return "vazio"
    if dados.startswith((b"PK\x03\x04", b"PK\x05\x06")):
        return "docx" if _eh_docx(dados) else "zip"
    inicio = dados[:64]
    if inicio.startswith(b"\xef\xbb\xbf"):
        inicio = inicio[3:]
    if inicio.lstrip().startswith(b"%PDF-"):  # só no começo: um HTML que cite %PDF- não é PDF
        return "pdf"
    if dados.startswith(MAGICO_CFB):
        return "doc"
    if dados[:64].lstrip().startswith(b"{\\rtf"):
        return "rtf"
    if dados.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if dados.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if dados.startswith((b"II*\x00", b"MM\x00*")):
        return "tiff"
    cabeca = _cabeca_texto(dados)
    if _eh_html(cabeca):
        return "html"
    if not dados.strip():
        return "vazio"
    if _eh_texto(dados):
        return "texto"
    return "desconhecido"
