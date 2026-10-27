"""Blocos HTML da página inicial: paisagem de abertura, vereadores, mapa e linha do tempo.

Funções puras: recebem o modelo (ou a memória) e devolvem HTML escapado e determinístico.
Um bloco sem dados devolve "", para a página omitir a seção inteira.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import coletor.site.paginas as P

H1_INICIO = "Leis que mudam a cidade, e quem as escreveu."
# Camadas da paisagem, do fundo para a frente; cada uma usa site_src/paisagem/<camada>.svg como máscara.
CAMADAS = ("sol", "fundo", "baia", "promontorio", "orla")


# ---------------------------------------------------------------- abertura
def texto_abertura(modelo: dict) -> str:
    """Parágrafo de abertura da página inicial, com o mesmo texto de gerar_index."""
    total = len(modelo.get("projetos") or [])
    return (f"Desde 2021, a Câmara de Niterói analisou mais de {P.milhar(total // 100 * 100)} projetos de lei. "
            "Este site separa as leis com efeito real das homenagens, das leis que só autorizam o prefeito e das pautas "
            "polêmicas, e mostra quem fez cada uma.")


def atualizacao_txt(modelo: dict) -> str:
    """Data da última coleta no formato DD/MM/AAAA, ou travessão se ausente."""
    atualizado = ((modelo.get("meta") or {}).get("coleta") or {}).get("em", "")[:10]
    return P.data_br(atualizado) if atualizado else "—"


def camada(nome: str, url_estatica: Callable[[str], str]) -> str:
    """Div de uma camada da paisagem; omitida se o SVG da máscara não existir na árvore estática."""
    arquivo = f"paisagem/{nome}.svg"
    if not (P.FONTE_ESTATICA / arquivo).is_file():
        return ""
    return f'<div class="camada {nome}" style="--mascara:url(\'{P.esc(url_estatica(arquivo))}\')"></div>'


def hero(modelo: dict, url_estatica: Callable[[str], str]) -> str:
    """Abertura com a paisagem em camadas decorativas; proporção e cores ficam no CSS."""
    camadas = "".join(camada(nome, url_estatica) for nome in CAMADAS)
    return (f'<section class="hero" aria-labelledby="t-hero">'
            f'<div class="ceu" data-ceu="tarde" aria-hidden="true">{camadas}</div>'
            f'<div class="hero-texto"><h1 id="t-hero">{P.esc(H1_INICIO)}</h1>'
            f'<p>{P.esc(texto_abertura(modelo))}</p>'
            f'<p class="atualizacao">Dados do SISCAM de {P.esc(atualizacao_txt(modelo))} · '
            f'<a href="metodologia.html">como classificamos</a></p></div></section>')


# ---------------------------------------------------------------- vereadores
def membros_atuais(modelo: dict) -> list[dict]:
    """Pessoas com mandato na legislatura atual (mesma definição da 404), em ordem alfabética sem acentos."""
    legislaturas = modelo.get("legislaturas") or []
    if not legislaturas:
        return []
    atual = legislaturas[-1]["id"]
    return sorted((p for p in (modelo.get("pessoas") or {}).values() if atual in (p.get("mandatos") or {})),
                  key=lambda p: (P._chave_nome(p["nome"]), p["nome"], p["slug"]))


def quem_e_meu_vereador(modelo: dict, prefixo: str = "") -> str:
    """Lista de todos os vereadores da legislatura atual; base do combobox de site_src (melhoria progressiva)."""
    pessoas = membros_atuais(modelo)
    if not pessoas:
        return ""
    atual = modelo["legislaturas"][-1]["id"]
    itens = []
    for p in pessoas:
        mandato = p["mandatos"][atual] or {}
        partido = mandato.get("partido") or ""
        extra = f' <span class="partido">{P.esc(partido)}</span>' if partido else ""
        if mandato.get("eleito") is False:
            extra += ' <span class="status">suplente em exercício</span>'
        itens.append(f'<li><a href="{P.esc(prefixo)}vereadores/{P.esc(p["slug"])}.html">{P.esc(p["nome"])}</a>{extra}</li>')
    n = len(pessoas)
    resumo = "Ver o vereador da legislatura atual" if n == 1 else f"Ver os {n} vereadores da legislatura atual"
    return (f'<section class="quem-vereador" data-combobox aria-labelledby="t-quem">'
            f'<h2 id="t-quem" class="h-secao">Quem é meu vereador?</h2>'
            f'<p>Em Niterói, os vereadores são eleitos pelo voto de toda a cidade, sem divisão por bairro. '
            f'A página de cada um reúne projetos de lei, atividades, presença e votos na legislatura '
            f'{P.esc(atual)} e nas anteriores.</p>'
            f'<details class="lista-vereadores"><summary>{P.esc(resumo)}</summary>'
            f'<ul id="lista-vereadores">{"".join(itens)}</ul></details></section>')


# ---------------------------------------------------------------- mapa
def mapa_home(modelo: dict) -> str:
    """Mapa das indicações da legislatura atual; reusa mapa_indicacoes, que já traz atribuição OSM e data da base."""
    if not modelo.get("geo_bairros"):
        return ""
    legislaturas = modelo.get("legislaturas") or []
    if not legislaturas:
        return ""
    atual = legislaturas[-1]["id"]
    docs = [d for d in modelo.get("documentos") or [] if d.get("legislatura") == atual]
    if not P.resumo_bairros(docs)["indicacoes"]:
        return ""
    mapa = P.mapa_indicacoes(modelo, docs, f"Indicações por bairro, legislatura {atual}")
    if not mapa:
        return ""
    return (f'<section class="mapa-home" aria-labelledby="t-mapa-home">'
            f'<h2 id="t-mapa-home" class="h-secao">Bairros citados nas indicações</h2>'
            f'<p class="explica">Indicações são pedidos dos vereadores ao Executivo. O mapa conta as da legislatura '
            f'{P.esc(atual)} pelo bairro citado na ementa; não mostra quais pedidos foram atendidos.</p>'
            f'{mapa}'
            f'<p><a href="atividades.html#bairros">Ver os bairros das indicações em Atividades</a></p></section>')


# ---------------------------------------------------------------- linha do tempo
def carregar_memoria(raiz: Path) -> dict | None:
    """Conteúdo editorial de config/memoria.json; None se o arquivo não existir."""
    caminho = raiz / "config" / "memoria.json"
    if not caminho.is_file():
        return None
    return json.loads(caminho.read_text(encoding="utf-8"))


def data_memoria(valor: str) -> str:
    """AAAA-MM-DD vira DD/MM/AAAA; AAAA-MM vira MM/AAAA; AAAA fica como está."""
    partes = str(valor).split("-")
    return "/".join(reversed(partes))


def fontes_evento(fontes: list[dict] | None) -> str:
    """Links pequenos para as fontes; só URLs HTTPS viram link."""
    itens = []
    for f in fontes or []:
        titulo = P.esc(f.get("titulo") or f.get("url") or "")
        url = f.get("url") or ""
        itens.append(f'<a href="{P.esc(url)}">{titulo}</a>' if url.startswith("https://") else titulo)
    itens = [i for i in itens if i]
    return f'<p class="fontes"><small>Fontes: {", ".join(itens)}</small></p>' if itens else ""


def linha_do_tempo(memoria: dict | None) -> str:
    """Eventos da memória em ordem cronológica (estável para datas iguais)."""
    eventos = [e for e in ((memoria or {}).get("linha_do_tempo") or []) if e.get("data")]
    if not eventos:
        return ""
    eventos = sorted(eventos, key=lambda e: (str(e["data"]), str(e.get("data_fim") or "")))
    itens = []
    for e in eventos:
        quando = data_memoria(e["data"])
        if e.get("data_fim"):
            quando += "–" + data_memoria(e["data_fim"])
        itens.append(f'<li><time datetime="{P.esc(e["data"])}">{P.esc(quando)}</time> '
                     f'<strong>{P.esc(e.get("titulo") or "")}</strong> '
                     f'<p>{P.esc(e.get("texto") or "")}</p>{fontes_evento(e.get("fontes"))}</li>')
    return (f'<section class="linha-tempo" aria-labelledby="t-linha">'
            f'<h2 id="t-linha" class="h-secao">Niterói no tempo</h2>'
            f'<div class="tabela-rolavel linha-rolavel" role="region" tabindex="0" aria-labelledby="t-linha">'
            f'<ol>{"".join(itens)}</ol></div></section>')
