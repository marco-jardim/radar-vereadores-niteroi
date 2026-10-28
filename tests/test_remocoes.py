"""Testes da leitura de remoções (coletor/remocoes.py) e da validação do arquivo.

Uso: python -m unittest tests.test_remocoes
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from coletor import remocoes
from coletor.validar import validar_remocoes

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


if __name__ == "__main__":
    unittest.main()
