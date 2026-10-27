"""Emblemas próprios e máscara de azulejo: XML, cores herdadas e orçamento."""
from __future__ import annotations

import gzip
import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PASTA = RAIZ / "site_src" / "memoria"
NS = "{http://www.w3.org/2000/svg}"
CORES = {"currentColor", "var(--acento)", "none"}
ELEMENTOS = {"svg", "symbol", "g", "path", "circle", "ellipse", "rect", "line", "polyline", "polygon"}


class EmblemasTest(unittest.TestCase):
    def emblemas(self) -> list[Path]:
        return sorted(caminho for caminho in PASTA.glob("*.svg") if caminho.name != "azulejo.svg")

    def ler_svg(self, caminho: Path, limite: int) -> ET.Element:
        """Confere formato, tamanho e ausência de conteúdo ativo ou referências."""
        bruto = caminho.read_bytes()
        self.assertTrue(bruto.endswith(b"\n"))
        self.assertNotIn(b"\r", bruto)
        self.assertLessEqual(len(gzip.compress(bruto, compresslevel=9, mtime=0)), limite)
        raiz = ET.fromstring(bruto)
        self.assertEqual(raiz.tag, f"{NS}svg")
        self.assertTrue(raiz.get("viewBox"))
        for elemento in raiz.iter():
            self.assertIn(elemento.tag, {f"{NS}{nome}" for nome in ELEMENTOS})
            for atributo, valor in elemento.attrib.items():
                nome = atributo.rsplit("}", 1)[-1].lower()
                self.assertNotIn(nome, {"href", "style"})
                self.assertFalse(nome.startswith("on"), atributo)
                self.assertNotIn("url(", valor.lower())
        return raiz

    def test_arquivos_correspondem_a_configuracao(self) -> None:
        config = json.loads((RAIZ / "config" / "memoria.json").read_text(encoding="utf-8"))
        esperados = {pessoa["emblema"] for pessoa in config["homenageados"]}
        self.assertTrue(esperados)
        self.assertEqual({caminho.name for caminho in self.emblemas()}, esperados)

    def test_emblemas_xml_simbolos_cores_e_tamanho(self) -> None:
        caminhos = self.emblemas()
        config = json.loads((RAIZ / "config" / "memoria.json").read_text(encoding="utf-8"))
        self.assertEqual(len(caminhos), len(config["homenageados"]))
        for caminho in caminhos:
            with self.subTest(emblema=caminho.name):
                raiz = self.ler_svg(caminho, 6 * 1024)
                self.assertEqual(raiz.get("viewBox"), "0 0 96 96")
                self.assertEqual(len(raiz), 1)
                simbolo = raiz.find(f"{NS}symbol")
                self.assertIsNotNone(simbolo)
                self.assertEqual(simbolo.get("id"), "emblema")
                self.assertEqual(simbolo.get("viewBox"), "0 0 96 96")
                cores = set()
                for elemento in raiz.iter():
                    for atributo in ("fill", "stroke"):
                        if atributo in elemento.attrib:
                            cor = elemento.get(atributo)
                            self.assertIn(cor, CORES)
                            cores.add(cor)
                    if "stroke-width" in elemento.attrib:
                        self.assertIn(elemento.get("stroke-width"), {"3", "4"})
                self.assertTrue({"currentColor", "var(--acento)"}.issubset(cores))

    def test_azulejo_xml_mascara_preta_e_tamanho(self) -> None:
        raiz = self.ler_svg(PASTA / "azulejo.svg", 12 * 1024)
        self.assertEqual(raiz.get("viewBox"), "0 0 64 64")
        self.assertEqual(raiz.get("fill"), "#000")
        for elemento in raiz.iter():
            if "fill" in elemento.attrib:
                self.assertEqual(elemento.get("fill"), "#000")
            self.assertNotIn("stroke", elemento.attrib)


if __name__ == "__main__":
    unittest.main()
