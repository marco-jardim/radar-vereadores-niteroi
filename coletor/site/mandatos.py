"""Eleições registradas e atividade individual por legislatura, sem agregações por carreira."""
from __future__ import annotations

from datetime import date

from coletor.site import graficos as G
from coletor.site.modelo import partido_em, slug


def anos_eleito(perfil: dict, ate: int | None = None) -> list[int]:
    """Anos distintos de vitórias para vereador, até o ano eleitoral do recorte."""
    return sorted({e["ano"] for e in perfil.get("eleicoes") or []
                   if e.get("cargo", "").strip().casefold() == "vereador"
                   and e.get("resultado", "").strip().casefold().startswith("eleito")
                   and (ate is None or e["ano"] <= ate)})


def linhas_mandatos(modelo: dict, leg: dict) -> list[dict]:
    """Taxas por mês estimado pelas listas; bases insuficientes permanecem ausentes."""
    leg_id = leg["id"]
    pessoas = modelo["pessoas"]
    sessoes = modelo.get("sessoes") or {}
    cobertura = (sessoes.get("exercicio") or {}).get(leg_id, {})
    total = cobertura.get("total", 0)
    primeira, ultima = cobertura.get("primeira"), cobertura.get("ultima")
    meses = ((date.fromisoformat(ultima) - date.fromisoformat(primeira)).days / (365.25 / 12)
             if primeira and ultima else 0)
    cfg = modelo.get("cfg") or {}
    indice = {p["nome_siscam"]: s for s, p in pessoas.items()}
    linhas = []
    registros = sessoes.get("por_pessoa") or {}
    for s in set(pessoas) | set(registros):
        pessoa = pessoas.get(s, {})
        mandato = (pessoa.get("mandatos") or {}).get(leg_id, {})
        registro = registros.get(s, {}).get(leg_id, {})
        presenca = registro.get("presenca") or {}
        listadas = presenca.get("listadas", 0)
        if not mandato.get("eleito") and not listadas and not registro.get("condicao"):
            continue
        perfil = (modelo.get("perfis") or {}).get(s) or pessoa.get("perfil") or {}
        anos = anos_eleito(perfil, int(leg["inicio"][:4]) - 1)
        mesa = [m for m in cfg.get("mesa", []) if m["legislatura"] == leg_id
                and indice.get(m["siscam"], slug(m["siscam"])) == s]
        afastamentos = [a for a in cfg.get("afastamentos", []) if a["legislatura"] == leg_id
                       and indice.get(a["siscam"], slug(a["siscam"])) == s]
        participacao = registro.get("participacao") or {}
        presidindo = participacao.get("presidindo", 0)
        base = participacao.get("possiveis", 0) - presidindo
        meses_exercicio = meses * listadas / total if total else 0
        tipos = ((modelo.get("atividade") or {}).get(s, {}).get("por_leg") or {}).get(leg_id, {}).get("tipos", {})
        pls = (mandato.get("metricas") or {}).get("apresentados", 0)
        situacao = (perfil.get("mandatos") or {}).get(leg_id, {}).get("situacao")
        linhas.append({
            "slug": s, "nome": pessoa.get("nome") or registro.get("nome") or s,
            "pagina": s in pessoas, "partido": partido_em(modelo, s, leg_id),
            "situacao": (situacao if situacao in {"eleito", "eleita"} else "eleito")
                        if mandato.get("eleito") else "suplente em exercício",
            "anos": anos, "eleicoes": len(anos) if perfil else None,
            "mesa": mesa, "afastamentos": afastamentos,
            "cargo": bool(mesa or any(a["natureza"] == "cargo" for a in afastamentos)),
            "sessoes": listadas, "total": total, "meses": meses_exercicio,
            "presenca": presenca.get("pct") if presenca.get("denominador", 0) >= 10 else None,
            "nominais": 100 * participacao.get("votou", 0) / base if base >= 10 else None,
            "presidindo": presidindo,
            "pls": pls / meses_exercicio if meses_exercicio > 0 else None,
            "pedidos": (tipos.get("requerimento", 0) + tipos.get("indicacao", 0)) / meses_exercicio
                       if meses_exercicio > 0 else None,
        })
    from coletor.site.paginas import _chave_nome
    return sorted(linhas, key=lambda l: (_chave_nome(l["nome"]), l["slug"]))


COLUNAS = ("Vereador", "Situação", "Eleições para vereador", "Cargos no período", "Sessões em exercício",
           "Presença efetiva", "Votou nas nominais", "PLs como autor principal por mês em exercício",
           "Requerimentos e indicações por mês em exercício")
ORDENS = (("nome", "Nome"), ("eleicoes", COLUNAS[2]), ("sessoes", COLUNAS[4]),
          ("presenca", COLUNAS[5]), ("nominais", COLUNAS[6]), ("pls", "PLs/mês"),
          ("pedidos", "Requerimentos e indicações/mês"))
NOTA = ('Eleições conta vitórias para vereador até a eleição da legislatura; não conta exercício apenas como suplente. '
        'Sem histórico eleitoral disponível, a contagem fica vazia; zero significa nenhuma vitória registrada. '
        'Eleições de 1988/1992 têm fonte na Wikipédia; de 1996 em diante, no TSE (fontes nas fichas). '
        'Cargos e licenças são os registros da configuração, não uma lista exaustiva. '
        'Sessões em exercício é o número de sessões em cuja lista a pessoa consta, sobre o total de deliberativas '
        'incluídas na presença da legislatura. Presença efetiva usa P/C/V ÷ (P/C/V + A). '
        'Votou nas nominais usa votou ÷ (possíveis − presidindo); entre parênteses, quantas presidiu. '
        'Percentuais exigem base de dez. Meses em exercício são uma estimativa pelas listas de frequência: '
        'dias entre a primeira e a última deliberativa ÷ (365,25/12) × (sessões listadas ÷ total). '
        'As taxas dividem PLs como autor principal e requerimentos + indicações de qualquer autoria por esses meses; '
        'sem meses positivos, ficam vazias. Contar documentos, presença ou votos não mede qualidade, trabalho em '
        'comissões, relatorias ou articulação política. Cargos na Mesa Diretora e no Executivo alteram a atividade '
        'típica de plenário. <a href="metodologia.html#sessoes">Metodologia</a>.')


def secao_mandatos(modelo: dict) -> str:
    """Uma tabela alfabética por legislatura, com ordenação e filtro progressivos."""
    from coletor.site import paginas as P

    def numero(valor: float | None, percentual: bool = False) -> str:
        return "—" if valor is None else f"{valor:.1f}".replace(".", ",") + ("%" if percentual else "")

    blocos = []
    for leg in reversed(modelo["legislaturas"]):
        linhas = linhas_mandatos(modelo, leg)
        if not linhas:
            continue
        trs = []
        for l in linhas:
            nome = P.esc(l["nome"]) + P.partido_html(l["partido"])
            if l["pagina"]:
                nome = f'<a href="vereadores/{P.esc(l["slug"])}.html">{nome}</a>'
            cargos = [f'Mesa Diretora: {P.esc(m["cargo"])} ({P.esc(m["bienio"])}) ({P.link_fonte(m["fonte"])})'
                      for m in l["mesa"]]
            licencas = [a for a in l["afastamentos"] if a["natureza"] == "licenca"]
            for a in l["afastamentos"]:
                if a["natureza"] != "cargo":
                    continue
                datas = "; ".join(f'{rotulo} {P.data_br(a[k])}' for k, rotulo in
                                  (("inicio", "início"), ("fim", "fim"), ("aprovacao", "aprovação")) if a.get(k))
                cargos.append(f'Em outro cargo: {P.esc(a["cargo"])}'
                              + (f' ({P.esc(datas)})' if datas else ' (datas não registradas)')
                              + f' ({P.link_fonte(a["fonte"])})')
            if licencas:
                fontes = ", ".join(P.link_fonte(a["fonte"], f'fonte {i}') for i, a in enumerate(licencas, 1))
                rotulo = "licença registrada" if len(licencas) == 1 else "licenças registradas"
                cargos.append(f'{len(licencas)} {rotulo} ({fontes})')
            anos = ", ".join(map(str, l["anos"]))
            eleicoes = (f'<span title="Eleições para vereador: {anos or "nenhuma vitória registrada"}">'
                        f'{l["eleicoes"]}</span>' if l["eleicoes"] is not None else "—")
            nominal = numero(l["nominais"], True)
            if l["presidindo"]:
                nominal += f' ({l["presidindo"]} presidindo)'
            valores = [P.esc(l["situacao"]), eleicoes, "<br>".join(cargos) or "—",
                       f'{l["sessoes"]} de {l["total"]}', numero(l["presenca"], True), nominal,
                       numero(l["pls"]), numero(l["pedidos"])]
            atributos = f' data-nome="{P.esc(l["nome"])}" data-cargo="{int(l["cargo"])}"'
            atributos += "".join(f' data-{k}="{l[k] if l[k] is not None else ""}"' for k, _ in ORDENS[1:])
            trs.append(f'<tr role="row"{atributos}>' + G.cab_linha(nome, COLUNAS[0])
                       + "".join(G.celula(v, c) for v, c in zip(valores, COLUNAS[1:])) + '</tr>')
        opcoes = "".join(f'<option value="{k}">{P.esc(v)}</option>' for k, v in ORDENS)
        tabela = G.abre_tabela(len(COLUNAS)) + G.fecha_tabela(
            "".join(G.cab_coluna(P.esc(c)) for c in COLUNAS), "".join(trs))
        blocos.append(f'<section class="bloco-leg" data-mandatos><h3>Legislatura {P.esc(leg["id"])}</h3>'
                      f'<div class="filtros" data-controles-mandatos hidden>'
                      f'<label>Ordenar por <select data-ordem-mandatos>{opcoes}</select></label>'
                      '<label><input type="checkbox" data-ocultar-cargos> Ocultar quem exerceu cargo na Mesa Diretora '
                      'ou em outro cargo no período</label></div>'
                      f'<div class="tabela-rolavel" role="region" tabindex="0" '
                      f'aria-label="Mandatos e atividade na Câmara, legislatura {P.esc(leg["id"])}">{tabela}</div>'
                      f'<p class="explica">{NOTA}</p></section>')
    return ('<section id="mandatos-atividade" aria-labelledby="t-mandatos-atividade">'
            '<h2 id="t-mandatos-atividade" class="h-secao">Mandatos e atividade na Câmara</h2>'
            + "".join(blocos) + '</section>') if blocos else ""
