"""Coletor das sessões plenárias do SISCAM da Câmara Municipal de Niterói.

Lista as sessões de cada ano (ResultadoSessao.aspx?Ano=<ano>&pagina=<n>, 10 por página)
e baixa a página de detalhe de cada uma (DetalhesSessao.aspx?IdDocumento=<n>), com as
observações, os documentos da sessão (pauta, ordem do dia, expediente, ata), os itens
de pauta com prioridade e fase, a frequência dos vereadores e as votações nominais.
Grava um JSON por ano em data/sessoes/<ano>.json, com um registro por linha.

Os textos ficam como o SISCAM os exibe: a situação de frequência ("Consignado",
"Ausência Justificada"), o voto ("Favor", "Ausente", "Presidente") e o resultado
("Veto Mantido") não são interpretados aqui. Num veto, por exemplo, o sentido de
"Favor" ainda precisa ser definido com fonte pública antes de qualquer uso.

O IdDocumento dos itens de pauta e das votações é o mesmo id de data/proposicoes e de
data/documentos (DetalhesDocumentos.aspx); o IdDocumento da própria sessão é outra
numeração (DetalhesSessao.aspx), que não se compara com a dos documentos.

Pauta enxuta: cada item guarda só a referência (id_documento, fase, prioridade, secao e
secao_indice, a posição do documento da sessão de origem em documentos_sessao); tipo,
número, ano e ementa vêm de data/proposicoes e data/documentos pelo id.
O item cujo id não está nesses arquivos no momento da coleta, ou sem id (linha sem link
de documento), guarda também tipo_documento, numero, ano e ementa, para não perder
informação. Os ids conhecidos são lidos uma vez por execução (ids_conhecidos). As
votações, poucas, guardam sempre documento, tipo_documento, numero e ano (votação sem
link fica com id_documento null, como o item de pauta).

Listagem: a página não informa o total do ano. As páginas são pedidas em sequência até
uma página curta (menos de POR_PAGINA sessões), vazia ou fora do intervalo: o SISCAM
responde a uma página além da última com a página 1 de novo, o que se detecta pelo
número da página no paginador e pelos ids já vistos. PAGINAS_MAX é o limite de 50
páginas do SISCAM: a página 50 cheia deixa a listagem marcada como incompleta, com aviso.
Falha numa página, trava atingida ou listagem menor que a anterior mantêm os registros
anteriores do ano (mescla por id), com aviso; um ano sem nenhuma sessão listada não
substitui um arquivo existente.

Detalhe: baixado para sessões novas, sem detalhe, com detalhe pendente, com cabeçalho
alterado na listagem, realizadas nos últimos JANELA_RECENTE_DIAS dias (pauta, ata e
votações podem ser completadas depois) ou com --forcar; no máximo --max-detalhes
páginas por execução, as mais recentes primeiro. As que ficam para depois, ou cujo
download falha, mantêm o detalhe anterior (se houver) e recebem "detalhe_pendente": true.
A fila reúne os pendentes de todos os arquivos de data/sessoes. Seção presente na página
sem nenhum item reconhecido gera aviso (::warning::), e uma lista que tinha itens e veio
vazia num novo download mantém os itens anteriores. Rótulo de seção ("[ Votações ]") sem
a estrutura esperada é layout alterado: avisa e a sessão fica pendente, sem ser gravada
como detalhada. "detalhe_em" só muda quando o conteúdo do registro muda.

Dado bruto: um nome pode se repetir numa votação ou na frequência (o SISCAM listou o
presidente como "Ausente" e como "Presidente" na mesma votação); a linha é mantida e o
nome vai para "nomes_repetidos" da votação (ou "frequencia_nomes_repetidos" da sessão):
somas por vereador precisam deduplicar. O "ano" da sessão é o da listagem (o do
arquivo); título de outro ano só gera aviso. Sem tipo, a sessão fica "desconhecido".

Interrupção: --max-minutos é um prazo interno que encerra a execução de forma limpa (o
que falta fica pendente). Num SIGTERM ou Ctrl+C, os detalhes já aplicados são gravados e
a chave "sessoes" de data/meta.json é atualizada antes de sair.

Faz parte da coleta semanal (.github/workflows/coleta.yml), depois de coletor.documentos.

Uso: python -m coletor.sessoes [--anos 2025-2026] [--workers 4] [--forcar]
         [--max-detalhes 400] [--max-minutos 30]
Somente biblioteca padrão do Python.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import signal
import sys
import time
import unicodedata
from collections.abc import Callable, Collection, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urljoin

from coletor.arquivos import salvar_json, salvar_lista
from coletor.documentos import intervalo_anos
from coletor.siscam import BASE, baixar, data_iso

LISTAGEM = BASE + "/ResultadoSessao.aspx?Ano={ano}&pagina={pagina}"
DETALHE_SESSAO = BASE + "/DetalhesSessao.aspx?IdDocumento={id}"
POR_PAGINA = 10
PAGINAS_MAX = 50  # o SISCAM não pagina além da página 50; página 50 cheia = listagem possivelmente incompleta
JANELA_RECENTE_DIAS = 60  # sessões recentes têm o detalhe rebaixado: pauta, ata e votos chegam depois
MAX_DETALHES = 400  # páginas de detalhe por execução: a carga inicial se divide entre execuções
SALVAR_A_CADA = 50  # detalhes baixados entre gravações parciais
FALHAS_SEGUIDAS_MAX = 10  # interrompe os detalhes da execução depois de tantas falhas seguidas
LISTAGENS_SEM_RESPOSTA_MAX = 2  # anos seguidos sem resposta que encerram a execução
# tipos do filtro de sessões do SISCAM (ddlTipoSessao), normalizados; outro tipo gera aviso, mas é gravado
TIPOS_SESSAO = frozenset({"ordinaria", "extraordinaria", "solene", "especial", "instalacao", "audiencia_publica"})
TIPO_DESCONHECIDO = "desconhecido"  # sessão sem tipo na listagem nem no título
# tipos em que a falta de frequência é estranha (só aviso: a sessão pode ainda não ter ocorrido)
TIPOS_COM_FREQUENCIA = frozenset({"ordinaria", "extraordinaria"})
# campos vindos da listagem: se mudarem, o detalhe é baixado de novo
CAMPOS_LISTAGEM = ("titulo", "numero", "tipo", "tipo_texto", "ano", "data", "hora")
# campos vindos da página de detalhe, preservados quando a sessão é relistada
LISTAS_DETALHE = ("documentos_sessao", "pauta", "frequencia", "votacoes")
CAMPOS_DETALHE = ("observacoes", *LISTAS_DETALHE, "frequencia_nomes_repetidos", "detalhe_em")
CHAVES_TOTAIS = ("favor", "contra", "branco", "nulo", "abstencao", "ausentes")
# item de pauta: só a referência quando o id está em data/proposicoes ou data/documentos;
# senão (ou sem id), também os campos do documento. secao_indice é a posição do documento
# da sessão de origem em documentos_sessao (pode haver duas "Ordem do Dia")
CAMPOS_PAUTA = ("id_documento", "fase", "prioridade", "secao", "secao_indice")
CAMPOS_PAUTA_DOCUMENTO = ("tipo_documento", "numero", "ano", "ementa")
# seções do detalhe: rótulo exibido, id da linha (tr) e id da grade principal (None: não conferida)
SECOES_DETALHE = (
    ("Documentos da Sessão", "trDocumentosSessao", "gvDocumentoSessao"),
    ("Votações", "trVotacoes", "gvListagemVotacoes"),
    ("Frequência", "trFrequencia", None),
)
RAIZ = Path(__file__).resolve().parent.parent
DIR_SESSOES = RAIZ / "data" / "sessoes"
META = RAIZ / "data" / "meta.json"


# ---------------------------------------------------------------- árvore do HTML
# O detalhe aninha tabelas (grade de documentos > pauta; votações > votos): em vez de
# expressões regulares sobre a página toda, monta-se uma árvore com html.parser.
VAZIOS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
)


class No:
    """Elemento HTML: tag, atributos e filhos (elementos ou trechos de texto já sem entidades)."""

    __slots__ = ("tag", "attrs", "filhos")

    def __init__(self, tag: str, attrs: dict[str, str]) -> None:
        self.tag = tag
        self.attrs = attrs
        self.filhos: list[No | str] = []

    @property
    def id(self) -> str:
        return self.attrs.get("id", "")

    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def elementos(self) -> list[No]:
        return [f for f in self.filhos if isinstance(f, No)]

    def descendentes(self) -> Iterator[No]:
        """Elementos descendentes na ordem do documento."""
        pilha = list(reversed(self.elementos()))
        while pilha:
            no = pilha.pop()
            yield no
            pilha.extend(reversed(no.elementos()))

    def buscar(self, criterio: Callable[[No], bool]) -> No | None:
        return next((n for n in self.descendentes() if criterio(n)), None)

    def buscar_todos(self, criterio: Callable[[No], bool]) -> list[No]:
        return [n for n in self.descendentes() if criterio(n)]

    def texto(self, pular: No | None = None) -> str:
        """Texto do elemento com espaços normalizados; `pular` exclui uma subárvore."""
        partes: list[str] = []
        pilha: list[No | str] = [self]
        while pilha:
            atual = pilha.pop()
            if isinstance(atual, str):
                partes.append(atual)
            elif atual is not pular:
                if atual.tag == "br":
                    partes.append(" ")
                pilha.extend(reversed(atual.filhos))
        return re.sub(r"\s+", " ", "".join(partes)).strip()


class _Construtor(HTMLParser):
    """Monta a árvore de No; fechamento sem abertura correspondente é ignorado."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.raiz = No("#documento", {})
        self.pilha = [self.raiz]
        self.ids: dict[str, No] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        no = No(tag, {k: v or "" for k, v in attrs})
        self.pilha[-1].filhos.append(no)
        if no.id and no.id not in self.ids:
            self.ids[no.id] = no
        if tag not in VAZIOS:
            self.pilha.append(no)

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self.pilha) - 1, 0, -1):
            if self.pilha[i].tag == tag:
                del self.pilha[i:]
                return

    def handle_data(self, data: str) -> None:
        self.pilha[-1].filhos.append(data)


def arvore(pagina_html: str) -> tuple[No, dict[str, No]]:
    """Raiz da árvore da página e o mapa id → elemento (o primeiro de cada id)."""
    construtor = _Construtor()
    construtor.feed(pagina_html)
    construtor.close()
    return construtor.raiz, construtor.ids


def linhas(tabela: No) -> list[No]:
    """Linhas (tr) da própria tabela, sem as das tabelas aninhadas."""
    saida = []
    for filho in tabela.elementos():
        if filho.tag == "tr":
            saida.append(filho)
        elif filho.tag in ("thead", "tbody", "tfoot"):
            saida.extend(f for f in filho.elementos() if f.tag == "tr")
    return saida


def celulas(linha: No, tag: str = "td") -> list[No]:
    return [c for c in linha.elementos() if c.tag == tag]


def _id_termina(sufixo: str, tag: str = "table") -> Callable[[No], bool]:
    return lambda n: n.tag == tag and n.id.endswith(sufixo)


# --------------------------------------------------------------------- utilidades
def normalizar(texto: str) -> str:
    """Minúsculas sem acentos, com "_" no lugar de espaços e símbolos: "AUDIÊNCIA PÚBLICA" → "audiencia_publica"."""
    sem_acento = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", sem_acento.lower()).strip("_")


def _aviso(mensagem: str) -> None:
    print(f"::warning::{mensagem}", file=sys.stderr)


RE_HORA = re.compile(r"\b(\d{1,2}):(\d{2})\b")


def hora(texto: str) -> str | None:
    """Primeira hora "hh:mm" válida do texto, com dois dígitos na hora."""
    m = RE_HORA.search(texto or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def data_calendario(texto: str) -> str | None:
    """Data "dd/mm/aaaa" do texto em ISO, só se for uma data de calendário (como coletor.validar exige)."""
    iso = data_iso(texto)
    try:
        return dt.date.fromisoformat(iso).isoformat() if iso else None
    except ValueError:
        _aviso(f"data {texto!r} inválida; gravada como null")
        return None


def url_arquivo(href: str) -> str | None:
    """URL absoluta de um arquivo da sessão, com espaços escapados (o validador exige URL http(s) sem espaços).

    Link que não leva a uma URL http(s) (por exemplo, "javascript:") vira None, com aviso.
    """
    url = re.sub(r"\s", lambda m: quote(m.group(0)), urljoin(BASE + "/", href.strip()))
    if not re.match(r"https?://", url, re.I):
        _aviso(f"link de arquivo da sessão {href!r} não é uma URL http(s); gravado como null")
        return None
    return url


# "13ª Sessão Extraordinária de 2021", "1ª Sessão AUDIÊNCIA PÚBLICA de 2023"
RE_TITULO = re.compile(r"^(?P<numero>\d+)\s*(?:[ªºa°o]\.?)?\s*Sess[ãa]o\s+(?P<tipo>.+?)\s+de\s+(?P<ano>\d{4})$", re.I)
# cabeçalho do detalhe: "<título> - dd/mm/aaaa hh:mm"
RE_CABECALHO = re.compile(r"^(?P<titulo>.+?)\s+-\s+(?P<data>\d{2}/\d{2}/\d{4})(?:\s+(?P<hora>\d{1,2}:\d{2}))?\s*$")
RE_ID_SESSAO = re.compile(r"DetalhesSessao\.aspx\?IdDocumento=(\d+)", re.I)
RE_ID_DOCUMENTO = re.compile(r"DetalhesDocumentos\.aspx\?IdDocumento=(\d+)", re.I)
# "Projeto de Lei Nº 00268/2021" → tipo, número e ano
RE_DOCUMENTO = re.compile(r"^(?P<tipo>.+?)\s+N(?:[º°o.]|&#186;)*\s*(?P<numero>\d+)\s*/\s*(?P<ano>\d{4})$", re.I)
# qualquer "<rótulo>: <n>" da célula de totais; rótulo fora de CHAVES_TOTAIS gera aviso
RE_TOTAL = re.compile(r"([^\W\d_]\w*)\s*:\s*(\d+)")
# voto ou rótulo de total normalizado → chave de CHAVES_TOTAIS ("Presidente" e outros textos não contam)
CHAVE_DO_VOTO = {
    "favor": "favor", "contra": "contra", "branco": "branco", "nulo": "nulo",
    "abstencao": "abstencao", "ausente": "ausentes", "ausentes": "ausentes",
}


def titulo_sessao(titulo: str) -> dict:
    """Número, tipo e ano do título "<n>ª Sessão <Tipo> de <ano>"; campos ausentes (ou número 0) ficam None."""
    m = RE_TITULO.match(titulo or "")
    if not m:
        return {"numero": None, "tipo_texto": None, "ano": None}
    return {"numero": int(m.group("numero")) or None, "tipo_texto": m.group("tipo"), "ano": int(m.group("ano"))}


def nomes_repetidos(itens: list[dict], grupo: str | None = None) -> list[str]:
    """Nomes que aparecem mais de uma vez (no mesmo valor de `grupo`, se informado), na ordem da 1ª repetição.

    O SISCAM às vezes lista o mesmo vereador duas vezes numa votação (na 95ª Ordinária de
    2025, o presidente como "Ausente" e como "Presidente"): o dado bruto é mantido, e
    quem somar por vereador precisa deduplicar.
    """
    vistos: set[tuple] = set()
    repetidos: list[str] = []
    for item in itens:
        chave = (item.get(grupo) if grupo else None, item.get("nome"))
        if chave in vistos and item.get("nome") not in repetidos:
            repetidos.append(item["nome"])
        vistos.add(chave)
    return repetidos


def referencia_documento(link: No) -> dict:
    """Id, texto, tipo, número ("268/2021") e ano do documento de um link DetalhesDocumentos.aspx."""
    id_doc = int(RE_ID_DOCUMENTO.search(link.attrs.get("href", "")).group(1))
    texto = link.texto() or re.sub(r"\s+", " ", link.attrs.get("title", "")).strip()
    return referencia_texto(id_doc, texto)


def referencia_texto(id_doc: int | None, texto: str) -> dict:
    """Tipo, número e ano de um rótulo "<tipo> Nº <número>/<ano>"; fora do formato, o rótulo vira o tipo, com aviso."""
    m = RE_DOCUMENTO.match(texto)
    if not m:
        _aviso(f"documento {id_doc}: rótulo {texto!r} fora do formato '<tipo> Nº <número>/<ano>'")
        return {"id_documento": id_doc, "documento": texto, "tipo_documento": texto, "numero": None, "ano": None}
    numero = int(m.group("numero"))
    return {
        "id_documento": id_doc,
        "documento": texto,
        "tipo_documento": m.group("tipo"),
        "numero": f"{numero}/{m.group('ano')}" if numero else None,  # "Nº 0000/2024" não é número válido
        "ano": int(m.group("ano")),
    }


def _link_documento(no: No | None) -> No | None:
    if no is None:
        return None
    return no.buscar(lambda n: n.tag == "a" and bool(RE_ID_DOCUMENTO.search(n.attrs.get("href", ""))))


def _colunas(linha: No) -> dict[str, int]:
    """Posição de cada coluna pelo cabeçalho (th) normalizado: "Tipo Votação" → "tipo_votacao"."""
    return {normalizar(th.texto()): i for i, th in enumerate(celulas(linha, "th"))}


def _celula(tds: list[No], colunas: dict[str, int], nome: str) -> No | None:
    i = colunas.get(nome)
    return tds[i] if i is not None and i < len(tds) else None


def _texto(no: No | None) -> str:
    return no.texto() if no is not None else ""


# ----------------------------------------------------------------------- listagem
def url_listagem(ano: int, pagina: int) -> str:
    return LISTAGEM.format(ano=ano, pagina=pagina)


def pagina_exibida(raiz: No) -> int | None:
    """Número da página marcado no paginador (span.currentPage); None se não houver paginador."""
    atual = raiz.buscar(lambda n: n.tag == "span" and "currentPage" in n.classes())
    if atual is None:
        return None
    texto = atual.texto()
    return int(texto) if texto.isdigit() else None


def parse_listagem(pagina_html: str) -> tuple[list[dict], int | None]:
    """Sessões de uma página da listagem e o número da página exibido no paginador.

    Cada sessão é uma tabela "tabela-simples" com o link para o detalhe, a data e o
    tipo. Levanta ValueError se um bloco não tiver o link (mudança de layout).
    """
    raiz, _ = arvore(pagina_html)
    sessoes: list[dict] = []
    vistos: set[int] = set()
    for bloco in raiz.buscar_todos(lambda n: n.tag == "table" and "tabela-simples" in n.classes()):
        links = bloco.buscar_todos(lambda n: n.tag == "a" and bool(RE_ID_SESSAO.search(n.attrs.get("href", ""))))
        if not links:
            raise ValueError("bloco da listagem de sessões sem link para DetalhesSessao.aspx; o layout do SISCAM mudou?")
        id_sessao = int(RE_ID_SESSAO.search(links[0].attrs["href"]).group(1))
        if id_sessao in vistos:
            continue
        vistos.add(id_sessao)
        titulo = next((t for t in (a.texto() for a in links) if t), "")
        rotulos = {}
        for td in bloco.buscar_todos(lambda n: n.tag == "td"):
            m = re.match(r"(Data|Tipo)\s*:\s*(.*)$", td.texto())
            if m:
                rotulos[m.group(1)] = m.group(2).strip()
        pelo_titulo = titulo_sessao(titulo)
        tipo_texto = rotulos.get("Tipo") or pelo_titulo["tipo_texto"] or ""
        tipo = normalizar(tipo_texto) or TIPO_DESCONHECIDO
        if pelo_titulo["numero"] is None:
            _aviso(f"sessão {id_sessao}: título {titulo!r} fora do formato '<n>ª Sessão <Tipo> de <ano>'")
        if tipo == TIPO_DESCONHECIDO:
            _aviso(f"sessão {id_sessao}: sem tipo na listagem nem no título; gravada como {TIPO_DESCONHECIDO!r}")
        elif tipo not in TIPOS_SESSAO:
            _aviso(f"sessão {id_sessao}: tipo {tipo_texto!r} fora dos tipos conhecidos do filtro de sessões; gravado como está")
        sessoes.append(
            {
                "id": id_sessao,
                "titulo": titulo,
                "numero": pelo_titulo["numero"],
                "tipo": tipo,
                "tipo_texto": tipo_texto,
                "ano": pelo_titulo["ano"],  # listar_ano troca pelo ano da listagem
                "data": data_calendario(rotulos.get("Data", "")),
                "hora": hora(rotulos.get("Data", "")),
                "url": DETALHE_SESSAO.format(id=id_sessao),
            }
        )
    return sessoes, pagina_exibida(raiz)


def listar_ano(ano: int) -> dict:
    """Pede as páginas da listagem do ano em sequência até o fim.

    Para numa página vazia ou curta (menos de POR_PAGINA sessões), numa página fora do
    intervalo (o paginador marca outra página: o SISCAM devolve a página 1) ou numa
    página sem nenhuma sessão nova. Devolve {"itens": {id: sessão}, "completa": bool,
    "paginas": páginas pedidas, "falhas": [...]}; "completa" é False se uma página falhou
    ou se a página PAGINAS_MAX (a 50, limite do SISCAM) veio cheia. Falha na página 1
    sobe como exceção.

    O "ano" de cada sessão é o da listagem (o do arquivo em que ela é gravada), não o
    do título: título de outro ano só gera aviso, e o título fica como está em "titulo".
    """
    itens: dict[int, dict] = {}
    falhas: list[str] = []
    completa = False
    pagina = 0
    for pagina in range(1, PAGINAS_MAX + 1):
        try:
            sessoes, exibida = parse_listagem(baixar(url_listagem(ano, pagina)))
        except Exception as e:
            if pagina == 1:
                raise
            falhas.append(f"página {pagina}: {e}")
            _aviso(f"sessões {ano}, página {pagina}: falha na listagem ({e}); a listagem do ano fica incompleta")
            break
        if exibida is not None and exibida != pagina:
            if pagina == 1:
                raise ValueError(f"a página 1 da listagem de {ano} veio marcada como página {exibida}")
            completa = True  # fora do intervalo: o SISCAM devolveu outra página (a primeira)
            break
        novas = [s for s in sessoes if s["id"] not in itens]
        if not novas:
            completa = True  # vazia, ou só com sessões já vistas
            break
        if len(novas) < len(sessoes):
            _aviso(
                f"sessões {ano}, página {pagina}: {len(sessoes) - len(novas)} sessão(ões) repetida(s) de páginas "
                "anteriores; a listagem pode ter mudado durante a coleta"
            )
        for s in novas:
            if s["ano"] is not None and s["ano"] != ano:
                _aviso(
                    f"sessão {s['id']} ({s['titulo']!r}) listada em {ano}, mas o título é de {s['ano']}; "
                    f"gravada em {ano}, com o título como está"
                )
            itens[s["id"]] = {**s, "ano": ano}
        if len(sessoes) < POR_PAGINA:
            completa = True
            break
    else:  # a última página possível veio cheia: pode haver sessões além do limite do SISCAM
        falhas.append(f"página {PAGINAS_MAX} cheia")
        _aviso(
            f"sessões {ano}: listagem interrompida após {PAGINAS_MAX} páginas, a última cheia (o SISCAM não pagina "
            "além da 50); o total parece incompleto"
        )
    return {"itens": itens, "completa": completa and not falhas, "paginas": pagina, "falhas": falhas}


# ------------------------------------------------------------------------ detalhe
def _observacoes(raiz: No) -> str:
    celula = raiz.buscar(
        lambda n: n.tag == "td" and any(f.tag == "strong" and f.texto().startswith("Observa") for f in n.elementos())
    )
    if celula is None:
        return ""
    return re.sub(r"^Observa\w*\s*:\s*", "", celula.texto())


def _referencia_celula(celula: No | None) -> tuple[dict | None, bool]:
    """Referência do documento de uma célula e se ela tinha link DetalhesDocumentos.aspx.

    Sem link, mas com o rótulo do documento, a referência vem do rótulo, com id_documento
    None; sem nenhum rótulo, a referência é None.
    """
    link = _link_documento(celula)
    if link is not None:
        return referencia_documento(link), True
    rotulo = _texto(celula)
    return (referencia_texto(None, rotulo) if rotulo else None), False


def _itens_pauta(tabela: No, secao: str, indice: int, avisos: list[str]) -> list[dict]:
    """Itens completos de uma tabela de pauta (Prioridade | Fase | Documento | Arquivo | Ementa).

    `secao` e `indice` são o rótulo e a posição, em documentos_sessao, do documento da
    sessão em que a tabela está. Linha sem link de documento, mas com o rótulo do
    documento, entra com id_documento None (e aviso); linha sem nenhum rótulo é
    descartada, também com aviso. A pauta é enxugada só ao gravar (veja enxugar_pauta).
    """
    colunas = {"prioridade": 0, "fase": 1, "documento": 2, "arquivo": 3, "ementa": 4}
    itens, dados, sem_link = [], 0, 0
    for linha in linhas(tabela):
        if "grid-empty-data" in linha.classes():
            continue
        if celulas(linha, "th"):
            colunas = _colunas(linha)
            continue
        tds = celulas(linha)
        dados += 1
        ref, com_link = _referencia_celula(_celula(tds, colunas, "documento"))
        sem_link += not com_link
        if ref is None:
            continue
        itens.append(
            {
                "secao": secao,
                "secao_indice": indice,
                "prioridade": _texto(_celula(tds, colunas, "prioridade")),
                "fase": _texto(_celula(tds, colunas, "fase")),
                "id_documento": ref["id_documento"],
                "tipo_documento": ref["tipo_documento"],
                "numero": ref["numero"],
                "ano": ref["ano"],
                "ementa": _texto(_celula(tds, colunas, "ementa")),
            }
        )
    if sem_link:
        avisos.append(
            f"pauta '{secao}': {sem_link} de {dados} linha(s) sem link de documento reconhecido "
            f"({dados - len(itens)} sem rótulo, descartada(s); as demais gravadas sem id)"
        )
    return itens


def ids_conhecidos(dados: Path | None = None) -> frozenset[int]:
    """Ids dos registros de data/proposicoes/*.json e data/documentos/*/*.json.

    São os documentos cujo tipo, número, ano e ementa já estão nos dados (só o id de
    cada registro, não os de autores ou substitutivos). Lido uma vez por execução,
    antes dos detalhes; arquivo ilegível é ignorado com aviso, e os itens de pauta dos
    documentos dele ficam completos, sem perder informação.
    """
    base = Path(dados or DIR_SESSOES.parent)
    ids: set[int] = set()
    for arq in sorted([*base.glob("proposicoes/*.json"), *base.glob("documentos/*/*.json")]):
        try:
            registros = json.loads(arq.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            _aviso(f"{arq}: não foi possível ler ({e}); itens de pauta desses documentos ficam completos")
            continue
        if isinstance(registros, list):
            ids.update(
                r["id"] for r in registros
                if isinstance(r, dict) and isinstance(r.get("id"), int) and not isinstance(r["id"], bool)
            )
    return frozenset(ids)


def enxugar_pauta(pauta: list[dict], conhecidos: Collection[int]) -> list[dict]:
    """Pauta como é gravada: referência (CAMPOS_PAUTA) e, se o id não é conhecido ou falta, os campos do documento."""
    return [
        {
            chave: item.get(chave)
            for chave in (
                CAMPOS_PAUTA if item.get("id_documento") is not None and item["id_documento"] in conhecidos
                else (*CAMPOS_PAUTA, *CAMPOS_PAUTA_DOCUMENTO)
            )
        }
        for item in pauta
    ]


def _secoes_alteradas(raiz: No, ids: dict[str, No]) -> list[str]:
    """Seções do detalhe cujo layout mudou: o rótulo ("[ Votações ]") está na página sem a
    linha esperada (trVotacoes), ou a linha está sem a grade principal (gvListagemVotacoes)
    e sem "Nenhum Registro". Uma sessão sem a seção (sem o rótulo nem a linha) não entra.
    """
    texto = raiz.texto()
    alteradas = []
    for rotulo, id_linha, id_grade in SECOES_DETALHE:
        linha = ids.get(id_linha)
        if linha is None:
            if re.search(r"\[\s*" + re.escape(rotulo) + r"\s*\]", texto, re.I):
                alteradas.append(f"seção [ {rotulo} ] na página sem a linha {id_linha}")
        elif id_grade and ids.get(id_grade) is None and "Nenhum Registro" not in linha.texto():
            alteradas.append(f"seção [ {rotulo} ] sem a grade {id_grade}")
    return alteradas


def _documentos_e_pauta(ids: dict[str, No], avisos: list[str]) -> tuple[list[dict], list[dict]]:
    """Documentos da sessão (rótulo e arquivo) e os itens de pauta aninhados em cada um.

    Sem a linha ou sem a grade, devolve listas vazias: o layout é conferido à parte (_secoes_alteradas).
    """
    grade = ids.get("gvDocumentoSessao") if "trDocumentosSessao" in ids else None
    if grade is None:
        return [], []
    documentos, pauta, dados = [], [], 0
    for linha in linhas(grade):
        if "grid-empty-data" in linha.classes() or celulas(linha, "th"):
            continue
        dados += 1
        titulo = linha.buscar(lambda n: n.tag == "h4")
        rotulo = _texto(titulo)
        if not rotulo:
            avisos.append("documento da sessão sem rótulo (h4)")
        celula_arquivo = linha.buscar(_id_termina("_tdArquivo", "td"))
        link = celula_arquivo.buscar(lambda n: n.tag == "a" and bool(n.attrs.get("href"))) if celula_arquivo else None
        documentos.append({"rotulo": rotulo, "url": url_arquivo(link.attrs["href"]) if link else None})
        tabela = linha.buscar(_id_termina("_gvDocumentos"))
        if tabela is not None:
            pauta += _itens_pauta(tabela, rotulo, len(documentos) - 1, avisos)
    if dados and not documentos:
        avisos.append("seção [ Documentos da Sessão ] sem nenhum documento reconhecido")
    return documentos, pauta


def _frequencia(ids: dict[str, No], avisos: list[str]) -> list[dict]:
    """Frequência por momento da sessão ("Abertura - 14:10"): nome e situação como exibidos.

    O nome é gravado como vem (nenhuma página real traz cargo junto do nome); um nome
    pode se repetir no mesmo momento (veja nomes_repetidos).
    """
    secao = ids.get("trFrequencia")
    if secao is None:
        return []
    itens, momento = [], ""
    for no in secao.descendentes():
        if no.tag == "h4":
            momento = no.texto()
        elif no.tag == "table" and no.id.endswith("_grdMembros"):
            colunas = {"vereador": 0, "frequencia": 1}
            for linha in linhas(no):
                if "grid-empty-data" in linha.classes():
                    continue
                if celulas(linha, "th"):
                    colunas = _colunas(linha)
                    continue
                tds = celulas(linha)
                nome = _texto(_celula(tds, colunas, "vereador"))
                if not nome:
                    continue
                itens.append({"momento": momento, "nome": nome, "situacao": _texto(_celula(tds, colunas, "frequencia"))})
    if not itens:
        avisos.append("seção [ Frequência ] sem nenhum vereador reconhecido")
    return itens


def _totais(texto: str) -> tuple[dict | None, list[str]]:
    """Contagens "Favor: 11 , Contra: 2 , ..." como estão na página e os rótulos desconhecidos.

    Os totais ficam None se nenhum rótulo conhecido aparecer; cada chave ausente fica None.
    """
    totais: dict[str, int | None] = dict.fromkeys(CHAVES_TOTAIS)
    desconhecidos: list[str] = []
    achou = False
    for rotulo, valor in RE_TOTAL.findall(texto):
        chave = CHAVE_DO_VOTO.get(normalizar(rotulo))
        if chave is None:
            desconhecidos.append(rotulo)
            continue
        totais[chave] = int(valor)
        achou = True
    return (totais if achou else None), desconhecidos


def contagem_dos_votos(votos: list[dict]) -> dict[str, int]:
    """Votos por chave de CHAVES_TOTAIS ("Ausente" → ausentes); "Presidente" e outros textos não contam."""
    contagem = dict.fromkeys(CHAVES_TOTAIS, 0)
    for voto in votos:
        chave = CHAVE_DO_VOTO.get(normalizar(voto.get("voto") or ""))
        if chave:
            contagem[chave] += 1
    return contagem


def _votos(tabela: No) -> list[dict]:
    """Votos nominais (Vereador | Voto), com o nome como vem; um nome pode se repetir."""
    colunas = {"vereador": 0, "voto": 1}
    votos = []
    for linha in linhas(tabela):
        if "grid-empty-data" in linha.classes():
            continue
        if celulas(linha, "th"):
            colunas = _colunas(linha)
            continue
        tds = celulas(linha)
        nome = _texto(_celula(tds, colunas, "vereador"))
        if not nome:
            continue
        votos.append({"nome": nome, "voto": _texto(_celula(tds, colunas, "voto"))})
    return votos


def _votacoes(ids: dict[str, No], avisos: list[str]) -> list[dict]:
    """Votações (Documento | Resultado | Tipo Votação | Votação) com totais e votos nominais.

    Votação sem link de documento, mas com o rótulo, fica com id_documento None (e aviso),
    como o item de pauta; sem nenhum rótulo, é descartada com aviso. Totais que não
    batem com a contagem dos votos, ou com rótulo desconhecido, só geram aviso: os dois
    ficam como estão na página. Nome repetido nos votos vai para "nomes_repetidos".
    Sem a linha ou sem a grade, devolve [] (o layout é conferido em _secoes_alteradas).
    """
    grade = ids.get("gvListagemVotacoes") if "trVotacoes" in ids else None
    if grade is None:
        return []
    colunas = {"documento": 0, "resultado": 1, "tipo_votacao": 2, "votacao": 3}
    votacoes, dados = [], 0
    for linha in linhas(grade):
        if "grid-empty-data" in linha.classes():
            continue
        if celulas(linha, "th"):
            colunas = _colunas(linha)
            continue
        tds = celulas(linha)
        dados += 1
        ref, com_link = _referencia_celula(_celula(tds, colunas, "documento"))
        if not com_link:
            avisos.append(
                f"votação {dados} sem link de documento reconhecido"
                + (" (gravada sem id, com o rótulo)" if ref else " nem rótulo (descartada)")
            )
        if ref is None:
            continue
        celula_votacao = _celula(tds, colunas, "votacao")
        tabela_votos = celula_votacao.buscar(_id_termina("_grdVotos")) if celula_votacao else None
        votos = _votos(tabela_votos) if tabela_votos is not None else []
        totais, desconhecidos = _totais(celula_votacao.texto(pular=tabela_votos)) if celula_votacao else (None, [])
        tipo_votacao = _texto(_celula(tds, colunas, "tipo_votacao"))
        if normalizar(tipo_votacao) == "nominal" and (totais is None or not votos):
            avisos.append(f"votação nominal de {ref['documento']!r} sem totais ou sem votos reconhecidos")
        if desconhecidos:
            _aviso(f"votação de {ref['documento']!r}: rótulo(s) de total desconhecido(s): {', '.join(desconhecidos)}")
        if totais is not None and votos:
            contagem = contagem_dos_votos(votos)
            divergentes = [f"{k} {totais[k]} ≠ {contagem[k]}" for k in CHAVES_TOTAIS if totais[k] not in (None, contagem[k])]
            if divergentes:
                _aviso(
                    f"votação de {ref['documento']!r}: totais da página diferem da contagem dos votos "
                    f"({'; '.join(divergentes)}); os dois ficam como estão"
                )
        votacao = {
            **ref,
            "resultado": _texto(_celula(tds, colunas, "resultado")),
            "tipo_votacao": tipo_votacao,
            "totais": totais,
            "votos": votos,
        }
        repetidos = nomes_repetidos(votos)
        if repetidos:
            votacao["nomes_repetidos"] = repetidos
        votacoes.append(votacao)
    if not votacoes:
        avisos.append("seção [ Votações ] sem nenhuma votação reconhecida")
    return votacoes


def parse_detalhe(pagina_html: str) -> dict:
    """Lê a página DetalhesSessao.aspx: cabeçalho, observações, documentos, pauta, frequência e votações.

    "id" é o IdDocumento da ação do formulário (None se ausente) e "titulo" fica vazio se
    a página não tiver o cabeçalho da sessão. Cada seção presente sem nenhum item
    reconhecido gera um aviso em "avisos" (e em stderr), em vez de virar lista vazia em
    silêncio. "layout_alterado" lista as seções cujo rótulo aparece sem a estrutura
    esperada (veja _secoes_alteradas): ler_detalhe recusa a página, e a sessão fica pendente.
    Nomes repetidos nos votos ou na frequência são mantidos e avisados em stderr, sem
    ::warning:: (é dado do SISCAM, não mudança de layout).
    """
    raiz, ids = arvore(pagina_html)
    avisos: list[str] = []
    formulario = raiz.buscar(lambda n: n.tag == "form")
    acao = RE_ID_SESSAO.search(formulario.attrs.get("action", "")) if formulario else None
    cabecalho = _texto(raiz.buscar(lambda n: n.tag == "td" and "form-task" in n.classes()))
    m = RE_CABECALHO.match(cabecalho)
    titulo = m.group("titulo") if m else cabecalho
    pelo_titulo = titulo_sessao(titulo)
    alterado = _secoes_alteradas(raiz, ids)
    avisos += alterado
    documentos, pauta = _documentos_e_pauta(ids, avisos)
    frequencia = _frequencia(ids, avisos) if "trFrequencia" in ids else []
    detalhe = {
        "id": int(acao.group(1)) if acao else None,
        "titulo": titulo,
        "numero": pelo_titulo["numero"],
        "tipo": normalizar(pelo_titulo["tipo_texto"] or "") or TIPO_DESCONHECIDO,
        "tipo_texto": pelo_titulo["tipo_texto"],
        "ano": pelo_titulo["ano"],
        "data": data_calendario(m.group("data")) if m else None,
        "hora": hora(m.group("hora") or "") if m else None,
        "observacoes": _observacoes(raiz),
        "documentos_sessao": documentos,
        "pauta": pauta,
        "frequencia": frequencia,
        "votacoes": _votacoes(ids, avisos),
        "avisos": avisos,
        "layout_alterado": alterado,
    }
    for aviso in avisos:
        _aviso(f"sessão {detalhe['id']} ({titulo!r}): {aviso}; o layout do SISCAM mudou?")
    repetidos = [
        (f"votação de {v['documento']!r}", v["nomes_repetidos"]) for v in detalhe["votacoes"] if v.get("nomes_repetidos")
    ]
    if nomes_repetidos(frequencia, "momento"):
        repetidos.append(("frequência", nomes_repetidos(frequencia, "momento")))
    for onde, nomes in repetidos:
        print(
            f"aviso: sessão {detalhe['id']} ({titulo!r}), {onde}: nome(s) repetido(s) {', '.join(nomes)}; "
            "dado mantido como no SISCAM",
            file=sys.stderr,
        )
    return detalhe


def ler_detalhe(pagina_html: str, registro: dict) -> dict:
    """Lê o detalhe e confere que é a página da sessão pedida.

    Levanta ValueError se a página não tiver o cabeçalho da sessão (página de erro ou
    layout novo), se o formulário for de outra sessão ou se o layout de uma seção mudou
    (detalhe["layout_alterado"]): nesses casos a sessão não é gravada como detalhada e
    fica pendente. Cabeçalho que difere da listagem (número, tipo, data ou hora) só gera
    aviso: valem os dados da listagem. Sessão ordinária ou extraordinária sem frequência
    também só gera aviso (pode ainda não ter ocorrido).
    """
    detalhe = parse_detalhe(pagina_html)
    if not detalhe["titulo"] or detalhe["data"] is None:
        raise ValueError(f"página de detalhe sem o cabeçalho '<título> - dd/mm/aaaa' (encontrado: {detalhe['titulo']!r})")
    if detalhe["id"] is not None and detalhe["id"] != registro["id"]:
        raise ValueError(f"página de detalhe da sessão {detalhe['id']}, não da {registro['id']}")
    if detalhe["layout_alterado"]:
        raise ValueError(f"layout do SISCAM alterado ({'; '.join(detalhe['layout_alterado'])}); sessão mantida pendente")
    diferencas = [
        f"{chave} {detalhe[chave]!r} ≠ {registro.get(chave)!r}"
        for chave in ("numero", "tipo", "data", "hora")
        if registro.get(chave) is not None and detalhe[chave] != registro.get(chave)
    ]
    if diferencas:
        _aviso(f"sessão {registro['id']}: cabeçalho do detalhe difere da listagem ({'; '.join(diferencas)})")
    if registro.get("tipo") in TIPOS_COM_FREQUENCIA and not detalhe["frequencia"]:
        _aviso(
            f"sessão {registro['id']} ({registro.get('titulo')!r}): sessão {registro.get('tipo')} sem frequência; "
            "confira se já ocorreu"
        )
    return detalhe


def aplicar_detalhe(registro: dict, detalhe: dict, em: str, conhecidos: Collection[int] = frozenset()) -> dict:
    """Devolve um registro novo com as observações e as listas do detalhe, sem alterar `registro`.

    A pauta é gravada enxuta (enxugar_pauta): só a referência para os ids em
    `conhecidos` (veja ids_conhecidos); sem `conhecidos`, todos os itens ficam completos.
    Uma lista que tinha itens e veio vazia mantém os itens anteriores, com aviso: o
    SISCAM às vezes devolve a página sem uma seção, e o dado não se perde em silêncio.
    "frequencia_nomes_repetidos" (omitida se vazia) lista os nomes repetidos num mesmo
    momento da frequência gravada. "detalhe_em" só muda quando o conteúdo do registro
    muda: rebaixar uma sessão recente sem novidade não gera diff. O chamador troca o
    registro antigo pelo novo de uma vez (sem estado intermediário numa interrupção).
    """
    fixos = ("detalhe_pendente", "detalhe_em", "frequencia_nomes_repetidos")
    novo = {k: v for k, v in registro.items() if k not in fixos}
    novo["observacoes"] = detalhe["observacoes"]
    for chave in LISTAS_DETALHE:
        anterior = registro.get(chave) or []
        if anterior and not detalhe[chave]:
            _aviso(f"sessão {registro['id']}: '{chave}' veio vazia no detalhe; {len(anterior)} item(ns) anterior(es) mantido(s)")
            novo[chave] = anterior
        elif chave == "pauta":
            novo[chave] = enxugar_pauta(detalhe[chave], conhecidos)
        else:
            novo[chave] = detalhe[chave]
    repetidos = nomes_repetidos(novo["frequencia"], "momento")
    if repetidos:
        novo["frequencia_nomes_repetidos"] = repetidos
    antes = {k: v for k, v in registro.items() if k not in ("detalhe_pendente", "detalhe_em")}
    novo["detalhe_em"] = registro["detalhe_em"] if registro.get("detalhe_em") and antes == novo else em
    return novo


# ---------------------------------------------------------------- incremental
def recente(registro: dict, hoje: str) -> bool:
    """Se a sessão é de até JANELA_RECENTE_DIAS dias atrás (ou futura)."""
    try:
        dias = (dt.date.fromisoformat(hoje) - dt.date.fromisoformat(registro.get("data") or "")).days
    except ValueError:
        return False
    return dias <= JANELA_RECENTE_DIAS


def precisa_detalhe(registro: dict, anterior: dict | None, hoje: str, forcar: bool = False) -> bool:
    """Se o detalhe da sessão relistada deve ser baixado.

    Sim com forcar, para sessão nova, sem detalhe ou com detalhe pendente, quando um
    campo da listagem mudou e quando a sessão é recente (veja recente) e o detalhe não
    foi baixado hoje depois do dia da sessão.
    """
    if forcar or anterior is None or not anterior.get("detalhe_em") or anterior.get("detalhe_pendente"):
        return True
    if any(anterior.get(chave) != registro.get(chave) for chave in CAMPOS_LISTAGEM):
        return True
    if recente(registro, hoje):
        em = anterior["detalhe_em"]
        return not (em == hoje and em > (registro.get("data") or ""))
    return False


def mesclar(sessao: dict, anterior: dict | None, hoje: str, forcar: bool = False) -> dict:
    """Registro relistado: campos da listagem, detalhe anterior (mescla por id) e a marca de pendente."""
    novo = dict(sessao)
    for chave in CAMPOS_DETALHE:
        if anterior and chave in anterior:
            novo[chave] = anterior[chave]
    if precisa_detalhe(sessao, anterior, hoje, forcar):
        novo["detalhe_pendente"] = True
    return novo


# ------------------------------------------------------------------- persistência
def caminho_ano(ano: int, pasta: Path | None = None) -> Path:
    return Path(pasta or DIR_SESSOES) / f"{ano}.json"


def anos_existentes(pasta: Path | None = None) -> list[int]:
    base = Path(pasta or DIR_SESSOES)
    return [int(arq.stem) for arq in sorted(base.glob("*.json")) if re.fullmatch(r"\d{4}", arq.stem)]


def carregar_ano(caminho: Path) -> dict[int, dict]:
    if not caminho.exists():
        return {}
    return {r["id"]: r for r in json.loads(caminho.read_text(encoding="utf-8"))}


def chave_arquivo(registro: dict) -> tuple:
    """Ordem dos registros em data/sessoes/<ano>.json: data, hora, número e id."""
    return registro.get("data") or "", registro.get("hora") or "", registro.get("numero") or 0, registro["id"]


def salvar_ano(caminho: Path, registros: dict[int, dict]) -> None:
    salvar_lista(caminho, sorted(registros.values(), key=chave_arquivo))  # uma sessão por linha


def coletar_ano(ano: int, pasta: Path | None = None, forcar: bool = False, hoje: str | None = None) -> dict:
    """Relista o ano e grava o arquivo, sem baixar detalhes (veja coletar_detalhes).

    Mescla o detalhe anterior de cada sessão relistada e marca "detalhe_pendente" onde
    precisa_detalhe indicar. Sessões anteriores que não aparecem na listagem são
    mantidas, com aviso; falha na primeira página mantém o arquivo como está.
    """
    t0 = time.time()
    hoje = hoje or dt.date.today().isoformat()
    caminho = caminho_ano(ano, pasta)
    anteriores = carregar_ano(caminho)
    # as contagens de detalhe do ano (detalhes_baixados, _falhas, _pendentes) entram depois, em coletar
    estat = {
        "listado": 0, "registros": len(anteriores), "preservados": 0,
        "completa": False, "falhas": 0, "sem_resposta": False, "gravado": False,
    }
    try:
        lista = listar_ano(ano)
    except Exception as e:  # nada listado: o arquivo anterior fica como está
        _aviso(f"sessões {ano}: falha na listagem ({e}); arquivo anterior mantido")
        estat.update(falhas=1, sem_resposta=True, segundos=round(time.time() - t0))
        return estat
    itens = lista["itens"]
    estat.update(listado=len(itens), completa=lista["completa"], falhas=len(lista["falhas"]), paginas=lista["paginas"])
    if not itens:
        if anteriores:
            _aviso(f"sessões {ano}: nenhuma sessão listada; arquivo anterior mantido")
        estat["segundos"] = round(time.time() - t0)
        return estat
    registros = {id_sessao: mesclar(s, anteriores.get(id_sessao), hoje, forcar) for id_sessao, s in itens.items()}
    faltam = {i: r for i, r in anteriores.items() if i not in registros}
    if faltam:
        _aviso(
            f"sessões {ano}: {len(faltam)} sessão(ões) do arquivo anterior não aparecem na listagem "
            f"({len(itens)} listadas, {len(anteriores)} antes); mantidas"
        )
        registros.update(faltam)
    salvar_ano(caminho, registros)
    estat.update(registros=len(registros), preservados=len(faltam), gravado=True, segundos=round(time.time() - t0))
    return estat


def _agora() -> float:
    """Relógio do prazo de --max-minutos (monotônico; substituído nos testes)."""
    return time.monotonic()


def prazo_esgotado(prazo: float | None) -> bool:
    return prazo is not None and _agora() >= prazo


def _gravar_alterados(arquivos: dict[int, tuple[Path, dict[int, dict]]], alterados: set[int]) -> None:
    for ano in sorted(alterados):
        salvar_ano(*arquivos[ano])
    alterados.clear()


def coletar_detalhes(
    anos: list[int],
    workers: int,
    pasta: Path | None = None,
    max_detalhes: int = MAX_DETALHES,
    hoje: str | None = None,
    prazo: float | None = None,
    resumo: dict | None = None,
    conhecidos: Collection[int] | None = None,
    contagem: dict[int, dict[str, int]] | None = None,
) -> dict:
    """Baixa o detalhe das sessões com "detalhe_pendente", as mais recentes primeiro.

    A fila reúne os anos da execução e todos os arquivos de data/sessoes; sessão sem
    detalhe e sem a marca recebe a marca. Baixa no máximo max_detalhes páginas; para
    de pedir depois de FALHAS_SEGUIDAS_MAX falhas seguidas ou quando o prazo passa.
    Uma falha (inclusive layout alterado, veja ler_detalhe) deixa o registro como
    estava, ainda pendente; o registro baixado é trocado de uma vez pelo novo. Grava os
    arquivos alterados a cada SALVAR_A_CADA detalhes e no fim, também numa interrupção.
    Em `resumo` ficam fila, baixados, falhas, pendentes e, quando for o caso,
    "prazo_esgotado" e "interrompido_por_falhas"; em `contagem`, por ano,
    detalhes_baixados, detalhes_falhas e detalhes_pendentes (os dois visíveis ao
    chamador mesmo numa interrupção).

    `conhecidos` são os ids que deixam o item de pauta enxuto (veja enxugar_pauta); sem
    eles, ids_conhecidos lê a pasta data/ (a que contém `pasta`) uma única vez, e só se
    houver detalhe a baixar.
    """
    em = hoje or dt.date.today().isoformat()
    resumo = resumo if resumo is not None else {}
    resumo.update(baixados=0, falhas=0, pendentes=0, fila=0)
    contagem = contagem if contagem is not None else {}
    arquivos: dict[int, tuple[Path, dict[int, dict]]] = {}
    alterados: set[int] = set()
    fila: list[tuple[int, dict]] = []
    for ano in sorted(set(anos) | set(anos_existentes(pasta))):
        caminho = caminho_ano(ano, pasta)
        arquivos[ano] = (caminho, carregar_ano(caminho))
        contagem[ano] = {"detalhes_baixados": 0, "detalhes_falhas": 0, "detalhes_pendentes": 0}
        for reg in arquivos[ano][1].values():
            if not reg.get("detalhe_pendente") and not reg.get("detalhe_em"):
                reg["detalhe_pendente"] = True
                alterados.add(ano)
            if reg.get("detalhe_pendente"):
                fila.append((ano, reg))
    fila.sort(key=lambda item: chave_arquivo(item[1]), reverse=True)
    escolhidos = fila[: max(0, max_detalhes)]
    resumo["fila"] = len(fila)
    if escolhidos and prazo_esgotado(prazo):
        _aviso(f"prazo de --max-minutos esgotado antes dos detalhes; {len(fila)} sessão(ões) ficam pendentes")
        resumo["prazo_esgotado"] = True
        escolhidos = []
    if escolhidos and conhecidos is None:
        conhecidos = ids_conhecidos(Path(pasta or DIR_SESSOES).parent)

    def trabalho(registro: dict) -> dict:
        return ler_detalhe(baixar(DETALHE_SESSAO.format(id=registro["id"])), registro)

    ex = ThreadPoolExecutor(max(1, workers))
    try:
        if escolhidos:
            print(f"sessões: baixando {len(escolhidos)} de {len(fila)} detalhe(s) pendente(s)", flush=True)
            seguidas, parou = 0, False
            futuros = {ex.submit(trabalho, reg): (ano, reg) for ano, reg in escolhidos}
            for i, f in enumerate(as_completed(futuros), 1):
                if f.cancelled():  # interrompido abaixo: continua pendente, sem contar como falha
                    continue
                ano, reg = futuros[f]
                try:
                    novo = aplicar_detalhe(reg, f.result(), em, conhecidos or frozenset())
                except Exception as e:  # mantém o registro anterior, ainda pendente
                    resumo["falhas"] += 1
                    contagem[ano]["detalhes_falhas"] += 1
                    seguidas += 1
                    print(f"  falha no detalhe da sessão {reg['id']} ({reg.get('titulo')!r}): {e}", file=sys.stderr)
                else:
                    arquivos[ano][1][reg["id"]] = novo  # troca numa única atribuição
                    resumo["baixados"] += 1
                    contagem[ano]["detalhes_baixados"] += 1
                    alterados.add(ano)
                    seguidas = 0
                if not parou and seguidas >= FALHAS_SEGUIDAS_MAX:
                    parou = resumo["interrompido_por_falhas"] = True
                    canceladas = sum(g.cancel() for g in futuros)
                    _aviso(f"detalhes de sessões interrompidos após {seguidas} falhas seguidas; {canceladas} ficam pendentes")
                elif not parou and prazo_esgotado(prazo):
                    parou = resumo["prazo_esgotado"] = True
                    canceladas = sum(g.cancel() for g in futuros)
                    _aviso(f"prazo de --max-minutos esgotado; {canceladas} detalhe(s) de sessão ficam pendentes")
                if i % SALVAR_A_CADA == 0:
                    print(f"  {i}/{len(escolhidos)} detalhes de sessões", flush=True)
                    _gravar_alterados(arquivos, alterados)
    except BaseException:  # Ctrl+C, SIGTERM (veja main) ou erro: descarta as páginas ainda na fila
        ex.shutdown(wait=False, cancel_futures=True)
        raise
    finally:
        _gravar_alterados(arquivos, alterados)  # antes de esperar as páginas em andamento
        ex.shutdown(wait=True)
        for ano, (_, registros) in arquivos.items():
            contagem[ano]["detalhes_pendentes"] = sum(1 for r in registros.values() if r.get("detalhe_pendente"))
        resumo["pendentes"] = sum(c["detalhes_pendentes"] for c in contagem.values())
    return resumo


# ---------------------------------------------------------------------- execução
def coletar(
    anos: list[int],
    workers: int,
    pasta: Path | None = None,
    max_detalhes: int = MAX_DETALHES,
    forcar: bool = False,
    hoje: str | None = None,
    prazo: float | None = None,
    estat: dict | None = None,
    conhecidos: Collection[int] | None = None,
) -> dict:
    """Lista os anos (do mais recente ao mais antigo) e depois baixa os detalhes pendentes.

    As estatísticas vão sendo gravadas em `estat`, visível ao chamador mesmo numa
    interrupção. Se o SISCAM não responder em LISTAGENS_SEM_RESPOSTA_MAX anos seguidos,
    as demais listagens e os detalhes ficam para a próxima execução. `conhecidos` vai
    para coletar_detalhes (sem ele, os ids são lidos de data/ uma vez).
    """
    estat = estat if estat is not None else {}
    estat.setdefault("anos", {})
    hoje = hoje or dt.date.today().isoformat()
    sem_resposta = 0
    siscam_fora = False
    for ano in sorted(anos, reverse=True):
        if prazo_esgotado(prazo):
            estat["listagem_interrompida"] = "prazo"
            _aviso(f"prazo de --max-minutos esgotado; a listagem de sessões de {ano} e as seguintes ficam para depois")
            break
        e = coletar_ano(ano, pasta, forcar, hoje)
        estat["anos"][str(ano)] = e
        print(f"sessões {ano}: {e['listado']} listadas, {e['registros']} no arquivo, {e['falhas']} falha(s)", flush=True)
        sem_resposta = sem_resposta + 1 if e["sem_resposta"] else 0
        if sem_resposta >= LISTAGENS_SEM_RESPOSTA_MAX:
            siscam_fora = True
            estat["listagem_interrompida"] = "siscam_sem_resposta"
            _aviso(f"SISCAM sem resposta em {sem_resposta} listagens seguidas; o restante fica para a próxima execução")
            break
    limite = 0 if siscam_fora else max_detalhes
    estat["detalhes"] = {"limite": limite}
    contagem: dict[int, dict[str, int]] = {}
    try:
        coletar_detalhes(anos, workers, pasta, limite, hoje, prazo, estat["detalhes"], conhecidos, contagem)
    finally:  # também numa interrupção: as contagens por ano aparecem em data/meta.json
        for ano, c in contagem.items():
            # anos fora da listagem desta execução entram só se tiveram detalhe baixado, falha ou pendência
            if str(ano) in estat["anos"] or any(c.values()):
                estat["anos"].setdefault(str(ano), {}).update(c)
    d = estat["detalhes"]
    if d["falhas"]:
        _aviso(f"{d['falhas']} página(s) de detalhe de sessão falharam; registros anteriores mantidos como pendentes")
    print(
        f"::notice::sessões: {d['baixados']} detalhe(s) baixado(s), {d['falhas']} falha(s); "
        f"{d['pendentes']} sessão(ões) ainda aguardam o detalhe (limite de {limite} por execução)",
        flush=True,
    )
    return estat


def atualizar_meta(estat: dict, caminho: Path | None = None) -> dict:
    """Atualiza a chave "sessoes" de data/meta.json, preservando as demais.

    Cada ano relistado (com "listado") substitui a entrada anterior; o que só teve
    detalhes nesta execução atualiza as contagens de detalhe (detalhes_baixados,
    detalhes_falhas, detalhes_pendentes) e mantém as da última listagem, como em
    coletor.documentos. Grava os totais de detalhe da execução e, se for o caso,
    "listagem_interrompida" e "interrompido" (nome da exceção que parou a execução).
    """
    caminho = Path(caminho or META)
    dados = json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else {}
    por_ano = dict((dados.get("sessoes") or {}).get("anos") or {})
    for ano, valor in (estat.get("anos") or {}).items():
        base = {} if "listado" in valor else por_ano.get(str(ano)) or {}
        por_ano[str(ano)] = {**base, **valor}
    dados["sessoes"] = {
        "em": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "anos": por_ano,
        "detalhes": estat.get("detalhes") or {},
    }
    for chave in ("listagem_interrompida", "interrompido"):
        if estat.get(chave):
            dados["sessoes"][chave] = estat[chave]
    salvar_json(caminho, dados)
    return dados


def _interromper(sinal: int, _quadro: object) -> None:
    """Trata o SIGTERM como Ctrl+C, para que os blocos finally gravem o que já foi aplicado."""
    raise KeyboardInterrupt(f"sinal {sinal}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ano_atual = dt.date.today().year
    ap.add_argument(
        "--anos", default=f"{ano_atual - 1}-{ano_atual}", help="ano ou intervalo inclusivo (padrão: anterior e atual)"
    )
    ap.add_argument("--workers", type=int, default=int(os.environ.get("COLETOR_WORKERS", 4)))
    ap.add_argument(
        "--forcar", action="store_true", help="rebaixa o detalhe de todas as sessões listadas (ainda limitado por --max-detalhes)"
    )
    ap.add_argument(
        "--max-detalhes", type=int, default=MAX_DETALHES,
        help=f"páginas de detalhe por execução, as mais recentes primeiro (padrão: {MAX_DETALHES})",
    )
    ap.add_argument(
        "--max-minutos", type=float, default=None,
        help="prazo interno: ao esgotar, para de listar e de pedir detalhes, grava e atualiza data/meta.json",
    )
    args = ap.parse_args()
    if args.max_detalhes < 0:
        ap.error("--max-detalhes não pode ser negativo")
    if args.max_minutos is not None and args.max_minutos <= 0:
        ap.error("--max-minutos precisa ser positivo")
    try:
        anos = intervalo_anos(args.anos)
    except ValueError as e:
        ap.error(f"--anos inválido: {e}")
    prazo = _agora() + 60 * args.max_minutos if args.max_minutos else None
    signal.signal(signal.SIGTERM, _interromper)
    estat: dict = {"anos": {}}
    try:
        coletar(anos, args.workers, max_detalhes=args.max_detalhes, forcar=args.forcar, prazo=prazo, estat=estat)
    except BaseException as e:
        estat["interrompido"] = type(e).__name__
        _aviso(f"coleta de sessões interrompida ({type(e).__name__}); dados parciais gravados")
        raise
    finally:  # data/meta.json reflete também uma execução interrompida
        atualizar_meta(estat)
    print(json.dumps(estat, ensure_ascii=False, default=str))
    resumos = [e for e in estat["anos"].values() if "listado" in e]  # anos só com detalhes não contam
    if resumos and all(e["falhas"] and not e["listado"] for e in resumos):
        sys.exit(1)
    if estat.get("listagem_interrompida") == "siscam_sem_resposta":
        sys.exit(1)
    detalhes = estat.get("detalhes") or {}
    if detalhes.get("falhas") and not detalhes.get("baixados"):
        sys.exit(1)


if __name__ == "__main__":
    main()
