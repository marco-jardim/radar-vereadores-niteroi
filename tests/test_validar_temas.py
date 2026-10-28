"""Esquema e formato do cache opcional de temas, sem dados reais nem rede."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from coletor import arquivos, temas, validar


class TestValidarCacheTemas(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)
        self.caminho = self.raiz / "data" / "temas_ia.json"
        self.caminho.parent.mkdir()
        self.doc = "doc:" + "a" * 16
        self.pessoa = "pessoa:ana:2025-2028"
        self.registro = {"rotulos": ["Transporte coletivo"], "total_base": 2,
                         "versao": temas.VERSAO_TEMAS, "modelo": temas.MODELO,
                         "documentos": [self.doc]}
        self.cache = {self.doc: "Transporte coletivo", self.pessoa: self.registro}

    def gravar(self, cache):
        arquivos.salvar_mapa(self.caminho, cache)
        return validar.validar_cache_temas(self.raiz)

    def test_ausente_e_cache_valido(self):
        self.assertEqual(validar.validar_cache_temas(self.raiz), [])
        self.assertEqual(self.gravar(self.cache), [])
        self.registro["rotulos_pendentes"] = copy.deepcopy(self.registro)
        self.assertEqual(self.gravar(self.cache), [])
        self.cache[self.pessoa] = {"falha_amostra": "b" * 64,
                                  "motivos": ["resposta descartada: JSON, rótulo ou classificação inválida"]}
        self.assertEqual(self.gravar(self.cache), [])

    def test_bytes_canonicos_utf8_lf_ordem_e_quebra_final(self):
        for bruto in (json.dumps(self.cache).encode(), b"\xef\xbb\xbf{}\n", b"{}\r\n", b"{}", b"\xff"):
            with self.subTest(bruto=bruto):
                self.caminho.write_bytes(bruto)
                self.assertTrue(validar.validar_cache_temas(self.raiz))

    def test_esquema_fechado_prefixos_hashes_e_classificacao(self):
        for cache in ([], {"outro:abc": {}}, {"doc:errado": "outros"},
                      {"pessoa:ana": self.registro}, {self.pessoa: "corrompido"},
                      {self.doc: {"rotulo": "Transporte coletivo"}}, {self.doc: "Gestão produtiva"}):
            with self.subTest(cache=cache):
                self.caminho.write_text(json.dumps(cache), encoding="utf-8")
                self.assertTrue(validar.validar_cache_temas(self.raiz))
        for campo, valor in (("ementa", "Não pode guardar"), ("total_base", True),
                             ("total_base", -1), ("versao", None), ("modelo", ""),
                             ("rotulos", ["Gestão produtiva"]), ("rotulos", ["Transporte coletivo,"]),
                             ("documentos", ["doc:errado"]), ("documentos", [{"id": 1}]),
                             ("falha_amostra", "errado"), ("motivos", ["texto da IA"]),
                             ("rotulos_pendentes", {})):
            cache = copy.deepcopy(self.cache)
            cache[self.pessoa][campo] = valor
            with self.subTest(campo=campo, valor=valor):
                self.assertTrue(self.gravar(cache))

    def test_validar_tudo_inclui_cache_opcional(self):
        with mock.patch.object(validar, "validar_cache_temas", return_value=["cache de temas inválido"]) as conferir:
            problemas = validar.validar_tudo(self.raiz)
        conferir.assert_called_once_with(self.raiz)
        self.assertIn("cache de temas inválido", problemas)
