"""Regiões de rolagem das tabelas, inclusive nas páginas completas geradas offline."""
from __future__ import annotations

import unittest
from html.parser import HTMLParser
from xml.etree import ElementTree

from coletor.site import graficos as G
from coletor.site import paginas as P
from tests.test_geo import geo_completo


class TabelasHTML(HTMLParser):
    """Guarda ancestrais das tabelas e texto dos ids para resolver aria-labelledby."""

    VAZIOS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
              "meta", "param", "source", "track", "wbr"}

    def __init__(self, texto: str):
        super().__init__(convert_charrefs=True)
        self.pilha = []
        self.ids = {}
        self.tabelas = []
        self.regioes = []
        self.feed(texto)
        self.close()

    def handle_starttag(self, tag, attrs):
        no = {"tag": tag, "attrs": dict(attrs), "texto": []}
        if no["attrs"].get("role") == "region":
            self.regioes.append(no)
        if tag == "table":
            self.tabelas.append(tuple(self.pilha))
        if "id" in no["attrs"]:
            self.ids[no["attrs"]["id"]] = no
        if tag not in self.VAZIOS:
            self.pilha.append(no)

    def handle_endtag(self, tag):
        for i in range(len(self.pilha) - 1, -1, -1):
            if self.pilha[i]["tag"] == tag:
                del self.pilha[i:]
                break

    def handle_data(self, data):
        for no in self.pilha:
            if "id" in no["attrs"]:
                no["texto"].append(data)

    def rotulo(self, attrs):
        if "aria-labelledby" in attrs:
            ids = attrs["aria-labelledby"].split()
            if not ids or any(i not in self.ids for i in ids):
                return ""
            return " ".join("".join(self.ids[i]["texto"]) for i in ids).strip()
        return attrs.get("aria-label", "").strip()


class ContratoTabelas(unittest.TestCase):
    def conferir_tabelas(self, texto: str) -> TabelasHTML:
        doc = TabelasHTML(texto)
        for i, ancestrais in enumerate(doc.tabelas):
            with self.subTest(tabela=i):
                regioes = [no for no in ancestrais if set(no["attrs"].get("class", "").split())
                           & {"tabela-rolavel", "tabela-resumo", "faixa-rolagem"}]
                self.assertTrue(regioes, "Tabela sem ancestral de rolagem")
                regiao = regioes[-1]
                self.assertEqual(regiao["attrs"].get("role"), "region")
                self.assertEqual(regiao["attrs"].get("tabindex"), "0")
                self.assertTrue(doc.rotulo(regiao["attrs"]), "Região sem rótulo acessível")
        rotulos = [" ".join(doc.rotulo(no["attrs"]).split()).casefold() for no in doc.regioes]
        self.assertEqual(len(rotulos), len(set(rotulos)), "Rótulos de região repetidos na mesma página")
        return doc


class TestAlternativasGraficos(ContratoTabelas):
    def test_tabela_fica_dentro_da_regiao_e_fora_do_summary(self):
        texto = G.tabela(["Ano", "Total"], [[2026, 3]], "Produção anual")
        doc = self.conferir_tabelas(texto)
        self.assertEqual(len(doc.tabelas), 1)
        self.assertEqual([no["tag"] for no in doc.tabelas[0]], ["details", "div"])
        self.assertEqual(doc.tabelas[0][-1]["attrs"]["class"], "tabela-rolavel")
        self.assertEqual(doc.tabelas[0][-1]["attrs"]["aria-label"], "Produção anual")
        self.assertIn("<table>", texto)  # pagina_sessoes._grafico insere o caption neste literal.
        with self.assertRaises(TypeError):
            G.tabela(["Total"], [[3]])

    def test_helpers_usam_titulo_escapado_sem_criar_ids(self):
        titulo = 'Produção <anual> & "total"'
        exemplos = {
            "colunas": G.colunas_empilhadas(titulo, "", ["2026"], [("PLs", "c-efeito", [3])]),
            "linhas": G.linhas(titulo, "", ["2026"], [("PLs", "c-efeito", [3])]),
            "barras": G.barras_horizontais(titulo, "", [{"rotulo": "Ana", "total": 3}],
                                            [("PLs", "c-efeito", "total")]),
            "dispersao": G.dispersao(titulo, "", [{"rotulo": "Ana", "x": 3, "y": 1}], "PLs", "Leis"),
        }
        for nome, texto in exemplos.items():
            with self.subTest(grafico=nome):
                doc = self.conferir_tabelas(texto)
                self.assertEqual(len(doc.tabelas), 1)
                self.assertEqual(doc.tabelas[0][-1]["attrs"]["aria-label"], titulo)
                self.assertEqual(doc.ids, {})
                self.assertNotIn("<anual>", texto)
                self.assertIn("<table>", texto)

    def test_mapa_inteiro_continua_xml_valido(self):
        titulo = 'Indicações por bairro & "região"'
        texto = G.mapa_coropletico({"Icaraí": 7}, geo_completo(), titulo)
        raiz = ElementTree.fromstring(texto)
        regioes = raiz.findall(".//div[@class='tabela-rolavel']")
        self.assertEqual(len(regioes), 1)
        self.assertEqual(regioes[0].get("aria-label"), titulo)
        self.assertIsNotNone(regioes[0].find("table"))
        self.assertEqual(len(raiz.findall(".//tbody/tr")), 52)
        self.conferir_tabelas(texto)

    def test_resumo_ja_rolavel_nao_recebe_segundo_wrapper(self):
        texto = P.tabela_resumo("Resumo", ["Ano", "Total"], [[2026, 3]])
        doc = self.conferir_tabelas(texto)
        self.assertEqual(len(doc.tabelas), 1)
        self.assertEqual(len(doc.tabelas[0]), 1)
        self.assertNotIn("tabela-rolavel", texto)

    def test_parser_resolve_rotulo_por_id_mesmo_depois_da_tabela(self):
        texto = ('<div class="tabela-rolavel" role="region" tabindex="0" aria-labelledby="titulo">'
                 '<table></table></div><h2 id="titulo">Dados <span>anuais</span></h2>')
        doc = self.conferir_tabelas(texto)
        self.assertEqual(doc.rotulo(doc.tabelas[0][-1]["attrs"]), "Dados anuais")
        self.assertEqual(TabelasHTML(texto).rotulo({"aria-labelledby": "inexistente"}), "")

    def test_rejeita_rotulos_repetidos_na_mesma_pagina(self):
        texto = G.tabela(["Total"], [[3]], "Produção anual")
        with self.assertRaisesRegex(AssertionError, "Rótulos de região repetidos"):
            self.conferir_tabelas(texto + texto)


if __name__ == "__main__":
    unittest.main()
