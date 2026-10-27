"""Testes da verificação semanal dos vereadores (coletor/vereadores_semanal.py), offline.

Uso: python -m unittest tests.test_vereadores_semanal  (ou pytest tests/test_vereadores_semanal.py)
"""
from __future__ import annotations

import contextlib
import datetime as dt
import email.message
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from coletor import vereadores_semanal as semanal

HOJE = dt.date(2026, 3, 1)
CONFIG = {
    "legislaturas": [
        {"id": "2021-2024", "inicio": "2021-01-01", "fim": "2024-12-31", "fonte": "https://exemplo.org/2020",
         "eleitos": [{"nome": "Ana", "siscam": "ANA MARIA TESTE", "partido": "PT"},
                     {"nome": "Eva", "siscam": "EVA ANTIGA", "partido": "PV"}]},
        {"id": "2025-2028", "inicio": "2025-01-01", "fim": "2028-12-31", "fonte": "https://exemplo.org/2024",
         "eleitos": [{"nome": "Ana", "siscam": "ANA MARIA TESTE", "partido": "PT"},
                     {"nome": "Bruno", "siscam": "BRUNO TESTE", "partido": "PSOL"}]},
    ],
    "afastamentos": [],
    "nao_vereador": ["PODER EXECUTIVO"],
    "apelidos": {"_leia_me": "x", "CARLOS SUPLENTE DA SILVA": "Carlos"},
}
PERFIS = {"vereadores": {
    "ANA MARIA TESTE": {"mandatos": {"2025-2028": {"partido": "PT", "situacao": "eleita", "fontes": []}},
                        "eleicoes": [], "camara": None, "site": None, "redes": []},
    "BRUNO TESTE": {"mandatos": {"2025-2028": {"partido": "PSOL", "situacao": "eleito", "fontes": []}},
                    "eleicoes": [], "camara": None, "site": None, "redes": []},
}}
ANA = {"id": 1, "nome": "ANA MARIA TESTE", "origem": "Vereador", "papel": "Autor"}
CARLOS = {"id": 3, "nome": "CARLOS SUPLENTE DA SILVA", "origem": "Vereador", "papel": "Co-Autor"}
EXECUTIVO = {"id": 99, "nome": "PODER EXECUTIVO", "origem": "Executivo", "papel": "Autor"}
PLS = [
    {"ano": 2025, "data": "2025-03-10", "id": 500, "numero": "10/2025", "autoria": [ANA, CARLOS]},
    {"ano": 2025, "data": "2025-04-01", "id": 501, "numero": "11/2025", "autoria": [EXECUTIVO]},
]
INDICACOES = [
    {"ano": 2025, "data": "2025-05-02", "id": 600, "numero": "5/2025", "tipo": "indicacao",
     "autores": [{"id": 3, "nome": "CARLOS SUPLENTE DA SILVA"}],
     "url": "https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento=600"},
]
PL_ANTIGO = [{"ano": 2022, "data": "2022-03-10", "id": 400, "numero": "1/2022",
              "autoria": [{"id": 9, "nome": "EVA ANTIGA", "origem": "Vereador", "papel": "Autor"}]}]


def _sessao(id_, data, frequencia):
    return {"ano": int(data[:4]), "data": data, "hora": "16:00", "id": id_, "tipo": "ordinaria",
            "frequencia": [{"momento": "Abertura - 16:10", "nome": n, "situacao": s} for n, s in frequencia],
            "votacoes": []}


SESSOES = [
    _sessao(7001, "2026-02-24", [("ANA MARIA TESTE", "Presença"), ("BRUNO TESTE", "Licença")]),
    _sessao(7002, "2026-02-26", [("Ana Maria Teste", "Presença"), ("BRUNO TESTE", "Licença")]),
]


def _gravar(caminho: Path, dados) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")


class Resposta:
    def __init__(self, corpo: str):
        self._corpo = corpo.encode("utf-8")
        self.headers = email.message.Message()
        self.headers["Content-Type"] = "text/html; charset=utf-8"

    def read(self, n: int = -1) -> bytes:
        return self._corpo

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.raiz = Path(self._tmp.name)
        self.cfg = json.loads(json.dumps(CONFIG))
        self.perfis = json.loads(json.dumps(PERFIS))
        _gravar(self.raiz / "data" / "proposicoes" / "2025.json", PLS)
        _gravar(self.raiz / "data" / "proposicoes" / "2022.json", PL_ANTIGO)
        _gravar(self.raiz / "data" / "documentos" / "indicacao" / "2025.json", INDICACOES)
        _gravar(self.raiz / "data" / "sessoes" / "2026.json", SESSOES)
        self.gravar_config()

    def tearDown(self):
        self._tmp.cleanup()

    def gravar_config(self):
        _gravar(self.raiz / "config" / "vereadores.json", self.cfg)
        _gravar(self.raiz / "config" / "perfis.json", self.perfis)

    def gerar(self, com_rede: bool = False) -> tuple[str, int]:
        return semanal.gerar(self.raiz, HOJE, com_rede)


class TestDeteccoes(Base):
    def test_suplente_novo(self):
        texto, achados = self.gerar()
        self.assertIn("**CARLOS SUPLENTE DA SILVA**: 2 proposição(ões) como autor", texto)
        self.assertIn("[Indicação 5/2025](https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento=600)", texto)
        self.assertIn("[PL 10/2025](https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento=500)", texto)
        self.assertIn("tem apelido em `config/vereadores.json`", texto)
        self.assertNotIn("**ANA MARIA TESTE**", texto)
        self.assertNotIn("PODER EXECUTIVO", texto)
        self.assertNotIn("EVA ANTIGA", texto)  # só a legislatura atual
        self.assertEqual(achados, 2)  # suplente e licença
        self.assertTrue(texto.endswith("<!-- achados: 2 -->\n"))

    def test_licenca_sem_afastamento(self):
        texto, _ = self.gerar()
        self.assertIn("**Bruno** (`BRUNO TESTE`): licença em 2 sessão(ões)", texto)
        self.assertIn("[24/02/2026](https://consultaniteroi.siscam.com.br/DetalhesSessao.aspx?IdDocumento=7001)", texto)

    def test_sem_diferencas(self):
        self.cfg["afastamentos"].append({"siscam": "BRUNO TESTE", "legislatura": "2025-2028", "cargo": "Secretário",
                                         "fonte": "https://exemplo.org/afastamento"})
        self.perfis["vereadores"]["CARLOS SUPLENTE DA SILVA"] = {
            "mandatos": {"2025-2028": {"partido": "PT", "situacao": "suplente", "fontes": []}},
            "eleicoes": [], "camara": None, "site": None, "redes": []}
        self.gravar_config()
        texto, achados = self.gerar()
        self.assertEqual(achados, 0)
        self.assertIn(semanal.SEM_DIFERENCAS, texto)
        self.assertIn("<!-- achados: 0 -->", texto)
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            codigo = semanal.main(["--raiz", str(self.raiz), "--hoje", HOJE.isoformat(), "--saida", str(self.raiz / "r.md")])
        self.assertEqual(codigo, 0)
        self.assertEqual(saida.getvalue().strip(), "sem diferenças")
        self.assertEqual((self.raiz / "r.md").read_text(encoding="utf-8"), texto)

    def test_sem_sessoes_nem_perfis(self):
        (self.raiz / "data" / "sessoes" / "2026.json").unlink()
        (self.raiz / "config" / "perfis.json").unlink()
        texto, achados = self.gerar()
        self.assertIn("Nenhuma licença sem registro nas sessões de 2026.", texto)
        self.assertIn("**CARLOS SUPLENTE DA SILVA**", texto)
        self.assertEqual(achados, 1)


class TestCamara(Base):
    def test_indisponivel(self):
        erro = urllib.error.HTTPError(semanal.URL_CAMARA, 503, "Service Unavailable", None, None)
        with mock.patch("coletor.vereadores_semanal.urllib.request.urlopen", side_effect=erro):
            texto, achados = self.gerar(com_rede=True)
        self.assertIn("indisponível (HTTP 503)", texto)
        self.assertEqual(achados, 2)  # a indisponibilidade não conta como achado
        saida = io.StringIO()
        with mock.patch("coletor.vereadores_semanal.urllib.request.urlopen", side_effect=erro), \
                contextlib.redirect_stdout(saida):
            codigo = semanal.main(["--raiz", str(self.raiz), "--hoje", HOJE.isoformat(), "--com-rede"])
        self.assertEqual(codigo, 0)
        self.assertIn("indisponível", saida.getvalue())

    def test_sem_rede_nao_verifica(self):
        with mock.patch("coletor.vereadores_semanal.urllib.request.urlopen", side_effect=AssertionError("rede")):
            texto, _ = self.gerar()
        self.assertIn("Não verificado nesta execução", texto)

    def test_estrutura_desconhecida(self):
        with mock.patch("coletor.vereadores_semanal.urllib.request.urlopen", return_value=Resposta("<p>Manutenção</p>")):
            texto, _ = self.gerar(com_rede=True)
        self.assertIn("Estrutura do [site da Câmara]", texto)

    def test_diferenca_de_partido(self):
        outros = "".join(f"<li><h3>Vereador Exemplo {letra}</h3><span>PSD</span></li>" for letra in "CDEFGHIJK")
        corpo = (f"<html><body><ul><li><h3>Ana</h3><span>MDB</span></li>"
                 f"<li><a>Bruno (PSOL)</a></li>{outros}</ul><script>var x = 'Ana (PT)';</script></body></html>")
        with mock.patch("coletor.vereadores_semanal.urllib.request.urlopen", return_value=Resposta(corpo)):
            texto, achados = self.gerar(com_rede=True)
        self.assertIn("**Ana** (`ANA MARIA TESTE`): site informa **MDB**; perfil/configuração informa **PT**.", texto)
        self.assertNotIn("**Bruno** (`BRUNO TESTE`): site", texto)
        self.assertIn("Vereador Exemplo C", texto)  # sem correspondência, só informativo
        self.assertEqual(achados, 3)


if __name__ == "__main__":
    unittest.main()
