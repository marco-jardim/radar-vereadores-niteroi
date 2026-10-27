"""Templates neutros do resumo; a mesma conferência também percorre todas as fichas reais."""
from __future__ import annotations

import copy
import html
import re
import unittest

from coletor.site import resumo as R
from tests.test_mandatos import modelo_tabela
from tests.test_modelo_sessoes import LEG


def texto_visivel(conteudo: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", conteudo))


def conferir_resumo(caso: unittest.TestCase, modelo: dict, pessoa: dict, conteudo: str) -> None:
    """Confere neutralidade e números contra o modelo, não contra outro texto do template."""
    texto = texto_visivel(conteudo)
    for palavra in R.PALAVRAS_PROIBIDAS:
        sufixo = r"\w*" if palavra == "polêmic" else ""
        caso.assertIsNone(re.search(r"(?<!\w)" + re.escape(palavra) + sufixo + r"(?!\w)",
                                   texto, flags=re.IGNORECASE), palavra)
    registros = ((modelo.get("sessoes") or {}).get("por_pessoa") or {}).get(pessoa["slug"], {})
    mandatos = pessoa.get("mandatos") or {}
    esperadas = sorted(set(registros) | set(mandatos), reverse=True)
    paragrafos = re.findall(r'<p data-resumo-leg="([^"]+)">(.*?)</p>', conteudo, flags=re.S)
    caso.assertEqual([leg for leg, _ in paragrafos], esperadas)

    def inteiro(valor: str) -> int:
        return int(valor.replace(".", ""))

    for leg, paragrafo in paragrafos:
        p = (registros.get(leg) or {}).get("presenca") or {}
        texto = texto_visivel(paragrafo)
        if p.get("denominador", 0) >= 10 and p.get("pct") is not None:
            valores = re.search(r"Presença efetiva: ([\d.,]+)% \(([\d.]+) faltas não abonadas", texto)
            caso.assertIsNotNone(valores)
            caso.assertEqual(float(valores[1].replace(".", "").replace(",", ".")), p["pct"])
            caso.assertEqual(inteiro(valores[2]), p.get("A", 0))
            for c, rotulo in (("J", "ausências justificadas"), ("O", "em outro cargo"), ("L", "de licença")):
                valor = re.search(r"([\d.]+) " + rotulo, texto)
                if p.get(c):
                    caso.assertIsNotNone(valor)
                    caso.assertEqual(inteiro(valor[1]), p[c])
                else:
                    caso.assertIsNone(valor)
        else:
            caso.assertIn("Presença: base inferior a 10 sessões, sem percentual.", texto)
            caso.assertNotIn("Presença efetiva:", texto)
        projetos = mandatos.get(leg, {}).get("projetos_autor") or []
        if projetos:
            valores = re.search(r"Projetos de lei como autor principal: ([\d.]+); vir(?:ou|aram) lei: ([\d.]+)", texto)
            caso.assertIsNotNone(valores)
            caso.assertEqual(inteiro(valores[1]), len(projetos))
            caso.assertEqual(inteiro(valores[2]), sum(p["desfecho"] == "virou_lei" for p in projetos))
        else:
            caso.assertIn("Projetos de lei como autor principal: sem registro.", texto)


class TestResumo(unittest.TestCase):
    def test_template_completo_fontes_ordem_e_formulas(self):
        modelo = modelo_tabela()
        pessoa = modelo["pessoas"]["ana"]
        pessoa["mandatos"][LEG]["projetos_autor"] = ([{"desfecho": "virou_lei"}] * 6
                                                     + [{"desfecho": "em_tramitacao"}] * 35)
        # Uma lei de coautoria não entra na contagem de autoria principal.
        pessoa["mandatos"][LEG]["projetos_coautor"] = [{"desfecho": "virou_lei"}]
        registro = modelo["sessoes"]["por_pessoa"]["ana"][LEG]
        registro["presenca"] = {"listadas": 197, "denominador": 151, "pct": 61,
                                "A": 59, "J": 30, "O": 3, "L": 13}
        registro.update(divididas=7, divergencias=[{}, {}])
        modelo["sessoes"]["exercicio"][LEG]["total"] = 250
        atividade = modelo["atividade"]["ana"]
        atividade["por_leg"][LEG]["tipos"] = {"requerimento": 8, "indicacao": 9, "mocao": 2}
        atividade["documentos"] = [{"tipo": "indicacao", "legislatura": LEG, "bairro": b}
                                   for b in ["Centro"] * 3 + ["São Francisco"] * 2 + ["Icaraí"] * 2
                                   + ["Barreto", None]]
        antes = copy.deepcopy(modelo)
        conteudo = R.secao_resumo(modelo, pessoa)
        conferir_resumo(self, modelo, pessoa, conteudo)
        texto = texto_visivel(conteudo)
        frases = [
            "Exerceu o mandato em 197 de 250 sessões deliberativas com lista de presença (cerca de 9,4 meses).",
            "Mesa Diretora: Presidente (2025–2026)",
            "Em outro cargo: Secretária (a partir de 01/03/2025; até 01/04/2025)",
            "Licenças registradas: 1",
            "Presença efetiva: 61% (59 faltas não abonadas; 30 ausências justificadas, 3 em outro cargo e 13 de licença, fora da base).",
            "Projetos de lei como autor principal: 41; viraram lei: 6.",
            "Requerimentos: 8. Indicações: 9. Moções: 2.",
            "Bairros mais citados nas indicações: Centro (3), Icaraí (2), São Francisco (2).",
            "Votou em 80% das votações nominais possíveis (8 de 10); presidiu a sessão em 2 delas.",
            "Votou diferente da maioria em 2 de 7 votações divididas com sentido conhecido.",
        ]
        posicoes = [texto.index(frase) for frase in frases]
        self.assertEqual(posicoes, sorted(posicoes))
        for fonte in ("mesa", "cargo", "licenca"):
            self.assertIn(f'href="https://example.org/{fonte}"', conteudo)
        self.assertIn('aria-labelledby="t-resumo-numeros"', conteudo)
        self.assertIn('href="../metodologia.html#resumo"', conteudo)
        self.assertEqual(conteudo, R.secao_resumo(modelo, pessoa))
        self.assertEqual(modelo, antes)

    def test_sem_sessoes_sem_producao_e_sem_cargos(self):
        modelo = modelo_tabela()
        pessoa = modelo["pessoas"]["bruno"]
        modelo["sessoes"] = None
        conteudo = R.secao_resumo(modelo, pessoa, "/radar/")
        conferir_resumo(self, modelo, pessoa, conteudo)
        for frase in ("Sem registro de sessões em exercício nesta legislatura.",
                      "Requerimentos, indicações e moções: sem registro.",
                      "Votações nominais: base inferior a 10."):
            self.assertIn(frase, conteudo)
        for ausente in ("Mesa Diretora:", "Em outro cargo:", "Licenças registradas:",
                        "Bairros mais citados", "Votou diferente da maioria", "%"):
            self.assertNotIn(ausente, conteudo)
        self.assertIn('href="/radar/metodologia.html#resumo"', conteudo)

    def test_bases_nove_e_dez_e_categorias_zeradas(self):
        modelo = modelo_tabela()
        pessoa = modelo["pessoas"]["ana"]
        registro = modelo["sessoes"]["por_pessoa"]["ana"][LEG]
        registro["presenca"].update(A=0, J=0, O=0, L=0)
        registro["participacao"].update(possiveis=12, presidindo=3, votou=8)
        registro["presenca"]["denominador"] = 9
        curto = R.secao_resumo(modelo, pessoa)
        self.assertNotIn("%", curto)
        self.assertIn("Votações nominais: base inferior a 10; presidiu a sessão em 3 delas.", curto)
        registro["presenca"]["denominador"] = 10
        registro["participacao"]["possiveis"] = 13
        completo = R.secao_resumo(modelo, pessoa)
        self.assertIn("Presença efetiva: 80% (0 faltas não abonadas).", completo)
        self.assertIn("Votou em 80% das votações nominais possíveis (8 de 10)", completo)
        self.assertNotIn("fora da base", completo)
        self.assertNotIn("Bairros mais citados", completo)  # Contagem de indicações sem bairros disponíveis.

    def test_legislatura_com_sessoes_sem_mandato_e_ordem_por_data(self):
        modelo = modelo_tabela()
        pessoa = modelo["pessoas"]["ana"]
        leg_anterior = {"id": "2021-2024", "inicio": "2021-01-01"}
        modelo["legislaturas"].append(leg_anterior)  # Entrada fora da ordem cronológica.
        modelo["sessoes"]["por_pessoa"]["ana"][leg_anterior["id"]] = {
            "presenca": {"listadas": 1, "denominador": 1, "pct": None}}
        conteudo = R.secao_resumo(modelo, pessoa)
        conferir_resumo(self, modelo, pessoa, conteudo)
        self.assertEqual(conteudo.count("<h3>Legislatura "), 2)
        self.assertLess(conteudo.index(LEG), conteudo.index(leg_anterior["id"]))

    def test_cargos_sem_frequencia_datas_ausentes_e_escape(self):
        modelo = modelo_tabela()
        pessoa = modelo["pessoas"]["ana"]
        pessoa["mandatos"][LEG]["eleito"] = False
        modelo["sessoes"] = None
        cargo = modelo["cfg"]["afastamentos"][0]
        cargo.pop("inicio")
        cargo.pop("fim")
        cargo["cargo"] = 'Secretária <municipal> & assessora'
        conteudo = R.secao_resumo(modelo, pessoa)
        self.assertIn("Secretária &lt;municipal&gt; &amp; assessora (datas não registradas)", conteudo)
        self.assertNotIn("<municipal>", conteudo)
        self.assertIn("Mesa Diretora:", conteudo)
        self.assertIn("Licenças registradas:", conteudo)

    def test_formatacao_pt_br(self):
        for valor, esperado in ((0, "0"), (10, "10"), (1234, "1.234"), (1234.56, "1.234,6")):
            self.assertEqual(R._numero(valor), esperado)
