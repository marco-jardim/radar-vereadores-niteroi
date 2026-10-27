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
    def setUp(self):
        temporario = tempfile.TemporaryDirectory(prefix="estaticos-", dir=Path(__file__).resolve().parents[1])
        self.addCleanup(temporario.cleanup)
        self.raiz = Path(temporario.name)
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
        self.assertEqual(P.css_publicado(texto, self.fonte), esperado)

    def test_urls_externas_consultas_e_fragmentos_intactos(self):
        texto = '''a{a:url(data:image/svg+xml;base64,AAAA);b:url("https://exemplo.org/a.svg");
        c:url(http://exemplo.org/a.svg);d:url(//exemplo.org/a.svg);e:url('a.svg?v=123#x');
        f:url(#emblema);g:url(/a.svg)}'''
        self.assertEqual(P.css_publicado(texto, self.fonte), texto)

    def test_comentarios_e_strings_nao_sao_reescritos(self):
        texto = '''/* url(ausente.svg) */ a{content:"url(ausente.svg)"}'''
        self.assertEqual(P.css_publicado(texto, self.fonte), texto)

    def test_alvo_ausente_informa_css_e_alvo(self):
        css = self.gravar("css/tema.css", b"a{background:url(../ausente.svg)}")
        with self.assertRaises(ValueError) as erro:
            P.bytes_estaticos(css)
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
        self.assertEqual(P.bytes_estaticos(principal), (saida / "estilo.css").read_bytes())

    def test_ciclo_css_falha_sem_recursao_infinita(self):
        primeiro = self.gravar("a.css", b"@import url(b.css);")
        self.gravar("b.css", b"@import url(a.css);")
        with self.assertRaisesRegex(ValueError, "Ciclo de recursos CSS"):
            P.bytes_estaticos(primeiro)

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
