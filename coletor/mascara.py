"""Máscara de dados pessoais (LGPD) no texto pesquisável.

Regras de `mascarar`:
- **CPF** é mascarado sempre, de qualquer pessoa, com ou sem pontuação, mas só
  quando os dígitos verificadores são válidos.
- **RG** é mascarado quando o rótulo "RG" ou "R.G." aparece até 20 caracteres antes
  do número; "identidade" só vale como rótulo seguido de "nº"/"n."/":" ou precedido
  de "carteira"/"cédula" (evita "identidade de gênero, Lei 13.709/2018").
- **Telefones** brasileiros (fixos e celulares, com ou sem DDD, com +55, colados a
  "/", "," ou "." como em `Tel.2620-1234` ou `2620-1234/2620-5678`) e **e-mails** são
  mascarados, exceto os liberados: contatos oficiais de vereadores e suplentes
  (`contatos` em `config/perfis.json`), contatos institucionais
  (`contatos_institucionais` em `config/backend.json`) e os domínios
  `@camaraniteroi.rj.gov.br` e `@niteroi.rj.gov.br`, com qualquer subdomínio.

Não são mascarados (proteções contra falso positivo): CEP, CNPJ, processo no padrão
CNJ, número SEI (só nos formatos do SEI logo depois da sigla), matrícula funcional,
valores em R$, datas, intervalos de anos e, para telefones e RG, números precedidos
de lei, decreto, processo, protocolo e afins. Um número de 11 dígitos sem DV de CPF
válido não é CPF. CPF formatado (000.000.000-00) com DV válido é mascarado mesmo
dentro dessas proteções.

`mascarar` é idempotente e devolve a contagem por tipo.

`varrer` é a barreira antes de gravar ou carregar textos: um detector independente e
mais amplo, que não usa as regras de `mascarar`. Procura qualquer sequência de 11
dígitos (com separadores) com DV de CPF válido, qualquer número com forma de telefone
(`\\d{4,5}[ .-]?\\d{4}`, com DDD/+55 opcionais) e qualquer endereço com "@", além do
RG rotulado. Ignora só o que casa com as proteções explícitas de datas (inclusive
intervalos de anos), CEP, CNPJ com DV válido, processo CNJ, "Lei nº …" e valores em
R$. Pode apontar falsos positivos (por exemplo, protocolos com forma de telefone):
quem chama decide. Passe a `varrer` o mesmo conjunto `liberados` usado em `mascarar`.
Devolve só tipo, posição e força (`forte`), nunca o valor; a barreira bloqueia nas
ocorrências fortes.

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
from collections.abc import Iterable
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
_RE_SEPARADOR_TELEFONE = re.compile(r"[ .\-()+]")

TIPOS = ("cpf", "rg", "telefone", "email")
SUBSTITUICOES = {
    "cpf": "[CPF omitido]",
    "rg": "[RG omitido]",
    "telefone": "[telefone omitido]",
    "email": "[e-mail omitido]",
}
DOMINIOS_LIBERADOS = ("camaraniteroi.rj.gov.br", "niteroi.rj.gov.br")

DDDS = frozenset(
    [11, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 24, 27, 28, 31, 32, 33, 34, 35, 37, 38,
     41, 42, 43, 44, 45, 46, 47, 48, 49, 51, 53, 54, 55, 61, 62, 63, 64, 65, 66, 67, 68, 69,
     71, 73, 74, 75, 77, 79, 81, 82, 83, 84, 85, 86, 87, 88, 89, 91, 92, 93, 94, 95, 96, 97,
     98, 99]
)

# Número opcional depois de uma palavra: "nº", "n.", "número", ":" — sem \s* encadeados,
# para não haver retrocesso quadrático em linhas com muitos espaços (saída -layout).
_NUMERO = r"\s*(?:(?:[Nn][º°Oo]?|[Nn][ÚúUu]mero)\.?\s*)?(?:[:.]\s*)?"

# Desempenho: os padrões que varrem o texto inteiro começam por uma classe de caracteres
# ou um literal (o `re` então pula em C até os candidatos); os lookbehinds de borda vêm
# depois do primeiro caractere, como `\d(?<!\d\d)` no lugar de `(?<!\d)\d`.

# ---------------------------------------------------------------- padrões de mascarar
_RE_EMAIL = re.compile(
    r"(?<![\w.%+-])[A-Za-z0-9][A-Za-z0-9._%+-]*@"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,}(?![\w-])"
)
_RE_EMAIL_COMPLETO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_RE_CPF = re.compile(
    r"(?P<a>\d)(?<!\d\d)(?<!\d[.,/-]\d)(?P<b>\d\d)(?P<s1>\.?)(?P<c>\d{3})(?P<s2>\.?)(?P<d>\d{3})"
    r"(?P<s3>[-.]?)(?P<e>\d{2})(?!\d)(?![.,/-]\d)"
)
_RE_RG = re.compile(
    r"(?P<rotulo>[RrIi](?<![\w.][RrIi])"
    r"(?:(?<=[Rr])(?:\.\s?[Gg]\.?|[Gg])|(?<=[Ii])[Dd][Ee][Nn][Tt][Ii][Dd][Aa][Dd][Ee]))(?![\w])"
    r"(?P<meio>[^\d\n\[\]]{0,20}?)"
    r"(?P<numero>\d[\d.\-]{3,15}[\dXx])(?![\d\w])"
)
_RE_MARCA_IDENTIDADE = re.compile(r"\s*(?:n[º°o]?\.|nº|n°|:)", re.I)
_RE_TELEFONE = re.compile(
    r"(?<![\w@+])(?<!\d-)"
    r"(?:(?P<pais>\+ ?55|55)[ .-]?)?"
    r"(?:\( ?(?P<zero1>0)?(?P<ddd1>\d{2}) ?\) ?|(?P<zero2>0)?(?P<ddd2>\d{2})[ .-]?)?"
    r"(?P<assinante>9[ .]?\d{4}|[2-5]\d{3})"
    r"(?P<sep>[ .-]?)"
    r"\d{4}"
    r"(?![\w@])(?!-\d)"
)
# Onde um telefone pode começar: "+", "(" ou o início de uma sequência de dígitos.
_RE_CANDIDATO_TELEFONE = re.compile(r"[+(\d]\d*")

_DATA = r"\d(?<!\d\d)\d?[/.-]\d{1,2}[/.-]\d{2,4}(?!\d)"
_DATA_ISO = r"\d(?<!\d\d)\d{3}-\d{2}-\d{2}(?!\d)"
_ANOS = r"(?:19|20)(?<!\d19)(?<!\d20)\d{2} ?[-–/] ?(?:19|20)\d{2}(?!\d)"
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
               r"(?![\w])(?:\s+[Ff][Uu][Nn][Cc][Ii][Oo][Nn][Aa][Ll])?" + _NUMERO + r"\d[\d./-]*"),
    re.compile(_REAIS),
    re.compile(_DATA),
    re.compile(_DATA_ISO),
    re.compile(_ANOS),
]
# Proteções para telefones e RG: números de atos, processos e documentos.
_PALAVRAS_ATO = (
    r"leis?|decretos?|portarias?|resolu[cç](?:[aã]o|[oõ]es)|emendas?|processos?|protocolos?|"
    r"of[ií]cios?|requerimentos?|indica[cç](?:[aã]o|[oõ]es)|mo[cç](?:[aã]o|[oõ]es)|projetos?|"
    r"pdl|pl|plc|edital|editais|contratos?|conv[eê]nios?|termos?|atas?|sess(?:[aã]o|[oõ]es)|"
    r"art(?:igo)?s?\.?|incisos?|par[aá]grafos?|preg[aã]o|licita[cç](?:[aã]o|[oõ]es)|empenhos?|"
    r"notas? fiscal|notas? fiscais|inscri[cç](?:[aã]o|[oõ]es)|matr[ií]culas?"
)
_QUALIFICADORES = (
    r"municipal|complementar|estadual|federal|ordin[aá]ria|legislativo|administrativo|"
    r"eletr[oô]nico|de lei|de decreto legislativo|de resolu[cç][aã]o|sei"
)
# Consultado só perto de cada candidato (janela antes do número), não no texto inteiro:
# a palavra do ato, qualificadores e "nº" terminando onde o número começa.
_RE_ATO_ANTES = re.compile(
    rf"\b(?:{_PALAVRAS_ATO})(?:\s+(?:{_QUALIFICADORES}))*" + _NUMERO + r"\Z", re.I
)
_JANELA_ATO = 160

# ---------------------------------------------------------------- padrões de varrer
_V_CPF = re.compile(r"\d(?<!\d\d)(?<!\d[ .\-/]\d)(?:[ .\-/]?\d){10}(?![ .\-/]?\d)")
_V_TELEFONE = re.compile(
    r"(?<!\d)(?:\+\s?55[ .-]?)?(?:\(\s?0?\d{2}\s?\)\s?|0?\d{2}[ .-]?)?\d{4,5}[ .-]?\d{4}(?!\d)"
)
_V_EMAIL = re.compile(r"[^\s@<>()\[\]{},;:\"']+@[^\s@<>()\[\]{},;:\"']+\.\w{2,}")
_V_RG = re.compile(
    r"[Rr](?<![\w.][Rr])(?:\.\s?[Gg]\.?|[Gg])(?![\w])[^\d\n\[\]]{0,20}?(\d[\d.\-]{3,15}[\dXx])"
)
_V_PROTECOES = [re.compile(p) for p in (_DATA, _DATA_ISO, _ANOS, _CEP, _CNJ, _REAIS)] + [
    re.compile(r"[Ll](?<!\w[Ll])[Ee][Ii](?![\w])(?:\s+[Cc]omplementar)?"
               r"(?:\s+(?:[Mm]unicipal|[Ee]stadual|[Ff]ederal))?" + _NUMERO + r"\d[\d./-]*\d"),
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
    (como "@camaraniteroi.rj.gov.br"). E-mails ficam em minúsculas e precisam ser
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


def _protegidos(texto: str, padroes) -> _Intervalos:
    return _Intervalos(m.span() for p in padroes for m in p.finditer(texto))


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


def _detectar(texto: str, liberados_: Iterable[str]) -> list[tuple[int, int, str]]:
    """Ocorrências (início, fim, tipo) de `mascarar`, sem sobreposição, em ordem de posição."""
    conjunto, dominios = _preparar(liberados_)
    aceitos = _Aceitos()
    gerais = _protegidos(texto, _PROTECOES_GERAIS)

    if "@" in texto:
        for m in _RE_EMAIL.finditer(texto):
            tipo = "_liberado" if _email_liberado(m.group(), conjunto, dominios) else "email"
            aceitos.incluir(m.start(), m.end(), tipo)

    for m in _RE_RG.finditer(texto):
        ini, fim = m.span("numero")
        if sum(c.isdigit() for c in m.group("numero")) < 5:
            continue
        if m.group("rotulo").lower() == "identidade":
            antes = _dobrar(texto[max(0, m.start() - 25):m.start()])
            if ("carteira" not in antes and "cedula" not in antes
                    and not _RE_MARCA_IDENTIDADE.match(m.group("meio"))):
                continue
        if gerais.sobrepoe(ini, fim) or _numero_de_ato(texto, ini):
            continue
        aceitos.incluir(ini, fim, "rg")

    for m in _RE_CPF.finditer(texto):
        digitos = "".join(m.group(g) for g in "abcde")
        if not cpf_valido(digitos):
            continue
        formatado = m.group("s1") == "." and m.group("s2") == "." and m.group("s3") == "-"
        if not formatado and gerais.sobrepoe(m.start(), m.end()):
            continue
        aceitos.incluir(m.start(), m.end(), "cpf")

    for m in _a_partir(_RE_CANDIDATO_TELEFONE, _RE_TELEFONE, texto):
        ddd = m.group("ddd1") or m.group("ddd2")
        if ddd is not None and int(ddd) not in DDDS:
            continue
        if ddd is None and not m.group("sep"):
            continue  # 8 ou 9 dígitos corridos, sem DDD: ambíguo demais
        ini, fim = m.span()
        if gerais.sobrepoe(ini, fim) or _numero_de_ato(texto, ini):
            continue
        canonico = telefone_canonico(m.group())
        if canonico is not None and canonico in conjunto:
            aceitos.incluir(ini, fim, "_liberado")
            continue
        aceitos.incluir(ini, fim, "telefone")

    return [item for item in aceitos.lista if not item[2].startswith("_")]


# ---------------------------------------------------------------- API
def mascarar(texto: str, liberados: Iterable[str] = frozenset()) -> tuple[str, dict[str, int]]:
    """Texto com os dados pessoais substituídos e a contagem por tipo; idempotente."""
    contagens = {tipo: 0 for tipo in TIPOS}
    partes: list[str] = []
    pos = 0
    for ini, fim, tipo in _detectar(texto, liberados):
        partes.append(texto[pos:ini])
        partes.append(SUBSTITUICOES[tipo])
        contagens[tipo] += 1
        pos = fim
    partes.append(texto[pos:])
    return "".join(partes), contagens


def varrer(texto: str, liberados: Iterable[str] = frozenset()) -> list[dict]:
    """Barreira independente: ocorrências `{tipo, inicio, fim, forte}` suspeitas, sem o valor.

    Mais ampla que `mascarar` (veja o docstring do módulo); use o mesmo `liberados`.
    `forte` é verdadeiro para CPF com DV válido, e-mail, RG com rótulo e telefone com
    separador, parênteses ou +55; telefone só de dígitos corridos é fraco. A barreira
    bloqueia só nas ocorrências fortes; as fracas são contadas para revisão.
    """
    conjunto, dominios = _preparar(liberados)
    ignorar = _Intervalos(
        [m.span() for p in _V_PROTECOES for m in p.finditer(texto)]
        + [m.span() for m in _V_CNPJ.finditer(texto) if cnpj_valido(re.sub(r"\D", "", m.group()))]
    )
    achados: list[tuple[int, int, str]] = []
    for m in (_V_EMAIL.finditer(texto) if "@" in texto else ()):
        email = m.group().strip(".")
        if "@" in email and not _email_liberado(email, conjunto, dominios):
            achados.append((m.start(), m.end(), "email"))
    for m in _V_RG.finditer(texto):
        if sum(c.isdigit() for c in m.group(1)) >= 5 and not ignorar.sobrepoe(*m.span(1)):
            achados.append((m.start(1), m.end(1), "rg"))
    for m in _V_CPF.finditer(texto):
        if cpf_valido(re.sub(r"\D", "", m.group())) and not ignorar.sobrepoe(*m.span()):
            achados.append((m.start(), m.end(), "cpf"))
    fortes = _Intervalos((a, b) for a, b, _ in achados)
    for m in _a_partir(_RE_CANDIDATO_TELEFONE, _V_TELEFONE, texto):
        ini, fim = m.span()
        if ignorar.sobrepoe(ini, fim) or fortes.sobrepoe(ini, fim):
            continue
        digitos = re.sub(r"\D", "", m.group())
        candidatos = {telefone_canonico(m.group()), telefone_canonico(digitos[-9:]),
                      telefone_canonico(digitos[-8:])}
        if candidatos & conjunto:
            continue
        achados.append((ini, fim, "telefone" if _RE_SEPARADOR_TELEFONE.search(m.group()) else "_fraco"))
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
