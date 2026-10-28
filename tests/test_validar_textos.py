"""Validação offline do contrato de inteiro teor, sem modificar as fixtures reais."""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from coletor import arquivos, textos, trechos
from coletor import validar as V

FIXTURES = Path(__file__).parent / "fixtures" / "contratos"
# Mesma configuração sintética de gerar_fixtures.py; não está nos manifestos.
LIBERADOS = frozenset({"@camaraniteroi.rj.gov.br", "@niteroi.rj.gov.br", "2126201234"})


class TestValidarTextos(unittest.TestCase):
    def test_estrita_no_validador_de_texto_e_orfao(self):
        texto = "ID: 12.345,678-9 IFP/RJ\n"
        alvo = self.caminho()
        alvo.write_bytes(alvo.read_bytes() + texto.encode("utf-8"))
        alvo.with_name("siscam-999999.txt").write_bytes(texto.encode("utf-8"))
        with mock.patch.object(V.mascara, "varrer", return_value=[]):
            problemas = self.assertProblema("ocorrência forte")
        for chave in ("siscam:900001", "siscam:999999"):
            self.assertIn(f"{chave}: ocorrência forte de mascara.varrer (rg)", problemas)
        self.assertNotIn("12.345", " ".join(problemas))

    def setUp(self):
        temporario = tempfile.TemporaryDirectory()
        self.addCleanup(temporario.cleanup)
        self.raiz = Path(temporario.name) / "raiz"
        shutil.copytree(FIXTURES, self.raiz)
        self.pasta = self.raiz / "dados-textos"
        self.manifesto = self.raiz / "data" / "textos" / "manifesto-2024.json"
        self.mapa = json.loads(self.manifesto.read_bytes())
        liberados = mock.patch.object(V.mascara, "liberados", return_value=LIBERADOS)
        self.liberados = liberados.start()
        self.addCleanup(liberados.stop)

    def gravar(self):
        arquivos.salvar_mapa(self.manifesto, self.mapa)

    def caminho(self, chave="siscam:900001") -> Path:
        e = self.mapa[chave]
        return self.pasta / textos.caminho_texto(e["tipo"], 2024, e["documento"], chave)

    def validar(self, com_textos=True) -> list[str]:
        return V.validar_textos(self.raiz, self.pasta if com_textos else None)

    def assertProblema(self, trecho: str, com_textos=True) -> list[str]:
        problemas = self.validar(com_textos)
        self.assertTrue(any(trecho in p for p in problemas), (trecho, problemas))
        return problemas

    def test_fixtures_passam_com_pendentes_removidos_duplicatas_e_esvaziado(self):
        self.assertEqual(self.validar(False), [])
        self.assertEqual(self.validar(), [])
        self.liberados.assert_called_once_with(self.raiz)

    def test_baixa_confianca_booleano_aceito_e_tipo_invalido_rejeitado(self):
        caminho = self.pasta / "trechos" / "pl" / "2024.jsonl"
        lista = [json.loads(linha) for linha in caminho.read_bytes().splitlines()]
        self.assertTrue(any(t["baixa_confianca"] for t in lista))
        self.assertEqual(self.validar(), [])
        lista[0]["baixa_confianca"] = "true"
        caminho.write_bytes("".join(textos.linha_trecho(t) + "\n" for t in lista).encode("utf-8"))
        self.assertProblema("campos, offsets")

    def test_baixa_confianca_obrigatoria_na_versao_atual(self):
        caminho = self.pasta / "trechos" / "pl" / "2024.jsonl"
        lista = [json.loads(linha) for linha in caminho.read_bytes().splitlines()]
        t = lista[0]
        e = self.mapa[t["arquivo"]]
        e["versao_trechos"] = trechos.VERSAO_TRECHOS
        del t["baixa_confianca"]
        caminho.write_bytes("".join(textos.linha_trecho(item) + "\n" for item in lista).encode("utf-8"))
        self.gravar()
        self.assertFalse(V._validar_trecho_texto(t, self.caminho(t["arquivo"]).read_text(encoding="utf-8")[:-1],
                                               e["documento"], t["arquivo"], t["posicao"], trechos.VERSAO_TRECHOS))
        self.assertProblema("campos, offsets")
        # Formatos antigos continuam legíveis, mas um sinalizador presente precisa
        # ser booleano independentemente da versão.
        e["versao_trechos"] = "2"
        self.gravar()
        self.assertEqual(self.validar(), [])

    def test_pasta_opcional_ausente(self):
        shutil.rmtree(self.raiz / "data" / "textos")
        self.assertEqual(self.validar(False), [])

    def test_worktree_inexistente(self):
        self.assertTrue(V.validar_textos(self.raiz, self.raiz / "ausente"))

    def test_hash_blob_e_chars_adulterados(self):
        original = dict(self.mapa["siscam:900001"])
        for campo, valor in (("sha256_texto", "0" * 64), ("blob_texto", "0" * 40), ("chars", 1)):
            with self.subTest(campo=campo):
                self.mapa["siscam:900001"] = {**original, campo: valor}
                self.gravar()
                self.assertProblema(f"{campo} não confere")

    def test_texto_adulterado(self):
        with self.caminho().open("ab") as destino:
            destino.write(b"Adulterado\n")
        self.assertProblema("sha256_texto não confere")

    def test_txt_ausente_so_e_erro_com_worktree(self):
        self.caminho().unlink()
        self.assertEqual(self.validar(False), [])
        self.assertProblema("texto ausente")

    def test_txt_orfao(self):
        caminho = self.caminho().with_name("siscam-999999.txt")
        caminho.write_bytes(b"Texto sintetico\n")
        self.assertProblema(".txt órfão")

    def test_jsonl_orfao_mesmo_vazio(self):
        caminho = self.pasta / "trechos" / "pl" / "2099.jsonl"
        caminho.write_bytes(b"")
        self.assertProblema(".jsonl órfão")

    def test_jsonl_ausente(self):
        (self.pasta / textos.caminho_trechos("pl", 2024)).unlink()
        self.assertProblema("arquivo de trechos ausente")

    def test_ordem_fisica_do_manifesto_e_a_de_salvar_mapa(self):
        linhas = self.manifesto.read_bytes().split(b"\n")
        entradas = [linha.removesuffix(b",") for linha in linhas[1:-2]]
        self.manifesto.write_bytes(b"{\n" + b",\n".join(reversed(entradas)) + b"\n}\n")
        self.assertProblema("ordem", False)

    def test_ordem_numerica_da_canonica_nao_se_confunde_com_serializacao(self):
        for anterior, nova in (("siscam:900003", "siscam:2"), ("siscam:900008", "siscam:10")):
            e = self.mapa.pop(anterior)
            e["url_origem"] = textos.URL_DOWNLOAD.format(id=nova.split(":")[1])
            self.mapa[nova] = e
        self.mapa["siscam:10"]["duplicata_de"] = "siscam:2"
        self.gravar()
        self.assertEqual(self.validar(False), [])
        self.mapa["siscam:2"]["status"] = "duplicata"
        self.mapa["siscam:2"]["duplicata_de"] = "siscam:10"
        self.gravar()
        self.assertProblema("menor chave", False)

    def test_status_invalido(self):
        self.mapa["siscam:900001"]["status"] = "inventado"
        self.gravar()
        self.assertProblema("'status'", False)

    def test_removido_pela_chave_nao_marcado(self):
        self.mapa["siscam:900004"]["status"] = "pendente_download"
        self.gravar()
        self.assertProblema("sem status removido", False)

    def test_removido_pelo_sha_nao_marcado(self):
        self.mapa["siscam:900007"]["status"] = "erro_formato"
        self.gravar()
        self.assertProblema("sem status removido", False)

    def test_pii_forte_e_detectada_mesmo_com_hashes_e_trechos_atualizados(self):
        chave = "siscam:900001"
        e = self.mapa[chave]
        texto = self.caminho().read_bytes().decode("utf-8")[:-1] + "\n\nE-mail: titular.sintetico@exemplo.com"
        dados = (texto + "\n").encode("utf-8")
        self.caminho().write_bytes(dados)
        e.update(sha256_texto=textos.sha256(dados), blob_texto=textos.blob_git(dados), chars=len(texto))
        caminho = self.pasta / textos.caminho_trechos(e["tipo"], 2024)
        lista = [json.loads(linha) for linha in caminho.read_text(encoding="utf-8").splitlines()]
        novos = trechos.dividir(texto, e["documento"], chave)
        lista = [t for t in lista if t["arquivo"] != chave] + novos
        lista.sort(key=lambda t: (t["documento"], t["arquivo"], t["posicao"]))
        caminho.write_bytes("".join(textos.linha_trecho(t) + "\n" for t in lista).encode("utf-8"))
        e.update(trechos=len(novos), trechos_vetorizaveis=sum(t["vetorizavel"] for t in novos))
        self.gravar()
        problemas = self.assertProblema("ocorrência forte")
        self.assertTrue(any(chave in p and "email" in p for p in problemas))
        self.assertNotIn("titular.sintetico", "\n".join(problemas))
        self.assertNotIn("@exemplo.com", "\n".join(problemas))

    def test_pii_forte_em_txt_orfao_tambem_e_varrida(self):
        self.caminho().with_name("siscam-999999.txt").write_bytes(b"E-mail: pessoa@exemplo.com\n")
        problemas = self.assertProblema("ocorrência forte")
        self.assertNotIn("pessoa@exemplo.com", "\n".join(problemas))

    def test_formato_de_bytes_do_manifesto(self):
        original = self.manifesto.read_bytes()
        for nome, dados in (("indentado", json.dumps(self.mapa, ensure_ascii=False, indent=1).encode("utf-8")),
                            ("crlf", original.replace(b"\n", b"\r\n")), ("sem quebra", original[:-1]),
                            ("bom", b"\xef\xbb\xbf" + original)):
            with self.subTest(nome=nome):
                self.manifesto.write_bytes(dados)
                self.assertTrue(self.validar(False))

    def test_formato_de_bytes_do_txt(self):
        original = self.caminho().read_bytes()
        for nome, dados in (("crlf", original.replace(b"\n", b"\r\n")), ("sem quebra", original[:-1]),
                            ("bom", b"\xef\xbb\xbf" + original), ("utf8", b"\xff\n")):
            with self.subTest(nome=nome):
                self.caminho().write_bytes(dados)
                self.assertTrue(self.validar())

    def test_schema_campos_chaves_hashes_e_tipos(self):
        original = dict(self.mapa["siscam:900001"])
        for campo, valor in (("sha256_original", "A" * 64), ("sha256_texto", "0" * 63),
                            ("blob_texto", "0" * 64), ("chars", True), ("paginas", -1),
                            ("tipo", "substitutivo"), ("documentos", []), ("documento", "doc:0"),
                            ("trechos", []), ("status", []), ("limpeza", []), ("mascarados", [])):
            with self.subTest(campo=campo):
                self.mapa["siscam:900001"] = {**original, campo: valor}
                self.gravar()
                self.assertProblema(f"'{campo}'", False)
        self.mapa["siscam:900001"] = {**original, "extra": 1}
        self.gravar()
        self.assertProblema("campos do manifesto", False)
        self.mapa["siscam:900001"] = dict(original)
        del self.mapa["siscam:900001"]["sha256_bruto"]
        self.gravar()
        self.assertProblema("campos do manifesto", False)

    def test_chave_fora_do_padrao(self):
        original = dict(self.mapa)
        for chave in ("siscam:01", "siscam:0", "sessao:0000000A-0000-4000-8000-0000000000B2"):
            with self.subTest(chave=chave):
                self.mapa = {**original, chave: original["siscam:900001"]}
                self.gravar()
                self.assertProblema("chave de arquivo fora do padrão", False)

    def test_ano_e_do_registro_nao_da_data(self):
        # A fixture já tem um requerimento com data em 2025 e ano de registro 2024.
        self.assertEqual(self.validar(False), [])
        self.manifesto.rename(self.manifesto.with_name("manifesto-2025.json"))
        self.assertProblema("ano", False)

    def test_documento_principal_inexistente_e_substitutivo_no_lugar_do_pl(self):
        self.mapa["siscam:900001"]["documento"] = "doc:999999"
        self.gravar()
        self.assertProblema("documento principal não existe", False)
        self.mapa["siscam:900001"]["documento"] = "doc:266596"
        self.gravar()
        self.assertProblema("documento principal", False)

    def test_duplicata_de_inexistente(self):
        self.mapa["siscam:900008"]["duplicata_de"] = "siscam:999999"
        self.gravar()
        self.assertProblema("canônica existente", False)

    def test_chave_repetida_entre_anos(self):
        arquivos.salvar_mapa(self.manifesto.with_name("manifesto-2025.json"), self.mapa)
        self.assertProblema("chave repetida entre manifestos", False)

    def test_trechos_campos_offsets_utf16_id_hash_e_contagem(self):
        caminho = self.pasta / textos.caminho_trechos("ata", 2024)
        original = json.loads(caminho.read_bytes())
        for campo, valor in (("inicio", -1), ("fim", 999999), ("inicio_utf16", 1), ("fim_utf16", 0),
                            ("id", "0" * 16), ("sha256", "0" * 64), ("posicao", 2),
                            ("vetorizavel", 1), ("documento", "sessao:999999")):
            with self.subTest(campo=campo):
                t = {**original, campo: valor}
                caminho.write_bytes((textos.linha_trecho(t) + "\n").encode("utf-8"))
                self.assertProblema("trechos não conferem")
        caminho.write_bytes(b"")
        self.assertProblema("contagem de trechos")

    def test_trecho_orfao(self):
        caminho = self.pasta / textos.caminho_trechos("ata", 2024)
        t = json.loads(caminho.read_bytes())
        t["arquivo"] = "siscam:999999"
        caminho.write_bytes((textos.linha_trecho(t) + "\n").encode("utf-8"))
        self.assertProblema("trecho órfão")

    def test_ordem_e_formato_jsonl(self):
        caminho = self.pasta / textos.caminho_trechos("pl", 2024)
        original = caminho.read_bytes()
        for dados in (b"\n".join(reversed(original.splitlines())) + b"\n",
                      original.replace(b"\n", b"\r\n"), original[:-1], b"{\n"):
            with self.subTest(dados=dados[:20]):
                caminho.write_bytes(dados)
                self.assertTrue(self.validar())

    def test_cli_textos_e_anotacao_ci(self):
        erro = io.StringIO()
        with mock.patch.object(V, "validar_tudo", return_value=["siscam:1: chars não confere"]) as validar, \
                mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}), contextlib.redirect_stderr(erro):
            self.assertEqual(V.main(["--textos", str(self.pasta)]), 1)
        validar.assert_called_once_with(pasta_textos=self.pasta)
        self.assertIn("::error::siscam:1", erro.getvalue())

    def test_validar_tudo_inclui_manifestos_e_repassa_worktree(self):
        # A raiz congelada é propositalmente mínima, não uma base completa dos
        # coletores; os demais problemas não interferem na integração desta área.
        for pasta in (None, self.pasta):
            with self.subTest(pasta=pasta), \
                    mock.patch.object(V, "validar_textos", return_value=["manifesto sintético inválido"]) as validar, \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertIn("manifesto sintético inválido", V.validar_tudo(self.raiz, pasta))
            validar.assert_called_once_with(self.raiz, pasta)

    def test_cli_sem_textos_retorna_zero(self):
        with mock.patch.object(V, "validar_tudo", return_value=[]) as validar, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(V.main([]), 0)
        validar.assert_called_once_with(pasta_textos=None)


if __name__ == "__main__":
    unittest.main()
