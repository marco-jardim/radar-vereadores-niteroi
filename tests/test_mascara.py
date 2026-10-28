"""Testes da máscara LGPD (coletor/mascara.py).

Os números são sintéticos: os CPFs usados são exemplos de dígitos verificadores
válidos, sem relação com pessoas reais. As regressões de e-mails incluem as formas
de OCR fornecidas na auditoria do corpus, além dos endereços sintéticos.

Uso: python -m unittest tests.test_mascara
"""
from __future__ import annotations

import json
import random
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from coletor import mascara
from coletor.mascara import liberados, mascarar, varrer

RAIZ = Path(__file__).resolve().parent.parent
CPF_A = "529.982.247-25"
CPF_B = "111.444.777-35"


def _sem_mudanca(teste: unittest.TestCase, texto: str, lib=frozenset()) -> None:
    saida, contagens = mascarar(texto, lib)
    teste.assertEqual(saida, texto)
    teste.assertEqual(sum(contagens.values()), 0, contagens)


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
        self.assertEqual(contagens, {"cpf": 1, "rg": 0, "telefone": 0, "email": 0, "documento": 0, "numero": 0})


class TestCpfSeparadoresMistos(unittest.TestCase):
    """CPF com separadores trocados pelo OCR (dígitos sintéticos)."""

    def _mascarado_limpo(self, texto: str, esperado: str) -> None:
        saida, contagens = mascarar(texto)
        self.assertEqual(saida, esperado)
        self.assertEqual(contagens["cpf"], 1)
        self.assertEqual(mascarar(saida), (saida, {tipo: 0 for tipo in mascara.TIPOS}))  # idempotente
        self.assertFalse([a for a in varrer(saida) if a["forte"]])

    def test_caso_do_lote_real(self) -> None:
        self.assertTrue(mascara.cpf_valido("12345678909"))
        self._mascarado_limpo("DENISE FULANA, RG. [RG omitido], CPF. 123.456 789-09, Casada",
                              "DENISE FULANA, RG. [RG omitido], CPF. [CPF omitido], Casada")

    def test_dv_valido_com_qualquer_separador(self) -> None:
        for cpf in ("529 982 247 25", "529/982/247/25", "529-982-247-25", "529.982.247 - 25",
                    "529.982.247- 25", "529982247 25", "529.982247-25", "529 982.247/25", "529.982 247-25"):
            with self.subTest(cpf=cpf):
                self._mascarado_limpo(f"Número {cpf}, fim.", "Número [CPF omitido], fim.")

    def test_dv_invalido_sem_rotulo_fica(self) -> None:
        for texto in ("Código 529 982 247 26", "Número 529/982/247/26.", "Item 529.982 247-26"):
            with self.subTest(texto=texto):
                _sem_mudanca(self, texto)

    def test_dv_invalido_com_rotulo(self) -> None:
        self.assertFalse(mascara.cpf_valido("12345678900"))
        casos = {
            "CPF: 123.456.789-00": "CPF: [CPF omitido]",
            "C.P.F. 123 456 789 00": "C.P.F. [CPF omitido]",
            "CPF/MF nº 123.456 789-00": "CPF/MF nº [CPF omitido]",
            "cpf 12345678900, solteiro": "cpf [CPF omitido], solteiro",
            "CPF nº 123/456/789-00": "CPF nº [CPF omitido]",
            "inscrito no CPF sob 123.456.789-00": "inscrito no CPF sob [CPF omitido]",
        }
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                self._mascarado_limpo(texto, esperado)

    def test_rotulo_longe_ou_marca_nao_valem(self) -> None:
        _sem_mudanca(self, "CPF do declarante, conforme o registro 123.456.789-00")
        _sem_mudanca(self, "[CPF omitido] e 123.456.789-00")
        _sem_mudanca(self, "CPFs 123.456.789-00")

    def test_espaco_dentro_de_sequencia_maior_nao_e_cpf(self) -> None:
        for texto in ("Tabela 111 529 982 247 25", "Colunas 529 982 247 25 333", "valores 7 529 982 247 25 8"):
            with self.subTest(texto=texto):
                _sem_mudanca(self, texto)
        # sem espaço como separador, a vizinhança não importa
        self._mascarado_limpo("item 1 529.982.247-25", "item 1 [CPF omitido]")
        self._mascarado_limpo("Número 529 982 247 25.", "Número [CPF omitido].")
        # o rótulo vence a proteção da sequência
        saida, contagens = mascarar("CPF: 529 982 247 25 7")
        self.assertEqual((saida, contagens["cpf"]), ("CPF: [CPF omitido] 7", 1))
        saida, contagens = mascarar("CPF 1 529 982 247 25")
        self.assertEqual((saida, contagens["cpf"]), ("CPF 1 [CPF omitido]", 1))

    def test_rotulo_de_rg_nao_corta_cpf(self) -> None:
        self._mascarado_limpo("RG nº, CPF 123.456 789-09", "RG nº, CPF [CPF omitido]")


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
        # Desde a máscara 10, número com forma de RG até 40 caracteres depois do rótulo é mascarado
        # (decisão conservadora após o vazamento de RGs com emissor e redação variados).
        self.assertEqual(mascarar("RG emitido pelo órgão estadual competente 12.345.678-9")[0],
                         "RG emitido pelo órgão estadual competente [RG omitido]")
        _sem_mudanca(self, "Organização 12.345.678-9 e ORG 1234567")

    def test_identidade_sem_marca_nao_e_rotulo(self) -> None:
        _sem_mudanca(self, "identidade de gênero, conforme Lei 13.709/2018")
        _sem_mudanca(self, "Identidade, 22.11.2020")
        _sem_mudanca(self, "a identidade 2024 do evento 12345")
        saida, _ = mascarar("cédula de identidade 12.345.678-9")
        self.assertEqual(saida, "cédula de identidade [RG omitido]")
        saida, _ = mascarar("Identidade nº 123456789")
        self.assertEqual(saida, "Identidade nº [RG omitido]")

    def test_rg_respeita_protecoes(self) -> None:
        _sem_mudanca(self, "RG: Lei nº 12.345/2020")
        _sem_mudanca(self, "RG 12.03.2024")


class TestTelefoneColado(unittest.TestCase):
    def test_telefones_colados_a_pontuacao(self) -> None:
        casos = {
            "(21) 2620-1234/2620-5678": "[telefone omitido]/[telefone omitido]",
            "2620-1234,2620-5678": "[telefone omitido],[telefone omitido]",
            "Tel.2620-1234": "Tel.[telefone omitido]",
            "Cel.98765-4321": "Cel.[telefone omitido]",
        }
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual(mascarar(texto)[0], esperado)
                self.assertTrue(varrer(texto))

    def test_sei_so_no_formato_do_sei(self) -> None:
        saida, contagens = mascarar("Acesso ao SEI, ligue 2620-1234")
        self.assertEqual((saida, contagens["telefone"]), ("Acesso ao SEI, ligue [telefone omitido]", 1))
        saida, contagens = mascarar("SEI: CPF 12345678909")
        self.assertEqual((saida, contagens["cpf"]), ("SEI: CPF [CPF omitido]", 1))
        _sem_mudanca(self, "SEI nº 9900.000123/2024-91 e SEI 12345678")

    def test_sem_retrocesso_em_linhas_com_muitos_espacos(self) -> None:
        linha = ("Processo" + " " * 80 + "Lei" + " " * 60 + "matrícula" + " " * 70 + "Valor"
                 + " " * 50 + "R$ 1.234,56" + " " * 40 + "nº" + " " * 30 + ":\n")
        texto = linha * (5_000_000 // len(linha))
        inicio = time.perf_counter()
        saida, contagens = mascarar(texto)
        self.assertLess(time.perf_counter() - inicio, 3.0)
        self.assertEqual(sum(contagens.values()), 0)
        self.assertEqual(saida, texto)


class TestTelefone(unittest.TestCase):
    def test_celular_com_ponto_depois_do_nove(self) -> None:
        for telefone in ("21-9.8115-0243", "(21) 9.8115-0243", "21 9 8115 0243",
                         "9.8115-0243", "9 8115-0243", "(21) 9.8115.0243"):
            with self.subTest(telefone=telefone):
                texto = "Telefones: " + telefone + " (celular)"
                saida, contagens = mascarar(texto)
                self.assertEqual(saida, "Telefones: [telefone omitido] (celular)")
                self.assertEqual(contagens["telefone"], 1)
                self.assertEqual([(a["tipo"], a["forte"]) for a in varrer(texto)], [("telefone", True)])
                self.assertEqual(varrer(saida), [])
                self.assertEqual(mascarar(saida)[0], saida)
                _sem_mudanca(self, texto, {"21981150243"})
                self.assertEqual(varrer(texto, {"21981150243"}), [])
        self.assertEqual([(a["tipo"], a["forte"]) for a in varrer("21-9.8115-0243")],
                         [("telefone", True)])
        _sem_mudanca(self, "Código 9.811 e valor 9.81150243")
        self.assertEqual(varrer("Código 9.811 e valor 9.81150243"), [])
        for data in ("21-09-2024", "21.09.2024", "21/09/2024"):
            _sem_mudanca(self, "Data " + data)
            self.assertEqual(varrer("Data " + data), [])

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
    def test_separadores_ocr_em_qualquer_pagina(self) -> None:
        for separador in ("(D", "(OD", "(Q", "(0D", "(@", "©", "@ ", "O"):
            for dominio in ("gmail.com", "yahoo.com.br"):
                with self.subTest(separador=separador, dominio=dominio):
                    email = "pessoa.teste" + separador + dominio
                    texto = f"Escreva para {email}."
                    for paginas in (None, {1}, {2}):
                        saida, contagens = mascarar(texto, ocr_paginas=paginas)
                        self.assertEqual(saida, "Escreva para [e-mail omitido].")
                        self.assertEqual(contagens["email"], 1)
                        self.assertEqual(mascarar(saida, ocr_paginas=paginas)[0], saida)
                        self.assertEqual(varrer(saida, ocr_paginas=paginas), [])
                    achados = varrer(texto)
                    self.assertEqual([(a["tipo"], a["forte"]) for a in achados], [("email", True)])
                    self.assertEqual(texto[achados[0]["inicio"]:achados[0]["fim"]], email)

    def test_ocr_dominio_proprio_e_provedores(self) -> None:
        for email in ("contato(Dcartorio.exemplo.com", "contato(Qrefugio.exemplo.org",
                      "pessoaOhotmail.com", "pessoaOoutlook.com", "pessoaOlive.com",
                      "pessoaOuol.com.br", "pessoaObol.com.br", "pessoaOterra.com.br",
                      "pessoaOicloud.com", "pessoaOglobo.com", "pessoaOig.com.br"):
            with self.subTest(email=email):
                self.assertEqual(mascarar(email)[0], "[e-mail omitido]")
                self.assertEqual([(a["tipo"], a["forte"]) for a in varrer(email)], [("email", True)])
        self.assertEqual(mascarar("vereador pessoaOgmail.com")[0], "vereador [e-mail omitido]")

    def test_ocr_liberado_pelo_endereco_reconstruido(self) -> None:
        for email, lib in (("servidor(Dtjrj.jus.br", set()),
                           ("12345678(ODorgao.gov.br", set()),
                           ("Pessoa.Teste(Qexemplo.org", {"pessoa.teste@exemplo.org"}),
                           ("12345678(@gmail.com", {"12345678@gmail.com"}),
                           ("pessoaOgmail.com", {"pessoa@gmail.com"}),
                           ("pessoa@ gmail.com", {"pessoa@gmail.com"})):
            with self.subTest(email=email):
                _sem_mudanca(self, email, lib)
                self.assertEqual(mascarar(email, lib, ocr_paginas={1})[0], email)
                self.assertEqual(varrer(email, lib, ocr_paginas={1}), [])
        self.assertEqual(mascarar("pessoa(Dorgao.gov.br.exemplo.com")[0], "[e-mail omitido]")

    def test_ocr_exige_dominio_com_tld(self) -> None:
        for texto in ("contato(Dgmail", "contato(Qexemplo.invalido", "pessoaOgmail",
                      "documento(D artigo", "pessoaOgmail.composto"):
            with self.subTest(texto=texto):
                _sem_mudanca(self, texto)
                self.assertEqual(varrer(texto), [])

    def test_email_pessoal_mascarado(self) -> None:
        for email in ("fulano.tal@exemplo.com.br", "a+b@x.io", "c@camaraniteroi.rj.gov.br.exemplo.com",
                      "fulano@gmail.com", "x@gov.br.exemplo.com", "x@naogov.br"):
            with self.subTest(email=email):
                saida, contagens = mascarar(f"Escreva para {email}.")
                self.assertEqual(saida, "Escreva para [e-mail omitido].")
                self.assertEqual(contagens["email"], 1)

    def test_email_institucional_liberado(self) -> None:
        for email in ("gabinete@camaraniteroi.rj.gov.br", "Ouvidoria@NITEROI.RJ.GOV.BR",
                      "protocolo@sub.niteroi.rj.gov.br", "servidor@tjrj.jus.br",
                      "x@sub.orgao.leg.br", "x@orgao.mp.br", "x@orgao.def.br", "x@orgao.mil.br",
                      "d@fakeniteroi.rj.gov.br"):
            with self.subTest(email=email):
                _sem_mudanca(self, f"Escreva para {email}.")
                self.assertEqual(varrer(f"Escreva para {email}."), [])

    def test_telefone_dentro_de_email_nao_vaza(self) -> None:
        saida, _ = mascarar("contato 2126201234@exemplo.com")
        self.assertEqual(saida, "contato [e-mail omitido]")


class TestEmailAuditoriaV5(unittest.TestCase):
    def test_versao(self) -> None:
        self.assertEqual(mascara.VERSAO_MASCARA, "10")

    def _email_mascarado(self, texto: str, esperado: str) -> None:
        for paginas in (None, {1}, {2}):
            with self.subTest(texto=texto, paginas=paginas):
                achados = varrer(texto, ocr_paginas=paginas)
                self.assertEqual([(a["tipo"], a["forte"]) for a in achados], [("email", True)])
                saida, contagens = mascarar(texto, ocr_paginas=paginas)
                self.assertEqual(saida, esperado)
                self.assertEqual(contagens, {**dict.fromkeys(mascara.TIPOS, 0), "email": 1})
                self.assertEqual(varrer(saida, ocr_paginas=paginas), [])
                self.assertEqual(mascarar(saida, ocr_paginas=paginas),
                                 (saida, dict.fromkeys(mascara.TIPOS, 0)))

    def test_exemplos_da_auditoria(self) -> None:
        for texto in (
            "uesben(Ogmail.com", "abrazrj(Ogmail.com", "abrazriO gmail.com",
            "jhontatananjos.niteroi(Pgmail.com", "jhonatananjos.niteroi gmail.com",
            "iteroiQgmai .com", "vereadordanielmarguesGgmail.com", "imprensa.crndgmail.com",
            "ferjji.contatoQgmail.com", "frederico.andradeQoutlook.com",
            "guilherme.giesta)gmail.com", "sheilafaulhaber? 1GDgmail.com",
            "instituto(altresromas.org", "instituio(atresromas.org",
            "Iwerj&hotmail.com", "IwerjDhotmail.com", "Iwerj&Photmail.com",
            "Iwer|Mhotmall.com", "mestrezezeu(Dyahõo.com.br", "DY AHOO.COM.BR",
            "riodejaneiroDabraz.org.br", "pessoaOexemplo.com",
            "instituto? xexemplo.org",
        ):
            self._email_mascarado(texto, "[e-mail omitido]")
        self._email_mascarado("No institutoQtresromas.org", "No [e-mail omitido]")
        self._email_mascarado("e-mail: secretariaofnp.org.br", "e-mail: [e-mail omitido]")
        self._email_mascarado("contato projetoavante.com", "contato [e-mail omitido]")

    def test_cabecalhos_com_emails_entre_angulos(self) -> None:
        texto = ("Frederico Andrade dos Santos <frederico.andradeQoutlook.com> "
                 "3 de fevereiro de 2026 às 12:16")
        self._email_mascarado(texto, "Frederico Andrade dos Santos <[e-mail omitido]> "
                             "3 de fevereiro de 2026 às 12:16")
        self._email_mascarado('Para: "[e-mail omitido]" <guilherme.giesta)gmail.com>',
                             'Para: "[e-mail omitido]" <[e-mail omitido]>')
        for email in ("fulano@gmail.com", "fulano@exemplo.org", "uesben(Ogmail.com",
                      "institutoQtresromas.org", "instituto(altresromas.org", "gmail.com"):
            self._email_mascarado(f"<{email}>", "<[e-mail omitido]>")
            achado = varrer(f"<{email}>")[0]
            self.assertEqual((achado["inicio"], achado["fim"]), (1, len(email) + 1))

    def test_prosa_ocr_entre_sinais_nao_e_tag(self) -> None:
        # Reprodução reduzida da supressão por uma zona <…> ampla: o trecho sem
        # o sinal inicial detectava o e-mail, mas o documento completo não.
        trecho = "AS 2 Site: www.Iwerj.com E-mail: IwerjDhotmail.com 485 4,"
        texto = "<Relatorio digitalizado\n" + "Texto do relatório. " * 10 + trecho + "\nFim >"
        esperado = texto.replace("IwerjDhotmail.com", "[e-mail omitido]")
        self._email_mascarado(texto, esperado)
        self._email_mascarado(trecho, trecho.replace("IwerjDhotmail.com", "[e-mail omitido]"))

    def test_email_forte_nao_desaparece_ao_adicionar_contexto(self) -> None:
        contextos = (
            ("<Relatorio digitalizado\n", "\nProsa de OCR >"),
            ("<rastro 1 " + "Prosa " * 200, " 2 fim>"),
            ('<registro origem="digitalizacao">\n', "\n</registro>"),
            ("Site: https://exemplo.org/relatorio\n", "\nFim."),
            ("www.exemplo.org <Prosa 2 Site: ", " 3 fim>"),
            ("Linha longa " + " " * 1000, " " * 1000 + " fim"),
        )
        for email in ("IwerjDhotmail.com", "frederico.andradeQoutlook.com",
                      "guilherme.giesta)gmail.com", "instituto(altresromas.org", "fulano@exemplo.org"):
            self.assertTrue(any(o["tipo"] == "email" and o["forte"] for o in varrer(email)))
            for antes, depois in contextos:
                with self.subTest(email=email, antes=antes[:40]):
                    texto = antes + email + depois
                    fortes = [o for o in varrer(texto) if o["tipo"] == "email" and o["forte"]]
                    self.assertEqual([(o["inicio"], o["fim"]) for o in fortes],
                                     [(len(antes), len(antes) + len(email))])
                    self.assertEqual(mascarar(texto)[0], antes + "[e-mail omitido]" + depois)

    def test_emails_entre_angulos_liberados(self) -> None:
        for email, lib in (("gabinetemichelsaad@gmail.com", {"gabinetemichelsaad@gmail.com"}),
                           ("frederico.andradeQoutlook.com", {"frederico.andrade@outlook.com"}),
                           ("servidor(Dtjrj.jus.br", set()),
                           ("12345678Ogmail.com", {"12345678@gmail.com"})):
            texto = f"Para: <{email}>"
            with self.subTest(email=email):
                _sem_mudanca(self, texto, lib)
                self.assertEqual(varrer(texto, lib), [])
                self.assertEqual(mascarar(texto, lib, ocr_paginas={1})[0], texto)
                self.assertEqual(varrer(texto, lib, ocr_paginas={1}), [])

    def test_tags_reais_nao_sao_enderecos_entre_angulos(self) -> None:
        for texto in ("<p>", "</p>", "<foo.bar>", "<pessoaQtresromas.org/>",
                      "</pessoaQtresromas.org>", '<a href="https://outlook.com">',
                      '<a href="frederico.andradeQoutlook.com">',
                      '<manifest:file-entry manifest:full-path="guilherme.giesta)gmail.com"/>',
                      '<?xml version="1.0" encoding="UTF-8"?>',
                      '<campo valor="uesben(Ogmail.com"/>'):
            with self.subTest(texto=texto):
                _sem_mudanca(self, texto)
                self.assertEqual(varrer(texto), [])

    def test_provedores_variantes_e_espaco_interno(self) -> None:
        for provedor in ("gmail", "gmai", "grnail", "hotmail", "hotmall", "hotmai", "yahoo",
                         "yahõo", "outlook", "live", "msn", "uol", "bol", "terra", "icloud", "globo", "ig"):
            formas = [provedor, provedor[:1] + " " + provedor[1:]]
            for forma in formas:
                for sufixo in (".com", " .com.br"):
                    self._email_mascarado("pessoaQ" + forma.upper() + sufixo.upper(), "[e-mail omitido]")

    def test_rotulos_e_pontuacao_nao_sao_engolidos(self) -> None:
        for rotulo in ("E-mail:", "e-mail", "email:", "e mail", "correio eletrônico", "Contato:", "Outro:"):
            self._email_mascarado(rotulo + " pessoa(Ogmail.com", rotulo + " [e-mail omitido]")
            self._email_mascarado(rotulo + " gmail.com", rotulo + " [e-mail omitido]")
        self._email_mascarado("(pessoaOgmail.com).", "([e-mail omitido]).")
        self._email_mascarado("uesben(Ogmail.com; fim", "[e-mail omitido]; fim")
        # Dois espaços não juntam o token anterior ao provedor.
        self._email_mascarado("anterior  gmail.com", "anterior  [e-mail omitido]")
        self._email_mascarado("contato@exemplo.org", "[e-mail omitido]")
        self._email_mascarado("e-mail@exemplo.org", "[e-mail omitido]")

    def test_rotulo_sem_arroba_e_janela(self) -> None:
        for rotulo in ("e-mail", "email", "e mail", "correio eletrônico", "CORREIO ELETRÔNICO"):
            self._email_mascarado(rotulo + ": secretariaofnp.org.br", rotulo + ": [e-mail omitido]")
        self._email_mascarado("e-mail: envio para secretaria.exemplo.org", "e-mail: envio para [e-mail omitido]")
        self._email_mascarado("email " + " " * 23 + "secretaria.exemplo.org",
                             "email " + " " * 23 + "[e-mail omitido]")
        texto = "email " + " " * 25 + "secretaria.exemplo.org"
        _sem_mudanca(self, texto)
        self.assertEqual(varrer(texto), [])
        # Só o primeiro domínio pertence ao rótulo; a segunda passagem não pode
        # reinterpretar a marca [e-mail omitido] nem avançar para outro domínio.
        self._email_mascarado("email: pessoa.exemplo.org outra.exemplo.org",
                             "email: [e-mail omitido] outra.exemplo.org")

    def test_urls_metadados_e_dominios_publicos_intactos(self) -> None:
        for token in (
            "verificador.iti.gov.br", ".planalto.gov.br", "alerjln1.alerj.rj.gov.br",
            "consumidor.gov", "camaraniteroi.siscam.com.br", "web: abrazrj.com.br",
            "www.gmail.com", "www.institutoQtresromas.org", "https://gmail.com",
            "WWW.gmail.com", "HTTPS://institutoQtresromas.org",
            "https://institutoQtresromas.org", '//institutoQtresromas.org',
            'name="microsoft.com', 'name="pessoaOgmail.com',
            '<item name="institutoQtresromas.org"/>', "www.exemplo.org", "https://exemplo.org",
        ):
            # Um domínio privado solto é legítimo; depois de um rótulo de e-mail,
            # porém, a regra C o trata como contato. URLs/atributos continuam
            # protegidos mesmo nesse contexto.
            contextos = (token, "email: " + token) if any(
                marca in token for marca in ("www", "http", "=", "//", "web:")) else (token,)
            for texto in contextos:
                with self.subTest(texto=texto):
                    _sem_mudanca(self, texto)
                    self.assertEqual(varrer(texto), [])
        for texto in ("email servidororgao.gov.br", "email servidororgao.jus.br",
                      "servidorQorgao.leg.br", "servidorDorgao.gov.br",
                      "email: 12345678orgao.gov.br"):
            with self.subTest(texto=texto):
                _sem_mudanca(self, texto)
                self.assertEqual(mascarar(texto, ocr_paginas={1})[0], texto)
                self.assertEqual(varrer(texto, ocr_paginas={1}), [])

    def test_liberacao_por_reconstrucoes(self) -> None:
        for texto, endereco in (
            ("jhonatananjos.niteroi gmail.com", "jhonatananjos.niteroi@gmail.com"),
            ("abrazriO gmail.com", "abrazri@gmail.com"),
            ("pessoa(Dgrnail .com", "pessoa@gmail.com"),
            ("pessoa&Photmall.com", "pessoa@hotmail.com"),
            ("mestrezezeu(Dyahõo.com.br", "mestrezezeu@yahoo.com.br"),
            ("imprensa.crndgmail.com", "imprensa.crn@gmail.com"),
            ("instituto(altresromas.org", "instituto@tresromas.org"),
            ("instituio(atresromas.org", "instituio@tresromas.org"),
            ("riodejaneiroDabraz.org.br", "riodejaneiro@abraz.org.br"),
            ("email: secretariaofnp.org.br", "secretaria@fnp.org.br"),
            ("email: secretaria.exemplo.org", "secretaria@exemplo.org"),
            ("email: 12345678exemplo.org", "12345678@exemplo.org"),
        ):
            with self.subTest(texto=texto):
                lib = {endereco}
                _sem_mudanca(self, texto, lib)
                self.assertEqual(mascarar(texto, lib, ocr_paginas={1})[0], texto)
                self.assertEqual(varrer(texto, lib, ocr_paginas={1}), [])
                self.assertEqual(len(varrer(texto)), 1)
        self._email_mascarado("servidorDorgao.gov.br.exemplo.com", "[e-mail omitido]")


class TestFalsosPositivos(unittest.TestCase):
    def test_cep_malformado_cinco_quatro_nao_e_telefone(self) -> None:
        for numero in ("24320-5902", "24320-5700", "24358-3800"):
            texto = f"NITERÓI - RJ, {numero}."
            with self.subTest(texto=texto):
                _sem_mudanca(self, texto)
                self.assertEqual(varrer(texto), [])
                _sem_mudanca(self, "Tel: " + numero)
                self.assertEqual(varrer("Tel: " + numero), [])
        for numero in ("2620-1234", "(21) 98765-4321", "98765-4321"):
            texto = "Tel: " + numero
            self.assertEqual(mascarar(texto)[0], "Tel: [telefone omitido]")
            self.assertEqual([(o["tipo"], o["forte"]) for o in varrer(numero)], [("telefone", True)])

    def test_faixas_de_numeracao_predial(self) -> None:
        for texto in ("NA ALTURA DOS NÚMEROS 1109-1203 – CHARITAS.",
                      "número 2620-2630", "números 2620-2630", "nºs 2620-2630",
                      "n.ºs 2620-2630", "nos 2620-2630", "altura do 2620-2630",
                      "altura dos 2620-2630"):
            with self.subTest(texto=texto):
                _sem_mudanca(self, texto)
                self.assertEqual(varrer(texto), [])
                self.assertEqual(mascarar(texto, ocr_paginas={1})[0], texto)
                self.assertEqual(varrer(texto, ocr_paginas={1}), [])
        texto = "Números de telefone 2620-1234"
        self.assertEqual(mascarar(texto)[0], "Números de telefone [telefone omitido]")
        self.assertEqual([(o["tipo"], o["forte"]) for o in varrer(texto)], [("telefone", True)])
        texto = "Números " + "distante" * 4 + " 2620-1234"
        self.assertEqual(mascarar(texto)[0], texto.replace("2620-1234", "[telefone omitido]"))
        self.assertEqual([(o["tipo"], o["forte"]) for o in varrer(texto)], [("telefone", True)])

    def test_listas_de_numeros_de_documentos(self) -> None:
        for texto in ("4406, 4407", "4404, 4405, 4406, 4407, 4408",
                      "4404, 4405, 4406 4407, 4408", "4404, 4405 4406 e 4407",
                      "4404 e 4405 e 4406", "4404,\n4405, 4406 4407, 4408",
                      "4404, 4405 4406.", "4404, 4405 E 4406."):
            with self.subTest(texto=texto):
                _sem_mudanca(self, texto)
                self.assertEqual(varrer(texto), [])
                self.assertEqual(mascarar(texto, ocr_paginas={1})[0], texto)
                self.assertEqual(varrer(texto, ocr_paginas={1}), [])
        # A proteção não se estende a telefones seguintes nem a pares isolados com espaço.
        for telefone in ("2620-1234", "(21) 2620 1234", "2620 1234"):
            texto = "4404, 4405, 4406; ligue " + telefone
            self.assertEqual(mascarar(texto)[0], "4404, 4405, 4406; ligue [telefone omitido]")
            self.assertEqual(len(varrer(texto)), 1)
        texto = "Telefone (21) 2620 1234, 4404"
        self.assertEqual(mascarar(texto)[0], "Telefone [telefone omitido], 4404")
        self.assertEqual([(a["tipo"], a["forte"]) for a in varrer(texto)], [("telefone", True)])

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
            *("@" + d for d in mascara.DOMINIOS_LIBERADOS),
        })
        texto = ("Gabinete: 3333-4444, (21) 3333-4444 ou +55 21 3333-4444; fulano.gabinete@exemplo.com; "
                 "Câmara (21) 2620-1234; pessoal (21) 5555-6666 e (21) 98888-7777.")
        saida, contagens = mascarar(texto, lib)
        self.assertEqual(saida, texto.replace("(21) 5555-6666", "[telefone omitido]")
                         .replace("(21) 98888-7777", "[telefone omitido]"))
        self.assertEqual(contagens["telefone"], 2)

    def test_email_liberado_precisa_ser_endereco_completo(self) -> None:
        fonte = "https://www.camaraniteroi.rj.gov.br/x"
        contatos = [{"tipo": "email", "valor": v, "fonte": fonte}
                    for v in ("@exemplo.com", "exemplo.com", "a@b@c.com", "ok@exemplo.com")]
        with tempfile.TemporaryDirectory() as nome:
            pasta = Path(nome)
            self._config(pasta, backend={"contatos_institucionais": contatos})
            lib = liberados(pasta)
        self.assertEqual(lib - {"@" + d for d in mascara.DOMINIOS_LIBERADOS}, {"ok@exemplo.com"})
        saida, _ = mascarar("x@exemplo.com e ok@exemplo.com", lib)
        self.assertEqual(saida, "[e-mail omitido] e ok@exemplo.com")

    def test_arquivos_ausentes(self) -> None:
        with tempfile.TemporaryDirectory() as nome:
            pasta = Path(nome)
            self._config(pasta)
            self.assertEqual(liberados(pasta), {"@" + d for d in mascara.DOMINIOS_LIBERADOS})

    def test_config_do_repositorio(self) -> None:
        lib = liberados(RAIZ)
        self.assertIn("@gov.br", lib)


class TestIdempotenciaVarrer(unittest.TestCase):
    TEXTO = (f"CPF {CPF_A} e 11144477735; RG 12.345.678-9; tel (21) 99999-9999, 2620-1234 e "
             "+55 21 2222-3333; e-mail a.b@exemplo.com e c@d.org. Lei 3.456/2020, CEP 24020-000.")

    def test_contagens(self) -> None:
        _, contagens = mascarar(self.TEXTO)
        self.assertEqual(contagens, {"cpf": 2, "rg": 1, "telefone": 3, "email": 2, "documento": 0, "numero": 0})

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
            self.assertEqual(set(a), {"tipo", "inicio", "fim", "forte"})
            self.assertTrue(a["forte"])
        primeiro = achados[0]
        self.assertEqual(self.TEXTO[primeiro["inicio"]:primeiro["fim"]], CPF_A)
        mascarado, _ = mascarar(self.TEXTO)
        self.assertEqual(varrer(mascarado), [])
        # um dado acrescentado depois da máscara é encontrado
        self.assertEqual([a["tipo"] for a in varrer(mascarado + " Novo: (21) 98888-7777")], ["telefone"])

    def test_texto_vazio(self) -> None:
        self.assertEqual(mascarar(""), ("", {tipo: 0 for tipo in mascara.TIPOS}))
        self.assertEqual(varrer(""), [])

    def test_varrer_e_mais_amplo_que_mascarar(self) -> None:
        texto = "Protocolo nº 2026-1234, código 26201234 e CPF 529 982 247 25"
        saida, contagens = mascarar(texto)
        # o protocolo e os dígitos corridos ficam (protegidos ou ambíguos); o CPF com
        # espaços é mascarado
        self.assertEqual(contagens, {"cpf": 1, "rg": 0, "telefone": 0, "email": 0, "documento": 0, "numero": 0})
        self.assertEqual(saida, "Protocolo nº 2026-1234, código 26201234 e CPF [CPF omitido]")
        achados = varrer(texto)
        self.assertEqual([a["tipo"] for a in achados], ["telefone", "telefone", "cpf"])
        # "2026-1234" logo depois de protocolo e "26201234" só de dígitos: fracos
        self.assertEqual([a["forte"] for a in achados], [False, False, True])

    def test_forca_das_ocorrencias(self) -> None:
        casos = {
            "Tel. (21) 2620-1234": ("telefone", True),
            "Tel. +5521998887777": ("telefone", True),
            "Tel. 2620 1234": ("telefone", True),
            "Código 26201234": ("telefone", False),
            "Código 2126201234": ("telefone", False),
            "CPF 52998224725": ("cpf", True),
            "RG 12.345.678-9": ("rg", True),
            "e-mail fulano@exemplo.org": ("email", True),
        }
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                achados = varrer(texto)
                self.assertEqual([(a["tipo"], a["forte"]) for a in achados], [esperado])

    def test_medir(self) -> None:
        with tempfile.TemporaryDirectory() as nome:
            pasta = Path(nome)
            (pasta / "a.txt").write_text("CPF 529.982.247-25 e protocolo 26201234", encoding="utf-8")
            (pasta / "b.txt").write_text("Processo nº 2024-1234, Ofício nº 3456-7890, tel (21) 2620-1234",
                                         encoding="utf-8")
            (pasta / "c.txt").write_text("Sem dados pessoais.", encoding="utf-8")
            resultado = mascara.medir(pasta)
        self.assertEqual(resultado, {
            "documentos": 3,
            "mascarados": {"cpf": 1, "rg": 0, "telefone": 1, "email": 0, "documento": 0, "numero": 0},
            "restantes": {"telefone_forte": 1, "telefone_fraco": 2},
            "documentos_com_forte": 1,
            "documentos_com_fraco": 2,
        })
        self.assertNotIn("2620", json.dumps(resultado))

    def test_forca_por_contexto(self) -> None:
        casos = {
            "Ação por conta do Programa 2045.1234": False,   # código orçamentário
            "Lei Ordinária 2620 1234": False,                # coluna de tabela depois de "lei"
            "Protocolo nº: 212620-1234": False,
            "Protocolo do dia 10/05 202112345": False,
            "Código 2620 1234": False,
            "Código 2620.1234": False,
            "cel. 2620 1234": True,
            "Contato: 2620.1234": True,
            "Fone 26201234": True,
            "(21) 2620 1234": True,
            "021 2620 1234": True,
            "+55 21 2620 1234": True,
            "Código 2620-1234": True,
        }
        for texto, forte in casos.items():
            with self.subTest(texto=texto):
                achados = varrer(texto)
                self.assertEqual([(a["tipo"], a["forte"]) for a in achados], [("telefone", forte)])

    def test_varrer_ignora_links_marcacao_e_metadados(self) -> None:
        for texto in (
            "https://www.niteroi.rj.gov.br/decreto-n-98765-4321",
            "ver leismunicipais.com.br/lei-2620-1234 e www.exemplo.org/2620-1234",
            "<dc:date>2021-05-10T14:32:15.123456789</dc:date>",
            "<dc:date>2021-05-10T14:32:52.998224725</dc:date>",  # CPF válido no carimbo
            '<ext uri="{28A0092B-C50C-407E-A947-70E740481C1C}"/>',
            '<w:pgSz width="26.20123456"/>',
        ):
            with self.subTest(texto=texto):
                self.assertEqual(varrer(texto), [])
                self.assertEqual(mascarar(texto)[0], texto)  # links e metadados intactos
        self.assertTrue(mascara.cpf_valido("52998224725"))

    def test_varrer_ignora_so_as_protecoes_explicitas(self) -> None:
        texto = ("em 12/03/2024, mandato 2021-2024, CEP 24020-000, CNPJ 11.222.333/0001-81, "
                 "Lei nº 2620-1234, R$ 2620-1234 e processo 0001234-56.2024.8.19.0002")
        self.assertEqual(varrer(texto), [])
        self.assertTrue(mascara.cnpj_valido("11222333000181"))
        self.assertFalse(mascara.cnpj_valido("11222333000182"))

    def test_varrer_usa_os_liberados(self) -> None:
        self.assertEqual(varrer("Ligue 3333-4444", {"2133334444"}), [])
        self.assertEqual(varrer("Ligue (11) 3333-4444", {"1133334444"}), [])
        self.assertEqual(varrer("gabinete@camaraniteroi.rj.gov.br e x@niteroi.rj.gov.br"), [])
        self.assertEqual([a["tipo"] for a in varrer("Ligue (11) 3333-4444")], ["telefone"])
        self.assertEqual([a["tipo"] for a in varrer("Escreva para (fulano@exemplo.org).")], ["email"])


class TestQuartaMedicao(unittest.TestCase):
    """Formas da quarta medição no corpus real (com dígitos sintéticos)."""

    def test_url_continua_depois_de_quebra_de_linha(self) -> None:
        texto = ("Disponível em https://www.scielo.br/pdf/pcp/\n"
                 "v12nspe1/2620-1234-pcp-12-spe1-2026.pdf\nTexto seguinte")
        _sem_mudanca(self, texto)
        self.assertEqual(varrer(texto), [])
        # só uma quebra de linha; uma palavra comum na linha seguinte encerra a URL
        saida, _ = mascarar("Ver www.exemplo.com.br/\nLigue 2620-1234")
        self.assertEqual(saida, "Ver www.exemplo.com.br/\nLigue [telefone omitido]")

    def test_doi(self) -> None:
        for texto in ("DOI: 10.1111/j.2620-1234.2012.tb12345.x",
                      "doi:10.1590/S0102-311X2012000100001 e mais",
                      "https://doi.org/10.1000/2620-1234"):
            with self.subTest(texto=texto):
                _sem_mudanca(self, texto)
                self.assertEqual(varrer(texto), [])

    def test_decimais_nao_sao_telefone_nem_cpf(self) -> None:
        for texto in ("passa a ser de 1,04712345678", "| 3,14159265358 | 2,71828182845 |",
                      "valor 1.234,52998224725", "índice 1.04712345678"):
            with self.subTest(texto=texto):
                _sem_mudanca(self, texto)
                self.assertEqual(varrer(texto), [])
        # telefones colados por vírgula continuam mascarados
        self.assertEqual(mascarar("2620-1234,2620-5678")[0], "[telefone omitido],[telefone omitido]")

    def test_digitos_corridos_de_tabela_ficam(self) -> None:
        for texto in ("                              2025                          1,04712345678",
                      "   7612345", "Valor 2126201234", "Total 21998887777 e 02126201234"):
            with self.subTest(texto=texto):
                _sem_mudanca(self, texto)
        self.assertEqual([a["forte"] for a in varrer("Valor 2126201234")], [False])
        # com rótulo, dígitos corridos ainda são telefone
        self.assertEqual(mascarar("Tel. 2126201234")[0], "Tel. [telefone omitido]")
        self.assertEqual(mascarar("https://wa.me/5521998887777")[0], "https://wa.me/[telefone omitido]")


class TestTerceiraMedicao(unittest.TestCase):
    """Formas da terceira medição no corpus real (com dígitos sintéticos)."""

    def test_rotulo_de_identidade_com_erro_de_ocr(self) -> None:
        self.assertTrue(mascara.cpf_valido("12345678909"))
        casos = {
            "Identdede: 12345678909": "Identdede: [CPF omitido]",       # 11 dígitos, DV de CPF
            "Idenlidade: 123456789": "Idenlidade: [RG omitido]",
            "IDENTIDADE nº 12345678901": "IDENTIDADE nº [RG omitido]",  # 11 dígitos sem DV válido
            "R. G. 12.345.678-9": "R. G. [RG omitido]",
            "rg: 123456789": "rg: [RG omitido]",
        }
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                saida, _ = mascarar(texto)
                self.assertEqual(saida, esperado)
                self.assertEqual(mascarar(saida)[0], saida)
                self.assertFalse([a for a in varrer(saida) if a["forte"]])
        # sem a marca ":"/"nº" nem "carteira"/"cédula", variante de "identidade" não é rótulo
        _sem_mudanca(self, "Identdede visual 123456789")

    def test_url_quebrada_pela_diagramacao(self) -> None:
        texto = "Disponível em: scielo.br/pdf/pcp/ v12nspe1/ 1234-5678.pdf e mais"
        _sem_mudanca(self, texto)
        self.assertEqual(varrer(texto), [])
        texto = "Fonte: www.exemplo.org/artigos/ v3n2/ 2620-1234"
        _sem_mudanca(self, texto)
        self.assertEqual(varrer(texto), [])
        # depois do endereço, palavra comum encerra a URL: o telefone seguinte é mascarado
        saida, _ = mascarar("Ver www.exemplo.com.br/ e ligue 2620-1234")
        self.assertEqual(saida, "Ver www.exemplo.com.br/ e ligue [telefone omitido]")
        saida, _ = mascarar("Ver www.exemplo.com.br/ (21) 2620-1234")
        self.assertEqual(saida, "Ver www.exemplo.com.br/ [telefone omitido]")

    def test_protocolo_e_sic_e_ouvidoria(self) -> None:
        for texto in ("Pedido E-SIC nº 2620-1234", "Protocolo e-SIC 2620-1234", "SIC: 2620-1234",
                      "Ouvidoria nº 2620-1234", "Pedido eSIC nº 2620-1234"):
            with self.subTest(texto=texto):
                _sem_mudanca(self, texto)
                achados = varrer(texto)
                self.assertEqual([(a["tipo"], a["forte"]) for a in achados], [("telefone", False)])
        # sem o contexto, o mesmo número com hífen é forte
        self.assertEqual([a["forte"] for a in varrer("Código 2620-1234")], [True])


class TestSegundaMedicao(unittest.TestCase):
    """Formas da segunda medição no corpus real (com dígitos sintéticos)."""

    def test_intervalo_de_anos_nao_e_telefone(self) -> None:
        for texto in ("cientista Vital Brazil (1865-1950)", "poeta (1922 – 1990) e músico",
                      "período 1500-1600", "obras de 2000-2100"):
            with self.subTest(texto=texto):
                _sem_mudanca(self, texto)
                self.assertEqual(varrer(texto), [])
        # anos fora da faixa ou fora de ordem não são intervalo
        self.assertEqual(mascarar("Contato: 2100-2200")[0], "Contato: [telefone omitido]")
        self.assertEqual([a["tipo"] for a in varrer("Código 2150-1990")], ["telefone"])

    def test_documentos_pessoais_rotulados(self) -> None:
        casos = {
            "ID: 12345 MF/RJ – CNH 12345678901": "ID: 12345 MF/RJ – CNH [documento omitido]",
            "RENACH RJ123456789": "RENACH [documento omitido]",
            "Título de eleitor nº 1234 5678 9012": "Título de eleitor nº [documento omitido]",
            "titulo eleitoral: 123456789012": "titulo eleitoral: [documento omitido]",
            "PIS/PASEP: 123.45678.90-1": "PIS/PASEP: [documento omitido]",
            "NIS 12345678901": "NIS [documento omitido]",
            "NIT nº 12345678901": "NIT nº [documento omitido]",
            "Passaporte FZ123456": "Passaporte [documento omitido]",
            "CTPS 1234567 série 0012": "CTPS [documento omitido] série 0012",
            "carteira de trabalho 1234567": "carteira de trabalho [documento omitido]",
            "Cartão SUS 123 4567 8901 2345": "Cartão SUS [documento omitido]",
            "cartão do SUS: 123456789012345": "cartão do SUS: [documento omitido]",
            "CNS: 123456789012345": "CNS: [documento omitido]",
        }
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual([(a["tipo"], a["forte"]) for a in varrer(texto)], [("documento", True)])
                saida, contagens = mascarar(texto)
                self.assertEqual(saida, esperado)
                self.assertEqual(contagens["documento"], 1)
                self.assertEqual(mascarar(saida), (saida, {tipo: 0 for tipo in mascara.TIPOS}))
                self.assertEqual(varrer(saida), [])

    def test_documento_sem_rotulo_ou_curto_fica(self) -> None:
        for texto in ("CNH válida até 10/10/2025", "PIS 2024", "nitrato 12345678",
                      "Unidade de piso 12345678", "CNH " + "distante " * 5 + "12345678901"):
            with self.subTest(texto=texto):
                _sem_mudanca(self, texto)

    def test_valores_de_planilha_xml(self) -> None:
        for texto in ('<c r="B2" s="1"><v>12345.123456789</v></c>',
                      '<x:c si="12"/><v>21998887777</v>',
                      "<si><t>21998887777</t></si>", "<f>2126201234</f>"):
            with self.subTest(texto=texto):
                _sem_mudanca(self, texto)
                self.assertEqual(varrer(texto), [])
        # texto de célula que não é só número continua mascarado
        self.assertEqual(mascarar("<t>Tel. (21) 2620-1234</t>")[0], "<t>Tel. [telefone omitido]</t>")

    def test_medir_conta_documentos(self) -> None:
        with tempfile.TemporaryDirectory() as nome:
            pasta = Path(nome)
            (pasta / "a.txt").write_text("CNH 12345678901 e Vital Brazil (1865-1950)", encoding="utf-8")
            resultado = mascara.medir(pasta)
        self.assertEqual(resultado["mascarados"]["documento"], 1)
        self.assertEqual(resultado["restantes"], {})


class TestFormasDoCorpusReal(unittest.TestCase):
    """Formas medidas no corpus real (com dígitos sintéticos)."""

    def test_telefones_que_escapavam_sao_mascarados(self) -> None:
        casos = {
            "[telefone omitido] –– cel.  2620-1234": "[telefone omitido] –– cel.  [telefone omitido]",
            "            (21) 2620-1234": "            [telefone omitido]",
            "CELULAR:    (21)2620-1234": "CELULAR:    [telefone omitido]",
            "Celular: 021-2620-1234": "Celular: [telefone omitido]",
            "      (21) 26201234": "      [telefone omitido]",
            # celulares antigos de 8 dígitos começando por 6–9
            "Tel. (21) 2620-1234 –– cel.  9876-5432": "Tel. [telefone omitido] –– cel.  [telefone omitido]",
            "            (21) 9876-5432": "            [telefone omitido]",
            "CELULAR:    (21)9876-5432": "CELULAR:    [telefone omitido]",
            "Celular: 021-9876-5432": "Celular: [telefone omitido]",
            "      (21) 98765432": "      [telefone omitido]",
            # palavra de ato em outra linha ou coluna (-layout) não protege o telefone
            "Ata da sessão\n            (21) 9876-5432": "Ata da sessão\n            [telefone omitido]",
            "Termo de posse          (21) 2620-1234": "Termo de posse          [telefone omitido]",
            # ponto como separador só com rótulo ou DDD
            "Tel.: 2620.1234": "Tel.: [telefone omitido]",
            "(21) 2620.1234": "[telefone omitido]",
            # link de WhatsApp continua pessoal
            "https://wa.me/5521998887777": "https://wa.me/[telefone omitido]",
        }
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                saida, _ = mascarar(texto)
                self.assertEqual(saida, esperado)
                self.assertEqual(mascarar(saida)[0], saida)  # idempotente
                self.assertFalse([a for a in varrer(saida) if a["forte"]])

    def test_numeros_que_nao_sao_telefone_ficam(self) -> None:
        for texto in ("Ação por conta do Programa 2045.1234", "Lei Ordinária 2620 1234",
                      "Protocolo nº: 212620-1234", "Protocolo do dia 10/05 202112345",
                      "Código 9876 5432", "Código 98765432"):
            with self.subTest(texto=texto):
                _sem_mudanca(self, texto)

    def test_documento_misto_sem_ocorrencias_fortes(self) -> None:
        documento = "\n".join([
            "Ação por conta do Programa 2045.1234 e da Ação 2046.5678",
            "Lei Ordinária 3456 7890",
            "<dc:date>2021-05-10T14:32:52.998224725</dc:date>",
            '<w:pgSz width="26.20123456"/>',
            "Ver https://www.niteroi.rj.gov.br/decreto-n-98765-4321 e www.exemplo.gov.br/lei/2620-1234",
            '<ext uri="{28A0092B-C50C-407E-A947-70E740481C1C}"/>',
            "Protocolo nº: 212620-1234; Protocolo do dia 10/05 202112345",
            "Tel. (21) 2620-1234 –– cel.  9876-5432",
            "            (21) 9876-5432",
            "CELULAR:    (21)9876-5432",
            "Celular: 021-9876-5432",
            "      (21) 98765432",
        ])
        mascarado, contagens = mascarar(documento)
        self.assertEqual(contagens, {"cpf": 0, "rg": 0, "telefone": 6, "email": 0, "documento": 0, "numero": 0})
        for intacto in ("Programa 2045.1234", "Ação 2046.5678", "Lei Ordinária 3456 7890",
                        "decreto-n-98765-4321", "www.exemplo.gov.br/lei/2620-1234", "nº: 212620-1234",
                        "10/05 202112345", "2021-05-10T14:32:52.998224725", 'width="26.20123456"'):
            self.assertIn(intacto, mascarado)
        achados = varrer(mascarado)
        self.assertEqual([a for a in achados if a["forte"]], [])
        self.assertTrue(achados)  # os números ambíguos continuam contados como fracos
        self.assertTrue(all(a["tipo"] == "telefone" for a in achados))


class TestRotulosDoOcr(unittest.TestCase):
    """Regressões das páginas digitalizadas, também cobertas sem ativar modo OCR."""

    def test_rg_com_sufixo_colado(self) -> None:
        for texto, esperado in (
            ("RG:12345SSP/AM", "RG:[RG omitido]SSP/AM"),
            ("RG 12345E OAB - RJ", "RG [RG omitido]E OAB - RJ"),
        ):
            with self.subTest(texto=texto):
                saida, contagens = mascarar(texto)
                self.assertEqual(saida, esperado)
                self.assertEqual(contagens["rg"], 1)
                self.assertFalse([a for a in varrer(saida) if a["forte"]])

    def test_habilitacao_rotulada(self) -> None:
        for texto in (
            "VALIDADE 12 HABILITAÇÃO\nDq moda 12345678901 12/03/2026",
            "Nº REGI: VALIDADE 12 HABILITAÇÃO — O ml 12345678901",
            "cédula de habilitação nº12345678901",
            "CNH emitida pelo órgão estadual 12345678901",
            "registro " + "x" * 28 + " 12345678901",
        ):
            with self.subTest(texto=texto):
                saida, contagens = mascarar(texto)
                self.assertEqual(saida, texto.replace("12345678901", "[documento omitido]"))
                self.assertEqual(contagens["documento"], 1)
                self.assertTrue(any(a["tipo"] == "documento" and a["forte"] for a in varrer(texto)))
                self.assertFalse([a for a in varrer(saida) if a["forte"]])

    def test_cpf_com_primeiro_digito_separado(self) -> None:
        for texto, numero in (
            ("CPF 1 23.456.789-09", "1 23.456.789-09"),
            ("CPF sob 1 nº2 34.567.890-12", "2 34.567.890-12"),
        ):
            with self.subTest(texto=texto):
                saida, contagens = mascarar(texto)
                self.assertEqual(saida, texto.replace(numero, "[CPF omitido]"))
                self.assertEqual(contagens["cpf"], 1)
                self.assertEqual([(a["tipo"], a["forte"]) for a in varrer(texto)], [("cpf", True)])
                self.assertEqual(varrer(saida), [])

    def test_cpf_no_certificado_digital(self) -> None:
        for texto, numero in (
            ("NOMEFICTICIO SILVA:1234567 8901\nAssinado de forma digital", "1234567 8901"),
            ("SILVA:12345678901", "12345678901"),
            ("SILVA:\n12345678901", "12345678901"),
            ("Assinado de forma digital por Silva:12345678901", "12345678901"),
            ("Silva:12345678901\nassinado digitalmente", "12345678901"),
        ):
            with self.subTest(texto=texto):
                saida, contagens = mascarar(texto)
                self.assertEqual(saida, texto.replace(numero, "[CPF omitido]"))
                self.assertEqual(contagens["cpf"], 1)
                self.assertEqual([(a["tipo"], a["forte"]) for a in varrer(texto)], [("cpf", True)])
                self.assertFalse([a for a in varrer(saida) if a["forte"]])
        _sem_mudanca(self, "Silva:12345678901 sem carimbo de assinatura")
        # O contexto digital vale só na janela, e marcas de tipos de documentos não
        # viram nomes de titulares (CNS/PIS/CNH continuam sendo documentos).
        _sem_mudanca(self, "digitalmente " + "x" * 61 + " Silva:12345678901")

    def test_telefones_com_ddd_rotulo_e_barra(self) -> None:
        casos = {
            "Fone: 21 2620-1234": "Fone: [telefone omitido]",
            "Fone: 20 2620-1234": "Fone: [telefone omitido]",  # DDD com erro de OCR
            "Tel.: 21 2620-1234 / 9876-5432": "Tel.: [telefone omitido] / [telefone omitido]",
            "Tel/Fax: (21 2620-1234": "Tel/Fax: [telefone omitido]",
            "[telefone omitido] / 20 9876-5432": "[telefone omitido] / [telefone omitido]",
        }
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                saida, contagens = mascarar(texto)
                self.assertEqual(saida, esperado)
                self.assertGreater(contagens["telefone"], 0)
                self.assertEqual(mascarar(saida), (saida, dict.fromkeys(mascara.TIPOS, 0)))
                self.assertFalse([a for a in varrer(saida) if a["forte"]])


class TestNumerosOcr(unittest.TestCase):
    def test_somente_paginas_selecionadas_e_offsets(self) -> None:
        texto = "Tabela 12345678\n\f\nAssinatura 12345678\n\f\nTotal 12345678"
        esperado = texto.replace("Assinatura 12345678", "Assinatura [número omitido]")
        saida, contagens = mascarar(texto, ocr_paginas={2})
        self.assertEqual(saida, esperado)
        self.assertEqual(contagens, {**dict.fromkeys(mascara.TIPOS, 0), "numero": 1})
        self.assertEqual(mascarar(saida, ocr_paginas={2}), (saida, dict.fromkeys(mascara.TIPOS, 0)))
        self.assertFalse([a for a in varrer(saida, ocr_paginas={2}) if a["forte"]])
        fortes = [a for a in varrer(texto, ocr_paginas={2}) if a["forte"]]
        self.assertEqual(len(fortes), 1)
        self.assertEqual(fortes[0]["tipo"], "numero")
        self.assertEqual(texto[fortes[0]["inicio"]:fortes[0]["fim"]], "12345678")
        self.assertEqual(fortes[0]["inicio"], texto.index("12345678", texto.index("\f")))
        _sem_mudanca(self, texto)
        self.assertEqual(mascarar(texto, ocr_paginas=set())[0], texto)

    def test_numeros_separados_e_ruido_de_uma_letra(self) -> None:
        for numero in ("12345678", "123.456.78", "1234 5678", "1-234-5678", "1/23456E/ 78",
                       "12345678E9", "1234567-8901"):
            with self.subTest(numero=numero):
                texto = "Assinatura\n" + numero
                saida, contagens = mascarar(texto, ocr_paginas={1})
                self.assertEqual(saida, "Assinatura\n[número omitido]")
                self.assertEqual(contagens["numero"], 1)
                self.assertTrue(any(a["tipo"] == "numero" and a["forte"]
                                    for a in varrer(texto, ocr_paginas={1})))
                self.assertFalse([a for a in varrer(saida, ocr_paginas={1}) if a["forte"]])
                self.assertEqual(mascarar(saida, ocr_paginas={1}), (saida, dict.fromkeys(mascara.TIPOS, 0)))
        self.assertEqual(mascarar("1234567\n1234567", ocr_paginas={1})[0], "1234567\n1234567")

    def test_protecoes_explicitas(self) -> None:
        protegidos = (
            "em 12/03/2024", "data 2024-03-12", "R$ 12345678", "R$ 2.620.123,45",
            "valor 1,123456789", "valor 12345678,90", "CEP 24020-000", "CEP 24.020-000",
            "Lei nº 3.456/2020", "Decreto 12345/2024", "Processo nº 12345678/2024",
            "nº 1234/2020", "mandato 2021-2024", "período 1865-1950", "biênio 2025/2026",
        )
        for texto in protegidos:
            with self.subTest(texto=texto):
                saida, contagens = mascarar(texto, ocr_paginas={1})
                self.assertEqual(saida, texto)
                self.assertEqual(sum(contagens.values()), 0)
                self.assertFalse([a for a in varrer(saida, ocr_paginas={1}) if a["forte"]])

    def test_protecao_nao_libera_numero_vizinho(self) -> None:
        for protegido in ("12/03/2024", "2024-03-12", "Lei nº 3.456/2020", "CEP 24.020-000",
                          "R$ 12345678,90", "2021-2024"):
            for texto in (protegido + " 12345678", "12345678 " + protegido):
                with self.subTest(texto=texto):
                    saida, contagens = mascarar(texto, ocr_paginas={1})
                    self.assertIn(protegido, saida)
                    self.assertIn("[número omitido]", saida)
                    self.assertEqual(contagens["numero"], 1)
                    self.assertFalse([a for a in varrer(saida, ocr_paginas={1}) if a["forte"]])
        # CEP sem rótulo próximo não é proteção da regra agressiva.
        self.assertEqual(mascarar("24020-000", ocr_paginas={1})[0], "[número omitido]")
        self.assertEqual(mascarar("CEP " + "x" * 21 + " 24020-000", ocr_paginas={1})[1]["numero"], 1)

    def test_liberados_inclusive_email_numerico(self) -> None:
        lib = {"2126201234", "12345678@exemplo.org"}
        texto = ("Fone: (21 2620-1234\nFONE:2126201234\n2126201234\n"
                 "12345678@exemplo.org\n12345678@orgao.gov.br")
        saida, contagens = mascarar(texto, lib, ocr_paginas={1})
        self.assertEqual(saida, texto)
        self.assertEqual(sum(contagens.values()), 0)
        self.assertEqual(varrer(saida, lib, ocr_paginas={1}), [])

    def test_residuos_e_falsos_positivos_do_lote(self) -> None:
        for texto in ("SILVA:1/23456E/ 78", "João de Tal\n1234567-8901", "SQL:1234-5678-9012",
                      "Salas 1234-5678", "Ruído 123456789012345678"):
            with self.subTest(texto=texto):
                saida, _ = mascarar(texto, ocr_paginas={1})
                self.assertNotEqual(saida, texto)
                self.assertFalse([a for a in varrer(saida, ocr_paginas={1}) if a["forte"]])
        self.assertEqual(mascarar("DOI quebrado 10.1 234/s", ocr_paginas={1})[0], "DOI quebrado 10.1 234/s")

    def test_tabelas_nativas_permanecem(self) -> None:
        texto = "Tabela orçamentária\n12345678 12345678901\n1,123456789 2045.1234\nTotal 2126201234"
        _sem_mudanca(self, texto)
        self.assertEqual(mascarar(texto, ocr_paginas={2})[0], texto)
        self.assertNotIn("numero", [a["tipo"] for a in varrer(texto)])


class TestMascaraV8(unittest.TestCase):
    """Regressões sintéticas do vazamento, sombra e barreira independente."""

    def _limpo(self, texto: str, tipo: str, paginas=None) -> str:
        self.assertIn(tipo, {o["tipo"] for o in mascara.varrer_estrito(texto)})
        saida, contagens = mascarar(texto, ocr_paginas=paginas)
        self.assertIn(mascara.SUBSTITUICOES[tipo], saida)
        self.assertGreater(contagens[tipo], 0)
        self.assertEqual(mascara.varrer_estrito(saida), [])
        self.assertFalse([o for o in varrer(saida, ocr_paginas=paginas) if o["forte"]])
        self.assertEqual(mascarar(saida, ocr_paginas=paginas), (saida, dict.fromkeys(mascara.TIPOS, 0)))
        return saida

    def test_repros_do_vazamento(self) -> None:
        casos = (
            ("inscrito no CPF sob o nº 529,982.247-25", "cpf"),
            ("CPF 529.982,247/25", "cpf"),
            ("529,982.247-25", "cpf"),
            ("Identidade nº 12.345,678-9", "rg"),
            ("RG 12.345,678-9", "rg"),
            ("ID: 12.345.678-9, IFP/RJ", "rg"),
            ("Id: 12.345.678-9 SSP-RJ", "rg"),
            ("ID: 12345678-9", "rg"),
        )
        for texto, tipo in casos:
            for paginas in (None, {1}):
                with self.subTest(texto=texto, paginas=paginas):
                    self._limpo(texto, tipo, paginas)

    def test_negativos(self) -> None:
        casos = (
            "R$ 529.982,24", "Valor 1.234,56", "ID do processo 123",
            "ID do documento: 123456789", "ID: 12345 MF/RJ",
            "Identidade de gênero, Lei 13.709/2018", "Identidade, 22.11.2020",
            "RG: 13.709/2018", "RG 12.03.2024", "4406, 4407", "Tel: 24320-5902",
            "Contato: 2000-2021", "valor 1.234,52998224725", "CNPJ 11.222.333/0001-81",
            "Processo 0001234-56.2024.8.19.0002",
        )
        for texto in casos:
            with self.subTest(texto=texto):
                _sem_mudanca(self, texto)
                self.assertEqual(mascara.varrer_estrito(texto), [])
        self.assertEqual(mascarar("4406, 4407", ocr_paginas={1})[0], "4406, 4407")
        texto = "Telefone do gabinete: (21) 2620-1234"
        _sem_mudanca(self, texto, {"2126201234"})
        self.assertEqual(mascara.varrer_estrito(texto, {"2126201234"}), [])

    def test_identidade_rejeitada_nao_esconde_rotulo_de_rg_seguinte(self) -> None:
        texto = "Identidade visual, RG 12.345,678-9"
        self.assertEqual(self._limpo(texto, "rg"), "Identidade visual, RG [RG omitido]")

    def test_tracos_quebras_e_offsets(self) -> None:
        prefixo = "Art. 1º – "
        for traco in mascara._TRACOS + "-":
            for quebra in ("", "\n", " \n", "\r\n", " \r\n  "):
                for rotulo, valor, tipo in (
                    ("CPF ", "529.982.247" + traco + quebra + "25", "cpf"),
                    ("Tel ", "(21) 99999" + traco + quebra + "1234", "telefone"),
                    ("RG ", "12.345.678" + traco + quebra + "9", "rg"),
                ):
                    with self.subTest(traco=traco, quebra=quebra, tipo=tipo):
                        texto = prefixo + rotulo + valor + "; fim."
                        saida = self._limpo(texto, tipo)
                        self.assertEqual(saida, prefixo + rotulo + mascara.SUBSTITUICOES[tipo] + "; fim.")
                        achados = [o for o in varrer(texto) if o["tipo"] == tipo and o["forte"]]
                        self.assertTrue(achados)
                        self.assertEqual([texto[o["inicio"]:o["fim"]] for o in achados], [valor])

    def test_invisiveis_e_espacos_especiais(self) -> None:
        from coletor import trechos

        for valor, tipo in (("CPF 529.\u200b982.247\u00a0-\u00a025", "cpf"),
                            ("Tel\u00a0(21)\u00a0999\u200b99-1234", "telefone")):
            with self.subTest(tipo=tipo):
                saida, contagens = mascarar(valor)
                self.assertEqual(contagens[tipo], 1)
                self.assertIn(mascara.SUBSTITUICOES[tipo], saida)
                self.assertEqual(mascara.varrer_estrito(trechos.normalizar(saida)), [])
                self.assertEqual(mascarar(saida)[0], saida)

    def test_marcacao_nao_esconde_rotulos(self) -> None:
        for texto in ('<<Contato: Tel. (21) 99999-1234 CPF 52998224725>>',
                      '<campo valor="Tel (21) 99999-1234 CPF 52998224725"/>'):
            with self.subTest(texto=texto):
                saida, contagens = mascarar(texto)
                self.assertEqual((contagens["cpf"], contagens["telefone"]), (1, 1))
                self.assertEqual(mascara.varrer_estrito(saida), [])
                self.assertEqual(mascarar(saida)[0], saida)
        for texto in ('<p class="texto">…</p>', '<w:pgSz width="26.20123456"/>'):
            _sem_mudanca(self, texto)
            self.assertEqual(mascara.varrer_estrito(texto), [])

    def test_dominio_corrompido_nao_libera_email_pessoal(self) -> None:
        self.assertFalse(mascara._email_liberado(
            "fulano@gmail.com/camara.leg.br", set(), mascara.DOMINIOS_LIBERADOS))
        for sufixo in ("/camara.leg.br", "(camara.leg.br)", "/x@camara.leg.br"):
            with self.subTest(sufixo=sufixo):
                saida, _ = mascarar("fulano@gmail.com" + sufixo)
                self.assertTrue("fulano@gmail.com" not in saida or mascara.varrer_estrito(saida))

    def test_estrita_independente(self) -> None:
        texto = "CPF 529,982.247-25; ID: 12.345,678-9; Tel (21) 99999-1234; fulano@exemplo.org"
        auxiliares = {nome: mock.Mock(side_effect=AssertionError) for nome in
                      ("_detectar", "_protegidos", "_emails_ocr", "_zonas", "_Sombra")}
        with mock.patch.multiple(mascara, **auxiliares):
            achados = mascara.varrer_estrito(texto)
        self.assertEqual({o["tipo"] for o in achados}, {"cpf", "rg", "telefone", "email"})
        self.assertTrue(all(set(o) == {"tipo", "inicio", "fim"} for o in achados))
        self.assertEqual(achados, sorted(achados, key=lambda o: (o["inicio"], o["fim"], o["tipo"])))

    def test_propriedade_cpfs_validos(self) -> None:
        sorteio = random.Random(20261028)
        for _ in range(100):
            digitos = [sorteio.randrange(10) for _ in range(9)]
            for n in (9, 10):
                digitos.append(sum(digitos[i] * (n + 1 - i) for i in range(n)) * 10 % 11 % 10)
            cpf = "".join(map(str, digitos))
            self.assertTrue(mascara.cpf_valido(cpf))
            valor = (cpf[:3] + sorteio.choice(".,") + cpf[3:6] + sorteio.choice(".,") + cpf[6:9]
                     + sorteio.choice(mascara._TRACOS + "-") + sorteio.choice(("", "\n", " \r\n  ")) + cpf[9:])
            for antes, depois in (("<<", ">>"), ("Lista, ", "; fim"), ("OCR\n", "\n")):
                with self.subTest(cpf=cpf, contexto=antes):
                    self._limpo(antes + valor + depois, "cpf")

    def test_desempenho_das_barreiras(self) -> None:
        linha = ("Processo" + " " * 80 + "Lei" + " " * 60 + "matrícula" + " " * 70 + "Valor"
                 + " " * 50 + "R$ 1.234,56" + " " * 40 + "nº" + " " * 30 + ":\n")
        texto = linha * (5_000_000 // len(linha))
        for detector in (mascara.varrer_estrito, varrer):
            with self.subTest(detector=detector.__name__):
                inicio = time.perf_counter()
                achados = detector(texto)
                self.assertLess(time.perf_counter() - inicio, 3.0)
                self.assertEqual(achados, [])

    def test_desempenho_da_sombra(self) -> None:
        linha = "Art. 1º – Processo" + " " * 80 + "R$ 1.234,56 – nº 12-\n3\n"
        texto = linha * (5_000_000 // len(linha))
        inicio = time.perf_counter()
        saida, contagens = mascarar(texto)
        self.assertLess(time.perf_counter() - inicio, 3.0)
        self.assertEqual(saida, texto)
        self.assertEqual(sum(contagens.values()), 0)


class TestMascaraV9(unittest.TestCase):
    """RGs rotulados da auditoria, sempre com números sintéticos."""

    def _rg_inteiro(self, antes: str, numero: str, depois: str = "") -> None:
        texto = antes + numero + depois
        esperado = antes + "[RG omitido]" + depois
        self.assertEqual(mascara.varrer_estrito(texto), [
            {"tipo": "rg", "inicio": len(antes), "fim": len(antes) + len(numero)}])
        saida, contagens = mascarar(texto)
        self.assertEqual(saida, esperado)
        self.assertEqual(contagens, {tipo: int(tipo == "rg") for tipo in mascara.TIPOS})
        self.assertEqual(mascara.varrer_estrito(saida), [])
        self.assertFalse([o for o in varrer(saida) if o["forte"]])
        self.assertEqual(mascarar(saida), (saida, dict.fromkeys(mascara.TIPOS, 0)))

    def test_rg_com_grupos_partidos(self) -> None:
        for antes, numero, depois in (
            ("RG. ", "12.345 678-9", " IFP"),
            ("identidade nº ", "12.345. 678-9", " DETRAN/RJ"),
            ("identidade de n.º ", "12.345. 678-9", ","),
            ("RG ", "12,345, 678-X", ", residente"),
            ("RG ", "12345 6789", " IFP"),
            ("RG ", "12345678-9", " IFP"),
            ("RG ", "1,234  567x", " IFP"),
        ):
            with self.subTest(antes=antes, numero=numero):
                self._rg_inteiro(antes, numero, depois)

    def test_rg_com_marcadores_emissores_e_ruido(self) -> None:
        for antes, numero, depois in (
            ("identidade ", "1.234.567", " IFP, residente"),
            ("carteira de identidade n.º ", "12.34.56-7", " IFP,"),
            ("Identidade NO: ", "12345678", ""),
            ("C.I. nº ", "12345", ""),
            ("identidade ", "1234567", "ol lFP/Rj"),
            ("identidade SSP/MG nº ", "M-1234567", ""),
            ("identidade (RG) nº ", "12.345.678-9", ""),
            ("Identidade OAB/RJ nº ", "123456", ""),
            ("registro geral n.o ", "AB1234567890-X", ""),
            ("ci IFP nº ", "1234567", ""),
            ("r.g. DETRAN/RJ no: ", "12 345 678", ""),
            ("CI ", "N-1234567", ""),
            ("CI" + " " * 25, "AB-1234567", ""),
        ):
            with self.subTest(antes=antes, numero=numero):
                self._rg_inteiro(antes, numero, depois)

    def test_repara_cauda_de_mascara_anterior(self) -> None:
        for separador in (" ", ". ", ", ", ".  "):
            for dv in "9Xx":
                with self.subTest(separador=separador, dv=dv):
                    self._rg_inteiro("RG. [RG omitido]" + separador, "678-" + dv, " IFP")

    def test_negativos_e_limites(self) -> None:
        for texto in (
            "Identidade de gênero, Lei 13.709/2018", "identidade visual", "identidade cultural",
            "identidade visual sem número", "identidade cultural sem número",
            "RG: 13.709/2018", "RG 12.03.2024", "ID do processo 123", "ID: 12345 MF/RJ",
            "identidade 2024 do evento 12345", "CI " + " " * 40 + "1234567",
            "[RG omitido]    678-9", "[RG omitido] 6789-0", "[RG omitido] 678-90",
        ):
            with self.subTest(texto=texto):
                _sem_mudanca(self, texto)
                self.assertEqual(mascara.varrer_estrito(texto), [])

    def test_barreira_rg_independente_da_mascara(self) -> None:
        with mock.patch.object(mascara, "_RE_RG_ROTULADO", None), mock.patch.object(
                mascara, "_RE_RG_CAUDA", None), mock.patch.object(
                mascara, "_detectar", side_effect=AssertionError):
            self.assertEqual([o["tipo"] for o in mascara.varrer_estrito(
                "Identidade SSP/MG nº M-1234567; [RG omitido]. 678-9")], ["rg", "rg"])

    def test_rg_com_dv_nao_e_data(self) -> None:
        for numero in ("12.34.56-7", "12.03.24-X"):
            with self.subTest(numero=numero):
                self._rg_inteiro("carteira de identidade n.º ", numero, " IFP,")
        for texto in ("carteira de identidade n.º 12.03.2024", "RG 12.03.24"):
            with self.subTest(texto=texto):
                _sem_mudanca(self, texto)
                self.assertEqual(mascara.varrer_estrito(texto), [])

    def test_cpf_rotulado_com_espacos_internos(self) -> None:
        for antes, numero in (
            ("inscrito no CPF sob o nº ", "529,982,2 47-25"),
            ("CPF sob q nº ", "529.98 2,247-25"),
            ("C.P.F./MF nº ", "5 29.982.24 7-25"),
            ("CPF nº ", "529.982.247-2 5"),
            ("CPF" + " " * 15, "529.98 2,247-25"),
        ):
            with self.subTest(antes=antes, numero=numero):
                texto = antes + numero + ", residente."
                esperado = antes + "[CPF omitido], residente."
                self.assertEqual(mascara.varrer_estrito(texto), [
                    {"tipo": "cpf", "inicio": len(antes), "fim": len(antes) + len(numero)}])
                saida, contagens = mascarar(texto)
                self.assertEqual(saida, esperado)
                self.assertEqual(contagens, {tipo: int(tipo == "cpf") for tipo in mascara.TIPOS})
                self.assertEqual(mascara.varrer_estrito(saida), [])
                self.assertFalse([o for o in varrer(saida) if o["forte"]])
                self.assertEqual(mascarar(saida), (saida, dict.fromkeys(mascara.TIPOS, 0)))

    def test_cpf_com_espacos_exige_rotulo_proximo_e_dv(self) -> None:
        for texto in (
            "529,982,2 47-25", "529.98 2,247-25", "4406, 4407", "R$ 529.982,24",
            "Processo nº 529,982,2 47-25", "Processo 0001234-56.2024.8.19.0002",
            "CPF" + " " * 16 + "529,982,2 47-25", "CPF sob q nº 529.98 2,247-26",
            "CPF 5 2 9.98 2.247-25",
        ):
            with self.subTest(texto=texto):
                self.assertNotIn("cpf", {o["tipo"] for o in mascara.varrer_estrito(texto)})
                saida, contagens = mascarar(texto)
                self.assertEqual(contagens["cpf"], 0)
                # Números sem rótulo podem acionar regras de telefone; estas duas
                # proteções não devem sofrer nenhuma alteração, de qualquer tipo.
                if texto.startswith(("R$", "Processo")) or texto == "4406, 4407":
                    self.assertEqual(saida, texto)

    def test_barreira_cpf_com_espacos_independente(self) -> None:
        with mock.patch.object(mascara, "_RE_CPF_ESPACOS_ROTULADO", None), mock.patch.object(
                mascara, "_cpfs_rotulados", side_effect=AssertionError):
            self.assertEqual([o["tipo"] for o in mascara.varrer_estrito(
                "CPF sob q nº 529.98 2,247-25")], ["cpf"])


class TestMascaraV10(unittest.TestCase):
    """Formas sintéticas da revisão: emissores, quebras e CI administrativo."""

    _limpo = TestMascaraV8._limpo
    _rg_inteiro = TestMascaraV9._rg_inteiro

    def test_emissores_e_redacoes_de_identidade(self) -> None:
        for antes, numero in (
            ("identidade IFP/RJ nº ", "12.345.678-9"),
            ("identidade DETRAN-RJ nº ", "1.234.567"),
            ("identidade SSP-SP ", "1.234.567"),
            ("identidade DIC/RJ ", "12.345.678-9"),
            ("identidade número ", "1.234.567"),
            ("identidade numero ", "1.234.567"),
            ("identidade sob o nº ", "1234567"),
            ("identidade expedida pelo IFP sob o nº ", "12.345.678-9"),
            ("identidade expedido pela DIC/RJ nº ", "12.345.678-9"),
            ("C.I. IFP/RJ nº ", "12345"),
            ("identidade ABCDEFGH-SP nº ", "1234567"),
            ("CI" + " " * 40, "1234567"),
        ):
            with self.subTest(antes=antes, numero=numero):
                self._rg_inteiro(antes, numero, "; fim.")
                self.assertTrue(any(o["tipo"] == "rg" and o["forte"] for o in varrer(antes + numero)))

    def test_janela_livre_e_barreira_independente(self) -> None:
        for rotulo in ("identidade", "RG", "R.G.", "C.I."):
            for numero in ("12.345.678-9", "1234567", "123456789", "1,234,567X"):
                with self.subTest(rotulo=rotulo, numero=numero):
                    self._rg_inteiro(rotulo + " emitida por órgão não previsto: ", numero)
        texto = "identidade emitida por órgão não previsto: 12.345.678-9"
        direto = mock.Mock()
        direto.finditer.return_value = ()
        with mock.patch.multiple(mascara, _RE_RG_ROTULADO=None, _RE_RG_JANELA=None,
                                 _E_RG_ROTULADO=direto,
                                 _detectar=mock.Mock(side_effect=AssertionError),
                                 _Sombra=mock.Mock(side_effect=AssertionError)):
            self.assertEqual(mascara.varrer_estrito(texto), [
                {"tipo": "rg", "inicio": texto.index("12."), "fim": len(texto)}])

    def test_quebras_de_cpf_e_rg_preservam_offsets(self) -> None:
        self.assertTrue(set("\u2043\u02d7\u2796\ufe31\ufe32").issubset(mascara._TRACOS))
        for quebra in ("\n", "\r\n", " \r\n\t "):
            for antes, numero, tipo in (
                ("CPF ", "529.982." + quebra + "247-25", "cpf"),
                ("CPF ", "529,982," + quebra + "247-25", "cpf"),
                ("CPF ", "529/982/" + quebra + "247-25", "cpf"),
                ("CPF ", "529 982 " + quebra + "247 25", "cpf"),
                ("", "529.982." + quebra + "247-25", "cpf"),
                ("RG ", "12.345." + quebra + "678-9", "rg"),
                ("RG ", "12,345," + quebra + "678-9", "rg"),
                ("RG ", "12/345/" + quebra + "678-9", "rg"),
                ("RG ", "12 345 " + quebra + "678-9", "rg"),
            ):
                with self.subTest(quebra=quebra, tipo=tipo, numero=numero):
                    prefixo = "Art. 1º; " + antes
                    texto = prefixo + numero + "; fim."
                    self.assertEqual(self._limpo(texto, tipo), prefixo + mascara.SUBSTITUICOES[tipo] + "; fim.")
                    for detector in (varrer, mascara.varrer_estrito):
                        achados = [o for o in detector(texto) if o["tipo"] == tipo]
                        self.assertTrue(achados)
                        self.assertTrue(all(texto[o["inicio"]:o["fim"]] == numero for o in achados))

    def test_estrita_com_quebras_nao_depende_da_sombra(self) -> None:
        texto = "CPF 529.982.\n247-25; RG 12.345.\r\n678-9"
        with mock.patch.multiple(mascara, _RE_RG_ROTULADO=None, _RE_RG_JANELA=None, _RE_CPF=None,
                                 _detectar=mock.Mock(side_effect=AssertionError),
                                 _Sombra=mock.Mock(side_effect=AssertionError)):
            achados = mascara.varrer_estrito(texto)
        self.assertEqual([(o["tipo"], texto[o["inicio"]:o["fim"]]) for o in achados], [
            ("cpf", "529.982.\n247-25"), ("rg", "12.345.\r\n678-9")])

    def test_negativos_listas_ci_e_limites_da_janela(self) -> None:
        casos = (
            "Identidade de gênero, Lei 13.709/2018", "identidade visual/cultural",
            "RG: 13.709/2018", "RG 12.03.2024", "ID do processo 123", "ID: 12345 MF/RJ",
            "4406, 4407", "4406,\n4407", "4406,\r\n 4407", "4406,\n4407,\n4408",
            "4406,\n4407; Comunicação Interna: CI nº 1234 \n5678",
            "CI nº 123/2024", "C.I. nº 123456/2024", "CI nº 1234567/2024",
            "Ofício: CI nº 123456", "memorando referente à C.I. nº 123456",
            "Comunicação Interna: CI nº 123456", "OFÍCIO anterior, CI nº 123456",
            "Memorando\nC.I. nº 123456",
            "identidade" + " " * 41 + "1234567", "identidade emitida\npelo órgão 1234567",
        )
        for texto in casos:
            for paginas in ((None, {1}) if texto.startswith("4406,") else (None,)):
                with self.subTest(texto=texto, paginas=paginas):
                    self.assertEqual(mascarar(texto, ocr_paginas=paginas), (texto, dict.fromkeys(mascara.TIPOS, 0)))
                    self.assertEqual(mascara.varrer_estrito(texto), [])
                    self.assertFalse([o for o in varrer(texto, ocr_paginas=paginas) if o["forte"]])
        self._rg_inteiro("C.I. nº ", "12345")
        self._rg_inteiro("CI nº ", "123456")
        self._rg_inteiro("Ofício" + " " * 41 + "C.I. nº ", "12345")

    def test_desempenho_da_janela_rg_sem_numero(self) -> None:
        linha = "identidade emitida por órgão " + " " * 80 + "sem número\n"
        texto = linha * (5_000_000 // len(linha))
        for detector in (mascarar, varrer, mascara.varrer_estrito):
            with self.subTest(detector=detector.__name__):
                inicio = time.perf_counter()
                resultado = detector(texto)
                self.assertLess(time.perf_counter() - inicio, 3.0)
                self.assertEqual(resultado, (texto, dict.fromkeys(mascara.TIPOS, 0)) if detector is mascarar else [])


class TestBarreiraListas(unittest.TestCase):
    def test_listas_com_virgula_e_espacos_nao_sao_cpf_na_barreira(self) -> None:
        for texto in ("arte; 3354, 3355, 3356, 3357, 3358, 3359, 330, 3361, 3362",
                      "pelos Decretos nos\n8.464/2001, 8.619/2001,                    359 a 392"):
            with self.subTest(texto=texto):
                self.assertFalse([o for o in varrer(texto) if o["forte"]])
        self.assertTrue([o for o in varrer("CPF 529,982,247,25") if o["forte"]])

if __name__ == "__main__":
    unittest.main()
