"""Regras de sessões offline: casos sintéticos, HTML real e regressões dos dados."""
from __future__ import annotations

import contextlib
import copy
import io
import os
import unittest
from collections import Counter
from unittest import mock

from coletor import regras_sessoes as R
from coletor import sessoes as S
from tests.apoio import RAIZ, ler_fixture


# ---- dados sintéticos ----------------------------------------------------------
def frequencia(nome: str, situacao: str, momento: str = "Abertura") -> dict:
    return {"nome": nome, "situacao": situacao, "momento": momento}


def sessao(**campos) -> dict:
    return {"id": 1, "ano": 2026, "data": "2026-03-25", "hora": "16:00", "tipo": "ordinaria",
            "titulo": "1ª Sessão Ordinária de 2026", "frequencia": [], "votacoes": [], "pauta": [], **campos}


def votacao(favor: int = 11, contra: int = 6, **campos) -> dict:
    votos = ([{"nome": f"Favor {n}", "voto": "Favor"} for n in range(favor)]
             + [{"nome": f"Contra {n}", "voto": "Contra"} for n in range(contra)])
    return {"tipo_votacao": "Nominal", "tipo_documento": "Projeto de Lei", "resultado": "Veto Mantido",
            "id_documento": 123, "documento": "Projeto de Lei Nº 00280/2025", "numero": "280/2025",
            "votos": votos, "totais": None, **campos}


def passo(texto: str, **campos) -> dict:
    return {"seq": 1, "destinatario": "Plenário", "remetente": "Secretaria Mesa Diretora",
            "objetivo": "Ordem do Dia - Discussão Única", "data_resposta": "2026-03-25",
            "enviado": "2026-03-25", "resultado": "Veto Mantido", "observacao": texto, "complemento": "", **campos}


def documento(*passos: dict, **campos) -> dict:
    return {"id": 123, "tramitacoes": list(passos), "substitutivos": [], **campos}


def parecer_ccj(resultado: str, dia: str = "2026-03-20", **campos) -> dict:
    return passo("", **{"destinatario": "Comissão Permanente de Constituição e Justiça e Redação Final",
                        "objetivo": "Exarar Parecer", "resultado": resultado,
                        "data_resposta": dia, "enviado": dia, **campos})


def fixture(id_sessao: int) -> dict:
    with contextlib.redirect_stderr(io.StringIO()):
        return S.parse_detalhe(ler_fixture("siscam", f"sessao_{id_sessao}.html"))


# ---- presença e deduplicação ----------------------------------------------------
class TestPresenca(unittest.TestCase):
    def test_categorias_e_denominador_individual(self):
        lista = [frequencia("P", "Presença"), frequencia("C", "Consignado"), frequencia("V", "Ausência"),
                 frequencia("J", "Ausência Justificada"), frequencia("A", "Ausência"),
                 frequencia("L", "Licença"), frequencia("?", "Outro texto")]
        s = sessao(frequencia=lista, votacoes=[votacao(votos=[{"nome": "V", "voto": "Branco"},
                                                           {"nome": "Só voto", "voto": "Favor"}])])
        resultado = R.presencas_da_sessao(s)
        pessoas = resultado["pessoas"]
        self.assertEqual([pessoas[R.slug(n)]["categoria"] for n in ("P", "C", "V", "J", "A", "L", "?")],
                         ["P", "C", "V", "J", "A", "L", "?"])
        self.assertEqual(sum(p["denominador"] for p in pessoas.values()), 5)
        self.assertEqual(sum(p["presente"] for p in pessoas.values()), 3)
        self.assertTrue(pessoas["l"]["licenca"])
        self.assertNotIn("so-voto", pessoas)
        self.assertIn("frequência desconhecida", resultado["qualidade"][0])

    def test_melhor_evidencia_em_momentos_distintos_e_lista_duplicada(self):
        ordem = [("Presença", "P"), ("Consignado", "C"), ("Ausência", "V"),
                 ("Licença", "L"), ("Ausência Justificada", "J"), ("Ausência", "A")]
        for inicio in range(len(ordem)):
            with self.subTest(categoria=ordem[inicio][1]):
                linhas = [frequencia("Pessoa", texto, f"Momento {n}") for n, (texto, _) in enumerate(ordem[inicio:])]
                votos = [votacao(votos=[{"nome": "Pessoa", "voto": "Favor"}])] if inicio <= 2 else []
                s = sessao(frequencia=linhas + linhas, votacoes=votos)
                r = R.presencas_da_sessao(s)
                self.assertEqual(r["pessoas"]["pessoa"]["categoria"], ordem[inicio][1])
                self.assertEqual(len(r["pessoas"]), 1)
                self.assertEqual(r["duplicatas"][0]["linhas"], 2 * len(linhas))

    def test_v_exige_voto_substantivo_nominal_deduplicado(self):
        for texto in ("Favor", "Contra", "Abstenção", "Branco", "Nulo", "Presidente", "Ausente", "Outro"):
            with self.subTest(voto=texto):
                s = sessao(frequencia=[frequencia("Pessoa", "Ausência Justificada")],
                           votacoes=[votacao(votos=[{"nome": "Pessoa", "voto": texto}])])
                esperado = "V" if texto in R.VOTOS_SUBSTANTIVOS else "J"
                self.assertEqual(R.presencas_da_sessao(s)["pessoas"]["pessoa"]["categoria"], esperado)
        s["votacoes"] = [votacao(tipo_votacao="Simbólica", votos=[{"nome": "Pessoa", "voto": "Favor"}])]
        self.assertEqual(R.presencas_da_sessao(s)["pessoas"]["pessoa"]["categoria"], "J")
        s["votacoes"] = [votacao(votos=[{"nome": "Pessoa", "voto": "Favor"}, {"nome": "Pessoa", "voto": "Contra"}])]
        self.assertEqual(R.presencas_da_sessao(s)["pessoas"]["pessoa"]["categoria"], "J")

    def test_lista_inteira_duplicada_no_mesmo_momento(self):
        lista = [frequencia(f"Pessoa {n}", "Presença") for n in range(21)]
        s = sessao(frequencia=lista + lista)
        r = R.presencas_da_sessao(s)
        self.assertEqual(len(r["pessoas"]), 21)
        self.assertEqual(sum(p["denominador"] for p in r["pessoas"].values()), 21)
        self.assertEqual(len(r["duplicatas"]), 21)

    def test_so_deliberativas_com_lista(self):
        for tipo in ("solene", "especial", "instalacao", "audiencia_publica", "desconhecido"):
            self.assertFalse(R.presencas_da_sessao(sessao(tipo=tipo, frequencia=[frequencia("A", "Presença")]))["incluida"])
        r = R.presencas_da_sessao(sessao())
        self.assertFalse(r["incluida"])
        self.assertEqual(r["qualidade"], ["sessão sem lista de frequência"])
        self.assertTrue(R.presencas_da_sessao(sessao(tipo="extraordinaria", frequencia=[frequencia("A", "Presença")]))["incluida"])

    def test_resumo_nao_inventa_faltas_nem_conta_licenca(self):
        sessoes = [sessao(id=1, frequencia=[frequencia("A", "Consignado")]),
                   sessao(id=2, frequencia=[frequencia("A", "Licença"), frequencia("B", "Ausência")]),
                   sessao(id=3, frequencia=[frequencia("A", "Texto desconhecido")]),
                   sessao(id=4), sessao(id=5, tipo="especial", frequencia=[frequencia("B", "Presença")])]
        r = R.resumo_presencas(sessoes)
        self.assertEqual((r["a"]["presentes"], r["a"]["denominador"], r["a"]["licencas"]), (1, 1, 1))
        self.assertEqual((r["b"]["presentes"], r["b"]["denominador"]), (0, 1))


class TestVotos(unittest.TestCase):
    def test_prioridades_conflitos_e_totais_deduplicados(self):
        pares = [("A", "Ausente"), ("A", "Presidente"), ("B", "Ausente"), ("B", "Favor"), ("B", "Favor"),
                 ("C", "Favor"), ("C", "Contra"), ("D", "Abstenção"), ("E", "Branco"), ("F", "Nulo"),
                 ("G", "Presidente"), ("G", "Contra"), ("H", "Texto novo")]
        v = votacao(votos=[{"nome": n, "voto": texto} for n, texto in pares])
        r = R.deduplicar_votos(v)
        self.assertEqual(r["votos"], {"a": "Presidente", "b": "Favor", "c": "indeterminado", "d": "Abstenção",
                                      "e": "Branco", "f": "Nulo", "g": "Presidente", "h": "indeterminado"})
        self.assertEqual(r["totais"], {"favor": 1, "contra": 0, "abstencao": 1, "branco": 1, "nulo": 1,
                                       "ausentes": 0, "presidente": 2, "indeterminado": 2})
        self.assertEqual(len(r["duplicatas"]), 4)
        self.assertEqual(len(r["qualidade"]), 2)
        self.assertEqual(r, R.deduplicar_votos({**v, "votos": list(reversed(v["votos"]))}))

    def test_nao_nominal_ou_sem_votos_ficam_fora(self):
        for v in (votacao(tipo_votacao="Simbólica"), votacao(votos=[])):
            self.assertFalse(R.votacao_nominal(v))
            self.assertEqual(R.deduplicar_votos(v)["votos"], {})
            self.assertEqual(R.sentido_voto(v, sessao(), None)["motivos"], ["votação não nominal ou sem votos"])

    def test_classe_calibravel_maioria_e_divergencia(self):
        casos = [(20, 0, 0, "unanime"), (0, 20, 0, "unanime"), (15, 2, 0, "dissenso"),
                 (15, 0, 2, "dissenso"), (15, 3, 0, "dividida"), (15, 0, 3, "dividida")]
        for favor, contra, abstencao, classe in casos:
            self.assertEqual(R.classe_votacao({"favor": favor, "contra": contra, "abstencao": abstencao}), classe)
        self.assertEqual([R.classe_votacao({"favor": 11, "contra": 3}, minimo) for minimo in (2, 3, 4, 5)],
                         ["dividida", "dividida", "dissenso", "dissenso"])
        with self.assertRaises(ValueError):
            R.classe_votacao({}, 0)
        self.assertEqual(R.maioria({"favor": 8, "contra": 7}), "Favor")
        self.assertEqual(R.maioria({"favor": 7, "contra": 8}), "Contra")
        self.assertIsNone(R.maioria({"favor": 7, "contra": 7}))
        self.assertTrue(R.divergencia("Contra", {"favor": 8, "contra": 7}))
        self.assertTrue(R.divergencia("Favor", {"favor": 7, "contra": 8}))
        for voto in ("Favor", "Abstenção", "Ausente", "Presidente", "Branco", "Nulo", "indeterminado"):
            self.assertFalse(R.divergencia(voto, {"favor": 8, "contra": 7}))
        self.assertFalse(R.divergencia("Contra", {"favor": 7, "contra": 7}))


# ---- sentido e consistência -----------------------------------------------------
class TestSentido(unittest.TestCase):
    def test_resultado_oficial_sem_depender_do_texto(self):
        casos = [
            (12, 5, "Aprovado", "favor_aprova"), (6, 8, "Aprovado", "favor_rejeita"),
            (12, 5, "Rejeitado", "favor_rejeita"), (6, 8, "Rejeitado", "favor_aprova"),
        ]
        for tipo in ("Projeto de Lei", "Projeto de Decreto Legislativo", "Projeto de Resolução", "Emenda"):
            for favor, contra, resultado, esperado in casos:
                with self.subTest(tipo=tipo, resultado=resultado, favor=favor):
                    r = R.sentido_voto(votacao(favor, contra, resultado=resultado, tipo_documento=tipo), sessao(), None)
                    self.assertEqual((r["sentido"], r["fonte"]), (esperado, "resultado_oficial"), r)
        self.assertEqual(R.sentido_voto(votacao(14, 5, resultado="Rejeitado", tipo_documento="Emendas 2 e 3"),
                                       sessao(), None)["sentido"], "favor_rejeita")

    def test_vetos_com_lado_de_onze_pelo_resultado(self):
        casos = [
            (11, 6, "Veto Mantido", "favor_mantem"), (6, 11, "Veto Mantido", "favor_derruba"),
            (11, 5, "Veto Rejeitado", "favor_derruba"), (5, 11, "Veto Rejeitado", "favor_mantem"),
            (11, 5, "Veto Derrubado", "favor_derruba"),
        ]
        for favor, contra, resultado, esperado in casos:
            r = R.sentido_voto(votacao(favor, contra, resultado=resultado), sessao(), documento())
            self.assertEqual((r["sentido"], r["fonte"]), (esperado, "resultado_oficial"), r)
        self.assertEqual(R.QUORUM_DERRUBADA_VETO, 11)
        self.assertEqual(R.ROTULO_QUORUM_VETO, "maioria absoluta (21 vereadores)")

    def test_veto_ambiguo_usa_direcao_e_decisao_na_data_sem_contagens(self):
        casos = [(8, 7, "APROVADO", "MANUTENÇÃO", "favor_mantem"),
                 (8, 7, "APROVADO", "DERRUBADA", "favor_derruba"),
                 (8, 7, "REJEITADO", "MANUTENÇÃO", "favor_derruba"),
                 (8, 7, "REJEITADO", "REJEIÇÃO", "favor_mantem"),
                 (4, 10, "REJEITADO", "DERRUBADA", "favor_derruba")]
        for favor, contra, decisao, direcao, esperado in casos:
            texto = f"{decisao} O PARECER PELA {direcao} DO VETO COM 99 VOTOS FAVORÁVEIS"
            r = R.sentido_voto(votacao(favor, contra), sessao(), documento(passo(texto)))
            self.assertEqual((r["sentido"], r["fonte"]), (esperado, "texto_veto_ambiguo"), r)
            self.assertTrue(r["notas"])

    def test_inconsistente_so_impossibilidade_logica_ou_totais(self):
        for favor, contra, resultado in ((10, 6, "Veto Derrubado"), (0, 0, "Veto Rejeitado"), (11, 11, "Veto Mantido")):
            v = votacao(favor, contra, resultado=resultado)
            if not v["votos"]:
                v["votos"] = [{"nome": "Pessoa", "voto": "Abstenção"}]
            r = R.sentido_voto(v, sessao(), documento())
            self.assertEqual(r["sentido"], "inconsistente", r)
        r = R.sentido_voto(votacao(totais={"favor": 99}), sessao(), documento())
        self.assertEqual(r["sentido"], "inconsistente")
        self.assertIn("não fecha", r["motivos"][0])
        v = votacao(votos=[{"nome": "A", "voto": "Favor"}, {"nome": "A", "voto": "Favor"}],
                    resultado="Aprovado", totais={"favor": 2})
        self.assertEqual(R.sentido_voto(v, sessao(), None)["sentido"], "favor_aprova")

    def test_texto_mistura_votacoes_e_gera_notas_sem_excluir(self):
        texto = "REJEITADO O PARECER PELA DERRUBADA DO VETO COM 11 VOTOS CONTRÁRIOS. APROVADO O PARECER FAVORÁVEL COM 17 VOTOS FAVORÁVEIS."
        r = R.sentido_voto(votacao(), sessao(), documento(passo(texto)))
        self.assertEqual(r["sentido"], "favor_mantem")
        self.assertEqual(r["motivos"], [])
        self.assertTrue(any("registra estes votos como 'Favor'" in n for n in r["notas"]))
        self.assertTrue(any("favor=17" in n for n in r["notas"]))

    def test_votos_pela_derrubada_nao_sao_direcao_de_parecer(self):
        textos = ["HOUVE 4 VOTOS PELA DERRUBADA DO VETO", "REJEITADO O PARECER COM 4 VOTOS PELA DERRUBADA DO VETO"]
        for texto in textos:
            r = R.sentido_voto(votacao(4, 10), sessao(), documento(passo(texto)))
            self.assertEqual(r["sentido"], "indeterminado", r)
        r = R.sentido_voto(votacao(), sessao(), None)
        self.assertEqual(r["sentido"], "indeterminado")
        self.assertIn("não encontrado", r["motivos"][0])

    def test_data_resposta_prevalece_sobre_enviado_e_comissao_nao_e_plenario(self):
        texto = "APROVADO O PARECER PELA MANUTENÇÃO DO VETO"
        for p in (passo(texto, data_resposta="2026-03-26"),
                  passo(texto, destinatario="CCJRF", objetivo="Exarar Parecer")):
            r = R.sentido_voto(votacao(8, 7), sessao(), documento(p))
            self.assertEqual(r["sentido"], "indeterminado", r)
        r = R.sentido_voto(votacao(8, 7), sessao(), documento(passo(texto, data_resposta=None)))
        self.assertEqual(r["sentido"], "favor_mantem")

    def test_substitutivo_e_direcoes_conflitantes(self):
        sub = documento(passo("APROVADO O PARECER PELA MANUTENÇÃO DO VETO"), id=456)
        doc = documento(substitutivos=[sub])
        r = R.sentido_voto(votacao(8, 7), sessao(), doc)
        self.assertEqual(r["sentido"], "favor_mantem")
        self.assertEqual(r["evidencias"][0]["id_documento"], 456)
        doc["tramitacoes"] = [passo("APROVADO O PARECER PELA DERRUBADA DO VETO")]
        r = R.sentido_voto(votacao(8, 7), sessao(), doc)
        self.assertEqual(r["sentido"], "indeterminado")
        self.assertIn("conflitantes", r["motivos"][0])

    def test_empate_sem_resultado_e_quorum_qualificado_nao_usam_parecer_antigo(self):
        doc = documento(parecer_ccj("Contrário"))
        casos = [(votacao(7, 7, resultado="Aprovado"), "empate"),
                 (votacao(resultado="Retirado"), "não reconhecido"),
                 (votacao(12, 5, resultado="Rejeitado", tipo_documento="Projeto de Emenda à Lei Orgânica"), "quórum qualificado")]
        for v, motivo in casos:
            r = R.sentido_voto(v, sessao(), doc)
            self.assertEqual(r["sentido"], "indeterminado", r)
            self.assertIn(motivo, r["motivos"][0])

    def test_gancho_curadoria_prioritario_mas_nao_desliga_consistencia(self):
        doc = documento(passo("PARECER PELA DERRUBADA DO VETO"))
        r = R.sentido_voto(votacao(), sessao(), doc, sentido_curado="favor_mantem")
        self.assertEqual((r["sentido"], r["fonte"]), ("favor_mantem", "curadoria"))
        r = R.sentido_voto(votacao(resultado="Veto Rejeitado"), sessao(), doc, sentido_curado="favor_mantem")
        self.assertEqual(r["sentido"], "inconsistente")
        r = R.sentido_voto(votacao(resultado="Aprovado"), sessao(), None, sentido_curado="favor_rejeita")
        self.assertEqual(r["sentido"], "inconsistente")
        self.assertIn("sem quórum qualificado", r["motivos"][0])
        r = R.sentido_voto(votacao(resultado="Rejeitado", tipo_documento="Projeto de Emenda à Lei Orgânica"),
                           sessao(), None, sentido_curado="favor_aprova")
        self.assertEqual((r["sentido"], r["fonte"]), ("favor_aprova", "curadoria"))
        with self.assertRaises(ValueError):
            R.sentido_voto(votacao(), sessao(), doc, sentido_curado="favor_aprova")

    def test_materia_e_rotulos(self):
        for tipo, materia in (("Projeto de Lei", "pl"), ("Projeto de Decreto Legislativo", "pdl"),
                              ("Projeto de Resolução", "resolucao"), ("Moção", "outra")):
            self.assertEqual(R.materia_votacao(votacao(resultado="Aprovado", tipo_documento=tipo)), materia)
        self.assertEqual(R.materia_votacao(votacao()), "veto")
        for voto, sentido, esperado in (("Favor", "favor_mantem", "votou para manter o veto"),
                                        ("Contra", "favor_mantem", "votou para derrubar o veto"),
                                        ("Favor", "favor_derruba", "votou para derrubar o veto"),
                                        ("Contra", "favor_derruba", "votou para manter o veto"),
                                        ("Favor", "favor_aprova", "votou a favor do projeto"),
                                        ("Favor", "favor_rejeita", "votou contra o projeto"),
                                        ("Contra", "favor_rejeita", "votou a favor do projeto")):
            self.assertEqual(R.rotulo_voto(voto, sentido, "pl"), esperado)
        for voto, esperado in (("Abstenção", "absteve-se"), ("Ausente", "ausente nesta votação"),
                               ("Presidente", "presidia a sessão"), ("Branco", "votou em branco"), ("Nulo", "voto nulo")):
            self.assertEqual(R.rotulo_voto(voto, "inconsistente", "veto"), esperado)
        self.assertEqual(R.rotulo_voto("Favor", "indeterminado", "veto"), "Favor ao parecer (sentido não determinado)")
        self.assertEqual(R.rotulo_voto("Favor", "inconsistente", "veto"), "Favor ao parecer (sentido não determinado)")
        self.assertEqual(R.rotulo_voto("Contra", "indeterminado", "veto"), "Contra o parecer (sentido não determinado)")
        self.assertEqual(R.rotulo_voto("Favor", "favor_aprova", "pdl"), "votou a favor do projeto de decreto legislativo")
        self.assertEqual(R.rotulo_voto("Contra", "favor_aprova", "resolucao"), "votou contra o projeto de resolução")


# ---- tempo, identidade e relatório ----------------------------------------------
class TestTempoEAuditoria(unittest.TestCase):
    def test_faixas(self):
        casos = [(0, "até 7"), (7, "até 7"), (8, "8–30"), (30, "8–30"), (31, "31–90"), (90, "31–90"),
                 (91, "91–180"), (180, "91–180"), (181, "181–365"), (365, "181–365"), (366, ">365"),
                 (None, "ainda não pautado")]
        for dias, faixa in casos:
            self.assertEqual(R.faixa_leitura_votacao(dias), faixa)
        with self.assertRaises(ValueError):
            R.faixa_leitura_votacao(-1)

    def test_primeira_leitura_e_primeira_sessao_posterior_por_id(self):
        def item(id_doc, fase):
            return {"id_documento": id_doc, "fase": fase, "tipo_documento": "Projeto de Lei"}
        sessoes = [sessao(id=10, ano=2025, data="2025-12-30", pauta=[item(123, "Leitura"), item(123, "Votação"),
                                                                     item(999, "Leitura"), item(None, "Leitura")]),
                   sessao(id=11, ano=2025, data="2025-12-31", pauta=[item(123, "Leitura")]),
                   sessao(id=12, data="2026-01-06", pauta=[item(123, "Votação"), item(123, "Votação")]),
                   sessao(id=13, data="2026-01-07", pauta=[item(123, "Votação"), item(555, "Votação")])]
        r = R.tempos_leitura_votacao(list(reversed(sessoes)))
        self.assertEqual(r[123], {"leitura": "2025-12-30", "sessao_leitura": 10, "votacao": "2026-01-06",
                                  "sessao_votacao": 12, "ano": 2025, "dias": 7, "faixa": "até 7",
                                  "confiavel": False, "motivo": R.MOTIVO_LEITURA_VOTACAO})
        self.assertEqual(r[999]["faixa"], "sem par observado")
        self.assertEqual(set(r), {123, 999})
        mesmo_dia = [sessao(id=1, pauta=[item(123, "Leitura")]),
                     sessao(id=2, hora="16:30", pauta=[item(123, "Votação")])]
        self.assertEqual(R.tempos_leitura_votacao(mesmo_dia)[123]["dias"], 0)
        mesmo_dia[1]["hora"] = None
        self.assertIsNone(R.tempos_leitura_votacao(mesmo_dia)[123]["dias"])

    def test_tempo_restringe_materias_liga_so_substitutivos_explicitos(self):
        docs = {123: documento(id=123, tipo="pl", substitutivos=[{"id": 456}]),
                456: documento(id=456, tipo="pl"), 789: documento(id=789, tipo="mocao")}
        sessoes = [sessao(id=1, data="2026-03-01", pauta=[{"id_documento": 123, "fase": "Leitura"},
                                                        {"id_documento": 789, "fase": "Leitura"}]),
                   sessao(id=2, data="2026-03-08", pauta=[{"id_documento": 456, "fase": "Discussão Única"},
                                                        {"id_documento": 789, "fase": "Votação"}])]
        tempos = R.tempos_leitura_votacao(sessoes, docs)
        self.assertEqual(set(tempos), {123})
        self.assertEqual(tempos[123]["dias"], 7)
        self.assertFalse(tempos[123]["confiavel"])
        diagnostico = R.diagnostico_pautas(sessoes, docs)
        self.assertFalse(diagnostico["confiavel"])
        self.assertIn("id 456 → 123", diagnostico["exemplos_vinculos"][0])
        sessoes[1]["pauta"][0]["tipo_documento"] = "Veto"
        self.assertIsNone(R.tempos_leitura_votacao(sessoes, docs)[123]["dias"])

    def test_nomes_sem_fuzzy_reusa_indice_do_modelo(self):
        cfg = {"legislaturas": [{"eleitos": [{"siscam": "CARLOS VAZ - CASOTA", "nome": "Casota"}]}],
               "apelidos": {"SUPLENTE COMPLETO": "Suplente"}, "nao_vereador": ["PREFEITO"]}
        pessoas, indice = R.indice_nomes(cfg, [{"autoria": [{"nome": "OUTRO SUPLENTE", "origem": "Vereador"},
                                                          {"nome": "PREFEITO", "origem": "Prefeito"}]}])
        self.assertEqual(indice["carlos-vaz"], "carlos-vaz-casota")
        self.assertNotIn("casota", indice)
        self.assertNotIn("carlos-vaz-casotta", indice)
        self.assertNotIn("prefeito", pessoas)
        self.assertIn("outro-suplente", pessoas)
        s = sessao(frequencia=[frequencia("Carlos Vaz", "Ausência"), frequencia("CARLOS VAZ - CASOTA", "Consignado")])
        self.assertEqual(len(R.presencas_da_sessao(s, indice)["pessoas"]), 1)

    def test_auditoria_deterministica_sem_rede_nem_mutacao(self):
        cfg = {"legislaturas": [{"id": "2025-2028", "inicio": "2025-01-01", "fim": "2028-12-31",
                                 "eleitos": [{"siscam": "Pessoa conhecida", "nome": "Pessoa"}]}]}
        v = votacao(votos=[{"nome": "Pessoa conhecida", "voto": "Favor"}, {"nome": "Pessoa conhecida", "voto": "Favor"},
                          {"nome": "Não casado", "voto": "Favor"}])
        s = sessao(frequencia=[frequencia("Pessoa conhecida", "Texto novo"), frequencia("Não casado", "Presença")], votacoes=[v],
                   pauta=[{"id_documento": 123, "fase": "Leitura", "tipo_documento": "Projeto de Lei"}])
        fontes = ([s, sessao(id=2, data="2026-03-26")], {}, cfg)
        antes = copy.deepcopy(fontes)
        with mock.patch("coletor.siscam.baixar", side_effect=AssertionError("rede proibida")):
            texto = R.auditar(*fontes)
        self.assertEqual(fontes, antes)
        self.assertEqual(texto, R.auditar(list(reversed(fontes[0])), {}, cfg))
        for trecho in ("Deliberativas com lista: 1; sem lista: 1", "Nomes não casados: Não casado: 2",
                       "Distribuição de menor", "Distribuição de abstenções", "Indeterminados (motivos): 1",
                       "não encontrado", "Duplicatas resolvidas (por pessoa/grupo): 1",
                       "frequência desconhecida", "NÃO CONFIÁVEL", "sem mediana", "não membro da legislatura",
                       "resultado oficial:", "texto (veto ambíguo):", "Notas de conferência"):
            self.assertIn(trecho, texto)
        for minimo in range(2, 6):
            self.assertIn(f"Classes com minimo={minimo}:", texto)

    def test_nao_membros_e_mandatos_de_outra_legislatura_ficam_fora(self):
        cfg = {"legislaturas": [{"id": "2021-2024", "inicio": "2021-01-01", "fim": "2024-12-31",
                                 "eleitos": [{"siscam": "Membro antigo", "nome": "Antigo"}]},
                                {"id": "2025-2028", "inicio": "2025-01-01", "fim": "2028-12-31",
                                 "eleitos": [{"siscam": "Membro atual", "nome": "Atual"}]}]}
        pessoas, _ = R.indice_nomes(cfg, [{"data": "2026-01-01", "ano": 2026,
                                         "autoria": [{"nome": "Suplente atual", "origem": "Vereador"}]}])
        s = sessao(frequencia=[frequencia(n, "Presença") for n in ("Membro antigo", "Membro atual", "Convidado", "Suplente atual")])
        membros = R.indice_membros(s, pessoas, cfg)
        r = R.presencas_da_sessao(s, membros)
        self.assertEqual(set(r["pessoas"]), {"membro-atual", "suplente-atual"})
        self.assertEqual(len(r["qualidade"]), 2)
        v = votacao(votos=[{"nome": n, "voto": "Favor"} for n in ("Membro atual", "Convidado")], resultado="Aprovado")
        self.assertEqual(R.deduplicar_votos(v, membros)["totais"]["favor"], 1)
        self.assertEqual(R.sentido_voto(v, s, None, indice=membros)["totais"]["favor"], 1)
        resumo = R.resumo_presencas([s], pessoas=pessoas, cfg=cfg)
        self.assertEqual(set(resumo), {"membro-atual", "suplente-atual"})

    def test_cli_leitura_somente(self):
        with mock.patch.object(R, "carregar_fontes", return_value=([], {}, {})) as carregar, contextlib.redirect_stdout(io.StringIO()) as saida:
            self.assertEqual(R.main(["--auditoria"]), 0)
        carregar.assert_called_once_with()
        self.assertIn("0 sessões", saida.getvalue())
        with mock.patch.object(R, "carregar_fontes", side_effect=ValueError("JSON inválido")), contextlib.redirect_stderr(io.StringIO()) as erro:
            self.assertEqual(R.main(["--auditoria"]), 1)
        self.assertIn("JSON inválido", erro.getvalue())


# ---- fixtures reais e dados versionados -----------------------------------------
class TestFixtures(unittest.TestCase):
    def test_22344_presidente_duplicado_nao_e_ausente(self):
        s = fixture(22344)
        v = s["votacoes"][4]
        r = R.deduplicar_votos(v)
        self.assertEqual(r["votos"]["milton-carlos-da-silva-lopes"], "Presidente")
        self.assertEqual(r["totais"]["ausentes"], v["totais"]["ausentes"] - 1)
        self.assertEqual(len(r["votos"]), len(v["votos"]) - 1)
        self.assertEqual(len(r["duplicatas"]), 1)

    def test_11850_consignado_licenca_e_pl_nao_coletado(self):
        s = fixture(11850)
        r = R.presencas_da_sessao(s)
        self.assertEqual(r["pessoas"]["atratino-cortes-coutinho-neto"]["categoria"], "C")
        self.assertEqual(sum(p["licenca"] for p in r["pessoas"].values()), 1)
        self.assertEqual(sum(p["denominador"] for p in r["pessoas"].values()), 20)
        self.assertEqual(R.classe_votacao(R.deduplicar_votos(s["votacoes"][0])["totais"]), "dividida")  # 3 abstenções
        analise = R.sentido_voto(s["votacoes"][0], s, None)
        self.assertEqual(s["votacoes"][0]["numero"], "2/2015")
        self.assertEqual(analise["sentido"], "indeterminado")

    def test_22367_placar_e_frequencia_deduplicados(self):
        s = fixture(22367)
        r = R.deduplicar_votos(s["votacoes"][0])
        self.assertEqual((r["totais"]["favor"], r["totais"]["contra"]), (11, 6))
        presencas = R.presencas_da_sessao(s)
        # São 22 nomes diferentes, não uma lista duplicada: não imponha 21 à frequência.
        self.assertEqual(len(presencas["pessoas"]), 22)
        self.assertEqual(Counter(p["categoria"] for p in presencas["pessoas"].values()), Counter({"P": 20, "J": 1, "C": 1}))
        texto = "APROVADO O PARECER PELA MANUTENÇÃO DO VETO, COM 11 VOTOS FAVORÁVEIS"
        r = R.sentido_voto(s["votacoes"][0], s, documento(passo(texto)))
        self.assertEqual(r["sentido"], "favor_mantem")

    @unittest.skipIf(os.environ.get("RADAR_COLETA") == "1", "dados mudam durante a coleta")
    def test_regressao_nos_dados_versionados(self):
        sessoes, documentos, _ = R.carregar_fontes(RAIZ)
        esperados = {"96/2024": "favor_mantem", "144/2024": "favor_derruba", "280/2025": "favor_mantem",
                     "135/2022": "favor_derruba", "57/2021": "favor_derruba", "31/2023": "favor_mantem"}
        encontrados = Counter()
        for s in sessoes:
            for v in s.get("votacoes") or []:
                numero = v.get("numero")
                if (R.materia_votacao(v) != "veto" and R.votacao_nominal(v)
                        and R._normalizar(v.get("resultado")).startswith(("aprovad", "rejeitad"))
                        and "emenda a lei organica" not in R._normalizar(v.get("tipo_documento"))):
                    with self.subTest(materia=v.get("documento"), sessao=s["id"]):
                        analise = R.sentido_voto(v, s, documentos.get(v.get("id_documento")))
                        self.assertIn(analise["sentido"], {"favor_aprova", "favor_rejeita"}, analise)
                if numero in esperados and R.materia_votacao(v) == "veto" and R.votacao_nominal(v):
                    with self.subTest(projeto=numero, sessao=s["id"]):
                        analise = R.sentido_voto(v, s, documentos.get(v.get("id_documento")))
                        self.assertEqual(analise["sentido"], esperados[numero], analise)
                        if numero in {"96/2024", "144/2024"}:
                            self.assertTrue(analise["notas"], analise)
                        if numero in {"57/2021", "31/2023"}:
                            self.assertEqual(analise["fonte"], "texto_veto_ambiguo", analise)
                        encontrados[numero] += 1
        self.assertEqual(set(encontrados), set(esperados), "todos os seis casos precisam existir na base")

    @unittest.skipIf(os.environ.get("RADAR_COLETA") == "1", "dados mudam durante a coleta")
    def test_investigacao_dos_dados_sem_inventar_vinculos_ou_mandato(self):
        sessoes, documentos, cfg = R.carregar_fontes(RAIZ)
        pessoas, _ = R.indice_nomes(cfg, list(documentos.values()))
        nome = "HENRIQUE DOS SANTOS VIEIRA LIMA"
        casos = [s for s in sessoes if any(f["nome"] == nome for f in s.get("frequencia") or [])]
        self.assertEqual(len(casos), 1)
        s = casos[0]
        self.assertEqual((s["id"], s["numero"], s["data"], s["tipo"]), (22263, 21, "2025-04-15", "ordinaria"))
        membros = R.indice_membros(s, pessoas, cfg)
        self.assertNotIn(R.slug(nome), R.presencas_da_sessao(s, membros)["pessoas"])
        self.assertTrue(any(nome in aviso and "não membro" in aviso for aviso in R.presencas_da_sessao(s, membros)["qualidade"]))
        self.assertFalse(any(v["nome"] == nome for ss in sessoes for vv in ss.get("votacoes") or [] for v in vv.get("votos") or []))
        # PL 1/2025: votação em 11/03 na tramitação, mas só a leitura aparece
        # na pauta HTML. Não é falta de ligar um substitutivo: não tem nenhum.
        pl = documentos[275545]
        self.assertEqual(pl["substitutivos"], [])
        self.assertTrue(any(p.get("data_resposta") == "2025-03-11" and "Aprovado" in p.get("resultado", "") for p in pl["tramitacoes"]))
        ocorrencias = [(ss["data"], p["fase"]) for ss in sessoes for p in ss.get("pauta") or [] if p.get("id_documento") == 275545]
        self.assertEqual(ocorrencias, [("2025-02-19", "Leitura")])
        self.assertEqual(R._vinculos_documentos(documentos)[266596], 127858)
        self.assertEqual(documentos[266596]["data"], "2024-03-14")
        self.assertTrue(any(p.get("data_resposta") == "2024-04-18" and p.get("resultado") == "Aprovado em Primeira Discussão"
                            for p in documentos[266596]["tramitacoes"]))
        self.assertFalse(any(p.get("id_documento") == 266596 for ss in sessoes for p in ss.get("pauta") or []))
        discussoes = [(ss["data"], p["id_documento"]) for ss in sessoes for p in ss.get("pauta") or []
                      if p.get("fase") == "Discussão Única"]
        self.assertEqual(len(discussoes), 3)
        self.assertEqual({d for d, _ in discussoes}, {"2021-10-20"})
        diagnostico = R.diagnostico_pautas(sessoes, documentos)
        self.assertTrue(any("id 275545" in lacuna and "2025-03-11" in lacuna for lacuna in diagnostico["lacunas_tramitacao"]))
        self.assertFalse(R.LEITURA_VOTACAO_CONFIAVEL)


if __name__ == "__main__":
    unittest.main()
