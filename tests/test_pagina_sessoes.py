"""Contrato de apresentação de sessões: dados sintéticos, sem coleta nem IA."""
from __future__ import annotations

import copy
import gzip
import hashlib
import re
import unittest
from collections import Counter, defaultdict
from datetime import date, timedelta
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

from coletor.site import pagina_sessoes as S
from coletor.site import paginas as P


RAIZ = Path(__file__).resolve().parents[1]
TOKENS = ("presente", "consignado", "votou-ausente", "justificada", "ausente", "licenca",
          "voto-maioria", "voto-diferente", "voto-abstencao")


def presenca(**extra) -> dict:
    return {"P": 90, "C": 10, "V": 5, "J": 3, "A": 4, "L": 2,
            "denominador": 112, "presentes": 105, "pct": 94, **extra}


def modelo_sintetico(numero_sessoes: int = 12, numero_votacoes: int = 6, distribuicao_realista: bool = False) -> dict:
    """Contrato independente do agregador, com duas legislaturas e 21 pessoas.

    A distribuição realista tem 30% divididas, 20% dissenso e 50% unânimes.
    Os casos pequenos podem usar só divididas para exercitar os cartões.
    Ementas variam para não medir só a compressão de um texto repetido.
    """
    legs = [{"id": "2021-2024", "rotulo": "2021–2024", "anos": [2021, 2022, 2023, 2024]},
            {"id": "2025-2028", "rotulo": "2025–2028", "anos": [2025, 2026]}]
    pessoas = {f"pessoa-{i:02}": {"slug": f"pessoa-{i:02}", "nome": f"Pessoa {i:02}", "nome_siscam": f"PESSOA {i:02}",
                                "mandatos": {l["id"]: {"partido": f"P{i % 5}", "eleito": i != 20} for l in legs}}
               for i in range(21)}
    datas = []
    sessoes = []
    for i in range(numero_sessoes):
        # Distribui os registros pelos seis anos, sem usar o relógio.
        ano = 2021 + i % 6
        dia = date(ano, 1, 1) + timedelta(days=(i // 6 * 3) % 350)
        datas.append(dia.isoformat())
        tipo = ("ordinaria", "extraordinaria", "solene", "especial")[i % 4]
        sessoes.append({"id": i + 1, "data": dia.isoformat(), "hora": "14:00", "tipo": tipo,
                        "numero": i + 1, "titulo": f"{i + 1}ª sessão de {ano}",
                        "deliberativa": tipo in {"ordinaria", "extraordinaria"}, "realizada": True,
                        "marcas": [], "url_siscam": f"{P.SISCAM}DetalhesSessao.aspx?IdSessao={i + 1}", "votacoes": []})
    vocabulario = ("educação", "saúde", "mobilidade", "ruas", "escolas", "praças", "atendimento", "cultura",
                   "acessibilidade", "cadastro", "transporte", "proteção", "serviços", "moradores", "parques", "gestão")
    votacoes, por_ano, ritmo = [], defaultdict(Counter), defaultdict(lambda: defaultdict(Counter))
    for sessao in sessoes:
        ritmo[int(sessao["data"][:4])][sessao["data"][:7]][sessao["tipo"]] += 1
    for i in range(numero_votacoes):
        sessao = sessoes[i % len(sessoes)]
        classe = "dividida" if not distribuicao_realista or i % 10 < 3 else "dissenso" if i % 10 < 5 else "unanime"
        favor, contra, abstencao = {"dividida": (11, 6, 3), "dissenso": (18, 1, 0), "unanime": (20, 0, 0)}[classe]
        ausentes = 21 - favor - contra - abstencao
        votos, rotulos = {}, {}
        for j, slug in enumerate(pessoas):
            posicao = (j + i) % 21
            voto = "Favor" if posicao < favor else "Contra" if posicao < favor + contra else "Abstenção" if posicao < favor + contra + abstencao else "Ausente"
            votos[slug] = voto
            rotulos[slug] = {"Favor": "votou para manter o veto", "Contra": "votou para derrubar o veto",
                             "Abstenção": "absteve-se", "Ausente": "ausente nesta votação"}[voto]
        # Hash somente para variar as combinações de palavras, sem dados reais.
        resumo_hash = hashlib.sha256(f"ementa-{i}".encode()).digest()
        ementa = "Dispõe sobre " + " ".join(vocabulario[b % len(vocabulario)] for b in resumo_hash[:24]) + f" no programa {i + 1}."
        v = {"id": f"{sessao['id']}-{i}", "sessao": sessao["id"], "data": sessao["data"],
             "titulo_sessao": sessao["titulo"], "materia": "veto", "id_documento": 1000 + i,
             "documento": f"Veto ao PL {i + 1}/{sessao['data'][:4]}", "numero": f"{i + 1}/{sessao['data'][:4]}",
             "ementa": ementa, "url_documento": f"{P.SISCAM}DetalhesDocumentos.aspx?IdDocumento={1000 + i}",
             "resultado": "Veto Mantido", "totais": {"favor": favor, "contra": contra, "abstencao": abstencao, "ausentes": ausentes, "branco": 0, "nulo": 0},
             "classe": classe, "sentido": "favor_mantem", "fonte_sentido": "resultado_oficial", "maioria": "Favor",
             "quorum": {"exigido": 11, "derrubar": contra, "manter": favor}, "qualidade": "ok", "notas": [],
             "votos": votos, "rotulos": rotulos,
             "resumo": f"{favor} para manter · {contra} para derrubar · {P.plural(abstencao, 'abstenção', 'abstenções')} · {P.plural(ausentes, 'ausente', 'ausentes')}"}
        votacoes.append(v)
        sessao["votacoes"].append(v["id"])
        por_ano[int(v["data"][:4])][classe] += 1
    por_pessoa = {}
    for slug in pessoas:
        por_pessoa[slug] = {}
        for leg in legs:
            votos_leg = [v for v in votacoes if int(v["data"][:4]) in leg["anos"]]
            divergencias = [v["id"] for v in votos_leg if v["classe"] == "dividida" and v["votos"][slug] == "Contra"]
            como = Counter(v["rotulos"][slug] for v in votos_leg if v["votos"][slug] not in {"Ausente", "Presidente"})
            por_pessoa[slug][leg["id"]] = {
                "presenca": presenca(), "por_ano": {a: presenca() for a in leg["anos"] if a <= 2026},
                "participacao": {"votou": 61, "possiveis": 63, "presidindo": 2},
                "como_votou": {"veto": dict(como)}, "indeterminadas": 0,
                "divididas": sum(v["classe"] == "dividida" for v in votos_leg), "divergencias": divergencias,
            }
    dados = {"anos": list(range(2021, 2027)), "legislaturas": legs, "sessoes": sessoes, "votacoes": votacoes,
             "por_pessoa": por_pessoa, "mediana_presenca": {l["id"]: 92 for l in legs},
             "cobertura": {a: {"listadas": sum(d.startswith(str(a)) for d in datas), "com_frequencia": 1,
                                "com_votacao": 1, "pendentes": 0} for a in range(2021, 2027)},
             "placares_por_ano": {a: {c: cont[c] for c in ("unanime", "dissenso", "dividida", "inconsistente", "indeterminado")}
                                 for a, cont in por_ano.items()},
             "ritmo": {a: {m: dict(c) for m, c in meses.items()} for a, meses in ritmo.items()},
             "qualidade": {"sem_lista": [], "inconsistentes": [], "indeterminadas": [], "duplicados": [], "nao_membros": [], "notas": []}}
    return {"pessoas": pessoas, "sessoes": dados,
            "meta": {"coleta": {"em": "2026-10-20T15:00:00+00:00"}, "sessoes": {"em": "2026-10-23T15:00:00+00:00"}}}


class Documento(HTMLParser):
    """Árvore mínima para testar sem bibliotecas externas nem navegador."""
    VAZIOS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, texto: str):
        super().__init__()
        self.raiz = {"tag": "raiz", "attrs": {}, "filhos": []}
        self.pilha = [self.raiz]
        self.nos = []
        self.feed(texto)

    def handle_starttag(self, tag, attrs):
        no = {"tag": tag, "attrs": dict(attrs), "filhos": [], "pai": self.pilha[-1]}
        self.pilha[-1]["filhos"].append(no)
        self.nos.append(no)
        if tag not in self.VAZIOS:
            self.pilha.append(no)

    def handle_endtag(self, tag):
        for i in range(len(self.pilha) - 1, 0, -1):
            if self.pilha[i]["tag"] == tag:
                self.pilha = self.pilha[:i]
                break

    def handle_data(self, texto):
        self.pilha[-1]["filhos"].append(texto)

    def com_classe(self, classe: str) -> list[dict]:
        return [n for n in self.nos if classe in n["attrs"].get("class", "").split()]

    @staticmethod
    def texto(no: dict) -> str:
        return "".join(Documento.texto(f) if isinstance(f, dict) else f for f in no["filhos"])


class TestPaginaSessoes(unittest.TestCase):
    def setUp(self):
        self.modelo = modelo_sintetico()
        self.pessoa = self.modelo["pessoas"]["pessoa-00"]

    def test_pagina_completa_reutiliza_moldura_e_dialogo_sem_js_novo(self):
        with mock.patch.object(P, "pagina", wraps=P.pagina) as pagina:
            html = S.gerar_sessoes(self.modelo)
        self.assertTrue(html.startswith("<!doctype html>"))
        self.assertIn('<h1>Sessões e votações</h1>', html)
        self.assertIn("Sessões coletadas: 2021–2026", html)
        self.assertIn("dados do SISCAM de 23/10/2026", html)
        self.assertIn('href="metodologia.html#sessoes"', html)
        self.assertEqual(pagina.call_args.args[2], "sessoes.html")
        self.assertTrue(pagina.call_args.kwargs["dialogo"])
        doc = Documento(html)
        scripts = [n for n in doc.nos if n["tag"] == "script"]
        self.assertEqual(len(scripts), 2)
        self.assertTrue(all(n["attrs"].get("src", "").startswith(("app.js?", "dados.js?")) for n in scripts))
        self.assertTrue(all(not Documento.texto(n).strip() for n in scripts))
        self.assertIn('id="siscam-dialogo"', html)
        self.assertNotIn('<iframe', html)
        blocos = [n for n in doc.nos if n["attrs"].get("id", "").startswith("sessoes-leg-")]
        self.assertEqual([b["attrs"]["id"] for b in blocos], ["sessoes-leg-2025-2028", "sessoes-leg-2021-2024"])
        self.assertTrue(all(b["tag"] == "details" for b in blocos))
        self.assertIn("open", blocos[0]["attrs"])
        self.assertNotIn("open", blocos[1]["attrs"])
        self.assertFalse(any("hidden" in b["attrs"] for b in blocos))

    def test_presenca_bases_e_contrato_do_placar(self):
        r = self.modelo["sessoes"]["por_pessoa"]["pessoa-00"]["2025-2028"]
        r["presenca"] = presenca(P=4, C=1, V=0, J=1, A=0, L=2, denominador=6, presentes=5, pct=83)
        html = S.gerar_sessoes(self.modelo)
        self.assertIn("94% · 105 de 112", html)
        self.assertIn("5 de 6", html)
        self.assertNotIn("83%", html)
        self.assertIn("justificadas · 2 licenças (fora da base)", html)
        self.assertIn("Consignado: registro da Mesa", html)
        self.assertIn("Ausente na abertura, com voto registrado", html)
        self.assertIn("presença mediana dos eleitos", html)
        doc = Documento(html)
        linhas = doc.com_classe("linha")
        self.assertEqual(len(linhas), 42)
        for linha in linhas:
            self.assertIn("placar", linha["pai"]["attrs"]["class"])
            self.assertIn("legislatura", linha["pai"]["pai"]["attrs"]["class"])
            for atributo in ("data-nome", "data-eleito", "data-partido", "data-presenca", "data-denominador", "data-presentes"):
                self.assertIn(atributo, linha["attrs"])
        primeiro = linhas[0]
        self.assertIn("Pessoa 00", Documento.texto(primeiro))
        self.assertIn("P0", Documento.texto(primeiro))
        self.assertIn('href="vereadores/pessoa-00.html"', html)
        self.assertIn('id="ordem"', html)
        self.assertIn("suplente em exercício", html)

    def test_suplente_sem_pagina_tem_nome_condicao_e_nenhum_link(self):
        slug = "suplente-sem-pagina"
        nome = "Ana Maria de Souza"
        registros = copy.deepcopy(self.modelo["sessoes"]["por_pessoa"]["pessoa-00"])
        registros.update(sem_pagina=True, nome=nome, condicao="suplente em exercício")
        self.modelo["sessoes"]["por_pessoa"][slug] = registros
        for v in self.modelo["sessoes"]["votacoes"]:
            v["votos"][slug] = "Contra"
            v["rotulos"][slug] = "votou para derrubar o veto"
        html = S.gerar_sessoes(self.modelo)
        self.assertNotIn(f'vereadores/{slug}.html', html)
        doc = Documento(html)
        linhas = [n for n in doc.com_classe("linha") if n["attrs"]["data-nome"] == nome]
        self.assertEqual(len(linhas), 2)
        for linha in linhas:
            self.assertEqual(linha["attrs"]["data-eleito"], "0")
            self.assertIn(nome, Documento.texto(linha))
            self.assertIn("suplente em exercício", Documento.texto(linha))
            self.assertTrue(any(isinstance(f, dict) and f["tag"] == "span" and f["attrs"].get("class") == "quem" for f in linha["filhos"]))
        chips = [n for n in doc.com_classe("chip") if "Ana de Souza" in Documento.texto(n)]
        self.assertEqual(len(chips), 6)
        self.assertTrue(all(n["tag"] == "span" and "href" not in n["attrs"] for n in chips))
        self.assertTrue(all("suplente em exercício" in Documento.texto(n) for n in chips))
        # Mesmo com metadados no agregado, quem tem página continua com link.
        self.modelo["sessoes"]["por_pessoa"]["pessoa-00"].update(sem_pagina=True, nome="Pessoa 00")
        self.assertIn('href="vereadores/pessoa-00.html"', S.gerar_sessoes(self.modelo))
        self.assertIn("Presença e votos", S.secao_sessoes_vereador(self.modelo, self.pessoa))
        registros["nome"] = 'Ana <X> & Souza'
        registros["condicao"] = 'suplente <em exercício>'
        html = S.gerar_sessoes(self.modelo)
        self.assertIn(P.esc(registros["nome"]), html)
        self.assertIn(P.esc(registros["condicao"]), html)
        self.assertNotIn("<em exercício>", html)

    def test_chips_usam_nome_curto_e_rotulo_uma_vez_por_grupo(self):
        self.pessoa["nome"] = "Ana Maria de Souza"
        html = S.gerar_sessoes(self.modelo)
        chips = [n for n in Documento(html).com_classe("chip") if n["attrs"].get("href") == "vereadores/pessoa-00.html"]
        self.assertTrue(chips)
        self.assertTrue(all(Documento.texto(n) == "Ana de Souza" for n in chips))
        self.assertTrue(all("votou" not in Documento.texto(n) for n in chips))
        self.assertIn("Ana Maria de Souza", html)  # nome completo nas linhas e na tabela

    def test_metadados_do_suplente_no_registro_da_legislatura(self):
        slug = "suplente-sem-pagina"
        registros = copy.deepcopy(self.modelo["sessoes"]["por_pessoa"]["pessoa-00"])
        for registro in registros.values():
            registro.update(sem_pagina=True, nome="Ana Maria de Souza", condicao="suplente em exercício")
        self.modelo["sessoes"]["por_pessoa"][slug] = registros
        v = self.modelo["sessoes"]["votacoes"][0]
        v["votos"][slug] = "Contra"
        v["rotulos"][slug] = "votou para derrubar o veto"
        html = S.gerar_sessoes(self.modelo)
        self.assertNotIn(f'vereadores/{slug}.html', html)
        doc = Documento(html)
        self.assertEqual(sum(n["attrs"]["data-nome"] == "Ana Maria de Souza" for n in doc.com_classe("linha")), 2)
        chip = next(n for n in doc.com_classe("chip") if "Ana de Souza" in Documento.texto(n))
        self.assertEqual(chip["tag"], "span")
        self.assertIn("suplente em exercício", Documento.texto(chip))

    def test_cartoes_somente_divididas_e_limite_inicial(self):
        modelo = modelo_sintetico(12, 150)
        v = modelo["sessoes"]["votacoes"][0]
        v["classe"] = "unanime"
        html = S.gerar_sessoes(modelo)
        doc = Documento(html)
        cartoes = doc.com_classe("votacao")
        self.assertEqual(len(cartoes), 149)
        self.assertNotIn(f'id="v-{v["id"]}"', html)
        listas = [n for n in doc.com_classe("votacoes") if n["pai"]["tag"] != "details"]
        self.assertEqual(len(listas), 2)
        self.assertTrue(all(len(n["filhos"]) == 40 for n in listas))
        self.assertIn("Ver mais 10", html)
        self.assertIn("Ver mais 59", html)
        for lista in doc.com_classe("votacoes"):
            datas = [modelo["sessoes"]["votacoes"][int(n["attrs"]["id"].rsplit("-", 1)[1])]["data"] for n in lista["filhos"]]
            self.assertEqual(datas, sorted(datas, reverse=True))
        self.assertIn("Como votou cada vereador", html)
        self.assertIn("Resultado oficial: Veto Mantido", html)
        self.assertIn("11 para manter · 6 para derrubar", html)
        self.assertIn("1 ou 2 votos diferentes", html)
        self.assertIn("ao menos 3 votos no lado menor ou 3 abstenções", html)

    def test_veto_mantido_nao_inventa_maioria_e_mostra_nota(self):
        v = self.modelo["sessoes"]["votacoes"][0]
        v.update(sentido="favor_derruba", maioria="Favor", fonte_sentido="texto_veto_ambiguo",
                 totais={"favor": 10, "contra": 7, "abstencao": 3, "ausentes": 1},
                 quorum={"exigido": 11, "derrubar": 10, "manter": 7}, resumo="10 para derrubar · 7 para manter · 3 abstenções · 1 ausente")
        nota = "o SISCAM registra estes votos como 'Favor'; a tramitação os descreve como votos contrários ao parecer"
        v["notas"] = [nota]
        html = S.gerar_sessoes(self.modelo)
        self.assertIn("Derrubar o veto exige 11 votos (maioria absoluta dos 21 vereadores); houve 10.", html)
        self.assertIn("10 para derrubar · 7 para manter", html)
        self.assertIn(P.esc(nota), html)
        self.assertIn("Sentido definido pelo texto do parecer na tramitação.", html)
        self.assertNotIn("a maioria quis manter", html.lower())

    def test_notas_tecnicas_recolhidas_e_explicacao_ao_leitor_visivel(self):
        v = self.modelo["sessoes"]["votacoes"][0]
        leitor = "o SISCAM registra estes votos como 'Favor'; a tramitação os descreve como votos contrários ao parecer"
        tecnicas = ["conferência textual contra=10 ≠ nominal 0; a tramitação pode misturar votações",
                    "decisão do parecer no texto diverge do lado nominal vencedor; conferência, não exclusão",
                    "Conferência <script>não é HTML</script> & fonte"]
        quorum = "Veto derrubado sem 11 votos: conferir o quórum publicado."
        v["notas"] = [leitor, *tecnicas, quorum]
        self.modelo["sessoes"]["qualidade"]["notas"] = list(tecnicas)
        html = S.gerar_sessoes(self.modelo)
        doc = Documento(html)
        cartao = next(n for n in doc.com_classe("votacao") if n["attrs"]["id"] == f'v-{v["id"]}')
        visivel = " ".join(Documento.texto(n) for n in cartao["filhos"] if isinstance(n, dict) and n["tag"] == "p")
        self.assertIn(leitor, visivel)
        self.assertIn(quorum, visivel)
        for nota in tecnicas:
            self.assertNotIn(nota, visivel)
        conferencia = next(n for n in doc.com_classe("notas-conferencia") if n["pai"] is cartao)
        self.assertNotIn("open", conferencia["attrs"])
        self.assertIn("Notas de conferência (3)", Documento.texto(conferencia))
        self.assertIs(cartao["filhos"][-1], conferencia)
        for nota in tecnicas:
            self.assertIn(nota, Documento.texto(conferencia))
        qualidade = next(n for n in doc.nos if n["attrs"].get("id") == "qualidade-sessoes")
        for nota in tecnicas:
            self.assertIn(nota, Documento.texto(qualidade))
        self.assertNotIn("<script>não é HTML", html)
        self.assertNotIn("Sentido dos votos: resultado oficial e lado vencedor.", html)

    def test_linha_de_fonte_so_quando_relevante(self):
        v = copy.deepcopy(self.modelo["sessoes"]["votacoes"][0])
        for fonte in ("resultado_oficial", "curadoria", "nenhuma"):
            v["fonte_sentido"] = fonte
            self.assertFalse(Documento(S._cartao(self.modelo, v)).com_classe("fonte-sentido"))
        v["fonte_sentido"] = "texto_veto_ambiguo"
        fontes = Documento(S._cartao(self.modelo, v)).com_classe("fonte-sentido")
        self.assertEqual(len(fontes), 1)
        self.assertEqual(Documento.texto(fontes[0]), "Sentido definido pelo texto do parecer na tramitação.")
        v.update(qualidade="indeterminado", sentido="indeterminado")
        fontes = Documento(S._cartao(self.modelo, v)).com_classe("fonte-sentido")
        self.assertEqual(len(fontes), 1)
        self.assertIn("sentido não determinado", Documento.texto(fontes[0]))
        v.update(qualidade="inconsistente", sentido="inconsistente")
        cartao = S._cartao(self.modelo, v)
        self.assertFalse(Documento(cartao).com_classe("fonte-sentido"))
        self.assertIn("Placar inconsistente", cartao)

    def test_indeterminado_em_cinza_e_inconsistente_sem_nomes(self):
        v = self.modelo["sessoes"]["votacoes"][0]
        v.update(qualidade="indeterminado", sentido="indeterminado", quorum=None)
        html = S.gerar_sessoes(self.modelo)
        cartao = next(n for n in Documento(html).com_classe("votacao") if n["attrs"]["id"] == f'v-{v["id"]}')
        texto = Documento.texto(cartao)
        self.assertIn("Favor ao parecer", texto)
        self.assertIn("Contra o parecer", texto)
        self.assertIn("sentido não determinado", texto)
        self.assertNotIn("votou para manter o veto", texto)
        barra = next(n for n in cartao["filhos"] if isinstance(n, dict) and n["attrs"].get("class") == "mini-barra")
        self.assertTrue(all(n["attrs"]["class"] == "s-voto-abstencao" for n in barra["filhos"][:2]))
        v.update(qualidade="inconsistente", sentido="inconsistente", notas=["Total publicado diverge da lista nominal."])
        html = S.gerar_sessoes(self.modelo)
        cartao = next(n for n in Documento(html).com_classe("votacao") if n["attrs"]["id"] == f'v-{v["id"]}')
        texto = Documento.texto(cartao)
        self.assertIn("Placar inconsistente", texto)
        self.assertIn("Total publicado diverge", texto)
        self.assertIn("Placar oficial", next(n["attrs"]["aria-label"] for n in cartao["filhos"] if isinstance(n, dict) and n["attrs"].get("class") == "mini-barra"))
        self.assertNotIn("Pessoa", texto)
        self.assertNotIn("Como votou cada vereador", texto)
        self.assertNotIn("11 para manter", texto)

    def test_inconsistente_prefere_totais_oficiais_quando_conservados(self):
        v = self.modelo["sessoes"]["votacoes"][0]
        v.update(qualidade="inconsistente", sentido="inconsistente",
                 totais_oficiais={"favor": 13, "contra": 8, "abstencao": 0, "ausentes": 0})
        cartao = next(n for n in Documento(S.gerar_sessoes(self.modelo)).com_classe("votacao")
                      if n["attrs"]["id"] == f'v-{v["id"]}')
        texto = Documento.texto(cartao)
        self.assertIn("13 Favor ao parecer · 8 Contra o parecer", texto)
        self.assertNotIn("11 Favor ao parecer", texto)
        self.assertNotIn("Pessoa", texto)

    def test_links_siscam_e_contestacao(self):
        doc = Documento(S.gerar_sessoes(self.modelo))
        externos = [n for n in doc.nos if n["tag"] == "a" and n["attrs"].get("href", "").startswith(P.SISCAM + "Detalhes")]
        self.assertTrue(externos)
        for link in externos:
            self.assertEqual(link["attrs"].get("target"), "_blank")
            self.assertEqual(link["attrs"].get("rel"), "noopener")
        botoes = doc.com_classe("ver-siscam")
        self.assertEqual(len(botoes), 6)
        self.assertTrue(all(re.fullmatch(re.escape(P.SISCAM) + r"DetalhesDocumentos.aspx\?IdDocumento=\d+", n["attrs"]["data-url"]) for n in botoes))
        contestar = doc.com_classe("contestar")
        self.assertGreaterEqual(len(contestar), 7)
        self.assertTrue(all(n["attrs"]["href"].startswith(P.REPO + "/issues/new?") for n in contestar))

    def test_qualidade_e_ritmo_com_cobertura(self):
        qualidade = self.modelo["sessoes"]["qualidade"]
        for chave in qualidade:
            qualidade[chave] = [f"Ocorrência {chave} <conferir>"]
        html = S.gerar_sessoes(self.modelo)
        self.assertIn("Cobertura da coleta de sessões", html)
        for titulo in ("Sessões sem lista de frequência", "Placares inconsistentes", "Sentido não determinado",
                       "Duplicados resolvidos", "Registros de não membros", "Notas de conferência"):
            self.assertIn(titulo + ": 1", html)
        self.assertIn("Sessões por mês e tipo · 2026", html)
        self.assertIn("Sessões por ano e tipo", html)
        self.assertIn("Placares por ano · 2025–2028", html)
        self.assertIn("Dissenso isolado", html)
        self.assertIn("Ocorrência sem_lista &lt;conferir&gt;", html)

    def test_escape_de_todos_os_textos_e_determinismo_sem_mutacao(self):
        pessoa = self.pessoa
        pessoa["nome"] = 'Ana <script>alert("x")</script> & Cia'
        pessoa["mandatos"]["2025-2028"]["partido"] = 'P"<X>'
        v = self.modelo["sessoes"]["votacoes"][0]
        for campo in ("documento", "numero", "ementa", "resultado", "titulo_sessao", "resumo"):
            v[campo] = f'{campo} <img src=x onerror=alert(1)> & "teste"'
        v["notas"] = ['Nota <b>não é HTML</b> & fonte']
        v["rotulos"]["pessoa-00"] = 'Voto <i>texto</i> & fonte'
        v["url_documento"] += '&consulta="<x>'
        self.modelo["sessoes"]["qualidade"]["notas"] = [{"texto": "<svg onload=alert(1)>", "sessao": 1}]
        antes = copy.deepcopy(self.modelo)
        for renderizar in (S.gerar_sessoes, S.metodologia_sessoes, lambda m: S.secao_sessoes_vereador(m, pessoa)):
            html = renderizar(self.modelo)
            self.assertEqual(html, renderizar(self.modelo))
            self.assertNotIn("<img src=x", html)
            self.assertNotIn("<script>alert", html)
            self.assertNotIn("<svg onload", html)
        html = S.gerar_sessoes(self.modelo)
        self.assertIn(P.esc(pessoa["nome"]), html)
        self.assertIn(P.esc(v["ementa"]), html)
        self.assertIn(P.esc(v["rotulos"]["pessoa-00"]), html)
        self.assertIn(P.esc(v["notas"][0]), html)
        self.assertEqual(self.modelo, antes)

    def test_acessibilidade_barras_tabelas_ancoras_e_chips(self):
        for html in (S.gerar_sessoes(self.modelo), S.secao_sessoes_vereador(self.modelo, self.pessoa)):
            doc = Documento(html)
            ids = [n["attrs"]["id"] for n in doc.nos if "id" in n["attrs"]]
            self.assertEqual(len(ids), len(set(ids)))
            for no in doc.nos:
                if no["attrs"].get("role") == "img":
                    self.assertTrue(no["attrs"].get("aria-label"))
                if no["tag"] == "table":
                    self.assertTrue(any(isinstance(f, dict) and f["tag"] == "caption" and Documento.texto(f) for f in no["filhos"]))
                if no["tag"] == "th":
                    self.assertIn(no["attrs"].get("scope"), {"col", "row"})
                href = no["attrs"].get("href", "")
                if href.startswith("#"):
                    self.assertIn(href[1:], ids)
            for barra in doc.com_classe("presenca"):
                self.assertIn("licenças fora da base", barra["attrs"]["aria-label"])
                self.assertIn("105 de 112", barra["attrs"]["aria-label"])
                self.assertIn("Consignado: 10", barra["attrs"]["aria-label"])
            for chip in doc.com_classe("chip"):
                self.assertIn("Pessoa", Documento.texto(chip))
                self.assertNotIn("target", chip["attrs"])

    def test_secao_individual_tiles_comparacao_e_divergencias_mais_recentes(self):
        modelo = modelo_sintetico(12, 150)
        pessoa = modelo["pessoas"]["pessoa-00"]
        r = modelo["sessoes"]["por_pessoa"][pessoa["slug"]]["2025-2028"]
        r["indeterminadas"] = 7
        html = S.secao_sessoes_vereador(modelo, pessoa)
        self.assertIn('<section class="mandato sessoes" aria-labelledby="t-sessoes">', html)
        self.assertIn('id="t-sessoes">Presença e votos', html)
        self.assertIn("sessões plenárias e votações nominais", html)
        self.assertIn('href="../metodologia.html#sessoes"', html)
        self.assertIn("94% · 105 de 112", html)
        self.assertIn("acima da mediana dos eleitos (92%)", html)
        self.assertIn("3 justificadas · 2 licenças (fora da base)", html)
        self.assertIn("61 de 63", html)
        self.assertIn("2 presidindo", html)
        self.assertIn("Sentido não determinado: 7", html)
        self.assertIn("Como votou por matéria (sentidos determinados)", html)
        self.assertIn("Onde votou diferente da maioria", html)
        self.assertIn('href="../sessoes.html#sessoes-leg-2025-2028"', html)
        self.assertIn("Ver todas em Sessões", html)
        self.assertIn("Presença por ano", html)
        doc = Documento(html)
        self.assertEqual(len(doc.com_classe("tile")), 8)
        self.assertEqual(Documento.texto(doc.com_classe("tile-valor")[0]), "94%")
        self.assertEqual(Documento.texto(doc.com_classe("tile-rotulo")[0]), "105 de 112 sessões deliberativas")
        self.assertIn("Votações divididas com sentido conhecido; divergir não mede qualidade", html)
        listas = doc.com_classe("votos-diferentes")
        self.assertTrue(listas)
        self.assertTrue(all(len(n["filhos"]) <= 10 for n in listas))
        pagina = S.gerar_sessoes(modelo)
        ids = {n["attrs"]["id"] for n in Documento(pagina).nos if "id" in n["attrs"]}
        for link in (n for n in doc.nos if n["tag"] == "a"):
            href = link["attrs"].get("href", "")
            if href.startswith("../sessoes.html#"):
                self.assertIn(href.split("#")[1], ids)

    def test_estados_vazios_e_base_pequena(self):
        for dados in (None, {}, {"anos": list(range(2021, 2027)), "sessoes": [], "por_pessoa": {}}):
            modelo = {"sessoes": dados, "pessoas": {}}
            self.assertIn("Nenhuma sessão coletada", S.gerar_sessoes(modelo))
            self.assertIn("Nenhum registro de frequência com este nome", S.secao_sessoes_vereador(modelo, self.pessoa))
            self.assertIn('id="sessoes"', S.metodologia_sessoes(modelo))
        modelo = {"sessoes": {"anos": list(range(2021, 2027))}}
        self.assertIn("(2021–2026)", S.secao_sessoes_vereador(modelo, self.pessoa))
        r = self.modelo["sessoes"]["por_pessoa"][self.pessoa["slug"]]["2025-2028"]
        r["presenca"] = presenca(P=1, C=1, V=0, J=1, A=0, L=0, denominador=3, presentes=2, pct=67)
        html = S.secao_sessoes_vereador(self.modelo, self.pessoa)
        self.assertIn("2 de 3", html)
        self.assertNotIn("67%", html)
        self.assertIn("base inferior a 10 sessões", html)
        self.assertEqual(Documento.texto(Documento(html).com_classe("tile-valor")[0]), "2 de 3")
        r["presenca"] = dict.fromkeys(presenca(), 0)
        self.assertIn("Sem base de frequência", S.secao_sessoes_vereador(self.modelo, self.pessoa))

    def test_pessoa_pre_cadastrada_sem_registros_e_como_votou_sem_sentido(self):
        por_leg = self.modelo["sessoes"]["por_pessoa"][self.pessoa["slug"]]
        for registro in por_leg.values():
            registro["como_votou"] = {"pl": {"Favor ao parecer (sentido não determinado)": 7,
                                             "votou a favor do projeto": 2}}
        html = S.secao_sessoes_vereador(self.modelo, self.pessoa)
        self.assertNotIn("Favor ao parecer (sentido não determinado)", html)
        self.assertIn("a favor 2", html)
        for registro in por_leg.values():
            registro["presenca"] = dict.fromkeys(presenca(), 0)
            registro["participacao"] = {"votou": 0, "possiveis": 0, "presidindo": 0}
        html = S.secao_sessoes_vereador(self.modelo, self.pessoa)
        self.assertIn("Nenhum registro de frequência com este nome nas sessões coletadas (2021–2026)", html)
        self.assertNotIn('class="tiles"', html)

    def test_zeros_omitidos_e_plurais_na_presenca_e_participacao(self):
        for registro in self.modelo["sessoes"]["por_pessoa"][self.pessoa["slug"]].values():
            registro["presenca"].update(J=0, L=0)
            registro["participacao"]["presidindo"] = 0
            registro["indeterminadas"] = 1
        html = S.secao_sessoes_vereador(self.modelo, self.pessoa)
        for texto in ("0 licenças", "0 justificadas", "0 presidindo", "licenças fora da base: 0", ": 1 votações"):
            self.assertNotIn(texto, html)
        self.assertIn("Sentido não determinado: 1 votação.", html)
        r = self.modelo["sessoes"]["por_pessoa"][self.pessoa["slug"]]["2025-2028"]
        r["presenca"].update(J=1, A=0, L=1, pct=None)
        r["participacao"].update(votou=1, possiveis=1, presidindo=1)
        html = S.secao_sessoes_vereador(self.modelo, self.pessoa)
        doc = Documento(html)
        self.assertEqual(Documento.texto(doc.com_classe("tile-valor")[0]), "105 de 112")
        self.assertEqual(Documento.texto(doc.com_classe("tile-rotulo")[1]), "ausência")
        self.assertEqual(Documento.texto(doc.com_classe("tile-rotulo")[2]), "votação nominal em que votou")
        self.assertIn("1 justificada · 1 licença (fora da base)", html)
        self.assertIn("1 presidindo", html)
        pagina = Documento(S.gerar_sessoes(self.modelo))
        linha = next(n for n in pagina.com_classe("linha") if n["attrs"]["data-nome"] == self.pessoa["nome"])
        self.assertIn("1 justificada · 1 licença (fora da base)", Documento.texto(linha))

    def test_plurais_nos_placares_e_na_base_de_uma_sessao(self):
        v = copy.deepcopy(self.modelo["sessoes"]["votacoes"][0])
        v.update(qualidade="indeterminado", sentido="indeterminado",
                 totais={"favor": 10, "contra": 5, "abstencao": 1, "ausentes": 1, "branco": 1, "nulo": 2})
        html = S._cartao(self.modelo, v)
        for trecho in ("1 abstenção", "1 ausente", "1 voto em branco", "2 votos nulos"):
            self.assertIn(trecho, html)
        self.assertNotIn("1 abstenções", html)
        dados = {"votacoes": [v], "placares_por_ano": {2021: {"unanime": 1, "dissenso": 0, "dividida": 0}}}
        self.assertIn("Da 1 votação nominal de 2021, 1 foi unânime", S._resumo_placares(dados, [2021]))
        barra = S._barra_presenca(presenca(P=1, C=0, V=0, J=0, A=0, L=0, denominador=1, presentes=1, pct=None))
        self.assertIn("1 de 1 sessão deliberativa", barra)
        self.assertNotIn("licenças fora da base", barra)

    def test_como_votou_resumo_por_materia_e_tabela_acessivel(self):
        registro = {"indeterminadas": 1, "como_votou": {
            "pl": {"votou a favor do projeto": 82, "votou contra o projeto": 18, "absteve-se": 10,
                   "votou em branco": 2, "voto nulo": 1, "Favor ao parecer (sentido não determinado)": 7},
            "veto": {"votou para manter o veto": 9, "votou para derrubar o veto": 3, "absteve-se": 1},
            "pdl": {"Contra o parecer (sentido não determinado)": 4},
        }}
        html = S._como_votou(registro)
        doc = Documento(html)
        resumo = doc.com_classe("como-votou")[0]
        self.assertEqual(len(resumo["filhos"]), 2)
        self.assertEqual(Documento.texto(resumo["filhos"][0]),
                         "Projetos de lei — a favor 82 · contra 18 · abstenção 10 · branco 2 · nulo 1")
        self.assertEqual(Documento.texto(resumo["filhos"][1]), "Vetos — manter 9 · derrubar 3 · abstenção 1")
        self.assertNotIn("ao parecer", html)
        self.assertIn("Sentido não determinado: 1 votação.", html)
        tabela = doc.com_classe("tabela-como-votou")[0]
        self.assertNotIn("open", tabela["attrs"])
        colunas = [Documento.texto(n) for n in doc.nos if n["tag"] == "th" and n["attrs"].get("scope") == "col"]
        self.assertEqual(colunas, ["Matéria", "A favor do projeto ou manter o veto", "Contra ou derrubar", "Abstenção", "Total"])
        linhas = [n for n in doc.nos if n["tag"] == "tr" and n["pai"]["tag"] == "tbody"]
        self.assertEqual([[Documento.texto(c) for c in linha["filhos"]] for linha in linhas],
                         [["Projetos de lei", "82", "18", "10", "113"], ["Vetos", "9", "3", "1", "13"]])
        self.assertTrue(all(linha["filhos"][0]["attrs"]["scope"] == "row" for linha in linhas))
        self.assertIn("<caption>Como votou por matéria (sentidos determinados)</caption>", html)
        self.assertIn("O total inclui os outros registros discriminados no resumo", html)
        registro["como_votou"] = {"<matéria>": {"Outro <script>voto</script> & registro": 2}}
        html = S._como_votou(registro)
        self.assertIn("&lt;matéria&gt;", html)
        self.assertIn("Outro &lt;script&gt;voto&lt;/script&gt; &amp; registro 2", html)
        self.assertNotIn("<script>", html)

    def test_diferenca_em_frase_curta_sem_confundir_veto_e_maioria(self):
        v = self.modelo["sessoes"]["votacoes"][0]
        slug = self.pessoa["slug"]
        v.update(materia="pl", sentido="favor_aprova", maioria="Favor", resultado="Aprovado",
                 totais={"favor": 15, "contra": 5}, resumo="RESUMO LONGO NÃO DEVE SER REPETIDO")
        v["votos"][slug] = "Contra"
        v["rotulos"][slug] = "votou contra o projeto"
        registro = {"divergencias": [v["id"]]}
        leg = self.modelo["sessoes"]["legislaturas"][0]
        renderizar = lambda: S._diferentes(self.modelo["sessoes"], registro, slug, leg)
        html = renderizar()
        self.assertIn("Votou contra o projeto; a maioria votou a favor (15 × 5). Resultado oficial: Aprovado.", html)
        self.assertNotIn("Opção mais votada", html)
        self.assertNotIn("RESUMO LONGO", html)
        v.update(materia="veto", sentido="favor_derruba", resultado="Veto Mantido", totais={"favor": 10, "contra": 7})
        v["rotulos"][slug] = "votou para manter o veto"
        self.assertIn("Votou para manter o veto; a maioria votou para derrubar o veto (10 × 7). Resultado oficial: Veto Mantido.", renderizar())
        v.update(qualidade="indeterminado", sentido="indeterminado")
        html = renderizar()
        self.assertIn('class="sentido-indeterminado"', html)
        self.assertIn("Registrou “Contra o parecer”; a maioria registrou “Favor ao parecer” (10 × 7). Sentido não determinado.", html)
        self.assertNotIn("a maioria votou para derrubar", html)
        v.update(qualidade="ok", sentido="favor_derruba", resultado="Resultado <b>oficial</b>")
        v["rotulos"][slug] = "votou <script>texto</script>"
        self.assertIn("Votou &lt;script&gt;texto&lt;/script&gt;", renderizar())
        self.assertIn("Resultado &lt;b&gt;oficial&lt;/b&gt;", renderizar())

    def test_metodologia_explicita_regras_e_limites(self):
        html = S.metodologia_sessoes(self.modelo)
        for trecho in ("id=\"sessoes\"", "Consignado", "registro feito pela Mesa", "Licença", "fora da base",
                       "abertura com voto", "ordinárias e extraordinárias", "sobre o parecer da comissão",
                       "resultado oficial e do lado vencedor", "na mesma data", "maioria absoluta dos 21 vereadores",
                       "ao menos 3 votos no lado menor", "3 abstenções", "Não membros", "Comissões, debates",
                       "votações simbólicas", "não mede qualidade do mandato", "motivo de ausência", "contestar", "por issue"):
            self.assertIn(trecho, html)

    def test_neutralidade_sem_rotulos_politicos_nem_cores_de_alerta(self):
        for html in (S.gerar_sessoes(self.modelo), S.secao_sessoes_vereador(self.modelo, self.pessoa), S.metodologia_sessoes(self.modelo)):
            texto = unescape(re.sub(r"<[^>]*>", " ", html)).casefold()
            self.assertNotRegex(texto, r"\b(?:governo|oposição|bancada|governista|alinhamento|rebeldia|fidelidade)\b")
            self.assertNotRegex(html, r'class="[^"]*\b(?:c-alerta|n-alerta|tile-alerta|c-efeito|tile-efeito)\b')

    def test_contraste_tokens_nos_dois_temas(self):
        css = (RAIZ / "site_src/estilo.css").read_text(encoding="utf-8")
        self.assertEqual(css.count("/* ---- sessões */"), 1)
        blocos = re.findall(r"(:root(?:\[[^\]]+\]|:not\([^)]*\))?)\s*\{([^}]+)\}", css)
        temas = {"claro": {}, "escuro-auto": {}, "escuro-explicito": {}}
        for seletor, bloco in blocos:
            valores = dict(re.findall(r"--([\w-]+):\s*(#[0-9A-Fa-f]{6})", bloco))
            if seletor == ":root":
                for tema in temas.values():
                    # Um segundo :root no fim fornece só os tokens novos.
                    tema.update(valores)
            elif ":not" in seletor:
                temas["escuro-auto"].update(valores)
            else:
                temas["escuro-explicito"].update(valores)

        def luminancia(cor: str) -> float:
            canais = [int(cor[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in canais]
            return sum(v * peso for v, peso in zip(linear, (.2126, .7152, .0722)))

        for nome, tema in temas.items():
            for token in TOKENS:
                with self.subTest(tema=nome, token=token):
                    self.assertIn(token, tema)
                    a, b = sorted([luminancia(tema[token]), luminancia(tema["superficie"])])
                    self.assertGreaterEqual((b + .05) / (a + .05), 3)
                    self.assertNotEqual(tema[token].lower(), tema["alerta"].lower())
                    self.assertNotEqual(tema[token].lower(), tema["efeito"].lower())
        for token in TOKENS:
            self.assertEqual(temas["escuro-auto"][token], temas["escuro-explicito"][token])

    def test_orcamento_gzip_com_600_sessoes_500_votacoes_21_pessoas(self):
        modelo = modelo_sintetico(600, 500, distribuicao_realista=True)
        self.assertEqual(len(modelo["sessoes"]["sessoes"]), 600)
        self.assertEqual(len(modelo["sessoes"]["votacoes"]), 500)
        self.assertEqual(len(modelo["pessoas"]), 21)
        self.assertEqual(len(modelo["sessoes"]["legislaturas"]), 2)
        self.assertEqual(Counter(v["classe"] for v in modelo["sessoes"]["votacoes"]),
                         {"dividida": 150, "dissenso": 100, "unanime": 250})
        html = S.gerar_sessoes(modelo).encode("utf-8")
        tamanho = len(gzip.compress(html, mtime=0))
        secoes = [len(gzip.compress(S.secao_sessoes_vereador(modelo, p).encode("utf-8"), mtime=0)) for p in modelo["pessoas"].values()]
        maior = max(secoes)
        print(f"\nSessões (sintético: 600/500/21/2, 30% divididas): página {len(html)} B brutos / {tamanho} B gzip; maior seção individual {maior} B gzip.")
        self.assertLessEqual(tamanho, 100 * 1024, "teto oficial: 100 KiB gzip; alvo de 60 KiB medido com os dados reais")
        self.assertLessEqual(maior, 10 * 1024, "seção individual: até +10 KiB gzip")


if __name__ == "__main__":
    unittest.main()
