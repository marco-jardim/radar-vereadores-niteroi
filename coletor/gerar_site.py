"""Gera o site estático em ./site a partir de data/ e config/.

Uso: python -m coletor.gerar_site
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

from coletor import novidades as N
from coletor import regras_documentos as RD
from coletor import regras_sessoes as RS
from coletor.site import inicio, modelo_sessoes, pagina_memoria, pagina_sessoes
from coletor.site import paginas as P
from coletor.site.modelo import (
    DESFECHO_GRUPO, NOME_ALERTA, NOME_CATEGORIA, NOME_CATEGORIA_DOC, NOME_DESFECHO, NOME_SINAL, NOME_SUBCATEGORIA_DOC,
    NOME_TEMA, NOME_TIPO_DOC, TIPOS_COM_DETALHE, TIPOS_DOC, URL_DETALHE, com_efeito, montar_modelo, nome_curto, sem_efeito, slug,
)

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "site"
FONTE_ESTATICA = RAIZ / "site_src"
LIMITE_HTML_GZIP = 100 * 1024
LIMITE_JSON_GZIP = 200 * 1024
FATIAS_PL = ("pl-lei", "pl-andamento", "pl-sem_exito")
# Prévia de projetos.html sem filtros: as primeiras linhas na ordem padrão, no formato das fatias.
PREVIA_PL = "pl-recentes"
JSON_BUSCADOS = {f"dados/{nome}.json" for nome in ("manifest", "dic-pl", "dic-doc", "dic-ses", *FATIAS_PL, PREVIA_PL)}
# Documentos: fatiar com alvo de 120 KiB gzip deixa folga para o orçamento oficial de 150 KiB do relatório.
# As primeiras (mais recentes) de cada tipo/ano são menores, para que a carga inicial de atividades.html
# (dic-doc + primeiras partes de cada tipo) fique em até 200 KiB.
LIMITE_PARTE_DOC_GZIP = 150 * 1024
ALVO_PARTE_DOC_GZIP = 120 * 1024
LIMITE_PRIMEIRA_PARTE_DOC_GZIP = 24 * 1024
LIMITE_INICIAL_GZIP = 200 * 1024
MARGEM_GZIP = 512  # folga para o nível de compressão do relatório
AMOSTRA_LINHAS = 256  # linhas comprimidas para estimar os bytes por linha da primeira parte
COLUNAS_DOC = ("id", "tp", "n", "a", "d", "e", "st", "as", "au", "c", "sc", "h", "rs", "re", "dr", "pu", "pb", "b", "dp")
LIMITE_PARTE_VOT_GZIP = 150 * 1024
VOTOS_SESSOES = (("F", "Favor"), ("C", "Contra"), ("S", "Abstenção"), ("X", "Ausente"), ("R", "Presidente"),
                 ("B", "Branco"), ("N", "Nulo"), ("I", "indeterminado"), (".", "não consta"))
MATERIAS_SESSOES = (("veto", "Vetos", "Veto"), ("pl", "Projetos de lei", "Projeto de lei"),
                    ("pdl", "Projetos de decreto legislativo", "Projeto de decreto legislativo"),
                    ("resolucao", "Projetos de resolução", "Projeto de resolução"), ("outra", "Outras matérias", "Outra matéria"))
SENTIDOS_SESSOES = ("favor_mantem", "favor_derruba", "favor_aprova", "favor_rejeita", "indeterminado", "inconsistente")
COLUNAS_VOT = ("id", "s", "d", "ts", "m", "doc", "n", "e", "r", "t", "to", "cl", "sx", "mj", "q", "ql", "nt", "v")


def dados_cliente(modelo: dict) -> dict:
    """Contrato legado dos registros, também usado para validar a exportação em colunas."""
    pessoas = {s: p["nome"] for s, p in modelo["pessoas"].items()}
    projetos = []
    for p in sorted(modelo["projetos"], key=lambda p: p["data"] or "", reverse=True):
        lei = p.get("lei") or {}
        projetos.append({
            "n": p["numero"], "a": p["ano"], "d": p["data"], "e": p["ementa"], "u": p["url"],
            "r": p["resumo"], "pb": p["publico"], "t": p["tema"],
            "g": DESFECHO_GRUPO.get(p["desfecho"], "andamento"), "dx": NOME_DESFECHO.get(p["desfecho"], p["desfecho"]),
            "c": p["categoria"], "i": p["impacto"], "ef": int(com_efeito(p)), "se": int(sem_efeito(p)),
            "l": lei.get("numero"), "ld": lei.get("data"), "lt": lei.get("tipo"), "vp": int(bool(lei.get("veto_parcial"))),
            # Página do substitutivo de onde saiu a lei; u continua sendo a do PL original.
            "ls": URL_DETALHE.format(id=p["lei_substitutivo"]) if p.get("lei_substitutivo") else None,
            "dl": p["dias_ate_lei"],
            "o": p["origem"], "lg": p["legislatura"], "pt": p["partido"], "pr": p["principal"],
            "au": [[a["exibicao"], a["slug"] if a["vereador"] else ""] for a in p["autores"]],
            "al": [[NOME_ALERTA.get(a["rotulo"], a["rotulo"]), a["origem"], a.get("nota", "")] for a in p["alertas"]],
            "pol": int(p["polemico"]),
            "s": [s for s in p["sinais"]],
            "rp": p["repete"]["numero"] if p.get("repete") else None,
        })
    return {
        "projetos": projetos,
        "pessoas": pessoas,
        "temas": NOME_TEMA,
        "sinais": NOME_SINAL,
        "legislaturas": [l["id"] for l in modelo["legislaturas"]],
    }


def json_compacto(dados: dict) -> bytes:
    return json.dumps(dados, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def exportar_fatias(modelo: dict, cliente: dict, saida: Path) -> dict:
    """Dicionários e colunas reversíveis; a ordem original também desempata as buscas."""
    registros = sorted(modelo["projetos"], key=lambda p: p["data"] or "", reverse=True)
    pessoas = {
        (s, p["nome"]): {leg: m["partido"] for leg, m in sorted(p["mandatos"].items())}
        for s, p in sorted(modelo["pessoas"].items())
    }
    for p in cliente["projetos"]:
        for nome, s in p["au"]:
            pessoas.setdefault((s, nome), {})

    def pares(nomes: dict, usados: set) -> list:
        return [[s, nomes.get(s, s)] for s in sorted(set(nomes) | usados)]

    dic = {
        "pessoas": [[s, nome, partidos] for (s, nome), partidos in sorted(pessoas.items())],
        "temas": pares(NOME_TEMA, {p["t"] for p in cliente["projetos"]}),
        "sinais": pares(NOME_SINAL, {s for p in cliente["projetos"] for s in p["s"]}),
        "desfechos": [[s, NOME_DESFECHO.get(s, s), DESFECHO_GRUPO.get(s, "andamento")]
                      for s in sorted(set(NOME_DESFECHO) | {p["desfecho"] for p in registros})],
        "categorias": pares(NOME_CATEGORIA, {p["c"] for p in cliente["projetos"]}),
        "alertas": pares(NOME_ALERTA, {a["rotulo"] for p in registros for a in p["alertas"]}),
        "origens": sorted({p["o"] for p in cliente["projetos"]} | {a[1] for p in cliente["projetos"] for a in p["al"]}),
        "legislaturas": sorted(cliente["legislaturas"]),
        "url_detalhe": "https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento={id}",
    }
    indices = {k: {v[0]: i for i, v in enumerate(dic[k])}
               for k in ("temas", "sinais", "desfechos", "categorias", "alertas")}
    indices.update({k: {v: i for i, v in enumerate(dic[k])} for k in ("origens", "legislaturas")})
    autores = {(s, nome): i for i, (s, nome, _) in enumerate(dic["pessoas"])}
    principais = {s: i for i, (s, _, _) in enumerate(dic["pessoas"]) if s}
    # h referencia desfechos; ord restaura a ordem global ao reunir as três fatias; ls é o id do substitutivo da lei.
    nomes_colunas = ("id", "ord", "n", "a", "d", "e", "r", "pb", "t", "h", "c", "i", "l", "ld", "lt", "vp", "dl", "o", "lg", "pr", "au", "al", "pol", "s", "rp", "ls")
    fatias = {nome: {"nome": nome, "n": 0, "colunas": {k: [] for k in nomes_colunas}} for nome in FATIAS_PL}
    recentes = []
    for ordem, (reg, p) in enumerate(zip(registros, cliente["projetos"], strict=True)):
        if p["u"] != dic["url_detalhe"].format(id=reg["id"]):
            raise ValueError(f"URL fora do modelo de detalhes: {p['u']}")
        ls = reg.get("lei_substitutivo")
        if p["ls"] != (dic["url_detalhe"].format(id=ls) if ls else None):
            raise ValueError(f"URL do substitutivo fora do modelo de detalhes: {p['ls']}")
        linha = {k: p[k] for k in ("n", "a", "d", "e", "r", "pb", "i", "l", "ld", "lt", "vp", "dl", "pol", "rp")}
        linha.update({k: indices[tabela][p[k]] for k, tabela in (("t", "temas"), ("c", "categorias"), ("o", "origens"))})
        linha.update({
            "id": reg["id"], "ord": ordem, "h": indices["desfechos"][reg["desfecho"]], "ls": ls or None,
            "lg": indices["legislaturas"][p["lg"]] if p["lg"] is not None else None,
            "pr": principais[p["pr"]] if p["pr"] is not None else None,
            "au": [autores[(s, nome)] for nome, s in p["au"]],
            "al": [[indices["alertas"][a["rotulo"]], indices["origens"][a["origem"]], a.get("nota", "")] for a in reg["alertas"]],
            "s": [indices["sinais"][s] for s in p["s"]],
        })
        fatia = fatias[f"pl-{p['g']}"]
        fatia["n"] += 1
        for k in nomes_colunas:
            fatia["colunas"][k].append(linha[k])
        if ordem < P.PASSO_LISTA:
            recentes.append(linha)
    # O build depende de todos os bytes lógicos, inclusive dos dicionários; a prévia é derivada das fatias.
    build = hashlib.sha1(json_compacto(dic) + b"".join(json_compacto(f) for f in fatias.values())).hexdigest()[:10]
    # Mesmas linhas (inclusive ord) e o mesmo build das fatias: hidratar() a lê como qualquer fatia, e o
    # navegador a usa só para desenhar a primeira tela; as contagens vêm prontas no HTML (P.resumo_projetos).
    previa = {"nome": PREVIA_PL, "n": len(recentes), "colunas": {k: [l[k] for l in recentes] for k in nomes_colunas}}
    manifesto = {"esquema": 2, "build": build, "arquivos": {}}
    for nome, dados in (("dic-pl", {"n": len(pessoas), **dic}), *fatias.items(), (PREVIA_PL, previa)):
        conteudo = json_compacto({"esquema": 2, "build": build, **dados})
        caminho = f"dados/{nome}.json"
        (saida / caminho).write_bytes(conteudo)
        manifesto["arquivos"][nome] = {"url": f"{caminho}?v={P.versao_bytes(conteudo)}", "n": dados["n"], "bytes": len(conteudo)}
    escrever_manifesto(manifesto, saida)
    return manifesto


def escrever_manifesto(manifesto: dict, saida: Path) -> None:
    (saida / "dados/manifest.json").write_bytes(json_compacto(manifesto))


# ------------------------------------------------------------- demais documentos
def tamanho_gzip(conteudo: bytes, nivel: int = 9) -> int:
    return len(gzip.compress(conteudo, compresslevel=nivel, mtime=0))


def dicionario_documentos(modelo: dict) -> dict:
    """Só as enumerações estáveis: tipos, categorias, subcategorias e o modelo de URL.

    Autores, situações e bairros mudam a cada coleta e ficam em dicionários locais de cada parte
    (fatia_documentos): uma parte cujos documentos não mudaram mantém os mesmos bytes e a mesma URL.
    """
    docs = modelo["documentos"]
    categorias = list(RD.CATEGORIAS) + sorted({d["categoria"] for d in docs} - set(RD.CATEGORIAS))
    subcategorias = [(t, s) for t in TIPOS_DOC for s in RD.SUBCATEGORIAS.get(t, ())]
    subcategorias += sorted({(d["tipo"], d["subcategoria"]) for d in docs} - set(subcategorias))
    return {
        "tipos": [[t, *NOME_TIPO_DOC[t], int(t in TIPOS_COM_DETALHE)] for t in TIPOS_DOC],
        "categorias": [[c, NOME_CATEGORIA_DOC.get(c, c)] for c in categorias],
        "subcategorias": [[t, s, NOME_SUBCATEGORIA_DOC.get((t, s), s)] for t, s in subcategorias],
        "url_detalhe": URL_DETALHE,
    }


def linhas_documentos(modelo: dict, dic: dict) -> list[dict]:
    """Uma linha por documento, na mesma ordem de modelo["documentos"].

    tp, c e sc já são índices nas enumerações de dic-doc; au (slug, nome, tem página), st e b guardam os
    próprios valores, trocados por índices nos dicionários locais em fatia_documentos.
    """
    idx = {
        "tipos": {t[0]: i for i, t in enumerate(dic["tipos"])},
        "categorias": {c[0]: i for i, c in enumerate(dic["categorias"])},
        "subcategorias": {(t, s): i for i, (t, s, _) in enumerate(dic["subcategorias"])},
    }
    linhas = []
    for d in modelo["documentos"]:
        if d["url"] != dic["url_detalhe"].format(id=d["id"]):
            raise ValueError(f"URL fora do modelo de detalhes: {d['url']}")
        pub = d["publicacao"]
        linhas.append({
            "id": d["id"], "tp": idx["tipos"][d["tipo"]], "n": d["numero"], "a": d["ano"], "d": d["data"], "e": d["ementa"],
            "st": d["situacao"], "as": d["assunto"],
            "au": [(a["slug"], a["exibicao"], int(bool(a["pagina"]))) for a in d["autores"]],
            "c": idx["categorias"][d["categoria"]], "sc": idx["subcategorias"][(d["tipo"], d["subcategoria"])],
            "h": int(d["homenagem"]), "rs": int(d["respondido"]), "re": d["respondido_em"], "dr": d["dias_ate_resposta"],
            "pu": int(d["publicado"]), "pb": [pub["numero"], pub["data"]] if pub else None,
            "b": d["bairro"] or None, "dp": int(d["detalhe_pendente"]),
        })
    return linhas


def nome_parte(base: str, k: int) -> str:
    return base if k == 0 else f"{base}-{k}"


def fatia_documentos(nome: str, linhas: list[dict], extra: dict) -> dict:
    """Parte em colunas, sem build: o conteúdo depende só das próprias linhas e das enumerações de dic-doc.

    pessoas ([slug, nome, tem página]), situacoes e bairros são dicionários locais, ordenados.
    """
    pessoas = sorted({a for l in linhas for a in l["au"]})
    situacoes = sorted({l["st"] for l in linhas})
    bairros = sorted({l["b"] for l in linhas if l["b"]}, key=lambda b: (slug(b), b))
    i_pessoa = {p: i for i, p in enumerate(pessoas)}
    i_situacao = {s: i for i, s in enumerate(situacoes)}
    i_bairro = {b: i for i, b in enumerate(bairros)}
    locais = {
        "au": lambda l: [i_pessoa[a] for a in l["au"]],
        "st": lambda l: i_situacao[l["st"]],
        "b": lambda l: None if l["b"] is None else i_bairro[l["b"]],
    }
    return {"esquema": 2, "nome": nome, "n": len(linhas), **extra,
            "pessoas": [list(p) for p in pessoas], "situacoes": situacoes, "bairros": bairros,
            "colunas": {k: [locais[k](l) if k in locais else l[k] for l in linhas] for k in COLUNAS_DOC}}


def partir_por_orcamento(linhas: list[dict], montar, limite_primeira: int, limite: int,
                         minimo_primeiras: int = P.PASSO_LISTA) -> list[list[dict]]:
    """Divide linhas já ordenadas em partes cujo JSON comprimido cabe no orçamento.

    montar(k, linhas) devolve o objeto da parte k. Uma data nunca fica dividida entre
    duas partes (salvo se sozinha estourar o orçamento): assim a fronteira usada por
    fatiasDocs no navegador é estrita e "Mostrar mais" só acrescenta itens ao fim.

    As primeiras partes usam limite_primeira até somarem minimo_primeiras linhas e
    terminarem numa troca de data. Se a data mais recente não couber numa parte pequena,
    o resto dela também vai em partes pequenas: a primeira tela nunca depende de uma parte grande.

    O tamanho é estimado pelos bytes por linha da parte anterior (ou de uma amostra, na
    primeira) e conferido comprimindo só a própria parte, nunca o restante inteiro.
    """
    partes: list[list[dict]] = []
    ini, primeiras, pequena, por_linha = 0, 0, True, None
    while ini < len(linhas):
        k = len(partes)
        orcamento = (limite_primeira if pequena else limite) - MARGEM_GZIP
        restante = len(linhas) - ini
        medidas: dict[int, int] = {}

        def cabe(m: int) -> bool:
            # nível 6 na busca: mais rápido e, em texto, em geral maior que o nível 9 do relatório (a margem cobre o resto)
            if m not in medidas:
                medidas[m] = tamanho_gzip(json_compacto(montar(k, linhas[ini:ini + m])), nivel=6)
            return medidas[m] <= orcamento

        def maior_que_cabe(bom: int, ruim: int) -> int:
            """Busca binária com cabe(bom) (ou bom == 0) e não cabe(ruim)."""
            while ruim - bom > 1:
                meio = (bom + ruim) // 2
                if cabe(meio):
                    bom = meio
                else:
                    ruim = meio
            return bom

        if por_linha is None:
            amostra = min(restante, AMOSTRA_LINHAS)
            cabe(amostra)
            por_linha = medidas[amostra] / amostra
        palpite = max(1, min(restante, int(orcamento / por_linha)))
        bom, ruim = 0, restante + 1  # restante + 1 é só sentinela: nunca é medido
        if cabe(palpite):
            bom = palpite
            while bom < restante:
                prox = min(restante, int(bom * 1.1) + 1)
                if not cabe(prox):
                    ruim = prox
                    break
                bom = prox
        else:
            ruim = palpite
            while (prox := int(ruim / 1.1)) > bom:
                if cabe(prox):
                    bom = prox
                    break
                ruim = prox
        m = max(maior_que_cabe(bom, ruim), 1)
        if m < restante:
            alinhado = m
            while alinhado > 0 and linhas[ini + alinhado - 1]["d"] == linhas[ini + alinhado]["d"]:
                alinhado -= 1
            if alinhado > 0:
                m = alinhado
        if m > 1 and not cabe(m):
            # O tamanho comprimido quase sempre cresce com o prefixo; ainda assim, a parte final é conferida.
            m = max(maior_que_cabe(0, m), 1)
        cabe(m)
        por_linha = medidas[m] / m
        partes.append(linhas[ini:ini + m])
        if pequena:
            primeiras += m
        ini += m
        pequena = pequena and ini < len(linhas) and (primeiras < minimo_primeiras or linhas[ini]["d"] == linhas[ini - 1]["d"])
    return partes


def versao_documentos(entradas: dict) -> str:
    """Resumo das URLs (que já trazem o hash de cada arquivo); só vai no manifesto."""
    return hashlib.sha1(json_compacto({n: e["url"] for n, e in sorted(entradas.items())})).hexdigest()[:10]


def exportar_documentos(modelo: dict, saida: Path, manifesto: dict) -> dict:
    """Famílias dic-doc, doc-<tipo>-<ano>[-k] e ver/<slug>[-<tipo>][-k] no mesmo manifesto.

    Os arquivos de documentos não levam build: a URL traz o hash do conteúdo, e cada parte depende só
    das próprias linhas e das enumerações estáveis de dic-doc. Assim, partes sem mudança mantêm bytes e
    URL de um build para outro. build_doc, só no manifesto, muda quando alguma parte muda, sem tocar no PL.
    Sem documentos coletados, o manifesto fica como está.
    """
    docs = modelo.get("documentos") or []
    if not docs:
        return manifesto
    dic = dicionario_documentos(modelo)
    linhas = linhas_documentos(modelo, dic)
    i_tipo = {t[0]: i for i, t in enumerate(dic["tipos"])}
    fatias: list[tuple[str, dict, dict]] = []  # (nome, conteúdo, metadados do manifesto)

    grupos: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for d, linha in zip(docs, linhas, strict=True):
        grupos[(d["tipo"], d["ano"])].append(linha)
    for tipo, ano in sorted(grupos, key=lambda g: (-g[1], TIPOS_DOC.index(g[0]) if g[0] in TIPOS_DOC else len(TIPOS_DOC), g[0])):
        base = f"doc-{tipo}-{ano}"
        extra = lambda k: {"tipo": tipo, "ano": ano, "parte": k}
        montar = lambda k, ls: fatia_documentos(nome_parte(base, k), ls, extra(k))
        for k, parte in enumerate(partir_por_orcamento(grupos[(tipo, ano)], montar, LIMITE_PRIMEIRA_PARTE_DOC_GZIP, ALVO_PARTE_DOC_GZIP)):
            fatias.append((nome_parte(base, k), montar(k, parte),
                           {"familia": "doc", **extra(k), "ate": parte[0]["d"], "de": parte[-1]["d"]}))

    por_autor: dict[str, list[dict]] = defaultdict(list)
    for d, linha in zip(docs, linhas, strict=True):
        for s in dict.fromkeys(a["slug"] for a in d["autores"] if a["vereador"]):
            por_autor[s].append(linha)
    for s in sorted(por_autor):
        base = f"ver/{s}"
        inteiro = fatia_documentos(base, por_autor[s], {"slug": s, "tipo": None, "parte": 0})
        if tamanho_gzip(json_compacto(inteiro), nivel=6) <= ALVO_PARTE_DOC_GZIP - MARGEM_GZIP:
            fatias.append((base, inteiro, {"familia": "ver", "slug": s, "tipo": None, "parte": 0}))
            continue
        for tipo in TIPOS_DOC:  # grande demais: um arquivo por tipo, em partes se preciso
            do_tipo = [l for l in por_autor[s] if l["tp"] == i_tipo[tipo]]
            if not do_tipo:
                continue
            base_t = f"{base}-{tipo}"
            montar = lambda k, ls: fatia_documentos(nome_parte(base_t, k), ls, {"slug": s, "tipo": tipo, "parte": k})
            for k, parte in enumerate(partir_por_orcamento(do_tipo, montar, ALVO_PARTE_DOC_GZIP, ALVO_PARTE_DOC_GZIP)):
                fatias.append((nome_parte(base_t, k), montar(k, parte), {"familia": "ver", "slug": s, "tipo": tipo, "parte": k}))

    (saida / "dados" / "ver").mkdir(parents=True, exist_ok=True)
    entradas = {}
    for nome, dados, meta in (("dic-doc", {"esquema": 2, "n": len(dic["tipos"]), **dic}, {"familia": "dic-doc"}), *fatias):
        conteudo = json_compacto(dados)
        caminho = f"dados/{nome}.json"
        (saida / caminho).write_bytes(conteudo)
        entradas[nome] = {"url": f"{caminho}?v={P.versao_bytes(conteudo)}", "n": dados["n"], "bytes": len(conteudo), **meta}
    manifesto["build_doc"] = versao_documentos(entradas)
    manifesto["arquivos"].update(entradas)
    escrever_manifesto(manifesto, saida)
    return manifesto


# ------------------------------------------------------------- votações nominais
def dicionario_sessoes() -> dict:
    """Enumerações estáveis; a tradução de votos vem das mesmas regras do servidor."""
    return {
        "esquema": 1,
        "votos": [list(v) for v in VOTOS_SESSOES],
        "materias": [list(m) for m in MATERIAS_SESSOES],
        "classes": [["unanime", "Unânime"], ["dissenso", "Com 1 ou 2 votos diferentes"], ["dividida", "Dividida"]],
        # Rótulos genéricos; rotulos especifica o objeto quando depende da matéria.
        "sentidos": [[s, RS.rotulo_voto("Favor", s, "outra"), RS.rotulo_voto("Contra", s, "outra")]
                     for s in SENTIDOS_SESSOES],
        "rotulos": {m: {s: [RS.rotulo_voto(v, s, m) for _, v in VOTOS_SESSOES[:7]]
                        for s in SENTIDOS_SESSOES} for m, _, _ in MATERIAS_SESSOES},
        "qualidade": ["ok", "inconsistente", "indeterminado"],
        "url_detalhe": URL_DETALHE.removesuffix("{id}"),
        "minimo_dividida": RS.MINIMO_DIVIDIDA,
        "quorum_veto": RS.QUORUM_DERRUBADA_VETO,
    }


def pessoa_votacao(modelo: dict, s: str, ano: int) -> list:
    """Metadados locais do ano, inclusive suplentes sem página e nomes não casados."""
    dados = modelo["sessoes"]
    pessoa = (modelo.get("pessoas") or {}).get(s) or {}
    entrada = (dados.get("por_pessoa") or {}).get(s) or {}
    legs = {str(l["id"]) for l in dados.get("legislaturas") or [] if ano in {int(a) for a in l.get("anos") or []}}
    registros = [r for leg, r in sorted(entrada.items()) if isinstance(r, dict) and (not legs or str(leg) in legs)]
    registro = next((r for r in registros if r.get("nome") or r.get("condicao") or r.get("sem_pagina")), {})
    nome = pessoa.get("nome") or entrada.get("nome") or registro.get("nome") or s
    condicao = entrada.get("condicao") or registro.get("condicao") or pessoa.get("condicao") or (
        "suplente em exercício" if registro.get("sem_pagina") else "")
    return [s, nome_curto(nome), int(s in (modelo.get("pessoas") or {})), condicao]


def numero_votacao(votacao: dict) -> str:
    """Referência curta, sem confundir o PL de um veto com o número da sessão."""
    referencia = str(votacao.get("documento") or votacao.get("numero") or "Documento não identificado")
    numero = re.search(r"\b(\d+)\s*/\s*(\d{4})\b", str(votacao.get("numero") or referencia))
    if not numero:
        return referencia
    tipos = (("projeto-de-decreto-legislativo", "PDL"), ("projeto-de-resolucao", "PR"), ("projeto-de-lei", "PL"),
             ("pdl", "PDL"), ("pl", "PL"), ("pr", "PR"), ("veto", "Veto"),
             ("substitutivo", "Substitutivo"), ("emenda", "Emenda"))
    normal = slug(referencia)
    tipo = next((sigla for nome, sigla in tipos if normal == nome or normal.startswith(nome + "-")), None)
    tipo = tipo or {"pl": "PL", "pdl": "PDL", "resolucao": "PR", "veto": "Veto"}.get(votacao.get("materia"))
    return f"{tipo} {int(numero[1])}/{numero[2]}" if tipo else referencia


def notas_votacao(votacao: dict) -> list[str]:
    """Só as explicações visíveis do cartão; as conferências técnicas não vão ao navegador."""
    notas = [n for n in votacao.get("notas") or [] if pagina_sessoes._nota_leitor(n)]
    determinada = pagina_sessoes._determinada(votacao)
    if votacao.get("qualidade") == "inconsistente":
        notas.insert(0, "Placar inconsistente: exibimos apenas os totais oficiais, sem atribuir votos a nomes.")
    elif not determinada:
        notas.insert(0, "Favor ao parecer / Contra o parecer: sentido não determinado.")
    elif votacao.get("fonte_sentido") == "texto_veto_ambiguo":
        notas.insert(0, "Sentido definido pelo texto do parecer na tramitação.")
    if votacao.get("materia") == "veto":
        houve = (votacao.get("quorum") or {}).get("derrubar") if determinada else None
        conclusao = f"houve {houve}." if houve is not None else "o número para derrubar não pôde ser determinado."
        notas.insert(0, "Derrubar o veto exige 11 votos (maioria absoluta dos 21 vereadores); " + conclusao)
    return notas


def fatia_votacoes(modelo: dict, ano: int, votacoes: list[dict]) -> dict:
    """Uma parte anual, sem build; cada posição de v corresponde a uma pessoa local."""
    pessoas = sorted({s for v in votacoes for s in v["votos"]})
    codigos = {v: c for c, v in VOTOS_SESSOES}
    linhas = []
    for v in sorted(votacoes, key=lambda v: (v.get("data") or "", str(v["id"])), reverse=True):
        totais = [v["totais"].get(c, 0) or 0 for c in modelo_sessoes.CAMPOS_TOTAIS]
        oficiais = v.get("totais_oficiais")
        publicados = [oficiais.get(c, 0) or 0 for c in modelo_sessoes.CAMPOS_TOTAIS] if oficiais is not None else None
        quorum = v.get("quorum")
        linhas.append({
            "id": v["id"], "s": v["sessao"], "d": v.get("data"), "ts": v.get("titulo_sessao") or "",
            "m": v["materia"], "doc": v.get("id_documento"), "n": numero_votacao(v), "e": v.get("ementa") or "",
            "r": v.get("resultado") or "", "t": totais, "to": publicados if publicados != totais else None,
            "cl": v["classe"], "sx": v["sentido"], "mj": codigos.get(v.get("maioria")),
            "q": [quorum[c] for c in ("exigido", "derrubar", "manter")] if quorum is not None else None,
            "ql": v["qualidade"], "nt": notas_votacao(v),
            "v": "".join(codigos.get(v["votos"][s], "I") if s in v["votos"] else "." for s in pessoas),
        })
    return {"esquema": 1, "ano": ano, "n": len(linhas), "pessoas": [pessoa_votacao(modelo, s, ano) for s in pessoas],
            "colunas": {c: [l[c] for l in linhas] for c in COLUNAS_VOT}}


def exportar_sessoes(modelo: dict, saida: Path, manifesto: dict) -> dict:
    """dic-ses e vot-<ano> por conteúdo; mudar um ano não invalida os demais nem os PLs."""
    dados = modelo.get("sessoes") or {}
    votacoes = dados.get("votacoes") or []
    if not votacoes:
        return manifesto
    sessoes = {s["id"]: s for s in dados.get("sessoes") or []}
    por_ano: dict[int, list[dict]] = defaultdict(list)
    for v in votacoes:
        sessao = sessoes.get(v["sessao"]) or {}
        ano = v.get("ano") or sessao.get("ano")
        data = v.get("data") or sessao.get("data")
        if ano is None and data:
            ano = int(data[:4])
        if ano is None and len(dados.get("anos") or []) == 1:
            ano = dados["anos"][0]
        if ano is None:
            raise ValueError(f"Votação {v['id']}: sem ano identificável para a exportação")
        por_ano[int(ano)].append(v)
    dic = dicionario_sessoes()
    arquivos = [("dic-ses", dic, {"familia": "dic-ses", "n": len(dic["materias"])})]
    arquivos += [(f"vot-{ano}", fatia_votacoes(modelo, ano, vs), {"familia": "vot", "ano": ano, "n": len(vs)})
                 for ano, vs in sorted(por_ano.items(), reverse=True)]
    (saida / "dados").mkdir(parents=True, exist_ok=True)
    entradas = {}
    for nome, dados_arquivo, meta in arquivos:
        conteudo = json_compacto(dados_arquivo)
        caminho = f"dados/{nome}.json"
        (saida / caminho).write_bytes(conteudo)
        entradas[nome] = {"url": f"{caminho}?v={P.versao_bytes(conteudo)}", "bytes": len(conteudo), **meta}
    manifesto["build_ses"] = versao_documentos(entradas)
    manifesto["arquivos"].update(entradas)
    escrever_manifesto(manifesto, saida)
    return manifesto


# ------------------------------------------------------------------- orçamentos
def cargas_iniciais(saida: Path, manifesto: dict) -> dict[str, tuple[int, int, int]]:
    """(arquivos, bytes brutos, bytes gzip) do JSON que cada página carrega sem filtros."""
    cargas = {}
    for pagina, nomes in P.iniciais_por_pagina(manifesto).items():
        arquivos = [saida / manifesto["arquivos"][n]["url"].split("?")[0] for n in nomes if n in manifesto["arquivos"]]
        conteudos = [a.read_bytes() for a in arquivos if a.is_file()]
        cargas[pagina] = (len(conteudos), sum(len(c) for c in conteudos), sum(len(gzip.compress(c, mtime=0)) for c in conteudos))
    return cargas


def cargas_acima_do_orcamento(saida: Path, manifesto: dict) -> list[str]:
    """Páginas cuja carga inicial passa de LIMITE_INICIAL_GZIP; vazia quando todas cabem."""
    return [f"{pagina}: carga inicial de {comprimido} bytes gzip excede o orçamento de {LIMITE_INICIAL_GZIP} bytes"
            for pagina, (_, _, comprimido) in cargas_iniciais(saida, manifesto).items() if comprimido > LIMITE_INICIAL_GZIP]


def relatorio_tamanhos(saida: Path, manifesto: dict | None = None) -> None:
    """Lista bytes brutos e gzip; os orçamentos valem por arquivo e, na carga inicial, por página."""
    linhas, vereadores, avisos = [], [], []
    grupos = {"dados/doc-*.json": [], "dados/ver/*.json": [], "dados/vot-*.json": []}
    for arq in sorted(saida.rglob("*")):
        if not arq.is_file():
            continue
        nome = arq.relative_to(saida).as_posix()
        conteudo = arq.read_bytes()
        bruto, comprimido = len(conteudo), len(gzip.compress(conteudo, mtime=0))
        parte_doc = (nome.startswith("dados/doc-") or nome.startswith("dados/ver/")) and arq.suffix == ".json"
        parte_vot = nome.startswith("dados/vot-") and arq.suffix == ".json"
        if arq.parent == saida / "vereadores" and arq.suffix == ".html":
            vereadores.append((bruto, comprimido))
        elif parte_doc:
            grupos["dados/ver/*.json" if nome.startswith("dados/ver/") else "dados/doc-*.json"].append((bruto, comprimido))
        elif parte_vot:
            grupos["dados/vot-*.json"].append((bruto, comprimido))
        else:
            linhas.append((nome, bruto, comprimido))
        if arq.suffix == ".html" and comprimido > LIMITE_HTML_GZIP:
            avisos.append(f"{nome}: {comprimido} bytes gzip excedem o orçamento HTML de {LIMITE_HTML_GZIP} bytes")
        if nome in JSON_BUSCADOS and comprimido > LIMITE_JSON_GZIP:
            avisos.append(f"{nome}: {comprimido} bytes gzip excedem o orçamento JSON de {LIMITE_JSON_GZIP} bytes")
        if parte_doc and comprimido > LIMITE_PARTE_DOC_GZIP:
            avisos.append(f"{nome}: {comprimido} bytes gzip excedem o orçamento de parte de documentos de {LIMITE_PARTE_DOC_GZIP} bytes")
        if parte_vot and comprimido > LIMITE_PARTE_VOT_GZIP:
            avisos.append(f"{nome}: {comprimido} bytes gzip excedem o orçamento de parte de votações de {LIMITE_PARTE_VOT_GZIP} bytes")
    if vereadores:
        linhas.append((f"vereadores/*.html (soma de {len(vereadores)})", sum(b for b, _ in vereadores), sum(g for _, g in vereadores)))
        linhas.append(("vereadores/*.html (máximo)", max(b for b, _ in vereadores), max(g for _, g in vereadores)))
    for rotulo, tamanhos in grupos.items():
        if tamanhos:
            linhas.append((f"{rotulo} (soma de {len(tamanhos)})", sum(b for b, _ in tamanhos), sum(g for _, g in tamanhos)))
            linhas.append((f"{rotulo} (máximo)", max(b for b, _ in tamanhos), max(g for _, g in tamanhos)))
    if manifesto:
        for pagina, (n, bruto, comprimido) in cargas_iniciais(saida, manifesto).items():
            linhas.append((f"JSON inicial de {pagina} ({n} arquivos)", bruto, comprimido))
        avisos += cargas_acima_do_orcamento(saida, manifesto)
    largura = max([len("Arquivo"), *(len(nome) for nome, _, _ in linhas)])
    print("\nTamanhos do site (bytes):")
    print(f"{'Arquivo':<{largura}} {'Bruto':>12} {'Gzip':>12}")
    for nome, bruto, comprimido in linhas:
        print(f"{nome:<{largura}} {bruto:>12} {comprimido:>12}")
    for aviso in avisos:
        print(f"::warning::{aviso}", file=sys.stderr)


def carregar_geo(raiz: Path | None = None) -> dict | None:
    """A geometria é opcional; se presente, um arquivo inválido não deve virar mapa enganoso."""
    from coletor.validar import validar_geo

    caminho = (raiz or RAIZ) / "data" / "geo" / "bairros.json"
    if not caminho.exists():
        return None
    geo = json.loads(caminho.read_text(encoding="utf-8"))
    problemas = validar_geo(geo)
    if problemas:
        raise ValueError("; ".join(problemas))
    return geo


def copiar_estaticos(fonte: Path, saida: Path) -> None:
    """Publica a árvore estática sem arquivos ocultos nem documentação Markdown."""
    for arq in sorted(fonte.rglob("*")):
        relativo = arq.relative_to(fonte)
        if not arq.is_file() or not P.publicavel(relativo):
            continue
        destino = saida / relativo
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(P.bytes_estaticos(arq, raiz=fonte))


def gerar_404(modelo: dict) -> str:
    """Links absolutos à raiz publicada funcionam mesmo em URLs inexistentes profundas."""
    prefixo = urlsplit(N.URL_SITE).path
    legislaturas = modelo.get("legislaturas") or []
    atual = legislaturas[-1]["id"] if legislaturas else None
    pessoas = sorted((p for p in modelo.get("pessoas", {}).values() if atual is not None and atual in p["mandatos"]),
                     key=lambda p: P._chave_nome(p["nome"]))
    links = "".join(f'<li><a href="{P.esc(prefixo + "vereadores/" + p["slug"] + ".html")}">{P.esc(p["nome"])}</a></li>'
                    for p in pessoas)
    lista = f'<section><h2>Procure um vereador</h2><ul>{links}</ul></section>' if links else ""
    corpo = (f'<section class="abertura"><h1>Página não encontrada</h1>'
             f'<p>O endereço pode ter mudado ou não existir. <a href="{P.esc(prefixo)}">Volte ao início</a>.</p></section>'
             f'{lista}')
    return P.pagina("Página não encontrada · Radar dos Vereadores de Niterói", corpo, "", prefixo=prefixo,
                    caminho="404.html", indexavel=False)


def main() -> None:
    modelo = montar_modelo()
    modelo["sessoes"] = modelo_sessoes.montar_sessoes(modelo) if (RAIZ / "data" / "sessoes").is_dir() else None
    modelo["geo_bairros"] = carregar_geo()
    modelo["memoria"] = inicio.carregar_memoria(RAIZ)
    # O próprio HTML da memória também recebe o link no rodapé. Reinicia a flag em toda execução.
    P.MEMORIA_PUBLICADA = bool(modelo["memoria"] and modelo["memoria"].get("homenageados"))
    memoria_html = pagina_memoria.gerar_memoria(modelo["memoria"])
    P.MEMORIA_PUBLICADA = memoria_html is not None
    if SAIDA.exists():
        shutil.rmtree(SAIDA)
    (SAIDA / "vereadores").mkdir(parents=True)
    (SAIDA / "dados").mkdir()
    copiar_estaticos(FONTE_ESTATICA, SAIDA)
    escrever = lambda nome, conteudo: (SAIDA / nome).write_text(conteudo, encoding="utf-8")
    if memoria_html is not None:
        escrever("memoria.html", memoria_html)
    cliente = dados_cliente(modelo)
    projetos = json_compacto(cliente)
    (SAIDA / "dados/projetos.json").write_bytes(projetos)
    manifesto = exportar_fatias(modelo, cliente, SAIDA)
    exportar_documentos(modelo, SAIDA, manifesto)
    exportar_sessoes(modelo, SAIDA, manifesto)
    escrever("index.html", P.gerar_index(modelo))
    escrever("leis.html", P.gerar_leis(cliente, manifesto))
    escrever("projetos.html", P.gerar_projetos(cliente, manifesto))
    escrever("atividades.html", P.gerar_atividades(modelo, manifesto))
    sessoes_html = pagina_sessoes.gerar_sessoes(modelo)
    # O renderizador recebe só o modelo; a carga de dados é ligada aqui, sem acoplar a apresentação à exportação.
    if 'id="manifesto-dados"' not in sessoes_html:
        sessoes_html = sessoes_html.replace("</head>", P.cabecalho_dados(manifesto, "sessoes.html", "") + "\n</head>", 1)
    escrever("sessoes.html", sessoes_html)
    escrever("ruido.html", P.gerar_ruido(modelo))
    escrever("analises.html", P.gerar_analises(modelo))
    escrever("metodologia.html", P.gerar_metodologia(modelo))
    # Eventos derivados das datas já coletadas; nada é gravado em data/.
    eventos = N.eventos_do_modelo(modelo)
    escrever(N.PAGINA, P.gerar_novidades(eventos))
    (SAIDA / N.FEED).write_bytes(N.gerar_rss(eventos).encode("utf-8"))  # bytes: LF em qualquer sistema
    escrever("alertas.html", P.redirecionar("ruido.html"))
    escrever("404.html", gerar_404(modelo))
    for pessoa in modelo["pessoas"].values():
        escrever(f"vereadores/{pessoa['slug']}.html", P.gerar_vereador(modelo, pessoa))
    resumo = {
        leg["id"]: {
            p["nome"]: {"partido": p["mandatos"][leg["id"]]["partido"], "eleito": p["mandatos"][leg["id"]]["eleito"], **p["mandatos"][leg["id"]]["metricas"]}
            for p in modelo["pessoas"].values() if leg["id"] in p["mandatos"]
        }
        for leg in modelo["legislaturas"]
    }
    escrever("dados/vereadores.json", json.dumps(resumo, ensure_ascii=False, indent=1))
    escrever(".nojekyll", "")
    print(f"site gerado: {len(modelo['pessoas'])} vereadores, {len(modelo['projetos'])} projetos, "
          f"{len(modelo.get('documentos') or [])} documentos")
    relatorio_tamanhos(SAIDA, manifesto)


if __name__ == "__main__":
    main()
