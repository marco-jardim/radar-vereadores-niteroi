"""Contratos responsivos e orçamentos de publicação, offline e sem gerar o site."""
from __future__ import annotations

import gzip
import re
import unittest
from pathlib import Path

from coletor import gerar_site
from coletor.site import paginas as P
from tests.test_design_tokens import declaracoes as ler_declaracoes
from tests.test_design_tokens import regras, sem_comentarios

CSS = P.FONTE_ESTATICA / "estilo.css"
MOVEL = "@media (max-width: 759.98px)"
DESKTOP = "@media (min-width: 760px)"
FORCADO = "@media (forced-colors: active)"
IMPRESSAO = "@media print"
NUMERO = r"(?:\d+(?:\.\d+)?|\.\d+)"


def separar(valor: str, separador: str = ",") -> list[str]:
    """Divide apenas fora de funções, atributos e strings (listas de seletores inclusive)."""
    partes = []
    inicio = profundidade = 0
    aspas = ""
    escape = False
    for i, caractere in enumerate(valor):
        if escape:
            escape = False
        elif caractere == "\\":
            escape = True
        elif aspas:
            if caractere == aspas:
                aspas = ""
        elif caractere in "\"'":
            aspas = caractere
        elif caractere in "([":
            profundidade += 1
        elif caractere in ")]":
            profundidade -= 1
        elif caractere == separador and profundidade == 0:
            partes.append(valor[inicio:i].strip())
            inicio = i + 1
    partes.append(valor[inicio:].strip())
    return partes


def regras_seletor(css: str, seletor: str) -> list[tuple[tuple[str, ...], dict[str, str]]]:
    """Preserva as at-rules envolventes para não confundir mobile, desktop e impressão."""
    return [(contexto, ler_declaracoes(corpo)) for contexto, lista, corpo in regras(css)
            if seletor in separar(lista)]


def declaracoes(css: str, seletor: str) -> dict[str, str]:
    """Mescla, em ordem de fonte, regras que contêm o seletor como item exato da lista.

    Inclui @media; regras_seletor expõe o contexto quando a faixa precisa ser distinguida.
    """
    resultado = {}
    for _, propriedades in regras_seletor(css, seletor):
        resultado.update(propriedades)
    return resultado


def na_faixa(css: str, seletor: str, media: str | None = None) -> dict[str, str]:
    """Mescla a base com uma faixa explícita, sem aplicar outros meios de saída."""
    resultado = {}
    for contexto, propriedades in regras_seletor(css, seletor):
        if not contexto or (media is not None and media in contexto):
            resultado.update(propriedades)
    return resultado


def sem_importante(valor: str) -> str:
    return re.sub(r"\s*!important\s*$", "", valor, flags=re.I).strip()


def medida_px(valor: str, tokens: dict[str, str], vistos: tuple[str, ...] = ()) -> float:
    """Resolve tokens e o limite inferior de clamp(); 1rem corresponde a 16px."""
    valor = sem_importante(valor)
    variavel = re.fullmatch(r"var\(\s*(--[\w-]+)\s*\)", valor)
    if variavel:
        nome = variavel.group(1)
        if nome in vistos:
            raise ValueError(f"Ciclo de tokens: {nome}")
        return medida_px(tokens[nome], tokens, (*vistos, nome))
    if valor.startswith("clamp(") and valor.endswith(")"):
        return medida_px(separar(valor[6:-1])[0], tokens, vistos)
    medida = re.fullmatch(rf"(-?{NUMERO})(px|rem)", valor)
    if not medida:
        raise ValueError(f"Medida não suportada: {valor!r}")
    return float(medida.group(1)) * (16 if medida.group(2) == "rem" else 1)


def minimos_fixos(valor: str) -> list[float]:
    """Encontra mínimos px sem min(); o segundo argumento de minmax é só um máximo."""
    pilha: list[tuple[str, int]] = []
    minimos = []
    padrao = rf'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[\w-]+\s*\(|[(),]|{NUMERO}px\b'''
    for item in re.finditer(padrao, valor):
        token = item.group()
        if token.endswith("("):
            pilha.append((token[:-1].strip().lower(), 0))
        elif token == "," and pilha:
            nome, argumento = pilha[-1]
            pilha[-1] = nome, argumento + 1
        elif token == ")":
            pilha.pop()
        elif token.endswith("px"):
            if not any(nome == "min" or (nome == "minmax" and argumento > 0)
                       for nome, argumento in pilha):
                minimos.append(float(token[:-2]))
    return minimos


def tamanho_fonte(valor: str) -> str | None:
    """Extrai o tamanho do shorthand sem confundir peso, entrelinha ou família."""
    if sem_importante(valor) in {"inherit", "initial", "unset", "revert", "revert-layer"}:
        return None
    # A divisão da entrelinha fica fora de var()/clamp().
    antes_entrelinha = separar(valor, "/")[0]
    tamanho = re.search(rf"var\(\s*--fs-[\w-]+\s*\)|clamp\([^)]*\)|{NUMERO}(?:rem|px)\b",
                        antes_entrelinha)
    if tamanho is None:
        raise ValueError(f"Tamanho ausente no shorthand font: {valor!r}")
    return tamanho.group()


def paginas_atuais(caso: unittest.TestCase) -> list[Path]:
    """Reusa site/ de test_gerar_site, sem chamar o gerador novamente."""
    saida = gerar_site.SAIDA
    paginas = sorted(saida.rglob("*.html")) if saida.is_dir() else []
    atualizado_em = CSS.stat().st_mtime_ns
    if (not paginas or saida.stat().st_mtime_ns <= atualizado_em
            or any(pagina.stat().st_mtime_ns <= atualizado_em for pagina in paginas)):
        caso.skipTest("site/ ausente ou desatualizado; rode python -m coletor.gerar_site")
    return paginas


# Os orçamentos sintéticos de sessões já são cobertos por tests/test_pagina_sessoes.py.


class TestResponsivoCSS(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css = CSS.read_text(encoding="utf-8")
        cls.regras = regras(cls.css)
        cls.tokens = declaracoes(cls.css, ":root")

    def test_grades_sem_minimo_fixo_maior_que_288px(self):
        for contexto, seletor, corpo in self.regras:
            for nome, valor in ler_declaracoes(corpo).items():
                if nome in {"grid-template-columns", "grid-template"}:
                    with self.subTest(media=contexto, seletor=seletor, valor=valor):
                        self.assertTrue(all(minimo <= 288 for minimo in minimos_fixos(valor)), valor)

    def test_alvos_de_toque(self):
        grandes = (".menu-botao", ".mais", ".acoes-filtro button", ".dialogo-cab .fechar",
                   "select", 'input[type="search"]')
        pequenos = (".chip", ".ver-siscam", ".tag", ".chips-impacto label")
        for seletores, minimo in ((grandes, 44), (pequenos, 24)):
            for seletor in seletores:
                with self.subTest(seletor=seletor):
                    propriedades = declaracoes(self.css, seletor)
                    self.assertIn("min-height", propriedades)
                    self.assertGreaterEqual(medida_px(propriedades["min-height"], self.tokens), minimo)
        for seletor in (".menu-botao", ".tema button", ".mais", ".dialogo-cab .fechar"):
            with self.subTest(largura=seletor):
                propriedades = declaracoes(self.css, seletor)
                self.assertIn("min-width", propriedades)
                self.assertGreaterEqual(medida_px(propriedades["min-width"], self.tokens), 44)

    def test_menu_e_tema_por_faixa(self):
        for seletor in (".topo nav a", ".tema button"):
            with self.subTest(seletor=seletor, media=MOVEL):
                propriedades = na_faixa(self.css, seletor, MOVEL)
                self.assertIn("min-height", propriedades)
                self.assertGreaterEqual(medida_px(propriedades["min-height"], self.tokens), 44)
            with self.subTest(seletor=seletor, media=DESKTOP):
                propriedades = na_faixa(self.css, seletor, DESKTOP)
                altura = medida_px(propriedades.get("min-height", "0px"), self.tokens)
                if altura >= 44:
                    continue
                area = na_faixa(self.css, seletor + "::after", DESKTOP)
                self.assertEqual(area.get("position"), "absolute")
                self.assertIn("content", area)
                self.assertEqual(propriedades.get("position"), "relative")
                if seletor == ".topo nav a":
                    for lado in ("top", "bottom"):
                        self.assertLessEqual(medida_px(area[lado], self.tokens), -8)
                else:
                    altura_area = medida_px(area.get("min-height", "0px"), self.tokens)
                    expansao = altura - sum(medida_px(area[lado], self.tokens) for lado in ("top", "bottom"))
                    self.assertGreaterEqual(max(altura_area, expansao), 44)

    def test_tamanho_minimo_das_fontes(self):
        self.assertRegex(self.css, r"/\* exceção de tamanho:.*?\.svg-box")
        for contexto, lista, corpo in self.regras:
            propriedades = ler_declaracoes(corpo)
            for nome in ("font-size", "font"):
                if nome not in propriedades:
                    continue
                valor = propriedades[nome]
                tamanho = tamanho_fonte(valor) if nome == "font" else sem_importante(valor)
                if tamanho is None or tamanho in {"inherit", "initial", "unset", "revert", "revert-layer"}:
                    continue
                for seletor in separar(lista):
                    with self.subTest(media=contexto, seletor=seletor, propriedade=nome, valor=valor):
                        minimo = 12 if seletor.startswith(".svg-box") else 13
                        self.assertGreaterEqual(medida_px(tamanho, self.tokens), minimo)
                if re.fullmatch(r"var\(\s*--fs--1\s*\)", tamanho) and "line-height" in propriedades:
                    with self.subTest(entrelinha=lista, media=contexto):
                        entrelinha = sem_importante(propriedades["line-height"])
                        if re.fullmatch(NUMERO, entrelinha):
                            razao = float(entrelinha)
                        elif entrelinha.endswith("%"):
                            razao = float(entrelinha[:-1]) / 100
                        else:
                            razao = medida_px(entrelinha, self.tokens) / medida_px(tamanho, self.tokens)
                        self.assertGreaterEqual(razao, 1.4)

    def test_css_publicado_ate_16_kib_gzip(self):
        publicado = P.bytes_estaticos(P.FONTE_ESTATICA / "estilo.css")
        self.assertLessEqual(len(gzip.compress(publicado, compresslevel=9, mtime=0)), 16 * 1024)

    def test_html_gerado_dentro_do_orcamento(self):
        for pagina in paginas_atuais(self):
            with self.subTest(pagina=str(pagina.relative_to(gerar_site.SAIDA))):
                tamanho = len(gzip.compress(pagina.read_bytes(), compresslevel=9, mtime=0))
                self.assertLessEqual(tamanho, gerar_site.LIMITE_HTML_GZIP)

    def test_cores_forcadas_sem_textura_e_com_foco_highlight(self):
        regras_forcadas = [(lista, ler_declaracoes(corpo)) for contexto, lista, corpo in self.regras
                          if FORCADO in contexto]
        self.assertTrue(regras_forcadas)
        self.assertTrue(any("body::before" in separar(lista) and sem_importante(d.get("display", "")) == "none"
                            for lista, d in regras_forcadas))
        self.assertTrue(any(":focus-visible" in separar(lista)
                            and (d.get("outline-color") == "Highlight"
                                 or re.search(r"\bHighlight\b", d.get("outline", "")))
                            for lista, d in regras_forcadas))

    def test_impressao_sem_textura(self):
        self.assertTrue(any(IMPRESSAO in contexto and sem_importante(d.get("display", "")) == "none"
                            for contexto, d in regras_seletor(self.css, "body::before")))

    def test_tabelas_contem_rolagem_e_textos_absolutos(self):
        seletores = (".tabela-rolavel", ".tabela-resumo", ".sessoes .faixa-rolagem")
        for seletor in seletores:
            with self.subTest(seletor=seletor):
                propriedades = declaracoes(self.css, seletor)
                self.assertEqual(propriedades.get("overflow-x"), "auto")
                self.assertEqual(propriedades.get("position"), "relative")
        self.assertTrue(any(set(seletores).issubset(separar(lista))
                            and ler_declaracoes(corpo).get("position") == "relative"
                            for _, lista, corpo in self.regras))


class TestAuxiliaresResponsivos(unittest.TestCase):
    def test_declaracoes_exatas_com_comentarios_e_media_aninhada(self):
        css = ("/* .alvo { min-height: 1px; } */ .alvo:hover { min-height: 2px; }"
               ".alvo, :is(.outro, .terceiro) { min-height: 44px; }"
               "@media (min-width: 760px) { @media (hover: hover) {"
               ".alvo { min-width: 48px; } } }")
        self.assertEqual(declaracoes(css, ".alvo"), {"min-height": "44px", "min-width": "48px"})
        self.assertEqual(regras_seletor(css, ".alvo")[-1][0], (DESKTOP, "@media (hover: hover)"))
        self.assertNotIn("/*", sem_comentarios(css))

    def test_minimos_das_grades(self):
        self.assertEqual(minimos_fixos("repeat(auto-fill, minmax(340px, 1fr))"), [340])
        self.assertEqual(minimos_fixos("repeat(2, 300px) minmax(0, 900px)"), [300])
        self.assertEqual(minimos_fixos("repeat(auto-fit, minmax(min(100%, 340px), 1fr))"), [])
        self.assertEqual(minimos_fixos('"area 900px" 280px / minmax(290px, 1fr)'), [280, 290])

    def test_tokens_e_shorthand(self):
        tokens = {"--fs--1": "clamp(.8125rem, .8rem + .08vw, .8333rem)", "--esp-7": "48px"}
        self.assertEqual(medida_px("var(--fs--1) !important", tokens), 13)
        self.assertEqual(medida_px("var(--esp-7)", tokens), 48)
        self.assertEqual(tamanho_fonte("600 .75rem/1.5 sans-serif"), ".75rem")
        self.assertEqual(tamanho_fonte("400 var(--fs--1)/1.4 var(--texto)"), "var(--fs--1)")
        self.assertIsNone(tamanho_fonte("inherit"))


if __name__ == "__main__":
    unittest.main()
