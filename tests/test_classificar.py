"""Testes do classificador: regras, hash do cache, curadoria e caminho sem chave da IA."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from coletor import arquivos
from coletor import classificar as C


def projeto(**campos) -> dict:
    base = {"id": 1, "numero": "1/2025", "ementa": "Dispõe sobre a coleta seletiva nas escolas.", "situacao": "", "tramitacoes": []}
    return {**base, **campos}


IA_BASE = {
    "categoria": "regulacao",
    "impacto": 2,
    "resumo": "Resumo da IA.",
    "publico": "comércio",
    "tema": "economia",
    "alertas": [{"rotulo": "apelo_populista", "confianca": 0.9}, {"rotulo": "pauta_de_costumes", "confianca": 0.5}],
    "justificativa": "Justificativa da IA.",
    "hash": "0123456789abcdef",
}


# -------------------------------------------------------------------------- regras
class TestCategoriaPorRegra(unittest.TestCase):
    def test_ementas_simbolicas(self):
        ementas = [
            "Dá nome à Rua Projetada 1, no bairro de Itaipu.",
            "Denomina a praça localizada no Fonseca.",
            "Passa a denominar-se Escola Municipal Fulana a unidade...",
            "Institui o Dia Municipal do Ciclista.",
            "Inclui no Calendário Oficial da cidade a Semana do Rock.",
            "Declara de utilidade pública a Associação de Moradores X.",
            "Concede o Título de Cidadão Niteroiense ao Sr. Fulano.",
            "Declara patrimônio cultural imaterial o samba de roda.",
            "Altera o art. 6° da Lei nº 3.474, de 07 de fevereiro de 2020, para instituir data.",
        ]
        for ementa in ementas:
            with self.subTest(ementa=ementa):
                self.assertEqual(C.categoria_por_regra({"ementa": ementa}), "simbolica")

    def test_ementas_nao_simbolicas(self):
        for ementa in ("Dispõe sobre a obrigatoriedade de bebedouros nas escolas.", "", None):
            with self.subTest(ementa=ementa):
                self.assertIsNone(C.categoria_por_regra({"ementa": ementa}))
        self.assertIsNone(C.categoria_por_regra({}))


class TestAutorizativa(unittest.TestCase):
    def test_autorizativas(self):
        for ementa in (
            "Autoriza o Poder Executivo a criar o programa X.",
            "Ementa: Fica autorizado o Executivo a instituir Y.",
            "  AUTORIZA O EXECUTIVO A CONCEDER desconto.",
        ):
            with self.subTest(ementa=ementa):
                self.assertTrue(C.e_autorizativa({"ementa": ementa}))

    def test_nao_autorizativas(self):
        for ementa in ("Institui programa e autoriza o Poder Executivo a regulamentá-lo.", "", None):
            with self.subTest(ementa=ementa):
                self.assertFalse(C.e_autorizativa({"ementa": ementa}))


class TestSinaisTramitacao(unittest.TestCase):
    CCJ = "Comissão Permanente de Constituição e Justiça e Redação Final"

    def test_sem_sinais(self):
        self.assertEqual(C.sinais_tramitacao({}), [])
        self.assertEqual(C.sinais_tramitacao(projeto(tramitacoes=[{"resultado": "Favorável", "destinatario": self.CCJ}])), [])

    def test_parecer_contrario_da_ccj(self):
        p = projeto(tramitacoes=[{"destinatario": self.CCJ, "resultado": "Contrário"}])
        self.assertEqual(C.sinais_tramitacao(p), ["parecer_contrario_ccj"])
        # parecer contrário de outra comissão não conta
        p = projeto(tramitacoes=[{"destinatario": "Comissão de Saúde", "resultado": "Contrário"}])
        self.assertEqual(C.sinais_tramitacao(p), [])

    def test_rejeicao_em_plenario_nao_confunde_com_veto(self):
        p = projeto(tramitacoes=[{"resultado": "Rejeitado em Primeira Discussão"}])
        self.assertEqual(C.sinais_tramitacao(p), ["rejeitado_plenario"])
        p = projeto(tramitacoes=[{"resultado": "Veto rejeitado em plenário"}])
        self.assertEqual(C.sinais_tramitacao(p), [])

    def test_veto_total_sem_repeticao(self):
        p = projeto(tramitacoes=[{"resultado": "Veto Total"}, {"observacao": "VETO TOTAL MANTIDO"}], situacao="VETO MANTIDO")
        self.assertEqual(C.sinais_tramitacao(p), ["veto_total"])

    def test_duplica_lei_vigente(self):
        for campos in ({"complemento": "PROJETO EM DUPLICIDADE"}, {"observacao": "JÁ EXISTE LEI SOBRE O TEMA"},
                       {"resultado": "Lei nº 3.500 em vigor"}):
            with self.subTest(campos=campos):
                self.assertEqual(C.sinais_tramitacao(projeto(tramitacoes=[campos])), ["duplica_lei_vigente"])

    def test_sinais_pela_situacao(self):
        self.assertEqual(C.sinais_tramitacao(projeto(situacao="Veto Total")), ["veto_total"])
        self.assertEqual(C.sinais_tramitacao(projeto(situacao="PARECER CONTRÁRIO")), ["parecer_contrario_ccj"])
        self.assertEqual(C.sinais_tramitacao(projeto(situacao="REJEITADA")), ["rejeitado_plenario"])

    def test_sinais_pela_lei(self):
        p = projeto(lei={"tipo": "veto_derrubado", "veto_parcial": True})
        self.assertEqual(C.sinais_tramitacao(p), ["veto_derrubado", "veto_parcial"])


# ---------------------------------------------------------------------------- hash
class TestHash(unittest.TestCase):
    def test_formato_e_formula(self):
        h = C._hash("Dispõe sobre algo.")
        self.assertRegex(h, r"^[0-9a-f]{16}$")
        esperado = hashlib.sha1(f"{C.VERSAO_PROMPT}|{C.MODELO}|Dispõe sobre algo.".encode()).hexdigest()[:16]
        self.assertEqual(h, esperado)

    def test_deterministico_e_sensivel_a_ementa(self):
        self.assertEqual(C._hash("a"), C._hash("a"))
        self.assertNotEqual(C._hash("a"), C._hash("b"))

    def test_muda_com_versao_do_prompt_e_modelo(self):
        original = C._hash("ementa")
        with mock.patch.object(C, "VERSAO_PROMPT", "outra-versao"):
            self.assertNotEqual(C._hash("ementa"), original)
        with mock.patch.object(C, "MODELO", "outro-modelo"):
            self.assertNotEqual(C._hash("ementa"), original)
        self.assertEqual(C._hash("ementa"), original)


class TestNormalizarIa(unittest.TestCase):
    def test_normaliza_valores_invalidos(self):
        bruto = {
            "categoria": "inventada",
            "impacto": 7,
            "alertas": ["pauta_de_costumes", {"rotulo": "inexistente", "confianca": 1}, {"rotulo": "apelo_populista", "confianca": "0.876"}],
            "resumo": "x" * 500,
        }
        n = C.normalizar_ia(bruto)
        self.assertEqual(n["categoria"], "outra")
        self.assertEqual(n["impacto"], 3)
        self.assertEqual(n["alertas"], [{"rotulo": "pauta_de_costumes", "confianca": 0.5}, {"rotulo": "apelo_populista", "confianca": 0.88}])
        self.assertEqual(len(n["resumo"]), 180)
        self.assertEqual(n["tema"], "outro")

    def test_impacto_nao_numerico(self):
        self.assertIsNone(C.normalizar_ia({"impacto": "alto"})["impacto"])
        self.assertIsNone(C.normalizar_ia({})["impacto"])
        self.assertEqual(C.normalizar_ia({"impacto": -2})["impacto"], 0)


# ----------------------------------------------------------------------- curadoria
@mock.patch.object(C, "CONFIANCA_MINIMA", 0.75)
class TestClassificacaoFinal(unittest.TestCase):
    def test_sem_nenhuma_camada(self):
        cls = C.classificacao_final(projeto(), {}, {})
        self.assertEqual(cls, {
            "categoria": "outra", "impacto": None, "resumo": "", "publico": "", "tema": "outro", "sinais": [],
            "alertas": [], "polemico": False, "risco_juridico": False,
        })

    def test_so_ia_respeita_confianca_minima(self):
        cls = C.classificacao_final(projeto(), {"1": IA_BASE}, {})
        self.assertEqual(cls["categoria"], "regulacao")
        self.assertEqual(cls["impacto"], 2)
        self.assertEqual(cls["resumo"], "Resumo da IA.")
        self.assertEqual(cls["tema"], "economia")
        self.assertEqual(cls["alertas"], [
            {"rotulo": "apelo_populista", "origem": "ia", "confianca": 0.9, "nota": "Justificativa da IA."},
        ])
        self.assertTrue(cls["polemico"])
        self.assertFalse(cls["risco_juridico"])

    def test_curadoria_prevalece_e_soma_alertas_da_ia(self):
        cur = {"1/2025": {
            "projeto": "1/2025", "categoria": "politica_publica", "impacto": 3, "resumo": "Resumo curado.",
            "alertas": ["restricao_de_direitos", "apelo_populista"], "fontes": ["https://exemplo.org/a"], "nota": "Nota.",
        }}
        cls = C.classificacao_final(projeto(), {"1": IA_BASE}, cur)
        self.assertEqual(cls["categoria"], "politica_publica")
        self.assertEqual(cls["impacto"], 3)
        self.assertEqual(cls["resumo"], "Resumo curado.")
        self.assertEqual(cls["publico"], "comércio")  # público continua vindo da IA
        self.assertEqual([(a["rotulo"], a["origem"]) for a in cls["alertas"]],
                         [("restricao_de_direitos", "curadoria"), ("apelo_populista", "curadoria")])
        self.assertEqual(cls["alertas"][0]["fontes"], ["https://exemplo.org/a"])
        self.assertEqual(cls["alertas"][0]["nota"], "Nota.")

    def test_substitui_ia_suprime_alertas_da_ia(self):
        cur = {"1/2025": {"projeto": "1/2025", "alertas": [], "substitui_ia": True, "fontes": ["https://exemplo.org"]}}
        cls = C.classificacao_final(projeto(), {"1": IA_BASE}, cur)
        self.assertEqual(cls["alertas"], [])
        self.assertFalse(cls["polemico"])
        self.assertEqual(cls["categoria"], "regulacao")  # a categoria da IA continua valendo

    def test_impacto_zero_da_curadoria_nao_e_ignorado(self):
        cur = {"1/2025": {"projeto": "1/2025", "impacto": 0, "fontes": ["https://exemplo.org"]}}
        self.assertEqual(C.classificacao_final(projeto(), {"1": IA_BASE}, cur)["impacto"], 0)

    def test_regra_simbolica_vence_a_ia_e_zera_impacto(self):
        p = projeto(ementa="Dá nome à Rua Projetada 1.")
        cls = C.classificacao_final(p, {"1": IA_BASE}, {})
        self.assertEqual(cls["categoria"], "simbolica")
        self.assertEqual(cls["impacto"], 0)
        self.assertEqual(C.classificacao_final(p, {}, {})["tema"], "homenagem")

    def test_categoria_da_curadoria_vence_a_regra(self):
        p = projeto(ementa="Dá nome à Rua Projetada 1.")
        cur = {"1/2025": {"projeto": "1/2025", "categoria": "politica_publica", "fontes": ["https://exemplo.org"]}}
        self.assertEqual(C.classificacao_final(p, {}, cur)["categoria"], "politica_publica")

    def test_autorizativa_limita_impacto(self):
        p = projeto(ementa="Autoriza o Poder Executivo a criar o programa X.")
        cls = C.classificacao_final(p, {"1": {**IA_BASE, "impacto": 3}}, {})
        self.assertEqual(cls["impacto"], 1)
        self.assertIn("autorizativa", cls["sinais"])
        self.assertIsNone(C.classificacao_final(p, {}, {})["impacto"])

    def test_risco_juridico(self):
        ia = {**IA_BASE, "alertas": [{"rotulo": "inconstitucionalidade_provavel", "confianca": 0.8}]}
        cls = C.classificacao_final(projeto(), {"1": ia}, {})
        self.assertTrue(cls["risco_juridico"])
        self.assertFalse(cls["polemico"])
        cur = {"1/2025": {"projeto": "1/2025", "sinais": ["inconstitucionalidade_declarada"], "fontes": ["https://exemplo.org"]}}
        cls = C.classificacao_final(projeto(), {}, cur)
        self.assertTrue(cls["risco_juridico"])
        self.assertIn("inconstitucionalidade_declarada", cls["sinais"])

    def test_cache_de_outro_projeto_nao_vaza(self):
        cls = C.classificacao_final(projeto(id=2, numero="2/2025"), {"1": IA_BASE}, {})
        self.assertEqual(cls["categoria"], "outra")
        self.assertEqual(cls["alertas"], [])


class TestCarregarCuradoria(unittest.TestCase):
    def test_indexa_por_numero_do_projeto(self):
        with tempfile.TemporaryDirectory() as tmp:
            arq = Path(tmp) / "curadoria.json"
            arq.write_text(json.dumps({"_leia_me": "x", "entradas": [
                {"projeto": "1/2025", "alertas": [], "fontes": ["https://exemplo.org"]},
                {"projeto": "7/2024", "alertas": ["pauta_de_costumes"], "fontes": ["https://exemplo.org"]},
            ]}), encoding="utf-8")
            with mock.patch.object(C, "CURADORIA", arq):
                cur = C.carregar_curadoria()
        self.assertEqual(sorted(cur), ["1/2025", "7/2024"])
        self.assertEqual(cur["7/2024"]["alertas"], ["pauta_de_costumes"])

    def test_sem_arquivo(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(C, "CURADORIA", Path(tmp) / "nao_existe.json"):
            self.assertEqual(C.carregar_curadoria(), {})


# ------------------------------------------------------------- execução sem chave
class TestSemChaveDaIa(unittest.TestCase):
    """Sem OPENCODE_API_KEY o classificador não pode fazer chamadas de rede nem gravar o cache."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.dir_dados = base / "proposicoes"
        self.dir_dados.mkdir()
        (self.dir_dados / "2025.json").write_text(json.dumps([
            projeto(id=1, numero="1/2025"), projeto(id=2, numero="2/2025", ementa="Dá nome à Rua A."),
        ]), encoding="utf-8")
        self.cache = base / "classificacao_ia.json"
        for alvo in (
            mock.patch.object(C, "DIR_DADOS", self.dir_dados),
            mock.patch.object(C, "CACHE_IA", self.cache),
            mock.patch("urllib.request.urlopen", side_effect=AssertionError("chamada de rede inesperada")),
            mock.patch.object(C, "chamar_ia", side_effect=AssertionError("chamada à IA inesperada")),
        ):
            self.mock = alvo.start()
            self.addCleanup(alvo.stop)

    def rodar(self, usar_ia: bool, ambiente: dict) -> tuple[dict, str]:
        saida = io.StringIO()
        with mock.patch.dict(os.environ, ambiente, clear=False), contextlib.redirect_stderr(saida), \
                contextlib.redirect_stdout(io.StringIO()):
            if "OPENCODE_API_KEY" not in ambiente:
                os.environ.pop("OPENCODE_API_KEY", None)
            estat = C.classificar(usar_ia, None)
        return estat, saida.getvalue()

    def test_sem_chave(self):
        estat, erro = self.rodar(True, {})
        self.assertEqual(estat, {"total": 2, "ia_novos": 0, "ia_cache": 0, "ia_desligada": True})
        self.assertIn("OPENCODE_API_KEY", erro)
        self.assertFalse(self.cache.exists())

    def test_chave_em_branco_equivale_a_sem_chave(self):
        estat, _ = self.rodar(True, {"OPENCODE_API_KEY": "   "})
        self.assertTrue(estat["ia_desligada"])
        self.assertFalse(self.cache.exists())

    def test_sem_ia_mesmo_com_chave(self):
        estat, erro = self.rodar(False, {"OPENCODE_API_KEY": "chave-falsa"})
        self.assertTrue(estat["ia_desligada"])
        self.assertEqual(estat["ia_novos"], 0)
        self.assertEqual(erro, "")
        self.assertFalse(self.cache.exists())


# ------------------------------------------------------- execução com IA simulada
class TestComIaSimulada(unittest.TestCase):
    """Com chave, as respostas da IA (chamar_ia simulada, sem rede) vão para o cache por salvar_mapa."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.dir_dados = base / "proposicoes"
        self.dir_dados.mkdir()
        self.cache = base / "classificacao_ia.json"
        self.lotes: list[list[int]] = []
        self.recusar_no_lote: int | None = None
        for alvo in (
            mock.patch.object(C, "DIR_DADOS", self.dir_dados),
            mock.patch.object(C, "CACHE_IA", self.cache),
            mock.patch.object(C, "LOTE", 15),  # independente de CLASSIFICADOR_LOTE no ambiente
            mock.patch("urllib.request.urlopen", side_effect=AssertionError("chamada de rede inesperada")),
            mock.patch.object(C, "chamar_ia", side_effect=self.ia_falsa),
        ):
            alvo.start()
            self.addCleanup(alvo.stop)

    def ia_falsa(self, itens: list[dict], chave: str, sessao: str) -> dict[int, dict]:
        self.assertEqual(chave, "chave-falsa")
        self.lotes.append([p["id"] for p in itens])
        if self.recusar_no_lote == len(self.lotes):
            raise PermissionError("OpenCode Go recusou a chave (401)")
        return {
            p["id"]: {"id": p["id"], "categoria": "regulacao", "impacto": 2, "resumo": f"Resumo {p['id']}.",
                      "publico": "comércio", "tema": "economia", "alertas": [], "justificativa": "sem alertas"}
            for p in itens
        }

    def gravar_projetos(self, n: int) -> list[dict]:
        projetos = [projeto(id=i, numero=f"{i}/2025", ementa=f"Dispõe sobre o tema {i}.") for i in range(1, n + 1)]
        projetos.append(projeto(id=n + 1, numero=f"{n + 1}/2025", ementa=""))  # sem ementa: não vai para a IA
        (self.dir_dados / "2025.json").write_text(json.dumps(projetos), encoding="utf-8")
        return projetos

    def rodar(self, limite: int | None = None) -> tuple[dict, str]:
        erro = io.StringIO()
        with mock.patch.dict(os.environ, {"OPENCODE_API_KEY": "chave-falsa"}), contextlib.redirect_stderr(erro), \
                contextlib.redirect_stdout(io.StringIO()):
            estat = C.classificar(True, limite)
        return estat, erro.getvalue()

    def test_grava_o_cache_um_projeto_por_linha(self):
        projetos = self.gravar_projetos(2)
        estat, _ = self.rodar()
        self.assertEqual(estat, {"total": 3, "ia_novos": 2, "ia_cache": 1, "ia_desligada": False})
        self.assertEqual(self.lotes, [[1, 2]])
        texto = self.cache.read_text(encoding="utf-8")
        cache = json.loads(texto)
        self.assertEqual(texto, arquivos.texto_mapa(cache))  # formato compacto de coletor.arquivos
        self.assertEqual(sorted(cache), ["1", "2"])
        self.assertEqual(cache["1"]["hash"], C._hash(projetos[0]["ementa"]))
        self.assertEqual((cache["1"]["modelo"], cache["1"]["versao_prompt"]), (C.MODELO, C.VERSAO_PROMPT))
        self.assertEqual((cache["2"]["categoria"], cache["2"]["impacto"], cache["2"]["resumo"]),
                         ("regulacao", 2, "Resumo 2."))

    def test_cache_valido_nao_e_reenviado(self):
        self.gravar_projetos(2)
        self.rodar()
        self.lotes.clear()
        antes = self.cache.read_bytes()
        estat, _ = self.rodar()
        self.assertEqual(self.lotes, [])
        self.assertEqual((estat["ia_novos"], estat["ia_cache"]), (0, 3))
        self.assertEqual(self.cache.read_bytes(), antes)

    def test_gravacao_parcial_a_cada_dez_lotes(self):
        self.gravar_projetos(11)
        tamanhos: list[int] = []

        def salvar(caminho, mapa):
            tamanhos.append(len(mapa))
            return arquivos.salvar_mapa(caminho, mapa)

        with mock.patch.object(C, "LOTE", 1), mock.patch.object(C, "salvar_mapa", side_effect=salvar):
            estat, _ = self.rodar()
        self.assertEqual(estat["ia_novos"], 11)
        self.assertEqual(tamanhos, [10, 11])  # depois do 10º lote e no fim
        self.assertEqual(len(json.loads(self.cache.read_text(encoding="utf-8"))), 11)

    def test_chave_recusada_no_meio_preserva_o_que_ja_foi_pago(self):
        self.gravar_projetos(3)
        self.recusar_no_lote = 2
        with mock.patch.object(C, "LOTE", 1):
            estat, erro = self.rodar()
        self.assertEqual(self.lotes, [[1], [2]])
        self.assertEqual(estat["ia_novos"], 1)
        self.assertIn("recusou a chave", estat["ia_erro"])
        self.assertIn("::warning::", erro)
        self.assertEqual(sorted(json.loads(self.cache.read_text(encoding="utf-8"))), ["1"])

    def test_limite(self):
        self.gravar_projetos(3)
        estat, _ = self.rodar(limite=2)
        self.assertEqual(self.lotes, [[1, 2]])
        self.assertEqual(estat["ia_novos"], 2)
        self.assertEqual(sorted(json.loads(self.cache.read_text(encoding="utf-8"))), ["1", "2"])


if __name__ == "__main__":
    unittest.main()
