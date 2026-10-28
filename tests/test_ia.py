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
    def test_decodificador_json_preserva_entradas_e_erros_historicos(self):
        esperado = {"itens": [{"id": "1", "rotulo": "Educação municipal"}]}
        objeto = json.dumps(esperado, ensure_ascii=False)
        for texto in (objeto, "```json\n" + objeto + "\n```",
                      "```\n" + objeto + "\n```", "Antes " + objeto + " depois"):
            with self.subTest(texto=texto):
                self.assertEqual(ia.decodificar_json(texto), esperado)
        for texto in ("não é JSON", "```json\n{inválido}\n```", "{} {}", "[]"):
            with self.subTest(texto=texto), self.assertRaises(json.JSONDecodeError):
                ia.decodificar_json(texto)
        with self.assertRaises(AttributeError):
            ia.decodificar_json(None)

    def test_prazo_limita_timeout_e_impede_tentativa_sem_tempo(self):
        transporte = mock.Mock(return_value=resposta())
        ia.chamar({}, "x", "s", base_url="https://exemplo.invalid", prazo=107,
                  relogio=lambda: 100, transporte=transporte)
        self.assertEqual(transporte.call_args.kwargs, {"timeout": 7})
        transporte.reset_mock()
        self.assertEqual(ia.chamar({}, "x", "s", base_url="https://exemplo.invalid", prazo=100,
                                  relogio=lambda: 100, transporte=transporte), {})
        transporte.assert_not_called()

    def test_prazo_limita_esperas_inclusive_retry_after(self):
        for erro in (TimeoutError(), urllib.error.HTTPError(
                "https://exemplo.invalid", 429, "limite", {"Retry-After": "999"}, io.BytesIO(b"limite"))):
            agora = 100

            def esperar(segundos):
                nonlocal agora
                agora += segundos

            transporte = mock.Mock(side_effect=erro)
            espera = mock.Mock(side_effect=esperar)
            self.assertEqual(ia.chamar({}, "x", "s", base_url="https://exemplo.invalid", prazo=102,
                                      relogio=lambda: agora, transporte=transporte, esperar=espera), {})
            espera.assert_called_once_with(2)
            self.assertEqual(transporte.call_count, 1)

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
