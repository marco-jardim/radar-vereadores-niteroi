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
| `coletor/sessoes.py` | Sessões plenárias: listagem por ano, pauta, fases, frequência e votações nominais, coletadas semanalmente em `coleta.yml`. |
| `coletor/regras_sessoes.py` | Regras determinísticas de presença, votos, sentido do parecer, quórum e qualidade, sem IA. |
| `coletor/regras_documentos.py` | Categorias, bairro, resposta e publicação dos documentos, por regras determinísticas. |
| `coletor/geo.py` | Conversão offline do Overpass em limites simplificados dos 52 bairros, com fonte OSM/ODbL. |
| `coletor/classificar.py` | Taxonomia, regras, prompt, chamadas à IA, cache e curadoria dos projetos de lei. |
| `coletor/arquivos.py` | Gravação atômica dos JSONs de `data/`, com um registro por linha. |
| `coletor/validar.py` | Validação de `data/` e `config/`, sem alterar nada. |
| `coletor/gerar_site.py` | Entrada da geração; exporta os JSONs do navegador, o manifesto e o relatório de tamanhos. |
| `coletor/novidades.py` | Eventos dos PLs (apresentado, lei, veto, veto derrubado) pelas datas dos dados, semanas e feed RSS. |
| `coletor/site/modelo.py` | Enriquecimento, pessoas, mandatos, métricas, projetos repetidos e documentos por autor. |
| `coletor/site/modelo_sessoes.py` | Agregação das sessões coletadas, cobertura e métricas da Câmara e de cada pessoa. |
| `coletor/site/pagina_sessoes.py` | `sessoes.html`, seção "Presença e votos" dos vereadores e metodologia `#sessoes`. |
| `coletor/site/graficos.py` | Gráficos SVG com tabelas acessíveis. |
| `coletor/site/paginas.py` | HTML, componentes, diálogo do SISCAM e metodologia publicada. |
| `config/vereadores.json` | Legislaturas, eleitos, partidos, apelidos e afastamentos. |
| `config/curadoria.json` | Rótulos e correções manuais com fontes públicas. |
| `data/` | Projetos, documentos e (quando coletadas) sessões por ano, cache da IA e metadados, todos gerados e versionados. |
| `site_src/` | Fontes estáticas: `app.js`, `dados.js`, `sessoes.js`, `estilo.css` e `favicon.svg`. |
| `tests/` | Testes Python (`test_*.py`), JavaScript (`tests/js/`) e HTML real do SISCAM (`tests/fixtures/siscam/`). |
| `.github/workflows/` | Testes, coleta semanal e publicação do site. |
| `site/` | Saída gerada localmente, ignorada pelo Git. |

## Pipeline (coleta → documentos → sessões → classificação → validação → site)

1. `coletor.siscam` lista os projetos de lei por ano e baixa detalhes novos ou alterados.
   Junto com o detalhe do PL, baixa o de cada substitutivo da seção "[ Substitutivos ]" e grava `substitutivos`
   (id, número, data, situação, autoria, tramitação e lei). Se a lei sai de um substitutivo e não do próprio PL,
   o PL fica com essa lei (número e data do substitutivo), `desfecho` `virou_lei` e `lei_substitutivo` com o id.
   Salva `data/proposicoes/<ano>.json` e atualiza `data/meta.json`.
2. `coletor.documentos` lista os cinco demais tipos e salva `data/documentos/<tipo>/<ano>.json`.
   A página de detalhe (autoria com papéis, tramitação completa, processo e protocolo) só é baixada para
   requerimentos, PDLs, resoluções e documentos com mais de um autor; indicações e moções de um só autor ficam
   com a listagem. O detalhe que falta, falha ou fica para depois recebe `"detalhe_pendente": true`; a fila reúne
   os pendentes de todos os arquivos, os mais recentes primeiro. Atualiza a chave `documentos` de `data/meta.json`,
   inclusive numa interrupção.
3. `coletor.sessoes` lista as sessões plenárias por ano e baixa pauta, frequência e votações nominais (detalhes abaixo).
   Salva `data/sessoes/<ano>.json` e atualiza a chave `sessoes` de `data/meta.json`, inclusive numa interrupção.
4. `coletor.classificar` consulta a IA para ementas de projetos de lei ainda não cobertas pelo cache válido.
   Atualiza `data/classificacao_ia.json` quando usa IA e registra estatísticas em `data/meta.json`.
5. `coletor.validar` confere a forma de `data/` e `config/`, inclusive o formato byte a byte de `data/documentos`
   e de `data/sessoes` (pastas opcionais), e sai com código 1 se encontrar problema.
6. `coletor.gerar_site` combina curadoria, regras e cache, classifica os documentos, calcula métricas e recria `site/`,
   inclusive `sessoes.html`, `novidades.html` e `feed.xml`, com eventos derivados na hora (não há `data/novidades.json`).

Passo de sessões em `coleta.yml`, depois de documentos e antes da classificação:
`coletor.sessoes` lista as sessões plenárias de cada ano
(`ResultadoSessao.aspx?Ano=<ano>&pagina=<n>`, 10 por página, sem total) e baixa o detalhe de cada uma
(`DetalhesSessao.aspx`): observações, documentos da sessão (rótulo e arquivo), itens de pauta, frequência por
momento ("Abertura - 14:10") e votações com totais e votos nominais.
Salva `data/sessoes/<ano>.json`, ordenado por data, hora, número e id, e atualiza a chave `sessoes` de `data/meta.json`.
- A pauta guarda só referências: `id_documento`, `fase`, `prioridade`, `secao` (rótulo do documento da sessão em que
  o item aparece) e `secao_indice` (a posição dele em `documentos_sessao`, porque pode haver duas "Ordem do Dia").
  Tipo, número, ano e ementa vêm de `data/proposicoes` e `data/documentos` pelo id. Só o item cujo id não está
  nesses arquivos no momento da coleta, ou sem id (linha sem link, gravada com `id_documento` null), guarda também
  `tipo_documento`, `numero`, `ano` e `ementa`, para não perder informação; os ids conhecidos são lidos uma vez por
  execução (`sessoes.ids_conhecidos`). As votações, poucas, continuam com `documento`, `tipo_documento`, `numero` e
  `ano`, que servem de conferência; votação sem link também fica com `id_documento` null.
- No workflow, a ordem é obrigatória: `siscam` → `documentos` → `sessoes`, para que os ids da pauta já
  estejam em `data/`. Risco: um item enxuto cujo documento depois some de `data/proposicoes` ou `data/documentos`
  (removido ou renumerado no SISCAM) perde tipo, número e ementa. Recuperação: rode `python -m coletor.sessoes
  --anos <ano> --forcar` (o item volta completo se o id não for mais conhecido); o SISCAM ainda mostra a pauta.
- Dado bruto: um mesmo nome pode se repetir numa votação ou num momento da frequência (na 95ª Ordinária de 2025, o
  presidente aparece como "Ausente" e como "Presidente"). A linha é mantida e o nome vai para `nomes_repetidos` da
  votação ou `frequencia_nomes_repetidos` da sessão (omitidos se vazios), com aviso simples em stderr; somas por
  vereador precisam deduplicar. O nome é gravado como vem, sem separar cargo (nenhuma página real traz cargo no nome).
- Layout alterado: rótulo de seção ("[ Votações ]", "[ Frequência ]", "[ Documentos da Sessão ]") na página sem a
  linha esperada (`trVotacoes`, `trFrequencia`, `trDocumentosSessao`), ou linha sem a grade principal, gera
  `::warning::` e a sessão não é gravada como detalhada: fica pendente. Ordinária ou extraordinária sem frequência só
  avisa. Totais que divergem da contagem dos votos, ou com rótulo desconhecido, também só avisam.
- O `ano` da sessão é o da listagem (o do arquivo); título de outro ano só gera aviso e fica como está em `titulo`.
  Sessão sem tipo na listagem nem no título fica `"tipo": "desconhecido"`, com aviso. `detalhe_em` só muda quando o
  conteúdo do registro muda, para não gerar diffs semanais vazios.
- Paginação: para numa página curta, vazia ou fora do intervalo — o SISCAM responde a uma página além da última com
  a página 1 de novo, o que se detecta pelo paginador (`currentPage`) e pelos ids repetidos. `PAGINAS_MAX = 50` é o
  limite do SISCAM: se a página 50 vier cheia, a listagem do ano fica marcada como incompleta, com aviso.
- Os textos ficam como no SISCAM: situação de frequência ("Consignado", "Ausência Justificada"), voto ("Favor",
  "Ausente", "Presidente") e resultado ("Veto Mantido") não são interpretados na coleta. Na geração do site,
  `regras_sessoes.py` deriva o sentido quando há evidência suficiente; o resto aparece como não determinado.
- O `IdDocumento` dos itens de pauta e das votações é o mesmo id de `data/proposicoes` e `data/documentos`; o id da
  própria sessão é de outra numeração (`DetalhesSessao.aspx`).
- Detalhe baixado para sessões novas, sem detalhe, pendentes, com cabeçalho alterado, dos últimos 60 dias ou com
  `--forcar`; o resto recebe `"detalhe_pendente": true`. Falha de listagem ou listagem menor mantêm as sessões
  anteriores, e uma lista que tinha itens e veio vazia num novo download mantém os itens anteriores, com aviso.

`coletor/regras_documentos.py` não usa IA nem rede: categoria e subcategoria saem da ementa normalizada (o `assunto`
da listagem só desempata), e o bairro é o último bairro oficial citado na ementa das indicações. A coleta grava,
a partir da tramitação do detalhe, `respondido_em` e `dias_ate_resposta` dos requerimentos e `publicacao`
(número e data) de PDLs e resoluções; categoria, bairro e `respondido` são calculados na geração do site.
`respondido_em` é a data do passo "Respondido" da tramitação, não necessariamente a data da resposta do Executivo.

Geometria opcional, separada da coleta semanal: `python -m coletor.geo --entrada bairros-overpass.json`
atualiza `data/geo/bairros.json` a partir de JSON Overpass com `out geom` dos bairros administrativos de nível 10
dentro de Niterói (relação OSM 2220789; consulta no README). Não usa rede. Encadeia ways por pontas, inverte
quando preciso, respeita outer/inner e falha com aviso em anel aberto; projeta em metros (equiretangular local),
simplifica por way compartilhado (Douglas–Peucker, inicialmente 25 m), preserva pontas, descarta recortes
menores que 400 m²/invisíveis e arredonda num viewBox de largura 1000. Anel degenerado/cruzado reduz a tolerância
global ou aborta. O comando ajusta até 100 m para caber em 60 KiB brutos e informa tolerância final e tamanhos
bruto/gzip. Mesma entrada, mesmos bytes; nunca edite a geometria à mão. Rode a validação e gere/inspecione o site.
Fonte: © contribuidores do OpenStreetMap, ODbL 1.0, https://www.openstreetmap.org/copyright; preserve a atribuição
visível e a data da base OSM em todo mapa. Não trate limites simplificados como mapa cadastral. Os 52 nomes da
extração inicial de 23/10/2026 coincidem com BAIRROS_NITEROI; faltas, sobras e duplicatas abortam a conversão.

As regras das métricas dos documentos também ficam só em `coletor/regras_documentos.py`; `coletor/site/modelo.py`
só agrega. `eixos_perfil` é a única regra do perfil de atuação. Homenagem é a categoria `homenagem` (moções de
aplauso, inclusive congratulação, e de pesar; títulos e honrarias em PDLs e resoluções; repúdio e apoio não contam), e
o peso é a contagem e a % da produção do mesmo período (documentos do autor + PLs como autor principal, só em anos de
coleta completa, com os cinco tipos; `modelo.anos_coleta`, calculado uma vez em `montar_modelo`). `extrair_orgao` dá o
primeiro órgão específico citado na ementa do requerimento de informação (senão o `assunto`; órgão estadual só como
destinatário; depois "Prefeito ou Poder Executivo"; senão "Não identificado"): o destinatário da tramitação é
quase sempre a Secretaria Municipal de Governo, que repassa o pedido. `estado_pedido` separa respondido, aguardando,
encerrado e retirado; a taxa de resposta exclui os retirados e a mediana de `dias_ate_resposta` usa só os respondidos
com data (que exige o detalhe baixado), exibida com essa base.

## Comandos

Execute na raiz. Para verificar um ano, substitua `2026` pelo ano desejado:

```text
python -m coletor.siscam --anos 2026
python -m coletor.documentos --anos 2026
python -m coletor.sessoes --anos 2026
python -m coletor.classificar --sem-ia
python -m coletor.validar
python -m coletor.gerar_site
python -m http.server -d site 8000
```

- `--anos` aceita um ano ou intervalo inclusivo, como `2025-2026`. Padrão: 2021 até o ano atual em `coletor.siscam`;
  ano anterior e atual em `coletor.documentos` e `coletor.sessoes`.
- `--workers 4` controla a concorrência dos coletores (no de sessões, só dos detalhes). Em `coletor.siscam`, `--forcar` baixa novamente
  todos os detalhes, mesmo sem mudança; `--max-detalhes 400` limita, por execução e do mais recente ao mais antigo,
  os detalhes pedidos só pelos substitutivos (PL ainda sem a chave `substitutivos` ou sem lei com substitutivo
  ainda sem lei, cuja tramitação não muda a listagem do PL); o resto fica para a próxima execução.
- Em `coletor.documentos`: `--tipos requerimento,indicacao,mocao,pdl,resolucao` restringe os tipos;
  `--max-detalhes 1500` limita as páginas de detalhe por execução; `--sem-detalhe` só lista; `--so-detalhes`
  não relista e só esvazia a fila de pendentes (não combina com `--sem-detalhe` nem `--forcar`); `--forcar`
  rebaixa o detalhe de todos os elegíveis, ainda dentro de `--max-detalhes`; `--max-minutos 100` encerra de forma
  limpa no prazo e deixa o resto pendente.
- Sessões: `python -m coletor.sessoes --anos 2021-2026 --workers 4`; padrão: ano anterior
  e atual. `--max-detalhes 400` limita as páginas de detalhe por execução, as mais recentes primeiro; `--forcar`
  rebaixa o detalhe de todas as sessões listadas, ainda dentro do limite; `--max-minutos` encerra de forma limpa.
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
| `COLETOR_WORKERS` | `4`; padrão de `--workers` nos coletores, que pode sobrescrevê-lo. |
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
  `site_src/dados.js` hidrata as colunas no formato de objeto legado que `app.js` usa. A coluna `ls` (id do
  substitutivo da lei) vira, como `u`, a URL do detalhe; o link "via substitutivo" usa `ls`, e o número do PL, `u`.
- Documentos: `dic-doc` só com enumerações estáveis (tipos, categorias, subcategorias e URL de detalhe);
  `doc-<tipo>-<ano>[-k]` e `ver/<slug>[-<tipo>][-k]` têm dicionários locais (pessoas, situações, bairros) e não
  levam build, então uma parte sem mudança mantém os mesmos bytes e a mesma URL.
  O fatiamento usa alvo de 120 KiB gzip (com margem de 512 bytes), sem mudar o orçamento oficial de 150 KiB;
  as primeiras partes de cada tipo/ano usam 24 KiB, até cobrir `PASSO_LISTA` itens e terminar numa troca de data.
- As URLs levam `?v=` com os 10 primeiros caracteres do SHA-1 do conteúdo.
- Orçamentos em gzip: JSON inicial de cada página e cada JSON de PL ou dicionário ≤ 200 KiB; cada parte de
  documentos ≤ 150 KiB; cada HTML ≤ 100 KiB. O gerador imprime um relatório de tamanhos e `::warning::` ao exceder.
- `novidades.html` e `feed.xml` (RSS 2.0, na raiz do site) não têm JSON próprio: o HTML sai pronto do servidor.
  `coletor/novidades.py` deriva os eventos só das datas já coletadas, sem comparar coletas nem guardar estado:
  `data` do PL (apresentado), `lei.data` (virou lei, com `lei_substitutivo`) e, por `marcos_tramitacao` (chave
  `marcos` do projeto em `modelo.py`), a Data Resposta do passo de veto e a do passo de plenário que derruba o veto,
  no PL ou num substitutivo. A derrubada só conta com confirmação no mesmo documento (situação "VETO REJEITADO" ou
  "VETO DERRUBADO", ou `lei.tipo == "veto_derrubado"`), nunca com "VETO MANTIDO" ou desfecho `vetado`, e ignora
  "votos pela derrubada". A semana mais recente é a semana ISO (segunda a domingo) da última data dos eventos,
  nunca a do relógio; datas posteriores ao dia de `coleta.em` de `data/meta.json`, no horário de Brasília (UTC−3),
  são ignoradas. A página mostra 12 semanas; o feed, os 100 eventos mais recentes, com `guid` fixo (tipo, id e
  data), links absolutos sobre `URL_SITE` (a lei via substitutivo leva ao substitutivo) e `lastBuildDate` igual à
  data mais recente: a mesma entrada gera os mesmos bytes. Alertas de polêmica ficam de fora
  porque curadoria e cache da IA não têm data. Toda página leva `<link rel="alternate" type="application/rss+xml">`.
- `atividades.html` lista os documentos com filtros na URL; cada página de vereador tem a seção "Atividade".
  "Ver no SISCAM" abre um `<dialog>` com iframe em sandbox, aceito só para
  `DetalhesDocumentos.aspx?IdDocumento=<n>`; o link "abrir no SISCAM" fica sempre visível como alternativa.
- `sessoes.html` e a seção "Presença e votos" de cada vereador mantêm HTML gerado no servidor. Para consultas
  no navegador, `dados/dic-ses.json` exporta enumerações e os mesmos rótulos de `regras_sessoes.rotulo_voto`;
  `dados/vot-<ano>.json` guarda as votações nominais em colunas, com pessoas locais e um caractere por pessoa
  em cada string de votos (`.` significa que não consta, diferente de ausência ou voto indeterminado).
  Esses JSONs não levam build; as famílias `dic-ses` e `vot` entram no manifesto com `?v=` por conteúdo,
  preservando a URL de um ano sem mudança. O manifesto embutido de `sessoes.html` lista todos os anos, com
  carga inicial prevista de dicionário + ano mais recente; só o dicionário recebe preload fixo, pois a consulta
  pode pedir outro ano. Cada parte anual tem teto de 150 KiB gzip (estimativa: cerca de 8 KiB para 70 votações);
  o relatório mostra o dicionário, a soma e o máximo das partes, com aviso ao exceder o orçamento.
  O gerador chama `modelo_sessoes.montar_sessoes` quando existe `data/sessoes`; sem a pasta, gera o estado vazio
  e não cria partes `vot-*`. A página mostra presença por legislatura, votações divididas (40 cartões iniciais e o resto
  em `<details>`), placares por ano, ritmo e qualidade. Suplentes sem página aparecem sem link, identificados
  como "suplente em exercício". As regras e limitações estão em `metodologia.html#sessoes`: só deliberativas
  realizadas com lista entram na presença; licenças ficam fora da base individual; Favor/Contra é voto sobre
  o parecer, não automaticamente sobre a matéria. Sentidos não determinados ficam explícitos e placares
  inconsistentes mostram apenas os totais oficiais, sem nomes. Contar presença e votos não mede qualidade.
  O relatório inclui `sessoes.html` no teto oficial de 100 KiB gzip; o alvo de apresentação é 60 KiB nos dados
  reais, e a seção individual tem orçamento de +10 KiB gzip. A coleta de sessões roda semanalmente em `coleta.yml`.
  `site_src/sessoes.js` melhora só `sessoes.html`: revela os formulários por legislatura, grava filtros com
  `history.replaceState` (`leg`, `ano`, `classe`, `materia`, `vereador`, `div=1`, `q`, `ordem`; padrões omitidos),
  pagina de 40 em 40 e exporta CSV UTF-8 com BOM e fórmulas neutralizadas. `div=1` exige vereador e comparação
  determinada. A ordenação “apertadas” usa a margem absoluta Favor/Contra, não o quórum legal.
  Sem consulta, preserva os cartões e as notas técnicas do servidor e busca só dicionário + último ano;
  filtros, Mostrar mais e CSV carregam o recorte completo necessário, sempre pelas URLs do manifesto.
  `app.js` expõe apenas `RadarArquivos.carregar/manifesto` (cache/renovação compartilhados) e não inicia
  listas genéricas nos formulários de sessões. Os arquivos de sessões usam esquema 1, dentro do manifesto 2.
  Ao escolher ano, o cliente refaz a faixa; “todos” restaura a faixa inicial do último ano com divididas.
  `tr[data-vereador]` preserva a composição do servidor e permite destacar a pessoa sem promover nomes brutos.
  Preserve o contrato de `cartao_votacao`/`_mapa_votos`, os rótulos de `dic-ses` e a fixture de paridade
  `tests/js/fixtures/sessoes.json` + `faixa_sessoes.html`, conferida tanto pelo Python como pelo JS.
  Referências abreviadas e nomes curtos vêm do JSON; notas técnicas não são exportadas (continuam no HTML
  inicial e em Qualidade dos dados). CSV inclui “não consta”; em placares inconsistentes não atribui votos
  às pessoas, assim como os cartões. O alvo de `sessoes.js` é até 12 KiB gzip, testado offline.
- As métricas dos documentos (homenagens em `ruido.html`; requerimentos de informação por vereador e por órgão e
  indicações nos 52 bairros em `atividades.html`; as três na seção "Atividade") são tabelas e gráficos gerados no
  servidor, só com agregados: não há colunas novas nos JSONs do navegador.
- O mapa de indicações reusa esses agregados e a geometria opcional `data/geo/bairros.json`, carregada por
  `gerar_site.py`. Sem o arquivo, ficam os gráficos/tabelas anteriores. SVG sem JS, com título/descrição,
  até cinco quantis dos positivos (menos com poucos valores distintos, sem dividir empates), zero hachurado
  quando presente, títulos por bairro e tabela dos 52 bairros. Arredonde cortes só no vão entre observações:
  não mude os grupos nem crie classes vazias. A legenda mostra limites e contagem de bairros; cores de mapas
  com limites diferentes não são comparáveis. Informe valores absolutos (sem população), bairro inferido da
  ementa e % sem bairro fora do mapa.
  Em cada vereador, o bloco completo só aparece se medir ≤ 12 KiB gzip (medição determinística na geração);
  acima disso, só tabelas por legislatura. Com a geometria atual (base OSM 23/10/2026), o mapa individual não
  é exibido por exceder esse orçamento. Preserve ODbL/atribuição junto ao mapa, inclusive em páginas individuais.

## CI/CD

- `.github/workflows/testes.yml`: em `pull_request`, em pushes para branches que não são `main` e como workflow
  reutilizável. Com Python 3.12 e Node 22, roda os testes Python, `coletor.validar`, os testes JS e a geração do site.
- `.github/workflows/coleta.yml`: cron `17 9 * * 1`, segunda-feira às 09:17 UTC (06:17 em Brasília), ou execução
  manual com `anos`, `anos_documentos`, `anos_sessoes` e `forcar`. Passos: `siscam` (90 min) → `documentos`
  (`continue-on-error`, 120 min, `timeout 110m` e `--max-minutos 100`) → `sessoes` (`continue-on-error`, 30 min,
  `timeout 25m` e `--max-minutos 20`) → `classificar` (90 min) → `coletor.validar` e testes Python com
  `RADAR_COLETA=1`. Ambos os comandos `timeout` usam `--kill-after=2m`; o job tem limite de 350 min.
  `anos_sessoes` vazio mantém o padrão (ano anterior e atual); `forcar` também rebaixa os detalhes das sessões listadas,
  respeitando o limite padrão de 400 detalhes por execução e o prazo, sem aumentar os 4 workers padrão.
  Se a validação ou os testes falharem, descarta as mudanças em `data/documentos` e `data/sessoes`, apaga
  temporários e valida de novo. As estatísticas dessas etapas em `data/meta.json` ficam como registro da execução.
  Só então faz commit de `data/` inteiro (inclusive `data/sessoes`) como `github-actions[bot]`, com `git pull --rebase`
  antes do push. Se nada for gravado, `data/` inteiro sobe como artefato por 14 dias, para não perder a classificação
  já paga da IA. A concorrência não cancela execuções; não interrompa uma coleta em andamento sem necessidade.
- IA na coleta: secret **`OPENCODE_API_KEY`** e variável de Actions **`OPENCODE_MODEL`**, opcional.
- `.github/workflows/site.yml`: em pushes para `main` que alterem `coletor/**`, `config/**`, `data/**`, `site_src/**`,
  `tests/**`, `site.yml` ou `testes.yml`; também após uma coleta bem-sucedida e por execução manual. Chama
  `testes.yml` sobre `main`, gera o site no SHA exato que passou nos testes (e confere) e só então publica no
  GitHub Pages, com `cancel-in-progress: false`. Pages deve usar a fonte GitHub Actions.

## Arquivos gerados vs. editados à mão

- **Nunca edite à mão** `data/` (`data/proposicoes/`, `data/documentos/`, `data/sessoes/`, `data/classificacao_ia.json`,
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
  (`PASSO_LISTA`/`PASSO`, `plano_docs`/`fatiasDocs`, cartões e faixa de `pagina_sessoes.py`/`sessoes.js`).
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
  usada pelos coletores de projetos e de documentos. O de sessões lista por ano sem faixa (cerca de 120 sessões por
  ano, 12 páginas) e para na página 50 (`sessoes.PAGINAS_MAX`), marcando a listagem como incompleta se ela vier cheia.
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
projetos e atividades, páginas de vereadores com a seção "Atividade", novidades e `feed.xml`, diálogo do SISCAM,
gráficos, tabelas acessíveis, links e console do navegador. Informe o que foi verificado e o que não foi executado.

## Commits

Escreva em português, com inicial maiúscula e frase no imperativo ou na terceira pessoa: “Inclui…” ou “Atualiza…”.
Não use prefixos de conventional commits, trailers de coautoria de IA nem linhas “Generated with”.
Mantenha a mudança pequena e focada; não misture ajustes de código com atualizações de dados não solicitadas.
