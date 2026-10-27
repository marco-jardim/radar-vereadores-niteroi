"""Partido ao lado do nome do vereador e bloco de perfil da ficha (config/perfis.json).

Dados sintéticos em diretórios temporários, sem rede; só a última classe lê o config versionado.
"""
from __future__ import annotations

import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from coletor import gerar_site as GS
from coletor import validar as V
from coletor.site import graficos as G
from coletor.site import modelo as M
from coletor.site import pagina_sessoes as S
from coletor.site import paginas as P
from tests.test_documentos_site import DOCS, URL, preparar_raiz

RAIZ = Path(__file__).resolve().parents[1]
FONTE = {"titulo": "Eleição municipal — Wikipédia", "url": "https://pt.wikipedia.org/wiki/Exemplo"}


def pl(id_: int, numero: str, data: str, autoria: list[dict]) -> dict:
    return {"id": id_, "numero": numero, "ano": int(numero.split("/")[1]), "data": data, "data_protocolo": data,
            "ementa": f"Cria o programa municipal número {id_} de apoio às feiras livres", "situacao": "",
            "desfecho": "em_tramitacao", "lei": None, "autoria": autoria, "tramitacoes": [], "url": URL.format(id=id_)}


def autoria(nome: str, papel: str = "Autor") -> dict:
    return {"id": 1, "nome": nome, "origem": "Vereador", "papel": papel}


PROPOSICOES = [
    pl(20, "20/2022", "2022-05-10", [autoria("ANA MARIA TESTE"), autoria("BIA SUPLENTE", "Co-Autor")]),
    pl(21, "21/2025", "2025-05-10", [autoria("ANA MARIA TESTE")]),
    pl(22, "22/2023", "2023-03-01", [autoria("BIA SUPLENTE")]),
    pl(23, "23/2023", "2023-03-02", [autoria("CAIO SEM PARTIDO")]),
]
PERFIS = {"fonte_padrao": FONTE, "vereadores": {
    "BIA SUPLENTE": {"mandatos": {"2021-2024": {"partido": "PQ", "votos": 1234, "situacao": "suplente", "fontes": [FONTE]}},
                     "eleicoes": [], "camara": None, "site": None, "redes": []},
}}


def montar(proposicoes=PROPOSICOES, perfis: dict | None = PERFIS, documentos=DOCS) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        raiz = Path(tmp)
        preparar_raiz(raiz, documentos)
        if perfis is not None:
            (raiz / "config" / "perfis.json").write_text(json.dumps(perfis, ensure_ascii=False), encoding="utf-8")
        with mock.patch.object(M, "RAIZ", raiz), \
                mock.patch.object(M, "carregar_proposicoes", lambda: [dict(p) for p in proposicoes]), \
                mock.patch.object(M, "carregar_curadoria", lambda: {}), \
                mock.patch("coletor.classificar.CONFIANCA_MINIMA", 0.75):
            return M.montar_modelo()


def projeto(modelo: dict, numero: str) -> dict:
    return next(p for p in modelo["projetos"] if p["numero"] == numero)


class TestPartidoNoModelo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.modelo = montar()

    def test_partido_da_legislatura_do_projeto(self):
        # Ana: PV na eleição de 2020 e PX na de 2024 (CFG de test_documentos_site).
        self.assertEqual(projeto(self.modelo, "20/2022")["autores"][0]["partido"], "PV")
        self.assertEqual(projeto(self.modelo, "21/2025")["autores"][0]["partido"], "PX")
        self.assertEqual(M.partido_em(self.modelo, "ana-maria-teste", "2021-2024"), "PV")
        self.assertEqual(M.partido_em(self.modelo, "ana-maria-teste", "2025-2028"), "PX")
        self.assertEqual(M.partido_atual(self.modelo, "ana-maria-teste"), "PX")

    def test_suplente_recebe_o_partido_dos_perfis(self):
        bia = self.modelo["pessoas"]["bia-suplente"]
        self.assertFalse(bia["mandatos"]["2021-2024"]["eleito"])
        self.assertEqual(bia["mandatos"]["2021-2024"]["partido"], "PQ")
        self.assertEqual(projeto(self.modelo, "20/2022")["autores"][1]["partido"], "PQ")
        self.assertEqual(bia["perfil"]["mandatos"]["2021-2024"], {"partido": "PQ", "votos": 1234, "situacao": "suplente"})
        self.assertEqual(bia["perfil"]["fontes"], [FONTE])  # fonte do mandato e fonte padrão, sem repetir

    def test_sem_partido_conhecido_nao_ha_span(self):
        p = projeto(self.modelo, "23/2023")
        self.assertEqual(p["autores"][0]["partido"], "")
        html = P.item_projeto(p, "")
        self.assertRegex(html, r'href="vereadores/caio-sem-partido\.html">[^<]*</a>')
        self.assertNotIn('class="partido"', html)
        self.assertIsNone(self.modelo["pessoas"]["caio-sem-partido"]["perfil"])

    def test_chips_de_projetos_com_partido_dentro_do_link(self):
        html = P.item_projeto(projeto(self.modelo, "20/2022"), "")
        self.assertIn('<a class="chip chip-principal" href="vereadores/ana-maria-teste.html">Ana Teste<span class="partido">PV</span></a>', html)
        self.assertIn('<li>Bia Suplente<span class="partido">PQ</span></li>', html)
        cartao = P.cartao_lei({**projeto(self.modelo, "21/2025"), "lei": {"numero": 1, "data": "2025-06-01"},
                               "desfecho": "virou_lei"}, "")
        self.assertIn('Ana Teste<span class="partido">PX</span></a></div>', cartao)

    def test_documentos_com_partido_da_legislatura_do_documento(self):
        d = next(d for d in self.modelo["documentos"] if d["id"] == 900001)
        html = P.autores_documento_html(d, "")
        self.assertIn('<a class="chip" href="vereadores/ana-maria-teste.html">Ana Teste<span class="partido">PX</span></a>', html)
        self.assertIn('<span class="chip chip-exec">Mesa Diretora 2025/2026</span>', html)
        linha = next(l for l in GS.linhas_documentos(self.modelo, GS.dicionario_documentos(self.modelo)) if l["id"] == 900001)
        self.assertIn(("ana-maria-teste", "Ana Teste", 1, "PX"), linha["au"])
        self.assertTrue(any(len(a) == 3 for a in linha["au"]), "sem partido, a pessoa local fica com três campos")

    def test_link_autor_e_nota_dos_eleitos_sem_lei(self):
        self.assertEqual(P.link_autor(self.modelo, "ana-maria-teste", "", "2021-2024"),
                         '<a href="vereadores/ana-maria-teste.html">Ana Teste<span class="partido">PV</span></a>')
        self.assertEqual(P.link_autor(self.modelo, "ana-maria-teste", ""), '<a href="vereadores/ana-maria-teste.html">Ana Teste</a>')
        index = P.gerar_index(self.modelo)
        self.assertIn('<strong>Ana Teste</strong> <span class="partido">PX</span>', index)

    def test_ficha_com_partido_no_titulo_e_perfil(self):
        html = P.gerar_vereador(self.modelo, self.modelo["pessoas"]["bia-suplente"])
        self.assertIn('<h1>Bia Suplente<span class="partido">PQ</span></h1>', html)
        self.assertIn('<section class="perfil" aria-labelledby="t-perfil">', html)
        self.assertIn('<dt>Mandato 2021-2024</dt><dd>suplente pelo PQ com 1.234 votos</dd>', html)
        self.assertIn(f'<p class="perfil-fontes">Fontes: <a href="{FONTE["url"]}">', html)
        self.assertLess(html.index('class="perfil"'), html.index('class="mandato"'))


class TestPerfilDaFicha(unittest.TestCase):
    MODELO = {"legislaturas": [{"id": "2021-2024"}, {"id": "2025-2028"}]}

    def pessoa(self, perfil: dict | None, mandatos: dict | None = None) -> dict:
        return {"slug": "x", "mandatos": mandatos or {}, "perfil": M.perfil_da_pessoa(perfil, None)}

    def test_textos(self):
        self.assertEqual(P.texto_mandato("eleito", "PL", 16369), "eleito pelo PL com 16.369 votos")
        self.assertEqual(P.texto_mandato("suplente", "PDT", None), "suplente pelo PDT")
        self.assertEqual(P.texto_eleicao({"ano": 2026, "cargo": "Deputado Estadual", "uf": "RJ", "partido": "PL",
                                          "votos": 12345, "resultado": "Eleito por média"}),
                         "2026 · Deputado Estadual (RJ) · PL · 12.345 votos · Eleito por média")
        self.assertEqual(P.texto_eleicao({"ano": 2022, "cargo": "Deputado Federal", "uf": "RJ", "partido": "PSOL",
                                          "votos": None, "resultado": "Não eleito"}),
                         "2022 · Deputado Federal (RJ) · PSOL · Não eleito")

    def test_bloco_completo_mandatos_mais_recentes_primeiro(self):
        perfil = {
            "mandatos": {"2021-2024": {"partido": "DEM", "votos": 2411, "situacao": "eleito", "fontes": [FONTE]},
                         "2025-2028": {"partido": "PL", "votos": 6750, "situacao": "eleito", "fontes": [FONTE]}},
            "eleicoes": [{"ano": 2022, "cargo": "Deputado Estadual", "uf": "RJ", "partido": "DEM", "votos": None,
                          "resultado": "Suplente", "fonte": {"titulo": "TSE", "url": "https://dadosabertos.tse.jus.br/x"}}],
            "camara": "https://www.cmniteroi.rj.gov.br/vereador/x", "site": None,
            "redes": [{"rede": "instagram", "url": "https://www.instagram.com/x", "fonte": "https://www.cmniteroi.rj.gov.br/vereador/x"}],
        }
        html = P.secao_perfil(self.MODELO, self.pessoa(perfil))
        self.assertLess(html.index("Mandato 2025-2028"), html.index("Mandato 2021-2024"))
        self.assertIn("<dd>eleito pelo PL com 6.750 votos</dd>", html)
        self.assertIn('<ul class="perfil-eleicoes"><li>2022 · Deputado Estadual (RJ) · DEM · Suplente</li></ul>', html)
        self.assertIn('<dt>Página na Câmara</dt><dd><a href="https://www.cmniteroi.rj.gov.br/vereador/x">cmniteroi.rj.gov.br</a></dd>', html)
        self.assertNotIn("Site oficial", html)
        self.assertIn('<ul class="perfil-redes"><li><a href="https://www.instagram.com/x">Instagram</a></li></ul>', html)
        self.assertIn('href="https://dadosabertos.tse.jus.br/x">TSE</a>', html)
        self.assertNotIn("target=", html)  # links externos sem nova aba, como os demais além do SISCAM

    def test_omite_linhas_e_secao_vazias(self):
        self.assertEqual(P.secao_perfil(self.MODELO, self.pessoa(None)), "")
        sem_partido = self.pessoa(None, {"2025-2028": {"partido": "", "eleito": False}})
        self.assertEqual(P.secao_perfil(self.MODELO, sem_partido), "")
        so_config = P.secao_perfil(self.MODELO, self.pessoa(None, {"2025-2028": {"partido": "PX", "eleito": True}}))
        self.assertIn("<dd>eleito pelo PX</dd>", so_config)
        self.assertNotIn("perfil-fontes", so_config)

    def test_escapa_textos(self):
        perfil = {"mandatos": {"2025-2028": {"partido": "P<&>", "situacao": "eleito", "fontes": [FONTE]}}}
        html = P.secao_perfil(self.MODELO, self.pessoa(perfil))
        self.assertIn("eleito pelo P&lt;&amp;&gt;", html)
        self.assertEqual(P.partido_html("P<&>"), '<span class="partido">P&lt;&amp;&gt;</span>')
        self.assertEqual(P.partido_html(""), "")


class TestPartidoEmSessoesEGraficos(unittest.TestCase):
    def modelo(self) -> dict:
        leg = {"id": "2025-2028", "rotulo": "2025–2028", "anos": [2025]}
        return {"pessoas": {"ana": {"nome": "Ana", "mandatos": {"2025-2028": {"partido": "PX", "eleito": True}}}},
                "perfis": {"bia": {"mandatos": {"2025-2028": {"partido": "PQ"}}}},
                "sessoes": {"legislaturas": [leg], "por_pessoa": {
                    "bia": {"nome": "Bia Suplente", "condicao": "suplente em exercício", "sem_pagina": True, "2025-2028": {}}}}}

    def test_nomes_das_sessoes(self):
        modelo = self.modelo()
        self.assertEqual(S.leg_do_ano(modelo, 2025), "2025-2028")
        self.assertEqual(S._nome(modelo, "ana", chip=True, leg_id="2025-2028"),
                         '<a class="chip" href="vereadores/ana.html">Ana<span class="partido">PX</span></a>')
        self.assertEqual(S._nome(modelo, "ana", chip=True), '<a class="chip" href="vereadores/ana.html">Ana</a>')
        self.assertEqual(S._nome(modelo, "bia", chip=True, leg_id="2025-2028"),
                         '<span class="chip">Bia Suplente<span class="partido">PQ</span>'
                         '<span class="status">suplente em exercício</span></span>')

    def test_pessoas_das_votacoes_com_quinto_campo(self):
        modelo = self.modelo()
        self.assertEqual(GS.pessoa_votacao(modelo, "ana", 2025), ["ana", "Ana", 1, "", "PX"])
        modelo["pessoas"]["ana"]["mandatos"]["2025-2028"]["partido"] = ""
        self.assertEqual(len(GS.pessoa_votacao(modelo, "ana", 2025)), 4)

    def test_graficos_levam_o_partido_so_no_tooltip_e_na_tabela(self):
        html = G.barras_horizontais("Teste", "", [{"rotulo": "Ana", "link": "vereadores/ana.html", "partido": "PX", "v": 3}],
                                    [("Leis", "c-efeito", "v")])
        self.assertIn('data-tip="Ana (PX) · Leis: 3"', html)
        self.assertIn(">Ana</text></a>", html)
        self.assertIn(">Ana (PX)</th>", html)
        pontos = G.dispersao("Teste", "", [{"x": 2, "y": 1, "rotulo": "Ana", "link": "vereadores/ana.html", "partido": "PX"}], "x", "y")
        self.assertIn('aria-label="Ana (PX): 2 projetos, 1 leis com efeito"', pontos)


class TestValidarPerfis(unittest.TestCase):
    CFG = {"legislaturas": [{"id": "2025-2028", "eleitos": [{"nome": "Ana", "siscam": "ANA MARIA TESTE", "partido": "PX"}]}]}

    def perfil(self, **extra) -> dict:
        base = {"mandatos": {"2025-2028": {"partido": "PX", "votos": 10, "situacao": "eleita", "fontes": [FONTE]}},
                "eleicoes": [], "camara": None, "site": None, "redes": []}
        return {**base, **extra}

    def validar(self, vereadores: dict, texto: str | None = None, cfg: dict | None = CFG) -> list[str]:
        dados = {"_leia_me": "x", "fonte_padrao": FONTE, "vereadores": vereadores}
        with tempfile.TemporaryDirectory() as tmp:
            arq = Path(tmp) / "perfis.json"
            arq.write_bytes((texto if texto is not None else json.dumps(dados, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
            return V.validar_perfis(arq, cfg)

    def test_valido_e_ausente(self):
        self.assertEqual(self.validar({"ANA MARIA TESTE": self.perfil()}), [])
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()) as erro:
            self.assertEqual(V.validar_perfis(Path(tmp) / "perfis.json", self.CFG), [])
        self.assertIn("perfis.json", erro.getvalue())

    def test_formato_canonico(self):
        texto = json.dumps({"vereadores": {"ANA MARIA TESTE": self.perfil()}}, ensure_ascii=False) + "\n"
        self.assertTrue(any("fora do formato" in p for p in self.validar({}, texto)))

    def test_erros(self):
        casos = {
            "maiúsculas": ({"Ana Maria Teste": self.perfil()}, "maiúsculas"),
            "legislatura": ({"ANA MARIA TESTE": self.perfil(mandatos={"1999-2002": {"partido": "PX", "situacao": "suplente",
                                                                                    "fontes": [FONTE]}})}, "inexistente"),
            "partido": ({"ANA MARIA TESTE": self.perfil(mandatos={"2025-2028": {"partido": "PY", "situacao": "eleita",
                                                                                "fontes": [FONTE]}})}, "difere"),
            "vazio": ({"ANA MARIA TESTE": self.perfil(mandatos={"2025-2028": {"partido": "", "situacao": "eleita",
                                                                              "fontes": [FONTE]}})}, "'partido'"),
            "votos": ({"ANA MARIA TESTE": self.perfil(mandatos={"2025-2028": {"partido": "PX", "votos": 0, "situacao": "eleita",
                                                                              "fontes": [FONTE]}})}, "'votos'"),
            "situacao": ({"ANA MARIA TESTE": self.perfil(mandatos={"2025-2028": {"partido": "PX", "situacao": "eleitx",
                                                                                 "fontes": [FONTE]}})}, "'situacao'"),
            "suplente eleito": ({"BIA": self.perfil(mandatos={"2025-2028": {"partido": "PQ", "situacao": "eleito",
                                                                            "fontes": [FONTE]}})}, "suplente"),
            "fonte": ({"ANA MARIA TESTE": self.perfil(mandatos={"2025-2028": {"partido": "PX", "situacao": "eleita",
                                                                              "fontes": [{"titulo": "t", "url": "http://x.org"}]}})}, "HTTPS"),
            "camara": ({"ANA MARIA TESTE": self.perfil(camara="http://cmniteroi.rj.gov.br")}, "'camara'"),
            "rede": ({"ANA MARIA TESTE": self.perfil(redes=[{"rede": "orkut", "url": "https://a.org", "fonte": "https://b.org"}])}, "'rede'"),
            "fonte da rede": ({"ANA MARIA TESTE": self.perfil(redes=[{"rede": "x", "url": "https://x.com/a"}])}, "'fonte'"),
            "campo": ({"ANA MARIA TESTE": self.perfil(partido_fim={})}, "desconhecidos"),
        }
        for nome, (vereadores, trecho) in casos.items():
            with self.subTest(caso=nome):
                problemas = self.validar(vereadores)
                self.assertTrue(any(trecho in p for p in problemas), problemas)

    def test_eleicoes(self):
        boa = {"ano": 2026, "cargo": "Deputado Estadual", "uf": "RJ", "partido": "PL", "votos": None,
               "resultado": "Eleito por média", "fonte": {"titulo": "TSE", "url": "https://dadosabertos.tse.jus.br/x"}}
        antiga = {**boa, "ano": 2022, "votos": 0}
        pre_tse = {**boa, "ano": 1988, "fonte": {"titulo": "Wikipédia", "url": "https://pt.wikipedia.org/wiki/x"}}
        self.assertEqual(self.validar({"ANA MARIA TESTE": self.perfil(eleicoes=[boa, antiga, pre_tse])}), [])
        self.assertEqual(self.validar({"ANA MARIA TESTE": self.perfil(eleicoes=[{**boa, "ano": 1945}])}), [])
        casos = {"ordem": ([antiga, boa], "mais recente"), "ano": ([{**boa, "ano": 1944}], "entre 1945 e 2100"),
                 "ano futuro": ([{**boa, "ano": 2101}], "'ano'"), "ano texto": ([{**boa, "ano": "1988"}], "'ano'"),
                 "uf": ([{**boa, "uf": "rj"}], "'uf'"), "votos": ([{**boa, "votos": -1}], "'votos'"),
                 "cargo": ([{**boa, "cargo": ""}], "cargo"), "fonte": ([{**boa, "fonte": {"titulo": "TSE", "url": "http://tse.jus.br"}}], "HTTPS")}
        for nome, (eleicoes, trecho) in casos.items():
            with self.subTest(caso=nome):
                problemas = self.validar({"ANA MARIA TESTE": self.perfil(eleicoes=eleicoes)})
                self.assertTrue(any(trecho in p for p in problemas), problemas)


class TestPerfisVersionados(unittest.TestCase):
    def test_config_versionado_valido(self):
        cfg = json.loads((RAIZ / "config/vereadores.json").read_text(encoding="utf-8"))
        self.assertEqual(V.validar_perfis(RAIZ / "config/perfis.json", cfg), [])

    def test_mesmos_campos_para_todos(self):
        dados = json.loads((RAIZ / "config/perfis.json").read_text(encoding="utf-8"))
        for nome, perfil in dados["vereadores"].items():
            with self.subTest(vereador=nome):
                self.assertEqual(list(perfil), ["mandatos", "eleicoes", "camara", "site", "redes"])
                self.assertTrue(re.fullmatch(r"[A-ZÀ-Ý0-9 .\-]+", nome), nome)


if __name__ == "__main__":
    unittest.main()
