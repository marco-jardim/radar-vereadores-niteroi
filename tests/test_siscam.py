"""Testes do coletor do SISCAM: utilidades, parsing de páginas reais e derivações."""
from __future__ import annotations

import unittest

from coletor import siscam
from tests.apoio import ler_fixture, registro_versionado

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


if __name__ == "__main__":
    unittest.main()
