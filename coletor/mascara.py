"""Máscara de dados pessoais (LGPD) no texto pesquisável.

Regras de `mascarar`:
- **CPF** é mascarado sempre, de qualquer pessoa, com ou sem pontuação, mas só
  quando os dígitos verificadores são válidos. Entre os grupos 3-3-3-2 vale um
  separador por intervalo: ".", " ", "/", "-" (com espaço opcional de cada lado) ou
  nenhum, como em "123.456 789-09" (OCR). Com espaço como separador, uma fatia
  3-3-3-2 colada a outros números por espaço ("1 529 982 247 25 7", colunas de
  tabela) não é CPF, salvo com rótulo. Com o rótulo "CPF" ("cpf", "c.p.f.",
  "CPF/MF", "CPF nº", "CPF:") até `JANELA_ROTULO_CPF` caracteres antes, o número é
  mascarado mesmo com DV inválido (erros de OCR), e as proteções gerais não valem.
- **RG** é mascarado quando o rótulo "RG" ou "R.G." aparece até 20 caracteres antes
  do número; "identidade" só vale como rótulo seguido de "nº"/"n."/":" ou precedido
  de "carteira"/"cédula" (evita "identidade de gênero, Lei 13.709/2018"); variantes de
  OCR ("Identdede", "Idenlidade") valem como "identidade". Número de 11 dígitos com DV
  de CPF válido depois desses rótulos é mascarado como CPF.
- **Documentos pessoais** (CNH, RENACH, título de eleitor, PIS/PASEP, NIS, NIT,
  passaporte, CTPS/carteira de trabalho, cartão SUS/CNS) são mascarados como
  `[documento omitido]` quando o rótulo aparece até 20 caracteres antes do número.
- **Telefones** brasileiros (fixos e celulares, com ou sem DDD, com +55, colados a
  "/", "," ou "." como em `Tel.2620-1234` ou `2620-1234/2620-5678`) e **e-mails** são
  mascarados, exceto os liberados: contatos oficiais de vereadores e suplentes
  (`contatos` em `config/perfis.json`), contatos institucionais
  (`contatos_institucionais` em `config/backend.json`) e os domínios
   públicos `gov.br`, `jus.br`, `leg.br`, `mp.br`, `def.br` e `mil.br`, com subdomínios.
   E-mails com separador corrompido pelo OCR (`(D`, `(OD`, `(Q`, `(0D`, `(@`, `©`,
   `@ ` e `O` antes de provedor conhecido) também são mascarados em qualquer página;
   Também entram tokens terminados em provedores de webmail (incluindo erros como
   gmai/grnail, hotmall/hotmai e yahõo/y ahoo), separadores gráficos ou maiúscula
   entre minúsculas colados a um domínio, e domínios sem @ até 25 caracteres depois
   de e-mail/email/e mail/correio eletrônico ou contato. Provedor separado por um
   espaço inclui o token local anterior, nunca um rótulo. Essas regras adicionais
   preservam URLs, www e atributos XML. Um endereço entre <…>, como nos cabeçalhos
   de e-mail impressos, não é uma tag: o conteúdo deve ser um token com ponto e
   forma de e-mail, sem espaços, aspas, = ou /. A liberação tenta endereços reconstruídos
   com @ e provedores corrigidos, sem alterar o texto visível.
   Celulares admitem ponto ou espaço depois do 9 (`21-9.8115-0243`). Listas de três
   ou mais números de quatro dígitos separados por vírgula/`e` não são telefones,
   inclusive quando falta uma vírgula entre dois itens. Dois itens com vírgula
   também não são telefone.
  Números de 8 dígitos começando por 6–9 (celulares antigos) exigem hífen, DDD ou
  rótulo; separados por ponto (9999.9999, como códigos de programa orçamentário) e
  dígitos corridos (mesmo com um "DDD" colado, como em números de tabela) só com rótulo
  (tel, fone, cel, celular, whatsapp, wa.me, contato,
  fax) até 25 caracteres antes. Números dentro de endereços web (exceto WhatsApp; o
  endereço continua por até 3 pedaços separados por espaço simples ou por uma quebra de
  linha quando a diagramação o quebrou em "/"),
  marcação XML/HTML, GUIDs e carimbos ISO de data e hora não são mascarados, para não
  corromper links e metadados (e-mail e CPF formatado são mascarados sempre).

Não são mascarados (proteções contra falso positivo): CEP, CNPJ, processo no padrão
CNJ, número SEI (só nos formatos do SEI logo depois da sigla), matrícula funcional,
valores em R$, datas, intervalos de anos (inclusive "1865-1950", entre 1500 e 2100 e em
ordem), decimais ("1,04712345678", "1.234,5", "1.04712345678"), DOIs ("10.1590/…"),
valores numéricos de células de planilha (<v>, <t>, <f>) e, para telefones e RG,
números precedidos
de lei, decreto, processo, protocolo, e-SIC, ouvidoria e afins (até 3 espaços entre a palavra, o "nº" e
o número, na mesma linha). Um número de 11 dígitos sem DV de CPF
válido não é CPF. CPF formatado (000.000.000-00) com DV válido é mascarado mesmo
dentro dessas proteções.

`mascarar` é idempotente e devolve a contagem por tipo.
Com `ocr_paginas` (base 1; linha só com \\f separa páginas), aplica depois das regras
normais uma máscara de números de 8+ dígitos, inclusive com separadores e uma letra
de ruído entre grupos. Preserva datas, moeda, CEP rotulado, atos com número/ano,
intervalos de anos, listas de documentos de quatro dígitos e contatos liberados.
A barreira recebe as mesmas páginas e aponta resíduos numéricos como `numero` forte.

`varrer` é a barreira antes de gravar ou carregar textos: um detector independente e
mais amplo, que não usa as regras de `mascarar`. Procura qualquer sequência de 11
dígitos (com separadores) com DV de CPF válido, qualquer número com forma de telefone
(`\\d{4,5}[ .-]?\\d{4}`, inclusive 9 separado por ponto/espaço, com DDD/+55
opcionais) e qualquer endereço com "@" ou os separadores OCR acima, além do
RG rotulado. Ignora só o que casa com as proteções explícitas de datas (inclusive
intervalos de anos), listas de documentos de quatro dígitos, CEP, CNPJ com DV válido,
processo CNJ, "Lei nº …" e valores em R$. Pode apontar falsos positivos (por exemplo,
protocolos com forma de telefone):
quem chama decide. Passe a `varrer` o mesmo conjunto `liberados` usado em `mascarar`.
Devolve só tipo, posição e força (`forte`, critérios em `varrer`), nunca o valor; a
barreira bloqueia nas ocorrências fortes.

Uso: python -m coletor.mascara --medir DIR [--limite N]
  Mascara cada .txt de DIR e imprime, em JSON, quantas ocorrências `varrer` ainda acha
  (por tipo, fortes e fracas) e quantos documentos têm cada uma; não imprime valores.

Somente biblioteca padrão do Python.
"""
from __future__ import annotations

import argparse
import bisect
import json
import re
import sys
import unicodedata
from collections.abc import Iterable, Iterator
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# Mudar qualquer regra de `mascarar` muda os textos gravados: suba esta versão.
VERSAO_MASCARA = "6"
TIPOS = ("cpf", "rg", "telefone", "email", "documento", "numero")
SUBSTITUICOES = {
    "cpf": "[CPF omitido]",
    "rg": "[RG omitido]",
    "telefone": "[telefone omitido]",
    "email": "[e-mail omitido]",
    "documento": "[documento omitido]",
    "numero": "[número omitido]",
}
# Documentos pessoais mascarados quando o rótulo aparece até 20 caracteres antes do número.
ROTULOS_DOCUMENTO = (
    "cnh", "renach", "título de eleitor", "titulo de eleitor", "título eleitoral", "titulo eleitoral",
    "pis/pasep", "pis", "pasep", "nis", "nit", "passaporte", "ctps", "carteira de trabalho",
    "cartão do sus", "cartao do sus", "cartão sus", "cartao sus", "cns",
)
DOMINIOS_LIBERADOS = ("gov.br", "jus.br", "leg.br", "mp.br", "def.br", "mil.br")

DDDS = frozenset(
    [11, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 24, 27, 28, 31, 32, 33, 34, 35, 37, 38,
     41, 42, 43, 44, 45, 46, 47, 48, 49, 51, 53, 54, 55, 61, 62, 63, 64, 65, 66, 67, 68, 69,
     71, 73, 74, 75, 77, 79, 81, 82, 83, 84, 85, 86, 87, 88, 89, 91, 92, 93, 94, 95, 96, 97,
     98, 99]
)

# Número opcional depois de uma palavra: "nº", "n.", "número", ":" — sem \s* encadeados,
# para não haver retrocesso quadrático em linhas com muitos espaços (saída -layout).
_NUMERO = r"\s*(?:(?:[Nn][º°Oo]?|[Nn][ÚúUu]mero)\.?\s*)?(?:[:.]\s*)?"
# Versão curta, para "número logo depois da palavra": no máximo 3 espaços ou tabulações
# em cada trecho e nunca quebra de linha, para que uma palavra de outra linha ou de
# outra coluna (saída -layout) não proteja um telefone.
_NUMERO_CURTO = r"[ \t]{0,3}(?:(?:[Nn][º°Oo]?|[Nn][ÚúUu]mero)\.?[ \t]{0,3})?(?:[:.][ \t]{0,3})?"

# Desempenho: os padrões que varrem o texto inteiro começam por uma classe de caracteres
# ou um literal (o `re` então pula em C até os candidatos); os lookbehinds de borda vêm
# depois do primeiro caractere, como `\d(?<!\d\d)` no lugar de `(?<!\d)\d`.

# ---------------------------------------------------------------- padrões de mascarar
_RE_EMAIL = re.compile(
    r"(?<![\w.%+-])[A-Za-z0-9][A-Za-z0-9._%+-]*@"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,}(?![\w-])"
)
_RE_EMAIL_COMPLETO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Separadores OCR inequívocos; O solto só diante de provedores conhecidos. O TLD
# precisa ser reconhecível (ccTLD de duas letras ou um dos genéricos abaixo).
_PROVEDORES_EMAIL = r"gmail|hotmail|yahoo|outlook|live|uol|bol|terra|icloud|globo|ig"
_RE_EMAIL_OCR = re.compile(
    r"(?<![\w.%+-])(?P<local>[A-Za-z0-9][A-Za-z0-9._%+-]*?)"
    rf"(?:\((?:0?[Dd]|[Oo][Dd]|[Qq]|@)|©|@[ \t]+|O(?=(?i:{_PROVEDORES_EMAIL})\.))[ \t]*"
    r"(?P<dominio>(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+"
    r"(?i:com|org|net|edu|gov|mil|int|info|biz|name|pro|coop|aero|museum|"
    r"app|dev|tech|online|site|xyz|[a-z]{2}))(?![\w-]|\.[A-Za-z0-9])"
)
# Regras adicionais do corpus OCR: a busca por provedor começa no domínio, para
# aceitar separadores arbitrários sem retrocesso sobre todo o endereço.
_PROVEDORES_OCR = (
    ("gmail", ("gmail", "gmai", "grnail")),
    ("hotmail", ("hotmail", "hotmall", "hotmai")),
    ("yahoo", ("yahoo", "yahõo")),
    *((p, (p,)) for p in ("outlook", "live", "msn", "uol", "bol", "terra", "icloud", "globo", "ig")),
)


def _padrao_provedores_ocr() -> str:
    """Admite um único espaço em qualquer posição interna do nome do provedor."""
    ramos = []
    for canonico, variantes in _PROVEDORES_OCR:
        formas = []
        for variante in variantes:
            formas.append(re.escape(variante))
            formas.extend(re.escape(variante[:i]) + " " + re.escape(variante[i:])
                          for i in range(1, len(variante)))
        inicial = variantes[0][0]
        # O primeiro caractere é consumido fora de re.I, para o motor pular
        # rapidamente texto sem provedores (inclusive linhas -layout extensas).
        restos = [forma[1:] for forma in formas]
        ramos.append(rf"(?P<{canonico}>(?<=[{inicial.upper()}{inicial.lower()}])(?i:{'|'.join(restos)}))")
    return "|".join(ramos)


_RE_PROVEDOR_OCR = re.compile(
    rf"[GgHhYyOoLlMmUuBbTtIi](?:{_padrao_provedores_ocr()}) ?"
    r"(?P<sufixo>(?i:\.com(?:\.br)?))(?![\w-]|\.[A-Za-z0-9])")
_DOMINIO_OCR = r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+(?i:com|org|net|br)"
_RE_DOMINIO_OCR = re.compile(_DOMINIO_OCR + r"(?![\w-]|\.[A-Za-z0-9])")
_RE_EMAIL_COLADO = re.compile(
    r"(?<![\w._-])(?P<local>[A-Za-z0-9._-]{3,320}?)"
    r"(?:[()&|?©]|(?<=[a-z])[A-Z](?=[a-z]))"
    r"(?P<resto>[A-Za-z0-9()&|?© \t]{0,2}" + _DOMINIO_OCR + r")(?![\w-]|\.[A-Za-z0-9])")
_RE_ROTULO_EMAIL = re.compile(
    r"(?<![\w@._%+-])(?:e[- ]?mail|correio eletr[oô]nico|contato)(?![\w@._%+-])", re.I)
_RE_TOKEN_EMAIL = re.compile(r"[^\s<>\"';,\[\]{}]+")
_RE_WEB_EMAIL = re.compile(r"(?:https?://|www\.)[^\s<>\"']+", re.I)
_RE_LOCAL_EMAIL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._%+-]*")
_RE_RUIDO_EMAIL = re.compile(r"[()&|?©@\s]|(?<=[a-z])[A-Z](?=[a-z])")
_RE_EMAIL_ANGULOS = re.compile(r'''<[^\s<>="'/]+>''')
# Um separador por intervalo entre os grupos 3-3-3-2: ".", " ", "/", "-" (com espaço
# opcional de cada lado) ou nenhum.
_SEP_CPF = r"(?: ?- ?|[. /])?"
_RE_CPF = re.compile(
    rf"(?P<a>\d)(?<!\d\d)(?<!\d[.,/-]\d)(?P<b>\d\d)(?P<s1>{_SEP_CPF})(?P<c>\d{{3}})"
    rf"(?P<s2>{_SEP_CPF})(?P<d>\d{{3}})(?P<s3>{_SEP_CPF})(?P<e>\d{{2}})(?!\d)(?![.,/-]\d)"
)
# Rótulo de CPF ("cpf", "c.p.f.", "cpf/mf", "cpf nº", "cpf:") no texto dobrado.
JANELA_ROTULO_CPF = 15
_RE_ROTULO_CPF = re.compile(r"(?<![a-z0-9])c\.? ?p\.? ?f(?![a-z])")
_RE_CPF_PARTIDO = re.compile(r"\d(?<!\d\d) \d{2}\.\d{3}\.\d{3}-\d{2}(?!\d)")
_RE_CPF_ASSINATURA = re.compile(
    r"\b(?P<nome>[^\W\d_]{3,}):[ \t\r\n]*(?P<numero>\d{6,}(?: \d{1,5}(?![\d/]))?)")
_RE_ASSINATURA_DIGITAL = re.compile(r"assinado\s+de\s+forma\s+digital|digitalmente", re.I)
_RE_RG = re.compile(
    r"(?P<rotulo>[RrIi](?<![\w.][RrIi])"
    # "identidade" e erros comuns de OCR ("Identdede", "Idenlidade"): iden…d…
    r"(?:(?<=[Rr])(?:\.\s?[Gg]\.?|[Gg])|(?<=[Ii])[Dd][Ee][Nn][^\W\d_]{1,4}[Dd][^\W\d_]{0,3}))(?![\w])"
    r"(?P<meio>[^\d\n\[\]]{0,20}?)"
    r"(?P<numero>\d[\d.\-]{3,15}[\dXx])(?!\d)"
)
_RE_MARCA_IDENTIDADE = re.compile(r"\s*(?:n[º°o]?\.|nº|n°|:)", re.I)


def _sem_caixa(texto: str) -> str:
    """Padrão sem diferenciar maiúsculas, sem re.I (que impede o `re` de pular até os
    candidatos): cada letra vira [Aa]; espaço vira \\s+."""
    partes = []
    for c in texto:
        if c == " ":
            partes.append(r"\s+")
        elif c.isalpha():
            partes.append(f"[{c.upper()}{c.lower()}]")
        else:
            partes.append(re.escape(c))
    return "".join(partes)


def _padrao_documento() -> str:
    por_inicial: dict[str, list[str]] = {}
    for rotulo in sorted(ROTULOS_DOCUMENTO, key=lambda r: (-len(r), r)):
        por_inicial.setdefault(rotulo[0], []).append(_sem_caixa(rotulo[1:]))
    iniciais = "".join(sorted({c.upper() + c.lower() for c in por_inicial}))
    ramos = "|".join(f"(?<=[{c.upper()}{c.lower()}])(?:{'|'.join(resto)})"
                     for c, resto in sorted(por_inicial.items()))
    return (rf"(?P<rotulo>[{iniciais}](?<![\w.][{iniciais}])(?:{ramos}))(?![\w])"
            r"(?P<meio>[^\d\n\[\]]{0,20}?)"
            r"(?P<numero>(?:[A-Za-z]{1,2}[- ]?)?\d[\d.\-/ ]{3,23}\d)(?![\d\w])")


# Números de documentos pessoais (CNH, título de eleitor, PIS, passaporte, CTPS, cartão
# SUS…) com o rótulo até 20 caracteres antes; o número tem ao menos 5 dígitos.
_RE_DOCUMENTO = re.compile(_padrao_documento())
_RE_ONZE_DIGITOS = re.compile(r"\d(?<!\d\d)\d{10}(?!\d)")
_RE_ROTULO_CNH = re.compile(r"\b(?:habilita[cç][aã]o|cnh|registro)\b", re.I)
_RE_TELEFONE = re.compile(
    r"(?<![\w@+])(?<!\d-)"
    r"(?:(?P<pais>\+ ?55|55)[ .-]?)?"
    r"(?:\( ?(?P<zero1>0)?(?P<ddd1>\d{2}) ?\)? ?|(?P<zero2>0)?(?P<ddd2>\d{2})[ .-]?)?"
    r"(?P<assinante>9[ .]?\d{4}|[2-9]\d{3})"
    r"(?P<sep>[ .-]?)"
    r"\d{4}"
    r"(?![\w@])(?!-\d)"
)
# Rótulos de telefone e palavras de atos, procurados até JANELA_CONTEXTO caracteres antes
# do número (texto sem acentos e em minúsculas).
JANELA_CONTEXTO = 25
_RE_ROTULO_TELEFONE = re.compile(
    r"\b(?:tel|fones?|telefones?|cel|celular(?:es)?|whatsapp|contatos?|fax)\b|wa\.me/"
)
_RE_SEGUNDO_TELEFONE = re.compile(r"\[telefone omitido\][ \t]*/[ \t]*\Z")
_RE_SEPARADOR_TELEFONE = re.compile(r"[ .\-()+]")
_RE_CONTEXTO_ATO = re.compile(
    r"\b(?:protocolo|processo|decreto|lei|sei|e-sic|esic|sic|ouvidoria|matricula|inscricao|cnpj|cep)\b"
)
# Zonas que não são texto corrido: endereços web (exceto links de WhatsApp), marcação
# XML/HTML, GUIDs e carimbos de data e hora ISO (metadados embutidos nos arquivos).
_RE_MARCA_URL = re.compile(r"https?://|www\.|\.gov\b|\.br/|\.com/|\.org/")
_RE_TAG = re.compile(r"<[A-Za-z/?!][^<>]{0,2000}>")
# Valor numérico de célula de planilha (<v>…</v>, <t>…</t>, <f>…</f>): só número.
_RE_VALOR_XML = re.compile(r"<([vtf])(?:\s[^<>]{0,200})?>\s*[-+]?[\d.,Ee+-]{1,40}\s*</\1>")
_RE_GUID = re.compile(r"\{[0-9A-Fa-f-]{20,40}\}")
_RE_CARIMBO = re.compile(
    r"\d(?<!\d\d)\d{3}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:[.,]\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?"
)
# DOI ("doi:10.1590/…", "DOI: 10.1111/j.1234-5678.2012.x"): o prefixo 10.NNNN/ basta.
_RE_DOI = re.compile(r"1(?<!\d1)0\.\d{4,9}/[^\s<>\"']+")
# Decimais: parte inteira de até 3 dígitos (com milhares) e vírgula ("1,04712345678",
# "1.234,5"), ou ponto seguido de 5+ dígitos ("1.04712345678"); a parte fracionária
# nunca é telefone, CPF ou RG.
_DECIMAL_VIRGULA = r"\d(?<!\d\d)(?<![.,\-]\d)\d{0,2}(?:\.\d{3})*,\d+"
_DECIMAL_PONTO = r"\d(?<!\d\d)(?<![.,\-]\d)\d{0,2}\.\d{5,}(?![\d.\-])"
_FIM_DE_URL = " \t\r\n\f<>\"'"
MAX_CONTINUACOES_URL = 3
_RE_MARCA_CORTADA = re.compile(r"^[^\[\]]*omitido\]")
# Onde um telefone pode começar: "+", "(" ou o início de uma sequência de dígitos.
_RE_CANDIDATO_TELEFONE = re.compile(r"[+(\d]\d*")

# O separador precisa se repetir: 21-9.8115 de um celular não é uma data.
_DATA = r"\d(?<!\d\d)\d?(?P<separador_data>[/.-])\d{1,2}(?P=separador_data)\d{2,4}(?!\d)"
_DATA_ISO = r"\d(?<!\d\d)\d{3}-\d{2}-\d{2}(?!\d)"
_ANOS = r"(?:19|20)(?<!\d19)(?<!\d20)\d{2} ?[-–/] ?(?:19|20)\d{2}(?!\d)"
# Intervalo de anos com hífen ou travessão, como "(1865-1950)": nunca é telefone se os
# dois forem anos plausíveis (1500–2100) e o segundo não for menor (`_anos_validos`).
_RE_INTERVALO_ANOS = re.compile(r"\d(?<!\d\d)\d{3}[ \t]*[-–][ \t]*\d{4}(?!\d)")
# Não inclui hífen/ponto: 2620-1234 e (21) 2620 1234 continuam telefones.
_RE_LISTA_NUMEROS = re.compile(
    r"(?<![\w.\-/])\d{4}(?!\d)"
    r"(?:(?:\s*,\s*(?:[eE]\s+)?|\s+[eE]\s+|[ \t]+)\d{4}(?![\w/-]|\.\d)){2,}")
ANO_MINIMO, ANO_MAXIMO = 1500, 2100
_CEP = r"\d(?<!\d\d)\d\.?\d{3}-\d{3}(?!\d)"
_CNPJ = r"\d(?<!\d\d)\d\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}(?!\d)"
_CNJ = r"\d(?<!\d\d)\d{6}-?\d{2}\.?\d{4}\.?\d\.?\d{2}\.?\d{4}(?!\d)"
_REAIS = r"R\$\s*-?\d[\d.,]*"

# Proteções que valem para CPF sem formatação completa, RG e telefones.
_PROTECOES_GERAIS = [
    re.compile(_CEP),
    re.compile(_CNPJ),
    re.compile(_CNJ),
    re.compile(r"SEI(?<!\wSEI)\s*(?:[Nn][º°Oo]\.?|:|-)?\s*"
               r"(?:\d{4}\.\d{6}/\d{4}-\d{2}|\d+/\d+/\d{4}|\d{6,8})(?!\d)"),  # número SEI
    re.compile(r"[Mm][Aa][Tt][Rr][IiÍí][Cc][Uu][Ll][Aa](?<!\w[Mm][Aa][Tt][Rr][IiÍí][Cc][Uu][Ll][Aa])"
               r"(?![\w])(?:[ \t]+[Ff][Uu][Nn][Cc][Ii][Oo][Nn][Aa][Ll])?" + _NUMERO_CURTO + r"\d[\d./-]*"),
    re.compile(_REAIS),
    re.compile(_DATA),
    re.compile(_DATA_ISO),
    re.compile(_ANOS),
    re.compile(_DECIMAL_VIRGULA),
    re.compile(_DECIMAL_PONTO),
]
# Proteções para telefones e RG: números de atos, processos e documentos.
_PALAVRAS_ATO = (
    r"leis?|decretos?|portarias?|resolu[cç](?:[aã]o|[oõ]es)|emendas?|processos?|protocolos?|"
    r"of[ií]cios?|requerimentos?|indica[cç](?:[aã]o|[oõ]es)|mo[cç](?:[aã]o|[oõ]es)|projetos?|"
    r"pdl|pl|plc|edital|editais|contratos?|conv[eê]nios?|termos?|atas?|sess(?:[aã]o|[oõ]es)|"
    r"art(?:igo)?s?\.?|incisos?|par[aá]grafos?|preg[aã]o|licita[cç](?:[aã]o|[oõ]es)|empenhos?|"
    r"notas? fiscal|notas? fiscais|inscri[cç](?:[aã]o|[oõ]es)|matr[ií]culas?|e-?sic|sic|ouvidorias?"
)
_RE_NOME_NAO_PESSOAL = re.compile(
    rf"(?:{_PALAVRAS_ATO}|cpf|cnpj|cep|rg|identidade|registro|"
    + "|".join(re.escape(r.split()[-1]) for r in ROTULOS_DOCUMENTO) + r")", re.I)
_QUALIFICADORES = (
    r"municipal|complementar|estadual|federal|ordin[aá]ria|legislativo|administrativo|"
    r"eletr[oô]nico|de lei|de decreto legislativo|de resolu[cç][aã]o|sei"
)
# Consultado só perto de cada candidato (janela antes do número), não no texto inteiro:
# a palavra do ato, qualificadores e "nº" terminando onde o número começa.
_RE_ATO_ANTES = re.compile(
    rf"\b(?:{_PALAVRAS_ATO})(?:[ \t]{{1,3}}(?:{_QUALIFICADORES}))*" + _NUMERO_CURTO + r"\Z", re.I
)
_JANELA_ATO = 160

# A regra de OCR é deliberadamente mais abrangente que as regras normais. Não cruza
# linhas e admite uma letra de ruído entre grupos (inclusive "1/23456E/ 78").
_RE_NUMERO_OCR = re.compile(
    r"\d(?<!\d\d)(?:\d|(?:[ ./-]| ?[./-] ?|[ ./-]?[^\W\d_][ ./-]{0,2})\d)*")
_RE_OCR_ATO = re.compile(
    rf"\b(?:{_PALAVRAS_ATO})(?:[ \t]{{1,3}}(?:{_QUALIFICADORES}))*"
    + _NUMERO_CURTO + r"\d[\d.]*[/-]\d{4}(?!\d)|\bn[º°][ \t]*\d[\d.]*[/\-]\d{4}(?!\d)", re.I)
_OCR_PROTECOES = [re.compile(p) for p in (
    r"\d(?<!\d\d)\d/\d{2}/\d{4}(?!\d)", _DATA_ISO, _REAIS, _ANOS,
    r"\d(?<!\d\d)[\d.]*,\d+",
)] + [_RE_OCR_ATO]
_RE_CEP = re.compile(_CEP)
_RE_ROTULO_CEP = re.compile(r"\bCEP\b", re.I)
_RE_PAGINA = re.compile(r"(?m)^\f\r?$")

# ---------------------------------------------------------------- padrões de varrer
_V_CPF = re.compile(r"\d(?<!\d\d)(?<!\d[ .\-/]\d)(?:[ .\-/]?\d){10}(?![ .\-/]?\d)")
_V_TELEFONE = re.compile(
    r"(?<!\d)(?P<pais>\+\s?55[ .-]?)?(?:(?P<parenteses>\(\s?0?\d{2}\s?\)?\s?)|(?P<zero>0)?\d{2}[ .-]?)?"
    r"(?:9[ .]?\d{4}|\d{4,5})(?P<sep>[ .-]?)\d{4}(?!\d)"
)
_V_EMAIL = re.compile(r"[^\s@<>()\[\]{},;:\"']+@[^\s@<>()\[\]{},;:\"']+\.\w{2,}")
_V_RG = re.compile(
    r"[Rr](?<![\w.][Rr])(?:\.\s?[Gg]\.?|[Gg])(?![\w])[^\d\n\[\]]{0,20}?(\d[\d.\-]{3,15}[\dXx])"
)
_V_PROTECOES = [re.compile(p) for p in (_DATA, _DATA_ISO, _ANOS, _CEP, _CNJ, _REAIS,
                                        _DECIMAL_VIRGULA, _DECIMAL_PONTO)] + [
    re.compile(r"[Ll](?<!\w[Ll])[Ee][Ii](?![\w])(?:[ \t]+[Cc]omplementar)?"
               r"(?:[ \t]+(?:[Mm]unicipal|[Ee]stadual|[Ff]ederal))?" + _NUMERO_CURTO + r"\d[\d./-]*\d"),
]
_V_CNPJ = re.compile(_CNPJ)


# ---------------------------------------------------------------- utilidades
def cpf_valido(digitos: str) -> bool:
    """Confere os dois dígitos verificadores de um CPF de 11 dígitos."""
    if len(digitos) != 11 or not digitos.isdigit() or digitos == digitos[0] * 11:
        return False
    for n in (9, 10):
        soma = sum(int(digitos[i]) * (n + 1 - i) for i in range(n))
        if (soma * 10) % 11 % 10 != int(digitos[n]):
            return False
    return True


def cnpj_valido(digitos: str) -> bool:
    """Confere os dois dígitos verificadores de um CNPJ de 14 dígitos."""
    if len(digitos) != 14 or not digitos.isdigit() or digitos == digitos[0] * 14:
        return False
    for n, pesos in ((12, (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)), (13, (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))):
        resto = sum(int(d) * p for d, p in zip(digitos[:n], pesos)) % 11
        if (0 if resto < 2 else 11 - resto) != int(digitos[n]):
            return False
    return True


def telefone_canonico(valor: str) -> str | None:
    """Telefone só com dígitos, com DDD (21 quando ausente) e sem +55 nem zero de tronco."""
    d = re.sub(r"\D", "", valor)
    if d.startswith("55") and len(d) in (12, 13):
        d = d[2:]
    if d.startswith("0") and len(d) in (11, 12):
        d = d[1:]
    if len(d) in (8, 9):
        d = "21" + d
    return d if len(d) in (10, 11) else None


def _dobrar(texto: str) -> str:
    """Minúsculas sem acentos."""
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower())
                   if unicodedata.category(c) != "Mn")


def _pasta_config(config_raiz: Path) -> Path:
    config_raiz = Path(config_raiz)
    return config_raiz / "config" if (config_raiz / "config").is_dir() else config_raiz


def _ler_json(caminho: Path):
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def _valores_liberados(contatos: Iterable) -> set[str]:
    valores: set[str] = set()
    for contato in contatos or ():
        if not isinstance(contato, dict):
            continue
        valor, tipo, fonte = contato.get("valor"), contato.get("tipo"), contato.get("fonte")
        if not isinstance(valor, str) or not isinstance(fonte, str) or not fonte.startswith("https://"):
            continue
        valor = valor.strip()
        if tipo == "email":
            # só endereços completos (local@domínio); domínio solto não libera nada
            if _RE_EMAIL_COMPLETO.match(valor):
                valores.add(valor.lower())
        elif tipo == "telefone":
            canonico = telefone_canonico(valor)
            if canonico:
                valores.add(canonico)
    return valores


def liberados(config_raiz: Path) -> set[str]:
    """Contatos que não são mascarados.

    Reúne os `contatos` (com fonte HTTPS) de cada perfil em `config/perfis.json`, os
    `contatos_institucionais` de `config/backend.json` e os domínios institucionais
    públicos (como "@gov.br" e "@jus.br"). E-mails ficam em minúsculas e precisam ser
    endereços completos; telefones, na forma de `telefone_canonico`. Aceita a raiz do
    repositório ou a pasta `config/`; arquivos ou campos ausentes não liberam nada.
    """
    pasta = _pasta_config(config_raiz)
    resultado = {"@" + d for d in DOMINIOS_LIBERADOS}
    perfis = _ler_json(pasta / "perfis.json")
    if isinstance(perfis, dict):
        for perfil in (perfis.get("vereadores") or {}).values():
            if isinstance(perfil, dict):
                resultado |= _valores_liberados(perfil.get("contatos"))
    backend = _ler_json(pasta / "backend.json")
    if isinstance(backend, dict):
        resultado |= _valores_liberados(backend.get("contatos_institucionais"))
    return resultado


class _Intervalos:
    """Consulta de sobreposição com intervalos fixos [ini, fim)."""

    def __init__(self, intervalos: Iterable[tuple[int, int]]) -> None:
        ordenados = sorted(intervalos)
        self.inicios = [a for a, _ in ordenados]
        self.max_fim: list[int] = []
        maior = -1
        for _, b in ordenados:
            maior = max(maior, b)
            self.max_fim.append(maior)

    def sobrepoe(self, ini: int, fim: int) -> bool:
        k = bisect.bisect_left(self.inicios, fim)
        return k > 0 and self.max_fim[k - 1] > ini

    def contem(self, ini: int, fim: int) -> bool:
        """Se um dos intervalos contém o candidato inteiro, não só parte dele."""
        k = bisect.bisect_right(self.inicios, ini)
        return k > 0 and self.max_fim[k - 1] >= fim


class _Aceitos:
    """Intervalos aceitos, sem sobreposição entre si."""

    def __init__(self) -> None:
        self.lista: list[tuple[int, int, str]] = []

    def livre(self, ini: int, fim: int) -> bool:
        k = bisect.bisect_left(self.lista, (ini, -1, ""))
        if k < len(self.lista) and self.lista[k][0] < fim:
            return False
        return not (k > 0 and self.lista[k - 1][1] > ini)

    def incluir(self, ini: int, fim: int, tipo: str) -> bool:
        if not self.livre(ini, fim):
            return False
        bisect.insort(self.lista, (ini, fim, tipo))
        return True


def _documentos(texto: str) -> list[tuple[int, int]]:
    """Trechos dos números de documentos pessoais rotulados (ao menos 5 dígitos)."""
    trechos = {m.span("numero") for m in _RE_DOCUMENTO.finditer(texto)
               if sum(c.isdigit() for c in m.group("numero")) >= 5}
    trechos.update(m.span() for m in _RE_ONZE_DIGITOS.finditer(texto)
                   if any(m.start() - r.end() <= 30 for r in _RE_ROTULO_CNH.finditer(
                       texto, max(0, m.start() - 45), m.start())))
    return sorted(trechos)


def _cpfs_rotulados(texto: str) -> list[tuple[int, int]]:
    """CPF partido pelo OCR ou inscrito no carimbo de um certificado digital."""
    trechos = [m.span() for m in _RE_CPF_PARTIDO.finditer(texto) if _rotulo_cpf(texto, m.start())]
    for m in _RE_CPF_ASSINATURA.finditer(texto):
        if (_RE_NOME_NAO_PESSOAL.fullmatch(m.group("nome"))
                or _RE_ROTULO_TELEFONE.fullmatch(_dobrar(m.group("nome")))):
            continue  # CNH:…, PIS:… e Lei:… não são nomes de titulares de certificado
        if (m.group("nome").isupper() or _RE_ASSINATURA_DIGITAL.search(
                texto[max(0, m.start() - 60):min(len(texto), m.end() + 60)])):
            trechos.append(m.span("numero"))
    return trechos


def _intervalos_de_anos(texto: str) -> list[tuple[int, int]]:
    """Trechos "AAAA-AAAA" com dois anos plausíveis em ordem (como "1865-1950")."""
    trechos = []
    for m in _RE_INTERVALO_ANOS.finditer(texto):
        anos = re.findall(r"\d{4}", m.group())
        a, b = int(anos[0]), int(anos[1])
        if ANO_MINIMO <= a <= b <= ANO_MAXIMO:
            trechos.append(m.span())
    return trechos


def _protegidos(texto: str, padroes) -> _Intervalos:
    return _Intervalos([m.span() for p in padroes for m in p.finditer(texto)]
                       + _intervalos_de_anos(texto))


def _listas_de_numeros(texto: str) -> list[tuple[int, int]]:
    """Listas de 3+ itens de quatro dígitos, com ao menos uma vírgula ou conjunção."""
    return [m.span() for m in _RE_LISTA_NUMEROS.finditer(texto)
            if "," in m.group() or re.search(r"\s+[eE]\s+", m.group())]


def _a_partir(candidatos: re.Pattern, padrao: re.Pattern, texto: str):
    """Como `padrao.finditer(texto)`, mas tentando só no início de cada candidato e,
    quando o candidato começa por "+" ou "(", também no primeiro dígito seguinte
    (`candidatos` precisa cobrir todo início possível de `padrao`)."""
    fim = -1
    for c in candidatos.finditer(texto):
        inicio = c.start()
        posicoes = (inicio, inicio + 1) if c.end() - inicio > 1 and not texto[inicio].isdigit() else (inicio,)
        for pos in posicoes:
            if pos < fim:
                continue
            m = padrao.match(texto, pos)
            if m:
                yield m
                fim = m.end()
                break


def _zonas_url(texto: str) -> list[tuple[int, int]]:
    """Trechos de endereços web (a palavra inteira em volta de http://, www., .gov, .br/),
    exceto links de WhatsApp (wa.me, whatsapp), cujos números continuam pessoais."""
    zonas: list[tuple[int, int]] = []
    for m in _RE_MARCA_URL.finditer(texto):
        if zonas and m.start() < zonas[-1][1]:
            continue
        ini, fim = m.start(), m.end()
        while ini > 0 and texto[ini - 1] not in _FIM_DE_URL:
            ini -= 1
        while fim < len(texto) and texto[fim] not in _FIM_DE_URL:
            fim += 1
        fim = _continuacao_de_url(texto, ini, fim)
        palavra = texto[ini:fim].lower()
        if "wa.me" in palavra or "whatsapp" in palavra:
            continue
        zonas.append((ini, fim))
    return zonas


def _continuacao_de_url(texto: str, ini: int, fim: int) -> int:
    """Estende um endereço web quebrado na diagramação por espaços simples ou por uma
    quebra de linha, como "scielo.br/pdf/pcp/ v12nspe1/ 1234-5678": até
    `MAX_CONTINUACOES_URL` pedaços seguintes (no máximo uma quebra de linha), enquanto o
    endereço termina em "/" ou o pedaço contém "/", e o pedaço não é uma palavra só de
    letras nem começa por "(" (início de um telefone)."""
    quebras = 0
    for _ in range(MAX_CONTINUACOES_URL):
        if fim + 1 >= len(texto) or texto[fim] not in " \n" or texto[fim + 1] in _FIM_DE_URL:
            break
        if texto[fim] == "\n":
            if quebras:
                break
            quebras += 1
        prox = fim + 1
        while prox < len(texto) and texto[prox] not in _FIM_DE_URL:
            prox += 1
        pedaco = texto[fim + 1:prox]
        if pedaco.startswith("(") or not re.search(r"[\d/]", pedaco):
            break
        if not (texto[fim - 1] == "/" or "/" in pedaco):
            break
        fim = prox
    return fim


def _tag_com_email(trecho: str) -> bool:
    """Distingue <endereço> de tags reais sem liberar atributos ou tags de fechamento."""
    if not _RE_EMAIL_ANGULOS.fullmatch(trecho) or "." not in trecho:
        return False
    return ("@" in trecho or _RE_EMAIL_OCR.search(trecho) is not None
            or _RE_EMAIL_COLADO.search(trecho) is not None
            or _RE_PROVEDOR_OCR.search(trecho) is not None)


def _zonas(texto: str, urls: bool, emails: bool = False) -> _Intervalos:
    """XML/HTML e metadados; com `emails`, <endereço> não é marcação protegida.

    `urls` também protege endereços web. A exceção de <endereço> é exclusiva das
    regras de e-mail: as proteções dos demais tipos de dados ficam inalteradas.
    """
    trechos = [m.span() for p in (_RE_TAG, _RE_VALOR_XML, _RE_GUID, _RE_CARIMBO, _RE_DOI)
               for m in p.finditer(texto)
               if not (emails and p is _RE_TAG and _tag_com_email(m.group()))]
    if urls:
        trechos += _zonas_url(texto)
    return _Intervalos(trechos)


def _antes(texto: str, inicio: int) -> str:
    """Até JANELA_CONTEXTO caracteres antes da posição, sem acentos e em minúsculas; as
    marcas de substituição ("[telefone omitido]") não contam como rótulo."""
    trecho = texto[max(0, inicio - JANELA_CONTEXTO):inicio]
    for marca in SUBSTITUICOES.values():
        trecho = trecho.replace(marca, " ")
    trecho = _RE_MARCA_CORTADA.sub(" ", trecho)  # marca cortada no começo da janela
    return _dobrar(trecho)


def _dentro_de_sequencia(texto: str, m: re.Match) -> bool:
    """Se o candidato tem "dígito espaço" logo antes ou "espaço dígito" logo depois."""
    antes = texto[max(0, m.start() - 2):m.start()]
    depois = texto[m.end():m.end() + 2]
    return ((len(antes) == 2 and antes[0].isdigit() and antes[1] == " ")
            or (len(depois) == 2 and depois[0] == " " and depois[1].isdigit()))


def _rotulo_cpf(texto: str, inicio: int) -> bool:
    """Se há rótulo de CPF até JANELA_ROTULO_CPF caracteres antes da posição; as marcas
    de substituição ("[CPF omitido]") não contam como rótulo."""
    trecho = texto[max(0, inicio - JANELA_ROTULO_CPF):inicio]
    for marca in SUBSTITUICOES.values():
        trecho = trecho.replace(marca, " ")
    trecho = _RE_MARCA_CORTADA.sub(" ", trecho)
    return _RE_ROTULO_CPF.search(_dobrar(trecho)) is not None


def _numero_de_ato(texto: str, inicio: int) -> bool:
    """Se o número que contém a posição `inicio` vem logo depois de lei, processo e afins."""
    s = inicio
    while s > 0 and (texto[s - 1].isdigit() or texto[s - 1] in "./-"):
        s -= 1
    return _RE_ATO_ANTES.search(texto, max(0, s - _JANELA_ATO), s) is not None


def _preparar(liberados_: Iterable[str]) -> tuple[set[str], tuple[str, ...]]:
    conjunto = {v.strip().lower() for v in liberados_}
    dominios = tuple(dict.fromkeys(
        [*DOMINIOS_LIBERADOS, *(v[1:] for v in conjunto if v.startswith("@"))]
    ))
    return conjunto, dominios


def _email_liberado(email: str, conjunto: set[str], dominios: tuple[str, ...]) -> bool:
    email = email.lower()
    if email in conjunto:
        return True
    dominio = email.rsplit("@", 1)[1]
    return any(dominio == d or dominio.endswith("." + d) for d in dominios)


def _locais_email_ocr(prefixo: str) -> set[str]:
    """Possíveis partes locais antes de separadores e lixo do OCR, sem expô-las."""
    candidatos = {prefixo, re.sub(r"[()&|?©@A-Z0-9 \t]+$", "", prefixo),
                  re.sub(r"[dD]$", "", prefixo)}
    candidatos.update(prefixo[:m.start()] for m in _RE_RUIDO_EMAIL.finditer(prefixo))
    return {p for p in candidatos if _RE_LOCAL_EMAIL.fullmatch(p)}


def _enderecos_email_rotulado(valor: str) -> set[str]:
    """Tenta inserir @ antes dos rótulos de domínio, inclusive dentro do token colado.

    Até dois caracteres entre local e domínio podem ser lixo. O tamanho limitado
    do token impede uma busca quadrática sobre uma linha inteira de OCR.
    """
    enderecos = {valor} if _RE_EMAIL_COMPLETO.fullmatch(valor) else set()
    for i in range(1, len(valor)):
        local = valor[:i]
        if not _RE_LOCAL_EMAIL.fullmatch(local):
            continue
        for ruido in range(3):
            dominio = valor[i + ruido:]
            if _RE_DOMINIO_OCR.fullmatch(dominio):
                enderecos.add(local + "@" + dominio)
    return enderecos


def _emails_ocr(texto: str, conjunto: set[str], dominios: tuple[str, ...]) -> list[tuple[int, int, bool]]:
    """Candidatos OCR das três regras; une sobreposições e suas reconstruções.

    A máscara e a barreira compartilham só os candidatos de e-mail, não os demais
    detectores. O booleano informa se alguma reconstrução é um contato liberado.
    """
    candidatos: list[tuple[int, int, set[str]]] = []
    zonas: _Intervalos | None = None
    web: _Intervalos | None = None

    def incluir(ini: int, fim: int, enderecos: set[str]) -> None:
        nonlocal zonas, web
        if zonas is None:
            zonas = _zonas(texto, urls=False, emails=True)
            # Não usar a proteção ampla de '.gov' dos telefones: o sufixo
            # gov.br.exemplo.com de um e-mail não é um domínio público liberado.
            web = _Intervalos(m.span() for m in _RE_WEB_EMAIL.finditer(texto))
        assert web is not None
        if (zonas.sobrepoe(ini, fim) or web.sobrepoe(ini, fim)
                or texto[ini:fim].lower().startswith(("www.", "http://", "https://", "//"))
                or texto[max(0, ini - 2):ini] in ('="', "='", "//")):
            if not any(_email_liberado(e, conjunto, dominios) for e in enderecos):
                return
        candidatos.append((ini, fim, enderecos))

    for m in _RE_EMAIL_OCR.finditer(texto):
        incluir(m.start(), m.end(), {m.group("local") + "@" + m.group("dominio")})

    for m in _RE_PROVEDOR_OCR.finditer(texto):
        ini = m.start()
        while ini > 0 and texto[ini - 1] not in " \t\r\n\f<>\"',;:[]{}":
            ini -= 1
        while ini < m.start() and texto[ini] in "(":
            ini += 1  # parêntese externo não faz parte da parte local
        prefixo = texto[ini:m.start()]
        # Provedor em token próprio (ou só lixo antes dele): inclui exatamente um
        # token anterior, com uma letra e sem rótulos/pontuação de introdução.
        if not re.search(r"[a-z]", prefixo) and ini > 0 and texto[ini - 1] == " ":
            anterior = re.search(r"[^\s]+$", texto[max(0, ini - 321):ini - 1])
            if anterior:
                token = anterior.group()
                rotulo_antes = any(r.end() == ini - 1 for r in _RE_ROTULO_EMAIL.finditer(
                    texto, max(0, ini - 40), ini - 1))
                if (not token.endswith((":", ".")) and not _RE_ROTULO_EMAIL.fullmatch(token)
                        and not rotulo_antes
                        and re.search(r"[A-Za-z]", token)
                        and re.fullmatch(r"[A-Za-z0-9._%+()&|?©@-]+", token)):
                    ini -= len(token) + 1
                    prefixo = texto[ini:m.start()]
        if m.end() - ini > 320:
            continue
        provedor = next(p for p, _ in _PROVEDORES_OCR if m.group(p) is not None)
        dominio = provedor + m.group("sufixo").lower()
        enderecos = {local + "@" + dominio for local in _locais_email_ocr(prefixo)}
        incluir(ini, m.end(), enderecos or {"_@" + dominio})

    for m in _RE_EMAIL_COLADO.finditer(texto):
        if m.end() - m.start() > 320:
            continue
        local, resto = m.group("local"), m.group("resto")
        enderecos = {local + "@" + resto[i:] for i in range(3)
                     if _RE_DOMINIO_OCR.fullmatch(resto[i:])}
        incluir(m.start(), m.end(), enderecos)

    for rotulo in _RE_ROTULO_EMAIL.finditer(texto):
        if (rotulo.start() > 0 and texto[rotulo.start() - 1] == "["
                and texto.startswith(" omitido]", rotulo.end())):
            continue  # a marca da própria máscara não é um novo rótulo
        for token in _RE_TOKEN_EMAIL.finditer(texto, rotulo.end(), min(len(texto), rotulo.end() + 346)):
            ini, fim = token.span()
            if ini - rotulo.end() > 25:
                break
            if ini > 0 and texto.startswith(SUBSTITUICOES["email"], ini - 1):
                break  # o primeiro contato já foi mascarado; não avançar na segunda passagem
            valor = token.group().strip("().:")
            ini += len(token.group()) - len(token.group().lstrip("().:"))
            fim = ini + len(valor)
            if token.group().lower() in ("web:", "site:"):
                break
            if not valor or len(valor) > 320 or not _RE_DOMINIO_OCR.search(valor):
                continue
            if "www" in valor.lower() or "http" in valor.lower() or valor.startswith("//"):
                break
            incluir(ini, fim, _enderecos_email_rotulado(valor))
            break  # só o primeiro token com domínio depois do rótulo

    unidos: list[tuple[int, int, set[str]]] = []
    for ini, fim, enderecos in sorted(candidatos, key=lambda c: (c[0], -c[1])):
        if unidos and ini < unidos[-1][1]:
            a, b, anteriores = unidos[-1]
            unidos[-1] = (a, max(b, fim), anteriores | enderecos)
        else:
            unidos.append((ini, fim, enderecos))
    return [(ini, fim, any(_email_liberado(e, conjunto, dominios) for e in enderecos))
            for ini, fim, enderecos in unidos]


def _numeros_ocr(texto: str, liberados_: Iterable[str],
                 ocr_paginas: set[int] | None) -> Iterator[tuple[int, int, str]]:
    """Números residuais de 8+ dígitos nas páginas OCR (numeração começa em 1).

    As proteções são recortadas *antes* da busca: uma data ao lado de um identificador
    não libera também o identificador. Não se aplicam as proteções amplas de links,
    CNPJ ou metadados, inadequadas para documentos digitalizados com ruído.
    """
    if not ocr_paginas:
        return
    conjunto, dominios = _preparar(liberados_)
    inicio = 0
    for numero, separador in enumerate([*_RE_PAGINA.finditer(texto), None], 1):
        fim = separador.start() if separador else len(texto)
        if numero in ocr_paginas:
            pagina = texto[inicio:fim]
            protegidos = [m.span() for p in _OCR_PROTECOES for m in p.finditer(pagina)]
            protegidos += _intervalos_de_anos(pagina)
            protegidos += _listas_de_numeros(pagina)
            protegidos += [m.span() for m in _RE_CEP.finditer(pagina)
                           if _RE_ROTULO_CEP.search(pagina[max(0, m.start() - 20):m.start()])
                           or _RE_ROTULO_CEP.search(pagina[m.end():m.end() + 20])]
            protegidos += [m.span() for m in _RE_EMAIL.finditer(pagina)
                           if _email_liberado(m.group(), conjunto, dominios)]
            protegidos += [(a, b) for a, b, livre in _emails_ocr(pagina, conjunto, dominios) if livre]
            protegidos += [m.span() for m in _a_partir(_RE_CANDIDATO_TELEFONE, _RE_TELEFONE, pagina)
                           if telefone_canonico(m.group()) in conjunto]
            # Um caractere não numérico e não separador impede juntar grupos através
            # de uma proteção e conserva os offsets do texto original.
            partes = []
            pos = 0
            for a, b in sorted(protegidos):
                if b <= pos:
                    continue
                partes.extend((pagina[pos:max(pos, a)], ";" * (b - max(pos, a))))
                pos = b
            partes.append(pagina[pos:])
            for m in _RE_NUMERO_OCR.finditer("".join(partes)):
                if sum(c.isdigit() for c in m.group()) >= 8:
                    yield inicio + m.start(), inicio + m.end(), "numero"
        inicio = separador.end() if separador else fim


def _telefone_em_serie(texto: str, inicio: int) -> bool:
    """Segundo telefone após uma marca já mascarada, separado por barra."""
    return _RE_SEGUNDO_TELEFONE.search(texto[max(0, inicio - 80):inicio]) is not None


def _detectar(texto: str, liberados_: Iterable[str]) -> list[tuple[int, int, str]]:
    """Ocorrências (início, fim, tipo) de `mascarar`, sem sobreposição, em ordem de posição."""
    conjunto, dominios = _preparar(liberados_)
    aceitos = _Aceitos()
    gerais = _protegidos(texto, _PROTECOES_GERAIS)
    marcacao = _zonas(texto, urls=False)  # XML/HTML, GUID, carimbos de data e hora
    web = _Intervalos(_zonas_url(texto))
    listas = _Intervalos(_listas_de_numeros(texto))

    for ini, fim, livre in _emails_ocr(texto, conjunto, dominios):
        aceitos.incluir(ini, fim, "_liberado" if livre else "email")
    if "@" in texto:
        for m in _RE_EMAIL.finditer(texto):
            tipo = "_liberado" if _email_liberado(m.group(), conjunto, dominios) else "email"
            aceitos.incluir(m.start(), m.end(), tipo)

    # CPF antes do RG: um rótulo de RG até 20 caracteres antes não pode reivindicar só
    # o começo de um CPF com espaço ("RG nº, CPF 123.456 789-09").
    for ini, fim in _cpfs_rotulados(texto):
        aceitos.incluir(ini, fim, "cpf")
    for m in _RE_CPF.finditer(texto):
        digitos = "".join(m.group(g) for g in "abcde")
        rotulado = _rotulo_cpf(texto, m.start())
        if not rotulado:
            if not cpf_valido(digitos):
                continue
            if " " in (m.group("s1"), m.group("s2"), m.group("s3")) and _dentro_de_sequencia(texto, m):
                continue  # fatia 3-3-3-2 de uma sequência maior de números separados por espaço
        formatado = m.group("s1") == "." and m.group("s2") == "." and m.group("s3").strip() == "-"
        if not formatado and marcacao.sobrepoe(m.start(), m.end()):
            continue  # metadado ou marcação; CPF formatado é mascarado sempre
        if not (formatado or rotulado) and gerais.sobrepoe(m.start(), m.end()):
            continue
        aceitos.incluir(m.start(), m.end(), "cpf")

    for m in _RE_RG.finditer(texto):
        ini, fim = m.span("numero")
        if sum(c.isdigit() for c in m.group("numero")) < 5:
            continue
        if m.group("rotulo")[0] in "Ii":  # identidade (ou variante de OCR)
            antes = _dobrar(texto[max(0, m.start() - 25):m.start()])
            if ("carteira" not in antes and "cedula" not in antes
                    and not _RE_MARCA_IDENTIDADE.match(m.group("meio"))):
                continue
        if gerais.sobrepoe(ini, fim) or _numero_de_ato(texto, ini) or marcacao.sobrepoe(ini, fim):
            continue
        digitos = re.sub(r"\D", "", m.group("numero"))
        # 11 dígitos com DV de CPF válido depois do rótulo: é CPF, não RG
        aceitos.incluir(ini, fim, "cpf" if len(digitos) == 11 and cpf_valido(digitos) else "rg")

    for ini, fim in _documentos(texto):
        if not gerais.sobrepoe(ini, fim) and not marcacao.sobrepoe(ini, fim):
            aceitos.incluir(ini, fim, "documento")

    for m in _a_partir(_RE_CANDIDATO_TELEFONE, _RE_TELEFONE, texto):
        ini, fim = m.span()
        if marcacao.sobrepoe(ini, fim) or web.sobrepoe(ini, fim) or listas.contem(ini, fim):
            continue  # número de link, metadado ou marcação: mascarar corromperia o link
        rotulado = bool(_RE_ROTULO_TELEFONE.search(_antes(texto, ini))) or _telefone_em_serie(texto, ini)
        anterior = bisect.bisect_left(aceitos.lista, (ini, -1, "")) - 1
        if anterior >= 0:
            _, b, tipo = aceitos.lista[anterior]
            rotulado |= (b <= ini and tipo in ("telefone", "_liberado")
                         and texto[b:ini].strip(" \t") == "/")
        ddd = m.group("ddd1") or m.group("ddd2")
        if ddd is not None and int(ddd) not in DDDS and not rotulado:
            continue
        sep = m.group("sep")
        tem_ddd = ddd is not None or m.group("pais") is not None
        assinante = m.group("assinante")
        if not rotulado and not _RE_SEPARADOR_TELEFONE.search(m.group()):
            # dígitos corridos (8 a 13), sem separador, parênteses, + nem rótulo: valores e
            # números de tabela, nunca telefone (um "DDD" colado não basta)
            continue
        if sep == "." and not (tem_ddd or rotulado):
            continue  # 9999.9999 sem DDD nem rótulo: códigos de programa e ação orçamentária
        if len(assinante) == 4 and assinante[0] in "6789" and not (sep == "-" or tem_ddd or rotulado):
            continue  # número antigo de 8 dígitos começando por 6–9: só com hífen, DDD ou rótulo
        if gerais.sobrepoe(ini, fim) or _numero_de_ato(texto, ini):
            continue
        canonico = telefone_canonico(m.group())
        if canonico is not None and canonico in conjunto:
            aceitos.incluir(ini, fim, "_liberado")
            continue
        aceitos.incluir(ini, fim, "telefone")

    return [item for item in aceitos.lista if not item[2].startswith("_")]


# ---------------------------------------------------------------- API
def _substituir(texto: str, ocorrencias: Iterable[tuple[int, int, str]], contagens: dict[str, int]) -> str:
    """Aplica ocorrências ordenadas e disjuntas e acumula as contagens."""
    partes: list[str] = []
    pos = 0
    for ini, fim, tipo in ocorrencias:
        partes.append(texto[pos:ini])
        partes.append(SUBSTITUICOES[tipo])
        contagens[tipo] += 1
        pos = fim
    partes.append(texto[pos:])
    return "".join(partes)


def mascarar(texto: str, liberados: Iterable[str] = frozenset(),
             ocr_paginas: set[int] | None = None) -> tuple[str, dict[str, int]]:
    """Texto mascarado e contagens; idempotente. Páginas OCR (base 1) têm regra extra
    de números de 8+ dígitos, depois das regras normais, preservando só as proteções
    explícitas de datas, moeda, CEP rotulado, atos, intervalos de anos, listas de
    documentos de quatro dígitos e contatos.
    """
    liberados = frozenset(liberados)
    contagens = {tipo: 0 for tipo in TIPOS}
    texto = _substituir(texto, _detectar(texto, liberados), contagens)
    texto = _substituir(texto, _numeros_ocr(texto, liberados, ocr_paginas), contagens)
    return texto, contagens


def _fracionario(texto: str, inicio: int) -> bool:
    """Se o número começa logo depois de "\\d," ou "\\d." (parte fracionária de um decimal)."""
    return inicio >= 2 and texto[inicio - 1] in ",." and texto[inicio - 2].isdigit()


def _telefone_forte(texto: str, m: re.Match) -> bool:
    """Força de um número com forma de telefone achado por `varrer` (veja o docstring)."""
    antes = _antes(texto, m.start())
    if _RE_ROTULO_TELEFONE.search(antes) or _telefone_em_serie(texto, m.start()):
        return True
    if _RE_CONTEXTO_ATO.search(antes):
        return False
    return bool(m.group("pais") or m.group("parenteses") or m.group("zero") or m.group("sep") == "-")


def varrer(texto: str, liberados: Iterable[str] = frozenset(),
           ocr_paginas: set[int] | None = None) -> list[dict]:
    """Barreira independente: ocorrências `{tipo, inicio, fim, forte}` suspeitas, sem o valor.

    Mais ampla que `mascarar` (veja o docstring do módulo); use o mesmo `liberados`.
    `forte` é verdadeiro para CPF com DV válido, e-mail, RG com rótulo e número de
    documento pessoal rotulado (`documento`: CNH, título de eleitor, PIS…). Intervalos de
    anos ("1865-1950") e listas de documentos de quatro dígitos nunca são telefone.
    Telefone é forte
    com rótulo (tel, fone, cel, celular, whatsapp, contato, fax) até `JANELA_CONTEXTO`
    caracteres antes; fraco logo depois de protocolo, processo, decreto, lei, SEI,
    e-SIC/SIC, ouvidoria, matrícula, inscrição, CNPJ ou CEP; nos demais casos, forte com DDD entre parênteses,
    +55, 0DDD ou hífen (9999-9999), e fraco com ponto, espaço ou dígitos corridos.
    Números dentro de endereços web (exceto WhatsApp), marcação XML/HTML, GUIDs e
    carimbos ISO de data e hora são ignorados (CPF: só os três últimos). A barreira
    bloqueia só nas ocorrências fortes; as fracas são contadas para revisão.
    Nas `ocr_paginas` (base 1), a mesma regra numérica extra da máscara detecta
    resíduos como `numero` forte. Use o mesmo conjunto de páginas do mascaramento.
    """
    liberados = frozenset(liberados)
    conjunto, dominios = _preparar(liberados)
    ignorar = _Intervalos(
        [m.span() for p in _V_PROTECOES for m in p.finditer(texto)]
        + [m.span() for m in _V_CNPJ.finditer(texto) if cnpj_valido(re.sub(r"\D", "", m.group()))]
        + _intervalos_de_anos(texto)
    )
    marcacao = _zonas(texto, urls=False)
    web = _Intervalos(_zonas_url(texto))
    listas = _Intervalos(_listas_de_numeros(texto))
    achados: list[tuple[int, int, str]] = []
    emails_liberados: list[tuple[int, int]] = []
    emails_ocr = _emails_ocr(texto, conjunto, dominios)
    zonas_email_ocr = _Intervalos((a, b) for a, b, _ in emails_ocr)
    for ini, fim, livre in emails_ocr:
        if livre:
            emails_liberados.append((ini, fim))
        else:
            achados.append((ini, fim, "email"))
    for m in (_V_EMAIL.finditer(texto) if "@" in texto else ()):
        if zonas_email_ocr.sobrepoe(*m.span()):
            continue
        email = m.group().strip(".")
        if "@" not in email:
            continue
        if _email_liberado(email, conjunto, dominios):
            emails_liberados.append(m.span())
        else:
            achados.append((m.start(), m.end(), "email"))
    ignorar_email = _Intervalos(emails_liberados)
    for m in _V_RG.finditer(texto):
        if sum(c.isdigit() for c in m.group(1)) >= 5 and not ignorar.sobrepoe(*m.span(1)):
            achados.append((m.start(1), m.end(1), "rg"))
    cpfs_rotulados = _cpfs_rotulados(texto)
    achados.extend((a, b, "cpf") for a, b in cpfs_rotulados)
    rotulados = _Intervalos(cpfs_rotulados)
    for ini, fim in _documentos(texto):
        if not ignorar.sobrepoe(ini, fim) and not marcacao.sobrepoe(ini, fim):
            achados.append((ini, fim, "documento"))
    for m in _V_CPF.finditer(texto):
        if (cpf_valido(re.sub(r"\D", "", m.group())) and not ignorar.sobrepoe(*m.span())
                and not rotulados.sobrepoe(*m.span()) and not marcacao.sobrepoe(*m.span())
                and not _fracionario(texto, m.start())):
            achados.append((m.start(), m.end(), "cpf"))
    fortes = _Intervalos((a, b) for a, b, _ in achados)
    achados.extend((a, b, tipo) for a, b, tipo in _numeros_ocr(texto, liberados, ocr_paginas)
                   if not fortes.sobrepoe(a, b))
    fortes = _Intervalos((a, b) for a, b, _ in achados)
    for m in _a_partir(_RE_CANDIDATO_TELEFONE, _V_TELEFONE, texto):
        ini, fim = m.span()
        if (ignorar.sobrepoe(ini, fim) or fortes.sobrepoe(ini, fim) or _fracionario(texto, ini)
                or marcacao.sobrepoe(ini, fim) or web.sobrepoe(ini, fim)
                or ignorar_email.sobrepoe(ini, fim) or listas.contem(ini, fim)):
            continue
        digitos = re.sub(r"\D", "", m.group())
        candidatos = {telefone_canonico(m.group()), telefone_canonico(digitos[-9:]),
                      telefone_canonico(digitos[-8:])}
        if candidatos & conjunto:
            continue
        achados.append((ini, fim, "telefone" if _telefone_forte(texto, m) else "_fraco"))
    return [
        {"tipo": "telefone" if tipo == "_fraco" else tipo, "inicio": ini, "fim": fim,
         "forte": tipo != "_fraco"}
        for ini, fim, tipo in sorted(achados)
    ]


# ---------------------------------------------------------------- medição
def medir(pasta: Path, liberados_: Iterable[str] = frozenset(), limite: int = 0) -> dict:
    """Ocorrências que `varrer` ainda acha depois de `mascarar`, nos .txt de `pasta`.

    Só contagens (por tipo e força, e documentos afetados); nenhum valor é guardado.
    """
    conjunto = frozenset(liberados_)
    arquivos = sorted(p for p in Path(pasta).rglob("*.txt") if p.is_file())
    if limite > 0:
        arquivos = arquivos[:limite]
    restantes: dict[str, int] = {}
    mascarados = {tipo: 0 for tipo in TIPOS}
    docs_forte = docs_fraco = 0
    for arquivo in arquivos:
        texto = arquivo.read_text(encoding="utf-8", errors="replace")
        limpo, contagens = mascarar(texto, conjunto)
        for tipo, n in contagens.items():
            mascarados[tipo] += n
        achados = varrer(limpo, conjunto)
        for o in achados:
            chave = f"{o['tipo']}_{'forte' if o['forte'] else 'fraco'}"
            restantes[chave] = restantes.get(chave, 0) + 1
        docs_forte += any(o["forte"] for o in achados)
        docs_fraco += any(not o["forte"] for o in achados)
    return {"documentos": len(arquivos), "mascarados": mascarados,
            "restantes": dict(sorted(restantes.items())),
            "documentos_com_forte": docs_forte, "documentos_com_fraco": docs_fraco}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Mede o que a barreira (varrer) ainda acha depois da máscara; só contagens.")
    parser.add_argument("--medir", type=Path, required=True, help="pasta com um .txt por documento")
    parser.add_argument("--limite", type=int, default=0, help="número máximo de documentos")
    args = parser.parse_args(argv)
    if not args.medir.is_dir():
        print(f"pasta inexistente: {args.medir}", file=sys.stderr)
        return 2
    print(json.dumps(medir(args.medir, liberados(RAIZ), args.limite), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
