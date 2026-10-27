"""Blocos HTML da página inicial: paisagem de abertura, vereadores, mapa e linha do tempo.

Funções puras: recebem o modelo (ou a memória) e devolvem HTML escapado e determinístico.
Um bloco sem dados devolve "", para a página omitir a seção inteira.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from xml.etree import ElementTree

import coletor.site.paginas as P

H1_INICIO = "Leis que mudam a cidade, e quem as escreveu."
# Camadas da paisagem, do fundo para a frente; cada uma usa site_src/paisagem/<camada>.svg como máscara.
# O sol (ou a lua) não é camada: é o .ceu::before de inicio.css.
CAMADAS = ("fundo", "baia", "promontorio", "orla")
# Fase do céu antes da primeira pintura, logo depois do .ceu, para não piscar a fase "tarde" do servidor.
# Mesma tabela de FASES em site_src/inicio.js (início inclusivo, fim exclusivo; conferida em
# tests/test_inicio.py) e mesmo fallback UTC−3; hour12:!1 pode dar "24" à meia-noite, daí o %24.
# Bloco com let: nada vaza para o escopo global. Até 300 bytes.
SCRIPT_CEU = ('{let d=new Date,h;try{try{h=new Intl.DateTimeFormat("en",{timeZone:"America/Sao_Paulo",'
              'hour:"numeric",hour12:!1}).format(d)%24}catch(e){}h>=0||(h=(d.getUTCHours()+21)%24);'
              'document.querySelector(".ceu").dataset.ceu=h<6?"madrugada":h<12?"manha":h<17?"tarde":'
              'h<19?"por-do-sol":"noite"}catch(e){}}')


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
            f'<div class="ceu" data-ceu="tarde" aria-hidden="true">{camadas}</div><script>{SCRIPT_CEU}</script>'
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


def resumo_lista(eleitos: int, suplentes: int) -> str:
    """Rótulo do <details>: eleitos e suplentes em exercício, com singular e plural."""
    def contagem(n: int, singular: str, plural: str) -> str:
        return f"{n} {singular if n == 1 else plural}"

    if not suplentes:
        return "Ver o vereador eleito nesta legislatura" if eleitos == 1 else f"Ver os {eleitos} vereadores eleitos nesta legislatura"
    total = eleitos + suplentes
    return (f"Ver os {total} que exerceram mandato nesta legislatura "
            f"({contagem(eleitos, 'eleito', 'eleitos')} e {contagem(suplentes, 'suplente', 'suplentes')})")


# Campo do combobox já no HTML, para não deslocar o layout quando inicio.js o ativa; oculto sem JS (inicio.css).
CAMPO_BUSCA = ('<div class="cb-campo"><label for="cb-vereadores" id="cb-vereadores-rotulo">Digite o nome do vereador</label>'
               '<input id="cb-vereadores" type="text" role="combobox" aria-autocomplete="list" aria-expanded="false" '
               'aria-controls="cb-vereadores-lista" autocomplete="off">'
               '<ul role="listbox" id="cb-vereadores-lista" aria-labelledby="cb-vereadores-rotulo" hidden></ul>'
               '<p class="so-leitor" aria-live="polite" id="cb-vereadores-status"></p></div>')


def quem_e_meu_vereador(modelo: dict, prefixo: str = "") -> str:
    """Lista de todos os vereadores da legislatura atual; base do combobox de site_src (melhoria progressiva)."""
    pessoas = membros_atuais(modelo)
    if not pessoas:
        return ""
    atual = modelo["legislaturas"][-1]["id"]
    itens = []
    suplentes = 0
    for p in pessoas:
        mandato = p["mandatos"][atual] or {}
        partido = mandato.get("partido") or ""
        extra = f' <span class="partido">{P.esc(partido)}</span>' if partido else ""
        if mandato.get("eleito") is False:
            suplentes += 1
            extra += ' <span class="status">suplente em exercício</span>'
        itens.append(f'<li><a href="{P.esc(prefixo)}vereadores/{P.esc(p["slug"])}.html">{P.esc(p["nome"])}</a>{extra}</li>')
    resumo = resumo_lista(len(pessoas) - suplentes, suplentes)
    return (f'<section class="quem-vereador" data-combobox aria-labelledby="t-quem">'
            f'<h2 id="t-quem" class="h-secao">Quem é meu vereador?</h2>'
            f'<p>Em Niterói, os vereadores são eleitos pelo voto de toda a cidade, sem divisão por bairro. '
            f'A página de cada um reúne projetos de lei, atividades, presença e votos na legislatura '
            f'{P.esc(atual)} e nas anteriores.</p>'
            f'{CAMPO_BUSCA}'
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
    def tempo(valor: str) -> str:
        return f'<time datetime="{P.esc(valor)}">{P.esc(data_memoria(valor))}</time>'

    for e in eventos:
        # Intervalo com um <time> por ponta; o <span> mantém as datas juntas no cartão em coluna.
        quando = tempo(e["data"]) + ("–" + tempo(e["data_fim"]) if e.get("data_fim") else "")
        itens.append(f'<li><span class="quando">{quando}</span> '
                     f'<strong>{P.esc(e.get("titulo") or "")}</strong> '
                     f'<p>{P.esc(e.get("texto") or "")}</p>{fontes_evento(e.get("fontes"))}</li>')
    return (f'<section class="linha-tempo" aria-labelledby="t-linha">'
            f'<h2 id="t-linha" class="h-secao">Niterói no tempo</h2>'
            f'<div class="tabela-rolavel linha-rolavel" role="region" tabindex="0" '
            f'aria-label="Linha do tempo, role na horizontal">'
            f'<ol>{"".join(itens)}</ol></div></section>')


# ---------------------------------------------------------------- memória
def faixa_memoria(memoria: dict | None, prefixo: str = "") -> str:
    """Pessoas da página de memória; sem homenageados, omite a faixa inteira."""
    pessoas = (memoria or {}).get("homenageados") or []
    if not pessoas:
        return ""
    itens = []
    for pessoa in pessoas:
        identificador = P.esc(pessoa["id"])
        nome = P.esc(pessoa["nome"])
        arquivo = pessoa.get("emblema")
        emblema = ""
        if arquivo and (P.FONTE_ESTATICA / "memoria" / arquivo).is_file():
            caixa = ElementTree.parse(P.FONTE_ESTATICA / "memoria" / arquivo).getroot().get("viewBox")
            viewbox = f' viewBox="{P.esc(caixa)}"' if caixa else ""
            emblema = (f'<svg class="emblema"{viewbox} aria-hidden="true" focusable="false">'
                       f'<use href="{P.esc(P.url_estatica("memoria/" + arquivo, prefixo))}#emblema"/></svg>')
        itens.append(f'<li><a href="{P.esc(prefixo)}memoria.html#{identificador}">{emblema}<span>{nome}</span></a></li>')
    return (f'<section class="faixa-memoria" aria-labelledby="fm-titulo">'
            f'<h2 id="fm-titulo" class="h-secao">Niterói que nos inspira</h2>'
            f'<ul>{"".join(itens)}</ul><p><a href="{P.esc(prefixo)}memoria.html">'
            f'Conheça a Memória de Niterói</a></p></section>')
