"""Cliente S3 do R2 com AWS Signature Version 4 (só `hmac` e `hashlib`).

Endpoint `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`, região `auto`, endereço
por caminho (`/<bucket>/<chave>`). Operações: `enviar` (PUT, por padrão com
`If-None-Match: *`: o R2 responde 412 se o objeto já existe, de forma atômica),
`existe` (HEAD), `obter` (GET), `apagar` (DELETE, usado só pela remoção) e `listar`
(ListObjectsV2). Credenciais em `R2_ACCESS_KEY_ID` e `R2_SECRET_ACCESS_KEY`; o
segredo nunca aparece em mensagens.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time
import urllib.parse
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from coletor.nuvem.rede import TENTATIVAS, ErroNuvem, Resposta, requisitar

ALGORITMO = "AWS4-HMAC-SHA256"
HASH_VAZIO = hashlib.sha256(b"").hexdigest()
REGIAO = "auto"
SERVICO = "s3"
SEGUROS = "-_.~"


# ---------------------------------------------------------------- SigV4
def _hmac(chave: bytes, mensagem: str) -> bytes:
    return hmac.new(chave, mensagem.encode("utf-8"), hashlib.sha256).digest()


def chave_assinatura(segredo: str, dia: str, regiao: str, servico: str) -> bytes:
    """kSigning = HMAC(HMAC(HMAC(HMAC("AWS4" + segredo, dia), região), serviço), "aws4_request")."""
    k_data = _hmac(("AWS4" + segredo).encode("utf-8"), dia)
    k_regiao = _hmac(k_data, regiao)
    k_servico = _hmac(k_regiao, servico)
    return _hmac(k_servico, "aws4_request")


def codificar(texto: str, seguros: str = SEGUROS) -> str:
    """Codificação de URI do SigV4: tudo fora de A-Z a-z 0-9 - _ . ~ vira %XX (UTF-8, maiúsculas)."""
    return urllib.parse.quote(texto, safe=seguros)


def uri_canonica(caminho: str) -> str:
    """Caminho codificado uma vez (regra do S3), sem normalizar segmentos."""
    return codificar(urllib.parse.unquote(caminho or "/"), SEGUROS + "/")


def consulta_canonica(consulta: str) -> str:
    """Pares `chave=valor` codificados e ordenados pela chave (e pelo valor)."""
    pares = urllib.parse.parse_qsl(consulta, keep_blank_values=True)
    return "&".join(f"{k}={v}" for k, v in sorted((codificar(k), codificar(v)) for k, v in pares))


def cabecalhos_canonicos(cabecalhos: Mapping[str, Any]) -> tuple[str, str]:
    """(bloco `nome:valor\\n` em minúsculas e ordenado, lista `a;b;c` dos cabeçalhos assinados)."""
    normais: dict[str, str] = {}
    for nome, valor in cabecalhos.items():
        normais[nome.strip().lower()] = " ".join(str(valor).strip().split())
    nomes = sorted(normais)
    return "".join(f"{n}:{normais[n]}\n" for n in nomes), ";".join(nomes)


def requisicao_canonica(metodo: str, url: str, cabecalhos: Mapping[str, Any], hash_corpo: str) -> tuple[str, str]:
    """(requisição canônica, cabeçalhos assinados); `cabecalhos` já inclui host e x-amz-date."""
    partes = urllib.parse.urlsplit(url)
    bloco, assinados = cabecalhos_canonicos(cabecalhos)
    canonica = "\n".join([metodo.upper(), uri_canonica(partes.path), consulta_canonica(partes.query),
                          bloco, assinados, hash_corpo])
    return canonica, assinados


def assinar(metodo: str, url: str, cabecalhos: Mapping[str, Any], hash_corpo: str, chave_acesso: str,
            segredo: str, regiao: str, servico: str, agora: datetime) -> dict[str, str]:
    """Cabeçalhos a enviar: os recebidos, `x-amz-date` e `Authorization` (o `host` vem da URL)."""
    data_amz = agora.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dia = data_amz[:8]
    todos = {k: v for k, v in cabecalhos.items() if k.lower() != "x-amz-date"}
    if not any(k.lower() == "host" for k in todos):
        todos["host"] = urllib.parse.urlsplit(url).netloc
    todos["x-amz-date"] = data_amz
    canonica, assinados = requisicao_canonica(metodo, url, todos, hash_corpo)
    escopo = f"{dia}/{regiao}/{servico}/aws4_request"
    texto = "\n".join([ALGORITMO, data_amz, escopo, hashlib.sha256(canonica.encode("utf-8")).hexdigest()])
    assinatura = hmac.new(chave_assinatura(segredo, dia, regiao, servico), texto.encode("utf-8"),
                          hashlib.sha256).hexdigest()
    saida = {k: str(v) for k, v in todos.items() if k.lower() != "host"}
    saida["Authorization"] = (f"{ALGORITMO} Credential={chave_acesso}/{escopo}, "
                              f"SignedHeaders={assinados}, Signature={assinatura}")
    return saida


# ---------------------------------------------------------------- cliente
def chave_r2(sha256: str) -> str:
    """`sha256/<aa>/<bb>/<sha256>` (contrato, seção 4.1)."""
    return f"sha256/{sha256[:2]}/{sha256[2:4]}/{sha256}"


class R2:
    """Cliente S3 mínimo do R2."""

    def __init__(self, chave_acesso: str, segredo: str, *, conta: str | None = None, endpoint: str | None = None,
                 regiao: str = REGIAO, tentativas: int = TENTATIVAS, dormir: Callable[[float], Any] = time.sleep,
                 relogio: Callable[[], datetime] | None = None) -> None:
        if not endpoint and not conta:
            raise ValueError("informe a conta ou o endpoint do R2")
        self.endpoint = (endpoint or f"https://{conta}.r2.cloudflarestorage.com").rstrip("/")
        self.regiao = regiao
        self.tentativas = tentativas
        self._chave = chave_acesso
        self._segredo = segredo
        self._dormir = dormir
        self._relogio = relogio or (lambda: datetime.now(timezone.utc))

    def __repr__(self) -> str:
        return f"R2(endpoint={self.endpoint!r})"

    @classmethod
    def do_ambiente(cls, conta: str, env: Mapping[str, str] = os.environ, **kw) -> R2:
        chave, segredo = env.get("R2_ACCESS_KEY_ID"), env.get("R2_SECRET_ACCESS_KEY")
        if not chave or not segredo:
            raise ErroNuvem("defina R2_ACCESS_KEY_ID e R2_SECRET_ACCESS_KEY")
        return cls(chave, segredo, conta=conta, **kw)

    def url(self, bucket: str, chave: str = "", consulta: str = "") -> str:
        caminho = "/" + bucket + ("/" + chave if chave else "")
        return self.endpoint + codificar(caminho, SEGUROS + "/") + ("?" + consulta if consulta else "")

    def _pedir(self, metodo: str, bucket: str, chave: str = "", *, consulta: str = "", corpo: bytes = b"",
               cabecalhos: Mapping[str, str] | None = None, aceitar=()) -> Resposta:
        url = self.url(bucket, chave, consulta)
        hash_corpo = hashlib.sha256(corpo).hexdigest()
        base = {**(cabecalhos or {}), "x-amz-content-sha256": hash_corpo}

        def assinar_agora() -> dict[str, str]:
            return assinar(metodo, url, base, hash_corpo, self._chave, self._segredo, self.regiao, SERVICO,
                           self._relogio())

        return requisitar(metodo, url, corpo if metodo in ("PUT", "POST") else None, None, aceitar=aceitar,
                          tentativas=self.tentativas, dormir=self._dormir, segredos=(self._segredo,),
                          assinar=assinar_agora)

    def enviar(self, bucket: str, chave: str, dados: bytes, tipo: str = "application/octet-stream",
               metadados: Mapping[str, str] | None = None, se_ausente: bool = True) -> bool:
        """PUT do objeto; True se gravou, False se já existia (412 com `If-None-Match: *`)."""
        cab = {"Content-Type": tipo}
        for nome, valor in (metadados or {}).items():
            if not str(valor).isascii():
                raise ValueError(f"metadado {nome} precisa ser ASCII")
            cab[f"x-amz-meta-{nome}"] = str(valor)
        if se_ausente:
            cab["If-None-Match"] = "*"
        r = self._pedir("PUT", bucket, chave, corpo=dados, cabecalhos=cab, aceitar=(412,))
        return r.status != 412

    def existe(self, bucket: str, chave: str) -> bool:
        return self._pedir("HEAD", bucket, chave, aceitar=(404,)).status != 404

    def obter(self, bucket: str, chave: str) -> bytes | None:
        r = self._pedir("GET", bucket, chave, aceitar=(404,))
        return None if r.status == 404 else r.corpo

    def apagar(self, bucket: str, chave: str) -> None:
        self._pedir("DELETE", bucket, chave, aceitar=(404,))

    def listar(self, bucket: str, prefixo: str = "") -> list[str]:
        """Chaves sob `prefixo` (ListObjectsV2, com paginação)."""
        chaves: list[str] = []
        token = None
        while True:
            params = {"list-type": "2", "prefix": prefixo}
            if token:
                params["continuation-token"] = token
            consulta = urllib.parse.urlencode(sorted(params.items()), quote_via=urllib.parse.quote)
            raiz = ET.fromstring(self._pedir("GET", bucket, consulta=consulta).corpo)
            for el in raiz.iter():
                if el.tag.rsplit("}", 1)[-1] == "Key" and el.text:
                    chaves.append(el.text)
            truncado = next((el.text for el in raiz.iter() if el.tag.rsplit("}", 1)[-1] == "IsTruncated"), "false")
            token = next((el.text for el in raiz.iter()
                          if el.tag.rsplit("}", 1)[-1] == "NextContinuationToken"), None)
            if truncado != "true" or not token:
                return chaves
