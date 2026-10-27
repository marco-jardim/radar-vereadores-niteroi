"""Exceções, constantes e utilidades comuns dos extratores de texto.

Somente biblioteca padrão do Python.
"""
from __future__ import annotations

import zipfile
import zlib
from dataclasses import dataclass, field

# Versão dos extratores escritos em Python puro (docx, doc, rtf, html, zip, texto).
# Mudar a saída de qualquer um deles exige subir esta versão, para reprocessar.
VERSAO_EXTRATORES = "2"

# Limite de bytes descompactados por arquivo zip/docx (proteção contra zip bomb).
LIMITE_DESCOMPACTADO = 100 * 1024 * 1024

# Confiança média mínima do OCR (0–100) para o status `ok_ocr`.
CONFIANCA_MINIMA = 60.0

STATUS = (
    "ok",
    "ok_ocr",
    "ocr_baixa_confianca",
    "escaneado_sem_ocr",
    "pendente_ferramenta",
    "vazio_legitimo",
    "erro_formato",
)


@dataclass
class Resultado:
    """Resultado da extração de um arquivo.

    - `formato`: formato detectado pelos magic bytes (`pdf`, `docx`, `doc`, ...);
    - `texto`: texto normalizado (`coletor.trechos.normalizar`);
    - `extrator`/`versao_extrator`: ferramenta e versão que produziram o texto
      (por exemplo `pdftotext`/`25.07.0`, `pdftotext+tesseract`/`25.07.0+5.5.3` ou
      `docx`/`VERSAO_EXTRATORES`); vazio quando nada foi executado;
    - `paginas`: páginas do PDF (1 para imagens; soma dos membros num zip);
    - `paginas_ocr`: quantas páginas passaram por OCR;
    - `paginas_escaneadas`: páginas (base 1) com menos de 100 caracteres úteis no
      texto do PDF, candidatas ao OCR;
    - `confianca`: confiança média do OCR (0–100, ponderada pelas palavras) ou None;
    - `confianca_paginas`: confiança por página com OCR;
    - `status`: um de `STATUS`; `detalhe`: motivo legível de erro, pendência ou aviso;
    - `cabecalhos_omitidos`: partes de cabeçalho/rodapé (docx) ou histórias de
      cabeçalho (doc) que existiam no arquivo e ficaram fora do texto.

    No PDF, as páginas do texto ficam separadas por uma linha só com \\f.
    """

    formato: str
    texto: str = ""
    extrator: str = ""
    versao_extrator: str = ""
    paginas: int = 0
    paginas_ocr: int = 0
    confianca: float | None = None
    status: str = "ok"
    paginas_escaneadas: list[int] = field(default_factory=list)
    confianca_paginas: dict[int, float] = field(default_factory=dict)
    detalhe: str = ""
    cabecalhos_omitidos: int = 0


class ErroFormato(ValueError):
    """Arquivo malformado, truncado, criptografado ou fora do formato esperado."""


class ErroLimite(ErroFormato):
    """Limite de bytes descompactados excedido (zip bomb): o arquivo inteiro é recusado."""


class FerramentaAusente(RuntimeError):
    """Ferramenta externa (pdftotext, pdftoppm, tesseract ou idioma) indisponível."""


class ErroFerramenta(RuntimeError):
    """Ferramenta externa terminou com erro ou estourou o tempo limite."""


def ler_membro_zip(zf: zipfile.ZipFile, info: zipfile.ZipInfo, orcamento: list[int]) -> bytes:
    """Lê um membro de zip sem passar do tamanho declarado nem do orçamento restante.

    `orcamento` é uma lista de um elemento com os bytes ainda permitidos, compartilhada
    entre os níveis de um zip aninhado; é decrementada a cada leitura.
    """
    if info.flag_bits & 0x1:
        raise ErroFormato(f"membro criptografado: {info.filename}")
    if info.file_size > orcamento[0]:
        raise ErroLimite("limite de bytes descompactados excedido")
    partes: list[bytes] = []
    lidos = 0
    try:
        with zf.open(info) as f:
            while True:
                bloco = f.read(1024 * 1024)
                if not bloco:
                    break
                lidos += len(bloco)
                if lidos > info.file_size or lidos > orcamento[0]:
                    raise ErroLimite("limite de bytes descompactados excedido")
                partes.append(bloco)
    except (zipfile.BadZipFile, zlib.error, EOFError, OSError, NotImplementedError) as exc:
        raise ErroFormato(f"membro ilegível {info.filename}: {exc}") from exc
    orcamento[0] -= lidos
    return b"".join(partes)
