"""Testes da limpeza de cabeçalhos, rodapés, ruído e clichês (coletor/limpeza.py).

Uso: python -m unittest tests.test_limpeza
"""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from coletor import arquivos, limpeza, mascara, trechos
from coletor.limpeza import ProtecaoLimpeza, gerar_cliches, limpar, normalizar_linha

RAIZ = Path(__file__).resolve().parent.parent
ORDINAIS = ["primeira", "segunda", "terceira", "quarta"]
GREGAS = ["alfa", "beta", "gama", "delta", "epsilon", "zeta", "eta", "teta", "iota", "kapa"]
PARAGRAFO = ("A Câmara Municipal de Niterói aprovou em primeira discussão o projeto que institui "
             "o programa municipal de hortas comunitárias nas escolas da rede pública.")
ENDERECO_CAMARA = "Av. Ernani do Amaral Peixoto, 625 - Centro"


def _paginas(com_cabecalho: list[bool], extra: dict[int, str] | None = None) -> str:
    paginas = []
    for i, cabecalho in enumerate(com_cabecalho):
        linhas = ["CÂMARA MUNICIPAL DE NITERÓI"] if cabecalho else []
        linhas += [f"Trecho {ORDINAIS[i]} do corpo", f"Mais conteúdo {ORDINAIS[i]} aqui"]
        if extra and i in extra:
            linhas.append(extra[i])
        linhas.append(ENDERECO_CAMARA)
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


# ------------------------------------------------------------------- cabeçalho e rodapé
class TestCabecalhoRodape(unittest.TestCase):
    def test_repetido_em_3_de_4_paginas_sai(self) -> None:
        texto = _paginas([True, True, True, False], extra={1: "Visto do relator"})
        limpo, contagens = limpar(texto)
        self.assertNotIn("CÂMARA MUNICIPAL", limpo)
        self.assertNotIn("Amaral Peixoto", limpo)
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

    def test_chave_que_aparece_no_miolo_nao_e_cabecalho(self) -> None:
        miolo = [f"Conteúdo {g}" for g in GREGAS[:8]]
        miolo.insert(4, "Resumo")  # também no miolo da primeira página
        pagina1 = "\n".join(["Resumo", *miolo, "Fim um"])
        pagina2 = "\n".join(["Resumo", "Outro texto", "Fim dois"])
        limpo, contagens = limpar(pagina1 + "\f" + pagina2)
        self.assertEqual(limpo.count("Resumo"), 3)
        self.assertEqual(contagens["cabecalho_rodape"], 0)

    def test_tabela_numerica_entre_paginas_fica(self) -> None:
        paginas = ["\n".join(["1 | 2 | 3", "4 | 5 | 6", f"Texto da página {o}", "7 | 8 | 9"])
                   for o in ORDINAIS[:3]]
        limpo, contagens = limpar("\f".join(paginas))
        self.assertEqual(limpo.count("1 | 2 | 3"), 3)
        self.assertEqual(limpo.count("7 | 8 | 9"), 3)
        self.assertEqual(contagens, _zeros())


# ------------------------------------------------------------------- numeração e ruído
class TestNumeracaoRuido(unittest.TestCase):
    def test_numeracao_so_nas_bordas_de_textos_com_paginas(self) -> None:
        pagina1 = ["Página 1 de 3", "Conteúdo alfa", "Conteúdo beta", "Conteúdo gama", "17", "2/5",
                   "Conteúdo delta", "Conteúdo épsilon", "Conteúdo zeta", "Conteúdo eta", "- 1 -"]
        pagina2 = ["Pág. 2", "Texto dois", "12/2024", "15/13", "Texto final", "2/3"]
        limpo, contagens = limpar("\n".join(pagina1) + "\f" + "\n".join(pagina2))
        primeira, segunda = trechos.paginas(limpo)
        self.assertEqual(primeira.split("\n"), pagina1[1:-1])  # 17 e 2/5 no miolo ficam
        self.assertEqual(segunda.split("\n"), ["Texto dois", "12/2024", "15/13", "Texto final"])
        self.assertEqual(contagens["numeracao"], 4)

    def test_texto_de_uma_pagina_nao_tem_numeracao(self) -> None:
        linhas = ["Início do texto"] + [f"Conteúdo {g}" for g in GREGAS[:4]] + ["17", "2/5"] \
            + [f"Mais {g}" for g in GREGAS[4:9]]
        limpo, contagens = limpar("\n".join(linhas))
        self.assertEqual(limpo.split("\n"), linhas)
        self.assertEqual(contagens, _zeros())

    def test_ruido_em_pagina_de_ocr(self) -> None:
        linhas = ["Texto lido no OCR", "~~ ;; ^^ ,,", "I", "II", "1º", "X | X", "------",
                  "Mais uma linha", "a.,;:!?/", "Linha final do texto"]
        limpo, contagens = limpar("\n".join(linhas), ocr_paginas={1})
        self.assertEqual(limpo.split("\n"), ["Texto lido no OCR", "I", "II", "1º", "X | X",
                                             "Mais uma linha", "Linha final do texto"])
        self.assertEqual(contagens["ruido_ocr"], 3)

    def test_ruido_fora_do_ocr_so_nas_bordas(self) -> None:
        conteudo = [f"Conteúdo {g}" for g in GREGAS[:8]]
        linhas = ["-----", *conteudo[:4], "~~ ;; ^^ ,,", *conteudo[4:], "====="]
        limpo, contagens = limpar("\n".join(linhas))
        self.assertEqual(limpo.split("\n"), linhas[1:-1])
        self.assertEqual(contagens["ruido_ocr"], 2)


# ------------------------------------------------------------------- proteção
class TestProtecao(unittest.TestCase):
    def setUp(self) -> None:
        self.protecao = ProtecaoLimpeza.de_config(RAIZ)

    def test_nomes_em_assinaturas(self) -> None:
        for linha in ("Adriano Boinha", "Jhonatan Anjos", "MILTON CARLOS LOPES – CAL",
                      "Vereador Sylvio Mauricio", "Andrigo de Carvalho", "Axel Grael",
                      "Verônica Santos Lima", "Gabinete do vereador MILTON CARLOS DA SILVA LOPES",
                      "Fael Faustino", "Rodrigo Neves"):
            with self.subTest(linha=linha):
                self.assertTrue(self.protecao.protegida(linha))
        self.assertFalse(self.protecao.tem_nome("Milton"))
        self.assertFalse(self.protecao.protegida("Prefeitura Municipal"))
        self.assertTrue(all(len(par) == 2 for par in self.protecao.nomes))

    def test_estrutura_legal(self) -> None:
        for linha in ("CAPÍTULO II", "Capítulo 3", "Seção I", "TÍTULO I", "ANEXO I", "Anexo",
                      "Das Disposições Finais", "DAS DISPOSIÇÕES TRANSITÓRIAS", "I – manter",
                      "IV - garantir", "Art. 1º", "§ 2º", "JUSTIFICATIVA"):
            with self.subTest(linha=linha):
                self.assertTrue(self.protecao.protegida(linha))

    def test_enderecos_bairros_e_atos_numerados(self) -> None:
        protecao = ProtecaoLimpeza()
        for linha in ("Rua das Flores, 100", "Avenida Central", "Praça Arariboia", "Av. Sete de Setembro",
                      "Icaraí", "Requerimento nº 123/2024", "Indicação 45/2023", "Projeto de Lei nº 7/2025",
                      "Sala das Sessões"):
            with self.subTest(linha=linha):
                self.assertTrue(protecao.protegida(linha))
        for linha in ("Requerimento nº ____/2024", "Requerimento nº      /2024", ENDERECO_CAMARA,
                      "CÂMARA MUNICIPAL DE NITERÓI", "Sala das Sessões, 10 de maio de 2021",
                      "Plenário Brígido Tinoco, 22 de maio de 2021"):
            with self.subTest(linha=linha):
                self.assertFalse(protecao.protegida(linha))

    def test_contagem_de_palavras_so_com_letras(self) -> None:
        protecao = ProtecaoLimpeza()
        self.assertFalse(protecao.protegida("| 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |"))
        self.assertFalse(protecao.protegida("- - - - - - - - - - - - - -"))
        self.assertTrue(protecao.protegida(
            "uma linha de conteúdo com doze palavras ou mais para ser protegida sempre"))


# ------------------------------------------------------------------- clichês
class TestCliches(unittest.TestCase):
    def test_cliche_removido_e_protegidos_ficam(self) -> None:
        linhas = ["Art. 1º Fica instituído o programa.", "o programa municipal de hortas",
                  "MILTON CARLOS DA SILVA LOPES", "Lei nº 3.456/2020", "MILTON",
                  "Documento assinado eletronicamente.", "Sala das Sessões", "JUSTIFICATIVA"]
        cliches = {normalizar_linha(l) for l in linhas}
        protecao = ProtecaoLimpeza(["MILTON CARLOS DA SILVA LOPES", "MILTON"])
        limpo, contagens = limpar("\n".join(linhas), cliches, protecao,
                                  ementa="Institui o programa municipal de hortas comunitárias")
        # "MILTON" fica: linha de uma palavra só fora da lista fechada não é clichê
        self.assertEqual(limpo.split("\n"), [linhas[0], linhas[1], linhas[2], linhas[3], "MILTON",
                                             "Sala das Sessões", "JUSTIFICATIVA"])
        self.assertEqual(contagens["cliche"], 1)

    def test_continuacao_de_frase_nao_e_removida(self) -> None:
        linhas = ["Solicita providências quanto à", "sinalização da via", "Fim da frase.",
                  "sinalização da via"]
        limpo, contagens = limpar("\n".join(linhas), {"sinalizacao da via"})
        self.assertEqual(limpo.split("\n"), linhas[:3])
        self.assertEqual(contagens["cliche"], 1)

    def test_palavra_unica_so_da_lista_fechada(self) -> None:
        limpo, contagens = limpar("Texto do ofício.\nAtenciosamente,\nConsiderando",
                                  {"atenciosamente", "considerando"})
        self.assertEqual(limpo, "Texto do ofício.\nConsiderando")
        self.assertEqual(contagens["cliche"], 1)

    def test_gerar_cliches_deterministico(self) -> None:
        docs = [(f"doc{i}", f"Documento assinado eletronicamente\nConteúdo exclusivo {ORDINAIS[i % 4]}\n"
                            "Art. 5º Revogam-se as disposições em contrário.")
                for i in range(30)]
        a = gerar_cliches(docs)
        b = gerar_cliches(list(reversed(docs)))
        self.assertEqual(list(a.items()), list(b.items()))
        self.assertEqual(a, {"documento assinado eletronicamente": 30})
        with tempfile.TemporaryDirectory() as nome:
            um, dois = Path(nome) / "a.json", Path(nome) / "b.json"
            arquivos.salvar_mapa(um, a)
            arquivos.salvar_mapa(dois, b)
            self.assertEqual(um.read_bytes(), dois.read_bytes())
            self.assertEqual(json.loads(um.read_text(encoding="utf-8")), a)

    def _corpus(self, n: int, contagens: dict[str, int], **opcoes) -> dict[str, int]:
        docs = []
        for i in range(n):
            linhas = ["Texto comum de todos"]
            linhas += [linha for linha, k in contagens.items() if i < k]
            docs.append((f"d{i}", "\n".join(linhas)))
        return gerar_cliches(docs, **opcoes)

    def test_limites_exigem_documentos_e_fracao(self) -> None:
        r = self._corpus(2000, {"Linha alfa repetida": 40, "Linha beta repetida": 39,
                                "Rua das Flores, 100 - Fonseca": 30})
        self.assertIn("linha alfa repetida", r)      # 2% de 2000 = 40
        self.assertNotIn("linha beta repetida", r)   # passa de 20, mas não de 2%
        self.assertNotIn("rua das flores, # - fonseca", r)
        r = self._corpus(1000, {"Linha gama repetida": 20, "Linha delta repetida": 19})
        self.assertIn("linha gama repetida", r)
        self.assertNotIn("linha delta repetida", r)
        r = self._corpus(100, {"Linha epsilon repetida": 4, "Linha zeta repetida": 5}, min_docs=3)
        self.assertNotIn("linha epsilon repetida", r)  # nunca abaixo de 5 documentos
        self.assertIn("linha zeta repetida", r)
        self.assertEqual(r["texto comum de todos"], 100)

    def test_documento_repetido_conta_uma_vez(self) -> None:
        docs = [("a", "Linha única aqui")] * 10 + [(f"b{i}", "Outra coisa qualquer") for i in range(4)]
        self.assertEqual(gerar_cliches(docs, min_docs=1), {})

    def test_regras_da_auditoria(self) -> None:
        linhas_fixas = [
            "CÂMARA MUNICIPAL DE NITERÓI", "Av. Ernani do Amaral Peixoto, 625 - Centro - Niterói - RJ",
            "Assinado de forma digital por", "Por todo o exposto, justifica-se a presente proposição.",
            "Desde já, contamos com o apoio dos nobres pares.", "Telefone da Câmara: (21) 3105-2200",
            "Requerimento nº ____/2024", "Rua das Flores, 100 - Fonseca", "CAPÍTULO II", "I – manter",
            "Das Disposições Finais", "Atenciosamente", "Considerando", "Requer informações sobre a obra",
            "Institui o dia municipal", "Escreva para contato@exemplo.com", "Veja www.exemplo.com.br",
            "CPF do interessado: 529.982.247-25", "10 20 30", "12:30", "Adriano Boinha",
            "Jhonatan Anjos", "Axel Grael",
        ]
        docs = []
        for i in range(100):
            dia = i % 28 + 1
            linhas = linhas_fixas + [f"Plenário Brígido Tinoco, {dia} de maio de 2021",
                                     f"Niterói, {dia} de maio de 2022",
                                     f"Sala das Sessões, {dia} de maio de 2021",
                                     f"Requerimento nº {i + 1}/2024"]
            docs.append((f"d{i}", "\n".join(linhas)))
        protecao = ProtecaoLimpeza.de_config(RAIZ)
        r = gerar_cliches(docs, protecao=protecao)
        self.assertEqual(sorted(r), [
            "assinado de forma digital por",
            "atenciosamente",
            "av. ernani do amaral peixoto, # - centro - niteroi - rj",
            "camara municipal de niteroi",
            "desde ja, contamos com o apoio dos nobres pares",
            "niteroi, # de maio de #",
            "plenario brigido tinoco, # de maio de #",
            "por todo o exposto, justifica-se a presente proposicao",
            "requerimento nº ____/#",
            "sala das sessoes, # de maio de #",
        ])
        # telefone institucional liberado pode entrar; sem estar liberado, é ocorrência forte
        r = gerar_cliches(docs, protecao=protecao, liberados={"2131052200"})
        self.assertIn("telefone da camara: (#) #-#", r)

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
            self.assertEqual(dados, {"documento assinado eletronicamente": 25})
            self.assertEqual(limpeza.main(["--gerar-cliches", *args]), 2)  # não sobrescreve
            self.assertEqual(limpeza.main(["--recalcular-cliches", *args]), 0)
            self.assertEqual(limpeza.carregar_cliches(saida), dados)


# ------------------------------------------------------------------- integração e desempenho
class TestIdempotenciaIntegracao(unittest.TestCase):
    def test_idempotente(self) -> None:
        texto = _paginas([True, True, True, True]) + "\nPágina 4 de 4\n-----"
        uma, contagens = limpar(texto)
        self.assertEqual((contagens["cabecalho_rodape"], contagens["numeracao"], contagens["ruido_ocr"]),
                         (8, 1, 1))
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

    def test_texto_grande_rapido(self) -> None:
        frase = "A Câmara Municipal discutiu o projeto"
        linhas = [f"Coluna um{' ' * 40}{frase}{' ' * 30}R$ 1.234,{i:05d}" for i in range(34_000)]
        paginas = ["\n".join(linhas[i:i + 60]) for i in range(0, len(linhas), 60)]
        texto = "\f".join(paginas)
        self.assertGreater(len(texto), 4_000_000)
        inicio = time.perf_counter()
        limpo, _ = limpar(texto, {"documento assinado eletronicamente"})
        self.assertLess(time.perf_counter() - inicio, 2.0)
        self.assertEqual(len(trechos.paginas(limpo)), len(paginas))


if __name__ == "__main__":
    unittest.main()
