"""Modelo de dados do site: projetos enriquecidos, pessoas, mandatos e métricas."""
from __future__ import annotations

import json
import re
import statistics
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from coletor import regras_documentos as RD
from coletor.classificar import carregar_curadoria, carregar_proposicoes, classificacao_final
from coletor.novidades import marcos_tramitacao
from coletor.siscam import derivar_lei

RAIZ = Path(__file__).resolve().parents[2]
URL_DETALHE = "https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento={id}"

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
NOME_TIPO_LEI = {
    "sancionada": "Sancionada",
    "promulgada_camara": "Promulgada pela Câmara",
    "veto_derrubado": "Veto derrubado",
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

# ---------------------------------------------------------- demais documentos
# Pastas de data/documentos/<tipo>/<ano>.json, na ordem do coletor.
TIPOS_DOC = ("requerimento", "indicacao", "mocao", "pdl", "resolucao")
# (singular, plural, rótulo curto usado antes do número)
NOME_TIPO_DOC = {
    "requerimento": ("Requerimento", "Requerimentos", "Requerimento"),
    "indicacao": ("Indicação", "Indicações", "Indicação"),
    "mocao": ("Moção", "Moções", "Moção"),
    "pdl": ("Projeto de decreto legislativo", "Projetos de decreto legislativo", "PDL"),
    "resolucao": ("Projeto de resolução", "Projetos de resolução", "Resolução"),
}
# Tipos cujo detalhe (autoria com papel e tramitação completa) é consultado; os demais
# só pela listagem, exceto quando têm mais de um autor.
TIPOS_COM_DETALHE = ("requerimento", "pdl", "resolucao")
NOME_CATEGORIA_DOC = {
    "zeladoria": "Zeladoria",
    "fiscalizacao": "Fiscalização",
    "homenagem": "Homenagem",
    "manifestacao": "Manifestação",
    "legislacao": "Legislação",
    "outra": "Outra",
}
DESC_CATEGORIA_DOC = {
    "zeladoria": "Indicações: pedidos de serviço ao Executivo, como iluminação, asfalto, poda ou limpeza.",
    "fiscalizacao": "Requerimentos que pedem informações ou cópias de processos e contratos.",
    "homenagem": "Moções de aplauso ou de pesar; títulos de cidadão, medalhas, diplomas e outras honrarias em PDLs e resoluções.",
    "manifestacao": "Demais moções: repúdio, apoio e outras.",
    "legislacao": "PDLs e resoluções que não são homenagem, como mudanças no Regimento ou sustação de atos.",
    "outra": "Demais requerimentos.",
}
NOME_SUBCATEGORIA_DOC = {
    ("indicacao", "iluminacao"): "Iluminação",
    ("indicacao", "asfalto"): "Asfalto e buracos",
    ("indicacao", "poda"): "Poda e árvores",
    ("indicacao", "limpeza"): "Limpeza",
    ("indicacao", "saneamento"): "Saneamento e drenagem",
    ("indicacao", "transito"): "Trânsito e sinalização",
    ("indicacao", "outra"): "Outros serviços",
    ("requerimento", "informacao"): "Pedido de informação",
    ("requerimento", "outro"): "Outro requerimento",
    ("mocao", "aplauso"): "Aplauso",
    ("mocao", "pesar"): "Pesar",
    ("mocao", "repudio"): "Repúdio",
    ("mocao", "apoio"): "Apoio",
    ("mocao", "outra"): "Outra moção",
    ("pdl", "titulo_cidadao"): "Título de cidadão",
    ("pdl", "honraria"): "Honraria",
    ("pdl", "outra"): "Outro PDL",
    ("resolucao", "honraria"): "Honraria",
    ("resolucao", "regimento"): "Regimento",
    ("resolucao", "administrativa"): "Administrativa",
    ("resolucao", "outra"): "Outra resolução",
}
NOME_EIXO = {"zeladoria": "Zeladoria", "fiscalizacao": "Fiscalização", "homenagem": "Homenagem", "legislacao": "Legislação"}


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


# ------------------------------------------------------------- demais documentos
def _sem_acento(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in t if not unicodedata.combining(c)).upper()


def numero_int(numero) -> int:
    try:
        return int(str(numero).split("/")[0])
    except ValueError:
        return 0


def chave_documento(d: dict) -> tuple:
    """Ordem dos documentos; com reverse=True, do mais recente ao mais antigo (igual a compararDocs no dados.js)."""
    return (d.get("data") or "", d["ano"], numero_int(d["numero"]), d["id"])


def carregar_documentos() -> list[dict]:
    """Registros de data/documentos/<tipo>/<ano>.json; tipo ou ano sem arquivo não contribui com nada."""
    registros = []
    for tipo in TIPOS_DOC:
        pasta = RAIZ / "data" / "documentos" / tipo
        if not pasta.is_dir():
            continue
        for arq in sorted(pasta.glob("*.json")):
            dados = json.loads(arq.read_text(encoding="utf-8"))
            if not isinstance(dados, list):
                raise ValueError(f"{arq}: esperada uma lista de documentos")
            registros.extend({**r, "tipo": r.get("tipo") or tipo} for r in dados)
    return registros


def e_autor_vereador_doc(autor: dict, nao_vereador: list[str]) -> bool:
    """Como e_vereador, mas sem diferenciar caixa nem acentos: a listagem traz nomes em caixa mista."""
    nome = _sem_acento(autor.get("nome") or "")
    if any(_sem_acento(t) in nome for t in nao_vereador):
        return False
    return (autor.get("origem") or "").lower() in ("", "vereador", "vereadora")


def indice_pessoas(pessoas: dict) -> dict[str, str]:
    """Slug de nome → slug da pessoa; aceita também o nome sem o apelido depois de " - "."""
    indice = {s: s for s in pessoas}
    variantes: dict[str, set[str]] = defaultdict(set)
    for s, p in pessoas.items():
        base = slug(p["nome_siscam"].split(" - ")[0])
        if base and base not in indice:
            variantes[base].add(s)
    indice.update({b: next(iter(ss)) for b, ss in variantes.items() if len(ss) == 1})  # ambíguas ficam de fora
    return indice


def montar_documentos(registros: list[dict], cfg: dict, pessoas: dict, legs: list[dict]) -> list[dict]:
    """Documentos enriquecidos, do mais recente ao mais antigo, separados dos projetos de lei.

    A autoria vem do detalhe ("autoria", com papel) quando existe; senão, da listagem
    ("autores"), em que todos contam como autores, sem principal nem coautor.
    """
    nao_vereador = cfg.get("nao_vereador", [])
    apelidos = {slug(k): v for k, v in cfg.get("apelidos", {}).items() if not k.startswith("_")}
    indice = indice_pessoas(pessoas)
    vistos: set[tuple[str, int]] = set()
    documentos = []
    for r in registros:
        if (r["tipo"], r["id"]) in vistos:
            continue
        vistos.add((r["tipo"], r["id"]))
        cls = RD.classificar_documento(r)
        autoria = r.get("autoria") or []
        autores, marcas = [], set()
        for a in autoria or r.get("autores") or []:
            nome = " ".join(str(a.get("nome") or "").split())
            if not nome:
                continue
            vereador = e_autor_vereador_doc({**a, "nome": nome}, nao_vereador)
            s = indice.get(slug(nome), slug(nome)) if vereador else ""
            vereador = vereador and bool(s)
            marca = s or _sem_acento(nome)
            if marca in marcas:
                continue
            marcas.add(marca)
            if s in pessoas:
                exibicao = pessoas[s]["nome"]
            elif vereador:
                exibicao = apelidos.get(slug(nome)) or nome_curto(nome)
            else:
                exibicao = nome.title() if nome.isupper() else nome
            autores.append({"nome": nome, "papel": (a.get("papel") or "") if autoria else "", "slug": s,
                            "vereador": vereador, "pagina": s in pessoas, "exibicao": exibicao})
        respondido_em = r.get("respondido_em")
        dias = r.get("dias_ate_resposta")
        if "dias_ate_resposta" not in r and respondido_em:
            dias = dias_entre(r.get("data"), respondido_em)
        pub = r.get("publicacao")
        informacao = r["tipo"] == "requerimento" and cls["subcategoria"] == "informacao"
        documentos.append({
            "id": r["id"], "tipo": r["tipo"], "numero": r["numero"], "ano": r["ano"], "data": r.get("data"),
            "ementa": r.get("ementa") or "", "situacao": r.get("situacao") or "", "assunto": r.get("assunto") or None,
            "url": r.get("url") or URL_DETALHE.format(id=r["id"]),
            "legislatura": legislatura_de(r.get("data"), r["ano"], legs),
            "autores": autores,
            "categoria": cls["categoria"], "subcategoria": cls["subcategoria"], "homenagem": bool(cls["homenagem"]),
            "respondido": bool(cls["respondido"]), "publicado": bool(cls["publicado"]), "bairro": cls["bairro"],
            "respondido_em": respondido_em, "dias_ate_resposta": dias,
            "publicacao": {"numero": pub.get("numero"), "data": pub.get("data")} if isinstance(pub, dict) else None,
            "detalhe_pendente": bool(r.get("detalhe_pendente")),
            # Só nos requerimentos de informação; não vai para os JSONs do navegador (tabelas geradas no servidor).
            "orgao": RD.extrair_orgao(r.get("ementa"), r.get("assunto")) if informacao else None,
        })
    documentos.sort(key=chave_documento, reverse=True)
    return documentos


def atividade_por_autor(documentos: list[dict]) -> dict[str, dict]:
    """Documentos de cada autor vereador e contagens por legislatura; todo autor listado conta.

    Os eixos do perfil vêm de regras_documentos.eixos_perfil, a única regra do perfil.
    """
    atividade: dict[str, dict] = {}
    for d in documentos:
        eixos = RD.eixos_perfil(d)
        for a in d["autores"]:
            if not a["vereador"]:
                continue
            reg = atividade.setdefault(a["slug"], {"documentos": [], "por_leg": {}})
            reg["documentos"].append(d)
            if not d["legislatura"]:
                continue
            leg = reg["por_leg"].setdefault(d["legislatura"], {
                "tipos": dict.fromkeys(TIPOS_DOC, 0),
                "perfil": dict.fromkeys(RD.EIXOS_PERFIL, 0),
                "informacao": {"respondidos": 0, "sem_resposta": 0},
            })
            leg["tipos"][d["tipo"]] = leg["tipos"].get(d["tipo"], 0) + 1
            for e in eixos:
                leg["perfil"][e] = leg["perfil"].get(e, 0) + 1
            if d["tipo"] == "requerimento" and d["subcategoria"] == "informacao":
                leg["informacao"]["respondidos" if d["respondido"] else "sem_resposta"] += 1
    return atividade


# ------------------------------------------------------- métricas dos documentos
# Agregações sobre os documentos já classificados: as regras (homenagem, órgão, estado do
# pedido, bairro) ficam em regras_documentos; aqui só se conta. Valem para qualquer
# intervalo de anos e geram tabelas no servidor, sem mudar os JSONs do navegador.
# Contar documentos não mede qualidade nem resultado.
def _pct(parte: int, total: int) -> int | None:
    return round(100 * parte / total) if total else None


def _chave_texto(texto: str) -> tuple[str, str]:
    return (_sem_acento(texto), texto)


def e_pedido_informacao(d: dict) -> bool:
    return d["tipo"] == "requerimento" and d["subcategoria"] == "informacao"


def anos_coleta(documentos: list[dict]) -> dict[str, list[int]]:
    """Anos com documentos: "todos", "completos" (cada tipo de TIPOS_DOC tem ao menos um registro) e "parciais".

    Calculado uma vez em montar_modelo (modelo["anos_coleta"]). Num ano parcial faltam tipos inteiros, e o peso das
    homenagens dividiria por uma produção incompleta; por isso só os completos entram nele.
    """
    tipos: dict[int, set[str]] = defaultdict(set)
    for d in documentos:
        tipos[d["ano"]].add(d["tipo"])
    todos = sorted(tipos)
    completos = [a for a in todos if set(TIPOS_DOC) <= tipos[a]]
    return {"todos": todos, "completos": completos, "parciais": [a for a in todos if a not in completos]}


def coleta_do_modelo(modelo: dict) -> dict[str, list[int]]:
    """anos_coleta já calculado no modelo; só recalcula num modelo montado à mão (testes)."""
    return modelo.get("anos_coleta") or anos_coleta(modelo.get("documentos") or [])


def anos_documentos(modelo: dict) -> set[int]:
    """Anos com coleta completa (anos_coleta); fora deles, nem documentos nem projetos entram no peso das homenagens."""
    return set(coleta_do_modelo(modelo)["completos"])


def projetos_do_autor(modelo: dict, s: str) -> list[dict]:
    """Projetos de lei da pessoa como autora principal, em todas as legislaturas (mesma base de "apresentados")."""
    pessoa = modelo["pessoas"].get(s) or {}
    return [p for m in (pessoa.get("mandatos") or {}).values() for p in m["projetos_autor"]]


def resumo_homenagens(docs: list[dict], n_projetos: int) -> dict:
    """Homenagens entre `docs` (marca "homenagem" de regras_documentos) e o peso na produção.

    producao = len(docs) + n_projetos (documentos de todos os tipos mais projetos de lei do
    mesmo período); pct = homenagens / producao, em % inteiro.
    """
    homenagens = sum(1 for d in docs if d["homenagem"])
    producao = len(docs) + n_projetos
    return {"homenagens": homenagens, "documentos": len(docs), "projetos": n_projetos, "producao": producao,
            "pct": _pct(homenagens, producao)}


def homenagens_por_periodo(docs: list[dict], projetos: list[dict], anos: set[int] | None = None) -> dict:
    """Homenagens de um conjunto de documentos e projetos, por legislatura e por ano.

    Só entram anos de `anos` (padrão: os anos dos próprios documentos), para não dividir
    as homenagens por projetos de anos cujos documentos ainda não foram coletados.
    Devolve {"por_leg": {leg: resumo}, "por_ano": {ano: resumo}}, em ordem crescente.
    """
    anos = {d["ano"] for d in docs} if anos is None else anos
    docs = [d for d in docs if d["ano"] in anos]
    projetos = [p for p in projetos if p["ano"] in anos]
    saida: dict[str, dict] = {}
    for chave, campo in (("por_leg", "legislatura"), ("por_ano", "ano")):
        grupos_d, grupos_p = defaultdict(list), Counter(p[campo] for p in projetos if p[campo] is not None)
        for d in docs:
            if d[campo] is not None:
                grupos_d[d[campo]].append(d)
        saida[chave] = {k: resumo_homenagens(grupos_d.get(k, []), grupos_p.get(k, 0)) for k in sorted(set(grupos_d) | set(grupos_p))}
    return saida


def homenagens_do_autor(modelo: dict, s: str, anos: set[int] | None = None) -> dict:
    """homenagens_por_periodo da pessoa: documentos em que aparece como autora e projetos como autora principal.

    anos: anos com coleta completa; padrão, anos_documentos(modelo), já calculado no modelo.
    """
    docs = ((modelo.get("atividade") or {}).get(s) or {}).get("documentos") or []
    return homenagens_por_periodo(docs, projetos_do_autor(modelo, s), anos_documentos(modelo) if anos is None else anos)


def homenagens_por_ano(documentos: list[dict], projetos: list[dict], anos: set[int] | None = None) -> list[dict]:
    """Homenagens da Câmara por ano, por tipo, e o peso na produção total (documentos e projetos de lei de qualquer autor).

    Só os anos de `anos` (no site, os de coleta completa; padrão, os anos dos documentos); tipos em TIPOS_DOC, com
    zero quando não há.
    """
    anos_ord = sorted({d["ano"] for d in documentos} if anos is None else anos)
    tipos = Counter((d["ano"], d["tipo"]) for d in documentos if d["homenagem"])
    resumo = homenagens_por_periodo(documentos, projetos, set(anos_ord))["por_ano"]
    return [{"ano": a, "por_tipo": {t: tipos.get((a, t), 0) for t in TIPOS_DOC}, **(resumo.get(a) or resumo_homenagens([], 0))}
            for a in anos_ord]


def resumo_informacao(docs: list[dict]) -> dict:
    """Requerimentos de informação entre `docs`, pelo estado de regras_documentos.estado_pedido.

    taxa: % de respondidos entre os pedidos não retirados; mediana_dias: mediana de
    dias_ate_resposta só entre os respondidos que têm esse número (com_dias, a base da
    mediana: os dias só existem quando o detalhe, com a tramitação, foi baixado);
    pendentes: pedidos com detalhe_pendente.
    """
    estados: Counter = Counter()
    dias = []
    pendentes = 0
    for d in docs:
        if not e_pedido_informacao(d):
            continue
        estado = RD.estado_pedido(d["respondido"], d["situacao"])
        estados[estado] += 1
        pendentes += bool(d.get("detalhe_pendente"))
        if estado == "respondido" and d["dias_ate_resposta"] is not None:
            dias.append(d["dias_ate_resposta"])
    pedidos = sum(estados.values())
    return {
        "pedidos": pedidos, "respondidos": estados["respondido"], "aguardando": estados["aguardando"],
        "encerrados": estados["encerrado"], "retirados": estados["retirado"],
        "taxa": _pct(estados["respondido"], pedidos - estados["retirado"]),
        "mediana_dias": statistics.median(dias) if dias else None, "com_dias": len(dias), "pendentes": pendentes,
    }


def orgao_do_documento(d: dict) -> str:
    return d.get("orgao") or RD.extrair_orgao(d.get("ementa"), d.get("assunto"))


def ranking_orgaos(docs: list[dict]) -> list[dict]:
    """resumo_informacao por órgão citado (regras_documentos.extrair_orgao), do mais pedido ao menos pedido.

    Empates pelo nome; "Não identificado" fica por último.
    """
    grupos: dict[str, list[dict]] = defaultdict(list)
    for d in docs:
        if e_pedido_informacao(d):
            grupos[orgao_do_documento(d)].append(d)
    linhas = [{"orgao": o, **resumo_informacao(ds)} for o, ds in grupos.items()]
    linhas.sort(key=lambda l: (l["orgao"] == RD.ORGAO_NAO_IDENTIFICADO, -l["pedidos"], _chave_texto(l["orgao"])))
    return linhas


def resumo_bairros(docs: list[dict], top: int = 5) -> dict:
    """Bairros das indicações entre `docs` (regras_documentos.extrair_bairro).

    top: os `top` bairros mais citados, (bairro, indicações), empates pelo nome;
    mais_citados: todos os empatados no topo; concentracao: % das indicações com bairro
    que caem no mais citado (em cada um, se houver empate); pct_sem_bairro: % das
    indicações sem bairro reconhecido.
    """
    indicacoes = [d for d in docs if d["tipo"] == "indicacao"]
    cont = Counter(d["bairro"] for d in indicacoes if d["bairro"])
    com_bairro = sum(cont.values())
    ordem = sorted(cont.items(), key=lambda bn: (-bn[1], _chave_texto(bn[0])))
    return {"indicacoes": len(indicacoes), "com_bairro": com_bairro, "sem_bairro": len(indicacoes) - com_bairro,
            "pct_sem_bairro": _pct(len(indicacoes) - com_bairro, len(indicacoes)), "distintos": len(cont),
            "top": ordem[:top], "mais_citados": [b for b, n in ordem if n == ordem[0][1]] if ordem else [],
            "concentracao": _pct(ordem[0][1], com_bairro) if ordem else None}


def indicacoes_por_bairro(docs: list[dict]) -> list[dict]:
    """Os 52 bairros oficiais, na ordem de BAIRROS_POR_REGIAO, com as indicações de cada um, inclusive zero."""
    cont = Counter(d["bairro"] for d in docs if d["tipo"] == "indicacao" and d["bairro"])
    return [{"regiao": r, "bairro": b, "indicacoes": cont.get(b, 0)} for r, bs in RD.BAIRROS_POR_REGIAO.items() for b in bs]


def menos_citados(por_bairro: list[dict], n: int = 10) -> list[dict]:
    """Os `n` bairros com menos indicações, mais os empatados com o último deles; do menor ao maior."""
    ordem = sorted(por_bairro, key=lambda b: (b["indicacoes"], _chave_texto(b["bairro"])))
    if len(ordem) <= n:
        return ordem
    corte = ordem[n - 1]["indicacoes"]
    return [b for b in ordem if b["indicacoes"] <= corte]


def documentos_por_legislatura(modelo: dict) -> dict[str, dict[str, list[dict]]]:
    """Documentos de cada autor vereador por legislatura: {leg: {slug: [docs]}}; sem legislatura não entra."""
    saida: dict[str, dict[str, list[dict]]] = defaultdict(dict)
    for s, reg in (modelo.get("atividade") or {}).items():
        for d in reg["documentos"]:
            if d["legislatura"]:
                saida[d["legislatura"]].setdefault(s, []).append(d)
    return saida


# ------------------------------------------------------------------------ modelo
def substitutivo_da_lei(p: dict) -> dict | None:
    """Substitutivo de onde saiu a lei do PL (lei_substitutivo), se ele estiver entre os coletados."""
    ls = p.get("lei_substitutivo")
    return next((s for s in p.get("substitutivos") or [] if isinstance(s, dict) and s.get("id") == ls), None) if ls else None


def autoria_efetiva(p: dict) -> list[dict]:
    """Soma os autores do substitutivo que virou lei, como coautores se não assinaram o PL."""
    autoria = p.get("autoria") or []
    substitutivo = substitutivo_da_lei(p)
    if not substitutivo or p.get("desfecho") != "virou_lei" or not p.get("lei"):
        return autoria
    autores, vistos = [], set()
    novos = [{**a, "papel": "Co-Autor"} for a in substitutivo.get("autoria") or []]
    for a in autoria + novos:
        s = slug(a["nome"])  # mesma identidade usada no PL; o id do autor pode não existir no substitutivo
        if s not in vistos:
            vistos.add(s)
            autores.append(a)
    return autores


def corrigir_proposicao(p: dict, correcao: dict | None) -> dict:
    """Aplica a curadoria sem apagar campos conhecidos da lei com valores nulos.

    A lei coletada (inclusive a de um substitutivo, com a data da promulgação) só perde para
    campos não nulos da curadoria.
    """
    corrigido = {**p, **(correcao or {})}
    lei = {**(p.get("lei") or {})}
    lei.update({k: v for k, v in ((correcao or {}).get("lei") or {}).items() if v is not None})
    if corrigido["desfecho"] == "virou_lei" and not lei.get("data"):
        # A mesma seleção do coletor, mas só entre passos datados: não usar a data de
        # apresentação, votação ou de uma simples menção a outra lei como publicação.
        # Lei vinda de substitutivo: a tramitação é a do substitutivo, não a do PL original.
        origem = substitutivo_da_lei(p) or p
        trams = [t for t in origem.get("tramitacoes", []) if t.get("data_resposta") or t.get("enviado")]
        derivada = derivar_lei(trams) or {}
        lei = {**lei, **derivada, **{k: v for k, v in lei.items() if v is not None}}
    corrigido["lei"] = lei or None
    return corrigido


def url_lei(p: dict) -> str:
    """Página do SISCAM da lei: a do substitutivo aprovado, quando houver; senão, a do próprio PL."""
    ls = p.get("lei_substitutivo")
    return URL_DETALHE.format(id=ls) if ls else p["url"]


def situacao_lei(lei: dict) -> str:
    """Situação da lei; espelho de situacaoLei em app.js."""
    rotulo = NOME_TIPO_LEI.get(lei.get("tipo"), "Situação não informada")
    return rotulo + (" · Veto parcial" if lei.get("veto_parcial") else "")


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
        p = corrigir_proposicao(p, correcao)
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
        # Só com lei e substitutivo coletado: o link da lei passa a ser o do substitutivo aprovado.
        lei_substitutivo = p.get("lei_substitutivo") if p["desfecho"] == "virou_lei" and lei and substitutivo_da_lei(p) else None
        # O principal e a origem continuam sendo os do PL, mesmo se só o substitutivo tiver vereadores.
        autoria = autoria_efetiva(p)
        projetos.append({
            "id": p["id"], "numero": p["numero"], "ano": p["ano"], "data": p.get("data"),
            "ementa": p.get("ementa") or "", "situacao": p.get("situacao") or "",
            "desfecho": p["desfecho"], "lei": p.get("lei"), "url": p["url"], "legislatura": leg,
            "lei_substitutivo": lei_substitutivo,
            "origem": origem,
            "autores": [{"nome": a["nome"], "papel": a.get("papel", ""), "slug": slug(a["nome"]), "vereador": e_vereador(a, cfg["nao_vereador"])} for a in autoria],
            "principal": slug(principal["nome"]) if principal else None,
            "dias_ate_lei": dias_entre(p.get("data_protocolo") or p.get("data"), lei.get("data")) if p["desfecho"] == "virou_lei" else None,
            "repete": None,
            # Veto e derrubada de veto com a data do passo da tramitação (do PL ou de um substitutivo).
            "marcos": marcos_tramitacao(p),
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

    # Documentos ficam fora de `projetos`: não entram em marcar_repetidos nem nas métricas de PL.
    documentos = montar_documentos(carregar_documentos(), cfg, pessoas, legs)
    atividade = atividade_por_autor(documentos)
    for s, pessoa in pessoas.items():
        pessoa["atividade"] = atividade.get(s) or {"documentos": [], "por_leg": {}}

    return {"legislaturas": legs, "pessoas": pessoas, "projetos": projetos, "meta": meta, "curadoria": curadoria, "cfg": cfg,
            "documentos": documentos, "atividade": atividade, "anos_coleta": anos_coleta(documentos)}


def mediana_legislatura(modelo: dict, leg_id: str, chave: str) -> float | None:
    vals = [p["mandatos"][leg_id]["metricas"][chave] for p in modelo["pessoas"].values()
            if leg_id in p["mandatos"] and p["mandatos"][leg_id]["eleito"] and p["mandatos"][leg_id]["metricas"][chave] is not None]
    return statistics.median(vals) if vals else None
