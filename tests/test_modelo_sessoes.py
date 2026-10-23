"""Agregação offline das sessões, com o mesmo cadastro de pessoas do site."""
from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from coletor import regras_sessoes as R
from coletor.site.modelo import montar_modelo, slug
from coletor.site.modelo_sessoes import montar_sessoes
from tests.apoio import RAIZ


# ---- fontes sintéticas ---------------------------------------------------------
LEG = "2025-2028"


def modelo_minimo(eleitos: tuple[str, ...] = ("Ana", "Bruno"),
                  suplentes: tuple[str, ...] = ("Suplente",)) -> dict:
    leg = {"id": LEG, "inicio": "2025-01-01", "fim": "2028-12-31",
           "eleitos": [{"siscam": n, "nome": n} for n in eleitos]}
    pessoas = {slug(n): {"slug": slug(n), "nome_siscam": n, "nome": n,
                         "mandatos": {LEG: {"eleito": n in eleitos}}}
               for n in (*eleitos, *suplentes)}
    return {"pessoas": pessoas, "legislaturas": [leg], "cfg": {"legislaturas": [leg]},
            "projetos": [], "documentos": []}


def frequencia(nome: str, situacao: str = "Presença") -> dict:
    return {"nome": nome, "situacao": situacao, "momento": "Abertura"}


def sessao(id_sessao: int = 1, **campos) -> dict:
    return {"id": id_sessao, "ano": 2026, "data": f"2026-03-{id_sessao:02d}",
            "hora": "16:00", "numero": id_sessao, "tipo": "ordinaria",
            "titulo": f"{id_sessao}ª Sessão Ordinária de 2026", "frequencia": [],
            "pauta": [], "votacoes": [], "observacoes": "", **campos}


def votacao(pares: list[tuple[str, str]], **campos) -> dict:
    return {"tipo_votacao": "Nominal", "tipo_documento": "Projeto de Lei",
            "id_documento": 123, "documento": "Projeto de Lei Nº 00001/2026",
            "numero": "1/2026", "resultado": "Aprovado", "totais": None,
            "votos": [{"nome": n, "voto": v} for n, v in pares], **campos}


# ---- presença e pessoas --------------------------------------------------------
class TestPresenca(unittest.TestCase):
    def test_denominador_individual_licenca_solene_v_e_lista_duplicada(self):
        lista = [frequencia("Ana"), frequencia("Bruno", "Ausência"), frequencia("Suplente")]
        registros = [sessao(1, frequencia=lista + lista),
                     sessao(2, frequencia=[frequencia("Ana", "Licença"), frequencia("Bruno", "Ausência")],
                            votacoes=[votacao([("Bruno", "Favor")])]),
                     sessao(3, tipo="solene", frequencia=[frequencia("Suplente")]),
                     sessao(4, frequencia=[frequencia("Ana", "Consignado")]), sessao(5)]
        resultado = montar_sessoes(modelo_minimo(), registros, {})
        pessoas = resultado["por_pessoa"]
        ana, bruno, suplente = (pessoas[s][LEG] for s in ("ana", "bruno", "suplente"))
        self.assertEqual((ana["presenca"]["denominador"], ana["presenca"]["presentes"], ana["presenca"]["L"]), (2, 2, 1))
        self.assertEqual((bruno["presenca"]["denominador"], bruno["presenca"]["presentes"], bruno["presenca"]["V"]), (2, 1, 1))
        self.assertEqual(suplente["presenca"]["denominador"], 1)
        self.assertIsNone(ana["presenca"]["pct"])
        self.assertEqual(ana["por_ano"][2026], ana["presenca"])
        self.assertEqual(len(resultado["qualidade"]["duplicados"]), 3)
        self.assertEqual(resultado["qualidade"]["sem_lista"][0]["sessao"], 5)
        self.assertFalse(resultado["sessoes"][2]["deliberativa"])
        self.assertEqual(resultado["cobertura"][2026],
                         {"listadas": 5, "com_frequencia": 4, "com_votacao": 1, "pendentes": 0})

    def test_uma_frequencia_sem_voto_nao_prova_composicao(self):
        modelo = modelo_minimo()
        modelo["pessoas"]["antigo"] = {"nome_siscam": "Antigo", "mandatos": {"2021-2024": {"eleito": True}}}
        nomes = ("Ana", "Antigo", "Convidado")
        registro = sessao(frequencia=[frequencia(n) for n in nomes],
                          votacoes=[votacao([("Ana", "Favor"), ("Antigo", "Ausente"), ("Convidado", "Presidente")])])
        resultado = montar_sessoes(modelo, [registro], {})
        self.assertNotIn("convidado", resultado["por_pessoa"])
        self.assertNotIn(LEG, resultado["por_pessoa"].get("antigo", {}))
        self.assertEqual(resultado["votacoes"][0]["votos"], {"ana": "Favor", "antigo": "Ausente", "convidado": "Presidente"})
        self.assertEqual(resultado["votacoes"][0]["totais"]["ausentes"], 1)
        avisos = resultado["qualidade"]["nao_membros"]
        self.assertEqual({a["nome"] for a in avisos}, {"Antigo", "Convidado"})
        self.assertTrue(all(a["sessao"] == 1 and a["motivo"] for a in avisos))
        self.assertEqual({a["motivo"] for a in avisos}, {"aparece em 1 sessão(ões) sem voto; não consta da composição"})

    def test_suplente_sem_pagina_com_tres_deliberativas_entra(self):
        modelo = modelo_minimo(suplentes=())
        modelo["cfg"]["apelidos"] = {"SUPLENTE NOVA": "Nome de exibição"}
        registros = [sessao(n, frequencia=[frequencia("SUPLENTE NOVA"), frequencia("SUPLENTE NOVA"),
                                          frequencia("Só duas")]) for n in range(1, 3)]
        registros += [sessao(3, frequencia=[frequencia("SUPLENTE NOVA")]),
                      sessao(4, tipo="solene", frequencia=[frequencia("Só duas")])]
        resultado = montar_sessoes(modelo, registros, {})
        suplente = resultado["por_pessoa"]["suplente-nova"][LEG]
        self.assertTrue(suplente["sem_pagina"])
        self.assertEqual((suplente["nome"], suplente["condicao"]), ("Nome de exibição", "suplente em exercício"))
        self.assertEqual(suplente["presenca"]["denominador"], 3)
        self.assertNotIn("so-duas", resultado["por_pessoa"])
        self.assertEqual({a["nome"] for a in resultado["qualidade"]["nao_membros"]}, {"Só duas"})
        self.assertTrue(all("aparece em 2 sessão(ões)" in a["motivo"] for a in resultado["qualidade"]["nao_membros"]))
        self.assertNotIn("suplente-nova", modelo["pessoas"])

    def test_suplente_sem_pagina_com_um_voto_substantivo_entra(self):
        for voto in sorted(R.VOTOS_SUBSTANTIVOS):
            with self.subTest(voto=voto):
                resultado = montar_sessoes(modelo_minimo(suplentes=()),
                    [sessao(votacoes=[votacao([("Nome Suplente Completo", voto)])])], {})
                suplente = resultado["por_pessoa"]["nome-suplente-completo"][LEG]
                self.assertTrue(suplente["sem_pagina"])
                self.assertEqual(suplente["nome"], "Nome Completo")
                self.assertEqual(suplente["participacao"]["votou"], 1)
                self.assertEqual(suplente["presenca"]["denominador"], 0)
                self.assertFalse(resultado["qualidade"]["nao_membros"])

    def test_eleito_antigo_segue_o_limiar_na_nova_legislatura(self):
        modelo = modelo_minimo(suplentes=())
        modelo["pessoas"]["antigo"] = {"nome_siscam": "Antigo", "mandatos": {"2021-2024": {"eleito": True}}}
        registros = [sessao(n, frequencia=[frequencia("Antigo")]) for n in range(1, 4)]
        resultado = montar_sessoes(modelo, registros, {})
        suplente = resultado["por_pessoa"]["antigo"][LEG]
        self.assertFalse(suplente["sem_pagina"])
        self.assertEqual(suplente["condicao"], "suplente em exercício")
        self.assertIsNone(resultado["mediana_presenca"][LEG])

    def test_mediana_so_de_eleitos_e_base_minima_de_dez(self):
        registros = [sessao(n, frequencia=[frequencia("Ana"), frequencia("Bruno", "Ausência"),
                                           frequencia("Suplente")]) for n in range(1, 11)]
        resultado = montar_sessoes(modelo_minimo(), registros, {})
        self.assertEqual(resultado["mediana_presenca"][LEG], 50)
        self.assertEqual(resultado["por_pessoa"]["ana"][LEG]["presenca"]["pct"], 100)
        self.assertEqual(resultado["por_pessoa"]["bruno"][LEG]["presenca"]["pct"], 0)
        curto = montar_sessoes(modelo_minimo(), registros[:9], {})
        self.assertIsNone(curto["mediana_presenca"][LEG])

    def test_pagina_antiga_com_autoria_de_vereador_na_nova_legislatura(self):
        modelo = modelo_minimo()
        modelo["pessoas"]["suplente"]["mandatos"] = {"2021-2024": {"eleito": False}}
        modelo["documentos"] = [{"id": 999, "ano": 2026, "data": "2026-02-01",
                                  "autores": [{"nome": "Suplente", "vereador": True},
                                              {"nome": "Convidado", "vereador": False}]}]
        registro = sessao(frequencia=[frequencia("Suplente"), frequencia("Convidado")])
        resultado = montar_sessoes(modelo, [registro], {})
        self.assertEqual(resultado["por_pessoa"]["suplente"][LEG]["presenca"]["denominador"], 1)
        self.assertNotIn("convidado", resultado["por_pessoa"])

    def test_por_ano_e_legislaturas_so_com_sessoes(self):
        modelo = modelo_minimo()
        modelo["legislaturas"].append({"id": "2029-2032", "inicio": "2029-01-01", "fim": "2032-12-31", "eleitos": []})
        registros = [sessao(1, ano=2025, data="2025-12-01", frequencia=[frequencia("Ana")]),
                     sessao(2, frequencia=[frequencia("Ana", "Ausência")], detalhe_pendente=True)]
        resultado = montar_sessoes(modelo, registros, {})
        self.assertEqual(resultado["anos"], [2025, 2026])
        self.assertEqual(resultado["legislaturas"], [{"id": LEG, "rotulo": LEG, "anos": [2025, 2026]}])
        self.assertEqual(resultado["por_pessoa"]["ana"][LEG]["por_ano"][2025]["presentes"], 1)
        self.assertEqual(resultado["cobertura"][2026]["pendentes"], 1)
        self.assertEqual(resultado["ritmo"][2025], {"2025-12": {"ordinaria": 1}})


# ---- votações ------------------------------------------------------------------
class TestVotacoes(unittest.TestCase):
    def test_presidente_duplicado_totais_classe_e_divergencia(self):
        nomes = ("Ana", "Bruno", "Caio", "Dora", "Eva", "Fabio", "Gabi", "Presidente")
        modelo = modelo_minimo(nomes, ())
        pares = [(n, "Favor" if i < 4 else "Contra") for i, n in enumerate(nomes[:-1])]
        pares += [("Presidente", "Ausente"), ("Presidente", "Presidente")]
        publicados = {"favor": 4, "contra": 3, "ausentes": 1, "presidente": 1}
        registro = sessao(frequencia=[frequencia(n) for n in nomes], votacoes=[votacao(pares, totais=publicados)])
        resultado = montar_sessoes(modelo, [registro], {})
        voto = resultado["votacoes"][0]
        self.assertEqual(voto["totais"], {"favor": 4, "contra": 3, "abstencao": 0, "ausentes": 0, "branco": 0, "nulo": 0})
        self.assertEqual((voto["classe"], voto["maioria"], voto["sentido"], voto["qualidade"]),
                         ("dividida", "Favor", "favor_aprova", "ok"))
        self.assertEqual(voto["votos"]["presidente"], "Presidente")
        self.assertEqual(voto["totais_oficiais"], publicados)
        self.assertIsNot(voto["totais_oficiais"], publicados)
        self.assertEqual(voto["rotulos"]["eva"], R.rotulo_voto("Contra", "favor_aprova", "pl"))
        self.assertEqual(resultado["por_pessoa"]["eva"][LEG]["divergencias"], ["1-123"])
        self.assertEqual(resultado["por_pessoa"]["ana"][LEG]["divergencias"], [])
        self.assertEqual(resultado["por_pessoa"]["eva"][LEG]["divididas"], 1)
        self.assertEqual(resultado["por_pessoa"]["presidente"][LEG]["participacao"],
                         {"votou": 0, "possiveis": 1, "presidindo": 1})
        self.assertEqual(resultado["por_pessoa"]["eva"][LEG]["como_votou"], {"pl": {"votou contra o projeto": 1}})
        self.assertEqual(len(resultado["qualidade"]["duplicados"]), 1)

    def test_participacao_exige_evidencia_de_exercicio_na_sessao(self):
        registro = sessao(frequencia=[frequencia("Ana"), frequencia("Bruno", "Licença")],
                          votacoes=[votacao([("Ana", "Favor"), ("Suplente", "Abstenção")])])
        resultado = montar_sessoes(modelo_minimo(), [registro], {})
        pessoas = resultado["por_pessoa"]
        self.assertEqual(pessoas["ana"][LEG]["participacao"], {"votou": 1, "possiveis": 1, "presidindo": 0})
        self.assertEqual(pessoas["bruno"][LEG]["participacao"]["possiveis"], 0)
        self.assertEqual(pessoas["suplente"][LEG]["participacao"], {"votou": 1, "possiveis": 1, "presidindo": 0})
        self.assertEqual(pessoas["suplente"][LEG]["presenca"]["denominador"], 0)

    def test_indeterminadas_conservam_divergencia_inconsistentes_nao(self):
        pares = [("Ana", "Favor"), ("Bruno", "Contra"), ("Suplente", "Favor")]
        votos = [votacao(pares, id_documento=1, resultado="Retirado"),
                 votacao(pares, id_documento=2, totais={"favor": 99}),
                 votacao(pares, tipo_votacao="Simbólica", id_documento=3),
                 votacao([], id_documento=4)]
        resultado = montar_sessoes(modelo_minimo(), [sessao(votacoes=votos)], {})
        self.assertEqual(len(resultado["votacoes"]), 2)
        bruno = resultado["por_pessoa"]["bruno"][LEG]
        self.assertEqual(bruno["divergencias"], ["1-1"])
        self.assertEqual(bruno["indeterminadas"], 1)
        self.assertEqual(bruno["como_votou"], {})
        placares = resultado["placares_por_ano"][2026]
        self.assertEqual((placares["dissenso"], placares["indeterminado"], placares["inconsistente"]), (2, 1, 1))
        self.assertTrue(resultado["qualidade"]["indeterminadas"][0]["motivo"])
        self.assertTrue(resultado["qualidade"]["inconsistentes"][0]["motivo"])
        inconsistente = next(v for v in resultado["votacoes"] if v["qualidade"] == "inconsistente")
        self.assertEqual(inconsistente["totais_oficiais"], {"favor": 99})
        self.assertEqual(inconsistente["totais"]["favor"], 2)

    def test_placar_integral_sem_pagina_ou_legislatura_correspondente(self):
        modelo = modelo_minimo(suplentes=())
        pares = [("Ana", "Favor"), ("Fora da composição", "Favor"), ("Outra pessoa", "Contra")]
        resultado = montar_sessoes(modelo, [sessao(ano=2020, data="2020-03-01", votacoes=[votacao(pares)])], {})
        voto = resultado["votacoes"][0]
        self.assertEqual((voto["totais"]["favor"], voto["totais"]["contra"]), (2, 1))
        self.assertEqual(voto["sentido"], "favor_aprova")
        self.assertEqual(resultado["por_pessoa"], {})
        self.assertIsNone(voto["totais_oficiais"])

    def test_veto_quorum_resumo_e_nota_da_tramitacao(self):
        nomes = tuple(f"Pessoa {n}" for n in range(21))
        modelo = modelo_minimo(nomes, ())
        pares = [(n, "Favor" if i < 11 else "Contra" if i < 17 else "Ausente" if i < 20 else "Presidente")
                 for i, n in enumerate(nomes)]
        texto = "REJEITADO O PARECER PELA DERRUBADA DO VETO COM 11 VOTOS CONTRÁRIOS"
        documento = {"id": 123, "numero": "280/2025", "ementa": "Ementa pelo id",
                     "tramitacoes": [{"destinatario": "Plenário", "data_resposta": "2026-03-01", "observacao": texto}]}
        resultado = montar_sessoes(modelo, [sessao(votacoes=[votacao(pares, resultado="Veto Mantido")])], {123: documento})
        voto = resultado["votacoes"][0]
        self.assertEqual(voto["sentido"], "favor_mantem")
        self.assertEqual(voto["quorum"], {"exigido": 11, "derrubar": 6, "manter": 11})
        self.assertIn("11 para manter · 6 para derrubar · 3 ausentes", voto["resumo"])
        self.assertTrue(voto["notas"])
        self.assertEqual((voto["numero"], voto["ementa"]), ("280/2025", "Ementa pelo id"))
        self.assertTrue(voto["url_documento"].endswith("IdDocumento=123"))

    def test_sem_id_fallback_e_ids_distintos_para_mesmo_documento(self):
        votos = [votacao([("Ana", "Favor")], id_documento=None, ementa="Ementa avulsa"),
                 votacao([("Ana", "Favor")]), votacao([("Ana", "Contra")], resultado="Rejeitado")]
        resultado = montar_sessoes(modelo_minimo(), [sessao(votacoes=votos)], {})
        ids = [v["id"] for v in resultado["votacoes"]]
        self.assertEqual(len(set(ids)), 3)
        avulsa = next(v for v in resultado["votacoes"] if v["id_documento"] is None)
        self.assertIsNone(avulsa["url_documento"])
        self.assertEqual(avulsa["ementa"], "Ementa avulsa")
        self.assertEqual(set(resultado["sessoes"][0]["votacoes"]), set(ids))
        self.assertEqual(resultado, montar_sessoes(modelo_minimo(), [sessao(votacoes=list(reversed(votos)))], {}))

    def test_ementa_da_pauta_e_substitutivo_por_id(self):
        substitutivo = {"id": 456, "numero": "2/2026", "ementa": "Texto do substitutivo"}
        documentos = {123: {"id": 123, "substitutivos": [substitutivo]}}
        registro = sessao(pauta=[{"id_documento": 789, "ementa": "Ementa histórica", "numero": "3/2020"}],
                          votacoes=[votacao([("Ana", "Favor")], id_documento=456),
                                    votacao([("Ana", "Favor")], id_documento=789)])
        resultado = montar_sessoes(modelo_minimo(), [registro], documentos)
        por_id = {v["id_documento"]: v for v in resultado["votacoes"]}
        self.assertEqual(por_id[456]["ementa"], "Texto do substitutivo")
        self.assertEqual(por_id[456]["numero"], "2/2026")
        self.assertEqual(por_id[789]["ementa"], "Ementa histórica")


# ---- leitura e regressão -------------------------------------------------------
class TestFontes(unittest.TestCase):
    def test_determinismo_sem_rede_mutacao_ou_indicador_de_leitura(self):
        modelo = modelo_minimo()
        registros = [sessao(2, frequencia=[frequencia("Ana"), frequencia("Ana", "Consignado")],
                            votacoes=[votacao([("Ana", "Favor"), ("Bruno", "Contra"), ("Suplente", "Favor")])]),
                     sessao(1, pauta=[{"id_documento": 123, "fase": "Leitura"}])]
        antes = copy.deepcopy((modelo, registros))
        with mock.patch("coletor.siscam.baixar", side_effect=AssertionError("rede proibida")):
            resultado = montar_sessoes(modelo, registros, {})
        invertidos = copy.deepcopy(registros[::-1])
        for registro in invertidos:
            registro["frequencia"].reverse()
            registro["votacoes"].reverse()
            for voto in registro["votacoes"]:
                voto["votos"].reverse()
        outro = montar_sessoes(modelo, invertidos, {})
        self.assertEqual(json.dumps(resultado, ensure_ascii=False), json.dumps(outro, ensure_ascii=False))
        self.assertEqual((modelo, registros), antes)
        self.assertEqual(set(resultado), {"anos", "cobertura", "legislaturas", "sessoes", "votacoes", "por_pessoa",
                                           "mediana_presenca", "placares_por_ano", "ritmo", "qualidade"})

    def test_le_arquivos_na_raiz_e_aproveita_documentos_do_modelo(self):
        modelo = modelo_minimo()
        modelo["documentos"] = [{"id": 123, "numero": "9/2026", "ementa": "Ementa do modelo"}]
        with tempfile.TemporaryDirectory() as pasta:
            raiz = Path(pasta)
            (raiz / "data" / "sessoes").mkdir(parents=True)
            (raiz / "data" / "proposicoes").mkdir()
            (raiz / "data" / "sessoes" / "2026.json").write_text(
                json.dumps([sessao(votacoes=[votacao([("Ana", "Favor")])])]), encoding="utf-8")
            (raiz / "data" / "proposicoes" / "2026.json").write_text(
                json.dumps([{"id": 123, "numero": "1/2026", "ementa": "Ementa bruta"}]), encoding="utf-8")
            resultado = montar_sessoes(modelo, raiz=raiz)
        self.assertEqual(len(resultado["sessoes"]), 1)
        self.assertEqual(resultado["votacoes"][0]["ementa"], "Ementa do modelo")
        self.assertEqual(resultado["votacoes"][0]["numero"], "9/2026")

    def test_le_demais_documentos_por_id_mesmo_com_modelo_parcial(self):
        modelo = modelo_minimo()
        modelo["documentos"] = [{"id": 999, "ementa": "Outro documento"}]
        with tempfile.TemporaryDirectory() as pasta:
            raiz = Path(pasta)
            pasta_pdl = raiz / "data" / "documentos" / "pdl"
            pasta_pdl.mkdir(parents=True)
            (pasta_pdl / "2026.json").write_text(json.dumps([
                {"id": 123, "ementa": "Ementa do PDL", "numero": "9/2026"}]), encoding="utf-8")
            resultado = montar_sessoes(modelo, [sessao(votacoes=[votacao([("Ana", "Favor")])])], raiz=raiz)
        self.assertEqual(resultado["votacoes"][0]["ementa"], "Ementa do PDL")

    def test_vazio(self):
        resultado = montar_sessoes(modelo_minimo(), [], {})
        self.assertEqual(resultado["anos"], [])
        self.assertEqual(resultado["sessoes"], [])
        self.assertEqual(resultado["legislaturas"], [])

    @unittest.skipIf(os.environ.get("RADAR_COLETA") == "1", "dados mudam durante a coleta")
    def test_dados_versionados(self):
        resultado = montar_sessoes(montar_modelo(), raiz=RAIZ)
        self.assertEqual(len(resultado["sessoes"]), 627)
        self.assertEqual(sum(v["data"].startswith("2024-") for v in resultado["votacoes"]), 67)
        veto = next(v for v in resultado["votacoes"] if v["numero"] == "280/2025" and v["materia"] == "veto")
        self.assertEqual(veto["sentido"], "favor_mantem")
        self.assertIn("11 para manter · 6 para derrubar", veto["resumo"])
        historico = [v for v in resultado["votacoes"] if v["numero"] == "96/2024" and v["materia"] == "veto"]
        self.assertTrue(historico)
        self.assertTrue(all(v["notas"] for v in historico))
        derrubada = next(v for v in resultado["votacoes"] if v["sessao"] == 22222 and v["numero"] == "144/2024")
        self.assertEqual((derrubada["sentido"], derrubada["qualidade"]), ("favor_derruba", "ok"))
        self.assertEqual((derrubada["totais"]["favor"], derrubada["totais"]["contra"]), (11, 0))
        self.assertEqual(derrubada["totais_oficiais"]["favor"], 11)
        self.assertTrue(derrubada["notas"])
        incluidos = {leg: {s for s, periodos in resultado["por_pessoa"].items()
                           if (periodos.get(leg) or {}).get("sem_pagina")}
                     for leg in ("2021-2024", "2025-2028")}
        self.assertTrue({"luis-roberto-nogueira-saad", "tania-regina-pereira-rodrigues"} <= incluidos["2021-2024"])
        self.assertIn("henrique-miranda-santos", incluidos["2025-2028"])
        restantes = {a["nome"] for a in resultado["qualidade"]["nao_membros"]}
        self.assertEqual(restantes, {"CARLOS OTÁVIO DIAS VAZ - CASOTA", "HENRIQUE DOS SANTOS VIEIRA LIMA"})


if __name__ == "__main__":
    unittest.main()
