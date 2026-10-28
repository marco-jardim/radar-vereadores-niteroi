"""Remoções: leitura, validação e expurgo integrado offline de textos/nuvem/exportações.

Uso: python -m unittest tests.test_remocoes
"""
from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from coletor import remocoes, textos
from coletor.arquivos import salvar_mapa
from coletor.nuvem.ambientes import BUCKET_EXPORTACOES_LOCAL
from coletor.nuvem.local import R2Local
from coletor.nuvem.rede import ErroNuvem
from coletor.nuvem.sincronizar import _ler_dump, _ler_somas_exportacao, _nomes_exportacao
from coletor.validar import validar_remocoes
from tests.test_nuvem_sincronizar import Base as _BaseNuvem, FIXTURES, G, SHA_900002

SHA_A = "a" * 64
SHA_B = "0123456789abcdef" * 4
FONTE = "https://github.com/marco-jardim/radar-vereadores-niteroi/issues"


def _item(chave: str, sha256: str, data: str = "2025-01-15", **extra) -> dict:
    item = {"chave": chave, "sha256": sha256, "motivo": "Pedido de titular (exemplo sintético).",
            "fonte": FONTE, "data": data}
    item.update(extra)
    return item


class _ComRaiz(unittest.TestCase):
    def setUp(self) -> None:
        remocoes.limpar_cache()
        self._tmp = tempfile.TemporaryDirectory()
        self.raiz = Path(self._tmp.name)
        (self.raiz / "config").mkdir()

    def tearDown(self) -> None:
        remocoes.limpar_cache()
        self._tmp.cleanup()

    def gravar(self, dados: object) -> None:
        texto = json.dumps(dados, ensure_ascii=False, indent=1) + "\n"
        (self.raiz / "config" / "remocoes.json").write_bytes(texto.encode("utf-8"))


class TestCarregar(_ComRaiz):
    def test_arquivo_ausente(self) -> None:
        self.assertEqual(remocoes.carregar(self.raiz), [])
        self.assertEqual(remocoes.chaves_removidas(self.raiz), set())
        self.assertFalse(remocoes.esta_removido(self.raiz, "siscam:1", SHA_A))

    def test_lista_vazia(self) -> None:
        self.gravar({"remocoes": []})
        self.assertEqual(remocoes.carregar(self.raiz), [])
        self.assertEqual(remocoes.chaves_removidas(self.raiz), set())
        self.assertEqual(validar_remocoes(self.raiz), [])

    def test_com_itens(self) -> None:
        itens = [_item("siscam:123", SHA_A), _item("sessao:00000000-0000-4000-8000-0000000000a1", SHA_B,
                                                   data="2025-02-01")]
        self.gravar({"remocoes": itens})
        self.assertEqual(remocoes.carregar(self.raiz), itens)
        self.assertEqual(remocoes.chaves_removidas(self.raiz),
                         {("siscam:123", SHA_A), ("sessao:00000000-0000-4000-8000-0000000000a1", SHA_B)})
        self.assertEqual(validar_remocoes(self.raiz), [])

    def test_aceita_pasta_config_e_arquivo(self) -> None:
        self.gravar({"remocoes": [_item("siscam:123", SHA_A)]})
        esperado = {("siscam:123", SHA_A)}
        self.assertEqual(remocoes.chaves_removidas(self.raiz / "config"), esperado)
        self.assertEqual(remocoes.chaves_removidas(self.raiz / "config" / "remocoes.json"), esperado)
        self.assertEqual(remocoes.chaves_removidas(str(self.raiz)), esperado)

    def test_copia_nao_altera_o_cache(self) -> None:
        self.gravar({"remocoes": [_item("siscam:123", SHA_A)]})
        remocoes.carregar(self.raiz)[0]["chave"] = "siscam:999"
        self.assertEqual(remocoes.carregar(self.raiz)[0]["chave"], "siscam:123")

    def test_cache_renovado_quando_o_arquivo_muda(self) -> None:
        self.gravar({"remocoes": []})
        self.assertFalse(remocoes.esta_removido(self.raiz, "siscam:123"))
        self.gravar({"remocoes": [_item("siscam:123", SHA_A)]})  # tamanho diferente
        self.assertTrue(remocoes.esta_removido(self.raiz, "siscam:123"))

    def test_estrutura_invalida_e_erro(self) -> None:
        for dados in ([], {"remocoes": {}}, {"outro": []}, {"remocoes": [{"chave": "siscam:1"}]},
                      {"remocoes": ["siscam:1"]}):
            with self.subTest(dados=dados):
                remocoes.limpar_cache()
                self.gravar(dados)
                with self.assertRaises(ValueError):
                    remocoes.carregar(self.raiz)
        remocoes.limpar_cache()
        (self.raiz / "config" / "remocoes.json").write_bytes(b"{nao e json")
        with self.assertRaises(ValueError):
            remocoes.chaves_removidas(self.raiz)


class TestEstaRemovido(_ComRaiz):
    def setUp(self) -> None:
        super().setUp()
        self.gravar({"remocoes": [_item("siscam:123", SHA_A)]})

    def test_por_chave_por_sha_ou_ambos(self) -> None:
        self.assertTrue(remocoes.esta_removido(self.raiz, "siscam:123"))
        self.assertTrue(remocoes.esta_removido(self.raiz, chave="siscam:123", sha256=SHA_B))  # nova versão
        self.assertTrue(remocoes.esta_removido(self.raiz, sha256=SHA_A))
        self.assertTrue(remocoes.esta_removido(self.raiz, chave="siscam:456", sha256=SHA_A))  # mesmo original
        self.assertTrue(remocoes.esta_removido(self.raiz, sha256=SHA_A.upper()))
        self.assertFalse(remocoes.esta_removido(self.raiz, "siscam:456", SHA_B))
        self.assertFalse(remocoes.esta_removido(self.raiz, "siscam:1234"))
        self.assertFalse(remocoes.esta_removido(self.raiz, sha256=SHA_B))

    def test_aceita_lista_conjunto_e_indice(self) -> None:
        lista = remocoes.carregar(self.raiz)
        pares = remocoes.chaves_removidas(self.raiz)
        indice = remocoes.indice(self.raiz)
        for fonte in (lista, pares, indice):
            with self.subTest(fonte=type(fonte).__name__):
                self.assertTrue(remocoes.esta_removido(fonte, "siscam:123"))
                self.assertTrue(remocoes.esta_removido(fonte, sha256=SHA_A))
                self.assertFalse(remocoes.esta_removido(fonte, "siscam:9", SHA_B))
        self.assertTrue(indice.contem("siscam:123"))
        self.assertIs(remocoes.indice(indice), indice)

    def test_sem_chave_nem_sha_e_erro(self) -> None:
        with self.assertRaises(ValueError):
            remocoes.esta_removido(self.raiz)


class TestValidacao(_ComRaiz):
    def test_problemas_de_campos_e_https(self) -> None:
        casos = {
            "fonte http": _item("siscam:1", SHA_A, fonte="http://exemplo.org/x"),
            "sem motivo": {k: v for k, v in _item("siscam:1", SHA_A).items() if k != "motivo"},
            "campo extra": _item("siscam:1", SHA_A, extra="x"),
            "chave sem origem": _item("arquivo:1", SHA_A),
            "siscam não numérico": _item("siscam:abc", SHA_A),
            "siscam com zero à esquerda": _item("siscam:012", SHA_A),
            "sessao com id numérico": _item("sessao:5001", SHA_A),
            "guid maiúsculo": _item("sessao:00000000-0000-4000-8000-0000000000A1", SHA_A),
            "sha curto": _item("siscam:1", "abc"),
            "sha maiúsculo": _item("siscam:1", SHA_A.upper()),
            "data inválida": _item("siscam:1", SHA_A, data="2025-02-30"),
            "data futura": _item("siscam:1", SHA_A, data="2999-01-01"),
        }
        for nome, item in casos.items():
            with self.subTest(caso=nome):
                self.gravar({"remocoes": [item]})
                self.assertTrue(validar_remocoes(self.raiz), nome)

    def test_ordem_e_repeticao(self) -> None:
        self.gravar({"remocoes": [_item("siscam:2", SHA_A, data="2025-02-01"), _item("siscam:1", SHA_A)]})
        self.assertTrue(validar_remocoes(self.raiz))
        self.gravar({"remocoes": [_item("siscam:1", SHA_A), _item("siscam:1", SHA_A)]})
        self.assertTrue(validar_remocoes(self.raiz))

    def test_formato_do_arquivo(self) -> None:
        texto = json.dumps({"remocoes": [_item("siscam:1", SHA_A)]}, ensure_ascii=False, indent=2) + "\n"
        (self.raiz / "config" / "remocoes.json").write_bytes(texto.encode("utf-8"))
        self.assertTrue(validar_remocoes(self.raiz))


class TestPropagacao(_BaseNuvem):
    """Somente cópias temporárias das fixtures; SQLite, R2 e vetores locais."""

    def manifesto(self):
        return json.loads((self.raiz / "data/textos/manifesto-2024.json").read_text(encoding="utf-8"))

    def processar_textos(self):
        baixar = mock.Mock(side_effect=AssertionError("teste não pode acessar a rede"))
        op = textos.Opcoes(raiz=self.raiz, textos=self.textos, cache=self.cache,
                           anos=frozenset({1900}), max_arquivos=1, sem_rede=True,
                           liberados=G.LIBERADOS, pessoas=G.PESSOAS, hoje="2026-10-28", baixar=baixar,
                           versoes_ferramentas={})
        resultado = textos.executar(op)
        baixar.assert_not_called()
        return resultado

    def adicionar_segunda_remocao(self):
        sha = self.manifesto()["siscam:900005"]["sha256_original"]
        caminho = self.raiz / "config/remocoes.json"
        dados = json.loads(caminho.read_bytes())
        dados["remocoes"].append(_item("siscam:900005", sha, data="2026-01-17"))
        caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        self.processar_textos()

    def test_sem_pendencias_nao_consulta_bucket_de_exportacoes(self):
        def ajustar(ambiente):
            ambiente.r2.listar = mock.Mock(side_effect=AssertionError("listagem desnecessária"))
            obter = ambiente.r2.obter

            def conferir(bucket, chave):
                self.assertNotEqual(bucket, BUCKET_EXPORTACOES_LOCAL)
                return obter(bucket, chave)

            ambiente.r2.obter = conferir

        # Tombstones das fixtures não tornam toda carga/simulação um expurgo.
        self.sincronizar(ajustar=ajustar, simular=True)
        self.sincronizar(ajustar=ajustar)
        self.assertEqual(self.sincronizar(ajustar=ajustar).escritas, 0)

    def test_simular_expurgo_pendente_nao_escreve_nem_registra(self):
        self.sincronizar(exportar=self.cache / "exportacoes")
        self.remover("siscam:900002", SHA_900002)
        self.processar_textos()

        def fotografia():
            return {p.relative_to(self.tmp): p.read_bytes() for p in self.tmp.rglob("*") if p.is_file()}

        antes = fotografia()
        with mock.patch.object(R2Local, "enviar", side_effect=AssertionError("simulação escreveu")), \
                mock.patch.object(R2Local, "apagar", side_effect=AssertionError("simulação apagou")):
            rel = self.sincronizar(simular=True)
        self.assertEqual(rel.plano["exportacao_regravar"], 1)
        self.assertEqual(rel.escritas, 0)
        self.assertEqual(fotografia(), antes)

    def test_sha256sums_divergente_nao_afetado_so_avisa(self):
        versao = self.sincronizar(exportar=self.cache / "exportacoes").versao
        somas = self.pasta / "r2" / BUCKET_EXPORTACOES_LOCAL / versao / "SHA256SUMS"
        somas.write_bytes(b"divergencia sintetica\n")
        # Há remoção nova, mas nenhum arquivo dessa exportação coincide com ela.
        self.remover("siscam:999999", SHA_A)
        rel = self.sincronizar()
        self.assertEqual(rel.feitas["exportacao_enviar"], 0)
        self.assertEqual(rel.feitas["exportacao_apagar"], 0)
        self.assertTrue(any("difere" in a for a in rel.avisos))
        self.assertEqual(somas.read_bytes(), b"divergencia sintetica\n")

    def test_sha256sums_divergente_afetado_impede_confirmar_remocao(self):
        versao = self.sincronizar(exportar=self.cache / "exportacoes").versao
        somas = self.pasta / "r2" / BUCKET_EXPORTACOES_LOCAL / versao / "SHA256SUMS"
        antes = somas.read_bytes()
        estado = self.consultar("SELECT * FROM estado_indice")
        somas.write_bytes(b"divergencia sintetica\n")
        self.remover("siscam:900002", SHA_900002)
        self.processar_textos()
        with self.assertRaisesRegex(ErroNuvem, "SHA256SUMS divergente"):
            self.sincronizar()
        self.assertEqual(self.consultar("SELECT * FROM estado_indice"), estado)
        self.assertTrue(self.consultar("SELECT id FROM arquivos WHERE id = 'siscam:900002'"))
        self.assertEqual(somas.read_bytes(), b"divergencia sintetica\n")
        somas.write_bytes(antes)
        self.sincronizar()
        self.assertFalse(somas.exists())

    def test_textos_manifesto_d1_vetores_r2_e_nao_retorna(self):
        for por_sha in (False, True):
            with self.subTest(por_sha=por_sha):
                # A segunda variante usa outra chave: o SHA, sozinho, deve bastar.
                self.restaurar_remocoes()
                chave = "siscam:900002"
                antes = self.manifesto()[chave]
                self.sincronizar()
                ids = {r[0] for r in self.consultar("SELECT id FROM trechos WHERE arquivo = ?", (chave,))}
                self.assertTrue(ids)
                self.remover("siscam:999999" if por_sha else chave, SHA_900002 if por_sha else SHA_A)
                self.processar_textos()
                depois = self.manifesto()[chave]
                self.assertEqual(depois["status"], "removido")
                self.assertEqual((depois["sha256_original"], depois["bytes"]),
                                 (antes["sha256_original"], antes["bytes"]))
                self.assertEqual(set(depois), set(antes))  # contrato congelado: sem campo motivo extra
                self.assertIsNone(depois["sha256_texto"])
                self.assertIsNone(depois["r2_chave"])
                self.assertEqual(depois["trechos"], 0)
                self.assertFalse(list(self.textos.rglob("siscam-900002.txt")))
                for caminho in (self.textos / "trechos").rglob("*.jsonl"):
                    self.assertTrue(all(json.loads(l)["arquivo"] != chave
                                        for l in caminho.read_text(encoding="utf-8").splitlines()))
                self.assertFalse((self.cache / "arquivos" / SHA_900002).exists())
                rel = self.sincronizar()
                self.assertEqual(rel.falhas, [])
                self.assertEqual(self.consultar("SELECT id FROM arquivos WHERE id = ?", (chave,)), [])
                self.assertEqual(self.consultar("SELECT arquivo FROM arquivo_documento WHERE arquivo = ?", (chave,)), [])
                self.assertEqual(self.consultar("SELECT id FROM trechos WHERE arquivo = ?", (chave,)), [])
                for ident in ids:
                    self.assertEqual(self.consultar("SELECT id FROM trechos_fts WHERE id = ?", (ident,)), [])
                    self.assertEqual(self.consultar("SELECT id FROM trechos_indexados WHERE id = ?", (ident,)), [])
                    self.assertNotIn(ident, self.vetores())
                self.assertFalse(self.objeto_r2(SHA_900002).exists())
                self.assertTrue(self.consultar("SELECT motivo FROM remocoes WHERE chave = ?",
                                               ("siscam:999999" if por_sha else chave,)))
                # Remover um arquivo não remove documento, autoria ou ementa pública.
                self.assertTrue(self.consultar("SELECT id FROM documentos WHERE id = 'doc:127858'"))
                self.assertTrue(self.consultar("SELECT documento FROM ementas_fts WHERE documento = 'doc:127858'"))
                self.assertIn("ementa:doc:290006", self.vetores())
                self.processar_textos()
                self.assertEqual(self.manifesto()[chave], depois)
                self.assertEqual(self.sincronizar().escritas, 0)
                # Restaura a fixture para testar a outra forma de remoção no mesmo ambiente.
                if not por_sha:
                    shutil.copytree(FIXTURES, self.raiz, dirs_exist_ok=True,
                                    ignore=shutil.ignore_patterns("*.py", "__pycache__"))
                    (self.cache / "arquivos" / SHA_900002).write_bytes(G.ORIGINAIS[chave])

    def test_tombstone_sem_citacao_e_resto_de_interrupcao(self):
        self.remover("siscam:900002", SHA_900002)
        self.processar_textos()
        # Até um resto num caminho antigo é apagado na próxima execução.
        resto = self.textos / "textos/pl/2021/1/siscam-900002.txt"
        resto.parent.mkdir(parents=True)
        resto.write_text("Texto sintético.\n", encoding="utf-8")
        (self.raiz / "data/proposicoes/2024.json").write_text("[]\n", encoding="utf-8")
        self.processar_textos()
        self.assertFalse(resto.exists())
        self.assertEqual(self.manifesto()["siscam:900002"]["status"], "removido")

    def test_sha_numa_chave_nova_descartado_sem_cache(self):
        self.remover("siscam:900002", SHA_900002)
        pipeline = textos.Pipeline(textos.Opcoes(raiz=self.raiz, textos=self.textos, cache=self.cache,
                                                liberados=G.LIBERADOS, pessoas=G.PESSOAS,
                                                baixar=lambda _: G.ORIGINAIS["siscam:900002"]))
        (self.cache / "arquivos" / SHA_900002).unlink()
        obtido = pipeline._obter("siscam:999999", "https://example.org/sintetico")
        self.assertEqual((obtido.tipo, obtido.sha), ("removido", SHA_900002))
        self.assertFalse((self.cache / "arquivos" / SHA_900002).exists())

    def test_exportacoes_historicas_novas_somas_e_exclusao_da_versao_antiga(self):
        pasta = self.cache / "exportacoes"
        primeira = self.sincronizar(exportar=pasta).versao
        # O passado pode usar o formato anterior (um único gzip sem número).
        bucket = self.pasta / "r2" / BUCKET_EXPORTACOES_LOCAL
        for destino in (pasta / primeira, bucket / primeira):
            (destino / f"vetores-{primeira}-001.jsonl.gz").rename(destino / f"vetores-{primeira}.jsonl.gz")
            arquivos = {p.name: p.read_bytes() for p in destino.iterdir() if p.name != "SHA256SUMS"}
            (destino / "SHA256SUMS").write_bytes("".join(
                f"{hashlib.sha256(b).hexdigest()}  {n}\n" for n, b in sorted(arquivos.items())).encode("ascii"))
        historico = _ler_dump((pasta / primeira / f"d1-{primeira}.sql").read_bytes())
        ids = {k[0] for k, row in historico["trechos"].items() if row[2] == "siscam:900002"}
        # Segunda exportação tem conteúdo alheio diferente: não substituir o passado pelo estado atual.
        self.reescrever("siscam:900005", "Texto sintético de outra versão histórica, sem dados pessoais.")
        segunda = self.sincronizar(exportar=pasta).versao
        self.assertNotEqual(primeira, segunda)
        self.remover("siscam:900002", SHA_900002)
        self.processar_textos()
        rel = self.sincronizar()  # expurgo obrigatório mesmo sem --exportar
        self.assertEqual(rel.plano["exportacao_regravar"], 2)
        bucket = self.pasta / "r2" / BUCKET_EXPORTACOES_LOCAL
        for antiga in (primeira, segunda):
            self.assertFalse((pasta / antiga).exists())
            self.assertFalse(list((bucket / antiga).glob("*")))
            recibo = json.loads((bucket / "remocoes" / f"{antiga}.json").read_bytes())
            nova = recibo["nova"]
            self.assertNotEqual(nova, antiga)
            sums = (bucket / nova / "SHA256SUMS").read_bytes()
            self.assertEqual(hashlib.sha256(sums).hexdigest(), recibo["sha256sums"])
            for linha in sums.decode("ascii").splitlines():
                sha, nome = linha.split("  ", 1)
                dados = (bucket / nova / nome).read_bytes()
                self.assertEqual(hashlib.sha256(dados).hexdigest(), sha)
                self.assertEqual(dados, (pasta / nova / nome).read_bytes())
            dump = _ler_dump((bucket / nova / f"d1-{nova}.sql").read_bytes())
            self.assertNotIn(("siscam:900002",), dump["arquivos"])
            self.assertFalse(ids & {k[0] for k in dump["trechos"]})
            self.assertFalse(ids & {k[0] for k in dump["trechos_indexados"]})
            if antiga == primeira:
                self.assertEqual(dump["trechos"], {k: row for k, row in historico["trechos"].items()
                                                  if k[0] not in ids})
            vetores = [json.loads(l) for l in gzip.decompress((bucket / nova / f"vetores-{nova}-001.jsonl.gz").read_bytes()).splitlines()]
            self.assertFalse(ids & {v["id"] for v in vetores})
            self.assertIn("ementa:doc:290006", {v["id"] for v in vetores})
            registro = (self.raiz / "docs/backend.md").read_text(encoding="utf-8")
            self.assertIn(f"`{antiga}` regravada como `{nova}`", registro)
        self.assertEqual(self.sincronizar().escritas, 0)

    def test_expurgo_de_partes_remotas_confere_destino_e_apaga_todas_as_antigas(self):
        pasta = self.cache / "exportacoes"
        limite = 6_000
        with mock.patch("coletor.nuvem.sincronizar.LIMITE_PARTE_EXPORTACAO", limite):
            antiga = self.sincronizar(exportar=pasta).versao
            bucket = self.pasta / "r2" / BUCKET_EXPORTACOES_LOCAL
            sqls, vetores = _nomes_exportacao(antiga, _ler_somas_exportacao(
                antiga, (bucket / antiga / "SHA256SUMS").read_bytes()))
            self.assertGreater(len(sqls), 1)
            self.assertGreater(len(vetores), 1)
            historico = _ler_dump(b"".join((bucket / antiga / n).read_bytes() for n in sqls))
            ids = {k[0] for k, row in historico["trechos"].items() if row[2] == "siscam:900002"}
            self.remover("siscam:900002", SHA_900002)
            self.processar_textos()
            shutil.rmtree(pasta)  # reconstituição só do histórico remoto, incluindo as partes SQL
            apagar = R2Local.apagar

            def conferir_destino(r2, nome_bucket, chave):
                if nome_bucket == BUCKET_EXPORTACOES_LOCAL and chave.startswith(antiga + "/"):
                    recibo = json.loads((bucket / "remocoes" / f"{antiga}.json").read_bytes())
                    nova = recibo["nova"]
                    sums = (bucket / nova / "SHA256SUMS").read_bytes()
                    self.assertEqual(hashlib.sha256(sums).hexdigest(), recibo["sha256sums"])
                    for nome, soma in _ler_somas_exportacao(nova, sums).items():
                        self.assertEqual(hashlib.sha256((bucket / nova / nome).read_bytes()).hexdigest(), soma)
                return apagar(r2, nome_bucket, chave)

            with mock.patch.object(R2Local, "apagar", conferir_destino):
                rel = self.sincronizar()
            self.assertEqual(rel.plano["exportacao_regravar"], 1)
            self.assertEqual(rel.feitas["exportacao_apagar"], len(sqls) + len(vetores) + 1)
            self.assertFalse(list((bucket / antiga).glob("*")))
            self.assertFalse((pasta / antiga).exists())
            nova = json.loads((bucket / "remocoes" / f"{antiga}.json").read_bytes())["nova"]
            sums = _ler_somas_exportacao(nova, (bucket / nova / "SHA256SUMS").read_bytes())
            sqls, vetores = _nomes_exportacao(nova, sums)
            self.assertGreater(len(sqls), 1)
            self.assertGreater(len(vetores), 1)
            for nome in sums:
                dados = (bucket / nova / nome).read_bytes()
                self.assertLessEqual(len(dados), limite)
                self.assertEqual(dados, (pasta / nova / nome).read_bytes())
            dump = _ler_dump(b"".join((bucket / nova / n).read_bytes() for n in sqls))
            self.assertNotIn(("siscam:900002",), dump["arquivos"])
            self.assertEqual(dump["trechos"], {k: row for k, row in historico["trechos"].items() if k[0] not in ids})
            lista = [json.loads(l) for n in vetores
                     for l in gzip.decompress((bucket / nova / n).read_bytes()).splitlines()]
            self.assertFalse(ids & {v["id"] for v in lista})
            self.assertEqual([v["id"] for v in lista], sorted(v["id"] for v in lista))
            self.assertEqual(self.sincronizar().escritas, 0)

    def test_falha_de_publicacao_preserva_versao_antiga_e_retomada_apaga(self):
        antiga = self.sincronizar(exportar=self.cache / "exportacoes").versao
        self.remover("siscam:900002", SHA_900002)
        self.processar_textos()
        enviar = R2Local.enviar

        def falhar(r2, bucket, chave, *args, **kw):
            if bucket == BUCKET_EXPORTACOES_LOCAL and chave.endswith("SHA256SUMS"):
                raise ErroNuvem("falha sintética")
            return enviar(r2, bucket, chave, *args, **kw)

        with mock.patch.object(R2Local, "enviar", falhar), self.assertRaises(ErroNuvem):
            self.sincronizar()
        bucket = self.pasta / "r2" / BUCKET_EXPORTACOES_LOCAL
        self.assertTrue((bucket / antiga / "SHA256SUMS").exists())
        self.sincronizar()
        self.assertFalse(list((bucket / antiga).glob("*")))

    def test_remocao_so_no_historico_remoto_tambem_expurga(self):
        pasta = self.cache / "exportacoes"
        antiga = self.sincronizar(exportar=pasta).versao
        # O arquivo já não consta do estado corrente, mas o dump público ainda o tem.
        caminho = self.raiz / "data/textos/manifesto-2024.json"
        manifesto = self.manifesto()
        del manifesto["siscam:900002"]
        salvar_mapa(caminho, manifesto)
        for arq in (self.textos / "trechos").rglob("*.jsonl"):
            linhas = [l for l in arq.read_text(encoding="utf-8").splitlines(keepends=True)
                      if json.loads(l)["arquivo"] != "siscam:900002"]
            arq.write_text("".join(linhas), encoding="utf-8", newline="\n")
        self.sincronizar()
        shutil.rmtree(pasta)
        self.remover("siscam:900002", SHA_900002)
        rel = self.sincronizar()
        self.assertEqual(rel.plano["exportacao_regravar"], 1)
        bucket = self.pasta / "r2" / BUCKET_EXPORTACOES_LOCAL
        self.assertFalse(list((bucket / antiga).glob("*")))
        self.assertTrue((bucket / "remocoes" / f"{antiga}.json").is_file())

    def test_dump_publico_nao_executa_ddl_nem_funcoes(self):
        for sql in (b"DROP TABLE arquivos;", b"SELECT load_extension('sintetico');",
                    b"INSERT INTO arquivos (id) VALUES (random());"):
            with self.subTest(sql=sql), self.assertRaises(ErroNuvem):
                _ler_dump(sql)

    def test_exclusao_interrompida_retoma_pelo_recibo_sem_copia_local(self):
        pasta = self.cache / "exportacoes"
        antiga = self.sincronizar(exportar=pasta).versao
        self.remover("siscam:900002", SHA_900002)
        self.processar_textos()
        apagar = R2Local.apagar
        chamadas = 0

        def interromper(r2, bucket, chave):
            nonlocal chamadas
            if bucket == BUCKET_EXPORTACOES_LOCAL and chave.startswith(antiga + "/"):
                chamadas += 1
                if chamadas == 2:
                    raise ErroNuvem("interrupção sintética")
            return apagar(r2, bucket, chave)

        with mock.patch.object(R2Local, "apagar", interromper), self.assertRaises(ErroNuvem):
            self.sincronizar()
        shutil.rmtree(pasta)  # outra máquina só tem bucket/recibo, não os dumps locais
        self.sincronizar()
        bucket = self.pasta / "r2" / BUCKET_EXPORTACOES_LOCAL
        self.assertFalse(list((bucket / antiga).glob("*")))
        self.assertEqual(self.sincronizar().escritas, 0)

    def test_remocao_posterior_regrava_destino_de_recibo_antigo(self):
        pasta = self.cache / "exportacoes"
        antiga = self.sincronizar(exportar=pasta).versao
        self.remover("siscam:900002", SHA_900002)
        self.processar_textos()
        self.sincronizar()
        bucket = self.pasta / "r2" / BUCKET_EXPORTACOES_LOCAL
        primeira = json.loads((bucket / "remocoes" / f"{antiga}.json").read_bytes())["nova"]
        self.adicionar_segunda_remocao()
        rel = self.sincronizar()
        self.assertEqual(rel.plano["exportacao_regravar"], 1)
        self.assertFalse(list((bucket / primeira).glob("*")))
        segunda = json.loads((bucket / "remocoes" / f"{primeira}.json").read_bytes())["nova"]
        dump = _ler_dump((bucket / segunda / f"d1-{segunda}.sql").read_bytes())
        self.assertNotIn(("siscam:900002",), dump["arquivos"])
        self.assertNotIn(("siscam:900005",), dump["arquivos"])
        self.assertEqual(json.loads((bucket / "remocoes" / f"{antiga}.json").read_bytes())["nova"], primeira)
        # Recibos concluídos não provocam uma listagem a cada execução.
        with mock.patch.object(R2Local, "listar", side_effect=AssertionError("nenhum expurgo pendente")):
            self.assertEqual(self.sincronizar().escritas, 0)

    def test_cadeia_interrompida_retoma_em_outra_maquina(self):
        pasta = self.cache / "exportacoes"
        antiga = self.sincronizar(exportar=pasta).versao
        self.remover("siscam:900002", SHA_900002)
        self.processar_textos()
        self.sincronizar()
        bucket = self.pasta / "r2" / BUCKET_EXPORTACOES_LOCAL
        primeira = json.loads((bucket / "remocoes" / f"{antiga}.json").read_bytes())["nova"]
        self.adicionar_segunda_remocao()
        apagar = R2Local.apagar
        chamadas = 0
        estado = self.consultar("SELECT * FROM estado_indice")

        def interromper(r2, bucket, chave):
            nonlocal chamadas
            if bucket == BUCKET_EXPORTACOES_LOCAL and chave.startswith(primeira + "/"):
                chamadas += 1
                if chamadas == 2:
                    raise ErroNuvem("interrupção sintética da segunda remoção")
            return apagar(r2, bucket, chave)

        with mock.patch.object(R2Local, "apagar", interromper), self.assertRaises(ErroNuvem):
            self.sincronizar()
        segunda = json.loads((bucket / "remocoes" / f"{primeira}.json").read_bytes())["nova"]
        self.assertEqual(self.consultar("SELECT * FROM estado_indice"), estado)
        shutil.rmtree(pasta)  # só o D1 e os recibos remotos sobrevivem
        # Um recibo não basta: a cadeia só permite apagar após conferir o destino.
        destino = bucket / segunda / f"d1-{segunda}.sql"
        dados = destino.read_bytes()
        destino.write_bytes(dados + b"-- alteracao sintetica\n")
        with mock.patch.object(R2Local, "apagar", side_effect=AssertionError("destino não confirmado")), \
                self.assertRaises(ErroNuvem):
            self.sincronizar()
        destino.write_bytes(dados)
        rel = self.sincronizar()
        self.assertEqual(rel.feitas["exportacao_enviar"], 0)
        for origem in (antiga, primeira):
            self.assertFalse(list((bucket / origem).glob("*")))
        somas = (bucket / segunda / "SHA256SUMS").read_bytes()
        for linha in somas.decode("ascii").splitlines():
            sha, nome = linha.split("  ", 1)
            self.assertEqual(hashlib.sha256((bucket / segunda / nome).read_bytes()).hexdigest(), sha)
        dump = _ler_dump((bucket / segunda / f"d1-{segunda}.sql").read_bytes())
        self.assertNotIn(("siscam:900002",), dump["arquivos"])
        self.assertNotIn(("siscam:900005",), dump["arquivos"])
        registro = (self.raiz / "docs/backend.md").read_text(encoding="utf-8")
        self.assertIn(f"`{antiga}` regravada como `{segunda}`", registro)
        self.assertIn(f"`{primeira}` regravada como `{segunda}`", registro)
        self.assertEqual(self.sincronizar().escritas, 0)


if __name__ == "__main__":
    unittest.main()
