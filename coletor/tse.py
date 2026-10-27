"""Importador de dados abertos do TSE para os perfis dos vereadores.

Para cada eleição pedida, baixa (ou reaproveita do cache) três arquivos públicos do
TSE: consulta_cand_<ano>.zip (candidaturas), rede_social_candidato_<ano>.zip (redes
declaradas no registro) e votacao_candidato_munzona_<ano>.zip (votos por zona). Lê
só os CSVs do Rio de Janeiro (_RJ) e os nacionais (_BR), em latin-1 com ponto e
vírgula, sempre em fluxo: o arquivo de votação de 2026 passa de 400 MB.

Pessoas de interesse: todos os eleitos de config/vereadores.json e todas as chaves de
config/perfis.json (inclusive suplentes). O casamento é exato depois da normalização
(sem acentos, maiúsculas, espaços colapsados), pelo nome civil ou social do TSE; sem
ele, tenta o nome de urna (com e sem títulos como DR ou PROFESSOR) e o nome do SISCAM
como subsequência do nome civil, só entre candidaturas de Niterói e do RJ e só com um
único candidato. APELIDOS_TSE lista outras grafias do nome civil no TSE, conferidas à
mão, tentadas como nome exato antes dessas alternativas.
Cargos municipais só valem em Niterói; para cargos estaduais e federais, o nome deve
corresponder a uma única candidatura no RJ. Com várias candidaturas da mesma pessoa no
ano, ficam as aptas e com resultado. Homônimos de outros municípios são ignorados;
casos ambíguos ficam de fora e aparecem no resumo.

Atualiza config/perfis.json no mesmo lugar, preservando a ordem das chaves:
  - "eleicoes" de cada pessoa nos anos processados (a mais recente primeiro);
  - "redes" pela candidatura mais recente encontrada;
  - "votos" ausentes dos mandatos, pela eleição municipal que abriu a legislatura;
  - eleitos ausentes do arquivo entram com os mandatos da configuração.
Nada é inventado: só entra o que está nos arquivos do TSE.

Uso: python -m coletor.tse [--anos 2020,2024,2026] [--cache DIR] [--sem-download]
Somente biblioteca padrão do Python.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import http.client
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from coletor.arquivos import gravar_atomico, salvar_json
from coletor.siscam import USER_AGENT

RAIZ = Path(__file__).resolve().parent.parent
CONFIG = RAIZ / "config" / "vereadores.json"
PERFIS = RAIZ / "config" / "perfis.json"
CACHE_PADRAO = Path(tempfile.gettempdir()) / "radar-tse"
ANOS_PADRAO = "2020,2024,2026"

BASE_TSE = "https://cdn.tse.jus.br/estatistica/sead/odsele"
URL_CANDIDATOS = BASE_TSE + "/consulta_cand/consulta_cand_{ano}.zip"
URL_REDES = BASE_TSE + "/consulta_cand/rede_social_candidato_{ano}.zip"
URL_VOTACAO = BASE_TSE + "/votacao_candidato_munzona/votacao_candidato_munzona_{ano}.zip"
URL_CONJUNTO = "https://dadosabertos.tse.jus.br/dataset/candidatos-{ano}"
URL_RESULTADOS = "https://dadosabertos.tse.jus.br/dataset/resultados-{ano}"
PREFIXO_FONTE_TSE = "https://dadosabertos.tse.jus.br/"
TITULO_CONJUNTO = "TSE — Dados abertos: candidatos {ano}"
TITULO_RESULTADOS = "TSE — Dados abertos: resultados {ano}"

TENTATIVAS = 5
ESPERA = 2  # segundos, multiplicados pelo número da tentativa
TIMEOUT = 120
BLOCO = 1 << 20  # bytes copiados por vez no download
ARQUIVO_VERSOES = "versoes.json"

RE_MEMBRO = re.compile(r"_(RJ|BR)\.(csv|txt)$", re.I)  # _BRASIL.csv (todas as UFs) fica de fora
CARGOS_MUNICIPAIS = frozenset({"VEREADOR", "PREFEITO", "VICE-PREFEITO"})
MUNICIPIO = "NITEROI"
UFS_GERAIS = frozenset({"RJ", "BR"})
SEM_RESULTADO = "Resultado não divulgado"

# ---- casamento de nomes ------------------------------------------------------------
# Nome no SISCAM → outros nomes civis (NM_CANDIDATO) da mesma pessoa no TSE, como em
# arquivos antigos com grafia diferente. São tentados como nome exato depois do nome do
# SISCAM e antes das alternativas automáticas (nome de urna, nome civil parcial), com as
# mesmas regras de ambiguidade. Cada entrada cita a fonte da conferência.
WIKIPEDIA_VEREADORES = "https://pt.wikipedia.org/w/index.php?title=Lista_de_vereadores_de_Niter%C3%B3i&oldid=70206495"
APELIDOS_TSE: dict[str, tuple[str, ...]] = {
    # Gallo: eleito vereador em 1996 (PFL) e 2004 (PL) como "LUIZ CARLOS DE FREITAS" (urna GALLO);
    # conferido em WIKIPEDIA_VEREADORES
    "LUIZ CARLOS GALLO DE FREITAS": ("LUIZ CARLOS DE FREITAS",),
    # Zaf: eleito em 2000 (PSD) como "JOSÉ ANTONIO TORO FERNANDES"; conferido em WIKIPEDIA_VEREADORES
    "JOSÉ ANTONIO TORO FERNANDEZ": ("JOSÉ ANTONIO TORO FERNANDES",),
    # Leandro Portugal: eleito em 2016 (PV, por QP) como "LEANDRO PORTUGAL FRAZEN DE LIMA";
    # conferido em WIKIPEDIA_VEREADORES
    "LEANDRO PORTUGAL FRANZEN DE LIMA": ("LEANDRO PORTUGAL FRAZEN DE LIMA",),
    # confirmado pelo mantenedor em 2026-10-27
    "EMANUEL JORGE ROCHA": ("EMANUEL JORGE MENDES DA ROCHA",),
    # confirmado pelo mantenedor em 2026-10-27
    "BENNY BRIOLLY": ("BENNY BRIOLLY ROSA DA SILVA SANTOS",),
}
# identidade confirmada pelo mantenedor em 2026-10-27; fixada por SQ_CANDIDATO
CANDIDATURAS_FIXADAS: dict[str, dict[int, str]] = {
    "BENNY BRIOLLY": {2020: "190000675864", 2026: "190002543064"},
}
# títulos removidos do início do nome de urna ("DR EMANUEL ROCHA" → "EMANUEL ROCHA")
TITULOS_URNA = frozenset({
    "DR", "DRA", "PROF", "PROFA", "PROFESSOR", "PROFESSORA", "PASTOR", "PASTORA",
    "DELEGADO", "DELEGADA", "CORONEL", "SARGENTO", "CABO",
})
MINIMO_TOKENS_PARCIAL = 3
VIAS_APROXIMADAS = frozenset({"urna", "nome_parcial"})
ROTULOS_VIA = {"apelido_tse": "apelido", "urna": "nome de urna", "nome_parcial": "nome civil parcial"}

LEIA_ME_PADRAO = (
    "Perfis dos vereadores por nome no SISCAM: mandatos, candidaturas (TSE), Câmara, site e redes. "
    "Candidaturas e redes são atualizadas por python -m coletor.tse; revise e abra um PR."
)

# ---- partidos, cargos e resultados -----------------------------------------------
# chaves sem acento e em maiúsculas; siglas fora do mapa ficam como o TSE publica
PARTIDOS = {
    "PC DO B": "PCdoB",
    "PCDOB": "PCdoB",
    "UNIAO": "União Brasil",
    "UNIAO BRASIL": "União Brasil",
    "PODE": "Podemos",
    "PODEMOS": "Podemos",
    "SOLIDARIEDADE": "Solidariedade",
    "CIDADANIA": "Cidadania",
    "REPUBLICANOS": "Republicanos",
    "AVANTE": "Avante",
}
PARTICULAS = frozenset({"de", "da", "do", "das", "dos", "e"})
RESULTADOS = {
    "ELEITO": "Eleito",
    "ELEITA": "Eleita",
    "ELEITO POR QP": "Eleito por QP",
    "ELEITO POR MEDIA": "Eleito por média",
    "MEDIA": "Eleito por média",  # arquivos antigos: eleito pelas sobras ("MÉDIA")
    "SUPLENTE": "Suplente",
    "NAO ELEITO": "Não eleito",
    "2º TURNO": "2º turno",
    "2O TURNO": "2º turno",
}

# ---- redes sociais -----------------------------------------------------------------
REDES = (
    ("instagram", ("instagram.com", "instagr.am")),
    ("facebook", ("facebook.com", "fb.com", "fb.me")),
    ("x", ("twitter.com", "x.com")),
    ("youtube", ("youtube.com", "youtu.be")),
    ("tiktok", ("tiktok.com",)),
    ("threads", ("threads.net", "threads.com")),
    ("linkedin", ("linkedin.com",)),
)
ORDEM_REDES = {rede: i for i, (rede, _) in enumerate(REDES)}
REDES_SEM_CONSULTA = frozenset({"instagram", "x", "tiktok", "threads", "linkedin"})  # perfis não dependem de ?…
PARAMETROS_RASTREIO = frozenset({"igsh", "igshid", "fbclid", "gclid", "mibextid", "si", "feature"})
RE_DOMINIO = re.compile(r"^[\w-]+(?:\.[\w-]+)+(?:[/?:#]|$)")

COLUNAS_CANDIDATOS = (
    "NM_UE", "DS_CARGO", "SQ_CANDIDATO", "NM_CANDIDATO", "NM_URNA_CANDIDATO", "SG_PARTIDO",
    "NR_CANDIDATO", "DS_SIT_TOT_TURNO", "SG_UF", "NR_TURNO", "NM_SOCIAL_CANDIDATO",
    "DS_SITUACAO_CANDIDATURA", "DS_DETALHE_SITUACAO_CAND",
)
OBRIGATORIAS_CANDIDATOS = COLUNAS_CANDIDATOS[:9]
COLUNAS_VOTACAO = ("SQ_CANDIDATO", "QT_VOTOS_NOMINAIS", "NR_TURNO")
OBRIGATORIAS_VOTACAO = COLUNAS_VOTACAO[:2]
COLUNAS_REDES = ("SQ_CANDIDATO", "DS_URL")


# ---- utilidades --------------------------------------------------------------------
def aviso(mensagem: str) -> None:
    print(f"::warning::{mensagem}", file=sys.stderr)


def normalizar(texto: str | None) -> str:
    """Maiúsculas sem acentos (NFD sem marcas combinantes) e espaços colapsados."""
    t = unicodedata.normalize("NFD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.upper().split())


def variantes(nome: str) -> list[str]:
    """Nome normalizado e, se houver sufixo " - APELIDO" (como no SISCAM), o nome sem ele."""
    base = normalizar(nome)
    saida = [base] if base else []
    if " - " in base:
        civil = base.split(" - ", 1)[0].strip()
        if civil and civil not in saida:
            saida.append(civil)
    return saida


def _inteiro(texto: str | None) -> int | None:
    t = (texto or "").strip()
    return int(t) if re.fullmatch(r"\d+", t) else None  # códigos nulos do TSE são negativos (-1, -3)


def _ano(item: Any) -> int:
    try:
        return int(item.get("ano"))
    except (AttributeError, TypeError, ValueError):
        return 0


def _fonte_tse(fonte: Any) -> bool:
    """Fonte (texto ou {"url": …}) que aponta para os dados abertos do TSE."""
    url = fonte.get("url") if isinstance(fonte, dict) else fonte
    return isinstance(url, str) and url.startswith(PREFIXO_FONTE_TSE)


def normalizar_partido(sigla: str | None) -> str | None:
    s = " ".join((sigla or "").split())
    if not s or s.startswith("#"):
        return None
    return PARTIDOS.get(normalizar(s), s)


def titulo_cargo(cargo: str | None) -> str:
    """"DEPUTADO ESTADUAL" → "Deputado Estadual"; "VICE-GOVERNADOR" → "Vice-Governador"."""
    palavras = []
    for i, palavra in enumerate((cargo or "").lower().split()):
        if i and palavra in PARTICULAS:
            palavras.append(palavra)
        else:
            palavras.append("-".join(p[:1].upper() + p[1:] for p in palavra.split("-")))
    return " ".join(palavras)


def resultado(situacao: str | None) -> str:
    """DS_SIT_TOT_TURNO em caixa de frase; #NULO, #NE e vazio viram "Resultado não divulgado"."""
    t = " ".join((situacao or "").split())
    if not t or t.startswith("#"):
        return SEM_RESULTADO
    return RESULTADOS.get(normalizar(t), t[:1].upper() + t[1:].lower())


def rede_do_host(host: str) -> str | None:
    h = (host or "").lower()
    for rede, dominios in REDES:
        if any(h == d or h.endswith("." + d) for d in dominios):
            return rede
    return None


def _rastreio(parametro: str) -> bool:
    p = parametro.lower()
    return p in PARAMETROS_RASTREIO or p.startswith("utm_")


def normalizar_url(bruta: str | None) -> str | None:
    """URL em https, sem fragmento, parâmetros de rastreio nem barra final; None se inválida.

    Texto sem domínio (como "@perfil") não vira URL: o importador não deduz a rede.
    """
    t = (bruta or "").strip()
    if not t or t.startswith("#") or any(c.isspace() for c in t):
        return None
    if "://" not in t:
        if t.startswith("//"):
            t = "https:" + t
        elif RE_DOMINIO.match(t):
            t = "https://" + t
        else:
            return None
    try:
        partes = urllib.parse.urlsplit(t)
        porta = partes.port
    except ValueError:
        return None
    if partes.scheme.lower() not in ("http", "https"):
        return None
    host = (partes.hostname or "").lower().rstrip(".")
    if not host or "." not in host:
        return None
    if porta and porta not in (80, 443):
        host = f"{host}:{porta}"
    rede = rede_do_host(partes.hostname or "")
    consulta = urllib.parse.parse_qsl(partes.query, keep_blank_values=True)
    if rede in REDES_SEM_CONSULTA:
        consulta = []
    elif rede == "facebook":
        consulta = [(k, v) for k, v in consulta if k == "id"]  # profile.php?id=…
    else:
        consulta = [(k, v) for k, v in consulta if not _rastreio(k)]
    caminho = partes.path.rstrip("/")
    return urllib.parse.urlunsplit(("https", host, caminho, urllib.parse.urlencode(consulta), ""))


def redes_declaradas(urls: Iterable[str], ano: int) -> tuple[list[dict], list[str], list[str]]:
    """Separa redes conhecidas, outros sites e textos ignorados, em ordem determinística."""
    redes, sites, ignoradas, vistas = [], [], [], set()
    for bruta in urls:
        url = normalizar_url(bruta)
        if url is None:
            ignoradas.append(bruta)
            continue
        if url in vistas:
            continue
        vistas.add(url)
        rede = rede_do_host(urllib.parse.urlsplit(url).hostname or "")
        if rede:
            redes.append({"rede": rede, "url": url, "fonte": URL_CONJUNTO.format(ano=ano)})
        else:
            sites.append(url)
    redes.sort(key=lambda r: (ORDEM_REDES[r["rede"]], r["url"]))
    return redes, sorted(sites), ignoradas


def interpretar_anos(texto: str) -> list[int]:
    """"2020,2024" ou "2020-2026" (só anos pares, de eleição), do mais recente ao mais antigo."""
    anos: set[int] = set()
    for parte in (texto or "").split(","):
        parte = parte.strip()
        if not parte:
            continue
        m = re.fullmatch(r"(\d{4})(?:-(\d{4}))?", parte)
        if not m:
            raise ValueError(f"ano inválido: {parte!r}")
        inicio, fim = int(m[1]), int(m[2] or m[1])
        if fim < inicio:
            raise ValueError(f"intervalo invertido: {parte!r}")
        if not m[2] and inicio % 2:
            raise ValueError(f"{inicio} não é ano de eleição")
        anos.update(a for a in range(inicio, fim + 1) if a % 2 == 0)
    if not anos:
        raise ValueError("nenhum ano de eleição informado")
    return sorted(anos, reverse=True)


# ---- download com cache ------------------------------------------------------------
class Indisponivel(Exception):
    """O servidor respondeu 4xx: arquivo ainda não publicado ou removido."""


def carregar_versoes(cache: Path) -> dict:
    try:
        dados = json.loads((cache / ARQUIVO_VERSOES).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dados if isinstance(dados, dict) else {}


def salvar_versoes(cache: Path, versoes: dict) -> None:
    salvar_json(cache / ARQUIVO_VERSOES, versoes)


def _versao(cabecalhos: Any) -> dict:
    return {"etag": cabecalhos.get("ETag"), "last_modified": cabecalhos.get("Last-Modified")}


def _mesma_versao(publicada: dict | None, anterior: dict | None) -> bool:
    if not publicada or not anterior:
        return False
    if publicada.get("etag") and anterior.get("etag"):
        return publicada["etag"] == anterior["etag"]
    return bool(publicada.get("last_modified")) and publicada.get("last_modified") == anterior.get("last_modified")


def _esperar(tentativa: int) -> None:
    if tentativa + 1 < TENTATIVAS:
        time.sleep(ESPERA * (tentativa + 1))


def _consultar(url: str) -> dict | None:
    """HEAD: ETag/Last-Modified publicados, ou None se o servidor não os informar."""
    for tentativa in range(TENTATIVAS):
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resposta:
                return _versao(resposta.headers)
        except urllib.error.HTTPError as e:
            if e.code < 500:
                return None  # 404, 405…: o GET decide
        except (OSError, http.client.HTTPException):
            pass
        _esperar(tentativa)
    return None


def _gravar_fluxo(origem: Any, destino: Path) -> None:
    """Copia a resposta em blocos para um temporário e troca o arquivo só se for um zip."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    fd, temporario = tempfile.mkstemp(dir=destino.parent, prefix=f".{destino.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            shutil.copyfileobj(origem, f, BLOCO)
        if not zipfile.is_zipfile(temporario):
            raise zipfile.BadZipFile(f"{destino.name}: o conteúdo baixado não é um zip completo")
        os.replace(temporario, destino)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporario)
        raise


def _baixar(url: str, destino: Path, condicionais: dict[str, str]) -> dict | None:
    """GET condicional; devolve a versão baixada ou None se o servidor respondeu 304."""
    erro: BaseException | None = None
    for tentativa in range(TENTATIVAS):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **condicionais})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resposta:
                versao = _versao(resposta.headers)
                _gravar_fluxo(resposta, destino)
                return versao
        except urllib.error.HTTPError as e:
            if e.code == 304:
                return None
            if e.code < 500:
                raise Indisponivel(f"{url}: HTTP {e.code}") from e
            erro = e
        except (OSError, http.client.HTTPException, zipfile.BadZipFile) as e:
            erro = e
        _esperar(tentativa)
    raise RuntimeError(f"falha ao baixar {url}: {erro}")


def obter(url: str, cache: Path, versoes: dict, sem_download: bool = False) -> Path | None:
    """Caminho local do arquivo, baixando só se a versão publicada mudou.

    Com sem_download, usa apenas o que já está no cache. Falha de rede com cópia
    em cache usa a cópia, com aviso; sem cópia, devolve None (ano indisponível).
    """
    nome = url.rsplit("/", 1)[-1]
    destino = cache / nome
    existente = destino.is_file()
    if sem_download:
        if not existente:
            aviso(f"{nome} não está no cache {cache}; tratado como indisponível")
        return destino if existente else None
    anterior = versoes.get(nome) if existente else None
    if anterior and _mesma_versao(_consultar(url), anterior):
        print(f"{nome}: sem mudança desde o último download")
        return destino
    condicionais = {}
    if anterior and anterior.get("etag"):
        condicionais["If-None-Match"] = anterior["etag"]
    if anterior and anterior.get("last_modified"):
        condicionais["If-Modified-Since"] = anterior["last_modified"]
    try:
        versao = _baixar(url, destino, condicionais)
    except (Indisponivel, RuntimeError) as e:
        if existente:
            aviso(f"{e}; usando a cópia em cache")
            return destino
        aviso(f"{e}; arquivo indisponível")
        return None
    if versao is None:
        print(f"{nome}: sem mudança (304)")
        return destino
    versoes[nome] = {"url": url, **versao}
    print(f"{nome}: baixado ({destino.stat().st_size:,} bytes)")
    return destino


# ---- leitura dos CSVs --------------------------------------------------------------
def membros(arquivo: zipfile.ZipFile) -> list[str]:
    """CSVs do RJ e nacionais (_RJ, _BR), em ordem de nome."""
    return sorted(n for n in arquivo.namelist() if RE_MEMBRO.search(n.rsplit("/", 1)[-1]))


def linhas_csv(caminho: Path, colunas: tuple[str, ...], obrigatorias: tuple[str, ...] = ()) -> Iterator[tuple[str | None, ...]]:
    """Valores das colunas pedidas, linha a linha, sem carregar o arquivo na memória.

    Coluna obrigatória ausente indica layout alterado e levanta ValueError.
    """
    with zipfile.ZipFile(caminho) as arquivo:
        for nome in membros(arquivo):
            with arquivo.open(nome) as bruto:
                texto = io.TextIOWrapper(bruto, encoding="latin-1", newline="")
                leitor = csv.reader(texto, delimiter=";", quotechar='"')
                cabecalho = next(leitor, None)
                if not cabecalho:
                    continue
                cabecalho = [c.strip().removeprefix("ï»¿").removeprefix("\ufeff") for c in cabecalho]
                faltando = [c for c in obrigatorias if c not in cabecalho]
                if faltando:
                    raise ValueError(f"{caminho.name}/{nome}: colunas ausentes {faltando} (layout alterado?)")
                posicoes = [cabecalho.index(c) if c in cabecalho else None for c in colunas]
                for linha in leitor:
                    yield tuple(linha[p].strip() if p is not None and p < len(linha) else None for p in posicoes)


class IndiceCandidatos(dict):
    """Nome normalizado → candidaturas, com a lista das elegíveis para os casamentos aproximados.

    Elegíveis: cargos municipais de Niterói e cargos estaduais/federais do RJ (ou nacionais).
    """

    elegiveis: list[dict]
    por_sq: dict[str, dict]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.elegiveis = []
        self.por_sq = {}


def _elegivel(cargo_chave: str, ue: str, uf: str) -> bool:
    if cargo_chave in CARGOS_MUNICIPAIS:
        return ue == MUNICIPIO
    return uf in UFS_GERAIS


def sem_titulo(nome: str) -> str:
    """Remove títulos do início de um nome já normalizado, mantendo ao menos uma palavra."""
    palavras = nome.split()
    while len(palavras) > 1 and palavras[0].rstrip(".") in TITULOS_URNA:
        palavras.pop(0)
    return " ".join(palavras)


def chaves_urna(urna: str | None) -> frozenset[str]:
    """Nome de urna normalizado, com e sem título; vazio para #NULO."""
    n = normalizar(urna)
    if not n or n.startswith("#"):
        return frozenset()
    return frozenset({n, sem_titulo(n)})


def _apto(situacao: str | None, detalhe: str | None) -> bool | None:
    """APTO/DEFERIDO → True; outra situação informada → False; sem informação → None."""
    for texto in (situacao, detalhe):
        t = normalizar(texto)
        if t and not t.startswith("#"):
            return t == "APTO" or t.startswith("DEFERIDO")
    return None


def ler_candidatos(caminho: Path, alvos: set[str]) -> IndiceCandidatos:
    """Índice nome normalizado → candidaturas (uma por SQ, a do último turno).

    Guarda as candidaturas elegíveis (Niterói e RJ) e, de outros lugares, só as de nome
    exato procurado, para contar homônimos ignorados.
    """
    por_sq: dict[str, dict] = {}
    sqs_fixados = {sq for anos in CANDIDATURAS_FIXADAS.values() for sq in anos.values()}
    for valores in linhas_csv(caminho, COLUNAS_CANDIDATOS, OBRIGATORIAS_CANDIDATOS):
        linha = dict(zip(COLUNAS_CANDIDATOS, valores))
        nomes = sorted({n for n in (normalizar(linha["NM_CANDIDATO"]), normalizar(linha["NM_SOCIAL_CANDIDATO"])) if n})
        sq = linha["SQ_CANDIDATO"]
        if not sq:
            continue
        ue, cargo_chave, uf = normalizar(linha["NM_UE"]), normalizar(linha["DS_CARGO"]), linha["SG_UF"] or ""
        elegivel = _elegivel(cargo_chave, ue, uf)
        if not elegivel and sq not in sqs_fixados and not any(n in alvos for n in nomes):
            continue
        turno = _inteiro(linha["NR_TURNO"]) or 1
        anterior = por_sq.get(sq)
        if anterior is not None and anterior["turno"] >= turno:
            continue
        por_sq[sq] = {
            "sq": sq,
            "nomes": nomes,
            "ue": ue,
            "ue_texto": linha["NM_UE"] or "",
            "cargo": titulo_cargo(linha["DS_CARGO"]),
            "cargo_chave": cargo_chave,
            "uf": uf,
            "partido": normalizar_partido(linha["SG_PARTIDO"]),
            "numero": linha["NR_CANDIDATO"] or "",
            "urna": linha["NM_URNA_CANDIDATO"] or "",
            "chaves_urna": chaves_urna(linha["NM_URNA_CANDIDATO"]),
            "situacao": linha["DS_SIT_TOT_TURNO"] or "",
            "apto": _apto(linha["DS_SITUACAO_CANDIDATURA"], linha["DS_DETALHE_SITUACAO_CAND"]),
            "elegivel": elegivel,
            "turno": turno,
        }
    indice = IndiceCandidatos()
    indice.por_sq = por_sq
    for sq in sorted(por_sq):
        for nome in por_sq[sq]["nomes"]:
            indice.setdefault(nome, []).append(por_sq[sq])
    indice.elegiveis = [por_sq[sq] for sq in sorted(por_sq) if por_sq[sq]["elegivel"]]
    return indice


def somar_votos(caminho: Path, sqs: set[str]) -> dict[str, int]:
    """Votos nominais por SQ, somados em todas as zonas e municípios do arquivo.

    Em cargos com dois turnos, vale a soma do último turno disputado.
    """
    por_turno: dict[str, dict[int, int]] = {}
    for sq, quantidade, turno in linhas_csv(caminho, COLUNAS_VOTACAO, OBRIGATORIAS_VOTACAO):
        if sq not in sqs:
            continue
        votos = _inteiro(quantidade)
        if votos is None:
            continue
        somas = por_turno.setdefault(sq, {})
        t = _inteiro(turno) or 1
        somas[t] = somas.get(t, 0) + votos
    return {sq: somas[max(somas)] for sq, somas in sorted(por_turno.items())}


def ler_redes(caminho: Path, sqs: set[str]) -> dict[str, list[str]]:
    urls: dict[str, list[str]] = {}
    for sq, url in linhas_csv(caminho, COLUNAS_REDES, COLUNAS_REDES):
        if sq in sqs and url:
            urls.setdefault(sq, []).append(url)
    return dict(sorted(urls.items()))


# ---- casamento ---------------------------------------------------------------------
def _municipal(candidato: dict) -> bool:
    return candidato["cargo_chave"] in CARGOS_MUNICIPAIS


def descrever(candidato: dict) -> str:
    local = candidato["ue_texto"] or candidato["uf"]
    return f"{candidato['cargo']} ({local}), nº {candidato['numero']}, {candidato['partido']}, SQ {candidato['sq']}"


def _com_resultado(candidato: dict) -> bool:
    situacao = (candidato.get("situacao") or "").strip()
    return bool(situacao) and not situacao.startswith("#")


def desempatar(candidatos: list[dict]) -> list[dict]:
    """Entre várias candidaturas da mesma pessoa no ano, fica com as válidas.

    Primeiro as aptas (DS_SITUACAO_CANDIDATURA, ou o detalhe deferido); depois, se algum
    resultado foi divulgado, só as com resultado (sem #NULO). Sem nenhuma válida, devolve todas.
    """
    if len(candidatos) <= 1:
        return candidatos
    validos = [c for c in candidatos if c.get("apto") is not False]
    if any(_com_resultado(c) for c in validos):
        validos = [c for c in validos if _com_resultado(c)]
    return validos or candidatos


def _decidir(candidatos: list[dict], via: str, ignorados: list[dict], motivo: str) -> dict:
    escolhidos = desempatar(candidatos)
    if len(escolhidos) == 1:
        return {"estado": "casado", "via": via, "candidato": escolhidos[0], "ambiguos": [], "ignorados": ignorados}
    return {"estado": "ambiguo", "via": via, "motivo": motivo, "candidato": None,
            "ambiguos": candidatos, "ignorados": ignorados}


def _elegiveis(indice: dict[str, list[dict]]) -> list[dict]:
    lista = getattr(indice, "elegiveis", None)
    if lista is not None:
        return lista
    unicos = {c["sq"]: c for candidatos in indice.values() for c in candidatos}
    return [unicos[sq] for sq in sorted(unicos) if _elegivel(unicos[sq]["cargo_chave"], unicos[sq]["ue"], unicos[sq]["uf"])]


def chaves_siscam_urna(nome: str) -> frozenset[str]:
    """Formas do nome do SISCAM comparáveis ao nome de urna: inteiro, sem título e só o apelido."""
    chaves = set()
    for variante in variantes(nome):
        chaves.update({variante, sem_titulo(variante)})
    base = normalizar(nome)
    if " - " in base:
        apelido = base.split(" - ", 1)[1].strip()
        if apelido:
            chaves.update({apelido, sem_titulo(apelido)})
    return frozenset(chaves)


def subsequencia(curto: list[str], longo: list[str]) -> bool:
    """Palavras de curto em ordem dentro de longo, com a primeira e a última iguais (≥ 3 palavras)."""
    if len(curto) < MINIMO_TOKENS_PARCIAL or len(longo) < len(curto):
        return False
    if curto[0] != longo[0] or curto[-1] != longo[-1]:
        return False
    restante = iter(longo)
    return all(palavra in restante for palavra in curto)


def casar(nome: str, indice: dict[str, list[dict]], ano: int | None = None) -> dict:
    """Casamento: municipal só em Niterói; estadual/federal único no RJ.

    Ordem: SQ_CANDIDATO fixado para o ano, se houver; nome exato do SISCAM (e sem o
    apelido " - X"); depois os nomes civis de APELIDOS_TSE, também exatos;
    depois nome de urna, com e sem título; depois nome do
    SISCAM como subsequência do nome civil. As alternativas automáticas só olham as
    candidaturas elegíveis e só valem com um único candidato válido.
    Devolve {"estado": "casado"|"ambiguo"|"sem_candidatura", "via", "candidato",
    "ambiguos", "ignorados"} e, quando ambíguo, "motivo".
    """
    sq_fixado = CANDIDATURAS_FIXADAS.get(nome, {}).get(ano)
    if sq_fixado:
        por_sq = getattr(indice, "por_sq", None)
        if por_sq is None:
            por_sq = {c["sq"]: c for candidatos in indice.values() for c in candidatos}
        candidato = por_sq.get(sq_fixado)
        return {"estado": "casado" if candidato else "sem_candidatura", "via": "sq_fixado",
                "candidato": candidato, "ambiguos": [], "ignorados": []}
    ignorados: list[dict] = []
    exatos = [(v, "nome", "ambíguo") for v in variantes(nome)]
    exatos += [(normalizar(a), "apelido_tse", "ambíguo pelo apelido") for a in APELIDOS_TSE.get(nome, ())]
    for variante, via, motivo in exatos:
        candidatos = indice.get(variante) or []
        relevantes = ([c for c in candidatos if _municipal(c) and c["ue"] == MUNICIPIO]
                      or [c for c in candidatos if not _municipal(c) and c["uf"] in UFS_GERAIS])
        ignorados.extend(c for c in candidatos if c not in relevantes and c not in ignorados)
        if relevantes:
            return _decidir(relevantes, via, ignorados, motivo)
    vazio = {"estado": "sem_candidatura", "via": None, "candidato": None, "ambiguos": [], "ignorados": ignorados}
    elegiveis = _elegiveis(indice)
    chaves = chaves_siscam_urna(nome)
    por_urna = [c for c in elegiveis if c.get("chaves_urna", frozenset()) & chaves]
    if por_urna:
        return _decidir(por_urna, "urna", ignorados, "homônimo pelo nome de urna")
    palavras = [v.split() for v in variantes(nome)]
    parciais = [c for c in elegiveis if any(subsequencia(p, n.split()) for p in palavras for n in c["nomes"])]
    if parciais:
        return _decidir(parciais, "nome_parcial", ignorados, "homônimo pelo nome civil parcial")
    return vazio


def resolver_conflitos(casamentos: dict[str, dict]) -> None:
    """Casamento aproximado que reusa a candidatura de outra pessoa vira homônimo (no lugar)."""
    usos: dict[str, list[str]] = {}
    for nome, casamento in casamentos.items():
        if casamento["estado"] == "casado":
            usos.setdefault(casamento["candidato"]["sq"], []).append(nome)
    for nomes in usos.values():
        if len(nomes) < 2:
            continue
        for nome in nomes:
            casamento = casamentos[nome]
            if casamento.get("via") in VIAS_APROXIMADAS:
                casamentos[nome] = {
                    "estado": "ambiguo", "via": casamento["via"], "candidato": None,
                    "motivo": f"homônimo: candidatura também casada com {', '.join(n for n in nomes if n != nome)}",
                    "ambiguos": [casamento["candidato"]], "ignorados": casamento["ignorados"],
                }


def pessoas_de_interesse(cfg: dict, perfis: dict) -> list[str]:
    """Eleitos da configuração (na ordem das legislaturas) e depois as chaves dos perfis."""
    nomes: list[str] = []
    vistos: set[str] = set()
    eleitos = [e.get("siscam") for leg in cfg.get("legislaturas") or [] for e in leg.get("eleitos") or []]
    for nome in [*eleitos, *(perfis.get("vereadores") or {})]:
        if isinstance(nome, str) and nome and not nome.startswith("_") and nome not in vistos:
            vistos.add(nome)
            nomes.append(nome)
    return nomes


# ---- atualização dos perfis --------------------------------------------------------
def novo_perfil(siscam: str, cfg: dict) -> dict:
    """Perfil mínimo para um eleito ausente, com os mandatos e o partido da configuração."""
    mandatos = {}
    for leg in cfg.get("legislaturas") or []:
        for eleito in leg.get("eleitos") or []:
            if eleito.get("siscam") == siscam and leg.get("id"):
                fontes = [{"titulo": f"Composição eleita da legislatura {leg['id']}", "url": leg["fonte"]}] if leg.get("fonte") else []
                # "votos" só entra quando conhecido (inteiro positivo), por preencher_votos_mandatos
                mandatos[leg["id"]] = {
                    "partido": eleito.get("partido"),
                    "situacao": eleito.get("situacao") or "eleito",
                    "fontes": fontes,
                }
    return {"mandatos": mandatos, "eleicoes": [], "camara": None, "site": None, "redes": []}


def _votos(dados: dict, candidato: dict) -> int | None:
    if dados.get("votos") is None or candidato["uf"] == "BR":
        return None  # cargo nacional: só os arquivos do RJ e BR são lidos
    return dados["votos"].get(candidato["sq"])


def item_eleicao(ano: int, candidato: dict, votos: int | None) -> dict:
    return {
        "ano": ano,
        "cargo": candidato["cargo"],
        "uf": candidato["uf"],
        "partido": candidato["partido"],
        "votos": votos,
        "resultado": resultado(candidato["situacao"]),
        "fonte": {"titulo": TITULO_CONJUNTO.format(ano=ano), "url": URL_CONJUNTO.format(ano=ano)},
    }


def _estado(resultados: dict[int, dict], ano: int, nome: str) -> dict:
    return resultados[ano]["casamentos"].get(nome) or {"estado": "sem_candidatura", "candidato": None}


def atualizar_eleicoes(perfil: dict, nome: str, resultados: dict[int, dict]) -> None:
    """Troca as candidaturas dos anos processados, preservando as demais.

    Ano ambíguo mantém o que havia; ano sem candidatura remove só itens com fonte do TSE.
    """
    mantidas = []
    for item in perfil.get("eleicoes") or []:
        ano = _ano(item)
        if ano not in resultados:
            mantidas.append(item)
            continue
        estado = _estado(resultados, ano, nome)["estado"]
        if estado == "ambiguo" or (estado == "sem_candidatura" and not _fonte_tse(item.get("fonte") if isinstance(item, dict) else None)):
            mantidas.append(item)
    novas = []
    for ano in sorted(resultados, reverse=True):
        casamento = _estado(resultados, ano, nome)
        if casamento["estado"] != "casado":
            continue
        candidato = casamento["candidato"]
        if not candidato["cargo"] or not candidato["partido"] or not re.fullmatch(r"[A-Z]{2}", candidato["uf"]):
            aviso(f"{ano}: candidatura de {nome} sem cargo, partido ou UF válidos ({descrever(candidato)}); ignorada")
            continue
        novas.append(item_eleicao(ano, candidato, _votos(resultados[ano], candidato)))
    perfil["eleicoes"] = sorted([*mantidas, *novas], key=lambda e: -_ano(e))


def atualizar_redes(perfil: dict, nome: str, resultados: dict[int, dict]) -> list[str]:
    """Redes da candidatura mais recente; mantém as de outras fontes que não repetem URL.

    Sem o arquivo de redes daquele ano, nada muda. Devolve os textos ignorados.
    """
    anos = [a for a in sorted(resultados, reverse=True) if _estado(resultados, a, nome)["estado"] == "casado"]
    if not anos or resultados[anos[0]].get("redes") is None:
        return []
    ano = anos[0]
    candidato = resultados[ano]["casamentos"][nome]["candidato"]
    tse, sites, ignoradas = redes_declaradas(resultados[ano]["redes"].get(candidato["sq"], []), ano)
    urls = {r["url"] for r in tse}
    outras = [
        r for r in perfil.get("redes") or []
        if isinstance(r, dict) and not _fonte_tse(r.get("fonte")) and normalizar_url(r.get("url")) not in urls
    ]
    perfil["redes"] = [*tse, *outras]
    if sites and not perfil.get("site"):
        perfil["site"] = sites[0]
    return ignoradas


def preencher_votos_mandatos(perfil: dict, nome: str, cfg: dict, resultados: dict[int, dict]) -> None:
    """Votos ausentes do mandato, pela eleição municipal anterior ao início da legislatura."""
    mandatos = perfil.get("mandatos")
    if not isinstance(mandatos, dict):
        return
    for leg in cfg.get("legislaturas") or []:
        mandato = mandatos.get(leg.get("id"))
        if not isinstance(mandato, dict) or mandato.get("votos") is not None:
            continue
        try:
            eleicao = int(str(leg.get("inicio"))[:4]) - 1
        except ValueError:
            continue
        if eleicao not in resultados:
            continue
        casamento = _estado(resultados, eleicao, nome)
        candidato = casamento["candidato"]
        if casamento["estado"] != "casado" or candidato["cargo_chave"] != "VEREADOR":
            continue
        votos = _votos(resultados[eleicao], candidato)
        if not votos:  # o validador exige inteiro positivo
            continue
        if "votos" in mandato:
            mandato["votos"] = votos
        else:
            # sem a chave, ela entra logo depois de "partido", na ordem do esquema
            itens = list(mandato.items())
            posicao = next((i + 1 for i, (k, _) in enumerate(itens) if k == "partido"), len(itens))
            itens.insert(posicao, ("votos", votos))
            mandato.clear()
            mandato.update(itens)
        fontes = mandato.get("fontes")
        if not isinstance(fontes, list):
            fontes = mandato["fontes"] = []
        fonte = {"titulo": TITULO_RESULTADOS.format(ano=eleicao), "url": URL_RESULTADOS.format(ano=eleicao)}
        if all(not isinstance(f, dict) or f.get("url") != fonte["url"] for f in fontes):
            fontes.append(fonte)


def atualizar_perfis(perfis: dict, cfg: dict, resultados: dict[int, dict]) -> dict:
    """Atualiza perfis["vereadores"] no lugar e devolve o relatório da execução."""
    vereadores = perfis.setdefault("vereadores", {})
    adicionados = []
    pessoas = pessoas_de_interesse(cfg, perfis)
    for nome in pessoas:
        if nome not in vereadores:
            vereadores[nome] = novo_perfil(nome, cfg)
            adicionados.append(nome)
    ignoradas = []
    for nome in pessoas:
        perfil = vereadores[nome]
        if not isinstance(perfil, dict):
            continue
        atualizar_eleicoes(perfil, nome, resultados)
        ignoradas.extend((nome, url) for url in atualizar_redes(perfil, nome, resultados))
        preencher_votos_mandatos(perfil, nome, cfg, resultados)
    anos = {}
    for ano in sorted(resultados, reverse=True):
        casamentos = resultados[ano]["casamentos"]
        anos[ano] = {
            "casados": [n for n in pessoas if casamentos.get(n, {}).get("estado") == "casado"],
            "ambiguos": [(n, casamentos[n].get("motivo") or "ambíguo", [descrever(c) for c in casamentos[n]["ambiguos"]])
                         for n in pessoas if casamentos.get(n, {}).get("estado") == "ambiguo"],
            "aproximados": [(n, casamentos[n]["via"], descrever(casamentos[n]["candidato"])) for n in pessoas
                            if casamentos.get(n, {}).get("estado") == "casado"
                            and casamentos[n].get("via") in (*VIAS_APROXIMADAS, "apelido_tse")],
            "fixados": [(n, casamentos[n]["candidato"]["sq"]) for n in pessoas
                        if casamentos.get(n, {}).get("estado") == "casado"
                        and casamentos[n].get("via") == "sq_fixado"],
            "sem_candidatura": [n for n in pessoas if casamentos.get(n, {}).get("estado", "sem_candidatura") == "sem_candidatura"],
            "homonimos_ignorados": sum(len(c.get("ignorados") or []) for c in casamentos.values()),
            "votacao": resultados[ano].get("votos") is not None,
            "redes": resultados[ano].get("redes") is not None,
        }
    nunca = [n for n in pessoas if all(_estado(resultados, a, n)["estado"] != "casado" for a in resultados)]
    return {"anos": anos, "adicionados": adicionados, "sem_nenhuma": nunca, "urls_ignoradas": ignoradas}


def texto_perfis(perfis: dict) -> str:
    """JSON canônico do arquivo: indent=1, acentos sem escape, ordem das chaves preservada."""
    return json.dumps(perfis, ensure_ascii=False, indent=1) + "\n"


# ---- execução ----------------------------------------------------------------------
def processar_ano(ano: int, pessoas: list[str], alvos: set[str], cache: Path, versoes: dict, sem_download: bool) -> dict | None:
    """Casamentos, votos e redes de uma eleição; None se o arquivo de candidaturas faltar."""
    arquivo = obter(URL_CANDIDATOS.format(ano=ano), cache, versoes, sem_download)
    if arquivo is None:
        aviso(f"candidaturas de {ano} indisponíveis; eleições desse ano ficam como estão")
        return None
    indice = ler_candidatos(arquivo, alvos)
    casamentos = {nome: casar(nome, indice, ano) for nome in pessoas}
    resolver_conflitos(casamentos)
    sqs = {c["candidato"]["sq"] for c in casamentos.values() if c["estado"] == "casado"}
    votos = redes = None
    if sqs:
        arquivo_votos = obter(URL_VOTACAO.format(ano=ano), cache, versoes, sem_download)
        if arquivo_votos is None:
            aviso(f"votação de {ano} indisponível; votos ficam nulos")
        else:
            votos = somar_votos(arquivo_votos, sqs)
        arquivo_redes = obter(URL_REDES.format(ano=ano), cache, versoes, sem_download)
        if arquivo_redes is None:
            aviso(f"redes sociais de {ano} indisponíveis; redes ficam como estão")
        else:
            redes = ler_redes(arquivo_redes, sqs)
    return {"casamentos": casamentos, "votos": votos, "redes": redes}


def imprimir_resumo(relatorio: dict) -> None:
    for ano, r in relatorio["anos"].items():
        print(
            f"{ano}: {len(r['casados'])} casado(s), {len(r['sem_candidatura'])} sem candidatura, "
            f"{len(r['ambiguos'])} ambíguo(s), {r['homonimos_ignorados']} homônimo(s) ignorado(s); "
            f"votação: {'sim' if r['votacao'] else 'não'}; redes: {'sim' if r['redes'] else 'não'}"
        )
        for nome, via, candidato in r["aproximados"]:
            revisao = "confirmado" if via == "apelido_tse" else "confira na revisão"
            print(f"{ano}: {nome} casado por {ROTULOS_VIA[via]} ({revisao}): {candidato}")
        for nome, sq in r.get("fixados", []):
            print(f"{ano}: {nome} fixado por SQ (confirmado): {sq}")
        for nome, motivo, opcoes in r["ambiguos"]:
            aviso(f"{ano}: {nome} {motivo}, ignorado: {'; '.join(opcoes)}")
    if relatorio["sem_nenhuma"]:
        print("Sem candidatura casada nos anos processados: " + ", ".join(relatorio["sem_nenhuma"]))
    if relatorio["adicionados"]:
        print("Perfis adicionados: " + ", ".join(relatorio["adicionados"]))
    for nome, url in relatorio["urls_ignoradas"]:
        print(f"URL de rede social ignorada ({nome}): {url!r}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--anos", default=ANOS_PADRAO, help=f"anos de eleição, separados por vírgula ou em intervalo (padrão {ANOS_PADRAO})")
    ap.add_argument("--cache", default=str(CACHE_PADRAO), help=f"pasta dos arquivos baixados (padrão {CACHE_PADRAO})")
    ap.add_argument("--sem-download", action="store_true", help="usa só os arquivos já presentes no cache")
    ap.add_argument("--perfis", default=str(PERFIS), help=argparse.SUPPRESS)
    ap.add_argument("--vereadores", default=str(CONFIG), help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    try:
        anos = interpretar_anos(args.anos)
    except ValueError as e:
        ap.error(str(e))
    cfg = json.loads(Path(args.vereadores).read_text(encoding="utf-8"))
    caminho_perfis = Path(args.perfis)
    if caminho_perfis.exists():
        texto_antigo = caminho_perfis.read_text(encoding="utf-8")
        perfis = json.loads(texto_antigo)
    else:
        aviso(f"{caminho_perfis} não existe; será criado")
        texto_antigo = None
        perfis = {"_leia_me": LEIA_ME_PADRAO, "vereadores": {}}
    if not isinstance(perfis, dict) or not isinstance(perfis.get("vereadores", {}), dict):
        print(f"::error::{caminho_perfis}: esperado objeto com a chave 'vereadores'", file=sys.stderr)
        return 1
    pessoas = pessoas_de_interesse(cfg, perfis)
    alvos = {v for nome in pessoas for v in variantes(nome)}
    alvos |= {normalizar(apelido) for nome in pessoas for apelido in APELIDOS_TSE.get(nome, ())}
    cache = Path(args.cache)
    versoes = carregar_versoes(cache)
    resultados: dict[int, dict] = {}
    try:
        for ano in anos:
            dados = processar_ano(ano, pessoas, alvos, cache, versoes, args.sem_download)
            if dados is not None:
                resultados[ano] = dados
    except (ValueError, zipfile.BadZipFile, OSError) as e:
        print(f"::error::leitura dos arquivos do TSE interrompida, perfis não alterados: {e}", file=sys.stderr)
        return 1
    finally:
        if not args.sem_download:
            salvar_versoes(cache, versoes)
    relatorio = atualizar_perfis(perfis, cfg, resultados)
    imprimir_resumo(relatorio)
    texto = texto_perfis(perfis)
    if texto != texto_antigo:
        gravar_atomico(caminho_perfis, texto)
        print(f"{caminho_perfis.name}: atualizado")
    else:
        print(f"{caminho_perfis.name}: sem mudanças")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
