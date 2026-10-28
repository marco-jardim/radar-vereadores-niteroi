"""CLI: python -m coletor.nuvem --ambiente local|staging|production [opções].

Exemplos:
  python -m coletor.nuvem --ambiente local --sqlite D:\\radar-niteroi-cache\\local.sqlite --simular
  python -m coletor.nuvem --ambiente staging
  python -m coletor.nuvem --ambiente production --exportar D:\\radar-niteroi-cache\\exportacoes
  python -m coletor.nuvem --ambiente production --reconstruir
  python -m coletor.nuvem --ambiente staging --etapas r2
  python -m coletor.nuvem --ambiente staging --etapas d1,vetores --sem-r2

Código de saída: 0 sem falhas; 1 com falhas (barreira de PII, Git inconsistente,
chamada à nuvem ou originais ausentes no cache); 2 em uso inválido.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from coletor import mascara
from coletor.nuvem.ambientes import AMBIENTES, ambiente_local, ambiente_remoto
from coletor.nuvem.fonte import ErroFonte
from coletor.nuvem.rede import ErroNuvem
from coletor.nuvem.sincronizar import ETAPAS, ETAPAS_PADRAO, ErroBarreira, etapas_validas, sincronizar

RAIZ = Path(__file__).resolve().parents[2]


def cache_padrao() -> Path:
    if os.environ.get("RADAR_CACHE"):
        return Path(os.environ["RADAR_CACHE"])
    return Path(r"D:\radar-niteroi-cache") if os.name == "nt" else Path.home() / ".cache" / "radar-niteroi"


def textos_padrao() -> Path:
    if os.environ.get("RADAR_TEXTOS"):
        return Path(os.environ["RADAR_TEXTOS"])
    return RAIZ.parent / "radar-vereadores-niteroi-textos"


def commit_atual(raiz: Path) -> str | None:
    """Commit dos manifestos: GITHUB_SHA no Actions; senão, `git rev-parse HEAD` (sem shell)."""
    if os.environ.get("GITHUB_SHA"):
        return os.environ["GITHUB_SHA"]
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(raiz), capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    saida = r.stdout.strip()
    return saida if r.returncode == 0 and saida else None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m coletor.nuvem",
                                description="Sincroniza D1, Vectorize e R2 com o Git (contrato de textos).")
    p.add_argument("--ambiente", required=True, choices=AMBIENTES)
    p.add_argument("--sqlite", type=Path, help="banco SQLite do ambiente local (padrão: <cache>/local.sqlite)")
    p.add_argument("--simular", action="store_true", help="mostra o plano, sem gravar nada")
    p.add_argument("--exportar", type=Path, metavar="DIR",
                   help="grava dump, vetores e SHA256SUMS em DIR/<versao>/ e envia ao bucket de exportações")
    p.add_argument("--reconstruir", action="store_true", help="recria D1 e Vectorize a partir do Git")
    p.add_argument("--textos", type=Path, help="worktree da branch dados-textos (padrão: RADAR_TEXTOS ou "
                                               "../radar-vereadores-niteroi-textos)")
    p.add_argument("--raiz", type=Path, default=RAIZ, help=argparse.SUPPRESS)
    p.add_argument("--cache", type=Path, help="cache local (padrão: RADAR_CACHE)")
    p.add_argument("--commit", help="commit dos manifestos (padrão: GITHUB_SHA ou git rev-parse HEAD)")
    p.add_argument("--etapas", default=",".join(ETAPAS_PADRAO), metavar="LISTA",
                   help=f"etapas separadas por vírgula, entre {','.join(ETAPAS)} (padrão: {','.join(ETAPAS_PADRAO)}; "
                        "--exportar acrescenta exportar). estado_indice só é gravado com r2, d1 e vetores")
    p.add_argument("--sem-r2", action="store_true",
                   help="não usa o R2: pula a etapa r2 e o envio da exportação (sem gravar estado_indice)")
    args = p.parse_args(argv)

    try:
        etapas = etapas_validas(args.etapas)
    except ValueError as e:
        p.error(str(e))
    cache = args.cache or cache_padrao()
    if args.ambiente != "local" and args.sqlite:
        p.error("--sqlite só vale para --ambiente local")
    try:
        if args.ambiente == "local":
            ambiente = ambiente_local(args.sqlite or cache / "local.sqlite", somente_leitura=args.simular)
            if args.sem_r2:
                ambiente.r2 = None
        else:
            ambiente = ambiente_remoto(args.ambiente, cache, sem_r2=args.sem_r2)
    except (ErroNuvem, OSError, KeyError, ValueError) as e:
        print(f"erro: {e}", file=sys.stderr)
        return 1
    try:
        rel = sincronizar(args.raiz, args.textos or textos_padrao(), ambiente, liberados=mascara.liberados(args.raiz),
                          cache=cache, simular=args.simular, reconstruir=args.reconstruir, exportar=args.exportar,
                          commit=args.commit or commit_atual(args.raiz), etapas=etapas,
                          progresso=lambda texto: print(texto, file=sys.stderr, flush=True))
    except ErroBarreira as e:
        print(str(e), file=sys.stderr)
        return 1
    except (ErroFonte, ErroNuvem) as e:
        print(f"erro: {e}", file=sys.stderr)
        print("estado_indice não foi gravado.", file=sys.stderr)
        return 1
    finally:
        ambiente.banco.fechar()
    print(rel.texto())
    for falha in rel.falhas:
        print(f"::warning::{falha}" if os.environ.get("GITHUB_ACTIONS") else f"falha: {falha}", file=sys.stderr)
    return 1 if rel.falhas else 0


if __name__ == "__main__":
    sys.exit(main())
