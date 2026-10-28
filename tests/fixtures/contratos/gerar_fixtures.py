"""Gera as fixtures do contrato de textos (`docs/contratos/textos.md`).

A pasta `tests/fixtures/contratos/` funciona como uma raiz de repositório em
miniatura: registros sintéticos no formato real de `data/proposicoes/`,
`data/documentos/` e `data/sessoes/` (substitutivos aninhados no PL), o manifesto
`data/textos/manifesto-2024.json`, a lista de clichês `data/textos/cliches.json`,
`config/remocoes.json`, a árvore `dados-textos/` (textos e trechos) e
`normalizacao.json` (pares da normalização da busca, para Python e JavaScript).

Este gerador é uma implementação de referência das regras do contrato: fila (sem
indicações e moções), documentos que citam cada arquivo, documento principal (o PL
para arquivos do PL ou de seus substitutivos), ano pelo `ano` do registro, remoção
por chave (sem download) ou por SHA-256 (baixado e descartado), duplicatas pelo
SHA-256 do original e o pipeline real: `trechos.normalizar` → `limpeza.limpar` →
`mascara.mascarar` → `trechos.normalizar` → `trechos.dividir`, com a barreira
`mascara.varrer`. As regras puras (chaves, caminhos, fila, principal, entrada e
pipeline de cada arquivo) são as de `coletor.textos`; `tests/test_textos.py` roda o
`coletor.textos` completo sobre estes registros e confere os mesmos bytes.

Os textos são sintéticos: nomes, números e endereços não correspondem a pessoas
reais; `LIBERADOS` e `PESSOAS` substituem a configuração do repositório. Mesma
entrada, mesmos bytes. `tests/test_contratos.py` gera de novo numa pasta temporária
e compara com os arquivos versionados. A pasta de destino é esvaziada antes (exceto
os `.py`), para não deixar arquivos de versões anteriores.

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

from coletor import arquivos, limpeza  # noqa: E402
from coletor import textos as pipeline  # noqa: E402
from coletor.extratores import VERSAO_EXTRATORES, Resultado  # noqa: E402
# Regras puras compartilhadas com coletor.textos (mesmo código, mesmos bytes).
from coletor.textos import (  # noqa: E402,F401
    PRIORIDADE_TIPO,
    ROTULOS_ATA,
    STATUS_COM_TEXTO,
    TIPOS_COM_TEXTO,
    URL_DOWNLOAD,
    blob_git,
    caminho_texto,
    caminho_trechos,
    citacoes,
    linha_trecho,
    ordem_chave,
    principal,
    r2_chave,
    sha256,
)

ANO = 2024
PROCESSADO_EM = "2026-10-27"
URL_SESSOES = "https://consultaniteroi.siscam.com.br/Arquivos/Sessoes/{nome}"
URL_DETALHE = "https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento={id}"
GUID_ATA = "00000000-0000-4000-8000-0000000000a1"
GUID_ATA_PENDENTE = "0000000A-0000-4000-8000-0000000000B2"  # maiúsculas na URL; a chave usa minúsculas
GUID_EXPEDIENTE = "00000000-0000-4000-8000-0000000000c3"

# Configuração sintética (no lugar de config/perfis.json, config/backend.json e config/vereadores.json)
LIBERADOS = frozenset({"@camaraniteroi.rj.gov.br", "@niteroi.rj.gov.br", "2126201234"})
PESSOAS = [("FULANO SINTETICO DE TAL", "Fulano Sintético")]
CLICHES = {limpeza.normalizar_linha("CÂMARA MUNICIPAL DE NITERÓI"): 40}

# Pares da normalização da busca por palavras (contrato, seção 8.1), compartilhados pelos testes
# Python (coletor.nuvem.fonte.normalizar_busca) e JavaScript (Worker). JSON só com ASCII (\uXXXX).
FUNCAO_JS_NORMALIZACAO = 's.normalize("NFD").replace(/\\p{Mn}/gu, "").normalize("NFC").toLowerCase()'
PARES_NORMALIZACAO = [
    ("Licen\u00e7a", "licenca"),
    ("LICEN\u00c7A Ambiental", "licenca ambiental"),
    ("Niter\u00f3i", "niteroi"),
    ("S\u00e3o Gon\u00e7alo", "sao goncalo"),
    ("A\u00c7\u00c3O", "acao"),
    ("Prac\u0327a", "praca"),  # c + cedilha combinante
    ("\u00d1and\u00fa", "nandu"),
    ("Vi\u1ec7t", "viet"),  # duas marcas sobre o e
    ("\u0130stanbul", "istanbul"),  # I com ponto: NFD separa o ponto (Mn) antes das minúsculas
    ("\u212b", "a"),  # sinal de angstrom: decomposição canônica
    ("\u1f08\u03b8\u1fc6\u03bd\u03b1\u03b9", "\u03b1\u03b8\u03b7\u03bd\u03b1\u03b9"),
    ("Stra\u00dfe", "stra\u00dfe"),  # minúsculas simples, sem expandir o ß
    ("\ufb01m", "\ufb01m"),  # ligadura: só compatibilidade, NFD não muda
    ("N\u00ba 29/2024", "n\u00ba 29/2024"),
    ("a\u20dd", "a\u20dd"),  # marca envolvente (Me) fica
    ("\u0915\u093f", "\u0915\u093f"),  # marca com espaçamento (Mc) fica
    ("\ud55c\uae00", "\ud55c\uae00"),  # hangul: NFD e NFC se desfazem
    ("a\U0001f600", "a\U0001f600"),
    ("  Espa\u00e7os  ", "  espacos  "),  # espaços preservados
    ("", ""),
]
NORMALIZACAO = {
    "descricao": "Pares entrada -> sa\u00edda da normaliza\u00e7\u00e3o da busca por palavras (contrato, "
                 "se\u00e7\u00e3o 8.1): coletor.nuvem.fonte.normalizar_busca e o Worker devem produzir a mesma "
                 "sa\u00edda.",
    "funcao_js": FUNCAO_JS_NORMALIZACAO,
    "pares": [{"entrada": e, "saida": s} for e, s in PARES_NORMALIZACAO],
}

EMENTA_PL = "Institui o Programa Municipal Sintético de Leitura nas Praças de Niterói."
EMENTA_REQ = "Requer informações sintéticas sobre a manutenção das praças do município."
EMENTA_REQ_2 = "Requer cópia sintética do mesmo levantamento sobre as praças do município."
EMENTA_PDL = "Concede título sintético de cidadania a pessoa fictícia."
EMENTA_RES = "Altera o regimento sintético da Casa."
EMENTA_PDL_2 = "Aprova as contas sintéticas do exercício."
EMENTA_IND = "Indica a poda sintética de árvores na praça do bairro."


def _arquivo(ident: int, data: str, icone: str = "doc") -> dict:
    return {"data": data, "descricao": "", "icone": icone, "id": ident, "versao": "Anexos"}


# ---- registros sintéticos no formato real de data/
PROPOSICOES = [{
    "ano": 2024, "arquivos": [_arquivo(900001, "2024-03-10"), _arquivo(900002, "2024-03-10", "pdf")],
    "data": "2024-03-10", "ementa": EMENTA_PL, "id": 127858, "lei": None, "numero": "900/2024",
    "situacao": "Em tramitação",
    "substitutivos": [{
        # substitutivo real: só estes campos, sem ano nem ementa; cita um arquivo do PL e um próprio
        "arquivos": [_arquivo(900001, "2024-06-20"), _arquivo(900005, "2024-06-20", "pdf")],
        "autoria": [{"id": 1, "nome": "FULANO SINTETICO DE TAL", "origem": "Vereador", "papel": "Autor"}],
        "data": "2024-06-20", "id": 266596, "lei": None, "numero": "1", "situacao": "RECEBIDO PELA SMD",
        "tramitacoes": [],
    }],
}]

DOCUMENTOS = {
    "requerimento": [
        # protocolado em 2024, com data do documento em 2025: o manifesto é o de 2024
        {"ano": 2024, "arquivos": [_arquivo(900003, "2025-01-03")], "data": "2025-01-03", "ementa": EMENTA_REQ,
         "id": 290001, "numero": "901/2024", "tipo": "requerimento"},
        # mesmo arquivo publicado de novo sob outro id: duplicata
        {"ano": 2024, "arquivos": [_arquivo(900008, "2024-11-02")], "data": "2024-11-02", "ementa": EMENTA_REQ_2,
         "id": 290004, "numero": "950/2024", "tipo": "requerimento"},
    ],
    "pdl": [
        # removido pela chave: nunca baixado
        {"ano": 2024, "arquivos": [_arquivo(900004, "2024-08-01", "pdf")], "data": "2024-08-01",
         "ementa": EMENTA_PDL, "id": 290002, "numero": "12/2024", "tipo": "pdl"},
        # texto que a limpeza esvazia
        {"ano": 2024, "arquivos": [_arquivo(900006, "2024-09-01")], "data": "2024-09-01",
         "ementa": EMENTA_PDL_2, "id": 290005, "numero": "13/2024", "tipo": "pdl"},
    ],
    "resolucao": [
        # o original removido, publicado de novo sob outra chave: removido pelo SHA-256
        {"ano": 2024, "arquivos": [_arquivo(900007, "2024-10-01", "pdf")], "data": "2024-10-01",
         "ementa": EMENTA_RES, "id": 290003, "numero": "3/2024", "tipo": "resolucao"},
    ],
    "indicacao": [
        # indicações e moções ficam fora do manifesto mesmo com `arquivos`
        {"ano": 2024, "arquivos": [_arquivo(900009, "2024-05-05")], "data": "2024-05-05", "ementa": EMENTA_IND,
         "id": 290006, "numero": "77/2024", "tipo": "indicacao"},
    ],
}

SESSOES = [{
    "ano": 2024, "data": "2024-02-15", "id": 5001,
    "documentos_sessao": [
        {"rotulo": "Expediente em pdf", "url": URL_SESSOES.format(nome=f"{GUID_EXPEDIENTE}.pdf")},
        {"rotulo": "Ata", "url": URL_SESSOES.format(nome=f"{GUID_ATA}.docx")},
        {"rotulo": "Ata", "url": URL_SESSOES.format(nome=f"{GUID_ATA_PENDENTE}.pdf")},
        {"rotulo": "Ata", "url": None},
    ],
}]

# ---- textos brutos (como sairiam de coletor.extratores) e originais
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
    "Telefone do gabinete: (21) 2620-1234. Contato pessoal do assessor: (21) 98888-7777.",
    "Sala das Sessões, 10 de março de 2024.",
    "Vereador Fulano Sintético",
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
    # Parágrafo abaixo do limite de unidade e grande demais para agrupar com as
    # páginas anteriores: um trecho baixo, sem retirar os seis trechos já indexáveis.
    "Art. 9º " + ("A conservação das estantes comunitárias será registrada em relatório público, "
                   "com a descrição dos materiais e das intervenções previstas. " * 30)[:1760] + ".",
])

TEXTO_SUBSTITUTIVO = "\f".join([
    "\n".join([
        "SUBSTITUTIVO Nº 1 AO PROJETO DE LEI Nº 900/2024",
        "",
        "Art. 1º Fica instituído o Programa Municipal Sintético de Leitura nas Praças e nas bibliotecas "
        "escolares, com estantes comunitárias e rodas de leitura abertas ao público em geral.",
    ]),
    "",  # página escaneada que ficou sem OCR
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

TEXTO_SO_RUIDO = "-----\n=====\n* * * *"

ORIGINAL_REMOVIDO = b"%PDF-1.7 pdl sintetico removido a pedido"
ORIGINAL_REQ = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1 doc sintetico do requerimento"

# O que o servidor devolveria em cada chave (None: download ainda não feito).
ORIGINAIS: dict[str, bytes | None] = {
    "siscam:900001": b"PK\x03\x04 docx sintetico do PL 900/2024 e do substitutivo",
    "siscam:900002": b"%PDF-1.7 anexo sintetico com pagina escaneada",
    "siscam:900003": ORIGINAL_REQ,
    "siscam:900004": ORIGINAL_REMOVIDO,
    "siscam:900005": b"%PDF-1.7 substitutivo sintetico com pagina sem OCR",
    "siscam:900006": b"PK\x03\x04 docx sintetico so com separadores",
    "siscam:900007": ORIGINAL_REMOVIDO,
    "siscam:900008": ORIGINAL_REQ,
    f"sessao:{GUID_ATA}": b"PK\x03\x04 docx sintetico da ata da sessao 5001",
    f"sessao:{GUID_ATA_PENDENTE.lower()}": None,
}

# Resultado de coletor.extratores.extrair para cada original processado.
EXTRACOES = {
    "siscam:900001": {"formato": "docx", "extrator": "docx", "versao_extrator": VERSAO_EXTRATORES,
                      "paginas": 0, "paginas_ocr": 0, "confianca": None, "confianca_paginas": {},
                      "status": "ok", "detalhe": "", "cabecalhos_omitidos": 2, "texto": TEXTO_PL},
    "siscam:900002": {"formato": "pdf", "extrator": "pdftotext+tesseract", "versao_extrator": "25.07.0+5.5.3",
                      "paginas": 3, "paginas_ocr": 2, "confianca": 70.0, "confianca_paginas": {2: 87.43, 3: 45.0},
                      "status": "ok_ocr", "detalhe": "", "cabecalhos_omitidos": 0, "texto": TEXTO_ANEXO},
    "siscam:900003": {"formato": "doc", "extrator": "doc", "versao_extrator": VERSAO_EXTRATORES,
                      "paginas": 0, "paginas_ocr": 0, "confianca": None, "confianca_paginas": {},
                      "status": "ok", "detalhe": "", "cabecalhos_omitidos": 0, "texto": TEXTO_REQ},
    "siscam:900005": {"formato": "pdf", "extrator": "pdftotext", "versao_extrator": "25.07.0",
                      "paginas": 2, "paginas_ocr": 0, "confianca": None, "confianca_paginas": {},
                      "status": "ok_parcial", "detalhe": "páginas escaneadas sem OCR: 2",
                      "cabecalhos_omitidos": 0, "texto": TEXTO_SUBSTITUTIVO},
    "siscam:900006": {"formato": "docx", "extrator": "docx", "versao_extrator": VERSAO_EXTRATORES,
                      "paginas": 0, "paginas_ocr": 0, "confianca": None, "confianca_paginas": {},
                      "status": "ok", "detalhe": "", "cabecalhos_omitidos": 0, "texto": TEXTO_SO_RUIDO},
    f"sessao:{GUID_ATA}": {"formato": "docx", "extrator": "docx", "versao_extrator": VERSAO_EXTRATORES,
                           "paginas": 0, "paginas_ocr": 0, "confianca": None, "confianca_paginas": {},
                           "status": "ok", "detalhe": "", "cabecalhos_omitidos": 0, "texto": TEXTO_ATA},
}

REMOCOES = {"remocoes": [{
    "chave": "siscam:900004",
    "sha256": hashlib.sha256(ORIGINAL_REMOVIDO).hexdigest(),
    "motivo": "Exemplo sintético de pedido de titular (art. 18 da LGPD).",
    "fonte": "https://github.com/marco-jardim/radar-vereadores-niteroi/issues",
    "data": "2026-01-15",
}]}


# ---- regras do contrato
# sha256, blob_git, r2_chave, ordem_chave, caminhos, citacoes e principal vêm de
# coletor.textos; entrada_vazia e processar usam a mesma implementação com a
# configuração sintética desta fixture (PROCESSADO_EM e LIBERADOS).
def entrada_vazia(documentos: list[str], documento: str, tipo: str, url: str, status: str) -> dict:
    return pipeline.entrada_vazia(documentos, documento, tipo, url, status, PROCESSADO_EM)


def processar(entrada: dict, chave: str, extracao: dict, ementa: str, cliches: dict, protecao,
              versao_limpeza: str, sha_config: str) -> tuple[str | None, list[dict]]:
    """Preenche a entrada com o pipeline (`coletor.textos.processar`); devolve o conteúdo
    do .txt (ou None) e os trechos. A barreira de PII levanta `pipeline.BarreiraPII`."""
    conteudo, lista, _ = pipeline.processar(entrada, chave, Resultado(**extracao), ementa, cliches, protecao,
                                          LIBERADOS, versao_limpeza, sha_config)
    return conteudo, lista


def montar(cliches: dict, versao_limpeza: str) -> tuple[dict[int, dict], dict[str, str], dict[str, list]]:
    """Manifestos por ano, textos (caminho → conteúdo) e trechos (caminho → lista)."""
    protecao = limpeza.ProtecaoLimpeza(PESSOAS)
    sha_config = limpeza.hash_config_de(LIBERADOS, PESSOAS)
    removidas = {(r["chave"], r["sha256"]) for r in REMOCOES["remocoes"]}
    chaves_removidas = {c for c, _ in removidas}
    shas_removidos = {s for _, s in removidas}
    fila = citacoes(PROPOSICOES, DOCUMENTOS, SESSOES)

    entradas: dict[str, dict] = {}
    anos: dict[str, int] = {}
    ementas: dict[str, str] = {}
    for chave in sorted(fila, key=ordem_chave):
        item = fila[chave]
        documento, tipo, ano, ementa = principal(item["citacoes"])
        docs = [c[0] for c in item["citacoes"]]
        anos[chave], ementas[chave] = ano, ementa
        if chave in chaves_removidas:  # removido pela chave: não baixa
            entradas[chave] = entrada_vazia(docs, documento, tipo, item["url"], "removido")
            continue
        original = ORIGINAIS[chave]
        if original is None:
            entradas[chave] = entrada_vazia(docs, documento, tipo, item["url"], "pendente_download")
            continue
        entrada = entrada_vazia(docs, documento, tipo, item["url"], "ok")
        entrada["sha256_original"], entrada["bytes"] = sha256(original), len(original)
        if entrada["sha256_original"] in shas_removidos:  # removido pelo SHA-256: baixado e descartado
            entrada["status"] = "removido"
        entradas[chave] = entrada

    # duplicatas: o mesmo original sob várias chaves; a menor chave é a canônica
    grupos: dict[str, list[str]] = {}
    for chave in sorted(entradas, key=ordem_chave):
        e = entradas[chave]
        if e["status"] != "removido" and e["sha256_original"]:
            grupos.setdefault(e["sha256_original"], []).append(chave)
    for chaves in grupos.values():
        canonica, outras = chaves[0], chaves[1:]
        if not outras:
            continue
        todas = [c for k in chaves for c in fila[k]["citacoes"]]
        documento, tipo, ano, ementa = principal(todas)
        e = entradas[canonica]
        e.update({"documentos": sorted({c[0] for c in todas}), "documento": documento, "tipo": tipo})
        anos[canonica], ementas[canonica] = ano, ementa
        for outra in outras:
            entradas[outra]["status"] = "duplicata"
            entradas[outra]["duplicata_de"] = canonica

    manifestos: dict[int, dict] = {}
    textos: dict[str, str] = {}
    lista_trechos: dict[str, list] = {}
    for chave in sorted(entradas, key=ordem_chave):
        e = entradas[chave]
        if e["status"] == "ok":
            conteudo, lista = processar(e, chave, EXTRACOES[chave], ementas[chave], cliches, protecao,
                                        versao_limpeza, sha_config)
            if conteudo is not None:
                textos[caminho_texto(e["tipo"], anos[chave], e["documento"], chave)] = conteudo
            if lista:
                lista_trechos.setdefault(caminho_trechos(e["tipo"], anos[chave]), []).extend(lista)
        manifestos.setdefault(anos[chave], {})[chave] = e
    for lista in lista_trechos.values():
        lista.sort(key=lambda t: (t["documento"], t["arquivo"], t["posicao"]))
    return manifestos, textos, lista_trechos


def _json_config(obj: dict) -> str:
    """Formato dos configs editoriais: indent=1, ordem das chaves preservada."""
    return json.dumps(obj, ensure_ascii=False, indent=1) + "\n"


def _esvaziar(destino: Path) -> None:
    """Apaga tudo em `destino`, exceto os .py e __pycache__."""
    if (destino / ".git").exists() or destino.resolve() == RAIZ:
        raise RuntimeError(f"destino suspeito: {destino}")
    for item in destino.iterdir():
        if item.name == "__pycache__" or item.suffix == ".py":
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()


def gravar_bytes(caminho: Path, conteudo: str) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(conteudo.encode("utf-8"))


def gerar(destino: Path) -> None:
    """Grava a raiz em miniatura (data/, config/ e dados-textos/) em `destino`."""
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    _esvaziar(destino)
    arquivos.salvar_lista(destino / "data" / "proposicoes" / f"{ANO}.json", PROPOSICOES)
    for tipo, registros in sorted(DOCUMENTOS.items()):
        arquivos.salvar_lista(destino / "data" / "documentos" / tipo / f"{ANO}.json", registros)
    arquivos.salvar_lista(destino / "data" / "sessoes" / f"{ANO}.json", SESSOES)
    caminho_cliches = destino / "data" / "textos" / "cliches.json"
    arquivos.salvar_mapa(caminho_cliches, CLICHES)
    cliches = limpeza.carregar_cliches(caminho_cliches)
    versao_limpeza = limpeza.versao_efetiva(destino)
    gravar_bytes(destino / "config" / "remocoes.json", _json_config(REMOCOES))
    gravar_bytes(destino / "normalizacao.json", json.dumps(NORMALIZACAO, ensure_ascii=True, indent=1) + "\n")

    manifestos, textos, lista_trechos = montar(cliches, versao_limpeza)
    for ano, manifesto in sorted(manifestos.items()):
        arquivos.salvar_mapa(destino / "data" / "textos" / f"manifesto-{ano}.json", manifesto)
    dados_textos = destino / "dados-textos"
    for caminho, conteudo in sorted(textos.items()):
        gravar_bytes(dados_textos / caminho, conteudo)
    for caminho, lista in sorted(lista_trechos.items()):
        gravar_bytes(dados_textos / caminho, "".join(linha_trecho(t) + "\n" for t in lista))


if __name__ == "__main__":
    gerar(AQUI)
    print(f"fixtures gravadas em {AQUI}")
