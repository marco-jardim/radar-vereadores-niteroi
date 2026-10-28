"""Detecção de exportações locais pendentes, inclusive publicações interrompidas."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from coletor.nuvem.fonte import Fonte
from coletor.nuvem.rede import ErroNuvem
from coletor.nuvem.sincronizar import _exportacoes_pendentes


class TestExportacoesPendentes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="radar-exportacoes-")
        self.addCleanup(self.tmp.cleanup)
        self.pasta = Path(self.tmp.name)
        self.versao = "a" * 16
        self.destino = self.pasta / self.versao
        self.destino.mkdir()
        self.sha = "b" * 64
        remocoes = {("siscam:1", self.sha): ("siscam:1", self.sha, "Teste sintético.", "2026-01-01")}
        self.fonte = Fonte(linhas={"remocoes": remocoes}, trechos={}, vetores={}, ementas={},
                           originais={}, remover_r2={f"originais/{self.sha}"}, sha256_manifestos="")
        self.atual = {"arquivos": {}, "remocoes": remocoes.copy(), "estado_indice": None}
        self.sql = f"d1-{self.versao}.sql"
        self.vetores = f"vetores-{self.versao}-001.jsonl.gz"
        self.dump = (f"INSERT INTO arquivos VALUES ('siscam:1', '{self.sha}', 'pdf', "
                     "'extraido', 0, NULL, NULL);\n").encode("utf-8")

    def pendentes(self):
        return _exportacoes_pendentes(self.fonte, self.atual, self.pasta, False)

    def test_sem_manifesto_ignora_conjuntos_incompletos_e_temporarios(self):
        for nomes in ([], [".parcial"], [self.sql], [self.vetores], [self.sql, "outro.tmp"],
                      [f"d1-{self.versao}-002.sql", self.vetores]):
            with self.subTest(nomes=nomes):
                for arquivo in self.destino.iterdir():
                    arquivo.unlink()
                for nome in nomes:
                    (self.destino / nome).write_bytes(b"parcial")
                self.assertFalse(self.pendentes())

    def test_sem_manifesto_confere_dump_completo_ignorando_dotfiles_e_tmp(self):
        (self.destino / self.sql).write_bytes(self.dump)
        (self.destino / self.vetores).write_bytes(b"")
        (self.destino / ".SHA256SUMS.tmp").write_bytes(b"parcial")
        (self.destino / "vetores.tmp").write_bytes(b"parcial")
        (self.destino / ".DS_Store").write_bytes(b"ignorado")
        self.assertTrue(self.pendentes())
        (self.destino / self.sql).write_bytes(b"-- sem arquivos removidos\n")
        self.assertFalse(self.pendentes())

    def test_com_manifesto_confere_dump_e_preserva_erro_de_manifesto_invalido(self):
        arquivos = {self.sql: self.dump, self.vetores: b""}
        for nome, dados in arquivos.items():
            (self.destino / nome).write_bytes(dados)
        somas = "".join(f"{hashlib.sha256(dados).hexdigest()}  {nome}\n"
                        for nome, dados in sorted(arquivos.items()))
        (self.destino / "SHA256SUMS").write_bytes(somas.encode("ascii"))
        (self.destino / "extra.tmp").write_bytes(b"parcial")
        self.assertTrue(self.pendentes())
        (self.destino / "SHA256SUMS").write_bytes(b"invalido\n")
        with self.assertRaises(ErroNuvem):
            self.pendentes()
