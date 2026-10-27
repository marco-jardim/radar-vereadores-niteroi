# Perfis dos vereadores: TSE e verificação semanal

Trecho para incorporar ao AGENTS.md e ao README.

## Comandos

```text
python -m coletor.tse --anos 2020,2024,2026 [--cache DIR] [--sem-download]
python -m coletor.vereadores_semanal [--saida relatorio.md] [--com-rede]
```

- `coletor.tse` baixa os arquivos do TSE para `--cache` (padrão: `<temp>/radar-tse`, fora do repositório)
  e atualiza `config/perfis.json` no mesmo lugar. `--anos` aceita anos pares separados por vírgula ou um
  intervalo (`2020-2026`, só os pares). Com `--sem-download`, usa só o que já está no cache; arquivo
  ausente faz o ano (ou só os votos/redes dele) ficar como está. Antes de baixar, um `HEAD` compara
  ETag/Last-Modified com `versoes.json` do cache; o `GET` é condicional (`If-None-Match`/`If-Modified-Since`).
  Os zips são lidos em fluxo (a votação de 2026 passa de 400 MB). Layout alterado (coluna obrigatória
  ausente) encerra com código 1 sem gravar.
- `coletor.vereadores_semanal` só lê `data/` e `config/` e escreve um relatório Markdown; termina sempre com
  código 0. A última linha do relatório é `<!-- achados: N -->`; com N = 0 aparece "Sem diferenças em relação à
  configuração." e a saída padrão imprime `sem diferenças`.

## Fontes

- Candidaturas: `https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_<ano>.zip`
  (conjunto `https://dadosabertos.tse.jus.br/dataset/candidatos-<ano>`).
- Redes declaradas no registro: `.../consulta_cand/rede_social_candidato_<ano>.zip` (mesmo conjunto).
- Votos: `.../votacao_candidato_munzona/votacao_candidato_munzona_<ano>.zip`
  (conjunto `https://dadosabertos.tse.jus.br/dataset/resultados-<ano>`).
- Só os CSVs `_RJ` e `_BR` (latin-1, `;`); `_BRASIL` e outras UFs ficam de fora.
- Composição e partidos publicados pela Câmara: `https://www.camaraniteroi.rj.gov.br/site/vereadores/` (`--com-rede`).

## Regras do importador

- Pessoas: eleitos de `config/vereadores.json` e chaves de `config/perfis.json`. Casamento exato, sem acentos e em
  maiúsculas, pelo `NM_CANDIDATO` (ou `NM_SOCIAL_CANDIDATO`); nomes do SISCAM com sufixo ` - APELIDO` também são
  tentados sem ele. Cargo municipal só em Niterói (homônimos de outros municípios são ignorados); cargo estadual ou
  federal exige uma única candidatura no RJ.
- Sem casamento pelo nome do SISCAM, os nomes civis de `coletor.tse.APELIDOS_TSE` (nome do SISCAM → outras grafias
  no TSE, cada uma com a fonte da conferência em comentário) são tentados como nome exato, com as mesmas regras de
  ambiguidade; o resumo mostra "casado por apelido (confirmado)".
- Identidades confirmadas também podem ser fixadas por ano e `SQ_CANDIDATO` em
  `coletor.tse.CANDIDATURAS_FIXADAS`, antes de qualquer casamento por nome. Só vale o SQ exato;
  se ele não constar no arquivo, não há alternativa automática naquele ano. O resumo mostra
  "fixado por SQ (confirmado)", com a chave SISCAM e o SQ, sem expor o nome civil do registro.
- Sem casamento exato nem por apelido, duas alternativas, só entre candidaturas de Niterói (vereador, prefeito, vice) e do RJ:
  nome de urna (`NM_URNA_CANDIDATO`, com e sem títulos como DR, PROFESSOR, PASTOR, DELEGADO, CORONEL) igual ao nome
  do SISCAM ou ao apelido depois de ` - `; depois, o nome do SISCAM (≥ 3 palavras) como subsequência ordenada do nome
  civil, com primeira e última palavras iguais. Cada alternativa só vale com um único candidato; o resumo lista esses
  casamentos para conferência, e um casamento aproximado que reusa a candidatura de outra pessoa vira homônimo.
  Casos que nenhuma alternativa resolve entram em `APELIDOS_TSE`.
- Várias candidaturas da mesma pessoa no ano (troca de cargo, renúncia): ficam as aptas
  (`DS_SITUACAO_CANDIDATURA` = APTO ou detalhe deferido) e, se houver resultado divulgado, só as sem `#NULO`.
  Restando uma, ela vale; senão, o caso fica de fora com `::warning::` ("ambíguo"/"homônimo") e o que havia é mantido.
- `eleicoes`: nos anos processados, a candidatura encontrada substitui os itens do ano; sem candidatura, só os itens
  com fonte do TSE saem; anos não processados ficam intactos. Ordem: mais recente primeiro. Cargo em título
  ("Deputado Estadual"), partido na grafia do site (`PC do B` → `PCdoB`, `UNIÃO` → `União Brasil`, `PODE` → `Podemos`
  etc.), resultado em caixa de frase (`#NULO`/`#NE` → "Resultado não divulgado"). Votos: soma de
  `QT_VOTOS_NOMINAIS` em todas as zonas e municípios do RJ, do último turno; `null` sem arquivo de votação, sem
  linhas do candidato ou em cargo nacional.
- `redes`: as da candidatura mais recente encontrada, com `fonte` do conjunto do TSE daquele ano (o registro de
  candidatura é declaração a órgão oficial e conta como fonte oficial, como diz o AGENTS.md); URLs em https, sem
  parâmetros de rastreio (`igsh`, `utm_*`, `fbclid`, `si`…), fragmento nem barra final. Outros hosts preenchem `site`
  só se ele estiver vazio. Redes com outra fonte são preservadas se não repetirem a URL.
- `mandatos[leg].votos` ausente é preenchido pela eleição municipal anterior (2020 → 2021-2024, 2024 → 2025-2028),
  só com votos positivos, acrescentando a fonte dos resultados do TSE. Eleito ausente do arquivo entra com partido e
  fonte da legislatura da configuração e situação `eleito`.
- Saída canônica: `json.dumps(..., ensure_ascii=False, indent=1)` + LF, ordem das chaves preservada, gravação atômica;
  a mesma entrada produz os mesmos bytes.

## Verificação semanal

- (a) Autores com papel de vereador em PLs e documentos da legislatura atual fora dos eleitos dela e sem perfil:
  "possível suplente em exercício", com até três links do SISCAM.
- (b) Eleitos com licença na frequência das sessões deliberativas do ano atual (`regras_sessoes.presencas_da_sessao`)
  sem entrada em `afastamentos`: "possível licença/afastamento", com links das sessões.
- (c) Com `--com-rede`, partidos do site da Câmara diferentes do mandato atual em `config/perfis.json` (ou do partido
  da eleição). Exige ao menos 10 pares nome–partido reconhecidos; senão, "estrutura desconhecida". Erro HTTP ou de rede
  vira "indisponível". Nenhum desses dois estados conta como achado, nem nomes do site sem correspondência.

## Workflow `vereadores.yml`

- Terças, 10:23 UTC, e manual. Restaura o cache do TSE (`actions/cache`, chave pelo SHA-256 de `versoes.json`), roda
  `coletor.tse`, a verificação semanal, `coletor.validar` e os testes de perfis/TSE. Falha de validação ou de teste
  encerra o job sem PR.
- Se `config/` mudou ou o relatório tem achados, recria o ramo `atualiza-vereadores` a partir de `main`, faz commit como
  `github-actions[bot]` ("Atualiza perfis dos vereadores com dados do TSE"; sem mudança, um commit vazio para as
  detecções), envia com `--force` só para esse ramo e abre ou atualiza um único PR para `main`, com o relatório e a
  lista de arquivos no corpo. Nunca altera `data/` (falha se isso acontecer) nem envia para `main`.
- O ramo é recriado a cada execução: não faça commits manuais nele; corrija em outro ramo.
- Requisitos do repositório: "Allow GitHub Actions to create and approve pull requests" habilitado. PRs abertos com
  `GITHUB_TOKEN` não disparam outros workflows; rode os testes no PR (por exemplo, reabrindo-o ou com um push manual).

## Limites

- O TSE não publica mais as listas individuais de filiação partidária: trocas de partido no meio do mandato não são
  detectadas pelo importador; só aparecem pela comparação com o site da Câmara, quando ele responde e tem estrutura
  reconhecível.
- O site da Câmara pode estar fora do ar ou mudar de layout; nesses casos a verificação (c) só informa.
- Homônimos no RJ em cargos estaduais/federais e nomes do SISCAM que nem o nome de urna nem o nome civil parcial
  resolvem ficam sem casamento; acrescente a grafia do TSE em `coletor.tse.APELIDOS_TSE` ou complete à mão em
  `config/perfis.json`, com fonte. O casamento parcial pode, raramente, achar outra pessoa de nome parecido no RJ:
  confira os casamentos aproximados listados no resumo antes de aprovar o PR.
- Contagens e detecções são pistas para revisão humana, não confirmação de licença, suplência ou filiação.
