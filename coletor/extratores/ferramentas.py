"""Execução das ferramentas externas (poppler e tesseract) por subprocess.

As ferramentas são chamadas com a lista de argumentos, sem shell, com stdin vazio
e tempo limite. O caminho vem de `shutil.which` ou do mapeamento `ferramentas`
passado a `extrair`: `{"pdftotext": "C:/.../pdftotext.exe"}`, `{"tesseract": None}`
(indisponível) ou uma lista de prefixo de comando (`[sys.executable, "falso.py"]`,
usada nos testes). Nomes ausentes do mapeamento são procurados no PATH.

Somente biblioteca padrão do Python.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence

from .base import ErroFerramenta, FerramentaAusente

NOMES = ("pdftotext", "pdftoppm", "tesseract")

# Tempo limite, em segundos, de cada chamada (um PDF inteiro no pdftotext; uma
# página no pdftoppm e no tesseract).
TIMEOUT_SEGUNDOS = {"pdftotext": 180, "pdftoppm": 180, "tesseract": 300}
TIMEOUT_VERSAO = 20

_ARGS_VERSAO = {"pdftotext": ["-v"], "pdftoppm": ["-v"], "tesseract": ["--version"]}
_RE_VERSAO = re.compile(r"(\d+\.\d+(?:\.\d+)?)")
_CRIACAO = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0

_cache_versoes: dict[tuple[str, ...], str] = {}
_cache_idiomas: dict[tuple[str, ...], tuple[str, ...]] = {}

Ferramentas = Mapping[str, "str | Sequence[str] | None"]


def resolver(nome: str, ferramentas: Ferramentas | None = None) -> list[str] | None:
    """Prefixo de comando da ferramenta, ou None se indisponível."""
    if ferramentas is not None and nome in ferramentas:
        valor = ferramentas[nome]
        if valor is None:
            return None
        if isinstance(valor, str):
            return [valor] if valor else None
        lista = [str(v) for v in valor]
        return lista or None
    caminho = shutil.which(nome)
    return [caminho] if caminho else None


def executar(
    nome: str,
    args: Sequence[str],
    ferramentas: Ferramentas | None = None,
    timeout: float | None = None,
    exigir_sucesso: bool = True,
) -> subprocess.CompletedProcess:
    """Executa a ferramenta com os argumentos dados; devolve stdout/stderr em bytes.

    FerramentaAusente se ela não existe; ErroFerramenta em tempo esgotado ou, com
    `exigir_sucesso`, código de saída diferente de zero.
    """
    prefixo = resolver(nome, ferramentas)
    if prefixo is None:
        raise FerramentaAusente(nome)
    limite = TIMEOUT_SEGUNDOS.get(nome, 120) if timeout is None else timeout
    try:
        resultado = subprocess.run(
            [*prefixo, *args],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=limite,
            check=False,
            shell=False,
            creationflags=_CRIACAO,
        )
    except FileNotFoundError as exc:
        raise FerramentaAusente(nome) from exc
    except PermissionError as exc:
        raise FerramentaAusente(f"{nome}: sem permissão de execução") from exc
    except subprocess.TimeoutExpired as exc:
        raise ErroFerramenta(f"{nome}: tempo esgotado após {limite} s") from exc
    if exigir_sucesso and resultado.returncode != 0:
        erro = resultado.stderr.decode("utf-8", "replace").strip().splitlines()
        resumo = erro[-1][:200] if erro else ""
        raise ErroFerramenta(f"{nome}: código {resultado.returncode} {resumo}".strip())
    return resultado


def versao(nome: str, ferramentas: Ferramentas | None = None) -> str | None:
    """Versão da ferramenta (como "25.07.0"), "desconhecida" ou None se ausente."""
    prefixo = resolver(nome, ferramentas)
    if prefixo is None:
        return None
    chave = tuple(prefixo)
    if chave in _cache_versoes:
        return _cache_versoes[chave]
    try:
        r = executar(nome, _ARGS_VERSAO.get(nome, ["--version"]), ferramentas,
                     timeout=TIMEOUT_VERSAO, exigir_sucesso=False)
    except FerramentaAusente:
        return None
    except ErroFerramenta:
        return "desconhecida"
    saida = (r.stdout + b"\n" + r.stderr).decode("utf-8", "replace")
    encontrada = "desconhecida"
    for linha in saida.splitlines():
        m = _RE_VERSAO.search(linha)
        if m:
            encontrada = m.group(1)
            break
    _cache_versoes[chave] = encontrada
    return encontrada


def idiomas_tesseract(ferramentas: Ferramentas | None = None) -> tuple[str, ...]:
    """Idiomas instalados do tesseract (`--list-langs`); vazio se indisponível."""
    prefixo = resolver("tesseract", ferramentas)
    if prefixo is None:
        return ()
    chave = tuple(prefixo)
    if chave in _cache_idiomas:
        return _cache_idiomas[chave]
    try:
        r = executar("tesseract", ["--list-langs"], ferramentas,
                     timeout=TIMEOUT_VERSAO, exigir_sucesso=False)
    except (FerramentaAusente, ErroFerramenta):
        return ()
    saida = (r.stdout + b"\n" + r.stderr).decode("utf-8", "replace")
    idiomas = []
    for linha in saida.splitlines():
        linha = linha.strip()
        if not linha or " " in linha or ":" in linha or "/" in linha or "\\" in linha:
            continue
        idiomas.append(linha)
    resultado = tuple(sorted(set(idiomas)))
    _cache_idiomas[chave] = resultado
    return resultado


def disponiveis(ferramentas: Ferramentas | None = None) -> dict:
    """Versões das ferramentas externas e idiomas do tesseract, sem caminhos locais."""
    info: dict = {nome: versao(nome, ferramentas) for nome in NOMES}
    info["tesseract_idiomas"] = list(idiomas_tesseract(ferramentas))
    return info
