"""Testes do formato compacto dos arquivos de dados (coletor/arquivos.py).

Uso: python -m unittest tests.test_arquivos  (ou pytest tests/test_arquivos.py)
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from coletor import arquivos

# ------------------------------------------------------------------------ exemplos
PROJETOS = [
    {
        "ano": 2026,
        "autoria": [{"id": 275, "nome": "Fulano de Tal", "origem": "Vereador", "papel": "Autor"}],
        "ementa": "DISPÕE SOBRE A DOAÇÃO DE RAÇÃO EM SUBSTITUIÇÃO AO ALIMENTO NÃO PERECÍVEL.",
        "id": 290536,
        "lei": None,
        "numero": "1/2026",
        "situacao": "ENCAMINHADO ÀS COMISSÕES",
        "tramitacoes": [
            {"seq": 1, "resultado": "Lido na Sessão Plenária", "data_resposta": "2026-02-25"},
            {"seq": 2, "resultado": "", "data_resposta": None, "observacao": "linha 1\nlinha 2"},
        ],
    },
    {
        "ano": 2026,
        "autoria": [],
        "ementa": "INSTITUI A SEMANA MUNICIPAL DE CONSCIENTIZAÇÃO.",
        "id": 290537,
        "lei": {"numero": 4137, "tipo": "sancionada", "veto_parcial": False},
        "numero": "2/2026",
        "situacao": "PUBLICADO",
        "tramitacoes": [],
    },
]

CACHE = {
    "125350": {"alertas": [], "categoria": "politica_publica", "impacto": 2, "publico": "pessoas em situação de rua"},
    "125349": {"alertas": [{"confianca": 0.8, "rotulo": "apelo_populista"}], "categoria": "outra", "impacto": None},
}


class _ComPasta(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.pasta = Path(self._temp.name)

    def tearDown(self) -> None:
        self._temp.cleanup()

    def ler(self, nome: str) -> str:
        return (self.pasta / nome).read_bytes().decode("utf-8")


# --------------------------------------------------------------------------- lista
class TestSalvarLista(_ComPasta):
    def test_ida_e_volta(self) -> None:
        arquivos.salvar_lista(self.pasta / "2026.json", PROJETOS)
        self.assertEqual(json.loads(self.ler("2026.json")), PROJETOS)

    def test_um_registro_por_linha(self) -> None:
        arquivos.salvar_lista(self.pasta / "2026.json", PROJETOS)
        linhas = self.ler("2026.json").split("\n")
        self.assertEqual(linhas[0], "[")
        self.assertEqual(linhas[-2:], ["]", ""])
        corpo = linhas[1:-2]
        self.assertEqual(len(corpo), len(PROJETOS))
        for i, (linha, esperado) in enumerate(zip(corpo, PROJETOS)):
            ultima = i == len(PROJETOS) - 1
            self.assertEqual(linha.endswith(","), not ultima)
            self.assertEqual(json.loads(linha.removesuffix(",")), esperado)
            self.assertNotIn('": ', linha)  # separadores compactos, sem espaço

    def test_formato_exato(self) -> None:
        esperado = "[\n" + ",\n".join(
            json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for r in PROJETOS
        ) + "\n]\n"
        arquivos.salvar_lista(self.pasta / "2026.json", PROJETOS)
        self.assertEqual(self.ler("2026.json"), esperado)

    def test_lista_vazia(self) -> None:
        arquivos.salvar_lista(self.pasta / "vazio.json", [])
        self.assertEqual(self.ler("vazio.json"), "[]\n")
        self.assertEqual(json.loads(self.ler("vazio.json")), [])

    def test_unicode_sem_escape(self) -> None:
        arquivos.salvar_lista(self.pasta / "2026.json", [{"ementa": "Ação de proteção à criança"}])
        bruto = (self.pasta / "2026.json").read_bytes()
        self.assertIn("Ação de proteção à criança".encode("utf-8"), bruto)
        self.assertNotIn(b"\\u00", bruto)

    def test_quebra_de_linha_final_e_lf(self) -> None:
        arquivos.salvar_lista(self.pasta / "2026.json", PROJETOS)
        bruto = (self.pasta / "2026.json").read_bytes()
        self.assertTrue(bruto.endswith(b"]\n"))
        self.assertNotIn(b"\r\n", bruto)

    def test_deterministico(self) -> None:
        invertidos = [dict(reversed(list(p.items()))) for p in PROJETOS]
        arquivos.salvar_lista(self.pasta / "a.json", PROJETOS)
        arquivos.salvar_lista(self.pasta / "b.json", invertidos)
        arquivos.salvar_lista(self.pasta / "c.json", PROJETOS)
        self.assertEqual(self.ler("a.json"), self.ler("b.json"))
        self.assertEqual(self.ler("a.json"), self.ler("c.json"))

    def test_preserva_ordem_da_lista(self) -> None:
        arquivos.salvar_lista(self.pasta / "2026.json", list(reversed(PROJETOS)))
        self.assertEqual([p["id"] for p in json.loads(self.ler("2026.json"))], [290537, 290536])


# ---------------------------------------------------------------------------- mapa
class TestSalvarMapa(_ComPasta):
    def test_ida_e_volta(self) -> None:
        arquivos.salvar_mapa(self.pasta / "cache.json", CACHE)
        self.assertEqual(json.loads(self.ler("cache.json")), CACHE)

    def test_uma_chave_por_linha_ordenada(self) -> None:
        arquivos.salvar_mapa(self.pasta / "cache.json", CACHE)
        linhas = self.ler("cache.json").split("\n")
        self.assertEqual(linhas[0], "{")
        self.assertEqual(linhas[-2:], ["}", ""])
        corpo = linhas[1:-2]
        self.assertEqual(len(corpo), len(CACHE))
        chaves = []
        for linha in corpo:
            par = json.loads("{" + linha.removesuffix(",") + "}")
            self.assertEqual(len(par), 1)
            (chave, valor), = par.items()
            self.assertEqual(valor, CACHE[chave])
            chaves.append(chave)
        self.assertEqual(chaves, sorted(CACHE))
        self.assertTrue(corpo[0].startswith('"125349":{'))

    def test_mapa_vazio(self) -> None:
        arquivos.salvar_mapa(self.pasta / "vazio.json", {})
        self.assertEqual(self.ler("vazio.json"), "{}\n")
        self.assertEqual(json.loads(self.ler("vazio.json")), {})

    def test_unicode_sem_escape(self) -> None:
        arquivos.salvar_mapa(self.pasta / "cache.json", {"ação": "não"})
        self.assertEqual(self.ler("cache.json"), '{\n"ação":"não"\n}\n')

    def test_deterministico(self) -> None:
        invertido = dict(reversed(list(CACHE.items())))
        arquivos.salvar_mapa(self.pasta / "a.json", CACHE)
        arquivos.salvar_mapa(self.pasta / "b.json", invertido)
        self.assertEqual(self.ler("a.json"), self.ler("b.json"))

    def test_chaves_inteiras_viram_texto(self) -> None:
        arquivos.salvar_mapa(self.pasta / "cache.json", {2: "b", 10: "a"})
        self.assertEqual(json.loads(self.ler("cache.json")), {"2": "b", "10": "a"})

    def test_chaves_duplicadas_falham(self) -> None:
        with self.assertRaises(ValueError):
            arquivos.salvar_mapa(self.pasta / "cache.json", {1: "a", "1": "b"})
        self.assertEqual(os.listdir(self.pasta), [])


# ---------------------------------------------------------------------------- json
class TestSalvarJson(_ComPasta):
    def test_indentado_e_ordenado(self) -> None:
        meta = {"coleta": {"em": "2026-10-22T13:47:46+00:00", "anos": {2021: {"total": 448}}}, "classificacao": {}}
        arquivos.salvar_json(self.pasta / "meta.json", meta)
        texto = self.ler("meta.json")
        self.assertEqual(texto, json.dumps(meta, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
        self.assertTrue(texto.endswith("}\n"))
        self.assertEqual(json.loads(texto)["coleta"]["anos"], {"2021": {"total": 448}})


# ------------------------------------------------------------------------ gravação
class TestGravacaoAtomica(_ComPasta):
    def test_nao_deixa_temporario(self) -> None:
        arquivos.salvar_lista(self.pasta / "2026.json", PROJETOS)
        arquivos.salvar_mapa(self.pasta / "cache.json", CACHE)
        arquivos.salvar_json(self.pasta / "meta.json", {"a": 1})
        arquivos.salvar_lista(self.pasta / "2026.json", PROJETOS[:1])  # sobrescreve
        self.assertEqual(sorted(os.listdir(self.pasta)), ["2026.json", "cache.json", "meta.json"])

    def test_falha_preserva_original_e_apaga_temporario(self) -> None:
        arquivos.salvar_lista(self.pasta / "2026.json", PROJETOS)
        antes = self.ler("2026.json")
        with mock.patch.object(arquivos.os, "replace", side_effect=OSError("disco cheio")):
            with self.assertRaises(OSError):
                arquivos.salvar_lista(self.pasta / "2026.json", PROJETOS[:1])
        self.assertEqual(self.ler("2026.json"), antes)
        self.assertEqual(os.listdir(self.pasta), ["2026.json"])

    def test_cria_pasta(self) -> None:
        arquivos.salvar_lista(self.pasta / "data" / "proposicoes" / "2026.json", [])
        self.assertEqual(self.ler("data/proposicoes/2026.json"), "[]\n")

    def test_troca_bloqueada_no_windows_e_tentada_de_novo(self) -> None:
        arquivos.salvar_lista(self.pasta / "2026.json", PROJETOS)
        real = os.replace
        tentativas = []

        def replace(origem, destino):
            tentativas.append(destino)
            if len(tentativas) <= 2:  # destino aberto por outro processo (antivírus, indexador)
                raise PermissionError(13, "Acesso negado", str(destino))
            return real(origem, destino)

        with mock.patch.object(arquivos.os, "replace", side_effect=replace), \
                mock.patch.object(arquivos.time, "sleep") as espera:
            arquivos.salvar_lista(self.pasta / "2026.json", PROJETOS[:1])
        self.assertEqual(len(tentativas), 3)
        self.assertEqual(espera.call_count, 2)
        self.assertEqual(json.loads(self.ler("2026.json")), PROJETOS[:1])
        self.assertEqual(os.listdir(self.pasta), ["2026.json"])

    def test_troca_bloqueada_sem_fim_desiste_e_preserva_original(self) -> None:
        arquivos.salvar_lista(self.pasta / "2026.json", PROJETOS)
        antes = self.ler("2026.json")
        with mock.patch.object(arquivos.os, "replace", side_effect=PermissionError(13, "Acesso negado")) as troca, \
                mock.patch.object(arquivos.time, "sleep") as espera:
            with self.assertRaises(PermissionError):
                arquivos.salvar_lista(self.pasta / "2026.json", PROJETOS[:1])
        self.assertEqual(troca.call_count, arquivos.TENTATIVAS_TROCA)
        self.assertEqual(espera.call_count, arquivos.TENTATIVAS_TROCA - 1)
        self.assertEqual(self.ler("2026.json"), antes)
        self.assertEqual(os.listdir(self.pasta), ["2026.json"])

    def test_outros_erros_da_troca_nao_sao_repetidos(self) -> None:
        with mock.patch.object(arquivos.os, "replace", side_effect=OSError(28, "Disco cheio")) as troca, \
                mock.patch.object(arquivos.time, "sleep") as espera:
            with self.assertRaises(OSError):
                arquivos.salvar_lista(self.pasta / "2026.json", PROJETOS)
        self.assertEqual((troca.call_count, espera.call_count), (1, 0))
        self.assertEqual(os.listdir(self.pasta), [])


# -------------------------------------------------------------------- reformatação
class TestReformatar(_ComPasta):
    def preparar_antigo(self) -> tuple[Path, Path]:
        dir_dados = self.pasta / "proposicoes"
        dir_dados.mkdir()
        cache = self.pasta / "classificacao_ia.json"
        antigo = lambda obj: json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
        (dir_dados / "2026.json").write_text(antigo(PROJETOS), encoding="utf-8", newline="\n")
        (dir_dados / "2025.json").write_text(antigo([]), encoding="utf-8", newline="\n")
        cache.write_text(antigo(CACHE), encoding="utf-8", newline="\n")
        return dir_dados, cache

    def test_regrava_com_mesmo_conteudo(self) -> None:
        dir_dados, cache = self.preparar_antigo()
        relatorio = arquivos.reformatar(dir_dados, cache)
        self.assertEqual(len(relatorio), 3)
        self.assertEqual(json.loads((dir_dados / "2026.json").read_text(encoding="utf-8")), PROJETOS)
        self.assertEqual(json.loads((dir_dados / "2025.json").read_text(encoding="utf-8")), [])
        self.assertEqual(json.loads(cache.read_text(encoding="utf-8")), CACHE)
        self.assertEqual((dir_dados / "2026.json").read_text(encoding="utf-8"), arquivos.texto_lista(PROJETOS))
        self.assertEqual(cache.read_text(encoding="utf-8"), arquivos.texto_mapa(CACHE))
        por_nome = {r["arquivo"].name: r for r in relatorio}
        self.assertLess(por_nome["2026.json"]["bytes_depois"], por_nome["2026.json"]["bytes_antes"])
        self.assertEqual(por_nome["2026.json"]["linhas_depois"], len(PROJETOS) + 2)
        self.assertEqual(sorted(os.listdir(dir_dados)), ["2025.json", "2026.json"])

    def test_idempotente(self) -> None:
        dir_dados, cache = self.preparar_antigo()
        arquivos.reformatar(dir_dados, cache)
        primeira = (dir_dados / "2026.json").read_bytes(), cache.read_bytes()
        arquivos.reformatar(dir_dados, cache)
        self.assertEqual(((dir_dados / "2026.json").read_bytes(), cache.read_bytes()), primeira)

    def test_diferenca_aborta_sem_gravar(self) -> None:
        dir_dados, cache = self.preparar_antigo()
        originais = {p: p.read_bytes() for p in [*dir_dados.iterdir(), cache]}
        with mock.patch.object(arquivos, "texto_mapa", return_value="{}\n"):
            with self.assertRaises(ValueError):
                arquivos.reformatar(dir_dados, cache)
        self.assertEqual({p: p.read_bytes() for p in originais}, originais)

    def test_tipo_inesperado_aborta(self) -> None:
        dir_dados, cache = self.preparar_antigo()
        (dir_dados / "2024.json").write_text('{"nao": "lista"}\n', encoding="utf-8")
        with self.assertRaises(ValueError):
            arquivos.reformatar(dir_dados, cache)
        self.assertEqual(json.loads(cache.read_text(encoding="utf-8")), CACHE)
        self.assertIn(b"\n ", cache.read_bytes())  # continua no formato antigo


if __name__ == "__main__":
    unittest.main()
