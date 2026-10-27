"""Verificação semanal da composição da Câmara, sem alterar arquivos.

Lê só os dados versionados (data/ e config/) e aponta, para revisão humana:
  (a) autores com papel de vereador em PLs e documentos da legislatura atual que
      não estão entre os eleitos dela nem em config/perfis.json: possível suplente
      em exercício;
  (b) eleitos com licença registrada na frequência das sessões do ano atual, pelas
      regras de coletor.regras_sessoes, sem entrada em "afastamentos": possível
      licença ou afastamento;
  (c) com --com-rede, partidos publicados no site da Câmara diferentes dos perfis.
      Site fora do ar ou com estrutura não reconhecida só é informado.
Grava um relatório em Markdown e termina sempre com código 0.

Uso: python -m coletor.vereadores_semanal [--saida relatorio.md] [--com-rede]
Somente biblioteca padrão do Python.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import http.client
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from coletor.regras_sessoes import presencas_da_sessao
from coletor.siscam import BASE, DETALHE, USER_AGENT
from coletor.site.modelo import e_autor_vereador_doc, e_vereador, legislatura_de, slug
from coletor.tse import normalizar, normalizar_partido, variantes

RAIZ = Path(__file__).resolve().parent.parent
URL_CAMARA = "https://www.camaraniteroi.rj.gov.br/site/vereadores/"
DETALHE_SESSAO = BASE + "/DetalhesSessao.aspx?IdDocumento={id}"  # como coletor.sessoes.DETALHE_SESSAO
TIMEOUT_CAMARA = 30
MAX_BYTES_CAMARA = 4 << 20
MINIMO_CAMARA = 10  # pares nome–partido para considerar a estrutura reconhecida
EXEMPLOS = 3
SESSOES_LISTADAS = 5
MARCADOR = "<!-- achados: {n} -->"
SEM_DIFERENCAS = "Sem diferenças em relação à configuração."

ROTULOS_TIPO = {
    "requerimento": "Requerimento",
    "indicacao": "Indicação",
    "mocao": "Moção",
    "pdl": "PDL",
    "resolucao": "Projeto de resolução",
}
PARTIDOS_COMUNS = (
    "PT", "PL", "PSOL", "PDT", "MDB", "PSD", "PSDB", "PP", "PV", "PCdoB", "PC do B", "Cidadania",
    "Republicanos", "Podemos", "PODE", "União Brasil", "UNIÃO", "Solidariedade", "Avante", "NOVO",
    "PSB", "REDE", "DC", "AGIR", "MOBILIZA", "PRD", "PRTB", "PMB", "PCO", "PSTU", "UP", "PCB",
    "DEM", "PTB", "PROS", "PATRIOTA", "PSC", "PTC", "PMN",
)


# ---- leitura ---------------------------------------------------------------------
def _ler_json(caminho: Path, padrao: Any = None) -> Any:
    if not caminho.exists():
        return padrao
    return json.loads(caminho.read_text(encoding="utf-8"))


def _md(texto: Any) -> str:
    """Escapa os caracteres que mudariam a formatação do Markdown."""
    return re.sub(r"([\\`*_\[\]<>|])", r"\\\1", str(texto or ""))


def _data_br(iso: str | None) -> str:
    if iso and re.fullmatch(r"\d{4}-\d{2}-\d{2}", iso):
        return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}"
    return "sem data"


def _ano_arquivo(arquivo: Path) -> int | None:
    return int(arquivo.stem) if re.fullmatch(r"\d{4}", arquivo.stem) else None


def legislatura_atual(cfg: dict, hoje: dt.date) -> dict | None:
    legs = [leg for leg in cfg.get("legislaturas") or [] if leg.get("id") and leg.get("inicio")]
    iso = hoje.isoformat()
    for leg in legs:
        if leg["inicio"] <= iso <= (leg.get("fim") or "9999-12-31"):
            return leg
    return max(legs, key=lambda leg: leg["inicio"], default=None)


def _anos_legislatura(leg: dict) -> range:
    inicio = int(leg["inicio"][:4])
    fim = int((leg.get("fim") or leg["inicio"])[:4])
    return range(inicio, fim + 1)


def _perfis(perfis: dict) -> dict:
    vereadores = perfis.get("vereadores") if isinstance(perfis, dict) else None
    if not isinstance(vereadores, dict):
        return {}
    return {k: v for k, v in vereadores.items() if not k.startswith("_")}


# ---- (a) autores fora da composição -----------------------------------------------
def autores_fora_da_composicao(raiz: Path, cfg: dict, perfis: dict, leg: dict) -> list[dict]:
    """Autores vereadores na legislatura que não são eleitos dela nem têm perfil."""
    legs = cfg.get("legislaturas") or []
    nao_vereador = cfg.get("nao_vereador") or []
    conhecidos = {slug(e["siscam"]) for e in leg.get("eleitos") or [] if e.get("siscam")}
    conhecidos |= {slug(nome) for nome in _perfis(perfis)}
    anos = _anos_legislatura(leg)
    achados: dict[str, dict] = {}

    def registrar(nome: str, data: str | None, rotulo: str, url: str | None) -> None:
        chave = slug(nome)
        if not chave or chave in conhecidos:
            return
        achado = achados.setdefault(chave, {"nome": nome, "total": 0, "exemplos": []})
        achado["nome"] = min(achado["nome"], nome)
        achado["total"] += 1
        achado["exemplos"].append((data or "", rotulo, url or ""))

    for arquivo in sorted((raiz / "data" / "proposicoes").glob("*.json")):
        if _ano_arquivo(arquivo) not in anos:
            continue
        for pl in json.loads(arquivo.read_text(encoding="utf-8")):
            if legislatura_de(pl.get("data"), pl.get("ano") or 0, legs) != leg["id"]:
                continue
            for autor in pl.get("autoria") or []:
                if autor.get("nome") and e_vereador(autor, nao_vereador):
                    url = DETALHE.format(doc=pl["id"]) if pl.get("id") else None
                    registrar(autor["nome"], pl.get("data"), f"PL {pl.get('numero') or ''}".strip(), url)
    for arquivo in sorted((raiz / "data" / "documentos").glob("*/*.json")):
        if _ano_arquivo(arquivo) not in anos:
            continue
        tipo = arquivo.parent.name
        for doc in json.loads(arquivo.read_text(encoding="utf-8")):
            if legislatura_de(doc.get("data"), doc.get("ano") or 0, legs) != leg["id"]:
                continue
            for autor in doc.get("autoria") or doc.get("autores") or []:
                if autor.get("nome") and e_autor_vereador_doc(autor, nao_vereador):
                    url = doc.get("url") or (DETALHE.format(doc=doc["id"]) if doc.get("id") else None)
                    rotulo = f"{ROTULOS_TIPO.get(tipo, tipo)} {doc.get('numero') or ''}".strip()
                    registrar(autor["nome"], doc.get("data"), rotulo, url)

    eleitos_antes = {slug(e["siscam"]): outra["id"] for outra in legs if outra.get("id") != leg["id"]
                     for e in outra.get("eleitos") or [] if e.get("siscam")}
    apelidos = {slug(n) for n in cfg.get("apelidos") or {} if not n.startswith("_")}
    saida = []
    for chave, achado in achados.items():
        exemplos = sorted(achado["exemplos"], key=lambda e: (e[0], e[1], e[2]), reverse=True)[:EXEMPLOS]
        notas = []
        if chave in eleitos_antes:
            notas.append(f"eleito na legislatura {eleitos_antes[chave]}")
        if chave in apelidos:
            notas.append("tem apelido em `config/vereadores.json`")
        saida.append({"nome": achado["nome"], "total": achado["total"], "exemplos": exemplos, "notas": notas})
    return sorted(saida, key=lambda a: (-a["total"], a["nome"]))


# ---- (b) licenças sem afastamento --------------------------------------------------
def licencas_sem_afastamento(raiz: Path, cfg: dict, leg: dict, ano: int) -> list[dict]:
    """Eleitos com licença na frequência das sessões do ano, sem registro de afastamento."""
    legs = cfg.get("legislaturas") or []
    eleitos = {slug(e["siscam"]): e for e in leg.get("eleitos") or [] if e.get("siscam")}
    afastados = {slug(a.get("siscam") or "") for a in cfg.get("afastamentos") or [] if a.get("legislatura") == leg["id"]}
    sessoes = _ler_json(raiz / "data" / "sessoes" / f"{ano}.json", []) or []
    achados: dict[str, dict] = {}
    ordenadas = sorted(sessoes, key=lambda s: (s.get("data") or "", s.get("hora") or "", str(s.get("id") or "")))
    for sessao in ordenadas:
        if legislatura_de(sessao.get("data"), sessao.get("ano") or ano, legs) != leg["id"]:
            continue
        for chave, registro in presencas_da_sessao(sessao)["pessoas"].items():
            if not registro["licenca"] or chave not in eleitos or chave in afastados:
                continue
            eleito = eleitos[chave]
            achado = achados.setdefault(chave, {"nome": eleito.get("nome") or eleito["siscam"],
                                                "siscam": eleito["siscam"], "sessoes": []})
            url = DETALHE_SESSAO.format(id=sessao["id"]) if sessao.get("id") else None
            achado["sessoes"].append((sessao.get("data"), url))
    return sorted(achados.values(), key=lambda a: a["nome"])


# ---- (c) site da Câmara ------------------------------------------------------------
def partidos_conhecidos(cfg: dict, perfis: dict) -> dict[str, str]:
    """Chave normalizada → grafia do site, a partir de uma lista fixa e da configuração."""
    nomes = list(PARTIDOS_COMUNS)
    nomes += [e.get("partido") for leg in cfg.get("legislaturas") or [] for e in leg.get("eleitos") or []]
    for perfil in _perfis(perfis).values():
        mandatos = perfil.get("mandatos") if isinstance(perfil, dict) else None
        for mandato in (mandatos or {}).values() if isinstance(mandatos, dict) else ():
            if isinstance(mandato, dict):
                nomes.append(mandato.get("partido"))
    saida = {}
    for nome in nomes:
        canonico = normalizar_partido(nome)
        if canonico:
            saida.setdefault(normalizar(nome), canonico)
            saida.setdefault(normalizar(canonico), canonico)
    return saida


def _linhas_texto(corpo: str) -> list[str]:
    sem_codigo = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1\s*>", " ", corpo)
    texto = html.unescape(re.sub(r"(?s)<[^>]+>", "\n", sem_codigo))
    return [" ".join(linha.split()) for linha in texto.splitlines() if linha.strip()]


RE_NOME_PARTIDO = re.compile(r"^(?P<nome>[^()\d|:]{3,60}?)\s*(?:\((?P<p1>[^()]{2,25})\)|\s[-–—|]\s*(?P<p2>[^()\-–—|]{2,25}))$")
RE_ROTULO_PARTIDO = re.compile(r"^partido\s*:?\s*(?P<p>.{2,25})$", re.I)


def _parece_nome(texto: str, partidos: dict[str, str]) -> bool:
    palavras = texto.split()
    if not 1 <= len(palavras) <= 6 or len(texto) > 60 or len(texto) < 3:
        return False
    if normalizar(texto) in partidos or any(c.isdigit() or c in ":|/@" for c in texto):
        return False
    return all(p[:1].isalpha() for p in palavras)


def extrair_vereadores(corpo: str, partidos: dict[str, str]) -> dict[str, str]:
    """Pares nome → partido em "Nome (PARTIDO)", "Nome - PARTIDO" ou nome seguido do partido.

    Só reconhece siglas conhecidas; o chamador exige um mínimo de pares antes de comparar.
    """
    linhas = _linhas_texto(corpo)
    pares: dict[str, str] = {}
    for i, linha in enumerate(linhas):
        m = RE_NOME_PARTIDO.match(linha)
        if m:
            nome = m["nome"].strip()
            partido = partidos.get(normalizar(m["p1"] or m["p2"]))
            if partido and _parece_nome(nome, partidos):
                pares.setdefault(nome, partido)
                continue
        if i + 1 < len(linhas) and _parece_nome(linha, partidos):
            seguinte = linhas[i + 1]
            rotulo = RE_ROTULO_PARTIDO.match(seguinte)
            partido = partidos.get(normalizar(rotulo["p"] if rotulo else seguinte))
            if partido:
                pares.setdefault(linha, partido)
    return pares


def _indice_nomes(leg: dict) -> dict[str, str]:
    """Nome de exibição, nome do SISCAM e nome sem apelido → nome do SISCAM."""
    indice = {}
    for eleito in leg.get("eleitos") or []:
        siscam = eleito.get("siscam")
        if not siscam:
            continue
        for chave in [normalizar(eleito.get("nome")), *variantes(siscam)]:
            if chave:
                indice.setdefault(chave, siscam)
    return indice


def _partido_perfil(siscam: str, cfg_leg: dict, perfis: dict) -> str | None:
    perfil = _perfis(perfis).get(siscam)
    mandato = ((perfil or {}).get("mandatos") or {}).get(cfg_leg["id"]) if isinstance(perfil, dict) else None
    if isinstance(mandato, dict) and mandato.get("partido"):
        return mandato["partido"]
    return next((e.get("partido") for e in cfg_leg.get("eleitos") or [] if e.get("siscam") == siscam), None)


def verificar_camara(cfg: dict, perfis: dict, leg: dict) -> dict:
    """Compara partidos do site da Câmara com os perfis; nunca levanta exceção de rede."""
    try:
        req = urllib.request.Request(URL_CAMARA, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT_CAMARA) as resposta:
            charset = resposta.headers.get_content_charset() or "utf-8"
            corpo = resposta.read(MAX_BYTES_CAMARA).decode(charset, "replace")
    except urllib.error.HTTPError as e:
        return {"estado": "indisponivel", "motivo": f"HTTP {e.code}"}
    except (OSError, http.client.HTTPException, ValueError, LookupError) as e:
        return {"estado": "indisponivel", "motivo": type(e).__name__}
    partidos = partidos_conhecidos(cfg, perfis)
    pares = extrair_vereadores(corpo, partidos)
    if len(pares) < MINIMO_CAMARA:
        return {"estado": "estrutura_desconhecida", "pares": len(pares)}
    indice = _indice_nomes(leg)
    diferencas, sem_correspondencia, conferidos = [], [], 0
    for nome_site, partido_site in sorted(pares.items()):
        siscam = indice.get(normalizar(nome_site))
        if siscam is None:
            sem_correspondencia.append(nome_site)
            continue
        conferidos += 1
        registrado = _partido_perfil(siscam, leg, perfis)
        if normalizar(normalizar_partido(registrado)) != normalizar(partido_site):
            diferencas.append({"nome": nome_site, "siscam": siscam, "site": partido_site, "perfil": registrado})
    return {"estado": "ok", "diferencas": diferencas, "sem_correspondencia": sem_correspondencia,
            "conferidos": conferidos}


# ---- relatório ---------------------------------------------------------------------
def montar_relatorio(hoje: dt.date, leg: dict, ano: int, suplentes: list[dict],
                     licencas: list[dict], camara: dict) -> tuple[str, int]:
    diferencas = camara.get("diferencas") or []
    achados = len(suplentes) + len(licencas) + len(diferencas)
    linhas = [
        "# Verificação semanal dos vereadores",
        "",
        f"Gerada em {hoje:%d/%m/%Y} com os dados versionados de `data/` e `config/` (legislatura {leg['id']}).",
        "Cada item é uma pista para conferência humana: confira a fonte antes de alterar a configuração.",
        "",
        "## Possíveis suplentes em exercício",
        "",
    ]
    if suplentes:
        linhas.append("Autores com papel de vereador na legislatura, fora dos eleitos dela e sem perfil em `config/perfis.json`:")
        linhas.append("")
        for s in suplentes:
            exemplos = ", ".join(f"[{_md(r)}]({u}) ({_data_br(d)})" if u else f"{_md(r)} ({_data_br(d)})"
                                 for d, r, u in s["exemplos"])
            notas = f" Observação: {'; '.join(s['notas'])}." if s["notas"] else ""
            linhas.append(f"- **{_md(s['nome'])}**: {s['total']} proposição(ões) como autor. Exemplos: {exemplos}.{notas}")
    else:
        linhas.append("Nenhum autor novo.")
    linhas += ["", "## Possíveis licenças ou afastamentos sem registro", ""]
    if licencas:
        linhas.append(f"Eleitos com licença na frequência das sessões de {ano}, sem entrada em `afastamentos` de `config/vereadores.json`:")
        linhas.append("")
        for item in licencas:
            sessoes = item["sessoes"]
            links = ", ".join(f"[{_data_br(d)}]({u})" if u else _data_br(d) for d, u in sessoes[-SESSOES_LISTADAS:])
            linhas.append(f"- **{_md(item['nome'])}** (`{item['siscam']}`): licença em {len(sessoes)} sessão(ões) deliberativa(s). "
                          f"Mais recentes: {links}.")
    else:
        linhas.append(f"Nenhuma licença sem registro nas sessões de {ano}.")
    linhas += ["", "## Partidos no site da Câmara", ""]
    estado = camara.get("estado")
    fonte = f"[site da Câmara]({URL_CAMARA})"
    if estado == "nao_verificado":
        linhas.append("Não verificado nesta execução (use `--com-rede`).")
    elif estado == "indisponivel":
        linhas.append(f"O {fonte} está indisponível ({_md(camara.get('motivo'))}); partidos não conferidos.")
    elif estado == "estrutura_desconhecida":
        linhas.append(f"Estrutura do {fonte} desconhecida ({camara.get('pares', 0)} par(es) nome–partido reconhecidos, "
                      f"mínimo de {MINIMO_CAMARA}); partidos não conferidos.")
    else:
        if diferencas:
            linhas.append(f"Partido no {fonte} diferente do registrado para a legislatura {leg['id']}:")
            linhas.append("")
            for d in diferencas:
                linhas.append(f"- **{_md(d['nome'])}** (`{d['siscam']}`): site informa **{_md(d['site'])}**; "
                              f"perfil/configuração informa **{_md(d['perfil'] or 'sem partido')}**.")
        else:
            linhas.append(f"{camara.get('conferidos', 0)} vereador(es) conferido(s) no {fonte}, sem diferença de partido.")
        if camara.get("sem_correspondencia"):
            linhas.append("")
            linhas.append("Nomes do site sem correspondência entre os eleitos (informativo): "
                          + ", ".join(_md(n) for n in camara["sem_correspondencia"]) + ".")
    linhas += ["", SEM_DIFERENCAS if achados == 0 else f"Total: {achados} achado(s) para revisão.", MARCADOR.format(n=achados)]
    return "\n".join(linhas) + "\n", achados


def gerar(raiz: Path, hoje: dt.date, com_rede: bool = False) -> tuple[str, int]:
    """Relatório e número de achados, lendo os arquivos de raiz."""
    cfg = _ler_json(raiz / "config" / "vereadores.json")
    if not isinstance(cfg, dict):
        raise ValueError("config/vereadores.json ausente ou inválido")
    perfis = _ler_json(raiz / "config" / "perfis.json", {}) or {}
    leg = legislatura_atual(cfg, hoje)
    if leg is None:
        raise ValueError("nenhuma legislatura com id e início em config/vereadores.json")
    suplentes = autores_fora_da_composicao(raiz, cfg, perfis, leg)
    licencas = licencas_sem_afastamento(raiz, cfg, leg, hoje.year)
    camara = verificar_camara(cfg, perfis, leg) if com_rede else {"estado": "nao_verificado"}
    return montar_relatorio(hoje, leg, hoje.year, suplentes, licencas, camara)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--saida", help="arquivo Markdown do relatório (padrão: imprime na saída)")
    ap.add_argument("--com-rede", action="store_true", help="confere os partidos no site da Câmara")
    ap.add_argument("--raiz", default=str(RAIZ), help=argparse.SUPPRESS)
    ap.add_argument("--hoje", type=dt.date.fromisoformat, default=None, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    hoje = args.hoje or dt.date.today()
    try:
        texto, achados = gerar(Path(args.raiz), hoje, args.com_rede)
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"::warning::verificação semanal incompleta: {e}", file=sys.stderr)
        texto = (f"# Verificação semanal dos vereadores\n\nNão foi possível ler os dados versionados: {_md(e)}\n\n"
                 + MARCADOR.format(n=0) + "\n")
        achados = 0
    if args.saida:
        Path(args.saida).write_text(texto, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(texto)
    print("sem diferenças" if achados == 0 else f"{achados} achado(s) para revisão")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
