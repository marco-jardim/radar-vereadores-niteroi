"""Gera o site estático em ./site a partir de data/ e config/.

Uso: python -m coletor.gerar_site
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from coletor.site import paginas as P
from coletor.site.modelo import (
    DESFECHO_GRUPO, NOME_ALERTA, NOME_DESFECHO, NOME_SINAL, NOME_TEMA, com_efeito, montar_modelo, sem_efeito,
)

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "site"
FONTE_ESTATICA = RAIZ / "site_src"


def dados_cliente(modelo: dict) -> dict:
    """JSON compacto lido pelo app.js nas páginas de leis e projetos."""
    pessoas = {s: p["nome"] for s, p in modelo["pessoas"].items()}
    projetos = []
    for p in sorted(modelo["projetos"], key=lambda p: p["data"] or "", reverse=True):
        lei = p.get("lei") or {}
        projetos.append({
            "n": p["numero"], "a": p["ano"], "d": p["data"], "e": p["ementa"], "u": p["url"],
            "r": p["resumo"], "pb": p["publico"], "t": p["tema"],
            "g": DESFECHO_GRUPO.get(p["desfecho"], "andamento"), "dx": NOME_DESFECHO.get(p["desfecho"], p["desfecho"]),
            "c": p["categoria"], "i": p["impacto"], "ef": int(com_efeito(p)), "se": int(sem_efeito(p)),
            "l": lei.get("numero"), "ld": lei.get("data"), "dl": p["dias_ate_lei"],
            "o": p["origem"], "lg": p["legislatura"], "pt": p["partido"], "pr": p["principal"],
            "au": [[a["exibicao"], a["slug"] if a["vereador"] else ""] for a in p["autores"]],
            "al": [[NOME_ALERTA.get(a["rotulo"], a["rotulo"]), a["origem"], a.get("nota", "")] for a in p["alertas"]],
            "pol": int(p["polemico"]),
            "s": [s for s in p["sinais"]],
            "rp": p["repete"]["numero"] if p.get("repete") else None,
        })
    return {
        "projetos": projetos,
        "pessoas": pessoas,
        "temas": NOME_TEMA,
        "sinais": NOME_SINAL,
        "legislaturas": [l["id"] for l in modelo["legislaturas"]],
    }


def main() -> None:
    modelo = montar_modelo()
    if SAIDA.exists():
        shutil.rmtree(SAIDA)
    (SAIDA / "vereadores").mkdir(parents=True)
    (SAIDA / "dados").mkdir()
    for arq in FONTE_ESTATICA.iterdir():
        shutil.copy(arq, SAIDA / arq.name)
    escrever = lambda nome, conteudo: (SAIDA / nome).write_text(conteudo, encoding="utf-8")
    escrever("index.html", P.gerar_index(modelo))
    escrever("leis.html", P.gerar_leis())
    escrever("projetos.html", P.gerar_projetos())
    escrever("ruido.html", P.gerar_ruido(modelo))
    escrever("analises.html", P.gerar_analises(modelo))
    escrever("metodologia.html", P.gerar_metodologia(modelo))
    escrever("alertas.html", P.redirecionar("ruido.html"))
    for pessoa in modelo["pessoas"].values():
        escrever(f"vereadores/{pessoa['slug']}.html", P.gerar_vereador(modelo, pessoa))
    escrever("dados/projetos.json", json.dumps(dados_cliente(modelo), ensure_ascii=False, separators=(",", ":")))
    resumo = {
        leg["id"]: {
            p["nome"]: {"partido": p["mandatos"][leg["id"]]["partido"], "eleito": p["mandatos"][leg["id"]]["eleito"], **p["mandatos"][leg["id"]]["metricas"]}
            for p in modelo["pessoas"].values() if leg["id"] in p["mandatos"]
        }
        for leg in modelo["legislaturas"]
    }
    escrever("dados/vereadores.json", json.dumps(resumo, ensure_ascii=False, indent=1))
    escrever(".nojekyll", "")
    print(f"site gerado: {len(modelo['pessoas'])} vereadores, {len(modelo['projetos'])} projetos")


if __name__ == "__main__":
    main()
