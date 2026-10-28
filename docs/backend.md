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
```

| Opção | Efeito |
|---|---|
| `--ambiente local\|staging\|production` | `local`: SQLite (`--sqlite`, padrão `<cache>\local.sqlite`), R2 em `<pasta do SQLite>\r2\<bucket>\…`, Vectorize em `<pasta do SQLite>\vetores.jsonl` e embeddings falsos determinísticos (SHAKE-256, 1.024 dimensões), sem rede. `staging`/`production`: nomes e ids de `worker\wrangler.jsonc`. |
| `--simular` | Só leituras: imprime o plano (contagens por operação) sem gravar nada, nem o SQLite local. |
| `--exportar DIR` | Grava em `DIR\<versao>\` `d1-<versao>.sql` (tabelas-base, sem `trechos_fts`), `vetores-<versao>.jsonl.gz` (um vetor por linha, `values` em float32 little-endian base64, gzip com mtime 0 e sem nome) e `SHA256SUMS`, e envia ao bucket de exportações em `<versao>/…` com `If-None-Match: *` (o `SHA256SUMS` por último). |
| `--reconstruir` | Limpa as tabelas-base, o FTS e `estado_indice` e regrava tudo a partir do Git; reenvia todos os vetores (reaproveitando o cache de embeddings). |
| `--textos DIR` | Worktree de `dados-textos` (padrão: `RADAR_TEXTOS` ou `..\radar-vereadores-niteroi-textos`). |
| `--cache DIR` | Cache local (padrão: `RADAR_CACHE`). Originais em `arquivos\<sha256>`; embeddings em `embeddings\<modelo>\<aa>\<sha256>.f32`. |
| `--commit SHA` | Commit gravado em `estado_indice.commit` (padrão: `GITHUB_SHA` ou `git rev-parse HEAD`). |

**Etapas, nesta ordem:**
1. **Barreira de PII:** `mascara.varrer` (com `mascara.liberados`) em todo trecho e em toda ementa mascarada a enviar. Uma ocorrência forte aborta antes de qualquer escrita, listando origem, tipo e posição, nunca o valor.
2. **Migrações:** `worker\migrations\` é a pasta única. Local: `sqlite3`, com a mesma tabela `d1_migrations` do wrangler. Remoto: `npx wrangler d1 migrations apply <db> --remote [--env staging]`.
3. **R2:** os originais que ainda não constam em `arquivos` do D1 são conferidos por `HEAD` e, se faltarem, enviados do cache (bytes conferidos pelo SHA-256) com `If-None-Match: *`, `Content-Type` e `x-amz-meta-documentos`. Original ausente no cache é falha: a linha do arquivo não é gravada e `estado_indice` fica como estava. Os originais de `config\remocoes.json` são apagados (`DELETE`, só aqui).
4. **D1:** diferença de `documentos`, `autoria`, `pessoas`, `arquivos`, `arquivo_documento`, `trechos` (texto = `conteudo[:-1][inicio:fim]`, conferido pelo `sha256`) e `remocoes` contra o Git: grava o que mudou e apaga o que saiu do Git ou entrou nas remoções. O FTS acompanha os trechos e é refeito se a contagem divergir. Até 400 instruções vão por lotes REST (100 parâmetros e 100 KB por instrução, sem `BEGIN`/`COMMIT`). Acima disso, por um arquivo `.sql` temporário e `npx wrangler d1 execute <db> --remote --file=…`.
5. **Vectorize:** vetores só para trechos vetorizáveis novos ou alterados e para as ementas mascaradas de indicações e moções (`ementa:doc:<id>`), pela diferença contra `trechos_indexados` (`sha256` do texto). Metadados `{tipo, ano, legislatura, documento}`. Embeddings `@cf/baai/bge-m3` em lotes de 50 (dimensão conferida: 1.024), upsert em lotes de 1.000 (até 5.000 e 100 MB), `delete_by_ids` para os ids que saíram e espera por `processedUpToMutation`. Trocar o modelo reenvia todos os vetores.
6. **Estado:** `estado_indice` só no fim, sem falhas, e só se algo além da data mudou.

Uma segunda execução sem mudanças no Git não faz nenhuma escrita. Código de saída: 0 sem falhas, 1 com falhas.

**Segurança.** Credenciais só por variáveis de ambiente (`CLOUDFLARE_API_TOKEN` ou `CLOUDFLARE_API_TOKEN_DADOS`, `CLOUDFLARE_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`). Mensagens de erro trazem só esquema, host e caminho das URLs; tokens, assinaturas SigV4 e segredos aparecem como `***`. 429 respeita `Retry-After`; 5xx e falhas de rede têm até 5 tentativas com espera progressiva.

**Busca por palavras.** O D1 não confirmou `remove_diacritics`, por isso `trechos_fts` guarda `texto_norm` (NFD sem marcas `Mn`, minúsculas, como `coletor.nuvem.fonte.normalizar_busca`). O Worker aplica a mesma normalização à consulta (`normalize("NFD")`, sem `\p{Mn}`, `toLowerCase()`) e junta por `trechos_fts.id = trechos.id`.
