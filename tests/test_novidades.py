"""Novidades da semana e feed RSS: eventos derivados só das datas dos dados, sem rede nem relógio."""
from __future__ import annotations

import json
import os
import random
import re
import unittest
from datetime import date
from unittest import mock
from xml.etree import ElementTree

from coletor import novidades as N
from coletor.siscam import derivar_lei, parse_detalhe
from coletor.site import paginas as P
from tests.apoio import RAIZ, ler_fixture, registro_versionado

URL = "https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento={}"


def projeto(id_doc: int, numero: str, data: str | None, **extra) -> dict:
    """Projeto já enriquecido, só com os campos que novidades.py e a página usam."""
    return {
        "id": id_doc, "numero": numero, "ano": int(numero.split("/")[1]), "data": data,
        "ementa": "Dispõe sobre a coleta seletiva", "resumo": "", "desfecho": "em_tramitacao", "lei": None,
        "lei_substitutivo": None, "marcos": [], "url": URL.format(id_doc), "partido": "PX", "principal": "ana-teste",
        "autores": [{"nome": "ANA TESTE", "exibicao": "Ana Teste", "slug": "ana-teste", "vereador": True, "papel": "Autor"}],
        **extra,
    }


def passo(seq: int, resultado: str, data_resposta: str | None, observacao: str = "", destinatario: str = "Axel Grael",
          objetivo: str = "Sancionar / Vetar Lei", enviado: str | None = None) -> dict:
    return {"seq": seq, "remetente": "Secretaria Mesa Diretora", "destinatario": destinatario, "objetivo": objetivo,
            "enviado": enviado or data_resposta, "complemento": "", "resultado": resultado,
            "data_resposta": data_resposta, "observacao": observacao}


class SemRelogio(date):
    """date que falha se alguém consultar o dia de hoje."""

    @classmethod
    def today(cls):
        raise AssertionError("novidades.py não pode depender do relógio")


# ---------------------------------------------------------------------- marcos
class TestMarcosTramitacao(unittest.TestCase):
    def test_veto_total_e_derrubada_no_substitutivo_real(self):
        # Substitutivo ao PL 140/2021: vetado em 27/06/2024, veto derrubado em plenário em 30/07/2024,
        # lei promulgada em 12/09/2024 (o passo da promulgação repete "REJEIÇÃO DO VETO", mas não conta).
        detalhe = parse_detalhe(ler_fixture("siscam", "detalhe_substitutivo_266596.html"))
        lei = derivar_lei(detalhe["tramitacoes"])  # como em coletar_substitutivos: a confirmação estrutural
        self.assertEqual(lei["tipo"], "veto_derrubado")
        substitutivo = {"id": 266596, "situacao": detalhe["situacao"], "tramitacoes": detalhe["tramitacoes"], "lei": lei}
        registro = {"id": 127858, "situacao": "Apensado", "tramitacoes": [], "substitutivos": [substitutivo]}
        self.assertEqual(N.marcos_tramitacao(registro), [
            {"tipo": "veto", "data": "2024-06-27", "alcance": "total", "substitutivo": 266596},
            {"tipo": "veto_derrubado", "data": "2024-07-30", "substitutivo": 266596},
        ])
        # A mesma tramitação no próprio PL: sem substitutivo.
        self.assertEqual([m["substitutivo"] for m in N.marcos_tramitacao({"tramitacoes": detalhe["tramitacoes"], "lei": lei})],
                         [None, None])
        # Sem confirmação no documento (situação ou lei), o texto do passo não basta: fica só o veto.
        sem_confirmacao = {"situacao": detalhe["situacao"], "tramitacoes": detalhe["tramitacoes"]}
        self.assertEqual([m["tipo"] for m in N.marcos_tramitacao(sem_confirmacao)], ["veto"])

    def test_lei_sancionada_sem_veto_nao_gera_marco(self):
        detalhe = parse_detalhe(ler_fixture("siscam", "detalhe_pl_275545.html"))
        self.assertTrue(detalhe["tramitacoes"])
        self.assertEqual(N.marcos_tramitacao({"tramitacoes": detalhe["tramitacoes"], "substitutivos": []}), [])

    def test_alcance_do_veto(self):
        casos = [
            ({"tramitacoes": [passo(1, "Veto Parcial", "2026-05-12")]}, "parcial"),
            ({"tramitacoes": [passo(1, "Vetado", "2026-05-12", "RECEBIDO COM AS RAZÕES DO VETO TOTAL")]}, "total"),
            ({"situacao": "VETO MANTIDO", "tramitacoes": [passo(1, "Vetado", "2026-05-12")]}, "total"),
            ({"situacao": "PUBLICADO", "lei": {"veto_parcial": True}, "tramitacoes": [passo(1, "Vetado", "2026-05-12")]}, "parcial"),
            ({"situacao": "EM TRAMITAÇÃO", "tramitacoes": [passo(1, "Vetado", "2026-05-12")]}, None),
        ]
        for registro, alcance in casos:
            with self.subTest(registro=registro):
                self.assertEqual(N.marcos_tramitacao(registro),
                                 [{"tipo": "veto", "data": "2026-05-12", "alcance": alcance, "substitutivo": None}])

    def test_passos_que_nao_sao_veto_nem_derrubada(self):
        ccj = "Comissão Permanente de Constituição e Justiça e Redação Final"
        plenario = {"destinatario": "Plenário", "objetivo": "Ordem do Dia - Discussão Única"}
        # Situação que confirmaria a derrubada: o que barra cada passo é a própria regra do texto.
        registro = {"situacao": "VETO REJEITADO", "tramitacoes": [
            passo(1, "Vetado", None),  # sem Data Resposta: não há data confiável do veto
            passo(2, "Manutenção ao Veto", "2026-06-01", destinatario=ccj, objetivo="Exarar Parecer"),
            passo(3, "Rejeição ao Veto", "2026-06-02", destinatario=ccj, objetivo="Exarar Parecer"),  # parecer, não votação
            passo(4, "Lido na Sessão Plenária", "2026-06-03", "VETO TOTAL", destinatario="Plenário", objetivo="Leitura"),
            passo(5, "Aprovado em Discussão Única", "2026-06-04", "REJEITADO O PARECER DA CCJ PELA MANUTENÇÃO DO VETO",
                  destinatario="Plenário", objetivo="Ordem do Dia - Discussão Única"),
            passo(6, "PROMULGADO", "2026-07-01", "TENDO EM VISTA A REJEIÇÃO DO VETO TOTAL, PROMULGA A LEI",
                  objetivo="VETO DERRUBADO"),
            passo(7, "Veto Mantido", "2026-06-05", **plenario),
            # Votos pela derrubada não são a derrubada (veto mantido em PLs reais como 36/2024 e 5/2025).
            passo(8, "Aprovado em Discussão Única", "2026-06-06",
                  "APROVADO O PARECER PELA MANUTENÇÃO DO VETO TOTAL, COM 11 VOTOS FAVORÁVEIS E 8 VOTOS PELA DERRUBADA DO VETO. "
                  "MANTIDO O VETO TOTAL EM DISCUSSÃO ÚNICA.", **plenario),
            passo(9, "Aprovado em Discussão Única", "2026-06-07", "6 VOTOS FAVORÁVEIS À DERRUBADA DO VETO", **plenario),
            passo(10, "Aprovado em Discussão Única", "2026-06-08", "VOTOS PARA A REJEIÇÃO DO VETO E A FAVOR DA DERRUBADA DO VETO",
                  **plenario),
            passo(11, "Aprovado em Discussão Única", "2026-06-09", "8 VOTOS CONTRÁRIOS À DERRUBADA DO VETO", **plenario),
        ]}
        self.assertEqual(N.marcos_tramitacao(registro), [])

    def test_derrubada_exige_confirmacao_no_documento(self):
        derrubada = passo(2, "Aprovado em Discussão Única", "2026-06-10", "DERRUBADO O VETO TOTAL EM DISCUSSÃO ÚNICA.",
                          destinatario="Plenário", objetivo="Ordem do Dia - Discussão Única")
        casos = [
            ({"situacao": "VETO REJEITADO"}, True),
            ({"situacao": "VETO DERRUBADO"}, True),
            ({"situacao": "PUBLICADO", "lei": {"tipo": "veto_derrubado"}}, True),
            ({"situacao": "VETO MANTIDO"}, False),
            ({"situacao": "VETO MANTIDO", "lei": {"tipo": "veto_derrubado"}}, False),  # contraditório: veto mantido vence
            ({"situacao": "Arquivado", "desfecho": "vetado"}, False),
            ({"situacao": "EM TRAMITAÇÃO", "lei": None}, False),
            ({"situacao": "PUBLICADO", "lei": {"tipo": "sancionada"}}, False),
        ]
        for documento, confirmada in casos:
            with self.subTest(documento=documento):
                self.assertIs(N.confirma_derrubada(documento), confirmada)
                registro = {**documento, "tramitacoes": [passo(1, "Vetado", "2026-05-12"), derrubada]}
                tipos = [m["tipo"] for m in N.marcos_tramitacao(registro)]
                self.assertEqual(tipos, ["veto", "veto_derrubado"] if confirmada else ["veto"])
        # A confirmação vale para o documento cujo passo casou: a do PL não empresta para o substitutivo.
        registro = {"situacao": "VETO REJEITADO", "tramitacoes": [],
                    "substitutivos": [{"id": 9, "situacao": "RECEBIDO PELA SMD", "lei": None, "tramitacoes": [derrubada]}]}
        self.assertEqual(N.marcos_tramitacao(registro), [])

    def test_registra_derrubada(self):
        self.assertTrue(N.registra_derrubada("COM 5 VOTOS PELA DERRUBADA DO VETO. DERRUBADO O VETO TOTAL."))
        self.assertTrue(N.registra_derrubada("VETO TOTAL FOI REJEITADO"))
        self.assertFalse(N.registra_derrubada("COM 5 VOTOS PELA DERRUBADA DO VETO. MANTIDO O VETO TOTAL."))
        self.assertFalse(N.registra_derrubada("VOTOS FAVORAVEIS A DERRUBADA DO VETO"))

    def test_um_marco_de_cada_tipo_o_mais_antigo_e_o_do_pl_no_empate(self):
        plenario = {"destinatario": "Plenário", "objetivo": "Ordem do Dia - Discussão Única"}
        registro = {
            "situacao": "VETO REJEITADO",
            "tramitacoes": [passo(1, "Vetado", "2026-05-12"), passo(2, "Veto Rejeitado", None, enviado="2026-06-10", **plenario)],
            "substitutivos": [{"id": 9, "situacao": "VETO REJEITADO",
                               "tramitacoes": [passo(1, "Vetado", "2026-05-12"), passo(2, "Vetado", "2026-04-01"),
                                               passo(3, "Veto Rejeitado", "2026-06-20", **plenario)]}],
        }
        self.assertEqual(N.marcos_tramitacao(registro), [
            {"tipo": "veto", "data": "2026-04-01", "alcance": None, "substitutivo": 9},
            {"tipo": "veto_derrubado", "data": "2026-06-10", "substitutivo": None},  # sem Data Resposta: Enviado em
        ])
        registro["substitutivos"][0]["tramitacoes"].pop(1)
        self.assertIsNone(N.marcos_tramitacao(registro)[0]["substitutivo"])


def e_plenario(t: dict) -> bool:
    return bool(N.RE_PLENARIO.search(f"{t.get('destinatario') or ''} {t.get('objetivo') or ''}"))


class TestVetoMantidoNosDadosVersionados(unittest.TestCase):
    """Regressão: votos "pela derrubada do veto" em PLs cujo veto foi mantido não são derrubada.

    Os registros vêm de data/proposicoes/<ano>.json com o texto exato das observações; com RADAR_COLETA=1
    (coleta semanal) registro_versionado devolve None e o teste é pulado, como os demais que dependem dos dados.
    """

    CASOS = ((2024, 266876, "36/2024"), (2024, 268946, "96/2024"), (2025, 275593, "5/2025"), (2021, 126459, "57/2021"))

    def test_pls_com_veto_mantido_nao_geram_derrubada(self):
        for ano, id_doc, numero in self.CASOS:
            with self.subTest(pl=numero):
                registro = registro_versionado(ano, id_doc)
                if registro is None:
                    self.skipTest(f"PL {numero} ausente de data/proposicoes/{ano}.json ou RADAR_COLETA=1")
                self.assertEqual((registro["numero"], registro["situacao"], registro["desfecho"], registro["lei"]),
                                 (numero, "VETO MANTIDO", "vetado", None))
                # O texto de algum passo de plenário casa com RE_DERRUBADA: era o falso positivo da regra antiga.
                self.assertTrue(any(N.RE_DERRUBADA.search(f"{t.get('resultado') or ''} {t.get('observacao') or ''}")
                                    and e_plenario(t) for t in registro["tramitacoes"]))
                self.assertFalse(N.confirma_derrubada(registro))
                self.assertNotIn("veto_derrubado", [m["tipo"] for m in N.marcos_tramitacao(registro)])

    @unittest.skipIf(os.environ.get("RADAR_COLETA") == "1", "dados recém-coletados podem divergir dos versionados")
    def test_nenhum_pl_com_veto_mantido_gera_derrubada(self):
        arquivos = sorted((RAIZ / "data" / "proposicoes").glob("*.json"))
        if not arquivos:
            self.skipTest("sem data/proposicoes")
        mantidos = 0
        for arq in arquivos:
            for p in json.loads(arq.read_text(encoding="utf-8")):
                if "VETO MANTIDO" not in (p.get("situacao") or "").upper() and p.get("desfecho") != "vetado":
                    continue
                mantidos += 1
                with self.subTest(pl=p.get("numero")):
                    self.assertNotIn("veto_derrubado", [m["tipo"] for m in N.marcos_tramitacao(p)])
        self.assertGreater(mantidos, 0)


# --------------------------------------------------------------------- eventos
class TestEventos(unittest.TestCase):
    def setUp(self):
        self.lei = projeto(1, "140/2021", "2021-04-21", desfecho="virou_lei", lei_substitutivo=266596,
                           lei={"numero": 3958, "data": "2024-09-12", "tipo": "veto_derrubado", "veto_parcial": False},
                           marcos=[{"tipo": "veto", "data": "2024-06-27", "alcance": "total", "substitutivo": 266596},
                                   {"tipo": "veto_derrubado", "data": "2024-07-30", "substitutivo": 266596}])
        self.novo = projeto(2, "300/2024", "2024-09-12")
        self.sem_data = projeto(3, "1/2024", None, desfecho="virou_lei", lei={"numero": 4000, "data": None})

    def test_cada_tipo_sai_do_seu_campo(self):
        eventos = N.derivar_eventos([self.novo, self.lei, self.sem_data])
        self.assertEqual([(e["tipo"], e["projeto"]["id"], e["data"], e["substitutivo"]) for e in eventos], [
            ("lei", 1, "2024-09-12", 266596),       # lei.data, com o substitutivo de onde saiu a lei
            ("apresentado", 2, "2024-09-12", None),  # data; no mesmo dia, a lei vem antes
            ("veto_derrubado", 1, "2024-07-30", 266596),
            ("veto", 1, "2024-06-27", 266596),
            ("apresentado", 1, "2021-04-21", None),
        ])
        self.assertEqual(eventos[3]["alcance"], "total")

    def test_lei_so_com_desfecho_e_data(self):
        aguardando = projeto(4, "2/2024", None, desfecho="aprovado_aguardando_sancao", lei={"numero": 1, "data": "2024-01-02"})
        self.assertEqual(N.derivar_eventos([aguardando, self.sem_data]), [])

    def test_datas_invalidas_e_posteriores_a_coleta_ficam_de_fora(self):
        futuro = projeto(5, "3/2024", "2062-01-01")
        torto = projeto(6, "4/2024", "12/09/2024")
        eventos = N.derivar_eventos([self.novo, futuro, torto], ate="2024-10-01")
        self.assertEqual([e["projeto"]["id"] for e in eventos], [2])
        self.assertEqual(len(N.derivar_eventos([futuro, torto])), 1)  # sem limite, só a data inválida sai

    def test_data_da_coleta(self):
        self.assertEqual(N.data_da_coleta({"coleta": {"em": "2026-10-19T09:17:00+00:00"}}), "2026-10-19")
        # Horário de Brasília (UTC−3): 01:30 UTC de 20/10 ainda é 19/10, e 02:59 também; 03:00 já é 20/10.
        self.assertEqual(N.data_da_coleta({"coleta": {"em": "2026-10-20T01:30:00+00:00"}}), "2026-10-19")
        self.assertEqual(N.data_da_coleta({"coleta": {"em": "2026-10-20T02:59:59+00:00"}}), "2026-10-19")
        self.assertEqual(N.data_da_coleta({"coleta": {"em": "2026-10-20T03:00:00+00:00"}}), "2026-10-20")
        self.assertEqual(N.data_da_coleta({"coleta": {"em": "2026-10-19T23:30:00-03:00"}}), "2026-10-19")
        self.assertEqual(N.data_da_coleta({"coleta": {"em": "2026-10-19"}}), "2026-10-19")  # sem fuso: como está
        self.assertIsNone(N.data_da_coleta({}))
        self.assertIsNone(N.data_da_coleta({"coleta": {"em": "ontem"}}))
        # O corte usa o dia de Brasília: um evento de 19/10 entra numa coleta das 01:30 UTC de 20/10; um de 20/10, não.
        meta = {"coleta": {"em": "2026-10-20T01:30:00+00:00"}}
        modelo = {"meta": meta, "projetos": [projeto(8, "8/2026", "2026-10-19"), projeto(9, "9/2026", "2026-10-20")]}
        self.assertEqual([e["projeto"]["id"] for e in N.eventos_do_modelo(modelo)], [8])

    def test_titulos(self):
        eventos = {e["tipo"]: e for e in N.derivar_eventos([self.lei])}
        self.assertEqual(N.titulo_evento(eventos["lei"]),
                         "PL 140/2021 virou a Lei 3958, via substitutivo (promulgada após a derrubada do veto)")
        self.assertEqual(N.titulo_evento(eventos["veto"]), "PL 140/2021 recebeu veto total do prefeito (no substitutivo)")
        self.assertEqual(N.titulo_evento(eventos["veto_derrubado"]), "A Câmara derrubou o veto ao PL 140/2021 (no substitutivo)")
        self.assertEqual(N.titulo_evento(eventos["apresentado"]), "PL 140/2021 apresentado")
        sancionada = projeto(7, "5/2025", "2025-01-02", desfecho="virou_lei",
                             lei={"numero": None, "data": "2025-03-01", "tipo": "sancionada", "veto_parcial": True})
        lei = next(e for e in N.derivar_eventos([sancionada]) if e["tipo"] == "lei")
        self.assertEqual(N.titulo_evento(lei), "PL 5/2025 virou lei (sancionada, com veto parcial)")
        veto = {"tipo": "veto", "data": "2025-02-01", "alcance": None, "substitutivo": None, "projeto": sancionada}
        self.assertEqual(N.titulo_evento(veto), "PL 5/2025 recebeu veto do prefeito")


# --------------------------------------------------------------------- semanas
class TestSemanas(unittest.TestCase):
    def setUp(self):
        self.projetos = [
            projeto(1, "1/2026", "2026-10-14"),  # quarta-feira
            projeto(2, "2/2026", "2026-10-19"),  # segunda-feira: a data mais recente
            projeto(3, "3/2026", "2026-02-02", desfecho="virou_lei",
                    lei={"numero": 4100, "data": "2026-08-03", "tipo": "sancionada"}),  # segunda, 11 semanas antes
            projeto(4, "4/2026", "2026-08-02"),  # domingo, fora das 12 semanas
        ]

    def test_semana_atual_ancorada_na_data_mais_recente_e_nunca_no_relogio(self):
        with mock.patch.object(N, "date", SemRelogio):
            semanas = N.semanas_recentes(N.derivar_eventos(self.projetos))
        self.assertEqual(len(semanas), N.SEMANAS)
        self.assertEqual((semanas[0]["inicio"], semanas[0]["fim"]), ("2026-10-19", "2026-10-25"))
        self.assertEqual(semanas[0]["numero"], date(2026, 10, 19).isocalendar().week)
        self.assertEqual([e["projeto"]["id"] for e in semanas[0]["eventos"]], [2])
        self.assertEqual((semanas[1]["inicio"], [e["projeto"]["id"] for e in semanas[1]["eventos"]]), ("2026-10-12", [1]))
        self.assertEqual((semanas[-1]["inicio"], semanas[-1]["fim"]), ("2026-08-03", "2026-08-09"))
        self.assertEqual(semanas[-1]["contagem"], {"lei": 1})
        self.assertEqual(semanas[2]["eventos"], [])  # semana sem evento continua na lista
        exibidos = {e["projeto"]["id"] for s in semanas for e in s["eventos"]}
        self.assertNotIn(4, exibidos)
        inicios = [s["inicio"] for s in semanas]
        self.assertEqual(inicios, sorted(inicios, reverse=True))
        self.assertTrue(all(date.fromisoformat(i).weekday() == 0 for i in inicios))

    def test_contagem_por_tipo_na_ordem_de_exibicao(self):
        p = projeto(5, "5/2026", "2026-10-20", desfecho="virou_lei", lei={"numero": 4200, "data": "2026-10-21"},
                    marcos=[{"tipo": "veto", "data": "2026-10-20", "alcance": "parcial", "substitutivo": None}])
        semana = N.semanas_recentes(N.derivar_eventos(self.projetos + [p]))[0]
        self.assertEqual(semana["contagem"], {"lei": 1, "veto": 1, "apresentado": 2})
        self.assertIn('<p class="contagem"><b>1</b> lei sancionada ou promulgada · <b>1</b> veto do prefeito · '
                      '<b>2</b> projetos apresentados</p>', P.secao_semana(semana, "", True))

    def test_sem_eventos(self):
        self.assertEqual(N.semanas_recentes([]), [])
        self.assertIn("Nenhum evento", P.gerar_novidades([]))
        canal = ElementTree.fromstring(N.gerar_rss([]).encode("utf-8")).find("channel")
        self.assertEqual(canal.findall("item"), [])
        self.assertIsNone(canal.find("lastBuildDate"))


# ------------------------------------------------------------- RSS e página
class TestRssEPagina(unittest.TestCase):
    def setUp(self):
        self.perigoso = projeto(10, "10/2026", "2026-10-19", ementa="Proíbe <script>alert(1)</script> & “aspas”\x0b no fim",
                                resumo='Resumo com "aspas" & <b>tags</b>')
        self.projetos = [self.perigoso] + [projeto(100 + i, f"{100 + i}/2026", f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}")
                                           for i in range(150)]

    def canal(self, eventos):
        raiz = ElementTree.fromstring(N.gerar_rss(eventos).encode("utf-8"))
        self.assertEqual((raiz.tag, raiz.get("version")), ("rss", "2.0"))
        return raiz.find("channel")

    def test_rss_valido_com_guid_estavel_e_links_absolutos(self):
        eventos = N.derivar_eventos(self.projetos)
        canal = self.canal(eventos)
        self.assertEqual(canal.findtext("link"), N.URL_SITE + "novidades.html")
        self.assertTrue(canal.findtext("title"))
        self.assertTrue(canal.findtext("description"))
        atom = canal.find("{http://www.w3.org/2005/Atom}link")
        self.assertEqual((atom.get("href"), atom.get("rel")), (N.URL_SITE + "feed.xml", "self"))
        itens = canal.findall("item")
        self.assertEqual(len(itens), N.MAX_ITENS_RSS)  # 151 eventos, só os 100 mais recentes
        self.assertEqual(itens[0].findtext("guid"), "radar-vereadores-niteroi:apresentado:10:2026-10-19")
        self.assertEqual([i.findtext("guid") for i in itens],
                         [f"radar-vereadores-niteroi:{e['tipo']}:{e['projeto']['id']}:{e['data']}" for e in eventos[:100]])
        for item in itens:
            self.assertEqual(item.find("guid").get("isPermaLink"), "false")
            self.assertRegex(item.findtext("link"), r"^https://")
            self.assertRegex(item.findtext("pubDate"), r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun), \d{2} [A-Z][a-z]{2} \d{4} 00:00:00 -0300$")
        self.assertEqual(canal.findtext("lastBuildDate"), "Mon, 19 Oct 2026 00:00:00 -0300")
        self.assertEqual(canal.findtext("pubDate"), canal.findtext("lastBuildDate"))

    def test_escape_xml(self):
        item = self.canal(N.derivar_eventos([self.perigoso])).find("item")
        descricao = item.findtext("description")
        self.assertIn("Proíbe <script>alert(1)</script> & “aspas” no fim", descricao)  # volta igual, sem o \x0b
        self.assertIn('Resumo com "aspas" & <b>tags</b>', descricao)
        self.assertIn("Autoria: Ana Teste (PX).", descricao)
        bruto = N.gerar_rss(N.derivar_eventos([self.perigoso]))
        self.assertIn("&lt;script&gt;", bruto)
        self.assertNotIn("<script>", bruto)
        self.assertNotIn("\x0b", bruto)
        self.assertEqual(N.link_absoluto("dados/x.json"), N.URL_SITE + "dados/x.json")

    def test_link_da_lei_via_substitutivo_e_o_do_substitutivo(self):
        p = projeto(20, "140/2021", "2021-04-21", desfecho="virou_lei", lei_substitutivo=266596,
                    lei={"numero": 3958, "data": "2024-09-12", "tipo": "veto_derrubado", "veto_parcial": False},
                    marcos=[{"tipo": "veto", "data": "2024-06-27", "alcance": "total", "substitutivo": 266596}])
        links = {i.findtext("guid").split(":")[1]: i.findtext("link") for i in self.canal(N.derivar_eventos([p])).findall("item")}
        self.assertEqual(links, {
            "lei": URL.format(266596),          # a página de onde saiu a lei, como na página (url_lei)
            "veto": URL.format(20),             # os demais eventos levam ao PL
            "apresentado": URL.format(20),
        })
        sem_substitutivo = projeto(21, "1/2024", "2024-01-02", desfecho="virou_lei",
                                   lei={"numero": 3900, "data": "2024-03-01", "tipo": "sancionada"})
        lei = next(e for e in N.derivar_eventos([sem_substitutivo]) if e["tipo"] == "lei")
        self.assertEqual(N.link_evento(lei), URL.format(21))

    def test_data_rfc822_sem_locale(self):
        self.assertEqual(N.data_rfc822("2026-10-05"), "Mon, 05 Oct 2026 00:00:00 -0300")
        self.assertEqual(N.data_rfc822("2024-02-29"), "Thu, 29 Feb 2024 00:00:00 -0300")

    def test_mesma_entrada_mesmos_bytes(self):
        embaralhados = list(self.projetos)
        random.Random(7).shuffle(embaralhados)
        a, b = N.derivar_eventos(self.projetos), N.derivar_eventos(embaralhados)
        self.assertEqual(N.gerar_rss(a).encode("utf-8"), N.gerar_rss(b).encode("utf-8"))
        self.assertEqual(P.gerar_novidades(a), P.gerar_novidades(b))
        with mock.patch.object(N, "date", SemRelogio):
            self.assertEqual(N.gerar_rss(N.derivar_eventos(self.projetos)), N.gerar_rss(a))

    def test_pagina_agrupada_com_links_e_escape(self):
        lei = projeto(20, "20/2026", "2026-03-01", desfecho="virou_lei", lei_substitutivo=266596,
                      lei={"numero": 4300, "data": "2026-10-13", "tipo": "sancionada"})
        html = P.gerar_novidades(N.derivar_eventos([self.perigoso, lei]))
        self.assertIn('href="novidades.html" aria-current="page"', html)
        self.assertIn('<link rel="alternate" type="application/rss+xml"', html)
        self.assertNotIn("<script>alert(1)", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt; &amp;", html)
        self.assertIn(f'<a href="{URL.format(10)}" target="_blank" rel="noopener">PL 10/2026', html)
        # O partido do autor principal fica dentro do chip, logo depois do nome (não mais solto após os autores).
        self.assertIn('<a class="chip chip-principal" href="vereadores/ana-teste.html">Ana Teste<span class="partido">PX</span></a>', html)
        self.assertNotIn('</a><span class="partido">', html)
        self.assertIn(f'href="{URL.format(266596)}" target="_blank" rel="noopener">substitutivo no SISCAM', html)
        self.assertIn('<time datetime="2026-10-19">19/10/2026</time>', html)
        # Semanas da mais recente para a mais antiga, com a contagem por tipo.
        self.assertLess(html.index('id="semana-2026-10-19"'), html.index('id="semana-2026-10-12"'))
        self.assertIn('Semana de 19/10/2026 a 25/10/2026 <span>mais recente</span>', html)
        self.assertIn('<p class="contagem"><b>1</b> projeto apresentado</p>', html)
        self.assertIn('<p class="contagem"><b>1</b> lei sancionada ou promulgada</p>', html)
        self.assertIn("Nenhum evento com data nesta semana.", html)
        self.assertEqual(len(re.findall(r'<section class="semana"', html)), N.SEMANAS)


if __name__ == "__main__":
    unittest.main()
