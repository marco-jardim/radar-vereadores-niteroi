# Guia para agentes de código

## Visão geral

O Radar dos Vereadores de Niterói é um site estático sobre a produção da Câmara desde 2021: projetos de lei e,
à parte, requerimentos, indicações, moções, projetos de decreto legislativo (PDL) e projetos de resolução.
Os dados vêm do SISCAM. Nos projetos de lei, a classificação combina curadoria, regras e IA via OpenCode Go;
os demais documentos são classificados só por regras, sem IA.
O processamento usa somente a biblioteca padrão do Python: não adicione dependências externas sem perguntar.
O front-end usa JavaScript e CSS puros, sem etapa de build própria, e a publicação é no GitHub Pages.

**Python 3.12+ obrigatório para o código atual**; os workflows usam 3.12.
Há sintaxe da PEP 701: aspas simples reutilizadas dentro de `{}` em `coletor/site/graficos.py` (rótulos do gráfico
de pontos) e barras invertidas dentro de um campo de substituição em `coletor/site/paginas.py` (menu de navegação).
Os testes de JavaScript pedem Node 21+ (o CI usa 22).

## Estrutura do repositório

| Caminho | Responsabilidade |
| --- | --- |
| `coletor/siscam.py` | HTTP, parsing do SISCAM, autoria, tramitação e desfechos dos projetos de lei. |
| `coletor/documentos.py` | Listagem e detalhe seletivo de requerimentos, indicações, moções, PDLs e resoluções. |
| `coletor/regras_documentos.py` | Categorias, bairro, resposta e publicação dos documentos, por regras determinísticas. |
| `coletor/classificar.py` | Taxonomia, regras, prompt, chamadas à IA, cache e curadoria dos projetos de lei. |
| `coletor/arquivos.py` | Gravação atômica dos JSONs de `data/`, com um registro por linha. |
| `coletor/validar.py` | Validação de `data/` e `config/`, sem alterar nada. |
| `coletor/gerar_site.py` | Entrada da geração; exporta os JSONs do navegador, o manifesto e o relatório de tamanhos. |
| `coletor/site/modelo.py` | Enriquecimento, pessoas, mandatos, métricas, projetos repetidos e documentos por autor. |
| `coletor/site/graficos.py` | Gráficos SVG com tabelas acessíveis. |
| `coletor/site/paginas.py` | HTML, componentes, diálogo do SISCAM e metodologia publicada. |
| `config/vereadores.json` | Legislaturas, eleitos, partidos, apelidos e afastamentos. |
| `config/curadoria.json` | Rótulos e correções manuais com fontes públicas. |
| `data/` | Projetos e documentos por ano, cache da IA e metadados, todos gerados e versionados. |
| `site_src/` | Fontes estáticas: `app.js`, `dados.js`, `estilo.css` e `favicon.svg`. |
| `tests/` | Testes Python (`test_*.py`), JavaScript (`tests/js/`) e HTML real do SISCAM (`tests/fixtures/siscam/`). |
| `.github/workflows/` | Testes, coleta semanal e publicação do site. |
| `site/` | Saída gerada localmente, ignorada pelo Git. |

## Pipeline (coleta → documentos → classificação → validação → site)

1. `coletor.siscam` lista os projetos de lei por ano e baixa detalhes novos ou alterados.
   Salva `data/proposicoes/<ano>.json` e atualiza `data/meta.json`.
2. `coletor.documentos` lista os cinco demais tipos e salva `data/documentos/<tipo>/<ano>.json`.
   A página de detalhe (autoria com papéis, tramitação completa, processo e protocolo) só é baixada para
   requerimentos, PDLs, resoluções e documentos com mais de um autor; indicações e moções de um só autor ficam
   com a listagem. O detalhe que falta, falha ou fica para depois recebe `"detalhe_pendente": true`; a fila reúne
   os pendentes de todos os arquivos, os mais recentes primeiro. Atualiza a chave `documentos` de `data/meta.json`,
   inclusive numa interrupção.
3. `coletor.classificar` consulta a IA para ementas de projetos de lei ainda não cobertas pelo cache válido.
   Atualiza `data/classificacao_ia.json` quando usa IA e registra estatísticas em `data/meta.json`.
4. `coletor.validar` confere a forma de `data/` e `config/`, inclusive o formato byte a byte de `data/documentos`,
   e sai com código 1 se encontrar problema.
5. `coletor.gerar_site` combina curadoria, regras e cache, classifica os documentos, calcula métricas e recria `site/`.

`coletor/regras_documentos.py` não usa IA nem rede: categoria e subcategoria saem da ementa normalizada (o `assunto`
da listagem só desempata), e o bairro é o último bairro oficial citado na ementa das indicações. A coleta grava,
a partir da tramitação do detalhe, `respondido_em` e `dias_ate_resposta` dos requerimentos e `publicacao`
(número e data) de PDLs e resoluções; categoria, bairro e `respondido` são calculados na geração do site.
`respondido_em` é a data do passo "Respondido" da tramitação, não necessariamente a data da resposta do Executivo.

## Comandos

Execute na raiz. Para verificar um ano, substitua `2026` pelo ano desejado:

```text
python -m coletor.siscam --anos 2026
python -m coletor.documentos --anos 2026
python -m coletor.classificar --sem-ia
python -m coletor.validar
python -m coletor.gerar_site
python -m http.server -d site 8000
```

- `--anos` aceita um ano ou intervalo inclusivo, como `2025-2026`. Padrão: 2021 até o ano atual em `coletor.siscam`;
  ano anterior e atual em `coletor.documentos`.
- `--workers 4` controla a concorrência dos dois coletores. Em `coletor.siscam`, `--forcar` baixa novamente
  todos os detalhes, mesmo sem mudança.
- Em `coletor.documentos`: `--tipos requerimento,indicacao,mocao,pdl,resolucao` restringe os tipos;
  `--max-detalhes 1500` limita as páginas de detalhe por execução; `--sem-detalhe` só lista; `--so-detalhes`
  não relista e só esvazia a fila de pendentes (não combina com `--sem-detalhe` nem `--forcar`); `--forcar`
  rebaixa o detalhe de todos os elegíveis, ainda dentro de `--max-detalhes`; `--max-minutos 100` encerra de forma
  limpa no prazo e deixa o resto pendente.
- No classificador, `--sem-ia` evita novas chamadas; `--limite 15` limita a 15 projetos novos classificados por IA.
- Mesmo após classificar com `--sem-ia`, o gerador lê o cache existente; a opção não limpa classificações anteriores.
- `python -m coletor.arquivos --reformatar` regrava `data/proposicoes/*.json` e `data/classificacao_ia.json` no
  formato de um registro por linha, conferindo antes que o conteúdo não muda.

Carga inicial dos documentos de 2021 em diante: rode a coleta manualmente ano a ano, pelo input `anos_documentos`
(`2021`, depois `2022`…). Com volumes como os de 2026, a listagem leva cerca de 23 minutos por ano; o restante do
prazo da execução vai para os detalhes. Os pendentes são baixados nas execuções seguintes, ou localmente com
`python -m coletor.documentos --so-detalhes`.

Para habilitar novas chamadas à IA, a forma POSIX do README é:

```sh
OPENCODE_API_KEY=... python -m coletor.classificar
```

No Windows/PowerShell (`pwsh`), use:

```powershell
$env:OPENCODE_API_KEY = "..."
python -m coletor.classificar
```

Não exponha chaves em commits, exemplos reais ou logs.

## Variáveis de ambiente

| Variável | Padrão / função |
| --- | --- |
| `COLETOR_USER_AGENT` | Identificação do projeto com URL do repositório nas requisições ao SISCAM. |
| `COLETOR_WORKERS` | `4`; padrão de `--workers` nos dois coletores, que pode sobrescrevê-lo. |
| `OPENCODE_API_KEY` | Sem padrão; sem chave, não há novas chamadas à IA. |
| `OPENCODE_MODEL` | `deepseek-v4.1-flash`; modelo usado pelo classificador. |
| `OPENCODE_BASE_URL` | `https://opencode.ai/zen/go/v1`; base da API compatível com chat completions. |
| `CLASSIFICADOR_LOTE` | `15`; projetos por chamada à IA. |
| `CLASSIFICADOR_CONFIANCA_MINIMA` | `0.75`; limiar de exibição dos alertas da IA. |
| `RADAR_COLETA` | Sem padrão; com `1`, pula os testes que comparam fixtures com os dados versionados. |

As variáveis são lidas do ambiente do processo; não há carregamento automático de `.env`.
Com `GITHUB_ACTIONS` definida, `coletor.validar` emite os problemas como `::error::`.

## Dados do site

- `site_src/app.js` não busca `dados/projetos.json`. Cada página com dados embute o manifesto em
  `<script type="application/json" id="manifesto-dados">`; `dados/manifest.json` só é buscado para renovar um
  manifesto desatualizado. `dados/projetos.json` continua gerado apenas como exportação.
- Projetos de lei: `dic-pl` (dicionários) e as fatias em colunas `pl-lei`, `pl-andamento` e `pl-sem_exito`, com o
  mesmo `build`; `pl-recentes` é a prévia das 40 primeiras linhas, usada por `projetos.html` sem filtros.
  `site_src/dados.js` hidrata as colunas no formato de objeto legado que `app.js` usa.
- Documentos: `dic-doc` só com enumerações estáveis (tipos, categorias, subcategorias e URL de detalhe);
  `doc-<tipo>-<ano>[-k]` e `ver/<slug>[-<tipo>][-k]` têm dicionários locais (pessoas, situações, bairros) e não
  levam build, então uma parte sem mudança mantém os mesmos bytes e a mesma URL.
- As URLs levam `?v=` com os 10 primeiros caracteres do SHA-1 do conteúdo.
- Orçamentos em gzip: JSON inicial de cada página e cada JSON de PL ou dicionário ≤ 200 KiB; cada parte de
  documentos ≤ 150 KiB; cada HTML ≤ 100 KiB. O gerador imprime um relatório de tamanhos e `::warning::` ao exceder.
- `atividades.html` lista os documentos com filtros na URL; cada página de vereador tem a seção "Atividade".
  "Ver no SISCAM" abre um `<dialog>` com iframe em sandbox, aceito só para
  `DetalhesDocumentos.aspx?IdDocumento=<n>`; o link "abrir no SISCAM" fica sempre visível como alternativa.

## CI/CD

- `.github/workflows/testes.yml`: em `pull_request`, em pushes para branches que não são `main` e como workflow
  reutilizável. Com Python 3.12 e Node 22, roda os testes Python, `coletor.validar`, os testes JS e a geração do site.
- `.github/workflows/coleta.yml`: cron `17 9 * * 1`, segunda-feira às 09:17 UTC (06:17 em Brasília), ou execução
  manual com `anos`, `anos_documentos` e `forcar`. Passos: `siscam` (90 min) → `documentos` (`continue-on-error`,
  120 min, `timeout 110m` e `--max-minutos 100`) → `classificar` (90 min) → `coletor.validar` e testes Python com
  `RADAR_COLETA=1`. Se a validação ou os testes falharem, descarta as mudanças em `data/documentos`, apaga
  temporários e valida de novo. Só então faz commit de `data/` como `github-actions[bot]`, com `git pull --rebase`
  antes do push. Se nada for gravado, `data/` sobe como artefato por 14 dias, para não perder a classificação já
  paga da IA. A concorrência não cancela execuções; não interrompa uma coleta em andamento sem necessidade.
- IA na coleta: secret **`OPENCODE_API_KEY`** e variável de Actions **`OPENCODE_MODEL`**, opcional.
- `.github/workflows/site.yml`: em pushes para `main` que alterem `coletor/**`, `config/**`, `data/**`, `site_src/**`,
  `tests/**`, `site.yml` ou `testes.yml`; também após uma coleta bem-sucedida e por execução manual. Chama
  `testes.yml` sobre `main`, gera o site no SHA exato que passou nos testes (e confere) e só então publica no
  GitHub Pages, com `cancel-in-progress: false`. Pages deve usar a fonte GitHub Actions.

## Arquivos gerados vs. editados à mão

- **Nunca edite à mão** `data/` (`data/proposicoes/`, `data/documentos/`, `data/classificacao_ia.json`,
  `data/meta.json`) nem `site/`. Corrija a coleta, as regras ou a configuração e regenere; correções editoriais
  cabem em `config/curadoria.json`.
- Edite as fontes em `coletor/`, `config/` e `site_src/`, conforme a responsabilidade da mudança.
- Preserve `/site/` com a barra inicial no `.gitignore`: `site/` sem ela também ignoraria **`coletor/site/`**, que é código-fonte.
- O gerador apaga e recria a saída; mudanças manuais no HTML/CSS de `site/` serão perdidas.
- O hash do cache é SHA-1 de `VERSAO_PROMPT|MODELO|ementa`, truncado para 16 caracteres.
  Alterar `VERSAO_PROMPT` ou o modelo invalida o cache para novas chamadas e gera custo de reclassificação.
  Ao mudar o prompt, revise seu versionamento e esse custo; não apague o cache para experimentar.

## Convenções de código

- Identificadores, docstrings, comentários e mensagens em português; mantenha os nomes de APIs externas.
- Inclua `from __future__ import annotations` em cada módulo Python; use tipos modernos (`list[str]`, `str | None`).
- Siga o estilo local: quatro espaços, funções/campos em `snake_case`, constantes em maiúsculas e datas em ISO 8601.
- Use separadores de seção como `# ---- nome`, com os traços estendidos conforme os módulos existentes.
- Avisos usam `print(..., file=sys.stderr)`; use `::warning::` para anotações reconhecidas pelo CI.
- Grave `data/` só por `coletor/arquivos.py`: `salvar_lista` (lista, um registro por linha), `salvar_mapa`
  (objeto, uma chave por linha) e `salvar_json` (arquivos pequenos como `data/meta.json`, com `indent=1`).
  Todos ordenam as chaves, usam `ensure_ascii=False`, LF e quebra de linha final, com gravação atômica.
  `.gitattributes` fixa LF em `data/**`. Os JSONs do navegador em `site/dados/` são compactos.
- No front-end, edite JS/CSS puros em `site_src/`. Preserve o contrato entre `coletor/gerar_site.py`,
  `coletor/site/paginas.py`, `site_src/dados.js` e `app.js`: colunas, manifesto e regras espelhadas nos dois lados
  (`PASSO_LISTA`/`PASSO`, `plano_docs`/`fatiasDocs`).
- Preserve escape de HTML, tabelas acessíveis dos gráficos, navegação por teclado e a restrição de URL do diálogo do SISCAM.

## Curadoria e neutralidade editorial

- Cada entrada de `config/curadoria.json` precisa de **`fontes` públicas**, com pelo menos uma URL verificável.
  Use o número do PL em `projeto` (por exemplo, `1/2022`) e uma `nota` factual apoiada nas fontes.
- Os critérios, inclusive as regras dos documentos, valem igualmente para qualquer autor, partido ou espectro
  político; não crie exceções partidárias.
- A curadoria prevalece sobre a IA; `substitui_ia: true` suprime os alertas da IA daquele projeto.
  Use `corrige` para correções documentadas, em vez de alterar os dados coletados.
- Em `config/vereadores.json`, os nomes `siscam` devem corresponder **exatamente ao SISCAM, em maiúsculas**.
  Preserve o partido da eleição, as fontes das legislaturas e os registros de afastamento.
- Não confunda impacto estimado com resultado comprovado; mantenha explícitas as limitações e a contestação por issue.
  Contar documentos não mede qualidade nem resultado.

## Scraping do SISCAM (cuidados)

- Mantenha um `User-Agent` identificável, timeout e tentativas com espera progressiva (retry/backoff).
- Use concorrência baixa: o padrão é **4 workers**. Evite `--forcar` e aumentos de paralelismo sem necessidade.
- O SISCAM só pagina até a **página 50** (500 registros); preserve a divisão por faixas de número (`FAIXA = 400`),
  usada pelos dois coletores.
- O parsing de HTML por regex e divisões de texto é frágil: confira o HTML real antes de ajustar os padrões.
- Compare contagens esperadas, autoria, situação e tramitação; não transforme falhas de parsing em dados vazios silenciosos.
  Preserve dados anteriores em falhas de listagem ou detalhe e investigue avisos de listagem incompleta.
- Em `coletor.documentos`, respeite `--max-detalhes` e `--max-minutos`: o que não couber fica pendente para a próxima execução.

## Testes e verificação

Execute na raiz:

```text
python -m unittest discover -s tests -t .
node --test "tests/js/**/*.test.js"
python -m coletor.validar
```

- Os testes Python também rodam com pytest. Mantenha o glob do Node entre aspas: o próprio Node 21+ o expande.
- Os testes são offline: não acessam o SISCAM nem a IA. Novos testes devem seguir a mesma regra.
- `tests/fixtures/siscam/` guarda HTML real do SISCAM; preserve os bytes e o CRLF (`.gitattributes` marca as fixtures
  como `-text`). Para um layout novo, salve a página real como fixture.
- Testes que comparam fixtures com os dados versionados são pulados com `RADAR_COLETA=1`, como na coleta semanal.
- Não há linter, formatter nem typecheck configurados.

Para mudanças de pipeline ou apresentação, rode também os comandos da seção Comandos e inspecione
`http://localhost:8000`: contagens e JSONs gerados, avisos e relatório de tamanhos do gerador, filtros de leis,
projetos e atividades, páginas de vereadores com a seção "Atividade", diálogo do SISCAM, gráficos, tabelas
acessíveis, links e console do navegador. Informe o que foi verificado e o que não foi executado.

## Commits

Escreva em português, com inicial maiúscula e frase no imperativo ou na terceira pessoa: “Inclui…” ou “Atualiza…”.
Não use prefixos de conventional commits, trailers de coautoria de IA nem linhas “Generated with”.
Mantenha a mudança pequena e focada; não misture ajustes de código com atualizações de dados não solicitadas.
