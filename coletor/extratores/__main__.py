"""Medição dos extratores num diretório de arquivos (por exemplo, o cache do SISCAM).

Uso: python -m coletor.extratores DIR [--ocr] [--limite N] [--lista]

Imprime, por formato, a contagem de cada status, a taxa de `ok` e quantos textos
ainda têm caracteres de controle (exceto \\n e \\t). Com `--lista`, também imprime
uma linha por arquivo (nome, formato, status, detalhe). Não grava nada; o
conteúdo dos arquivos não é impresso.
"""
from __future__ import annotations

import argparse
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from . import extrair, ferramentas_disponiveis


def _tem_controle(texto: str) -> bool:
    return any(unicodedata.category(c) in ("Cc", "Cf") and c not in "\n\t" for c in texto)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("diretorio", type=Path)
    parser.add_argument("--ocr", action="store_true", help="aplica OCR às páginas escaneadas")
    parser.add_argument("--limite", type=int, default=0, help="número máximo de arquivos")
    parser.add_argument("--lista", action="store_true", help="uma linha por arquivo")
    args = parser.parse_args(argv)

    print(f"ferramentas: {ferramentas_disponiveis()}")
    arquivos = sorted(p for p in args.diretorio.rglob("*") if p.is_file())
    if args.limite > 0:
        arquivos = arquivos[: args.limite]
    por_formato: dict[str, Counter] = defaultdict(Counter)
    controles: Counter = Counter()
    lento = (0.0, "")
    for caminho in arquivos:
        inicio = time.perf_counter()
        r = extrair(caminho.read_bytes(), ocr=args.ocr)
        duracao = time.perf_counter() - inicio
        if duracao > lento[0]:
            lento = (duracao, caminho.name)
        por_formato[r.formato][r.status] += 1
        if _tem_controle(r.texto):
            controles[r.formato] += 1
        if args.lista:
            print(f"{caminho.name}\t{r.formato}\t{r.status}\t{r.detalhe}")
    for formato in sorted(por_formato):
        contagem = por_formato[formato]
        total = sum(contagem.values())
        ok = contagem["ok"] + contagem["ok_ocr"]
        print(f"{formato}: {total} arquivos, ok {ok / total:.1%}, {dict(sorted(contagem.items()))}, "
              f"com controles: {controles[formato]}")
    print(f"mais lento: {lento[1]} ({lento[0]:.2f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
