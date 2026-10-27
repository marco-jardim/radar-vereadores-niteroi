"""Texto de documentos Word 97–2003 (.doc, [MS-DOC]) pelo FIB e pela piece table.

O texto não é procurado no binário: o FIB do stream `WordDocument` indica o
stream de tabela (`0Table`/`1Table`, bit fWhichTblStm) e a posição do Clx
(fcClx/lcbClx). O Clx traz a piece table (Pcdt → PlcPcd): cada peça cobre um
intervalo de CPs e aponta, pelo FcCompressed, para bytes do `WordDocument`:
- bit 30 ligado: peça compactada, 1 byte por caractere em cp1252, a partir de fc/2;
- bit 30 desligado: peça Unicode, UTF-16LE a partir de fc.

São lidos o texto principal, as notas de rodapé, os cabeçalhos/rodapés, as notas
de fim e as caixas de texto; comentários (anotações) ficam de fora. Caracteres
especiais: \\r, \\x0b, \\x0c e \\x0e viram quebra; \\x07 (fim de célula) vira " | "
e, repetido, fim de linha da tabela; campos (\\x13 código \\x14 resultado \\x15)
mantêm só o resultado; os demais controles somem.

Word 6/95 sem edição rápida (não complexo) é lido pelo intervalo fcMin–fcMac.

Somente biblioteca padrão do Python.
"""
from __future__ import annotations

import re
import struct

from .base import ErroFormato
from .cfb import CompoundFile

IDENT_WORD = 0xA5EC
NFIB_WORD97 = 0x00C1
_INDICE_CLX = 33  # par fcClx/lcbClx em FibRgFcLcb97
_MAX_PECAS = 1_000_000

# Controles do Word: quebras viram \n, hífen não separável vira "-", os demais somem.
# \x07 (fim de célula) é tratado depois, em _celulas; \t e \n ficam.
_TABELA_CONTROLES: dict[int, str | None] = {
    i: None for i in range(32) if chr(i) not in "\t\n\x07"
}
_TABELA_CONTROLES.update({ord("\r"): "\n", 0x0B: "\n", 0x0C: "\n", 0x0E: "\n", 0x1E: "-"})
_RE_CAMPO = re.compile("[\x13\x14\x15]")


def _cp1252(bruto: bytes) -> str:
    return bruto.decode("cp1252", "replace")


def _campos(texto: str) -> str:
    """Mantém só o resultado dos campos (\\x13 código \\x14 resultado \\x15), aninhados ou não."""
    if "\x13" not in texto:
        return texto.replace("\x14", "").replace("\x15", "")
    saida: list[str] = []
    pilha: list[bool] = []  # True = no código do campo; False = no resultado
    codigos = 0
    pos = 0
    for m in _RE_CAMPO.finditer(texto):
        i = m.start()
        if not codigos:
            saida.append(texto[pos:i])
        c = texto[i]
        if c == "\x13":
            pilha.append(True)
            codigos += 1
        elif c == "\x14":
            if pilha and pilha[-1]:
                pilha[-1] = False
                codigos -= 1
        elif pilha and pilha.pop():
            codigos -= 1
        pos = i + 1
    if not codigos:
        saida.append(texto[pos:])
    return "".join(saida)


def _limpar(texto: str) -> str:
    """Aplica campos, controles e marcas de célula do Word ao texto das peças.

    \\x07 marca o fim de uma célula; dois seguidos marcam o fim da linha da tabela.
    """
    texto = _campos(texto).translate(_TABELA_CONTROLES)
    return texto.replace("\x07\x07", "\n").replace("\x07", " | ")


class _Pecas:
    def __init__(self, palavra: bytes, tabela: bytes, fc_clx: int, lcb_clx: int) -> None:
        if lcb_clx == 0 or fc_clx + lcb_clx > len(tabela):
            raise ErroFormato("Clx fora do stream de tabela")
        clx = tabela[fc_clx:fc_clx + lcb_clx]
        pos = 0
        while pos < len(clx) and clx[pos] == 0x01:  # RgPrc
            if pos + 3 > len(clx):
                raise ErroFormato("Prc truncado")
            cb = struct.unpack_from("<h", clx, pos + 1)[0]
            if cb < 0:
                raise ErroFormato("Prc com tamanho negativo")
            pos += 3 + cb
        if pos + 5 > len(clx) or clx[pos] != 0x02:
            raise ErroFormato("Pcdt ausente no Clx")
        lcb = struct.unpack_from("<I", clx, pos + 1)[0]
        plc = clx[pos + 5:pos + 5 + lcb]
        if len(plc) < lcb or lcb < 16 or (lcb - 4) % 12:
            raise ErroFormato("PlcPcd com tamanho inválido")
        n = (lcb - 4) // 12
        if n > _MAX_PECAS:
            raise ErroFormato("piece table grande demais")
        self.cps = struct.unpack_from(f"<{n + 1}I", plc, 0)
        if any(b < a for a, b in zip(self.cps, self.cps[1:])):
            raise ErroFormato("CPs fora de ordem na piece table")
        self.pecas: list[tuple[int, bool]] = []
        base = (n + 1) * 4
        for i in range(n):
            fc_bruto = struct.unpack_from("<I", plc, base + i * 8 + 2)[0]
            compactada = bool(fc_bruto & 0x40000000)
            fc = fc_bruto & 0x3FFFFFFF
            self.pecas.append((fc // 2 if compactada else fc, compactada))
        self.palavra = palavra

    def texto(self, cp_ini: int, cp_fim: int) -> str:
        partes: list[str] = []
        for i, (fc, compactada) in enumerate(self.pecas):
            a, b = self.cps[i], self.cps[i + 1]
            ini, fim = max(a, cp_ini), min(b, cp_fim)
            if ini >= fim:
                continue
            largura = 1 if compactada else 2
            inicio = fc + (ini - a) * largura
            final = inicio + (fim - ini) * largura
            if final > len(self.palavra):
                raise ErroFormato("peça aponta para fora do WordDocument")
            bruto = self.palavra[inicio:final]
            partes.append(_cp1252(bruto) if compactada else bruto.decode("utf-16-le", "replace"))
        return "".join(partes)


def _word95(palavra: bytes, flags: int) -> str:
    if flags & 0x0004:
        raise ErroFormato("Word 6/95 com edição rápida não suportado")
    if len(palavra) < 0x50:
        raise ErroFormato("FIB do Word 6/95 truncado")
    fc_min, fc_mac = struct.unpack_from("<II", palavra, 0x18)
    if not 0 < fc_min <= fc_mac <= len(palavra):
        raise ErroFormato("intervalo de texto inválido no Word 6/95")
    return _limpar(_cp1252(palavra[fc_min:fc_mac]))


def extrair_doc(dados: bytes) -> str:
    """Texto do .doc; ErroFormato (ou ErroCFB) se malformado, criptografado ou sem Word."""
    cf = CompoundFile(dados)
    filhos = cf.filhos(0)
    if "WordDocument" not in filhos:
        raise ErroFormato("CFB sem stream WordDocument (não é documento Word)")
    palavra = cf.ler(filhos["WordDocument"])
    if len(palavra) < 0x22:
        raise ErroFormato("FIB truncado")
    ident, nfib = struct.unpack_from("<HH", palavra, 0)
    if ident != IDENT_WORD:
        raise ErroFormato("FIB com identificador inválido")
    flags = struct.unpack_from("<H", palavra, 0x0A)[0]
    if flags & 0x0100:
        raise ErroFormato("documento Word criptografado")
    if nfib < NFIB_WORD97 and nfib not in (0x00C0, 0x00C2):
        return _word95(palavra, flags)

    pos = 0x20
    csw = struct.unpack_from("<H", palavra, pos)[0]
    pos += 2 + csw * 2
    if pos + 2 > len(palavra):
        raise ErroFormato("FIB truncado (fibRgW)")
    cslw = struct.unpack_from("<H", palavra, pos)[0]
    pos += 2
    if cslw < 11 or pos + cslw * 4 + 2 > len(palavra):
        raise ErroFormato("FIB truncado (fibRgLw)")
    rglw = struct.unpack_from(f"<{cslw}i", palavra, pos)
    pos += cslw * 4
    cb_fclcb = struct.unpack_from("<H", palavra, pos)[0]
    pos += 2
    if cb_fclcb <= _INDICE_CLX or pos + cb_fclcb * 8 > len(palavra):
        raise ErroFormato("FIB truncado (fibRgFcLcb)")
    fc_clx, lcb_clx = struct.unpack_from("<II", palavra, pos + _INDICE_CLX * 8)

    nome_tabela = "1Table" if flags & 0x0200 else "0Table"
    if nome_tabela not in filhos:
        raise ErroFormato(f"stream {nome_tabela} ausente")
    tabela = cf.ler(filhos[nome_tabela])
    pecas = _Pecas(palavra, tabela, fc_clx, lcb_clx)

    # ccpText, ccpFtn, ccpHdd, ccpMcr, ccpAtn, ccpEdn, ccpTxbx, ccpHdrTxbx
    contagens = [max(0, v) for v in rglw[3:11]]
    total = pecas.cps[-1]
    secoes: list[str] = []
    inicio = 0
    for indice, quantidade in enumerate(contagens):
        fim = min(inicio + quantidade, total)
        if indice not in (3, 4) and fim > inicio:  # pula macros e comentários
            secoes.append(_limpar(pecas.texto(inicio, fim)))
        inicio = fim
    return "\n\n".join(s for s in secoes if s.strip())
