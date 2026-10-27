"""Testes da máscara LGPD (coletor/mascara.py).

Todos os números e endereços são sintéticos: os CPFs usados são exemplos de
dígitos verificadores válidos, sem relação com pessoas reais.

Uso: python -m unittest tests.test_mascara
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from coletor import mascara
from coletor.mascara import liberados, mascarar, varrer

RAIZ = Path(__file__).resolve().parent.parent
CPF_A = "529.982.247-25"
CPF_B = "111.444.777-35"


def _sem_mudanca(teste: unittest.TestCase, texto: str, lib=frozenset()) -> None:
    saida, contagens = mascarar(texto, lib)
    teste.assertEqual(saida, texto)
    teste.assertEqual(sum(contagens.values()), 0, contagens)
    teste.assertEqual(varrer(texto, lib), [])


class TestCpf(unittest.TestCase):
    def test_dv(self) -> None:
        self.assertTrue(mascara.cpf_valido("52998224725"))
        self.assertTrue(mascara.cpf_valido("11144477735"))
        self.assertFalse(mascara.cpf_valido("52998224726"))
        self.assertFalse(mascara.cpf_valido("11111111111"))
        self.assertFalse(mascara.cpf_valido("1234567890"))

    def test_cpf_valido_mascarado(self) -> None:
        for texto in (f"CPF {CPF_A}.", "CPF: 52998224725", "cpf 529982247-25", f"({CPF_B})", f"CPF{CPF_A}"):
            with self.subTest(texto=texto):
                saida, contagens = mascarar(texto)
                self.assertIn("[CPF omitido]", saida)
                self.assertNotIn("2998224", saida.replace(".", "").replace("-", ""))
                self.assertNotIn("1444777", saida.replace(".", "").replace("-", ""))
                self.assertEqual(contagens["cpf"], 1)

    def test_cpf_com_dv_invalido_fica(self) -> None:
        _sem_mudanca(self, "Número 529.982.247-26 e 52998224726 não são CPF válidos.")

    def test_cpf_formatado_dentro_de_contexto_protegido(self) -> None:
        saida, contagens = mascarar(f"Processo nº {CPF_A}")
        self.assertEqual((saida, contagens["cpf"]), ("Processo nº [CPF omitido]", 1))

    def test_cpf_de_vereador_mascarado(self) -> None:
        lib = {"2133334444", "fulano@exemplo.com", "@camaraniteroi.rj.gov.br"}
        texto = f"Vereador Fulano, CPF {CPF_B}, telefone (21) 3333-4444, fulano@exemplo.com"
        saida, contagens = mascarar(texto, lib)
        self.assertEqual(saida, "Vereador Fulano, CPF [CPF omitido], telefone (21) 3333-4444, fulano@exemplo.com")
        self.assertEqual(contagens, {"cpf": 1, "rg": 0, "telefone": 0, "email": 0})


class TestRg(unittest.TestCase):
    def test_rg_com_rotulo(self) -> None:
        casos = {
            "RG nº 12.345.678-9 SSP/RJ": "RG nº [RG omitido] SSP/RJ",
            "R.G. 98.765.432-1": "R.G. [RG omitido]",
            "portador da carteira de identidade 123456789, residente": (
                "portador da carteira de identidade [RG omitido], residente"),
            "Identidade: 20.123.456-X": "Identidade: [RG omitido]",
        }
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                saida, contagens = mascarar(texto)
                self.assertEqual(saida, esperado)
                self.assertEqual(contagens["rg"], 1)

    def test_rg_sem_rotulo_ou_longe_fica(self) -> None:
        _sem_mudanca(self, "Código 12.345.678-9 do item.")
        _sem_mudanca(self, "RG emitido pelo órgão estadual competente 12.345.678-9")
        _sem_mudanca(self, "Organização 12.345.678-9 e ORG 1234567")


class TestTelefone(unittest.TestCase):
    def test_formatos_mascarados(self) -> None:
        casos = [
            "(21) 99999-9999",
            "(21) 9 8765-4321",
            "+55 21 2620-1234",
            "+55 (21) 2620-1234",
            "55 21 3333-4444",
            "21 2620-1234",
            "(021) 2620-1234",
            "2620-1234",
            "2620 1234",
            "98765-4321",
            "2126201234",
            "(21)2620.1234",
        ]
        for telefone in casos:
            with self.subTest(telefone=telefone):
                saida, contagens = mascarar(f"Contato: {telefone}.")
                self.assertEqual(saida, "Contato: [telefone omitido].")
                self.assertEqual(contagens["telefone"], 1)

    def test_canonico(self) -> None:
        for valor in ("(21) 2620-1234", "+55 21 2620-1234", "2620-1234", "021 2620 1234", "552126201234"):
            with self.subTest(valor=valor):
                self.assertEqual(mascara.telefone_canonico(valor), "2126201234")
        self.assertEqual(mascara.telefone_canonico("(21) 99999-8888"), "21999998888")
        self.assertIsNone(mascara.telefone_canonico("123"))

    def test_ddd_invalido_ou_digitos_corridos_ficam(self) -> None:
        _sem_mudanca(self, "Código 2026201234 e 26201234 e 20 2620 1234x")


class TestEmail(unittest.TestCase):
    def test_email_pessoal_mascarado(self) -> None:
        for email in ("fulano.tal@exemplo.com.br", "a+b@x.io", "c@camaraniteroi.rj.gov.br.exemplo.com",
                      "d@fakeniteroi.rj.gov.br"):
            with self.subTest(email=email):
                saida, contagens = mascarar(f"Escreva para {email}.")
                self.assertEqual(saida, "Escreva para [e-mail omitido].")
                self.assertEqual(contagens["email"], 1)

    def test_email_institucional_liberado(self) -> None:
        for email in ("gabinete@camaraniteroi.rj.gov.br", "Ouvidoria@NITEROI.RJ.GOV.BR",
                      "protocolo@sub.niteroi.rj.gov.br"):
            with self.subTest(email=email):
                _sem_mudanca(self, f"Escreva para {email}.")

    def test_telefone_dentro_de_email_nao_vaza(self) -> None:
        saida, _ = mascarar("contato 2126201234@exemplo.com")
        self.assertEqual(saida, "contato [e-mail omitido]")


class TestFalsosPositivos(unittest.TestCase):
    def test_nao_mascarados(self) -> None:
        casos = [
            "CEP 24020-000",
            "CEP 24.020-000",
            "CNPJ 12.345.678/0001-95",
            "CNPJ 12345678000195",
            "Processo 0001234-56.2024.8.19.0002",
            "Processo SEI 9900.000123/2024-91",
            "SEI-990012/000123/2024",
            "matrícula nº 123.456-7",
            "matrícula funcional 2620-1234",
            "Protocolo 20240012345",
            "R$ 2.620,50",
            "R$ 1.234.567,89 e R$ 3333-4444",
            "em 12/03/2024, 12-03-2024 e 2024-03-12",
            "Lei 3.456/2020",
            "Lei Complementar nº 3456-2020",
            "Processo 1234/2024",
            "Processo nº 2024-1234",
            "Decreto nº 12.345/2016",
            "Ofício nº 3456-2024",
            "Projeto de Lei nº 280/2024",
            "mandato 2021-2024 e biênio 2025/2026",
            "às 14:10 do dia 3",
            "art. 5º, inciso 3",
        ]
        for texto in casos:
            with self.subTest(texto=texto):
                _sem_mudanca(self, texto)

    def test_protecao_e_local(self) -> None:
        saida, contagens = mascarar("Processo 1234/2024, telefone 2620-1234, CEP 24020-000.")
        self.assertEqual(saida, "Processo 1234/2024, telefone [telefone omitido], CEP 24020-000.")
        self.assertEqual(contagens["telefone"], 1)


class TestLiberados(unittest.TestCase):
    def _config(self, pasta: Path, perfis=None, backend=None) -> None:
        (pasta / "config").mkdir()
        if perfis is not None:
            (pasta / "config" / "perfis.json").write_text(json.dumps(perfis), encoding="utf-8")
        if backend is not None:
            (pasta / "config" / "backend.json").write_text(json.dumps(backend), encoding="utf-8")

    def test_le_perfis_e_backend(self) -> None:
        fonte = "https://www.camaraniteroi.rj.gov.br/vereadores/exemplo"
        perfis = {"vereadores": {
            "FULANO DE TAL": {"mandatos": [], "contatos": [
                {"tipo": "telefone", "valor": "(21) 3333-4444", "fonte": fonte},
                {"tipo": "email", "valor": "Fulano.Gabinete@Exemplo.com", "fonte": fonte},
                {"tipo": "telefone", "valor": "(21) 5555-6666", "fonte": "http://inseguro.exemplo"},
            ]},
            "SEM CONTATOS": {"mandatos": []},
        }}
        backend = {"contatos_institucionais": [
            {"tipo": "telefone", "valor": "(21) 2620-1234", "descricao": "Protocolo", "fonte": fonte},
        ]}
        with tempfile.TemporaryDirectory() as nome:
            pasta = Path(nome)
            self._config(pasta, perfis, backend)
            lib = liberados(pasta)
            self.assertEqual(liberados(pasta / "config"), lib)
        self.assertEqual(lib, {
            "2133334444", "fulano.gabinete@exemplo.com", "2126201234",
            "@camaraniteroi.rj.gov.br", "@niteroi.rj.gov.br",
        })
        texto = ("Gabinete: 3333-4444, (21) 3333-4444 ou +55 21 3333-4444; fulano.gabinete@exemplo.com; "
                 "Câmara (21) 2620-1234; pessoal (21) 5555-6666 e (21) 98888-7777.")
        saida, contagens = mascarar(texto, lib)
        self.assertEqual(saida, texto.replace("(21) 5555-6666", "[telefone omitido]")
                         .replace("(21) 98888-7777", "[telefone omitido]"))
        self.assertEqual(contagens["telefone"], 2)

    def test_arquivos_ausentes(self) -> None:
        with tempfile.TemporaryDirectory() as nome:
            pasta = Path(nome)
            self._config(pasta)
            self.assertEqual(liberados(pasta), {"@camaraniteroi.rj.gov.br", "@niteroi.rj.gov.br"})

    def test_config_do_repositorio(self) -> None:
        lib = liberados(RAIZ)
        self.assertIn("@camaraniteroi.rj.gov.br", lib)


class TestIdempotenciaVarrer(unittest.TestCase):
    TEXTO = (f"CPF {CPF_A} e 11144477735; RG 12.345.678-9; tel (21) 99999-9999, 2620-1234 e "
             "+55 21 2222-3333; e-mail a.b@exemplo.com e c@d.org. Lei 3.456/2020, CEP 24020-000.")

    def test_contagens(self) -> None:
        _, contagens = mascarar(self.TEXTO)
        self.assertEqual(contagens, {"cpf": 2, "rg": 1, "telefone": 3, "email": 2})

    def test_idempotente(self) -> None:
        uma, _ = mascarar(self.TEXTO)
        duas, contagens = mascarar(uma)
        self.assertEqual(duas, uma)
        self.assertEqual(sum(contagens.values()), 0)
        self.assertIn("Lei 3.456/2020, CEP 24020-000.", uma)
        self.assertEqual(
            uma,
            "CPF [CPF omitido] e [CPF omitido]; RG [RG omitido]; tel [telefone omitido], "
            "[telefone omitido] e [telefone omitido]; e-mail [e-mail omitido] e [e-mail omitido]. "
            "Lei 3.456/2020, CEP 24020-000.",
        )

    def test_varrer_encontra_o_que_escapou(self) -> None:
        achados = varrer(self.TEXTO)
        self.assertEqual([a["tipo"] for a in achados],
                         ["cpf", "cpf", "rg", "telefone", "telefone", "telefone", "email", "email"])
        for a in achados:
            self.assertEqual(set(a), {"tipo", "inicio", "fim"})
        primeiro = achados[0]
        self.assertEqual(self.TEXTO[primeiro["inicio"]:primeiro["fim"]], CPF_A)
        mascarado, _ = mascarar(self.TEXTO)
        self.assertEqual(varrer(mascarado), [])
        # um dado acrescentado depois da máscara é encontrado
        self.assertEqual([a["tipo"] for a in varrer(mascarado + " Novo: (21) 98888-7777")], ["telefone"])

    def test_texto_vazio(self) -> None:
        self.assertEqual(mascarar(""), ("", {"cpf": 0, "rg": 0, "telefone": 0, "email": 0}))
        self.assertEqual(varrer(""), [])


if __name__ == "__main__":
    unittest.main()
