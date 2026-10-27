"""Agregados das sessões para o site; as decisões pertencem a regras_sessoes.

Não lê a rede, não grava arquivos nem cria páginas para suplentes das sessões.
Os registros brutos de PLs preservam a tramitação que o modelo geral não exporta.
"""
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from coletor import regras_sessoes as R
from coletor.site.modelo import URL_DETALHE, indice_pessoas, legislatura_de, slug
from coletor.sessoes import DETALHE_SESSAO


RAIZ = Path(__file__).resolve().parents[2]
CAMPOS_PRESENCA = ("P", "C", "V", "J", "A", "L", "O")
CAMPOS_TOTAIS = ("favor", "contra", "abstencao", "ausentes", "branco", "nulo")
CAMPOS_PLACAR = ("unanime", "dissenso", "dividida", "inconsistente", "indeterminado")


# ---- leitura e ordenação -------------------------------------------------------
def _ler_lista(arquivo: Path) -> list[dict]:
    registros = json.loads(arquivo.read_text(encoding="utf-8"))
    if not isinstance(registros, list):
        raise ValueError(f"{arquivo}: esperada uma lista de registros")
    return registros


def _chave_sessao(sessao: dict) -> tuple:
    return sessao.get("data") or "", sessao.get("hora") or "", sessao.get("numero") or 0, sessao["id"]


def _chave_votacao(votacao: dict) -> tuple:
    # A ordem das linhas nominais não muda a identidade nem os sufixos de uma
    # segunda votação do mesmo documento na sessão. Não se modifica a entrada.
    canonica = {**votacao, "votos": sorted(votacao.get("votos") or [],
                                         key=lambda v: json.dumps(v, sort_keys=True, ensure_ascii=False))}
    return (votacao.get("id_documento") is None, votacao.get("id_documento") or 0,
            json.dumps(canonica, sort_keys=True, ensure_ascii=False))


def _documentos(modelo: dict, proposicoes: dict | None, raiz: Path, ids: set[int]) -> dict[int, dict]:
    """Enunciados do modelo prevalecem; tramitações vêm da fonte bruta por id.

    Um mapa explícito (inclusive vazio) substitui a leitura dos arquivos. Só os
    documentos referidos em votações nominais e seus substitutivos são retidos.
    """
    documentos = {}

    def incluir(registro: dict) -> None:
        if registro["id"] in ids:
            documentos[registro["id"]] = registro
        for substitutivo in registro.get("substitutivos") or []:
            if substitutivo["id"] in ids:
                documentos[substitutivo["id"]] = substitutivo

    if proposicoes is not None:
        for id_doc, registro in proposicoes.items():
            incluir({"id": id_doc, **registro})
    elif ids:
        for arquivo in sorted((raiz / "data" / "proposicoes").glob("*.json")):
            for registro in _ler_lista(arquivo):
                incluir(registro)
        # Os documentos enriquecidos já informam tipo/ano. Isso evita reler toda
        # a produção de indicações e moções na geração normal do site.
        referencias = {d["id"]: d for d in modelo.get("documentos") or [] if d["id"] in ids}
        faltantes = ids - documentos.keys()
        arquivos = {raiz / "data" / "documentos" / d["tipo"] / f"{d['ano']}.json"
                    for id_doc, d in referencias.items() if id_doc in faltantes and d.get("tipo") and d.get("ano")}
        if faltantes - referencias.keys():
            arquivos.update((raiz / "data" / "documentos").glob("*/*.json"))
        for arquivo in sorted(arquivos):
            if arquivo.is_file():
                for registro in _ler_lista(arquivo):
                    incluir(registro)
    for registro in [*(modelo.get("projetos") or []), *(modelo.get("documentos") or [])]:
        if registro["id"] in ids:
            documentos[registro["id"]] = {**documentos.get(registro["id"], {}), **registro}
    return documentos


# ---- projeções de regras -------------------------------------------------------
def _pessoas_do_modelo(modelo: dict, cfg: dict) -> dict:
    # indice_nomes reconhece também a autoria dos demais documentos. Uma página
    # pode existir por PL de outro mandato, sem PL na legislatura da sessão.
    fontes = [{"data": d.get("data"), "ano": d.get("ano"),
               "autoria": [a for a in d.get("autoria") or d.get("autores") or [] if a.get("vereador", True)]}
              for campo in ("projetos", "documentos") for d in modelo.get(campo) or []]
    cfg_nomes = {**cfg, "legislaturas": [{**leg, "eleitos": leg.get("eleitos") or []} for leg in cfg["legislaturas"]]}
    conhecidas, indice = R.indice_nomes(cfg_nomes, fontes)
    pessoas = {}
    for s, pessoa in sorted((modelo.get("pessoas") or {}).items()):
        conhecida = conhecidas.get(indice.get(slug(pessoa["nome_siscam"]))) or {}
        legs = set(pessoa.get("legislaturas") or []) | set(pessoa.get("mandatos") or [])
        pessoas[s] = {**pessoa, "legislaturas": legs | set(conhecida.get("legislaturas") or []),
                      "suplencias_sessoes": set(pessoa.get("suplencias_sessoes") or [])}
    return pessoas


def _presenca(resumo: dict | None = None) -> dict:
    resumo = resumo or {}
    categorias = resumo.get("categorias") or {}
    denominador = resumo.get("denominador", 0)
    presentes = resumo.get("presentes", 0)
    base_bruta = presentes + sum(categorias.get(c, 0) for c in ("A", "J", "O"))
    return {**{c: categorias.get(c, 0) for c in CAMPOS_PRESENCA},
            "denominador": denominador, "presentes": presentes,
            "faltas": resumo.get("faltas", 0), "listadas": resumo.get("listadas", 0),
            "pct": round(100 * presentes / denominador) if denominador >= R.MINIMO_BASE_PRESENCA else None,
            "pct_bruta": round(100 * presentes / base_bruta) if base_bruta >= R.MINIMO_BASE_PRESENCA else None}


def _registro_pessoa() -> dict:
    return {"presenca": _presenca(), "por_ano": {},
            "participacao": {"votou": 0, "possiveis": 0, "presidindo": 0},
            "como_votou": {}, "indeterminadas": 0, "divididas": 0, "divergencias": []}


def _aviso(sessao: dict, motivo: str, *, documento: str | None = None, nome: str | None = None) -> dict:
    return {"sessao": sessao["id"], "data": sessao.get("data"),
            "documento": documento, "nome": nome, "motivo": motivo}


def _ordenar_avisos(avisos: list[dict]) -> list[dict]:
    unicos = {json.dumps(a, sort_keys=True, ensure_ascii=False): a for a in avisos}
    return sorted(unicos.values(), key=lambda a: (a["data"] or "", a["sessao"],
                                                  a["documento"] or "", a["nome"] or "", a["motivo"]))


def _agregar_voto(registro: dict, voto: str | None, votacao: dict) -> None:
    registro["participacao"]["possiveis"] += 1
    registro["participacao"]["presidindo"] += int(voto == "Presidente")
    if voto not in R.VOTOS_SUBSTANTIVOS:
        return
    registro["participacao"]["votou"] += 1
    registro["divididas"] += int(votacao["classe"] == "dividida")
    if votacao["qualidade"] == "indeterminado":
        registro["indeterminadas"] += 1
    elif votacao["qualidade"] == "ok":
        contagem = registro["como_votou"].setdefault(votacao["materia"], {})
        rotulo = R.rotulo_voto(voto, votacao["sentido"], votacao["materia"])
        contagem[rotulo] = contagem.get(rotulo, 0) + 1
    if votacao["qualidade"] != "inconsistente" and R.divergencia(voto, votacao["totais"]):
        registro["divergencias"].append(votacao["id"])


# ---- modelo das sessões --------------------------------------------------------
def montar_sessoes(modelo: dict, registros: list[dict] | None = None,
                   proposicoes: dict | None = None, raiz: Path | None = None) -> dict:
    """Agrega sessões e votos nominais, com denominadores individuais observados.

    ``por_pessoa`` reúne a composição conhecida e suplências reconhecidas pela
    frequência reiterada ou voto nominal, sem criar páginas no modelo geral.
    Placar e sentido incluem todos os votos, independentemente da composição.
    Presença vem do resumo das regras; participação exige exercício na sessão. Como
    votou/divididas contam votos substantivos; divergência independe do sentido,
    mas nunca inclui placares inconsistentes. Não há indicador leitura→votação.
    """
    raiz = Path(raiz) if raiz is not None else RAIZ
    if registros is None:
        registros = [s for arquivo in sorted((raiz / "data" / "sessoes").glob("*.json")) for s in _ler_lista(arquivo)]
    ordenadas = sorted(registros, key=_chave_sessao)
    cfg = {**(modelo.get("cfg") or {})}
    legs = modelo.get("legislaturas") or cfg.get("legislaturas") or []
    cfg["legislaturas"] = legs
    pessoas = _pessoas_do_modelo(modelo, cfg)
    # Só as pessoas originais podem ter os aliases já usados pelo modelo geral.
    # Nomes reconhecidos nas sessões usam exclusivamente seu slug literal.
    indice = indice_pessoas(pessoas)
    candidatos = R.suplentes_das_sessoes(ordenadas, pessoas, cfg)
    for (s, leg_id), candidato in candidatos.items():
        if not candidato["incluido"]:
            continue
        pessoa = pessoas.setdefault(s, {"nome_siscam": candidato["nome_siscam"], "nome": candidato["nome"], "legislaturas": set()})
        pessoa["legislaturas"].add(leg_id)
        pessoa.setdefault("suplencias_sessoes", set()).add(leg_id)
        indice.setdefault(s, s)
    abonos = R.intervalos_abono(cfg, registros, indice)
    ids = {v["id_documento"] for s in ordenadas for v in s.get("votacoes") or []
           if R.votacao_nominal(v) and v.get("id_documento") is not None}
    documentos = _documentos(modelo, proposicoes, raiz, ids)
    anos = sorted({s["ano"] for s in ordenadas})
    saida = {"anos": anos,
             "cobertura": {a: dict.fromkeys(("listadas", "com_frequencia", "com_votacao", "pendentes"), 0) for a in anos},
             "legislaturas": [], "sessoes": [], "votacoes": [], "por_pessoa": {}, "mediana_presenca": {},
             "exercicio": {l["id"]: {"total": 0, "primeira": None, "ultima": None} for l in legs},
             "placares_por_ano": {a: dict.fromkeys(CAMPOS_PLACAR, 0) for a in anos}, "ritmo": {},
             "qualidade": {c: [] for c in ("sem_lista", "inconsistentes", "indeterminadas", "duplicados", "nao_membros", "notas")}}
    qualidade = saida["qualidade"]
    por_leg, por_leg_ano = defaultdict(list), defaultdict(list)
    ritmo = defaultdict(lambda: defaultdict(Counter))
    for sessao in ordenadas:
        leg_id = legislatura_de(sessao.get("data"), sessao["ano"], legs)
        if leg_id:
            por_leg[leg_id].append(sessao)
            por_leg_ano[(leg_id, sessao["ano"])].append(sessao)
    for leg in sorted(legs, key=lambda l: (l["inicio"], l["id"])):
        leg_id = leg["id"]
        if leg_id not in por_leg:
            continue
        anos_leg = sorted({s["ano"] for s in por_leg[leg_id]})
        saida["legislaturas"].append({"id": leg_id, "rotulo": leg.get("rotulo") or leg_id, "anos": anos_leg})
        resumo = R.resumo_presencas(por_leg[leg_id], pessoas=pessoas, cfg=cfg, abonos=abonos)
        anuais = {ano: R.resumo_presencas(por_leg_ano[(leg_id, ano)], pessoas=pessoas, cfg=cfg, abonos=abonos) for ano in anos_leg}
        for s, pessoa in pessoas.items():
            if leg_id not in pessoa["legislaturas"]:
                continue
            registro = saida["por_pessoa"].setdefault(s, {})[leg_id] = _registro_pessoa()
            if leg_id in pessoa.get("suplencias_sessoes", set()):
                registro.update(sem_pagina=s not in (modelo.get("pessoas") or {}),
                                nome=candidatos[(s, leg_id)]["nome"], condicao="suplente em exercício")
            registro["presenca"] = _presenca(resumo.get(s))
            registro["por_ano"] = {ano: _presenca(anuais[ano].get(s)) for ano in anos_leg}
        eleitos = {indice.get(slug(e["siscam"])) for e in leg.get("eleitos") or []}
        eleitos.update(s for s, p in pessoas.items() if ((p.get("mandatos") or {}).get(leg_id) or {}).get("eleito"))
        percentuais = [registro[leg_id]["presenca"]["pct"] for s, registro in saida["por_pessoa"].items()
                       if s in eleitos and leg_id in registro and registro[leg_id]["presenca"]["pct"] is not None]
        saida["mediana_presenca"][leg_id] = statistics.median(percentuais) if percentuais else None

    for sessao in ordenadas:
        ano = sessao["ano"]
        leg_id = legislatura_de(sessao.get("data"), ano, legs)
        membros = R.indice_membros(sessao, pessoas, cfg)
        presencas = R.presencas_da_sessao(sessao, membros, abonos)
        if leg_id:
            cobertura_exercicio = saida["exercicio"][leg_id]
            cobertura_exercicio["total"] += int(presencas["incluida"])
            if sessao.get("tipo") in R.TIPOS_DELIBERATIVOS and sessao.get("data"):
                data = sessao["data"]
                cobertura_exercicio["primeira"] = min(cobertura_exercicio["primeira"] or data, data)
                cobertura_exercicio["ultima"] = max(cobertura_exercicio["ultima"] or data, data)
        exercicio = R.pessoas_em_exercicio(sessao, membros, presencas=presencas)
        indicadores = R.indicadores_sessao(sessao)
        cobertura = saida["cobertura"][ano]
        cobertura["listadas"] += 1
        cobertura["com_frequencia"] += int(bool(sessao.get("frequencia")))
        cobertura["com_votacao"] += int(bool(sessao.get("votacoes")))
        cobertura["pendentes"] += int(bool(sessao.get("detalhe_pendente")))
        if sessao.get("data"):
            ritmo[ano][sessao["data"][:7]][sessao.get("tipo") or "desconhecido"] += 1
        if indicadores["deliberativa"] and not sessao.get("frequencia"):
            qualidade["sem_lista"].append(_aviso(sessao, "sessão deliberativa sem lista de frequência"))
        if not leg_id:
            qualidade["notas"].append(_aviso(sessao, "sem legislatura correspondente; fora das métricas individuais"))
        for marca in indicadores["marcas"]:
            if marca != "sem lista de frequência":
                qualidade["notas"].append(_aviso(sessao, marca))
        for mensagem in presencas["qualidade"]:
            if mensagem != "sessão sem lista de frequência" and "não membro da legislatura" not in mensagem:
                qualidade["notas"].append(_aviso(sessao, mensagem))
        for repetida in presencas["duplicatas"]:
            qualidade["duplicados"].append(_aviso(sessao,
                f"frequência: {repetida['linhas']} linhas → {repetida['categoria']}", nome=repetida["nome"]))
        for linha in sessao.get("frequencia") or []:
            if slug(linha["nome"]) not in membros:
                motivo = (candidatos.get((slug(linha["nome"]), leg_id)) or {}).get("motivo") or "sem legislatura correspondente"
                qualidade["nao_membros"].append(_aviso(sessao, motivo, nome=linha["nome"]))
        cartao = {c: sessao.get(c) for c in ("id", "data", "hora", "tipo", "numero", "titulo")}
        cartao.update(indicadores)
        cartao.update(url_siscam=DETALHE_SESSAO.format(id=sessao["id"]), votacoes=[])
        saida["sessoes"].append(cartao)
        repeticoes = Counter()
        pauta = {item["id_documento"]: item for item in sessao.get("pauta") or [] if item.get("id_documento") is not None}
        for posicao, votacao in enumerate(sorted(sessao.get("votacoes") or [], key=_chave_votacao), 1):
            referencia = votacao.get("documento") or f"id {votacao.get('id_documento')}"
            for linha in votacao.get("votos") or []:
                if slug(linha["nome"]) not in membros:
                    motivo = (candidatos.get((slug(linha["nome"]), leg_id)) or {}).get("motivo") or "sem legislatura correspondente"
                    qualidade["nao_membros"].append(_aviso(sessao, motivo, documento=referencia, nome=linha["nome"]))
            # Índice completo: resolve identidades já conhecidas, mas nunca
            # descarta uma linha por falta de página ou prova de mandato.
            indice_votos = {slug(l["nome"]): membros.get(slug(l["nome"]), slug(l["nome"])) for l in votacao.get("votos") or []}
            dedup = R.deduplicar_votos(votacao, indice_votos)
            if not dedup["incluida"] or not dedup["votos"]:
                if dedup["incluida"]:
                    qualidade["notas"].append(_aviso(sessao, "sem votos nominais; fora das métricas", documento=referencia))
                elif slug(votacao.get("tipo_votacao") or "") == "nominal":
                    qualidade["notas"].append(_aviso(sessao, "votação nominal sem lista de votos", documento=referencia))
                continue
            id_doc = votacao.get("id_documento")
            documento = documentos.get(id_doc) or {}
            referencia_pauta = pauta.get(id_doc) or {}
            base_id = f"{sessao['id']}-{id_doc if id_doc is not None else f'n{posicao}'}"
            repeticoes[base_id] += 1
            id_votacao = base_id if repeticoes[base_id] == 1 else f"{base_id}-{repeticoes[base_id]}"
            analise = R.sentido_voto(votacao, sessao, documento or None, indice=indice_votos)
            sentido = analise["sentido"]
            estado = sentido if sentido in {"inconsistente", "indeterminado"} else "ok"
            notas = sorted(set(analise["notas"] + analise["motivos"] + dedup["qualidade"]))
            registro = {"id": id_votacao, "sessao": sessao["id"], "data": sessao.get("data"),
                        "titulo_sessao": sessao.get("titulo"), "materia": analise["materia"],
                        "id_documento": id_doc, "documento": referencia,
                        "numero": documento.get("numero") or votacao.get("numero") or referencia_pauta.get("numero"),
                        "ementa": documento.get("ementa") or votacao.get("ementa") or referencia_pauta.get("ementa") or "",
                        "url_documento": URL_DETALHE.format(id=id_doc) if id_doc is not None else None,
                        "resultado": votacao.get("resultado") or "",
                        "totais": {c: dedup["totais"][c] for c in CAMPOS_TOTAIS},
                        "totais_oficiais": dict(votacao["totais"]) if isinstance(votacao.get("totais"), dict) else None,
                        "classe": R.classe_votacao(dedup["totais"]), "sentido": sentido, "fonte_sentido": analise["fonte"],
                        "maioria": R.maioria(dedup["totais"]), "quorum": R.quorum_veto(analise),
                        "qualidade": estado, "notas": notas, "votos": dedup["votos"],
                        "rotulos": {s: R.rotulo_voto(v, sentido, analise["materia"]) for s, v in dedup["votos"].items()},
                        "resumo": R.resumo_placar(analise)}
            saida["votacoes"].append(registro)
            cartao["votacoes"].append(id_votacao)
            saida["placares_por_ano"][ano][registro["classe"]] += 1
            if estado != "ok":
                saida["placares_por_ano"][ano][estado] += 1
                grupo = "inconsistentes" if estado == "inconsistente" else "indeterminadas"
                qualidade[grupo].append(_aviso(sessao, "; ".join(analise["motivos"]), documento=referencia))
            for nota in analise["notas"] + dedup["qualidade"]:
                if "não membro da legislatura" not in nota:
                    qualidade["notas"].append(_aviso(sessao, nota, documento=referencia))
            for repetida in dedup["duplicatas"]:
                qualidade["duplicados"].append(_aviso(sessao, f"votação: {repetida['linhas']} linhas → {repetida['voto']}",
                                                      documento=referencia, nome=repetida["nome"]))
            individuais = R.deduplicar_votos(votacao, membros)["votos"]
            for s in sorted(exercicio):
                pessoa = saida["por_pessoa"].get(s, {}).get(leg_id)
                if pessoa is not None:
                    _agregar_voto(pessoa, individuais.get(s), registro)

    saida["por_pessoa"] = {s: {leg: {**reg, "como_votou": {m: dict(sorted(cont.items())) for m, cont in sorted(reg["como_votou"].items())}}
                              for leg, reg in sorted(legs_pessoa.items())}
                           for s, legs_pessoa in sorted(saida["por_pessoa"].items())}
    saida["ritmo"] = {a: {mes: dict(sorted(cont.items())) for mes, cont in sorted(ritmo[a].items())} for a in anos}
    saida["qualidade"] = {c: _ordenar_avisos(avisos) for c, avisos in qualidade.items()}
    return saida
