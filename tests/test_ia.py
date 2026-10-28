"""Transporte de IA testado sem rede, com respostas e esperas injetadas."""
from __future__ import annotations

import io
import json
import unittest
import urllib.error
from unittest import mock

from coletor import ia


def resposta(texto: str = '{"ok":true}'):
    return io.BytesIO(json.dumps({"choices": [{"message": {"content": texto}}]}).encode())


class TestClienteIa(unittest.TestCase):
    def test_post_corpo_sessao_e_timeout(self):
        transporte = mock.Mock(return_value=resposta())
        corpo = {"model": "modelo", "messages": [{"role": "user", "content": "ação"}]}
        dados = ia.chamar(corpo, "falsa", "sessao-estavel", base_url="https://exemplo.invalid/v1/",
                          transporte=transporte)
        self.assertEqual(dados, {"ok": True})
        req = transporte.call_args.args[0]
        self.assertEqual(req.full_url, "https://exemplo.invalid/v1/chat/completions")
        self.assertEqual(req.method, "POST")
        self.assertEqual(req.data, json.dumps(corpo).encode())
        headers = {k.lower(): v for k, v in req.header_items()}
        self.assertEqual(headers["authorization"], "Bearer falsa")
        self.assertEqual(headers["x-opencode-session"], "sessao-estavel")
        self.assertEqual(headers["user-agent"], ia.USER_AGENT)
        self.assertEqual(headers["content-type"], "application/json")
        self.assertEqual(transporte.call_args.kwargs, {"timeout": 180})

    def test_tentativas_e_espera_progressiva(self):
        transporte = mock.Mock(side_effect=[TimeoutError(), resposta("não é JSON"), resposta()])
        esperar = mock.Mock()
        self.assertEqual(ia.chamar({}, "x", "s", base_url="https://exemplo.invalid",
                                  transporte=transporte, esperar=esperar), {"ok": True})
        self.assertEqual(esperar.call_args_list, [mock.call(5), mock.call(10)])
        self.assertIs(transporte.call_args_list[0].args[0], transporte.call_args_list[-1].args[0])

    def test_limite_de_uso_retry_after_e_fallback(self):
        for headers, segundos in (({"Retry-After": "7"}, 7), ({}, 30)):
            transporte = mock.Mock(side_effect=[urllib.error.HTTPError(
                "https://exemplo.invalid", 429, "limite", headers, io.BytesIO(b"limite")), resposta()])
            esperar = mock.Mock()
            ia.chamar({}, "x", "s", base_url="https://exemplo.invalid",
                      transporte=transporte, esperar=esperar)
            esperar.assert_called_once_with(segundos)

    def test_chave_recusada_e_tentativas_esgotadas(self):
        for codigo in (401, 403):
            erro = urllib.error.HTTPError("https://exemplo.invalid", codigo, "negado", {}, io.BytesIO(b"negado"))
            with self.assertRaisesRegex(PermissionError, str(codigo)):
                ia.chamar({}, "x", "s", base_url="https://exemplo.invalid",
                          transporte=mock.Mock(side_effect=erro))
        transporte, esperar = mock.Mock(side_effect=urllib.error.URLError("offline")), mock.Mock()
        self.assertEqual(ia.chamar({}, "x", "s", base_url="https://exemplo.invalid",
                                  transporte=transporte, esperar=esperar), {})
        self.assertEqual(transporte.call_count, 4)
        self.assertEqual(esperar.call_args_list, [mock.call(n) for n in (5, 10, 15, 20)])
