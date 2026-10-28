"""Testes de `coletor.textos` (pipeline do inteiro teor), offline.

A raiz de cada teste é montada a partir de `tests/fixtures/contratos/` (registros,
clichês e remoções); o download é um servidor falso em memória (e, para
`baixar_bytes`, um servidor HTTP local) e a extração devolve os resultados sintéticos
de `gerar_fixtures.py`. A primeira execução precisa reproduzir byte a byte o
manifesto e a árvore `dados-textos/` das fixtures do contrato.

Uso: python -m unittest tests.test_textos
"""
from __future__ import annotations

import contextlib
import copy
import http.server
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from coletor import arquivos, mascara, remocoes, siscam, textos
from coletor.extratores import VERSAO_EXTRATORES, Resultado

RAIZ = Path(__file__).resolve().parent.parent
FIXTURES = RAIZ / "tests" / "fixtures" / "contratos"
MANIFESTO = Path("data") / "textos" / "manifesto-2024.json"
HOJE = "2026-11-03"


def _gerador():
    spec = importlib.util.spec_from_file_location("gerar_fixtures_textos", FIXTURES / "gerar_fixtures.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


G = _gerador()
PENDENTE = f"sessao:{G.GUID_ATA_PENDENTE.lower()}"
ATA = f"sessao:{G.GUID_ATA}"


def _arquivos(pasta: Path) -> dict[str, bytes]:
    if not pasta.exists():
        return {}
    return {p.relative_to(pasta).as_posix(): p.read_bytes() for p in sorted(pasta.rglob("*"))
            if p.is_file() and ".git" not in p.relative_to(pasta).parts}


def _extracao(texto: str) -> dict:
    return {"formato": "docx", "extrator": "docx", "versao_extrator": VERSAO_EXTRATORES, "paginas": 0,
            "paginas_ocr": 0, "confianca": None, "confianca_paginas": {}, "status": "ok", "detalhe": "",
            "cabecalhos_omitidos": 0, "texto": texto}


TEXTO_NOVO = ("REQUERIMENTO Nº 902/2025\n\nRequer informações sintéticas sobre a iluminação das praças do "
              "bairro, com o cronograma de manutenção previsto para o exercício e a relação das equipes "
              "responsáveis pelo atendimento noturno.")


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.raiz, self.dir_textos, self.cache = base / "raiz", base / "dados-textos", base / "cache"
        for rel in ("data/proposicoes", "data/documentos", "data/sessoes"):
            shutil.copytree(FIXTURES / rel, self.raiz / rel)
        (self.raiz / "data" / "textos").mkdir(parents=True)
        shutil.copy2(FIXTURES / "data" / "textos" / "cliches.json", self.raiz / "data" / "textos" / "cliches.json")
        (self.raiz / "config").mkdir()
        shutil.copy2(FIXTURES / "config" / "remocoes.json", self.raiz / "config" / "remocoes.json")
        fila = textos.citacoes(G.PROPOSICOES, G.DOCUMENTOS, G.SESSOES)
        self.urls = {k: item["url"] for k, item in fila.items()}
        self.servidor = {self.urls[k]: v for k, v in G.ORIGINAIS.items() if v is not None}
        self.extracoes = {G.ORIGINAIS[k]: v for k, v in G.EXTRACOES.items()}
        self.baixados: list[str] = []
        self.extraidos: list[str] = []
        self.err = ""
        remocoes.limpar_cache()

    # ---- dependências falsas
    def baixar(self, url: str) -> bytes:
        self.baixados.append(url)
        if url not in self.servidor:
            raise RuntimeError("HTTP 404 sintético")
        return self.servidor[url]

    def extrair(self, dados: bytes, ocr: bool = False, cache_ocr=None) -> Resultado:
        self.extraidos.append(textos.sha256(dados))
        return Resultado(**copy.deepcopy(self.extracoes[dados]))

    def opcoes(self, **kw) -> textos.Opcoes:
        base = dict(raiz=self.raiz, textos=self.dir_textos, cache=self.cache, hoje=G.PROCESSADO_EM,
                    extrair=self.extrair, baixar=self.baixar, liberados=G.LIBERADOS, pessoas=G.PESSOAS,
                    max_arquivos=0, workers=2)
        base.update(kw)
        return textos.Opcoes(**base)

    def rodar(self, **kw) -> dict:
        saida = io.StringIO()
        try:
            with contextlib.redirect_stderr(saida):
                return textos.Pipeline(self.opcoes(**kw)).executar()
        finally:
            self.err = saida.getvalue()

    # ---- leitura
    def manifesto(self, ano: int = 2024) -> dict:
        caminho = self.raiz / "data" / "textos" / f"manifesto-{ano}.json"
        return json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else {}

    def salvar_manifesto(self, mapa: dict, ano: int = 2024) -> None:
        arquivos.salvar_mapa(self.raiz / "data" / "textos" / f"manifesto-{ano}.json", mapa)

    def saida(self) -> dict[str, bytes]:
        resultado = {f"raiz/{k}": v for k, v in _arquivos(self.raiz / "data" / "textos").items()}
        resultado.update(_arquivos(self.dir_textos))
        return resultado

    def assert_igual_as_fixtures(self) -> None:
        self.assertEqual((self.raiz / MANIFESTO).read_bytes(), (FIXTURES / MANIFESTO).read_bytes())
        self.assertEqual(sorted(p for p in (self.raiz / "data" / "textos").iterdir()),
                         sorted([self.raiz / MANIFESTO, self.raiz / "data" / "textos" / "cliches.json"]))
        gerados, esperados = _arquivos(self.dir_textos), _arquivos(FIXTURES / "dados-textos")
        self.assertEqual(sorted(gerados), sorted(esperados))
        for caminho, conteudo in esperados.items():
            with self.subTest(caminho=caminho):
                self.assertEqual(gerados[caminho], conteudo)

    def verificar(self, **kw) -> dict:
        with contextlib.redirect_stderr(io.StringIO()):
            return textos.verificar(self.raiz, self.dir_textos, self.cache, amostra=0, extrair=self.extrair, **kw)

    def acrescentar_documento(self, tipo: str, ano: int, registro: dict) -> None:
        caminho = self.raiz / "data" / "documentos" / tipo / f"{ano}.json"
        lista = json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else []
        arquivos.salvar_lista(caminho, [*lista, registro])


class TestContrato(_Base):
    def test_reproduz_as_fixtures_do_contrato(self) -> None:
        estat = self.rodar()
        self.assert_igual_as_fixtures()
        self.assertEqual(estat["bloqueados"], [])
        self.assertNotIn(self.urls["siscam:900004"], self.baixados)  # removido pela chave: nem baixa
        self.assertIn(self.urls["siscam:900007"], self.baixados)  # pelo SHA-256: baixado e descartado
        sha_removido = G.REMOCOES["remocoes"][0]["sha256"]
        self.assertFalse((self.cache / "arquivos" / sha_removido).exists())
        self.assertNotIn(textos.URL_DOWNLOAD.format(id=900009), self.baixados)  # indicação: fora
        self.assertEqual(len(self.extraidos), len(set(self.extraidos)))  # duplicata não é extraída de novo
        self.assertEqual(len(self.extraidos), 6)
        m = self.manifesto()
        self.assertNotIn("siscam:900009", m)
        self.assertEqual(m["siscam:900004"]["status"], "removido")
        self.assertIsNone(m["siscam:900004"]["sha256_original"])
        self.assertEqual((m["siscam:900007"]["status"], m["siscam:900007"]["sha256_original"]),
                         ("removido", sha_removido))

    def test_idempotente_com_processado_em_estavel(self) -> None:
        self.rodar()
        antes = self.saida()
        self.baixados.clear()
        self.extraidos.clear()
        self.rodar(hoje=HOJE)
        self.assertEqual(self.saida(), antes)
        self.assertEqual(self.extraidos, [])
        self.assertEqual(self.baixados, [self.urls[PENDENTE]])  # só a pendência é tentada de novo
        self.assertEqual({e["processado_em"] for e in self.manifesto().values()}, {G.PROCESSADO_EM})

    def test_arquivo_compartilhado_e_arquivo_so_do_substitutivo(self) -> None:
        self.rodar()
        m = self.manifesto()
        self.assertEqual(m["siscam:900001"]["documentos"], ["doc:127858", "doc:266596"])
        self.assertEqual((m["siscam:900001"]["documento"], m["siscam:900001"]["tipo"]), ("doc:127858", "pl"))
        e = m["siscam:900005"]
        self.assertEqual(e["documentos"], ["doc:266596"])
        self.assertEqual((e["documento"], e["tipo"]), ("doc:127858", "pl"))  # o PL, sem citar o arquivo
        self.assertTrue((self.dir_textos / "textos/pl/2024/127858/siscam-900005.txt").is_file())
        trechos_pl = (self.dir_textos / "trechos/pl/2024.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(sum(json.loads(t)["arquivo"] == "siscam:900001" for t in trechos_pl),
                         m["siscam:900001"]["trechos"])  # sem trechos duplicados pelo substitutivo

    def test_ata_com_chave_sessao(self) -> None:
        self.rodar()
        m = self.manifesto()
        self.assertEqual((m[ATA]["documento"], m[ATA]["tipo"], m[ATA]["status"]), ("sessao:5001", "ata", "ok"))
        self.assertEqual(m[PENDENTE]["status"], "pendente_download")
        self.assertIn(G.GUID_ATA_PENDENTE, m[PENDENTE]["url_origem"])  # URL como está, chave em minúsculas
        self.assertTrue((self.dir_textos / f"textos/ata/2024/5001/sessao-{G.GUID_ATA}.txt").is_file())

    def test_ok_parcial_mantem_o_texto_e_volta_com_ocr(self) -> None:
        self.rodar()
        m = self.manifesto()
        self.assertEqual(m["siscam:900005"]["status"], "ok_parcial")
        self.assertGreater(m["siscam:900005"]["trechos"], 0)
        self.extraidos.clear()
        self.rodar(hoje=HOJE)
        self.assertEqual(self.extraidos, [])
        self.rodar(hoje=HOJE, ocr=True)
        self.assertEqual(self.extraidos, [G.sha256(G.ORIGINAIS["siscam:900005"])])

    def test_texto_esvaziado_pela_limpeza(self) -> None:
        self.rodar()
        e = self.manifesto()["siscam:900006"]
        self.assertEqual((e["status"], e["detalhe"], e["chars"], e["trechos"]),
                         ("vazio_legitimo", textos.ESVAZIADO, 0, 0))
        self.assertEqual((self.dir_textos / "textos/pdl/2024/290005/siscam-900006.txt").read_bytes(), b"\n")


class TestFilaIncremental(_Base):
    def test_novo_documento_e_ano_do_registro(self) -> None:
        self.rodar()
        manifesto_2024 = (self.raiz / MANIFESTO).read_bytes()
        novo = b"PK\x03\x04 docx sintetico do requerimento novo"
        self.servidor[textos.URL_DOWNLOAD.format(id=900010)] = novo
        self.extracoes[novo] = _extracao(TEXTO_NOVO)
        self.acrescentar_documento("requerimento", 2025, {
            "ano": 2025, "arquivos": [G._arquivo(900010, "2024-12-30")], "data": "2024-12-30",
            "ementa": "Requer informações sintéticas sobre a iluminação das praças.", "id": 290010,
            "numero": "902/2025", "tipo": "requerimento"})
        self.baixados.clear()
        self.rodar(hoje=HOJE)
        self.assertEqual(sorted(self.baixados), sorted([textos.URL_DOWNLOAD.format(id=900010), self.urls[PENDENTE]]))
        self.assertEqual((self.raiz / MANIFESTO).read_bytes(), manifesto_2024)
        e = self.manifesto(2025)["siscam:900010"]  # ano do registro, não da data
        self.assertEqual((e["status"], e["documento"], e["processado_em"]), ("ok", "doc:290010", HOJE))
        self.assertTrue((self.dir_textos / "textos/requerimento/2025/290010/siscam-900010.txt").is_file())
        self.assertEqual(self.verificar()["falhas"], [])

    def test_max_arquivos(self) -> None:
        estat = self.rodar(max_arquivos=2)
        self.assertEqual((estat["trabalho"], estat["adiados_limite"]), (2, 7))
        self.assertEqual(set(self.manifesto()), {"siscam:900001", "siscam:900002", "siscam:900004"})
        self.assertEqual(self.verificar()["falhas"], [])
        estat = self.rodar(max_arquivos=0)  # 0 = sem limite
        self.assertEqual(estat["adiados_limite"], 0)
        self.assert_igual_as_fixtures()

    def test_sem_rede_sem_cache(self) -> None:
        self.rodar(sem_rede=True)
        self.assertEqual(self.baixados, [])
        m = self.manifesto()
        self.assertEqual(m["siscam:900004"]["status"], "removido")
        for chave, e in m.items():
            if chave != "siscam:900004":
                with self.subTest(chave=chave):
                    self.assertEqual(e["status"], "pendente_download")
                    self.assertIsNone(e["sha256_original"])
                    self.assertIsNone(e["r2_chave"])
        self.assertEqual(_arquivos(self.dir_textos / "textos"), {})

    def test_sem_rede_com_os_mapas_do_levantamento(self) -> None:
        pl, ata = G.ORIGINAIS["siscam:900001"], G.ORIGINAIS[ATA]
        for dados in (pl, ata):
            (self.cache / "arquivos").mkdir(parents=True, exist_ok=True)
            (self.cache / "arquivos" / G.sha256(dados)).write_bytes(dados)
        (self.cache / textos.MAPA_SISCAM).write_text(json.dumps({"900001": G.sha256(pl)}), encoding="utf-8")
        (self.cache / textos.MAPA_ATAS).write_text(json.dumps({self.urls[ATA]: G.sha256(ata)}), encoding="utf-8")
        self.rodar(sem_rede=True)
        self.assertEqual(self.baixados, [])
        m = self.manifesto()
        self.assertEqual((m["siscam:900001"]["status"], m[ATA]["status"]), ("ok", "ok"))
        self.assertEqual(m["siscam:900002"]["status"], "pendente_download")

    def test_duplicata_ganha_nova_canonica(self) -> None:
        self.rodar()
        m = self.manifesto()
        self.assertEqual((m["siscam:900008"]["status"], m["siscam:900008"]["duplicata_de"]),
                         ("duplicata", "siscam:900003"))
        self.assertEqual(m["siscam:900003"]["documentos"], ["doc:290001", "doc:290004"])
        self.servidor[textos.URL_DOWNLOAD.format(id=899999)] = G.ORIGINAL_REQ
        self.acrescentar_documento("requerimento", 2024, {
            "ano": 2024, "arquivos": [G._arquivo(899999, "2024-01-02")], "data": "2024-01-02",
            "ementa": "Requer cópia sintética do levantamento anterior sobre as praças.", "id": 290000,
            "numero": "1/2024", "tipo": "requerimento"})
        self.rodar(hoje=HOJE)
        m = self.manifesto()
        canonica = m["siscam:899999"]
        self.assertEqual(canonica["status"], "ok")
        self.assertEqual(canonica["documentos"], ["doc:290000", "doc:290001", "doc:290004"])
        self.assertEqual(canonica["documento"], "doc:290000")
        for chave in ("siscam:900003", "siscam:900008"):
            self.assertEqual((m[chave]["status"], m[chave]["duplicata_de"]), ("duplicata", "siscam:899999"))
        self.assertFalse((self.dir_textos / "textos/requerimento/2024/290001/siscam-900003.txt").exists())
        self.assertTrue((self.dir_textos / "textos/requerimento/2024/290000/siscam-899999.txt").is_file())
        self.assertEqual(self.verificar()["falhas"], [])

    def test_entrada_muda_de_manifesto_com_o_ano_do_principal(self) -> None:
        self.rodar()
        caminho = self.raiz / "data" / "proposicoes" / "2024.json"
        pls = json.loads(caminho.read_text(encoding="utf-8"))
        pls[0]["ano"] = 2025
        arquivos.salvar_lista(caminho, pls)
        self.rodar(hoje=HOJE)
        m2024, m2025 = self.manifesto(2024), self.manifesto(2025)
        self.assertEqual(set(m2025), {"siscam:900001", "siscam:900002", "siscam:900005"})
        self.assertFalse(set(m2025) & set(m2024))
        self.assertFalse((self.dir_textos / "textos/pl/2024").exists())
        self.assertFalse((self.dir_textos / "trechos/pl/2024.jsonl").exists())
        self.assertTrue((self.dir_textos / "textos/pl/2025/127858/siscam-900001.txt").is_file())
        self.assertEqual(self.verificar()["falhas"], [])


class TestReprocessamento(_Base):
    def test_por_versao(self) -> None:
        self.rodar()
        m = self.manifesto()
        m["siscam:900001"]["versao_mascara"] = "0"
        self.salvar_manifesto(m)
        self.extraidos.clear()
        self.rodar(hoje=HOJE)  # sem --reprocessar-versao: fica como está
        self.assertEqual(self.extraidos, [])
        self.assertEqual(self.manifesto()["siscam:900001"]["versao_mascara"], "0")
        self.rodar(hoje=HOJE, reprocessar_versao=True)
        self.assertEqual(self.extraidos, [G.sha256(G.ORIGINAIS["siscam:900001"])])
        m = self.manifesto()
        self.assertEqual(m["siscam:900001"]["versao_mascara"], mascara.VERSAO_MASCARA)
        self.assertEqual(m["siscam:900001"]["processado_em"], HOJE)
        self.assertEqual(m["siscam:900002"]["processado_em"], G.PROCESSADO_EM)

    def test_por_configuracao(self) -> None:
        self.rodar()
        antigo = self.manifesto()["siscam:900001"]["sha256_config"]
        self.extraidos.clear()
        estat = self.rodar(hoje=HOJE, liberados=G.LIBERADOS - {"2126201234"})
        self.assertTrue(estat["config_mudou"])
        self.assertEqual(len(self.extraidos), 6)  # todas as entradas com texto, sem esperar a versão
        m = self.manifesto()
        for chave, e in m.items():
            if e["sha256_config"] is not None:
                with self.subTest(chave=chave):
                    self.assertNotEqual(e["sha256_config"], antigo)
                    self.assertEqual(e["processado_em"], HOJE)
        texto = (self.dir_textos / "textos/pl/2024/127858/siscam-900001.txt").read_text(encoding="utf-8")
        self.assertNotIn("2620-1234", texto)

    def test_novo_sha_para_o_mesmo_id(self) -> None:
        self.rodar()
        m = self.manifesto()
        antigo = m["siscam:900002"]["r2_chave"]
        m["siscam:900002"]["versao_extratores"] = "0"
        self.salvar_manifesto(m)
        novo = b"%PDF-1.7 anexo sintetico, segunda versao publicada"
        self.servidor[self.urls["siscam:900002"]] = novo
        self.extracoes[novo] = G.EXTRACOES["siscam:900002"]
        self.rodar(hoje=HOJE, cache=self.cache.parent / "cache-vazio", reprocessar_versao=True)
        e = self.manifesto()["siscam:900002"]
        self.assertEqual(e["sha256_original"], G.sha256(novo))
        self.assertEqual(e["r2_chave"], textos.r2_chave(G.sha256(novo)))
        self.assertNotEqual(e["r2_chave"], antigo)
        self.assertEqual(e["processado_em"], HOJE)


class TestInterrupcao(_Base):
    def test_gravacao_parcial_coerente_e_retomada(self) -> None:
        chamadas: list[int] = []

        def extrair(dados, ocr=False, cache_ocr=None):
            chamadas.append(1)
            if len(chamadas) == 3:
                raise KeyboardInterrupt("simulado")
            return self.extrair(dados, ocr=ocr, cache_ocr=cache_ocr)

        with self.assertRaises(KeyboardInterrupt):
            self.rodar(extrair=extrair, workers=1)
        self.assertEqual(set(self.manifesto()), {"siscam:900001", "siscam:900002"})
        self.assertEqual(self.verificar()["falhas"], [])
        self.rodar()
        self.assert_igual_as_fixtures()


class TestBarreira(_Base):
    def test_texto_com_ocorrencia_forte_nao_e_gravado(self) -> None:
        def sem_mascara(texto, liberados=frozenset()):
            return texto, {tipo: 0 for tipo in mascara.TIPOS}

        with mock.patch.object(mascara, "mascarar", sem_mascara):
            estat = self.rodar()
        chaves = {b["chave"] for b in estat["bloqueados"]}
        self.assertIn("siscam:900003", chaves)
        m = self.manifesto()
        self.assertNotIn("siscam:900003", m)
        self.assertNotIn("siscam:900008", m)  # o grupo de duplicatas não entra pela metade
        self.assertFalse((self.dir_textos / "textos/requerimento").exists())
        self.assertNotIn("789-09", self.err)
        self.assertNotIn("denise", self.err.lower())


@unittest.skipIf(shutil.which("git") is None, "git indisponível")
class TestCommitTextos(_Base):
    def setUp(self) -> None:
        super().setUp()
        self.dir_textos.mkdir()
        self.git("init", "-q")
        for chave, valor in (("user.name", "Teste"), ("user.email", "teste@example.invalid"),
                             ("commit.gpgsign", "false"), ("core.autocrlf", "false")):
            self.git("config", chave, valor)
        (self.dir_textos / "README.md").write_bytes(b"dados-textos\n")
        self.git("add", "README.md")
        self.git("commit", "-q", "-m", "Inicial")

    def git(self, *args: str) -> str:
        return subprocess.run(["git", "-C", str(self.dir_textos), *args], capture_output=True, check=True,
                              ).stdout.decode("utf-8")

    def commit(self, todos: bool = False) -> tuple[int, str]:
        saida = io.StringIO()
        with contextlib.redirect_stderr(saida):
            codigo = textos.commit_textos(self.dir_textos, G.LIBERADOS, todos=todos)
        return codigo, saida.getvalue()

    def test_commit_com_textos_limpos(self) -> None:
        self.rodar()
        codigo, _ = self.commit(todos=True)
        self.assertEqual(codigo, 0)
        self.assertEqual(self.git("log", "-1", "--format=%s").strip(), "Atualiza textos extraídos (6 arquivos)")
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(self.commit(), (0, "dados-textos: nada a commitar\n"))

    def test_barreira_aborta_o_commit(self) -> None:
        self.rodar()
        alvo = self.dir_textos / "textos/pl/2024/127858/siscam-900002.txt"
        alvo.write_bytes(alvo.read_bytes() + b"Contato do titular: CPF 529.982.247-25\n")
        codigo, err = self.commit()
        self.assertEqual(codigo, 1)
        self.assertEqual(self.git("rev-list", "--count", "HEAD").strip(), "1")
        self.assertIn("siscam:900002", err)
        self.assertIn("cpf", err)
        self.assertNotIn("529.982", err)
        self.assertNotIn("247-25", err)


class TestVerificar(_Base):
    def test_detecta_adulteracao_e_nao_comparavel(self) -> None:
        self.rodar()
        rel = self.verificar()
        self.assertEqual((rel["falhas"], rel["nao_comparaveis"], rel["reextraidos"]), ([], [], 6))
        alvo = self.dir_textos / "textos/requerimento/2024/290001/siscam-900003.txt"
        alvo.write_bytes(alvo.read_bytes() + b"x")
        m = self.manifesto()
        m["siscam:900001"]["versao_extrator"] = "0"
        self.salvar_manifesto(m)
        rel = self.verificar()
        self.assertEqual([f["chave"] for f in rel["falhas"]], ["siscam:900003"])
        self.assertIn("adulterado", rel["falhas"][0]["motivo"])
        self.assertEqual(rel["nao_comparaveis"], ["siscam:900001"])

    def test_detecta_trechos_alterados(self) -> None:
        self.rodar()
        caminho = self.dir_textos / "trechos/ata/2024.jsonl"
        linhas = caminho.read_text(encoding="utf-8").splitlines()
        t = json.loads(linhas[0])
        t["fim"] -= 1
        linhas[0] = textos.linha_trecho(t)
        caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8", newline="\n")
        self.assertEqual([f["chave"] for f in self.verificar()["falhas"]], [ATA])


class TestRegrasPuras(unittest.TestCase):
    def test_ordem_e_chave_da_ata(self) -> None:
        chaves = ["sessao:b", "siscam:10", "siscam:9", "sessao:a"]
        self.assertEqual(sorted(chaves, key=textos.ordem_chave), ["siscam:9", "siscam:10", "sessao:a", "sessao:b"])
        url = "https://consultaniteroi.siscam.com.br/Arquivos/Sessoes/0000000A-0000-4000-8000-0000000000B2.pdf"
        self.assertEqual(textos.chave_ata(url), "sessao:0000000a-0000-4000-8000-0000000000b2")
        self.assertIsNone(textos.chave_ata("https://consultaniteroi.siscam.com.br/Arquivos/Sessoes/ata.pdf"))

    def test_fila_sem_indicacoes_e_mocoes(self) -> None:
        documentos = {**G.DOCUMENTOS, "mocao": [{"ano": 2024, "arquivos": [G._arquivo(900011, "2024-01-01")],
                                                 "ementa": "", "id": 290011, "tipo": "mocao"}]}
        fila = textos.citacoes(G.PROPOSICOES, documentos, G.SESSOES)
        self.assertNotIn("siscam:900009", fila)
        self.assertNotIn("siscam:900011", fila)
        self.assertIn(ATA, fila)

    def test_chaves_dos_mapas_do_levantamento(self) -> None:
        self.assertEqual(textos._chave_legada("123", "siscam"), "siscam:123")
        self.assertEqual(textos._chave_legada("https://x/Download.aspx?id=77", "siscam"), "siscam:77")
        self.assertIsNone(textos._chave_legada("5001", "sessao"))
        self.assertEqual(textos._chave_legada("A1B2C3D4-0000-4000-8000-0000000000AA.docx", "sessao"),
                         "sessao:a1b2c3d4-0000-4000-8000-0000000000aa")

    def test_processado_em(self) -> None:
        anterior = {c: "x" for c in textos.CAMPOS_PROCESSADO_EM} | {"processado_em": "2026-01-01", "chars": 1}
        self.assertEqual(textos.processado_em(dict(anterior, chars=2), anterior, HOJE), "2026-01-01")
        self.assertEqual(textos.processado_em(dict(anterior, status="y"), anterior, HOJE), HOJE)
        self.assertEqual(textos.processado_em(anterior, None, HOJE), HOJE)

    def test_cli_rejeita_tipo_fora_do_escopo(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            textos.main(["--tipos", "indicacao"])


class TestBaixarBytes(unittest.TestCase):
    def test_servidor_local_binario_tentativas_e_user_agent(self) -> None:
        corpo = b"\x00\xff binario \r\n\x1a"
        pedidos: list[tuple[str, str]] = []

        class Tratador(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                pedidos.append((self.path, self.headers.get("User-Agent")))
                if self.path == "/ok":
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(corpo)))
                    self.end_headers()
                    self.wfile.write(corpo)
                else:
                    self.send_error(500 if self.path == "/erro" else 404)

            def log_message(self, *args) -> None:
                pass

        servidor = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Tratador)
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
        self.addCleanup(servidor.server_close)
        self.addCleanup(servidor.shutdown)
        base = f"http://127.0.0.1:{servidor.server_address[1]}"
        with mock.patch.dict(os.environ, {"no_proxy": "*", "NO_PROXY": "*"}):
            self.assertEqual(textos.baixar_bytes(base + "/ok", espera=0), corpo)
            with self.assertRaises(RuntimeError):
                textos.baixar_bytes(base + "/nada", tentativas=3, espera=0)
            with self.assertRaises(RuntimeError):
                textos.baixar_bytes(base + "/erro", tentativas=2, espera=0)
        self.assertEqual([p for p, _ in pedidos], ["/ok", "/nada", "/erro", "/erro"])  # 404 não repete
        self.assertEqual({ua for _, ua in pedidos}, {siscam.USER_AGENT})


if __name__ == "__main__":
    unittest.main()
