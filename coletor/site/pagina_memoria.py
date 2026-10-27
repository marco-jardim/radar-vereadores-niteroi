"""Página editorial de pessoas e marcos ligados à memória de Niterói."""
from __future__ import annotations

from xml.etree import ElementTree

import coletor.site.paginas as P


DESCRICOES_EMBLEMAS = {
    "arariboia": "canoa e arco sobre a linha da baía",
    "vital-brazil": "serpente estilizada e frasco",
    "antonio-parreiras": "paleta e moldura com horizonte",
    "ismael-silva": "pandeiro e pauta",
    "oscar-niemeyer": "a curva do MAC sobre a rampa",
}


def _data(iso: str) -> str:
    """Formata datas completas, preservando anos sem inventar dia ou mês."""
    return P.data_br(iso) if len(iso.split("-")) == 3 else iso


def _fontes(fontes: list[dict]) -> str:
    if not fontes:
        return ""
    return '<ul class="memoria-fontes">' + "".join(
        f'<li><a href="{P.esc(fonte["url"])}">{P.esc(fonte["titulo"])}</a></li>'
        for fonte in fontes
    ) + "</ul>"


def _homenageado(pessoa: dict) -> str:
    identificador = P.esc(pessoa["id"])
    nome = P.esc(pessoa["nome"])
    emblema = ""
    arquivo = pessoa.get("emblema")
    if arquivo and (P.FONTE_ESTATICA / "memoria" / arquivo).is_file():
        descricao = DESCRICOES_EMBLEMAS.get(pessoa["id"], "ilustração própria do projeto")
        caixa = ElementTree.parse(P.FONTE_ESTATICA / "memoria" / arquivo).getroot().get("viewBox")
        viewbox = f' viewBox="{P.esc(caixa)}"' if caixa else ""
        emblema = (
            f'<svg class="emblema"{viewbox} role="img" aria-labelledby="e-{identificador}">'
            f'<title id="e-{identificador}">Emblema de {nome}: {P.esc(descricao)}</title>'
            f'<use href="{P.esc(P.url_estatica("memoria/" + arquivo))}#emblema"/></svg>'
        )
    completo = pessoa.get("nome_completo")
    nome_completo = (f'<p class="nome-completo">{P.esc(completo)}</p>'
                     if completo and completo != pessoa["nome"] else "")
    datas = []
    for campo, rotulo in (("nascimento", "Nascimento"), ("morte", "Morte")):
        texto = pessoa.get(campo + "_texto")
        if texto or pessoa.get(campo):
            datas.append(f'{rotulo}: {P.esc(texto or _data(pessoa[campo]))}')
    datas_html = f'<p class="datas-vida">{" · ".join(datas)}</p>' if datas else ""
    vinculo = f'<p class="vinculo">{P.esc(pessoa["vinculo"])}</p>' if pessoa.get("vinculo") else ""
    biografia = ("<ul>" + "".join(f"<li>{P.esc(item)}</li>" for item in pessoa["biografia"]) + "</ul>"
                 if pessoa.get("biografia") else "")
    lugar = (f'<p class="lugar-memoria"><strong>Lugar de memória:</strong> {P.esc(pessoa["lugar_de_memoria"])}</p>'
             if pessoa.get("lugar_de_memoria") else "")
    fontes = _fontes(pessoa.get("fontes", []))
    return (f'<article id="{identificador}" class="homenageado" aria-labelledby="h-{identificador}">'
            f'{emblema}<h2 id="h-{identificador}">{nome}</h2>{nome_completo}{datas_html}{vinculo}'
            f'{biografia}{lugar}' + (f'<h3>Fontes</h3>{fontes}' if fontes else "") + '</article>')


def _evento(evento: dict) -> str:
    data = evento["data"]
    periodo = f'<time datetime="{P.esc(data)}">{P.esc(_data(data))}</time>'
    if evento.get("data_fim"):
        fim = evento["data_fim"]
        periodo += f'–<time datetime="{P.esc(fim)}">{P.esc(_data(fim))}</time>'
    fontes = _fontes(evento.get("fontes", []))
    return (f'<li>{periodo}<h3>{P.esc(evento["titulo"])}</h3><p>{P.esc(evento["texto"])}</p>'
            + (f'<p class="fontes-rotulo">Fontes:</p>{fontes}' if fontes else "") + '</li>')


def gerar_memoria(memoria: dict | None) -> str | None:
    """Gera a página completa, ou omite a memória quando não há homenageados."""
    if not memoria or not memoria.get("homenageados"):
        return None
    criterios = (f'<section class="memoria-secao" aria-label="Critérios"><h2>Critérios</h2>'
                 f'<p>{P.esc(memoria["criterios"])}</p></section>' if memoria.get("criterios") else "")
    eventos = "".join(_evento(evento) for evento in memoria.get("linha_do_tempo", []))
    linha = (f'<section class="memoria-secao" aria-label="Linha do tempo"><h2>Linha do tempo</h2>'
             f'<ol class="linha-tempo-completa">{eventos}</ol></section>' if eventos else "")
    corpo = (
        '<div class="memoria">'
        '<section class="memoria-abertura"><h1>Cidade Sorriso</h1>'
        '<p>Niterói é chamada de Cidade Sorriso. Esta página reúne pessoas ligadas à cidade '
        'e uma linha do tempo de sua história, com fontes para consulta.</p></section>'
        f'{criterios}<div class="memoria-pessoas">'
        + "".join(_homenageado(pessoa) for pessoa in memoria["homenageados"])
        + f'</div>{linha}'
        '<section class="memoria-secao" aria-label="Créditos"><h2>Créditos</h2>'
        '<p>Os emblemas e a textura de azulejos são ilustrações próprias do projeto.</p>'
        '<p>Fontes tipográficas Barlow Condensed, Public Sans e Fraunces: '
        'SIL Open Font License (OFL) 1.1.</p></section>'
        f'<p>Encontrou um erro? <a href="{P.esc(P.REPO + "/issues/new")}">Abra uma issue</a>.</p></div>'
    )
    pagina = P.pagina(
        "Cidade Sorriso", corpo, ativo="", caminho="memoria.html",
        descricao="Pessoas ligadas a Niterói, critérios de homenagem e marcos da história da Cidade Sorriso.",
        estilos=("memoria.css",),
    )
    # Fraunces é pré-carregada só nesta página editorial.
    links = []
    fonte = "fontes/fraunces-latin-wght-normal.woff2"
    if (P.FONTE_ESTATICA / fonte).is_file():
        links.append(f'<link rel="preload" as="font" type="font/woff2" crossorigin href="{P.esc(P.url_estatica(fonte))}">')
    return pagina.replace("</head>", "\n".join(links) + "\n</head>", 1)
