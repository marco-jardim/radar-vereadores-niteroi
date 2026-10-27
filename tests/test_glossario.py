"""Contratos do glossário, sem gerar páginas nem acessar a rede."""
from __future__ import annotations

from html import escape
import re
import unittest
from unittest.mock import patch

from coletor.site.glossario import ColetorGlossario, TERMOS, secao_glossario


class TestGlossario(unittest.TestCase):
    def test_termos_previstos_com_definicao_e_ancora(self):
        self.assertEqual(set(TERMOS), {
            "autorizativa", "sem-efeito", "simbolica", "substitutivo", "indicacao",
            "requerimento", "mocao", "pdl", "projeto-de-resolucao", "veto",
            "derrubada", "quorum", "parecer", "consignado", "votou-ausente",
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
            "autorizativa", "consignado", "derrubada", "indicacao", "mocao", "parecer",
            "pdl", "projeto-de-resolucao", "quorum", "requerimento", "sem-efeito",
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


if __name__ == "__main__":
    unittest.main()
