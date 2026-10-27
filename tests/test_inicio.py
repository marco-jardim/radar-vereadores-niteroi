"""Blocos da página inicial (coletor.site.inicio), com modelos sintéticos e sem rede."""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

from coletor import gerar_site
from coletor import novidades as N
from coletor.site import inicio as I
from coletor.site import paginas as P
from coletor.site.pagina_memoria import gerar_memoria
from tests import test_tabelas_rolaveis
from tests.test_design_tokens import compor, declaracoes, luminancia, regras, rgba, sem_comentarios
from tests.test_geo import geo_completo

RAIZ = Path(__file__).resolve().parents[1]
ATUAL = "2025-2028"
CSS_INICIO = P.FONTE_ESTATICA / "inicio.css"
FASES_CEU = ("madrugada", "manha", "tarde", "por-do-sol", "noite")
CHAVES_FASE = ("--ceu-1", "--ceu-2", "--sol", "--sol-x", "--sol-y", "--camada-1", "--camada-2", "--camada-3", "--camada-4",
               "--veu", "--h1")
# Marcadores das seções da home, na ordem do plano.
ORDEM_HOME = ('id="t-hero"', 'id="t-quem"', 'class="tiles"', 'id="t-destaques"', 'id="t-mapa-home"', 'id="t-placar"',
              'id="t-linha"', 'id="fm-titulo"', 'class="convite"')
ALT_OG = "Paisagem de Niterói ao pôr do sol vista da baía, com a marca do Radar dos Vereadores"
KIB = 1024


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
                                        f'<script>{I.SCRIPT_CEU}</script>'
                                        '<div class="hero-texto"><h1 id="t-hero">'))
        self.assertNotIn("camada", html)
        self.assertIn("Dados do SISCAM de 19/10/2026", html)

    def test_script_do_ceu_pequeno_e_com_a_tabela_de_inicio_js(self):
        script = I.SCRIPT_CEU
        self.assertLessEqual(len(script.encode("utf-8")), 300)
        self.assertNotIn("</", script)
        # Nada global: bloco com let, Intl com fuso de São Paulo e fallback UTC−3, tudo sob try/catch.
        self.assertTrue(script.startswith("{let ") and script.endswith("}"))
        self.assertIn('timeZone:"America/Sao_Paulo"', script)
        self.assertIn("(d.getUTCHours()+21)%24", script)
        self.assertEqual(script.count("try{"), script.count("catch(e){}"))
        self.assertTrue(script.endswith("}catch(e){}}"))
        # Mesmos limites [início, fim) de FASES em inicio.js.
        js = (P.FONTE_ESTATICA / "inicio.js").read_text(encoding="utf-8")
        fases_js = [(int(h), nome) for h, nome in
                    re.findall(r'\[(\d+), "([a-z-]+)"\]', js.split("var FASES = ", 1)[1].split(";", 1)[0])]
        tabela = [(int(h), nome) for h, nome in re.findall(r'h<(\d+)\?"([a-z-]+)":', script)]
        ultima = re.search(r':"([a-z-]+)"\}catch', script).group(1)
        self.assertEqual(tabela + [(24, ultima)], fases_js)
        self.assertEqual([nome for _, nome in fases_js], list(FASES_CEU))

    def test_script_do_ceu_logo_apos_o_ceu(self):
        html = I.hero(modelo_base(), P.url_estatica)
        self.assertEqual(html.count("<script>"), 1)
        self.assertIn(f'</div><script>{I.SCRIPT_CEU}</script><div class="hero-texto">', html)
        self.assertLess(html.index('<div class="ceu"'), html.index("<script>"))

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
        for nome in ("baia", "promontorio"):
            self.assertNotIn(f"camada {nome}", html)
        # O sol é o .ceu::before do CSS, não uma camada com máscara.
        self.assertEqual(I.CAMADAS, ("fundo", "baia", "promontorio", "orla"))
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
        self.assertIn('<details class="lista-vereadores"><summary>Ver os 5 que exerceram mandato nesta legislatura '
                      '(4 eleitos e 1 suplente)</summary><ul id="lista-vereadores">', html)
        self.assertIn('<a href="vereadores/bruno.html">Bruno</a> <span class="partido">PA</span></li>', html)
        self.assertIn('Carlos Silva</a> <span class="partido">PC</span> <span class="status">suplente em exercício</span>', html)

    def test_campo_do_combobox_no_servidor_antes_da_lista(self):
        html = I.quem_e_meu_vereador(modelo_base())
        self.assertEqual(html.count(I.CAMPO_BUSCA), 1)
        self.assertLess(html.index('<div class="cb-campo">'), html.index('<details class="lista-vereadores">'))
        self.assertIn('<label for="cb-vereadores" id="cb-vereadores-rotulo">Digite o nome do vereador</label>', html)
        self.assertIn('<input id="cb-vereadores" type="text" role="combobox" aria-autocomplete="list" aria-expanded="false" '
                      'aria-controls="cb-vereadores-lista" autocomplete="off">', html)
        self.assertIn('<ul role="listbox" id="cb-vereadores-lista" aria-labelledby="cb-vereadores-rotulo" hidden></ul>', html)
        self.assertIn('<p class="so-leitor" aria-live="polite" id="cb-vereadores-status"></p></div>', html)
        # Sem JS, o campo some (a classe js vem de SCRIPT_CABECA); na impressão também.
        css = sem_comentarios(CSS_INICIO.read_text(encoding="utf-8"))
        ocultos = [(c, s) for c, s, corpo in regras(css) if ".cb-campo" in s and declaracoes(corpo).get("display", "").startswith("none")]
        self.assertIn(((), "html:not(.js) .cb-campo"), ocultos)
        self.assertTrue(any(c == ("@media print",) for c, _ in ocultos))

    def test_resumo_com_eleitos_e_suplentes(self):
        self.assertEqual(I.resumo_lista(21, 9), "Ver os 30 que exerceram mandato nesta legislatura (21 eleitos e 9 suplentes)")
        self.assertEqual(I.resumo_lista(21, 1), "Ver os 22 que exerceram mandato nesta legislatura (21 eleitos e 1 suplente)")
        self.assertEqual(I.resumo_lista(1, 2), "Ver os 3 que exerceram mandato nesta legislatura (1 eleito e 2 suplentes)")
        self.assertEqual(I.resumo_lista(21, 0), "Ver os 21 vereadores eleitos nesta legislatura")
        self.assertEqual(I.resumo_lista(1, 0), "Ver o vereador eleito nesta legislatura")

    def test_prefixo_e_escape(self):
        modelo = modelo_base()
        modelo["pessoas"] = {"x": pessoa("x", "Ana <b> & Cia", {ATUAL: {"partido": "P&<T>"}})}
        html = I.quem_e_meu_vereador(modelo, "../")
        self.assertIn('<a href="../vereadores/x.html">Ana &lt;b&gt; &amp; Cia</a> <span class="partido">P&amp;&lt;T&gt;</span>', html)
        self.assertNotIn("<b>", html)
        # Sem "eleito": False, conta como eleito.
        self.assertIn("<summary>Ver o vereador eleito nesta legislatura</summary>", html)


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
                                        '<div class="tabela-rolavel linha-rolavel" role="region" tabindex="0" '
                                        'aria-label="Linha do tempo, role na horizontal"><ol>'))
        self.assertEqual(re.findall(r'<span class="quando"><time datetime="([^"]+)">', html), ["1573-11-22", "1894", "1975-03-15"])
        self.assertEqual(re.findall(r'<time datetime="([^"]+)">', html), ["1573-11-22", "1894", "1903", "1975-03-15"])
        self.assertIn('<li><span class="quando"><time datetime="1573-11-22">22/11/1573</time></span> <strong>', html)
        self.assertIn('<span class="quando"><time datetime="1894">1894</time>–<time datetime="1903">1903</time></span>', html)
        self.assertIn("<strong>Capital &lt;fora&gt; &amp; volta</strong>", html)
        self.assertIn("<p>Texto &lt;i&gt;A&lt;/i&gt; &amp; mais.</p>", html)
        self.assertIn('<a href="https://exemplo.test/a?x=1&amp;y=2">Arquivo &amp; cia</a>', html)
        self.assertNotIn("<fora>", html)
        self.assertNotIn("<i>", html)

    def test_memoria_real_em_ordem(self):
        memoria = I.carregar_memoria(RAIZ)
        self.assertIsNotNone(memoria)
        html = I.linha_do_tempo(memoria)
        datas = re.findall(r'<span class="quando"><time datetime="([^"]+)">', html)
        self.assertEqual(len(datas), len(memoria["linha_do_tempo"]))
        self.assertEqual(datas, sorted(datas))
        self.assertIn('<time datetime="1894">1894</time>–<time datetime="1903">1903</time>', html)
        self.assertEqual(html.count("<li>"), len(memoria["linha_do_tempo"]))


class TestFaixaMemoria(unittest.TestCase):
    def test_sem_memoria_ou_homenageados(self):
        for memoria in (None, {}, {"homenageados": []}, memoria_sintetica()):
            with self.subTest(memoria=memoria):
                self.assertEqual(I.faixa_memoria(memoria), "")

    def test_emblemas_acessiveis_e_ancoras_da_memoria_real(self):
        memoria = I.carregar_memoria(RAIZ)
        html = I.faixa_memoria(memoria)
        pagina = gerar_memoria(memoria)
        self.assertIn('id="fm-titulo" class="h-secao">Niterói que nos inspira</h2>', html)
        self.assertEqual(html.count('<svg class="emblema"'), len(memoria["homenageados"]))
        self.assertEqual(len(ids(html)), len(set(ids(html))))
        for pessoa in memoria["homenageados"]:
            identificador, nome = pessoa["id"], pessoa["nome"]
            self.assertIn(f'href="memoria.html#{identificador}"', html)
            self.assertIn(f'<span>{P.esc(nome)}</span>', html)
            self.assertIn(f'role="img" aria-labelledby="fm-{identificador}"', html)
            self.assertIn(f'<title id="fm-{identificador}">Emblema de {P.esc(nome)}</title>', html)
            self.assertIn(f'<use href="{P.url_estatica("memoria/" + pessoa["emblema"])}#emblema"/>', html)
            self.assertIn(f'<article id="{identificador}"', pagina)
        self.assertIn('href="memoria.html">Conheça a Memória de Niterói</a>', html)
        self.assertEqual(html, I.faixa_memoria(memoria))

    def test_prefixo_escape_e_emblema_ausente(self):
        memoria = {"homenageados": [{"id": "nome", "nome": "Nome <b> & Cia", "emblema": "ausente.svg"}]}
        with tempfile.TemporaryDirectory() as pasta, mock.patch.object(P, "FONTE_ESTATICA", Path(pasta)):
            html = I.faixa_memoria(memoria, "../")
        self.assertNotIn("<svg", html)
        self.assertIn('href="../memoria.html#nome"><span>Nome &lt;b&gt; &amp; Cia</span>', html)
        self.assertIn('href="../memoria.html">', html)
        memoria = I.carregar_memoria(RAIZ)
        html = I.faixa_memoria(memoria, "../")
        self.assertIn(f'<use href="{P.url_estatica("memoria/" + memoria["homenageados"][0]["emblema"], "../")}#emblema"/>', html)


class TestBlocosJuntos(unittest.TestCase):
    def test_ids_unicos_e_saida_deterministica(self):
        modelo = modelo_base(documentos=docs_mapa(), geo_bairros=geo_completo())
        memoria = I.carregar_memoria(RAIZ)

        def tudo() -> str:
            return (I.hero(modelo, P.url_estatica) + I.quem_e_meu_vereador(modelo) + I.mapa_home(modelo)
                    + I.linha_do_tempo(memoria) + I.faixa_memoria(memoria))

        html = tudo()
        lista = ids(html)
        repetidos = [i for i, n in Counter(lista).items() if n > 1]
        self.assertEqual(repetidos, [])
        for esperado in ("t-hero", "t-quem", "t-mapa-home", "t-linha", "fm-titulo", "lista-vereadores"):
            self.assertIn(esperado, lista)
        self.assertEqual(tudo(), html)


# ---- integração na página inicial
def metricas_placar() -> dict:
    return {"apresentados": 2, "leis": 1, "leis_efeito": 1, "leis_outras": 0, "leis_sem_efeito": 0, "andamento": 1,
            "sem_exito": 0, "polemicos": 0, "pct_sem_efeito": 0, "taxa_aprovacao": 50}


def modelo_home(**extra) -> dict:
    """Modelo com o mínimo que o placar de gerar_index usa, além dos blocos de inicio.py."""
    modelo = modelo_base(**extra)
    for p in modelo["pessoas"].values():
        for mandato in p["mandatos"].values():
            mandato.update(afastamentos=[], metricas=metricas_placar())
    return modelo


def corpo_principal(html: str) -> str:
    return html.split('<main id="conteudo"', 1)[1].split(">", 1)[1].split("</main>", 1)[0]


def fases_do_ceu(css: str) -> dict[str, dict[str, str]]:
    """Propriedades de cada fase, lidas dos blocos .ceu[data-ceu="…"] fora de at-rules."""
    fases: dict[str, dict[str, str]] = {}
    for contexto, seletor, corpo in regras(css):
        m = re.match(r'\.ceu\[data-ceu="([a-z-]+)"\]', seletor)
        if m and not contexto:
            fases.setdefault(m.group(1), {}).update({n: v for n, v in declaracoes(corpo).items() if n.startswith("--")})
    return fases


def razao_contraste(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    claro, escuro = sorted((luminancia(a), luminancia(b)), reverse=True)
    return (claro + .05) / (escuro + .05)


class TestFasesDoCeu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css = CSS_INICIO.read_text(encoding="utf-8")
        cls.fases = fases_do_ceu(cls.css)

    def test_mesmas_fases_de_inicio_js_e_todas_as_chaves(self):
        js = (P.FONTE_ESTATICA / "inicio.js").read_text(encoding="utf-8")
        nomes_js = re.findall(r'\[\d+, "([a-z-]+)"\]', js.split("var FASES = ", 1)[1].split(";", 1)[0])
        self.assertEqual(tuple(nomes_js), FASES_CEU)
        self.assertEqual(sorted(self.fases), sorted(FASES_CEU))
        for fase, props in self.fases.items():
            with self.subTest(fase=fase):
                self.assertEqual([c for c in CHAVES_FASE if c not in props], [])

    def test_texto_com_contraste_sobre_a_cor_mais_clara_com_veu(self):
        for fase, props in self.fases.items():
            with self.subTest(fase=fase):
                mais_clara = max((rgba(props[c], {})[:3] for c in ("--ceu-1", "--ceu-2", "--sol")), key=luminancia)
                veu = rgba(props["--veu"], {})
                fundo = compor(veu, mais_clara)
                texto = rgba(props["--h1"], {})
                self.assertEqual(texto[3], 1.0)
                self.assertGreaterEqual(razao_contraste(texto[:3], fundo), 4.5)

    def test_texto_empilhado_sobre_a_orla_com_contraste(self):
        # Abaixo de 900px o texto sai do céu e fica sobre --camada-4.
        for fase, props in self.fases.items():
            with self.subTest(fase=fase):
                texto, orla = rgba(props["--h1"], {}), rgba(props["--camada-4"], {})
                self.assertEqual(orla[3], 1.0)
                self.assertGreaterEqual(razao_contraste(texto[:3], orla[:3]), 4.5)

    def test_horizonte_e_fundo_distinguiveis(self):
        # O fundo da paisagem (--camada-1) recorta o horizonte (--ceu-2), também à noite e de madrugada.
        for fase, props in self.fases.items():
            with self.subTest(fase=fase):
                horizonte, fundo = rgba(props["--ceu-2"], {}), rgba(props["--camada-1"], {})
                self.assertGreaterEqual(razao_contraste(horizonte[:3], fundo[:3]), 1.5)

    def test_texto_empilhado_abaixo_de_900px(self):
        estreito = "@media (max-width: 899.98px)"
        hero_texto = {s: declaracoes(corpo) for c, s, corpo in regras(self.css) if c == (estreito,)}
        self.assertEqual(hero_texto[".hero"].get("grid-template-rows"), "auto auto")
        self.assertEqual(hero_texto[".ceu"].get("grid-area"), "1 / 1")
        self.assertEqual(hero_texto[".hero-texto"].get("grid-area"), "2 / 1")
        self.assertEqual(hero_texto[".hero-texto"].get("background"), "var(--camada-4)")
        self.assertEqual(hero_texto[".hero-texto"].get("max-width"), "none")
        largo = [declaracoes(corpo) for c, s, corpo in regras(self.css) if not c and s == ".hero-texto"]
        self.assertIn("min(46rem, 55%)", [d.get("max-width") for d in largo])

    def test_veu_e_texto_tambem_valem_para_o_irmao_hero_texto(self):
        # As propriedades são declaradas no .ceu; o texto é irmão, então cada bloco precisa do seletor ~ .hero-texto.
        for fase in FASES_CEU:
            with self.subTest(fase=fase):
                self.assertIn(f'.ceu[data-ceu="{fase}"] ~ .hero-texto', self.css)

    def test_hexadecimais_so_nas_fases(self):
        for contexto, seletor, corpo in regras(self.css):
            if re.search(r"#[0-9A-Fa-f]{3,8}\b", corpo):
                with self.subTest(seletor=seletor):
                    self.assertFalse(contexto)
                    self.assertRegex(seletor, r'^\.ceu\[data-ceu="[a-z-]+"\]')

    def test_guardas_de_movimento(self):
        css = sem_comentarios(self.css)
        self.assertIn("@supports (animation-timeline: scroll())", css)
        self.assertIn("prefers-reduced-motion", css)
        animadas = [(contexto, seletor) for contexto, seletor, corpo in regras(css) if "animation" in declaracoes(corpo)
                    or "animation-timeline" in declaracoes(corpo)]
        self.assertTrue(animadas)
        for contexto, seletor in animadas:
            with self.subTest(seletor=seletor):
                self.assertIn("@supports (animation-timeline: scroll())", contexto)
                self.assertIn("@media (prefers-reduced-motion: no-preference)", contexto)
        # Deslocamento sutil: no máximo 40px por camada.
        deslocamentos = [float(v[:-2]) for _, _, corpo in regras(css)
                         for n, v in declaracoes(corpo).items() if n == "--desloca"]
        self.assertTrue(deslocamentos)
        self.assertLessEqual(max(abs(d) for d in deslocamentos), 40)

    def test_proporcao_fixa_impressao_e_cores_forcadas(self):
        ceu = [(contexto, declaracoes(corpo)) for contexto, seletor, corpo in regras(self.css) if seletor == ".ceu"]
        self.assertIn(("16 / 6"), [d.get("aspect-ratio") for c, d in ceu if not c])
        self.assertTrue(any(d.get("aspect-ratio") == "2 / 1" and c == ("@media (max-width: 899.98px)",) for c, d in ceu))
        ocultos = {c[-1] for c, s, corpo in regras(self.css) if c and ".ceu" in s.split(", ")
                   and declaracoes(corpo).get("display", "").startswith("none")}
        self.assertIn("@media print", ocultos)
        self.assertIn("@media (forced-colors: active)", ocultos)

    def test_view_transition_no_css_global_so_sem_movimento_reduzido(self):
        css = sem_comentarios((P.FONTE_ESTATICA / "estilo.css").read_text(encoding="utf-8"))
        self.assertEqual(css.count("@view-transition"), 1)
        vt = [(contexto, declaracoes(corpo)) for contexto, seletor, corpo in regras(css) if seletor == "@view-transition"]
        self.assertEqual(vt, [(("@media (prefers-reduced-motion: no-preference)",), {"navigation": "auto"})])
        nomes = Counter(d["view-transition-name"] for _, _, corpo in regras(css)
                        for d in [declaracoes(corpo)] if "view-transition-name" in d)
        self.assertEqual(nomes, Counter({"marca": 1, "titulo": 1}))
        titulo = next(s for _, s, corpo in regras(css) if declaracoes(corpo).get("view-transition-name") == "titulo")
        self.assertIn(".hero h1", titulo)


class TestHomeIntegrada(unittest.TestCase):
    def test_ordem_das_secoes(self):
        modelo = modelo_home(documentos=docs_mapa(), geo_bairros=geo_completo(), memoria=I.carregar_memoria(RAIZ))
        with mock.patch.object(P, "MEMORIA_PUBLICADA", True):
            corpo = corpo_principal(P.gerar_index(modelo))
        posicoes = [corpo.find(marca) for marca in ORDEM_HOME]
        self.assertNotIn(-1, posicoes, dict(zip(ORDEM_HOME, posicoes)))
        self.assertEqual(posicoes, sorted(posicoes))
        self.assertTrue(corpo.lstrip().startswith('<section class="hero"'))
        self.assertNotIn('class="abertura"', corpo)
        self.assertIn('class="camada fundo"', corpo)  # máscaras versionadas de site_src/paisagem/

    def test_mapa_e_linha_do_tempo_omitidos_sem_dados(self):
        modelo = modelo_home(memoria=None)
        corpo = corpo_principal(P.gerar_index(modelo))
        self.assertNotIn('id="t-mapa-home"', corpo)
        self.assertNotIn('id="t-linha"', corpo)
        self.assertNotIn('id="fm-titulo"', corpo)
        restantes = [m for m in ORDEM_HOME if m not in ('id="t-mapa-home"', 'id="t-linha"', 'id="fm-titulo"')]
        posicoes = [corpo.find(m) for m in restantes]
        self.assertNotIn(-1, posicoes)
        self.assertEqual(posicoes, sorted(posicoes))

    def test_memoria_real_sem_chave_no_modelo(self):
        corpo = corpo_principal(P.gerar_index(modelo_home()))
        self.assertIn('id="t-linha"', corpo)
        self.assertEqual(corpo.count('<span class="quando"><time datetime='), len(I.carregar_memoria(RAIZ)["linha_do_tempo"]))

    def test_faixa_so_quando_pagina_publicada(self):
        modelo = modelo_home(memoria=I.carregar_memoria(RAIZ))
        with mock.patch.object(P, "MEMORIA_PUBLICADA", False):
            html = P.gerar_index(modelo)
        self.assertNotIn("memoria.html", html)
        self.assertNotIn('id="fm-titulo"', html)
        # Mesmo com a flag ligada, uma memória sem homenageados não gera faixa nem âncoras.
        with mock.patch.object(P, "MEMORIA_PUBLICADA", True):
            corpo = corpo_principal(P.gerar_index(modelo_home(memoria=None)))
        self.assertNotIn("memoria.html", corpo)

    def test_ids_unicos_e_tabelas_acessiveis(self):
        html = P.gerar_index(modelo_home(documentos=docs_mapa(), geo_bairros=geo_completo(), memoria=memoria_sintetica()))
        repetidos = [i for i, n in Counter(ids(html)).items() if n > 1]
        self.assertEqual(repetidos, [])
        self.assertEqual(html.count("<h1"), 1)
        test_tabelas_rolaveis.ContratoTabelas.conferir_tabelas(self, html)

    def test_inicio_css_e_js_so_na_home(self):
        home = P.gerar_index(modelo_home())
        css, js = P.url_estatica("inicio.css"), P.url_estatica("inicio.js")
        self.assertIn(f'<link rel="stylesheet" href="{css}">', home)
        self.assertIn(f'<script src="{js}" defer></script>', home)
        self.assertLess(home.index("estilo.css?v="), home.index(css))
        self.assertLess(home.index("app.js?v="), home.index(js))
        for html in (P.pagina("Leis", "", "leis.html"),
                     P.pagina("Ficha", "", "", prefixo="../", caminho="vereadores/ana.html")):
            self.assertNotIn("inicio.css", html)
            self.assertNotIn("inicio.js", html)

    def test_estilos_extras_com_prefixo_e_so_se_existirem(self):
        html = P.pagina("Ficha", "", "", prefixo="../", caminho="vereadores/ana.html", estilos=("inicio.css", "nao-existe.css"))
        self.assertIn(f'<link rel="stylesheet" href="{P.url_estatica("inicio.css", "../")}">', html)
        self.assertNotIn("nao-existe.css", html)


class TestImagemDeCompartilhamento(unittest.TestCase):
    def test_og_image_absoluta_versionada_em_toda_pagina(self):
        versao = hashlib.sha1((P.FONTE_ESTATICA / "og-radar.png").read_bytes()).hexdigest()[:10]
        url = f"{N.URL_SITE}og-radar.png?v={versao}"
        self.assertTrue(url.startswith("https://"))
        modelo_404 = {"legislaturas": [{"id": ATUAL}], "pessoas": {"ana": {"slug": "ana", "nome": "Ana", "mandatos": {ATUAL: {}}}}}
        paginas = {"index": P.gerar_index(modelo_home()), "leis": P.pagina("Leis", "", "leis.html"),
                   "ficha": P.pagina("Ficha", "", "", prefixo="../", caminho="vereadores/ana.html"),
                   "404": gerar_site.gerar_404(modelo_404)}
        for nome, html in paginas.items():
            with self.subTest(pagina=nome):
                self.assertEqual(html.count('property="og:image"'), 1)
                self.assertIn(f'<meta property="og:image" content="{url}">', html)
                self.assertIn('<meta property="og:image:width" content="1200">', html)
                self.assertIn('<meta property="og:image:height" content="630">', html)
                self.assertIn(f'<meta property="og:image:alt" content="{ALT_OG}">', html)
                self.assertIn(f'<meta name="twitter:image" content="{url}">', html)
                self.assertIn('<meta name="twitter:card" content="summary_large_image">', html)

    def test_sem_png_sem_og_image(self):
        with tempfile.TemporaryDirectory() as pasta:
            fonte = Path(pasta)
            for nome in ("estilo.css", "dados.js", "app.js"):
                (fonte / nome).write_bytes(b"/* recurso de teste */")
            with mock.patch.object(P, "FONTE_ESTATICA", fonte):
                html = P.pagina("Leis", "", "leis.html")
        self.assertNotIn("og:image", html)
        self.assertNotIn("twitter:image", html)


def gz(conteudo: bytes) -> int:
    return len(gzip.compress(conteudo, mtime=0))


def fontes_do_css_global() -> list[str]:
    """WOFF2 de todos os @font-face de estilo.css (Barlow Condensed e Public Sans, normal, itálico e latin-ext)."""
    css = sem_comentarios((P.FONTE_ESTATICA / "estilo.css").read_text(encoding="utf-8"))
    return sorted({url for _, seletor, corpo in regras(css) if seletor == "@font-face"
                   for url in re.findall(r'url\(\s*["\']?([^"\')?#]+\.woff2)', corpo)})


class TestOrcamentoDaHome(unittest.TestCase):
    def html_sintetico(self) -> bytes:
        return P.gerar_index(modelo_home(documentos=docs_mapa(), geo_bairros=geo_completo())).encode("utf-8")

    def html_home(self) -> bytes:
        """A home gerada em site/, se for mais nova que o código da geração; senão, a de um modelo sintético."""
        gerada = gerar_site.SAIDA / "index.html"
        fontes = [*(RAIZ / "coletor" / "site").glob("*.py"), RAIZ / "coletor" / "gerar_site.py"]
        if gerada.is_file() and gerada.stat().st_mtime >= max(f.stat().st_mtime for f in fontes):
            return gerada.read_bytes()
        return self.html_sintetico()

    def test_html_ate_100_kib(self):
        self.assertLessEqual(gz(self.html_home()), 100 * KIB)
        self.assertLessEqual(gz(self.html_sintetico()), 100 * KIB)

    def test_carga_da_home_ate_300_kib(self):
        textos = ["estilo.css", "inicio.css", "navegacao.js", "inicio.js", "dados.js", "app.js",
                  *(f"paisagem/{c}.svg" for c in I.CAMADAS if (P.FONTE_ESTATICA / f"paisagem/{c}.svg").is_file()),
                  "textura-bairros.svg"]
        self.assertEqual(len(textos), 11)  # seis CSS/JS, quatro máscaras e a textura de body::before
        fontes = fontes_do_css_global()
        # Todas as faces que a home pode pedir: Barlow 500/600/700 e Public Sans normal/itálico, latin e latin-ext.
        self.assertEqual(len(fontes), 10, fontes)
        self.assertIn("fontes/public-sans-latin-wght-normal.woff2", fontes)
        self.assertTrue(all("fraunces" not in f for f in fontes))
        tamanhos = {nome: gz(P.bytes_estaticos(P.FONTE_ESTATICA / nome)) for nome in textos}
        # WOFF2 já é comprimido e não é servido com gzip: conta os bytes brutos.
        tamanhos.update({nome: len(P.bytes_estaticos(P.FONTE_ESTATICA / nome)) for nome in fontes})
        tamanhos["index.html"] = gz(self.html_home())
        total = sum(tamanhos.values())
        self.assertLessEqual(total, 300 * KIB, tamanhos)


if __name__ == "__main__":
    unittest.main()
