"""Persistência compacta, incremental em memória e atômica dos vetores locais."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from coletor.nuvem.local import VetoresLocal, como_float32, desempacotar, empacotar


class TestVetoresLocal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="radar-vetores-")
        self.addCleanup(self.tmp.cleanup)
        self.caminho = Path(self.tmp.name) / "vetores.jsonl"
        self.vetores = VetoresLocal(self.caminho)

    def test_muitos_lotes_gravam_uma_vez_por_flush(self):
        valores = [0.1] * 1024
        with mock.patch.object(self.vetores, "_gravar", wraps=self.vetores._gravar) as gravar:
            for i in range(100):
                self.vetores.upsert([{"id": f"{i:04}", "values": valores}])
            self.vetores.apagar(["0000"])
            gravar.assert_not_called()
            self.assertFalse(self.caminho.exists())
            self.assertIsNone(self.vetores.info()["processedUpToMutation"])
            self.vetores.flush()
            gravar.assert_called_once_with()
            self.assertEqual(self.vetores.info()["processedUpToMutation"], "local-101")
            self.vetores.flush()
            self.vetores.esperar("local-101")
            gravar.assert_called_once_with()

            mutacao = self.vetores.upsert([{"id": "novo", "values": valores}])[-1]
            info = self.vetores.esperar(mutacao)
            self.assertEqual(gravar.call_count, 2)
            self.assertEqual(info["processedUpToMutation"], mutacao)
        self.assertEqual(len(VetoresLocal(self.caminho).ids()), 100)
        self.assertNotIn("0000", VetoresLocal(self.caminho).ids())

    def test_valores_e_metadados_sobrevivem_a_reabertura(self):
        valores = [0.1, -0.3, 0.0, 1.0] * 256
        metadata = {"tipo": "moção", "ano": 2026, "documento": "doc:1"}
        self.vetores.upsert([{"id": "a", "values": valores, "metadata": metadata}])
        esperado = [{"id": "a", "values": como_float32(valores), "metadata": metadata}]
        self.assertEqual(self.vetores.obter(["a", "ausente"]), esperado)
        self.vetores.flush()
        obj = json.loads(self.caminho.read_text(encoding="utf-8"))
        self.assertIsInstance(obj["values"], str)
        self.assertEqual(len(obj["values"]), 5464)  # base64 de 1.024 float32
        self.assertEqual(desempacotar(obj["values"]), esperado[0]["values"])
        with mock.patch.object(Path, "read_text", side_effect=AssertionError("leitura deve ser por linha")):
            self.assertEqual(VetoresLocal(self.caminho).obter(["a"]), esperado)

    def test_bytes_deterministicos_independem_da_ordem_e_dos_lotes(self):
        itens = [{"id": i, "metadata": {"tipo": "moção", "ano": 2026}, "values": [0.1, -0.2]}
                 for i in ("c", "a", "b")]
        self.vetores.upsert(itens)
        self.vetores.flush()
        outro = self.caminho.with_name("outro.jsonl")
        indice = VetoresLocal(outro)
        for item in reversed(itens):
            indice.upsert([{**item, "metadata": dict(reversed(list(item["metadata"].items())))}])
        indice.flush()
        self.assertEqual(self.caminho.read_bytes(), outro.read_bytes())
        self.assertNotIn(b"\r", self.caminho.read_bytes())
        self.assertEqual([json.loads(linha)["id"] for linha in self.caminho.read_bytes().splitlines()],
                         ["a", "b", "c"])

    def test_escritor_recebe_uma_linha_por_chamada(self):
        for i in range(20):
            self.vetores.upsert([{"id": f"{i:04}", "values": [0.1] * 1024}])
        # O arquivo real é fechado antes do replace, inclusive no Windows.
        fdopen = os.fdopen
        escritor = None

        def abrir(*args, **kwargs):
            nonlocal escritor
            arquivo = fdopen(*args, **kwargs)
            escritor = mock.MagicMock(wraps=arquivo)
            escritor.__enter__.return_value = escritor
            escritor.__exit__.side_effect = arquivo.__exit__
            return escritor

        with mock.patch("coletor.nuvem.local.os.fdopen", side_effect=abrir):
            self.vetores.flush()
        self.assertEqual(escritor.write.call_count, 20)
        for chamada in escritor.write.call_args_list:
            linha = chamada.args[0]
            self.assertEqual(linha.count("\n"), 1)
            self.assertTrue(linha.endswith("\n"))
            self.assertIn("id", json.loads(linha))
        self.assertEqual(len(self.caminho.read_bytes().splitlines()), 20)

    def test_formatos_anteriores_sao_lidos_e_preservam_metadados(self):
        itens = [{"id": "lista", "values": [0.1, -0.2], "metadata": {"ano": 2021}},
                 {"id": "base64", "values": empacotar([0.3]), "metadata": {"tipo": "pl"}}]
        self.caminho.write_text("\n".join(json.dumps(i) for i in itens) + "\n", encoding="utf-8")
        esperado = [{**itens[0], "values": como_float32([0.1, -0.2])},
                    {**itens[1], "values": como_float32([0.3])}]
        self.assertEqual(self.vetores.obter(["lista", "base64"]), esperado)
        self.vetores.upsert([{"id": "novo", "values": [1.0]}])
        self.vetores.flush()
        self.assertEqual(VetoresLocal(self.caminho).obter(["lista", "base64"]), esperado)
        self.assertTrue(all(isinstance(json.loads(linha)["values"], str)
                            for linha in self.caminho.read_text(encoding="utf-8").splitlines()))

    def test_replace_falho_preserva_destino_limpa_temporario_e_permite_repetir(self):
        self.vetores.upsert([{"id": "antigo", "values": [1.0]}])
        self.vetores.flush()
        anterior = self.caminho.read_bytes()
        self.vetores.upsert([{"id": "novo", "values": [2.0]}])

        def falhar(temporario, destino):
            self.assertEqual(destino, self.caminho)
            self.assertEqual(self.caminho.read_bytes(), anterior)
            # O temporário já contém o conjunto novo completo, nunca o destino parcial.
            self.assertEqual(len(Path(temporario).read_bytes().splitlines()), 2)
            raise OSError("falha simulada no replace")

        with mock.patch("coletor.nuvem.local.os.replace", side_effect=falhar):
            with self.assertRaisesRegex(OSError, "falha simulada"):
                self.vetores.flush()
        self.assertEqual(self.caminho.read_bytes(), anterior)
        self.assertEqual(list(self.caminho.parent.glob(".*.tmp")), [])
        self.assertEqual(self.vetores.info()["processedUpToMutation"], "local-1")
        self.vetores.flush()
        self.assertEqual(VetoresLocal(self.caminho).ids(), ["antigo", "novo"])


if __name__ == "__main__":
    unittest.main()
