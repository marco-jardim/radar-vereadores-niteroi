"""Seção "[ Arquivos ]" das páginas de detalhe do SISCAM (coletor/arquivos_siscam.py).

As páginas com e sem arquivos são reais, salvas em tests/fixtures/siscam/; só a de layout
alterado (detalhe_arquivos_layout_alterado.html) é sintética.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from coletor import siscam
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
LAYOUT_ALTERADO = "detalhe_arquivos_layout_alterado.html"


class TestExtrairArquivos(unittest.TestCase):
    def test_fixture_de_layout_alterado_usa_crlf(self):
        conteudo = (Path(__file__).parent / "fixtures" / "siscam" / LAYOUT_ALTERADO).read_bytes()
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
        pagina = ler_fixture("siscam", "detalhe_pl_275545.html")
        sem_secao = pagina.replace('id="trArquivos"', 'id="outra"').replace("[ Arquivos ]", "[ Outros ]")
        self.assertEqual(extrair_arquivos(sem_secao), [])
        self.assertEqual(extrair_arquivos(""), [])

    def test_pl_real_sem_secao_de_arquivos(self):
        # PL 175/2026: o SISCAM omite a seção inteira (sem trArquivos nem legenda)
        pagina = ler_fixture("siscam", "detalhe_pl_293738_sem_arquivos.html")
        self.assertNotIn('id="trArquivos"', pagina)
        self.assertEqual(extrair_arquivos(pagina), [])
        d = siscam.parse_detalhe(pagina)
        self.assertEqual(d["arquivos"], [])
        self.assertEqual((d["data"], d["situacao"], d["protocolo"], d["data_protocolo"]),
                         ("2026-04-29", "ENCAMINHADO ÀS COMISSÕES", "3105/2026", "2026-04-29"))
        self.assertEqual(d["autoria"], [{"nome": "Mesa Diretora 2025/2026", "origem": "Mesa", "papel": "Autor"}])
        self.assertEqual([t["seq"] for t in d["tramitacoes"]][:2], [1, 2])

    def test_resolucao_real_com_nenhum_registro_encontrado(self):
        # Resolução 20/2025: grade arquivos_gvListagem com a linha grid-empty-data
        pagina = ler_fixture("siscam", "detalhe_resolucao_288836_sem_arquivos.html")
        self.assertIn("Nenhum Registro Encontrado!", pagina)
        self.assertEqual(extrair_arquivos(pagina), [])
        d = siscam.parse_detalhe(pagina)
        self.assertEqual(d["arquivos"], [])
        self.assertEqual((d["data"], d["assunto"], d["situacao"], d["processo"], d["protocolo"]),
                         ("2025-11-25", "LOA", "PUBLICADO", "773/2025", "12991/2025"))
        self.assertTrue(d["autoria"])
        self.assertEqual([t["seq"] for t in d["tramitacoes"]][:8], list(range(1, 9)))

    def test_layout_alterado(self):
        with self.assertRaisesRegex(ValueError, "^layout alterado: tabela de arquivos ausente$"):
            extrair_arquivos(ler_fixture("siscam", LAYOUT_ALTERADO))

    def test_legenda_sem_linha_tr_arquivos_e_layout_alterado(self):
        pagina = ler_fixture("siscam", "detalhe_pl_275545.html").replace('id="trArquivos"', 'id="trOutros"')
        with self.assertRaisesRegex(ValueError, "^layout alterado: legenda de arquivos sem a linha trArquivos$"):
            extrair_arquivos(pagina)
        with self.assertRaises(ValueError):
            siscam.parse_detalhe(pagina)

    def test_nenhum_registro_de_outra_secao_nao_oculta_layout_alterado(self):
        pagina = ler_fixture("siscam", LAYOUT_ALTERADO)
        with self.assertRaises(ValueError):
            extrair_arquivos(pagina + "<tr><td>Nenhum Registro</td></tr>")


if __name__ == "__main__":
    unittest.main()
