# Radar dos Vereadores de Niterói

Site aberto sobre a produção da Câmara Municipal de Niterói desde 2021: quem apresenta projetos de lei,
quais viram lei, seu efeito estimado e quanto da produção é homenagem, projeto repetido ou pauta polêmica.
Também reúne outros documentos legislativos, presença em plenário e votações nominais.

[Acesse o site](https://marco-jardim.github.io/radar-vereadores-niteroi/).
Os dados vêm do [SISCAM da Câmara Municipal de Niterói](https://consultaniteroi.siscam.com.br/).
A coleta é programada semanalmente pelo GitHub Actions; o site é estático, publicado no GitHub Pages.

## O que você encontra

| Página | Conteúdo |
| --- | --- |
| Início (`index.html`) | Placar por vereador e leis com efeito mais recentes. |
| Novidades (`novidades.html`) | Apresentações de PLs, leis, vetos e vetos derrubados; também em RSS (`feed.xml`). |
| Leis aprovadas (`leis.html`) | Leis com filtros por impacto, tema, vereador e partido. |
| Projetos (`projetos.html`) | Projetos de lei, inclusive em tramitação e sem êxito. |
| Atividades (`atividades.html`) | Requerimentos, indicações, moções, PDLs e resoluções, com filtros e resumos. |
| Sessões (`sessoes.html`) | Presença por legislatura, votações nominais, mapa de votos, ritmo e cobertura. |
| Sem efeito e polêmicas (`ruido.html`) | Produção simbólica, projetos sem efeito, alertas e homenagens. |
| Análises (`analises.html`) | Gráficos históricos e comparações da produção legislativa. |
| Metodologia (`metodologia.html`) | Critérios, fontes e limitações. |

As páginas em `vereadores/` reúnem projetos, **Presença e votos** e, quando há documentos coletados,
**Atividade**. Os demais documentos não entram nos números de projetos de lei e leis.
O endereço antigo `alertas.html` redireciona para `ruido.html`; `dados/` contém os JSONs de consulta e exportação.

**Limites importantes:** impacto é estimado pela ementa, não resultado comprovado. Contar documentos,
presenças ou votos não mede a qualidade do mandato. Os critérios valem igualmente para qualquer autor,
partido ou espectro político; classificações e dados podem ser contestados.

## Como funciona

O fluxo é **projetos → documentos → sessões → classificação → validação → geração do site**:

1. Os três coletores (`siscam`, `documentos`, `sessoes`) gravam os dados em `data/` e estatísticas em
   `data/meta.json`. Detalhes de documentos são seletivos; documentos e sessões têm limites e fila de pendentes.
2. A classificação dos PLs combina curadoria com fontes, regras e cache da IA via OpenCode Go. A IA avalia
   a ementa; novas chamadas dependem de chave e da combinação ementa, versão do prompt e modelo.
   Sem chave ou com `--sem-ia`, não há novas chamadas, mas o site continua usando o cache existente.
3. Demais documentos e sessões são interpretados só por regras, sem IA. O validador não altera arquivos.
4. O gerador recria `site/`, com HTML, gráficos SVG e tabelas acessíveis. JavaScript permite filtrar listas;
   os resumos são gerados em HTML e não mudam com os filtros. Novidades e RSS derivam das datas dos PLs,
   sem comparar coletas: são 12 semanas até a última semana com evento nos dados, não necessariamente até hoje.

Não edite `data/` nem `site/` à mão. O [guia para agentes e contribuidores técnicos](AGENTS.md)
descreve módulos, opções dos comandos, contratos e cuidados com a coleta.

## Automação e publicação

- **Testes** (`.github/workflows/testes.yml`): em PRs, pushes fora de `main` e chamadas reutilizáveis;
  executa testes Python/JavaScript, valida os dados e gera o site, com Python 3.12 e Node 22.
- **Coleta** (`coleta.yml`): segunda-feira às 06:17 (Brasília), ou manualmente. Os inputs `anos`,
  `anos_documentos`, `anos_sessoes` e `forcar` controlam os coletores. Falhas em documentos/sessões são
  toleradas; se a validação ou os testes falharem, essas mudanças são descartadas e ambos rodam novamente.
  O commit abrange `data/` inteiro; em caso de falha, há um artefato de recuperação por 14 dias.
- **Site** (`site.yml`): após coleta bem-sucedida, execução manual ou push em `main` nos caminhos monitorados
  de código, configuração, dados, testes e workflows de site/testes. Testa `main` e publica o SHA aprovado.

Para publicar uma cópia, em **Settings → Pages**, escolha **Source: GitHub Actions**.
Para novas chamadas à IA na coleta, configure o secret de Actions `OPENCODE_API_KEY`.
A variável de Actions `OPENCODE_MODEL` é opcional (padrão: `deepseek-v4.1-flash`).

## Rodar localmente

Use **Python 3.12+**, sem dependências externas. Os testes JavaScript requerem **Node 21+** (CI: 22).
Com os dados já versionados, não é preciso coletar nem ter chave de IA:

```text
python -m coletor.validar
python -m coletor.gerar_site
python -m http.server -d site 8000
```

Abra `http://localhost:8000`. Para atualizar os dados, execute na raiz, nesta ordem, escolhendo o ano:

```text
python -m coletor.siscam --anos 2026
python -m coletor.documentos --anos 2026
python -m coletor.sessoes --anos 2026
python -m coletor.classificar --sem-ia
python -m coletor.validar
python -m coletor.gerar_site
```

`--anos` aceita um ano ou intervalo inclusivo (`2025-2026`). Sem a opção, projetos vão de 2021 ao ano atual;
documentos e sessões, do ano anterior ao atual. Coletar acessa o SISCAM; evite `--forcar` sem necessidade.
Para habilitar novas classificações por IA, em POSIX:

```sh
OPENCODE_API_KEY=... python -m coletor.classificar
```

No PowerShell:

```powershell
$env:OPENCODE_API_KEY = "..."
python -m coletor.classificar
```

As variáveis são lidas do processo, não de `.env`. Não exponha chaves em commits ou logs.
Testes offline, sem acesso ao SISCAM nem à IA:

```text
python -m unittest discover -s tests -t .
node --test "tests/js/**/*.test.js"
```

## Presença, votos e bairros

Sessões têm tabelas e cartões disponíveis sem JavaScript. Com JavaScript, há filtros por ano, classe,
matéria, vereador e busca, ordenação, "Mostrar mais" e CSV (UTF-8 com BOM e fórmulas neutralizadas).
Os filtros ficam na URL; escolher um ano atualiza o mapa de votos e "todos" restaura o mapa inicial.
O filtro de voto diferente da maioria exige vereador e comparação determinada: não é avaliação de qualidade.

Só sessões deliberativas realizadas com lista entram na presença; licenças ficam fora da base individual.
Favor/Contra é voto sobre o parecer, não automaticamente sobre a matéria. Sentidos indeterminados ficam
explícitos; placares inconsistentes não atribuem votos a nomes. Suplentes sem página são identificados,
sem link. Comissões, debates e votações simbólicas não estão nesses indicadores.
Veja as regras em `metodologia.html#sessoes` no site.

Em Atividades, o mapa SVG de indicações usa os mesmos agregados das tabelas dos 52 bairros, sem JavaScript.
São **valores absolutos, não taxas por habitante nem pedidos atendidos**; o bairro é inferido da ementa.
A porcentagem sem bairro fica fora do mapa. As cores representam até cinco faixas de valores positivos,
sem separar empates, e zero é hachurado; mapas com limites diferentes não têm cores comparáveis.
Sem geometria, permanecem gráficos e tabelas; em páginas individuais, o mapa só entra se couber no orçamento.

Os limites simplificados vêm do OpenStreetMap, com data da base exibida no mapa: não são mapa cadastral
nem confirmação municipal dos limites. A geometria é opcional e atualizada separadamente da coleta semanal.
Para obter uma nova entrada, salve localmente uma resposta JSON do Overpass com:

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

O conversor é offline. Revise seu relatório, o mapa e os limites antes de versionar
`data/geo/bairros.json`; não edite a geometria à mão. Detalhes técnicos e orçamentos estão no [AGENTS.md](AGENTS.md).

## Contribuir e contestar

- **Erro nos dados ou na classificação:** use "contestar" no site ou
  [abra uma issue](https://github.com/marco-jardim/radar-vereadores-niteroi/issues/new), com documento e fonte.
- **Composição das legislaturas e afastamentos:** `config/vereadores.json`; preserve o partido da eleição.
- **Curadoria:** `config/curadoria.json`. Toda entrada precisa de fonte pública; a curadoria prevalece sobre a IA.
- **Memória:** `config/memoria.json` reúne critérios, homenageados e linha do tempo, com fontes públicas HTTPS;
  é conferido por `coletor.validar`.
- **Código:** consulte [AGENTS.md](AGENTS.md), faça mudanças focadas e execute os testes offline.

A metodologia completa é publicada no próprio site. Correções editoriais vão na configuração,
não nos arquivos coletados.

## Fontes e licenças

- Documentos e sessões: [SISCAM da Câmara Municipal de Niterói](https://consultaniteroi.siscam.com.br/).
- Composição e curadoria: fontes públicas registradas nos arquivos de `config/`.
- Código: [GNU General Public License v3.0 (GPL-3.0)](LICENSE).
- Fontes tipográficas: Barlow Condensed, Public Sans e Fraunces, sob SIL Open Font License 1.1;
  arquivos WOFF2 e licenças `OFL-*.txt` em `site_src/fontes/`. O site não carrega fontes de terceiros.
- Geometria derivada: © contribuidores do [OpenStreetMap](https://www.openstreetmap.org/copyright),
  sob [ODbL 1.0](https://www.openstreetmap.org/copyright), bairros administrativos de nível 10 dentro de
  [Niterói, relação 2220789](https://www.openstreetmap.org/relation/2220789).
  Preserve atribuição e data da base OSM ao reutilizar os mapas.
