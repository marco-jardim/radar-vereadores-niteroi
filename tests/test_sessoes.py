"""Testes do coletor de sessões plenárias (coletor/sessoes.py).

Usa a listagem por ano (sessoes_resultado_2021_*.html) e as páginas de detalhe reais
(sessao_<id>.html) salvas em tests/fixtures/siscam/, lidas como siscam.baixar as
decodifica (bytes, sem traduzir quebras de linha); a rede é sempre simulada.
Uso: python -m unittest tests.test_sessoes  (ou pytest tests/test_sessoes.py)
"""
from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import os
import random
import re
import tempfile
import unittest
from collections import Counter, defaultdict
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from coletor import documentos, validar
from coletor import sessoes as S
from coletor.arquivos import texto_lista
from tests.apoio import RAIZ, ler_fixture

P1 = "sessoes_resultado_2021_p1.html"
P11 = "sessoes_resultado_2021_p11.html"
P13 = "sessoes_resultado_2021_p13_fora.html"  # página fora do intervalo: o SISCAM devolve a página 1
IDS_P1 = [11895, 11896, 11894, 11893, 11892, 11891, 11890, 11889, 11888, 11887]
IDS_P11 = [11789, 11800]
FIXTURES_DETALHE = (11800, 11850, 11896, 12029, 22155, 22344, 22367, 22399, 22436)
# linhas de tabela simples "<td>nome</td><td>valor</td>" (frequência e votos)
RE_LINHA_SIMPLES = re.compile(r'<tr class="grid-row-(?:item|alternativo)">\s*<td>[^<]*</td><td>[^<]*</td>\s*</tr>')


def ler(nome: str) -> str:
    return ler_fixture("siscam", nome)


def pagina_detalhe(id_sessao: int) -> str:
    return ler(f"sessao_{id_sessao}.html")


def marcar_pagina(html: str, n: int) -> str:
    """A listagem com o paginador marcando a página n."""
    return re.sub(r'<span class="currentPage">\d+</span>', f'<span class="currentPage">{n}</span>', html)


def pagina_sintetica(n: int, deslocamento: int) -> str:
    """A página 1 real de 2021 com os ids somados de `deslocamento` e o paginador marcando a página n."""
    html = re.sub(r"IdDocumento=(\d+)", lambda m: f"IdDocumento={int(m.group(1)) + deslocamento}", ler(P1))
    return marcar_pagina(html, n)


def sem_paginador(html: str) -> str:
    return html.replace('class="currentPage"', 'class="paginaAtual"')


def servidor(listagem: dict[int, object], detalhe=None):
    """Simula baixar(): a listagem responde pela página, o detalhe por `detalhe(id)`; exceções são levantadas.

    Página da listagem não informada responde como o SISCAM a uma página além da última: com a página 1.
    """
    chamadas: list[str] = []

    def baixar(url: str, tentativas: int = 5) -> str:
        chamadas.append(url)
        q = parse_qs(urlsplit(url).query)
        if "ResultadoSessao.aspx" in url:
            resposta = listagem.get(int(q["pagina"][0]), ler(P13))
        else:
            resposta = detalhe(int(q["IdDocumento"][0]))
        if isinstance(resposta, Exception):
            raise resposta
        return resposta

    return baixar, chamadas


def contar_pauta(html: str) -> int:
    """Contagem independente do parser: os links da pauta usam aspas simples; os das votações, duplas."""
    return html.count("href='DetalhesDocumentos.aspx?IdDocumento=")


def contar_frequencia(html: str) -> int:
    """Linhas de vereador depois do início da seção de frequência (a última da página)."""
    if 'id="trFrequencia"' not in html:
        return 0
    return len(RE_LINHA_SIMPLES.findall(html[html.index('id="trFrequencia"'):]))


def detalhe_silencioso(html: str) -> tuple[dict, str]:
    with contextlib.redirect_stderr(io.StringIO()) as err:
        return S.parse_detalhe(html), err.getvalue()


# --------------------------------------------------------------------- listagem
class TestListagem(unittest.TestCase):
    def test_pagina_1(self):
        sessoes, exibida = S.parse_listagem(ler(P1))
        self.assertEqual(exibida, 1)
        self.assertEqual([s["id"] for s in sessoes], IDS_P1)  # a ordem não é estritamente por número
        self.assertEqual(
            sessoes[0],
            {
                "id": 11895,
                "titulo": "13ª Sessão Extraordinária de 2021",
                "numero": 13,
                "tipo": "extraordinaria",
                "tipo_texto": "Extraordinária",
                "ano": 2021,
                "data": "2021-12-22",
                "hora": "15:00",
                "url": "https://consultaniteroi.siscam.com.br/DetalhesSessao.aspx?IdDocumento=11895",
            },
        )
        # o SISCAM repete o número 13 em duas extraordinárias, com ids e datas diferentes
        self.assertEqual([(s["id"], s["data"]) for s in sessoes if s["numero"] == 13],
                         [(11895, "2021-12-22"), (11894, "2021-12-21")])
        self.assertEqual(Counter(s["tipo"] for s in sessoes), Counter({"ordinaria": 5, "extraordinaria": 5}))

    def test_ultima_pagina(self):
        sessoes, exibida = S.parse_listagem(ler(P11))
        self.assertEqual(exibida, 11)
        self.assertEqual(
            [(s["id"], s["numero"], s["tipo"], s["data"], s["hora"]) for s in sessoes],
            [(11789, 1, "ordinaria", "2021-01-13", "17:00"), (11800, 1, "especial", "2021-01-01", "10:00")],
        )

    def test_pagina_fora_do_intervalo_repete_a_primeira(self):
        fora, exibida = S.parse_listagem(ler(P13))
        self.assertEqual(exibida, 1)  # pedida a 13, o paginador marca a 1
        self.assertEqual(fora, S.parse_listagem(ler(P1))[0])

    def listar(self, paginas: dict[int, object]) -> tuple[dict, list[str], str]:
        baixar, chamadas = servidor(paginas)
        with mock.patch.object(S, "baixar", baixar), contextlib.redirect_stderr(io.StringIO()) as err:
            lista = S.listar_ano(2021)
        return lista, chamadas, err.getvalue()

    def test_ano_completo_para_na_pagina_curta(self):
        paginas = {1: ler(P1), **{n: pagina_sintetica(n, 1000 * n) for n in range(2, 11)}, 11: ler(P11)}
        lista, chamadas, err = self.listar(paginas)
        self.assertTrue(lista["completa"])
        self.assertEqual(len(lista["itens"]), 102)
        self.assertEqual(lista["paginas"], 11)
        self.assertEqual(len(chamadas), 11)  # a página 11 tem 2 sessões: a 12 nem é pedida
        self.assertEqual(err, "")

    def test_pagina_fora_do_intervalo_encerra_sem_duplicar(self):
        # 30 sessões: a página 4 não existe e o SISCAM devolve a página 1 de novo
        lista, chamadas, err = self.listar({1: ler(P1), 2: pagina_sintetica(2, 1000), 3: pagina_sintetica(3, 2000)})
        self.assertTrue(lista["completa"])
        self.assertEqual(len(lista["itens"]), 30)
        self.assertEqual(len(chamadas), 4)
        self.assertEqual(parse_qs(urlsplit(chamadas[-1]).query)["pagina"], ["4"])
        self.assertEqual(err, "")

    def test_repeticao_de_ids_encerra_sem_paginador(self):
        paginas = {1: sem_paginador(ler(P1)), 2: sem_paginador(pagina_sintetica(2, 1000)), 3: sem_paginador(ler(P13))}
        lista, chamadas, _ = self.listar(paginas)
        self.assertTrue(lista["completa"])
        self.assertEqual(len(lista["itens"]), 20)
        self.assertEqual(len(chamadas), 3)

    def test_trava_de_paginas(self):
        paginas = {n: pagina_sintetica(n, 1000 * n) for n in range(1, 6)}
        with mock.patch.object(S, "PAGINAS_MAX", 3):
            lista, chamadas, err = self.listar(paginas)
        self.assertFalse(lista["completa"])
        self.assertEqual(len(lista["itens"]), 30)
        self.assertEqual(len(chamadas), 3)
        self.assertIn("::warning::sessões 2021: listagem interrompida após 3 páginas", err)

    def test_falha_numa_pagina_seguinte_deixa_a_listagem_incompleta(self):
        lista, _, err = self.listar({1: ler(P1), 2: RuntimeError("tempo esgotado")})
        self.assertFalse(lista["completa"])
        self.assertEqual(len(lista["itens"]), 10)
        self.assertEqual(len(lista["falhas"]), 1)
        self.assertIn("::warning::sessões 2021, página 2: falha na listagem", err)

    def test_falha_na_primeira_pagina_sobe(self):
        with self.assertRaises(RuntimeError):
            self.listar({1: RuntimeError("SISCAM fora do ar")})

    def test_primeira_pagina_marcada_como_outra(self):
        with self.assertRaises(ValueError):
            self.listar({1: marcar_pagina(ler(P1), 2)})


# ---------------------------------------------------------------------- detalhe
ESPERADO = {
    # pauta e frequência None: conferidas só pela contagem independente
    11800: dict(titulo="1ª Sessão Especial de 2021", numero=1, tipo="especial", data="2021-01-01", hora="10:00",
                documentos=["Ata"], pauta=0, frequencia=0, votos=[]),
    11850: dict(titulo="48ª Sessão Ordinária de 2021", numero=48, tipo="ordinaria", data="2021-08-04", hora="14:00",
                documentos=["Ordem do Dia", "Pauta", "Ordem do Dia", "Ata"], pauta=142, frequencia=21,
                votos=[21, 21, 21, 21]),
    11896: dict(titulo="83ª Sessão Ordinária de 2021", numero=83, tipo="ordinaria", data="2021-12-22", hora="14:00",
                documentos=["Ordem do Dia", "Pauta", "Ordem do Dia", "Ata"], pauta=0, frequencia=21, votos=[]),
    12029: dict(titulo="29ª Sessão Ordinária de 2023", numero=29, tipo="ordinaria", data="2023-05-03", hora="16:00",
                documentos=["Pauta", "Ordem do Dia", "Ata"], pauta=35, frequencia=21, votos=[21]),
    22155: dict(titulo="34ª Sessão Ordinária de 2024", numero=34, tipo="ordinaria", data="2024-05-16", hora="16:00",
                documentos=["Pauta", "Ordem do Dia", "Ata"], pauta=49, frequencia=21, votos=[21]),
    22344: dict(titulo="95ª Sessão Ordinária de 2025", numero=95, tipo="ordinaria", data="2025-12-02", hora="16:00",
                documentos=["Pauta", "Ordem do Dia", "Ordem do Dia", "Ata"], pauta=None, frequencia=None,
                votos=[21, 21, 21, 20, 20]),
    22367: dict(titulo="1ª Sessão Extraordinária de 2026", numero=1, tipo="extraordinaria", data="2026-03-25",
                hora="16:30", documentos=["Ordem do Dia", "Ordem do Dia", "Ata"], pauta=0, frequencia=22, votos=[21]),
    22399: dict(titulo="4ª Sessão Extraordinária de 2026", numero=4, tipo="extraordinaria", data="2026-06-17",
                hora="17:00", documentos=["Ordem do Dia", "Expediente em pdf", "Ata"], pauta=0, frequencia=21,
                votos=[21]),
    22436: dict(titulo="74ª Sessão Ordinária de 2026", numero=74, tipo="ordinaria", data="2026-10-13", hora="11:00",
                documentos=["Pauta", "Ordem do Dia", "Ata"], pauta=None, frequencia=21, votos=[]),
}


class TestDetalhe(unittest.TestCase):
    def test_cada_fixture(self):
        for id_sessao, esperado in ESPERADO.items():
            with self.subTest(sessao=id_sessao):
                html = pagina_detalhe(id_sessao)
                d, err = detalhe_silencioso(html)
                self.assertNotIn("::warning::", err, "a página real não deveria gerar aviso de layout ou de totais")
                if id_sessao == 22344:  # o presidente aparece duas vezes numa votação: só o aviso simples
                    self.assertIn("nome(s) repetido(s) MILTON CARLOS DA SILVA LOPES", err)
                else:
                    self.assertEqual(err, "", "a página real não deveria gerar aviso")
                self.assertEqual(d["avisos"], [])
                self.assertEqual(d["layout_alterado"], [])
                self.assertEqual(d["id"], id_sessao)
                for chave in ("titulo", "numero", "tipo", "data", "hora"):
                    self.assertEqual(d[chave], esperado[chave], chave)
                self.assertEqual([x["rotulo"] for x in d["documentos_sessao"]], esperado["documentos"])
                for x in d["documentos_sessao"]:
                    self.assertRegex(x["url"], r"^https://consultaniteroi\.siscam\.com\.br/Arquivos/Sessoes/[0-9a-f-]+\.\w+$")
                self.assertEqual(len(d["pauta"]), contar_pauta(html))
                if esperado["pauta"] is not None:
                    self.assertEqual(len(d["pauta"]), esperado["pauta"])
                self.assertEqual(len(d["frequencia"]), contar_frequencia(html))
                if esperado["frequencia"] is not None:
                    self.assertEqual(len(d["frequencia"]), esperado["frequencia"])
                self.assertEqual([len(v["votos"]) for v in d["votacoes"]], esperado["votos"])

    def test_sessao_especial_sem_frequencia_nem_votacao(self):
        d, _ = detalhe_silencioso(pagina_detalhe(11800))
        self.assertEqual(d["tipo_texto"], "Especial")
        self.assertEqual(d["observacoes"], "SESSÃO ESPECIAL DE INSTALAÇÃO NA FORMA DO ART. 9º DO REGIEMNTO INTERNO.")
        self.assertEqual(
            d["documentos_sessao"],
            [{"rotulo": "Ata",
              "url": "https://consultaniteroi.siscam.com.br/Arquivos/Sessoes/9803db06-44c4-4ef0-b80a-d3989f9acd37.doc"}],
        )
        self.assertEqual((d["pauta"], d["frequencia"], d["votacoes"]), ([], [], []))

    def test_observacoes(self):
        self.assertEqual(
            detalhe_silencioso(pagina_detalhe(11896))[0]["observacoes"],
            "EXTRAPAUTA: MOÇÃO Nº 1502/2021- APROVADA; PROJETO DE DECRETO Nº 210/2021 - LIDO",
        )
        self.assertTrue(
            detalhe_silencioso(pagina_detalhe(22344))[0]["observacoes"].startswith(
                "EXTRA PAUTA: PROJETO DE DECRETO LEGISLATIVO Nº 282, 283 E 284/2025 - LIDO;"
            )
        )
        self.assertEqual(detalhe_silencioso(pagina_detalhe(22367))[0]["observacoes"], "")

    def test_pauta_2021(self):
        pauta = detalhe_silencioso(pagina_detalhe(11850))[0]["pauta"]
        self.assertEqual(
            pauta[0],
            {
                "secao": "Pauta",
                "secao_indice": 1,  # documentos_sessao: Ordem do Dia, Pauta, Ordem do Dia, Ata
                "prioridade": "Ordinária",
                "fase": "Leitura",
                "id_documento": 130695,
                "tipo_documento": "Projeto de Lei",
                "numero": "268/2021",
                "ano": 2021,
                "ementa": "Ementa: Dispõe sobre a instalação de recuo para cadeirantes nos pontos de ônibus que possuem "
                "abrigos de passageiros e os que venham a ser instalados no município de Niterói.",
            },
        )
        self.assertEqual((pauta[3]["tipo_documento"], pauta[3]["numero"], pauta[3]["id_documento"]),
                         ("Indicação", "3577/2021", 130687))
        self.assertEqual((pauta[-1]["tipo_documento"], pauta[-1]["numero"], pauta[-1]["id_documento"], pauta[-1]["fase"]),
                         ("Moção", "605/2021", 130811, "Votação"))
        self.assertEqual(Counter(p["fase"] for p in pauta), Counter({"Leitura": 112, "Votação": 30}))
        self.assertEqual({(p["secao"], p["secao_indice"]) for p in pauta}, {("Pauta", 1)})

    def test_pauta_de_outros_anos(self):
        self.assertEqual(Counter(p["fase"] for p in detalhe_silencioso(pagina_detalhe(22155))[0]["pauta"]),
                         Counter({"Leitura": 23, "Votação": 26}))
        pauta_2026 = detalhe_silencioso(pagina_detalhe(22436))[0]["pauta"]
        self.assertEqual({p["fase"] for p in pauta_2026}, {"Leitura"})
        self.assertEqual((pauta_2026[0]["tipo_documento"], pauta_2026[0]["numero"], pauta_2026[0]["id_documento"]),
                         ("Projeto de Decreto Legislativo", "240/2026", 300342))
        self.assertTrue(all(p["ano"] == 2026 and p["numero"].endswith("/2026") for p in pauta_2026))

    def test_frequencia(self):
        f = detalhe_silencioso(pagina_detalhe(11850))[0]["frequencia"]
        self.assertEqual(f[0], {"momento": "Abertura - 14:10", "nome": "ATRATINO CORTES COUTINHO NETO",
                                "situacao": "Consignado"})
        self.assertEqual({x["momento"] for x in f}, {"Abertura - 14:10"})
        self.assertEqual(Counter(x["situacao"] for x in f),
                         Counter({"Presença": 14, "Consignado": 5, "Licença": 1, "Ausência": 1}))
        # o nome fica como vem, com o apelido depois do hífen
        self.assertIn({"momento": "Abertura - 14:10", "nome": "CARLOS OTÁVIO DIAS VAZ - CASOTA", "situacao": "Presença"}, f)
        self.assertTrue(all(set(x) == {"momento", "nome", "situacao"} for x in f))
        f_2026 = detalhe_silencioso(pagina_detalhe(22367))[0]["frequencia"]
        self.assertEqual(Counter(x["situacao"] for x in f_2026),
                         Counter({"Presença": 20, "Ausência Justificada": 1, "Consignado": 1}))

    def test_votacoes_nominais_de_veto_2021(self):
        votacoes = detalhe_silencioso(pagina_detalhe(11850))[0]["votacoes"]
        self.assertEqual([v["id_documento"] for v in votacoes], [30641, 126663, 126249, 125529])
        self.assertEqual({v["resultado"] for v in votacoes}, {"Veto Mantido"})
        v = votacoes[0]
        self.assertEqual(
            {k: v[k] for k in v if k != "votos"},
            {
                "id_documento": 30641,
                "documento": "Projeto de Lei Nº 00002/2015",
                "tipo_documento": "Projeto de Lei",
                "numero": "2/2015",
                "ano": 2015,
                "resultado": "Veto Mantido",
                "tipo_votacao": "Nominal",
                "totais": {"favor": 11, "contra": 2, "branco": 0, "nulo": 0, "abstencao": 3, "ausentes": 4},
            },
        )
        self.assertEqual(v["votos"][0], {"nome": "DADO FOLY", "voto": "Favor"})
        # o texto do voto é gravado como está, sem interpretar "Presidente" nem o sentido de "Favor" num veto
        self.assertIn({"nome": "MILTON CARLOS DA SILVA LOPES", "voto": "Presidente"}, v["votos"])
        self.assertIn({"nome": "BENNY BRIOLLY", "voto": "Abstenção"}, v["votos"])
        self.assertIn({"nome": "José Adriano Valle da Costa - Folha", "voto": "Favor"}, v["votos"])
        self.assertEqual(S.contagem_dos_votos(v["votos"]), v["totais"])  # "Presidente" não conta

    def test_totais_batem_com_os_votos(self):
        for id_sessao in FIXTURES_DETALHE:
            for i, v in enumerate(detalhe_silencioso(pagina_detalhe(id_sessao))[0]["votacoes"]):
                with self.subTest(sessao=id_sessao, votacao=i):
                    c = Counter(x["voto"] for x in v["votos"])
                    self.assertEqual(
                        v["totais"],
                        {"favor": c["Favor"], "contra": c["Contra"], "branco": c["Branco"], "nulo": c["Nulo"],
                         "abstencao": c["Abstenção"], "ausentes": c["Ausente"]},
                    )

    def test_votacao_2025_com_vereador_repetido(self):
        # 95ª Ordinária de 2025, PL 487/2025: o SISCAM lista o presidente como "Ausente" e como "Presidente"
        d, err = detalhe_silencioso(pagina_detalhe(22344))
        v = d["votacoes"][4]
        self.assertEqual((v["numero"], v["resultado"]), ("487/2025", "Aprovado"))
        # o dado bruto fica, e o nome repetido é sinalizado (somas por vereador precisam deduplicar)
        self.assertEqual([x["voto"] for x in v["votos"] if x["nome"] == "MILTON CARLOS DA SILVA LOPES"],
                         ["Ausente", "Presidente"])
        self.assertEqual(v["nomes_repetidos"], ["MILTON CARLOS DA SILVA LOPES"])
        self.assertEqual([("nomes_repetidos" in x) for x in d["votacoes"]], [False, False, False, False, True])
        self.assertIn("aviso: sessão 22344", err)
        self.assertNotIn("::warning::", err)

    def test_nomes_repetidos_na_frequencia_por_momento(self):
        frequencia = [{"momento": "Abertura", "nome": "A", "situacao": "Presença"},
                      {"momento": "Encerramento", "nome": "A", "situacao": "Presença"},
                      {"momento": "Abertura", "nome": "B", "situacao": "Presença"},
                      {"momento": "Abertura", "nome": "B", "situacao": "Ausência"}]
        self.assertEqual(S.nomes_repetidos(frequencia, "momento"), ["B"])
        self.assertEqual(S.nomes_repetidos(frequencia), ["A", "B"])
        d, _ = detalhe_silencioso(pagina_detalhe(11896))
        reg = S.aplicar_detalhe({"id": 11896}, {**d, "frequencia": frequencia}, "2026-10-23")
        self.assertEqual(reg["frequencia_nomes_repetidos"], ["B"])
        self.assertNotIn("frequencia_nomes_repetidos", S.aplicar_detalhe({"id": 11896}, d, "2026-10-23"))

    def test_votacao_de_veto_2026(self):
        v = detalhe_silencioso(pagina_detalhe(22367))[0]["votacoes"][0]
        self.assertEqual((v["id_documento"], v["numero"], v["resultado"]), (280671, "280/2025", "Veto Mantido"))
        self.assertEqual(v["totais"], {"favor": 11, "contra": 6, "branco": 0, "nulo": 0, "abstencao": 0, "ausentes": 3})

    def test_expediente_em_pdf_2026(self):
        docs = detalhe_silencioso(pagina_detalhe(22399))[0]["documentos_sessao"]
        self.assertTrue(docs[1]["url"].endswith(".pdf"))


class TestAvisos(unittest.TestCase):
    """Seção presente sem nenhum item reconhecido avisa em vez de virar lista vazia em silêncio."""

    def test_frequencia_sem_vereadores(self):
        html = pagina_detalhe(11850)
        i = html.index('id="trFrequencia"')
        d, err = detalhe_silencioso(html[:i] + RE_LINHA_SIMPLES.sub("", html[i:]))
        self.assertEqual(d["frequencia"], [])
        self.assertIn("::warning::sessão 11850", err)
        self.assertIn("[ Frequência ] sem nenhum vereador reconhecido", err)

    def test_grade_de_votacoes_ausente(self):
        d, err = detalhe_silencioso(pagina_detalhe(12029).replace('id="gvListagemVotacoes"', 'id="gvOutraGrade"'))
        self.assertEqual(d["votacoes"], [])
        self.assertIn("::warning::", err)
        self.assertIn("sem a grade gvListagemVotacoes", err)
        self.assertEqual(d["layout_alterado"], ["seção [ Votações ] sem a grade gvListagemVotacoes"])

    def test_rotulo_de_secao_sem_o_id_esperado_e_layout_alterado(self):
        # o rótulo "[ ... ]" continua na página, mas a linha mudou de id: avisa e não vira lista vazia em silêncio
        casos = {
            "trFrequencia": ("Frequência", "frequencia"),
            "trVotacoes": ("Votações", "votacoes"),
            "trDocumentosSessao": ("Documentos da Sessão", "pauta"),
        }
        for id_linha, (rotulo, lista) in casos.items():
            with self.subTest(id_linha=id_linha):
                html = pagina_detalhe(11850).replace(f'id="{id_linha}"', f'id="{id_linha}Novo"')
                d, err = detalhe_silencioso(html)
                self.assertEqual(d[lista], [])
                self.assertEqual(d["layout_alterado"], [f"seção [ {rotulo} ] na página sem a linha {id_linha}"])
                self.assertIn(f"::warning::sessão 11850 ('48ª Sessão Ordinária de 2021'): seção [ {rotulo} ]", err)
                with self.assertRaisesRegex(ValueError, "layout do SISCAM alterado"), \
                        contextlib.redirect_stderr(io.StringIO()):
                    S.ler_detalhe(html, dict(TestLerEAplicarDetalhe.REGISTRO))

    def test_secao_ausente_sem_rotulo_nao_e_layout_alterado(self):
        # sem a linha e sem o rótulo, a sessão só não tem a seção (como a 1ª Especial de 2021, sem votação)
        d, err = detalhe_silencioso(pagina_detalhe(11800))
        self.assertEqual((d["frequencia"], d["votacoes"], d["layout_alterado"]), ([], [], []))
        self.assertEqual(err, "")

    def test_ordinaria_sem_frequencia_so_avisa(self):
        html = pagina_detalhe(11896)
        i = html.index('<tr id="trFrequencia">')
        j = html.index("</tr>", html.index("</fieldset>", i)) + len("</tr>")
        registro = {"id": 11896, "numero": 83, "tipo": "ordinaria", "data": "2021-12-22", "hora": "14:00"}
        with contextlib.redirect_stderr(io.StringIO()) as err:
            d = S.ler_detalhe(html[:i] + html[j:], registro)
        self.assertEqual((d["frequencia"], d["layout_alterado"]), ([], []))
        self.assertIn("::warning::sessão 11896", err.getvalue())
        self.assertIn("sessão ordinaria sem frequência", err.getvalue())
        with contextlib.redirect_stderr(io.StringIO()) as err:  # especial sem frequência: normal
            S.ler_detalhe(pagina_detalhe(11800), {"id": 11800, "tipo": "especial"})
        self.assertEqual(err.getvalue(), "")

    def test_votacao_sem_link_fica_sem_id(self):
        html = pagina_detalhe(22399).replace('href="DetalhesDocumentos.aspx?IdDocumento=295535"', 'href="Outra.aspx"')
        d, err = detalhe_silencioso(html)
        v = d["votacoes"][0]
        self.assertEqual((v["id_documento"], v["documento"], v["tipo_documento"], v["numero"], v["ano"]),
                         (None, "Projeto de Lei Nº 00253/2026", "Projeto de Lei", "253/2026", 2026))
        self.assertEqual(len(v["votos"]), 21)
        self.assertIn("votação 1 sem link de documento reconhecido (gravada sem id, com o rótulo)", err)
        reg = S.aplicar_detalhe(registro_da_fixture(22399), d, "2026-10-23")
        self.assertEqual(validar.validar_sessao(reg, 2026, "data/sessoes/2026.json"), [])

    def test_totais_divergentes_e_rotulo_desconhecido_avisam(self):
        html = pagina_detalhe(22399).replace("Favor: <strong>17</strong>", "Favor: <strong>16</strong>")
        d, err = detalhe_silencioso(html)
        self.assertEqual(d["votacoes"][0]["totais"]["favor"], 16)  # o total da página fica como está
        self.assertIn("totais da página diferem da contagem dos votos (favor 16 ≠ 17)", err)
        html = pagina_detalhe(22399).replace("Nulo: <strong>0</strong>,", "Nulo: <strong>0</strong>, Obstrução: <strong>1</strong>,")
        d, err = detalhe_silencioso(html)
        self.assertIn("rótulo(s) de total desconhecido(s): Obstrução", err)
        self.assertEqual(set(d["votacoes"][0]["totais"]), set(S.CHAVES_TOTAIS))

    def test_votacao_nominal_sem_votos(self):
        html = pagina_detalhe(22399)
        i, j = html.index('id="trVotacoes"'), html.index('id="trFrequencia"')
        d, err = detalhe_silencioso(html[:i] + RE_LINHA_SIMPLES.sub("", html[i:j]) + html[j:])
        self.assertEqual([v["votos"] for v in d["votacoes"]], [[]])
        self.assertIn("sem totais ou sem votos reconhecidos", err)

    def test_pauta_sem_link_de_documento(self):
        # sem o link, o item fica sem id, mas com o rótulo do documento: avisa e não perde a linha
        html = pagina_detalhe(12029).replace("href='DetalhesDocumentos.aspx?IdDocumento=", "href='Outra.aspx?Id=")
        d, err = detalhe_silencioso(html)
        self.assertEqual(len(d["pauta"]), 35)
        self.assertEqual({p["id_documento"] for p in d["pauta"]}, {None})
        self.assertEqual((d["pauta"][0]["tipo_documento"], d["pauta"][0]["numero"], d["pauta"][0]["ano"]),
                         ("Projeto de Lei", "61/2023", 2023))
        self.assertIn("pauta 'Pauta': 35 de 35 linha(s) sem link de documento reconhecido", err)
        # sem id, o item gravado continua completo mesmo com todos os ids conhecidos
        self.assertEqual(S.enxugar_pauta(d["pauta"], {186777}), d["pauta"])

    def test_pauta_sem_rotulo_de_documento_e_descartada(self):
        html = pagina_detalhe(12029)
        i = html.index("<a href='DetalhesDocumentos.aspx?IdDocumento=186777'")
        j = html.index("</a>", i) + len("</a>")
        d, err = detalhe_silencioso(html[:i] + html[j:])  # a primeira linha fica sem link e sem rótulo
        self.assertEqual(len(d["pauta"]), 34)
        self.assertNotIn(186777, {p["id_documento"] for p in d["pauta"]})
        self.assertIn("1 de 35 linha(s) sem link de documento reconhecido (1 sem rótulo, descartada(s)", err)


class TestLerEAplicarDetalhe(unittest.TestCase):
    REGISTRO = {"id": 11850, "numero": 48, "tipo": "ordinaria", "data": "2021-08-04", "hora": "14:00"}

    def test_confere_a_sessao(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            d = S.ler_detalhe(pagina_detalhe(11850), dict(self.REGISTRO))
        self.assertEqual(len(d["votacoes"]), 4)
        self.assertEqual(err.getvalue(), "")

    def test_pagina_de_outra_sessao(self):
        with self.assertRaisesRegex(ValueError, "11850"):
            S.ler_detalhe(pagina_detalhe(11850), {**self.REGISTRO, "id": 11896})

    def test_pagina_sem_cabecalho(self):
        with self.assertRaises(ValueError):
            S.ler_detalhe("<html><body><p>Erro no servidor</p></body></html>", {"id": 1})

    def test_cabecalho_diferente_da_listagem_so_avisa(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            d = S.ler_detalhe(pagina_detalhe(11850), {**self.REGISTRO, "data": "2021-08-05"})
        self.assertEqual(d["data"], "2021-08-04")
        self.assertIn("difere da listagem", err.getvalue())

    def test_lista_que_veio_vazia_mantem_a_anterior(self):
        d, _ = detalhe_silencioso(pagina_detalhe(11896))  # sem votações
        anterior = {"id": 11896, "votacoes": [{"id_documento": 1}], "detalhe_pendente": True}
        with contextlib.redirect_stderr(io.StringIO()) as err:
            reg = S.aplicar_detalhe(anterior, d, "2026-10-22")
        self.assertEqual(reg["votacoes"], [{"id_documento": 1}])
        self.assertEqual(len(reg["frequencia"]), 21)
        self.assertEqual(reg["detalhe_em"], "2026-10-22")
        self.assertNotIn("detalhe_pendente", reg)
        self.assertNotIn("avisos", reg)
        self.assertNotIn("layout_alterado", reg)
        self.assertIn("'votacoes' veio vazia", err.getvalue())
        # o registro de entrada não é alterado: o chamador troca o antigo pelo novo de uma vez
        self.assertEqual(anterior, {"id": 11896, "votacoes": [{"id_documento": 1}], "detalhe_pendente": True})

    def test_detalhe_em_so_muda_quando_o_conteudo_muda(self):
        d, _ = detalhe_silencioso(pagina_detalhe(11850))
        primeiro = S.aplicar_detalhe({"id": 11850}, d, "2026-10-01")
        self.assertEqual(primeiro["detalhe_em"], "2026-10-01")
        mesmo = S.aplicar_detalhe({**primeiro, "detalhe_pendente": True}, d, "2026-10-08")
        self.assertEqual(mesmo, primeiro)  # rebaixado sem novidade: sem diff
        outro = S.aplicar_detalhe(primeiro, {**d, "observacoes": "EXTRAPAUTA: outra"}, "2026-10-08")
        self.assertEqual(outro["detalhe_em"], "2026-10-08")


class TestPautaEnxuta(unittest.TestCase):
    """A pauta guarda só a referência dos documentos já em data/; os ids conhecidos são injetados no teste."""

    COMPLETO = {"secao": "Pauta", "secao_indice": 0, "prioridade": "Ordinária", "fase": "Leitura", "id_documento": 1,
                "tipo_documento": "Indicação", "numero": "5/2024", "ano": 2024, "ementa": "Sugere a poda."}

    def test_enxugar_pauta(self):
        desconhecido = {**self.COMPLETO, "id_documento": 2}
        sem_id = {**self.COMPLETO, "id_documento": None}
        self.assertEqual(
            S.enxugar_pauta([self.COMPLETO, desconhecido, sem_id], frozenset({1})),
            [{"id_documento": 1, "fase": "Leitura", "prioridade": "Ordinária", "secao": "Pauta", "secao_indice": 0},
             desconhecido, sem_id],
        )
        self.assertEqual(S.enxugar_pauta([self.COMPLETO], frozenset()), [self.COMPLETO])

    def test_aplicar_detalhe_com_e_sem_id_conhecido(self):
        d, _ = detalhe_silencioso(pagina_detalhe(11850))
        conhecidos = frozenset(p["id_documento"] for p in d["pauta"]) - {130836}  # PL 271/2021 fica de fora
        reg = S.aplicar_detalhe({"id": 11850}, d, "2026-10-23", conhecidos)
        self.assertEqual(len(reg["pauta"]), 142)
        self.assertEqual(reg["pauta"][0], {"id_documento": 130695, "fase": "Leitura", "prioridade": "Ordinária",
                                           "secao": "Pauta", "secao_indice": 1})
        self.assertEqual(reg["pauta"][1], d["pauta"][1])  # id desconhecido: item completo
        self.assertEqual(reg["pauta"][1]["numero"], "271/2021")
        self.assertEqual([set(p) for p in reg["pauta"][2:]], [set(S.CAMPOS_PAUTA)] * 140)
        # as votações não são enxugadas
        self.assertEqual(reg["votacoes"][0]["documento"], "Projeto de Lei Nº 00002/2015")
        self.assertLess(len(json.dumps(reg["pauta"])), len(json.dumps(d["pauta"])) / 2)

    def test_ids_conhecidos(self):
        with tempfile.TemporaryDirectory() as tmp:
            dados = Path(tmp)
            (dados / "proposicoes").mkdir()
            (dados / "documentos" / "indicacao").mkdir(parents=True)
            (dados / "documentos" / "mocao").mkdir()
            # só o id de cada registro conta, não os de autores ou substitutivos
            (dados / "proposicoes" / "2024.json").write_text(
                json.dumps([{"id": 1, "autoria": [{"id": 99}], "substitutivos": [{"id": 7}]}]), encoding="utf-8")
            (dados / "documentos" / "indicacao" / "2024.json").write_text(
                json.dumps([{"id": 2, "autores": [{"id": 98}]}, {"id": True}]), encoding="utf-8")
            (dados / "documentos" / "mocao" / "2024.json").write_text("[{", encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(S.ids_conhecidos(dados), frozenset({1, 2}))
            self.assertIn("::warning::", err.getvalue())
            self.assertEqual(S.ids_conhecidos(dados / "inexistente"), frozenset())

    def preparar(self, tmp: str) -> Path:
        """data/sessoes/2023.json com a 29ª Ordinária de 2023 ainda sem detalhe."""
        pasta = Path(tmp) / "data" / "sessoes"
        reg = {"id": 12029, "titulo": "29ª Sessão Ordinária de 2023", "numero": 29, "tipo": "ordinaria",
               "tipo_texto": "Ordinária", "ano": 2023, "data": "2023-05-03", "hora": "16:00",
               "url": S.DETALHE_SESSAO.format(id=12029), "detalhe_pendente": True}
        S.salvar_ano(S.caminho_ano(2023, pasta), {12029: reg})
        return pasta

    def test_coletar_detalhes_le_os_ids_uma_vez_e_grava_a_pauta_enxuta(self):
        completa = detalhe_silencioso(pagina_detalhe(12029))[0]["pauta"]
        conhecidos = frozenset(p["id_documento"] for p in completa[1:])  # o PL 61/2023 (186777) não está em data/
        with tempfile.TemporaryDirectory() as tmp:
            pasta = self.preparar(tmp)
            baixar, _ = servidor({}, pagina_detalhe)
            with mock.patch.object(S, "baixar", baixar), \
                    mock.patch.object(S, "ids_conhecidos", return_value=conhecidos) as ler_ids, \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                resumo = S.coletar_detalhes([2023], 2, pasta, hoje="2026-10-23")
            ler_ids.assert_called_once_with(pasta.parent)
            bruto = S.caminho_ano(2023, pasta).read_bytes()
        self.assertEqual((resumo["baixados"], resumo["falhas"]), (1, 0))
        pauta = json.loads(bruto)[0]["pauta"]
        self.assertEqual(pauta[0], completa[0])
        self.assertEqual(pauta[0]["id_documento"], 186777)
        self.assertEqual(pauta[1], {"id_documento": 186776, "fase": "Leitura", "prioridade": "Ordinária",
                                    "secao": "Pauta", "secao_indice": 0})
        self.assertTrue(all(set(p) == set(S.CAMPOS_PAUTA) for p in pauta[1:]))
        self.assertEqual(validar.validar_arquivo_sessoes(bruto, 2023, "data/sessoes/2023.json", {}), [])

    def test_ids_injetados_e_sem_detalhe_a_baixar_nao_leem_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            pasta = self.preparar(tmp)
            baixar, _ = servidor({}, pagina_detalhe)
            with mock.patch.object(S, "baixar", baixar), mock.patch.object(S, "ids_conhecidos") as ler_ids, \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                S.coletar_detalhes([2023], 1, pasta, hoje="2026-10-23", conhecidos=frozenset({186777}))
                S.coletar_detalhes([2023], 1, pasta, hoje="2026-10-23")  # nada pendente
            ler_ids.assert_not_called()
            pauta = S.carregar_ano(S.caminho_ano(2023, pasta))[12029]["pauta"]
        self.assertEqual(set(pauta[0]), set(S.CAMPOS_PAUTA))
        self.assertTrue(all("ementa" in p for p in pauta[1:]))


class TestUtilidades(unittest.TestCase):
    def test_tipos_do_filtro_real(self):
        # as opções do filtro de tipo de sessão (ddlTipoSessao) da página Default.aspx?Exibir=Sessoes
        _, ids = S.arvore(ler("sessoes_default.html"))
        filtro = ids["consulta1_tabConsulta_tpSessoes_ddlTipoSessao"]
        opcoes = [o.texto() for o in filtro.buscar_todos(lambda n: n.tag == "option") if o.texto()]
        self.assertEqual(opcoes, ["AUDIÊNCIA PÚBLICA", "Especial", "Extraordinária", "Instalação", "Ordinária", "Solene"])
        self.assertEqual({S.normalizar(t) for t in opcoes}, set(S.TIPOS_SESSAO))
        self.assertNotIn(S.TIPO_DESCONHECIDO, S.TIPOS_SESSAO)

    def test_titulo(self):
        self.assertEqual(S.titulo_sessao("1ª Sessão AUDIÊNCIA PÚBLICA de 2023"),
                         {"numero": 1, "tipo_texto": "AUDIÊNCIA PÚBLICA", "ano": 2023})
        self.assertEqual(S.titulo_sessao("Sessão sem número"), {"numero": None, "tipo_texto": None, "ano": None})
        self.assertIsNone(S.titulo_sessao("0ª Sessão Ordinária de 2023")["numero"])  # o validador exige número ≥ 1

    def test_valores_que_o_validador_aceita(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertIsNone(S.data_calendario("31/02/2024 10:00"))
        self.assertIn("inválida", err.getvalue())
        self.assertEqual(S.data_calendario("29/02/2024 10:00"), "2024-02-29")
        self.assertEqual((S.hora("9:05"), S.hora("25:00"), S.hora("sem hora")), ("09:05", None, None))
        self.assertEqual(S.url_arquivo("Arquivos/Sessoes/ata 1.docx"),
                         "https://consultaniteroi.siscam.com.br/Arquivos/Sessoes/ata%201.docx")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertIsNone(S.url_arquivo("javascript:;"))
        self.assertEqual(S.referencia_texto(1, "Indicação Nº 00000/2024")["numero"], None)


# -------------------------------------------------------------------- incremental
INFO = {s["id"]: s for s in S.parse_listagem(ler(P1))[0] + S.parse_listagem(ler(P11))[0]}


def detalhe_simulado(id_sessao: int) -> str:
    """Detalhe real para 11800 e 11896; para as demais sessões listadas, o de 11896 com o id e o cabeçalho delas."""
    if id_sessao in (11800, 11896):
        return pagina_detalhe(id_sessao)
    s = INFO[id_sessao]
    cabecalho = f"{s['titulo']} - {dt.date.fromisoformat(s['data']):%d/%m/%Y} {s['hora']}"
    html = pagina_detalhe(11896).replace("IdDocumento=11896", f"IdDocumento={id_sessao}")
    return re.sub(r'(class="form-task">)[^<]*', lambda m: m.group(1) + cabecalho, html, count=1)


class TestIncremental(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.pasta = Path(tmp.name) / "data" / "sessoes"
        self.listagem: dict[int, object] = {1: ler(P1), 2: marcar_pagina(ler(P11), 2)}
        self.falhar: set[int] = set()
        self.stderr = ""

    def detalhe(self, id_sessao: int) -> object:
        return RuntimeError("SISCAM fora do ar") if id_sessao in self.falhar else detalhe_simulado(id_sessao)

    def rodar(self, hoje: str, **kwargs) -> tuple[dict, list[int]]:
        """Executa coletar() para 2021; devolve as estatísticas e os ids de sessão com detalhe pedido."""
        baixar, chamadas = servidor(self.listagem, self.detalhe)
        with mock.patch.object(S, "baixar", baixar), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            estat = S.coletar([2021], 2, pasta=self.pasta, hoje=hoje, **kwargs)
        self.stderr = err.getvalue()
        return estat, sorted(int(parse_qs(urlsplit(u).query)["IdDocumento"][0]) for u in chamadas if "DetalhesSessao" in u)

    def registros(self) -> dict[int, dict]:
        return S.carregar_ano(S.caminho_ano(2021, self.pasta))

    def bruto(self) -> bytes:
        return S.caminho_ano(2021, self.pasta).read_bytes()

    def test_limite_por_execucao_e_fila_de_pendentes(self):
        recentes = {11895, 11896, 11894, 11893, 11892}  # as cinco sessões mais recentes de 2021
        estat, pedidos = self.rodar("2022-06-01", max_detalhes=5)
        self.assertEqual(pedidos, sorted(recentes))
        regs = self.registros()
        self.assertEqual(set(regs), set(IDS_P1 + IDS_P11))
        self.assertEqual({i for i, r in regs.items() if r.get("detalhe_em") == "2022-06-01"}, recentes)
        self.assertEqual({i for i, r in regs.items() if r.get("detalhe_pendente")}, set(regs) - recentes)
        self.assertNotIn("pauta", regs[11800])  # sem detalhe: campos ausentes, não listas vazias
        self.assertEqual(estat["detalhes"], {"limite": 5, "baixados": 5, "falhas": 0, "pendentes": 7, "fila": 12})
        self.assertEqual(estat["anos"]["2021"]["listado"], 12)
        # as contagens de detalhe também por ano, depois dos detalhes (não as da listagem)
        self.assertEqual({k: v for k, v in estat["anos"]["2021"].items() if k.startswith("detalhes_")},
                         {"detalhes_baixados": 5, "detalhes_falhas": 0, "detalhes_pendentes": 7})
        self.assertNotIn("pendentes", estat["anos"]["2021"])
        self.assertEqual(validar.validar_arquivo_sessoes(self.bruto(), 2021, "data/sessoes/2021.json", {}), [])
        _, pedidos = self.rodar("2022-06-01")
        self.assertEqual(pedidos, sorted(set(regs) - recentes))
        self.assertFalse(any(r.get("detalhe_pendente") for r in self.registros().values()))
        self.assertEqual(self.rodar("2022-06-01")[1], [])
        self.assertEqual(validar.validar_arquivo_sessoes(self.bruto(), 2021, "data/sessoes/2021.json", {}), [])

    def test_sessoes_recentes_sao_rebaixadas(self):
        self.assertEqual(len(self.rodar("2021-12-23")[1]), 12)
        self.assertEqual(self.rodar("2021-12-23")[1], [])  # detalhe já baixado hoje, depois do dia da sessão
        self.assertEqual(self.rodar("2021-12-30")[1], sorted(IDS_P1))  # dezembro: dentro da janela de 60 dias
        self.assertEqual(self.rodar("2022-06-01")[1], [])

    def test_forcar_rebaixa_todas(self):
        self.rodar("2022-06-01")
        self.assertEqual(len(self.rodar("2022-06-02", forcar=True)[1]), 12)

    def test_falha_no_detalhe_mantem_o_anterior_e_fica_pendente(self):
        self.rodar("2022-06-01")
        antes = self.registros()[11896]
        self.falhar = {11896}
        estat, pedidos = self.rodar("2022-07-01", forcar=True)
        self.assertEqual(len(pedidos), 12)
        self.assertEqual((estat["detalhes"]["baixados"], estat["detalhes"]["falhas"]), (11, 1))
        depois = self.registros()
        self.assertIs(depois[11896]["detalhe_pendente"], True)
        self.assertEqual({k: v for k, v in depois[11896].items() if k != "detalhe_pendente"}, antes)
        self.assertEqual(depois[11895]["detalhe_em"], "2022-06-01")  # rebaixado sem mudança: detalhe_em não muda
        self.assertEqual(estat["anos"]["2021"]["detalhes_falhas"], 1)
        self.falhar = set()
        self.assertEqual(self.rodar("2022-07-01")[1], [11896])
        self.assertNotIn("detalhe_pendente", self.registros()[11896])

    def test_layout_alterado_deixa_a_sessao_pendente(self):
        self.rodar("2022-06-01")
        antes = self.registros()[11896]
        original = self.detalhe
        self.detalhe = lambda i: original(i).replace('id="trFrequencia"', 'id="trPresencas"') if i == 11896 else original(i)
        estat, pedidos = self.rodar("2022-07-01", forcar=True)
        self.assertIn(11896, pedidos)
        self.assertEqual(estat["detalhes"]["falhas"], 1)
        self.assertIn("layout do SISCAM alterado (seção [ Frequência ] na página sem a linha trFrequencia)", self.stderr)
        depois = self.registros()[11896]
        self.assertIs(depois["detalhe_pendente"], True)  # não gravada como detalhada com a frequência vazia
        self.assertEqual({k: v for k, v in depois.items() if k != "detalhe_pendente"}, antes)
        self.assertEqual(validar.validar_arquivo_sessoes(self.bruto(), 2021, "data/sessoes/2021.json", {}), [])

    def test_titulo_de_outro_ano_e_sessao_sem_tipo_ficam_validos(self):
        # título de 2020 na listagem de 2021 e um bloco sem tipo: gravados no ano da listagem, com aviso
        p11 = marcar_pagina(ler(P11), 2).replace("1ª Sessão Ordinária de 2021", "1ª Sessão Ordinária de 2020")
        p11 = p11.replace("<strong>Tipo: </strong>Especial", "<strong>Tipo: </strong>")
        p11 = p11.replace(">1ª Sessão Especial de 2021<", ">Sessão de posse<")
        self.listagem = {1: ler(P1), 2: p11}
        estat, _ = self.rodar("2022-06-01", max_detalhes=0)
        regs = self.registros()
        self.assertEqual((regs[11789]["ano"], regs[11789]["titulo"]), (2021, "1ª Sessão Ordinária de 2020"))
        self.assertEqual((regs[11800]["tipo"], regs[11800]["tipo_texto"], regs[11800]["numero"]), ("desconhecido", "", None))
        self.assertIn("listada em 2021, mas o título é de 2020", self.stderr)
        self.assertIn("gravada como 'desconhecido'", self.stderr)
        self.assertEqual(validar.validar_arquivo_sessoes(self.bruto(), 2021, "data/sessoes/2021.json", {}), [])

    def test_listagem_com_falha_mantem_o_arquivo(self):
        self.rodar("2022-06-01")
        antes = self.bruto()
        self.listagem = {1: RuntimeError("SISCAM fora do ar")}
        estat, pedidos = self.rodar("2022-06-01")
        self.assertEqual(self.bruto(), antes)
        self.assertEqual(pedidos, [])
        self.assertEqual((estat["anos"]["2021"]["gravado"], estat["anos"]["2021"]["falhas"]), (False, 1))
        self.assertIn("::warning::sessões 2021: falha na listagem", self.stderr)

    def test_listagem_menor_preserva_as_sessoes_anteriores(self):
        self.rodar("2022-06-01")
        self.listagem = {1: marcar_pagina(ler(P11), 1)}  # só as 2 sessões de janeiro
        estat, pedidos = self.rodar("2022-06-01")
        self.assertEqual(set(self.registros()), set(IDS_P1 + IDS_P11))
        self.assertEqual((estat["anos"]["2021"]["listado"], estat["anos"]["2021"]["preservados"]), (2, 10))
        self.assertIn("não aparecem na listagem", self.stderr)
        self.assertEqual(pedidos, [])

    def test_regravacao_deterministica_e_ordem(self):
        self.rodar("2022-06-01")
        antes = self.bruto()
        self.rodar("2022-06-01")
        self.assertEqual(self.bruto(), antes)
        self.assertNotIn(b"\r", antes)
        self.assertTrue(antes.startswith(b"[\n{") and antes.endswith(b"}\n]\n"))
        ids = [r["id"] for r in json.loads(antes)]
        self.assertEqual(ids[:2], [11800, 11789])  # data, hora, número e id
        self.assertEqual(ids[-2:], [11896, 11895])  # 22/12/2021: 14:00 antes de 15:00


# ----------------------------------------------------------------------- gravação
def registro_da_fixture(id_sessao: int) -> dict:
    d, _ = detalhe_silencioso(pagina_detalhe(id_sessao))
    reg = {k: d[k] for k in ("titulo", "numero", "tipo", "tipo_texto", "ano", "data", "hora")}
    reg.update(id=id_sessao, url=S.DETALHE_SESSAO.format(id=id_sessao))
    return S.aplicar_detalhe(reg, d, "2026-10-22")


class TestGravacao(unittest.TestCase):
    def test_gravacao_deterministica_e_valida(self):
        por_ano: dict[int, dict[int, dict]] = defaultdict(dict)
        for id_sessao in FIXTURES_DETALHE:
            reg = registro_da_fixture(id_sessao)
            por_ano[reg["ano"]][id_sessao] = reg
        self.assertEqual(sorted(por_ano), [2021, 2023, 2024, 2025, 2026])
        with tempfile.TemporaryDirectory() as tmp:
            pasta = Path(tmp) / "data" / "sessoes"
            for ano, regs in por_ano.items():
                caminho = S.caminho_ano(ano, pasta)
                itens = list(regs.items())
                random.Random(ano).shuffle(itens)
                S.salvar_ano(caminho, dict(itens))
                primeiro = caminho.read_bytes()
                S.salvar_ano(caminho, dict(reversed(itens)))
                self.assertEqual(caminho.read_bytes(), primeiro)
                self.assertEqual(json.loads(primeiro), sorted(regs.values(), key=S.chave_arquivo))
            self.assertEqual(validar.validar_sessoes(Path(tmp)), [])

    def test_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "meta.json"
            caminho.write_text(json.dumps({"coleta": {"x": 1}, "sessoes": {"anos": {"2020": {"listado": 5}}}}),
                               encoding="utf-8")
            S.atualizar_meta({"anos": {"2021": {"listado": 102}}, "detalhes": {"baixados": 3},
                              "interrompido": "KeyboardInterrupt"}, caminho)
            dados = json.loads(caminho.read_text(encoding="utf-8"))
        self.assertEqual(dados["coleta"], {"x": 1})
        self.assertEqual(dados["sessoes"]["anos"], {"2020": {"listado": 5}, "2021": {"listado": 102}})
        self.assertEqual(dados["sessoes"]["detalhes"], {"baixados": 3})
        self.assertEqual(dados["sessoes"]["interrompido"], "KeyboardInterrupt")
        self.assertEqual(validar.validar_meta(dados), [])

    def test_meta_ano_so_com_detalhes_mantem_a_ultima_listagem(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "meta.json"
            caminho.write_text(json.dumps({"sessoes": {"anos": {"2020": {"listado": 5, "detalhes_pendentes": 3}}}}),
                               encoding="utf-8")
            contagem = {"detalhes_baixados": 2, "detalhes_falhas": 0, "detalhes_pendentes": 1}
            dados = S.atualizar_meta({"anos": {"2020": contagem}}, caminho)
        self.assertEqual(dados["sessoes"]["anos"]["2020"], {"listado": 5, **contagem})


class TestValidarSessoes(unittest.TestCase):
    def setUp(self):
        self.reg = registro_da_fixture(11850)

    def problemas(self, reg: dict) -> list[str]:
        return validar.validar_sessao(reg, 2021, "data/sessoes/2021.json")

    def assertProblema(self, problemas: list[str], trecho: str) -> None:
        self.assertTrue(any(trecho in p for p in problemas), f"{trecho!r} não está em {problemas}")

    def test_registro_valido(self):
        self.assertEqual(self.problemas(self.reg), [])
        sem_detalhe = {k: v for k, v in self.reg.items() if k not in S.CAMPOS_DETALHE}
        self.assertEqual(self.problemas({**sem_detalhe, "detalhe_pendente": True}), [])

    def test_campos_invalidos(self):
        self.assertProblema(self.problemas({**self.reg, "tipo": "Ordinária"}), "'tipo'")
        self.assertProblema(self.problemas({**self.reg, "hora": "14h"}), "'hora'")
        self.assertProblema(self.problemas({**self.reg, "ano": 2022}), "difere do ano do arquivo")
        self.assertProblema(self.problemas({**self.reg, "detalhe_pendente": False}), "'detalhe_pendente'")
        sem_detalhe = {k: v for k, v in self.reg.items() if k not in S.CAMPOS_DETALHE}
        self.assertProblema(self.problemas(sem_detalhe), "sem 'detalhe_em' e sem 'detalhe_pendente'")
        votacao = {**self.reg["votacoes"][0], "totais": {"favor": 1}}
        self.assertProblema(self.problemas({**self.reg, "votacoes": [votacao]}), "'totais'")
        item = {**self.reg["pauta"][0], "numero": "00268/2021"}
        self.assertProblema(self.problemas({**self.reg, "pauta": [item]}), "fora do formato <n>/<ano>")
        self.assertProblema(self.problemas({**self.reg, "frequencia": [{"nome": "", "situacao": "Presença"}]}),
                            "'nome' ausente ou vazio")

    def test_pauta_enxuta(self):
        d, _ = detalhe_silencioso(pagina_detalhe(11850))
        conhecidos = frozenset(p["id_documento"] for p in d["pauta"]) - {130836}
        enxuto = S.aplicar_detalhe({k: v for k, v in self.reg.items() if k not in S.CAMPOS_DETALHE}, d, "2026-10-23",
                                   conhecidos)
        self.assertEqual(self.problemas(enxuto), [])  # referência para os conhecidos, item completo para 130836
        referencia = enxuto["pauta"][0]
        self.assertProblema(self.problemas({**enxuto, "pauta": [{**referencia, "id_documento": None}]}),
                            "item sem 'id_documento' precisa de tipo_documento, numero, ano, ementa")
        self.assertProblema(self.problemas({**enxuto, "pauta": [{**referencia, "ementa": "x"}]}), "deveriam vir juntos")
        self.assertProblema(self.problemas({**enxuto, "pauta": [{**referencia, "documento": "x"}]}),
                            "chave(s) inesperada(s) documento")
        self.assertProblema(self.problemas({**enxuto, "pauta": [{k: v for k, v in referencia.items() if k != "fase"}]}),
                            "'fase' ausente")
        sem_id = {**d["pauta"][0], "id_documento": None}  # linha sem link: completa e sem id
        self.assertEqual(self.problemas({**enxuto, "pauta": [sem_id]}), [])
        self.assertProblema(self.problemas({**enxuto, "pauta": [{**referencia, "id_documento": "130695"}]}),
                            "'id_documento' deveria ser inteiro ou null")
        votacao = {k: v for k, v in enxuto["votacoes"][0].items() if k != "id_documento"}
        self.assertProblema(self.problemas({**enxuto, "votacoes": [votacao]}), "'id_documento' deveria ser inteiro ou null")
        self.assertEqual(self.problemas({**enxuto, "votacoes": [{**votacao, "id_documento": None}]}), [])  # sem link

    def test_secao_indice_nomes_repetidos_e_ano(self):
        item = self.reg["pauta"][0]  # Pauta, a 2ª entrada de documentos_sessao
        self.assertEqual(item["secao_indice"], 1)
        self.assertEqual(self.problemas({**self.reg, "pauta": [{k: v for k, v in item.items() if k != "secao_indice"}]}), [])
        self.assertProblema(self.problemas({**self.reg, "pauta": [{**item, "secao_indice": 0}]}),
                            "aponta para um documento de outro rótulo")
        self.assertProblema(self.problemas({**self.reg, "pauta": [{**item, "secao_indice": 9}]}),
                            "não é a posição de um documento da sessão")
        votacao = self.reg["votacoes"][0]
        self.assertEqual(self.problemas({**self.reg, "votacoes": [{**votacao, "nomes_repetidos": ["DADO FOLY"]}]}), [])
        self.assertProblema(self.problemas({**self.reg, "votacoes": [{**votacao, "nomes_repetidos": []}]}),
                            "'nomes_repetidos' deveria ser uma lista não vazia")
        self.assertEqual(self.problemas({**self.reg, "frequencia_nomes_repetidos": ["DADO FOLY"]}), [])
        self.assertProblema(self.problemas({**self.reg, "frequencia_nomes_repetidos": "DADO FOLY"}),
                            "'frequencia_nomes_repetidos' deveria ser uma lista")
        self.assertProblema(self.problemas({**self.reg, "ano": None}), "difere do ano do arquivo")

    def test_formato_e_ids_repetidos(self):
        bruto = texto_lista([self.reg]).encode("utf-8")
        self.assertEqual(validar.validar_arquivo_sessoes(bruto, 2021, "a", {}), [])
        self.assertProblema(validar.validar_arquivo_sessoes(bruto.replace(b"\n", b"\r\n"), 2021, "a", {}),
                            "fora do formato gravado por coletor.sessoes")
        self.assertProblema(validar.validar_arquivo_sessoes(bruto, 2021, "b", {11850: "a"}), "sessão 11850 repetida")

    def test_pasta_opcional_e_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(validar.validar_sessoes(Path(tmp)), [])
            pasta = Path(tmp) / "data" / "sessoes"
            pasta.mkdir(parents=True)
            (pasta / "x.json").write_text("[]\n", encoding="utf-8")
            self.assertProblema(validar.validar_sessoes(Path(tmp)), "nome de arquivo deveria ser <ano>.json")
        self.assertProblema(validar.validar_meta({"sessoes": []}), "'sessoes' deveria ser um objeto com o mapa 'anos'")


# --------------------------------------------------------------------------- CLI
class TestMain(unittest.TestCase):
    def test_repassa_os_argumentos(self):
        chamadas = []

        def coletar(anos, workers, **kw):
            chamadas.append((anos, workers, kw))
            kw["estat"]["anos"]["2021"] = {"listado": 1, "falhas": 0}
            kw["estat"]["detalhes"] = {"baixados": 0, "falhas": 0}
            return kw["estat"]

        argv = ["sessoes", "--anos", "2021-2022", "--workers", "2", "--max-detalhes", "7", "--forcar"]
        with mock.patch.object(S, "coletar", coletar), mock.patch.object(S, "atualizar_meta") as meta, \
                mock.patch.object(S.signal, "signal"), mock.patch("sys.argv", argv), \
                contextlib.redirect_stdout(io.StringIO()):
            S.main()
        anos, workers, kw = chamadas[0]
        self.assertEqual((anos, workers), ([2021, 2022], 2))
        self.assertEqual((kw["max_detalhes"], kw["forcar"], kw["prazo"]), (7, True, None))
        meta.assert_called_once()

    def test_argumentos_invalidos(self):
        for argv in (["sessoes", "--max-detalhes", "-1"], ["sessoes", "--anos", "2026-2025"], ["sessoes", "--max-minutos", "0"]):
            with self.subTest(argv=argv), mock.patch("sys.argv", argv), contextlib.redirect_stderr(io.StringIO()), \
                    self.assertRaises(SystemExit):
                S.main()


# ------------------------------------------------------------ ids dos documentos
class TestIdsDosDocumentos(unittest.TestCase):
    """O IdDocumento da pauta e das votações é o mesmo id de data/proposicoes e data/documentos."""

    def test_fixtures_contra_os_dados_versionados(self):
        if os.environ.get("RADAR_COLETA") == "1":
            self.skipTest("coleta semanal: os dados recém-coletados podem divergir das fixtures")
        conhecidos: dict[int, tuple[str, str]] = {}
        for arq in sorted((RAIZ / "data" / "proposicoes").glob("*.json")):
            for p in json.loads(arq.read_text(encoding="utf-8")):
                conhecidos[p["id"]] = ("Projeto de Lei", p["numero"])
        for tipo, rotulo in documentos.ROTULOS.items():
            arq = RAIZ / "data" / "documentos" / tipo / "2026.json"
            if arq.exists():
                for d in json.loads(arq.read_text(encoding="utf-8")):
                    conhecidos[d["id"]] = (rotulo, d["numero"])
        if not conhecidos:
            self.skipTest("sem data/proposicoes nem data/documentos")
        itens = []
        for id_sessao in FIXTURES_DETALHE:
            d, _ = detalhe_silencioso(pagina_detalhe(id_sessao))
            itens += d["pauta"] + d["votacoes"]
        cruzados = [i for i in itens if i["id_documento"] in conhecidos]
        self.assertGreater(len(cruzados), 0)
        divergentes = [
            (i["id_documento"], i["tipo_documento"], i["numero"], conhecidos[i["id_documento"]])
            for i in cruzados
            if conhecidos[i["id_documento"]] != (i["tipo_documento"], i["numero"])
        ]
        self.assertEqual(divergentes, [])
        for id_doc, esperado in ((295535, ("Projeto de Lei", "253/2026")), (280671, ("Projeto de Lei", "280/2025"))):
            if id_doc in conhecidos:
                self.assertEqual(conhecidos[id_doc], esperado)


if __name__ == "__main__":
    unittest.main()
