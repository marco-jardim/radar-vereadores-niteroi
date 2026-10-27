"""Testes das métricas dos documentos no modelo do site e das tabelas geradas no servidor.

Cobre o perfil de atuação com uma única regra (regras_documentos.eixos_perfil), homenagens com
contagem e peso, requerimentos de informação por vereador e por órgão e bairros das indicações.
Usa dados sintéticos e fixtures; não lê data/ nem escreve em site/.

Uso: python -m unittest tests.test_modelo_documentos  (ou pytest tests/test_modelo_documentos.py)
"""
from __future__ import annotations

import unittest
from unittest import mock

from coletor import documentos as coleta
from coletor import regras_documentos as RD
from coletor.site import modelo as M
from coletor.site import paginas as P
from tests.apoio import ler_fixture
from tests.test_documentos_site import CFG, DOCS, doc, montar
from tests.test_tabelas_empilhaveis import sem_empilhamento

MICHEL = [{"id": 275, "nome": "Michel Salim Saad Neto"}]
# DOCS de test_documentos_site com os cinco tipos em 2026 (coleta completa) e 2025 só com moção (coleta parcial),
# mais um pedido de informação de Michel ainda sem detalhe.
DOCS_METRICAS = {
    **DOCS,
    ("requerimento", 2026): DOCS[("requerimento", 2026)] + [
        doc(900012, "requerimento", "5/2026", "2026-02-15", "Requer informações à NitTrans sobre vagas de estacionamento.",
            MICHEL, detalhe_pendente=True),
    ],
    ("mocao", 2026): [doc(900030, "mocao", "7/2026", "2026-05-01", "Moção de repúdio ao ato do Sr. Fulano.", MICHEL,
                          situacao="APROVADA")],
    ("resolucao", 2026): [doc(900040, "resolucao", "3/2026", "2026-05-02", "Aprova o Orçamento da Câmara Municipal.",
                              [{"id": 278, "nome": "Mesa Diretora 2025/2026"}], situacao="PUBLICADO")],
}


def eixos_perfil_anterior(d: dict) -> list[str]:
    """Cópia literal de modelo.eixos_perfil antes de a regra ficar só em regras_documentos."""
    eixos = [e for e in ("zeladoria", "fiscalizacao", "legislacao") if d["categoria"] == e]
    if d["homenagem"]:
        eixos.append("homenagem")
    return eixos


def listagem(tipo: str) -> list[dict]:
    return coleta.parse_listagem(ler_fixture("siscam", f"listagem_tipo{coleta.TIPOS[tipo]}_2025.html"), tipo)


def item(**campos) -> dict:
    """Documento do modelo (montar_documentos) só com os campos que as agregações leem."""
    base = {"tipo": "requerimento", "subcategoria": "informacao", "categoria": "fiscalizacao", "homenagem": False,
            "respondido": False, "situacao": "", "dias_ate_resposta": None, "bairro": None, "ano": 2026,
            "legislatura": "2025-2028", "ementa": "", "assunto": None, "orgao": None}
    return {**base, **campos}


def indicacao(bairro: str | None, **campos) -> dict:
    return item(tipo="indicacao", subcategoria="asfalto", categoria="zeladoria", bairro=bairro, **campos)


# -------------------------------------------------------------------------- perfil
class TestPerfilUmaFonte(unittest.TestCase):
    """O perfil tinha a regra em dois lugares (regras_documentos.perfil_atuacao e modelo.eixos_perfil)."""

    def test_regra_so_em_regras_documentos(self):
        self.assertFalse(hasattr(M, "eixos_perfil"))
        self.assertFalse(hasattr(RD, "perfil_atuacao"))

    def test_mesmos_eixos_em_todas_as_combinacoes(self):
        for categoria in (*RD.CATEGORIAS, "desconhecida"):
            for homenagem in (False, True):
                d = {"categoria": categoria, "homenagem": homenagem}
                with self.subTest(**d):
                    self.assertEqual(RD.eixos_perfil(d), eixos_perfil_anterior(d))

    def test_mesmos_eixos_nas_listagens_reais(self):
        for tipo in coleta.TIPOS:
            for reg in listagem(tipo):
                c = RD.classificar_documento(reg)
                with self.subTest(tipo=tipo, numero=reg["numero"]):
                    self.assertEqual(RD.eixos_perfil(c), eixos_perfil_anterior(c))

    def test_perfil_do_modelo_igual_ao_de_perfil_atuacao(self):
        # Registros e contagens do antigo teste de perfil_atuacao (com nao_vereador): o perfil por
        # legislatura do modelo, somado, dá o mesmo resultado por autor.
        registros = [
            doc(1, "indicacao", "1/2025", "2025-03-01", "Solicito tapa buraco na Rua X, Icaraí.", [{"id": 237, "nome": "ROBSON"}]),
            doc(2, "indicacao", "2/2025", "2025-03-02", "Solicito poda de árvore.",
                [{"id": 237, "nome": "ROBSON"}, {"id": 237, "nome": "ROBSON"}]),
            doc(3, "requerimento", "3/2025", "2025-03-03", "REQUER INFORMAÇÕES SOBRE O CONTRATO.", [{"id": 275, "nome": "MICHEL"}]),
            doc(4, "pdl", "4/2025", "2025-03-04", "CONCEDE O TÍTULO DE CIDADÃO NITEROIENSE A FULANO.",
                [{"id": 272, "nome": "ALLAN PINHO LYRA"}, {"id": 9, "nome": "MILTON CARLOS DA SILVA LOPES"}]),
            doc(5, "pdl", "5/2025", "2025-03-05", "Susta o Decreto Legislativo nº 1/2025.", [{"id": 281, "nome": "EDUARDO"}]),
            doc(6, "resolucao", "6/2025", "2025-03-06", "Aprova o Orçamento da Câmara Municipal.",
                [{"id": 278, "nome": "Mesa Diretora 2025/2026"}]),
            doc(7, "mocao", "7/2025", "2025-03-07", "Moção de Aplausos ao Sr. Fulano.", [{"id": 285, "nome": "ANTONIO"}]),
            doc(8, "mocao", "8/2025", "2025-03-08", "Moção de Repúdio ao ato.", [{"id": 285, "nome": "ANTONIO"}]),
        ]
        docs = M.montar_documentos(registros, CFG, {}, CFG["legislaturas"])
        perfil = {}
        for s, reg in M.atividade_por_autor(docs).items():
            soma = dict.fromkeys(RD.EIXOS_PERFIL, 0)
            for leg in reg["por_leg"].values():
                for eixo, n in leg["perfil"].items():
                    soma[eixo] += n
            perfil[s] = soma
        contagem = lambda **v: {**dict.fromkeys(RD.EIXOS_PERFIL, 0), **v}
        self.assertEqual(perfil, {
            "robson": contagem(zeladoria=2),
            "michel": contagem(fiscalizacao=1),
            "allan-pinho-lyra": contagem(homenagem=1),
            "milton-carlos-da-silva-lopes": contagem(homenagem=1),
            "eduardo": contagem(legislacao=1),
            "antonio": contagem(homenagem=1),
        })


# ---------------------------------------------------------------------- homenagens
class TestHomenagens(unittest.TestCase):
    DOCS = [
        item(tipo="mocao", subcategoria="aplauso", categoria="homenagem", homenagem=True, ano=2026),
        item(tipo="pdl", subcategoria="titulo_cidadao", categoria="homenagem", homenagem=True, ano=2026),
        item(tipo="mocao", subcategoria="repudio", categoria="manifestacao", ano=2026),
        item(tipo="mocao", subcategoria="pesar", categoria="homenagem", homenagem=True, ano=2025),
    ]
    PROJETOS = [
        {"ano": 2026, "legislatura": "2025-2028"},
        {"ano": 2026, "legislatura": "2025-2028"},
        {"ano": 2024, "legislatura": "2021-2024"},  # ano sem documentos coletados: fica de fora
    ]

    def test_contagem_e_peso_por_ano_e_legislatura(self):
        r = M.homenagens_por_periodo(self.DOCS, self.PROJETOS)
        self.assertEqual(r["por_ano"], {
            2025: {"homenagens": 1, "documentos": 1, "projetos": 0, "producao": 1, "pct": 100},
            2026: {"homenagens": 2, "documentos": 3, "projetos": 2, "producao": 5, "pct": 40},
        })
        self.assertEqual(r["por_leg"], {"2025-2028": {"homenagens": 3, "documentos": 4, "projetos": 2, "producao": 6, "pct": 50}})
        com_2024 = M.homenagens_por_periodo(self.DOCS, self.PROJETOS, {2024, 2025, 2026})
        self.assertEqual(com_2024["por_leg"]["2021-2024"], {"homenagens": 0, "documentos": 0, "projetos": 1, "producao": 1, "pct": 0})

    def test_repudio_e_apoio_nao_sao_homenagem(self):
        for ementa in ("Moção de Repúdio ao ato.", "Moção de Apoio à greve."):
            self.assertFalse(RD.classificar_documento({"tipo": "mocao", "ementa": ementa})["homenagem"])
        self.assertEqual(M.resumo_homenagens(self.DOCS[2:3], 0)["homenagens"], 0)
        self.assertIsNone(M.resumo_homenagens([], 0)["pct"])

    def test_camara_por_ano_e_tipo(self):
        anos = M.homenagens_por_ano(self.DOCS, self.PROJETOS)
        self.assertEqual([a["ano"] for a in anos], [2025, 2026])
        self.assertEqual(anos[1]["por_tipo"], {"requerimento": 0, "indicacao": 0, "mocao": 1, "pdl": 1, "resolucao": 0})
        self.assertEqual((anos[1]["homenagens"], anos[1]["producao"], anos[1]["pct"]), (2, 5, 40))
        so_completos = M.homenagens_por_ano(self.DOCS, self.PROJETOS, {2026})
        self.assertEqual([a["ano"] for a in so_completos], [2026])


class TestAnosColeta(unittest.TestCase):
    """O peso das homenagens só usa anos em que os cinco tipos têm registro, calculados uma vez no modelo."""

    def test_completos_e_parciais(self):
        docs = [item(tipo=t, ano=2026) for t in M.TIPOS_DOC] + [item(tipo="mocao", ano=2025)]
        self.assertEqual(M.anos_coleta(docs), {"todos": [2025, 2026], "completos": [2026], "parciais": [2025]})
        self.assertEqual(M.anos_coleta([]), {"todos": [], "completos": [], "parciais": []})

    def test_ano_parcial_fica_fora_do_peso(self):
        docs = [item(tipo=t, ano=2026, legislatura="2025-2028") for t in M.TIPOS_DOC]
        docs.append(item(tipo="mocao", subcategoria="aplauso", categoria="homenagem", homenagem=True, ano=2025))
        modelo = {"documentos": docs, "pessoas": {}, "atividade": {"x": {"documentos": docs, "por_leg": {}}}}
        self.assertEqual(M.anos_documentos(modelo), {2026})
        h = M.homenagens_do_autor(modelo, "x")
        self.assertEqual(list(h["por_ano"]), [2026])
        self.assertEqual(h["por_leg"]["2025-2028"], {"homenagens": 0, "documentos": 5, "projetos": 0, "producao": 5, "pct": 0})

    def test_calculado_uma_vez_no_modelo(self):
        modelo = montar(DOCS_METRICAS)
        self.assertEqual(modelo["anos_coleta"], {"todos": [2025, 2026], "completos": [2026], "parciais": [2025]})
        self.assertEqual(M.anos_documentos({"anos_coleta": {"todos": [2030], "completos": [2030], "parciais": []},
                                            "documentos": []}), {2030})  # usa o valor guardado
        with mock.patch.object(M, "anos_coleta", side_effect=AssertionError("recalculou anos_coleta")):
            for pessoa in modelo["pessoas"].values():
                P.gerar_vereador(modelo, pessoa)
            P.gerar_ruido(modelo)
            P.gerar_atividades(modelo, {"build_doc": "x", "arquivos": {"doc-mocao-2026": {"familia": "doc", "ano": 2026}}})
            P.gerar_metodologia(modelo)


# ------------------------------------------------------- requerimentos de informação
class TestInformacao(unittest.TestCase):
    DOCS = [
        item(respondido=True, situacao="RESPONDIDO", dias_ate_resposta=10, orgao="NitTrans"),
        item(respondido=True, situacao="RESPONDIDO", dias_ate_resposta=20, orgao="NitTrans"),
        item(respondido=True, situacao="ENCAMINHADO À PREFEITURA", orgao="Secretaria de Saúde"),
        item(situacao="ENCAMINHADO À PREFEITURA", orgao="Secretaria de Saúde"),
        item(situacao="Arquivado", orgao=RD.ORGAO_NAO_IDENTIFICADO),
        item(situacao="RETIRADO", orgao=RD.ORGAO_NAO_IDENTIFICADO),
        item(situacao="RECEBIDO PELA SMD", orgao=RD.ORGAO_NAO_IDENTIFICADO, detalhe_pendente=True),
        item(subcategoria="outro", categoria="outra", respondido=True, dias_ate_resposta=1,
             detalhe_pendente=True),  # não é pedido de informação
        indicacao("Icaraí"),
    ]

    def test_resumo(self):
        self.assertEqual(M.resumo_informacao(self.DOCS), {
            "pedidos": 7, "respondidos": 3, "aguardando": 2, "encerrados": 1, "retirados": 1,
            "taxa": 50, "mediana_dias": 15, "com_dias": 2, "pendentes": 1,
        })

    def test_base_da_mediana_e_pendentes_no_texto(self):
        r = M.resumo_informacao(self.DOCS)
        self.assertEqual(P.base_mediana_txt(r), "mediana entre 2 respondidos com data")
        self.assertEqual(P.base_mediana_txt({**r, "com_dias": 1}), "mediana entre 1 respondido com data")
        self.assertEqual(P.pendentes_txt(r), "1 requerimento de informação ainda está com o detalhe pendente.")
        self.assertEqual(P.pendentes_txt({**r, "pendentes": 0}), "Nenhum requerimento de informação está com o detalhe pendente.")
        self.assertEqual(P.celulas_informacao(r), [7, 3, "50%", 15, 2, 2, 1, 1])
        vazio = M.resumo_informacao([indicacao(None)])
        self.assertEqual((vazio["pedidos"], vazio["taxa"], vazio["mediana_dias"]), (0, None, None))

    def test_ranking_por_orgao(self):
        ranking = M.ranking_orgaos(self.DOCS)
        self.assertEqual([(o["orgao"], o["pedidos"]) for o in ranking],
                         [("NitTrans", 2), ("Secretaria de Saúde", 2), (RD.ORGAO_NAO_IDENTIFICADO, 3)])
        self.assertEqual((ranking[0]["taxa"], ranking[0]["mediana_dias"]), (100, 15))
        self.assertEqual((ranking[1]["respondidos"], ranking[1]["taxa"], ranking[1]["mediana_dias"]), (1, 50, None))
        self.assertEqual(ranking[2]["taxa"], 0)  # retirado sai do denominador: 0 de 2

    def test_orgao_calculado_quando_falta_no_documento(self):
        d = item(ementa="Requer informações à NitTrans sobre vagas.")
        self.assertEqual(M.ranking_orgaos([d])[0]["orgao"], "NitTrans")

    def test_montar_documentos_preenche_orgao_so_nos_pedidos_de_informacao(self):
        registros = [
            doc(1, "requerimento", "1/2026", "2026-01-02", "Requer informações à NitTrans sobre vagas.", [{"id": 1, "nome": "ANA"}]),
            doc(2, "requerimento", "2/2026", "2026-01-03", "Requer a realização de Sessão Solene.", [{"id": 1, "nome": "ANA"}]),
            doc(3, "indicacao", "3/2026", "2026-01-04", "Indica poda na Rua X, Icaraí.", [{"id": 1, "nome": "ANA"}]),
        ]
        orgaos = {d["id"]: d["orgao"] for d in M.montar_documentos(registros, CFG, {}, CFG["legislaturas"])}
        self.assertEqual(orgaos, {1: "NitTrans", 2: None, 3: None})


# ---------------------------------------------------------------------- bairros
class TestBairros(unittest.TestCase):
    DOCS = [indicacao(b) for b in ("Icaraí", "Icaraí", "Icaraí", "Fonseca", "Fonseca", "Centro", "Centro", "Barreto",
                                   "Itaipu", "Jurujuba", None, None)] + [item(bairro="Centro")]  # requerimento não conta

    def test_por_vereador(self):
        r = M.resumo_bairros(self.DOCS)
        self.assertEqual({k: r[k] for k in ("indicacoes", "com_bairro", "sem_bairro", "pct_sem_bairro", "distintos", "concentracao")},
                         {"indicacoes": 12, "com_bairro": 10, "sem_bairro": 2, "pct_sem_bairro": 17, "distintos": 6, "concentracao": 30})
        self.assertEqual(r["top"], [("Icaraí", 3), ("Centro", 2), ("Fonseca", 2), ("Barreto", 1), ("Itaipu", 1)])
        self.assertEqual(r["mais_citados"], ["Icaraí"])
        self.assertEqual(P.mais_citado_txt(r), "Icaraí (30%)")
        vazio = M.resumo_bairros([indicacao(None)])
        self.assertEqual((vazio["top"], vazio["mais_citados"], vazio["concentracao"], vazio["pct_sem_bairro"]),
                         ([], [], None, 100))
        self.assertEqual(P.mais_citado_txt(vazio), "—")
        self.assertIsNone(M.resumo_bairros([])["pct_sem_bairro"])

    def test_empate_no_mais_citado(self):
        r = M.resumo_bairros([indicacao(b) for b in ("Icaraí", "Icaraí", "Centro", "Centro", "Fonseca")])
        self.assertEqual((r["mais_citados"], r["concentracao"]), (["Centro", "Icaraí"], 40))
        self.assertEqual(P.mais_citado_txt(r), "empate: Centro, Icaraí (40% cada)")
        muitos = M.resumo_bairros([indicacao(b) for b in ("Badu", "Barreto", "Cafubá", "Centro", "Fonseca")])
        self.assertEqual(P.mais_citado_txt(muitos), "empate: Badu, Barreto, Cafubá e mais 2 (20% cada)")

    def test_os_52_bairros_com_zeros(self):
        por_bairro = M.indicacoes_por_bairro(self.DOCS)
        self.assertEqual([b["bairro"] for b in por_bairro], list(RD.BAIRROS_NITEROI))
        self.assertEqual(len(por_bairro), 52)
        self.assertEqual(sum(b["indicacoes"] for b in por_bairro), 10)
        self.assertEqual(sum(1 for b in por_bairro if b["indicacoes"] == 0), 46)
        self.assertEqual(next(b for b in por_bairro if b["bairro"] == "Icaraí"), {"regiao": "Praias da Baía", "bairro": "Icaraí", "indicacoes": 3})

    def test_menos_citados_com_empates(self):
        lista = [{"bairro": "Badu", "indicacoes": 5}, {"bairro": "Cafubá", "indicacoes": 1}, {"bairro": "Barreto", "indicacoes": 1},
                 {"bairro": "Ingá", "indicacoes": 0}]
        self.assertEqual([b["bairro"] for b in M.menos_citados(lista, 2)], ["Ingá", "Barreto", "Cafubá"])
        self.assertEqual(len(M.menos_citados(lista, 10)), 4)


# ---------------------------------------------------------------------- páginas
class TestPaginasMetricas(unittest.TestCase):
    """DOCS_METRICAS: 2026 com coleta completa e 2025 parcial (só a moção de aplauso de Ana)."""
    NOTA_PARCIAIS = "Anos com coleta parcial (falta algum dos cinco tipos de documento), fora destas contas: 2025."

    @classmethod
    def setUpClass(cls):
        cls.modelo = montar(DOCS_METRICAS)

    # As asserções de linhas comparam conteúdo e ordem das células sem os papéis ARIA e data-label das tabelas
    # empilháveis, conferidos em tests/test_tabelas_empilhaveis.py.
    def test_ruido_com_homenagens(self):
        bruto = P.gerar_ruido(self.modelo)
        self.assertIn('<td role="cell" data-label="% da produção">25%</td>', bruto)
        html = sem_empilhamento(bruto)
        self.assertIn('<a href="#homenagens">Homenagens</a>', html)
        self.assertIn('id="homenagens"', html)
        self.assertIn("Homenagens por ano e tipo de documento", html)
        self.assertIn("Peso das homenagens na produção total da Câmara, por ano", html)
        self.assertIn("<caption>Homenagens por vereador, legislatura 2025-2028</caption>", html)
        # Ana em 2026 (2025 é parcial): título de cidadão entre 4 documentos, sem projeto de lei no ano
        self.assertIn('<tr><th scope="row"><a href="vereadores/ana-maria-teste.html">Ana Teste</a></th>'
                      "<td>1</td><td>4</td><td>0</td><td>25%</td></tr>", html)
        self.assertIn('<th scope="row">Diná</th>', html)  # sem página: sem link
        self.assertIn(self.NOTA_PARCIAIS, html)
        self.assertNotIn('<tr><th scope="row">2025</th>', html)
        sem_docs = P.gerar_ruido(montar(documentos=None))
        self.assertNotIn('id="homenagens"', sem_docs)
        sem_ano_completo = P.gerar_ruido(montar())  # DOCS: nenhum ano com os cinco tipos
        self.assertIn('id="homenagens"', sem_ano_completo)
        self.assertIn("Sem dados: nenhum ano tem os cinco tipos de documento coletados", sem_ano_completo)

    def test_atividades_com_resumos(self):
        bruto = P.gerar_atividades(self.modelo, {"build_doc": "x", "arquivos": {"doc-mocao-2026": {"familia": "doc", "ano": 2026}}})
        self.assertIn('<td role="cell" data-label="Mais citado (concentração)" class="txt">Icaraí (100%)</td>', bruto)
        html = sem_empilhamento(bruto)
        self.assertIn('<a href="#pedidos-informacao">Requerimentos de informação</a>', html)
        self.assertIn('id="bairros"', html)
        self.assertIn("<caption>Requerimentos de informação por vereador, legislatura 2025-2028</caption>", html)
        self.assertIn('<th scope="col">Base da mediana (respondidos com data)</th>', html)
        # Michel: um respondido em 30 dias (com data) e um aguardando, ainda sem detalhe
        self.assertIn('<tr><th scope="row"><a href="vereadores/michel-salim-saad-neto.html">Michel Saad</a></th>'
                      "<td>2</td><td>1</td><td>50%</td><td>30</td><td>1</td><td>1</td><td>0</td><td>0</td></tr>", html)
        self.assertIn("Requerimentos de informação por órgão citado", html)
        self.assertIn('<tr><th scope="row">NitTrans</th><td>1</td><td>0</td><td>0%</td><td>—</td><td>0</td><td>1</td>'
                      "<td>0</td><td>0</td></tr>", html)
        self.assertIn(f'<th scope="row">{RD.ORGAO_NAO_IDENTIFICADO}</th>', html)
        self.assertIn("<p class=tile-nota>mediana entre 1 respondido com data</p>", html)  # tile() não põe aspas na classe
        self.assertIn("1 requerimento de informação ainda está com o detalhe pendente.", html)
        self.assertIn("só existem para os respondidos cuja página de detalhe", html)
        self.assertIn("não é necessariamente o dia em que o Executivo respondeu", html)
        self.assertIn("assinados em conjunto (coautoria)", html)
        self.assertIn("vale o assunto da listagem do SISCAM", html)
        self.assertIn("Contar pedidos não mede a qualidade", html)
        self.assertIn("Indicações por bairro", html)
        self.assertIn("Menos citados:", html)
        self.assertIn("<caption>Bairros das indicações por vereador, legislatura 2025-2028</caption>", html)
        self.assertIn('<th scope="col" class="txt">Mais citado (concentração)</th>', html)
        self.assertIn('<td>1</td><td>1</td><td>1</td><td class="txt">Icaraí (100%)</td><td class="txt">Icaraí (1)</td>', html)
        self.assertIn('<div class="tabela-graf tabela-resumo" role="region" tabindex="0" '
                      'aria-label="Bairros das indicações por vereador, legislatura 2025-2028">', html)
        self.assertIn(">0%</p><p class=\"tile-rotulo\">sem bairro identificado", html)

    def test_pagina_do_vereador(self):
        bruto = P.gerar_vereador(self.modelo, self.modelo["pessoas"]["ana-maria-teste"])
        self.assertIn('<tr role="row"><th scope="row" role="rowheader" data-label="Legislatura">2025-2028</th>', bruto)
        html = sem_empilhamento(bruto)
        self.assertIn("<caption>Homenagens por legislatura</caption>", html)
        self.assertIn('<tr><th scope="row">2025-2028</th><td>1</td><td>4</td><td>0</td><td>25%</td></tr>', html)
        self.assertIn("<caption>Homenagens por ano</caption>", html)
        self.assertIn('<tr><th scope="row">2026</th><td>1</td><td>4</td><td>0</td><td>25%</td></tr>', html)
        # 2025 é parcial: fora da tabela de homenagens por ano (o gráfico de documentos por ano ainda o mostra).
        homenagens_ano = html.split("<caption>Homenagens por ano</caption>", 1)[1].split("</table>", 1)[0]
        self.assertNotIn('<th scope="row">2025</th>', homenagens_ano)
        self.assertIn(self.NOTA_PARCIAIS, html)
        self.assertIn("<caption>Requerimentos de informação por legislatura</caption>", html)
        self.assertIn('<tr><th scope="row">2025-2028</th><td>1</td><td>1</td><td>100%</td><td>30</td><td>1</td>'
                      "<td>0</td><td>0</td><td>0</td></tr>", html)
        self.assertIn("<caption>Órgãos mais citados nos requerimentos de informação</caption>", html)
        self.assertIn("<caption>Bairros das indicações por legislatura</caption>", html)
        michel = P.gerar_vereador(self.modelo, self.modelo["pessoas"]["michel-salim-saad-neto"])
        self.assertNotIn("Bairros das indicações por legislatura", michel)  # sem indicações

    def test_metodologia(self):
        html = P.gerar_metodologia(self.modelo)
        self.assertIn('id="metricas-documentos"', html)
        self.assertIn('<a href="ruido.html#homenagens">Sem efeito e polêmicas</a>', html)
        self.assertIn("aplauso e congratulação são uma única classe", html)
        self.assertIn("anos com coleta parcial ficam fora da conta", html)
        self.assertIn("Não há dado de população no site", html)
        self.assertIn("não necessariamente até o Executivo responder", html)
        self.assertIn("1 requerimento de informação ainda está com o detalhe pendente.", html)
        self.assertIn("Secretaria de Mobilidade Urbana", html)
        self.assertIn("citado em outro papel", html)
        sem_docs = P.gerar_metodologia(montar(documentos=None))
        self.assertNotIn('href="ruido.html#homenagens"', sem_docs)  # a seção só existe com documentos


if __name__ == "__main__":
    unittest.main()
