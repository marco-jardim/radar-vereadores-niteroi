"""Publicação recursiva e versões dos bytes estáticos, sem acesso à rede."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from coletor import gerar_site
from coletor.site import paginas as P


class TestEstaticos(unittest.TestCase):
    def test_fontes_woff2_validas_e_ate_60_kib_brutos(self):
        fontes = sorted((P.FONTE_ESTATICA / "fontes").glob("*.woff2"))
        self.assertTrue(fontes)
        for caminho in fontes:
            with self.subTest(fonte=caminho.name):
                conteudo = caminho.read_bytes()
                self.assertTrue(conteudo.startswith(b"wOF2"))
                self.assertLessEqual(len(conteudo), 60 * 1024)

    def setUp(self):
        temporario = tempfile.TemporaryDirectory(prefix="estaticos-")
        self.addCleanup(temporario.cleanup)
        self.raiz = Path(temporario.name).resolve()
        self.fonte = self.raiz / "site_src"
        self.fonte.mkdir()

    def gravar(self, nome: str, conteudo: bytes) -> Path:
        caminho = self.fonte / nome
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(conteudo)
        return caminho

    @staticmethod
    def versao(conteudo: bytes) -> str:
        return hashlib.sha1(conteudo).hexdigest()[:10]

    def test_url_com_aspas_espacos_e_fragmento(self):
        self.gravar("imagens/a.svg", b"<svg/>")
        versao = self.versao(b"<svg/>")
        texto = '''a{a:url('imagens/a.svg');b:url( "imagens/a.svg#emblema" );c:url(imagens/a.svg)}'''
        esperado = (f'''a{{a:url('imagens/a.svg?v={versao}');'''
                    f'''b:url( "imagens/a.svg?v={versao}#emblema" );c:url(imagens/a.svg?v={versao})}}''')
        self.assertEqual(P.css_publicado(texto, self.fonte, raiz=self.fonte), esperado)

    def test_urls_externas_consultas_e_fragmentos_intactos(self):
        texto = '''a{a:url(data:image/svg+xml;base64,AAAA);b:url("https://exemplo.org/a.svg");
        c:url(http://exemplo.org/a.svg);d:url(//exemplo.org/a.svg);e:url('a.svg?v=123#x');
        f:url(#emblema);g:url(/a.svg);h:url(data:image/svg+xml,%3Csvg%3E);i:url(https://host/a%20b.png)}'''
        self.assertEqual(P.css_publicado(texto, self.fonte), texto)

    def test_comentarios_e_strings_nao_sao_reescritos(self):
        texto = '''/* url(ausente.svg) */ a{content:"url(ausente.svg)"}'''
        self.assertEqual(P.css_publicado(texto, self.fonte), texto)

    def test_alvo_ausente_informa_css_e_alvo(self):
        css = self.gravar("css/tema.css", b"a{background:url(../ausente.svg)}")
        with self.assertRaises(ValueError) as erro:
            P.bytes_estaticos(css, raiz=self.fonte)
        self.assertIn(str(css), str(erro.exception))
        self.assertIn("../ausente.svg", str(erro.exception))

    def test_dependencia_css_usa_bytes_publicados(self):
        self.gravar("imagens/a.svg", b"<svg/>")
        self.gravar("css/base.css", b"a{background:url(../imagens/a.svg)}\r\n")
        principal = self.gravar("estilo.css", b'@import url("css/base.css");\r\n')
        saida = self.raiz / "publicado"
        gerar_site.copiar_estaticos(self.fonte, saida)
        base = (saida / "css/base.css").read_bytes()
        self.assertEqual(base, f"a{{background:url(../imagens/a.svg?v={self.versao(b'<svg/>')})}}\r\n".encode())
        self.assertEqual((saida / "estilo.css").read_bytes(),
                         f'@import url("css/base.css?v={self.versao(base)}");\r\n'.encode())
        self.assertEqual(P.bytes_estaticos(principal, raiz=self.fonte), (saida / "estilo.css").read_bytes())

    def test_ciclo_css_falha_sem_recursao_infinita(self):
        primeiro = self.gravar("a.css", b"@import url(b.css);")
        self.gravar("b.css", b"@import url(a.css);")
        with self.assertRaisesRegex(ValueError, "Ciclo de recursos CSS"):
            P.bytes_estaticos(primeiro, raiz=self.fonte)

    def test_importacao_string_e_image_set_versionam_so_referencias(self):
        self.gravar("css/base.css", b"a{background:url(../imagens/a.svg)}")
        self.gravar("imagens/a.svg", b"<svg/>")
        versao_svg = self.versao(b"<svg/>")
        versao_css = self.versao(f"a{{background:url(../imagens/a.svg?v={versao_svg})}}".encode())
        texto = '''@import "css/base.css" screen; @import 'css/base.css';
        a{background:image-set("imagens/a.svg" 1x, 'imagens/a.svg#x' 2x,
          url(imagens/a.svg) 3x, linear-gradient(red, blue) 4x);
          b:-webkit-image-set("imagens/a.svg" type("image/svg+xml") 1x);
          content:"imagens/a.svg";other:myurl(ausente.svg);outra:minha-url(ausente.svg)}
        /* @import "ausente.css"; image-set("ausente.svg" 1x) */'''
        esperado = texto.replace('"css/base.css"', f'"css/base.css?v={versao_css}"')
        esperado = esperado.replace("'css/base.css'", f"'css/base.css?v={versao_css}'")
        esperado = esperado.replace('image-set("imagens/a.svg"', f'image-set("imagens/a.svg?v={versao_svg}"')
        esperado = esperado.replace("'imagens/a.svg#x'", f"'imagens/a.svg?v={versao_svg}#x'")
        esperado = esperado.replace("url(imagens/a.svg)", f"url(imagens/a.svg?v={versao_svg})")
        self.assertEqual(P.css_publicado(texto, self.fonte, raiz=self.fonte), esperado)

    def test_referencias_string_ausentes_informam_css_e_alvo(self):
        for texto in ('@import "ausente.css";', "@import 'ausente.css';",
                      'a{background:image-set("ausente.svg" 1x)}',
                      "a{background:-webkit-image-set('ausente.svg' 1x)}"):
            with self.subTest(texto=texto):
                css = self.gravar("estilo.css", texto.encode())
                with self.assertRaises(ValueError) as erro:
                    P.bytes_estaticos(css, raiz=self.fonte)
                self.assertIn(str(css), str(erro.exception))
                self.assertIn("ausente.", str(erro.exception))

    def test_url_sem_aspas_com_escape_nao_e_resolvida(self):
        for alvo in (r"imagens/a\ b.svg", r"imagens/a\29.svg", "imagens/a%20b.svg"):
            with self.subTest(alvo=alvo), self.assertRaisesRegex(ValueError, "URL com escape não suportada"):
                P.css_publicado(f"a{{background:url({alvo})}}", self.fonte, raiz=self.fonte)

    def test_css_rejeita_alvos_fora_da_raiz_ou_excluidos(self):
        (self.raiz / "fora.svg").write_bytes(b"fora")
        alvos = ("../fora.svg", ".oculto.svg", ".pasta/a.svg", "FONTES.md")
        for alvo in alvos[1:]:
            self.gravar(alvo, b"excluido")
        for alvo in alvos:
            for referencia in (f'url("{alvo}")', f'image-set("{alvo}" 1x)'):
                with self.subTest(alvo=alvo, referencia=referencia):
                    css = self.gravar("estilo.css", f"a{{background:{referencia}}}".encode())
                    with self.assertRaises(ValueError) as erro:
                        P.bytes_estaticos(css, raiz=self.fonte)
                    self.assertIn(str(css), str(erro.exception))
                    self.assertIn(alvo, str(erro.exception))
        with mock.patch.object(P, "FONTE_ESTATICA", self.fonte):
            with self.assertRaises(ValueError):
                P.bytes_estaticos(css)

    def test_copia_nao_cria_diretorios_vazios_e_preserva_pasta_md(self):
        self.gravar("so-documentacao/leia.md", b"documentacao")
        self.gravar("pasta.md/icone.svg", b"<svg/>")
        (self.fonte / "vazia").mkdir()
        saida = self.raiz / "publicado"
        gerar_site.copiar_estaticos(self.fonte, saida)
        self.assertFalse((saida / "so-documentacao").exists())
        self.assertFalse((saida / "vazia").exists())
        self.assertEqual((saida / "pasta.md/icone.svg").read_bytes(), b"<svg/>")
        self.assertTrue(P.publicavel(Path("pasta.md/icone.svg")))
        for nome in (".oculto.svg", "pasta/.oculto.svg", ".pasta/a.svg", "FONTES.MD"):
            self.assertFalse(P.publicavel(Path(nome)), nome)

    def test_pagina_sem_favicon_nao_publica_link_ausente(self):
        for nome in ("estilo.css", "dados.js", "app.js"):
            self.gravar(nome, b"")
        with mock.patch.object(P, "FONTE_ESTATICA", self.fonte):
            self.assertNotIn('rel="icon"', P.pagina("Teste", "", "index.html"))

    def test_atributos_python_lf_preservam_precedencia_das_fixtures(self):
        caminho = Path(__file__).resolve().parents[1] / ".gitattributes"
        linhas = caminho.read_text(encoding="utf-8").splitlines()
        self.assertIn("*.py text eol=lf", linhas)
        self.assertEqual(linhas[-1], "tests/fixtures/** -text")
        self.assertTrue(linhas[-2].startswith("#"))

    def test_copia_recursiva_exclusoes_html_e_determinismo(self):
        self.gravar("fontes/aninhada/fonte.woff2", b"fonte")
        self.gravar("favicon.svg", b"<svg/>")
        script = self.gravar("app.js", b"// javascript\r\n")
        self.gravar("dados.js", b"// dados\n")
        self.gravar("estilo.css", b"a{src:url(fontes/aninhada/fonte.woff2)}\r\n")
        excluidos = (".oculto", ".pasta/a.svg", "fontes/.pasta/a.svg", "fontes/.oculto", "fontes/FONTES.md")
        for nome in excluidos:
            self.gravar(nome, b"nao publicar")
        saidas = [self.raiz / "primeira", self.raiz / "segunda"]
        for saida in saidas:
            gerar_site.copiar_estaticos(self.fonte, saida)
            self.assertEqual((saida / "fontes/aninhada/fonte.woff2").read_bytes(), b"fonte")
            for nome in excluidos:
                self.assertFalse((saida / nome).exists(), nome)
            self.assertFalse((saida / ".pasta").exists())
            self.assertFalse((saida / "fontes/.pasta").exists())
        arquivos = lambda pasta: {p.relative_to(pasta): p.read_bytes() for p in pasta.rglob("*") if p.is_file()}
        self.assertEqual(arquivos(saidas[0]), arquivos(saidas[1]))
        with mock.patch.object(P, "FONTE_ESTATICA", self.fonte):
            html = P.pagina("Teste", "", "index.html", prefixo="../")
            versao_css = self.versao((saidas[0] / "estilo.css").read_bytes())
            self.assertIn(f'href="../estilo.css?v={versao_css}"', html)
            self.assertIn(f'href="../favicon.svg?v={self.versao(b"<svg/>")}"', html)
            self.assertEqual(P.versao_estatica("app.js"), self.versao(script.read_bytes()))
            self.assertEqual(P.url_estatica("fontes/aninhada/fonte.woff2", "../"),
                             f"../fontes/aninhada/fonte.woff2?v={self.versao(b'fonte')}")
