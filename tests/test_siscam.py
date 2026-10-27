"""Testes do coletor do SISCAM: utilidades, parsing de páginas reais e derivações."""
from __future__ import annotations

import contextlib
import copy
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from coletor import siscam
from tests.apoio import ler_fixture, registro_versionado
from tests.test_arquivos_siscam import ESPERADOS

# Resumo do PL 1/2025 como aparece na listagem (id 275545, virou a Lei 3.987/2025)
RESUMO_275545 = {
    "id": 275545,
    "numero": "1/2025",
    "ano": 2025,
    "situacao": "PUBLICADO",
    "autor_ids": [(7, "RODRIGO FLACH FARAH")],
    "n_tramitacoes": 5,
}


def tram(**campos) -> dict:
    """Tramitação sintética com os campos produzidos por parse_detalhe."""
    base = {
        "seq": 1, "remetente": "", "destinatario": "", "objetivo": "", "enviado": None,
        "complemento": "", "resultado": "", "data_resposta": None, "observacao": "",
    }
    return {**base, **campos}


# ---------------------------------------------------------------------- utilidades
class TestUtilidades(unittest.TestCase):
    def test_limpar_remove_tags_entidades_e_espacos(self):
        self.assertEqual(siscam.limpar("<b>Olá</b>&nbsp; <i>mundo</i>\n"), "Olá mundo")
        self.assertEqual(siscam.limpar("A &amp; B"), "A & B")
        self.assertEqual(siscam.limpar("  \n\t "), "")
        self.assertEqual(siscam.limpar(""), "")

    def test_data_iso(self):
        self.assertEqual(siscam.data_iso("06/02/2025"), "2025-02-06")
        self.assertEqual(siscam.data_iso("10/02/2025 12:32"), "2025-02-10")
        self.assertEqual(siscam.data_iso("Enviado em 17/03/2025"), "2025-03-17")
        self.assertIsNone(siscam.data_iso(""))
        self.assertIsNone(siscam.data_iso(None))
        self.assertIsNone(siscam.data_iso("2025-02-06"))

    def test_campo_usa_dotall_e_limpa(self):
        html = "<td><strong>Ementa: </strong>Linha um\n<b>linha dois</b></td>"
        self.assertEqual(siscam.campo(r"Ementa: </strong>(.*?)</td>", html), "Linha um linha dois")

    def test_campo_sem_correspondencia(self):
        self.assertEqual(siscam.campo(r"Inexistente: (.*?)<", "<td>nada</td>"), "")


# ------------------------------------------------------------------------ listagem
class TestListagem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pagina = ler_fixture("siscam", "listagem_tipo4_2025.html")
        cls.itens = siscam.parse_listagem(cls.pagina)

    def test_dez_registros(self):
        self.assertEqual(len(self.itens), 10)

    def test_registros_esperados(self):
        esperado = [
            (284727, "400/2025", "PARECER CONTRÁRIO", [(275, "Michel Salim Saad Neto")], 3),
            (284726, "399/2025", "ENCAMINHADO ÀS COMISSÕES", [(275, "Michel Salim Saad Neto")], 2),
            (284725, "398/2025", "SMDCP", [(7, "RODRIGO FLACH FARAH")], 3),
            (284724, "397/2025", "ENCAMINHADO ÀS COMISSÕES", [(237, "ROBSON GUIMARÃES JOSÉ FILHO")], 2),
            (284723, "396/2025", "SMDCP", [(237, "ROBSON GUIMARÃES JOSÉ FILHO")], 3),
            (284722, "395/2025", "ENCAMINHADO ÀS COMISSÕES", [(81, "DANIEL MARQUES FREDERICO")], 3),
            (284721, "394/2025", "ENCAMINHADO ÀS COMISSÕES", [(81, "DANIEL MARQUES FREDERICO")], 2),
            (284720, "393/2025", "ENCAMINHADO ÀS COMISSÕES", [(81, "DANIEL MARQUES FREDERICO")], 2),
            (284719, "392/2025", "ENCAMINHADO ÀS COMISSÕES", [(238, "TULIO RABELO DE ALBUQUERQUE MOTA")], 2),
            (284340, "391/2025", "PUBLICADO", [(99, "RODRIGO NEVES")], 31),
        ]
        obtido = [(i["id"], i["numero"], i["situacao"], i["autor_ids"], i["n_tramitacoes"]) for i in self.itens]
        self.assertEqual(obtido, esperado)

    def test_campos_coerentes(self):
        for item in self.itens:
            with self.subTest(id=item["id"]):
                self.assertEqual(item["ano"], 2025)
                self.assertRegex(item["numero"], r"^[1-9]\d*/2025$")  # sem zeros à esquerda
                self.assertTrue(item["situacao"])
                self.assertEqual(item["situacao"], item["situacao"].strip())
                self.assertTrue(item["autor_ids"])
                for autor_id, nome in item["autor_ids"]:
                    self.assertIsInstance(autor_id, int)
                    self.assertTrue(nome)
                    self.assertNotIn("<", nome)
        self.assertEqual(len({i["id"] for i in self.itens}), 10)

    def test_total_registros(self):
        self.assertEqual(siscam.total_registros(self.pagina), 400)

    def test_pagina_vazia(self):
        self.assertEqual(siscam.parse_listagem(""), [])
        self.assertEqual(siscam.total_registros(""), 0)


# ------------------------------------------------------------------------- detalhe
class TestDetalhe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.detalhe = siscam.parse_detalhe(ler_fixture("siscam", "detalhe_pl_275545.html"))
        cls.versionado = registro_versionado(2025, 275545)

    def test_cabecalho(self):
        d = self.detalhe
        self.assertEqual(d["data"], "2025-02-06")
        self.assertEqual(d["assunto"], "CÓDIGO AMBIENTAL")
        self.assertEqual(d["situacao"], "PUBLICADO")
        self.assertEqual(d["processo"], "1/2025")
        self.assertEqual(d["protocolo"], "31/2025")  # não confunde com "Data do Protocolo"
        self.assertEqual(d["data_protocolo"], "2025-02-10")
        self.assertTrue(d["ementa"].startswith("Ementa: Altera a Lei nº 1.212"))

    def test_autoria(self):
        self.assertEqual(self.detalhe["autoria"], [{"nome": "RODRIGO FLACH FARAH", "origem": "Vereador", "papel": "Autor"}])

    def test_tramitacoes(self):
        trams = self.detalhe["tramitacoes"]
        self.assertEqual([t["seq"] for t in trams], [1, 2, 3, 4, 5])
        ultima = trams[-1]
        self.assertEqual(ultima["resultado"], "Promulgado/Sancionado")
        self.assertEqual(ultima["enviado"], "2025-03-17")
        self.assertEqual(ultima["data_resposta"], "2025-04-08")
        self.assertEqual(ultima["destinatario"], "RODRIGO NEVES")
        self.assertEqual(ultima["observacao"], 'LEI MUNICIPAL N° 3987/2025, PUBLICADO NO JORNAL "A TRIBUNA"')

    def test_lei_e_desfecho_derivados(self):
        self.assertEqual(
            siscam.derivar_lei(self.detalhe["tramitacoes"]),
            {"numero": 3987, "data": "2025-04-08", "tipo": "sancionada", "veto_parcial": False},
        )
        reg = siscam.montar_registro(RESUMO_275545, self.detalhe)
        self.assertEqual(reg["desfecho"], "virou_lei")
        self.assertEqual(reg["url"], "https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento=275545")
        self.assertEqual(reg["autoria"], [{"nome": "RODRIGO FLACH FARAH", "origem": "Vereador", "papel": "Autor", "id": 7}])

    def test_confere_com_registro_versionado(self):
        if self.versionado is None:
            self.skipTest("registro 275545 ausente de data/proposicoes/2025.json")
        for chave in ("data", "assunto", "situacao", "processo", "ementa", "protocolo", "data_protocolo", "tramitacoes"):
            with self.subTest(campo=chave):
                self.assertEqual(self.detalhe[chave], self.versionado[chave])
        sem_id = [{k: v for k, v in a.items() if k != "id"} for a in self.versionado["autoria"]]
        self.assertEqual(self.detalhe["autoria"], sem_id)

    def test_montar_registro_confere_com_versionado(self):
        if self.versionado is None:
            self.skipTest("registro 275545 ausente de data/proposicoes/2025.json")
        reg = siscam.montar_registro(RESUMO_275545, self.detalhe)
        for chave, valor in reg.items():
            if chave == "arquivos":  # metadados novos, ainda ausentes da base histórica
                self.assertEqual(valor, ESPERADOS["pl_275545"])
                continue
            with self.subTest(campo=chave):
                self.assertEqual(valor, self.versionado.get(chave))

    def test_pagina_sem_dados(self):
        d = siscam.parse_detalhe("<html></html>")
        self.assertEqual(d["autoria"], [])
        self.assertEqual(d["tramitacoes"], [])
        self.assertIsNone(d["data"])
        self.assertEqual(d["ementa"], "")


class TestMontarRegistro(unittest.TestCase):
    def test_autor_da_listagem_ausente_do_detalhe(self):
        resumo = {**RESUMO_275545, "autor_ids": [(7, "Rodrigo Flach Farah"), (8, "FULANA DE TAL")], "situacao": ""}
        detalhe = {
            "data": None, "assunto": "", "situacao": "ARQUIVADO", "processo": "", "ementa": "", "protocolo": "",
            "data_protocolo": None, "tramitacoes": [],
            "autoria": [{"nome": "RODRIGO FLACH FARAH", "origem": "Vereador", "papel": "Autor"}],
        }
        reg = siscam.montar_registro(resumo, detalhe)
        self.assertEqual(reg["autoria"][0]["id"], 7)  # casa nomes sem diferenciar maiúsculas
        self.assertEqual(reg["autoria"][1], {"id": 8, "nome": "FULANA DE TAL", "origem": "", "papel": "Co-Autor"})
        self.assertEqual(reg["situacao"], "ARQUIVADO")  # sem situação na listagem, vale a do detalhe
        self.assertIsNone(reg["lei"])
        self.assertEqual(reg["desfecho"], "arquivado")

    def test_autor_unico_vindo_da_listagem_e_autor(self):
        detalhe = {"data": None, "situacao": "", "tramitacoes": [], "autoria": []}
        reg = siscam.montar_registro({**RESUMO_275545, "autor_ids": [(9, "BELTRANO")]}, detalhe)
        self.assertEqual(reg["autoria"], [{"id": 9, "nome": "BELTRANO", "origem": "", "papel": "Autor"}])


class TestPrecisaDetalhe(unittest.TestCase):
    RESUMO = {"n_tramitacoes": 3, "situacao": "SMDCP"}
    ANTERIOR = {"n_tramitacoes": 3, "situacao": "SMDCP", "tramitacoes": [{"seq": 1}]}

    def test_sem_mudanca(self):
        self.assertFalse(siscam.precisa_detalhe(self.ANTERIOR, self.RESUMO, False))

    def test_novo_ou_forcado(self):
        self.assertTrue(siscam.precisa_detalhe(None, self.RESUMO, False))
        self.assertTrue(siscam.precisa_detalhe(self.ANTERIOR, self.RESUMO, True))

    def test_mudou_contagem_ou_situacao(self):
        self.assertTrue(siscam.precisa_detalhe(self.ANTERIOR, {**self.RESUMO, "n_tramitacoes": 4}, False))
        self.assertTrue(siscam.precisa_detalhe(self.ANTERIOR, {**self.RESUMO, "situacao": "ARQUIVADO"}, False))

    def test_anterior_sem_tramitacoes(self):
        self.assertTrue(siscam.precisa_detalhe({**self.ANTERIOR, "tramitacoes": []}, self.RESUMO, False))


# --------------------------------------------------------------------- derivações
class TestNumeroLei(unittest.TestCase):
    def test_reconhece_lei(self):
        self.assertEqual(siscam._numero_lei("LEI MUNICIPAL Nº 4137/2026"), 4137)
        self.assertEqual(siscam._numero_lei("LEI N° 3.987/2025"), 3987)
        self.assertEqual(siscam._numero_lei("lei nº 4012, de 2025"), 4012)

    def test_ignora_projeto_de_lei_e_leis_antigas(self):
        self.assertIsNone(siscam._numero_lei("PROJETO DE LEI Nº 4124/2026"))
        self.assertIsNone(siscam._numero_lei("ALTERA A LEI Nº 1.212/1993"))
        self.assertIsNone(siscam._numero_lei(""))
        self.assertIsNone(siscam._numero_lei(None))


class TestDerivarLei(unittest.TestCase):
    def test_sem_tramitacoes(self):
        self.assertIsNone(siscam.derivar_lei([]))

    def test_sem_sancao(self):
        trams = [tram(resultado="Aprovado em Primeira Discussão"), tram(resultado="Favorável", observacao="Parecer 1/2025")]
        self.assertIsNone(siscam.derivar_lei(trams))

    def test_sancao_pelo_resultado(self):
        trams = [
            tram(seq=1, resultado="Aprovado em Segunda Discussão"),
            tram(seq=2, resultado="Promulgado/Sancionado", observacao="LEI MUNICIPAL N° 3987/2025, PUBLICADO NO JORNAL",
                 enviado="2025-03-17", data_resposta="2025-04-08"),
        ]
        self.assertEqual(
            siscam.derivar_lei(trams), {"numero": 3987, "data": "2025-04-08", "tipo": "sancionada", "veto_parcial": False}
        )

    def test_sancao_pela_observacao_usa_data_de_envio(self):
        trams = [tram(resultado="Ciência", observacao="LEI Nº 4.012/2025 PUBLICADA NO DIÁRIO OFICIAL", enviado="2025-05-02")]
        lei = siscam.derivar_lei(trams)
        self.assertEqual(lei["numero"], 4012)
        self.assertEqual(lei["data"], "2025-05-02")

    def test_observacao_que_so_cita_outra_lei(self):
        self.assertIsNone(siscam.derivar_lei([tram(observacao="ALTERA A LEI Nº 3.474/2020")]))
        duplicada = tram(observacao="LEI Nº 3500/2020 PUBLICADA; PROJETO EM DUPLICIDADE")
        self.assertIsNone(siscam.derivar_lei([duplicada]))
        vigente = tram(observacao="A LEI Nº 3500/2020, PUBLICADA EM JORNAL, ESTÁ EM VIGOR")
        self.assertIsNone(siscam.derivar_lei([vigente]))

    def test_veto_derrubado(self):
        trams = [
            tram(seq=1, resultado="Veto Total", observacao=""),
            tram(seq=2, resultado="Veto Rejeitado", observacao=""),
            tram(seq=3, resultado="Promulgado", observacao="LEI Nº 3958/2024", data_resposta="2024-06-01"),
        ]
        self.assertEqual(siscam.derivar_lei(trams)["tipo"], "veto_derrubado")

    def test_promulgada_pela_camara(self):
        trams = [tram(resultado="Promulgado/Sancionado", observacao="LEI Nº 4050/2025 PROMULGADA PELO PRESIDENTE DA CÂMARA")]
        self.assertEqual(siscam.derivar_lei(trams)["tipo"], "promulgada_camara")

    def test_veto_parcial(self):
        trams = [
            tram(seq=1, resultado="Veto Parcial", observacao="VETO PARCIAL AO ART. 3º"),
            tram(seq=2, resultado="Sancionado", observacao="LEI Nº 4001/2025"),
        ]
        lei = siscam.derivar_lei(trams)
        self.assertTrue(lei["veto_parcial"])
        self.assertEqual(lei["tipo"], "sancionada")

    def test_corrigenda_leia_se(self):
        trams = [
            tram(seq=1, resultado="Promulgado/Sancionado", observacao="LEI Nº 3958/2024 PUBLICADA"),
            tram(seq=2, resultado="Ciência", observacao="ONDE SE LÊ: LEI Nº 3958/2024, LEIA-SE: LEI Nº 3959/2024"),
        ]
        self.assertEqual(siscam.derivar_lei(trams)["numero"], 3959)


class TestDerivarDesfecho(unittest.TestCase):
    def desfecho(self, situacao: str = "", trams: list[dict] | None = None, lei: dict | None = None) -> str:
        return siscam.derivar_desfecho({"situacao": situacao, "tramitacoes": trams or [], "lei": lei})

    def test_virou_lei(self):
        self.assertEqual(self.desfecho(lei={"numero": 4000}), "virou_lei")
        for situacao in sorted(siscam.SITUACOES_LEI):
            with self.subTest(situacao=situacao):
                self.assertEqual(self.desfecho(situacao), "virou_lei")
        self.assertEqual(self.desfecho("publicado"), "virou_lei")  # compara em maiúsculas

    def test_lei_prevalece_sobre_situacao(self):
        self.assertEqual(self.desfecho("ARQUIVADO", lei={"numero": 4000}), "virou_lei")

    def test_vetado(self):
        self.assertEqual(self.desfecho("VETO MANTIDO"), "vetado")
        self.assertEqual(self.desfecho("VETO TOTAL"), "vetado")
        self.assertEqual(self.desfecho("SMDCP", [tram(resultado="Veto Total")]), "vetado")

    def test_rejeitado(self):
        self.assertEqual(self.desfecho("REJEITADO"), "rejeitado")
        self.assertEqual(self.desfecho("REJEITADA"), "rejeitado")
        self.assertEqual(self.desfecho("SMDCP", [tram(observacao="Rejeitado em 1ª discussão")]), "rejeitado")

    def test_demais_situacoes(self):
        casos = {
            "AGUARDANDO SANÇÃO": "aprovado_aguardando_sancao",
            "APROVADO": "aprovado_aguardando_sancao",
            "VOTADO": "aprovado_aguardando_sancao",
            "RETIRADO": "retirado",
            "RETIRADA": "retirado",
            "CANCELADO": "retirado",
            "PARECER CONTRÁRIO": "parecer_contrario",
            "ARQUIVADO": "arquivado",
            "APENSADO": "apensado",
            "SMDCP": "em_tramitacao",
            "": "em_tramitacao",
        }
        for situacao, esperado in casos.items():
            with self.subTest(situacao=situacao):
                self.assertEqual(self.desfecho(situacao), esperado)

    def test_registro_vazio(self):
        self.assertEqual(siscam.derivar_desfecho({}), "em_tramitacao")


# -------------------------------------------------------------------- substitutivos
# PL 140/2021 (id 127858): o SISCAM o registra como apensado, mas o Substitutivo nº 1 (id 266596)
# virou a Lei 3.958/2024 depois que a Câmara derrubou o veto total.
URL_127858 = "https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento=127858"
URL_266596 = "https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento=266596"
FIXTURES_DETALHE = {127858: "detalhe_pl_127858.html", 266596: "detalhe_substitutivo_266596.html"}
RESUMO_127858 = {
    "id": 127858, "numero": "140/2021", "ano": 2021, "situacao": "Apensado",
    "autor_ids": [(81, "DANIEL MARQUES FREDERICO")], "n_tramitacoes": 10,
}
LEI_3958 = {"numero": 3958, "data": "2024-09-12", "tipo": "veto_derrubado", "veto_parcial": False}


def doc_da_url(url: str) -> int:
    return int(url.rsplit("=", 1)[1])


def baixar_fixtures(url: str, tentativas: int = 5) -> str:
    """Substitui siscam.baixar: devolve as páginas reais salvas, sem rede."""
    return ler_fixture("siscam", FIXTURES_DETALHE[doc_da_url(url)])


def silencioso():
    """Engole os avisos e o progresso impressos pelo coletor."""
    pilha = contextlib.ExitStack()
    pilha.enter_context(contextlib.redirect_stderr(io.StringIO()))
    pilha.enter_context(contextlib.redirect_stdout(io.StringIO()))
    return pilha


def substitutivo(id_: int = 266596, lei: dict | None = None, **campos) -> dict:
    """Substitutivo já gravado, no formato de montar_registro."""
    trams = [
        tram(seq=1, resultado="Aprovado em Discussão Única", observacao="DERRUBADO O VETO TOTAL EM DISCUSSÃO ÚNICA"),
        tram(seq=2, resultado="PROMULGADO", observacao="PROMULGA LEI Nº 3958/2024, PUBLICADA NO JORNAL", data_resposta="2024-09-12"),
    ] if lei else []
    return {"id": id_, "numero": "1", "data": "2024-03-14", "situacao": "RECEBIDO PELA SMD",
            "autoria": [{"nome": "DANIEL MARQUES FREDERICO", "origem": "Vereador", "papel": "Autor", "id": 81}],
            "tramitacoes": trams, "lei": lei, **campos}


class TestParseSubstitutivos(unittest.TestCase):
    def test_secao_do_pl_140_2021(self):
        refs = siscam.parse_substitutivos(ler_fixture("siscam", "detalhe_pl_127858.html"))
        # só o substitutivo: a Emenda nº 1 (252101) e os pareceres ficam de fora
        self.assertEqual(refs, [{"id": 266596, "numero": "1", "data": "2024-03-14"}])

    def test_pagina_sem_substitutivos(self):
        with silencioso():
            # o próprio substitutivo só tem emendas e parecer
            self.assertEqual(siscam.parse_substitutivos(ler_fixture("siscam", "detalhe_substitutivo_266596.html")), [])
            self.assertEqual(siscam.parse_substitutivos(ler_fixture("siscam", "detalhe_pl_275545.html")), [])
            self.assertEqual(siscam.parse_substitutivos(""), [])

    def test_detalhe_do_pl_continua_igual(self):
        d = siscam.parse_detalhe(ler_fixture("siscam", "detalhe_pl_127858.html"))
        self.assertEqual(d["situacao"], "Apensado")
        self.assertEqual([t["seq"] for t in d["tramitacoes"]], list(range(1, 11)))
        self.assertEqual(d["tramitacoes"][-1]["observacao"], "RECEBIDO SUBSTITUTIVO N° 01/2024")
        self.assertNotIn("substitutivos", d)
        self.assertIsNone(siscam.derivar_lei(d["tramitacoes"]))

    def test_detalhe_do_substitutivo(self):
        d = siscam.parse_detalhe(ler_fixture("siscam", "detalhe_substitutivo_266596.html"))
        self.assertEqual(d["situacao"], "RECEBIDO PELA SMD")
        self.assertEqual(d["data"], "2024-03-14")
        self.assertEqual(d["autoria"], [
            {"nome": "DANIEL MARQUES FREDERICO", "origem": "Vereador", "papel": "Autor"},
            {"nome": "MILTON CARLOS DA SILVA LOPES", "origem": "Vereador", "papel": "Co-Autor"},
        ])
        trams = d["tramitacoes"]
        self.assertEqual([t["seq"] for t in trams], list(range(1, 13)))
        self.assertEqual((trams[7]["objetivo"], trams[7]["resultado"]), ("Sancionar / Vetar Lei", "Vetado"))
        self.assertEqual((trams[11]["objetivo"], trams[11]["resultado"], trams[11]["data_resposta"]),
                         ("VETO DERRUBADO", "PROMULGADO", "2024-09-12"))

    def test_lei_do_substitutivo(self):
        d = siscam.parse_detalhe(ler_fixture("siscam", "detalhe_substitutivo_266596.html"))
        self.assertEqual(siscam.derivar_lei(d["tramitacoes"]), LEI_3958)


class TestRegistroComSubstitutivo(unittest.TestCase):
    def montar(self) -> dict:
        with mock.patch.object(siscam, "baixar", side_effect=baixar_fixtures) as baixar:
            pagina = siscam.baixar(URL_127858)
            substitutivos = siscam.coletar_substitutivos(siscam.parse_substitutivos(pagina), None)
            reg = siscam.montar_registro(RESUMO_127858, siscam.parse_detalhe(pagina), substitutivos)
        self.assertEqual([c.args[0] for c in baixar.call_args_list], [URL_127858, URL_266596])
        return reg

    def test_lei_do_substitutivo_vai_para_o_pl_original(self):
        reg = self.montar()
        self.assertEqual(reg["desfecho"], "virou_lei")
        self.assertEqual(reg["lei"], LEI_3958)
        self.assertEqual(reg["lei_substitutivo"], 266596)
        self.assertEqual(reg["url"], URL_127858)  # o registro continua sendo o do PL original
        self.assertEqual((reg["numero"], reg["situacao"]), ("140/2021", "Apensado"))

    def test_forma_do_substitutivo_gravado(self):
        [s] = self.montar()["substitutivos"]
        self.assertEqual(set(s), {"id", "numero", "data", "situacao", "autoria", "tramitacoes", "lei", "arquivos"})
        self.assertEqual(s["arquivos"], ESPERADOS["substitutivo_266596"])
        self.assertEqual((s["id"], s["numero"], s["data"], s["situacao"]), (266596, "1", "2024-03-14", "RECEBIDO PELA SMD"))
        self.assertEqual(s["lei"], LEI_3958)
        self.assertEqual(len(s["tramitacoes"]), 12)
        # ids dos autores vêm da listagem do PL; o coautor que só assina o substitutivo fica sem id
        self.assertEqual([(a["nome"], a["papel"], a["id"]) for a in s["autoria"]],
                         [("DANIEL MARQUES FREDERICO", "Autor", 81), ("MILTON CARLOS DA SILVA LOPES", "Co-Autor", None)])

    def test_sem_substitutivos_o_registro_nao_muda(self):
        detalhe = siscam.parse_detalhe(ler_fixture("siscam", "detalhe_pl_127858.html"))
        reg = siscam.montar_registro(RESUMO_127858, detalhe)
        self.assertEqual(reg["desfecho"], "apensado")
        self.assertIsNone(reg["lei"])
        self.assertNotIn("substitutivos", reg)
        self.assertNotIn("lei_substitutivo", reg)
        vazio = siscam.montar_registro(RESUMO_127858, detalhe, [])
        self.assertEqual(vazio, {**reg, "substitutivos": []})


class TestColetarSubstitutivos(unittest.TestCase):
    REF = {"id": 266596, "numero": "1", "data": "2024-03-14"}

    def test_falha_mantem_o_substitutivo_anterior(self):
        anterior = substitutivo(lei=dict(LEI_3958))
        with silencioso(), mock.patch.object(siscam, "baixar", side_effect=RuntimeError("fora do ar")):
            self.assertEqual(siscam.coletar_substitutivos([self.REF], [anterior]), [anterior])

    def test_falha_sem_dado_anterior_faz_o_pl_falhar(self):
        with mock.patch.object(siscam, "baixar", side_effect=RuntimeError("fora do ar")):
            with self.assertRaisesRegex(RuntimeError, "substitutivo 266596"):
                siscam.coletar_substitutivos([self.REF], [])

    def test_pagina_sem_tramitacao_nao_apaga_a_anterior(self):
        anterior = substitutivo(lei=dict(LEI_3958))
        with silencioso(), mock.patch.object(siscam, "baixar", return_value="<html></html>"):
            self.assertEqual(siscam.coletar_substitutivos([self.REF], [anterior]), [anterior])

    def test_substitutivo_que_sumiu_da_pagina_e_mantido(self):
        anterior = substitutivo(id_=111, lei=dict(LEI_3958))
        with silencioso(), mock.patch.object(siscam, "baixar", side_effect=baixar_fixtures):
            obtido = siscam.coletar_substitutivos([self.REF], [anterior])
        self.assertEqual([s["id"] for s in obtido], [266596, 111])
        self.assertEqual(obtido[1], anterior)


class TestAplicarSubstitutivos(unittest.TestCase):
    def registro(self, **campos) -> dict:
        return {"situacao": "Apensado", "tramitacoes": [], "lei": None, "desfecho": "apensado", **campos}

    def test_sem_lei_no_substitutivo_o_desfecho_nao_muda(self):
        reg = siscam.aplicar_substitutivos(self.registro(substitutivos=[substitutivo()]))
        self.assertEqual(reg["desfecho"], "apensado")
        self.assertIsNone(reg["lei"])
        self.assertNotIn("lei_substitutivo", reg)

    def test_vence_o_substitutivo_que_virou_lei(self):
        reg = siscam.aplicar_substitutivos(self.registro(substitutivos=[substitutivo(id_=1), substitutivo(lei=LEI_3958)]))
        self.assertEqual((reg["desfecho"], reg["lei"], reg["lei_substitutivo"]), ("virou_lei", LEI_3958, 266596))

    def test_lei_do_proprio_pl_prevalece(self):
        proprio = tram(resultado="Promulgado/Sancionado", observacao="LEI MUNICIPAL N° 3987/2025", data_resposta="2025-04-08")
        reg = siscam.aplicar_substitutivos(self.registro(tramitacoes=[proprio], substitutivos=[substitutivo(lei=LEI_3958)],
                                                         lei_substitutivo=266596))
        self.assertEqual(reg["lei"]["numero"], 3987)
        self.assertNotIn("lei_substitutivo", reg)

    def test_recalcula_e_e_idempotente(self):
        reg = self.registro(substitutivos=[substitutivo(lei=LEI_3958)])
        uma = copy.deepcopy(siscam.aplicar_substitutivos(reg))
        self.assertEqual(siscam.aplicar_substitutivos(reg), uma)


class TestPrecisaSubstitutivos(unittest.TestCase):
    def test_casos(self):
        casos = [
            (None, False),
            ({"lei": None}, True),  # registro coletado antes do suporte: backfill
            ({"lei": None, "substitutivos": []}, False),
            ({"lei": None, "substitutivos": [substitutivo()]}, True),  # substitutivo ainda sem lei
            ({"lei": LEI_3958, "substitutivos": [substitutivo(lei=LEI_3958)], "lei_substitutivo": 266596}, False),
            ({"lei": {"numero": 4000}, "substitutivos": [substitutivo()]}, False),  # o próprio PL já virou lei
        ]
        for anterior, esperado in casos:
            with self.subTest(anterior=anterior):
                self.assertEqual(siscam.precisa_substitutivos(anterior), esperado)


class TestColetarComSubstitutivos(unittest.TestCase):
    """coletar() com listagem, gravação e downloads simulados."""

    @staticmethod
    def par(id_: int, numero: int, ano: int, **anterior) -> tuple[dict, dict]:
        resumo = {"id": id_, "numero": f"{numero}/{ano}", "ano": ano, "situacao": "SMDCP",
                  "autor_ids": [(81, "DANIEL MARQUES FREDERICO")], "n_tramitacoes": 1}
        reg = {"id": id_, "numero": resumo["numero"], "ano": ano, "situacao": "SMDCP", "n_tramitacoes": 1,
               "tramitacoes": [tram()], "lei": None, "desfecho": "em_tramitacao",
               "autoria": [{"id": 81, "nome": "DANIEL MARQUES FREDERICO", "origem": "Vereador", "papel": "Autor"}],
               "url": siscam.DETALHE.format(doc=id_), **anterior}
        return resumo, reg

    def rodar(self, pares: dict[int, list[tuple[dict, dict]]], max_detalhes: int, baixar) -> tuple[dict, dict, list[int]]:
        salvos, baixados = {}, []

        def baixar_registrando(url, tentativas=5):
            baixados.append(doc_da_url(url))
            return baixar(url)

        with silencioso(), \
                mock.patch.object(siscam, "listar_ano", side_effect=lambda ano, w: [dict(r) for r, _ in pares[ano]]), \
                mock.patch.object(siscam, "carregar_ano", side_effect=lambda ano: {a["id"]: copy.deepcopy(a) for _, a in pares[ano]}), \
                mock.patch.object(siscam, "salvar_ano", side_effect=lambda ano, regs: salvos.__setitem__(ano, copy.deepcopy(regs))), \
                mock.patch.object(siscam, "baixar", side_effect=baixar_registrando):
            estat = siscam.coletar(sorted(pares), False, 1, max_detalhes)
        return estat, salvos, baixados

    def test_limite_e_ordem_do_backfill(self):
        pares = {
            2025: [self.par(501, 1, 2025), self.par(502, 2, 2025), self.par(503, 3, 2025)],
            2024: [self.par(401, 1, 2024), self.par(402, 2, 2024),
                   self.par(403, 3, 2024, substitutivos=[], n_tramitacoes=0),  # mudou na listagem: fora do limite
                   self.par(404, 4, 2024, substitutivos=[], arquivos=[])],     # já conferido e sem mudança
        }
        estat, salvos, baixados = self.rodar(pares, 4, lambda url: "<html></html>")
        # do mais recente ao mais antigo; a mudança da listagem vem antes e não gasta o limite
        self.assertEqual(baixados, [503, 502, 501, 403, 402])
        self.assertEqual((estat["por_substitutivos"], estat["substitutivos_adiados"], estat["falhas"]), (4, 1, 0))
        for id_ in (501, 502, 503):
            self.assertEqual(salvos[2025][id_]["substitutivos"], [])
        self.assertEqual(salvos[2024][402]["substitutivos"], [])
        self.assertEqual(salvos[2024][403]["substitutivos"], [])
        self.assertNotIn("substitutivos", salvos[2024][401])  # fica para a próxima execução
        self.assertEqual(salvos[2024][404], pares[2024][3][1])

    def test_falha_mantem_o_registro_anterior(self):
        pares = {2025: [self.par(501, 1, 2025), self.par(502, 2, 2025)]}

        def baixar(url):
            if doc_da_url(url) == 502:
                raise RuntimeError("fora do ar")
            return "<html></html>"

        estat, salvos, _ = self.rodar(pares, 10, baixar)
        self.assertEqual(estat["falhas"], 1)
        self.assertEqual(salvos[2025][502], pares[2025][1][1])
        self.assertEqual(salvos[2025][501]["substitutivos"], [])

    def test_pl_140_2021_vira_lei_pelo_substitutivo(self):
        resumo = dict(RESUMO_127858)
        _, anterior = self.par(127858, 140, 2021, situacao="Apensado", n_tramitacoes=10, desfecho="apensado")
        estat, salvos, baixados = self.rodar({2021: [(resumo, anterior)]}, 400, baixar_fixtures)
        self.assertEqual(baixados, [127858, 266596])
        self.assertEqual(estat["por_substitutivos"], 1)
        reg = salvos[2021][127858]
        self.assertEqual((reg["desfecho"], reg["lei"], reg["lei_substitutivo"]), ("virou_lei", LEI_3958, 266596))
        self.assertEqual(reg["url"], URL_127858)
        self.assertFalse(siscam.precisa_substitutivos(reg))  # com a lei, não volta a ser pedido

    def test_limite_zero_nao_baixa_nada_pelos_substitutivos(self):
        pares = {2025: [self.par(501, 1, 2025)]}
        estat, salvos, baixados = self.rodar(pares, 0, lambda url: "<html></html>")
        self.assertEqual(baixados, [])
        self.assertEqual((estat["por_substitutivos"], estat["substitutivos_adiados"]), (0, 1))
        self.assertNotIn("substitutivos", salvos[2025][501])


class TestArquivos(unittest.TestCase):
    def test_parse_e_montagem(self):
        detalhe = siscam.parse_detalhe(ler_fixture("siscam", "detalhe_pl_275545.html"))
        self.assertEqual(detalhe["arquivos"], ESPERADOS["pl_275545"])
        self.assertEqual(siscam.montar_registro(RESUMO_275545, detalhe)["arquivos"], detalhe["arquivos"])

    def test_precisa_arquivos(self):
        self.assertTrue(siscam.precisa_arquivos({"id": 1}))
        self.assertFalse(siscam.precisa_arquivos({"arquivos": []}))
        self.assertFalse(siscam.precisa_arquivos({"arquivos": ESPERADOS["pl_275545"]}))
        self.assertFalse(siscam.precisa_arquivos(None))
        self.assertTrue(siscam.precisa_arquivos({"arquivos": [], "substitutivos": [{"id": 1}]}))
        self.assertFalse(siscam.precisa_arquivos({"arquivos": [], "substitutivos": [{"id": 1, "arquivos": []}]}))

    def test_fila_compartilha_limite_sem_duplicar(self):
        ajuda = TestColetarComSubstitutivos()
        pares = {2025: [ajuda.par(501, 1, 2025, substitutivos=[]), ajuda.par(502, 2, 2025)]}
        for limite, esperado in [(0, []), (1, [502]), (2, [502, 501])]:
            with self.subTest(limite=limite):
                _, _, baixados = ajuda.rodar(pares, limite, lambda url: "<html></html>")
                self.assertEqual(baixados, esperado)

    def test_lista_vazia_preserva_arquivos_do_pl_com_aviso(self):
        ajuda = TestColetarComSubstitutivos()
        pares = {2025: [ajuda.par(501, 1, 2025, arquivos=ESPERADOS["pl_275545"])]}
        # rodar silencia stderr; captura o print para conferir o aviso sem depender da saída.
        with mock.patch("builtins.print") as imprimir:
            _, salvos, _ = ajuda.rodar(pares, 1, lambda url: "<html></html>")
        self.assertEqual(salvos[2025][501]["arquivos"], ESPERADOS["pl_275545"])
        self.assertTrue(any("::warning::" in str(c) for c in imprimir.call_args_list))

    def test_layout_alterado_mantem_o_pl(self):
        ajuda = TestColetarComSubstitutivos()
        pares = {2025: [ajuda.par(501, 1, 2025)]}
        estat, salvos, _ = ajuda.rodar(pares, 1, lambda url: ler_fixture("siscam", "detalhe_arquivos_layout_alterado.html"))
        self.assertEqual(estat["falhas"], 1)
        self.assertEqual(salvos[2025][501], pares[2025][0][1])

    def test_substitutivo_preserva_arquivos_vazios_e_falha_de_layout(self):
        anterior = substitutivo(arquivos=ESPERADOS["substitutivo_266596"])
        ref = TestColetarSubstitutivos.REF
        with contextlib.redirect_stderr(io.StringIO()) as erros, mock.patch.object(siscam, "baixar", return_value=""):
            [obtido] = siscam.coletar_substitutivos([ref], [anterior])
        self.assertEqual(obtido["arquivos"], anterior["arquivos"])
        self.assertIn("::warning::", erros.getvalue())
        with silencioso(), mock.patch.object(siscam, "baixar", return_value=ler_fixture("siscam", "detalhe_arquivos_layout_alterado.html")):
            self.assertEqual(siscam.coletar_substitutivos([ref], [anterior]), [anterior])

    def test_cli_cache_offline_idempotente_e_sem_outros_campos(self):
        with tempfile.TemporaryDirectory() as temp:
            raiz = Path(temp)
            dados, cache = raiz / "proposicoes", raiz / "cache"
            cache.mkdir()
            _, reg = TestColetarComSubstitutivos.par(127858, 140, 2021, substitutivos=[substitutivo()])
            _, ausente = TestColetarComSubstitutivos.par(9, 2, 2021)
            for id_, nome in FIXTURES_DETALHE.items():
                (cache / f"{id_}.html").write_text(ler_fixture("siscam", nome), encoding="utf-8")
            with mock.patch.object(siscam, "DIR_DADOS", dados), mock.patch.object(siscam, "baixar") as baixar, \
                    mock.patch.object(sys, "argv", ["siscam", "--arquivos-do-cache", str(cache)]):
                siscam.salvar_ano(2021, {127858: reg, 9: ausente})
                siscam.main()
                primeira = (dados / "2021.json").read_bytes()
                siscam.main()
                self.assertEqual((dados / "2021.json").read_bytes(), primeira)
                lidos = siscam.carregar_ano(2021)
                baixar.assert_not_called()
            self.assertEqual(lidos[9], ausente)
            self.assertEqual(lidos[127858], {**reg, "arquivos": ESPERADOS["pl_127858"],
                             "substitutivos": [{**reg["substitutivos"][0], "arquivos": ESPERADOS["substitutivo_266596"]}]})

    def test_cli_cache_respeita_anos(self):
        with mock.patch.object(sys, "argv", ["siscam", "--arquivos-do-cache", "cache", "--anos", "2024-2025"]), \
                mock.patch.object(siscam, "arquivos_do_cache") as preencher:
            siscam.main()
        preencher.assert_called_once_with(Path("cache"), [2024, 2025])


if __name__ == "__main__":
    unittest.main()
