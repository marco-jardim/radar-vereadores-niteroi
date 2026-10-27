"""Testes da limpeza de cabeçalhos, rodapés, ruído e clichês (coletor/limpeza.py).

Uso: python -m unittest tests.test_limpeza
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from coletor import arquivos, limpeza, mascara, trechos
from coletor.limpeza import ProtecaoLimpeza, gerar_cliches, limpar, normalizar_linha

RAIZ = Path(__file__).resolve().parent.parent
ORDINAIS = ["primeira", "segunda", "terceira", "quarta"]
PARAGRAFO = ("A Câmara Municipal de Niterói aprovou em primeira discussão o projeto que institui "
             "o programa municipal de hortas comunitárias nas escolas da rede pública.")


def _paginas(com_cabecalho: list[bool], extra: dict[int, str] | None = None) -> str:
    paginas = []
    for i, cabecalho in enumerate(com_cabecalho):
        linhas = ["CÂMARA MUNICIPAL DE NITERÓI"] if cabecalho else []
        linhas += [f"Trecho {ORDINAIS[i]} do corpo", f"Mais conteúdo {ORDINAIS[i]} aqui"]
        if extra and i in extra:
            linhas.append(extra[i])
        linhas.append("Rua da Conceição, 100 - Centro")
        paginas.append("\n".join(linhas))
    return "\f".join(paginas)


def _zeros() -> dict[str, int]:
    return {regra: 0 for regra in limpeza.REGRAS}


class TestNormalizarLinha(unittest.TestCase):
    def test_forma(self) -> None:
        self.assertEqual(normalizar_linha("  — Página 12 de 30. "), "pagina # de #")
        self.assertEqual(normalizar_linha("CÂMARA   Municipal de NITERÓI"), "camara municipal de niteroi")
        self.assertEqual(normalizar_linha("Rua da Conceição, 100 - Centro"), "rua da conceicao, # - centro")
        self.assertEqual(normalizar_linha("-----"), "")


class TestCabecalhoRodape(unittest.TestCase):
    def test_repetido_em_3_de_4_paginas_sai(self) -> None:
        texto = _paginas([True, True, True, False], extra={1: "Visto do relator"})
        limpo, contagens = limpar(texto)
        self.assertNotIn("CÂMARA MUNICIPAL", limpo)
        self.assertNotIn("Rua da Conceição", limpo)
        self.assertIn("Visto do relator", limpo)  # só numa página: fica
        self.assertEqual(contagens["cabecalho_rodape"], 7)
        self.assertEqual(contagens["linhas_removidas"], 7)
        self.assertEqual(trechos.paginas(limpo)[0], "Trecho primeira do corpo\nMais conteúdo primeira aqui")
        self.assertEqual(len(trechos.paginas(limpo)), 4)

    def test_documento_de_uma_pagina_nao_corta_repeticao(self) -> None:
        texto = "CÂMARA MUNICIPAL DE NITERÓI\nCorpo único\nRua da Conceição, 100 - Centro"
        limpo, contagens = limpar(texto)
        self.assertEqual(limpo, texto)
        self.assertEqual(contagens, _zeros())

    def test_linha_repetida_no_meio_da_pagina_fica(self) -> None:
        def pagina(sufixo: str, fim: str) -> str:
            corpo = [f"Linha de conteúdo {ORDINAIS[i % 4]} número {ORDINAIS[(i // 4) % 4]} {sufixo}"
                     for i in range(12)]
            corpo[5] = "Linha comum do meio"  # repetida, mas fora das 4 linhas das bordas
            return "\n".join(["Cabeçalho comum", *corpo, fim])

        limpo, contagens = limpar("\f".join([pagina("alfa", "Rodapé"), pagina("beta", "Outro fim")]))
        self.assertNotIn("Cabeçalho comum", limpo)
        self.assertEqual(limpo.count("Linha comum do meio"), 2)
        self.assertEqual(contagens["cabecalho_rodape"], 2)


class TestRuido(unittest.TestCase):
    def test_numeracao_separadores_e_ocr(self) -> None:
        linhas = ["Corpo do texto com conteúdo", "Página 1 de 3", "Pág. 2", "- 2 -", "2/5", "17",
                  "------", "____", "****", "=====", "~~ ;; ^^ ,,", "a.,;:!?/|", "Art. 1º", "§ 2º",
                  "Considerando"]
        limpo, contagens = limpar("\n".join(linhas))
        self.assertEqual(limpo, "Corpo do texto com conteúdo\nArt. 1º\n§ 2º\nConsiderando")
        esperado = _zeros()
        esperado.update(numeracao=5, ruido_ocr=6, linhas_removidas=11)
        self.assertEqual(contagens, esperado)


class TestCliches(unittest.TestCase):
    def test_cliche_removido_e_protegidos_ficam(self) -> None:
        linhas = ["Art. 1º Fica instituído o programa.", "o programa municipal de hortas",
                  "MILTON CARLOS DA SILVA LOPES", "Lei nº 3.456/2020", "MILTON",
                  "Documento assinado eletronicamente.", "Sala das Sessões", "JUSTIFICATIVA"]
        cliches = {normalizar_linha(l) for l in linhas}
        protecao = ProtecaoLimpeza(["MILTON CARLOS DA SILVA LOPES", "MILTON"])
        limpo, contagens = limpar("\n".join(linhas), cliches, protecao,
                                  ementa="Institui o programa municipal de hortas comunitárias")
        self.assertEqual(limpo.split("\n"), [linhas[0], linhas[1], linhas[2], linhas[3],
                                             "Sala das Sessões", "JUSTIFICATIVA"])
        self.assertEqual(contagens["cliche"], 2)

    def test_protecao_da_configuracao(self) -> None:
        protecao = ProtecaoLimpeza.de_config(RAIZ)
        self.assertTrue(protecao.tem_nome("Gabinete do vereador MILTON CARLOS DA SILVA LOPES"))
        self.assertTrue(protecao.tem_nome("Fael Faustino"))  # apelido
        self.assertFalse(protecao.tem_nome("Milton"))
        self.assertTrue(all(len(nome) >= 2 for nome in protecao.nomes))
        self.assertTrue(protecao.protegida(
            "uma linha de conteúdo com doze palavras ou mais para ser protegida sempre"))

    def test_gerar_cliches_deterministico(self) -> None:
        docs = [(f"doc{i}", f"Documento assinado eletronicamente\nConteúdo exclusivo {ORDINAIS[i % 4]}\n"
                            "Art. 5º Revogam-se as disposições em contrário.")
                for i in range(30)]
        a = gerar_cliches(docs)
        b = gerar_cliches(list(reversed(docs)))
        self.assertEqual(list(a.items()), list(b.items()))
        self.assertEqual(a["documento assinado eletronicamente"], 30)
        self.assertNotIn(normalizar_linha("Art. 5º Revogam-se as disposições em contrário."), a)
        self.assertEqual(list(a), sorted(a))
        with tempfile.TemporaryDirectory() as nome:
            um, dois = Path(nome) / "a.json", Path(nome) / "b.json"
            arquivos.salvar_mapa(um, a)
            arquivos.salvar_mapa(dois, b)
            self.assertEqual(um.read_bytes(), dois.read_bytes())
            self.assertEqual(json.loads(um.read_text(encoding="utf-8")), a)

    def _corpus(self, n: int, contagens: dict[str, int]) -> dict[str, int]:
        docs = []
        for i in range(n):
            linhas = ["Texto comum de todos"]
            linhas += [linha for linha, k in contagens.items() if i < k]
            docs.append((f"d{i}", "\n".join(linhas)))
        return gerar_cliches(docs)

    def test_limites(self) -> None:
        r = self._corpus(1000, {"Linha alfa repetida": 20, "Linha beta repetida": 19})
        self.assertIn("linha alfa repetida", r)      # 20 documentos
        self.assertNotIn("linha beta repetida", r)   # 19 documentos, 1,9%
        r = self._corpus(500, {"Linha gama repetida": 10, "Linha delta repetida": 9})
        self.assertIn("linha gama repetida", r)      # exatamente 2%
        self.assertNotIn("linha delta repetida", r)
        r = self._corpus(100, {"Linha epsilon repetida": 4, "Linha zeta repetida": 5})
        self.assertNotIn("linha epsilon repetida", r)  # 4% mas abaixo de 5 documentos
        self.assertIn("linha zeta repetida", r)
        self.assertEqual(r["texto comum de todos"], 100)

    def test_documento_repetido_conta_uma_vez(self) -> None:
        docs = [("a", "Linha única")] * 10 + [(f"b{i}", "Outra coisa") for i in range(4)]
        self.assertEqual(gerar_cliches(docs, min_docs=1), {})

    def test_cli(self) -> None:
        with tempfile.TemporaryDirectory() as nome:
            pasta = Path(nome) / "cache"
            pasta.mkdir()
            for i in range(25):
                (pasta / f"{i}.txt").write_text(f"Documento assinado eletronicamente\nTexto {ORDINAIS[i % 4]}",
                                                encoding="utf-8")
            saida = Path(nome) / "textos" / "cliches.json"
            args = ["--cache", str(pasta), "--saida", str(saida)]
            self.assertEqual(limpeza.main(["--gerar-cliches", *args]), 0)
            dados = json.loads(saida.read_text(encoding="utf-8"))
            self.assertEqual(dados["documento assinado eletronicamente"], 25)
            self.assertEqual(limpeza.main(["--gerar-cliches", *args]), 2)  # não sobrescreve
            self.assertEqual(limpeza.main(["--recalcular-cliches", *args]), 0)
            self.assertEqual(limpeza.carregar_cliches(saida), dados)


class TestIdempotenciaIntegracao(unittest.TestCase):
    def test_idempotente(self) -> None:
        texto = _paginas([True, True, True, True]) + "\nPágina 4 de 4\n-----"
        uma, contagens = limpar(texto)
        self.assertGreater(contagens["linhas_removidas"], 0)
        duas, de_novo = limpar(uma)
        self.assertEqual(duas, uma)
        self.assertEqual(de_novo, _zeros())

    def test_limpar_mascarar_dividir(self) -> None:
        paginas = [f"CÂMARA MUNICIPAL DE NITERÓI\nRequerimento {o}: contato (21) 98888-7777\n{PARAGRAFO}\n- {i + 1} -"
                   for i, o in enumerate(ORDINAIS[:3])]
        limpo, contagens = limpar("\f".join(paginas))
        self.assertEqual((contagens["cabecalho_rodape"], contagens["numeracao"]), (3, 3))
        mascarado, quantos = mascara.mascarar(limpo)
        self.assertEqual(quantos["telefone"], 3)
        self.assertNotIn("CÂMARA MUNICIPAL DE NITERÓI\n", mascarado)
        self.assertEqual(mascara.varrer(mascarado), [])
        lista = trechos.dividir(mascarado, "doc:1", "siscam:2")
        self.assertTrue(lista)
        self.assertTrue(all(t["vetorizavel"] for t in lista))
        for t in lista:
            self.assertEqual(trechos.texto_do_trecho(mascarado, t), mascarado[t["inicio"]:t["fim"]])


if __name__ == "__main__":
    unittest.main()
