"""Gera as fixtures do contrato de textos (`docs/contratos/textos.md`).

Os textos são sintéticos; nomes, números e endereços não correspondem a pessoas
reais. O pipeline é o real: `trechos.normalizar` → `limpeza.limpar` →
`mascara.mascarar` → `trechos.normalizar` → `trechos.dividir`, com o manifesto
gravado por `arquivos.salvar_mapa`. Mesma entrada, mesmos bytes;
`tests/test_contratos.py` gera de novo numa pasta temporária e compara com os
arquivos versionados.

Uso (na raiz do repositório):
  python tests/fixtures/contratos/gerar_fixtures.py
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parent.parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from coletor import arquivos, limpeza, mascara, trechos  # noqa: E402
from coletor.extratores import VERSAO_EXTRATORES  # noqa: E402

ANO = 2024
PROCESSADO_EM = "2026-10-27"
STATUS_COM_TEXTO = ("ok", "ok_ocr", "ocr_baixa_confianca")
CLICHES = frozenset({limpeza.normalizar_linha("CÂMARA MUNICIPAL DE NITERÓI")})
URL_DOWNLOAD = "https://consultaniteroi.siscam.com.br/Download.aspx?id={id}"
URL_SESSOES = "https://consultaniteroi.siscam.com.br/Arquivos/Sessoes/{guid}.docx"
GUID_ATA = "00000000-0000-4000-8000-0000000000a1"

EMENTA_PL = "Institui o Programa Municipal Sintético de Leitura nas Praças de Niterói."
EMENTA_REQ = "Requer informações sintéticas sobre a manutenção das praças do município."

TEXTO_PL = "\n".join([
    "CÂMARA MUNICIPAL DE NITERÓI",
    "PROJETO DE LEI Nº 900/2024",
    "",
    EMENTA_PL,
    "",
    "Art. 1º Fica instituído o Programa Municipal Sintético de Leitura nas Praças, com o objetivo de "
    "ampliar o acesso a livros, revistas e jornais em espaços públicos abertos, por meio de estantes "
    "comunitárias instaladas em praças, parques e outros logradouros do município.",
    "",
    "Art. 2º O programa será desenvolvido em parceria com bibliotecas públicas, escolas, associações de "
    "moradores e coletivos culturais, que poderão propor a localização das estantes, organizar rodas de "
    "leitura e manter o acervo em boas condições de uso, sem custo para o leitor.",
    "",
    "Art. 3º As despesas decorrentes da execução desta Lei correrão por conta das dotações orçamentárias "
    "próprias, suplementadas se necessário. Esta Lei entra em vigor na data de sua publicação.",
    "",
    "JUSTIFICATIVA",
    "",
    "A leitura em espaços públicos aproxima as pessoas dos livros e fortalece a convivência nos bairros. "
    "Experiências semelhantes em outras cidades mostram que estantes comunitárias são simples de manter, "
    "têm baixo custo e alcançam leitores de todas as idades, especialmente crianças e pessoas idosas.",
    "",
    "O projeto não cria cargos nem despesas obrigatórias: organiza parcerias que já ocorrem de maneira "
    "informal e dá a elas regras claras de funcionamento, transparência e prestação de contas à população, "
    "com relatório anual publicado no portal oficial do município.",
    "",
    "Contato do gabinete para dúvidas: (21) 98888-7777.",
    "Sala das Sessões, 10 de março de 2024.",
])

TEXTO_ANEXO = "\f".join([
    "\n".join([
        "PREFEITURA SINTÉTICA DE EXEMPLO",
        "Anexo técnico do projeto de leitura nas praças",
        "",
        "Este anexo descreve as estantes comunitárias previstas: estrutura de madeira tratada, cobertura "
        "contra chuva, capacidade para cerca de cem volumes e placa com as regras de uso do acervo.",
        "",
        "Página 1 de 2",
    ]),
    "\n".join([
        "PREFEITURA SINTÉTICA DE EXEMPLO",
        "Mapa ilustrativo das praças atendidas na primeira etapa do programa, com a indicação dos pontos "
        "de instalação sugeridos pelas associações de moradores durante as reuniões públicas.",
        "~ ,; .",
        "Página 2 de 2",
    ]),
])

TEXTO_REQ = "\n".join([
    "CÂMARA MUNICIPAL DE NITERÓI",
    "REQUERIMENTO Nº 901/2024",
    "",
    EMENTA_REQ,
    "",
    "DENISE FULANA SINTÉTICA, RG 12.345.678-9, CPF. 123.456 789-09, e-mail "
    "denise.sintetica@exemplo.com, moradora do bairro, solicita ao Poder Executivo o cronograma de "
    "manutenção das praças e a relação dos contratos vigentes de conservação de áreas verdes.",
    "",
    "Sala das Sessões, 5 de dezembro de 2024.",
])

TEXTO_ATA = "\n".join([
    "ATA DA 10ª SESSÃO ORDINÁRIA SINTÉTICA",
    "",
    "Aos quinze dias do mês de fevereiro, reuniu-se a Câmara em sessão ordinária sintética. Na abertura, "
    "a banda escolar executou o hino com o símbolo 𝄞 impresso no programa distribuído ao público, e a "
    "Presidência saudou as pessoas presentes nas galerias.",
    "",
    "No expediente, foram lidos os projetos sintéticos protocolados na semana, inclusive o Projeto de Lei "
    "nº 900/2024, que institui o programa de leitura nas praças. A Secretaria informou que as dúvidas "
    "podem ser enviadas a secretaria@camaraniteroi.rj.gov.br, endereço institucional da Câmara.",
    "",
    "Na ordem do dia, a matéria foi discutida por diversos oradores, que destacaram a importância das "
    "bibliotecas comunitárias, a necessidade de manutenção periódica das estantes e o papel das escolas "
    "na formação de novos leitores. Encerrada a discussão, a votação foi adiada para a sessão seguinte, "
    "a pedido da liderança, para que as comissões pudessem concluir seus pareceres sobre o texto.",
    "",
    "Nada mais havendo a tratar, a Presidência encerrou a sessão, e eu, secretário sintético, lavrei a "
    "presente ata, que, lida e aprovada, será assinada por quem de direito, na forma regimental.",
])

# Registros sintéticos dos documentos (como em data/): o ano do manifesto vem de `ano`.
REGISTROS = {
    "doc:127858": {"tipo": "pl", "numero": 900, "ano": 2024, "data": "2024-03-10"},
    "doc:266596": {"tipo": "substitutivo", "numero": 1, "ano": 2024, "data": "2024-06-20", "pl": "doc:127858"},
    # protocolado em 2024, com data do documento em 2025: o manifesto é o de 2024
    "doc:290001": {"tipo": "requerimento", "numero": 901, "ano": 2024, "data": "2025-01-03"},
    "doc:290002": {"tipo": "pdl", "numero": 902, "ano": 2024, "data": "2024-08-01"},
    "sessao:5001": {"tipo": "ata", "numero": 10, "ano": 2024, "data": "2024-02-15"},
}

ARQUIVOS = [
    {"chave": "siscam:900001", "documentos": ["doc:266596", "doc:127858"], "documento": "doc:127858",
     "tipo": "pl", "original": b"PK\x03\x04 docx sintetico do PL 900/2024 e do substitutivo",
     "formato": "docx", "extrator": "docx", "versao_extrator": VERSAO_EXTRATORES, "paginas": 0,
     "paginas_ocr": 0, "confianca": None, "status": "ok", "cabecalhos_omitidos": 2,
     "ocr_paginas": None, "ementa": EMENTA_PL, "bruto": TEXTO_PL},
    {"chave": "siscam:900002", "documentos": ["doc:127858"], "documento": "doc:127858",
     "tipo": "pl", "original": b"%PDF-1.7 anexo sintetico com pagina escaneada",
     "formato": "pdf", "extrator": "pdftotext+tesseract", "versao_extrator": "25.07.0+5.5.3", "paginas": 2,
     "paginas_ocr": 1, "confianca": 87.43, "status": "ok_ocr", "cabecalhos_omitidos": 0,
     "ocr_paginas": {2}, "ementa": EMENTA_PL, "bruto": TEXTO_ANEXO},
    {"chave": "siscam:900003", "documentos": ["doc:290001"], "documento": "doc:290001",
     "tipo": "requerimento", "original": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1 doc sintetico do requerimento",
     "formato": "doc", "extrator": "doc", "versao_extrator": VERSAO_EXTRATORES, "paginas": 0,
     "paginas_ocr": 0, "confianca": None, "status": "ok", "cabecalhos_omitidos": 0,
     "ocr_paginas": None, "ementa": EMENTA_REQ, "bruto": TEXTO_REQ},
    {"chave": f"sessao:{GUID_ATA}", "documentos": ["sessao:5001"], "documento": "sessao:5001",
     "tipo": "ata", "url_origem": URL_SESSOES.format(guid=GUID_ATA),
     "original": b"PK\x03\x04 docx sintetico da ata da sessao 5001",
     "formato": "docx", "extrator": "docx", "versao_extrator": VERSAO_EXTRATORES, "paginas": 0,
     "paginas_ocr": 0, "confianca": None, "status": "ok", "cabecalhos_omitidos": 0,
     "ocr_paginas": None, "ementa": "", "bruto": TEXTO_ATA},
    {"chave": "siscam:900004", "documentos": ["doc:290002"], "documento": "doc:290002",
     "tipo": "pdl", "original": b"%PDF-1.7 pdl sintetico removido a pedido", "status": "removido"},
]

REMOCOES = {"remocoes": [{
    "chave": "siscam:900004",
    "sha256": hashlib.sha256(ARQUIVOS[-1]["original"]).hexdigest(),
    "motivo": "Exemplo sintético de pedido de titular (art. 18 da LGPD).",
    "fonte": "https://github.com/marco-jardim/radar-vereadores-niteroi/issues",
    "data": "2026-01-15",
}]}


def sha256(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


def r2_chave(sha: str) -> str:
    """Chave do original no R2: sha256/<aa>/<bb>/<sha256>."""
    return f"sha256/{sha[:2]}/{sha[2:4]}/{sha}"


def caminho_texto(tipo: str, ano: int, documento: str, chave: str) -> str:
    """textos/<tipo>/<ano>/<documento sem prefixo>/<origem>-<id>.txt"""
    return f"textos/{tipo}/{ano}/{documento.split(':', 1)[1]}/{chave.replace(':', '-', 1)}.txt"


def caminho_trechos(tipo: str, ano: int) -> str:
    return f"trechos/{tipo}/{ano}.jsonl"


def linha_trecho(trecho: dict) -> str:
    return json.dumps(trecho, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sem_texto(base: dict) -> dict:
    base.update({
        "formato": None, "extrator": None, "versao_extrator": None, "versao_extratores": None,
        "versao_limpeza": None, "versao_mascara": None, "versao_trechos": None, "paginas": 0,
        "paginas_ocr": 0, "confianca": None, "cabecalhos_omitidos": 0, "detalhe": "",
        "limpeza": None, "mascarados": None, "sha256_bruto": None, "sha256_texto": None,
        "chars": 0, "trechos": 0, "trechos_vetorizaveis": 0, "r2_chave": None,
    })
    return base


def processar(spec: dict) -> tuple[dict, tuple[str, str] | None, list[dict]]:
    """Entrada do manifesto, (caminho, conteúdo) do .txt e os trechos de um arquivo."""
    chave = spec["chave"]
    original = spec["original"]
    sha_original = sha256(original)
    id_origem = chave.split(":", 1)[1]
    base = {
        "documentos": sorted(spec["documentos"]),
        "documento": spec["documento"],
        "tipo": spec["tipo"],
        "url_origem": spec.get("url_origem") or URL_DOWNLOAD.format(id=id_origem),
        "sha256_original": sha_original,
        "bytes": len(original),
        "status": spec["status"],
        "commit_textos": None,
        "processado_em": PROCESSADO_EM,
    }
    if spec["status"] not in STATUS_COM_TEXTO:
        return _sem_texto(base), None, []
    bruto = trechos.normalizar(spec["bruto"])
    limpo, contagens = limpeza.limpar(bruto, CLICHES, ementa=spec["ementa"],
                                      ocr_paginas=spec["ocr_paginas"])
    mascarado, mascarados = mascara.mascarar(limpo)
    texto = trechos.normalizar(mascarado)
    fortes = [o for o in mascara.varrer(texto) if o["forte"]]
    if fortes:  # barreira de PII, como em coletor.textos --commit-textos
        raise RuntimeError(f"{chave}: {len(fortes)} ocorrência(s) forte(s) depois da máscara")
    lista = trechos.dividir(texto, spec["documento"], chave)
    conteudo = texto + "\n"
    confianca = spec["confianca"]
    base.update({
        "formato": spec["formato"],
        "extrator": spec["extrator"] or None,
        "versao_extrator": spec["versao_extrator"] or None,
        "versao_extratores": VERSAO_EXTRATORES,
        "versao_limpeza": limpeza.VERSAO_LIMPEZA,
        "versao_mascara": mascara.VERSAO_MASCARA,
        "versao_trechos": trechos.VERSAO_TRECHOS,
        "paginas": spec["paginas"],
        "paginas_ocr": spec["paginas_ocr"],
        "confianca": None if confianca is None else round(float(confianca), 1),
        "cabecalhos_omitidos": spec["cabecalhos_omitidos"],
        "detalhe": "",
        "limpeza": {
            "linhas_removidas": contagens["linhas_removidas"],
            "por_regra": {regra: contagens[regra]
                          for regra in ("cabecalho_rodape", "numeracao", "ruido_ocr", "cliche")},
        },
        "mascarados": {tipo: mascarados[tipo] for tipo in mascara.TIPOS},
        "sha256_bruto": sha256(bruto.encode("utf-8")),
        "sha256_texto": sha256(conteudo.encode("utf-8")),
        "chars": len(texto),
        "trechos": len(lista),
        "trechos_vetorizaveis": sum(t["vetorizavel"] for t in lista),
        "r2_chave": r2_chave(sha_original),
    })
    caminho = caminho_texto(spec["tipo"], ANO, spec["documento"], chave)
    return base, (caminho, conteudo), lista


def _json_config(obj: dict) -> str:
    """Formato dos configs editoriais: indent=1, ordem das chaves preservada."""
    return json.dumps(obj, ensure_ascii=False, indent=1) + "\n"


def gerar(destino: Path) -> None:
    """Grava manifesto, registros, remoções e a árvore dados-textos em `destino`."""
    destino = Path(destino)
    dados_textos = destino / "dados-textos"
    if dados_textos.exists():
        shutil.rmtree(dados_textos)
    manifesto: dict[str, dict] = {}
    por_arquivo_trechos: dict[str, list[dict]] = {}
    for spec in ARQUIVOS:
        entrada, texto, lista = processar(spec)
        manifesto[spec["chave"]] = entrada
        if texto is not None:
            caminho, conteudo = texto
            alvo = dados_textos / caminho
            alvo.parent.mkdir(parents=True, exist_ok=True)
            alvo.write_bytes(conteudo.encode("utf-8"))
        if lista:
            por_arquivo_trechos.setdefault(caminho_trechos(spec["tipo"], ANO), []).extend(lista)
    for caminho, lista in sorted(por_arquivo_trechos.items()):
        lista.sort(key=lambda t: (t["documento"], t["arquivo"], t["posicao"]))
        alvo = dados_textos / caminho
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_bytes(("".join(linha_trecho(t) + "\n" for t in lista)).encode("utf-8"))
    arquivos.salvar_mapa(destino / f"manifesto-{ANO}.json", manifesto)
    arquivos.salvar_mapa(destino / "registros.json", REGISTROS)
    (destino / "config").mkdir(parents=True, exist_ok=True)
    (destino / "config" / "remocoes.json").write_bytes(_json_config(REMOCOES).encode("utf-8"))


if __name__ == "__main__":
    gerar(AQUI)
    print(f"fixtures gravadas em {AQUI}")
