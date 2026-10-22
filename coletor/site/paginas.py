"""Páginas HTML do site."""
from __future__ import annotations

import html
import re
import statistics
from collections import Counter, defaultdict

from coletor.classificar import ALERTAS, CATEGORIAS, CONFIANCA_MINIMA
from coletor.site import graficos as G
from coletor.site.modelo import (
    DESC_SINAL, DESFECHO_GRUPO, NOME_ALERTA, NOME_CATEGORIA, NOME_DESFECHO, NOME_IMPACTO, NOME_SINAL, NOME_TEMA,
    com_efeito, mediana_legislatura, sem_efeito,
)

REPO = "https://github.com/marco-jardim/radar-vereadores-niteroi"
NAV = [
    ("index.html", "Início"),
    ("leis.html", "Leis aprovadas"),
    ("projetos.html", "Projetos"),
    ("ruido.html", "Sem efeito e polêmicas"),
    ("analises.html", "Análises"),
    ("metodologia.html", "Metodologia"),
]
CLASSE_IMPACTO = {3: "imp-3", 2: "imp-2", 1: "imp-1", 0: "imp-0", None: "imp-x"}


def esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


def data_br(iso: str | None) -> str:
    if not iso:
        return "—"
    a, m, d = iso.split("-")
    return f"{d}/{m}/{a}"


SIGLAS = {"sus", "cras", "creas", "caps", "lgbt", "lgbtqia+", "pcd", "tea", "ubs", "upa", "iptu", "iss", "ccj", "cmn", "rj", "ong", "oab", "pm", "gm", "eja", "enem"}
NOMES_PROPRIOS = {"niterói": "Niterói", "niteroi": "Niterói", "icaraí": "Icaraí", "rio": "Rio", "janeiro": "Janeiro", "brasil": "Brasil"}


def legivel(texto: str) -> str:
    """Converte ementas em caixa alta para frase normal, preservando siglas e nomes conhecidos."""
    letras = [c for c in texto if c.isalpha()]
    if not letras or sum(c.isupper() for c in letras) / len(letras) < 0.7:
        return texto
    palavras = texto.lower().split(" ")
    saida = []
    for i, p in enumerate(palavras):
        nucleo = p.strip("“”\"'(),.;:")
        if nucleo in SIGLAS:
            p = p.replace(nucleo, nucleo.upper())
        elif nucleo in NOMES_PROPRIOS:
            p = p.replace(nucleo, NOMES_PROPRIOS[nucleo])
        saida.append(p)
    t = " ".join(saida)
    t = re.sub(r"^(ementa:\s*)", "", t)
    return t[:1].upper() + t[1:]


def milhar(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def plural(n: int, um: str, varios: str) -> str:
    return f"{n} {um if n == 1 else varios}"


def pagina(titulo: str, corpo: str, ativo: str, prefixo: str = "", descricao: str = "") -> str:
    desc = esc(descricao or "Quais leis de Niterói mudam a cidade, quem as escreveu, e quanto da produção da Câmara é homenagem, "
               "lei sem efeito ou pauta polêmica. Dados do SISCAM atualizados toda semana.")
    nav = "".join(
        f'<a href="{prefixo}{href}"{" aria-current=\"page\"" if href == ativo else ""}>{esc(nome)}</a>' for href, nome in NAV
    )
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(titulo)}</title>
<meta name="description" content="{desc}">
<meta property="og:title" content="{esc(titulo)}">
<meta property="og:description" content="{desc}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=Public+Sans:ital,wght@0,400;0,600;0,700;1,400&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{prefixo}estilo.css">
<link rel="icon" href="{prefixo}favicon.svg" type="image/svg+xml">
</head>
<body>
<a class="pular" href="#conteudo">Ir para o conteúdo</a>
<header class="topo">
 <a class="marca" href="{prefixo}index.html">Radar dos Vereadores <span>Niterói</span></a>
 <nav aria-label="Principal">{nav}</nav>
</header>
<main id="conteudo" data-prefixo="{prefixo}">
{corpo}
</main>
<footer class="rodape">
 <p>Dados públicos do <a href="https://consultaniteroi.siscam.com.br/">SISCAM da Câmara Municipal de Niterói</a>, coletados toda semana. Classificação por regras, curadoria com fonte e IA, explicada na <a href="{prefixo}metodologia.html">metodologia</a>. Código aberto sob GPL v3 no <a href="{REPO}">GitHub</a>. Encontrou um erro? <a href="{REPO}/issues/new">Abra uma issue</a>.</p>
</footer>
<div id="tip" role="tooltip" hidden></div>
<script src="{prefixo}app.js" defer></script>
</body>
</html>
"""


# --------------------------------------------------------------------- componentes
def chip_autor(a: dict, prefixo: str, principal: bool = False) -> str:
    if not a.get("vereador"):
        return f'<span class="chip chip-exec">{esc(a["exibicao"])}</span>'
    return f'<a class="chip{" chip-principal" if principal else ""}" href="{prefixo}vereadores/{a["slug"]}.html">{esc(a["exibicao"])}</a>'


def autores_html(p: dict, prefixo: str) -> str:
    principal = [a for a in p["autores"] if a["slug"] == p["principal"]] or p["autores"][:1]
    outros = [a for a in p["autores"] if a not in principal]
    base = "".join(chip_autor(a, prefixo, True) for a in principal)
    if outros:
        base += f'<span class="coautores">e {plural(len(outros), "coautor", "coautores")}</span>'
    return base


def selo_impacto(p: dict) -> str:
    imp = p["impacto"]
    if p["categoria"] == "simbolica":
        return '<span class="selo imp-0">Simbólica</span>'
    if "autorizativa" in p["sinais"]:
        return '<span class="selo imp-0">Autorizativa</span>'
    return f'<span class="selo {CLASSE_IMPACTO[imp]}">{esc(NOME_IMPACTO[imp])}</span>'


def tags_html(p: dict, contestar: bool = True) -> str:
    alertas = "".join(
        f'<span class="tag alerta" title="{esc(a.get("nota", ""))}">{esc(NOME_ALERTA.get(a["rotulo"], a["rotulo"]))}'
        f'<small>{"curadoria" if a["origem"] == "curadoria" else "IA"}</small></span>'
        for a in p["alertas"]
    )
    sinais = "".join(f'<span class="tag sinal" title="{esc(DESC_SINAL.get(s, ""))}">{esc(NOME_SINAL.get(s, s))}</span>'
                     for s in p["sinais"] if s != "autorizativa")
    if p.get("repete"):
        sinais += f'<a class="tag sinal" href="{esc(p["repete"]["url"])}">igual ao PL {esc(p["repete"]["numero"])}</a>'
    if not (alertas or sinais):
        return ""
    link = ""
    if contestar:
        link = f' <a class="contestar" href="{REPO}/issues/new?title={esc("Classificação do PL " + p["numero"])}&amp;body={esc("Projeto: " + p["url"])}">contestar</a>'
    return f'<p class="tags">{alertas}{sinais}{link}</p>'


def cartao_lei(p: dict, prefixo: str) -> str:
    lei = p.get("lei") or {}
    resumo = p["resumo"] or legivel(p["ementa"])
    tema = NOME_TEMA.get(p["tema"], "") if p["tema"] not in ("outro", "homenagem") else ""
    return f"""<article class="cartao {CLASSE_IMPACTO[p['impacto']]}">
 <p class="cartao-topo">{selo_impacto(p)}<span>Lei {esc(lei.get('numero') or '')} · {data_br(lei.get('data'))}</span></p>
 <h3><a href="{esc(p['url'])}">{esc(resumo)}</a></h3>
 {f'<p class="publico">Afeta: {esc(p["publico"])}{" · " + esc(tema) if tema else ""}</p>' if p['publico'] or tema else ''}
 <p class="cartao-autor">{autores_html(p, prefixo)}{f'<span class="partido">{esc(p["partido"])}</span>' if p["partido"] else ''}</p>
</article>"""


def item_projeto(p: dict, prefixo: str) -> str:
    lei = p.get("lei") or {}
    lei_txt = f" · Lei {lei['numero']}" if lei.get("numero") else ""
    resumo = f'<p class="resumo-ia">{esc(p["resumo"])}</p>' if p["resumo"] else ""
    return f"""<li class="projeto d-{esc(DESFECHO_GRUPO.get(p['desfecho'], 'andamento'))}">
 <p class="cab"><a href="{esc(p['url'])}">PL {esc(p['numero'])}</a><span>{data_br(p['data'])}</span><span class="desfecho">{esc(NOME_DESFECHO.get(p['desfecho'], p['desfecho']))}{esc(lei_txt)}</span>{selo_impacto(p)}</p>
 {resumo}<p class="ementa">{esc(legivel(p['ementa']))}</p>
 <p class="autoria">{autores_html(p, prefixo)}</p>
 {tags_html(p)}
</li>"""


def tile(valor, rotulo: str, nota: str = "", classe: str = "") -> str:
    return f'<div class="tile {classe}"><p class="tile-valor">{esc(valor)}</p><p class="tile-rotulo">{esc(rotulo)}</p>{f"<p class=tile-nota>{esc(nota)}</p>" if nota else ""}</div>'


def barra_producao(m: dict, maximo: int) -> str:
    total = m["apresentados"]
    if total == 0:
        return '<div class="barra vazia" role="img" aria-label="Nenhum projeto apresentado como autor"><span>nenhum projeto como autor</span></div>'
    seg = [
        ("c-efeito", m["leis_efeito"], "leis com efeito"),
        ("c-baixo", m["leis_outras"], "leis de impacto baixo"),
        ("c-sem-efeito", m["leis_sem_efeito"], "leis sem efeito prático"),
        ("c-andamento", m["andamento"], "em andamento"),
        ("c-sem-exito", m["sem_exito"], "sem êxito"),
    ]
    largura = 100 * total / max(maximo, 1)
    rotulo = ", ".join(f"{n} {t}" for _, n, t in seg if n)
    partes = "".join(f'<i class="{c}" style="flex:{n}" data-tip="{n} {t}"></i>' for c, n, t in seg if n)
    return f'<div class="barra" role="img" aria-label="{total} projetos como autor: {esc(rotulo)}"><div class="trilho" style="width:{largura:.1f}%">{partes}</div></div>'


LEGENDA_BARRA = """<ul class="leg-graf" aria-label="Legenda das barras">
 <li><i class="sw c-efeito"></i>Virou lei com efeito</li>
 <li><i class="sw c-baixo"></i>Virou lei de impacto baixo</li>
 <li><i class="sw c-sem-efeito"></i>Virou lei sem efeito prático</li>
 <li><i class="sw c-andamento"></i>Em andamento</li>
 <li><i class="sw c-sem-exito"></i>Arquivado, vetado ou rejeitado</li>
</ul>"""


# ------------------------------------------------------------------------- início
def linha_placar(pessoa: dict, leg: str, maximo: int) -> str:
    m = pessoa["mandatos"][leg]
    me = m["metricas"]
    status = []
    if not m["eleito"]:
        status.append("suplente em exercício")
    if m["afastamentos"]:
        status.append("afastou-se para o Executivo")
    dados = " ".join(f'data-{k.replace("_", "-")}="{v if v is not None else -1}"' for k, v in me.items())
    alerta = f'<span class="n-alerta">{plural(me["polemicos"], "projeto com alerta", "projetos com alerta")}</span>' if me["polemicos"] else ""
    sem = f'<span>{me["leis_sem_efeito"]} sem efeito</span>' if me["leis_sem_efeito"] else ""
    return f"""<li class="linha" {dados} data-nome="{esc(pessoa['nome'])}" data-eleito="{int(m['eleito'])}" data-partido="{esc(m['partido'])}">
 <a class="quem" href="vereadores/{pessoa['slug']}.html"><strong>{esc(pessoa['nome'])}</strong> <span class="partido">{esc(m['partido'])}</span>{''.join(f'<span class="status">{esc(s)}</span>' for s in status)}</a>
 {barra_producao(me, maximo)}
 <p class="numeros"><span class="n-efeito"><b>{me['leis_efeito']}</b> {'lei com efeito' if me['leis_efeito'] == 1 else 'leis com efeito'}</span><span>{me['leis']} de {plural(me['apresentados'], 'projeto', 'projetos')}{' · ' if sem else ''}{sem}</span>{alerta}</p>
</li>"""


def gerar_index(modelo: dict) -> str:
    legs = modelo["legislaturas"]
    atual = legs[-1]["id"]
    projs = modelo["projetos"]
    ver_atual = [p for p in projs if p["legislatura"] == atual and p["origem"] == "vereador"]
    leis_atual = [p for p in ver_atual if p["desfecho"] == "virou_lei"]
    efeito = [p for p in leis_atual if com_efeito(p)]
    sem = [p for p in leis_atual if sem_efeito(p)]
    dias = [p["dias_ate_lei"] for p in leis_atual if p["dias_ate_lei"] is not None]
    alertas = [p for p in ver_atual if p["polemico"]]

    destaques = sorted([p for p in projs if com_efeito(p) and p["origem"] == "vereador"],
                       key=lambda p: ((p.get("lei") or {}).get("data") or "", p["impacto"] or 0), reverse=True)[:6]

    blocos, abas = [], []
    partidos_por_leg = {}
    for leg in reversed(legs):
        pessoas = [p for p in modelo["pessoas"].values() if leg["id"] in p["mandatos"]]
        pessoas.sort(key=lambda p: (-p["mandatos"][leg["id"]]["metricas"]["leis_efeito"], -p["mandatos"][leg["id"]]["metricas"]["leis"], p["nome"]))
        maximo = max([p["mandatos"][leg["id"]]["metricas"]["apresentados"] for p in pessoas] + [1])
        partidos_por_leg[leg["id"]] = sorted({p["mandatos"][leg["id"]]["partido"] for p in pessoas if p["mandatos"][leg["id"]]["partido"]})
        zerados = [p["nome"] for p in pessoas if p["mandatos"][leg["id"]]["eleito"] and p["mandatos"][leg["id"]]["metricas"]["leis"] == 0]
        nota_zero = f'<p class="nota">Eleitos sem nenhuma lei de autoria própria nesta legislatura: {esc(", ".join(zerados))}.</p>' if zerados else ""
        blocos.append(f"""<section class="legislatura" id="leg-{esc(leg['id'])}" data-leg="{esc(leg['id'])}"{'' if leg['id'] == atual else ' hidden'}>
{nota_zero}
<ol class="placar">{''.join(linha_placar(p, leg['id'], maximo) for p in pessoas)}</ol>
</section>""")
        abas.append(f'<button type="button" role="tab" aria-selected="{"true" if leg["id"] == atual else "false"}" data-alvo="leg-{esc(leg["id"])}">{esc(leg["id"])}</button>')
    opcoes_partido = "".join(f'<option value="{esc(pt)}">{esc(pt)}</option>' for pt in sorted({x for v in partidos_por_leg.values() for x in v}))
    atualizado = (modelo["meta"].get("coleta") or {}).get("em", "")[:10]
    pct_sem = round(100 * len(sem) / len(leis_atual)) if leis_atual else 0

    corpo = f"""<section class="abertura">
 <h1>Leis que mudam a cidade, e quem as escreveu.</h1>
 <p>Desde 2021, a Câmara de Niterói analisou mais de {milhar(len(projs) // 100 * 100)} projetos de lei. Este site separa as leis com efeito real das homenagens, das leis que só autorizam o prefeito e das pautas polêmicas, e mostra quem fez cada uma.</p>
 <p class="atualizacao">Dados do SISCAM de {data_br(atualizado) if atualizado else '—'} · <a href="metodologia.html">como classificamos</a></p>
</section>

<section aria-labelledby="t-numeros">
 <h2 id="t-numeros" class="h-secao">Legislatura {esc(atual)}, até agora</h2>
 <div class="tiles">
  {tile(len(efeito), "leis de vereadores com efeito real", f"de {len(leis_atual)} leis aprovadas", "tile-efeito")}
  {tile(f"{pct_sem}%", "das leis aprovadas não têm efeito prático", f"{len(sem)} homenagens, datas, nomes e leis autorizativas", "tile-sem")}
  {tile(len(alertas), "projetos com alerta de polêmica", "restrição de direitos, costumes ou apelo populista", "tile-alerta")}
  {tile(f"{int(statistics.median(dias))} dias" if dias else "—", "é o tempo mediano até um projeto virar lei", "")}
 </div>
</section>

<section aria-labelledby="t-destaques">
 <div class="cab-secao"><h2 id="t-destaques" class="h-secao">Leis com efeito aprovadas mais recentemente</h2><a href="leis.html?efeito=1">Ver todas as leis com efeito</a></div>
 <div class="cartoes">{''.join(cartao_lei(p, '') for p in destaques)}</div>
</section>

<section aria-labelledby="t-placar">
 <div class="cab-secao"><h2 id="t-placar" class="h-secao">Produção de cada vereador como autor principal</h2></div>
 <p class="explica">O comprimento da barra é o total de projetos apresentados; as cores mostram o que aconteceu com eles. Projetos assinados como coautor não entram, para que assinaturas em bloco não inflem a conta.</p>
 <div class="controles">
  <div role="tablist" aria-label="Legislatura" class="abas">{''.join(abas)}</div>
  <label>Ordenar por
   <select id="ordem">
    <option value="leis-efeito">Leis com efeito</option>
    <option value="leis">Total de leis</option>
    <option value="apresentados">Projetos apresentados</option>
    <option value="leis-sem-efeito">Leis sem efeito prático</option>
    <option value="pct-sem-efeito">% de leis sem efeito</option>
    <option value="polemicos">Projetos com alerta</option>
    <option value="taxa-aprovacao">Taxa de aprovação</option>
    <option value="nome">Nome</option>
   </select>
  </label>
  <label>Partido <select id="f-partido-placar"><option value="">Todos</option>{opcoes_partido}</select></label>
  <label class="check"><input type="checkbox" id="so-eleitos"> Só eleitos</label>
 </div>
 {LEGENDA_BARRA}
 {''.join(blocos)}
</section>

<section class="convite">
 <a href="ruido.html"><strong>Sem efeito e polêmicas</strong><span>Homenagens, leis que só autorizam o prefeito, projetos repetidos e pautas que restringem direitos.</span></a>
 <a href="analises.html"><strong>Análises históricas</strong><span>Como a produção da Câmara mudou de 2021 a hoje, por tema, partido e tempo de tramitação.</span></a>
</section>"""
    return pagina("Radar dos Vereadores de Niterói", corpo, "index.html")


# ------------------------------------------------------------- leis e projetos
def filtros_lista(modo: str) -> str:
    extra = ""
    if modo == "projetos":
        extra = """
  <label>Desfecho <select id="f-desfecho"><option value="">Todos</option><option value="lei">Virou lei</option><option value="andamento">Em andamento</option><option value="sem_exito">Sem êxito</option></select></label>
  <label>Sinal <select id="f-sinal"><option value="">Qualquer</option><option value="alerta">Com alerta de polêmica</option><option value="autorizativa">Lei autorizativa</option><option value="repete_projeto">Repete projeto anterior</option><option value="veto">Vetado ou com veto</option><option value="parecer_contrario_ccj">Parecer contrário da CCJ</option></select></label>"""
    return f"""<form class="filtros" role="search" onsubmit="return false" data-modo="{modo}">
 <div class="linha-busca"><label class="busca-q">Buscar <input type="search" id="q" placeholder="tema, número, nome de vereador…" autocomplete="off"></label>
  <label>Ordenar <select id="f-ordem"><option value="recente">Mais recentes</option><option value="impacto">Maior impacto</option>{'<option value="rapida">Aprovadas mais rápido</option>' if modo == 'leis' else ''}</select></label></div>
 <fieldset class="chips-impacto"><legend>Impacto</legend>
  <label><input type="checkbox" name="imp" value="3"> Alto</label>
  <label><input type="checkbox" name="imp" value="2"> Médio</label>
  <label><input type="checkbox" name="imp" value="1"> Baixo</label>
  <label><input type="checkbox" name="imp" value="0"> Sem efeito</label>
  <label><input type="checkbox" name="imp" value="x"> Não avaliado</label>
 </fieldset>
 <details class="mais-filtros" open><summary>Mais filtros</summary>
 <div class="grade-filtros">
  <label>Autoria <select id="f-origem"><option value="">Todas</option><option value="vereador">Vereadores</option><option value="executivo">Prefeitura</option></select></label>
  <label>Vereador <select id="f-autor"><option value="">Todos</option></select></label>
  <label>Partido <select id="f-partido"><option value="">Todos</option></select></label>
  <label>Tema <select id="f-tema"><option value="">Todos</option></select></label>
  <label>Legislatura <select id="f-leg"><option value="">Todas</option></select></label>
  <label>Ano <select id="f-ano"><option value="">Todos</option></select></label>{extra}
  <label class="check"><input type="checkbox" id="f-coautor"> Incluir coautoria</label>
 </div>
 </details>
 <p class="acoes-filtro"><button type="button" id="limpar">Limpar filtros</button> <button type="button" id="csv">Baixar CSV</button></p>
</form>
<div class="resumo-filtro" id="resumo-filtro" aria-live="polite"></div>
<ol id="resultados" class="projetos"></ol>
<button type="button" id="mais" class="mais" hidden>Mostrar mais</button>"""


def gerar_leis() -> str:
    corpo = f"""<section class="abertura">
 <h1>Leis aprovadas</h1>
 <p>Todas as leis que saíram de projetos apresentados desde 2021, com o impacto estimado e um resumo em linguagem simples. Filtre por impacto, tema, vereador ou partido; o quadro abaixo dos filtros mostra quem mais aprovou leis no recorte escolhido.</p>
</section>
{filtros_lista('leis')}"""
    return pagina("Leis aprovadas · Radar dos Vereadores de Niterói", corpo, "leis.html")


def gerar_projetos() -> str:
    corpo = f"""<section class="abertura">
 <h1>Todos os projetos de lei</h1>
 <p>Os {''}projetos apresentados desde 2021, incluindo os arquivados, vetados e em tramitação. Os filtros ficam no endereço da página, então dá para compartilhar uma busca.</p>
</section>
{filtros_lista('projetos')}"""
    return pagina("Projetos de lei · Radar dos Vereadores de Niterói", corpo, "projetos.html")


# --------------------------------------------------------------------- ruído
def gerar_ruido(modelo: dict) -> str:
    projs = modelo["projetos"]
    legs = modelo["legislaturas"]
    atual = legs[-1]["id"]
    ver = [p for p in projs if p["origem"] == "vereador"]
    leis_ver = [p for p in ver if p["desfecho"] == "virou_lei"]
    simb = [p for p in leis_ver if p["categoria"] == "simbolica"]
    autoriz = [p for p in ver if "autorizativa" in p["sinais"]]
    rep = [p for p in ver if "repete_projeto" in p["sinais"]]
    curados = [p for p in projs if any(a["origem"] == "curadoria" for a in p["alertas"]) or "inconstitucionalidade_declarada" in p["sinais"]]
    ia = [p for p in projs if p not in curados and (p["polemico"] or p["risco_juridico"])]
    ia.sort(key=lambda p: p["data"] or "", reverse=True)

    pessoas = [p for p in modelo["pessoas"].values() if atual in p["mandatos"] and p["mandatos"][atual]["metricas"]["leis"]]
    itens = [{"rotulo": p["nome"], "link": f"vereadores/{p['slug']}.html", "efeito": p["mandatos"][atual]["metricas"]["leis_efeito"],
              "baixo": p["mandatos"][atual]["metricas"]["leis_outras"], "sem": p["mandatos"][atual]["metricas"]["leis_sem_efeito"]} for p in pessoas]
    itens.sort(key=lambda i: (-i["sem"], i["efeito"]))
    graf = G.barras_horizontais(
        f"Leis aprovadas por vereador na legislatura {atual}, por efeito",
        "Ordenado pelo número de leis sem efeito prático (homenagens, datas, nomes e leis autorizativas).",
        itens, [("Sem efeito prático", "c-sem-efeito", "sem"), ("Impacto baixo", "c-baixo", "baixo"), ("Com efeito", "c-efeito", "efeito")])

    por_tipo = Counter()
    for p in simb:
        e = p["ementa"].upper()
        if "CALEND" in e or "DIA " in e or "SEMANA" in e or "3.474" in e or "3474" in e:
            por_tipo["Datas e semanas comemorativas"] += 1
        elif "DENOMIN" in e or " NOME" in e:
            por_tipo["Nomes de ruas e prédios"] += 1
        elif "UTILIDADE" in e:
            por_tipo["Declarações de utilidade pública"] += 1
        elif "PATRIM" in e or "TOMBA" in e:
            por_tipo["Patrimônio e tombamento"] += 1
        else:
            por_tipo["Outras homenagens e títulos"] += 1
    graf_tipo = G.barras_horizontais("Leis simbólicas de vereadores desde 2021, por tipo", "",
                                     [{"rotulo": k, "v": v} for k, v in por_tipo.most_common()], [("Leis", "c-sem-efeito", "v")])

    def lista(ps, vazio):
        return f'<ol class="projetos">{"".join(item_projeto(p, "") for p in ps) or f"<li class=vazio>{vazio}</li>"}</ol>'

    corpo = f"""<section class="abertura">
 <h1>Sem efeito e polêmicas</h1>
 <p>Uma parte da produção da Câmara não muda nada na vida da cidade: homenagens, datas comemorativas, nomes de rua, leis que só "autorizam" o prefeito a fazer o que ele já pode fazer, e projetos que repetem outros. Outra parte gera conflito: restringe direitos de grupos, explora pauta de costumes ou tem apelo populista. Esta página reúne as duas.</p>
</section>
<div class="tiles">
 {tile(len(simb), "leis simbólicas aprovadas desde 2021", f"{round(100 * len(simb) / max(len(leis_ver), 1))}% das leis de vereadores", "tile-sem")}
 {tile(len(autoriz), "projetos autorizativos", f"{sum(1 for p in autoriz if p['desfecho'] == 'virou_lei')} viraram lei", "tile-sem")}
 {tile(len(rep), "projetos repetem um anterior", "ementa quase idêntica", "")}
 {tile(sum(1 for p in projs if p['polemico']), "projetos com alerta de polêmica", f"{len(curados)} revisados por curadoria", "tile-alerta")}
</div>
<nav class="indice" aria-label="Nesta página"><a href="#por-vereador">Por vereador</a><a href="#polemicas">Polêmicas revisadas</a><a href="#ia">Marcadas por IA</a><a href="#autorizativas">Autorizativas</a><a href="#repetidos">Repetidos</a></nav>
<section id="por-vereador">{graf}{graf_tipo}</section>
<section id="polemicas"><h2 class="h-secao">Polêmicas revisadas por curadoria</h2><p class="explica">Cada item tem fonte pública em <a href="{REPO}/blob/main/config/curadoria.json">config/curadoria.json</a>.</p>{lista(curados, "Nenhum projeto revisado.")}</section>
<section id="ia"><h2 class="h-secao">Marcadas por IA</h2><p class="explica">Alertas sugeridos pela IA a partir da ementa, com confiança mínima de {int(CONFIANCA_MINIMA * 100)}%. Podem conter erros; cada um tem link para contestar.</p>{lista(ia[:150], "Nenhum projeto marcado por IA ainda.")}</section>
<section id="autorizativas"><h2 class="h-secao">Leis autorizativas aprovadas</h2><p class="explica">{esc(DESC_SINAL['autorizativa'])}</p>{lista([p for p in autoriz if p['desfecho'] == 'virou_lei'], "Nenhuma.")}</section>
<section id="repetidos"><h2 class="h-secao">Projetos que repetem outro</h2><p class="explica">{esc(DESC_SINAL['repete_projeto'])} Reapresentar um projeto arquivado é legítimo; o sinal serve para ver o quanto da produção é reaproveitada.</p>{lista(sorted(rep, key=lambda p: p['data'] or '', reverse=True), "Nenhum.")}</section>"""
    return pagina("Sem efeito e polêmicas · Radar dos Vereadores de Niterói", corpo, "ruido.html")


# ------------------------------------------------------------------- análises
def gerar_analises(modelo: dict) -> str:
    projs = modelo["projetos"]
    anos = sorted({p["ano"] for p in projs})
    rot = [str(a) for a in anos]
    ver = [p for p in projs if p["origem"] == "vereador"]

    def conta(filtro, por="ano"):
        c = Counter(p[por] for p in projs if filtro(p))
        return [c.get(a, 0) for a in anos]

    g1 = G.colunas_empilhadas(
        "Projetos de vereadores por ano de apresentação, pelo desfecho", "Projetos recentes ainda estão em tramitação.", rot, [
            ("Virou lei com efeito", "c-efeito", conta(lambda p: p["origem"] == "vereador" and com_efeito(p))),
            ("Virou lei de impacto baixo", "c-baixo", conta(lambda p: p["origem"] == "vereador" and p["desfecho"] == "virou_lei" and not com_efeito(p) and not sem_efeito(p))),
            ("Virou lei sem efeito prático", "c-sem-efeito", conta(lambda p: p["origem"] == "vereador" and p["desfecho"] == "virou_lei" and sem_efeito(p))),
            ("Em andamento", "c-andamento", conta(lambda p: p["origem"] == "vereador" and DESFECHO_GRUPO.get(p["desfecho"]) == "andamento")),
            ("Sem êxito", "c-sem-exito", conta(lambda p: p["origem"] == "vereador" and DESFECHO_GRUPO.get(p["desfecho"]) == "sem_exito")),
        ])

    def ano_lei(p):
        d = (p.get("lei") or {}).get("data")
        return int(d[:4]) if d else p["ano"]
    leis = [p for p in projs if p["desfecho"] == "virou_lei"]
    anos_lei = sorted({ano_lei(p) for p in leis if ano_lei(p) >= anos[0]})
    rot_l = [str(a) for a in anos_lei]

    def conta_l(f):
        c = Counter(ano_lei(p) for p in leis if f(p))
        return [c.get(a, 0) for a in anos_lei]
    g2 = G.colunas_empilhadas("Leis sancionadas ou promulgadas por ano, pela autoria", "Ano em que o projeto virou lei.", rot_l, [
        ("Vereadores, com efeito", "c-efeito", conta_l(lambda p: p["origem"] == "vereador" and com_efeito(p))),
        ("Vereadores, sem efeito ou impacto baixo", "c-sem-efeito", conta_l(lambda p: p["origem"] == "vereador" and not com_efeito(p))),
        ("Prefeitura", "c-exec", conta_l(lambda p: p["origem"] == "executivo")),
    ])

    def med_dias(f):
        out = []
        for a in anos_lei:
            ds = [p["dias_ate_lei"] for p in leis if ano_lei(p) == a and f(p) and p["dias_ate_lei"] is not None]
            out.append(int(statistics.median(ds)) if ds else None)
        return out
    g3 = G.linhas("Tempo mediano entre o protocolo e a lei, em dias", "Por ano em que o projeto virou lei.", rot_l, [
        ("Vereadores", "c-efeito", med_dias(lambda p: p["origem"] == "vereador")),
        ("Prefeitura", "c-exec", med_dias(lambda p: p["origem"] == "executivo")),
    ], unidade=" dias")

    temas = Counter(p["tema"] for p in leis if p["origem"] == "vereador" and com_efeito(p) and p["tema"] not in ("homenagem", "outro"))
    g4 = "" if len(temas) < 3 else G.barras_horizontais("Temas das leis de vereadores com efeito, desde 2021", "Tema atribuído pela IA a partir da ementa.",
                              [{"rotulo": NOME_TEMA.get(t, t), "v": n, "link": f"leis.html?efeito=1&tema={t}"} for t, n in temas.most_common(14)],
                              [("Leis com efeito", "c-efeito", "v")])

    blocos_leg = []
    for leg in reversed(modelo["legislaturas"]):
        pessoas = [p for p in modelo["pessoas"].values() if leg["id"] in p["mandatos"] and p["mandatos"][leg["id"]]["metricas"]["apresentados"]]
        pts = [{"x": p["mandatos"][leg["id"]]["metricas"]["apresentados"], "y": p["mandatos"][leg["id"]]["metricas"]["leis_efeito"],
                "rotulo": p["nome"], "link": f"vereadores/{p['slug']}.html",
                "cor": "c-efeito" if p["mandatos"][leg["id"]]["eleito"] else "c-andamento"} for p in pessoas]
        gd = G.dispersao(f"Volume x resultado, legislatura {leg['id']}",
                         "Cada ponto é um vereador. Mais à direita, mais projetos apresentados; mais acima, mais leis com efeito. Suplentes em cinza.",
                         pts, "Projetos apresentados como autor", "Leis com efeito", rotular=10)
        part = defaultdict(lambda: Counter())
        for p in pessoas:
            m = p["mandatos"][leg["id"]]
            if not m["partido"]:
                continue
            part[m["partido"]]["vereadores"] += 1
            part[m["partido"]]["efeito"] += m["metricas"]["leis_efeito"]
            part[m["partido"]]["sem"] += m["metricas"]["leis_sem_efeito"]
            part[m["partido"]]["baixo"] += m["metricas"]["leis_outras"]
        it = [{"rotulo": f"{pt} ({c['vereadores']})", "efeito": c["efeito"], "baixo": c["baixo"], "sem": c["sem"]} for pt, c in part.items()]
        it.sort(key=lambda i: (-i["efeito"], -i["baixo"]))
        gp = G.barras_horizontais(f"Leis aprovadas por partido, legislatura {leg['id']}",
                                  "Partido pelo qual o vereador foi eleito; entre parênteses, quantos eleitos do partido apresentaram projetos.",
                                  it, [("Com efeito", "c-efeito", "efeito"), ("Impacto baixo", "c-baixo", "baixo"), ("Sem efeito prático", "c-sem-efeito", "sem")])
        blocos_leg.append(f'<section class="bloco-leg"><h2 class="h-secao">Legislatura {esc(leg["id"])}</h2>{gd}{gp}</section>')

    corpo = f"""<section class="abertura">
 <h1>Análises históricas</h1>
 <p>Como a produção legislativa de Niterói evoluiu desde 2021: quanto vira lei, quanto disso tem efeito, quanto tempo leva e quais temas dominam. Cada gráfico tem uma tabela com os números.</p>
</section>
<div class="graficos">{g1}{g2}{g3}{g4}</div>
{''.join(blocos_leg)}"""
    return pagina("Análises · Radar dos Vereadores de Niterói", corpo, "analises.html")


# ------------------------------------------------------------------ vereador
def comparacao(valor, mediana, maior_melhor: bool = True, sufixo: str = "") -> str:
    if valor is None or mediana is None:
        return ""
    if valor == mediana:
        return f"igual à mediana dos eleitos ({G._fmt(mediana)}{sufixo})"
    acima = valor > mediana
    return f"{'acima' if acima else 'abaixo'} da mediana dos eleitos ({G._fmt(mediana)}{sufixo})"


def gerar_vereador(modelo: dict, pessoa: dict) -> str:
    secoes = []
    for leg in reversed(modelo["legislaturas"]):
        m = pessoa["mandatos"].get(leg["id"])
        if not m:
            continue
        me = m["metricas"]
        afast = "".join(f'<p class="aviso">Afastou-se da Câmara para o cargo de {esc(a["cargo"])} (<a href="{esc(a["fonte"])}">fonte</a>). Nesse período a cadeira foi ocupada por suplente.</p>' for a in m["afastamentos"])
        cond = "Eleito" if m["eleito"] else "Suplente em exercício"
        med = lambda k: mediana_legislatura(modelo, leg["id"], k)
        proj = sorted(m["projetos_autor"], key=lambda p: p["data"] or "", reverse=True)
        leis = [p for p in proj if p["desfecho"] == "virou_lei"]
        efeito = sorted([p for p in leis if com_efeito(p)], key=lambda p: (-(p["impacto"] or 0), (p.get("lei") or {}).get("data") or ""))
        sem = [p for p in leis if sem_efeito(p)]
        polem = [p for p in proj if p["polemico"] or p["risco_juridico"]]

        anos = sorted({p["ano"] for p in proj})
        graf_ano = ""
        if len(anos) > 1:
            c = lambda f: [sum(1 for p in proj if p["ano"] == a and f(p)) for a in anos]
            graf_ano = G.colunas_empilhadas("Projetos por ano de apresentação", "", [str(a) for a in anos], [
                ("Lei com efeito", "c-efeito", c(com_efeito)),
                ("Lei de impacto baixo", "c-baixo", c(lambda p: p["desfecho"] == "virou_lei" and not com_efeito(p) and not sem_efeito(p))),
                ("Lei sem efeito prático", "c-sem-efeito", c(lambda p: p["desfecho"] == "virou_lei" and sem_efeito(p))),
                ("Em andamento", "c-andamento", c(lambda p: DESFECHO_GRUPO.get(p["desfecho"]) == "andamento")),
                ("Sem êxito", "c-sem-exito", c(lambda p: DESFECHO_GRUPO.get(p["desfecho"]) == "sem_exito")),
            ], altura=200)
        temas = Counter(p["tema"] for p in proj if p["tema"] not in ("outro",))
        graf_tema = "" if len(temas) < 2 else G.barras_horizontais("Temas dos projetos apresentados", "", [{"rotulo": NOME_TEMA.get(t, t), "v": n} for t, n in temas.most_common(8)],
                                         [("Projetos", "c-exec", "v")])

        tiles = "".join([
            tile(me["leis_efeito"], "leis com efeito", comparacao(me["leis_efeito"], med("leis_efeito")), "tile-efeito"),
            tile(me["leis"], "leis aprovadas no total", f"de {plural(me['apresentados'], 'projeto apresentado', 'projetos apresentados')}"),
            tile(me["leis_sem_efeito"], "leis sem efeito prático", comparacao(me["leis_sem_efeito"], med("leis_sem_efeito")), "tile-sem"),
            tile(me["polemicos"], "projetos com alerta de polêmica", "", "tile-alerta" if me["polemicos"] else ""),
            tile(f"{me['taxa_aprovacao']}%" if me["taxa_aprovacao"] is not None else "—", "dos projetos concluídos viraram lei",
                 comparacao(me["taxa_aprovacao"], med("taxa_aprovacao"), sufixo="%")),
            tile(me["leis_coautoria"], "leis como coautor", ""),
        ])
        secoes.append(f"""<section class="mandato">
 <h2>{esc(leg['id'])} <span>{esc(cond)}{(' · ' + esc(m['partido'])) if m['partido'] else ''}</span></h2>
 {afast}
 <div class="tiles">{tiles}</div>
 {barra_producao(me, max(me['apresentados'], 1))}
 <div class="graficos duas">{graf_ano}{graf_tema}</div>
 <h3>Leis com efeito</h3>
 {f'<div class="cartoes">{"".join(cartao_lei(p, "../") for p in efeito)}</div>' if efeito else '<p class="vazio">Nenhuma lei com efeito nesta legislatura.</p>'}
 {f'<h3>Projetos com alerta</h3><ol class="projetos">{"".join(item_projeto(p, "../") for p in polem)}</ol>' if polem else ''}
 {f'<details class="bloco"><summary>Leis sem efeito prático ({len(sem)})</summary><ol class="projetos">{"".join(item_projeto(p, "../") for p in sem)}</ol></details>' if sem else ''}
 <details class="bloco"><summary>Todos os projetos como autor principal ({len(proj)})</summary>{'<ol class="projetos">' + ''.join(item_projeto(p, '../') for p in proj) + '</ol>' if proj else '<p class="vazio">Nenhum.</p>'}</details>
 <p><a href="../leis.html?autor={pessoa['slug']}&amp;coautor=1">Ver também as leis em que é coautor</a></p>
</section>""")
    corpo = f"""<section class="abertura ficha">
 <p><a href="../index.html">Todos os vereadores</a></p>
 <h1>{esc(pessoa['nome'])}</h1>
 <p class="siscam">Nome no SISCAM: {esc(pessoa['nome_siscam'])}</p>
</section>
{LEGENDA_BARRA}
{''.join(secoes)}"""
    return pagina(f"{pessoa['nome']} · Radar dos Vereadores de Niterói", corpo, "", "../",
                  f"Leis e projetos de {pessoa['nome']} na Câmara de Niterói: quantas leis com efeito, quantas sem efeito prático e quais pautas polêmicas.")


# -------------------------------------------------------------------- metodologia
def gerar_metodologia(modelo: dict) -> str:
    cls = modelo["meta"].get("classificacao") or {}
    defs_cat = "".join(f"<dt>{esc(NOME_CATEGORIA[k])}</dt><dd>{esc(v)}</dd>" for k, v in CATEGORIAS.items())
    defs_al = "".join(f"<dt>{esc(NOME_ALERTA[k])}</dt><dd>{esc(v)}</dd>" for k, v in ALERTAS.items())
    defs_sin = "".join(f"<dt>{esc(v)}</dt><dd>{esc(DESC_SINAL[k])}</dd>" for k, v in NOME_SINAL.items())
    corpo = f"""<section class="abertura texto">
<h1>Metodologia</h1>
<p>Este site mede a produção de cada vereador em projetos de lei, não seu trabalho inteiro. Indicações, requerimentos, fiscalização do Executivo, comissões e atendimento à população não entram nos números.</p>

<h2>De onde vêm os dados</h2>
<p>Toda semana, uma GitHub Action baixa do <a href="https://consultaniteroi.siscam.com.br/">SISCAM</a> os projetos de lei de cada ano desde 2021 e, para os novos ou com tramitação alterada, a autoria e a tramitação completa. Só a composição das legislaturas e a curadoria são editadas à mão, em arquivos públicos.</p>

<h2>Como os números são contados</h2>
<ul>
 <li><b>Autor principal</b> é quem o SISCAM registra como "Autor". As barras e os rankings contam só autoria principal, para que projetos assinados em bloco não inflem a produção de cada um.</li>
 <li><b>Virou lei</b>: sancionada, promulgada pela Câmara ou com veto derrubado. Número e data vêm da tramitação, incluindo as corrigendas publicadas.</li>
 <li><b>Tempo até virar lei</b>: dias entre o protocolo e a sanção ou promulgação.</li>
 <li><b>Taxa de aprovação</b>: leis divididas por projetos já concluídos (viraram lei, foram arquivados, vetados, rejeitados ou retirados). Projetos em tramitação ficam de fora.</li>
 <li><b>Legislatura</b>: o projeto conta na legislatura em que foi apresentado. Suplentes em exercício e afastamentos para o Executivo aparecem identificados.</li>
</ul>

<h2 id="impacto">Impacto e efeito</h2>
<p>Cada projeto recebe um impacto de 0 a 3, estimado pela IA a partir da ementa:</p>
<dl class="defs">
 <dt>3 · Alto</dt><dd>Afeta grande parte da população, cria política ou serviço amplo, ou mexe em orçamento ou tributo relevante.</dd>
 <dt>2 · Médio</dt><dd>Muda regra ou serviço para um grupo relevante ou um setor da cidade.</dd>
 <dt>1 · Baixo</dt><dd>Efeito pontual, restrito a um local, grupo pequeno ou procedimento menor.</dd>
 <dt>0 · Sem efeito prático</dt><dd>Homenagem, data, nome, título, utilidade pública, lei que só autoriza o Executivo ou repete norma existente.</dd>
</dl>
<p>Duas regras determinísticas se sobrepõem à IA: projetos simbólicos sempre recebem impacto 0, e leis autorizativas recebem no máximo 1. <b>Lei com efeito</b> é a que virou lei com impacto 2 ou 3. Enquanto a IA não avaliou um projeto, conta como lei com efeito a que não é simbólica nem autorizativa.</p>
<p>O resumo em linguagem simples e o público afetado também são gerados pela IA e servem de apoio à leitura; o texto oficial é sempre a ementa, mostrada logo abaixo.</p>

<h2>Categoria</h2>
<p>Ementas que batem com padrões de homenagem, nome de logradouro, data comemorativa (incluindo alterações da Lei 3.474/2020, o calendário oficial), título ou patrimônio imaterial são classificadas como simbólicas por regra; as demais, pela IA.</p>
<dl class="defs">{defs_cat}</dl>

<h2 id="sinais">Sinais objetivos</h2>
<dl class="defs">{defs_sin}</dl>

<h2 id="alertas">Alertas de polêmica</h2>
<p>Os alertas valem igualmente para qualquer autor, partido ou espectro político. Têm duas origens:</p>
<ul>
 <li><b>Curadoria</b>: revisado à mão, com fonte pública, em <a href="{REPO}/blob/main/config/curadoria.json"><code>config/curadoria.json</code></a>. Prevalece sobre a IA.</li>
 <li><b>IA</b>: o modelo <code>{esc(cls.get('modelo', '—'))}</code>, via OpenCode Go, lê só a ementa. Só aparece alerta com confiança de pelo menos {int(CONFIANCA_MINIMA * 100)}%. O prompt completo está em <a href="{REPO}/blob/main/coletor/classificar.py"><code>coletor/classificar.py</code></a> (versão {esc(cls.get('versao_prompt', '—'))}).</li>
</ul>
<dl class="defs">{defs_al}</dl>
<p>"Com alerta de polêmica" soma restrição de direitos, pauta de costumes e apelo populista. Risco de inconstitucionalidade aparece à parte, porque é comum em projetos municipais de todos os campos.</p>

<h2>Limitações</h2>
<ul>
 <li>A ementa é um resumo. A IA não lê o texto integral nem o contexto político, e pode errar nos dois sentidos.</li>
 <li>Impacto estimado não é avaliação de resultado: uma lei de impacto alto pode nunca ser cumprida.</li>
 <li>A detecção de projetos repetidos compara palavras da ementa e pode juntar projetos parecidos mas diferentes.</li>
 <li>Erros de registro no SISCAM passam para cá.</li>
</ul>

<h2>Contestar ou corrigir</h2>
<p>Projetos com alerta ou sinal têm um link "contestar", que abre uma issue no GitHub. Correções na composição das legislaturas e na curadoria podem ser enviadas como pull request.</p>
</section>"""
    return pagina("Metodologia · Radar dos Vereadores de Niterói", corpo, "metodologia.html")


def redirecionar(destino: str) -> str:
    return f'<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0; url={destino}"><link rel="canonical" href="{destino}"><a href="{destino}">Esta página mudou de endereço.</a>'
