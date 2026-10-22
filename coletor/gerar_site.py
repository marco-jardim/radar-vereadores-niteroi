"""Gera o site estático em ./site a partir de data/ e config/.

Uso: python -m coletor.gerar_site
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
import shutil
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from coletor.classificar import ALERTAS, CATEGORIAS, carregar_curadoria, carregar_proposicoes, classificacao_final

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "site"
FONTE_ESTATICA = RAIZ / "site_src"
REPO = "https://github.com/marco-jardim/radar-vereadores-niteroi"

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
}


def esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


def slug(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def data_br(iso: str | None) -> str:
    if not iso:
        return "—"
    a, m, d = iso.split("-")
    return f"{d}/{m}/{a}"


# ------------------------------------------------------------------------ modelo
def carregar_config() -> dict:
    return json.loads((RAIZ / "config" / "vereadores.json").read_text(encoding="utf-8"))


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
    origem = (autor.get("origem") or "").lower()
    return origem in ("", "vereador", "vereadora")


def montar_modelo() -> dict:
    cfg = carregar_config()
    legs = cfg["legislaturas"]
    proposicoes = carregar_proposicoes()
    cache_ia = json.loads((RAIZ / "data" / "classificacao_ia.json").read_text(encoding="utf-8")) if (RAIZ / "data" / "classificacao_ia.json").exists() else {}
    curadoria = carregar_curadoria()
    meta = json.loads((RAIZ / "data" / "meta.json").read_text(encoding="utf-8")) if (RAIZ / "data" / "meta.json").exists() else {}

    eleitos = {leg["id"]: {e["siscam"].upper(): e for e in leg["eleitos"]} for leg in legs}
    afast = defaultdict(list)
    for a in cfg.get("afastamentos", []):
        afast[(a["siscam"].upper(), a["legislatura"])].append(a)

    pessoas: dict[str, dict] = {}  # chave: slug do nome SISCAM
    projetos = []
    executivo = Counter()

    for p in proposicoes:
        correcao = (curadoria.get(p["numero"]) or {}).get("corrige")
        if correcao:  # lacunas do SISCAM corrigidas por curadoria, com fonte
            p = {**p, **correcao}
        cls = classificacao_final(p, cache_ia, curadoria)
        leg = legislatura_de(p.get("data") or p.get("data_protocolo"), p["ano"], legs)
        autores_ver = [a for a in p.get("autoria", []) if e_vereador(a, cfg["nao_vereador"])]
        if not autores_ver and p.get("autoria"):
            origem = (p["autoria"][0].get("origem") or "").lower()
            if "execut" in origem or any(n in p["autoria"][0]["nome"].upper() for n in ("RODRIGO NEVES", "AXEL GRAEL", "PREFEIT")):
                executivo[(leg, "apresentados")] += 1
                if p["desfecho"] == "virou_lei":
                    executivo[(leg, "leis")] += 1
        principal = next((a for a in autores_ver if a.get("papel", "").lower().startswith("autor")), autores_ver[0] if autores_ver else None)
        reg = {
            "id": p["id"],
            "numero": p["numero"],
            "ano": p["ano"],
            "data": p.get("data"),
            "ementa": p.get("ementa") or "",
            "situacao": p.get("situacao") or "",
            "desfecho": p["desfecho"],
            "lei": p.get("lei"),
            "url": p["url"],
            "legislatura": leg,
            "autores": [{"nome": a["nome"], "papel": a.get("papel", ""), "slug": slug(a["nome"])} for a in p.get("autoria", [])],
            "principal": slug(principal["nome"]) if principal else None,
            **cls,
        }
        projetos.append(reg)
        if not leg:
            continue
        for a in autores_ver:
            chave = slug(a["nome"])
            pessoa = pessoas.setdefault(chave, {"slug": chave, "nome_siscam": a["nome"], "mandatos": {}})
            m = pessoa["mandatos"].setdefault(leg, {"projetos_autor": [], "projetos_coautor": []})
            (m["projetos_autor"] if chave == reg["principal"] else m["projetos_coautor"]).append(reg)

    # metadados dos vereadores e métricas por legislatura
    for chave, pessoa in pessoas.items():
        nome_up = pessoa["nome_siscam"].upper()
        pessoa["nome"] = None
        for leg_id, m in pessoa["mandatos"].items():
            info = eleitos.get(leg_id, {}).get(nome_up)
            m["eleito"] = bool(info)
            m["partido"] = info["partido"] if info else ""
            m["afastamentos"] = afast.get((nome_up, leg_id), [])
            if info:
                pessoa["nome"] = info["nome"]
            m["metricas"] = metricas(m["projetos_autor"], m["projetos_coautor"])
        if not pessoa["nome"]:
            apelidos = {k.upper(): v for k, v in cfg.get("apelidos", {}).items()}
            pessoa["nome"] = apelidos.get(nome_up) or nome_curto(pessoa["nome_siscam"])

    # eleitos sem nenhum projeto ainda aparecem com zero
    for leg in legs:
        for e in leg["eleitos"]:
            chave = slug(e["siscam"])
            pessoa = pessoas.setdefault(chave, {"slug": chave, "nome_siscam": e["siscam"], "nome": e["nome"], "mandatos": {}})
            if leg["id"] not in pessoa["mandatos"]:
                pessoa["mandatos"][leg["id"]] = {
                    "projetos_autor": [], "projetos_coautor": [], "eleito": True, "partido": e["partido"],
                    "afastamentos": afast.get((e["siscam"].upper(), leg["id"]), []), "metricas": metricas([], []),
                }

    return {"legislaturas": legs, "pessoas": pessoas, "projetos": projetos, "executivo": executivo, "meta": meta, "curadoria": curadoria}


NOMES: dict[str, str] = {}  # slug -> nome de exibição, preenchido em main()
PARTICULAS = {"de", "da", "do", "das", "dos", "e"}
SUFIXOS = {"junior", "júnior", "filho", "neto", "sobrinho"}


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


def nome_exibicao(autor: dict) -> str:
    return NOMES.get(autor["slug"]) or nome_curto(autor["nome"])


def metricas(autor: list[dict], coautor: list[dict]) -> dict:
    leis = [p for p in autor if p["desfecho"] == "virou_lei"]
    return {
        "apresentados": len(autor),
        "coautorias": len(coautor),
        "leis": len(leis),
        "leis_substantivas": sum(1 for p in leis if p["categoria"] != "simbolica"),
        "leis_simbolicas": sum(1 for p in leis if p["categoria"] == "simbolica"),
        "andamento": sum(1 for p in autor if DESFECHO_GRUPO.get(p["desfecho"]) == "andamento"),
        "sem_exito": sum(1 for p in autor if DESFECHO_GRUPO.get(p["desfecho"]) == "sem_exito"),
        "simbolicos": sum(1 for p in autor if p["categoria"] == "simbolica"),
        "polemicos": sum(1 for p in autor if p["polemico"]),
        "risco_juridico": sum(1 for p in autor if p["risco_juridico"]),
        "leis_coautoria": sum(1 for p in coautor if p["desfecho"] == "virou_lei"),
    }


# -------------------------------------------------------------------------- HTML
def pagina(titulo: str, corpo: str, prefixo: str = "", descricao: str = "") -> str:
    desc = esc(descricao or "Quantos projetos de lei cada vereador de Niterói apresentou, quantos viraram lei e de que tipo. Dados do SISCAM da Câmara, atualizados toda semana.")
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
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=Public+Sans:ital,wght@0,400;0,600;1,400&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{prefixo}estilo.css">
<link rel="icon" href="{prefixo}favicon.svg" type="image/svg+xml">
</head>
<body>
<a class="pular" href="#conteudo">Ir para o conteúdo</a>
<header class="topo">
 <a class="marca" href="{prefixo}index.html">Radar dos Vereadores <span>Niterói</span></a>
 <nav aria-label="Principal">
  <a href="{prefixo}index.html">Vereadores</a>
  <a href="{prefixo}projetos.html">Projetos</a>
  <a href="{prefixo}alertas.html">Alertas</a>
  <a href="{prefixo}metodologia.html">Metodologia</a>
 </nav>
</header>
<main id="conteudo">
{corpo}
</main>
<footer class="rodape">
 <p>Dados públicos do <a href="https://consultaniteroi.siscam.com.br/">SISCAM da Câmara Municipal de Niterói</a>, coletados automaticamente toda semana. Código aberto sob GPL v3 no <a href="{REPO}">GitHub</a>. Encontrou um erro? <a href="{REPO}/issues/new">Abra uma issue</a>.</p>
</footer>
<script src="{prefixo}app.js" defer></script>
</body>
</html>
"""


def barra(m: dict, maximo: int) -> str:
    """Barra de produção: um segmento por desfecho, largura proporcional ao total apresentado."""
    total = m["apresentados"]
    if total == 0:
        return '<div class="barra vazia" role="img" aria-label="Nenhum projeto apresentado como autor"><span>nenhum projeto como autor</span></div>'
    seg = [
        ("sub", m["leis_substantivas"], "leis substantivas"),
        ("sim", m["leis_simbolicas"], "leis simbólicas"),
        ("and", m["andamento"], "em andamento"),
        ("sem", m["sem_exito"], "sem êxito"),
    ]
    largura = 100 * total / max(maximo, 1)
    rotulo = ", ".join(f"{n} {t}" for _, n, t in seg if n)
    partes = "".join(f'<i class="s-{c}" style="flex:{n}" title="{n} {t}"></i>' for c, n, t in seg if n)
    return f'<div class="barra" role="img" aria-label="{esc(total)} projetos como autor: {esc(rotulo)}"><div class="trilho" style="width:{largura:.1f}%">{partes}</div></div>'


def linha_vereador(pessoa: dict, leg: str, maximo: int, prefixo: str = "") -> str:
    m = pessoa["mandatos"][leg]
    me = m["metricas"]
    status = []
    if not m["eleito"]:
        status.append("suplente em exercício")
    if m["afastamentos"]:
        status.append("afastou-se para o Executivo")
    alerta = f'<span class="selo-alerta" title="Projetos com alerta de polêmica">{me["polemicos"]} com alerta</span>' if me["polemicos"] else ""
    dados = " ".join(f'data-{k.replace("_", "-")}="{v}"' for k, v in me.items())
    return f"""<li class="linha" {dados} data-nome="{esc(pessoa['nome'])}" data-eleito="{int(m['eleito'])}">
 <a class="quem" href="{prefixo}vereadores/{pessoa['slug']}.html"><strong>{esc(pessoa['nome'])}</strong> <span class="partido">{esc(m['partido'])}</span>{''.join(f'<span class="status">{esc(s)}</span>' for s in status)}</a>
 {barra(me, maximo)}
 <p class="numeros"><span><b>{me['leis_substantivas']}</b> {'lei substantiva' if me['leis_substantivas'] == 1 else 'leis substantivas'}</span> <span><b>{me['leis']}</b> {'lei' if me['leis'] == 1 else 'leis'} em {me['apresentados']} {'projeto' if me['apresentados'] == 1 else 'projetos'}</span>{alerta}</p>
</li>"""


LEGENDA = """<ul class="legenda" aria-label="Legenda da barra">
 <li><i class="s-sub"></i>Virou lei substantiva</li>
 <li><i class="s-sim"></i>Virou lei simbólica</li>
 <li><i class="s-and"></i>Em andamento</li>
 <li><i class="s-sem"></i>Arquivado, vetado, rejeitado ou retirado</li>
</ul>"""


def gerar_index(modelo: dict) -> str:
    legs = modelo["legislaturas"]
    atual = legs[-1]["id"]
    blocos = []
    for leg in reversed(legs):
        pessoas = [p for p in modelo["pessoas"].values() if leg["id"] in p["mandatos"]]
        pessoas.sort(key=lambda p: (-p["mandatos"][leg["id"]]["metricas"]["leis_substantivas"], -p["mandatos"][leg["id"]]["metricas"]["leis"], p["nome"]))
        maximo = max([p["mandatos"][leg["id"]]["metricas"]["apresentados"] for p in pessoas] + [1])
        ex = modelo["executivo"]
        tot = sum(p["mandatos"][leg["id"]]["metricas"]["apresentados"] for p in pessoas)
        leis = sum(p["mandatos"][leg["id"]]["metricas"]["leis"] for p in pessoas)
        zerados = [p["nome"] for p in pessoas if p["mandatos"][leg["id"]]["eleito"] and p["mandatos"][leg["id"]]["metricas"]["leis"] == 0]
        resumo = (
            f"<p class=\"resumo\">Na legislatura {esc(leg['id'])}, os vereadores apresentaram <b>{tot}</b> projetos de lei como autores principais e "
            f"<b>{leis}</b> viraram lei. O Executivo enviou <b>{ex[(leg['id'], 'apresentados')]}</b> projetos, dos quais "
            f"<b>{ex[(leg['id'], 'leis')]}</b> viraram lei."
            + (f" Eleitos sem nenhuma lei de autoria própria até agora: {esc(', '.join(zerados))}." if zerados else "")
            + "</p>"
        )
        linhas = "\n".join(linha_vereador(p, leg["id"], maximo) for p in pessoas)
        oculto = "" if leg["id"] == atual else " hidden"
        blocos.append(f"""<section class="legislatura" id="leg-{esc(leg['id'])}" data-leg="{esc(leg['id'])}"{oculto}>
{resumo}
<ol class="placar">{linhas}</ol>
</section>""")
    abas = "".join(
        f'<button type="button" role="tab" aria-selected="{"true" if l["id"] == atual else "false"}" data-alvo="leg-{esc(l["id"])}">{esc(l["id"])}</button>'
        for l in reversed(legs)
    )
    atualizado = (modelo["meta"].get("coleta") or {}).get("em", "")[:10]
    corpo = f"""<section class="abertura">
 <h1>O que cada vereador de Niterói apresentou, e o que virou lei.</h1>
 <p>Cada barra é a produção de um vereador como autor principal de projetos de lei. O comprimento é o total apresentado; as cores mostram o que aconteceu com eles. Leis simbólicas são homenagens, nomes de rua e datas comemorativas.</p>
 <p class="atualizacao">Dados do SISCAM atualizados em {data_br(atualizado) if atualizado else '—'}. <a href="metodologia.html">Como os números são calculados</a>.</p>
</section>
<div class="controles">
 <div role="tablist" aria-label="Legislatura" class="abas">{abas}</div>
 <label>Ordenar por
  <select id="ordem">
   <option value="leis-substantivas">Leis substantivas</option>
   <option value="leis">Total de leis</option>
   <option value="apresentados">Projetos apresentados</option>
   <option value="simbolicos">Projetos simbólicos</option>
   <option value="polemicos">Projetos com alerta</option>
   <option value="nome">Nome</option>
  </select>
 </label>
 <label class="check"><input type="checkbox" id="so-eleitos"> Só eleitos</label>
</div>
{LEGENDA}
{''.join(blocos)}"""
    return pagina("Radar dos Vereadores de Niterói", corpo)


def item_projeto(p: dict, prefixo: str = "") -> str:
    lei = p.get("lei") or {}
    lei_txt = f" · Lei {lei['numero']}" if lei.get("numero") else ""
    alertas = "".join(
        f'<span class="tag alerta" title="{esc(a.get("nota", ""))}">{esc(NOME_ALERTA.get(a["rotulo"], a["rotulo"]))}'
        f'<small>{"curadoria" if a["origem"] == "curadoria" else "IA " + str(int(a.get("confianca", 0) * 100)) + "%"}</small></span>'
        for a in p["alertas"]
    )
    sinais = "".join(f'<span class="tag sinal">{esc(NOME_SINAL.get(s, s))}</span>' for s in p["sinais"])
    autores = ", ".join(
        f'<a href="{prefixo}vereadores/{a["slug"]}.html">{esc(nome_exibicao(a))}</a>' + (" (autor)" if a["slug"] == p["principal"] and len(p["autores"]) > 1 else "")
        for a in p["autores"]
    )
    contestar = f'{REPO}/issues/new?title={esc("Classificação do PL " + p["numero"])}&body={esc("Projeto: " + p["url"])}'
    return f"""<li class="projeto d-{esc(DESFECHO_GRUPO.get(p['desfecho'], 'andamento'))}">
 <p class="cab"><a href="{esc(p['url'])}">PL {esc(p['numero'])}</a> <span>{data_br(p['data'])}</span> <span class="desfecho">{esc(NOME_DESFECHO.get(p['desfecho'], p['desfecho']))}{esc(lei_txt)}</span> <span class="cat">{esc(NOME_CATEGORIA.get(p['categoria'], p['categoria']))}</span></p>
 <p class="ementa">{esc(p['ementa'])}</p>
 <p class="autoria">{autores}</p>
 {('<p class="tags">' + alertas + sinais + f' <a class="contestar" href="{contestar}">contestar</a></p>') if (alertas or sinais) else ''}
</li>"""


def gerar_vereador(modelo: dict, pessoa: dict) -> str:
    secoes = []
    for leg in reversed(modelo["legislaturas"]):
        m = pessoa["mandatos"].get(leg["id"])
        if not m:
            continue
        me = m["metricas"]
        afast = "".join(
            f'<p class="aviso">Afastou-se da Câmara para o cargo de {esc(a["cargo"])} (<a href="{esc(a["fonte"])}">fonte</a>). Nesse período a cadeira foi ocupada por suplente.</p>'
            for a in m["afastamentos"]
        )
        cond = "Eleito" if m["eleito"] else "Suplente em exercício"
        proj = sorted(m["projetos_autor"], key=lambda p: (p["data"] or ""), reverse=True)
        leis_co = [p for p in m["projetos_coautor"] if p["desfecho"] == "virou_lei"]
        secoes.append(f"""<section class="mandato">
 <h2>{esc(leg['id'])} <span>{esc(cond)}{(' · ' + esc(m['partido'])) if m['partido'] else ''}</span></h2>
 {afast}
 {barra(me, max(me['apresentados'], 1))}
 <dl class="quadro">
  <div><dt>Projetos como autor</dt><dd>{me['apresentados']}</dd></div>
  <div><dt>Viraram lei</dt><dd>{me['leis']}</dd></div>
  <div><dt>Leis substantivas</dt><dd>{me['leis_substantivas']}</dd></div>
  <div><dt>Projetos simbólicos</dt><dd>{me['simbolicos']}</dd></div>
  <div><dt>Com alerta de polêmica</dt><dd>{me['polemicos']}</dd></div>
  <div><dt>Leis como coautor</dt><dd>{me['leis_coautoria']}</dd></div>
 </dl>
 <h3>Projetos como autor principal</h3>
 {'<ol class="projetos">' + ''.join(item_projeto(p, '../') for p in proj) + '</ol>' if proj else '<p class="vazio">Nenhum projeto de lei como autor principal nesta legislatura.</p>'}
 {('<h3>Leis aprovadas como coautor</h3><ol class="projetos">' + ''.join(item_projeto(p, '../') for p in leis_co) + '</ol>') if leis_co else ''}
</section>""")
    corpo = f"""<section class="abertura ficha">
 <p><a href="../index.html">Todos os vereadores</a></p>
 <h1>{esc(pessoa['nome'])}</h1>
 <p class="siscam">Nome no SISCAM: {esc(pessoa['nome_siscam'])}</p>
</section>
{LEGENDA}
{''.join(secoes)}"""
    return pagina(f"{pessoa['nome']} · Radar dos Vereadores de Niterói", corpo, "../",
                  f"Projetos de lei de {pessoa['nome']} na Câmara de Niterói: quantos apresentou, quantos viraram lei e de que tipo.")


def gerar_alertas(modelo: dict) -> str:
    projs = [p for p in modelo["projetos"] if p["polemico"] or p["risco_juridico"] or "inconstitucionalidade_declarada" in p["sinais"]]
    projs.sort(key=lambda p: (0 if any(a["origem"] == "curadoria" for a in p["alertas"]) else 1, p["data"] or ""), reverse=False)
    cur = [p for p in projs if any(a["origem"] == "curadoria" for a in p["alertas"]) or "inconstitucionalidade_declarada" in p["sinais"]]
    ia = [p for p in projs if p not in cur]
    ia.sort(key=lambda p: p["data"] or "", reverse=True)
    corpo = f"""<section class="abertura">
 <h1>Projetos com alerta</h1>
 <p>Projetos que restringem direitos de grupos, tratam de pauta de costumes, têm apelo populista ou risco jurídico. Os da primeira lista foram revisados à mão e têm fonte. Os da segunda foram marcados por IA a partir da ementa, com confiança mínima de 75%, e podem conter erros: cada um tem um link para contestar.</p>
 <p><a href="metodologia.html#alertas">Definições de cada alerta</a>.</p>
</section>
<section><h2>Revisados por curadoria</h2><ol class="projetos">{''.join(item_projeto(p) for p in cur) or '<li class="vazio">Nenhum.</li>'}</ol></section>
<section><h2>Marcados por IA</h2><ol class="projetos">{''.join(item_projeto(p) for p in ia) or '<li class="vazio">Nenhum projeto marcado por IA ainda.</li>'}</ol></section>"""
    return pagina("Projetos com alerta · Radar dos Vereadores de Niterói", corpo)


def gerar_projetos() -> str:
    corpo = """<section class="abertura">
 <h1>Todos os projetos de lei</h1>
 <p>Busque pela ementa, número ou nome do autor. A lista inclui projetos do Executivo e da Mesa Diretora.</p>
</section>
<form class="busca" role="search" onsubmit="return false">
 <label>Buscar <input type="search" id="q" placeholder="ex.: transporte, 1/2022, Benny"></label>
 <label>Desfecho
  <select id="f-desfecho"><option value="">Todos</option><option value="lei">Virou lei</option><option value="andamento">Em andamento</option><option value="sem_exito">Sem êxito</option></select>
 </label>
 <label>Categoria
  <select id="f-categoria"><option value="">Todas</option><option value="simbolica">Simbólica</option><option value="politica_publica">Política pública</option><option value="regulacao">Regulação</option><option value="administrativa_fiscal">Administrativa e fiscal</option><option value="outra">Outra</option></select>
 </label>
 <label>Ano <select id="f-ano"><option value="">Todos</option></select></label>
 <label class="check"><input type="checkbox" id="f-alerta"> Só com alerta</label>
</form>
<p id="contagem" class="contagem" aria-live="polite">Carregando projetos…</p>
<ol id="resultados" class="projetos"></ol>
<button type="button" id="mais" class="mais" hidden>Mostrar mais</button>"""
    return pagina("Projetos de lei · Radar dos Vereadores de Niterói", corpo)


def gerar_metodologia(modelo: dict) -> str:
    meta = modelo["meta"]
    cls = meta.get("classificacao") or {}
    defs_cat = "".join(f"<dt>{esc(NOME_CATEGORIA[k])}</dt><dd>{esc(v)}</dd>" for k, v in CATEGORIAS.items())
    defs_al = "".join(f"<dt>{esc(NOME_ALERTA[k])}</dt><dd>{esc(v)}</dd>" for k, v in ALERTAS.items())
    defs_sin = "".join(f"<dt>{esc(v)}</dt><dd>{esc(DESC_SINAL[k])}</dd>" for k, v in NOME_SINAL.items())
    corpo = f"""<section class="abertura texto">
<h1>Metodologia</h1>
<p>Este site mede a produção de cada vereador em projetos de lei, não seu trabalho inteiro. Indicações, requerimentos, fiscalização do Executivo, atuação em comissões e atendimento à população não entram nos números, e um vereador pode ser atuante nessas frentes com poucos projetos.</p>

<h2>De onde vêm os dados</h2>
<p>Toda semana, uma GitHub Action baixa do <a href="https://consultaniteroi.siscam.com.br/">SISCAM</a> a lista de projetos de lei de cada ano desde 2021 e, para cada projeto novo ou com tramitação alterada, a página de detalhe com autoria e tramitação completa. Nada é digitado à mão, exceto a composição das legislaturas e a curadoria, ambas em arquivos públicos no repositório.</p>

<h2>Como os números são contados</h2>
<ul>
 <li><b>Autor principal</b> é quem o SISCAM registra como "Autor". Os demais signatários são coautores. A barra e o ranking contam só autoria principal, para que projetos assinados em bloco por dez vereadores não inflem a produção de cada um.</li>
 <li><b>Virou lei</b>: o projeto foi sancionado, promulgado pela Câmara ou teve veto derrubado. O número e a data da lei vêm da tramitação.</li>
 <li><b>Legislatura</b>: o projeto conta na legislatura em que foi apresentado, mesmo que tenha virado lei depois.</li>
 <li><b>Suplentes</b>: quem assina projetos como vereador sem estar entre os eleitos aparece como suplente em exercício.</li>
 <li><b>Afastamentos</b> para cargos no Executivo vêm de notícias citadas em <code>config/vereadores.json</code>. O SISCAM não registra o período exato de licença.</li>
</ul>

<h2>Categoria do projeto</h2>
<p>Cada projeto recebe uma categoria. Ementas que batem com padrões de homenagem, nome de logradouro, data comemorativa, título ou patrimônio imaterial são classificadas como simbólicas por regra; as demais são classificadas por IA.</p>
<dl class="defs">{defs_cat}</dl>

<h2 id="sinais">Sinais objetivos da tramitação</h2>
<dl class="defs">{defs_sin}</dl>

<h2 id="alertas">Alertas</h2>
<p>Os alertas apontam projetos que merecem atenção. Eles valem igualmente para qualquer autor, partido ou espectro político, e cada um tem uma de duas origens:</p>
<ul>
 <li><b>Curadoria</b>: revisado à mão, com pelo menos uma fonte pública, em <a href="{REPO}/blob/main/config/curadoria.json"><code>config/curadoria.json</code></a>. A curadoria prevalece sobre a IA.</li>
 <li><b>IA</b>: o modelo <code>{esc(cls.get('modelo', '—'))}</code>, via OpenCode Go, lê só a ementa e aplica as definições abaixo. Só aparece no site o alerta com confiança de pelo menos 75%. O prompt completo está em <a href="{REPO}/blob/main/coletor/classificar.py"><code>coletor/classificar.py</code></a> (versão {esc(cls.get('versao_prompt', '—'))}).</li>
</ul>
<dl class="defs">{defs_al}</dl>
<p>"Com alerta de polêmica" soma restrição de direitos, pauta de costumes e apelo populista. Risco de inconstitucionalidade aparece à parte, porque é comum em projetos municipais de todos os campos.</p>

<h2>Limitações</h2>
<ul>
 <li>A ementa é um resumo. A IA não lê o texto integral nem o contexto político, e pode errar nos dois sentidos.</li>
 <li>Quantidade de projetos não é qualidade. Um único projeto bem feito pode valer mais que dezenas de homenagens; por isso o site separa leis substantivas de simbólicas.</li>
 <li>O SISCAM às vezes registra autoria ou situação de forma incompleta. Erros de origem passam para cá.</li>
</ul>

<h2>Contestar ou corrigir</h2>
<p>Cada projeto com alerta tem um link "contestar", que abre uma issue no GitHub. Correções na composição das legislaturas e na curadoria podem ser enviadas como pull request.</p>
</section>"""
    return pagina("Metodologia · Radar dos Vereadores de Niterói", corpo)


DESC_SINAL = {
    "parecer_contrario_ccj": "A Comissão de Constituição e Justiça deu parecer contrário.",
    "rejeitado_plenario": "O plenário votou contra o projeto.",
    "veto_total": "O prefeito vetou o projeto inteiro.",
    "veto_parcial": "O prefeito vetou parte do projeto.",
    "veto_derrubado": "A Câmara derrubou o veto do prefeito e a lei foi promulgada.",
    "inconstitucionalidade_declarada": "A Justiça declarou a lei inconstitucional (registrado por curadoria, com fonte).",
}


def dados_busca(modelo: dict) -> list[dict]:
    return [
        {
            "n": p["numero"], "a": p["ano"], "d": p["data"], "e": p["ementa"], "u": p["url"],
            "x": p["desfecho"], "g": DESFECHO_GRUPO.get(p["desfecho"], "andamento"), "dx": NOME_DESFECHO.get(p["desfecho"], p["desfecho"]),
            "c": p["categoria"], "cx": NOME_CATEGORIA.get(p["categoria"], p["categoria"]),
            "l": (p.get("lei") or {}).get("numero"),
            "au": [[nome_exibicao(a), a["slug"], a["slug"] == p["principal"]] for a in p["autores"]],
            "al": [[NOME_ALERTA.get(a["rotulo"], a["rotulo"]), a["origem"], a.get("confianca"), a.get("nota", "")] for a in p["alertas"]],
            "s": [NOME_SINAL.get(s, s) for s in p["sinais"]],
        }
        for p in sorted(modelo["projetos"], key=lambda p: p["data"] or "", reverse=True)
    ]


def main() -> None:
    modelo = montar_modelo()
    NOMES.update({s: p["nome"] for s, p in modelo["pessoas"].items()})
    if SAIDA.exists():
        shutil.rmtree(SAIDA)
    (SAIDA / "vereadores").mkdir(parents=True)
    (SAIDA / "dados").mkdir()
    for arq in FONTE_ESTATICA.iterdir():
        shutil.copy(arq, SAIDA / arq.name)
    (SAIDA / "index.html").write_text(gerar_index(modelo), encoding="utf-8")
    (SAIDA / "projetos.html").write_text(gerar_projetos(), encoding="utf-8")
    (SAIDA / "alertas.html").write_text(gerar_alertas(modelo), encoding="utf-8")
    (SAIDA / "metodologia.html").write_text(gerar_metodologia(modelo), encoding="utf-8")
    for pessoa in modelo["pessoas"].values():
        (SAIDA / "vereadores" / f"{pessoa['slug']}.html").write_text(gerar_vereador(modelo, pessoa), encoding="utf-8")
    (SAIDA / "dados" / "projetos.json").write_text(json.dumps(dados_busca(modelo), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    resumo = {
        leg["id"]: {
            p["nome"]: {"partido": p["mandatos"][leg["id"]]["partido"], "eleito": p["mandatos"][leg["id"]]["eleito"], **p["mandatos"][leg["id"]]["metricas"]}
            for p in modelo["pessoas"].values() if leg["id"] in p["mandatos"]
        }
        for leg in modelo["legislaturas"]
    }
    (SAIDA / "dados" / "vereadores.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=1), encoding="utf-8")
    (SAIDA / ".nojekyll").write_text("")
    print(f"site gerado: {len(modelo['pessoas'])} vereadores, {len(modelo['projetos'])} projetos")


if __name__ == "__main__":
    main()
