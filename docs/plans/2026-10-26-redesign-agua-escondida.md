# Plano — Redesign "Água Escondida" + página de memória "Cidade Sorriso"

- **Repositório:** `D:\git\radar-vereadores-niteroi`
- **Plataforma:** win32 · **Shell:** pwsh 7 · **Python:** 3.12+ (CI 3.12; local pode ser 3.13; escreva para 3.12) · **Node:** 22
- **Branch de integração:** `redesign-agua-escondida`, criada no pré-voo da F0 a partir de `main`.
- **Data:** 26/10/2026 · **Revisão 2:** incorpora os 35 achados da revisão adversarial do plano.
- **Executor:** um único agente LLM de alta capacidade, orquestrador do model-router, do início ao fim.

---

## 0. Objetivo e decisões aprovadas

O site deve ficar mais bonito, mais acessível e homenagear Niterói. Continua sem backend, responsivo, em JS/CSS puros, sem build e sem dependências Python externas.

| Decisão | Valor aprovado |
|---|---|
| Direção visual do site | **"Água Escondida"**: Baía de Guanabara, pôr do sol visto de Niterói, areia de Icaraí, traço dos 52 bairros |
| Direção da página de memória | **"Cidade Sorriso"**: editorial, títulos serifados, textura de azulejo própria, emblemas ilustrados |
| Homenageados | **Araribóia, Vital Brazil, Antônio Parreiras, Ismael Silva, Oscar Niemeyer** (sujeitos ao critério do item seguinte) |
| Critério de neutralidade (texto público) | "Não homenageamos quem exerceu mandato eletivo ou foi dirigente partidário. Cargos coloniais e militância pessoal não excluem e são mencionados com neutralidade." |
| **Decisões humanas na execução** | (1) Critério publicado reescrito: "Não homenageamos quem exerceu mandato eletivo ou função executiva na direção de partido político. Cargos coloniais, títulos honorários e militância pessoal não excluem e são mencionados com neutralidade." (2) Oscar Niemeyer retirado dos homenageados: a nota do PCB fala em presidente de honra (1992), mas o obituário do The Guardian o descreve como presidente do partido de 1992 a 1996. O MAC permanece na linha do tempo e na paisagem como obra. Homenageados publicados: Arariboia, Vital Brazil, Antônio Parreiras e Ismael Silva. |
| Imagens | **Só ilustrações próprias** (SVG do projeto) **ou domínio público comprovado.** Padrão: emblemas próprios, sem tentar retratar rostos |
| Ideias "WOW" | Todas: céu vivo; paralaxe por rolagem; números que contam; mapa dos 52 bairros na home; View Transitions; linha do tempo; faixa "Niterói que nos inspira" e página de memória; `og:image`. **Sem selo de aniversário** |
| UI/UX | Itens 1–14 da análise |
| Escopo | Completo, todo o site |
| Prazo | Nenhum |
| Placar sem JS | Todas as legislaturas visíveis, empilhadas e com título; só o JS esconde as abas inativas |

### Itens de UI/UX e onde são resolvidos

| # | Item | Phase |
|---|---|---|
| 1 | Menu móvel e alvos de toque | F1 |
| 2 | Overflow em 320 px | F2 |
| 3 | Rolagem horizontal das tabelas | F2 |
| 4 | Contraste AA | F0 (tokens) + F2 (componentes) |
| 5 | Tooltips por toque e Esc; coautores acessíveis | F5 |
| 6 | Abas WAI-ARIA | F5 |
| 7 | Foco no "Mostrar mais" | F5 |
| 8 | "Quem é meu vereador?" | F3 |
| 9 | Tokens de tipografia e espaçamento | F0 + F2 |
| 10 | Alternador de tema | F1 |
| 11 | Ementas expansíveis | F5 |
| 12 | Glossário | F5 |
| 13 | Favicon | F1 |
| 14 | Fontes auto-hospedadas | F0 |

---

## 1. Diretivas de execução (obrigatórias)

### 1.1 Execução contínua

- **Execute o plano inteiro, de wave em wave e de phase em phase, sem interrupções.**
- **Só pare e pergunte ao humano** em um destes casos:
  - (a) ambiguidade que muda o resultado e que este plano não resolve;
  - (b) problema crítico: risco à neutralidade editorial, licença duvidosa, segredo exposto ou perda de dados;
  - (c) bloqueio real: rede indisponível para fontes ou Playwright, testes de referência quebrados antes de qualquer mudança, ou ferramenta recusada sem alternativa.
- Fora desses casos, decida pelo padrão deste plano, registre a decisão no relatório da phase e siga.
- **Regra de conteúdo factual:** fato sem fonte pública verificável é removido. Só pergunte se isso obrigar a **remover um homenageado inteiro**.
- **Gatilho editorial obrigatório (caso b):** se a pesquisa da T0.1 confirmar que algum homenageado exerceu mandato eletivo ou cargo de **dirigente partidário**, **pare e pergunte** antes de seguir. Isso vale, por exemplo, para uma eventual presidência de Oscar Niemeyer no PCB.

### 1.2 Solução definitiva, sem entregas parciais

- Cada task entrega a solução final do seu sub-objetivo: sem stubs, `TODO` ou flags desligadas.
- **Uma task nunca consome o que outra task da mesma wave produz.** Quem consome fica na wave seguinte.
- Nenhum commit deixa o site com link quebrado ou geração falhando.
- Bug encontrado no caminho: correção mínima, sem refatorar junto.

### 1.3 Paralelismo máximo com segurança

1. **Isolamento por worktree.**
   - Toda task que **escreve código** em paralelo com outra roda em um **git worktree próprio**:
     - criado com `tools.Claude.worktree_create` a partir da ponta atual de `redesign-agua-escondida`;
     - nome `rd-<task>`, por exemplo `rd-t0-6`;
     - passado ao dispatch com `root=<caminho absoluto do worktree>` na linha `route` e no ENVIRONMENT.
   - Assim nenhuma task lê um arquivo que outra está editando: cada uma vê um snapshot estável.
   - Uma task sozinha na wave roda no worktree principal `D:\git\radar-vereadores-niteroi`.
2. **Um arquivo, um escritor por wave.**
   - Cada task declara `escreve:` e `lê:`. Dois `escreve:` da mesma wave nunca se cruzam, o que garante integração sem conflito.
   - Arquivos quentes têm dono único por wave:
     - `D:\git\radar-vereadores-niteroi\site_src\estilo.css`
     - `D:\git\radar-vereadores-niteroi\coletor\site\paginas.py`
     - `D:\git\radar-vereadores-niteroi\coletor\gerar_site.py`
     - `D:\git\radar-vereadores-niteroi\site_src\app.js`
     - `D:\git\radar-vereadores-niteroi\site_src\sessoes.js`
     - `D:\git\radar-vereadores-niteroi\AGENTS.md`
     - `D:\git\radar-vereadores-niteroi\README.md`
     - `D:\git\radar-vereadores-niteroi\.gitattributes`
3. **Integração serial pelo orquestrador.**
   - Ao fim da wave, o orquestrador integra os worktrees na branch, um de cada vez (`git merge --no-ff rd-<task>`), na ordem das tasks.
   - Depois de cada merge, roda os testes da área. Depois do último, roda a suíte completa (1.8).
   - Por fim remove os worktrees com `tools.Claude.worktree_remove`, sem `force`.
4. **Testes durante a wave:**
   - cada task roda **só os testes da sua área** no próprio worktree;
   - a suíte completa roda **depois** da integração da wave.
5. **Leituras e pesquisas:**
   - `explorer`, `researcher` e `reviewer` não escrevem;
   - rodam em paralelo com qualquer wave se lerem a branch integrada ou um worktree fechado, nunca um worktree com escrita em andamento.
6. **Leases do router:** recusa de lease significa esperar o dono terminar, nunca tentar de novo em paralelo.
7. **Git:**
   - commits só pelo orquestrador ou pelo implementer dentro do **próprio** worktree, com caminhos explícitos (`git add <paths>`), nunca `git add -A`;
   - push nunca, salvo pedido explícito do humano.

### 1.4 Commit often

- Um commit por task verificada, e um commit por correção de QA (ou grupo coeso de correções).
- **Formato da mensagem:** português, inicial maiúscula, imperativo ou terceira pessoa. Exemplo: "Inclui fontes auto-hospedadas".
- **Proibido:**
  - conventional commits;
  - trailer `Co-Authored-By` de qualquer modelo;
  - linha "Generated with";
  - misturar código com `D:\git\radar-vereadores-niteroi\data\`;
  - force push;
  - push em `main`.
- Nunca edite à mão `D:\git\radar-vereadores-niteroi\data\` ou `D:\git\radar-vereadores-niteroi\site\`.

### 1.5 Caminhos

- Toda referência a arquivo usa o caminho completo a partir de `D:\git\radar-vereadores-niteroi\`, no plano e nos prompts.
- Em worktree, o prompt traz o caminho do worktree e o caminho equivalente no repositório principal.

### 1.6 Ciclo de cada phase

1. **Pré-voo** com o checklist da phase.
2. **Waves** em ordem: tasks paralelas em worktrees, integração serial, suíte completa e **QA review da wave**.
3. **Novos testes** da phase, cobrindo caminhos felizes e os casos de borda listados.
4. **Verificação completa** (1.8), incluindo capturas.
5. **QA review da phase** (`reviewer`). Quando houver conteúdo factual, também a **checagem factual** (`researcher`, com o conteúdo colado no prompt).
6. **Corrigir todos os achados** (`implementer`) e reconfirmar retomando a **mesma** sessão do revisor.
   - Máximo de 3 ciclos.
   - Sem convergência: reverta para o último estado verde, documente e consulte o `architect` com `[tier:heavy]`. Persistindo, pergunte ao humano.
7. **Documentação da phase:** a última task de cada phase é a única dona de `D:\git\radar-vereadores-niteroi\AGENTS.md` e `D:\git\radar-vereadores-niteroi\README.md`.
8. Aceitação e DoD conferidas item a item, com evidência. Commit. Próxima phase **sem parar**.

**QA review de wave**
- Rota: `[route class=review risk=medium scope=multi d=grader]`, papel `reviewer`.
- Escopo: o diff da wave (`git diff <base>..HEAD`).
- Roda sobre a branch integrada, em paralelo com a wave seguinte **somente se** ela não escrever nenhum arquivo revisado; senão, roda antes.
- Os achados são corrigidos antes do fim da phase.

### 1.7 Anotações model-router

| Campo | Significado |
|---|---|
| `role:` | `explorer`, `researcher`, `runner`, `implementer`, `reviewer`, `architect` ou `general` |
| `route:` | Primeira linha literal do prompt: `[route class=… risk=… scope=… needs=… d=… root=…]` |
| `VERIFY:required` | Bloqueante: a wave seguinte depende do resultado |
| `VERIFY:deferred` | Não bloqueia agora. Chame `router_verify` antes de construir em cima de um resultado de risco médio ou alto |
| `[tier:heavy]` | **Só** onde aparece. Acrescente `tier=heavy pin` à rota |
| `[acceptance]` | Bloco anexado ao dispatch: `check: testsPass` + `criteria:` + `deliverable:` |
| **Ação direta do orquestrador** | Passo que exige rede **e** escrita (download de fontes, Playwright, axe). Nenhum papel tem as duas autoridades. O orquestrador executa no pwsh e registra a saída |

- Nunca defina `model`.
- Todo prompt tem TASK, EXPECTED OUTCOME, TOOLS, MUST DO, MUST NOT DO, CONTEXT e ENVIRONMENT.
- ENVIRONMENT padrão:
  > Working directory é `D:\git\radar-vereadores-niteroi` (ou o worktree `<caminho>`). Platform: win32. Shell: pwsh. Você já está aqui; não peça permissão. Siga `D:\git\radar-vereadores-niteroi\AGENTS.md`. Nunca use trailer de coautoria de IA nem "Generated with".
- Todo prompt de implementer inclui a **Lista de contratos** (seção 2.2) e os trechos de código já levantados.
- O `heavy` recebe contexto pronto.
- Retomada: depois de `NEED MORE`, `ESCALATE: authority` ou FAIL, retome a **mesma** `sessionID`.

### 1.8 Comandos de verificação

**Comandos**

| O quê | Quem | Comando |
|---|---|---|
| Testes Python | Orquestrador no pwsh; ou `pytest` via `runner` se o pré-voo da F0 confirmar que está disponível | `python -m unittest discover -s tests -t .` |
| Testes JS | `runner`, sem glob | `node --test` (o Node 22 descobre `**/*.test.js` sozinho; o pré-voo da F0 confirma que o número de testes é igual ao de `node --test "tests/js/**/*.test.js"`) |
| Validação de dados | Orquestrador no pwsh | `python -m coletor.validar` |
| Geração do site | Orquestrador no pwsh | `python -m coletor.gerar_site` |

- **Não crie `package.json`.**

**Capturas e medições (obrigatório; ação direta do orquestrador)**
- Ferramenta: Playwright via `npx`, instalado fora do repositório no pré-voo da F0 (`npx playwright install chromium`). Falha na instalação é bloqueio (1.1c).
- Scripts auxiliares só em `C:\Users\Marquinho\AppData\Local\Temp\Claude\qa\`, nunca versionados.
- Servidor: `python -m http.server -d site 8000`, subido em segundo plano e derrubado ao fim (`Stop-Process`).
- Matriz: larguras **320, 375, 768 e 1280 px** × temas **claro e escuro**, mais um passe **sem JS**, um com **movimento reduzido** e um com **forced-colors**.
- Medições:
  - overflow (`scrollWidth <= innerWidth`);
  - altura do cabeçalho;
  - erros de console;
  - requisições automáticas a outros hosts.
- Saída em `C:\Users\Marquinho\AppData\Local\Temp\Claude\capturas\<phase>\`. O `reviewer` lê as imagens.

**Regressão de tamanho**
- O relatório do `gerar_site` é comparado pelo QA com o baseline da F0, guardado em `C:\Users\Marquinho\AppData\Local\Temp\Claude\baseline-tamanhos.txt`.
- **Não é teste versionado.** No repositório ficam apenas tetos absolutos.

---

## 2. Restrições globais

### 2.1 Regras gerais

**Sem terceiros, sem dependências**
1. **Sem backend e sem carregamento automático de terceiros:** nenhum `src`, `<link rel=stylesheet|preload|icon|modulepreload>` ou `url()` para outro host.
   - **Exceção explícita:** o iframe do diálogo SISCAM, criado por ação do usuário (`D:\git\radar-vereadores-niteroi\site_src\app.js:90-97`). Links de navegação (`href`) não contam.
2. **Sem dependências:** Python só com stdlib; JS/CSS puros, sem build. Ferramentas de QA via `npx` ficam fora do repositório.

**Orçamentos (gzip)**
3. Tetos existentes:
   - HTML ≤ 100 KiB por página;
   - JSON inicial ≤ 200 KiB;
   - `D:\git\radar-vereadores-niteroi\site_src\sessoes.js` ≤ 12 KiB;
   - mapa individual ≤ 12 KiB;
   - tetos sintéticos de sessões (2.2).
4. **Tetos novos, testados:**
   - CSS global ≤ 16 KiB;
   - `D:\git\radar-vereadores-niteroi\site_src\navegacao.js` ≤ 4 KiB;
   - `D:\git\radar-vereadores-niteroi\site_src\inicio.js` ≤ 6 KiB;
   - camadas da paisagem somadas ≤ 18 KiB;
   - textura ≤ 12 KiB;
   - cada emblema ≤ 6 KiB;
   - cada woff2 ≤ 60 KiB **brutos**;
   - carga da home (HTML + CSS + JS + SVG + fontes da home) ≤ 300 KiB.

**HTML, acessibilidade e movimento**
5. **Melhoria progressiva:** conteúdo e navegação funcionam sem JS; o JS só realça. Nenhum conteúdo do servidor nasce com `hidden` esperando o JS revelar, salvo controles que só funcionam com JS.
6. **Contraste:**
   - texto normal ≥ 4,5:1;
   - texto grande e componentes/bordas de controle ≥ 3:1;
   - nos dois temas, em todas as fases do céu;
   - `forced-colors: active` suportado: bordas e foco visíveis, sem depender de cor.
7. **Alvos de toque:**
   - ≥ 44 × 44 px em navegação, botão do menu, controle de tema, combobox e botões principais ("Mostrar mais", "Baixar CSV", "Limpar filtros", "Fechar");
   - ≥ 24 × 24 px (WCAG 2.5.8 AA) em chips, `.ver-siscam`, glossário e links inline;
   - checkboxes ganham área pelo `<label>`.
8. **Movimento:** `prefers-reduced-motion: reduce` desliga paralaxe, contagem e View Transitions. Nenhuma animação > 5 s nem pisca > 3 Hz.
9. **HTML válido:** nada de bloco (`<details>`, `<div>`) dentro de `<p>`, nem interativo dentro de interativo.
10. **Elementos não focáveis ficam assim:** filhos de `role="img"` e marcas de gráfico nunca recebem `tabindex`. O dado já está em `aria-label` e nas tabelas.

**Conteúdo e licenças**
11. **Neutralidade editorial:**
    - critério publicado (seção 0);
    - mesmos critérios para todos;
    - o teste de vocabulário de sessões (2.2) vale também para o texto do shell e do glossário.
12. **Licenças:**
    - fontes OFL com `OFL-*.txt` versionado;
    - atribuição "© contribuidores do OpenStreetMap, ODbL 1.0" e data da base em **todo** mapa e na textura;
    - ilustrações próprias sob a licença do projeto;
    - foto em domínio público só pelo **art. 44 da Lei 9.610/98** (70 anos contados de 1º de janeiro do ano seguinte à **divulgação**), com autor, ano de divulgação e URL registrados em `D:\git\radar-vereadores-niteroi\config\memoria.json`.

**Formato e convenções**
13. **Determinismo:** mesma entrada, mesmos bytes no HTML e nos SVGs. O PNG é comparado pelos **pixels descomprimidos**, não pelos bytes do zlib. O relógio só entra no navegador (céu vivo).
14. **Fim de linha:** arquivos de texto novos (`*.svg`, `config/*.json`, `*.css`, `*.js`, `*.py`) com LF garantido por `D:\git\radar-vereadores-niteroi\.gitattributes`; `*.woff2` e `*.png` marcados como `binary`.
15. **Versionamento de estáticos (`?v=`):**
    - os 10 primeiros caracteres do SHA-1 dos **bytes publicados**, ou seja, depois da reescrita das `url()` do CSS;
    - um `preload` usa exatamente a mesma URL da `url()` correspondente;
    - favicon, `og:image` e SVGs referenciados também levam `?v=`.
16. **Convenções** de `D:\git\radar-vereadores-niteroi\AGENTS.md`:
    - português;
    - `from __future__ import annotations`;
    - tipos modernos;
    - `# ---- nome`;
    - avisos em `stderr` com `::warning::`.

### 2.2 Lista de contratos (anexar a todo prompt de implementer)

A T0.3 completa e confirma esta lista. **Mudar marcação travada exige atualizar Python, JS, fixtures e testes no mesmo commit, com paridade verde.**

**Tokens CSS**
- Tokens de contrato continuam com **hex literal de 6 dígitos** em `:root`, em `@media (prefers-color-scheme: dark)` e em `:root[data-theme="dark"]`, **sem `var()`**:
  - `--tinta`, `--tinta-suave`, `--tinta-fraca`, `--fundo`, `--superficie`, `--linha`;
  - `--efeito`, `--alerta`, `--presente`, `--ausente` e demais tokens de sessões;
  - `--mapa-1..5`, literais e declarados uma única vez.
- **Nunca** declarar hex em bloco `[data-theme="light"]`, porque `D:\git\radar-vereadores-niteroi\tests\test_pagina_sessoes.py:980-981` o classificaria como escuro.
- Referências: `D:\git\radar-vereadores-niteroi\tests\test_pagina_sessoes.py:967-973,992` e `D:\git\radar-vereadores-niteroi\tests\test_geo.py:217-236`.

**Fixtures**
- `D:\git\radar-vereadores-niteroi\tests\js\fixtures\faixa_sessoes.html`: paridade byte a byte (`D:\git\radar-vereadores-niteroi\tests\test_pagina_sessoes.py:202-203`, `D:\git\radar-vereadores-niteroi\tests\js\sessoes.test.js:96-99`).
- `D:\git\radar-vereadores-niteroi\tests\js\fixtures\sessoes.json`
- `D:\git\radar-vereadores-niteroi\tests\js\fixtures\cabecalho_sessoes.html` (`D:\git\radar-vereadores-niteroi\tests\test_exportar_sessoes.py:256-259`)
- `D:\git\radar-vereadores-niteroi\tests\js\fixtures\plano_docs.json`
- `D:\git\radar-vereadores-niteroi\tests\js\fixtures\pl.json`

**Orçamentos sintéticos de sessões**
- Página com mapa ≤ 65 KiB e +12 KiB (`D:\git\radar-vereadores-niteroi\tests\test_pagina_sessoes.py:1018-1019`).
- Seção individual ≤ +10 KiB (`D:\git\radar-vereadores-niteroi\tests\test_pagina_sessoes.py:1034-1035`).
- Menu, tema, metadados e glossário consomem essa margem; meça sempre.

**Vocabulário proibido em sessões**
- `D:\git\radar-vereadores-niteroi\tests\test_pagina_sessoes.py:961-965` (ex.: "governo", "oposição", "bancada") vale para **todo** o HTML de `sessoes.html`: shell, rodapé, glossário.

**Classes e textos**
- `contagem inicial` (de `projetos.html`, `D:\git\radar-vereadores-niteroi\coletor\site\paginas.py:733`), `n inicial`, `lei-situacao`, `via-substitutivo`, `tabela-graf`, `tabela-resumo`, `ver-siscam`, `n-docs`, `chip chip-principal`, `semana`.
- `<h1>Sessões e votações</h1>`, `mandato sessoes`, ordem `t-sessoes`/`mandato`/`t-atividade`.
- IDs `siscam-dialogo`/`siscam-quadro`/`siscam-titulo`, classe `com-dialogo`.
- Ausência de `class="tiles"` em sessões (`D:\git\radar-vereadores-niteroi\tests\test_pagina_sessoes.py:854`) e classes proibidas em sessões (`:965`).
- `<link rel="alternate" type="application/rss+xml"` em todas as páginas.
- Ordem e `defer` dos scripts (`D:\git\radar-vereadores-niteroi\tests\test_exportar_sessoes.py:320-334`).
- O texto literal `'<table>'` de que depende `D:\git\radar-vereadores-niteroi\coletor\site\pagina_sessoes.py:508`.
- O mapa SVG bem-formado como XML (`D:\git\radar-vereadores-niteroi\tests\test_geo.py:242`).
- Coautores: `D:\git\radar-vereadores-niteroi\tests\js\carregamento.test.js:386` (`coautores" title="…">e 1 coautor`), até a F5 mudá-lo deliberadamente.

**Harness dos testes JS**
- O `app.js` real roda em `vm.runInNewContext` com DOM falso mínimo:
  - `D:\git\radar-vereadores-niteroi\tests\js\dialogo.test.js:40-49,59`: um único handler por tipo em `document.addEventListener`; `window` sem `matchMedia` ou `localStorage`;
  - `D:\git\radar-vereadores-niteroi\tests\js\carregamento.test.js:94-104`: `document` sem `addEventListener`;
  - `D:\git\radar-vereadores-niteroi\tests\js\sessoes.test.js:206-215`.
- Código novo de menu, tema e glossário fica em `D:\git\radar-vereadores-niteroi\site_src\navegacao.js`, **não** em `app.js`.
- Toda mudança em `app.js` usa checagem defensiva de API (`typeof window.matchMedia === "function"`) e **não** adiciona um segundo listener de documento para um tipo já usado.

---

## 3. Referência de design

### 3.1 Paleta "Água Escondida"

Todos os valores são hex literais de 6 dígitos. A coluna **Tom** indica a cor de referência; o hex final é o que passar no teste de contraste da T0.8.

| Token (contrato existente) | Claro | Escuro | Tom |
|---|---|---|---|
| `--tinta` | `#0B2A3F` | `#E6EEF4` | Baía profunda / espuma |
| `--fundo` | `#F7F2E9` | `#0E1B26` | Areia de Icaraí / baía à noite |
| `--superficie` | `#FFFFFF` | `#14283A` | — |
| demais | ajustados por contraste | ajustados por contraste | Mantêm a semântica de dados |

| Token novo de identidade | Claro | Escuro | Uso |
|---|---|---|---|
| `--baia` | `#13476B` | `#9CC6E4` | Links e destaques |
| `--mar` | `#1F6F8B` | `#5FB3CF` | Acento secundário |
| `--por-do-sol` | `#B4491A` (texto) | `#F08A55` | Acento quente |
| `--por-do-sol-area` | `#E8743B` | `#E8743B` | Áreas, não texto |
| `--dourado` | `#F2B544` | `#F2B544` | Sol, realces não textuais |

- `--por-do-sol` nunca carrega significado de dado.
- O `color-scheme` CSS acompanha o tema: `:root{color-scheme:light dark}`, `:root[data-theme="dark"]{color-scheme:dark}` e `:root[data-theme="light"]{color-scheme:light}`. Esses blocos **não declaram hex**.

### 3.2 Tipografia e escala

| Família | Uso | Arquivos | Regra de tamanho |
|---|---|---|---|
| **Barlow Condensed** | Títulos e números | Pesos estáticos **500, 600 e 700**; 500 é usado em `.marca span`, `D:\git\radar-vereadores-niteroi\site_src\estilo.css:68-69` | — |
| **Public Sans** | Texto | Variável `wght`, normal e itálico | — |
| **Fraunces** | Só na página de memória | Variável só `wght` | Se passar de 60 KiB, usar estática 600 + 400 itálico, só `latin` |

- Subconjuntos `latin` + `latin-ext`; todas sob SIL OFL 1.1.
- **Tokens de escala e movimento:**
  - `--fs--1 … --fs-6` (escala 1,2 com `clamp()`);
  - `--esp-1 … --esp-8` (4, 8, 12, 16, 24, 32, 48, 64 px);
  - `--raio-1`, `--raio-2`, `--raio-pilula`;
  - `--sombra-1`, `--sombra-2`;
  - `--dur-curta: 150ms`, `--dur-media: 300ms`, `--ease-mar: cubic-bezier(.2,.7,.2,1)`.
- Texto auxiliar com mínimo de `.8125rem` e `line-height ≥ 1.4`. Rótulos SVG de 12 px ficam como exceção listada.

### 3.3 Paisagem (hero)

- **Vista:** de Niterói para o pôr do sol atrás do Rio.
- **Camadas, de trás para frente:**
  1. céu (gradiente CSS por fase);
  2. sol;
  3. serra do Rio (Pão de Açúcar, maciço com Corcovado);
  4. baía com a Ponte Rio–Niterói;
  5. promontório da Boa Viagem com o MAC e a Pedra de Itapuca;
  6. orla de Icaraí e Fortaleza de Santa Cruz.
- **Implementação:** cada camada é um SVG monocromático (forma em preto sobre transparente) usado como **`mask-image`** de um `<div aria-hidden="true">`. A cor vem de `background-color: var(--camada-N)`, que muda por tema e por fase do céu.
- **Fonte única da geometria:** `D:\git\radar-vereadores-niteroi\coletor\paisagem.py`. O mesmo módulo gera favicon, marca, camadas, textura e o PNG social.
- **Base legal para representar o MAC:** obra em logradouro público, Lei 9.610/98, art. 48.

### 3.4 Emblemas da memória (próprios, sem rostos)

| Homenageado | Emblema |
|---|---|
| Araribóia | Canoa e arco sobre a linha da baía |
| Vital Brazil | Serpente estilizada e frasco |
| Antônio Parreiras | Paleta e moldura com horizonte |
| Ismael Silva | Pandeiro e pauta |
| Oscar Niemeyer | A curva do MAC sobre a rampa |

- Cada arquivo SVG externo contém um `<symbol id="emblema">` desenhado com `currentColor` e `var(--acento)`.
- A página usa `<svg role="img" aria-labelledby="…"><title id="…">…</title><use href="memoria/<id>.svg?v=…#emblema"/></svg>`. Assim o emblema herda cor e tema. **`<img>` não deve ser usado para emblemas.**
- O azulejo é aplicado por `mask-image` em pseudo-elemento com `opacity`.

---

## 4. Phases

> Ciclo em todas: pré-voo → waves (worktrees → integração → suíte → QA da wave) → testes novos → verificação 1.8 → QA da phase (e checagem factual quando houver) → correções → documentação → aceitação/DoD → commit → próxima phase **sem parar**.

---

### F0 — Fundação: plano versionado, conteúdo verificado, `.gitattributes`, estáticos, fontes e tokens

#### Pré-voo F0

- [ ] **Passo 0:** commit deste plano na `main` local (`git add D:\git\radar-vereadores-niteroi\docs\plans\2026-10-26-redesign-agua-escondida.md`, mensagem "Inclui plano do redesign Água Escondida"). Em seguida, `git status` limpo.
- [ ] Criar e trocar para `redesign-agua-escondida`.
- [ ] Ferramentas: `python --version` ≥ 3.12, `node --version` ≥ 21, `pytest` disponível ou não, `npx playwright install chromium` concluído (obrigatório).
- [ ] `node --test` sem argumentos roda o mesmo número de testes que `node --test "tests/js/**/*.test.js"`.
- [ ] Baseline verde em 1.8. Falha pré-existente é bloqueio (1.1c).
- [ ] Guardar o baseline de tamanhos e as capturas de linha de base (matriz 1.8) de:
  - `index.html`, `projetos.html`, `atividades.html`, `sessoes.html`, `metodologia.html`;
  - uma ficha em `vereadores\`.

#### Wave 0.1 (paralela)

**T0.1 Pesquisa factual da memória e da linha do tempo**
- `role: researcher` · `route: [route class=other risk=high scope=single needs=web d=none]` · `VERIFY:deferred`
- **Para cada homenageado:**
  - nome completo;
  - nascimento e morte (ISO, ano, ou texto aproximado como "fim do século XVI");
  - vínculo com Niterói;
  - 3 a 5 fatos neutros;
  - lugar de memória na cidade;
  - **pelo menos 2 fontes HTTPS públicas** (prefeitura, IBGE, instituições, Instituto Vital Brazil/Fiocruz, museus, Dicionário Cravo Albin, Fundação Oscar Niemeyer; Wikipedia só como apoio).
- **Responder explicitamente**, com fonte, se cada um **exerceu mandato eletivo ou foi dirigente partidário**. Isso inclui verificar se Oscar Niemeyer presidiu o PCB e como descrever o cargo de capitão-mor de Araribóia. Se algum caso se confirmar, aplique o gatilho 1.1.
- **Linha do tempo:** verificar ou descartar, **sem presumir datas**:
  - fundação (1573, 22/11);
  - Vila Real da Praia Grande (1819; dia exato a verificar);
  - capital da província (1834 ou 1835, a verificar);
  - capital transferida para Petrópolis (intervalo 1894–1902/1903, a verificar);
  - Ponte Rio–Niterói (4/3/1974);
  - fusão (15/3/1975);
  - MAC (2/9/1996);
  - início da cobertura do Radar (2021).
- Sinalizar divergências entre fontes.
- **Entrega:** JSON no esquema da T0.5.

**T0.2 Pesquisa de fontes tipográficas**
- `role: researcher` · `route: [route class=other risk=low scope=single needs=web d=none]` · `VERIFY:deferred`
- URLs HTTPS com versão fixada (preferir `@fontsource` ou `@fontsource-variable` no jsDelivr) para as fontes da seção 3.2, subconjuntos `latin` e `latin-ext`.
- Para cada arquivo: `unicode-range` oficial, tamanho e URL do `OFL.txt`.
- Dizer se a Fraunces variável só `wght` cabe em 60 KiB. Se não couber, dar as URLs do plano B.

**T0.3 Inventário de contratos**
- `role: explorer` · `route: [route class=recon risk=low scope=repo d=none]` · `CAP:none` (reason: inventário exaustivo de asserts de marcação e harness em todos os testes)
- **Confirmar e completar a seção 2.2** com arquivo:linha:
  - classes, IDs, textos, seletores CSS, tokens, fixtures, orçamentos sintéticos e vocabulário proibido;
  - o harness DOM de cada teste JS (quais APIs existem no `window`/`document` falso);
  - qualquer teste que dependa de `hidden` no placar (`D:\git\radar-vereadores-niteroi\coletor\site\paginas.py:641`);
  - qualquer seletor CSS de `p.cartao-autor` ou `p.autoria`.
- **Entrega:** "Lista de contratos v2", anexada aos prompts seguintes.

**T0.4 `.gitattributes`**
- `role: implementer` · `route: [route class=mechanical risk=low scope=single needs=edit,shell d=deterministic]` · `VERIFY:required`
- `escreve:` `D:\git\radar-vereadores-niteroi\.gitattributes`
- **Acrescentar, sem alterar as regras existentes:**
  - `site_src/** text eol=lf`
  - `config/*.json text eol=lf`
  - `coletor/** text eol=lf`
  - `tests/js/** text eol=lf` (exceto `tests/fixtures/**`, que continua `-text`)
  - `*.woff2 binary`
  - `*.png binary`
- **Teste:** `D:\git\radar-vereadores-niteroi\tests\test_estaticos.py` só nasce na T0.6; aqui, verificar com `git check-attr` no relatório.

#### Wave 0.2 (paralela, worktrees)

**T0.5 Conteúdo da memória e validação**
- `role: implementer` · `route: [route class=implement risk=medium scope=multi needs=edit,shell d=deterministic root=<worktree rd-t0-5>]` · `VERIFY:required`
- `escreve:`
  - `D:\git\radar-vereadores-niteroi\config\memoria.json`
  - `D:\git\radar-vereadores-niteroi\coletor\validar.py`
  - `D:\git\radar-vereadores-niteroi\tests\test_memoria_config.py`
- `lê:` relatório da T0.1; `D:\git\radar-vereadores-niteroi\config\curadoria.json` (formato e padrão de `fontes`).
- **Esquema** (gravação no mesmo estilo de `D:\git\radar-vereadores-niteroi\config\curadoria.json`: UTF-8, LF, quebra final):

  ```json
  {"criterios": "<texto público da seção 0>",
   "homenageados": [{"id": "vital-brazil", "nome": "...", "nome_completo": "...",
     "nascimento": "AAAA-MM-DD | AAAA | null", "nascimento_texto": "opcional",
     "morte": "AAAA-MM-DD | AAAA | null", "morte_texto": "opcional",
     "categoria": "fundacao|ciencia|artes|musica|arquitetura",
     "vinculo": "...", "biografia": ["..."], "lugar_de_memoria": "opcional",
     "emblema": "vital-brazil.svg",
     "imagem": {"tipo": "propria|dominio_publico", "credito": "...",
                "autor": "obrig. se dominio_publico", "ano_divulgacao": 1930,
                "url_origem": "https://..."},
     "fontes": [{"titulo": "...", "url": "https://..."}]}],
   "linha_do_tempo": [{"data": "AAAA-MM-DD | AAAA", "data_fim": "opcional",
     "titulo": "...", "texto": "...", "fontes": [...]}]}
  ```

- **O validador confere:**
  - campos obrigatórios;
  - `morte` ou `morte_texto` presente (só falecidos);
  - `nascimento` nulo só com `nascimento_texto`;
  - datas ISO ou ano;
  - `data_fim` ≥ `data`;
  - `categoria` na lista fechada;
  - pelo menos uma fonte `https://` por pessoa e por evento;
  - `id` únicos;
  - linha do tempo ordenada por `data`;
  - domínio público exige `autor`, `ano_divulgacao` e `url_origem`, com `ano_divulgacao + 70 < ano atual` (art. 44);
  - `emblema` com nome de arquivo seguro (`^[a-z0-9-]+\.svg$`);
  - formato de gravação.
- Arquivo ausente gera aviso, não erro.
- **Casos de borda testados:**
  - arquivo ausente; JSON inválido;
  - fonte `http://` ou vazia;
  - categoria `politica`;
  - pessoa sem `morte` e sem `morte_texto`;
  - `nascimento: null` sem texto;
  - `data_fim` anterior a `data`;
  - eventos fora de ordem;
  - `id` duplicado;
  - domínio público com 69 anos (rejeitado) e com 71 anos (aceito);
  - emblema `../x.svg`;
  - CRLF;
  - nomes em NFC.

**T0.6 Pipeline de estáticos e versionamento**
- `role: implementer` · `route: [route class=implement risk=high scope=multi needs=edit,shell d=deterministic root=<worktree rd-t0-6>]` · `VERIFY:required`
- `escreve:`
  - `D:\git\radar-vereadores-niteroi\coletor\gerar_site.py`
  - `D:\git\radar-vereadores-niteroi\coletor\site\paginas.py` (só `versao_estatica`/`url_estatica`, linhas ~105-110, e o favicon com `?v=` na linha ~239)
  - `D:\git\radar-vereadores-niteroi\tests\test_estaticos.py`
  - `D:\git\radar-vereadores-niteroi\tests\test_gerar_site.py` (só o teste das linhas ~115-118)
- **Comportamento:**
  - Cópia recursiva de `D:\git\radar-vereadores-niteroi\site_src\` (substitui `D:\git\radar-vereadores-niteroi\coletor\gerar_site.py:598-599`), ignorando arquivos ocultos e `*.md`.
  - CSS publicado: cada `url(<relativo>)` local vira `url(<relativo>?v=<sha1[:10] dos bytes publicados do alvo>)`.
    - Absolutas e `data:` ficam intactas.
    - `#fragmento` é preservado depois do `?v=`.
    - Alvo inexistente é **erro** de geração com mensagem clara.
  - **Uma única função** em `paginas.py` calcula `?v=` sobre os **bytes publicados**. Para CSS, isso é depois da reescrita. Também expõe a URL versionada para `preload`, `<use href>` e `og:image`.
- **Testes de borda:**
  - subpasta aninhada;
  - `url()` com aspas simples, duplas e sem aspas;
  - `#fragmento`;
  - `data:` e `https:` intactos;
  - alvo inexistente gera erro;
  - `?v=` do CSS igual a `sha1(site\estilo.css)[:10]`;
  - `preload` e `url()` com URL idêntica (quando houver preload);
  - duas gerações com bytes iguais;
  - arquivo oculto e `*.md` ignorados.

#### Wave 0.3 (sozinha; depende da T0.6 integrada)

**T0.7 Download das fontes**
- **Ação direta do orquestrador** (rede + escrita).
- `escreve:`
  - `D:\git\radar-vereadores-niteroi\site_src\fontes\*.woff2`
  - `D:\git\radar-vereadores-niteroi\site_src\fontes\OFL-barlow-condensed.txt`, `OFL-public-sans.txt`, `OFL-fraunces.txt`
  - `D:\git\radar-vereadores-niteroi\site_src\fontes\FONTES.md`
- **Procedimento:**
  1. Baixar com `Invoke-WebRequest` das URLs da T0.2.
  2. Conferir a assinatura `wOF2` e o tamanho (≤ 60 KiB); se a Fraunces passar disso, aplicar o plano B.
  3. Registrar origem e versão em `D:\git\radar-vereadores-niteroi\site_src\fontes\FONTES.md`, que não é copiado para o site.
  4. Rodar `python -m coletor.gerar_site` para confirmar a cópia recursiva.
- Commit.

#### Wave 0.4 (sozinha)

**T0.8 Tokens, paleta, `@font-face` e `<head>` sem Google Fonts**
- `role: implementer` · `route: [route class=implement risk=high scope=multi needs=edit,shell d=deterministic]` · `VERIFY:required`
- `escreve:`
  - `D:\git\radar-vereadores-niteroi\site_src\estilo.css`
  - `D:\git\radar-vereadores-niteroi\coletor\site\paginas.py` (só o `<head>` de `pagina()`, linhas ~226-242: remover preconnect e Google Fonts de `D:\git\radar-vereadores-niteroi\coletor\site\paginas.py:235-237`; incluir `preload` das fontes críticas com `crossorigin` e URL idêntica à da `url()`)
  - `D:\git\radar-vereadores-niteroi\tests\test_design_tokens.py`
- **Escopo:**
  - Paleta e tokens das seções 3.1 e 3.2, respeitando **todas** as regras de tokens da 2.2.
  - `@font-face` com `font-display: swap` e `unicode-range`.
  - Fallbacks métricos (`size-adjust`, `ascent-override`).
  - `color-scheme` por tema.
  - Contraste AA (item 4):
    - selo de impacto alto (`D:\git\radar-vereadores-niteroi\site_src\estilo.css:127-128`);
    - `--tinta-fraca` em texto pequeno;
    - `--alerta` no escuro;
    - bordas de campo ≥ 3:1.
- **Testes:**
  - parser dos três blocos de cor, com contraste WCAG para a **lista declarada de pares**;
  - blocos escuros idênticos;
  - todo `var(--x)` usado está declarado;
  - nenhum hex em `[data-theme="light"]`;
  - nenhum `fonts.googleapis` ou `fonts.gstatic` no HTML ou CSS gerados;
  - todo `@font-face` com `font-display` e arquivo existente;
  - pesos 500, 600 e 700 da Barlow presentes.
  - **Casos de borda:** hex de 3 dígitos, `rgba()` composto sobre o fundo, token que referencia outro token (permitido só fora dos tokens de contrato).

#### Wave 0.5 (sozinha)

**T0.9 Documentação da F0**
- `role: implementer` · `route: [route class=mechanical risk=low scope=multi needs=edit d=deterministic]` · `VERIFY:deferred`
- `escreve:` `D:\git\radar-vereadores-niteroi\AGENTS.md`, `D:\git\radar-vereadores-niteroi\README.md`
- **Conteúdo:** mapa do repositório (`D:\git\radar-vereadores-niteroi\site_src\fontes\`, `D:\git\radar-vereadores-niteroi\config\memoria.json`), estáticos em subpastas, `?v=` dos bytes publicados, `.gitattributes`, validação da memória, licenças OFL.

#### QA F0

- **Review técnico**
  - `role: reviewer` · `route: [route class=review risk=medium scope=multi d=grader]`
  - Checklist:
    - licenças OFL;
    - contraste;
    - cache-busting;
    - `.gitattributes`;
    - contratos intactos;
    - capturas sem quebra;
    - regressão de tamanho contra o baseline.
- **Checagem factual**
  - `role: researcher` · `route: [route class=review risk=high scope=single needs=web d=none]`
  - O conteúdo de `D:\git\radar-vereadores-niteroi\config\memoria.json` vai colado no prompt.
  - Conferir **cada** data e afirmação contra as fontes citadas e contra fontes independentes.

#### Aceitação F0

1. Comandos de 1.8 verdes.
2. Nenhum carregamento automático de terceiros (teste).
3. Pares de contraste AA nos dois temas (teste).
4. `D:\git\radar-vereadores-niteroi\config\memoria.json` válido; checagem factual sem pendências; nenhum homenageado viola o critério (ou o humano decidiu, pelo gatilho 1.1).
5. `?v=` igual ao SHA-1 dos bytes publicados.
6. Fontes versionadas com OFL.

#### DoD F0

- Aceitação com evidência.
- Achados de QA corrigidos e reconfirmados.
- Documentação atualizada (T0.9).
- Worktrees removidos.
- Commits feitos.

```
[acceptance]
check: testsPass
criteria: suite verde; nenhum carregamento de terceiros; contraste AA por teste com tokens de contrato em hex literal; memoria.json validado e checado factualmente; ?v= sobre bytes publicados e preload igual a url(); fontes OFL locais; .gitattributes com LF e binários.
deliverable: D:\git\radar-vereadores-niteroi\.gitattributes, D:\git\radar-vereadores-niteroi\config\memoria.json, D:\git\radar-vereadores-niteroi\coletor\validar.py, D:\git\radar-vereadores-niteroi\coletor\gerar_site.py, D:\git\radar-vereadores-niteroi\coletor\site\paginas.py, D:\git\radar-vereadores-niteroi\site_src\estilo.css, D:\git\radar-vereadores-niteroi\site_src\fontes\
[/acceptance]
```

---

### F1 — Shell: menu móvel, tema, metadados, 404 e marca

#### Pré-voo F1

- [ ] DoD da F0 fechado; árvore limpa; 1.8 verde; Lista de contratos v2 à mão.
- [ ] Confirmar `URL_SITE` em `D:\git\radar-vereadores-niteroi\coletor\novidades.py:20` como base de URLs absolutas.
- [ ] Medir a margem atual dos orçamentos sintéticos de sessões (2.2).

#### Wave 1.1 (paralela, worktrees)

**T1.1 Menu móvel (item 1)**
- `role: implementer` · `route: [route class=implement risk=high scope=multi needs=edit,shell d=deterministic root=<worktree rd-t1-1>]` · `VERIFY:required`
- `escreve:`
  - `D:\git\radar-vereadores-niteroi\site_src\navegacao.js` (novo)
  - `D:\git\radar-vereadores-niteroi\coletor\site\paginas.py` (só cabeçalho, nav e inclusão de `navegacao.js`; **`NAV` sem mudar ordem nem rótulos**)
  - `D:\git\radar-vereadores-niteroi\site_src\estilo.css` (só a seção cabeçalho/nav)
  - `D:\git\radar-vereadores-niteroi\tests\test_cabecalho.py`
  - `D:\git\radar-vereadores-niteroi\tests\js\navegacao.test.js`
  - `D:\git\radar-vereadores-niteroi\tests\test_exportar_sessoes.py` (só se a ordem dos scripts mudar; ver contrato)
- **Comportamento sem JS:** nav inteira, em grade de 2 colunas abaixo de 760 px, alvos ≥ 44 px.
- **Comportamento com JS:** classe `js` em `<html>`, posta pelo script inline do `<head>`.
  - Abaixo de 760 px aparece o botão "Menu" com `aria-expanded` e `aria-controls`.
  - Esc fecha e devolve o foco ao botão.
  - Clique fora fecha.
  - Perda de foco ao sair do menu com Tab fecha.
  - Mudança de breakpoint por `matchMedia` com listener, sem estado preso.
  - Tudo com checagem defensiva das APIs.
- `aria-current="page"` preservado. **Sem link para a memória** (vai para a T4.3).
- **Testes de borda:**
  - sem a classe `js`;
  - página atual dentro do menu fechado;
  - Tab para fora;
  - Esc com o menu fechado;
  - fichas com prefixo `../`;
  - `matchMedia` ausente (sem exceção);
  - redimensionamento com o menu aberto;
  - os três harness existentes (`dialogo`, `carregamento`, `sessoes`) **inalterados e verdes**.

**T1.2 Marca e favicon (item 13) com geometria única**
- `role: implementer` · `route: [route class=implement risk=low scope=multi needs=edit,shell d=deterministic root=<worktree rd-t1-2>]` · `VERIFY:required`
- `escreve:`
  - `D:\git\radar-vereadores-niteroi\coletor\paisagem.py` (novo; seção `# ---- marca`)
  - `D:\git\radar-vereadores-niteroi\site_src\favicon.svg`
  - `D:\git\radar-vereadores-niteroi\site_src\marca.svg`
  - `D:\git\radar-vereadores-niteroi\tests\test_paisagem.py`
- **Desenho:** sol poente sobre três ondas que lembram as barras do placar, com geometria definida **só** em `paisagem.py`.
- **CLI:** `python -m coletor.paisagem --marca` grava os dois SVGs.
- **Favicon:** legível em 16 px; contraste ≥ 3:1 nos dois temas via `@media (prefers-color-scheme)` interno.
- **Testes:**
  - XML válido;
  - `viewBox` presente;
  - cores dentro da paleta;
  - ≤ 2 KiB;
  - versionado igual ao regenerado;
  - determinismo.

#### Wave 1.2 (sozinha)

**T1.3 Tema (item 10), metadados, canônica e 404**
- `role: implementer` · `route: [route class=implement risk=medium scope=multi needs=edit,shell d=deterministic]` · `VERIFY:required`
- `escreve:`
  - `D:\git\radar-vereadores-niteroi\coletor\site\paginas.py`
  - `D:\git\radar-vereadores-niteroi\coletor\site\pagina_sessoes.py` (chamadas a `pagina()`)
  - `D:\git\radar-vereadores-niteroi\coletor\gerar_site.py` (`404.html`)
  - `D:\git\radar-vereadores-niteroi\site_src\navegacao.js`
  - `D:\git\radar-vereadores-niteroi\site_src\estilo.css` (só o controle de tema)
  - `D:\git\radar-vereadores-niteroi\tests\test_cabecalho.py`
  - `D:\git\radar-vereadores-niteroi\tests\js\tema.test.js`
- **Tema:**
  - script inline no `<head>`, antes do CSS, ≤ 400 bytes: aplica `data-theme` de `localStorage['radar-tema']` dentro de `try`;
  - controle de três estados (Automático, Claro, Escuro) com `aria-pressed`, oculto sem JS;
  - valor inválido vira automático.
- **Canônica:** `pagina()` ganha o parâmetro `caminho` (as fichas hoje passam `ativo=""`, em `D:\git\radar-vereadores-niteroi\coletor\site\paginas.py:1361`). Todas as chamadas são atualizadas.
- **Metadados em todas as páginas:**
  - `theme-color` claro e escuro;
  - `og:type`, `og:site_name`, `og:locale=pt_BR`;
  - `og:url` e `<link rel="canonical">` absolutos sobre `URL_SITE`;
  - `twitter:card=summary_large_image`.
- **`404.html`:** página do template comum com links e assets por URL **absoluta** (servida em qualquer caminho), busca de vereador por lista de links e link para a home.
- **Testes de borda:**
  - storage que lança exceção;
  - valor `"azul"`;
  - mudança da preferência do sistema no modo automático;
  - canônica de ficha (slug ASCII com hífen, `D:\git\radar-vereadores-niteroi\coletor\site\modelo.py:150-152`) e de `index.html` (raiz);
  - `alertas.html` (redirect) sem metadados do template;
  - `404.html` com URLs absolutas;
  - orçamentos sintéticos de sessões verdes;
  - vocabulário proibido ausente do shell.

#### Wave 1.3 (sozinha)

**T1.4 Documentação da F1**
- `role: implementer` · `route: [route class=mechanical risk=low scope=multi needs=edit d=deterministic]` · `VERIFY:deferred`
- `escreve:` `D:\git\radar-vereadores-niteroi\AGENTS.md`, `D:\git\radar-vereadores-niteroi\README.md`
- **Conteúdo:** `navegacao.js`, tema, canônica, 404, `coletor.paisagem --marca`.

#### QA F1

- `role: reviewer` · `route: [route class=review risk=medium scope=multi d=grader]`
- **Checklist:**
  - teclado no menu;
  - nomes acessíveis;
  - tema sem flash (captura logo após o carregamento);
  - nav sem JS;
  - capturas em 320 e 375 px com o menu aberto e fechado, nos dois temas e em forced-colors;
  - altura do cabeçalho;
  - metadados (3 páginas e 1 ficha);
  - 404 servida em caminho profundo;
  - harness JS existentes verdes.

#### Aceitação F1

1. Em 320 px com JS, cabeçalho ≤ 72 px com o menu fechado (medido pelo Playwright).
2. Nav ≥ 44 px.
3. Tema persistente, sem flash, tolerante a storage bloqueado.
4. Canônica e `og:url` corretas em todas as páginas.
5. `404.html` funcional.
6. Favicon novo gerado da geometria única.

#### DoD F1

- Aceitação com evidência; QA corrigido; documentação; worktrees removidos; commits.

```
[acceptance]
check: testsPass
criteria: menu móvel em navegacao.js com fallback sem JS e harness existentes intactos; tema de três estados sem flash; canônica/og absolutos; 404 com URLs absolutas; favicon e marca gerados por coletor.paisagem.
deliverable: D:\git\radar-vereadores-niteroi\site_src\navegacao.js, D:\git\radar-vereadores-niteroi\coletor\site\paginas.py, D:\git\radar-vereadores-niteroi\coletor\paisagem.py, D:\git\radar-vereadores-niteroi\site_src\favicon.svg
[/acceptance]
```

---

### F2 — Sistema visual e responsividade no site inteiro

#### Pré-voo F2

- [ ] DoD da F1 fechado; árvore limpa; 1.8 verde; capturas "antes" da matriz completa.

#### Wave 2.1 (paralela, worktrees)

**T2.1 Tabelas roláveis (item 3)**
- `role: implementer` · `route: [route class=implement risk=medium scope=multi needs=edit,shell d=deterministic root=<worktree rd-t2-1>]` · `VERIFY:required`
- `escreve:`
  - `D:\git\radar-vereadores-niteroi\coletor\site\graficos.py`
  - `D:\git\radar-vereadores-niteroi\coletor\site\pagina_sessoes.py` (só wrappers de tabela)
  - `D:\git\radar-vereadores-niteroi\coletor\site\paginas.py` (só wrappers de tabela)
  - `D:\git\radar-vereadores-niteroi\tests\test_tabelas_rolaveis.py`
- **Contrato da classe para a T2.3:** `div.tabela-rolavel[role=region][tabindex=0]`.
  - Rótulo por `aria-labelledby` (caption ou título da figura) ou `aria-label`. `graficos.tabela` não tem `caption` (`D:\git\radar-vereadores-niteroi\coletor\site\graficos.py:63`): usar o título da figura.
  - O wrapper fica **fora** do `<table>`, preservando o literal `'<table>'` de `D:\git\radar-vereadores-niteroi\coletor\site\pagina_sessoes.py:508`.
- **Exceções**, que já são roláveis:
  - `tabela-graf tabela-resumo` (`D:\git\radar-vereadores-niteroi\coletor\site\paginas.py:504-505`);
  - a faixa `faixa-rolagem` de sessões.
- **Testes:**
  - percorrer **todo** o HTML gerado: cada `<table>` tem ancestral rolável rotulado ou está na lista de exceções;
  - SVG do mapa bem-formado como XML;
  - `faixa_sessoes.html` com paridade intacta.

**T2.2 Textura dos bairros**
- `role: implementer` · `route: [route class=implement risk=low scope=multi needs=edit,shell d=deterministic root=<worktree rd-t2-2>]` · `VERIFY:required`
- `escreve:`
  - `D:\git\radar-vereadores-niteroi\coletor\paisagem.py` (seção `# ---- textura`)
  - `D:\git\radar-vereadores-niteroi\site_src\textura-bairros.svg`
  - `D:\git\radar-vereadores-niteroi\tests\test_paisagem.py`
- **Escopo:**
  - `python -m coletor.paisagem --textura` lê `D:\git\radar-vereadores-niteroi\data\geo\bairros.json` e gera contornos em traço (máscara monocromática), simplificados.
  - Atribuição OSM e data da base em `<desc>`.
  - ≤ 12 KiB gzip; determinístico.
- **Testes:**
  - geometria ausente: a CLI falha sem sobrescrever;
  - atribuição presente;
  - teto de tamanho;
  - versionado igual ao regenerado.

#### Wave 2.2 (sozinha; consome T2.1 e T2.2)

**T2.3 Componentes em CSS (itens 2, 4, 9)**
- `role: implementer` · `route: [route class=implement risk=high scope=single needs=edit,shell d=deterministic]` · `VERIFY:required`
- `escreve:` `D:\git\radar-vereadores-niteroi\site_src\estilo.css`
- **Escopo:**
  - Tokens `--fs-*`, `--esp-*`, `--raio-*` e `--sombra-*` em todas as regras.
  - Grids com `minmax(min(100%, Npx), 1fr)`.
  - Cartões com elevação suave.
  - Estilo de `.tabela-rolavel`.
  - Textura dos bairros em `body::before` com `mask-image` + `background-color: var(--linha)` + `opacity ≤ .06`; desligada na impressão e em forced-colors.
  - Estados hover e foco com contraste.
  - `@media (forced-colors: active)`: bordas e foco visíveis.
  - Impressão revisada.
  - Todos os seletores da Lista de contratos preservados.

#### Wave 2.3 (sozinha)

**T2.4 Testes de responsividade e tetos**
- `role: implementer` · `route: [route class=implement risk=low scope=multi needs=edit,shell d=deterministic]` · `VERIFY:required`
- `escreve:` `D:\git\radar-vereadores-niteroi\tests\test_responsivo_css.py`
- **Testes:**
  - nenhuma trilha de grid com mínimo fixo > 288 px sem `min()`;
  - alvos conforme a regra 2.1-7, por seletor listado;
  - nenhum `font-size` < `.8125rem` fora das exceções listadas;
  - CSS global ≤ 16 KiB gzip;
  - nenhum HTML gerado > 100 KiB gzip;
  - bloco `forced-colors` presente;
  - orçamentos sintéticos de sessões verdes.
- **Sem comparação com baseline** (fica no QA).

#### Wave 2.4 (sozinha)

**T2.5 Documentação da F2**
- `role: implementer` · `route: [route class=mechanical risk=low scope=multi needs=edit d=deterministic]` · `VERIFY:deferred`
- `escreve:` `D:\git\radar-vereadores-niteroi\AGENTS.md`, `D:\git\radar-vereadores-niteroi\README.md`
- **Conteúdo:** tokens, tabelas roláveis, textura, forced-colors, tetos.

#### QA F2

- `role: reviewer` · `route: [route class=review risk=high scope=repo d=grader]`
- **Checklist:**
  - matriz completa;
  - **zero overflow em 320 px** em todas as páginas principais, 3 fichas e `404.html`;
  - dark mode em todos os componentes;
  - semântica das cores de dados intacta;
  - impressão;
  - forced-colors;
  - paridade de sessões;
  - regressão de tamanho contra o baseline (≤ +8 % por página, senão justificar).

#### Aceitação F2

1. Zero overflow em 320 px (medido).
2. Todas as tabelas roláveis, focáveis e rotuladas.
3. Contraste AA em componentes e estados.
4. Tokens aplicados.
5. Forced-colors suportado.
6. Tetos respeitados.

#### DoD F2

- Aceitação com evidência; QA corrigido; documentação; worktrees removidos; commits.

```
[acceptance]
check: testsPass
criteria: sem overflow em 320 px; toda tabela em região rolável rotulada (exceto tabela-resumo e faixa); tokens aplicados; forced-colors; CSS global ≤ 16 KiB gzip; contratos e orçamentos de sessões preservados.
deliverable: D:\git\radar-vereadores-niteroi\site_src\estilo.css, D:\git\radar-vereadores-niteroi\coletor\site\graficos.py, D:\git\radar-vereadores-niteroi\site_src\textura-bairros.svg, D:\git\radar-vereadores-niteroi\tests\test_responsivo_css.py
[/acceptance]
```

---

### F3 — Home "WOW": paisagem, céu vivo, paralaxe, contagem, "Quem é meu vereador?", mapa, linha do tempo, View Transitions e `og:image`

> A faixa "Niterói que nos inspira" depende dos emblemas e de `memoria.html`, por isso fica na **F4 (T4.3)**.

#### Pré-voo F3

- [ ] DoD da F2 fechado; árvore limpa; 1.8 verde.
- [ ] `D:\git\radar-vereadores-niteroi\config\memoria.json` válido.
- [ ] `D:\git\radar-vereadores-niteroi\data\geo\bairros.json` presente. Se ausente, o mapa da home fica oculto (contrato).

#### Wave 3.1 (paralela, worktrees)

**T3.1 Camadas da paisagem e PNG social**
- `role: implementer` · `route: [route class=implement risk=high scope=multi needs=edit,shell d=deterministic root=<worktree rd-t3-1>]` · `VERIFY:required`
- `escreve:`
  - `D:\git\radar-vereadores-niteroi\coletor\paisagem.py` (seções `# ---- silhuetas`, `# ---- svg`, `# ---- png`)
  - `D:\git\radar-vereadores-niteroi\site_src\paisagem\fundo.svg`, `baia.svg`, `promontorio.svg`, `orla.svg`
  - `D:\git\radar-vereadores-niteroi\site_src\og-radar.png`
  - `D:\git\radar-vereadores-niteroi\tests\test_paisagem.py`
- **SVGs:** máscaras monocromáticas com `viewBox` comum.
- **PNG 1200×630:**
  - rasterizador stdlib (`zlib`, `struct`), com varredura e cobertura analítica;
  - céu de pôr do sol em cores fixas;
  - marca da geometria única, sem texto.
- **CLI:** `python -m coletor.paisagem --camadas --og`.
- **Testes:**
  - SVG idêntico byte a byte;
  - PNG com assinatura e CRC válidos, dimensões corretas e **pixels descomprimidos idênticos** aos regenerados (raster de verificação em 300×158; o PNG completo só nos testes de CLI marcados como lentos, com tempo apenas registrado);
  - polígono com menos de 3 pontos rejeitado;
  - polígono fora do quadro recortado;
  - camadas ≤ 18 KiB somadas.

**T3.2 Blocos da home**
- `role: implementer` · `route: [route class=implement risk=high scope=multi needs=edit,shell d=deterministic root=<worktree rd-t3-2>]` · `VERIFY:required`
- `escreve:` `D:\git\radar-vereadores-niteroi\coletor\site\inicio.py` (novo), `D:\git\radar-vereadores-niteroi\tests\test_inicio.py`
- Funções puras que recebem `url_estatica` (injetada) e retornam HTML escapado:

**`hero(modelo, url_estatica)`**
- h1 atual preservado.
- `<div class="ceu" data-ceu="tarde">` com camadas `<div aria-hidden="true">`.
- Proporção fixa (`aspect-ratio`) para zero CLS.

**`quem_e_meu_vereador(modelo, prefixo)`** (item 8)
- Sem JS: `<details>` com links para as fichas da legislatura atual, em ordem alfabética.
- O mesmo HTML é a fonte do combobox.

**`mapa_home(modelo)`**
- Reusa `mapa_indicacoes` (`D:\git\radar-vereadores-niteroi\coletor\site\paginas.py:877-890`) por import, com agregados da legislatura atual, atribuição OSM, data da base e link para `atividades.html`.
- Sem geometria, retorna vazio.

**`linha_do_tempo(memoria)`**
- `<ol>` em região rolável rotulada, com `tabindex="0"`.
- Datas de intervalo exibidas como "1894–1903".

**Testes de borda**
- sem legislatura atual;
- nomes acentuados e repetidos;
- memória ausente ou vazia;
- geometria ausente;
- escape de `<` e `&`;
- IDs únicos;
- ordem cronológica;
- `data_fim`.

**T3.3 Interações da home**
- `role: implementer` · `route: [route class=implement risk=medium scope=multi needs=edit,shell d=deterministic root=<worktree rd-t3-3>]` · `VERIFY:required`
- `escreve:` `D:\git\radar-vereadores-niteroi\site_src\inicio.js` (novo), `D:\git\radar-vereadores-niteroi\tests\js\inicio.test.js` (harness próprio no padrão `vm.runInNewContext`)

**Céu vivo**
- Fase calculada pela hora em `America/Sao_Paulo` via `Intl.DateTimeFormat`, com fallback UTC−3.
- Grava `data-ceu`; reavalia a cada 10 min com a aba visível.

**Contagem**
- Lê o valor final do texto do servidor e anima em ≤ 1,2 s ao entrar na tela.
- O texto final é **idêntico** ao do servidor.
- Sem animação quando `IntersectionObserver` está ausente ou o movimento é reduzido.
- Valor real em `.so-leitor` durante a animação.

**Combobox (padrão APG)**
- Filtro sem acento e sem diferença de caixa (normalização de `D:\git\radar-vereadores-niteroi\site_src\dados.js`).
- Teclado: setas com volta, Home/End, Enter navega, Esc limpa e fecha.
- Contagem em `aria-live`.

**Testes de borda**
- 00:00, 05:59, 06:00, 17:59, 18:00 e 23:59 em São Paulo, com visitante em UTC+9;
- `Intl` sem fuso;
- números com milhar, `%`, unidade, `—` e zero;
- movimento reduzido;
- consulta vazia, só espaços, com acento ou sem resultado;
- setas nos limites;
- Esc duas vezes.

#### Wave 3.2 (sozinha; consome T3.1 a T3.3)

**T3.4 Integração na home, `inicio.css`, paralaxe, View Transitions e `og:image`**
- `role: implementer` · `route: [route class=implement risk=high scope=multi needs=edit,shell d=deterministic]` · `VERIFY:required`
- `escreve:`
  - `D:\git\radar-vereadores-niteroi\coletor\site\paginas.py` (`gerar_index`; `pagina()` com CSS/JS extras por página; `og:image` + `og:image:width/height/alt` com `?v=`)
  - `D:\git\radar-vereadores-niteroi\site_src\inicio.css` (novo)
  - `D:\git\radar-vereadores-niteroi\site_src\estilo.css` (só `@view-transition`)
  - `D:\git\radar-vereadores-niteroi\tests\test_inicio.py`
- **Ordem da home:**
  1. hero;
  2. "Quem é meu vereador?";
  3. números;
  4. destaques;
  5. mapa;
  6. placar;
  7. linha do tempo;
  8. convites.
  - (A faixa entra na T4.3, entre a linha do tempo e os convites.)
- **Fases do céu:** `inicio.css` define, por `[data-ceu]`, as cores do céu e das camadas em hex literal, com um véu atrás do h1.
- **Paralaxe:** `@supports (animation-timeline: scroll())` + `prefers-reduced-motion`.
- **View Transitions:** `@view-transition {navigation:auto}` dentro de `@media (prefers-reduced-motion: no-preference)`; `view-transition-name` único na marca e no h1.
- **Impressão da home:** sem camadas, só texto e números.
- **Testes:**
  - contraste do h1 contra a cor **mais clara** de cada fase, já com o véu (≥ 4,5:1), lido do `inicio.css`;
  - ordem das seções;
  - `inicio.css` e `inicio.js` só na home;
  - `og:image` absoluto e com `?v=` em todas as páginas;
  - home ≤ 100 KiB gzip;
  - carga da home ≤ 300 KiB;
  - guardas de `@supports` e de movimento reduzido presentes.

#### Wave 3.3 (sozinha)

**T3.5 Documentação da F3**
- `role: implementer` · `route: [route class=mechanical risk=low scope=multi needs=edit d=deterministic]` · `VERIFY:deferred`
- `escreve:` `D:\git\radar-vereadores-niteroi\AGENTS.md`, `D:\git\radar-vereadores-niteroi\README.md`
- **Conteúdo:** home, `coletor.paisagem --camadas --og`, `inicio.*`, orçamentos novos.

#### QA F3

- `role: reviewer` · `route: [route class=review risk=high scope=multi d=grader]`
- **Checklist:**
  - capturas da home na matriz;
  - 3 fases do céu (madrugada, pôr do sol, meio-dia, forçadas por `data-ceu`) nos dois temas;
  - sem JS;
  - movimento reduzido;
  - forced-colors;
  - teclado no combobox e na linha do tempo;
  - atribuição OSM no mapa;
  - `og:image` (abrir o PNG);
  - CLS (camadas com proporção fixa).

#### Aceitação F3

1. Elementos WOW da home funcionando com e sem JS.
2. h1 com contraste ≥ 4,5:1 em todas as fases (teste).
3. Combobox APG.
4. Tetos respeitados.
5. `og:image` válido em todas as páginas.
6. Movimento reduzido respeitado.

#### DoD F3

- Aceitação com evidência; QA corrigido; documentação; worktrees removidos; commits.

```
[acceptance]
check: testsPass
criteria: hero em camadas por mask-image com fases do céu testadas por contraste; contagem fiel ao texto do servidor; combobox APG com fallback em details; mapa com atribuição OSM; linha do tempo com fontes e intervalos; View Transitions/paralaxe guardados por suporte e movimento reduzido; og:image 1200x630 com pixels determinísticos; home ≤ 100 KiB gzip.
deliverable: D:\git\radar-vereadores-niteroi\coletor\site\inicio.py, D:\git\radar-vereadores-niteroi\site_src\inicio.js, D:\git\radar-vereadores-niteroi\site_src\inicio.css, D:\git\radar-vereadores-niteroi\coletor\paisagem.py, D:\git\radar-vereadores-niteroi\site_src\og-radar.png
[/acceptance]
```

---

### F4 — Página de memória "Cidade Sorriso" e faixa da home

#### Pré-voo F4

- [ ] DoD da F3 fechado; árvore limpa; 1.8 verde.
- [ ] Fraunces presente; `D:\git\radar-vereadores-niteroi\config\memoria.json` válido; checagem factual da F0 sem pendências.

#### Wave 4.1 (sozinha)

**T4.1 Emblemas e azulejo**
- `role: implementer` · `route: [route class=implement risk=medium scope=multi needs=edit,shell d=deterministic]` · `VERIFY:required`
- `escreve:`
  - `D:\git\radar-vereadores-niteroi\site_src\memoria\arariboia.svg`, `vital-brazil.svg`, `antonio-parreiras.svg`, `ismael-silva.svg`, `oscar-niemeyer.svg`
  - `D:\git\radar-vereadores-niteroi\site_src\memoria\azulejo.svg`
  - `D:\git\radar-vereadores-niteroi\tests\test_emblemas.py`
- **Formato:** `<symbol id="emblema">` com `currentColor` e `var(--acento)` (seção 3.4); azulejo como máscara. **Proibido** desenhar rostos ou usar imagens de terceiros.
- **Testes:**
  - XML válido;
  - `<symbol id="emblema">` e `viewBox` presentes;
  - ≤ 6 KiB gzip;
  - nenhuma referência externa (`<image>`, `href` http);
  - nomes de arquivo iguais aos de `emblema` em `memoria.json`.

#### Wave 4.2 (sozinha; consome T4.1)

**T4.2 Gerador da página de memória**
- `role: implementer` · `route: [route class=implement risk=medium scope=multi needs=edit,shell d=deterministic]` · `VERIFY:required`
- `escreve:`
  - `D:\git\radar-vereadores-niteroi\coletor\site\pagina_memoria.py` (novo)
  - `D:\git\radar-vereadores-niteroi\site_src\memoria.css` (novo)
  - `D:\git\radar-vereadores-niteroi\tests\test_memoria_pagina.py`
- **Estrutura da página:**
  1. Abertura editorial em Fraunces, sobre azulejo.
  2. Texto sobre a cidade.
  3. **Critérios** (texto de `criterios`).
  4. Um `<article id>` por homenageado: emblema via `<use>`, datas (`*_texto` quando aproximadas), vínculo, biografia, lugar de memória e fontes.
  5. Linha do tempo completa.
  6. Créditos (ilustrações próprias; fontes OFL).
  7. "Encontrou um erro? Abra uma issue".
- **Layout e carregamento:** duas colunas no desktop, uma no mobile; Fraunces com `preload` **só nesta página**.
- **Testes de borda:**
  - memória ausente (função não gera);
  - campos opcionais ausentes;
  - datas aproximadas;
  - escape de HTML;
  - âncoras únicas;
  - ≤ 100 KiB gzip;
  - Fraunces ausente das demais páginas;
  - vocabulário proibido ausente.

#### Wave 4.3 (sozinha)

**T4.3 Integração: geração, rodapé e faixa da home**
- `role: implementer` · `route: [route class=implement risk=medium scope=multi needs=edit,shell d=deterministic]` · `VERIFY:required`
- `escreve:`
  - `D:\git\radar-vereadores-niteroi\coletor\gerar_site.py`
  - `D:\git\radar-vereadores-niteroi\coletor\site\paginas.py` (link "Memória de Niterói" no rodapé de **todas** as páginas; faixa na home; **nav principal inalterada**)
  - `D:\git\radar-vereadores-niteroi\coletor\site\inicio.py` (`faixa_memoria`)
  - `D:\git\radar-vereadores-niteroi\site_src\inicio.css` (estilo da faixa)
  - `D:\git\radar-vereadores-niteroi\tests\test_gerar_site.py` (`PAGINAS` inclui `memoria.html` quando há memória)
  - `D:\git\radar-vereadores-niteroi\tests\test_inicio.py`
- **Condição:** faixa e link aparecem **somente se `memoria.html` foi gerada**.
- **Testes:**
  - rodapé em todas as páginas, inclusive fichas (`../`) e `404.html` (URL absoluta);
  - sem memória, nenhum link quebrado;
  - home → faixa → âncora existente em `memoria.html`;
  - orçamentos sintéticos de sessões verdes.

#### Wave 4.4 (sozinha)

**T4.4 Documentação da F4**
- `role: implementer` · `route: [route class=mechanical risk=low scope=multi needs=edit d=deterministic]` · `VERIFY:deferred`
- `escreve:` `D:\git\radar-vereadores-niteroi\AGENTS.md`, `D:\git\radar-vereadores-niteroi\README.md`
- **Conteúdo:** contrato da memória (critérios, neutralidade, art. 44, emblemas via `<use>`).

#### QA F4

- **Review técnico**
  - `role: reviewer` · `route: [route class=review risk=medium scope=multi d=grader]`
  - Checklist:
    - tom;
    - nenhum rosto ou imagem de terceiros;
    - legibilidade;
    - matriz de capturas;
    - leitor de tela (`<title>` dos emblemas);
    - impressão;
    - orçamentos.
- **Checagem factual**
  - `role: researcher` · `route: [route class=review risk=high scope=single needs=web d=none]`
  - O texto **renderizado** de `memoria.html` vai colado no prompt.
  - Conferir 100 % das afirmações.

#### Aceitação F4

1. `memoria.html` com os homenageados aprovados, critérios, fontes e créditos.
2. Emblemas próprios via `<use>`, herdando o tema.
3. Faixa na home e link no rodapé de todas as páginas.
4. Fraunces só nesta página.
5. Zero afirmação sem fonte.

#### DoD F4

- Aceitação com evidência; QA técnico e factual corrigidos; documentação; commits.

```
[acceptance]
check: testsPass
criteria: memoria.html editorial com critérios publicados, fontes HTTPS e emblemas próprios via <use> com currentColor; faixa na home e link no rodapé condicionados à página gerada; Fraunces só nessa página; ≤ 100 KiB gzip.
deliverable: D:\git\radar-vereadores-niteroi\coletor\site\pagina_memoria.py, D:\git\radar-vereadores-niteroi\site_src\memoria.css, D:\git\radar-vereadores-niteroi\site_src\memoria\
[/acceptance]
```

---

### F5 — Interações e acessibilidade (itens 5, 6, 7, 11, 12)

#### Pré-voo F5

- [ ] DoD da F4 fechado; árvore limpa; 1.8 verde.
- [ ] Margem de `D:\git\radar-vereadores-niteroi\site_src\sessoes.js` até 12 KiB gzip e dos orçamentos sintéticos medida.

#### Wave 5.1 (paralela, worktrees)

**T5.1 Tooltips, coautores, abas, placar sem JS e foco (itens 5, 6, 7)**
- `role: implementer` · `route: [route class=implement risk=high scope=multi needs=edit,shell d=deterministic root=<worktree rd-t5-1>]` · `VERIFY:required`
- `escreve:`
  - `D:\git\radar-vereadores-niteroi\site_src\app.js`
  - `D:\git\radar-vereadores-niteroi\coletor\site\paginas.py`
  - `D:\git\radar-vereadores-niteroi\site_src\estilo.css` (só tooltips, coautores e abas)
  - `D:\git\radar-vereadores-niteroi\tests\js\interacoes.test.js`
  - `D:\git\radar-vereadores-niteroi\tests\js\carregamento.test.js`
  - `D:\git\radar-vereadores-niteroi\tests\js\dialogo.test.js` (só se o harness precisar de API nova; preferir código defensivo)
  - `D:\git\radar-vereadores-niteroi\tests\test_acessibilidade_html.py`
  - `D:\git\radar-vereadores-niteroi\tests\test_documentos_site.py`
- `lê sem alterar:` `D:\git\radar-vereadores-niteroi\tests\js\sessoes.test.js`, que **deve passar inalterado**.

**Tooltips**
- Abrem por hover e foco, e por toque **só em ponteiro** (`pointerType === "touch"`, alternado).
- Fecham com Esc, toque fora ou perda de foco.
- `aria-describedby` dinâmico apenas em elementos **já** focáveis, como links de pontos.
- **Marcas não ganham `tabindex`** (regra 2.1-10).
- Um único listener delegado por tipo de evento, compatível com o harness.

**Coautores**
- `<p class="cartao-autor">` e `<p class="autoria">` (`D:\git\radar-vereadores-niteroi\coletor\site\paginas.py:330,411`) viram `<div>` com as mesmas classes, no Python e no JS (`D:\git\radar-vereadores-niteroi\site_src\app.js:163,730`). CSS ajustado se houver seletor `p.`.
- A lista completa passa a ficar num `<details class="coautores"><summary>e N coautores</summary>…</details>` válido dentro do `<div>`.
- Documentos: o servidor usava `title` (`D:\git\radar-vereadores-niteroi\coletor\site\paginas.py:399`); PLs, não (`:276`).
- Atualizar `D:\git\radar-vereadores-niteroi\tests\js\carregamento.test.js:386` deliberadamente.

**Abas**
- Padrão APG: setas com volta, Home/End, `tabindex` roving, `aria-controls`, `role="tabpanel"` e `aria-labelledby`.
- **Placar sem JS:** os painéis saem do servidor **sem `hidden`**, empilhados e com título visível. O JS esconde os inativos na inicialização (corrige `D:\git\radar-vereadores-niteroi\coletor\site\paginas.py:641`).

**"Mostrar mais" (PLs e atividades)**
- Foco no primeiro item novo (`tabindex="-1"`).
- Anúncio "N itens adicionados".
- O foco nunca cai no `body` quando o botão some.

**Testes de borda**
- tooltip de elemento removido;
- dois tooltips em sequência;
- Esc sem tooltip aberto;
- toque com mouse (não abre);
- aba única;
- setas na última aba;
- placar sem JS (todas as legislaturas visíveis);
- "Mostrar mais" que esgota a lista;
- lista vazia;
- coautores com 1 e com 30 nomes;
- HTML sem `<details>` dentro de `<p>` em todo o site gerado;
- **nenhum filho focável dentro de `role="img"`** em todo o site gerado.

**T5.2 Sessões: ementas, foco e carregamento (itens 7, 11)**
- `role: implementer` · `route: [route class=implement risk=high scope=multi needs=edit,shell d=deterministic root=<worktree rd-t5-2>]` · `VERIFY:required`
- `escreve:`
  - `D:\git\radar-vereadores-niteroi\site_src\sessoes.js`
  - `D:\git\radar-vereadores-niteroi\coletor\site\pagina_sessoes.py` (cartão de votação)
  - `D:\git\radar-vereadores-niteroi\tests\js\fixtures\cartao_sessoes.html` (nova fixture de paridade do cartão)
  - `D:\git\radar-vereadores-niteroi\tests\js\fixtures\faixa_sessoes.html` (só se a faixa mudar)
  - `D:\git\radar-vereadores-niteroi\tests\js\sessoes.test.js`
  - `D:\git\radar-vereadores-niteroi\tests\test_pagina_sessoes.py`

**Ementa sem duplicar texto**
- Sem JS, a ementa aparece inteira.
- Com `html.js`, aplica-se o `line-clamp` existente (`D:\git\radar-vereadores-niteroi\site_src\estilo.css:432`) e um botão "Ver ementa completa" com `aria-expanded`, só quando a ementa passa do limiar declarado.

**Demais escopos**
- "Mostrar mais" com foco no primeiro cartão novo.
- "Carregando…" textual em `aria-live` durante a busca.
- **Paridade nova:** o cartão gerado por Python e por JS é igual a `D:\git\radar-vereadores-niteroi\tests\js\fixtures\cartao_sessoes.html`, conferido nos dois lados.

**Testes**
- paridade da faixa e do cartão;
- `sessoes.js` ≤ 12 KiB gzip;
- ementa curta (sem botão);
- ementa com `<` e `&`;
- foco após a última página;
- orçamentos sintéticos (65 KiB, +12 KiB, +10 KiB);
- vocabulário proibido ausente.

**T5.3 Glossário (item 12)**
- `role: implementer` · `route: [route class=implement risk=medium scope=multi needs=edit,shell d=deterministic root=<worktree rd-t5-3>]` · `VERIFY:required`
- `escreve:` `D:\git\radar-vereadores-niteroi\coletor\site\glossario.py` (novo), `D:\git\radar-vereadores-niteroi\tests\test_glossario.py`

**Termos**
- autorizativa, sem efeito, simbólica, substitutivo, indicação, requerimento, moção, PDL, projeto de resolução;
- veto e derrubada, quórum, parecer, consignado e votou ausente.
- As definições são factuais, alinhadas à metodologia e **sem** o vocabulário proibido de sessões.

**API**
- `ColetorGlossario(prefixo)`, um por página:
  - `termo(chave, texto)` devolve `<a class="glossario" href="{prefixo}metodologia.html#g-<chave>">texto</a>`, que funciona sem JS;
  - `definicoes()` emite **uma vez por página**, ao final do `<main>`, `<template id="glossario-defs">` só com os termos usados.
- `secao_glossario()` gera a seção `#glossario` da metodologia com `<dfn id="g-<chave>">`.

**Contextos proibidos**
- Não chamar `termo` dentro de `<summary>`, `<label>`, `<th>`, `<button>` ou `<a>`.
- Teste por varredura do HTML gerado (na T5.4).

**Testes**
- todo termo com definição e âncora;
- termo repetido gera uma única definição;
- escape;
- prefixo `../`;
- chave inexistente gera erro.

#### Wave 5.2 (sozinha; consome T5.1 a T5.3)

**T5.4 Aplicação do glossário**
- `role: implementer` · `route: [route class=implement risk=medium scope=multi needs=edit,shell d=deterministic]` · `VERIFY:required`
- `escreve:`
  - `D:\git\radar-vereadores-niteroi\coletor\site\paginas.py` (primeira ocorrência em leis, projetos, atividades, ruído; metodologia `#glossario`)
  - `D:\git\radar-vereadores-niteroi\coletor\site\pagina_sessoes.py` (quórum, parecer)
  - `D:\git\radar-vereadores-niteroi\site_src\navegacao.js` (promove `a.glossario` a popover com `<span popover>` quando `HTMLElement.prototype.showPopover` existe; sem suporte, o link continua funcionando)
  - `D:\git\radar-vereadores-niteroi\site_src\estilo.css` (estilo do glossário)
  - `D:\git\radar-vereadores-niteroi\tests\test_glossario.py`
  - `D:\git\radar-vereadores-niteroi\tests\js\navegacao.test.js`
- **Testes:**
  - nenhum termo em contexto proibido em todo o site gerado;
  - no máximo um `<template id="glossario-defs">` por página;
  - metodologia com todas as âncoras;
  - fallback sem `popover`;
  - orçamentos de HTML e de sessões verdes.

#### Wave 5.3 (sozinha)

**T5.5 Documentação da F5**
- `role: implementer` · `route: [route class=mechanical risk=low scope=multi needs=edit d=deterministic]` · `VERIFY:deferred`
- `escreve:` `D:\git\radar-vereadores-niteroi\AGENTS.md`, `D:\git\radar-vereadores-niteroi\README.md`
- **Conteúdo:** glossário, contratos de interação, fixture `cartao_sessoes.html`, placar sem JS.

#### QA F5

- `role: reviewer` · `route: [route class=review risk=high scope=repo d=grader]`
- **Checklist:**
  - roteiro só de teclado em home, projetos, atividades, sessões, ficha e memória;
  - toque (Playwright com `hasTouch`);
  - nenhum foco perdido;
  - nomes acessíveis;
  - paridades;
  - orçamentos;
  - testes de contrato verdes;
  - HTML válido nos pontos alterados.

#### Aceitação F5

1. Itens 5, 6, 7, 11 e 12 atendidos, com testes.
2. Placar acessível sem JS.
3. Glossário funcional sem JS e promovido a popover com JS.
4. `sessoes.js` ≤ 12 KiB gzip.
5. Paridades da faixa e do cartão verdes.

#### DoD F5

- Aceitação com evidência; QA corrigido; documentação; worktrees removidos; commits.

```
[acceptance]
check: testsPass
criteria: tooltips sem tornar marcas focáveis; coautores em div+details válidos com Python/JS/testes atualizados; abas APG e placar visível sem JS; foco gerenciado no Mostrar mais; ementa sem texto duplicado; glossário por link servido e popover por JS; paridade de faixa e cartão; sessoes.js ≤ 12 KiB gzip.
deliverable: D:\git\radar-vereadores-niteroi\site_src\app.js, D:\git\radar-vereadores-niteroi\site_src\sessoes.js, D:\git\radar-vereadores-niteroi\coletor\site\glossario.py, D:\git\radar-vereadores-niteroi\tests\js\fixtures\cartao_sessoes.html
[/acceptance]
```

---

### F6 — Verificação global, revisão adversarial `heavy` e fechamento

#### Pré-voo F6

- [ ] DoD de F0 a F5 fechados; árvore limpa; nenhum worktree pendente (`tools.Claude.worktree_list`).
- [ ] Site regenerado do zero.

#### Wave 6.1 (paralela; leitura e execução)

**T6.1 Bateria completa**
- **Ação direta do orquestrador** (Python e Playwright) + `role: runner` para `node --test` · `route: [route class=other risk=low scope=repo needs=shell d=deterministic]`
- **Execução:**
  - comandos de 1.8;
  - relatório de tamanhos contra o baseline;
  - matriz completa de capturas;
  - medições de overflow, console, requisições automáticas a terceiros (com a exceção do iframe SISCAM) e altura do cabeçalho.
- **Páginas:** todas as principais, 3 fichas, `memoria.html` e `404.html`.

**T6.2 Auditoria axe**
- **Ação direta do orquestrador** (rede e `npx`, fora do repositório).
- `@axe-core/cli` contra `http://localhost:8000` nas mesmas páginas, nos dois temas.
- **Exigido:** zero violações *serious* ou *critical*.
- Se a ferramenta falhar, é bloqueio (1.1c), porque o critério global depende dela.

**T6.3 Checagem factual final**
- `role: researcher` · `route: [route class=review risk=high scope=single needs=web d=none]`
- Texto renderizado de `memoria.html` e da linha do tempo colado no prompt.

#### Wave 6.2 — revisão adversarial `[tier:heavy]`

**T6.4 Revisão adversarial do plano executado**
- `role: reviewer` · `[tier:heavy]` · `route: [route class=review risk=high scope=repo d=grader tier=heavy pin]` · `VERIFY:required`
- **Entrada (colada no prompt):**
  - este plano;
  - relatórios de aceitação e DoD de F0 a F5;
  - saídas da T6.1, T6.2 e T6.3;
  - caminhos das capturas;
  - `git log --stat redesign-agua-escondida`.
- **Mandato:** provar que o plano **não** foi cumprido em:
  - itens 1 a 14 e cada ideia WOW;
  - restrições 2.1 e Lista de contratos 2.2;
  - neutralidade e critério publicado;
  - licenças (OFL, ODbL, art. 44);
  - orçamentos;
  - melhoria progressiva;
  - movimento reduzido e forced-colors;
  - contraste;
  - determinismo;
  - cache-busting;
  - higiene de commits (mensagens, ausência de trailers e de "Generated with", nada de `data\` misturado).
- **Entrega:** veredito por item e defeitos por severidade.

#### Wave 6.3 — correção e reconfirmação

**T6.5 Correções**
- `role: implementer` · `route: [route class=implement risk=high scope=multi needs=edit,shell d=deterministic]` · `VERIFY:required`
- Corrigir **todos** os achados (um commit por achado ou grupo coeso).

**T6.6 Reconfirmação**
- Retomar a **mesma** sessão da T6.4 até não haver pendências (até 3 ciclos; depois, regra 1.6.6).

#### Wave 6.4 — fechamento

**T6.7 Documentação final**
- `role: implementer` · `route: [route class=mechanical risk=low scope=multi needs=edit d=deterministic]` · `VERIFY:deferred`
- `escreve:` `D:\git\radar-vereadores-niteroi\AGENTS.md`, `D:\git\radar-vereadores-niteroi\README.md`
- Consolidar e conferir a coerência com o código.

**T6.8 Relatório final ao humano**
- `role: general` · `route: [route class=other risk=low scope=repo d=none]`
- Conteúdo: o que mudou, evidências, o que não foi verificável (por exemplo, leitor de tela real) e um checklist curto de inspeção humana.
- A branch fica pronta para PR, **sem push**.

---

## 5. Critérios de aceitação globais

1. Os comandos de 1.8 verdes na branch final; todos os testes novos presentes e offline.
2. Itens de UI/UX 1 a 14 resolvidos, cada um com teste ou medição.
3. Ideias WOW presentes, funcionando sem JS, com movimento reduzido e em forced-colors.
4. Memória com critério publicado, homenageados conforme o critério, fontes HTTPS, emblemas próprios e checagem factual final sem pendências.
5. Zero carregamento automático de terceiros (exceto o iframe SISCAM por ação do usuário) e zero dependência nova.
6. Orçamentos existentes, sintéticos de sessões e novos (2.1) respeitados.
7. Contraste AA nos dois temas e em todas as fases do céu; zero violação axe *serious* ou *critical*; zero overflow em 320 px.
8. Determinismo: SVG e HTML byte a byte; PNG por pixels.
9. Atribuição OSM em todo mapa e na textura; OFL das fontes versionada.
10. `?v=` sobre bytes publicados em todos os estáticos.
11. Revisão adversarial `heavy` sem pendências.

## 6. Definition of Done global

- [ ] Aceitação global 1 a 11 com evidência no relatório final.
- [ ] Todos os QA reviews (wave, phase, factual e heavy) com achados corrigidos e reconfirmados.
- [ ] `D:\git\radar-vereadores-niteroi\AGENTS.md` e `D:\git\radar-vereadores-niteroi\README.md` coerentes com o código.
- [ ] Histórico com commits pequenos, em português, sem trailers de IA nem "Generated with", sem `data\` misturado.
- [ ] Nada editado à mão em `D:\git\radar-vereadores-niteroi\data\` ou `D:\git\radar-vereadores-niteroi\site\`; nenhum `.tmp` versionado; nenhum worktree remanescente.
- [ ] Nenhum push sem pedido explícito.

---

## 7. Riscos e mitigação

| Risco | Mitigação |
|---|---|
| Quebrar harness JS ou contratos | Código novo em `navegacao.js`; checagem defensiva; Lista de contratos em todo prompt; harness listados em `escreve:` quando mudam deliberadamente |
| Conflito entre agentes paralelos | Worktree por task, `escreve:` disjunto, integração serial, suíte após a integração |
| Fato errado ou homenageado fora do critério | T0.1 com pergunta explícita sobre mandato e cargo partidário; gatilho 1.1; checagem factual em F0, F4 e F6 |
| SVG sem tema | `mask-image` para paisagem e textura; `<use>` + `currentColor` para emblemas |
| Cache desatualizado | `?v=` sobre bytes publicados; `preload` com URL idêntica |
| CRLF no Windows | `.gitattributes` na F0 |
| PNG diferente entre versões do zlib | Comparação por pixels |
| Fraunces pesada | Plano B estático, só `latin` |
| Navegador sem `animation-timeline`, View Transitions ou `popover` | Guardas `@supports` e detecção; fallback estático ou por link |
| Margem dos orçamentos de sessões | Medição no pré-voo de F1 e F5; testes sintéticos em toda task que toca o shell |
| `router_run` sem `python` e sem glob | Python no pwsh pelo orquestrador; `node --test` sem argumentos |
| Rede indisponível | Fontes, Playwright e axe são bloqueio (1.1c), resolvido com o humano |

## 8. Mapa de arquivos

### Novos

**Conteúdo e geração**
- `D:\git\radar-vereadores-niteroi\config\memoria.json`
- `D:\git\radar-vereadores-niteroi\coletor\paisagem.py`
- `D:\git\radar-vereadores-niteroi\coletor\site\inicio.py`
- `D:\git\radar-vereadores-niteroi\coletor\site\pagina_memoria.py`
- `D:\git\radar-vereadores-niteroi\coletor\site\glossario.py`

**Estáticos**
- Fontes:
  - `D:\git\radar-vereadores-niteroi\site_src\fontes\*.woff2`
  - `D:\git\radar-vereadores-niteroi\site_src\fontes\OFL-barlow-condensed.txt`
  - `D:\git\radar-vereadores-niteroi\site_src\fontes\OFL-public-sans.txt`
  - `D:\git\radar-vereadores-niteroi\site_src\fontes\OFL-fraunces.txt`
  - `D:\git\radar-vereadores-niteroi\site_src\fontes\FONTES.md`
- Paisagem:
  - `D:\git\radar-vereadores-niteroi\site_src\paisagem\fundo.svg`
  - `D:\git\radar-vereadores-niteroi\site_src\paisagem\baia.svg`
  - `D:\git\radar-vereadores-niteroi\site_src\paisagem\promontorio.svg`
  - `D:\git\radar-vereadores-niteroi\site_src\paisagem\orla.svg`
- Memória:
  - `D:\git\radar-vereadores-niteroi\site_src\memoria\arariboia.svg`
  - `D:\git\radar-vereadores-niteroi\site_src\memoria\vital-brazil.svg`
  - `D:\git\radar-vereadores-niteroi\site_src\memoria\antonio-parreiras.svg`
  - `D:\git\radar-vereadores-niteroi\site_src\memoria\ismael-silva.svg`
  - `D:\git\radar-vereadores-niteroi\site_src\memoria\oscar-niemeyer.svg`
  - `D:\git\radar-vereadores-niteroi\site_src\memoria\azulejo.svg`
- Outros:
  - `D:\git\radar-vereadores-niteroi\site_src\textura-bairros.svg`
  - `D:\git\radar-vereadores-niteroi\site_src\marca.svg`
  - `D:\git\radar-vereadores-niteroi\site_src\og-radar.png`
  - `D:\git\radar-vereadores-niteroi\site_src\navegacao.js`
  - `D:\git\radar-vereadores-niteroi\site_src\inicio.js`
  - `D:\git\radar-vereadores-niteroi\site_src\inicio.css`
  - `D:\git\radar-vereadores-niteroi\site_src\memoria.css`

**Testes Python**
- `D:\git\radar-vereadores-niteroi\tests\test_memoria_config.py`
- `D:\git\radar-vereadores-niteroi\tests\test_estaticos.py`
- `D:\git\radar-vereadores-niteroi\tests\test_design_tokens.py`
- `D:\git\radar-vereadores-niteroi\tests\test_cabecalho.py`
- `D:\git\radar-vereadores-niteroi\tests\test_paisagem.py`
- `D:\git\radar-vereadores-niteroi\tests\test_tabelas_rolaveis.py`
- `D:\git\radar-vereadores-niteroi\tests\test_responsivo_css.py`
- `D:\git\radar-vereadores-niteroi\tests\test_inicio.py`
- `D:\git\radar-vereadores-niteroi\tests\test_emblemas.py`
- `D:\git\radar-vereadores-niteroi\tests\test_memoria_pagina.py`
- `D:\git\radar-vereadores-niteroi\tests\test_acessibilidade_html.py`
- `D:\git\radar-vereadores-niteroi\tests\test_glossario.py`

**Testes JS e fixtures**
- `D:\git\radar-vereadores-niteroi\tests\js\navegacao.test.js`
- `D:\git\radar-vereadores-niteroi\tests\js\tema.test.js`
- `D:\git\radar-vereadores-niteroi\tests\js\inicio.test.js`
- `D:\git\radar-vereadores-niteroi\tests\js\interacoes.test.js`
- `D:\git\radar-vereadores-niteroi\tests\js\fixtures\cartao_sessoes.html`

### Alterados

**Configuração do repositório**
- `D:\git\radar-vereadores-niteroi\.gitattributes`

**Front-end**
- `D:\git\radar-vereadores-niteroi\site_src\estilo.css`
- `D:\git\radar-vereadores-niteroi\site_src\app.js`
- `D:\git\radar-vereadores-niteroi\site_src\sessoes.js`
- `D:\git\radar-vereadores-niteroi\site_src\favicon.svg`

**Geração**
- `D:\git\radar-vereadores-niteroi\coletor\site\paginas.py`
- `D:\git\radar-vereadores-niteroi\coletor\site\graficos.py`
- `D:\git\radar-vereadores-niteroi\coletor\site\pagina_sessoes.py`
- `D:\git\radar-vereadores-niteroi\coletor\gerar_site.py`
- `D:\git\radar-vereadores-niteroi\coletor\validar.py`

**Testes e fixtures**
- `D:\git\radar-vereadores-niteroi\tests\test_gerar_site.py`
- `D:\git\radar-vereadores-niteroi\tests\test_pagina_sessoes.py`
- `D:\git\radar-vereadores-niteroi\tests\test_documentos_site.py`
- `D:\git\radar-vereadores-niteroi\tests\test_exportar_sessoes.py` (se a ordem dos scripts mudar)
- `D:\git\radar-vereadores-niteroi\tests\js\sessoes.test.js`
- `D:\git\radar-vereadores-niteroi\tests\js\carregamento.test.js`
- `D:\git\radar-vereadores-niteroi\tests\js\dialogo.test.js` (se necessário)
- `D:\git\radar-vereadores-niteroi\tests\js\fixtures\faixa_sessoes.html` (se a faixa mudar)

**Documentação**
- `D:\git\radar-vereadores-niteroi\AGENTS.md`
- `D:\git\radar-vereadores-niteroi\README.md`

---

## 9. Rastreabilidade da revisão adversarial (revisão 2)

| Achado | Onde foi tratado |
|---|---|
| 1 Harness JS | 2.2 (harness), T1.1 (`navegacao.js`), T5.1 (`escreve:` e código defensivo) |
| 2 Coautores | T5.1 (`<div>` + `<details>`, testes listados) |
| 3 F3/F4 invertidas | Faixa e link na T4.3, condicionados à página gerada; removidos da T1.1 |
| 4 Baseline | 1.8 (QA), T2.4 sem comparação relativa |
| 5 Tokens | 2.2 e 3.1 (hex literal; sem hex em `[data-theme="light"]`) |
| 6 SVG em `<img>` | 3.3 (`mask-image`), 3.4 (`<use>`), T2.3 (textura) |
| 7 `.gitattributes` | T0.4 |
| 8 Glossário | T5.3 e T5.4 (link servido, popover por JS, coletor por página, prefixo, contextos proibidos) |
| 9 Marcas focáveis | 2.1-10, T5.1 |
| 10 `?v=` | 2.1-15, T0.6, T0.8 |
| 11 Ordem T0.5/T0.6 | Fontes na Wave 0.3, depois da T0.6 |
| 12 Dependência na mesma wave | 1.2, F2 (T2.3 na W2.2), F4 (W4.1 → W4.2 → W4.3) |
| 13 Escopo da T2.2 | T2.1 (exceções, literal `<table>`, XML bem-formado, `paginas.py` em `escreve:`) |
| 14 Alvos de toque | 2.1-7 |
| 15 `router_run` | 1.8 (`node --test` sem glob; capturas pelo orquestrador) |
| 16 Playwright | 1.8 (obrigatório), substitutos testáveis (contraste por fase na T3.4) |
| 17 PNG e tempo | 2.1-13, T3.1 |
| 18 Fontes | 3.2 (Barlow 500; plano B da Fraunces) |
| 19 Iframe SISCAM | 2.1-1 |
| 20 Documentação | Task de documentação ao fim de cada phase |
| 21 Esquema da memória | T0.5 (`*_texto`, `null`, `data_fim`) |
| 22 Art. 44 | 2.1-12, T0.5 |
| 23 QA factual com web | `researcher` em F0, F4 e F6 |
| 24 Orçamentos sintéticos | 2.2, pré-voos de F1 e F5, testes das tasks |
| 25 Paridade do cartão | T5.2 (fixture `cartao_sessoes.html`) |
| 26 Leitura em edição | 1.3 (worktrees e suíte após integração) |
| 27 Vocabulário de sessões | 2.2, T5.3, T1.3 |
| 28 Placar sem JS | Seção 0, T5.1 |
| 29 Pré-voo com `docs/` | Passo 0 do pré-voo da F0 |
| 30 Referências | 2.2 (caminhos de fixtures; `contagem inicial` em `projetos.html`) |
| 31 Canônica e slug | T1.3 (parâmetro `caminho`; caso de borda com slug ASCII) |
| 32 Lacunas | `color-scheme` (3.1), forced-colors (2.1-6, T2.3), 404 (T1.3), impressão da home (T3.4), `?v=` no `og:image` (T3.4) |
| 33 Diretivas | Caminhos completos; `route` em todas as tasks e revisões; ações diretas do orquestrador declaradas |
| 34 Marca | Geometria única em `D:\git\radar-vereadores-niteroi\coletor\paisagem.py` (T1.2, T3.1) |
| 35 Editorial | T0.1 (datas sem presunção; pergunta sobre mandato e cargo partidário), gatilho 1.1, critério publicado |
