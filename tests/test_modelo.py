"""Testes do modelo do site: desfechos, normalização, repetidos e montagem com dados sintéticos."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from coletor import siscam
from coletor.site import modelo as M


# ------------------------------------------------------------------------ desfechos
class TestDesfechos(unittest.TestCase):
    def test_grupos(self):
        self.assertEqual(M.DESFECHO_GRUPO["virou_lei"], "lei")
        for d in ("aprovado_aguardando_sancao", "em_tramitacao", "apensado"):
            self.assertEqual(M.DESFECHO_GRUPO[d], "andamento", d)
        for d in ("arquivado", "vetado", "rejeitado", "parecer_contrario", "retirado"):
            self.assertEqual(M.DESFECHO_GRUPO[d], "sem_exito", d)
        self.assertEqual(set(M.DESFECHO_GRUPO.values()), {"lei", "andamento", "sem_exito"})

    def test_todo_desfecho_tem_nome(self):
        self.assertEqual(set(M.DESFECHO_GRUPO), set(M.NOME_DESFECHO))

    def test_coletor_so_produz_desfechos_conhecidos(self):
        situacoes = sorted(siscam.SITUACOES_LEI) + [
            "VETO MANTIDO", "VETO TOTAL", "REJEITADO", "REJEITADA", "AGUARDANDO SANÇÃO", "APROVADO", "VOTADO",
            "RETIRADO", "RETIRADA", "CANCELADO", "PARECER CONTRÁRIO", "ARQUIVADO", "APENSADO", "SMDCP", "",
        ]
        produzidos = {siscam.derivar_desfecho({"situacao": s, "tramitacoes": []}) for s in situacoes}
        self.assertEqual(produzidos, set(M.DESFECHO_GRUPO))


# --------------------------------------------------------------------- normalização
class TestNormalizacao(unittest.TestCase):
    def test_slug(self):
        self.assertEqual(M.slug("JOSÉ ADRIANO VALLE DA COSTA - FOLHA"), "jose-adriano-valle-da-costa-folha")
        self.assertEqual(M.slug("  Ação & Cia.  "), "acao-cia")
        self.assertEqual(M.slug("Sylvio Maurício De Freitas"), M.slug("SYLVIO MAURÍCIO DE FREITAS"))
        self.assertEqual(M.slug(""), "")

    def test_tokens(self):
        t = M._tokens("Dispõe sobre a criação do Programa Municipal de Hortas Comunitárias no Município de Niterói")
        self.assertEqual(t, frozenset({"CRIACAO", "PROGRAMA", "HORTAS", "COMUNITARIAS"}))
        self.assertEqual(M._tokens("Ação"), frozenset({"ACAO"}))
        self.assertEqual(M._tokens(""), frozenset())

    def test_nome_curto(self):
        self.assertEqual(M.nome_curto("RODRIGO FLACH FARAH"), "Rodrigo Farah")
        self.assertEqual(M.nome_curto("JOSÉ ADRIANO VALLE DA COSTA - FOLHA"), "Folha")
        self.assertEqual(M.nome_curto("MICHEL SALIM SAAD NETO"), "Michel Saad")
        self.assertEqual(M.nome_curto("LUIZ CARLOS GALLO DE FREITAS"), "Luiz de Freitas")
        self.assertEqual(M.nome_curto("BENNY BRIOLLY"), "Benny Briolly")

    def test_legislatura_de(self):
        legs = [{"id": "2021-2024", "inicio": "2021-01-01", "fim": "2024-12-31"},
                {"id": "2025-2028", "inicio": "2025-01-01", "fim": "2028-12-31"}]
        self.assertEqual(M.legislatura_de("2024-12-31", 2024, legs), "2021-2024")
        self.assertEqual(M.legislatura_de("2025-01-01", 2024, legs), "2025-2028")
        self.assertEqual(M.legislatura_de(None, 2026, legs), "2025-2028")
        self.assertIsNone(M.legislatura_de("2019-05-05", 2019, legs))

    def test_dias_entre(self):
        self.assertEqual(M.dias_entre("2025-02-10", "2025-04-08"), 57)
        self.assertEqual(M.dias_entre("2025-01-01", "2025-01-01"), 0)
        self.assertIsNone(M.dias_entre("2025-04-08", "2025-02-10"))
        self.assertIsNone(M.dias_entre(None, "2025-02-10"))
        self.assertIsNone(M.dias_entre("2025-02-30", "2025-03-01"))

    def test_autor_vereador_ou_executivo(self):
        nao_vereador = ["MESA DIRETORA", "PODER EXECUTIVO"]
        self.assertTrue(M.e_vereador({"nome": "Fulana", "origem": "Vereadora"}, nao_vereador))
        self.assertTrue(M.e_vereador({"nome": "Fulana", "origem": ""}, nao_vereador))
        self.assertFalse(M.e_vereador({"nome": "Mesa Diretora", "origem": "Vereador"}, nao_vereador))
        self.assertFalse(M.e_vereador({"nome": "Fulana", "origem": "Executivo"}, nao_vereador))
        self.assertTrue(M.e_executivo({"nome": "PODER EXECUTIVO", "origem": "Executivo"}))
        self.assertTrue(M.e_executivo({"nome": "AXEL GRAEL", "origem": ""}))
        self.assertFalse(M.e_executivo({"nome": "Fulana", "origem": "Vereador"}))

    def test_efeito_das_leis(self):
        lei = {"desfecho": "virou_lei", "impacto": None, "categoria": "politica_publica", "sinais": []}
        self.assertTrue(M.com_efeito(lei))
        self.assertTrue(M.com_efeito({**lei, "impacto": 2}))
        self.assertFalse(M.com_efeito({**lei, "impacto": 1}))
        self.assertFalse(M.com_efeito({**lei, "sinais": ["autorizativa"]}))
        self.assertFalse(M.com_efeito({**lei, "desfecho": "arquivado", "impacto": 3}))
        self.assertTrue(M.sem_efeito({**lei, "categoria": "simbolica"}))
        self.assertTrue(M.sem_efeito({**lei, "impacto": 0}))
        self.assertFalse(M.sem_efeito(lei))


# ------------------------------------------------------------------------ repetidos
EMENTA = "Dispõe sobre a instalação de bebedouros públicos para animais domésticos nas praças e parques municipais"


def candidato(id_: int, data: str | None, ementa: str = EMENTA, principal: str | None = "ana", categoria: str = "regulacao") -> dict:
    return {
        "id": id_, "numero": f"{id_}/2025", "ano": 2025, "data": data, "ementa": ementa, "url": f"https://exemplo.invalid/{id_}",
        "principal": principal, "categoria": categoria, "sinais": [], "repete": None,
    }


class TestMarcarRepetidos(unittest.TestCase):
    def test_marca_o_posterior_e_nao_o_original(self):
        original, copia = candidato(1, "2021-03-01"), candidato(2, "2023-05-10")
        M.marcar_repetidos([copia, original])  # a ordem da lista não importa, vale a data
        self.assertNotIn("repete_projeto", original["sinais"])
        self.assertIsNone(original["repete"])
        self.assertEqual(copia["sinais"], ["repete_projeto"])
        self.assertEqual(copia["repete"], {"numero": "1/2025", "url": "https://exemplo.invalid/1", "mesmo_autor": True})

    def test_autor_diferente(self):
        original, copia = candidato(1, "2021-03-01"), candidato(2, "2023-05-10", principal="bruno")
        M.marcar_repetidos([original, copia])
        self.assertFalse(copia["repete"]["mesmo_autor"])

    def test_data_ausente_usa_fim_do_ano(self):
        original, copia = candidato(1, None), candidato(2, "2025-06-01")
        original["ano"] = 2024
        M.marcar_repetidos([copia, original])
        self.assertEqual(copia["repete"]["numero"], "1/2025")
        self.assertIsNone(original["repete"])

    def test_ignora_simbolicos_sem_autor_vereador_e_ementas_curtas(self):
        original = candidato(1, "2021-03-01")
        simbolico = candidato(2, "2022-01-01", categoria="simbolica")
        sem_principal = candidato(3, "2022-01-02", principal=None)
        curta_1, curta_2 = candidato(4, "2022-01-03", ementa="Cria bebedouros públicos"), candidato(5, "2022-01-04", ementa="Cria bebedouros públicos")
        diferente = candidato(6, "2022-01-05", ementa="Institui o programa de castração gratuita de cães e gatos em todos os bairros")
        projetos = [original, simbolico, sem_principal, curta_1, curta_2, diferente]
        M.marcar_repetidos(projetos)
        for p in projetos:
            with self.subTest(id=p["id"]):
                self.assertIsNone(p["repete"])
                self.assertEqual(p["sinais"], [])

    def test_limiar(self):
        quase = EMENTA + " arborizados"  # um termo a mais: Jaccard 8/9
        original, copia = candidato(1, "2021-03-01"), candidato(2, "2023-05-10", ementa=quase)
        M.marcar_repetidos([original, copia])
        self.assertIsNotNone(copia["repete"])
        original, copia = candidato(1, "2021-03-01"), candidato(2, "2023-05-10", ementa=quase)
        M.marcar_repetidos([original, copia], limiar=0.95)
        self.assertIsNone(copia["repete"])


# ------------------------------------------------------------- correções de lei
class TestCorrecaoLei(unittest.TestCase):
    def test_nulos_nao_apagam_campos_e_false_e_correcao_valida(self):
        p = {"desfecho": "virou_lei", "lei": {
            "numero": 3959, "data": "2024-10-10", "tipo": "sancionada", "veto_parcial": True,
        }}
        correcao = {"lei": {"numero": 3958, "data": None, "tipo": "veto_derrubado", "veto_parcial": False}}
        corrigido = M.corrigir_proposicao(p, correcao)
        self.assertEqual(corrigido["lei"], {
            "numero": 3958, "data": "2024-10-10", "tipo": "veto_derrubado", "veto_parcial": False,
        })
        self.assertEqual(p["lei"]["numero"], 3959)  # não muda os dados coletados nem a curadoria
        self.assertTrue(p["lei"]["veto_parcial"])
        self.assertIsNone(correcao["lei"]["data"])
        self.assertEqual(M.corrigir_proposicao(p, {"lei": {"data": "2024-11-01"}})["lei"]["data"], "2024-11-01")

    def test_data_vem_do_passo_datado_de_sancao_ou_publicacao(self):
        casos = [
            ({"resultado": "Sancionado", "data_resposta": "2024-10-10", "enviado": "2024-10-09"}, "2024-10-10"),
            ({"resultado": "Promulgado pela Câmara", "enviado": "2024-10-09"}, "2024-10-09"),
            ({"observacao": "LEI Nº 3958 PUBLICADA NO JORNAL", "enviado": "2024-10-11"}, "2024-10-11"),
        ]
        for passo, data in casos:
            with self.subTest(passo=passo):
                p = {"desfecho": "apensado", "lei": None, "tramitacoes": [
                    {"resultado": "Sancionado"},  # não deixar um passo sem data esconder outro que a tenha
                    {"resultado": "Aprovado", "enviado": "2024-10-01"}, passo,
                ]}
                corrigido = M.corrigir_proposicao(p, {"desfecho": "virou_lei", "lei": {
                    "numero": 3958, "data": None, "tipo": "veto_derrubado",
                }})
                self.assertEqual(corrigido["lei"]["data"], data)
                self.assertEqual(corrigido["lei"]["tipo"], "veto_derrubado")
                self.assertEqual(corrigido["lei"]["numero"], 3958)

    def test_lei_sem_correcao_tambem_pode_recuperar_data(self):
        p = {"desfecho": "virou_lei", "lei": {"numero": 4000, "data": None}, "tramitacoes": [
            {"resultado": "Sancionado", "enviado": "2025-03-03"},
        ]}
        self.assertEqual(M.corrigir_proposicao(p, None)["lei"]["data"], "2025-03-03")

    def test_nao_inventa_data_a_partir_de_votacao_ou_outra_lei(self):
        p = {"desfecho": "virou_lei", "lei": {"numero": 3958, "data": None}, "tramitacoes": [
            {"resultado": "Aprovado", "enviado": "2024-10-01"},
            {"observacao": "DUPLICIDADE COM LEI Nº 3474 PUBLICADA EM 2020", "enviado": "2024-10-02"},
        ]}
        self.assertIsNone(M.corrigir_proposicao(p, None)["lei"].get("data"))


# ------------------------------------------------------------- modelo sintético
CFG = {
    "legislaturas": [{
        "id": "2025-2028", "inicio": "2025-01-01", "fim": "2028-12-31", "fonte": "https://exemplo.invalid/eleitos",
        "eleitos": [
            {"nome": "Ana Teste", "siscam": "ANA MARIA TESTE", "partido": "PX"},
            {"nome": "Bruno Zero", "siscam": "BRUNO SEM PROJETO", "partido": "PY"},
        ],
    }],
    "afastamentos": [{"siscam": "ANA MARIA TESTE", "legislatura": "2025-2028", "cargo": "Secretária", "fonte": "https://exemplo.invalid/a"}],
    "nao_vereador": ["MESA DIRETORA", "PODER EXECUTIVO"],
    "apelidos": {"_leia_me": "ignorado", "CARLOS SUPLENTE DA SILVA": "Carlinhos"},
}
ANA = {"id": 1, "nome": "ANA MARIA TESTE", "origem": "Vereador", "papel": "Autor"}
CARLOS = {"id": 3, "nome": "CARLOS SUPLENTE DA SILVA", "origem": "Vereador", "papel": "Co-Autor"}
EXECUTIVO = {"id": 99, "nome": "PODER EXECUTIVO", "origem": "Executivo", "papel": "Autor"}


def proposicao(id_: int, ementa: str, autoria: list[dict], desfecho: str = "em_tramitacao", lei: dict | None = None,
               data: str = "2025-02-01", ano: int = 2025) -> dict:
    return {
        "id": id_, "numero": f"{id_}/{ano}", "ano": ano, "data": data, "data_protocolo": data, "ementa": ementa,
        "situacao": "", "desfecho": desfecho, "lei": lei, "autoria": autoria, "tramitacoes": [],
        "url": f"https://exemplo.invalid/{id_}",
    }


PROPOSICOES = [
    proposicao(1, "Cria o programa municipal de hortas comunitárias nas escolas", [ANA, CARLOS], "virou_lei",
               {"numero": 4000, "data": "2025-03-03", "tipo": "sancionada", "veto_parcial": False}),
    proposicao(2, "Dá nome à Rua Projetada 1, no bairro de Itaipu", [ANA], "arquivado"),
    proposicao(3, "Dispõe sobre o orçamento do Fundo Municipal de Saúde", [EXECUTIVO], "em_tramitacao"),
    proposicao(4, "Dispõe sobre o uso de banheiros em estabelecimentos", [ANA], "em_tramitacao"),
    proposicao(5, "Dispõe sobre feiras livres", [ANA], "arquivado", data="2019-05-05", ano=2019),
]
CURADORIA = {"4/2025": {
    "projeto": "4/2025", "alertas": ["pauta_de_costumes"], "nota": "Nota.", "fontes": ["https://exemplo.invalid/c"],
    "corrige": {"desfecho": "virou_lei", "lei": {"numero": 4001, "data": None, "tipo": "veto_derrubado", "veto_parcial": False}},
}}
CACHE_IA = {"1": {
    "categoria": "politica_publica", "impacto": 3, "resumo": "Cria hortas.", "publico": "estudantes", "tema": "educacao",
    "alertas": [], "justificativa": "sem alertas", "hash": "0123456789abcdef",
}}


class TestMontarModelo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            (raiz / "config").mkdir()
            (raiz / "data").mkdir()
            (raiz / "config" / "vereadores.json").write_text(json.dumps(CFG), encoding="utf-8")
            (raiz / "data" / "classificacao_ia.json").write_text(json.dumps(CACHE_IA), encoding="utf-8")
            (raiz / "data" / "meta.json").write_text(json.dumps({"coleta": {"em": "2026-10-19T09:17:00+00:00"}}), encoding="utf-8")
            with mock.patch.object(M, "RAIZ", raiz), \
                    mock.patch.object(M, "carregar_proposicoes", lambda: [dict(p) for p in PROPOSICOES]), \
                    mock.patch.object(M, "carregar_curadoria", lambda: CURADORIA), \
                    mock.patch("coletor.classificar.CONFIANCA_MINIMA", 0.75):
                cls.modelo = M.montar_modelo()
        cls.projetos = {p["id"]: p for p in cls.modelo["projetos"]}
        cls.pessoas = cls.modelo["pessoas"]

    def test_estrutura(self):
        self.assertEqual(set(self.modelo), {"legislaturas", "pessoas", "projetos", "meta", "curadoria", "cfg", "documentos", "atividade"})
        self.assertEqual(len(self.modelo["projetos"]), 5)
        self.assertEqual(self.modelo["documentos"], [])  # sem data/documentos, nenhum documento
        self.assertEqual(self.modelo["atividade"], {})
        self.assertEqual(self.modelo["meta"], {"coleta": {"em": "2026-10-19T09:17:00+00:00"}})
        self.assertIs(self.modelo["curadoria"], CURADORIA)

    def test_projeto_de_vereadora_que_virou_lei(self):
        p = self.projetos[1]
        self.assertEqual(p["origem"], "vereador")
        self.assertEqual(p["principal"], "ana-maria-teste")
        self.assertEqual(p["legislatura"], "2025-2028")
        self.assertEqual(p["partido"], "PX")
        self.assertEqual(p["dias_ate_lei"], 30)
        self.assertEqual((p["categoria"], p["impacto"], p["tema"]), ("politica_publica", 3, "educacao"))
        self.assertEqual([a["exibicao"] for a in p["autores"]], ["Ana Teste", "Carlinhos"])
        self.assertEqual([a["vereador"] for a in p["autores"]], [True, True])

    def test_simbolico_por_regra(self):
        p = self.projetos[2]
        self.assertEqual((p["categoria"], p["impacto"], p["tema"]), ("simbolica", 0, "homenagem"))

    def test_projeto_do_executivo(self):
        p = self.projetos[3]
        self.assertEqual(p["origem"], "executivo")
        self.assertIsNone(p["principal"])
        self.assertEqual(p["partido"], "")
        self.assertEqual(p["autores"][0]["vereador"], False)

    def test_correcao_e_alerta_da_curadoria(self):
        p = self.projetos[4]
        self.assertEqual(p["desfecho"], "virou_lei")
        self.assertEqual(p["lei"]["numero"], 4001)
        self.assertIsNone(p["dias_ate_lei"])
        self.assertTrue(p["polemico"])
        self.assertIn("veto_derrubado", p["sinais"])
        self.assertEqual([(a["rotulo"], a["origem"]) for a in p["alertas"]], [("pauta_de_costumes", "curadoria")])

    def test_montagem_preserva_data_coletada_ao_aplicar_curadoria(self):
        p = {**PROPOSICOES[3], "lei": {"numero": 4000, "data": "2025-03-03", "tipo": "sancionada"}}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(M, "RAIZ", Path(tmp)), \
                mock.patch.object(M, "carregar_config", return_value=CFG), \
                mock.patch.object(M, "carregar_proposicoes", return_value=[p]), \
                mock.patch.object(M, "carregar_curadoria", return_value=CURADORIA), \
                mock.patch.object(M, "carregar_documentos", return_value=[]):
            projeto = M.montar_modelo()["projetos"][0]
        self.assertEqual(projeto["lei"]["data"], "2025-03-03")
        self.assertEqual(projeto["lei"]["tipo"], "veto_derrubado")
        self.assertEqual(projeto["dias_ate_lei"], 30)

    def test_projeto_fora_das_legislaturas(self):
        self.assertIsNone(self.projetos[5]["legislatura"])

    def test_pessoa_eleita_com_metricas(self):
        ana = self.pessoas["ana-maria-teste"]
        self.assertEqual(ana["nome"], "Ana Teste")
        self.assertEqual(set(ana["mandatos"]), {"2025-2028"})  # o projeto de 2019 fica de fora
        m = ana["mandatos"]["2025-2028"]
        self.assertTrue(m["eleito"])
        self.assertEqual(m["partido"], "PX")
        self.assertEqual(len(m["afastamentos"]), 1)
        self.assertEqual([p["id"] for p in m["projetos_autor"]], [1, 2, 4])
        esperado = {
            "apresentados": 3, "coautorias": 0, "leis": 2, "leis_efeito": 2, "leis_alto": 1, "leis_sem_efeito": 0,
            "leis_outras": 0, "andamento": 0, "sem_exito": 1, "simbolicos": 1, "autorizativos": 0, "repetidos": 0,
            "polemicos": 1, "risco_juridico": 0, "leis_coautoria": 0, "taxa_aprovacao": 67, "dias_mediana": 30,
            "pct_sem_efeito": 0,
        }
        self.assertEqual(m["metricas"], esperado)

    def test_suplente_coautor_usa_apelido(self):
        carlos = self.pessoas["carlos-suplente-da-silva"]
        self.assertEqual(carlos["nome"], "Carlinhos")
        m = carlos["mandatos"]["2025-2028"]
        self.assertFalse(m["eleito"])
        self.assertEqual(m["partido"], "")
        self.assertEqual(m["metricas"]["apresentados"], 0)
        self.assertEqual(m["metricas"]["coautorias"], 1)
        self.assertEqual(m["metricas"]["leis_coautoria"], 1)

    def test_eleito_sem_projetos_aparece_zerado(self):
        bruno = self.pessoas["bruno-sem-projeto"]
        self.assertEqual(bruno["nome"], "Bruno Zero")
        m = bruno["mandatos"]["2025-2028"]
        self.assertTrue(m["eleito"])
        self.assertEqual(m["metricas"]["apresentados"], 0)
        self.assertIsNone(m["metricas"]["taxa_aprovacao"])

    def test_autores_que_nao_sao_vereadores_ficam_fora(self):
        self.assertNotIn("poder-executivo", self.pessoas)
        self.assertEqual(set(self.pessoas), {"ana-maria-teste", "carlos-suplente-da-silva", "bruno-sem-projeto"})

    def test_mediana_da_legislatura(self):
        # só eleitos contam: Ana (3) e Bruno (0)
        self.assertEqual(M.mediana_legislatura(self.modelo, "2025-2028", "apresentados"), 1.5)
        self.assertIsNone(M.mediana_legislatura(self.modelo, "2021-2024", "apresentados"))


if __name__ == "__main__":
    unittest.main()
