"""Testes do coletor das demais proposituras (coletor/documentos.py).

Usa as listagens e páginas de detalhe reais salvas em tests/fixtures/siscam/, lidas
como siscam.baixar as decodifica (bytes, sem traduzir quebras de linha); a rede é
sempre simulada.
Uso: python -m unittest tests.test_documentos  (ou pytest tests/test_documentos.py)
"""
from __future__ import annotations

import contextlib
import io
import itertools
import json
import re
import signal
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from coletor import arquivos, documentos, validar
from tests.apoio import SaidaQueSinaliza, ler_fixture
from tests.test_arquivos_siscam import ESPERADOS

TOTAIS = {"requerimento": 253, "indicacao": 400, "mocao": 400, "pdl": 315, "resolucao": 22}
VAZIA = "<html><body><table><tr><td>Nenhum registro encontrado.</td></tr></table></body></html>"


def fixture(tipo: str) -> str:
    """Listagem real do tipo (ano de 2025, faixa 1-400, página 1)."""
    return ler_fixture("siscam", f"listagem_tipo{documentos.TIPOS[tipo]}_2025.html")


def por_id(itens: list[dict], id_doc: int) -> dict:
    return next(i for i in itens if i["id"] == id_doc)


def resolucoes_com_total(total: int) -> str:
    """A listagem real de resoluções (10 registros) com outro total no cabeçalho."""
    return fixture("resolucao").replace("<strong>22 registro(s)</strong>", f"<strong>{total} registro(s)</strong>")


def sem_registros(tipo: str) -> str:
    """A listagem real do tipo sem os blocos de registro: só o filtro e os cabeçalhos de total."""
    html = fixture(tipo)
    inicio = html.rfind("<tr>", 0, html.index(documentos.BLOCO))
    return html[:inicio] + html[html.index('<tr id="trPaginacao">'):]


# o que o SISCAM devolve numa faixa sem documentos do tipo pedido: o cabeçalho de total de outro tipo
INDICACOES_SEM_REGISTROS = sem_registros("indicacao")
# registros do tipo pedido sob o cabeçalho de total de outro tipo: mudança de layout
RESOLUCOES_SOB_OUTRO_CABECALHO = fixture("resolucao").replace(
    "<h3 class='destaque'>Projeto de Resolução</h3>", "<h3 class='destaque'>Indicação</h3>"
)
SEM_FAIXA = 0  # NumeroInicial com que servidor() identifica a listagem do ano, sem faixa de número


def faixas(chamadas: list[str]) -> set[int]:
    """NumeroInicial das faixas pedidas, sem a listagem do ano."""
    return {int(parse_qs(urlsplit(u).query)["NumeroInicial"][0]) for u in chamadas if "NumeroInicial" in u}


def deslocar(html: str, numeros: int, ids: int) -> str:
    """A listagem de resoluções com o número e o id de cada registro somados de `numeros` e `ids`."""
    html = re.sub(r"IdDocumento=(\d+)", lambda m: f"IdDocumento={int(m.group(1)) + ids}", html)
    return re.sub(
        r"(Projeto de Resolução\s+N[º°o]\.?\s*)(\d+)(/\d{4})",
        lambda m: f"{m.group(1)}{int(m.group(2)) + numeros:05d}{m.group(3)}",
        html,
    )


def servidor(paginas: dict[tuple[int, int], object]):
    """Simula baixar(): responde por (NumeroInicial, pagina); exceções são levantadas.

    A listagem do ano, sem faixa de número, responde pela chave (SEM_FAIXA, 1).
    """
    chamadas: list[str] = []

    def baixar(url: str, tentativas: int = 5) -> str:
        chamadas.append(url)
        q = parse_qs(urlsplit(url).query)
        resposta = paginas.get((int(q.get("NumeroInicial", [SEM_FAIXA])[0]), int(q["pagina"][0])), VAZIA)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta

    return baixar, chamadas


def registro(id_doc: int, numero: int, ano: int = 2025, tipo: str = "resolucao") -> dict:
    return {
        "id": id_doc, "tipo": tipo, "numero": f"{numero}/{ano}", "ano": ano, "data": f"{ano}-01-02",
        "ementa": "REGISTRO ANTERIOR", "situacao": "PUBLICADO", "autores": [{"id": 1, "nome": "FULANO"}],
        "ultima_tramitacao": None, "n_tramitacoes": 0, "url": documentos.DETALHE.format(doc=id_doc),
    }


def detalhe_html(nome: str) -> str:
    """Página de detalhe real salva em tests/fixtures/siscam/detalhe_<nome>.html."""
    return ler_fixture("siscam", f"detalhe_{nome}.html")


def com_detalhe(tipo: str, id_doc: int, nome: str, em: str = "2026-10-22") -> dict:
    """Registro da listagem real com a página de detalhe real aplicada."""
    reg = por_id(documentos.parse_listagem(fixture(tipo), tipo), id_doc)
    return documentos.aplicar_detalhe(reg, documentos.ler_detalhe(detalhe_html(nome), reg), em)


RESOLUCOES = {r["id"]: r for r in documentos.parse_listagem(fixture("resolucao"), "resolucao")}
DETALHES_REAIS = {289947: detalhe_html("resolucao_289947")}
# a listagem real de resoluções com um passo a mais na tramitação de 22/2025 (id 289947)
UM_PASSO_A_MAIS = re.sub(r"(Última Tramitac[^(<]*\()4\)", r"\g<1>5)", resolucoes_com_total(10), count=1)


def pagina_minima(reg: dict, rotulo: str = "Projeto de Resolução") -> str:
    """Página de detalhe mínima, no layout do SISCAM, de um registro de listagem."""
    numero, ano = reg["numero"].split("/")
    autores = "".join(
        f"<tr><td>{a['nome']}</td><td>Vereador</td><td>{'Autor' if i == 0 else 'Co-Autor'}</td></tr>"
        for i, a in enumerate(reg["autores"])
    )
    passos = "".join(
        f"<tr><td><strong>Sequência: </strong>{seq}</td></tr><tr><td><strong>Objetivo: </strong>Leitura</td>"
        "<td><strong>Enviado em: </strong>01/02/2026 10:00</td></tr>"
        for seq in range(1, reg["n_tramitacoes"] + 1)
    )
    return (
        f'<table><tr><td colspan="2" class="form-task">{rotulo} Nº {int(numero):05d}/{ano}</td></tr>'
        f"<tr><td><strong>Protocolo: </strong>{reg['id']}/{ano}</td></tr></table>"
        f'<table id="autores_grdMembros">{autores}</table><tr id="trArquivos"><td>Nenhum Registro</td></tr>'
        f'<table id="tramitacoes_gvTramitacoes">{passos}</table>'
    )


def pagina_detalhe(id_doc: int) -> str:
    """Página de detalhe mínima de uma resolução da listagem real."""
    return pagina_minima(RESOLUCOES[id_doc])


def servidor_com_detalhes(listagens: dict[tuple[int, int], object], detalhes: dict[int, object] | None = None):
    """Como servidor(), mas responde também às páginas de detalhe, por IdDocumento.

    Sem resposta em detalhes, usa a página real (289947) ou a mínima de pagina_detalhe.
    Devolve (baixar, ids dos detalhes pedidos); as URLs de listagem pedidas ficam em
    baixar.listagens.
    """
    listar, listagens_pedidas = servidor(listagens)
    pedidos: list[int] = []

    def baixar(url: str, tentativas: int = 5) -> str:
        q = parse_qs(urlsplit(url).query)
        if "IdDocumento" not in q:
            return listar(url, tentativas)
        id_doc = int(q["IdDocumento"][0])
        pedidos.append(id_doc)
        resposta = (detalhes or {}).get(id_doc) or DETALHES_REAIS.get(id_doc) or pagina_detalhe(id_doc)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta

    baixar.listagens = listagens_pedidas
    return baixar, pedidos


def segurar_detalhes(livres: int, evento: threading.Event, ao_ultimo_livre=None):
    """Embrulho de baixar(): as `livres` primeiras páginas de detalhe respondem na hora; as
    seguintes esperam `evento` (no máximo 10 s), ocupando os workers.

    Assim, quando o código testado decide parar (e só então dispara o evento, por um aviso
    em stderr), nenhum worker está livre para começar outra página: as que ficaram na fila
    só não são pedidas se forem de fato canceladas. `ao_ultimo_livre` roda no pedido de
    número `livres`, antes da resposta.
    """
    contador = itertools.count(1)
    trava = threading.Lock()

    def embrulho(baixar):
        def segurado(url: str, tentativas: int = 5) -> str:
            if "IdDocumento" in url:
                with trava:
                    n = next(contador)
                if n == livres and ao_ultimo_livre:
                    ao_ultimo_livre()
                if n > livres:
                    evento.wait(10)
            return baixar(url, tentativas)

        return segurado

    return embrulho


# ------------------------------------------------------------------------ listagem
class TestParseListagem(unittest.TestCase):
    def test_dez_registros_e_total_por_tipo(self) -> None:
        for tipo, total in TOTAIS.items():
            with self.subTest(tipo=tipo):
                html = fixture(tipo)
                itens = documentos.parse_listagem(html, tipo)
                self.assertEqual(len(itens), 10)
                self.assertEqual(documentos.total_registros(html, tipo), total)
                self.assertTrue(all(i["tipo"] == tipo and i["ano"] == 2025 for i in itens))
                self.assertEqual(len({i["id"] for i in itens}), 10)
                for i in itens:
                    self.assertTrue(i["ementa"])
                    self.assertNotIn("\n", i["ementa"])
                    self.assertNotIn("<", i["ementa"])
                    self.assertTrue(i["autores"])
                    self.assertRegex(i["data"], r"^\d{4}-\d{2}-\d{2}$")

    def test_primeiro_requerimento(self) -> None:
        r = documentos.parse_listagem(fixture("requerimento"), "requerimento")[0]
        self.assertEqual(r["id"], 290506)
        self.assertEqual(r["numero"], "253/2025")
        self.assertEqual(r["data"], "2025-12-11")
        self.assertEqual(r["situacao"], "RECEBIDO PELA SMD")
        self.assertEqual(r["autores"], [{"id": 275, "nome": "Michel Salim Saad Neto"}])
        self.assertTrue(r["ementa"].startswith("REQUER INFORMAÇÕES SOBRE O PROCESSO ELETRÔNICO"))
        self.assertIsNone(r["ultima_tramitacao"])
        self.assertEqual(r["n_tramitacoes"], 0)
        self.assertEqual(r["url"], "https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento=290506")
        self.assertEqual(r["assunto"], "INFORMAÇÕES")
        self.assertEqual(
            set(r),
            {"id", "tipo", "numero", "ano", "data", "assunto", "ementa", "situacao", "autores", "ultima_tramitacao",
             "n_tramitacoes", "url"},
        )

    def test_assunto_da_listagem(self) -> None:
        primeiros = {tipo: documentos.parse_listagem(fixture(tipo), tipo)[0]["assunto"] for tipo in TOTAIS}
        self.assertEqual(
            primeiros,
            {"requerimento": "INFORMAÇÕES", "indicacao": "TAPA BURACO", "mocao": "APLAUSOS",
             "pdl": "DECRETO/MEDALHA", "resolucao": "CRIAÇÃO"},
        )
        self.assertEqual(por_id(documentos.parse_listagem(fixture("pdl"), "pdl"), 290379)["assunto"], "CIDADÃO NITEROIENSE")
        self.assertEqual(por_id(documentos.parse_listagem(fixture("indicacao"), "indicacao"), 276135)["assunto"], "BUEIRO")
        for tipo in TOTAIS:
            for i in documentos.parse_listagem(fixture(tipo), tipo):
                with self.subTest(tipo=tipo, id=i["id"]):
                    self.assertTrue(i["assunto"])
                    self.assertNotIn("<", i["assunto"])
                    self.assertNotEqual(i["assunto"], i["ementa"])

    def test_primeira_indicacao(self) -> None:
        r = documentos.parse_listagem(fixture("indicacao"), "indicacao")[0]
        self.assertEqual((r["id"], r["numero"], r["data"], r["situacao"]), (276138, "400/2025", "2025-02-24", "Arquivado"))
        self.assertEqual(r["autores"], [{"id": 237, "nome": "ROBSON GUIMARÃES JOSÉ FILHO"}])
        self.assertIn("Piratininga – Niterói", r["ementa"])
        self.assertEqual(r["n_tramitacoes"], 4)
        self.assertEqual(
            r["ultima_tramitacao"],
            {"seq": 4, "objetivo": "Arquivar", "enviado": "2025-06-27", "resultado": "Arquivado através do MEMO Nº",
             "data_resposta": "2025-07-01", "observacao": "67/2025"},
        )

    def test_primeira_mocao(self) -> None:
        r = documentos.parse_listagem(fixture("mocao"), "mocao")[0]
        self.assertEqual((r["id"], r["numero"]), (279272, "400/2025"))
        self.assertTrue(r["ementa"].startswith("Moção de Congratulações e Aplausos"))
        self.assertEqual(r["autores"], [{"id": 285, "nome": "ANTONIO CARLOS MORETT SILVA JUNIOR"}])

    def test_primeiro_pdl(self) -> None:
        r = documentos.parse_listagem(fixture("pdl"), "pdl")[0]
        self.assertEqual((r["id"], r["numero"], r["data"]), (290514, "315/2025", "2025-12-15"))
        self.assertEqual(r["situacao"], "ENCAMINHADO ÀS COMISSÕES")
        self.assertEqual(r["n_tramitacoes"], 3)
        passo = r["ultima_tramitacao"]
        self.assertEqual((passo["seq"], passo["objetivo"], passo["enviado"]), (3, "Juntada", "2026-04-01"))
        self.assertEqual((passo["resultado"], passo["data_resposta"]), ("", None))

    def test_primeira_resolucao(self) -> None:
        r = documentos.parse_listagem(fixture("resolucao"), "resolucao")[0]
        self.assertEqual((r["id"], r["numero"], r["data"]), (289947, "22/2025", "2025-12-04"))
        self.assertEqual(r["situacao"], "PUBLICADO")

    def test_pdl_com_dois_autores_na_ordem_da_listagem(self) -> None:
        r = por_id(documentos.parse_listagem(fixture("pdl"), "pdl"), 290379)
        self.assertEqual(r["numero"], "309/2025")
        self.assertEqual(
            r["autores"],
            [{"id": 272, "nome": "ALLAN PINHO LYRA"}, {"id": 9, "nome": "MILTON CARLOS DA SILVA LOPES"}],
        )
        for autor in r["autores"]:  # a listagem não marca autor principal nem coautor
            self.assertEqual(set(autor), {"id", "nome"})

    def test_autor_mesa_diretora(self) -> None:
        r = por_id(documentos.parse_listagem(fixture("resolucao"), "resolucao"), 288836)
        self.assertEqual(r["autores"], [{"id": 278, "nome": "Mesa Diretora 2025/2026"}])

    def test_requerimento_respondido_com_ultimo_passo(self) -> None:
        r = por_id(documentos.parse_listagem(fixture("requerimento"), "requerimento"), 290504)
        self.assertEqual((r["numero"], r["situacao"], r["n_tramitacoes"]), ("251/2025", "RESPONDIDO", 5))
        self.assertEqual(
            r["ultima_tramitacao"],
            {"seq": 5, "objetivo": "Respondido", "enviado": "2026-10-20",
             "resultado": "Ofício Lido na Sessão Plenária do dia", "data_resposta": "2026-10-21", "observacao": ""},
        )

    def test_sem_tramitacao_fica_nulo(self) -> None:
        itens = documentos.parse_listagem(fixture("requerimento"), "requerimento")
        sem = {i["id"] for i in itens if i["ultima_tramitacao"] is None}
        self.assertEqual(sem, {290506, 290503, 290502, 290412})
        for i in itens:
            self.assertEqual(i["n_tramitacoes"] == 0, i["id"] in sem)

    def test_passo_sem_resultado(self) -> None:
        r = por_id(documentos.parse_listagem(fixture("requerimento"), "requerimento"), 290038)
        passo = r["ultima_tramitacao"]
        self.assertEqual((passo["objetivo"], passo["enviado"]), ("Prorrogação de prazo", "2026-02-25"))
        self.assertEqual((passo["resultado"], passo["data_resposta"], passo["observacao"]), ("", None, ""))

    def test_cabecalho_de_total_de_outro_tipo_falha(self) -> None:
        with self.assertRaises(ValueError):
            documentos.total_registros(fixture("requerimento"), "indicacao")

    def test_registro_de_outro_tipo_falha(self) -> None:
        with self.assertRaises(ValueError):
            documentos.parse_listagem(fixture("requerimento"), "indicacao")

    def test_pagina_sem_resultado(self) -> None:
        self.assertEqual(documentos.total_registros(VAZIA, "mocao"), 0)
        self.assertEqual(documentos.parse_listagem(VAZIA, "mocao"), [])


# -------------------------------------------------------------------------- faixas
class TestListarFaixa(unittest.TestCase):
    def test_url_da_listagem(self) -> None:
        self.assertEqual(
            documentos.url_listagem("resolucao", 2025, 1, 400, 1),
            "https://consultaniteroi.siscam.com.br/ResultadoPropositura.aspx?Tipo=7&Exibir=1,2,3,4,6,7,8"
            "&Ano=2025&pagina=1&NumeroInicial=1&NumeroFinal=400",
        )
        self.assertEqual(
            documentos.url_ano("resolucao", 2025),
            "https://consultaniteroi.siscam.com.br/ResultadoPropositura.aspx?Tipo=7&Exibir=1,2,3,4,6,7,8"
            "&Ano=2025&pagina=1",
        )

    def test_pagina_unica(self) -> None:
        falso, chamadas = servidor({(1, 1): resolucoes_com_total(10)})
        with mock.patch.object(documentos, "baixar", side_effect=falso):
            itens, total = documentos.listar_faixa("resolucao", 2025, 1, 400, 2)
        self.assertEqual((len(itens), total), (10, 10))
        self.assertEqual(chamadas, [documentos.url_listagem("resolucao", 2025, 1, 400, 1)])

    def test_baixa_todas_as_paginas_da_faixa(self) -> None:
        falso, chamadas = servidor({(1, p): fixture("resolucao") for p in (1, 2, 3)})
        with mock.patch.object(documentos, "baixar", side_effect=falso):
            itens, total = documentos.listar_faixa("resolucao", 2025, 1, 400, 2)
        self.assertEqual(total, 22)
        self.assertEqual(len(itens), 30)  # a mesma página três vezes; a deduplicação é no ano
        paginas = sorted(int(parse_qs(urlsplit(u).query)["pagina"][0]) for u in chamadas)
        self.assertEqual(paginas, [1, 2, 3])

    def test_registros_sem_total_indicam_mudanca_de_layout(self) -> None:
        html = fixture("indicacao").replace("<h3 class='destaque'>Indicação</h3>", "<h3>Indicação</h3>")
        self.assertEqual(documentos.total_registros(html, "indicacao"), 0)
        falso, _ = servidor({(1, 1): html})
        with mock.patch.object(documentos, "baixar", side_effect=falso):
            with self.assertRaises(ValueError):
                documentos.listar_faixa("indicacao", 2025, 1, 400, 2)

    def test_total_sem_registros_reconhecidos_falha(self) -> None:
        html = VAZIA + "<h3 class='destaque'>Moção</h3> (<span class='total-item'><strong>5 registro(s)</strong>"
        falso, _ = servidor({(1, 1): html})
        with mock.patch.object(documentos, "baixar", side_effect=falso):
            with self.assertRaises(ValueError):
                documentos.listar_faixa("mocao", 2025, 1, 400, 2)

    def test_faixa_sem_documentos_do_tipo_com_cabecalho_de_outro_e_vazia(self) -> None:
        self.assertNotIn(documentos.BLOCO, INDICACOES_SEM_REGISTROS)
        self.assertIn("<h3 class='destaque'>Indicação</h3>", INDICACOES_SEM_REGISTROS)
        for pagina in (INDICACOES_SEM_REGISTROS, fixture("indicacao")):  # sem registros ou só com os do outro tipo
            with self.subTest(com_registros=documentos.BLOCO in pagina):
                self.assertTrue(documentos.pagina_de_outro_tipo(pagina, "requerimento"))
                falso, chamadas = servidor({(401, 1): pagina})
                with mock.patch.object(documentos, "baixar", side_effect=falso):
                    self.assertEqual(documentos.listar_faixa("requerimento", 2026, 401, 800, 2), ([], 0))
                self.assertEqual(len(chamadas), 1)

    def test_registros_do_tipo_sob_cabecalho_de_outro_falham(self) -> None:
        self.assertFalse(documentos.pagina_de_outro_tipo(RESOLUCOES_SOB_OUTRO_CABECALHO, "resolucao"))
        falso, _ = servidor({(1, 1): RESOLUCOES_SOB_OUTRO_CABECALHO})
        with mock.patch.object(documentos, "baixar", side_effect=falso):
            with self.assertRaisesRegex(ValueError, "cabeçalho de total inesperado"):
                documentos.listar_faixa("resolucao", 2025, 1, 400, 2)

    def test_so_cabecalhos_conhecidos_indicam_faixa_sem_documentos(self) -> None:
        cabecalho = "<h3 class='destaque'>Indicação</h3>"
        self.assertIn(cabecalho, INDICACOES_SEM_REGISTROS)
        projeto_de_lei = INDICACOES_SEM_REGISTROS.replace(cabecalho, "<h3 class='destaque'>Projeto de Lei</h3>")
        self.assertTrue(documentos.pagina_de_outro_tipo(projeto_de_lei, "requerimento"))
        desconhecido = INDICACOES_SEM_REGISTROS.replace(cabecalho, "<h3 class='destaque'>Documento Avulso</h3>")
        self.assertFalse(documentos.pagina_de_outro_tipo(desconhecido, "requerimento"))
        falso, _ = servidor({(401, 1): desconhecido})
        with mock.patch.object(documentos, "baixar", side_effect=falso):
            with self.assertRaisesRegex(ValueError, "cabeçalho de total inesperado"):
                documentos.listar_faixa("requerimento", 2026, 401, 800, 2)

    def test_registros_sem_rotulo_sob_cabecalho_de_outro_falham(self) -> None:
        html, trocas = re.subn(r'(IdDocumento=\d+"[^>]*>\s*)Indicação', r"\1Documento", fixture("indicacao"))
        self.assertEqual(trocas, 10)
        self.assertFalse(documentos.pagina_de_outro_tipo(html, "requerimento"))
        falso, _ = servidor({(401, 1): html})
        with mock.patch.object(documentos, "baixar", side_effect=falso):
            with self.assertRaises(ValueError):
                documentos.listar_faixa("requerimento", 2026, 401, 800, 2)

    def test_total_do_ano(self) -> None:
        casos = (
            (resolucoes_com_total(37), 37, ""),
            (INDICACOES_SEM_REGISTROS, 0, ""),  # nenhum documento do tipo no ano
            (VAZIA, 0, ""),
            (RuntimeError("falha ao baixar"), None, "total do ano indisponível"),
            (RESOLUCOES_SOB_OUTRO_CABECALHO, None, "cabeçalho de total inesperado"),
        )
        for pagina, esperado, aviso in casos:
            with self.subTest(esperado=esperado, aviso=aviso):
                falso, chamadas = servidor({(SEM_FAIXA, 1): pagina})
                erros = io.StringIO()
                with mock.patch.object(documentos, "baixar", side_effect=falso), contextlib.redirect_stderr(erros):
                    self.assertEqual(documentos.total_do_ano("resolucao", 2025), esperado)
                self.assertEqual(chamadas, [documentos.url_ano("resolucao", 2025)])
                if aviso:
                    self.assertIn("::warning::", erros.getvalue())
                    self.assertIn(aviso, erros.getvalue())
                else:
                    self.assertEqual(erros.getvalue(), "")


# ------------------------------------------------------------------------ gravação
class TestColetarAno(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.pasta = Path(self._temp.name)
        self.arquivo = documentos.caminho_ano("resolucao", 2025, self.pasta)

    def tearDown(self) -> None:
        self._temp.cleanup()

    def anteriores(self, *registros: dict) -> None:
        documentos.salvar_ano(self.arquivo, {r["id"]: r for r in registros})

    def coletar(self, paginas: dict[tuple[int, int], object]) -> tuple[dict, str, list[str]]:
        falso, chamadas = servidor(paginas)
        erros = io.StringIO()
        with mock.patch.object(documentos, "baixar", side_effect=falso), contextlib.redirect_stderr(erros):
            estat = documentos.coletar_ano("resolucao", 2025, 2, self.pasta)
        return estat, erros.getvalue(), chamadas

    def lidos(self) -> list[dict]:
        return json.loads(self.arquivo.read_text(encoding="utf-8"))

    def test_lista_completa_grava_ordenado_um_por_linha(self) -> None:
        estat, erros, _ = self.coletar({(1, 1): resolucoes_com_total(10)})
        lidos = self.lidos()
        self.assertEqual([r["numero"] for r in lidos], [f"{n}/2025" for n in range(13, 23)])
        self.assertEqual(self.arquivo.read_text(encoding="utf-8"), arquivos.texto_lista(lidos))
        self.assertEqual(len(self.arquivo.read_text(encoding="utf-8").splitlines()), 12)
        self.assertEqual((estat["esperado"], estat["listado"], estat["falhas"], estat["gravado"]), (10, 10, 0, True))
        self.assertNotIn("::warning::", erros)

    def test_relistar_substitui_o_ano(self) -> None:
        self.anteriores(registro(1, 5))
        estat, _, _ = self.coletar({(1, 1): resolucoes_com_total(10)})
        self.assertNotIn(1, {r["id"] for r in self.lidos()})
        self.assertEqual((estat["registros"], estat["preservados"]), (10, 0))

    def test_falha_numa_faixa_mantem_os_anteriores_dela(self) -> None:
        self.anteriores(registro(1, 5), registro(2, 450))
        estat, erros, _ = self.coletar({(1, 1): resolucoes_com_total(10), (401, 1): RuntimeError("falha ao baixar")})
        ids = {r["id"] for r in self.lidos()}
        self.assertIn(2, ids)  # faixa 401-800 falhou: registro anterior mantido
        self.assertNotIn(1, ids)  # faixa 1-400 relistada por completo
        self.assertEqual(len(ids), 11)
        self.assertEqual((estat["falhas"], estat["preservados"]), (1, 1))
        self.assertIn("::warning::", erros)

    def test_falha_total_mantem_o_arquivo(self) -> None:
        self.anteriores(registro(1, 5), registro(2, 450))
        antes = self.arquivo.read_bytes()
        estat, erros, _ = self.coletar({(1, 1): RuntimeError("falha ao baixar")})
        self.assertEqual(self.arquivo.read_bytes(), antes)
        self.assertEqual(estat["listado"], 0)
        self.assertGreaterEqual(estat["falhas"], 1)
        self.assertEqual(estat["registros"], 2)
        self.assertIn("::warning::", erros)

    def test_mudanca_de_layout_mantem_o_arquivo(self) -> None:
        self.anteriores(registro(1, 5))
        antes = self.arquivo.read_bytes()
        html = fixture("resolucao").replace("<h3 class='destaque'>Projeto de Resolução</h3>", "<h3>Projeto de Resolução</h3>")
        estat, erros, _ = self.coletar({(1, 1): html})
        self.assertEqual(self.arquivo.read_bytes(), antes)
        self.assertEqual(estat["falhas"], 1)
        self.assertIn("layout", erros)

    def test_falha_sem_anteriores_nao_cria_arquivo(self) -> None:
        estat, _, _ = self.coletar({(1, 1): RuntimeError("falha ao baixar")})
        self.assertFalse(self.arquivo.exists())
        self.assertFalse(estat["gravado"])

    def test_listagem_incompleta_avisa_e_preserva(self) -> None:
        self.anteriores(registro(3, 3))
        estat, erros, _ = self.coletar({(1, 1): fixture("resolucao")})  # 22 esperados, páginas 2 e 3 vazias
        self.assertIn("listou 10 de 22", erros)
        self.assertIn(3, {r["id"] for r in self.lidos()})
        self.assertEqual((estat["esperado"], estat["listado"], estat["preservados"]), (22, 10, 1))

    def test_faixa_vazia_onde_havia_registros_preserva(self) -> None:
        self.anteriores(registro(2, 450))
        estat, erros, chamadas = self.coletar({(1, 1): resolucoes_com_total(10)})
        self.assertIn(2, {r["id"] for r in self.lidos()})
        self.assertEqual(estat["falhas"], 1)
        self.assertIn("::warning::", erros)
        self.assertEqual(faixas(chamadas), {1, 401})  # para depois da faixa do maior número anterior

    def test_lista_sem_baixar_detalhe_e_marca_pendentes(self) -> None:
        _, _, chamadas = self.coletar({(1, 1): resolucoes_com_total(10)})
        self.assertFalse(any("IdDocumento" in u for u in chamadas))
        self.assertTrue(all(r["detalhe_pendente"] for r in self.lidos()))

    def test_registro_preservado_fica_como_estava(self) -> None:
        self.anteriores(registro(2, 450))
        antes = self.lidos()[0]
        self.coletar({(1, 1): resolucoes_com_total(10), (401, 1): RuntimeError("falha ao baixar")})
        self.assertEqual(next(r for r in self.lidos() if r["id"] == 2), antes)

    def test_faixa_vazia_com_cabecalho_de_outro_tipo_encerra_sem_falha(self) -> None:
        estat, erros, chamadas = self.coletar({(1, 1): resolucoes_com_total(10), (401, 1): INDICACOES_SEM_REGISTROS})
        self.assertEqual((estat["esperado"], estat["listado"], estat["falhas"], estat["gravado"]), (10, 10, 0, True))
        self.assertEqual(len(self.lidos()), 10)
        self.assertNotIn("::warning::", erros)
        self.assertEqual(faixas(chamadas), {1, 401})  # a faixa vazia é o fim da numeração

    def test_registros_sob_cabecalho_de_outro_tipo_contam_como_falha(self) -> None:
        self.anteriores(registro(1, 5))
        antes = self.arquivo.read_bytes()
        estat, erros, _ = self.coletar({(1, 1): RESOLUCOES_SOB_OUTRO_CABECALHO})
        self.assertEqual(self.arquivo.read_bytes(), antes)
        self.assertEqual((estat["listado"], estat["falhas"], estat["preservados"]), (0, 1, 1))
        self.assertIn("cabeçalho de total inesperado", erros)

    def test_total_do_ano_encerra_sem_pedir_a_faixa_seguinte(self) -> None:
        estat, erros, chamadas = self.coletar({
            (SEM_FAIXA, 1): resolucoes_com_total(10),
            (1, 1): resolucoes_com_total(10),
            (401, 1): RuntimeError("faixa que não deveria ser pedida"),
        })
        self.assertEqual(chamadas[0], documentos.url_ano("resolucao", 2025))
        self.assertEqual(faixas(chamadas), {1})
        self.assertEqual(
            (estat["total_ano"], estat["esperado"], estat["listado"], estat["falhas"], estat["gravado"]),
            (10, 10, 10, 0, True),
        )
        self.assertNotIn("::warning::", erros)

    def test_total_do_ano_nao_dispensa_a_faixa_de_registros_anteriores(self) -> None:
        self.anteriores(registro(2, 450))
        estat, erros, chamadas = self.coletar({
            (SEM_FAIXA, 1): resolucoes_com_total(10),
            (1, 1): resolucoes_com_total(10),
            (401, 1): INDICACOES_SEM_REGISTROS,
        })
        self.assertEqual(faixas(chamadas), {1, 401})
        self.assertIn(2, {r["id"] for r in self.lidos()})  # sumiu da listagem: o anterior fica, com aviso
        self.assertEqual((estat["falhas"], estat["preservados"]), (1, 1))
        self.assertIn("havia registros até o nº 450", erros)

    def test_faixas_aquem_do_total_do_ano_contam_como_falha(self) -> None:
        estat, erros, chamadas = self.coletar({
            (SEM_FAIXA, 1): resolucoes_com_total(30), (1, 1): resolucoes_com_total(10),
        })
        self.assertEqual(faixas(chamadas), {1, 401})
        self.assertEqual((estat["total_ano"], estat["esperado"], estat["falhas"], estat["gravado"]), (30, 10, 1, True))
        self.assertIn("as faixas somam 10 registros, mas o total do ano é 30", erros)

    def test_faixas_alem_do_total_do_ano_so_avisam(self) -> None:
        estat, erros, _ = self.coletar({(SEM_FAIXA, 1): resolucoes_com_total(5), (1, 1): resolucoes_com_total(10)})
        self.assertEqual((estat["total_ano"], estat["esperado"], estat["falhas"], estat["gravado"]), (5, 10, 0, True))
        self.assertIn("as faixas somam 10 registros, mas o total do ano é 5", erros)

    def test_ano_com_total_e_sem_registros_nao_grava_arquivo_vazio(self) -> None:
        estat, erros, _ = self.coletar({
            (SEM_FAIXA, 1): resolucoes_com_total(10), (1, 1): INDICACOES_SEM_REGISTROS,
        })
        self.assertFalse(self.arquivo.exists())
        self.assertFalse(estat["gravado"])
        self.assertEqual((estat["total_ano"], estat["listado"], estat["falhas"]), (10, 0, 1))
        self.assertIn("arquivo não gravado", erros)

    def test_faixa_com_menos_registros_que_antes_preserva_os_que_sumiram(self) -> None:
        self.anteriores(*RESOLUCOES.values(), registro(1, 5))  # 11 registros na faixa 1-400
        estat, erros, _ = self.coletar({(1, 1): resolucoes_com_total(10)})
        self.assertEqual({r["id"] for r in self.lidos()}, set(RESOLUCOES) | {1})
        self.assertEqual((estat["listado"], estat["preservados"], estat["registros"], estat["falhas"]), (10, 1, 11, 0))
        self.assertIn("10 registros listados, menos que os 11 anteriores", erros)

    def test_falha_numa_faixa_do_meio_segue_para_as_seguintes(self) -> None:
        self.anteriores(registro(1, 5), registro(2, 450), registro(3, 850))
        estat, erros, chamadas = self.coletar({
            (1, 1): resolucoes_com_total(10),
            (401, 1): RuntimeError("falha ao baixar"),
            (801, 1): deslocar(resolucoes_com_total(10), 800, 10**6),
        })
        self.assertEqual(faixas(chamadas), {1, 401, 801, 1201})  # a 1201 vazia encerra a numeração
        lidos = {r["id"]: r for r in self.lidos()}
        self.assertIn(2, lidos)  # faixa 401-800 falhou: o anterior fica
        self.assertNotIn(1, lidos)  # faixas 1-400 e 801-1200 relistadas por completo
        self.assertNotIn(3, lidos)
        self.assertEqual(
            sorted(documentos.numero_int(r) for i, r in lidos.items() if i != 2),
            [*range(13, 23), *range(813, 823)],
        )
        self.assertEqual(
            (estat["esperado"], estat["listado"], estat["preservados"], estat["falhas"], estat["sem_resposta"]),
            (20, 20, 1, 1, False),
        )
        self.assertIn("faixa 401-800: falha na listagem", erros)

    def test_falhas_seguidas_de_faixa_encerram_o_ano_e_preservam_o_resto(self) -> None:
        self.anteriores(*(registro(i + 1, 400 * i + 5) for i in range(6)))  # um por faixa, até o nº 2005
        antes = self.arquivo.read_bytes()
        estat, erros, chamadas = self.coletar({(400 * i + 1, 1): RuntimeError("falha ao baixar") for i in range(6)})
        maximo = documentos.FALHAS_FAIXA_MAX
        self.assertEqual(faixas(chamadas), {400 * i + 1 for i in range(maximo)})
        self.assertEqual(self.arquivo.read_bytes(), antes)  # todos os anteriores mantidos, inclusive os não pedidos
        self.assertEqual((estat["listado"], estat["preservados"], estat["registros"]), (0, 6, 6))
        self.assertEqual(estat["falhas"], maximo + 1)
        self.assertTrue(estat["sem_resposta"])
        self.assertIn(f"listagem interrompida após {maximo} falhas seguidas", erros)
        self.assertIn(f"registros anteriores de {400 * maximo + 1} a 2005 mantidos", erros)

    def test_sem_total_do_ano_segue_pelas_faixas(self) -> None:
        estat, erros, chamadas = self.coletar({
            (SEM_FAIXA, 1): RuntimeError("falha ao baixar"), (1, 1): resolucoes_com_total(10),
        })
        self.assertEqual(faixas(chamadas), {1, 401})
        self.assertEqual((estat["total_ano"], estat["listado"], estat["falhas"], estat["gravado"]), (None, 10, 0, True))
        self.assertIn("total do ano indisponível", erros)


# ------------------------------------------------------------------------- detalhe
TRAMITACAO_PL = {"seq", "remetente", "destinatario", "objetivo", "enviado", "complemento", "resultado",
                 "data_resposta", "observacao"}


class TestDetalhe(unittest.TestCase):
    def test_requerimento_respondido(self) -> None:
        listado = por_id(documentos.parse_listagem(fixture("requerimento"), "requerimento"), 290504)
        r = com_detalhe("requerimento", 290504, "requerimento_290504")
        self.assertEqual(
            r["autoria"], [{"id": 275, "nome": "Michel Salim Saad Neto", "origem": "Vereador", "papel": "Autor"}]
        )
        self.assertEqual(r["autores"], listado["autores"])  # a autoria da listagem fica como está
        self.assertEqual([t["seq"] for t in r["tramitacoes"]], [1, 2, 3, 4, 5])
        self.assertTrue(all(set(t) == TRAMITACAO_PL for t in r["tramitacoes"]))
        self.assertEqual(r["tramitacoes"][3]["objetivo"], "Prorrogação de prazo")
        self.assertEqual((r["tramitacoes"][4]["objetivo"], r["tramitacoes"][4]["enviado"]), ("Respondido", "2026-10-20"))
        self.assertEqual((r["processo"], r["protocolo"], r["data_protocolo"]), ("", "14625/2025", "2025-12-11"))
        self.assertEqual(r["detalhe_em"], "2026-10-22")
        # "enviado" do passo "Respondido"; a "Data Resposta" bruta (21/10) fica intocada
        self.assertEqual((r["respondido_em"], r["dias_ate_resposta"]), ("2026-10-20", 313))
        self.assertEqual(r["ultima_tramitacao"], listado["ultima_tramitacao"])
        self.assertEqual(r["ultima_tramitacao"]["data_resposta"], "2026-10-21")
        for chave in ("detalhe_pendente", "publicacao", "lei", "desfecho"):
            self.assertNotIn(chave, r)

    def test_requerimento_sem_resposta(self) -> None:
        r = com_detalhe("requerimento", 290505, "requerimento_290505")
        self.assertEqual([t["seq"] for t in r["tramitacoes"]], [1, 2, 3, 4])
        self.assertEqual(r["tramitacoes"][3]["objetivo"], "Prorrogação de prazo")
        self.assertEqual((r["protocolo"], r["data_protocolo"]), ("14626/2025", "2025-12-11"))
        self.assertIsNone(r["respondido_em"])
        self.assertIsNone(r["dias_ate_resposta"])

    def test_pdl_com_autor_e_coautor(self) -> None:
        r = com_detalhe("pdl", 290379, "pdl_290379")
        self.assertEqual(
            r["autoria"],
            [{"id": 272, "nome": "ALLAN PINHO LYRA", "origem": "Vereador", "papel": "Autor"},
             {"id": 9, "nome": "MILTON CARLOS DA SILVA LOPES", "origem": "Vereador", "papel": "Co-Autor"}],
        )
        self.assertEqual(len(r["tramitacoes"]), 5)
        self.assertEqual((r["processo"], r["protocolo"], r["data_protocolo"]), ("848/2025", "14500/2025", "2025-12-10"))
        publicado = r["tramitacoes"][2]
        self.assertEqual((publicado["resultado"], publicado["data_resposta"]), ("Publicado", "2025-12-12"))
        self.assertEqual(r["tramitacoes"][-1]["objetivo"], "Arquivar")  # a publicação não é o último passo
        self.assertEqual(r["publicacao"], {"numero": 3993, "data": "2025-12-12"})
        self.assertNotIn("respondido_em", r)

    def test_resolucao_publicada(self) -> None:
        r = com_detalhe("resolucao", 289947, "resolucao_289947")
        self.assertEqual(
            r["autoria"],
            [{"id": 237, "nome": "ROBSON GUIMARÃES JOSÉ FILHO", "origem": "Vereador", "papel": "Autor"}],
        )
        self.assertEqual([t["seq"] for t in r["tramitacoes"]], [1, 2, 3, 4])
        self.assertEqual(r["tramitacoes"][-1]["observacao"], r["ultima_tramitacao"]["observacao"])
        self.assertIn("3167/2025", r["tramitacoes"][-1]["observacao"])
        self.assertEqual((r["processo"], r["protocolo"], r["data_protocolo"]), ("820/2025", "14078/2025", "2025-12-04"))
        self.assertEqual(r["publicacao"], {"numero": 3167, "data": "2026-02-27"})

    def test_pagina_de_outro_documento_ou_de_erro_falha(self) -> None:
        reg = por_id(documentos.parse_listagem(fixture("requerimento"), "requerimento"), 290505)
        with self.assertRaises(ValueError):
            documentos.ler_detalhe(detalhe_html("requerimento_290504"), reg)
        with self.assertRaises(ValueError):
            documentos.ler_detalhe("<html><body>Erro no servidor</body></html>", reg)

    def test_detalhe_sem_tramitacao_falha(self) -> None:
        reg = por_id(documentos.parse_listagem(fixture("requerimento"), "requerimento"), 290504)
        html = detalhe_html("requerimento_290504").replace('id="tramitacoes_gvTramitacoes"', 'id="outra_grade"')
        with self.assertRaises(ValueError):
            documentos.ler_detalhe(html, reg)


class TestPrecisaDetalhe(unittest.TestCase):
    def test_elegiveis(self) -> None:
        um = [{"id": 1, "nome": "A"}]
        dois = [{"id": 1, "nome": "A"}, {"id": 2, "nome": "B"}]
        casos = (
            ("requerimento", um, True), ("pdl", um, True), ("resolucao", um, True), ("indicacao", um, False),
            ("mocao", um, False), ("indicacao", dois, True), ("mocao", dois, True),
        )
        for tipo, autores, esperado in casos:
            with self.subTest(tipo=tipo, autores=len(autores)):
                self.assertEqual(documentos.elegivel_detalhe({"tipo": tipo, "autores": autores}), esperado)

    def test_quando_baixar(self) -> None:
        novo = {**registro(9, 1), "n_tramitacoes": 3}
        baixado = {**novo, "detalhe_em": "2026-10-01", "tramitacoes": [], "arquivos": []}
        self.assertTrue(documentos.precisa_detalhe(novo, None))
        self.assertTrue(documentos.precisa_detalhe(novo, dict(novo)))  # anterior sem detalhe
        self.assertFalse(documentos.precisa_detalhe(novo, baixado))
        self.assertTrue(documentos.precisa_detalhe({**novo, "n_tramitacoes": 4}, baixado))
        coautor = {**novo, "autores": [{"id": 1, "nome": "FULANO"}, {"id": 2, "nome": "BELTRANO"}]}
        self.assertTrue(documentos.precisa_detalhe(coautor, baixado))  # autores listados mudaram
        self.assertTrue(documentos.precisa_detalhe(novo, {**baixado, "detalhe_pendente": True}))
        self.assertTrue(documentos.precisa_detalhe(novo, baixado, forcar=True))
        self.assertFalse(documentos.precisa_detalhe({**novo, "tipo": "indicacao"}, None, forcar=True))

    def test_situacao_ou_ultimo_passo_diferentes_rebaixam(self) -> None:
        passo = {"seq": 3, "objetivo": "Despachar", "enviado": "2026-03-01", "resultado": "", "data_resposta": None,
                 "observacao": ""}
        novo = {**registro(9, 1), "n_tramitacoes": 3, "ultima_tramitacao": passo}
        baixado = {**novo, "detalhe_em": "2026-10-01", "tramitacoes": [], "arquivos": []}
        self.assertFalse(documentos.precisa_detalhe(dict(novo), baixado))
        self.assertTrue(documentos.precisa_detalhe({**novo, "situacao": "ARQUIVADO"}, baixado))
        editado = {**passo, "resultado": "Respondido"}  # mesmo passo, mesma contagem, outro resultado
        self.assertTrue(documentos.precisa_detalhe({**novo, "ultima_tramitacao": editado}, baixado))
        self.assertTrue(documentos.precisa_detalhe({**novo, "ultima_tramitacao": None}, baixado))

    def test_indicacoes_de_um_autor_ficam_so_com_a_listagem(self) -> None:
        itens = {r["id"]: r for r in documentos.parse_listagem(fixture("indicacao"), "indicacao")}
        um_autor = {i for i, r in itens.items() if len(r["autores"]) == 1}
        self.assertTrue(um_autor)
        self.assertEqual(documentos.marcar_detalhes(itens, {}), len(itens) - len(um_autor))
        self.assertFalse(any("detalhe_pendente" in itens[i] for i in um_autor))


class TestColetaComDetalhes(unittest.TestCase):
    LISTAGEM = {(1, 1): resolucoes_com_total(10)}

    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.pasta = Path(self._temp.name)
        self.arquivo = documentos.caminho_ano("resolucao", 2025, self.pasta)

    def tearDown(self) -> None:
        self._temp.cleanup()

    def coletar(
        self, listagens: dict | None = None, detalhes: dict | None = None, hoje: str = "2026-10-22",
        erros: io.StringIO | None = None, embrulho=None, **opcoes,
    ) -> tuple[dict, list[int]]:
        """Roda documentos.coletar com a rede simulada; `embrulho` modifica o baixar() falso."""
        falso, pedidos = servidor_com_detalhes(listagens or self.LISTAGEM, detalhes)
        self.listagens, self.pedidos = falso.listagens, pedidos  # visíveis mesmo se coletar levantar
        saida, erros = io.StringIO(), erros if erros is not None else io.StringIO()
        with mock.patch.object(documentos, "baixar", side_effect=embrulho(falso) if embrulho else falso), \
                contextlib.redirect_stdout(saida), contextlib.redirect_stderr(erros):
            estat = documentos.coletar(["resolucao"], [2025], 2, self.pasta, hoje=hoje, **opcoes)
        self.saida, self.erros = saida.getvalue(), erros.getvalue()
        return estat, sorted(pedidos)

    def lidos(self) -> dict[int, dict]:
        return {r["id"]: r for r in json.loads(self.arquivo.read_text(encoding="utf-8"))}

    @staticmethod
    def contagem(estat: dict) -> tuple[int, int, int]:
        e = estat["tipos"]["resolucao"]["2025"]
        return e["detalhes_baixados"], e["detalhes_falhas"], e["detalhes_pendentes"]

    def test_primeira_coleta_baixa_todos_os_detalhes(self) -> None:
        estat, pedidos = self.coletar()
        self.assertEqual(pedidos, sorted(RESOLUCOES))
        self.assertEqual(self.contagem(estat), (10, 0, 0))
        lidos = self.lidos()
        for reg in lidos.values():
            self.assertEqual(reg["detalhe_em"], "2026-10-22")
            self.assertNotIn("detalhe_pendente", reg)
            self.assertEqual(reg["autoria"][0]["papel"], "Autor")
            self.assertEqual(len(reg["tramitacoes"]), reg["n_tramitacoes"])
        self.assertEqual(lidos[289947]["publicacao"], {"numero": 3167, "data": "2026-02-27"})
        self.assertEqual(lidos[289947]["assunto"], "CRIAÇÃO")
        self.assertIsNone(lidos[288917]["publicacao"])  # página mínima: nenhum passo "Publicado"
        self.assertEqual(self.arquivo.read_text(encoding="utf-8"), arquivos.texto_lista(sorted(
            lidos.values(), key=lambda r: (r["ano"], documentos.numero_int(r), r["id"]))))
        self.assertIn("::notice::", self.saida)
        self.assertNotIn("::warning::", self.erros)

    def test_limite_baixa_os_mais_recentes_primeiro(self) -> None:
        estat, pedidos = self.coletar(max_detalhes=2)
        # 22/2025 (04/12) e, no empate de 25/11 entre 21/2025 e 20/2025, o de maior número
        self.assertEqual(pedidos, [288917, 289947])
        self.assertEqual(self.contagem(estat), (2, 0, 8))
        lidos = self.lidos()
        pendentes = {i for i, r in lidos.items() if r.get("detalhe_pendente")}
        self.assertEqual(pendentes, set(RESOLUCOES) - {288917, 289947})
        for i in pendentes:
            self.assertNotIn("autoria", lidos[i])
            self.assertNotIn("publicacao", lidos[i])
        self.assertIn("::notice::", self.saida)
        self.assertIn("8 documento(s) ainda aguardam", self.saida)
        estat, pedidos = self.coletar()  # a execução seguinte baixa só os que faltam
        self.assertEqual(pedidos, sorted(pendentes))
        self.assertEqual(self.contagem(estat), (8, 0, 0))

    def test_relistar_preserva_o_detalhe_e_so_rebaixa_quem_mudou(self) -> None:
        self.coletar(hoje="2026-10-20")
        estat, pedidos = self.coletar()
        self.assertEqual(pedidos, [])  # nada mudou na listagem
        self.assertEqual(self.contagem(estat), (0, 0, 0))
        self.assertTrue(all(r["detalhe_em"] == "2026-10-20" and r["autoria"] for r in self.lidos().values()))
        estat, pedidos = self.coletar({(1, 1): UM_PASSO_A_MAIS})
        self.assertEqual(pedidos, [289947])
        lidos = self.lidos()
        self.assertEqual((lidos[289947]["n_tramitacoes"], lidos[289947]["detalhe_em"]), (5, "2026-10-22"))
        self.assertEqual(lidos[288917]["detalhe_em"], "2026-10-20")

    def test_falha_no_detalhe_mantem_o_anterior_e_tenta_de_novo(self) -> None:
        self.coletar(hoje="2026-10-20")
        antes = self.lidos()[289947]
        estat, pedidos = self.coletar({(1, 1): UM_PASSO_A_MAIS}, {289947: RuntimeError("falha ao baixar")})
        self.assertEqual(pedidos, [289947])
        self.assertEqual(self.contagem(estat), (0, 1, 1))
        self.assertEqual((estat["detalhes"]["baixados"], estat["detalhes"]["falhas"]), (0, 1))
        depois = self.lidos()[289947]
        for chave in documentos.CAMPOS_DETALHE + ("publicacao",):
            self.assertEqual(depois[chave], antes[chave])
        self.assertEqual(depois["n_tramitacoes"], 5)
        self.assertTrue(depois["detalhe_pendente"])
        self.assertIn("::warning::", self.erros)
        estat, pedidos = self.coletar({(1, 1): UM_PASSO_A_MAIS})  # a listagem não mudou de novo, mas ficou pendente
        self.assertEqual(pedidos, [289947])
        self.assertEqual(self.contagem(estat), (1, 0, 0))
        self.assertNotIn("detalhe_pendente", self.lidos()[289947])

    def test_pagina_de_erro_conta_como_falha(self) -> None:
        estat, _ = self.coletar(detalhes={289947: "<html><body>Erro no servidor</body></html>"})
        self.assertEqual(self.contagem(estat), (9, 1, 1))
        reg = self.lidos()[289947]
        self.assertTrue(reg["detalhe_pendente"])
        self.assertNotIn("autoria", reg)

    def test_falhas_seguidas_interrompem_os_detalhes(self) -> None:
        fora_do_ar = {i: RuntimeError("falha ao baixar") for i in RESOLUCOES}
        evento = threading.Event()
        erros = SaidaQueSinaliza("detalhes interrompidos após", evento)
        # 3 falhas na hora; os 2 workers ficam presos nas páginas 4 e 5 até o aviso de interrupção
        with mock.patch.object(documentos, "FALHAS_SEGUIDAS_MAX", 3):
            estat, pedidos = self.coletar(detalhes=fora_do_ar, erros=erros, embrulho=segurar_detalhes(3, evento))
        baixados, falhas, pendentes = self.contagem(estat)
        self.assertTrue(evento.is_set())
        self.assertLess(len(pedidos), len(RESOLUCOES))  # as páginas da fila foram canceladas, não pedidas
        self.assertLessEqual(len(pedidos), 3 + 2)
        self.assertEqual((baixados, falhas, pendentes), (0, len(pedidos), 10))
        self.assertTrue(estat["detalhes"]["interrompido_por_falhas"])
        self.assertIn(f"{len(RESOLUCOES) - len(pedidos)} página(s) ficam pendentes", self.erros)
        self.assertTrue(all(r["detalhe_pendente"] for r in self.lidos().values()))

    def test_prazo_interrompe_os_detalhes_e_grava_o_que_ja_baixou(self) -> None:
        relogio = [0.0]
        evento = threading.Event()
        erros = SaidaQueSinaliza("prazo de --max-minutos esgotado", evento)
        vencer = lambda: relogio.__setitem__(0, 100.0)  # o prazo vence durante a 3ª página
        with mock.patch.object(documentos, "_agora", new=lambda: relogio[0]):
            estat, pedidos = self.coletar(prazo=50.0, erros=erros, embrulho=segurar_detalhes(3, evento, vencer))
        self.assertTrue(evento.is_set())
        self.assertLess(len(pedidos), len(RESOLUCOES))
        self.assertGreaterEqual(len(pedidos), 3)
        self.assertEqual(self.contagem(estat), (len(pedidos), 0, len(RESOLUCOES) - len(pedidos)))
        self.assertTrue(estat["detalhes"]["prazo_esgotado"])
        lidos = self.lidos()  # as páginas em andamento quando o prazo venceu também são aplicadas e gravadas
        self.assertEqual({i for i, r in lidos.items() if r.get("detalhe_em")}, set(pedidos))
        self.assertEqual({i for i, r in lidos.items() if r.get("detalhe_pendente")}, set(RESOLUCOES) - set(pedidos))

    def test_prazo_vencido_nao_lista_nem_baixa(self) -> None:
        self.coletar(sem_detalhe=True)
        antes = self.arquivo.read_bytes()
        estat, pedidos = self.coletar(prazo=documentos._agora() - 1)
        self.assertEqual((pedidos, self.listagens), ([], []))
        self.assertEqual(estat["listagem_interrompida"], "prazo")
        self.assertTrue(estat["detalhes"]["prazo_esgotado"])
        self.assertEqual(self.contagem(estat), (0, 0, 10))
        self.assertEqual(self.arquivo.read_bytes(), antes)

    def test_interrupcao_grava_os_detalhes_ja_aplicados(self) -> None:
        original = documentos.aplicar_detalhe
        aplicados: list[int] = []

        def aplicar(reg: dict, detalhe: dict, em: str) -> dict:
            if len(aplicados) == 3:
                raise KeyboardInterrupt  # Ctrl+C (ou SIGTERM, veja main) no meio dos detalhes
            aplicados.append(reg["id"])
            return original(reg, detalhe, em)

        estat: dict = {}
        with mock.patch.object(documentos, "aplicar_detalhe", side_effect=aplicar):
            with self.assertRaises(KeyboardInterrupt):
                self.coletar(estat=estat)
        lidos = self.lidos()
        self.assertEqual(len(aplicados), 3)
        self.assertEqual({i for i, r in lidos.items() if r.get("detalhe_em")}, set(aplicados))
        self.assertEqual({i for i, r in lidos.items() if r.get("detalhe_pendente")}, set(RESOLUCOES) - set(aplicados))
        self.assertEqual(list(self.pasta.rglob("*.tmp")), [])
        # as contagens parciais ficam em estat, para data/meta.json
        self.assertEqual(self.contagem(estat), (3, 0, 7))
        self.assertEqual((estat["detalhes"]["baixados"], estat["detalhes"]["pendentes"]), (3, 7))

    def test_mudanca_de_situacao_ou_do_ultimo_passo_rebaixa_o_detalhe(self) -> None:
        self.coletar(hoje="2026-10-20")
        situacao, trocas = re.subn(
            r"(Situação: </strong>\s*)PUBLICADO", r"\g<1>ARQUIVADO", resolucoes_com_total(10), count=1
        )
        self.assertEqual(trocas, 1)  # a primeira é a de 22/2025 (id 289947)
        _, pedidos = self.coletar({(1, 1): situacao})
        self.assertEqual(pedidos, [289947])
        self.assertEqual((self.lidos()[289947]["situacao"], self.lidos()[289947]["detalhe_em"]), ("ARQUIVADO", "2026-10-22"))
        passo, trocas = re.subn(r"(Data Resposta: </strong>)27/02/2026", r"\g<1>28/02/2026", situacao, count=1)
        self.assertEqual(trocas, 1)
        _, pedidos = self.coletar({(1, 1): passo}, hoje="2026-10-23")  # mesma contagem, passo editado
        self.assertEqual(pedidos, [289947])
        reg = self.lidos()[289947]
        self.assertEqual((reg["ultima_tramitacao"]["data_resposta"], reg["detalhe_em"]), ("2026-02-28", "2026-10-23"))
        _, pedidos = self.coletar({(1, 1): passo})
        self.assertEqual(pedidos, [])

    def test_fila_inclui_pendentes_de_outros_arquivos_e_so_detalhes_os_esvazia(self) -> None:
        def pdl(id_doc: int, numero: int, data: str, pendente: bool) -> dict:
            reg = {**registro(id_doc, numero, 2024, "pdl"), "data": data}
            return {**reg, "detalhe_pendente": True} if pendente else reg

        # arquivo de outro tipo e ano, fora da listagem desta execução; dois sem a marca (versão anterior)
        antigos = [pdl(9001, 1, "2024-01-10", True), pdl(9002, 2, "2024-02-10", False), pdl(9003, 3, "2024-03-10", False)]
        arquivo_pdl = documentos.caminho_ano("pdl", 2024, self.pasta)
        documentos.salvar_ano(arquivo_pdl, {r["id"]: r for r in antigos})
        paginas = {r["id"]: pagina_minima(r, "Projeto de Decreto Legislativo") for r in antigos}
        estat, pedidos = self.coletar(detalhes=paginas, max_detalhes=12)
        # os mais recentes primeiro, entre todos os arquivos: as 10 resoluções de 2025 e os PDLs 3 e 2/2024
        self.assertEqual(pedidos, sorted([*RESOLUCOES, 9002, 9003]))
        lidos = {r["id"]: r for r in json.loads(arquivo_pdl.read_text(encoding="utf-8"))}
        self.assertEqual({i for i, r in lidos.items() if r.get("detalhe_em")}, {9002, 9003})
        self.assertEqual(lidos[9001].get("detalhe_pendente"), True)
        self.assertNotIn("detalhe_em", lidos[9001])
        self.assertEqual(lidos[9003]["autoria"][0]["papel"], "Autor")
        self.assertEqual(
            estat["tipos"]["pdl"]["2024"], {"detalhes_baixados": 2, "detalhes_falhas": 0, "detalhes_pendentes": 1}
        )
        self.assertEqual((estat["detalhes"]["baixados"], estat["detalhes"]["pendentes"]), (12, 1))
        # --so-detalhes: nenhuma listagem, só a fila
        estat, pedidos = self.coletar({(1, 1): RuntimeError("não deveria listar")}, paginas, so_detalhes=True)
        self.assertEqual((pedidos, self.listagens), ([9001], []))
        self.assertEqual(estat["tipos"], {"pdl": {"2024": {"detalhes_baixados": 1, "detalhes_falhas": 0,
                                                           "detalhes_pendentes": 0}}})
        self.assertTrue(all(r.get("detalhe_em") for r in json.loads(arquivo_pdl.read_text(encoding="utf-8"))))

    def test_arquivos_gravados_passam_na_validacao(self) -> None:
        for opcoes in ({"max_detalhes": 4}, {}):
            with self.subTest(**opcoes):
                self.coletar(**opcoes)
                problemas = validar.validar_arquivo_documentos(
                    self.arquivo.read_bytes(), "resolucao", 2025, "data/documentos/resolucao/2025.json", {}, set()
                )
                self.assertEqual(problemas, [])

    def test_sem_detalhe(self) -> None:
        estat, pedidos = self.coletar(sem_detalhe=True)
        self.assertEqual(pedidos, [])
        self.assertEqual(self.contagem(estat), (0, 0, 10))
        self.assertTrue(all(r["detalhe_pendente"] for r in self.lidos().values()))
        self.coletar(hoje="2026-10-20")
        estat, pedidos = self.coletar(sem_detalhe=True)  # relistar sem detalhe preserva o já baixado
        self.assertEqual(pedidos, [])
        self.assertEqual(self.contagem(estat), (0, 0, 0))
        self.assertTrue(all(r["detalhe_em"] == "2026-10-20" for r in self.lidos().values()))

    def test_forcar_rebaixa_todos(self) -> None:
        self.coletar(hoje="2026-10-20")
        estat, pedidos = self.coletar(forcar=True)
        self.assertEqual(pedidos, sorted(RESOLUCOES))
        self.assertEqual(self.contagem(estat), (10, 0, 0))

    def test_meta_registra_as_contagens_de_detalhe(self) -> None:
        estat, _ = self.coletar(max_detalhes=3)
        meta = self.pasta / "meta.json"
        documentos.atualizar_meta(estat, meta)
        documentos_meta = json.loads(meta.read_text(encoding="utf-8"))["documentos"]
        e = documentos_meta["tipos"]["resolucao"]["2025"]
        self.assertEqual((e["detalhes_baixados"], e["detalhes_falhas"], e["detalhes_pendentes"]), (3, 0, 7))
        self.assertEqual((e["listado"], e["registros"]), (10, 10))
        self.assertEqual(
            documentos_meta["detalhes"], {"baixados": 3, "falhas": 0, "pendentes": 7, "limite": 3, "fila": 10}
        )


# ---------------------------------------------------------------------------- meta
class TestMeta(unittest.TestCase):
    def test_preserva_outras_chaves_e_anos(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            meta = Path(temp) / "meta.json"
            arquivos.salvar_json(meta, {"coleta": {"em": "2026-10-19T09:17:00+00:00"}})
            primeira = {"esperado": 22, "listado": 22, "registros": 22, "falhas": 0}
            documentos.atualizar_meta({"tipos": {"resolucao": {"2025": primeira}}}, meta)
            segunda = {"esperado": 3, "listado": 3, "registros": 3, "falhas": 0}
            documentos.atualizar_meta({"tipos": {"resolucao": {2026: segunda}, "mocao": {"2026": segunda}}}, meta)
            dados = json.loads(meta.read_text(encoding="utf-8"))
        self.assertEqual(dados["coleta"], {"em": "2026-10-19T09:17:00+00:00"})
        self.assertEqual(dados["documentos"]["tipos"]["resolucao"], {"2025": primeira, "2026": segunda})
        self.assertEqual(dados["documentos"]["tipos"]["mocao"], {"2026": segunda})
        self.assertIn("em", dados["documentos"])

    def test_so_detalhes_mantem_a_ultima_listagem_e_grava_totais(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            meta = Path(temp) / "meta.json"
            listagem = {"esperado": 3, "listado": 3, "registros": 3, "falhas": 0, "detalhes_baixados": 3,
                        "detalhes_falhas": 0, "detalhes_pendentes": 2}
            documentos.atualizar_meta({"tipos": {"pdl": {"2024": listagem}}}, meta)
            so_detalhes = {"detalhes_baixados": 2, "detalhes_falhas": 0, "detalhes_pendentes": 0}
            totais = {"baixados": 2, "falhas": 0, "pendentes": 0, "limite": 1500, "fila": 2}
            documentos.atualizar_meta(
                {"tipos": {"pdl": {"2024": so_detalhes}}, "detalhes": totais, "interrompido": "KeyboardInterrupt"}, meta
            )
            dados = json.loads(meta.read_text(encoding="utf-8"))["documentos"]
        self.assertEqual(dados["tipos"]["pdl"]["2024"], {**listagem, **so_detalhes})
        self.assertEqual(dados["detalhes"], totais)
        self.assertEqual(dados["interrompido"], "KeyboardInterrupt")
        self.assertNotIn("listagem_interrompida", dados)


class TestDisjuntorDaExecucao(unittest.TestCase):
    """Listagens de vários tipos numa execução, com o SISCAM fora do ar."""

    def coletar(self, baixar, tipos: list[str]) -> tuple[dict, str]:
        erros = io.StringIO()
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(documentos, "baixar", side_effect=baixar), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(erros):
            estat = documentos.coletar(tipos, [2025], 2, Path(temp), hoje="2026-10-22")
        return estat, erros.getvalue()

    @staticmethod
    def tipo_pedido(url: str) -> str:
        return parse_qs(urlsplit(url).query).get("Tipo", ["detalhe"])[0]

    def test_siscam_fora_do_ar_encerra_as_listagens_e_os_detalhes(self) -> None:
        chamadas: list[str] = []

        def fora_do_ar(url: str, tentativas: int = 5) -> str:
            chamadas.append(url)
            raise RuntimeError("SISCAM fora do ar")

        estat, erros = self.coletar(fora_do_ar, ["resolucao", "mocao", "pdl"])
        maximo = documentos.LISTAGENS_SEM_RESPOSTA_MAX
        self.assertEqual({self.tipo_pedido(u) for u in chamadas}, {"7", "3"})  # o PDL (6) nem é pedido
        self.assertEqual(estat["listagem_interrompida"], "siscam_sem_resposta")
        self.assertEqual(sorted(estat["tipos"]), ["mocao", "resolucao"])
        self.assertTrue(all(e["sem_resposta"] for anos in estat["tipos"].values() for e in anos.values()))
        self.assertEqual(estat["detalhes"]["limite"], 0)
        self.assertIn(f"SISCAM sem resposta em {maximo} listagens seguidas", erros)

    def test_falha_de_um_tipo_nao_interrompe_os_demais(self) -> None:
        chamadas: list[str] = []

        def so_resolucoes_falham(url: str, tentativas: int = 5) -> str:
            chamadas.append(url)
            if self.tipo_pedido(url) == "7":
                raise RuntimeError("falha ao baixar")
            return VAZIA

        estat, _ = self.coletar(so_resolucoes_falham, ["resolucao", "mocao", "pdl"])
        self.assertEqual({self.tipo_pedido(u) for u in chamadas}, {"7", "3", "6"})
        self.assertNotIn("listagem_interrompida", estat)
        self.assertEqual(
            {t: e["2025"]["sem_resposta"] for t, e in estat["tipos"].items()},
            {"resolucao": True, "mocao": False, "pdl": False},
        )


class TestMain(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.meta = Path(self._temp.name) / "meta.json"

    def rodar(self, argumentos: list[str], coletar_falso) -> mock.MagicMock:
        """Roda main() com coletar simulado; devolve o mock de coletar (sem tocar no SIGTERM do processo de testes)."""
        with mock.patch.object(sys, "argv", ["coletor.documentos", *argumentos]), \
                mock.patch.object(documentos, "META", self.meta), \
                mock.patch.object(documentos, "_agora", return_value=1000.0), \
                mock.patch.object(documentos.signal, "signal") as instalar, \
                mock.patch.object(documentos, "coletar", side_effect=coletar_falso) as coletar, \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                documentos.main()
            finally:
                instalar.assert_called_once_with(signal.SIGTERM, documentos._interromper)
        return coletar

    def test_interrupcao_ainda_grava_a_meta(self) -> None:
        def interrompido(*_, estat: dict, **__) -> dict:
            estat["tipos"]["resolucao"] = {"2025": {"esperado": 10, "listado": 10, "registros": 10, "falhas": 0}}
            estat["detalhes"] = {"baixados": 3, "falhas": 0, "pendentes": 7, "limite": 1500}
            raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            self.rodar(["--anos", "2025", "--tipos", "resolucao"], interrompido)
        dados = json.loads(self.meta.read_text(encoding="utf-8"))["documentos"]
        self.assertEqual(dados["interrompido"], "KeyboardInterrupt")
        self.assertEqual(dados["tipos"]["resolucao"]["2025"]["listado"], 10)
        self.assertEqual(dados["detalhes"]["baixados"], 3)

    def test_so_detalhes_e_prazo(self) -> None:
        def ok(*_, estat: dict, **__) -> dict:
            estat["detalhes"] = {"baixados": 1, "falhas": 0, "pendentes": 0, "limite": 1500}
            return estat

        coletar = self.rodar(["--anos", "2025", "--so-detalhes", "--max-minutos", "100"], ok)
        opcoes = coletar.call_args.kwargs
        self.assertEqual((opcoes["so_detalhes"], opcoes["prazo"]), (True, 1000.0 + 100 * 60))
        self.assertNotIn("interrompido", json.loads(self.meta.read_text(encoding="utf-8"))["documentos"])

    def test_opcoes_incompativeis(self) -> None:
        for argumentos in (["--so-detalhes", "--sem-detalhe"], ["--so-detalhes", "--forcar"], ["--max-minutos", "0"]):
            with self.subTest(argumentos=argumentos):
                with mock.patch.object(sys, "argv", ["coletor.documentos", *argumentos]), \
                        mock.patch.object(documentos, "coletar") as coletar, \
                        contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as saida:
                    documentos.main()
                self.assertEqual(saida.exception.code, 2)
                coletar.assert_not_called()

    def test_sigterm_vira_interrupcao(self) -> None:
        with self.assertRaises(KeyboardInterrupt):
            documentos._interromper(signal.SIGTERM, None)


class TestIntervaloAnos(unittest.TestCase):
    def test_intervalos(self) -> None:
        self.assertEqual(documentos.intervalo_anos("2025-2026"), [2025, 2026])
        self.assertEqual(documentos.intervalo_anos("2025"), [2025])
        with self.assertRaises(ValueError):
            documentos.intervalo_anos("2026-2025")


class TestArquivos(unittest.TestCase):
    def test_aplicar_e_relistar_preservam_arquivos(self):
        anterior = com_detalhe("pdl", 290379, "pdl_290379")
        self.assertEqual(anterior["arquivos"], ESPERADOS["pdl_290379"])
        relistado = por_id(documentos.parse_listagem(fixture("pdl"), "pdl"), 290379)
        documentos.herdar_detalhe(relistado, anterior)
        self.assertEqual(relistado["arquivos"], anterior["arquivos"])
        documentos.marcar_detalhes({290379: relistado}, {290379: anterior})
        self.assertEqual(relistado["arquivos"], anterior["arquivos"])

    def test_vazio_mantem_anterior_com_aviso(self):
        reg = com_detalhe("resolucao", 289947, "resolucao_289947")
        detalhe = documentos.ler_detalhe(detalhe_html("resolucao_289947"), reg)
        detalhe["arquivos"] = []
        with contextlib.redirect_stderr(io.StringIO()) as erros:
            documentos.aplicar_detalhe(reg, detalhe, "2026-10-27")
        self.assertEqual(reg["arquivos"], ESPERADOS["resolucao_289947"])
        self.assertIn("::warning::", erros.getvalue())

    def test_layout_alterado_preserva_detalhe_pendente(self):
        with tempfile.TemporaryDirectory() as temp:
            pasta = Path(temp)
            caminho = documentos.caminho_ano("resolucao", 2025, pasta)
            reg = com_detalhe("resolucao", 289947, "resolucao_289947")
            reg["detalhe_pendente"] = True
            documentos.salvar_ano(caminho, {reg["id"]: reg})
            antes = caminho.read_bytes()
            pagina = detalhe_html("resolucao_289947").replace('id="arquivos_gvListagem"', 'id="grade_alterada"')
            with mock.patch.object(documentos, "baixar", return_value=pagina), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                estat = documentos.coletar_detalhes([], [], 1, pasta)
            self.assertEqual(estat[("resolucao", 2025)]["detalhes_falhas"], 1)
            self.assertEqual(caminho.read_bytes(), antes)

    def test_cli_cache_offline_e_idempotente(self):
        with tempfile.TemporaryDirectory() as temp:
            raiz = Path(temp)
            dados, cache = raiz / "documentos", raiz / "cache"
            cache.mkdir()
            reg = registro(289947, 22)
            ausente = {**registro(9, 1), "detalhe_em": "2026-10-01"}
            conhecido = {**registro(10, 2), "arquivos": []}
            simples = registro(11, 3, tipo="indicacao")
            multiplo = {**registro(12, 4, tipo="mocao"), "detalhe_em": "2026-10-01",
                        "autores": [{"id": 1, "nome": "A"}, {"id": 2, "nome": "B"}]}
            nao_baixado = {**multiplo, "id": 13, "numero": "5/2025"}
            nao_baixado.pop("detalhe_em")
            for id_ in (289947, 11, 12, 13):
                (cache / f"{id_}.html").write_text(detalhe_html("resolucao_289947"), encoding="utf-8")
            with mock.patch.object(documentos, "DIR_DOCUMENTOS", dados), \
                    mock.patch.object(documentos, "baixar") as baixar, \
                    mock.patch.object(documentos, "atualizar_meta") as meta, \
                    mock.patch.object(sys, "argv", ["documentos", "--arquivos-do-cache", str(cache)]):
                for tipo, regs in [("resolucao", [reg, ausente, conhecido]), ("indicacao", [simples]),
                                   ("mocao", [multiplo, nao_baixado])]:
                    documentos.salvar_ano(documentos.caminho_ano(tipo, 2025), {r["id"]: r for r in regs})
                documentos.main()
                primeira = {p: p.read_bytes() for p in dados.rglob("*.json")}
                documentos.main()
                self.assertEqual({p: p.read_bytes() for p in dados.rglob("*.json")}, primeira)
                lidos = documentos.carregar_ano(documentos.caminho_ano("resolucao", 2025))
                mocoes = documentos.carregar_ano(documentos.caminho_ano("mocao", 2025))
                self.assertEqual(documentos.carregar_ano(documentos.caminho_ano("indicacao", 2025))[11], simples)
                baixar.assert_not_called()
                meta.assert_not_called()
            self.assertEqual(lidos[289947], {**reg, "arquivos": ESPERADOS["resolucao_289947"]})
            # sem HTML no cache: intocados, sem chaves novas (nem "detalhe_pendente")
            self.assertEqual(lidos[9], ausente)
            self.assertEqual(lidos[10], conhecido)
            self.assertEqual(mocoes[12], {**multiplo, "arquivos": ESPERADOS["resolucao_289947"]})
            self.assertEqual(mocoes[13], nao_baixado)  # moção ainda sem detalhe: fica para a fila normal

    def test_cli_cache_respeita_anos_e_tipos(self):
        with mock.patch.object(sys, "argv", ["documentos", "--arquivos-do-cache", "cache", "--anos", "2024"]), \
                mock.patch.object(documentos, "arquivos_do_cache") as preencher:
            documentos.main()
        preencher.assert_called_once_with(Path("cache"), [2024], list(documentos.TIPOS))
        argv = ["documentos", "--arquivos-do-cache", "cache", "--tipos", "pdl,requerimento"]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(documentos, "arquivos_do_cache") as preencher:
            documentos.main()
        preencher.assert_called_once_with(Path("cache"), None, ["pdl", "requerimento"])

    def test_cli_cache_so_preenche_os_tipos_pedidos(self):
        with tempfile.TemporaryDirectory() as temp:
            dados, cache = Path(temp) / "documentos", Path(temp) / "cache"
            cache.mkdir()
            (cache / "289947.html").write_text(detalhe_html("resolucao_289947"), encoding="utf-8")
            (cache / "290379.html").write_text(detalhe_html("pdl_290379"), encoding="utf-8")
            with mock.patch.object(documentos, "DIR_DOCUMENTOS", dados):
                documentos.salvar_ano(documentos.caminho_ano("resolucao", 2025), {289947: registro(289947, 22)})
                documentos.salvar_ano(documentos.caminho_ano("pdl", 2025), {290379: registro(290379, 309, tipo="pdl")})
                documentos.arquivos_do_cache(cache, None, ["pdl"])
                resolucoes = documentos.carregar_ano(documentos.caminho_ano("resolucao", 2025))
                pdls = documentos.carregar_ano(documentos.caminho_ano("pdl", 2025))
        self.assertNotIn("arquivos", resolucoes[289947])
        self.assertEqual(pdls[290379]["arquivos"], ESPERADOS["pdl_290379"])

    def test_cli_cache_avisa_opcoes_ignoradas(self):
        argv = ["documentos", "--arquivos-do-cache", "cache", "--so-detalhes"]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(documentos, "arquivos_do_cache") as preencher, \
                mock.patch.object(documentos, "coletar") as coletar, contextlib.redirect_stderr(io.StringIO()) as erros:
            documentos.main()
        preencher.assert_called_once()
        coletar.assert_not_called()
        self.assertIn("::warning::--arquivos-do-cache ignora --so-detalhes", erros.getvalue())


class TestFilaDeArquivos(unittest.TestCase):
    """Detalhe antigo, sem a chave "arquivos", volta à fila só em requerimentos, PDLs e resoluções."""

    def test_falta_arquivos(self):
        baixado = {**registro(9, 1), "detalhe_em": "2026-10-01"}
        dois = [{"id": 1, "nome": "A"}, {"id": 2, "nome": "B"}]
        casos = (
            (baixado, True),
            ({**baixado, "tipo": "requerimento"}, True),
            ({**baixado, "tipo": "pdl"}, True),
            ({**baixado, "arquivos": []}, False),
            (registro(9, 1), False),  # sem detalhe: regra de sempre (precisa_detalhe), não esta
            ({**baixado, "tipo": "indicacao", "autores": dois}, False),
            ({**baixado, "tipo": "mocao", "autores": dois}, False),
            (None, False),
        )
        for reg, esperado in casos:
            with self.subTest(reg=reg):
                self.assertEqual(documentos.falta_arquivos(reg), esperado)

    def test_relistar_sem_mudanca_rebaixa_so_quem_nao_tem_arquivos(self):
        dois = [{"id": 1, "nome": "A"}, {"id": 2, "nome": "B"}]
        anterior = {**registro(9, 1, tipo="requerimento"), "detalhe_em": "2026-10-01"}
        mocao = {**registro(10, 2, tipo="mocao"), "autores": dois, "detalhe_em": "2026-10-01"}
        self.assertTrue(documentos.precisa_detalhe(registro(9, 1, tipo="requerimento"), anterior))
        self.assertFalse(documentos.precisa_detalhe(registro(9, 1, tipo="requerimento"), {**anterior, "arquivos": []}))
        self.assertFalse(documentos.precisa_detalhe({**registro(10, 2, tipo="mocao"), "autores": dois}, mocao))

    def test_fila_respeita_o_limite_e_a_recencia(self):
        dois = [{"id": 1, "nome": "A"}, {"id": 2, "nome": "B"}]

        def req(id_doc: int, numero: int, data: str, **campos) -> dict:
            return {**registro(id_doc, numero, 2025, "requerimento"), "data": data, "detalhe_em": "2026-10-01", **campos}

        requerimentos = [req(1, 1, "2025-01-10"), req(2, 2, "2025-02-10"), req(3, 3, "2025-03-10"),
                         req(4, 4, "2025-04-10", arquivos=[])]
        mocao = {**registro(5, 1, 2025, "mocao"), "autores": dois, "detalhe_em": "2026-10-01", "data": "2025-12-01"}
        paginas = {r["id"]: pagina_minima(r, "Requerimento") for r in requerimentos}
        pedidos: list[int] = []

        def baixar(url: str, tentativas: int = 5) -> str:
            id_doc = int(parse_qs(urlsplit(url).query)["IdDocumento"][0])
            pedidos.append(id_doc)
            return paginas[id_doc]

        with tempfile.TemporaryDirectory() as temp:
            pasta = Path(temp)
            documentos.salvar_ano(documentos.caminho_ano("requerimento", 2025, pasta), {r["id"]: r for r in requerimentos})
            documentos.salvar_ano(documentos.caminho_ano("mocao", 2025, pasta), {5: mocao})
            antes_mocao = documentos.caminho_ano("mocao", 2025, pasta).read_bytes()
            with mock.patch.object(documentos, "baixar", side_effect=baixar), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                documentos.coletar_detalhes([], [], 1, pasta, max_detalhes=2, hoje="2026-10-27")
                self.assertEqual(sorted(pedidos), [2, 3])  # os mais recentes; o 4 já tem "arquivos"
                lidos = documentos.carregar_ano(documentos.caminho_ano("requerimento", 2025, pasta))
                self.assertEqual({i for i, r in lidos.items() if r.get("detalhe_pendente")}, {1})
                self.assertEqual((lidos[2]["arquivos"], lidos[3]["detalhe_em"]), ([], "2026-10-27"))
                self.assertEqual(lidos[4], requerimentos[3])
                self.assertEqual(documentos.caminho_ano("mocao", 2025, pasta).read_bytes(), antes_mocao)
                pedidos.clear()
                documentos.coletar_detalhes([], [], 1, pasta, max_detalhes=0, hoje="2026-10-27")
                self.assertEqual(pedidos, [])  # limite zero: nada baixado, o 1 continua pendente
                lidos = documentos.carregar_ano(documentos.caminho_ano("requerimento", 2025, pasta))
                self.assertTrue(lidos[1]["detalhe_pendente"])


if __name__ == "__main__":
    unittest.main()
