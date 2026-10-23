"""Contrato offline dos votos nominais em colunas, sem ler data/ nem acessar a rede."""
from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from coletor import gerar_site as GS
from coletor import regras_sessoes as R
from coletor.site import pagina_sessoes as S
from coletor.site import paginas as P
from coletor.site.modelo import URL_DETALHE


def votacao(id_: str, data: str, votos: dict[str, str], **campos) -> dict:
    totais = {c: sum(v == voto for v in votos.values()) for voto, c in R.CHAVES_TOTAIS.items()
              if c in GS.modelo_sessoes.CAMPOS_TOTAIS}
    return {"id": id_, "sessao": int(id_.split("-")[0]), "data": data,
            "titulo_sessao": "Sessão Ordinária de " + data[:4], "materia": "pl", "id_documento": 100,
            "documento": "Projeto de Lei Nº 00001/" + data[:4], "numero": "1/" + data[:4],
            "ementa": "Dispõe sobre <serviços> & fiscalização.", "resultado": "Aprovado",
            "url_documento": URL_DETALHE.format(id=100), "totais": totais, "totais_oficiais": None,
            "classe": R.classe_votacao(totais), "sentido": "favor_aprova", "maioria": R.maioria(totais),
            "quorum": None, "qualidade": "ok", "fonte_sentido": "resultado_oficial", "notas": [],
            "votos": votos, **campos}


def modelo_sintetico() -> dict:
    antigo = votacao("1-100", "2025-12-01", {"ana": "Favor", "so-em-2025": "Ausente"})
    incerto = votacao("20-501", "2026-02-01", {"ana": "Contra", "helio": "indeterminado"},
                     id_documento=None, url_documento=None, sentido="indeterminado", qualidade="indeterminado")
    incerto["totais_oficiais"] = {**incerto["totais"], "presidente": 0}
    veto = votacao("21-502", "2026-03-02", {
        "ana": "Favor", "bruno": "Contra", "caio": "Abstenção", "dora": "Ausente", "eva": "Presidente",
        "fabio": "Branco", "gabi": "Nulo", "suplente": "Favor",
    }, materia="veto", documento="Projeto de Lei Nº 00280/2025", numero="280/2025", resultado="Veto Mantido",
        sentido="favor_mantem", quorum={"exigido": 11, "derrubar": 1, "manter": 2}, fonte_sentido="texto_veto_ambiguo",
        notas=["o SISCAM registra estes votos como 'Favor'; a tramitação os descreve como votos contrários ao parecer",
               "conferência textual favor=3 ≠ nominal 2; a tramitação pode misturar votações"])
    veto["totais_oficiais"] = {**veto["totais"], "ausentes": 2, "presidente": 1}
    return {
        "pessoas": {s: {"nome": nome} for s, nome in (("ana", "Ana Maria Teste"), ("bruno", "Bruno Teste"),
                     ("caio", "Caio Teste"), ("dora", "Dora Teste"), ("eva", "Eva Teste"), ("fabio", "Fabio Teste"),
                     ("gabi", "Gabi Teste"), ("nao-votou", "Não Votou"))},
        "sessoes": {"anos": [2025, 2026], "sessoes": [], "votacoes": [antigo, veto, incerto],
                    "legislaturas": [{"id": "2025-2028", "anos": [2025, 2026]}],
                    "por_pessoa": {"suplente": {"2025-2028": {"nome": "Nome Suplente Completo",
                                      "sem_pagina": True, "condicao": "suplente em exercício"}}}},
    }


def manifesto_vazio() -> dict:
    return {"esquema": 2, "build": "pl00000000", "arquivos": {
        "dic-pl": {"url": "dados/dic-pl.json?v=pl", "n": 1, "bytes": 1},
    }}


def manifesto_embutido(html: str) -> dict:
    return json.loads(html.split('<script type="application/json" id="manifesto-dados">', 1)[1].split("</script>", 1)[0])


class TestExportarSessoes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.saida = Path(self.tmp.name)
        self.modelo = modelo_sintetico()
        self.manifesto = GS.exportar_sessoes(self.modelo, self.saida, manifesto_vazio())

    def ler(self, nome: str) -> dict:
        return json.loads((self.saida / f"dados/{nome}.json").read_bytes())

    def test_dicionario_forma_e_constantes(self):
        dic = self.ler("dic-ses")
        self.assertEqual(set(dic), {"esquema", "votos", "materias", "classes", "sentidos", "rotulos", "qualidade",
                                    "url_detalhe", "minimo_dividida", "quorum_veto"})
        self.assertEqual(dic["esquema"], 1)
        self.assertEqual(dic["votos"], [["F", "Favor"], ["C", "Contra"], ["S", "Abstenção"], ["X", "Ausente"],
                                       ["R", "Presidente"], ["B", "Branco"], ["N", "Nulo"],
                                       ["I", "indeterminado"], [".", "não consta"]])
        self.assertEqual({m for m, _, _ in dic["materias"]}, {"veto", "pl", "pdl", "resolucao", "outra"})
        self.assertTrue(all(len(m) == 3 for m in dic["materias"]))
        self.assertEqual(dic["classes"], [["unanime", "Unânime"], ["dissenso", "Com 1 ou 2 votos diferentes"],
                                         ["dividida", "Dividida"]])
        self.assertEqual(dic["qualidade"], ["ok", "inconsistente", "indeterminado"])
        self.assertEqual(dic["url_detalhe"] + "123", URL_DETALHE.format(id=123))
        self.assertEqual(dic["minimo_dividida"], 3)
        self.assertEqual(dic["quorum_veto"], 11)

    def test_rotulos_identicos_as_regras_por_materia_e_sentido(self):
        dic = self.ler("dic-ses")
        for sentido, favor, contra in dic["sentidos"]:
            self.assertEqual([favor, contra], [R.rotulo_voto(v, sentido, "outra") for v in ("Favor", "Contra")])
        for materia, _, _ in dic["materias"]:
            for sentido, _, _ in dic["sentidos"]:
                with self.subTest(materia=materia, sentido=sentido):
                    esperado = [R.rotulo_voto(v, sentido, materia) for _, v in dic["votos"][:7]]
                    self.assertEqual(dic["rotulos"][materia][sentido], esperado)

    def test_forma_das_colunas_e_ordem(self):
        dados = self.ler("vot-2026")
        self.assertEqual(set(dados), {"esquema", "ano", "n", "pessoas", "colunas"})
        self.assertEqual((dados["esquema"], dados["ano"], dados["n"]), (1, 2026, 2))
        c = dados["colunas"]
        self.assertEqual(set(c), {"id", "s", "d", "ts", "m", "doc", "n", "e", "r", "t", "to", "cl", "sx", "mj", "q", "ql", "nt", "v"})
        self.assertTrue(all(len(coluna) == dados["n"] for coluna in c.values()))
        self.assertEqual(c["id"], ["21-502", "20-501"])
        self.assertEqual(c["s"], [21, 20])
        self.assertEqual(c["d"], ["2026-03-02", "2026-02-01"])
        self.assertEqual(c["ts"], ["Sessão Ordinária de 2026"] * 2)
        self.assertEqual(c["m"], ["veto", "pl"])
        self.assertEqual(c["doc"], [100, None])
        self.assertEqual(c["n"], ["PL 280/2025", "PL 1/2026"])
        self.assertEqual(c["e"], ["Dispõe sobre <serviços> & fiscalização."] * 2)
        self.assertEqual(c["r"], ["Veto Mantido", "Aprovado"])
        self.assertEqual(c["t"], [[2, 1, 1, 1, 1, 1], [0, 1, 0, 0, 0, 0]])
        self.assertEqual(c["to"], [[2, 1, 1, 2, 1, 1], None])
        self.assertEqual(c["cl"], ["dissenso", "unanime"])
        self.assertEqual(c["sx"], ["favor_mantem", "indeterminado"])
        self.assertEqual(c["mj"], ["F", "C"])
        self.assertEqual(c["q"], [[11, 1, 2], None])
        self.assertEqual(c["ql"], ["ok", "indeterminado"])

    def test_votos_alinhados_so_com_pessoas_do_ano(self):
        dic = dict(self.ler("dic-ses")["votos"])
        originais = {v["id"]: v for v in self.modelo["sessoes"]["votacoes"]}
        for ano in (2025, 2026):
            dados = self.ler(f"vot-{ano}")
            pessoas = [s for s, _, _, _ in dados["pessoas"]]
            self.assertEqual(pessoas, sorted(pessoas))
            esperadas = {s for v in originais.values() if v["data"].startswith(str(ano)) for s in v["votos"]}
            self.assertEqual(set(pessoas), esperadas)
            for id_, votos in zip(dados["colunas"]["id"], dados["colunas"]["v"], strict=True):
                self.assertEqual(len(votos), len(pessoas))
                for s, codigo in zip(pessoas, votos, strict=True):
                    self.assertEqual(dic[codigo], originais[id_]["votos"].get(s, "não consta"))
        pessoas = {s: [nome, pagina, condicao] for s, nome, pagina, condicao in self.ler("vot-2026")["pessoas"]}
        self.assertEqual(pessoas["ana"], ["Ana Teste", 1, ""])
        self.assertEqual(pessoas["suplente"], ["Nome Completo", 0, "suplente em exercício"])
        self.assertEqual(pessoas["helio"], ["Helio", 0, ""])
        self.assertNotIn("nao-votou", pessoas)
        self.assertNotIn("so-em-2025", pessoas)
        self.assertIn("I", self.ler("vot-2026")["colunas"]["v"][1])
        self.assertIn(".", self.ler("vot-2026")["colunas"]["v"][1])

    def test_maioria_nula_no_empate_e_ordenacao_estavel_no_mesmo_dia(self):
        votos = [votacao(id_, "2026-03-02", {"ana": "Favor", "bruno": "Contra"}) for id_ in ("21-2", "21-1")]
        dados = GS.fatia_votacoes(self.modelo, 2026, votos)
        self.assertEqual(dados["colunas"]["mj"], [None, None])
        self.assertEqual(dados["colunas"]["id"], ["21-2", "21-1"])
        self.assertEqual(dados, GS.fatia_votacoes(self.modelo, 2026, votos[::-1]))

    def test_referencias_curtas_e_totais_oficiais_parciais(self):
        for materia, documento, esperado in (
            ("pdl", "Projeto de Decreto Legislativo Nº 00003/2026", "PDL 3/2026"),
            ("resolucao", "Projeto de Resolução Nº 00003/2026", "PR 3/2026"),
            ("outra", "Substitutivo Nº 00003/2026", "Substitutivo 3/2026"),
        ):
            with self.subTest(materia=materia):
                self.assertEqual(GS.numero_votacao({"materia": materia, "documento": documento}), esperado)
        self.assertEqual(GS.numero_votacao({}), "Documento não identificado")
        v = votacao("1-100", "2026-01-01", {"ana": "Favor"}, totais_oficiais={"favor": 99})
        self.assertEqual(GS.fatia_votacoes(self.modelo, 2026, [v])["colunas"]["to"], [[99, 0, 0, 0, 0, 0]])

    def test_notas_visiveis_sem_conferencias_tecnicas(self):
        veto = self.modelo["sessoes"]["votacoes"][1]
        notas = self.ler("vot-2026")["colunas"]["nt"][0]
        self.assertEqual(notas, ["Derrubar o veto exige 11 votos (maioria absoluta dos 21 vereadores); houve 1.",
                                "Sentido definido pelo texto do parecer na tramitação.", veto["notas"][0]])
        self.assertEqual(self.ler("vot-2026")["colunas"]["nt"][1],
                         ["Favor ao parecer / Contra o parecer: sentido não determinado."])
        inconsistente = {**veto, "qualidade": "inconsistente", "sentido": "inconsistente", "quorum": None}
        notas_inconsistentes = GS.notas_votacao(inconsistente)
        self.assertIn("Placar inconsistente: exibimos apenas os totais oficiais, sem atribuir votos a nomes.", notas_inconsistentes)
        for registro in (veto, inconsistente):
            html = S._cartao(self.modelo, registro)
            for nota in GS.notas_votacao(registro):
                self.assertIn(P.esc(nota), html)
            self.assertNotIn(veto["notas"][1], GS.notas_votacao(registro))

    def test_manifesto_sem_build_nas_entradas_hash_do_conteudo_e_json_compacto(self):
        self.assertEqual(self.manifesto["build"], "pl00000000")
        self.assertEqual(self.manifesto["arquivos"]["dic-pl"], manifesto_vazio()["arquivos"]["dic-pl"])
        self.assertRegex(self.manifesto["build_ses"], r"^[0-9a-f]{10}$")
        for nome in ("dic-ses", "vot-2025", "vot-2026"):
            entrada = self.manifesto["arquivos"][nome]
            conteudo = (self.saida / f"dados/{nome}.json").read_bytes()
            dados = json.loads(conteudo)
            self.assertNotIn("build", dados)
            self.assertNotIn("build", entrada)
            self.assertEqual(conteudo, json.dumps(dados, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            self.assertEqual(entrada["url"], f"dados/{nome}.json?v={hashlib.sha1(conteudo).hexdigest()[:10]}")
            self.assertEqual(entrada["bytes"], len(conteudo))
            self.assertEqual(entrada["familia"], "dic-ses" if nome == "dic-ses" else "vot")
            if nome != "dic-ses":
                self.assertEqual((entrada["ano"], entrada["n"]), (dados["ano"], dados["n"]))
        self.assertEqual(self.ler("manifest"), self.manifesto)

    def test_determinismo_sem_mutacao_mesma_entrada_mesmos_bytes_e_urls(self):
        antes = copy.deepcopy(self.modelo)
        outra = self.saida / "outra"
        with mock.patch("coletor.siscam.baixar", side_effect=AssertionError("rede proibida")):
            manifesto = GS.exportar_sessoes(self.modelo, outra, manifesto_vazio())
        self.assertEqual(self.modelo, antes)
        self.assertEqual(manifesto, self.manifesto)
        for arquivo in (self.saida / "dados").glob("*.json"):
            self.assertEqual(arquivo.read_bytes(), (outra / "dados" / arquivo.name).read_bytes())
        invertido = copy.deepcopy(self.modelo)
        invertido["sessoes"]["votacoes"].reverse()
        for v in invertido["sessoes"]["votacoes"]:
            v["votos"] = dict(reversed(list(v["votos"].items())))
        self.assertEqual(GS.exportar_sessoes(invertido, outra, manifesto_vazio()), self.manifesto)

    def test_mudar_um_ano_nao_muda_url_dos_outros_nem_dicionario(self):
        alterado = copy.deepcopy(self.modelo)
        alterado["sessoes"]["votacoes"][1]["ementa"] = "Outra ementa de 2026."
        outro = GS.exportar_sessoes(alterado, self.saida / "mudou", manifesto_vazio())
        for nome in ("dic-ses", "vot-2025"):
            self.assertEqual(outro["arquivos"][nome], self.manifesto["arquivos"][nome])
            self.assertEqual((self.saida / f"dados/{nome}.json").read_bytes(),
                             (self.saida / f"mudou/dados/{nome}.json").read_bytes())
        self.assertNotEqual(outro["arquivos"]["vot-2026"]["url"], self.manifesto["arquivos"]["vot-2026"]["url"])
        self.assertNotEqual(outro["build_ses"], self.manifesto["build_ses"])

    def test_manifesto_da_pagina_so_com_familias_de_sessoes_e_preload_do_dicionario(self):
        html = P.pagina("Sessões", "", "sessoes.html", manifesto=self.manifesto)
        embutido = manifesto_embutido(html)
        self.assertEqual(set(embutido), {"esquema", "build", "build_ses", "inicial", "arquivos"})
        self.assertEqual(set(embutido["arquivos"]), {"dic-ses", "vot-2025", "vot-2026"})
        self.assertEqual(embutido["inicial"], ["dic-ses", "vot-2026"])
        self.assertEqual(embutido["build_ses"], self.manifesto["build_ses"])
        self.assertIn('as="fetch" crossorigin href="' + self.manifesto["arquivos"]["dic-ses"]["url"] + '"', html)
        self.assertNotIn('as="fetch" crossorigin href="dados/vot-', html)
        pl = manifesto_embutido(P.cabecalho_dados(self.manifesto, "projetos.html", ""))
        self.assertNotIn("dic-ses", pl["arquivos"])
        self.assertFalse(any(n.startswith("vot-") for n in pl["arquivos"]))
        self.manifesto.update(build_doc="doc0000000")
        self.manifesto["arquivos"].update({"dic-doc": {"familia": "dic-doc", "url": "dados/dic-doc.json?v=x"},
            "doc-pdl-2026": {"familia": "doc", "ano": 2026, "tipo": "pdl", "n": 1, "url": "dados/doc-pdl-2026.json?v=x"}})
        docs = manifesto_embutido(P.cabecalho_dados(self.manifesto, "atividades.html", ""))
        self.assertEqual(set(docs["arquivos"]), {"dic-doc", "doc-pdl-2026"})
        # Mesmas chaves obrigatórias de validarManifesto (app.js), inclusive nas famílias sem build.
        for pagina, manifesto in (("sessoes", embutido), ("projetos", pl), ("atividades", docs)):
            with self.subTest(pagina=pagina):
                self.assertTrue({"esquema", "build", "arquivos"} <= set(manifesto))
                self.assertEqual(manifesto["esquema"], 2)
                self.assertIsInstance(manifesto["build"], str)
                self.assertEqual(manifesto["build"], self.manifesto["build"])

    def test_cabecalho_compartilhado_com_vm_igual_ao_gerado(self):
        pasta = Path(__file__).resolve().parent / "js" / "fixtures"
        html = (pasta / "cabecalho_sessoes.html").read_text(encoding="utf-8").strip()
        self.assertEqual(P.cabecalho_dados(manifesto_embutido(html), "sessoes.html", ""), html)

    def test_main_embute_manifesto_no_html_sem_acoplar_o_renderizador(self):
        raiz = self.saida / "integracao"
        (raiz / "data/sessoes").mkdir(parents=True)
        saida = raiz / "site"
        modelo = {"pessoas": {}, "projetos": [], "documentos": [], "legislaturas": []}
        html = "<!doctype html><html><head></head><body>Sessões</body></html>"
        with contextlib.ExitStack() as pilha:
            pilha.enter_context(mock.patch.object(GS, "RAIZ", raiz))
            pilha.enter_context(mock.patch.object(GS, "SAIDA", saida))
            pilha.enter_context(mock.patch.object(GS, "montar_modelo", return_value=modelo))
            pilha.enter_context(mock.patch.object(GS, "carregar_geo", return_value=None))
            pilha.enter_context(mock.patch.object(GS.modelo_sessoes, "montar_sessoes", return_value=self.modelo["sessoes"]))
            pilha.enter_context(mock.patch.object(GS.pagina_sessoes, "gerar_sessoes", return_value=html))
            pilha.enter_context(mock.patch.object(GS.N, "eventos_do_modelo", return_value=[]))
            pilha.enter_context(mock.patch.object(GS.N, "gerar_rss", return_value="<rss/>"))
            for funcao in ("gerar_index", "gerar_leis", "gerar_projetos", "gerar_atividades", "gerar_ruido", "gerar_analises",
                           "gerar_metodologia", "gerar_novidades"):
                pilha.enter_context(mock.patch.object(P, funcao, return_value=html))
            pilha.enter_context(contextlib.redirect_stdout(io.StringIO()))
            GS.main()
        embutido = manifesto_embutido((saida / "sessoes.html").read_text(encoding="utf-8"))
        manifesto = json.loads((saida / "dados/manifest.json").read_bytes())
        self.assertEqual(embutido["esquema"], manifesto["esquema"])
        self.assertEqual(embutido["build"], manifesto["build"])
        self.assertEqual((saida / "sessoes.js").read_bytes(), (GS.FONTE_ESTATICA / "sessoes.js").read_bytes())
        self.assertEqual(embutido["arquivos"], {n: e for n, e in manifesto["arquivos"].items()
                                               if e.get("familia") in {"dic-ses", "vot"}})
        self.assertEqual(set(embutido["arquivos"]), {"dic-ses", "vot-2025", "vot-2026"})

    def test_relatorio_dicionario_soma_maximo_e_aviso_de_150_kib(self):
        (self.saida / "sessoes.js").write_bytes((GS.FONTE_ESTATICA / "sessoes.js").read_bytes())
        saida, avisos = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(avisos):
            GS.relatorio_tamanhos(self.saida, self.manifesto)
        self.assertIn("dados/dic-ses.json", saida.getvalue())
        self.assertIn("sessoes.js", saida.getvalue())
        self.assertIn("dados/vot-*.json (soma de 2)", saida.getvalue())
        self.assertIn("dados/vot-*.json (máximo)", saida.getvalue())
        self.assertIn("JSON inicial de sessoes.html (2 arquivos)", saida.getvalue())
        self.assertEqual(avisos.getvalue(), "")
        self.assertEqual(GS.LIMITE_PARTE_VOT_GZIP, 150 * 1024)
        with (mock.patch.object(GS, "LIMITE_PARTE_VOT_GZIP", 1),
              mock.patch.object(GS, "LIMITE_JSON_GZIP", 1),
              contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(avisos)):
            GS.relatorio_tamanhos(self.saida)
        self.assertIn("::warning::dados/vot-2026.json:", avisos.getvalue())
        self.assertIn("::warning::dados/dic-ses.json:", avisos.getvalue())

    def test_sem_sessoes_ou_sem_votos_nao_cria_partes(self):
        for dados in (None, {}, {"anos": [2026], "votacoes": []}):
            with self.subTest(sessoes=dados):
                saida = self.saida / "vazio"
                manifesto = manifesto_vazio()
                self.assertIs(GS.exportar_sessoes({"sessoes": dados}, saida, manifesto), manifesto)
                self.assertEqual(manifesto, manifesto_vazio())
                self.assertFalse(list(saida.glob("dados/vot-*.json")))


class TestScriptsOpcionais(unittest.TestCase):
    def test_scripts_com_prefixo_hash_e_defer_sem_exigir_arquivo_futuro(self):
        with tempfile.TemporaryDirectory() as pasta:
            fonte = Path(pasta)
            for nome in ("estilo.css", "dados.js", "app.js"):
                (fonte / nome).write_bytes(b"/* recurso de teste */")
            with mock.patch.object(P, "FONTE_ESTATICA", fonte):
                html = P.pagina("Sessões", "", "sessoes.html", prefixo="../", scripts=("sessoes.js",))
                self.assertNotIn('src="../sessoes.js', html)
                conteudo = b"// sessoes"
                (fonte / "sessoes.js").write_bytes(conteudo)
                html = P.pagina("Sessões", "", "sessoes.html", prefixo="../", scripts=("sessoes.js",))
                versao = hashlib.sha1(conteudo).hexdigest()[:10]
                self.assertIn(f'<script src="../sessoes.js?v={versao}" defer></script>', html)
                self.assertLess(html.index('src="../app.js'), html.index('src="../sessoes.js'))
                self.assertNotIn('src="../sessoes.js', P.pagina("Sessões", "", "sessoes.html", prefixo="../"))


if __name__ == "__main__":
    unittest.main()
