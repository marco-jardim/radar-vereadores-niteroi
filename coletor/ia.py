"""Cliente OpenCode Go compartilhado; o chamador fornece corpo e decodificação."""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

USER_AGENT = "radar-vereadores-niteroi/1.0 (+https://github.com/marco-jardim/radar-vereadores-niteroi)"


def chamar(corpo: dict, chave: str, sessao: str, *, base_url: str,
           decodificar: Callable[[str], Any] = json.loads, user_agent: str = USER_AGENT,
           transporte=None, esperar=None, timeout: float = 180) -> Any:
    """POST com quatro tentativas; falha esgotada retorna {}, chave recusada lança PermissionError.

    Transporte e espera injetáveis permitem testes offline. A decodificação fica
    dentro das tentativas para conservar o comportamento histórico do classificador.
    """
    transporte = transporte or urllib.request.urlopen
    esperar = esperar or time.sleep
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
        try:
            with transporte(req, timeout=timeout) as r:
                resposta = json.loads(r.read().decode())
            return decodificar(resposta["choices"][0]["message"]["content"])
        except urllib.error.HTTPError as e:
            corpo_erro = e.read().decode(errors="ignore")[:300]
            if e.code in (401, 403):
                raise PermissionError(f"OpenCode Go recusou a chave ({e.code}): {corpo_erro}")
            if e.code == 429:
                espera = int(e.headers.get("Retry-After") or 30 * (tentativa + 1))
                print(f"  limite de uso; aguardando {espera}s", file=sys.stderr)
                esperar(espera)
                continue
            print(f"  HTTP {e.code}: {corpo_erro}", file=sys.stderr)
        except (json.JSONDecodeError, KeyError, ValueError, urllib.error.URLError, TimeoutError) as e:
            print(f"  resposta inválida ({type(e).__name__}); tentando de novo", file=sys.stderr)
        esperar(5 * (tentativa + 1))
    return {}
