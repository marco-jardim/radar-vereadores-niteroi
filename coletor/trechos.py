"""Normalização do texto extraído e divisão determinística em trechos.

O texto de cada arquivo é normalizado uma única vez (`normalizar`) e gravado assim;
os trechos guardam só offsets nesse texto normalizado, nunca o próprio texto:
`texto[inicio:fim]` reconstitui cada trecho. `inicio`/`fim` contam pontos de código
(índices de `str` do Python); `inicio_utf16`/`fim_utf16` contam unidades UTF-16,
para fatiar o mesmo texto em JavaScript (`texto.slice(inicio_utf16, fim_utf16)`).

Páginas (PDF) ficam separadas por uma linha só com \\f, preservada pela normalização.

Divisão (`dividir`):
- parágrafos são sequências de linhas não vazias, separadas por linha em branco ou
  por quebra de página;
- parágrafos acima de `LIMITE_UNIDADE` são cortados em fim de frase ou de linha e,
  na falta deles, em espaço; só uma palavra sem espaços maior que o limite é cortada
  no meio;
- parágrafos consecutivos são agrupados até o alvo de `ALVO` caracteres (até `MAXIMO`
  quando o trecho ainda está abaixo da metade do alvo);
- cada trecho seguinte começa até `SOBREPOSICAO` caracteres antes do fim do anterior,
  sempre no início de uma palavra;
- `vetorizavel` indica se o trecho tem ao menos `MIN_CARACTERES_VETOR` letras e
  dígitos; os demais não vão para os embeddings.

Mesma entrada, mesmos trechos e mesmos ids. Somente biblioteca padrão do Python.
"""
from __future__ import annotations

import bisect
import hashlib
import re
import unicodedata

VERSAO_TRECHOS = "2"
ALVO = 1200
MAXIMO = 2000
SOBREPOSICAO = 200
MIN_CARACTERES_VETOR = 80
# Uma unidade (parágrafo ou pedaço dele) mais a sobreposição nunca passa do máximo.
LIMITE_UNIDADE = MAXIMO - SOBREPOSICAO
SEPARADOR_PAGINA = "\n\f\n"

_QUEBRAS = {"\r": "\n", "\v": "\n", "\x85": "\n", "\u2028": "\n", "\u2029": "\n"}
_RE_LINHAS_VAZIAS = re.compile(r"\n{3,}")
_RE_PARAGRAFO = re.compile(r"[^\n\f]+(?:\n[^\n\f]+)*")
_RE_FIM_FRASE = re.compile(r"[.!?;:](?=\s)|\n")
_RE_ESPACO = re.compile(r"\s")
_RE_ASTRAL = re.compile("[\U00010000-\U0010FFFF]")


# ---------------------------------------------------------------- normalização
def _caractere(c: str) -> str:
    """Filtra um caractere: quebras viram \\n, espaços viram ' ', controles somem; \\f fica."""
    if c in "\n\t\f":
        return c
    if c in _QUEBRAS:
        return "\n"
    categoria = unicodedata.category(c)
    if categoria == "Zs":
        return " "
    if categoria in ("Cc", "Cf", "Cs"):
        return ""
    return c


def normalizar(texto: str) -> str:
    """Normaliza o texto extraído; idempotente.

    \\r\\n e \\r viram \\n; separadores Unicode de linha viram \\n; caracteres de
    formatação (categoria Cf, como U+200B e U+00AD), controles e surrogates somem;
    espaços Unicode (como U+00A0) viram espaço comum; aplica NFC. Em cada página
    (texto entre \\f), remove espaços no fim das linhas, reduz 3+ quebras seguidas a
    uma linha em branco e tira linhas em branco do começo e do fim; as páginas são
    unidas por `SEPARADOR_PAGINA` (uma linha só com \\f).
    """
    if not texto:
        return ""
    texto = texto.replace("\r\n", "\n")
    # Tabela só com os caracteres distintos que mudam: str.translate roda em C.
    tabela = {}
    for c in set(texto):
        novo = _caractere(c)
        if novo != c:
            tabela[ord(c)] = novo
    if tabela:
        texto = texto.translate(tabela)
    texto = unicodedata.normalize("NFC", texto)
    if "\f" in texto:
        return SEPARADOR_PAGINA.join(_normalizar_pagina(p) for p in texto.split("\f"))
    return _normalizar_pagina(texto)


def _normalizar_pagina(texto: str) -> str:
    texto = "\n".join(linha.rstrip(" \t") for linha in texto.split("\n"))
    texto = _RE_LINHAS_VAZIAS.sub("\n\n", texto)
    return texto.strip("\n")


def paginas(texto: str) -> list[str]:
    """Páginas de um texto normalizado (uma só se não houver \\f)."""
    return texto.split(SEPARADOR_PAGINA) if "\f" in texto else [texto]


# ---------------------------------------------------------------- unidades
def _corte(texto: str, ini: int, fim: int) -> int:
    """Posição de corte de um parágrafo longo, entre ini e fim (exclusivo)."""
    meio = ini + ALVO // 2
    alvo = ini + ALVO
    limite = ini + LIMITE_UNIDADE
    janela = texto[ini:min(fim, limite)]
    frases = [ini + m.end() for m in _RE_FIM_FRASE.finditer(janela)]
    perto = [p for p in frases if meio < p <= alvo]
    if perto:
        return perto[-1]
    depois = [p for p in frases if alvo < p <= limite]
    if depois:
        return depois[0]
    espacos = [ini + m.start() for m in _RE_ESPACO.finditer(janela)]
    perto = [p for p in espacos if meio < p <= alvo]
    if perto:
        return perto[-1]
    validos = [p for p in espacos if ini < p <= limite]
    if validos:
        return validos[-1]
    return limite  # uma única "palavra" maior que o limite: corte inevitável


def _aparar(texto: str, ini: int, fim: int) -> tuple[int, int]:
    while ini < fim and texto[ini].isspace():
        ini += 1
    while fim > ini and texto[fim - 1].isspace():
        fim -= 1
    return ini, fim


def _unidades(texto: str) -> list[tuple[int, int]]:
    """Parágrafos (ou pedaços de parágrafo) sem espaços nas pontas, até LIMITE_UNIDADE."""
    unidades: list[tuple[int, int]] = []
    for m in _RE_PARAGRAFO.finditer(texto):
        ini, fim = _aparar(texto, m.start(), m.end())
        while fim - ini > LIMITE_UNIDADE:
            corte = _corte(texto, ini, fim)
            a, b = _aparar(texto, ini, corte)
            if b > a:
                unidades.append((a, b))
            ini, fim = _aparar(texto, corte, fim)
        if fim > ini:
            unidades.append((ini, fim))
    return unidades


def _inicio_sobreposto(texto: str, ini_anterior: int, fim_anterior: int,
                       proxima: tuple[int, int]) -> int:
    """Início do trecho seguinte: começo de palavra até SOBREPOSICAO antes do fim anterior.

    A sobreposição não passa da metade do trecho anterior nem faz o trecho seguinte,
    que contém ao menos a próxima unidade, passar de MAXIMO.
    """
    p = max(fim_anterior - SOBREPOSICAO, (ini_anterior + fim_anterior + 1) // 2,
            proxima[1] - MAXIMO)
    while p < fim_anterior:
        if not texto[p].isspace() and (p == 0 or texto[p - 1].isspace()):
            return p
        p += 1
    return proxima[0]  # sem início de palavra na janela: sem sobreposição


# ---------------------------------------------------------------- trechos
def dividir(texto: str, documento: str, arquivo: str) -> list[dict]:
    """Divide o texto normalizado em trechos com offsets.

    Cada trecho é `{id, documento, arquivo, posicao, inicio, fim, inicio_utf16,
    fim_utf16, sha256, vetorizavel}`, com `sha256` dos bytes UTF-8 de
    `texto[inicio:fim]` e `id = sha1(f"{documento}|{arquivo}|{posicao}|{sha256}")[:16]`.
    O texto precisa já estar normalizado (`normalizar(texto) == texto`); caso
    contrário os offsets não corresponderiam ao `.txt` gravado e é ValueError.
    """
    if not texto or not texto.strip():
        return []
    if normalizar(texto) != texto:
        raise ValueError("texto não normalizado: aplique trechos.normalizar antes de dividir")
    unidades = _unidades(texto)
    astrais = [m.start() for m in _RE_ASTRAL.finditer(texto)]

    def utf16(i: int) -> int:
        # cada caractere fora do plano básico ocupa duas unidades UTF-16
        return i + bisect.bisect_left(astrais, i) if astrais else i

    trechos: list[dict] = []
    j = 0
    ini = unidades[0][0] if unidades else 0
    while j < len(unidades):
        fim = unidades[j][1]
        while j + 1 < len(unidades):
            novo = unidades[j + 1][1] - ini
            if novo <= ALVO or (fim - ini < ALVO // 2 and novo <= MAXIMO):
                j += 1
                fim = unidades[j][1]
            else:
                break
        trecho = _trecho(texto, documento, arquivo, len(trechos), ini, fim)
        trecho["inicio_utf16"], trecho["fim_utf16"] = utf16(ini), utf16(fim)
        trechos.append(trecho)
        j += 1
        if j < len(unidades):
            ini = _inicio_sobreposto(texto, ini, fim, unidades[j])
    return trechos


def _trecho(texto: str, documento: str, arquivo: str, posicao: int, ini: int, fim: int) -> dict:
    parte = texto[ini:fim]
    sha = hashlib.sha256(parte.encode("utf-8")).hexdigest()
    ident = hashlib.sha1(f"{documento}|{arquivo}|{posicao}|{sha}".encode("utf-8")).hexdigest()[:16]
    return {
        "id": ident,
        "documento": documento,
        "arquivo": arquivo,
        "posicao": posicao,
        "inicio": ini,
        "fim": fim,
        "sha256": sha,
        "vetorizavel": vetorizavel(parte),
    }


def vetorizavel(parte: str) -> bool:
    """Se o trecho tem letras e dígitos suficientes para virar embedding."""
    return sum(map(str.isalnum, parte)) >= MIN_CARACTERES_VETOR


def texto_do_trecho(texto: str, trecho: dict) -> str:
    """Texto de um trecho, conferindo o hash; ValueError se o texto não corresponde."""
    parte = texto[trecho["inicio"]:trecho["fim"]]
    if hashlib.sha256(parte.encode("utf-8")).hexdigest() != trecho["sha256"]:
        raise ValueError(f"trecho {trecho.get('id')} não corresponde ao texto")
    return parte
