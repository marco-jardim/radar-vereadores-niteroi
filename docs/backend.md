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
