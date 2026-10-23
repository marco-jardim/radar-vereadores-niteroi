"""Regras puras das sessões; a auditoria lê os JSONs, sem rede nem gravações.

As funções devolvem avisos em ``qualidade``, sem imprimir nem alterar a entrada.
Nomes são casados pelo índice do modelo, nunca por aproximação. Partido não faz
parte destas regras. Uso: python -m coletor.regras_sessoes --auditoria.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from coletor.novidades import RE_PLENARIO, data_valida
from coletor.site.modelo import e_autor_vereador_doc, indice_pessoas, legislatura_de, nome_curto, slug


# ---- constantes ---------------------------------------------------------------
MINIMO_DIVIDIDA = 3
"""Limiar decidido de votação dividida; auditoria conserva a comparação 2–5."""

QUORUM_DERRUBADA_VETO = 11
"""Maioria absoluta dos 21 vereadores (art. 54 da Lei Orgânica:
"voto da maioria dos Vereadores"). Não é maioria dos presentes.
"""

ROTULO_QUORUM_VETO = "maioria absoluta (21 vereadores)"
"""Texto de apresentação do quórum, sem referência ao Regimento."""

TIPOS_DELIBERATIVOS = frozenset({"ordinaria", "extraordinaria"})
"""Só estes tipos, com frequência não vazia, entram na presença."""

VOTOS_SUBSTANTIVOS = frozenset({"Favor", "Contra", "Abstenção", "Branco", "Nulo"})
"""Evidência de participação nominal; presidência e ausência não são votos."""

CATEGORIAS_PRESENCA = {
    "P": "Presença", "C": "Consignado", "V": "Ausência com voto registrado",
    "J": "Ausência Justificada", "A": "Ausência", "L": "Licença", "?": "Texto desconhecido",
}
"""P/C/V contam como presentes; L/? ficam fora do denominador."""

ORDEM_PRESENCA = {c: i for i, c in enumerate("?AJLVCP")}
"""Melhor evidência, em ordem crescente: ? < A < J < L < V < C < P."""

CHAVES_TOTAIS = {
    "Favor": "favor", "Contra": "contra", "Abstenção": "abstencao", "Branco": "branco",
    "Nulo": "nulo", "Ausente": "ausentes", "Presidente": "presidente", "indeterminado": "indeterminado",
}
"""Totais recalculados depois da deduplicação, inclusive presidência e conflitos."""

RAIZ = Path(__file__).resolve().parent.parent
"""Raiz padrão da auditoria; as funções de regras não leem arquivos."""


# ---- votos e presença ----------------------------------------------------------
def _normalizar(texto: str) -> str:
    return slug(texto or "").replace("-", " ")


def _pessoa(nome: str, indice: dict[str, str] | None) -> str:
    chave = slug(nome)
    return (indice or {}).get(chave, chave)


def votacao_nominal(votacao: dict) -> bool:
    """Só votação de tipo Nominal e com linhas de votos pode ser analisada."""
    return _normalizar(votacao.get("tipo_votacao")) == "nominal" and bool(votacao.get("votos"))


def deduplicar_votos(votacao: dict, indice: dict[str, str] | None = None) -> dict:
    """Devolve votos (pessoa → texto), nomes, totais, duplicatas e qualidade.

    Presidente prevalece; depois voto substantivo; depois Ausente. Substantivos
    diferentes são indeterminados, mesmo se a pessoa também aparecer presidindo.
    Duplicatas idênticas não multiplicam os totais. Tipo não nominal fica de fora.
    Com índice explícito, só seus membros entram; use indice_membros por sessão.
    """
    grupos: dict[str, list[dict]] = defaultdict(list)
    nao_membros = []
    if votacao_nominal(votacao):
        for linha in votacao["votos"]:
            if indice is not None and slug(linha["nome"]) not in indice:
                nao_membros.append(f"{linha['nome']}: não membro da legislatura; voto {linha.get('voto')!r}")
                continue
            grupos[_pessoa(linha["nome"], indice)].append(linha)
    votos, nomes, duplicatas, qualidade = {}, {}, [], sorted(set(nao_membros))
    canonicos = {_normalizar(v): v for v in CHAVES_TOTAIS if v != "indeterminado"}
    for pessoa, linhas in sorted(grupos.items()):
        nomes[pessoa] = min(l["nome"] for l in linhas)
        opcoes = {canonicos.get(_normalizar(l.get("voto")), "indeterminado") for l in linhas}
        substantivos = opcoes & VOTOS_SUBSTANTIVOS
        if len(substantivos) > 1:
            voto = "indeterminado"
            qualidade.append(f"{nomes[pessoa]}: votos substantivos conflitantes ({', '.join(sorted(substantivos))})")
        elif "Presidente" in opcoes:
            voto = "Presidente"
        elif substantivos:
            voto = next(iter(substantivos))
        elif "Ausente" in opcoes:
            voto = "Ausente"
        else:
            voto = "indeterminado"
        if "indeterminado" in opcoes:
            textos = sorted({l.get("voto") or "" for l in linhas if _normalizar(l.get("voto")) not in canonicos})
            qualidade.append(f"{nomes[pessoa]}: voto desconhecido {textos!r}")
        votos[pessoa] = voto
        if len(linhas) > 1:
            duplicatas.append({"nome": nomes[pessoa], "linhas": len(linhas), "voto": voto})
    contagem = Counter(votos.values())
    totais = {chave: contagem[voto] for voto, chave in CHAVES_TOTAIS.items()}
    return {"incluida": votacao_nominal(votacao), "votos": votos, "nomes": nomes,
            "totais": totais, "duplicatas": duplicatas, "qualidade": qualidade,
            "nao_membros": sorted(set(nao_membros))}


def presencas_da_sessao(sessao: dict, indice: dict[str, str] | None = None) -> dict:
    """Categorias por pessoa, com flags presente/denominador/licenca e qualidade.

    O denominador é individual: só quem consta na frequência deliberativa, menos
    licenças e textos desconhecidos. Não se inventam faltas para nomes ausentes da
    lista. V exige ausência registrada e voto substantivo deduplicado na mesma sessão.
    """
    qualidade = []
    frequencia = []
    for linha in sessao.get("frequencia") or []:
        if indice is not None and slug(linha["nome"]) not in indice:
            qualidade.append(f"{linha['nome']}: não membro da legislatura; frequência {linha.get('situacao')!r}, momento {linha.get('momento')!r}")
        else:
            frequencia.append(linha)
    deliberativa = sessao.get("tipo") in TIPOS_DELIBERATIVOS
    if not frequencia:
        qualidade.append("sessão sem lista de frequência")
    if not deliberativa or not frequencia:
        return {"incluida": False, "pessoas": {}, "duplicatas": [], "qualidade": qualidade}
    participantes = set()
    for votacao in sessao.get("votacoes") or []:
        dedup = deduplicar_votos(votacao, indice)
        participantes.update(p for p, v in dedup["votos"].items() if v in VOTOS_SUBSTANTIVOS)
    grupos: dict[str, list[dict]] = defaultdict(list)
    for linha in frequencia:
        grupos[_pessoa(linha["nome"], indice)].append(linha)
    situacoes = {"presenca": "P", "consignado": "C", "ausencia justificada": "J", "ausencia": "A", "licenca": "L"}
    pessoas, duplicatas = {}, []
    for pessoa, linhas in sorted(grupos.items()):
        nome = min(l["nome"] for l in linhas)
        categorias = []
        for linha in linhas:
            categoria = situacoes.get(_normalizar(linha.get("situacao")), "?")
            if categoria == "?":
                qualidade.append(f"{nome}: frequência desconhecida {linha.get('situacao')!r}")
            if categoria in {"A", "J"} and pessoa in participantes:
                categoria = "V"
            categorias.append(categoria)
        categoria = max(categorias, key=ORDEM_PRESENCA.__getitem__)
        pessoas[pessoa] = {"nome": nome, "categoria": categoria, "presente": categoria in {"P", "C", "V"},
                           "denominador": categoria not in {"L", "?"}, "licenca": categoria == "L"}
        if len(linhas) > 1:
            duplicatas.append({"nome": nome, "linhas": len(linhas), "categoria": categoria})
    return {"incluida": True, "pessoas": pessoas, "duplicatas": duplicatas, "qualidade": sorted(set(qualidade))}


def classe_votacao(totais: dict, minimo: int = MINIMO_DIVIDIDA) -> str:
    """Unânime sem oposição/abstenção; dissenso abaixo do limiar; dividida acima."""
    if minimo < 1:
        raise ValueError("o mínimo de votação dividida deve ser positivo")
    menor = min(totais.get("favor", 0), totais.get("contra", 0))
    abst = totais.get("abstencao", 0)
    if menor >= minimo or abst >= minimo:
        return "dividida"
    return "dissenso" if menor or abst else "unanime"


def maioria(totais: dict) -> str | None:
    """Opção mais votada entre Favor/Contra; não é quórum legal de aprovação."""
    favor, contra = totais.get("favor", 0), totais.get("contra", 0)
    return None if favor == contra else "Favor" if favor > contra else "Contra"


def divergencia(voto: str, totais: dict) -> bool:
    """Só Favor/Contra na opção minoritária; empate não produz divergência."""
    maior = maioria(totais)
    return voto in {"Favor", "Contra"} and maior is not None and voto != maior


# ---- matéria, parecer e consistência -------------------------------------------
RE_PARECER_VETO = re.compile(r"\bparecer\b(?:(?!\bvotos?\b).)*?\bpela\s+(manutencao|derrubada|rejeicao)\s+d[oa]\s+veto\b")
"""Exige direção explícita do parecer; 'votos pela derrubada' sozinho não conta."""

RE_PARECER_PROJETO = re.compile(r"\bparecer\s+(?:verbal\s+)?(favoravel|contrario)\b")
"""Favor é voto sobre o parecer da CCJRF, não diretamente sobre a matéria."""

RE_DECISAO_PARECER = re.compile(r"\b(aprovad|rejeitad)[oa]\s+o\s+parecer\b")
"""Decisão do plenário sobre o parecer, distinta do resultado da matéria."""

RE_CONTAGEM = re.compile(r"\bcom\s+(\d+)\s+votos?\s+(favoraveis|contrarios)\b")
"""Contagens textuais são conferidas contra os votos nominais deduplicados."""


def materia_votacao(votacao: dict) -> str:
    """veto/pl/pdl/resolucao/outra, pela votação (não pela situação atual do PL)."""
    tipo = _normalizar(votacao.get("tipo_documento"))
    if "veto" in _normalizar(votacao.get("resultado")) or "veto" in tipo:
        return "veto"
    if tipo in {"pl", "projeto de lei"}:
        return "pl"
    if tipo in {"pdl", "projeto de decreto legislativo"}:
        return "pdl"
    if tipo in {"resolucao", "projeto de resolucao"}:
        return "resolucao"
    return "outra"


def _data_passo(passo: dict) -> str | None:
    # Data Resposta tem precedência: um envio anterior não antecipa o resultado.
    valor = passo.get("data_resposta") or passo.get("enviado")
    return valor if data_valida(valor) else None


def _texto_passo(passo: dict) -> str:
    return " ".join(str(passo.get(k) or "") for k in ("resultado", "observacao", "complemento"))


def _passos(documento: dict | None) -> list[tuple[dict, dict]]:
    if not documento:
        return []
    origens = [documento, *(documento.get("substitutivos") or [])]
    return [(origem, passo) for origem in origens for passo in origem.get("tramitacoes") or []]


def _evidencia(origem: dict, passo: dict) -> dict:
    return {"id_documento": origem.get("id"), "seq": passo.get("seq"),
            "data": _data_passo(passo), "texto": _texto_passo(passo)}


def _direcoes(texto: str, veto: bool) -> set[str]:
    normal = _normalizar(texto)
    if veto:
        return {"favor_mantem" if m == "manutencao" else "favor_derruba" for m in RE_PARECER_VETO.findall(normal)}
    return {"favor_aprova" if m == "favoravel" else "favor_rejeita" for m in RE_PARECER_PROJETO.findall(normal)}


def _inverter_sentido(sentido: str) -> str:
    return {"favor_mantem": "favor_derruba", "favor_derruba": "favor_mantem",
            "favor_aprova": "favor_rejeita", "favor_rejeita": "favor_aprova"}[sentido]


def _sentidos_textuais(texto: str, veto: bool, favor: int, contra: int) -> set[str]:
    """Decisão e direção, sem contagens, para o lado nominal Favor.

    A decisão descreve o lado vencedor: rejeitar um parecer pela derrubada é uma
    decisão pela manutenção. Se Contra venceu, converte-se de volta para Favor.
    Assim, 4×10 com parecer pela derrubada rejeitado continua favor_derruba.
    Não associa decisões de parágrafos/pareceres diferentes por produto cartesiano.
    """
    normal = _normalizar(texto)
    decisoes = list(RE_DECISAO_PARECER.finditer(normal))
    sentidos = set()
    if favor == contra:
        return sentidos
    for posicao, decisao in enumerate(decisoes):
        fim = decisoes[posicao + 1].start() if posicao + 1 < len(decisoes) else len(normal)
        trecho = normal[decisao.start():fim]
        direcoes = _direcoes(trecho, veto)
        if len(direcoes) == 1:
            sentido = next(iter(direcoes))
            if decisao.group(1) == "rejeitad":
                sentido = _inverter_sentido(sentido)
            if contra > favor:
                sentido = _inverter_sentido(sentido)
            sentidos.add(sentido)
    return sentidos


def _erros_totais(votacao: dict, dedup: dict) -> list[str]:
    """Duplicação/filtragem explicam ajustes; divergência não explicada é impossível."""
    brutos = Counter(_normalizar(v.get("voto")) for v in votacao.get("votos") or [])
    erros = []
    for voto, chave in CHAVES_TOTAIS.items():
        publicado = (votacao.get("totais") or {}).get(chave)
        if publicado is not None and publicado not in {brutos[_normalizar(voto)], dedup["totais"][chave]}:
            erros.append(f"total publicado {chave}={publicado} não fecha com linhas brutas ou votos deduplicados")
    return erros


def sentido_voto(
    votacao: dict, sessao: dict, documento: dict | None,
    *, sentido_curado: str | None = None, indice: dict[str, str] | None = None,
) -> dict:
    """Resultado oficial + lado vencedor; texto é desempate semântico ou conferência.

    Retorna sentido/sentido_base, fonte, evidencias, motivos, notas, qualidade e
    totais. Curadoria é um gancho explícito, sem configuração. Só vetos mantidos
    sem lado com 11 usam direção/decisão do texto na mesma data (janela zero).
    Narrativas de várias votações geram notas, nunca exclusão por contagem textual.
    """
    dedup = deduplicar_votos(votacao, indice)
    totais = dedup["totais"]
    materia = materia_votacao(votacao)
    veto = materia == "veto"
    permitidos = {"favor_mantem", "favor_derruba"} if veto else {"favor_aprova", "favor_rejeita"}
    if sentido_curado is not None and sentido_curado not in permitidos:
        raise ValueError("sentido curado incompatível com a matéria")
    motivos, evidencias, notas = [], [], []
    fonte = "nenhuma"
    dia = sessao.get("data")
    passos = _passos(documento)
    do_dia = [(o, p) for o, p in passos if data_valida(dia) and _data_passo(p) == dia
              and RE_PLENARIO.search(f"{p.get('destinatario') or ''} {p.get('objetivo') or ''}")]
    for origem, passo in do_dia:
        evidencias.append(_evidencia(origem, passo))
    favor, contra = totais["favor"], totais["contra"]
    resultado = _normalizar(votacao.get("resultado"))
    aprovado = bool(re.match(r"aprovad\w*\b", resultado))
    rejeitado = bool(re.match(r"rejeitad\w*\b", resultado))
    mantido = bool(re.search(r"\bveto\s+mantid\w*\b", resultado))
    derrubado = bool(re.search(r"\bveto\s+(?:rejeitad|derrubad)\w*\b", resultado))
    qualificado = "emenda a lei organica" in _normalizar(votacao.get("tipo_documento"))
    erros = _erros_totais(votacao, dedup) if dedup["incluida"] else []
    sentido = "indeterminado"
    if not dedup["incluida"]:
        motivos.append("votação não nominal ou sem votos")
    elif not dedup["votos"]:
        motivos.append("sem votos de membros da legislatura")
    elif totais["indeterminado"]:
        motivos.append("votos desconhecidos ou conflitantes impedem determinar o lado vencedor")
    elif veto and favor >= QUORUM_DERRUBADA_VETO and contra >= QUORUM_DERRUBADA_VETO:
        erros.append("dois lados com 11 votos: placar incompatível com 21 vereadores")
    elif veto and derrubado and max(favor, contra) < QUORUM_DERRUBADA_VETO:
        erros.append("veto derrubado sem 11 votos em nenhum lado")
    elif sentido_curado:
        sentido, fonte = sentido_curado, "curadoria"
        if veto and (mantido or derrubado):
            votos_derrubar = favor if sentido == "favor_derruba" else contra
            if derrubado != (votos_derrubar >= QUORUM_DERRUBADA_VETO):
                erros.append("curadoria contraria resultado oficial e quórum de 11 votos")
        elif not veto and not qualificado and (aprovado or rejeitado) and favor != contra:
            explica = (favor > contra) == (sentido == "favor_aprova")
            if explica != aprovado:
                erros.append("resultado contrário ao lado vencedor segundo a curadoria, sem quórum qualificado plausível")
    elif veto:
        # Mantém a limitação dos PLs históricos fora da base: não há documento
        # para conferir a identidade/natureza da votação (por exemplo, PL 2/2015).
        if not documento:
            motivos.append("documento do veto não encontrado nos dados")
        elif derrubado:
            sentido = "favor_derruba" if favor >= QUORUM_DERRUBADA_VETO else "favor_mantem"
            fonte = "resultado_oficial"
        elif mantido and max(favor, contra) >= QUORUM_DERRUBADA_VETO:
            sentido = "favor_mantem" if favor >= QUORUM_DERRUBADA_VETO else "favor_derruba"
            fonte = "resultado_oficial"
        elif mantido:
            textuais = set()
            for _, passo in do_dia:
                textuais.update(_sentidos_textuais(_texto_passo(passo), True, favor, contra))
            if len(textuais) == 1:
                sentido, fonte = next(iter(textuais)), "texto_veto_ambiguo"
            elif len(textuais) > 1:
                motivos.append("veto mantido ambíguo: direções/decisões textuais conflitantes")
            else:
                motivos.append("veto mantido ambíguo: nenhum lado com 11 e sem direção/decisão inequívoca na data")
        else:
            motivos.append("resultado de veto não reconhecido")
    elif qualificado:
        motivos.append("quórum qualificado (emenda à Lei Orgânica): maioria simples não explica o resultado com segurança")
    elif favor == contra:
        motivos.append("empate entre Favor e Contra")
    elif aprovado or rejeitado:
        sentido = "favor_aprova" if aprovado == (favor > contra) else "favor_rejeita"
        fonte = "resultado_oficial"
    else:
        motivos.append("resultado oficial não reconhecido")
    base = sentido
    for _, passo in do_dia:
        texto = _texto_passo(passo)
        normal = _normalizar(texto)
        direcoes = _direcoes(texto, veto)
        if sentido in permitidos and direcoes and sentido not in direcoes:
            notas.append("a direção do parecer na tramitação diverge do sentido derivado do resultado oficial; pode narrar outra votação")
        for quantidade, opcao in RE_CONTAGEM.findall(normal):
            chave = "favor" if opcao == "favoraveis" else "contra"
            if int(quantidade) != totais[chave]:
                notas.append(f"conferência textual {chave}={int(quantidade)} ≠ nominal {totais[chave]}; a tramitação pode misturar votações")
            if direcoes and opcao == "contrarios" and int(quantidade) == favor and favor != contra:
                notas.append("o SISCAM registra estes votos como 'Favor'; a tramitação os descreve como votos contrários ao parecer")
        for decisao in RE_DECISAO_PARECER.findall(normal):
            if (decisao == "aprovad") != (favor > contra):
                notas.append("decisão do parecer no texto diverge do lado nominal vencedor; conferência, não exclusão")
    if erros:
        sentido, motivos = "inconsistente", erros
    return {"sentido": sentido, "sentido_base": base, "materia": materia, "fonte": fonte,
            "evidencias": evidencias, "motivos": sorted(set(erros or motivos)),
            "notas": sorted(set(notas)), "qualidade": dedup["qualidade"], "totais": totais}


def rotulo_voto(voto: str, sentido: str, materia: str) -> str:
    """Traduz Favor/Contra só quando a direção do parecer é determinada e consistente."""
    fixos = {"Abstenção": "absteve-se", "Ausente": "ausente nesta votação", "Presidente": "presidia a sessão",
             "Branco": "votou em branco", "Nulo": "voto nulo"}
    if voto in fixos:
        return fixos[voto]
    if voto not in {"Favor", "Contra"}:
        return "voto não determinado"
    if sentido in {"favor_mantem", "favor_derruba"}:
        manter = (sentido == "favor_mantem") == (voto == "Favor")
        return "votou para manter o veto" if manter else "votou para derrubar o veto"
    if sentido in {"favor_aprova", "favor_rejeita"}:
        aprovar = (sentido == "favor_aprova") == (voto == "Favor")
        objeto = {"pl": "o projeto", "pdl": "o projeto de decreto legislativo", "resolucao": "o projeto de resolução"}.get(materia, "a matéria")
        return f"votou a favor d{objeto}" if aprovar else f"votou contra {objeto}"
    opcao = "Favor ao parecer" if voto == "Favor" else "Contra o parecer"
    return f"{opcao} (sentido não determinado)"


# ---- leitura até votação -------------------------------------------------------
LEITURA_VOTACAO_CONFIAVEL = False
"""Indicador suspenso: a pauta HTML não cobre a votação legislativa dos anexos."""

MOTIVO_LEITURA_VOTACAO = (
    "a pauta HTML não representa integralmente as ordens do dia anexadas; "
    "a ausência de fase Votação não prova que a matéria ainda não foi pautada. "
    "Substitutivos têm vínculo explícito, mas emendas/autógrafos/vetos não têm "
    "um vínculo geral seguro nestes arquivos. Discussão Única é apenas candidata, não prova de votação realizada"
)
"""Limitação da fonte, não uma estimativa de tempo de tramitação."""


def faixa_leitura_votacao(dias: int | None) -> str:
    """Faixas em dias corridos; None significa leitura ainda sem votação posterior."""
    if dias is None:
        return "ainda não pautado"
    if dias < 0:
        raise ValueError("o intervalo leitura–votação não pode ser negativo")
    for limite, rotulo in ((7, "até 7"), (30, "8–30"), (90, "31–90"), (180, "91–180"), (365, "181–365")):
        if dias <= limite:
            return rotulo
    return ">365"


def _chave_sessao(sessao: dict) -> tuple:
    return sessao.get("data") or "", sessao.get("hora") or "", sessao.get("id") or 0


def _vinculos_documentos(documentos: dict[int, dict]) -> dict[int, int]:
    return {s["id"]: d["id"] for d in documentos.values() for s in d.get("substitutivos") or []}


def _referencia_pauta(item: dict, documentos: dict[int, dict], vinculos: dict[int, int]) -> tuple[int | None, str]:
    id_doc = item.get("id_documento")
    raiz = vinculos.get(id_doc, id_doc)
    doc = documentos.get(raiz) or {}
    tipo = doc.get("tipo") or item.get("tipo_documento") or ""
    # Veto não é a primeira votação do projeto; emenda/autógrafo não se liga por
    # coincidência de número. Só substitutivos com vínculo expresso são reunidos.
    if "veto" in _normalizar(item.get("tipo_documento")):
        return None, "veto"
    materia = materia_votacao({"tipo_documento": tipo})
    return (raiz if materia in {"pl", "pdl", "resolucao"} else None), materia


def tempos_leitura_votacao(sessoes: list[dict], documentos: dict[int, dict] | None = None) -> dict[int, dict]:
    """DIAGNÓSTICO NÃO CONFIÁVEL, não utilizar como indicador na fase 1.

    Restringe a PL/PDL/resolução, reúne só substitutivos explicitamente ligados e
    aceita Discussão Única como candidata. Não usa a lista nominal de vetos para
    preencher lacunas da pauta. Uma referência enxuta pode nem distinguir a fase
    de veto da votação do PL. 'Sem par observado' não significa 'não pautado'.
    """
    documentos = documentos or {}
    vinculos = _vinculos_documentos(documentos)
    ordenadas = sorted((s for s in sessoes if data_valida(s.get("data"))), key=_chave_sessao)
    leituras: dict[int, dict] = {}
    votacoes: dict[int, list[dict]] = defaultdict(list)
    for sessao in ordenadas:
        for item in sessao.get("pauta") or []:
            id_doc, _ = _referencia_pauta(item, documentos, vinculos)
            if id_doc is None:
                continue
            fase = _normalizar(item.get("fase"))
            if re.search(r"\bleitura\b", fase):
                leituras.setdefault(id_doc, sessao)
            if re.search(r"\bvotacao\b", fase) or fase == "discussao unica":
                votacoes[id_doc].append(sessao)
    tempos = {}
    for id_doc, leitura in sorted(leituras.items()):
        posteriores = [s for s in votacoes[id_doc] if s.get("id") != leitura.get("id")
                       and (s["data"] > leitura["data"] or
                            (s["data"] == leitura["data"] and s.get("hora") and leitura.get("hora")
                             and s["hora"] > leitura["hora"]))]
        votacao = posteriores[0] if posteriores else None
        dias = (date.fromisoformat(votacao["data"]) - date.fromisoformat(leitura["data"])).days if votacao else None
        tempos[id_doc] = {"leitura": leitura["data"], "sessao_leitura": leitura.get("id"),
                         "votacao": votacao["data"] if votacao else None,
                         "sessao_votacao": votacao.get("id") if votacao else None,
                         "ano": leitura["ano"], "dias": dias,
                         "faixa": faixa_leitura_votacao(dias) if dias is not None else "sem par observado",
                         "confiavel": LEITURA_VOTACAO_CONFIAVEL, "motivo": MOTIVO_LEITURA_VOTACAO}
    return tempos


def diagnostico_pautas(sessoes: list[dict], documentos: dict[int, dict]) -> dict:
    """Cobertura por fase/tipo e exemplos de vínculos; não publica mediana enviesada."""
    vinculos = _vinculos_documentos(documentos)
    fases, tipos, especiais, leituras, votacoes = Counter(), Counter(), [], set(), set()
    datas_votacoes: dict[int, set[str]] = defaultdict(set)
    for sessao in sorted(sessoes, key=_chave_sessao):
        for item in sessao.get("pauta") or []:
            id_doc = item.get("id_documento")
            raiz, materia = _referencia_pauta(item, documentos, vinculos)
            fase = _normalizar(item.get("fase"))
            fases[item.get("fase") or "sem fase"] += 1
            tipos[(materia, item.get("fase") or "sem fase")] += 1
            if raiz is not None:
                if fase == "leitura":
                    leituras.add(raiz)
                elif fase in {"votacao", "discussao unica"}:
                    votacoes.add(raiz)
                    datas_votacoes[raiz].add(sessao["data"])
            tipo = item.get("tipo_documento") or (documentos.get(id_doc) or {}).get("tipo") or "não resolvido"
            if id_doc in vinculos or fase == "discussao unica" or re.search(r"veto|emenda|autografo|redacao final", _normalizar(tipo)):
                especiais.append(f"{sessao['data']}, sessão {sessao['id']}: {tipo}, id {id_doc} → {raiz}, fase {item.get('fase')}")
    lacunas = []
    for id_doc in sorted(leituras):
        doc = documentos.get(id_doc)
        for origem, passo in _passos(doc):
            dia = _data_passo(passo)
            if (dia and dia not in datas_votacoes[id_doc]
                    and RE_PLENARIO.search(f"{passo.get('destinatario') or ''} {passo.get('objetivo') or ''}")
                    and re.match(r"(?:aprovad|rejeitad)\w*\b", _normalizar(passo.get("resultado")))):
                lacunas.append(f"id {id_doc}, documento {origem.get('id')}, {dia}: tramitação {passo.get('resultado')!r}, sem fase de votação correspondente na pauta HTML")
    return {"confiavel": False, "motivo": MOTIVO_LEITURA_VOTACAO, "fases": fases, "tipos_fases": tipos,
            "leituras_legislativas": len(leituras), "votacoes_candidatas": len(votacoes),
            "exemplos_vinculos": sorted(set(especiais)), "lacunas_tramitacao": sorted(set(lacunas))}


# ---- pessoas e auditoria -------------------------------------------------------
def indice_nomes(cfg: dict, documentos: list[dict]) -> tuple[dict, dict[str, str]]:
    """Pessoas conhecidas pela configuração/autoria e índice já usado no modelo.

    Inclui suplentes que assinam documentos, mas não cadastra automaticamente os
    nomes vindos das sessões. Não usa nomes de exibição como aliases nem fuzzy.
    O retorno (pessoas, índice) permite listar os não casados antes de propor aliases.
    """
    pessoas = {}
    legs = cfg.get("legislaturas") or []
    completas = [leg for leg in legs if all(k in leg for k in ("inicio", "fim", "id"))]
    for leg in cfg.get("legislaturas") or []:
        for eleito in leg["eleitos"]:
            s = slug(eleito["siscam"])
            pessoa = pessoas.setdefault(s, {"nome_siscam": eleito["siscam"], "nome": eleito["nome"], "legislaturas": set()})
            if leg.get("id"):
                pessoa["legislaturas"].add(leg["id"])
    for nome, exibicao in sorted((cfg.get("apelidos") or {}).items()):
        if not nome.startswith("_"):
            pessoas.setdefault(slug(nome), {"nome_siscam": nome, "nome": exibicao, "legislaturas": set()})
    for doc in documentos:
        leg = legislatura_de(doc.get("data"), doc.get("ano") or 0, completas)
        for autor in doc.get("autoria") or doc.get("autores") or []:
            nome = autor.get("nome") or ""
            if nome and e_autor_vereador_doc(autor, cfg.get("nao_vereador") or []):
                pessoa = pessoas.setdefault(slug(nome), {"nome_siscam": nome, "nome": nome_curto(nome), "legislaturas": set()})
                if leg:
                    pessoa["legislaturas"].add(leg)
    return pessoas, indice_pessoas(pessoas)


def indice_membros(sessao: dict, pessoas: dict, cfg: dict) -> dict[str, str]:
    """Eleitos ou suplentes com autoria de vereador na legislatura, sem inferir pelo rol da sessão.

    Nome desconhecido não prova mandato: fica fora das métricas e na qualidade.
    Apelido de exibição, sozinho, também não comprova exercício numa legislatura.
    Não pretende resolver afastamentos por dia, que exigem outra fonte temporal.
    """
    leg = legislatura_de(sessao.get("data"), sessao["ano"], cfg.get("legislaturas") or [])
    return {nome: pessoa for nome, pessoa in indice_pessoas(pessoas).items()
            if leg and leg in pessoas[pessoa]["legislaturas"]}


def resumo_presencas(
    sessoes: list[dict], indice: dict[str, str] | None = None,
    *, pessoas: dict | None = None, cfg: dict | None = None,
) -> dict[str, dict]:
    """Soma por pessoa: presentes P/C/V, denominador individual, licenças e categorias."""
    resumo = {}
    for sessao in sorted(sessoes, key=_chave_sessao):
        membros = indice_membros(sessao, pessoas, cfg or {}) if pessoas is not None else indice
        for chave, registro in presencas_da_sessao(sessao, membros)["pessoas"].items():
            pessoa = resumo.setdefault(chave, {"nome": registro["nome"], "presentes": 0, "denominador": 0,
                                               "licencas": 0, "categorias": dict.fromkeys(CATEGORIAS_PRESENCA, 0)})
            pessoa["presentes"] += int(registro["presente"])
            pessoa["denominador"] += int(registro["denominador"])
            pessoa["licencas"] += int(registro["licenca"])
            pessoa["categorias"][registro["categoria"]] += 1
    return dict(sorted(resumo.items()))


def _distribuicao(contagem: dict) -> str:
    return ", ".join(f"{chave}: {valor}" for chave, valor in sorted(contagem.items())) or "nenhum"


def auditar(sessoes: list[dict], documentos: dict[int, dict], cfg: dict) -> str:
    """Relatório determinístico por ano; entrada já carregada, sem efeitos colaterais.

    Nomes não casados contam ocorrências brutas em frequência e votos, não pessoas.
    Presença e placares são deduplicados, só com membros da legislatura.
    Leitura→votação é diagnóstico de cobertura, não mediana publicável.
    """
    pessoas, indice = indice_nomes(cfg, [documentos[k] for k in sorted(documentos)])
    tempos = tempos_leitura_votacao(sessoes, documentos)
    saida = [f"Auditoria de sessões — {len(sessoes)} sessões", f"MINIMO_DIVIDIDA decidido: {MINIMO_DIVIDIDA}",
             f"Derrubada de veto: {QUORUM_DERRUBADA_VETO} votos — {ROTULO_QUORUM_VETO}",
             "Presença: P/C/V presentes; L/? fora do denominador individual.",
             "Nomes não casados: ocorrências brutas em frequência e votos (sem fuzzy).",
             f"Leitura→votação: NÃO CONFIÁVEL; fora da fase 1. {MOTIVO_LEITURA_VOTACAO}"]
    por_ano: dict[int, list[dict]] = defaultdict(list)
    for sessao in sessoes:
        por_ano[sessao["ano"]].append(sessao)
    for ano, lista in sorted(por_ano.items()):
        lista = sorted(lista, key=_chave_sessao)
        tipos = Counter(s.get("tipo") or "desconhecido" for s in lista)
        deliberativas = [s for s in lista if s.get("tipo") in TIPOS_DELIBERATIVOS]
        com_lista = sum(bool(s.get("frequencia")) for s in deliberativas)
        categorias, nao_casados, menores, abstencoes = Counter(), Counter(), Counter(), Counter()
        classes = {minimo: Counter() for minimo in range(2, 6)}
        sentidos: dict[str, Counter] = defaultdict(Counter)
        fontes: dict[str, Counter] = defaultdict(Counter)
        indeterminados, inconsistentes, duplicatas, qualidade, notas = [], [], [], [], []
        nominais = 0
        for sessao in lista:
            referencia = f"{sessao.get('titulo') or sessao['id']} [sessão {sessao['id']}, {sessao.get('data')}]"
            membros = indice_membros(sessao, pessoas, cfg)
            presencas = presencas_da_sessao(sessao, membros)
            categorias.update(p["categoria"] for p in presencas["pessoas"].values())
            qualidade.extend(f"{referencia}: {m}" for m in presencas["qualidade"])
            if not legislatura_de(sessao.get("data"), ano, cfg.get("legislaturas") or []):
                qualidade.append(f"{referencia}: sem legislatura correspondente")
            if data_valida(sessao.get("data")) and int(sessao["data"][:4]) != ano:
                qualidade.append(f"{referencia}: data fora do ano da listagem {ano}")
            for repetida in presencas["duplicatas"]:
                duplicatas.append(f"{referencia}: frequência {repetida['nome']} ({repetida['linhas']} linhas) → {repetida['categoria']}")
            linhas_nomes = list(sessao.get("frequencia") or [])
            for votacao in sessao.get("votacoes") or []:
                linhas_nomes.extend(votacao.get("votos") or [])
                documento = votacao.get("documento") or f"id {votacao.get('id_documento')}"
                ref_voto = f"{referencia}, {documento}"
                if not votacao_nominal(votacao):
                    if _normalizar(votacao.get("tipo_votacao")) == "nominal":
                        qualidade.append(f"{ref_voto}: nominal sem votos")
                    continue
                dedup = deduplicar_votos(votacao, membros)
                qualidade.extend(f"{ref_voto}: {m}" for m in dedup["qualidade"])
                if not dedup["votos"]:
                    qualidade.append(f"{ref_voto}: sem votos de membros; fora das métricas")
                    continue
                nominais += 1
                totais = dedup["totais"]
                menores[min(totais["favor"], totais["contra"])] += 1
                abstencoes[totais["abstencao"]] += 1
                for minimo, contagem in classes.items():
                    contagem[classe_votacao(totais, minimo)] += 1
                for repetida in dedup["duplicatas"]:
                    duplicatas.append(f"{ref_voto}: {repetida['nome']} ({repetida['linhas']} linhas) → {repetida['voto']}")
                for chave, valor in (votacao.get("totais") or {}).items():
                    if chave in totais and valor is not None and valor != totais[chave]:
                        qualidade.append(f"{ref_voto}: total publicado {chave}={valor} ≠ deduplicado {totais[chave]}")
                analise = sentido_voto(votacao, sessao, documentos.get(votacao.get("id_documento")), indice=membros)
                sentidos[analise["materia"]][analise["sentido"]] += 1
                categoria_fonte = analise["fonte"] if analise["sentido"] not in {"indeterminado", "inconsistente"} else analise["sentido"]
                fontes[analise["materia"]][categoria_fonte] += 1
                notas.extend(f"{ref_voto}: {nota}" for nota in analise["notas"])
                motivos = "; ".join(analise["motivos"])
                if analise["sentido"] == "indeterminado":
                    indeterminados.append(f"{ref_voto} ({analise['materia']}): {motivos}")
                elif analise["sentido"] == "inconsistente":
                    inconsistentes.append(f"{ref_voto}: {motivos}")
            for linha in linhas_nomes:
                if slug(linha["nome"]) not in indice:
                    nao_casados[linha["nome"]] += 1
        resumo = resumo_presencas(lista, pessoas=pessoas, cfg=cfg)
        coorte = [t for t in tempos.values() if t["ano"] == ano]
        duracoes = [t["dias"] for t in coorte if t["dias"] is not None]
        saida.extend(["", f"=== {ano} ===", f"Sessões por tipo: {_distribuicao(tipos)}",
                      f"Deliberativas com lista: {com_lista}; sem lista: {len(deliberativas) - com_lista}",
                      "Presença por pessoa/sessão: " + ", ".join(f"{c} ({rotulo}): {categorias[c]}" for c, rotulo in CATEGORIAS_PRESENCA.items()),
                      f"Base individual somada: {sum(p['denominador'] for p in resumo.values())}; presentes: {sum(p['presentes'] for p in resumo.values())}; licenças: {sum(p['licencas'] for p in resumo.values())}",
                      f"Nomes não casados: {_distribuicao(nao_casados)}", f"Votações nominais com votos: {nominais}",
                      f"Distribuição de menor=min(Favor, Contra): {_distribuicao(menores)}",
                      f"Distribuição de abstenções: {_distribuicao(abstencoes)}"])
        for minimo, contagem in classes.items():
            saida.append(f"Classes com minimo={minimo}: " + ", ".join(f"{c}: {contagem[c]}" for c in ("unanime", "dissenso", "dividida")))
        for materia, contagem in sorted(sentidos.items()):
            saida.append(f"Sentidos — {materia}: {_distribuicao(contagem)}")
            saida.append(f"Fontes — {materia}: resultado oficial: {fontes[materia]['resultado_oficial']}; "
                         f"texto (veto ambíguo): {fontes[materia]['texto_veto_ambiguo']}; "
                         f"curadoria: {fontes[materia]['curadoria']}; indeterminados: {fontes[materia]['indeterminado']}; "
                         f"inconsistentes: {fontes[materia]['inconsistente']}")
        for titulo, itens in (("Indeterminados (motivos)", indeterminados), ("Inconsistentes", inconsistentes),
                              ("Notas de conferência (sem excluir)", notas),
                              ("Duplicatas resolvidas (por pessoa/grupo)", duplicatas), ("Qualidade / avisos", qualidade)):
            saida.append(f"{titulo}: {len(itens)}")
            saida.extend(f"  - {item}" for item in sorted(itens))
        diagnostico = diagnostico_pautas(lista, documentos)
        saida.extend([f"Pauta — fases brutas: {_distribuicao(diagnostico['fases'])}",
                      "Pauta — tipo/fase: " + _distribuicao({f"{m}/{f}": n for (m, f), n in diagnostico["tipos_fases"].items()}),
                      f"Leitura→votação NÃO CONFIÁVEL: pares candidatos {len(duracoes)} / leituras legislativas {len(coorte)}; sem mediana nem taxa de 'não pautado'.",
                      f"Vínculos especiais/Discussão Única: {len(diagnostico['exemplos_vinculos'])} exemplos"])
        saida.extend(f"  - {exemplo}" for exemplo in diagnostico["exemplos_vinculos"])
        saida.append(f"Passos de votação sem fase correspondente na pauta HTML: {len(diagnostico['lacunas_tramitacao'])}; primeiros 5 exemplos:")
        saida.extend(f"  - {exemplo}" for exemplo in diagnostico["lacunas_tramitacao"][:5])
    return "\n".join(saida) + "\n"


# ---- entrada de linha de comando (somente leitura) ------------------------------
def carregar_fontes(raiz: Path = RAIZ) -> tuple[list[dict], dict[int, dict], dict]:
    """Lê sessões, PLs/substitutivos, documentos e configuração; falhas não são ocultadas."""
    cfg = json.loads((raiz / "config" / "vereadores.json").read_text(encoding="utf-8"))
    sessoes, documentos = [], {}
    for arquivo in sorted((raiz / "data" / "sessoes").glob("*.json")):
        sessoes.extend(json.loads(arquivo.read_text(encoding="utf-8")))
    arquivos = sorted([*(raiz / "data" / "proposicoes").glob("*.json"),
                       *(raiz / "data" / "documentos").glob("*/*.json")])
    for arquivo in arquivos:
        tipo = "pl" if arquivo.parent.name == "proposicoes" else arquivo.parent.name
        for registro in json.loads(arquivo.read_text(encoding="utf-8")):
            documentos[registro["id"]] = {**registro, "tipo": tipo}
            for substitutivo in registro.get("substitutivos") or []:
                documentos[substitutivo["id"]] = {**substitutivo, "tipo": "pl"}
    return sessoes, documentos, cfg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auditoria", action="store_true", help="imprime distribuições e problemas dos dados versionados")
    args = parser.parse_args(argv)
    if not args.auditoria:
        parser.print_help()
        return 0
    try:
        print(auditar(*carregar_fontes()), end="")
    except (OSError, ValueError) as erro:
        print(f"Não foi possível auditar as sessões: {erro}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
