"""Cabeçalho comum: menu móvel com melhoria progressiva, sem rede nem navegador."""
from __future__ import annotations

import gzip
import hashlib
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

from coletor.site import paginas as P


RAIZ = Path(__file__).resolve().parents[1]
CLASSE_JS = '<script>document.documentElement.classList.add("js")</script>'


class Cabecalho(HTMLParser):
    """Coleta scripts, o botão do menu e os links da navegação principal."""

    def __init__(self, texto: str):
        super().__init__()
        self.scripts: list[dict] = []
        self.botoes: list[dict] = []
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
        self.assertIn(f'<script src="../navegacao.js?v={versao}" defer></script>', html)

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
                self.assertIn(f'<script src="../navegacao.js?v={versao}" defer></script>', html)
                self.assertEqual([s.split("?v=")[0] for s in externos(html)],
                                 ["../navegacao.js", "../dados.js", "../app.js", "../sessoes.js"])

    def test_navegacao_cabe_no_orcamento(self):
        conteudo = (RAIZ / "site_src/navegacao.js").read_bytes()
        self.assertLessEqual(len(gzip.compress(conteudo, mtime=0)), 4 * 1024)


if __name__ == "__main__":
    unittest.main()
