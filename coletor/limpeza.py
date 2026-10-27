"""Limpeza do texto extraído antes de gravar e de gerar embeddings.

Ordem no pipeline: extrair → **limpar** → mascarar → trechos. A limpeza tira linhas
sem conteúdo útil, sempre linha inteira e de forma determinística:

- **cabecalho_rodape**: em textos com 2 ou mais páginas (separadas por uma linha só
  com \\f, como sai de `coletor.extratores`), linhas entre as 4 primeiras e as 4 últimas
  linhas não vazias de cada página cuja forma normalizada (`normalizar_linha`, com
  dígitos trocados por "#") se repete em pelo menos metade das páginas (e em 2 ou mais);
  repetido até não haver mais o que tirar;
- **numeracao**: "Página 1 de 3", "Pág. 2", "- 2 -", "2/5" e linha só com um número;
- **ruido_ocr**: linhas só de separadores (----, ____, ****, ====), linhas com menos de
  3 letras/dígitos ou com menos de 40% de letras/dígitos entre os caracteres visíveis;
- **cliche**: linhas cuja forma normalizada está no conjunto de clichês do corpus
  (`gerar_cliches`, gravado em `data/textos/cliches.json`).

Nunca são removidas (`ProtecaoLimpeza`) linhas com "art.", "art ", "§", "parágrafo",
"inciso", "justificativa", "sala das sessões", "ementa", "lei n", "lei complementar",
"decreto" ou "processo" (sem diferenciar maiúsculas e acentos), linhas com a ementa do
documento, linhas com o nome (de 2 ou mais palavras) de vereadores e suplentes da
configuração e linhas com 12 ou mais palavras. As linhas em branco repetidas são
reduzidas pela normalização de `coletor.trechos`.

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
import json
import math
import re
import sys
import unicodedata
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from . import arquivos
from .trechos import SEPARADOR_PAGINA, normalizar, paginas

VERSAO_LIMPEZA = "1"
REGRAS = ("cabecalho_rodape", "numeracao", "ruido_ocr", "cliche", "linhas_removidas")
LINHAS_BORDA = 4
FRACAO_CABECALHO = 0.5
MIN_PALAVRAS_CONTEUDO = 12
MIN_DOCS_CLICHE = 5
MIN_UTEIS = 3
FRACAO_UTEIS = 0.4

RAIZ = Path(__file__).resolve().parent.parent
CAMINHO_CLICHES = RAIZ / "data" / "textos" / "cliches.json"

_RE_PROTEGIDA = re.compile(
    r"\bart\.|\bart\s|§|paragrafo|inciso|justificativa|sala das sessoes|ementa|\blei n"
    r"|lei complementar|decreto|processo"
)
_RE_NUMERACAO = re.compile(
    r"^(?:p(?:agina|ag\.?|g\.?)\s*(?:n[º°o]\.?\s*)?\d+(?:\s*(?:de|/)\s*\d+)?"
    r"|-\s*\d+\s*-|\d+\s*/\s*\d+|\d+\s+de\s+\d+|\d+\.?)$"
)
_RE_SEPARADOR = re.compile(r"^(?:[-_*=~.·•]\s*){3,}$")
_RE_DIGITOS = re.compile(r"\d+")
_RE_ESPACOS = re.compile(r"\s+")
_RE_PALAVRA = re.compile(r"\w+")


# ---------------------------------------------------------------- normalização
def dobrar(texto: str) -> str:
    """Minúsculas, sem acentos (NFD sem marcas combinantes)."""
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower())
                   if unicodedata.category(c) != "Mn")


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


# ---------------------------------------------------------------- proteção
class ProtecaoLimpeza:
    """Linhas que a limpeza nunca remove (veja o docstring do módulo)."""

    def __init__(self, nomes: Iterable[str] = ()) -> None:
        indice: dict[str, set[tuple[str, ...]]] = {}
        for nome in nomes:
            if not isinstance(nome, str):
                continue
            tokens = tuple(_RE_PALAVRA.findall(dobrar(nome)))
            if len(tokens) >= 2:  # nome de uma palavra só é ambíguo demais
                indice.setdefault(tokens[0], set()).add(tokens)
        self._nomes = {k: sorted(v) for k, v in indice.items()}

    @property
    def nomes(self) -> list[tuple[str, ...]]:
        return sorted(t for v in self._nomes.values() for t in v)

    @classmethod
    def de_config(cls, raiz: Path = RAIZ) -> ProtecaoLimpeza:
        """Nomes de `config/vereadores.json` (eleitos, apelidos, afastamentos, Mesa) e
        as chaves de `config/perfis.json`; arquivos ausentes não acrescentam nada."""
        raiz = Path(raiz)
        pasta = raiz / "config" if (raiz / "config").is_dir() else raiz
        nomes: list[str] = []
        vereadores = _ler_json(pasta / "vereadores.json") or {}
        for legislatura in vereadores.get("legislaturas") or []:
            for eleito in legislatura.get("eleitos") or []:
                nomes += [eleito.get("siscam"), eleito.get("nome")]
        for chave, valor in (vereadores.get("apelidos") or {}).items():
            if not str(chave).startswith("_"):
                nomes += [chave, valor]
        for afastamento in vereadores.get("afastamentos") or []:
            nomes.append(afastamento.get("siscam"))
            nomes += afastamento.get("suplentes") or []
        for cargo in vereadores.get("mesa") or []:
            nomes.append(cargo.get("siscam"))
        perfis = _ler_json(pasta / "perfis.json") or {}
        nomes += list((perfis.get("vereadores") or {}).keys())
        return cls(n for n in nomes if isinstance(n, str))

    def tem_nome(self, linha: str) -> bool:
        tokens = _RE_PALAVRA.findall(dobrar(linha))
        for i, token in enumerate(tokens):
            for nome in self._nomes.get(token, ()):
                if tuple(tokens[i:i + len(nome)]) == nome:
                    return True
        return False

    def protegida(self, linha: str, ementa: str = "") -> bool:
        """Se a linha não pode ser removida; `ementa` já em `_compactar`."""
        if len(linha.split()) >= MIN_PALAVRAS_CONTEUDO:
            return True
        d = _compactar(linha)
        if _RE_PROTEGIDA.search(d):
            return True
        if ementa and d and ((len(d) >= 15 and d in ementa) or ementa in d):
            return True
        return self.tem_nome(linha)


def _ler_json(caminho: Path):
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


# ---------------------------------------------------------------- regras
def _regra_linha(linha: str, cliches) -> str | None:
    """Regra que remove a linha (fora cabeçalho/rodapé), ou None."""
    visivel = linha.strip()
    if _RE_NUMERACAO.match(_compactar(visivel)):
        return "numeracao"
    chave = normalizar_linha(visivel)
    if chave and chave in cliches:
        return "cliche"
    if _RE_SEPARADOR.match(visivel):
        return "ruido_ocr"
    sem_espacos = "".join(visivel.split())
    uteis = sum(map(str.isalnum, sem_espacos))
    if uteis < MIN_UTEIS or uteis < FRACAO_UTEIS * len(sem_espacos):
        return "ruido_ocr"
    return None


def _remover_cabecalhos(paginas_: list[list[str]], protegida) -> int:
    """Remove linhas de borda repetidas em ≥ metade das páginas; devolve quantas."""
    n = len(paginas_)
    minimo = max(2, math.ceil(FRACAO_CABECALHO * n))
    presencas: Counter = Counter()
    bordas: list[dict[str, list[int]]] = []
    for pagina in paginas_:
        cheias = [i for i, linha in enumerate(pagina) if linha.strip()]
        chaves: dict[str, list[int]] = {}
        for i in sorted(set(cheias[:LINHAS_BORDA] + cheias[-LINHAS_BORDA:])):
            chave = normalizar_linha(pagina[i])
            if chave:
                chaves.setdefault(chave, []).append(i)
        bordas.append(chaves)
        presencas.update(chaves.keys())
    repetidas = {chave for chave, total in presencas.items() if total >= minimo}
    removidas = 0
    for pagina, chaves in zip(paginas_, bordas):
        remover = {i for chave in repetidas.intersection(chaves) for i in chaves[chave]
                   if not protegida(pagina[i])}
        if remover:
            pagina[:] = [linha for i, linha in enumerate(pagina) if i not in remover]
            removidas += len(remover)
    return removidas


def limpar(texto: str, cliches=frozenset(), protegidos: ProtecaoLimpeza | None = None,
           ementa: str = "") -> tuple[str, dict[str, int]]:
    """Texto limpo (normalizado) e quantas linhas cada regra removeu; idempotente.

    `cliches` é um conjunto (ou o mapa de `gerar_cliches`) de linhas normalizadas;
    `ementa` é a ementa do documento, cujas linhas ficam protegidas.
    """
    protecao = protegidos or ProtecaoLimpeza()
    ementa_c = _compactar(ementa) if ementa else ""
    contagens = {regra: 0 for regra in REGRAS}
    cache: dict[str, bool] = {}

    def protegida(linha: str) -> bool:
        if linha not in cache:
            cache[linha] = protecao.protegida(linha, ementa_c)
        return cache[linha]

    texto = normalizar(texto)
    paginas_ = [pagina.split("\n") for pagina in paginas(texto)]
    mudou = True
    while mudou:
        mudou = False
        for pagina in paginas_:
            mantidas = []
            for linha in pagina:
                regra = None if not linha.strip() or protegida(linha) else _regra_linha(linha, cliches)
                if regra:
                    contagens[regra] += 1
                    mudou = True
                else:
                    mantidas.append(linha)
            pagina[:] = mantidas
        if len(paginas_) >= 2:
            removidas = _remover_cabecalhos(paginas_, protegida)
            if removidas:
                contagens["cabecalho_rodape"] += removidas
                mudou = True
    contagens["linhas_removidas"] = sum(contagens[r] for r in REGRAS[:-1])
    limpo = SEPARADOR_PAGINA.join("\n".join(pagina) for pagina in paginas_)
    return normalizar(limpo), contagens


# ---------------------------------------------------------------- clichês do corpus
def gerar_cliches(textos_por_documento: Iterable[tuple[str, str]], min_fracao: float = 0.02,
                  min_docs: int = 20, protecao: ProtecaoLimpeza | None = None) -> dict[str, int]:
    """Linhas normalizadas frequentes no corpus: {linha: documentos distintos}.

    Entra a linha presente em pelo menos `min_docs` documentos ou em pelo menos
    `min_fracao` deles, nunca em menos de `MIN_DOCS_CLICHE`. Linhas protegidas (sem
    ementa) ficam de fora. Documentos repetidos (mesmo id) contam uma vez. O mapa sai
    ordenado pela linha: mesma entrada, mesmo resultado.
    """
    protecao = protecao or ProtecaoLimpeza()
    por_documento: dict[str, set[str]] = {}
    cache: dict[str, str | None] = {}
    for documento, texto in textos_por_documento:
        chaves = por_documento.setdefault(str(documento), set())
        for linha in texto.split("\n"):
            if not linha.strip():
                continue
            if linha not in cache:
                cache[linha] = None if protecao.protegida(linha) else (normalizar_linha(linha) or None)
            chave = cache[linha]
            if chave:
                chaves.add(chave)
    total = len(por_documento)
    if not total:
        return {}
    contagem = Counter(chave for chaves in por_documento.values() for chave in chaves)
    escolhidas = {
        chave: n for chave, n in contagem.items()
        if n >= MIN_DOCS_CLICHE and (n >= min_docs or n * 1_000_000 >= round(min_fracao * 1_000_000) * total)
    }
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
                            ProtecaoLimpeza.de_config(RAIZ))
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    arquivos.salvar_mapa(args.saida, cliches)
    print(f"{len(cliches)} clichês gravados em {args.saida} (VERSAO_LIMPEZA {VERSAO_LIMPEZA})")
    if args.recalcular_cliches:
        print("lembrete: suba VERSAO_LIMPEZA para reprocessar os textos", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
