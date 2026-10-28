"""Temas: privacidade, neutralidade, contagens locais, cache e apresentação offline."""
from __future__ import annotations

import copy
import json
import os
import signal
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from coletor import arquivos, mascara, temas as T
from coletor.site import modelo as M
from coletor.site.temas_html import bloco_temas

LEG = "2025-2028"
ROTULOS = ["Transporte coletivo", "Educação municipal"]


def documento(i: int, tipo: str = "indicacao") -> dict:
    return {"id": i, "tipo": tipo, "numero": f"{i}/2025", "ano": 2025,
            "data": "2025-03-01", "legislatura": LEG, "ementa": f"Solicita serviço municipal {i}."}


def modelo(n: int = 4) -> dict:
    docs = [documento(i) for i in range(1, n + 1)]
    p = {"slug": "ana", "nome": "Ana", "nome_siscam": "ANA", "partido": "XYZ",
         "mandatos": {LEG: {"projetos_autor": [], "projetos_coautor": []}}}
    return {"pessoas": {"ana": p}, "legislaturas": [
        {"id": LEG, "inicio": "2025-01-01", "fim": "2028-12-31"}],
        "atividade": {"ana": {"documentos": docs}}}


def registro(rotulos=None, total=4):
    return {"rotulos": ROTULOS if rotulos is None else rotulos, "total_base": total,
            "versao": T.VERSAO_TEMAS, "modelo": T.MODELO}


def cache_completo(m):
    docs = T.documentos_da_pessoa(m, m["pessoas"]["ana"], LEG, ())
    cache = {f"pessoa:ana:{LEG}": registro(total=len(docs))}
    cache.update({"doc:" + T._hash(d["ementa"], ROTULOS): ROTULOS[d["id"] % 2] for d in docs})
    return docs, cache


def ia_falsa(docs, chave, sessao, liberados, rotulos=None):
    if rotulos is None:
        return {"rotulos": ["Transporte coletivo"]}
    return {"itens": [{"id": d["id"], "rotulo": rotulos[0]} for d in docs]}


class TestValidacaoTemas(unittest.TestCase):
    def test_rotulos_proibidos_e_quantidade_palavras(self):
        for r in ("Mais produtivo", "Pauta polêmica", "Acima da média", "Gestão conservadora",
                  "Esquerda municipal", "Pauta do PSOL", "Pauta do PT", "Pauta liberal",
                  "Um", "Um dois três quatro cinco", "<script> tema"):
            with self.subTest(rotulo=r), self.assertRaises(ValueError):
                T.validar_rotulos({"rotulos": [r]})
        for valor in (None, [], {"rotulos": "texto"}, {"rotulos": ["Tema municipal"] * 6},
                      {"rotulos": ["Tema municipal", "TEMA MUNICIPAL"]}):
            with self.assertRaises(ValueError):
                T.validar_rotulos(valor)
        self.assertEqual(T.validar_rotulos({"rotulos": ROTULOS}), ROTULOS)

    def test_ids_alheios_duplicados_ausentes_e_rotulos_desconhecidos(self):
        for itens in ([{"id": 99, "rotulo": ROTULOS[0]}],
                      [{"id": "1", "rotulo": ROTULOS[0]}],
                      [{"id": True, "rotulo": ROTULOS[0]}],
                      [{"id": 1, "rotulo": ROTULOS[0]}] * 2,
                      [{"id": 1, "rotulo": "inventado"}], []):
            with self.assertRaises(ValueError):
                T.validar_classificacoes({"itens": itens}, [documento(1)], ROTULOS)
        self.assertEqual(T.validar_classificacoes({"itens": [{"id": 1, "rotulo": "outros"}]},
                                                 [documento(1)], ROTULOS), {1: "outros"})

    def test_contagem_local_exemplos_recentes_e_tema_unitario(self):
        m = modelo(5)
        docs, cache = cache_completo(m)
        reg = cache[f"pessoa:ana:{LEG}"]
        reg.update(total=999, exemplos=[999], validado=True)
        temas, erros = T.temas_validados(docs, reg, cache)
        self.assertFalse(erros)
        self.assertEqual([(t["total"], [d["id"] for d in t["exemplos"]]) for t in temas],
                         [(2, [4, 2]), (3, [5, 3])])
        docs = docs[:2]
        temas, erros = T.temas_validados(docs, reg, cache)
        self.assertEqual(temas, [])
        self.assertIn("menos de 2 documentos", erros[0])
        del cache["doc:" + T._hash(docs[0]["ementa"], ROTULOS)]
        self.assertEqual(T.temas_validados(docs, reg, cache)[0], [])

    def test_outros_nao_entra_na_contagem_e_exemplos_alheios_sao_ignorados(self):
        m = modelo(5)
        docs, cache = cache_completo(m)
        reg = cache[f"pessoa:ana:{LEG}"]
        reg["exemplos"] = [9999]
        cache["doc:" + T._hash(docs[0]["ementa"], ROTULOS)] = "outros"
        temas, erros = T.temas_validados(docs, reg, cache)
        self.assertFalse(erros)
        self.assertEqual([t["total"] for t in temas], [2, 2])
        self.assertNotIn(9999, [d["id"] for t in temas for d in t["exemplos"]])

    def test_resposta_invalida_descartada_com_motivo_sem_dados_brutos(self):
        for retorno in ({}, {"rotulos": ["Gestão produtiva"]}, {"rotulos": ["Pauta socialista"]}):
            m, cache = modelo(), {}
            with mock.patch.dict(os.environ, {"OPENCODE_API_KEY": "falsa"}), \
                    mock.patch.object(T, "chamar_ia", return_value=retorno):
                T.agrupar(m, cache)
            self.assertTrue(cache[f"pessoa:ana:{LEG}"]["motivos"])
            self.assertFalse(any(k.startswith("doc:") for k in cache))
            self.assertNotIn("produtiva", json.dumps(cache))

    def test_json_invalido_no_transporte(self):
        from tests.test_ia import resposta
        m, cache = modelo(), {}
        with mock.patch.dict(os.environ, {"OPENCODE_API_KEY": "falsa"}), \
                mock.patch("urllib.request.urlopen", side_effect=lambda *a, **k: resposta("não é JSON")), \
                mock.patch("coletor.ia.time.sleep"):
            T.agrupar(m, cache)
        self.assertIn("motivos", cache[f"pessoa:ana:{LEG}"])

    def test_id_alheio_na_execucao_nao_entra_no_cache(self):
        def alheio(docs, chave, sessao, liberados, rotulos=None):
            return ia_falsa(docs, chave, sessao, liberados) if rotulos is None else {
                "itens": [{"id": 9999, "rotulo": rotulos[0]}]}
        cache = {}
        with mock.patch.dict(os.environ, {"OPENCODE_API_KEY": "falsa"}), \
                mock.patch.object(T, "chamar_ia", side_effect=alheio):
            T.agrupar(modelo(), cache)
        self.assertFalse(any(k.startswith("doc:") for k in cache))
        self.assertTrue(cache[f"pessoa:ana:{LEG}"]["motivos"])


class TestFontePrompt(unittest.TestCase):
    def test_autoria_pl_principal_documentos_e_mascara(self):
        m = modelo()
        p = m["pessoas"]["ana"]
        p["mandatos"][LEG]["projetos_autor"] = [documento(10, "pl")]
        p["mandatos"][LEG]["projetos_coautor"] = [documento(11, "pl")]
        m["atividade"]["ana"]["documentos"][0]["ementa"] = "Contato maria@example.com; telefone (21) 98765-4321."
        antes = copy.deepcopy(m)
        docs = T.documentos_da_pessoa(m, p, LEG, ())
        self.assertEqual({d["id"] for d in docs}, {1, 2, 3, 4, 10})
        d = next(d for d in docs if d["id"] == 1)
        self.assertEqual(d["ementa"], mascara.mascarar(antes["atividade"]["ana"]["documentos"][0]["ementa"], ())[0])
        self.assertNotIn("maria@example.com", d["ementa"])
        self.assertEqual(m, antes)

    def test_amostra_40_por_tipo_deterministica(self):
        docs = [documento(i, tipo) for tipo in ("pl", "indicacao", "mocao") for i in range(1, 46)]
        amostra = T.amostra_documentos(docs)
        self.assertEqual(amostra, T.amostra_documentos(list(reversed(docs))))
        self.assertEqual(len(amostra), 120)
        for tipo in ("pl", "indicacao", "mocao"):
            self.assertEqual([d["id"] for d in amostra if d["tipo"] == tipo], list(range(45, 5, -1)))

    def test_prompt_mesmo_sem_nome_partido_e_fronteira_mascarada(self):
        doc = dict(documento(1), nome="NOME_SECRETO", partido="SIGLA_SECRETA", ementa="Email maria@example.com")
        esperado = mascara.mascarar(doc["ementa"], ())[0]
        a = T.mensagens([doc], ())
        b = T.mensagens([dict(doc, nome="OUTRA_PESSOA", partido="OUTRA_SIGLA")], ())
        self.assertEqual(a, b)
        self.assertEqual(a[0]["content"], T.PROMPT_ROTULOS)
        self.assertEqual(json.loads(a[1]["content"])["documentos"][0]["ementa"], esperado)
        for termo in ("NOME_SECRETO", "SIGLA_SECRETA", "maria@example.com"):
            self.assertNotIn(termo, json.dumps(a))
        self.assertEqual(T.mensagens([doc], (), ROTULOS)[0]["content"], T.PROMPT_CLASSIFICAR)


class TestCacheExecucao(unittest.TestCase):
    def rodar(self, m, cache, **kwargs):
        with mock.patch.dict(os.environ, {"OPENCODE_API_KEY": "falsa"}), \
                mock.patch.object(T, "chamar_ia", side_effect=ia_falsa) as chamar:
            estat = T.agrupar(m, cache, **kwargs)
        return estat, chamar

    def test_cache_estavel_documentos_novos_e_limiar_10_porcento(self):
        m, cache = modelo(20), {}
        self.rodar(m, cache)
        antes = arquivos.texto_mapa(cache)
        _, chamar = self.rodar(m, cache)
        chamar.assert_not_called()
        self.assertEqual(arquivos.texto_mapa(cache), antes)
        m["atividade"]["ana"]["documentos"].append(documento(21))
        _, chamar = self.rodar(m, cache)
        self.assertEqual(chamar.call_count, 1)
        self.assertEqual([d["id"] for d in chamar.call_args.args[0]], [21])
        m["atividade"]["ana"]["documentos"].append(documento(22))
        _, chamar = self.rodar(m, cache)
        self.assertEqual(chamar.call_count, 2)  # rótulos + documento novo; antigos reutilizados
        self.assertEqual(chamar.call_args_list[0].args[-1], ())
        self.assertEqual(cache[f"pessoa:ana:{LEG}"]["total_base"], 22)

    def test_encerrada_estavel_e_hash_sensivel(self):
        reg = registro(total=20)
        self.assertFalse(T.recalcular_rotulos(reg, 200, True))
        self.assertFalse(T.recalcular_rotulos(reg, 21, False))
        self.assertTrue(T.recalcular_rotulos(reg, 22, False))
        h = T._hash("ementa", ROTULOS)
        self.assertNotEqual(h, T._hash("outra", ROTULOS))
        self.assertNotEqual(h, T._hash("ementa", ["Tema municipal"]))
        with mock.patch.object(T, "VERSAO_TEMAS", "nova"):
            self.assertNotEqual(h, T._hash("ementa", ROTULOS))
        with mock.patch.object(T, "MODELO", "outro"):
            self.assertNotEqual(h, T._hash("ementa", ROTULOS))

    def test_lotes_30_limite_e_retomada(self):
        m, cache = modelo(65), {}
        estat, chamar = self.rodar(m, cache, limite=32)
        self.assertEqual(estat["documentos_novos"], 32)
        self.assertEqual([len(c.args[0]) for c in chamar.call_args_list], [40, 30, 2])
        estat, chamar = self.rodar(m, cache)
        self.assertEqual(estat["documentos_novos"], 33)
        self.assertEqual([len(c.args[0]) for c in chamar.call_args_list], [30, 3])

    def test_prazo_e_interrupcao_preservam_apos_primeiro_lote(self):
        for modo in ("prazo", "sinal", "teclado"):
            cache, salvos = {}, []
            chamadas = 0

            def salvar(c):
                salvos.append(copy.deepcopy(c))

            def chamar(*args):
                nonlocal chamadas
                chamadas += 1
                if modo == "teclado" and chamadas == 3:
                    raise KeyboardInterrupt
                return ia_falsa(*args)

            with mock.patch.dict(os.environ, {"OPENCODE_API_KEY": "falsa"}), \
                    mock.patch.object(T, "chamar_ia", side_effect=chamar):
                estat = T.agrupar(modelo(65), cache, salvar=salvar,
                                  max_minutos=1 if modo == "prazo" else None,
                                  relogio=lambda: 61 if chamadas >= 2 else 0,
                                  parar=(lambda: chamadas >= 2) if modo == "sinal" else None)
            self.assertTrue(estat["interrompido"])
            self.assertEqual(sum(k.startswith("doc:") for k in salvos[-1]), 30)

    def test_sem_ia_e_sem_chave_nao_chamam_nem_gravam(self):
        for usar, chave in ((False, "falsa"), (True, "")):
            with mock.patch.dict(os.environ, {"OPENCODE_API_KEY": chave}), \
                    mock.patch.object(T, "chamar_ia", side_effect=AssertionError("rede")), \
                    mock.patch("urllib.request.urlopen", side_effect=AssertionError("rede")):
                salvar = mock.Mock()
                cache = {"preservar": "valor"}
                estat = T.agrupar(modelo(), cache, usar_ia=usar, salvar=salvar)
            self.assertTrue(estat["ia_desligada"])
            self.assertEqual(cache, {"preservar": "valor"})
            salvar.assert_not_called()

    def test_amostra_filtra_pessoas(self):
        _, chamar = self.rodar(modelo(), {}, amostra={"outra-pessoa"})
        chamar.assert_not_called()

    def test_limite_conta_respostas_descartadas_tambem(self):
        m = modelo()
        m["pessoas"]["bia"] = dict(m["pessoas"]["ana"], slug="bia")
        m["atividade"]["bia"] = {"documentos": [documento(10), documento(11)]}

        def invalida(docs, chave, sessao, liberados, rotulos=None):
            return ia_falsa(docs, chave, sessao, liberados) if rotulos is None else {}

        with mock.patch.dict(os.environ, {"OPENCODE_API_KEY": "falsa"}), \
                mock.patch.object(T, "chamar_ia", side_effect=invalida) as chamar:
            estat = T.agrupar(m, {}, limite=2)
        self.assertEqual(estat["documentos_novos"], 0)
        self.assertEqual(estat["documentos_enviados"], 2)
        self.assertEqual(chamar.call_count, 2)  # amostra e lote da primeira pessoa

    def test_cli_sigterm_grava_e_restaura_handler(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(T, "CACHE_IA", Path(tmp) / "temas.json"), \
                mock.patch.object(T, "montar_modelo", return_value=modelo(65)), \
                mock.patch.dict(os.environ, {"OPENCODE_API_KEY": "falsa"}):
            anterior = signal.getsignal(signal.SIGTERM)

            def chamar(docs, chave, sessao, liberados, rotulos=None):
                retorno = ia_falsa(docs, chave, sessao, liberados, rotulos)
                if rotulos is not None:
                    signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
                return retorno

            with mock.patch.object(T, "chamar_ia", side_effect=chamar):
                T.main([])
            cache = T.carregar_cache(T.CACHE_IA)
            self.assertEqual(sum(k.startswith("doc:") for k in cache), 30)
            self.assertEqual(signal.getsignal(signal.SIGTERM), anterior)
            self.assertEqual(T.CACHE_IA.read_text(encoding="utf-8"), arquivos.texto_mapa(cache))

    def test_cli_sem_ia_offline_e_cache_ausente(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(T, "CACHE_IA", Path(tmp) / "temas.json"), \
                mock.patch.object(T, "montar_modelo", return_value=modelo()), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("rede")), \
                mock.patch.object(T, "salvar_mapa", side_effect=AssertionError("gravação")):
            T.main(["--sem-ia"])
            self.assertFalse(T.CACHE_IA.exists())


class TestHtmlTemas(unittest.TestCase):
    def test_renderiza_so_validado_com_frase_fixa_e_links_locais(self):
        m = modelo()
        docs, cache = cache_completo(m)
        p = m["pessoas"]["ana"]
        html = bloco_temas(m, p, cache)
        self.assertIn("Temas (agrupados por IA)", html)
        self.assertIn("Transporte coletivo: 2 documentos (ex.: ", html)
        self.assertIn("metodologia.html#temas", html)
        self.assertNotIn("Resumo em números", html)
        self.assertIn('class="tag">IA</span>', html)
        self.assertIn(M.URL_DETALHE.format(id=4), html)
        self.assertEqual(bloco_temas(m, p, {}), "")
        cache[f"pessoa:ana:{LEG}"].update(rotulos=["Gestão produtiva"], validado=True)
        self.assertEqual(bloco_temas(m, p, cache), "")
        cache[f"pessoa:ana:{LEG}"] = "corrompido"
        self.assertEqual(bloco_temas(m, p, cache), "")

    def test_escape_numero_e_prefixo(self):
        m = modelo()
        m["atividade"]["ana"]["documentos"][0]["numero"] = '<img src=x>'
        _, cache = cache_completo(m)
        html = bloco_temas(m, m["pessoas"]["ana"], cache, '"/raiz/')
        self.assertIn("&lt;img src=x&gt;", html)
        self.assertIn('href="&quot;/raiz/metodologia.html#temas"', html)
        self.assertNotIn("<img", html)

    def test_neutralidade_todas_as_pessoas_da_base_sem_ia_cache_vazio(self):
        # Percorre eleitos e suplentes reconhecidos pelo mesmo modelo usado nas fichas.
        m = M.montar_modelo()
        self.assertTrue(m["pessoas"])
        cache = {}
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("rede")), \
                mock.patch.object(T, "chamar_ia", side_effect=AssertionError("IA")):
            T.agrupar(m, cache, usar_ia=False)
            for p in m["pessoas"].values():
                with self.subTest(pessoa=p["slug"]):
                    self.assertEqual(bloco_temas(m, p, cache), "")
        self.assertEqual(cache, {})
