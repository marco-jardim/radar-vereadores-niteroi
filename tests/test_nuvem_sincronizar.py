"""Sincronização no ambiente local (SQLite, R2 e Vectorize em pastas) a partir das fixtures do contrato."""
from __future__ import annotations

import contextlib
import gzip
import hashlib
import importlib.util
import io
import json
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from coletor import mascara, remocoes
from coletor.arquivos import salvar_mapa
from coletor.nuvem import __main__ as cli
from coletor.nuvem import banco
from coletor.nuvem.ambientes import BUCKET_ARQUIVOS_LOCAL, BUCKET_EXPORTACOES_LOCAL, ambiente_local
from coletor.nuvem.fonte import ErroFonte, Fonte, Trecho, carregar_fonte, normalizar_busca, varrer_fonte
from coletor.nuvem.local import MODELO_LOCAL, R2Local, VetoresLocal, desempacotar
from coletor.nuvem.r2 import chave_r2
from coletor.nuvem.rede import ErroNuvem
from coletor.nuvem.sincronizar import (ErroBarreira, _ler_dump, _ler_somas_exportacao, _nomes_exportacao,
                                      _partes_exportacao, gzip_deterministico, sincronizar)
from coletor.trechos import VERSAO_TRECHOS

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "contratos"
AGORA = datetime(2026, 10, 27, 15, 0, 0, tzinfo=timezone.utc)
COMMIT = "c0ffee0000000000000000000000000000000000"


def _gerador():
    spec = importlib.util.spec_from_file_location("gerar_fixtures_contratos_nuvem", FIXTURES / "gerar_fixtures.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


G = _gerador()
SHA_900002 = hashlib.sha256(G.ORIGINAIS["siscam:900002"]).hexdigest()
SHA_900005 = hashlib.sha256(G.ORIGINAIS["siscam:900005"]).hexdigest()
TEXTO_LICENCA = ("Requer informações sobre o pedido de licença ambiental para a reforma da praça central do "
                 "bairro, com a análise técnica e o parecer da secretaria municipal competente.")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="radar-nuvem-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.raiz = self.tmp / "raiz"
        shutil.copytree(FIXTURES, self.raiz, ignore=shutil.ignore_patterns("*.py", "__pycache__"))
        self.textos = self.raiz / "dados-textos"
        self.cache = self.tmp / "cache"
        (self.cache / "arquivos").mkdir(parents=True)
        for dados in G.ORIGINAIS.values():
            if dados:
                (self.cache / "arquivos" / hashlib.sha256(dados).hexdigest()).write_bytes(dados)
        self.pasta = self.tmp / "nuvem"
        self.sqlite = self.pasta / "local.sqlite"
        self.remocoes_originais = (self.raiz / "config" / "remocoes.json").read_bytes()

    def sincronizar(self, ajustar=None, liberados=None, **kw):
        remocoes.limpar_cache()
        ambiente = ambiente_local(self.sqlite, somente_leitura=kw.get("simular", False))
        if ajustar:
            ajustar(ambiente)
        try:
            return sincronizar(self.raiz, self.textos, ambiente, cache=self.cache, commit=COMMIT,
                               liberados=G.LIBERADOS if liberados is None else liberados,
                               agora=lambda: AGORA, **kw)
        finally:
            ambiente.banco.fechar()

    def consultar(self, sql, params=()):
        con = sqlite3.connect(self.sqlite)
        try:
            return con.execute(sql, params).fetchall()
        finally:
            con.close()

    def contar(self, tabela):
        return self.consultar(f"SELECT count(*) FROM {tabela}")[0][0]

    def vetores(self) -> dict[str, dict]:
        caminho = self.pasta / "vetores.jsonl"
        if not caminho.exists():
            return {}
        return {o["id"]: o for o in map(json.loads, caminho.read_text(encoding="utf-8").splitlines())}

    def objeto_r2(self, sha) -> Path:
        return self.pasta / "r2" / BUCKET_ARQUIVOS_LOCAL / Path(*chave_r2(sha).split("/"))

    def remover(self, chave, sha):
        dados = json.loads(self.remocoes_originais)
        dados["remocoes"].append({"chave": chave, "sha256": sha, "motivo": "Teste sintético.",
                                  "fonte": "https://example.org/remocao", "data": "2026-01-16"})
        (self.raiz / "config" / "remocoes.json").write_text(json.dumps(dados, ensure_ascii=False, indent=1) + "\n",
                                                            encoding="utf-8", newline="\n")

    def restaurar_remocoes(self):
        (self.raiz / "config" / "remocoes.json").write_bytes(self.remocoes_originais)

    def reescrever(self, chave: str, texto: str) -> str:
        """Troca o texto de um arquivo (um trecho só), atualizando .txt, trechos e manifesto como coletor.textos."""
        caminho_man = self.raiz / "data" / "textos" / "manifesto-2024.json"
        manifesto = json.loads(caminho_man.read_text(encoding="utf-8"))
        e = manifesto[chave]
        doc = e["documento"]
        conteudo = (texto + "\n").encode("utf-8")
        destino = self.textos / "textos" / e["tipo"] / "2024" / doc.split(":", 1)[1] / f"{chave.replace(':', '-', 1)}.txt"
        destino.write_bytes(conteudo)
        sha = hashlib.sha256(texto.encode("utf-8")).hexdigest()
        ident = hashlib.sha1(f"{doc}|{chave}|0|{sha}".encode()).hexdigest()[:16]
        u16 = len(texto.encode("utf-16-le")) // 2
        trecho = {"arquivo": chave, "documento": doc, "fim": len(texto), "fim_utf16": u16, "id": ident, "inicio": 0,
                  "inicio_utf16": 0, "posicao": 0, "sha256": sha, "vetorizavel": True}
        arq = self.textos / "trechos" / e["tipo"] / "2024.jsonl"
        lista = [json.loads(linha) for linha in arq.read_text(encoding="utf-8").splitlines() if linha]
        lista = sorted([t for t in lista if t["arquivo"] != chave] + [trecho],
                       key=lambda t: (t["documento"], t["arquivo"], t["posicao"]))
        arq.write_text("".join(json.dumps(t, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
                               for t in lista), encoding="utf-8", newline="\n")
        e.update(sha256_texto=hashlib.sha256(conteudo).hexdigest(), chars=len(texto), trechos=1,
                 trechos_vetorizaveis=1)
        salvar_mapa(caminho_man, manifesto)
        return ident


class TestBarreiraContextual(unittest.TestCase):
    def test_detector_estrito_no_texto_completo_e_nas_ementas(self):
        casos = (("CPF 529,982.247-25", "cpf"), ("ID: 12.345,678-9, IFP/RJ", "rg"),
                 ("<<Tel (21) 99999-\n1234>>", "telefone"), ("pessoa@exemplo.org", "email"))
        for texto, tipo in casos:
            with self.subTest(tipo=tipo):
                meio = len(texto) // 2
                fonte = self._fonte(texto, [(0, meio), (meio, len(texto))])
                fonte.ementas["doc:2"] = texto
                fonte.linhas["remocoes"][("siscam:2", "a" * 64)] = (
                    "siscam:2", "a" * 64, texto, "2026-01-01")
                with mock.patch.object(mascara, "varrer", return_value=[]):
                    fortes, fracas = varrer_fonte(fonte, ())
                self.assertEqual(fracas, 0)
                self.assertTrue(any(o["origem"].startswith("trecho ") and o["tipo"] == tipo for o in fortes))
                self.assertTrue(any(o["origem"] == "ementa doc:2" and o["tipo"] == tipo for o in fortes))
                self.assertTrue(any(o["origem"] == "remocao siscam:2" and o["tipo"] == tipo for o in fortes))
                self.assertNotIn(texto, json.dumps(fortes, ensure_ascii=False))

    def test_estrita_preserva_recorte_e_ignora_ocorrencias_fora_do_trecho(self):
        texto = "ID: 12.345,678-9\nTexto público."
        inicio = texto.index("12.")
        fim = texto.index("\n")
        fonte = self._fonte(texto, [(inicio + 2, fim - 1), (fim + 1, len(texto))])
        with mock.patch.object(mascara, "varrer", return_value=[]):
            fortes, fracas = varrer_fonte(fonte, ())
        self.assertEqual(fracas, 0)
        self.assertEqual(fortes, [{"origem": "trecho 0000000000000000 (siscam:1)",
                                  "tipo": "rg", "inicio": 0, "fim": fim - inicio - 3}])
        fonte = self._fonte(texto, [(fim + 1, len(texto))])
        with mock.patch.object(mascara, "varrer", return_value=[]):
            self.assertEqual(varrer_fonte(fonte, ()), ([], 0))

    def _fonte(self, texto: str, intervalos: list[tuple[int, int]]) -> Fonte:
        trechos = {}
        for i, (inicio, fim) in enumerate(intervalos):
            ident = f"{i:016x}"
            pedaco = texto[inicio:fim]
            trechos[ident] = Trecho(id=ident, documento="doc:1", arquivo="siscam:1", posicao=i,
                                    texto=pedaco, sha256=hashlib.sha256(pedaco.encode()).hexdigest(),
                                    vetorizavel=True, tipo="requerimento", ano=2026, inicio=inicio, fim=fim)
        return Fonte(linhas={"remocoes": {}}, trechos=trechos, vetores={}, ementas={}, originais={},
                     remover_r2=set(), sha256_manifestos="", textos_arquivos={"siscam:1": texto})

    def test_protocolo_nao_vira_telefone_forte_no_corte(self):
        for numero in ("001189202514", "2620-1234", "02126201234"):
            with self.subTest(numero=numero):
                texto = f"E-SIC Protocolo nº {numero}, datada de hoje."
                inicio = texto.index("nº")
                fonte = self._fonte(texto, [(inicio, len(texto)), (inicio + 3, len(texto))])
                if numero != "001189202514":
                    self.assertTrue(any(o["forte"] for o in mascara.varrer(texto[inicio:])))
                with mock.patch("coletor.nuvem.fonte.mascara.varrer", wraps=mascara.varrer) as espiao:
                    fortes, fracas = varrer_fonte(fonte, ())
                espiao.assert_called_once_with(texto, frozenset())
                self.assertEqual(fortes, [])
                self.assertEqual(fracas, sum(not o["forte"] for o in mascara.varrer(texto)))

    def test_forte_atribuido_somente_aos_trechos_sobrepostos(self):
        email = "fulano@exemplo.org"
        texto = "Antes " + email + " depois"
        inicio, fim = 6, 6 + len(email)
        fonte = self._fonte(texto, [(0, inicio), (inicio, inicio + 5),
                                   (inicio + 5, len(texto)), (fim, len(texto))])
        with mock.patch("coletor.nuvem.fonte.mascara.varrer", wraps=mascara.varrer) as espiao:
            fortes, fracas = varrer_fonte(fonte, ())
        espiao.assert_called_once_with(texto, frozenset())
        self.assertEqual(fortes, [
            {"origem": "trecho 0000000000000001 (siscam:1)", "tipo": "email", "inicio": 0, "fim": 5},
            {"origem": "trecho 0000000000000002 (siscam:1)", "tipo": "email", "inicio": 0, "fim": len(email) - 5},
        ])
        self.assertEqual(fracas, 0)
        self.assertNotIn(email, json.dumps(fortes))

    def test_forte_fora_dos_trechos_nao_e_enviado(self):
        texto = "fulano@exemplo.org\nTexto público sem contato."
        fonte = self._fonte(texto, [(texto.index("Texto"), len(texto))])
        self.assertEqual(varrer_fonte(fonte, ()), ([], 0))

    def test_ementas_e_motivos_continuam_isolados(self):
        fonte = self._fonte("Texto público.", [(0, 14)])
        fonte.ementas["doc:2"] = "Contato fulano@exemplo.org"
        fonte.linhas["remocoes"][("siscam:2", "a" * 64)] = (
            "siscam:2", "a" * 64, "Pedido de pessoa@exemplo.org", "2026-01-01")
        fortes, fracas = varrer_fonte(fonte, ())
        self.assertEqual([o["origem"] for o in fortes], ["ementa doc:2", "remocao siscam:2"])
        self.assertEqual(fracas, 0)

    def test_sem_texto_completo_falha_fechado(self):
        fonte = self._fonte("Texto público.", [(0, 14)])
        fonte.textos_arquivos.clear()
        with self.assertRaises(ErroFonte):
            varrer_fonte(fonte, ())


class TestSincronizacaoCompleta(Base):
    def test_estado_guarda_commit_independente_de_dados_textos(self):
        commit_dados = "b" * 40
        primeira = self.sincronizar(commit_dados_textos=commit_dados)
        self.assertTrue(primeira.estado_gravado)
        self.assertEqual(self.consultar('SELECT "commit", commit_dados_textos FROM estado_indice'),
                         [(COMMIT, commit_dados)])
        self.assertEqual(self.sincronizar(commit_dados_textos=commit_dados).escritas, 0)
        self.assertEqual(self.sincronizar(commit_dados_textos="d" * 40).feitas["estado_indice"], 1)

    def test_migracao_commit_dados_textos_preserva_estado_e_simulacao(self):
        self.sincronizar()
        with sqlite3.connect(self.sqlite) as con:
            con.execute("ALTER TABLE estado_indice DROP COLUMN commit_dados_textos")
            con.execute("DELETE FROM d1_migrations WHERE name = '0005_estado_commit_dados_textos.sql'")
        antes = self.sqlite.read_bytes()
        self.assertEqual(self.sincronizar(simular=True, commit_dados_textos="b" * 40).plano["migracoes"], 1)
        self.assertEqual(self.sqlite.read_bytes(), antes)
        rel = self.sincronizar(commit_dados_textos="b" * 40)
        self.assertEqual(rel.feitas["migracoes"], 1)
        self.assertEqual(rel.plano["d1_trechos_gravar"], 0)
        self.assertEqual(self.consultar('SELECT "commit", commit_dados_textos FROM estado_indice'),
                         [(COMMIT, "b" * 40)])
        self.assertEqual(self.sincronizar(commit_dados_textos="b" * 40).escritas, 0)

    def test_lotes_de_vetores_persistidos_uma_vez_no_fim_da_etapa(self):
        with mock.patch("coletor.nuvem.sincronizar.LOTE_SINCRONIZACAO", 2), \
                mock.patch.object(VetoresLocal, "_gravar", autospec=True, side_effect=VetoresLocal._gravar) as gravar:
            rel = self.sincronizar()
        self.assertEqual(rel.falhas, [])
        self.assertEqual(rel.feitas["vetores_upsert"], 7)
        self.assertEqual(len(self.vetores()), 7)
        gravar.assert_called_once()

    def test_carga_completa(self):
        rel = self.sincronizar()
        self.assertEqual(rel.falhas, [])
        self.assertTrue(rel.estado_gravado)
        self.assertEqual(self.contar("documentos"), 9)
        self.assertEqual(self.contar("arquivos"), 7)  # sem removidos (900004, 900007) e duplicata (900008)
        self.assertEqual(self.contar("arquivo_documento"), 9)
        self.assertEqual(self.contar("trechos"), 6)
        self.assertEqual(self.contar("trechos_fts"), 6)
        self.assertEqual(self.contar("trechos_indexados"), 7)
        self.assertEqual(self.contar("remocoes"), 1)
        self.assertEqual(self.consultar("SELECT documento, slug, papel FROM autoria"),
                         [("doc:266596", "fulano-sintetico-de-tal", "autor")])
        self.assertEqual(self.consultar("SELECT tipo, numero, ano, pl FROM documentos WHERE id = 'doc:266596'"),
                         [("substitutivo", "1", 2024, "doc:127858")])
        self.assertEqual(self.consultar("SELECT sha256, status, r2_chave FROM arquivos "
                                        "WHERE id = 'sessao:0000000a-0000-4000-8000-0000000000b2'"),
                         [(None, "pendente_download", None)])
        self.assertEqual(sorted(r[0] for r in self.consultar(
            "SELECT documento FROM arquivo_documento WHERE arquivo = 'siscam:900001'")), ["doc:127858", "doc:266596"])
        self.assertEqual(self.consultar("SELECT ocr, confianca FROM arquivos WHERE id = 'siscam:900002'"),
                         [(1, 70.0)])

        # texto do trecho = conteudo[:-1][inicio:fim], conferido pelo sha256
        for texto, sha in self.consultar("SELECT texto, sha256 FROM trechos"):
            self.assertEqual(hashlib.sha256(texto.encode()).hexdigest(), sha)

        # originais no R2 (simulado), na chave sha256/<aa>/<bb>/<sha>
        manifesto = json.loads((self.raiz / "data" / "textos" / "manifesto-2024.json").read_text(encoding="utf-8"))
        com_r2 = [e for e in manifesto.values() if e["r2_chave"]]
        self.assertEqual(len(com_r2), 6)
        for e in com_r2:
            self.assertEqual(self.objeto_r2(e["sha256_original"]).read_bytes(),
                             (self.cache / "arquivos" / e["sha256_original"]).read_bytes())
        self.assertFalse(self.objeto_r2("fa0b85dd45022b83a97322b122308c1f80fe68f9a4a0fc72b483f086c306d8ab").exists())

        vetores = self.vetores()
        self.assertEqual(len(vetores), 7)
        self.assertEqual(vetores["ementa:doc:290006"]["metadata"],
                         {"ano": 2024, "documento": "doc:290006", "tipo": "indicacao"})
        self.assertEqual(vetores["b30b6c30b03eee82"]["metadata"],
                         {"ano": 2024, "documento": "doc:127858", "tipo": "pl"})
        self.assertEqual(len(desempacotar(vetores["b30b6c30b03eee82"]["values"])), 1024)

        estado = self.consultar('SELECT id, versao, "commit", sha256_manifestos, total, sha256_conjunto, modelo, '
                                'versao_trechos, data FROM estado_indice')
        self.assertEqual(len(estado), 1)
        _, versao, commit, sha_man, total, conjunto, modelo, vt, data = estado[0]
        self.assertEqual((commit, total, modelo, vt, data),
                         (COMMIT, 6, MODELO_LOCAL, VERSAO_TRECHOS, "2026-10-27T15:00:00Z"))
        self.assertEqual(versao, rel.versao)
        self.assertEqual(sha_man, hashlib.sha256(
            (self.raiz / "data" / "textos" / "manifesto-2024.json").read_bytes()).hexdigest())
        linhas = sorted(self.consultar("SELECT id, sha256 FROM trechos"))
        self.assertEqual(conjunto, hashlib.sha256("".join(f"{i} {s}\n" for i, s in linhas).encode()).hexdigest())

    def test_segunda_execucao_sem_escritas(self):
        primeira = self.sincronizar()
        self.assertGreater(primeira.escritas, 0)
        vetores = (self.pasta / "vetores.jsonl").read_bytes()
        segunda = self.sincronizar()
        self.assertEqual(segunda.escritas, 0, segunda.texto())
        self.assertEqual(segunda.falhas, [])
        self.assertFalse(segunda.estado_gravado)
        self.assertEqual((self.pasta / "vetores.jsonl").read_bytes(), vetores)
        self.assertEqual(segunda.versao, primeira.versao)

    def test_migracao_aplicada_uma_vez(self):
        self.assertEqual(self.sincronizar().feitas["migracoes"], len(banco.nomes_migracoes()))
        self.assertEqual(self.sincronizar().feitas["migracoes"], 0)
        self.assertEqual(self.consultar("SELECT name FROM d1_migrations"), [(n,) for n in banco.nomes_migracoes()])

    def test_fts_sem_acento(self):
        ident = self.reescrever("siscam:900003", TEXTO_LICENCA)
        self.sincronizar()
        self.assertEqual(normalizar_busca("LICENÇA Ambiental"), "licenca ambiental")
        for consulta in ("licenca", normalizar_busca("Licença"), "licenca AND praca"):
            achados = self.consultar("SELECT id FROM trechos_fts WHERE trechos_fts MATCH ?", (consulta,))
            self.assertEqual(achados, [(ident,)], consulta)
        juntos = self.consultar("SELECT t.texto FROM trechos_fts f JOIN trechos t ON t.id = f.id "
                                "WHERE trechos_fts MATCH 'licenca'")
        self.assertEqual(juntos, [(TEXTO_LICENCA,)])


class TestDiferenca(Base):
    def test_baixa_confianca_excluida_e_retirada_incrementalmente(self):
        caminho = self.textos / "trechos" / "pl" / "2024.jsonl"
        publicado = caminho.read_bytes()
        lista = [json.loads(linha) for linha in publicado.splitlines()]
        baixos = {t["id"] for t in lista if t["baixa_confianca"]}
        self.assertTrue(baixos)
        # Simula o índice anterior à decisão humana, inclusive os vetores.
        for t in lista:
            t["baixa_confianca"] = False
        caminho.write_text("".join(json.dumps(t) + "\n" for t in lista), encoding="utf-8")
        self.sincronizar()
        self.assertTrue(baixos <= set(self.vetores()))
        caminho.write_bytes(publicado)
        rel = self.sincronizar(exportar=self.tmp / "exportacoes")
        self.assertEqual(rel.falhas, [])
        self.assertEqual(rel.plano["vetores_apagar"], len(baixos))
        self.assertEqual(rel.plano["d1_trechos_apagar"], len(baixos))
        for tabela in ("trechos", "trechos_fts", "trechos_indexados"):
            ids = {r[0] for r in self.consultar(f"SELECT id FROM {tabela}")}
            self.assertFalse(baixos & ids)
        self.assertFalse(baixos & set(self.vetores()))
        self.assertEqual(self.consultar("SELECT status FROM arquivos WHERE id = 'siscam:900002'"), [("ok_ocr",)])
        self.assertEqual(caminho.read_bytes(), publicado)  # publicação não é apagada
        dump = next((self.tmp / "exportacoes").rglob("d1-*.sql")).read_text(encoding="utf-8")
        self.assertFalse(any(i in dump for i in baixos))
        self.assertEqual(self.sincronizar().escritas, 0)

    def test_novos_alterados_e_removidos(self):
        self.remover("siscam:900002", SHA_900002)
        primeira = self.sincronizar()
        self.assertEqual(primeira.falhas, [])
        self.assertEqual(self.contar("trechos"), 5)
        self.assertNotIn("f23d327591e03053", self.vetores())
        self.assertFalse(self.objeto_r2(SHA_900002).exists())

        self.restaurar_remocoes()  # 900002 volta: trecho novo
        novo = self.reescrever("siscam:900003", TEXTO_LICENCA)  # 900003 muda: um trecho sai, outro entra
        rel = self.sincronizar()
        self.assertEqual(rel.falhas, [])
        self.assertEqual(rel.plano["d1_trechos_gravar"], 2)
        self.assertEqual(rel.plano["d1_trechos_apagar"], 1)
        self.assertEqual(rel.plano["d1_trechos_fts_gravar"], 2)
        self.assertEqual(rel.plano["d1_trechos_fts_apagar"], 1)
        self.assertEqual(rel.plano["vetores_upsert"], 2)
        self.assertEqual(rel.plano["vetores_apagar"], 1)
        self.assertEqual(rel.feitas["embeddings"], 2)
        self.assertEqual(rel.plano["d1_documentos_gravar"], 0)
        self.assertEqual(rel.plano["r2_enviar"], 1)
        self.assertEqual(rel.plano["d1_remocoes_apagar"], 1)
        ids = {r[0] for r in self.consultar("SELECT id FROM trechos")}
        self.assertIn(novo, ids)
        self.assertIn("f23d327591e03053", ids)
        self.assertNotIn("2e52e27349897577", ids)
        self.assertEqual(self.contar("trechos_fts"), 6)
        vetores = self.vetores()
        self.assertIn(novo, vetores)
        self.assertNotIn("2e52e27349897577", vetores)
        self.assertEqual({r[0] for r in self.consultar("SELECT id FROM trechos_indexados")}, set(vetores))
        self.assertTrue(self.objeto_r2(SHA_900002).exists())
        self.assertEqual(self.sincronizar().escritas, 0)

    def test_remocao_propaga(self):
        self.sincronizar()
        self.assertTrue(self.objeto_r2(SHA_900002).exists())
        self.remover("siscam:900002", SHA_900002)
        rel = self.sincronizar()
        self.assertEqual(rel.falhas, [])
        self.assertEqual(rel.feitas["r2_apagar"], 1)
        self.assertFalse(self.objeto_r2(SHA_900002).exists())
        self.assertEqual(self.consultar("SELECT count(*) FROM arquivos WHERE id = 'siscam:900002'"), [(0,)])
        self.assertEqual(self.consultar("SELECT count(*) FROM arquivo_documento WHERE arquivo = 'siscam:900002'"),
                         [(0,)])
        self.assertEqual(self.consultar("SELECT count(*) FROM trechos WHERE arquivo = 'siscam:900002'"), [(0,)])
        self.assertEqual(self.contar("trechos_fts"), 5)
        self.assertEqual(self.consultar("SELECT count(*) FROM trechos_fts WHERE id = 'f23d327591e03053'"), [(0,)])
        self.assertNotIn("f23d327591e03053", self.vetores())
        self.assertEqual(self.consultar("SELECT count(*) FROM trechos_indexados WHERE id = 'f23d327591e03053'"),
                         [(0,)])
        self.assertEqual(self.consultar("SELECT chave FROM remocoes ORDER BY chave"),
                         [("siscam:900002",), ("siscam:900004",)])
        self.assertTrue(any("expurgo pendente" in a for a in rel.avisos))
        self.assertTrue(rel.estado_gravado)
        self.assertEqual(self.consultar("SELECT total FROM estado_indice"), [(5,)])


class TestEmentasFts(Base):
    def test_todos_documentos_com_ementa_mascarada_normalizada(self):
        caminho = self.raiz / "data" / "documentos" / "indicacao" / "2024.json"
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        dados[0]["ementa"] = "Indica manutenção do poste. Contato pessoa@example.org."
        caminho.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
        fonte = carregar_fonte(self.raiz, self.textos, G.LIBERADOS)
        self.assertEqual(fonte.linhas["ementas_fts"], {
            (ident,): (ident, normalizar_busca(texto)) for ident, texto in fonte.ementas.items()})
        self.assertNotIn("pessoa@example.org", fonte.ementas["doc:290006"])
        self.sincronizar()
        self.assertEqual(self.contar("ementas_fts"), self.contar("documentos"))
        self.assertEqual(dict(self.consultar("SELECT documento, texto_norm FROM ementas_fts")),
                         {i: normalizar_busca(t) for i, t in fonte.ementas.items()})
        self.assertTrue(any(i.startswith("sessao:") for i in fonte.ementas))
        self.assertIn("doc:266596", fonte.ementas)  # substitutivo, sem colisão com PL/sessão
        # doc:290001 (requerimento da fixture) já fala em "manutenção"; doc:290006 é a indicação alterada
        self.assertEqual(self.consultar("SELECT documento FROM ementas_fts WHERE ementas_fts MATCH 'manutencao' "
                                        "ORDER BY documento"), [("doc:290001",), ("doc:290006",)])
        self.assertEqual(self.sincronizar().escritas, 0)

    def test_alteracao_exclusao_e_retomada(self):
        self.sincronizar()
        caminho = self.raiz / "data" / "documentos" / "indicacao" / "2024.json"
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        dados[0]["ementa"] = "Indica iluminação do poste."
        caminho.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
        rel = self.sincronizar()
        self.assertEqual(rel.plano["d1_ementas_fts_gravar"], 1)
        self.assertEqual(rel.plano["d1_ementas_fts_apagar"], 1)
        self.assertEqual(self.consultar("SELECT texto_norm FROM ementas_fts WHERE documento = 'doc:290006'"),
                         [("indica iluminacao do poste.",)])
        self.assertEqual(self.consultar("SELECT documento FROM ementas_fts WHERE ementas_fts MATCH 'poda'"), [])
        # Uma carga interrompida depois do DELETE é reparada, mesmo com documentos já atualizado.
        with sqlite3.connect(self.sqlite) as con:
            con.execute("DELETE FROM ementas_fts WHERE documento = 'doc:290006'")
        self.assertEqual(self.sincronizar().plano["d1_ementas_fts_gravar"], 1)
        self.assertEqual(self.sincronizar().escritas, 0)
        caminho.write_text("[]\n", encoding="utf-8")
        rel = self.sincronizar()
        self.assertEqual(rel.plano["d1_ementas_fts_apagar"], 1)
        self.assertEqual(rel.plano["d1_ementas_fts_gravar"], 0)
        self.assertEqual(self.consultar("SELECT documento FROM ementas_fts WHERE documento = 'doc:290006'"), [])
        self.assertEqual(self.sincronizar().escritas, 0)

    def test_migracao_incremental_preenche_sem_regravar_documentos(self):
        self.assertIn("0003_ementas_fts.sql", banco.nomes_migracoes())
        self.sincronizar()
        with sqlite3.connect(self.sqlite) as con:
            con.execute("DROP TABLE ementas_fts")
            con.execute("DELETE FROM d1_migrations WHERE name = '0003_ementas_fts.sql'")
        rel = self.sincronizar()
        self.assertEqual(rel.feitas["migracoes"], 1)
        self.assertEqual(rel.plano["d1_documentos_gravar"], 0)
        self.assertEqual(rel.plano["d1_trechos_gravar"], 0)
        self.assertEqual(rel.plano["d1_ementas_fts_gravar"], self.contar("documentos"))
        self.assertEqual(self.sincronizar().escritas, 0)

    def test_repetir_lote_nao_duplica_ementa(self):
        self.sincronizar()
        alteracao = banco.Alteracao.de("ementas_fts", gravar=[("doc:290006", "indica iluminacao do poste.")])
        unidades = banco.unidades([alteracao])
        self.assertEqual(len(unidades), 1)
        self.assertEqual(len(unidades[0]), 2)  # DELETE + INSERT sempre juntos no lote remoto
        local = banco.BancoLocal(self.sqlite)
        try:
            local.aplicar([alteracao])
            local.aplicar([alteracao])  # resposta perdida e repetição do mesmo lote
        finally:
            local.fechar()
        self.assertEqual(self.consultar("SELECT texto_norm FROM ementas_fts WHERE documento = 'doc:290006'"),
                         [("indica iluminacao do poste.",)])

    def test_remocao_de_arquivo_preserva_ementa_publica(self):
        self.sincronizar()
        antes = self.consultar("SELECT documento, texto_norm FROM ementas_fts ORDER BY documento")
        self.remover("siscam:900002", SHA_900002)
        rel = self.sincronizar()
        self.assertEqual(rel.plano["d1_ementas_fts_apagar"], 0)
        self.assertEqual(rel.plano["d1_ementas_fts_gravar"], 0)
        self.assertEqual(self.consultar("SELECT documento, texto_norm FROM ementas_fts ORDER BY documento"), antes)


class TestSegurancaEFalhas(Base):
    def argumentos_cli(self):
        return ["--ambiente", "local", "--sqlite", str(self.sqlite), "--raiz", str(self.raiz),
                "--textos", str(self.textos), "--cache", str(self.cache), "--commit", COMMIT]

    def test_cli_commit_dados_textos_padrao_vem_do_worktree_nao_do_actions(self):
        commit_dados = "b" * 40
        with mock.patch.dict("os.environ", {"GITHUB_SHA": "a" * 40}), \
                mock.patch.object(cli.subprocess, "run", return_value=mock.Mock(returncode=0, stdout=commit_dados + "\n")) as git, \
                mock.patch.object(cli.mascara, "liberados", return_value=G.LIBERADOS), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(self.argumentos_cli()), 0)
        git.assert_called_once_with(["git", "-C", str(self.textos), "rev-parse", "HEAD"],
                                    capture_output=True, text=True, timeout=15)
        self.assertEqual(self.consultar('SELECT "commit", commit_dados_textos FROM estado_indice'),
                         [(COMMIT, commit_dados)])

    def test_cli_commit_dados_textos_explicito_nao_consulta_git(self):
        with mock.patch.object(cli.subprocess, "run") as git, \
                mock.patch.object(cli.mascara, "liberados", return_value=G.LIBERADOS), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(self.argumentos_cli() + ["--commit-dados-textos", "d" * 40]), 0)
        git.assert_not_called()
        self.assertEqual(self.consultar("SELECT commit_dados_textos FROM estado_indice"), [("d" * 40,)])

    def test_cli_commit_dados_textos_indisponivel(self):
        for resultado in (mock.Mock(returncode=128, stdout=""), OSError("git ausente")):
            with self.subTest(resultado=resultado):
                opcoes = {"side_effect": resultado} if isinstance(resultado, OSError) else {"return_value": resultado}
                with mock.patch.object(cli.subprocess, "run", **opcoes):
                    self.assertIsNone(cli.commit_dados_textos(self.textos))

    def test_cli_falha_no_actions_orienta_reexecucao_sem_dados_pessoais(self):
        for falha in (ErroFonte("fonte inválida"), ErroNuvem("nuvem indisponível"),
                      ErroBarreira([{"origem": "trecho sintético", "tipo": "telefone", "inicio": 0, "fim": 8}])):
            with self.subTest(falha=type(falha).__name__):
                erro = io.StringIO()
                with mock.patch.dict("os.environ", {"GITHUB_ACTIONS": "true"}), \
                        mock.patch.object(cli, "sincronizar", side_effect=falha), \
                        contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(erro):
                    self.assertEqual(cli.main(self.argumentos_cli() + ["--commit-dados-textos", "b" * 40]), 1)
                self.assertIn("::error::", erro.getvalue())
                self.assertIn("re-execute com workflow_dispatch", erro.getvalue())

    def test_cli_falhas_no_relatorio_orientam_reexecucao_so_no_actions(self):
        (self.cache / "arquivos" / SHA_900005).unlink()
        for actions in ("", "true"):
            erro = io.StringIO()
            with mock.patch.dict("os.environ", {"GITHUB_ACTIONS": actions}), \
                    mock.patch.object(cli.mascara, "liberados", return_value=G.LIBERADOS), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(erro):
                self.assertEqual(cli.main(self.argumentos_cli() + ["--commit-dados-textos", "b" * 40]), 1)
            self.assertEqual("re-execute com workflow_dispatch" in erro.getvalue(), bool(actions))

    def test_fonte_conserva_texto_completo_e_intervalos(self):
        texto = "Introdução\nE-SIC Protocolo nº 001189202514, datada de hoje.\n"
        ident = self.reescrever("siscam:900003", texto)
        fonte = carregar_fonte(self.raiz, self.textos, G.LIBERADOS)
        self.assertEqual(fonte.textos_arquivos["siscam:900003"], texto)
        trecho = fonte.trechos[ident]
        self.assertEqual((trecho.inicio, trecho.fim, trecho.texto), (0, len(texto), texto))

    def test_barreira_de_pii_aborta_sem_gravar(self):
        with self.assertRaises(ErroBarreira) as ctx:
            self.sincronizar(liberados=frozenset())  # o telefone do gabinete deixa de ser liberado
        mensagem = str(ctx.exception)
        self.assertIn("telefone", mensagem)
        self.assertNotIn("2620", mensagem)
        self.assertFalse(self.sqlite.exists())
        self.assertFalse((self.pasta / "r2").exists())
        self.assertFalse((self.pasta / "vetores.jsonl").exists())

    def test_cli_aborta_na_barreira(self):
        # a raiz das fixtures não libera o telefone do gabinete: a CLI recusa a carga
        saida, erro = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(erro):
            codigo = cli.main(["--ambiente", "local", "--sqlite", str(self.sqlite), "--raiz", str(self.raiz),
                               "--textos", str(self.textos), "--cache", str(self.cache), "--commit", COMMIT])
        self.assertEqual(codigo, 1)
        self.assertIn("barreira de PII", erro.getvalue())
        self.assertNotIn("2620", erro.getvalue() + saida.getvalue())
        self.assertFalse(self.sqlite.exists())

    def test_simular_nao_grava(self):
        rel = self.sincronizar(simular=True, exportar=self.tmp / "exp")
        self.assertEqual(rel.escritas, 0)
        self.assertEqual(rel.plano["migracoes"], len(banco.nomes_migracoes()))
        self.assertEqual(rel.plano["r2_enviar"], 6)
        self.assertEqual(rel.plano["d1_documentos_gravar"], 9)
        self.assertEqual(rel.plano["d1_trechos_gravar"], 6)
        self.assertEqual(rel.plano["vetores_upsert"], 7)
        self.assertEqual(rel.plano["estado_indice"], 1)
        self.assertEqual(rel.plano["exportacao_arquivos"], 3)
        self.assertIn("simulação", rel.texto())
        self.assertFalse(self.sqlite.exists())
        self.assertFalse(self.pasta.exists())
        self.assertFalse((self.tmp / "exp").exists())

        self.sincronizar()
        antes = self.sqlite.read_bytes()
        rel = self.sincronizar(simular=True)
        self.assertEqual(rel.escritas, 0)
        for chave in ("migracoes", "r2_enviar", "d1_trechos_gravar", "d1_documentos_gravar", "vetores_upsert",
                      "vetores_apagar", "estado_indice"):
            self.assertEqual(rel.plano[chave], 0, chave)
        self.assertEqual(self.sqlite.read_bytes(), antes)

    def test_estado_nao_gravado_em_falha_no_meio(self):
        def quebrar(ambiente):
            def falhar(textos):
                raise RuntimeError("falha simulada nos embeddings")
            ambiente.embedder = falhar

        with self.assertRaises(RuntimeError):
            self.sincronizar(ajustar=quebrar)
        self.assertEqual(self.contar("trechos"), 6)  # o D1 já foi atualizado
        self.assertEqual(self.contar("estado_indice"), 0)
        self.assertEqual(self.contar("trechos_indexados"), 0)

        rel = self.sincronizar()
        self.assertEqual(rel.plano["vetores_upsert"], 7)
        self.assertEqual(rel.plano["d1_trechos_gravar"], 0)
        self.assertEqual(self.contar("estado_indice"), 1)

    def test_original_ausente_no_cache(self):
        (self.cache / "arquivos" / SHA_900005).unlink()
        rel = self.sincronizar()
        self.assertEqual(len(rel.falhas), 1)
        self.assertIn("siscam:900005", rel.falhas[0])
        self.assertFalse(rel.estado_gravado)
        self.assertEqual(self.contar("estado_indice"), 0)
        self.assertEqual(self.consultar("SELECT count(*) FROM arquivos WHERE id = 'siscam:900005'"), [(0,)])

        (self.cache / "arquivos" / SHA_900005).write_bytes(G.ORIGINAIS["siscam:900005"])
        rel = self.sincronizar()
        self.assertEqual(rel.falhas, [])
        self.assertEqual(rel.feitas["r2_enviar"], 1)
        self.assertEqual(self.contar("arquivos"), 7)
        self.assertEqual(self.contar("estado_indice"), 1)


class TestExportacaoEReconstrucao(Base):
    def test_exportacao_deterministica(self):
        rel = self.sincronizar(exportar=self.tmp / "exp1")
        versao = rel.versao
        pasta = self.tmp / "exp1" / versao
        nomes = sorted(p.name for p in pasta.iterdir())
        self.assertEqual(nomes, sorted(["SHA256SUMS", f"d1-{versao}.sql", f"vetores-{versao}-001.jsonl.gz"]))
        somas = (pasta / "SHA256SUMS").read_text(encoding="ascii").splitlines()
        self.assertEqual(len(somas), 2)
        for linha in somas:
            sha, nome = linha.split("  ", 1)
            self.assertEqual(hashlib.sha256((pasta / nome).read_bytes()).hexdigest(), sha)

        gz = (pasta / f"vetores-{versao}-001.jsonl.gz").read_bytes()
        self.assertEqual(gz[:2], b"\x1f\x8b")
        self.assertEqual(gz[4:8], b"\x00\x00\x00\x00")  # mtime = 0
        self.assertEqual(gz[3] & 0x08, 0)  # sem nome de arquivo
        linhas = gzip.decompress(gz).decode("utf-8").splitlines()
        self.assertEqual(len(linhas), 7)
        primeiro = json.loads(linhas[0])
        self.assertEqual(sorted(primeiro), ["id", "metadata", "values"])
        self.assertEqual(len(desempacotar(primeiro["values"])), 1024)
        self.assertEqual([json.loads(x)["id"] for x in linhas], sorted(json.loads(x)["id"] for x in linhas))

        dump = (pasta / f"d1-{versao}.sql").read_text(encoding="utf-8")
        self.assertNotIn('INSERT INTO "trechos_fts"', dump)
        self.assertNotIn('INSERT INTO "ementas_fts"', dump)
        self.assertEqual(dump.count('INSERT INTO "trechos" '), 6)
        self.assertEqual(dump.count('INSERT INTO "documentos" '), 9)

        bucket = self.pasta / "r2" / BUCKET_EXPORTACOES_LOCAL / versao
        self.assertEqual(sorted(p.name for p in bucket.iterdir()), nomes)
        self.assertEqual(rel.feitas["exportacao_enviar"], 3)

        outra = self.sincronizar(exportar=self.tmp / "exp2")
        self.assertEqual(outra.versao, versao)
        self.assertEqual(outra.escritas, 0)  # If-None-Match: os objetos já existem
        for nome in nomes:
            self.assertEqual((self.tmp / "exp2" / versao / nome).read_bytes(), (pasta / nome).read_bytes())

    def test_exportacao_em_partes_limitadas_deterministicas_e_sem_reenvio(self):
        limite = 6_000
        with mock.patch("coletor.nuvem.sincronizar.LIMITE_PARTE_EXPORTACAO", limite):
            primeira = self.sincronizar(exportar=self.tmp / "exp1")
            segunda = self.sincronizar(exportar=self.tmp / "exp2")
        versao = primeira.versao
        pasta = self.tmp / "exp1" / versao
        arquivos = {p.name: p.read_bytes() for p in pasta.iterdir()}
        somas = _ler_somas_exportacao(versao, arquivos["SHA256SUMS"])
        sqls, vetores = _nomes_exportacao(versao, somas)
        self.assertGreater(len(sqls), 1)
        self.assertGreater(len(vetores), 1)
        self.assertEqual(vetores, [f"vetores-{versao}-{i:03d}.jsonl.gz" for i in range(1, len(vetores) + 1)])
        self.assertEqual(sqls, [f"d1-{versao}-{i:03d}.sql" for i in range(1, len(sqls) + 1)])
        self.assertEqual(set(arquivos), set(somas) | {"SHA256SUMS"})
        self.assertEqual(primeira.feitas["exportacao_enviar"], len(arquivos))
        self.assertEqual(primeira.plano["exportacao_arquivos"], len(arquivos))
        self.assertEqual(segunda.versao, versao)
        self.assertEqual(segunda.escritas, 0)
        bucket = self.pasta / "r2" / BUCKET_EXPORTACOES_LOCAL / versao
        for nome, soma in somas.items():
            self.assertLessEqual(len(arquivos[nome]), limite)
            self.assertEqual(hashlib.sha256(arquivos[nome]).hexdigest(), soma)
        for nome, dados in arquivos.items():
            self.assertEqual((self.tmp / "exp2" / versao / nome).read_bytes(), dados)
            self.assertEqual((bucket / nome).read_bytes(), dados)
        linhas = []
        for nome in vetores:
            gz = arquivos[nome]
            self.assertEqual(gz[4:8], b"\0" * 4)
            self.assertEqual(gz[3] & 0x08, 0)
            texto = gzip.decompress(gz)
            self.assertTrue(texto.endswith(b"\n"))
            linhas.extend(json.loads(l) for l in texto.splitlines())
        self.assertEqual([v["id"] for v in linhas], sorted(self.vetores()))
        dump = _ler_dump(b"".join(arquivos[n] for n in sqls))
        self.assertEqual(len(dump["documentos"]), 9)
        self.assertEqual(len(dump["trechos"]), 6)

    def test_exportacao_antiga_de_arquivo_unico_nao_reenvia(self):
        rel = self.sincronizar(exportar=self.tmp / "exp1")
        versao = rel.versao
        bucket = self.pasta / "r2" / BUCKET_EXPORTACOES_LOCAL / versao
        (bucket / f"vetores-{versao}-001.jsonl.gz").rename(bucket / f"vetores-{versao}.jsonl.gz")
        dados = {p.name: p.read_bytes() for p in bucket.iterdir() if p.name != "SHA256SUMS"}
        somas = "".join(f"{hashlib.sha256(b).hexdigest()}  {n}\n" for n, b in sorted(dados.items())).encode("ascii")
        (bucket / "SHA256SUMS").write_bytes(somas)
        antes = {p.name: p.read_bytes() for p in bucket.iterdir()}
        outra = self.sincronizar(exportar=self.tmp / "exp2")
        self.assertEqual(outra.feitas["exportacao_enviar"], 0)
        self.assertEqual({p.name: p.read_bytes() for p in bucket.iterdir()}, antes)

    def test_publicacao_em_partes_interrompida_nao_reenvia_partes_confirmadas(self):
        enviar = R2Local.enviar

        def interromper(r2, bucket, chave, *args, **kw):
            if bucket == BUCKET_EXPORTACOES_LOCAL and chave.endswith("-002.jsonl.gz"):
                raise ErroNuvem("interrupção sintética")
            return enviar(r2, bucket, chave, *args, **kw)

        with mock.patch("coletor.nuvem.sincronizar.LIMITE_PARTE_EXPORTACAO", 6_000):
            with mock.patch.object(R2Local, "enviar", interromper), self.assertRaises(ErroNuvem):
                self.sincronizar(exportar=self.tmp / "exp")
            bucket = self.pasta / "r2" / BUCKET_EXPORTACOES_LOCAL
            presentes = {p.relative_to(bucket).as_posix(): p.read_bytes() for p in bucket.rglob("*") if p.is_file()}
            self.assertTrue(presentes)
            self.assertFalse(any(n.endswith("SHA256SUMS") for n in presentes))

            def conferir(r2, nome_bucket, chave, *args, **kw):
                if nome_bucket == BUCKET_EXPORTACOES_LOCAL:
                    self.assertNotIn(chave, presentes)
                return enviar(r2, nome_bucket, chave, *args, **kw)

            with mock.patch.object(R2Local, "enviar", conferir):
                rel = self.sincronizar(exportar=self.tmp / "exp")
            for nome, dados in presentes.items():
                self.assertEqual((bucket / nome).read_bytes(), dados)
            self.assertTrue((bucket / rel.versao / "SHA256SUMS").is_file())
            self.assertEqual(self.sincronizar(exportar=self.tmp / "exp").escritas, 0)

    def test_limite_considera_cabecalho_e_rodape_gzip(self):
        linhas = [hashlib.sha256(str(i).encode()).digest() + b"\n" for i in range(3)]
        limite = sum(map(len, linhas))
        self.assertGreater(len(gzip_deterministico(b"".join(linhas))), limite)
        with mock.patch("coletor.nuvem.sincronizar.LIMITE_PARTE_EXPORTACAO", limite):
            partes = _partes_exportacao(linhas, comprimir=True)
            self.assertGreater(len(partes), 1)
            self.assertTrue(all(len(p) <= limite for p in partes))
            self.assertEqual(b"".join(gzip.decompress(p) for p in partes), b"".join(linhas))
        with mock.patch("coletor.nuvem.sincronizar.LIMITE_PARTE_EXPORTACAO", 10):
            with self.assertRaisesRegex(ErroNuvem, "linha excede"):
                _partes_exportacao(linhas[:1], comprimir=True)

    def test_somas_rejeitam_lacunas_mistura_e_caminhos_externos(self):
        versao = "a" * 16
        for nomes in ([f"d1-{versao}.sql", f"vetores-{versao}-002.jsonl.gz"],
                      [f"d1-{versao}.sql", f"vetores-{versao}.jsonl.gz", f"vetores-{versao}-001.jsonl.gz"],
                      [f"d1-{versao}.sql", "../vetores.jsonl.gz"],
                      [f"d1-{versao}.sql", f"vetores-{versao}.jsonl.gz", f"vetores-{versao}.jsonl.gz"]):
            with self.subTest(nomes=nomes), self.assertRaisesRegex(ErroNuvem, "SHA256SUMS inválido"):
                sums = "".join(f"{'0' * 64}  {n}\n" for n in nomes).encode("ascii")
                _ler_somas_exportacao(versao, sums)

    def test_exportacao_importavel(self):
        rel = self.sincronizar(exportar=self.tmp / "exp")
        dump = (self.tmp / "exp" / rel.versao / f"d1-{rel.versao}.sql").read_text(encoding="utf-8")
        con = sqlite3.connect(":memory:")
        try:
            con.executescript((Path(__file__).resolve().parents[1] / "worker" / "migrations" / "0001_inicial.sql")
                              .read_text(encoding="utf-8"))
            con.executescript(dump)
            self.assertEqual(con.execute("SELECT count(*) FROM trechos").fetchone()[0], 6)
            self.assertEqual(con.execute("SELECT count(*) FROM trechos_indexados").fetchone()[0], 7)
        finally:
            con.close()

    def test_reconstruir(self):
        self.sincronizar()
        con = sqlite3.connect(self.sqlite)
        con.execute("DELETE FROM trechos")
        con.execute("DELETE FROM documentos WHERE tipo = 'pl'")
        con.execute("INSERT INTO trechos_fts (rowid, id, texto_norm) VALUES (1, 'lixo', 'lixo')")
        con.execute("INSERT INTO ementas_fts (documento, texto_norm) VALUES ('lixo', 'lixo')")
        con.execute("INSERT INTO pessoas VALUES ('fantasma', 'Fantasma', NULL)")
        con.commit()
        con.close()
        rel = self.sincronizar(reconstruir=True)
        self.assertEqual(rel.falhas, [])
        self.assertEqual(rel.plano["vetores_upsert"], 7)
        self.assertEqual(self.contar("trechos"), 6)
        self.assertEqual(self.contar("trechos_fts"), 6)
        self.assertEqual(self.contar("documentos"), 9)
        self.assertEqual(self.contar("ementas_fts"), 9)
        self.assertEqual(self.consultar("SELECT documento FROM ementas_fts WHERE documento = 'lixo'"), [])
        self.assertEqual(self.consultar("SELECT slug FROM pessoas"), [("fulano-sintetico-de-tal",)])
        self.assertEqual(self.consultar("SELECT count(*) FROM trechos_fts WHERE id = 'lixo'"), [(0,)])
        self.assertEqual(self.contar("estado_indice"), 1)
        self.assertEqual(len(self.vetores()), 7)
        self.assertEqual(self.sincronizar().escritas, 0)

    def test_fts_inconsistente_e_refeito(self):
        self.sincronizar()
        con = sqlite3.connect(self.sqlite)
        con.execute("DELETE FROM trechos_fts")
        con.commit()
        con.close()
        rel = self.sincronizar()
        self.assertEqual(rel.plano["d1_fts_reconstruir"], 1)
        self.assertEqual(self.contar("trechos_fts"), 6)


if __name__ == "__main__":
    unittest.main()
