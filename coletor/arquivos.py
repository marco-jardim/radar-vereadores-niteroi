"""Gravação dos arquivos de dados versionados em data/.

Formato compacto "um registro por linha": cada elemento de uma lista (ou cada
par chave/valor de um mapa) ocupa exatamente uma linha, serializado sem espaços
e com chaves ordenadas. O arquivo continua sendo JSON válido, lido com json.load,
mas fica menor e os diffs do Git mostram só os registros que mudaram.

A gravação é atômica: escreve num temporário da mesma pasta e troca com os.replace.
No Windows, a troca falha com PermissionError enquanto outro processo (antivírus,
indexador, editor) segura o destino aberto; por isso ela é tentada de novo algumas vezes.

Uso: python -m coletor.arquivos --reformatar
  Regrava data/proposicoes/*.json e data/classificacao_ia.json no formato compacto,
  sem coletar nada, conferindo antes que o conteúdo continua idêntico.
Somente biblioteca padrão do Python.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import tempfile
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent
DIR_DADOS = RAIZ / "data" / "proposicoes"
CACHE_IA = RAIZ / "data" / "classificacao_ia.json"
TENTATIVAS_TROCA = 5  # tentativas de os.replace diante de PermissionError (Windows)
ESPERA_TROCA = 0.05  # segundos antes da tentativa seguinte, multiplicados pelo número dela


# ------------------------------------------------------------------- serialização
def _compacto(valor: Any) -> str:
    """Uma linha de JSON: sem espaços, chaves ordenadas e acentos sem escape."""
    return json.dumps(valor, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _chave(chave: Any) -> str:
    """Converte a chave do mapa para texto, como o json faria com inteiros."""
    if isinstance(chave, str):
        return chave
    if isinstance(chave, int) and not isinstance(chave, bool):
        return str(chave)
    raise TypeError(f"chave de mapa não suportada: {chave!r}")


def texto_lista(registros: Iterable[Any]) -> str:
    """Lista JSON com um registro por linha, na ordem recebida."""
    linhas = [_compacto(r) for r in registros]
    if not linhas:
        return "[]\n"
    return "[\n" + ",\n".join(linhas) + "\n]\n"


def texto_mapa(mapa: dict) -> str:
    """Objeto JSON com um par "chave":valor por linha, ordenado pela chave."""
    pares = {_chave(k): v for k, v in mapa.items()}
    if len(pares) != len(mapa):
        raise ValueError("chaves duplicadas depois da conversão para texto")
    if not pares:
        return "{}\n"
    linhas = [f"{_compacto(k)}:{_compacto(pares[k])}" for k in sorted(pares)]
    return "{\n" + ",\n".join(linhas) + "\n}\n"


def texto_json(obj: Any) -> str:
    """JSON indentado para arquivos pequenos, como data/meta.json."""
    return json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True, default=str) + "\n"


# ----------------------------------------------------------------------- gravação
def _trocar(origem: str, destino: Path) -> None:
    """os.replace com novas tentativas, e espera crescente, só para PermissionError.

    Outros erros (disco cheio, caminho inválido) sobem na primeira vez; na última
    tentativa, o PermissionError também sobe.
    """
    for tentativa in range(1, TENTATIVAS_TROCA + 1):
        try:
            os.replace(origem, destino)
            return
        except PermissionError:
            if tentativa == TENTATIVAS_TROCA:
                raise
            time.sleep(ESPERA_TROCA * tentativa)


def gravar_atomico(caminho: str | os.PathLike, texto: str) -> None:
    """Grava em UTF-8 com quebras de linha "\\n", trocando o arquivo de uma vez.

    Quem lê durante a gravação vê o conteúdo antigo ou o novo, nunca um JSON pela
    metade; numa falha, o temporário é apagado e o original fica intacto.
    """
    destino = Path(caminho)
    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        modo = destino.stat().st_mode & 0o777
    except FileNotFoundError:
        modo = 0o644
    # sufixo .tmp: o temporário nunca casa com os globs "*.json" dos leitores
    fd, temporario = tempfile.mkstemp(dir=destino.parent, prefix=f".{destino.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(texto)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(temporario, modo)
        _trocar(temporario, destino)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporario)
        raise


def salvar_lista(caminho: str | os.PathLike, registros: Iterable[Any]) -> None:
    """Grava uma lista JSON com um registro por linha (data/proposicoes/<ano>.json)."""
    gravar_atomico(caminho, texto_lista(registros))


def salvar_mapa(caminho: str | os.PathLike, mapa: dict) -> None:
    """Grava um objeto JSON com uma chave por linha (data/classificacao_ia.json)."""
    gravar_atomico(caminho, texto_mapa(mapa))


def salvar_json(caminho: str | os.PathLike, obj: Any) -> None:
    """Grava JSON pequeno com indent=1, chaves ordenadas e quebra de linha final."""
    gravar_atomico(caminho, texto_json(obj))


# ------------------------------------------------------------------- reformatação
def _preparar(caminho: Path, formatar: Callable[[Any], str], tipo: type) -> tuple[str, bytes]:
    """Lê o arquivo, gera o texto novo e confere que o conteúdo é o mesmo."""
    bruto = caminho.read_bytes()
    original = json.loads(bruto.decode("utf-8"))
    if not isinstance(original, tipo):
        raise ValueError(f"{caminho}: esperado {tipo.__name__}, encontrado {type(original).__name__}")
    novo = formatar(original)
    if json.loads(novo) != original:
        raise ValueError(f"{caminho}: o conteúdo reformatado difere do original")
    return novo, bruto


def reformatar(dir_dados: str | os.PathLike = DIR_DADOS, cache_ia: str | os.PathLike = CACHE_IA) -> list[dict]:
    """Regrava os arquivos de dados no formato compacto, sem alterar o conteúdo.

    Confere todos os arquivos antes de gravar qualquer um: se algum diferir do
    original depois de reformatado, levanta ValueError e nada é alterado.
    """
    alvos: list[tuple[Path, Callable[[Any], str], type]] = [
        (arq, texto_lista, list) for arq in sorted(Path(dir_dados).glob("*.json"))
    ]
    if Path(cache_ia).exists():
        alvos.append((Path(cache_ia), texto_mapa, dict))
    preparados = [(caminho, *_preparar(caminho, formatar, tipo)) for caminho, formatar, tipo in alvos]
    relatorio = []
    for caminho, novo, bruto in preparados:
        gravar_atomico(caminho, novo)
        relatorio.append(
            {
                "arquivo": caminho,
                "bytes_antes": len(bruto),
                "bytes_depois": len(novo.encode("utf-8")),
                "linhas_antes": bruto.count(b"\n"),
                "linhas_depois": novo.count("\n"),
            }
        )
    return relatorio


def _rotulo(caminho: Path) -> str:
    try:
        return caminho.resolve().relative_to(RAIZ).as_posix()
    except ValueError:
        return str(caminho)


def _variacao(antes: int, depois: int) -> str:
    return f"{100 * (depois - antes) / antes:+.1f}%" if antes else "n/d"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--reformatar",
        action="store_true",
        help="regrava data/proposicoes/*.json e data/classificacao_ia.json no formato compacto",
    )
    args = ap.parse_args()
    if not args.reformatar:
        ap.error("nada a fazer: use --reformatar")
    try:
        relatorio = reformatar()
    except (ValueError, TypeError) as e:
        print(f"::error::reformatação abortada, nenhum arquivo alterado: {e}", file=sys.stderr)
        sys.exit(1)
    if not relatorio:
        print("nenhum arquivo de dados encontrado", file=sys.stderr)
        return
    for r in relatorio:
        print(
            f"{_rotulo(r['arquivo'])}: {r['bytes_antes']:,} -> {r['bytes_depois']:,} bytes "
            f"({_variacao(r['bytes_antes'], r['bytes_depois'])}), "
            f"{r['linhas_antes']:,} -> {r['linhas_depois']:,} linhas"
        )
    antes = sum(r["bytes_antes"] for r in relatorio)
    depois = sum(r["bytes_depois"] for r in relatorio)
    print(f"total: {antes:,} -> {depois:,} bytes ({_variacao(antes, depois)})")


if __name__ == "__main__":
    main()
