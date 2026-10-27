"""Blocos da página inicial (coletor.site.inicio), com modelos sintéticos e sem rede."""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

from coletor.site import inicio as I
from coletor.site import paginas as P
from tests.test_geo import geo_completo

RAIZ = Path(__file__).resolve().parents[1]
ATUAL = "2025-2028"


def pessoa(slug: str, nome: str, legs: dict[str, dict]) -> dict:
    return {"slug": slug, "nome": nome, "mandatos": legs}


def modelo_base(**extra) -> dict:
    pessoas = [
        pessoa("bruno", "Bruno", {ATUAL: {"partido": "PA", "eleito": True}}),
        pessoa("alvaro", "Álvaro", {ATUAL: {"partido": "PB", "eleito": True}}),
        pessoa("carlos-silva", "Carlos Silva", {ATUAL: {"partido": "PA", "eleito": True}}),
        pessoa("carlos-silva-2", "Carlos Silva", {ATUAL: {"partido": "PC", "eleito": False}}),
        pessoa("ana", "ana", {ATUAL: {"partido": "PD", "eleito": True}}),
        pessoa("anterior", "Antiga", {"2021-2024": {"partido": "PA", "eleito": True}}),
    ]
    modelo = {"legislaturas": [{"id": "2021-2024"}, {"id": ATUAL}], "pessoas": {p["slug"]: p for p in pessoas},
              "projetos": [], "meta": {"coleta": {"em": "2026-10-19T09:30:00Z"}}}
    modelo.update(extra)
    return modelo


def memoria_sintetica() -> dict:
    return {"linha_do_tempo": [
        {"data": "1975-03-15", "titulo": "Fusão", "texto": "Texto B.", "fontes": [{"titulo": "Fonte", "url": "https://exemplo.test/b"}]},
        {"data": "1894", "data_fim": "1903", "titulo": "Capital <fora> & volta", "texto": "Texto <i>A</i> & mais.",
         "fontes": [{"titulo": "Arquivo & cia", "url": "https://exemplo.test/a?x=1&y=2"}]},
        {"data": "1573-11-22", "titulo": "Fundação", "texto": "Texto C.", "fontes": []},
    ]}


def ids(html: str) -> list[str]:
    return re.findall(r'\bid="([^"]+)"', html)


class TestHero(unittest.TestCase):
    def test_h1_e_abertura_iguais_aos_da_pagina_inicial_atual(self):
        # Sem pessoas: o placar de gerar_index exige métricas que não interessam aqui.
        modelo = modelo_base(pessoas={})
        index = P.gerar_index(modelo)
        h1_index, p_index = re.search(r"<h1[^>]*>(.*?)</h1>\s*<p>(.*?)</p>", index, re.DOTALL).groups()
        h1_hero, p_hero = re.search(r'<h1 id="t-hero">(.*?)</h1><p>(.*?)</p>', I.hero(modelo, P.url_estatica)).groups()
        self.assertEqual(h1_hero, h1_index)
        self.assertEqual(p_hero, p_index)
        self.assertEqual(h1_hero, "Leis que mudam a cidade, e quem as escreveu.")

    def test_estrutura_e_camadas_omitidas_sem_svg(self):
        with tempfile.TemporaryDirectory() as pasta, mock.patch.object(P, "FONTE_ESTATICA", Path(pasta)):
            html = I.hero(modelo_base(), P.url_estatica)
        self.assertTrue(html.startswith('<section class="hero" aria-labelledby="t-hero">'
                                        '<div class="ceu" data-ceu="tarde" aria-hidden="true"></div>'
                                        '<div class="hero-texto"><h1 id="t-hero">'))
        self.assertNotIn("camada", html)
        self.assertIn("Dados do SISCAM de 19/10/2026", html)

    def test_camadas_presentes_com_url_versionada(self):
        with tempfile.TemporaryDirectory() as pasta:
            fonte = Path(pasta)
            (fonte / "paisagem").mkdir()
            conteudo = {"fundo": b'<svg xmlns="http://www.w3.org/2000/svg"/>', "orla": b'<svg xmlns="http://www.w3.org/2000/svg"><g/></svg>'}
            for nome, dados in conteudo.items():
                (fonte / "paisagem" / f"{nome}.svg").write_bytes(dados)
            with mock.patch.object(P, "FONTE_ESTATICA", fonte):
                html = I.hero(modelo_base(), P.url_estatica)
        for nome, dados in conteudo.items():
            versao = hashlib.sha1(dados).hexdigest()[:10]
            self.assertIn(f'<div class="camada {nome}" style="--mascara:url(\'paisagem/{nome}.svg?v={versao}\')"></div>', html)
        for nome in ("sol", "baia", "promontorio"):
            self.assertNotIn(f"camada {nome}", html)
        # Ordem fixa das camadas, do fundo para a frente.
        self.assertLess(html.index("camada fundo"), html.index("camada orla"))


class TestQuemEMeuVereador(unittest.TestCase):
    def test_sem_legislatura_ou_membros_vazio(self):
        self.assertEqual(I.quem_e_meu_vereador({"legislaturas": [], "pessoas": {}}), "")
        self.assertEqual(I.quem_e_meu_vereador({}), "")
        modelo = modelo_base()
        modelo["legislaturas"].append({"id": "2029-2032"})
        self.assertEqual(I.quem_e_meu_vereador(modelo), "")

    def test_ordem_sem_acentos_e_nomes_repetidos(self):
        html = I.quem_e_meu_vereador(modelo_base())
        nomes = re.findall(r'<li><a href="vereadores/([^"]+)\.html">([^<]+)</a>', html)
        self.assertEqual(nomes, [("alvaro", "Álvaro"), ("ana", "ana"), ("bruno", "Bruno"),
                                 ("carlos-silva", "Carlos Silva"), ("carlos-silva-2", "Carlos Silva")])
        self.assertNotIn("vereadores/anterior.html", html)
        self.assertIn('<section class="quem-vereador" data-combobox aria-labelledby="t-quem">', html)
        self.assertIn('<h2 id="t-quem" class="h-secao">Quem é meu vereador?</h2>', html)
        self.assertIn('<details class="lista-vereadores"><summary>Ver os 5 vereadores da legislatura atual</summary>'
                      '<ul id="lista-vereadores">', html)
        self.assertIn('<a href="vereadores/bruno.html">Bruno</a> <span class="partido">PA</span></li>', html)
        self.assertIn('Carlos Silva</a> <span class="partido">PC</span> <span class="status">suplente em exercício</span>', html)

    def test_prefixo_e_escape(self):
        modelo = modelo_base()
        modelo["pessoas"] = {"x": pessoa("x", "Ana <b> & Cia", {ATUAL: {"partido": "P&<T>"}})}
        html = I.quem_e_meu_vereador(modelo, "../")
        self.assertIn('<a href="../vereadores/x.html">Ana &lt;b&gt; &amp; Cia</a> <span class="partido">P&amp;&lt;T&gt;</span>', html)
        self.assertNotIn("<b>", html)
        self.assertIn("Ver o vereador da legislatura atual", html)


def docs_mapa() -> list[dict]:
    return [{"tipo": "indicacao", "bairro": "Icaraí", "legislatura": ATUAL},
            {"tipo": "indicacao", "bairro": None, "legislatura": ATUAL},
            {"tipo": "indicacao", "bairro": "Badu", "legislatura": "2021-2024"},
            {"tipo": "mocao", "bairro": None, "legislatura": ATUAL}]


class TestMapaHome(unittest.TestCase):
    def test_sem_geometria_vazio(self):
        self.assertEqual(I.mapa_home(modelo_base(documentos=docs_mapa())), "")
        self.assertEqual(I.mapa_home(modelo_base(documentos=docs_mapa(), geo_bairros=None)), "")

    def test_sem_indicacoes_na_legislatura_vazio(self):
        modelo = modelo_base(documentos=[d for d in docs_mapa() if d["legislatura"] != ATUAL], geo_bairros=geo_completo())
        self.assertEqual(I.mapa_home(modelo), "")

    def test_mapa_da_legislatura_atual_com_atribuicao_unica(self):
        html = I.mapa_home(modelo_base(documentos=docs_mapa(), geo_bairros=geo_completo()))
        self.assertTrue(html.startswith('<section class="mapa-home" aria-labelledby="t-mapa-home"><h2 id="t-mapa-home"'))
        self.assertIn('class="mapa-bairros"', html)
        self.assertIn(f"Indicações por bairro, legislatura {ATUAL}", html)
        # Só as indicações da legislatura atual: Icaraí com 1, Badu fora, uma sem bairro.
        self.assertIn("50% sem bairro identificado (1 de 2 indicações)", html)
        self.assertIn("<title>Icaraí: 1 indicações</title>", html)
        self.assertIn("<title>Badu: 0 indicações</title>", html)
        self.assertEqual(html.count("https://www.openstreetmap.org/copyright"), 1)
        self.assertIn("base OSM: 2026-10-23T03:26:20Z", html)
        self.assertIn('<a href="atividades.html#bairros">', html)


class TestLinhaDoTempo(unittest.TestCase):
    def test_memoria_ausente_ou_vazia(self):
        self.assertEqual(I.linha_do_tempo(None), "")
        self.assertEqual(I.linha_do_tempo({}), "")
        self.assertEqual(I.linha_do_tempo({"linha_do_tempo": []}), "")
        with tempfile.TemporaryDirectory() as pasta:
            self.assertIsNone(I.carregar_memoria(Path(pasta)))
            (Path(pasta) / "config").mkdir()
            (Path(pasta) / "config" / "memoria.json").write_text(json.dumps(memoria_sintetica()), encoding="utf-8")
            self.assertEqual(I.carregar_memoria(Path(pasta)), memoria_sintetica())

    def test_ordem_cronologica_intervalo_e_escape(self):
        html = I.linha_do_tempo(memoria_sintetica())
        self.assertTrue(html.startswith('<section class="linha-tempo" aria-labelledby="t-linha">'
                                        '<h2 id="t-linha" class="h-secao">Niterói no tempo</h2>'
                                        '<div class="tabela-rolavel linha-rolavel" role="region" tabindex="0" aria-labelledby="t-linha"><ol>'))
        self.assertEqual(re.findall(r'<time datetime="([^"]+)">', html), ["1573-11-22", "1894", "1975-03-15"])
        self.assertIn('<time datetime="1573-11-22">22/11/1573</time>', html)
        self.assertIn('<time datetime="1894">1894–1903</time>', html)
        self.assertIn("<strong>Capital &lt;fora&gt; &amp; volta</strong>", html)
        self.assertIn("<p>Texto &lt;i&gt;A&lt;/i&gt; &amp; mais.</p>", html)
        self.assertIn('<a href="https://exemplo.test/a?x=1&amp;y=2">Arquivo &amp; cia</a>', html)
        self.assertNotIn("<fora>", html)
        self.assertNotIn("<i>", html)

    def test_memoria_real_em_ordem(self):
        memoria = I.carregar_memoria(RAIZ)
        self.assertIsNotNone(memoria)
        html = I.linha_do_tempo(memoria)
        datas = re.findall(r'<time datetime="([^"]+)">', html)
        self.assertEqual(len(datas), len(memoria["linha_do_tempo"]))
        self.assertEqual(datas, sorted(datas))
        self.assertIn('<time datetime="1894">1894–1903</time>', html)
        self.assertEqual(html.count("<li>"), len(memoria["linha_do_tempo"]))


class TestBlocosJuntos(unittest.TestCase):
    def test_ids_unicos_e_saida_deterministica(self):
        modelo = modelo_base(documentos=docs_mapa(), geo_bairros=geo_completo())
        memoria = I.carregar_memoria(RAIZ)

        def tudo() -> str:
            return (I.hero(modelo, P.url_estatica) + I.quem_e_meu_vereador(modelo) + I.mapa_home(modelo)
                    + I.linha_do_tempo(memoria))

        html = tudo()
        lista = ids(html)
        repetidos = [i for i, n in Counter(lista).items() if n > 1]
        self.assertEqual(repetidos, [])
        for esperado in ("t-hero", "t-quem", "t-mapa-home", "t-linha", "lista-vereadores"):
            self.assertIn(esperado, lista)
        self.assertEqual(tudo(), html)


if __name__ == "__main__":
    unittest.main()
