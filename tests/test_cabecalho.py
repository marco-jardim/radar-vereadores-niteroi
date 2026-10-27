"""Cabeçalho comum: menu móvel com melhoria progressiva, sem rede nem navegador."""
from __future__ import annotations

import gzip
import hashlib
import re
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

from coletor.site import paginas as P
from coletor import gerar_site as GS
from coletor import novidades as N


RAIZ = Path(__file__).resolve().parents[1]
CLASSE_JS = f'<script>{P.SCRIPT_CABECA}</script>'


class Cabecalho(HTMLParser):
    """Coleta scripts, o botão do menu e os links da navegação principal."""

    def __init__(self, texto: str):
        super().__init__()
        self.scripts: list[dict] = []
        self.botoes: list[dict] = []
        self.botoes_tema: list[dict] = []
        self.grupos_tema: list[dict] = []
        self.nos: list[dict] = []
        self.navs: list[dict] = []
        self.links: list[dict] = []
        self.no_head = False
        self.script: dict | None = None
        self.nav: dict | None = None
        self.link: dict | None = None
        self.botao: dict | None = None
        self.feed(texto)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.nos.append({"tag": tag, "attrs": a})
        if tag == "head":
            self.no_head = True
        elif tag == "script":
            self.script = {"attrs": a, "texto": "", "head": self.no_head}
            self.scripts.append(self.script)
        elif tag == "nav" and a.get("aria-label") == "Principal":
            self.nav = {"attrs": a}
            self.navs.append(self.nav)
        elif tag == "a" and self.nav is not None:
            self.link = {"attrs": a, "texto": ""}
            self.links.append(self.link)
        elif tag == "button" and "menu-botao" in (a.get("class") or "").split():
            self.botao = {"attrs": a, "texto": ""}
            self.botoes.append(self.botao)
        elif tag == "div" and a.get("class") == "tema":
            self.grupos_tema.append({"attrs": a, "na_nav": self.nav is not None})
        elif tag == "button" and "data-tema" in a:
            self.botao = {"attrs": a, "texto": ""}
            self.botoes_tema.append(self.botao)

    def handle_endtag(self, tag):
        if tag == "head":
            self.no_head = False
        elif tag == "script":
            self.script = None
        elif tag == "nav":
            self.nav = None
        elif tag == "a":
            self.link = None
        elif tag == "button":
            self.botao = None

    def handle_data(self, texto):
        for aberto in (self.script, self.link, self.botao):
            if aberto is not None:
                aberto["texto"] += texto


def externos(html: str) -> list[str]:
    return [s["attrs"]["src"] for s in Cabecalho(html).scripts if s["attrs"].get("src")]


class TestCabecalho(unittest.TestCase):
    def test_classe_js_no_head_antes_do_estilo(self):
        html = P.pagina("Título", "<p>corpo</p>", "index.html")
        cab = html.split("</head>", 1)[0]
        self.assertEqual(html.count(CLASSE_JS), 1)
        self.assertIn(CLASSE_JS, cab)
        self.assertLess(cab.index('<meta name="viewport"'), cab.index(CLASSE_JS))
        self.assertLess(cab.index(CLASSE_JS), cab.index('rel="stylesheet"'))
        inline = [s for s in Cabecalho(html).scripts if not s["attrs"]]
        self.assertEqual(len(inline), 1)
        self.assertTrue(inline[0]["head"])
        self.assertEqual(inline[0]["texto"], P.SCRIPT_CABECA)
        self.assertLessEqual(len(P.SCRIPT_CABECA.encode("utf-8")), 400)
        teste_js = (RAIZ / "tests/js/tema.test.js").read_text(encoding="utf-8")
        constante = re.search(r"^const SCRIPT_CABECA = '(.*)';$", teste_js, re.MULTILINE)
        self.assertIsNotNone(constante)
        self.assertEqual(P.SCRIPT_CABECA.encode("utf-8"), constante.group(1).encode("utf-8"))

    def test_controle_de_tema_oculto_sem_js_dentro_da_nav(self):
        doc = Cabecalho(P.pagina("Início", "", "index.html"))
        self.assertEqual(doc.grupos_tema, [{"attrs": {"class": "tema", "role": "group", "aria-label": "Tema", "hidden": None}, "na_nav": True}])
        self.assertEqual([b["texto"] for b in doc.botoes_tema], ["Automático", "Claro", "Escuro"])
        self.assertEqual([b["attrs"] for b in doc.botoes_tema], [
            {"type": "button", "data-tema": tema, "aria-pressed": str(tema == "auto").lower()}
            for tema in ("auto", "claro", "escuro")])

    def test_canonical_e_open_graph_por_caminho(self):
        for caminho, ativo in (("index.html", "index.html"), ("projetos.html", "projetos.html"),
                               ("vereadores/ana-de-souza.html", "")):
            with self.subTest(caminho=caminho):
                html = P.pagina("Título", "", ativo, caminho=caminho)
                url = N.URL_SITE + ("" if caminho == "index.html" else caminho)
                self.assertIn(f'<link rel="canonical" href="{url}">', html)
                self.assertIn(f'<meta property="og:url" content="{url}">', html)
        # A ficha precisa passar seu caminho real, sem derivá-lo do ativo vazio.
        pessoa = {"slug": "ana-de-souza", "nome": "Ana de Souza", "nome_siscam": "ANA DE SOUZA", "mandatos": {}}
        with mock.patch("coletor.site.pagina_sessoes.secao_sessoes_vereador", return_value=""):
            ficha = P.gerar_vereador({"legislaturas": []}, pessoa)
        self.assertIn(f'<link rel="canonical" href="{N.URL_SITE}vereadores/ana-de-souza.html">', ficha)
        # Compatibilidade com chamadas posicionais antigas.
        self.assertIn(f'href="{N.URL_SITE}projetos.html"', P.pagina("Título", "", "projetos.html"))

    def test_metadados_comuns_e_escape(self):
        html = P.pagina('Título "especial"', "", "index.html", descricao='Texto "citado"')
        nos = Cabecalho(html).nos
        metas = [n["attrs"] for n in nos if n["tag"] == "meta"]
        for propriedade, valor in (("og:type", "website"), ("og:site_name", "Radar dos Vereadores de Niterói"),
                                   ("og:locale", "pt_BR")):
            self.assertIn({"property": propriedade, "content": valor}, metas)
        self.assertIn({"name": "twitter:card", "content": "summary_large_image"}, metas)
        for tema, cor in (("light", "#F7F2E9"), ("dark", "#0E1B26")):
            self.assertIn({"name": "theme-color", "content": cor, "media": f"(prefers-color-scheme: {tema})"}, metas)
        self.assertIn('content="Título &quot;especial&quot;"', html)
        self.assertIn('content="Texto &quot;citado&quot;"', html)
        with mock.patch.object(N, "URL_SITE", 'https://exemplo.test/"&/'):
            html = P.pagina("Título", "", "index.html")
        self.assertIn('href="https://exemplo.test/&quot;&amp;/"', html)

    def test_404_links_absolutos_noindex_e_fichas_atuais(self):
        modelo = {"legislaturas": [{"id": "2021-2024"}, {"id": "2025-2028"}], "pessoas": {
            "zoe": {"slug": "zoe", "nome": "Zoé", "mandatos": {"2025-2028": {}}},
            "ana-de-souza": {"slug": "ana-de-souza", "nome": "Ana de Souza", "mandatos": {"2025-2028": {}}},
            "anterior": {"slug": "anterior", "nome": "Anterior", "mandatos": {"2021-2024": {}}}}}
        html = GS.gerar_404(modelo)
        self.assertIn('<h1>Página não encontrada</h1>', html)
        self.assertIn('<meta name="robots" content="noindex">', html)
        self.assertNotIn('rel="canonical"', html)
        self.assertNotIn('property="og:url"', html)
        self.assertIn('<h2>Procure um vereador</h2><ul><li>', html)
        self.assertIn('href="/radar-vereadores-niteroi/vereadores/ana-de-souza.html"', html)
        self.assertIn('href="/radar-vereadores-niteroi/vereadores/zoe.html"', html)
        self.assertLess(html.index('>Ana de Souza</a>'), html.index('>Zoé</a>'))
        self.assertNotIn("vereadores/anterior.html", html)
        for no in Cabecalho(html).nos:
            for atributo in ("href", "src"):
                if atributo in no["attrs"]:
                    self.assertTrue(no["attrs"][atributo].startswith(("/radar-vereadores-niteroi/", "#", "https://")), no)
        self.assertLessEqual(len(gzip.compress(html.encode("utf-8"), mtime=0)), 15 * 1024)
        self.assertIn('rel="alternate" type="application/rss+xml"', html)

    def test_redirect_alertas_permanece_separado(self):
        html = P.redirecionar("ruido.html")
        self.assertEqual(html, '<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0; url=ruido.html"><link rel="canonical" href="ruido.html"><a href="ruido.html">Esta página mudou de endereço.</a>')
        self.assertNotIn("og:site_name", html)

    def test_moldura_sem_vocabulario_politico_de_sessoes(self):
        html = P.pagina("Título", "", "index.html")
        moldura = " ".join(re.findall(r"<(?:header|footer)\b[^>]*>(.*?)</(?:header|footer)>", html, re.DOTALL))
        texto = re.sub(r"<[^>]+>", " ", moldura).casefold()
        self.assertTrue(texto.strip())
        self.assertNotRegex(texto, r"\b(?:governo|oposição|bancada|governista|alinhamento|rebeldia|fidelidade)\b")

    def test_botao_e_navegacao_principal(self):
        doc = Cabecalho(P.pagina("Sessões", "", "sessoes.html"))
        self.assertEqual(len(doc.botoes), 1)
        botao = doc.botoes[0]
        self.assertEqual(botao["attrs"], {"class": "menu-botao", "type": "button", "aria-expanded": "false",
                                          "aria-controls": "menu-principal", "hidden": None})
        self.assertEqual(botao["texto"], "Menu")
        self.assertEqual(len(doc.navs), 1)
        self.assertEqual(doc.navs[0]["attrs"], {"id": "menu-principal", "aria-label": "Principal"})
        self.assertEqual([(l["attrs"]["href"], l["texto"]) for l in doc.links], P.NAV)
        atuais = [l["attrs"]["href"] for l in doc.links if l["attrs"].get("aria-current") == "page"]
        self.assertEqual(atuais, ["sessoes.html"])
        html = P.pagina("Sessões", "", "sessoes.html")
        self.assertLess(html.index('class="marca"'), html.index('class="menu-botao"'))
        self.assertLess(html.index('class="menu-botao"'), html.index('id="menu-principal"'))

    def test_ficha_com_prefixo(self):
        html = P.pagina("Ficha", "", "", prefixo="../")
        doc = Cabecalho(html)
        self.assertTrue(all(l["attrs"]["href"].startswith("../") for l in doc.links))
        self.assertEqual([l["attrs"]["href"] for l in doc.links], [f"../{href}" for href, _ in P.NAV])
        self.assertFalse(any("aria-current" in l["attrs"] for l in doc.links))
        versao = hashlib.sha1((P.FONTE_ESTATICA / "navegacao.js").read_bytes()).hexdigest()[:10]
        self.assertIn(f'<script src="../navegacao.js?v={versao}" defer onerror="{P.ERRO_NAVEGACAO}"></script>', html)

    def test_classe_js_condicionada_e_desfeita_se_navegacao_falhar(self):
        self.assertIn("if(window.matchMedia&&d.addEventListener)r.classList.add(\"js\")", P.SCRIPT_CABECA)
        self.assertEqual(P.ERRO_NAVEGACAO, "document.documentElement.classList.remove('js')")
        doc = Cabecalho(P.pagina("Início", "", "index.html"))
        tags = [s["attrs"] for s in doc.scripts if (s["attrs"].get("src") or "").startswith("navegacao.js")]
        self.assertEqual(len(tags), 1)
        self.assertEqual(tags[0]["onerror"], P.ERRO_NAVEGACAO)
        self.assertIn("defer", tags[0])
        # Sem js, a grade de duas colunas segue visível; com js, o menu nasce recolhido abaixo de 760px.
        css = (RAIZ / "site_src/estilo.css").read_text(encoding="utf-8")
        estreito = css.split("@media (max-width: 759.98px) {", 1)[1].split("\n}", 1)[0]
        self.assertIn('.js .topo:not([data-menu="aberto"]) nav { display: none; }', estreito)
        self.assertIn(".js .menu-botao {", estreito)
        self.assertNotIn("[data-menu]", estreito.replace('[data-menu="aberto"]', ""))

    def test_ordem_dos_scripts(self):
        srcs = externos(P.pagina("Sessões", "", "sessoes.html", scripts=("sessoes.js",)))
        self.assertEqual([s.split("?v=")[0] for s in srcs], ["navegacao.js", "dados.js", "app.js", "sessoes.js"])

    def test_navegacao_opcional_por_existencia(self):
        with tempfile.TemporaryDirectory() as pasta:
            fonte = Path(pasta)
            for nome in ("estilo.css", "dados.js", "app.js"):
                (fonte / nome).write_bytes(b"/* recurso de teste */")
            with mock.patch.object(P, "FONTE_ESTATICA", fonte):
                html = P.pagina("Início", "", "index.html", prefixo="../")
                self.assertNotIn("navegacao.js", html)
                self.assertIn('class="menu-botao"', html)
                self.assertEqual([s.split("?v=")[0] for s in externos(html)], ["../dados.js", "../app.js"])
                conteudo = b"// menu"
                (fonte / "navegacao.js").write_bytes(conteudo)
                (fonte / "sessoes.js").write_bytes(b"// sessoes")
                html = P.pagina("Início", "", "index.html", prefixo="../", scripts=("sessoes.js",))
                versao = hashlib.sha1(conteudo).hexdigest()[:10]
                self.assertIn(f'<script src="../navegacao.js?v={versao}" defer onerror="{P.ERRO_NAVEGACAO}"></script>', html)
                self.assertEqual([s.split("?v=")[0] for s in externos(html)],
                                 ["../navegacao.js", "../dados.js", "../app.js", "../sessoes.js"])

    def test_navegacao_cabe_no_orcamento(self):
        conteudo = (RAIZ / "site_src/navegacao.js").read_bytes()
        self.assertLessEqual(len(gzip.compress(conteudo, mtime=0)), 4 * 1024)


if __name__ == "__main__":
    unittest.main()
