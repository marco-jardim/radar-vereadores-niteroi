# Guia para agentes de código

## Escopo e ambiente

O Radar dos Vereadores de Niterói é um site estático sobre a produção da Câmara desde 2021: projetos de lei e,
à parte, requerimentos, indicações, moções, projetos de decreto legislativo (PDL) e projetos de resolução.
Também apresenta sessões plenárias, presença e votos nominais. A fonte é o SISCAM. PLs combinam curadoria,
regras e cache da IA via OpenCode Go; demais documentos e sessões usam só regras, sem IA.

- Use **Python 3.12+**; o CI usa 3.12. O código ainda usa PEP 701: aspas reutilizadas no gráfico de pontos
  (`coletor/site/graficos.py`, `dispersao`) e barra invertida no campo do menu (`paginas.py`, `pagina`).
- O processamento usa só a biblioteca padrão: não adicione dependências externas sem perguntar.
- O front-end usa JavaScript e CSS puros, sem build próprio. Os testes JS requerem Node 21+; o CI usa 22.
- O site é publicado no GitHub Pages. A visão para pessoas, as páginas e as licenças estão no [README](README.md).

## Mapa do repositório

| Caminho | Responsabilidade |
| --- | --- |
| `coletor/siscam.py` | HTTP compartilhado, parsing, autoria, tramitação, substitutivos e desfechos dos PLs. |
| `coletor/documentos.py` | Listagem e detalhe seletivo dos cinco demais tipos de documento. |
| `coletor/arquivos_siscam.py` | Tabela "[ Arquivos ]" do detalhe (`extrair_arquivos`), preservação da lista anterior e preenchimento offline por `--arquivos-do-cache`. |
| `coletor/contatos.py` | Propõe contatos públicos do cache bruto com evidências; aplica somente arquivo revisado, validando perfis e backend, sem rede. |
| `coletor/sessoes.py` | Coleta de sessões, documentos da sessão, pauta, frequência e votações. |
| `coletor/regras_documentos.py` | Classificação, bairros, respostas, publicação e regras das métricas de documentos. |
| `coletor/regras_sessoes.py` | Presença, votos, parecer, quórum, qualidade e auditoria offline das sessões. |
| `coletor/classificar.py` | Taxonomia, regras, prompt, chamadas à IA, cache e curadoria dos PLs. |
| `coletor/arquivos.py` | Serialização e gravação atômica dos JSONs versionados. |
| `coletor/validar.py` | Validação de dados, configuração e temporários, sem alterar arquivos. |
| `coletor/remocoes.py` | Leitura de `config/remocoes.json` com cache: `carregar`, `chaves_removidas` e `esta_removido` (chave **ou** SHA-256); o expurgo não fica aqui. |
| `coletor/geo.py` | Conversão offline do Overpass em limites simplificados dos bairros, com fonte OSM/ODbL. |
| `coletor/paisagem.py` | Marca e favicon (`--marca`), textura dos bairros (`--textura`), camadas da paisagem (`--camadas`) e imagem de compartilhamento (`--og`); geração offline em `site_src/`, comparada por bytes nos SVGs e por pixels no PNG. |
| `coletor/novidades.py` | Eventos dos PLs pelas datas dos dados, semanas e feed RSS. |
| `coletor/gerar_site.py` | Geração de `site/`, JSONs do navegador, manifesto e relatório de tamanhos. |
| `coletor/site/modelo.py` | Enriquecimento, pessoas, mandatos, métricas, repetidos e documentos por autor. |
| `coletor/site/modelo_sessoes.py` | Agregação de sessões, cobertura e métricas da Câmara e das pessoas. |
| `coletor/site/pagina_sessoes.py` | Página de sessões, seção individual e metodologia `#sessoes`. |
| `coletor/site/pagina_busca.py` | Página `busca.html`, configuração `radar-api` e metodologia de inteiro teor, busca, privacidade e auditoria. |
| `coletor/site/inicio.py` | Blocos da home: hero com camadas, “Quem é meu vereador?”, mapa de indicações da legislatura atual e linha do tempo de `config/memoria.json`. |
| `coletor/site/pagina_memoria.py` | Página de memória `memoria.html`, gerada por `coletor.gerar_site` quando há `config/memoria.json`; link no rodapé e faixa na home só quando publicada. |
| `coletor/site/glossario.py` | Glossário: links `a.glossario` para `metodologia.html#g-*` na prosa, definições num `<template>` por página e popover progressivo em `navegacao.js`. |
| `coletor/site/graficos.py` | Gráficos SVG e tabelas acessíveis. |
| `coletor/site/paginas.py` | HTML, navegação, componentes, diálogo SISCAM e metodologia. |
| `config/vereadores.json` | Legislaturas, eleitos, partidos da eleição, apelidos, afastamentos com datas e fontes e Mesa Diretora por biênio (`mesa`, ainda não exibida no site). |
| `config/curadoria.json` | Rótulos e correções editoriais com fontes públicas. |
| `config/memoria.json` | Conteúdo editorial da memória: critérios, homenageados e linha do tempo; validado por `coletor.validar`. |
| `config/perfis.json` | Perfil público por nome do SISCAM: partido, votos e situação por mandato, outras eleições (TSE), links oficiais, falecimento opcional e fontes; validado por `coletor.validar`. |
| `config/backend.json` | URL opcional da API, origens CORS e contatos institucionais com fonte; validado por `coletor.validar`. |
| `config/remocoes.json` | Remoções por chave de origem e SHA-256, com motivo, fonte e data; validado por `coletor.validar`. |
| `data/proposicoes/`, `data/documentos/`, `data/sessoes/` | Registros coletados por ano (documentos também por tipo). |
| `data/classificacao_ia.json`, `data/meta.json` | Cache da IA e metadados das execuções. |
| `data/geo/bairros.json` | Geometria opcional gerada por `coletor.geo`. |
| `site_src/app.js` | Listas de PLs/documentos, carregador compartilhado e diálogo SISCAM. |
| `site_src/navegacao.js` | Menu móvel e tema, até 4 KiB gzip; um listener por tipo no documento em cada script, sem alterar `app.js` para essas funções. |
| `site_src/dados.js` | Hidratação das colunas e planejamento das partes de PLs/documentos. |
| `site_src/sessoes.js` | Filtros, mapa de votos, paginação e CSV de sessões. |
| `site_src/busca.js` e `busca.css` | Só em `busca.html`: consulta ao Worker, filtros na URL, trechos escapados com destaque seguro, fontes e paginação acessível; JS até 6 KiB gzip. Sem `api_url` ou JavaScript, mantém aviso e links para listas/SISCAM. |
| `site_src/inicio.js` | Só na home: céu vivo pelo fuso `America/Sao_Paulo` com fallback UTC−3, contagem dos números e combobox APG; até 6 KiB gzip. |
| `site_src/inicio.css` | Só na home: fases do céu por `[data-ceu]`, com hexadecimais apenas nesses blocos; paralaxe sob `@supports (animation-timeline: scroll())` e sem movimento reduzido. |
| `site_src/memoria.css` | Estilos da página de memória (só nela, com a Fraunces). |
| `site_src/estilo.css` | Estilos, tokens, paleta e `@font-face`. |
| `site_src/favicon.svg` | Ícone gerado por `coletor.paisagem`; não editar à mão. |
| `site_src/marca.svg` | Símbolo `#marca`: ondas com `currentColor`, sol com `fill` herdado do `<use>` via token `--marca-sol`; gerado, não editar à mão. |
| `site_src/textura-bairros.svg` | Gerada por `python -m coletor.paisagem --textura` a partir de `data/geo/bairros.json`; não editar à mão; ≤ 12 KiB gzip; atribuição OSM visível no rodapé. |
| `site_src/paisagem/*.svg` | Máscaras geradas por `python -m coletor.paisagem --camadas`; não editar à mão. |
| `site_src/og-radar.png` | Imagem de compartilhamento 1200×630 gerada por `python -m coletor.paisagem --og`; testes comparam pixels, não os bytes comprimidos. |
| `site_src/memoria/*.svg` | Emblemas próprios com `<symbol id="emblema">` e máscara de azulejo (`azulejo.svg`). |
| `site_src/fontes/` | WOFF2 auto-hospedadas Barlow Condensed, Public Sans e Fraunces; licenças `OFL-*.txt`; `FONTES.md` não publicado. |
| `tests/` | Testes Python, JS em `tests/js/` e HTML real em `tests/fixtures/siscam/`. |
| `tests/js/fixtures/cartao_sessoes.html` | Paridade Python/JavaScript do cartão de votação. |
| `worker/` | Worker de busca TypeScript (`src/`: `/api/busca`, `/api/documento`, `/api/original`, `/api/versao`, `/api/saude`; testes vitest no pool dos Workers em `test/`); `wrangler.jsonc` com produção no nível superior e staging em `env.staging`. |
| `scripts/testes.ps1` | Executor paralelo local equivalente ao discover; o CI segue sequencial. |
| `docs/backend.md` | Recursos Cloudflare, ferramentas, credenciais e rollback. |
| `docs/contratos/textos.md` | Contrato congelado de chaves, documento principal, manifesto `data/textos/manifesto-<ano>.json`, remoções, duplicatas, `dados-textos`, D1 e Vectorize; fixtures em `tests/fixtures/contratos/` (raiz em miniatura gerada por `gerar_fixtures.py`). |
| `.github/workflows/` | Testes, coleta semanal e publicação. |
| `site/` | Saída gerada e ignorada pelo Git. |

Os `__init__.py` delimitam os pacotes Python. As pastas de documentos, sessões e geometria existem na base
versionada; o código também trata sua ausência conforme os contratos abaixo.

## O que editar e como gravar

- **Nunca edite à mão `data/` nem `site/`**, inclusive geometria, cache e metadados. Corrija coleta, regras ou
  configuração e regenere; correções editoriais cabem em `config/curadoria.json`.
- Edite fontes em `coletor/`, `config/` e `site_src/` conforme a responsabilidade. O gerador apaga e recria `site/`.
- `coletor/gerar_site.py:copiar_estaticos` copia `site_src/` recursivamente pela regra única
  `paginas.publicavel`: ignora componentes do caminho iniciados por `.` e arquivos `*.md`.
  No CSS publicado, cada alvo local de `url()`, `@import "…"` e `image-set("…")` recebe
  `?v=<10 primeiros hex do SHA-1 dos bytes publicados do alvo>`, com o fragmento depois de `?v=`.
  URLs `data:` e absolutas ficam intactas; alvo inexistente, fora de `site_src/` ou não publicável é erro.
  `paginas.url_estatica(nome, prefixo)` e `versao_estatica` calculam `?v=` sobre os bytes **publicados**
  (CSS após a reescrita); preloads usam exatamente a mesma URL. O favicon também leva `?v=`.
- Preserve `/site/` com barra inicial no `.gitignore`: `site/` também ignoraria o código em `coletor/site/`.
- Grave `data/` só por `coletor/arquivos.py`: `salvar_lista` (um registro por linha), `salvar_mapa` (uma chave
  por linha) e `salvar_json` (JSON pequeno, como metadados, com `indent=1`). Não são todos o mesmo formato.
  Todos ordenam chaves, usam UTF-8, `ensure_ascii=False`, LF, quebra final e gravação atômica.
  `.gitattributes` fixa LF em `data/**`; temporários `.*.tmp` não devem ser versionados.
- `.gitattributes` também fixa LF em `site_src/**`, `coletor/**`, `config/*.json`, `tests/js/**` e `*.py`;
  marca `*.woff2` e `*.png` como binários e mantém `tests/fixtures/** -text` por último.
- O hash da IA é SHA-1 de `VERSAO_PROMPT|MODELO|ementa`, truncado para 16 caracteres. Mudar versão ou modelo
  invalida o cache **para novas chamadas**, com custo de reclassificação. Ao mudar o prompt, revise a versão
  e esse custo; não apague o cache para experimentar. O gerador lê o cache existente sem conferir esse hash.

## Pipeline e comandos

Ordem: **`siscam` → `documentos` → `sessoes` → `classificar` → `validar` → `gerar_site`**.
Os três primeiros e a classificação rodam na coleta; a geração fica no workflow de publicação.

1. `siscam` lista PLs por ano e baixa detalhes novos ou alterados, além da fila de revisão de substitutivos.
   Salva `data/proposicoes/<ano>.json` e a chave `coleta` de `data/meta.json`.
2. `documentos` lista os cinco tipos e baixa detalhes seletivos; salva `data/documentos/<tipo>/<ano>.json`
   e a chave `documentos` dos metadados, inclusive numa interrupção tratada.
3. `sessoes` lista sessões e baixa detalhes; salva `data/sessoes/<ano>.json` e a chave `sessoes`, também numa
   interrupção tratada. Deve vir depois dos documentos para enxugar referências da pauta.
4. `classificar` faz novas chamadas à IA para ementas sem cache válido, quando habilitadas. Grava
   `data/classificacao_ia.json` ao usar IA e a chave `classificacao` dos metadados; a combinação final das
   camadas acontece na geração, não num arquivo de projetos classificados.
5. `validar` confere `data/` e `config/`, inclusive o formato byte a byte de documentos e sessões
   (pastas opcionais), geometria e temporários. Não grava; retorna código 1 se houver problemas.
6. `gerar_site` combina curadoria, regras e cache, calcula métricas e recria `site/`. As páginas principais
   seguem `paginas.NAV`: início, novidades, leis, projetos, atividades, sessões, sem efeito e polêmicas
   (`ruido.html`), análises, busca e metodologia. Também gera `vereadores/*.html`, `feed.xml`, o redirect
   `alertas.html` → `ruido.html`, `404.html`, `dados/*`, estáticos e `.nojekyll`. A 404 usa o template comum,
   prefixo de caminho absoluto extraído de `URL_SITE`, `noindex`, sem canônica, e lista de vereadores da
   legislatura atual.

Execute na raiz, trocando o ano conforme necessário:

```text
python -m coletor.siscam --anos 2026
python -m coletor.documentos --anos 2026
python -m coletor.sessoes --anos 2026
python -m coletor.classificar --sem-ia
python -m coletor.validar
python -m coletor.gerar_site
python -m http.server -d site 8000
```

Para usar só os dados versionados, comece por `validar` e `gerar_site`, sem rede nem chave.
`python -m coletor.validar --textos DIR` confere também hashes, trechos e a barreira de PII do worktree `dados-textos`; os manifestos são sempre validados.

Para regenerar a marca e o favicon após mudar sua geometria, execute separadamente, offline:

```text
python -m coletor.paisagem --marca
```

Para regenerar a textura após atualizar os limites dos bairros, também offline:

```text
python -m coletor.paisagem --textura
```

Para regenerar as máscaras da paisagem e a imagem de compartilhamento após mudar as silhuetas, offline:

```text
python -m coletor.paisagem --camadas --og
```

### Validação da memória

`coletor.validar` também confere `config/memoria.json`; a ausência do arquivo gera aviso. Valida campos,
datas `AAAA` ou `AAAA-MM-DD`, homenageados falecidos, categorias fechadas (`fundacao`, `ciencia`, `artes`,
`musica`, `arquitetura`), fontes HTTPS por pessoa e evento, ids únicos e linha do tempo ordenada.
Exige `data_fim` ≥ `data` e emblema no padrão `^[a-z0-9-]+\.svg$`. Domínio público só é aceito para
fotografia pelo art. 44 da Lei 9.610/98, com `ano_divulgacao + 70 < ano atual`. O formato é JSON com
`indent=1`, UTF-8, LF e normalização NFC.

### Validação dos perfis

`coletor.validar` confere `config/perfis.json`; a ausência gera aviso (suplentes ficam sem partido e as fichas,
sem perfil). Chaves de `vereadores` são o nome exato do SISCAM em maiúsculas; cada perfil tem só `mandatos`,
`eleicoes`, `camara`, `site`, `redes` e, opcionalmente, `falecimento` e `contatos`. Por mandato: legislatura existente em
`config/vereadores.json`, `partido` não vazio, `votos` inteiro positivo (opcional), `situacao` em
`eleito`/`eleita`/`suplente` e `fontes` HTTPS.
Quem está entre os eleitos da legislatura precisa do mesmo partido do config e não pode ser suplente; quem não
está, só suplente. `eleicoes`, da mais recente para a mais antiga: `ano` 1945–2100, `cargo`, `partido` e
`resultado` não vazios, `uf` com duas letras maiúsculas, `votos` inteiro ≥ 0 ou `null` e `fonte` HTTPS.
`camara`/`site` são HTTPS ou `null`; `redes` usa `instagram`, `facebook`, `x`, `youtube`, `tiktok`, `threads`
ou `linkedin`, com `url` e `fonte` HTTPS: página oficial da Câmara ou do vereador, ou o registro de candidatura
no TSE (`fonte` = `https://dadosabertos.tse.jus.br/dataset/candidatos-<ano>`, como grava `coletor.tse`).
Formato: JSON com `indent=1`, ordem das chaves preservada, UTF-8, LF e NFC.
`falecimento` contém somente `data` (`AAAA-MM-DD` válida, não futura) e `fonte` (`{titulo, url}` HTTPS);
quando presente, a ficha informa a data com link para a fonte, sem alterar as métricas históricas.
`contatos` é lista de `{tipo: telefone|email, valor, fonte}` (HTTPS), com `descricao` opcional não vazia.
E-mail exige endereço completo; telefone, ≥ 8 dígitos e só dígitos/espaços/`()+-`. Não repita `(tipo, valor)`
no mesmo perfil nem entre perfis. O importador TSE preserva contatos e outras chaves não eleitorais.

Contatos publicados pelo próprio mandato em timbre/assinatura são públicos, inclusive celulares e e-mails
pessoais; a mesma regra vale para todos os vereadores. Confirme a fonte antes de incluí-los nas listas
explícitas de perfis/backend. E-mails com domínio público `gov.br`, `jus.br`, `leg.br`, `mp.br`, `def.br` ou
`mil.br` (e subdomínios) não são mascarados; telefones só são liberados pelas listas explícitas.
`python -m coletor.contatos --candidatos --cache DIR [--min-docs 3] [--saida ARQ]` gera apenas proposta
em `.qa/contatos_propostos.json` (ignorada pelo Git); revise/remova candidatos antes de `--aplicar ARQ`.

### Validação dos afastamentos

Cada item de `afastamentos` mantém `siscam`, `legislatura`, `cargo` (cargo ou motivo),
`natureza` (`cargo` para exercício de outro cargo ou `licenca` para licença) e `fonte` HTTPS
obrigatórios. Aceita somente os opcionais `inicio`, `fim`, `aprovacao` (datas ISO válidas dentro da legislatura
ou `null`, com `fim` ≥ `inicio`), `ato` (URL HTTPS do requerimento/ata ou `null`), `evidencia` (`ata`,
`requerimento`, `diario_oficial`, `prefeitura`, `alerj` ou `imprensa`), `suplentes` (lista de nomes SISCAM)
e `nota` (texto factual curto). Fonte sem data é admitida; não invente início a partir da aprovação ou do
primeiro registro observado. `siscam` e `suplentes` precisam estar entre eleitos de qualquer legislatura,
`apelidos` ou chaves de `perfis.json`; só registre suplentes nomeados no documento citado. Novos apelidos
exigem nome encontrado na frequência das sessões. Ordene por legislatura, `inicio` ou `aprovacao` (sem data
primeiro), depois `siscam`. Preserve fontes de divergências nas notas e não duplique o mesmo afastamento.
O abono usa `inicio` ou, na sua ausência, `aprovacao`; sem ambos, não cria intervalo.
Sem `fim`, vai até a véspera do próximo P/C/V em deliberativa da legislatura ou até o fim dela.
Licenças só abonam com `aprovacao` ou `ato`. Presença efetiva é P/C/V ÷ (P/C/V + A):
J/O/L são abonadas e ficam fora da base; J continua contando como exercício nas votações possíveis.

### Validação da Mesa Diretora

A chave opcional `mesa` de `config/vereadores.json` lista `{siscam, legislatura, bienio, cargo, fonte}`, como
`afastamentos`. `coletor.validar` exige campos não vazios e sem extras, legislatura existente, `bienio` `AAAA-AAAA`
com anos consecutivos dentro da legislatura, `cargo` entre Presidente, 1º/2º Vice-Presidente, 1º/2º Secretário e
1º/2º Suplente, `siscam` entre os eleitos da legislatura ou os nomes conhecidos (eleitos de outra legislatura ou
`apelidos`), `fonte` HTTPS (ata ou votação da sessão no SISCAM) e, por biênio, nenhum cargo repetido nem pessoa com
dois cargos. Não invente nomes: quem ainda não está na configuração (como um suplente) entra primeiro em `apelidos`.

### Validação do backend e das remoções

`coletor.validar` confere `config/backend.json` e `config/remocoes.json`; a ausência de cada arquivo gera aviso,
não erro. Ambos usam JSON com `indent=1`, ordem das chaves preservada, UTF-8, LF, quebra final e NFC.
O backend aceita só `api_url` (URL HTTPS sem barra final, consulta nem fragmento ou `null`; caminho permitido),
`origens_cors` (lista não vazia de origens HTTPS únicas em minúsculas, `https://host[:porta]`, sem ponto final
no host, porta padrão `:443`, caminho, consulta, fragmento nem barra final) e `contatos_institucionais`. Cada contato tem
somente `tipo` (`telefone` ou `email`), `valor`, `descricao` não vazia e `fonte` HTTPS; e-mail precisa ter formato
de endereço e telefone admite só dígitos, espaços, parênteses, `+` e `-`, com pelo menos oito dígitos.
Não repita o par `(tipo, valor)`.

Remoções têm somente a lista `remocoes`, ordenada por `(data, chave, sha256)`, sem pares `(chave, sha256)` repetidos. Cada item
contém exatamente `chave` (`siscam:<IdArquivo>`, inteiro positivo, ou `sessao:<guid>`, GUID em minúsculas,
como em `docs/contratos/textos.md` §2.1), `sha256`
(64 hexadecimais minúsculos), `motivo` não vazio, `fonte` HTTPS e `data` válida `AAAA-MM-DD`, não futura.
O `motivo` é público no Git e não deve conter dados pessoais.

### Opções das CLIs

- Nos três coletores, `--anos` aceita ano ou intervalo inclusivo (`2025-2026`). Padrão de PLs: 2021 até o
  ano atual; documentos/sessões: ano anterior e atual. `--workers` usa `COLETOR_WORKERS` ou 4; em sessões,
  controla só os detalhes, pois a paginação da listagem é sequencial.
- **PLs:** `--forcar` rebaixa os detalhes de todos os PLs listados. `--max-detalhes` (padrão 400) limita
  apenas detalhes pedidos **só pelos substitutivos ou pelos arquivos**, do mais recente ao mais antigo, na
  execução inteira: PL sem a chave `substitutivos`, PL sem lei com substitutivo ainda sem lei ou PL sem a chave
  `arquivos` (só a do próprio PL decide; substitutivo sem ela não recoloca o PL na fila). Mudanças normais da
  listagem e `--forcar` não entram nesse limite. Extras adiados ficam para outra execução; `meta.json` separa
  `por_substitutivos`/`substitutivos_adiados` de `por_arquivos`/`arquivos_adiados`.
- **Arquivos do cache (PLs e documentos):** `--arquivos-do-cache DIR` só preenche `arquivos` a partir de
  `DIR/<id>.html` (PL, cada substitutivo e documento), sem rede nem outros campos, e encerra; respeita `--anos`
  (padrão: todos os anos existentes) e, em documentos, `--tipos`. Sem HTML, o registro fica intocado. Em
  documentos, avisa que ignora `--so-detalhes`, `--sem-detalhe`, `--forcar` e `--max-minutos`. Idempotente.
- **Documentos:** `--tipos requerimento,indicacao,mocao,pdl,resolucao` seleciona os tipos a **relistar**;
  `--max-detalhes` (1500) limita detalhes; `--sem-detalhe` só lista; `--so-detalhes` não relista e atende
  pendentes, sem combinar com `--sem-detalhe` ou `--forcar`. `--forcar` marca os elegíveis relistados para
  rebaixar, ainda dentro do limite. A fila de detalhes inclui **todos os arquivos existentes**, mesmo fora
  dos tipos/anos escolhidos. Portanto `--so-detalhes` não garante esvaziar toda a fila numa execução.
  Requerimentos, PDLs e resoluções com `detalhe_em` e sem `arquivos` também entram nessa fila, por recência e
  dentro do limite; indicações e moções com detalhe não (inteiro teor fora do escopo).
- **Sessões:** `--forcar` marca as sessões listadas para rebaixar; `--max-detalhes` (400) limita a execução,
  mais recentes primeiro. A fila também inclui pendentes de todos os anos existentes.
- **Documentos e sessões:** `--max-minutos N` é um prazo interno positivo, sem prazo por padrão. Para de
  iniciar trabalho, preserva o progresso e deixa o restante para depois. SIGTERM/Ctrl+C tratam a gravação
  parcial e os metadados; não equivalem a interromper à força o processo durante uma gravação.
- **Classificador:** `--sem-ia` impede novas chamadas, sem apagar o cache; `--limite N` limita os projetos
  pendentes enviados à IA (sem limite por padrão). O gerador continua lendo o cache mesmo sem chave.
- **Arquivos:** `python -m coletor.arquivos --reformatar` regrava apenas `data/proposicoes/*.json` e
  `data/classificacao_ia.json`, conferindo antes de qualquer gravação que o conteúdo não muda.
- **Auditoria:** `python -m coletor.regras_sessoes --auditoria` imprime distribuições e problemas, sem gravar.
- **Geometria:** `python -m coletor.geo --entrada bairros-overpass.json`; `--tolerancia` muda o valor inicial
  de 25 m. Veja o contrato de mapas abaixo. Validador e gerador não têm opções próprias de CLI.

Para uma carga histórica de documentos, prefira execuções manuais ano a ano via `anos_documentos`; não
presuma duração fixa. Os pendentes podem ser atendidos depois com `python -m coletor.documentos --so-detalhes`.

Novas chamadas à IA, em POSIX:

```sh
OPENCODE_API_KEY=... python -m coletor.classificar
```

No PowerShell (`pwsh`):

```powershell
$env:OPENCODE_API_KEY = "..."
python -m coletor.classificar
```

Não exponha chaves em commits, exemplos reais ou logs.

### Ambiente

| Variável | Padrão / função |
| --- | --- |
| `COLETOR_USER_AGENT` | Identificação com URL do repositório, compartilhada pelos três coletores do SISCAM. |
| `COLETOR_WORKERS` | `4`; padrão de `--workers`, sobrescrito pela CLI. |
| `OPENCODE_API_KEY` | Sem chave, não há novas chamadas à IA. |
| `OPENCODE_MODEL` | `deepseek-v4.1-flash`. |
| `OPENCODE_BASE_URL` | `https://opencode.ai/zen/go/v1`. |
| `CLASSIFICADOR_LOTE` | `15`; projetos por chamada à IA. |
| `CLASSIFICADOR_CONFIANCA_MINIMA` | `0.75`; limiar de exibição dos alertas da IA. |
| `RADAR_COLETA` | Com `1`, pula testes de comparação com a base versionada e algumas checagens dessa base. |
| `GITHUB_ACTIONS` | Quando não vazia, o validador emite problemas como `::error::`. |
| `GITHUB_RUN_ID` | Se presente, identifica a sessão da IA; fora do Actions, usa identificador aleatório. |

Não há carregamento automático de `.env`. A IA usa `POST /chat/completions`, `Authorization: Bearer`,
`User-Agent` próprio (não `COLETOR_USER_AGENT`) e `x-opencode-session` estável na execução.

## Contratos dos dados do navegador

- `app.js` não busca `dados/projetos.json`: ele é só exportação. Também se gera `dados/vereadores.json`.
  Páginas de consulta embutem `<script type="application/json" id="manifesto-dados">` com o recorte do manifesto;
  `dados/manifest.json` serve para renovação quando o manifesto falta, é inválido ou está desatualizado.
- PLs usam esquema 2: `dic-pl`, `pl-lei`, `pl-andamento`, `pl-sem_exito` e `pl-recentes`, com o mesmo `build`.
  A prévia tem as primeiras 40 linhas e atende `projetos.html` sem filtros; fatias completas são carregadas
  depois da primeira pintura. `dados.js` hidrata o objeto legado de `app.js`. A coluna `ls` é o id do
  substitutivo da lei e vira URL, como `u`; "via substitutivo" usa `ls`, enquanto o número do PL usa `u`.
- Documentos usam esquema 2: `dic-doc` tem só tipos, categorias, subcategorias e URL de detalhe.
  `doc-<tipo>-<ano>[-k]` e `ver/<slug>[-<tipo>][-k]` têm pessoas, situações e bairros locais. Não levam
  `build`: conteúdo e enumerações estáveis determinam os bytes; partes sem mudança mantêm a URL.
  `build_doc` fica no manifesto. O alvo de fatiamento é 120 KiB gzip, com margem de 512 bytes; as primeiras
  partes de tipo/ano usam 24 KiB até cobrir `PASSO_LISTA` e terminar numa troca de data. Uma data só se divide
  se não couber sozinha no orçamento. Partes por autor usam o alvo de 120 KiB.
- URLs dos arquivos do manifesto usam `?v=` com os 10 primeiros caracteres do SHA-1 dos bytes;
  para estáticos, veja a regra de bytes publicados em "O que editar e como gravar".
- `atividades.html` e a seção "Atividade" das fichas usam filtros na URL. Métricas agregadas de documentos
  são HTML/SVG, sem novas colunas nos JSONs e sem reagir aos filtros da lista.
- "Ver no SISCAM" abre `<dialog>` com iframe em sandbox. Só aceite a URL HTTPS exata do host SISCAM e
  `DetalhesDocumentos.aspx?IdDocumento=<n>`; preserve o link "abrir no SISCAM" como alternativa visível.
- Preserve colunas, escape de HTML e os espelhos `PASSO_LISTA`/`PASSO`, `plano_docs`/`fatiasDocs` e as fixtures
  de paridade. Sessões têm contrato próprio, consolidado na próxima seção.
- Toda tabela fica em `div.tabela-rolavel[role=region][tabindex=0][aria-label]`, com rótulo acessível único
  na página e foco por teclado. Exceções: os wrappers `tabela-resumo` e `faixa-rolagem`, que preservam seus
  próprios `role="region"`, `tabindex="0"` e rótulo (`aria-label` ou `aria-labelledby`).
- Tabelas empilham em vez de rolar: toda `<table>` sai pelos auxiliares de `graficos.py` (`abre_tabela`,
  `fecha_tabela`, `cab_coluna`, `cab_linha`, `celula`, usados por `tabela`, `paginas.tabela_resumo` e a faixa
  de sessões) com classes `empilha col-N` (N colunas), papéis ARIA explícitos (`table`, `rowgroup`, `row`,
  `columnheader`, `rowheader`, `cell`) e `data-label` em toda célula do corpo, igual ao texto do cabeçalho
  da coluna (no cabeçalho de linha, o da primeira coluna). Os wrappers são contêineres (`container-type:
  inline-size`); no fim de `estilo.css`, `@container (max-width: …)` por faixa de `col-N` transforma cada linha
  em cartão: `thead` fora da tela como `.so-leitor` (nunca `display: none`), cabeçalho de linha como título e
  `td::before` com `attr(data-label)`. Regras genéricas, sem CSS por tabela. Os wrappers mantêm
  `overflow-x: auto` só como alternativa sem container queries, e `position: relative`: contêm os spans
  `.so-leitor` absolutos das células; sem o bloco de contenção, eles escapam do recorte e alargam a página.
  Meta: nenhuma tabela com rolagem horizontal a 320, 375 e 414 px. `tests/test_tabelas_empilhaveis.py` confere
  os construtores e `TestGerarSite` confere todas as tabelas do site gerado.

### Partido ao lado do nome

- Todo nome de vereador no site leva `<span class="partido">SIGLA</span>` logo depois do texto do nome, dentro do
  mesmo link ou chip (`paginas.partido_html`, `ptHtml` em `app.js`, `nome()` em `sessoes.js`). A sigla é a do partido
  na legislatura do item (`modelo.partido_em`: projeto, documento, votação ou mandato); em listas sem item, a da
  legislatura atual (404, home) ou a mais recente conhecida (`partido_atual`, título da ficha). Partido desconhecido:
  sem span. Exceções: na lista da home o span fica logo depois do link (`inicio.js` lê o nome do link); nos gráficos
  SVG o partido vai só no tooltip, no `aria-label` e na tabela alternativa (`graficos.com_partido`), não no rótulo.
- O partido é o da eleição (`config/vereadores.json`) para eleitos e o de `config/perfis.json` para suplentes.
  No navegador: `dic-pl.pessoas` já tem `{legislatura: partido}`; nas partes de documentos a pessoa local ganha
  o partido como quarto campo, e nas de votações (`vot-<ano>`) como quinto, só quando conhecido (sem mapas de
  partido por pessoa). Sem partido, a marcação é idêntica à anterior, e as fixtures de paridade não mudam.
- A ficha tem `section.perfil` depois do título: partido e votos por mandato (mais recente primeiro), outras
  eleições, página na Câmara, site e redes oficiais, e as fontes; linhas sem dado são omitidas. Links externos
  seguem a regra geral (sem nova aba; só os detalhes do SISCAM abrem em nova aba).

### Home e interações acessíveis

- Cada ficha publica “Resumo em números” depois do perfil, por legislatura (mais recente primeiro),
  em `coletor/site/resumo.py`: funções puras, frases e ordem fixas para todos, sem IA, adjetivos ou comparação
  entre vereadores. Reusa `mandatos.linhas_mandatos` para sessões em exercício, meses estimados e cargos com
  fontes; presença efetiva e faltas, PLs como autor principal e leis, tipos de documentos, três bairros das
  indicações (empates alfabéticos) e votos vêm do modelo. Percentuais exigem base ≥ 10; nas nominais a base é
  possíveis menos presidindo. Ausência de registro não significa ausência de trabalho. A metodologia está em
  `metodologia.html#resumo`; `tests/test_resumo.py` e `TestGerarSite` conferem números e neutralidade em todas
  as pessoas da base, com `PALAVRAS_PROIBIDAS`. Não acrescentar inferências, médias ou frases personalizadas.

- `analises.html#mandatos-atividade` publica uma tabela alfabética por legislatura, incluindo suplentes em exercício,
  sem faixas de carreira, correlação ou comparação entre grupos. `coletor/site/mandatos.py` conta vitórias para
  vereador cujo resultado começa por “Eleito”, até o ano eleitoral do recorte; a ficha mostra todos os anos registrados.
  Meses estimados = intervalo das deliberativas em dias ÷ (365,25/12) × (presença `listadas` / total incluído).
  A cobertura vem de `modelo_sessoes.exercicio`; não usar o denominador efetivo como tempo em exercício.
  Percentuais exigem base ≥ 10; taxas mensais, meses positivos. Valores ausentes ficam vazios nos `data-*` e por último
  na ordenação. Controles de ordem/filtro de cargos só aparecem após inicialização do JS; sem JS, todas as linhas ficam visíveis.

- A home segue a ordem hero → “Quem é meu vereador?” → números → destaques → mapa → placar → linha do tempo
  → faixa “Niterói que nos inspira” → convites. Blocos sem dados podem ser omitidos. `inicio.css` e `inicio.js`
  são carregados só na home; sem JavaScript, permanecem a lista de vereadores em `<details>` e os números reais do servidor.
- Tooltips abrem por hover ou foco; alternar por toque exige `pointerType === "touch"`. Fecham com Esc,
  interação fora, saída do foco ou rolagem. `aria-describedby` fica nos links focalizáveis, nunca se adiciona
  `tabindex` às marcas dos gráficos. Gráficos com links usam `role="group"`, não `role="img"`.
- Autoria usa `<div class="cartao-autor">` ou `<div class="autoria">`, com `<details class="coautores">`
  para os demais nomes; não envolva esses blocos em `<p>`. Preserve a paridade da marcação Python/JavaScript.
- As abas do placar seguem APG: `tablist` sai com `hidden` e o JavaScript o revela; setas, Home/End e
  `tabindex` móvel controlam seleção e foco. Os painéis saem como `<section>` sem `hidden`, `role` ou `tabindex`,
  com `h3.titulo-legislatura` visível sem JavaScript. Ao revelar as abas, o JS acrescenta `role="tabpanel"`,
  `tabindex="0"` e `aria-labelledby`, para manter todas as legislaturas legíveis sem JS.
- “Mostrar mais” nas listas de PLs, documentos e votações leva o foco ao primeiro item novo e anuncia
  a inclusão numa região `aria-live="polite"`, inclusive quando o botão desaparece no último lote.

### Cabeçalho, tema e metadados

- `paginas.SCRIPT_CABECA` roda inline antes do CSS: adiciona `js` só com `matchMedia` e `addEventListener`,
  e aplica `localStorage['radar-tema']` se for `claro` ou `escuro`. Cabe em 400 bytes; os testes comparam
  seu conteúdo byte a byte com a constante de `tests/js/tema.test.js`.
- Abaixo de 760 px, sem JS, a navegação é uma grade de duas colunas com links de altura mínima de 44 px.
  Com `js`, começa recolhida no próprio CSS, sem salto de layout. O `onerror` de `navegacao.js` e os retornos
  sem menu funcional removem `js`, restaurando os links. Clique fora fecha; `focusout` fecha ao sair do
  cabeçalho só sem pressão de ponteiro em curso; Esc fecha e devolve o foco ao botão Menu.
- `.tema` tem três botões com `aria-pressed`: Automático, Claro e Escuro; fica oculto sem JS.
  `navegacao.js` cuida do menu e do tema, separado de `app.js`. Preserve um listener por tipo no documento
  em cada script. A ordem dos scripts com `defer` é `navegacao.js` → `dados.js` → `app.js` → extras.
- `pagina()` recebe `caminho` e `indexavel`: canônica e `og:url` usam `URL_SITE` + caminho (`index.html`
  vira a raiz); com `indexavel=False`, saem ambas e entra `noindex`. O template também emite `og:type`,
  `og:site_name`, `og:locale`, `twitter:card` e `theme-color` claro/escuro. Com `og-radar.png` disponível,
  toda página do template recebe `og:image` (URL absoluta com `?v=`), largura, altura, texto alternativo
  e `twitter:image`. `estilos=` recebe uma tupla de CSS extras por página, versionados e inseridos após
  o CSS global quando existem. O redirect `alertas.html` é separado e não recebe esses metadados.
- View Transitions usam `@view-transition` sob `prefers-reduced-motion: no-preference`, com os nomes
  `marca` no cabeçalho e `titulo` no título de abertura ou hero.

### Tokens e fontes

- Os tokens de cor do contrato são literais hexadecimais de seis dígitos em `:root`, no bloco `@media`
  escuro e em `:root[data-theme="dark"]`, nunca `var()`. Não use hexadecimais em `[data-theme="light"]`.
  `tests/test_design_tokens.py` verifica os pares WCAG declarados; preserve esses contrastes.
- Use em todos os componentes os tokens de `site_src/estilo.css`: `--fs--1` a `--fs-6` (escala de razão
  1,2 com `clamp()`), `--esp-1` a `--esp-8`, `--raio-*`, `--sombra-*`, `--dur-*` e `--ease-mar`.
  Texto auxiliar tem mínimo de `.8125rem` (`--fs--1`) e entrelinha ≥ 1,4. A exceção são os rótulos de
  12 px em unidades do viewBox na `.svg-box`, identificados pelo comentário `/* exceção de tamanho: … */`;
  a faixa de votos de sessões não tem essa exceção.
- Fontes são auto-hospedadas em `site_src/fontes/`, com `font-display: swap`. Não carregue fontes de
  terceiros; o carregamento via Google Fonts foi removido. Preserve as licenças OFL junto aos arquivos.

### Responsividade e meios de saída

- Nas grades autoajustáveis, use `minmax(min(100%, Npx), 1fr)`, sem mínimos fixos > 288 px.
  A meta é nenhuma rolagem horizontal da página a 320 px; confira com Playwright na QA. As tabelas
  empilham em cartões conforme o contrato acima, sem rolagem horizontal própria a 320, 375 e 414 px.
- Alvos de toque dos controles principais têm ≥ 44 px; chips, tags e `.ver-siscam`, ≥ 24 px.
  No desktop, navegação e tema podem ampliar a área de toque por pseudoelementos sem ampliar o desenho.
- A textura decorativa fica em `body::before`, com `mask-image` de `textura-bairros.svg`,
  `background-color: var(--tinta)` e opacidade ≤ .06; fica oculta na impressão e em cores forçadas.
- Em `@media (forced-colors: active)`, preserve bordas visíveis e foco com `Highlight`. As cores de dados
  só são preservadas com `forced-color-adjust: none` nas amostras, barras, marcas dos gráficos e mapa,
  não no texto ou nos cartões inteiros.
- Na impressão, mantenha texto preto sobre branco, sem textura nem sombras e com os controles ocultos.

### Orçamentos (gzip, salvo indicação contrária)

| Objeto | Limite ou alvo |
| --- | --- |
| JSON inicial de cada página | 200 KiB, soma dos arquivos previstos sem filtros. |
| Manifesto, dicionários e arquivos de PL | 200 KiB por arquivo buscado. |
| Parte de documentos (`doc-*`, `ver/*`) ou votações (`vot-*`) | 150 KiB por arquivo. |
| HTML, inclusive home, fichas e `sessoes.html` | 100 KiB por página. |
| Carga da home (`index.html`, CSS/JS e máscaras em gzip, WOFF2 em bytes brutos) | Até 300 KiB. |
| Apresentação de `sessoes.html` | Alvo de 60 KiB nos dados reais, não teto imposto pelo gerador. |
| Seção individual de sessões | Até +10 KiB, verificada em teste sintético. |
| `sessoes.js` | Até 12 KiB, testado offline. |
| `navegacao.js` | Até 4 KiB. |
| `inicio.js` | Até 6 KiB. |
| `busca.js` | Até 6 KiB; carregado só em `busca.html`. |
| CSS global (`estilo.css` publicado) | Até 16 KiB, testado em `tests/test_responsivo_css.py`. |
| Script inline `paginas.SCRIPT_CABECA` | Até 400 bytes **brutos**. |
| `favicon.svg` e `marca.svg` | Até 2 KiB **brutos** cada. |
| `textura-bairros.svg` | Até 12 KiB; distância de simplificação fixa, sem ajuste pelo compressor. |
| Camadas da paisagem (`paisagem/*.svg`) | Até 18 KiB somadas. |
| Emblemas (`memoria/*.svg`, exceto azulejo) | Até 6 KiB cada. |
| `memoria/azulejo.svg` | Até 12 KiB. |
| Mapa individual de indicações completo | Até 12 KiB, medidos deterministicamente na geração. |
| Geometria `data/geo/bairros.json` | Até 60 KiB **brutos**, conferidos pelo conversor. |

O gerador imprime tamanhos brutos/gzip, soma e máximo das famílias e avisos `::warning::` para os tetos
oficiais de HTML/JSON/carga inicial. Não confunda esses tetos com alvos de apresentação; os testes do mapa
de votos também têm um cenário sintético de até 65 KiB para a página com mapa.
`tests/test_gerar_site.py` (`TestGerarSite`) confere no site recém-gerado o teto de 100 KiB por HTML,
a varredura de acessibilidade (sem bloco em `<p>`, sem focável em `role="img"`, abas) e a do glossário.

## Sessões: coleta, regras e apresentação

Esta é a referência única para sessões; a CLI está em "Pipeline e comandos" e a operação em "CI/CD".

### Registros coletados

- Lista `ResultadoSessao.aspx?Ano=<ano>&pagina=<n>` em sequência, 10 por página, sem total; detalhe em
  `DetalhesSessao.aspx`. Guarda observações, documentos da sessão (rótulo/arquivo), pauta com fase e prioridade,
  frequência por momento (como "Abertura - 14:10") e votações com totais e votos nominais.
- Para em página curta, vazia ou fora do intervalo. O SISCAM pode devolver a página 1 além da última;
  detecte pelo paginador `currentPage` e ids repetidos. Página 50 cheia (`PAGINAS_MAX`) marca a listagem
  incompleta, com aviso. Falha ou listagem menor preserva sessões anteriores por id.
- A pauta conhecida guarda `id_documento`, `fase`, `prioridade`, `secao` e `secao_indice` (posição em
  `documentos_sessao`, pois rótulos podem se repetir). Tipo, número, ano e ementa vêm dos documentos por id.
  Se o id falta ou não está nos arquivos na coleta, guarda também `tipo_documento`, `numero`, `ano`, `ementa`.
  `ids_conhecidos` lê uma vez os ids dos registros de PLs/documentos, não os de seus substitutivos.
  Votações continuam guardando `documento`, `tipo_documento`, `numero`, `ano`; sem link, o id é `null`.
- O id de pauta/votação é de `DetalhesDocumentos.aspx`; o id da própria sessão é de outra numeração.
  Não os compare. Se um documento de pauta enxuta sumir da base, perde-se sua descrição; recupere com
  `python -m coletor.sessoes --anos <ano> --forcar`, dentro dos limites: o item volta completo se o id
  deixar de ser conhecido e a informação ainda estiver no SISCAM.
- Rebaixa detalhes novos, ausentes, pendentes, com cabeçalho alterado ou sessões recentes (até 60 dias,
  incluindo futuras), além de `--forcar`. Na janela recente, dispensa nova tentativa se `detalhe_em` é hoje
  e posterior à data da sessão. Sessões antigas sem mudança **não** viram pendentes só por não rebaixar;
  a marca fica nas que precisam de detalhe e foram adiadas ou falharam.
- Preserve textos brutos: frequência, voto e resultado não são interpretados na coleta. Nomes repetidos
  continuam nas linhas e em `nomes_repetidos` da votação ou `frequencia_nomes_repetidos` da sessão, omitidos
  se vazios, com aviso em stderr. Não separe cargos do nome sem evidência de layout; deduplique nas métricas.
- Rótulo de seção sem a linha esperada (`trVotacoes`, `trFrequencia`, `trDocumentosSessao`) é layout alterado.
  Para documentos/votações, também se confere a grade principal, salvo indicação de "Nenhum Registro";
  frequência não tem essa checagem de grade. O detalhe fica pendente, sem substituir o anterior.
  Ordinária/extraordinária sem frequência, totais divergentes ou rótulos de total desconhecidos só avisam.
- Uma lista antes preenchida que venha vazia mantém os itens antigos, com aviso. O `ano` é o da listagem;
  título de outro ano só avisa e permanece em `titulo`. Sem tipo identificado, usa `desconhecido`, com aviso.
  A ordem no arquivo é data, hora, número e id. `detalhe_em` só muda quando o conteúdo muda.

### Interpretação e HTML

- Só deliberativas (ordinárias/extraordinárias) com lista entram na presença. O denominador é individual,
  com presença efetiva P/C/V ÷ (P/C/V + A), sem J/O/L e textos desconhecidos nem faltas inventadas para nomes
  ausentes. Cada pessoa conta uma vez,
  pela melhor evidência; ausência com voto substantivo na sessão pode virar presença identificada como V.
  Com base menor que 10, não há percentual; a mediana considera eleitos com base suficiente.
- Desde `2026-10-27` (`pagina_sessoes.CRITERIO_PRESENCA_DESDE`), justificadas (J), abonadas por outro cargo (O)
  e licenças (L) ficam fora da base efetiva. A barra separa P/C/V/A de J/O/L por um corte de 2 px e usa texturas
  e rótulos além das cores. A tabela empilhável de dez colunas conserva a presença bruta P/C/V ÷ (P/C/V + A + J + O)
  para comparação, também com mínimo de dez na própria base. As fichas contam só A em “Faltas não abonadas”.
- Favor/Contra é sobre o parecer, não automaticamente a matéria. Use `regras_sessoes` para determinar o
  sentido e o quórum: derrubar veto exige 11 votos dos 21 vereadores, não maioria dos presentes.
  Sentido inseguro aparece como não determinado; placar inconsistente só mostra totais oficiais, sem nomes.
  Contar presença/votos não mede qualidade; abertura não mede permanência e cobertura incompleta limita comparações.
- `modelo_sessoes` agrega sem criar páginas para suplentes reconhecidos nas sessões. Sem página, mostre
  nome e "suplente em exercício", sem link. Preserve os critérios das regras e a metodologia publicada em
  `metodologia.html#sessoes`, inclusive qualidade, duplicatas e nomes não associados aos membros.
- Sem `data/sessoes`, gere estados vazios. Com dados, `sessoes.html` e "Presença e votos" nas fichas mantêm
  HTML estático: presença por legislatura, divididas (40 cartões iniciais, resto em `<details>`), mapa de
  votos do último ano com divididas, placares anuais, ritmo e qualidade. Não há indicador leitura→votação no site.
- A ementa do cartão de votação só é limitada a duas linhas sob `.js`. `sessoes.js` acrescenta “Ver ementa
  completa” quando há mais de 180 caracteres ou corte visual; o botão alterna `aria-expanded` e expande
  o mesmo texto, sem duplicá-lo. Sem JavaScript, a ementa aparece inteira.

### JSON e melhoria progressiva

- Só quando há votações, exporte `dic-ses` e `vot-<ano>`, esquema 1 dentro do manifesto 2. Não levam `build`;
  `build_ses` fica no manifesto. Uma parte anual sem mudança mantém seus bytes e URL por conteúdo.
  `dic-ses` usa os rótulos de `regras_sessoes.rotulo_voto`. Votos ficam em colunas, com pessoas locais e
  um caractere por pessoa; `.` é "não consta", diferente de ausência ou voto indeterminado.
- O manifesto embutido lista os anos com votações e inclui `build` global e `build_ses`, sem exigir `build`
  nos arquivos de sessões. Sem consulta, o carregador usa esse manifesto e busca dicionário + ano mais
  recente, como no relatório, sem buscar `dados/manifest.json`; só o dicionário tem preload fixo.
- `sessoes.js` controla só a página de sessões. `app.js` fornece `RadarArquivos.carregar/manifesto`, com cache
  e renovação compartilhados, sem iniciar listas genéricas nos formulários de sessões.
- Revele os formulários por legislatura, mantenha filtros via `history.replaceState` (`leg`, `ano`, `classe`,
  `materia`, `vereador`, `div=1`, `q`, `ordem`, omitindo padrões) e paginação de 40. `div=1` exige vereador
  e comparação determinada. "Apertadas" usa margem absoluta Favor/Contra, não quórum legal.
- Sem consulta, preserve cartões e notas técnicas do servidor. Filtros, Mostrar mais e CSV pedem o recorte
  completo necessário pelas URLs do manifesto. Escolher ano refaz a faixa; "todos" restaura a faixa inicial.
  `tr[data-vereador]` preserva a composição do servidor e permite destaque sem promover nomes brutos.
- Preserve `cartao_votacao`/`_mapa_votos`, rótulos e a paridade de `tests/js/fixtures/sessoes.json` com
  `faixa_sessoes.html` e `cartao_sessoes.html`, conferida por Python e JS. Referências abreviadas e nomes
  curtos vêm do JSON; notas técnicas ficam só no HTML inicial e em Qualidade dos dados.
- A faixa (`<table class="faixa empilha col-N" role="table">`, com `faixa-larga` antes de `empilha` acima de
  12 colunas, `pagina_sessoes.FAIXA_LARGA`) e o resumo por vereador saem iguais de `pagina_sessoes._mapa_votos`
  e de `sessoes.js` (`faixa`): papéis ARIA e `data-label` com a referência curta do cabeçalho (`"25/03 PL 280"`,
  nunca o título longo do `<abbr>`). O rótulo da região é neutro (“Mapa de votos de <ano>, legislatura …:
  vereador × votação dividida”), sem mencionar rolagem. Abaixo de 56rem de contêiner (100rem com `faixa-larga`,
  que não cabe nem no desktop), cada vereador vira um cartão com ladrilhos rotulados
  (`repeat(auto-fill, minmax(5.5rem, 1fr))`); ladrilhos `.voto-vazio` somem só no cartão, e quem só tem células
  vazias fica com o nome. A faixa fica fora do limiar genérico de 9 colunas ou mais. A regra da primeira coluna
  fixa (`.sessoes .faixa tr > :first-child` com `position: sticky; left: 0`) vale para a matriz larga e para
  navegadores sem container queries.
- CSV é UTF-8 com BOM e fórmulas neutralizadas; inclui "não consta" no produto pessoa × votação filtrada.
  Em inconsistentes, não atribui votos a pessoas, assim como os cartões. Não confunda filtrar por vereador
  (selecionar votações) com exportar somente as linhas dessa pessoa.

## Projetos de lei e novidades

- Ao baixar detalhe de PL, colete os substitutivos da seção própria: id, número, data, situação, autoria,
  tramitação e lei. Se a lei sai do substitutivo e não do PL, aplique-a ao PL com `desfecho: virou_lei`
  e `lei_substitutivo` apontando para ele. Preserve autoria principal do PL; autores adicionais do substitutivo
  que virou lei entram como coautores no modelo, sem duplicar nomes.
- Chave `arquivos` (PL, cada substitutivo e documentos com detalhe): lista, na ordem da página, de
  `{id, descricao, versao, data, icone}` da tabela "[ Arquivos ]" (`coletor/arquivos_siscam.py`); `id` é o
  de `Download.aspx?id=`, `data` é `AAAA-MM-DD` ou `null` e `icone` vem da imagem (`doc`, `pdf`; vazio sem
  imagem). Ausência da chave = ainda não coletado; `[]` = página sem arquivos ("Nenhum Registro" ou sem seção).
  Lista nova vazia não apaga uma anterior não vazia (aviso); seção sem grade é layout alterado e mantém o
  detalhe anterior como falha. Relistar documentos preserva a chave como os demais campos do detalhe.
- Categoria combina curadoria → regra → IA. Curadoria pode corrigir campos; categoria simbólica zera impacto,
  autorizativa limita impacto avaliado a 1. IA avalia só ementa; não trate estimativa como efeito comprovado.
- Novidades são derivadas na geração, sem estado entre coletas nem `data/novidades.json` ou JSON próprio no
  navegador: `data` do PL, `lei.data` e `marcos_tramitacao` (chave `marcos` no modelo), no PL/substitutivos.
  Veto usa a Data Resposta; derrubada usa Data Resposta ou, faltando, Enviado em do passo de plenário.
  Exija confirmação no mesmo documento (`VETO REJEITADO`, `VETO DERRUBADO` ou `lei.tipo: veto_derrubado`);
  `VETO MANTIDO`/desfecho `vetado` não confirmam. "Votos pela derrubada" não é resultado de derrubada.
- A semana mais recente é a ISO da última data válida dos eventos, não a do relógio. Datas posteriores ao
  dia de `coleta.em` dos metadados, em Brasília (UTC−3), são ignoradas quando esse limite está disponível.
  A página mostra 12 semanas; RSS 2.0, os 100 eventos mais recentes, `guid` fixo por tipo/id/data, links
  absolutos sobre `URL_SITE` e `lastBuildDate` da última data. Lei via substitutivo aponta para ele.
  Mesma entrada, mesmos bytes. Polêmicas ficam fora porque curadoria/cache não têm data de evento.
  Páginas do template comum levam `<link rel="alternate" type="application/rss+xml">`; o redirect é separado.

## Documentos e métricas

- Detalhe só para requerimentos, PDLs, resoluções ou múltiplos autores; indicações/moções de um autor ficam
  com a listagem. Preserve autoria com papéis, tramitação completa, processo e protocolo quando disponíveis.
  A fila é global, por recência; falhas/adiamentos mantêm detalhe anterior e `detalhe_pendente: true`.
- `regras_documentos.py` é a única fonte das regras; `modelo.py` só agrega. Categoria/subcategoria usam
  ementa normalizada, com `assunto` como apoio. Bairro das indicações é o último bairro oficial citado.
  Categoria, bairro e `respondido` são derivados na geração, sem IA ou rede.
- A coleta deriva `respondido_em`/`dias_ate_resposta` e `publicacao` (número/data de PDLs/resoluções) da
  tramitação completa. Resposta usa o Enviado em do primeiro passo "Respondido", não a Data Resposta de
  qualquer passo nem necessariamente o dia da resposta do Executivo; dias contam do protocolo ou data do documento.
- `eixos_perfil` é a única regra do perfil. Homenagem é a categoria `homenagem`: aplauso (inclusive
  congratulação) e pesar, títulos e honrarias em PDLs/resoluções; repúdio, apoio e sustação de homenagem não contam.
  Peso é contagem e % da produção do mesmo período: documentos do autor + PLs como autor principal;
  para a Câmara, documentos e PLs de qualquer autor. Só usa anos que `anos_coleta` marca como completos:
  **cada um dos cinco tipos tem ao menos um registro**, não uma garantia de cobertura integral ou detalhe completo.
  Calcule `anos_coleta` uma vez em `montar_modelo`.
- `extrair_orgao` prefere o primeiro órgão específico na ementa, depois no assunto; órgão estadual só como
  destinatário. Depois tenta "Concessionária não especificada", "Prefeito ou Poder Executivo" e "Não identificado".
  Não infira o órgão do destinatário da tramitação, que é caminho de encaminhamento do pedido.
- `estado_pedido` separa respondido, aguardando, encerrado e retirado. Taxa exclui retirados; encerrados
  contam como sem resposta. A mediana usa só respondidos com dias disponíveis no detalhe, exibindo essa base.
- Homenagens ficam em `ruido.html`; informação por vereador/órgão e indicações por bairro, em `atividades.html`;
  as três métricas aparecem em "Atividade" nas fichas. São tabelas e gráficos de agregados no servidor.

## Geometria e mapas de indicações

- Atualização offline separada da coleta semanal: `coletor.geo` lê JSON Overpass com `out geom`, relações
  `boundary=administrative`, `admin_level=10` de Niterói (relação 2220789; consulta no README).
  Exija os 52 nomes de `BAIRROS_NITEROI`, com normalização e variantes cadastradas; faltas, sobras e
  duplicatas abortam. Preserve timestamp da base, atribuição e ODbL; não edite a saída à mão.
  Após regenerar a geometria com `coletor.geo`, execute `python -m coletor.paisagem --textura`.
  A textura decorativa deduplica bordas compartilhadas; toda página que a usa mantém atribuição OSM
  visível no rodapé, com a data da base extraída do `<desc>` do SVG.
- Encadeie ways por pontas exatas, invertendo se preciso, respeitando outer/inner, sem fechar lacunas à força.
  Projeção equiretangular local em metros usa o cosseno da latitude média dos extremos; não é mapa cadastral.
  Simplificação Douglas–Peucker por way compartilhado preserva pontas e mínimo lexicográfico; anéis fechados
  são divididos antes do DP. SVG usa `evenodd` para buracos. Descarte recortes menores que 400 m²/invisíveis;
  arredonde para inteiros em viewBox de largura 1000, altura proporcional e margem.
- Anel degenerado/cruzado reduz tolerância global, até zero, ou aborta sem sobrescrever a geometria anterior.
  A CLI começa em 25 m por padrão e pode aumentar até 100 m para caber em 60 KiB brutos; informa tolerância
  usada e tamanhos bruto/gzip. Mesma entrada/opções, mesmos bytes, sem rede/relógio. Isso não substitui
  validação topológica cadastral; valide e gere/inspecione o site antes de versionar a saída.
- O mapa reusa os agregados das indicações. Geometria é opcional; se ausente, ficam gráficos/tabelas;
  se inválida, a geração falha em vez de mostrar mapa enganoso.
- SVG sem JS, título/descrição, títulos por bairro e tabela dos 52 bairros. Até cinco quantis dos positivos,
  menos com poucos valores distintos, sem separar empates; zero hachurado quando presente. Arredonde cortes
  só entre observações, sem mudar grupos ou criar classes vazias. Legenda mostra limites e contagem de bairros;
  cores com limites diferentes não são comparáveis. Informe valores absolutos, sem população, bairro inferido
  da ementa e % sem bairro fora do mapa. Não representam pedidos atendidos.
- Na ficha individual, o bloco completo (SVG, legenda, tabela e atribuição) só entra se couber em 12 KiB gzip;
  se não, ficam tabelas por legislatura. Verifique a medição; não presuma o resultado pela data da geometria.
- Fonte: © contribuidores do OpenStreetMap, ODbL 1.0, https://www.openstreetmap.org/copyright.
  Preserve atribuição visível e data da base em **todo** mapa, inclusive individual; não apresente limites
  simplificados como confirmação municipal. Código do projeto: GPL-3.0, conforme `LICENSE`.

## CI/CD

- `testes.yml`: PRs, pushes fora de `main` e workflow reutilizável. Python 3.12/Node 22; testes Python,
  `coletor.validar`, testes JS e geração. Retorna o SHA do checkout aprovado para a publicação.
- `coleta.yml`: cron `17 9 * * 1` (segunda, 09:17 UTC/06:17 Brasília) ou manual. Inputs `anos`,
  `anos_documentos`, `anos_sessoes` vazios mantêm os padrões das CLIs; `forcar` vale para os três coletores,
  sem aumentar workers ou limites. Ordem e limites do job (350 min):
  1. `siscam`: passo de 90 min.
  2. `documentos`: `continue-on-error`, passo de 120 min, `timeout --kill-after=2m 110m`, `--max-minutos 100`.
  3. `sessoes`: `continue-on-error`, passo de 30 min, `timeout --kill-after=2m 25m`, `--max-minutos 20`.
  4. `classificar`: passo de 90 min; secret `OPENCODE_API_KEY`, variável opcional `OPENCODE_MODEL`
     (se vazia, é removida do ambiente para usar o padrão).
  5. Validação e testes Python com `RADAR_COLETA=1`.
  Se validação/testes falharem, restaura documentos/sessões versionados, remove novos arquivos dessas pastas
  e temporários e **repete validação e testes**. Falha na reserva impede commit; estatísticas dessas etapas
  em `meta.json` permanecem. Só com uma dessas barreiras aprovada faz `git add data`, commit como
  `github-actions[bot]`, `git pull --rebase` e push. Em falha (`failure()` ou reserva falha), preserva `data/`
  inteiro como artefato por 14 dias; uma execução sem mudanças não cria artefato só por não haver commit.
- `site.yml`: pushes em `main` nos caminhos `coletor/**`, `config/**`, `data/**`, `site_src/**`, `tests/**`,
  `.github/workflows/site.yml` ou `testes.yml`; também manual e após coleta bem-sucedida.
  Chama testes sobre `main`, gera no SHA retornado e confere o checkout antes de publicar no Pages.
  Pages deve usar a fonte GitHub Actions. Geração e publicação têm permissões separadas.
- Coleta e publicação usam `cancel-in-progress: false`; não interrompa coleta em andamento sem necessidade.

## Curadoria e neutralidade editorial

- Toda entrada em `config/curadoria.json` precisa de `fontes` públicas, com pelo menos uma URL verificável.
  Use o número do PL em `projeto` (ex.: `1/2022`) e nota factual apoiada nas fontes.
- Aplique os mesmos critérios a qualquer autor, partido ou espectro político, inclusive nas regras dos
  documentos. Não crie exceções partidárias.
- Na memória, o critério é: "Não homenageamos quem exerceu mandato eletivo ou função executiva na direção
  de partido político. Cargos coloniais, títulos honorários e militância pessoal não excluem e são
  mencionados com neutralidade." Cada fato precisa de fonte pública HTTPS; as mesmas regras valem para todos.
- Curadoria prevalece sobre IA; `substitui_ia: true` suprime seus alertas naquele projeto. Use `corrige`
  para correções documentadas em vez de alterar os dados coletados.
- Nomes `siscam` em `config/vereadores.json` devem corresponder exatamente ao SISCAM, em maiúsculas.
  Preserve partido da eleição, fontes das legislaturas e registros de afastamento.
- `config/perfis.json` usa os mesmos campos para todos os vereadores, com fonte pública HTTPS para cada fato
  (votação e partido da eleição, eleições do TSE). Links de redes sociais só entram quando declarados numa página
  oficial (da Câmara ou do próprio vereador) ou no registro de candidatura ao TSE (declaração a órgão oficial;
  `fonte` = URL do conjunto de dados do TSE daquele ano), registrada em `fonte`; não inclua perfis não oficiais
  nem omita links oficiais de alguém por critério político.
- Não confunda impacto estimado e resultado comprovado. Preserve limitações e contestação por issue;
  contar documentos, presença ou votos não mede qualidade nem resultado.

## Convenções e cuidados com o SISCAM

- Identificadores, docstrings, comentários e mensagens em português; preserve nomes de APIs externas.
- Inclua `from __future__ import annotations` nos módulos Python; use tipos modernos (`list[str]`, `str | None`).
  Quatro espaços, funções/campos em `snake_case`, constantes em maiúsculas, datas ISO 8601 e separadores
  de seção como `# ---- nome`, com traços estendidos conforme o módulo.
- Avisos usam `print(..., file=sys.stderr)` e `::warning::` quando devem virar anotação no CI.
- Preserve escape de HTML, tabelas acessíveis, navegação por teclado e restrição de URL do diálogo SISCAM.
- Mantenha User-Agent identificável, timeout e tentativas com espera progressiva. Padrão de concorrência: 4;
  evite `--forcar` e aumento de paralelismo sem necessidade. Respeite limites de detalhe/prazo.
- SISCAM pagina até 50 (10 registros/página); preserve faixas de número `FAIXA = 400` em PLs/documentos.
  Sessões paginam por ano, sem faixas; seus cuidados de paginação estão no contrato de sessões.
- Parsing é frágil (regex, divisões e parser HTML local): confira HTML real antes de mudar padrões.
  Compare contagens, autoria, situação e tramitação. Não transforme falhas em dados vazios silenciosos;
  preserve anteriores quando a coleta falhar e investigue avisos de listagem incompleta.

## Testes e verificação

Execute na raiz:

```text
python -m unittest discover -s tests -t .
node --test "tests/js/**/*.test.js"
python -m coletor.validar
python -m coletor.gerar_site
```

- Os testes também podem ser executados com pytest, mas o CI usa unittest, sem instalar dependências.
  Mantenha o glob do Node entre aspas: Node 21+ faz a expansão.
- Testes são offline, sem SISCAM/IA; novos testes devem continuar assim. `RADAR_COLETA=1` pula comparações
  e verificações dependentes da base versionada que podem divergir durante a coleta; não use para ocultar falhas locais.
- Preserve bytes/CRLF das fixtures reais: `.gitattributes` marca `tests/fixtures/**` como `-text`.
  Para layout novo, salve a página real como fixture.
- Não há configuração de linter, formatter ou typecheck no repositório nem etapa dessas ferramentas no CI.
- Para mudanças de pipeline/apresentação, além dos testes/validação/geração, rode os comandos de coleta
  apenas quando necessário e autorizado (eles acessam a rede). Sirva `site/` e inspecione `http://localhost:8000`:
  contagens, JSONs, avisos e relatório de tamanhos, filtros de leis/projetos/atividades/sessões, fichas
  ("Presença e votos" e "Atividade"), novidades/RSS, diálogo, gráficos, tabelas, links, teclado e console.
  Informe o que verificou e o que não executou; testes não substituem inspeção visual.

## Commits

Escreva em português, com inicial maiúscula e frase no imperativo ou na terceira pessoa: “Inclui…” ou “Atualiza…”.
Não use conventional commits, trailers de coautoria de IA nem linhas “Generated with”.
Mantenha a mudança pequena e focada; não misture código com atualização de dados não solicitada.
