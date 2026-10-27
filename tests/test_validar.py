"""Testes do validador de dados e configuração, com entradas sintéticas."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import tempfile
import unittest
from datetime import date, timedelta
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
    "afastamentos": [{"siscam": "ANA MARIA", "legislatura": "2025-2028", "cargo": "Secretária Municipal",
                      "natureza": "cargo", "fonte": "https://exemplo.org/ato"}],
}
BACKEND = {"api_url": None, "origens_cors": ["https://exemplo.org"], "contatos_institucionais": []}
REMOCAO = {"chave": "siscam:123", "sha256": "ab" * 32, "motivo": "Remoção solicitada.",
           "fonte": "https://exemplo.org/pedido", "data": "2024-02-29"}


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


class TestValidarAfastamentos(Afirmacoes):
    def cfg(self, **campos) -> dict:
        cfg = copy.deepcopy(VEREADORES)
        cfg["apelidos"] = {"_leia_me": "x", "BIA SUPLENTE": "Bia"}
        cfg["afastamentos"][0].update(campos)
        return cfg

    def test_opcionais_nulos_e_sem_datas(self):
        self.assertEqual(V.validar_vereadores(self.cfg()), [])  # fonte sem data é admitida
        cfg = self.cfg(inicio=None, fim=None, aprovacao=None, ato=None, suplentes=[])
        self.assertEqual(V.validar_vereadores(cfg), [])
        del cfg["afastamentos"]
        self.assertEqual(V.validar_vereadores(cfg), [])

    def test_natureza(self):
        for natureza in ("cargo", "licenca"):
            self.assertEqual(V.validar_vereadores(self.cfg(natureza=natureza)), [])
        for natureza in ("Licença", "outro", [], {}):
            with self.subTest(natureza=natureza):
                self.assertProblema(V.validar_vereadores(self.cfg(natureza=natureza)), "natureza")

    def test_datas_e_evidencias_validas(self):
        for evidencia in ("ata", "requerimento", "diario_oficial", "prefeitura", "alerj", "imprensa"):
            with self.subTest(evidencia=evidencia):
                cfg = self.cfg(inicio="2025-01-01", fim="2028-12-31", aprovacao="2025-01-02",
                               evidencia=evidencia, ato="https://exemplo.org/ata", nota="Licença aprovada.")
                self.assertEqual(V.validar_vereadores(cfg), [])

    def test_nomes_conhecidos_inclusive_suplentes_e_perfis(self):
        # Eleita de outra legislatura, apelido e perfil são igualmente admitidos.
        perfis = {"vereadores": {"CAIO SUPLENTE": {}}}
        for nome in ("JOSÉ ADRIANO - FOLHA", "BIA SUPLENTE", "CAIO SUPLENTE"):
            with self.subTest(nome=nome):
                cfg = self.cfg(siscam=nome, suplentes=[nome])
                self.assertEqual(V.validar_vereadores(cfg, perfis), [])

    def test_campos_obrigatorios(self):
        for campo in ("siscam", "legislatura", "cargo", "natureza", "fonte"):
            for valor in (None, "", " "):
                with self.subTest(campo=campo, valor=valor):
                    self.assertProblema(V.validar_vereadores(self.cfg(**{campo: valor})), campo)
            cfg = self.cfg()
            del cfg["afastamentos"][0][campo]
            self.assertProblema(V.validar_vereadores(cfg), campo)
        # Datas conhecidas não dispensam a fonte obrigatória.
        self.assertProblema(V.validar_vereadores(self.cfg(inicio="2025-01-01", fonte=None)), "fonte")

    def test_datas_invalidas_e_fora_da_legislatura(self):
        for campo in ("inicio", "fim", "aprovacao"):
            for valor in ("2025-02-30", "2025-2-03", "03/02/2025", "2025-01-01T00:00", "", 20250101):
                with self.subTest(campo=campo, valor=valor):
                    self.assertProblema(V.validar_vereadores(self.cfg(**{campo: valor})), "ISO válida")
            for valor in ("2024-12-31", "2029-01-01"):
                with self.subTest(campo=campo, valor=valor):
                    self.assertProblema(V.validar_vereadores(self.cfg(**{campo: valor})), "fora da legislatura")
        self.assertProblema(V.validar_vereadores(self.cfg(inicio="2025-03-02", fim="2025-03-01")), "anterior")
        self.assertEqual(V.validar_vereadores(self.cfg(inicio="2025-03-02", fim="2025-03-02")), [])
        cfg = self.cfg(inicio="2025-01-01")
        cfg["legislaturas"][1].update(inicio="2025-01-02", fim="2028-12-30")
        self.assertProblema(V.validar_vereadores(cfg), "fora da legislatura")
        cfg["afastamentos"][0].update(inicio="2025-01-02", fim="2028-12-31")
        self.assertProblema(V.validar_vereadores(cfg), "fora da legislatura")

    def test_demais_erros(self):
        casos = [({"legislatura": "1999-2002"}, "inexistente"),
                 ({"siscam": "DESCONHECIDO"}, "nomes conhecidos"),
                 ({"siscam": "Ana Maria"}, "maiúsculas"),
                 ({"fonte": "http://exemplo.org/ata"}, "HTTPS"),
                 ({"ato": "http://exemplo.org/ata"}, "HTTPS"),
                 ({"ato": "https://"}, "HTTPS"),
                 ({"evidencia": "boato"}, "'evidencia'"),
                 ({"evidencia": None}, "'evidencia'"),
                 ({"suplentes": "BIA SUPLENTE"}, "lista"),
                 ({"suplentes": ["DESCONHECIDO"]}, "nomes conhecidos"),
                 ({"suplentes": ["_leia_me"]}, "nomes conhecidos"),
                 ({"suplentes": [None]}, "nomes conhecidos"),
                 ({"nota": ""}, "'nota'"),
                 ({"extra": "x"}, "desconhecidos")]
        for campos, trecho in casos:
            with self.subTest(campos=campos):
                self.assertProblema(V.validar_vereadores(self.cfg(**campos)), trecho)
        self.assertProblema(V.validar_vereadores({**VEREADORES, "afastamentos": {}}), "lista")
        self.assertProblema(V.validar_vereadores({**VEREADORES, "afastamentos": [None]}), "objeto")

    def test_config_versionado_ordenado_e_formato(self):
        raiz = Path(__file__).resolve().parent.parent
        arq = raiz / "config" / "vereadores.json"
        cfg = json.loads(arq.read_text(encoding="utf-8"))
        perfis = json.loads((raiz / "config" / "perfis.json").read_text(encoding="utf-8"))
        self.assertEqual(V.validar_vereadores(cfg, perfis), [])
        self.assertEqual(arq.read_bytes(), (json.dumps(cfg, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
        self.assertEqual(V._memoria_nfc(cfg, "config/vereadores.json"), [])
        itens = cfg["afastamentos"]
        for item in itens:
            chaves = list(item)
            self.assertEqual(chaves[chaves.index("cargo") + 1], "natureza")
            self.assertEqual(item["natureza"], "licenca" if item["cargo"].startswith("Licença") else "cargo")
        self.assertEqual(itens, sorted(itens, key=lambda a: (a["legislatura"], a.get("inicio") or a.get("aprovacao") or "", a["siscam"])))


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


# ------------------------------------------------------------- backend e remoções
class ConfigOpcional:
    """Casos comuns do formato canônico e da leitura dos dois configs opcionais."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.raiz = Path(tmp.name)
        (self.raiz / "config").mkdir()
        self.caminho = self.raiz / "config" / f"{self.nome}.json"

    def escrever(self, dados: object) -> bytes:
        bruto = (json.dumps(dados, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
        self.caminho.write_bytes(bruto)
        return bruto

    def validar(self, dados: object) -> list[str]:
        self.escrever(dados)
        return getattr(V, f"validar_{self.nome}")(self.raiz)

    def test_ausente_so_avisa(self):
        for ambiente in ({}, {"GITHUB_ACTIONS": "true"}):
            with self.subTest(ambiente=ambiente), mock.patch.dict(os.environ, ambiente, clear=True):
                erro = io.StringIO()
                with contextlib.redirect_stderr(erro):
                    self.assertEqual(getattr(V, f"validar_{self.nome}")(self.raiz), [])
                self.assertIn(f"config/{self.nome}.json: arquivo ausente", erro.getvalue())
                self.assertTrue(erro.getvalue().startswith("::warning::" if ambiente else "aviso:"))
                self.assertNotIn("::error::", erro.getvalue())

    def test_formato_canonico_e_nfc(self):
        bruto = self.escrever(self.valido)
        self.assertEqual(getattr(V, f"validar_{self.nome}")(self.raiz), [])
        variantes = [bruto.replace(b"\n", b"\r\n"), bruto.rstrip(b"\n"),
                     (json.dumps(self.valido, ensure_ascii=False, indent=2) + "\n").encode(),
                     (json.dumps(self.valido, ensure_ascii=True, indent=1) + "\n").encode(),
                     b"\xef\xbb\xbf" + bruto]
        for variante in variantes:
            with self.subTest(variante=variante):
                self.caminho.write_bytes(variante)
                self.assertTrue(getattr(V, f"validar_{self.nome}")(self.raiz))
        self.caminho.write_bytes(bruto.replace("ç".encode(), "c\u0327".encode()))
        self.assertProblema(getattr(V, f"validar_{self.nome}")(self.raiz), "normalização NFC")

    def test_json_ilegivel_ou_nao_objeto(self):
        for bruto in (b"[{", b"\xff", b'"\\ud800"'):
            with self.subTest(bruto=bruto):
                self.caminho.write_bytes(bruto)
                self.assertTrue(getattr(V, f"validar_{self.nome}")(self.raiz))
        for dados in (None, [], "texto", 1):
            with self.subTest(dados=dados):
                self.assertProblema(self.validar(dados), "deveria conter um objeto")

    def test_erro_de_leitura(self):
        with mock.patch.object(Path, "read_bytes", side_effect=OSError("leitura indisponível")):
            self.assertProblema(getattr(V, f"validar_{self.nome}")(self.raiz), "não foi possível ler o arquivo")


class TestValidarBackend(ConfigOpcional, Afirmacoes):
    nome = "backend"
    contato = {"tipo": "telefone", "valor": "+55 (21) 1234-5678", "descricao": "Recepção",
               "fonte": "https://exemplo.org/contatos"}
    valido = {**BACKEND, "contatos_institucionais": [contato]}

    def test_validos(self):
        self.assertEqual(self.validar(BACKEND), [])
        cfg = {**self.valido, "api_url": "https://api.exemplo.org:8443/api",
               "origens_cors": ["https://exemplo.org", "https://outro.org:8443", "https://[::1]:8443"],
               "contatos_institucionais": [self.contato, {**self.contato, "tipo": "email", "valor": "camara@exemplo.org"}]}
        self.assertEqual(self.validar(cfg), [])

    def test_campos_exatos(self):
        self.assertProblema(self.validar({**BACKEND, "extra": 1}), "campos esperados")
        for campo in BACKEND:
            cfg = dict(BACKEND)
            del cfg[campo]
            with self.subTest(campo=campo):
                self.assertProblema(self.validar(cfg), "campos esperados")

    def test_api_url(self):
        for valor in ("", "http://exemplo.org", "https://", "https://exemplo.org/", "https://exemplo.org/api/",
                      "https://exemplo.org/a b", "https://exemplo.org:abc", "https://exemplo.org:70000", 1, [], {}):
            with self.subTest(valor=valor):
                self.assertProblema(self.validar({**BACKEND, "api_url": valor}), "'api_url'")

    def test_origens_cors(self):
        for valor in (None, "https://exemplo.org", [], [None], [[]], [1], ["http://exemplo.org"],
                      ["https://"], ["https://exemplo.org/"], ["https://exemplo.org/api"],
                      ["https://exemplo.org?q=1"], ["https://exemplo.org#x"], ["https://exemplo.org?"],
                      ["https://exemplo.org#"], ["https://user@exemplo.org"], ["https://exemplo.org:abc"],
                      ["https://exemplo.org:70000"], ["https://exemplo.org:"], ["https://exemplo.org\n"],
                      ["https://exemplo.org\\caminho"], ["https://[invalido]"], ["https://..."],
                      ["https://-host.org"], ["https://exemplo.org/\x00"], ["https://exemplo.org"] * 2):
            with self.subTest(valor=valor):
                self.assertTrue(self.validar({**BACKEND, "origens_cors": valor}))

    def test_contatos_estrutura(self):
        for valor in (None, {}, "telefone"):
            self.assertProblema(self.validar({**BACKEND, "contatos_institucionais": valor}), "deveria ser uma lista")
        self.assertProblema(self.validar({**BACKEND, "contatos_institucionais": [None]}), "deveria ser um objeto")
        for campo in self.contato:
            contato = dict(self.contato)
            del contato[campo]
            with self.subTest(campo=campo):
                self.assertProblema(self.validar({**BACKEND, "contatos_institucionais": [contato]}), "campos esperados")
        self.assertProblema(self.validar({**BACKEND, "contatos_institucionais": [{**self.contato, "extra": 1}]}),
                            "campos esperados")

    def test_contatos_campos(self):
        casos = [("tipo", valor) for valor in ("fax", None, [], {})]
        casos += [(campo, valor) for campo in ("valor", "descricao") for valor in ("", " ", None, 123, [])]
        casos += [("valor", valor) for valor in ("(21) ABCD-1234", "21.1234.5678", "21\t1234", "21\n1234")]
        casos += [("fonte", valor) for valor in ("http://exemplo.org", "https://", None, "https://exemplo.org/a b")]
        for campo, valor in casos:
            with self.subTest(campo=campo, valor=valor):
                contato = {**self.contato, campo: valor}
                self.assertTrue(self.validar({**BACKEND, "contatos_institucionais": [contato]}))
        for valor in ("camara", "a@", "@exemplo.org", "a@exemplo", "a@@exemplo.org", "a b@exemplo.org", "a@exemplo..org"):
            with self.subTest(email=valor):
                contato = {**self.contato, "tipo": "email", "valor": valor}
                self.assertProblema(self.validar({**BACKEND, "contatos_institucionais": [contato]}), "inválido para email")

    def test_contatos_repetidos(self):
        contatos = [self.contato, {**self.contato, "descricao": "Outra descrição"}]
        self.assertProblema(self.validar({**BACKEND, "contatos_institucionais": contatos}), "(tipo, valor) repetido")


class TestValidarRemocoes(ConfigOpcional, Afirmacoes):
    nome = "remocoes"
    valido = {"remocoes": [REMOCAO]}

    def test_validas(self):
        self.assertEqual(self.validar({"remocoes": []}), [])
        itens = [REMOCAO, {**REMOCAO, "chave": "sessao:Ab-123", "data": date.today().isoformat()}]
        self.assertEqual(self.validar({"remocoes": itens}), [])

    def test_estrutura(self):
        for cfg in ({}, {"remocoes": [], "extra": 1}):
            self.assertProblema(self.validar(cfg), "somente o campo 'remocoes'")
        for valor in (None, {}, "texto"):
            self.assertProblema(self.validar({"remocoes": valor}), "deveria ser uma lista")
        self.assertProblema(self.validar({"remocoes": [None]}), "deveria ser um objeto")
        for campo in REMOCAO:
            item = dict(REMOCAO)
            del item[campo]
            with self.subTest(campo=campo):
                self.assertProblema(self.validar({"remocoes": [item]}), "campos esperados")
        self.assertProblema(self.validar({"remocoes": [{**REMOCAO, "extra": 1}]}), "campos esperados")

    def test_campos_invalidos(self):
        casos = {
            "chave": (None, [], 123, "", "outro:123", "siscam:", "sessao:1_2", "siscam:1/2", "siscam:á", "siscam:123\n"),
            "sha256": (None, [], 123, "a" * 63, "a" * 65, "A" * 64, "g" * 64, "a" * 64 + "\n"),
            "motivo": (None, [], 123, "", " "),
            "fonte": (None, [], "", "http://exemplo.org", "https://", "https://exemplo.org/a b"),
            "data": (None, [], 20240229, "", "2024", "29/02/2024", "2024-2-29", "2023-02-29", "2024-02-30",
                     "2024-02-29T00:00", "2024-02-29\n", (date.today() + timedelta(days=1)).isoformat()),
        }
        for campo, valores in casos.items():
            for valor in valores:
                with self.subTest(campo=campo, valor=valor):
                    problemas = self.validar({"remocoes": [{**REMOCAO, campo: valor}]})
                    self.assertProblema(problemas, f"'{campo}'")

    def test_chave_repetida(self):
        self.assertProblema(self.validar({"remocoes": [REMOCAO, {**REMOCAO, "sha256": "c" * 64}]}), "repetida")

    def test_ordem_por_data_depois_chave(self):
        itens = [REMOCAO, {**REMOCAO, "chave": "siscam:124"},
                 {**REMOCAO, "chave": "sessao:1", "data": "2024-03-01"}]
        self.assertEqual(self.validar({"remocoes": itens}), [])
        for fora_de_ordem in ([itens[1], itens[0], itens[2]], [itens[2], itens[0], itens[1]]):
            self.assertProblema(self.validar({"remocoes": fora_de_ordem}), "fora de ordem por data e chave")


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
        for nome, dados in (("backend", BACKEND), ("remocoes", {"remocoes": []})):
            (raiz / "config" / f"{nome}.json").write_bytes(
                (json.dumps(dados, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
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

    def test_main_configs_backend_e_remocoes_ausentes_so_avisam(self):
        raiz = self.montar_raiz()
        for nome in ("backend", "remocoes"):
            (raiz / "config" / f"{nome}.json").unlink()
        codigo, erro, _ = self.rodar_main(raiz, {})
        self.assertEqual(codigo, 0)
        self.assertIn("config/backend.json: arquivo ausente", erro)
        self.assertIn("config/remocoes.json: arquivo ausente", erro)

    def test_validar_tudo_inclui_backend_e_remocoes(self):
        raiz = self.montar_raiz()
        for nome in ("backend", "remocoes"):
            (raiz / "config" / f"{nome}.json").write_bytes(b"{}\n")
        problemas = V.validar_tudo(raiz)
        self.assertProblema(problemas, "config/backend.json: campos esperados")
        self.assertProblema(problemas, "config/remocoes.json: esperado somente")

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
