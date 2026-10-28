"""Fixtures do contrato de textos (`docs/contratos/textos.md`).

As fixtures em `tests/fixtures/contratos/` são geradas por
`tests/fixtures/contratos/gerar_fixtures.py`; aqui elas são geradas de novo numa
pasta temporária e comparadas byte a byte, e depois conferidas contra o contrato.

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
from coletor.extratores import CONFIANCA_MINIMA, STATUS, VERSAO_EXTRATORES
from coletor.validar import validar_remocoes

RAIZ = Path(__file__).resolve().parent.parent
FIXTURES = RAIZ / "tests" / "fixtures" / "contratos"
DADOS_TEXTOS = FIXTURES / "dados-textos"
CONTRATO = RAIZ / "docs" / "contratos" / "textos.md"

CAMPOS = {
    "documentos", "documento", "tipo", "url_origem", "sha256_original", "bytes", "formato", "extrator",
    "versao_extrator", "versao_extratores", "versao_limpeza", "versao_mascara", "versao_trechos",
    "paginas", "paginas_ocr", "confianca", "cabecalhos_omitidos", "detalhe", "status", "limpeza",
    "mascarados", "sha256_bruto", "sha256_texto", "chars", "trechos", "trechos_vetorizaveis",
    "r2_chave", "commit_textos", "processado_em",
}
CAMPOS_TRECHO = {"id", "documento", "arquivo", "posicao", "inicio", "fim", "inicio_utf16", "fim_utf16",
                 "sha256", "vetorizavel"}
TIPOS = {"pl", "substitutivo", "requerimento", "pdl", "resolucao", "ata"}
STATUS_MANIFESTO = set(STATUS) | {"removido", "pendente_download"}
STATUS_COM_TEXTO = {"ok", "ok_ocr", "ocr_baixa_confianca"}
SUCESSO = {"ok", "ok_ocr", "vazio_legitimo"}
REGRAS = ("cabecalho_rodape", "numeracao", "ruido_ocr", "cliche")
TABELAS_D1 = ("documentos", "autoria", "pessoas", "arquivos", "arquivo_documento", "trechos",
              "trechos_fts", "trechos_indexados", "remocoes", "estado_indice", "verificacoes")
RE_CHAVE = re.compile(r"(?:siscam:[1-9][0-9]*|sessao:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")
RE_DOCUMENTO = re.compile(r"(?:doc|sessao):[1-9][0-9]*")
RE_SHA = re.compile(r"[0-9a-f]{64}")
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
        self.assertEqual(sorted(versionados), sorted(gerados),
                         "rode: python tests/fixtures/contratos/gerar_fixtures.py")
        for caminho, conteudo in gerados.items():
            with self.subTest(caminho=caminho):
                self.assertEqual(versionados[caminho], conteudo,
                                 "rode: python tests/fixtures/contratos/gerar_fixtures.py")


class TestManifesto(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bruto = (FIXTURES / "manifesto-2024.json").read_bytes()
        cls.manifesto = json.loads(cls.bruto.decode("utf-8"))
        cls.registros = json.loads((FIXTURES / "registros.json").read_text(encoding="utf-8"))

    def test_formato_salvar_mapa(self) -> None:
        from coletor.arquivos import texto_mapa
        self.assertEqual(self.bruto, texto_mapa(self.manifesto).encode("utf-8"))
        self.assertNotIn(b"\r", self.bruto)

    def test_cobertura_dos_casos(self) -> None:
        m = self.manifesto
        self.assertEqual(len(m), 5)
        self.assertEqual(sum(e["tipo"] == "pl" and e["documento"] == "doc:127858" for e in m.values()), 2)
        self.assertTrue(any(e["status"] == "ok_ocr" for e in m.values()))
        self.assertTrue(any(len(e["documentos"]) == 2 for e in m.values()))
        self.assertTrue(any(k.startswith("sessao:") and e["tipo"] == "ata" for k, e in m.items()))
        self.assertTrue(any(e["status"] == "removido" for e in m.values()))
        self.assertTrue(any(e["tipo"] == "requerimento" for e in m.values()))

    def test_chaves_campos_e_enumeracoes(self) -> None:
        for chave, e in self.manifesto.items():
            with self.subTest(chave=chave):
                self.assertRegex(chave, RE_CHAVE)
                self.assertEqual(set(e), CAMPOS)
                self.assertIn(e["tipo"], TIPOS)
                self.assertIn(e["status"], STATUS_MANIFESTO)
                if chave.startswith("sessao:"):
                    self.assertEqual(e["tipo"], "ata")
                    guid = chave.split(":", 1)[1]
                    self.assertEqual(e["url_origem"].rsplit("/", 1)[1].rsplit(".", 1)[0].lower(), guid)
                else:
                    self.assertNotEqual(e["tipo"], "ata")
                    self.assertTrue(e["url_origem"].endswith(f"Download.aspx?id={chave.split(':', 1)[1]}"))
                self.assertTrue(e["url_origem"].startswith("https://"))

    def test_documentos_ordenados_e_principal(self) -> None:
        for chave, e in self.manifesto.items():
            with self.subTest(chave=chave):
                docs = e["documentos"]
                self.assertTrue(docs)
                self.assertEqual(docs, sorted(set(docs)))
                for d in docs:
                    self.assertRegex(d, RE_DOCUMENTO)
                self.assertIn(e["documento"], docs)
                self.assertEqual(self.registros[e["documento"]]["tipo"], e["tipo"])
                if e["tipo"] == "ata":
                    self.assertTrue(all(d.startswith("sessao:") for d in docs))
                else:
                    self.assertTrue(all(d.startswith("doc:") for d in docs))

    def test_compartilhado_tem_o_pl_como_principal(self) -> None:
        compartilhados = [e for e in self.manifesto.values() if len(e["documentos"]) > 1]
        self.assertEqual(len(compartilhados), 1)
        e = compartilhados[0]
        tipos = {self.registros[d]["tipo"] for d in e["documentos"]}
        self.assertEqual(tipos, {"pl", "substitutivo"})
        self.assertEqual(self.registros[e["documento"]]["tipo"], "pl")
        for d in e["documentos"]:
            if self.registros[d]["tipo"] == "substitutivo":
                self.assertEqual(self.registros[d]["pl"], e["documento"])

    def test_ano_do_manifesto_e_o_ano_do_registro(self) -> None:
        diverge = False
        for chave, e in self.manifesto.items():
            with self.subTest(chave=chave):
                registro = self.registros[e["documento"]]
                self.assertEqual(registro["ano"], 2024)
                diverge |= int(registro["data"][:4]) != registro["ano"]
        self.assertTrue(diverge, "a fixture precisa de um registro com data em outro ano")

    def test_datas_versoes_e_r2(self) -> None:
        for chave, e in self.manifesto.items():
            with self.subTest(chave=chave):
                self.assertRegex(e["processado_em"], RE_DATA)
                date.fromisoformat(e["processado_em"])
                self.assertIsNone(e["commit_textos"])
                self.assertIsInstance(e["bytes"], int)
                self.assertRegex(e["sha256_original"], RE_SHA)
                if e["status"] in ("removido", "pendente_download"):
                    self.assertIsNone(e["r2_chave"])
                    for campo in ("versao_extratores", "versao_limpeza", "versao_mascara", "versao_trechos",
                                  "formato", "limpeza", "mascarados", "sha256_bruto", "sha256_texto"):
                        self.assertIsNone(e[campo], campo)
                    continue
                s = e["sha256_original"]
                self.assertEqual(e["r2_chave"], f"sha256/{s[:2]}/{s[2:4]}/{s}")
                self.assertEqual(e["versao_extratores"], VERSAO_EXTRATORES)
                self.assertEqual(e["versao_limpeza"], limpeza.VERSAO_LIMPEZA)
                self.assertEqual(e["versao_mascara"], mascara.VERSAO_MASCARA)
                self.assertEqual(e["versao_trechos"], trechos.VERSAO_TRECHOS)
                self.assertTrue(e["formato"])

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
            if e["status"] not in STATUS_COM_TEXTO:
                continue
            with self.subTest(chave=chave):
                self.assertEqual(set(e["limpeza"]), {"linhas_removidas", "por_regra"})
                self.assertEqual(set(e["limpeza"]["por_regra"]), set(REGRAS))
                self.assertEqual(e["limpeza"]["linhas_removidas"], sum(e["limpeza"]["por_regra"].values()))
                self.assertEqual(set(e["mascarados"]), set(mascara.TIPOS))
                self.assertRegex(e["sha256_bruto"], RE_SHA)
        requerimento = next(e for e in self.manifesto.values() if e["tipo"] == "requerimento")
        self.assertEqual(requerimento["mascarados"]["cpf"], 1)  # CPF com espaço, do lote real
        self.assertGreater(sum(e["limpeza"]["linhas_removidas"] for e in self.manifesto.values()
                               if e["limpeza"]), 0)


class TestTextosETrechos(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifesto = json.loads((FIXTURES / "manifesto-2024.json").read_text(encoding="utf-8"))
        cls.txts = {p.relative_to(DADOS_TEXTOS).as_posix(): p for p in DADOS_TEXTOS.glob("textos/**/*.txt")}
        cls.trechos: dict[str, list[dict]] = {}
        cls.linhas: dict[str, list[str]] = {}
        for p in sorted(DADOS_TEXTOS.glob("trechos/*/*.jsonl")):
            rel = p.relative_to(DADOS_TEXTOS).as_posix()
            texto = p.read_bytes().decode("utf-8")
            cls.linhas[rel] = texto.split("\n")
            cls.trechos[rel] = [json.loads(linha) for linha in texto.splitlines()]

    @staticmethod
    def caminho(chave: str, e: dict) -> str:
        doc = e["documento"].split(":", 1)[1]
        return f"textos/{e['tipo']}/2024/{doc}/{chave.replace(':', '-', 1)}.txt"

    def texto(self, chave: str) -> str:
        e = self.manifesto[chave]
        return self.txts[self.caminho(chave, e)].read_bytes().decode("utf-8")[:-1]

    def test_txt_existe_so_com_texto(self) -> None:
        esperados = {self.caminho(k, e) for k, e in self.manifesto.items() if e["status"] in STATUS_COM_TEXTO}
        self.assertEqual(set(self.txts), esperados)
        for chave, e in self.manifesto.items():
            if e["status"] == "removido":
                self.assertFalse(any(chave.replace(":", "-", 1) in c for c in self.txts))
                self.assertEqual((e["chars"], e["trechos"], e["trechos_vetorizaveis"]), (0, 0, 0))
                self.assertFalse(any(t["arquivo"] == chave for ts in self.trechos.values() for t in ts))

    def test_txt_bytes_e_hash(self) -> None:
        for chave, e in self.manifesto.items():
            if e["status"] not in STATUS_COM_TEXTO:
                continue
            with self.subTest(chave=chave):
                bruto = self.txts[self.caminho(chave, e)].read_bytes()
                self.assertEqual(_sha(bruto), e["sha256_texto"])
                conteudo = bruto.decode("utf-8")
                self.assertNotIn("\r", conteudo)
                self.assertTrue(conteudo.endswith("\n") and not conteudo.endswith("\n\n"))
                texto = conteudo[:-1]
                self.assertEqual(unicodedata.normalize("NFC", texto), texto)
                self.assertEqual(trechos.normalizar(texto), texto)
                self.assertEqual(len(texto), e["chars"])
                for linha in texto.split("\n"):
                    self.assertTrue("\f" not in linha or linha == "\f")
                self.assertEqual([o for o in mascara.varrer(texto) if o["forte"]], [])

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
            if e["status"] not in STATUS_COM_TEXTO:
                continue
            with self.subTest(chave=chave):
                deste = sorted((t for t in todos if t["arquivo"] == chave), key=lambda t: t["posicao"])
                self.assertEqual(deste, trechos.dividir(self.texto(chave), e["documento"], chave))
                self.assertEqual([t["posicao"] for t in deste], list(range(len(deste))))
                self.assertEqual(len(deste), e["trechos"])
                self.assertEqual(sum(t["vetorizavel"] for t in deste), e["trechos_vetorizaveis"])
        self.assertGreater(max(e["trechos"] for e in self.manifesto.values()), 1)


class TestRemocoesDasFixtures(unittest.TestCase):
    def setUp(self) -> None:
        remocoes.limpar_cache()

    def test_exemplo_valido_e_aplicado(self) -> None:
        self.assertEqual(validar_remocoes(FIXTURES), [])
        manifesto = json.loads((FIXTURES / "manifesto-2024.json").read_text(encoding="utf-8"))
        for chave, e in manifesto.items():
            with self.subTest(chave=chave):
                removido = remocoes.esta_removido(FIXTURES, chave, e["sha256_original"])
                self.assertEqual(removido, e["status"] == "removido")
                if removido:
                    self.assertIn((chave, e["sha256_original"]), remocoes.chaves_removidas(FIXTURES))


class TestDocumentoDoContrato(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.texto = CONTRATO.read_text(encoding="utf-8")

    def test_menciona_campos_status_tabelas_e_versoes(self) -> None:
        nomes = (CAMPOS | CAMPOS_TRECHO | STATUS_MANIFESTO | set(TABELAS_D1) | set(REGRAS) | TIPOS
                 | set(mascara.TIPOS) | {"VERSAO_EXTRATORES", "VERSAO_LIMPEZA", "VERSAO_MASCARA", "VERSAO_TRECHOS"})
        for nome in sorted(nomes):
            with self.subTest(nome=nome):
                self.assertIn(f"`{nome}`", self.texto)

    def test_sucesso(self) -> None:
        for status in SUCESSO:
            self.assertIn(f"`{status}`", self.texto)
        self.assertIn("ementa:doc:", self.texto)
        self.assertIn("mtime=0", self.texto)


if __name__ == "__main__":
    unittest.main()
