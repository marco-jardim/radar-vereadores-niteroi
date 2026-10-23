"""Novidades da semana: eventos dos projetos de lei derivados das datas já coletadas.

Nada é guardado entre coletas nem comparado com a coleta anterior: cada evento sai de uma data
que já está nos dados (apresentação do PL, data da lei, passos de veto e de derrubada de veto na
tramitação). A semana mais recente é a semana ISO (segunda a domingo) da data mais recente entre
os eventos, nunca a do relógio: a mesma entrada gera sempre os mesmos bytes, inclusive no RSS.

Só biblioteca padrão. Este módulo não importa coletor.site (modelo.py usa marcos_tramitacao).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from xml.sax.saxutils import escape

from coletor.siscam import DETALHE

# Endereço publicado no GitHub Pages; os links do feed RSS precisam ser absolutos.
URL_SITE = "https://marco-jardim.github.io/radar-vereadores-niteroi/"
PAGINA = "novidades.html"
FEED = "feed.xml"
SEMANAS = 12  # semanas exibidas em novidades.html, contando a mais recente
MAX_ITENS_RSS = 100
# Horário de Brasília: UTC−3 fixo, sem horário de verão desde 2019 (sem zoneinfo nem tzdata).
FUSO_BRASILIA = timezone(timedelta(hours=-3))
FUSO_RSS = "-0300"  # o mesmo fuso no RSS; as datas do SISCAM não têm hora

# Ordem de exibição e de contagem; num mesmo dia, a lei vem antes do veto, e o veto antes da apresentação.
TIPOS_EVENTO = ("lei", "veto_derrubado", "veto", "apresentado")
PRIORIDADE = {t: len(TIPOS_EVENTO) - i for i, t in enumerate(TIPOS_EVENTO)}
ROTULO_EVENTO = {"lei": "Virou lei", "veto_derrubado": "Veto derrubado", "veto": "Veto", "apresentado": "Apresentado"}
# (singular, plural) da contagem por semana
NOME_EVENTO = {
    "lei": ("lei sancionada ou promulgada", "leis sancionadas ou promulgadas"),
    "veto_derrubado": ("veto derrubado", "vetos derrubados"),
    "veto": ("veto do prefeito", "vetos do prefeito"),
    "apresentado": ("projeto apresentado", "projetos apresentados"),
}
FORMA_LEI = {
    "sancionada": "sancionada",
    "promulgada_camara": "promulgada pela Câmara",
    "veto_derrubado": "promulgada após a derrubada do veto",
}
ALCANCE_VETO = {"total": "veto total", "parcial": "veto parcial"}


def url_detalhe(id_doc: int) -> str:
    return DETALHE.format(doc=id_doc)


# ------------------------------------------------------------------- tramitação
# Resultado do passo em que o SISCAM registra o veto do prefeito: "Vetado", "Veto Parcial", "Veto Total".
# "Manutenção ao Veto" (parecer da CCJ), "Veto Mantido" e "Veto Rejeitado" não são o veto em si.
RE_RESULTADO_VETO = re.compile(r"^\s*vet(?:ad[oa]|os?)\b", re.I)
RE_NAO_E_VETO = re.compile(r"derrub|rejei|mantid|manuten", re.I)
# "DERRUBADO O VETO TOTAL", "Rejeitado o Veto", "veto foi rejeitado"; não "REJEITADO O PARECER ... DO VETO".
RE_DERRUBADA = re.compile(
    r"vetos?\s+(?:total\s+|parcial\s+)?(?:foi\s+|foram\s+)?(?:rejeitad|derrubad)"
    r"|(?:derrubad|rejeitad)[oa]s?\s+(?:[oa]s?\s+|d[oa]s?\s+)?vetos?"
    r"|rejei[çc][ãa]o\s+(?:a[o]?s?\s+|d[oa]s?\s+)?vetos?",
    re.I,
)
# "votos pela derrubada do veto" descreve a votação, não o resultado: o veto pode ter sido mantido.
RE_ANTES_NAO_CONTA = re.compile(
    r"(?:\bpela|\bpara\s+a|\ba\s+favor\s+da|\bfavor[áa]veis\s+[àa]|\bcontr[áa]ri[oa]s?\s+[àa]|\bcontra\s+a)\s*$", re.I)
# Situações do SISCAM que confirmam a derrubada; "VETO MANTIDO" (ou o desfecho "vetado") nunca confirma.
SITUACOES_DERRUBADA = ("VETO REJEITADO", "VETO DERRUBADO")
# A derrubada é votada em plenário; o mesmo texto num parecer de comissão não conta.
RE_PLENARIO = re.compile(r"plen[áa]rio|ordem do dia|discuss[ãa]o|vota[çc][ãa]o", re.I)
# O passo da promulgação repete "REJEIÇÃO DO VETO", mas a data dele é a da lei, não a da votação.
RE_PROMULGACAO = re.compile(r"promulgad|sancionad|promulga[çc][ãa]o", re.I)


def data_valida(texto) -> bool:
    try:
        return isinstance(texto, str) and len(texto) == 10 and date.fromisoformat(texto).isoformat() == texto
    except ValueError:
        return False


def _alcance(passo: dict, origem: dict) -> str | None:
    """Total ou parcial pelo texto do passo; sem isso, pela situação e pela lei do mesmo documento."""
    texto = " ".join(str(passo.get(k) or "") for k in ("resultado", "observacao", "complemento"))
    if re.search(r"parcia", texto, re.I):
        return "parcial"
    if re.search(r"\btota", texto, re.I):
        return "total"
    situacao = (origem.get("situacao") or "").upper()
    if situacao == "VETO PARCIAL" or (origem.get("lei") or {}).get("veto_parcial"):
        return "parcial"
    if situacao in {"VETO TOTAL", "VETO MANTIDO"}:
        return "total"
    return None


def registra_derrubada(texto: str) -> bool:
    """O texto do passo diz que o veto caiu, e não só que houve votos pela derrubada."""
    return any(not RE_ANTES_NAO_CONTA.search(texto[:m.start()]) for m in RE_DERRUBADA.finditer(texto))


def confirma_derrubada(documento: dict) -> bool:
    """Confirmação estrutural no próprio documento (PL ou substitutivo) de que o veto foi derrubado.

    Vale a situação "VETO REJEITADO"/"VETO DERRUBADO" ou a lei com tipo "veto_derrubado" (siscam.derivar_lei).
    Veto mantido ou desfecho "vetado" nunca confirmam, mesmo que a tramitação fale em derrubada.
    """
    situacao = (documento.get("situacao") or "").upper()
    if "VETO MANTIDO" in situacao or documento.get("desfecho") == "vetado":
        return False
    return any(s in situacao for s in SITUACOES_DERRUBADA) or (documento.get("lei") or {}).get("tipo") == "veto_derrubado"


def marcos_tramitacao(registro: dict) -> list[dict]:
    """Veto e derrubada de veto de um PL bruto (data/proposicoes), com a data do passo da tramitação.

    Lê a tramitação do PL e a de cada substitutivo (a lei, e o veto, podem sair do substitutivo).
    Veto: passo cujo resultado é o veto ("Vetado", "Veto Parcial"), com a Data Resposta; sem ela, não há
    data confiável e o passo não conta. Derrubada: passo de plenário que registra a derrubada ou a rejeição
    do veto (não "votos pela derrubada"), com a Data Resposta ou, sem ela, o Enviado em (o dia da sessão),
    e só se o mesmo documento confirmar a derrubada pela situação ou pela lei (confirma_derrubada).
    Há no máximo um marco de cada tipo por PL, o de data mais antiga; no empate de data, vale o do próprio PL.
    """
    fontes = [(registro, None)] + [(s, s.get("id")) for s in registro.get("substitutivos") or [] if isinstance(s, dict)]
    vetos, derrubadas = [], []
    for ordem, (origem, sub) in enumerate(fontes):
        confirmada = confirma_derrubada(origem)
        for passo in origem.get("tramitacoes") or []:
            resultado = str(passo.get("resultado") or "")
            texto = resultado + " " + str(passo.get("observacao") or "")
            if RE_RESULTADO_VETO.search(resultado) and not RE_NAO_E_VETO.search(resultado):
                data = passo.get("data_resposta")
                if data_valida(data):
                    vetos.append((data, ordem, {"tipo": "veto", "data": data, "alcance": _alcance(passo, origem), "substitutivo": sub}))
            elif (confirmada and registra_derrubada(texto) and not RE_PROMULGACAO.search(resultado)
                  and RE_PLENARIO.search(f"{passo.get('destinatario') or ''} {passo.get('objetivo') or ''}")):
                data = passo.get("data_resposta") or passo.get("enviado")
                if data_valida(data):
                    derrubadas.append((data, ordem, {"tipo": "veto_derrubado", "data": data, "substitutivo": sub}))
    return [min(lista, key=lambda c: c[:2])[2] for lista in (vetos, derrubadas) if lista]


# ----------------------------------------------------------------------- eventos
def _numero(p: dict) -> int:
    try:
        return int(str(p.get("numero") or "").split("/")[0])
    except ValueError:
        return 0


def chave_evento(ev: dict) -> tuple:
    """Ordem total dos eventos; com reverse=True, do mais recente ao mais antigo."""
    p = ev["projeto"]
    return ev["data"], PRIORIDADE[ev["tipo"]], p.get("ano") or 0, _numero(p), p["id"]


def derivar_eventos(projetos: list[dict], ate: str | None = None) -> list[dict]:
    """Eventos dos projetos já enriquecidos (modelo["projetos"]), do mais recente ao mais antigo.

    Cada evento é {"tipo", "data", "projeto", "substitutivo"} e, no veto, "alcance". Datas inválidas
    ficam de fora, assim como as posteriores a `ate` (a data da última coleta): um passo datado
    depois da coleta é erro de registro e não pode puxar a semana mais recente para o futuro.
    """
    eventos = []
    for p in projetos:
        if p.get("data"):
            eventos.append({"tipo": "apresentado", "data": p["data"], "projeto": p, "substitutivo": None})
        lei = p.get("lei") or {}
        if p.get("desfecho") == "virou_lei" and lei.get("data"):
            eventos.append({"tipo": "lei", "data": lei["data"], "projeto": p, "substitutivo": p.get("lei_substitutivo")})
        for m in p.get("marcos") or []:
            if m.get("tipo") in PRIORIDADE:
                eventos.append({**m, "projeto": p})
    validos = [e for e in eventos if data_valida(e["data"]) and (ate is None or e["data"] <= ate)]
    validos.sort(key=chave_evento, reverse=True)
    return validos


def data_da_coleta(meta: dict) -> str | None:
    """Dia da última coleta dos projetos (data/meta.json) no horário de Brasília, limite das datas dos eventos.

    coleta.em é gravado em UTC; a coleta das 01:30 UTC ainda é o dia anterior em Brasília. Sem fuso, vale
    a data como está escrita.
    """
    try:
        momento = datetime.fromisoformat(str((meta.get("coleta") or {}).get("em") or ""))
    except ValueError:
        return None
    if momento.tzinfo is not None:
        momento = momento.astimezone(FUSO_BRASILIA)
    return momento.date().isoformat()


def eventos_do_modelo(modelo: dict) -> list[dict]:
    return derivar_eventos(modelo["projetos"], data_da_coleta(modelo.get("meta") or {}))


# ----------------------------------------------------------------------- semanas
def inicio_semana(data_iso: str) -> date:
    """Segunda-feira da semana ISO da data."""
    d = date.fromisoformat(data_iso)
    return d - timedelta(days=d.weekday())


def semanas_recentes(eventos: list[dict], n: int = SEMANAS) -> list[dict]:
    """As n semanas ISO até a da data mais recente dos eventos, da mais recente à mais antiga.

    Semanas sem evento também aparecem, com lista vazia. Sem eventos, não há semana de referência.
    """
    if not eventos:
        return []
    atual = inicio_semana(max(e["data"] for e in eventos))
    por_semana: dict[date, list[dict]] = defaultdict(list)
    for e in eventos:
        por_semana[inicio_semana(e["data"])].append(e)
    semanas = []
    for k in range(n):
        inicio = atual - timedelta(weeks=k)
        lista = sorted(por_semana.get(inicio, []), key=chave_evento, reverse=True)
        contagem = Counter(e["tipo"] for e in lista)
        ano, numero, _ = inicio.isocalendar()
        semanas.append({
            "inicio": inicio.isoformat(), "fim": (inicio + timedelta(days=6)).isoformat(), "ano": ano, "numero": numero,
            "eventos": lista, "contagem": {t: contagem[t] for t in TIPOS_EVENTO if contagem[t]},
        })
    return semanas


# ------------------------------------------------------------------------ textos
def titulo_evento(ev: dict) -> str:
    """Frase do evento, a mesma na página e no feed."""
    p = ev["projeto"]
    pl = f"PL {p['numero']}"
    no_sub = " (no substitutivo)" if ev.get("substitutivo") else ""
    if ev["tipo"] == "lei":
        lei = p.get("lei") or {}
        texto = f"{pl} virou a Lei {lei['numero']}" if lei.get("numero") else f"{pl} virou lei"
        if ev.get("substitutivo"):
            texto += ", via substitutivo"
        forma = [FORMA_LEI[lei["tipo"]]] if lei.get("tipo") in FORMA_LEI else []
        if lei.get("veto_parcial"):
            forma.append("com veto parcial")
        return texto + (f" ({', '.join(forma)})" if forma else "")
    if ev["tipo"] == "veto":
        return f"{pl} recebeu {ALCANCE_VETO.get(ev.get('alcance'), 'veto')} do prefeito{no_sub}"
    if ev["tipo"] == "veto_derrubado":
        return f"A Câmara derrubou o veto ao {pl}{no_sub}"
    return f"{pl} apresentado"


def autoria_texto(p: dict) -> str:
    """Autor principal (ou o primeiro), partido e quantos coautores; espelha autores_html em texto."""
    autores = p.get("autores") or []
    principal = [a for a in autores if a.get("slug") and a.get("slug") == p.get("principal")] or autores[:1]
    if not principal:
        return ""
    a = principal[0]
    texto = str(a.get("exibicao") or a.get("nome") or "")
    if p.get("partido") and p.get("principal"):
        texto += f" ({p['partido']})"
    outros = len(autores) - 1
    if outros > 0:
        texto += f" e {outros} {'coautor' if outros == 1 else 'coautores'}"
    return texto


# --------------------------------------------------------------------------- RSS
DIAS_RFC = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MESES_RFC = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
# Caracteres que o XML 1.0 não aceita nem como entidade.
RE_INVALIDO_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


def data_rfc822(data_iso: str) -> str:
    """Data do RSS 2.0 sem depender do locale: "Mon, 05 Oct 2026 00:00:00 -0300"."""
    d = date.fromisoformat(data_iso)
    return f"{DIAS_RFC[d.weekday()]}, {d.day:02d} {MESES_RFC[d.month - 1]} {d.year} 00:00:00 {FUSO_RSS}"


def xml_texto(valor) -> str:
    return escape(RE_INVALIDO_XML.sub("", str(valor if valor is not None else "")), {'"': "&quot;"})


def guid_evento(ev: dict) -> str:
    """Identificador estável do evento: tipo, id do PL e data."""
    return f"radar-vereadores-niteroi:{ev['tipo']}:{ev['projeto']['id']}:{ev['data']}"


def link_absoluto(url: str, base: str = URL_SITE) -> str:
    return url if re.match(r"https?://", url or "") else base + (url or "").lstrip("/")


def link_evento(ev: dict) -> str:
    """Página do SISCAM do evento: a do substitutivo quando a lei saiu dele (como url_lei); senão, a do PL."""
    if ev["tipo"] == "lei" and ev.get("substitutivo"):
        return url_detalhe(ev["substitutivo"])
    p = ev["projeto"]
    return p.get("url") or url_detalhe(p["id"])


def gerar_rss(eventos: list[dict], base: str = URL_SITE, maximo: int = MAX_ITENS_RSS) -> str:
    """Feed RSS 2.0 com os `maximo` eventos mais recentes; `eventos` já vem ordenado (derivar_eventos).

    lastBuildDate e pubDate são a data mais recente dos eventos, nunca a hora da geração.
    """
    itens = []
    for ev in eventos[:maximo]:
        p = ev["projeto"]
        partes = [str(p.get("resumo") or ""), str(p.get("ementa") or "")]
        autoria = autoria_texto(p)
        if autoria:
            partes.append(f"Autoria: {autoria}.")
        descricao = " ".join(x.strip() for x in partes if x and x.strip())
        itens.append(f"""  <item>
   <title>{xml_texto(titulo_evento(ev))}</title>
   <link>{xml_texto(link_absoluto(link_evento(ev), base))}</link>
   <description>{xml_texto(descricao)}</description>
   <category>{xml_texto(ROTULO_EVENTO[ev["tipo"]])}</category>
   <pubDate>{data_rfc822(ev["data"])}</pubDate>
   <guid isPermaLink="false">{xml_texto(guid_evento(ev))}</guid>
  </item>
""")
    datas = ""
    if eventos:
        ultima = data_rfc822(max(e["data"] for e in eventos))
        datas = f"  <pubDate>{ultima}</pubDate>\n  <lastBuildDate>{ultima}</lastBuildDate>\n"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
 <channel>
  <title>Novidades · Radar dos Vereadores de Niterói</title>
  <link>{xml_texto(base + PAGINA)}</link>
  <description>Projetos de lei apresentados, leis sancionadas ou promulgadas, vetos e vetos derrubados na Câmara Municipal de Niterói, pelas datas registradas no SISCAM.</description>
  <language>pt-BR</language>
  <atom:link href="{xml_texto(base + FEED)}" rel="self" type="application/rss+xml"/>
{datas}{"".join(itens)} </channel>
</rss>
"""
