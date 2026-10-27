"""Texto de documentos Word 2007+ (docx, WordprocessingML).

Lê o documento principal indicado em `_rels/.rels` (ou `word/document.xml`),
depois as notas de rodapé e as notas de fim. Cabeçalhos e rodapés só são contados,
não entram no texto. Cada parágrafo `w:p`
vira uma linha; `w:tab` vira tabulação; `w:br`/`w:cr` viram quebra de linha.
Tabelas saem linha a linha, com as células separadas por " | ". Texto excluído
em revisão (`w:delText`), códigos de campo (`w:instrText`) e o conteúdo
alternativo de compatibilidade (`mc:Fallback`) são ignorados.

Somente biblioteca padrão do Python.
"""
from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
import zipfile

from . import base
from .base import ErroFormato, ErroLimite, ler_membro_zip

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

W_P, W_TBL, W_TR, W_TC = W + "p", W + "tbl", W + "tr", W + "tc"
W_T, W_TAB, W_BR, W_CR = W + "t", W + "tab", W + "br", W + "cr"
W_NBHYPHEN, W_TXBX = W + "noBreakHyphen", W + "txbxContent"
_IGNORADOS = {W + "delText", W + "instrText", W + "pPr", W + "rPr", W + "sectPr",
              W + "tblPr", W + "tblGrid", W + "trPr", W + "tcPr", MC + "Fallback",
              W + "delInstrText", W + "fldData"}
_CONTENTORES_LINHA = {W + "sdt", W + "sdtContent", W + "customXml", W + "ins", W + "moveTo"}
_TIPOS_NOTA_IGNORADOS = {"separator", "continuationSeparator", "continuationNotice"}
_RE_CABECALHO = re.compile(r"^word/(header|footer)(\d*)\.xml$")
_MAX_PROFUNDIDADE = 200


def _paragrafo(p: ET.Element, profundidade: int) -> list[str]:
    """Linha do parágrafo, seguida das linhas de caixas de texto ancoradas nele."""
    partes: list[str] = []
    caixas: list[str] = []

    def visitar(el: ET.Element, nivel: int) -> None:
        if nivel > _MAX_PROFUNDIDADE:
            raise ErroFormato("docx com aninhamento excessivo")
        for filho in el:
            tag = filho.tag
            if tag == W_T:
                partes.append(filho.text or "")
            elif tag == W_TAB:
                partes.append("\t")
            elif tag in (W_BR, W_CR):
                partes.append("\n")
            elif tag == W_NBHYPHEN:
                partes.append("-")
            elif tag in _IGNORADOS:
                continue
            elif tag == W_TXBX:
                _blocos(filho, caixas, nivel + 1)
            else:
                visitar(filho, nivel + 1)

    visitar(p, profundidade)
    return ["".join(partes), *caixas]


def _celulas(linha: ET.Element):
    for filho in linha:
        if filho.tag == W_TC:
            yield filho
        elif filho.tag in _CONTENTORES_LINHA:
            yield from _celulas(filho)


def _linhas_tabela(tabela: ET.Element):
    for filho in tabela:
        if filho.tag == W_TR:
            yield filho
        elif filho.tag in _CONTENTORES_LINHA:
            yield from _linhas_tabela(filho)


def _tabela(tbl: ET.Element, profundidade: int) -> list[str]:
    linhas: list[str] = []
    for tr in _linhas_tabela(tbl):
        celulas = []
        for tc in _celulas(tr):
            conteudo: list[str] = []
            _blocos(tc, conteudo, profundidade + 1)
            celulas.append(" ".join(t.strip() for t in conteudo if t.strip()))
        if any(celulas):
            linhas.append(" | ".join(celulas))
    return linhas


def _blocos(el: ET.Element, linhas: list[str], profundidade: int = 0) -> None:
    if profundidade > _MAX_PROFUNDIDADE:
        raise ErroFormato("docx com aninhamento excessivo")
    for filho in el:
        tag = filho.tag
        if tag == W_P:
            linhas.extend(_paragrafo(filho, profundidade + 1))
        elif tag == W_TBL:
            linhas.extend(_tabela(filho, profundidade + 1))
        elif tag in _IGNORADOS:
            continue
        else:
            _blocos(filho, linhas, profundidade + 1)


def _texto_parte(xml: bytes, notas: bool = False) -> str:
    try:
        raiz = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ErroFormato(f"XML inválido no docx: {exc}") from exc
    linhas: list[str] = []
    if notas:
        for nota in raiz:
            if nota.get(W + "type") in _TIPOS_NOTA_IGNORADOS:
                continue
            _blocos(nota, linhas)
    else:
        _blocos(raiz, linhas)
    return "\n".join(linhas)


def _parte_principal(zf: zipfile.ZipFile, nomes: dict[str, zipfile.ZipInfo],
                     orcamento: list[int]) -> str:
    rels = nomes.get("_rels/.rels")
    if rels is not None:
        try:
            raiz = ET.fromstring(ler_membro_zip(zf, rels, orcamento))
        except ET.ParseError:
            raiz = None
        if raiz is not None:
            for rel in raiz.iter(REL + "Relationship"):
                if rel.get("Type", "").endswith("/officeDocument"):
                    alvo = rel.get("Target", "").lstrip("/")
                    if alvo in nomes:
                        return alvo
    return "word/document.xml"


def _ordem_cabecalho(nome: str) -> tuple:
    m = _RE_CABECALHO.match(nome)
    assert m is not None
    return (m.group(1) != "header", int(m.group(2) or 0), nome)


def extrair_docx(dados: bytes, orcamento: list[int] | None = None) -> tuple[str, int]:
    """Texto do docx e quantas partes de cabeçalho/rodapé com texto ficaram de fora.

    O texto tem o corpo e as notas de rodapé e de fim; cabeçalhos e rodapés não entram
    (são repetição de papel timbrado). ErroFormato se não há documento principal ou o
    XML é inválido.
    """
    if orcamento is None:
        orcamento = [base.LIMITE_DESCOMPACTADO]
    try:
        zf = zipfile.ZipFile(io.BytesIO(dados))
    except (zipfile.BadZipFile, OSError, ValueError, EOFError) as exc:
        raise ErroFormato(f"zip inválido: {exc}") from exc
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if sum(i.file_size for i in infos) > orcamento[0]:
            raise ErroLimite("limite de bytes descompactados excedido")
        nomes = {i.filename: i for i in infos}
        principal = _parte_principal(zf, nomes, orcamento)
        if principal not in nomes:
            raise ErroFormato("docx sem document.xml")
        secoes = [_texto_parte(ler_membro_zip(zf, nomes[principal], orcamento))]
        cabecalhos = 0
        for nome in sorted((n for n in nomes if _RE_CABECALHO.match(n)), key=_ordem_cabecalho):
            if _texto_parte(ler_membro_zip(zf, nomes[nome], orcamento)).strip():
                cabecalhos += 1
        for nome in ("word/footnotes.xml", "word/endnotes.xml"):
            if nome in nomes:
                secoes.append(_texto_parte(ler_membro_zip(zf, nomes[nome], orcamento), notas=True))
    return "\n\n".join(s for s in secoes if s.strip()), cabecalhos
