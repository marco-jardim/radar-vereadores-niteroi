"""Contratos do glossário, sem gerar páginas nem acessar a rede."""
from __future__ import annotations

from html import escape
from html.parser import HTMLParser
import re
import unittest
from unittest.mock import patch

from coletor.site.glossario import ColetorGlossario, TERMOS, secao_glossario


class PaginaGlossario(HTMLParser):
    """Inspeciona ancestrais sem a correção automática de links aninhados do navegador."""

    PROIBIDOS = {"summary", "label", "th", "button", "a", "caption", *(
        f"h{i}" for i in range(1, 7))}
    VAZIOS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
              "meta", "param", "source", "track", "wbr"}

    def __init__(self, texto: str):
        super().__init__()
        self.pilha: list[tuple[str, dict]] = []
        self.usados: set[str] = set()
        self.definidos: set[str] = set()
        self.ids: set[str] = set()
        self.templates = 0
        self.invalidos: list[str] = []
        self.feed(texto)

    def handle_starttag(self, tag, attrs):
        atributos = dict(attrs)
        ancestrais = [t for t, _ in self.pilha]
        if atributos.get("id"):
            self.ids.add(atributos["id"])
        if tag == "template" and atributos.get("id") == "glossario-defs":
            self.templates += 1
            if "main" not in ancestrais:
                self.invalidos.append("template fora de main")
        if tag == "a" and "glossario" in (atributos.get("class") or "").split():
            self.usados.add(atributos.get("data-termo", ""))
            self.invalidos.extend(t for t in ancestrais if t in self.PROIBIDOS)
        if tag == "p" and any(t == "template" and a.get("id") == "glossario-defs"
                               for t, a in self.pilha):
            self.definidos.add(atributos.get("data-termo", ""))
        if tag not in self.VAZIOS:
            self.pilha.append((tag, atributos))

    def handle_endtag(self, tag):
        for i in range(len(self.pilha) - 1, -1, -1):
            if self.pilha[i][0] == tag:
                del self.pilha[i:]
                break


class TestGlossario(unittest.TestCase):
    def test_termos_previstos_com_definicao_e_ancora(self):
        self.assertEqual(set(TERMOS), {
            "autorizativa", "sem-efeito", "simbolica", "substitutivo", "indicacao",
            "requerimento", "mocao", "pdl", "projeto-de-resolucao", "veto",
            "derrubada", "quorum", "parecer", "consignado", "votou-ausente",
            "ausencia-justificada", "abono-cargo", "presenca-efetiva",
        })
        secao = secao_glossario()
        self.assertTrue(secao.startswith(
            '<section id="glossario" aria-labelledby="t-glossario">'
            '<h2 id="t-glossario">Glossário</h2><dl class="defs">'
        ))
        self.assertTrue(secao.endswith('</dl></section>'))
        for chave, (rotulo, definicao) in TERMOS.items():
            with self.subTest(chave=chave):
                self.assertTrue(rotulo.strip())
                self.assertTrue(definicao.strip())
                self.assertEqual(secao.count(f'id="g-{chave}"'), 1)
                self.assertIn(
                    f'<dt><dfn id="g-{chave}">{escape(rotulo)}</dfn></dt>'
                    f'<dd>{escape(definicao)}</dd>', secao,
                )

    def test_secao_em_ordem_alfabetica_estavel(self):
        self.assertEqual(re.findall(r'<dfn id="g-([^"]+)">', secao_glossario()), [
            "abono-cargo", "ausencia-justificada", "autorizativa", "consignado", "derrubada", "indicacao", "mocao", "parecer",
            "presenca-efetiva", "pdl", "projeto-de-resolucao", "quorum", "requerimento", "sem-efeito",
            "simbolica", "substitutivo", "veto", "votou-ausente",
        ])
        with patch.dict(TERMOS, {"z": ("Árvore", "Uma definição."),
                                "a": ("Azul", "Outra definição.")}, clear=True):
            self.assertLess(secao_glossario().index('id="g-z"'),
                            secao_glossario().index('id="g-a"'))

    def test_links_e_chaves_de_todos_os_termos(self):
        coletor = ColetorGlossario()
        for chave, (rotulo, _) in TERMOS.items():
            with self.subTest(chave=chave):
                self.assertRegex(chave, r"^[a-z0-9-]+$")
                self.assertEqual(coletor.termo(chave),
                                 f'<a class="glossario" href="metodologia.html#g-{chave}" '
                                 f'data-termo="{chave}">{escape(rotulo)}</a>')

    def test_prefixo_relativo(self):
        coletor = ColetorGlossario("../")
        for chave in TERMOS:
            with self.subTest(chave=chave):
                self.assertIn(f'href="../metodologia.html#g-{chave}"', coletor.termo(chave))

    def test_escapa_texto_e_atributos(self):
        coletor = ColetorGlossario('../"&')
        link = coletor.termo("veto", '<veto> & "texto"')
        self.assertIn('>&lt;veto&gt; &amp; &quot;texto&quot;</a>', link)
        self.assertIn('href="../&quot;&amp;metodologia.html#g-veto"', link)

    def test_escapa_rotulos_e_definicoes(self):
        with patch.dict(TERMOS, {"teste": ("<Rótulo> &", "<Definição> &")}):
            coletor = ColetorGlossario()
            self.assertIn('>&lt;Rótulo&gt; &amp;</a>', coletor.termo("teste"))
            self.assertIn('<b>&lt;Rótulo&gt; &amp;</b>: &lt;Definição&gt; &amp;',
                          coletor.definicoes())
            self.assertIn('>&lt;Rótulo&gt; &amp;</dfn></dt><dd>&lt;Definição&gt; &amp;</dd>',
                          secao_glossario())

    def test_termo_repetido_tem_definicao_unica_em_ordem_de_uso(self):
        coletor = ColetorGlossario()
        coletor.termo("veto")
        coletor.termo("parecer")
        coletor.termo("veto", "outro texto")
        definicoes = coletor.definicoes()
        self.assertTrue(definicoes.startswith('<template id="glossario-defs">'))
        self.assertTrue(definicoes.endswith('</template>'))
        self.assertEqual(re.findall(r'<p data-termo="([^"]+)">', definicoes),
                         ["veto", "parecer"])
        for chave in ("veto", "parecer"):
            rotulo, definicao = TERMOS[chave]
            self.assertIn(f'<b>{escape(rotulo)}</b>: {escape(definicao)}</p>', definicoes)

    def test_definicoes_vazias_e_emissao_unica(self):
        coletor = ColetorGlossario()
        self.assertEqual(coletor.definicoes(), "")
        coletor.termo("consignado")
        self.assertTrue(coletor.definicoes())
        self.assertEqual(coletor.definicoes(), "")
        coletor.termo("veto")
        self.assertEqual(coletor.definicoes(), "")

    def test_coletores_independentes(self):
        primeiro, segundo = ColetorGlossario(), ColetorGlossario()
        primeiro.termo("veto")
        self.assertEqual(segundo.definicoes(), "")
        segundo.termo("veto")
        self.assertEqual(primeiro.definicoes(), segundo.definicoes())

    def test_chave_desconhecida(self):
        coletor = ColetorGlossario()
        with self.assertRaises(KeyError) as erro:
            coletor.termo("inexistente")
        self.assertEqual(erro.exception.args, ("termo de glossário desconhecido: inexistente",))
        self.assertEqual(coletor.definicoes(), "")

    def test_vocabulario_neutro(self):
        proibidas = re.compile(r"\b(?:governo|oposição|bancada|governista|alinhamento|rebeldia|fidelidade)\b")
        for chave, (rotulo, definicao) in TERMOS.items():
            with self.subTest(chave=chave):
                self.assertIsNone(proibidas.search(f"{rotulo} {definicao}".casefold()))


class TestGlossarioPublicado(unittest.TestCase):
    def test_inspecao_detecta_ancestrais_proibidos(self):
        for tag in PaginaGlossario.PROIBIDOS:
            with self.subTest(tag=tag):
                doc = PaginaGlossario(f'<{tag}><a class="glossario" data-termo="veto">veto</a></{tag}>')
                self.assertIn(tag, doc.invalidos)


if __name__ == "__main__":
    unittest.main()
