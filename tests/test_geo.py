"""Geometria e mapas offline: Overpass sintético, sem ler a extração real nem data/."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import random
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from unittest import mock

from coletor import arquivos, geo, gerar_site, validar
from coletor.regras_documentos import BAIRROS_NITEROI
from coletor.site import graficos as G
from coletor.site import paginas as P

ESPERADOS = ("Icaraí", "Ponta d'Areia", "Vital Brazil")
NS = "{http://www.w3.org/2000/svg}"


def way(ref: int, pontos: list[tuple[float, float]], papel: str = "outer") -> dict:
    return {"type": "way", "ref": ref, "role": papel, "geometry": [{"lon": x, "lat": y} for x, y in pontos]}


def relacao(id_: int, nome: str, membros: list[dict]) -> dict:
    return {"type": "relation", "id": id_, "tags": {"name": nome, "boundary": "administrative", "admin_level": "10"},
            "members": membros}


def overpass() -> dict:
    a, b, c, d = (-43.10, -22.90), (-43.09, -22.90), (-43.09, -22.89), (-43.10, -22.89)
    fronteira = [b, (-43.08999, -22.895), c]
    f, g = (-43.08, -22.90), (-43.08, -22.89)
    buraco = [(-43.098, -22.898), (-43.095, -22.898), (-43.095, -22.895), (-43.098, -22.895), (-43.098, -22.898)]
    minusculo = [(-43.099, -22.899), (-43.09899, -22.899), (-43.09899, -22.89899), (-43.099, -22.89899), (-43.099, -22.899)]
    ilha = [(-43.08, -22.88), (-43.07, -22.88), (-43.07, -22.87), (-43.08, -22.87), (-43.08, -22.88)]
    # Quatro ways fora de ordem, dois invertidos; a fronteira 12 é compartilhada.
    dados = {"osm3s": {"timestamp_osm_base": "2026-10-23T03:26:20Z"}, "elements": [
        relacao(1, "ICARAI", [way(13, [d, c]), way(11, [b, a]), way(14, [a, d]), way(12, fronteira),
                               way(15, buraco, "inner"), way(16, minusculo, "inner")]),
        relacao(2, "Ponta D’Areia", [way(22, [g, f]), way(12, list(reversed(fronteira))), way(21, [c, g]), way(23, [f, b])]),
        relacao(3, "Vital Brasil", [way(30, ilha)]),
    ]}
    return json.loads(json.dumps(dados))  # a mesma forma que uma resposta JSON real


def geo_completo() -> dict:
    bairros = {}
    for i, nome in enumerate(BAIRROS_NITEROI):
        x, y = (i % 8) * 100, (i // 8) * 100
        bairros[nome] = {"path": f"M{x},{y} {x + 80},{y} {x + 80},{y + 80} {x},{y + 80}Z", "osm_id": i + 1,
                         "centro": [x + 40, y + 40]}
    return {"fonte": "https://www.openstreetmap.org/relation/2220789", "licenca": "ODbL 1.0",
            "atribuicao": "© contribuidores do OpenStreetMap", "osm_base": "2026-10-23T03:26:20Z",
            "viewbox": [0, 0, 1000, 1000], "bairros": bairros}


class TestGeometria(unittest.TestCase):
    def test_normalizacao_de_nomes_completos(self):
        for nome in BAIRROS_NITEROI:
            self.assertEqual(geo.nome_oficial(nome), nome)
        self.assertEqual(geo.nome_oficial("icarai"), "Icaraí")
        self.assertEqual(geo.nome_oficial("PONTA D’AREIA"), "Ponta d'Areia")
        self.assertEqual(geo.nome_oficial("Vital Brasil"), "Vital Brazil")
        self.assertIsNone(geo.nome_oficial("Rua em Icaraí"))

    def test_encadeia_fora_de_ordem_e_inverte(self):
        trechos = [[(1, 1), (0, 1)], [(1, 0), (0, 0)], [(0, 0), (0, 1)], [(1, 0), (1, 1)]]
        self.assertEqual(geo.montar_aneis(trechos), [[(0, 0), (0, 1), (1, 1), (1, 0), (0, 0)]])
        self.assertEqual(geo.montar_aneis(list(reversed(trechos))), geo.montar_aneis(trechos))

    def test_anel_aberto_avisa_e_falha(self):
        saida = io.StringIO()
        with contextlib.redirect_stderr(saida), self.assertRaisesRegex(ValueError, "anel não fechou"):
            geo.montar_aneis([[(0, 0), (1, 0)], [(1, 0), (1, 1)]], "Icaraí/outer")
        self.assertIn("::warning::Icaraí/outer", saida.getvalue())

    def test_simplificacao_deterministica(self):
        pontos = [(0, 0), (1, .01), (2, 0), (3, 1), (4, 1)]
        self.assertEqual(geo.douglas_peucker(pontos, .1), [(0, 0), (2, 0), (3, 1), (4, 1)])
        self.assertEqual(geo.douglas_peucker(pontos, .1), geo.douglas_peucker(pontos, .1))

    def test_recusa_entrada_e_tolerancia_invalidas(self):
        with self.assertRaisesRegex(ValueError, "objeto Overpass"):
            geo.converter_overpass([])
        for tolerancia in (-1, float("nan"), float("inf")):
            with self.subTest(tolerancia=tolerancia), self.assertRaisesRegex(ValueError, "tolerância"):
                geo.converter_overpass(overpass(), bairros_esperados=ESPERADOS, tolerancia=tolerancia)

    def test_converte_inner_descarta_minusculo_e_limita_coordenadas(self):
        resultado = geo.converter_overpass(overpass(), bairros_esperados=ESPERADOS)
        self.assertEqual(set(resultado["bairros"]), set(ESPERADOS))
        self.assertEqual(resultado["bairros"]["Icaraí"]["path"].count("M"), 2)
        self.assertEqual(resultado["bairros"]["Icaraí"]["path"].count("Z"), 2)
        self.assertEqual(resultado["licenca"], "ODbL 1.0")
        self.assertEqual(resultado["osm_base"], "2026-10-23T03:26:20Z")
        self.assertEqual(resultado["viewbox"][2], 1000)
        self.assertEqual(resultado["tolerancia_m"], 25)
        for bairro in resultado["bairros"].values():
            self.assertIsInstance(bairro["osm_id"], int)
            self.assertTrue(bairro["path"].endswith("Z"))
            for i in (0, 1):
                self.assertTrue(0 <= bairro["centro"][i] <= resultado["viewbox"][i + 2])

    def test_mesmos_bytes_com_ordem_e_direcao_diferentes(self):
        dados = overpass()
        original = geo.converter_overpass(dados, bairros_esperados=ESPERADOS)
        rnd = random.Random(42)
        rnd.shuffle(dados["elements"])
        for rel in dados["elements"]:
            rnd.shuffle(rel["members"])
            for membro in rel["members"]:
                membro["geometry"].reverse()
        novo = geo.converter_overpass(dados, bairros_esperados=ESPERADOS)
        self.assertEqual(arquivos.texto_mapa(novo), arquivos.texto_mapa(original))

    def test_fronteira_compartilhada_nao_abre_fresta(self):
        resultado = geo.converter_overpass(overpass(), bairros_esperados=ESPERADOS)
        # O way 12 tem um desvio de aproximadamente um metro: o DP remove seu
        # ponto intermediário dos dois bairros e mantém as mesmas duas pontas.
        ic = resultado["bairros"]["Icaraí"]["path"].split("Z")[0][1:].split()
        pa = resultado["bairros"]["Ponta d'Areia"]["path"].split("Z")[0][1:].split()
        self.assertEqual(len(set(ic) & set(pa)), 2)

    def test_tolerancia_excessiva_nao_deixa_aneis_degenerados(self):
        resultado = geo.converter_overpass(overpass(), bairros_esperados=ESPERADOS, tolerancia=10000)
        self.assertLess(resultado["tolerancia_m"], 10000)
        for bairro in resultado["bairros"].values():
            self.assertGreaterEqual(len(bairro["path"].split("Z")[0].split()), 3)

    def test_falta_sobra_duplicata_e_geometria_ausente_falham(self):
        with self.assertRaisesRegex(ValueError, "bairros oficiais sem geometria"):
            geo.converter_overpass(overpass())
        dados = overpass()
        dados["elements"][0]["tags"]["name"] = "Desconhecido"
        with self.assertRaisesRegex(ValueError, "sem bairro oficial"):
            geo.converter_overpass(dados, bairros_esperados=ESPERADOS)
        dados = overpass()
        dados["elements"].append(copy.deepcopy(dados["elements"][0]))
        with self.assertRaisesRegex(ValueError, "duplicadas"):
            geo.converter_overpass(dados, bairros_esperados=ESPERADOS)
        dados = overpass()
        del dados["elements"][0]["members"][0]["geometry"]
        with self.assertRaisesRegex(ValueError, "out geom"):
            geo.converter_overpass(dados, bairros_esperados=ESPERADOS)

    def test_comando_grava_pelo_serializador_e_relata_tamanho(self):
        converter = geo.converter_overpass
        with tempfile.TemporaryDirectory() as pasta:
            raiz = Path(pasta)
            entrada, destino = raiz / "entrada.json", raiz / "saida.json"
            arquivos.salvar_json(entrada, overpass())
            saida = io.StringIO()
            with mock.patch.object(geo, "DESTINO", destino), \
                    mock.patch.object(geo, "converter_overpass", side_effect=lambda d, **kw: converter(d, bairros_esperados=ESPERADOS, **kw)), \
                    mock.patch("sys.argv", ["coletor.geo", "--entrada", str(entrada)]), contextlib.redirect_stdout(saida):
                geo.main()
            self.assertEqual(destino.read_bytes(), arquivos.texto_mapa(converter(overpass(), bairros_esperados=ESPERADOS)).encode())
            self.assertIn("3 bairros; tolerância 25 m", saida.getvalue())
            self.assertIn("bytes gzip", saida.getvalue())


class TestQuantis(unittest.TestCase):
    def verificar_faixas(self, valores: list[int]) -> list[tuple[int, int, int]]:
        faixas = G.faixas_quantis(valores)
        self.assertEqual(sum(n for _, _, n in faixas), len(valores))
        self.assertTrue(all(inicio <= fim and n > 0 for inicio, fim, n in faixas))
        for inicio, fim, quantidade in faixas:
            self.assertEqual(sum(inicio <= v <= fim for v in valores), quantidade)
        self.assertTrue(all(a[1] < b[0] for a, b in zip(faixas, faixas[1:])))
        positivas = [f for f in faixas if f[0] > 0]
        self.assertEqual(len(positivas), min(5, len({v for v in valores if v > 0})))
        return faixas

    def test_quantidades_equilibradas(self):
        self.assertEqual(self.verificar_faixas(list(range(1, 51))),
                         [(1, 10, 10), (11, 20, 10), (21, 30, 10), (31, 40, 10), (41, 50, 10)])

    def test_distribuicao_enviesada_e_cortes_arredondados(self):
        valores = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 20, 40, 80, 160, 320, 640, 1280, 2560, 5120, 10240]
        self.assertEqual(self.verificar_faixas(valores),
                         [(1, 4, 4), (5, 8, 4), (9, 50, 4), (51, 1000, 4), (1001, 10240, 4)])
        self.assertEqual(G._corte_limpo(76, 81), 80)
        self.assertEqual(G._corte_limpo(120, 159), 150)
        self.assertEqual(G._corte_limpo(24, 24), 24)  # sem espaço para arredondar

    def test_poucos_valores_distintos_nao_dividem_empates(self):
        self.assertEqual(self.verificar_faixas([24] * 20 + [25] * 10 + [100] * 5),
                         [(24, 24, 20), (25, 50, 10), (51, 100, 5)])
        self.verificar_faixas([1] * 100 + [2, 3, 4, 5, 6])  # muita concentração num valor

    def test_todos_iguais_e_vazios(self):
        self.assertEqual(self.verificar_faixas([37] * 52), [(37, 37, 52)])
        self.assertEqual(self.verificar_faixas([0] * 52), [(0, 0, 52)])
        self.assertEqual(self.verificar_faixas([]), [])

    def test_zeros_separados_nao_entram_nos_quantis(self):
        positivos = [10] * 3 + [20] * 3
        self.assertEqual(self.verificar_faixas([0] * 4 + positivos),
                         [(0, 0, 4), (10, 10, 3), (11, 20, 3)])
        self.assertEqual(G.faixas_quantis([0] * 100 + positivos)[1:], G.faixas_quantis(positivos))

    def test_determinismo_independente_da_ordem(self):
        rnd = random.Random(73)
        for _ in range(20):
            valores = [rnd.choice((0, 24, 25, 26, 80, 150, 500, 3000)) for _ in range(52)]
            esperado = self.verificar_faixas(valores)
            rnd.shuffle(valores)
            self.assertEqual(G.faixas_quantis(valores), esperado)


class TestMapa(unittest.TestCase):
    def test_paleta_sequencial_e_bordas_contrastantes_nos_dois_temas(self):
        css = (Path(__file__).resolve().parents[1] / "site_src" / "estilo.css").read_text(encoding="utf-8")

        def cor(variavel):
            return re.search(rf"--{variavel}:\s*(#[0-9A-Fa-f]{{6}})", css).group(1)

        def luminosidade(hexa):
            canais = [int(hexa[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            lineares = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in canais]
            return sum(peso * valor for peso, valor in zip((.2126, .7152, .0722), lineares))

        tons = [luminosidade(cor(f"mapa-{i}")) for i in range(1, 6)]
        self.assertTrue(all(a - b > .1 for a, b in zip(tons, tons[1:])))
        for i, tom in enumerate(tons, 1):
            borda = luminosidade(cor("mapa-borda-escura" if i <= 3 else "mapa-borda-clara"))
            self.assertGreaterEqual((max(tom, borda) + .05) / (min(tom, borda) + .05), 3)
            # A sequência não é invertida nem sobrescrita em prefers-color-scheme/data-theme.
            self.assertEqual(css.count(f"--mapa-{i}:"), 1)
        self.assertIn("@media (prefers-color-scheme: dark)", css)
        self.assertIn(':root[data-theme="dark"]', css)

    def test_svg_com_52_paths_faixas_titulo_legenda_e_tabela(self):
        valores = {"Icaraí": 7, "Centro": 30, "Badu": 200, "Itaipu": 1200, "Cafubá": 10000}
        texto = G.mapa_coropletico(valores, geo_completo(), "Indicações por bairro")
        raiz = ET.fromstring(texto)
        svg = raiz.find(f".//{NS}svg")
        self.assertEqual(svg.get("role"), "img")
        self.assertIsNotNone(svg.find(f"{NS}title"))
        self.assertIsNotNone(svg.find(f"{NS}desc"))
        paths = svg.findall(f".//{NS}path")
        self.assertEqual(len(paths), 52)
        self.assertEqual({p.get("class") for p in paths}, {f"mapa-bairro mapa-{i}" for i in range(6)})
        self.assertTrue(all(p.get("fill-rule") == "evenodd" for p in paths))
        self.assertIn("Icaraí: 7 indicações", [p.find(f"{NS}title").text for p in paths])
        self.assertIn("Zero é hachurado", svg.find(f"{NS}desc").text)
        self.assertEqual(len(raiz.findall(".//tbody/tr")), 52)
        self.assertIn("0 (hachurado)", texto)
        self.assertIn("© contribuidores do OpenStreetMap", texto)
        self.assertIn("https://www.openstreetmap.org/copyright", texto)
        self.assertNotIn("<script", texto)
        legenda = raiz.find(".//ul[@class='leg-graf leg-mapa']")
        self.assertEqual(legenda.get("aria-label"), "Faixas de indicações e número de bairros")
        faixas = G.faixas_quantis([valores.get(b, 0) for b in BAIRROS_NITEROI])
        itens = legenda.findall("li")
        self.assertEqual(len(itens), len(faixas))
        for item, (inicio, fim, quantidade) in zip(itens, faixas):
            amostra = item.find("i")
            self.assertEqual(amostra.get("aria-hidden"), "true")
            classe = amostra.get("class").split()[-1]
            classificados = [p for p in paths if p.get("class").split()[-1] == classe]
            self.assertEqual(len(classificados), quantidade)
            for path in classificados:
                bairro = path.find(f"{NS}title").text.split(": ")[0]
                self.assertTrue(inicio <= valores.get(bairro, 0) <= fim)
            rotulo = "0 (hachurado)" if inicio == 0 else G._fmt(inicio) if inicio == fim else f"{G._fmt(inicio)}–{G._fmt(fim)}"
            self.assertEqual(item.find("span").text,
                             f"{rotulo} indicações · {quantidade} {'bairro' if quantidade == 1 else 'bairros'}")

    def test_sem_faixas_vazias_quando_todos_os_bairros_tem_indicacoes(self):
        valores = dict(zip(BAIRROS_NITEROI, range(24, 76)))
        texto = G.mapa_coropletico(valores, geo_completo(), "Indicações")
        raiz = ET.fromstring(texto)
        self.assertNotIn("0 (hachurado)", texto)
        classes = Counter(p.get("class") for p in raiz.findall(f".//{NS}path"))
        self.assertEqual(set(classes), {f"mapa-bairro mapa-{i}" for i in range(1, 6)})
        self.assertTrue(all(10 <= n <= 11 for n in classes.values()))
        self.assertEqual(len(raiz.findall(".//ul[@class='leg-graf leg-mapa']/li")), 5)

    def test_legenda_permanece_com_uma_unica_faixa(self):
        for valor, classe in ((0, 0), (37, 3)):
            with self.subTest(valor=valor):
                valores = dict.fromkeys(BAIRROS_NITEROI, valor)
                raiz = ET.fromstring(G.mapa_coropletico(valores, geo_completo(), "Indicações"))
                self.assertEqual({p.get("class") for p in raiz.findall(f".//{NS}path")}, {f"mapa-bairro mapa-{classe}"})
                itens = raiz.findall(".//ul[@class='leg-graf leg-mapa']/li")
                self.assertEqual(len(itens), 1)
                self.assertIn("52 bairros", itens[0].find("span").text)

    def test_escape_de_titulo_atribuicao_e_path(self):
        geometria = geo_completo()
        geometria["atribuicao"] = 'OSM <fonte> & "autores"'
        geometria["bairros"]["Icaraí"]["path"] += '" onload="alert(1)'
        titulo = '<mapa & "teste">'
        texto = G.mapa_coropletico({}, geometria, titulo)
        self.assertNotIn(titulo, texto)
        self.assertNotIn('" onload="', texto)
        raiz = ET.fromstring(texto)
        self.assertEqual(raiz.find(f".//{NS}title").text, titulo)
        self.assertNotIn("onload", raiz.find(f".//{NS}path").attrib)

    def test_integracao_geral_individual_opcional_e_orcamento(self):
        # Modelo sintético compartilhado com os testes de documentos, sem dados reais.
        from tests.test_documentos_site import montar

        modelo = montar()
        pessoa = modelo["pessoas"]["ana-maria-teste"]
        sem_geo = P.secao_resumos_atividades(modelo)
        self.assertNotIn('class="mapa-bairros"', sem_geo)
        self.assertIn("Indicações por bairro", sem_geo)
        modelo["geo_bairros"] = geo_completo()
        geral = P.secao_resumos_atividades(modelo)
        self.assertIn('class="mapa-bairros"', geral)
        self.assertIn("0% sem bairro identificado", geral)
        self.assertIn("Valores absolutos, sem ajuste por população", geral)
        individual = P.metricas_atividade(modelo, pessoa)
        self.assertIn('class="mapa-bairros"', individual)
        self.assertIn("Indicações de Ana Teste por bairro", individual)
        self.assertEqual(P.mapa_indicacoes(modelo, modelo["documentos"], "Título", limite_gzip=1), "")
        with mock.patch.object(P.gzip, "compress", return_value=b"x" * (12 * 1024 + 1)):
            sem_mapa = P.metricas_atividade(modelo, pessoa)
        self.assertNotIn('class="mapa-bairros"', sem_mapa)
        self.assertIn("Bairros das indicações por legislatura", sem_mapa)

    def test_sem_bairro_fica_fora_do_mapa_mas_na_nota(self):
        docs = [{"tipo": "indicacao", "bairro": None}, {"tipo": "indicacao", "bairro": "Icaraí"}]
        texto = P.mapa_indicacoes({"geo_bairros": geo_completo()}, docs, "Indicações")
        self.assertIn("50% sem bairro identificado (1 de 2 indicações), fora do mapa", texto)


class TestValidarGeo(unittest.TestCase):
    def test_completo_valido_e_tipos_invalidos(self):
        self.assertEqual(validar.validar_geo(geo_completo()), [])
        for valor in (None, [], "texto", {"bairros": []}):
            with self.subTest(valor=valor):
                self.assertTrue(validar.validar_geo(valor))

    def test_faltam_sobram_paths_e_atribuicao(self):
        geometria = geo_completo()
        del geometria["bairros"]["Badu"]
        geometria["bairros"]["Não oficial"] = {"path": ""}
        geometria["atribuicao"] = ""
        geometria["licenca"] = "outra"
        geometria["viewbox"] = [0, 0, False, 1000]
        texto = "\n".join(validar.validar_geo(geometria))
        for trecho in ("52 bairros", "Badu", "Não oficial", "path", "atribuicao", "ODbL", "viewbox"):
            self.assertIn(trecho, texto)

    def test_arquivo_opcional_integra_gerador_e_validacao(self):
        with tempfile.TemporaryDirectory() as pasta:
            raiz = Path(pasta)
            arquivos.salvar_lista(raiz / "data" / "proposicoes" / "2026.json", [])
            arquivos.salvar_json(raiz / "config" / "vereadores.json", {"legislaturas": []})
            self.assertIsNone(gerar_site.carregar_geo(raiz))
            self.assertEqual(validar.validar_tudo(raiz), [])
            caminho = raiz / "data" / "geo" / "bairros.json"
            arquivos.salvar_mapa(caminho, geo_completo())
            self.assertEqual(gerar_site.carregar_geo(raiz), geo_completo())
            self.assertEqual(validar.validar_tudo(raiz), [])
            arquivos.salvar_json(caminho, {"bairros": {}})
            self.assertTrue(any("data/geo/bairros.json" in p for p in validar.validar_tudo(raiz)))
            with self.assertRaisesRegex(ValueError, "data/geo/bairros.json"):
                gerar_site.carregar_geo(raiz)


if __name__ == "__main__":
    unittest.main()
