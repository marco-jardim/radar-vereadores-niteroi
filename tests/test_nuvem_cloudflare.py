"""Clientes REST do Cloudflare e S3 do R2 contra um servidor HTTP falso local (sem rede externa)."""
from __future__ import annotations

import json
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from coletor.nuvem import banco, cloudflare
from coletor.nuvem.cloudflare import D1, Cloudflare, Vectorize, WorkersAI
from coletor.nuvem.r2 import R2
from coletor.nuvem.rede import ErroNuvem, espera_retry_after, redigir, requisitar
from coletor.nuvem.wrangler import VERSAO_WRANGLER

TOKEN = "tok-SEGREDO-0123456789abcdef"


class Servidor:
    """Servidor HTTP em 127.0.0.1 numa thread; `responder(pedido)` devolve (status, cabeçalhos, corpo)."""

    def __init__(self, responder):
        self.pedidos: list[dict] = []
        externo = self

        class Manipulador(BaseHTTPRequestHandler):
            def _tratar(self):
                n = int(self.headers.get("Content-Length") or 0)
                corpo = self.rfile.read(n) if n else b""
                pedido = {"metodo": self.command, "caminho": self.path, "corpo": corpo,
                          "cabecalhos": {k.lower(): v for k, v in self.headers.items()}}
                externo.pedidos.append(pedido)
                status, cab, dados = responder(pedido)
                self.send_response(status)
                for k, v in cab.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(dados)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(dados)

            do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = _tratar

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Manipulador)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def fechar(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def ok(resultado, status=200, cab=None):
    corpo = json.dumps({"success": True, "errors": [], "messages": [], "result": resultado}).encode()
    return status, {"Content-Type": "application/json", **(cab or {})}, corpo


def ndjson_do_multipart(corpo: bytes) -> list[dict]:
    dados = corpo.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n--", 1)[0]
    return [json.loads(linha) for linha in dados.splitlines() if linha]


class Base(unittest.TestCase):
    responder = None

    def iniciar(self, responder):
        self.servidor = Servidor(responder)
        self.addCleanup(self.servidor.fechar)
        self.esperas: list[float] = []
        self.cf = Cloudflare("conta", TOKEN, base=self.servidor.url, dormir=self.esperas.append)
        return self.servidor


class TestD1(Base):
    def test_lote_respeita_parametros_e_instrucoes(self):
        def responder(p):
            corpo = json.loads(p["corpo"])
            return ok([{"results": [], "success": True} for _ in corpo["batch"]])

        srv = self.iniciar(responder)
        linhas = [(f"doc:{i}", "pl", i) for i in range(1000)]
        instrucoes = banco.instrucoes_gravar("documentos", ("id", "tipo", "ano"), linhas)
        self.assertTrue(all(len(p) <= 100 for _, p in instrucoes))
        self.assertEqual(sum(len(p) for _, p in instrucoes), 3000)
        D1(self.cf, "banco-1").lote(instrucoes)
        recebidas = [json.loads(p["corpo"])["batch"] for p in srv.pedidos]
        self.assertGreater(len(recebidas), 0)
        self.assertTrue(all(len(lote) <= cloudflare.MAX_INSTRUCOES_LOTE for lote in recebidas))
        todas = [i for lote in recebidas for i in lote]
        self.assertEqual(len(todas), len(instrucoes))
        for i in todas:
            self.assertLessEqual(len(i["params"]), 100)
            self.assertLessEqual(len(i["sql"].encode()), cloudflare.MAX_BYTES_INSTRUCAO)
            self.assertTrue(all(isinstance(v, str) for v in i["params"]))  # parâmetros como texto
            self.assertNotRegex(i["sql"], r"(?i)^\s*(BEGIN|COMMIT)")
        self.assertEqual(srv.pedidos[0]["caminho"], "/accounts/conta/d1/database/banco-1/query")
        self.assertEqual(srv.pedidos[0]["cabecalhos"]["authorization"], f"Bearer {TOKEN}")

    def test_null_embutido_e_rowid_inteiro(self):
        sql, params = banco.instrucoes_gravar("trechos_fts", ("rowid", "id", "texto_norm"), [(7, "a", None)])[0]
        self.assertIn("CAST(? AS INTEGER)", sql)
        self.assertIn("NULL", sql)
        self.assertEqual(params, (7, "a"))

    def test_instrucoes_literais_ate_100kb(self):
        texto = "licença " * 1500  # ~12 KB por linha
        linhas = [(f"t{i}", "doc:1", "siscam:1", i, texto, "0" * 64) for i in range(40)]
        lista = banco.instrucoes_gravar("trechos", banco.COLUNAS["trechos"][0], linhas, modo="literal")
        self.assertGreater(len(lista), 1)
        for sql, params in lista:
            self.assertEqual(params, ())
            self.assertLessEqual(len(sql.encode("utf-8")), cloudflare.MAX_BYTES_INSTRUCAO)
        self.assertEqual(sum(sql.count("'doc:1'") for sql, _ in lista), 40)
        with self.assertRaises(ValueError):
            banco.instrucoes_gravar("trechos", ("id", "texto"), [("x", "y" * 200_000)], modo="literal")

    def test_validacao_dos_limites(self):
        with self.assertRaises(ValueError):
            cloudflare.validar_instrucao("SELECT 1", ["1"] * 101)
        with self.assertRaises(ValueError):
            cloudflare.validar_instrucao("SELECT '" + "x" * 100_001 + "'")
        with self.assertRaises(ValueError):
            cloudflare.validar_instrucao("BEGIN TRANSACTION")
        cloudflare.validar_instrucao("SELECT 1", ["1"] * 100)

    def test_consultar(self):
        srv = self.iniciar(lambda p: ok([{"results": [{"n": 3}], "success": True}]))
        self.assertEqual(D1(self.cf, "b").consultar("SELECT count(*) AS n FROM x WHERE a = ?", [5]), [{"n": 3}])
        self.assertEqual(json.loads(srv.pedidos[0]["corpo"]), {"sql": "SELECT count(*) AS n FROM x WHERE a = ?",
                                                               "params": ["5"]})


class TestRepeticoesERedacao(Base):
    def test_429_respeita_retry_after(self):
        estado = {"n": 0}

        def responder(p):
            estado["n"] += 1
            if estado["n"] == 1:
                return 429, {"Retry-After": "7", "Content-Type": "application/json"}, b'{"success":false}'
            return ok([{"results": [], "success": True}])

        self.iniciar(responder)
        D1(self.cf, "b").consultar("SELECT 1")
        self.assertEqual(estado["n"], 2)
        self.assertEqual(self.esperas, [7.0])

    def test_5xx_espera_progressiva_e_desiste(self):
        srv = self.iniciar(lambda p: (503, {}, b"indisponivel"))
        with self.assertRaises(ErroNuvem) as ctx:
            self.cf.chamar("GET", "vectorize/v2/indexes/x/info")
        self.assertEqual(ctx.exception.status, 503)
        self.assertEqual(len(srv.pedidos), 5)
        self.assertEqual(self.esperas, [2.0, 4.0, 8.0, 16.0])

    def test_token_redigido_nos_erros(self):
        def responder(p):
            eco = f"recebido: {p['cabecalhos'].get('authorization')} em {p['caminho']}"
            return 403, {"Content-Type": "text/plain"}, eco.encode()

        self.iniciar(responder)
        with self.assertRaises(ErroNuvem) as ctx:
            self.cf.chamar("POST", "ai/run/@cf/baai/bge-m3", json_={"text": ["x"]})
        mensagem = str(ctx.exception)
        self.assertNotIn(TOKEN, mensagem)
        self.assertIn("HTTP 403", mensagem)
        self.assertIn("***", mensagem)
        self.assertNotIn(TOKEN, repr(self.cf))

    def test_consulta_da_url_redigida(self):
        srv = self.iniciar(lambda p: (400, {}, b"ruim"))
        url = srv.url + "/bucket/x?X-Amz-Signature=abcdef123456&token=OUTRO-SEGREDO"
        with self.assertRaises(ErroNuvem) as ctx:
            requisitar("GET", url, tentativas=1, segredos=("OUTRO-SEGREDO",))
        self.assertNotIn("abcdef123456", str(ctx.exception))
        self.assertNotIn("OUTRO-SEGREDO", str(ctx.exception))
        self.assertEqual(redigir("Authorization: Bearer abc.def-123"), "Authorization: Bearer ***")

    def test_retry_after_data_http(self):
        from datetime import datetime, timezone
        agora = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(espera_retry_after("Tue, 27 Oct 2026 12:00:30 GMT", agora), 30.0)
        self.assertIsNone(espera_retry_after("amanhã"))
        self.assertIsNone(espera_retry_after(None))


class TestVectorize(Base):
    def _responder(self, p):
        if p["caminho"].endswith("/info"):
            return ok({"vectorCount": 0, "processedUpToMutation": "m-1"})
        return ok({"mutationId": f"m-{len(self.servidor.pedidos)}"})

    def test_lotes_de_ate_5000(self):
        self.iniciar(self._responder)
        vetores = [{"id": f"v{i}", "values": [0.5, -0.25], "metadata": {"ano": 2024, "tipo": "pl"}}
                   for i in range(12001)]
        indice = Vectorize(self.cf, "radar-niteroi-trechos-staging", lote=5000)
        mutacoes = indice.upsert(vetores)
        tamanhos = [len(ndjson_do_multipart(p["corpo"])) for p in self.servidor.pedidos]
        self.assertEqual(tamanhos, [5000, 5000, 2001])
        self.assertEqual(len(mutacoes), 3)
        p = self.servidor.pedidos[0]
        self.assertEqual(p["caminho"], "/accounts/conta/vectorize/v2/indexes/radar-niteroi-trechos-staging/upsert")
        self.assertTrue(p["cabecalhos"]["content-type"].startswith("multipart/form-data; boundary="))
        self.assertIn(b'name="vectors"', p["corpo"])
        primeiro = ndjson_do_multipart(p["corpo"])[0]
        self.assertEqual(primeiro, {"id": "v0", "values": [0.5, -0.25], "metadata": {"ano": 2024, "tipo": "pl"}})
        with self.assertRaises(ValueError):
            Vectorize(self.cf, "x", lote=5001)
        with self.assertRaises(ValueError):
            Vectorize(self.cf, "x", max_bytes=cloudflare.MAX_BYTES_VETORES + 1)

    def test_lotes_por_bytes(self):
        self.iniciar(self._responder)
        limite = cloudflare.ENVELOPE + 400
        vetores = [{"id": f"v{i:03d}", "values": [0.125] * 8} for i in range(50)]
        Vectorize(self.cf, "x", lote=5000, max_bytes=limite).inserir(vetores)
        self.assertGreater(len(self.servidor.pedidos), 1)
        for p in self.servidor.pedidos:
            self.assertLessEqual(len(p["corpo"]), limite)
            self.assertTrue(p["caminho"].endswith("/insert"))
        ids = [v["id"] for p in self.servidor.pedidos for v in ndjson_do_multipart(p["corpo"])]
        self.assertEqual(ids, [v["id"] for v in vetores])

    def test_apagar_por_ids(self):
        self.iniciar(self._responder)
        Vectorize(self.cf, "x").apagar([f"id{i}" for i in range(2500)])
        corpos = [json.loads(p["corpo"]) for p in self.servidor.pedidos]
        self.assertEqual([len(c["ids"]) for c in corpos], [1000, 1000, 500])
        self.assertTrue(all(p["caminho"].endswith("/delete_by_ids") for p in self.servidor.pedidos))

    def test_espera_a_mutacao(self):
        estado = {"n": 0}

        def responder(p):
            estado["n"] += 1
            return ok({"vectorCount": 3, "processedUpToMutation": "m-velha" if estado["n"] < 3 else "m-nova"})

        self.iniciar(responder)
        info = Vectorize(self.cf, "x", dormir=self.esperas.append).esperar("m-nova", intervalo=2.0)
        self.assertEqual(info["processedUpToMutation"], "m-nova")
        self.assertEqual(estado["n"], 3)
        self.assertEqual(self.esperas, [2.0, 2.0])

    def test_espera_com_prazo(self):
        self.iniciar(lambda p: ok({"processedUpToMutation": "outra"}))
        relogio = iter(range(0, 10_000, 10))
        indice = Vectorize(self.cf, "x", dormir=lambda s: None, relogio=lambda: next(relogio))
        with self.assertRaises(ErroNuvem):
            indice.esperar("minha", timeout=30, intervalo=1)


class TestWorkersAI(Base):
    def test_lotes_de_50_e_dimensao(self):
        def responder(p):
            textos = json.loads(p["corpo"])["text"]
            return ok({"shape": [len(textos), 1024], "data": [[0.01] * 1024 for _ in textos]})

        srv = self.iniciar(responder)
        ia = WorkersAI(self.cf)
        vetores = ia.embeddings([f"texto {i}" for i in range(120)])
        self.assertEqual(len(vetores), 120)
        self.assertEqual([len(json.loads(p["corpo"])["text"]) for p in srv.pedidos], [50, 50, 20])
        self.assertEqual(srv.pedidos[0]["caminho"], "/accounts/conta/ai/run/@cf/baai/bge-m3")

    def test_lote_limitado_por_caracteres_e_dividido_no_limite_de_contexto(self):
        def responder(p):
            textos = json.loads(p["corpo"])["text"]
            if len(textos) > 2:
                return 400, {"Content-Type": "application/json"}, json.dumps({
                    "success": False, "errors": [{"code": 3030, "message": "AiError: Max context reached "
                                                  "62350 tokens but model supports only 60000"}]}).encode()
            return ok({"data": [[0.01] * 1024 for _ in textos]})

        srv = self.iniciar(responder)
        textos = ["x" * 25_000] * 3 + ["curto"] * 5
        self.assertEqual(len(WorkersAI(self.cf).embeddings(textos)), 8)
        tamanhos = [len(json.loads(p["corpo"])["text"]) for p in srv.pedidos]
        # 2 longos (50 mil caracteres) por chamada; o terceiro abre o lote seguinte com os curtos,
        # que excede o contexto simulado e é dividido ao meio até caber
        self.assertEqual(tamanhos[0], 2)
        self.assertEqual(tamanhos[1], 6)
        self.assertEqual(tamanhos, [2, 6, 3, 1, 2, 3, 1, 2])  # recusados (>2) e as metades aceitas

    def test_dimensao_errada_falha(self):
        self.iniciar(lambda p: ok({"shape": [1, 1023], "data": [[0.0] * 1023]}))
        with self.assertRaises(ErroNuvem) as ctx:
            WorkersAI(self.cf).embeddings(["x"])
        self.assertIn("1023", str(ctx.exception))

    def test_quantidade_errada_falha(self):
        self.iniciar(lambda p: ok({"data": [[0.0] * 1024]}))
        with self.assertRaises(ErroNuvem):
            WorkersAI(self.cf).embeddings(["a", "b"])


class TestR2(Base):
    def test_put_condicional_head_get_delete(self):
        objetos: dict[str, bytes] = {}

        def responder(p):
            caminho = p["caminho"]
            if p["metodo"] == "PUT":
                if p["cabecalhos"].get("if-none-match") == "*" and caminho in objetos:
                    return 412, {}, b"<Error><Code>PreconditionFailed</Code></Error>"
                objetos[caminho] = p["corpo"]
                return 200, {"ETag": '"x"'}, b""
            if p["metodo"] in ("HEAD", "GET"):
                if caminho not in objetos:
                    return 404, {}, b""
                return 200, {}, objetos[caminho]
            if p["metodo"] == "DELETE":
                objetos.pop(caminho, None)
                return 204, {}, b""
            return 400, {}, b""

        srv = self.iniciar(responder)
        cliente = R2("AKID", "segredo-r2-muito-secreto", endpoint=srv.url, dormir=self.esperas.append)
        chave = "sha256/ab/cd/abcd"
        self.assertFalse(cliente.existe("b", chave))
        self.assertTrue(cliente.enviar("b", chave, b"original", "application/pdf", {"documentos": "doc:1"}))
        self.assertFalse(cliente.enviar("b", chave, b"original", "application/pdf"))  # 412
        self.assertTrue(cliente.existe("b", chave))
        self.assertEqual(cliente.obter("b", chave), b"original")
        put = next(p for p in srv.pedidos if p["metodo"] == "PUT")
        self.assertEqual(put["cabecalhos"]["if-none-match"], "*")
        self.assertEqual(put["cabecalhos"]["x-amz-meta-documentos"], "doc:1")
        self.assertEqual(put["cabecalhos"]["content-type"], "application/pdf")
        self.assertIn("x-amz-content-sha256", put["cabecalhos"])
        self.assertTrue(put["cabecalhos"]["authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKID/"))
        self.assertIn("/auto/s3/aws4_request", put["cabecalhos"]["authorization"])
        cliente.apagar("b", chave)
        self.assertFalse(cliente.existe("b", chave))
        self.assertEqual(srv.pedidos[1]["caminho"], "/b/sha256/ab/cd/abcd")

    def test_erro_sem_segredo(self):
        srv = self.iniciar(lambda p: (403, {}, ("assinatura " + p["cabecalhos"]["authorization"]).encode()))
        cliente = R2("AKID", "segredo-r2-muito-secreto", endpoint=srv.url, tentativas=1)
        with self.assertRaises(ErroNuvem) as ctx:
            cliente.obter("b", "x")
        self.assertNotIn("segredo-r2-muito-secreto", str(ctx.exception))
        self.assertIn("Signature=***", str(ctx.exception))


class TestConfigWrangler(unittest.TestCase):
    def test_nomes_de_producao_e_staging(self):
        from coletor.nuvem.ambientes import config_wrangler, sem_comentarios
        producao = config_wrangler("production")
        self.assertEqual((producao["banco"], producao["indice"], producao["arquivos"], producao["exportacoes"],
                          producao["env"]),
                         ("radar-niteroi", "radar-niteroi-trechos", "radar-niteroi-arquivos",
                          "radar-niteroi-exportacoes", None))
        staging = config_wrangler("staging")
        self.assertEqual((staging["banco"], staging["indice"], staging["env"]),
                         ("radar-niteroi-staging", "radar-niteroi-trechos-staging", "staging"))
        self.assertEqual(json.loads(sem_comentarios('{"a": "https://x//y", /* c */ "b": [1,], // fim\n}')),
                         {"a": "https://x//y", "b": [1]})


class TestBancoRemoto(unittest.TestCase):
    def test_carga_grande_vai_por_arquivo_e_wrangler(self):
        chamadas = []

        class D1Falso:
            def lote(self, instrucoes):
                raise AssertionError("não deveria usar REST")

        def executar(comando, **kw):
            arquivo = next(a.split("=", 1)[1] for a in comando if a.startswith("--file="))
            chamadas.append((comando, kw, Path(arquivo).read_text(encoding="utf-8")))

            class R:
                returncode = 0
                stdout = stderr = ""
            return R()

        pasta = Path(tempfile.mkdtemp(prefix="radar-worker-"))
        self.addCleanup(shutil.rmtree, pasta, ignore_errors=True)
        remoto = banco.BancoRemoto(D1Falso(), "radar-niteroi-staging", ambiente_wrangler="staging",
                                   executar=executar, limiar_arquivo=0, env_extra={"CLOUDFLARE_API_TOKEN": TOKEN},
                                   comando_npx="npx", pasta_worker=pasta)
        linhas = [(f"doc:{i}", "pl", None, 2024, None, "Ementa d'água", None, None, None) for i in range(300)]
        n = remoto.aplicar([banco.Alteracao.de("documentos", gravar=linhas)])
        self.assertGreater(n, 0)
        comando, kw, conteudo = chamadas[0]
        self.assertEqual(comando[:3], ["npx", "--yes", f"wrangler@{VERSAO_WRANGLER}"])  # versão fixada
        self.assertEqual(comando[3:8], ["d1", "execute", "radar-niteroi-staging", "--remote", "--yes"])
        self.assertEqual(comando[-2:], ["--env", "staging"])
        self.assertEqual(kw["env"]["CI"], "true")
        self.assertEqual(kw["timeout"], 900)
        self.assertEqual(kw["cwd"], str(pasta))
        self.assertEqual(kw["env"]["CLOUDFLARE_API_TOKEN"], TOKEN)
        self.assertIn("'Ementa d''água'", conteudo)
        self.assertNotIn("BEGIN", conteudo)
        for linha in conteudo.splitlines():
            self.assertLessEqual(len(linha.encode()), cloudflare.MAX_BYTES_INSTRUCAO)
        self.assertEqual(conteudo.count("'doc:"), 300)

    def test_falha_do_wrangler_redigida(self):
        def executar(comando, **kw):
            class R:
                returncode = 1
                stdout = ""
                stderr = f"Authentication error with {TOKEN}"
            return R()

        class D1Falso:
            def consultar(self, sql, params=()):
                return [{"name": "documentos"}]

        remoto = banco.BancoRemoto(D1Falso(), "radar-niteroi", executar=executar, segredos=(TOKEN,),
                                   comando_npx="npx")
        with self.assertRaises(ErroNuvem) as ctx:
            remoto.migrar(banco.PASTA_MIGRACOES)
        self.assertNotIn(TOKEN, str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
