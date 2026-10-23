"""Teste de fumaça: gera o site inteiro a partir de data/ e config/ reais.

Escreve em <repositório>/site/, que é saída gerada e ignorada pelo Git.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock
from xml.etree import ElementTree

from coletor import gerar_site
from coletor import novidades as N
from coletor.site import paginas as P
from coletor.site.modelo import TIPOS_DOC

PAGINAS = ("index.html", "novidades.html", "leis.html", "projetos.html", "atividades.html", "sessoes.html", "ruido.html", "analises.html",
           "metodologia.html")
DOCUMENTOS = gerar_site.RAIZ / "data" / "documentos"


class TestGerarSite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        saida = io.StringIO()
        with mock.patch.object(sys, "argv", ["coletor.gerar_site"]), contextlib.redirect_stdout(saida):
            gerar_site.main()
        cls.mensagem = saida.getvalue()
        cls.saida = gerar_site.SAIDA

    def test_paginas_principais(self):
        for nome in PAGINAS:
            with self.subTest(pagina=nome):
                arq = self.saida / nome
                self.assertTrue(arq.is_file(), f"{arq} não foi gerado")
                conteudo = arq.read_text(encoding="utf-8")
                self.assertIn("<html", conteudo.lower())

    def test_integracao_sessoes_menu_metodologia_e_fichas(self):
        hrefs = [href for href, _ in P.NAV]
        posicao = hrefs.index("sessoes.html")
        self.assertEqual(hrefs[posicao - 1:posicao + 2], ["atividades.html", "sessoes.html", "ruido.html"])
        html = (self.saida / "sessoes.html").read_text(encoding="utf-8")
        self.assertIn('<h1>Sessões e votações</h1>', html)
        self.assertIn('href="sessoes.html" aria-current="page">Sessões</a>', html)
        self.assertIn('href="metodologia.html#sessoes"', html)
        self.assertIn("sessoes.html", self.mensagem)  # o relatório percorre todos os HTMLs
        tamanho = gerar_site.tamanho_gzip((self.saida / "sessoes.html").read_bytes())
        print(f"\nSessões (dados versionados): {tamanho} B gzip; alvo de apresentação: 60 KiB.")
        self.assertLessEqual(tamanho, gerar_site.LIMITE_HTML_GZIP)
        metodo = (self.saida / "metodologia.html").read_text(encoding="utf-8")
        self.assertIn('id="sessoes"', metodo)
        self.assertIn('href="#sessoes"', metodo)
        for caminho in (self.saida / "vereadores").glob("*.html"):
            with self.subTest(vereador=caminho.name):
                ficha = caminho.read_text(encoding="utf-8")
                self.assertIn('id="t-sessoes">Presença e votos', ficha)
                self.assertIn('href="../metodologia.html#sessoes"', ficha)
                if 'class="mandato"' in ficha:
                    self.assertLess(ficha.index('class="mandato"'), ficha.index('id="t-sessoes"'))
                if 'id="t-atividade"' in ficha:
                    self.assertLess(ficha.index('id="t-sessoes"'), ficha.index('id="t-atividade"'))

    def test_gera_sem_pasta_de_sessoes(self):
        # Isola só a raiz opcional e a saída, sem renomear nem alterar data/.
        with tempfile.TemporaryDirectory(prefix="site-sem-sessoes-", dir=self.saida.parent) as pasta:
            raiz = Path(pasta)
            saida = raiz / "site"
            mensagem = io.StringIO()
            renderizar = gerar_site.pagina_sessoes.gerar_sessoes
            with (mock.patch.object(gerar_site, "RAIZ", raiz),
                  mock.patch.object(gerar_site, "SAIDA", saida),
                  mock.patch.object(gerar_site.modelo_sessoes, "montar_sessoes") as montar,
                  mock.patch.object(gerar_site.pagina_sessoes, "gerar_sessoes", wraps=renderizar) as pagina,
                  contextlib.redirect_stdout(mensagem)):
                gerar_site.main()
            montar.assert_not_called()
            self.assertIsNone(pagina.call_args.args[0]["sessoes"])
            self.assertIn("Nenhuma sessão coletada disponível", (saida / "sessoes.html").read_text(encoding="utf-8"))
            self.assertIn('id="sessoes"', (saida / "metodologia.html").read_text(encoding="utf-8"))
            ficha = next((saida / "vereadores").glob("*.html")).read_text(encoding="utf-8")
            self.assertIn("Nenhum registro de frequência com este nome", ficha)
            for nome in PAGINAS:
                self.assertTrue((saida / nome).is_file(), nome)
            self.assertIn("sessoes.html", mensagem.getvalue())

    def test_novidades_e_feed_rss(self):
        canal = ElementTree.fromstring((self.saida / "feed.xml").read_bytes()).find("channel")
        self.assertIsNotNone(canal)
        itens = canal.findall("item")
        self.assertLessEqual(len(itens), N.MAX_ITENS_RSS)
        for item in itens:
            self.assertTrue(item.findtext("link").startswith("https://"))
            self.assertEqual(item.find("guid").get("isPermaLink"), "false")
        self.assertEqual(len({i.findtext("guid") for i in itens}), len(itens))
        for nome in PAGINAS:
            with self.subTest(pagina=nome):
                html = (self.saida / nome).read_text(encoding="utf-8")
                self.assertIn('<link rel="alternate" type="application/rss+xml"', html)
                self.assertIn('href="novidades.html"', html)  # no menu
        self.assertIn('id="novidades"', (self.saida / "metodologia.html").read_text(encoding="utf-8"))
        tamanho = gerar_site.tamanho_gzip((self.saida / "novidades.html").read_bytes())
        self.assertLessEqual(tamanho, gerar_site.LIMITE_HTML_GZIP)

    def test_recursos_estaticos_copiados(self):
        for arq in gerar_site.FONTE_ESTATICA.iterdir():
            with self.subTest(recurso=arq.name):
                self.assertTrue((self.saida / arq.name).is_file())

    def test_json_do_cliente(self):
        dados = json.loads((self.saida / "dados" / "projetos.json").read_text(encoding="utf-8"))
        self.assertIsInstance(dados, dict)
        self.assertIn("projetos", dados)  # contrato com site_src/app.js
        self.assertIsInstance(dados["projetos"], list)
        self.assertTrue(dados["projetos"])
        self.assertTrue({"n", "a", "e", "u", "g"} <= set(dados["projetos"][0]))
        self.assertIn(dados["projetos"][0]["g"], {"lei", "andamento", "sem_exito"})

    def test_tipo_e_veto_da_lei_nas_fatias_e_no_legado(self):
        legado = json.loads((self.saida / "dados/projetos.json").read_bytes())["projetos"]
        for nome in gerar_site.FATIAS_PL:
            colunas = json.loads((self.saida / f"dados/{nome}.json").read_bytes())["colunas"]
            for j, ordem in enumerate(colunas["ord"]):
                with self.subTest(fatia=nome, projeto=ordem):
                    self.assertEqual(colunas["lt"][j], legado[ordem]["lt"])
                    self.assertEqual(colunas["vp"][j], legado[ordem]["vp"])
                    # ls: id do substitutivo nas fatias, URL do detalhe no legado (como hidratar em dados.js)
                    ls = colunas["ls"][j]
                    self.assertEqual(legado[ordem]["ls"], None if ls is None else f"{P.SISCAM}DetalhesDocumentos.aspx?IdDocumento={ls}")
                    if ls is not None:
                        self.assertEqual(legado[ordem]["g"], "lei")

    def test_autoria_principal_e_coautores_nas_fatias_e_no_legado(self):
        legado = json.loads((self.saida / "dados/projetos.json").read_bytes())["projetos"]
        pessoas = json.loads((self.saida / "dados/dic-pl.json").read_bytes())["pessoas"]
        for nome in gerar_site.FATIAS_PL:
            colunas = json.loads((self.saida / f"dados/{nome}.json").read_bytes())["colunas"]
            for j, ordem in enumerate(colunas["ord"]):
                with self.subTest(fatia=nome, projeto=legado[ordem]["n"]):
                    autores = [[pessoas[i][1], pessoas[i][0]] for i in colunas["au"][j]]
                    principal = colunas["pr"][j]
                    self.assertEqual(autores, legado[ordem]["au"])
                    self.assertEqual(None if principal is None else pessoas[principal][0], legado[ordem]["pr"])

    def test_pl_140_credita_o_substitutivo_sem_corrige(self):
        cliente = json.loads((self.saida / "dados/projetos.json").read_bytes())
        p = next(p for p in cliente["projetos"] if p["n"] == "140/2021")
        self.assertEqual(p["pr"], "daniel-marques-frederico")
        self.assertEqual([s for _, s in p["au"]], ["daniel-marques-frederico", "milton-carlos-da-silva-lopes"])
        self.assertEqual((p["g"], p["l"], p["ld"]), ("lei", 3958, "2024-09-12"))
        self.assertIn("inconstitucionalidade_declarada", p["s"])
        curadoria = json.loads((gerar_site.RAIZ / "config/curadoria.json").read_bytes())["entradas"]
        self.assertNotIn("corrige", next(e for e in curadoria if e["projeto"] == "140/2021"))
        for modo in ("leis", "projetos"):
            html = (self.saida / f"{modo}.html").read_text(encoding="utf-8")
            self.assertIn(f'<option value="milton-carlos-da-silva-lopes">{P.esc(p["au"][1][0])}</option>', html)
        metodologia = (self.saida / "metodologia.html").read_text(encoding="utf-8")
        self.assertIn("os autores do substitutivo também recebem o crédito, como coautores se não assinaram o PL", metodologia)

    def test_detalhes_externos_em_todas_as_paginas_e_navegacao_interna(self):
        for caminho in self.saida.rglob("*.html"):
            html = caminho.read_text(encoding="utf-8")
            for link in LinksHTML(html).links:
                href = link.get("href", "")
                with self.subTest(pagina=caminho.name, url=href):
                    if href.startswith("https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?"):
                        self.assertEqual(link.get("target"), "_blank")
                        self.assertEqual(link.get("rel"), "noopener")
                    elif not href.startswith(("https://", "http://")):
                        self.assertNotIn("target", link)

    def test_manifesto_e_documentos(self):
        manifesto = json.loads((self.saida / "dados" / "manifest.json").read_text(encoding="utf-8"))
        familias = {e.get("familia") for e in manifesto["arquivos"].values()}
        self.assertTrue({"dic-pl", "pl-lei", "pl-andamento", "pl-sem_exito"} <= set(manifesto["arquivos"]))
        for nome in ("dic-pl", "pl-lei", "pl-andamento", "pl-sem_exito"):
            self.assertNotIn("familia", manifesto["arquivos"][nome])  # entradas de PL inalteradas
        atividades = (self.saida / "atividades.html").read_text(encoding="utf-8")
        tem_documentos = any(json.loads(arq.read_text(encoding="utf-8"))
                             for tipo in TIPOS_DOC for arq in sorted((DOCUMENTOS / tipo).glob("*.json")))
        if tem_documentos:
            self.assertIn("dic-doc", manifesto["arquivos"])
            self.assertTrue({"dic-doc", "doc"} <= familias)
            self.assertRegex(manifesto["build_doc"], r"^[0-9a-f]{10}$")
            self.assertIn('data-modo="atividades"', atividades)
            for nome, e in manifesto["arquivos"].items():
                if e.get("familia"):
                    with self.subTest(arquivo=nome):
                        self.assertTrue((self.saida / e["url"].split("?")[0]).is_file())
        else:
            self.assertEqual(familias, {None})
            self.assertNotIn("build_doc", manifesto)
            self.assertNotIn('data-modo="atividades"', atividades)

    def test_paginas_de_vereadores(self):
        dados = json.loads((self.saida / "dados" / "vereadores.json").read_text(encoding="utf-8"))
        self.assertTrue(dados)
        self.assertTrue(any((self.saida / "vereadores").glob("*.html")))
        self.assertIn("site gerado", self.mensagem)

    def manifesto(self) -> dict:
        return json.loads((self.saida / "dados" / "manifest.json").read_text(encoding="utf-8"))

    def test_cargas_iniciais_cabem_no_orcamento(self):
        manifesto = self.manifesto()
        self.assertEqual(P.iniciais_por_pagina(manifesto)["projetos.html"], ["dic-pl", gerar_site.PREVIA_PL])
        cargas = gerar_site.cargas_iniciais(self.saida, manifesto)
        self.assertTrue({"leis.html", "projetos.html"} <= set(cargas))
        for pagina, (arquivos, _, comprimido) in cargas.items():
            with self.subTest(pagina=pagina):
                self.assertEqual(arquivos, len(P.iniciais_por_pagina(manifesto)[pagina]))
                self.assertLessEqual(comprimido, gerar_site.LIMITE_INICIAL_GZIP)
        self.assertEqual(gerar_site.cargas_acima_do_orcamento(self.saida, manifesto), [])

    def test_previa_de_projetos_e_resumo_exato(self):
        manifesto = self.manifesto()
        ler = lambda nome: json.loads((self.saida / manifesto["arquivos"][nome]["url"].split("?")[0]).read_bytes())
        self.assertNotIn("familia", manifesto["arquivos"][gerar_site.PREVIA_PL])
        linhas = {}
        for nome in gerar_site.FATIAS_PL:
            colunas = ler(nome)["colunas"]
            for j, ordem in enumerate(colunas["ord"]):
                linhas[ordem] = {k: v[j] for k, v in colunas.items()}
        previa = ler(gerar_site.PREVIA_PL)
        n = min(len(linhas), P.PASSO_LISTA)
        self.assertEqual((previa["esquema"], previa["build"], previa["n"]), (2, manifesto["build"], n))
        # As mesmas linhas das fatias completas, na ordem padrão: hidratar() devolve os mesmos registros.
        self.assertEqual(previa["colunas"], {k: [linhas[o][k] for o in range(n)] for k in previa["colunas"]})
        legado = json.loads((self.saida / "dados" / "projetos.json").read_text(encoding="utf-8"))["projetos"]
        html = (self.saida / "projetos.html").read_text(encoding="utf-8")
        total, ef = len(legado), sum(1 for p in legado if p["ef"])
        se, pol = sum(1 for p in legado if p["se"]), sum(1 for p in legado if p["pol"])
        self.assertIn(f'data-total="{total}"', html)
        self.assertIn(f'<p class="contagem inicial"><b>{total}</b> projetos · <b>{ef}</b> com efeito (viraram lei) · '
                      f'<b>{se}</b> sem efeito prático · <b>{pol}</b> com alerta</p>', html)
        chave = lambda p: "0" if p["c"] == "simbolica" or "autorizativa" in p["s"] else ("x" if p["i"] is None else str(p["i"]))
        for k, rotulo in P.CHIPS_IMPACTO:
            with self.subTest(chip=k):
                self.assertIn(f'value="{k}"> {rotulo}<span class="n inicial">{sum(1 for p in legado if chave(p) == k)}</span>', html)
        self.assertIn("<noscript>", html)
        self.assertIn("<noscript>", (self.saida / "leis.html").read_text(encoding="utf-8"))


class LinksHTML(HTMLParser):
    def __init__(self, texto: str):
        super().__init__()
        self.links = []
        self.feed(texto)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.append(dict(attrs))


class TestComponentesLei(unittest.TestCase):
    @staticmethod
    def projeto(**extra) -> dict:
        return {
            "numero": "140/2021", "data": "2021-04-21", "desfecho": "virou_lei", "impacto": 2,
            "lei": {"numero": 3958, "data": "2024-10-10", "tipo": "veto_derrubado", "veto_parcial": True},
            "resumo": "Infraestrutura <pública> & elétrica", "ementa": "Infraestrutura para carros elétricos",
            "tema": "mobilidade", "publico": "moradores", "partido": "PX", "categoria": "regulacao",
            "autores": [{"exibicao": "Ana", "vereador": True, "slug": "ana"}], "principal": "ana",
            "sinais": [], "alertas": [], "repete": {"numero": "1/2021", "url": "https://exemplo.invalid/pl/1"},
            "url": "https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento=127858", **extra,
        }

    def test_situacao_e_datas_nos_cartoes_e_itens(self):
        for tipo, rotulo in (("sancionada", "Sancionada"), ("promulgada_camara", "Promulgada pela Câmara"),
                             ("veto_derrubado", "Veto derrubado")):
            for renderizar in (P.cartao_lei, P.item_projeto):
                with self.subTest(tipo=tipo, componente=renderizar.__name__):
                    p = self.projeto(lei={"numero": 3958, "data": "2024-10-10", "tipo": tipo, "veto_parcial": True})
                    html = renderizar(p, "../")
                    self.assertIn(f"{rotulo} · Veto parcial", html)
                    self.assertIn("10/10/2024", html)
                    self.assertIn("Infraestrutura &lt;pública&gt; &amp; elétrica", html)
                    p["lei"]["data"] = None
                    self.assertIn("data não informada", renderizar(p, "../"))

    def test_lei_via_substitutivo(self):
        pl = "https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento=127858"
        sub = "https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento=266596"
        p = self.projeto(lei_substitutivo=266596, lei={"numero": 3958, "data": "2024-09-12", "tipo": "veto_derrubado", "veto_parcial": False})
        cartao = P.cartao_lei(p, "../")
        self.assertEqual([l["href"] for l in LinksHTML(cartao).links if l["href"].startswith("https://consultaniteroi")], [sub])
        self.assertIn('<p class="lei-situacao">Veto derrubado <span class="via-substitutivo">via substitutivo</span></p>', cartao)
        self.assertIn("Lei 3958 · 12/09/2024", cartao)
        item = P.item_projeto(p, "../")
        self.assertEqual([l["href"] for l in LinksHTML(item).links if l["href"].startswith("https://consultaniteroi")], [pl, sub])
        self.assertIn(f'>PL 140/2021{P.NOVA_ABA}</a>', item)
        self.assertIn(f' · Lei 3958 · Veto derrubado <a class="via-substitutivo" href="{sub}" target="_blank" rel="noopener">'
                      f'via substitutivo<span class="so-leitor"> (substitutivo ao PL 140/2021)</span>{P.NOVA_ABA}</a> · 12/09/2024', item)
        for renderizar in (P.cartao_lei, P.item_projeto):
            with self.subTest(componente=renderizar.__name__):
                html = renderizar(self.projeto(), "../")
                self.assertNotIn("via substitutivo", html)
                self.assertIn(pl, html)
                self.assertNotIn(sub, html)

    def test_links_externos_em_nova_aba_e_chips_na_mesma(self):
        for renderizar in (P.cartao_lei, P.item_projeto):
            html = renderizar(self.projeto(), "../")
            for link in LinksHTML(html).links:
                with self.subTest(componente=renderizar.__name__, url=link["href"]):
                    if link["href"].startswith("https://") and "github.com" not in link["href"]:
                        self.assertEqual(link.get("target"), "_blank")
                        self.assertEqual(link.get("rel"), "noopener")
                    elif link["href"].startswith("../vereadores/"):
                        self.assertNotIn("target", link)
            self.assertIn(P.NOVA_ABA, html)
        for modo in ("leis", "projetos"):
            html = P.filtros_lista(modo)
            self.assertIn('<label>Autoria <select id="f-coautor" disabled>', html)
            self.assertIn('<option value="">Só autoria principal</option>', html)
            self.assertIn('<option value="1">Incluir coautoria</option>', html)
            self.assertIn('<option value="so">Apenas coautoria</option>', html)
            self.assertNotIn('type="checkbox" id="f-coautor"', html)


class TestResumoProjetos(unittest.TestCase):
    """Contagens do HTML inicial de projetos.html, com as regras de aplicarFiltros (app.js)."""

    @staticmethod
    def projeto(**campos) -> dict:
        return {"c": "politica_publica", "i": 2, "s": [], "ef": 0, "se": 0, "pol": 0, **campos}

    def test_contagens_e_texto(self):
        cliente = {"projetos": [
            self.projeto(ef=1),
            self.projeto(c="simbolica", i=3, se=1),       # simbólica conta em "Sem efeito", mesmo com impacto
            self.projeto(s=["autorizativa"], i=1, se=1),  # autorizativa também
            self.projeto(i=None, pol=1),
            self.projeto(i=0, se=1),
        ]}
        r = P.resumo_projetos(cliente)
        self.assertEqual(r, {"total": 5, "ef": 1, "se": 3, "pol": 1, "chips": {"3": 0, "2": 1, "1": 0, "0": 3, "x": 1}})
        self.assertEqual(P.contagem_projetos(r), '<p class="contagem inicial"><b>5</b> projetos · <b>1</b> com efeito (viraram lei) · '
                                                 '<b>3</b> sem efeito prático · <b>1</b> com alerta</p>')
        um = P.resumo_projetos({"projetos": [self.projeto()]})
        self.assertTrue(P.contagem_projetos(um).startswith('<p class="contagem inicial"><b>1</b> projeto · '))
        self.assertEqual(P.contagem_projetos(P.resumo_projetos({"projetos": []})), '<p class="contagem inicial"><b>0</b> projetos</p>')

    def test_so_projetos_sem_cliente_nem_leis_ficam_sem_resumo(self):
        self.assertNotIn("data-total", P.filtros_lista("projetos"))
        self.assertNotIn('class="n inicial"', P.filtros_lista("projetos"))
        cliente = {"projetos": [], "pessoas": {}, "temas": {}, "legislaturas": []}
        self.assertNotIn("data-total", P.filtros_lista("leis", cliente))
        self.assertIn('data-total="0"', P.filtros_lista("projetos", cliente))


if __name__ == "__main__":
    unittest.main()
