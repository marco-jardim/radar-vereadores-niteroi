"""Contratos offline de privacidade e isolamento dos recursos do backend."""
from __future__ import annotations

import json
import unittest
from pathlib import Path


RAIZ = Path(__file__).resolve().parent.parent


def sem_comentarios_linha(texto: str) -> str:
    """Remove // só fora de strings JSON, respeitando aspas e barras escapadas."""
    partes = []
    em_string = False
    escape = False
    i = 0
    while i < len(texto):
        caractere = texto[i]
        if em_string:
            partes.append(caractere)
            if escape:
                escape = False
            elif caractere == "\\":
                escape = True
            elif caractere == '"':
                em_string = False
        elif texto.startswith("//", i):
            while i < len(texto) and texto[i] not in "\r\n":
                i += 1
            continue
        else:
            partes.append(caractere)
            if caractere == '"':
                em_string = True
        i += 1
    return "".join(partes)


class TestComentariosJsonc(unittest.TestCase):
    def test_preserva_urls_aspas_e_barras_escapadas(self):
        dados = {"url": "https://exemplo.org//caminho", "aspas": 'antes \\" // dentro',
                 "barra_final": "\\", "texto": "/* não é comentário de linha */"}
        texto = "// cabeçalho\r\n" + json.dumps(dados, ensure_ascii=False, indent=1) + " // fim"
        self.assertEqual(json.loads(sem_comentarios_linha(texto)), dados)

    def test_comentarios_entre_campos(self):
        texto = '{"a": 1, // primeiro\n "b": "https://exemplo.org" // segundo\n}\n// fim'
        self.assertEqual(json.loads(sem_comentarios_linha(texto)), {"a": 1, "b": "https://exemplo.org"})


class TestBackendConfig(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        texto = (RAIZ / "worker" / "wrangler.jsonc").read_text(encoding="utf-8")
        cls.cfg = json.loads(sem_comentarios_linha(texto))
        cls.backend = json.loads((RAIZ / "config" / "backend.json").read_text(encoding="utf-8"))

    def ambientes(self):
        return [(nome, self.cfg["env"][nome]) for nome in ("staging", "production")]

    def test_observabilidade_desligada(self):
        for nome, cfg in [("global", self.cfg), *self.ambientes()]:
            with self.subTest(ambiente=nome):
                self.assertIs(cfg["observability"]["enabled"], False)

    def test_sem_logpush_em_qualquer_nivel(self):
        def conferir(valor):
            if isinstance(valor, dict):
                self.assertNotIn("logpush", valor)
                for item in valor.values():
                    conferir(item)
            elif isinstance(valor, list):
                for item in valor:
                    conferir(item)

        conferir(self.cfg)

    def test_metadados_limite_cpu_migracoes_e_cron(self):
        for nome, cfg in self.ambientes():
            with self.subTest(ambiente=nome):
                self.assertEqual(cfg["version_metadata"]["binding"], "CF_VERSION_METADATA")
                cpu = cfg["limits"]["cpu_ms"]
                self.assertIs(type(cpu), int)
                self.assertGreater(cpu, 0)
                self.assertTrue(cfg["d1_databases"])
                for banco in cfg["d1_databases"]:
                    self.assertEqual(banco["migrations_dir"], "migrations")
                crons = cfg["triggers"]["crons"]
                self.assertIsInstance(crons, list)
                self.assertTrue(crons)
                self.assertTrue(all(isinstance(cron, str) and cron.strip() for cron in crons))

    def test_prefixo_de_todos_os_recursos(self):
        def conferir(valor):
            if isinstance(valor, dict):
                for chave, item in valor.items():
                    if chave in ("database_name", "index_name", "bucket_name"):
                        self.assertTrue(item.startswith("radar-niteroi"), item)
                    conferir(item)
            elif isinstance(valor, list):
                for item in valor:
                    conferir(item)

        conferir(self.cfg)
        for nome, cfg in [("global", self.cfg), *self.ambientes()]:
            with self.subTest(ambiente=nome):
                self.assertTrue(cfg["name"].startswith("radar-niteroi"))

    def test_recursos_separados_entre_ambientes(self):
        staging, producao = (cfg for _, cfg in self.ambientes())
        self.assertNotEqual(staging["name"], producao["name"])
        recursos = (("d1_databases", "database_id"), ("d1_databases", "database_name"),
                    ("vectorize", "index_name"), ("r2_buckets", "bucket_name"))
        for grupo, campo in recursos:
            with self.subTest(grupo=grupo, campo=campo):
                a = {item[campo] for item in staging[grupo]}
                b = {item[campo] for item in producao[grupo]}
                self.assertTrue(a)
                self.assertTrue(b)
                self.assertTrue(a.isdisjoint(b), f"{grupo}: recursos compartilhados: {a & b}")

    def test_cors_producao_igual_ao_config_versionado(self):
        self.assertEqual(self.cfg["env"]["production"]["vars"]["ORIGENS_CORS"],
                         ",".join(self.backend["origens_cors"]))


if __name__ == "__main__":
    unittest.main()
