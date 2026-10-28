"""Testes da máscara LGPD (coletor/mascara.py).

Todos os números e endereços são sintéticos: os CPFs usados são exemplos de
dígitos verificadores válidos, sem relação com pessoas reais.

Uso: python -m unittest tests.test_mascara
"""
from __future__ import annotations

import json
import tempfile
import time
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
        _sem_mudanca(self, "RG emitido pelo órgão estadual competente 12.345.678-9")
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


if __name__ == "__main__":
    unittest.main()
