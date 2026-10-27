"""Histórico eleitoral e tabela neutra de atividade, com fontes sintéticas offline."""
from __future__ import annotations

import copy
import unittest
from datetime import date

from coletor.site import mandatos as M
from coletor.site import paginas as P
from coletor.site.modelo_sessoes import montar_sessoes
from tests.test_modelo_sessoes import LEG, frequencia, modelo_minimo, sessao
from tests.test_tabelas_empilhaveis import ContratoEmpilhavel
from tests.test_tabelas_rolaveis import ContratoTabelas


def eleicao(ano: int, cargo: str = "Vereador", resultado: str = "Eleito por média") -> dict:
    return {"ano": ano, "cargo": cargo, "resultado": resultado}


def modelo_tabela() -> dict:
    modelo = modelo_minimo(suplentes=())
    ana = modelo["pessoas"]["ana"]
    ana["perfil"] = {"eleicoes": [eleicao(2028), eleicao(2024), eleicao(2020), eleicao(1988)],
                     "mandatos": {LEG: {"situacao": "eleita"}}}
    ana["mandatos"][LEG].update(partido="PV", metricas={"apresentados": 12})
    modelo["perfis"] = {"ana": ana["perfil"]}
    modelo["cfg"]["mesa"] = [{"siscam": "Ana", "legislatura": LEG, "cargo": "Presidente",
                              "bienio": "2025-2026", "fonte": "https://example.org/mesa"}]
    modelo["cfg"]["afastamentos"] = [
        {"siscam": "Ana", "legislatura": LEG, "natureza": "cargo", "cargo": "Secretária",
         "inicio": "2025-03-01", "fim": "2025-04-01", "fonte": "https://example.org/cargo"},
        {"siscam": "Ana", "legislatura": LEG, "natureza": "licenca", "cargo": "Licença",
         "fonte": "https://example.org/licenca"}]
    modelo["atividade"] = {"ana": {"por_leg": {LEG: {"tipos": {"requerimento": 8, "indicacao": 4}}}}}
    modelo["sessoes"] = {
        "exercicio": {LEG: {"total": 20, "primeira": "2025-01-01", "ultima": "2026-01-01"}},
        "por_pessoa": {
            "ana": {LEG: {"presenca": {"listadas": 10, "denominador": 10, "pct": 80},
                          "participacao": {"votou": 8, "possiveis": 12, "presidindo": 2}}},
            "bruno": {LEG: {"presenca": {"listadas": 1, "denominador": 1, "pct": 100}}},
            "suplente-nova": {LEG: {"nome": "Suplente <Nova>", "condicao": "suplente em exercício",
                                    "presenca": {"listadas": 3, "denominador": 3, "pct": None}}}}}
    return modelo


class TestMandatos(unittest.TestCase):
    def test_vitorias_apenas_para_vereador_sem_resultado_legado(self):
        perfil = {"eleicoes": [eleicao(1992, resultado="ELEITO"), eleicao(1988), eleicao(1988),
                               eleicao(2024, resultado="eleito por QP"), eleicao(2020, resultado="Suplente"),
                               eleicao(2016, resultado="Média"), eleicao(2010, "Deputado Estadual")]}
        self.assertEqual(M.anos_eleito(perfil), [1988, 1992, 2024])
        self.assertEqual(M.anos_eleito(perfil, 2020), [1988, 1992])
        self.assertEqual(M.anos_eleito({}), [])

    def test_ficha_linha_anos_ordenados_e_omissao(self):
        pessoa = {"perfil": {"eleicoes": [eleicao(2024), eleicao(1988)]}}
        html = P.secao_perfil({}, pessoa)
        self.assertIn("Eleito vereador 2 vezes: 1988, 2024", html)
        pessoa["perfil"]["eleicoes"] = [eleicao(2024)]
        self.assertIn("Eleito vereador 1 vez: 2024", P.secao_perfil({}, pessoa))
        pessoa["perfil"]["eleicoes"] = [eleicao(2024, resultado="Suplente")]
        self.assertNotIn("Eleito vereador", P.secao_perfil({}, pessoa))

    def test_formulas_usam_listadas_nao_denominador_efetivo(self):
        modelo = modelo_tabela()
        modelo["sessoes"]["por_pessoa"]["ana"][LEG]["presenca"]["denominador"] = 9
        antes = copy.deepcopy(modelo)
        linhas = M.linhas_mandatos(modelo, modelo["legislaturas"][0])
        ana, bruno, suplente = linhas
        meses = 365 / (365.25 / 12) * 10 / 20
        self.assertAlmostEqual(ana["meses"], meses)
        self.assertAlmostEqual(ana["pls"], 12 / meses)
        self.assertAlmostEqual(ana["pedidos"], 12 / meses)
        self.assertEqual(ana["eleicoes"], 3)
        self.assertEqual(ana["anos"], [1988, 2020, 2024])
        self.assertIsNone(ana["presenca"])
        self.assertEqual(ana["nominais"], 80)
        self.assertTrue(ana["cargo"])
        self.assertEqual(ana["situacao"], "eleita")
        self.assertIsNone(bruno["eleicoes"])
        self.assertIsNone(bruno["nominais"])
        self.assertFalse(suplente["pagina"])
        self.assertEqual(suplente["situacao"], "suplente em exercício")
        self.assertEqual(modelo, antes)

    def test_cobertura_reusa_inclusao_e_intervalo_de_todas_deliberativas(self):
        registros = [sessao(1, data="2026-01-01", frequencia=[frequencia("Ana")]),
                     sessao(2, data="2026-01-02", frequencia=[frequencia("Ana", "Ausência Justificada")]),
                     sessao(3, data="2026-02-01"),
                     sessao(4, data="2026-03-01", tipo="solene", frequencia=[frequencia("Ana")])]
        modelo = modelo_minimo(suplentes=())
        modelo["sessoes"] = montar_sessoes(modelo, registros, {})
        self.assertEqual(modelo["sessoes"]["exercicio"][LEG],
                         {"total": 2, "primeira": "2026-01-01", "ultima": "2026-02-01"})
        ana = M.linhas_mandatos(modelo, modelo["legislaturas"][0])[0]
        self.assertEqual(ana["sessoes"], 2)
        self.assertAlmostEqual(ana["meses"], (date(2026, 2, 1) - date(2026, 1, 1)).days / (365.25 / 12))

    def test_ausencia_de_cobertura_e_intervalo_nulo_nao_gera_taxas(self):
        modelo = modelo_tabela()
        modelo["sessoes"]["exercicio"] = {}
        for l in M.linhas_mandatos(modelo, modelo["legislaturas"][0]):
            self.assertIsNone(l["pls"])
            self.assertIsNone(l["pedidos"])
        modelo["sessoes"]["exercicio"][LEG] = {"total": 20, "primeira": "2026-01-01", "ultima": "2026-01-01"}
        self.assertIsNone(M.linhas_mandatos(modelo, modelo["legislaturas"][0])[0]["pls"])

    def test_contagem_limitada_ao_ano_eleitoral_da_legislatura(self):
        modelo = modelo_tabela()
        leg = {"id": "2021-2024", "inicio": "2021-01-01"}
        modelo["pessoas"]["ana"]["mandatos"][leg["id"]] = {"eleito": True}
        linha = M.linhas_mandatos(modelo, leg)[0]
        self.assertEqual(linha["anos"], [1988, 2020])
        self.assertEqual(linha["eleicoes"], 2)
        self.assertFalse(linha["cargo"])

    def test_renderizador_neutro_acessivel_e_progressivo(self):
        html = M.secao_mandatos(modelo_tabela())
        ContratoTabelas.conferir_tabelas(self, html)
        ContratoEmpilhavel.conferir_empilhamento(self, html)
        for coluna in M.COLUNAS:
            self.assertIn(P.esc(coluna), html)
            self.assertIn(f'data-label="{P.esc(coluna)}"', html)
        for chave, _ in M.ORDENS:
            self.assertIn(f'data-{chave}=', html)
        self.assertIn('data-cargo="1"', html)
        self.assertIn('data-eleicoes=""', html)
        self.assertIn('data-controles-mandatos hidden', html)
        self.assertIn('title="Eleições para vereador: 1988, 2020, 2024"', html)
        self.assertIn('Ana<span class="partido">PV</span>', html)
        self.assertIn('href="vereadores/ana.html"', html)
        self.assertNotIn('href="vereadores/suplente-nova.html"', html)
        self.assertIn('Suplente &lt;Nova&gt;', html)
        self.assertIn('10 de 20', html)
        self.assertIn('80,0% (2 presidindo)', html)
        self.assertIn('1 licença registrada', html)
        for fonte in ("mesa", "cargo", "licenca"):
            self.assertIn(f'href="https://example.org/{fonte}"', html)
        for texto in ("estimativa pelas listas", "não mede qualidade", "relatorias", "articulação política",
                      "Mesa Diretora e no Executivo", "Wikipédia", "TSE", "metodologia.html#sessoes"):
            self.assertIn(texto, html)
        for texto in ("menos", "mais produtivo", "veteranos", "correlação"):
            self.assertNotIn(texto, html.casefold())
        self.assertLess(html.index('data-nome="Ana"'), html.index('data-nome="Bruno"'))
        self.assertEqual(M.secao_mandatos({"pessoas": {}, "legislaturas": []}), "")
