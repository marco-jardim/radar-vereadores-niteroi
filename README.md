# Radar dos Vereadores de Niterói

Site aberto que mostra quais leis de Niterói mudam a cidade e quem as escreveu, e quanto da produção da Câmara desde 2021 é homenagem, lei sem efeito prático, projeto repetido ou pauta polêmica.

Páginas: placar por vereador e leis com efeito mais recentes (início), novidades das últimas 12 semanas (projetos de lei apresentados, leis sancionadas ou promulgadas, vetos e vetos derrubados, também no feed RSS `feed.xml`), leis aprovadas com filtros por impacto, tema, vereador e partido, todos os projetos, atividades (indicações, moções, requerimentos, projetos de decreto legislativo e de resolução, com filtros por tipo, ano, vereador, categoria e bairro), sem efeito e polêmicas, análises históricas e metodologia. Cada vereador tem uma página com seus projetos e uma seção "Atividade" com esses documentos, que não entram nos números de projetos e leis.

Os dados vêm do [SISCAM da Câmara Municipal de Niterói](https://consultaniteroi.siscam.com.br/) e são atualizados toda semana por GitHub Actions. O site é estático e fica no GitHub Pages.

## Como funciona

| Etapa | Arquivo | O que faz |
|---|---|---|
| Coleta de projetos | `coletor/siscam.py` | Baixa a lista de projetos de lei de cada ano e, para os novos ou com tramitação alterada, a autoria e a tramitação completa. Grava `data/proposicoes/<ano>.json`. |
| Coleta de documentos | `coletor/documentos.py` | Lista requerimentos, indicações, moções, PDLs e resoluções. Baixa a página de detalhe só de requerimentos, PDLs, resoluções e documentos com mais de um autor, com limite por execução; o que fica para depois é marcado como pendente. Grava `data/documentos/<tipo>/<ano>.json`. |
| Classificação | `coletor/classificar.py` | Nos projetos de lei, combina curadoria (`config/curadoria.json`), regras determinísticas (simbólica, autorizativa, vetos, pareceres, duplicação de lei em vigor) e IA via OpenCode Go, que atribui categoria, tema, impacto (0 a 3), resumo, público afetado e alertas. O resultado fica em cache (`data/classificacao_ia.json`) e só é refeito quando a ementa ou o prompt mudam. |
| Regras dos documentos | `coletor/regras_documentos.py` | Classifica os demais documentos só por regras sobre a ementa, sem IA: categoria, bairro citado nas indicações, data em que o requerimento consta como respondido na tramitação (não necessariamente a data da resposta do Executivo), publicação de PDLs e resoluções, eixos do perfil de atuação (única regra do perfil), órgão citado nos requerimentos de informação e estado do pedido (respondido, aguardando, encerrado ou retirado). Com elas, o site mostra em tabelas, sem novos dados no navegador: homenagens com contagem e peso na produção, por vereador e por ano, em "Sem efeito e polêmicas"; requerimentos de informação por vereador e por órgão e indicações por bairro em "Atividades"; e as três na página de cada vereador. |
| Validação | `coletor/validar.py` | Confere a forma dos dados em `data/` e da configuração em `config/`, sem alterar nada. |
| Novidades | `coletor/novidades.py` | Deriva, na geração do site, os eventos dos projetos de lei a partir das datas já coletadas (apresentação, lei, veto e veto derrubado na tramitação), sem comparar coletas nem gravar estado. A semana mais recente é a da última data encontrada nos dados, não a de hoje. Alimenta `novidades.html` (montada em `paginas.py`) e gera o feed RSS 2.0 `feed.xml`. |
| Site | `coletor/gerar_site.py` e `coletor/site/` | Monta o modelo e as métricas (`modelo.py`), detecta projetos repetidos, gera gráficos SVG com tabela acessível (`graficos.py`) e as páginas (`paginas.py`). Os dados do navegador ficam em `dados/` em arquivos por colunas e partes, listados num manifesto embutido em cada página; os filtros rodam no navegador (`site_src/app.js` e `site_src/dados.js`). `dados/projetos.json` continua sendo gerado, só como exportação. |

Os dados em `data/` são gerados pelos coletores, com um registro por linha, e não devem ser editados à mão.

Os workflows estão em `.github/workflows/`:

- **Testes** (`testes.yml`): em pull requests e pushes fora de `main`, roda os testes Python e JavaScript, valida os dados e gera o site.
- **Coleta semanal** (`coleta.yml`): roda toda segunda-feira às 06:17 (Brasília) ou manualmente, coleta projetos e documentos, classifica, valida e grava os dados no repositório. Se a validação ou os testes falharem, as mudanças nos documentos são descartadas e os demais dados são validados de novo antes do commit.
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

## Contribuir

- **Composição das legislaturas e afastamentos**: `config/vereadores.json`.
- **Curadoria de alertas**: `config/curadoria.json`. Toda entrada precisa de fonte pública. A curadoria prevalece sobre a IA.
- **Classificação errada**: use o link "contestar" no site, que abre uma issue.

Os critérios valem igualmente para qualquer autor, partido ou espectro político. A [metodologia](coletor/site/paginas.py) completa é publicada no próprio site.

## Licença

[GNU General Public License v3.0](LICENSE).
