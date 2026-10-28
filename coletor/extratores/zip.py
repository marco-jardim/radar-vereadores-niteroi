"""Texto de arquivos zip: cada membro passa por `extrair`, até 2 níveis de zip.

Proteção contra zip bomb: a soma dos tamanhos descompactados declarados no
diretório central é conferida antes de ler qualquer membro, e a leitura conta os
bytes realmente descompactados, com um orçamento único de
`LIMITE_DESCOMPACTADO` compartilhado pelos níveis aninhados. O texto final é a
concatenação dos membros, cada um precedido de `=== <nome do membro> ===`.

Somente biblioteca padrão do Python.
"""
from __future__ import annotations

import io
import zipfile
from collections.abc import Callable

from .base import VERSAO_EXTRATORES, ErroFormato, ErroLimite, Resultado, ler_membro_zip

PROFUNDIDADE_MAXIMA = 2

# Ordem de gravidade usada para o status agregado do zip.
_PRIORIDADE = ("pendente_ferramenta", "escaneado_sem_ocr", "ok_parcial", "ocr_baixa_confianca", "ok_ocr", "ok")
# Membros com texto: com algum deles, um membro escaneado sem OCR deixa o zip `ok_parcial`.
_COM_TEXTO = ("ok_parcial", "ocr_baixa_confianca", "ok_ocr", "ok")


def _nome_seguro(nome: str) -> str:
    return "".join(c for c in nome if c.isprintable()) or "(sem nome)"


def extrair_zip(dados: bytes, ocr: bool, ferramentas, profundidade: int, orcamento: list[int],
                extrair_membro: Callable[..., Resultado]) -> Resultado:
    """Extrai os membros; `extrair_membro(dados, ocr, ferramentas, profundidade, orcamento)`."""
    if profundidade > PROFUNDIDADE_MAXIMA:
        raise ErroFormato("zip aninhado além da profundidade máxima")
    try:
        zf = zipfile.ZipFile(io.BytesIO(dados))
    except (zipfile.BadZipFile, OSError, ValueError, EOFError) as exc:
        raise ErroFormato(f"zip inválido: {exc}") from exc
    resultado = Resultado(formato="zip", extrator="zip", versao_extrator=VERSAO_EXTRATORES)
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if sum(i.file_size for i in infos) > orcamento[0]:
            raise ErroLimite("zip recusado: tamanho descompactado acima do limite")
        secoes: list[str] = []
        status_membros: list[str] = []
        detalhes: list[str] = []
        confiancas: list[float] = []
        for info in infos:
            nome = _nome_seguro(info.filename)
            try:
                conteudo = ler_membro_zip(zf, info, orcamento)
            except ErroLimite:
                raise  # zip bomb: o arquivo inteiro é recusado
            except ErroFormato as exc:
                status_membros.append("erro_formato")
                detalhes.append(f"{nome}: {exc}")
                continue
            membro = extrair_membro(conteudo, ocr, ferramentas, profundidade + 1, orcamento)
            status_membros.append(membro.status)
            if membro.detalhe:
                detalhes.append(f"{nome}: {membro.detalhe}")
            resultado.paginas += membro.paginas
            resultado.paginas_ocr += membro.paginas_ocr
            resultado.cabecalhos_omitidos += membro.cabecalhos_omitidos
            if membro.confianca is not None:
                confiancas.append(membro.confianca)
            if membro.texto:
                secoes.append(f"=== {nome} ===\n{membro.texto}")
    resultado.texto = "\n\n".join(secoes)
    resultado.detalhe = "; ".join(detalhes)
    if confiancas:
        resultado.confianca = round(sum(confiancas) / len(confiancas), 2)
    for status in _PRIORIDADE:
        if status in status_membros:
            resultado.status = status
            break
    else:
        if status_membros and all(s == "erro_formato" for s in status_membros):
            resultado.status = "erro_formato"
        else:
            resultado.status = "vazio_legitimo"
    if resultado.status == "escaneado_sem_ocr" and any(s in _COM_TEXTO for s in status_membros):
        resultado.status = "ok_parcial"
    return resultado
