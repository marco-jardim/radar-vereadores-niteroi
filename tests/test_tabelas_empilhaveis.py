"""Tabelas empilháveis: classes empilha/col-N, papéis ARIA explícitos e data-label igual ao cabeçalho da coluna.

Em contêiner estreito, o CSS transforma as linhas em cartões e usa data-label como rótulo de cada célula; os papéis
preservam a semântica de tabela quando o display das partes muda. Offline, sem gerar o site.
"""
from __future__ import annotations

import re
import unittest
from html import unescape
from html.parser import HTMLParser
from xml.etree import ElementTree

from coletor.site import graficos as G
from coletor.site import pagina_sessoes as S
from coletor.site import paginas as P
from tests.test_design_tokens import declaracoes as ler_declaracoes
from tests.test_design_tokens import regras
from tests.test_geo import geo_completo
from tests.test_pagina_sessoes import modelo_sintetico

PAPEIS = re.compile(r' (?:role="(?:table|rowgroup|row|columnheader|rowheader|cell)"|data-label="[^"]*")')


def sem_empilhamento(texto: str) -> str:
    """Remove os papéis das partes da tabela e data-label, para comparar só conteúdo e ordem das células.

    role="region" dos contêineres fica intacto.
    """
    return PAPEIS.sub("", texto)


class Tabelas(HTMLParser):
    """Cabeçalhos, linhas e células de cada <table>, com atributos e texto (entidades já convertidas)."""

    def __init__(self, texto: str):
        super().__init__(convert_charrefs=True)
        self.tabelas: list[dict] = []
        self.dentro = False
        self.secao = None
        self.celula = None
        self.feed(texto)
        self.close()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            self.dentro = True
            self.tabelas.append({"attrs": a, "secoes": [], "tr_cab": None, "cabecalhos": [], "linhas": []})
            return
        if not self.dentro:
            return
        tabela = self.tabelas[-1]
        if tag in ("thead", "tbody"):
            self.secao = tag
            tabela["secoes"].append((tag, a))
        elif tag == "tr":
            if self.secao == "tbody":
                tabela["linhas"].append({"attrs": a, "celulas": []})
            else:
                tabela["tr_cab"] = a
        elif tag in ("th", "td"):
            self.celula = {"tag": tag, "attrs": a, "texto": []}
            if self.secao == "thead":
                tabela["cabecalhos"].append(self.celula)
            else:
                tabela["linhas"][-1]["celulas"].append(self.celula)

    def handle_endtag(self, tag):
        if tag in ("th", "td"):
            self.celula = None
        elif tag in ("thead", "tbody"):
            self.secao = None
        elif tag == "table":
            self.dentro = False

    def handle_data(self, data):
        if self.celula is not None:
            self.celula["texto"].append(data)

    @staticmethod
    def texto(celula: dict) -> str:
        return " ".join("".join(celula["texto"]).split())


class ContratoEmpilhavel(unittest.TestCase):
    def conferir_empilhamento(self, texto: str) -> Tabelas:
        """Toda tabela: empilha + col-N, papéis ARIA e rótulo em toda célula do corpo.

        O rótulo é o texto do cabeçalho da coluna; no mapa de votos (faixa), a referência curta da votação.
        Sem subTest próprio: as falhas se propagam (quem chama pode envolver cada página num subTest).
        """
        doc = Tabelas(texto)
        for i, tabela in enumerate(doc.tabelas):
            classes = (tabela["attrs"].get("class") or "").split()
            onde = f"tabela {i} ({' '.join(classes)}; cabeçalhos {[Tabelas.texto(c) for c in tabela['cabecalhos']][:3]})"
            colunas = len(tabela["cabecalhos"])
            self.assertIn("empilha", classes, onde)
            self.assertEqual([c for c in classes if c.startswith("col-")], [f"col-{colunas}"], onde)
            self.assertEqual(tabela["attrs"].get("role"), "table", onde)
            self.assertEqual([(s, a.get("role")) for s, a in tabela["secoes"]], [("thead", "rowgroup"), ("tbody", "rowgroup")], onde)
            self.assertEqual((tabela["tr_cab"] or {}).get("role"), "row", onde)
            for cab in tabela["cabecalhos"]:
                self.assertEqual((cab["tag"], cab["attrs"].get("scope"), cab["attrs"].get("role")),
                                 ("th", "col", "columnheader"), onde)
            faixa = "faixa" in classes
            rotulos = [Tabelas.texto(c) for c in tabela["cabecalhos"]]
            for linha in tabela["linhas"]:
                self.assertEqual(linha["attrs"].get("role"), "row", onde)
                celulas = linha["celulas"]
                self.assertEqual(len(celulas), colunas, onde)
                titulo = celulas[0]
                self.assertEqual((titulo["tag"], titulo["attrs"].get("scope"), titulo["attrs"].get("role")),
                                 ("th", "row", "rowheader"), onde)
                self.assertEqual(titulo["attrs"].get("data-label"), rotulos[0], onde)
                for celula, rotulo in zip(celulas[1:], rotulos[1:]):
                    self.assertEqual((celula["tag"], celula["attrs"].get("role")), ("td", "cell"), onde)
                    self.assertTrue(celula["attrs"].get("data-label"), f"Célula sem data-label: {onde}")
                    if not faixa:
                        self.assertEqual(celula["attrs"]["data-label"], rotulo, onde)
        return doc


class TestConstrutores(ContratoEmpilhavel):
    def test_alternativas_dos_graficos(self):
        titulo = 'Produção <anual> & "total"'
        exemplos = {
            "tabela": G.tabela(["Ano", 'Leis "com efeito"', "Total"], [["2026", 3, 1000]], titulo),
            "colunas": G.colunas_empilhadas(titulo, "", ["2025", "2026"], [("PLs", "c-efeito", [3, 4]), ("Leis", "c-lei", [1, 2])]),
            "linhas": G.linhas(titulo, "", ["2026"], [("PLs", "c-efeito", [3])]),
            "barras": G.barras_horizontais(titulo, "", [{"rotulo": "Ana & Bia", "total": 3}], [("PLs", "c-efeito", "total")]),
            "dispersao": G.dispersao(titulo, "", [{"rotulo": "Ana", "x": 3, "y": 1}], "PLs", "Leis"),
        }
        colunas = {"tabela": 3, "colunas": 4, "linhas": 2, "barras": 2, "dispersao": 3}
        for nome, texto in exemplos.items():
            with self.subTest(grafico=nome):
                doc = self.conferir_empilhamento(texto)
                self.assertEqual(len(doc.tabelas), 1)
                self.assertIn(f"col-{colunas[nome]}", doc.tabelas[0]["attrs"]["class"].split())
        self.assertIn('<td role="cell" data-label="Leis &quot;com efeito&quot;">3</td>', exemplos["tabela"])
        self.assertIn('<td role="cell" data-label="Total">1.000</td>', exemplos["tabela"])
        self.assertIn('<th scope="row" role="rowheader" data-label="Ano">2026</th>', exemplos["tabela"])
        self.assertIn('<th scope="row" role="rowheader" data-label="">Ana &amp; Bia</th>', exemplos["barras"])

    def test_tabela_resumo_com_colunas_de_texto(self):
        texto = P.tabela_resumo("Resumo", ["Órgão", "Pedidos", 'Taxa "média" & <total>'],
                                [['<a href="x.html">NitTrans</a>', 2, "50%"], ["Outro", None, "—"]], texto=(2,))
        doc = self.conferir_empilhamento(texto)
        self.assertEqual(doc.tabelas[0]["attrs"]["class"], "empilha col-3")
        self.assertIn('<th scope="col" role="columnheader" class="txt">Taxa &quot;média&quot; &amp; &lt;total&gt;</th>', texto)
        self.assertIn('<td role="cell" data-label="Taxa &quot;média&quot; &amp; &lt;total&gt;" class="txt">50%</td>', texto)
        self.assertIn('<th scope="row" role="rowheader" data-label="Órgão"><a href="x.html">NitTrans</a></th>', texto)
        self.assertIn('<td role="cell" data-label="Pedidos">—</td>', texto)
        self.assertIn('<table class="empilha col-3" role="table"><caption>Resumo</caption><thead role="rowgroup">', texto)

    def test_grafico_de_sessoes_recebe_caption_e_rotulo_do_eixo(self):
        texto = S._grafico("Placares por ano", "", ["2025", "2026"], [("Unânime", "s-presente", [1, 2])], "Ano")
        self.conferir_empilhamento(texto)
        # Ano, a série e Total.
        self.assertIn('<table class="empilha col-3" role="table"><caption>Placares por ano</caption>', texto)
        self.assertIn('<th scope="col" role="columnheader">Ano</th>', texto)
        self.assertIn('<th scope="row" role="rowheader" data-label="Ano">2025</th>', texto)
        self.assertNotIn('data-label=""', texto)

    def test_mapa_de_votos_rotula_cada_celula_com_a_referencia_curta(self):
        modelo = modelo_sintetico()
        dados = modelo["sessoes"]
        leg = dados["legislaturas"][1]
        texto = S._mapa_votos(modelo, dados, leg)
        doc = self.conferir_empilhamento(texto)
        faixa, resumo = doc.tabelas
        self.assertEqual(faixa["attrs"]["class"].split()[:2], ["faixa", "empilha"])
        self.assertEqual(resumo["attrs"]["class"], "empilha col-5")
        tabela = re.search(r'<table class="faixa[^"]*".*?</table>', texto, re.S).group()
        referencias = [f"{unescape(d)} {unescape(c)}" for d, c in re.findall(r'<abbr title="[^"]*">([^<]*)</abbr><br>([^<*]*)', tabela)]
        self.assertEqual(len(referencias), len(faixa["cabecalhos"]) - 1)
        self.assertTrue(all(re.fullmatch(r"\d\d/\d\d \S.*", r) for r in referencias), referencias)
        self.assertTrue(faixa["linhas"])
        for linha in faixa["linhas"]:
            self.assertEqual(linha["celulas"][0]["attrs"]["data-label"], "Vereador")
            self.assertEqual([c["attrs"]["data-label"] for c in linha["celulas"][1:]], referencias)
        rotulos_resumo = [c["attrs"]["data-label"] for c in resumo["linhas"][0]["celulas"]]
        self.assertEqual(rotulos_resumo, ["Vereador", "Com a maioria", "Diferente da maioria", "Abstenção", "Ausente"])

    def test_faixa_larga_acima_de_12_colunas_e_rotulo_neutro(self):
        self.assertEqual(S._classe_faixa(S.FAIXA_LARGA), "faixa")
        self.assertEqual(S._classe_faixa(S.FAIXA_LARGA + 1), "faixa faixa-larga")
        # 25 divididas no ano mais recente: 26 colunas.
        modelo = modelo_sintetico(600, 150)
        dados = modelo["sessoes"]
        texto = S._mapa_votos(modelo, dados, dados["legislaturas"][1])
        self.assertIn('<table class="faixa faixa-larga empilha col-26" role="table">', texto)
        self.assertEqual(self.conferir_empilhamento(texto).tabelas[0]["attrs"]["class"], "faixa faixa-larga empilha col-26")
        self.assertIn('aria-label="Mapa de votos de 2026, legislatura 2025–2028: vereador × votação dividida"', texto)
        self.assertFalse(any("rolagem" in r for r in re.findall(r'aria-label="([^"]*)"', texto)))
        # Poucas votações: sem faixa-larga, a matriz cabe no desktop.
        pequeno = modelo_sintetico()
        self.assertNotIn("faixa-larga", S._mapa_votos(pequeno, pequeno["sessoes"], pequeno["sessoes"]["legislaturas"][1]))

    def test_mapa_de_bairros_continua_xml_valido_e_rotulado(self):
        titulo = 'Indicações por bairro & "região"'
        texto = G.mapa_coropletico({"Icaraí": 7}, geo_completo(), titulo)
        raiz = ElementTree.fromstring(texto)
        tabela = raiz.find(".//table")
        self.assertEqual((tabela.get("class"), tabela.get("role")), ("empilha col-3", "table"))
        titulos = raiz.findall(".//tbody/tr/th")
        self.assertEqual(len(titulos), 52)
        self.assertTrue(all(t.get("data-label") == "Bairro" and t.get("role") == "rowheader" for t in titulos))
        celulas = raiz.findall(".//tbody/tr/td")
        self.assertEqual(len(celulas), 104)
        self.assertEqual({c.get("data-label") for c in celulas}, {"Região", "Indicações"})
        self.conferir_empilhamento(texto)

    def test_remocao_dos_papeis_preserva_regioes(self):
        texto = P.tabela_resumo("Resumo", ["Ano", "Total"], [["2026", 3]])
        self.assertEqual(sem_empilhamento(texto),
                         '<div class="tabela-graf tabela-resumo" role="region" tabindex="0" aria-label="Resumo">'
                         '<table class="empilha col-2"><caption>Resumo</caption><thead><tr><th scope="col">Ano</th>'
                         '<th scope="col">Total</th></tr></thead><tbody><tr><th scope="row">2026</th><td>3</td></tr>'
                         '</tbody></table></div>')

    def test_conferencia_rejeita_tabela_sem_rotulo(self):
        texto = P.tabela_resumo("Resumo", ["Ano", "Total"], [[2026, 3]]).replace(' data-label="Total"', "")
        with self.assertRaises(AssertionError):
            self.conferir_empilhamento(texto)


class TestCSSEmpilhamento(unittest.TestCase):
    """Limiares por número de colunas em container queries; rolagem só como alternativa sem elas."""

    @classmethod
    def setUpClass(cls):
        cls.css = (P.FONTE_ESTATICA / "estilo.css").read_text(encoding="utf-8")
        cls.regras = regras(cls.css)

    def test_conteineres_e_limiares(self):
        self.assertTrue(any({".tabela-rolavel", ".tabela-resumo", ".sessoes .faixa-rolagem"} <= set(map(str.strip, lista.split(",")))
                            and ler_declaracoes(corpo).get("container-type") == "inline-size"
                            for _, lista, corpo in self.regras))
        consultas = [(contexto, lista) for contexto, lista, _ in self.regras if any(c.startswith("@container") for c in contexto)]
        self.assertTrue(consultas)
        for n in range(3, 9):
            with self.subTest(colunas=n):
                self.assertTrue(any(f".col-{n}" in lista for _, lista in consultas))
        # Nove ou mais colunas, exceto o mapa de votos, que tem limiares e regras próprias de cartão.
        self.assertTrue(any(".empilha:not(.col-1, .col-2, .col-3, .col-4, .col-5, .col-6, .col-7, .col-8, .faixa)" in lista
                            for _, lista in consultas))

    def test_mapa_de_votos_empilha_em_56rem_ou_100rem_com_faixa_larga(self):
        def contextos(seletor: str) -> list[tuple[str, ...]]:
            return [contexto for contexto, lista, _ in self.regras if lista == seletor]

        self.assertEqual(contextos(".sessoes .faixa.empilha tr"), [("@container (max-width: 56rem)",)])
        self.assertEqual(contextos(".sessoes .faixa.faixa-larga tr"), [("@container (max-width: 100rem)",)])
        # A matriz larga (fora das container queries) continua com a primeira coluna fixa.
        self.assertRegex(self.css, r"\.sessoes \.faixa tr > :first-child\s*\{[^}]*position:\s*sticky;[^}]*left:\s*0")
        for classe, limite in (("empilha", "56rem"), ("faixa-larga", "100rem")):
            with self.subTest(classe=classe):
                # Ladrilhos vazios (fora do mandato/não consta) somem só no cartão.
                vazio = [(contexto, ler_declaracoes(corpo)) for contexto, lista, corpo in self.regras
                         if lista == f".sessoes .faixa.{classe} td.voto-vazio"]
                self.assertEqual(vazio, [((f"@container (max-width: {limite})",), {"display": "none"})])
        self.assertFalse(any("voto-vazio" in lista and ler_declaracoes(corpo).get("display") == "none"
                             for contexto, lista, corpo in self.regras if not contexto))

    def test_cartoes_mantem_cabecalho_acessivel_e_rotulo(self):
        for contexto, lista, corpo in self.regras:
            if not any(c.startswith("@container") for c in contexto):
                continue
            propriedades = ler_declaracoes(corpo)
            if "thead" in lista:
                with self.subTest(seletor=lista):
                    self.assertNotEqual(propriedades.get("display"), "none")
                    self.assertEqual(propriedades.get("position"), "absolute")
            if lista.endswith("td::before"):
                with self.subTest(seletor=lista):
                    self.assertEqual(propriedades.get("content"), "attr(data-label)")


if __name__ == "__main__":
    unittest.main()
