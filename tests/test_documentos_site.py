"""Testes da integração dos demais documentos ao site: modelo, partes em colunas, manifesto e páginas.

Usa dados sintéticos em diretórios temporários; não lê data/ nem escreve em site/.
"""
from __future__ import annotations

import contextlib
import gzip
import hashlib
import io
import json
import random
import re
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from coletor import gerar_site as GS
from coletor.site import modelo as M
from coletor.site import paginas as P

URL = M.URL_DETALHE
# Manifesto e planos esperados compartilhados com tests/js/documentos.test.js (paridade plano_docs × fatiasDocs).
FIXTURE_PLANO = Path(__file__).resolve().parent / "js" / "fixtures" / "plano_docs.json"

CFG = {
    "legislaturas": [
        {"id": "2021-2024", "inicio": "2021-01-01", "fim": "2024-12-31", "fonte": "https://exemplo.invalid/e1",
         "eleitos": [{"nome": "Ana Teste", "siscam": "ANA MARIA TESTE", "partido": "PV"}]},
        {"id": "2025-2028", "inicio": "2025-01-01", "fim": "2028-12-31", "fonte": "https://exemplo.invalid/e2",
         "eleitos": [{"nome": "Ana Teste", "siscam": "ANA MARIA TESTE", "partido": "PX"},
                     {"nome": "Michel Saad", "siscam": "MICHEL SALIM SAAD NETO", "partido": "PZ"}]},
    ],
    "afastamentos": [],
    "nao_vereador": ["MESA DIRETORA", "COMISSÃO", "PODER EXECUTIVO", "MINISTÉRIO PÚBLICO"],
    "apelidos": {"_leia_me": "ignorado", "DINÁ SÓ INDICAÇÃO": "Diná"},
}
ANA_PL = {"id": 1, "nome": "ANA MARIA TESTE", "origem": "Vereador", "papel": "Autor"}
PROPOSICOES = [{
    "id": 10, "numero": "10/2025", "ano": 2025, "data": "2025-02-01", "data_protocolo": "2025-02-01",
    "ementa": "Cria o programa municipal de hortas comunitárias nas escolas", "situacao": "", "desfecho": "em_tramitacao",
    "lei": None, "autoria": [ANA_PL], "tramitacoes": [], "url": URL.format(id=10),
}]


def doc(id_: int, tipo: str, numero: str, data: str | None, ementa: str, autores: list[dict], situacao: str = "RECEBIDO", **extra) -> dict:
    ano = int(numero.split("/")[1])
    return {"id": id_, "tipo": tipo, "numero": numero, "ano": ano, "data": data, "ementa": ementa, "situacao": situacao,
            "autores": autores, "ultima_tramitacao": None, "n_tramitacoes": 0, "url": URL.format(id=id_), **extra}


DOCS = {
    ("indicacao", 2026): [
        doc(900001, "indicacao", "10/2026", "2026-03-10", "Indica a poda de árvores na Rua Tal, Icaraí.",
            [{"id": 1, "nome": "Ana Maria Teste"}, {"id": 2, "nome": "Mesa Diretora 2025/2026"}]),
        doc(900002, "indicacao", "11/2026", "2026-03-11", "Indica a troca de lâmpadas na Rua X, Centro.",
            [{"id": 5, "nome": "Diná Só Indicação"}, {"id": 5, "nome": "DINÁ SÓ INDICAÇÃO"}]),
    ],
    ("requerimento", 2026): [
        doc(900010, "requerimento", "3/2026", "2026-02-01", "Requer informações sobre o contrato de limpeza urbana.",
            [{"id": 275, "nome": "Michel Salim Saad Neto"}], situacao="RESPONDIDO",
            autoria=[{"nome": "MICHEL SALIM SAAD NETO", "origem": "Vereador", "papel": "Autor"},
                     {"nome": "Ána Maria Teste", "origem": "Vereadora", "papel": "Coautor"}],
            respondido_em="2026-03-03", dias_ate_resposta=30, detalhe_em="2026-03-05T10:00:00+00:00"),
        doc(900011, "requerimento", "4/2026", "2026-01-15", "Requer a realização de sessão solene.",
            [{"id": 1, "nome": "ANA MARIA TESTE"}], situacao="RECEBIDO PELA SMD", detalhe_pendente=True, assunto="Sessão solene"),
    ],
    ("mocao", 2025): [
        doc(800001, "mocao", "5/2025", "2025-06-01", "Moção de aplauso ao time <Unidos & Cia>.", [{"id": 1, "nome": "Ana Maria Teste"}],
            situacao="APROVADA"),
    ],
    ("pdl", 2026): [
        doc(900020, "pdl", "2/2026", "2026-04-01", "Concede o título de cidadão niteroiense ao Sr. Fulano.",
            [{"id": 1, "nome": "Ana Maria Teste"}], situacao="PUBLICADO",
            autoria=[{"nome": "ANA MARIA TESTE", "origem": "Vereadora", "papel": "Autor"}],
            publicacao={"numero": "123", "data": "2026-05-02"}),
    ],
}


def preparar_raiz(raiz: Path, documentos: dict | None = DOCS) -> None:
    (raiz / "config").mkdir(parents=True)
    (raiz / "data").mkdir()
    (raiz / "config" / "vereadores.json").write_text(json.dumps(CFG), encoding="utf-8")
    (raiz / "data" / "meta.json").write_text(json.dumps({"coleta": {"em": "2026-10-19T09:17:00+00:00"}}), encoding="utf-8")
    for (tipo, ano), registros in (documentos or {}).items():
        pasta = raiz / "data" / "documentos" / tipo
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / f"{ano}.json").write_text(json.dumps(registros, ensure_ascii=False), encoding="utf-8")


def montar(documentos: dict | None = DOCS) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        raiz = Path(tmp)
        preparar_raiz(raiz, documentos)
        with mock.patch.object(M, "RAIZ", raiz), \
                mock.patch.object(M, "carregar_proposicoes", lambda: [dict(p) for p in PROPOSICOES]), \
                mock.patch.object(M, "carregar_curadoria", lambda: {}), \
                mock.patch("coletor.classificar.CONFIANCA_MINIMA", 0.75):
            return M.montar_modelo()


def hidratar(dic: dict, fatia: dict) -> list[dict]:
    """Espelho em Python de RadarDados.hidratarDocs, para conferir a reversibilidade das colunas.

    tp, c e sc apontam para dic-doc; au, st e b, para os dicionários locais da própria parte.
    """
    c = fatia["colunas"]
    pessoas, situacoes, bairros = fatia["pessoas"], fatia["situacoes"], fatia["bairros"]
    saida = []
    for j, id_ in enumerate(c["id"]):
        pb = c["pb"][j]
        saida.append({
            "id": id_, "tipo": dic["tipos"][c["tp"][j]][0], "numero": c["n"][j], "ano": c["a"][j], "data": c["d"][j],
            "ementa": c["e"][j], "situacao": situacoes[c["st"][j]], "assunto": c["as"][j],
            "autores": [[pessoas[i][1], pessoas[i][0], 1 if pessoas[i][2] else 0, pessoas[i][3] if len(pessoas[i]) > 3 else ""]
                        for i in c["au"][j]],
            "categoria": dic["categorias"][c["c"][j]][0], "subcategoria": dic["subcategorias"][c["sc"][j]][1],
            "homenagem": c["h"][j] == 1, "respondido": c["rs"][j] == 1, "respondido_em": c["re"][j],
            "dias_ate_resposta": c["dr"][j], "publicado": c["pu"][j] == 1,
            "publicacao": {"numero": pb[0], "data": pb[1]} if pb else None,
            "bairro": None if c["b"][j] is None else bairros[c["b"][j]], "detalhe_pendente": c["dp"][j] == 1,
            "url": dic["url_detalhe"].replace("{id}", str(id_)),
        })
    return saida


def esperado(d: dict) -> dict:
    return {
        "id": d["id"], "tipo": d["tipo"], "numero": d["numero"], "ano": d["ano"], "data": d["data"], "ementa": d["ementa"],
        "situacao": d["situacao"], "assunto": d["assunto"],
        "autores": [[a["exibicao"], a["slug"], int(a["pagina"]), a.get("partido") or ""] for a in d["autores"]],
        "categoria": d["categoria"], "subcategoria": d["subcategoria"], "homenagem": d["homenagem"],
        "respondido": d["respondido"], "respondido_em": d["respondido_em"], "dias_ate_resposta": d["dias_ate_resposta"],
        "publicado": d["publicado"], "publicacao": d["publicacao"], "bairro": d["bairro"],
        "detalhe_pendente": d["detalhe_pendente"], "url": d["url"],
    }


# ------------------------------------------------------------------------- modelo
class TestModeloDocumentos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.modelo = montar()
        cls.docs = {d["id"]: d for d in cls.modelo["documentos"]}

    def test_documentos_separados_dos_projetos(self):
        self.assertEqual([p["id"] for p in self.modelo["projetos"]], [10])
        self.assertEqual(set(self.docs), {900001, 900002, 900010, 900011, 800001, 900020})
        ana = self.modelo["pessoas"]["ana-maria-teste"]
        self.assertEqual(ana["mandatos"]["2025-2028"]["metricas"]["apresentados"], 1)
        self.assertEqual(ana["mandatos"]["2025-2028"]["metricas"]["coautorias"], 0)
        for p in self.modelo["projetos"]:
            self.assertNotIn("repete_projeto", p["sinais"])

    def test_ordem_do_mais_recente(self):
        self.assertEqual([d["id"] for d in self.modelo["documentos"]], [900020, 900002, 900001, 900010, 900011, 800001])

    def test_nomes_da_listagem_em_caixa_mista_viram_slug_do_vereador(self):
        autores = self.docs[900001]["autores"]
        self.assertEqual([(a["slug"], a["vereador"], a["pagina"], a["exibicao"], a["papel"]) for a in autores], [
            ("ana-maria-teste", True, True, "Ana Teste", ""),
            ("", False, False, "Mesa Diretora 2025/2026", ""),
        ])
        michel = self.docs[900010]["autores"][0]
        self.assertEqual((michel["slug"], michel["exibicao"]), ("michel-salim-saad-neto", "Michel Saad"))

    def test_autoria_do_detalhe_prevalece_e_mantem_papel(self):
        autores = self.docs[900010]["autores"]
        self.assertEqual([(a["slug"], a["papel"]) for a in autores],
                         [("michel-salim-saad-neto", "Autor"), ("ana-maria-teste", "Coautor")])  # "Ána" sem diferença de acento

    def test_vereador_sem_projeto_de_lei_e_autores_repetidos(self):
        autores = self.docs[900002]["autores"]
        self.assertEqual(len(autores), 1)
        self.assertEqual((autores[0]["slug"], autores[0]["vereador"], autores[0]["pagina"], autores[0]["exibicao"]),
                         ("dina-so-indicacao", True, False, "Diná"))
        self.assertNotIn("dina-so-indicacao", self.modelo["pessoas"])  # não cria página nem linha no placar
        self.assertIn("dina-so-indicacao", self.modelo["atividade"])

    def test_classificacao_e_campos_derivados(self):
        ind, req, moc, pdl = self.docs[900001], self.docs[900010], self.docs[800001], self.docs[900020]
        self.assertEqual((ind["categoria"], ind["subcategoria"], ind["bairro"]), ("zeladoria", "poda", "Icaraí"))
        self.assertEqual((req["categoria"], req["subcategoria"], req["respondido"]), ("fiscalizacao", "informacao", True))
        self.assertEqual((req["respondido_em"], req["dias_ate_resposta"]), ("2026-03-03", 30))
        self.assertEqual((moc["categoria"], moc["homenagem"], moc["legislatura"]), ("homenagem", True, "2025-2028"))
        self.assertEqual((pdl["categoria"], pdl["publicado"], pdl["publicacao"]), ("homenagem", True, {"numero": "123", "data": "2026-05-02"}))
        self.assertTrue(self.docs[900011]["detalhe_pendente"])
        self.assertEqual(self.docs[900011]["assunto"], "Sessão solene")
        self.assertIsNone(ind["assunto"])

    def test_perfil_por_legislatura(self):
        leg = self.modelo["pessoas"]["ana-maria-teste"]["atividade"]["por_leg"]["2025-2028"]
        self.assertEqual(leg["tipos"], {"requerimento": 2, "indicacao": 1, "mocao": 1, "pdl": 1, "resolucao": 0})
        self.assertEqual(leg["perfil"], {"zeladoria": 1, "fiscalizacao": 1, "homenagem": 2, "legislacao": 0})
        self.assertEqual(leg["informacao"], {"respondidos": 1, "sem_resposta": 0})
        self.assertEqual(self.modelo["pessoas"]["ana-maria-teste"]["atividade"]["documentos"][0]["id"], 900020)
        self.assertEqual(self.modelo["pessoas"]["michel-salim-saad-neto"]["atividade"]["por_leg"]["2025-2028"]["tipos"]["requerimento"], 1)

    def test_arquivos_ausentes_viram_lista_vazia(self):
        modelo = montar(documentos=None)
        self.assertEqual(modelo["documentos"], [])
        self.assertEqual(modelo["atividade"], {})
        self.assertEqual(modelo["pessoas"]["ana-maria-teste"]["atividade"], {"documentos": [], "por_leg": {}})


# ------------------------------------------------------------------- exportação
def sinteticos(pessoas: dict, extras: list[dict] | None = None) -> list[dict]:
    rnd = random.Random(20260101)
    palavras = ("poda arvore lampada buraco asfalto calcada bueiro limpeza capina sinalizacao faixa pedestre escola posto "
                "praca travessa avenida esquina iluminacao reparo galeria entulho redutor ponto onibus").split()
    bairros = ("Icaraí", "Fonseca", "Centro", "Itaipu", "Barreto", "Santa Rosa")
    regs = []
    for i in range(1500):
        dia = date(2026, 1, 1) + timedelta(days=i // 8)
        ementa = "Indica " + " ".join(rnd.choice(palavras) for _ in range(rnd.randint(8, 18))) + \
            f", Rua {rnd.randint(1, 999)}, {rnd.choice(bairros)}."
        regs.append(doc(700000 + i, "indicacao", f"{i + 1}/2026", dia.isoformat(), ementa, [{"id": 1, "nome": "Ana Maria Teste"}]))
    for i in range(300):
        dia = date(2025, 1, 1) + timedelta(days=i // 4)
        ementa = "Moção de aplauso a " + " ".join(rnd.choice(palavras) for _ in range(rnd.randint(4, 12)))
        autores = [{"id": 1, "nome": "Ana Maria Teste"}] + ([{"id": 275, "nome": "Michel Salim Saad Neto"}] if i % 3 == 0 else [])
        regs.append(doc(600000 + i, "mocao", f"{i + 1}/2025", dia.isoformat(), ementa, autores, situacao="APROVADA"))
    return M.montar_documentos(regs + list(extras or []), CFG, pessoas, CFG["legislaturas"])


class TestExportacaoDocumentos(unittest.TestCase):
    LIMITE_PRIMEIRA, LIMITE = 3 * 1024, 8 * 1024

    @classmethod
    def setUpClass(cls):
        base = montar()
        cls.modelo = {"documentos": sinteticos(base["pessoas"]), "pessoas": base["pessoas"], "legislaturas": base["legislaturas"]}
        cls.tmp = tempfile.TemporaryDirectory()
        cls.saidas = [Path(cls.tmp.name) / "a", Path(cls.tmp.name) / "b"]
        cls.manifestos = [cls.exportar(s) for s in cls.saidas]
        cls.manifesto = cls.manifestos[0]
        cls.saida = cls.saidas[0]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def exportar(cls, saida: Path) -> dict:
        return cls.exportar_modelo(cls.modelo, saida)

    @classmethod
    def exportar_modelo(cls, modelo: dict, saida: Path) -> dict:
        (saida / "dados").mkdir(parents=True)
        manifesto = {"esquema": 2, "build": "pl00000000", "arquivos": {"dic-pl": {"url": "dados/dic-pl.json?v=x", "n": 1, "bytes": 1}}}
        with mock.patch.object(GS, "LIMITE_PRIMEIRA_PARTE_DOC_GZIP", cls.LIMITE_PRIMEIRA), \
                mock.patch.object(GS, "ALVO_PARTE_DOC_GZIP", cls.LIMITE):
            return GS.exportar_documentos(modelo, saida, manifesto)

    def ler(self, nome: str) -> dict:
        return json.loads((self.saida / f"dados/{nome}.json").read_bytes())

    def partes(self, familia: str) -> list[tuple[str, dict]]:
        return [(n, e) for n, e in self.manifesto["arquivos"].items() if e.get("familia") == familia]

    def test_pl_intacto_e_documentos_sem_build(self):
        self.assertEqual(self.manifesto["build"], "pl00000000")
        self.assertEqual(self.manifesto["arquivos"]["dic-pl"], {"url": "dados/dic-pl.json?v=x", "n": 1, "bytes": 1})
        self.assertRegex(self.manifesto["build_doc"], r"^[0-9a-f]{10}$")
        self.assertEqual(self.manifesto["build_doc"], GS.versao_documentos(
            {n: e for n, e in self.manifesto["arquivos"].items() if e.get("familia")}))
        for nome, _ in self.partes("doc") + self.partes("ver") + self.partes("dic-doc"):
            dados = self.ler(nome)
            self.assertEqual(dados["esquema"], 2, nome)
            self.assertNotIn("build", dados, nome)  # a URL já traz o hash do conteúdo

    def test_dic_doc_so_tem_enumeracoes_estaveis(self):
        dic = self.ler("dic-doc")
        self.assertEqual(set(dic), {"esquema", "n", "tipos", "categorias", "subcategorias", "url_detalhe"})
        self.assertEqual([t[0] for t in dic["tipos"]], list(M.TIPOS_DOC))
        for nome, _ in self.partes("doc") + self.partes("ver"):
            fatia = self.ler(nome)
            with self.subTest(nome=nome):
                self.assertEqual(fatia["pessoas"], sorted(fatia["pessoas"]))
                self.assertEqual(fatia["situacoes"], sorted(fatia["situacoes"]))
                # Sem mapas de partido por pessoa: no máximo a sigla na legislatura do documento, como quarto campo.
                self.assertTrue(all(len(p) == 3 or (len(p) == 4 and isinstance(p[3], str) and p[3]) for p in fatia["pessoas"]))
                usados = {i for au in fatia["colunas"]["au"] for i in au}
                self.assertEqual(usados, set(range(len(fatia["pessoas"]))), "dicionário local só com quem aparece na parte")

    def test_partes_inalteradas_mantem_bytes_e_url(self):
        """Um documento novo num tipo/ano muda só as partes desse tipo/ano e as do autor; as demais ficam idênticas."""
        base = montar()
        novo_doc = doc(990001, "requerimento", "1/2026", "2026-02-10", "Requer informações sobre a coleta de lixo.",
                       [{"id": 275, "nome": "Michel Salim Saad Neto"}])
        modelo = {"documentos": sinteticos(base["pessoas"], [novo_doc]), "pessoas": base["pessoas"],
                  "legislaturas": base["legislaturas"]}
        with tempfile.TemporaryDirectory() as tmp:
            saida = Path(tmp) / "c"
            novo = self.exportar_modelo(modelo, saida)
            antigo = self.manifesto["arquivos"]
            afetado = lambda n: n.startswith("doc-requerimento-2026") or n.startswith("ver/michel-salim-saad-neto")
            mudaram = {n for n, e in novo["arquivos"].items() if antigo.get(n, {}).get("url") != e["url"]}
            self.assertTrue(mudaram, "o documento novo precisa aparecer em alguma parte")
            self.assertTrue(all(afetado(n) for n in mudaram), mudaram)
            self.assertIn("doc-requerimento-2026", mudaram)
            inalterados = [n for n, e in antigo.items() if e.get("familia") and not afetado(n)]
            self.assertIn("dic-doc", inalterados)
            self.assertTrue(any(n.startswith("doc-indicacao-2026") for n in inalterados))
            self.assertTrue(any(n.startswith("doc-mocao-2025") for n in inalterados))
            self.assertTrue(any(n.startswith("ver/ana-maria-teste") for n in inalterados))
            for nome in inalterados:
                with self.subTest(nome=nome):
                    self.assertEqual(novo["arquivos"][nome], antigo[nome])  # mesma URL (hash), n e bytes
                    self.assertEqual((saida / f"dados/{nome}.json").read_bytes(), (self.saida / f"dados/{nome}.json").read_bytes())
            self.assertNotEqual(novo["build_doc"], self.manifesto["build_doc"])

    def test_entradas_do_manifesto(self):
        for nome, e in self.manifesto["arquivos"].items():
            if not e.get("familia"):
                continue
            conteudo = (self.saida / f"dados/{nome}.json").read_bytes()
            with self.subTest(nome=nome):
                self.assertEqual(e["url"], f"dados/{nome}.json?v={hashlib.sha1(conteudo).hexdigest()[:10]}")
                self.assertEqual(e["bytes"], len(conteudo))
                self.assertEqual(e["n"], json.loads(conteudo)["n"])
        nomes = [n for n, _ in self.partes("doc")]
        self.assertIn("doc-indicacao-2026", nomes)
        self.assertIn("doc-indicacao-2026-1", nomes)
        self.assertIn("doc-mocao-2025", nomes)

    def test_partes_cabem_no_orcamento_e_vao_do_mais_recente(self):
        grupos: dict[tuple[str, int], list[tuple[int, dict]]] = {}
        for nome, e in self.partes("doc"):
            grupos.setdefault((e["tipo"], e["ano"]), []).append((e["parte"], e))
            gz = len(gzip.compress((self.saida / f"dados/{nome}.json").read_bytes(), mtime=0))
            self.assertLessEqual(gz, self.LIMITE_PRIMEIRA if e["parte"] == 0 else self.LIMITE, nome)
        dic = self.ler("dic-doc")
        for (tipo, ano), partes in grupos.items():
            partes.sort(key=lambda pe: pe[0])
            self.assertEqual([k for k, _ in partes], list(range(len(partes))))
            ids, anterior = [], None
            for k, e in partes:
                fatia = self.ler(GS.nome_parte(f"doc-{tipo}-{ano}", k))
                self.assertEqual((fatia["tipo"], fatia["ano"], fatia["parte"]), (tipo, ano, k))
                self.assertEqual((e["ate"], e["de"]), (fatia["colunas"]["d"][0], fatia["colunas"]["d"][-1]))
                if anterior:
                    self.assertGreater(anterior["de"], e["ate"], "uma data não pode ficar dividida entre partes")
                anterior = e
                ids += fatia["colunas"]["id"]
            esperados = [d["id"] for d in self.modelo["documentos"] if (d["tipo"], d["ano"]) == (tipo, ano)]
            self.assertEqual(ids, esperados)
        self.assertGreater(len(grupos[("indicacao", 2026)]), 2)
        self.assertEqual(dic["url_detalhe"], URL)

    def test_colunas_reversiveis(self):
        dic = self.ler("dic-doc")
        hidratados = {}
        for nome, _ in self.partes("doc"):
            for d in hidratar(dic, self.ler(nome)):
                hidratados[d["id"]] = d
        self.assertEqual(len(hidratados), len(self.modelo["documentos"]))
        for d in self.modelo["documentos"]:
            self.assertEqual(hidratados[d["id"]], esperado(d))

    def test_arquivos_por_vereador(self):
        dic = self.ler("dic-doc")
        por_slug: dict[str, list[int]] = {}
        for nome, e in self.partes("ver"):
            gz = len(gzip.compress((self.saida / f"dados/{nome}.json").read_bytes(), mtime=0))
            self.assertLessEqual(gz, self.LIMITE, nome)
            fatia = self.ler(nome)
            self.assertEqual((fatia["slug"], fatia["tipo"], fatia["parte"]), (e["slug"], e["tipo"], e["parte"]))
            por_slug.setdefault(e["slug"], []).extend(d["id"] for d in hidratar(dic, fatia))
        self.assertEqual(set(por_slug), {"ana-maria-teste", "michel-salim-saad-neto"})
        for s, ids in por_slug.items():
            esperados = {d["id"] for d in self.modelo["documentos"] if any(a["slug"] == s for a in d["autores"])}
            self.assertEqual(sorted(ids), sorted(esperados), s)
            self.assertEqual(len(ids), len(set(ids)), s)
        self.assertTrue(any(e["tipo"] == "indicacao" for n, e in self.partes("ver") if e["slug"] == "ana-maria-teste"),
                        "acima do orçamento, ver/<slug> se divide por tipo")
        nome = next(n for n, e in self.partes("ver") if e["slug"] == "ana-maria-teste")
        # Quarto campo: o partido na legislatura dos documentos (PX, eleição de 2024).
        self.assertIn(["ana-maria-teste", "Ana Teste", 1, "PX"], self.ler(nome)["pessoas"])

    def test_saida_deterministica(self):
        self.assertEqual(self.manifestos[0], self.manifestos[1])
        arquivos = sorted(p.relative_to(self.saidas[0]).as_posix() for p in self.saidas[0].rglob("*.json"))
        self.assertEqual(arquivos, sorted(p.relative_to(self.saidas[1]).as_posix() for p in self.saidas[1].rglob("*.json")))
        for nome in arquivos:
            self.assertEqual((self.saidas[0] / nome).read_bytes(), (self.saidas[1] / nome).read_bytes(), nome)
        self.assertEqual(json.loads((self.saida / "dados/manifest.json").read_bytes()), self.manifesto)

    def test_carga_inicial_e_planejador(self):
        arquivos = self.manifesto["arquivos"]
        inicial = P.iniciais_por_pagina(self.manifesto)["atividades.html"]
        self.assertEqual(inicial[0], "dic-doc")
        self.assertEqual(P.ano_padrao_doc(arquivos), 2026)
        self.assertEqual(inicial[1], "doc-indicacao-2026")
        self.assertTrue(all(arquivos[n]["ano"] == 2026 for n in inicial[1:]))
        restantes = [e for n, e in arquivos.items() if e.get("familia") == "doc" and e["ano"] == 2026 and n not in inicial]
        fronteira = max((e["ate"] for e in restantes), default="")
        seguros = sum(arquivos[n]["n"] for n in inicial[1:] if arquivos[n]["de"] > fronteira)
        self.assertTrue(not restantes or seguros >= P.PASSO_LISTA)
        self.assertEqual(P.plano_docs(arquivos, tipos=["mocao"], ano=2025, alvo=10 ** 6),
                         sorted((n for n, e in arquivos.items() if e.get("familia") == "doc" and e["tipo"] == "mocao"),
                                key=lambda n: arquivos[n]["parte"]))

    def test_relatorio_inclui_carga_inicial(self):
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(io.StringIO()):
            GS.relatorio_tamanhos(self.saida, self.manifesto)
        self.assertIn("JSON inicial de atividades.html", saida.getvalue())
        self.assertIn("dados/doc-*.json (máximo)", saida.getvalue())
        self.assertEqual(GS.cargas_acima_do_orcamento(self.saida, self.manifesto), [])
        with mock.patch.object(GS, "LIMITE_INICIAL_GZIP", 1):
            self.assertEqual([a.split(":")[0] for a in GS.cargas_acima_do_orcamento(self.saida, self.manifesto)], ["atividades.html"])

    def test_sem_documentos_o_manifesto_fica_igual(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifesto = {"esquema": 2, "build": "b", "arquivos": {}}
            GS.exportar_documentos({"documentos": [], "pessoas": {}, "legislaturas": []}, Path(tmp), manifesto)
            self.assertEqual(manifesto, {"esquema": 2, "build": "b", "arquivos": {}})
            self.assertEqual(P.iniciais_por_pagina(manifesto), P.INICIAIS_PL)


class TestAlvoDocumentos(unittest.TestCase):
    def test_alvo_com_folga_sem_relaxar_orcamento_oficial(self):
        self.assertEqual(GS.ALVO_PARTE_DOC_GZIP, 120 * 1024)
        self.assertEqual(GS.LIMITE_PARTE_DOC_GZIP, 150 * 1024)
        self.assertEqual(GS.LIMITE_PRIMEIRA_PARTE_DOC_GZIP, 24 * 1024)
        self.assertEqual(GS.MARGEM_GZIP, 512)

    def test_exportacao_com_alvo_padrao_nas_duas_familias(self):
        base = montar()
        docs = sinteticos(base["pessoas"])
        rnd = random.Random(120)
        # Texto pouco repetitivo força partes grandes sem depender dos dados versionados.
        docs = [dict(d, ementa=d["ementa"] + " " + rnd.randbytes(128).hex()) for d in docs]
        modelo = {"documentos": docs}
        with tempfile.TemporaryDirectory() as tmp:
            saida, antiga = Path(tmp) / "nova", Path(tmp) / "antiga"
            for pasta in (saida, antiga):
                (pasta / "dados").mkdir(parents=True)
            manifesto = GS.exportar_documentos(modelo, saida, {"esquema": 2, "build": "pl", "arquivos": {}})
            with mock.patch.object(GS, "ALVO_PARTE_DOC_GZIP", GS.LIMITE_PARTE_DOC_GZIP):
                anterior = GS.exportar_documentos(modelo, antiga, {"esquema": 2, "build": "pl", "arquivos": {}})
            inalterados = ["dic-doc", "ver/michel-salim-saad-neto"]
            for familia in ("doc", "ver"):
                partes = [(n, e) for n, e in manifesto["arquivos"].items() if e.get("familia") == familia]
                self.assertTrue(any(e["parte"] > 1 for _, e in partes), "pré-condição: várias partes em " + familia)
                self.assertGreater(len(partes), sum(e.get("familia") == familia for e in anterior["arquivos"].values()))
                for nome, e in partes:
                    conteudo = (saida / e["url"].split("?")[0]).read_bytes()
                    with self.subTest(nome=nome):
                        self.assertLessEqual(GS.tamanho_gzip(conteudo, nivel=6), GS.ALVO_PARTE_DOC_GZIP - GS.MARGEM_GZIP)
                        self.assertLessEqual(GS.tamanho_gzip(conteudo), 125 * 1024)
                        if familia == "doc" and e["parte"] == 0:
                            self.assertLessEqual(GS.tamanho_gzip(conteudo, nivel=6), GS.LIMITE_PRIMEIRA_PARTE_DOC_GZIP - GS.MARGEM_GZIP)
                            inalterados.append(nome)
            for nome in inalterados:
                with self.subTest(inalterado=nome):
                    self.assertEqual(manifesto["arquivos"][nome], anterior["arquivos"][nome])
                    self.assertEqual((saida / f"dados/{nome}.json").read_bytes(), (antiga / f"dados/{nome}.json").read_bytes())

    def test_relatorio_so_avisa_acima_de_150_kib(self):
        with tempfile.TemporaryDirectory() as tmp:
            saida = Path(tmp)
            (saida / "dados" / "ver").mkdir(parents=True)
            for nome in ("doc-indicacao-2026", "ver/ana-maria-teste"):
                (saida / f"dados/{nome}.json").write_bytes(b"{}")
            for tamanho in (GS.ALVO_PARTE_DOC_GZIP + 1, GS.LIMITE_PARTE_DOC_GZIP, GS.LIMITE_PARTE_DOC_GZIP + 1):
                avisos = io.StringIO()
                with self.subTest(tamanho=tamanho), contextlib.redirect_stdout(io.StringIO()), \
                        contextlib.redirect_stderr(avisos), mock.patch.object(GS.gzip, "compress", return_value=b"x" * tamanho):
                    GS.relatorio_tamanhos(saida)
                if tamanho <= GS.LIMITE_PARTE_DOC_GZIP:
                    self.assertEqual(avisos.getvalue(), "")
                else:
                    self.assertEqual(avisos.getvalue().count("::warning::"), 2)
                    self.assertIn("orçamento de parte de documentos de 153600 bytes", avisos.getvalue())


class TestDataDivididaNaPrimeiraParte(unittest.TestCase):
    """Uma data com mais documentos do que cabem na primeira parte não pode levar uma parte grande à carga inicial."""
    LIMITE_PRIMEIRA, LIMITE = 3 * 1024, 16 * 1024

    def test_carga_inicial_so_com_partes_pequenas(self):
        base = montar()
        rnd = random.Random(7)
        palavras = ("poda arvore lampada buraco asfalto calcada bueiro limpeza capina sinalizacao faixa pedestre escola "
                    "posto praca travessa avenida esquina iluminacao reparo galeria entulho redutor ponto onibus").split()
        regs = []
        for i in range(600):
            # 200 indicações no dia mais recente; depois, 8 por dia.
            dia = date(2026, 10, 20) if i < 200 else date(2026, 10, 19) - timedelta(days=(i - 200) // 8)
            ementa = "Indica " + " ".join(rnd.choice(palavras) for _ in range(rnd.randint(8, 18))) + f", Rua {rnd.randint(1, 999)}."
            regs.append(doc(710000 + i, "indicacao", f"{i + 1}/2026", dia.isoformat(), ementa, [{"id": 1, "nome": "Ana Maria Teste"}]))
        modelo = {"documentos": M.montar_documentos(regs, CFG, base["pessoas"], CFG["legislaturas"]),
                  "pessoas": base["pessoas"], "legislaturas": base["legislaturas"]}
        with tempfile.TemporaryDirectory() as tmp:
            saida = Path(tmp)
            (saida / "dados").mkdir()
            with mock.patch.object(GS, "LIMITE_PRIMEIRA_PARTE_DOC_GZIP", self.LIMITE_PRIMEIRA), \
                    mock.patch.object(GS, "ALVO_PARTE_DOC_GZIP", self.LIMITE):
                manifesto = GS.exportar_documentos(modelo, saida, {"esquema": 2, "build": "pl", "arquivos": {}})
            arquivos = manifesto["arquivos"]
            gz = lambda n: len(gzip.compress((saida / f"dados/{n}.json").read_bytes(), mtime=0))
            partes = sorted((e["parte"], n) for n, e in arquivos.items() if e.get("familia") == "doc")
            nomes = [n for _, n in partes]
            self.assertEqual(arquivos[nomes[0]]["de"], arquivos[nomes[1]]["ate"], "pré-condição: a data mais recente fica dividida")
            self.assertTrue(any(gz(n) > self.LIMITE_PRIMEIRA for n in nomes), "pré-condição: há partes grandes")
            for n in nomes:
                self.assertLessEqual(gz(n), self.LIMITE, n)
            inicial = P.iniciais_por_pagina(manifesto)["atividades.html"][1:]
            self.assertGreater(len(inicial), 1)
            for n in inicial:
                self.assertLessEqual(gz(n), self.LIMITE_PRIMEIRA, n)
            restantes = [e for n, e in arquivos.items() if e.get("familia") == "doc" and n not in inicial]
            fronteira = max((e["ate"] for e in restantes), default="")
            self.assertGreaterEqual(sum(arquivos[n]["n"] for n in inicial if arquivos[n]["de"] > fronteira), P.PASSO_LISTA)
            ids = [i for n in nomes for i in json.loads((saida / f"dados/{n}.json").read_bytes())["colunas"]["id"]]
            self.assertEqual(ids, [d["id"] for d in modelo["documentos"]])


class TestParidadePlano(unittest.TestCase):
    """plano_docs (Python) e fatiasDocs (dados.js) leem a mesma fixture; tests/js/documentos.test.js confere o outro lado."""

    def test_plano_docs_igual_ao_esperado_pelo_navegador(self):
        fixture = json.loads(FIXTURE_PLANO.read_text(encoding="utf-8"))
        for cenario in (fixture, *fixture["refatiamentos"]):
            self.assertTrue(cenario["casos"])
            for caso in cenario["casos"]:
                with self.subTest(caso=caso["nome"]):
                    self.assertEqual(P.plano_docs(cenario["manifesto"]["arquivos"], tipos=caso["tipo"], ano=caso["ano"], alvo=caso["alvo"]),
                                     caso["nomes"])

    def test_passo_lista_igual_ao_do_app(self):
        app = (GS.FONTE_ESTATICA / "app.js").read_text(encoding="utf-8")
        self.assertEqual(int(re.search(r"\bPASSO = (\d+)", app).group(1)), P.PASSO_LISTA)

    def test_iniciais_de_atividades_usam_o_mesmo_plano(self):
        fixture = json.loads(FIXTURE_PLANO.read_text(encoding="utf-8"))
        caso = next(c for c in fixture["casos"] if c["tipo"] is None and c["ano"] == 2026 and c["alvo"] == P.PASSO_LISTA)
        self.assertEqual(P.iniciais_por_pagina(fixture["manifesto"])["atividades.html"], ["dic-doc", *caso["nomes"]])


# ---------------------------------------------------------------------- páginas
class TestPaginasDocumentos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.modelo = montar()
        cls.tmp = tempfile.TemporaryDirectory()
        saida = Path(cls.tmp.name)
        (saida / "dados").mkdir()
        cls.manifesto = GS.exportar_documentos(cls.modelo, saida, {"esquema": 2, "build": "pl", "arquivos": {}})

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_atividades(self):
        html = P.gerar_atividades(self.modelo, self.manifesto)
        self.assertIn('data-modo="atividades"', html)
        self.assertIn('data-ano-padrao="2026"', html)
        self.assertIn('<option value="2026" selected>', html)
        self.assertIn('<option value="ana-maria-teste">Ana Teste</option>', html)
        self.assertIn('<option value="dina-so-indicacao">Diná</option>', html)
        self.assertNotIn('value=""">Mesa', html)
        self.assertIn('<option value="Icaraí">Icaraí (1)</option>', html)
        self.assertIn('<optgroup label="Indicações">', html)
        self.assertIn('id="siscam-dialogo"', html)
        self.assertIn('aria-current="page">Atividades', html)
        embutido = json.loads(html.split('id="manifesto-dados">')[1].split("</script>")[0])
        self.assertEqual(embutido["build_doc"], self.manifesto["build_doc"])
        self.assertEqual(embutido["inicial"][0], "dic-doc")
        self.assertTrue(all(e.get("familia") for e in embutido["arquivos"].values()))

    def test_atividades_sem_documentos(self):
        html = P.gerar_atividades({"documentos": []}, None)
        self.assertIn("Nenhum documento coletado", html)
        self.assertNotIn('data-modo="atividades"', html)

    def test_secao_atividade_do_vereador(self):
        html = P.gerar_vereador(self.modelo, self.modelo["pessoas"]["ana-maria-teste"])
        self.assertIn('id="t-atividade"', html)
        self.assertIn("Documentos por ano e tipo", html)
        self.assertIn("Perfil de atuação por legislatura", html)
        self.assertIn("Requerimentos de informação: respondidos ou não", html)
        self.assertIn('<details class="tabela-graf">', html)
        self.assertIn('role="img"', html)
        self.assertIn('href="../atividades.html?autor=ana-maria-teste"', html)
        self.assertIn("&lt;Unidos &amp; Cia&gt;", html)
        self.assertNotIn("<Unidos", html)
        self.assertIn('class="ver-siscam"', html)
        self.assertIn(f'href="{URL.format(id=900020)}" target="_blank" rel="noopener">abrir no SISCAM', html)
        self.assertIn('id="siscam-dialogo"', html)

    def test_numero_do_documento_e_link_alternativo_abrem_em_nova_aba(self):
        d = self.modelo["documentos"][0]
        html = P.item_documento(d, "../")
        self.assertIn(f'href="{d["url"]}" target="_blank" rel="noopener">{P.rotulo_documento(d)}{P.NOVA_ABA}</a>', html)
        self.assertEqual(html.count('target="_blank" rel="noopener"'), 2)
        self.assertEqual(html.count(P.NOVA_ABA), 2)
        self.assertIn('<a class="chip" href="../vereadores/ana-maria-teste.html">', html)

    def test_placar_analises_e_metodologia(self):
        index = P.gerar_index(self.modelo)
        self.assertIn('data-indicacoes="1"', index)
        self.assertIn('data-requerimentos="2"', index)
        self.assertIn('<option value="mocoes">Moções</option>', index)
        self.assertIn('class="n-docs"', index)
        self.assertIn("Produção total da Câmara por tipo e ano", P.gerar_analises(self.modelo))
        meto = P.gerar_metodologia(self.modelo)
        self.assertIn('id="atividades"', meto)
        self.assertIn("respondido_em", meto)
        self.assertIn("só pela listagem", meto)

    def test_sem_documentos_paginas_de_pl_nao_mudam(self):
        modelo = montar(documentos=None)
        self.assertNotIn("data-indicacoes", P.gerar_index(modelo))
        self.assertNotIn("Produção total da Câmara por tipo e ano", P.gerar_analises(modelo))
        vereador = P.gerar_vereador(modelo, modelo["pessoas"]["ana-maria-teste"])
        self.assertNotIn('id="t-atividade"', vereador)
        self.assertNotIn('id="siscam-dialogo"', vereador)


if __name__ == "__main__":
    unittest.main()
