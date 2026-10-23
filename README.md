# Radar dos Vereadores de Niterói

Site aberto que mostra quais leis de Niterói mudam a cidade e quem as escreveu, e quanto da produção da Câmara desde 2021 é homenagem, lei sem efeito prático, projeto repetido ou pauta polêmica.

Páginas: placar por vereador e leis com efeito mais recentes (início), novidades das últimas 12 semanas (projetos de lei apresentados, leis sancionadas ou promulgadas, vetos e vetos derrubados, também no feed RSS `feed.xml`), leis aprovadas com filtros por impacto, tema, vereador e partido, todos os projetos, atividades (indicações, moções, requerimentos, projetos de decreto legislativo e de resolução, com filtros por tipo, ano, vereador, categoria e bairro), sessões e votações (`sessoes.html`), sem efeito e polêmicas, análises históricas e metodologia. Cada vereador tem uma página com seus projetos, a seção "Presença e votos" das sessões plenárias e uma seção "Atividade" com os demais documentos, que não entram nos números de projetos e leis.

Os dados vêm do [SISCAM da Câmara Municipal de Niterói](https://consultaniteroi.siscam.com.br/). Projetos, demais documentos e sessões são atualizados toda semana por GitHub Actions. O site é estático e fica no GitHub Pages.

## Como funciona

| Etapa | Arquivo | O que faz |
|---|---|---|
| Coleta de projetos | `coletor/siscam.py` | Baixa a lista de projetos de lei de cada ano e, para os novos ou com tramitação alterada, a autoria e a tramitação completa. Grava `data/proposicoes/<ano>.json`. |
| Coleta de documentos | `coletor/documentos.py` | Lista requerimentos, indicações, moções, PDLs e resoluções. Baixa a página de detalhe só de requerimentos, PDLs, resoluções e documentos com mais de um autor, com limite por execução; o que fica para depois é marcado como pendente. Grava `data/documentos/<tipo>/<ano>.json`. |
| Coleta de sessões | `coletor/sessoes.py` | Lista as sessões plenárias de cada ano e baixa o detalhe: documentos da sessão, itens de pauta com fase (só a referência ao documento, cujo tipo, número e ementa já estão em `data/proposicoes` ou `data/documentos`; o item cujo documento ainda não foi coletado, ou sem link, guarda também tipo, número e ementa), frequência e votações nominais, com os textos como o SISCAM os exibe (um nome repetido numa votação é mantido e sinalizado). Grava `data/sessoes/<ano>.json`, usado pelo site. Roda em `coleta.yml` depois de projetos e documentos. |
| Presença e votos | `coletor/regras_sessoes.py`, `coletor/site/modelo_sessoes.py` e `coletor/site/pagina_sessoes.py` | Aplica regras sem IA, agrega as sessões coletadas e gera `sessoes.html`, a seção "Presença e votos" dos vereadores e as regras publicadas em `metodologia.html#sessoes`, com tabelas acessíveis e qualidade dos dados. |
| Classificação | `coletor/classificar.py` | Nos projetos de lei, combina curadoria (`config/curadoria.json`), regras determinísticas (simbólica, autorizativa, vetos, pareceres, duplicação de lei em vigor) e IA via OpenCode Go, que atribui categoria, tema, impacto (0 a 3), resumo, público afetado e alertas. O resultado fica em cache (`data/classificacao_ia.json`) e só é refeito quando a ementa ou o prompt mudam. |
| Regras dos documentos | `coletor/regras_documentos.py` | Classifica os demais documentos só por regras sobre a ementa, sem IA: categoria, bairro citado nas indicações, data em que o requerimento consta como respondido na tramitação (não necessariamente a data da resposta do Executivo), publicação de PDLs e resoluções, eixos do perfil de atuação (única regra do perfil), órgão citado nos requerimentos de informação e estado do pedido (respondido, aguardando, encerrado ou retirado). Com elas, o site mostra em tabelas, sem novos dados no navegador: homenagens com contagem e peso na produção, por vereador e por ano, em "Sem efeito e polêmicas"; requerimentos de informação por vereador e por órgão e indicações por bairro em "Atividades"; e as três na página de cada vereador. |
| Geometria dos bairros | `coletor/geo.py` | Converte uma resposta local do Overpass em `data/geo/bairros.json`, com limites simplificados e atribuição OSM/ODbL. Atualização manual por comando, separada da coleta semanal; a geometria é opcional na geração do site. |
| Validação | `coletor/validar.py` | Confere a forma dos dados em `data/` e da configuração em `config/`, sem alterar nada. |
| Novidades | `coletor/novidades.py` | Deriva, na geração do site, os eventos dos projetos de lei a partir das datas já coletadas (apresentação, lei, veto e veto derrubado na tramitação), sem comparar coletas nem gravar estado. A semana mais recente é a da última data encontrada nos dados, não a de hoje. Alimenta `novidades.html` (montada em `paginas.py`) e gera o feed RSS 2.0 `feed.xml`. |
| Site | `coletor/gerar_site.py` e `coletor/site/` | Monta o modelo e as métricas (`modelo.py`), detecta projetos repetidos, gera gráficos SVG com tabela acessível (`graficos.py`) e as páginas (`paginas.py`). Os dados do navegador ficam em `dados/` em arquivos por colunas e partes, listados num manifesto embutido em cada página; os filtros rodam no navegador (`site_src/app.js` e `site_src/dados.js`). `dados/projetos.json` continua sendo gerado, só como exportação. |

Os dados em `data/` são gerados pelos coletores, com um registro por linha, e não devem ser editados à mão.

Os workflows estão em `.github/workflows/`:

- **Testes** (`testes.yml`): em pull requests e pushes fora de `main`, roda os testes Python e JavaScript, valida os dados e gera o site.
- **Coleta semanal** (`coleta.yml`): roda toda segunda-feira às 06:17 (Brasília) ou manualmente, coleta projetos → documentos → sessões, classifica, valida e grava os dados no repositório. Se a validação ou os testes falharem, as mudanças em documentos e sessões são descartadas e os demais dados são validados de novo antes do commit. O commit e o artefato de recuperação (14 dias, se a gravação falhar) abrangem `data/` inteiro, inclusive `data/sessoes`.
- **Publicar site** (`site.yml`): ao fim de cada coleta e a cada mudança no código, nos dados ou na configuração, roda os testes e publica no GitHub Pages exatamente o commit testado.

## Configuração

1. Em **Settings → Pages**, escolha **Source: GitHub Actions**.
2. Em **Settings → Secrets and variables → Actions**, crie o secret `OPENCODE_API_KEY` com sua chave do OpenCode Go. Sem ele, o site funciona só com regras e curadoria.
3. Opcional: crie a variável `OPENCODE_MODEL` para trocar o modelo (padrão: `deepseek-v4.1-flash`). A lista de modelos está em `https://opencode.ai/zen/go/v1/models`.

A chamada à IA usa `POST /chat/completions` em `https://opencode.ai/zen/go/v1`, com os headers `Authorization: Bearer <chave>`, `User-Agent` próprio e `x-opencode-session` estável por execução, como recomenda a [documentação do OpenCode Go](https://opencode.ai/docs/go/).

## Rodar localmente

Só precisa de Python 3.12+ (sem dependências externas). Os testes de JavaScript usam Node 21+.

```bash
python -m coletor.siscam --anos 2025-2026   # projetos de lei
python -m coletor.documentos --anos 2026    # demais documentos
python -m coletor.sessoes --anos 2026       # sessões plenárias, após projetos e documentos
OPENCODE_API_KEY=... python -m coletor.classificar   # ou --sem-ia
python -m coletor.validar
python -m coletor.gerar_site
python -m http.server -d site 8000
```

Testes (offline, sem acesso ao SISCAM nem à IA):

```bash
python -m unittest discover -s tests -t .
node --test "tests/js/**/*.test.js"
```

## Sessões e votações

`sessoes.html` mostra presença por legislatura, votações que dividiram a Câmara, placares por ano,
ritmo mensal e cobertura da coleta. Cada vereador tem a seção **Presença e votos**, antes de "Atividade".
Suplentes sem página própria aparecem com nome e a identificação "suplente em exercício", sem link.
Tudo é gerado no servidor: sem novos JSONs de votos nem JavaScript; os primeiros 40 cartões de cada
legislatura aparecem na lista e os demais ficam em "Ver mais". Sem `data/sessoes`, o site gera os estados vazios.

As regras estão em **`metodologia.html#sessoes`**: só sessões deliberativas realizadas com lista entram na
presença; licenças ficam fora da base individual. Favor/Contra é voto sobre o parecer da comissão;
sentidos não determinados e placares inconsistentes são identificados. Contar presença e votos não mede
qualidade do mandato, e comissões, debates e votações simbólicas não aparecem nestes indicadores.
A coleta roda em `coleta.yml`, depois de `siscam` e `documentos`, para resolver as referências da pauta
com os dados já coletados. Por padrão, lista o ano anterior e o atual; na execução manual, o input
`anos_sessoes` aceita um ano ou intervalo (por exemplo, `2021-2026`), e vazio mantém o padrão.
O input `forcar` também rebaixa os detalhes das sessões listadas, respeitando o limite padrão de
400 detalhes por execução e o prazo, com 4 workers padrão. O passo permite falhas (`continue-on-error`),
tem limite de 30 minutos, `timeout --kill-after=2m 25m` e prazo interno `--max-minutos 20` para gravar
o progresso de forma limpa; detalhes que ficam para depois permanecem pendentes.

## Mapa das indicações por bairro

O mapa SVG de `atividades.html` usa as mesmas contagens das tabelas dos 52 bairros, inclusive zeros,
sem JavaScript. Mostra valores absolutos, **não taxas por habitante nem pedidos atendidos**; o bairro é
inferido da ementa por regras, e a nota informa a porcentagem sem bairro (fora do mapa). São até cinco
faixas por quantis dos valores positivos, sem dividir empates; com poucos valores distintos, há menos faixas.
Os cortes são arredondados só entre valores observados, preservando os grupos e evitando classes vazias.
Zero tem faixa própria hachurada quando presente. A legenda mostra os limites reais e o número de bairros
por faixa. Há títulos por bairro e tabela alternativa; cores de mapas com limites diferentes não são comparáveis.
Nas páginas dos vereadores, o bloco inteiro (SVG, legenda, tabela e atribuição) só entra se medir
até 12 KiB gzip; acima disso, permanecem as tabelas por legislatura. Sem geometria, o site gera normalmente,
com os gráficos e tabelas anteriores. Com a geometria atual (base OSM de 23/10/2026), o orçamento individual
é excedido e o mapa é exibido apenas em Atividades.

**Fonte dos limites:** © contribuidores do [OpenStreetMap](https://www.openstreetmap.org/copyright),
[ODbL 1.0](https://www.openstreetmap.org/copyright), relações `boundary=administrative`, `admin_level=10`
dentro de Niterói ([relação 2220789](https://www.openstreetmap.org/relation/2220789)); as tags indicam origem
IBGE. A extração inicial fornecida usa a base OSM de **23/10/2026**. Seu timestamp exato é preservado no JSON
e exibido no mapa. A geometria derivada continua sob ODbL: não é um mapa cadastral nem uma confirmação
municipal dos limites. Os 52 nomes dessa extração coincidem com `BAIRROS_NITEROI`, sem divergências;
a normalização ignora acentos, caixa e pontuação e aceita as variantes já cadastradas, sem mudar as regras das ementas.

Para atualizar, salve uma resposta JSON do Overpass com a consulta abaixo (não faz parte da coleta semanal):

```text
[out:json][timeout:180];
rel(2220789);
map_to_area->.municipio;
rel(area.municipio)["boundary"="administrative"]["admin_level"="10"];
out geom;
```

Depois, na raiz:

```text
python -m coletor.geo --entrada bairros-overpass.json
python -m coletor.validar
python -m coletor.gerar_site
```

O conversor offline encadeia ways por pontas exatas (invertendo quando necessário), separa `outer` e `inner`
e falha com aviso se um anel não fechar. Usa projeção equiretangular local em metros, com `cos(latitude média
dos extremos)`: a extensão municipal pequena dispensa a distorção de escala de Mercator. Aplica
Douglas–Peucker **por way compartilhado**, uma vez só para os dois bairros, preservando suas pontas e o mínimo
lexicográfico. Assim as fronteiras comuns não ganham frestas por simplificações independentes.
Anéis fechados são divididos em duas metades antes do DP; o preenchimento SVG `evenodd` preserva os buracos.
Descarta recortes menores que 400 m² ou invisíveis na grade; arredonda para inteiros num viewBox de largura
1000, com altura proporcional e margem. Se aparecer anel degenerado ou com cruzamento próprio, reduz a
tolerância global, inclusive até zero, ou falha sem sobrescrever a geometria anterior.
Isso protege contornos comuns, mas não substitui uma validação topológica cadastral.

A tolerância inicial é **25 m** (`--tolerancia` para alterá-la). O comando pode aumentá-la até 100 m para
atingir **no máximo 60 KiB brutos**; imprime a tolerância efetivamente usada, bytes brutos e gzip antes da
verificação visual do site. Não usa relógio nem rede: a mesma entrada gera os mesmos bytes. Revise o relatório,
o mapa e os limites antes de versionar apenas `data/geo/bairros.json`; não edite esse arquivo à mão.

## Contribuir

- **Composição das legislaturas e afastamentos**: `config/vereadores.json`.
- **Curadoria de alertas**: `config/curadoria.json`. Toda entrada precisa de fonte pública. A curadoria prevalece sobre a IA.
- **Classificação errada**: use o link "contestar" no site, que abre uma issue.

Os critérios valem igualmente para qualquer autor, partido ou espectro político. A [metodologia](coletor/site/paginas.py) completa é publicada no próprio site.

## Licença

Código: [GNU General Public License v3.0](LICENSE). Geometria dos bairros derivada do OpenStreetMap:
© contribuidores do OpenStreetMap, sob [ODbL 1.0](https://www.openstreetmap.org/copyright).
