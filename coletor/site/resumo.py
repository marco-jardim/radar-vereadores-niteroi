"""Resumo determinístico das fichas: mesmas frases e bases para todas as pessoas, sem IA."""
from __future__ import annotations

from coletor.site.mandatos import linhas_mandatos
from coletor.site.modelo import resumo_bairros


PALAVRAS_PROIBIDAS = (
    "pouco", "pouca", "muito", "muita", "apenas", "somente", "só", "destaque", "relevante",
    "produtivo", "improdutivo", "ativo", "inativo", "polêmic", "melhor", "pior", "mais que",
    "menos que", "média", "acima", "abaixo", "veterano", "novato",
)


def _numero(valor: float) -> str:
    """Uma casa decimal quando necessária, com separadores pt-BR."""
    return f"{valor:,.1f}".rstrip("0").rstrip(".").replace(",", "_").replace(".", ",").replace("_", ".")


def _cargos(linha: dict) -> list[str]:
    from coletor.site import paginas as P

    frases = [f'Mesa Diretora: {P.esc(m["cargo"])} ({P.esc(m["bienio"].replace("-", "–"))}) '
              f'({P.link_fonte(m["fonte"])}).' for m in sorted(
                  linha.get("mesa") or [], key=lambda m: (m["bienio"], m["cargo"], m["fonte"]))]
    afastamentos = sorted(linha.get("afastamentos") or [], key=lambda a: (
        a.get("inicio") or a.get("aprovacao") or "", a["cargo"], a["fonte"]))
    for a in afastamentos:
        if a["natureza"] != "cargo":
            continue
        datas = "; ".join(f'{rotulo} {P.data_br(a[k])}' for k, rotulo in (
            ("inicio", "a partir de"), ("fim", "até"), ("aprovacao", "aprovado em")) if a.get(k))
        frases.append(f'Em outro cargo: {P.esc(a["cargo"])} '
                      f'({P.esc(datas or "datas não registradas")}) ({P.link_fonte(a["fonte"])}).')
    licencas = [a for a in afastamentos if a["natureza"] == "licenca"]
    if licencas:
        fontes = ", ".join(P.link_fonte(a["fonte"]) for a in licencas)
        frases.append(f'Licenças registradas: {P.milhar(len(licencas))} ({fontes}).')
    return frases


def frases_legislatura(modelo: dict, pessoa: dict, leg: dict) -> list[str]:
    """Frases HTML escapadas, na ordem exercício/cargos/presença/PLs/documentos/votos."""
    from coletor.site import paginas as P

    s, leg_id = pessoa["slug"], leg["id"]
    registro = ((modelo.get("sessoes") or {}).get("por_pessoa") or {}).get(s, {}).get(leg_id, {})
    mandato = (pessoa.get("mandatos") or {}).get(leg_id, {})
    linha = next((l for l in linhas_mandatos(modelo, leg) if l["slug"] == s), None)
    if linha is None:
        # Mandatos sem frequência também podem ter cargos documentados na configuração.
        cfg = modelo.get("cfg") or {}
        linha = {chave: [a for a in cfg.get(chave, []) if a["legislatura"] == leg_id
                        and a["siscam"] == pessoa.get("nome_siscam")]
                 for chave in ("mesa", "afastamentos")}
    frases = []
    if linha.get("sessoes", 0):
        meses = linha.get("meses") or 0
        duracao = ("menos de um mês" if meses < 1 else
                   f'cerca de {_numero(meses)} {"mês" if round(meses, 1) == 1 else "meses"}')
        frases.append(f'Exerceu o mandato em {P.milhar(linha["sessoes"])} de {P.milhar(linha["total"])} '
                      f'sessões deliberativas com lista de presença ({duracao}).')
    else:
        frases.append("Sem registro de sessões em exercício nesta legislatura.")
    frases.extend(_cargos(linha))

    presenca = registro.get("presenca") or {}
    if presenca.get("denominador", 0) >= 10 and presenca.get("pct") is not None:
        fora = [f'{P.milhar(presenca[c])} {rotulo}' for c, rotulo in (
            ("J", "ausências justificadas"), ("O", "em outro cargo"), ("L", "de licença")) if presenca.get(c)]
        nota = ("; " + (", ".join(fora[:-1]) + " e " + fora[-1] if len(fora) > 1 else fora[0])
                + ", fora da base") if fora else ""
        frases.append(f'Presença efetiva: {_numero(presenca["pct"])}% '
                      f'({P.milhar(presenca.get("A", 0))} faltas não abonadas{nota}).')
    else:
        frases.append("Presença: base inferior a 10 sessões, sem percentual.")

    projetos = mandato.get("projetos_autor") or []
    leis = sum(p.get("desfecho") == "virou_lei" for p in projetos)
    frases.append(f'Projetos de lei como autor principal: {P.milhar(len(projetos))}; '
                  f'{"virou lei" if leis == 1 else "viraram lei"}: {P.milhar(leis)}.' if projetos else
                  'Projetos de lei como autor principal: sem registro.')

    atividade = (modelo.get("atividade") or {}).get(s) or pessoa.get("atividade") or {}
    tipos = (atividade.get("por_leg") or {}).get(leg_id, {}).get("tipos") or {}
    documentos = [f'{rotulo}: {P.milhar(tipos[t])}.' for t, rotulo in (
        ("requerimento", "Requerimentos"), ("indicacao", "Indicações"), ("mocao", "Moções")) if tipos.get(t)]
    frases.append(" ".join(documentos) or "Requerimentos, indicações e moções: sem registro.")
    if tipos.get("indicacao"):
        docs = [d for d in atividade.get("documentos") or [] if d.get("legislatura") == leg_id]
        bairros = resumo_bairros(docs, top=3)["top"]
        if bairros:
            frases.append("Bairros mais citados nas indicações: " + ", ".join(
                f'{P.esc(b)} ({P.milhar(n)})' for b, n in bairros) + ".")

    participacao = registro.get("participacao") or {}
    presidindo = participacao.get("presidindo", 0)
    base = participacao.get("possiveis", 0) - presidindo
    if base >= 10:
        votou = participacao.get("votou", 0)
        frase = (f'Votou em {_numero(100 * votou / base)}% das votações nominais possíveis '
                 f'({P.milhar(votou)} de {P.milhar(base)})')
    else:
        frase = "Votações nominais: base inferior a 10"
    if presidindo:
        frase += f'; presidiu a sessão em {P.milhar(presidindo)} delas'
    frases.append(frase + ".")
    if "divididas" in registro and not registro["divididas"]:
        frases.append("Votações divididas com sentido conhecido: sem registro.")
    elif "divididas" in registro:
        frases.append(f'Votou diferente da maioria em {P.milhar(len(registro.get("divergencias") or []))} '
                      f'de {P.milhar(registro["divididas"])} votações divididas com sentido conhecido.')
    return frases


def secao_resumo(modelo: dict, pessoa: dict, prefixo: str = "../") -> str:
    """Uma seção estática, com um parágrafo por legislatura, sem modificar o modelo."""
    from coletor.site import paginas as P

    registros = ((modelo.get("sessoes") or {}).get("por_pessoa") or {}).get(pessoa["slug"], {})
    legs = set(pessoa.get("mandatos") or {}) | set(registros)
    blocos = []
    for leg in sorted(modelo.get("legislaturas") or [], key=lambda l: l["inicio"], reverse=True):
        if leg["id"] in legs:
            blocos.append(f'<h3>Legislatura {P.esc(leg["id"])}</h3>'
                          f'<p data-resumo-leg="{P.esc(leg["id"])}">'
                          + " ".join(frases_legislatura(modelo, pessoa, leg)) + '</p>')
    return ('<section class="resumo-numeros" aria-labelledby="t-resumo-numeros">'
            '<h2 id="t-resumo-numeros">Resumo em números</h2>' + "".join(blocos)
            + '<p class="explica">Resumo gerado automaticamente a partir dos dados do SISCAM, '
            'com as mesmas frases para todos os vereadores. '
            f'<a href="{P.esc(prefixo)}metodologia.html#resumo">Como é feito</a>.</p></section>')
