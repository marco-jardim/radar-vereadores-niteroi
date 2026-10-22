"""Modelo de dados do site: projetos enriquecidos, pessoas, mandatos e métricas."""
from __future__ import annotations

import json
import re
import statistics
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from coletor.classificar import carregar_curadoria, carregar_proposicoes, classificacao_final

RAIZ = Path(__file__).resolve().parents[2]

DESFECHO_GRUPO = {
    "virou_lei": "lei",
    "aprovado_aguardando_sancao": "andamento",
    "em_tramitacao": "andamento",
    "apensado": "andamento",
    "arquivado": "sem_exito",
    "vetado": "sem_exito",
    "rejeitado": "sem_exito",
    "parecer_contrario": "sem_exito",
    "retirado": "sem_exito",
}
NOME_DESFECHO = {
    "virou_lei": "Virou lei",
    "aprovado_aguardando_sancao": "Aprovado, aguardando sanção",
    "em_tramitacao": "Em tramitação",
    "apensado": "Apensado a outro projeto",
    "arquivado": "Arquivado",
    "vetado": "Vetado",
    "rejeitado": "Rejeitado em plenário",
    "parecer_contrario": "Parecer contrário",
    "retirado": "Retirado pelo autor",
}
NOME_CATEGORIA = {
    "simbolica": "Simbólica",
    "politica_publica": "Política pública",
    "regulacao": "Regulação",
    "administrativa_fiscal": "Administrativa e fiscal",
    "outra": "Outra",
}
NOME_ALERTA = {
    "restricao_de_direitos": "Restrição de direitos",
    "pauta_de_costumes": "Pauta de costumes",
    "apelo_populista": "Apelo populista",
    "inconstitucionalidade_provavel": "Risco de inconstitucionalidade",
}
NOME_SINAL = {
    "parecer_contrario_ccj": "Parecer contrário da CCJ",
    "rejeitado_plenario": "Rejeitado em plenário",
    "veto_total": "Veto total",
    "veto_parcial": "Veto parcial",
    "veto_derrubado": "Veto derrubado pela Câmara",
    "inconstitucionalidade_declarada": "Declarada inconstitucional",
    "autorizativa": "Lei autorizativa",
    "repete_projeto": "Repete projeto anterior",
    "duplica_lei_vigente": "Duplica lei em vigor",
}
DESC_SINAL = {
    "parecer_contrario_ccj": "A Comissão de Constituição e Justiça deu parecer contrário.",
    "rejeitado_plenario": "O plenário votou contra o projeto.",
    "veto_total": "O prefeito vetou o projeto inteiro.",
    "veto_parcial": "O prefeito vetou parte do projeto.",
    "veto_derrubado": "A Câmara derrubou o veto do prefeito e a lei foi promulgada.",
    "inconstitucionalidade_declarada": "A Justiça declarou a lei inconstitucional (registrado por curadoria, com fonte).",
    "autorizativa": "A ementa só autoriza o Executivo a fazer algo, sem obrigá-lo. Como o Executivo já pode agir sem essa "
    "autorização, esse tipo de lei costuma não ter efeito prático.",
    "repete_projeto": "A ementa é quase idêntica à de um projeto apresentado antes (comparação automática de palavras).",
    "duplica_lei_vigente": "A própria tramitação registra que o projeto pode duplicar uma lei que já está em vigor.",
}
NOME_IMPACTO = {3: "Impacto alto", 2: "Impacto médio", 1: "Impacto baixo", 0: "Sem efeito prático", None: "Não avaliado"}
NOME_TEMA = {
    "saude": "Saúde", "educacao": "Educação", "seguranca": "Segurança", "mobilidade": "Mobilidade",
    "meio_ambiente": "Meio ambiente", "urbanismo": "Urbanismo", "cultura": "Cultura", "esporte": "Esporte",
    "assistencia_social": "Assistência social", "direitos_humanos": "Direitos humanos", "economia": "Economia",
    "consumidor": "Consumidor", "animais": "Animais", "administracao": "Administração", "tributos": "Tributos",
    "homenagem": "Homenagem", "outro": "Outro",
}
PARTICULAS = {"de", "da", "do", "das", "dos", "e"}
SUFIXOS = {"junior", "júnior", "filho", "neto", "sobrinho"}


def slug(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def nome_curto(nome: str) -> str:
    if " - " in nome:
        return nome.split(" - ")[-1].strip().title()
    partes = [p if p.lower() not in PARTICULAS else p.lower() for p in nome.title().split()]
    while len(partes) > 2 and partes[-1].lower() in SUFIXOS:
        partes.pop()
    if len(partes) <= 2:
        return " ".join(partes)
    if partes[-2] in PARTICULAS:
        return f"{partes[0]} {partes[-2]} {partes[-1]}"
    return f"{partes[0]} {partes[-1]}"


def legislatura_de(data_iso: str | None, ano: int, legislaturas: list[dict]) -> str | None:
    ref = data_iso or f"{ano}-07-01"
    for leg in legislaturas:
        if leg["inicio"] <= ref <= leg["fim"]:
            return leg["id"]
    return None


def e_vereador(autor: dict, nao_vereador: list[str]) -> bool:
    nome = autor["nome"].upper()
    if any(t in nome for t in nao_vereador):
        return False
    return (autor.get("origem") or "").lower() in ("", "vereador", "vereadora")


def e_executivo(autor: dict) -> bool:
    origem = (autor.get("origem") or "").lower()
    nome = autor["nome"].upper()
    return "execut" in origem or "prefeit" in origem or any(n in nome for n in ("RODRIGO NEVES", "AXEL GRAEL", "PREFEIT", "BAGUEIRA"))


def dias_entre(a: str | None, b: str | None) -> int | None:
    if not a or not b:
        return None
    try:
        d = (date.fromisoformat(b) - date.fromisoformat(a)).days
        return d if d >= 0 else None
    except ValueError:
        return None


def com_efeito(p: dict) -> bool:
    """Lei com efeito: impacto ≥ 2 pela IA, ou, sem avaliação, não simbólica nem autorizativa."""
    if p["desfecho"] != "virou_lei":
        return False
    if p["impacto"] is not None:
        return p["impacto"] >= 2
    return p["categoria"] != "simbolica" and "autorizativa" not in p["sinais"]


def sem_efeito(p: dict) -> bool:
    return p["categoria"] == "simbolica" or p["impacto"] == 0 or "autorizativa" in p["sinais"]


# ------------------------------------------------------------- projetos repetidos
STOP = set(
    "DISPOE SOBRE PARA COMO PELA PELO PELOS PELAS NO NA NOS NAS DO DA DOS DAS DE EM E O A OS AS UM UMA COM QUE "
    "MUNICIPIO NITEROI AMBITO OUTRAS PROVIDENCIAS DA OUTRAS INSTITUI CRIA FICA LEI MUNICIPAL ESTABELECE FORMA "
    "QUE MENCIONA EMENTA REDE PUBLICA PUBLICO".split()
)


def _tokens(ementa: str) -> frozenset[str]:
    t = unicodedata.normalize("NFKD", ementa.upper()).encode("ascii", "ignore").decode()
    return frozenset(w for w in re.findall(r"[A-Z0-9]{4,}", t) if w not in STOP)


def marcar_repetidos(projetos: list[dict], limiar: float = 0.8) -> None:
    """Marca projetos de vereadores cuja ementa quase repete a de um projeto anterior."""
    candidatos = [p for p in projetos if p["categoria"] != "simbolica" and p["principal"]]
    candidatos.sort(key=lambda p: (p["data"] or f"{p['ano']}-12-31", p["id"]))
    indice: dict[str, list[int]] = defaultdict(list)
    toks = []
    for i, p in enumerate(candidatos):
        t = _tokens(p["ementa"])
        toks.append(t)
        if len(t) >= 6:
            vistos = Counter(j for w in t for j in indice[w])
            for j, comuns in vistos.most_common(5):
                uniao = len(t | toks[j])
                if uniao and comuns / uniao >= limiar:
                    anterior = candidatos[j]
                    p["sinais"] = sorted(set(p["sinais"]) | {"repete_projeto"})
                    p["repete"] = {"numero": anterior["numero"], "url": anterior["url"], "mesmo_autor": anterior["principal"] == p["principal"]}
                    break
        for w in t:
            indice[w].append(i)


# ------------------------------------------------------------------------ modelo
def carregar_config() -> dict:
    return json.loads((RAIZ / "config" / "vereadores.json").read_text(encoding="utf-8"))


def metricas(autor: list[dict], coautor: list[dict]) -> dict:
    leis = [p for p in autor if p["desfecho"] == "virou_lei"]
    dias = [p["dias_ate_lei"] for p in leis if p["dias_ate_lei"] is not None]
    concluidos = [p for p in autor if DESFECHO_GRUPO.get(p["desfecho"]) in ("lei", "sem_exito")]
    return {
        "apresentados": len(autor),
        "coautorias": len(coautor),
        "leis": len(leis),
        "leis_efeito": sum(1 for p in leis if com_efeito(p)),
        "leis_alto": sum(1 for p in leis if p["impacto"] == 3),
        "leis_sem_efeito": sum(1 for p in leis if sem_efeito(p)),
        "leis_outras": sum(1 for p in leis if not com_efeito(p) and not sem_efeito(p)),
        "andamento": sum(1 for p in autor if DESFECHO_GRUPO.get(p["desfecho"]) == "andamento"),
        "sem_exito": sum(1 for p in autor if DESFECHO_GRUPO.get(p["desfecho"]) == "sem_exito"),
        "simbolicos": sum(1 for p in autor if p["categoria"] == "simbolica"),
        "autorizativos": sum(1 for p in autor if "autorizativa" in p["sinais"]),
        "repetidos": sum(1 for p in autor if "repete_projeto" in p["sinais"]),
        "polemicos": sum(1 for p in autor if p["polemico"]),
        "risco_juridico": sum(1 for p in autor if p["risco_juridico"]),
        "leis_coautoria": sum(1 for p in coautor if p["desfecho"] == "virou_lei"),
        "taxa_aprovacao": round(100 * len(leis) / len(concluidos)) if concluidos else None,
        "dias_mediana": int(statistics.median(dias)) if dias else None,
        "pct_sem_efeito": round(100 * sum(1 for p in leis if sem_efeito(p)) / len(leis)) if leis else None,
    }


def montar_modelo() -> dict:
    cfg = carregar_config()
    legs = cfg["legislaturas"]
    arq_ia = RAIZ / "data" / "classificacao_ia.json"
    cache_ia = json.loads(arq_ia.read_text(encoding="utf-8")) if arq_ia.exists() else {}
    curadoria = carregar_curadoria()
    arq_meta = RAIZ / "data" / "meta.json"
    meta = json.loads(arq_meta.read_text(encoding="utf-8")) if arq_meta.exists() else {}
    eleitos = {leg["id"]: {e["siscam"].upper(): e for e in leg["eleitos"]} for leg in legs}
    apelidos = {k.upper(): v for k, v in cfg.get("apelidos", {}).items() if not k.startswith("_")}
    afast = defaultdict(list)
    for a in cfg.get("afastamentos", []):
        afast[(a["siscam"].upper(), a["legislatura"])].append(a)

    projetos = []
    for p in carregar_proposicoes():
        correcao = (curadoria.get(p["numero"]) or {}).get("corrige")
        if correcao:
            p = {**p, **correcao}
        cls = classificacao_final(p, cache_ia, curadoria)
        leg = legislatura_de(p.get("data") or p.get("data_protocolo"), p["ano"], legs)
        autoria = p.get("autoria", [])
        autores_ver = [a for a in autoria if e_vereador(a, cfg["nao_vereador"])]
        principal = next((a for a in autores_ver if a.get("papel", "").lower().startswith("autor")), autores_ver[0] if autores_ver else None)
        if principal:
            origem = "vereador"
        elif autoria and e_executivo(autoria[0]):
            origem = "executivo"
        else:
            origem = "outra"
        lei = p.get("lei") or {}
        projetos.append({
            "id": p["id"], "numero": p["numero"], "ano": p["ano"], "data": p.get("data"),
            "ementa": p.get("ementa") or "", "situacao": p.get("situacao") or "",
            "desfecho": p["desfecho"], "lei": p.get("lei"), "url": p["url"], "legislatura": leg,
            "origem": origem,
            "autores": [{"nome": a["nome"], "papel": a.get("papel", ""), "slug": slug(a["nome"]), "vereador": e_vereador(a, cfg["nao_vereador"])} for a in autoria],
            "principal": slug(principal["nome"]) if principal else None,
            "dias_ate_lei": dias_entre(p.get("data_protocolo") or p.get("data"), lei.get("data")) if p["desfecho"] == "virou_lei" else None,
            "repete": None,
            **cls,
        })
    marcar_repetidos(projetos)

    pessoas: dict[str, dict] = {}
    for reg in projetos:
        if not reg["legislatura"]:
            continue
        for a in reg["autores"]:
            if not a["vereador"]:
                continue
            pessoa = pessoas.setdefault(a["slug"], {"slug": a["slug"], "nome_siscam": a["nome"], "mandatos": {}})
            m = pessoa["mandatos"].setdefault(reg["legislatura"], {"projetos_autor": [], "projetos_coautor": []})
            (m["projetos_autor"] if a["slug"] == reg["principal"] else m["projetos_coautor"]).append(reg)

    for leg in legs:  # eleitos sem nenhum projeto ainda aparecem com zero
        for e in leg["eleitos"]:
            pessoa = pessoas.setdefault(slug(e["siscam"]), {"slug": slug(e["siscam"]), "nome_siscam": e["siscam"], "mandatos": {}})
            pessoa["mandatos"].setdefault(leg["id"], {"projetos_autor": [], "projetos_coautor": []})

    for pessoa in pessoas.values():
        nome_up = pessoa["nome_siscam"].upper()
        pessoa["nome"] = None
        for leg_id, m in pessoa["mandatos"].items():
            info = eleitos.get(leg_id, {}).get(nome_up)
            m["eleito"] = bool(info)
            m["partido"] = info["partido"] if info else ""
            m["afastamentos"] = afast.get((nome_up, leg_id), [])
            m["metricas"] = metricas(m["projetos_autor"], m["projetos_coautor"])
            if info:
                pessoa["nome"] = info["nome"]
        pessoa["nome"] = pessoa["nome"] or apelidos.get(nome_up) or nome_curto(pessoa["nome_siscam"])

    nomes = {s: p["nome"] for s, p in pessoas.items()}
    partido_de = {}
    for s, p in pessoas.items():
        for leg_id, m in p["mandatos"].items():
            partido_de[(s, leg_id)] = m["partido"]
    for reg in projetos:
        for a in reg["autores"]:
            a["exibicao"] = nomes.get(a["slug"]) or nome_curto(a["nome"])
        reg["partido"] = partido_de.get((reg["principal"], reg["legislatura"]), "")

    return {"legislaturas": legs, "pessoas": pessoas, "projetos": projetos, "meta": meta, "curadoria": curadoria, "cfg": cfg}


def mediana_legislatura(modelo: dict, leg_id: str, chave: str) -> float | None:
    vals = [p["mandatos"][leg_id]["metricas"][chave] for p in modelo["pessoas"].values()
            if leg_id in p["mandatos"] and p["mandatos"][leg_id]["eleito"] and p["mandatos"][leg_id]["metricas"][chave] is not None]
    return statistics.median(vals) if vals else None
