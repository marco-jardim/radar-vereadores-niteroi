"""Coletor das demais proposituras do SISCAM da Câmara Municipal de Niterói.

Lista requerimentos, indicações, moções, projetos de decreto legislativo (PDL) e
projetos de resolução de cada ano. A listagem já traz número, data, assunto,
ementa, situação, autores e o último passo da tramitação. Grava um JSON por tipo e
ano em data/documentos/<tipo>/<ano>.json, com um registro por linha.

A listagem não distingue autor de coautor: em "autores" eles ficam na ordem em que o
SISCAM os exibe, sem papel atribuído. A "Data Resposta" do último passo é copiada
como está; sozinha, ela não indica a data em que o Executivo respondeu.

Detalhe seletivo: requerimentos, PDLs, resoluções e documentos de mais de um autor
também têm a página de detalhe baixada, com a autoria e o papel de cada autor
("autoria", no mesmo formato dos projetos de lei), a tramitação completa, processo
e protocolo. Dela saem "respondido_em" e "dias_ate_resposta" dos requerimentos e
"publicacao" dos PDLs e resoluções. Indicações e moções de um só autor ficam só com
a listagem. O detalhe é baixado quando falta, quando a contagem de tramitações, a
situação, o último passo ou os autores da listagem mudam, ou com --forcar. A fila
reúne os pendentes de todos os arquivos de data/documentos, não só dos tipos e anos
relistados (assim a carga inicial se completa ao longo das semanas): no máximo
--max-detalhes páginas por execução, as mais recentes primeiro. Os que ficam para
depois, ou cujo download falha, mantêm o detalhe anterior (se houver) e recebem
"detalhe_pendente": true. Com --so-detalhes não relista nada: só esvazia essa fila.

Por padrão relista o ano anterior e o atual, em que a situação ainda muda; para a
carga completa use --anos 2021-<ano atual>. As faixas de número são percorridas
até somarem o total do ano, lido na listagem sem faixa, ou até a primeira faixa sem
documentos do tipo (o fim da numeração, não uma falha). Relistar um ano substitui o
arquivo dele, mas as faixas de número com falha, incompletas, com menos registros
que antes ou vazias onde antes havia registros mantêm os registros anteriores, com
aviso; o detalhe já baixado de cada documento relistado é preservado (mescla por id).
Faixas que somam menos que o total do ano contam como falha. Depois de
FALHAS_FAIXA_MAX falhas seguidas, a listagem do tipo/ano para e mantém o restante;
se o SISCAM não responder em LISTAGENS_SEM_RESPOSTA_MAX listagens seguidas, as demais
listagens e os detalhes ficam para a próxima execução.

Interrupção: --max-minutos é um prazo interno que encerra a execução de forma limpa
(o que falta fica pendente) antes do limite do passo no CI. Num SIGTERM ou Ctrl+C, os
detalhes já aplicados são gravados e data/meta.json é atualizado antes de sair.

Uso: python -m coletor.documentos [--anos 2025-2026]
         [--tipos requerimento,indicacao,mocao,pdl,resolucao] [--workers 4]
         [--max-detalhes 1500] [--sem-detalhe | --so-detalhes] [--forcar] [--max-minutos 100]
     python -m coletor.documentos --arquivos-do-cache DIR [--anos 2025-2026] [--tipos pdl]  (offline: só "arquivos")
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
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from coletor.arquivos import salvar_json, salvar_lista
from coletor.arquivos_siscam import preencher_arquivos_cache, preservar_arquivos
from coletor.regras_documentos import derivar_publicacao, derivar_resposta
from coletor.siscam import BASE, DETALHE, FAIXA, baixar, campo, data_iso, limpar, montar_registro, parse_detalhe

# código de cada tipo no parâmetro Tipo da listagem do SISCAM
TIPOS = {"requerimento": 1, "indicacao": 2, "mocao": 3, "pdl": 6, "resolucao": 7}
# rótulo exibido em cada registro ("Indicação Nº 00400/2025") e no cabeçalho do total
ROTULOS = {
    "requerimento": "Requerimento",
    "indicacao": "Indicação",
    "mocao": "Moção",
    "pdl": "Projeto de Decreto Legislativo",
    "resolucao": "Projeto de Resolução",
}
# cabeçalhos de total que o SISCAM exibe numa consulta sem documentos do tipo pedido;
# qualquer outro rótulo é tratado como mudança de layout (veja pagina_de_outro_tipo)
ROTULOS_CONHECIDOS = frozenset(ROTULOS.values()) | {"Projeto de Lei"}
# listagem do ano inteiro, sem faixa de número: dela só se lê o total do cabeçalho
LISTAGEM_ANO = BASE + "/ResultadoPropositura.aspx?Tipo={tipo}&Exibir=1,2,3,4,6,7,8&Ano={ano}&pagina={pagina}"
LISTAGEM = LISTAGEM_ANO + "&NumeroInicial={ini}&NumeroFinal={fim}"
POR_PAGINA = 10
PAGINAS_MAX = 50  # o SISCAM não pagina além da página 50; por isso as faixas de FAIXA números
FAIXAS_MAX = 100  # trava de segurança: até 40.000 números por tipo e ano
FALHAS_FAIXA_MAX = 3  # falhas seguidas de faixa que encerram a listagem do tipo/ano
LISTAGENS_SEM_RESPOSTA_MAX = 2  # tipos/anos seguidos sem resposta que encerram as listagens da execução
# tipos que sempre têm o detalhe baixado; os demais, só com mais de um autor
TIPOS_COM_DETALHE = frozenset({"requerimento", "pdl", "resolucao"})
MAX_DETALHES = 1500  # páginas de detalhe por execução: a carga inicial se divide entre semanas
SALVAR_A_CADA = 100  # detalhes baixados entre gravações parciais
FALHAS_SEGUIDAS_MAX = 20  # interrompe os detalhes da execução depois de tantas falhas seguidas
# campos vindos da página de detalhe, preservados quando o documento é relistado
CAMPOS_DETALHE = ("autoria", "tramitacoes", "processo", "protocolo", "data_protocolo", "detalhe_em", "arquivos")
RAIZ = Path(__file__).resolve().parent.parent
DIR_DOCUMENTOS = RAIZ / "data" / "documentos"
META = RAIZ / "data" / "meta.json"


# ----------------------------------------------------------------------- listagem
BLOCO = 'class="tabela-simples"'  # só os registros usam aspas duplas; o filtro usa aspas simples
RE_AUTOR = re.compile(r"Autor=(\d+)'>([^<]+)</a>")
RE_N_TRAMITACOES = re.compile(r"Última Tramitac[^(]*\((\d+)\)")  # o SISCAM escreve "Tramitacação"
RE_DESTAQUE = re.compile(r"<h3 class='destaque'>(.*?)</h3>", re.S)
RE_ROTULO = {
    tipo: re.compile(r'IdDocumento=(\d+)"[^>]*>\s*' + re.escape(rotulo) + r"\s+N[º°o]\.?\s*(\d+)/(\d{4})")
    for tipo, rotulo in ROTULOS.items()
}
RE_TOTAL = {
    tipo: re.compile(
        r"<h3 class='destaque'>" + re.escape(rotulo)
        + r"</h3>\s*\(<span class='total-item'><strong>(\d+) registro"
    )
    for tipo, rotulo in ROTULOS.items()
}


def _secoes(bloco: str) -> tuple[str, str]:
    """Separa o cabeçalho do registro do trecho com a última tramitação."""
    cabecalho, _, resto = bloco.partition('_trTramitacoes"')
    return cabecalho.split('_trVinculos"')[0], resto.split('_trVinculos"')[0]


def parse_ultima_tramitacao(trecho: str) -> dict | None:
    """Lê o único passo de tramitação que a listagem exibe (o último), se houver."""
    passos = trecho.split("<strong>Sequência: </strong>")[1:]
    if not passos:
        return None
    passo = passos[-1]
    seq = re.match(r"\s*(\d+)", passo)
    return {
        "seq": int(seq.group(1)) if seq else None,
        "objetivo": campo(r"Objetivo: </strong>(.*?)</td>", passo),
        "enviado": data_iso(campo(r"Enviado em: </strong>(.*?)</td>", passo)),
        "resultado": campo(r"Resultado: </strong>(.*?)</td>", passo),
        # copiada como está: não é, por si só, a data da resposta do Executivo
        "data_resposta": data_iso(campo(r"Data Resposta: </strong>(.*?)</td>", passo)),
        "observacao": campo(r"Observação: </strong>(.*?)</td>", passo),
    }


def _autores(cabecalho: str) -> list[dict]:
    """Autores na ordem da listagem, sem papel: a listagem não marca o autor principal."""
    linha = re.search(r'_trAutores"(.*?)</tr>', cabecalho, re.S)
    autores, vistos = [], set()
    for id_autor, nome in RE_AUTOR.findall(linha.group(1) if linha else cabecalho):
        if int(id_autor) not in vistos:
            vistos.add(int(id_autor))
            autores.append({"id": int(id_autor), "nome": limpar(nome)})
    return autores


def parse_listagem(pagina_html: str, tipo: str) -> list[dict]:
    """Extrai os registros de uma página de listagem do tipo informado.

    Levanta ValueError se um bloco de registro não trouxer o rótulo do tipo: é
    sinal de página de outro tipo ou de mudança no layout do SISCAM.
    """
    padrao = RE_ROTULO[tipo]
    itens = []
    for bloco in pagina_html.split(BLOCO)[1:]:
        m = padrao.search(bloco)
        if not m:
            raise ValueError(f"registro sem o rótulo {ROTULOS[tipo]!r} na listagem; o layout do SISCAM mudou?")
        doc, numero, ano = m.groups()
        cabecalho, tramitacao = _secoes(bloco)
        ntram = RE_N_TRAMITACOES.search(tramitacao)
        itens.append(
            {
                "id": int(doc),
                "tipo": tipo,
                "numero": f"{int(numero)}/{ano}",
                "ano": int(ano),
                "data": data_iso(campo(r"<strong>Data: </strong>([^<]*)", cabecalho)),
                # rótulo curto do SISCAM ("TAPA BURACO", "DECRETO/MEDALHA"); não confundir com a ementa
                "assunto": campo(r"<strong>Assunto:\s*</strong>(.*?)</td>", cabecalho),
                "ementa": campo(r"Ementa/Assunto: </strong>(.*?)</td>", cabecalho),
                "situacao": campo(r"Situação: </strong>([^<]*)", cabecalho),
                "autores": _autores(cabecalho),
                "ultima_tramitacao": parse_ultima_tramitacao(tramitacao),
                "n_tramitacoes": int(ntram.group(1)) if ntram else 0,
                "url": DETALHE.format(doc=int(doc)),
            }
        )
    return itens


def total_registros(pagina_html: str, tipo: str) -> int:
    """Total de registros da consulta, lido no cabeçalho de paginação.

    Devolve 0 se a página não tiver cabeçalho de total (consulta sem resultado) e
    levanta ValueError se o cabeçalho for de outro tipo ou estiver em outro formato.
    """
    m = RE_TOTAL[tipo].search(pagina_html)
    if m:
        return int(m.group(1))
    outro = RE_DESTAQUE.search(pagina_html)
    if outro:
        raise ValueError(
            f"cabeçalho de total inesperado ({limpar(outro.group(1))!r}; esperado {ROTULOS[tipo]!r})"
        )
    return 0


def pagina_de_outro_tipo(pagina_html: str, tipo: str) -> bool:
    """Se a página é a resposta do SISCAM a uma consulta sem documentos do tipo.

    Sem documentos do tipo na faixa, o SISCAM exibe o cabeçalho de total de outro
    tipo (por exemplo, "Indicação" numa consulta de requerimentos), sem registros ou
    só com registros desse outro tipo. Só valem os rótulos de ROTULOS_CONHECIDOS.
    Cabeçalho desconhecido, cabeçalho de outro tipo com registros do tipo pedido ou
    com registros sem o rótulo do cabeçalho não entram aqui: é mudança de layout, e
    total_registros levanta ValueError.
    """
    if RE_TOTAL[tipo].search(pagina_html):
        return False
    outro = RE_DESTAQUE.search(pagina_html)
    rotulo = limpar(outro.group(1)) if outro else ""
    if not rotulo or rotulo == ROTULOS[tipo] or rotulo not in ROTULOS_CONHECIDOS:
        return False
    padrao = re.compile(r'IdDocumento=\d+"[^>]*>\s*' + re.escape(rotulo) + r"\s+N[º°o]")
    return all(padrao.search(bloco) for bloco in pagina_html.split(BLOCO)[1:])


def url_listagem(tipo: str, ano: int, ini: int, fim: int, pagina: int) -> str:
    return LISTAGEM.format(tipo=TIPOS[tipo], ano=ano, pagina=pagina, ini=ini, fim=fim)


def url_ano(tipo: str, ano: int) -> str:
    """Primeira página da listagem do ano sem faixa de número, de onde sai o total do ano."""
    return LISTAGEM_ANO.format(tipo=TIPOS[tipo], ano=ano, pagina=1)


def total_do_ano(tipo: str, ano: int) -> int | None:
    """Total de documentos do tipo no ano, lido no cabeçalho da listagem sem faixa.

    Devolve 0 se o ano não tiver documentos do tipo e None, com aviso, se a página
    não puder ser lida; nesse caso a listagem segue pelas faixas até a primeira vazia.
    """
    try:
        pagina = baixar(url_ano(tipo, ano))
        if pagina_de_outro_tipo(pagina, tipo):
            return 0
        total = total_registros(pagina, tipo)
        if total == 0 and BLOCO in pagina:
            raise ValueError("página com registros e sem total; o layout do SISCAM mudou?")
        return total
    except Exception as e:  # o total só encurta e confere a varredura das faixas
        print(
            f"::warning::{tipo} {ano}: total do ano indisponível ({e}); listagem segue pelas faixas",
            file=sys.stderr,
        )
        return None


def listar_faixa(tipo: str, ano: int, ini: int, fim: int, workers: int) -> tuple[list[dict], int]:
    """Lista os registros numerados de ini a fim; devolve (registros, total informado).

    Faixa sem documentos do tipo devolve ([], 0), inclusive quando o SISCAM responde
    com o cabeçalho de outro tipo (veja pagina_de_outro_tipo).
    """
    primeira = baixar(url_listagem(tipo, ano, ini, fim, 1))
    if pagina_de_outro_tipo(primeira, tipo):
        return [], 0
    total = total_registros(primeira, tipo)
    itens = parse_listagem(primeira, tipo)
    if total == 0:
        if BLOCO in primeira:
            raise ValueError(
                f"{tipo} {ano}, faixa {ini}-{fim}: página com registros e sem total; o layout do SISCAM mudou?"
            )
        return [], 0
    if not itens:
        raise ValueError(
            f"{tipo} {ano}, faixa {ini}-{fim}: total de {total} registros, mas nenhum reconhecido na página 1"
        )
    paginas = (total + POR_PAGINA - 1) // POR_PAGINA
    if paginas > PAGINAS_MAX:
        raise ValueError(f"{tipo} {ano}, faixa {ini}-{fim}: {paginas} páginas, além do limite de {PAGINAS_MAX}")
    if paginas > 1:
        with ThreadPoolExecutor(max(1, workers)) as ex:
            futuros = [ex.submit(baixar, url_listagem(tipo, ano, ini, fim, p)) for p in range(2, paginas + 1)]
            for f in as_completed(futuros):
                itens.extend(parse_listagem(f.result(), tipo))
    return itens, total


def numero_int(registro: dict) -> int:
    return int(registro["numero"].split("/")[0])


def chave_arquivo(registro: dict) -> tuple[int, int, int]:
    """Ordem dos registros em data/documentos/<tipo>/<ano>.json: ano, número e id."""
    return registro["ano"], numero_int(registro), registro["id"]


def listar_ano(tipo: str, ano: int, workers: int, anteriores: dict[int, dict] | None = None) -> dict:
    """Percorre as faixas de número do ano até a primeira faixa vazia ou até o total do ano.

    Quando as faixas somam exatamente o total do ano (total_do_ano), para sem pedir a
    faixa seguinte; sem esse total, ou se a soma não bater, segue até a primeira faixa
    vazia, que marca o fim da numeração e não é falha. Faixas com falha, incompletas,
    com menos registros que os anteriores ou vazias onde antes havia registros vão
    para "faixas_preservar", para que o chamador mantenha os registros anteriores delas.

    Depois de FALHAS_FAIXA_MAX falhas seguidas, para e preserva também as faixas que
    faltam até o maior número anterior. Faixas que somam menos que o total do ano
    contam como falha. "sem_resposta" indica que nenhuma faixa pedida foi respondida.
    """
    anteriores = anteriores or {}
    maior_anterior = max((numero_int(r) for r in anteriores.values()), default=0)
    total_ano = total_do_ano(tipo, ano)
    itens: dict[int, dict] = {}
    esperado = 0
    preservar: list[tuple[int, int]] = []
    falhas: list[str] = []
    respondidas = 0  # faixas em que o SISCAM respondeu, com ou sem registros
    seguidas = 0  # falhas seguidas de faixa
    ini = 1
    for _ in range(FAIXAS_MAX):
        if total_ano and esperado == total_ano and maior_anterior < ini:
            break  # as faixas já somam o total do ano
        fim = ini + FAIXA - 1
        try:
            lote, total = listar_faixa(tipo, ano, ini, fim, workers)
        except Exception as e:  # mantém os registros anteriores da faixa
            seguidas += 1
            falhas.append(f"faixa {ini}-{fim}: {e}")
            preservar.append((ini, fim))
            print(
                f"::warning::{tipo} {ano}, faixa {ini}-{fim}: falha na listagem ({e}); "
                "registros anteriores da faixa mantidos",
                file=sys.stderr,
            )
            if maior_anterior <= fim:
                break
            if seguidas >= FALHAS_FAIXA_MAX:  # o SISCAM parou de responder: não insiste no resto do ano
                preservar.append((fim + 1, maior_anterior))
                falhas.append(f"listagem interrompida após {seguidas} falhas seguidas")
                print(
                    f"::warning::{tipo} {ano}: listagem interrompida após {seguidas} falhas seguidas; "
                    f"registros anteriores de {fim + 1} a {maior_anterior} mantidos",
                    file=sys.stderr,
                )
                break
            ini += FAIXA
            continue
        respondidas += 1
        seguidas = 0
        if total == 0:
            if maior_anterior < ini:
                break  # fim da numeração do ano
            falhas.append(f"faixa {ini}-{fim}: listagem vazia, mas havia registros até o nº {maior_anterior}")
            preservar.append((ini, fim))
            print(
                f"::warning::{tipo} {ano}, faixa {ini}-{fim}: listagem vazia, mas havia registros "
                f"até o nº {maior_anterior}; registros anteriores mantidos",
                file=sys.stderr,
            )
            if maior_anterior <= fim:
                break
            ini += FAIXA
            continue
        unicos = {i["id"]: i for i in lote}
        antes = sum(1 for r in anteriores.values() if ini <= numero_int(r) <= fim)
        if len(unicos) < total:
            preservar.append((ini, fim))
        elif len(unicos) < antes:  # sumiram registros: mantém os anteriores até a próxima listagem
            preservar.append((ini, fim))
            print(
                f"::warning::{tipo} {ano}, faixa {ini}-{fim}: {len(unicos)} registros listados, menos que os "
                f"{antes} anteriores; registros anteriores da faixa mantidos",
                file=sys.stderr,
            )
        itens.update(unicos)
        esperado += total
        ini += FAIXA
    else:
        falhas.append(f"mais de {FAIXAS_MAX} faixas de {FAIXA} números")
        print(f"::warning::{tipo} {ano}: listagem interrompida após {FAIXAS_MAX} faixas", file=sys.stderr)
    if total_ano and esperado != total_ano:
        if esperado < total_ano:  # faltam registros do ano: a listagem não está completa
            falhas.append(f"as faixas somam {esperado} registros, mas o total do ano é {total_ano}")
        print(
            f"::warning::{tipo} {ano}: as faixas somam {esperado} registros, mas o total do ano é {total_ano}",
            file=sys.stderr,
        )
    if len(itens) < esperado:
        print(f"::warning::{tipo} {ano}: listou {len(itens)} de {esperado} registros", file=sys.stderr)
    return {
        "itens": itens, "esperado": esperado, "total_ano": total_ano, "faixas_preservar": preservar, "falhas": falhas,
        "sem_resposta": respondidas == 0 and seguidas > 0,
    }


# ------------------------------------------------------------------------ detalhe
# título da página de detalhe: "Requerimento Nº 00251/2025", "Projeto de Resolução Nº 00022/2025"
RE_TITULO_DETALHE = re.compile(r'class="form-task">[^<]*?N[º°o]\.?\s*(\d+)/(\d{4})')


def elegivel_detalhe(registro: dict) -> bool:
    """Se o documento tem a página de detalhe baixada: requerimento, PDL, resolução ou mais de um autor.

    Neles a listagem não basta: o papel de cada autor, a tramitação completa e as
    datas de resposta e de publicação só aparecem no detalhe. Indicações e moções
    de um só autor ficam só com a listagem.
    """
    return registro.get("tipo") in TIPOS_COM_DETALHE or len(registro.get("autores") or []) > 1


def tem_detalhe(registro: dict | None) -> bool:
    return bool(registro and registro.get("detalhe_em"))


def falta_arquivos(registro: dict | None) -> bool:
    """Requerimento, PDL ou resolução com detalhe baixado antes do suporte à chave "arquivos".

    Entra de novo na fila de detalhes (dentro de --max-detalhes, por recência). Indicações e
    moções de vários autores ficam de fora: o inteiro teor delas está fora do escopo.
    """
    return bool(registro) and registro.get("tipo") in TIPOS_COM_DETALHE and tem_detalhe(registro) \
        and "arquivos" not in registro


def precisa_detalhe(registro: dict, anterior: dict | None, forcar: bool = False) -> bool:
    """Se o detalhe de um documento elegível deve ser baixado.

    Sim quando ainda não há detalhe, quando ele ficou pendente numa execução anterior
    (adiado pelo limite ou com falha), quando a contagem de tramitações, a situação ou
    o último passo da listagem diferem dos gravados no registro anterior (um passo
    pode ser editado, ou a situação mudar, sem que a contagem mude), quando os autores
    listados mudaram (a autoria do detalhe ficaria desatualizada), quando o detalhe antigo
    de requerimento, PDL ou resolução não tem "arquivos" (falta_arquivos) ou com forcar.
    """
    if not elegivel_detalhe(registro):
        return False
    if forcar or anterior is None or not tem_detalhe(anterior) or anterior.get("detalhe_pendente"):
        return True
    if falta_arquivos(anterior):
        return True
    return (
        anterior.get("n_tramitacoes") != registro.get("n_tramitacoes")
        or anterior.get("situacao") != registro.get("situacao")
        or anterior.get("ultima_tramitacao") != registro.get("ultima_tramitacao")
        or _ids_autores(anterior) != _ids_autores(registro)
    )


def _ids_autores(registro: dict) -> list:
    return sorted(str(a.get("id")) for a in registro.get("autores") or [])


def derivar_campos(registro: dict) -> dict:
    """Recalcula os campos derivados da tramitação completa, sem rebaixar nada.

    Sem detalhe não há tramitação completa e os campos ficam ausentes (desconhecidos),
    em vez de nulos (que indicariam "não respondido" ou "não publicado").
    """
    if "tramitacoes" not in registro:
        return registro
    if registro.get("tipo") == "requerimento":
        registro.update(derivar_resposta(registro))
    elif registro.get("tipo") in ("pdl", "resolucao"):
        registro["publicacao"] = derivar_publicacao(registro["tramitacoes"])
    return registro


def herdar_detalhe(registro: dict, anterior: dict | None) -> dict:
    """Copia para o registro relistado os campos do detalhe já baixado (mescla por id)."""
    for chave in CAMPOS_DETALHE:
        if anterior and chave in anterior:
            registro[chave] = anterior[chave]
    return registro


def ler_detalhe(pagina_html: str, registro: dict) -> dict:
    """Lê a página de detalhe com o mesmo parser dos projetos de lei (siscam.parse_detalhe).

    O layout é o mesmo; aqui só se confere que a página é a do documento pedido e
    que a tramitação não sumiu, para que uma página de erro ou um layout novo não
    vire, em silêncio, autoria e tramitação vazias. Levanta ValueError nesses casos.
    """
    m = RE_TITULO_DETALHE.search(pagina_html)
    if not m or f"{int(m.group(1))}/{m.group(2)}" != registro["numero"]:
        achado = f"{int(m.group(1))}/{m.group(2)}" if m else "nenhum"
        raise ValueError(f"página de detalhe sem o título do nº {registro['numero']} (encontrado: {achado})")
    detalhe = parse_detalhe(pagina_html)
    if registro.get("n_tramitacoes") and not detalhe["tramitacoes"]:
        raise ValueError(
            f"detalhe sem tramitação, mas a listagem informa {registro['n_tramitacoes']} passo(s); o layout mudou?"
        )
    return detalhe


def aplicar_detalhe(registro: dict, detalhe: dict, em: str) -> dict:
    """Grava no registro a autoria com papéis, a tramitação completa, processo e protocolo.

    A autoria sai de siscam.montar_registro, igual à dos projetos de lei: cada autor
    do detalhe recebe o id da listagem pelo nome, e quem só aparece na listagem entra
    no fim. Os campos que montar_registro calcula só para projetos de lei ("lei" e
    "desfecho") são descartados; "autores" e os demais campos da listagem ficam como
    estão. O registro só é alterado depois que tudo foi calculado.
    """
    resumo = {
        "id": registro["id"],
        "numero": registro["numero"],
        "ano": registro["ano"],
        "n_tramitacoes": registro.get("n_tramitacoes", 0),
        "situacao": registro.get("situacao") or "",
        "autor_ids": [(a.get("id"), a.get("nome") or "") for a in registro.get("autores") or []],
    }
    montado = montar_registro(resumo, detalhe)
    novo = {k: v for k, v in registro.items() if k != "detalhe_pendente"}
    for chave in ("autoria", "tramitacoes", "processo", "protocolo", "data_protocolo", "arquivos"):
        novo[chave] = montado[chave]
    preservar_arquivos(registro, novo)
    novo["detalhe_em"] = em
    derivar_campos(novo)
    registro.clear()
    registro.update(novo)
    return registro


def marcar_detalhes(registros: dict[int, dict], anteriores: dict[int, dict], forcar: bool = False) -> int:
    """Mescla o detalhe anterior nos registros relistados e marca os que precisam de detalhe.

    Nos relistados, marca "detalhe_pendente": true onde precisa_detalhe indicar e
    tira a marca dos demais. Os preservados de faixas com falha (os próprios objetos
    anteriores) ficam como estavam, inclusive a marca. Devolve quantos relistados
    ficaram marcados.
    """
    pendentes = 0
    for id_doc, reg in registros.items():
        anterior = anteriores.get(id_doc)
        if reg is anterior:
            continue
        herdar_detalhe(reg, anterior)
        derivar_campos(reg)
        if precisa_detalhe(reg, anterior, forcar):
            reg["detalhe_pendente"] = True
            pendentes += 1
        else:
            reg.pop("detalhe_pendente", None)
    return pendentes


def recencia(registro: dict) -> tuple:
    """Chave de ordenação por recência: data do documento, ano, número e id."""
    return (registro.get("data") or "", registro.get("ano") or 0, numero_int(registro), registro.get("id") or 0)


def _gravar_alterados(arquivos: dict[tuple[str, int], tuple[Path, dict[int, dict]]], alterados: set) -> None:
    for chave in sorted(alterados):
        caminho, registros = arquivos[chave]
        salvar_ano(caminho, registros)
    alterados.clear()


def _agora() -> float:
    """Relógio do prazo de --max-minutos (monotônico; substituído nos testes)."""
    return time.monotonic()


def prazo_esgotado(prazo: float | None) -> bool:
    """Se o prazo interno (instante de _agora) já passou; sem prazo, nunca."""
    return prazo is not None and _agora() >= prazo


def coletar_detalhes(
    tipos: list[str],
    anos: list[int],
    workers: int,
    pasta: Path | None = None,
    max_detalhes: int = MAX_DETALHES,
    hoje: str | None = None,
    prazo: float | None = None,
    contagem: dict[tuple[str, int], dict[str, int]] | None = None,
    resumo: dict | None = None,
) -> dict[tuple[str, int], dict[str, int]]:
    """Baixa o detalhe dos documentos com "detalhe_pendente", os mais recentes primeiro.

    A fila reúne os tipos e anos da execução e todos os arquivos já existentes em
    data/documentos, para que os pendentes de anos que não são mais relistados também
    sejam baixados. Documento elegível sem detalhe e sem a marca (arquivo de versão
    anterior) recebe "detalhe_pendente" e entra na fila, assim como o detalhe antigo sem
    "arquivos" (veja falta_arquivos). Baixa no máximo max_detalhes
    páginas; os demais continuam pendentes para a próxima execução. Uma falha deixa o
    registro como estava (com o detalhe anterior, se houver) e ainda pendente.

    Para de pedir páginas depois de FALHAS_SEGUIDAS_MAX falhas seguidas ou quando o
    prazo (instante de _agora) passa; as páginas já em andamento ainda são aplicadas.
    Grava os arquivos alterados a cada SALVAR_A_CADA detalhes e no fim, também quando
    interrompido (Ctrl+C, SIGTERM ou erro): o que já foi aplicado não se perde.

    Devolve, por (tipo, ano), detalhes_baixados, detalhes_falhas e detalhes_pendentes,
    preenchidos em `contagem` se informado (visível ao chamador mesmo numa
    interrupção). Em `resumo`, se informado, ficam "fila" e, quando for o caso,
    "prazo_esgotado" e "interrompido_por_falhas".
    """
    em = hoje or dt.date.today().isoformat()
    contagem = contagem if contagem is not None else {}
    resumo = resumo if resumo is not None else {}
    chaves = sorted({(t, a) for t in tipos for a in anos} | set(arquivos_existentes(pasta)))
    arquivos: dict[tuple[str, int], tuple[Path, dict[int, dict]]] = {}
    alterados: set[tuple[str, int]] = set()
    fila = []
    for chave in chaves:
        caminho = caminho_ano(*chave, pasta)
        arquivos[chave] = (caminho, carregar_ano(caminho))
        contagem[chave] = {"detalhes_baixados": 0, "detalhes_falhas": 0, "detalhes_pendentes": 0}
        for reg in arquivos[chave][1].values():
            if not reg.get("detalhe_pendente") and elegivel_detalhe(reg) and (not tem_detalhe(reg) or falta_arquivos(reg)):
                reg["detalhe_pendente"] = True
                alterados.add(chave)
            if reg.get("detalhe_pendente"):
                fila.append((chave, reg))
    fila.sort(key=lambda item: recencia(item[1]), reverse=True)
    escolhidos = fila[: max(0, max_detalhes)]
    resumo["fila"] = len(fila)
    if escolhidos and prazo_esgotado(prazo):
        print(
            f"::warning::prazo de --max-minutos esgotado antes dos detalhes; {len(fila)} página(s) "
            "ficam pendentes para a próxima execução",
            file=sys.stderr,
        )
        resumo["prazo_esgotado"] = True
        escolhidos = []

    def trabalho(registro: dict) -> dict:
        return ler_detalhe(baixar(DETALHE.format(doc=registro["id"])), registro)

    ex = ThreadPoolExecutor(max(1, workers))
    try:
        if escolhidos:
            print(f"detalhes: baixando {len(escolhidos)} de {len(fila)} pendente(s)", flush=True)
            seguidas = 0
            parou = False
            futuros = {ex.submit(trabalho, reg): (chave, reg) for chave, reg in escolhidos}
            for i, f in enumerate(as_completed(futuros), 1):
                if f.cancelled():  # interrompido abaixo: continua pendente, sem contar como falha
                    continue
                chave, reg = futuros[f]
                try:
                    aplicar_detalhe(reg, f.result(), em)
                except Exception as e:  # mantém o registro anterior, ainda pendente
                    contagem[chave]["detalhes_falhas"] += 1
                    seguidas += 1
                    print(f"  falha no detalhe de {chave[0]} {reg['numero']} (id {reg['id']}): {e}", file=sys.stderr)
                else:
                    contagem[chave]["detalhes_baixados"] += 1
                    alterados.add(chave)
                    seguidas = 0
                if not parou and seguidas >= FALHAS_SEGUIDAS_MAX:
                    # com o SISCAM fora do ar, cada página esgota as tentativas: não prende a coleta semanal
                    parou = resumo["interrompido_por_falhas"] = True
                    canceladas = sum(g.cancel() for g in futuros)
                    print(
                        f"::warning::detalhes interrompidos após {seguidas} falhas seguidas; "
                        f"{canceladas} página(s) ficam pendentes para a próxima execução",
                        file=sys.stderr,
                    )
                elif not parou and prazo_esgotado(prazo):
                    parou = resumo["prazo_esgotado"] = True
                    canceladas = sum(g.cancel() for g in futuros)
                    print(
                        f"::warning::prazo de --max-minutos esgotado; detalhes interrompidos e "
                        f"{canceladas} página(s) ficam pendentes para a próxima execução",
                        file=sys.stderr,
                    )
                if i % SALVAR_A_CADA == 0:
                    print(f"  {i}/{len(escolhidos)} detalhes", flush=True)
                    _gravar_alterados(arquivos, alterados)
    except BaseException:  # Ctrl+C, SIGTERM (veja main) ou erro: descarta as páginas ainda na fila
        ex.shutdown(wait=False, cancel_futures=True)
        raise
    finally:
        _gravar_alterados(arquivos, alterados)  # antes de esperar as páginas em andamento
        ex.shutdown(wait=True)
        for chave, (_, registros) in arquivos.items():
            contagem[chave]["detalhes_pendentes"] = sum(1 for r in registros.values() if r.get("detalhe_pendente"))
    return contagem


# ------------------------------------------------------------------- persistência
def caminho_ano(tipo: str, ano: int, pasta: Path | None = None) -> Path:
    return Path(pasta or DIR_DOCUMENTOS) / tipo / f"{ano}.json"


def arquivos_existentes(pasta: Path | None = None) -> list[tuple[str, int]]:
    """(tipo, ano) de cada data/documentos/<tipo>/<ano>.json já gravado, de qualquer tipo conhecido."""
    base = Path(pasta or DIR_DOCUMENTOS)
    return [
        (tipo, int(arq.stem))
        for tipo in TIPOS
        for arq in sorted((base / tipo).glob("*.json"))
        if re.fullmatch(r"\d{4}", arq.stem)
    ]


def carregar_ano(caminho: Path) -> dict[int, dict]:
    if not caminho.exists():
        return {}
    return {r["id"]: r for r in json.loads(caminho.read_text(encoding="utf-8"))}


def salvar_ano(caminho: Path, registros: dict[int, dict]) -> None:
    lista = sorted(registros.values(), key=chave_arquivo)
    salvar_lista(caminho, lista)  # um documento por linha: diffs por registro


def coletar_ano(tipo: str, ano: int, workers: int, pasta: Path | None = None, forcar: bool = False) -> dict:
    """Relista um tipo/ano e grava o arquivo, preservando o que não pôde ser relistado.

    Não baixa detalhes: mescla o detalhe anterior de cada documento e marca com
    "detalhe_pendente" os que precisam dele (veja coletar_detalhes).
    """
    t0 = time.time()
    caminho = caminho_ano(tipo, ano, pasta)
    anteriores = carregar_ano(caminho)
    lista = listar_ano(tipo, ano, workers, anteriores)
    registros = dict(lista["itens"])
    preservados = 0
    for ini, fim in lista["faixas_preservar"]:
        for id_doc, reg in anteriores.items():
            if id_doc not in registros and ini <= numero_int(reg) <= fim:
                registros[id_doc] = reg
                preservados += 1
    estat = {
        "esperado": lista["esperado"],
        "total_ano": lista["total_ano"],  # None quando o total do ano não pôde ser lido
        "listado": len(lista["itens"]),
        "preservados": preservados,
        "registros": len(registros),
        "falhas": len(lista["falhas"]),
        "sem_resposta": lista["sem_resposta"],
        "gravado": False,
    }
    if not registros and (anteriores or lista["falhas"] or lista["total_ano"]):
        if anteriores:  # nunca troca um arquivo com dados por uma lista vazia
            print(f"::warning::{tipo} {ano}: nenhum registro listado; arquivo anterior mantido", file=sys.stderr)
        elif lista["total_ano"]:  # nem cria um arquivo vazio para um ano que tem documentos
            print(
                f"::warning::{tipo} {ano}: nenhum registro listado, mas o total do ano é {lista['total_ano']}; "
                "arquivo não gravado",
                file=sys.stderr,
            )
        estat["registros"] = len(anteriores)
    else:
        if len(registros) < len(anteriores):
            print(
                f"::warning::{tipo} {ano}: {len(registros)} registros, menos que os {len(anteriores)} anteriores",
                file=sys.stderr,
            )
        marcar_detalhes(registros, anteriores, forcar)
        salvar_ano(caminho, registros)
        estat["gravado"] = True
    estat["segundos"] = round(time.time() - t0)
    return estat


def coletar(
    tipos: list[str],
    anos: list[int],
    workers: int,
    pasta: Path | None = None,
    max_detalhes: int = MAX_DETALHES,
    sem_detalhe: bool = False,
    forcar: bool = False,
    hoje: str | None = None,
    so_detalhes: bool = False,
    prazo: float | None = None,
    estat: dict | None = None,
) -> dict:
    """Lista todos os tipos e anos e depois baixa os detalhes pendentes, dentro do limite.

    Com so_detalhes, não lista nada: só baixa os pendentes. As estatísticas vão sendo
    gravadas em `estat` (se informado), para que o chamador as tenha mesmo numa
    interrupção. Se o SISCAM não responder em LISTAGENS_SEM_RESPOSTA_MAX listagens
    seguidas, ou se o prazo (instante de _agora) passar, as listagens restantes ficam
    para a próxima execução ("listagem_interrompida"); no primeiro caso, os detalhes também.
    """
    estat = estat if estat is not None else {}
    estat.setdefault("tipos", {})
    siscam_fora = False
    if so_detalhes:
        print("listagem: desativada (--so-detalhes); só os detalhes pendentes", flush=True)
    else:
        sem_resposta = 0
        for tipo, ano in [(t, a) for t in tipos for a in anos]:
            if prazo_esgotado(prazo):
                estat["listagem_interrompida"] = "prazo"
                print(
                    f"::warning::prazo de --max-minutos esgotado; a listagem de {tipo} {ano} e as seguintes "
                    "ficam para a próxima execução",
                    file=sys.stderr,
                )
                break
            e = coletar_ano(tipo, ano, workers, pasta, forcar)
            estat["tipos"].setdefault(tipo, {})[str(ano)] = e
            print(
                f"{tipo} {ano}: {e['listado']} listados de {e['esperado']} esperados, "
                f"{e['registros']} no arquivo, {e['falhas']} falha(s)",
                flush=True,
            )
            sem_resposta = sem_resposta + 1 if e["sem_resposta"] else 0
            if sem_resposta >= LISTAGENS_SEM_RESPOSTA_MAX:
                siscam_fora = True
                estat["listagem_interrompida"] = "siscam_sem_resposta"
                print(
                    f"::warning::SISCAM sem resposta em {sem_resposta} listagens seguidas; as demais listagens "
                    "e os detalhes ficam para a próxima execução",
                    file=sys.stderr,
                )
                break
    limite = 0 if sem_detalhe or siscam_fora else max_detalhes
    if sem_detalhe:
        print("detalhes: download desativado (--sem-detalhe)", flush=True)
    estat["detalhes"] = {"baixados": 0, "falhas": 0, "pendentes": 0, "limite": limite}
    detalhes: dict[tuple[str, int], dict[str, int]] = {}
    try:
        coletar_detalhes(tipos, anos, workers, pasta, limite, hoje, prazo, detalhes, estat["detalhes"])
    finally:  # também numa interrupção: o que já foi baixado aparece em data/meta.json
        for (tipo, ano), contagem in detalhes.items():
            # arquivos fora da listagem desta execução entram só com as contagens de detalhe
            if str(ano) in estat["tipos"].get(tipo, {}) or any(contagem.values()):
                estat["tipos"].setdefault(tipo, {}).setdefault(str(ano), {}).update(contagem)
        totais = {
            chave: sum(c[f"detalhes_{chave}"] for c in detalhes.values())
            for chave in ("baixados", "falhas", "pendentes")
        }
        estat["detalhes"].update(totais)
    for (tipo, ano), contagem in detalhes.items():
        if any(contagem.values()):
            print(
                f"{tipo} {ano}: {contagem['detalhes_baixados']} detalhe(s) baixado(s), "
                f"{contagem['detalhes_falhas']} falha(s), {contagem['detalhes_pendentes']} pendente(s)",
                flush=True,
            )
    if totais["falhas"]:
        print(
            f"::warning::{totais['falhas']} página(s) de detalhe falharam; registros anteriores mantidos como pendentes",
            file=sys.stderr,
        )
    print(
        f"::notice::documentos: {totais['baixados']} detalhe(s) baixado(s), {totais['falhas']} falha(s); "
        f"{totais['pendentes']} documento(s) ainda aguardam a página de detalhe (limite de {limite} por execução)",
        flush=True,
    )
    return estat


def atualizar_meta(estat: dict, caminho: Path | None = None) -> dict:
    """Atualiza a chave "documentos" de data/meta.json, preservando as demais.

    Cada tipo/ano relistado substitui a entrada anterior; o que só teve detalhes nesta
    execução (sem "listado") atualiza as contagens de detalhe e mantém as da última
    listagem. Grava também os totais de detalhe da execução e, se for o caso,
    "listagem_interrompida" e "interrompido" (nome da exceção que parou a execução).
    """
    caminho = Path(caminho or META)
    dados = json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else {}
    anteriores = (dados.get("documentos") or {}).get("tipos") or {}
    por_tipo = {t: dict(anos) for t, anos in anteriores.items()}
    for tipo, anos in estat.get("tipos", {}).items():
        destino = por_tipo.setdefault(tipo, {})
        for ano, valor in anos.items():
            base = {} if "listado" in valor else destino.get(str(ano)) or {}
            destino[str(ano)] = {**base, **valor}
    dados["documentos"] = {
        "em": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "tipos": por_tipo,
        "detalhes": estat.get("detalhes") or {},
    }
    for chave in ("listagem_interrompida", "interrompido"):
        if estat.get(chave):
            dados["documentos"][chave] = estat[chave]
    salvar_json(caminho, dados)
    return dados


# ---------------------------------------------------------------------- execução
def arquivos_do_cache(pasta: Path, anos: list[int] | None = None, tipos: list[str] | None = None) -> None:
    """Preenche só "arquivos" a partir de <pasta>/<id>.html, sem rede.

    Vale para requerimentos, PDLs e resoluções e para indicações/moções de vários autores já
    com detalhe. Sem HTML no cache, o registro fica intocado (nenhuma chave nova); quem tem
    detalhe e continua sem "arquivos" volta à fila normal de detalhes (falta_arquivos).
    """
    for tipo, ano in arquivos_existentes():
        if (anos is not None and ano not in anos) or (tipos is not None and tipo not in tipos):
            continue
        caminho = caminho_ano(tipo, ano)
        registros = carregar_ano(caminho)
        for reg in registros.values():
            if not elegivel_detalhe(reg) or not (tipo in TIPOS_COM_DETALHE or tem_detalhe(reg)):
                continue
            try:
                preencher_arquivos_cache(reg, pasta)
            except ValueError as e:
                print(f"::warning::documento {reg['id']}: cache não aplicado ({e})", file=sys.stderr)
        salvar_ano(caminho, registros)


def intervalo_anos(texto: str) -> list[int]:
    """Converte "2025-2026" em [2025, 2026] e "2025" em [2025]."""
    ini, _, fim = texto.strip().partition("-")
    primeiro, ultimo = int(ini), int(fim or ini)
    if primeiro > ultimo:
        raise ValueError(f"intervalo de anos invertido: {texto!r}")
    return list(range(primeiro, ultimo + 1))


def _interromper(sinal: int, _quadro: object) -> None:
    """Trata o SIGTERM (enviado por `timeout` no CI) como Ctrl+C, para que os blocos
    finally gravem os detalhes já aplicados e data/meta.json antes de sair."""
    raise KeyboardInterrupt(f"sinal {sinal}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    hoje = dt.date.today().year
    ap.add_argument("--anos", default=None, help="ano ou intervalo inclusivo (padrão: anterior e atual)")
    ap.add_argument("--arquivos-do-cache", type=Path, metavar="DIR", help="preenche arquivos do HTML local, sem rede")
    ap.add_argument("--tipos", default=",".join(TIPOS), help="tipos separados por vírgula: " + ",".join(TIPOS))
    ap.add_argument("--workers", type=int, default=int(os.environ.get("COLETOR_WORKERS", 4)))
    ap.add_argument(
        "--max-detalhes", type=int, default=MAX_DETALHES,
        help=f"páginas de detalhe por execução, as mais recentes primeiro (padrão: {MAX_DETALHES})",
    )
    ap.add_argument("--sem-detalhe", action="store_true", help="só lista; não baixa páginas de detalhe")
    ap.add_argument(
        "--so-detalhes", action="store_true",
        help="não relista: só baixa os detalhes pendentes de todos os arquivos (ainda limitado por --max-detalhes)",
    )
    ap.add_argument(
        "--forcar", action="store_true",
        help="rebaixa o detalhe de todos os documentos elegíveis (ainda limitado por --max-detalhes)",
    )
    ap.add_argument(
        "--max-minutos", type=float, default=None,
        help="prazo interno: ao esgotar, para de listar e de pedir detalhes, grava e atualiza data/meta.json",
    )
    args = ap.parse_args()
    tipos = [t.strip() for t in args.tipos.split(",") if t.strip()]
    desconhecidos = [t for t in tipos if t not in TIPOS]
    if not tipos or desconhecidos:
        ap.error(f"tipos desconhecidos: {', '.join(desconhecidos) or '(nenhum)'}; use {','.join(TIPOS)}")
    if args.max_detalhes < 0:
        ap.error("--max-detalhes não pode ser negativo")
    if args.so_detalhes and (args.sem_detalhe or args.forcar):
        ap.error("--so-detalhes não combina com --sem-detalhe nem com --forcar (que dependem da listagem)")
    if args.max_minutos is not None and args.max_minutos <= 0:
        ap.error("--max-minutos precisa ser positivo")
    try:
        anos = intervalo_anos(args.anos or f"{hoje - 1}-{hoje}")
    except ValueError as e:
        ap.error(f"--anos inválido: {e}")
    if args.arquivos_do_cache:
        ignoradas = [nome for nome, ativa in (("--so-detalhes", args.so_detalhes), ("--sem-detalhe", args.sem_detalhe),
                                              ("--forcar", args.forcar), ("--max-minutos", args.max_minutos))
                     if ativa]
        if ignoradas:
            print(f"::warning::--arquivos-do-cache ignora {', '.join(ignoradas)}", file=sys.stderr)
        arquivos_do_cache(args.arquivos_do_cache, anos if args.anos is not None else None, tipos)
        return
    prazo = _agora() + 60 * args.max_minutos if args.max_minutos else None
    signal.signal(signal.SIGTERM, _interromper)
    estat: dict = {"tipos": {}}
    try:
        coletar(
            tipos, anos, args.workers, max_detalhes=args.max_detalhes, sem_detalhe=args.sem_detalhe,
            forcar=args.forcar, so_detalhes=args.so_detalhes, prazo=prazo, estat=estat,
        )
    except BaseException as e:
        estat["interrompido"] = type(e).__name__
        print(f"::warning::coleta de documentos interrompida ({type(e).__name__}); dados parciais gravados", file=sys.stderr)
        raise
    finally:  # data/meta.json reflete também uma execução interrompida
        atualizar_meta(estat)
    print(json.dumps(estat, ensure_ascii=False, default=str))
    resumos = [e for anos_tipo in estat["tipos"].values() for e in anos_tipo.values() if "listado" in e]
    if any(e["falhas"] for e in resumos) and not any(e["listado"] for e in resumos):
        sys.exit(1)
    if estat.get("listagem_interrompida") == "siscam_sem_resposta":
        sys.exit(1)
    if estat["detalhes"]["falhas"] and not estat["detalhes"]["baixados"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
