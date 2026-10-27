"""Gera a identidade visual do Radar a partir de uma única geometria, sem rede nem relógio.

A marca é um sol poente sobre três ondas que lembram as barras do placar: meio disco
cortado pelo horizonte e três traços ondulados de comprimento decrescente, alinhados à
esquerda como barras de um gráfico. A mesma geometria produz o favicon (SVG autônomo,
com cores próprias para os temas claro e escuro) e a marca do cabeçalho (sprite
`<symbol id="marca">` sem cores fixas: o sol herda `fill` e as ondas `currentColor` da
página, pelos tokens de estilo.css).

Uso: python -m coletor.paisagem [--marca] [--textura] (ao menos uma opção)
Grava favicon.svg e marca.svg em site_src/. --textura gera textura-bairros.svg
a partir da geometria local dos bairros. Mesma geometria, mesmos bytes.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from collections import defaultdict
from html import escape
from pathlib import Path

from coletor.arquivos import gravar_atomico

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


# ---- cli
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--marca", action="store_true", help="grava favicon.svg e marca.svg em site_src/")
    ap.add_argument("--textura", action="store_true", help="grava textura-bairros.svg usando data/geo/bairros.json")
    args = ap.parse_args(argv)
    if not (args.marca or args.textura):
        ap.print_usage(sys.stderr)
        print("nada a fazer: informe --marca ou --textura", file=sys.stderr)
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
    for nome, texto in arquivos:
        destino = SAIDA / nome
        gravar(destino, texto)
        print(f"{exibir(destino)}: {len(texto.encode('utf-8'))} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
