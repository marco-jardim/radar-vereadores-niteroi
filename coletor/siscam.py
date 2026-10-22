"""Coletor de projetos de lei do SISCAM da Câmara Municipal de Niterói.

Baixa a listagem de Projetos de Lei de cada ano (2021 em diante) e, para cada
projeto novo ou com tramitação alterada, a página de detalhe com autoria e
tramitação completa. Grava um JSON por ano em data/proposicoes/.

Uso: python -m coletor.siscam [--anos 2021-2026] [--forcar] [--workers 4]
Somente biblioteca padrão do Python.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BASE = "https://consultaniteroi.siscam.com.br"
LISTAGEM = BASE + "/ResultadoPropositura.aspx?Tipo=4&Exibir=1,2,3,4,6,7,8&Ano={ano}&pagina={pagina}"
DETALHE = BASE + "/DetalhesDocumentos.aspx?IdDocumento={doc}"
USER_AGENT = os.environ.get(
    "COLETOR_USER_AGENT",
    "radar-vereadores-niteroi/1.0 (+https://github.com/marco-jardim/radar-vereadores-niteroi)",
)
RAIZ = Path(__file__).resolve().parent.parent
DIR_DADOS = RAIZ / "data" / "proposicoes"
ANO_INICIAL = 2021


# --------------------------------------------------------------------------- HTTP
def baixar(url: str, tentativas: int = 5) -> str:
    erro = None
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read().decode("utf-8", "ignore")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            erro = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"falha ao baixar {url}: {erro}")


# --------------------------------------------------------------------- utilidades
def limpar(fragmento: str) -> str:
    texto = re.sub(r"<[^>]+>", " ", fragmento)
    return re.sub(r"\s+", " ", html.unescape(texto)).strip()


def data_iso(texto: str) -> str | None:
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", texto or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def campo(padrao: str, texto: str) -> str:
    m = re.search(padrao, texto, re.S)
    return limpar(m.group(1)) if m else ""


# ----------------------------------------------------------------------- listagem
def parse_listagem(pagina_html: str) -> list[dict]:
    """Extrai os registros resumidos de uma página de listagem."""
    itens = []
    for bloco in pagina_html.split('class="tabela-simples"')[1:]:
        m = re.search(r'IdDocumento=(\d+)"[^>]*>Projeto de Lei Nº (\d+)/(\d{4})', bloco)
        if not m:
            continue
        doc, numero, ano = m.groups()
        cabecalho = bloco.split("trTramitacoes")[0]
        ntram = re.search(r"Última Tramitac[^(]*\((\d+)\)", bloco)
        itens.append(
            {
                "id": int(doc),
                "numero": f"{int(numero)}/{ano}",
                "ano": int(ano),
                "situacao": campo(r"Situação: </strong>([^<]*)", bloco),
                "autor_ids": [
                    (int(a), html.unescape(n).strip())
                    for a, n in re.findall(r"Autor=(\d+)'>([^<]+)</a>", cabecalho)
                ],
                "n_tramitacoes": int(ntram.group(1)) if ntram else 0,
            }
        )
    return itens


def total_registros(pagina_html: str) -> int:
    m = re.search(r"Projeto de Lei</h3>\s*\(<span class='total-item'><strong>(\d+) registro", pagina_html)
    return int(m.group(1)) if m else 0


FAIXA = 400  # o SISCAM só pagina até a página 50 (500 registros); listamos por faixas de número


def listar_faixa(ano: int, ini: int, fim: int, workers: int) -> tuple[list[dict], int]:
    url = LISTAGEM + f"&NumeroInicial={ini}&NumeroFinal={fim}"
    primeira = baixar(url.format(ano=ano, pagina=1))
    total = total_registros(primeira)
    paginas = (total + 9) // 10
    itens = parse_listagem(primeira)
    if paginas > 1:
        with ThreadPoolExecutor(workers) as ex:
            futuros = [ex.submit(baixar, url.format(ano=ano, pagina=p)) for p in range(2, paginas + 1)]
            for f in as_completed(futuros):
                itens.extend(parse_listagem(f.result()))
    return itens, total


def listar_ano(ano: int, workers: int) -> list[dict]:
    itens, esperado, ini = [], 0, 1
    while True:
        lote, total = listar_faixa(ano, ini, ini + FAIXA - 1, workers)
        if total == 0:
            break
        itens.extend(lote)
        esperado += total
        ini += FAIXA
    unicos = {i["id"]: i for i in itens}
    if len(unicos) < esperado:
        print(f"  aviso: {ano} listou {len(unicos)} de {esperado} registros", file=sys.stderr)
    return list(unicos.values())


# ------------------------------------------------------------------------ detalhe
def parse_detalhe(pagina_html: str) -> dict:
    texto_cab = pagina_html.split('id="trArquivos"')[0]
    detalhe = {
        "data": data_iso(campo(r"Data do Documento:\s*</strong>(.*?)</", texto_cab)),
        "assunto": campo(r"Assunto:\s*</strong>(.*?)</", texto_cab),
        "situacao": campo(r"Situação:\s*</strong>(.*?)</", texto_cab),
        "processo": campo(r"Processo:\s*</strong>(.*?)</", texto_cab),
        "ementa": campo(r"Ementa:\s*</strong>(.*?)</td>", texto_cab),
        "protocolo": campo(r"Protocolo:\s*</strong>(.*?)</", texto_cab),
        "data_protocolo": data_iso(campo(r"Data do Protocolo:\s*</strong>(.*?)</", texto_cab)),
        "autoria": [],
        "tramitacoes": [],
    }
    grade = re.search(r'id="autores_grdMembros"(.*?)</table>', pagina_html, re.S)
    if grade:
        for linha in re.findall(r"<tr[^>]*>(.*?)</tr>", grade.group(1), re.S):
            celulas = [limpar(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", linha, re.S)]
            if len(celulas) >= 3 and celulas[0]:
                detalhe["autoria"].append({"nome": celulas[0], "origem": celulas[1], "papel": celulas[2]})

    trams = pagina_html.split('id="tramitacoes_gvTramitacoes"')
    if len(trams) > 1:
        corpo = trams[1].split('id="trParecer"')[0]
        for bloco in re.split(r"<strong>Sequência: </strong>", corpo)[1:]:
            seq = re.match(r"\s*(\d+)", bloco)
            detalhe["tramitacoes"].append(
                {
                    "seq": int(seq.group(1)) if seq else None,
                    "remetente": campo(r"Remetente: </strong>(.*?)</td>", bloco),
                    "destinatario": campo(r"Destinatário: </strong>(.*?)</td>", bloco),
                    "objetivo": campo(r"Objetivo: </strong>(.*?)</td>", bloco),
                    "enviado": data_iso(campo(r"Enviado em: </strong>(.*?)</td>", bloco)),
                    "complemento": campo(r"Complemento: </strong>(.*?)</td>", bloco),
                    "resultado": campo(r"Resultado: </strong>(.*?)</td>", bloco),
                    "data_resposta": data_iso(campo(r"Data Resposta: </strong>(.*?)</td>", bloco)),
                    "observacao": campo(r"Observação: </strong>(.*?)</td>", bloco),
                }
            )
    return detalhe


# ------------------------------------------------------------------- derivações
# "LEI MUNICIPAL Nº 4137/2026", mas não "PROJETO DE LEI Nº 124/2026"
RE_LEI = re.compile(r"(?<!PROJETO DE )(?<!PROJETO DE  )\bLEI\s+(?:MUN[A-Z]*\s+)?N[º°o.]*\s*\.?\s*(\d[\d.]{2,})", re.I)


def _numero_lei(texto: str) -> int | None:
    for m in RE_LEI.finditer(texto or ""):
        n = int(m.group(1).replace(".", ""))
        if n >= 3000:  # leis de Niterói no período estão na faixa 3.6xx–4.xxx
            return n
    return None


def derivar_lei(trams: list[dict]) -> dict | None:
    """Encontra a sanção/promulgação e o número da lei na tramitação."""
    escolhido = None
    for t in trams:  # 1º: passo cujo resultado é sanção/promulgação
        if re.search(r"Promulgad|Sancionad|Promulgação", t.get("resultado", ""), re.I):
            escolhido = t
            break
    if escolhido is None:  # 2º: observação que cita o número da lei
        for t in trams:
            if _numero_lei(t.get("observacao", "") + " " + t.get("complemento", "")):
                escolhido = t
                break
    if escolhido is None:
        return None
    texto_total = " ".join(" ".join([t.get("resultado", ""), t.get("observacao", "")]) for t in trams)
    texto = " ".join([escolhido.get("resultado", ""), escolhido.get("observacao", ""), escolhido.get("complemento", "")])
    numero = _numero_lei(texto)
    # corrigendas publicadas depois: "ONDE SE LÊ: LEI Nº 3958/2024, LEIA-SE: LEI Nº 3959/2024"
    for t in trams:
        m = re.search(r"LEIA-SE:?\s*(.*)", t.get("observacao", ""), re.I)
        if m and _numero_lei(m.group(1)):
            numero = _numero_lei(m.group(1))
    tipo = "sancionada"
    if re.search(r"veto\s+(foi\s+)?(rejeitad|derrubad)|derrubad[ao] o veto", texto_total, re.I):
        tipo = "veto_derrubado"
    elif re.search(r"promulgad[ao]\s+pel[ao]\s+(c[âa]mara|presidente|cmn)", texto, re.I):
        tipo = "promulgada_camara"
    return {
        "numero": numero,
        "data": escolhido.get("data_resposta") or escolhido.get("enviado"),
        "tipo": tipo,
        "veto_parcial": bool(re.search(r"veto(s)?\s+(parcia|aos?\s+art)", texto_total, re.I)),
    }


SITUACOES_LEI = {"PUBLICADO", "PROMULGADO PELA CMN", "VETO PARCIAL", "VETO REJEITADO", "REVOGADO"}


def derivar_desfecho(p: dict) -> str:
    s = (p.get("situacao") or "").upper()
    trams = p.get("tramitacoes", [])
    texto = " ".join((t.get("resultado", "") + " " + t.get("observacao", "")) for t in trams).upper()
    if p.get("lei") or s in SITUACOES_LEI:
        return "virou_lei"
    if s in {"VETO MANTIDO", "VETO TOTAL"} or "VETO TOTAL" in texto:
        return "vetado"
    if s in {"REJEITADO", "REJEITADA"} or "REJEITADO EM" in texto:
        return "rejeitado"
    if s in {"AGUARDANDO SANÇÃO", "APROVADO", "VOTADO"}:
        return "aprovado_aguardando_sancao"
    if s in {"RETIRADO", "RETIRADA", "CANCELADO"}:
        return "retirado"
    if s == "PARECER CONTRÁRIO":
        return "parecer_contrario"
    if s == "ARQUIVADO":
        return "arquivado"
    if s == "APENSADO":
        return "apensado"
    return "em_tramitacao"


# ------------------------------------------------------------------- persistência
def carregar_ano(ano: int) -> dict[int, dict]:
    arq = DIR_DADOS / f"{ano}.json"
    if not arq.exists():
        return {}
    return {p["id"]: p for p in json.loads(arq.read_text(encoding="utf-8"))}


def salvar_ano(ano: int, registros: dict[int, dict]) -> None:
    DIR_DADOS.mkdir(parents=True, exist_ok=True)
    lista = sorted(registros.values(), key=lambda p: (p["ano"], int(p["numero"].split("/")[0])))
    (DIR_DADOS / f"{ano}.json").write_text(
        json.dumps(lista, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )


def precisa_detalhe(anterior: dict | None, resumo: dict, forcar: bool) -> bool:
    if forcar or anterior is None or not anterior.get("tramitacoes") and resumo["n_tramitacoes"]:
        return True
    return (
        anterior.get("n_tramitacoes") != resumo["n_tramitacoes"]
        or anterior.get("situacao") != resumo["situacao"]
    )


def montar_registro(resumo: dict, detalhe: dict) -> dict:
    ids_por_nome = {n.upper(): i for i, n in resumo["autor_ids"]}
    autoria = []
    for a in detalhe["autoria"]:
        autoria.append({**a, "id": ids_por_nome.get(a["nome"].upper())})
    # autores que aparecem na listagem mas não na grade do detalhe
    nomes_detalhe = {a["nome"].upper() for a in autoria}
    for i, n in resumo["autor_ids"]:
        if n.upper() not in nomes_detalhe:
            autoria.append({"id": i, "nome": n, "origem": "", "papel": "Autor" if not autoria else "Co-Autor"})
    reg = {
        "id": resumo["id"],
        "numero": resumo["numero"],
        "ano": resumo["ano"],
        "n_tramitacoes": resumo["n_tramitacoes"],
        **{k: v for k, v in detalhe.items() if k != "autoria"},
        "situacao": resumo["situacao"] or detalhe["situacao"],
        "autoria": autoria,
        "url": DETALHE.format(doc=resumo["id"]),
    }
    reg["lei"] = derivar_lei(reg["tramitacoes"])
    reg["desfecho"] = derivar_desfecho(reg)
    return reg


def coletar(anos: list[int], forcar: bool, workers: int) -> dict:
    estat = {"anos": {}, "detalhes_baixados": 0, "falhas": 0}
    for ano in anos:
        t0 = time.time()
        anteriores = carregar_ano(ano)
        resumos = listar_ano(ano, workers)
        pendentes = [r for r in resumos if precisa_detalhe(anteriores.get(r["id"]), r, forcar)]
        print(f"{ano}: {len(resumos)} projetos, {len(pendentes)} para atualizar", flush=True)
        registros = dict(anteriores)
        # atualiza situação/contagem dos que não precisam de detalhe
        for r in resumos:
            if r["id"] in registros and r not in pendentes:
                registros[r["id"]]["situacao"] = r["situacao"]

        def trabalho(resumo):
            return resumo, parse_detalhe(baixar(DETALHE.format(doc=resumo["id"])))

        with ThreadPoolExecutor(workers) as ex:
            futuros = [ex.submit(trabalho, r) for r in pendentes]
            for i, f in enumerate(as_completed(futuros), 1):
                try:
                    resumo, detalhe = f.result()
                    registros[resumo["id"]] = montar_registro(resumo, detalhe)
                    estat["detalhes_baixados"] += 1
                except Exception as e:  # mantém o dado anterior se falhar
                    estat["falhas"] += 1
                    print(f"  falha: {e}", file=sys.stderr)
                if i % 100 == 0:
                    print(f"  {i}/{len(pendentes)}", flush=True)
                    salvar_ano(ano, registros)
        for reg in registros.values():  # regras de derivação podem mudar; recalcula sem rebaixar
            reg["lei"] = derivar_lei(reg.get("tramitacoes", []))
            reg["desfecho"] = derivar_desfecho(reg)
        salvar_ano(ano, registros)
        estat["anos"][ano] = {"total": len(resumos), "atualizados": len(pendentes), "segundos": round(time.time() - t0)}
    return estat


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    hoje = dt.date.today().year
    ap.add_argument("--anos", default=f"{ANO_INICIAL}-{hoje}")
    ap.add_argument("--forcar", action="store_true", help="rebaixa todos os detalhes")
    ap.add_argument("--workers", type=int, default=int(os.environ.get("COLETOR_WORKERS", 4)))
    args = ap.parse_args()
    ini, _, fim = args.anos.partition("-")
    anos = list(range(int(ini), int(fim or ini) + 1))
    estat = coletar(anos, args.forcar, args.workers)
    meta = RAIZ / "data" / "meta.json"
    dados_meta = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
    dados_meta["coleta"] = {"em": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), **estat}
    meta.write_text(json.dumps(dados_meta, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps(estat, ensure_ascii=False, default=str))
    if estat["falhas"] and estat["detalhes_baixados"] == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
