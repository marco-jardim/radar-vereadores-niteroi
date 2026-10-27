"""Máscara de dados pessoais (LGPD) no texto pesquisável.

Regras:
- **CPF** é mascarado sempre, de qualquer pessoa, com ou sem pontuação, mas só
  quando os dígitos verificadores são válidos.
- **RG** é mascarado sempre que o rótulo "RG", "R.G.", "identidade" ou "carteira de
  identidade" aparece até 20 caracteres antes do número.
- **Telefones** brasileiros (fixos e celulares, com ou sem DDD, com +55) e
  **e-mails** são mascarados, exceto os liberados: contatos oficiais de vereadores e
  suplentes (`contatos` em `config/perfis.json`), contatos institucionais
  (`contatos_institucionais` em `config/backend.json`) e os domínios
  `@camaraniteroi.rj.gov.br` e `@niteroi.rj.gov.br`, com qualquer subdomínio.

Não são mascarados (proteções contra falso positivo): CEP, CNPJ, processo no padrão
CNJ, número SEI, matrícula funcional, valores em R$, datas, intervalos de anos e,
só para telefones, números precedidos de lei, decreto, processo, protocolo e afins.
Um número de 11 dígitos sem DV de CPF válido não é CPF. CPF formatado
(000.000.000-00) com DV válido é mascarado mesmo dentro dessas proteções.

`mascarar` é idempotente e devolve a contagem por tipo. `varrer` refaz a detecção
do zero sobre qualquer texto e devolve só tipo e posição das ocorrências, sem o
valor: é a barreira antes de gravar ou carregar textos.

Somente biblioteca padrão do Python.
"""
from __future__ import annotations

import bisect
import json
import re
from collections.abc import Iterable
from pathlib import Path

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

# ---------------------------------------------------------------- padrões
_RE_EMAIL = re.compile(
    r"(?<![\w.%+-])[A-Za-z0-9][A-Za-z0-9._%+-]*@"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,}(?![\w-])"
)
_RE_CPF = re.compile(
    r"(?<!\d)(?<!\d[.,/-])"
    r"(\d{3})(\.?)(\d{3})(\.?)(\d{3})([-.]?)(\d{2})"
    r"(?!\d)(?![.,/-]\d)"
)
_RE_RG = re.compile(
    r"(?<![\w.])(?:R\.\s?G\.?|RG|identidade)(?![\w])"
    r"[^\d\n\[\]]{0,20}?"
    r"(?P<numero>\d[\d.\-]{3,15}[\dXx]|\d{5})(?![\d\w])",
    re.I,
)
_RE_TELEFONE = re.compile(
    r"(?<![\w@+.,/-])(?<!\d[.,/-])"
    r"(?:(?P<pais>\+ ?55|55)[ .-]?)?"
    r"(?:\( ?(?P<zero1>0)?(?P<ddd1>\d{2}) ?\) ?|(?P<zero2>0)?(?P<ddd2>\d{2})[ .-]?)?"
    r"(?P<assinante>9[ .]?\d{4}|[2-5]\d{3})"
    r"(?P<sep>[ .-]?)"
    r"\d{4}"
    r"(?![\w@])(?![.,/-]?\d)"
)

# Proteções que valem para CPF sem formatação completa e para telefones.
_PROTECOES_GERAIS = [
    re.compile(r"(?<!\d)\d{5}-\d{3}(?!\d)"),                                 # CEP
    re.compile(r"(?<!\d)\d{2}\.\d{3}-\d{3}(?!\d)"),                          # CEP com ponto
    re.compile(r"(?<!\d)\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}(?!\d)"),         # CNPJ
    re.compile(r"(?<!\d)\d{7}-?\d{2}\.?\d{4}\.?\d\.?\d{2}\.?\d{4}(?!\d)"),    # processo CNJ
    re.compile(r"\bSEI\b[^\n\d]{0,15}\d[\d./-]*\d"),                         # número SEI (maiúsculas)
    re.compile(r"\bmatr[ií]cula\b(?:\s+funcional)?\s*(?:n[º°o]?\.?|número|numero)?\s*[:.]?\s*"
               r"\d[\d./-]*\d?", re.I),                                       # matrícula funcional
    re.compile(r"R\$\s*-?\d[\d.,]*"),                                        # valores
    re.compile(r"(?<!\d)\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}(?!\d)"),              # datas
    re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)"),                           # datas ISO
    re.compile(r"(?<!\d)(?:19|20)\d{2} ?[-–/] ?(?:19|20)\d{2}(?!\d)"),        # intervalos de anos
]
# Proteções só para telefones: números de atos, processos e documentos.
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
_PROTECOES_TELEFONE = [
    re.compile(
        rf"\b(?:{_PALAVRAS_ATO})(?:\s+(?:{_QUALIFICADORES}))*\s*(?:n[º°o]?\.?|número|numero)?"
        r"\s*[:.]?\s*\d[\d./-]*\d",
        re.I,
    )
]


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
        if tipo == "email" and "@" in valor:
            valores.add(valor.strip().lower())
        elif tipo == "telefone":
            canonico = telefone_canonico(valor)
            if canonico:
                valores.add(canonico)
    return valores


def liberados(config_raiz: Path) -> set[str]:
    """Contatos que não são mascarados.

    Reúne os `contatos` (com fonte HTTPS) de cada perfil em `config/perfis.json`, os
    `contatos_institucionais` de `config/backend.json` e os domínios institucionais
    (como "@camaraniteroi.rj.gov.br"). E-mails ficam em minúsculas; telefones, na
    forma de `telefone_canonico`. Aceita a raiz do repositório ou a pasta `config/`;
    arquivos ou campos ausentes não liberam nada.
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


def _email_liberado(email: str, liberados_: set[str] | frozenset[str], dominios: tuple[str, ...]) -> bool:
    email = email.lower()
    if email in liberados_:
        return True
    dominio = email.rsplit("@", 1)[1]
    return any(dominio == d or dominio.endswith("." + d) for d in dominios)


def _detectar(texto: str, liberados_: Iterable[str]) -> list[tuple[int, int, str]]:
    """Ocorrências (início, fim, tipo), sem sobreposição, em ordem de posição."""
    conjunto = {v.strip().lower() for v in liberados_}
    dominios = tuple(dict.fromkeys(
        [*DOMINIOS_LIBERADOS, *(v[1:] for v in conjunto if v.startswith("@"))]
    ))
    aceitos = _Aceitos()
    gerais = _protegidos(texto, _PROTECOES_GERAIS)

    for m in _RE_EMAIL.finditer(texto):
        tipo = "_liberado" if _email_liberado(m.group(), conjunto, dominios) else "email"
        aceitos.incluir(m.start(), m.end(), tipo)

    for m in _RE_RG.finditer(texto):
        numero = m.group("numero")
        if sum(c.isdigit() for c in numero) >= 5:
            aceitos.incluir(m.start("numero"), m.end("numero"), "rg")

    for m in _RE_CPF.finditer(texto):
        digitos = m.group(1) + m.group(3) + m.group(5) + m.group(7)
        if not cpf_valido(digitos):
            continue
        formatado = m.group(2) == "." and m.group(4) == "." and m.group(6) == "-"
        if not formatado and gerais.sobrepoe(m.start(), m.end()):
            continue
        aceitos.incluir(m.start(), m.end(), "cpf")

    de_telefone = _protegidos(texto, _PROTECOES_TELEFONE)
    for m in _RE_TELEFONE.finditer(texto):
        ddd = m.group("ddd1") or m.group("ddd2")
        if ddd is not None and int(ddd) not in DDDS:
            continue
        if ddd is None and not m.group("sep"):
            continue  # 8 ou 9 dígitos corridos, sem DDD: ambíguo demais
        ini, fim = m.span()
        if gerais.sobrepoe(ini, fim) or de_telefone.sobrepoe(ini, fim):
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
    """Ocorrências restantes `{tipo, inicio, fim}`, sem o valor; vazio se o texto está limpo."""
    return [{"tipo": tipo, "inicio": ini, "fim": fim} for ini, fim, tipo in _detectar(texto, liberados)]
