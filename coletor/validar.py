"""Validação dos dados versionados e da configuração.

Confere, sem alterar nada, a forma de data/proposicoes/<ano>.json, de
data/documentos/<tipo>/<ano>.json (inclusive o formato byte a byte gravado por
coletor.arquivos), do cache da IA (data/classificacao_ia.json), de data/meta.json e
dos arquivos config/curadoria.json e config/vereadores.json, e acusa temporários de
gravação interrompida em data/. Cada verificação é uma função que recebe os dados já
carregados e devolve a lista de problemas encontrados (vazia quando está tudo certo).

Uso: python -m coletor.validar
Sai com código 0 sem problemas e 1 com problemas. As mensagens vão para stderr;
no GitHub Actions (variável GITHUB_ACTIONS definida) saem como anotações ::error::.
Somente biblioteca padrão do Python.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import date
from pathlib import Path

from coletor import documentos as D
from coletor.arquivos import texto_lista
from coletor.site.modelo import DESFECHO_GRUPO

RAIZ = Path(__file__).resolve().parent.parent

DESFECHOS_CONHECIDOS = frozenset(DESFECHO_GRUPO)
RE_NUMERO = re.compile(r"^([1-9]\d*)/(\d{4})$")  # sem zeros à esquerda, como siscam.parse_listagem grava
RE_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RE_HASH = re.compile(r"^[0-9a-f]{16}$")  # hexdigest() do SHA-1 é minúsculo; ver classificar._hash
RE_URL = re.compile(r"^https?://\S+$", re.I)
RE_ANO = re.compile(r"\d{4}")
CAMPOS_DATA = ("data", "data_protocolo")
# "enviado" é gravado só com a data (siscam.data_iso descarta a hora "13:47" do SISCAM)
CAMPOS_DATA_TRAMITACAO = ("enviado", "data_resposta")
CAMPOS_DATA_DOCUMENTO = ("data", "data_protocolo", "detalhe_em", "respondido_em")


# --------------------------------------------------------------------- utilidades
def data_valida(valor: object) -> bool:
    """Aceita None ou uma data de calendário real no formato AAAA-MM-DD."""
    if valor is None:
        return True
    if not isinstance(valor, str) or not RE_DATA.match(valor):
        return False
    try:
        date.fromisoformat(valor)
    except ValueError:
        return False
    return True


def _e_inteiro(valor: object) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool)


def _rotulo(arquivo: str, p: dict) -> str:
    return f"{arquivo}: id {p.get('id')!r} ({p.get('numero')!r})"


# ---------------------------------------------------------------------- proposições
def validar_autoria(autoria: object, rotulo: str) -> list[str]:
    if not isinstance(autoria, list):
        return [f"{rotulo}: 'autoria' deveria ser uma lista, não {type(autoria).__name__}"]
    problemas = []
    for i, autor in enumerate(autoria, 1):
        if not isinstance(autor, dict):
            problemas.append(f"{rotulo}: autor {i} deveria ser um objeto")
            continue
        if not isinstance(autor.get("nome"), str) or not autor["nome"].strip():
            problemas.append(f"{rotulo}: autor {i} sem 'nome'")
        for chave in ("origem", "papel"):
            if not isinstance(autor.get(chave), str):
                problemas.append(f"{rotulo}: autor {i} com '{chave}' ausente ou não textual")
        if "id" not in autor:
            problemas.append(f"{rotulo}: autor {i} sem a chave 'id'")
        elif autor["id"] is not None and not _e_inteiro(autor["id"]):
            problemas.append(f"{rotulo}: autor {i} com 'id' {autor['id']!r}, que não é inteiro nem null")
    return problemas


def validar_registro(p: object, ano: int, arquivo: str) -> list[str]:
    """Confere um registro de data/proposicoes/<ano>.json."""
    if not isinstance(p, dict):
        return [f"{arquivo}: registro deveria ser um objeto, não {type(p).__name__}"]
    rotulo = _rotulo(arquivo, p)
    problemas = []
    if not _e_inteiro(p.get("id")):
        problemas.append(f"{rotulo}: 'id' ausente ou não inteiro")
    numero = p.get("numero")
    m = RE_NUMERO.match(numero) if isinstance(numero, str) else None
    if not m:
        problemas.append(f"{rotulo}: 'numero' fora do formato <n>/<ano>")
    elif int(m.group(2)) != ano:
        problemas.append(f"{rotulo}: 'numero' é de {m.group(2)}, mas está no arquivo de {ano}")
    if p.get("ano") != ano:
        problemas.append(f"{rotulo}: 'ano' {p.get('ano')!r} difere do ano do arquivo ({ano})")
    for chave in CAMPOS_DATA:
        if not data_valida(p.get(chave)):
            problemas.append(f"{rotulo}: '{chave}' {p.get(chave)!r} não é data AAAA-MM-DD nem null")
    if p.get("desfecho") not in DESFECHOS_CONHECIDOS:
        problemas.append(f"{rotulo}: desfecho {p.get('desfecho')!r} desconhecido em coletor/site/modelo.py")
    lei = p.get("lei")
    if lei is not None:
        if not isinstance(lei, dict):
            problemas.append(f"{rotulo}: 'lei' deveria ser um objeto ou null")
        elif not data_valida(lei.get("data")):
            problemas.append(f"{rotulo}: 'lei.data' {lei.get('data')!r} não é data AAAA-MM-DD nem null")
    problemas += validar_autoria(p.get("autoria"), rotulo)
    tramitacoes = p.get("tramitacoes", [])
    if not isinstance(tramitacoes, list):
        problemas.append(f"{rotulo}: 'tramitacoes' deveria ser uma lista")
    else:
        for t in tramitacoes:
            if not isinstance(t, dict):
                problemas.append(f"{rotulo}: tramitação deveria ser um objeto")
                continue
            for chave in CAMPOS_DATA_TRAMITACAO:
                if not data_valida(t.get(chave)):
                    problemas.append(
                        f"{rotulo}: tramitação {t.get('seq')!r} com '{chave}' {t.get(chave)!r} fora do formato AAAA-MM-DD"
                    )
    return problemas


def validar_proposicoes(arquivos: dict[int, object]) -> list[str]:
    """Confere o conteúdo de cada arquivo anual e a unicidade dos ids entre arquivos.

    `arquivos` mapeia o ano do nome do arquivo para o JSON já carregado.
    """
    problemas = []
    origem_id: dict[int, str] = {}
    for ano in sorted(arquivos):
        arquivo = f"data/proposicoes/{ano}.json"
        registros = arquivos[ano]
        if not isinstance(registros, list):
            problemas.append(f"{arquivo}: deveria conter uma lista, não {type(registros).__name__}")
            continue
        for p in registros:
            problemas += validar_registro(p, ano, arquivo)
            if isinstance(p, dict) and _e_inteiro(p.get("id")):
                if p["id"] in origem_id:
                    problemas.append(f"{arquivo}: id {p['id']} repetido (já aparece em {origem_id[p['id']]})")
                else:
                    origem_id[p["id"]] = arquivo
    return problemas


def indices(arquivos: dict[int, object]) -> tuple[set[int], set[str]]:
    """Ids e números de projeto presentes nos arquivos anuais."""
    ids, numeros = set(), set()
    for registros in arquivos.values():
        if not isinstance(registros, list):
            continue
        for p in registros:
            if isinstance(p, dict):
                if _e_inteiro(p.get("id")):
                    ids.add(p["id"])
                if isinstance(p.get("numero"), str):
                    numeros.add(p["numero"])
    return ids, numeros


# ---------------------------------------------------------------------- documentos
def _datas_passo(passo: object, rotulo: str, nome: str) -> list[str]:
    """Confere as datas de um passo de tramitação (último da listagem ou do detalhe)."""
    if not isinstance(passo, dict):
        return [f"{rotulo}: {nome} deveria ser um objeto"]
    return [
        f"{rotulo}: {nome} com '{chave}' {passo.get(chave)!r} fora do formato AAAA-MM-DD"
        for chave in CAMPOS_DATA_TRAMITACAO
        if not data_valida(passo.get(chave))
    ]


def validar_documento(d: object, tipo: str, ano: int, arquivo: str) -> list[str]:
    """Confere um registro de data/documentos/<tipo>/<ano>.json, como coletor.documentos grava."""
    if not isinstance(d, dict):
        return [f"{arquivo}: registro deveria ser um objeto, não {type(d).__name__}"]
    rotulo = _rotulo(arquivo, d)
    problemas = []
    if not _e_inteiro(d.get("id")):
        problemas.append(f"{rotulo}: 'id' ausente ou não inteiro")
    if d.get("tipo") != tipo:
        problemas.append(f"{rotulo}: 'tipo' {d.get('tipo')!r} difere da pasta ({tipo})")
    if not _e_inteiro(d.get("ano")) or d["ano"] != ano:
        problemas.append(f"{rotulo}: 'ano' {d.get('ano')!r} difere do ano do arquivo ({ano})")
    numero = d.get("numero")
    m = RE_NUMERO.match(numero) if isinstance(numero, str) else None
    if not m:
        problemas.append(f"{rotulo}: 'numero' fora do formato <n>/<ano>")
    elif int(m.group(2)) != ano:
        problemas.append(f"{rotulo}: 'numero' é de {m.group(2)}, mas está no arquivo de {ano}")
    for chave in CAMPOS_DATA_DOCUMENTO:
        if not data_valida(d.get(chave)):
            problemas.append(f"{rotulo}: '{chave}' {d.get(chave)!r} não é data AAAA-MM-DD nem null")
    autores = d.get("autores")
    if not isinstance(autores, list):
        problemas.append(f"{rotulo}: 'autores' deveria ser uma lista")
    else:
        for i, autor in enumerate(autores, 1):
            nome = autor.get("nome") if isinstance(autor, dict) else None
            if not isinstance(autor, dict) or not _e_inteiro(autor.get("id")) or not isinstance(nome, str) \
                    or not nome.strip():
                problemas.append(f"{rotulo}: autor {i} da listagem deveria ter 'id' inteiro e 'nome' não vazio")
    n = d.get("n_tramitacoes")
    if not _e_inteiro(n) or n < 0:
        problemas.append(f"{rotulo}: 'n_tramitacoes' {n!r} deveria ser um inteiro maior ou igual a zero")
    if d.get("ultima_tramitacao") is not None:
        problemas += _datas_passo(d["ultima_tramitacao"], rotulo, "'ultima_tramitacao'")
    tem_detalhe = bool(d.get("detalhe_em"))
    if tem_detalhe:
        problemas += validar_autoria(d.get("autoria"), rotulo)
    tramitacoes = d.get("tramitacoes")
    if (tem_detalhe or "tramitacoes" in d) and not isinstance(tramitacoes, list):
        problemas.append(f"{rotulo}: 'tramitacoes' deveria ser uma lista")
    elif isinstance(tramitacoes, list):
        for t in tramitacoes:
            problemas += _datas_passo(t, rotulo, f"tramitação {t.get('seq')!r}" if isinstance(t, dict) else "tramitação")
    dias = d.get("dias_ate_resposta")
    if dias is not None and (not _e_inteiro(dias) or dias < 0):
        problemas.append(f"{rotulo}: 'dias_ate_resposta' {dias!r} deveria ser um inteiro maior ou igual a zero, ou null")
    publicacao = d.get("publicacao")
    if publicacao is not None:
        if not isinstance(publicacao, dict):
            problemas.append(f"{rotulo}: 'publicacao' deveria ser um objeto ou null")
        else:
            if publicacao.get("numero") is not None and not _e_inteiro(publicacao.get("numero")):
                problemas.append(f"{rotulo}: 'publicacao.numero' {publicacao.get('numero')!r} não é inteiro nem null")
            if not data_valida(publicacao.get("data")):
                problemas.append(f"{rotulo}: 'publicacao.data' {publicacao.get('data')!r} não é data AAAA-MM-DD nem null")
    if "detalhe_pendente" in d and d["detalhe_pendente"] is not True:
        problemas.append(f"{rotulo}: 'detalhe_pendente' deveria ser true ou ausente, não {d['detalhe_pendente']!r}")
    elif "detalhe_pendente" not in d and not tem_detalhe and isinstance(autores, list) and D.elegivel_detalhe(d):
        problemas.append(f"{rotulo}: elegível para a página de detalhe, mas sem 'detalhe_em' e sem 'detalhe_pendente'")
    return problemas


def _ordenavel(d: object) -> bool:
    """Se o registro tem o que documentos.chave_arquivo precisa para ordenar o arquivo."""
    return (
        isinstance(d, dict) and _e_inteiro(d.get("ano")) and _e_inteiro(d.get("id"))
        and isinstance(d.get("numero"), str) and bool(RE_NUMERO.match(d["numero"]))
    )


def validar_arquivo_documentos(
    bruto: bytes, tipo: str, ano: int, arquivo: str, origem_id: dict[int, str], ids_proposicoes: set[int]
) -> list[str]:
    """Confere um arquivo de documentos já lido em bytes.

    `origem_id` acumula, entre os arquivos, o primeiro arquivo de cada id; ids repetidos
    entre documentos ou presentes também em `ids_proposicoes` são problema (o
    IdDocumento do SISCAM é único entre os tipos). O conteúdo precisa ser, byte a
    byte, o que coletor.documentos.salvar_ano gravaria: um registro por linha, chaves
    ordenadas, LF e ordem por ano, número e id.
    """
    try:
        registros = json.loads(bruto.decode("utf-8"))
    except ValueError as e:  # inclui UnicodeDecodeError
        return [f"{arquivo}: não foi possível ler o JSON ({e})"]
    if not isinstance(registros, list):
        return [f"{arquivo}: deveria conter uma lista, não {type(registros).__name__}"]
    problemas = []
    for d in registros:
        problemas += validar_documento(d, tipo, ano, arquivo)
        if isinstance(d, dict) and _e_inteiro(d.get("id")):
            if d["id"] in ids_proposicoes:
                problemas.append(f"{arquivo}: id {d['id']} também está em data/proposicoes")
            if d["id"] in origem_id:
                problemas.append(f"{arquivo}: id {d['id']} repetido (já aparece em {origem_id[d['id']]})")
            else:
                origem_id[d["id"]] = arquivo
    if all(_ordenavel(d) for d in registros):
        canonico = texto_lista(sorted(registros, key=D.chave_arquivo)).encode("utf-8")
        if canonico != bruto:
            problemas.append(
                f"{arquivo}: fora do formato gravado por coletor.documentos (um registro por linha, chaves "
                "ordenadas, quebras de linha LF, ordem por ano, número e id); regenere com python -m coletor.documentos"
            )
    return problemas


def validar_documentos(raiz: Path | None = None, ids_proposicoes: set[int] | None = None) -> list[str]:
    """Confere data/documentos/<tipo>/<ano>.json; a pasta é opcional.

    Cada subpasta precisa ser um tipo de coletor.documentos.TIPOS e cada arquivo, um
    <ano>.json; o conteúdo é conferido por validar_arquivo_documentos. Sem
    `ids_proposicoes`, os ids são lidos de data/proposicoes.
    """
    raiz = raiz or RAIZ
    pasta = raiz / "data" / "documentos"
    if not pasta.exists():
        return []
    if not pasta.is_dir():
        return ["data/documentos: deveria ser um diretório"]
    if ids_proposicoes is None:
        ids_proposicoes = indices(carregar_arquivos_anuais(raiz / "data" / "proposicoes")[0])[0]
    problemas = []
    origem_id: dict[int, str] = {}
    for dir_tipo in sorted(pasta.iterdir()):
        if dir_tipo.name.startswith("."):
            continue  # temporários de gravação: veja validar_temporarios
        rotulo_dir = f"data/documentos/{dir_tipo.name}"
        if not dir_tipo.is_dir() or dir_tipo.name not in D.TIPOS:
            problemas.append(f"{rotulo_dir}: esperado um diretório de tipo ({', '.join(D.TIPOS)})")
            continue
        for arq in sorted(dir_tipo.glob("*.json")):
            arquivo = f"{rotulo_dir}/{arq.name}"
            if not RE_ANO.fullmatch(arq.stem):
                problemas.append(f"{arquivo}: nome de arquivo deveria ser <ano>.json")
                continue
            try:
                bruto = arq.read_bytes()
            except OSError as e:
                problemas.append(f"{arquivo}: não foi possível ler o arquivo ({e})")
                continue
            problemas += validar_arquivo_documentos(
                bruto, dir_tipo.name, int(arq.stem), arquivo, origem_id, ids_proposicoes
            )
    return problemas


# ------------------------------------------------------------- meta e temporários
def validar_meta(meta: object) -> list[str]:
    """Confere a forma geral de data/meta.json (escrito pela coleta, pela classificação e pelos documentos)."""
    arquivo = "data/meta.json"
    if not isinstance(meta, dict):
        return [f"{arquivo}: deveria conter um objeto, não {type(meta).__name__}"]
    docs = meta.get("documentos")
    if docs is not None and (not isinstance(docs, dict) or not isinstance(docs.get("tipos"), dict)):
        return [f"{arquivo}: 'documentos' deveria ser um objeto com o mapa 'tipos'"]
    return []


def validar_temporarios(raiz: Path | None = None) -> list[str]:
    """Temporários de coletor.arquivos (.<nome>.<sufixo>.tmp) em data/ indicam gravação interrompida."""
    raiz = raiz or RAIZ
    dados = raiz / "data"
    if not dados.is_dir():
        return []
    return [
        f"{arq.relative_to(raiz).as_posix()}: temporário de gravação interrompida; o arquivo de destino "
        "ficou intacto, apague o temporário"
        for arq in sorted(dados.rglob(".*.tmp"))
    ]


# ------------------------------------------------------------------------ cache IA
def validar_cache_ia(cache: object, ids: set[int]) -> list[str]:
    arquivo = "data/classificacao_ia.json"
    if not isinstance(cache, dict):
        return [f"{arquivo}: deveria conter um objeto, não {type(cache).__name__}"]
    problemas = []
    for chave in sorted(cache):
        item = cache[chave]
        if not chave.isdigit() or int(chave) not in ids:
            problemas.append(f"{arquivo}: chave {chave!r} não corresponde a nenhum id de data/proposicoes")
        if not isinstance(item, dict):
            problemas.append(f"{arquivo}: entrada {chave!r} deveria ser um objeto")
            continue
        h = item.get("hash")
        if not isinstance(h, str) or not RE_HASH.match(h):
            problemas.append(f"{arquivo}: entrada {chave!r} com 'hash' {h!r}, que não tem 16 caracteres hexadecimais")
    return problemas


# ----------------------------------------------------------------------- curadoria
def validar_curadoria(curadoria: object, numeros: set[str]) -> list[str]:
    arquivo = "config/curadoria.json"
    if not isinstance(curadoria, dict) or not isinstance(curadoria.get("entradas"), list):
        return [f"{arquivo}: deveria ser um objeto com a lista 'entradas'"]
    problemas = []
    vistos: set[str] = set()
    for i, e in enumerate(curadoria["entradas"], 1):
        if not isinstance(e, dict):
            problemas.append(f"{arquivo}: entrada {i} deveria ser um objeto")
            continue
        projeto = e.get("projeto")
        rotulo = f"{arquivo}: entrada {i} ({projeto!r})"
        if not isinstance(projeto, str) or not RE_NUMERO.match(projeto):
            problemas.append(f"{rotulo}: 'projeto' fora do formato <n>/<ano>")
        elif projeto not in numeros:
            problemas.append(f"{rotulo}: projeto não existe em data/proposicoes")
        if isinstance(projeto, str):
            if projeto in vistos:
                problemas.append(f"{rotulo}: projeto repetido; só a última entrada seria usada")
            vistos.add(projeto)
        fontes = e.get("fontes")
        if not isinstance(fontes, list) or not any(isinstance(f, str) and RE_URL.match(f) for f in fontes):
            problemas.append(f"{rotulo}: 'fontes' precisa de pelo menos uma URL http(s)")
    return problemas


# ---------------------------------------------------------------------- vereadores
def validar_vereadores(cfg: object) -> list[str]:
    arquivo = "config/vereadores.json"
    if not isinstance(cfg, dict) or not isinstance(cfg.get("legislaturas"), list):
        return [f"{arquivo}: deveria ser um objeto com a lista 'legislaturas'"]
    problemas = []
    for leg in cfg["legislaturas"]:
        if not isinstance(leg, dict):
            problemas.append(f"{arquivo}: legislatura deveria ser um objeto")
            continue
        leg_id = leg.get("id")
        eleitos = leg.get("eleitos")
        if not isinstance(eleitos, list):
            problemas.append(f"{arquivo}: legislatura {leg_id!r} sem a lista 'eleitos'")
            continue
        vistos: set[str] = set()
        for e in eleitos:
            nome = e.get("siscam") if isinstance(e, dict) else None
            if not isinstance(nome, str) or not nome.strip():
                problemas.append(f"{arquivo}: legislatura {leg_id!r} tem eleito sem 'siscam'")
                continue
            if nome != nome.upper():
                problemas.append(f"{arquivo}: legislatura {leg_id!r}: siscam {nome!r} deveria estar em maiúsculas")
            if nome.upper() in vistos:
                problemas.append(f"{arquivo}: legislatura {leg_id!r}: siscam {nome!r} repetido")
            vistos.add(nome.upper())
    for a in cfg.get("afastamentos", []):
        nome = a.get("siscam") if isinstance(a, dict) else None
        if not isinstance(nome, str) or nome != nome.upper():
            problemas.append(f"{arquivo}: afastamento com siscam {nome!r} fora de maiúsculas")
    return problemas


# ------------------------------------------------------------------------ execução
def _ler_json(arq: Path, rotulo: str) -> tuple[object, list[str]]:
    try:
        return json.loads(arq.read_text(encoding="utf-8")), []
    except (OSError, ValueError) as e:
        return None, [f"{rotulo}: não foi possível ler o JSON ({e})"]


def carregar_arquivos_anuais(diretorio: Path) -> tuple[dict[int, object], list[str]]:
    """Lê cada <ano>.json do diretório, sem interpretar o conteúdo."""
    arquivos: dict[int, object] = {}
    problemas = []
    if not diretorio.is_dir():
        return arquivos, ["data/proposicoes: diretório não encontrado"]
    for arq in sorted(diretorio.glob("*.json")):
        rotulo = f"data/proposicoes/{arq.name}"
        if not re.fullmatch(r"\d{4}", arq.stem):
            problemas.append(f"{rotulo}: nome de arquivo deveria ser <ano>.json")
            continue
        conteudo, erros = _ler_json(arq, rotulo)
        problemas += erros
        if not erros:
            arquivos[int(arq.stem)] = conteudo
    if not arquivos and not problemas:
        problemas.append("data/proposicoes: nenhum arquivo <ano>.json encontrado")
    return arquivos, problemas


def validar_tudo(raiz: Path | None = None) -> list[str]:
    """Roda todas as verificações sobre os arquivos de `raiz` (padrão: o repositório)."""
    raiz = raiz or RAIZ
    arquivos, problemas = carregar_arquivos_anuais(raiz / "data" / "proposicoes")
    problemas += validar_proposicoes(arquivos)
    ids, numeros = indices(arquivos)
    problemas += validar_documentos(raiz, ids)

    arq_meta = raiz / "data" / "meta.json"
    if arq_meta.exists():  # escrito pelos coletores; num repositório recém-criado pode faltar
        meta, erros = _ler_json(arq_meta, "data/meta.json")
        problemas += erros or validar_meta(meta)
    problemas += validar_temporarios(raiz)

    arq_ia = raiz / "data" / "classificacao_ia.json"
    if arq_ia.exists():  # o cache é opcional: sem IA, ele pode não existir
        cache, erros = _ler_json(arq_ia, "data/classificacao_ia.json")
        problemas += erros or validar_cache_ia(cache, ids)

    arq_cur = raiz / "config" / "curadoria.json"
    if arq_cur.exists():  # classificar.carregar_curadoria também aceita a ausência
        curadoria, erros = _ler_json(arq_cur, "config/curadoria.json")
        problemas += erros or validar_curadoria(curadoria, numeros)

    cfg, erros = _ler_json(raiz / "config" / "vereadores.json", "config/vereadores.json")
    problemas += erros or validar_vereadores(cfg)
    return problemas


def _anotacao(texto: str) -> str:
    """Escapa a mensagem para o formato de comandos do GitHub Actions."""
    return texto.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main() -> int:
    problemas = validar_tudo()
    no_ci = bool(os.environ.get("GITHUB_ACTIONS"))
    for problema in problemas:
        print(f"::error::{_anotacao(problema)}" if no_ci else problema, file=sys.stderr)
    if problemas:
        print(f"validação: {len(problemas)} problema(s) encontrado(s)", file=sys.stderr)
        return 1
    print("validação: dados e configuração OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
