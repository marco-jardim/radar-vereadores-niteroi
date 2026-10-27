"""Testes do validador de dados e configuração, com entradas sintéticas."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from coletor import arquivos
from coletor import validar as V


def registro(**campos) -> dict:
    base = {
        "id": 275545, "numero": "1/2025", "ano": 2025, "data": "2025-02-06", "data_protocolo": "2025-02-10",
        "desfecho": "virou_lei", "ementa": "Altera a Lei nº 1.212.", "situacao": "PUBLICADO",
        "lei": {"numero": 3987, "data": "2025-04-08", "tipo": "sancionada", "veto_parcial": False},
        "autoria": [{"id": 7, "nome": "RODRIGO FLACH FARAH", "origem": "Vereador", "papel": "Autor"}],
        "tramitacoes": [{"seq": 1, "enviado": "2025-02-19", "data_resposta": None, "resultado": "Lido"}],
        "url": "https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento=275545",
    }
    return {**base, **campos}


def documento(**campos) -> dict:
    """Resolução de data/documentos já com o detalhe aplicado, como coletor.documentos grava."""
    base = {
        "id": 290861, "tipo": "resolucao", "numero": "1/2026", "ano": 2026, "data": "2026-02-11",
        "assunto": "CRIAÇÃO", "ementa": "CRIA O DIPLOMA DRª TÂNIA RODRIGUES.", "situacao": "ENCAMINHADO ÀS COMISSÕES",
        "autores": [{"id": 17, "nome": "LUIZ CARLOS GALLO DE FREITAS"}],
        "ultima_tramitacao": {"seq": 3, "objetivo": "Juntada", "enviado": "2026-03-03", "resultado": "",
                              "data_resposta": None, "observacao": ""},
        "n_tramitacoes": 3, "url": "https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento=290861",
        "autoria": [{"id": 17, "nome": "LUIZ CARLOS GALLO DE FREITAS", "origem": "Vereador", "papel": "Autor"}],
        "tramitacoes": [{"seq": 1, "objetivo": "Leitura", "enviado": "2026-02-25", "data_resposta": "2026-02-25",
                         "resultado": "Lido na Sessão Plenária"}],
        "processo": "", "protocolo": "1001/2026", "data_protocolo": "2026-02-11", "detalhe_em": "2026-10-22",
        "publicacao": None,
    }
    return {**base, **campos}


def requerimento_pendente(**campos) -> dict:
    """Requerimento só com a listagem, à espera da página de detalhe."""
    base = {
        "id": 294244, "tipo": "requerimento", "numero": "70/2026", "ano": 2026, "data": "2026-05-06",
        "ementa": "REQUER INFORMAÇÕES.", "situacao": "ENCAMINHADO À PREFEITURA",
        "autores": [{"id": 272, "nome": "ALLAN PINHO LYRA"}], "ultima_tramitacao": None, "n_tramitacoes": 0,
        "detalhe_pendente": True,
    }
    return {**base, **campos}


def indicacao(**campos) -> dict:
    """Indicação de um só autor: fica só com a listagem, sem detalhe nem marca de pendente."""
    base = {
        "id": 300001, "tipo": "indicacao", "numero": "1/2026", "ano": 2026, "data": "2026-02-03",
        "ementa": "Solicito tapa buraco na Rua X, Icaraí.", "situacao": "Arquivado",
        "autores": [{"id": 237, "nome": "ROBSON GUIMARÃES JOSÉ FILHO"}], "ultima_tramitacao": None, "n_tramitacoes": 0,
    }
    return {**base, **campos}


def canonico(registros: list[dict]) -> bytes:
    """Bytes que coletor.documentos.salvar_ano gravaria."""
    return arquivos.texto_lista(sorted(registros, key=lambda r: (r["ano"], int(r["numero"].split("/")[0]), r["id"]))).encode()


CURADORIA = {"_leia_me": "x", "entradas": [{"projeto": "1/2025", "alertas": [], "fontes": ["https://exemplo.org/noticia"]}]}
VEREADORES = {
    "legislaturas": [
        {"id": "2021-2024", "eleitos": [{"nome": "A", "siscam": "ANA MARIA"}, {"nome": "J", "siscam": "JOSÉ ADRIANO - FOLHA"}]},
        {"id": "2025-2028", "eleitos": [{"nome": "A", "siscam": "ANA MARIA"}]},
    ],
    "afastamentos": [{"siscam": "ANA MARIA", "legislatura": "2025-2028"}],
}


class Afirmacoes(unittest.TestCase):
    def assertProblema(self, problemas: list[str], trecho: str):
        self.assertTrue(any(trecho in p for p in problemas), f"nenhum problema contém {trecho!r}: {problemas}")


# ---------------------------------------------------------------------- utilidades
class TestDataValida(unittest.TestCase):
    def test_aceita(self):
        for valor in (None, "2025-02-06", "2024-02-29"):
            self.assertTrue(V.data_valida(valor), valor)

    def test_rejeita(self):
        for valor in ("06/02/2025", "2025-2-6", "2025-02-30", "2025-02-06T10:00", "", 20250206):
            self.assertFalse(V.data_valida(valor), valor)


# ---------------------------------------------------------------------- proposições
class TestValidarProposicoes(Afirmacoes):
    def test_dados_validos(self):
        arquivos = {2025: [registro(), registro(id=2, numero="2/2025", lei=None, desfecho="em_tramitacao")],
                    2024: [registro(id=3, numero="9/2024", ano=2024)]}
        self.assertEqual(V.validar_proposicoes(arquivos), [])

    def test_arquivo_que_nao_e_lista(self):
        self.assertProblema(V.validar_proposicoes({2025: {"id": 1}}), "deveria conter uma lista")

    def test_id_repetido_entre_arquivos(self):
        problemas = V.validar_proposicoes({2024: [registro(numero="1/2024", ano=2024)], 2025: [registro()]})
        self.assertEqual(len(problemas), 1)
        self.assertProblema(problemas, "id 275545 repetido")

    def test_id_repetido_no_mesmo_arquivo(self):
        self.assertProblema(V.validar_proposicoes({2025: [registro(), registro(numero="2/2025")]}), "repetido")

    def test_id_invalido(self):
        self.assertProblema(V.validar_proposicoes({2025: [registro(id="275545")]}), "'id' ausente ou não inteiro")
        self.assertProblema(V.validar_proposicoes({2025: [registro(id=True)]}), "'id' ausente ou não inteiro")

    def test_numero(self):
        self.assertProblema(V.validar_proposicoes({2025: [registro(numero="1-2025")]}), "formato <n>/<ano>")
        self.assertProblema(V.validar_proposicoes({2025: [registro(numero="1/2025x")]}), "formato <n>/<ano>")
        self.assertProblema(V.validar_proposicoes({2025: [registro(numero="0001/2025")]}), "formato <n>/<ano>")
        self.assertProblema(V.validar_proposicoes({2025: [registro(numero="1/2024")]}), "está no arquivo de 2025")
        self.assertProblema(V.validar_proposicoes({2025: [registro(ano=2024)]}), "'ano' 2024 difere")

    def test_datas(self):
        self.assertProblema(V.validar_proposicoes({2025: [registro(data="06/02/2025")]}), "'data'")
        self.assertProblema(V.validar_proposicoes({2025: [registro(data_protocolo="2025-02-30")]}), "'data_protocolo'")
        lei = {"numero": 3987, "data": "8/4/2025", "tipo": "sancionada", "veto_parcial": False}
        self.assertProblema(V.validar_proposicoes({2025: [registro(lei=lei)]}), "'lei.data'")
        trams = [{"seq": 4, "enviado": "2025-13-01", "data_resposta": None}]
        self.assertProblema(V.validar_proposicoes({2025: [registro(tramitacoes=trams)]}), "tramitação 4")

    def test_desfecho(self):
        self.assertProblema(V.validar_proposicoes({2025: [registro(desfecho="aprovado")]}), "desfecho 'aprovado' desconhecido")
        sem_desfecho = registro()
        del sem_desfecho["desfecho"]
        self.assertProblema(V.validar_proposicoes({2025: [sem_desfecho]}), "desfecho None desconhecido")

    def test_todos_os_desfechos_do_modelo_sao_aceitos(self):
        for i, desfecho in enumerate(sorted(V.DESFECHOS_CONHECIDOS), 1):
            with self.subTest(desfecho=desfecho):
                self.assertEqual(V.validar_proposicoes({2025: [registro(id=i, numero=f"{i}/2025", desfecho=desfecho)]}), [])

    def test_autoria(self):
        self.assertProblema(V.validar_proposicoes({2025: [registro(autoria={"nome": "X"})]}), "'autoria' deveria ser uma lista")
        self.assertProblema(V.validar_proposicoes({2025: [registro(autoria=["X"])]}), "autor 1 deveria ser um objeto")
        casos = {
            "sem 'nome'": {"id": 7, "nome": " ", "origem": "Vereador", "papel": "Autor"},
            "'origem' ausente": {"id": 7, "nome": "X", "papel": "Autor"},
            "sem a chave 'id'": {"nome": "X", "origem": "", "papel": "Autor"},
            "não é inteiro nem null": {"id": "7", "nome": "X", "origem": "", "papel": "Autor"},
        }
        for trecho, autor in casos.items():
            with self.subTest(trecho=trecho):
                self.assertProblema(V.validar_proposicoes({2025: [registro(autoria=[autor])]}), trecho)
        autor_sem_id = {"id": None, "nome": "X", "origem": "", "papel": "Co-Autor"}
        self.assertEqual(V.validar_proposicoes({2025: [registro(autoria=[autor_sem_id])]}), [])

    def test_registro_que_nao_e_objeto(self):
        self.assertProblema(V.validar_proposicoes({2025: ["texto"]}), "registro deveria ser um objeto")

    def test_indices(self):
        ids, numeros = V.indices({2025: [registro(), registro(id=2, numero="2/2025")], 2024: "inválido"})
        self.assertEqual(ids, {275545, 2})
        self.assertEqual(numeros, {"1/2025", "2/2025"})


# -------------------------------------------------------------------- substitutivos
LEI_3958 = {"numero": 3958, "data": "2024-09-12", "tipo": "veto_derrubado", "veto_parcial": False}


def substitutivo(**campos) -> dict:
    base = {
        "id": 266596, "numero": "1", "data": "2024-03-14", "situacao": "RECEBIDO PELA SMD",
        "autoria": [{"id": 81, "nome": "DANIEL MARQUES FREDERICO", "origem": "Vereador", "papel": "Autor"},
                    {"id": None, "nome": "MILTON CARLOS DA SILVA LOPES", "origem": "Vereador", "papel": "Co-Autor"}],
        "tramitacoes": [{"seq": 12, "enviado": "2024-07-31", "data_resposta": "2024-09-12", "resultado": "PROMULGADO"}],
        "lei": dict(LEI_3958),
    }
    return {**base, **campos}


def pl_140(**campos) -> dict:
    """PL 140/2021 como o coletor grava depois de ler o substitutivo que virou lei."""
    base = registro(id=127858, numero="140/2021", ano=2021, data="2021-04-21", data_protocolo="2021-04-21",
                    situacao="Apensado", lei=dict(LEI_3958), substitutivos=[substitutivo()], lei_substitutivo=266596)
    return {**base, **campos}


class TestValidarSubstitutivos(Afirmacoes):
    def validar(self, p: dict) -> list[str]:
        return V.validar_proposicoes({p["ano"]: [p]})

    def test_validos(self):
        self.assertEqual(self.validar(pl_140()), [])
        self.assertEqual(self.validar(registro(substitutivos=[])), [])  # chave vazia: PL já conferido
        sem_lei = pl_140(lei=None, desfecho="apensado", substitutivos=[substitutivo(lei=None)])
        del sem_lei["lei_substitutivo"]
        self.assertEqual(self.validar(sem_lei), [])

    def test_forma_dos_substitutivos(self):
        casos = {
            "'substitutivos' deveria ser uma lista": pl_140(substitutivos={"id": 1}),
            "substitutivo 1 deveria ser um objeto": pl_140(substitutivos=["x"]),
            "'id' ausente ou não inteiro": pl_140(substitutivos=[substitutivo(id="266596")]),
            "é o do próprio PL": pl_140(substitutivos=[substitutivo(id=127858)]),
            "id 266596 repetido": pl_140(substitutivos=[substitutivo(), substitutivo()]),
            "'numero' '001'": pl_140(substitutivos=[substitutivo(numero="001")]),
            "'data' '14/03/2024'": pl_140(substitutivos=[substitutivo(data="14/03/2024")]),
            "'situacao' ausente": pl_140(substitutivos=[substitutivo(situacao=None)]),
            "autor 1 sem a chave 'id'": pl_140(substitutivos=[substitutivo(autoria=[{"nome": "X", "origem": "", "papel": "Autor"}])]),
            "tramitação 12 com 'data_resposta'": pl_140(substitutivos=[substitutivo(tramitacoes=[{"seq": 12, "data_resposta": "12/09/2024"}])]),
            "'lei.data'": pl_140(substitutivos=[substitutivo(lei={**LEI_3958, "data": "12/09/2024"})]),
        }
        for trecho, p in casos.items():
            with self.subTest(trecho=trecho):
                self.assertProblema(self.validar(p), trecho)
        sem_chave = substitutivo()
        del sem_chave["lei"]
        self.assertProblema(self.validar(pl_140(substitutivos=[sem_chave])), "sem a chave 'lei'")

    def test_lei_substitutivo_coerente(self):
        casos = {
            "deveria ser o id inteiro": pl_140(lei_substitutivo="266596"),
            "não está em 'substitutivos'": pl_140(lei_substitutivo=999),
            "aponta para um substitutivo sem lei": pl_140(substitutivos=[substitutivo(lei=None)]),
            "o PL não consta como lei": pl_140(desfecho="apensado"),
        }
        for trecho, p in casos.items():
            with self.subTest(trecho=trecho):
                self.assertProblema(self.validar(p), trecho)
        sem_lista = pl_140()
        del sem_lista["substitutivos"]
        self.assertProblema(self.validar(sem_lista), "não está em 'substitutivos'")
        self.assertProblema(self.validar(pl_140(lei=None)), "o PL não consta como lei")


# ------------------------------------------------------------------------ cache IA
class TestValidarCacheIa(Afirmacoes):
    def test_valido(self):
        self.assertEqual(V.validar_cache_ia({"275545": {"hash": "95106c8c2765e0cf"}}, {275545}), [])

    def test_chave_sem_projeto(self):
        self.assertProblema(V.validar_cache_ia({"1": {"hash": "95106c8c2765e0cf"}}, {275545}), "chave '1' não corresponde")
        self.assertProblema(V.validar_cache_ia({"abc": {"hash": "95106c8c2765e0cf"}}, {275545}), "chave 'abc'")

    def test_hash_invalido(self):
        for h in ("95106c8c2765e0c", "95106c8c2765e0cf0", "95106c8c2765e0cg", "95106C8C2765E0CF", None):
            with self.subTest(hash=h):
                self.assertProblema(V.validar_cache_ia({"275545": {"hash": h}}, {275545}), "16 caracteres hexadecimais")
        self.assertProblema(V.validar_cache_ia({"275545": {}}, {275545}), "'hash' None")

    def test_formato_geral(self):
        self.assertProblema(V.validar_cache_ia([], set()), "deveria conter um objeto")
        self.assertProblema(V.validar_cache_ia({"275545": "x"}, {275545}), "deveria ser um objeto")


# ----------------------------------------------------------------------- curadoria
class TestValidarCuradoria(Afirmacoes):
    def test_valida(self):
        self.assertEqual(V.validar_curadoria(CURADORIA, {"1/2025"}), [])

    def test_projeto_inexistente_ou_mal_formatado(self):
        self.assertProblema(V.validar_curadoria(CURADORIA, {"2/2025"}), "projeto não existe")
        entrada = {"projeto": "PL 1/2025", "fontes": ["https://exemplo.org"]}
        self.assertProblema(V.validar_curadoria({"entradas": [entrada]}, {"1/2025"}), "fora do formato")

    def test_fontes(self):
        for fontes in ([], ["Jornal X, 2025"], ["ftp://exemplo.org/a"], "https://exemplo.org", None, ["https://"]):
            with self.subTest(fontes=fontes):
                entrada = {"projeto": "1/2025", "fontes": fontes}
                self.assertProblema(V.validar_curadoria({"entradas": [entrada]}, {"1/2025"}), "pelo menos uma URL")
        mista = {"projeto": "1/2025", "fontes": ["Diário Oficial", "http://exemplo.org/do"]}
        self.assertEqual(V.validar_curadoria({"entradas": [mista]}, {"1/2025"}), [])

    def test_projeto_repetido(self):
        entradas = CURADORIA["entradas"] * 2
        self.assertProblema(V.validar_curadoria({"entradas": entradas}, {"1/2025"}), "projeto repetido")

    def test_formato_geral(self):
        self.assertProblema(V.validar_curadoria([], set()), "lista 'entradas'")
        self.assertProblema(V.validar_curadoria({"entradas": ["x"]}, set()), "entrada 1 deveria ser um objeto")


# ---------------------------------------------------------------------- vereadores
class TestValidarVereadores(Afirmacoes):
    def test_valido_e_mesmo_nome_em_legislaturas_diferentes(self):
        self.assertEqual(V.validar_vereadores(VEREADORES), [])

    def test_nome_fora_de_maiusculas(self):
        cfg = copy.deepcopy(VEREADORES)
        cfg["legislaturas"][0]["eleitos"][0]["siscam"] = "Ana Maria"
        self.assertProblema(V.validar_vereadores(cfg), "'Ana Maria' deveria estar em maiúsculas")
        cfg = copy.deepcopy(VEREADORES)
        cfg["afastamentos"][0]["siscam"] = "Ana Maria"
        self.assertProblema(V.validar_vereadores(cfg), "afastamento")

    def test_nome_repetido_na_legislatura(self):
        cfg = copy.deepcopy(VEREADORES)
        cfg["legislaturas"][1]["eleitos"].append({"nome": "Outra", "siscam": "ANA MARIA"})
        problemas = V.validar_vereadores(cfg)
        self.assertEqual(len(problemas), 1)
        self.assertProblema(problemas, "legislatura '2025-2028': siscam 'ANA MARIA' repetido")

    def test_eleito_sem_siscam(self):
        cfg = copy.deepcopy(VEREADORES)
        cfg["legislaturas"][1]["eleitos"].append({"nome": "Sem"})
        self.assertProblema(V.validar_vereadores(cfg), "eleito sem 'siscam'")

    def test_formato_geral(self):
        self.assertProblema(V.validar_vereadores({}), "lista 'legislaturas'")
        self.assertProblema(V.validar_vereadores({"legislaturas": [{"id": "x"}]}), "sem a lista 'eleitos'")


class TestValidarMesa(Afirmacoes):
    FONTE = "https://consultaniteroi.siscam.com.br/Arquivos/Sessoes/ata.doc"

    def cfg(self, *itens: dict) -> dict:
        cfg = copy.deepcopy(VEREADORES)
        cfg["apelidos"] = {"_leia_me": "x", "CARLOS SUPLENTE": "Carlos"}
        cfg["mesa"] = [{"siscam": "ANA MARIA", "legislatura": "2021-2024", "bienio": "2021-2022", "cargo": "Presidente",
                        "fonte": self.FONTE, **item} for item in itens]
        return cfg

    def test_valida_e_opcional(self):
        self.assertEqual(V.validar_vereadores(VEREADORES), [])
        cfg = self.cfg({}, {"siscam": "JOSÉ ADRIANO - FOLHA", "cargo": "1º Secretário"},
                       {"siscam": "CARLOS SUPLENTE", "cargo": "2º Suplente"},
                       {"bienio": "2023-2024"}, {"legislatura": "2025-2028", "bienio": "2027-2028"})
        self.assertEqual(V.validar_vereadores(cfg), [])

    def test_erros(self):
        casos = {
            "campo vazio": ({"fonte": ""}, "campos ausentes ou vazios: fonte"),
            "legislatura": ({"legislatura": "1999-2002"}, "inexistente"),
            "biênio inválido": ({"bienio": "2021"}, "'bienio'"),
            "biênio não consecutivo": ({"bienio": "2021-2023"}, "'bienio'"),
            "biênio fora": ({"bienio": "2025-2026"}, "fora da legislatura"),
            "cargo": ({"cargo": "Tesoureiro"}, "'cargo'"),
            "pessoa": ({"siscam": "FULANO DESCONHECIDO"}, "nomes conhecidos"),
            "fonte": ({"fonte": "http://exemplo.org/ata"}, "HTTPS"),
            "campo extra": ({"observacao": "x"}, "desconhecidos"),
        }
        for nome, (item, trecho) in casos.items():
            with self.subTest(caso=nome):
                self.assertProblema(V.validar_vereadores(self.cfg(item)), trecho)
        self.assertProblema(V.validar_vereadores({**VEREADORES, "mesa": {}}), "'mesa' deveria ser uma lista")

    def test_repeticoes_no_bienio(self):
        cargo_repetido = self.cfg({}, {"siscam": "JOSÉ ADRIANO - FOLHA"})
        self.assertProblema(V.validar_vereadores(cargo_repetido), "cargo 'Presidente' repetido")
        dois_cargos = self.cfg({}, {"cargo": "1º Suplente"})
        self.assertProblema(V.validar_vereadores(dois_cargos), "dois cargos no biênio")
        outro_bienio = self.cfg({}, {"bienio": "2023-2024"})
        self.assertEqual(V.validar_vereadores(outro_bienio), [])

    def test_config_versionado(self):
        raiz = Path(__file__).resolve().parent.parent
        cfg = json.loads((raiz / "config" / "vereadores.json").read_text(encoding="utf-8"))
        self.assertIn("mesa", cfg)
        self.assertEqual(V.validar_vereadores(cfg), [])


# ---------------------------------------------------------------------- documentos
class TestValidarDocumento(Afirmacoes):
    ARQ = "data/documentos/resolucao/2026.json"

    def problemas(self, d: object, tipo: str = "resolucao") -> list[str]:
        return V.validar_documento(d, tipo, 2026, self.ARQ)

    def test_validos(self):
        self.assertEqual(self.problemas(documento()), [])
        self.assertEqual(self.problemas(documento(publicacao={"numero": 3167, "data": "2026-02-27"})), [])
        self.assertEqual(self.problemas(documento(publicacao={"numero": None, "data": None})), [])
        self.assertEqual(self.problemas(requerimento_pendente(), "requerimento"), [])
        respondido = requerimento_pendente(detalhe_em="2026-10-22", autoria=documento()["autoria"], tramitacoes=[],
                                           respondido_em="2026-08-06", dias_ate_resposta=92)
        del respondido["detalhe_pendente"]
        self.assertEqual(self.problemas(respondido, "requerimento"), [])
        self.assertEqual(self.problemas(requerimento_pendente(dias_ate_resposta=None), "requerimento"), [])
        self.assertEqual(self.problemas(indicacao(), "indicacao"), [])
        self.assertEqual(self.problemas(documento(autores=[])), [])

    def test_registro_que_nao_e_objeto(self):
        self.assertProblema(self.problemas(["x"]), "registro deveria ser um objeto")

    def test_tipo_ano_numero_e_id(self):
        self.assertProblema(self.problemas(documento(tipo="pdl")), "'tipo' 'pdl' difere da pasta (resolucao)")
        self.assertProblema(self.problemas(documento(ano=2025)), "'ano' 2025 difere do ano do arquivo (2026)")
        self.assertProblema(self.problemas(documento(ano="2026")), "'ano' '2026' difere")
        self.assertProblema(self.problemas(documento(numero="1/2025")), "'numero' é de 2025, mas está no arquivo de 2026")
        for numero in ("00001/2026", "1-2026", 1, None):
            with self.subTest(numero=numero):
                self.assertProblema(self.problemas(documento(numero=numero)), "'numero' fora do formato")
        for id_doc in ("290861", True, None):
            with self.subTest(id=id_doc):
                self.assertProblema(self.problemas(documento(id=id_doc)), "'id' ausente ou não inteiro")

    def test_datas(self):
        # o SISCAM exibe "20/10/2026 13:47"; o coletor grava só a data ISO
        for chave in ("data", "data_protocolo", "detalhe_em", "respondido_em"):
            for valor in ("20/10/2026 13:47", "2026-10-20 13:47", "2026-02-30"):
                with self.subTest(chave=chave, valor=valor):
                    self.assertProblema(self.problemas(documento(**{chave: valor})), f"'{chave}' {valor!r}")
        ultima = {**documento()["ultima_tramitacao"], "enviado": "20/10/2026 13:47"}
        self.assertProblema(self.problemas(documento(ultima_tramitacao=ultima)), "'ultima_tramitacao' com 'enviado'")
        ultima = {**documento()["ultima_tramitacao"], "data_resposta": "2026-10-21T00:00"}
        self.assertProblema(self.problemas(documento(ultima_tramitacao=ultima)), "com 'data_resposta'")
        self.assertProblema(self.problemas(documento(ultima_tramitacao="Juntada")), "'ultima_tramitacao' deveria ser um objeto")
        trams = [{"seq": 2, "enviado": "2026-13-01", "data_resposta": None}]
        self.assertProblema(self.problemas(documento(tramitacoes=trams)), "tramitação 2 com 'enviado'")
        publicacao = {"numero": 3167, "data": "27/02/2026"}
        self.assertProblema(self.problemas(documento(publicacao=publicacao)), "'publicacao.data'")

    def test_autores_e_contagem_de_tramitacoes(self):
        self.assertProblema(self.problemas(documento(autores={"id": 17})), "'autores' deveria ser uma lista")
        for autor in ({"id": "17", "nome": "X"}, {"id": 17, "nome": " "}, {"id": 17}, {"nome": "X"}, "X"):
            with self.subTest(autor=autor):
                self.assertProblema(self.problemas(documento(autores=[autor])), "autor 1 da listagem")
        for n in (-1, "3", None, 2.0, True):
            with self.subTest(n=n):
                self.assertProblema(self.problemas(documento(n_tramitacoes=n)), "'n_tramitacoes'")

    def test_campos_do_detalhe(self):
        sem_origem = [{"id": 17, "nome": "X", "papel": "Autor"}]
        self.assertProblema(self.problemas(documento(autoria=sem_origem)), "'origem' ausente")
        sem_autoria = documento()
        del sem_autoria["autoria"]
        self.assertProblema(self.problemas(sem_autoria), "'autoria' deveria ser uma lista")
        self.assertProblema(self.problemas(documento(tramitacoes=None)), "'tramitacoes' deveria ser uma lista")
        self.assertProblema(self.problemas(indicacao(tramitacoes="x"), "indicacao"), "'tramitacoes' deveria ser uma lista")
        for dias in (-1, "92", 9.5):
            with self.subTest(dias=dias):
                self.assertProblema(self.problemas(documento(dias_ate_resposta=dias)), "'dias_ate_resposta'")
        self.assertProblema(self.problemas(documento(publicacao={"numero": "3167", "data": None})), "'publicacao.numero'")
        self.assertProblema(self.problemas(documento(publicacao=[3167])), "'publicacao' deveria ser um objeto")

    def test_marca_de_detalhe_pendente(self):
        for valor in (False, None, "sim", 1):
            with self.subTest(valor=valor):
                self.assertProblema(self.problemas(documento(detalhe_pendente=valor)), "'detalhe_pendente' deveria ser true")
        self.assertEqual(self.problemas(documento(detalhe_pendente=True)), [])  # detalhe antigo, à espera de outro
        sem_marca = requerimento_pendente()
        del sem_marca["detalhe_pendente"]
        self.assertProblema(self.problemas(sem_marca, "requerimento"), "elegível para a página de detalhe")
        dois_autores = indicacao(autores=[{"id": 1, "nome": "A"}, {"id": 2, "nome": "B"}])
        self.assertProblema(self.problemas(dois_autores, "indicacao"), "elegível para a página de detalhe")
        self.assertEqual(self.problemas({**dois_autores, "detalhe_pendente": True}, "indicacao"), [])


class TestValidarDocumentos(Afirmacoes):
    def raiz(self, arquivos_: dict[str, bytes | str]) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        raiz = Path(tmp.name)
        for caminho, conteudo in arquivos_.items():
            destino = raiz / "data" / "documentos" / caminho
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(conteudo if isinstance(conteudo, bytes) else conteudo.encode("utf-8"))
        return raiz

    def test_sem_pasta_de_documentos(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.assertEqual(V.validar_documentos(Path(tmp.name), set()), [])

    def test_arquivos_validos(self):
        raiz = self.raiz({
            "resolucao/2026.json": canonico([documento(), documento(id=290862, numero="2/2026")]),
            "requerimento/2026.json": canonico([requerimento_pendente()]),
            "indicacao/2026.json": canonico([indicacao()]),
            "mocao/2026.json": canonico([]),
        })
        self.assertEqual(V.validar_documentos(raiz, {275545}), [])

    def test_formato_canonico_byte_a_byte(self):
        registros = [documento(), documento(id=290862, numero="2/2026"), documento(id=290870, numero="10/2026")]
        bruto = canonico(registros)
        variantes = {
            "ordem por número": arquivos.texto_lista([registros[0], registros[2], registros[1]]).encode(),
            "ordem por texto": arquivos.texto_lista(sorted(registros, key=lambda r: r["numero"])).encode(),
            "indentado": (json.dumps(registros, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode(),
            "CRLF": bruto.replace(b"\n", b"\r\n"),
            "sem quebra final": bruto.rstrip(b"\n"),
            "acentos escapados": (
                "[\n" + ",\n".join(json.dumps(r, sort_keys=True, separators=(",", ":")) for r in registros) + "\n]\n"
            ).encode(),
        }
        self.assertEqual(V.validar_documentos(self.raiz({"resolucao/2026.json": bruto}), set()), [])
        for nome, conteudo in variantes.items():
            with self.subTest(variante=nome):
                problemas = V.validar_documentos(self.raiz({"resolucao/2026.json": conteudo}), set())
                self.assertEqual(len(problemas), 1, problemas)
                self.assertProblema(problemas, "data/documentos/resolucao/2026.json: fora do formato")

    def test_pastas_e_nomes(self):
        raiz = self.raiz({
            "projeto/2026.json": canonico([]),
            "resolucao/todos.json": canonico([]),
            "solto.json": canonico([]),
        })
        problemas = V.validar_documentos(raiz, set())
        self.assertProblema(problemas, "data/documentos/projeto: esperado um diretório de tipo")
        self.assertProblema(problemas, "data/documentos/solto.json: esperado um diretório de tipo")
        self.assertProblema(problemas, "data/documentos/resolucao/todos.json: nome de arquivo deveria ser <ano>.json")

    def test_conteudo_ilegivel_ou_que_nao_e_lista(self):
        raiz = self.raiz({"resolucao/2025.json": "[{", "resolucao/2026.json": '{"id": 1}\n', "pdl/2026.json": b"\xff\xfe"})
        problemas = V.validar_documentos(raiz, set())
        self.assertProblema(problemas, "data/documentos/resolucao/2025.json: não foi possível ler o JSON")
        self.assertProblema(problemas, "data/documentos/resolucao/2026.json: deveria conter uma lista")
        self.assertProblema(problemas, "data/documentos/pdl/2026.json: não foi possível ler o JSON")

    def test_ids_unicos_entre_arquivos_e_distintos_das_proposicoes(self):
        raiz = self.raiz({
            "resolucao/2026.json": canonico([documento()]),
            "pdl/2026.json": canonico([documento(tipo="pdl")]),
            "resolucao/2025.json": canonico([documento(id=275545, numero="1/2025", ano=2025)]),
        })
        problemas = V.validar_documentos(raiz, {275545})
        self.assertProblema(problemas, "id 290861 repetido (já aparece em data/documentos/pdl/2026.json)")
        self.assertProblema(problemas, "data/documentos/resolucao/2025.json: id 275545 também está em data/proposicoes")

    def test_le_os_ids_das_proposicoes_se_nao_informados(self):
        raiz = self.raiz({"resolucao/2026.json": canonico([documento(id=275545)])})
        (raiz / "data" / "proposicoes").mkdir(parents=True)
        (raiz / "data" / "proposicoes" / "2025.json").write_text(json.dumps([registro()]), encoding="utf-8")
        self.assertProblema(V.validar_documentos(raiz), "id 275545 também está em data/proposicoes")


class TestValidarMeta(Afirmacoes):
    def test_valida(self):
        self.assertEqual(V.validar_meta({}), [])
        self.assertEqual(V.validar_meta({"coleta": {}, "documentos": {"em": "x", "tipos": {}}}), [])

    def test_invalida(self):
        self.assertProblema(V.validar_meta([]), "data/meta.json: deveria conter um objeto")
        self.assertProblema(V.validar_meta({"documentos": {"em": "x"}}), "mapa 'tipos'")
        self.assertProblema(V.validar_meta({"documentos": []}), "mapa 'tipos'")


# ------------------------------------------------------------------------ execução
class TestExecucao(Afirmacoes):
    def montar_raiz(self, registros: object = None, cache: object = None, curadoria: object = None) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        raiz = Path(tmp.name)
        (raiz / "data" / "proposicoes").mkdir(parents=True)
        (raiz / "config").mkdir()
        escrever = lambda caminho, dados: (raiz / caminho).write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
        escrever("data/proposicoes/2025.json", [registro()] if registros is None else registros)
        escrever("data/classificacao_ia.json", {"275545": {"hash": "95106c8c2765e0cf"}} if cache is None else cache)
        escrever("config/curadoria.json", CURADORIA if curadoria is None else curadoria)
        escrever("config/vereadores.json", VEREADORES)
        (raiz / "config" / "memoria.json").write_bytes(
            (json.dumps({"criterios": "Critérios de memória", "homenageados": [], "linha_do_tempo": []},
                        ensure_ascii=False, indent=1) + "\n").encode("utf-8")
        )
        # Perfis mínimos no formato canônico: sem o arquivo, o validador só avisaria (stderr não ficaria vazio).
        (raiz / "config" / "perfis.json").write_bytes(
            (json.dumps({"vereadores": {}}, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
        )
        return raiz

    def rodar_main(self, raiz: Path, ambiente: dict) -> tuple[int, str, str]:
        erro, saida = io.StringIO(), io.StringIO()
        with mock.patch.object(V, "RAIZ", raiz), mock.patch.dict(os.environ, ambiente), \
                contextlib.redirect_stderr(erro), contextlib.redirect_stdout(saida):
            if "GITHUB_ACTIONS" not in ambiente:
                os.environ.pop("GITHUB_ACTIONS", None)
            codigo = V.main()
        return codigo, erro.getvalue(), saida.getvalue()

    def test_validar_tudo_sem_problemas(self):
        self.assertEqual(V.validar_tudo(self.montar_raiz()), [])

    def test_validar_tudo_reune_problemas_de_todos_os_arquivos(self):
        raiz = self.montar_raiz(cache={"999": {"hash": "x"}}, curadoria={"entradas": [{"projeto": "5/2025", "fontes": []}]})
        problemas = V.validar_tudo(raiz)
        self.assertProblema(problemas, "data/classificacao_ia.json: chave '999'")
        self.assertProblema(problemas, "data/classificacao_ia.json: entrada '999' com 'hash'")
        self.assertProblema(problemas, "config/curadoria.json: entrada 1 ('5/2025'): projeto não existe")
        self.assertProblema(problemas, "pelo menos uma URL")

    def test_arquivos_opcionais_e_invalidos(self):
        raiz = self.montar_raiz()
        (raiz / "data" / "classificacao_ia.json").unlink()
        (raiz / "config" / "curadoria.json").unlink()
        self.assertEqual(V.validar_tudo(raiz), [])
        (raiz / "data" / "proposicoes" / "2024.json").write_text("[{", encoding="utf-8")
        (raiz / "data" / "proposicoes" / "todos.json").write_text("[]", encoding="utf-8")
        problemas = V.validar_tudo(raiz)
        self.assertProblema(problemas, "data/proposicoes/2024.json: não foi possível ler o JSON")
        self.assertProblema(problemas, "data/proposicoes/todos.json: nome de arquivo deveria ser <ano>.json")

    def test_sem_arquivos_anuais(self):
        raiz = self.montar_raiz()
        (raiz / "data" / "proposicoes" / "2025.json").unlink()
        self.assertProblema(V.validar_tudo(raiz), "nenhum arquivo <ano>.json")

    def test_validar_tudo_inclui_documentos(self):
        raiz = self.montar_raiz()
        pasta = raiz / "data" / "documentos" / "resolucao"
        pasta.mkdir(parents=True)
        (pasta / "2026.json").write_bytes(canonico([documento()]))
        self.assertEqual(V.validar_tudo(raiz), [])
        (pasta / "2026.json").write_bytes(canonico([documento(id=275545)]))  # mesmo id do projeto de lei
        self.assertProblema(V.validar_tudo(raiz), "id 275545 também está em data/proposicoes")

    def test_meta(self):
        raiz = self.montar_raiz()
        meta = raiz / "data" / "meta.json"
        meta.write_text(json.dumps({"coleta": {}, "documentos": {"em": "x", "tipos": {}}}), encoding="utf-8")
        self.assertEqual(V.validar_tudo(raiz), [])
        meta.write_text('{"coleta": ', encoding="utf-8")
        self.assertProblema(V.validar_tudo(raiz), "data/meta.json: não foi possível ler o JSON")
        meta.write_text("[]", encoding="utf-8")
        self.assertProblema(V.validar_tudo(raiz), "data/meta.json: deveria conter um objeto")

    def test_temporario_de_gravacao_interrompida(self):
        raiz = self.montar_raiz()
        pasta = raiz / "data" / "documentos" / "resolucao"
        pasta.mkdir(parents=True)
        (pasta / ".2026.json.k3j9x.tmp").write_text("[\n", encoding="utf-8")
        (raiz / "data" / ".meta.json.a1b2.tmp").write_text("{", encoding="utf-8")
        problemas = V.validar_tudo(raiz)
        self.assertEqual(len(problemas), 2, problemas)
        self.assertProblema(problemas, "data/documentos/resolucao/.2026.json.k3j9x.tmp: temporário de gravação interrompida")
        self.assertProblema(problemas, "data/.meta.json.a1b2.tmp: temporário")

    def test_main_ok(self):
        codigo, erro, saida = self.rodar_main(self.montar_raiz(), {})
        self.assertEqual(codigo, 0)
        self.assertEqual(erro, "")
        self.assertIn("OK", saida)

    def test_main_com_problemas(self):
        raiz = self.montar_raiz(registros=[registro(desfecho="inventado")])
        codigo, erro, _ = self.rodar_main(raiz, {})
        self.assertEqual(codigo, 1)
        self.assertIn("desfecho 'inventado' desconhecido", erro)
        self.assertNotIn("::error::", erro)

    def test_main_no_github_actions(self):
        raiz = self.montar_raiz(registros=[registro(desfecho="inventado")])
        codigo, erro, _ = self.rodar_main(raiz, {"GITHUB_ACTIONS": "true"})
        self.assertEqual(codigo, 1)
        linhas = [l for l in erro.splitlines() if "desconhecido" in l]
        self.assertTrue(linhas)
        self.assertTrue(all(l.startswith("::error::") for l in linhas))

    def test_anotacao_escapa_caracteres_especiais(self):
        self.assertEqual(V._anotacao("100% certo\nlinha"), "100%25 certo%0Alinha")


if __name__ == "__main__":
    unittest.main()
