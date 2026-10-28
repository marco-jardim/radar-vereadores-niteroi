"""Confere o executor paralelo de testes versionado em scripts/testes.ps1."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SCRIPT = RAIZ / "scripts" / "testes.ps1"
PWSH = shutil.which("pwsh")
TESTE_OK = "import unittest\nclass T(unittest.TestCase):\n    def test_a(self):\n        pass\n"
TESTE_FALHA = "import unittest\nclass T(unittest.TestCase):\n    def test_a(self):\n        self.fail('x')\n"


def rodar(raiz: Path) -> subprocess.CompletedProcess:
    return subprocess.run([PWSH, "-NoProfile", "-File", str(SCRIPT), "-Raiz", str(raiz), "-Python", sys.executable],
                          capture_output=True, text=True, encoding="utf-8", timeout=300)


def contagem(saida: str) -> tuple[int, int, int]:
    m = re.search(r"python: (\d+) m\S+, (\d+) testes, (\d+) com falha", saida)
    assert m, saida
    return int(m[1]), int(m[2]), int(m[3])


def montar(raiz: Path, arquivos: dict[str, str]) -> None:
    for rel, texto in arquivos.items():
        caminho = raiz / rel
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(texto, encoding="utf-8")


class TestScriptTestes(unittest.TestCase):
    def test_script_versionado_sem_caminhos_locais(self):
        texto = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("-Recurse", texto)
        self.assertIn("-ErrorAction Stop", texto)
        self.assertIn("Pop-Location", texto)
        self.assertNotIn("Temp", texto)

    @unittest.skipUnless(PWSH, "pwsh indisponível")
    def test_mesmos_testes_que_o_discover_e_codigos_de_saida(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            montar(raiz, {"tests/__init__.py": "", "tests/test_ok.py": TESTE_OK, "tests/test_falha.py": TESTE_FALHA,
                          "tests/test_vazio.py": "import unittest\n", "tests/sub/__init__.py": "",
                          "tests/sub/test_x.py": TESTE_OK,
                          "tests/sem_pacote/test_y.py": TESTE_FALHA,
                          "tests/sem_pacote/sub/__init__.py": "",
                          "tests/sem_pacote/sub/test_z.py": TESTE_FALHA})
            discover = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                                      cwd=raiz, capture_output=True, text=True, encoding="utf-8", timeout=300)
            esperado = int(re.search(r"Ran (\d+) test", discover.stderr)[1])
            r = rodar(raiz)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            modulos, testes, falhas = contagem(r.stdout)
            self.assertEqual((modulos, testes, falhas), (4, esperado, 1))
            (raiz / "tests" / "test_falha.py").unlink()
            r = rodar(raiz)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(contagem(r.stdout), (3, esperado - 1, 0))

    @unittest.skipUnless(PWSH, "pwsh indisponível")
    def test_sem_testes_sai_com_erro(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            r = rodar(raiz)
            self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
            montar(raiz, {"tests/__init__.py": "", "tests/test_vazio.py": "import unittest\n"})
            r = rodar(raiz)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
