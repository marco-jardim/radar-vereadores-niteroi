"""Confere o executor paralelo de testes versionado em scripts/testes.ps1."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SCRIPT = RAIZ / "scripts" / "testes.ps1"
PWSH = shutil.which("pwsh")


class TestScriptTestes(unittest.TestCase):
    def test_script_versionado_descobre_os_mesmos_modulos(self):
        texto = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('-Filter "test_*.py"', texto)
        self.assertIn("python -m unittest", texto)
        self.assertIn("exit 1", texto)
        self.assertNotIn("Temp", texto)

    @unittest.skipUnless(PWSH, "pwsh indisponível")
    def test_sai_com_erro_quando_um_modulo_falha(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            (raiz / "tests").mkdir()
            (raiz / "tests" / "__init__.py").write_text("", encoding="utf-8")
            (raiz / "tests" / "test_ok.py").write_text(
                "import unittest\nclass T(unittest.TestCase):\n    def test_a(self):\n        pass\n", encoding="utf-8")
            (raiz / "tests" / "test_falha.py").write_text(
                "import unittest\nclass T(unittest.TestCase):\n    def test_a(self):\n        self.fail('x')\n",
                encoding="utf-8")
            r = subprocess.run([PWSH, "-NoProfile", "-File", str(SCRIPT), "-Raiz", str(raiz)],
                               capture_output=True, text=True, timeout=300)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("2 módulos, 2 testes, 1 com falha", r.stdout)
            (raiz / "tests" / "test_falha.py").unlink()
            r = subprocess.run([PWSH, "-NoProfile", "-File", str(SCRIPT), "-Raiz", str(raiz)],
                               capture_output=True, text=True, timeout=300)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
