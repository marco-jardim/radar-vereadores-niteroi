"""Validação offline da configuração editorial da página de memória."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import tempfile
import unicodedata
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from coletor import validar as V


def configuracao() -> dict:
    """Configuração sintética válida; cada chamada devolve listas e objetos independentes."""
    return {
        "criterios": "Pessoas falecidas com vínculo com Niterói e fontes públicas.",
        "homenageados": [{
            "id": "antonio-exemplo", "nome": "Antônio", "nome_completo": "Antônio Exemplo",
            "nascimento": "1860-01-20", "morte": "1937-10-17", "categoria": "artes",
            "vinculo": "Nasceu em Niterói.", "biografia": ["Foi pintor."],
            "emblema": "antonio-exemplo.svg",
            "imagem": {"tipo": "propria", "credito": "Ilustração própria do projeto"},
            "fontes": [{"titulo": "Biografia", "url": "https://exemplo.org/biografia"}],
        }],
        "linha_do_tempo": [{
            "data": "1573-11-22", "titulo": "Fundação", "texto": "Marco de fundação de Niterói.",
            "fontes": [{"titulo": "História", "url": "https://exemplo.org/historia"}],
        }],
    }


def canonico(dados: object) -> bytes:
    return (json.dumps(dados, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


class TestMemoriaConfig(unittest.TestCase):
    HOJE = date(2026, 10, 26)

    def setUp(self):
        temporario = tempfile.TemporaryDirectory()
        self.addCleanup(temporario.cleanup)
        self.raiz = Path(temporario.name)
        self.caminho = self.raiz / "config" / "memoria.json"
        self.caminho.parent.mkdir()

    def validar(self, dados: object) -> list[str]:
        self.caminho.write_bytes(canonico(dados))
        return V.validar_memoria(self.caminho, hoje=self.HOJE)

    def assertProblema(self, problemas: list[str], trecho: str):
        self.assertTrue(any(trecho in p for p in problemas), f"nenhum problema contém {trecho!r}: {problemas}")

    def test_configuracao_valida_e_arquivo_real(self):
        self.assertEqual(self.validar(configuracao()), [])
        real = Path(__file__).resolve().parent.parent / "config" / "memoria.json"
        self.assertTrue(real.is_file(), "a configuração real deve existir")
        self.assertEqual(V.validar_memoria(real, hoje=self.HOJE), [])
        with mock.patch.object(V, "RAIZ", self.raiz):
            self.assertEqual(V.validar_memoria(hoje=self.HOJE), [])

    def test_arquivo_ausente_avisa_sem_problemas(self):
        for ambiente in ({}, {"GITHUB_ACTIONS": "true"}):
            with self.subTest(ambiente=ambiente), mock.patch.dict(os.environ, ambiente, clear=True):
                erro = io.StringIO()
                with contextlib.redirect_stderr(erro):
                    self.assertEqual(V.validar_memoria(self.caminho), [])
                self.assertIn("config/memoria.json: arquivo ausente", erro.getvalue())
                self.assertNotIn("::error::", erro.getvalue())
                if ambiente:
                    self.assertTrue(erro.getvalue().startswith("::warning::"))
                else:
                    self.assertTrue(erro.getvalue().startswith("aviso:"))

    def test_json_invalido_e_utf8_invalido(self):
        for bruto in (b'{"criterios":', b"\xff\xfe"):
            with self.subTest(bruto=bruto):
                self.caminho.write_bytes(bruto)
                self.assertProblema(V.validar_memoria(self.caminho), "não foi possível ler o JSON")

    def test_estrutura_superior(self):
        for dados in ([], None, "texto"):
            with self.subTest(dados=dados):
                self.assertProblema(self.validar(dados), "deveria conter um objeto")
        for chave, valores in {"criterios": (None, "", " ", []),
                               "homenageados": (None, {}, "texto"),
                               "linha_do_tempo": (None, {}, "texto")}.items():
            for valor in valores:
                with self.subTest(chave=chave, valor=valor):
                    dados = configuracao()
                    dados[chave] = valor
                    self.assertProblema(self.validar(dados), f"'{chave}'")
            dados = configuracao()
            del dados[chave]
            self.assertProblema(self.validar(dados), f"'{chave}'")
        self.assertEqual(self.validar({"criterios": "Critérios", "homenageados": [], "linha_do_tempo": []}), [])

    def test_campos_obrigatorios_da_pessoa(self):
        for chave in configuracao()["homenageados"][0]:
            with self.subTest(chave=chave):
                dados = configuracao()
                del dados["homenageados"][0][chave]
                self.assertProblema(self.validar(dados), f"'{chave}'")
        for chave in ("nome", "nome_completo", "vinculo"):
            for valor in (None, "", " ", 123):
                with self.subTest(chave=chave, valor=valor):
                    dados = configuracao()
                    dados["homenageados"][0][chave] = valor
                    self.assertProblema(self.validar(dados), f"'{chave}'")
        for biografia in ([], "Texto", [""], [" "], [None], ["Texto", 42]):
            with self.subTest(biografia=biografia):
                dados = configuracao()
                dados["homenageados"][0]["biografia"] = biografia
                self.assertProblema(self.validar(dados), "'biografia'")

    def test_datas_validas_e_invalidas(self):
        for campo in ("nascimento", "morte", "data", "data_fim"):
            for valor in ("1900", "2000-02-29", "2026-01-01"):
                with self.subTest(campo=campo, valor=valor):
                    dados = configuracao()
                    item = dados["homenageados"][0] if campo in ("nascimento", "morte") else dados["linha_do_tempo"][0]
                    item[campo] = valor
                    self.assertEqual(self.validar(dados), [])
            for valor in ("1900-02-29", "2026-02-30", "2026-13-01", "2026-1-1", "26", "", 2026,
                          "2026-01-01T00:00", "2026\n"):
                with self.subTest(campo=campo, valor=valor):
                    dados = configuracao()
                    item = dados["homenageados"][0] if campo in ("nascimento", "morte") else dados["linha_do_tempo"][0]
                    item[campo] = valor
                    self.assertProblema(self.validar(dados), f"'{campo}'")
        for campo in ("data", "data_fim"):
            dados = configuracao()
            dados["linha_do_tempo"][0][campo] = None
            self.assertProblema(self.validar(dados), f"'{campo}'")

    def test_apenas_falecidos_e_nascimento_desconhecido(self):
        for campo in ("nascimento", "morte"):
            for texto in (None, "", " ", 123):
                with self.subTest(campo=campo, texto=texto):
                    dados = configuracao()
                    pessoa = dados["homenageados"][0]
                    pessoa[campo] = None
                    if texto is not None:
                        pessoa[f"{campo}_texto"] = texto
                    trecho = "somente falecidos" if campo == "morte" else "nascimento null exige"
                    self.assertProblema(self.validar(dados), trecho)
        dados = configuracao()
        dados["homenageados"][0].update(nascimento=None, nascimento_texto="século XVI",
                                          morte=None, morte_texto="fim do século XVI")
        self.assertEqual(self.validar(dados), [])

    def test_categorias_fechadas(self):
        for categoria in ("fundacao", "ciencia", "artes", "musica", "arquitetura"):
            dados = configuracao()
            dados["homenageados"][0]["categoria"] = categoria
            self.assertEqual(self.validar(dados), [])
        for categoria in ("politica", "", None, []):
            dados = configuracao()
            dados["homenageados"][0]["categoria"] = categoria
            self.assertProblema(self.validar(dados), "'categoria'")

    def test_fontes_de_pessoas_e_eventos(self):
        fontes_invalidas = ([], None, "https://exemplo.org", ["https://exemplo.org"], [{}],
                            [{"titulo": "", "url": "https://exemplo.org"}],
                            [{"titulo": "Fonte", "url": "http://exemplo.org"}],
                            [{"titulo": "Fonte", "url": ""}], [{"titulo": "Fonte", "url": None}])
        for lista in ("homenageados", "linha_do_tempo"):
            for fontes in fontes_invalidas:
                with self.subTest(lista=lista, fontes=fontes):
                    dados = configuracao()
                    dados[lista][0]["fontes"] = fontes
                    self.assertTrue(self.validar(dados))
            dados = configuracao()
            dados[lista][0]["fontes"].append({"titulo": "Outra fonte", "url": "http://exemplo.org"})
            self.assertProblema(self.validar(dados), "'url' deveria começar com https://")

    def test_ids_unicos_e_formato(self):
        dados = configuracao()
        dados["homenageados"].append(copy.deepcopy(dados["homenageados"][0]))
        self.assertProblema(self.validar(dados), "id 'antonio-exemplo' repetido")
        for identificador in ("Antônio", "antonio_exemplo", "-antonio", "antonio-", "a--b", "../a", "a\n", None, []):
            with self.subTest(identificador=identificador):
                dados = configuracao()
                dados["homenageados"][0]["id"] = identificador
                self.assertProblema(self.validar(dados), "'id'")

    def test_campos_obrigatorios_dos_eventos(self):
        for chave in ("data", "titulo", "texto", "fontes"):
            dados = configuracao()
            del dados["linha_do_tempo"][0][chave]
            self.assertProblema(self.validar(dados), f"'{chave}'")
        for chave in ("titulo", "texto"):
            dados = configuracao()
            dados["linha_do_tempo"][0][chave] = " "
            self.assertProblema(self.validar(dados), f"'{chave}'")

    def test_ordem_e_intervalos_da_linha_do_tempo(self):
        dados = configuracao()
        evento = dados["linha_do_tempo"][0]
        evento.update(data="1900-01-01", data_fim="1900")
        self.assertProblema(self.validar(dados), "'data_fim' anterior a 'data'")
        for fim in ("1900-01-01", "1901"):
            evento["data_fim"] = fim
            self.assertEqual(self.validar(dados), [])
        dados["linha_do_tempo"] = [{**evento, "data": data, "data_fim": "1901"}
                                  for data in ("1900", "1900-01-01", "1900-02-01")]
        self.assertEqual(self.validar(dados), [])
        dados["linha_do_tempo"].reverse()
        self.assertProblema(self.validar(dados), "linha_do_tempo fora de ordem")

    def test_dominio_publico_prazo_e_campos(self):
        imagem = {"tipo": "dominio_publico", "credito": "Acervo público", "autor": "Fotógrafo",
                  "ano_divulgacao": self.HOJE.year - 71, "url_origem": "https://exemplo.org/foto"}
        dados = configuracao()
        dados["homenageados"][0]["imagem"] = imagem
        self.assertEqual(self.validar(dados), [])
        for idade in (69, 70):
            with self.subTest(idade=idade):
                imagem["ano_divulgacao"] = self.HOJE.year - idade
                self.assertProblema(self.validar(dados), "ano_divulgacao + 70 < 2026")
        imagem["ano_divulgacao"] = self.HOJE.year - 71
        for chave in ("autor", "ano_divulgacao", "url_origem"):
            incompleta = copy.deepcopy(dados)
            del incompleta["homenageados"][0]["imagem"][chave]
            self.assertProblema(self.validar(incompleta), f"'{chave}'")
        for chave, valor in (("autor", " "), ("ano_divulgacao", "1955"), ("ano_divulgacao", True),
                             ("url_origem", "http://exemplo.org/foto"), ("url_origem", "")):
            invalida = copy.deepcopy(dados)
            invalida["homenageados"][0]["imagem"][chave] = valor
            self.assertProblema(self.validar(invalida), f"'{chave}'")

    def test_imagem_tipo_credito_e_emblema(self):
        for imagem in (None, {}, {"tipo": "externa", "credito": "Fonte"},
                       {"tipo": "propria", "credito": " "}):
            dados = configuracao()
            dados["homenageados"][0]["imagem"] = imagem
            self.assertTrue(self.validar(dados))
        for emblema in ("../x.svg", "pasta/x.svg", "X.svg", "x.png", "x.svg\n", None):
            dados = configuracao()
            dados["homenageados"][0]["emblema"] = emblema
            self.assertProblema(self.validar(dados), "'emblema'")

    def test_registros_malformados_nao_causam_excecao(self):
        for lista in ("homenageados", "linha_do_tempo"):
            for item in (None, "texto", [], 42):
                dados = configuracao()
                dados[lista] = [item]
                self.assertProblema(self.validar(dados), "deveria ser um objeto")

    def test_formato_byte_a_byte_e_ordem_das_chaves_preservada(self):
        dados = configuracao()
        bruto = canonico(dados)
        variantes = {"CRLF": bruto.replace(b"\n", b"\r\n"), "sem quebra final": bruto[:-1],
                     "indentação": (json.dumps(dados, ensure_ascii=False, indent=2) + "\n").encode(),
                     "acentos escapados": (json.dumps(dados, indent=1) + "\n").encode()}
        for nome, conteudo in variantes.items():
            with self.subTest(variante=nome):
                self.caminho.write_bytes(conteudo)
                self.assertProblema(V.validar_memoria(self.caminho, hoje=self.HOJE), "fora do formato esperado")
        self.assertEqual(self.validar(dict(reversed(list(dados.items())))), [])

    def test_nfc_em_nomes_e_textos_recursivos(self):
        dados = configuracao()
        dados["homenageados"][0]["nome"] = unicodedata.normalize("NFD", "Antônio")
        self.assertProblema(self.validar(dados), "NFC")
        dados["homenageados"][0]["nome"] = unicodedata.normalize("NFC", "Antônio")
        self.assertEqual(self.validar(dados), [])
        for alterar in (lambda d, s: d.update(_leia_me=s),
                        lambda d, s: d["homenageados"][0]["biografia"].append(s),
                        lambda d, s: d["linha_do_tempo"][0]["fontes"][0].update(titulo=s),
                        lambda d, s: d.update({s: "Campo opcional"})):
            dados = configuracao()
            alterar(dados, unicodedata.normalize("NFD", "Memória"))
            self.assertProblema(self.validar(dados), "NFC")

    def test_integracao_validar_tudo_e_main(self):
        pasta = self.raiz / "data" / "proposicoes"
        pasta.mkdir(parents=True)
        (pasta / "2026.json").write_bytes(b"[]\n")
        (self.raiz / "config" / "vereadores.json").write_bytes(canonico({"legislaturas": []}))
        self.validar(configuracao())
        self.assertEqual(V.validar_tudo(self.raiz), [])
        dados = configuracao()
        dados["homenageados"][0]["categoria"] = "politica"
        self.validar(dados)
        self.assertProblema(V.validar_tudo(self.raiz), "'categoria' desconhecida")
        erro, saida = io.StringIO(), io.StringIO()
        with mock.patch.object(V, "RAIZ", self.raiz), mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}), \
                contextlib.redirect_stderr(erro), contextlib.redirect_stdout(saida):
            self.assertEqual(V.main(), 1)
        self.assertIn("::error::config/memoria.json:", erro.getvalue())


if __name__ == "__main__":
    unittest.main()
