"""Testes do importador de dados abertos do TSE (coletor/tse.py), offline.

Os zips são sintéticos, criados numa pasta temporária com CSVs em latin-1 e ponto e vírgula.
Uso: python -m unittest tests.test_tse  (ou pytest tests/test_tse.py)
"""
from __future__ import annotations

import contextlib
import copy
import csv
import email.message
import io
import json
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest import mock

from coletor import tse

# ---- dados sintéticos ---------------------------------------------------------------
CAB_CAND = ["DT_GERACAO", "NM_UE", "DS_CARGO", "SQ_CANDIDATO", "NM_CANDIDATO", "NM_URNA_CANDIDATO",
            "SG_PARTIDO", "NR_CANDIDATO", "DS_SIT_TOT_TURNO", "SG_UF", "NR_TURNO"]
CAB_VOT = ["NM_MUNICIPIO", "DS_CARGO", "SQ_CANDIDATO", "QT_VOTOS_NOMINAIS", "DS_SIT_TOT_TURNO", "NR_TURNO"]
CAB_REDES = ["SQ_CANDIDATO", "NR_ORDEM_REDE_SOCIAL", "DS_URL"]


def _cand(ue, cargo, sq, nome, partido, situacao, uf="RJ", turno="1", urna="URNA"):
    return ["01/10/2024", ue, cargo, sq, nome, urna, partido, "10", situacao, uf, turno]


CANDIDATOS_2024 = {
    "consulta_cand_2024_RJ.csv": [
        CAB_CAND,
        _cand("NITERÓI", "VEREADOR", "1001", "ANA MARIA TESTE", "PC do B", "ELEITO POR QP"),
        _cand("MARICÁ", "VEREADOR", "1002", "ANA MARIA TESTE", "PT", "NÃO ELEITO"),  # homônimo
        _cand("NITERÓI", "VEREADOR", "1003", "BRUNO TESTE", "UNIÃO", "#NULO"),
    ],
    # outras UFs e o arquivo nacional consolidado não são lidos
    "consulta_cand_2024_SP.csv": [CAB_CAND, _cand("NITERÓI", "VEREADOR", "9001", "ANA MARIA TESTE", "PL", "ELEITO", uf="SP")],
    "consulta_cand_2024_BRASIL.csv": [CAB_CAND, _cand("NITERÓI", "VEREADOR", "9002", "ANA MARIA TESTE", "PL", "ELEITO")],
}
CANDIDATOS_2022 = {
    "consulta_cand_2022_RJ.csv": [
        CAB_CAND,
        _cand("RIO DE JANEIRO", "DEPUTADO ESTADUAL", "2001", "ANA MARIA TESTE", "PC do B", "SUPLENTE"),
        _cand("RIO DE JANEIRO", "DEPUTADO ESTADUAL", "2002", "CARLOS AMBIGUO", "PODE", "NÃO ELEITO"),
        _cand("RIO DE JANEIRO", "DEPUTADO FEDERAL", "2003", "CARLOS AMBIGUO", "AVANTE", "NÃO ELEITO"),
        _cand("RIO DE JANEIRO", "VICE-GOVERNADOR", "2004", "BRUNO TESTE", "SOLIDARIEDADE", "2º TURNO", turno="1"),
        _cand("RIO DE JANEIRO", "VICE-GOVERNADOR", "2004", "BRUNO TESTE", "SOLIDARIEDADE", "NÃO ELEITO", turno="2"),
    ],
    "consulta_cand_2022_SP.csv": [CAB_CAND, _cand("SÃO PAULO", "DEPUTADO ESTADUAL", "9003", "ANA MARIA TESTE", "PL", "ELEITO", uf="SP")],
}
VOTACAO_2024 = {
    "votacao_candidato_munzona_2024_RJ.csv": [
        CAB_VOT,
        ["NITERÓI", "VEREADOR", "1001", "100", "ELEITO POR QP", "1"],
        ["NITERÓI", "VEREADOR", "1001", "50", "ELEITO POR QP", "1"],
        ["MARICÁ", "VEREADOR", "1002", "999", "NÃO ELEITO", "1"],
    ],
}
VOTACAO_2022 = {
    "votacao_candidato_munzona_2022_RJ.csv": [
        CAB_VOT,
        ["NITERÓI", "DEPUTADO ESTADUAL", "2001", "300", "SUPLENTE", "1"],
        ["SÃO GONÇALO", "DEPUTADO ESTADUAL", "2001", "200", "SUPLENTE", "1"],
        ["RIO DE JANEIRO", "DEPUTADO ESTADUAL", "2001", "500", "SUPLENTE", "1"],
        ["NITERÓI", "VICE-GOVERNADOR", "2004", "7", "2º TURNO", "1"],
        ["NITERÓI", "VICE-GOVERNADOR", "2004", "3", "NÃO ELEITO", "2"],
        ["NITERÓI", "VICE-GOVERNADOR", "2004", "#NULO", "NÃO ELEITO", "2"],
    ],
}
REDES_2024 = {
    "rede_social_candidato_2024_RJ.csv": [
        CAB_REDES,
        ["1001", "1", "instagram.com/ana.teste/?igsh=abc123"],
        ["1001", "2", "https://www.facebook.com/anateste/"],
        ["1001", "3", "http://twitter.com/anateste?s=20"],
        ["1001", "4", "https://www.anateste.com.br/"],
        ["1001", "5", "@anateste"],
        ["1001", "6", "https://instagram.com/ana.teste"],  # repetida depois da normalização
    ],
}
REDES_2022 = {"rede_social_candidato_2022_RJ.csv": [CAB_REDES, ["2001", "1", "https://www.youtube.com/@anateste"]]}

CONFIG = {
    "legislaturas": [
        {"id": "2021-2024", "inicio": "2021-01-01", "fim": "2024-12-31", "fonte": "https://exemplo.org/2020",
         "eleitos": [{"nome": "Ana", "siscam": "ANA MARIA TESTE", "partido": "PCdoB"}]},
        {"id": "2025-2028", "inicio": "2025-01-01", "fim": "2028-12-31", "fonte": "https://exemplo.org/2024",
         "eleitos": [{"nome": "Ana", "siscam": "ANA MARIA TESTE", "partido": "PCdoB"},
                     {"nome": "Bruno", "siscam": "BRUNO TESTE", "partido": "União Brasil"},
                     {"nome": "Diego", "siscam": "DIEGO NOVO", "partido": "PT"}]},
    ],
    "afastamentos": [],
    "nao_vereador": [],
    "apelidos": {},
}
FONTE_WIKI = {"titulo": "Wiki", "url": "https://pt.wikipedia.org/wiki/Teste"}
PERFIS = {
    "_leia_me": "teste",
    "fonte_padrao": FONTE_WIKI,
    "vereadores": {
        "ANA MARIA TESTE": {
            "mandatos": {"2025-2028": {"partido": "PCdoB", "situacao": "eleita", "fontes": [FONTE_WIKI]}},
            "eleicoes": [{"ano": 2016, "cargo": "Vereador", "uf": "RJ", "partido": "PCdoB", "votos": 10,
                          "resultado": "Suplente", "fonte": FONTE_WIKI}],
            "camara": None,
            "site": None,
            "redes": [
                {"rede": "instagram", "url": "https://instagram.com/velho", "fonte": "https://dadosabertos.tse.jus.br/dataset/candidatos-2020"},
                {"rede": "linkedin", "url": "https://linkedin.com/in/ana", "fonte": "https://ana.exemplo.org/contato"},
            ],
        },
        "BRUNO TESTE": {
            "mandatos": {"2025-2028": {"partido": "União Brasil", "situacao": "eleito", "fontes": [FONTE_WIKI]}},
            "eleicoes": [],
            "camara": None,
            "site": None,
            "redes": [],
        },
        "CARLOS AMBIGUO": {
            "mandatos": {},
            "eleicoes": [{"ano": 2022, "cargo": "Deputado Estadual", "uf": "RJ", "partido": "Podemos", "votos": None,
                          "resultado": "Não eleito", "fonte": FONTE_WIKI}],
            "camara": None,
            "site": None,
            "redes": [],
        },
    },
}


def _zip(caminho: Path, membros: dict[str, list[list[str]]]) -> None:
    with zipfile.ZipFile(caminho, "w") as arquivo:
        for nome, linhas in membros.items():
            buffer = io.StringIO()
            csv.writer(buffer, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\r\n").writerows(linhas)
            arquivo.writestr(nome, buffer.getvalue().encode("latin-1"))
        arquivo.writestr("leiame.pdf", b"%PDF")


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.cache = self.dir / "cache"
        self.cache.mkdir()
        for nome, membros in (
            ("consulta_cand_2024.zip", CANDIDATOS_2024), ("consulta_cand_2022.zip", CANDIDATOS_2022),
            ("votacao_candidato_munzona_2024.zip", VOTACAO_2024), ("votacao_candidato_munzona_2022.zip", VOTACAO_2022),
            ("rede_social_candidato_2024.zip", REDES_2024), ("rede_social_candidato_2022.zip", REDES_2022),
        ):
            _zip(self.cache / nome, membros)
        self.config = self.dir / "vereadores.json"
        self.config.write_text(json.dumps(CONFIG, ensure_ascii=False), encoding="utf-8")
        self.perfis = self.dir / "perfis.json"
        self.perfis.write_text(tse.texto_perfis(copy.deepcopy(PERFIS)), encoding="utf-8", newline="\n")

    def tearDown(self):
        self._tmp.cleanup()

    def rodar(self, *extra: str) -> tuple[int, str, str]:
        saida, erros = io.StringIO(), io.StringIO()
        argv = ["--anos", "2022,2024", "--cache", str(self.cache), "--sem-download",
                "--perfis", str(self.perfis), "--vereadores", str(self.config), *extra]
        with mock.patch("coletor.tse.urllib.request.urlopen", side_effect=AssertionError("rede proibida")), \
                contextlib.redirect_stdout(saida), contextlib.redirect_stderr(erros):
            codigo = tse.main(argv)
        return codigo, saida.getvalue(), erros.getvalue()

    def resultado(self) -> dict:
        return json.loads(self.perfis.read_text(encoding="utf-8"))


# ---- funções puras ------------------------------------------------------------------
class TestNormalizacao(unittest.TestCase):
    def test_nome_sem_acentos_e_espacos(self):
        self.assertEqual(tse.normalizar("  Túlio  Rabelo de   Albuquerque "), "TULIO RABELO DE ALBUQUERQUE")
        self.assertEqual(tse.normalizar(None), "")

    def test_variantes_com_apelido_do_siscam(self):
        self.assertEqual(tse.variantes("JOSÉ ADRIANO VALLE DA COSTA - FOLHA"),
                         ["JOSE ADRIANO VALLE DA COSTA - FOLHA", "JOSE ADRIANO VALLE DA COSTA"])
        self.assertEqual(tse.variantes("BENNY BRIOLLY"), ["BENNY BRIOLLY"])

    def test_partidos(self):
        casos = {"PC do B": "PCdoB", "UNIÃO": "União Brasil", "PODE": "Podemos", "SOLIDARIEDADE": "Solidariedade",
                 "CIDADANIA": "Cidadania", "REPUBLICANOS": "Republicanos", "AVANTE": "Avante", "PSOL": "PSOL",
                 "MDB": "MDB", "NOVO": "NOVO"}
        for sigla, esperado in casos.items():
            with self.subTest(sigla=sigla):
                self.assertEqual(tse.normalizar_partido(sigla), esperado)
        self.assertIsNone(tse.normalizar_partido("#NULO"))

    def test_cargos(self):
        self.assertEqual(tse.titulo_cargo("VEREADOR"), "Vereador")
        self.assertEqual(tse.titulo_cargo("DEPUTADO ESTADUAL"), "Deputado Estadual")
        self.assertEqual(tse.titulo_cargo("VICE-GOVERNADOR"), "Vice-Governador")
        self.assertEqual(tse.titulo_cargo("1º SUPLENTE"), "1º Suplente")

    def test_resultados(self):
        self.assertEqual(tse.resultado("ELEITO POR QP"), "Eleito por QP")
        self.assertEqual(tse.resultado("ELEITO POR MÉDIA"), "Eleito por média")
        self.assertEqual(tse.resultado("NÃO ELEITO"), "Não eleito")
        self.assertEqual(tse.resultado("SUPLENTE"), "Suplente")
        self.assertEqual(tse.resultado("2º TURNO"), "2º turno")
        self.assertEqual(tse.resultado("ELEITO"), "Eleito")
        self.assertEqual(tse.resultado("MÉDIA"), "Eleito por média")  # arquivos antigos
        self.assertEqual(tse.resultado("MEDIA"), "Eleito por média")
        for nulo in ("#NULO", "#NE", "#NULO#", "", None):
            self.assertEqual(tse.resultado(nulo), "Resultado não divulgado")

    def test_anos(self):
        self.assertEqual(tse.interpretar_anos("2020,2024,2026"), [2026, 2024, 2020])
        self.assertEqual(tse.interpretar_anos("2020-2024"), [2024, 2022, 2020])
        for invalido in ("2021", "abc", "2024-2020", ""):
            with self.subTest(invalido=invalido), self.assertRaises(ValueError):
                tse.interpretar_anos(invalido)


class TestUrls(unittest.TestCase):
    def test_normaliza_e_remove_rastreio(self):
        casos = {
            "instagram.com/ana.teste/?igsh=abc123": "https://instagram.com/ana.teste",
            "http://twitter.com/anateste?s=20&t=xyz": "https://twitter.com/anateste",
            "https://www.facebook.com/anateste/": "https://www.facebook.com/anateste",
            "https://www.facebook.com/profile.php?id=123&mibextid=zz": "https://www.facebook.com/profile.php?id=123",
            "https://www.youtube.com/watch?v=abc&si=rastreio&utm_source=x": "https://www.youtube.com/watch?v=abc",
            "https://WWW.Exemplo.com.br/pagina/?utm_medium=a&b=1#topo": "https://www.exemplo.com.br/pagina?b=1",
            "https://www.exemplo.com.br/": "https://www.exemplo.com.br",
        }
        for bruta, esperada in casos.items():
            with self.subTest(bruta=bruta):
                self.assertEqual(tse.normalizar_url(bruta), esperada)
        for invalida in ("@anateste", "", "#NULO", "ftp://exemplo.com", "nao e url", "https://localhost"):
            with self.subTest(invalida=invalida):
                self.assertIsNone(tse.normalizar_url(invalida))

    def test_classificacao_por_host(self):
        casos = {"https://instagram.com/a": "instagram", "https://m.facebook.com/a": "facebook", "https://x.com/a": "x",
                 "https://twitter.com/a": "x", "https://youtu.be/a": "youtube", "https://www.tiktok.com/@a": "tiktok",
                 "https://www.threads.net/@a": "threads", "https://br.linkedin.com/in/a": "linkedin"}
        for url, rede in casos.items():
            with self.subTest(url=url):
                redes, sites, _ = tse.redes_declaradas([url], 2024)
                self.assertEqual([r["rede"] for r in redes], [rede])
                self.assertEqual(sites, [])
        redes, sites, ignoradas = tse.redes_declaradas(["https://instagram.com.golpe.net/a", "@a"], 2024)
        self.assertEqual((redes, sites, ignoradas), ([], ["https://instagram.com.golpe.net/a"], ["@a"]))


# ---- leitura e casamento ------------------------------------------------------------
class TestLeitura(Base):
    def test_le_so_rj_e_br_e_ignora_homonimo_de_outro_municipio(self):
        indice = tse.ler_candidatos(self.cache / "consulta_cand_2024.zip", {"ANA MARIA TESTE", "BRUNO TESTE"})
        self.assertEqual(sorted(c["sq"] for c in indice["ANA MARIA TESTE"]), ["1001", "1002"])
        casamento = tse.casar("ANA MARIA TESTE", indice)
        self.assertEqual(casamento["estado"], "casado")
        self.assertEqual(casamento["candidato"]["sq"], "1001")
        self.assertEqual([c["sq"] for c in casamento["ignorados"]], ["1002"])

    def test_estadual_ambiguo_fica_de_fora(self):
        indice = tse.ler_candidatos(self.cache / "consulta_cand_2022.zip", {"CARLOS AMBIGUO", "ANA MARIA TESTE"})
        casamento = tse.casar("CARLOS AMBIGUO", indice)
        self.assertEqual(casamento["estado"], "ambiguo")
        self.assertEqual(sorted(c["sq"] for c in casamento["ambiguos"]), ["2002", "2003"])
        self.assertEqual(tse.casar("ANA MARIA TESTE", indice)["candidato"]["sq"], "2001")  # SP ignorado

    def test_ultimo_turno_prevalece(self):
        indice = tse.ler_candidatos(self.cache / "consulta_cand_2022.zip", {"BRUNO TESTE"})
        [candidato] = indice["BRUNO TESTE"]
        self.assertEqual((candidato["turno"], candidato["situacao"], candidato["cargo"]), (2, "NÃO ELEITO", "Vice-Governador"))

    def test_soma_votos_por_zona_e_municipio(self):
        self.assertEqual(tse.somar_votos(self.cache / "votacao_candidato_munzona_2024.zip", {"1001"}), {"1001": 150})
        votos = tse.somar_votos(self.cache / "votacao_candidato_munzona_2022.zip", {"2001", "2004"})
        self.assertEqual(votos, {"2001": 1000, "2004": 3})  # todos os municípios; último turno

    def test_layout_alterado_levanta_erro(self):
        _zip(self.cache / "quebrado.zip", {"consulta_cand_2024_RJ.csv": [["NM_UE", "SQ_CANDIDATO"], ["NITERÓI", "1"]]})
        with self.assertRaises(ValueError):
            tse.ler_candidatos(self.cache / "quebrado.zip", {"X"})


# ---- desempate e casamentos alternativos ----------------------------------------------
CAB_CAND_SIT = [*CAB_CAND, "DS_SITUACAO_CANDIDATURA"]


def _cand_sit(ue, cargo, sq, nome, situacao, apto="APTO", urna="URNA", partido="PL", uf="RJ"):
    return [*_cand(ue, cargo, sq, nome, partido, situacao, uf=uf, urna=urna), apto]


class TestCasamentoAlternativo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def indice(self, linhas: list[list[str]], alvos: set[str], ano: int = 2024):
        caminho = self.dir / f"consulta_cand_{ano}.zip"
        _zip(caminho, {f"consulta_cand_{ano}_RJ.csv": [CAB_CAND_SIT, *linhas]})
        return tse.ler_candidatos(caminho, alvos)

    def test_troca_de_cargo_fica_com_a_candidatura_apta(self):
        indice = self.indice([
            _cand_sit("RIO DE JANEIRO", "DEPUTADO ESTADUAL", "3001", "FERNANDA ANCHIETA LOUBACK", "#NULO#", apto="INAPTO"),
            _cand_sit("RIO DE JANEIRO", "VICE-GOVERNADOR", "3002", "FERNANDA ANCHIETA LOUBACK", "NÃO ELEITO"),
        ], {"FERNANDA ANCHIETA LOUBACK"}, ano=2026)
        casamento = tse.casar("FERNANDA ANCHIETA LOUBACK", indice)
        self.assertEqual((casamento["estado"], casamento["via"]), ("casado", "nome"))
        self.assertEqual(casamento["candidato"]["sq"], "3002")
        self.assertEqual(casamento["candidato"]["cargo"], "Vice-Governador")

    def test_sem_resultado_divulgado_decide_pela_aptidao(self):
        indice = self.indice([
            _cand_sit("RIO DE JANEIRO", "DEPUTADO ESTADUAL", "3001", "FERNANDA ANCHIETA LOUBACK", "#NULO#", apto="INAPTO"),
            _cand_sit("RIO DE JANEIRO", "VICE-GOVERNADOR", "3002", "FERNANDA ANCHIETA LOUBACK", "#NULO#"),
        ], {"FERNANDA ANCHIETA LOUBACK"}, ano=2026)
        self.assertEqual(tse.casar("FERNANDA ANCHIETA LOUBACK", indice)["candidato"]["sq"], "3002")

    def test_vereador_e_prefeito_fica_com_a_que_tem_resultado(self):
        indice = self.indice([
            _cand_sit("NITERÓI", "VEREADOR", "4001", "ALLAN PINHO LYRA", "SUPLENTE"),
            _cand_sit("NITERÓI", "PREFEITO", "4002", "ALLAN PINHO LYRA", "#NULO"),
        ], {"ALLAN PINHO LYRA"}, ano=2020)
        casamento = tse.casar("ALLAN PINHO LYRA", indice)
        self.assertEqual((casamento["estado"], casamento["candidato"]["sq"]), ("casado", "4001"))

    def test_duas_candidaturas_validas_continuam_ambiguas(self):
        indice = self.indice([
            _cand_sit("NITERÓI", "VEREADOR", "4001", "ALLAN PINHO LYRA", "SUPLENTE"),
            _cand_sit("NITERÓI", "PREFEITO", "4002", "ALLAN PINHO LYRA", "NÃO ELEITO"),
        ], {"ALLAN PINHO LYRA"}, ano=2020)
        casamento = tse.casar("ALLAN PINHO LYRA", indice)
        self.assertEqual((casamento["estado"], casamento["motivo"]), ("ambiguo", "ambíguo"))
        self.assertEqual([c["sq"] for c in casamento["ambiguos"]], ["4001", "4002"])

    def test_desempatar_sem_nenhuma_valida_devolve_todas(self):
        candidatos = [{"sq": "1", "apto": False, "situacao": "#NULO"}, {"sq": "2", "apto": False, "situacao": "#NULO"}]
        self.assertEqual(tse.desempatar(candidatos), candidatos)
        self.assertEqual(tse._apto("", "DEFERIDO COM RECURSO"), True)
        self.assertEqual(tse._apto("INAPTO", "DEFERIDO"), False)
        self.assertIsNone(tse._apto("#NULO#", ""))

    LINHAS_NITEROI = [
        _cand_sit("NITERÓI", "VEREADOR", "5001", "EMANUEL JORGE MENDES DA ROCHA", "SUPLENTE", urna="DR EMANUEL ROCHA"),
        _cand_sit("NITERÓI", "VEREADOR", "5002", "CARLOS EDUARDO FORTES FOLY", "SUPLENTE", urna="DADO FOLY"),
        _cand_sit("MARICÁ", "VEREADOR", "5003", "EDUARDO FOLY DE SOUZA", "SUPLENTE", urna="DADO FOLY"),  # fora de Niterói
        _cand_sit("NITERÓI", "VEREADOR", "5004", "JOSE CARLOS DO GAS", "SUPLENTE", urna="ZE DO GAS"),
        _cand_sit("NITERÓI", "VEREADOR", "5005", "JOSE PEDRO DO GAS", "NÃO ELEITO", urna="PASTOR ZE DO GAS"),
        _cand_sit("NITERÓI", "VEREADOR", "5006", "ANA MARIA TESTE", "ELEITO", urna="ANA TESTE"),
    ]

    def test_nome_de_urna(self):
        indice = self.indice(self.LINHAS_NITEROI, {"DADO FOLY"})
        casamento = tse.casar("DADO FOLY", indice)
        self.assertEqual((casamento["estado"], casamento["via"], casamento["candidato"]["sq"]), ("casado", "urna", "5002"))

    def test_nome_de_urna_sem_titulo(self):
        self.assertEqual(tse.chaves_urna("Dr. Emanuel Rocha"), frozenset({"DR. EMANUEL ROCHA", "EMANUEL ROCHA"}))
        self.assertEqual(tse.sem_titulo("PROFESSORA DRA ANA"), "ANA")
        self.assertEqual(tse.sem_titulo("PASTOR"), "PASTOR")
        indice = self.indice(self.LINHAS_NITEROI, set())
        self.assertEqual(tse.casar("EMANUEL ROCHA", indice)["candidato"]["sq"], "5001")

    def test_nome_civil_parcial(self):
        indice = self.indice(self.LINHAS_NITEROI, {"EMANUEL JORGE ROCHA"})
        casamento = tse.casar("EMANUEL JORGE ROCHA", indice)
        self.assertEqual((casamento["estado"], casamento["via"], casamento["candidato"]["sq"]), ("casado", "nome_parcial", "5001"))
        self.assertTrue(tse.subsequencia("EMANUEL JORGE ROCHA".split(), "EMANUEL JORGE MENDES DA ROCHA".split()))
        self.assertFalse(tse.subsequencia("JORGE ROCHA".split(), "JORGE MENDES ROCHA".split()))  # menos de 3 palavras
        self.assertFalse(tse.subsequencia("EMANUEL JORGE ROCHA".split(), "EMANUEL JORGE ROCHA FILHO".split()))  # última difere
        self.assertFalse(tse.subsequencia("JORGE EMANUEL ROCHA".split(), "EMANUEL JORGE MENDES DA ROCHA".split()))  # primeira difere
        self.assertFalse(tse.subsequencia("EMANUEL ROCHA JORGE ROCHA".split(), "EMANUEL JORGE MENDES DA ROCHA".split()))  # fora de ordem

    def test_homonimo_por_nome_de_urna(self):
        indice = self.indice(self.LINHAS_NITEROI, set())
        casamento = tse.casar("ZE DO GAS", indice)
        self.assertEqual((casamento["estado"], casamento["motivo"]), ("ambiguo", "homônimo pelo nome de urna"))
        self.assertEqual([c["sq"] for c in casamento["ambiguos"]], ["5004", "5005"])

    def test_exato_tem_prioridade_e_conflito_vira_homonimo(self):
        indice = self.indice(self.LINHAS_NITEROI, {"ANA MARIA TESTE", "ANA TESTE"})
        casamentos = {nome: tse.casar(nome, indice) for nome in ("ANA MARIA TESTE", "ANA TESTE")}
        self.assertEqual(casamentos["ANA MARIA TESTE"]["via"], "nome")
        self.assertEqual(casamentos["ANA TESTE"]["via"], "urna")
        tse.resolver_conflitos(casamentos)
        self.assertEqual(casamentos["ANA MARIA TESTE"]["estado"], "casado")
        self.assertEqual(casamentos["ANA TESTE"]["estado"], "ambiguo")
        self.assertIn("ANA MARIA TESTE", casamentos["ANA TESTE"]["motivo"])

    def test_apelido_antes_das_alternativas(self):
        indice = self.indice(self.LINHAS_NITEROI, {"JOSE PEDRO DO GAS"})
        # sem o apelido, o nome de urna é ambíguo; com ele, o nome civil exato decide
        with mock.patch.dict(tse.APELIDOS_TSE, {"ZE DO GAS": ("NOME QUE NAO EXISTE", "JOSÉ PEDRO DO GÁS")}):
            casamento = tse.casar("ZE DO GAS", indice)
        self.assertEqual((casamento["estado"], casamento["via"], casamento["candidato"]["sq"]), ("casado", "apelido_tse", "5005"))
        # apelido sem candidatura não impede as alternativas automáticas
        with mock.patch.dict(tse.APELIDOS_TSE, {"DADO FOLY": ("NOME QUE NAO EXISTE",)}):
            self.assertEqual(tse.casar("DADO FOLY", indice)["via"], "urna")

    def test_nome_do_siscam_tem_prioridade_sobre_o_apelido(self):
        # Gallo em 2000: candidato a vice-prefeito com o nome completo, sub judice (#NULO#)
        indice = self.indice([
            _cand_sit("NITERÓI", "VICE-PREFEITO", "6001", "LUIZ CARLOS GALLO DE FREITAS", "#NULO#", urna="GALLO"),
            _cand_sit("NITERÓI", "VEREADOR", "6002", "LUIZ CARLOS DE FREITAS", "ELEITO", urna="LUIZ CARLOS"),
        ], {"LUIZ CARLOS GALLO DE FREITAS", "LUIZ CARLOS DE FREITAS"}, ano=2000)
        casamento = tse.casar("LUIZ CARLOS GALLO DE FREITAS", indice)
        self.assertEqual((casamento["via"], casamento["candidato"]["sq"]), ("nome", "6001"))

    def test_apelidos_versionados(self):
        """Gallo (1996/2004), Zaf (2000) e Leandro Portugal (2016) com outra grafia no TSE."""
        casos = {
            "LUIZ CARLOS GALLO DE FREITAS": ("LUIZ CARLOS DE FREITAS", "GALLO", "PFL", "ELEITO", 1996),
            "JOSÉ ANTONIO TORO FERNANDEZ": ("JOSÉ ANTONIO TORO FERNANDES", "ZAF", "PSD", "ELEITO", 2000),
            "LEANDRO PORTUGAL FRANZEN DE LIMA": ("LEANDRO PORTUGAL FRAZEN DE LIMA", "LEANDRO PORTUGAL", "PV", "ELEITO POR QP", 2016),
        }
        for siscam, (civil, urna, partido, situacao, ano) in casos.items():
            with self.subTest(siscam=siscam):
                self.assertIn(civil, tse.APELIDOS_TSE[siscam])
                alvos = {tse.normalizar(civil)}
                indice = self.indice([_cand_sit("NITERÓI", "VEREADOR", "7001", civil, situacao, urna=urna, partido=partido)],
                                     alvos, ano=ano)
                casamento = tse.casar(siscam, indice)
                self.assertEqual((casamento["estado"], casamento["via"]), ("casado", "apelido_tse"))
                self.assertEqual(tse.item_eleicao(ano, casamento["candidato"], None)["partido"], partido)

    def test_resumo_mostra_casamento_por_apelido(self):
        relatorio = {"anos": {1996: {"casados": ["X"], "sem_candidatura": [], "ambiguos": [], "homonimos_ignorados": 0,
                                     "votacao": True, "redes": False,
                                     "aproximados": [("X", "apelido_tse", "Vereador (NITERÓI), nº 1, PFL, SQ 1")]}},
                     "sem_nenhuma": [], "adicionados": [], "urls_ignoradas": []}
        with contextlib.redirect_stdout(io.StringIO()) as saida:
            tse.imprimir_resumo(relatorio)
        self.assertIn("1996: X casado por apelido (confira na revisão)", saida.getvalue())


# ---- execução completa --------------------------------------------------------------
class TestExecucao(Base):
    def test_atualiza_perfis(self):
        codigo, saida, erros = self.rodar()
        self.assertEqual(codigo, 0, erros)
        vereadores = self.resultado()["vereadores"]
        ana = vereadores["ANA MARIA TESTE"]
        self.assertEqual(ana["eleicoes"], [
            {"ano": 2024, "cargo": "Vereador", "uf": "RJ", "partido": "PCdoB", "votos": 150, "resultado": "Eleito por QP",
             "fonte": {"titulo": "TSE — Dados abertos: candidatos 2024", "url": "https://dadosabertos.tse.jus.br/dataset/candidatos-2024"}},
            {"ano": 2022, "cargo": "Deputado Estadual", "uf": "RJ", "partido": "PCdoB", "votos": 1000, "resultado": "Suplente",
             "fonte": {"titulo": "TSE — Dados abertos: candidatos 2022", "url": "https://dadosabertos.tse.jus.br/dataset/candidatos-2022"}},
            PERFIS["vereadores"]["ANA MARIA TESTE"]["eleicoes"][0],
        ])
        fonte = "https://dadosabertos.tse.jus.br/dataset/candidatos-2024"
        self.assertEqual(ana["redes"], [
            {"rede": "instagram", "url": "https://instagram.com/ana.teste", "fonte": fonte},
            {"rede": "facebook", "url": "https://www.facebook.com/anateste", "fonte": fonte},
            {"rede": "x", "url": "https://twitter.com/anateste", "fonte": fonte},
            {"rede": "linkedin", "url": "https://linkedin.com/in/ana", "fonte": "https://ana.exemplo.org/contato"},
        ])
        self.assertEqual(ana["site"], "https://www.anateste.com.br")
        # votos do mandato, logo depois do partido, com a fonte dos resultados
        self.assertEqual(list(ana["mandatos"]["2025-2028"]), ["partido", "votos", "situacao", "fontes"])
        self.assertEqual(ana["mandatos"]["2025-2028"]["votos"], 150)
        self.assertIn("https://dadosabertos.tse.jus.br/dataset/resultados-2024",
                      [f["url"] for f in ana["mandatos"]["2025-2028"]["fontes"]])

        bruno = vereadores["BRUNO TESTE"]
        self.assertEqual([(e["ano"], e["cargo"], e["partido"], e["votos"], e["resultado"]) for e in bruno["eleicoes"]],
                         [(2024, "Vereador", "União Brasil", None, "Resultado não divulgado"),
                          (2022, "Vice-Governador", "Solidariedade", 3, "Não eleito")])
        self.assertNotIn("votos", bruno["mandatos"]["2025-2028"])  # sem votos na votação: nada inventado

        carlos = vereadores["CARLOS AMBIGUO"]
        self.assertEqual(carlos["eleicoes"], PERFIS["vereadores"]["CARLOS AMBIGUO"]["eleicoes"])
        self.assertIn("CARLOS AMBIGUO ambíguo", erros)

        diego = vereadores["DIEGO NOVO"]
        self.assertEqual(diego, {
            "mandatos": {"2025-2028": {"partido": "PT", "situacao": "eleito",
                                       "fontes": [{"titulo": "Composição eleita da legislatura 2025-2028",
                                                   "url": "https://exemplo.org/2024"}]}},
            "eleicoes": [], "camara": None, "site": None, "redes": [],
        })
        self.assertIn("Perfis adicionados: DIEGO NOVO", saida)
        self.assertEqual(list(vereadores), ["ANA MARIA TESTE", "BRUNO TESTE", "CARLOS AMBIGUO", "DIEGO NOVO"])

    def test_formato_canonico_e_deterministico(self):
        self.rodar()
        primeiro = self.perfis.read_bytes()
        texto = primeiro.decode("utf-8")
        self.assertNotIn(b"\r\n", primeiro)
        self.assertEqual(texto, json.dumps(json.loads(texto), ensure_ascii=False, indent=1) + "\n")
        self.assertEqual(list(json.loads(texto)), ["_leia_me", "fonte_padrao", "vereadores"])
        _, saida, _ = self.rodar()
        self.assertEqual(self.perfis.read_bytes(), primeiro)
        self.assertIn("perfis.json: sem mudanças", saida)

    def test_sem_download_sem_cache_mantem_eleicoes(self):
        for arquivo in self.cache.glob("*.zip"):
            arquivo.unlink()
        codigo, _, erros = self.rodar()
        self.assertEqual(codigo, 0)
        self.assertIn("::warning::", erros)
        vereadores = self.resultado()["vereadores"]
        self.assertEqual(vereadores["ANA MARIA TESTE"]["eleicoes"], PERFIS["vereadores"]["ANA MARIA TESTE"]["eleicoes"])
        self.assertEqual(vereadores["ANA MARIA TESTE"]["redes"], PERFIS["vereadores"]["ANA MARIA TESTE"]["redes"])

    def test_sem_votacao_votos_ficam_nulos(self):
        (self.cache / "votacao_candidato_munzona_2024.zip").unlink()
        self.rodar()
        ana = self.resultado()["vereadores"]["ANA MARIA TESTE"]
        self.assertIsNone(ana["eleicoes"][0]["votos"])
        self.assertNotIn("votos", ana["mandatos"]["2025-2028"])

    def test_anos_fora_da_execucao_ficam_intactos(self):
        tse_2008 = {"ano": 2008, "cargo": "Vereador", "uf": "RJ", "partido": "PT", "votos": 1234, "resultado": "Suplente",
                    "fonte": {"titulo": "TSE — Dados abertos: candidatos 2008",
                              "url": "https://dadosabertos.tse.jus.br/dataset/candidatos-2008"}}
        # 2020 é pedido, mas o arquivo não está no cache: o ano não é processado
        tse_2020 = {**tse_2008, "ano": 2020, "votos": 999, "fonte": {"titulo": "TSE — Dados abertos: candidatos 2020",
                                                                      "url": "https://dadosabertos.tse.jus.br/dataset/candidatos-2020"}}
        wiki_1992 = {"ano": 1992, "cargo": "Vereador", "uf": "RJ", "partido": "PDT", "votos": None, "resultado": "Eleito",
                     "fonte": {"titulo": "Wikipédia", "url": "https://pt.wikipedia.org/wiki/Elei%C3%A7%C3%B5es_em_Niter%C3%B3i"}}
        perfis = copy.deepcopy(PERFIS)
        perfis["vereadores"]["ANA MARIA TESTE"]["eleicoes"] = [tse_2020, tse_2008, wiki_1992]
        self.perfis.write_text(tse.texto_perfis(perfis), encoding="utf-8", newline="\n")
        codigo, _, erros = self.rodar("--anos", "2020,2024")
        self.assertEqual(codigo, 0, erros)
        eleicoes = self.resultado()["vereadores"]["ANA MARIA TESTE"]["eleicoes"]
        self.assertEqual([e["ano"] for e in eleicoes], [2024, 2020, 2008, 1992])
        self.assertEqual(eleicoes[1:], [tse_2020, tse_2008, wiki_1992])
        self.assertEqual(eleicoes[0]["fonte"]["url"], "https://dadosabertos.tse.jus.br/dataset/candidatos-2024")

    def test_passa_no_validador(self):
        from coletor import validar
        self.rodar()
        self.assertEqual(validar.validar_perfis(self.perfis, CONFIG), [])


# ---- download com cache -------------------------------------------------------------
class Resposta:
    def __init__(self, corpo: bytes = b"", cabecalhos: dict | None = None):
        self._corpo = io.BytesIO(corpo)
        self.headers = email.message.Message()
        for chave, valor in (cabecalhos or {}).items():
            self.headers[chave] = valor

    def read(self, n: int = -1) -> bytes:
        return self._corpo.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class TestDownload(Base):
    URL = tse.URL_CANDIDATOS.format(ano=2024)

    def _abrir(self, respostas):
        pedidos = []

        def abrir(req, timeout=None):
            pedidos.append((req.get_method(), dict(req.header_items())))
            resposta = respostas[req.get_method()]
            if isinstance(resposta, BaseException):
                raise resposta
            return resposta

        return abrir, pedidos

    def test_mesma_versao_no_head_nao_baixa(self):
        versoes = {"consulta_cand_2024.zip": {"etag": '"abc"', "last_modified": None, "url": self.URL}}
        abrir, pedidos = self._abrir({"HEAD": Resposta(cabecalhos={"ETag": '"abc"'})})
        with mock.patch("coletor.tse.urllib.request.urlopen", side_effect=abrir), contextlib.redirect_stdout(io.StringIO()):
            caminho = tse.obter(self.URL, self.cache, versoes, False)
        self.assertEqual(caminho, self.cache / "consulta_cand_2024.zip")
        self.assertEqual([m for m, _ in pedidos], ["HEAD"])

    def test_versao_nova_usa_get_condicional_e_aceita_304(self):
        versoes = {"consulta_cand_2024.zip": {"etag": '"abc"', "last_modified": "Mon, 01 Jan 2024 00:00:00 GMT"}}
        antes = (self.cache / "consulta_cand_2024.zip").read_bytes()
        nao_modificado = urllib.error.HTTPError(self.URL, 304, "Not Modified", None, None)
        abrir, pedidos = self._abrir({"HEAD": Resposta(cabecalhos={"ETag": '"novo"'}), "GET": nao_modificado})
        with mock.patch("coletor.tse.urllib.request.urlopen", side_effect=abrir), contextlib.redirect_stdout(io.StringIO()):
            caminho = tse.obter(self.URL, self.cache, versoes, False)
        self.assertEqual(caminho.read_bytes(), antes)
        metodo, cabecalhos = pedidos[-1]
        self.assertEqual(metodo, "GET")
        self.assertEqual(cabecalhos.get("If-none-match"), '"abc"')
        self.assertEqual(cabecalhos.get("If-modified-since"), "Mon, 01 Jan 2024 00:00:00 GMT")

    def test_download_grava_zip_e_versao(self):
        conteudo = (self.cache / "consulta_cand_2024.zip").read_bytes()
        vazio = self.dir / "vazio"
        versoes: dict = {}
        abrir, _ = self._abrir({"GET": Resposta(conteudo, {"ETag": '"v1"', "Last-Modified": "Tue, 02 Jan 2024 00:00:00 GMT"})})
        with mock.patch("coletor.tse.urllib.request.urlopen", side_effect=abrir), contextlib.redirect_stdout(io.StringIO()):
            caminho = tse.obter(self.URL, vazio, versoes, False)
        self.assertEqual(caminho.read_bytes(), conteudo)
        self.assertEqual(versoes["consulta_cand_2024.zip"]["etag"], '"v1"')
        self.assertEqual(list(vazio.glob(".*.tmp")), [])

    def test_404_sem_cache_fica_indisponivel(self):
        nao_encontrado = urllib.error.HTTPError(self.URL, 404, "Not Found", None, None)
        abrir, _ = self._abrir({"GET": nao_encontrado})
        with mock.patch("coletor.tse.urllib.request.urlopen", side_effect=abrir), \
                contextlib.redirect_stderr(io.StringIO()) as erros:
            self.assertIsNone(tse.obter(self.URL, self.dir / "vazio", {}, False))
        self.assertIn("::warning::", erros.getvalue())

    def test_conteudo_que_nao_e_zip_nao_substitui(self):
        vazio = self.dir / "vazio"
        abrir, _ = self._abrir({"GET": Resposta(b"<html>erro</html>")})
        with mock.patch("coletor.tse.urllib.request.urlopen", side_effect=abrir), mock.patch("coletor.tse.time.sleep"), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertIsNone(tse.obter(self.URL, vazio, {}, False))
        self.assertEqual(list(vazio.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
