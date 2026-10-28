"""Validação dos dados versionados e da configuração.

Confere, sem alterar nada, a forma de data/proposicoes/<ano>.json (inclusive os
substitutivos e a coerência de lei_substitutivo), de
data/documentos/<tipo>/<ano>.json e de data/sessoes/<ano>.json (inclusive o formato
byte a byte gravado por coletor.arquivos; as duas pastas são opcionais), da geometria
opcional (data/geo/bairros.json), dos manifestos opcionais de inteiro teor
(data/textos/manifesto-<ano>.json), do cache da IA (data/classificacao_ia.json), de
data/meta.json e dos arquivos
config/curadoria.json, config/vereadores.json, config/memoria.json, config/perfis.json,
config/backend.json e config/remocoes.json (opcionais os quatro últimos), e acusa temporários de gravação
interrompida em data/. Com --textos DIR, confere também os textos, trechos e a barreira
de PII do worktree dados-textos. Cada verificação é uma função que recebe os dados já
carregados e devolve a lista de problemas encontrados (vazia quando está tudo certo).

Uso: python -m coletor.validar [--textos DIR]
Sai com código 0 sem problemas e 1 com problemas. As mensagens vão para stderr;
no GitHub Actions (variável GITHUB_ACTIONS definida) saem como anotações ::error::.
Somente biblioteca padrão do Python.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from coletor import documentos as D
from coletor import sessoes as S
from coletor import mascara, remocoes, textos, trechos
from coletor.arquivos import texto_lista, texto_mapa
from coletor.regras_documentos import BAIRROS_NITEROI
from coletor.site.modelo import DESFECHO_GRUPO

RAIZ = Path(__file__).resolve().parent.parent

DESFECHOS_CONHECIDOS = frozenset(DESFECHO_GRUPO)
RE_NUMERO = re.compile(r"^([1-9]\d*)/(\d{4})$")  # sem zeros à esquerda, como siscam.parse_listagem grava
RE_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RE_HASH = re.compile(r"^[0-9a-f]{16}$")  # hexdigest() do SHA-1 é minúsculo; ver classificar._hash
RE_URL = re.compile(r"^https?://\S+$", re.I)
RE_ANO = re.compile(r"\d{4}")
RE_HORA = re.compile(r"^\d{2}:\d{2}$")
RE_TIPO_SESSAO = re.compile(r"^[a-z0-9_]+$")  # sessoes.normalizar: "audiencia_publica"
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


CAMPOS_ARQUIVO = {"id", "descricao", "versao", "data", "icone"}


def validar_arquivos(registro: dict, rotulo: str) -> list[str]:
    """Confere a chave opcional 'arquivos' (tabela de arquivos do detalhe no SISCAM).

    Registros coletados antes do suporte não têm a chave; arquivo ainda sem texto extraído não é erro.
    """
    if "arquivos" not in registro:
        return []
    arquivos = registro["arquivos"]
    if not isinstance(arquivos, list):
        return [f"{rotulo}: 'arquivos' deveria ser uma lista"]
    problemas, vistos = [], set()
    for i, a in enumerate(arquivos, 1):
        r = f"{rotulo}: arquivo {i}"
        if not isinstance(a, dict):
            problemas.append(f"{r} deveria ser um objeto")
            continue
        if set(a) != CAMPOS_ARQUIVO:
            problemas.append(f"{r}: campos {sorted(a)} diferem de {sorted(CAMPOS_ARQUIVO)}")
        aid = a.get("id")
        if not _e_inteiro(aid) or aid <= 0:
            problemas.append(f"{r}: 'id' {aid!r} deveria ser inteiro positivo")
        elif aid in vistos:
            problemas.append(f"{r}: id {aid} repetido")
        else:
            vistos.add(aid)
        for chave in ("descricao", "versao", "icone"):
            if not isinstance(a.get(chave), str):
                problemas.append(f"{r}: '{chave}' deveria ser texto")
        if not data_valida(a.get("data")):
            problemas.append(f"{r}: 'data' {a.get('data')!r} não é data AAAA-MM-DD nem null")
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
    problemas += _validar_lei(p.get("lei"), rotulo)
    problemas += validar_autoria(p.get("autoria"), rotulo)
    problemas += validar_tramitacoes(p.get("tramitacoes", []), rotulo)
    problemas += validar_substitutivos(p, rotulo)
    problemas += validar_arquivos(p, rotulo)
    return problemas


def validar_tramitacoes(tramitacoes: object, rotulo: str) -> list[str]:
    if not isinstance(tramitacoes, list):
        return [f"{rotulo}: 'tramitacoes' deveria ser uma lista"]
    problemas = []
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


def _validar_lei(lei: object, rotulo: str) -> list[str]:
    if lei is None:
        return []
    if not isinstance(lei, dict):
        return [f"{rotulo}: 'lei' deveria ser um objeto ou null"]
    if not data_valida(lei.get("data")):
        return [f"{rotulo}: 'lei.data' {lei.get('data')!r} não é data AAAA-MM-DD nem null"]
    return []


def validar_substitutivos(p: dict, rotulo: str) -> list[str]:
    """Confere 'substitutivos' (opcional: registros coletados antes do suporte não têm a chave) e 'lei_substitutivo'.

    lei_substitutivo, quando existe, precisa ser o id de um substitutivo da lista que tenha lei,
    e o PL precisa constar como lei (desfecho virou_lei), como siscam.aplicar_substitutivos grava.
    """
    problemas = []
    com_id: dict[int, dict] = {}
    if "substitutivos" in p:
        substitutivos = p["substitutivos"]
        if not isinstance(substitutivos, list):
            problemas.append(f"{rotulo}: 'substitutivos' deveria ser uma lista")
            substitutivos = []
        for i, s in enumerate(substitutivos, 1):
            r = f"{rotulo}: substitutivo {i}"
            if not isinstance(s, dict):
                problemas.append(f"{r} deveria ser um objeto")
                continue
            sid = s.get("id")
            if not _e_inteiro(sid):
                problemas.append(f"{r}: 'id' ausente ou não inteiro")
            elif sid == p.get("id"):
                problemas.append(f"{r}: 'id' {sid} é o do próprio PL")
            elif sid in com_id:
                problemas.append(f"{r}: id {sid} repetido")
            else:
                com_id[sid] = s
                r = f"{rotulo}: substitutivo {sid}"
            numero = s.get("numero")
            if not isinstance(numero, str) or not re.fullmatch(r"[1-9]\d*", numero):
                problemas.append(f"{r}: 'numero' {numero!r} deveria ser o número sem zeros à esquerda, como texto")
            if not data_valida(s.get("data")):
                problemas.append(f"{r}: 'data' {s.get('data')!r} não é data AAAA-MM-DD nem null")
            if not isinstance(s.get("situacao"), str):
                problemas.append(f"{r}: 'situacao' ausente ou não textual")
            problemas += validar_autoria(s.get("autoria"), r)
            problemas += validar_tramitacoes(s.get("tramitacoes"), r)
            if "lei" not in s:
                problemas.append(f"{r}: sem a chave 'lei'")
            problemas += _validar_lei(s.get("lei"), r)
            problemas += validar_arquivos(s, r)
    if "lei_substitutivo" in p:
        ls = p["lei_substitutivo"]
        if not _e_inteiro(ls):
            problemas.append(f"{rotulo}: 'lei_substitutivo' {ls!r} deveria ser o id inteiro de um substitutivo")
        elif ls not in com_id:
            problemas.append(f"{rotulo}: 'lei_substitutivo' {ls} não está em 'substitutivos'")
        elif not isinstance(com_id[ls].get("lei"), dict):
            problemas.append(f"{rotulo}: 'lei_substitutivo' {ls} aponta para um substitutivo sem lei")
        elif not p.get("lei") or p.get("desfecho") != "virou_lei":
            problemas.append(f"{rotulo}: 'lei_substitutivo' {ls} definido, mas o PL não consta como lei (virou_lei)")
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
    problemas += validar_arquivos(d, rotulo)
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


# ------------------------------------------------------------------------- sessões
def _textos(item: dict, chaves: tuple[str, ...], rotulo: str) -> list[str]:
    return [f"{rotulo}: '{chave}' ausente ou não textual" for chave in chaves if not isinstance(item.get(chave), str)]


def _referencia_documento(item: dict, rotulo: str) -> list[str]:
    """tipo_documento, numero (<n>/<ano> ou null) e ano de uma votação ou de um item de pauta completo."""
    problemas = _textos(item, ("tipo_documento",), rotulo)
    numero, ano = item.get("numero"), item.get("ano")
    m = RE_NUMERO.match(numero) if isinstance(numero, str) else None
    if numero is not None and not m:
        problemas.append(f"{rotulo}: 'numero' {numero!r} fora do formato <n>/<ano>")
    if ano is not None and not _e_inteiro(ano):
        problemas.append(f"{rotulo}: 'ano' {ano!r} não é inteiro nem null")
    elif m and ano != int(m.group(2)):
        problemas.append(f"{rotulo}: 'ano' {ano!r} difere do ano do número {numero!r}")
    return problemas


def _pessoa(item: object, rotulo: str, campo: str) -> list[str]:
    """Vereador da frequência ou de uma votação: nome não vazio (como vem do SISCAM) e o campo do valor."""
    if not isinstance(item, dict):
        return [f"{rotulo} deveria ser um objeto"]
    problemas = _textos(item, (campo,), rotulo)
    if not isinstance(item.get("nome"), str) or not item["nome"].strip():
        problemas.append(f"{rotulo}: 'nome' ausente ou vazio")
    return problemas


def _nomes_repetidos(item: dict, chave: str, rotulo: str) -> list[str]:
    """Lista opcional de nomes repetidos (sessoes.nomes_repetidos): omitida quando vazia."""
    if chave not in item:
        return []
    valor = item[chave]
    if not isinstance(valor, list) or not valor or not all(isinstance(n, str) and n.strip() for n in valor):
        return [f"{rotulo}: '{chave}' deveria ser uma lista não vazia de nomes (ou ausente)"]
    return []


def _item_pauta(p: object, rotulo: str, documentos: list | None = None) -> list[str]:
    """Item de pauta como sessoes.enxugar_pauta grava.

    Sempre id_documento (inteiro, ou null numa linha sem link), fase, prioridade e secao;
    secao_indice, se presente, é a posição em `documentos` (documentos_sessao) de um
    documento com o rótulo `secao`. tipo_documento, numero, ano e ementa vêm todos juntos
    ou nenhum, e são obrigatórios sem id. Não se confere se o id está em data/proposicoes
    ou data/documentos: o que vale é o conjunto de ids do momento da coleta, e um
    documento coletado depois não torna o item inválido.
    """
    if not isinstance(p, dict):
        return [f"{rotulo} deveria ser um objeto"]
    problemas = _textos(p, ("secao", "prioridade", "fase"), rotulo)
    id_doc = p.get("id_documento")
    if "id_documento" not in p or not (id_doc is None or _e_inteiro(id_doc)):
        problemas.append(f"{rotulo}: 'id_documento' deveria ser inteiro ou null")
    if "secao_indice" in p:
        indice = p["secao_indice"]
        documentos = documentos or []
        if not _e_inteiro(indice) or not 0 <= indice < len(documentos):
            problemas.append(f"{rotulo}: 'secao_indice' {indice!r} não é a posição de um documento da sessão")
        elif not isinstance(documentos[indice], dict) or documentos[indice].get("rotulo") != p.get("secao"):
            problemas.append(f"{rotulo}: 'secao_indice' {indice} aponta para um documento de outro rótulo que 'secao'")
    inesperadas = sorted(set(p) - set(S.CAMPOS_PAUTA) - set(S.CAMPOS_PAUTA_DOCUMENTO))
    if inesperadas:
        problemas.append(f"{rotulo}: chave(s) inesperada(s) {', '.join(inesperadas)}")
    presentes = [chave for chave in S.CAMPOS_PAUTA_DOCUMENTO if chave in p]
    if presentes and len(presentes) < len(S.CAMPOS_PAUTA_DOCUMENTO):
        problemas.append(f"{rotulo}: {', '.join(S.CAMPOS_PAUTA_DOCUMENTO)} deveriam vir juntos (há só {', '.join(presentes)})")
    elif presentes:
        problemas += _textos(p, ("ementa",), rotulo) + _referencia_documento(p, rotulo)
    elif id_doc is None:
        problemas.append(f"{rotulo}: item sem 'id_documento' precisa de {', '.join(S.CAMPOS_PAUTA_DOCUMENTO)}")
    return problemas


def _lista(s: dict, chave: str, rotulo: str) -> tuple[list, list[str]]:
    valor = s.get(chave)
    if not isinstance(valor, list):
        return [], [f"{rotulo}: '{chave}' deveria ser uma lista"]
    return valor, []


def _detalhe_sessao(s: dict, rotulo: str) -> list[str]:
    """Campos da página de detalhe, como coletor.sessoes.aplicar_detalhe grava."""
    problemas = _textos(s, ("observacoes",), rotulo)
    documentos, erros = _lista(s, "documentos_sessao", rotulo)
    problemas += erros
    for i, d in enumerate(documentos, 1):
        r = f"{rotulo}: documento da sessão {i}"
        if not isinstance(d, dict):
            problemas.append(f"{r} deveria ser um objeto")
            continue
        problemas += _textos(d, ("rotulo",), r)
        if "url" not in d or not (d["url"] is None or (isinstance(d["url"], str) and RE_URL.match(d["url"]))):
            problemas.append(f"{r}: 'url' deveria ser uma URL http(s) ou null")
    pauta, erros = _lista(s, "pauta", rotulo)
    problemas += erros
    for i, p in enumerate(pauta, 1):
        problemas += _item_pauta(p, f"{rotulo}: item de pauta {i}", documentos)
    frequencia, erros = _lista(s, "frequencia", rotulo)
    problemas += erros + _nomes_repetidos(s, "frequencia_nomes_repetidos", rotulo)
    for i, f in enumerate(frequencia, 1):
        r = f"{rotulo}: frequência {i}"
        problemas += _pessoa(f, r, "situacao")
        if isinstance(f, dict):
            problemas += _textos(f, ("momento",), r)
    votacoes, erros = _lista(s, "votacoes", rotulo)
    problemas += erros
    for i, v in enumerate(votacoes, 1):
        r = f"{rotulo}: votação {i}"
        if not isinstance(v, dict):
            problemas.append(f"{r} deveria ser um objeto")
            continue
        problemas += _textos(v, ("documento", "resultado", "tipo_votacao"), r) + _referencia_documento(v, r)
        problemas += _nomes_repetidos(v, "nomes_repetidos", r)
        # null numa votação sem link de documento: documento e tipo_documento guardam o rótulo
        if "id_documento" not in v or not (v["id_documento"] is None or _e_inteiro(v["id_documento"])):
            problemas.append(f"{r}: 'id_documento' deveria ser inteiro ou null")
        totais = v.get("totais")
        if totais is not None and (
            not isinstance(totais, dict)
            or set(totais) != set(S.CHAVES_TOTAIS)
            or any(t is not None and (not _e_inteiro(t) or t < 0) for t in totais.values())
        ):
            problemas.append(f"{r}: 'totais' deveria ser null ou um objeto com {', '.join(S.CHAVES_TOTAIS)} (inteiros ≥ 0 ou null)")
        votos, erros = _lista(v, "votos", r)
        problemas += erros
        for j, voto in enumerate(votos, 1):
            problemas += _pessoa(voto, f"{r}: voto {j}", "voto")
    return problemas


def validar_sessao(s: object, ano: int, arquivo: str) -> list[str]:
    """Confere um registro de data/sessoes/<ano>.json, como coletor.sessoes grava."""
    if not isinstance(s, dict):
        return [f"{arquivo}: registro deveria ser um objeto, não {type(s).__name__}"]
    rotulo = f"{arquivo}: sessão {s.get('id')!r} ({s.get('titulo')!r})"
    problemas = _textos(s, ("titulo", "tipo_texto", "url"), rotulo)
    if not _e_inteiro(s.get("id")):
        problemas.append(f"{rotulo}: 'id' ausente ou não inteiro")
    # o ano é o da listagem em que a sessão apareceu (o do arquivo), mesmo que o título cite outro
    if not _e_inteiro(s.get("ano")) or s["ano"] != ano:
        problemas.append(f"{rotulo}: 'ano' {s.get('ano')!r} difere do ano do arquivo ({ano})")
    numero = s.get("numero")
    if numero is not None and (not _e_inteiro(numero) or numero < 1):
        problemas.append(f"{rotulo}: 'numero' {numero!r} deveria ser um inteiro positivo ou null")
    if not isinstance(s.get("tipo"), str) or not RE_TIPO_SESSAO.match(s["tipo"]):
        problemas.append(f"{rotulo}: 'tipo' {s.get('tipo')!r} deveria ser o tipo normalizado (minúsculas, sem acentos)")
    for chave in ("data", "detalhe_em"):
        if not data_valida(s.get(chave)):
            problemas.append(f"{rotulo}: '{chave}' {s.get(chave)!r} não é data AAAA-MM-DD nem null")
    if s.get("hora") is not None and not (isinstance(s["hora"], str) and RE_HORA.match(s["hora"])):
        problemas.append(f"{rotulo}: 'hora' {s.get('hora')!r} deveria ser hh:mm ou null")
    tem_detalhe = bool(s.get("detalhe_em"))
    if tem_detalhe or any(chave in s for chave in S.CAMPOS_DETALHE if chave != "detalhe_em"):
        problemas += _detalhe_sessao(s, rotulo)
    if "detalhe_pendente" in s and s["detalhe_pendente"] is not True:
        problemas.append(f"{rotulo}: 'detalhe_pendente' deveria ser true ou ausente, não {s['detalhe_pendente']!r}")
    elif "detalhe_pendente" not in s and not tem_detalhe:
        problemas.append(f"{rotulo}: sem 'detalhe_em' e sem 'detalhe_pendente'")
    return problemas


def _sessao_ordenavel(s: object) -> bool:
    """Se o registro tem o que sessoes.chave_arquivo precisa para ordenar o arquivo."""
    return (
        isinstance(s, dict) and _e_inteiro(s.get("id"))
        and (s.get("numero") is None or _e_inteiro(s["numero"]))
        and all(s.get(chave) is None or isinstance(s[chave], str) for chave in ("data", "hora"))
    )


def validar_arquivo_sessoes(bruto: bytes, ano: int, arquivo: str, origem_id: dict[int, str]) -> list[str]:
    """Confere um arquivo de sessões já lido em bytes.

    `origem_id` acumula, entre os arquivos, o primeiro arquivo de cada id de sessão. O
    conteúdo precisa ser, byte a byte, o que coletor.sessoes.salvar_ano gravaria: um
    registro por linha, chaves ordenadas, LF e ordem por data, hora, número e id. O id
    da sessão é de outra numeração (DetalhesSessao.aspx) e não se compara aos de
    data/proposicoes e data/documentos.
    """
    try:
        registros = json.loads(bruto.decode("utf-8"))
    except ValueError as e:  # inclui UnicodeDecodeError
        return [f"{arquivo}: não foi possível ler o JSON ({e})"]
    if not isinstance(registros, list):
        return [f"{arquivo}: deveria conter uma lista, não {type(registros).__name__}"]
    problemas = []
    for s in registros:
        problemas += validar_sessao(s, ano, arquivo)
        if isinstance(s, dict) and _e_inteiro(s.get("id")):
            if s["id"] in origem_id:
                problemas.append(f"{arquivo}: sessão {s['id']} repetida (já aparece em {origem_id[s['id']]})")
            else:
                origem_id[s["id"]] = arquivo
    if all(_sessao_ordenavel(s) for s in registros):
        canonico = texto_lista(sorted(registros, key=S.chave_arquivo)).encode("utf-8")
        if canonico != bruto:
            problemas.append(
                f"{arquivo}: fora do formato gravado por coletor.sessoes (um registro por linha, chaves ordenadas, "
                "quebras de linha LF, ordem por data, hora, número e id); regenere com python -m coletor.sessoes"
            )
    return problemas


def validar_sessoes(raiz: Path | None = None) -> list[str]:
    """Confere data/sessoes/<ano>.json; a pasta é opcional (a coleta de sessões ainda não roda no CI)."""
    raiz = raiz or RAIZ
    pasta = raiz / "data" / "sessoes"
    if not pasta.exists():
        return []
    if not pasta.is_dir():
        return ["data/sessoes: deveria ser um diretório"]
    problemas = []
    origem_id: dict[int, str] = {}
    for arq in sorted(pasta.glob("*.json")):
        arquivo = f"data/sessoes/{arq.name}"
        if not RE_ANO.fullmatch(arq.stem):
            problemas.append(f"{arquivo}: nome de arquivo deveria ser <ano>.json")
            continue
        try:
            bruto = arq.read_bytes()
        except OSError as e:
            problemas.append(f"{arquivo}: não foi possível ler o arquivo ({e})")
            continue
        problemas += validar_arquivo_sessoes(bruto, int(arq.stem), arquivo, origem_id)
    return problemas


# ---------------------------------------------------------------------- geometria
def validar_geo(geo: object) -> list[str]:
    """Confere a geometria opcional gerada por coletor.geo, sem acessar OSM/Overpass."""
    arquivo = "data/geo/bairros.json"
    if not isinstance(geo, dict):
        return [f"{arquivo}: deveria conter um objeto"]
    problemas = []
    for chave in ("atribuicao", "osm_base"):
        if not isinstance(geo.get(chave), str) or not geo[chave].strip():
            problemas.append(f"{arquivo}: '{chave}' ausente ou vazia")
    if geo.get("licenca") != "ODbL 1.0":
        problemas.append(f"{arquivo}: licença deveria ser ODbL 1.0")
    if not isinstance(geo.get("fonte"), str) or not RE_URL.fullmatch(geo["fonte"]):
        problemas.append(f"{arquivo}: 'fonte' deveria ser uma URL pública")
    viewbox = geo.get("viewbox")
    caixa_valida = (isinstance(viewbox, list) and len(viewbox) == 4 and all(_e_inteiro(v) for v in viewbox)
                    and viewbox[:2] == [0, 0] and viewbox[2] > 0 and viewbox[3] > 0)
    if not caixa_valida:
        problemas.append(f"{arquivo}: 'viewbox' deveria ser [0, 0, largura, altura], com inteiros positivos")
    bairros = geo.get("bairros")
    if not isinstance(bairros, dict):
        return problemas + [f"{arquivo}: 'bairros' deveria ser um objeto com os 52 bairros oficiais"]
    faltam, sobram = set(BAIRROS_NITEROI) - bairros.keys(), bairros.keys() - set(BAIRROS_NITEROI)
    if faltam or sobram:
        problemas.append(f"{arquivo}: esperados os 52 bairros oficiais; faltam {sorted(faltam)}; sobram {sorted(sobram)}")
    for nome, bairro in bairros.items():
        rotulo = f"{arquivo}: bairro {nome!r}"
        if not isinstance(bairro, dict):
            problemas.append(f"{rotulo} deveria ser um objeto")
            continue
        path = bairro.get("path")
        if not isinstance(path, str) or not re.fullmatch(r"(?:M\d+,\d+(?: \d+,\d+){2,}Z)+", path):
            problemas.append(f"{rotulo}: 'path' vazio ou fora do formato de anéis inteiros gerado por coletor.geo")
        if not _e_inteiro(bairro.get("osm_id")) or bairro["osm_id"] <= 0:
            problemas.append(f"{rotulo}: 'osm_id' deveria ser um inteiro positivo")
        centro = bairro.get("centro")
        if not isinstance(centro, list) or len(centro) != 2 or not all(_e_inteiro(v) for v in centro):
            problemas.append(f"{rotulo}: 'centro' deveria ser [x, y], com inteiros")
        elif caixa_valida and not (0 <= centro[0] <= viewbox[2] and 0 <= centro[1] <= viewbox[3]):
            problemas.append(f"{rotulo}: 'centro' fora do viewBox")
    return problemas


# ------------------------------------------------------------- meta e temporários
def validar_meta(meta: object) -> list[str]:
    """Confere a forma geral de data/meta.json (escrito pela coleta, pela classificação, pelos documentos e pelas sessões)."""
    arquivo = "data/meta.json"
    if not isinstance(meta, dict):
        return [f"{arquivo}: deveria conter um objeto, não {type(meta).__name__}"]
    problemas = []
    docs = meta.get("documentos")
    if docs is not None and (not isinstance(docs, dict) or not isinstance(docs.get("tipos"), dict)):
        problemas.append(f"{arquivo}: 'documentos' deveria ser um objeto com o mapa 'tipos'")
    sessoes = meta.get("sessoes")
    if sessoes is not None and (not isinstance(sessoes, dict) or not isinstance(sessoes.get("anos"), dict)):
        problemas.append(f"{arquivo}: 'sessoes' deveria ser um objeto com o mapa 'anos'")
    return problemas


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
def validar_vereadores(cfg: object, perfis: object = None) -> list[str]:
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
    return problemas + _validar_afastamentos(cfg, perfis, arquivo) + _validar_mesa(cfg, arquivo)


def _validar_afastamentos(cfg: dict, perfis: object, arquivo: str) -> list[str]:
    """Licenças e exercício de outros cargos, sem inferir datas nem substituições."""
    itens = cfg.get("afastamentos", [])
    if not isinstance(itens, list):
        return [f"{arquivo}: 'afastamentos' deveria ser uma lista"]
    legs = {leg["id"]: leg for leg in cfg["legislaturas"] if isinstance(leg, dict) and isinstance(leg.get("id"), str)}
    conhecidos = {e["siscam"] for leg in legs.values() for e in leg.get("eleitos") or []
                  if isinstance(e, dict) and isinstance(e.get("siscam"), str)}
    conhecidos |= {n for n in (cfg.get("apelidos") or {}) if isinstance(n, str) and not n.startswith("_")}
    if isinstance(perfis, dict) and isinstance(perfis.get("vereadores"), dict):
        conhecidos |= set(perfis["vereadores"])
    obrigatorios = {"siscam", "legislatura", "cargo", "natureza", "fonte"}
    opcionais = {"inicio", "fim", "aprovacao", "ato", "evidencia", "suplentes", "nota"}
    evidencias = ("ata", "requerimento", "diario_oficial", "prefeitura", "alerj", "imprensa")
    problemas = []
    for i, item in enumerate(itens, 1):
        r = f"{arquivo}: afastamento {i}"
        if not isinstance(item, dict):
            problemas.append(f"{r} deveria ser um objeto")
            continue
        problemas += _memoria_textos(item, tuple(sorted(obrigatorios)), r)
        if item.get("natureza") not in ("cargo", "licenca"):
            problemas.append(f"{r}: 'natureza' deveria ser cargo ou licenca")
        extras = set(item) - obrigatorios - opcionais
        if extras:
            problemas.append(f"{r}: campos desconhecidos: {', '.join(sorted(extras))}")
        nome = item.get("siscam")
        if not isinstance(nome, str) or nome != nome.upper():
            problemas.append(f"{r}: siscam {nome!r} fora de maiúsculas")
        if not isinstance(nome, str) or nome not in conhecidos:
            problemas.append(f"{r}: siscam não está entre os nomes conhecidos")
        leg_id = item.get("legislatura")
        leg = legs.get(leg_id) if isinstance(leg_id, str) else None
        if leg is None:
            problemas.append(f"{r}: legislatura inexistente")
        for chave in ("inicio", "fim", "aprovacao"):
            valor = item.get(chave)
            if not data_valida(valor):
                problemas.append(f"{r}: '{chave}' deveria ser data ISO válida AAAA-MM-DD ou null")
            elif valor is not None and leg is not None:
                anos = _anos_legislatura(leg)
                if anos is not None:
                    inicio = leg.get("inicio") or f"{anos[0]:04d}-01-01"
                    fim = leg.get("fim") or f"{anos[1]:04d}-12-31"
                    if not inicio <= valor <= fim:
                        problemas.append(f"{r}: '{chave}' fora da legislatura")
        inicio, fim = item.get("inicio"), item.get("fim")
        if inicio and fim and data_valida(inicio) and data_valida(fim) and fim < inicio:
            problemas.append(f"{r}: 'fim' anterior a 'inicio'")
        if not _https(item.get("fonte")):
            problemas.append(f"{r}: 'fonte' deveria ser URL HTTPS com host")
        if item.get("ato") is not None and not _https(item["ato"]):
            problemas.append(f"{r}: 'ato' deveria ser URL HTTPS com host ou null")
        if "evidencia" in item and item["evidencia"] not in evidencias:
            problemas.append(f"{r}: 'evidencia' deveria ser {', '.join(evidencias)}")
        if "nota" in item and not _memoria_texto(item["nota"]):
            problemas.append(f"{r}: 'nota' deveria ser texto não vazio")
        suplentes = item.get("suplentes", [])
        if not isinstance(suplentes, list):
            problemas.append(f"{r}: 'suplentes' deveria ser uma lista")
        elif any(not isinstance(n, str) or n not in conhecidos for n in suplentes):
            problemas.append(f"{r}: 'suplentes' deve conter apenas nomes conhecidos do SISCAM")
    return problemas


# ---- mesa diretora
CARGOS_MESA = ("Presidente", "1º Vice-Presidente", "2º Vice-Presidente", "1º Secretário", "2º Secretário",
               "1º Suplente", "2º Suplente")
CAMPOS_MESA = ("siscam", "legislatura", "bienio", "cargo", "fonte")
RE_HTTPS_MESA = re.compile(r"https://[^\s/]+\.[^\s/]+(/\S*)?")


def _anos_legislatura(leg: dict) -> tuple[int, int] | None:
    """Anos de início e fim por 'inicio'/'fim' ou, na falta deles, pelo id AAAA-AAAA."""
    inicio, fim = str(leg.get("inicio") or "")[:4], str(leg.get("fim") or "")[:4]
    if not (inicio.isdigit() and fim.isdigit()):
        m = re.fullmatch(r"(\d{4})-(\d{4})", str(leg.get("id") or ""))
        if not m:
            return None
        inicio, fim = m[1], m[2]
    return int(inicio), int(fim)


def _validar_mesa(cfg: dict, arquivo: str) -> list[str]:
    """Composição da Mesa Diretora por biênio (chave opcional 'mesa')."""
    mesa = cfg.get("mesa")
    if mesa is None:
        return []
    if not isinstance(mesa, list):
        return [f"{arquivo}: 'mesa' deveria ser uma lista"]
    legs = {leg["id"]: leg for leg in cfg["legislaturas"] if isinstance(leg, dict) and isinstance(leg.get("id"), str)}
    eleitos = {leg_id: {e.get("siscam") for e in leg.get("eleitos") or [] if isinstance(e, dict)} for leg_id, leg in legs.items()}
    conhecidos = set().union(*eleitos.values()) if eleitos else set()
    conhecidos |= {n for n in (cfg.get("apelidos") or {}) if isinstance(n, str) and not n.startswith("_")}
    problemas = []
    cargos: dict[tuple[tuple[str, str], str], str] = {}  # ((legislatura, biênio), cargo) → siscam
    pessoas: dict[tuple[tuple[str, str], str], str] = {}  # ((legislatura, biênio), siscam) → cargo
    for i, item in enumerate(mesa, 1):
        r = f"{arquivo}: mesa {i}"
        if not isinstance(item, dict):
            problemas.append(f"{r} deveria ser um objeto")
            continue
        faltando = [c for c in CAMPOS_MESA if not _memoria_texto(item.get(c))]
        if faltando:
            problemas.append(f"{r}: campos ausentes ou vazios: {', '.join(faltando)}")
            continue
        extras = set(item) - set(CAMPOS_MESA)
        if extras:
            problemas.append(f"{r}: campos desconhecidos: {', '.join(sorted(extras))}")
        nome, leg_id, bienio, cargo = item["siscam"], item["legislatura"], item["bienio"], item["cargo"]
        r = f"{arquivo}: mesa {i} ({nome}, {bienio})"
        leg = legs.get(leg_id)
        if leg is None:
            problemas.append(f"{r}: legislatura {leg_id!r} inexistente")
        m = re.fullmatch(r"(\d{4})-(\d{4})", bienio)
        anos = _anos_legislatura(leg) if leg is not None else None
        if not m or int(m[2]) != int(m[1]) + 1:
            problemas.append(f"{r}: 'bienio' deveria ser AAAA-AAAA, com anos consecutivos")
        elif anos is not None and not (anos[0] <= int(m[1]) and int(m[2]) <= anos[1]):
            problemas.append(f"{r}: biênio fora da legislatura {leg_id}")
        if cargo not in CARGOS_MESA:
            problemas.append(f"{r}: 'cargo' deveria ser {', '.join(CARGOS_MESA)}")
        if nome not in eleitos.get(leg_id, set()) and nome not in conhecidos:
            problemas.append(f"{r}: siscam {nome!r} não está entre os eleitos da legislatura nem entre os nomes conhecidos")
        if not RE_HTTPS_MESA.fullmatch(item["fonte"]):
            problemas.append(f"{r}: 'fonte' deveria ser URL HTTPS")
        chave = (leg_id, bienio)
        if (chave, cargo) in cargos:
            problemas.append(f"{r}: cargo {cargo!r} repetido no biênio (já ocupado por {cargos[(chave, cargo)]})")
        else:
            cargos[(chave, cargo)] = nome
        if (chave, nome) in pessoas:
            problemas.append(f"{r}: mesma pessoa com dois cargos no biênio ({pessoas[(chave, nome)]} e {cargo})")
        else:
            pessoas[(chave, nome)] = cargo
    return problemas


# ------------------------------------------------------------------------- memória
def _memoria_texto(valor: object) -> bool:
    return isinstance(valor, str) and bool(valor.strip())


def _memoria_textos(item: dict, chaves: tuple[str, ...], rotulo: str) -> list[str]:
    return [
        f"{rotulo}: '{chave}' ausente ou vazio; deveria ser texto não vazio"
        for chave in chaves if not _memoria_texto(item.get(chave))
    ]


def _memoria_data(valor: object) -> tuple[int, int, int] | None:
    """Data parcial ordenável: um ano sem mês/dia vem antes das datas completas desse ano."""
    if not isinstance(valor, str):
        return None
    if RE_ANO.fullmatch(valor):
        return int(valor), 0, 0
    if RE_DATA.fullmatch(valor):
        try:
            data = date.fromisoformat(valor)
        except ValueError:
            return None
        return data.year, data.month, data.day
    return None


def _memoria_fontes(fontes: object, rotulo: str) -> list[str]:
    if not isinstance(fontes, list) or not fontes:
        return [f"{rotulo}: 'fontes' precisa de pelo menos uma fonte com título e URL HTTPS"]
    problemas = []
    for i, fonte in enumerate(fontes, 1):
        r = f"{rotulo}: fonte {i}"
        if not isinstance(fonte, dict):
            problemas.append(f"{r} deveria ser um objeto")
            continue
        problemas += _memoria_textos(fonte, ("titulo",), r)
        if not isinstance(fonte.get("url"), str) or not re.fullmatch(r"https://[^\s/]+\.[^\s/]+(/\S*)?", fonte["url"]):
            problemas.append(f"{r}: 'url' deveria ser HTTPS com host contendo ponto e sem espaços")
    return problemas


def _memoria_nfc(valor: object, rotulo: str) -> list[str]:
    """Confere todas as strings, inclusive chaves e campos editoriais opcionais."""
    if isinstance(valor, str):
        return [] if unicodedata.is_normalized("NFC", valor) else [f"{rotulo}: texto fora da normalização NFC"]
    problemas = []
    if isinstance(valor, dict):
        for chave, item in valor.items():
            problemas += _memoria_nfc(chave, f"{rotulo}: chave {chave!r}")
            problemas += _memoria_nfc(item, f"{rotulo}.{chave}")
    elif isinstance(valor, list):
        for i, item in enumerate(valor, 1):
            problemas += _memoria_nfc(item, f"{rotulo}[{i}]")
    return problemas


def _validar_formato_config(dados: object, bruto: bytes, arquivo: str) -> list[str]:
    """Formato comum dos configs editoriais, preservando a ordem das chaves."""
    problemas = _memoria_nfc(dados, arquivo)
    try:
        canonico = (json.dumps(dados, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    except UnicodeEncodeError:
        problemas.append(f"{arquivo}: texto não representável em UTF-8")
    else:
        if bruto != canonico:
            problemas.append(f"{arquivo}: fora do formato esperado (UTF-8, indentação de 1 espaço, "
                             "ordem das chaves preservada, quebras LF e quebra final)")
    return problemas


def _memoria_imagem(imagem: object, rotulo: str, ano_atual: int) -> list[str]:
    if not isinstance(imagem, dict):
        return [f"{rotulo}: 'imagem' deveria ser um objeto"]
    r = f"{rotulo}: imagem"
    problemas = _memoria_textos(imagem, ("credito",), r)
    tipo = imagem.get("tipo")
    if tipo not in ("propria", "dominio_publico"):
        problemas.append(f"{r}: 'tipo' deveria ser propria ou dominio_publico")
    if tipo == "dominio_publico":
        if imagem.get("obra") != "fotografia":
            problemas.append(f"{r}: domínio público só para fotografia (art. 44); outras obras exigem análise do art. 41")
        problemas += _memoria_textos(imagem, ("autor",), r)
        origem = imagem.get("url_origem")
        if not isinstance(origem, str) or not re.fullmatch(r"https://[^\s/]+\.[^\s/]+(/\S*)?", origem):
            problemas.append(f"{r}: 'url_origem' deveria ser HTTPS com host contendo ponto e sem espaços")
        ano = imagem.get("ano_divulgacao")
        if not _e_inteiro(ano):
            problemas.append(f"{r}: 'ano_divulgacao' deveria ser inteiro")
        elif ano + 70 >= ano_atual:
            problemas.append(
                f"{r}: domínio público exige ano_divulgacao + 70 < {ano_atual} "
                "(art. 44 da Lei 9.610/98)"
            )
    return problemas


def validar_memoria(caminho: Path | None = None, hoje: date | None = None) -> list[str]:
    """Confere conteúdo, fontes, direitos das imagens e bytes de config/memoria.json, sem rede."""
    caminho = caminho or RAIZ / "config" / "memoria.json"
    arquivo = "config/memoria.json"
    try:
        bruto = caminho.read_bytes()
    except FileNotFoundError:
        aviso = f"{arquivo}: arquivo ausente; página de memória sem configuração"
        print(f"::warning::{_anotacao(aviso)}" if os.environ.get("GITHUB_ACTIONS") else f"aviso: {aviso}", file=sys.stderr)
        return []
    except OSError as e:
        return [f"{arquivo}: não foi possível ler o arquivo ({e})"]
    try:
        dados = json.loads(bruto.decode("utf-8"))
    except ValueError as e:  # inclui UnicodeDecodeError
        return [f"{arquivo}: não foi possível ler o JSON ({e})"]

    problemas = _validar_formato_config(dados, bruto, arquivo)
    if not isinstance(dados, dict):
        return problemas + [f"{arquivo}: deveria conter um objeto"]
    problemas += _memoria_textos(dados, ("criterios",), arquivo)
    pessoas, erros = _lista(dados, "homenageados", arquivo)
    problemas += erros
    vistos: set[str] = set()
    hoje = hoje or date.today()
    limite = (hoje.year, hoje.month, hoje.day)
    ano_atual = hoje.year
    for i, pessoa in enumerate(pessoas, 1):
        r = f"{arquivo}: homenageado {i}"
        if not isinstance(pessoa, dict):
            problemas.append(f"{r} deveria ser um objeto")
            continue
        problemas += _memoria_textos(pessoa, ("id", "nome", "nome_completo", "categoria", "vinculo", "emblema"), r)
        identificador = pessoa.get("id")
        if not isinstance(identificador, str) or not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", identificador):
            problemas.append(f"{r}: 'id' deveria conter minúsculas e números separados por hífen")
        if isinstance(identificador, str):
            if identificador in vistos:
                problemas.append(f"{r}: id {identificador!r} repetido")
            vistos.add(identificador)
        if pessoa.get("categoria") not in ("fundacao", "ciencia", "artes", "musica", "arquitetura"):
            problemas.append(f"{r}: 'categoria' desconhecida")
        biografia = pessoa.get("biografia")
        if not isinstance(biografia, list) or not biografia or not all(_memoria_texto(t) for t in biografia):
            problemas.append(f"{r}: 'biografia' deveria ser uma lista não vazia de textos não vazios")
        for chave in ("nascimento", "morte"):
            if chave not in pessoa:
                problemas.append(f"{r}: sem a chave '{chave}'")
            elif pessoa[chave] is not None and _memoria_data(pessoa[chave]) is None:
                problemas.append(f"{r}: '{chave}' deveria ser AAAA, data válida AAAA-MM-DD ou null")
        nascimento = _memoria_data(pessoa.get("nascimento"))
        morte = _memoria_data(pessoa.get("morte"))
        if morte is not None:
            if morte > limite:
                problemas.append(f"{r}: 'morte' posterior a hoje")
            morte_fim = (morte[0], 12, 31) if morte[1] == 0 else morte
            if nascimento is not None and morte_fim < nascimento:
                problemas.append(f"{r}: 'morte' anterior a 'nascimento'")
        for chave in ("nascimento_texto", "morte_texto", "lugar_de_memoria"):
            if chave in pessoa:
                problemas += _memoria_textos(pessoa, (chave,), r)
        if pessoa.get("nascimento") is None and not _memoria_texto(pessoa.get("nascimento_texto")):
            problemas.append(f"{r}: nascimento null exige 'nascimento_texto' não vazio")
        if pessoa.get("morte") is None and not _memoria_texto(pessoa.get("morte_texto")):
            problemas.append(f"{r}: somente falecidos; informe 'morte' ou 'morte_texto' não vazio")
        emblema = pessoa.get("emblema")
        if not isinstance(emblema, str) or not re.fullmatch(r"[a-z0-9-]+\.svg", emblema):
            problemas.append(f"{r}: 'emblema' deveria ser um nome SVG sem diretórios ([a-z0-9-]+.svg)")
        problemas += _memoria_imagem(pessoa.get("imagem"), r, ano_atual)
        problemas += _memoria_fontes(pessoa.get("fontes"), r)

    eventos, erros = _lista(dados, "linha_do_tempo", arquivo)
    problemas += erros
    anterior: tuple[int, int, int] | None = None
    for i, evento in enumerate(eventos, 1):
        r = f"{arquivo}: evento {i}"
        if not isinstance(evento, dict):
            problemas.append(f"{r} deveria ser um objeto")
            continue
        problemas += _memoria_textos(evento, ("titulo", "texto"), r)
        inicio = _memoria_data(evento.get("data"))
        if inicio is None:
            problemas.append(f"{r}: 'data' deveria ser AAAA ou data válida AAAA-MM-DD")
        else:
            if inicio > limite:
                problemas.append(f"{r}: 'data' posterior a hoje")
            if anterior is not None and inicio < anterior:
                problemas.append(f"{r}: linha_do_tempo fora de ordem por 'data'")
            anterior = inicio
        if "data_fim" in evento:
            fim = _memoria_data(evento["data_fim"])
            if fim is not None and fim[1:] == (0, 0):
                fim = (fim[0], 12, 31)
            if fim is None:
                problemas.append(f"{r}: 'data_fim' deveria ser AAAA ou data válida AAAA-MM-DD")
            elif inicio is not None and fim < inicio:
                problemas.append(f"{r}: 'data_fim' anterior a 'data'")
        problemas += _memoria_fontes(evento.get("fontes"), r)
    return problemas


# ------------------------------------------------------------------------ execução
# ---- perfis
REDES_PERFIL = ("instagram", "facebook", "x", "youtube", "tiktok", "threads", "linkedin")
SITUACOES_PERFIL = ("eleito", "eleita", "suplente")
CAMPOS_PERFIL = {"mandatos", "eleicoes", "camara", "site", "redes", "falecimento", "contatos"}
URL_HTTPS = r"https://[^\s/]+\.[^\s/]+(/\S*)?"


def _https(valor: object) -> bool:
    return isinstance(valor, str) and re.fullmatch(URL_HTTPS, valor) is not None


def _perfil_eleicoes(eleicoes: object, r: str) -> list[str]:
    """Outras eleições (dados do TSE), da mais recente para a mais antiga."""
    if not isinstance(eleicoes, list):
        return [f"{r}: 'eleicoes' deveria ser uma lista"]
    problemas = []
    anos = []
    for i, e in enumerate(eleicoes, 1):
        re_ = f"{r}: eleição {i}"
        if not isinstance(e, dict):
            problemas.append(f"{re_} deveria ser um objeto")
            continue
        ano = e.get("ano")
        if not _e_inteiro(ano) or not 1945 <= ano <= 2100:
            problemas.append(f"{re_}: 'ano' deveria ser inteiro entre 1945 e 2100")
        else:
            anos.append(ano)
        problemas += _memoria_textos(e, ("cargo", "partido", "resultado"), re_)
        if not isinstance(e.get("uf"), str) or not re.fullmatch(r"[A-Z]{2}", e["uf"]):
            problemas.append(f"{re_}: 'uf' deveria ter duas letras maiúsculas")
        votos = e.get("votos")
        if votos is not None and (not _e_inteiro(votos) or votos < 0):
            problemas.append(f"{re_}: 'votos' deveria ser inteiro ≥ 0 ou null")
        fonte = e.get("fonte")
        if not isinstance(fonte, dict):
            problemas.append(f"{re_}: 'fonte' deveria ser um objeto com título e URL HTTPS")
        else:
            problemas += _memoria_fontes([fonte], re_)
    if anos != sorted(anos, reverse=True):
        problemas.append(f"{r}: 'eleicoes' deveria estar da mais recente para a mais antiga")
    return problemas


def validar_perfis(caminho: Path | None = None, cfg: object = None) -> list[str]:
    """Confere config/perfis.json: nomes, legislaturas, partidos, votos, situação, fontes, links e formato, sem rede.

    Com cfg (config/vereadores.json), o partido de quem foi eleito na legislatura deve ser o mesmo do config,
    e a situação, eleito/eleita; quem não está entre os eleitos só pode ser suplente.
    """
    caminho = caminho or RAIZ / "config" / "perfis.json"
    arquivo = "config/perfis.json"
    try:
        bruto = caminho.read_bytes()
    except FileNotFoundError:
        aviso = f"{arquivo}: arquivo ausente; fichas sem perfil e suplentes sem partido"
        print(f"::warning::{_anotacao(aviso)}" if os.environ.get("GITHUB_ACTIONS") else f"aviso: {aviso}", file=sys.stderr)
        return []
    except OSError as e:
        return [f"{arquivo}: não foi possível ler o arquivo ({e})"]
    try:
        dados = json.loads(bruto.decode("utf-8"))
    except ValueError as e:  # inclui UnicodeDecodeError
        return [f"{arquivo}: não foi possível ler o JSON ({e})"]
    problemas = _validar_formato_config(dados, bruto, arquivo)
    if not isinstance(dados, dict):
        return problemas + [f"{arquivo}: o conteúdo deveria ser um objeto"]
    if dados.get("fonte_padrao") is not None:
        problemas += _memoria_fontes([dados["fonte_padrao"]], f"{arquivo}: fonte_padrao")
    vereadores = dados.get("vereadores")
    if not isinstance(vereadores, dict):
        return problemas + [f"{arquivo}: 'vereadores' deveria ser um objeto"]

    legs: dict[str, dict[str, str]] | None = None
    if isinstance(cfg, dict) and isinstance(cfg.get("legislaturas"), list):
        legs = {}
        for leg in cfg["legislaturas"]:
            if isinstance(leg, dict) and isinstance(leg.get("id"), str):
                legs[leg["id"]] = {str(e.get("siscam", "")).upper(): str(e.get("partido", ""))
                                   for e in leg.get("eleitos") or [] if isinstance(e, dict)}
    contatos_vistos: dict[tuple[str, str], str] = {}
    for nome, perfil in vereadores.items():
        r = f"{arquivo}: {nome}"
        if not nome or nome != nome.upper() or nome != " ".join(nome.split()):
            problemas.append(f"{r}: a chave deveria ser o nome exato do SISCAM, em maiúsculas e sem espaços extras")
        if not isinstance(perfil, dict):
            problemas.append(f"{r}: o perfil deveria ser um objeto")
            continue
        extras = set(perfil) - CAMPOS_PERFIL
        if extras:
            problemas.append(f"{r}: campos desconhecidos: {', '.join(sorted(extras))}")
        contatos = perfil.get("contatos", [])
        if not isinstance(contatos, list):
            problemas.append(f"{r}: 'contatos' deveria ser uma lista")
            contatos = []
        for i, contato in enumerate(contatos, 1):
            rc = f"{r}: contato {i}"
            if not isinstance(contato, dict):
                problemas.append(f"{rc} deveria ser um objeto")
                continue
            if (set(contato) - {"tipo", "valor", "fonte", "descricao"}
                    or not {"tipo", "valor", "fonte"} <= set(contato)):
                problemas.append(f"{rc}: campos esperados: tipo, valor, fonte e descricao opcional, sem extras")
            problemas += _memoria_textos(contato, ("valor",), rc)
            if "descricao" in contato:
                problemas += _memoria_textos(contato, ("descricao",), rc)
            tipo, valor = contato.get("tipo"), contato.get("valor")
            if tipo not in ("telefone", "email"):
                problemas.append(f"{rc}: 'tipo' deveria ser telefone ou email")
            elif isinstance(valor, str):
                padrao = r"[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+" if tipo == "email" else r"[0-9 ()+\-]+"
                if not re.fullmatch(padrao, valor) or (tipo == "telefone" and len(re.findall(r"[0-9]", valor)) < 8):
                    problemas.append(f"{rc}: 'valor' inválido para {tipo}")
                chave = (tipo, valor)
                if chave in contatos_vistos:
                    problemas.append(f"{rc}: contato (tipo, valor) repetido no perfil de {contatos_vistos[chave]}")
                else:
                    contatos_vistos[chave] = nome
            if not _https_backend(contato.get("fonte")):
                problemas.append(f"{rc}: 'fonte' deveria ser URL HTTPS com host")
        if "falecimento" in perfil:
            falecimento = perfil["falecimento"]
            rf = f"{r}: falecimento"
            if not isinstance(falecimento, dict):
                problemas.append(f"{rf} deveria ser um objeto com data e fonte")
            else:
                if set(falecimento) - {"data", "fonte"}:
                    problemas.append(f"{rf}: campos desconhecidos")
                data = falecimento.get("data")
                if data is None or not data_valida(data):
                    problemas.append(f"{rf}: 'data' deveria ser data ISO válida AAAA-MM-DD")
                elif date.fromisoformat(data) > date.today():
                    problemas.append(f"{rf}: 'data' não pode ser futura")
                problemas += _memoria_fontes([falecimento.get("fonte")], rf)
        mandatos = perfil.get("mandatos")
        if not isinstance(mandatos, dict):
            problemas.append(f"{r}: 'mandatos' deveria ser um objeto por legislatura")
            mandatos = {}
        for leg_id, m in mandatos.items():
            rm = f"{r}: mandato {leg_id}"
            if legs is not None and leg_id not in legs:
                problemas.append(f"{rm}: legislatura inexistente em config/vereadores.json")
            if not isinstance(m, dict):
                problemas.append(f"{rm} deveria ser um objeto")
                continue
            partido = m.get("partido")
            if not _memoria_texto(partido):
                problemas.append(f"{rm}: 'partido' deveria ser texto não vazio")
            if "votos" in m and (not _e_inteiro(m["votos"]) or m["votos"] <= 0):
                problemas.append(f"{rm}: 'votos' deveria ser inteiro positivo (ou ficar de fora)")
            situacao = m.get("situacao")
            if situacao not in SITUACOES_PERFIL:
                problemas.append(f"{rm}: 'situacao' deveria ser {', '.join(SITUACOES_PERFIL)}")
            problemas += _memoria_fontes(m.get("fontes"), rm)
            if legs is not None and leg_id in legs:
                eleito = legs[leg_id].get(nome.upper())
                if eleito is not None:
                    if partido != eleito:
                        problemas.append(f"{rm}: partido {partido!r} difere do partido da eleição em config/vereadores.json ({eleito!r})")
                    if situacao == "suplente":
                        problemas.append(f"{rm}: está entre os eleitos em config/vereadores.json; situação deveria ser eleito ou eleita")
                elif situacao in ("eleito", "eleita"):
                    problemas.append(f"{rm}: não está entre os eleitos em config/vereadores.json; situação deveria ser suplente")
        problemas += _perfil_eleicoes(perfil.get("eleicoes", []), r)
        for chave in ("camara", "site"):
            if perfil.get(chave) is not None and not _https(perfil[chave]):
                problemas.append(f"{r}: '{chave}' deveria ser URL HTTPS com host ou null")
        redes = perfil.get("redes", [])
        if not isinstance(redes, list):
            problemas.append(f"{r}: 'redes' deveria ser uma lista")
            redes = []
        for i, rede in enumerate(redes, 1):
            rr = f"{r}: rede {i}"
            if not isinstance(rede, dict):
                problemas.append(f"{rr} deveria ser um objeto")
                continue
            if rede.get("rede") not in REDES_PERFIL:
                problemas.append(f"{rr}: 'rede' deveria ser {', '.join(REDES_PERFIL)}")
            if not _https(rede.get("url")):
                problemas.append(f"{rr}: 'url' deveria ser HTTPS com host")
            if not _https(rede.get("fonte")):
                problemas.append(f"{rr}: 'fonte' (página oficial que declara a rede) deveria ser HTTPS com host")
    return problemas


# ---- backend e remoções
def _ler_config_opcional(raiz: Path, nome: str) -> tuple[object, list[str]]:
    arquivo = f"config/{nome}.json"
    try:
        bruto = (raiz / arquivo).read_bytes()
    except FileNotFoundError:
        aviso = f"{arquivo}: arquivo ausente; configuração de {nome} indisponível"
        print(f"::warning::{_anotacao(aviso)}" if os.environ.get("GITHUB_ACTIONS") else f"aviso: {aviso}", file=sys.stderr)
        return None, []
    except OSError as e:
        return None, [f"{arquivo}: não foi possível ler o arquivo ({e})"]
    try:
        dados = json.loads(bruto.decode("utf-8"))
    except ValueError as e:  # inclui UnicodeDecodeError
        return None, [f"{arquivo}: não foi possível ler o JSON ({e})"]
    problemas = _validar_formato_config(dados, bruto, arquivo)
    if not isinstance(dados, dict):
        return None, problemas + [f"{arquivo}: deveria conter um objeto"]
    return dados, problemas


def _https_backend(valor: object, origem: bool = False) -> bool:
    """URL HTTPS com host e porta válidos; origens não admitem caminho nem sufixos."""
    if not isinstance(valor, str) or re.search(r"[\s\x00-\x1f\x7f\\]", valor):
        return False
    try:
        url = urlsplit(valor)
        _ = url.port  # também rejeita portas inválidas ou fora do intervalo
    except ValueError:
        return False
    if url.scheme != "https" or not url.hostname or url.username is not None or url.password is not None:
        return False
    host = r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*\.?"
    if not re.fullmatch(rf"(?:{host}|\[[A-Fa-f0-9:]+\])(?::[0-9]+)?", url.netloc):
        return False
    return not origem or (valor == f"https://{url.netloc}" and valor == valor.lower()
                          and not url.hostname.endswith(".") and url.port != 443)


def validar_backend(raiz: Path | None = None) -> list[str]:
    """Confere endereço da API, origens CORS e contatos institucionais, sem rede."""
    arquivo = "config/backend.json"
    dados, problemas = _ler_config_opcional(raiz or RAIZ, "backend")
    if dados is None:
        return problemas
    if set(dados) != {"api_url", "origens_cors", "contatos_institucionais"}:
        problemas.append(f"{arquivo}: campos esperados: api_url, origens_cors, contatos_institucionais, sem extras")
    api = dados.get("api_url")
    if api is not None and (not _https_backend(api) or api.endswith("/") or "?" in api or "#" in api):
        problemas.append(f"{arquivo}: 'api_url' deveria ser URL HTTPS sem barra final, consulta nem fragmento ou null")
    origens = dados.get("origens_cors")
    if not isinstance(origens, list) or not origens:
        problemas.append(f"{arquivo}: 'origens_cors' deveria ser lista não vazia de origens HTTPS únicas")
    else:
        vistas: set[str] = set()
        for origem in origens:
            if not _https_backend(origem, origem=True):
                problemas.append(f"{arquivo}: origem {origem!r} deveria ser https://host[:porta] em minúsculas, "
                                 "sem ponto final no host, porta padrão, caminho, consulta nem fragmento")
            elif origem in vistas:
                problemas.append(f"{arquivo}: origem {origem!r} repetida")
            else:
                vistas.add(origem)
    contatos, erros = _lista(dados, "contatos_institucionais", arquivo)
    problemas += erros
    vistos: set[tuple[str, str]] = set()
    for i, contato in enumerate(contatos, 1):
        r = f"{arquivo}: contato {i}"
        if not isinstance(contato, dict):
            problemas.append(f"{r} deveria ser um objeto")
            continue
        if set(contato) != {"tipo", "valor", "descricao", "fonte"}:
            problemas.append(f"{r}: campos esperados: tipo, valor, descricao, fonte, sem extras")
        problemas += _memoria_textos(contato, ("valor", "descricao"), r)
        tipo, valor = contato.get("tipo"), contato.get("valor")
        if tipo not in ("telefone", "email"):
            problemas.append(f"{r}: 'tipo' deveria ser telefone ou email")
        elif isinstance(valor, str):
            padrao = r"[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+" if tipo == "email" else r"[0-9 ()+\-]+"
            if not re.fullmatch(padrao, valor) or (tipo == "telefone" and len(re.findall(r"[0-9]", valor)) < 8):
                problemas.append(f"{r}: 'valor' inválido para {tipo}")
            chave = (tipo, valor)
            if chave in vistos:
                problemas.append(f"{r}: contato (tipo, valor) repetido")
            vistos.add(chave)
        if not _https_backend(contato.get("fonte")):
            problemas.append(f"{r}: 'fonte' deveria ser URL HTTPS com host")
    return problemas


RE_CHAVE_ARQUIVO = re.compile(
    r"siscam:[1-9][0-9]*|sessao:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)


def validar_remocoes(raiz: Path | None = None) -> list[str]:
    """Confere chaves, hashes, justificativas e ordem das remoções, sem rede."""
    arquivo = "config/remocoes.json"
    dados, problemas = _ler_config_opcional(raiz or RAIZ, "remocoes")
    if dados is None:
        return problemas
    if set(dados) != {"remocoes"}:
        problemas.append(f"{arquivo}: esperado somente o campo 'remocoes'")
    itens, erros = _lista(dados, "remocoes", arquivo)
    problemas += erros
    vistos: set[tuple[str, str]] = set()
    anterior: tuple[str, str, str] | None = None
    for i, item in enumerate(itens, 1):
        r = f"{arquivo}: remoção {i}"
        if not isinstance(item, dict):
            problemas.append(f"{r} deveria ser um objeto")
            continue
        if set(item) != {"chave", "sha256", "motivo", "fonte", "data"}:
            problemas.append(f"{r}: campos esperados: chave, sha256, motivo, fonte, data, sem extras")
        problemas += _memoria_textos(item, ("motivo",), r)
        chave, sha256, data = item.get("chave"), item.get("sha256"), item.get("data")
        # docs/contratos/textos.md §2.1: siscam:<IdArquivo> ou sessao:<guid> em minúsculas
        chave_valida = isinstance(chave, str) and re.fullmatch(RE_CHAVE_ARQUIVO, chave)
        if not chave_valida:
            problemas.append(f"{r}: 'chave' deveria ser siscam:<IdArquivo> (inteiro positivo) ou "
                             "sessao:<guid> (GUID em minúsculas)")
        sha256_valido = isinstance(sha256, str) and re.fullmatch(r"[0-9a-f]{64}", sha256)
        if not sha256_valido:
            problemas.append(f"{r}: 'sha256' deveria ter 64 caracteres hexadecimais minúsculos")
        if chave_valida and sha256_valido:
            par = (chave, sha256)
            if par in vistos:
                problemas.append(f"{r}: combinação (chave, sha256) repetida: {par!r}")
            vistos.add(par)
        if not _https_backend(item.get("fonte")):
            problemas.append(f"{r}: 'fonte' deveria ser URL HTTPS com host")
        if not isinstance(data, str) or not RE_DATA.fullmatch(data) or not data_valida(data):
            problemas.append(f"{r}: 'data' deveria ser data ISO válida AAAA-MM-DD")
        else:
            if date.fromisoformat(data) > date.today():
                problemas.append(f"{r}: 'data' não pode ser futura")
            if chave_valida and sha256_valido:
                ordem = (data, chave, sha256)
                if anterior is not None and ordem < anterior:
                    problemas.append(f"{r}: remoções fora de ordem por data, chave e sha256")
                anterior = ordem
    return problemas


# ---------------------------------------------------------------------- inteiro teor
RE_DOCUMENTO_TEXTO = re.compile(r"(?:doc|sessao):[1-9][0-9]*")
STATUS_TEXTOS = (*textos.STATUS_COM_TEXTO, "vazio_legitimo", "escaneado_sem_ocr",
                 "pendente_ferramenta", "erro_formato", *textos.SEM_PROCESSAMENTO)
CAMPOS_ENTRADA_TEXTO = frozenset(textos.entrada_vazia([], "", "", "", "", ""))
CONTAGENS_TEXTO = ("paginas", "paginas_ocr", "cabecalhos_omitidos", "chars", "trechos", "trechos_vetorizaveis")
VERSOES_TEXTO = ("versao_extrator", "versao_extratores", "versao_limpeza", "versao_mascara", "versao_trechos")
CAMPOS_TRECHO = frozenset({"id", "documento", "arquivo", "posicao", "inicio", "fim",
                           "inicio_utf16", "fim_utf16", "sha256", "vetorizavel", "baixa_confianca"})


def _hash_texto(valor: object, tamanho: int = 64) -> bool:
    return isinstance(valor, str) and re.fullmatch(rf"[0-9a-f]{{{tamanho}}}", valor) is not None


def _documento_texto(valor: object) -> bool:
    return isinstance(valor, str) and RE_DOCUMENTO_TEXTO.fullmatch(valor) is not None


def validar_entrada_texto(entrada: object, chave: str, rotulo: str) -> list[str]:
    """Esquema e campos por situação, conforme §§4–5 do contrato congelado."""
    if not isinstance(entrada, dict):
        return [f"{rotulo}: entrada deveria ser um objeto"]
    e, problemas = entrada, []

    def erro(campo: str) -> None:
        problemas.append(f"{rotulo}: '{campo}' inválido para o contrato de textos")

    if set(e) != CAMPOS_ENTRADA_TEXTO:
        problemas.append(f"{rotulo}: campos do manifesto diferem do contrato (sem extras)")
    status = e.get("status")
    if status not in STATUS_TEXTOS:
        erro("status")
    if e.get("tipo") not in textos.TIPOS:
        erro("tipo")
    if not _documento_texto(e.get("documento")):
        erro("documento")
    elif e.get("tipo") in textos.TIPOS and e["documento"].startswith("sessao:") != (e["tipo"] == "ata"):
        erro("documento")
    docs = e.get("documentos")
    if (not isinstance(docs, list) or not docs or not all(_documento_texto(d) for d in docs)
            or docs != sorted(set(docs))):
        erro("documentos")
    if not _https_backend(e.get("url_origem")):
        erro("url_origem")
    elif chave.startswith("siscam:"):
        if e["url_origem"] != textos.URL_DOWNLOAD.format(id=chave.split(":", 1)[1]):
            erro("url_origem")
    elif (textos.chave_ata(e["url_origem"]) != chave or not re.fullmatch(
            r"https://consultaniteroi\.siscam\.com\.br/Arquivos/Sessoes/[0-9A-Fa-f-]+\.(?:doc|docx|pdf)",
            e["url_origem"])):
        erro("url_origem")
    for campo in ("sha256_original", "sha256_config", "sha256_bruto", "sha256_texto", "blob_texto"):
        if e.get(campo) is not None and not _hash_texto(e[campo], 40 if campo == "blob_texto" else 64):
            erro(campo)
    for campo in CONTAGENS_TEXTO:
        if not _e_inteiro(e.get(campo)) or e[campo] < 0:
            erro(campo)
    for campo, limite in (("paginas_ocr", "paginas"), ("trechos_vetorizaveis", "trechos")):
        if (_e_inteiro(e.get(campo)) and _e_inteiro(e.get(limite)) and e[campo] > e[limite]):
            erro(campo)
    original = e.get("sha256_original")
    tamanho = e.get("bytes")
    if ((original is None and tamanho is not None) or
            (original is not None and (not _e_inteiro(tamanho) or tamanho < 0))):
        erro("bytes")
    if original is None and status not in ("pendente_download", "removido"):
        erro("sha256_original")
    if status == "pendente_download" and original is not None:
        erro("sha256_original")
    for campo in ("formato", "extrator", *VERSOES_TEXTO):
        if e.get(campo) is not None and (not isinstance(e[campo], str) or not e[campo]):
            erro(campo)
    if e.get("formato") is not None and e["formato"] not in (
            "docx", "doc", "rtf", "html", "texto", "pdf", "jpeg", "png", "tiff", "zip", "vazio", "desconhecido"):
        erro("formato")
    confianca = e.get("confianca")
    if confianca is not None and (type(confianca) not in (float, int) or not 0 <= confianca <= 100
                                  or round(confianca, 1) != confianca):
        erro("confianca")
    if not isinstance(e.get("detalhe"), str) or len(e["detalhe"]) > 300:
        erro("detalhe")
    if not isinstance(e.get("processado_em"), str) or not data_valida(e["processado_em"]):
        erro("processado_em")
    com_texto = status in textos.STATUS_COM_TEXTO or (
        status == "vazio_legitimo" and e.get("detalhe") == textos.ESVAZIADO)
    for campo in ("limpeza", "mascarados", "sha256_bruto", "sha256_texto", "blob_texto"):
        if (e.get(campo) is not None) != com_texto:
            erro(campo)
    if (not com_texto or status == "vazio_legitimo") and any(
            e.get(c) != 0 for c in ("chars", "trechos", "trechos_vetorizaveis")):
        erro("contagens sem texto ou de vazio_legitimo")
    limpeza = e.get("limpeza")
    if limpeza is not None:
        regras = limpeza.get("por_regra") if isinstance(limpeza, dict) else None
        if (not isinstance(limpeza, dict) or set(limpeza) != {"linhas_removidas", "por_regra"}
                or not isinstance(regras, dict)
                or set(regras) != {"cabecalho_rodape", "numeracao", "ruido_ocr", "cliche"}
                or any(not _e_inteiro(v) or v < 0 for v in regras.values())
                or not _e_inteiro(limpeza.get("linhas_removidas"))
                or limpeza["linhas_removidas"] != sum(regras.values())):
            erro("limpeza")
    mascarados = e.get("mascarados")
    if mascarados is not None and (not isinstance(mascarados, dict) or set(mascarados) != set(mascara.TIPOS)
                                  or any(not _e_inteiro(v) or v < 0 for v in mascarados.values())):
        erro("mascarados")
    if status in textos.SEM_PROCESSAMENTO:
        for campo in ("formato", "extrator", *VERSOES_TEXTO, "sha256_config", "confianca", "r2_chave"):
            if e.get(campo) is not None:
                erro(campo)
        if any(e.get(c) != 0 for c in ("paginas", "paginas_ocr", "cabecalhos_omitidos")) or e.get("detalhe") != "":
            erro("extração sem processamento")
    else:
        for campo in ("formato", "versao_extratores", "versao_limpeza", "versao_mascara", "versao_trechos", "sha256_config"):
            if e.get(campo) is None:
                erro(campo)
        if _hash_texto(original) and e.get("r2_chave") != textos.r2_chave(original):
            erro("r2_chave")
    if status == "duplicata":
        if not isinstance(e.get("duplicata_de"), str) or not textos.RE_CHAVE.fullmatch(e["duplicata_de"]):
            erro("duplicata_de")
    elif e.get("duplicata_de") is not None:
        erro("duplicata_de")
    return problemas


def _principais_textos(raiz: Path) -> tuple[dict[str, tuple[str, str, int]], list[str]]:
    """Documento citante → principal, tipo e ano do registro (inclusive substitutivos)."""
    problemas, catalogo = [], {}
    try:
        pls, documentos, sessoes = textos.carregar_registros(raiz)
    except (OSError, ValueError) as erro:
        return {}, [f"data: não foi possível resolver documentos dos textos ({type(erro).__name__})"]
    grupos = [("pl", pls), *documentos.items(), ("ata", sessoes)]
    for tipo, registros in grupos:
        for registro in registros:
            if (not isinstance(registro, dict) or not _e_inteiro(registro.get("id"))
                    or not _e_inteiro(registro.get("ano"))):
                continue  # a validação de cada coletor informa o registro malformado
            doc = f"{'sessao' if tipo == 'ata' else 'doc'}:{registro['id']}"
            catalogo[doc] = (doc, tipo, registro["ano"])
            subs = registro.get("substitutivos")
            for sub in subs if isinstance(subs, list) else []:
                if isinstance(sub, dict) and _e_inteiro(sub.get("id")):
                    catalogo[f"doc:{sub['id']}"] = catalogo[doc]
    return catalogo, problemas


def validar_textos(raiz: Path | None = None, pasta_textos: Path | None = None) -> list[str]:
    """Confere manifestos sempre; com worktree, confere também bytes, trechos e PII, sem gravar."""
    raiz = Path(raiz or RAIZ)
    pasta = raiz / "data" / "textos"
    problemas, entradas = [], {}
    for caminho in sorted(pasta.glob("manifesto-*.json")):
        rotulo = f"data/textos/{caminho.name}"
        nome = textos.RE_MANIFESTO.fullmatch(caminho.name)
        if not nome:
            problemas.append(f"{rotulo}: nome deveria ser manifesto-<ano>.json")
            continue
        try:
            bruto = caminho.read_bytes()
            mapa = json.loads(bruto.decode("utf-8"))
        except (OSError, ValueError) as erro:
            problemas.append(f"{rotulo}: não foi possível ler o manifesto ({type(erro).__name__})")
            continue
        if not isinstance(mapa, dict):
            problemas.append(f"{rotulo}: manifesto deveria ser um objeto")
            continue
        # salvar_mapa ordena fisicamente por texto; ordem_chave rege o processamento
        # e a escolha da canônica, não a serialização (§§4 e 6.2 do contrato).
        if bruto != texto_mapa(mapa).encode("utf-8"):
            problemas.append(f"{rotulo}: formato de bytes difere de coletor.arquivos.salvar_mapa (ordem, UTF-8 e LF)")
        for chave, entrada in mapa.items():
            if not textos.RE_CHAVE.fullmatch(chave):
                problemas.append(f"{rotulo}: chave de arquivo fora do padrão do contrato")
                continue
            r = f"{rotulo}: {chave}"
            problemas += validar_entrada_texto(entrada, chave, r)
            if chave in entradas:
                problemas.append(f"{r}: chave repetida entre manifestos")
            elif isinstance(entrada, dict):
                entradas[chave] = (entrada, int(nome[1]))
    catalogo, erros = _principais_textos(raiz) if entradas else ({}, [])
    problemas += erros
    try:
        removidos = remocoes.indice(raiz)
    except (OSError, ValueError) as erro:
        problemas.append(f"config/remocoes.json: não foi possível conferir textos ({type(erro).__name__})")
        removidos = remocoes.indice([])
    grupos = {}
    for chave in sorted(entradas, key=textos.ordem_chave):
        e, ano = entradas[chave]
        r = f"data/textos/manifesto-{ano}.json: {chave}"
        sha = e.get("sha256_original")
        if remocoes.esta_removido(removidos, chave, sha if isinstance(sha, str) else None) and e.get("status") != "removido":
            problemas.append(f"{r}: arquivo removido por chave ou SHA-256 sem status removido")
        if _hash_texto(sha) and e.get("status") != "removido":
            grupos.setdefault(sha, []).append(chave)
        doc, tipo = e.get("documento"), e.get("tipo")
        if _documento_texto(doc) and tipo in textos.TIPOS:
            conhecido = catalogo.get(doc)
            familia = "sessoes" if tipo == "ata" else "proposicoes" if tipo == "pl" else f"documentos/{tipo}"
            if conhecido is None and (raiz / "data" / familia).is_dir():
                problemas.append(f"{r}: documento principal não existe em data/")
            elif conhecido is not None and conhecido != (doc, tipo, ano):
                problemas.append(f"{r}: documento principal, tipo ou ano diverge do registro em data/")
            docs = e.get("documentos")
            if isinstance(docs, list) and docs and all(_documento_texto(d) and d in catalogo for d in docs):
                principal = min((catalogo[d] for d in docs),
                                key=lambda p: (textos.PRIORIDADE_TIPO[p[1]], int(p[0].split(":")[1])))
                if principal != (doc, tipo, ano):
                    problemas.append(f"{r}: documento principal não segue a prioridade dos citantes ou o ano do registro")
        if e.get("status") == "duplicata":
            canonica = e.get("duplicata_de")
            alvo = entradas.get(canonica) if isinstance(canonica, str) else None
            if (alvo is None or alvo[0].get("status") in ("duplicata", "removido")
                    or alvo[0].get("sha256_original") != sha
                    or alvo[0].get("bytes") != e.get("bytes")
                    or textos.ordem_chave(canonica) >= textos.ordem_chave(chave)):
                problemas.append(f"{r}: duplicata_de não aponta para uma canônica existente com o mesmo original e menor chave")
            elif isinstance(e.get("documentos"), list) and isinstance(alvo[0].get("documentos"), list):
                if any(d not in alvo[0]["documentos"] for d in e["documentos"]):
                    problemas.append(f"{r}: documentos da duplicata ausentes na canônica")
    for chaves in grupos.values():
        for chave in chaves[1:]:
            e = entradas[chave][0]
            if e.get("status") != "duplicata" or e.get("duplicata_de") != chaves[0]:
                problemas.append(f"{chave}: mesmo original sem duplicata da menor chave canônica")
    if pasta_textos is not None:
        problemas += _validar_arquivos_textos(raiz, Path(pasta_textos), entradas)
    return problemas


def _validar_trecho_texto(t: object, texto: str, documento: str, chave: str, posicao: int) -> bool:
    """Offsets, hash, id e vetor: independe da versão do algoritmo de divisão."""
    if (not isinstance(t, dict) or set(t) not in (CAMPOS_TRECHO, CAMPOS_TRECHO - {"baixa_confianca"})
            or ("baixa_confianca" in t and type(t["baixa_confianca"]) is not bool)):
        return False
    for campo in ("posicao", "inicio", "fim", "inicio_utf16", "fim_utf16"):
        if not _e_inteiro(t[campo]) or t[campo] < 0:
            return False
    if (t["documento"] != documento or t["arquivo"] != chave or t["posicao"] != posicao
            or not 0 <= t["inicio"] < t["fim"] <= len(texto) or type(t["vetorizavel"]) is not bool):
        return False
    inicio, fim = t["inicio"], t["fim"]
    parte = texto[inicio:fim]
    sha = textos.sha256(parte.encode("utf-8"))
    ident = hashlib.sha1(f"{documento}|{chave}|{posicao}|{sha}".encode("utf-8")).hexdigest()[:16]
    return (t["sha256"] == sha and t["id"] == ident
            and t["inicio_utf16"] == len(texto[:inicio].encode("utf-16-le")) // 2
            and t["fim_utf16"] == len(texto[:fim].encode("utf-16-le")) // 2
            and t["vetorizavel"] == trechos.vetorizavel(parte))


def _validar_arquivos_textos(raiz: Path, pasta: Path, entradas: dict[str, tuple[dict, int]]) -> list[str]:
    """Lê somente o worktree indicado; não extrai, não usa cache e não acessa a rede."""
    if not pasta.is_dir():
        return ["dados-textos: diretório não encontrado"]
    problemas, esperados, grupos = [], set(), {}
    try:
        liberados = mascara.liberados(raiz)
    except (OSError, ValueError) as erro:
        problemas.append(f"dados-textos: falha ao ler contatos liberados ({type(erro).__name__})")
        liberados = frozenset()

    def ler_texto(caminho: Path, chave: str) -> tuple[bytes, str] | None:
        try:
            dados = caminho.read_bytes()
            conteudo = dados.decode("utf-8")
        except (OSError, ValueError) as erro:
            problemas.append(f"{chave}: texto ausente, ilegível ou fora de UTF-8 ({type(erro).__name__})")
            return None
        texto = conteudo[:-1] if conteudo.endswith("\n") else conteudo
        # O contrato não grava confianca_paginas/ocr_paginas nem liberados por entrada.
        # Sem os metadados do cache, aplica a mesma barreira normal de textos.barreira.
        fortes = sorted({o["tipo"] for o in mascara.varrer(texto, liberados) if o["forte"]}
                        | {o["tipo"] for o in mascara.varrer_estrito(texto, liberados)})
        if fortes:
            problemas.append(f"{chave}: ocorrência forte de mascara.varrer ({', '.join(fortes)})")
        if not conteudo.endswith("\n") or trechos.normalizar(texto) != texto:
            problemas.append(f"{chave}: formato do .txt inválido (UTF-8 sem BOM, NFC, LF e quebra final)")
        return dados, texto

    for chave in sorted(entradas, key=textos.ordem_chave):
        e, ano = entradas[chave]
        if not textos.tem_texto(e) or e.get("tipo") not in textos.TIPOS or not _documento_texto(e.get("documento")):
            continue
        rel = textos.caminho_texto(e["tipo"], ano, e["documento"], chave)
        esperados.add(rel)
        grupo = textos.caminho_trechos(e["tipo"], ano)
        # O esvaziado pela limpeza tem .txt mas zero trechos; o pipeline não cria
        # um .jsonl vazio só por ele (a fixture congelada também não tem esse arquivo).
        grupos.setdefault(grupo, {})[chave] = (e, None)
        lido = ler_texto(pasta / rel, chave)
        if lido is None:
            continue
        dados, texto = lido
        grupos[grupo][chave] = (e, texto)
        if textos.sha256(dados) != e.get("sha256_texto"):
            problemas.append(f"{chave}: sha256_texto não confere")
        if textos.blob_git(dados) != e.get("blob_texto"):
            problemas.append(f"{chave}: blob_texto não confere")
        if len(texto) != e.get("chars"):
            problemas.append(f"{chave}: chars não confere")
    for caminho in sorted((pasta / "textos").rglob("*.txt")):
        if caminho.relative_to(pasta).as_posix() not in esperados:
            chave = textos.chave_do_caminho(caminho.name)
            rotulo = chave if textos.RE_CHAVE.fullmatch(chave) else "dados-textos"
            problemas.append(f"{rotulo}: .txt órfão sem entrada com texto no manifesto")
            ler_texto(caminho, rotulo)
    presentes = {p.relative_to(pasta).as_posix(): p for p in (pasta / "trechos").rglob("*.jsonl")}
    for rel in sorted(set(grupos) | set(presentes)):
        grupo = grupos.get(rel, {})
        caminho = presentes.get(rel)
        if not grupo:
            problemas.append("dados-textos: .jsonl órfão sem entrada com texto no manifesto")
            continue
        if caminho is None:
            if any(e.get("trechos") != 0 for e, _ in grupo.values()):
                problemas.append(f"{rel}: arquivo de trechos ausente")
            continue
        try:
            bruto = caminho.read_bytes()
            linhas = bruto.decode("utf-8").split("\n")
            lista = [json.loads(linha) for linha in linhas if linha]
        except (OSError, ValueError) as erro:
            problemas.append(f"{rel}: trechos ilegíveis ({type(erro).__name__})")
            continue
        if any(not isinstance(t, dict) for t in lista):
            problemas.append(f"{rel}: trecho deveria ser objeto")
            continue
        campos_ordem_validos = all(isinstance(t.get("documento"), str) and isinstance(t.get("arquivo"), str)
                                   and _e_inteiro(t.get("posicao")) for t in lista)
        if not campos_ordem_validos:
            problemas.append(f"{rel}: campos de ordenação dos trechos inválidos")
            continue
        ordenados = sorted(lista, key=lambda t: (t["documento"], t["arquivo"], t["posicao"]))
        canonico = "".join(textos.linha_trecho(t) + "\n" for t in ordenados).encode("utf-8")
        if bruto != canonico:
            problemas.append(f"{rel}: formato de bytes ou ordem dos trechos inválido")
        por_chave = {}
        for t in lista:
            chave = t["arquivo"]
            if chave not in grupo:
                # Não reproduzir valores desconhecidos vindos do JSONL nas mensagens.
                problemas.append(f"{rel}: trecho órfão sem entrada correspondente no manifesto")
            else:
                por_chave.setdefault(chave, []).append(t)
        for chave, (e, texto) in grupo.items():
            itens = por_chave.get(chave, [])
            if (len(itens) != e.get("trechos")
                    or sum(t.get("vetorizavel") is True for t in itens) != e.get("trechos_vetorizaveis")):
                problemas.append(f"{chave}: contagem de trechos não confere")
            if texto is None:
                continue
            if any(not _validar_trecho_texto(t, texto, e["documento"], chave, i) for i, t in enumerate(itens)):
                problemas.append(f"{chave}: campos, offsets, id ou hash dos trechos não conferem com o texto")
            elif trechos.normalizar(texto) == texto and e.get("versao_trechos") == trechos.VERSAO_TRECHOS:
                # Confiança por página só existe no cache bruto, não no manifesto.
                if (any(type(t.get("baixa_confianca")) is not bool for t in itens)
                        or [dict(t, baixa_confianca=False) for t in itens] != trechos.dividir(texto, e["documento"], chave)):
                    problemas.append(f"{chave}: trechos não conferem com a divisão do texto")
    return problemas


def validar_cache_temas(raiz: Path | None = None) -> list[str]:
    """Cache opcional de temas: esquema fechado e bytes de salvar_mapa, sem rede."""
    from coletor.temas import validar_rotulos

    caminho = (raiz or RAIZ) / "data" / "temas_ia.json"
    arquivo = "data/temas_ia.json"
    if not caminho.exists():
        return []
    try:
        bruto = caminho.read_bytes()
        cache = json.loads(bruto.decode("utf-8"))
    except (OSError, ValueError):
        return [f"{arquivo}: JSON ou UTF-8 inválido"]
    if not isinstance(cache, dict):
        return [f"{arquivo}: deve ser um mapa"]
    problemas = []
    if bruto != texto_mapa(cache).encode("utf-8"):
        problemas.append(f"{arquivo}: formato de bytes difere de coletor.arquivos.salvar_mapa")

    def conjunto(registro, rotulo, pendente=False):
        if not isinstance(registro, dict):
            problemas.append(f"{rotulo}: registro deve ser um mapa")
            return
        obrigatorios = {"rotulos", "total_base", "versao", "modelo"}
        extras = {"documentos"} if pendente else {"documentos", "rotulos_pendentes", "falha_amostra", "motivos"}
        if set(registro) - obrigatorios - extras:
            problemas.append(f"{rotulo}: campos desconhecidos")
        if "rotulos" in registro or pendente:
            if not obrigatorios <= set(registro):
                problemas.append(f"{rotulo}: campos obrigatórios ausentes")
            try:
                if validar_rotulos(registro) != registro.get("rotulos"):
                    raise ValueError
            except ValueError:
                problemas.append(f"{rotulo}: rótulos inválidos ou não normalizados")
            if type(registro.get("total_base")) is not int or registro["total_base"] < 0:
                problemas.append(f"{rotulo}: total_base inválido")
            if any(not isinstance(registro.get(c), str) or not registro[c].strip()
                   for c in ("versao", "modelo")):
                problemas.append(f"{rotulo}: versão ou modelo inválido")
        elif not ({"falha_amostra", "rotulos_pendentes"} & set(registro)):
            problemas.append(f"{rotulo}: registro sem rótulos, pendência ou falha")
        if "documentos" in registro:
            refs = registro["documentos"]
            if (not isinstance(refs, list) or any(not isinstance(r, str) or
                    not re.fullmatch(r"doc:[0-9a-f]{16}", r) for r in refs)
                    or (isinstance(refs, list) and refs != sorted(set(refs)))):
                problemas.append(f"{rotulo}: referências de documentos inválidas")
        if "motivos" in registro:
            motivos = registro["motivos"]
            permitidos = {"resposta descartada: JSON, rótulo ou classificação inválida",
                          "tema descartado: menos de 2 documentos"}
            if not isinstance(motivos, list) or any(not isinstance(m, str) or m not in permitidos for m in motivos):
                problemas.append(f"{rotulo}: motivos inválidos")
        if "falha_amostra" in registro and (not isinstance(registro["falha_amostra"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", registro["falha_amostra"])):
            problemas.append(f"{rotulo}: hash de falha inválido")
        if "rotulos_pendentes" in registro:
            conjunto(registro["rotulos_pendentes"], rotulo + ": rotulos_pendentes", True)

    for chave, valor in cache.items():
        rotulo = f"{arquivo}: {chave}"
        if re.fullmatch(r"pessoa:[a-z0-9]+(?:-[a-z0-9]+)*:\d{4}-\d{4}", chave):
            conjunto(valor, rotulo)
        elif re.fullmatch(r"doc:[0-9a-f]{16}", chave):
            try:
                if valor != "outros" and validar_rotulos({"rotulos": [valor]}) != [valor]:
                    raise ValueError
            except ValueError:
                problemas.append(f"{rotulo}: classificação inválida")
        else:
            problemas.append(f"{rotulo}: chave inválida (pessoa: ou doc:)")
    return problemas


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


def validar_tudo(raiz: Path | None = None, pasta_textos: Path | None = None) -> list[str]:
    """Roda todas as verificações sobre os arquivos de `raiz` (padrão: o repositório)."""
    raiz = raiz or RAIZ
    arquivos, problemas = carregar_arquivos_anuais(raiz / "data" / "proposicoes")
    problemas += validar_proposicoes(arquivos)
    ids, numeros = indices(arquivos)
    problemas += validar_documentos(raiz, ids)
    problemas += validar_sessoes(raiz)
    problemas += validar_cache_temas(raiz)

    arq_geo = raiz / "data" / "geo" / "bairros.json"
    if arq_geo.exists():  # mapa opcional: sem geometria, permanecem gráficos e tabelas
        geo, erros = _ler_json(arq_geo, "data/geo/bairros.json")
        problemas += erros or validar_geo(geo)

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
    arq_perfis = raiz / "config" / "perfis.json"
    perfis = _ler_json(arq_perfis, "config/perfis.json")[0] if arq_perfis.exists() else None
    problemas += erros or validar_vereadores(cfg, perfis)
    problemas += validar_memoria(raiz / "config" / "memoria.json")
    problemas += validar_perfis(raiz / "config" / "perfis.json", cfg if not erros else None)
    problemas += validar_backend(raiz)
    problemas += validar_remocoes(raiz)
    problemas += validar_textos(raiz, pasta_textos)
    return problemas


def _anotacao(texto: str) -> str:
    """Escapa a mensagem para o formato de comandos do GitHub Actions."""
    return texto.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--textos", type=Path, metavar="DIR",
                        help="confere também os textos e trechos do worktree dados-textos")
    # A entrada do módulo passa sys.argv; chamadas programáticas legadas de main()
    # não devem interpretar argumentos do executor de testes.
    opcoes = parser.parse_args(argv if argv is not None else [])
    problemas = validar_tudo(pasta_textos=opcoes.textos)
    no_ci = bool(os.environ.get("GITHUB_ACTIONS"))
    for problema in problemas:
        print(f"::error::{_anotacao(problema)}" if no_ci else problema, file=sys.stderr)
    if problemas:
        print(f"validação: {len(problemas)} problema(s) encontrado(s)", file=sys.stderr)
        return 1
    print("validação: dados e configuração OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
