"""Testes dos extratores de texto (coletor/extratores/).

As fixtures são sintéticas e geradas em memória por tests/fixtures/textos/gerar_fixtures.py.
Os testes de PDF e OCR com as ferramentas reais (poppler e tesseract) são pulados quando
elas não estão no PATH; os demais usam ferramentas falsas (scripts Python) passadas pelo
mapeamento `ferramentas`.

Uso: python -m unittest tests.test_extratores
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from coletor import extratores
from coletor.extratores import base, cfb, ferramentas, pdf
from coletor.trechos import normalizar

_CAMINHO_GERADOR = Path(__file__).resolve().parent / "fixtures" / "textos" / "gerar_fixtures.py"
_spec = importlib.util.spec_from_file_location("gerar_fixtures_textos", _CAMINHO_GERADOR)
fx = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(fx)

PDFTOTEXT = shutil.which("pdftotext")
PDFTOPPM = shutil.which("pdftoppm")
TESSERACT = shutil.which("tesseract")

# ------------------------------------------------------------------- ferramentas falsas
FALSO = r'''
import json
import sys
import time
from pathlib import Path

pasta = Path(__file__).resolve().parent
cfg = json.loads((pasta / "config.json").read_text(encoding="utf-8"))
ferramenta, args = sys.argv[1], sys.argv[2:]


def registrar(linha):
    with open(pasta / "registro.txt", "a", encoding="utf-8") as f:
        f.write(linha + "\n")


if ferramenta in ("pdftotext", "pdftoppm") and args == ["-v"]:
    sys.stderr.write(ferramenta + " version 99.1.0\nCopyright 2005-2025 The Poppler Developers\n")
    sys.exit(0)
if ferramenta == "pdftotext":
    time.sleep(cfg.get("dormir", 0))
    if cfg.get("falhar"):
        sys.stderr.write("Syntax Error: arquivo falso\n")
        sys.exit(1)
    saida = "".join(p + "\f" for p in cfg["paginas"])
    sys.stdout.buffer.write(saida.encode("utf-8"))
    sys.exit(0)
if ferramenta == "pdftoppm":
    n = args[args.index("-f") + 1]
    registrar("pdftoppm " + n)
    if int(n) in cfg.get("falhar_paginas", []):
        sys.stderr.write("Syntax Error: pagina falsa\n")
        sys.exit(1)
    Path(args[-1] + ".png").write_bytes(b"\x89PNG falso")
    sys.exit(0)
if ferramenta == "tesseract":
    if args == ["--version"]:
        print("tesseract v9.9.9.20260101")
        sys.exit(0)
    if args == ["--list-langs"]:
        print('List of available languages in "falso/" (2):')
        for idioma in cfg.get("idiomas", ["eng", "por"]):
            print(idioma)
        sys.exit(0)
    imagem, saida = args[0], args[1]
    registrar("tesseract " + Path(imagem).name)
    texto = cfg.get("ocr_texto", "Texto lido pelo OCR falso")
    Path(saida + ".txt").write_text(texto, encoding="utf-8")
    linhas = ["level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext",
              "1\t1\t0\t0\t0\t0\t0\t0\t100\t100\t-1\t"]
    confs = cfg.get("confs") or [90.0] * 1000
    for i, (palavra, conf) in enumerate(zip(texto.split(), confs)):
        linhas.append("5\t1\t1\t1\t1\t%d\t0\t0\t10\t10\t%s\t%s" % (i + 1, conf, palavra))
    Path(saida + ".tsv").write_text("\n".join(linhas) + "\n", encoding="utf-8")
    sys.exit(0)
sys.exit(2)
'''

PAGINA_LONGA = (
    "Página com texto suficiente: " + "a Câmara Municipal de Niterói discute o orçamento " * 4
)


class ComFerramentasFalsas(unittest.TestCase):
    """Base: cria o script falso e o mapeamento `ferramentas` num diretório temporário."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self._tmp.name)
        self.script = self.pasta / "falso.py"
        self.script.write_text(FALSO, encoding="utf-8")
        self.configurar(paginas=[PAGINA_LONGA])
        self.ferr = {n: [sys.executable, str(self.script), n] for n in ("pdftotext", "pdftoppm", "tesseract")}
        ferramentas._cache_versoes.clear()
        ferramentas._cache_idiomas.clear()

    def tearDown(self) -> None:
        ferramentas._cache_versoes.clear()
        ferramentas._cache_idiomas.clear()
        self._tmp.cleanup()

    def configurar(self, **cfg) -> None:
        (self.pasta / "config.json").write_text(json.dumps(cfg), encoding="utf-8")

    def registro(self) -> list[str]:
        arq = self.pasta / "registro.txt"
        return arq.read_text(encoding="utf-8").splitlines() if arq.exists() else []


# ------------------------------------------------------------------- detecção
class TestDetectar(unittest.TestCase):
    def test_formatos(self) -> None:
        casos = {
            "docx": fx.docx_simples(),
            "zip": fx.zip_docx_pdf(),
            "pdf": fx.pdf_texto(),
            "doc": fx.doc_curto(),
            "rtf": fx.rtf_exemplo(),
            "html": fx.html_exemplo(),
            "png": fx.png_escaneado(),
            "jpeg": b"\xff\xd8\xff\xe0" + b"\x00" * 20,
            "tiff": b"II*\x00" + b"\x00" * 20,
            "vazio": b"",
            "texto": "Texto simples da Câmara.\n".encode("utf-8"),
            "desconhecido": b"\x00\x01\x02\x03binario",
        }
        for esperado, dados in casos.items():
            with self.subTest(esperado=esperado):
                self.assertEqual(extratores.detectar(dados), esperado)

    def test_html_com_declaracao_xml_e_docx_sem_documento(self) -> None:
        self.assertEqual(extratores.detectar(b"<?xml version='1.0'?>\n<html><body>x</body></html>"), "html")
        self.assertEqual(extratores.detectar(fx.docx_sem_documento()), "docx")
        self.assertEqual(extratores.detectar(b"   \n\t "), "vazio")

    def test_pdf_so_no_inicio(self) -> None:
        self.assertEqual(extratores.detectar(b"\xef\xbb\xbf %PDF-1.7\n..."), "pdf")
        html = b"<html><body><p>Baixe o arquivo (formato %PDF-1.4)</p></body></html>"
        self.assertEqual(extratores.detectar(html), "html")
        self.assertEqual(extratores.detectar(b"Texto que cita %PDF-1.4 no meio"), "texto")


# ------------------------------------------------------------------- docx
class TestDocx(unittest.TestCase):
    def test_docx_simples(self) -> None:
        r = extratores.extrair(fx.docx_simples())
        self.assertEqual((r.formato, r.status, r.extrator), ("docx", "ok", "docx"))
        self.assertEqual(r.versao_extrator, base.VERSAO_EXTRATORES)
        self.assertIn("Projeto de Lei nº 1/2026", r.texto)
        self.assertIn("hortas comunitárias", r.texto)
        self.assertIn("Art. 1º\tEsta lei entra em vigor.\nNa data.", r.texto)

    def test_docx_completo(self) -> None:
        r = extratores.extrair(fx.docx_completo())
        self.assertEqual(r.status, "ok")
        self.assertIn("Item | Quantidade\nBancos de praça | 12\nLixeiras | 30", r.texto)
        # cabeçalhos e rodapés ficam fora do texto, só contados (header1, header2, footer1)
        self.assertNotIn("CABEÇALHO SINTÉTICO", r.texto)
        self.assertNotIn("Rodapé sintético", r.texto)
        self.assertEqual(r.cabecalhos_omitidos, 3)
        self.assertIn("Nota de rodapé sintética.", r.texto)
        self.assertIn("Texto mantido7", r.texto)
        self.assertNotIn("TEXTO APAGADO", r.texto)
        self.assertNotIn("PAGE", r.texto)
        self.assertNotIn("SEPARADOR", r.texto)
        self.assertEqual(r.texto.count("Caixa de texto sintética"), 1)
        # corpo antes das notas
        self.assertLess(r.texto.index("Indicação sintética"), r.texto.index("Nota de rodapé"))

    def test_docx_cabecalho_com_ato_numerado_fica(self) -> None:
        cabecalho = (f'<?xml version="1.0" encoding="UTF-8"?><w:hdr {fx.NS_DECL}>'
                     + fx._p("CÂMARA MUNICIPAL DE NITERÓI") + fx._p("PROJETO DE LEI Nº 45/2026")
                     + fx._p("Indicação sintética") + "</w:hdr>").encode()
        dados = fx.zip_bytes({
            "[Content_Types].xml": fx._CT.encode(), "_rels/.rels": fx._RELS.encode(),
            "word/document.xml": fx._documento(fx._p("Indicação sintética") + fx._p("Dispõe sobre praças.")),
            "word/header1.xml": cabecalho,
        })
        r = extratores.extrair(dados)
        self.assertEqual(r.texto, "PROJETO DE LEI Nº 45/2026\n\nIndicação sintética\nDispõe sobre praças.")
        self.assertEqual(r.cabecalhos_omitidos, 1)

    def test_docx_sem_document_xml(self) -> None:
        r = extratores.extrair(fx.docx_sem_documento())
        self.assertEqual(r.status, "erro_formato")
        self.assertIn("document.xml", r.detalhe)

    def test_docx_xml_invalido(self) -> None:
        dados = fx.zip_bytes({"[Content_Types].xml": b"<Types/>", "word/document.xml": b"<w:document><w:body"})
        self.assertEqual(extratores.extrair(dados).status, "erro_formato")

    def test_docx_sem_texto_e_vazio_legitimo(self) -> None:
        dados = fx.zip_bytes({"word/document.xml": fx._documento("<w:p/>")})
        r = extratores.extrair(dados)
        self.assertEqual((r.formato, r.status, r.texto), ("docx", "vazio_legitimo", ""))


# ------------------------------------------------------------------- CFB e .doc
class TestDoc(unittest.TestCase):
    def test_doc_curto(self) -> None:
        r = extratores.extrair(fx.doc_curto())
        self.assertEqual((r.formato, r.status, r.extrator), ("doc", "ok", "doc"))
        self.assertEqual(
            r.texto,
            "Requerimento sintético nº 5/2026\nSolicita informações sobre a manutenção das praças públicas.",
        )

    def test_doc_fragmentado_cp1252_e_unicode(self) -> None:
        r = extratores.extrair(fx.doc_fragmentado())
        self.assertEqual(r.status, "ok")
        linhas = r.texto.split("\n")
        self.assertEqual(linhas[0], "Câmara Municipal de Niterói — “texto” em cp1252")
        self.assertEqual(linhas[1], "Peça Unicode: meta ≥ 60% → atingida ✓")
        self.assertEqual(linhas[2], "Volta ao cp1252: ação e opinião")
        self.assertEqual(linhas[3], "Clique aqui para ver")
        self.assertIn("Coluna A | Coluna B\nValor 1 | Valor 2", r.texto)
        self.assertIn("Fim\ncom quebra manual\nnova página", r.texto)
        self.assertNotIn("HYPERLINK", r.texto)
        self.assertFalse(any(ord(c) < 32 and c not in "\n\t" for c in r.texto))

    def test_doc_minifat(self) -> None:
        dados = fx.doc_minifat()
        arquivo = cfb.CompoundFile(dados)
        filhos = arquivo.filhos()
        self.assertLess(filhos["WordDocument"].tamanho, 4096)  # lido pela MiniFAT
        self.assertLess(filhos["0Table"].tamanho, 4096)
        self.assertTrue(arquivo.minifat)
        r = extratores.extrair(dados)
        self.assertEqual(r.status, "ok")
        self.assertEqual(r.texto, "Moção sintética guardada no mini stream da MiniFAT.")

    def test_cfb_le_streams_grandes_e_pequenos(self) -> None:
        grande = bytes(range(256)) * 40
        dados = fx.cfb({"Grande": grande, "Pequeno": b"abc", "Vazio": b""})
        arquivo = cfb.CompoundFile(dados)
        self.assertEqual(arquivo.stream("Grande"), grande)
        self.assertEqual(arquivo.stream("Pequeno"), b"abc")
        self.assertEqual(arquivo.stream("Vazio"), b"")
        self.assertTrue(arquivo.existe("Pequeno"))
        self.assertFalse(arquivo.existe("Ausente"))
        with self.assertRaises(KeyError):
            arquivo.stream("Ausente")

    def test_cfb_com_ciclo_termina_com_erro(self) -> None:
        dados = fx.cfb_com_ciclo(fx.doc_curto())
        with self.assertRaises(cfb.ErroCFB):
            cfb.CompoundFile(dados)
        inicio = time.perf_counter()
        r = extratores.extrair(dados)
        self.assertLess(time.perf_counter() - inicio, 5)
        self.assertEqual(r.status, "erro_formato")
        self.assertIn("ciclo", r.detalhe)

    def test_cfb_com_ciclo_na_cadeia_de_um_stream(self) -> None:
        dados = bytearray(fx.cfb({"WordDocument": b"\x00" * 5000}))
        fat0 = struct.unpack_from("<I", dados, 0x4C)[0]
        arquivo = cfb.CompoundFile(bytes(dados))
        inicio = arquivo.filhos()["WordDocument"].inicio
        # o segundo setor do stream volta para o primeiro
        struct.pack_into("<I", dados, (fat0 + 1) * 512 + (inicio + 1) * 4, inicio)
        with self.assertRaises(cfb.ErroCFB):
            cfb.CompoundFile(bytes(dados)).stream("WordDocument")

    def test_cfb_truncado(self) -> None:
        dados = fx.doc_curto()
        for corte in (100, 600, len(dados) // 2, len(dados) - 600):
            with self.subTest(corte=corte):
                self.assertEqual(extratores.extrair(dados[:corte]).status, "erro_formato")

    def test_cfb_tamanho_declarado_maior_que_arquivo(self) -> None:
        dados = bytearray(fx.cfb({"WordDocument": b"x" * 100}))
        dir_ini = struct.unpack_from("<I", dados, 0x30)[0]
        entrada = (dir_ini + 1) * 512 + 128  # primeira entrada depois da raiz
        struct.pack_into("<Q", dados, entrada + 0x78, 10 ** 9)
        with self.assertRaises(cfb.ErroCFB):
            cfb.CompoundFile(bytes(dados))

    def test_cfb_sem_word_document(self) -> None:
        r = extratores.extrair(fx.cfb({"Workbook": b"planilha"}))
        self.assertEqual((r.formato, r.status), ("doc", "erro_formato"))
        self.assertIn("WordDocument", r.detalhe)

    def test_doc_criptografado(self) -> None:
        r = extratores.extrair(fx.doc_word97([("segredo\r", True)], criptografado=True))
        self.assertEqual(r.status, "erro_formato")
        self.assertIn("criptografado", r.detalhe)

    def test_doc_peca_fora_do_stream(self) -> None:
        dados = fx.doc_word97([("texto\r", True)])
        arquivo = cfb.CompoundFile(dados)
        tabela = arquivo.stream("1Table")
        self.assertTrue(tabela)  # sanidade: a piece table existe
        # ccpText enorme não faz ler além das peças
        bruto = bytearray(dados)
        palavra = arquivo.filhos()["WordDocument"]
        deslocamento = (palavra.inicio + 1) * 512 + 0x40 + 12
        struct.pack_into("<i", bruto, deslocamento, 10 ** 8)
        r = extratores.extrair(bytes(bruto))
        self.assertEqual((r.status, r.texto), ("ok", "texto"))

    def test_doc_grande_rapido_com_muitas_pecas(self) -> None:
        bloco = "Parágrafo sintético de um documento grande da Câmara, com ação. " * 23 + "\r"
        pecas = [(f"{i:04d} {bloco}", i % 2 == 0) for i in range(2000)]  # cp1252 e UTF-16
        dados = fx.doc_word97(pecas)
        self.assertGreater(len(dados), 4_000_000)
        inicio = time.perf_counter()
        r = extratores.extrair(dados)
        duracao = time.perf_counter() - inicio
        self.assertEqual(r.status, "ok")
        self.assertTrue(r.texto.startswith("0000 Parágrafo sintético"))
        self.assertIn("1999 Parágrafo", r.texto)
        self.assertLess(duracao, 2.0, "QA: ≤ 2 s em 5 MB sem OCR")

    def test_pecas_repetidas_recusadas(self) -> None:
        texto = "Trecho repetido da piece table. " * 100 + "\r"
        self.assertEqual(extratores.extrair(fx.doc_word97([(texto, True)])).status, "ok")
        r = extratores.extrair(fx.doc_word97([(texto, True)], repetir=50))
        self.assertEqual(r.status, "erro_formato")
        self.assertIn("WordDocument", r.detalhe)

    def test_tabela_com_celula_vazia_e_linhas_ttp(self) -> None:
        texto = "Tabela\rA\x07\x07C\x07\x07D\x07E\x07F\x07\x07Fim\r"
        # marcas de fim de linha: a \x07 depois de C (posição 12) e a depois de F (posição 19)
        fins = [i for i, c in enumerate(texto) if c == "\x07"]
        r = extratores.extrair(fx.doc_word97([(texto, True)], ttp=[fins[3], fins[7]]))
        self.assertEqual(r.texto, "Tabela\nA |  | C\nD | E | F\nFim")

    def test_tabela_sem_papx_vira_celulas(self) -> None:
        texto = "A\x07B\x07\x07Fim\r"
        r = extratores.extrair(fx.doc_word97([(texto, True)], ttp=[]))
        self.assertEqual(r.texto, "A | B |  | Fim")

    def test_campo_sem_fim_mantem_texto(self) -> None:
        r = extratores.extrair(fx.doc_word97([("Antes \x13 PAGE \x14 depois do campo aberto\r", True),
                                              ("Outro \x13 HYPERLINK sem fim e texto final\r", True)]))
        self.assertEqual(r.status, "ok")
        self.assertIn("Antes  depois do campo aberto", r.texto)
        self.assertIn("texto final", r.texto)
        self.assertIn("campo do Word sem fim", r.detalhe)

    def test_cabecalho_do_doc_fica_fora(self) -> None:
        r = extratores.extrair(fx.doc_word97([("Corpo do requerimento.\r", True)],
                                             cabecalho="CÂMARA MUNICIPAL DE NITERÓI\r"))
        self.assertEqual((r.texto, r.cabecalhos_omitidos), ("Corpo do requerimento.", 1))

    def test_cabecalho_do_doc_com_ato_numerado_fica(self) -> None:
        r = extratores.extrair(fx.doc_word97([("Corpo do requerimento.\r", True)],
                                             cabecalho="REQUERIMENTO Nº 12/2026\rCÂMARA MUNICIPAL DE NITERÓI\r"))
        self.assertEqual((r.texto, r.cabecalhos_omitidos), ("REQUERIMENTO Nº 12/2026\n\nCorpo do requerimento.", 1))

    def test_word95(self) -> None:
        r = extratores.extrair(fx.doc_word95("Indicação antiga em Word 95.\rSegunda linha.\r"))
        self.assertEqual((r.formato, r.status), ("doc", "ok"))
        self.assertEqual(r.texto, "Indicação antiga em Word 95.\nSegunda linha.")

    def test_real_pl_127510(self) -> None:
        pasta = Path(__file__).resolve().parent / "fixtures" / "textos"
        dados = (pasta / "real_pl_127510.doc").read_bytes()
        esperado = (pasta / "real_pl_127510.esperado.txt").read_text(encoding="utf-8")
        r = extratores.extrair(dados)
        self.assertEqual((r.formato, r.status), ("doc", "ok"))
        self.assertIn("Art. 1º - Fica vedada a circulação", r.texto)
        self.assertIn("JUSTIFICATIVA", r.texto)
        self.assertIn("§ 1º - Para efeitos desta Lei", r.texto)
        # o corpo é idêntico ao texto conferido; o papel timbrado (histórias de cabeçalho)
        # que vinha depois das assinaturas agora fica fora do texto
        corpo = esperado[:esperado.index("Benny Briolly") + len("Benny Briolly")]
        self.assertTrue(r.texto.startswith(corpo), r.texto[:200])
        self.assertEqual(r.texto, normalizar(r.texto))


# ------------------------------------------------------------------- RTF, HTML, texto
class TestRtfHtmlTexto(unittest.TestCase):
    def test_rtf(self) -> None:
        r = extratores.extrair(fx.rtf_exemplo())
        self.assertEqual((r.formato, r.status, r.extrator), ("rtf", "ok", "rtf"))
        self.assertEqual(
            r.texto.split("\n"),
            [
                "Câmara Municipal de Niterói",
                "Projeto de Lei nº 1/2026",
                "Unicode: € euro, — travessão e liga\ufb01ura",
                "Clique aqui",
                "A1 | B1",
                "Fim da função",
            ],
        )
        for oculto in ("Arial", "Título oculto", "Autor oculto", "HYPERLINK", "89504e47", "Gerador"):
            self.assertNotIn(oculto, r.texto)

    def test_rtf_par_de_surrogates(self) -> None:
        r = extratores.extrair(b"{\\rtf1 Emoji \\u-10179?\\u-8704? fim \\u-10179? solto}")
        self.assertEqual(r.texto, "Emoji \U0001F600 fim  solto")

    def test_rtf_malformado(self) -> None:
        self.assertEqual(extratores.extrair(b"{\\rtf1 sem fechar {\\b grupo").status, "ok")
        self.assertEqual(extratores.extrair(b"{\\rtf1 {\\*\\x}}").status, "vazio_legitimo")

    def test_html(self) -> None:
        r = extratores.extrair(fx.html_exemplo())
        self.assertEqual((r.formato, r.status), ("html", "ok"))
        self.assertIn("Câmara Municipal de Niterói", r.texto)
        self.assertIn("Primeiro & parágrafo com entidade é texto.", r.texto)
        self.assertIn("Item | Valor\nItem A | 10", r.texto)
        self.assertIn("Último\nlinha", r.texto)
        for oculto in ("segredo", "color:red", "comentário oculto"):
            self.assertNotIn(oculto, r.texto)

    def test_html_cp1252(self) -> None:
        dados = "<html><meta charset='windows-1252'><p>Niterói</p></html>".encode("cp1252")
        self.assertEqual(extratores.extrair(dados).texto, "Niterói")

    def test_texto_simples(self) -> None:
        r = extratores.extrair("Linha 1\r\nLinha 2\u200b\u00a0  \r\n\r\n\r\n\r\nLinha 3".encode("utf-8"))
        self.assertEqual((r.formato, r.status), ("texto", "ok"))
        self.assertEqual(r.texto, "Linha 1\nLinha 2\n\nLinha 3")


# ------------------------------------------------------------------- vazio e desconhecido
class TestVazioDesconhecido(unittest.TestCase):
    def test_arquivo_vazio(self) -> None:
        for dados in (b"", b"  \r\n "):
            with self.subTest(dados=dados):
                r = extratores.extrair(dados)
                self.assertEqual((r.formato, r.status, r.texto), ("vazio", "vazio_legitimo", ""))

    def test_desconhecido(self) -> None:
        r = extratores.extrair(b"\x00\x01\x02\x03binario")
        self.assertEqual((r.formato, r.status), ("desconhecido", "erro_formato"))

    def test_status_sempre_conhecido(self) -> None:
        for dados in (fx.docx_simples()[:200], b"PK\x03\x04lixo", b"%PDF", fx.MAGICO_CFB + b"\x00" * 600):
            with self.subTest(dados=dados[:8]):
                r = extratores.extrair(dados, ferramentas={"pdftotext": None})
                self.assertIn(r.status, base.STATUS)


# ------------------------------------------------------------------- OpenDocument (mantém o contrato zip)
class TestOpenDocument(unittest.TestCase):
    _NS = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
           'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
           'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"')

    def _xml(self, corpo: str, tipo: str = "text") -> bytes:
        return (f'<office:document-content {self._NS}>'
                '<office:automatic-styles>ESTILO OCULTO</office:automatic-styles>'
                f'<office:body><office:{tipo}>{corpo}</office:{tipo}></office:body>'
                '</office:document-content>').encode()

    def _pacote(self, conteudo: bytes | None, mime: str = "text") -> bytes:
        membros = {
            "mimetype": ("application/vnd.oasis.opendocument." + mime).encode(),
            "META-INF/manifest.xml": b"<manifest>METADADO OCULTO</manifest>",
            "meta.xml": b"<meta>AUTOR OCULTO</meta>",
            "styles.xml": b"<styles>ESTILO OCULTO</styles>",
            # Não deve tentar OCR das imagens embutidas, mesmo com --ocr.
            "Pictures/figura.png": fx.png_escaneado(),
        }
        if conteudo is not None:
            membros["content.xml"] = conteudo
        return fx.zip_bytes(membros)

    def test_odt_so_conteudo_sem_xml_metadados_ou_ocr(self) -> None:
        xml = self._xml('<text:h>Título sintético</text:h>'
                        '<text:p>Antes <text:span>do span</text:span> depois'
                        '<text:s text:c="3"/>espaços<text:tab/>tab'
                        '<text:line-break/>outra linha &amp; fim.</text:p>'
                        '<table:table><table:table-row>'
                        '<table:table-cell><text:p>Célula A</text:p></table:table-cell>'
                        '<table:table-cell><text:p>Célula B</text:p></table:table-cell>'
                        '</table:table-row></table:table>'
                        '<text:p>Final.</text:p>')
        dados = self._pacote(xml)
        with mock.patch.object(extratores._ocr, "extrair_imagem", side_effect=AssertionError("OCR indevido")):
            r = extratores.extrair(dados, ocr=True, ferramentas={"tesseract": None})
        self.assertEqual(extratores.detectar(dados), "zip")
        self.assertEqual((r.formato, r.extrator, r.status, r.versao_extrator),
                         ("zip", "zip", "ok", base.VERSAO_EXTRATORES))
        self.assertEqual(r.texto, "Título sintético\nAntes do span depois   espaços\ttab\n"
                         "outra linha & fim.\nCélula A\tCélula B\nFinal.")
        self.assertEqual((r.paginas_ocr, r.confianca, r.detalhe), (0, None, ""))

    def test_ods_e_odp(self) -> None:
        for mime in ("spreadsheet", "presentation"):
            with self.subTest(mime=mime):
                xml = self._xml('<text:p>Texto da célula ou slide.</text:p>', mime)
                r = extratores.extrair(self._pacote(xml, mime))
                self.assertEqual((r.status, r.texto), ("ok", "Texto da célula ou slide."))

    def test_vazio_e_xml_ausente_ou_invalido(self) -> None:
        self.assertEqual(extratores.extrair(self._pacote(self._xml(""))).status, "vazio_legitimo")
        for xml in (None, b"<xml", b"<document/>"):
            with self.subTest(xml=xml):
                r = extratores.extrair(self._pacote(xml))
                self.assertEqual((r.status, r.texto), ("erro_formato", ""))
                self.assertNotIn("METADADO", r.texto)

    def test_dtd_e_entidades_recusados_inclusive_utf16(self) -> None:
        for entidade in ('<!ENTITY x SYSTEM "file:///arquivo-inexistente">', '<!ENTITY x "expansão">'):
            xml = '<!DOCTYPE office:document-content [' + entidade + ']>' + self._xml('<text:p>&x;</text:p>').decode()
            for codificacao in ("utf-8", "utf-16"):
                with self.subTest(entidade=entidade, codificacao=codificacao):
                    r = extratores.extrair(self._pacote(xml.encode(codificacao)))
                    self.assertEqual((r.status, r.texto), ("erro_formato", ""))
                    self.assertIn("DTD", r.detalhe)

    def test_limites_de_zip_espacos_e_aninhamento(self) -> None:
        dados = self._pacote(self._xml('<text:p>Texto</text:p>'))
        with mock.patch.object(base, "LIMITE_DESCOMPACTADO", 100):
            r = extratores.extrair(dados)
        self.assertEqual(r.status, "erro_formato")
        self.assertIn("limite", r.detalhe)
        xml = self._xml('<text:p>Antes<text:s text:c="1000000000"/>depois</text:p>')
        r = extratores.extrair(self._pacote(xml))
        self.assertEqual((r.status, r.texto), ("erro_formato", ""))
        self.assertIn("limite", r.detalhe)
        xml = self._xml('<text:span>' * 210 + '<text:p>Texto</text:p>' + '</text:span>' * 210)
        r = extratores.extrair(self._pacote(xml))
        self.assertEqual(r.status, "erro_formato")
        self.assertIn("aninhamento", r.detalhe)

    def test_odt_dentro_de_zip_compartilha_orcamento(self) -> None:
        interno = self._pacote(self._xml('<text:p>Texto interno.</text:p>'))
        externo = fx.zip_bytes({"anexo.odt": interno})
        self.assertEqual(extratores.extrair(externo).texto, "=== anexo.odt ===\nTexto interno.")
        with mock.patch.object(base, "LIMITE_DESCOMPACTADO", len(interno) + 100):
            r = extratores.extrair(externo)
        self.assertNotEqual(r.status, "ok")
        self.assertEqual(r.texto, "")
        self.assertIn("limite", r.detalhe)


# ------------------------------------------------------------------- zip
class TestZip(ComFerramentasFalsas):
    def test_metadados_de_empacotamento_ficam_fora(self) -> None:
        dados = fx.zip_bytes({
            "mimetype": b"application/x-outro-pacote",
            "META-INF/manifest.xml": b"<manifest>OCULTO</manifest>",
            "META-INF/assinatura.xml": b"<signature>OCULTO</signature>",
            "[Content_Types].xml": b"<Types>OCULTO</Types>",
            "_rels/.rels": b"<Relationships>OCULTO</Relationships>",
            "docProps/core.xml": b"<core>OCULTO</core>",
            "meta.xml": b"<meta>OCULTO</meta>",
            "styles.xml": b"<styles>OCULTO</styles>",
            "settings.xml": b"<settings>OCULTO</settings>",
            "anexo.txt": b"Texto do anexo.",
            # Um XML de dados, não metadados de pacote, continua sendo extraído.
            "dados.xml": b"<dados>Conteudo do anexo XML.</dados>",
        })
        r = extratores.extrair(dados)
        self.assertEqual(r.status, "ok")
        self.assertEqual(r.texto, "=== anexo.txt ===\nTexto do anexo.\n\n"
                         "=== dados.xml ===\n<dados>Conteudo do anexo XML.</dados>")
        self.assertNotIn("OCULTO", r.texto)

    def test_zip_com_docx_e_pdf(self) -> None:
        r = extratores.extrair(fx.zip_docx_pdf(), ferramentas=self.ferr)
        self.assertEqual((r.formato, r.status, r.extrator), ("zip", "ok", "zip"))
        self.assertTrue(r.texto.startswith("=== documento.docx ===\nProjeto de Lei nº 1/2026"))
        self.assertIn("=== anexo.pdf ===\nPágina com texto suficiente", r.texto)
        self.assertEqual(r.paginas, 1)

    def test_zip_aninhado_ate_dois_niveis(self) -> None:
        r = extratores.extrair(fx.zip_aninhado())
        self.assertEqual(r.status, "ok")
        self.assertIn("=== externo.rtf ===\nCâmara Municipal de Niterói", r.texto)
        self.assertIn("=== nivel2.zip ===\n=== interno.docx ===", r.texto)
        self.assertNotIn("=== profundo.docx ===", r.texto)
        self.assertIn("profundidade", r.detalhe)

    def test_zip_bomb_recusada(self) -> None:
        dados = fx.zip_bytes({"zeros.txt": b"\x00" * 200_000, "ok.txt": b"texto"})
        self.assertLess(len(dados), 2_000)
        with mock.patch.object(base, "LIMITE_DESCOMPACTADO", 100_000):
            r = extratores.extrair(dados)
        self.assertEqual((r.formato, r.status), ("zip", "erro_formato"))
        self.assertIn("limite", r.detalhe)

    def test_zip_bomb_com_tamanho_declarado_falso(self) -> None:
        dados = bytearray(fx.zip_bytes({"a.txt": b"A" * 50_000}))
        # diretório central e cabeçalho local passam a declarar 10 bytes descompactados
        central = dados.rfind(b"PK\x01\x02")
        struct.pack_into("<I", dados, central + 24, 10)
        struct.pack_into("<I", dados, 22, 10)
        r = extratores.extrair(bytes(dados))
        self.assertNotEqual(r.status, "ok")
        self.assertLess(len(r.texto), 1000)

    def test_membro_corrompido_com_limite_no_nome(self) -> None:
        dados = bytearray(fx.zip_bytes({"leia.txt": "Texto do anexo".encode(),
                                        "limite_gastos.pdf": fx.pdf_texto()}, comprimir=False))
        with zipfile.ZipFile(io.BytesIO(bytes(dados))) as zf:
            info = zf.getinfo("limite_gastos.pdf")
        inicio = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
        dados[inicio + 20] ^= 0xFF  # dado corrompido: CRC não confere
        r = extratores.extrair(bytes(dados))
        self.assertEqual((r.formato, r.status), ("zip", "ok"))
        self.assertIn("=== leia.txt ===\nTexto do anexo", r.texto)
        self.assertIn("limite_gastos.pdf", r.detalhe)

    def test_zip_invalido_e_vazio(self) -> None:
        self.assertEqual(extratores.extrair(b"PK\x03\x04" + b"\x00" * 30).status, "erro_formato")
        r = extratores.extrair(fx.zip_bytes({}))
        self.assertEqual((r.formato, r.status), ("zip", "vazio_legitimo"))


# ------------------------------------------------------------------- PDF e OCR com ferramentas falsas
class TestPdfFalso(ComFerramentasFalsas):
    def test_confianca_por_pagina_reutilizada_do_cache_sem_refazer_ocr(self) -> None:
        from coletor.extratores import ocr
        self.configurar(paginas=[PAGINA_LONGA, "", ""])
        cache = self.pasta / "cache-ocr"
        lidas = [("Texto da segunda página", 40.0, 4), ("Texto da terceira página", 90.0, 4)]
        with mock.patch.object(ocr, "_ocr_pagina", side_effect=lidas) as executar:
            primeira = extratores.extrair(fx.pdf_misto(), ocr=True, ferramentas=self.ferr, cache_ocr=cache)
            self.assertEqual(executar.call_count, 2)
        with mock.patch.object(ocr, "_ocr_pagina", side_effect=AssertionError("não deve refazer OCR")):
            segunda = extratores.extrair(fx.pdf_misto(), ocr=True, ferramentas=self.ferr, cache_ocr=cache)
        self.assertEqual(primeira, segunda)
        self.assertEqual(segunda.confianca_paginas, {2: 40.0, 3: 90.0})
        self.assertEqual(segunda.status, "ok_ocr")  # média global alta não promove a página 2
        self.assertEqual(segunda.texto.split("\n\f\n"), [PAGINA_LONGA.rstrip(), lidas[0][0], lidas[1][0]])

    def test_pdf_com_texto(self) -> None:
        r = extratores.extrair(fx.pdf_texto(), ferramentas=self.ferr)
        self.assertEqual((r.formato, r.status, r.extrator, r.versao_extrator),
                         ("pdf", "ok", "pdftotext", "99.1.0"))
        self.assertEqual((r.paginas, r.paginas_ocr, r.paginas_escaneadas), (1, 0, []))

    def test_normaliza_saida_do_pdftotext(self) -> None:
        self.configurar(paginas=[PAGINA_LONGA + "\u200b fim\u00a0  \r\n\r\n\r\n\r\nNiteroi\u0301"])
        r = extratores.extrair(fx.pdf_texto(), ferramentas=self.ferr)
        self.assertNotIn("\u200b", r.texto)
        self.assertNotIn("\r", r.texto)
        self.assertTrue(r.texto.endswith(" fim\n\nNiteroí"))

    def test_misto_sem_ocr(self) -> None:
        self.configurar(paginas=[PAGINA_LONGA, "  12  ", PAGINA_LONGA])
        r = extratores.extrair(fx.pdf_misto(), ferramentas=self.ferr)
        self.assertEqual(r.status, "ok_parcial")  # há páginas com texto: o disponível é mantido
        self.assertEqual((r.paginas, r.paginas_escaneadas, r.paginas_ocr), (3, [2], 0))
        self.assertIn("Página com texto suficiente", r.texto)
        self.assertIn("páginas escaneadas sem OCR: 2", r.detalhe)
        self.assertEqual(self.registro(), [])

    def test_todo_escaneado_sem_ocr(self) -> None:
        self.configurar(paginas=["  12  ", ""])
        r = extratores.extrair(fx.pdf_escaneado(), ferramentas=self.ferr)
        self.assertEqual((r.status, r.paginas_escaneadas), ("escaneado_sem_ocr", [1, 2]))
        self.assertIn("ok_parcial", base.STATUS)

    def test_zip_com_membro_escaneado_e_membro_com_texto(self) -> None:
        self.configurar(paginas=[""])
        dados = fx.zip_bytes({"leia.txt": "Texto do anexo".encode(), "escaneado.pdf": fx.pdf_escaneado()})
        r = extratores.extrair(dados, ferramentas=self.ferr)
        self.assertEqual((r.formato, r.status), ("zip", "ok_parcial"))
        self.assertIn("Texto do anexo", r.texto)
        r = extratores.extrair(fx.zip_bytes({"escaneado.pdf": fx.pdf_escaneado()}), ferramentas=self.ferr)
        self.assertEqual((r.formato, r.status), ("zip", "escaneado_sem_ocr"))

    def test_misto_ocr_so_na_pagina_escaneada(self) -> None:
        self.configurar(paginas=[PAGINA_LONGA, "", PAGINA_LONGA], ocr_texto="Texto escaneado da segunda",
                        confs=[95, 85, 90, 80])
        r = extratores.extrair(fx.pdf_misto(), ocr=True, ferramentas=self.ferr)
        self.assertEqual(r.status, "ok_ocr")
        self.assertEqual(self.registro(), ["pdftoppm 2", "tesseract pagina-2.png"])
        self.assertEqual((r.paginas, r.paginas_ocr, r.paginas_escaneadas), (3, 1, [2]))
        self.assertEqual(r.confianca, 87.5)
        self.assertEqual(r.confianca_paginas, {2: 87.5})
        self.assertEqual((r.extrator, r.versao_extrator), ("pdftotext+tesseract", "99.1.0+9.9.9"))
        partes = r.texto.split("\n\f\n")  # páginas separadas por uma linha só com \f
        self.assertEqual(len(partes), 3)
        self.assertEqual(partes[1], "Texto escaneado da segunda")
        self.assertTrue(partes[0].startswith("Página com texto"))

    def test_falha_de_ocr_numa_pagina_nao_perde_as_outras(self) -> None:
        self.configurar(paginas=[PAGINA_LONGA, "", "", PAGINA_LONGA], ocr_texto="Texto lido da página",
                        falhar_paginas=[3])
        r = extratores.extrair(fx.pdf_misto(), ocr=True, ferramentas=self.ferr)
        self.assertEqual(r.status, "ok_parcial")
        self.assertIn("OCR falhou nas páginas 3", r.detalhe)
        self.assertEqual((r.paginas_escaneadas, r.paginas_ocr, list(r.confianca_paginas)), ([2, 3], 1, [2]))
        partes = r.texto.split("\n\f\n")
        self.assertEqual(partes[1], "Texto lido da página")
        self.assertTrue(partes[0].startswith("Página com texto") and partes[3].startswith("Página com texto"))

    def test_orcamento_de_paginas_de_ocr(self) -> None:
        from coletor.extratores import ocr
        self.configurar(paginas=["", "", ""], ocr_texto="Texto lido")
        with mock.patch.object(ocr, "MAX_PAGINAS_OCR", 1):
            r = extratores.extrair(fx.pdf_escaneado(), ocr=True, ferramentas=self.ferr)
        self.assertEqual(r.status, "ok_parcial")  # a página 1 foi lida; 2 e 3 ficam para depois
        self.assertIn("OCR adiado", r.detalhe)
        self.assertIn("páginas 2, 3", r.detalhe)
        self.assertEqual((r.paginas_ocr, r.texto.split("\n\f\n")), (1, ["Texto lido", "", ""]))
        self.assertEqual(self.registro(), ["pdftoppm 1", "tesseract pagina-1.png"])

    def test_cache_de_ocr_retoma_paginas_adiadas(self) -> None:
        from coletor.extratores import ocr
        self.configurar(paginas=["", "", ""], ocr_texto="Texto lido", confs=[80, 90])
        cache = self.pasta / "cache-ocr"
        with mock.patch.object(ocr, "MAX_PAGINAS_OCR", 1):
            primeira = extratores.extrair(fx.pdf_escaneado(), ocr=True, ferramentas=self.ferr, cache_ocr=cache)
            self.assertEqual(self.registro(), ["pdftoppm 1", "tesseract pagina-1.png"])
            segunda = extratores.extrair(fx.pdf_escaneado(), ocr=True, ferramentas=self.ferr, cache_ocr=cache)
            self.assertEqual(self.registro()[2:], ["pdftoppm 2", "tesseract pagina-2.png"])
        self.assertEqual((primeira.status, primeira.paginas_ocr), ("ok_parcial", 1))
        self.assertEqual((segunda.status, segunda.paginas_ocr), ("ok_parcial", 2))
        self.assertIn("páginas 3", segunda.detalhe)
        terceira = extratores.extrair(fx.pdf_escaneado(), ocr=True, ferramentas=self.ferr, cache_ocr=cache)
        self.assertEqual(self.registro()[4:], ["pdftoppm 3", "tesseract pagina-3.png"])
        self.assertEqual((terceira.status, terceira.paginas_ocr, terceira.confianca), ("ok_ocr", 3, 85.0))
        quarta = extratores.extrair(fx.pdf_escaneado(), ocr=True, ferramentas=self.ferr, cache_ocr=cache)
        self.assertEqual(len(self.registro()), 6)  # tudo do cache: nenhuma chamada nova
        self.assertEqual(quarta.texto, terceira.texto)
        self.assertEqual(len(list(cache.glob("*.json"))), 3)
        # sem cache, o OCR é refeito
        extratores.extrair(fx.pdf_escaneado(), ocr=True, ferramentas=self.ferr)
        self.assertEqual(len(self.registro()), 12)

    def test_orcamento_de_tempo_de_ocr(self) -> None:
        from coletor.extratores import ocr
        self.configurar(paginas=["", ""])
        with mock.patch.object(ocr, "OCR_SEGUNDOS_DOCUMENTO", 0):
            r = extratores.extrair(fx.pdf_escaneado(), ocr=True, ferramentas=self.ferr)
        self.assertEqual((r.status, r.paginas_ocr), ("escaneado_sem_ocr", 0))
        self.assertIn("páginas 1, 2", r.detalhe)
        self.assertEqual(self.registro(), [])

    def test_ocr_pior_que_o_texto_embutido_nao_conta(self) -> None:
        embutido = "Texto curto embutido com 40 letras ou mais aqui"
        self.configurar(paginas=[embutido], ocr_texto="ruim", confs=[10])
        r = extratores.extrair(fx.pdf_escaneado(), ocr=True, ferramentas=self.ferr)
        self.assertEqual(r.texto, embutido)
        self.assertEqual((r.confianca, r.confianca_paginas, r.paginas_ocr), (None, {}, 1))
        self.assertEqual(r.status, "ok")

    def test_ocr_baixa_confianca(self) -> None:
        self.configurar(paginas=[""], ocr_texto="ruído ilegível aqui", confs=[40, 50, 30])
        r = extratores.extrair(fx.pdf_escaneado(), ocr=True, ferramentas=self.ferr)
        self.assertEqual(r.status, "ocr_baixa_confianca")
        self.assertEqual(r.confianca, 40.0)

    def test_escaneado_sem_texto_no_ocr_e_vazio(self) -> None:
        self.configurar(paginas=[""], ocr_texto="")
        r = extratores.extrair(fx.pdf_escaneado(), ocr=True, ferramentas=self.ferr)
        self.assertEqual((r.status, r.confianca, r.paginas_ocr), ("vazio_legitimo", None, 1))

    def test_timeout_do_subprocess(self) -> None:
        self.configurar(paginas=[PAGINA_LONGA], dormir=30)
        inicio = time.perf_counter()
        with mock.patch.dict(ferramentas.TIMEOUT_SEGUNDOS, {"pdftotext": 2}):
            r = extratores.extrair(fx.pdf_texto(), ferramentas=self.ferr)
        self.assertLess(time.perf_counter() - inicio, 20)
        self.assertEqual(r.status, "erro_formato")
        self.assertIn("tempo esgotado", r.detalhe)

    def test_pdftotext_com_erro_e_pdf_corrompido(self) -> None:
        self.configurar(paginas=[], falhar=True)
        r = extratores.extrair(fx.pdf_corrompido(), ferramentas=self.ferr)
        self.assertEqual(r.status, "erro_formato")
        self.assertIn("pdftotext", r.detalhe)

    def test_pdf_sem_paginas(self) -> None:
        self.configurar(paginas=[])
        self.assertEqual(extratores.extrair(fx.pdf_texto(), ferramentas=self.ferr).status, "erro_formato")

    def test_path_vazio_da_pendente_ferramenta(self) -> None:
        with mock.patch.dict(os.environ, {"PATH": ""}):
            r = extratores.extrair(fx.pdf_texto())
        self.assertEqual((r.formato, r.status), ("pdf", "pendente_ferramenta"))
        self.assertIn("pdftotext", r.detalhe)
        r = extratores.extrair(fx.pdf_texto(), ferramentas={"pdftotext": None})
        self.assertEqual(r.status, "pendente_ferramenta")

    def test_executavel_inexistente_da_pendente_ferramenta(self) -> None:
        inexistente = str(self.pasta / "nao-existe" / "pdftotext.exe")
        r = extratores.extrair(fx.pdf_texto(), ferramentas={"pdftotext": inexistente})
        self.assertEqual(r.status, "pendente_ferramenta")

    def test_ocr_sem_pdftoppm_ou_tesseract(self) -> None:
        self.configurar(paginas=[PAGINA_LONGA, ""])
        for ausente in ("pdftoppm", "tesseract"):
            with self.subTest(ausente=ausente):
                mapa = dict(self.ferr, **{ausente: None})
                r = extratores.extrair(fx.pdf_misto(), ocr=True, ferramentas=mapa)
                self.assertEqual(r.status, "pendente_ferramenta")
                self.assertIn(ausente, r.detalhe)
                self.assertIn("Página com texto suficiente", r.texto)
                self.assertEqual(r.paginas_escaneadas, [2])

    def test_tesseract_sem_portugues(self) -> None:
        self.configurar(paginas=[""], idiomas=["eng", "osd"])
        r = extratores.extrair(fx.pdf_escaneado(), ocr=True, ferramentas=self.ferr)
        self.assertEqual(r.status, "pendente_ferramenta")
        self.assertIn("por", r.detalhe)

    def test_imagens(self) -> None:
        png = fx.png_escaneado()
        r = extratores.extrair(png, ferramentas=self.ferr)
        self.assertEqual((r.formato, r.status, r.paginas_escaneadas), ("png", "escaneado_sem_ocr", [1]))
        self.configurar(ocr_texto="Imagem lida", confs=[70, 80])
        r = extratores.extrair(png, ocr=True, ferramentas=self.ferr)
        self.assertEqual((r.status, r.texto, r.confianca, r.extrator, r.versao_extrator),
                         ("ok_ocr", "Imagem lida", 75.0, "tesseract", "9.9.9"))
        self.assertEqual(self.registro(), ["tesseract entrada.png"])
        r = extratores.extrair(b"\xff\xd8\xff\xe0jpeg", ocr=True, ferramentas={"tesseract": None})
        self.assertEqual((r.formato, r.status), ("jpeg", "pendente_ferramenta"))

    def test_ferramentas_disponiveis(self) -> None:
        info = extratores.ferramentas_disponiveis(self.ferr)
        self.assertEqual(info, {"pdftotext": "99.1.0", "pdftoppm": "99.1.0", "tesseract": "9.9.9",
                                "tesseract_idiomas": ["eng", "por"]})
        vazio = extratores.ferramentas_disponiveis({n: None for n in ferramentas.NOMES})
        self.assertEqual(vazio, {"pdftotext": None, "pdftoppm": None, "tesseract": None,
                                 "tesseract_idiomas": []})

    def test_argumentos_sem_shell(self) -> None:
        chamadas = []
        original = subprocess.run

        def espiao(*args, **kwargs):
            chamadas.append((args, kwargs))
            return original(*args, **kwargs)

        self.configurar(paginas=[PAGINA_LONGA, ""])
        with mock.patch.object(ferramentas.subprocess, "run", espiao):
            extratores.extrair(fx.pdf_misto(), ocr=True, ferramentas=self.ferr)
        self.assertTrue(chamadas)
        for args, kwargs in chamadas:
            self.assertIsInstance(args[0], list)
            self.assertFalse(kwargs.get("shell"))
            self.assertIsNotNone(kwargs.get("timeout"))
        comandos = [a[0][3:] for a, _ in chamadas]
        self.assertIn(["-layout", "-enc", "UTF-8"], [c[:3] for c in comandos])
        pdftoppm = next(c for c in comandos if c[:2] == ["-r", "300"])
        self.assertEqual(pdftoppm[:9], ["-r", "300", "-gray", "-f", "2", "-l", "2", "-png", "-singlefile"])
        tesseract = next(c for c in comandos if "--psm" in c)
        self.assertEqual(tesseract[2:], ["-l", "por", "--psm", "6", "-c", "tessedit_create_txt=1", "-c", "tessedit_create_tsv=1"])


class TestConfiancaTsv(unittest.TestCase):
    def test_media_das_palavras(self) -> None:
        from coletor.extratores import ocr
        tsv = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
               "1\t1\t0\t0\t0\t0\t0\t0\t9\t9\t-1\t\n"
               "5\t1\t1\t1\t1\t1\t0\t0\t9\t9\t96.5\tCâmara\n"
               "5\t1\t1\t1\t1\t2\t0\t0\t9\t9\t-1\t\n"
               "5\t1\t1\t1\t1\t3\t0\t0\t9\t9\t33.5\tNiterói\n"
               "5\t1\t1\t1\t1\t4\t0\t0\t9\t9\t50\t \n")
        self.assertEqual(ocr.confianca_tsv(tsv), (65.0, 2))
        self.assertEqual(ocr.confianca_tsv(""), (None, 0))


class TestPaginasPdftotext(unittest.TestCase):
    def test_divisao(self) -> None:
        self.assertEqual(pdf.paginas_pdftotext("a\fb\f"), ["a", "b"])
        self.assertEqual(pdf.paginas_pdftotext("a\f\f"), ["a", ""])
        self.assertEqual(pdf.paginas_pdftotext("\f"), [""])
        self.assertEqual(pdf.paginas_pdftotext(""), [])
        self.assertEqual(pdf.caracteres_uteis("a-b c_1 ç!"), 5)


# ------------------------------------------------------------------- ferramentas reais
@unittest.skipUnless(PDFTOTEXT, "pdftotext (poppler) não está no PATH")
class TestPdfReal(unittest.TestCase):
    def test_pdf_com_texto(self) -> None:
        r = extratores.extrair(fx.pdf_texto())
        self.assertEqual((r.status, r.extrator, r.paginas), ("ok", "pdftotext", 1))
        self.assertRegex(r.versao_extrator, r"^\d+\.\d+")
        self.assertIn("Câmara Municipal de Niterói", r.texto)
        self.assertIn("Projeto de Lei nº 2/2026", r.texto)
        self.assertIn("hortas comunitárias", r.texto)
        self.assertEqual(r.texto, normalizar(r.texto))

    def test_pdf_corrompido(self) -> None:
        self.assertEqual(extratores.extrair(fx.pdf_corrompido()).status, "erro_formato")

    def test_escaneado_e_misto_sem_ocr(self) -> None:
        r = extratores.extrair(fx.pdf_escaneado())
        self.assertEqual((r.status, r.paginas, r.paginas_escaneadas), ("escaneado_sem_ocr", 1, [1]))
        r = extratores.extrair(fx.pdf_misto())
        self.assertEqual((r.status, r.paginas, r.paginas_escaneadas), ("ok_parcial", 2, [2]))
        self.assertIn("Câmara Municipal de Niterói", r.texto)


@unittest.skipUnless(PDFTOTEXT and PDFTOPPM and TESSERACT, "poppler ou tesseract não estão no PATH")
class TestOcrReal(unittest.TestCase):
    def setUp(self) -> None:
        if "por" not in ferramentas.idiomas_tesseract():
            self.skipTest("tesseract sem o idioma por")

    def test_pdf_misto_com_ocr_so_na_pagina_escaneada(self) -> None:
        r = extratores.extrair(fx.pdf_misto(), ocr=True)
        self.assertIn(r.status, ("ok_ocr", "ocr_baixa_confianca"))
        self.assertEqual((r.paginas, r.paginas_ocr, r.paginas_escaneadas), (2, 1, [2]))
        self.assertEqual(list(r.confianca_paginas), [2])
        self.assertEqual(r.extrator, "pdftotext+tesseract")
        self.assertIn("Câmara Municipal de Niterói", r.texto)

    def test_jpeg_gerado_pelo_pdftoppm(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "escaneado.pdf"
            arquivo.write_bytes(fx.pdf_escaneado())
            prefixo = Path(pasta) / "escaneado"
            subprocess.run([PDFTOPPM, "-r", "150", "-gray", "-jpeg", "-singlefile", str(arquivo), str(prefixo)],
                           check=True, capture_output=True, timeout=120)
            jpeg = prefixo.with_name("escaneado.jpg").read_bytes()
        self.assertEqual(extratores.detectar(jpeg), "jpeg")
        r = extratores.extrair(jpeg, ocr=True)
        self.assertIn(r.status, ("ok_ocr", "ocr_baixa_confianca"))
        self.assertEqual((r.extrator, r.paginas_ocr), ("tesseract", 1))
        self.assertIsNotNone(r.confianca)


class TestFixtures(unittest.TestCase):
    def test_deterministicas_e_pequenas(self) -> None:
        for nome, funcao in fx.FIXTURES.items():
            with self.subTest(nome=nome):
                dados = funcao()
                self.assertEqual(dados, funcao())
                self.assertLessEqual(len(dados), 50 * 1024)


if __name__ == "__main__":
    unittest.main()
