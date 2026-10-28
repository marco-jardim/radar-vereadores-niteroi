"""Estado desejado da nuvem, lido só do Git (contrato `docs/contratos/textos.md`).

Conserva texto completo e intervalos dos trechos para a barreira de PII não perder
rótulos/contexto nos cortes; cada arquivo é varrido uma única vez.

Fontes: os registros de `data/proposicoes/`, `data/documentos/<tipo>/` e
`data/sessoes/`, `config/vereadores.json`, `config/perfis.json`,
`config/remocoes.json`, os manifestos `data/textos/manifesto-<ano>.json` e a árvore
`dados-textos` (`textos/…/*.txt` e `trechos/<tipo>/<ano>.jsonl`). Não depende de
`coletor.textos`: lê os arquivos no formato do contrato e confere `sha256_texto`, a
quantidade de trechos e o `sha256` de cada trecho (texto = `conteudo[:-1]`, depois
`[inicio:fim]`). Qualquer divergência é `ErroFonte`, antes de qualquer escrita.
"""
from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from coletor import mascara, remocoes
from coletor.nuvem.r2 import chave_r2
from coletor.site.modelo import (URL_DETALHE, carregar_perfis, e_autor_vereador_doc, indice_pessoas,
                                 legislatura_de, nome_curto, partido_perfil, perfis_por_slug, slug)

TIPOS_DOCUMENTOS = ("requerimento", "indicacao", "mocao", "pdl", "resolucao")
TIPOS_EMENTA_VETOR = ("indicacao", "mocao")
URL_SESSAO = "https://consultaniteroi.siscam.com.br/DetalhesSessao.aspx?IdDocumento={id}"


class ErroFonte(RuntimeError):
    """Git inconsistente com o contrato; nada é gravado."""


@dataclass
class Trecho:
    id: str
    documento: str
    arquivo: str
    posicao: int
    texto: str
    sha256: str
    vetorizavel: bool
    tipo: str
    ano: int
    inicio: int
    fim: int


@dataclass
class Original:
    sha256: str
    chave_r2: str
    formato: str | None
    arquivos: set[str] = field(default_factory=set)
    documentos: set[str] = field(default_factory=set)


@dataclass
class Fonte:
    linhas: dict[str, dict[tuple, tuple]]
    trechos: dict[str, Trecho]
    vetores: dict[str, tuple[str, dict, str]]  # id -> (sha256 do texto, metadados, texto)
    ementas: dict[str, str]  # documento -> ementa mascarada
    originais: dict[str, Original]
    remover_r2: set[str]
    sha256_manifestos: str
    avisos: list[str] = field(default_factory=list)
    textos_arquivos: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------- utilidades
def sha256(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


def normalizar_busca(texto: str) -> str:
    """Forma da busca por palavras: NFD, sem marcas Mn, NFC e minúsculas ("Licença" -> "licenca").

    O Worker normaliza a consulta com exatamente
    `s.normalize("NFD").replace(/\\p{Mn}/gu, "").normalize("NFC").toLowerCase()`;
    os pares de `tests/fixtures/contratos/normalizacao.json` valem para as duas implementações.
    """
    decomposto = unicodedata.normalize("NFD", texto)
    return unicodedata.normalize("NFC", "".join(c for c in decomposto if unicodedata.category(c) != "Mn")).lower()


def sha_indexado(sha_texto: str, meta: dict) -> str:
    """`trechos_indexados.sha256`: SHA-256 de (sha256 do texto + metadados em JSON com chaves ordenadas).

    Mudar só os metadados (tipo, ano, legislatura, documento) também reenvia o vetor.
    """
    return sha256((sha_texto + json.dumps(meta, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
                  .encode("utf-8"))


def rowid_fts(id_trecho: str) -> int:
    """rowid do trecho em `trechos_fts`: os 64 bits do id, deslocados para caber num inteiro com sinal."""
    return int(id_trecho, 16) >> 1


def ordem_chave(chave: str) -> tuple:
    """siscam antes de sessao; ids numéricos crescentes (contrato, seção 2.1)."""
    origem, ident = chave.split(":", 1)
    return (0, int(ident), "") if origem == "siscam" else (1, 0, ident)


def _ler_json(caminho: Path) -> Any:
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def _registros(pasta: Path) -> list[dict]:
    saida: list[dict] = []
    for arq in sorted(pasta.glob("*.json")):
        dados = _ler_json(arq)
        if not isinstance(dados, list):
            raise ErroFonte(f"{arq}: esperada uma lista de registros")
        saida.extend(d for d in dados if isinstance(d, dict))
    return saida


# ---------------------------------------------------------------- documentos e pessoas
def _documentos(raiz: Path, liberados) -> tuple[dict, dict, dict, dict]:
    cfg = _ler_json(raiz / "config" / "vereadores.json") or {}
    legs = cfg.get("legislaturas") or []
    nao_vereador = cfg.get("nao_vereador") or []
    apelidos = {k.upper(): v for k, v in (cfg.get("apelidos") or {}).items() if not k.startswith("_")}
    perfis = perfis_por_slug(carregar_perfis(raiz))

    pessoas: dict[str, dict] = {}
    for leg in legs:
        for e in leg.get("eleitos") or []:
            s = slug(e["siscam"])
            p = pessoas.setdefault(s, {"nome_siscam": e["siscam"], "nome": None, "partidos": {}})
            p["nome"] = e.get("nome") or p["nome"]
            if e.get("partido"):
                p["partidos"][leg["id"]] = e["partido"]
    indice = indice_pessoas(pessoas)

    documentos: dict[tuple, tuple] = {}
    ementas: dict[str, str] = {}
    autoria: dict[tuple, tuple] = {}
    mascaradas: dict[str, str] = {}

    def mascarar(texto: str) -> str:
        if texto not in mascaradas:
            mascaradas[texto] = mascara.mascarar(texto, liberados)[0]
        return mascaradas[texto]

    def registrar(ident: str, tipo: str, numero, ano, data, ementa, url, leg, pl) -> bool:
        if (ident,) in documentos:
            return False
        texto = mascarar(str(ementa or ""))
        documentos[(ident,)] = (ident, tipo, None if numero is None else str(numero),
                                ano if isinstance(ano, int) else None, data or None, texto, url, leg, pl)
        ementas[ident] = texto
        return True

    def autores(ident: str, lista, com_papel: bool) -> None:
        for a in lista or []:
            if not isinstance(a, dict):
                continue
            nome = " ".join(str(a.get("nome") or "").split())
            if not nome or not e_autor_vereador_doc({**a, "nome": nome}, nao_vereador):
                continue
            s = indice.get(slug(nome), slug(nome))
            if not s:
                continue
            papel = "coautor" if com_papel and str(a.get("papel") or "").strip().lower().startswith("co") else "autor"
            autoria[(ident, s, papel)] = (ident, s, papel)
            if s not in pessoas:
                pessoas[s] = {"nome_siscam": nome, "nome": apelidos.get(nome.upper()) or nome_curto(nome),
                              "partidos": {}}

    def legislatura(data, ano):
        if not data and not isinstance(ano, int):
            return None
        return legislatura_de(data, ano, legs)

    for p in _registros(raiz / "data" / "proposicoes"):
        ident = f"doc:{p['id']}"
        leg = legislatura(p.get("data") or p.get("data_protocolo"), p.get("ano"))
        if registrar(ident, "pl", p.get("numero"), p.get("ano"), p.get("data"), p.get("ementa"),
                     p.get("url") or URL_DETALHE.format(id=p["id"]), leg, None):
            autores(ident, p.get("autoria"), True)
        for sub in p.get("substitutivos") or []:
            if not isinstance(sub, dict) or not sub.get("id"):
                continue
            sid = f"doc:{sub['id']}"
            # o substitutivo herda ano, ementa e legislatura do PL
            if registrar(sid, "substitutivo", sub.get("numero"), p.get("ano"), sub.get("data"), p.get("ementa"),
                         URL_DETALHE.format(id=sub["id"]), leg, ident):
                autores(sid, sub.get("autoria"), True)
    for tipo in TIPOS_DOCUMENTOS:
        for d in _registros(raiz / "data" / "documentos" / tipo):
            ident = f"doc:{d['id']}"
            if registrar(ident, d.get("tipo") or tipo, d.get("numero"), d.get("ano"), d.get("data"),
                         d.get("ementa"), d.get("url") or URL_DETALHE.format(id=d["id"]),
                         legislatura(d.get("data"), d.get("ano")), None):
                if d.get("autoria"):
                    autores(ident, d["autoria"], True)
                else:
                    autores(ident, d.get("autores"), False)  # listagem: todos contam como autores
    for s in _registros(raiz / "data" / "sessoes"):
        registrar(f"sessao:{s['id']}", "ata", s.get("numero"), s.get("ano"), s.get("data"), s.get("titulo"),
                  s.get("url") or URL_SESSAO.format(id=s["id"]), legislatura(s.get("data"), s.get("ano")), None)

    linhas_pessoas: dict[tuple, tuple] = {}
    for s, p in pessoas.items():
        partido = None
        for leg in reversed(legs):
            partido = p["partidos"].get(leg["id"]) or partido_perfil(perfis, s, leg["id"]) or None
            if partido:
                break
        nome = p["nome"] or apelidos.get(p["nome_siscam"].upper()) or nome_curto(p["nome_siscam"])
        linhas_pessoas[(s,)] = (s, nome, partido)
    return documentos, autoria, linhas_pessoas, ementas


# ---------------------------------------------------------------- manifestos e textos
def _manifestos(raiz: Path) -> tuple[dict[str, tuple[int, dict]], str]:
    pasta = raiz / "data" / "textos"
    arquivos = []
    for arq in pasta.glob("manifesto-*.json"):
        ano = arq.stem.split("-", 1)[1]
        if not ano.isdigit():
            raise ErroFonte(f"{arq.name}: nome de manifesto inválido")
        arquivos.append((int(ano), arq))
    soma = hashlib.sha256()
    entradas: dict[str, tuple[int, dict]] = {}
    for ano, arq in sorted(arquivos):
        dados = arq.read_bytes()
        soma.update(dados)
        for chave, entrada in json.loads(dados.decode("utf-8")).items():
            if chave in entradas:
                raise ErroFonte(f"{chave} em mais de um manifesto")
            entradas[chave] = (ano, entrada)
    return entradas, soma.hexdigest()


def caminho_texto(textos: Path, tipo: str, ano: int, documento: str, chave: str) -> Path:
    """textos/<tipo>/<ano>/<documento sem prefixo>/<origem>-<id>.txt (contrato, seção 7.1)."""
    return textos / "textos" / tipo / str(ano) / documento.split(":", 1)[1] / f"{chave.replace(':', '-', 1)}.txt"


def carregar_fonte(raiz: str | Path, textos: str | Path | None, liberados) -> Fonte:
    raiz = Path(raiz)
    textos = Path(textos) if textos else None
    avisos: list[str] = []
    documentos, autoria, pessoas, ementas = _documentos(raiz, liberados)
    entradas, sha_manifestos = _manifestos(raiz)

    itens_remocao = remocoes.carregar(raiz)
    indice = remocoes.indice(itens_remocao)
    linhas_remocoes = {(r["chave"], r["sha256"]): (r["chave"], r["sha256"], r.get("motivo") or "", r.get("data") or "")
                       for r in itens_remocao}
    remover_r2 = {chave_r2(r["sha256"].lower()) for r in itens_remocao}

    arquivos: dict[tuple, tuple] = {}
    arquivo_documento: dict[tuple, tuple] = {}
    originais: dict[str, Original] = {}
    com_texto: dict[str, tuple[int, dict]] = {}
    removidas: set[str] = set()
    for chave in sorted(entradas, key=ordem_chave):
        ano, e = entradas[chave]
        sha = e.get("sha256_original")
        status = e.get("status")
        if status == "removido" or indice.contem(chave, sha):
            removidas.add(chave)
            if sha:
                remover_r2.add(chave_r2(sha))
            continue
        if status == "duplicata":
            continue
        r2 = e.get("r2_chave")
        if r2 and (not sha or r2 != chave_r2(sha)):
            raise ErroFonte(f"{chave}: r2_chave não corresponde ao sha256_original")
        arquivos[(chave,)] = (chave, sha, e.get("formato"), status, 1 if (e.get("paginas_ocr") or 0) > 0 else 0,
                              e.get("confianca"), r2)
        for doc in e.get("documentos") or []:
            arquivo_documento[(chave, doc)] = (chave, doc)
        if r2:
            original = originais.setdefault(sha, Original(sha, r2, e.get("formato")))
            original.arquivos.add(chave)
            original.documentos.update(e.get("documentos") or [])
        if (e.get("trechos") or 0) > 0:
            com_texto[chave] = (ano, e)

    textos_arquivos: dict[str, str] = {}
    trechos = _trechos(textos, com_texto, removidas, avisos, textos_arquivos)

    vetores: dict[str, tuple[str, dict, str]] = {}
    for t in trechos.values():
        if not t.vetorizavel:
            continue
        doc = documentos.get((t.documento,))
        meta = {"ano": t.ano, "documento": t.documento, "tipo": t.tipo}
        if doc and doc[7]:
            meta["legislatura"] = doc[7]
        vetores[t.id] = (t.sha256, meta, t.texto)
    for (ident,), doc in documentos.items():
        if doc[1] in TIPOS_EMENTA_VETOR and doc[5].strip():
            meta = {"documento": ident, "tipo": doc[1]}
            if doc[3] is not None:
                meta["ano"] = doc[3]
            if doc[7]:
                meta["legislatura"] = doc[7]
            vetores[f"ementa:{ident}"] = (sha256(doc[5].encode("utf-8")), meta, doc[5])

    linhas = {
        "documentos": documentos,
        "ementas_fts": {(ident,): (ident, normalizar_busca(texto)) for ident, texto in ementas.items()},
        "autoria": autoria,
        "pessoas": pessoas,
        "arquivos": arquivos,
        "arquivo_documento": arquivo_documento,
        "trechos": {(t.id,): (t.id, t.documento, t.arquivo, t.posicao, t.texto, t.sha256) for t in trechos.values()},
        "remocoes": linhas_remocoes,
        "trechos_indexados": {(i,): (i, sha_indexado(v[0], v[1])) for i, v in vetores.items()},
    }
    return Fonte(linhas, trechos, vetores, ementas, originais, remover_r2, sha_manifestos, avisos, textos_arquivos)


def _trechos(textos: Path | None, com_texto: dict[str, tuple[int, dict]], removidas: set[str],
             avisos: list[str], textos_arquivos: dict[str, str]) -> dict[str, Trecho]:
    por_arquivo: dict[str, list[dict]] = defaultdict(list)
    pasta = textos / "trechos" if textos else None
    if pasta is not None and pasta.is_dir():
        for arq in sorted(pasta.rglob("*.jsonl")):
            for n, linha in enumerate(arq.read_text(encoding="utf-8").splitlines(), 1):
                if linha.strip():
                    try:
                        t = json.loads(linha)
                    except ValueError as e:
                        raise ErroFonte(f"{arq}:{n}: JSON inválido ({e})") from None
                    por_arquivo[t["arquivo"]].append(t)
    elif com_texto:
        raise ErroFonte(f"pasta de trechos ausente: {pasta} (informe --textos)")
    for chave in sorted(por_arquivo, key=ordem_chave):
        if chave in com_texto:
            continue
        if chave in removidas:
            avisos.append(f"{chave}: removido, mas ainda com trechos em dados-textos (expurgo pendente); ignorado")
            continue
        raise ErroFonte(f"{chave}: trechos sem entrada com texto no manifesto")

    trechos: dict[str, Trecho] = {}
    for chave in sorted(com_texto, key=ordem_chave):
        ano, e = com_texto[chave]
        lista = sorted(por_arquivo.get(chave, []), key=lambda t: t["posicao"])
        if len(lista) != e["trechos"]:
            raise ErroFonte(f"{chave}: {len(lista)} trechos em dados-textos, {e['trechos']} no manifesto")
        caminho = caminho_texto(textos, e["tipo"], ano, e["documento"], chave)
        try:
            dados = caminho.read_bytes()
        except FileNotFoundError:
            raise ErroFonte(f"{chave}: texto ausente ({caminho})") from None
        if sha256(dados) != e.get("sha256_texto"):
            raise ErroFonte(f"{chave}: sha256 do .txt difere do manifesto")
        if not dados.endswith(b"\n"):
            raise ErroFonte(f"{chave}: .txt sem a quebra final")
        texto = dados.decode("utf-8")[:-1]  # remove exatamente uma quebra final (contrato, seção 7.1)
        textos_arquivos[chave] = texto
        for t in lista:
            if t["documento"] != e["documento"]:
                raise ErroFonte(f"{chave}: trecho {t['id']} com documento diferente do principal")
            pedaco = texto[t["inicio"]:t["fim"]]
            if sha256(pedaco.encode("utf-8")) != t["sha256"]:
                raise ErroFonte(f"{chave}: trecho {t['id']} não confere com o texto (sha256)")
            if t["id"] in trechos:
                raise ErroFonte(f"trecho {t['id']} repetido")
            trechos[t["id"]] = Trecho(t["id"], t["documento"], chave, t["posicao"], pedaco, t["sha256"],
                                      bool(t.get("vetorizavel")), e["tipo"], ano, t["inicio"], t["fim"])
    return trechos


# ---------------------------------------------------------------- barreira de PII
def _ocorrencias(texto: str, liberados) -> list[dict]:
    """Acrescenta achados estritos sem duplicar ocorrências fortes sobrepostas."""
    achados = mascara.varrer(texto, liberados)
    fortes = [(o["inicio"], o["fim"]) for o in achados if o["forte"]]
    extras = [{**o, "forte": True} for o in mascara.varrer_estrito(texto, liberados)
              if not any(o["inicio"] < b and o["fim"] > a for a, b in fortes)]
    return sorted(achados + extras, key=lambda o: (o["inicio"], o["fim"], o["tipo"]))


def varrer_fonte(fonte: Fonte, liberados) -> tuple[list[dict], int]:
    """Varre cada arquivo completo uma vez e atribui fortes aos trechos sobrepostos.

    As posições relatadas são relativas ao trecho, recortadas aos seus limites,
    sem o valor pessoal. Fracas são contadas uma vez por ocorrência do arquivo
    com trecho sobreposto. Ementas e motivos de remoção são varridos isoladamente.
    """
    liberados = frozenset(liberados)
    fortes: list[dict] = []
    fracas = 0
    por_arquivo: dict[str, list[Trecho]] = defaultdict(list)
    for _, t in sorted(fonte.trechos.items()):
        por_arquivo[t.arquivo].append(t)
    for arquivo, trechos in sorted(por_arquivo.items()):
        if arquivo not in fonte.textos_arquivos:
            raise ErroFonte(f"{arquivo}: texto completo ausente para a barreira de PII")
        texto = fonte.textos_arquivos[arquivo]
        for o in _ocorrencias(texto, liberados):
            sobrepostos = [t for t in trechos if o["inicio"] < t.fim and o["fim"] > t.inicio]
            if not sobrepostos:
                continue
            if not o["forte"]:
                fracas += 1
                continue
            for t in sobrepostos:
                fortes.append({"origem": f"trecho {t.id} ({t.arquivo})", "tipo": o["tipo"],
                               "inicio": max(o["inicio"], t.inicio) - t.inicio,
                               "fim": min(o["fim"], t.fim) - t.inicio})
    alvos = [(f"ementa {d}", texto) for d, texto in sorted(fonte.ementas.items())]
    alvos += [(f"remocao {chave[0]}", linha[2] or "") for chave, linha in sorted(fonte.linhas["remocoes"].items())]
    for origem, texto in alvos:
        for o in _ocorrencias(texto, liberados):
            if o["forte"]:
                fortes.append({"origem": origem, "tipo": o["tipo"], "inicio": o["inicio"], "fim": o["fim"]})
            else:
                fracas += 1
    return fortes, fracas
