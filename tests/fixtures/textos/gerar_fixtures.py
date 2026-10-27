"""Gerador determinístico das fixtures sintéticas dos extratores de texto.

Todas as fixtures são sintéticas: texto inventado, sem dados pessoais. Os testes
importam este módulo e geram os bytes em memória; `python
tests/fixtures/textos/gerar_fixtures.py` grava as mesmas fixtures nesta pasta,
para inspeção manual (mesma entrada, mesmos bytes). A origem de cada uma está em
FONTES.md.

Somente biblioteca padrão do Python.
"""
from __future__ import annotations

import io
import math
import struct
import sys
import zipfile
import zlib
from pathlib import Path

PASTA = Path(__file__).resolve().parent

# ---------------------------------------------------------------- textos sintéticos
PARAGRAFO = (
    "A Câmara Municipal de Niterói aprovou em primeira discussão o projeto que institui "
    "o programa municipal de hortas comunitárias nas escolas da rede pública, com ações "
    "de educação ambiental, compostagem e alimentação saudável para os estudantes."
)
TEXTO_ESCANEADO = ["CAMARA MUNICIPAL", "DE NITEROI", "DOCUMENTO DIGITALIZADO"]

# ---------------------------------------------------------------- zip / docx
DATA_ZIP = (2026, 1, 1, 0, 0, 0)


def zip_bytes(membros: dict[str, bytes], comprimir: bool = True) -> bytes:
    """Zip determinístico: data fixa, sistema de origem fixo e ordem dos membros dada."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for nome, dados in membros.items():
            info = zipfile.ZipInfo(nome, date_time=DATA_ZIP)
            info.compress_type = zipfile.ZIP_DEFLATED if comprimir else zipfile.ZIP_STORED
            info.create_system = 0
            info.external_attr = 0
            zf.writestr(info, dados)
    return buf.getvalue()


NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS_DECL = (
    f'xmlns:w="{NS_W}" '
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
    'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
    'xmlns:v="urn:schemas-microsoft-com:vml"'
)
_CT = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)
_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="word/document.xml"/></Relationships>'
)


def _xml(texto: str) -> str:
    return texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _p(texto: str) -> str:
    """Parágrafo WordprocessingML; \\t vira w:tab e \\n vira w:br."""
    runs = []
    for i, linha in enumerate(texto.split("\n")):
        if i:
            runs.append("<w:r><w:br/></w:r>")
        for j, parte in enumerate(linha.split("\t")):
            if j:
                runs.append("<w:r><w:tab/></w:r>")
            if parte:
                runs.append(f'<w:r><w:t xml:space="preserve">{_xml(parte)}</w:t></w:r>')
    return "<w:p>" + "".join(runs) + "</w:p>"


def _tabela(linhas: list[list[str]]) -> str:
    corpo = "".join(
        "<w:tr>" + "".join(f"<w:tc>{_p(c)}</w:tc>" for c in linha) + "</w:tr>" for linha in linhas
    )
    return f"<w:tbl><w:tblPr/>{corpo}</w:tbl>"


def _documento(corpo: str) -> bytes:
    return (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {NS_DECL}>'
        f"<w:body>{corpo}<w:sectPr/></w:body></w:document>"
    ).encode("utf-8")


def docx_simples() -> bytes:
    corpo = _p("Projeto de Lei nº 1/2026") + _p(PARAGRAFO) + _p("Art. 1º\tEsta lei entra em vigor.\nNa data.")
    return zip_bytes({
        "[Content_Types].xml": _CT.encode(),
        "_rels/.rels": _RELS.encode(),
        "word/document.xml": _documento(corpo),
    })


def docx_completo() -> bytes:
    caixa = (
        "<w:p><w:r><mc:AlternateContent><mc:Choice Requires=\"wps\"><w:drawing><wps:txbx>"
        "<w:txbxContent>" + _p("Caixa de texto sintética") + "</w:txbxContent>"
        "</wps:txbx></w:drawing></mc:Choice><mc:Fallback><w:pict><v:textbox><w:txbxContent>"
        + _p("Caixa de texto sintética") + "</w:txbxContent></v:textbox></w:pict></mc:Fallback>"
        "</mc:AlternateContent></w:r></w:p>"
    )
    revisao = (
        "<w:p><w:r><w:t>Texto mantido</w:t></w:r><w:del><w:r><w:delText>TEXTO APAGADO</w:delText>"
        "</w:r></w:del><w:r><w:fldChar w:fldCharType=\"begin\"/></w:r><w:r><w:instrText> PAGE "
        "</w:instrText></w:r><w:r><w:fldChar w:fldCharType=\"separate\"/></w:r><w:r><w:t>7</w:t>"
        "</w:r><w:r><w:fldChar w:fldCharType=\"end\"/></w:r></w:p>"
    )
    corpo = (
        _p("Indicação sintética com tabela")
        + _tabela([["Item", "Quantidade"], ["Bancos de praça", "12"], ["Lixeiras", "30"]])
        + revisao + caixa
    )
    cabecalho = (f'<?xml version="1.0" encoding="UTF-8"?><w:hdr {NS_DECL}>'
                 + _p("CABEÇALHO SINTÉTICO DA CÂMARA") + "</w:hdr>").encode()
    rodape = (f'<?xml version="1.0" encoding="UTF-8"?><w:ftr {NS_DECL}>'
              + _p("Rodapé sintético – página") + "</w:ftr>").encode()
    notas = (
        f'<?xml version="1.0" encoding="UTF-8"?><w:footnotes {NS_DECL}>'
        '<w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:t>SEPARADOR</w:t></w:r></w:p></w:footnote>'
        '<w:footnote w:id="1">' + _p("Nota de rodapé sintética.") + "</w:footnote></w:footnotes>"
    ).encode()
    return zip_bytes({
        "[Content_Types].xml": _CT.encode(),
        "_rels/.rels": _RELS.encode(),
        "word/document.xml": _documento(corpo),
        "word/header1.xml": cabecalho,
        "word/header2.xml": cabecalho,  # repetido: deve aparecer uma vez
        "word/footer1.xml": rodape,
        "word/footnotes.xml": notas,
    })


def docx_sem_documento() -> bytes:
    return zip_bytes({
        "[Content_Types].xml": _CT.encode(),
        "_rels/.rels": _RELS.encode(),
        "word/styles.xml": b"<?xml version=\"1.0\"?><styles/>",
    })


# ---------------------------------------------------------------- CFB (OLE)
MAGICO_CFB = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
FREESECT, ENDOFCHAIN, FATSECT, NOSTREAM = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD, 0xFFFFFFFF
SETOR = 512


def _entrada_dir(nome: str, tipo: int, esquerda: int, direita: int, filho: int,
                 inicio: int, tamanho: int) -> bytes:
    reg = bytearray(128)
    if nome:
        nb = nome.encode("utf-16-le") + b"\x00\x00"
        reg[: len(nb)] = nb
        struct.pack_into("<HBB", reg, 0x40, len(nb), tipo, 1)
    struct.pack_into("<III", reg, 0x44, esquerda, direita, filho)
    struct.pack_into("<IQ", reg, 0x74, inicio, tamanho)
    return bytes(reg)


def cfb(streams: dict[str, bytes]) -> bytes:
    """Compound File versão 3 (setores de 512 bytes) com os streams na raiz.

    Streams com menos de 4096 bytes vão para o mini stream (MiniFAT); os demais,
    para setores comuns (FAT). O diretório encadeia as entradas pelo irmão direito.
    """
    nomes = list(streams)
    mini = bytearray()
    cadeias_mini: dict[str, tuple[int, int] | None] = {}
    grandes: dict[str, bytes] = {}
    for nome in nomes:
        dados = streams[nome]
        if len(dados) >= 4096:
            grandes[nome] = dados
        elif dados:
            n = math.ceil(len(dados) / 64)
            cadeias_mini[nome] = (len(mini) // 64, n)
            mini += dados + b"\x00" * (n * 64 - len(dados))
        else:
            cadeias_mini[nome] = None
    n_mini = len(mini) // 64
    n_minifat = math.ceil(n_mini / 128)
    n_ministream = math.ceil(len(mini) / SETOR)
    n_dir = math.ceil((1 + len(nomes)) / 4)
    n_grandes = sum(math.ceil(len(d) / SETOR) for d in grandes.values())
    resto = n_dir + n_minifat + n_ministream + n_grandes
    n_fat = 1
    while math.ceil((resto + n_fat) / 128) > n_fat:
        n_fat += 1
    if n_fat > 109:
        raise ValueError("fixture grande demais para a DIFAT do cabeçalho")

    setor = 0
    fat_setores = list(range(n_fat))
    setor += n_fat
    dir_ini = setor
    setor += n_dir
    minifat_ini = setor if n_minifat else ENDOFCHAIN
    setor += n_minifat
    ministream_ini = setor if n_ministream else ENDOFCHAIN
    setor += n_ministream
    grandes_ini: dict[str, int] = {}
    for nome, dados in grandes.items():
        grandes_ini[nome] = setor
        setor += math.ceil(len(dados) / SETOR)

    fat = [FREESECT] * (n_fat * 128)
    for s in fat_setores:
        fat[s] = FATSECT

    def encadear(tabela: list[int], ini: int, n: int) -> None:
        for i in range(n):
            tabela[ini + i] = ini + i + 1 if i < n - 1 else ENDOFCHAIN

    encadear(fat, dir_ini, n_dir)
    if n_minifat:
        encadear(fat, minifat_ini, n_minifat)
    if n_ministream:
        encadear(fat, ministream_ini, n_ministream)
    for nome, dados in grandes.items():
        encadear(fat, grandes_ini[nome], math.ceil(len(dados) / SETOR))
    minifat = [FREESECT] * (n_minifat * 128)
    for cadeia in cadeias_mini.values():
        if cadeia:
            encadear(minifat, *cadeia)

    entradas = [_entrada_dir("Root Entry", 5, NOSTREAM, NOSTREAM, 1 if nomes else NOSTREAM,
                             ministream_ini, len(mini))]
    for i, nome in enumerate(nomes, 1):
        direita = i + 1 if i < len(nomes) else NOSTREAM
        if nome in grandes:
            inicio = grandes_ini[nome]
        else:
            cadeia = cadeias_mini[nome]
            inicio = cadeia[0] if cadeia else ENDOFCHAIN
        entradas.append(_entrada_dir(nome, 2, NOSTREAM, direita, NOSTREAM, inicio, len(streams[nome])))
    while len(entradas) % 4:
        entradas.append(_entrada_dir("", 0, NOSTREAM, NOSTREAM, NOSTREAM, 0, 0))

    cab = bytearray(SETOR)
    cab[0:8] = MAGICO_CFB
    struct.pack_into("<HHHHH", cab, 0x18, 0x003E, 3, 0xFFFE, 9, 6)
    struct.pack_into("<IIIIIIIII", cab, 0x28, 0, n_fat, dir_ini, 0, 4096, minifat_ini, n_minifat,
                     ENDOFCHAIN, 0)
    struct.pack_into("<109I", cab, 0x4C, *(fat_setores + [FREESECT] * (109 - n_fat)))

    def preencher(dados: bytes) -> bytes:
        return dados + b"\x00" * (-len(dados) % SETOR)

    corpo = bytearray(cab)
    corpo += struct.pack(f"<{len(fat)}I", *fat)
    corpo += b"".join(entradas)
    if n_minifat:
        corpo += struct.pack(f"<{len(minifat)}I", *minifat)
    corpo += preencher(bytes(mini))
    for dados in grandes.values():
        corpo += preencher(dados)
    return bytes(corpo)


def cfb_com_ciclo(dados: bytes) -> bytes:
    """Mesmo CFB com a cadeia do diretório apontando para si mesma (ciclo na FAT)."""
    d = bytearray(dados)
    fat0 = struct.unpack_from("<I", d, 0x4C)[0]
    dir_ini = struct.unpack_from("<I", d, 0x30)[0]
    struct.pack_into("<I", d, (fat0 + 1) * SETOR + dir_ini * 4, dir_ini)
    return bytes(d)


# ---------------------------------------------------------------- Word 97 (.doc)
INICIO_TEXTO = 1024


def _fkp_papx(limites: list[int], fins_ttp: set[int]) -> bytes:
    """Página FKP de PAPX: parágrafos entre `limites`; os que terminam em `fins_ttp`
    recebem sprmPFInTable e sprmPFTtp (fim de linha de tabela)."""
    cpara = len(limites) - 1
    if not 0 < cpara <= 27:
        raise ValueError("fixture com parágrafos demais para uma FKP")
    pagina = bytearray(512)
    struct.pack_into(f"<{cpara + 1}I", pagina, 0, *limites)
    # PapxInFkp em 480 (bOffset 240): cb = 0, cb' = 4 → 8 bytes: istd + 2 sprms
    pagina[480:490] = (b"\x00\x04" + b"\x00\x00" + struct.pack("<HB", 0x2416, 1)
                       + struct.pack("<HB", 0x2417, 1))
    for i in range(cpara):
        if limites[i + 1] in fins_ttp:
            pagina[(cpara + 1) * 4 + i * 13] = 240
    pagina[511] = cpara
    return bytes(pagina)


def doc_word97(pecas: list[tuple[str, bool]], *, tabela: str = "1Table", minifat: bool = False,
               criptografado: bool = False, extras: dict[str, bytes] | None = None,
               ttp: list[int] | None = None, repetir: int = 1, cabecalho: str = "") -> bytes:
    """Documento Word 97 mínimo: FIB, piece table (com um Prc antes do Pcdt) e as peças.

    `pecas` é a lista de (texto, compactada): compactada em cp1252 (bit 30 do fc) ou
    Unicode em UTF-16LE. Sem `minifat`, os streams são completados até 4096 bytes e
    ficam na FAT; com `minifat`, ficam pequenos e vão para o mini stream.

    `ttp` lista os CPs das marcas \\x07 que encerram linhas de tabela; sem ele, a
    segunda marca de cada "\\x07\\x07" é a de fim de linha. As marcas viram uma FKP de
    PAPX com sprmPFTtp, apontada pela PlcBtePapx. `repetir` repete a lista de peças
    (todas apontando para os mesmos bytes), para testar piece tables malformadas.
    `cabecalho` vira uma história de cabeçalho (ccpHdd) depois do texto principal.
    """
    texto = bytearray()
    cps = [0]
    pcds = []
    posicoes = []  # (cp inicial, cp final, byte inicial, largura) de cada peça
    todas = list(pecas) + ([(cabecalho, True)] if cabecalho else [])
    for conteudo, compactada in todas:
        deslocamento = INICIO_TEXTO + len(texto)
        if compactada:
            bruto = conteudo.encode("cp1252")
            fc = (deslocamento * 2) | 0x40000000
        else:
            if deslocamento % 2:
                texto += b"\x00"
                deslocamento += 1
            bruto = conteudo.encode("utf-16-le")
            fc = deslocamento
        texto += bruto
        posicoes.append((cps[-1], cps[-1] + len(conteudo), deslocamento, 1 if compactada else 2))
        cps.append(cps[-1] + len(conteudo))
        pcds.append(struct.pack("<HIH", 0, fc, 0))
    if repetir > 1:
        tamanhos = [b - a for a, b in zip(cps, cps[1:])]
        for _ in range(repetir - 1):
            for tamanho in tamanhos:
                cps.append(cps[-1] + tamanho)
        pcds = pcds * repetir
    plc = struct.pack(f"<{len(cps)}I", *cps) + b"".join(pcds)
    clx = b"\x01" + struct.pack("<h", 2) + b"\x00\x00" + b"\x02" + struct.pack("<I", len(plc)) + plc
    prefixo = b"\x00" * 16
    stream_tabela = prefixo + clx

    principal = "".join(c for c, _ in pecas)
    if ttp is None:
        ttp = [i + 1 for i in range(len(principal) - 1)
               if principal[i] == "\x07" and principal[i + 1] == "\x07"
               and (i == 0 or principal[i - 1] != "\x07")]
    fins_ttp = set()
    for cp in ttp:
        for cp_a, cp_b, inicio, largura in posicoes:
            if cp_a <= cp < cp_b:
                fins_ttp.add(inicio + (cp - cp_a + 1) * largura)

    fib = bytearray(INICIO_TEXTO)
    flags = 0x0004 | (0x0200 if tabela == "1Table" else 0) | (0x0100 if criptografado else 0)
    struct.pack_into("<HHHHHH", fib, 0, 0xA5EC, 0x00C1, 0, 0x0416, 0, flags)
    struct.pack_into("<H", fib, 0x0C, 0x00BF)
    struct.pack_into("<H", fib, 0x20, 14)       # csw
    struct.pack_into("<H", fib, 0x3E, 22)       # cslw
    struct.pack_into("<i", fib, 0x40 + 3 * 4, cps[-1] - len(cabecalho) * repetir)  # ccpText
    struct.pack_into("<i", fib, 0x40 + 5 * 4, len(cabecalho))  # ccpHdd
    struct.pack_into("<H", fib, 0x98, 0x5D)     # cbRgFcLcb
    struct.pack_into("<II", fib, 0x9A + 33 * 8, len(prefixo), len(clx))  # fcClx, lcbClx
    palavra = bytearray(fib) + texto
    if fins_ttp:
        limites = sorted({INICIO_TEXTO, INICIO_TEXTO + len(texto), *fins_ttp})
        palavra += b"\x00" * (-len(palavra) % 512)
        pn = len(palavra) // 512
        palavra += _fkp_papx(limites, fins_ttp)
        fc_bte = len(stream_tabela)
        stream_tabela += struct.pack("<III", limites[0], limites[-1], pn)
        struct.pack_into("<II", palavra, 0x9A + 13 * 8, fc_bte, 12)  # fcPlcfBtePapx
    if not minifat:
        palavra += b"\x00" * max(0, 4096 - len(palavra))
        stream_tabela += b"\x00" * max(0, 4096 - len(stream_tabela))
    struct.pack_into("<i", palavra, 0x40, len(palavra))  # cbMac
    streams = {"WordDocument": bytes(palavra), tabela: stream_tabela}
    streams.update(extras or {})
    return cfb(streams)


def doc_word95(texto: str) -> bytes:
    """Word 6/95 não complexo: FIB antigo (nFib 0x65) e texto cp1252 entre fcMin e fcMac."""
    bruto = texto.encode("cp1252")
    fib = bytearray(0x300)
    struct.pack_into("<HHHHHH", fib, 0, 0xA5EC, 0x0065, 0, 0x0416, 0, 0)
    struct.pack_into("<II", fib, 0x18, 0x300, 0x300 + len(bruto))
    palavra = bytes(fib) + bruto
    palavra += b"\x00" * max(0, 4096 - len(palavra))
    return cfb({"WordDocument": palavra})


def doc_curto() -> bytes:
    return doc_word97([("Requerimento sintético nº 5/2026\rSolicita informações sobre a "
                        "manutenção das praças públicas.\r", True)])


def doc_fragmentado() -> bytes:
    return doc_word97([
        ("Câmara Municipal de Niterói — “texto” em cp1252\r", True),
        ("Peça Unicode: meta ≥ 60% → atingida ✓\r", False),
        ("Volta ao cp1252: ação e opinião\r", True),
        ("\x13 HYPERLINK \"https://exemplo.invalid\" \x14Clique aqui\x15 para ver\r", True),
        ("Coluna A\x07Coluna B\x07\x07Valor 1\x07Valor 2\x07\x07", True),
        ("Fim\x0bcom quebra manual\x0cnova página\r", False),
    ])


def doc_antigo() -> bytes:
    return doc_word95("Indicação antiga em Word 95.\rSegunda linha.\r")


def doc_minifat() -> bytes:
    return doc_word97([("Moção sintética guardada no mini stream da MiniFAT.\r", True)],
                      tabela="0Table", minifat=True)


# ---------------------------------------------------------------- RTF e HTML
def rtf_exemplo() -> bytes:
    return (
        rb"{\rtf1\ansi\ansicpg1252\deff0{\fonttbl{\f0\fswiss Arial;}}{\colortbl;\red0\green0\blue0;}"
        rb"{\*\generator Gerador sint\'e9tico;}{\info{\title T\'edtulo oculto}{\author Autor oculto}}"
        b"\r\n"
        rb"\pard\f0\fs24 C\'e2mara Municipal de Niter\'f3i\par" b"\r\n"
        rb"Projeto de Lei n\'ba 1/2026\par" b"\r\n"
        rb"Unicode: \u8364? euro, \uc2\u8212\'97\'97 travess\'e3o\uc1  e liga\u-1279?ura\par" b"\r\n"
        rb"{\field{\*\fldinst HYPERLINK " b'"https://exemplo.invalid"' rb"}{\fldrslt Clique aqui}}\par"
        b"\r\n"
        rb"{\*\shppict{\pict\pngblip 89504e470d0a1a0a}}"
        rb"\trowd\cellx1000\cellx2000 A1\cell B1\cell\row" b"\r\n"
        rb"{\*\bindado \bin3 " + b"\x00}{" + rb"}"
        rb"Fim da fun\'e7\'e3o\par}"
    )


def html_exemplo() -> bytes:
    return (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>Título da página</title>"
        "<style>.x{color:red}</style><script>var segredo = \"não deve aparecer\";</script></head>"
        "<body><h1>Câmara Municipal de Niterói</h1>"
        "<p>Primeiro &amp; parágrafo com&nbsp;entidade &eacute; texto.</p>"
        "<table><tr><th>Item</th><th>Valor</th></tr><tr><td>Item A</td><td>10</td></tr></table>"
        "<!-- comentário oculto --><p>Último<br>linha</p></body></html>"
    ).encode("utf-8")


# ---------------------------------------------------------------- imagem com texto (5×7)
_FONTE = {
    "A": [".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "B": ["####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."],
    "C": [".###.", "#...#", "#....", "#....", "#....", "#...#", ".###."],
    "D": ["####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."],
    "E": ["#####", "#....", "#....", "####.", "#....", "#....", "#####"],
    "F": ["#####", "#....", "#....", "####.", "#....", "#....", "#...."],
    "G": [".###.", "#...#", "#....", "#.###", "#...#", "#...#", ".####"],
    "H": ["#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "I": [".###.", "..#..", "..#..", "..#..", "..#..", "..#..", ".###."],
    "J": ["..###", "...#.", "...#.", "...#.", "...#.", "#..#.", ".##.."],
    "K": ["#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"],
    "L": ["#....", "#....", "#....", "#....", "#....", "#....", "#####"],
    "M": ["#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"],
    "N": ["#...#", "#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#"],
    "O": [".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "P": ["####.", "#...#", "#...#", "####.", "#....", "#....", "#...."],
    "Q": [".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".##.#"],
    "R": ["####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"],
    "S": [".####", "#....", "#....", ".###.", "....#", "....#", "####."],
    "T": ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."],
    "U": ["#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "V": ["#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."],
    "W": ["#...#", "#...#", "#...#", "#.#.#", "#.#.#", "#.#.#", ".#.#."],
    "X": ["#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"],
    "Y": ["#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."],
    "Z": ["#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"],
    "0": [".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."],
    "1": ["..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."],
    "2": [".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"],
    "3": ["#####", "...#.", "..#..", "...#.", "....#", "#...#", ".###."],
    "4": ["...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."],
    "5": ["#####", "#....", "####.", "....#", "....#", "#...#", ".###."],
    "6": ["..##.", ".#...", "#....", "####.", "#...#", "#...#", ".###."],
    "7": ["#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."],
    "8": [".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."],
    "9": [".###.", "#...#", "#...#", ".####", "....#", "...#.", ".##.."],
    " ": ["....."] * 7,
}


def bitmap_texto(linhas: list[str], escala: int = 4, margem: int = 32) -> tuple[int, int, bytes]:
    """Imagem em tons de cinza (8 bits, fundo branco) com o texto na fonte 5×7."""
    avanco, altura_linha = 6 * escala, 10 * escala
    largura = 2 * margem + max(len(l) for l in linhas) * avanco
    altura = 2 * margem + len(linhas) * altura_linha
    pixels = bytearray(b"\xff" * (largura * altura))
    for n, linha in enumerate(linhas):
        for k, letra in enumerate(linha.upper()):
            glifo = _FONTE.get(letra, _FONTE[" "])
            for gy, fileira in enumerate(glifo):
                for gx, ponto in enumerate(fileira):
                    if ponto != "#":
                        continue
                    x0 = margem + k * avanco + gx * escala
                    y0 = margem + n * altura_linha + gy * escala
                    for y in range(y0, y0 + escala):
                        inicio = y * largura + x0
                        pixels[inicio:inicio + escala] = b"\x00" * escala
    return largura, altura, bytes(pixels)


def png_bytes(largura: int, altura: int, pixels: bytes) -> bytes:
    """PNG em tons de cinza de 8 bits, sem filtro, com zlib nível 9."""
    def bloco(tipo: bytes, dados: bytes) -> bytes:
        return (struct.pack(">I", len(dados)) + tipo + dados
                + struct.pack(">I", zlib.crc32(tipo + dados) & 0xFFFFFFFF))
    linhas = b"".join(b"\x00" + pixels[y * largura:(y + 1) * largura] for y in range(altura))
    return (b"\x89PNG\r\n\x1a\n"
            + bloco(b"IHDR", struct.pack(">IIBBBBB", largura, altura, 8, 0, 0, 0, 0))
            + bloco(b"IDAT", zlib.compress(linhas, 9))
            + bloco(b"IEND", b""))


# ---------------------------------------------------------------- PDF
def _escapar_pdf(texto: str) -> bytes:
    bruto = texto.encode("cp1252")
    return bruto.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _quebrar(texto: str, largura: int = 80) -> list[str]:
    linhas, atual = [], ""
    for palavra in texto.split():
        if atual and len(atual) + 1 + len(palavra) > largura:
            linhas.append(atual)
            atual = palavra
        else:
            atual = f"{atual} {palavra}".strip()
    if atual:
        linhas.append(atual)
    return linhas


def pdf_bytes(paginas: list[dict]) -> bytes:
    """PDF 1.4 mínimo. Cada página é {"texto": [linhas]} (Helvetica, WinAnsi) ou
    {"imagem": (largura, altura, pixels)} (imagem cinza FlateDecode, sem texto)."""
    objetos: list[bytes] = []

    def novo(corpo: bytes) -> int:
        objetos.append(corpo)
        return len(objetos)

    catalogo = novo(b"")
    raiz_paginas = novo(b"")
    fonte = novo(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    filhos = []
    for pagina in paginas:
        if "texto" in pagina:
            ops = b"BT\n/F1 11 Tf\n14 TL\n56 790 Td\n"
            ops += b"".join(b"(" + _escapar_pdf(l) + b") Tj T*\n" for l in pagina["texto"])
            ops += b"ET"
            recursos = b"<< /Font << /F1 %d 0 R >> >>" % fonte
        else:
            largura, altura, pixels = pagina["imagem"]
            comprimido = zlib.compress(pixels, 9)
            imagem = novo(
                b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceGray "
                b"/BitsPerComponent 8 /Filter /FlateDecode /Length %d >>\nstream\n"
                % (largura, altura, len(comprimido)) + comprimido + b"\nendstream"
            )
            pl, pa = largura * 72 / 150, altura * 72 / 150  # como se escaneada a 150 dpi
            ops = b"q %.2f 0 0 %.2f 56 %.2f cm /Im1 Do Q" % (pl, pa, 790 - pa)
            recursos = b"<< /XObject << /Im1 %d 0 R >> >>" % imagem
        conteudo = novo(b"<< /Length %d >>\nstream\n" % len(ops) + ops + b"\nendstream")
        filhos.append(novo(
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 595 842] /Resources %s /Contents %d 0 R >>"
            % (raiz_paginas, recursos, conteudo)
        ))
    objetos[catalogo - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % raiz_paginas
    objetos[raiz_paginas - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % f for f in filhos), len(filhos))

    saida = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    deslocamentos = []
    for i, corpo in enumerate(objetos, 1):
        deslocamentos.append(len(saida))
        saida += b"%d 0 obj\n" % i + corpo + b"\nendobj\n"
    xref = len(saida)
    saida += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objetos) + 1)
    for d in deslocamentos:
        saida += b"%010d 00000 n \n" % d
    saida += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objetos) + 1, catalogo, xref)
    return bytes(saida)


def pagina_texto() -> dict:
    return {"texto": ["Câmara Municipal de Niterói", "Projeto de Lei nº 2/2026", ""] + _quebrar(PARAGRAFO)}


def pagina_escaneada() -> dict:
    return {"imagem": bitmap_texto(TEXTO_ESCANEADO)}


def pdf_texto() -> bytes:
    return pdf_bytes([pagina_texto()])


def pdf_misto() -> bytes:
    return pdf_bytes([pagina_texto(), pagina_escaneada()])


def pdf_escaneado() -> bytes:
    return pdf_bytes([pagina_escaneada()])


def pdf_corrompido() -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 9 0 R" + b"\x00\xff" * 64 + b"\nquebrado"


def png_escaneado() -> bytes:
    return png_bytes(*bitmap_texto(TEXTO_ESCANEADO))


# ---------------------------------------------------------------- zips compostos
def zip_docx_pdf() -> bytes:
    return zip_bytes({"documento.docx": docx_simples(), "anexo.pdf": pdf_texto()})


def zip_aninhado() -> bytes:
    nivel3 = zip_bytes({"profundo.docx": docx_simples()})
    nivel2 = zip_bytes({"interno.docx": docx_completo(), "nivel3.zip": nivel3})
    return zip_bytes({"externo.rtf": rtf_exemplo(), "nivel2.zip": nivel2})


FIXTURES = {
    "docx_simples.docx": docx_simples,
    "docx_completo.docx": docx_completo,
    "docx_sem_documento.docx": docx_sem_documento,
    "doc_curto.doc": doc_curto,
    "doc_fragmentado.doc": doc_fragmentado,
    "doc_minifat.doc": doc_minifat,
    "doc_word95.doc": doc_antigo,
    "exemplo.rtf": rtf_exemplo,
    "exemplo.html": html_exemplo,
    "pdf_texto.pdf": pdf_texto,
    "pdf_misto.pdf": pdf_misto,
    "pdf_escaneado.pdf": pdf_escaneado,
    "pdf_corrompido.pdf": pdf_corrompido,
    "escaneado.png": png_escaneado,
    "zip_docx_pdf.zip": zip_docx_pdf,
    "zip_aninhado.zip": zip_aninhado,
}


def main() -> int:
    for nome, funcao in FIXTURES.items():
        dados = funcao()
        if len(dados) > 50 * 1024:
            print(f"{nome}: {len(dados)} bytes, acima de 50 KB", file=sys.stderr)
            return 1
        (PASTA / nome).write_bytes(dados)
        print(f"{nome}: {len(dados)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
