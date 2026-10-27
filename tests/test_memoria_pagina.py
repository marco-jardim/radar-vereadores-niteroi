"""Contratos offline da página editorial Cidade Sorriso."""
from __future__ import annotations

import copy
import gzip
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

import coletor.site.paginas as P
from coletor.site.pagina_memoria import DESCRICOES_EMBLEMAS, gerar_memoria


RAIZ = Path(__file__).resolve().parents[1]


class LeitorHTML(HTMLParser):
    def __init__(self, conteudo: str):
        super().__init__()
        self.elementos: list[tuple[str, dict]] = []
        self.textos: list[str] = []
        self.feed(conteudo)

    def handle_starttag(self, tag, attrs):
        self.elementos.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.textos.append(data)


class TestMemoriaPagina(unittest.TestCase):
    def setUp(self):
        temporario = tempfile.TemporaryDirectory()
        self.addCleanup(temporario.cleanup)
        self.estaticos = Path(temporario.name)
        self.mock_estaticos = patch.object(P, "FONTE_ESTATICA", self.estaticos)
        self.mock_estaticos.start()
        self.addCleanup(self.mock_estaticos.stop)
        # O template exige só estes três arquivos; demais recursos são opcionais.
        for nome in ("estilo.css", "dados.js", "app.js"):
            (self.estaticos / nome).write_text("", encoding="utf-8")
        self.memoria = {
            "criterios": "Critério editorial com fontes públicas, aplicado igualmente a todas as pessoas.",
            "homenageados": [{
                "id": "arariboia", "nome": "Arariboia", "nascimento": "1500", "morte": "1589-01-02",
                "vinculo": "Pessoa ligada à cidade.", "biografia": ["Uma trajetória documentada."],
                "emblema": "arariboia.svg",
                "fontes": [{"titulo": "Fonte pública", "url": "https://example.org/fonte"}],
            }],
            "linha_do_tempo": [{
                "data": "1894", "data_fim": "1903", "titulo": "Um período",
                "texto": "Um marco documentado.",
                "fontes": [{"titulo": "Fonte do marco", "url": "https://example.org/marco"}],
            }],
        }

    def criar_estatico(self, nome: str, conteudo: str = ""):
        caminho = self.estaticos / nome
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(conteudo, encoding="utf-8")

    def criar_emblema(self, nome: str):
        self.criar_estatico("memoria/" + nome,
                            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 160">'
                            '<symbol id="emblema"><path d="M0 0h10v10z"/></symbol></svg>')

    def memoria_real(self) -> dict:
        return json.loads((RAIZ / "config/memoria.json").read_text(encoding="utf-8"))

    def test_memoria_ausente_ou_vazia(self):
        for memoria in (None, {}, {"homenageados": []}):
            with self.subTest(memoria=memoria):
                self.assertIsNone(gerar_memoria(memoria))

    def test_opcionais_ausentes_nao_geram_elementos_vazios(self):
        pagina = gerar_memoria(self.memoria)
        self.assertNotIn('class="nome-completo"', pagina)
        self.assertNotIn('class="lugar-memoria"', pagina)
        self.assertNotIn('class="emblema"', pagina)
        self.assertNotRegex(pagina, r"<(p|ul|li|h[1-6])\b[^>]*>\s*</\1>")
        pessoa = self.memoria["homenageados"][0]
        pessoa["nome_completo"] = pessoa["nome"]
        pessoa.pop("nascimento")
        pessoa.pop("morte")
        pessoa.pop("biografia")
        pessoa.pop("fontes")
        pessoa.pop("vinculo")
        self.memoria.pop("criterios")
        self.memoria.pop("linha_do_tempo")
        pagina = gerar_memoria(self.memoria)
        self.assertNotIn('class="nome-completo"', pagina)
        self.assertNotIn('class="datas-vida"', pagina)
        self.assertNotIn('class="memoria-fontes"', pagina)
        self.assertNotIn('class="linha-tempo-completa"', pagina)

    def test_datas_precisas_anos_intervalos_e_aproximacoes(self):
        pagina = gerar_memoria(self.memoria)
        self.assertIn("Nascimento: 1500 · Morte: 02/01/1589", pagina)
        self.assertIn("1894–1903", "".join(LeitorHTML(pagina).textos))
        self.assertIn('<time datetime="1894">1894</time>', pagina)
        pessoa = self.memoria["homenageados"][0]
        pessoa["nascimento_texto"] = "século XVI"
        pessoa["morte_texto"] = "fim do século XVI (data incerta)"
        pagina = gerar_memoria(self.memoria)
        self.assertIn("Nascimento: século XVI · Morte: fim do século XVI (data incerta)", pagina)
        self.assertNotIn("02/01/1589", pagina)

    def test_escape_de_textos_atributos_e_urls(self):
        valor = 'Texto <marcado> & "citado"'
        url = 'https://example.org/?a=<b>&c="d"'
        pessoa = self.memoria["homenageados"][0]
        pessoa.update(nome=valor, nome_completo=valor + " completo", vinculo=valor,
                      biografia=[valor], lugar_de_memoria=valor, nascimento_texto=valor)
        pessoa["fontes"] = [{"titulo": valor, "url": url}]
        self.memoria["criterios"] = valor
        evento = self.memoria["linha_do_tempo"][0]
        evento.update(titulo=valor, texto=valor, fontes=pessoa["fontes"])
        self.criar_emblema("arariboia.svg")
        pagina = gerar_memoria(self.memoria)
        self.assertNotIn("<marcado>", pagina)
        self.assertGreaterEqual(pagina.count(html.escape(valor)), 10)
        self.assertEqual(pagina.count(f'href="{html.escape(url)}"'), 2)
        pessoa["id"] = 'nome"<&'
        pagina = gerar_memoria(self.memoria)
        self.assertIn('id="nome&quot;&lt;&amp;"', pagina)

    def test_ancoras_unicas_emblemas_acessiveis_e_fontes_preservadas(self):
        memoria = self.memoria_real()
        for pessoa in memoria["homenageados"]:
            self.criar_emblema(pessoa["emblema"])
        pagina = gerar_memoria(memoria)
        leitor = LeitorHTML(pagina)
        ids = [atributos["id"] for _, atributos in leitor.elementos if "id" in atributos]
        self.assertEqual(len(ids), len(set(ids)))
        artigos = [atributos for tag, atributos in leitor.elementos if tag == "article"]
        self.assertEqual([artigo["id"] for artigo in artigos], [p["id"] for p in memoria["homenageados"]])
        emblemas = [atributos for tag, atributos in leitor.elementos if tag == "svg"]
        self.assertEqual(len(emblemas), len(artigos))
        for pessoa, emblema, artigo in zip(memoria["homenageados"], emblemas, artigos):
            identificador = pessoa["id"]
            self.assertEqual(artigo["aria-labelledby"], "h-" + identificador)
            self.assertEqual(emblema["role"], "img")
            self.assertEqual(emblema["aria-labelledby"], "e-" + identificador)
            self.assertEqual(emblema["viewbox"], "0 0 160 160")
            self.assertIn(f'<title id="e-{identificador}">Emblema de {pessoa["nome"]}: '
                          f'{DESCRICOES_EMBLEMAS[identificador]}</title>', pagina)
            self.assertIn(f'{P.url_estatica("memoria/" + pessoa["emblema"])}#emblema', pagina)
            for fonte in pessoa["fontes"]:
                self.assertIn(html.escape(fonte["titulo"]), pagina)
        self.assertIn(memoria["criterios"], pagina)
        self.assertEqual(pagina, gerar_memoria(copy.deepcopy(memoria)))

    def test_css_e_preload_exclusivos_da_memoria_com_urls_publicadas(self):
        self.criar_estatico("memoria.css", (RAIZ / "site_src/memoria.css").read_text(encoding="utf-8"))
        for nome in ("fontes/fraunces-latin-wght-normal.woff2",
                     "fontes/fraunces-latin-ext-wght-normal.woff2", "memoria/azulejo.svg"):
            self.criar_estatico(nome, "recurso simulado")
        pagina = gerar_memoria(self.memoria)
        cabeca, corpo = pagina.split("</head>", 1)
        css = f'<link rel="stylesheet" href="{P.url_estatica("memoria.css")}">'
        preload = (f'<link rel="preload" as="font" type="font/woff2" crossorigin '
                   f'href="{P.url_estatica("fontes/fraunces-latin-wght-normal.woff2")}">')
        self.assertEqual(cabeca.count(css), 1)
        self.assertEqual(cabeca.count(preload), 1)
        self.assertNotIn("fraunces-", corpo)
        css_publicado = P.bytes_estaticos(self.estaticos / "memoria.css").decode("utf-8")
        self.assertIn(P.url_estatica("fontes/fraunces-latin-wght-normal.woff2"), css_publicado)
        inicio = P.pagina("Início", "<h1>Início</h1>", ativo="index.html")
        self.assertNotIn("fraunces", inicio.casefold())
        self.assertNotIn("memoria.css", inicio)

    def test_recursos_opcionais_ausentes(self):
        pagina = gerar_memoria(self.memoria)
        self.assertNotIn("fraunces-", pagina.casefold())
        self.assertNotIn("memoria.css", pagina)

    def test_orcamento_html_com_configuracao_real(self):
        memoria = self.memoria_real()
        for pessoa in memoria["homenageados"]:
            self.criar_emblema(pessoa["emblema"])
        self.criar_estatico("memoria.css")
        self.criar_estatico("fontes/fraunces-latin-wght-normal.woff2", "fonte simulada")
        pagina = gerar_memoria(memoria)
        self.assertLessEqual(len(gzip.compress(pagina.encode("utf-8"), mtime=0)), 100 * 1024)
        self.assertIn('href="' + P.REPO + '/issues/new"', pagina)
        self.assertIn('memoria.html', pagina)

    def test_gerador_nao_introduz_vocabulario_de_sessoes(self):
        # Fixture neutra: os títulos das fontes reais são preservados, inclusive
        # "Governo do Estado do Rio de Janeiro", que é o nome de um publicador.
        texto = " ".join(LeitorHTML(gerar_memoria(self.memoria)).textos).casefold()
        for palavra in ("governo", "oposição", "bancada", "governista", "alinhamento", "rebeldia", "fidelidade"):
            self.assertIsNone(re.search(rf"\b{palavra}\b", texto), palavra)


if __name__ == "__main__":
    unittest.main()
