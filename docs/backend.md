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
| Worker | `radar-niteroi-api` | `radar-niteroi-api-staging` |

**Acesso aos buckets de originais.** Os buckets de originais, de produção e de staging, recusam acesso anônimo. Uma requisição S3 sem assinatura recebe HTTP 400, e o `r2.dev` está desativado neles. A escrita, a leitura e a remoção de um objeto de teste no staging funcionaram em 27/10/2026.

**Configuração do Worker:** `D:\git\radar-vereadores-niteroi\worker\wrangler.jsonc`, com os ambientes `staging` e `production`.
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

1. **Token da API Cloudflare** em `CLOUDFLARE_API_TOKEN`. Tipo "Custom token", com escopo **Account: Marco Jardim** e as permissões:
   - Account → D1: Edit;
   - Account → Vectorize: Edit;
   - Account → Workers AI: Read;
   - Account → Workers Scripts: Edit;
   - Account → Account Analytics: Read.
2. **Token do R2** em "R2 → Manage API tokens". Permissão "Object Read & Write", com escopo **só** nos quatro buckets `radar-niteroi-*`. O *Access Key ID* vai para `R2_ACCESS_KEY_ID` e o *Secret Access Key* para `R2_SECRET_ACCESS_KEY`. O endpoint S3 é `https://7b60055a9f153a4a8441ff519e1a208f.r2.cloudflarestorage.com`, na região `auto`.
3. **Secret `CLOUDFLARE_ACCOUNT_ID`** com o valor `7b60055a9f153a4a8441ff519e1a208f`.
4. **Alerta de cobrança.** Em "Notifications → Billing → Usage Based Billing", criar um aviso por e-mail quando o uso passar de US$ 10 acima da assinatura.

Para a carga a partir da máquina local, as mesmas credenciais entram só como variáveis de ambiente da sessão, nunca gravadas em arquivo.

**Limitação de isolamento.** As permissões de D1, Vectorize, Workers AI e Workers Scripts valem para a conta inteira, não para um recurso específico. O isolamento total exigiria uma conta Cloudflare separada, que só o titular pode criar.

## Rollback, recriação e reconstrução

- **Voltar a versão anterior do Worker:** `npx wrangler rollback --env production`, no diretório `D:\git\radar-vereadores-niteroi\worker`.
- **Reconstruir D1 e Vectorize a partir do Git:** `python -m coletor.nuvem --ambiente production --reconstruir`. Disponível a partir da Phase 2.2.
- **Recriar os recursos do zero:** repetir os comandos da Phase 0.2 com `CLOUDFLARE_ACCOUNT_ID` definido:
  - `npx wrangler r2 bucket create <nome>`;
  - `npx wrangler d1 create <nome>`;
  - `npx wrangler vectorize create <nome> --dimensions=1024 --metric=cosine`;
  - `npx wrangler vectorize create-metadata-index <nome> --propertyName=<p> --type=<t>`.

  Depois, atualizar os ids em `wrangler.jsonc`.
