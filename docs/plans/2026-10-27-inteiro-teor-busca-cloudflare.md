# Plano: inteiro teor, OCR, busca com D1, Vectorize e R2 no Cloudflare, e temas por IA

- **Repositório:** `D:\git\radar-vereadores-niteroi`
- **Plataforma:** win32 · **Shell:** pwsh 7 · **Python:** 3.12+ (CI 3.12) · **Node:** 22 nos testes (24 local)
- **Data:** 27/10/2026.
- **Revisão:** 3.
  - Incorpora os 41 achados da revisão adversarial `[tier:heavy]` da revisão 1.
  - Incorpora os 6 achados parciais e os 13 novos da revisão de acompanhamento (seção 6).
- **Executor:** um único agente LLM de alta capacidade, orquestrador do model-router, do início ao fim.
- **Conta Cloudflare:** `Marco Jardim`.
  - `CLOUDFLARE_ACCOUNT_ID=7b60055a9f153a4a8441ff519e1a208f`.
  - Plano Workers Paid.
  - wrangler 4.154 logado por OAuth na máquina local.
- **Branch de integração:** `inteiro-teor-busca`, criada a partir de `main` na Phase 0.1. Recebe push frequente. Um PR em rascunho dá retorno do CI. Merge só na Wave 5.
- **Branch de dados textuais:** `dados-textos`, órfã, criada na Phase 2.1, no worktree `D:\git\radar-vereadores-niteroi-textos`.

---

## 0. Objetivo, escopo e decisões

### 0.1 Objetivo central

Tornar pesquisável e auditável o inteiro teor dos documentos da Câmara de Niterói, com busca por palavras e por significado sobre um backend Cloudflare. Condições:

- **Fonte da verdade:** o Git continua sendo a fonte da verdade. D1, Vectorize e R2 são projeções reconstruíveis a partir do Git e verificáveis por hash.
- **Site:** o site estático funciona sem o backend. A busca é melhoria progressiva.
- **Privacidade:** dados pessoais ficam mascarados em tudo o que é pesquisável, conforme a seção 0.3. Os originais ficam íntegros no R2, em bucket privado. São servidos pelo Worker com proteções e respeitam pedidos de remoção.
- **OCR:** feito todo localmente na carga inicial. O incremental roda em cron híbrido: o GitHub Actions processa e publica, e o Cloudflare Worker cron verifica e expõe a saúde do índice.
- **IA de texto:** `deepseek-v4.1-flash` pelo OpenCode Go (`OPENCODE_API_KEY`), usada só para os temas, num bloco próprio separado do "Resumo em números".
- **Vetores:** `@cf/baai/bge-m3` do Workers AI, com 1.024 dimensões.

### 0.2 Escopo de documentos

| Conjunto | Registros | Inteiro teor | Busca |
|---|---|---|---|
| PLs (`D:\git\radar-vereadores-niteroi\data\proposicoes\*.json`) | 2.055 | sim | palavras + vetores |
| Substitutivos (dentro dos PLs) | 38 | sim | palavras + vetores |
| Requerimentos, PDLs e resoluções (`D:\git\radar-vereadores-niteroi\data\documentos\{requerimento,pdl,resolucao}\*.json`) | 1.153 + 1.648 + 147 | sim | palavras + vetores |
| Atas de sessão (`documentos_sessao` com `rotulo` em `ROTULOS_ATA = {"Ata"}` em `D:\git\radar-vereadores-niteroi\data\sessoes\*.json`) | 584 | sim | palavras + vetores |
| Indicações e moções (`D:\git\radar-vereadores-niteroi\data\documentos\{indicacao,mocao}\*.json`) | 32.242 + 15.016 | **não**. Mesmo com `arquivos` no detalhe de autoria múltipla, ficam fora da fila de textos | **só a ementa mascarada** (palavras + vetores) |

**Referência do levantamento local:**
- 6.006 arquivos únicos, com 3.046 MB e cerca de 41 MB de texto.
- Formatos: 3.577 docx, 579 doc, 1.449 PDFs com texto, 338 PDFs escaneados, 47 imagens e 14 zip/outros.
- Caches atuais em `C:\Users\Marquinho\AppData\Local\Temp\Claude\inteiro\` e `C:\Users\Marquinho\AppData\Local\Temp\Claude\atas\`, migrados na Phase 0.1.

### 0.3 Decisões aprovadas e ajustes da revisão adversarial

| Decisão | Valor |
|---|---|
| Backend | Cloudflare Workers Paid com **R2**, **D1** (tabelas e FTS5), **Vectorize** (`bge-m3`, cosseno) e **Worker**. O Worker é só leitura para o público; a única escrita é a do cron na tabela `verificacoes` |
| Fonte da verdade | Git: textos em `dados-textos`; manifesto e hashes em `main` |
| **Máscara LGPD**: o humano pediu para mascarar só dados de não vereadores e não suplentes | **CPF e RG são mascarados sempre, de qualquer pessoa.** Ajuste da revisão, achado 1: não dá para atribuir um CPF a um vereador sem publicar um hash que se reverte por força bruta, e CPF de político não serve à fiscalização. **Telefone e e-mail** são mascarados, exceto: contatos de vereadores e suplentes declarados em fonte oficial HTTPS (`contatos` em `D:\git\radar-vereadores-niteroi\config\perfis.json`), telefones institucionais com fonte (`D:\git\radar-vereadores-niteroi\config\backend.json` → `contatos_institucionais`) e os domínios `@camaraniteroi.rj.gov.br` e `@niteroi.rj.gov.br` |
| **Originais** | **Bucket R2 privado** `radar-niteroi-arquivos`, sem trava de retenção. Ajuste da revisão, achado 3. O Worker serve os originais em `GET /api/original/:sha256`, com `Content-Disposition: attachment`, `X-Robots-Tag: noindex`, `X-Content-Type-Options: nosniff` e `Content-Security-Policy: sandbox`, e respeita `D:\git\radar-vereadores-niteroi\config\remocoes.json`, que é consultado no D1 **antes** da Cache API. As exportações vão para o bucket separado `radar-niteroi-exportacoes`, **também sem trava de retenção**: a integridade é provada pelo `SHA256SUMS` e pela atestação do GitHub, não pela trava, para que a remoção também alcance exportações antigas |
| Remoção (art. 18 da LGPD) | `D:\git\radar-vereadores-niteroi\config\remocoes.json`, com fonte e motivo, validado, e chave `<origem>:<id>` mais `sha256`. Expurgo em textos, D1, Vectorize, R2 de originais e exportações, inclusive as antigas, que são regravadas sem o item. Procedimento de reescrita da `dados-textos` documentado |
| Confirmação pendente | A máscara de CPF e RG de **todos**, inclusive vereadores, é mais restritiva que o pedido original. O humano confirma no checkpoint T0.2.2; enquanto isso, vale a regra mais restritiva |
| OCR | Todo local na carga inicial. Incremental no GitHub Actions |
| Cron | Híbrido. O GitHub Actions processa, com registros públicos. O Worker cron verifica hashes baixando os objetos |
| IA de texto | `deepseek-v4.1-flash`. A IA **classifica cada documento** num rótulo; o **código conta**. A amostra de 10 pessoas passa por revisão humana antes de publicar |
| Endereço da API no site | Constante versionada em `D:\git\radar-vereadores-niteroi\config\backend.json` → `api_url`, sem variável de ambiente. Preserva "mesma entrada, mesmos bytes" |
| Privacidade da busca | `observability.enabled: false`, sem Logpush e sem registro da consulta nem do IP. A metodologia avisa que a borda do Cloudflare processa a URL |
| Isolamento | Recursos `radar-niteroi-*` separados em staging e produção, com credenciais de escopo mínimo (seção 0.5) |

### 0.4 Exceções aprovadas às regras de `D:\git\radar-vereadores-niteroi\AGENTS.md`

1. **Ferramentas externas por subprocess, sem dependência Python nova:**
   - `pdftotext` e `pdftoppm` (poppler);
   - `tesseract` 5 com o idioma `por`;
   - `npx wrangler` (`d1 migrations apply` e `d1 execute --file`), chamado pelo `coletor.nuvem`.

   O Python segue só com a biblioteca padrão.
2. **Subprojeto TypeScript** em `D:\git\radar-vereadores-niteroi\worker\`, com `package.json` próprio. Dependências de desenvolvimento com versões fixadas: `wrangler`, `typescript`, `vitest`, `@cloudflare/vitest-pool-workers`, `@cloudflare/workers-types` e `@vitest/coverage-istanbul`.
3. **Formatos de dados novos:**
   - chave `arquivos` nos registros de PLs e documentos;
   - manifesto `D:\git\radar-vereadores-niteroi\data\textos\manifesto-<ano>.json`;
   - `D:\git\radar-vereadores-niteroi\data\temas_ia.json`;
   - `D:\git\radar-vereadores-niteroi\config\backend.json` e `D:\git\radar-vereadores-niteroi\config\remocoes.json`;
   - campo `contatos` em `D:\git\radar-vereadores-niteroi\config\perfis.json`.

### 0.5 Isolamento no Cloudflare

A conta tem outros projetos: `moltbot-data`, `open-auri-media*`, `condominio-db`, `lucas-predictor-db`, `condominio-docs`, `itbi-nacional-rag` e `ncm-embeddings`. Os recursos deste projeto:

| Recurso | Produção | Staging |
|---|---|---|
| R2 (originais) | `radar-niteroi-arquivos` (privado) | `radar-niteroi-arquivos-staging` (privado) |
| R2 (exportações) | `radar-niteroi-exportacoes` (leitura pública, sem trava) | `radar-niteroi-exportacoes-staging` (privado) |
| D1 | `radar-niteroi` | `radar-niteroi-staging` |
| Vectorize | `radar-niteroi-trechos` | `radar-niteroi-trechos-staging` |
| Worker | `radar-niteroi-api` | `radar-niteroi-api-staging` |

**Credenciais:**
- `CLOUDFLARE_API_TOKEN`, com escopo de conta: D1:Edit, Vectorize:Edit, Workers AI:Read, Workers Scripts:Edit e Account Analytics:Read.
- Chaves S3 do R2 (`R2_ACCESS_KEY_ID`/`R2_SECRET_ACCESS_KEY`), restritas aos quatro buckets.

**Limitação documentada:** as permissões de D1, Vectorize e Workers valem para a conta toda. O isolamento total exigiria uma conta separada, que só o humano pode criar.

### 0.6 Fora do escopo

- Inteiro teor de indicações e moções.
- Respostas geradas por IA na busca.
- Migrar a hospedagem do site para Workers Static Assets.
- Reclassificar os PLs com o inteiro teor, porque mudaria `VERSAO_PROMPT` e tem custo.

---

## 1. Diretivas de execução (obrigatórias)

### 1.1 Execução contínua

- **Execute o plano inteiro, wave a wave e phase a phase, sem interrupções.**
- **Só pare e pergunte ao humano** quando houver:
  - (a) **ambiguidade** que muda o resultado e que este plano não resolve;
  - (b) **problema crítico**: segredo exposto, risco à neutralidade ou à LGPD, perda de dados ou cobrança projetada acima de US$ 10/mês;
  - (c) **bloqueio real**: ferramenta impossível de instalar sem alternativa; credencial que só o humano pode criar; SISCAM ou Cloudflare indisponível por mais de 2 horas;
  - (d) **checkpoints humanos combinados:**
    - credenciais e alerta de cobrança, que bloqueiam só o pré-voo da Phase 3.1;
    - amostra de temas, na T4.3.5.
- Fora desses casos, decida pelo padrão deste plano e siga. Registre a decisão no relatório da phase, em `D:\git\radar-vereadores-niteroi\docs\plans\relatorios\2026-10-27-inteiro-teor\<phase>.md`.
- **Solução definitiva sempre.** Nada de stub, nada de "TODO depois", nada de "se não houver, registrar e seguir" quando existir solução. Cada phase entrega o sub-objetivo completo, testado e integrado.

### 1.2 Ciclo obrigatório de cada phase

1. **Pré-voo** da phase. Tudo verde, ou corrigir antes de editar qualquer arquivo.
2. **Tasks e subtasks** na ordem e com o paralelismo indicados.
3. **Novos testes** da phase, cobrindo as funções novas e os casos-limite listados.
4. **Suíte afetada**, depois a suíte completa:
   - `pwsh -NoProfile -File D:\git\radar-vereadores-niteroi\scripts\testes.ps1`, que roda em paralelo o mesmo que `python -m unittest discover -s tests -t .` e é versionado na T0.1.4;
   - `node --test "tests/js/**/*.test.js"`;
   - `python -m coletor.validar`;
   - `python -m coletor.gerar_site`;
   - em `D:\git\radar-vereadores-niteroi\worker`, rodar `npm test` quando a phase tocar o Worker.
5. **Revisão de QA sênior** da phase (`role=reviewer`): defeitos, regressões, segurança, LGPD, neutralidade, desempenho e testes fracos.
6. **Corrigir todos os achados.** Achado recusado exige justificativa escrita no relatório. Depois, repetir o passo 4 e fazer uma revisão curta só dos pontos corrigidos.
7. **Commit e push** na branch de integração, e atualização do relatório.

Ao fim de **cada wave**: revisão de QA da integração entre as phases e correção dos achados, antes de abrir a próxima wave.

### 1.3 Commits frequentes

- **Quando:** commit a cada subtask verde, ou no máximo a cada task. Push na branch `inteiro-teor-busca` ao fim de cada task.
- **Mensagens:** em português, no imperativo ou na 3ª pessoa ("Inclui…", "Extrai…"). Sem conventional commits, sem trailers de coautoria de IA e sem "Generated with".
- **Separação:** não misture código com `D:\git\radar-vereadores-niteroi\data\` no mesmo commit.
- **PR:** um PR em rascunho para `main` é aberto na Phase 0.1, só para o CI rodar. **Merge só na Wave 5**, com CI verde.
- **Branch `dados-textos`:** recebe commits só do `coletor.textos`, depois da barreira de PII da T2.1.1 S6.

### 1.4 Paralelismo seguro

- **Paralelize** phases e tasks independentes no mesmo bloco de dispatch, sempre que a matriz da seção 1.5 permitir.
- **Um dono por arquivo de cada vez:**
  - ninguém escreve num arquivo que outro agente está editando;
  - ninguém lê um arquivo em edição por outro;
  - espere o dono terminar e o orquestrador registrar a liberação.
- **Arquivos compartilhados são do orquestrador** (lista na seção 1.5). Os agentes entregam o trecho a incluir no relatório, e o orquestrador aplica em sequência.
- **Worktrees para phases paralelas** com vários arquivos: `D:\git\radar-vereadores-niteroi-wt\<phase>`, criados a partir da branch de integração.
  - O orquestrador integra um worktree por vez: rebase, suíte completa, e só então a próxima integração.
  - Mudanças do orquestrador em arquivos compartilhados que um worktree precisa para testar, como `D:\git\radar-vereadores-niteroi\coletor\validar.py`, são aplicadas **dentro daquele worktree** depois que o implementer termina e antes dos testes. Na integração, o orquestrador resolve conflitos nesses arquivos.
- **Nunca em paralelo**, porque gravam no mesmo destino:
  - `python -m coletor.gerar_site`, que recria `D:\git\radar-vereadores-niteroi\site\`;
  - `python -m coletor.textos`, que grava no worktree `dados-textos`;
  - `python -m coletor.nuvem`;
  - `npx wrangler deploy`.
- **Commit, push e deploy são só do orquestrador.** Delegados nunca fazem nenhum dos três.

### 1.5 Matriz de posse de arquivos

**Do orquestrador o tempo todo:**
- `D:\git\radar-vereadores-niteroi\AGENTS.md`, `D:\git\radar-vereadores-niteroi\README.md` e `D:\git\radar-vereadores-niteroi\docs\backend.md`;
- `D:\git\radar-vereadores-niteroi\coletor\validar.py` e `D:\git\radar-vereadores-niteroi\tests\test_validar.py`;
- `D:\git\radar-vereadores-niteroi\coletor\gerar_site.py`, `D:\git\radar-vereadores-niteroi\coletor\site\modelo.py` e `D:\git\radar-vereadores-niteroi\coletor\site\paginas.py`;
- `D:\git\radar-vereadores-niteroi\tests\test_gerar_site.py`;
- `D:\git\radar-vereadores-niteroi\config\*.json`;
- `D:\git\radar-vereadores-niteroi\.github\workflows\*.yml`;
- `D:\git\radar-vereadores-niteroi\.gitignore` e `D:\git\radar-vereadores-niteroi\.gitattributes`;
- `D:\git\radar-vereadores-niteroi\scripts\`;
- `D:\git\radar-vereadores-niteroi\tests\test_scripts.py` (Phase 0.1) e `D:\git\radar-vereadores-niteroi\tests\test_backend_config.py` (Phase 0.2).

| Wave | Phase | Dono exclusivo de |
|---|---|---|
| 1 | 1.1 | `D:\git\radar-vereadores-niteroi\coletor\siscam.py`<br>`D:\git\radar-vereadores-niteroi\coletor\documentos.py`<br>`D:\git\radar-vereadores-niteroi\coletor\arquivos_siscam.py` (novo)<br>`D:\git\radar-vereadores-niteroi\tests\test_arquivos_siscam.py` (novo)<br>`D:\git\radar-vereadores-niteroi\tests\test_siscam*.py`<br>`D:\git\radar-vereadores-niteroi\tests\test_documentos*.py`<br>`D:\git\radar-vereadores-niteroi\tests\fixtures\siscam\` (só novas fixtures) |
| 1 | 1.2 | `D:\git\radar-vereadores-niteroi\coletor\extratores\` (novo)<br>`D:\git\radar-vereadores-niteroi\coletor\mascara.py`<br>`D:\git\radar-vereadores-niteroi\coletor\trechos.py`<br>`D:\git\radar-vereadores-niteroi\tests\test_extratores*.py`<br>`D:\git\radar-vereadores-niteroi\tests\test_mascara.py`<br>`D:\git\radar-vereadores-niteroi\tests\test_trechos.py`<br>`D:\git\radar-vereadores-niteroi\tests\fixtures\textos\` (novo) |
| 1 | 1.3 | orquestrador:<br>`D:\git\radar-vereadores-niteroi\docs\contratos\textos.md`<br>`D:\git\radar-vereadores-niteroi\tests\fixtures\contratos\`<br>`D:\git\radar-vereadores-niteroi\tests\test_contratos.py`<br>`D:\git\radar-vereadores-niteroi\coletor\remocoes.py` (leitura e chaves)<br>`D:\git\radar-vereadores-niteroi\tests\test_remocoes.py` |
| 2 | 2.1 | `D:\git\radar-vereadores-niteroi\coletor\textos.py`<br>`D:\git\radar-vereadores-niteroi\tests\test_textos.py`<br>worktree `D:\git\radar-vereadores-niteroi-textos` |
| 2 | 2.2 | `D:\git\radar-vereadores-niteroi\coletor\nuvem\` (novo)<br>`D:\git\radar-vereadores-niteroi\worker\migrations\`<br>`D:\git\radar-vereadores-niteroi\tests\test_nuvem*.py` |
| 3 | 3.1 | execuções e `D:\git\radar-vereadores-niteroi\tests\test_integracao_rest.py` |
| 3 | 3.2 | `D:\git\radar-vereadores-niteroi\worker\` inteiro, exceto `D:\git\radar-vereadores-niteroi\worker\migrations\` (só leitura) |
| 4 | 4.1 | `D:\git\radar-vereadores-niteroi\coletor\site\pagina_busca.py`<br>`D:\git\radar-vereadores-niteroi\site_src\busca.js`<br>`D:\git\radar-vereadores-niteroi\site_src\busca.css`<br>`D:\git\radar-vereadores-niteroi\tests\test_pagina_busca.py`<br>`D:\git\radar-vereadores-niteroi\tests\js\busca.test.js` |
| 4 | 4.2 | `D:\git\radar-vereadores-niteroi\worker\` inteiro, incluindo `D:\git\radar-vereadores-niteroi\worker\migrations\`<br>`D:\git\radar-vereadores-niteroi\coletor\remocoes.py` (expurgo)<br>`D:\git\radar-vereadores-niteroi\coletor\textos.py`<br>`D:\git\radar-vereadores-niteroi\coletor\nuvem\`<br>`D:\git\radar-vereadores-niteroi\tests\test_remocoes.py`<br>`D:\git\radar-vereadores-niteroi\tests\test_textos.py`<br>`D:\git\radar-vereadores-niteroi\tests\test_nuvem*.py`<br>`D:\git\radar-vereadores-niteroi\tests\test_workflows.py` |
| 4 | 4.3 | `D:\git\radar-vereadores-niteroi\coletor\temas.py`<br>`D:\git\radar-vereadores-niteroi\coletor\ia.py` (novo, cliente extraído)<br>`D:\git\radar-vereadores-niteroi\coletor\classificar.py`<br>`D:\git\radar-vereadores-niteroi\coletor\site\temas_html.py` (novo)<br>`D:\git\radar-vereadores-niteroi\tests\test_temas.py`<br>`D:\git\radar-vereadores-niteroi\tests\test_classificar*.py`<br>`D:\git\radar-vereadores-niteroi\tests\test_ia.py` |

### 1.6 Anotações do model-router

- **Linha de rota:** cada task e cada revisão traz `router:` com `role`, `class`, `risk`, `scope` e `needs`. Essa linha vira a linha de rota do dispatch.
- **`[tier:heavy]`:** só onde estiver escrito no plano. Nesses casos, acrescente `tier=heavy pin` à rota.
- **Dispatch de implementação:** leva `[acceptance]` com `check: testsPass` e os critérios da task.
- **Testes, validação, geração, carga e deploy:** executados pelo orquestrador, porque os delegados não têm `router_run` para Python neste repositório.
- **Contexto pesado:** reunido antes por `role=explorer` e colado no prompt de quem implementa.
- **Consultas de documentação do Cloudflare:** `router: role=researcher class=search risk=low scope=single needs=web`. O resultado é colado no despacho seguinte, porque o researcher não lê arquivos locais.

---

## 2. Pré-voo global, antes da Wave 0

- [ ] `git -C D:\git\radar-vereadores-niteroi status` limpo, com `main` igual a `origin/main`.
- [ ] Suíte completa verde no ponto de partida, com as contagens registradas: Python ≥ 995 e JS ≥ 151.
- [ ] `npx wrangler whoami` lista `Marco Jardim`.
- [ ] Espaço livre em `D:\` de pelo menos 10 GB.
- [ ] `OPENCODE_API_KEY` presente, sem imprimir o valor. Se faltar, só bloqueia a Phase 4.3: pedir ao humano ao chegar lá.

---

## Wave 0: Ambiente

### Phase 0.1: Ferramentas locais, cache, scripts e branch

**Pré-voo**
- [ ] Pré-voo global verde.
- [ ] `winget --version` responde.
- [ ] `D:\git\radar-vereadores-niteroi\.gitignore` e `D:\git\radar-vereadores-niteroi\.gitattributes` lidos.

**Tasks**

- **T0.1.1 Branch, relatório e PR em rascunho.** `router: role=general class=mechanical risk=low scope=single needs=shell`
  - S1. `git switch -c inteiro-teor-busca`.
  - S2. Criar a pasta `D:\git\radar-vereadores-niteroi\docs\plans\relatorios\2026-10-27-inteiro-teor\`.
  - S3. Push e `gh pr create --draft`.
- **T0.1.2 Ferramentas.** `router: role=general class=other risk=medium scope=single needs=shell,external_dir`
  - S1. Instalar poppler (`pdftotext`, `pdftoppm`) e Tesseract 5 com `por.traineddata`:
    - primeiro winget (`UB-Mannheim.TesseractOCR` e um pacote de poppler);
    - se não houver, scoop;
    - se não houver, conda.
  - S2. Registrar as versões exatas em `D:\git\radar-vereadores-niteroi\docs\backend.md`.
  - S3. Smoke test com 3 PDFs com texto, 3 escaneados e 1 JPG do cache.
  - Sem nenhuma instalação possível: parar (1.1-c).
- **T0.1.3 Cache estável.** `router: role=general class=mechanical risk=low scope=single needs=shell,external_dir`
  - S1. Mover os caches para `D:\radar-niteroi-cache\`, com as subpastas `html\`, `arquivos\` (nome = SHA-256), `atas\`, `ocr\` e `exportacoes\`.
  - S2. Variável `RADAR_CACHE`: padrão `D:\radar-niteroi-cache` no Windows e `~/.cache/radar-niteroi` em POSIX.
- **T0.1.4 Scripts e higiene do repositório** (orquestrador). `router: role=general class=mechanical risk=low scope=multi needs=edit`
  - S1. Versionar `D:\git\radar-vereadores-niteroi\scripts\testes.ps1` a partir de `C:\Users\Marquinho\AppData\Local\Temp\Claude\qa\testes.ps1`, com caminhos relativos ao repositório.
  - S2. Em `D:\git\radar-vereadores-niteroi\.gitattributes`, LF para `worker/**` e `scripts/**`.
  - S3. Em `D:\git\radar-vereadores-niteroi\.gitignore`, incluir `/worker/node_modules/`, `/worker/.wrangler/` e `/worker/coverage/`.

**Novos testes:** `D:\git\radar-vereadores-niteroi\tests\test_scripts.py`. O script existe, roda os mesmos módulos do `unittest discover` e falha quando um módulo falha (simulado).

**Critérios de aceitação**
- `pdftotext -v`, `pdftoppm -v` e `tesseract --list-langs` (com `por`) respondem.
- O cache tem as mesmas contagens da origem: 5.041 HTMLs, 6.006 arquivos e as 584 atas.
- O PR em rascunho existe e o CI dele está verde.

**DoD:** relatório com versões e contagens; scripts e higiene commitados; push feito.

**QA sênior:** `router: role=reviewer class=review risk=low scope=multi`. Reprodutibilidade, cache fora do Git, script de testes equivalente ao do CI.

### Phase 0.2: Ambiente Cloudflare isolado

**Pré-voo**
- [ ] `npx wrangler r2 bucket list`, `npx wrangler d1 list` e `npx wrangler vectorize list` respondem, o que confirma o Workers Paid.
- [ ] Nenhum `radar-niteroi-*` existente fora do projeto.

**Tasks**

- **T0.2.1 Recursos.** `router: role=general class=other risk=medium scope=single needs=shell,network`. Rodar sempre com `CLOUDFLARE_ACCOUNT_ID=7b60055a9f153a4a8441ff519e1a208f`.
  - S1. Criar os quatro buckets da seção 0.5. Todos privados, exceto `radar-niteroi-exportacoes`, com leitura pública por domínio personalizado. Se o projeto não tiver domínio, usar `r2.dev` apenas para as exportações, documentando o limite de taxa.
  - S2. **Sem trava de retenção em nenhum bucket**, para que a remoção alcance todo o conteúdo. A imutabilidade das exportações vem de outro lado: chaves versionadas, `If-None-Match: *` em cada escrita, `SHA256SUMS` e atestação. Antes, o `role=researcher` (`router: role=researcher class=search risk=low scope=single needs=web`) confirma como publicar o bucket por domínio próprio e quais são os limites do `r2.dev`.
  - S3. Criar os bancos D1 `radar-niteroi` e `radar-niteroi-staging`.
  - S4. Criar os índices Vectorize:
    - `npx wrangler vectorize create radar-niteroi-trechos --dimensions=1024 --metric=cosine`, e o equivalente `-staging`;
    - índices de metadados `tipo` (string), `ano` (number) e `legislatura` (string). O filtro por autor fica no D1 (achado 15).
- **T0.2.2 Credenciais e alerta de cobrança (checkpoint humano 1.1-d).** `router: role=general class=other risk=high scope=single`
  - S1. Documentar em `D:\git\radar-vereadores-niteroi\docs\backend.md` as permissões exatas da seção 0.5 e o alerta de cobrança: notificação de uso no painel, com limite de US$ 10 acima da assinatura.
  - S2. **Pedir ao humano**, sem bloquear as Waves 1 e 2:
    - criar o token e as chaves;
    - gravar no GitHub os secrets `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `R2_ACCESS_KEY_ID` e `R2_SECRET_ACCESS_KEY`;
    - entregar a cópia local como variáveis de ambiente, nunca em arquivo;
    - criar o alerta de cobrança;
    - confirmar a regra de mascarar CPF e RG de todos (seção 0.3).
  - O pedido bloqueia só o pré-voo da Phase 3.1.
- **T0.2.3 Configuração do Worker e do backend.** `router: role=implementer class=implement risk=low scope=multi needs=edit`
  - S1. Criar `D:\git\radar-vereadores-niteroi\worker\wrangler.jsonc` com os ids reais, ambientes `staging` e `production`, e os bindings:
    - `DB`, `VETORES`, `ARQUIVOS` e `EXPORTACOES`;
    - `AI`;
    - `LIMITE` (Rate Limiting) e `METRICAS` (Analytics Engine);
    - `version_metadata` (`CF_VERSION_METADATA`).

    Configurar também `observability.enabled: false`, `limits.cpu_ms` e `migrations_dir: "migrations"`.
  - S2. O orquestrador cria `D:\git\radar-vereadores-niteroi\config\backend.json`, com `api_url` (`https://radar-niteroi-api.<subdominio>.workers.dev`), `origens_cors` (`https://marco-jardim.github.io`) e `contatos_institucionais` (vazio).
  - S3. O orquestrador cria `D:\git\radar-vereadores-niteroi\config\remocoes.json` (`{"remocoes": []}`) e as validações dos dois arquivos em `D:\git\radar-vereadores-niteroi\coletor\validar.py`.

**Novos testes**
- `D:\git\radar-vereadores-niteroi\tests\test_backend_config.py`:
  - o `wrangler.jsonc` tem `observability.enabled: false`, nenhum `logpush`, o binding `version_metadata` e `limits.cpu_ms`;
  - os nomes de recursos têm o prefixo `radar-niteroi`.
- `D:\git\radar-vereadores-niteroi\tests\test_validar.py` (orquestrador):
  - `backend.json` com URL HTTPS e origens válidas;
  - `remocoes.json` com campos, fonte HTTPS e motivo.
- **Smoke remoto:**
  - `npx wrangler d1 execute radar-niteroi-staging --remote --command "select 1"`;
  - `npx wrangler vectorize info` de cada índice;
  - envio e leitura de um objeto em `radar-niteroi-arquivos-staging`, apagado em seguida.

**Critérios de aceitação:** dez recursos criados e registrados; os buckets de originais recusam leitura anônima (teste com `curl`, esperando 403 ou 404); só `radar-niteroi-exportacoes` aceita leitura pública; os testes passam.

**DoD:** `D:\git\radar-vereadores-niteroi\docs\backend.md` com recursos, ids, permissões, limitação de isolamento, procedimento de recriação e de rollback (`npx wrangler rollback`), e a reconstrução por `python -m coletor.nuvem --reconstruir`. Commit e push.

**QA sênior:** `router: role=reviewer class=review risk=medium scope=multi`. Nenhum segredo versionado; nomes isolados; buckets privados; escopo mínimo.

**QA da Wave 0:** `router: role=reviewer class=review risk=medium scope=repo`. Reprodutibilidade do ambiente e das ferramentas.

---

## Wave 1: Fundamentos (Phases 1.1 e 1.2 em paralelo, em worktrees; Phase 1.3 depois das duas)

### Phase 1.1: Lista de arquivos de cada documento na coleta

**Pré-voo**
- [ ] QA da Wave 0 fechada.
- [ ] Worktree `D:\git\radar-vereadores-niteroi-wt\1.1` criado.
- [ ] As 7 fixtures reais com `trArquivos` em `D:\git\radar-vereadores-niteroi\tests\fixtures\siscam\` foram lidas, incluindo `detalhe_substitutivo_266596.html`, `detalhe_pl_127858.html`, `detalhe_resolucao_289947.html` e `detalhe_pdl_290379.html`.

**Tasks**

- **T1.1.1 Parser.** `router: role=implementer class=implement risk=medium scope=multi needs=edit`
  - S1. `D:\git\radar-vereadores-niteroi\coletor\arquivos_siscam.py`: `extrair_arquivos(html) -> list[dict]`, que lê `tr#trArquivos`/`table#arquivos_gvListagem`. Cada item tem:
    - `id: int`;
    - `descricao: str`, com `&nbsp;` virando vazio e entidades decodificadas;
    - `versao: str` (por exemplo "Anexos" ou "Arquivo em PDF");
    - `data: 'AAAA-MM-DD' | None`, lida pela regex `(\d{1,2})/(\d{1,2})/(\d{4})`. A ordem dia/mês é confirmada contra a "Data do Documento" das fixtures;
    - `icone: str`.
  - S2. Linha sem link é ignorada. Rótulo da seção presente sem a tabela vale como "layout alterado": o detalhe fica pendente, sem substituir o anterior.
  - S3. Duas novas fixtures reais: "Nenhum Registro" e vários arquivos com versões distintas. Os bytes são preservados.
- **T1.1.2 Coletores.** `router: role=implementer class=implement risk=high scope=multi needs=edit`
  - S1. Em `D:\git\radar-vereadores-niteroi\coletor\siscam.py`, gravar `arquivos` no PL e em cada substitutivo.
  - S2. Em `D:\git\radar-vereadores-niteroi\coletor\documentos.py`:
    - gravar `arquivos` nos tipos que têm detalhe;
    - **acrescentar `arquivos` a `CAMPOS_DETALHE`**, para que `herdar_detalhe` preserve a chave na relistagem;
    - indicações e moções com detalhe também guardam `arquivos`. A exclusão do escopo é feita na fila de textos.
  - S3. Uma lista antes preenchida que venha vazia mantém a anterior, com aviso.
- **T1.1.3 Carga dos `arquivos` a partir do cache.** `router: role=implementer class=implement risk=medium scope=multi needs=edit`
  - S1. Opção `--arquivos-do-cache DIR` em `coletor.siscam` e `coletor.documentos`. Lê `D:\radar-niteroi-cache\html\<id>.html` e preenche `arquivos`, gravando por `D:\git\radar-vereadores-niteroi\coletor\arquivos.py` (`salvar_lista`).
  - S2. Id sem HTML no cache:
    - **Documentos:** recebe `detalhe_pendente: true` normal, atendido pela próxima coleta dentro de `--max-detalhes`.
    - **PLs** (o coletor não tem `detalhe_pendente`): em `D:\git\radar-vereadores-niteroi\coletor\siscam.py`, uma nova regra `precisa_arquivos(anterior)` (registro sem a chave `arquivos`) entra no limite de `--max-detalhes`, como faz `precisa_substitutivos`.
- **T1.1.4 Validação.** O orquestrador aplica no worktree 1.1 antes dos testes. `router: role=general class=implement risk=medium scope=single needs=edit`
  - Em `D:\git\radar-vereadores-niteroi\coletor\validar.py`:
    - `arquivos` é opcional;
    - campos sem extras;
    - ids inteiros e únicos por documento;
    - `data` ISO ou `null`;
    - formato byte a byte inalterado.
  - **Arquivo sem entrada no manifesto não é erro.** O validador só confere as entradas que existem e imprime a contagem de pendentes (achado 2).

**Novos testes:** `D:\git\radar-vereadores-niteroi\tests\test_arquivos_siscam.py`, além das atualizações em `D:\git\radar-vereadores-niteroi\tests\test_siscam*.py`, `D:\git\radar-vereadores-niteroi\tests\test_documentos*.py` e `D:\git\radar-vereadores-niteroi\tests\test_validar.py`.
- As 7 fixtures existentes mais as 2 novas.
- Datas `14/3/2024`, `4/12/2025` e `10/12/2025`.
- Entidades e `&nbsp;`.
- Link sem id; layout alterado.
- Carga do cache idempotente, com os mesmos bytes.
- Lista vazia não apaga a anterior.
- **Relistagem preserva `arquivos`.**
- PL sem `arquivos` entra na fila de detalhe dentro de `--max-detalhes`; PL com `arquivos` não entra.
- Substitutivo com arquivos próprios.
- O validador recusa id repetido e campo extra.
- **Registro com `arquivos` sem manifesto passa no `validar_tudo`.**

**Critérios de aceitação:** depois da carga do cache, ≥ 99% dos PLs, requerimentos, PDLs e resoluções com `arquivos` não vazio (referência: 2.046 de 2.055 PLs); `python -m coletor.validar` verde; crescimento dos JSONs de `D:\git\radar-vereadores-niteroi\data\` ≤ 15%; suíte verde.

**DoD:** código, testes e fixtures num commit; `D:\git\radar-vereadores-niteroi\data\` em commit separado, só com `arquivos`; relatório.

**QA sênior:** `router: role=reviewer class=review risk=medium scope=multi`. Regressões nos coletores, herança na relistagem, formato de `D:\git\radar-vereadores-niteroi\data\`, tamanho.

### Phase 1.2: Extratores, máscara e trechos

**Pré-voo**
- [ ] Worktree `D:\git\radar-vereadores-niteroi-wt\1.2` criado.
- [ ] Fixtures em `D:\git\radar-vereadores-niteroi\tests\fixtures\textos\`, com até 50 KB cada. São **sintéticas, ou documentos públicos já mascarados e sem dados de terceiros** (achado 41), com a origem em `D:\git\radar-vereadores-niteroi\tests\fixtures\textos\FONTES.md`. Lista:
  - docx simples;
  - docx com tabela, cabeçalho e rodapé;
  - doc Word 97 curto;
  - doc fragmentado, com peças cp1252 e UTF-16 misturadas;
  - doc com MiniFAT;
  - RTF;
  - HTML;
  - PDF com texto;
  - PDF misto (uma página com texto e uma escaneada);
  - PDF escaneado de uma página;
  - JPG;
  - zip contendo docx e PDF.

**Tasks**

- **T1.2.1 Pacote `D:\git\radar-vereadores-niteroi\coletor\extratores\`.** `router: role=implementer class=implement risk=high scope=multi needs=edit [tier:heavy]`
  - S1. `detectar.py`: identifica o formato pelos *magic bytes*.
  - S2. `docx.py`: corpo, cabeçalhos, rodapés, notas e tabelas linha a linha. Usa `zipfile` e `xml.etree`.
  - S3. `cfb.py`: leitor do formato OLE Compound File (setores, FAT, DIFAT, MiniFAT e diretório), com limites:
    - detecção de ciclo em cadeia;
    - número máximo de setores;
    - tamanho declarado ≤ o tamanho do arquivo.
  - S4. `doc.py`: Word 97–2003 pelo FIB e pela *piece table* (CLX/PlcPcd) do stream `0Table`/`1Table`.
    - Peças compactadas em cp1252 e peças Unicode em UTF-16LE.
    - Remove campos e caracteres de controle.
    - **Proibido decodificar o binário inteiro.**
  - S5. `rtf.py` e `html.py`: tiram controles e tags com `html.parser` e decodificam entidades.
  - S6. `pdf.py`: `pdftotext -layout -enc UTF-8` por subprocess, com os argumentos em lista, sem shell e com timeout. Classifica **por página**: menos de 100 caracteres úteis marca a página como escaneada. Assim PDFs mistos recebem OCR só nas páginas escaneadas.
  - S7. `ocr.py`: `pdftoppm -r 300 -gray -f N -l N` seguido de `tesseract - - -l por --psm 6 tsv`, página a página. Calcula a confiança média por página. Imagens JPG e PNG vão direto ao tesseract.
  - S8. `zip.py`: extrai os membros com `zipfile` e aplica `extrair` a cada um, recursivamente até 2 níveis, com limite de tamanho descompactado de 100 MB (proteção contra *zip bomb*). O texto final é a concatenação, com o cabeçalho `=== <nome do membro> ===`.
  - S9. `__init__.py`: `extrair(bytes, ocr: bool) -> Resultado`, com:
    - `formato`, `texto`, `extrator`, `versao_extrator`, `paginas`;
    - `paginas_ocr`, `confianca`;
    - `status` ∈ {`ok`, `ok_ocr`, `ocr_baixa_confianca`, `escaneado_sem_ocr`, `pendente_ferramenta`, `vazio_legitimo`, `erro_formato`}.
- **T1.2.2 Máscara LGPD.** `router: role=implementer class=implement risk=high scope=single needs=edit`
  - S1. Em `D:\git\radar-vereadores-niteroi\coletor\mascara.py`, mascarar **sempre**:
    - CPF, com e sem pontuação, só quando o dígito verificador é válido;
    - RG, quando houver o rótulo "RG", "identidade" ou "carteira de identidade" a até 20 caracteres.
  - S2. Telefones brasileiros (fixos, celulares, com DDD, com +55) e e-mails são mascarados, **exceto** os valores do conjunto `liberados(config)`, que reúne:
    - os `contatos` de vereadores e suplentes em `D:\git\radar-vereadores-niteroi\config\perfis.json`, com fonte HTTPS oficial;
    - os `contatos_institucionais` de `D:\git\radar-vereadores-niteroi\config\backend.json`;
    - os domínios `@camaraniteroi.rj.gov.br` e `@niteroi.rj.gov.br`.
  - S3. Substituições: `[CPF omitido]`, `[RG omitido]`, `[telefone omitido]` e `[e-mail omitido]`. A função é idempotente e devolve a contagem por tipo.
  - S4. Proteções contra falso positivo, que **não** podem ser mascarados:
    - CEP;
    - CNPJ;
    - processo no padrão CNJ (`NNNNNNN-DD.AAAA.J.TR.OOOO`);
    - número SEI;
    - matrícula funcional ("matrícula nº …");
    - protocolo de 11 dígitos sem DV de CPF válido;
    - valores em R$;
    - datas;
    - "Lei 3.456/2020";
    - "Processo 1234/2024".
  - S5. Um varredor independente, `varrer(texto) -> list[ocorrencia]`, usado como barreira antes de qualquer commit ou carga (T2.1.1 S6 e T2.2.1 S3).
  - S6. O orquestrador acrescenta o campo `contatos` (`[{tipo: telefone|email, valor, fonte}]`) ao validador de `D:\git\radar-vereadores-niteroi\config\perfis.json`.
- **T1.2.3 Trechos.** `router: role=implementer class=implement risk=medium scope=single needs=edit`
  - S1. Em `D:\git\radar-vereadores-niteroi\coletor\trechos.py`, divisão determinística por parágrafo, com alvo de 1.200 caracteres, máximo de 2.000 e sobreposição de 200.
  - S2. Cada trecho é `{id, documento, arquivo, posicao, inicio, fim, sha256}`, com `id = sha1(documento|arquivo|posicao|sha256)[:16]`. **O trecho guarda offsets, não o texto**, que é lido do `.txt` (achado 22).
  - S3. Normalização NFC e de espaços antes de calcular os offsets. Constante `VERSAO_TRECHOS`.
- **T1.2.5 Limpeza de texto antes de salvar e de gerar vetores** (pedido do humano em 27/10/2026). `router: role=implementer class=implement risk=high scope=multi needs=edit`
  - S1. **Novo módulo** `D:\git\radar-vereadores-niteroi\coletor\limpeza.py`, com a constante `VERSAO_LIMPEZA`. É determinístico e só usa a biblioteca padrão. A ordem do pipeline é: extrair, limpar, mascarar, dividir em trechos.
  - S2. **Cabeçalhos e rodapés por documento.** Remove linhas que se repetem no topo ou no fim (até 4 linhas de cada borda) em pelo menos metade das páginas, quando há pelo menos 2 páginas separadas por `\f`. Nos docx, o texto de `header*.xml` e `footer*.xml` sai do corpo salvo e fica só contado no manifesto.
  - S3. **Ruído de página.** Remove:
    - numeração ("Página 1 de 3", "- 2 -", "2/5", número sozinho na linha);
    - linhas só com separadores;
    - linhas de OCR com menos de 40% de caracteres alfanuméricos ou com menos de 3 caracteres úteis;
    - linhas em branco repetidas.
  - S4. **Clichês do corpus (timbres).** Remove as linhas normalizadas (sem acento, minúsculas, espaços colapsados, dígitos trocados por `#`) que aparecem em pelo menos 2% dos documentos do escopo, ou em 20 documentos ou mais. Exemplos: "camara municipal de niteroi", "gabinete do vereador …", o endereço e o telefone da Câmara, "estado do rio de janeiro".
    - A lista é **gerada** por `python -m coletor.limpeza --gerar-cliches` a partir do texto bruto em cache. Fica versionada em `D:\git\radar-vereadores-niteroi\data\textos\cliches.json` (gravada por `salvar_mapa`, cada linha normalizada com a contagem de documentos), para que qualquer pessoa audite o que foi cortado.
    - A lista **congela** por `VERSAO_LIMPEZA`. O incremental usa a lista congelada. Recalcular exige `--recalcular-cliches`, sobe a versão e reprocessa tudo com `--reprocessar-versao`.
    - **Nunca cortar** linhas que contenham a ementa, "Art.", "§", "Parágrafo", "Inciso", "Justificativa", "Sala das Sessões", nomes de vereadores ou suplentes de `D:\git\radar-vereadores-niteroi\config\vereadores.json`, nem números de lei ou de processo.
  - S5. **Rastro no manifesto.** Cada arquivo registra:
    - `limpeza: {versao, linhas_removidas, por_regra: {cabecalho_rodape, numeracao, ruido_ocr, cliche}}`;
    - `sha256_bruto`, o hash do texto extraído antes da limpeza e da máscara.

    O texto bruto fica só no cache local, que não é público. O original no R2 continua sendo a prova.
  - S6. **Trechos para vetores.** Recebem o texto já limpo. Trechos com menos de 80 caracteres úteis não geram vetor, ficam só na busca por palavras, e a contagem vai para o manifesto.
  - **Testes** (`D:\git\radar-vereadores-niteroi\tests\test_limpeza.py`):
    - cabeçalho repetido em 3 de 4 páginas é cortado; linha igual que aparece em só 1 página é mantida;
    - documento de 1 página não sofre o corte por repetição;
    - numeração nos vários formatos;
    - linha de OCR ruidosa cortada; linha curta legítima ("Art. 1º") mantida;
    - clichê cortado; linha protegida (Art., ementa, nome de vereador, "Lei nº 3.456/2020") mantida mesmo frequente;
    - geração da lista determinística, com mesma entrada dando os mesmos bytes, e limiar exato (2% e 20 documentos);
    - lista congelada usada no incremental;
    - idempotência (limpar duas vezes dá o mesmo resultado);
    - contagens por regra;
    - integração com máscara e trechos;
    - trecho curto sem vetor.
  - **Aceitação:**
    - Na amostra auditada da T2.1.2 S3 (mais 30 documentos com cortes), zero cortes de conteúdo normativo, de justificativa ou de assinatura de vereador.
    - Pelo menos 90% das linhas com timbre da Câmara e dos gabinetes removidas nessa amostra.
    - Redução de tamanho registrada no relatório.
- **T1.2.4 CI com as ferramentas** (orquestrador). Em `D:\git\radar-vereadores-niteroi\.github\workflows\testes.yml`, rodar `apt-get install -y poppler-utils tesseract-ocr tesseract-ocr-por`, para que os testes de PDF e OCR não sejam pulados (achado 25). `router: role=general class=mechanical risk=low scope=single needs=edit`

**Novos testes**
- `D:\git\radar-vereadores-niteroi\tests\test_extratores.py`:
  - todas as fixtures, conferidas por trechos âncora;
  - peça Unicode no meio de cp1252;
  - MiniFAT;
  - CFB com ciclo na FAT, que precisa terminar com `erro_formato` sem travar;
  - CFB truncado;
  - docx sem `document.xml`;
  - PDF corrompido;
  - PDF misto com OCR só na página certa;
  - timeout de subprocess, com executável falso;
  - PATH vazio dando `pendente_ferramenta`;
  - zip aninhado;
  - *zip bomb* recusada;
  - arquivo vazio.
- `D:\git\radar-vereadores-niteroi\tests\test_mascara.py`:
  - CPF com DV válido e inválido;
  - todos os falsos positivos de S4;
  - telefone com (21), +55 e 9 dígitos;
  - e-mail institucional liberado;
  - contato liberado de vereador mantido;
  - CPF de vereador mascarado;
  - idempotência e contagens;
  - `varrer` encontra o que escapou.
- `D:\git\radar-vereadores-niteroi\tests\test_trechos.py`:
  - texto vazio;
  - parágrafo maior que o máximo;
  - determinismo e ids estáveis;
  - sobreposição;
  - offsets que reconstituem o texto (`texto[inicio:fim]`);
  - acentos e NFC.

**Critérios de aceitação**
- Medidos no cache inteiro e registrados no relatório:
  - doc: ≥ 97% `ok`;
  - docx: ≥ 99,5% `ok`;
  - zip: 100% processado;
  - os 338 escaneados identificados;
  - nenhuma saída com sequências de controle.
- 100% dos testes da máscara passam.

**DoD:** pacote, testes e fixtures com origem registrada; `testes.yml` atualizado; commit; relatório com as taxas.

**QA sênior:** `router: role=reviewer class=review risk=high scope=multi`. Robustez do CFB contra malformação, ausência de injeção no subprocess, falsos positivos e negativos da máscara, desempenho num arquivo de 5 MB (≤ 2 s sem OCR).

### Phase 1.3: Contrato congelado de manifesto e trechos (orquestrador)

**Pré-voo:** Phases 1.1 e 1.2 integradas, nessa ordem (1.2 primeiro, depois 1.1), com a suíte completa verde depois de cada integração.

**Tasks**

- **T1.3.1 Contrato.** `router: role=architect class=design risk=medium scope=multi`
  - S1. Escrever `D:\git\radar-vereadores-niteroi\docs\contratos\textos.md`, com:
    - chave do manifesto `<origem>:<id>`, onde a origem é `siscam:<IdArquivo>` ou `sessao:<guid>`;
    - documento `doc:<IdDocumento>` ou `sessao:<IdSessao>`, e `documentos` como lista, porque um arquivo pode servir a vários documentos;
    - o ano do manifesto é o `ano` do registro (não a `data`); nas atas, o ano da sessão;
    - os campos do manifesto, sem `processado_em` mutável. Ver S2;
    - o formato de `textos\` e `trechos\` em `dados-textos`;
    - as tabelas D1 e os metadados do Vectorize;
    - os estados.
  - S2. **Determinismo.** `processado_em` só muda quando a entrada muda (hash do original ou versões). Exportações gzip com `mtime=0`.
  - S3. Fixtures de contrato em `D:\git\radar-vereadores-niteroi\tests\fixtures\contratos\`: manifesto, textos e trechos de 5 documentos.
  - S4. **Remoções.** Chave em `D:\git\radar-vereadores-niteroi\config\remocoes.json`: `{chave: "<origem>:<id>", sha256, motivo, fonte, data}`. Tabela D1 `remocoes(chave, sha256, motivo, data)` na migração `0001`.
  - S5. **Módulo de remoções.** O orquestrador cria `D:\git\radar-vereadores-niteroi\coletor\remocoes.py` com `carregar(raiz) -> dict` e `esta_removido(chave|sha256) -> bool`, mais a validação do `remocoes.json` em `D:\git\radar-vereadores-niteroi\coletor\validar.py`. Essa leitura é usada pelas Phases 2.1 e 2.2; o expurgo é acrescentado na T4.2.4.

**Novos testes:** `D:\git\radar-vereadores-niteroi\tests\test_contratos.py`. As fixtures de contrato satisfazem o validador e o leitor de trechos.

Também `D:\git\radar-vereadores-niteroi\tests\test_remocoes.py`:
- carregamento vazio e com itens;
- busca por chave e por sha;
- validação de campos e de HTTPS.

**Critérios de aceitação:** o contrato cobre todos os campos usados nas Waves 2–4, e as fixtures passam.

**DoD:** contrato e fixtures commitados; relatório.

**QA sênior:** `router: role=reviewer class=review risk=medium scope=multi`. Completude e colisões de chave.

**QA da Wave 1:** `router: role=reviewer class=review risk=high scope=repo`. Lote real de 50 documentos: `arquivos` → `extrair` → máscara → trechos, conferido contra o contrato.

---

## Wave 2: Pipeline e cliente de nuvem (Phases 2.1 e 2.2 em paralelo)

### Phase 2.1: Pipeline `coletor.textos` e carga inicial com OCR local

**Pré-voo**
- [ ] QA da Wave 1 fechada.
- [ ] Ferramentas da Phase 0.1 respondem.
- [ ] Contrato da Phase 1.3 congelado.
- [ ] Branch órfã `dados-textos` criada no worktree `D:\git\radar-vereadores-niteroi-textos`, com `README.md` explicando conteúdo, licença, máscara e remoção.

**Tasks**

- **T2.1.1 Módulo `D:\git\radar-vereadores-niteroi\coletor\textos.py`.** `router: role=implementer class=implement risk=high scope=multi needs=edit [tier:heavy]`
  - S1. **Fila.**
    - Entram os `arquivos` dos registros com `tipo` em {pl, substitutivo, requerimento, pdl, resolucao}, de `D:\git\radar-vereadores-niteroi\data\proposicoes\` e `D:\git\radar-vereadores-niteroi\data\documentos\{requerimento,pdl,resolucao}\`.
    - Entram as atas com `rotulo` em `ROTULOS_ATA`, de `D:\git\radar-vereadores-niteroi\data\sessoes\`.
    - Só os que ainda não estão no manifesto, ou que estão em status reprocessável (`pendente_ferramenta`, ou `escaneado_sem_ocr` com `--ocr`), ou cuja versão mudou com `--reprocessar-versao`.
    - Excluir os itens removidos, por `D:\git\radar-vereadores-niteroi\coletor\remocoes.py` (`esta_removido`).
  - S2. **Download.** Mesmos User-Agent, tentativas e espera de `D:\git\radar-vereadores-niteroi\coletor\siscam.py`. Quatro workers. Cache em `D:\radar-niteroi-cache\arquivos\<sha256>`, ou no caminho de `RADAR_CACHE`.
  - S3. **Processamento**, em duas passadas na carga inicial. Na primeira, extrai o texto bruto para o cache e gera `D:\git\radar-vereadores-niteroi\data\textos\cliches.json`. Na segunda, limpa e grava. Para cada arquivo, nesta ordem:
    1. SHA-256 do original;
    2. `extrair` (com OCR quando `--ocr`); o bruto vai para `D:\radar-niteroi-cache\texto_bruto\<sha256>.txt`;
    3. `limpeza` (T1.2.5), com a lista de clichês congelada;
    4. máscara;
    4. trechos;
    5. gravar `D:\git\radar-vereadores-niteroi-textos\textos\<tipo>\<ano>\<documento>\<arquivo>.txt` (UTF-8, LF, NFC, já mascarado);
    6. gravar `D:\git\radar-vereadores-niteroi-textos\trechos\<tipo>\<ano>.jsonl`, só com offsets e ordem estável.
  - S4. **Manifesto** `D:\git\radar-vereadores-niteroi\data\textos\manifesto-<ano>.json`, gravado com `salvar_mapa`, com os campos do contrato.
  - S5. **CLI.**
    - `--anos`, `--tipos`;
    - `--max-arquivos N`, onde **0 significa sem limite** e o padrão é 500;
    - `--max-minutos`, `--ocr`;
    - `--sem-rede`, que usa só o cache e marca pendência quando falta o arquivo;
    - `--reprocessar-versao`;
    - `--verificar [--amostra N]`;
    - `--commit-textos`.
  - S6. **Barreira de PII antes do commit** (achado 14). `--commit-textos` roda `mascara.varrer` em todos os textos novos e alterados. Com zero ocorrências, faz o commit em `dados-textos` com a mensagem "Atualiza textos extraídos (N arquivos)" e grava o SHA desse commit no manifesto (`commit_textos`). Com qualquer ocorrência, aborta sem commit e lista as ocorrências **sem imprimir o valor**.
  - S7. **`--verificar` confere integridade** (achado 8):
    - o SHA-256 do `.txt` bate com o `sha256_texto`;
    - o SHA-256 dos trechos bate com o manifesto;
    - com credenciais, o objeto no R2 bate com o `sha256_original`.

    A reextração só compara quando `extrator` e `versao_extrator` são iguais aos da máquina local. Se forem diferentes, registra "não comparável", sem erro.
  - S8. **Interrupção** por SIGTERM ou Ctrl+C: gravação parcial atômica, como em `D:\git\radar-vereadores-niteroi\coletor\documentos.py`.
- **T2.1.2 Carga inicial local completa, com OCR.** `router: role=runner class=other risk=medium scope=repo needs=shell`. Executada pelo orquestrador.
  - S1. `python -m coletor.textos --sem-rede --ocr --max-arquivos 0`, sem commit.
  - S2. Baixar as atas que faltam no cache, com rede, e repetir S1 só para elas.
  - S3. **Auditoria manual:** 30 mascaramentos e 30 textos sem máscara sorteados, conferidos contra o original para buscar falsos positivos e negativos; e os 20 OCRs de pior confiança, com 5 inspecionados visualmente.
  - S4. Com a auditoria aprovada, rodar `--commit-textos` (barreira S6).
  - S5. Relatório com:
    - contagens por status;
    - confiança do OCR;
    - mascaramentos por tipo;
    - tamanho da pasta `textos\` (≤ 60 MB) e da pasta `trechos\` (≤ 15 MB).
- **T2.1.3 Validação** (orquestrador). `router: role=general class=implement risk=medium scope=single needs=edit`
  - Em `D:\git\radar-vereadores-niteroi\coletor\validar.py`:
    - manifesto bem formado, com chaves no padrão do contrato, hashes de 64 caracteres hexadecimais e status do conjunto;
    - opção `--textos DIR`, que confere `sha256_texto` e os offsets dos trechos;
    - pendentes contados sem erro.

**Novos testes:** `D:\git\radar-vereadores-niteroi\tests\test_textos.py`, offline, com servidor HTTP local falso.
- Fila incremental.
- Exclusão de indicações e moções e dos ids em `remocoes.json`.
- Reprocessamento por versão.
- Idempotência, com os mesmos bytes no manifesto e nos textos e `processado_em` estável.
- Interrupção.
- Arquivo com novo SHA-256 para o mesmo id (novo `r2_chave`).
- Mesmo arquivo servindo a dois documentos (lista `documentos`).
- Ata com chave `sessao:<guid>`.
- Ano do manifesto igual ao `ano` do registro, não à data.
- `--sem-rede` sem cache.
- **A barreira de PII aborta o commit.**
- `--verificar` detecta texto adulterado e marca "não comparável" quando a versão difere.
- `--max-arquivos 0`.

**Critérios de aceitação**
- **Base:** os arquivos do escopo.
- **Conta como sucesso:** `ok`, `ok_ocr` ou `vazio_legitimo`. Este último exige zero caracteres úteis depois do OCR, com confiança média ≥ 60 nas páginas, e o caso fica listado no relatório.
- **Metas:**
  - sucesso ≥ 99% da base;
  - `ocr_baixa_confianca` (confiança média < 60) ≤ 1%, cada caso listado;
  - `erro_formato` ≤ 0,5%, cada caso listado com o motivo.
- A barreira de PII dá zero ocorrências.
- `python -m coletor.validar --textos D:\git\radar-vereadores-niteroi-textos` verde.

**DoD:** `dados-textos` commitada; manifesto em `main` num commit de dados; código num commit de código; relatório com números e auditoria.

**QA sênior:** `router: role=reviewer class=review risk=high scope=repo`. Nova varredura independente de CPF válido, telefone e e-mail em todo o `dados-textos` (zero fora da liberação), determinismo, tamanhos, revisão da auditoria manual.

### Phase 2.2: Cliente de nuvem e migrações

**Pré-voo:** Phase 0.2 concluída; contrato da Phase 1.3 congelado. As credenciais **não** são necessárias: os testes usam servidor falso e SQLite local.

**Tasks**

- **T2.2.1 Pacote `D:\git\radar-vereadores-niteroi\coletor\nuvem\`, só com a biblioteca padrão.** `router: role=implementer class=implement risk=high scope=multi needs=edit [tier:heavy]`
  - S1. `r2.py`: cliente S3 com **AWS SigV4** (`hmac` e `hashlib`).
    - Operações `PUT` com `If-None-Match: *`, `HEAD`, `GET` e `DELETE`. O `DELETE` é usado só pela remoção.
    - Metadados `Content-Type` e `x-amz-meta-documentos`.
  - S2. `cloudflare.py`: cliente REST.
    - **D1 `query`** com instruções parametrizadas, até 100 parâmetros, instruções ≤ 100 KB e **sem `BEGIN`/`COMMIT` explícitos**. Esses limites precisam ser confirmados antes da implementação (`router: role=researcher class=search risk=low scope=single needs=web`). Carga em massa gerando arquivos `.sql` e aplicando com `npx wrangler d1 execute <db> --remote --file`.
    - **Vectorize** `upsert` (NDJSON, até 1.000 por lote), `deleteByIds`, `info` e espera por `processedUpToMutation`.
    - **Workers AI** `@cf/baai/bge-m3`, em lotes de 50, com 429 e `Retry-After` respeitados.
  - S3. `sincronizar.py`, CLI `python -m coletor.nuvem --ambiente local|staging|production`. O ambiente `local` recebe `--sqlite CAMINHO`, aplica as migrações pelo `sqlite3` da biblioteca padrão e simula R2 e Vectorize em pastas locais. Ele serve para os testes e para o critério de aceitação:
    - (a) **barreira de PII:** `mascara.varrer` em todo trecho e ementa a enviar; aborta se encontrar algo;
    - (b) **migrações:** `npx wrangler d1 migrations apply <db> --remote`, com a pasta única `D:\git\radar-vereadores-niteroi\worker\migrations\` (achado 16);
    - (c) **R2:** envia os originais que faltam, depois de `HEAD`;
    - (d) **D1:** upsert de documentos, autoria, arquivos, `arquivo_documento`, trechos (com o texto lido do `.txt` pelos offsets) e `remocoes`, mais o FTS5; remove o que saiu do Git ou entrou em `D:\git\radar-vereadores-niteroi\config\remocoes.json`;
    - (e) **Vectorize:** vetores só para trechos novos ou alterados, pela diferença contra `trechos_indexados`. Ementas de indicações e moções viram `ementa:doc:<id>`, mascaradas. Remove os ids que sumiram e espera o processamento;
    - (f) **estado:** grava `estado_indice` só no fim, com versão, commit, `commit_textos`, total, `sha256_conjunto`, modelo, `VERSAO_TRECHOS` e data;
    - (g) **`--exportar`:** dump só das tabelas-base (o FTS é reconstruível), vetores em `vetores-<versao>.jsonl.gz` com `mtime=0` e `SHA256SUMS`, tudo enviado a `radar-niteroi-exportacoes/<versao>/`;
    - (h) **`--reconstruir`:** recria D1 e Vectorize a partir do Git;
    - (i) **`--simular`:** mostra o plano sem gravar nada.
- **T2.2.2 Migrações** `D:\git\radar-vereadores-niteroi\worker\migrations\0001_inicial.sql`. `router: role=implementer class=implement risk=medium scope=single needs=edit`
  - Tabelas:
    - `documentos(id, tipo, numero, ano, data, ementa, url, legislatura)`;
    - `autoria(documento, slug, papel)`;
    - `pessoas(slug, nome, partido_atual)`;
    - `arquivos(id, sha256, formato, status, ocr, confianca, r2_chave)`;
    - `arquivo_documento(arquivo, documento)`, relação N:N, porque um arquivo pode servir a vários documentos;
    - `remocoes(chave, sha256, motivo, data)`;
    - `trechos(id, documento, arquivo, posicao, texto, sha256)`;
    - `trechos_fts` (FTS5, `tokenize='unicode61 remove_diacritics 2'`);
    - `trechos_indexados(id, sha256)`;
    - `estado_indice`;
    - `verificacoes(data, amostra, ok, falhas_json)`.
  - Índices em `documentos(tipo, ano)` e `autoria(slug)`.
  - Antes de fixar o tokenizer, confirmar que o D1 tem FTS5 com `remove_diacritics` (`router: role=researcher class=search risk=low scope=single needs=web`). Se não tiver, normalizar o texto (sem acento, minúsculo) numa coluna própria do FTS.

**Novos testes:** `D:\git\radar-vereadores-niteroi\tests\test_nuvem_sigv4.py`, `D:\git\radar-vereadores-niteroi\tests\test_nuvem_cloudflare.py` e `D:\git\radar-vereadores-niteroi\tests\test_nuvem_sincronizar.py`, com servidor HTTP falso e `sqlite3` local.
- SigV4 contra os vetores oficiais da AWS.
- `If-None-Match`.
- Limites de lote e de parâmetros.
- 429 com `Retry-After`.
- Diferença de trechos: novos, alterados e removidos.
- Remoção propagada.
- Barreira de PII aborta.
- Idempotência: a segunda execução não faz escritas.
- `--simular` não escreve.
- `estado_indice` não é gravado se a execução falhar no meio.
- `SHA256SUMS` correto e gzip determinístico.
- Migração aplicada no SQLite local, com FTS5: "licenca" encontra "licença".
- `--reconstruir` a partir das fixtures de contrato.

**Critérios de aceitação:** todos os testes verdes; `python -m coletor.nuvem --ambiente local --sqlite D:\radar-niteroi-cache\local.sqlite --simular`, com o manifesto e os trechos reais da 2.1, lista as contagens esperadas. Sem `--simular`, a mesma carga local termina, e uma segunda execução não faz nenhuma escrita.

**DoD:** pacote, migrações e testes; uso documentado em `D:\git\radar-vereadores-niteroi\docs\backend.md`; commit.

**QA sênior:** `router: role=reviewer class=review risk=high scope=multi`. Token e chaves nunca no log, URLs com segredo redigidas, SigV4 correto, consistência quando a execução para no meio, estimativa de chamadas e custo.

**QA da Wave 2:** `router: role=reviewer class=review risk=high scope=repo`. `--simular` contra um SQLite local com os dados reais, contagens e barreira de PII.

---

## Wave 3: Carga na nuvem e API (Phases 3.1 e 3.2 em paralelo)

### Phase 3.1: Carga em staging e produção, exportação e verificação

**Pré-voo**
- [ ] QA da Wave 2 fechada.
- [ ] **Credenciais em variáveis de ambiente locais e alerta de cobrança criados** (T0.2.2). Se faltarem: checkpoint 1.1-d.
- [ ] Custo projetado da carga ≤ US$ 1: cerca de 10 M tokens × US$ 0,0118 por M, mais as escritas.

**Tasks**

- **T3.1.1 Carga em staging.** `router: role=runner class=other risk=medium scope=repo needs=shell,network`. Executada pelo orquestrador.
  - S1. `python -m coletor.nuvem --ambiente staging`.
  - S2. Esperar o Vectorize terminar o processamento e conferir as contagens contra o manifesto: D1, Vectorize `info` e objetos no R2.
- **T3.1.2 Verificação via REST, sem o Worker.** `router: role=implementer class=implement risk=medium scope=single needs=edit`
  - S1. `D:\git\radar-vereadores-niteroi\tests\test_integracao_rest.py`, que roda só com `RADAR_INTEGRACAO=1`. Faz:
    - 10 consultas FTS5 por D1 REST com termos conhecidos. A lista exata vai para o relatório; por exemplo, "Tratamento Fora de Domicílio" precisa achar o PL 1/2024;
    - 10 consultas vetoriais por REST (vetor `bge-m3` e consulta ao Vectorize), em que o documento esperado precisa aparecer entre os 10 primeiros.
  - S2. `python -m coletor.textos --verificar --amostra 200`.
- **T3.1.3 Produção e exportação.** `router: role=runner class=other risk=high scope=repo needs=shell,network`
  - S1. `python -m coletor.nuvem --ambiente production --exportar`.
  - S2. Baixar a exportação publicada e conferir o `SHA256SUMS`.

**Novos testes:** `D:\git\radar-vereadores-niteroi\tests\test_integracao_rest.py`, com os casos de S1 e a conferência de contagens.

**Critérios de aceitação:** contagens idênticas em manifesto, D1, Vectorize e R2; 10/10 FTS5 e ≥ 9/10 vetoriais; exportação com hashes válidos e escrita com `If-None-Match: *`, que recusa sobrescrever uma versão.

**DoD:** relatório com as contagens, o custo real lido no painel e as consultas; teste de integração commitado.

**QA sênior:** `router: role=reviewer class=review risk=medium scope=repo`. Contagens, privacidade dos buckets, imutabilidade das exportações, custo.

### Phase 3.2: Worker de busca

**Pré-voo:** migrações da Phase 2.2 congeladas; `npm` disponível; o researcher (`router: role=researcher class=search risk=low scope=single needs=web`) confirmou na documentação atual:
- o limite de `topK` com `returnMetadata:"indexed"`;
- o mock de bindings no `vitest-pool-workers`;
- a compatibilidade de versões do vitest com o pool.

**Tasks**

- **T3.2.1 Projeto.** `router: role=implementer class=implement risk=medium scope=multi needs=edit,shell`
  - Criar `D:\git\radar-vereadores-niteroi\worker\package.json` (versões fixadas), `D:\git\radar-vereadores-niteroi\worker\tsconfig.json`, `D:\git\radar-vereadores-niteroi\worker\vitest.config.ts` (pool workers e `coverage.provider: istanbul`) e `D:\git\radar-vereadores-niteroi\worker\src\index.ts`.
  - O pré-voo da 3.2 congela as migrações da 2.2. Se a 3.2 precisar mudar o esquema, cria uma nova migração numerada, sem editar as existentes.
- **T3.2.2 Rotas.** `router: role=implementer class=implement risk=high scope=multi needs=edit [tier:heavy]`
  - S1. `GET /api/busca?q=&modo=palavras|semantica|hibrida&tipo=&ano=&autor=&legislatura=&pagina=`.
    - **FTS5**: `bm25` e `snippet()`.
    - **Vectorize**: `topK=50` com `returnMetadata:"indexed"`; os metadados completos vêm do D1.
    - **Filtro por autor**: via `autoria`, no D1.
    - **Fusão**: RRF com k=60 e empate resolvido pelo id.
    - **Cada resultado traz**: `documento, tipo, numero, ano, ementa, trecho` (só `<mark>` permitido), `arquivo, status, ocr, confianca, url_siscam, url_original` (`/api/original/<sha256>`), `sha256, pontuacao` e `origem`.
  - S2. `GET /api/documento/:id`.
  - S3. `GET /api/original/:sha256`:
    - consulta a tabela `remocoes` do D1 **antes da Cache API** e responde 410 quando o sha está lá; a tabela é sincronizada de `D:\git\radar-vereadores-niteroi\config\remocoes.json`;
    - lê do R2 privado;
    - cabeçalhos `Content-Disposition: attachment; filename=...`, `X-Robots-Tag: noindex`, `X-Content-Type-Options: nosniff` e `Content-Security-Policy: sandbox`.
  - S4. `GET /api/versao` (de `estado_indice` e `CF_VERSION_METADATA`) e `GET /api/saude`.
  - S5. Cabeçalhos comuns:
    - `X-Radar-Commit` e `X-Radar-Indice`;
    - cache pela **Cache API**, de 60 s nas buscas e 1 dia em documento e original, com `Vary: Origin`;
    - CORS só para as origens de `D:\git\radar-vereadores-niteroi\config\backend.json`, injetadas por variável no deploy, e `localhost`.
  - S6. Segurança:
    - consulta entre 2 e 200 caracteres;
    - **escape da sintaxe FTS5**, transformando cada termo em frase entre aspas, com as aspas internas duplicadas;
    - SQL só parametrizado;
    - Rate Limiting de 60 por minuto por IP;
    - sem log de consulta nem de IP;
    - `METRICAS` grava só o modo e a contagem de resultados.
  - S7. Erros em JSON `{erro, codigo}`, sem *stack*.
- **T3.2.3 Deploy em staging e integração.** `router: role=runner class=other risk=medium scope=single needs=shell,network`
  - S1. `npx wrangler d1 migrations apply radar-niteroi-staging --remote`.
  - S2. `npx wrangler deploy --env staging` com `COMMIT=<sha>`.
  - S3. `D:\git\radar-vereadores-niteroi\worker\test\integracao.test.ts` contra o staging, com `RADAR_INTEGRACAO=1`, rodando as 20 consultas da Phase 3.1.

**Novos testes** (`D:\git\radar-vereadores-niteroi\worker\test\*.test.ts`, com D1 local mais a fixture de 30 documentos, e Vectorize e AI simulados por injeção no `env`)
- Acento e ausência de acento.
- Operadores FTS5 maliciosos (`"`, `*`, `NEAR(`, `OR`, parênteses desbalanceados).
- Injeção de SQL.
- Consulta vazia, curta e longa.
- Filtros combinados, inclusive autor.
- RRF determinístico.
- Paginação.
- CORS permitido e recusado.
- 429.
- Cabeçalhos de versão e `Vary`.
- Documento inexistente: 404.
- Original removido: 410, **mesmo quando já estava na Cache API**.
- Original com cabeçalhos de segurança.
- Vectorize indisponível: modo híbrido cai para palavras, com `aviso`.
- Leitura do `wrangler.jsonc`: observabilidade desligada.

**Critérios de aceitação:** `npm test` verde com cobertura de linhas ≥ 90% em `D:\git\radar-vereadores-niteroi\worker\src\` (istanbul); staging responde às 20 consultas; p95 ≤ 500 ms em 50 consultas medidas.

**DoD:** Worker, testes, `D:\git\radar-vereadores-niteroi\worker\README.md`, deploy em staging; commit.

**QA sênior:** `router: role=reviewer class=review risk=high scope=multi`. OWASP API, privacidade, determinismo, `limits.cpu_ms`, CORS, cabeçalhos dos originais.

**QA da Wave 3:** `router: role=reviewer class=review risk=high scope=repo`. Revisão conjunta dos dados de produção e do Worker de staging. Depois dela:
- `npx wrangler d1 migrations apply radar-niteroi --remote`;
- `npx wrangler deploy --env production`;
- o orquestrador atualiza `api_url` em `D:\git\radar-vereadores-niteroi\config\backend.json`.

---

## Wave 4: Produto e automação (Phases 4.1, 4.2 e 4.3 em paralelo; arquivos compartilhados ficam com o orquestrador)

### Phase 4.1: Página de busca, metodologia e privacidade

**Pré-voo:** Worker em produção respondendo; `api_url` em `D:\git\radar-vereadores-niteroi\config\backend.json`.

**Tasks**

- **T4.1.1 Página.** `router: role=implementer class=implement risk=medium scope=multi needs=edit`
  - S1. `D:\git\radar-vereadores-niteroi\coletor\site\pagina_busca.py` gera `busca.html` pelo template comum.
    - Formulário (`q`, modo, tipo, ano, autor) e explicação.
    - `<meta name="radar-api">` vindo de `D:\git\radar-vereadores-niteroi\config\backend.json`.
    - Sem JS: aviso e links para o SISCAM e para as listas do site.
  - S2. `D:\git\radar-vereadores-niteroi\site_src\busca.js`, com até 6 KiB em gzip:
    - resultados escapados, só com `<mark>` permitido;
    - fontes (SISCAM, original e hash) e selos "OCR" e "OCR de baixa confiança";
    - "Mostrar mais" com foco e `aria-live`;
    - filtros guardados na URL com `history.replaceState`;
    - estados de erro, 429 e indisponibilidade.
  - S3. `D:\git\radar-vereadores-niteroi\site_src\busca.css`, carregado só nessa página e só com tokens.
  - S4. O orquestrador acrescenta "Busca" em `paginas.NAV` e no glossário, em `D:\git\radar-vereadores-niteroi\coletor\site\paginas.py`, e integra a página em `D:\git\radar-vereadores-niteroi\coletor\gerar_site.py`.
- **T4.1.2 Metodologia** (o implementer redige, o orquestrador aplica em `paginas.py`). `router: role=implementer class=implement risk=medium scope=single needs=edit`
  - `#inteiro-teor`: formatos, OCR, confiança e limitações.
  - `#busca`: palavras, semântica, RRF e ausência de texto gerado.
  - `#privacidade`:
    - CPF e RG sempre mascarados;
    - telefone e e-mail mascarados, salvo contatos oficiais;
    - originais privados servidos para download;
    - remoção por issue;
    - sem log de consulta, e aviso de que a borda do Cloudflare processa a URL.
  - `#auditoria`: manifesto, hashes, exportações, atestação e o comando de verificação.

**Novos testes**
- `D:\git\radar-vereadores-niteroi\tests\test_pagina_busca.py`:
  - página sem JS;
  - `meta radar-api` igual ao `D:\git\radar-vereadores-niteroi\config\backend.json`;
  - NAV e canônica;
  - HTML ≤ 100 KiB em gzip;
  - rótulos e `aria-live`.
- `D:\git\radar-vereadores-niteroi\tests\js\busca.test.js`, com `fetch` simulado:
  - `<script>` e `<img onerror>` no trecho não executam;
  - estados vazio, erro e 429;
  - paginação e foco;
  - URL sincronizada.
- `D:\git\radar-vereadores-niteroi\tests\test_gerar_site.py`, atualizado pelo orquestrador: glossário, tabelas e orçamentos.

**Critérios de aceitação:** axe com **zero violações serious ou critical** em `busca.html` e `metodologia.html`; nenhuma rolagem horizontal a 320, 375 e 1280 px; `busca.js` ≤ 6 KiB; as 5 consultas do relatório devolvem resultados na prévia local apontando para a produção.

**DoD:** página, scripts, CSS, metodologia e testes; capturas e axe no relatório; commit.

**QA sênior:** `router: role=reviewer class=review risk=medium scope=multi`. XSS, acessibilidade, neutralidade, comportamento sem JS e com a API fora do ar.

### Phase 4.2: Automação híbrida, remoção, cron de verificação e documentação

**Pré-voo:** secrets gravados no GitHub (T0.2.2).

**Tasks**

- **T4.2.1 Workflow `D:\git\radar-vereadores-niteroi\.github\workflows\textos.yml`** (orquestrador). `router: role=general class=implement risk=high scope=multi needs=edit`
  - S1. Disparos:
    - `workflow_run` depois de `coleta.yml` com sucesso;
    - `workflow_dispatch`;
    - `pull_request`, em modo verificação: `--simular`, ambiente staging, sem commit nem push.
  - S2. Imagem `ubuntu-24.04`, com as versões de poppler e tesseract registradas no log.
  - S3. Passos:
    1. checkout de `main` e de `dados-textos` (worktree);
    2. `python -m coletor.textos --ocr --max-arquivos 1500 --max-minutos 120 --commit-textos`;
    3. `python -m coletor.validar --textos …`;
    4. testes com `RADAR_COLETA=1`.
  - S4. **Ordem de push** (achado 30):
    1. push da `dados-textos`;
    2. commit do manifesto em `main` com `commit_textos` apontando para o commit já publicado;
    3. `git pull --rebase` e push, com até 3 tentativas;
    4. se ainda falhar, o artefato preserva o manifesto e a próxima execução refaz o trabalho de forma idempotente.
  - S5. `python -m coletor.nuvem --ambiente production --exportar`.
  - S6. Atestação com `actions/attest-build-provenance` sobre o manifesto e o `SHA256SUMS`. Permissões `contents: write`, `id-token: write` e `attestations: write` só nesse job.
  - S7. Concorrência:
    - `workflow_run` e `workflow_dispatch` usam o mesmo grupo de `coleta.yml`, com `cancel-in-progress: false`;
    - `pull_request` usa `group: textos-pr-${{ github.ref }}`, para nunca cancelar uma coleta que esteja na fila.
  - S7b. **Node:** `actions/setup-node` (Node 22) e `npm ci` em `D:\git\radar-vereadores-niteroi\worker` antes do passo `coletor.nuvem`, que chama `npx wrangler`.
  - S8. Em falha: restaurar e salvar artefato, como faz o `coleta.yml`.
- **T4.2.2 Workflow `D:\git\radar-vereadores-niteroi\.github\workflows\backend.yml`** (orquestrador). `router: role=general class=implement risk=high scope=single needs=edit`
  - Em PR: `npm ci` e `npm test`.
  - Em push na `main` com mudanças em `worker/**`:
    1. testes;
    2. `d1 migrations apply` no staging, deploy no staging e `integracao.test.ts`;
    3. `d1 migrations apply` em produção e deploy em produção com `COMMIT=${{ github.sha }}`.
- **T4.2.3 Cron de verificação.** `router: role=implementer class=implement risk=medium scope=multi needs=edit`
  - S1. Em `D:\git\radar-vereadores-niteroi\worker\src\cron.ts`, ligado ao `scheduled` de `D:\git\radar-vereadores-niteroi\worker\src\index.ts`, com o horário `triggers.crons` diário em `D:\git\radar-vereadores-niteroi\worker\wrangler.jsonc`:
    - baixa os manifestos de **todos os anos** pelo `raw.githubusercontent.com`;
    - sorteia 50 arquivos de forma determinística pela data;
    - **baixa cada objeto do R2 e calcula o SHA-256** com `crypto.DigestStream`, por streaming, sem carregar tudo na memória;
    - compara o `sha256` dos trechos do D1 com os `trechos\*.jsonl` da `dados-textos`, também via raw;
    - grava o resultado em `verificacoes`. É a única escrita do Worker.
  - S2. A migração `0002` só é criada se a tabela `verificacoes` precisar de ajuste. Ela já está na `0001`.
- **T4.2.4 Remoção.** `router: role=implementer class=implement risk=high scope=multi needs=edit`
  - S1. Em `D:\git\radar-vereadores-niteroi\coletor\remocoes.py`, acrescentar `aplicar_remocoes()`, que:
    - apaga os `.txt` e os trechos correspondentes na `dados-textos`;
    - marca o item no manifesto como `status: removido`, preservando o hash e o motivo;
    - remove do D1 e do Vectorize;
    - apaga do R2 de originais;
    - regrava as exportações antigas que continham o item, numa versão nova com `SHA256SUMS` novo, e apaga a versão antiga;
    - registra a regravação em `D:\git\radar-vereadores-niteroi\docs\backend.md`.
  - S2. Procedimento manual de reescrita do histórico da `dados-textos` (`git filter-repo`), para dado pessoal vazado, documentado em `D:\git\radar-vereadores-niteroi\docs\backend.md`. Exige aprovação humana.
  - S3. Integração ao `coletor.textos` e ao `coletor.nuvem`.
- **T4.2.5 Documentação** (orquestrador), em `D:\git\radar-vereadores-niteroi\AGENTS.md`, `D:\git\radar-vereadores-niteroi\README.md` e `D:\git\radar-vereadores-niteroi\docs\backend.md`. `router: role=general class=mechanical risk=low scope=multi needs=edit`
  - Mapa do repositório.
  - Pipeline:
    - `temas` roda depois de `classificar`, dentro de `coleta.yml`. Usa só ementas mascaradas e independe de `textos`.
    - `textos` roda em `textos.yml`, depois de `coleta.yml`.
    - `nuvem` roda depois de `validar`, em `textos.yml`.
  - CLIs.
  - Variáveis `RADAR_CACHE`, `CLOUDFLARE_*` e `R2_*`.
  - Contratos da máscara, do manifesto, da remoção e de `backend.json`.
  - CI/CD, rollback e reconstrução.
  - Orçamentos.

**Novos testes**
- `D:\git\radar-vereadores-niteroi\tests\test_workflows.py`, que lê os YAMLs e confere:
  - disparos;
  - permissões mínimas;
  - ordem dos pushes;
  - concorrência;
  - modo de PR sem push;
  - `apt-get` das ferramentas.
- `actionlint`, quando existir no PATH. Senão, ele é instalado por `go install` ou pelo binário oficial na Phase 4.2, porque é uma ferramenta de desenvolvimento.
- `D:\git\radar-vereadores-niteroi\worker\test\cron.test.ts`: tudo íntegro, objeto ausente, hash divergente, ano vazio e amostra determinística.
- `D:\git\radar-vereadores-niteroi\tests\test_remocoes.py`:
  - remoção propagada a textos, manifesto, D1 (SQLite local) e R2 (servidor falso);
  - item removido não volta na coleta seguinte;
  - validação de `remocoes.json`.

**Critérios de aceitação:**
- O `textos.yml` roda verde no PR em rascunho, em modo verificação.
- O `backend.yml` roda os testes verde no PR.
- No **staging**: o orquestrador faz o deploy (`npx wrangler deploy --env staging`), dispara o cron manualmente e `/api/saude` fica íntegro; a remoção de teste propaga e responde 410.
- O deploy da 4.2 em produção fica para a T5.1.5, pelo `backend.yml`.

**DoD:** workflows, cron, remoção, documentação e testes; commit. As **execuções reais** depois do merge ficam como critério da T5.1.5 (achado 7).

**QA sênior:** `router: role=reviewer class=review risk=high scope=multi`. Permissões, segredos, concorrência com a coleta, custo do cron, remoção completa.

### Phase 4.3: Temas por IA, com checkpoint humano

**Pré-voo:** `OPENCODE_API_KEY` presente; `OPENCODE_MODEL` vazio ou igual a `deepseek-v4.1-flash`; custo estimado da carga total ≤ US$ 5, contando cerca de 50 mil ementas em lotes de 30.

**Tasks**

- **T4.3.1 Cliente de IA extraído.** `router: role=implementer class=implement risk=medium scope=multi needs=edit`
  - S1. `D:\git\radar-vereadores-niteroi\coletor\ia.py`: cliente OpenCode Go genérico, com `POST /chat/completions`, `Authorization: Bearer`, cabeçalho **`x-opencode-session`**, tentativas e `User-Agent` próprio.
  - S2. `D:\git\radar-vereadores-niteroi\coletor\classificar.py` passa a usar `ia.py` sem mudar o comportamento.
  - S3. Teste garantindo que `_hash`, `PROMPT_SISTEMA` e `VERSAO_PROMPT` continuam iguais e que o cache existente segue válido.
- **T4.3.2 `D:\git\radar-vereadores-niteroi\coletor\temas.py`.** `router: role=implementer class=implement risk=high scope=multi needs=edit`
  - S1. **Rótulos por pessoa e legislatura.**
    - Amostra determinística igual para todos: os 40 documentos mais recentes de cada tipo, com ementas mascaradas.
    - A IA propõe até 5 rótulos de 2 a 4 palavras.
    - Prompt fixo (`VERSAO_TEMAS`), publicado na metodologia, que independe de nome e partido.
  - S2. **Classificação de cada documento** num dos rótulos ou em "outros", em lotes de 30 ementas.
    - A **contagem é feita pelo código** sobre todos os documentos da pessoa na legislatura.
    - Os exemplos são os dois documentos mais recentes de cada rótulo.
  - S3. **Validação.**
    - JSON válido.
    - Rótulos sem `PALAVRAS_PROIBIDAS` (as de `D:\git\radar-vereadores-niteroi\coletor\site\resumo.py`) e sem termos ideológicos ou partidários.
    - Ids válidos e pertencentes à pessoa.
    - Tema com pelo menos 2 documentos.
    - No máximo 5 temas.
    - Em caso de falha: descartar e registrar o motivo.
  - S4. **Cache** em `D:\git\radar-vereadores-niteroi\data\temas_ia.json`:
    - classificação por documento, com chave = hash de `VERSAO_TEMAS|MODELO|ementa|rótulos`;
    - rótulos por pessoa e legislatura.
    - Legislaturas encerradas ficam estáveis. Na atual, os rótulos são recalculados quando o número de documentos cresce 10% ou mais; documentos novos só são classificados.
  - S5. **CLI** `python -m coletor.temas [--sem-ia] [--limite N] [--max-minutos N] [--amostra slug,...]`. O `--max-minutos` preserva o progresso.
- **T4.3.3 Renderização.** `router: role=implementer class=implement risk=medium scope=single needs=edit`
  - Em `D:\git\radar-vereadores-niteroi\coletor\site\temas_html.py`, um bloco **"Temas (agrupados por IA)"** separado do "Resumo em números", que continua sem IA.
  - Frase fixa: "<rótulo>: N documentos (ex.: <link>, <link>)".
  - Selo e link para `metodologia.html#temas`.
  - O orquestrador o inclui na ficha via `D:\git\radar-vereadores-niteroi\coletor\site\paginas.py`.
- **T4.3.4 Metodologia `#temas` e CI** (orquestrador). `router: role=general class=implement risk=medium scope=multi needs=edit`
  - Texto com o prompt completo, as validações, os limites e o aviso de que agrupar não é avaliar.
  - Passo `python -m coletor.temas --limite 2000 --max-minutos 12` no `D:\git\radar-vereadores-niteroi\.github\workflows\coleta.yml`, depois de `classificar`.
    - Opções do passo: `timeout-minutes: 15` e `continue-on-error: true`, com o secret `OPENCODE_API_KEY`.
    - O passo `classificar` cai de 90 para 75 minutos, para o job continuar dentro dos 350.
    - O `--max-minutos` do `temas` faz parte da T4.3.2 S5.
  - Atualizar `D:\git\radar-vereadores-niteroi\AGENTS.md`: o resumo segue sem IA, e os temas formam um bloco separado.
- **T4.3.5 Amostra e checkpoint humano (1.1-d).** `router: role=runner class=other risk=medium scope=single needs=shell,network`
  - Gerar com `--amostra` os temas de 10 pessoas de partidos diferentes, incluindo suplentes.
  - Montar um relatório com os rótulos, as contagens e os exemplos.
  - **Pedir aprovação**. As Phases 4.1 e 4.2 seguem enquanto isso.
  - Com a aprovação, gerar para todos e publicar. Se houver ajuste, mudar o prompt, subir `VERSAO_TEMAS` e mostrar de novo.

**Novos testes:** `D:\git\radar-vereadores-niteroi\tests\test_ia.py`, `D:\git\radar-vereadores-niteroi\tests\test_temas.py` e `D:\git\radar-vereadores-niteroi\tests\test_classificar*.py`.
- Cabeçalho `x-opencode-session`.
- Classificador sem regressão (hash e prompt).
- JSON inválido.
- Rótulo proibido.
- Id alheio.
- Tema com 1 documento.
- Contagem feita pelo código.
- Prompt igual para todos, independente de nome e partido.
- Cache estável e recálculo só quando cresce 10%.
- `--sem-ia` sem rede.
- Renderização só com tema validado.
- Teste de neutralidade sobre todas as pessoas.

**Critérios de aceitação:** amostra aprovada; 100% dos temas publicados válidos; teste de neutralidade verde; custo real registrado e dentro do previsto.

**DoD:** módulos, cache, bloco, metodologia, passo no CI e testes; aprovação registrada; commits de código separados do `D:\git\radar-vereadores-niteroi\data\temas_ia.json`.

**QA sênior:** `router: role=reviewer class=review risk=high scope=multi`. Ler os rótulos de todas as pessoas, privacidade (só texto mascarado é enviado), custo, reprodutibilidade.

**QA da Wave 4:** `router: role=reviewer class=review risk=high scope=repo`. Fluxo completo simulado: coleta, textos, temas, nuvem, site e busca.

---

## Wave 5: Encerramento global

### Phase 5.1: QA global, revisão adversarial, merge e execução real

**Pré-voo:** todas as DoDs cumpridas; árvore limpa; PR em rascunho com CI verde.

**Tasks**

- **T5.1.1 Verificações globais.** `router: role=runner class=other risk=medium scope=repo needs=shell`. Executadas pelo orquestrador.
  - Python, JS e `npm test`.
  - `coletor.validar --textos`.
  - `gerar_site` sem avisos.
  - axe com zero serious e critical, e capturas.
  - Integração REST e integração do Worker.
- **T5.1.2 QA sênior global.** `router: role=reviewer class=review risk=high scope=repo`
- **T5.1.3 Revisão adversarial.** `router: role=reviewer class=review risk=high scope=repo [tier:heavy]`
  - Atacar a máscara, a busca (FTS5, XSS) e o endpoint de originais (tipo de conteúdo, remoção).
  - Adulterar um objeto do staging e comprovar que o cron e o `--verificar` detectam.
  - Conferir cada critério e cada DoD contra a evidência.
- **T5.1.4 Corrigir todos os achados**, repetir a T5.1.1 e fazer uma revisão curta dos pontos corrigidos. `router: role=implementer class=implement risk=high scope=repo needs=edit`
- **T5.1.5 Entrega e execução real.** `router: role=general class=other risk=high scope=repo needs=shell,network`
  - Tirar o PR do rascunho, fazer merge com o CI verde e acompanhar o `site.yml` e o `backend.yml`.
  - Disparar `textos.yml` por `workflow_dispatch` e conferir o resultado idempotente, sem nada novo e com atestação publicada.
  - Conferir `/api/versao` igual ao commit mergeado e `/api/saude` íntegro.
  - Falha aqui: corrigir imediatamente em novo PR.

---

## 3. Critérios de aceitação globais

1. Inteiro teor do escopo com sucesso ≥ 99%, pela definição da Phase 2.1. Todo escaneado com OCR e confiança registrada.
2. Nenhum CPF ou RG, de qualquer pessoa, e nenhum telefone ou e-mail fora da lista de liberação em `dados-textos`, no D1, no Vectorize ou nas exportações. Comprovado por varredura independente.
3. Manifesto em `main` com hashes que batem com o R2, o D1 e os textos; `--verificar` e `/api/saude` íntegros.
4. Busca por palavras, semântica e híbrida em `busca.html`, sempre com fontes e sem texto gerado. Zero violações serious ou critical no axe. Funciona sem a API, mostrando um aviso.
5. Originais disponíveis só para download, pelo Worker, com remoção funcionando (410) e propagada.
6. Incremental automático com registros públicos (`coleta.yml`, depois `textos.yml`) e verificação diária no Worker.
7. Temas publicados só depois da aprovação humana, todos válidos e neutros, em bloco separado do resumo sem IA.
8. Custo recorrente projetado ≤ US$ 10/mês além do plano, pelo método do painel: uso de 7 dias × 4,3. Alerta de cobrança ativo.
9. Suítes Python, JS e Worker verdes; `coletor.validar` verde; CI verde; site publicado.

## 4. Definition of Done global

- Todas as phases com DoD e QA fechadas, achados corrigidos e relatórios em `D:\git\radar-vereadores-niteroi\docs\plans\relatorios\2026-10-27-inteiro-teor\`.
- Revisão adversarial `[tier:heavy]` final sem achado crítico ou alto em aberto.
- `D:\git\radar-vereadores-niteroi\AGENTS.md`, `D:\git\radar-vereadores-niteroi\README.md` e `D:\git\radar-vereadores-niteroi\docs\backend.md` atualizados.
- PR mergeado; `site.yml`, `backend.yml` e `textos.yml` verdes na `main`; `/api/versao` mostrando o commit mergeado.

## 5. Riscos e mitigação

| Risco | Mitigação |
|---|---|
| Leitor de Word 97 falhar em variantes | Fixtures reais e sintéticas; `erro_formato` listado; meta medida ≥ 97% |
| OCR ruim | Confiança por página; selo de baixa confiança na busca; lista no relatório |
| Falso positivo da máscara | Casos de proteção testados; auditoria manual de 30 casos; RG só com rótulo |
| Vazamento de PII | Barreiras `varrer` antes de cada commit e carga; remoção e reescrita documentadas |
| Abuso da API e custo | Rate limit, Cache API, `limits.cpu_ms`, alerta de cobrança |
| Arquivo trocado no SISCAM | Novo SHA-256 gera novo objeto no R2; o Git preserva o histórico |
| Divergência de versões entre a máquina local e o CI | Versão registrada por arquivo; verificação de integridade; reextração só com versões iguais |
| Concorrência com a coleta | Mesmo grupo de concorrência; push com tentativas; idempotência |
| Credencial comprometida | Escopo mínimo, staging separado, rotação documentada |
| Limites do Cloudflare diferentes do esperado | O `role=researcher` confirma na documentação atual antes de implementar (T2.2.1, T2.2.2, T3.2, T0.2.1 S2) |
| Workflow de PR cancelando a coleta | Grupo de concorrência próprio para PR (T4.2.1 S7), com teste |
| Job da coleta estourando o tempo | Prazos por passo; `temas` com `--max-minutos` e `continue-on-error` |

## 6. Mapa dos achados da revisão adversarial da revisão 1

| Achados | Onde foram resolvidos |
|---|---|
| 1, 20 | 0.3 (máscara) e T1.2.2 |
| 2, 40 | T1.1.4 e 1.4 (aplicação no worktree) |
| 3, 26, 27 | 0.3 (originais e remoção), 0.5, T3.2.2 S3, T4.2.4 e docs de rollback na Phase 0.2 |
| 4 | T1.1.1 |
| 5 | T1.3.1 |
| 6, 37 | T0.2.2 e pré-voo da Phase 3.1 |
| 7 | 1.3 (PR em rascunho), T4.2.1 S1 e T5.1.5 |
| 8 | T2.1.1 S7 |
| 9 | 1.5 |
| 10 | T1.1.2 S2, T1.1.3 S2 e T2.1.1 S1 |
| 11 | 0.3 e T0.2.3 S2 |
| 12 | 0.3, T0.2.3 S1 e testes da Phase 0.2 |
| 13, 23 | Phase 4.3 |
| 14 | T2.1.1 S6 e T2.2.1 S3(a) |
| 15 | T0.2.1 S4 e T3.2.2 S1 |
| 16 | T2.2.1 S2/S3 e T2.2.2 |
| 17 | 0.4 e T3.2.1 |
| 18 | T0.2.3 S1 |
| 19 | T4.2.3 |
| 21 | T1.2.1 S6/S8 e critérios da Phase 2.1 |
| 22 | T1.2.3 S2 e T2.1.2 S5 |
| 24 | Phase 1.3 |
| 25 | T1.2.4 |
| 28 | T3.1.2 e T3.2.3 |
| 29 | T0.1.4 |
| 30 | T4.2.1 S4 |
| 31, 32 | Linhas `router:` e caminhos completos em todo o plano |
| 33 | Critérios da Phase 4.1 e itens 4 e 8 da seção 3 |
| 34 | T1.3.1 S2 |
| 35 | T2.1.1 S5 |
| 36 | T3.2.2 S5 |
| 38 | 0.3 (Worker com escrita só em `verificacoes`) |
| 39 | T0.1.4 |
| 41 | Pré-voo da Phase 1.2 |

**Revisão de acompanhamento** (6 achados parciais e 13 novos):

| Achado | Onde foi resolvido |
|---|---|
| 3 (cache e trava) e novo 9 | 0.3, 0.5, T0.2.1 S2 (sem trava), T3.2.2 S3 (remoções antes da Cache API) e T4.2.4 S1 (regrava exportações antigas) |
| 5 | T2.2.2: `arquivo_documento` N:N |
| 9 e novo 5 | 1.5 (testes de configuração com o orquestrador; 1.3 cria `remocoes.py`; a 4.2 possui `textos.py` e `nuvem\`) e T1.3.1 S4/S5 |
| 10 e novo 8 | T1.1.3 S2: `precisa_arquivos` para PLs |
| 31 | 1.6 e linhas `router:` dos researchers |
| 32 | Caminhos completos em T1.2.2, T2.1.1, T2.2.1, T3.2.2, DoD da 0.2 e Phase 1.1 |
| Novo 1 | T4.2.1 S7 |
| Novo 2 | T4.3.4 e T4.3.2 S5 |
| Novo 3 | T4.2.5 |
| Novo 4 | T1.3.1 S4 e T2.2.2 |
| Novo 6 | T4.2.1 S7b |
| Novo 7 | T2.2.1 S3 e critério da 2.2 |
| Novo 10 | T4.2.3 (`DigestStream`) |
| Novo 11 | Critérios da 4.2 |
| Novo 12 | 0.3 e T0.2.2 |
| Novo 13 | Critérios da 2.1 |
