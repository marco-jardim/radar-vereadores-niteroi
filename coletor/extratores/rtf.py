"""Texto de arquivos RTF.

Tokeniza o RTF por expressão regular, sem decodificar dados binários: grupos
`{\\*\\...}` e destinos sem texto (tabelas de fontes, cores, estilos, imagens,
objetos, metadados, códigos de campo) são ignorados; `\\binN` pula N bytes.
`\\'hh` é decodificado na página de código do documento (`\\ansicpgN`, padrão
cp1252) e `\\uN` vira o caractere Unicode, pulando os `\\ucN` caracteres
alternativos. `\\par`, `\\line`, `\\sect`, `\\page` e `\\row` viram quebra de linha,
`\\cell` vira " | " e `\\tab` vira tabulação.

Somente biblioteca padrão do Python.
"""
from __future__ import annotations

import codecs
import re

from .base import ErroFormato

_TOKEN = re.compile(
    rb"\\([a-zA-Z]{1,32})(-?\d{1,10})? ?"  # palavra de controle
    rb"|\\'([0-9a-fA-F]{2})"              # byte em hexadecimal
    rb"|\\(.)"                            # símbolo de controle
    rb"|([{}])"                           # grupo
    rb"|([^\\{}\r\n]+)"                   # texto
    rb"|[\r\n]+",                         # quebras do arquivo, sem significado
    re.S,
)

_DESTINOS_IGNORADOS = {
    "fonttbl", "colortbl", "stylesheet", "info", "pict", "object", "objdata", "objclass",
    "themedata", "colorschememapping", "datastore", "latentstyles", "listtable",
    "listoverridetable", "rsidtbl", "generator", "xmlnstbl", "mmathpr", "fldinst",
    "filetbl", "revtbl", "pgdsctbl", "docvar", "wgrffmtfilter", "blipuid", "nonshppict",
    "ftnsep", "ftnsepc", "aftnsep", "aftnsepc", "bkmkstart", "bkmkend", "xe", "tc",
    "template", "userprops", "operator", "passwordhash", "protusertbl", "listpicture",
    "falt", "panose", "fname", "printim", "buptim", "creatim",
    "revtim", "author", "title", "subject", "keywords", "comment", "doccomm", "company",
    "category", "manager", "hlinkbase", "atnid", "atnauthor", "annotation", "atrfstart",
    "atrfend", "atnref", "atndate", "shpinst", "sp", "sn", "sv", "background", "macpict",
    "wmetafile", "dibitmap", "wbitmap", "jpegblip", "pngblip", "emfblip",
}
_QUEBRAS = {"par", "line", "sect", "page", "row"}
_SIMBOLOS = {
    "tab": "\t", "cell": " | ", "nestcell": " | ", "emdash": "\u2014", "endash": "\u2013",
    "bullet": "\u2022", "lquote": "\u2018", "rquote": "\u2019", "ldblquote": "\u201c",
    "rdblquote": "\u201d", "emspace": " ", "enspace": " ", "qmspace": " ",
}


class _Estado:
    __slots__ = ("ignorar", "uc", "destino_novo")

    def __init__(self, ignorar: bool = False, uc: int = 1) -> None:
        self.ignorar = ignorar
        self.uc = uc
        self.destino_novo = True  # primeira palavra do grupo ainda não lida


def _codec(numero: int) -> str:
    nome = f"cp{numero}"
    try:
        codecs.lookup(nome)
    except LookupError:
        return "cp1252"
    return nome


def extrair_rtf(dados: bytes) -> str:
    """Texto do RTF; ErroFormato se não começa por {\\rtf.

    Grupos não fechados no fim do arquivo são tolerados. Pares de surrogates em
    \\uN (emoji e outros caracteres fora do plano básico) são combinados.
    """
    inicio = dados.find(b"{\\rtf")
    if inicio < 0 or inicio > 64:
        raise ErroFormato("RTF sem cabeçalho {\\rtf")
    saida: list[str] = []
    pendentes = bytearray()  # bytes \'hh consecutivos (páginas de código multibyte)
    codificacao = "cp1252"
    pilha: list[_Estado] = []
    estado = _Estado()
    pular = 0  # caracteres alternativos ainda a pular depois de \uN
    pos = inicio
    n = len(dados)

    def descarregar() -> None:
        if pendentes:
            if not estado.ignorar:
                saida.append(bytes(pendentes).decode(codificacao, "replace"))
            pendentes.clear()

    while pos < n:
        m = _TOKEN.match(dados, pos)
        if m is None:  # barra invertida no fim do arquivo
            break
        pos = m.end()
        palavra, parametro, hexa, simbolo, grupo, texto = m.groups()
        if hexa is not None:
            if pular:
                pular -= 1
                continue
            pendentes.append(int(hexa, 16))
            estado.destino_novo = False
            continue
        descarregar()
        if grupo is not None:
            pular = 0
            if grupo == b"{":
                if len(pilha) > 1000:
                    raise ErroFormato("RTF com aninhamento excessivo")
                pilha.append(estado)
                estado = _Estado(estado.ignorar, estado.uc)
            else:
                if not pilha:
                    break  # fim do documento
                estado = pilha.pop()
            continue
        if palavra is not None:
            nome = palavra.decode("ascii")
            valor = int(parametro) if parametro is not None else None
            primeira = estado.destino_novo
            estado.destino_novo = False
            pular = 0
            if nome == "bin":
                pos += max(0, valor or 0)
                continue
            if nome == "ansicpg" and valor:
                codificacao = _codec(valor)
                continue
            if nome == "uc":
                estado.uc = max(0, valor or 0)
                continue
            if nome in _DESTINOS_IGNORADOS and primeira:
                estado.ignorar = True
                continue
            if estado.ignorar:
                continue
            if nome == "u" and valor is not None:
                codigo = valor + 65536 if valor < 0 else valor
                saida.append(chr(codigo) if 0 < codigo < 0x110000 else "\ufffd")
                pular = estado.uc
                continue
            if nome in _QUEBRAS:
                if nome == "row" and saida and saida[-1] == " | ":
                    saida[-1] = "\n"
                else:
                    saida.append("\n")
            elif nome in _SIMBOLOS:
                saida.append(_SIMBOLOS[nome])
            continue
        if simbolo is not None:
            primeira = estado.destino_novo
            estado.destino_novo = False
            if simbolo == b"*":
                if primeira:
                    estado.ignorar = True
                continue
            if pular:
                pular -= 1
                continue
            if estado.ignorar:
                continue
            if simbolo in (b"\\", b"{", b"}"):
                saida.append(simbolo.decode("ascii"))
            elif simbolo == b"~":
                saida.append("\u00a0")
            elif simbolo == b"_":
                saida.append("-")
            elif simbolo in (b"\n", b"\r"):
                saida.append("\n")
            continue
        if texto is not None:
            estado.destino_novo = False
            if pular:
                corte = min(pular, len(texto))
                texto = texto[corte:]
                pular -= corte
            if texto and not estado.ignorar:
                saida.append(texto.decode(codificacao, "replace"))
            continue
        # quebras de linha do próprio arquivo: sem efeito
    descarregar()
    # \uN com pares de surrogates (D800–DBFF seguido de DC00–DFFF) vira um caractere só;
    # surrogates soltos continuam e são removidos na normalização.
    return "".join(saida).encode("utf-16-le", "surrogatepass").decode("utf-16-le", "surrogatepass")
