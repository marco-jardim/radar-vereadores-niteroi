"""Gera a identidade visual do Radar a partir de uma única geometria, sem rede nem relógio.

A marca é um sol poente sobre três ondas que lembram as barras do placar: meio disco
cortado pelo horizonte e três traços ondulados de comprimento decrescente, alinhados à
esquerda como barras de um gráfico. A mesma geometria produz o favicon (SVG autônomo,
com cores próprias para os temas claro e escuro) e a marca do cabeçalho (sprite
`<symbol id="marca">` cujas ondas herdam `currentColor` da página).

Uso: python -m coletor.paisagem --marca
Grava site_src/favicon.svg e site_src/marca.svg. Mesma geometria, mesmos bytes.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from coletor.arquivos import gravar_atomico

RAIZ = Path(__file__).resolve().parents[1]
SAIDA = RAIZ / "site_src"
SVG_NS = "http://www.w3.org/2000/svg"
TITULO = "Radar dos Vereadores de Niterói"

# Paleta do site (literais de estilo.css); só estas cores entram nos SVGs.
DOURADO = "#F2B544"  # --dourado
POR_DO_SOL = "#E8743B"  # --por-do-sol-area
BAIA = "#13476B"  # --baia, tema claro
BAIA_CLARA = "#9CC6E4"  # ondas no tema escuro


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

    Sem fundo próprio: no claro, sol #E8743B e ondas #13476B contra a aba branca; no
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
    """Sprite do cabeçalho: `<use href="marca.svg?v=…#marca">` herda a cor das ondas."""
    return (f'<svg xmlns="{SVG_NS}" viewBox="{_viewbox()}">'
            f'<symbol id="marca" viewBox="{_viewbox()}">'
            f'<path fill="{DOURADO}" d="{caminho_sol()}"/>'
            f'<path fill="none" stroke="currentColor" stroke-width="{numero(ESPESSURA_ONDA)}" '
            f'stroke-linecap="round" d="{caminho_ondas()}"/>'
            "</symbol></svg>\n")


def gravar(caminho: Path, texto: str) -> None:
    """Gravação atômica (temporário na mesma pasta + os.replace), UTF-8 e LF."""
    gravar_atomico(caminho, texto)


# ---- cli
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--marca", action="store_true", help="grava site_src/favicon.svg e site_src/marca.svg")
    args = ap.parse_args(argv)
    if not args.marca:
        ap.print_usage(sys.stderr)
        print("nada a fazer: informe --marca", file=sys.stderr)
        return 2
    for nome, texto in (("favicon.svg", favicon_svg()), ("marca.svg", marca_svg())):
        destino = SAIDA / nome
        gravar(destino, texto)
        print(f"site_src/{nome}: {len(texto.encode('utf-8'))} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
