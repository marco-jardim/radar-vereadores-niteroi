"""Texto de PDFs com `pdftotext -layout -enc UTF-8`, classificado por página.

O PDF inteiro é convertido numa chamada; as páginas são separadas pelo \\f que o
pdftotext grava ao fim de cada uma. Página com menos de `LIMIAR_UTEIS` caracteres
úteis (letras e dígitos) é considerada escaneada. Com `ocr=True`, só essas páginas
passam pelo OCR (`coletor.extratores.ocr`); as demais mantêm o texto do PDF.

Status: `ok` (todas as páginas com texto), `escaneado_sem_ocr` (há páginas
escaneadas e o OCR não foi pedido; o texto parcial é mantido), `ok_ocr` ou
`ocr_baixa_confianca` (conforme a confiança média), `pendente_ferramenta`
(pdftotext, pdftoppm, tesseract ou o idioma `por` ausente).

Somente biblioteca padrão do Python; as ferramentas rodam por subprocess, sem shell.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from . import ferramentas as _ferr
from . import ocr as _ocr
from .base import ErroFormato, FerramentaAusente, Resultado

LIMIAR_UTEIS = 100


def caracteres_uteis(texto: str) -> int:
    """Letras e dígitos do texto."""
    return sum(map(str.isalnum, texto))


def paginas_pdftotext(saida: str) -> list[str]:
    """Separa a saída do pdftotext em páginas (cada página termina com \\f)."""
    paginas = saida.split("\f")
    if paginas and not paginas[-1].strip():
        paginas.pop()
    return paginas


def extrair_pdf(dados: bytes, ocr: bool, ferramentas=None) -> Resultado:
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
            resultado.texto = "\n\n".join(paginas)
            resultado.status = "ok"
            return resultado
        if not ocr:
            resultado.texto = "\n\n".join(paginas)
            resultado.status = "escaneado_sem_ocr"
            return resultado
        try:
            _ocr.verificar(ferramentas, pdf=True)
        except FerramentaAusente as exc:
            resultado.texto = "\n\n".join(paginas)
            resultado.status, resultado.detalhe = "pendente_ferramenta", f"ferramenta ausente: {exc}"
            return resultado
        lidas = _ocr.ocr_paginas_pdf(arquivo, escaneadas, pasta, ferramentas)

    soma = 0.0
    palavras_total = 0
    for n, (texto, conf, palavras) in sorted(lidas.items()):
        if caracteres_uteis(texto) >= caracteres_uteis(paginas[n - 1]):
            paginas[n - 1] = texto
        if conf is not None and palavras:
            resultado.confianca_paginas[n] = round(conf, 2)
            soma += conf * palavras
            palavras_total += palavras
    resultado.texto = "\n\n".join(paginas)
    resultado.paginas_ocr = len(lidas)
    resultado.extrator = "pdftotext+tesseract"
    resultado.versao_extrator = f"{resultado.versao_extrator}+{_ferr.versao('tesseract', ferramentas) or ''}"
    if palavras_total:
        resultado.confianca = round(soma / palavras_total, 2)
    resultado.status = _ocr.status_ocr(resultado.confianca)
    return resultado
