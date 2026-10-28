"""AWS Signature Version 4 do cliente R2 contra os vetores oficiais da AWS (offline)."""
from __future__ import annotations

import hashlib
import unittest
from datetime import datetime, timezone

from coletor.nuvem import r2

# aws-sig-v4-test-suite (credenciais e data de todos os casos)
CHAVE = "AKIDEXAMPLE"
SEGREDO = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"
DATA = datetime(2015, 8, 30, 12, 36, 0, tzinfo=timezone.utc)
ESCOPO = "AKIDEXAMPLE/20150830/us-east-1/service/aws4_request"


def _assinatura(cabecalhos: dict[str, str]) -> str:
    return cabecalhos["Authorization"].rsplit("Signature=", 1)[1]


class TestChaveDeAssinatura(unittest.TestCase):
    def test_exemplo_da_documentacao(self):
        # "Examples of how to derive a signing key for Signature Version 4" (iam, 20120215)
        chave = r2.chave_assinatura(SEGREDO, "20120215", "us-east-1", "iam")
        self.assertEqual(chave.hex(), "f4780e2d9f65fa895f9c67b32ce1baf0b0d8a43505a000a1a9e090d414db404d")


class TestSuiteOficial(unittest.TestCase):
    def test_get_vanilla(self):
        url = "https://example.amazonaws.com/"
        cab = {"host": "example.amazonaws.com", "x-amz-date": "20150830T123600Z"}
        canonica, assinados = r2.requisicao_canonica("GET", url, cab, r2.HASH_VAZIO)
        self.assertEqual(canonica, "GET\n/\n\nhost:example.amazonaws.com\nx-amz-date:20150830T123600Z\n\n"
                                   "host;x-amz-date\n" + r2.HASH_VAZIO)
        self.assertEqual(assinados, "host;x-amz-date")
        self.assertEqual(hashlib.sha256(canonica.encode()).hexdigest(),
                         "bb579772317eb040ac9ed261061d46c1f17a8133879d6129b6e1c25292927e63")
        saida = r2.assinar("GET", url, {}, r2.HASH_VAZIO, CHAVE, SEGREDO, "us-east-1", "service", DATA)
        self.assertEqual(saida["x-amz-date"], "20150830T123600Z")
        self.assertEqual(saida["Authorization"],
                         f"AWS4-HMAC-SHA256 Credential={ESCOPO}, SignedHeaders=host;x-amz-date, "
                         "Signature=5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31")
        self.assertNotIn("host", {k.lower() for k in saida})  # o host vai pela URL

    def test_get_vanilla_query_order_key_case(self):
        url = "https://example.amazonaws.com/?Param2=value2&Param1=value1"
        cab = {"host": "example.amazonaws.com", "x-amz-date": "20150830T123600Z"}
        canonica, _ = r2.requisicao_canonica("GET", url, cab, r2.HASH_VAZIO)
        self.assertEqual(canonica.split("\n")[2], "Param1=value1&Param2=value2")
        saida = r2.assinar("GET", url, {}, r2.HASH_VAZIO, CHAVE, SEGREDO, "us-east-1", "service", DATA)
        self.assertEqual(_assinatura(saida), "b97d918cfa904a5beff61c982a1b6f458b799221646efd99d3219ec94cdf2500")

    def test_post_x_www_form_urlencoded(self):
        url = "https://example.amazonaws.com/"
        corpo = b"Param1=value1"
        hash_corpo = hashlib.sha256(corpo).hexdigest()
        self.assertEqual(hash_corpo, "9095672bbd1f56dfc5b65f3e153adc8731a4a654192329106275f4c7b24d0b6e")
        cab = {"Content-Type": "application/x-www-form-urlencoded"}
        canonica, assinados = r2.requisicao_canonica(
            "POST", url, {**cab, "host": "example.amazonaws.com", "x-amz-date": "20150830T123600Z"}, hash_corpo)
        self.assertEqual(assinados, "content-type;host;x-amz-date")
        self.assertEqual(canonica, "POST\n/\n\ncontent-type:application/x-www-form-urlencoded\n"
                                   "host:example.amazonaws.com\nx-amz-date:20150830T123600Z\n\n"
                                   "content-type;host;x-amz-date\n" + hash_corpo)
        saida = r2.assinar("POST", url, cab, hash_corpo, CHAVE, SEGREDO, "us-east-1", "service", DATA)
        self.assertEqual(_assinatura(saida), "ff11897932ad3f4e8b18135d722051e5ac45fc38421b1da7b9d196a0fe09473a")
        self.assertEqual(saida["Content-Type"], "application/x-www-form-urlencoded")


class TestS3(unittest.TestCase):
    def test_get_object_da_documentacao_s3(self):
        # "Signature Calculations for the Authorization Header: Transferring Payload in a Single Chunk"
        url = "https://examplebucket.s3.amazonaws.com/test.txt"
        cab = {"Range": "bytes=0-9", "x-amz-content-sha256": r2.HASH_VAZIO}
        saida = r2.assinar("GET", url, cab, r2.HASH_VAZIO, "AKIAIOSFODNN7EXAMPLE",
                           "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "us-east-1", "s3",
                           datetime(2013, 5, 24, tzinfo=timezone.utc))
        self.assertEqual(saida["Authorization"],
                         "AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request, "
                         "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date, "
                         "Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41")


class TestR2(unittest.TestCase):
    def test_endpoint_regiao_auto_e_caminho(self):
        cliente = r2.R2("chave", "segredo", conta="7b60055a9f153a4a8441ff519e1a208f")
        self.assertEqual(cliente.endpoint, "https://7b60055a9f153a4a8441ff519e1a208f.r2.cloudflarestorage.com")
        self.assertEqual(cliente.regiao, "auto")
        sha = "4bdbfe0974a8685415bbddb363b52455f430b3b445a906a9d934eff1f6b0e26e"
        self.assertEqual(r2.chave_r2(sha), f"sha256/4b/db/{sha}")
        self.assertEqual(cliente.url("radar-niteroi-arquivos", r2.chave_r2(sha)),
                         f"{cliente.endpoint}/radar-niteroi-arquivos/sha256/4b/db/{sha}")
        self.assertNotIn("segredo", repr(cliente))

    def test_escopo_r2_e_cabecalhos_assinados(self):
        url = "https://conta.r2.cloudflarestorage.com/bucket/sha256/aa/bb/x"
        cab = {"Content-Type": "application/pdf", "If-None-Match": "*", "x-amz-content-sha256": r2.HASH_VAZIO,
               "x-amz-meta-documentos": "doc:1,doc:2"}
        saida = r2.assinar("PUT", url, cab, r2.HASH_VAZIO, "AK", "SK", "auto", "s3", DATA)
        aut = saida["Authorization"]
        self.assertIn("Credential=AK/20150830/auto/s3/aws4_request", aut)
        self.assertIn("SignedHeaders=content-type;host;if-none-match;x-amz-content-sha256;x-amz-date;"
                      "x-amz-meta-documentos", aut)
        self.assertNotIn("SK", aut)

    def test_uri_codificada_uma_vez(self):
        self.assertEqual(r2.uri_canonica("/bucket/a b/ç"), "/bucket/a%20b/%C3%A7")
        self.assertEqual(r2.uri_canonica("/bucket/a%20b"), "/bucket/a%20b")
        self.assertEqual(r2.consulta_canonica("prefix=&list-type=2"), "list-type=2&prefix=")


if __name__ == "__main__":
    unittest.main()
