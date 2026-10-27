"""Marca e favicon gerados por coletor.paisagem: XML, paleta, contraste e bytes versionados."""
from __future__ import annotations

import contextlib
import io
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

from coletor import paisagem

RAIZ = Path(__file__).resolve().parents[1]
NS = "{http://www.w3.org/2000/svg}"
PALETA = {"#F2B544", "#E8743B", "#13476B", "#9CC6E4", "#0B2A3F", "#E6EEF4", "#F7F2E9", "#0E1B26",
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
        for texto in (self.favicon, self.marca):
            cores = HEX.findall(texto)
            self.assertTrue(cores)
            for cor in cores:
                self.assertIn(cor.upper(), PALETA, cor)

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


class ArquivosVersionadosTest(unittest.TestCase):
    def test_site_src_igual_a_geracao(self) -> None:
        """Mudou a geometria? Rode `python -m coletor.paisagem --marca`."""
        for nome, texto in (("favicon.svg", paisagem.favicon_svg()), ("marca.svg", paisagem.marca_svg())):
            with self.subTest(nome=nome):
                self.assertEqual((RAIZ / "site_src" / nome).read_bytes(), texto.encode("utf-8"))


class CliTest(unittest.TestCase):
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

    def test_sem_opcao_nao_grava(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            saida = Path(tmp) / "site_src"
            with mock.patch.object(paisagem, "SAIDA", saida), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(paisagem.main([]), 2)
            self.assertFalse(saida.exists())


if __name__ == "__main__":
    unittest.main()
