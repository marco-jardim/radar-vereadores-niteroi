"""Leitura das remoções (LGPD, art. 18) de `config/remocoes.json`.

Cada item tem `chave` (`siscam:<IdArquivo>` ou `sessao:<guid>`, a mesma chave do
manifesto de textos), `sha256` (do original), `motivo`, `fonte` e `data`; o formato é
conferido por `coletor.validar.validar_remocoes`. Um arquivo está removido quando a
chave **ou** o SHA-256 do original coincide com algum item: outra versão do mesmo id
e o mesmo original publicado sob outro id também ficam fora. Pela chave, o arquivo
nem é baixado; pelo SHA-256 (chave nova), é baixado só para calcular o hash e
descartado, sem cache nem R2 (veja `docs/contratos/textos.md`, seção "Remoções").

Arquivo ausente equivale a nenhuma remoção; arquivo ilegível ou com estrutura
inválida é ValueError, para nunca publicar por engano o que deveria sair. A leitura
fica em cache por caminho, renovada quando o tamanho ou a data de modificação mudam.

`aplicar_remocoes` expurga a árvore local; D1, Vectorize, R2 e exportações
são projeções sincronizadas por `coletor.nuvem`.
Somente biblioteca padrão do Python.
"""
from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO = Path("config") / "remocoes.json"

_cache: dict[str, tuple[tuple[int, int], list[dict], Indice]] = {}


@dataclass(frozen=True)
class Indice:
    """Chaves, hashes e pares (chave, sha256) removidos, para consultas repetidas."""

    chaves: frozenset[str]
    shas: frozenset[str]
    pares: frozenset[tuple[str, str]]

    def contem(self, chave: str | None = None, sha256: str | None = None) -> bool:
        """Se a chave ou o SHA-256 (qualquer um dos dois) foi removido."""
        if chave is None and sha256 is None:
            raise ValueError("informe a chave, o sha256 ou ambos")
        return ((chave is not None and chave in self.chaves)
                or (sha256 is not None and sha256.lower() in self.shas))


def _caminho(raiz: Path | str) -> Path:
    """Aceita a raiz do repositório, a pasta `config/` ou o próprio arquivo."""
    raiz = Path(raiz)
    if raiz.suffix == ".json":
        return raiz
    if raiz.name == "config" and not (raiz / "config").is_dir():
        return raiz / ARQUIVO.name
    return raiz / ARQUIVO


def _ler(caminho: Path) -> list[dict]:
    try:
        dados = json.loads(caminho.read_bytes().decode("utf-8"))
    except (OSError, ValueError) as e:  # ValueError inclui UnicodeDecodeError
        raise ValueError(f"{caminho}: não foi possível ler as remoções ({e})") from e
    itens = dados.get("remocoes") if isinstance(dados, dict) else None
    if not isinstance(itens, list):
        raise ValueError(f"{caminho}: esperado um objeto com a lista 'remocoes'")
    for i, item in enumerate(itens, 1):
        if (not isinstance(item, dict) or not isinstance(item.get("chave"), str)
                or not isinstance(item.get("sha256"), str)):
            raise ValueError(f"{caminho}: remoção {i} sem 'chave' e 'sha256' em texto")
    return itens


def _entrada(raiz: Path | str) -> tuple[list[dict], Indice]:
    caminho = _caminho(raiz)
    try:
        estado = os.stat(caminho)
    except FileNotFoundError:
        return [], Indice(frozenset(), frozenset(), frozenset())
    assinatura = (estado.st_mtime_ns, estado.st_size)
    nome = str(caminho.resolve())
    guardado = _cache.get(nome)
    if guardado is not None and guardado[0] == assinatura:
        return guardado[1], guardado[2]
    itens = _ler(caminho)
    indice = _indexar(itens)
    _cache[nome] = (assinatura, itens, indice)
    return itens, indice


def _indexar(itens: Iterable[dict] | Iterable[tuple[str, str]]) -> Indice:
    pares = set()
    for item in itens:
        if isinstance(item, dict):
            pares.add((item["chave"], item["sha256"].lower()))
        else:
            chave, sha256 = item
            pares.add((chave, sha256.lower()))
    return Indice(frozenset(c for c, _ in pares), frozenset(s for _, s in pares), frozenset(pares))


def limpar_cache() -> None:
    """Esquece as leituras guardadas (útil em testes)."""
    _cache.clear()


def carregar(raiz: Path | str = RAIZ) -> list[dict]:
    """Itens de `config/remocoes.json`, na ordem do arquivo; ausente = lista vazia.

    Devolve cópias: alterar o resultado não muda o cache.
    """
    itens, _ = _entrada(raiz)
    return [dict(item) for item in itens]


def chaves_removidas(raiz: Path | str = RAIZ) -> set[tuple[str, str]]:
    """Pares (chave, sha256) removidos."""
    return set(_entrada(raiz)[1].pares)


def indice(fonte: Path | str | Indice | Iterable = RAIZ) -> Indice:
    """Índice de consulta a partir da raiz (ou caminho), de um `Indice`, da lista de
    `carregar` ou do conjunto de `chaves_removidas`."""
    if isinstance(fonte, Indice):
        return fonte
    if isinstance(fonte, (str, os.PathLike)):
        return _entrada(fonte)[1]
    return _indexar(fonte)


def esta_removido(raiz_ou_cache: Path | str | Indice | Iterable = RAIZ,
                  chave: str | None = None, sha256: str | None = None) -> bool:
    """Se o arquivo de `chave` (`<origem>:<id>`) ou de `sha256` (do original) foi removido.

    Basta um dos dois coincidir. `raiz_ou_cache` aceita o mesmo que `indice`; ValueError
    se nem chave nem sha256 forem informados.
    """
    return indice(raiz_ou_cache).contem(chave, sha256)


def aplicar_remocoes(raiz: Path | str, textos: Path | str, *, hoje: str | None = None) -> set[str]:
    """Expurga todos os anos, independentemente dos filtros/limites da coleta.

    O chamador deve manter a trava de `coletor.textos`. Preserva hash/tamanho e
    os campos exatos do contrato (§4.2): motivo fica no config e no D1, não num
    campo extra do manifesto. Repetir também limpa restos de uma interrupção.
    """
    from coletor import arquivos
    from coletor.textos import entrada_vazia, hoje_brasilia, processado_em

    raiz, textos = Path(raiz), Path(textos)
    removidos = indice(raiz)
    if not removidos.pares:
        return set()
    hoje = hoje or hoje_brasilia()
    chaves = set(removidos.chaves)
    manifestos = []
    for caminho in sorted((raiz / "data" / "textos").glob("manifesto-*.json")):
        mapa = json.loads(caminho.read_text(encoding="utf-8"))
        novo = dict(mapa)
        for chave, anterior in mapa.items():
            if not removidos.contem(chave, anterior.get("sha256_original")):
                continue
            chaves.add(chave)
            entrada = entrada_vazia(anterior["documentos"], anterior["documento"], anterior["tipo"],
                                     anterior["url_origem"], "removido", hoje)
            entrada["sha256_original"] = anterior.get("sha256_original")
            entrada["bytes"] = anterior.get("bytes")
            entrada["processado_em"] = processado_em(entrada, anterior, hoje)
            novo[chave] = entrada
        manifestos.append((caminho, mapa, novo))
    # Apagar por chave também alcança caminhos antigos do mesmo arquivo.
    nomes = {f"{chave.replace(':', '-', 1)}.txt" for chave in chaves}
    for caminho in sorted((textos / "textos").rglob("*.txt")):
        if caminho.name in nomes:
            caminho.unlink()
    for caminho in sorted((textos / "trechos").rglob("*.jsonl")):
        linhas = caminho.read_text(encoding="utf-8").splitlines(keepends=True)
        novas = []
        for linha in linhas:
            try:
                trecho = json.loads(linha)
            except ValueError:
                trecho = None
            # Mesmo tratamento da fila: restos desconhecidos não são apagados às cegas.
            if not isinstance(trecho, dict) or trecho.get("arquivo") not in chaves:
                novas.append(linha)
        if novas != linhas:
            if novas:
                arquivos.gravar_atomico(caminho, "".join(novas))
            else:
                caminho.unlink()
    for caminho, anterior, novo in manifestos:
        if novo != anterior:
            arquivos.salvar_mapa(caminho, novo)
    return chaves
