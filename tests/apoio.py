"""Utilidades compartilhadas pelos testes (não é um módulo de testes)."""
from __future__ import annotations

import io
import json
import os
import threading
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def ler_fixture(*partes: str) -> str:
    """Lê uma fixture (somente leitura) decodificando como siscam.baixar, sem traduzir quebras de linha."""
    return FIXTURES.joinpath(*partes).read_bytes().decode("utf-8", "ignore")


class SaidaQueSinaliza(io.StringIO):
    """StringIO que dispara `evento` assim que o texto acumulado contém `trecho`.

    Usada no lugar de sys.stderr para liberar threads simuladas que esperam um aviso do
    código testado (por exemplo, o de interrupção dos detalhes), sem depender de tempo.
    """

    def __init__(self, trecho: str, evento: threading.Event) -> None:
        super().__init__()
        self.trecho = trecho
        self.evento = evento

    def write(self, texto: str) -> int:
        escrito = super().write(texto)
        if self.trecho in self.getvalue():
            self.evento.set()
        return escrito


def registro_versionado(ano: int, id_doc: int) -> dict | None:
    """Registro guardado em data/proposicoes/<ano>.json, ou None se não existir.

    Também devolve None quando RADAR_COLETA=1 (testes da coleta semanal): os dados recém-coletados
    podem divergir legitimamente das fixtures estáticas, e essa comparação não deve barrar o commit.
    """
    if os.environ.get("RADAR_COLETA") == "1":
        return None
    arq = RAIZ / "data" / "proposicoes" / f"{ano}.json"
    if not arq.exists():
        return None
    registros = json.loads(arq.read_text(encoding="utf-8"))
    if not isinstance(registros, list):
        return None
    return next((p for p in registros if isinstance(p, dict) and p.get("id") == id_doc), None)
