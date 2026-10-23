"""Classificação por regras das demais proposituras coletadas do SISCAM.

Recebe registros de data/documentos/<tipo>/<ano>.json (gerados por
coletor.documentos) e atribui categoria e subcategoria pela ementa normalizada
(maiúsculas, sem acentos e sem pontuação), além de marcas da situação e, nas
indicações, do bairro citado. O "assunto" da listagem (rótulo curto do SISCAM,
como "TAPA BURACO" ou "DECRETO/MEDALHA") só desempata quando a ementa não basta.
É determinística, sem IA e sem rede: o mesmo registro recebe sempre a mesma
classificação, e as regras valem igualmente para qualquer autor, partido ou
espectro político.

Também deriva, da tramitação completa da página de detalhe, a data em que um
requerimento consta como respondido e o número e a data de publicação de PDLs e
resoluções (derivar_resposta e derivar_publicacao).

É a única fonte das regras usadas nas métricas do site: os eixos do perfil de
atuação (eixos_perfil), o órgão citado num requerimento de informação
(extrair_orgao) e o estado desse pedido para a taxa de resposta (estado_pedido).
coletor.site.modelo só agrega o que estas funções devolvem.

Categorias:
  zeladoria     indicações (pedidos de serviço ao Executivo)
  fiscalizacao  requerimentos de informação
  homenagem     moções de aplauso ou de pesar; títulos, medalhas, diplomas e prêmios
  manifestacao  demais moções (repúdio, apoio e outras)
  legislacao    PDL e resoluções que não são homenagem
  outra         demais requerimentos
Somente biblioteca padrão do Python.
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata

CATEGORIAS = ("zeladoria", "fiscalizacao", "homenagem", "manifestacao", "legislacao", "outra")
SUBCATEGORIAS = {
    "indicacao": ("iluminacao", "asfalto", "poda", "limpeza", "saneamento", "transito", "outra"),
    "requerimento": ("informacao", "outro"),
    "mocao": ("aplauso", "pesar", "repudio", "apoio", "outra"),
    "pdl": ("titulo_cidadao", "honraria", "outra"),
    "resolucao": ("honraria", "regimento", "administrativa", "outra"),
}
EIXOS_PERFIL = ("zeladoria", "fiscalizacao", "homenagem", "legislacao")


# ------------------------------------------------------------------ normalização
def _sem_acento(texto: str | None) -> str:
    """Maiúsculas e sem acentos, mantendo a pontuação ("Nº 3.167/2025" vira "NO 3.167/2025")."""
    decomposto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in decomposto if not unicodedata.combining(c)).upper()


def normalizar(texto: str | None) -> str:
    """Maiúsculas, sem acentos, só letras, dígitos e espaços simples ("Nº" vira "NO")."""
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", _sem_acento(texto)).split())


def _regex(*termos: str) -> re.Pattern[str]:
    """Alternativas de termos já normalizados, com fronteira de palavra."""
    return re.compile(r"\b(?:" + "|".join(termos) + r")\b")


def _mais_cedo(texto: str, regras: tuple[tuple[str, re.Pattern[str]], ...]) -> str | None:
    """Regra cujo termo aparece primeiro na ementa; empate fica com a ordem das regras.

    A ementa costuma nomear o serviço ou o tipo de moção logo no início; termos
    usados só como referência de lugar ("em frente ao bueiro") vêm depois.
    """
    melhor: tuple[int, int, str] | None = None
    for ordem, (nome, padrao) in enumerate(regras):
        m = padrao.search(texto)
        if m and (melhor is None or (m.start(), ordem) < melhor[:2]):
            melhor = (m.start(), ordem, nome)
    return melhor[2] if melhor else None


# ---------------------------------------------------------------------- bairros
# Os 52 bairros oficiais de Niterói, pelas cinco regiões de planejamento. É a única
# cópia da lista no código: BAIRROS_NITEROI deriva dela.
BAIRROS_POR_REGIAO: dict[str, tuple[str, ...]] = {
    "Praias da Baía": (
        "Boa Viagem", "Cachoeira", "Centro", "Charitas", "Fátima", "Gragoatá", "Icaraí", "Ingá", "Jurujuba",
        "Morro do Estado", "Pé Pequeno", "Ponta d'Areia", "Santa Rosa", "São Domingos", "São Francisco",
        "Viradouro", "Vital Brazil",
    ),
    "Norte": (
        "Baldeador", "Barreto", "Caramujo", "Cubango", "Engenhoca", "Fonseca", "Ilha da Conceição",
        "Santa Bárbara", "Santana", "São Lourenço", "Tenente Jardim", "Viçoso Jardim",
    ),
    "Pendotiba": (
        "Badu", "Cantagalo", "Ititioca", "Largo da Batalha", "Maceió", "Maria Paula", "Matapaca", "Sapê",
        "Vila Progresso",
    ),
    "Oceânica": (
        "Cafubá", "Camboinhas", "Engenho do Mato", "Itacoatiara", "Itaipu", "Jacaré", "Jardim Imbuí",
        "Maravista", "Piratininga", "Santo Antônio", "Serra Grande",
    ),
    "Leste": ("Muriqui", "Rio do Ouro", "Várzea das Moças"),
}
BAIRROS_NITEROI: tuple[str, ...] = tuple(b for bairros in BAIRROS_POR_REGIAO.values() for b in bairros)
# Grafias alternativas. A comparação já ignora acentos, maiúsculas e pontuação:
# "Icarai", "ICARAÍ" e "Ponta D’Areia" casam sem precisar de variante.
VARIANTES_BAIRROS: dict[str, tuple[str, ...]] = {
    "Ponta d'Areia": ("Ponta da Areia", "Ponta Dareia"),
    "Vital Brazil": ("Vital Brasil",),
    "Jardim Imbuí": ("Imbuí",),
    "Maravista": ("Mara Vista",),
}
# Usos que não são o bairro: (restrição antes, restrição depois), sobre o texto normalizado.
RESTRICOES_BAIRROS: dict[str, tuple[str, str]] = {
    # "Centro de Saúde", "Centro Municipal de Educação Infantil", "Centro POP" (Centro de
    # Referência para a População em Situação de Rua)...; "Centro de Niterói" vale
    "Centro": (
        "",
        r"(?!\s(?:DE|DO|DA|DOS|DAS)\s(?!NITEROI\b|CIDADE\b))"
        r"(?!\s(?:MUNICIPAL|CULTURAL|ESPORTIVO|POLIESPORTIVO|COMUNITARIO|INTEGRADO|ESPECIALIZADO|POPULAR|POP"
        r"|EDUCACIONAL|SOCIAL|ADMINISTRATIVO|COMERCIAL|EMPRESARIAL|ESPIRITA|OLIMPICO)\b)",
    ),
    # "Nossa Senhora de Fátima" é nome de igreja, escola ou rua
    "Fátima": (r"(?<!SENHORA DE )(?<!SRA DE )(?<!N S DE )", ""),
}


def _padrao_bairro(nome: str) -> re.Pattern[str]:
    formas = {normalizar(nome), *(normalizar(v) for v in VARIANTES_BAIRROS.get(nome, ()))}
    alternativas = "|".join(re.escape(f) for f in sorted(formas, key=lambda f: (-len(f), f)))
    antes, depois = RESTRICOES_BAIRROS.get(nome, ("", ""))
    return re.compile(antes + r"\b(?:" + alternativas + r")\b" + depois)


_PADROES_BAIRROS = tuple((nome, _padrao_bairro(nome)) for nome in BAIRROS_NITEROI)


def extrair_bairro(texto: str | None) -> str | None:
    """Último bairro oficial citado no texto (nome canônico, com acentos), ou None.

    As indicações costumam terminar com "Rua X (em frente ao nº 20), Bairro – Niterói";
    por isso vale a última menção, e não a primeira (que pode ser sub-bairro ou rua).
    """
    norm = normalizar(texto)
    melhor: tuple[tuple[int, int], str] | None = None
    for nome, padrao in _PADROES_BAIRROS:
        for m in padrao.finditer(norm):
            chave = (m.end(), -m.start())  # mais à direita; no empate, a forma mais longa
            if melhor is None or chave > melhor[0]:
                melhor = (chave, nome)
    return melhor[1] if melhor else None


# ------------------------------------------------------------------------ regras
REGRAS_INDICACAO: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("iluminacao", _regex(
        r"ILUMINAC\w*", r"LAMPADAS?", r"LUMINARIAS?", r"REFLETOR\w*", r"POSTES? DE LUZ", r"LUZ(?:ES)? APAGADAS?",
    )),
    ("asfalto", _regex(
        r"TAPA BURACOS?", r"BURACOS?", r"ASFALT\w*", r"PAVIMENTAC\w*", r"PAVIMENTO", r"RECAPE\w*",
        r"CALCAMENTO", r"PARALELEPIPEDOS?", r"CRATERAS?",
    )),
    ("poda", _regex(r"PODAS?", r"PODAR", r"ARVORES?", r"GALHOS?", r"ARBORIZAC\w*")),
    ("limpeza", _regex(
        r"LIMPEZA", r"LIMPAR", r"CAPINA\w*", r"ROCADA\w*", r"ROCAGEM", r"LIXO\w*", r"LIXEIRAS?", r"ENTULHOS?",
        r"VARRICAO", r"VARREDURA", r"CACAMBAS?", r"(?<!ENGENHO DO )MATO",
    )),
    ("saneamento", _regex(
        r"SANEAMENTO", r"ESGOTO\w*", r"BUEIROS?", r"GALERIAS?", r"DRENAGEM", r"MANILHAS?", r"VAZAMENTOS?",
        r"ALAGAMENTOS?", r"BOCAS? DE LOBO", r"BOCAS? DE LEAO", r"CANALETAS?", r"VALAS?", r"VALAO",
        r"CORREGOS?", r"PLUVIA\w*", r"DESOBSTRUC\w*", r"DRAGAGEM", r"ASSOREAMENTO", r"(?:FALTA|ABASTECIMENTO) DE AGUA",
    )),
    ("transito", _regex(
        r"TRANSITO", r"SINALIZAC\w*", r"SEMAFOR\w*", r"FAIXAS? DE PEDESTRES?", r"FAIXAS? ELEVADAS?",
        r"QUEBRA MOLAS?", r"REDUTOR\w*", r"LOMBADAS?", r"PLACAS?", r"ESTACIONAMENTO\w*", r"PONTOS? DE ONIBUS",
        r"ABRIGOS? DE ONIBUS", r"ONIBUS", r"TRAVESSIAS?", r"PEDESTRES?", r"MAO (?:DUPLA|UNICA)", r"RADAR\w*",
        r"CICLOVIAS?", r"CICLOFAIXAS?", r"ROTATORIAS?",
    )),
)

REGRAS_MOCAO: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aplauso", _regex(
        r"APLAUSOS?", r"CONGRATULA\w*", r"LOUVOR\w*", r"PARABENIZ\w*", r"PARABENS", r"ELOGIOS?",
        r"HONRA AO MERITO", r"RECONHECIMENTO", r"AGRADECIMENTOS?", r"HOMENAG\w*",
    )),
    ("pesar", _regex(
        r"PESAR(?:ES)?", r"FALECIMENTOS?", r"CONDOLENCIAS?", r"LUTO", r"IN MEMORIAM", r"PASSAMENTO", r"OBITOS?",
    )),
    ("repudio", _regex(r"REPUDI\w*", r"PROTESTOS?", r"CENSURA")),
    ("apoio", _regex(r"APOI\w*", r"SOLIDARI\w*", r"ADESAO")),
)

# PDL ou resolução que derruba ato anterior não é homenagem, mesmo citando o título
RE_SUSTACAO = _regex(
    r"SUSTA(?:R|M|CAO)?", r"REVOGA(?:R|M|CAO)?", r"TORNA(?:R)? SEM EFEITO", r"ANULA(?:R|CAO)?", r"CASSA(?:R|CAO)?",
)
RE_TITULO_CIDADAO = re.compile(
    r"\bTITULOS?\s(?:HONORARIOS?\s)?DE\sCIDAD(?:AO|A|AOS|AS|ANIA)\b"
    r"|\bCIDAD(?:AO|A|AOS|AS|ANIA)\s(?:HONORARI[OA]S?\s)?(?:NITEROIENSES?|BENEMERIT[OA]S?|HONORARI[OA]S?)\b"
)
# sem "TITULO" solto: nas resoluções ele aparece como divisão do Regimento ("Título IV")
RE_HONRARIA = _regex(
    r"MEDALHAS?", r"DIPLOMAS?", r"COMENDAS?", r"HONRARIAS?", r"PREMIOS?", r"PREMIACAO", r"LAUREAS?", r"TROFEUS?",
    r"HONRA AO MERITO", r"HOMENAG\w*", r"TITULOS? HONORIFICOS?", r"TITULOS? HONORARIOS?", r"TITULOS? DE CIDAD\w*",
)
RE_TITULO = _regex(r"TITULOS?")
# o Regimento Interno da Câmara é a Resolução nº 2.181/1992
RE_REGIMENTO = re.compile(r"\bREGIMENTO\b|\bRESOLUCAO\s(?:NO?\s)?2\s?181\b")
RE_ADMINISTRATIVA = _regex(
    r"CAMARA", r"ORCAMENT\w*", r"SERVIDOR\w*", r"CARGOS?", r"COMISSAO", r"COMISSOES", r"FRENTES? PARLAMENTAR\w*",
    r"ESTRUTURA\w*", r"PESSOAL", r"SECRETARIAS?", r"PROCURADORIA", r"OUVIDORIA", r"CONTRATAC\w*", r"LICITAC\w*",
    r"MESA DIRETORA", r"TRABALHO REMOTO", r"EXPEDIENTE", r"SESSAO", r"SESSOES", r"ADMINISTRATIV\w*",
    r"FUNCIONAMENTO", r"LEGISLATIV\w*", r"RESOLUCAO",
)
RE_INFORMACAO = re.compile(
    r"\b(?:REQUER\w*|SOLICIT\w*|PEDIDOS?|PEDE)\b(?:\s\w+){0,12}?\sINFORMAC(?:AO|OES)\b"
    r"|\bQUE\s(?:SEJA\s|SEJAM\s)?INFORM\w*"
    r"|\b(?:INTEGRA|COPIAS?)\sD[OA]S?\s(?:PROCESSO|PROCEDIMENTO|CONTRATO|CONVENIO|DOCUMENTO)\w*"
)
# Termos do "assunto" da listagem que não deixam dúvida. O assunto só é consultado
# quando a ementa cai na subcategoria padrão; "TÍTULO" solto fica de fora porque o
# SISCAM usa "DECRETO/TÍTULO" também em PDL que susta um título já concedido.
RE_ASSUNTO_INFORMACAO = _regex(r"INFORMAC(?:AO|OES)")
RE_ASSUNTO_ADMINISTRATIVA = _regex(r"LOA", r"ORCAMENT\w*", r"FRENTES? PARLAMENTAR\w*", r"MESA DIRETORA")


# ------------------------------------------------------------------- classificação
def classificar_documento(registro: dict) -> dict:
    """Categoria, subcategoria e marcas de um documento, só a partir dos seus campos.

    Usa "tipo", "ementa", "situacao" e, quando existem, "assunto", "respondido_em" e
    "ultima_tramitacao". A ementa prevalece: o assunto só decide quando nenhuma regra
    da ementa se aplica, e nunca vence uma sustação ou revogação citada na ementa.
    "respondido" vale só para requerimentos (veja consta_respondido); "bairro" só é
    procurado nas indicações.
    """
    tipo = registro.get("tipo")
    texto = normalizar(registro.get("ementa"))
    assunto = normalizar(registro.get("assunto"))
    if RE_SUSTACAO.search(assunto):
        assunto = ""
    bairro = None
    if tipo == "indicacao":
        subcategoria = _mais_cedo(texto, REGRAS_INDICACAO) or _mais_cedo(assunto, REGRAS_INDICACAO) or "outra"
        categoria = "zeladoria"
        bairro = extrair_bairro(registro.get("ementa"))
    elif tipo == "requerimento":
        informacao = RE_INFORMACAO.search(texto) or RE_ASSUNTO_INFORMACAO.search(assunto)
        subcategoria = "informacao" if informacao else "outro"
        categoria = "fiscalizacao" if subcategoria == "informacao" else "outra"
    elif tipo == "mocao":
        subcategoria = _mais_cedo(texto, REGRAS_MOCAO) or _mais_cedo(assunto, REGRAS_MOCAO) or "outra"
        categoria = "homenagem" if subcategoria in ("aplauso", "pesar") else "manifestacao"
    elif tipo == "pdl":
        if RE_SUSTACAO.search(texto):
            subcategoria = "outra"
        elif RE_TITULO_CIDADAO.search(texto):
            subcategoria = "titulo_cidadao"
        elif RE_HONRARIA.search(texto) or RE_TITULO.search(texto):
            subcategoria = "honraria"
        elif RE_TITULO_CIDADAO.search(assunto):  # assunto "CIDADÃO NITEROIENSE", "CIDADÃO BENEMÉRITO"
            subcategoria = "titulo_cidadao"
        elif RE_HONRARIA.search(assunto):  # assunto "DECRETO/MEDALHA", "HOMENAGEM"
            subcategoria = "honraria"
        else:
            subcategoria = "outra"
        categoria = "legislacao" if subcategoria == "outra" else "homenagem"
    elif tipo == "resolucao":
        sustacao = bool(RE_SUSTACAO.search(texto))
        if not sustacao and RE_HONRARIA.search(texto):
            subcategoria = "honraria"  # vale mesmo quando a honraria é criada alterando o Regimento
        elif RE_REGIMENTO.search(texto):
            subcategoria = "regimento"
        elif RE_ADMINISTRATIVA.search(texto):
            subcategoria = "administrativa"
        elif not sustacao and RE_HONRARIA.search(assunto):
            subcategoria = "honraria"
        elif RE_REGIMENTO.search(assunto):
            subcategoria = "regimento"
        elif RE_ASSUNTO_ADMINISTRATIVA.search(assunto):
            subcategoria = "administrativa"
        else:
            subcategoria = "outra"
        categoria = "homenagem" if subcategoria == "honraria" else "legislacao"
    else:
        raise ValueError(f"tipo de documento desconhecido: {tipo!r}")
    situacao = normalizar(registro.get("situacao"))
    return {
        "categoria": categoria,
        "subcategoria": subcategoria,
        "homenagem": categoria == "homenagem",
        "respondido": tipo == "requerimento" and consta_respondido(registro),
        "publicado": situacao.startswith("PUBLICAD"),
        "bairro": bairro,
    }


# ------------------------------------------------------- derivações da tramitação
RE_RESPONDIDO = re.compile(r"(?<!NAO )\bRESPONDID[OA]S?\b")


def consta_respondido(registro: dict) -> bool:
    """Se algum dos sinais disponíveis indica que o documento foi respondido.

    Basta um: a situação começa com "RESPONDID", a tramitação completa do detalhe dá
    "respondido_em" ou o último passo da listagem tem objetivo ou resultado
    "Respondido" (sem acento nem caixa; "Não respondido" não conta). A situação nem
    sempre acompanha a tramitação: o requerimento 70/2026 (id 294244) seguia
    "ENCAMINHADO À PREFEITURA" com o último passo "Respondido".
    """
    if normalizar(registro.get("situacao")).startswith("RESPONDID") or registro.get("respondido_em"):
        return True
    passo = registro.get("ultima_tramitacao")
    if not isinstance(passo, dict):
        return False
    return any(RE_RESPONDIDO.search(normalizar(passo.get(c))) for c in ("objetivo", "resultado"))
RE_PUBLICADO = re.compile(r"(?<!NAO )\bPUBLICAD[OA]S?\b")
# "RESOLUÇÃO Nº 3167/2025", "DECRETO LEGISLATIVO N° 3993/2025"; não "PROJETO DE RESOLUÇÃO Nº 22/2025"
RE_ATO = re.compile(r"(?<!PROJETO DE )\b(?:RESOLUCAO|DECRETO\s+LEGISLATIVO)\s*(?:N[O°.]*\s*)?(\d[\d.]*)")
RE_DATA = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")


def _dias(inicio: str | None, fim: str | None) -> int | None:
    """Dias entre duas datas ISO; None se faltar uma delas, se forem inválidas ou se fim < início."""
    if not inicio or not fim:
        return None
    try:
        dias = (dt.date.fromisoformat(fim) - dt.date.fromisoformat(inicio)).days
    except ValueError:
        return None
    return dias if dias >= 0 else None


def derivar_resposta(registro: dict) -> dict:
    """Data em que a tramitação de um requerimento registra a resposta e os dias até ela.

    "respondido_em" é a data "enviado" do primeiro passo cujo objetivo ou resultado
    indica "Respondido" (sem acento nem caixa); None se nenhum passo indicar.
    "dias_ate_resposta" conta do protocolo (ou, sem ele, da data do documento) até
    "respondido_em"; None sem resposta ou com datas incoerentes. A "Data Resposta"
    dos passos não entra: ela aparece em passos de todo tipo e, sozinha, não é a data
    em que o Executivo respondeu.
    """
    respondido_em = None
    for passo in registro.get("tramitacoes") or []:
        indica = any(RE_RESPONDIDO.search(normalizar(passo.get(c))) for c in ("objetivo", "resultado"))
        if indica and passo.get("enviado"):
            respondido_em = passo["enviado"]
            break
    inicio = registro.get("data_protocolo") or registro.get("data")
    return {"respondido_em": respondido_em, "dias_ate_resposta": _dias(inicio, respondido_em)}


def _numero_ato(passo: dict) -> int | None:
    """Número do decreto legislativo ou da resolução citado na observação ou no complemento."""
    for chave in ("observacao", "complemento"):
        m = RE_ATO.search(_sem_acento(passo.get(chave)))
        if m:
            return int(m.group(1).replace(".", ""))
    return None


def derivar_publicacao(tramitacoes: list[dict] | None) -> dict | None:
    """Número do ato e data da publicação de um PDL ou resolução, pela tramitação completa.

    Usa o passo cujo resultado indica "Publicado", mesmo que não seja o último (depois
    dele pode vir o arquivamento); havendo mais de um, o primeiro que cita o número do
    ato. "numero" vem da observação (ex.: "RESOLUÇÃO Nº 3167/2025, NO JORNAL ...") e
    "data" é a "Data Resposta" desse passo ou, sem ela, a data citada na observação.
    None se nenhum passo indicar publicação.
    """
    publicados = [p for p in tramitacoes or [] if RE_PUBLICADO.search(normalizar(p.get("resultado")))]
    if not publicados:
        return None
    passo = next((p for p in publicados if _numero_ato(p) is not None), publicados[0])
    data = passo.get("data_resposta")
    if not data:
        m = RE_DATA.search(passo.get("observacao") or "")
        data = f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None
    return {"numero": _numero_ato(passo), "data": data}


# ------------------------------------------------------------------------ perfil
def eixos_perfil(classificacao: dict) -> list[str]:
    """Eixos do perfil de atuação (EIXOS_PERFIL) em que um documento conta.

    Recebe o resultado de classificar_documento ou qualquer dicionário com "categoria"
    e "homenagem", como os documentos do modelo do site (coletor.site.modelo, que só
    agrega). Zeladoria, fiscalização e legislação seguem a categoria; homenagem segue a
    marca "homenagem": moções de aplauso (inclui congratulação e louvor) e de pesar,
    títulos de cidadão e honrarias em PDLs e resoluções. Manifestação (repúdio, apoio
    e outras moções) e "outra" (demais requerimentos) não entram no perfil.
    """
    eixos = [e for e in ("zeladoria", "fiscalizacao", "legislacao") if classificacao["categoria"] == e]
    if classificacao["homenagem"]:
        eixos.append("homenagem")
    return eixos


# ------------------------------------------------------- requerimentos de informação
# Órgão a que se dirige um requerimento de informação, só pela ementa e, sem resultado,
# pelo "assunto" da listagem (que às vezes é o próprio órgão, como "NITTRANS"). O
# destinatário dos passos da tramitação não serve: é o caminho dentro da Câmara
# (Plenário, Secretaria Mesa Diretora) e, no envio, quase sempre a Secretaria Municipal
# de Governo, que repassa o pedido ao órgão responsável.
ORGAO_NAO_IDENTIFICADO = "Não identificado"
ORGAO_EXECUTIVO = "Prefeito ou Poder Executivo"
ORGAO_OUTRA_SECRETARIA = "Outra secretaria municipal"
ORGAO_ESTADUAL = "Governo do Estado ou órgão estadual"
ORGAO_CONCESSIONARIA = "Concessionária não especificada"
# Área depois de "Secretaria (Municipal) de": primeiro as duas primeiras palavras, depois
# só a primeira; a área que não está aqui vira "Outra secretaria municipal".
SECRETARIAS: dict[str, str] = {
    "SAUDE": "Secretaria de Saúde",
    "EDUCACAO": "Secretaria de Educação",
    "OBRAS": "Secretaria de Obras",
    "CONSERVACAO": "Secretaria de Conservação e Serviços Públicos",
    "URBANISMO": "Secretaria de Urbanismo e Mobilidade",
    # Nomes mudam entre gestões e os dados não dizem se "Mobilidade Urbana" e "Urbanismo e
    # Mobilidade" são o mesmo órgão: ficam separados, com o nome citado.
    "MOBILIDADE URBANA": "Secretaria de Mobilidade Urbana",
    "MOBILIDADE": "Secretaria de Mobilidade",
    "MEIO AMBIENTE": "Secretaria de Meio Ambiente",
    "ASSISTENCIA": "Secretaria de Assistência Social",
    "FAZENDA": "Secretaria de Fazenda",
    "PLANEJAMENTO": "Secretaria de Planejamento",
    "GOVERNO": "Secretaria de Governo",
    "ORDEM PUBLICA": "Secretaria de Ordem Pública",
    "ADMINISTRACAO": "Secretaria de Administração",
    "CULTURA": "Secretaria das Culturas",
    "CULTURAS": "Secretaria das Culturas",
    "ESPORTE": "Secretaria de Esporte e Lazer",
    "ESPORTES": "Secretaria de Esporte e Lazer",
    "HABITACAO": "Secretaria de Habitação",
    "DEFESA CIVIL": "Defesa Civil",
    "DIREITOS HUMANOS": "Secretaria de Direitos Humanos",
    "DESENVOLVIMENTO ECONOMICO": "Secretaria de Desenvolvimento Econômico",
    "TURISMO": "Secretaria de Turismo",
    "CIENCIA": "Secretaria de Ciência e Tecnologia",
    "TRABALHO": "Secretaria de Trabalho",
    "MULHER": "Secretaria da Mulher",
    "MULHERES": "Secretaria da Mulher",
    "IDOSO": "Secretaria do Idoso",
    "ACESSIBILIDADE": "Secretaria de Acessibilidade",
    "SEGURANCA": "Secretaria de Segurança",
    "COMUNICACAO": "Secretaria de Comunicação",
    "JUVENTUDE": "Secretaria de Juventude",
    "PARTICIPACAO": "Secretaria de Participação Social",
    "EXECUTIVA": "Secretaria Executiva",
}
# Depois de "Secretaria": da Câmara (não é órgão do Executivo), federal ou sem área definida.
_SECRETARIA_IGNORADA = {"MESA", "CAMARA", "NACIONAL", "ESPECIAL", "DE", "DA", "DO", "DAS", "DOS"}
_SECRETARIA_GENERICA = {"COMPETENTE", "COMPETENTES", "RESPONSAVEL", "RESPONSAVEIS", "PERTINENTE", "PERTINENTES",
                        "MUNICIPAL", "MUNICIPAIS"}
_SECRETARIA_ESTADUAL = {"ESTADO", "ESTADUAL", "ESTADUAIS"}
# Grupos: conector ("de", "da"...), área e a palavra seguinte. Área fora de SECRETARIAS só
# vale depois do conector: em "ao Secretário Municipal, Sr. Fulano" ou "à Secretaria
# Municipal e à Fundação" a palavra seguinte ("SR", "E") não é área.
RE_SECRETARIA = re.compile(r"\bSECRETARI(?:A|O|AS|OS)\s(?:MUNICIPA(?:L|IS)\s)?(?:(D[AEO]S?)\s)?([A-Z]+)(?:\s([A-Z]+))?")
# Órgão estadual só conta como destinatário: depois de "a", "ao" ou "junto ao", antes do
# assunto ("sobre", "acerca"...). Citado em outro papel ("baixa junto ao Detran-RJ" no
# meio do pedido), indica só o Executivo municipal, que é quem responde ao requerimento.
_ESTADUAL = (r"(?:GOVERNO DO ESTADO|GOVERNADOR[A]?|SECRETARI(?:A|O|AS|OS)\s(?:DE\s)?ESTADO"
             r"|SECRETARI(?:A|O|AS|OS)\sESTADUA(?:L|IS)|DETRAN|CEDAE|INEA)")
RE_ESTADUAL = re.compile(r"\b" + _ESTADUAL + r"\b")
RE_ESTADUAL_DESTINO = re.compile(
    r"\b(?:A|AO|AOS|AS|JUNTO AO|JUNTO A)\s(?:(?:EXMO|EXMA|EXCELENTISSIM[OA]|SR|SRA|SENHOR[A]?)\s)*" + _ESTADUAL + r"\b"
)
RE_FIM_DESTINO = _regex(r"SOBRE", r"ACERCA", r"A RESPEITO", r"REFERENTES?", r"QUANTO", r"RELATIV\w*", r"EM RELACAO")
# Órgãos com nome próprio e siglas sem ambiguidade; "AMPLA" fica de fora (é adjetivo comum).
ORGAOS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Secretaria de Conservação e Serviços Públicos", _regex(r"SECONSER")),
    ("Secretaria de Governo", _regex(r"SEMUG")),
    ("Secretaria de Planejamento", _regex(r"SEPLAG")),
    ("Secretaria de Ordem Pública", _regex(r"SEOP")),
    ("Secretaria de Meio Ambiente", _regex(r"SMARHS")),
    ("Fundação Municipal de Saúde", _regex(r"FUNDACAO MUNICIPAL DE SAUDE")),
    ("Fundação Municipal de Educação", _regex(r"FUNDACAO MUNICIPAL DE EDUCACAO", r"FME")),
    ("Fundação de Arte de Niterói", _regex(r"FUNDACAO DE ARTE DE NITEROI")),
    ("NitTrans", _regex(r"NITTRANS", r"NITEROI TRANSPORTE E TRANSITO")),
    ("Clin", _regex(r"CLIN", r"COMPANHIA MUNICIPAL DE LIMPEZA URBANA")),
    ("ION (antiga Emusa)", _regex(r"EMUSA", r"ION", r"EMPRESA DE INFRAESTRUTURA E OBRAS", r"EMPRESA MUNICIPAL DE MORADIA")),
    ("Neltur", _regex(r"NELTUR", r"NITEROI EMPRESA DE LAZER E TURISMO")),
    ("Niterói Prev", _regex(r"NITEROI ?PREV", r"NITPREV")),
    ("Guarda Municipal", _regex(r"GUARDA (?:CIVIL )?MUNICIPAL")),
    ("Defesa Civil", _regex(r"DEFESA CIVIL")),
    ("Procuradoria-Geral do Município", _regex(r"PROCURADORIA GERAL DO MUNICIPIO", r"PGM")),
    ("Controladoria-Geral do Município", _regex(r"CONTROLADORIA GERAL DO MUNICIPIO", r"CGM")),
    ("Águas de Niterói (concessionária)", _regex(r"AGUAS DE NITEROI")),
    ("Enel (concessionária)", _regex(r"ENEL")),
    ("CCR Barcas (concessionária)", _regex(r"CCR BARCAS")),
    ("Naturgy (concessionária)", _regex(r"NATURGY")),
)
RE_CONCESSIONARIA = _regex(r"CONCESSIONARIAS?")
RE_EXECUTIVO = _regex(
    r"PREFEIT[OA]S?", r"PREFEITURA", r"PODER EXECUTIVO", r"EXECUTIVO MUNICIPAL", r"CHEFE DO EXECUTIVO",
)


def _orgao_especifico(texto: str) -> str | None:
    """Órgão com nome próprio citado primeiro no texto normalizado (secretaria, fundação, empresa, concessionária).

    Órgão estadual só entra como destinatário, no trecho antes do assunto (RE_FIM_DESTINO).
    """
    candidatos: list[tuple[int, int, str]] = []
    for m in RE_SECRETARIA.finditer(texto):
        conector, area, seguinte = m.groups()
        if area in _SECRETARIA_IGNORADA or area in _SECRETARIA_GENERICA or area in _SECRETARIA_ESTADUAL:
            continue
        nome = SECRETARIAS.get(f"{area} {seguinte or ''}") or SECRETARIAS.get(area)
        if nome is None and conector:
            nome = ORGAO_OUTRA_SECRETARIA
        if nome:
            candidatos.append((m.start(), -1, nome))
    for ordem, (nome, padrao) in enumerate(ORGAOS):
        m = padrao.search(texto)
        if m:
            candidatos.append((m.start(), ordem, nome))
    fim = RE_FIM_DESTINO.search(texto)
    m = RE_ESTADUAL_DESTINO.search(texto, 0, fim.start() if fim else len(texto))
    if m:
        candidatos.append((m.start(), len(ORGAOS), ORGAO_ESTADUAL))
    return min(candidatos)[2] if candidatos else None


def extrair_orgao(ementa: str | None, assunto: str | None = None) -> str:
    """Órgão a que se dirige um requerimento de informação, pelo texto, com nome normalizado.

    Vale o primeiro órgão específico citado (secretaria, fundação, autarquia, empresa
    municipal ou concessionária), seja o destinatário direto, o intermediário ("por
    intermédio da NitTrans") ou a cópia ("ao Prefeito, com cópia à Secretaria de
    Educação"): é o órgão que responde pelo assunto. Órgão estadual só conta como
    destinatário ("ao Governo do Estado", "à Secretaria de Estado de Saúde"); citado em
    outro papel, vale o nível municipal. Sem órgão específico, "Concessionária não
    especificada" e, depois, "Prefeito ou Poder Executivo" (Prefeito, Prefeitura, Poder
    Executivo ou órgão estadual citado fora do destinatário); sem nada disso, "Não
    identificado". Em cada nível a ementa vem antes do assunto da listagem. Siglas
    ambíguas (SMS, SME, SMU) não são reconhecidas.
    """
    textos = (normalizar(ementa), normalizar(assunto))
    for texto in textos:
        orgao = _orgao_especifico(texto)
        if orgao:
            return orgao
    if any(RE_CONCESSIONARIA.search(t) for t in textos):
        return ORGAO_CONCESSIONARIA
    if any(RE_EXECUTIVO.search(t) or RE_ESTADUAL.search(t) for t in textos):
        return ORGAO_EXECUTIVO
    return ORGAO_NAO_IDENTIFICADO


ESTADOS_PEDIDO = ("respondido", "aguardando", "encerrado", "retirado")


def estado_pedido(respondido: bool, situacao: str | None) -> str:
    """Estado de um requerimento de informação para as métricas de resposta.

    "respondido" quando consta resposta (veja consta_respondido). Sem resposta,
    "retirado" se a situação começa com "Retirado" (o autor desistiu do pedido),
    "encerrado" se começa com "Arquivado", "Rejeitado" ou "Prejudicado", e "aguardando"
    nos demais casos. Retirados saem da taxa de resposta; encerrados contam como não
    respondidos.
    """
    if respondido:
        return "respondido"
    sit = normalizar(situacao)
    if sit.startswith("RETIRAD"):
        return "retirado"
    if sit.startswith(("ARQUIVAD", "REJEITAD", "PREJUDICAD")):
        return "encerrado"
    return "aguardando"
