# Contrato: manifesto, textos, trechos e índice

Contrato congelado na Phase 1.3 do plano `docs/plans/2026-10-27-inteiro-teor-busca-cloudflare.md`. Vale para
`coletor.textos` (Phase 2.1), `coletor.nuvem` e as migrações do D1 (Phase 2.2), o Worker (Phase 3.2), a busca
(Phase 4.1), o expurgo (T4.2.4) e os temas (Phase 4.3). Mudar um campo, uma chave ou um formato daqui exige
atualizar este documento, as fixtures de `tests/fixtures/contratos/` e `tests/test_contratos.py` no mesmo commit.

As fixtures são geradas por `python tests/fixtures/contratos/gerar_fixtures.py`, com textos sintéticos e o
pipeline real; `tests/test_contratos.py` gera de novo e compara byte a byte.

## 1. Pipeline e versões

Cada arquivo segue, nesta ordem:

1. SHA-256 dos bytes do original (`sha256_original`);
2. `coletor.extratores.extrair(dados, ocr=...)` → `Resultado`; o texto já sai normalizado por
   `coletor.trechos.normalizar` e é o **texto bruto** (`sha256_bruto`), guardado só no cache local;
3. `coletor.limpeza.limpar(texto, cliches, protegidos, ementa, ocr_paginas)` com a lista de clichês congelada
   de `data/textos/cliches.json`; `ocr_paginas` são as páginas que vieram do OCR;
4. `coletor.mascara.mascarar(texto, liberados(RAIZ))`;
5. `coletor.trechos.normalizar` de novo (idempotente) — este é o **texto final**, gravado no `.txt`;
6. `coletor.trechos.dividir(texto_final, documento, arquivo)`;
7. barreira: `coletor.mascara.varrer(texto_final, liberados)` sem nenhuma ocorrência forte, antes de gravar,
   commitar ou carregar.

| Constante | Módulo | Muda quando |
| --- | --- | --- |
| `VERSAO_EXTRATORES` | `coletor/extratores/base.py` | a saída de qualquer extrator em Python puro (docx, doc, rtf, html, zip, texto) muda |
| `VERSAO_LIMPEZA` | `coletor/limpeza.py` | uma regra, a proteção ou a lista de clichês muda |
| `VERSAO_MASCARA` | `coletor/mascara.py` | uma regra de `mascarar` muda |
| `VERSAO_TRECHOS` | `coletor/trechos.py` | a normalização ou a divisão em trechos muda |

A versão das ferramentas externas (pdftotext, tesseract) fica em `versao_extrator` de cada entrada.
`--reprocessar-versao` reprocessa as entradas cujas versões diferem das do código.

## 2. Chaves

### 2.1 Arquivo (chave do manifesto)

`<origem>:<id>`, única em todos os manifestos:

| Origem | Formato | `id` |
| --- | --- | --- |
| SISCAM | `siscam:<IdArquivo>` | inteiro positivo do link `Download.aspx?id=<IdArquivo>` da tabela "[ Arquivos ]" (campo `id` de cada item de `arquivos` nos registros de PLs, substitutivos e documentos) |
| Ata de sessão | `sessao:<guid>` | nome do arquivo, sem extensão e em minúsculas, da URL de `documentos_sessao` com `rotulo` em `ROTULOS_ATA = {"Ata"}` (de `coletor.textos`; `https://consultaniteroi.siscam.com.br/Arquivos/Sessoes/<guid>.docx`) |

Expressão: `^(siscam:[1-9][0-9]*|sessao:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$`.
A mesma chave é usada em `config/remocoes.json`, no D1 (`arquivos.id`) e no campo `arquivo` dos trechos.
Nos nomes de arquivo, o primeiro `:` vira `-` (`siscam-900001`, `sessao-<guid>`).

### 2.2 Documento

| Documento | Formato | Origem do id |
| --- | --- | --- |
| PL, substitutivo, requerimento, indicação, moção, PDL, resolução | `doc:<IdDocumento>` | `id` do registro (o de `DetalhesDocumentos.aspx?IdDocumento=`) |
| Sessão (ata) | `sessao:<IdSessao>` | `id` da sessão em `data/sessoes/<ano>.json` |

Expressão: `^(doc|sessao):[1-9][0-9]*$`. O id de documento e o de sessão são numerações diferentes; o prefixo
evita colisão. `sessao:<IdSessao>` (documento, número) não se confunde com `sessao:<guid>` (arquivo).

### 2.3 Vários documentos por arquivo e documento principal

Um mesmo `IdArquivo` pode aparecer em vários registros (por exemplo, o PL e o seu substitutivo). A entrada do
manifesto é **uma por arquivo**, e:

- `documentos` lista **todos** os documentos que citam o arquivo, sem repetição, em ordem crescente de texto
  (`sorted`);
- `documento` é o **documento principal**, que define `tipo`, o ano do manifesto, o caminho do `.txt` e o campo
  `documento` dos trechos: o PL quando o arquivo é do PL e de seus substitutivos; nos demais casos, o
  documento de menor id numérico entre os de maior prioridade na ordem `pl`, `substitutivo`, `requerimento`,
  `pdl`, `resolucao`, `ata`.

O texto e os trechos são gravados **uma vez**, no principal; a relação com os demais fica em
`arquivo_documento` (D1). Assim um arquivo compartilhado não duplica trechos nem vetores.

## 3. Ano do manifesto

O arquivo é `data/textos/manifesto-<ano>.json`, onde `<ano>` é o campo **`ano` do registro** do documento
principal (o de `data/proposicoes/<ano>.json` ou `data/documentos/<tipo>/<ano>.json`), **não** o ano da `data`.
Nas atas, é o `ano` da sessão. Uma entrada fica num único manifesto; se o principal mudar de ano, a entrada
muda de arquivo na mesma execução.

## 4. Manifesto

`data/textos/manifesto-<ano>.json`, gravado só por `coletor.arquivos.salvar_mapa`: objeto JSON com uma chave por
linha, chaves ordenadas, valores compactos com chaves ordenadas, UTF-8, `ensure_ascii=False`, LF e quebra final.

### 4.1 Campos de cada entrada

Todos os campos estão sempre presentes (sem extras); "nulo" é `null` no JSON.

| Campo | Tipo | Conteúdo |
| --- | --- | --- |
| `documentos` | lista de texto | Documentos que citam o arquivo (seção 2.3), ordenados, não vazia |
| `documento` | texto | Documento principal; está em `documentos` |
| `tipo` | texto | Tipo do principal: `pl`, `substitutivo`, `requerimento`, `pdl`, `resolucao` ou `ata` |
| `url_origem` | texto | URL HTTPS de download: `https://consultaniteroi.siscam.com.br/Download.aspx?id=<IdArquivo>` ou a URL da ata em `documentos_sessao` |
| `sha256_original` | texto ou nulo | SHA-256 (64 hexadecimais minúsculos) dos bytes do original; nulo só em `pendente_download` |
| `bytes` | inteiro ou nulo | Tamanho do original; nulo só em `pendente_download` |
| `formato` | texto ou nulo | `Resultado.formato` (`docx`, `doc`, `rtf`, `html`, `texto`, `pdf`, `jpeg`, `png`, `tiff`, `zip`, `vazio`, `desconhecido`…); nulo sem extração |
| `extrator` | texto ou nulo | `Resultado.extrator` (`docx`, `doc`, `pdftotext`, `pdftotext+tesseract`, `tesseract`, `zip`…); vazio vira nulo |
| `versao_extrator` | texto ou nulo | `Resultado.versao_extrator` (`VERSAO_EXTRATORES` nos extratores em Python, versão das ferramentas nos externos, como `25.07.0+5.5.3`); vazio vira nulo |
| `versao_extratores` | texto ou nulo | `VERSAO_EXTRATORES` na extração |
| `versao_limpeza` | texto ou nulo | `VERSAO_LIMPEZA` na limpeza |
| `versao_mascara` | texto ou nulo | `VERSAO_MASCARA` na máscara |
| `versao_trechos` | texto ou nulo | `VERSAO_TRECHOS` na divisão |
| `paginas` | inteiro | `Resultado.paginas`: páginas do PDF, 1 em imagens, soma dos membros num zip, 0 nos formatos sem páginas |
| `paginas_ocr` | inteiro | `Resultado.paginas_ocr` |
| `confianca` | número ou nulo | `Resultado.confianca` (0–100) arredondada a 1 casa decimal; nulo sem OCR |
| `cabecalhos_omitidos` | inteiro | `Resultado.cabecalhos_omitidos`: partes de cabeçalho/rodapé (docx) ou histórias de cabeçalho (doc) fora do texto salvo |
| `detalhe` | texto | `Resultado.detalhe` passado por `mascarar` e limitado a 300 caracteres; `""` quando não há |
| `status` | texto | Seção 5 |
| `limpeza` | objeto ou nulo | `{linhas_removidas, por_regra}`, das contagens de `limpar`; `por_regra` tem `cabecalho_rodape`, `numeracao`, `ruido_ocr` e `cliche`, e `linhas_removidas` é a soma deles; `VERSAO_LIMPEZA` fica em `versao_limpeza`; nulo sem texto |
| `mascarados` | objeto ou nulo | Contagem de `mascarar` por tipo: `cpf`, `rg`, `telefone`, `email`, `documento` (`mascara.TIPOS`); nulo sem texto |
| `sha256_bruto` | texto ou nulo | SHA-256 do UTF-8 do texto bruto (passo 2, antes da limpeza e da máscara); nulo sem texto |
| `sha256_texto` | texto ou nulo | SHA-256 dos bytes do `.txt` (seção 6.1); nulo sem `.txt` |
| `chars` | inteiro | Pontos de código do texto final, sem a quebra final do `.txt`; 0 sem `.txt` |
| `trechos` | inteiro | Quantidade de trechos do arquivo |
| `trechos_vetorizaveis` | inteiro | Trechos com `vetorizavel: true` |
| `r2_chave` | texto ou nulo | `sha256/<aa>/<bb>/<sha256_original>`, com `<aa>` e `<bb>` os 2 primeiros e os 2 seguintes hexadecimais; nulo em `removido` e `pendente_download` |
| `commit_textos` | texto ou nulo | SHA do commit da branch `dados-textos` que gravou o texto atual (40 hexadecimais); nulo antes do commit e sem `.txt` |
| `processado_em` | texto | Data `AAAA-MM-DD` (Brasília) do último processamento que mudou a entrada; seção 9 |

### 4.2 Campos por situação

| Situação | `.txt` e trechos | Campos de extração (`formato`…`detalhe`) | `limpeza`, `mascarados`, hashes de texto |
| --- | --- | --- | --- |
| `ok`, `ok_ocr`, `ocr_baixa_confianca` | sim | preenchidos | preenchidos |
| `vazio_legitimo`, `escaneado_sem_ocr`, `pendente_ferramenta`, `erro_formato` | não | preenchidos (`versao_limpeza`, `versao_mascara`, `versao_trechos` também) | nulos; `chars`, `trechos`, `trechos_vetorizaveis` = 0 |
| `removido`, `pendente_download` | não | nulos (`paginas`, `paginas_ocr`, `cabecalhos_omitidos` = 0, `detalhe` = `""`) | nulos; contagens 0 |

## 5. Status

| Status | Origem | Significado | Sucesso | Reprocessável |
| --- | --- | --- | --- | --- |
| `ok` | extratores | Texto extraído sem OCR | sim | por versão |
| `ok_ocr` | extratores | Texto com OCR em ao menos uma página e confiança média ≥ `CONFIANCA_MINIMA` (60) | sim | por versão |
| `vazio_legitimo` | extratores | Zero caracteres úteis (arquivo vazio, ou OCR com confiança ≥ 60 sem texto) | sim | por versão |
| `ocr_baixa_confianca` | extratores | OCR com confiança média < 60; o texto é gravado e pesquisável, com aviso | não | por versão |
| `escaneado_sem_ocr` | extratores | Páginas escaneadas e OCR desligado | não | com `--ocr` |
| `pendente_ferramenta` | extratores | pdftotext, pdftoppm, tesseract ou o idioma `por` ausente | não | sempre |
| `erro_formato` | extratores | Arquivo malformado, truncado, criptografado ou acima dos limites (`detalhe` diz o motivo) | não | por versão |
| `removido` | remoções | Coincide com `config/remocoes.json` (seção 8) | — | nunca, enquanto a remoção existir |
| `pendente_download` | `coletor.textos` | Ainda sem os bytes (`--sem-rede` sem cache ou falha de download) | não | sempre |

**Sucesso** = `ok`, `ok_ocr` ou `vazio_legitimo`. A base das metas é o conjunto de arquivos do escopo, exceto
`removido`.

## 6. Branch `dados-textos`

### 6.1 Textos

`textos/<tipo>/<ano>/<documento-sem-prefixo>/<origem>-<id>.txt`, com `tipo`, `ano` e documento do principal.
Exemplos: `textos/pl/2024/127858/siscam-900001.txt`, `textos/ata/2024/5001/sessao-<guid>.txt`.

- Conteúdo: o texto final (passo 5) seguido de uma única quebra `\n`; UTF-8 sem BOM, LF, NFC,
  `trechos.normalizar(texto) == texto`; já limpo e mascarado.
- Páginas separadas por uma linha só com `\f` (`trechos.SEPARADOR_PAGINA = "\n\f\n"`); `\f` não aparece em
  outro lugar.
- Os offsets dos trechos indexam o texto sem a quebra final; `sha256_texto` cobre os bytes do arquivo inteiro.

### 6.2 Trechos

`trechos/<tipo>/<ano>.jsonl`: um objeto JSON por linha, com `json.dumps(..., ensure_ascii=False,
sort_keys=True, separators=(",", ":"))`, ordenado por (`documento`, `arquivo`, `posicao`) e quebra final.
O arquivo reúne todos os trechos dos `.txt` de `textos/<tipo>/<ano>/`. Campos, exatamente os de
`trechos.dividir`, **sem o texto**:

| Campo | Tipo | Conteúdo |
| --- | --- | --- |
| `id` | texto | `sha1(f"{documento}\|{arquivo}\|{posicao}\|{sha256}")[:16]`, 16 hexadecimais |
| `documento` | texto | Documento principal do arquivo |
| `arquivo` | texto | Chave do manifesto |
| `posicao` | inteiro | 0, 1, 2… dentro do arquivo |
| `inicio`, `fim` | inteiro | Offsets em pontos de código (`texto[inicio:fim]`) |
| `inicio_utf16`, `fim_utf16` | inteiro | Offsets em unidades UTF-16 (`texto.slice(inicio_utf16, fim_utf16)` em JavaScript) |
| `sha256` | texto | SHA-256 do UTF-8 de `texto[inicio:fim]` |
| `vetorizavel` | booleano | Ao menos `MIN_CARACTERES_VETOR` (80) letras e dígitos; os demais ficam só na busca por palavras |

## 7. Projeções no Cloudflare

D1, Vectorize e R2 são reconstruíveis a partir do Git (`python -m coletor.nuvem --reconstruir`).

### 7.1 Tabelas D1 (`worker/migrations/0001_inicial.sql`)

| Tabela | Colunas | Chave e índices | Conteúdo |
| --- | --- | --- | --- |
| `documentos` | `id` TEXT, `tipo` TEXT, `numero` INTEGER, `ano` INTEGER, `data` TEXT, `ementa` TEXT, `url` TEXT, `legislatura` TEXT | PK `id`; índice (`tipo`, `ano`) | Todos os documentos (inclusive indicações e moções, só com a ementa). `id` como na seção 2.2; `tipo` inclui `indicacao` e `mocao`; `ementa` mascarada; `url` pública do detalhe no SISCAM; `legislatura` como em `config/vereadores.json` (`2021-2024`) |
| `autoria` | `documento` TEXT, `slug` TEXT, `papel` TEXT | PK (`documento`, `slug`, `papel`); índice (`slug`) | Autores; `papel` `autor` ou `coautor` |
| `pessoas` | `slug` TEXT, `nome` TEXT, `partido_atual` TEXT | PK `slug` | Slug e nome do modelo do site; `partido_atual` pode ser nulo |
| `arquivos` | `id` TEXT, `sha256` TEXT, `formato` TEXT, `status` TEXT, `ocr` INTEGER, `confianca` REAL, `r2_chave` TEXT | PK `id` | Uma linha por entrada do manifesto que não é `removido`; `id` = chave do manifesto; `ocr` = 1 se `paginas_ocr` > 0 |
| `arquivo_documento` | `arquivo` TEXT, `documento` TEXT | PK (`arquivo`, `documento`) | Relação N:N de `documentos` do manifesto |
| `trechos` | `id` TEXT, `documento` TEXT, `arquivo` TEXT, `posicao` INTEGER, `texto` TEXT, `sha256` TEXT | PK `id`; índice (`documento`) | Texto lido do `.txt` pelos offsets e conferido pelo `sha256` |
| `trechos_fts` | `texto` | FTS5 de conteúdo externo (`content='trechos'`), `tokenize='unicode61 remove_diacritics 2'` | Busca por palavras; reconstruível, fora das exportações |
| `trechos_indexados` | `id` TEXT, `sha256` TEXT | PK `id` | Vetores já enviados ao Vectorize (trechos e `ementa:doc:<id>`), para a diferença incremental |
| `remocoes` | `chave` TEXT, `sha256` TEXT, `motivo` TEXT, `data` TEXT | PK (`chave`, `sha256`) | Cópia de `config/remocoes.json` sem `fonte`; consultada pelo Worker antes da Cache API |
| `estado_indice` | `id` INTEGER (= 1), `versao` TEXT, `commit` TEXT, `commit_textos` TEXT, `total` INTEGER, `sha256_conjunto` TEXT, `modelo` TEXT, `versao_trechos` TEXT, `data` TEXT | PK `id` | Uma linha, gravada só no fim de uma sincronização completa; `sha256_conjunto` = SHA-256 das linhas `"<id> <sha256>\n"` de todos os trechos, ordenadas por `id` |
| `verificacoes` | `data` TEXT, `amostra` INTEGER, `ok` INTEGER, `falhas_json` TEXT | PK `data` (carimbo ISO UTC) | Única escrita do Worker (cron): conferência dos hashes por amostragem |

### 7.2 Vectorize

- Índice `radar-niteroi-trechos` (staging: `-staging`), `@cf/baai/bge-m3`, 1.024 dimensões, cosseno.
- Id do vetor: o `id` do trecho (16 hexadecimais) ou `ementa:doc:<IdDocumento>` para as ementas mascaradas de
  indicações e moções.
- Metadados: `{tipo, ano, legislatura, documento}`, com `ano` numérico, `tipo` e `legislatura` texto e
  `documento` como na seção 2.2. Índices de metadados: `tipo` (string), `ano` (number) e `legislatura`
  (string). O filtro por autor é feito no D1.
- Só trechos com `vetorizavel: true` viram vetor.

### 7.3 R2

- Originais no bucket privado `radar-niteroi-arquivos`, na chave `r2_chave`; servidos pelo Worker em
  `GET /api/original/:sha256` com `Content-Disposition: attachment`, `X-Robots-Tag: noindex`,
  `X-Content-Type-Options: nosniff` e `Content-Security-Policy: sandbox`, depois de consultar `remocoes`.
- Exportações em `radar-niteroi-exportacoes/<versao>/`: dump das tabelas-base, `vetores-<versao>.jsonl.gz` e
  `SHA256SUMS`.

## 8. Remoções

`config/remocoes.json` (validado por `coletor.validar.validar_remocoes`):

```json
{
 "remocoes": [
  {
   "chave": "siscam:900004",
   "sha256": "<64 hexadecimais minúsculos do original>",
   "motivo": "Texto público, sem dados pessoais.",
   "fonte": "https://…",
   "data": "2026-01-15"
  }
 ]
}
```

- Campos exatamente `chave` (seção 2.1), `sha256`, `motivo`, `fonte` (HTTPS) e `data` (`AAAA-MM-DD`, não
  futura); ordem por (`data`, `chave`, `sha256`), sem pares repetidos; JSON com `indent=1`, ordem das chaves
  preservada, UTF-8, LF, NFC.
- Leitura: `coletor.remocoes.carregar(raiz)`, `chaves_removidas(raiz)` e `esta_removido(raiz_ou_cache, chave,
  sha256)`. Um arquivo está removido quando **a chave ou o SHA-256 do original** coincide com algum item: uma
  nova versão do mesmo id e o mesmo original publicado sob outro id também saem.
- Efeitos: a entrada do manifesto vira `removido` (seção 4.2), mantendo `documentos`, `documento`, `tipo`,
  `url_origem`, `sha256_original` e `bytes`; `coletor.textos` não baixa nem processa o arquivo; o `.txt` e os
  trechos saem de `dados-textos` (com reescrita do histórico no expurgo da T4.2.4); no D1 saem `arquivos`,
  `arquivo_documento`, `trechos` e `trechos_fts`, e o item entra em `remocoes`; os vetores saem do Vectorize e de
  `trechos_indexados`; o original sai do R2; as exportações, inclusive as antigas, são regravadas sem o item.

## 9. Determinismo

- Mesma entrada (originais, código, `config/` e `data/textos/cliches.json`), mesmos bytes no manifesto, nos
  `.txt` e nos `.jsonl`.
- `processado_em` muda **somente** quando muda `sha256_original` ou qualquer `versao_*`
  (`versao_extrator`, `versao_extratores`, `versao_limpeza`, `versao_mascara`, `versao_trechos`).
  Reprocessar sem essas mudanças preserva o valor anterior, mesmo que outro campo seja atualizado.
  `commit_textos` só muda quando o `.txt` muda.
- Ordem estável: chaves do manifesto ordenadas; `documentos` ordenada; trechos por (`documento`, `arquivo`,
  `posicao`); JSON com chaves ordenadas.
- Gzip das exportações com `mtime=0` e sem nome de arquivo no cabeçalho; tarefas em ordem de chave; nenhum
  carimbo de relógio no conteúdo, exceto `processado_em`, `estado_indice.data` e `verificacoes.data`.
- Nenhum `.txt` ou trecho é gravado, commitado ou carregado com ocorrência forte de `mascara.varrer`.
