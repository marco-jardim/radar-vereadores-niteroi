"""Acessibilidade do HTML: aninhamento válido, abas do placar, coautores e gráficos com links.

Os testes de unidade chamam os renderizadores diretamente, sem site/. A varredura de site/ reusa a saída
existente, sem gerá-la, e é pulada se ela estiver ausente ou mais antiga que os fontes do gerador.
"""
from __future__ import annotations

import unittest
from html.parser import HTMLParser
from pathlib import Path

from coletor import gerar_site
from coletor.site import graficos as G
from coletor.site import paginas as P
from tests.test_documentos_site import montar

RAIZ = Path(__file__).resolve().parents[1]
VAZIOS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
CAMPOS = {"input", "select", "textarea"}


def interativo(tag: str, attrs: dict) -> bool:
    return (tag == "a" and "href" in attrs) or tag in {"button", "select", "textarea"} or (
        tag == "input" and attrs.get("type") != "hidden")


class Arvore(HTMLParser):
    """Acompanha os ancestrais de cada elemento e registra violações de aninhamento e das abas."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pilha: list[tuple[str, dict]] = []
        self.problemas: list[str] = []
        self.ids: dict[str, dict] = {}
        self.abas: list[dict] = []
        self.paineis: list[dict] = []
        self.listas_abas: list[dict] = []
        self.titulos_legislatura = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.verificar(tag, dict(attrs))
        if tag not in VAZIOS:
            self.pilha.append((tag, dict(attrs)))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.verificar(tag, dict(attrs))

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self.pilha) - 1, -1, -1):
            if self.pilha[i][0] == tag:
                del self.pilha[i:]
                return

    def verificar(self, tag: str, a: dict) -> None:
        ancestrais = [t for t, _ in self.pilha]
        descricao = f"<{tag} {a}>"
        if tag in {"details", "div"} and "p" in ancestrais:
            self.problemas.append(f"{descricao} dentro de <p>")
        if interativo(tag, a) and any(interativo(t, at) for t, at in self.pilha):
            self.problemas.append(f"{descricao} interativo dentro de interativo")
        focavel = interativo(tag, a) or tag in CAMPOS or "tabindex" in a
        if focavel and any(at.get("role") == "img" for _, at in self.pilha):
            self.problemas.append(f"{descricao} focável dentro de role=img")
        if a.get("id"):
            self.ids[a["id"]] = {"tag": tag, **a}
        if a.get("role") == "tab":
            self.abas.append(a)
        if a.get("role") == "tablist":
            self.listas_abas.append(a)
        if tag == "section" and "legislatura" in (a.get("class") or "").split():
            self.paineis.append(a)
            if "hidden" in a:
                self.problemas.append(f"{descricao} painel do placar oculto no HTML do servidor")
            if any(chave in a for chave in ("role", "tabindex", "aria-labelledby")):
                self.problemas.append(f"{descricao} painel do placar com semântica de aba antes do JS")
        if tag == "h3" and "titulo-legislatura" in (a.get("class") or "").split():
            self.titulos_legislatura += 1

    def concluir(self) -> list[str]:
        self.close()
        for aba in self.abas:
            alvo = self.ids.get(aba.get("aria-controls") or "")
            if not alvo:
                self.problemas.append(f"aba {aba} sem aria-controls para um painel existente")
        return self.problemas


def analisar(html: str) -> Arvore:
    arvore = Arvore()
    arvore.feed(html)
    arvore.concluir()
    return arvore


def autor(nome: str, slug: str = "", vereador: bool = False) -> dict:
    return {"nome": nome.upper(), "papel": "", "slug": slug, "vereador": vereador, "pagina": bool(slug), "exibicao": nome}


# --------------------------------------------------------------- unidades
class TestPlacarSemJS(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.modelo = montar()
        cls.html = P.gerar_index(cls.modelo)
        cls.arvore = analisar(cls.html)

    def test_todos_os_paineis_visiveis_e_empilhados_com_titulo(self):
        legs = [leg["id"] for leg in self.modelo["legislaturas"]]
        self.assertEqual(len(self.arvore.paineis), len(legs))
        for painel in self.arvore.paineis:
            with self.subTest(painel=painel["id"]):
                self.assertNotIn("hidden", painel)
                self.assertNotIn("role", painel)
                self.assertNotIn("tabindex", painel)
                self.assertNotIn("aria-labelledby", painel)
        self.assertEqual(self.arvore.titulos_legislatura, len(legs))
        self.assertIn('<h3 class="titulo-legislatura">Legislatura 2025–2028</h3>', self.html)
        self.assertEqual(self.arvore.problemas, [])

    def test_lista_de_abas_oculta_sem_js_e_tabindex_movel(self):
        self.assertEqual(len(self.arvore.listas_abas), 1)
        self.assertIn("hidden", self.arvore.listas_abas[0])
        self.assertEqual(self.arvore.listas_abas[0]["aria-label"], "Legislatura")
        selecionadas = [a for a in self.arvore.abas if a["aria-selected"] == "true"]
        self.assertEqual([a["aria-controls"] for a in selecionadas], ["leg-2025-2028"])
        for aba in self.arvore.abas:
            with self.subTest(aba=aba["id"]):
                self.assertEqual(aba["tabindex"], "0" if aba["aria-selected"] == "true" else "-1")
                self.assertEqual(aba["id"], "aba-" + aba["aria-controls"])

    def test_auxiliares_das_abas(self):
        self.assertEqual(P.aba_legislatura("2021-2024", False),
                         '<button type="button" role="tab" id="aba-leg-2021-2024" aria-selected="false" '
                         'aria-controls="leg-2021-2024" tabindex="-1">2021-2024</button>')
        painel = P.painel_legislatura("2021-2024", "<ol class=\"placar\"></ol>")
        self.assertTrue(painel.startswith('<section class="legislatura" id="leg-2021-2024" data-leg="2021-2024">'))
        self.assertNotIn("hidden", painel)
        self.assertIn(" hidden>", P.lista_abas_legislatura([P.aba_legislatura("2021-2024", True)]))


class TestCoautores(unittest.TestCase):
    def projeto(self, n: int) -> dict:
        principal = autor("Daniel Marques", "daniel-marques-frederico", True)
        outros = [autor("Cal")] if n == 1 else [autor(f"Pessoa {i}") for i in range(n)]
        return {"autores": [principal, *outros], "principal": "daniel-marques-frederico"}

    def test_um_e_trinta_coautores_em_details(self):
        um = P.autores_html(self.projeto(1), "")
        # Mesmo literal conferido em tests/js/interacoes.test.js (listaCoautores em app.js).
        self.assertIn('<details class="coautores"><summary>e 1 coautor</summary><ul><li>Cal</li></ul></details>', um)
        self.assertNotIn("title=", um)
        trinta = P.autores_html(self.projeto(30), "")
        self.assertIn("<summary>e 30 coautores</summary>", trinta)
        self.assertEqual(trinta.count("<li>"), 30)
        self.assertIn("<li>Pessoa 29</li>", trinta)

    def test_nomes_escapados(self):
        p = {"autores": [autor("Ana", "ana", True), autor("<b>&Cia</b>")], "principal": "ana"}
        html = P.autores_html(p, "")
        self.assertIn("<li>&lt;b&gt;&amp;Cia&lt;/b&gt;</li>", html)
        self.assertNotIn("<b>", html)

    def test_documentos_usam_o_mesmo_details(self):
        html = P.autores_documento_html({"autores": [autor(f"Pessoa {i}") for i in range(5)]}, "")
        self.assertIn('<details class="coautores"><summary>e mais 2 autores</summary><ul><li>Pessoa 3</li>'
                      '<li>Pessoa 4</li></ul></details>', html)
        self.assertNotIn("title=", html)

    def test_itens_usam_div_sem_details_dentro_de_p(self):
        modelo = montar()
        p = dict(modelo["projetos"][0])
        p["autores"] = [*p["autores"], autor("Cal"), autor("Bia")]
        d = dict(modelo["documentos"][0])
        d["autores"] = [*d["autores"], *[autor(f"Pessoa {i}") for i in range(4)]]
        for nome, html in (("projeto", P.item_projeto(p, "")), ("documento", P.item_documento(d, "../"))):
            with self.subTest(item=nome):
                self.assertIn('<div class="autoria">', html)
                self.assertNotIn('<p class="autoria">', html)
                self.assertIn('<details class="coautores">', html)
                self.assertEqual(analisar(html).problemas, [])


class TestGraficosComLinks(unittest.TestCase):
    def test_svg_com_links_vira_grupo_e_sem_links_continua_imagem(self):
        com_link = G.dispersao("Volume", "", [{"rotulo": "Ana", "x": 3, "y": 1, "link": "vereadores/ana.html"}], "PLs", "Leis")
        self.assertIn('<svg role="group" aria-label="Volume"', com_link)
        self.assertEqual(analisar(com_link).problemas, [])
        sem_link = G.dispersao("Volume", "", [{"rotulo": "Ana", "x": 3, "y": 1}], "PLs", "Leis")
        self.assertIn('<svg role="img" aria-label="Volume"', sem_link)
        # As marcas nunca recebem tabindex (só a região rolável da tabela tem tabindex="0").
        self.assertNotRegex(com_link + sem_link, r"<(?:circle|rect|path|i)\b[^>]*tabindex")

    def test_detector_aponta_violacoes(self):
        ruins = ('<p><details><summary>x</summary></details></p>', '<a href="#"><button>x</button></a>',
                 '<svg role="img"><a href="#"><circle/></a></svg>', '<div role="img"><i tabindex="0"></i></div>',
                 '<button role="tab" aria-controls="nada">x</button>')
        for html in ruins:
            with self.subTest(html=html):
                self.assertTrue(analisar(html).problemas)


# ---------------------------------------------------------- site/ existente
def fontes_do_gerador() -> list[Path]:
    return [p for pasta in ("coletor", "config", "site_src")
            for p in (RAIZ / pasta).rglob("*") if p.is_file()]


class TestSiteGerado(unittest.TestCase):
    def paginas(self) -> list[Path]:
        saida = gerar_site.SAIDA
        paginas = sorted(saida.rglob("*.html")) if saida.is_dir() else []
        if not paginas:
            self.skipTest("site/ ausente; rode python -m coletor.gerar_site para a varredura de acessibilidade")
        recente = max(f.stat().st_mtime_ns for f in fontes_do_gerador())
        if any(pagina.stat().st_mtime_ns <= recente for pagina in paginas):
            self.skipTest("site/ mais antigo que coletor/, config/ ou site_src/; rode python -m coletor.gerar_site")
        return paginas

    def test_aninhamento_abas_e_paineis(self):
        for pagina in self.paginas():
            with self.subTest(pagina=str(pagina.relative_to(gerar_site.SAIDA))):
                problemas = analisar(pagina.read_text(encoding="utf-8")).problemas
                self.assertEqual(problemas, [], "\n".join(problemas[:10]))


if __name__ == "__main__":
    unittest.main()
