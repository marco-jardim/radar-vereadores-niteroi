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

**Endereço da API — pré-requisitos de publicação.** `api_url` em `D:\git\radar-vereadores-niteroi\config\backend.json` continua `null` até a QA da Wave 3, a configuração de uma **rota em domínio próprio** e a publicação da nota pública `metodologia.html#privacidade`. O endereço `workers.dev` do primeiro deploy não basta: a Cache API nele é um **no-op**, então não protege o orçamento de D1/AI/Vectorize. A rota em domínio próprio deve existir antes de preencher `api_url` (não é criada nesta etapa).

`/api/original` serve o **original sem mascaramento, tal como publicado pelo SISCAM**, como registro público.
Só os textos extraídos, inclusive ementas da busca, são mascarados; os bytes do original não são alterados.
A nota pública de privacidade deve explicar essa distinção antes da ativação de `api_url`. O link nas respostas
410 vem de `URL_SITE`, definido nos dois ambientes do Worker, para `${URL_SITE}/metodologia.html#privacidade`.

**Configuração do Worker:** `D:\git\radar-vereadores-niteroi\worker\wrangler.jsonc`. A **produção fica no nível superior**, então `npx wrangler deploy` sem `--env` publica a produção completa. O staging fica em `env.staging` e é publicado com `--env staging`. O wrangler fixado no `D:\git\radar-vereadores-niteroi\worker\package.json` (Phase 3.2) precisa suportar `ratelimits`, versão 4.36 ou posterior, e a `compatibility_date` 2026-10-01.
- Observabilidade e Logpush ficam desligados.
- O limite de CPU por requisição é configurado.
- Ficam definidos o metadado de versão, o Rate Limiting de 60 requisições por minuto, o Analytics Engine só com contagens e o cron diário de verificação.

**Sem trava de retenção nos buckets.** A remoção (art. 18 da LGPD) precisa alcançar todo o conteúdo. A imutabilidade das exportações vem de outros mecanismos:
- chaves versionadas;
- `If-None-Match: *` em cada escrita (o R2 avalia de forma atômica e responde 412 se o objeto já existir);
- `SHA256SUMS`;
- atestação do GitHub (`actions/attest@v4`).

### Remoção e expurgo (T4.2.4)

Após aprovação do pedido, registre somente chave, hash do original, motivo público sem dados pessoais,
fonte e data em `config/remocoes.json`, conforme o contrato congelado (§6.1). Execute a sequência normal
`coletor.textos` → validação → `coletor.nuvem` no ambiente correto. Não remova a entrada da configuração:
ela impede o retorno em coletas futuras, inclusive do mesmo original sob outra chave.

- `textos` aplica as remoções em **todos os manifestos**, antes da fila e fora dos filtros de ano/tipo,
  prazo e limite de arquivos. Apaga `.txt` (inclusive caminhos antigos) e linhas de trechos; mantém
  `status: removido`, `sha256_original` e `bytes`. O manifesto não admite campos extras e exige `detalhe`
  vazio nesse status: o motivo é preservado no config e na tabela D1 `remocoes`, não no manifesto.
- A sincronização completa apaga `arquivos`, `arquivo_documento`, `trechos`, `trechos_fts`, os vetores dos
  trechos e `trechos_indexados`, além dos originais no R2. **Documento, autoria e ementa pública permanecem**
  (inclusive `ementas_fts` e vetores de ementas), pois a remoção do contrato é de arquivo, não de documento.
- Com remoções pendentes, a etapa R2 também varre **todas as versões do bucket público de exportações**, mesmo sem
  `--exportar`. Cada dump histórico afetado é regravado sem o arquivo e seus trechos/vetores, preservando os
  demais dados daquele momento, em **outra versão determinística**, com novos nomes e `SHA256SUMS`.
  Só após confirmar os bytes dos três objetos novos, apaga todos os objetos da versão antiga e sua cópia
  na pasta local de exportações usada na execução. Não há sobrescrita silenciosa de versão publicada.
  A varredura ocorre antes de confirmar as remoções no D1 e de gravar `estado_indice`: uma interrupção
  deixa a diferença pendente para a próxima execução. Tombstones já aplicados, sem cópias locais afetadas,
  não provocam consultas ao bucket em toda sincronização. A carga inicial sem histórico no D1 nem cópias
  locais não pressupõe exportações antigas; se o D1 foi perdido/recriado ou houve execução parcial,
  use `--reconstruir` para conferir também o histórico remoto, mesmo sem diferença de remoções no D1.
  `SHA256SUMS` divergente numa versão afetada interrompe o expurgo sem apagá-la; numa versão não afetada,
  gera somente aviso, sem sobrescrita.
- Recibos `remocoes/<versao-antiga>.json` no bucket guardam somente a nova versão e o hash de `SHA256SUMS`:
  permitem retomar exclusões interrompidas, inclusive em outra máquina. O resultado é registrado pela
  sincronização em **Registro de expurgos de exportações**, ao fim deste documento. Revise e versione esse
  registro, sem acrescentar dados pessoais; novas atestações devem se referir aos novos `SHA256SUMS`.
  Remoções sucessivas mantêm os recibos anteriores e formam uma cadeia: a retomada confirma os dois
  arquivos e `SHA256SUMS` do destino final antes de excluir as versões intermediárias.
- `--simular` não expurga nem registra; etapas parciais e `--sem-r2` **não comprovam** remoção completa.
  Guarde o relatório da execução, confira ausência dos objetos antigos no bucket público e o 410 do
  original. Limpe também outras cópias locais de exportações e artefatos de CI que possam conter o item.
  Não faça rollback de dados/configuração para uma versão anterior à remoção.

#### Histórico de `dados-textos`: procedimento manual, com aprovação humana

O expurgo automático remove a versão corrente, **não reescreve Git nem faz force-push**. Se dado pessoal
vazou no histórico, um responsável deve aprovar expressamente escopo (chaves, hashes, caminhos em todas
as versões), janela de manutenção e reescrita de `dados-textos`. Não ponha o dado vazado em issue, log,
mensagem de commit ou neste documento. `git filter-repo` é ferramenta operacional externa, não dependência
do coletor; instale-a separadamente e confira sua versão antes da intervenção.

1. Suspenda coleta/publicação e impeça pushes concorrentes. Anote o SHA remoto de `dados-textos` para
   `--force-with-lease`. Faça uma cópia restrita para contingência, com responsável e prazo de destruição;
   ela contém o vazamento e não pode virar artefato público. Prepare fora do clone uma fotografia já
   expurgada e validada do HEAD (somente a árvore limpa, sem `.git`, cache bruto ou arquivos desconhecidos).
2. Use **clone fresco isolado**, não o worktree diário. Inventarie os caminhos históricos do `.txt` por
   chave (tipo/ano/principal podem ter mudado) e todos os JSONL que contiveram seus trechos. Para evitar
   registrar texto pessoal em regras de substituição, remova esses caminhos do histórico inteiro.
   Exemplo **sintético**, a adaptar ao inventário aprovado:

   ```text
   git clone --single-branch --branch dados-textos <URL-DO-REPOSITORIO> dados-textos-expurgo
   cd dados-textos-expurgo
   git filter-repo --refs refs/heads/dados-textos --invert-paths --path-glob "textos/**/siscam-123.txt" --path trechos/pl/2024.jsonl
   ```

   A remoção do JSONL inteiro elimina também trechos históricos não afetados desse arquivo agregado;
   isso deve constar da aprovação. Restaure **somente no novo HEAD** a fotografia limpa para conservar
   os trechos atuais permitidos, faça commit e valide hashes, offsets e barreira de PII. Não restaure do
   histórico antigo. Se for necessário conservar os trechos históricos alheios, aprove e teste um callback
   `git filter-repo` que filtre JSONL por `arquivo`, em vez de eliminar o caminho agregado.
3. Inspecione todos os commits/refs alcançáveis do clone reescrito e confirme ausência dos blobs/textos
   removidos, não apenas do HEAD. Revise tags/refs adicionais que apontem para a branch antiga. Confira
   que manifestos atuais de `main` continuam com tombstones e que `config/remocoes.json` segue vigente.
   `blob_texto` dos textos preservados continua válido; não existe vínculo por commit no manifesto.
4. **Só com nova confirmação humana**, publique exclusivamente a branch aprovada:

   ```text
   git push <URL-DO-REPOSITORIO> refs/heads/dados-textos:refs/heads/dados-textos --force-with-lease=refs/heads/dados-textos:<SHA-REMOTO-ANOTADO>
   ```

   Não use `--mirror` nem force-push de `main`. Se a lease falhar, pare e refaça a revisão.
5. Invalide clones/worktrees antigos, elimine refs de contingência/reflogs e cópias locais após o prazo
   aprovado, e peça aos colaboradores um clone novo (não merge/rebase da branch antiga). Solicite ao
   suporte do GitHub a purga de caches, refs de PR e blobs ainda acessíveis; force-push sozinho não garante
   eliminação no provedor ou em forks. Revogue artefatos/atestação antiga que exponham o conteúdo e confira
   exportações, R2 e o acesso público. Registre só versões, hashes técnicos e aprovação, nunca o dado pessoal.
6. Reative a automação apenas depois de uma execução normal de textos/validação/nuvem, conferindo que o
   item não retorna. Não execute esse procedimento automaticamente no CI.

**Cache das respostas.** O Worker usa a Cache API e não o produto Workers Cache. O Workers Cache responde antes de o código rodar, o que impediria a consulta à tabela de remoções antes de servir um original já em cache.
No domínio próprio, rankings de busca são guardados por consulta normalizada/modo/filtros/estado/remoções, sem
`pagina`, por 60 s; páginas só hidratam seu recorte. Embeddings são guardados por consulta normalizada/modelo
por uma hora. Objetos R2 só são clonados para a Cache API até 10 MiB; acima disso, o stream vai direto ao cliente.
GET e HEAD de originais informam o tamanho do R2, e ambos usam `no-store` para o cliente.

## Credenciais para o GitHub Actions (o humano cria no painel)

O princípio é o menor privilégio: tokens separados por função, chaves R2 separadas por ambiente e secrets de produção restritos à branch `main`.

1. **GitHub Environments.** Em "Settings → Environments", criar `pr-simulacao`, `staging` e `production`. Em `staging` e `production`, a regra de branch é **só `main`**; `production` exige também um revisor. Os secrets abaixo são gravados no Environment correspondente, não como secrets do repositório.
   - `pr-simulacao` recebe **somente** `CLOUDFLARE_API_TOKEN_LEITURA` (D1: Read, Vectorize: Read, Workers AI: Read; sem R2 nem escrita). O job de PR do `textos.yml` roda código do PR e por isso nunca recebe tokens de escrita; sem esse secret, ou em PR de fork, a simulação é pulada com aviso.
2. **Token de dados** em `CLOUDFLARE_API_TOKEN_DADOS`, nos Environments `staging` e `production`. Tipo "Custom token", com escopo **Account: Marco Jardim** e as permissões:
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

**Cache do `textos.yml`.** O cache do Actions guarda só os originais baixados do SISCAM (documentos públicos) e os mapas id→SHA-256, nunca texto extraído, cache de OCR ou texto bruto anterior à máscara: caches da branch base podem ser restaurados por workflows de PR. O job de PR não restaura cache. A chave é semanal e o salvamento roda mesmo em falha (`actions/cache/save` com `if: always()`). Sem o cache de OCR, cada execução refaz o OCR apenas dos arquivos novos ou alterados, que são os únicos processados no modo incremental. Depois do merge, **apague manualmente** em "Actions → Caches" os caches antigos `textos-*-ocr-v1-*`, criados antes dessa restrição. O `npm ci` em `worker/` mantém os scripts de instalação (o wrangler precisa do binário `workerd`); por isso o checkout não persiste credenciais e o token de push do Git só entra nos passos de push.

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
| `--exportar DIR` | Grava em `DIR\<versao>\` `d1-<versao>.sql` (ou partes `d1-<versao>-<NNN>.sql`), `vetores-<versao>-<NNN>.jsonl.gz` e `SHA256SUMS`, e envia ao bucket de exportações em `<versao>/…` (o `SHA256SUMS` por último). Se `<versao>/SHA256SUMS` já está no bucket, inclusive no formato antigo sem partes, a versão inteira é pulada; se o conteúdo dele difere do gerado agora, sai um aviso, sem sobrescrever. Os valores que faltam no cache de embeddings vêm de `get_by_ids` em lotes de 100 (20 se o índice recusar), dentro do ritmo global de 4 requisições por segundo. |
| `--reconstruir` | Limpa as tabelas-base, o FTS e `estado_indice` e regrava tudo a partir do Git; reenvia todos os vetores (reaproveitando o cache de embeddings) e apaga do índice todo vetor listado (`GET …/vectorize/v2/indexes/<índice>/list`, com cursor; sem a rota, `wrangler vectorize list-vectors --json`) que o Git não tem. |
| `--textos DIR` | Worktree de `dados-textos` (padrão: `RADAR_TEXTOS` ou `..\radar-vereadores-niteroi-textos`). |
| `--cache DIR` | Cache local (padrão: `RADAR_CACHE`). Originais em `arquivos\<sha256>`; embeddings em `embeddings\<modelo>\<aa>\<sha256>.f32`. |
| `--commit SHA` | Commit de `main` dos manifestos, gravado em `estado_indice.commit` (padrão: `GITHUB_SHA` ou `git rev-parse HEAD`). |
| `--commit-dados-textos SHA` | Commit independente dos JSONL, gravado em `estado_indice.commit_dados_textos` (padrão: `git -C <textos> rev-parse HEAD` do worktree, quando disponível; não usa `GITHUB_SHA`). |

**Partes das exportações.** Cada objeto de dados tem até **90.000.000 bytes enviados**, abaixo do teto
da API REST do R2, sem exigir chaves S3 ou multipart. `NNN` começa em `001` em cada conjunto (mínimo de
três dígitos). As partes preservam linhas inteiras e ordem determinística; o orçamento também limita a
entrada antes da compressão. Os vetores têm um registro por linha em ordem de `id`, com `values` em
float32 little-endian base64; cada parte tem gzip independente, `mtime=0` e nenhum nome no cabeçalho.
O dump contém tabelas-base, sem `trechos_fts` nem `ementas_fts`. Confira **todos** os arquivos listados em
`SHA256SUMS`; concatene as partes SQL na ordem numérica antes de importar e, para os vetores, descomprima
cada parte e concatene na mesma ordem. Uma linha indivisível acima do limite causa falha antes do envio.
O expurgo lê tanto partes quanto os arquivos únicos antigos, regrava em partes limitadas e só apaga
todos os objetos da versão antiga depois de confirmar os hashes de todas as partes do destino.
Uma publicação interrompida retoma sem reenviar objetos já presentes; o `SHA256SUMS` encerra a publicação.

**Etapas, nesta ordem:**
1. **Barreira de PII:** `mascara.varrer` (com `mascara.liberados`) em todo trecho, em toda ementa mascarada e em todo `motivo` de `config\remocoes.json` a enviar. Uma ocorrência forte aborta antes de qualquer escrita, listando origem, tipo e posição, nunca o valor.
2. **Migrações:** `worker\migrations\` é a pasta única. Local: `sqlite3`, com a mesma tabela `d1_migrations` do wrangler. Remoto: `wrangler d1 migrations apply <db> --remote [--env staging]`.
3. **R2 (`r2`):** os originais que ainda não constam em `arquivos` do D1 são conferidos (S3: `HEAD`; REST: `GET` com `Range: bytes=0-0`) e, se faltarem, enviados do cache (bytes conferidos pelo SHA-256), em até 4 envios simultâneos, com aviso de progresso a cada 100. Na via S3, o PUT leva `If-None-Match: *`, `Content-Type` e `x-amz-meta-documentos` (ids inteiros, até 1.500 caracteres); na via REST, PUT sem condição depois da conferência (a chave é o SHA-256 do conteúdo) e sem metadados. Original ausente no cache é falha, tudo ou nada por arquivo: nesta execução ficam de fora a linha em `arquivos`, as de `arquivo_documento`, os trechos (com o FTS) e os vetores daquele arquivo, e `estado_indice` fica como estava. Os originais de `config\remocoes.json` são apagados (`DELETE`, só aqui).
4. **D1 (`d1`):** diferença de `documentos`, `autoria`, `pessoas`, `arquivos`, `arquivo_documento`, `trechos` (texto = `conteudo[:-1][inicio:fim]`, conferido pelo `sha256`) e `remocoes` contra o Git: grava o que mudou e apaga o que saiu do Git ou entrou nas remoções. Cada bloco de trechos vai no **mesmo lote atômico** das suas linhas de `trechos_fts` (DELETE dos rowids, INSERT dos trechos, INSERT do FTS), então uma falha no meio nunca separa os dois. Se mesmo assim os conjuntos de ids divergirem (duas consultas `LIMIT 1`, nos dois sentidos, conferindo também o `rowid`), o FTS é refeito por inteiro. A leitura das tabelas pagina por chave (`WHERE chave > última … LIMIT 5000`), sem `OFFSET`. Até 5.000 instruções vão por lotes REST (100 parâmetros e 100 KB por instrução, sem `BEGIN`/`COMMIT`, cada lote atômico). Acima disso, por um arquivo `.sql` temporário e `wrangler d1 execute <db> --remote --yes --file=…`: essa importação **bloqueia o banco** enquanto roda (o Worker não responde), por isso fica só para cargas enormes, como a primeira.
5. **Vectorize (`vetores`):** primeiro confere o índice (`info`: 1.024 dimensões; `metadata_index/list`: `tipo` string, `ano` number, `legislatura` string) e aborta antes de qualquer embedding se algo faltar. Vetores só para trechos vetorizáveis novos ou alterados e para as ementas mascaradas de indicações e moções (`ementa:doc:<id>`), pela diferença contra `trechos_indexados`, cujo `sha256` é o SHA-256 de (`sha256` do texto + metadados em JSON com chaves ordenadas): mudar só os metadados também reenvia o vetor. Metadados `{tipo, ano, legislatura, documento}`. Embeddings `@cf/baai/bge-m3` em lotes de 50 (dimensão conferida: 1.024), upsert em lotes de 1.000 (até 5.000 e 100 MB). Os ids ainda sem registro entram em `trechos_indexados` como `pendente` **antes** do upsert e recebem o hash real depois: nenhum vetor enviado fica sem registro. `delete_by_ids` apaga os ids registrados que saíram do Git, os trechos apagados nesta execução e as ementas dos documentos apagados. Toda mutação precisa devolver `mutationId`; ao fim, a execução espera (até 1.800 s) `processedUpToMutation` igual à última mutação e `processedUpToDatetime` ≥ início da execução (com 60 s de folga para o relógio). Trocar o modelo reenvia todos os vetores.
6. **Estado:** `estado_indice` só no fim, sem falhas, com as etapas `r2`, `d1` e `vetores`, e só se algo além da data mudou. Ambos os commits (`commit` e `commit_dados_textos`) fazem parte da comparação; a migração `0005_estado_commit_dados_textos.sql` acrescenta a referência dos JSONL sem alterar a dos manifestos.

**Originais grandes via REST.** A API REST tem teto de corpo de 100 MB decimais; `LIMITE_ENVIO_R2_REST` reserva 1 MiB de margem (98.951.424 bytes). Acima dele, o original não é lido nem enviado: entra na contagem `originais_grandes_demais` e em `::warning::` com chave e tamanho, sem falha nem bloqueio de `estado_indice`. Texto, FTS e vetores continuam publicados; só `arquivos.r2_chave` no D1 fica NULL, sem mudar o manifesto. O Worker informa 404 `original_indisponivel` com link ao SISCAM quando disponível, e `/api/documento` traz `url_original: null`. Repetir a sincronização não tenta o PUT nem gera escritas por esses arquivos. Para enviá-los depois, disponibilize `R2_ACCESS_KEY_ID` e `R2_SECRET_ACCESS_KEY` e repita a sincronização completa (ou `--etapas r2,d1` para atualizar só os downloads); elevar o limite, se a API passar a aceitá-lo, também os recoloca na fila. O cliente S3/SigV4 não recebe esse teto REST; multipart ainda não está implementado e pode ser acrescentado nessa via. `wrangler r2 object put` limita a 315 MB, portanto não é alternativa para um original de 333,3 MB.

Uma segunda execução sem mudanças no Git **e no mesmo commit** não faz nenhuma escrita; num commit novo, mesmo sem outra mudança, `estado_indice` é regravado (uma escrita), porque guarda o commit. Código de saída: 0 sem falhas, 1 com falhas.

No GitHub Actions, falhas na sincronização real emitem `::error::` com a orientação
“re-execute com workflow_dispatch”: a publicação de `dados-textos` já pode ter sido concluída,
e a nova execução deve concluir a projeção na nuvem. A simulação não emite essa orientação.

**Credenciais.** Token da API: `CLOUDFLARE_API_TOKEN` ou `CLOUDFLARE_API_TOKEN_DADOS`; sem eles, o login OAuth do wrangler (`npx wrangler login`), lido de `oauth_token` em `WRANGLER_CONFIG` ou, por padrão, `%USERPROFILE%\.wrangler\config\default.toml` (Windows) ou `~/.config/.wrangler/config/default.toml`. O token OAuth dura cerca de 1 hora: vencido (`expiration_time`) ou recusado com 401, é renovado executando `wrangler whoami` (o wrangler renova o próprio login) e relendo o arquivo, com uma única nova tentativa por 401. Com o login OAuth, os subprocessos do wrangler não recebem `CLOUDFLARE_API_TOKEN` e usam o próprio login. Conta: `CLOUDFLARE_ACCOUNT_ID` (padrão: `account_id` de `worker\wrangler.jsonc`). R2: com `R2_ACCESS_KEY_ID` e `R2_SECRET_ACCESS_KEY`, a via S3 (SigV4); sem elas, a API REST `…/accounts/<conta>/r2/buckets/<bucket>/objects/<chave>` com o token Bearer. Todas as chamadas à API de um ambiente remoto compartilham um ritmo de 4 requisições por segundo (limite global de 1.200 a cada 5 minutos).

**Wrangler.** `worker\package.json` fixa a versão exata (`4.154.0`, igual a `coletor.nuvem.wrangler.VERSAO_WRANGLER`). Com `npm ci` em `worker\`, os comandos usam `npx --no-install wrangler`; sem `worker\node_modules\wrangler`, `npx --yes wrangler@4.154.0`. No Windows, `npx.cmd` é procurado primeiro. Cada comando tem prazo de 900 s e recebe uma lista de argumentos (sem shell).

**Segurança.** Mensagens de erro trazem só esquema, host e caminho das URLs; tokens, assinaturas SigV4 e segredos aparecem como `***`. 429 respeita `Retry-After`; 5xx e falhas de rede têm até 5 tentativas com espera progressiva.

**Busca por palavras.** `modo=palavras` consulta o inteiro teor em `trechos_fts` e as ementas mascaradas de **todos** os documentos em `ementas_fts` (inclusive indicações, moções, substitutivos e sessões). O D1 não confirmou `remove_diacritics`, por isso ambos guardam `texto_norm` (NFD, sem marcas `Mn`, NFC e minúsculas, como `coletor.nuvem.fonte.normalizar_busca`). O Worker aplica à consulta exatamente

```js
s.normalize("NFD").replace(/\p{Mn}/gu, "").normalize("NFC").toLowerCase()
```

e junta por `trechos_fts.id = trechos.id` ou `ementas_fts.documento = documentos.id`, sem depender do rowid da ementa. Os pares de `tests\fixtures\contratos\normalizacao.json` valem para as duas implementações.
O FTS5 ordena e limita os primeiros 5.000 candidatos **de cada índice antes** das junções e dos filtros no D1.
Os termos são escapados e colocados entre aspas nas duas consultas. Os filtros `tipo`, `ano`, `legislatura` e `autor` são aplicados no SQL.
Depois o SQL funde as listas por documento (menor `rank`, melhor correspondência) e limita a 500 documentos; `total` conta documentos uma única vez, mesmo com ementa e trecho correspondentes.
Se a melhor correspondência é a ementa, o destaque vem dela e os campos de arquivo são nulos.
Remoções por chave ou SHA-256 excluem os trechos, não a ementa mascarada pública, mesmo quando todos os arquivos do documento foram removidos.
`modo=hibrida` usa a lista **inteira** de palavras (até 500 documentos) no RRF com a lista semântica,
sem cortar as palavras aos primeiros 50. `total` é o tamanho da união por documento; `limitado` é verdadeiro
se a lista de palavras atingiu um teto ou a lista semântica atingiu o `topK` da consulta.
`ementas_fts` é sincronizada por diferença (inclusive alterações e exclusões), reconstruída com `--reconstruir` e não entra nas exportações, como `trechos_fts`.
`limitado` avisa ao atingir qualquer teto; filtros seletivos podem deixar resultados além do teto de candidatos.
Consultas só com termos menores que três caracteres ou só palavras vazias comuns do português recebem
400 `consulta_muito_generica`. O destaque usa **`destacar` sobre o original acentuado**, escapando HTML,
em vez de `snippet()` do FTS, que só conhece o texto normalizado sem acentos.

## API do Worker

Código em `worker\src\`, detalhes em `worker\README.md`. Só leitura, `GET`/`HEAD`/`OPTIONS`, erros `{erro, codigo}`:

| Rota | Conteúdo | Cache API |
|---|---|---|
| `/api/busca?q=&modo=palavras\|semantica\|hibrida&tipo=&ano=&autor=&legislatura=&pagina=` | FTS5 (`bm25`, termos entre aspas), Vectorize (`topK` 50, `returnMetadata: "indexed"`, filtros `tipo`/`ano`/`legislatura`) e RRF k = 60; autor no D1; 10 por página, até a página 50 | 60 s |
| `/api/documento/:id` | metadados, autoria, arquivos não removidos e substitutivos | 60 s |
| `/api/original/:sha256` | download do R2 privado; `remocoes` consultada antes da Cache API (410) | 1 dia até 10 MiB, `no-store` para o cliente |
| `/api/versao`, `/api/saude` | `COMMIT`, `CF_VERSION_METADATA` e `estado_indice`; D1 e última verificação | não |

As chaves de cache incluem um resumo de `estado_indice` e da lista ordenada de `remocoes`, lidos no mesmo lote
D1: uma remoção invalida o cache mesmo sem atualizar o estado numa sincronização parcial. Busca e documento
permitem no máximo 60 s de cache no cliente; erros e respostas com `aviso` sempre usam `no-store`.
CORS em produção só para origens HTTPS exatas de `ORIGENS_CORS` (igual a `config/backend.json`);
somente `AMBIENTE=staging` permite também `http://localhost[:porta]` e `http://127.0.0.1[:porta]`.
Rate Limiting de 60 por minuto com IPv4 ou prefixo IPv6 /64 resumido por SHA-256; `METRICAS` só com o modo e a contagem.
A Cache API não opera em `*.workers.dev`. Testes: `npm test` e `npm run typecheck` em `worker\`.

**Filtros e limitação semântica.** Vectorize usa `topK = 50`; com autor ou `tipo=substitutivo`, usa
`topK = 100`, máximo permitido com `returnMetadata: "indexed"`. A autoria é filtrada depois no D1
(inclusive dos documentos que citam o mesmo arquivo). O tipo de um trecho é filtrado pelas associações
`arquivo_documento` com `documentos`, além do tipo do documento principal do trecho: o arquivo de um substitutivo
pode devolver o trecho no PL principal. Para `tipo=substitutivo`, o filtro de tipo não vai ao Vectorize
(os metadados têm o tipo principal `pl`); é aplicado no D1 após o `topK`. Os demais tipos continuam usando
o filtro de metadados, além da conferência no D1; ementas usam o próprio tipo do documento.
Portanto ainda podem faltar resultados fora dos 100 primeiros; não há garantia de recuperação exaustiva
por autor ou substitutivo. Consultas D1 de candidatos são divididas em lotes para respeitar os 100 parâmetros
por instrução.

**Consulta normalizada.** Após remover acentos e converter para minúsculas, a busca usa palavras
alfanuméricas distintas, na ordem original, sem as palavras vazias (`PALAVRAS_VAZIAS` em `texto.ts`).
Conserva até dez termos, dos quais no máximo um tem menos de três caracteres; os demais são ignorados.
`consulta_truncada` na resposta informa esse descarte (não a simples remoção de palavras vazias/repetidas);
`consulta` preserva a entrada. MATCH, embedding e suas chaves de cache usam os mesmos termos efetivos:
acrescentar palavras vazias não exige novo embedding. Sem termo específico de ao menos três caracteres,
retorna 400 `consulta_muito_generica`.

`HEAD /api/busca` valida os mesmos parâmetros do GET: retorna 200 se válidos ou 400 se inválidos,
sempre sem corpo e sem executar a busca (nem consultar D1, AI ou Vectorize).

### Cron diário de verificação

`worker/src/cron.ts`, ligado ao `scheduled`, roda às **07:17 UTC** somente em produção; staging não tem gatilho,
para não comparar seus recursos com os dados de produção. Lê todos os manifestos
de 2021 até o ano UTC do evento (`data/textos/manifesto-<ano>.json`); 404 de ano sem manifesto é normal.
`CRON_RAW_BASE`, `CRON_MANIFESTOS_BRANCH` e `CRON_TEXTOS_BRANCH`, definidos nos dois ambientes do wrangler,
apontam para `https://raw.githubusercontent.com/marco-jardim/radar-vereadores-niteroi`, `main` e `dados-textos`.
Manifestos são buscados no `estado_indice.commit` (commit de `main`); JSONL em
`estado_indice.commit_dados_textos` (commit da branch `dados-textos`), pois `main` não contém `trechos/`.
As referências independentes evitam divergências na janela entre publicação no Git e sincronização.
Cada referência NULL usa só a sua branch configurada (`main` ou `dados-textos`), inclusive nos índices antigos.
Só aceita o host raw do GitHub, sem seguir redirecionamentos.

A amostra tem até **50 arquivos** de no máximo **três grupos (tipo, ano)** por dia. Os grupos são ordenados
e percorridos numa janela circular, com início no número do dia UTC × 3, cobrindo todos em até
`ceil(grupos / 3)` dias com conjunto estável. Dentro de cada grupo, Fisher–Yates usa a data UTC e ordenação
inicial por chave; os candidatos são intercalados entre grupos. Mesma data e mesmo conjunto elegível dão
a mesma amostra. Exclui removidos, duplicatas, downloads pendentes,
originais acima de 98.951.424 bytes e `r2_chave` NULL no manifesto ou D1. Cada original é lido diretamente do R2
por `crypto.DigestStream` (SHA-256), sem bufferizar o corpo, e comparado com `sha256_original` do manifesto.
Compara também o conjunto completo de ids/hashes em `trechos.sha256` do D1 com `trechos/<tipo>/<ano>.jsonl`
do Git e a contagem do manifesto; cada JSONL necessário é buscado uma única vez, em streaming com
`TextDecoderStream` e separação por linhas (limite de 1 Mi de caracteres por linha), retendo só ids/hashes
dos arquivos amostrados, nunca o arquivo inteiro. O total de bytes originais enviados ao hash tem teto de
**300 MB decimais** por execução, inclusive leituras que falhem. Ao faltar saldo, cancela o corpo e marca
esse arquivo e os restantes como `r2/adiado`, sem contá-los em `ok`. O limite de CPU permanece em 1.000 ms,
também para preservar o teto do handler público; a auditoria não amplia os limites das consultas.

A única tabela escrita pelo Worker é `verificacoes`: antes das leituras insere a linha com contagens zeradas
e `falhas_json = [{"etapa":"cron","codigo":"iniciado"}]`; ao terminar faz UPDATE da mesma linha.
Uma execução morta por CPU/memória ou sem conseguir concluir a gravação fica visível como `cron/iniciado`,
sem exigir coluna nova. Os campos são `data` ISO UTC do evento, `amostra` examinada (inclui adiados), `ok`
(contagem de arquivos íntegros nos dois testes) e `falhas_json` com etapa/código fixos, chave válida e/ou ano.
Não guarda texto, valores de dados pessoais, mensagens de exceção ou pilhas. Falhas de rede, formato, D1 e R2
são registradas sem interromper o handler; se o próprio D1 não aceitar a gravação, não é possível persistir
o diagnóstico. `/api/saude` mostra as contagens da última verificação; os detalhes estão em `falhas_json`.
`ok = amostra` não dispensa examinar `falhas_json` (por exemplo, pode faltar a leitura de um manifesto).

Há teto de **240 subrequisições** (incluindo inserção inicial, leitura do estado e atualização final), sem retentativas, prazo global de 240 s para as leituras
e de até 10 s por operação, inclusive consumo dos corpos; a gravação tem mais 10 s reservados.
Uma base vazia gera `amostra = ok = 0`. A verificação não repara nem publica dados: em divergência, confira
o Git e execute a sincronização/reconstrução apropriada. Testes offline em `worker/test/cron.test.ts`.

**Carga em staging com o login OAuth** (sem chaves S3; na raiz do repositório, com `RADAR_CACHE` e `RADAR_TEXTOS` definidos ou `--cache`/`--textos`):

```powershell
npx --yes wrangler@4.154.0 whoami   # confirma o login (e o renova)
python -m coletor.nuvem --ambiente staging --simular
python -m coletor.nuvem --ambiente staging
```

A execução completa grava `estado_indice`; repetida no mesmo commit, não faz nenhuma escrita. Para dividir a carga, rode `--etapas r2,d1` e depois `--etapas vetores` (nenhuma das duas grava `estado_indice`) e termine com a execução completa, que então só confere e grava o estado. Evite `--etapas d1` sem `r2` numa carga nova: os arquivos entram com `r2_chave` NULL e a próxima etapa `r2` confere todos de novo.
