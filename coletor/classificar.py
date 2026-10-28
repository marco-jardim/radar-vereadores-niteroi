"""Classificação híbrida dos projetos de lei.

Três camadas, nesta ordem de precedência:
  1. Curadoria  (config/curadoria.json) — rótulos atribuídos à mão, sempre com fonte.
  2. Regras     — sinais objetivos extraídos da tramitação (veto, rejeição, parecer
                  contrário) e padrões de ementa para projetos simbólicos.
  3. IA         — modelo via OpenCode Go classifica a ementa numa taxonomia fixa,
                  com justificativa curta e grau de confiança. Resultado em cache.

A IA só roda se OPENCODE_API_KEY estiver definida. Sem ela, valem regras + curadoria.
Uso: python -m coletor.classificar [--sem-ia] [--limite N]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from coletor.arquivos import salvar_json, salvar_mapa
from coletor import ia

RAIZ = Path(__file__).resolve().parent.parent
DIR_DADOS = RAIZ / "data" / "proposicoes"
CACHE_IA = RAIZ / "data" / "classificacao_ia.json"
CURADORIA = RAIZ / "config" / "curadoria.json"

BASE_URL = os.environ.get("OPENCODE_BASE_URL", "https://opencode.ai/zen/go/v1")
MODELO = os.environ.get("OPENCODE_MODEL", "deepseek-v4.1-flash")
USER_AGENT = "radar-vereadores-niteroi/1.0 (+https://github.com/marco-jardim/radar-vereadores-niteroi)"
VERSAO_PROMPT = "2026-10-v2"
LOTE = int(os.environ.get("CLASSIFICADOR_LOTE", 15))

CATEGORIAS = {
    "simbolica": "Homenagem, nome de rua/logradouro/prédio público, data ou semana comemorativa, título, "
    "declaração de patrimônio cultural imaterial, utilidade pública, tombamento de bem específico.",
    "politica_publica": "Cria ou altera programa, política, serviço público, direito ou benefício para a população.",
    "regulacao": "Regras para atividades, comércio, consumo, posturas, trânsito, obras, uso do espaço urbano.",
    "administrativa_fiscal": "Estrutura administrativa, servidores, orçamento, créditos, tributos, fundos, contratos.",
    "outra": "Nenhuma das anteriores.",
}
ALERTAS = {
    "restricao_de_direitos": "Restringe direitos, acesso a espaços/serviços ou expressão de um grupo "
    "(ex.: pessoas LGBTQIA+, população em situação de rua, minorias religiosas, mulheres, artistas de periferia).",
    "pauta_de_costumes": "Tema de disputa moral/cultural (gênero, sexualidade, drogas, religião, 'ideologia') "
    "cujo efeito principal é simbólico ou de posicionamento, não de gestão.",
    "apelo_populista": "Medida de forte apelo imediato sem indicação de custo, fonte de recurso ou viabilidade, "
    "reação a caso midiático, ou que mira pessoa/grupo específico pelo nome.",
    "inconstitucionalidade_provavel": "Provável vício: invade competência da União/Estado, legisla sobre relações "
    "privadas fora da competência municipal, ou cria despesa/atribuição ao Executivo por iniciativa parlamentar.",
}
ALERTAS_POLEMICOS = {"restricao_de_direitos", "pauta_de_costumes", "apelo_populista"}
CONFIANCA_MINIMA = float(os.environ.get("CLASSIFICADOR_CONFIANCA_MINIMA", 0.75))

# ------------------------------------------------------------------------ regras
RE_SIMBOLICA = re.compile(
    r"\bD[ÁA] (O )?NOME\b|PASSA A (SE )?DENOMINAR|ALTERA[ÇC][ÃA]O DA DENOMINA[ÇC][ÃA]O|ALTERA A DENOMINA[ÇC][ÃA]O|DENOMINA[- ]SE\b|\bDENOMINA (A|O|DE|DO|DA|AS|OS)\b|"
    r"CALEND[ÁA]RIO OFICIAL|\bDIA MUNICIPAL\b|SEMANA MUNICIPAL|M[ÊE]S MUNICIPAL|UTILIDADE P[ÚU]BLICA|"
    r"PATRIM[ÔO]NIO CULTURAL (DE NATUREZA )?IMATERIAL|T[ÍI]TULO DE CIDAD|INSTITUI O DIA\b|INCLUI NO CALEND|HOMENAGEM|"
    r"LEI\s+(MUNICIPAL\s+)?(DE\s+)?(N[º°O.]*\s*)?3\.?474",  # Lei 3.474/2020 é o calendário oficial de datas
    re.I,
)
# "Autoriza o Poder Executivo a..." não obriga nada: o Executivo já pode agir sem a lei
RE_AUTORIZATIVA = re.compile(r"^\s*(EMENTA:\s*)?(FICA\s+)?AUTORIZ(A|ADO)\s+(O\s+)?(PODER\s+)?EXECUTIVO", re.I)


def sinais_tramitacao(p: dict) -> list[str]:
    sinais = []
    for t in p.get("tramitacoes", []):
        dest = (t.get("destinatario") or "") + " " + (t.get("remetente") or "")
        res = (t.get("resultado") or "") + " " + (t.get("observacao") or "")
        if re.search(r"Constitui[çc][ãa]o e Justi[çc]a", dest, re.I) and re.search(r"\bContr[áa]ri", res, re.I):
            sinais.append("parecer_contrario_ccj")
        if re.search(r"rejeitad[oa] em", res, re.I) and not re.search(r"veto", res, re.I):
            sinais.append("rejeitado_plenario")
        if re.search(r"veto total", res, re.I):
            sinais.append("veto_total")
        if re.search(r"DUPLICIDADE|J[ÁA] EXISTE (UMA )?LEI|LEI .{0,40}EM VIGOR", res + " " + (t.get("complemento") or ""), re.I):
            sinais.append("duplica_lei_vigente")
    s = (p.get("situacao") or "").upper()
    if s in {"VETO TOTAL", "VETO MANTIDO"}:
        sinais.append("veto_total")
    if s == "PARECER CONTRÁRIO":
        sinais.append("parecer_contrario_ccj")
    if s in {"REJEITADO", "REJEITADA"}:
        sinais.append("rejeitado_plenario")
    lei = p.get("lei") or {}
    if lei.get("tipo") == "veto_derrubado":
        sinais.append("veto_derrubado")
    if lei.get("veto_parcial"):
        sinais.append("veto_parcial")
    return sorted(set(sinais))


def categoria_por_regra(p: dict) -> str | None:
    return "simbolica" if RE_SIMBOLICA.search(p.get("ementa") or "") else None


def e_autorizativa(p: dict) -> bool:
    return bool(RE_AUTORIZATIVA.search(p.get("ementa") or ""))


# --------------------------------------------------------------------------- IA
PROMPT_SISTEMA = f"""Você classifica projetos de lei municipais da Câmara de Niterói (RJ) para um site de transparência
apartidário. Avalie apenas o texto da ementa. Seja conservador: só marque um alerta se a ementa der base clara para ele.
Aplique os mesmos critérios a qualquer autor, partido ou espectro político.

CATEGORIA (escolha exatamente uma):
{json.dumps(CATEGORIAS, ensure_ascii=False, indent=1)}

ALERTAS (zero ou mais; a maioria dos projetos não tem nenhum):
{json.dumps(ALERTAS, ensure_ascii=False, indent=1)}

IMPACTO (0 a 3), o efeito concreto esperado sobre a vida das pessoas ou sobre a gestão da cidade:
 0 = nenhum efeito prático (homenagem, data, nome, título, utilidade pública, lei meramente autorizativa ou que repete norma existente);
 1 = baixo (efeito pontual, restrito a um local, grupo pequeno ou procedimento menor);
 2 = médio (muda regra ou serviço para um grupo relevante ou para um setor da cidade);
 3 = alto (afeta grande parte da população, cria política ou serviço amplo, ou mexe em orçamento/tributo relevante).
Avalie o efeito pelo que a ementa determina, não pelo tema ser importante.

RESUMO: até 140 caracteres, linguagem simples, começando por um verbo no presente ("Obriga...", "Cria...", "Proíbe...").
PUBLICO: quem é diretamente afetado, em até 4 palavras (ex.: "pessoas com deficiência", "comércio do Centro", "toda a cidade").

TEMA: uma palavra entre saude, educacao, seguranca, mobilidade, meio_ambiente, urbanismo, cultura, esporte,
assistencia_social, direitos_humanos, economia, consumidor, animais, administracao, tributos, homenagem, outro.

Responda SOMENTE com JSON no formato:
{{"itens":[{{"id":<id>,"categoria":"...","tema":"...","impacto":0-3,"resumo":"...","publico":"...",
"alertas":[{{"rotulo":"...","confianca":0.0-1.0}}],
"justificativa":"até 200 caracteres, em português, citando o trecho da ementa que motivou os alertas (ou 'sem alertas')"}}]}}"""


def _hash(texto: str) -> str:
    return hashlib.sha1(f"{VERSAO_PROMPT}|{MODELO}|{texto}".encode()).hexdigest()[:16]


def chamar_ia(itens: list[dict], chave: str, sessao: str) -> dict[int, dict]:
    conteudo = "\n".join(f'{{"id":{p["id"]},"ementa":{json.dumps(p.get("ementa") or "", ensure_ascii=False)}}}' for p in itens)
    corpo = {
        "model": MODELO,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": PROMPT_SISTEMA},
            {"role": "user", "content": "Classifique os projetos abaixo (um JSON por linha):\n" + conteudo},
        ],
    }
    def decodificar(texto: str) -> dict[int, dict]:
        dados = ia.decodificar_json(texto)
        return {int(i["id"]): i for i in dados.get("itens", []) if "id" in i}

    return ia.chamar(corpo, chave, sessao, base_url=BASE_URL, decodificar=decodificar,
                     user_agent=USER_AGENT, transporte=urllib.request.urlopen, esperar=time.sleep)


def normalizar_ia(bruto: dict) -> dict:
    cat = bruto.get("categoria") if bruto.get("categoria") in CATEGORIAS else "outra"
    alertas = []
    for a in bruto.get("alertas") or []:
        if isinstance(a, str):
            a = {"rotulo": a, "confianca": 0.5}
        if a.get("rotulo") in ALERTAS:
            alertas.append({"rotulo": a["rotulo"], "confianca": round(float(a.get("confianca") or 0), 2)})
    try:
        impacto = max(0, min(3, int(bruto.get("impacto"))))
    except (TypeError, ValueError):
        impacto = None
    return {
        "categoria": cat,
        "impacto": impacto,
        "resumo": str(bruto.get("resumo") or "")[:180],
        "publico": str(bruto.get("publico") or "")[:60],
        "tema": str(bruto.get("tema") or "outro")[:30],
        "alertas": alertas,
        "justificativa": str(bruto.get("justificativa") or "")[:240],
    }


# ---------------------------------------------------------------------- execução
def carregar_proposicoes() -> list[dict]:
    todos = []
    for arq in sorted(DIR_DADOS.glob("*.json")):
        todos.extend(json.loads(arq.read_text(encoding="utf-8")))
    return todos


def classificar(usar_ia: bool, limite: int | None) -> dict:
    proposicoes = carregar_proposicoes()
    cache = json.loads(CACHE_IA.read_text(encoding="utf-8")) if CACHE_IA.exists() else {}
    chave = os.environ.get("OPENCODE_API_KEY", "").strip()
    estat = {"total": len(proposicoes), "ia_novos": 0, "ia_cache": 0, "ia_desligada": not (usar_ia and chave)}

    if usar_ia and chave:
        pendentes = [p for p in proposicoes if p.get("ementa") and cache.get(str(p["id"]), {}).get("hash") != _hash(p["ementa"])]
        estat["ia_cache"] = len(proposicoes) - len(pendentes)
        if limite:
            pendentes = pendentes[:limite]
        sessao = f"radar-vereadores-{os.environ.get('GITHUB_RUN_ID') or uuid.uuid4().hex[:12]}"
        print(f"IA: {len(pendentes)} projetos para classificar com {MODELO}", flush=True)
        for i in range(0, len(pendentes), LOTE):
            lote = pendentes[i: i + LOTE]
            try:
                respostas = chamar_ia(lote, chave, sessao)
            except PermissionError as e:  # chave inválida: segue só com regras e curadoria
                print(f"::warning::{e}", file=sys.stderr)
                estat["ia_erro"] = str(e)
                break
            for p in lote:
                if p["id"] in respostas:
                    cache[str(p["id"])] = {
                        **normalizar_ia(respostas[p["id"]]),
                        "hash": _hash(p["ementa"]),
                        "modelo": MODELO,
                        "versao_prompt": VERSAO_PROMPT,
                    }
                    estat["ia_novos"] += 1
            if (i // LOTE) % 10 == 9:
                salvar_mapa(CACHE_IA, cache)
                print(f"  {min(i + LOTE, len(pendentes))}/{len(pendentes)}", flush=True)
        salvar_mapa(CACHE_IA, cache)  # um projeto por linha: diffs por registro
    elif usar_ia:
        print("OPENCODE_API_KEY não definida: classificação só por regras e curadoria.", file=sys.stderr)
    return estat


def classificacao_final(p: dict, cache_ia: dict, curadoria: dict) -> dict:
    """Combina as três camadas. Usada pelo gerador do site."""
    ia = cache_ia.get(str(p["id"]))
    cur = curadoria.get(p["numero"])
    categoria = (cur or {}).get("categoria") or categoria_por_regra(p) or (ia or {}).get("categoria") or "outra"
    alertas = []
    if cur:
        for r in cur.get("alertas", []):
            alertas.append({"rotulo": r, "origem": "curadoria", "fontes": cur.get("fontes", []), "nota": cur.get("nota", "")})
    if ia and not (cur and cur.get("substitui_ia")):
        ja = {a["rotulo"] for a in alertas}
        for a in ia.get("alertas", []):
            if a["rotulo"] not in ja and a["confianca"] >= CONFIANCA_MINIMA:
                alertas.append({"rotulo": a["rotulo"], "origem": "ia", "confianca": a["confianca"], "nota": ia.get("justificativa", "")})
    autorizativa = e_autorizativa(p)
    impacto = (cur or {}).get("impacto")
    if impacto is None:
        impacto = (ia or {}).get("impacto")
    if categoria == "simbolica":
        impacto = 0
    elif autorizativa and impacto is not None:
        impacto = min(impacto, 1)
    sinais = sinais_tramitacao(p) + (cur or {}).get("sinais", []) + (["autorizativa"] if autorizativa else [])
    return {
        "categoria": categoria,
        "impacto": impacto,
        "resumo": (cur or {}).get("resumo") or (ia or {}).get("resumo") or "",
        "publico": (ia or {}).get("publico") or "",
        "tema": (ia or {}).get("tema") or ("homenagem" if categoria == "simbolica" else "outro"),
        "sinais": sinais,
        "alertas": alertas,
        "polemico": any(a["rotulo"] in ALERTAS_POLEMICOS for a in alertas),
        "risco_juridico": any(a["rotulo"] == "inconstitucionalidade_provavel" for a in alertas)
        or "inconstitucionalidade_declarada" in (cur or {}).get("sinais", []),
    }


def carregar_curadoria() -> dict:
    if not CURADORIA.exists():
        return {}
    dados = json.loads(CURADORIA.read_text(encoding="utf-8"))
    return {e["projeto"]: e for e in dados.get("entradas", [])}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sem-ia", action="store_true")
    ap.add_argument("--limite", type=int, default=None, help="classifica no máximo N projetos novos")
    args = ap.parse_args()
    estat = classificar(not args.sem_ia, args.limite)
    meta = RAIZ / "data" / "meta.json"
    dados = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
    dados["classificacao"] = {**estat, "modelo": MODELO, "versao_prompt": VERSAO_PROMPT}
    salvar_json(meta, dados)
    print(json.dumps(estat, ensure_ascii=False))


if __name__ == "__main__":
    main()
