"""Fixtures do contrato de textos (`docs/contratos/textos.md`).

`tests/fixtures/contratos/` é uma raiz de repositório em miniatura gerada por
`tests/fixtures/contratos/gerar_fixtures.py`; aqui ela é gerada de novo numa pasta
temporária e comparada byte a byte, e depois conferida contra o contrato, com as
regras recalculadas de forma independente a partir dos registros.

Uso: python -m unittest tests.test_contratos
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import tempfile
import unicodedata
import unittest
from datetime import date
from pathlib import Path

from coletor import limpeza, mascara, remocoes, trechos
from coletor.arquivos import texto_mapa
from coletor.extratores import CONFIANCA_MINIMA, STATUS, VERSAO_EXTRATORES
from coletor.validar import validar_remocoes

RAIZ = Path(__file__).resolve().parent.parent
FIXTURES = RAIZ / "tests" / "fixtures" / "contratos"
DADOS = FIXTURES / "data"
DADOS_TEXTOS = FIXTURES / "dados-textos"
MANIFESTO = DADOS / "textos" / "manifesto-2024.json"
CONTRATO = RAIZ / "docs" / "contratos" / "textos.md"
COMANDO = "rode: python tests/fixtures/contratos/gerar_fixtures.py"

CAMPOS = {
    "documentos", "documento", "tipo", "url_origem", "sha256_original", "bytes", "formato", "extrator",
    "versao_extrator", "versao_extratores", "versao_limpeza", "versao_mascara", "versao_trechos",
    "sha256_config", "paginas", "paginas_ocr", "confianca", "cabecalhos_omitidos", "detalhe", "status",
    "duplicata_de", "limpeza", "mascarados", "sha256_bruto", "sha256_texto", "blob_texto", "chars",
    "trechos", "trechos_vetorizaveis", "r2_chave", "processado_em",
}
CAMPOS_TRECHO = {"id", "documento", "arquivo", "posicao", "inicio", "fim", "inicio_utf16", "fim_utf16",
                 "sha256", "vetorizavel"}
TIPOS = {"pl", "substitutivo", "requerimento", "pdl", "resolucao", "ata"}
PRIORIDADE = {"pl": 0, "requerimento": 1, "pdl": 2, "resolucao": 3, "ata": 4}
SEM_PROCESSAMENTO = {"removido", "pendente_download", "duplicata"}
STATUS_MANIFESTO = set(STATUS) | SEM_PROCESSAMENTO
STATUS_COM_TEXTO = {"ok", "ok_ocr", "ok_parcial", "ocr_baixa_confianca"}
SUCESSO = {"ok", "ok_ocr", "vazio_legitimo"}
ESVAZIADO = "esvaziado pela limpeza"
REGRAS = ("cabecalho_rodape", "numeracao", "ruido_ocr", "cliche")
TABELAS_D1 = ("documentos", "autoria", "pessoas", "arquivos", "arquivo_documento", "trechos",
              "trechos_fts", "trechos_indexados", "remocoes", "estado_indice", "verificacoes")
RE_CHAVE = re.compile(r"(?:siscam:[1-9][0-9]*|sessao:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")
RE_DOCUMENTO = re.compile(r"(?:doc|sessao):[1-9][0-9]*")
RE_SHA = re.compile(r"[0-9a-f]{64}")
RE_SHA1 = re.compile(r"[0-9a-f]{40}")
RE_DATA = re.compile(r"\d{4}-\d{2}-\d{2}")


def _gerador():
    spec = importlib.util.spec_from_file_location("gerar_fixtures_contratos", FIXTURES / "gerar_fixtures.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _arquivos(pasta: Path) -> dict[str, bytes]:
    return {p.relative_to(pasta).as_posix(): p.read_bytes() for p in sorted(pasta.rglob("*"))
            if p.is_file() and p.suffix != ".py" and "__pycache__" not in p.parts}


def _sha(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


def _ler_lista(caminho: Path) -> list[dict]:
    return json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else []


def _ordem(chave: str) -> tuple:
    origem, ident = chave.split(":", 1)
    return (0, int(ident), "") if origem == "siscam" else (1, 0, ident)


def _ler_texto(caminho: Path) -> str:
    """Leitor do contrato: tira exatamente uma quebra final."""
    conteudo = caminho.read_bytes().decode("utf-8")
    assert conteudo.endswith("\n")
    return conteudo[:-1]


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bruto = MANIFESTO.read_bytes()
        cls.manifesto = json.loads(cls.bruto.decode("utf-8"))
        cls.registros: dict[str, dict] = {}   # documento → {tipo, ano, data, ementa, pl}
        cls.citacoes: dict[str, set[str]] = {}  # chave de arquivo → documentos que a citam
        cls.urls: dict[str, str] = {}

        def citar(chave: str, documento: str, url: str) -> None:
            cls.citacoes.setdefault(chave, set()).add(documento)
            cls.urls[chave] = url

        cls.fora_do_escopo: set[str] = set()
        for pl in _ler_lista(DADOS / "proposicoes" / "2024.json"):
            chave_pl = f"doc:{pl['id']}"
            cls.registros[chave_pl] = {"tipo": "pl", "ano": pl["ano"], "data": pl["data"], "pl": None}
            for a in pl.get("arquivos") or []:
                citar(f"siscam:{a['id']}", chave_pl, "")
            for sub in pl.get("substitutivos") or []:
                assert "ano" not in sub and "ementa" not in sub and sub["numero"] == "1"
                chave_sub = f"doc:{sub['id']}"
                cls.registros[chave_sub] = {"tipo": "substitutivo", "ano": pl["ano"], "data": sub["data"],
                                            "pl": chave_pl}
                for a in sub.get("arquivos") or []:
                    citar(f"siscam:{a['id']}", chave_sub, "")
        for pasta in sorted((DADOS / "documentos").iterdir()):
            for d in _ler_lista(pasta / "2024.json"):
                chave_doc = f"doc:{d['id']}"
                cls.registros[chave_doc] = {"tipo": d["tipo"], "ano": d["ano"], "data": d["data"], "pl": None}
                for a in d.get("arquivos") or []:
                    if d["tipo"] in ("indicacao", "mocao"):
                        cls.fora_do_escopo.add(f"siscam:{a['id']}")
                    else:
                        citar(f"siscam:{a['id']}", chave_doc, "")
        for sessao in _ler_lista(DADOS / "sessoes" / "2024.json"):
            chave_sessao = f"sessao:{sessao['id']}"
            cls.registros[chave_sessao] = {"tipo": "ata", "ano": sessao["ano"], "data": sessao["data"], "pl": None}
            for item in sessao.get("documentos_sessao") or []:
                if item.get("rotulo") == "Ata" and item.get("url"):
                    guid = item["url"].rsplit("/", 1)[1].rsplit(".", 1)[0].lower()
                    citar(f"sessao:{guid}", chave_sessao, item["url"])

    def principal(self, documentos) -> str:
        """Documento principal recalculado: o PL de substitutivos; maior prioridade, menor id."""
        candidatos = {self.registros[d]["pl"] or d for d in documentos}
        return min(candidatos, key=lambda d: (PRIORIDADE[self.registros[d]["tipo"]], int(d.split(":")[1])))

    def com_texto(self, e: dict) -> bool:
        return e["status"] in STATUS_COM_TEXTO or e["detalhe"] == ESVAZIADO

    @staticmethod
    def caminho(chave: str, e: dict) -> str:
        doc = e["documento"].split(":", 1)[1]
        return f"textos/{e['tipo']}/2024/{doc}/{chave.replace(':', '-', 1)}.txt"

    def texto(self, chave: str) -> str:
        return _ler_texto(DADOS_TEXTOS / self.caminho(chave, self.manifesto[chave]))


class TestFixturesEmDia(unittest.TestCase):
    def test_gerador_reproduz_os_arquivos_versionados(self) -> None:
        with tempfile.TemporaryDirectory() as nome:
            destino = Path(nome)
            _gerador().gerar(destino)
            gerados = _arquivos(destino)
            _gerador().gerar(destino)  # idempotente: mesmos bytes ao gerar de novo
            regerados = _arquivos(destino)
        self.assertEqual(regerados, gerados)
        versionados = _arquivos(FIXTURES)
        self.assertEqual(sorted(versionados), sorted(gerados), COMANDO)
        for caminho, conteudo in gerados.items():
            with self.subTest(caminho=caminho):
                self.assertEqual(versionados[caminho], conteudo, COMANDO)


class TestManifesto(_Base):
    def test_formato_salvar_mapa(self) -> None:
        self.assertEqual(self.bruto, texto_mapa(self.manifesto).encode("utf-8"))
        self.assertNotIn(b"\r", self.bruto)

    def test_cobertura_dos_casos(self) -> None:
        status = [e["status"] for e in self.manifesto.values()]
        for s in ("ok", "ok_ocr", "ok_parcial", "vazio_legitimo", "removido", "pendente_download", "duplicata"):
            self.assertIn(s, status)
        self.assertEqual(status.count("removido"), 2)  # pela chave e pelo SHA-256
        self.assertTrue(any(len(e["documentos"]) == 2 for e in self.manifesto.values()))
        self.assertTrue(any(k.startswith("sessao:") for k in self.manifesto))

    def test_fila_e_documentos_citantes(self) -> None:
        self.assertEqual(set(self.manifesto), set(self.citacoes))
        self.assertTrue(self.fora_do_escopo)
        self.assertFalse(self.fora_do_escopo & set(self.manifesto))  # indicações e moções: fora
        canonicas = {e["duplicata_de"] for e in self.manifesto.values() if e["duplicata_de"]}
        for chave, e in self.manifesto.items():
            with self.subTest(chave=chave):
                esperado = set(self.citacoes[chave])
                if chave in canonicas:
                    for outra, d in self.manifesto.items():
                        if d["duplicata_de"] == chave:
                            esperado |= self.citacoes[outra]
                self.assertEqual(set(e["documentos"]), esperado)

    def test_chaves_campos_e_enumeracoes(self) -> None:
        for chave, e in self.manifesto.items():
            with self.subTest(chave=chave):
                self.assertRegex(chave, RE_CHAVE)
                self.assertEqual(set(e), CAMPOS)
                self.assertIn(e["tipo"], TIPOS - {"substitutivo"})  # o tipo é o do principal
                self.assertIn(e["status"], STATUS_MANIFESTO)
                self.assertTrue(e["url_origem"].startswith("https://"))
                if chave.startswith("sessao:"):
                    self.assertEqual(e["tipo"], "ata")
                    stem = e["url_origem"].rsplit("/", 1)[1].rsplit(".", 1)[0]
                    self.assertEqual(stem.lower(), chave.split(":", 1)[1])
                    self.assertEqual(e["url_origem"], self.urls[chave])
                else:
                    self.assertNotEqual(e["tipo"], "ata")
                    self.assertTrue(e["url_origem"].endswith(f"Download.aspx?id={chave.split(':', 1)[1]}"))

    def test_documentos_ordenados_e_principal(self) -> None:
        for chave, e in self.manifesto.items():
            with self.subTest(chave=chave):
                docs = e["documentos"]
                self.assertTrue(docs)
                self.assertEqual(docs, sorted(set(docs)))
                for d in docs:
                    self.assertRegex(d, RE_DOCUMENTO)
                self.assertEqual(e["documento"], self.principal(docs))
                self.assertEqual(e["tipo"], self.registros[e["documento"]]["tipo"])

    def test_pl_e_principal_dos_arquivos_dos_substitutivos(self) -> None:
        do_substitutivo = [e for e in self.manifesto.values()
                           if any(self.registros[d]["tipo"] == "substitutivo" for d in e["documentos"])]
        self.assertEqual(len(do_substitutivo), 2)
        so_substitutivo = [e for e in do_substitutivo if len(e["documentos"]) == 1]
        self.assertEqual(len(so_substitutivo), 1)
        for e in do_substitutivo:
            self.assertEqual(e["tipo"], "pl")
            self.assertEqual(self.registros[e["documento"]]["tipo"], "pl")
        e = so_substitutivo[0]
        self.assertNotIn(e["documento"], e["documentos"])
        self.assertEqual(self.registros[e["documentos"][0]]["pl"], e["documento"])

    def test_ano_do_manifesto_e_o_ano_do_registro(self) -> None:
        diverge = False
        for chave, e in self.manifesto.items():
            with self.subTest(chave=chave):
                registro = self.registros[e["documento"]]
                self.assertEqual(registro["ano"], 2024)
                diverge |= int(registro["data"][:4]) != registro["ano"]
        self.assertTrue(diverge, "a fixture precisa de um registro com data em outro ano")

    def test_remocoes(self) -> None:
        self.assertEqual(validar_remocoes(FIXTURES), [])
        remocoes.limpar_cache()
        itens = remocoes.carregar(FIXTURES)
        chaves = {i["chave"] for i in itens}
        shas = {i["sha256"] for i in itens}
        por_chave = por_sha = 0
        for chave, e in self.manifesto.items():
            with self.subTest(chave=chave):
                removido = remocoes.esta_removido(FIXTURES, chave, e["sha256_original"])
                self.assertEqual(removido, e["status"] == "removido")
                if not removido:
                    continue
                self.assertIsNone(e["r2_chave"])
                if chave in chaves:  # pela chave: nunca baixado
                    por_chave += 1
                    self.assertIsNone(e["sha256_original"])
                    self.assertIsNone(e["bytes"])
                else:  # pelo SHA-256: baixado, conferido e descartado
                    por_sha += 1
                    self.assertIn(e["sha256_original"], shas)
                    self.assertIsInstance(e["bytes"], int)
        self.assertEqual((por_chave, por_sha), (1, 1))

    def test_duplicatas(self) -> None:
        grupos: dict[str, list[str]] = {}
        for chave, e in self.manifesto.items():
            if e["status"] != "removido" and e["sha256_original"]:
                grupos.setdefault(e["sha256_original"], []).append(chave)
        self.assertTrue(any(len(g) > 1 for g in grupos.values()))
        for chaves in grupos.values():
            canonica = min(chaves, key=_ordem)
            with self.subTest(canonica=canonica):
                self.assertNotEqual(self.manifesto[canonica]["status"], "duplicata")
                self.assertIsNone(self.manifesto[canonica]["duplicata_de"])
                for outra in chaves:
                    if outra == canonica:
                        continue
                    d = self.manifesto[outra]
                    self.assertEqual((d["status"], d["duplicata_de"]), ("duplicata", canonica))
                    self.assertLessEqual(set(d["documentos"]), set(self.manifesto[canonica]["documentos"]))
                    self.assertEqual((d["trechos"], d["chars"], d["r2_chave"], d["sha256_texto"]), (0, 0, None, None))
        for e in self.manifesto.values():
            if e["status"] != "duplicata":
                self.assertIsNone(e["duplicata_de"])

    def test_datas_versoes_config_e_r2(self) -> None:
        sha_config = limpeza.hash_config_de(_gerador().LIBERADOS, _gerador().PESSOAS)
        for chave, e in self.manifesto.items():
            with self.subTest(chave=chave):
                self.assertRegex(e["processado_em"], RE_DATA)
                date.fromisoformat(e["processado_em"])
                if e["sha256_original"] is not None:
                    self.assertRegex(e["sha256_original"], RE_SHA)
                    self.assertIsInstance(e["bytes"], int)
                else:
                    self.assertIn(e["status"], ("removido", "pendente_download"))
                if e["status"] in SEM_PROCESSAMENTO:
                    self.assertIsNone(e["r2_chave"])
                    for campo in ("versao_extratores", "versao_limpeza", "versao_mascara", "versao_trechos",
                                  "sha256_config", "formato", "limpeza", "mascarados", "sha256_bruto",
                                  "sha256_texto", "blob_texto"):
                        self.assertIsNone(e[campo], campo)
                    continue
                s = e["sha256_original"]
                self.assertEqual(e["r2_chave"], f"sha256/{s[:2]}/{s[2:4]}/{s}")
                self.assertEqual(e["versao_extratores"], VERSAO_EXTRATORES)
                self.assertEqual(e["versao_limpeza"], limpeza.versao_efetiva(FIXTURES))
                self.assertRegex(e["versao_limpeza"], rf"^{re.escape(limpeza.VERSAO_LIMPEZA)}\+[0-9a-f]{{8}}$")
                self.assertEqual(e["versao_mascara"], mascara.VERSAO_MASCARA)
                self.assertEqual(e["versao_trechos"], trechos.VERSAO_TRECHOS)
                self.assertEqual(e["sha256_config"], sha_config)
                self.assertTrue(e["formato"])

    def test_versao_efetiva_acompanha_os_cliches(self) -> None:
        with tempfile.TemporaryDirectory() as nome:
            raiz = Path(nome)
            sem = limpeza.versao_efetiva(raiz)
            self.assertEqual(sem, f"{limpeza.VERSAO_LIMPEZA}+{_sha(b'')[:8]}")
            (raiz / "data" / "textos").mkdir(parents=True)
            (raiz / "data" / "textos" / "cliches.json").write_bytes(b'{\n"a b":5\n}\n')
            self.assertNotEqual(limpeza.versao_efetiva(raiz), sem)

    def test_hash_config_canonico(self) -> None:
        a = limpeza.hash_config_de(["b", "a", "a"], [("Y", "X"), "Z"])
        self.assertEqual(a, limpeza.hash_config_de(["a", "b"], ["Z", ("X", "Y", "X")]))
        self.assertNotEqual(a, limpeza.hash_config_de(["a"], [("Y", "X"), "Z"]))
        self.assertNotEqual(a, limpeza.hash_config_de(["a", "b"], [("Y", "X")]))
        self.assertRegex(limpeza.hash_config(RAIZ), RE_SHA)

    def test_ocr_e_confianca(self) -> None:
        for chave, e in self.manifesto.items():
            with self.subTest(chave=chave):
                c = e["confianca"]
                if c is not None:
                    self.assertIsInstance(c, float)
                    self.assertEqual(round(c, 1), c)
                    self.assertTrue(0 <= c <= 100)
                if e["status"] == "ok_ocr":
                    self.assertGreater(e["paginas_ocr"], 0)
                    self.assertGreaterEqual(c, CONFIANCA_MINIMA)
                if e["paginas_ocr"] == 0:
                    self.assertIsNone(c)
                self.assertLessEqual(e["paginas_ocr"], max(e["paginas"], 1))

    def test_limpeza_e_mascarados(self) -> None:
        for chave, e in self.manifesto.items():
            if not self.com_texto(e):
                continue
            with self.subTest(chave=chave):
                self.assertEqual(set(e["limpeza"]), {"linhas_removidas", "por_regra"})
                self.assertEqual(set(e["limpeza"]["por_regra"]), set(REGRAS))
                self.assertEqual(e["limpeza"]["linhas_removidas"], sum(e["limpeza"]["por_regra"].values()))
                self.assertEqual(set(e["mascarados"]), set(mascara.TIPOS))
                self.assertRegex(e["sha256_bruto"], RE_SHA)
        requerimento = next(e for e in self.manifesto.values()
                            if e["tipo"] == "requerimento" and e["status"] == "ok")
        self.assertEqual(requerimento["mascarados"]["cpf"], 1)  # CPF com espaço, do lote real


class TestTextosETrechos(_Base):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.txts = {p.relative_to(DADOS_TEXTOS).as_posix(): p for p in DADOS_TEXTOS.glob("textos/**/*.txt")}
        cls.trechos: dict[str, list[dict]] = {}
        cls.linhas: dict[str, list[str]] = {}
        for p in sorted(DADOS_TEXTOS.glob("trechos/*/*.jsonl")):
            rel = p.relative_to(DADOS_TEXTOS).as_posix()
            texto = p.read_bytes().decode("utf-8")
            cls.linhas[rel] = texto.split("\n")
            cls.trechos[rel] = [json.loads(linha) for linha in texto.splitlines()]

    def test_txt_existe_so_com_texto(self) -> None:
        esperados = {self.caminho(k, e) for k, e in self.manifesto.items() if self.com_texto(e)}
        self.assertEqual(set(self.txts), esperados)
        for chave, e in self.manifesto.items():
            if not self.com_texto(e):
                with self.subTest(chave=chave):
                    self.assertFalse(any(chave.replace(":", "-", 1) in c for c in self.txts))
                    self.assertEqual((e["chars"], e["trechos"], e["trechos_vetorizaveis"]), (0, 0, 0))
                    self.assertIsNone(e["sha256_texto"])
                    self.assertIsNone(e["blob_texto"])
                    self.assertFalse(any(t["arquivo"] == chave for ts in self.trechos.values() for t in ts))

    def test_txt_bytes_hash_e_blob(self) -> None:
        for chave, e in self.manifesto.items():
            if not self.com_texto(e):
                continue
            with self.subTest(chave=chave):
                bruto = self.txts[self.caminho(chave, e)].read_bytes()
                self.assertEqual(_sha(bruto), e["sha256_texto"])
                self.assertRegex(e["blob_texto"], RE_SHA1)
                self.assertEqual(hashlib.sha1(b"blob %d\0" % len(bruto) + bruto).hexdigest(), e["blob_texto"])
                conteudo = bruto.decode("utf-8")
                self.assertNotIn("\r", conteudo)
                self.assertFalse(conteudo.startswith("\ufeff"))
                self.assertTrue(conteudo.endswith("\n"))
                texto = conteudo[:-1]  # o leitor tira exatamente uma quebra final
                self.assertEqual(unicodedata.normalize("NFC", texto), texto)
                self.assertEqual(trechos.normalizar(texto), texto)
                self.assertEqual(len(texto), e["chars"])
                for linha in texto.split("\n"):
                    self.assertTrue("\f" not in linha or linha == "\f")
                lib = _gerador().LIBERADOS
                self.assertEqual([o for o in mascara.varrer(texto, lib) if o["forte"]], [])

    def test_esvaziado_pela_limpeza(self) -> None:
        vazios = [(k, e) for k, e in self.manifesto.items() if e["detalhe"] == ESVAZIADO]
        self.assertEqual(len(vazios), 1)
        chave, e = vazios[0]
        self.assertEqual((e["status"], e["chars"], e["trechos"]), ("vazio_legitimo", 0, 0))
        self.assertEqual(self.txts[self.caminho(chave, e)].read_bytes(), b"\n")
        self.assertGreater(e["limpeza"]["linhas_removidas"], 0)

    def test_ok_parcial_tem_texto_e_trechos(self) -> None:
        parciais = [(k, e) for k, e in self.manifesto.items() if e["status"] == "ok_parcial"]
        self.assertEqual(len(parciais), 1)
        chave, e = parciais[0]
        self.assertGreater(e["trechos"], 0)
        self.assertIn("\n\f\n", self.texto(chave) + "\n")

    def test_mascara_respeita_os_liberados(self) -> None:
        chave = next(k for k, e in self.manifesto.items()
                     if e["tipo"] == "pl" and e["formato"] == "docx" and len(e["documentos"]) == 2)
        texto = self.texto(chave)
        self.assertIn("(21) 2620-1234", texto)  # telefone liberado (gabinete)
        self.assertNotIn("98888-7777", texto)
        self.assertEqual(self.manifesto[chave]["mascarados"]["telefone"], 1)
        self.assertIn("Fulano Sintético", texto)  # nome protegido na limpeza

    def test_paginas_separadas_por_linha_com_form_feed(self) -> None:
        anexo = next(k for k, e in self.manifesto.items() if e["status"] == "ok_ocr")
        self.assertIn("\n\f\n", self.texto(anexo))

    def test_jsonl_ordem_campos_e_tipo(self) -> None:
        self.assertTrue(self.trechos)
        for rel, lista in self.trechos.items():
            with self.subTest(arquivo=rel):
                tipo, ano = rel.split("/")[1], rel.split("/")[2].removesuffix(".jsonl")
                self.assertEqual(ano, "2024")
                self.assertEqual(self.linhas[rel][-1], "")  # quebra final
                for linha, t in zip(self.linhas[rel], lista):
                    self.assertEqual(linha, json.dumps(t, ensure_ascii=False, sort_keys=True,
                                                       separators=(",", ":")))
                    self.assertEqual(set(t), CAMPOS_TRECHO)
                    self.assertEqual(self.manifesto[t["arquivo"]]["tipo"], tipo)
                chaves = [(t["documento"], t["arquivo"], t["posicao"]) for t in lista]
                self.assertEqual(chaves, sorted(chaves))
                self.assertEqual(len(set(t["id"] for t in lista)), len(lista))

    def test_offsets_hash_utf16_e_ids(self) -> None:
        astral = False
        for lista in self.trechos.values():
            for t in lista:
                with self.subTest(trecho=t["id"]):
                    e = self.manifesto[t["arquivo"]]
                    self.assertEqual(t["documento"], e["documento"])
                    self.assertRegex(t["id"], r"[0-9a-f]{16}")
                    texto = self.texto(t["arquivo"])
                    parte = texto[t["inicio"]:t["fim"]]
                    self.assertTrue(parte.strip())
                    self.assertEqual(_sha(parte.encode("utf-8")), t["sha256"])
                    self.assertEqual(trechos.texto_do_trecho(texto, t), parte)
                    utf16 = texto.encode("utf-16-le")
                    self.assertEqual(utf16[2 * t["inicio_utf16"]:2 * t["fim_utf16"]].decode("utf-16-le"), parte)
                    astral |= (t["inicio_utf16"], t["fim_utf16"]) != (t["inicio"], t["fim"])
                    ident = hashlib.sha1(f"{t['documento']}|{t['arquivo']}|{t['posicao']}|{t['sha256']}"
                                         .encode("utf-8")).hexdigest()[:16]
                    self.assertEqual(t["id"], ident)
                    self.assertEqual(t["vetorizavel"], trechos.vetorizavel(parte))
        self.assertTrue(astral, "a fixture precisa de um caractere fora do plano básico")

    def test_trechos_iguais_a_dividir_e_contagens(self) -> None:
        todos = [t for lista in self.trechos.values() for t in lista]
        for chave, e in self.manifesto.items():
            if not self.com_texto(e):
                continue
            with self.subTest(chave=chave):
                deste = sorted((t for t in todos if t["arquivo"] == chave), key=lambda t: t["posicao"])
                self.assertEqual(deste, trechos.dividir(self.texto(chave), e["documento"], chave))
                self.assertEqual([t["posicao"] for t in deste], list(range(len(deste))))
                self.assertEqual(len(deste), e["trechos"])
                self.assertEqual(sum(t["vetorizavel"] for t in deste), e["trechos_vetorizaveis"])
        self.assertGreater(max(e["trechos"] for e in self.manifesto.values()), 1)


class TestDocumentoDoContrato(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.texto = CONTRATO.read_text(encoding="utf-8")

    def test_menciona_campos_status_tabelas_e_versoes(self) -> None:
        nomes = (CAMPOS | CAMPOS_TRECHO | STATUS_MANIFESTO | set(TABELAS_D1) | set(REGRAS) | TIPOS
                 | set(mascara.TIPOS) | {"VERSAO_EXTRATORES", "VERSAO_LIMPEZA", "VERSAO_MASCARA", "VERSAO_TRECHOS",
                                         "sha256_manifestos", "pl", "hash_config", "versao_efetiva"})
        for nome in sorted(nomes):
            with self.subTest(nome=nome):
                self.assertIn(f"`{nome}`", self.texto)
        self.assertNotIn("commit_textos", self.texto)

    def test_sucesso_e_regras(self) -> None:
        for status in SUCESSO:
            self.assertIn(f"`{status}`", self.texto)
        for trecho in ("ementa:doc:", "mtime=0", ESVAZIADO, "confianca_paginas", "ROTULOS_ATA"):
            self.assertIn(trecho, self.texto)


if __name__ == "__main__":
    unittest.main()
