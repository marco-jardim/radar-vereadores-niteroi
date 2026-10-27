"""Texto de documentos Word 97–2003 (.doc, [MS-DOC]) pelo FIB e pela piece table.

O texto não é procurado no binário: o FIB do stream `WordDocument` indica o
stream de tabela (`0Table`/`1Table`, bit fWhichTblStm) e a posição do Clx
(fcClx/lcbClx). O Clx traz a piece table (Pcdt → PlcPcd): cada peça cobre um
intervalo de CPs e aponta, pelo FcCompressed, para bytes do `WordDocument`:
- bit 30 ligado: peça compactada, 1 byte por caractere em cp1252, a partir de fc/2;
- bit 30 desligado: peça Unicode, UTF-16LE a partir de fc.
Piece table que cobre mais caracteres ou bytes do que o `WordDocument` tem é
recusada (ErroFormato), em vez de repetir o mesmo trecho indefinidamente.

São lidos o texto principal, as notas de rodapé, as notas de fim e as caixas de
texto. Cabeçalhos/rodapés (e suas caixas de texto) e comentários ficam de fora;
`cabecalhos` informa quantas histórias de cabeçalho foram omitidas.

Caracteres especiais: \\r, \\x0b, \\x0c e \\x0e viram quebra; campos (\\x13 código
\\x14 resultado \\x15) mantêm só o resultado (campo sem fim mantém o texto seguinte,
com aviso); os demais controles somem. Tabelas: \\x07 marca o fim de cada célula
(vira " | ") e o fim da linha é a marca \\x07 do parágrafo TTP (sprmPFTtp nas PAPX
das FKPs indicadas pela PlcBtePapx), que vira quebra de linha. Sem PAPX legível,
toda marca \\x07 vira " | ".

Word 6/95 sem edição rápida (não complexo) é lido pelo intervalo fcMin–fcMac.

Somente biblioteca padrão do Python.
"""
from __future__ import annotations

import bisect
import re
import struct

from .base import ErroFormato
from .cfb import CompoundFile

IDENT_WORD = 0xA5EC
NFIB_WORD97 = 0x00C1
_INDICE_PAPX = 13  # par fcPlcfBtePapx/lcbPlcfBtePapx em FibRgFcLcb97
_INDICE_CLX = 33  # par fcClx/lcbClx em FibRgFcLcb97
_MAX_PECAS = 1_000_000
_SPRMS_TTP = (0x2417, 0x244C)  # sprmPFTtp e sprmPFInnerTTP
_MARCA_LINHA = "\x1d"  # marca interna: \x07 que encerra uma linha de tabela

# Controles do Word: quebras viram \n, hífen não separável vira "-", os demais somem.
# \x07 (célula) e a marca interna de linha são tratados depois; \t e \n ficam.
_TABELA_CONTROLES: dict[int, str | None] = {
    i: None for i in range(32) if chr(i) not in "\t\n\x07" + _MARCA_LINHA
}
_TABELA_CONTROLES.update({ord("\r"): "\n", 0x0B: "\n", 0x0C: "\n", 0x0E: "\n", 0x1E: "-"})
_RE_CAMPO = re.compile("[\x13\x14\x15]")


def _cp1252(bruto: bytes) -> str:
    return bruto.decode("cp1252", "replace")


def _campos(texto: str) -> tuple[str, bool]:
    """Mantém só o resultado dos campos (\\x13 código \\x14 resultado \\x15), aninhados ou não.

    Devolve também se havia campo sem fim; nesse caso o texto depois do \\x13 aberto
    é mantido (sem as marcas de campo), para não perder o resto do documento.
    """
    if "\x13" not in texto:
        return texto.replace("\x14", "").replace("\x15", ""), False
    saida: list[str] = []
    pilha: list[bool] = []  # True = no código do campo; False = no resultado
    codigos = 0
    pos = 0
    aberto = 0
    for m in _RE_CAMPO.finditer(texto):
        i = m.start()
        if not codigos:
            saida.append(texto[pos:i])
        c = texto[i]
        if c == "\x13":
            if not codigos:
                aberto = i
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
        return "".join(saida), False
    saida.append(_RE_CAMPO.sub("", texto[aberto + 1:]))
    return "".join(saida), True


def _limpar(texto: str) -> tuple[str, bool]:
    """Aplica campos, controles e marcas de tabela; devolve o texto e se havia campo sem fim."""
    texto, aberto = _campos(texto)
    texto = texto.translate(_TABELA_CONTROLES)
    texto = (texto.replace("\x07" + _MARCA_LINHA, "\n").replace(_MARCA_LINHA, "\n")
             .replace("\x07", " | "))
    return texto, aberto


# ---------------------------------------------------------------- PAPX (linhas de tabela)
def _papx_ttp(pagina: bytes, deslocamento: int) -> bool:
    """Se a PapxInFkp em `deslocamento` marca o parágrafo como fim de linha de tabela."""
    if deslocamento >= 511:
        return False
    cb = pagina[deslocamento]
    if cb:
        grupo = pagina[deslocamento + 1:deslocamento + 2 * cb]
    else:
        grupo = pagina[deslocamento + 2:deslocamento + 2 + 2 * pagina[deslocamento + 1]]
    j = 2  # pula o istd
    while j + 2 <= len(grupo):
        op = struct.unpack_from("<H", grupo, j)[0]
        j += 2
        spra = op >> 13
        if op in _SPRMS_TTP:
            return j < len(grupo) and grupo[j] != 0
        if spra in (0, 1):
            tamanho = 1
        elif spra in (2, 4, 5):
            tamanho = 2
        elif spra == 3:
            tamanho = 4
        elif spra == 7:
            tamanho = 3
        elif op == 0xD608:  # sprmTDefTable: cb de 2 bytes (resto + 1)
            if j + 2 > len(grupo):
                return False
            tamanho = struct.unpack_from("<H", grupo, j)[0] + 1
        else:
            if j >= len(grupo) or grupo[j] == 255:
                return False
            tamanho = grupo[j] + 1
        j += tamanho
    return False


def _fcs_fim_de_linha(palavra: bytes, tabela: bytes, fc: int, lcb: int) -> list[int]:
    """FCs (no WordDocument) logo depois das marcas de fim de linha de tabela."""
    if lcb < 12 or (lcb - 4) % 8 or fc + lcb > len(tabela):
        return []
    n = (lcb - 4) // 8
    fins: list[int] = []
    vistas: set[int] = set()
    for pn_bruto in struct.unpack_from(f"<{n}I", tabela, fc + (n + 1) * 4):
        pn = pn_bruto & 0x3FFFFF
        if pn in vistas:
            continue
        vistas.add(pn)
        pagina = palavra[pn * 512:pn * 512 + 512]
        if len(pagina) < 512:
            continue
        cpara = pagina[511]
        if not cpara or (cpara + 1) * 4 + cpara * 13 > 511:
            continue
        rgfc = struct.unpack_from(f"<{cpara + 1}I", pagina, 0)
        base_bx = (cpara + 1) * 4
        for i in range(cpara):
            bx = pagina[base_bx + i * 13]
            if bx and _papx_ttp(pagina, bx * 2):
                fins.append(rgfc[i + 1])
    return fins


# ---------------------------------------------------------------- piece table
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
        if self.cps[-1] - self.cps[0] > len(palavra):
            raise ErroFormato("piece table com mais caracteres que o WordDocument")
        self.pecas: list[tuple[int, bool]] = []
        base = (n + 1) * 4
        total_bytes = 0
        for i in range(n):
            fc_bruto = struct.unpack_from("<I", plc, base + i * 8 + 2)[0]
            compactada = bool(fc_bruto & 0x40000000)
            fc = fc_bruto & 0x3FFFFFFF
            self.pecas.append((fc // 2 if compactada else fc, compactada))
            total_bytes += (self.cps[i + 1] - self.cps[i]) * (1 if compactada else 2)
        if total_bytes > len(palavra):
            raise ErroFormato("peças somam mais bytes que o WordDocument (peças repetidas)")
        self.palavra = palavra

    def cps_das_marcas(self, fins: list[int]) -> list[int]:
        """CPs das marcas de parágrafo que terminam nos FCs dados."""
        intervalos = sorted(
            (fc, fc + (self.cps[i + 1] - self.cps[i]) * (1 if comp else 2), self.cps[i], 1 if comp else 2)
            for i, (fc, comp) in enumerate(self.pecas)
        )
        inicios = [x[0] for x in intervalos]
        marcas: set[int] = set()
        for fim in fins:
            k = bisect.bisect_right(inicios, fim - 1) - 1
            if k < 0:
                continue
            fc, fc_fim, cp, largura = intervalos[k]
            if fc < fim <= fc_fim and (fim - fc) % largura == 0:
                marcas.add(cp + (fim - fc) // largura - 1)
        return sorted(marcas)

    def texto(self, cp_ini: int, cp_fim: int, marcas: list[int] | None = None) -> str:
        """Texto dos CPs [cp_ini, cp_fim); \\x07 nos CPs de `marcas` vira a marca de linha."""
        marcas = marcas or []
        partes: list[str] = []
        for i, (fc, compactada) in enumerate(self.pecas):
            a, b = self.cps[i], self.cps[i + 1]
            ini, fim = max(a, cp_ini), min(b, cp_fim)
            if ini >= fim:
                continue
            largura = 1 if compactada else 2
            if fc + (fim - a) * largura > len(self.palavra):
                raise ErroFormato("peça aponta para fora do WordDocument")

            def decodificar(x: int, y: int) -> str:
                bruto = self.palavra[fc + (x - a) * largura:fc + (y - a) * largura]
                return _cp1252(bruto) if compactada else bruto.decode("utf-16-le", "replace")

            pos = ini
            k = bisect.bisect_left(marcas, ini)
            while k < len(marcas) and marcas[k] < fim:
                m = marcas[k]
                partes.append(decodificar(pos, m))
                c = decodificar(m, m + 1)
                partes.append(_MARCA_LINHA if c == "\x07" else c)
                pos = m + 1
                k += 1
            partes.append(decodificar(pos, fim))
        return "".join(partes)


def _word95(palavra: bytes, flags: int) -> tuple[str, list[str], int]:
    if flags & 0x0004:
        raise ErroFormato("Word 6/95 com edição rápida não suportado")
    if len(palavra) < 0x50:
        raise ErroFormato("FIB do Word 6/95 truncado")
    fc_min, fc_mac = struct.unpack_from("<II", palavra, 0x18)
    if not 0 < fc_min <= fc_mac <= len(palavra):
        raise ErroFormato("intervalo de texto inválido no Word 6/95")
    texto, aberto = _limpar(_cp1252(palavra[fc_min:fc_mac]))
    return texto, ["campo do Word sem fim"] if aberto else [], 0


def extrair_doc(dados: bytes) -> tuple[str, list[str], int]:
    """Texto do .doc, avisos e histórias de cabeçalho omitidas.

    ErroFormato (ou ErroCFB) se malformado, criptografado ou sem documento Word.
    """
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
    if nfib < NFIB_WORD97 and nfib != 0x00C0:
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
    fc_papx, lcb_papx = struct.unpack_from("<II", palavra, pos + _INDICE_PAPX * 8)

    nome_tabela = "1Table" if flags & 0x0200 else "0Table"
    if nome_tabela not in filhos:
        raise ErroFormato(f"stream {nome_tabela} ausente")
    tabela = cf.ler(filhos[nome_tabela])
    pecas = _Pecas(palavra, tabela, fc_clx, lcb_clx)
    try:
        marcas = pecas.cps_das_marcas(_fcs_fim_de_linha(palavra, tabela, fc_papx, lcb_papx))
    except (struct.error, IndexError, ValueError):
        marcas = []  # PAPX ilegível: as linhas de tabela não são separadas

    # ccpText, ccpFtn, ccpHdd, ccpMcr, ccpAtn, ccpEdn, ccpTxbx, ccpHdrTxbx
    contagens = [max(0, v) for v in rglw[3:11]]
    total = pecas.cps[-1]
    secoes: list[str] = []
    avisos: list[str] = []
    cabecalhos = 0
    inicio = 0
    for indice, quantidade in enumerate(contagens):
        fim = min(inicio + quantidade, total)
        if fim > inicio and indice not in (3, 4):  # macros e comentários ficam de fora
            texto, aberto = _limpar(pecas.texto(inicio, fim, marcas))
            if aberto and "campo do Word sem fim" not in avisos:
                avisos.append("campo do Word sem fim")
            if indice in (2, 7):  # cabeçalhos/rodapés e suas caixas de texto
                cabecalhos += bool(texto.strip())
            else:
                secoes.append(texto)
        inicio = fim
    return "\n\n".join(s for s in secoes if s.strip()), avisos, cabecalhos
