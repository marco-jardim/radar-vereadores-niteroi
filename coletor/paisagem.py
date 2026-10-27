"""Gera a identidade visual do Radar a partir de uma única geometria, sem rede nem relógio.

A marca é um sol poente sobre três ondas que lembram as barras do placar: meio disco
cortado pelo horizonte e três traços ondulados de comprimento decrescente, alinhados à
esquerda como barras de um gráfico. A mesma geometria produz o favicon (SVG autônomo,
com cores próprias para os temas claro e escuro) e a marca do cabeçalho (sprite
`<symbol id="marca">` sem cores fixas: o sol herda `fill` e as ondas `currentColor` da
página, pelos tokens de estilo.css).

A paisagem do pôr do sol visto de Icaraí (Rio ao fundo, baía e ponte, Boa Viagem com o
MAC e a Pedra de Itapuca, orla com a Fortaleza de Santa Cruz) sai dos mesmos dados em
duas formas: quatro máscaras SVG monocromáticas para o topo da página inicial e a
imagem de compartilhamento 1200×630 em PNG, rasterizada aqui, sem dependências.

Uso: python -m coletor.paisagem [--marca] [--textura] [--camadas] [--og] (ao menos uma opção)
Grava favicon.svg e marca.svg em site_src/. --textura gera textura-bairros.svg
a partir da geometria local dos bairros. --camadas grava site_src/paisagem/*.svg e
--og grava site_src/og-radar.png. Mesma geometria, mesmos bytes (no PNG, mesmos pixels).
"""
from __future__ import annotations

import argparse
import contextlib
import gzip
import json
import math
import os
import re
import struct
import sys
import tempfile
import zlib
from collections import defaultdict
from functools import lru_cache
from html import escape
from pathlib import Path

from coletor.arquivos import _trocar, gravar_atomico

RAIZ = Path(__file__).resolve().parents[1]
SAIDA = RAIZ / "site_src"
GEOMETRIA = RAIZ / "data" / "geo" / "bairros.json"
SVG_NS = "http://www.w3.org/2000/svg"
TITULO = "Radar dos Vereadores de Niterói"

# Paleta do site (literais de estilo.css); só estas cores entram no favicon.
DOURADO = "#F2B544"  # --dourado, sol no tema escuro
POR_DO_SOL = "#B4491A"  # --por-do-sol do tema claro (≈ 5,4:1 sobre a aba branca)
BAIA = "#13476B"  # --baia, tema claro
BAIA_CLARA = "#9CC6E4"  # --baia do tema escuro, ondas
# Só no PNG de compartilhamento (também literais de estilo.css).
TINTA = "#0B2A3F"  # --tinta do tema claro: topo do céu e Boa Viagem
POR_DO_SOL_AREA = "#E8743B"  # --por-do-sol-area: faixa laranja do céu
MAR = "#1F6F8B"  # --mar: montanhas do Rio, a camada mais distante
NOITE = "#0E1B26"  # --fundo do tema escuro: orla, a camada mais próxima
CREME = "#F7F2E9"  # --fundo do tema claro: ondas da marca


# ---- geometria
LADO = 64  # viewBox quadrado; coordenadas inteiras em 64 dão meio pixel de resolução em 16 px
SOL = (32, 29, 21)  # centro x, linha do horizonte y, raio
ONDAS = ((8, 37, 48), (8, 48, 32), (8, 59, 16))  # x inicial, linha de base y, comprimento
ESPESSURA_ONDA = 6
AMPLITUDE_ONDA = 3  # deslocamento do ponto de controle; a crista fica na metade disso
MEIO_PERIODO = 8  # os comprimentos são múltiplos dele, para cada onda terminar na base


def numero(x: float) -> str:
    """Formato fixo: inteiros sem casas; demais com até duas casas, sem zeros à direita."""
    if float(x).is_integer():
        return str(int(x))
    return f"{x:.2f}".rstrip("0").rstrip(".")


def caminho_sol(cx: float = SOL[0], horizonte: float = SOL[1], raio: float = SOL[2]) -> str:
    """Meio disco acima do horizonte: arco da esquerda para a direita passando pelo topo."""
    r = numero(raio)
    return f"M{numero(cx - raio)} {numero(horizonte)}A{r} {r} 0 0 1 {numero(cx + raio)} {numero(horizonte)}Z"


def caminho_onda(x: float, y: float, comprimento: float) -> str:
    """Traço ondulado: uma curva quadrática e reflexões (t) a cada meio período."""
    meios = int(comprimento // MEIO_PERIODO)
    if meios < 1 or meios * MEIO_PERIODO != comprimento:
        raise ValueError(f"comprimento de onda deve ser múltiplo positivo de {MEIO_PERIODO}: {comprimento}")
    passo = numero(MEIO_PERIODO)
    inicio = f"M{numero(x)} {numero(y)}q{numero(MEIO_PERIODO / 2)} {numero(-AMPLITUDE_ONDA)} {passo} 0"
    return inicio + f"t{passo} 0" * (meios - 1)


def caminho_ondas() -> str:
    """As três ondas num só path, da mais longa à mais curta."""
    return "".join(caminho_onda(x, y, c) for x, y, c in ONDAS)


def _viewbox() -> str:
    return f"0 0 {LADO} {LADO}"


# ---- marca
def favicon_svg() -> str:
    """Favicon autônomo: classes para que a media query troque as cores no tema escuro.

    Sem fundo próprio: no claro, sol #B4491A e ondas #13476B contra a aba branca; no
    escuro, sol #F2B544 e ondas #9CC6E4. Todas as formas ficam com contraste ≥ 3:1.
    """
    estilo = (f".s{{fill:{POR_DO_SOL}}}"
              f".o{{fill:none;stroke:{BAIA};stroke-width:{numero(ESPESSURA_ONDA)};stroke-linecap:round}}"
              f"@media (prefers-color-scheme: dark){{.s{{fill:{DOURADO}}}.o{{stroke:{BAIA_CLARA}}}}}")
    return (f'<svg xmlns="{SVG_NS}" viewBox="{_viewbox()}">'
            f"<title>{TITULO}</title>"
            f"<style>{estilo}</style>"
            f'<path class="s" d="{caminho_sol()}"/>'
            f'<path class="o" d="{caminho_ondas()}"/>'
            "</svg>\n")


def marca_svg() -> str:
    """Sprite do cabeçalho: `<use href="marca.svg?v=…#marca">` herda `fill` (sol) e `color` (ondas).

    As cores vêm de `.marca svg` em estilo.css (`--marca-sol` e `--baia`), por tema.
    """
    return (f'<svg xmlns="{SVG_NS}" viewBox="{_viewbox()}">'
            f'<symbol id="marca" viewBox="{_viewbox()}">'
            f'<path d="{caminho_sol()}"/>'
            f'<path fill="none" stroke="currentColor" stroke-width="{numero(ESPESSURA_ONDA)}" '
            f'stroke-linecap="round" d="{caminho_ondas()}"/>'
            "</symbol></svg>\n")


def exibir(caminho: Path) -> str:
    """Caminho gravado, relativo à raiz do repositório quando estiver dentro dela."""
    try:
        return caminho.resolve().relative_to(RAIZ).as_posix()
    except ValueError:
        return str(caminho)


def gravar(caminho: Path, texto: str) -> None:
    """Gravação atômica (temporário na mesma pasta + os.replace), UTF-8 e LF."""
    gravar_atomico(caminho, texto)


# ---- textura
LIMITE_TEXTURA_GZIP = 12 * 1024
DISTANCIA_TEXTURA = 2  # Fixa: com bordas deduplicadas, ~10,5 KiB gzip, margem estável abaixo dos 12 KiB.


def _caminhos_textura(geo: dict) -> str:
    """Deduplica segmentos não orientados antes de encadear vértices de grau dois."""
    segmentos = set()
    for bairro in geo["bairros"].values():
        for anel in re.findall(r"M([^MZ]+)Z", bairro["path"]):
            pontos = [tuple(map(int, par.split(","))) for par in anel.split()]
            for a, b in zip(pontos, pontos[1:] + pontos[:1]):
                if a != b:
                    segmentos.add(tuple(sorted((a, b))))
    vizinhos = defaultdict(set)
    for a, b in segmentos:
        vizinhos[a].add(b)
        vizinhos[b].add(a)
    restantes = set(segmentos)
    linhas = []

    def encadear(a, b):
        pontos = [a]
        while True:
            restantes.remove(tuple(sorted((a, b))))
            pontos.append(b)
            proximos = sorted(c for c in vizinhos[b] if tuple(sorted((b, c))) in restantes)
            if len(vizinhos[b]) != 2 or not proximos:
                break
            a, b = b, proximos[0]
        # Distância fixa, nunca escolhida pelo tamanho comprimido ou pela versão do zlib.
        manter = [pontos[0]]
        for x, y in pontos[1:-1]:
            if (x - manter[-1][0]) ** 2 + (y - manter[-1][1]) ** 2 >= DISTANCIA_TEXTURA ** 2:
                manter.append((x, y))
        manter.append(pontos[-1])
        if pontos[0] == pontos[-1] and len(set(manter)) < 3:
            manter = pontos
        linhas.append("M" + " ".join(f"{x},{y}" for x, y in manter))

    # Primeiro as linhas entre entroncamentos; depois os ciclos isolados, sempre ordenados.
    for a in sorted(vizinhos):
        if len(vizinhos[a]) != 2:
            for b in sorted(vizinhos[a]):
                if tuple(sorted((a, b))) in restantes:
                    encadear(a, b)
    for a, b in sorted(restantes):
        if (a, b) in restantes:
            encadear(a, b)
    return "".join(linhas)


def textura_svg(geo: dict) -> str:
    """Máscara decorativa: contornos pretos sobre transparência, sem dados temáticos.

    Mantém o viewBox e deduplica as bordas dos 52 bairros antes de qualquer redução
    por distância fixa; não substitui a geometria dos mapas nem serve a cadastro.
    """
    from coletor.validar import validar_geo

    problemas = validar_geo(geo)
    if problemas:
        raise ValueError("; ".join(problemas))
    viewbox = " ".join(str(v) for v in geo["viewbox"])
    descricao = escape("© contribuidores do OpenStreetMap, ODbL 1.0, "
                       "https://www.openstreetmap.org/copyright. "
                       f"Base OSM: {geo['osm_base']}. Contornos simplificados para decoração; não é um mapa cadastral.")
    return (f'<svg xmlns="{SVG_NS}" viewBox="{viewbox}">'
            '<title>Contornos dos bairros de Niterói</title>'
            f'<desc>{descricao}</desc>'
            '<path fill="none" stroke="#000" stroke-width="1" vector-effect="non-scaling-stroke" '
            f'd="{_caminhos_textura(geo)}"/></svg>\n')


# ---- silhuetas
# Vista de Icaraí para oeste, com o sol se pondo atrás do Rio. Unidades da vista: x para a
# direita, y para baixo. Todas as curvas são polilinhas de funções simples, só com soma,
# produto, divisão e raiz quadrada (exatas em IEEE 754), arredondadas para inteiros.
LARGURA_VISTA = 1600
ALTURA_VISTA = 600
VIEWBOX_PAISAGEM = f"0 0 {LARGURA_VISTA} {ALTURA_VISTA}"
HORIZONTE = 448  # topo da faixa de água da baía
BASE_RIO = 452  # pé das montanhas do Rio, logo abaixo do horizonte
PASSO_PERFIL = 5  # amostragem horizontal dos perfis das montanhas
# Rio ao fundo, da esquerda para a direita: forma, centro x, largura, altura acima da base.
RIO = (
    ("morro", 120, 420, 34),  # morros distantes da entrada da baía
    ("morro", 330, 190, 78),  # Morro da Urca
    ("cupula", 452, 128, 150),  # Pão de Açúcar
    ("morro", 660, 300, 40),  # colinas baixas entre os dois
    ("morro", 900, 560, 118),  # maciço do Corcovado
    ("pico", 960, 56, 172),  # pico do Corcovado
    ("morro", 1150, 380, 92),  # serra ao fundo
    ("morro", 1420, 520, 52),  # morros distantes do Centro
)
# Ponte Rio–Niterói: tabuleiro fino que nasce na água à esquerda e sai pela direita.
PONTE_X0 = 660
PONTE_Y = 404  # topo do tabuleiro fora da rampa e do arco
PONTE_ESPESSURA = 7
PONTE_RAMPA = (780, 0.375)  # à esquerda deste x, o tabuleiro desce até a água nesta inclinação
ARCO_PONTE = (980, 300, 16)  # vão central: centro x, largura, altura
PILARES = ((720, 6), (790, 6), (850, 6), (910, 10), (1050, 10), (1110, 6), (1170, 6), (1230, 6),
           (1290, 6), (1350, 6), (1410, 6), (1470, 6), (1530, 6), (1590, 6))  # x, largura
# Boa Viagem: perfil do promontório, fechado pela linha d'água do primeiro e do último ponto.
BOA_VIAGEM = ((1080, 506), (1094, 482), (1108, 458), (1122, 440), (1142, 430), (1180, 425), (1280, 424),
              (1320, 428), (1348, 440), (1374, 462), (1396, 488), (1410, 506))
# MAC: centro x, chão, meia largura do pé, topo do pé, raio do disco, borda inferior e
# superior do disco, topo da cúpula rasa.
MAC = (1232, 424, 13, 402, 76, 384, 378, 368)
RAMPA_MAC = (1220, 403, 80, 24, 4)  # início no pé do museu, extensão à esquerda, descida, espessura
ITAPUCA = (1496, 522, 104, 56)  # centro x, linha d'água, largura, altura
AREIA = (566, 16)  # topo da areia no centro e quanto ele sobe até as pontas
# Fortaleza de Santa Cruz na borda esquerda: rochedo e muralha baixa com guaritas.
FORTALEZA = ((0, 452), (18, 452), (18, 444), (30, 444), (30, 452), (96, 456), (96, 450), (108, 450), (108, 457),
             (150, 462), (168, 474), (186, 490), (204, 508), (0, 508))
EDIFICIOS = ((236, 34, 520), (272, 22, 532), (296, 40, 512), (338, 28, 526), (368, 46, 506), (416, 24, 530),
             (442, 36, 516), (480, 30, 524), (512, 44, 510), (1290, 30, 520), (1322, 38, 508), (1362, 26, 526),
             (1390, 40, 512))  # x esquerdo, largura, topo; todos descem até a base da vista


def _u(x: float, cx: float, largura: float) -> float:
    return (x - cx) / (largura / 2)


def _cupula(x: float, cx: float, largura: float, altura: float) -> float:
    """Flancos quase verticais e topo arredondado, como o Pão de Açúcar."""
    u = _u(x, cx, largura)
    if abs(u) >= 1:
        return 0.0
    u2 = u * u
    return altura * math.sqrt(1 - u2 * u2)


def _morro(x: float, cx: float, largura: float, altura: float) -> float:
    """Elevação suave, sem quinas nas pontas."""
    u = _u(x, cx, largura)
    if abs(u) >= 1:
        return 0.0
    v = 1 - u * u
    return altura * v * v


def _pico(x: float, cx: float, largura: float, altura: float) -> float:
    """Pico estreito e pontudo."""
    u = _u(x, cx, largura)
    if abs(u) >= 1:
        return 0.0
    return altura * (1 - u * u)


FORMAS = {"cupula": _cupula, "morro": _morro, "pico": _pico}


def _area_dupla(pontos: list[tuple[float, float]]) -> float:
    """Dobro da área com sinal (fórmula do laço)."""
    return sum(xa * yb - xb * ya for (xa, ya), (xb, yb) in zip(pontos, pontos[1:] + pontos[:1]))


def _poligono(pontos) -> list[tuple[int, int]]:
    """Arredonda, tira repetidos e vértices colineares intermediários e fixa a orientação.

    Todos os polígonos ficam com área positiva: a união pela regra nonzero (padrão do SVG e
    do rasterizador) nunca cancela sobreposições entre partes da mesma camada.
    """
    inteiros: list[tuple[int, int]] = []
    for x, y in pontos:
        p = (int(round(x)), int(round(y)))
        if not inteiros or inteiros[-1] != p:
            inteiros.append(p)
    while len(inteiros) > 1 and inteiros[0] == inteiros[-1]:
        inteiros.pop()
    enxuto: list[tuple[int, int]] = []
    for i, p in enumerate(inteiros):
        if enxuto and i + 1 < len(inteiros):
            a, b = enxuto[-1], inteiros[i + 1]
            colinear = (p[0] - a[0]) * (b[1] - a[1]) - (p[1] - a[1]) * (b[0] - a[0]) == 0
            entre = min(a[0], b[0]) <= p[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])
            if colinear and entre:
                continue
        enxuto.append(p)
    if len(enxuto) < 3:
        raise ValueError(f"polígono degenerado depois do arredondamento: {enxuto}")
    if _area_dupla(enxuto) < 0:
        enxuto.reverse()
    return enxuto


def _amostras(x0: int, x1: int, passo: int) -> list[int]:
    """x0, x0 + passo, … e sempre x1 no fim."""
    return list(range(x0, x1, passo)) + [x1]


def _rio() -> list[list[tuple[int, int]]]:
    def altura(x: float) -> float:
        return max(FORMAS[forma](x, cx, largura, alt) for forma, cx, largura, alt in RIO)

    topo = [(x, BASE_RIO - altura(x)) for x in _amostras(0, LARGURA_VISTA, PASSO_PERFIL)]
    return [_poligono([(0, ALTURA_VISTA)] + topo + [(LARGURA_VISTA, ALTURA_VISTA)])]


def _topo_ponte(x: float) -> float:
    inicio, inclinacao = PONTE_RAMPA
    return PONTE_Y - _morro(x, *ARCO_PONTE) + max(0, inicio - x) * inclinacao


def _baia() -> list[list[tuple[int, int]]]:
    agua = _poligono([(0, HORIZONTE), (LARGURA_VISTA, HORIZONTE), (LARGURA_VISTA, ALTURA_VISTA), (0, ALTURA_VISTA)])
    xs = _amostras(PONTE_X0, LARGURA_VISTA, 10)
    tabuleiro = _poligono([(x, _topo_ponte(x)) for x in xs]
                          + [(x, _topo_ponte(x) + PONTE_ESPESSURA) for x in reversed(xs)])
    pilares = []
    for x, largura in PILARES:
        topo = int(round(_topo_ponte(x))) + PONTE_ESPESSURA - 1  # um pouco dentro do tabuleiro
        esquerda, direita = x - largura // 2, x + largura - largura // 2
        pilares.append(_poligono([(esquerda, topo), (direita, topo), (direita, HORIZONTE + 2),
                                  (esquerda, HORIZONTE + 2)]))
    return [agua, tabuleiro, *pilares]


def _mac() -> list[tuple[int, int]]:
    """Disco largo e chato sobre pé cilíndrico estreito, com cúpula rasa no topo."""
    cx, chao, pe, topo_pe, raio, borda_inf, borda_sup, cimo = MAC

    def sob(dx: float) -> float:  # curva convexa sob o disco, do pé até a borda
        u = dx / raio
        return borda_inf + (topo_pe - borda_inf) * (1 - u * u)

    def cupula(dx: float) -> float:
        u = dx / raio
        return borda_sup - (borda_sup - cimo) * (1 - u * u)

    lados = _amostras(pe, raio, 7)
    pontos = [(cx - pe, chao), (cx - pe, topo_pe)]
    pontos += [(cx - dx, sob(dx)) for dx in lados]
    pontos += [(cx + dx, cupula(dx)) for dx in _amostras(-raio, raio, 8)]
    pontos += [(cx + dx, sob(dx)) for dx in reversed(lados)]
    pontos += [(cx + pe, topo_pe), (cx + pe, chao)]
    return _poligono(pontos)


def _rampa_mac() -> list[tuple[int, int]]:
    """Faixa curva que desce do pé do museu até o chão, à esquerda."""
    x0, y0, extensao, descida, espessura = RAMPA_MAC
    linha = [(x0 - extensao * t, y0 + descida * t * (2 - t)) for t in (i / 10 for i in range(11))]
    return _poligono(linha + [(x, y + espessura) for x, y in reversed(linha)])


def _itapuca() -> list[tuple[int, int]]:
    """Rochedo assimétrico, mais alto à direita, com pequenas quebras no topo."""
    cx, base, largura, altura = ITAPUCA
    pontos = []
    for i in range(13):
        u = -1 + i / 6
        h = altura * (1 - u * u) * (1 + 0.25 * u) - (5 if i % 3 == 1 else 0)
        pontos.append((cx + u * largura / 2, base - max(0.0, h)))
    return _poligono(pontos)


def _promontorio() -> list[list[tuple[int, int]]]:
    return [_poligono(BOA_VIAGEM), _mac(), _rampa_mac(), _itapuca()]


def _orla() -> list[list[tuple[int, int]]]:
    centro, subida = AREIA
    meio = LARGURA_VISTA / 2

    def topo(x: float) -> float:
        u = (x - meio) / meio
        return centro - subida * u * u

    areia = _poligono([(0, ALTURA_VISTA)] + [(x, topo(x)) for x in _amostras(0, LARGURA_VISTA, 40)]
                      + [(LARGURA_VISTA, ALTURA_VISTA)])
    predios = [_poligono([(x, y), (x + largura, y), (x + largura, ALTURA_VISTA), (x, ALTURA_VISTA)])
               for x, largura, y in EDIFICIOS]
    return [areia, _poligono(FORTALEZA), *predios]


def silhuetas() -> dict[str, list[list[tuple[int, int]]]]:
    """Camadas do fundo para a frente: nome -> polígonos inteiros nas unidades da vista."""
    return {"fundo": _rio(), "baia": _baia(), "promontorio": _promontorio(), "orla": _orla()}


# ---- svg
LIMITE_CAMADAS_GZIP = 18 * 1024  # soma das quatro máscaras, gzip nível 9 sem data


def _caminho_poligonos(poligonos: list[list[tuple[int, int]]]) -> str:
    return "".join("M" + " ".join(f"{x},{y}" for x, y in p) + "Z" for p in poligonos)


def camada_svg(poligonos: list[list[tuple[int, int]]]) -> str:
    """Máscara decorativa: formas pretas sobre transparência, ancoradas embaixo e no centro."""
    return (f'<svg xmlns="{SVG_NS}" viewBox="{VIEWBOX_PAISAGEM}" preserveAspectRatio="xMidYMax slice">'
            f'<path fill="#000" d="{_caminho_poligonos(poligonos)}"/></svg>\n')


def camadas_svg() -> dict[str, str]:
    """Nome do arquivo -> SVG, do fundo para a frente (fundo, baia, promontorio, orla)."""
    return {f"{nome}.svg": camada_svg(poligonos) for nome, poligonos in silhuetas().items()}


def tamanho_gzip(texto: str) -> int:
    return len(gzip.compress(texto.encode("utf-8"), compresslevel=9, mtime=0))


# ---- png
LARGURA_OG = 1200
ALTURA_OG = 630
SUBAMOSTRAS = 4  # linhas de amostragem por linha de pixels; na horizontal a cobertura é exata
SOL_POENTE = (560, 370, 70)  # centro x, centro y e raio do sol, nas unidades da vista
LADOS_SOL = 32  # vértices por meia circunferência
CEU = ((0.0, TINTA), (0.38, BAIA), (0.62, POR_DO_SOL_AREA), (0.76, DOURADO), (1.0, DOURADO))  # fração da altura
TONS_CAMADAS = {"fundo": MAR, "baia": BAIA, "promontorio": TINTA, "orla": NOITE}
TAMANHO_MARCA = 0.15  # lado da marca no canto superior esquerdo, em fração da altura da imagem
MARGEM_MARCA = 0.06


def _rgb(cor: str) -> tuple[int, int, int]:
    return int(cor[1:3], 16), int(cor[3:5], 16), int(cor[5:7], 16)


def escala_quadro(largura: int, altura: int) -> tuple[float, float, float]:
    """Escala e deslocamentos x, y da vista no quadro, como `xMidYMax slice` no SVG."""
    escala = max(largura / LARGURA_VISTA, altura / ALTURA_VISTA)
    return escala, (largura - LARGURA_VISTA * escala) / 2, altura - ALTURA_VISTA * escala


def _semicirculo(n: int) -> list[tuple[float, float]]:
    """n + 1 pontos da metade superior do círculo unitário (y para cima), da esquerda para a direita.

    Parametrização racional, sem seno nem cosseno: os mesmos pontos em qualquer plataforma.
    """
    pontos = []
    for i in range(n + 1):
        t = -1 + 2 * i / n
        d = 1 + t * t
        pontos.append((2 * t / d, (1 - t * t) / d))
    return pontos


def _circulo(cx: float, cy: float, raio: float, n: int) -> list[tuple[float, float]]:
    metade = _semicirculo(n)[:-1]
    return ([(cx + raio * x, cy - raio * y) for x, y in metade]
            + [(cx - raio * x, cy + raio * y) for x, y in metade])


def _pontos_onda(x: float, y: float, comprimento: float, n: int = 8) -> list[tuple[float, float]]:
    """Polilinha da mesma onda de `caminho_onda`: quadráticas com controle alternado."""
    meios = int(comprimento // MEIO_PERIODO)
    if meios < 1 or meios * MEIO_PERIODO != comprimento:
        raise ValueError(f"comprimento de onda deve ser múltiplo positivo de {MEIO_PERIODO}: {comprimento}")
    pontos = [(float(x), float(y))]
    for k in range(meios):
        x0, x1 = x + k * MEIO_PERIODO, x + (k + 1) * MEIO_PERIODO
        cy = y - AMPLITUDE_ONDA if k % 2 == 0 else y + AMPLITUDE_ONDA
        cx = x0 + MEIO_PERIODO / 2
        for i in range(1, n + 1):
            t = i / n
            a, b, c = (1 - t) * (1 - t), 2 * (1 - t) * t, t * t
            pontos.append((a * x0 + b * cx + c * x1, a * y + b * cy + c * y))
    return pontos


def _traco(pontos: list[tuple[float, float]], meia: float) -> list[list[tuple[float, float]]]:
    """Traço grosso com pontas e junções redondas: um quadrilátero por segmento e um disco por vértice."""
    partes = []
    for (xa, ya), (xb, yb) in zip(pontos, pontos[1:]):
        dx, dy = xb - xa, yb - ya
        comprimento = math.sqrt(dx * dx + dy * dy)
        if comprimento == 0:
            continue
        nx, ny = -dy / comprimento * meia, dx / comprimento * meia
        partes.append([(xa + nx, ya + ny), (xb + nx, yb + ny), (xb - nx, yb - ny), (xa - nx, ya - ny)])
    partes.extend(_circulo(x, y, meia, 8) for x, y in pontos)
    return partes


def _arestas(poligonos) -> list[tuple[float, float, float, float, int]]:
    """Arestas não horizontais (y de cima, y de baixo, x em cima, dx/dy, sentido).

    O sentido é normalizado pela orientação de cada polígono: a regra nonzero vira a união
    das partes, sem cancelamento onde elas se sobrepõem.
    """
    arestas = []
    for poligono in poligonos:
        pontos = [(float(x), float(y)) for x, y in poligono]
        if len(pontos) < 3:
            raise ValueError(f"polígono precisa de ao menos 3 pontos, recebeu {len(pontos)}")
        sinal = -1 if _area_dupla(pontos) < 0 else 1
        for (xa, ya), (xb, yb) in zip(pontos, pontos[1:] + pontos[:1]):
            if ya == yb:
                continue
            if ya < yb:
                arestas.append((ya, yb, xa, (xb - xa) / (yb - ya), sinal))
            else:
                arestas.append((yb, ya, xb, (xa - xb) / (ya - yb), -sinal))
    return arestas


def _acumular(cheios: dict[int, int], parcial: dict[int, float], a: float, b: float, largura: int) -> None:
    """Soma um trecho [a, b) de uma linha de amostragem, recortado ao quadro.

    Pixels inteiros vão para a tabela de diferenças `cheios`; as pontas, para `parcial`, com
    a fração exata coberta.
    """
    a = max(a, 0.0)
    b = min(b, float(largura))
    if b <= a:
        return
    ia, ib = int(a), int(b)
    if ia == ib:
        parcial[ia] += b - a
        return
    parcial[ia] += ia + 1 - a
    if ia + 1 < ib:
        cheios[ia + 1] += 1
        cheios[ib] -= 1
    if b > ib:
        parcial[ib] += b - ib


@lru_cache(maxsize=None)
def _tabelas(cor: tuple[int, int, int], alfa: float) -> tuple[bytes, ...]:
    """Uma tabela de tradução por canal para misturar `cor` com opacidade `alfa`."""
    return tuple(bytes(int(v + (c - v) * alfa + 0.5) for v in range(256)) for c in cor)


def _misturar(linha: bytearray, x: int, cor: tuple[int, int, int], alfa: float) -> None:
    if alfa <= 0:
        return
    i = 3 * x
    if alfa >= 1:
        linha[i:i + 3] = bytes(cor)
        return
    for k in range(3):
        v = linha[i + k]
        linha[i + k] = int(v + (cor[k] - v) * alfa + 0.5)


def _compor(linha: bytearray, cheios: dict[int, int], parcial: dict[int, float],
            cor: tuple[int, int, int], largura: int) -> None:
    """Aplica a cobertura de uma linha: faixas constantes por fatia, pontas pixel a pixel."""
    eventos = sorted(set(cheios).union(parcial))
    contagem = 0
    for i, p in enumerate(eventos):
        if p >= largura:
            break
        contagem += cheios.get(p, 0)
        fim = min(eventos[i + 1] if i + 1 < len(eventos) else largura, largura)
        inicio = p
        if p in parcial:
            _misturar(linha, p, cor, min(1.0, (contagem + parcial[p]) / SUBAMOSTRAS))
            inicio = p + 1
        if contagem <= 0 or inicio >= fim:
            continue
        if contagem >= SUBAMOSTRAS:
            linha[3 * inicio:3 * fim] = bytes(cor) * (fim - inicio)
        else:
            for k, tabela in enumerate(_tabelas(cor, contagem / SUBAMOSTRAS)):
                fatia = slice(3 * inicio + k, 3 * fim, 3)
                linha[fatia] = linha[fatia].translate(tabela)


def preencher(linhas: list[bytearray], largura: int, altura: int, poligonos, cor: tuple[int, int, int]) -> None:
    """Pinta a união dos polígonos (coordenadas em pixels) sobre as linhas RGB, com antisserrilhado.

    Cada linha de pixels é amostrada em SUBAMOSTRAS alturas; em cada uma, os cruzamentos
    das arestas dão trechos pela regra nonzero, e a cobertura horizontal de cada trecho é
    exata. Pontos fora do quadro são recortados; polígono com menos de 3 pontos é erro.
    """
    arestas = _arestas(poligonos)
    cor = tuple(int(c) for c in cor)
    baldes: list[list[tuple]] = [[] for _ in range(altura)]
    for aresta in arestas:
        for r in range(max(0, math.floor(aresta[0])), min(altura - 1, math.floor(aresta[1])) + 1):
            baldes[r].append(aresta)
    for r, ativas in enumerate(baldes):
        if not ativas:
            continue
        cheios: dict[int, int] = defaultdict(int)
        parcial: dict[int, float] = defaultdict(float)
        for j in range(SUBAMOSTRAS):
            ys = r + (j + 0.5) / SUBAMOSTRAS
            cruzamentos = sorted((x0 + (ys - y0) * inclinacao, sentido)
                                 for y0, y1, x0, inclinacao, sentido in ativas if y0 <= ys < y1)
            enrolamento = 0
            abertura = 0.0
            for x, sentido in cruzamentos:
                if enrolamento == 0:
                    abertura = x
                enrolamento += sentido
                if enrolamento == 0:
                    _acumular(cheios, parcial, abertura, x, largura)
        if cheios or parcial:
            _compor(linhas[r], cheios, parcial, cor, largura)


def _cor_ceu(t: float) -> tuple[int, int, int]:
    """Degradê vertical do céu pelas paradas de CEU (t = 0 no topo, 1 na base)."""
    for (t0, c0), (t1, c1) in zip(CEU, CEU[1:]):
        if t <= t1:
            f = 0.0 if t1 == t0 else max(0.0, (t - t0) / (t1 - t0))
            return tuple(int(a + (b - a) * f + 0.5) for a, b in zip(_rgb(c0), _rgb(c1)))
    return _rgb(CEU[-1][1])


def _desenhar_marca(linhas: list[bytearray], largura: int, altura: int) -> None:
    """A geometria da marca (sol e três ondas) no canto superior esquerdo, sem texto."""
    escala = altura * TAMANHO_MARCA / LADO
    margem = altura * MARGEM_MARCA

    def no_quadro(pontos):
        return [(margem + x * escala, margem + y * escala) for x, y in pontos]

    cx, horizonte, raio = SOL
    sol = [(cx + raio * x, horizonte - raio * y) for x, y in _semicirculo(LADOS_SOL)]
    preencher(linhas, largura, altura, [no_quadro(sol)], _rgb(DOURADO))
    tracos = []
    for x, y, comprimento in ONDAS:
        tracos.extend(_traco(_pontos_onda(x, y, comprimento), ESPESSURA_ONDA / 2))
    preencher(linhas, largura, altura, [no_quadro(p) for p in tracos], _rgb(CREME))


def rasterizar(largura: int, altura: int) -> bytes:
    """Pixels RGB (linhas de cima para baixo) da imagem de compartilhamento em qualquer tamanho.

    Céu em degradê, sol, as quatro camadas da paisagem em tons do fundo (mais claro) para a
    frente (mais escuro) e a marca no canto. Sem texto. Mesmo tamanho, mesmos pixels.
    """
    if largura < 1 or altura < 1:
        raise ValueError(f"tamanho inválido: {largura}×{altura}")
    linhas = [bytearray(bytes(_cor_ceu((y + 0.5) / altura)) * largura) for y in range(altura)]
    escala, ox, oy = escala_quadro(largura, altura)

    def no_quadro(pontos):
        return [(ox + x * escala, oy + y * escala) for x, y in pontos]

    cx, cy, raio = SOL_POENTE
    preencher(linhas, largura, altura, [no_quadro(_circulo(cx, cy, raio, LADOS_SOL))], _rgb(DOURADO))
    for nome, poligonos in silhuetas().items():
        preencher(linhas, largura, altura, [no_quadro(p) for p in poligonos], _rgb(TONS_CAMADAS[nome]))
    _desenhar_marca(linhas, largura, altura)
    return b"".join(linhas)


def _bloco_png(tipo: bytes, dados: bytes) -> bytes:
    return struct.pack(">I", len(dados)) + tipo + dados + struct.pack(">I", zlib.crc32(tipo + dados) & 0xFFFFFFFF)


def png(largura: int, altura: int, pixels: bytes) -> bytes:
    """PNG RGB de 8 bits (tipo de cor 2), filtro 0 em todas as linhas, zlib nível 9."""
    passo = 3 * largura
    if largura < 1 or altura < 1 or len(pixels) != passo * altura:
        raise ValueError(f"pixels incompatíveis com {largura}×{altura}: {len(pixels)} bytes")
    bruto = b"".join(b"\x00" + pixels[i * passo:(i + 1) * passo] for i in range(altura))
    cabecalho = struct.pack(">IIBBBBB", largura, altura, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _bloco_png(b"IHDR", cabecalho)
            + _bloco_png(b"IDAT", zlib.compress(bruto, 9)) + _bloco_png(b"IEND", b""))


def og_png() -> bytes:
    """Imagem de compartilhamento (Open Graph) em LARGURA_OG×ALTURA_OG."""
    return png(LARGURA_OG, ALTURA_OG, rasterizar(LARGURA_OG, ALTURA_OG))


def gravar_binario(caminho: Path, dados: bytes) -> None:
    """Gravação atômica de bytes: temporário na mesma pasta e troca com nova tentativa."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fd, temporario = tempfile.mkstemp(dir=caminho.parent, prefix=f".{caminho.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(dados)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(temporario, 0o644)
        _trocar(temporario, caminho)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporario)
        raise


# ---- cli
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--marca", action="store_true", help="grava favicon.svg e marca.svg em site_src/")
    ap.add_argument("--textura", action="store_true", help="grava textura-bairros.svg usando data/geo/bairros.json")
    ap.add_argument("--camadas", action="store_true", help="grava as quatro máscaras da paisagem em site_src/paisagem/")
    ap.add_argument("--og", action="store_true", help="grava a imagem de compartilhamento site_src/og-radar.png")
    args = ap.parse_args(argv)
    if not (args.marca or args.textura or args.camadas or args.og):
        ap.print_usage(sys.stderr)
        print("nada a fazer: informe --marca, --textura, --camadas ou --og", file=sys.stderr)
        return 2
    arquivos = []
    if args.marca:
        arquivos.extend((("favicon.svg", favicon_svg()), ("marca.svg", marca_svg())))
    if args.textura:
        try:
            geo = json.loads(GEOMETRIA.read_text(encoding="utf-8"))
            textura = textura_svg(geo)
            if len(gzip.compress(textura.encode("utf-8"), compresslevel=9, mtime=0)) > LIMITE_TEXTURA_GZIP:
                raise ValueError("textura excede 12 KiB gzip; revise DISTANCIA_TEXTURA")
            arquivos.append(("textura-bairros.svg", textura))
        except (OSError, ValueError, TypeError, KeyError) as e:
            print(f"textura não gravada: {e}", file=sys.stderr)
            return 1
    camadas = camadas_svg() if args.camadas else {}
    total_camadas = sum(tamanho_gzip(texto) for texto in camadas.values())
    if total_camadas > LIMITE_CAMADAS_GZIP:
        print(f"camadas não gravadas: {total_camadas} bytes gzip excedem 18 KiB", file=sys.stderr)
        return 1
    imagem = og_png() if args.og else None
    for nome, texto in arquivos:
        destino = SAIDA / nome
        gravar(destino, texto)
        print(f"{exibir(destino)}: {len(texto.encode('utf-8'))} bytes")
    for nome, texto in camadas.items():
        destino = SAIDA / "paisagem" / nome
        gravar(destino, texto)
        print(f"{exibir(destino)}: {len(texto.encode('utf-8'))} bytes, {tamanho_gzip(texto)} gzip")
    if camadas:
        print(f"camadas da paisagem: {total_camadas} bytes gzip no total (limite {LIMITE_CAMADAS_GZIP})")
    if imagem is not None:
        destino = SAIDA / "og-radar.png"
        gravar_binario(destino, imagem)
        print(f"{exibir(destino)}: {len(imagem)} bytes ({LARGURA_OG}×{ALTURA_OG})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
