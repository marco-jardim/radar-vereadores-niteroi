"""Testes da normalização e da divisão em trechos (coletor/trechos.py).

Uso: python -m unittest tests.test_trechos
"""
from __future__ import annotations

import hashlib
import unicodedata
import unittest

from coletor import trechos
from coletor.trechos import ALVO, MAXIMO, SOBREPOSICAO, dividir, normalizar

FRASE = "A Câmara Municipal de Niterói discutiu o projeto de lei sobre mobilidade urbana. "


def _paragrafo(n_frases: int, rotulo: str = "") -> str:
    return (rotulo + " " + FRASE * n_frases).strip()


class TestNormalizar(unittest.TestCase):
    def test_regras(self) -> None:
        bruto = ("\n\n  \nLinha\u200b um\u00a0\u00a0 \r\nLinha\tdois\r\r\n\n\n\n"
                 "Niteroi\u0301\fpágina\u00ad nova\x01\u2028fim   \n\n\n")
        self.assertEqual(normalizar(bruto), "Linha um\nLinha\tdois\n\nNiteroí\npágina nova\nfim")

    def test_idempotente(self) -> None:
        for bruto in ("a\r\n\r\n\r\nb  ", "  recuo\n\n\n\n", "\ufeffBOM", "x\u3000y", ""):
            with self.subTest(bruto=bruto):
                uma = normalizar(bruto)
                self.assertEqual(normalizar(uma), uma)

    def test_nfc(self) -> None:
        nfd = unicodedata.normalize("NFD", "Ação na Câmara de Niterói")
        self.assertNotEqual(nfd, "Ação na Câmara de Niterói")
        self.assertEqual(normalizar(nfd), "Ação na Câmara de Niterói")


class TestDividir(unittest.TestCase):
    def assertTrechosValidos(self, texto: str, lista: list[dict]) -> None:
        anterior = None
        for i, t in enumerate(lista):
            parte = texto[t["inicio"]:t["fim"]]
            self.assertEqual(t["posicao"], i)
            self.assertEqual(t["sha256"], hashlib.sha256(parte.encode("utf-8")).hexdigest())
            self.assertLessEqual(len(parte), MAXIMO)
            self.assertTrue(parte)
            self.assertEqual(parte, parte.strip())
            self.assertEqual(trechos.texto_do_trecho(texto, t), parte)
            if anterior is not None:
                self.assertGreater(t["inicio"], anterior["inicio"])
                self.assertGreater(t["fim"], anterior["fim"])
                self.assertLessEqual(anterior["fim"] - t["inicio"], SOBREPOSICAO)
            anterior = t
        # todo caractere visível está em algum trecho
        cobertos = bytearray(len(texto))
        for t in lista:
            cobertos[t["inicio"]:t["fim"]] = b"\x01" * (t["fim"] - t["inicio"])
        for i, c in enumerate(texto):
            if not c.isspace():
                self.assertTrue(cobertos[i], f"caractere {i} fora dos trechos")

    def test_texto_vazio(self) -> None:
        self.assertEqual(dividir("", "doc:1", "siscam:2"), [])
        self.assertEqual(dividir("   ", "doc:1", "siscam:2"), [])

    def test_texto_nao_normalizado(self) -> None:
        with self.assertRaises(ValueError):
            dividir("a\r\nb", "doc:1", "siscam:2")
        with self.assertRaises(ValueError):
            dividir("fim com espaço \nx", "doc:1", "siscam:2")

    def test_texto_curto_e_id(self) -> None:
        texto = "Projeto de Lei nº 1/2026\n\nDispõe sobre hortas comunitárias."
        lista = dividir(texto, "doc:290536", "siscam:12345")
        self.assertEqual(len(lista), 1)
        t = lista[0]
        sha = hashlib.sha256(texto.encode("utf-8")).hexdigest()
        self.assertEqual(t, {
            "id": hashlib.sha1(f"doc:290536|siscam:12345|0|{sha}".encode("utf-8")).hexdigest()[:16],
            "documento": "doc:290536",
            "arquivo": "siscam:12345",
            "posicao": 0,
            "inicio": 0,
            "fim": len(texto),
            "sha256": sha,
        })

    def test_agrupa_paragrafos_ate_o_alvo(self) -> None:
        texto = "\n\n".join(_paragrafo(4, f"Parágrafo {i}.") for i in range(30))
        lista = dividir(texto, "doc:1", "siscam:2")
        self.assertGreater(len(lista), 3)
        self.assertTrechosValidos(texto, lista)
        for t in lista[:-1]:
            self.assertGreaterEqual(t["fim"] - t["inicio"], ALVO // 2)
            self.assertLessEqual(t["fim"] - t["inicio"], ALVO + SOBREPOSICAO)

    def test_paragrafo_maior_que_o_maximo(self) -> None:
        texto = _paragrafo(80)  # cerca de 6.600 caracteres, um único parágrafo
        self.assertGreater(len(texto), 3 * MAXIMO)
        lista = dividir(texto, "doc:1", "siscam:2")
        self.assertGreaterEqual(len(lista), 4)
        self.assertTrechosValidos(texto, lista)
        for t in lista:
            # nunca no meio de uma palavra
            self.assertTrue(t["inicio"] == 0 or texto[t["inicio"] - 1].isspace())
            self.assertTrue(t["fim"] == len(texto) or texto[t["fim"]].isspace())
        # cortes em fim de frase
        for t in lista[:-1]:
            self.assertEqual(texto[t["fim"] - 1], ".")

    def test_palavra_gigante_sem_espacos(self) -> None:
        texto = "inicio " + "x" * 5000 + " fim"
        lista = dividir(texto, "doc:1", "siscam:2")
        self.assertTrechosValidos(texto, lista)
        self.assertTrue(texto[lista[-1]["inicio"]:lista[-1]["fim"]].endswith("fim"))

    def test_sobreposicao(self) -> None:
        texto = _paragrafo(60)
        lista = dividir(texto, "doc:1", "siscam:2")
        for a, b in zip(lista, lista[1:]):
            self.assertLess(b["inicio"], a["fim"], "trechos consecutivos devem se sobrepor")
            self.assertLessEqual(a["fim"] - b["inicio"], SOBREPOSICAO)

    def test_layout_com_muitos_espacos(self) -> None:
        linha = "Coluna um" + " " * 60 + "Coluna dois" + " " * 60 + "valor"
        texto = "\n".join(f"{linha} {i}" for i in range(200))
        self.assertEqual(normalizar(texto), texto)
        lista = dividir(texto, "doc:1", "siscam:2")
        self.assertTrechosValidos(texto, lista)

    def test_determinismo_e_ids(self) -> None:
        texto = "\n\n".join(_paragrafo(7, f"Seção {i}.") for i in range(12))
        a = dividir(texto, "doc:1", "siscam:2")
        b = dividir(texto, "doc:1", "siscam:2")
        self.assertEqual(a, b)
        self.assertEqual(len({t["id"] for t in a}), len(a))
        c = dividir(texto, "doc:9", "siscam:2")
        self.assertEqual([t["sha256"] for t in a], [t["sha256"] for t in c])
        self.assertTrue(all(x["id"] != y["id"] for x, y in zip(a, c)))
        self.assertEqual(trechos.VERSAO_TRECHOS, "1")

    def test_acentos_e_nfc(self) -> None:
        bruto = unicodedata.normalize("NFD", "\n\n".join(_paragrafo(10, f"Ação {i}.") for i in range(5)))
        texto = normalizar(bruto)
        lista = dividir(texto, "doc:1", "siscam:2")
        self.assertTrechosValidos(texto, lista)
        for t in lista:
            parte = texto[t["inicio"]:t["fim"]]
            self.assertEqual(unicodedata.normalize("NFC", parte), parte)
        self.assertIn("Ação 0.", texto[lista[0]["inicio"]:lista[0]["fim"]])

    def test_texto_do_trecho_confere_hash(self) -> None:
        texto = "Um texto qualquer."
        t = dividir(texto, "doc:1", "siscam:2")[0]
        with self.assertRaises(ValueError):
            trechos.texto_do_trecho("Outro texto qualquer.", t)


if __name__ == "__main__":
    unittest.main()
