"""Texto de content.xml de OpenDocument (ODT, ODS e ODP), sem metadados do pacote.

Parágrafos e títulos conservam quebras, spans conservam texto, células são separadas
por tabulação. text:s, text:tab e text:line-break viram espaços, tabulação e quebra.
Não expande repetições de linhas/células de planilha. Rejeita DTDs (inclusive entidades
externas), aninhamento excessivo e expansão de espaços acima do limite de saída.
O contêiner ZIP e seu orçamento compartilhado são tratados em zip.py.

Somente biblioteca padrão do Python.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from . import base
from .base import ErroFormato, ErroLimite

MIMETYPES = frozenset({
    b"application/vnd.oasis.opendocument.text",
    b"application/vnd.oasis.opendocument.spreadsheet",
    b"application/vnd.oasis.opendocument.presentation",
})
_OFFICE = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
_TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
_TABLE = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
_PARAGRAFOS = {_TEXT + "p", _TEXT + "h"}
_IGNORADOS = {_OFFICE + "annotation", _OFFICE + "scripts", _TEXT + "tracked-changes"}
_MAX_PROFUNDIDADE = 200


class _ArvoreSemDtd(ET.TreeBuilder):
    def doctype(self, nome, publico, sistema) -> None:
        raise ErroFormato("DTD não permitido em OpenDocument")


def extrair_conteudo(xml: bytes) -> str:
    """Extrai só o corpo de content.xml, sem atributos, estilos nem XML bruto."""
    raiz = ET.fromstring(xml, parser=ET.XMLParser(target=_ArvoreSemDtd()))
    corpo = raiz.find(_OFFICE + "body")
    if corpo is None:
        raise ErroFormato("OpenDocument sem office:body em content.xml")
    partes: list[str] = []
    tamanho = 0

    def acrescentar(texto: str, repeticoes: int = 1) -> None:
        nonlocal tamanho
        tamanho += len(texto) * repeticoes
        if tamanho > base.LIMITE_DESCOMPACTADO:
            raise ErroLimite("limite de texto expandido do OpenDocument excedido")
        partes.append(texto * repeticoes)

    def visitar(el: ET.Element, nivel: int = 0, em_texto: bool = False) -> None:
        nonlocal tamanho
        if nivel > _MAX_PROFUNDIDADE:
            raise ErroFormato("OpenDocument com aninhamento excessivo")
        if el.tag in _IGNORADOS:
            return
        if el.tag == _TEXT + "s":
            quantidade = int(el.get(_TEXT + "c", "1"))
            if quantidade < 1:
                raise ErroFormato("quantidade inválida de espaços em OpenDocument")
            acrescentar(" ", quantidade)
            return
        if el.tag in (_TEXT + "tab", _TEXT + "line-break"):
            acrescentar("\t" if el.tag == _TEXT + "tab" else "\n")
            return
        em_texto = em_texto or el.tag in _PARAGRAFOS
        inicio = len(partes)
        if em_texto and el.text:
            acrescentar(el.text)
        for filho in el:
            visitar(filho, nivel + 1, em_texto)
            if em_texto and filho.tail:
                acrescentar(filho.tail)
        if el.tag == _TABLE + "table-row":
            if len(partes) > inicio and partes[-1] == "\t":
                partes.pop()
                tamanho -= 1
            acrescentar("\n")
        elif el.tag in _PARAGRAFOS:
            acrescentar("\n")
        elif el.tag in (_TABLE + "table-cell", _TABLE + "covered-table-cell"):
            while len(partes) > inicio and partes[-1] == "\n":
                partes.pop()
                tamanho -= 1
            acrescentar("\t")

    visitar(corpo)
    return "".join(partes)
