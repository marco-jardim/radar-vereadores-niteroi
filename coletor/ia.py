"""Cliente OpenCode Go compartilhado; o chamador fornece corpo e decodificação."""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

USER_AGENT = "radar-vereadores-niteroi/1.0 (+https://github.com/marco-jardim/radar-vereadores-niteroi)"


def decodificar_json(texto: str) -> Any:
    """Decodificação histórica do classificador, incluindo cercas e texto ao redor."""
    texto = re.sub(r"^```(?:json)?|```$", "", texto.strip(), flags=re.M)
    return json.loads(texto[texto.find("{"): texto.rfind("}") + 1])


def chamar(corpo: dict, chave: str, sessao: str, *, base_url: str,
           decodificar: Callable[[str], Any] = json.loads, user_agent: str = USER_AGENT,
           transporte=None, esperar=None, timeout: float = 180,
           prazo: float | None = None, relogio=None) -> Any:
    """POST com quatro tentativas; falha esgotada retorna {}, chave recusada lança PermissionError.

    Transporte e espera injetáveis permitem testes offline. A decodificação fica
    dentro das tentativas para conservar o comportamento histórico do classificador.
    prazo é um instante monotônico absoluto; limita timeout e esperas, sem mudar
    as chamadas existentes que o omitem.
    """
    transporte = transporte or urllib.request.urlopen
    esperar = esperar or time.sleep
    relogio = relogio or time.monotonic

    def aguardar(segundos):
        if prazo is not None:
            segundos = min(segundos, max(0, prazo - relogio()))
        if segundos > 0:
            esperar(segundos)

    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(corpo).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {chave}",
            "User-Agent": user_agent,
            "x-opencode-session": sessao,
        },
        method="POST",
    )
    for tentativa in range(4):
        restante = timeout if prazo is None else min(timeout, prazo - relogio())
        if restante <= 0:
            return {}
        try:
            with transporte(req, timeout=restante) as r:
                resposta = json.loads(r.read().decode())
            return decodificar(resposta["choices"][0]["message"]["content"])
        except urllib.error.HTTPError as e:
            corpo_erro = e.read().decode(errors="ignore")[:300]
            if e.code in (401, 403):
                raise PermissionError(f"OpenCode Go recusou a chave ({e.code}): {corpo_erro}")
            if e.code == 429:
                try:
                    espera = max(0, float(e.headers.get("Retry-After") or 30 * (tentativa + 1)))
                except ValueError:
                    espera = 30 * (tentativa + 1)
                print(f"  limite de uso; aguardando {espera}s", file=sys.stderr)
                aguardar(espera)
                continue
            print(f"  HTTP {e.code}: {corpo_erro}", file=sys.stderr)
        except (json.JSONDecodeError, KeyError, ValueError, urllib.error.URLError, TimeoutError) as e:
            print(f"  resposta inválida ({type(e).__name__}); tentando de novo", file=sys.stderr)
        aguardar(5 * (tentativa + 1))
    return {}
