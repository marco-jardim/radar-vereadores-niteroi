# Contrato: manifesto, textos, trechos e índice

Contrato congelado na Phase 1.3 do plano `docs/plans/2026-10-27-inteiro-teor-busca-cloudflare.md`, revisto com as
decisões da QA da Wave 1. Vale para `coletor.textos` (Phase 2.1), `coletor.nuvem` e as migrações do D1
(Phase 2.2), o Worker (Phase 3.2), a busca (Phase 4.1), o expurgo (T4.2.4) e os temas (Phase 4.3). Mudar um campo,
uma chave ou um formato daqui exige atualizar este documento, as fixtures de `tests/fixtures/contratos/` e
`tests/test_contratos.py` no mesmo commit.

`tests/fixtures/contratos/` é uma raiz em miniatura (registros em `data/`, manifesto, clichês, `config/remocoes.json`
e `dados-textos/`), gerada por `python tests/fixtures/contratos/gerar_fixtures.py` — uma implementação de
referência destas regras, com textos sintéticos e o pipeline real. `tests/test_contratos.py` gera de novo, compara
byte a byte e recalcula as regras a partir dos registros.

## 1. Pipeline e versões

Cada arquivo segue, nesta ordem:

1. SHA-256 dos bytes do original (`sha256_original`);
2. `coletor.extratores.extrair(dados, ocr=...)` → `Resultado`; o texto já sai normalizado por
   `coletor.trechos.normalizar` e é o **texto bruto** (`sha256_bruto`), guardado só no cache local;
3. `coletor.limpeza.limpar(texto, cliches, protegidos, ementa, ocr_paginas)`:
   - `cliches`: a lista congelada de `data/textos/cliches.json` (`limpeza.carregar_cliches`);
   - `protegidos`: `limpeza.ProtecaoLimpeza.de_config(RAIZ)` (pessoas de `limpeza.pessoas_de_config`);
   - `ementa`: a do documento principal (seção 2.3); para arquivos de PL ou de substitutivo, **a do PL**; atas, `""`;
   - `ocr_paginas`: `set(Resultado.confianca_paginas)` (as páginas, base 1, cujo texto veio do OCR); em zip,
     `None` (só as regras de borda);
4. `coletor.mascara.mascarar(texto, mascara.liberados(RAIZ))`;
5. `coletor.trechos.normalizar` de novo (idempotente) — este é o **texto final**, gravado no `.txt`;
6. `coletor.trechos.dividir(texto_final, documento_principal, chave_do_arquivo)`;
7. barreira: `coletor.mascara.varrer(texto_final, liberados)` sem nenhuma ocorrência forte, antes de gravar,
   commitar ou carregar.

Se a limpeza esvaziar um texto que o extrator devolveu com texto, o status vira `vazio_legitimo`, com `detalhe`
`"esvaziado pela limpeza"`, o `.txt` contém só `"\n"` e não há trechos.

| Constante ou função | Módulo | Gravada em | Muda quando |
| --- | --- | --- | --- |
| `VERSAO_EXTRATORES` | `coletor/extratores/base.py` | `versao_extratores` | a saída de qualquer extrator em Python puro (docx, doc, rtf, html, zip, texto) muda |
| `VERSAO_LIMPEZA` | `coletor/limpeza.py` | parte de `versao_limpeza` | uma regra ou a proteção da limpeza muda |
| `versao_efetiva` | `coletor/limpeza.py` | `versao_limpeza` | `f"{VERSAO_LIMPEZA}+{sha256(bytes de data/textos/cliches.json)[:8]}"`: muda também com a lista de clichês (sem o arquivo, hash de zero bytes) |
| `VERSAO_MASCARA` | `coletor/mascara.py` | `versao_mascara` | uma regra de `mascarar` muda |
| `VERSAO_TRECHOS` | `coletor/trechos.py` | `versao_trechos` | a normalização ou a divisão em trechos muda |
| `hash_config` | `coletor/limpeza.py` | `sha256_config` | muda `config/perfis.json` (`contatos`), `config/backend.json` (`contatos_institucionais`), `config/vereadores.json` ou `PREFEITOS` |

`limpeza.hash_config(raiz)` = `hash_config_de(mascara.liberados(raiz), pessoas_de_config(raiz))`: SHA-256 do JSON
canônico (chaves ordenadas, sem espaços, UTF-8) de `{"liberados": [...ordenados], "pessoas": [[variantes
ordenadas], ...ordenadas], "prefeitos": PREFEITOS}`. Fica em `limpeza` porque reúne as entradas da limpeza e da
máscara (`limpeza` já importa `mascara`).

A versão das ferramentas externas (pdftotext, tesseract) fica em `versao_extrator`. `--reprocessar-versao`
reprocessa as entradas cujas versões diferem das do código. **Quando `sha256_config` muda, todas as entradas com
texto são reprocessadas e `mascara.varrer` roda sobre todos os textos**, não só os alterados.

## 2. Chaves, fila e documento principal

### 2.1 Arquivo (chave do manifesto)

`<origem>:<id>`, única em todos os manifestos:

| Origem | Formato | `id` |
| --- | --- | --- |
| SISCAM | `siscam:<IdArquivo>` | inteiro positivo, sem zeros à esquerda, do link `Download.aspx?id=<IdArquivo>` (campo `id` de cada item de `arquivos` nos registros de PLs, substitutivos e documentos) |
| Ata de sessão | `sessao:<guid>` | nome do arquivo da URL de `documentos_sessao`, sem extensão e **em minúsculas** (`https://consultaniteroi.siscam.com.br/Arquivos/Sessoes/<GUID>.<doc\|docx\|pdf>`) |

Expressão: `^(siscam:[1-9][0-9]*|sessao:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$`, a mesma
de `coletor.validar.validar_remocoes`. A chave é usada em `config/remocoes.json`, no D1 (`arquivos.id`) e no campo
`arquivo` dos trechos. Nos nomes de arquivo, o primeiro `:` vira `-` (`siscam-900001`, `sessao-<guid>`).

**Ordem das chaves** (duplicatas e processamento): `siscam` antes de `sessao`; `siscam` por id numérico crescente;
`sessao` pelo GUID em ordem de texto.

### 2.2 Documento

| Documento | Formato | Origem do id |
| --- | --- | --- |
| PL, substitutivo, requerimento, indicação, moção, PDL, resolução | `doc:<IdDocumento>` | `id` do registro (o de `DetalhesDocumentos.aspx?IdDocumento=`); o substitutivo usa o `id` do item em `substitutivos` do PL |
| Sessão (ata) | `sessao:<IdSessao>` | `id` da sessão em `data/sessoes/<ano>.json` |

Expressão: `^(doc|sessao):[1-9][0-9]*$`. O prefixo evita colisão entre as numerações de documento e de sessão;
`sessao:<IdSessao>` (documento, número) não se confunde com `sessao:<guid>` (arquivo).

### 2.3 Fila

Entram, por chave de arquivo:

- os `arquivos` de cada PL (`data/proposicoes/<ano>.json`) e de cada item de `substitutivos` do PL (o substitutivo
  real só tem `arquivos`, `autoria`, `data`, `id`, `lei`, `numero` = `"1"`, `situacao` e `tramitacoes`; não tem
  `ano` nem `ementa`);
- os `arquivos` de requerimentos, PDLs e resoluções (`data/documentos/{requerimento,pdl,resolucao}/<ano>.json`);
- as atas: itens de `documentos_sessao` com `rotulo` em `ROTULOS_ATA = {"Ata"}` e `url` não nula
  (`data/sessoes/<ano>.json`); as atas vêm como `.doc`, `.docx` ou `.pdf`, e uma sessão pode ter duas atas, ambas
  arquivos do documento `sessao:<IdSessao>`.

**Indicações e moções ficam fora do manifesto**, mesmo que passem a ter `arquivos` no detalhe; só a ementa
mascarada delas vai para a busca (`ementa:doc:<id>`).

### 2.4 Documentos citantes e documento principal

A entrada do manifesto é **uma por arquivo**:

- `documentos`: **todos** os documentos que citam o arquivo (por exemplo `["doc:<pl>", "doc:<substitutivo>"]`),
  sem repetição, em ordem crescente de texto (`sorted`); na entrada canônica de duplicatas, a união (seção 6.2);
- `documento`: o **documento principal**, que define `tipo`, o ano do manifesto, o caminho do `.txt`, a ementa
  passada à limpeza e o campo `documento` dos trechos:
  - o **PL** para qualquer arquivo do PL **ou de qualquer um dos seus substitutivos** — também quando só o
    substitutivo cita o arquivo (então `documento` não está em `documentos`); `tipo` é `pl`;
  - nos demais casos, o documento de maior prioridade na ordem `pl`, `requerimento`, `pdl`, `resolucao`, `ata`
    e, entre eles, o de menor id numérico.

O texto e os trechos são gravados **uma vez**, no principal; a relação com os demais fica em `arquivo_documento`
(D1). Um arquivo compartilhado não duplica trechos nem vetores. `tipo` nunca é `substitutivo` no manifesto; o
valor existe em `documentos.tipo` do D1.

## 3. Ano do manifesto

O arquivo é `data/textos/manifesto-<ano>.json`, onde `<ano>` é o campo **`ano` do registro** do documento principal
(`data/proposicoes/<ano>.json` ou `data/documentos/<tipo>/<ano>.json`), **não** o ano da `data`; arquivos de
substitutivo usam o `ano` do PL; atas, o `ano` da sessão. Uma entrada fica num único manifesto; se o principal mudar
de ano, a entrada muda de arquivo na mesma execução.

## 4. Manifesto

`data/textos/manifesto-<ano>.json`, gravado só por `coletor.arquivos.salvar_mapa`: objeto JSON com uma chave por
linha, chaves ordenadas, valores compactos com chaves ordenadas, UTF-8, `ensure_ascii=False`, LF e quebra final.

### 4.1 Campos de cada entrada

Todos os campos estão sempre presentes (sem extras); "nulo" é `null` no JSON.

| Campo | Tipo | Conteúdo |
| --- | --- | --- |
| `documentos` | lista de texto | Documentos que citam o arquivo (seção 2.4), ordenados, não vazia |
| `documento` | texto | Documento principal (seção 2.4) |
| `tipo` | texto | Tipo do principal: `pl`, `requerimento`, `pdl`, `resolucao` ou `ata` |
| `url_origem` | texto | URL HTTPS de download: `https://consultaniteroi.siscam.com.br/Download.aspx?id=<IdArquivo>` ou a URL da ata em `documentos_sessao`, como está |
| `sha256_original` | texto ou nulo | SHA-256 (64 hexadecimais minúsculos) dos bytes do original; nulo em `pendente_download` e em `removido` nunca baixado |
| `bytes` | inteiro ou nulo | Tamanho do original; nulo quando `sha256_original` é nulo |
| `formato` | texto ou nulo | `Resultado.formato` (`docx`, `doc`, `rtf`, `html`, `texto`, `pdf`, `jpeg`, `png`, `tiff`, `zip`, `vazio`, `desconhecido`); nulo sem extração |
| `extrator` | texto ou nulo | `Resultado.extrator` (`docx`, `doc`, `pdftotext`, `pdftotext+tesseract`, `tesseract`, `zip`…); vazio vira nulo |
| `versao_extrator` | texto ou nulo | `Resultado.versao_extrator` (`VERSAO_EXTRATORES` nos extratores em Python; versão das ferramentas nos externos, como `25.07.0+5.5.3`); vazio vira nulo |
| `versao_extratores` | texto ou nulo | `VERSAO_EXTRATORES` na extração |
| `versao_limpeza` | texto ou nulo | `limpeza.versao_efetiva(RAIZ)` na limpeza (`VERSAO_LIMPEZA` + `+` + 8 hexadecimais dos clichês) |
| `versao_mascara` | texto ou nulo | `VERSAO_MASCARA` na máscara |
| `versao_trechos` | texto ou nulo | `VERSAO_TRECHOS` na divisão |
| `sha256_config` | texto ou nulo | `limpeza.hash_config(RAIZ)` no processamento (seção 1) |
| `paginas` | inteiro | `Resultado.paginas`: páginas do PDF, 1 em imagens, soma dos membros num zip, 0 nos formatos sem páginas |
| `paginas_ocr` | inteiro | `Resultado.paginas_ocr` |
| `confianca` | número ou nulo | `Resultado.confianca` (0–100) arredondada a 1 casa decimal; nulo sem OCR |
| `cabecalhos_omitidos` | inteiro | `Resultado.cabecalhos_omitidos`: partes de cabeçalho/rodapé (docx) ou histórias de cabeçalho (doc) fora do texto salvo |
| `detalhe` | texto | `Resultado.detalhe` passado por `mascarar` e limitado a 300 caracteres, ou `"esvaziado pela limpeza"`; `""` quando não há |
| `status` | texto | Seção 5 |
| `duplicata_de` | texto ou nulo | Em `duplicata`, a chave canônica (seção 6.2); nulo nas demais |
| `limpeza` | objeto ou nulo | `{linhas_removidas, por_regra}`, das contagens de `limpar`; `por_regra` tem `cabecalho_rodape`, `numeracao`, `ruido_ocr` e `cliche`, e `linhas_removidas` é a soma deles; nulo sem `.txt` |
| `mascarados` | objeto ou nulo | Contagem de `mascarar` por tipo: `cpf`, `rg`, `telefone`, `email`, `documento` (`mascara.TIPOS`); nulo sem `.txt` |
| `sha256_bruto` | texto ou nulo | SHA-256 do UTF-8 do texto bruto (passo 2); nulo sem `.txt` |
| `sha256_texto` | texto ou nulo | SHA-256 dos bytes do `.txt` (seção 7.1); nulo sem `.txt` |
| `blob_texto` | texto ou nulo | SHA-1 do blob do Git dos bytes do `.txt`, `sha1(b"blob <tamanho>\0" + bytes)` (o de `git hash-object`): identifica o texto na branch `dados-textos` e sobrevive à reescrita do histórico; nulo sem `.txt` |
| `chars` | inteiro | Pontos de código do texto final (sem a quebra final do `.txt`); 0 sem `.txt` |
| `trechos` | inteiro | Quantidade de trechos do arquivo |
| `trechos_vetorizaveis` | inteiro | Trechos com `vetorizavel: true` |
| `r2_chave` | texto ou nulo | `sha256/<aa>/<bb>/<sha256_original>`, com `<aa>` e `<bb>` os 2 primeiros e os 2 seguintes hexadecimais; nulo em `removido`, `pendente_download` e `duplicata` |
| `processado_em` | texto | Data `AAAA-MM-DD` (Brasília) da última execução que mudou algum de: `sha256_original`, qualquer `versao_*`, `sha256_config`, `status` ou `sha256_texto` (seção 9) |

### 4.2 Campos por situação

| Situação | `.txt` e trechos | Extração (`formato`…`detalhe`), versões e `sha256_config` | `limpeza`, `mascarados`, `sha256_bruto`, `sha256_texto`, `blob_texto` | `r2_chave` |
| --- | --- | --- | --- | --- |
| `ok`, `ok_ocr`, `ok_parcial`, `ocr_baixa_confianca`, e `vazio_legitimo` esvaziado pela limpeza | sim (o esvaziado: `.txt` `"\n"`, 0 trechos) | preenchidos | preenchidos | sim |
| `vazio_legitimo` do extrator, `escaneado_sem_ocr`, `pendente_ferramenta`, `erro_formato` | não | preenchidos | nulos; `chars`, `trechos`, `trechos_vetorizaveis` = 0 | sim |
| `removido`, `pendente_download`, `duplicata` | não | nulos (`paginas`, `paginas_ocr`, `cabecalhos_omitidos` = 0, `detalhe` = `""`) | nulos; contagens 0 | nulo |

## 5. Status

| Status | Origem | Significado | Sucesso | Com texto | Reprocessável |
| --- | --- | --- | --- | --- | --- |
| `ok` | extratores | Texto extraído sem OCR | sim | sim | por versão ou configuração |
| `ok_ocr` | extratores | Todas as páginas escaneadas lidas pelo OCR, confiança média ≥ `CONFIANCA_MINIMA` (60) | sim | sim | por versão ou configuração |
| `vazio_legitimo` | extratores ou limpeza | Zero caracteres úteis (arquivo vazio, OCR sem texto) ou texto esvaziado pela limpeza | sim | não | por versão ou configuração |
| `ok_parcial` | extratores | Há páginas com texto (do PDF ou do OCR) e páginas escaneadas sem OCR (desligado, adiado pelo orçamento ou com falha); o texto disponível é gravado e pesquisável | não (listado no relatório) | sim | com `--ocr` |
| `ocr_baixa_confianca` | extratores | OCR com confiança média < 60; o texto é gravado e pesquisável | não (listado no relatório) | sim | por versão |
| `escaneado_sem_ocr` | extratores | Páginas escaneadas sem OCR e **nenhuma** página com texto | não | não | com `--ocr` |
| `pendente_ferramenta` | extratores | pdftotext, pdftoppm, tesseract ou o idioma `por` ausente | não | não | sempre |
| `erro_formato` | extratores | Arquivo malformado, truncado, criptografado ou acima dos limites (`detalhe` diz o motivo) | não | não | por versão |
| `removido` | remoções | Coincide com `config/remocoes.json` (seção 6.1) | — | não | nunca, enquanto a remoção existir |
| `pendente_download` | `coletor.textos` | Ainda sem os bytes (`--sem-rede` sem cache ou falha de download) | não | não | sempre |
| `duplicata` | `coletor.textos` | Mesmo original de outra chave (seção 6.2) | — | não | quando o original muda |

**Sucesso** = `ok`, `ok_ocr` ou `vazio_legitimo`. A base das metas é o conjunto de arquivos do escopo, exceto
`removido` e `duplicata`. `ok_parcial` e `ocr_baixa_confianca` têm texto pesquisável, mas cada caso entra no relatório.

## 6. Remoções e duplicatas

### 6.1 Remoções

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

- Campos exatamente `chave` (expressão da seção 2.1), `sha256`, `motivo`, `fonte` (HTTPS) e `data` (`AAAA-MM-DD`,
  não futura); ordem por (`data`, `chave`, `sha256`), sem pares repetidos; JSON com `indent=1`, ordem das chaves
  preservada, UTF-8, LF, NFC.
- Leitura: `coletor.remocoes.carregar(raiz)`, `chaves_removidas(raiz)` e `esta_removido(raiz_ou_cache, chave,
  sha256)`. Um arquivo está removido quando **a chave ou o SHA-256 do original** coincide com algum item.
- **Pela chave**: o arquivo não é baixado; a entrada vira `removido` e mantém `sha256_original` e `bytes` de uma
  entrada anterior, se houver, ou nulos se nunca foi baixado.
- **Pelo SHA-256** (o mesmo original sob uma chave nova): o arquivo é baixado só para calcular o hash; os bytes são
  descartados (sem cache local, sem R2) e a entrada vira `removido`, com `sha256_original` e `bytes`.
- Efeitos: `coletor.textos` não processa o arquivo; o `.txt` e os trechos saem de `dados-textos` (com reescrita do
  histórico no expurgo da T4.2.4); no D1 saem `arquivos`, `arquivo_documento`, `trechos` e `trechos_fts`, e o item
  entra em `remocoes`; os vetores saem do Vectorize e de `trechos_indexados`; o original sai do R2; as exportações,
  inclusive as antigas, são regravadas sem o item. `remocoes` é consultada pelo Worker antes da Cache API.

### 6.2 Duplicatas

O mesmo `sha256_original` sob chaves diferentes (fora as removidas) gera **uma** entrada canônica: a menor chave na
ordem da seção 2.1. A canônica é processada normalmente, com `documentos` = união dos documentos que citam
qualquer uma das chaves e o principal recalculado sobre essa união. As outras chaves recebem `status: "duplicata"`,
`duplicata_de: <chave canônica>`, `sha256_original`, `bytes`, os **seus** `documentos`, `documento`, `tipo`,
`url_origem` e `processado_em`, com os demais campos como na seção 4.2: sem `.txt`, sem trechos, sem linhas em
`arquivos`/`trechos` do D1 nem vetores. A busca chega a elas pela canônica (`arquivo_documento`).

## 7. Branch `dados-textos`

### 7.1 Textos

`textos/<tipo>/<ano>/<documento-sem-prefixo>/<origem>-<id>.txt`, com `tipo`, `ano` e documento do principal.
Exemplos: `textos/pl/2024/127858/siscam-900005.txt` (arquivo só do substitutivo, no PL),
`textos/ata/2024/5001/sessao-<guid>.txt`.

- Conteúdo: o texto final (passo 5) seguido de **uma** quebra `\n`; UTF-8 sem BOM, LF, NFC; já limpo e mascarado.
- O leitor remove **exatamente uma** quebra final (`conteudo[:-1]`); o resultado satisfaz
  `trechos.normalizar(texto) == texto`, e é sobre ele que valem os offsets dos trechos e `chars`. O texto pode
  terminar em `"\n\f\n"` (última página vazia), então não se removem outras quebras.
- Páginas separadas por uma linha só com `\f` (`trechos.SEPARADOR_PAGINA = "\n\f\n"`); `\f` não aparece em outro
  lugar.
- `sha256_texto` e `blob_texto` cobrem os bytes do arquivo inteiro.

### 7.2 Trechos

`trechos/<tipo>/<ano>.jsonl`: um objeto JSON por linha, com `json.dumps(..., ensure_ascii=False, sort_keys=True,
separators=(",", ":"))`, ordenado por (`documento`, `arquivo`, `posicao`) e quebra final. O arquivo reúne os trechos
dos `.txt` de `textos/<tipo>/<ano>/`. Campos, exatamente os de `trechos.dividir`, **sem o texto**:

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

## 8. Projeções no Cloudflare

D1, Vectorize e R2 são reconstruíveis a partir do Git (`python -m coletor.nuvem --reconstruir`).

### 8.1 Tabelas D1 (`worker/migrations/0001_inicial.sql`)

| Tabela | Colunas | Chave e índices | Conteúdo |
| --- | --- | --- | --- |
| `documentos` | `id` TEXT, `tipo` TEXT, `numero` TEXT, `ano` INTEGER, `data` TEXT, `ementa` TEXT, `url` TEXT, `legislatura` TEXT, `pl` TEXT | PK `id`; índices (`tipo`, `ano`) e (`pl`) | Todos os documentos, inclusive indicações e moções (só ementa). `id` como na seção 2.2; `tipo` inclui `substitutivo`, `indicacao` e `mocao`; `numero` como gravado (`"29/2024"` nos PLs, `"1"` nos substitutivos); `ementa` mascarada; `url` pública do detalhe no SISCAM; `legislatura` como em `config/vereadores.json` (`2021-2024`). O substitutivo herda `ano`, `ementa` e `legislatura` do PL e tem `pl` = chave do PL; nos demais, `pl` é NULL |
| `autoria` | `documento` TEXT, `slug` TEXT, `papel` TEXT | PK (`documento`, `slug`, `papel`); índice (`slug`) | Autores; `papel` `autor` ou `coautor` |
| `pessoas` | `slug` TEXT, `nome` TEXT, `partido_atual` TEXT | PK `slug` | Slug e nome do modelo do site; `partido_atual` pode ser NULL |
| `arquivos` | `id` TEXT, `sha256` TEXT, `formato` TEXT, `status` TEXT, `ocr` INTEGER, `confianca` REAL, `r2_chave` TEXT | PK `id` | Uma linha por entrada do manifesto, exceto `removido` e `duplicata`; `id` = chave do manifesto; `ocr` = 1 se `paginas_ocr` > 0 |
| `arquivo_documento` | `arquivo` TEXT, `documento` TEXT | PK (`arquivo`, `documento`) | Relação N:N a partir de `documentos` de cada entrada (na canônica, a união das duplicatas) |
| `trechos` | `id` TEXT, `documento` TEXT, `arquivo` TEXT, `posicao` INTEGER, `texto` TEXT, `sha256` TEXT | PK `id`; índice (`documento`) | Texto lido do `.txt` pelos offsets e conferido pelo `sha256` |
| `trechos_fts` | `id` (UNINDEXED), `texto_norm` | FTS5 com `tokenize='unicode61'`; `rowid` = `int(id, 16) >> 1` | Busca por palavras; reconstruível, fora das exportações. O suporte do D1 a `remove_diacritics` não foi confirmado: `texto_norm` é o texto do trecho já normalizado por `coletor.nuvem.fonte.normalizar_busca` (NFD, sem marcas `Mn`, NFC e minúsculas: "Licença" → "licenca"), e a consulta é normalizada do mesmo jeito, no Worker com exatamente `s.normalize("NFD").replace(/\p{Mn}/gu, "").normalize("NFC").toLowerCase()`; os pares de `tests/fixtures/contratos/normalizacao.json` valem para as duas implementações |
| `trechos_indexados` | `id` TEXT, `sha256` TEXT | PK `id` | Vetores já enviados ao Vectorize (trechos e `ementa:doc:<id>`), para a diferença incremental. `sha256` = SHA-256 (hexadecimal) da concatenação do `sha256` do texto com os metadados do vetor em JSON (chaves ordenadas, sem espaços, UTF-8), de modo que mudar só os metadados também reenvia o vetor; `pendente` marca um upsert em curso |
| `remocoes` | `chave` TEXT, `sha256` TEXT, `motivo` TEXT, `data` TEXT | PK (`chave`, `sha256`) | Cópia de `config/remocoes.json` sem `fonte` |
| `estado_indice` | `id` INTEGER (= 1), `versao` TEXT, `commit` TEXT, `sha256_manifestos` TEXT, `total` INTEGER, `sha256_conjunto` TEXT, `modelo` TEXT, `versao_trechos` TEXT, `data` TEXT | PK `id` | Uma linha, gravada só no fim de uma sincronização completa. `commit`: commit de `main` dos manifestos; `sha256_manifestos`: SHA-256 da concatenação dos bytes de `data/textos/manifesto-*.json` em ordem crescente de ano; `sha256_conjunto`: SHA-256 das linhas `"<id> <sha256>\n"` de todos os trechos, ordenadas por `id` |
| `verificacoes` | `data` TEXT, `amostra` INTEGER, `ok` INTEGER, `falhas_json` TEXT | PK `data` (carimbo ISO UTC) | Única escrita do Worker (cron): conferência dos hashes por amostragem |

### 8.2 Vectorize

- Índice `radar-niteroi-trechos` (staging: `-staging`), `@cf/baai/bge-m3`, 1.024 dimensões, cosseno.
- Id do vetor: o `id` do trecho (16 hexadecimais) ou `ementa:doc:<IdDocumento>` para as ementas mascaradas de
  indicações e moções.
- Metadados: `{tipo, ano, legislatura, documento}`, com `ano` numérico, `tipo` e `legislatura` texto e
  `documento` como na seção 2.2. Índices de metadados: `tipo` (string), `ano` (number) e `legislatura` (string).
  O filtro por autor é feito no D1.
- Só trechos com `vetorizavel: true` viram vetor; duplicatas e removidos nunca.

### 8.3 R2

- Originais acima de `LIMITE_ENVIO_R2_REST` (100.000.000 bytes menos 1 MiB) são pulados só na via REST, com aviso e contagem `originais_grandes_demais`, sem falha: `arquivos.r2_chave` no D1 fica NULL (sem alterar o manifesto), `/api/documento` traz `url_original: null` e `/api/original/:sha256` responde 404 `original_indisponivel`, indicando o SISCAM; limite maior ou via S3 permite envio posterior.
- Originais no bucket privado `radar-niteroi-arquivos`, na chave `r2_chave`; servidos pelo Worker em
  `GET /api/original/:sha256` com `Content-Disposition: attachment`, `X-Robots-Tag: noindex`,
  `X-Content-Type-Options: nosniff` e `Content-Security-Policy: sandbox`, depois de consultar `remocoes`.
- Exportações em `radar-niteroi-exportacoes/<versao>/`: dump das tabelas-base, `vetores-<versao>.jsonl.gz` e
  `SHA256SUMS`.

## 9. Determinismo

- Mesma entrada (originais, código, `config/` e `data/textos/cliches.json`), mesmos bytes no manifesto, nos `.txt`
  e nos `.jsonl`.
- `processado_em` muda **somente** na execução em que muda algum de: `sha256_original`, `versao_extrator`,
  `versao_extratores`, `versao_limpeza`, `versao_mascara`, `versao_trechos`, `sha256_config`, `status` ou
  `sha256_texto`. Reprocessar sem essas mudanças preserva o valor anterior, mesmo que outro campo seja atualizado.
- Mudança de `sha256_config`: reprocessa todas as entradas com texto e roda `mascara.varrer` em **todos** os textos
  antes do commit.
- Ordem estável: chaves do manifesto ordenadas; `documentos` ordenada; processamento e duplicatas na ordem de chaves
  da seção 2.1; trechos por (`documento`, `arquivo`, `posicao`); JSON com chaves ordenadas.
- Gzip das exportações com `mtime=0` e sem nome de arquivo no cabeçalho; nenhum carimbo de relógio no conteúdo,
  exceto `processado_em`, `estado_indice.data` e `verificacoes.data`.
- Nenhum `.txt` ou trecho é gravado, commitado ou carregado com ocorrência forte de `mascara.varrer`.
