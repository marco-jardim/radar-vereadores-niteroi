"""Busca progressiva e metodologia: contratos offline, sem Worker nem rede."""
from __future__ import annotations

import gzip
import json
import re
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from coletor.site import pagina_busca as B
from coletor.site import paginas as P
from tests.test_acessibilidade_html import analisar
from tests.test_glossario import PaginaGlossario


MODELO = {"pessoas": {"ana": {"nome": "Ana <Teste> & Cia"}},
          "legislaturas": [{"id": "2025-2028"}, {"id": "2021-2024"}]}


class Estrutura(HTMLParser):
    def __init__(self, texto):
        super().__init__()
        self.tags = []
        self.feed(texto)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class TestPaginaBusca(unittest.TestCase):
    def test_sem_api_continua_util_e_nao_habilita_formulario(self):
        texto = B.gerar_busca(MODELO, None)
        arvore = analisar(texto)
        self.assertIn("ainda não está disponível", texto)
        self.assertIn('name="radar-api" content=""', texto)
        self.assertIn("disabled", arvore.ids["busca-campos"])
        for href in ("projetos.html", "atividades.html", "sessoes.html", P.SISCAM):
            self.assertIn(f'href="{href}"', texto)
        self.assertEqual(arvore.problemas, [])
        self.assertEqual(texto.count("<h1>"), 1)

    def test_sem_js_com_api_explicacao_e_melhora_progressiva(self):
        texto = B.gerar_busca(MODELO, "https://api.example.test")
        self.assertIn('name="radar-api" content="https://api.example.test"', texto)
        self.assertIn("precisa de JavaScript", texto)
        self.assertIn('id="busca-campos" disabled', texto)
        self.assertIn('aria-current="page">Busca</a>', texto)
        self.assertIn(f'<link rel="canonical" href="{P.N.URL_SITE}busca.html">', texto)
        doc = Estrutura(texto)
        campos = {a["id"]: a for t, a in doc.tags if t in {"input", "select"}}
        rotulos = {a["for"] for t, a in doc.tags if t == "label" and "for" in a}
        self.assertTrue(campos.keys() <= rotulos)
        self.assertEqual({a["name"] for a in campos.values()}, {"q", "modo", "tipo", "ano", "autor", "legislatura"})
        self.assertIn('role="status" aria-live="polite" aria-atomic="true"', texto)
        self.assertIn('id="busca-mais" type="button" hidden', texto)
        self.assertIn("Ana &lt;Teste&gt; &amp; Cia", texto)

    def test_configuracao_opcional_versionada_e_escape_de_atributo(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            self.assertIsNone(B.carregar_api(raiz))
            (raiz / "config").mkdir()
            caminho = raiz / "config/backend.json"
            for valor in (None, "https://api.example.test/base"):
                caminho.write_text(json.dumps({"api_url": valor}), encoding="utf-8")
                self.assertEqual(B.carregar_api(raiz), valor)
        texto = B.gerar_busca(MODELO, 'https://example.test/" onload="x')
        meta = next(a for t, a in Estrutura(texto).tags if t == "meta" and a.get("name") == "radar-api")
        self.assertEqual(set(meta), {"name", "content"})
        real = B.carregar_api(P.RAIZ)
        self.assertIn(f'name="radar-api" content="{P.esc(real or "")}"', B.gerar_busca(MODELO, real))

    def test_estaticos_versionados_ordem_glossario_e_orcamentos(self):
        texto = B.gerar_busca(MODELO, None)
        self.assertIn(f'href="{P.url_estatica("busca.css")}"', texto)
        scripts = [a for t, a in Estrutura(texto).tags if t == "script" and "src" in a]
        self.assertEqual([a["src"].split("?")[0] for a in scripts], ["navegacao.js", "dados.js", "app.js", "busca.js"])
        self.assertTrue(all("defer" in a for a in scripts))
        self.assertEqual(scripts[-1]["src"], P.url_estatica("busca.js"))
        glossario = PaginaGlossario(texto)
        self.assertEqual(glossario.usados, {"busca"})
        self.assertEqual(glossario.usados, glossario.definidos)
        self.assertEqual(glossario.invalidos, [])
        self.assertLessEqual(len(gzip.compress(texto.encode("utf-8"), mtime=0)), 100 * 1024)
        self.assertLessEqual(len(gzip.compress((P.FONTE_ESTATICA / "busca.js").read_bytes(), mtime=0)), 6 * 1024)

    def test_css_so_tokens_existentes_e_grade_flexivel(self):
        css = (P.FONTE_ESTATICA / "busca.css").read_text(encoding="utf-8")
        global_css = (P.FONTE_ESTATICA / "estilo.css").read_text(encoding="utf-8")
        self.assertFalse(re.search(r"#[0-9a-fA-F]{3,8}\b", css))
        tokens = set(re.findall(r"var\((--[\w-]+)\)", css))
        self.assertTrue(tokens <= set(re.findall(r"(--[\w-]+)\s*:", global_css)))
        self.assertIn("minmax(min(100%, 240px), 1fr)", css)

    def test_metodologia_privacidade_e_auditoria(self):
        texto = B.metodologia_busca()
        for secao in ("inteiro-teor", "busca", "privacidade", "auditoria"):
            self.assertIn(f'id="{secao}"', texto)
        for termo in ("CPF e RG", "sempre mascarados", "Telefones e e-mails", "contatos públicos", "sem máscara",
                      "exatamente como publicados pelo SISCAM", "config/remocoes.json", "/issues/new", "Cloudflare",
                      "não registra a consulta nem o IP", "RRF", "k = 60", "Não há resposta", "SHA-256",
                      "--verificar", "OCR", "inferior a 60", "atestação"):
            self.assertIn(termo, texto)
        self.assertEqual(analisar(texto).problemas, [])


if __name__ == "__main__":
    unittest.main()
