"""Correções da QA da Phase 2.2: FTS atômico, vetores órfãos, R2 por REST, login OAuth, etapas e limites.

Tudo offline: SQLite local, pastas no lugar de R2 e Vectorize e servidores HTTP falsos em 127.0.0.1.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from coletor.nuvem import banco, cloudflare
from coletor.nuvem import __main__ as cli
from coletor.nuvem.ambientes import BUCKET_ARQUIVOS_LOCAL, BUCKET_EXPORTACOES_LOCAL, ambiente_remoto, credencial_remota
from coletor.nuvem.banco import COLUNAS, BancoLocal, BancoRemoto, fts_divergente, ler_tabela
from coletor.nuvem.cloudflare import Cloudflare, Vectorize
from coletor.nuvem.credenciais import ORIGEM_OAUTH, Credencial, credencial_do_ambiente
from coletor.nuvem.fonte import normalizar_busca, rowid_fts, sha_indexado
from coletor.nuvem.local import MODELO_LOCAL, R2Local, VetoresLocal, embeddings_falsos
from coletor.nuvem.r2 import R2, R2Rest
from coletor.nuvem.rede import ErroNuvem, Ritmo
from coletor.nuvem.sincronizar import (FOLGA_RELOGIO, PENDENTE, TRABALHADORES_R2, Ambiente, ErroBarreira,
                                       documentos_meta, etapas_validas, sincronizar)
from coletor.nuvem.wrangler import VERSAO_WRANGLER, Wrangler, listar_vetores, npx, prefixo
from tests.test_nuvem_cloudflare import TOKEN, Servidor, ok
from tests.test_nuvem_sincronizar import AGORA, COMMIT, FIXTURES, SHA_900002, SHA_900005, G
from tests.test_nuvem_sincronizar import Base as BaseSincronizacao

RAIZ = Path(__file__).resolve().parents[1]
TRECHO_900002 = "f23d327591e03053"


def _ids(consultar, tabela: str) -> set[str]:
    return {r[0] for r in consultar(f"SELECT id FROM {tabela}")}


# ---------------------------------------------------------------- D1 falso com lotes atômicos
class D1Sqlite:
    """D1 sobre um SQLite: parâmetros como texto e cada grupo de `lote_unidades` atômico; o grupo
    número `falhar_em` (contado desde o início) é recusado sem aplicar nada."""

    def __init__(self, caminho: Path, max_instrucoes: int = 3) -> None:
        self.con = sqlite3.connect(caminho, isolation_level=None)
        self.con.row_factory = sqlite3.Row
        self.max_instrucoes = max_instrucoes
        self.falhar_em: int | None = None
        self.grupos = 0

    def consultar(self, sql, params=()):
        cloudflare.validar_instrucao(sql, params)
        return [dict(r) for r in self.con.execute(sql, [cloudflare.parametro_d1(p) for p in params])]

    def lote_unidades(self, unidades):
        for grupo in cloudflare.dividir_unidades(unidades, self.max_instrucoes):
            self.grupos += 1
            if self.falhar_em == self.grupos:
                raise ErroNuvem("lote recusado (simulado)", 500)
            self.con.execute("BEGIN")
            try:
                for sql, params in grupo:
                    self.con.execute(sql, [cloudflare.parametro_d1(p) for p in params])
            except BaseException:
                self.con.execute("ROLLBACK")
                raise
            self.con.execute("COMMIT")


class TestFtsAtomico(BaseSincronizacao):
    def setUp(self):
        super().setUp()
        original = banco.BYTES_UNIDADE_TRECHOS
        banco.BYTES_UNIDADE_TRECHOS = 1  # um trecho por unidade: vários lotes com trechos
        self.addCleanup(setattr, banco, "BYTES_UNIDADE_TRECHOS", original)

    def novo_d1(self, nome: str) -> D1Sqlite:
        pasta = self.tmp / nome
        pasta.mkdir()
        d1 = D1Sqlite(pasta / "d1.sqlite")
        d1.con.executescript((banco.PASTA_MIGRACOES / "0001_inicial.sql").read_text(encoding="utf-8"))
        d1.con.executescript("CREATE TABLE d1_migrations (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, "
                             "applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL);"
                             "INSERT INTO d1_migrations (name) VALUES ('0001_inicial.sql');")
        self.addCleanup(d1.con.close)
        d1.pasta = pasta
        return d1

    def rodar(self, d1: D1Sqlite):
        remoto = BancoRemoto(d1, "teste", comando_npx="npx", limiar_arquivo=10 ** 6, pasta_worker=d1.pasta)
        ambiente = Ambiente("teste", remoto, R2Local(d1.pasta / "r2"), BUCKET_ARQUIVOS_LOCAL,
                            BUCKET_EXPORTACOES_LOCAL, VetoresLocal(d1.pasta / "vetores.jsonl"), embeddings_falsos,
                            MODELO_LOCAL)
        from coletor import remocoes
        remocoes.limpar_cache()
        return sincronizar(self.raiz, self.textos, ambiente, cache=self.cache, commit=COMMIT,
                           liberados=G.LIBERADOS, agora=lambda: AGORA), remoto

    def conferir_fts(self, d1: D1Sqlite):
        trechos = {r["id"] for r in d1.consultar("SELECT id FROM trechos")}
        fts = {(r["rowid"], r["id"]) for r in d1.consultar("SELECT rowid, id FROM trechos_fts")}
        self.assertEqual({i for _, i in fts}, trechos)
        self.assertTrue(all(rowid == rowid_fts(i) for rowid, i in fts))

    def test_falha_em_qualquer_lote_nao_separa_trechos_e_fts(self):
        limpo = self.novo_d1("limpo")
        rel, _ = self.rodar(limpo)
        self.assertTrue(rel.estado_gravado)
        total = limpo.grupos
        self.assertGreater(total, 6)
        self.conferir_fts(limpo)
        # cada unidade de trechos tem o DELETE do FTS, o INSERT do trecho e o INSERT do FTS
        for n in range(1, total + 1):
            with self.subTest(grupo=n):
                d1 = self.novo_d1(f"falha-{n}")
                d1.falhar_em = n
                with self.assertRaises(ErroNuvem):
                    self.rodar(d1)
                self.conferir_fts(d1)
                remoto = BancoRemoto(d1, "teste", comando_npx="npx")
                self.assertFalse(fts_divergente(remoto))
                d1.falhar_em = None
                rel, _ = self.rodar(d1)
                self.assertEqual(rel.falhas, [])
                self.assertTrue(rel.estado_gravado)
                self.assertEqual(len(d1.consultar("SELECT id FROM trechos")), 6)
                self.conferir_fts(d1)
                self.assertEqual(self.rodar(d1)[0].escritas, 0)

    def test_unidades_nunca_divididas(self):
        unidades = [[("SELECT 1", ())], [("SELECT 2", ()), ("SELECT 3", ()), ("SELECT 4", ())], [("SELECT 5", ())]]
        grupos = cloudflare.dividir_unidades(unidades, max_instrucoes=3)
        self.assertEqual([[s for s, _ in g] for g in grupos],
                         [["SELECT 1"], ["SELECT 2", "SELECT 3", "SELECT 4"], ["SELECT 5"]])
        with self.assertRaises(ValueError):
            cloudflare.dividir_unidades([[("SELECT 1", ())] * 4], max_instrucoes=3)
        linhas = [(f"{i:016x}", "doc:1", "siscam:1", i, f"texto {i}", "0" * 64) for i in range(40)]
        alteracao = banco.Alteracao.de("trechos", gravar=linhas, apagar=[(f"{i:016x}",) for i in range(50, 60)],
                                       fts_linha=lambda t: (rowid_fts(t[0]), t[0], normalizar_busca(t[4])),
                                       fts_rowid=lambda k: rowid_fts(k[0]))
        for unidade in banco.unidades([alteracao]):
            sqls = " | ".join(s for s, _ in unidade)
            self.assertIn('"trechos"', sqls)
            self.assertIn("trechos_fts", sqls)


class TestFtsPorConjunto(BaseSincronizacao):
    def test_mesma_contagem_ids_diferentes_refaz(self):
        self.sincronizar()
        con = sqlite3.connect(self.sqlite)
        con.execute("DELETE FROM trechos_fts WHERE id = ?", (TRECHO_900002,))
        falso = "00000000000000aa"
        con.execute("INSERT INTO trechos_fts (rowid, id, texto_norm) VALUES (?, ?, 'x')", (rowid_fts(falso), falso))
        con.commit()
        con.close()
        self.assertEqual(self.contar("trechos_fts"), 6)  # a contagem não muda
        rel = self.sincronizar()
        self.assertEqual(rel.plano["d1_fts_reconstruir"], 1)
        self.assertEqual(_ids(self.consultar, "trechos_fts"), _ids(self.consultar, "trechos"))
        self.assertEqual(self.sincronizar().plano["d1_fts_reconstruir"], 0)

    def test_rowid_errado_refaz(self):
        self.sincronizar()
        con = sqlite3.connect(self.sqlite)
        texto = con.execute("SELECT texto_norm FROM trechos_fts WHERE id = ?", (TRECHO_900002,)).fetchone()[0]
        con.execute("DELETE FROM trechos_fts WHERE id = ?", (TRECHO_900002,))
        con.execute("INSERT INTO trechos_fts (rowid, id, texto_norm) VALUES (7, ?, ?)", (TRECHO_900002, texto))
        con.commit()
        con.close()
        self.assertEqual(self.sincronizar().plano["d1_fts_reconstruir"], 1)

    def test_expressao_do_rowid_no_sql(self):
        con = sqlite3.connect(":memory:")
        try:
            for ident in ("0000000000000000", "ffffffffffffffff", "b30b6c30b03eee82", TRECHO_900002, "8000000000000001"):
                valor = con.execute(f"SELECT {banco.sql_rowid_fts(repr(ident))}").fetchone()[0]
                self.assertEqual(valor, rowid_fts(ident), ident)
        finally:
            con.close()


# ---------------------------------------------------------------- vetores órfãos e metadados
class TestVetores(BaseSincronizacao):
    def test_upsert_interrompido_fica_pendente_e_sai_depois(self):
        def quebrar(ambiente):
            original = ambiente.vetores.upsert

            def upsert(vetores):
                original(vetores)
                raise RuntimeError("queda logo depois do upsert")
            ambiente.vetores.upsert = upsert

        with self.assertRaises(RuntimeError):
            self.sincronizar(ajustar=quebrar)
        self.assertIn(TRECHO_900002, self.vetores())
        self.assertEqual(self.consultar("SELECT DISTINCT sha256 FROM trechos_indexados"), [(PENDENTE,)])
        self.assertEqual(self.contar("trechos_indexados"), 7)

        self.remover("siscam:900002", SHA_900002)
        rel = self.sincronizar()
        self.assertEqual(rel.falhas, [])
        self.assertNotIn(TRECHO_900002, self.vetores())
        self.assertEqual(rel.plano["vetores_upsert"], 6)
        self.assertEqual(self.consultar("SELECT count(*) FROM trechos_indexados WHERE sha256 = ?", (PENDENTE,)),
                         [(0,)])
        self.assertEqual(_ids(self.consultar, "trechos_indexados"), set(self.vetores()))

    def test_trecho_apagado_sai_mesmo_sem_registro(self):
        self.sincronizar()
        con = sqlite3.connect(self.sqlite)
        con.execute("DELETE FROM trechos_indexados WHERE id = ?", (TRECHO_900002,))
        con.commit()
        con.close()
        self.remover("siscam:900002", SHA_900002)
        rel = self.sincronizar()
        self.assertEqual(rel.falhas, [])
        self.assertNotIn(TRECHO_900002, self.vetores())

    def test_ementa_de_documento_apagado_sai_mesmo_sem_registro(self):
        self.sincronizar()
        self.assertIn("ementa:doc:290006", self.vetores())
        con = sqlite3.connect(self.sqlite)
        con.execute("DELETE FROM trechos_indexados WHERE id = 'ementa:doc:290006'")
        con.commit()
        con.close()
        (self.raiz / "data" / "documentos" / "indicacao" / "2024.json").write_text("[]\n", encoding="utf-8")
        rel = self.sincronizar()
        self.assertEqual(rel.plano["d1_documentos_apagar"], 1)
        self.assertNotIn("ementa:doc:290006", self.vetores())

    def test_reconstruir_apaga_vetor_orfao_do_indice(self):
        self.sincronizar()
        VetoresLocal(self.pasta / "vetores.jsonl").upsert([{"id": "orfao", "values": [0.0] * 1024, "metadata": {}}])
        self.assertIn("orfao", self.vetores())
        rel = self.sincronizar(reconstruir=True)
        self.assertEqual(rel.falhas, [])
        self.assertNotIn("orfao", self.vetores())
        self.assertEqual(len(self.vetores()), 7)

    def test_metadados_alterados_reenviam(self):
        self.sincronizar()
        antes = self.consultar("SELECT sha256 FROM trechos_indexados WHERE id = 'ementa:doc:290006'")[0][0]
        caminho = self.raiz / "data" / "documentos" / "indicacao" / "2024.json"
        caminho.write_text(caminho.read_text(encoding="utf-8").replace('"ano":2024', '"ano":2023'), encoding="utf-8")
        rel = self.sincronizar()
        self.assertEqual(rel.plano["vetores_upsert"], 1)
        vetor = self.vetores()["ementa:doc:290006"]
        self.assertEqual(vetor["metadata"]["ano"], 2023)
        depois = self.consultar("SELECT sha256 FROM trechos_indexados WHERE id = 'ementa:doc:290006'")[0][0]
        self.assertNotEqual(depois, antes)
        texto = self.consultar("SELECT ementa FROM documentos WHERE id = 'doc:290006'")[0][0]
        self.assertEqual(depois, sha_indexado(hashlib.sha256(texto.encode()).hexdigest(), vetor["metadata"]))
        self.assertEqual(self.sincronizar().escritas, 0)

    def test_espera_com_data_do_inicio(self):
        chamadas = []

        def ajustar(ambiente):
            original = ambiente.vetores.esperar

            def esperar(mutacao, desde=None, **kw):
                chamadas.append((mutacao, desde))
                return original(mutacao, desde=desde)
            ambiente.vetores.esperar = esperar

        self.sincronizar(ajustar=ajustar)
        mutacao, desde = chamadas[-1]
        self.assertIsNotNone(mutacao)
        self.assertEqual(desde, AGORA - FOLGA_RELOGIO)
        self.sincronizar(ajustar=ajustar)
        self.assertEqual(chamadas[-1], (None, None))  # conferido sempre, mesmo sem mutações

    def test_preflight_dimensoes(self):
        def ajustar(ambiente):
            ambiente.vetores.info = lambda: {"dimensions": 768}

        with self.assertRaises(ErroNuvem) as ctx:
            self.sincronizar(ajustar=ajustar)
        self.assertIn("768", str(ctx.exception))
        self.assertFalse((self.pasta / "vetores.jsonl").exists())
        self.assertEqual(self.contar("trechos_indexados"), 0)

    def test_preflight_indices_de_metadados(self):
        def ajustar(ambiente):
            ambiente.vetores.indices_metadados = lambda: {"tipo": "string", "ano": "number"}

        with self.assertRaises(ErroNuvem) as ctx:
            self.sincronizar(ajustar=ajustar)
        self.assertIn("legislatura", str(ctx.exception))
        self.assertFalse((self.pasta / "vetores.jsonl").exists())


# ---------------------------------------------------------------- originais, etapas e barreira
class TestOriginaisEEtapas(BaseSincronizacao):
    def test_original_em_falha_segura_o_arquivo_inteiro(self):
        (self.cache / "arquivos" / SHA_900005).unlink()
        rel = self.sincronizar()
        self.assertEqual(len(rel.falhas), 1)
        for tabela, coluna in (("arquivos", "id"), ("arquivo_documento", "arquivo"), ("trechos", "arquivo")):
            self.assertEqual(self.consultar(f"SELECT count(*) FROM {tabela} WHERE {coluna} = 'siscam:900005'"),
                             [(0,)], tabela)
        self.assertEqual(self.contar("trechos"), 5)
        self.assertEqual(self.contar("trechos_fts"), 5)
        self.assertEqual(self.contar("arquivo_documento"), 8)
        antes = set(self.vetores())
        self.assertEqual(len(antes), 6)
        self.assertEqual(_ids(self.consultar, "trechos_indexados"), antes)

        (self.cache / "arquivos" / SHA_900005).write_bytes(G.ORIGINAIS["siscam:900005"])
        rel = self.sincronizar()
        self.assertEqual(rel.falhas, [])
        novo = set(self.vetores()) - antes
        self.assertEqual(novo, {r[0] for r in self.consultar("SELECT id FROM trechos WHERE arquivo = 'siscam:900005'")})
        self.assertEqual((self.contar("trechos"), self.contar("arquivo_documento"), len(self.vetores())), (6, 9, 7))

    def test_etapas_separadas(self):
        rel = self.sincronizar(etapas=("d1",))
        self.assertEqual(rel.falhas, [])
        self.assertFalse(rel.estado_gravado)
        self.assertTrue(any("etapas parciais" in a for a in rel.avisos))
        self.assertFalse(self.objeto_r2(SHA_900002).exists())
        self.assertEqual(self.vetores(), {})
        self.assertEqual(self.contar("trechos"), 6)
        # sem a etapa r2, nenhum r2_chave vai ao D1 sem o original conferido
        self.assertEqual(self.consultar("SELECT count(*) FROM arquivos WHERE r2_chave IS NOT NULL"), [(0,)])

        mensagens: list[str] = []
        rel = self.sincronizar(etapas="r2,d1", progresso=mensagens.append)
        self.assertEqual(rel.feitas["r2_enviar"], 6)
        self.assertEqual(mensagens[-1], "R2: 6/6 originais conferidos")
        self.assertTrue(self.objeto_r2(SHA_900002).exists())
        self.assertEqual(self.consultar("SELECT count(*) FROM arquivos WHERE r2_chave IS NOT NULL"), [(6,)])
        self.assertFalse(rel.estado_gravado)

        rel = self.sincronizar(etapas=["vetores"])
        self.assertEqual(len(self.vetores()), 7)
        self.assertFalse(rel.estado_gravado)

        rel = self.sincronizar()
        self.assertTrue(rel.estado_gravado)
        self.assertEqual((rel.plano["vetores_upsert"], rel.plano["r2_enviar"], rel.feitas["d1_instrucoes"]), (0, 0, 0))
        self.assertEqual(rel.feitas["estado_indice"], 1)
        self.assertEqual(self.sincronizar().escritas, 0)

    def test_etapas_invalidas(self):
        with self.assertRaises(ValueError):
            etapas_validas("r2,xyz")
        self.assertEqual(etapas_validas("vetores,r2"), ("r2", "vetores"))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                cli.main(["--ambiente", "local", "--etapas", "r2,xyz"])
        self.assertEqual(ctx.exception.code, 2)

    def test_sem_r2(self):
        def sem_r2(ambiente):
            ambiente.r2 = None

        rel = self.sincronizar(ajustar=sem_r2, exportar=self.tmp / "exp")
        self.assertEqual(rel.falhas, [])
        self.assertFalse(rel.estado_gravado)
        self.assertFalse((self.pasta / "r2").exists())
        self.assertTrue(any("sem R2" in a for a in rel.avisos))
        self.assertTrue((self.tmp / "exp" / rel.versao / "SHA256SUMS").is_file())

    def test_envios_paralelos_ate_4(self):
        estado = {"agora": 0, "maximo": 0}
        trava = threading.Lock()

        def ajustar(ambiente):
            original = ambiente.r2.existe

            def existe(bucket, chave):
                with trava:
                    estado["agora"] += 1
                    estado["maximo"] = max(estado["maximo"], estado["agora"])
                time.sleep(0.05)
                with trava:
                    estado["agora"] -= 1
                return original(bucket, chave)
            ambiente.r2.existe = existe

        rel = self.sincronizar(ajustar=ajustar)
        self.assertEqual(rel.feitas["r2_enviar"], 6)
        self.assertEqual(TRABALHADORES_R2, 4)
        self.assertLessEqual(estado["maximo"], 4)
        self.assertGreater(estado["maximo"], 1)

    def test_barreira_varre_motivo_das_remocoes(self):
        dados = json.loads(self.remocoes_originais)
        dados["remocoes"][0]["motivo"] = "Pedido recebido de fulano.sintetico@example.org."
        (self.raiz / "config" / "remocoes.json").write_text(json.dumps(dados, ensure_ascii=False, indent=1) + "\n",
                                                            encoding="utf-8", newline="\n")
        with self.assertRaises(ErroBarreira) as ctx:
            self.sincronizar()
        self.assertIn("remocao siscam:", str(ctx.exception))
        self.assertNotIn("example.org", str(ctx.exception))
        self.assertFalse(self.sqlite.exists())

    def test_exportacao_compara_sha256sums_do_bucket(self):
        rel = self.sincronizar(exportar=self.tmp / "exp1")
        somas = self.pasta / "r2" / BUCKET_EXPORTACOES_LOCAL / rel.versao / "SHA256SUMS"
        somas.write_bytes(b"diferente\n")
        outra = self.sincronizar(exportar=self.tmp / "exp2")
        self.assertEqual(outra.feitas["exportacao_enviar"], 0)
        self.assertTrue(any("difere" in a for a in outra.avisos))
        self.assertEqual(somas.read_bytes(), b"diferente\n")


# ---------------------------------------------------------------- leitura paginada e utilidades
class TestLeituraELimites(BaseSincronizacao):
    def test_paginas_por_chave_sem_offset(self):
        self.sincronizar()
        consultas: list[str] = []

        class Paginado(BancoLocal):
            pagina = 2

            def consultar(self, sql, params=()):
                consultas.append(sql)
                return super().consultar(sql, params)

        b = Paginado(self.sqlite, somente_leitura=True)
        self.addCleanup(b.fechar)
        completo = BancoLocal(self.sqlite, somente_leitura=True)
        self.addCleanup(completo.fechar)
        for tabela in ("documentos", "arquivo_documento", "autoria", "trechos"):
            colunas, chave = COLUNAS[tabela]
            with self.subTest(tabela=tabela):
                self.assertEqual(ler_tabela(b, tabela, colunas, chave), ler_tabela(completo, tabela, colunas, chave))
        self.assertTrue(consultas)
        self.assertFalse(any("OFFSET" in sql for sql in consultas))
        self.assertTrue(any(") > (" in sql for sql in consultas))  # chave composta

    def test_documentos_meta_sem_cortar_id(self):
        ids = [f"doc:{n}" for n in range(100000, 100400)]
        texto = documentos_meta(ids, limite=50)
        self.assertLessEqual(len(texto), 50)
        partes = texto.split(",")
        self.assertEqual(partes, sorted(ids)[:len(partes)])
        self.assertEqual(documentos_meta(["doc:2", "doc:1"], limite=8), "doc:1")
        self.assertEqual(documentos_meta(["doc:1"], limite=3), "")
        self.assertLessEqual(len(documentos_meta(ids)), 1500)

    def test_normalizacao_compartilhada(self):
        dados = json.loads((FIXTURES / "normalizacao.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(dados["pares"]), 15)
        for par in dados["pares"]:
            with self.subTest(entrada=par["entrada"]):
                self.assertEqual(normalizar_busca(par["entrada"]), par["saida"])
        funcao = dados["funcao_js"]
        self.assertEqual(funcao, 's.normalize("NFD").replace(/\\p{Mn}/gu, "").normalize("NFC").toLowerCase()')
        for doc in ("docs/backend.md", "docs/contratos/textos.md"):
            self.assertIn(funcao, (RAIZ / doc).read_text(encoding="utf-8"), doc)
        self.assertIn(funcao, normalizar_busca.__doc__)


# ---------------------------------------------------------------- R2 por REST e credenciais
class BaseHttp(unittest.TestCase):
    def iniciar(self, responder):
        self.servidor = Servidor(responder)
        self.addCleanup(self.servidor.fechar)
        self.esperas: list[float] = []
        return self.servidor


class TestR2Rest(BaseHttp):
    def test_put_get_delete_e_existencia(self):
        objetos: dict[str, bytes] = {}

        def responder(p):
            if p["cabecalhos"].get("authorization") != f"Bearer {TOKEN}":
                return 401, {}, b'{"success":false}'
            caminho = p["caminho"]
            if p["metodo"] == "PUT":
                objetos[caminho] = p["corpo"]
                return ok({"key": caminho})
            if p["metodo"] == "GET":
                if caminho not in objetos:
                    return 404, {"Content-Type": "application/json"}, b'{"success":false,"errors":[{"code":10007}]}'
                if p["cabecalhos"].get("range") == "bytes=0-0":
                    return 206, {}, objetos[caminho][:1]
                return 200, {}, objetos[caminho]
            if p["metodo"] == "DELETE":
                objetos.pop(caminho, None)
                return ok({})
            return 405, {}, b""

        srv = self.iniciar(responder)
        r2 = R2Rest(Cloudflare("conta", TOKEN, base=srv.url, dormir=self.esperas.append))
        chave = "sha256/ab/cd/abcd"
        self.assertFalse(R2Rest.put_condicional)
        self.assertFalse(r2.existe("b", chave))
        self.assertTrue(r2.enviar("b", chave, b"original", "application/pdf", {"documentos": "doc:1"}))
        self.assertFalse(r2.enviar("b", chave, b"original", "application/pdf"))  # já existe: sem PUT
        self.assertEqual(sum(p["metodo"] == "PUT" for p in srv.pedidos), 1)
        self.assertTrue(r2.enviar("b", chave, b"novo", se_ausente=False))  # PUT sem condição
        put = next(p for p in srv.pedidos if p["metodo"] == "PUT")
        self.assertEqual(put["caminho"], "/accounts/conta/r2/buckets/b/objects/sha256%2Fab%2Fcd%2Fabcd")
        self.assertEqual(put["cabecalhos"]["content-type"], "application/pdf")
        self.assertNotIn("if-none-match", put["cabecalhos"])
        self.assertEqual(srv.pedidos[0]["cabecalhos"]["range"], "bytes=0-0")
        self.assertTrue(r2.existe("b", chave))
        self.assertEqual(r2.obter("b", chave), b"novo")
        r2.apagar("b", chave)
        self.assertFalse(r2.existe("b", chave))
        self.assertIsNone(r2.obter("b", "outra"))
        self.assertNotIn(TOKEN, repr(r2))

    def test_401_renova_e_tenta_uma_vez(self):
        novo = "tok-NOVO-abcdef0123456789"

        def responder(p):
            if p["cabecalhos"].get("authorization") == f"Bearer {novo}":
                return ok({"vale": 1}) if p["metodo"] != "PUT" else ok({})
            return 401, {"Content-Type": "application/json"}, b'{"success":false,"errors":[{"code":10000}]}'

        srv = self.iniciar(responder)
        renovacoes = []
        credencial = Credencial(TOKEN, ORIGEM_OAUTH, renovador=lambda: (renovacoes.append(1) or (novo, None)))
        cf = Cloudflare("conta", credencial, base=srv.url)
        self.assertEqual(cf.chamar("GET", "vectorize/v2/indexes/x/info"), {"vale": 1})
        self.assertEqual(len(renovacoes), 1)
        self.assertEqual(len(srv.pedidos), 2)
        self.assertTrue(R2Rest(cf).enviar("b", "k", b"x", se_ausente=False))  # já com o token novo
        self.assertEqual(len(renovacoes), 1)

        # renovação que não resolve: uma única nova tentativa, erro sem o token
        recusado = Credencial(TOKEN, ORIGEM_OAUTH, renovador=lambda: ("tok-AINDA-RUIM-0000", None))
        antes = len(srv.pedidos)
        with self.assertRaises(ErroNuvem) as ctx:
            Cloudflare("conta", recusado, base=srv.url).chamar("GET", "x")
        self.assertEqual(ctx.exception.status, 401)
        self.assertEqual(len(srv.pedidos) - antes, 2)
        self.assertNotIn(TOKEN, str(ctx.exception))
        self.assertNotIn("tok-AINDA-RUIM-0000", str(ctx.exception))

        # token de ambiente: sem renovação, o 401 sobe direto
        with self.assertRaises(ErroNuvem):
            Cloudflare("conta", "tok-fixo-0000000000", base=srv.url).chamar("GET", "x")


class TestCredenciais(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="radar-cred-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.toml = self.tmp / "default.toml"

    def gravar(self, token: str, expira: str) -> None:
        self.toml.write_text(f'oauth_token = "{token}"\nexpiration_time = "{expira}"\nrefresh_token = "r-1"\n'
                             'scopes = [ "account:read" ]\n', encoding="utf-8")

    def test_oauth_lido_e_renovado_quando_vence(self):
        self.gravar("tok-oauth-AAAA", "2026-10-27T15:30:00.000Z")
        relogio = {"agora": AGORA}
        chamadas = []

        def whoami():
            chamadas.append(1)
            self.gravar("tok-oauth-BBBB", "2026-10-27T16:30:00.000Z")

        cred = credencial_do_ambiente({"WRANGLER_CONFIG": str(self.toml)}, executar_whoami=whoami,
                                      relogio=lambda: relogio["agora"])
        self.assertTrue(cred.oauth)
        self.assertEqual(cred.token(), "tok-oauth-AAAA")
        self.assertEqual(chamadas, [])
        relogio["agora"] = AGORA + timedelta(minutes=29, seconds=30)  # dentro da folga de 60 s
        self.assertEqual(cred.token(), "tok-oauth-BBBB")
        self.assertEqual(chamadas, [1])
        self.assertNotIn("tok-oauth", repr(cred))
        self.assertIn("tok-oauth-AAAA", cred.segredos())

    def test_ambiente_tem_precedencia_e_falta_de_login(self):
        self.gravar("tok-oauth-AAAA", "2999-01-01T00:00:00Z")
        cred = credencial_do_ambiente({"CLOUDFLARE_API_TOKEN_DADOS": "tok-env", "WRANGLER_CONFIG": str(self.toml)})
        self.assertFalse(cred.oauth)
        self.assertEqual(cred.token(), "tok-env")
        with self.assertRaises(ErroNuvem) as ctx:
            credencial_do_ambiente({"WRANGLER_CONFIG": str(self.tmp / "nada.toml")})
        self.assertIn("wrangler login", str(ctx.exception))
        self.toml.write_text('refresh_token = "r"\n', encoding="utf-8")
        with self.assertRaises(ErroNuvem) as ctx:
            credencial_do_ambiente({"WRANGLER_CONFIG": str(self.toml)})
        self.assertNotIn("r-1", str(ctx.exception))

    def test_whoami_sem_token_no_ambiente(self):
        self.gravar("tok-oauth-AAAA", "2000-01-01T00:00:00Z")  # vencido
        comandos = []

        def executar(comando, **kw):
            comandos.append((comando, kw))
            self.gravar("tok-oauth-BBBB", "2999-01-01T00:00:00Z")
            return subprocess.CompletedProcess(comando, 0, stdout="logado", stderr="")

        with mock.patch.dict(os.environ, {"CLOUDFLARE_API_TOKEN": "nao-deve-ir"}):
            cred = credencial_remota({"WRANGLER_CONFIG": str(self.toml)}, pasta_worker=self.tmp, executar=executar,
                                     comando_npx="npx")
            self.assertEqual(cred.token(), "tok-oauth-BBBB")
        comando, kw = comandos[0]
        self.assertEqual(comando, ["npx", "--yes", f"wrangler@{VERSAO_WRANGLER}", "whoami"])
        self.assertNotIn("CLOUDFLARE_API_TOKEN", kw["env"])
        self.assertEqual(kw["timeout"], 120.0)

    def test_escolha_do_r2_e_env_do_wrangler(self):
        self.gravar("tok-oauth-AAAA", "2999-01-01T00:00:00Z")
        base = {"WRANGLER_CONFIG": str(self.toml), "CLOUDFLARE_ACCOUNT_ID": "conta"}
        oauth = ambiente_remoto("staging", self.tmp, base, comando_npx="npx")
        self.assertIsInstance(oauth.r2, R2Rest)
        self.assertTrue(oauth.banco.credencial.oauth)
        self.assertNotIn("CLOUDFLARE_API_TOKEN", oauth.banco.wrangler.env_extra)
        self.assertIn("CLOUDFLARE_API_TOKEN", oauth.banco.wrangler.remover_env)
        self.assertIsNotNone(oauth.vetores.cf.ritmo)

        s3 = ambiente_remoto("staging", self.tmp, {**base, "R2_ACCESS_KEY_ID": "a", "R2_SECRET_ACCESS_KEY": "b"},
                             comando_npx="npx")
        self.assertIsInstance(s3.r2, R2)

        env = ambiente_remoto("staging", self.tmp, {"CLOUDFLARE_API_TOKEN": TOKEN, "CLOUDFLARE_ACCOUNT_ID": "conta"},
                              sem_r2=True, comando_npx="npx")
        self.assertIsNone(env.r2)
        self.assertEqual(env.banco.wrangler.env_extra["CLOUDFLARE_API_TOKEN"], TOKEN)

        # com o login OAuth, o subprocesso do wrangler não herda CLOUDFLARE_API_TOKEN
        capturados = []

        def executar(comando, **kw):
            capturados.append(kw["env"])
            return subprocess.CompletedProcess(comando, 0, stdout="", stderr="")

        remoto = BancoRemoto(None, "radar-niteroi-staging", executar=executar, comando_npx="npx",
                             remover_env=("CLOUDFLARE_API_TOKEN",), pasta_worker=self.tmp)
        with mock.patch.dict(os.environ, {"CLOUDFLARE_API_TOKEN": "herdado"}):
            remoto._wrangler("d1", "migrations", "apply", "radar-niteroi-staging", "--remote")
        self.assertNotIn("CLOUDFLARE_API_TOKEN", capturados[0])


# ---------------------------------------------------------------- Vectorize e ritmo
class TestVectorizeRobusto(BaseHttp):
    def cf(self, ritmo=None):
        return Cloudflare("conta", TOKEN, base=self.servidor.url, dormir=self.esperas.append, ritmo=ritmo)

    def test_mutacao_ausente_e_erro(self):
        self.iniciar(lambda p: ok({}))
        indice = Vectorize(self.cf(), "x")
        with self.assertRaises(ErroNuvem):
            indice.upsert([{"id": "a", "values": [0.5]}])
        with self.assertRaises(ErroNuvem):
            indice.apagar(["a"])

    def test_espera_data_de_processamento(self):
        estado = {"n": 0}

        def responder(p):
            estado["n"] += 1
            data = "2026-10-27T14:00:00Z" if estado["n"] < 3 else "2026-10-27T15:00:05.250Z"
            return ok({"processedUpToMutation": "m-1", "processedUpToDatetime": data, "dimensions": 1024})

        self.iniciar(responder)
        indice = Vectorize(self.cf(), "x", dormir=self.esperas.append)
        info = indice.esperar("m-1", intervalo=3.0, desde=AGORA)
        self.assertEqual(estado["n"], 3)
        self.assertEqual(self.esperas, [3.0, 3.0])
        self.assertEqual(info["dimensions"], 1024)

    def test_listar_ids_com_cursor_e_alternativa(self):
        def responder(p):
            if "cursor=" not in p["caminho"]:
                return ok({"vectors": [{"id": "a"}, {"id": "b"}], "isTruncated": True, "nextCursor": "c/1"})
            return ok({"vectors": [{"id": "c"}], "isTruncated": False, "nextCursor": None})

        srv = self.iniciar(responder)
        self.assertEqual(Vectorize(self.cf(), "idx").listar_ids(), ["a", "b", "c"])
        self.assertEqual(srv.pedidos[0]["caminho"], "/accounts/conta/vectorize/v2/indexes/idx/list?count=1000")
        self.assertTrue(srv.pedidos[1]["caminho"].endswith("&cursor=c%2F1"))

    def test_listar_sem_a_rota_usa_o_wrangler(self):
        self.iniciar(lambda p: (404, {"Content-Type": "application/json"}, b'{"success":false}'))
        indice = Vectorize(self.cf(), "idx", listar_alternativo=lambda: ["w1", "w2"])
        self.assertEqual(indice.listar_ids(), ["w1", "w2"])

    def test_indices_de_metadados(self):
        srv = self.iniciar(lambda p: ok({"metadataIndexes": [{"propertyName": "tipo", "indexType": "String"},
                                                              {"propertyName": "ano", "indexType": "Number"}]}))
        self.assertEqual(Vectorize(self.cf(), "idx").indices_metadados(), {"tipo": "string", "ano": "number"})
        self.assertEqual(srv.pedidos[0]["caminho"], "/accounts/conta/vectorize/v2/indexes/idx/metadata_index/list")

    def test_obter_em_lotes_de_100_no_ritmo(self):
        def responder(p):
            ids = json.loads(p["corpo"])["ids"]
            return ok([{"id": i, "values": [0.0], "metadata": {}} for i in ids])

        srv = self.iniciar(responder)
        esperas_ritmo: list[float] = []
        ritmo = Ritmo(4, relogio=lambda: 0.0, dormir=esperas_ritmo.append)
        vetores = Vectorize(self.cf(ritmo), "x").obter([f"v{i}" for i in range(250)])
        self.assertEqual(len(vetores), 250)
        self.assertEqual([len(json.loads(p["corpo"])["ids"]) for p in srv.pedidos], [100, 100, 50])
        self.assertEqual(esperas_ritmo, [0.25, 0.5])  # no máximo 4 por segundo

    def test_obter_recua_para_20(self):
        def responder(p):
            ids = json.loads(p["corpo"])["ids"]
            if len(ids) > 20:
                return 400, {"Content-Type": "application/json"}, b'{"success":false}'
            return ok([{"id": i, "values": [0.0]} for i in ids])

        srv = self.iniciar(responder)
        self.assertEqual(len(Vectorize(self.cf(), "x").obter([f"v{i}" for i in range(50)])), 50)
        self.assertEqual([len(json.loads(p["corpo"])["ids"]) for p in srv.pedidos], [50, 20, 20, 10])

    def test_ritmo(self):
        relogio = {"t": 10.0}
        esperas: list[float] = []

        def dormir(s):
            esperas.append(s)
            relogio["t"] += s

        ritmo = Ritmo(4, relogio=lambda: relogio["t"], dormir=dormir)
        for _ in range(5):
            ritmo.aguardar()
        self.assertEqual(esperas, [0.25] * 4)
        relogio["t"] += 5
        ritmo.aguardar()
        self.assertEqual(len(esperas), 4)


# ---------------------------------------------------------------- wrangler
class TestWrangler(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="radar-wrangler-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_npx_no_windows_prefere_cmd(self):
        caminhos = {"npx": "/bin/npx", "npx.cmd": r"C:\node\npx.cmd"}
        self.assertEqual(npx("nt", caminhos.get), r"C:\node\npx.cmd")
        self.assertEqual(npx("posix", caminhos.get), "/bin/npx")
        self.assertEqual(npx("nt", {"npx": "/bin/npx"}.get), "/bin/npx")
        with self.assertRaises(ErroNuvem):
            npx("nt", {}.get)

    def test_versao_fixada(self):
        pacote = json.loads((RAIZ / "worker" / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(pacote["devDependencies"]["wrangler"], VERSAO_WRANGLER)
        self.assertRegex(VERSAO_WRANGLER, r"^\d+\.\d+\.\d+$")
        self.assertEqual(prefixo(self.tmp, "npx"), ["npx", "--yes", f"wrangler@{VERSAO_WRANGLER}"])
        (self.tmp / "node_modules" / "wrangler").mkdir(parents=True)
        self.assertEqual(prefixo(self.tmp, "npx"), ["npx", "--no-install", "wrangler"])

    def test_prazo_esgotado(self):
        def executar(comando, **kw):
            raise subprocess.TimeoutExpired(comando, kw["timeout"])

        with self.assertRaises(ErroNuvem) as ctx:
            Wrangler(self.tmp, comando_npx="npx", executor=executar).executar("d1", "execute", "x")
        self.assertIn("900", str(ctx.exception))

    def test_listar_vetores_pelo_wrangler(self):
        saidas = iter(['aviso qualquer\n{"count":2,"vectors":[{"id":"a"},{"id":"b"}],"isTruncated":true,'
                       '"nextCursor":"c1"}', '{"vectors":[{"id":"c"}],"isTruncated":false}'])
        comandos = []

        def executar(comando, **kw):
            comandos.append(comando)
            return subprocess.CompletedProcess(comando, 0, stdout=next(saidas), stderr="")

        w = Wrangler(self.tmp, comando_npx="npx", executor=executar)
        self.assertEqual(listar_vetores(w, "idx"), ["a", "b", "c"])
        self.assertEqual(comandos[0][3:], ["vectorize", "list-vectors", "idx", "--count", "1000", "--json"])
        self.assertEqual(comandos[1][-2:], ["--cursor", "c1"])


if __name__ == "__main__":
    unittest.main()
