"""Propostas e aplicação de contatos públicos, com dados sintéticos e sem rede."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import tempfile
import unicodedata
import unittest
from pathlib import Path
from unittest import mock

from coletor import contatos, mascara, validar


class TestContatos(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)
        self.cache = self.raiz / "cache"
        self.cache.mkdir()
        perfil = {"mandatos": {}, "eleicoes": [], "camara": None, "site": None, "redes": []}
        self.perfis = {"_leia_me": "Teste", "vereadores": {
            "ANA MARIA TESTE": copy.deepcopy(perfil), "BIA TESTE": copy.deepcopy(perfil)}}
        self.backend = {"api_url": None, "origens_cors": ["https://exemplo.org"], "contatos_institucionais": []}
        self.cfg = {"legislaturas": [], "nao_vereador": ["PREFEITURA"], "apelidos": {}}
        self.gravar("config/perfis.json", self.perfis)
        self.gravar("config/backend.json", self.backend)
        self.gravar("config/vereadores.json", self.cfg)

    def gravar(self, nome: str, dados):
        caminho = self.raiz / nome
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes((json.dumps(dados, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
        return caminho

    def documento(self, id_: int, autor: str | None, texto: str, data: str = "2026-01-01", pl=False):
        tipo = "pl" if pl else "requerimento"
        (self.cache / f"{tipo}-{id_}.txt").write_text(texto, encoding="utf-8")
        caminho = self.raiz / ("data/proposicoes/2026.json" if pl else "data/documentos/requerimento/2026.json")
        registros = json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else []
        autores = [{"nome": autor, "papel": "Autor", "origem": "Vereador"}] if autor else []
        registro = {"id": id_, "ano": 2026, "data": data, "tipo": tipo}
        registro["autoria" if pl else "autores"] = autores
        registros.append(registro)
        self.gravar(str(caminho.relative_to(self.raiz)), registros)

    def propor(self, min_docs=3):
        return contatos.candidatos(self.raiz, self.cache, min_docs)

    def test_recorrencia_autor_principal_e_fonte_mais_recente(self):
        texto = "Gabinete: ana@gmail.com; celular (21) 99999-8888. " * 4
        for id_, data in ((10, "2026-01-10"), (20, "2026-03-01"), (30, "2026-02-01")):
            self.documento(id_, "Ana Maria Teste", texto, data, pl=id_ == 10)
        # Coautor vem antes na lista, mas o papel Autor identifica o principal do PL.
        arq = self.raiz / "data/proposicoes/2026.json"
        pl = json.loads(arq.read_text(encoding="utf-8"))
        pl[0]["autoria"].insert(0, {"nome": "BIA TESTE", "papel": "Co-Autor", "origem": "Vereador"})
        self.gravar("data/proposicoes/2026.json", pl)
        proposta = self.propor()
        self.assertEqual(len(proposta["perfis"]), 2)
        for entrada in proposta["perfis"]:
            self.assertEqual(entrada["siscam"], "ANA MARIA TESTE")
            self.assertEqual(entrada["fonte"], contatos.URL_DOCUMENTO.format(20))
            self.assertEqual(entrada["evidencias"]["documentos"], 3)
            self.assertEqual(entrada["evidencias"]["proporcao"], 1)
            self.assertEqual(entrada["evidencias"]["documentos_ids"], [10, 20, 30])
        self.assertEqual({e["valor"] for e in proposta["perfis"]}, {"ana@gmail.com", "21999998888"})
        self.assertEqual(proposta, self.propor())

    def test_minimo_proporcao_e_desconhecidos_no_denominador(self):
        for id_ in range(1, 4):
            self.documento(id_, "ANA MARIA TESTE", "ana@gmail.com unico@gmail.com" if id_ == 1 else "ana@gmail.com")
        self.documento(4, "BIA TESTE", "ana@gmail.com")
        # Sem registro nos dados: ainda é um documento do denominador.
        (self.cache / "pl-99.txt").write_text("ana@gmail.com", encoding="utf-8")
        proposta = self.propor()
        [entrada] = proposta["perfis"]
        self.assertEqual(entrada["valor"], "ana@gmail.com")
        self.assertEqual(entrada["evidencias"]["proporcao"], .6)
        self.assertEqual(entrada["evidencias"]["total_documentos"], 5)
        self.assertEqual(self.propor(4)["perfis"], [])
        (self.cache / "pl-100.txt").write_text("ana@gmail.com", encoding="utf-8")
        self.assertEqual(self.propor()["perfis"], [])

    def test_conta_documentos_nao_repeticoes_ou_copias_de_tipo(self):
        self.documento(1, "ANA MARIA TESTE", "ana@gmail.com " * 8)
        (self.cache / "outro-1.txt").write_text("ana@gmail.com " * 8, encoding="utf-8")
        self.assertEqual(self.propor()["perfis"], [])
        self.assertEqual(self.propor()["documentos_lidos"], 1)

    def test_orgaos_contexto_anterior_de_80_caracteres(self):
        for id_ in range(1, 4):
            self.documento(id_, "ANA MARIA TESTE", "Câmara Municipal — Telefone (21) 3333-4444.\n"
                            "Ouvidoria: 2620-1234.\n" + "Prefeitura " + "x" * 81 + " (21) 2222-3333.\n"
                            "(21) 4444-5555 Secretaria Municipal")
        proposta = self.propor()
        institucionais = proposta["contatos_institucionais"]
        self.assertEqual({e["valor"] for e in institucionais}, {"2133334444", "2126201234"})
        for entrada in institucionais:
            self.assertEqual(entrada["evidencias"]["documentos"], 3)
            self.assertTrue(entrada["descricao"])
            self.assertEqual(entrada["fonte"], contatos.URL_DOCUMENTO.format(3))

    def test_detecta_publicos_e_telefones_so_com_evidencia(self):
        texto = ("servidor@tjrj.jus.br ana@gmail.com tel 21999998888; (21) 3333-4444; 2620-1234; "
                 "código 21988887777; Lei nº 3456-7890; CPF 529.982.247-25; CEP 24020-000; "
                 "https://exemplo.org/3333-9999")
        achados = {(t, v) for t, v, _ in contatos._encontrar(texto)}
        self.assertEqual(achados, {("email", "servidor@tjrj.jus.br"), ("email", "ana@gmail.com"),
                                   ("telefone", "21999998888"), ("telefone", "2133334444"), ("telefone", "2126201234")})

    def test_autor_executivo_ou_desconhecido_nao_ganha_perfil(self):
        for id_ in range(1, 4):
            self.documento(id_, "PREFEITURA", "prefeitura@gmail.com")
        self.assertEqual(self.propor()["perfis"], [])

    def proposta_aprovada(self):
        return {"versao": 1, "perfis": [{
            "siscam": "ANA MARIA TESTE", "tipo": "email", "valor": "ana@gmail.com",
            "fonte": contatos.URL_DOCUMENTO.format(1), "descricao": "Gabinete de Joa\u0303o",
            "evidencias": {"documentos": 3, "total_documentos": 3},
        }], "contatos_institucionais": [{
            "tipo": "telefone", "valor": "2133334444", "descricao": "Câmara Municipal",
            "fonte": contatos.URL_DOCUMENTO.format(2), "evidencias": {"documentos": 3},
        }]}

    def test_aplica_valida_preserva_ordem_e_formato_idempotente(self):
        proposta = self.gravar("aprovados.json", self.proposta_aprovada())
        resultado = contatos.aplicar(self.raiz, proposta)
        self.assertEqual(resultado, {"perfis": 1, "contatos_institucionais": 1})
        self.assertEqual(validar.validar_perfis(self.raiz / "config/perfis.json", self.cfg), [])
        self.assertEqual(validar.validar_backend(self.raiz), [])
        for nome, original in (("perfis", self.perfis), ("backend", self.backend)):
            bruto = (self.raiz / f"config/{nome}.json").read_bytes()
            texto = bruto.decode("utf-8")
            dados = json.loads(texto)
            self.assertEqual(list(dados), list(original))
            self.assertEqual(texto, contatos._texto(dados))
            self.assertTrue(unicodedata.is_normalized("NFC", texto))
            self.assertNotIn(b"\r", bruto)
            self.assertNotIn("evidencias", texto)
        perfis = json.loads((self.raiz / "config/perfis.json").read_text(encoding="utf-8"))
        ana = perfis["vereadores"]["ANA MARIA TESTE"]
        self.assertEqual(list(ana), [*self.perfis["vereadores"]["ANA MARIA TESTE"], "contatos"])
        for chave, valor in self.perfis["vereadores"]["ANA MARIA TESTE"].items():
            self.assertEqual(ana[chave], valor)
        antes = {p: p.read_bytes() for p in (self.raiz / "config").glob("*.json")}
        self.assertEqual(contatos.aplicar(self.raiz, proposta), {"perfis": 0, "contatos_institucionais": 0})
        self.assertEqual(antes, {p: p.read_bytes() for p in antes})
        liberados = mascara.liberados(self.raiz)
        self.assertEqual(mascara.mascarar("ana@gmail.com e (21) 3333-4444", liberados)[0],
                         "ana@gmail.com e (21) 3333-4444")

    def test_rejeita_proposta_invalida_sem_gravar_config(self):
        antes = {p: p.read_bytes() for p in (self.raiz / "config").glob("*.json")}
        casos = []
        for campo, valor in (("tipo", "fax"), ("valor", "@gmail.com"), ("fonte", "http://exemplo.org"),
                             ("siscam", "INEXISTENTE"), ("descricao", "")):
            dados = self.proposta_aprovada()
            dados["perfis"][0][campo] = valor
            casos.append(dados)
        dados = self.proposta_aprovada()
        dados["perfis"].append({**dados["perfis"][0], "siscam": "BIA TESTE"})
        casos.append(dados)
        dados = self.proposta_aprovada()
        del dados["contatos_institucionais"][0]["descricao"]
        casos.append(dados)
        for dados in casos:
            with self.subTest(dados=dados):
                proposta = self.gravar("aprovados.json", dados)
                with self.assertRaises(ValueError):
                    contatos.aplicar(self.raiz, proposta)
                self.assertEqual(antes, {p: p.read_bytes() for p in antes})

    def test_reverte_se_segundo_arquivo_falha(self):
        proposta = self.gravar("aprovados.json", self.proposta_aprovada())
        antes = {p: p.read_bytes() for p in (self.raiz / "config").glob("*.json")}
        gravar = contatos.gravar_atomico

        def falhar(caminho, texto):
            if caminho == self.raiz / "config/backend.json":
                raise OSError("falha sintética")
            return gravar(caminho, texto)

        with mock.patch.object(contatos, "gravar_atomico", side_effect=falhar), self.assertRaises(OSError):
            contatos.aplicar(self.raiz, proposta)
        self.assertEqual(antes, {p: p.read_bytes() for p in antes})

    def test_cli_candidatos_nao_altera_config_e_aplica_so_explicitamente(self):
        for id_ in range(1, 4):
            self.documento(id_, "ANA MARIA TESTE", "ana@gmail.com")
        antes = {p: p.read_bytes() for p in (self.raiz / "config").glob("*.json")}
        with mock.patch.object(contatos, "RAIZ", self.raiz), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(contatos.main(["--candidatos", "--cache", str(self.cache)]), 0)
            proposta = self.raiz / ".qa/contatos_propostos.json"
            self.assertTrue(proposta.is_file())
            self.assertEqual(antes, {p: p.read_bytes() for p in antes})
            self.assertEqual(contatos.main(["--aplicar", str(proposta)]), 0)
        self.assertNotEqual((self.raiz / "config/perfis.json").read_bytes(), antes[self.raiz / "config/perfis.json"])

    def test_cli_recusa_saida_em_config_ou_data(self):
        antes = (self.raiz / "config/perfis.json").read_bytes()
        with mock.patch.object(contatos, "RAIZ", self.raiz), contextlib.redirect_stderr(io.StringIO()):
            for nome in ("config/perfis.json", "data/proposicoes/2026.json"):
                self.assertEqual(contatos.main(["--candidatos", "--cache", str(self.cache),
                                                "--saida", str(self.raiz / nome)]), 1)
        self.assertEqual((self.raiz / "config/perfis.json").read_bytes(), antes)


if __name__ == "__main__":
    unittest.main()
