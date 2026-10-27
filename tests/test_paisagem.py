"""Marca, favicon, textura, camadas da paisagem e PNG: XML, paleta, orçamento e bytes versionados."""
from __future__ import annotations

import contextlib
import gzip
import io
import json
import re
import struct
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path
from unittest import mock

from coletor import paisagem
from coletor.regras_documentos import BAIRROS_NITEROI

RAIZ = Path(__file__).resolve().parents[1]
NS = "{http://www.w3.org/2000/svg}"
PALETA = {"#F2B544", "#E8743B", "#B4491A", "#13476B", "#9CC6E4", "#0B2A3F", "#E6EEF4", "#F7F2E9", "#0E1B26",
          "#FFFFFF", "#14283A"}
HEX = re.compile(r"#[0-9A-Fa-f]{6}\b|#[0-9A-Fa-f]{3}\b")
ABA_CLARA = "#FFFFFF"
ABAS_ESCURAS = ("#202124", "#0E1B26")
LIMITE_BYTES = 2048


def luminancia(cor: str) -> float:
    """Luminância relativa WCAG 2.x de um hexadecimal #RRGGBB."""
    canais = []
    for i in (1, 3, 5):
        c = int(cor[i:i + 2], 16) / 255
        canais.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = canais
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(a: str, b: str) -> float:
    la, lb = sorted((luminancia(a), luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def regras_css(css: str) -> dict[str, dict[str, str]]:
    """Mapa seletor -> propriedades das regras simples `sel{prop:valor;...}`."""
    regras: dict[str, dict[str, str]] = {}
    for seletor, corpo in re.findall(r"([^{}@]+)\{([^{}]*)\}", css):
        props = regras.setdefault(seletor.strip(), {})
        for declaracao in corpo.split(";"):
            if ":" in declaracao:
                prop, valor = declaracao.split(":", 1)
                props[prop.strip()] = valor.strip()
    return regras


class MarcaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.favicon = paisagem.favicon_svg()
        self.marca = paisagem.marca_svg()

    def test_xml_valido_com_viewbox(self) -> None:
        for texto in (self.favicon, self.marca):
            raiz = ET.fromstring(texto)
            self.assertEqual(raiz.tag, f"{NS}svg")
            self.assertRegex(raiz.get("viewBox") or "", r"^0 0 \d+ \d+$")
            self.assertNotIn("width", raiz.attrib)
            self.assertNotIn("height", raiz.attrib)

    def test_cores_so_da_paleta(self) -> None:
        cores = HEX.findall(self.favicon)
        self.assertTrue(cores)
        for cor in cores:
            self.assertIn(cor.upper(), PALETA, cor)
        # A marca não fixa cores: tudo vem dos tokens da página.
        self.assertEqual(HEX.findall(self.marca), [])

    def test_constantes_de_cor_existem_em_estilo_css(self) -> None:
        css = (RAIZ / "site_src" / "estilo.css").read_text(encoding="utf-8").upper()
        constantes = {nome: valor for nome, valor in vars(paisagem).items()
                      if nome.isupper() and isinstance(valor, str) and HEX.fullmatch(valor)}
        self.assertTrue(constantes)
        for nome, valor in constantes.items():
            with self.subTest(constante=nome):
                self.assertIn(valor.upper(), css)

    def test_tamanho_e_formato(self) -> None:
        for texto in (self.favicon, self.marca):
            bruto = texto.encode("utf-8")
            self.assertLessEqual(len(bruto), LIMITE_BYTES)
            self.assertTrue(texto.endswith("</svg>\n"))
            self.assertEqual(texto.count("\n"), 1)
            self.assertNotIn("\r", texto)

    def test_deterministico(self) -> None:
        self.assertEqual(paisagem.favicon_svg(), self.favicon)
        self.assertEqual(paisagem.marca_svg(), self.marca)

    def test_mesma_geometria_nas_duas_saidas(self) -> None:
        def caminhos(texto: str) -> list[str]:
            return [p.get("d") for p in ET.fromstring(texto).iter(f"{NS}path")]

        self.assertEqual(caminhos(self.favicon), caminhos(self.marca))
        self.assertEqual(caminhos(self.favicon), [paisagem.caminho_sol(), paisagem.caminho_ondas()])
        # Coordenadas inteiras: nenhuma casa decimal nos paths.
        for d in caminhos(self.favicon):
            self.assertNotIn(".", d)

    def test_ondas_decrescentes(self) -> None:
        comprimentos = [c for _, _, c in paisagem.ONDAS]
        self.assertEqual(len(comprimentos), 3)
        self.assertEqual(comprimentos, sorted(comprimentos, reverse=True))
        self.assertEqual(len(set(comprimentos)), 3)
        with self.assertRaises(ValueError):
            paisagem.caminho_onda(0, 0, paisagem.MEIO_PERIODO + 1)

    def test_numero(self) -> None:
        self.assertEqual(paisagem.numero(4.0), "4")
        self.assertEqual(paisagem.numero(-3), "-3")
        self.assertEqual(paisagem.numero(2.5), "2.5")
        self.assertEqual(paisagem.numero(1.239), "1.24")

    def test_marca_sprite_com_currentcolor(self) -> None:
        self.assertIn('<symbol id="marca"', self.marca)
        self.assertIn("currentColor", self.marca)
        simbolo = ET.fromstring(self.marca).find(f"{NS}symbol")
        self.assertIsNotNone(simbolo)
        self.assertEqual(simbolo.get("id"), "marca")
        self.assertTrue(simbolo.get("viewBox"))
        self.assertNotIn("var(", self.marca)
        # O sol herda fill do <svg> do cabeçalho (.marca svg em estilo.css); as ondas usam currentColor.
        sol, ondas = list(simbolo.iter(f"{NS}path"))
        self.assertNotIn("fill", sol.attrib)
        self.assertEqual(ondas.get("stroke"), "currentColor")
        self.assertEqual(ondas.get("fill"), "none")
        self.assertNotIn('fill="#', self.marca)
        css = (RAIZ / "site_src" / "estilo.css").read_text(encoding="utf-8")
        self.assertIn(".marca svg { fill: var(--marca-sol); color: var(--baia); }", css)

    def test_favicon_titulo_e_media_query(self) -> None:
        raiz = ET.fromstring(self.favicon)
        self.assertEqual(raiz.findtext(f"{NS}title"), "Radar dos Vereadores de Niterói")
        self.assertIn("@media (prefers-color-scheme: dark)", self.favicon)
        # Cores só por classe, para que a media query funcione.
        for elemento in raiz.iter():
            self.assertNotIn("fill", elemento.attrib)
            self.assertNotIn("stroke", elemento.attrib)

    def test_favicon_contraste_nos_dois_temas(self) -> None:
        raiz = ET.fromstring(self.favicon)
        css = raiz.findtext(f"{NS}style") or ""
        claro_css, _, escuro_css = css.partition("@media (prefers-color-scheme: dark)")
        claro, escuro = regras_css(claro_css), regras_css(escuro_css)
        classes = [p.get("class") for p in raiz.iter(f"{NS}path")]
        self.assertTrue(classes)
        for classe in classes:
            seletor = f".{classe}"
            self.assertIn(seletor, claro)
            cores_claras = {p: v for p, v in claro[seletor].items() if p in ("fill", "stroke") and v.startswith("#")}
            self.assertTrue(cores_claras, seletor)
            cores_escuras = dict(cores_claras)
            cores_escuras.update({p: v for p, v in escuro.get(seletor, {}).items()
                                  if p in ("fill", "stroke") and v.startswith("#")})
            for cor in cores_claras.values():
                self.assertGreaterEqual(contraste(cor, ABA_CLARA), 3, f"{seletor} {cor} na aba clara")
            for cor in cores_escuras.values():
                for aba in ABAS_ESCURAS:
                    self.assertGreaterEqual(contraste(cor, aba), 3, f"{seletor} {cor} na aba {aba}")

    def test_contraste_wcag(self) -> None:
        self.assertAlmostEqual(contraste("#000000", "#FFFFFF"), 21)
        self.assertAlmostEqual(contraste("#777777", "#777777"), 1)


def geometria_textura() -> dict:
    """Geometria sintética mínima dos 52 bairros, sem depender da base opcional."""
    return {"viewbox": [0, 0, 1000, 800], "osm_base": "2026-10-23T03:26:20Z",
            "atribuicao": "© contribuidores do OpenStreetMap", "licenca": "ODbL 1.0",
            "fonte": "https://www.openstreetmap.org/relation/2220789",
            "bairros": {nome: {"path": "M8,8 9,8 10,8 20,8 20,20Z", "centro": [15, 12], "osm_id": i}
                        for i, nome in enumerate(BAIRROS_NITEROI, 1)}}


def segmentos_caminho(caminho: str) -> list[tuple]:
    """Lê os segmentos não orientados dos paths lineares de entrada e da textura."""
    segmentos = []
    for anel, fechado in re.findall(r"M([^MZ]+)(Z?)", caminho):
        pontos = [tuple(map(int, par.split(","))) for par in anel.split()]
        if fechado:
            pontos.append(pontos[0])
        segmentos.extend(tuple(sorted((a, b))) for a, b in zip(pontos, pontos[1:]) if a != b)
    return segmentos


class TexturaTest(unittest.TestCase):
    def test_xml_contornos_atribuicao_e_data(self) -> None:
        geo = geometria_textura()
        texto = paisagem.textura_svg(geo)
        raiz = ET.fromstring(texto)
        self.assertEqual(raiz.tag, f"{NS}svg")
        self.assertEqual(raiz.get("viewBox"), "0 0 1000 800")
        self.assertEqual(raiz.findtext(f"{NS}title"), "Contornos dos bairros de Niterói")
        descricao = raiz.findtext(f"{NS}desc")
        self.assertIn("© contribuidores do OpenStreetMap, ODbL 1.0, https://www.openstreetmap.org/copyright", descricao)
        self.assertIn(geo["osm_base"], descricao)
        caminhos = list(raiz.iter(f"{NS}path"))
        self.assertEqual(len(caminhos), 1)
        self.assertEqual(caminhos[0].get("fill"), "none")
        self.assertEqual(caminhos[0].get("stroke"), "#000")
        self.assertEqual(caminhos[0].get("stroke-width"), "1")
        self.assertEqual(caminhos[0].get("vector-effect"), "non-scaling-stroke")
        self.assertEqual(caminhos[0].get("d").count("M"), 1)  # 52 contornos idênticos viram um só.
        self.assertIsNone(raiz.find(f"{NS}rect"))
        self.assertEqual(set(HEX.findall(texto)), {"#000"})
        self.assertTrue(texto.endswith("</svg>\n"))
        self.assertNotIn("\r", texto)
        self.assertLessEqual(len(gzip.compress(texto.encode("utf-8"), compresslevel=9, mtime=0)), 12 * 1024)

    def test_deterministico_independente_da_ordem_dos_bairros(self) -> None:
        geo = geometria_textura()
        texto = paisagem.textura_svg(geo)
        self.assertEqual(texto, paisagem.textura_svg(geo))
        geo["bairros"] = dict(reversed(list(geo["bairros"].items())))
        self.assertEqual(texto, paisagem.textura_svg(geo))
        for bairro in geo["bairros"].values():
            bairro["path"] = "M20,20 20,8 10,8 9,8 8,8Z"
        self.assertEqual(texto, paisagem.textura_svg(geo))

    def test_bordas_compartilhadas_sem_duplicatas_em_precisao_integral(self) -> None:
        geo = geometria_textura()
        bairros = list(geo["bairros"].values())
        bairros[0]["path"] = "M20,8 30,8 30,20 20,20Z"  # Borda compartilhada em sentido inverso.
        bairros[1]["path"] += "M40,40 50,40 50,50Z"  # Outro anel, sem conexão.
        with mock.patch.object(paisagem, "DISTANCIA_TEXTURA", 0):
            texto = paisagem.textura_svg(geo)
        segmentos = segmentos_caminho(ET.fromstring(texto).find(f"{NS}path").get("d"))
        esperados = {s for bairro in bairros for s in segmentos_caminho(bairro["path"])}
        self.assertEqual(len(segmentos), len(set(segmentos)))
        self.assertEqual(set(segmentos), esperados)
        self.assertIn(((8, 8), (9, 8)), segmentos)  # Não elimina o segmento de um pixel.

    def test_bytes_independem_do_compressor(self) -> None:
        geo = geometria_textura()
        texto = paisagem.textura_svg(geo)
        with mock.patch.object(paisagem.gzip, "compress", return_value=b"x" * (13 * 1024)):
            self.assertEqual(texto, paisagem.textura_svg(geo))

    def test_geometria_invalida_falha(self) -> None:
        for geo in (None, {}, {**geometria_textura(), "bairros": {}},
                    {**geometria_textura(), "viewbox": [0, 0, 0, 800]}):
            with self.subTest(geo=geo), self.assertRaises(ValueError):
                paisagem.textura_svg(geo)


class ArquivosVersionadosTest(unittest.TestCase):
    def test_site_src_igual_a_geracao(self) -> None:
        """Mudou a geometria? Rode `python -m coletor.paisagem --marca`."""
        for nome, texto in (("favicon.svg", paisagem.favicon_svg()), ("marca.svg", paisagem.marca_svg())):
            with self.subTest(nome=nome):
                self.assertEqual((RAIZ / "site_src" / nome).read_bytes(), texto.encode("utf-8"))

    def test_textura_igual_a_geracao_e_dentro_do_orcamento(self) -> None:
        """Mudou a geometria? Rode `python -m coletor.paisagem --textura`."""
        caminho = RAIZ / "data" / "geo" / "bairros.json"
        if not caminho.exists():
            self.skipTest("data/geo/bairros.json ausente: geometria opcional da textura")
        geo = json.loads(caminho.read_text(encoding="utf-8"))
        texto = paisagem.textura_svg(geo)
        self.assertEqual((RAIZ / "site_src" / "textura-bairros.svg").read_bytes(), texto.encode("utf-8"))
        self.assertEqual(ET.fromstring(texto).get("viewBox"), " ".join(map(str, geo["viewbox"])))
        self.assertIn(geo["osm_base"], ET.fromstring(texto).findtext(f"{NS}desc"))
        self.assertEqual(set(HEX.findall(texto)), {"#000"})
        self.assertEqual(texto, paisagem.textura_svg(geo))
        self.assertLessEqual(len(gzip.compress(texto.encode("utf-8"), compresslevel=9, mtime=0)), 12 * 1024)
        # Em precisão integral, cada borda compartilhada sai uma única vez.
        with mock.patch.object(paisagem, "DISTANCIA_TEXTURA", 0):
            integral = paisagem.textura_svg(geo)
        segmentos = segmentos_caminho(ET.fromstring(integral).find(f"{NS}path").get("d"))
        self.assertEqual(len(segmentos), len(set(segmentos)))
        self.assertEqual(set(segmentos), {s for bairro in geo["bairros"].values()
                                         for s in segmentos_caminho(bairro["path"])})


class CliTest(unittest.TestCase):
    def test_orcamento_excedido_nao_grava_nem_simplifica(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            saida = Path(tmp) / "site_src"
            saida.mkdir()
            destino = saida / "textura-bairros.svg"
            destino.write_bytes(b"textura anterior\n")
            caminho = Path(tmp) / "bairros.json"
            caminho.write_text(json.dumps(geometria_textura()), encoding="utf-8")
            with (mock.patch.object(paisagem, "SAIDA", saida),
                  mock.patch.object(paisagem, "GEOMETRIA", caminho),
                  mock.patch.object(paisagem, "LIMITE_TEXTURA_GZIP", 1),
                  contextlib.redirect_stderr(io.StringIO()) as erro):
                self.assertEqual(paisagem.main(["--marca", "--textura"]), 1)
            self.assertIn("textura excede 12 KiB gzip", erro.getvalue())
            self.assertEqual(destino.read_bytes(), b"textura anterior\n")
            self.assertEqual(list(saida.iterdir()), [destino])

    def test_textura_e_marca_podem_ser_combinadas(self) -> None:
        geo = geometria_textura()
        for argumentos in (["--textura"], ["--marca", "--textura"]):
            with self.subTest(argumentos=argumentos), tempfile.TemporaryDirectory() as tmp:
                saida = Path(tmp) / "site_src"
                caminho = Path(tmp) / "bairros.json"
                caminho.write_text(json.dumps(geo), encoding="utf-8")
                with (mock.patch.object(paisagem, "SAIDA", saida),
                      mock.patch.object(paisagem, "GEOMETRIA", caminho), contextlib.redirect_stdout(io.StringIO())):
                    self.assertEqual(paisagem.main(argumentos), 0)
                self.assertEqual((saida / "textura-bairros.svg").read_bytes(), paisagem.textura_svg(geo).encode("utf-8"))
                self.assertEqual((saida / "marca.svg").exists(), "--marca" in argumentos)
                self.assertEqual((saida / "favicon.svg").exists(), "--marca" in argumentos)

    def test_geometria_ausente_ou_invalida_nao_sobrescreve_textura(self) -> None:
        for conteudo in (None, "{", "{}", "null"):
            with self.subTest(conteudo=conteudo), tempfile.TemporaryDirectory() as tmp:
                saida = Path(tmp) / "site_src"
                saida.mkdir()
                destino = saida / "textura-bairros.svg"
                destino.write_bytes(b"textura anterior\n")
                caminho = Path(tmp) / "bairros.json"
                if conteudo is not None:
                    caminho.write_text(conteudo, encoding="utf-8")
                with (mock.patch.object(paisagem, "SAIDA", saida),
                      mock.patch.object(paisagem, "GEOMETRIA", caminho),
                      contextlib.redirect_stderr(io.StringIO()) as erro):
                    self.assertNotEqual(paisagem.main(["--textura"]), 0)
                self.assertIn("textura não gravada", erro.getvalue())
                self.assertEqual(destino.read_bytes(), b"textura anterior\n")
                self.assertEqual(list(saida.iterdir()), [destino])

    def test_marca_grava_os_dois_arquivos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            saida = Path(tmp) / "site_src"
            with mock.patch.object(paisagem, "SAIDA", saida), contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(paisagem.main(["--marca"]), 0)
            self.assertEqual((saida / "favicon.svg").read_bytes(), paisagem.favicon_svg().encode("utf-8"))
            self.assertEqual((saida / "marca.svg").read_bytes(), paisagem.marca_svg().encode("utf-8"))
            self.assertEqual(sorted(p.name for p in saida.iterdir()), ["favicon.svg", "marca.svg"])
            self.assertIn("favicon.svg", out.getvalue())
            self.assertIn("bytes", out.getvalue())
            # O caminho exibido é o da saída real, não um "site_src/" fixo.
            self.assertIn(str(saida / "marca.svg"), out.getvalue())
            self.assertEqual(paisagem.exibir(paisagem.RAIZ / "site_src" / "favicon.svg"), "site_src/favicon.svg")

    def test_sem_opcao_nao_grava(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            saida = Path(tmp) / "site_src"
            with mock.patch.object(paisagem, "SAIDA", saida), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(paisagem.main([]), 2)
            self.assertFalse(saida.exists())

    def test_camadas_e_og_combinadas_com_marca(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            saida = Path(tmp) / "site_src"
            with (mock.patch.object(paisagem, "SAIDA", saida),
                  mock.patch.object(paisagem, "LARGURA_OG", 64), mock.patch.object(paisagem, "ALTURA_OG", 34),
                  contextlib.redirect_stdout(io.StringIO()) as out):
                self.assertEqual(paisagem.main(["--marca", "--camadas", "--og"]), 0)
            for nome, texto in paisagem.camadas_svg().items():
                self.assertEqual((saida / "paisagem" / nome).read_bytes(), texto.encode("utf-8"))
            self.assertEqual(pixels_png((saida / "og-radar.png").read_bytes()),
                             (64, 34, paisagem.rasterizar(64, 34)))
            self.assertTrue((saida / "marca.svg").exists())
            self.assertEqual(sorted(p.name for p in saida.rglob("*") if p.is_file()),
                             sorted([*paisagem.camadas_svg(), "favicon.svg", "marca.svg", "og-radar.png"]))
            self.assertIn("og-radar.png", out.getvalue())
            self.assertIn("gzip", out.getvalue())

    def test_camadas_acima_do_orcamento_nao_gravam(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            saida = Path(tmp) / "site_src"
            with (mock.patch.object(paisagem, "SAIDA", saida), mock.patch.object(paisagem, "LIMITE_CAMADAS_GZIP", 1),
                  contextlib.redirect_stderr(io.StringIO()) as erro):
                self.assertEqual(paisagem.main(["--marca", "--camadas"]), 1)
            self.assertIn("camadas não gravadas", erro.getvalue())
            self.assertFalse(saida.exists())


# ---- camadas da paisagem
NOMES_CAMADAS = ["fundo.svg", "baia.svg", "promontorio.svg", "orla.svg"]


class CamadasTest(unittest.TestCase):
    def setUp(self) -> None:
        self.camadas = paisagem.camadas_svg()

    def test_ordem_e_nomes(self) -> None:
        self.assertEqual(list(self.camadas), NOMES_CAMADAS)

    def test_xml_viewbox_comum_e_so_preto(self) -> None:
        for nome, texto in self.camadas.items():
            with self.subTest(nome=nome):
                raiz = ET.fromstring(texto)
                self.assertEqual(raiz.tag, f"{NS}svg")
                self.assertEqual(raiz.get("viewBox"), "0 0 1600 600")
                self.assertEqual(raiz.get("preserveAspectRatio"), "xMidYMax slice")
                self.assertNotIn("width", raiz.attrib)
                self.assertNotIn("height", raiz.attrib)
                self.assertEqual(set(HEX.findall(texto)), {"#000"})
                caminhos = list(raiz.iter(f"{NS}path"))
                self.assertTrue(caminhos)
                for elemento in raiz.iter():
                    self.assertNotIn("stroke", elemento.attrib)
                for caminho in caminhos:
                    self.assertEqual(caminho.get("fill"), "#000")
                    d = caminho.get("d")
                    self.assertNotIn(".", d)
                    pares = re.findall(r"(-?\d+),(-?\d+)", d)
                    self.assertTrue(pares)
                    for x, y in pares:
                        self.assertTrue(0 <= int(x) <= 1600 and 0 <= int(y) <= 600, (x, y))
                self.assertIsNone(raiz.find(f"{NS}title"))
                self.assertNotIn("<!--", texto)
                self.assertTrue(texto.endswith("</svg>\n"))
                self.assertEqual(texto.count("\n"), 1)
                self.assertNotIn("\r", texto)

    def test_orcamento_gzip(self) -> None:
        total = sum(len(gzip.compress(t.encode("utf-8"), compresslevel=9, mtime=0)) for t in self.camadas.values())
        self.assertLessEqual(total, 18 * 1024)

    def test_deterministico(self) -> None:
        self.assertEqual(paisagem.camadas_svg(), self.camadas)

    def test_versionadas_iguais_a_geracao(self) -> None:
        """Mudou a silhueta? Rode `python -m coletor.paisagem --camadas`."""
        for nome, texto in self.camadas.items():
            with self.subTest(nome=nome):
                self.assertEqual((RAIZ / "site_src" / "paisagem" / nome).read_bytes(), texto.encode("utf-8"))

    def test_poligonos_inteiros_orientados(self) -> None:
        for nome, poligonos in paisagem.silhuetas().items():
            for p in poligonos:
                with self.subTest(nome=nome):
                    self.assertGreaterEqual(len(p), 3)
                    self.assertGreater(paisagem._area_dupla(p), 0)
                    self.assertTrue(all(isinstance(v, int) for ponto in p for v in ponto))


# ---- PNG
def blocos_png(dados: bytes) -> list[tuple[bytes, bytes]]:
    """Separa os blocos do PNG conferindo assinatura, tamanhos e CRC de cada um."""
    if dados[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError("assinatura PNG inválida")
    blocos = []
    pos = 8
    while pos < len(dados):
        (tamanho,) = struct.unpack(">I", dados[pos:pos + 4])
        tipo = dados[pos + 4:pos + 8]
        corpo = dados[pos + 8:pos + 8 + tamanho]
        (crc,) = struct.unpack(">I", dados[pos + 8 + tamanho:pos + 12 + tamanho])
        if len(corpo) != tamanho or zlib.crc32(tipo + corpo) & 0xFFFFFFFF != crc:
            raise AssertionError(f"bloco {tipo!r} truncado ou com CRC inválido")
        blocos.append((tipo, corpo))
        pos += 12 + tamanho
    return blocos


def pixels_png(dados: bytes) -> tuple[int, int, bytes]:
    """Largura, altura e pixels RGB de um PNG gerado pelo módulo (filtro 0 em todas as linhas)."""
    blocos = blocos_png(dados)
    if blocos[0][0] != b"IHDR" or blocos[-1] != (b"IEND", b""):
        raise AssertionError("IHDR deve vir primeiro e IEND por último")
    largura, altura, bits, tipo_cor, compressao, filtro, entrelace = struct.unpack(">IIBBBBB", blocos[0][1])
    if (bits, tipo_cor, compressao, filtro, entrelace) != (8, 2, 0, 0, 0):
        raise AssertionError("esperado RGB de 8 bits sem entrelaçamento")
    bruto = zlib.decompress(b"".join(corpo for tipo, corpo in blocos if tipo == b"IDAT"))
    passo = 1 + 3 * largura
    if len(bruto) != passo * altura:
        raise AssertionError("tamanho dos dados descomprimidos incompatível")
    linhas = [bruto[i * passo:(i + 1) * passo] for i in range(altura)]
    if any(linha[0] != 0 for linha in linhas):
        raise AssertionError("filtro de linha diferente de 0")
    return largura, altura, b"".join(linha[1:] for linha in linhas)


def pixel(pixels: bytes, largura: int, x: int, y: int) -> tuple[int, int, int]:
    i = 3 * (y * largura + x)
    return tuple(pixels[i:i + 3])


class PngTest(unittest.TestCase):
    LARGURA, ALTURA = 300, 158

    @classmethod
    def setUpClass(cls) -> None:
        cls.pixels = paisagem.rasterizar(cls.LARGURA, cls.ALTURA)

    def assertCorProxima(self, obtida: tuple[int, int, int], cor: str, tolerancia: int = 8) -> None:
        esperada = paisagem._rgb(cor)
        self.assertTrue(all(abs(a - b) <= tolerancia for a, b in zip(obtida, esperada)), f"{obtida} longe de {cor}")

    def test_deterministico_e_tamanho(self) -> None:
        self.assertEqual(len(self.pixels), 3 * self.LARGURA * self.ALTURA)
        self.assertEqual(paisagem.rasterizar(self.LARGURA, self.ALTURA), self.pixels)

    def test_pixels_conhecidos(self) -> None:
        # Topo do céu, longe da marca.
        self.assertCorProxima(pixel(self.pixels, self.LARGURA, self.LARGURA // 2, 0), "#0B2A3F")
        # Centro do sol poente.
        escala, ox, oy = paisagem.escala_quadro(self.LARGURA, self.ALTURA)
        cx, cy, _ = paisagem.SOL_POENTE
        self.assertCorProxima(pixel(self.pixels, self.LARGURA, int(ox + cx * escala), int(oy + cy * escala)),
                              "#F2B544")
        # Última linha: orla, a camada mais escura.
        self.assertCorProxima(pixel(self.pixels, self.LARGURA, self.LARGURA // 2, self.ALTURA - 1), "#0E1B26")
        # Interior do sol da marca, no canto superior esquerdo.
        tamanho = self.ALTURA * paisagem.TAMANHO_MARCA / paisagem.LADO
        margem = self.ALTURA * paisagem.MARGEM_MARCA
        self.assertCorProxima(pixel(self.pixels, self.LARGURA, int(margem + 32 * tamanho), int(margem + 20 * tamanho)),
                              "#F2B544")

    def test_png_pequeno_valido(self) -> None:
        dados = paisagem.png(self.LARGURA, self.ALTURA, self.pixels)
        self.assertEqual([tipo for tipo, _ in blocos_png(dados)], [b"IHDR", b"IDAT", b"IEND"])
        self.assertEqual(pixels_png(dados), (self.LARGURA, self.ALTURA, self.pixels))
        with self.assertRaises(ValueError):
            paisagem.png(2, 2, b"\x00" * 11)

    def test_poligono_com_dois_pontos_falha(self) -> None:
        linhas = [bytearray(12) for _ in range(4)]
        with self.assertRaises(ValueError):
            paisagem.preencher(linhas, 4, 4, [[(0, 0), (3, 3)]], (255, 255, 255))

    def test_recorte_ao_quadro(self) -> None:
        largura, altura = 20, 10
        linhas = [bytearray(3 * largura) for _ in range(altura)]
        paisagem.preencher(linhas, largura, altura, [[(-30, -40), (60, 5), (-10, 50)]], (255, 255, 255))
        self.assertEqual(len(linhas), altura)
        self.assertTrue(all(len(linha) == 3 * largura for linha in linhas))
        self.assertEqual(bytes(linhas[5]), b"\xff" * (3 * largura))
        # Totalmente fora do quadro, por qualquer lado: nada muda.
        linhas = [bytearray(3 * largura) for _ in range(altura)]
        fora = [[(-10, 0), (-5, 0), (-5, 9)], [(30, 0), (40, 0), (40, 9)], [(0, -9), (20, -9), (10, -1)],
                [(0, 12), (20, 12), (10, 30)]]
        paisagem.preencher(linhas, largura, altura, fora, (255, 255, 255))
        self.assertTrue(all(linha == bytearray(3 * largura) for linha in linhas))

    def test_cobertura_horizontal_exata(self) -> None:
        largura, altura = 5, 5
        linhas = [bytearray(3 * largura) for _ in range(altura)]
        paisagem.preencher(linhas, largura, altura, [[(1.5, 0), (3.5, 0), (3.5, 4), (1.5, 4)]], (255, 255, 255))
        for y in range(4):
            self.assertEqual([linhas[y][3 * x] for x in range(largura)], [0, 128, 255, 128, 0])
        self.assertEqual(linhas[4], bytearray(3 * largura))

    def test_uniao_sem_cancelamento(self) -> None:
        """Polígonos sobrepostos em sentidos opostos continuam pintados (união pela regra nonzero)."""
        largura, altura = 6, 4
        linhas = [bytearray(3 * largura) for _ in range(altura)]
        horario = [(0, 0), (4, 0), (4, 4), (0, 4)]
        paisagem.preencher(linhas, largura, altura, [horario, list(reversed([(2, 0), (6, 0), (6, 4), (2, 4)]))],
                           (255, 255, 255))
        self.assertTrue(all(linha == bytearray(b"\xff" * (3 * largura)) for linha in linhas))


class PngCompletoLentoTest(unittest.TestCase):
    """Gera a imagem 1200×630 inteira: o teste mais lento do módulo, sem pular."""

    def test_og_versionado_igual_a_geracao(self) -> None:
        """Mudou a paisagem ou a marca? Rode `python -m coletor.paisagem --og`."""
        inicio = time.perf_counter()
        gerado = paisagem.og_png()
        print(f"og_png: {time.perf_counter() - inicio:.1f} s", file=sys.stderr)
        largura, altura, pixels = pixels_png(gerado)
        self.assertEqual((largura, altura), (1200, 630))
        versionado = pixels_png((RAIZ / "site_src" / "og-radar.png").read_bytes())
        # Bytes do zlib podem variar entre versões; os pixels não.
        self.assertEqual(versionado[:2], (1200, 630))
        self.assertTrue(versionado[2] == pixels, "pixels de site_src/og-radar.png diferem da geração")


if __name__ == "__main__":
    unittest.main()
