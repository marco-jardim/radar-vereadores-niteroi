"""Limpeza do texto extraído antes de gravar e de gerar embeddings.

Ordem no pipeline: extrair → **limpar** → mascarar → trechos. A limpeza tira linhas
sem conteúdo útil, sempre linha inteira e de forma determinística, numa passada:

1. regras por linha, aplicadas uma vez:
   - **cliche**: linha cuja forma normalizada (`normalizar_linha`) está no conjunto de
     clichês do corpus (`gerar_cliches`, gravado em `data/textos/cliches.json`); não sai
     se parecer continuação da linha anterior (a anterior não termina em . : ; ! ? e a
     atual começa por minúscula), nem se for de uma palavra só fora de
     `PALAVRAS_UNICAS_CLICHE`;
   - **numeracao**: só em textos com 2 ou mais páginas (\\f) e só nas 4 primeiras ou
     4 últimas linhas não vazias de cada página: "Página 1 de 3", "Pág. 2", "- 2 -",
     "2/5" (com n ≤ m ≤ 999, sem anos) e número sozinho de até 3 dígitos;
   - **ruido_ocr**: linhas só de separadores (----, ____, ****, ====) e linhas com menos
     de 3 letras/dígitos ou menos de 40% de letras/dígitos entre os caracteres visíveis;
     aplicado a todas as linhas das páginas em `ocr_paginas` e, nas demais (ou com
     `ocr_paginas=None`), só às linhas das bordas. Ficam numerais romanos ("I", "II"),
     ordinais ("1º") e linhas de tabela com "|";
2. **cabecalho_rodape** (uma passada): em textos com 2 ou mais páginas, linhas das
   bordas de cada página cuja forma normalizada tem letras, se repete nas bordas de
   pelo menos metade das páginas (e de 2 ou mais) e não aparece no miolo de nenhuma
   página.

Nunca são removidas (`ProtecaoLimpeza`): linhas com 12 ou mais palavras; com "art.",
"§", "parágrafo", "inciso", "justificativa", "ementa", "lei n", "lei complementar",
"decreto" ou "processo"; "sala das sessões" sem data por extenso; estrutura legal
(capítulo, seção, título, anexo, "das disposições finais/…", inciso "I –"); atos
numerados ("Requerimento nº 12/2024", mas não o modelo em branco "nº ____/2024");
endereços (rua, avenida, praça…) e nomes de bairros de Niterói, exceto o endereço da
Câmara (Amaral Peixoto); a ementa do documento; e nomes de vereadores, suplentes e
prefeitos (2 palavras seguidas de um nome, ou prenome + sobrenome/apelido), sem
diferenciar maiúsculas e acentos.

`gerar_cliches` só aceita linhas presentes em pelo menos
max(`min_docs`, ⌈`min_fracao` × documentos⌉) documentos (e nunca menos de 5), e
recusa: linhas protegidas, com ocorrência forte de `mascara.varrer`, com "@", "www."
ou "http", sem palavras (só números/símbolos), de uma palavra só fora da lista
fechada e começos de ementa ("Concede…", "Requer…", "Institui…").

Mudar qualquer regra, a proteção ou os clichês muda os textos gravados: suba
`VERSAO_LIMPEZA`. Clichês só são recalculados com `--recalcular-cliches`, junto com
essa troca de versão.

Uso:
  python -m coletor.limpeza --gerar-cliches --cache DIR [--saida ARQ]
  python -m coletor.limpeza --recalcular-cliches --cache DIR [--saida ARQ]
DIR tem um .txt por documento (texto bruto extraído). `--gerar-cliches` não
sobrescreve um arquivo existente; `--recalcular-cliches` sobrescreve e exige subir
VERSAO_LIMPEZA. Somente biblioteca padrão do Python.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path

from . import arquivos, mascara
from .regras_documentos import BAIRROS_NITEROI
from .trechos import SEPARADOR_PAGINA, normalizar, paginas

VERSAO_LIMPEZA = "2"
REGRAS = ("cabecalho_rodape", "numeracao", "ruido_ocr", "cliche", "linhas_removidas")
LINHAS_BORDA = 4
FRACAO_CABECALHO = 0.5
MIN_PALAVRAS_CONTEUDO = 12
MIN_DOCS_CLICHE = 5
MIN_UTEIS = 3
FRACAO_UTEIS = 0.4
MAX_VARIANTES = 64  # linhas originais conferidas por chave em gerar_cliches

PREFEITOS = ("axel grael", "rodrigo neves")
PALAVRAS_UNICAS_CLICHE = frozenset({
    "vereador", "vereadora", "presidente", "prefeito", "atenciosamente", "cordialmente",
    "assunto", "membro", "relator", "assinatura",
})
VERBOS_EMENTA = ("concede", "requer", "solicita", "institui", "dispoe", "autoriza", "denomina",
                 "declara", "altera", "cria", "proibe", "obriga", "estabelece", "reconhece")
CONECTORES = frozenset({"da", "de", "do", "das", "dos", "e", "d"})
MARCA_ENDERECO_CAMARA = "amaral peixoto"

RAIZ = Path(__file__).resolve().parent.parent
CAMINHO_CLICHES = RAIZ / "data" / "textos" / "cliches.json"

_RE_MARCAS = re.compile("[\u0300-\u036f]")
_RE_DIGITOS = re.compile(r"\d+")
_RE_ESPACOS = re.compile(r"\s+")
_RE_LETRAS = re.compile(r"[^\W\d_]+")
_RE_PROTEGIDA = re.compile(
    r"\bart\.|\bart\s|§|paragrafo|inciso|justificativa|ementa|\blei n|lei complementar"
    r"|decreto|processo"
)
_RE_DATA_EXTENSO = re.compile(r"\d{1,2}\s*(?:º|°|o)?\s+de\s+[a-z]+\s+de\s+\d{4}")
_RE_ESTRUTURA = re.compile(
    r"^(?:capitulo\s+(?:\d+|[ivxlc]+)\b|secao\s+(?:\d+|[ivxlc]+)\b|titulo\b|anexo\b"
    r"|[ivxlc]+\s?[–-])|das disposicoes (?:finais|preliminares|transitorias|gerais)"
)
_RE_ATO_NUMERADO = re.compile(
    r"\b(?:requerimento|indicacao|mocao|projeto|lei|resolucao|decreto|processo|oficio|mensagem)\b"
    r".{0,30}?(?:n[º°o]\.?\s*\d|\d\s*/\s*\d)"
)
_RE_ENDERECO = re.compile(r"\b(?:rua|avenida|travessa|estrada|praca|largo|alameda|rodovia)\b|\bav\.")
_RE_NUMERACAO = re.compile(
    r"^(?:p(?:agina|ag\.?|g\.?)\s*(?:n[º°o]\.?\s*)?(?P<n1>\d+)(?:\s*(?:de|/)\s*(?P<m1>\d+))?"
    r"|-\s*(?P<n2>\d+)\s*-|(?P<n3>\d+)\s*(?:/|de)\s*(?P<m3>\d+)|(?P<n4>\d+)\.?)$"
)
_RE_SEPARADOR = re.compile(r"^(?:[-_*=~.·•]\s*){3,}$")
_RE_ROMANO_ORDINAL = re.compile(r"^(?:[ivxlcdm]+|\d+\s*[º°ª])[.)]?$", re.I)
_RE_VERBO_EMENTA = re.compile(r"^(?:" + "|".join(VERBOS_EMENTA) + r")\b")


# ---------------------------------------------------------------- normalização
def dobrar(texto: str) -> str:
    """Minúsculas, sem acentos (NFD sem marcas combinantes)."""
    return _RE_MARCAS.sub("", unicodedata.normalize("NFD", texto.lower()))


def normalizar_linha(linha: str) -> str:
    """Forma de comparação de uma linha: sem acentos, minúscula, espaços reduzidos,
    cada sequência de dígitos trocada por "#" e sem pontuação nas pontas."""
    t = _RE_ESPACOS.sub(" ", _RE_DIGITOS.sub("#", dobrar(linha))).strip()
    i, j = 0, len(t)
    while i < j and not (t[i].isalnum() or t[i] == "#"):
        i += 1
    while j > i and not (t[j - 1].isalnum() or t[j - 1] == "#"):
        j -= 1
    return t[i:j]


def _compactar(texto: str) -> str:
    return _RE_ESPACOS.sub(" ", dobrar(texto)).strip()


def _tokens(texto_dobrado: str) -> list[str]:
    """Palavras (só letras) sem conectores como "da", "de", "dos"."""
    return [t for t in _RE_LETRAS.findall(texto_dobrado) if t not in CONECTORES]


# ---------------------------------------------------------------- proteção
class ProtecaoLimpeza:
    """Linhas que a limpeza nunca remove (veja o docstring do módulo).

    `nomes` tem um item por pessoa: um nome ou uma sequência de variantes do mesmo
    nome (nome no SISCAM, nome de exibição, apelido). Uma linha é protegida se tem
    duas palavras seguidas de uma variante ou o prenome de uma variante seguido de
    outra palavra (sobrenome ou apelido) da mesma pessoa; conectores são ignorados.
    """

    def __init__(self, nomes: Iterable[str | Sequence[str]] = ()) -> None:
        pares: set[tuple[str, str]] = set()
        for pessoa in nomes:
            variantes = [pessoa] if isinstance(pessoa, str) else list(pessoa)
            listas = [_tokens(dobrar(v)) for v in variantes if isinstance(v, str)]
            listas = [t for t in listas if t]
            prenomes = {t[0] for t in listas}
            palavras = {p for t in listas for p in t}
            for t in listas:
                pares.update(zip(t, t[1:]))
            pares.update((g, s) for g in prenomes for s in palavras if s != g)
        self._pares = frozenset(pares)
        indice: dict[str, set[tuple[str, ...]]] = {}
        for bairro in BAIRROS_NITEROI:
            tokens = tuple(_tokens(dobrar(bairro)))
            if tokens:
                indice.setdefault(tokens[0], set()).add(tokens)
        self._bairros = {k: sorted(v) for k, v in indice.items()}

    @property
    def nomes(self) -> list[tuple[str, str]]:
        """Pares de palavras que identificam um nome protegido."""
        return sorted(self._pares)

    @classmethod
    def de_config(cls, raiz: Path = RAIZ) -> ProtecaoLimpeza:
        """Proteção com as pessoas de `pessoas_de_config(raiz)`."""
        return cls(pessoas_de_config(raiz))

    def _nome_em(self, tokens: list[str]) -> bool:
        return any(par in self._pares for par in zip(tokens, tokens[1:]))

    def _bairro_em(self, tokens: list[str]) -> bool:
        for i, token in enumerate(tokens):
            for bairro in self._bairros.get(token, ()):
                if tuple(tokens[i:i + len(bairro)]) == bairro:
                    return True
        return False

    def tem_nome(self, linha: str) -> bool:
        return self._nome_em(_tokens(dobrar(linha)))

    def protegida(self, linha: str, ementa: str = "") -> bool:
        """Se a linha não pode ser removida; `ementa` já em `_compactar`."""
        d = _compactar(linha)
        if not d:
            return False
        if len(_RE_LETRAS.findall(d)) >= MIN_PALAVRAS_CONTEUDO:
            return True
        if _RE_PROTEGIDA.search(d) or _RE_ESTRUTURA.search(d) or _RE_ATO_NUMERADO.search(d):
            return True
        if "sala das sessoes" in d and not _RE_DATA_EXTENSO.search(d):
            return True
        tokens = _tokens(d)
        if MARCA_ENDERECO_CAMARA not in d and (_RE_ENDERECO.search(d) or self._bairro_em(tokens)):
            return True
        if ementa and ((len(d) >= 15 and d in ementa) or ementa in d):
            return True
        return self._nome_em(tokens)


def _ler_json(caminho: Path):
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def pessoas_de_config(raiz: Path = RAIZ) -> list[Sequence[str]]:
    """Pessoas protegidas: as de `config/vereadores.json` (eleitos com nome de exibição,
    apelidos, afastamentos, Mesa) e as chaves de `config/perfis.json`, em ordem do nome
    em maiúsculas, seguidas de `PREFEITOS`; cada item lista as variantes do nome.
    Arquivos ausentes não acrescentam nada. Aceita a raiz ou a pasta `config/`."""
    raiz = Path(raiz)
    pasta = raiz / "config" if (raiz / "config").is_dir() else raiz
    pessoas: dict[str, list[str]] = {}

    def incluir(chave, *variantes) -> None:
        if isinstance(chave, str) and chave:
            pessoas.setdefault(chave.upper(), [chave]).extend(
                v for v in variantes if isinstance(v, str) and v)

    vereadores = _ler_json(pasta / "vereadores.json") or {}
    for legislatura in vereadores.get("legislaturas") or []:
        for eleito in legislatura.get("eleitos") or []:
            incluir(eleito.get("siscam"), eleito.get("nome"))
    for chave, valor in (vereadores.get("apelidos") or {}).items():
        if not str(chave).startswith("_"):
            incluir(chave, valor)
    for afastamento in vereadores.get("afastamentos") or []:
        incluir(afastamento.get("siscam"))
        for suplente in afastamento.get("suplentes") or []:
            incluir(suplente)
    for cargo in vereadores.get("mesa") or []:
        incluir(cargo.get("siscam"))
    perfis = _ler_json(pasta / "perfis.json") or {}
    for chave in (perfis.get("vereadores") or {}):
        incluir(chave)
    lista: list[Sequence[str]] = [pessoas[k] for k in sorted(pessoas)]
    lista += [(p,) for p in PREFEITOS]
    return lista


# ---------------------------------------------------------------- versões e configuração
def versao_efetiva(raiz: Path = RAIZ, cliches: Path | None = None) -> str:
    """Versão da limpeza gravada no manifesto: `VERSAO_LIMPEZA` + "+" + os 8 primeiros
    hexadecimais do SHA-256 dos bytes de `data/textos/cliches.json` (ou de `cliches`).
    Sem o arquivo, usa o SHA-256 de zero bytes (nenhum clichê)."""
    caminho = Path(cliches) if cliches is not None else Path(raiz) / "data" / "textos" / "cliches.json"
    try:
        dados = caminho.read_bytes()
    except FileNotFoundError:
        dados = b""
    return f"{VERSAO_LIMPEZA}+{hashlib.sha256(dados).hexdigest()[:8]}"


def hash_config_de(liberados: Iterable[str], pessoas: Iterable[str | Sequence[str]]) -> str:
    """SHA-256 do JSON canônico da configuração que muda os textos: `liberados` da
    máscara (ordenados), as pessoas protegidas (variantes ordenadas e sem repetição,
    lista ordenada) e `PREFEITOS`. JSON com chaves ordenadas, sem espaços, UTF-8."""
    nomes = sorted({tuple(sorted({p} if isinstance(p, str) else set(p))) for p in pessoas})
    canonico = {
        "liberados": sorted(set(liberados)),
        "pessoas": [list(n) for n in nomes],
        "prefeitos": list(PREFEITOS),
    }
    texto = json.dumps(canonico, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def hash_config(raiz: Path = RAIZ) -> str:
    """`sha256_config` do manifesto: `hash_config_de(mascara.liberados(raiz),
    pessoas_de_config(raiz))`. Mudou, todos os textos são reprocessados e a barreira
    `mascara.varrer` roda em todos (docs/contratos/textos.md)."""
    return hash_config_de(mascara.liberados(raiz), pessoas_de_config(raiz))


# ---------------------------------------------------------------- regras
def cliche_admissivel(chave: str) -> bool:
    """Se uma linha normalizada pode ser clichê (independente da frequência)."""
    palavras = _RE_LETRAS.findall(chave)
    if not palavras:
        return False  # só números e símbolos
    if len(palavras) == 1 and palavras[0] not in PALAVRAS_UNICAS_CLICHE:
        return False
    if "@" in chave or "www." in chave or "http" in chave:
        return False
    return not _RE_VERBO_EMENTA.match(chave)


def _eh_numeracao(visivel: str) -> bool:
    m = _RE_NUMERACAO.match(_compactar(visivel))
    if not m:
        return False
    n = m.group("n1") or m.group("n2") or m.group("n3") or m.group("n4")
    total = m.group("m1") or m.group("m3")
    if len(n) > 3:
        return False  # ano ou número de ato, não página
    if total is None:
        return True
    return len(total) <= 3 and int(n) <= int(total) <= 999


def _eh_ruido(visivel: str) -> bool:
    if _RE_SEPARADOR.match(visivel):
        return True
    if "|" in visivel or _RE_ROMANO_ORDINAL.match(visivel):
        return False
    sem_espacos = "".join(visivel.split())
    uteis = sum(map(str.isalnum, sem_espacos))
    return uteis < MIN_UTEIS or uteis < FRACAO_UTEIS * len(sem_espacos)


def _continua(anterior: str, linha: str) -> bool:
    """Se a linha parece continuação da anterior (frase quebrada no meio)."""
    anterior, linha = anterior.rstrip(), linha.lstrip()
    return bool(anterior) and anterior[-1] not in ".:;!?" and linha[:1].islower()


def _bordas(pagina: list[str]) -> set[int]:
    cheias = [i for i, linha in enumerate(pagina) if linha.strip()]
    return set(cheias[:LINHAS_BORDA] + cheias[-LINHAS_BORDA:])


def _remover_cabecalhos(paginas_: list[list[str]], protegida, chave) -> int:
    """Uma passada: remove linhas de borda repetidas em ≥ metade das páginas que têm
    letras e não aparecem no miolo de nenhuma página; devolve quantas."""
    minimo = max(2, math.ceil(FRACAO_CABECALHO * len(paginas_)))
    presencas: Counter = Counter()
    miolo: set[str] = set()
    bordas: list[dict[str, list[int]]] = []
    for pagina in paginas_:
        borda = _bordas(pagina)
        chaves: dict[str, list[int]] = {}
        for i, linha in enumerate(pagina):
            if not linha.strip():
                continue
            k = chave(linha)
            if not k:
                continue
            if i in borda:
                chaves.setdefault(k, []).append(i)
            else:
                miolo.add(k)
        bordas.append(chaves)
        presencas.update(chaves.keys())
    repetidas = {k for k, total in presencas.items()
                 if total >= minimo and k not in miolo and _RE_LETRAS.search(k)}
    removidas = 0
    for pagina, chaves in zip(paginas_, bordas):
        remover = {i for k in repetidas.intersection(chaves) for i in chaves[k]
                   if not protegida(pagina[i])}
        if remover:
            pagina[:] = [linha for i, linha in enumerate(pagina) if i not in remover]
            removidas += len(remover)
    return removidas


def limpar(texto: str, cliches=frozenset(), protegidos: ProtecaoLimpeza | None = None,
           ementa: str = "", ocr_paginas: set[int] | None = None) -> tuple[str, dict[str, int]]:
    """Texto limpo (normalizado) e quantas linhas cada regra removeu.

    `cliches` é um conjunto (ou o mapa de `gerar_cliches`) de linhas normalizadas;
    `ementa` é a ementa do documento, cujas linhas ficam protegidas; `ocr_paginas`
    são as páginas (base 1) cujo texto veio do OCR, onde o ruído é procurado em todas
    as linhas (nas demais, só nas bordas).
    """
    protecao = protegidos or ProtecaoLimpeza()
    ementa_c = _compactar(ementa) if ementa else ""
    contagens = {regra: 0 for regra in REGRAS}
    cache_protecao: dict[str, bool] = {}
    cache_chave: dict[str, str] = {}

    def protegida(linha: str) -> bool:
        if linha not in cache_protecao:
            cache_protecao[linha] = protecao.protegida(linha, ementa_c)
        return cache_protecao[linha]

    def chave(linha: str) -> str:
        if linha not in cache_chave:
            cache_chave[linha] = normalizar_linha(linha)
        return cache_chave[linha]

    texto = normalizar(texto)
    paginas_ = [pagina.split("\n") for pagina in paginas(texto)]
    multipagina = len(paginas_) >= 2
    for numero, pagina in enumerate(paginas_, 1):
        borda = _bordas(pagina)
        pagina_ocr = ocr_paginas is not None and numero in ocr_paginas
        mantidas = []
        anterior = ""
        for i, linha in enumerate(pagina):
            if not linha.strip():
                mantidas.append(linha)
                continue
            visivel = linha.strip()
            regra = None
            k = chave(linha)
            if k and k in cliches and cliche_admissivel(k) and not _continua(anterior, linha):
                regra = "cliche"
            elif multipagina and i in borda and _eh_numeracao(visivel):
                regra = "numeracao"
            elif (pagina_ocr or i in borda) and _eh_ruido(visivel):
                regra = "ruido_ocr"
            if regra and not protegida(linha):
                contagens[regra] += 1
            else:
                mantidas.append(linha)
            anterior = linha
        pagina[:] = mantidas
    if multipagina:
        contagens["cabecalho_rodape"] += _remover_cabecalhos(paginas_, protegida, chave)
    contagens["linhas_removidas"] = sum(contagens[r] for r in REGRAS[:-1])
    limpo = SEPARADOR_PAGINA.join("\n".join(pagina) for pagina in paginas_)
    return normalizar(limpo), contagens


# ---------------------------------------------------------------- clichês do corpus
def _minimo_documentos(total: int, min_fracao: float, min_docs: int) -> int:
    fracao = -(-round(min_fracao * 1_000_000) * total // 1_000_000)  # teto, em inteiros
    return max(MIN_DOCS_CLICHE, min_docs, fracao)


def gerar_cliches(textos_por_documento: Iterable[tuple[str, str]], min_fracao: float = 0.02,
                  min_docs: int = 20, protecao: ProtecaoLimpeza | None = None,
                  liberados: Iterable[str] = frozenset()) -> dict[str, int]:
    """Linhas normalizadas frequentes no corpus: {linha: documentos distintos}.

    Entra a linha presente em pelo menos max(`min_docs`, ⌈`min_fracao` × total⌉)
    documentos, nunca menos de `MIN_DOCS_CLICHE`, e que passe em `cliche_admissivel`.
    Fica de fora a chave com alguma variante original (até `MAX_VARIANTES`) protegida
    ou com ocorrência forte de `mascara.varrer` (use os mesmos `liberados` da máscara).
    Documentos repetidos (mesmo id) contam uma vez. O mapa sai ordenado pela linha.
    """
    protecao = protecao or ProtecaoLimpeza()
    liberados = frozenset(liberados)
    por_documento: dict[str, set[str]] = {}
    variantes: dict[str, set[str]] = {}
    cache: dict[str, str] = {}
    for documento, texto in textos_por_documento:
        chaves = por_documento.setdefault(str(documento), set())
        for linha in texto.split("\n"):
            visivel = linha.strip()
            if not visivel or visivel == "\f":
                continue
            if visivel not in cache:
                cache[visivel] = normalizar_linha(visivel)
            k = cache[visivel]
            if k:
                chaves.add(k)
                conjunto = variantes.setdefault(k, set())
                if len(conjunto) < MAX_VARIANTES:
                    conjunto.add(visivel)
    total = len(por_documento)
    if not total:
        return {}
    minimo = _minimo_documentos(total, min_fracao, min_docs)
    contagem = Counter(k for chaves in por_documento.values() for k in chaves)
    escolhidas: dict[str, int] = {}
    for k, n in contagem.items():
        if n < minimo or not cliche_admissivel(k):
            continue
        linhas = sorted(variantes[k])
        if any(protecao.protegida(linha) for linha in linhas):
            continue
        if any(o["forte"] for linha in linhas for o in mascara.varrer(linha, liberados)):
            continue
        escolhidas[k] = n
    return dict(sorted(escolhidas.items()))


def carregar_cliches(caminho: Path = CAMINHO_CLICHES) -> dict[str, int]:
    """Clichês gravados; vazio se o arquivo não existe."""
    return _ler_json(Path(caminho)) or {}


def _textos_do_cache(pasta: Path):
    for arquivo in sorted(pasta.rglob("*.txt")):
        documento = arquivo.relative_to(pasta).with_suffix("").as_posix()
        yield documento, normalizar(arquivo.read_text(encoding="utf-8", errors="replace"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clichês do corpus para a limpeza dos textos.")
    acao = parser.add_mutually_exclusive_group(required=True)
    acao.add_argument("--gerar-cliches", action="store_true",
                      help="gera o arquivo de clichês (não sobrescreve)")
    acao.add_argument("--recalcular-cliches", action="store_true",
                      help="sobrescreve os clichês; exige subir VERSAO_LIMPEZA")
    parser.add_argument("--cache", type=Path, required=True, help="pasta com um .txt por documento")
    parser.add_argument("--saida", type=Path, default=CAMINHO_CLICHES)
    parser.add_argument("--min-fracao", type=float, default=0.02)
    parser.add_argument("--min-docs", type=int, default=20)
    args = parser.parse_args(argv)
    if not args.cache.is_dir():
        print(f"pasta inexistente: {args.cache}", file=sys.stderr)
        return 2
    if args.gerar_cliches and args.saida.exists():
        print(f"{args.saida} já existe; use --recalcular-cliches e suba VERSAO_LIMPEZA",
              file=sys.stderr)
        return 2
    cliches = gerar_cliches(_textos_do_cache(args.cache), args.min_fracao, args.min_docs,
                            ProtecaoLimpeza.de_config(RAIZ), mascara.liberados(RAIZ))
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    arquivos.salvar_mapa(args.saida, cliches)
    print(f"{len(cliches)} clichês gravados em {args.saida} (VERSAO_LIMPEZA {VERSAO_LIMPEZA})")
    if args.recalcular_cliches:
        print("lembrete: suba VERSAO_LIMPEZA para reprocessar os textos", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
