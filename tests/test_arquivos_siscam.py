"""Arquivos de páginas reais do SISCAM e proteções contra perda de metadados."""
from __future__ import annotations

import unittest
from pathlib import Path

from coletor.arquivos_siscam import extrair_arquivos
from tests.apoio import ler_fixture


def arquivo(id_: int, icone: str, data: str | None, descricao: str = "", versao: str = "Anexos") -> dict:
    return {"id": id_, "descricao": descricao, "versao": versao, "data": data, "icone": icone}


ESPERADOS = {
    "pl_127858": [arquivo(232123, "doc", "2021-04-21")],
    "substitutivo_266596": [
        arquivo(376337, "doc", "2024-03-14"),
        arquivo(381166, "pdf", "2024-06-27",
                "RECEBIDO OF/GAB/N° 396/2024, COM AS RAZÕES DO VETO TOTAL", "Arquivo em PDF"),
    ],
    "pl_275545": [arquivo(385956, "doc", "2025-02-10")],
    "pdl_290379": [arquivo(404139, "doc", "2025-12-10"), arquivo(404140, "pdf", "2025-12-10")],
    "resolucao_289947": [arquivo(403683, "pdf", "2025-12-04")],
    "requerimento_290504": [arquivo(404266, "pdf", "2025-12-11")],
    "requerimento_290505": [arquivo(404267, "pdf", "2025-12-11")],
}


class TestExtrairArquivos(unittest.TestCase):
    def test_fixtures_sinteticas_preservam_crlf(self):
        pasta = Path(__file__).parent / "fixtures" / "siscam"
        for nome in ("nenhum_registro", "layout_alterado"):
            with self.subTest(nome=nome):
                conteudo = (pasta / f"detalhe_arquivos_{nome}.html").read_bytes()
                self.assertIn(b"\r\n", conteudo)
                self.assertNotIn(b"\n", conteudo.replace(b"\r\n", b""))

    def test_paginas_reais(self):
        for nome, esperado in ESPERADOS.items():
            with self.subTest(nome=nome):
                self.assertEqual(extrair_arquivos(ler_fixture("siscam", f"detalhe_{nome}.html")), esperado)

    def test_normalizacao_data_invalida_e_icone_ausente(self):
        pagina = '''<tr id="trArquivos"><td><table id="arquivos_gvListagem">
            <tr class="outra grid-row-novo"><td><a href="Download.aspx?id=1">Visualizar</a></td>
            <td> &nbsp; A\u00a0 &amp; <b>B</b>\n </td><td> Arquivo\t em PDF </td><td>31/2/2024</td></tr>
            <tr class="grid-row-item"><td><a href="Download.aspx?id=2">Visualizar</a></td>
            <td>&nbsp;</td><td></td><td>sem data</td></tr></table></td></tr>'''
        self.assertEqual(extrair_arquivos(pagina), [arquivo(1, "", None, "A & B", "Arquivo em PDF"),
                                                  arquivo(2, "", None, versao="")])

    def test_ignora_links_sem_id_e_deduplica_preservando_ordem(self):
        pagina = ler_fixture("siscam", "detalhe_pdl_290379.html")
        self.assertEqual(extrair_arquivos(pagina.replace("id=404139", "outro=404139")), ESPERADOS["pdl_290379"][1:])
        self.assertEqual(extrair_arquivos(pagina.replace("id=404140", "id=404139")), ESPERADOS["pdl_290379"][:1])

    def test_sem_secao_nao_le_grade_de_outro_local(self):
        pagina = ler_fixture("siscam", "detalhe_pl_275545.html").replace('id="trArquivos"', 'id="outra"')
        self.assertEqual(extrair_arquivos(pagina), [])
        self.assertEqual(extrair_arquivos(""), [])

    def test_nenhum_registro(self):
        self.assertEqual(extrair_arquivos(ler_fixture("siscam", "detalhe_arquivos_nenhum_registro.html")), [])

    def test_layout_alterado(self):
        with self.assertRaisesRegex(ValueError, "^layout alterado: tabela de arquivos ausente$"):
            extrair_arquivos(ler_fixture("siscam", "detalhe_arquivos_layout_alterado.html"))

    def test_nenhum_registro_de_outra_secao_nao_oculta_layout_alterado(self):
        pagina = ler_fixture("siscam", "detalhe_arquivos_layout_alterado.html")
        with self.assertRaises(ValueError):
            extrair_arquivos(pagina + "<tr><td>Nenhum Registro</td></tr>")


if __name__ == "__main__":
    unittest.main()
