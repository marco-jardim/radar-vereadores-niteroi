"""Texto de PDFs com `pdftotext -layout -enc UTF-8`, classificado por página.

O PDF inteiro é convertido numa chamada; as páginas são separadas pelo \\f que o
pdftotext grava ao fim de cada uma. Página com menos de `LIMIAR_UTEIS` caracteres
úteis (letras e dígitos) é considerada escaneada. Com `ocr=True`, só essas páginas
passam pelo OCR (`coletor.extratores.ocr`); as demais mantêm o texto do PDF.

Status: `ok` (todas as páginas com texto), `escaneado_sem_ocr` (há páginas
escaneadas e o OCR não foi pedido, falhou em alguma página ou passou do orçamento
por documento; o texto parcial é mantido e `detalhe` lista as páginas), `ok_ocr` ou
`ocr_baixa_confianca` (conforme a confiança média), `pendente_ferramenta`
(pdftotext, pdftoppm, tesseract ou o idioma `por` ausente).

Somente biblioteca padrão do Python; as ferramentas rodam por subprocess, sem shell.
"""
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from . import ferramentas as _ferr
from . import ocr as _ocr
from .base import ErroFormato, FerramentaAusente, Resultado

LIMIAR_UTEIS = 100
# As páginas ficam separadas por uma linha só com \f (preservada pela normalização),
# para a limpeza de cabeçalhos e rodapés por página.
SEPARADOR = "\n\f\n"


def caracteres_uteis(texto: str) -> int:
    """Letras e dígitos do texto."""
    return sum(map(str.isalnum, texto))


def paginas_pdftotext(saida: str) -> list[str]:
    """Separa a saída do pdftotext em páginas (cada página termina com \\f)."""
    paginas = saida.split("\f")
    if paginas and not paginas[-1].strip():
        paginas.pop()
    return paginas


def extrair_pdf(dados: bytes, ocr: bool, ferramentas=None, cache_ocr: Path | None = None) -> Resultado:
    """Texto do PDF por página; `cache_ocr` guarda o OCR de cada página (veja `ocr`)."""
    resultado = Resultado(formato="pdf", extrator="pdftotext")
    with tempfile.TemporaryDirectory(prefix="radar-pdf-", ignore_cleanup_errors=True) as nome_pasta:
        pasta = Path(nome_pasta)
        arquivo = pasta / "entrada.pdf"
        arquivo.write_bytes(dados)
        try:
            saida = _ferr.executar("pdftotext", ["-layout", "-enc", "UTF-8", str(arquivo), "-"],
                                   ferramentas)
        except FerramentaAusente as exc:
            resultado.status, resultado.detalhe = "pendente_ferramenta", f"ferramenta ausente: {exc}"
            return resultado
        paginas = paginas_pdftotext(saida.stdout.decode("utf-8", "replace"))
        if not paginas:
            raise ErroFormato("PDF sem páginas legíveis")
        resultado.versao_extrator = _ferr.versao("pdftotext", ferramentas) or ""
        resultado.paginas = len(paginas)
        escaneadas = [i + 1 for i, p in enumerate(paginas) if caracteres_uteis(p) < LIMIAR_UTEIS]
        resultado.paginas_escaneadas = escaneadas
        if not escaneadas:
            resultado.texto = SEPARADOR.join(paginas)
            resultado.status = "ok"
            return resultado
        if not ocr:
            resultado.texto = SEPARADOR.join(paginas)
            resultado.status = "escaneado_sem_ocr"
            return resultado
        try:
            _ocr.verificar(ferramentas, pdf=True)
        except FerramentaAusente as exc:
            resultado.texto = SEPARADOR.join(paginas)
            resultado.status, resultado.detalhe = "pendente_ferramenta", f"ferramenta ausente: {exc}"
            return resultado
        lido = _ocr.ocr_paginas_pdf(arquivo, escaneadas, pasta, ferramentas, cache_ocr,
                                    hashlib.sha256(dados).hexdigest() if cache_ocr is not None else None)

    # A confiança só considera as páginas cujo texto do OCR foi usado, isto é, que
    # trouxe mais caracteres úteis que o texto embutido no PDF.
    soma = 0.0
    palavras_total = 0
    for n, (texto, conf, palavras) in sorted(lido.lidas.items()):
        if caracteres_uteis(texto) <= caracteres_uteis(paginas[n - 1]):
            continue
        paginas[n - 1] = texto
        if conf is not None and palavras:
            resultado.confianca_paginas[n] = round(conf, 2)
            soma += conf * palavras
            palavras_total += palavras
    resultado.texto = SEPARADOR.join(paginas)
    resultado.paginas_ocr = len(lido.lidas)
    resultado.extrator = "pdftotext+tesseract"
    resultado.versao_extrator = f"{resultado.versao_extrator}+{_ferr.versao('tesseract', ferramentas) or ''}"
    if palavras_total:
        resultado.confianca = round(soma / palavras_total, 2)
    pendencias = _ocr.descrever_pendencias(lido)
    if pendencias:
        resultado.status, resultado.detalhe = "escaneado_sem_ocr", pendencias
    else:
        resultado.status = _ocr.status_ocr(resultado.confianca)
    return resultado
