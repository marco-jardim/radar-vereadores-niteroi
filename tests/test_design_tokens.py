"""Tokens de design, contraste WCAG, fontes auto-hospedadas e <head> sem terceiros, sem acesso à rede."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from coletor.site import paginas as P

RAIZ = Path(__file__).resolve().parents[1]
FONTE = RAIZ / "site_src"
CSS = FONTE / "estilo.css"

# Tokens de contrato: hex literal de 6 dígitos em todo bloco que os declara (claro, escuro automático e explícito).
TOKENS_CONTRATO = ("tinta", "tinta-suave", "tinta-fraca", "fundo", "superficie", "linha", "efeito", "alerta",
                   "presente", "consignado", "votou-ausente", "justificada", "ausente", "licenca",
                   "voto-maioria", "voto-diferente", "voto-abstencao")
TOKENS_MAPA = tuple(f"mapa-{i}" for i in range(1, 6))
CONTRATO = frozenset(TOKENS_CONTRATO + TOKENS_MAPA)
TEMAS = ("claro", "escuro-auto", "escuro-explicito")

# Pares declarados (frente, fundo, mínimo). Texto normal: 4,5:1; componentes, bordas de controle e cores de
# dado que não viram texto (efeito só aparece em barras, marcas e bordas): 3:1.
PARES = (
    ("tinta", "fundo", 4.5), ("tinta", "superficie", 4.5),
    ("tinta-suave", "fundo", 4.5), ("tinta-suave", "superficie", 4.5),
    ("tinta-fraca", "fundo", 4.5), ("tinta-fraca", "superficie", 4.5),
    ("baia", "fundo", 4.5), ("baia", "superficie", 4.5),
    ("mar", "fundo", 4.5), ("mar", "superficie", 4.5),
    ("por-do-sol", "fundo", 4.5), ("por-do-sol", "superficie", 4.5),
    # Sol da marca do cabeçalho: forma gráfica.
    ("marca-sol", "fundo", 3), ("marca-sol", "superficie", 3),
    # .n-alerta usa --alerta como cor de texto, sobre o fundo (placar) e sobre a superfície.
    ("alerta", "fundo", 4.5), ("alerta", "superficie", 4.5),
    ("efeito", "fundo", 3), ("efeito", "superficie", 3),
    # Selo de impacto alto (.selo.imp-3) e demais selos/etiquetas com texto em --tinta.
    ("selo-alto-texto", "selo-alto-fundo", 4.5),
    ("tinta", "efeito-fundo", 4.5), ("tinta", "sem-efeito-fundo", 4.5), ("tinta", "alerta-fundo", 4.5),
    ("borda-campo", "superficie", 3), ("borda-campo", "fundo", 3),
    ("foco", "fundo", 3), ("foco", "superficie", 3),
    # Glifos do mapa de votos: texto nas células (superfície) e gráfico na legenda (fundo).
    ("voto-maioria", "superficie", 4.5), ("voto-diferente", "superficie", 4.5), ("voto-abstencao", "superficie", 4.5),
    ("voto-maioria", "fundo", 3), ("voto-diferente", "fundo", 3), ("voto-abstencao", "fundo", 3),
)
# Fontes com preload em pagina(), na mesma ordem do <head>.
FONTES_CRITICAS = ("fontes/public-sans-latin-wght-normal.woff2", "fontes/barlow-condensed-latin-700-normal.woff2")


# ---- leitura do CSS ---------------------------------------------------------------------------------------------
def sem_comentarios(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def regras(css: str) -> list[tuple[tuple[str, ...], str, str]]:
    """Regras sem blocos internos: (at-rules envolventes, seletor ou at-rule, corpo)."""
    css = sem_comentarios(css)
    saida: list[tuple[tuple[str, ...], str, str]] = []
    pilha: list[list] = []  # [prelúdio normalizado, se já teve bloco interno]
    inicio = 0
    for m in re.finditer(r"[{}]", css):
        if m.group() == "{":
            if pilha:
                pilha[-1][1] = True
            pilha.append([" ".join(css[inicio:m.start()].split()), False])
        else:
            preludio, teve_filho = pilha.pop()
            if not teve_filho:
                saida.append((tuple(p for p, _ in pilha), preludio, css[inicio:m.start()]))
        inicio = m.end()
    if pilha:
        raise ValueError("CSS com chaves desbalanceadas")
    return saida


def declaracoes(corpo: str) -> dict[str, str]:
    saida = {}
    for parte in corpo.split(";"):
        nome, separador, valor = parte.partition(":")
        if separador and nome.strip():
            saida[nome.strip()] = " ".join(valor.split())
    return saida


def tipo_bloco(seletor: str) -> str | None:
    """Mesma classificação de tests/test_pagina_sessoes.py, separando o tema claro explícito."""
    if seletor == ":root":
        return "base"
    if seletor.startswith(":root:not("):
        return "escuro-auto"
    if seletor.startswith(":root["):
        return "claro-explicito" if 'data-theme="light"' in seletor else "escuro-explicito"
    return None


def escopo_claro(seletor: str) -> bool:
    """Seletor restrito ao tema claro explícito; :root:not([data-theme="light"]) é escuro automático."""
    return 'data-theme="light"' in re.sub(r":not\([^)]*\)", "", seletor)


def blocos(css: str) -> dict[str, list[dict[str, str]]]:
    saida: dict[str, list[dict[str, str]]] = {"base": [], "escuro-auto": [], "escuro-explicito": [], "claro-explicito": []}
    for _, seletor, corpo in regras(css):
        tipo = tipo_bloco(seletor)
        if tipo:
            saida[tipo].append(declaracoes(corpo))
    return saida


def tokens(lista: list[dict[str, str]]) -> dict[str, str]:
    saida: dict[str, str] = {}
    for decl in lista:
        saida.update({n[2:]: v for n, v in decl.items() if n.startswith("--")})
    return saida


def temas(css: str) -> dict[str, dict[str, str]]:
    """Tokens por tema: o :root vale em todos; os blocos escuros, mais específicos, sobrescrevem."""
    por_tipo = blocos(css)
    base = tokens(por_tipo["base"])
    return {"claro": base, "escuro-auto": {**base, **tokens(por_tipo["escuro-auto"])},
            "escuro-explicito": {**base, **tokens(por_tipo["escuro-explicito"])}}


def hex_contrato(valor: str) -> bool:
    return re.fullmatch(r"#[0-9A-Fa-f]{6}", valor.strip()) is not None


def problemas_contrato(css: str) -> list[str]:
    """Tokens de contrato declarados com outra coisa que hex de 6 dígitos (var(), hex curto, rgb...)."""
    return [f"{seletor}: {nome}: {valor}" for _, seletor, corpo in regras(css)
            for nome, valor in declaracoes(corpo).items() if nome[2:] in CONTRATO and not hex_contrato(valor)]


def hex_em_tema_claro(css: str) -> list[str]:
    return [f"{seletor}: {corpo.strip()}" for _, seletor, corpo in regras(css)
            if escopo_claro(seletor) and re.search(r"#[0-9A-Fa-f]{3,8}\b", corpo)]


# ---- cor e contraste WCAG -----------------------------------------------------------------------------------------
def rgba(valor: str, tema: dict[str, str], _vistos: tuple[str, ...] = ()) -> tuple[float, float, float, float]:
    """Resolve var(--x), hex de 6 dígitos e rgb()/rgba(); hex curto é recusado como nos tokens de contrato."""
    valor = valor.strip()
    m = re.fullmatch(r"var\(\s*--([\w-]+)\s*\)", valor)
    if m:
        nome = m.group(1)
        if nome in _vistos:
            raise ValueError(f"ciclo de tokens: {' -> '.join((*_vistos, nome))}")
        if nome not in tema:
            raise ValueError(f"token não declarado: --{nome}")
        return rgba(tema[nome], tema, (*_vistos, nome))
    if hex_contrato(valor):
        return int(valor[1:3], 16), int(valor[3:5], 16), int(valor[5:7], 16), 1.0
    m = re.fullmatch(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)", valor)
    if m:
        r, g, b = (float(x) for x in m.groups()[:3])
        return r, g, b, float(m.group(4)) if m.group(4) is not None else 1.0
    raise ValueError(f"cor não suportada: {valor!r}")


def compor(frente: tuple[float, float, float, float], fundo: tuple[float, float, float]) -> tuple[float, float, float]:
    alfa = frente[3]
    return tuple(f * alfa + b * (1 - alfa) for f, b in zip(frente[:3], fundo))


def luminancia(rgb: tuple[float, float, float]) -> float:
    canais = [c / 255 for c in rgb]
    linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in canais]
    return sum(v * peso for v, peso in zip(linear, (.2126, .7152, .0722)))


def contraste(tema: dict[str, str], frente: str, fundo: str) -> float:
    """Contraste WCAG; cores translúcidas são compostas sobre o fundo (e um fundo translúcido, sobre --fundo)."""
    cor_fundo = rgba(fundo, tema)
    base = compor(cor_fundo, rgba("var(--fundo)", tema)[:3]) if cor_fundo[3] < 1 else cor_fundo[:3]
    claro, escuro = sorted((luminancia(compor(rgba(frente, tema), base)), luminancia(base)), reverse=True)
    return (claro + .05) / (escuro + .05)


# ---- testes ---------------------------------------------------------------------------------------------------------
class TestPaleta(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css = CSS.read_text(encoding="utf-8")
        cls.temas = temas(cls.css)
        cls.blocos = blocos(cls.css)

    def test_pares_declarados_nos_tres_temas(self):
        for nome in TEMAS:
            tema = self.temas[nome]
            for frente, fundo, minimo in PARES:
                with self.subTest(tema=nome, par=(frente, fundo)):
                    razao = contraste(tema, f"var(--{frente})", f"var(--{fundo})")
                    self.assertGreaterEqual(razao, minimo, f"{frente} sobre {fundo}: {razao:.2f}:1")

    def test_valores_da_paleta_agua_escondida(self):
        esperado = {"claro": {"tinta": "#0B2A3F", "fundo": "#F7F2E9", "superficie": "#FFFFFF", "baia": "#13476B",
                              "mar": "#1F6F8B", "por-do-sol": "#B4491A", "por-do-sol-area": "#E8743B", "dourado": "#F2B544"},
                    "escuro": {"tinta": "#E6EEF4", "fundo": "#0E1B26", "superficie": "#14283A", "baia": "#9CC6E4",
                               "mar": "#5FB3CF", "por-do-sol": "#F08A55", "por-do-sol-area": "#E8743B", "dourado": "#F2B544"}}
        for nome in TEMAS:
            for token, valor in esperado["claro" if nome == "claro" else "escuro"].items():
                with self.subTest(tema=nome, token=token):
                    self.assertEqual(self.temas[nome][token].upper(), valor)

    def test_blocos_escuros_identicos(self):
        self.assertTrue(self.blocos["escuro-auto"])
        self.assertEqual(tokens(self.blocos["escuro-auto"]), tokens(self.blocos["escuro-explicito"]))
        for contexto, seletor, _ in regras(self.css):
            if tipo_bloco(seletor) == "escuro-auto":
                self.assertEqual(contexto, ("@media (prefers-color-scheme: dark)",))

    def test_tokens_de_contrato_hex_literal_em_cada_bloco(self):
        self.assertEqual(problemas_contrato(self.css), [])
        for tipo in ("base", "escuro-auto", "escuro-explicito"):
            declarados = tokens(self.blocos[tipo])
            for token in TOKENS_CONTRATO:
                with self.subTest(bloco=tipo, token=token):
                    self.assertIn(token, declarados)
                    self.assertTrue(hex_contrato(declarados[token]), declarados[token])
        for token in TOKENS_MAPA:
            with self.subTest(token=token):
                self.assertEqual(self.css.count(f"--{token}:"), 1)
                self.assertTrue(hex_contrato(tokens(self.blocos["base"])[token]))

    def test_nenhum_hex_no_tema_claro_explicito(self):
        self.assertEqual(hex_em_tema_claro(self.css), [])
        self.assertTrue(self.blocos["claro-explicito"])

    def test_color_scheme_por_tema(self):
        def esquema(tipo: str) -> list[str]:
            return [d["color-scheme"] for d in self.blocos[tipo] if "color-scheme" in d]

        self.assertEqual(esquema("base"), ["light dark"])
        self.assertEqual(esquema("escuro-explicito"), ["dark"])
        self.assertEqual(esquema("claro-explicito"), ["light"])
        self.assertEqual(esquema("escuro-auto"), [])

    def test_todo_var_usado_esta_declarado(self):
        texto = sem_comentarios(self.css)
        declarados = set(re.findall(r"(--[\w-]+)\s*:", texto))
        usados = set(re.findall(r"var\(\s*(--[\w-]+)", texto))
        self.assertTrue(usados)
        self.assertEqual(usados - declarados, set())

    def test_tokens_de_escala_e_movimento_so_no_root(self):
        base = tokens(self.blocos["base"])
        nomes = (["fs--1", *(f"fs-{i}" for i in range(0, 7))] + [f"esp-{i}" for i in range(1, 9)]
                 + ["raio-1", "raio-2", "raio-pilula", "sombra-1", "sombra-2", "dur-curta", "dur-media", "ease-mar"])
        for nome in nomes:
            with self.subTest(token=nome):
                self.assertIn(nome, base)
                for tipo in ("escuro-auto", "escuro-explicito", "claro-explicito"):
                    self.assertNotIn(nome, tokens(self.blocos[tipo]))
        self.assertTrue(all("clamp(" in base[f"fs-{i}"] for i in range(0, 7)) and "clamp(" in base["fs--1"])
        self.assertEqual([base[f"esp-{i}"] for i in range(1, 9)], ["4px", "8px", "12px", "16px", "24px", "32px", "48px", "64px"])
        self.assertEqual((base["dur-curta"], base["dur-media"]), ("150ms", "300ms"))
        self.assertEqual(base["ease-mar"].replace(" ", ""), "cubic-bezier(.2,.7,.2,1)")

    def test_regras_usam_os_tokens_de_contraste(self):
        self.assertRegex(self.css, r"(?m)^a\s*\{\s*color:\s*var\(--baia\);")
        self.assertRegex(self.css, r"\.selo\.imp-3\s*\{\s*background:\s*var\(--selo-alto-fundo\);\s*color:\s*var\(--selo-alto-texto\);")
        self.assertRegex(self.css, r'select, input\[type="search"\]\s*\{[^}]*border:\s*1px solid var\(--borda-campo\)')
        self.assertNotRegex(sem_comentarios(self.css), r"\.selo\.imp-3\s*\{[^}]*#fff")


class TestAuxiliares(unittest.TestCase):
    def test_hex_curto_recusado_e_var_permitido_fora_do_contrato(self):
        self.assertTrue(hex_contrato("#0B2A3F"))
        for valor in ("#fff", "#0B2A3F80", "var(--tinta)", "0B2A3F", "#0B2A3G"):
            self.assertFalse(hex_contrato(valor), valor)
        css = (':root { --tinta: #000; --fundo: #FFFFFF; --destaque: var(--fundo); --mapa-1: #F7FBFF; }\n'
               '@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --alerta: var(--tinta); } }\n'
               ':root[data-theme="dark"] { --tinta: #E6EEF4; --realce: var(--tinta); }')
        problemas = problemas_contrato(css)
        self.assertEqual(len(problemas), 2, problemas)
        self.assertIn(":root: --tinta: #000", problemas)
        self.assertIn(':root:not([data-theme="light"]): --alerta: var(--tinta)', problemas)
        self.assertEqual(temas(css)["escuro-explicito"]["realce"], "var(--tinta)")
        self.assertRaises(ValueError, rgba, "#fff", {})
        self.assertRaises(ValueError, rgba, "var(--a)", {"a": "var(--b)", "b": "var(--a)"})

    def test_rgba_composto_sobre_o_fundo(self):
        tema = {"fundo": "#FFFFFF", "destaque": "var(--fundo)", "veu": "rgba(0, 0, 0, .5)", "tinta": "#000000",
                "noite": "#000000", "neblina": "rgba(255, 255, 255, .5)"}
        # 50% de preto sobre branco: canal 127,5/255 = 0,5 → luminância ((0,555/1,055)^2,4) ≈ 0,2140.
        meio = ((.5 + .055) / 1.055) ** 2.4
        self.assertAlmostEqual(contraste(tema, "var(--veu)", "var(--destaque)"), 1.05 / (meio + .05), places=9)
        self.assertAlmostEqual(contraste(tema, "var(--veu)", "var(--fundo)"), 3.977, delta=.005)
        self.assertAlmostEqual(contraste(tema, "var(--neblina)", "var(--noite)"), (meio + .05) / .05, places=9)
        self.assertAlmostEqual(contraste(tema, "var(--tinta)", "var(--destaque)"), 21, places=9)
        self.assertAlmostEqual(contraste(tema, "rgba(0, 0, 0, 1)", "#FFFFFF"), 21, places=9)
        # Fundo translúcido é composto sobre --fundo antes de medir.
        self.assertAlmostEqual(contraste(tema, "#FFFFFF", "var(--veu)"), 1.05 / (meio + .05), places=9)

    def test_parser_de_blocos_e_tema_claro(self):
        css = '/* :root { --tinta: #FFFFFF } */ @media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --a: #000000; } }'
        self.assertEqual(regras(css), [(("@media (prefers-color-scheme: dark)",), ':root:not([data-theme="light"])', " --a: #000000; ")])
        self.assertEqual(hex_em_tema_claro(css), [])
        self.assertTrue(hex_em_tema_claro('[data-theme="light"] .x { color: #fff; }'))
        self.assertTrue(hex_em_tema_claro(':root[data-theme="light"] { --tinta: #0B2A3F; }'))
        self.assertEqual(hex_em_tema_claro(':root[data-theme="light"] { color-scheme: light; }'), [])


class TestFontes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css = CSS.read_text(encoding="utf-8")
        cls.faces = [declaracoes(corpo) for _, seletor, corpo in regras(cls.css) if seletor == "@font-face"]
        cls.web = [f for f in cls.faces if "url(" in f.get("src", "")]

    def test_font_face_com_display_unicode_range_e_arquivo_existente(self):
        referenciados = set()
        for face in self.web:
            with self.subTest(face=face.get("src")):
                self.assertEqual(face.get("font-display"), "swap")
                self.assertIn("unicode-range", face)
                self.assertIn('format("woff2")', face["src"])
                for alvo in re.findall(r"""url\(\s*["']?([^"')\s]+)""", face["src"]):
                    self.assertTrue(alvo.startswith("fontes/"), alvo)
                    self.assertTrue((FONTE / alvo).is_file(), alvo)
                    referenciados.add(alvo)
        disponiveis = {f"fontes/{p.name}" for p in (FONTE / "fontes").glob("*.woff2") if not p.name.startswith("fraunces")}
        self.assertEqual(referenciados, disponiveis)
        self.assertNotIn("Fraunces", sem_comentarios(self.css))

    def test_pesos_e_estilos(self):
        def familia(face: dict[str, str]) -> str:
            return face["font-family"].strip("\"'")

        barlow = [f for f in self.web if familia(f) == "Barlow Condensed"]
        public = [f for f in self.web if familia(f) == "Public Sans"]
        self.assertEqual(sorted(f["font-weight"] for f in barlow), ["500", "500", "600", "600", "700", "700"])
        self.assertEqual(sorted((f["font-style"], f["font-weight"]) for f in public),
                         [("italic", "100 900")] * 2 + [("normal", "100 900")] * 2)
        self.assertEqual(len(self.web), len(barlow) + len(public))

    def test_fallbacks_metricos_nas_pilhas(self):
        fallbacks = {f["font-family"].strip("\"'"): f for f in self.faces if "url(" not in f.get("src", "")}
        self.assertEqual(set(fallbacks),
                         {"Public Sans fallback", "Barlow Condensed fallback", "Barlow Condensed fallback largo"})
        for nome, face in fallbacks.items():
            with self.subTest(fonte=nome):
                self.assertTrue(face["src"].startswith("local("))
                for chave in ("size-adjust", "ascent-override", "descent-override", "line-gap-override"):
                    self.assertIn(chave, face)
        self.assertIn('local("Arial Narrow")', fallbacks["Barlow Condensed fallback"]["src"])
        base = temas(self.css)["claro"]
        self.assertTrue(base["texto"].startswith('"Public Sans", "Public Sans fallback",'))
        self.assertTrue(base["display"].startswith(
            '"Barlow Condensed", "Barlow Condensed fallback", "Barlow Condensed fallback largo",'))
        self.assertEqual(fallbacks["Barlow Condensed fallback largo"]["src"], 'local("Arial")')


class TestCabecalho(unittest.TestCase):
    def test_sem_google_fonts_nem_recursos_de_terceiros(self):
        html = P.pagina("Teste", "<p>conteúdo</p>", "index.html", prefixo="../")
        publicado = P.bytes_estaticos(CSS).decode("utf-8")
        for texto in (html, publicado, CSS.read_text(encoding="utf-8")):
            self.assertNotIn("fonts.googleapis", texto)
            self.assertNotIn("fonts.gstatic", texto)
        cabeca = html.split("</head>")[0]
        # A canônica é endereço de navegação, não recurso carregado.
        carregados = [m for m in re.findall(r"<link\b[^>]*>", cabeca) if 'rel="canonical"' not in m]
        for href in (re.search(r'\bhref="([^"]+)"', m).group(1) for m in carregados if 'href="' in m):
            self.assertNotRegex(href, r"^(?:[a-z][a-z0-9+.-]*:|//)", href)
        for alvo in re.findall(r"""url\(\s*["']?([^"')\s]+)""", sem_comentarios(publicado)):
            self.assertNotRegex(alvo, r"^(?:[a-z][a-z0-9+.-]*:|//)", alvo)

    def test_preload_com_a_mesma_url_da_css_publicada(self):
        publicado = P.bytes_estaticos(CSS).decode("utf-8")
        for prefixo in ("", "../"):
            with self.subTest(prefixo=prefixo):
                html = P.pagina("Teste", "", "index.html", prefixo=prefixo)
                hrefs = re.findall(r'<link rel="preload" as="font" type="font/woff2" crossorigin href="([^"]+)">', html)
                self.assertEqual(len(hrefs), len(FONTES_CRITICAS))
                for nome, href in zip(FONTES_CRITICAS, hrefs):
                    self.assertEqual(href, P.url_estatica(nome, prefixo))
                    self.assertEqual(href, f"{prefixo}{nome}?v={P.versao_bytes((FONTE / nome).read_bytes())}")
                    self.assertIn(f"url({href[len(prefixo):]})", publicado)
                self.assertLess(html.index('as="font"'), html.index("</head>"))


if __name__ == "__main__":
    unittest.main()
