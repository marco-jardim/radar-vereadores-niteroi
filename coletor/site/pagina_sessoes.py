"""Apresentação das sessões, com melhoria progressiva opcional no navegador.

Consome apenas o contrato de modelo["sessoes"]. As regras e a agregação ficam
fora deste módulo; os mesmos sentidos e bases são usados nas duas páginas.
"""
from __future__ import annotations

import re
from collections import defaultdict
from urllib.parse import urlencode

from coletor.regras_sessoes import rotulo_voto
from coletor.site import graficos as G
from coletor.site import paginas as P
from coletor.site.modelo import nome_curto


# Contrato de melhoria progressiva (o servidor não depende de JS):
# - #filtros-sessoes-<leg>.filtros.filtros-sessoes[data-leg] nasce hidden.
#   Nomes: ano (todos|ano), classe (dividida|dissenso|todas), materia
#   (todas|veto|pl|pdl|resolucao|outra), vereador (vazio|slug), div, q,
#   ordem (recente|antigo|apertada); botões data-acao=limpar|csv|mais.
# - #lista-votacoes-<leg>.votacoes contém as primeiras LIMITE_CARTOES
#   divididas, recentes primeiro, de todos os anos; .mais-votacoes guarda
#   a continuação sem JS. Ao hidratar, substituir a lista e essa continuação.
#   #contagem-votacoes-<leg>[aria-live=polite]; botão mais começa hidden.
# - cartao_votacao(modelo, v) é o componente público a espelhar no cliente:
#   li.projeto.votacao#v-<id>[data-ano|materia|classe|sentido|qualidade];
#   p.cab (documento, data, sessão), p.desfecho, p.ementa, .mini-barra,
#   p.mini-n; opcionais p.quorum, p.fonte-sentido, p.qualidade-voto;
#   details.votos-nomes > summary + .grupo-votos (h4 e p com .chip),
#   ações SISCAM, a.contestar e details.notas-conferencia. Inconsistentes
#   nunca atribuem votos a nomes. Textos e atributos sempre escapados.
# - #faixa-<leg>.faixa-votos[data-ano] contém legenda, região rolável com
#   table.faixa e resumo. Só o ano mais recente com divididas vem no HTML.
#   .faixa-sem-comparacao marca colunas sem maioria/sentido/consistência;
#   .voto-maioria|diferente|abstencao|ausente|presidia|vazio|cru nas células.
#   tr[data-vereador] identifica a composição sem promover nomes brutos dos votos.
#   O cliente (site_src/sessoes.js) preserva glifos + .so-leitor, cabeçalhos e ordem alfabética.


# ---- componentes -------------------------------------------------------------
LIMITE_CARTOES = 40
PRESENCA = (
    ("P", "presente", "●", "Presença"),
    ("C", "consignado", "◆", "Consignado: registro da Mesa"),
    ("V", "votou-ausente", "▲", "Ausente na abertura, com voto registrado"),
    ("J", "justificada", "◇", "Ausência justificada"),
    ("A", "ausente", "○", "Ausência"),
)
MATERIAS = {"veto": "Vetos", "pl": "Projetos de lei", "pdl": "Projetos de decreto legislativo",
            "resolucao": "Projetos de resolução", "outra": "Outras matérias"}
VOTOS_FAIXA = {
    "maioria": ("■", "com a maioria"), "diferente": ("◆", "diferente da maioria"),
    "abstencao": ("◐", "abstenção"), "ausente": ("·", "ausente"),
    "presidia": ("P", "presidia"), "vazio": ("", "fora do mandato/não consta"),
}
TIPOS = {"ordinaria": "Ordinárias", "extraordinaria": "Extraordinárias", "solene": "Solenes",
         "especial": "Especiais", "desconhecido": "Tipo não identificado"}
SENTIDOS = {"favor_mantem", "favor_derruba", "favor_aprova", "favor_rejeita"}


def _valor(mapa: dict, chave, padrao=None):
    """Anos podem ser inteiros no modelo ou chaves de um JSON sintético."""
    return mapa.get(chave, mapa.get(str(chave), padrao))


def _anos(dados: dict) -> list[int]:
    return sorted(int(a) for a in dados.get("anos") or [])


def _periodo(dados: dict) -> str:
    anos = _anos(dados)
    if not anos:
        return "sem período coletado"
    return str(anos[0]) if len(anos) == 1 else f"{anos[0]}–{anos[-1]}"


def _legs(dados: dict) -> list[dict]:
    return sorted(dados.get("legislaturas") or [],
                  key=lambda l: (max(l.get("anos") or [0]), str(l["id"])), reverse=True)


def _ano(item: dict) -> int | None:
    data = str(item.get("data") or "")
    return int(data[:4]) if re.match(r"^\d{4}-", data) else None


def _da_leg(itens: list[dict], leg: dict) -> list[dict]:
    return [i for i in itens if _ano(i) in {int(a) for a in leg.get("anos") or []}]


def _recentes(itens: list[dict]) -> list[dict]:
    return sorted(itens, key=lambda v: (v.get("data") or "", str(v.get("id") or "")), reverse=True)


def _pct(valor) -> str:
    return "—" if valor is None else f"{G._fmt(valor)}%"


def _compareceu(presenca: dict, afastado: bool = False) -> str:
    base = presenca.get("denominador", 0)
    texto = f"{presenca.get('presentes', 0)} de {base}"
    if afastado and base < 10:
        return texto + " sessões em exercício"
    return f"{_pct(presenca['pct'])} · {texto}" if base >= 10 and presenca.get("pct") is not None else texto


def _nota_presenca(presenca: dict) -> str:
    notas = []
    if presenca.get("J", 0):
        notas.append(P.plural(presenca["J"], "justificada", "justificadas"))
    if presenca.get("L", 0):
        notas.append(P.plural(presenca["L"], "licença", "licenças") + " (fora da base)")
    return " · ".join(notas)


def _contestar(titulo: str, contexto: str = "") -> str:
    consulta = urlencode({"title": f"Sessões: {titulo}", "body": contexto})
    return f'<a class="contestar" href="{P.REPO}/issues/new?{P.esc(consulta)}">contestar</a>'


def _pessoa(modelo: dict, slug: str, leg_id: str | None = None) -> dict:
    """Suplentes sem página têm nome e condição no agregado das sessões."""
    pessoa = (modelo.get("pessoas") or {}).get(slug)
    if pessoa:
        return pessoa
    entrada = (((modelo.get("sessoes") or {}).get("por_pessoa") or {}).get(slug)) or {}
    # Os metadados podem acompanhar a pessoa ou o registro da legislatura.
    registro = (entrada.get(leg_id) or {}) if leg_id else next(
        (r for r in entrada.values() if isinstance(r, dict) and r.get("sem_pagina")), {})
    return {**registro, **entrada, "nome": entrada.get("nome") or registro.get("nome") or slug}


def _nome(modelo: dict, slug: str, prefixo: str = "", chip: bool = False) -> str:
    pessoa = _pessoa(modelo, slug)
    exibicao = pessoa.get("nome") or slug
    nome = P.esc(nome_curto(exibicao) if chip else exibicao)
    if slug not in (modelo.get("pessoas") or {}):
        condicao = pessoa.get("condicao") or ("suplente em exercício" if pessoa.get("sem_pagina") else "")
        if condicao:
            nome += f'<span class="status">{P.esc(condicao)}</span>'
        return f'<span class="chip">{nome}</span>' if chip else nome
    classe = ' class="chip"' if chip else ""
    return f'<a{classe} href="{prefixo}vereadores/{P.esc(slug)}.html">{nome}</a>'


def _etiqueta_afastamento(afastamentos: list[dict]) -> str:
    """Reutiliza cargo e fonte do mandato enriquecido a partir do config."""
    return "".join(f'<span class="status">afastado: {P.esc(a["cargo"])} '
                   f'(<a href="{P.esc(a["fonte"])}">fonte</a>)</span>' for a in afastamentos)


def _barra_presenca(presenca: dict, afastado: bool = False) -> str:
    base = presenca.get("denominador", 0)
    if afastado and base < 10:
        return '<p class="nota">Sem base suficiente para comparação de presença.</p>'
    rotulo = "; ".join(f"{'Consignado' if codigo == 'C' else nome}: {presenca.get(codigo, 0)}"
                       for codigo, _, _, nome in PRESENCA)
    if presenca.get("L", 0):
        rotulo += f"; licenças fora da base: {presenca['L']}"
    rotulo += f"; compareceu: {_compareceu(presenca)} {'sessão deliberativa' if base == 1 else 'sessões deliberativas'}"
    if not base:
        return f'<div class="barra vazia" role="img" aria-label="{P.esc(rotulo)}">Sem base de frequência</div>'
    segmentos = "".join(f'<i class="s-{classe}" style="flex:{presenca.get(codigo, 0)}"></i>'
                        for codigo, classe, _, _ in PRESENCA if presenca.get(codigo, 0))
    return (f'<div class="barra presenca" role="img" aria-label="{P.esc(rotulo)}">'
            f'<div class="trilho" aria-hidden="true">{segmentos}</div></div>')


def _legenda_presenca() -> str:
    itens = "".join(f'<li><i class="sw s-{classe}" aria-hidden="true"></i>{glifo} {P.esc(nome)}</li>'
                    for _, classe, glifo, nome in PRESENCA)
    return ('<ul class="leg-graf leg-presenca" aria-label="Legenda da presença">' + itens
            + '<li><i class="sw s-licenca" aria-hidden="true"></i>— Licença: fora da base</li></ul>')


def _tabela_presenca(titulo: str, linhas: list[list]) -> str:
    return P.tabela_resumo(titulo, ["Vereador / ano", "Compareceu", "Presença", "Consignado",
                                   "Ausência com voto", "Justificada", "Ausência", "Licença (fora da base)"], linhas)


def _celulas_presenca(p: dict, afastado: bool = False) -> list:
    return [P.esc(_compareceu(p, afastado)), *[p.get(c, 0) for c in ("P", "C", "V", "J", "A", "L")]]


def _presencas(modelo: dict, dados: dict, leg: dict, ordenar: bool = False) -> str:
    linhas, tabela = [], []
    pessoas = modelo.get("pessoas") or {}
    sem_pagina = {s for s in dados.get("por_pessoa") or {} if _pessoa(modelo, s).get("sem_pagina")}
    for slug in sorted(set(pessoas) | sem_pagina, key=lambda s: ((_pessoa(modelo, s).get("nome") or s).casefold(), s)):
        pessoa = _pessoa(modelo, slug, leg["id"])
        registro = (dados.get("por_pessoa", {}).get(slug) or {}).get(leg["id"])
        if not registro:
            continue
        presenca = registro.get("presenca") or {}
        mandato = (pessoa.get("mandatos") or {}).get(leg["id"]) or {}
        afastamentos = mandato.get("afastamentos") or []
        afastado = bool(afastamentos)
        partido = mandato.get("partido") or ""
        eleito = bool(mandato.get("eleito"))
        status = '' if eleito else f'<span class="status">{P.esc(pessoa.get("condicao") or "suplente em exercício")}</span>'
        conteudo_nome = f'<strong>{P.esc(pessoa["nome"])}</strong><span class="partido">{P.esc(partido)}</span>{status}'
        quem = (f'<a class="quem" href="vereadores/{P.esc(slug)}.html">{conteudo_nome}</a>' if slug in pessoas
                else f'<span class="quem">{conteudo_nome}</span>')
        if afastado:
            # A fonte é um link próprio, nunca um <a> dentro do link do vereador.
            nome = (f'<a href="vereadores/{P.esc(slug)}.html">{conteudo_nome}</a>' if slug in pessoas else conteudo_nome)
            quem = f'<span class="quem">{nome}{_etiqueta_afastamento(afastamentos)}</span>'
        # O contrato .legislatura > .placar > .linha e data-* é o do placar existente.
        atributos = (f'data-nome="{P.esc(pessoa["nome"])}" data-partido="{P.esc(partido)}" '
                     f'data-eleito="{int(eleito)}" data-presenca="{presenca.get("pct") if presenca.get("denominador", 0) >= 10 and presenca.get("pct") is not None else -1}" '
                      f'data-presentes="{presenca.get("presentes", 0)}" data-denominador="{presenca.get("denominador", 0)}"')
        nota = _nota_presenca(presenca)
        nota_html = f'<span>{P.esc(nota)}</span>' if nota else ''
        linhas.append(f'<li class="linha" {atributos}>'
                      f'{quem}{_barra_presenca(presenca, afastado)}'
                      f'<p class="numeros"><strong>{P.esc(_compareceu(presenca, afastado))}</strong>'
                      f'{nota_html}</p></li>')
        tabela.append([_nome(modelo, slug) + _etiqueta_afastamento(afastamentos), *_celulas_presenca(presenca, afastado)])
    if not linhas:
        return '<p class="vazio">Nenhum registro de frequência nesta legislatura.</p>'
    controles = ('<div class="controles"><label for="ordem">Ordenar presença da legislatura mais recente</label>'
                 '<select id="ordem"><option value="nome">Nome</option><option value="presenca">Presença (%)</option>'
                 '<option value="denominador">Sessões na base</option></select></div>') if ordenar else ''
    return (controles + f'<div class="legislatura" data-leg="{P.esc(leg["id"])}"><ol class="placar">'
            + "".join(linhas) + '</ol></div>' + _legenda_presenca()
            + '<details class="bloco"><summary>Presença em tabela</summary>'
            + _tabela_presenca(f'Presença nas sessões deliberativas · {leg["rotulo"]}', tabela) + '</details>')


def _rotulo(v: dict, slug: str) -> str:
    voto = (v.get("votos") or {}).get(slug, "indeterminado")
    if v.get("qualidade") == "indeterminado":
        return rotulo_voto(voto, "indeterminado", v.get("materia", "outra"))
    return (v.get("rotulos") or {}).get(slug) or rotulo_voto(voto, v.get("sentido", "indeterminado"), v.get("materia", "outra"))


def _determinada(v: dict) -> bool:
    return v.get("qualidade") == "ok" and v.get("sentido") in SENTIDOS


def _placar(v: dict) -> str:
    oficial = v.get("qualidade") == "inconsistente"
    # Quando a fonte conserva ambos, não substituir o oficial pelo recalculado.
    totais = (v.get("totais_oficiais") if oficial else None) or v.get("totais") or {}
    partes, rotulos = [], []
    for chave, rotulo, classe in (("favor", "Favor ao parecer", "voto-maioria"),
                                  ("contra", "Contra o parecer", "voto-diferente"),
                                  ("abstencao", "Abstenção", "voto-abstencao"),
                                  ("ausentes", "Ausentes", "ausente"), ("branco", "Branco", "licenca"),
                                  ("nulo", "Nulo", "licenca")):
        n = totais.get(chave, 0) or 0
        if not n:
            continue
        if chave in {"favor", "contra"} and _determinada(v):
            voto = "Favor" if chave == "favor" else "Contra"
            rotulo = rotulo_voto(voto, v["sentido"], v.get("materia", "outra")).removeprefix("votou ")
            classe = "voto-maioria" if voto == v.get("maioria") else "voto-diferente"
            if not v.get("maioria"):
                classe = "voto-abstencao"
        if chave in {"favor", "contra"} and not _determinada(v):
            classe = "voto-abstencao"
        if chave == "abstencao":
            rotulos.append(P.plural(n, "abstenção", "abstenções"))
        elif chave == "ausentes":
            rotulos.append(P.plural(n, "ausente", "ausentes"))
        elif chave in {"branco", "nulo"}:
            rotulos.append(P.plural(n, "voto em branco" if chave == "branco" else "voto nulo",
                                   "votos em branco" if chave == "branco" else "votos nulos"))
        else:
            rotulos.append(f"{n} {rotulo}")
        partes.append(f'<i class="s-{classe}" style="flex:{n}" aria-hidden="true"></i>')
    descricao = ("Placar oficial: " if oficial else "Placar nominal: ") + " · ".join(rotulos)
    if not oficial and not _determinada(v):
        descricao += " · sentido não determinado"
    resumo = v.get("resumo") if _determinada(v) else " · ".join(rotulos)
    return (f'<div class="mini-barra" role="img" aria-label="{P.esc(descricao)}">'
            + "".join(partes) + f'</div><p class="mini-n">{P.esc(resumo or "Placar não informado")}</p>')


def _documento(v: dict) -> str:
    return str(v.get("documento") or v.get("numero") or "Documento não identificado")


def _votos_nomes(modelo: dict, v: dict) -> str:
    grupos = defaultdict(list)
    for slug in sorted(v.get("votos") or {}, key=lambda s: (_pessoa(modelo, s).get("nome") or s, s)):
        grupos[_rotulo(v, slug)].append(_nome(modelo, slug, chip=True))
    itens = "".join(f'<div class="grupo-votos"><h4>{P.esc(rotulo)} ({len(nomes)})</h4><p>{" ".join(nomes)}</p></div>'
                    for rotulo, nomes in sorted(grupos.items()))
    return '<details class="votos-nomes"><summary>Como votou cada vereador</summary>' + itens + '</details>'


def _nota_leitor(nota: str) -> bool:
    """Separa explicação ao leitor das conferências técnicas, sem descartar notas."""
    texto = nota.casefold()
    return (texto.startswith("o siscam registra estes votos como")
            or any(t in texto for t in ("quórum", "quorum", "11 votos", "maioria absoluta",
                                        "placar inconsistente", "sentido não determinado")))


def cartao_votacao(modelo: dict, v: dict) -> str:
    """Cartão nominal reutilizável; estrutura pública descrita no contrato acima."""
    inconsistente = v.get("qualidade") == "inconsistente"
    documento = _documento(v)
    url = v.get("url_documento")
    titulo = (f'<a href="{P.esc(url)}" target="_blank" rel="noopener">{P.esc(documento)}{P.NOVA_ABA}</a>'
              if url else P.esc(documento))
    notas = [n for n in v.get("notas") or [] if _nota_leitor(n)]
    tecnicas = [n for n in v.get("notas") or [] if not _nota_leitor(n)]
    texto_fonte = ""
    if inconsistente:
        notas.insert(0, "Placar inconsistente: exibimos apenas os totais oficiais, sem atribuir votos a nomes.")
    elif not _determinada(v):
        texto_fonte = ('<p class="nota fonte-sentido sentido-indeterminado">'
                       'Favor ao parecer / Contra o parecer: sentido não determinado.</p>')
    elif v.get("fonte_sentido") == "texto_veto_ambiguo":
        texto_fonte = '<p class="nota fonte-sentido">Sentido definido pelo texto do parecer na tramitação.</p>'
    quorum = ""
    if v.get("materia") == "veto":
        q = v.get("quorum") or {}
        houve = q.get("derrubar") if _determinada(v) else None
        conclusao = f"houve {houve}." if houve is not None else "o número para derrubar não pôde ser determinado."
        quorum = '<p class="nota quorum">Derrubar o veto exige 11 votos (maioria absoluta dos 21 vereadores); ' + P.esc(conclusao) + '</p>'
    notas_html = "".join(f'<p class="nota qualidade-voto">ⓘ {P.esc(n)}</p>' for n in notas)
    conferencia = (f'<details class="notas-conferencia"><summary>Notas de conferência ({len(tecnicas)})</summary><ul>'
                   + "".join(f'<li>{P.esc(n)}</li>' for n in tecnicas) + '</ul></details>') if tecnicas else ''
    atributos = " ".join(f'data-{chave}="{P.esc(valor)}"' for chave, valor in (
        ("ano", _ano(v) or ""), ("materia", v.get("materia") or "outra"),
        ("classe", v.get("classe") or ""), ("sentido", v.get("sentido") or "indeterminado"),
        ("qualidade", v.get("qualidade") or "indeterminado")))
    return (f'<li class="projeto votacao" id="v-{P.esc(v["id"])}" {atributos}><p class="cab">{titulo}'
            f'<span>{P.esc(P.data_br(v.get("data")))}</span><span>{P.esc(v.get("titulo_sessao") or "Sessão não identificada")}</span></p>'
            f'<p class="desfecho">Resultado oficial: {P.esc(v.get("resultado") or "não informado")}</p>'
            f'<p class="ementa">{P.esc(P.legivel(v.get("ementa") or "Ementa não disponível na base coletada."))}</p>'
            + _placar(v) + quorum + texto_fonte + notas_html
            + ("" if inconsistente else _votos_nomes(modelo, v))
            + (P.botoes_siscam(url, documento) if url else '<p class="nota">Sem link do documento no SISCAM.</p>')
            + _contestar(documento, f'Sessão: {v.get("titulo_sessao") or ""}\nVotação: {v["id"]}\n{url or ""}')
            + conferencia + '</li>')


# Compatibilidade com os consumidores anteriores; usar cartao_votacao em código novo.
_cartao = cartao_votacao


def _resumo_placares(dados: dict, anos: list[int]) -> str:
    frases = []
    for ano in sorted(int(a) for a in anos):
        cont = _valor(dados.get("placares_por_ano") or {}, ano, {})
        votacoes = [v for v in dados.get("votacoes") or [] if _ano(v) == ano]
        if not votacoes and not cont:
            continue
        frases.append(f'{"Da" if len(votacoes) == 1 else "Das"} {P.plural(len(votacoes), "votação nominal", "votações nominais")} de {ano}, '
                      f'{P.plural(cont.get("unanime", 0), "foi unânime", "foram unânimes")} e '
                      f'{P.plural(cont.get("dissenso", 0), "teve", "tiveram")} 1 ou 2 votos diferentes; '
                      f'{P.plural(cont.get("dividida", 0), "dividiu", "dividiram")} a Câmara '
                      '(ao menos 3 votos no lado menor ou 3 abstenções).')
    return "".join(f'<p class="explica">{P.esc(f)}</p>' for f in frases)


def _pessoas_leg(modelo: dict, dados: dict, leg: dict) -> list[str]:
    """Composição conhecida, sem promover não membros dos votos brutos a vereadores."""
    slugs = {s for s, r in (dados.get("por_pessoa") or {}).items() if leg["id"] in r}
    slugs.update(s for s, p in (modelo.get("pessoas") or {}).items()
                 if leg["id"] in (p.get("mandatos") or {}) or leg["id"] in (p.get("legislaturas") or []))
    return sorted(slugs, key=lambda s: ((_pessoa(modelo, s, leg["id"]).get("nome") or s).casefold(), s))


def _filtros_votacoes(modelo: dict, dados: dict, leg: dict) -> str:
    ident = P.esc(leg["id"])
    anos = ''.join(f'<option value="{a}">{a}</option>' for a in sorted({int(a) for a in leg.get("anos") or []}, reverse=True))
    materias = ''.join(f'<option value="{chave}">{P.esc(nome)}</option>' for chave, nome in MATERIAS.items())
    pessoas = ''.join(f'<option value="{P.esc(s)}">{P.esc(_pessoa(modelo, s, leg["id"]).get("nome") or s)}</option>'
                      for s in _pessoas_leg(modelo, dados, leg))
    classes = ''.join(f'<label><input type="radio" name="classe" value="{chave}"'
                      f'{" checked" if chave == "dividida" else ""}>{nome}</label>'
                      for chave, nome in (("dividida", "Divididas"), ("dissenso", "Dissenso isolado"), ("todas", "Todas")))
    return (f'<form class="filtros filtros-sessoes" id="filtros-sessoes-{ident}" data-leg="{ident}" hidden>'
            f'<label>Ano<select name="ano"><option value="todos">Todos os anos</option>{anos}</select></label>'
            f'<fieldset><legend>Classe de votação</legend>{classes}</fieldset>'
            f'<label>Matéria<select name="materia"><option value="todas">Todas as matérias</option>{materias}</select></label>'
            f'<label>Vereador<select name="vereador"><option value="">Todos os vereadores</option>{pessoas}</select></label>'
            '<label><input type="checkbox" name="div">Só onde o vereador escolhido votou diferente da maioria</label>'
            '<label>Buscar votação<input type="search" name="q"></label>'
            '<label>Ordenar<select name="ordem"><option value="recente">Mais recentes</option>'
            '<option value="antigo">Mais antigas</option><option value="apertada">Mais apertadas</option></select></label>'
            '<div class="acoes-item"><button type="button" data-acao="limpar">Limpar filtros</button>'
            '<button type="button" data-acao="csv">Baixar CSV</button></div></form>')


def _divididas(modelo: dict, dados: dict, leg: dict) -> str:
    votacoes = _recentes([v for v in _da_leg(dados.get("votacoes") or [], leg) if v.get("classe") == "dividida"])
    texto = _resumo_placares(dados, leg.get("anos") or [])
    texto += ('<p class="nota">A opção mais votada não é o quórum legal. Um veto mantido não significa que '
              'a maioria votou para mantê-lo. Casos inconsistentes e sentidos não determinados estão identificados.</p>')
    ident = P.esc(leg["id"])
    texto += _filtros_votacoes(modelo, dados, leg)
    texto += (f'<p class="contagem" id="contagem-votacoes-{ident}" aria-live="polite">'
              f'{P.plural(len(votacoes), "votação dividida", "votações divididas")} nesta legislatura.</p>')
    if not votacoes:
        texto += '<p class="vazio">Nenhuma votação dividida registrada nesta legislatura.</p>'
    cartoes = [cartao_votacao(modelo, v) for v in votacoes]
    texto += f'<ol class="votacoes" id="lista-votacoes-{ident}">' + "".join(cartoes[:LIMITE_CARTOES]) + '</ol>'
    if len(cartoes) > LIMITE_CARTOES:
        texto += (f'<details class="bloco mais-votacoes"><summary>Ver mais {len(cartoes) - LIMITE_CARTOES}</summary>'
                  + '<ol class="votacoes">' + "".join(cartoes[LIMITE_CARTOES:]) + '</ol></details>')
    return texto + f'<button type="button" data-acao="mais" data-leg="{ident}" hidden>Mostrar mais</button>'


# ---- mapa de votos ------------------------------------------------------------
def _limite_faixa(v: dict) -> str:
    if v.get("qualidade") == "inconsistente":
        return "placar inconsistente; sem atribuição nominal"
    if not _determinada(v):
        return "sentido não determinado"
    if v.get("maioria") not in {"Favor", "Contra"}:
        return "sem maioria (empate)"
    return ""


def _voto_faixa(v: dict, slug: str) -> tuple[str, str, str]:
    """Classe, glifo e alternativa textual; cores nunca interpretam Favor/Contra."""
    limite = _limite_faixa(v)
    if v.get("qualidade") == "inconsistente":
        return "cru", "—", limite
    voto = (v.get("votos") or {}).get(slug)
    if voto is None:
        classe = "vazio"
    elif limite:
        return "cru", str(voto), f"{voto}; {limite}; sem comparação com a maioria"
    elif voto in {"Favor", "Contra"}:
        classe = "maioria" if voto == v["maioria"] else "diferente"
    else:
        classe = {"Abstenção": "abstencao", "Ausente": "ausente", "Presidente": "presidia"}.get(voto)
        if classe is None:
            return "cru", str(voto), str(voto)
    return classe, *VOTOS_FAIXA[classe]


def _cabecalho_faixa(v: dict) -> str:
    documento = _documento(v)
    numero = str(v.get("numero") or "").split("/")[0]
    sigla = {"pl": "PL", "pdl": "PDL", "resolucao": "PR", "veto": "Veto"}.get(v.get("materia"))
    curto = f"{sigla} {numero}" if sigla and numero else re.sub(r"/\d{4}\b", "", documento)
    data = P.data_br(v.get("data"))
    limite = _limite_faixa(v)
    marca = (f'<span aria-hidden="true"> *</span><span class="so-leitor"> · {P.esc(limite)}</span>' if limite else '')
    classe = ' class="faixa-sem-comparacao"' if limite else ''
    return (f'<th scope="col"{classe}><a href="#v-{P.esc(v["id"])}">'
            f'<abbr title="{P.esc(documento + ", " + data)}">{P.esc(data[:5])}</abbr><br>'
            f'{P.esc(curto)}{marca}</a></th>')


def _mapa_votos(modelo: dict, dados: dict, leg: dict) -> str:
    nominais = _da_leg(dados.get("votacoes") or [], leg)
    divididas = [v for v in nominais if v.get("classe") == "dividida"]
    ident = P.esc(leg["id"])
    if not divididas:
        return (f'<div class="faixa-votos" id="faixa-{ident}" data-ano="">'
                '<p class="vazio">Nenhuma votação dividida disponível para o mapa nesta legislatura.</p></div>')
    ano = max(_ano(v) for v in divididas)
    votacoes = list(reversed(_recentes([v for v in divididas if _ano(v) == ano])))
    membros = _pessoas_leg(modelo, dados, leg)
    linhas, resumo = [], []
    for slug in membros:
        pessoa = _pessoa(modelo, slug, leg["id"])
        eleito = ((pessoa.get("mandatos") or {}).get(leg["id"]) or {}).get("eleito")
        # Suplências sem nenhum voto substantivo/presidência não criam linhas.
        if not eleito and not any((v.get("votos") or {}).get(slug) in
                                  {"Favor", "Contra", "Abstenção", "Branco", "Nulo", "Presidente"} for v in nominais):
            continue
        nome = _nome(modelo, slug)
        if not eleito and slug in (modelo.get("pessoas") or {}):
            nome += '<span class="status">suplente em exercício</span>'
        celulas, contagens = [], defaultdict(int)
        for v in votacoes:
            classe, glifo, rotulo = _voto_faixa(v, slug)
            contagens[classe] += 1
            marca = ' faixa-sem-comparacao' if _limite_faixa(v) else ''
            celulas.append(f'<td class="voto-{classe}{marca}"><span aria-hidden="true">{P.esc(glifo)}</span>'
                           f'<span class="so-leitor">{P.esc(rotulo)}</span></td>')
        linhas.append(f'<tr data-vereador="{P.esc(slug)}"><th scope="row">{nome}</th>{"".join(celulas)}</tr>')
        resumo.append([nome, *[contagens[c] for c in ("maioria", "diferente", "abstencao", "ausente")]])
    legenda = ''.join(f'<li><span class="glifo-voto voto-{c}" aria-hidden="true">{g}</span>'
                      f'{P.esc(r if g else "Célula vazia: " + r)}</li>' for c, (g, r) in VOTOS_FAIXA.items())
    return (f'<div class="faixa-votos" id="faixa-{ident}" data-ano="{ano}"><h3>Votações divididas de {ano}</h3>'
            f'<ul class="leg-graf leg-votos" aria-label="Legenda do mapa de votos">{legenda}</ul>'
            '<p class="nota">Linhas parecidas indicam votos parecidos nas votações divididas deste ano; '
            'não indicam grupo político. Nomes em ordem alfabética, sem agrupamento por voto.</p>'
            f'<div class="faixa-rolagem" role="region" tabindex="0" aria-label="Mapa de votos de {ano}, legislatura {P.esc(leg["rotulo"])}: tabela com rolagem horizontal">'
            f'<table class="faixa"><caption>Vereador × votação dividida de {ano}, em ordem cronológica. '
            'A cor compara o voto à opção mais votada entre Favor e Contra, independentemente do sentido do parecer. '
            '* Coluna sem comparação: empate, sentido não determinado ou placar inconsistente.</caption>'
            '<thead><tr><th scope="col">Vereador</th>' + ''.join(_cabecalho_faixa(v) for v in votacoes)
            + '</tr></thead><tbody>' + ''.join(linhas) + '</tbody></table></div>'
            + P.tabela_resumo(f'Resumo por vereador · votações divididas de {ano}',
                              ["Vereador", "Com a maioria", "Diferente da maioria", "Abstenção", "Ausente"], resumo)
            + '<p class="nota">O resumo conta apenas as colunas com comparação determinada. Presidência, células vazias, '
            'votos em branco/nulos e colunas marcadas não entram nessas quatro contagens. '
            f'<a href="#divididas-{ident}">Ver outros anos nas listas de votações</a>.</p></div>')


def _grafico(titulo: str, subtitulo: str, rotulos: list[str], series: list[tuple], eixo: str) -> str:
    """Acrescenta caption e cabeçalhos de linha à alternativa do componente SVG."""
    grafico = G.colunas_empilhadas(titulo, subtitulo, rotulos, series)
    grafico = grafico.replace('<table>', f'<table><caption>{P.esc(titulo)}</caption>')
    grafico = grafico.replace('<th scope="col"></th>', f'<th scope="col">{P.esc(eixo)}</th>')
    return re.sub(r'<tr><td>(.*?)</td>', r'<tr><th scope="row">\1</th>', grafico)


def _grafico_placares(dados: dict, leg: dict) -> str:
    anos = sorted(int(a) for a in leg.get("anos") or [])
    contagens = dados.get("placares_por_ano") or {}
    if not any(_valor(contagens, a, {}) for a in anos):
        return '<p class="vazio">Nenhum placar nominal neste período.</p>'
    series = [(nome, classe, [_valor(contagens, a, {}).get(chave, 0) for a in anos])
              for chave, nome, classe in (("unanime", "Unânime", "s-presente"),
                                           ("dissenso", "Dissenso isolado", "s-consignado"),
                                           ("dividida", "Dividida", "s-votou-ausente"),
                                           ("inconsistente", "Inconsistente", "s-ausente"))]
    return _grafico(f'Placares por ano · {leg["rotulo"]}',
                    'Sentido não determinado é uma limitação de interpretação e pode ocorrer em qualquer classe; '
                    'os placares inconsistentes ficam separados.', [str(a) for a in anos], series, "Ano")


def _ritmo(dados: dict) -> str:
    ritmo = dados.get("ritmo") or {}
    anos = sorted(int(a) for a in ritmo)
    if not anos:
        return '<p class="vazio">Nenhuma sessão disponível para mostrar o ritmo mensal.</p>'
    recente = anos[-1]
    meses = _valor(ritmo, recente, {})
    tipos = sorted({t for valores in meses.values() for t in valores})
    classes = {"ordinaria": "s-presente", "extraordinaria": "s-consignado", "solene": "s-votou-ausente",
               "especial": "s-justificada", "desconhecido": "s-ausente"}
    rotulos = [f"{recente}-{m:02}" for m in range(1, 13)]
    grafico = _grafico(f'Sessões por mês e tipo · {recente}', 'Sessões listadas no SISCAM; não é uma medida de qualidade.',
                       [r[5:] for r in rotulos],
                       [(TIPOS.get(t, t), classes.get(t, "s-ausente"), [meses.get(r, {}).get(t, 0) for r in rotulos]) for t in tipos], "Mês")
    todos_tipos = sorted({t for ano in ritmo.values() for mes in ano.values() for t in mes})
    linhas = [[str(a), *[sum(m.get(t, 0) for m in _valor(ritmo, a, {}).values()) for t in todos_tipos]] for a in anos]
    return (grafico + '<details class="bloco"><summary>Sessões por ano e tipo</summary>'
            + P.tabela_resumo("Sessões listadas por ano e tipo", ["Ano", *[TIPOS.get(t, t) for t in todos_tipos]], linhas) + '</details>')


def _texto_qualidade(item) -> str:
    if isinstance(item, dict):
        return " · ".join(f"{chave}: {_texto_qualidade(valor)}" for chave, valor in sorted(item.items()))
    if isinstance(item, (list, tuple)):
        return "; ".join(_texto_qualidade(v) for v in item)
    return str(item)


def _qualidade(dados: dict) -> str:
    qualidade = dados.get("qualidade") or {}
    partes = []
    for chave, titulo in (("sem_lista", "Sessões sem lista de frequência"), ("inconsistentes", "Placares inconsistentes"),
                           ("indeterminadas", "Sentido não determinado"), ("duplicados", "Duplicados resolvidos"),
                           ("nao_membros", "Registros de não membros"), ("notas", "Notas de conferência")):
        itens = qualidade.get(chave) or []
        quantidade = itens if isinstance(itens, int) else len(itens)
        lista = ""
        if isinstance(itens, (list, tuple, set, dict)):
            valores = sorted(itens, key=str) if isinstance(itens, (set, dict)) else itens
            lista = '<ul>' + "".join(f'<li>{P.esc(_texto_qualidade(i))}</li>' for i in valores) + '</ul>' if itens else ''
        partes.append(f'<details class="bloco"><summary>{P.esc(titulo)}: {quantidade}</summary>'
                      + (lista or '<p class="nota">Nenhuma ocorrência detalhada nesta base.</p>') + '</details>')
    cobertura = dados.get("cobertura") or {}
    tabela = P.tabela_resumo("Cobertura da coleta de sessões", ["Ano", "Listadas", "Com frequência", "Com votação", "Pendentes"],
                            [[str(a), *[_valor(cobertura, a, {}).get(c, 0) for c in
                                         ("listadas", "com_frequencia", "com_votacao", "pendentes")]] for a in _anos(dados)])
    return (tabela + "".join(partes) + '<p class="nota">Pendências e falhas de registro limitam a cobertura. '
            'Nomes que não correspondem a membros da legislatura ficam fora das métricas. '
            + _contestar("Qualidade dos dados", "Página: sessoes.html#qualidade-sessoes") + '</p>')


# ---- página da Câmara --------------------------------------------------------
def gerar_sessoes(modelo: dict) -> str:
    """HTML completo de sessoes.html, inclusive o estado ainda sem coleta."""
    dados = modelo.get("sessoes") or {}
    meta = modelo.get("meta") or {}
    coleta = (meta.get("sessoes") or {}).get("em") or (meta.get("coleta") or {}).get("em") or ""
    abertura = ('<section class="abertura"><h1>Sessões e votações</h1>'
                '<p>Presença nas sessões plenárias e votos nominais: primeiro a participação, depois as decisões que dividiram a Câmara.</p>'
                f'<p class="atualizacao">Sessões coletadas: {P.esc(_periodo(dados))} · dados do SISCAM de '
                f'{P.esc(P.data_br(coleta[:10]))} · <a href="metodologia.html#sessoes">como contamos</a></p></section>')
    if not dados or not dados.get("sessoes"):
        corpo = abertura + '<p class="vazio">Nenhuma sessão coletada disponível neste momento.</p>'
    else:
        blocos = []
        for indice, leg in enumerate(_legs(dados)):
            ident = P.esc(leg["id"])
            sessoes = _da_leg(dados.get("sessoes") or [], leg)
            nominais = _da_leg(dados.get("votacoes") or [], leg)
            deliberativas = sum(bool(s.get("deliberativa") and s.get("realizada")) for s in sessoes)
            especiais = sum(s.get("tipo") in {"solene", "especial"} and s.get("realizada", True) for s in sessoes)
            divididas = sum(v.get("classe") == "dividida" and v.get("qualidade") != "inconsistente" for v in nominais)
            mediana = (dados.get("mediana_presenca") or {}).get(leg["id"])
            nota_especiais = f'+{P.plural(especiais, "solene/especial", "solenes/especiais")}' if especiais else ''
            tiles = (P.tile(deliberativas, "sessão deliberativa realizada" if deliberativas == 1 else "sessões deliberativas realizadas", nota_especiais)
                     + P.tile(_pct(mediana), "presença mediana dos eleitos", "apenas sessões deliberativas com lista; base individual")
                     + P.tile(f"{divididas} de {len(nominais)}",
                              "votação nominal dividiu a Câmara" if len(nominais) == 1 else "votações nominais dividiram a Câmara",
                              "ao menos 3 no lado menor ou 3 abstenções"))
            indice_html = (f'<nav class="indice" aria-label="Nesta legislatura: {P.esc(leg["rotulo"])}">'
                           f'<a href="#presenca-{ident}">Presença</a><a href="#divididas-{ident}">Votações divididas</a>'
                           f'<a href="#mapa-votos-{ident}">Mapa de votos</a>'
                           f'<a href="#placares-{ident}">Placares por ano</a><a href="#ritmo-sessoes">Ritmo</a>'
                           '<a href="#qualidade-sessoes">Qualidade dos dados</a></nav>')
            blocos.append(f'<details class="bloco" id="sessoes-leg-{ident}"{" open" if indice == 0 else ""}>'
                          f'<summary>Legislatura {P.esc(leg["rotulo"])}</summary><div class="tiles">{tiles}</div>{indice_html}'
                          f'<section id="presenca-{ident}"><h2 class="h-secao">Presença nas sessões deliberativas</h2>'
                          '<p class="explica">O percentual usa a base de cada vereador, sem licenças. Com menos de 10 sessões, '
                          'mostramos só a contagem. Afastados com base inferior a 10 sessões aparecem sem barra, '
                          'com a contagem em exercício e fora da mediana dos eleitos. '
                          'Partido é o da eleição; nomes em ordem alfabética.</p>'
                           + _presencas(modelo, dados, leg, ordenar=indice == 0) + '</section>'
                           f'<section id="divididas-{ident}"><h2 class="h-secao">Votações que dividiram a Câmara</h2>'
                           + _divididas(modelo, dados, leg) + '</section>'
                           f'<section id="mapa-votos-{ident}"><h2 class="h-secao">Mapa de votos</h2>'
                           + _mapa_votos(modelo, dados, leg) + '</section>'
                           f'<section id="placares-{ident}"><h2 class="h-secao">Placares por ano</h2>'
                          + _grafico_placares(dados, leg) + '</section></details>')
        corpo = (abertura + '<div class="sessoes"><h2 class="h-secao">Legislaturas</h2>'
                 '<p class="explica">A mais recente está aberta. Abra as demais legislaturas para comparar os períodos.</p>'
                 + "".join(blocos) + '<section id="ritmo-sessoes"><h2 class="h-secao">Ritmo das sessões</h2>'
                 + _ritmo(dados) + '</section><section id="qualidade-sessoes"><h2 class="h-secao">Qualidade dos dados</h2>'
                 + _qualidade(dados) + '</section></div>')
    return P.pagina("Sessões e votações · Radar dos Vereadores de Niterói", corpo, "sessoes.html",
                    descricao="Presença nas sessões plenárias e votações nominais da Câmara de Niterói, com fontes e limitações.",
                    dialogo=True, scripts=("sessoes.js",))


# ---- página individual -------------------------------------------------------
def _como_votou(registro: dict) -> str:
    linhas, resumos = [], []
    tem_outros = False
    for materia, contagens in sorted((registro.get("como_votou") or {}).items()):
        grupos = dict.fromkeys(("favor", "contra", "abstencao"), 0)
        outros = {}
        for rotulo, n in sorted(contagens.items()):
            # A agregação fornece apenas sentidos determinados; não misturar a base desconhecida.
            texto = rotulo.casefold()
            if not n or "sentido não determinado" in texto or texto.startswith(("favor ao parecer", "contra o parecer", "voto não determinado")):
                continue
            if texto.startswith(("votou a favor ", "votou para manter ")):
                grupos["favor"] += n
            elif texto.startswith(("votou contra ", "votou para derrubar ")):
                grupos["contra"] += n
            elif texto == "absteve-se":
                grupos["abstencao"] += n
            else:
                nome = {"votou em branco": "branco", "voto nulo": "nulo", "ausente nesta votação": "ausência",
                        "presidia a sessão": "presidindo"}.get(texto, rotulo)
                outros[nome] = outros.get(nome, 0) + n
        total = sum(grupos.values()) + sum(outros.values())
        if not total:
            continue
        nome_materia = MATERIAS.get(materia, materia)
        rotulos = ("manter", "derrubar", "abstenção") if materia == "veto" else ("a favor", "contra", "abstenção")
        partes = [f'{rotulo} {n}' for rotulo, n in zip(rotulos, grupos.values()) if n]
        partes += [f'{rotulo} {n}' for rotulo, n in sorted(outros.items())]
        resumos.append(f'<li><strong>{P.esc(nome_materia)}</strong> — {P.esc(" · ".join(partes))}</li>')
        linhas.append([P.esc(nome_materia), *grupos.values(), total])
        tem_outros |= bool(outros)
    if linhas:
        tabela = ('<ul class="como-votou" role="list">' + "".join(resumos) + '</ul>'
                  + '<details class="bloco tabela-como-votou"><summary>Como votou em tabela</summary>'
                  + P.tabela_resumo("Como votou por matéria (sentidos determinados)",
                                    ["Matéria", "A favor do projeto ou manter o veto", "Contra ou derrubar", "Abstenção", "Total"], linhas)
                  + ('<p class="nota">O total inclui os outros registros discriminados no resumo, quando houver.</p>' if tem_outros else '')
                  + '</details>')
    else:
        tabela = '<p class="vazio">Nenhum voto com sentido determinado neste período.</p>'
    return tabela + f'<p class="nota">Sentido não determinado: {P.plural(registro.get("indeterminadas", 0), "votação", "votações")}.</p>'


def _frase_diferenca(v: dict, slug: str) -> str:
    voto = _rotulo(v, slug)
    voto = voto[:1].upper() + voto[1:]
    maioria = v.get("maioria")
    if maioria not in {"Favor", "Contra"}:
        return f"{voto}. Placar sem maioria determinada."
    totais = v.get("totais") or {}
    maior = totais.get("favor" if maioria == "Favor" else "contra", 0)
    menor = totais.get("contra" if maioria == "Favor" else "favor", 0)
    placar = f"{maior} × {menor}"
    if not _determinada(v):
        pessoal = rotulo_voto((v.get("votos") or {}).get(slug), "indeterminado", v.get("materia", "outra"))
        maior_rotulo = rotulo_voto(maioria, "indeterminado", v.get("materia", "outra"))
        pessoal = pessoal.removesuffix(" (sentido não determinado)")
        maior_rotulo = maior_rotulo.removesuffix(" (sentido não determinado)")
        return f'Registrou “{pessoal}”; a maioria registrou “{maior_rotulo}” ({placar}). Sentido não determinado.'
    maior_rotulo = rotulo_voto(maioria, v["sentido"], v.get("materia", "outra"))
    if maior_rotulo.startswith("votou a favor "):
        maior_rotulo = "a favor"
    elif maior_rotulo.startswith("votou contra "):
        maior_rotulo = "contra"
    else:
        maior_rotulo = maior_rotulo.removeprefix("votou ")
    return f"{voto}; a maioria votou {maior_rotulo} ({placar})."


def _diferentes(dados: dict, registro: dict, slug: str, leg: dict) -> str:
    ids = {str(i) for i in registro.get("divergencias") or []}
    votacoes = _recentes([v for v in _da_leg(dados.get("votacoes") or [], leg)
                         if str(v["id"]) in ids and v.get("classe") == "dividida" and v.get("qualidade") != "inconsistente"])
    if not votacoes:
        return '<p class="vazio">Nenhum voto diferente da maioria em votação dividida neste período.</p>'
    itens = []
    for v in votacoes[:10]:
        classe = '' if _determinada(v) else ' class="sentido-indeterminado"'
        itens.append(f'<li{classe}><a href="../sessoes.html#v-{P.esc(v["id"])}">{P.esc(P.data_br(v.get("data")))} · '
                     f'{P.esc(_documento(v))}</a> — {P.esc(_frase_diferenca(v, slug))} '
                     f'Resultado oficial: {P.esc(v.get("resultado") or "não informado")}.</li>')
    return '<ul class="votos-diferentes">' + "".join(itens) + '</ul>'


def secao_sessoes_vereador(modelo: dict, pessoa: dict) -> str:
    """Seção da ficha do vereador; todos os links são relativos a vereadores/."""
    dados = modelo.get("sessoes") or {}
    por_leg = (dados.get("por_pessoa") or {}).get(pessoa["slug"]) or {}
    por_leg = {leg: r for leg, r in por_leg.items()
               if isinstance(r, dict) and (any((r.get("presenca") or {}).get(c, 0) for c in ("P", "C", "V", "J", "A", "L"))
                                          or any((r.get("participacao") or {}).values())
                                          or ((pessoa.get("mandatos") or {}).get(leg) or {}).get("afastamentos"))}
    cabecalho = ('<section class="mandato sessoes" aria-labelledby="t-sessoes">'
                 '<h2 id="t-sessoes">Presença e votos <span>sessões plenárias e votações nominais</span></h2>'
                 '<p class="explica">Presença e votos registrados, não uma avaliação do mandato. A base é individual, '
                 'só nas sessões deliberativas com lista; licenças ficam fora. '
                 'Afastados com base inferior a 10 sessões aparecem sem barra e ficam fora da mediana dos eleitos. '
                 '<a href="../metodologia.html#sessoes">Como contamos</a>.</p>')
    if not por_leg:
        return (cabecalho + '<p class="vazio">Nenhum registro de frequência com este nome nas sessões coletadas '
                f'({P.esc(_periodo(dados))}).</p></section>')
    blocos = []
    for leg in _legs(dados):
        registro = por_leg.get(leg["id"])
        if not registro:
            continue
        p = registro.get("presenca") or {}
        afastamentos = ((pessoa.get("mandatos") or {}).get(leg["id"]) or {}).get("afastamentos") or []
        afastado = bool(afastamentos)
        part = registro.get("participacao") or {}
        mediana = (dados.get("mediana_presenca") or {}).get(leg["id"])
        comparacao = P.comparacao(p.get("pct"), mediana, sufixo="%") if p.get("denominador", 0) >= 10 else "base inferior a 10 sessões; sem comparação percentual"
        base = p.get("denominador", 0)
        contagem = f'{p.get("presentes", 0)} de {base}'
        tem_pct = base >= 10 and p.get("pct") is not None
        rotulo_presenca = (f'{contagem} sessões deliberativas' if tem_pct else
                           'compareceu à sessão deliberativa' if base == 1 else 'compareceu às sessões deliberativas')
        if afastado and base < 10:
            rotulo_presenca = "sessões em exercício"
        ausencias = p.get("A", 0) + p.get("J", 0)
        presidindo = f'{part["presidindo"]} presidindo' if part.get("presidindo", 0) else ''
        tiles = (P.tile(_pct(p["pct"]) if tem_pct else contagem, rotulo_presenca, comparacao)
                 + P.tile(ausencias, "ausência" if ausencias == 1 else "ausências", _nota_presenca(p))
                 + P.tile(f'{part.get("votou", 0)} de {part.get("possiveis", 0)}',
                          "votação nominal em que votou" if part.get("possiveis") == 1 else "votações nominais em que votou", presidindo)
                 + P.tile(f'{len(registro.get("divergencias") or [])} de {registro.get("divididas", 0)}',
                          "votou diferente da maioria", "Votações divididas com sentido conhecido; divergir não mede qualidade"))
        por_ano = registro.get("por_ano") or {}
        tabela = _tabela_presenca("Presença por ano", [[P.esc(a), *_celulas_presenca(r, afastado)] for a, r in sorted(por_ano.items(), key=lambda i: str(i[0]))])
        blocos.append(f'<details class="bloco"{" open" if not blocos else ""}><summary>Legislatura {P.esc(leg["rotulo"])}</summary>'
                      + _etiqueta_afastamento(afastamentos)
                      + f'<div class="tiles">{tiles}</div>' + _barra_presenca(p, afastado) + _legenda_presenca()
                      + '<h3>Como votou</h3>' + _como_votou(registro)
                      + '<h3>Onde votou diferente da maioria</h3>' + _diferentes(dados, registro, pessoa["slug"], leg)
                      + f'<p><a href="../sessoes.html#sessoes-leg-{P.esc(leg["id"])}">Ver todas em Sessões</a></p>'
                      + '<details class="bloco"><summary>Presença por ano</summary>' + tabela + '</details></details>')
    return cabecalho + "".join(blocos) + '</section>'


# ---- metodologia -------------------------------------------------------------
def metodologia_sessoes(modelo: dict) -> str:
    """Regras publicadas, inclusive quando a coleta ainda está vazia."""
    dados = modelo.get("sessoes") or {}
    return f'''<section id="sessoes" class="texto sessoes" aria-labelledby="t-metodo-sessoes">
<h2 id="t-metodo-sessoes">Sessões plenárias: presença e votos</h2>
<p>A página <a href="sessoes.html">Sessões e votações</a> usa os registros públicos do SISCAM. Período coletado: {P.esc(_periodo(dados))}. A cobertura por ano e as pendências aparecem junto aos números; uma sessão sem lista não vira falta para ninguém.</p>
<h3>Presença e base individual</h3>
<ul>
<li>Só sessões ordinárias e extraordinárias realizadas, com lista de frequência, entram na presença. Solenes e especiais aparecem à parte.</li>
<li>● Presença (P) e ◆ Consignado (C) contam como presente. Consignado é um registro feito pela Mesa.</li>
<li>▲ Ausência na abertura com voto nominal substantivo registrado na mesma sessão conta como presença (V), identificada à parte. Presidir não é voto substantivo.</li>
<li>◇ Ausência justificada (J) e ○ Ausência (A) contam no denominador, mas não como presença. Licença (L) e textos desconhecidos ficam fora da base. O SISCAM não informa o motivo de ausência.</li>
<li>Não inventamos faltas para nomes que não estão na lista. Cada pessoa conta uma vez por sessão; vale a melhor evidência de presença. Com menos de 10 sessões na base, mostramos somente “X de Y”, sem percentual. A mediana considera os eleitos com base suficiente; suplentes são identificados e não entram na mediana.</li>
<li>Afastamentos registrados na configuração aparecem com cargo e fonte pública, por legislatura. Com base inferior a 10 sessões, mostramos “X de Y sessões em exercício”, sem barra de presença nem percentual; esses afastados ficam no fim da ordenação por presença e fora da mediana dos eleitos, como os demais sem base suficiente. Com pelo menos 10 sessões, a barra e o percentual permanecem, junto à etiqueta. O afastamento não reclassifica os registros brutos nem informa suas datas de início e fim.</li>
</ul>
<h3>O que significa cada voto</h3>
<p>O voto nominal “Favor” ou “Contra” é sobre o parecer da comissão, não necessariamente a favor ou contra a matéria. O sentido apresentado vem do resultado oficial e do lado vencedor. O texto da tramitação só determina o sentido em vetos mantidos sem nenhum lado com 11 votos, quando há decisão e direção inequívocas na mesma data; nos demais casos serve como conferência. Notas técnicas ficam em “Notas de conferência” e em “Qualidade dos dados”, sem apagar votos só porque o texto diverge.</p>
<p>Derrubar um veto exige 11 votos: maioria absoluta dos 21 vereadores, não dos presentes. Um veto pode ser mantido sem que a maioria tenha votado para mantê-lo: não atingir 11 votos para derrubar não transforma ausências e abstenções em votos para manter. A opção mais votada entre Favor e Contra não é o quórum legal; empates não têm maioria.</p>
<p>Sem sentido seguro, mostramos “Favor ao parecer” e “Contra o parecer”, em cinza, com “sentido não determinado”. Placar inconsistente mostra somente os totais oficiais e a nota, sem nomes. A participação nominal conta votos substantivos (inclusive abstenção, branco e nulo); presidência aparece à parte. “Como votou” usa apenas sentidos determinados e consistentes. Um voto na opção menos votada ainda pode ser identificado pelo rótulo original, mas sem lhe atribuir um sentido que não foi determinado.</p>
<h3>Votações divididas e ritmo</h3>
<p>Uma votação é dividida com ao menos 3 votos no lado menor entre Favor e Contra, ou ao menos 3 abstenções. Com 1 ou 2 votos diferentes ou abstenções, é dissenso isolado; sem eles, unânime. Inconsistentes ficam separados no gráfico. A comparação individual conta apenas Favor/Contra na opção minoritária em votações divididas, sem empates; não há ordenação dos vereadores por esse indicador. Ritmo conta sessões listadas por mês e tipo, não horas de trabalho.</p>
<h3>Qualidade e limitações</h3>
<p>Nomes são associados exatamente aos membros conhecidos da legislatura, sem aproximação. Não membros ficam fora das métricas e aparecem na qualidade. Duplicatas idênticas não multiplicam votos; presidência prevalece sobre ausência, e votos substantivos conflitantes ficam indeterminados. A qualidade lista sessões sem frequência, inconsistências, sentidos não determinados, duplicados e notas.</p>
<p>Contar presença e votos não mede qualidade do mandato. Comissões, debates, atendimento e votações simbólicas não aparecem nestes indicadores. Uma lista de abertura não mede permanência durante toda a sessão. A ausência de registro não prova ausência de trabalho; a cobertura do SISCAM e as pendências de coleta limitam todas as comparações.</p>
<p>Encontrou erro? {_contestar("Presença ou votos", "Informe sessão, data, documento e fonte pública.")} por issue, informando a sessão, o documento e uma fonte pública. As regras valem igualmente para todos.</p>
</section>'''
