"""Texto de arquivos HTML, com `html.parser`.

Ignora `script`, `style`, `noscript`, `template` e comentários; decodifica as
entidades; tags de bloco viram quebra de linha e células de tabela são separadas
por " | ". Espaços seguidos são reduzidos a um, exceto dentro de `pre`.
A codificação vem do BOM, do `<meta charset>`/declaração XML ou, na falta deles,
é UTF-8 com recuo para cp1252.

Somente biblioteca padrão do Python.
"""
from __future__ import annotations

import codecs
import re
from html.parser import HTMLParser

_IGNORADAS = {"script", "style", "noscript", "template", "svg", "math", "object", "iframe"}
_BLOCOS = {
    "p", "div", "br", "li", "ul", "ol", "dl", "dt", "dd", "table", "thead", "tbody",
    "tfoot", "caption", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "header",
    "footer", "aside", "nav", "main", "blockquote", "pre", "hr", "form", "address", "title",
    "figure", "figcaption", "fieldset", "legend", "details", "summary", "body", "html", "head",
}
_VAZIAS = {"br", "hr", "img", "meta", "link", "input", "area", "base", "col", "embed",
           "param", "source", "track", "wbr"}
_RE_CHARSET = re.compile(rb"""(?:charset|encoding)\s*=\s*["']?\s*([A-Za-z0-9._:-]+)""", re.I)
_RE_ESPACOS = re.compile(r"[ \t\r\n\f\v]+")


class _Coletor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.partes: list[str] = []
        self.ignorando = 0
        self.pre = 0
        self.celulas: list[int] = [0]

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _IGNORADAS:
            if tag not in _VAZIAS:
                self.ignorando += 1
            return
        if tag == "pre":
            self.pre += 1
        if tag == "tr":
            self.celulas[-1] = 0
        if tag == "table":
            self.celulas.append(0)
        if tag in ("td", "th"):
            if self.celulas[-1]:
                self.partes.append(" | ")
            self.celulas[-1] += 1
        if tag in _BLOCOS:
            self.partes.append("\n")

    def handle_startendtag(self, tag: str, attrs) -> None:
        if tag in _BLOCOS:
            self.partes.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _IGNORADAS:
            if tag not in _VAZIAS and self.ignorando:
                self.ignorando -= 1
            return
        if tag == "pre" and self.pre:
            self.pre -= 1
        if tag == "table" and len(self.celulas) > 1:
            self.celulas.pop()
        if tag in _BLOCOS or tag == "tr":  # linha da tabela: uma quebra só no fim
            self.partes.append("\n")

    def handle_data(self, data: str) -> None:
        if self.ignorando:
            return
        if self.pre:
            self.partes.append(data)
        else:
            self.partes.append(_RE_ESPACOS.sub(" ", data))


def _decodificar(dados: bytes) -> str:
    if dados.startswith(b"\xef\xbb\xbf"):
        return dados[3:].decode("utf-8", "replace")
    if dados.startswith((b"\xff\xfe", b"\xfe\xff")):
        return dados.decode("utf-16", "replace")
    m = _RE_CHARSET.search(dados[:4096])
    if m:
        nome = m.group(1).decode("ascii", "replace").lower()
        if nome in ("iso-8859-1", "latin-1", "latin1", "us-ascii", "ascii"):
            nome = "cp1252"  # como os navegadores
        try:
            codecs.lookup(nome)
            return dados.decode(nome, "replace")
        except LookupError:
            pass
    try:
        return dados.decode("utf-8")
    except UnicodeDecodeError:
        return dados.decode("cp1252", "replace")


def extrair_html(dados: bytes) -> str:
    """Texto visível do HTML."""
    coletor = _Coletor()
    coletor.feed(_decodificar(dados))
    coletor.close()
    linhas = [linha.strip(" ") for linha in "".join(coletor.partes).split("\n")]
    return "\n".join(linhas)
