"""Testes da classificação por regras das demais proposituras (coletor/regras_documentos.py).

Uso: python -m unittest tests.test_regras_documentos  (ou pytest tests/test_regras_documentos.py)
"""
from __future__ import annotations

import unittest

from coletor import documentos
from coletor.regras_documentos import (
    BAIRROS_NITEROI,
    BAIRROS_POR_REGIAO,
    CATEGORIAS,
    EIXOS_PERFIL,
    ESTADOS_PEDIDO,
    ORGAO_CONCESSIONARIA,
    ORGAO_ESTADUAL,
    ORGAO_EXECUTIVO,
    ORGAO_NAO_IDENTIFICADO,
    ORGAO_OUTRA_SECRETARIA,
    SUBCATEGORIAS,
    classificar_documento,
    consta_respondido,
    derivar_publicacao,
    derivar_resposta,
    eixos_perfil,
    estado_pedido,
    extrair_bairro,
    extrair_orgao,
    normalizar,
)
from tests.apoio import ler_fixture

# Referência independente do código: os 52 bairros oficiais de Niterói, por região de
# planejamento (Prefeitura de Niterói). Só este teste a repete; o código tem uma única
# lista, regras_documentos.BAIRROS_POR_REGIAO.
BAIRROS_OFICIAIS = {
    "Praias da Baía": (
        "Boa Viagem", "Cachoeira", "Centro", "Charitas", "Fátima", "Gragoatá", "Icaraí", "Ingá", "Jurujuba",
        "Morro do Estado", "Pé Pequeno", "Ponta d'Areia", "Santa Rosa", "São Domingos", "São Francisco",
        "Viradouro", "Vital Brazil",
    ),
    "Norte": (
        "Baldeador", "Barreto", "Caramujo", "Cubango", "Engenhoca", "Fonseca", "Ilha da Conceição",
        "Santa Bárbara", "Santana", "São Lourenço", "Tenente Jardim", "Viçoso Jardim",
    ),
    "Pendotiba": (
        "Badu", "Cantagalo", "Ititioca", "Largo da Batalha", "Maceió", "Maria Paula", "Matapaca", "Sapê",
        "Vila Progresso",
    ),
    "Oceânica": (
        "Cafubá", "Camboinhas", "Engenho do Mato", "Itacoatiara", "Itaipu", "Jacaré", "Jardim Imbuí",
        "Maravista", "Piratininga", "Santo Antônio", "Serra Grande",
    ),
    "Leste": ("Muriqui", "Rio do Ouro", "Várzea das Moças"),
}


def doc(tipo: str, ementa: str, situacao: str = "", autores: list[dict] | None = None, assunto: str = "") -> dict:
    return {"tipo": tipo, "ementa": ementa, "situacao": situacao, "autores": autores or [], "assunto": assunto}


def sub(tipo: str, ementa: str, assunto: str = "") -> str:
    return classificar_documento(doc(tipo, ementa, assunto=assunto))["subcategoria"]


def passo(objetivo: str = "", resultado: str = "", enviado: str | None = None, data_resposta: str | None = None,
          observacao: str = "", complemento: str = "") -> dict:
    """Passo de tramitação com os campos produzidos por siscam.parse_detalhe."""
    return {"seq": None, "remetente": "", "destinatario": "", "objetivo": objetivo, "enviado": enviado,
            "complemento": complemento, "resultado": resultado, "data_resposta": data_resposta,
            "observacao": observacao}


def listagem(tipo: str) -> list[dict]:
    """Registros da listagem real salva em tests/fixtures/siscam/, lida como siscam.baixar a decodifica."""
    return documentos.parse_listagem(ler_fixture("siscam", f"listagem_tipo{documentos.TIPOS[tipo]}_2025.html"), tipo)


# -------------------------------------------------------------------- normalização
class TestNormalizar(unittest.TestCase):
    def test_sem_acento_pontuacao_e_espacos_repetidos(self) -> None:
        self.assertEqual(normalizar("Jardim Imbuí – Niterói."), "JARDIM IMBUI NITEROI")
        self.assertEqual(normalizar("Ponta D’Areia"), "PONTA D AREIA")
        self.assertEqual(normalizar("tapa-buraco  (n°20)"), "TAPA BURACO N 20")
        self.assertEqual(normalizar("Nº 2.181/1992"), "NO 2 181 1992")
        self.assertEqual(normalizar(None), "")


# ------------------------------------------------------------------------- bairros
class TestBairros(unittest.TestCase):
    def test_lista_oficial_com_52_bairros(self) -> None:
        self.assertEqual(BAIRROS_POR_REGIAO, BAIRROS_OFICIAIS)
        self.assertEqual(
            {regiao: len(bairros) for regiao, bairros in BAIRROS_POR_REGIAO.items()},
            {"Praias da Baía": 17, "Norte": 12, "Pendotiba": 9, "Oceânica": 11, "Leste": 3},
        )
        self.assertEqual(BAIRROS_NITEROI, tuple(b for bairros in BAIRROS_OFICIAIS.values() for b in bairros))
        self.assertEqual(len(BAIRROS_NITEROI), 52)
        self.assertEqual(len({normalizar(b) for b in BAIRROS_NITEROI}), 52)

    def test_bairro_no_fim_da_ementa(self) -> None:
        casos = {
            "Solicito ao Poder Executivo, que seja realizado o serviço de tapa buraco localizado na Rua Hermes "
            "de Mata Barcelos (em frente ao n°20), Piratininga – Niterói.": "Piratininga",
            "Solicito ao Poder Executivo, que seja realizado o serviço de tapa buraco localizado na Av. dos "
            "Corais (em frente ao n°287), Jardim Imbuí – Niterói.": "Jardim Imbuí",
            "Solicito ao Poder Executivo, que seja realizado o serviço de troca da tampa de bueiro localizado na "
            "Rua Reverendo Armando Ferreira, (em frente ao n°176), Maceió – Niterói.": "Maceió",
        }
        for ementa, bairro in casos.items():
            with self.subTest(bairro=bairro):
                self.assertEqual(extrair_bairro(ementa), bairro)

    def test_vale_o_ultimo_bairro_citado(self) -> None:
        self.assertEqual(
            extrair_bairro("tapa buraco na Estrada Frei Orlando (em frente ao n°371) Jacaré, Piratininga – Niterói."),
            "Piratininga",
        )
        self.assertEqual(
            extrair_bairro("Rua. Jorn. Siney Correa (em frente ao n°437) Santo Antônio, Piratininga – Niterói."),
            "Piratininga",
        )

    def test_sem_acento_e_variantes(self) -> None:
        self.assertEqual(extrair_bairro("RUA MARIZ E BARROS, ICARAI"), "Icaraí")
        self.assertEqual(extrair_bairro("Rua Visconde de Itaboraí, Ponta D’Areia"), "Ponta d'Areia")
        self.assertEqual(extrair_bairro("Rua X, Ponta da Areia – Niterói"), "Ponta d'Areia")
        self.assertEqual(extrair_bairro("Avenida Y, Vital Brasil"), "Vital Brazil")
        self.assertEqual(extrair_bairro("Rua Z, Imbuí"), "Jardim Imbuí")
        self.assertEqual(extrair_bairro("Estrada W, VÁRZEA DAS MOÇAS"), "Várzea das Moças")

    def test_sem_bairro(self) -> None:
        self.assertIsNone(extrair_bairro("Solicito iluminação na Rua das Flores – Niterói."))
        self.assertIsNone(extrair_bairro(""))
        self.assertIsNone(extrair_bairro(None))

    def test_centro_so_como_bairro(self) -> None:
        self.assertEqual(extrair_bairro("em frente ao Centro Municipal de Educação Infantil, Fonseca"), "Fonseca")
        self.assertIsNone(extrair_bairro("em frente ao Centro de Saúde da Rua X"))
        self.assertEqual(extrair_bairro("Rua da Conceição, Centro – Niterói."), "Centro")
        self.assertEqual(extrair_bairro("no Centro de Niterói"), "Centro")

    def test_centro_pop_nao_e_o_bairro_centro(self) -> None:
        self.assertIsNone(extrair_bairro("Solicito a reforma do Centro POP."))
        self.assertIsNone(extrair_bairro("Solicito vagas no CENTRO POP da cidade"))
        self.assertEqual(extrair_bairro("em frente ao Centro Pop, Barreto – Niterói."), "Barreto")
        self.assertEqual(extrair_bairro("no Centro POP da Rua X, Centro – Niterói."), "Centro")

    def test_fatima_so_como_bairro(self) -> None:
        self.assertIsNone(extrair_bairro("em frente à Paróquia Nossa Senhora de Fátima"))
        self.assertEqual(extrair_bairro("Rua X, Fátima – Niterói."), "Fátima")


# ---------------------------------------------------------------------- indicações
class TestIndicacao(unittest.TestCase):
    def test_tapa_buraco_com_bairro(self) -> None:
        ementa = (
            "Solicito ao Poder Executivo, que seja realizado o serviço de tapa buraco localizado na Rua Hermes "
            "de Mata Barcelos (em frente ao n°20), Piratininga – Niterói."
        )
        self.assertEqual(
            classificar_documento(doc("indicacao", ementa, "Arquivado")),
            {"categoria": "zeladoria", "subcategoria": "asfalto", "homenagem": False, "respondido": False,
             "publicado": False, "bairro": "Piratininga"},
        )

    def test_subtipos_de_zeladoria(self) -> None:
        casos = {
            "Solicito a troca de lâmpadas queimadas na Rua Gavião Peixoto, Icaraí.": "iluminacao",
            "Solicito o serviço de tapa-buraco e recapeamento asfáltico na Rua X.": "asfalto",
            "Solicito o serviço de poda de árvore na Rua X, Santa Rosa.": "poda",
            "Solicito limpeza e capina do terreno na Rua Y, Fonseca.": "limpeza",
            "Solicito a capina do mato alto na Rua W, Engenho do Mato.": "limpeza",
            "Solicito o serviço de troca da tampa de bueiro na Rua Domingos Araújo, Piratininga.": "saneamento",
            "Solicito a instalação de quebra-molas na Estrada Z, Engenho do Mato.": "transito",
            "Solicito a sinalização horizontal da Rua Q, Barreto.": "transito",
            "Solicito a implantação de uma academia da terceira idade na Praça X, Itaipu.": "outra",
        }
        for ementa, esperado in casos.items():
            with self.subTest(ementa=ementa):
                c = classificar_documento(doc("indicacao", ementa))
                self.assertEqual(c["subcategoria"], esperado)
                self.assertEqual(c["categoria"], "zeladoria")
                self.assertIn(c["subcategoria"], SUBCATEGORIAS["indicacao"])

    def test_vale_o_servico_citado_primeiro(self) -> None:
        self.assertEqual(sub("indicacao", "Solicito a poda de árvore em frente ao bueiro da Rua X."), "poda")
        self.assertEqual(sub("indicacao", "Solicito tapa buraco na Rua X, próximo à árvore."), "asfalto")

    def test_bairro_engenho_do_mato_nao_e_limpeza(self) -> None:
        c = classificar_documento(doc("indicacao", "Solicito a instalação de quebra-molas na Estrada Z, Engenho do Mato."))
        self.assertEqual(c["bairro"], "Engenho do Mato")
        self.assertEqual(sub("indicacao", "Solicito melhorias na Estrada do Engenho do Mato."), "outra")


# ------------------------------------------------------------------- requerimentos
class TestRequerimento(unittest.TestCase):
    def test_pedido_de_informacao_respondido(self) -> None:
        c = classificar_documento(doc("requerimento", "REQUER INFORMAÇÕES SOBRE O PROCESSO Nº 1/2025", "RESPONDIDO"))
        self.assertEqual((c["categoria"], c["subcategoria"], c["respondido"]), ("fiscalizacao", "informacao", True))
        self.assertFalse(c["homenagem"])
        self.assertIsNone(c["bairro"])

    def test_outras_formas_de_pedido_de_informacao(self) -> None:
        for ementa in (
            "Requer informações ao Prefeito Municipal de Niterói acerca do evento.",
            "Pedido de informação sobre o contrato de iluminação.",
            "Requer ao Poder Executivo cópia do contrato de coleta de lixo.",
            "Requer o encaminhamento da íntegra do processo administrativo nº 1/2025.",
        ):
            with self.subTest(ementa=ementa):
                self.assertEqual(sub("requerimento", ementa), "informacao")

    def test_outro_requerimento(self) -> None:
        c = classificar_documento(doc("requerimento", "Requer a realização de Sessão Solene em homenagem ao Dia do Professor."))
        self.assertEqual((c["categoria"], c["subcategoria"], c["homenagem"]), ("outra", "outro", False))

    def test_respondido_so_para_requerimento(self) -> None:
        self.assertFalse(classificar_documento(doc("indicacao", "Solicito poda de árvore.", "RESPONDIDO"))["respondido"])
        self.assertFalse(classificar_documento(doc("requerimento", "REQUER INFORMAÇÕES", "ENCAMINHADO À PREFEITURA"))["respondido"])

    def test_respondido_pelo_ultimo_passo_mesmo_com_outra_situacao(self) -> None:
        # caso real: requerimento 70/2026 (id 294244), ainda "ENCAMINHADO À PREFEITURA"
        reg = {
            **doc("requerimento", "REQUER INFORMAÇÕES SOBRE GRAVE OCORRÊNCIA ENVOLVENDO ÓBITO DE ESTUDANTE "
                  "EM UNIDADE DA REDE MUNICIPAL DE ENSINO.", "ENCAMINHADO À PREFEITURA"),
            "id": 294244,
            "ultima_tramitacao": {"seq": 5, "objetivo": "Respondido", "enviado": "2026-08-06",
                                  "resultado": "Ofício Lido na Sessão Plenária do dia", "data_resposta": "2026-08-11",
                                  "observacao": ""},
        }
        self.assertTrue(consta_respondido(reg))
        self.assertTrue(classificar_documento(reg)["respondido"])
        pelo_resultado = {**reg, "ultima_tramitacao": {"objetivo": "Encaminhar", "resultado": "RESPONDIDA"}}
        self.assertTrue(classificar_documento(pelo_resultado)["respondido"])
        self.assertFalse(classificar_documento({**reg, "tipo": "indicacao"})["respondido"])

    def test_respondido_pela_data_da_resposta_do_detalhe(self) -> None:
        reg = {**doc("requerimento", "REQUER INFORMAÇÕES", "ENCAMINHADO À PREFEITURA"), "respondido_em": "2026-03-10"}
        self.assertTrue(classificar_documento(reg)["respondido"])
        self.assertFalse(classificar_documento({**reg, "respondido_em": None})["respondido"])

    def test_nao_respondido_nao_conta(self) -> None:
        base = doc("requerimento", "REQUER INFORMAÇÕES", "ENCAMINHADO À PREFEITURA")
        for passo_listado in (
            {"objetivo": "Não respondido", "resultado": ""},
            {"objetivo": "Prorrogação de prazo", "resultado": "NÃO RESPONDIDO NO PRAZO"},
            {"objetivo": "Aguardando resposta", "resultado": ""},
            None,
        ):
            with self.subTest(passo=passo_listado):
                self.assertFalse(classificar_documento({**base, "ultima_tramitacao": passo_listado})["respondido"])
        self.assertFalse(classificar_documento(doc("requerimento", "REQUER INFORMAÇÕES", "NÃO RESPONDIDO"))["respondido"])


# -------------------------------------------------------------------------- moções
class TestMocao(unittest.TestCase):
    def test_subtipos(self) -> None:
        casos = {
            "Moção de Congratulações e Aplausos a Sra. CRISTIANE MONTEIRO PAIXÃO.": ("aplauso", "homenagem"),
            "Moção de Pesar pelo falecimento do Sr. Fulano de Tal.": ("pesar", "homenagem"),
            "Moção de Repúdio às declarações do Sr. Fulano.": ("repudio", "manifestacao"),
            "MOÇÃO DE REPÚDIO À HOMENAGEM PRESTADA AO SR. FULANO.": ("repudio", "manifestacao"),
            "Moção de Apoio à greve dos professores da rede estadual.": ("apoio", "manifestacao"),
            "Moção de Apelo ao Governo do Estado.": ("outra", "manifestacao"),
        }
        for ementa, (subcategoria, categoria) in casos.items():
            with self.subTest(ementa=ementa):
                c = classificar_documento(doc("mocao", ementa))
                self.assertEqual((c["subcategoria"], c["categoria"]), (subcategoria, categoria))
                self.assertEqual(c["homenagem"], categoria == "homenagem")


# ---------------------------------------------------------------------------- PDLs
class TestPdl(unittest.TestCase):
    def test_titulo_de_cidadao(self) -> None:
        c = classificar_documento(doc("pdl", "CONCEDE O TÍTULO DE CIDADÃO NITEROIENSE A SUA SANTIDADE, O PAPA LEÃO XIV.", "PUBLICADO"))
        self.assertEqual((c["categoria"], c["subcategoria"]), ("homenagem", "titulo_cidadao"))
        self.assertTrue(c["homenagem"])
        self.assertTrue(c["publicado"])
        self.assertEqual(sub("pdl", "Concede o Título de Cidadão Benemérito ao advogado Fulano."), "titulo_cidadao")

    def test_medalha(self) -> None:
        self.assertEqual(sub("pdl", "CONCEDE A MEDALHA LEGISLATIVA FELISBERTO DE CARVALHO AO PROFESSOR FULANO."), "honraria")
        self.assertEqual(sub("pdl", "Concede Diploma de Honra ao Mérito à Escola X."), "honraria")

    def test_sustacao_nao_e_homenagem(self) -> None:
        c = classificar_documento(doc(
            "pdl",
            "Susta o Decreto Legislativo N° 3778/2025 decorrente do PDL nº 41/2025, que concedeu o Título de "
            "Cidadão Niteroiense ao Deputado Estadual Fulano.",
        ))
        self.assertEqual((c["categoria"], c["subcategoria"], c["homenagem"]), ("legislacao", "outra", False))

    def test_outro_pdl(self) -> None:
        self.assertEqual(
            classificar_documento(doc("pdl", "Aprova as contas do Prefeito referentes ao exercício de 2023."))["categoria"],
            "legislacao",
        )


# ---------------------------------------------------------------------- resoluções
class TestResolucao(unittest.TestCase):
    def test_subtipos(self) -> None:
        casos = {
            "Institui o Diploma Nédio Mocellin, destinado a enaltecer personalidades da gastronomia.": "honraria",
            "INSTITUI A MEDALHA LEGISLATIVA DO MÉRITO RELIGIOSO “SÃO JOÃO BATISTA”.": "honraria",
            "Altera o Regimento Interno da Câmara Municipal de Niterói (Resolução nº 2.181/1992) e institui a "
            "medalha legislativa municipal do mérito Fulano.": "honraria",
            "Altera a Resolução nº 2181/92 para incluir a Comissão Permanente de Ética e Decoro Parlamentar.": "regimento",
            "Altera o Título IV do Regimento Interno da Câmara Municipal.": "regimento",
            "Aprova o Orçamento da Câmara Municipal de Niterói para o Exercício Financeiro de 2026.": "administrativa",
            "INSTITUI A FRENTE PARLAMENTAR EVANGÉLICA NA CÂMARA MUNICIPAL DE NITERÓI.": "administrativa",
            "Dispõe sobre o uso de bicicletas compartilhadas.": "outra",
        }
        for ementa, esperado in casos.items():
            with self.subTest(ementa=ementa):
                c = classificar_documento(doc("resolucao", ementa))
                self.assertEqual(c["subcategoria"], esperado)
                self.assertEqual(c["categoria"], "homenagem" if esperado == "honraria" else "legislacao")

    def test_tipo_desconhecido(self) -> None:
        with self.assertRaises(ValueError):
            classificar_documento(doc("projeto_de_lei", "Dispõe sobre algo."))


# ------------------------------------------------------------------------- assunto
class TestAssunto(unittest.TestCase):
    def test_assunto_decide_quando_a_ementa_nao_basta(self) -> None:
        casos = (
            ("indicacao", "Solicito providências na Rua X, Icaraí.", "TAPA BURACO", "asfalto", "zeladoria"),
            ("indicacao", "Solicito providências na Rua X, Icaraí.", "BUEIRO", "saneamento", "zeladoria"),
            ("mocao", "Moção ao Sr. Fulano de Tal.", "APLAUSOS", "aplauso", "homenagem"),
            ("requerimento", "Requer ao Poder Executivo o envio do relatório anual.", "INFORMAÇÕES", "informacao",
             "fiscalizacao"),
            ("pdl", "Concede ao Sr. Fulano a distinção prevista em lei.", "DECRETO/MEDALHA", "honraria", "homenagem"),
            ("pdl", "Concede ao Sr. Fulano a distinção prevista em lei.", "CIDADÃO NITEROIENSE", "titulo_cidadao",
             "homenagem"),
            ("resolucao", "Dispõe sobre o uso de bicicletas compartilhadas.", "HOMENAGEM", "honraria", "homenagem"),
            ("resolucao", "Dispõe sobre o uso de bicicletas compartilhadas.", "LOA", "administrativa", "legislacao"),
        )
        for tipo, ementa, assunto, subcategoria, categoria in casos:
            with self.subTest(tipo=tipo, assunto=assunto):
                self.assertEqual(sub(tipo, ementa), SUBCATEGORIAS[tipo][-1])  # sem assunto: a padrão
                c = classificar_documento(doc(tipo, ementa, assunto=assunto))
                self.assertEqual((c["subcategoria"], c["categoria"]), (subcategoria, categoria))

    def test_ementa_prevalece_sobre_o_assunto(self) -> None:
        self.assertEqual(sub("indicacao", "Solicito a poda de árvore na Rua X.", "TAPA BURACO"), "poda")
        self.assertEqual(sub("mocao", "Moção de Repúdio ao ato do Sr. Fulano.", "APLAUSOS"), "repudio")
        self.assertEqual(sub("resolucao", "Altera o Regimento Interno da Câmara.", "HOMENAGEM"), "regimento")

    def test_assunto_ambiguo_ou_de_sustacao_nao_decide(self) -> None:
        c = classificar_documento(doc(
            "pdl", "Susta o Decreto Legislativo N° 3778/2025, que concedeu o Título de Cidadão Niteroiense.",
            assunto="DECRETO/TÍTULO",
        ))
        self.assertEqual((c["categoria"], c["subcategoria"], c["homenagem"]), ("legislacao", "outra", False))
        self.assertEqual(sub("pdl", "Concede ao Sr. Fulano a distinção prevista em lei.", "DECRETO/TÍTULO"), "outra")
        self.assertEqual(sub("resolucao", "Dispõe sobre o uso de bicicletas compartilhadas.", "SUSTAÇÃO DE HOMENAGEM"),
                         "outra")
        self.assertEqual(sub("indicacao", "Solicito providências na Rua X.", "DIVERSOS"), "outra")


# --------------------------------------------------------------------- derivações
class TestDerivarResposta(unittest.TestCase):
    def test_primeiro_passo_respondido(self) -> None:
        reg = {"data": "2025-12-01", "data_protocolo": "2025-12-11", "tramitacoes": [
            passo("Despachar", "Despachado", "2026-01-05", "2026-01-05"),
            passo("Prorrogação de prazo", "Lido na Sessão Plenária do dia", "2026-02-01", "2026-02-03"),
            passo("Respondido", "Ofício Lido na Sessão Plenária do dia", "2026-03-10", "2026-03-11"),
            passo("Respondido", "", "2026-04-01"),
        ]}
        self.assertEqual(derivar_resposta(reg), {"respondido_em": "2026-03-10", "dias_ate_resposta": 89})

    def test_resultado_em_maiusculas_e_sem_protocolo(self) -> None:
        reg = {"data": "2026-01-01", "tramitacoes": [passo("ENCAMINHADO", "RESPONDIDO", "2026-01-31")]}
        self.assertEqual(derivar_resposta(reg), {"respondido_em": "2026-01-31", "dias_ate_resposta": 30})

    def test_sem_resposta(self) -> None:
        reg = {"data": "2026-01-01", "tramitacoes": [
            passo("Prorrogação de prazo", "Lido na Sessão Plenária do dia", "2026-02-01", "2026-02-02"),
            passo("Não respondido", "", "2026-03-01"),
        ]}
        vazio = {"respondido_em": None, "dias_ate_resposta": None}
        self.assertEqual(derivar_resposta(reg), vazio)
        self.assertEqual(derivar_resposta({"data": "2026-01-01"}), vazio)

    def test_datas_incoerentes_nao_contam_dias(self) -> None:
        reg = {"data": "2026-05-01", "tramitacoes": [passo("Respondido", "", "2026-04-01")]}
        self.assertEqual(derivar_resposta(reg), {"respondido_em": "2026-04-01", "dias_ate_resposta": None})


class TestDerivarPublicacao(unittest.TestCase):
    def test_passo_publicado_que_nao_e_o_ultimo(self) -> None:
        trams = [
            passo("Leitura", "Lido na Sessão Plenária", "2025-12-10", "2025-12-10"),
            passo("Publicar", "Publicado", "2025-12-12", "2025-12-12", 'DECRETO LEGISLATIVO N° 3993/2025, NO JORNAL "A TRIBUNA"'),
            passo("Arquivar", "Arquivado através do MEMO Nº", "2026-01-06", "2026-01-06", "001/2026"),
        ]
        self.assertEqual(derivar_publicacao(trams), {"numero": 3993, "data": "2025-12-12"})

    def test_numero_com_ponto_e_data_da_observacao(self) -> None:
        trams = [passo("Publicar", "PUBLICADA", "2026-02-26", None,
                       'RESOLUÇÃO Nº 3.167/2025, NO JORNAL "A TRIBUNA" DE 27/02/2026')]
        self.assertEqual(derivar_publicacao(trams), {"numero": 3167, "data": "2026-02-27"})

    def test_prefere_o_passo_que_cita_o_ato(self) -> None:
        trams = [
            passo("Publicar", "Publicado", "2026-01-01", "2026-01-02", "PROJETO DE RESOLUÇÃO Nº 22/2025"),
            passo("Publicar", "Publicado", "2026-01-05", "2026-01-06", "RESOLUÇÃO Nº 3170/2026"),
        ]
        self.assertEqual(derivar_publicacao(trams), {"numero": 3170, "data": "2026-01-06"})
        self.assertEqual(derivar_publicacao(trams[:1]), {"numero": None, "data": "2026-01-02"})

    def test_sem_publicacao(self) -> None:
        self.assertIsNone(derivar_publicacao([passo("Publicar", "", "2026-01-01")]))
        self.assertIsNone(derivar_publicacao([passo("Publicar", "Não publicado", "2026-01-01")]))
        self.assertIsNone(derivar_publicacao([]))
        self.assertIsNone(derivar_publicacao(None))


# -------------------------------------------------------- listagens reais (fixtures)
class TestListagensReais(unittest.TestCase):
    def test_todos_os_registros_classificam(self) -> None:
        for tipo in documentos.TIPOS:
            for reg in listagem(tipo):
                c = classificar_documento(reg)
                self.assertIn(c["categoria"], CATEGORIAS)
                self.assertIn(c["subcategoria"], SUBCATEGORIAS[tipo])

    def test_indicacoes(self) -> None:
        por_numero = {r["numero"]: classificar_documento(r) for r in listagem("indicacao")}
        self.assertEqual(
            {n: c["bairro"] for n, c in por_numero.items()},
            {"400/2025": "Piratininga", "399/2025": "Piratininga", "398/2025": "Piratininga",
             "397/2025": "Piratininga", "396/2025": "Jardim Imbuí", "395/2025": "Maceió",
             "394/2025": "Piratininga", "393/2025": "Piratininga", "392/2025": "Piratininga",
             "391/2025": "Piratininga"},
        )
        saneamento = {n for n, c in por_numero.items() if c["subcategoria"] == "saneamento"}
        self.assertEqual(saneamento, {"397/2025", "395/2025"})
        self.assertTrue(all(c["subcategoria"] == "asfalto" for n, c in por_numero.items() if n not in saneamento))

    def test_requerimentos_e_mocoes(self) -> None:
        reqs = {r["id"]: classificar_documento(r) for r in listagem("requerimento")}
        self.assertTrue(all(c["subcategoria"] == "informacao" for c in reqs.values()))
        self.assertEqual({i for i, c in reqs.items() if c["respondido"]}, {290504, 290036})
        self.assertTrue(all(classificar_documento(r)["subcategoria"] == "aplauso" for r in listagem("mocao")))

    def test_pdls_e_resolucoes(self) -> None:
        pdls = {r["numero"]: classificar_documento(r)["subcategoria"] for r in listagem("pdl")}
        self.assertEqual({n for n, s in pdls.items() if s == "titulo_cidadao"}, {"310/2025", "309/2025"})
        self.assertEqual({n for n, s in pdls.items() if s == "outra"}, {"307/2025"})
        resolucoes = {r["numero"]: classificar_documento(r)["subcategoria"] for r in listagem("resolucao")}
        self.assertEqual(
            resolucoes,
            {"22/2025": "honraria", "21/2025": "administrativa", "20/2025": "administrativa",
             "19/2025": "administrativa", "18/2025": "honraria", "17/2025": "honraria", "16/2025": "regimento",
             "15/2025": "honraria", "14/2025": "administrativa", "13/2025": "honraria"},
        )


# -------------------------------------------------------------------------- perfil
class TestEixosPerfil(unittest.TestCase):
    """A regra do perfil fica só aqui; coletor.site.modelo a consome (veja tests/test_modelo_documentos.py)."""

    def test_eixo_de_cada_tipo_de_documento(self) -> None:
        casos = (
            ("indicacao", "Solicito tapa buraco na Rua X, Icaraí.", ["zeladoria"]),
            ("requerimento", "REQUER INFORMAÇÕES SOBRE O CONTRATO.", ["fiscalizacao"]),
            ("requerimento", "Requer a realização de Sessão Solene.", []),
            ("mocao", "Moção de Aplausos ao Sr. Fulano.", ["homenagem"]),
            ("mocao", "Moção de Congratulações à equipe.", ["homenagem"]),
            ("mocao", "Moção de Pesar pelo falecimento do Sr. Fulano.", ["homenagem"]),
            ("mocao", "Moção de Repúdio ao ato.", []),
            ("mocao", "Moção de Apoio à greve.", []),
            ("pdl", "CONCEDE O TÍTULO DE CIDADÃO NITEROIENSE A FULANO.", ["homenagem"]),
            ("pdl", "Susta o Decreto Legislativo nº 1/2025, que concedeu o Título de Cidadão.", ["legislacao"]),
            ("resolucao", "Institui a Medalha Legislativa do Mérito Esportivo.", ["homenagem"]),
            ("resolucao", "Aprova o Orçamento da Câmara Municipal.", ["legislacao"]),
        )
        for tipo, ementa, eixos in casos:
            with self.subTest(ementa=ementa):
                self.assertEqual(eixos_perfil(classificar_documento(doc(tipo, ementa))), eixos)

    def test_aceita_documento_do_modelo_e_so_eixos_conhecidos(self) -> None:
        for categoria in CATEGORIAS:
            eixos = eixos_perfil({"categoria": categoria, "homenagem": categoria == "homenagem"})
            self.assertTrue(set(eixos) <= set(EIXOS_PERFIL))
            self.assertEqual(eixos, [categoria] if categoria in EIXOS_PERFIL else [])


# ------------------------------------------------------- requerimentos de informação
class TestOrgao(unittest.TestCase):
    def test_ementas_reais(self) -> None:
        # Ementas de data/documentos/requerimento/2026.json (números entre parênteses).
        casos = {
            "REQUER INFORMAÇÕES À SECRETARIA MUNICIPAL DE EDUCAÇÃO E À FUNDAÇÃO MUNICIPAL DE EDUCAÇÃO PARA FINS DE "
            "FISCALIZAÇÃO PARLAMENTAR DE INDICADORES EDUCACIONAIS (8/2026)": "Secretaria de Educação",
            "Requer informações ao Prefeito Municipal de Niterói, Sr. Rodrigo Neves, com cópia à Secretaria Municipal de "
            "Educação, acerca da estrutura da rede municipal de ensino (51/2026)": "Secretaria de Educação",
            "REQUER INFORMAÇÕES SOBRE CONTRATAÇÕES DE MATERIAL GRÁFICO PELA SECRETARIA MUNICIPAL DAS CULTURAS (61/2026)":
                "Secretaria das Culturas",
            "REQUER INFORMAÇÕES AO PODER EXECUTIVO, POR INTERMÉDIO DA NITTRANS, ACERCA DOS CRITÉRIOS TÉCNICOS ADOTADOS "
            "PARA IMPLANTAÇÃO DE VAGAS DE ESTACIONAMENTO NO ENTORNO DE PONTOS DE ÔNIBUS (50/2026)": "NitTrans",
            "REQUER INFORMAÇÕES À COMPANHIA MUNICIPAL DE LIMPEZA URBANA DE NITERÓI — CLIN ACERCA DE EVENTUAL PROCESSO DE "
            "CONTRATAÇÃO DE NOVO PLANO DE SAÚDE (74/2026)": "Clin",
            "REQUER INFORMAÇÕES AO PODER EXECUTIVO E À EMPRESA DE INFRAESTRUTURA E OBRAS DE NITERÓI – ION (ANTIGA EMUSA) "
            "ACERCA DA CONTRATAÇÃO (116/2026)": "ION (antiga Emusa)",
            "REQUER INFORMAÇÕES AO PODER EXECUTIVO MUNICIPAL SOBRE A PARTICIPAÇÃO DE SERVIDORES E AGENTES PÚBLICOS EM "
            "AGENDA NA ORGANIZAÇÃO DAS NAÇÕES UNIDAS PARA A ALIMENTAÇÃO E A AGRICULTURA (FAO) (6/2026)": ORGAO_EXECUTIVO,
            "REQUER INFORMAÇÕES SOBRE O SISTEMA INFORMATIZADO DE TALÃO ELETRÔNICO QUE CONSTA HOMOLOGADO PARA O MUNICÍPIO "
            "DE NITERÓI/NITTRANS NA FORMA DA PORTARIA SENATRAN 997/2022 (84/2026)": "NitTrans",
            "REQUER À SECRETARIA MUNICIPAL DE DEFESA CIVIL E GEOTECNIA O ENVIO DE CÓPIA INTEGRAL DO AUTO DE INTERDIÇÃO "
            "(112/2026)": "Defesa Civil",
            "REQUER AO GABINETE DO PREFEITO, COM CÓPIA PARA A SECONSER, EMUSA/ION E SECRETARIA MUNICIPAL DE "
            "DESENVOLVIMENTO ECONÔMICO E REVITALIZAÇÃO DO CENTRO, A CÓPIA INTEGRAL (172/2026)":
                "Secretaria de Conservação e Serviços Públicos",
            "REQUER INFORMAÇÕES SOBRE A SITUAÇÃO FUNCIONAL DO SERVIDOR FULANO, OCUPANTE DO CARGO DE SUBSECRETÁRIO DA "
            "SECRETARIA MUNICIPAL DE ORDEM PÚBLICA (108/2026)": "Secretaria de Ordem Pública",
            # Detran citado no meio do pedido, não como destinatário: vale o nível municipal.
            "REQUER INFORMAÇÕES SOBRE A APLICAÇÃO DO DECRETO MUNICIPAL 743/2026 QUE INSTITUIU REGIME EXCEPCIONAL PARA "
            "REGULARIZAÇÃO DE MULTAS DE ESTACIONAMENTO ROTATIVO E OS TRÂMITES PARA O CANCELAMENTO AUTOMÁTICO DE AUTOS DE "
            "INFRAÇÃO COM RECURSOS PENDENTES E OS PROCEDIMENTOS DE COMUNICAÇÃO E BAIXA JUNTO AO DETRAN-RJ. (122/2026)":
                ORGAO_EXECUTIVO,
            "REQUER INFORMAÇÕES SOBRE OS PROCEDIMENTOS DO DECRETO MUNICIPAL Nº 743/2026 E A ARTICULAÇÃO DA NITTRANS JUNTO "
            "AO DETRAN-RJ (131/2026)": "NitTrans",
            "REQUER INFORMAÇÕES À SECRETARIA MUNICIPAL DE MOBILIDADE URBANA ACERCA DA ADMINISTRAÇÃO DO FUNDO MUNICIPAL DE "
            "MOBILIDADE URBANA (90/2026)": "Secretaria de Mobilidade Urbana",
            "REQUER INFORMAÇÕES AO PODER EXECUTIVO MUNICIPAL, À SECRETARIA MUNICIPAL DE URBANISMO E MOBILIDADE (SMU) E À "
            "EMPRESA DE INFRAESTRUTURA E OBRAS DE NITERÓI (ION) ACERCA DA EXECUÇÃO DAS OBRAS (153/2026)":
                "Secretaria de Urbanismo e Mobilidade",
            "REQUER INFORMAÇÕES AO PODER EXECUTIVO ACERCA DO FINANCIAMENTO DO SERVIÇO DE ATENDIMENTO MÓVEL DE URGÊNCIA – "
            "SAMU, NO ÂMBITO DA FUNDAÇÃO MUNICIPAL DE SAÚDE DE NITERÓI. (97/2026)": "Fundação Municipal de Saúde",
            "REQUER À PREFEITURA MUNICIPAL DE NITERÓI E À FUNDAÇÃO MUNICIPAL DE EDUCAÇÃO ESCLARECIMENTOS SOBRE A ANÁLISE "
            "E A ATRIBUIÇÃO DE PONTUAÇÃO DE TÍTULOS (165/2026)": "Fundação Municipal de Educação",
        }
        for ementa, orgao in casos.items():
            with self.subTest(ementa=ementa[:60]):
                self.assertEqual(extrair_orgao(ementa), orgao)

    def test_secretarias_normalizadas(self) -> None:
        casos = {
            "Requer informações ao Secretário Municipal de Saúde sobre vacinas.": "Secretaria de Saúde",
            "Requer informações à Secretaria de Saúde de Niterói.": "Secretaria de Saúde",
            "Requer informações à Secretaria Municipal do Meio Ambiente.": "Secretaria de Meio Ambiente",
            "Requer informações à Secretaria Municipal de Desenvolvimento Econômico.": "Secretaria de Desenvolvimento Econômico",
            "Requer informações à Secretaria Municipal de Desenvolvimento Regional.": ORGAO_OUTRA_SECRETARIA,
            "Requer informações à Secretaria Municipal de Inovação.": ORGAO_OUTRA_SECRETARIA,
            "Requer informações à Secretaria competente sobre o contrato.": ORGAO_NAO_IDENTIFICADO,
            "Requer à Secretaria Mesa Diretora a cópia da ata.": ORGAO_NAO_IDENTIFICADO,
            "Requer informações sobre normas da Secretaria Nacional de Trânsito.": ORGAO_NAO_IDENTIFICADO,
            "Requer informações sobre a Secretaria Especial de Assuntos Federativos.": ORGAO_NAO_IDENTIFICADO,
        }
        for ementa, orgao in casos.items():
            with self.subTest(ementa=ementa):
                self.assertEqual(extrair_orgao(ementa), orgao)

    def test_area_sem_conector_nao_vira_secretaria(self) -> None:
        # "SR" e "E" vinham como área: "Outra secretaria municipal" (e a segunda passava à frente da Fundação).
        self.assertEqual(extrair_orgao("Requer informações ao Secretário Municipal, Sr. Fulano de Tal, sobre o contrato."),
                         ORGAO_NAO_IDENTIFICADO)
        self.assertEqual(extrair_orgao("Requer informações à Secretaria Municipal e à Fundação Municipal de Saúde sobre o SAMU."),
                         "Fundação Municipal de Saúde")
        self.assertEqual(extrair_orgao("Requer informações à Secretaria Executiva sobre a agenda."), "Secretaria Executiva")

    def test_orgao_estadual_so_como_destinatario(self) -> None:
        casos = {
            "Requer informações à Secretaria de Estado de Saúde sobre leitos.": ORGAO_ESTADUAL,
            "Requer informações ao Governo do Estado sobre a CEDAE.": ORGAO_ESTADUAL,
            "Requer, junto ao Governo do Estado, informações sobre a duplicação da RJ-104.": ORGAO_ESTADUAL,
            "Requer informações ao DETRAN-RJ sobre as vistorias.": ORGAO_ESTADUAL,
            # Citado em outro papel: o pedido vai ao Executivo municipal.
            "Requer informações sobre o convênio entre o Município e o DETRAN.": ORGAO_EXECUTIVO,
            "Requer informações sobre a Secretaria de Estado de Saúde.": ORGAO_EXECUTIVO,
            "Requer informações à NitTrans sobre o convênio com o Governo do Estado.": "NitTrans",
        }
        for ementa, orgao in casos.items():
            with self.subTest(ementa=ementa):
                self.assertEqual(extrair_orgao(ementa), orgao)

    def test_vale_o_primeiro_orgao_especifico(self) -> None:
        self.assertEqual(extrair_orgao("Requer informações à NitTrans e à Secretaria de Obras."), "NitTrans")
        self.assertEqual(extrair_orgao("Requer informações à Secretaria de Obras e à NitTrans."), "Secretaria de Obras")
        self.assertEqual(extrair_orgao("Requer informações ao Prefeito sobre o contrato com a concessionária Águas de Niterói."),
                         "Águas de Niterói (concessionária)")
        self.assertEqual(extrair_orgao("Requer informações sobre a concessionária de ônibus."), ORGAO_CONCESSIONARIA)
        self.assertEqual(extrair_orgao("Requer informações ao Prefeito sobre a concessionária de ônibus."), ORGAO_CONCESSIONARIA)
        self.assertEqual(extrair_orgao("Requer informações à Prefeitura sobre a obra."), ORGAO_EXECUTIVO)

    def test_assunto_so_quando_a_ementa_nao_traz_orgao_especifico(self) -> None:
        self.assertEqual(extrair_orgao("Requer informações sobre o Hospital Fulano.", "INFORMAÇÕES"), ORGAO_NAO_IDENTIFICADO)
        self.assertEqual(extrair_orgao("Requer informações sobre vagas de estacionamento.", "NITTRANS"), "NitTrans")
        self.assertEqual(extrair_orgao("Requer informações ao Poder Executivo sobre vagas.", "NITTRANS"), "NitTrans")
        self.assertEqual(extrair_orgao("Requer informações à Secretaria de Obras.", "NITTRANS"), "Secretaria de Obras")

    def test_sem_falsos_positivos(self) -> None:
        for ementa in (
            "Requer informações sobre a clínica da família do Fonseca.",
            "Requer informações sobre a ampla divulgação do concurso.",
            "Requer informações à SMS sobre vacinas.",  # sigla ambígua: não reconhecida
            "",
            None,
        ):
            with self.subTest(ementa=ementa):
                self.assertEqual(extrair_orgao(ementa), ORGAO_NAO_IDENTIFICADO)


class TestEstadoPedido(unittest.TestCase):
    def test_estados(self) -> None:
        casos = (
            (True, "ARQUIVADO", "respondido"),
            (True, "RETIRADO", "respondido"),
            (False, "RETIRADO", "retirado"),
            (False, "Arquivado", "encerrado"),
            (False, "REJEITADO", "encerrado"),
            (False, "Prejudicado", "encerrado"),
            (False, "ENCAMINHADO À PREFEITURA", "aguardando"),
            (False, "RECEBIDO PELA SMD", "aguardando"),
            (False, "", "aguardando"),
            (False, None, "aguardando"),
        )
        for respondido, situacao, esperado in casos:
            with self.subTest(respondido=respondido, situacao=situacao):
                self.assertEqual(estado_pedido(respondido, situacao), esperado)
                self.assertIn(esperado, ESTADOS_PEDIDO)


if __name__ == "__main__":
    unittest.main()
