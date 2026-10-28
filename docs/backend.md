# Backend Cloudflare e ferramentas de extração

Este documento acompanha o plano `D:\git\radar-vereadores-niteroi\docs\plans\2026-10-27-inteiro-teor-busca-cloudflare.md`. O Git continua sendo a fonte da verdade. D1, Vectorize e R2 são projeções que podem ser reconstruídas a partir do repositório e conferidas por hash.

## Ferramentas locais (carga inicial e OCR)

| Ferramenta | Versão | Instalação no Windows | No GitHub Actions |
|---|---|---|---|
| poppler: `pdftotext`, `pdftoppm` | 25.07.0 | `winget install --id oschwartz10612.Poppler -e` | `apt-get install -y poppler-utils` |
| Tesseract | 5.5.3.20260724 | `scoop install tesseract` | `apt-get install -y tesseract-ocr` |
| Dados de idioma `por` | tessdata_fast 4.1.0 | `scoop install tesseract-languages` (ajusta `TESSDATA_PREFIX` para `C:\Users\Marquinho\scoop\apps\tesseract-languages\current`) | `apt-get install -y tesseract-ocr-por` (também tessdata_fast) |

**Por que tessdata_fast.** É o mesmo modelo que o pacote `tesseract-ocr-por` do Ubuntu instala. Assim a carga local e o incremental no CI usam modelos equivalentes. O tessdata padrão e o `best` são mais lentos e não existem como pacote apt.

**Instalação do Tesseract.** O pacote `UB-Mannheim.TesseractOCR` do winget pede elevação e foi cancelado (0x800704c7), por isso o Tesseract veio do scoop. O texto extraído registra no manifesto o extrator e a versão de cada arquivo, e por isso diferenças de versão entre a máquina local e o CI não forçam reprocessamento.

**Observações do teste rápido:**
- O `pdftotext` pode emitir caracteres de formatação invisíveis (U+200B). O extrator remove todo caractere da categoria Unicode `Cf`.
- OCR de fotografias (JPG) gera ruído com confiança baixa. Esses arquivos ficam marcados como `ocr_baixa_confianca`.

**Cache local:** `D:\radar-niteroi-cache\`, apontado pela variável `RADAR_CACHE`. Fora do Windows, o padrão é `~/.cache/radar-niteroi`. Conteúdo:
- `html\`: páginas de detalhe;
- `arquivos\`: originais, com o nome igual ao SHA-256;
- `atas\`, `ocr\` e `exportacoes\`.

## Recursos na conta "Marco Jardim" (`7b60055a9f153a4a8441ff519e1a208f`)

| Recurso | Produção | Staging |
|---|---|---|
| R2: originais (privado) | `radar-niteroi-arquivos` | `radar-niteroi-arquivos-staging` |
| R2: exportações | `radar-niteroi-exportacoes`, com leitura pública em `https://pub-a0abbdd3b622466e871e3be479876cd4.r2.dev`. O `r2.dev` tem limite de taxa e o Cloudflare o descreve como não destinado a produção. Basta para downloads ocasionais de auditoria; com um domínio do projeto no Cloudflare, migrar com `npx wrangler r2 bucket domain add`. | `radar-niteroi-exportacoes-staging` (privado) |
| D1 | `radar-niteroi` (`8750fe41-d702-407f-9373-414529504ced`) | `radar-niteroi-staging` (`653aeeb5-072e-46b0-a429-53c030458349`) |
| Vectorize (1.024 dimensões, cosseno) | `radar-niteroi-trechos` | `radar-niteroi-trechos-staging` |
| Índices de metadados do Vectorize | `tipo` (string), `ano` (number), `legislatura` (string) | os mesmos |
| Worker | `radar-niteroi-api`, criado no primeiro deploy (Phase 3.2) | `radar-niteroi-api-staging`, criado no primeiro deploy (Phase 3.2) |

**Acesso aos buckets privados.** Os três buckets privados (`radar-niteroi-arquivos`, `radar-niteroi-arquivos-staging` e `radar-niteroi-exportacoes-staging`) foram conferidos em 27/10/2026 de duas formas:
- `npx wrangler r2 bucket dev-url get <bucket>` informa o acesso pelo `r2.dev` desativado;
- `npx wrangler r2 bucket domain list <bucket>` mostra que não há domínio personalizado ligado.

Uma requisição S3 sem assinatura recebe HTTP 400, mas isso acontece em qualquer bucket e não prova, sozinho, que ele é privado. No staging, gravar, ler e apagar um objeto de teste funcionou.

**Endereço da API.** `api_url` em `D:\git\radar-vereadores-niteroi\config\backend.json` continua `null` até o primeiro deploy (Phase 3.2), quando o Cloudflare informa o endereço `workers.dev`. Ele é preenchido depois da QA da Wave 3.

**Configuração do Worker:** `D:\git\radar-vereadores-niteroi\worker\wrangler.jsonc`. A **produção fica no nível superior**, então `npx wrangler deploy` sem `--env` publica a produção completa. O staging fica em `env.staging` e é publicado com `--env staging`. O wrangler fixado no `D:\git\radar-vereadores-niteroi\worker\package.json` (Phase 3.2) precisa suportar `ratelimits`, versão 4.36 ou posterior, e a `compatibility_date` 2026-10-01.
- Observabilidade e Logpush ficam desligados.
- O limite de CPU por requisição é configurado.
- Ficam definidos o metadado de versão, o Rate Limiting de 60 requisições por minuto, o Analytics Engine só com contagens e o cron diário de verificação.

**Sem trava de retenção nos buckets.** A remoção (art. 18 da LGPD) precisa alcançar todo o conteúdo. A imutabilidade das exportações vem de outros mecanismos:
- chaves versionadas;
- `If-None-Match: *` em cada escrita (o R2 avalia de forma atômica e responde 412 se o objeto já existir);
- `SHA256SUMS`;
- atestação do GitHub (`actions/attest@v4`).

**Cache das respostas.** O Worker usa a Cache API e não o produto Workers Cache. O Workers Cache responde antes de o código rodar, o que impediria a consulta à tabela de remoções antes de servir um original já em cache.

## Credenciais para o GitHub Actions (o humano cria no painel)

O princípio é o menor privilégio: tokens separados por função, chaves R2 separadas por ambiente e secrets de produção restritos à branch `main`.

1. **GitHub Environments.** Em "Settings → Environments", criar `staging` e `production`. Em `production`, a regra de branch é **só `main`**. Os secrets abaixo são gravados no Environment correspondente, não como secrets do repositório.
2. **Token de dados** em `CLOUDFLARE_API_TOKEN_DADOS`, nos dois Environments. Tipo "Custom token", com escopo **Account: Marco Jardim** e as permissões:
   - Account → D1: Edit;
   - Account → Vectorize: Edit;
   - Account → Workers AI: Read.

   No checkpoint T0.2.2, testar uma chamada real a `/ai/run/@cf/baai/bge-m3` com esse token. Se `Read` não bastar, trocar por `Workers AI: Edit`.
3. **Token de deploy** em `CLOUDFLARE_API_TOKEN_DEPLOY`, só no Environment `production`, com uma cópia no `staging` para o deploy de staging. Permissões:
   - Account → Workers Scripts: Edit;
   - Account → D1: Edit, porque o deploy aplica as migrações.
4. **Chaves do R2**, criadas em "R2 → Manage API tokens", com a permissão "Object Read & Write", **uma por ambiente**:
   - `staging`: escopo em `radar-niteroi-arquivos-staging` e `radar-niteroi-exportacoes-staging`;
   - `production`: escopo em `radar-niteroi-arquivos` e `radar-niteroi-exportacoes`.

   Em cada Environment, o *Access Key ID* vai para `R2_ACCESS_KEY_ID` e o *Secret Access Key* para `R2_SECRET_ACCESS_KEY`. O endpoint S3 é `https://7b60055a9f153a4a8441ff519e1a208f.r2.cloudflarestorage.com`, região `auto`.
5. **`CLOUDFLARE_ACCOUNT_ID`** = `7b60055a9f153a4a8441ff519e1a208f`. Não é segredo; pode ser uma variável do repositório.
6. **Alerta de cobrança.** Em "Notifications → Billing → Usage Based Billing", criar um aviso por e-mail para quando o uso passar de US$ 10 acima da assinatura.
7. **Métricas.** `Account Analytics: Read` não entra nos tokens do CI. Só quem consulta as métricas no painel precisa dela.

Para a carga a partir da máquina local, as mesmas credenciais entram como variáveis de ambiente da sessão. Nunca são gravadas em arquivo; o `.gitignore` cobre `.env*` e `/worker/.dev.vars*` por precaução.

**Limitação de isolamento.** As permissões de D1, Vectorize, Workers AI e Workers Scripts valem para a conta inteira, não para um recurso específico. O token de deploy consegue alterar Workers de outros projetos da conta. Por isso ele fica restrito ao Environment `production` e à branch `main`. Isolamento total exigiria uma conta Cloudflare separada, que só o titular pode criar.

## Rollback, recriação e reconstrução

- **Voltar a versão anterior do Worker:** `npx wrangler rollback`, no diretório `D:\git\radar-vereadores-niteroi\worker` (para o staging, `npx wrangler rollback --env staging`). Isso não desfaz migrações nem dados do D1.
- **Voltar o D1 a um ponto no tempo:** `npx wrangler d1 time-travel restore radar-niteroi --timestamp=<ISO>`. Também dá para reconstruir a partir do Git, como no item seguinte.
- **Reconstruir D1 e Vectorize a partir do Git:** `python -m coletor.nuvem --ambiente production --reconstruir`. Disponível a partir da Phase 2.2.
- **Recriar os recursos do zero:** repetir os comandos da Phase 0.2 com `CLOUDFLARE_ACCOUNT_ID` definido:
  - `npx wrangler r2 bucket create <nome>`;
  - `npx wrangler d1 create <nome>`;
  - `npx wrangler vectorize create <nome> --dimensions=1024 --metric=cosine`;
  - `npx wrangler vectorize create-metadata-index <nome> --propertyName=<p> --type=<t>`.

  - `npx wrangler r2 bucket dev-url enable radar-niteroi-exportacoes`, para reabrir a leitura pública.

  Depois, atualizar os ids em `wrangler.jsonc`. A URL `pub-…` das exportações muda ao recriar o bucket: atualizar este documento e os links da metodologia.

## Sincronização com a nuvem

`python -m coletor.nuvem` (pacote `coletor/nuvem/`, só biblioteca padrão) leva o Git a D1, Vectorize e R2, conforme o contrato `docs/contratos/textos.md` (seção 8). Lê os registros de `data/`, `config/`, os manifestos `data/textos/manifesto-<ano>.json` e o worktree da branch `dados-textos`.

```text
python -m coletor.nuvem --ambiente local --sqlite D:\radar-niteroi-cache\local.sqlite --simular
python -m coletor.nuvem --ambiente local --sqlite D:\radar-niteroi-cache\local.sqlite
python -m coletor.nuvem --ambiente staging
python -m coletor.nuvem --ambiente production --exportar D:\radar-niteroi-cache\exportacoes
python -m coletor.nuvem --ambiente production --reconstruir
python -m coletor.nuvem --ambiente staging --etapas r2
python -m coletor.nuvem --ambiente staging --etapas d1,vetores
```

| Opção | Efeito |
|---|---|
| `--etapas LISTA` | Etapas separadas por vírgula, entre `r2`, `d1`, `vetores` e `exportar` (padrão `r2,d1,vetores`; `--exportar` acrescenta `exportar`). Barreira de PII e migrações rodam sempre. `estado_indice` só é gravado quando `r2`, `d1` e `vetores` rodam juntos. Sem `r2`, arquivos cujo original ainda não foi conferido entram no D1 com `r2_chave` NULL, até uma execução com `r2`. |
| `--sem-r2` | Não usa o R2: pula a etapa `r2` e o envio da exportação (os arquivos ficam só na pasta local); não grava `estado_indice`. |
| `--ambiente local\|staging\|production` | `local`: SQLite (`--sqlite`, padrão `<cache>\local.sqlite`), R2 em `<pasta do SQLite>\r2\<bucket>\…`, Vectorize em `<pasta do SQLite>\vetores.jsonl` e embeddings falsos determinísticos (SHAKE-256, 1.024 dimensões), sem rede. `staging`/`production`: nomes e ids de `worker\wrangler.jsonc`. |
| `--simular` | Só leituras: imprime o plano (contagens por operação) sem gravar nada, nem o SQLite local. |
| `--exportar DIR` | Grava em `DIR\<versao>\` `d1-<versao>.sql` (tabelas-base, sem `trechos_fts`), `vetores-<versao>.jsonl.gz` (um vetor por linha, `values` em float32 little-endian base64, gzip com mtime 0 e sem nome) e `SHA256SUMS`, e envia ao bucket de exportações em `<versao>/…` (o `SHA256SUMS` por último). Se `<versao>/SHA256SUMS` já está no bucket, a versão inteira é pulada; se o conteúdo dele difere do gerado agora, sai um aviso. Os valores que faltam no cache de embeddings vêm de `get_by_ids` em lotes de 100 (20 se o índice recusar), dentro do ritmo global de 4 requisições por segundo. |
| `--reconstruir` | Limpa as tabelas-base, o FTS e `estado_indice` e regrava tudo a partir do Git; reenvia todos os vetores (reaproveitando o cache de embeddings) e apaga do índice todo vetor listado (`GET …/vectorize/v2/indexes/<índice>/list`, com cursor; sem a rota, `wrangler vectorize list-vectors --json`) que o Git não tem. |
| `--textos DIR` | Worktree de `dados-textos` (padrão: `RADAR_TEXTOS` ou `..\radar-vereadores-niteroi-textos`). |
| `--cache DIR` | Cache local (padrão: `RADAR_CACHE`). Originais em `arquivos\<sha256>`; embeddings em `embeddings\<modelo>\<aa>\<sha256>.f32`. |
| `--commit SHA` | Commit gravado em `estado_indice.commit` (padrão: `GITHUB_SHA` ou `git rev-parse HEAD`). |

**Etapas, nesta ordem:**
1. **Barreira de PII:** `mascara.varrer` (com `mascara.liberados`) em todo trecho, em toda ementa mascarada e em todo `motivo` de `config\remocoes.json` a enviar. Uma ocorrência forte aborta antes de qualquer escrita, listando origem, tipo e posição, nunca o valor.
2. **Migrações:** `worker\migrations\` é a pasta única. Local: `sqlite3`, com a mesma tabela `d1_migrations` do wrangler. Remoto: `wrangler d1 migrations apply <db> --remote [--env staging]`.
3. **R2 (`r2`):** os originais que ainda não constam em `arquivos` do D1 são conferidos (S3: `HEAD`; REST: `GET` com `Range: bytes=0-0`) e, se faltarem, enviados do cache (bytes conferidos pelo SHA-256), em até 4 envios simultâneos, com aviso de progresso a cada 100. Na via S3, o PUT leva `If-None-Match: *`, `Content-Type` e `x-amz-meta-documentos` (ids inteiros, até 1.500 caracteres); na via REST, PUT sem condição depois da conferência (a chave é o SHA-256 do conteúdo) e sem metadados. Original ausente no cache é falha, tudo ou nada por arquivo: nesta execução ficam de fora a linha em `arquivos`, as de `arquivo_documento`, os trechos (com o FTS) e os vetores daquele arquivo, e `estado_indice` fica como estava. Os originais de `config\remocoes.json` são apagados (`DELETE`, só aqui).
4. **D1 (`d1`):** diferença de `documentos`, `autoria`, `pessoas`, `arquivos`, `arquivo_documento`, `trechos` (texto = `conteudo[:-1][inicio:fim]`, conferido pelo `sha256`) e `remocoes` contra o Git: grava o que mudou e apaga o que saiu do Git ou entrou nas remoções. Cada bloco de trechos vai no **mesmo lote atômico** das suas linhas de `trechos_fts` (DELETE dos rowids, INSERT dos trechos, INSERT do FTS), então uma falha no meio nunca separa os dois. Se mesmo assim os conjuntos de ids divergirem (duas consultas `LIMIT 1`, nos dois sentidos, conferindo também o `rowid`), o FTS é refeito por inteiro. A leitura das tabelas pagina por chave (`WHERE chave > última … LIMIT 5000`), sem `OFFSET`. Até 5.000 instruções vão por lotes REST (100 parâmetros e 100 KB por instrução, sem `BEGIN`/`COMMIT`, cada lote atômico). Acima disso, por um arquivo `.sql` temporário e `wrangler d1 execute <db> --remote --yes --file=…`: essa importação **bloqueia o banco** enquanto roda (o Worker não responde), por isso fica só para cargas enormes, como a primeira.
5. **Vectorize (`vetores`):** primeiro confere o índice (`info`: 1.024 dimensões; `metadata_index/list`: `tipo` string, `ano` number, `legislatura` string) e aborta antes de qualquer embedding se algo faltar. Vetores só para trechos vetorizáveis novos ou alterados e para as ementas mascaradas de indicações e moções (`ementa:doc:<id>`), pela diferença contra `trechos_indexados`, cujo `sha256` é o SHA-256 de (`sha256` do texto + metadados em JSON com chaves ordenadas): mudar só os metadados também reenvia o vetor. Metadados `{tipo, ano, legislatura, documento}`. Embeddings `@cf/baai/bge-m3` em lotes de 50 (dimensão conferida: 1.024), upsert em lotes de 1.000 (até 5.000 e 100 MB). Os ids ainda sem registro entram em `trechos_indexados` como `pendente` **antes** do upsert e recebem o hash real depois: nenhum vetor enviado fica sem registro. `delete_by_ids` apaga os ids registrados que saíram do Git, os trechos apagados nesta execução e as ementas dos documentos apagados. Toda mutação precisa devolver `mutationId`; ao fim, a execução espera (até 1.800 s) `processedUpToMutation` igual à última mutação e `processedUpToDatetime` ≥ início da execução (com 60 s de folga para o relógio). Trocar o modelo reenvia todos os vetores.
6. **Estado:** `estado_indice` só no fim, sem falhas, com as etapas `r2`, `d1` e `vetores`, e só se algo além da data mudou. O `commit` faz parte da comparação.

Uma segunda execução sem mudanças no Git **e no mesmo commit** não faz nenhuma escrita; num commit novo, mesmo sem outra mudança, `estado_indice` é regravado (uma escrita), porque guarda o commit. Código de saída: 0 sem falhas, 1 com falhas.

**Credenciais.** Token da API: `CLOUDFLARE_API_TOKEN` ou `CLOUDFLARE_API_TOKEN_DADOS`; sem eles, o login OAuth do wrangler (`npx wrangler login`), lido de `oauth_token` em `WRANGLER_CONFIG` ou, por padrão, `%USERPROFILE%\.wrangler\config\default.toml` (Windows) ou `~/.config/.wrangler/config/default.toml`. O token OAuth dura cerca de 1 hora: vencido (`expiration_time`) ou recusado com 401, é renovado executando `wrangler whoami` (o wrangler renova o próprio login) e relendo o arquivo, com uma única nova tentativa por 401. Com o login OAuth, os subprocessos do wrangler não recebem `CLOUDFLARE_API_TOKEN` e usam o próprio login. Conta: `CLOUDFLARE_ACCOUNT_ID` (padrão: `account_id` de `worker\wrangler.jsonc`). R2: com `R2_ACCESS_KEY_ID` e `R2_SECRET_ACCESS_KEY`, a via S3 (SigV4); sem elas, a API REST `…/accounts/<conta>/r2/buckets/<bucket>/objects/<chave>` com o token Bearer. Todas as chamadas à API de um ambiente remoto compartilham um ritmo de 4 requisições por segundo (limite global de 1.200 a cada 5 minutos).

**Wrangler.** `worker\package.json` fixa a versão exata (`4.154.0`, igual a `coletor.nuvem.wrangler.VERSAO_WRANGLER`). Com `npm ci` em `worker\`, os comandos usam `npx --no-install wrangler`; sem `worker\node_modules\wrangler`, `npx --yes wrangler@4.154.0`. No Windows, `npx.cmd` é procurado primeiro. Cada comando tem prazo de 900 s e recebe uma lista de argumentos (sem shell).

**Segurança.** Mensagens de erro trazem só esquema, host e caminho das URLs; tokens, assinaturas SigV4 e segredos aparecem como `***`. 429 respeita `Retry-After`; 5xx e falhas de rede têm até 5 tentativas com espera progressiva.

**Busca por palavras.** O D1 não confirmou `remove_diacritics`, por isso `trechos_fts` guarda `texto_norm` (NFD, sem marcas `Mn`, NFC e minúsculas, como `coletor.nuvem.fonte.normalizar_busca`). O Worker aplica à consulta exatamente

```js
s.normalize("NFD").replace(/\p{Mn}/gu, "").normalize("NFC").toLowerCase()
```

e junta por `trechos_fts.id = trechos.id`. Os pares de `tests\fixtures\contratos\normalizacao.json` valem para as duas implementações (o teste Python já os confere; o do Worker entra com ele).

## API do Worker

Código em `worker\src\`, detalhes em `worker\README.md`. Só leitura, `GET`/`HEAD`/`OPTIONS`, erros `{erro, codigo}`:

| Rota | Conteúdo | Cache API |
|---|---|---|
| `/api/busca?q=&modo=palavras\|semantica\|hibrida&tipo=&ano=&autor=&legislatura=&pagina=` | FTS5 (`bm25`, termos entre aspas), Vectorize (`topK` 50, `returnMetadata: "indexed"`, filtros `tipo`/`ano`/`legislatura`) e RRF k = 60; autor no D1; 10 por página, até a página 50 | 60 s |
| `/api/documento/:id` | metadados, autoria, arquivos não removidos e substitutivos | 1 dia |
| `/api/original/:sha256` | download do R2 privado; `remocoes` consultada antes da Cache API (410) | 1 dia, `no-store` para o cliente |
| `/api/versao`, `/api/saude` | `COMMIT`, `CF_VERSION_METADATA` e `estado_indice`; D1 e última verificação | não |

As chaves de cache da busca e do documento incluem um resumo de `estado_indice`. CORS só para `ORIGENS_CORS` e
`localhost`; Rate Limiting de 60 por minuto com o IP resumido por SHA-256; `METRICAS` só com o modo e a contagem.
A Cache API não opera em `*.workers.dev`. Testes: `npm test` e `npm run typecheck` em `worker\`.

**Carga em staging com o login OAuth** (sem chaves S3; na raiz do repositório, com `RADAR_CACHE` e `RADAR_TEXTOS` definidos ou `--cache`/`--textos`):

```powershell
npx --yes wrangler@4.154.0 whoami   # confirma o login (e o renova)
python -m coletor.nuvem --ambiente staging --simular
python -m coletor.nuvem --ambiente staging
```

A execução completa grava `estado_indice`; repetida no mesmo commit, não faz nenhuma escrita. Para dividir a carga, rode `--etapas r2,d1` e depois `--etapas vetores` (nenhuma das duas grava `estado_indice`) e termine com a execução completa, que então só confere e grava o estado. Evite `--etapas d1` sem `r2` numa carga nova: os arquivos entram com `r2_chave` NULL e a próxima etapa `r2` confere todos de novo.
