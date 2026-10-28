# Worker de busca (`radar-niteroi-api`)

API só de leitura sobre D1 (FTS5), Vectorize (`@cf/baai/bge-m3`, 1.024 dimensões) e R2 privado, conforme
`docs/contratos/textos.md` (seção 8) e a Phase 3.2 do plano `docs/plans/2026-10-27-inteiro-teor-busca-cloudflare.md`.
Recursos, credenciais, deploy e rollback: `docs/backend.md`.

## Rotas

Todas aceitam `GET`, `HEAD` e `OPTIONS`; `HEAD /api/busca` responde 200 só com cabeçalhos, sem executar a busca.
Os erros saem como `{"erro": "...", "codigo": "..."}`, sem pilha e com `Cache-Control: no-store`.

| Rota | Resposta | Cache API |
| --- | --- | --- |
| `GET /api/busca?q=&modo=palavras\|semantica\|hibrida&tipo=&ano=&autor=&legislatura=&pagina=` | `{consulta, modo, filtros, pagina, por_pagina, total, limitado, resultados, aviso?}` | 60 s |
| `GET /api/documento/:id` (`doc:<n>` ou `sessao:<n>`) | `{documento, autoria, arquivos, substitutivos}`; 404 se não existe | 60 s |
| `GET /api/original/:sha256` | o original, como download; 410 se removido; 404 sem arquivo | 1 dia (interno, até 10 MiB) |
| `GET /api/versao` | `{ambiente, codigo: {commit, versao, tag, publicado_em}, indice}` | não |
| `GET /api/saude` | `{ok, d1, indice, verificacao}`; 503 sem D1 | não |

**Busca.** `q` tem de 2 a 200 caracteres e ao menos uma letra ou um dígito; `modo` padrão `hibrida`; `tipo` entre
`pl`, `substitutivo`, `requerimento`, `indicacao`, `mocao`, `pdl`, `resolucao` e `ata`; `ano` com 4 dígitos;
`legislatura` `AAAA-AAAA`; `autor` é o slug; `pagina` de 1 a 50, com 10 resultados por página e um resultado por
documento. Parâmetro inválido ou repetido: 400. Consultas só com termos menores que três caracteres ou só
com palavras vazias comuns do português (`de`, `para`, `com`, etc.) recebem 400 `consulta_muito_generica`.

- **Palavras:** a consulta é normalizada como `coletor.nuvem.fonte.normalizar_busca`
  (`s.normalize("NFD").replace(/\p{Mn}/gu, "").normalize("NFC").toLowerCase()`), dividida por espaços e cada termo
  vira uma frase FTS5 entre aspas (aspas internas duplicadas): `OR`, `NOT`, `NEAR(`, `*`, `^`, `col:` e parênteses
  são só texto. Primeiro o FTS5 sozinho seleciona até 5.000 trechos por `rank` (BM25 padrão); só depois vêm as
  junções por `id` (nunca por `rowid`), filtros e remoções. O SQL agrupa por documento e escolhe o melhor trecho
  (empate pelo id) antes do teto de 500 **documentos**. `limitado: true` sinaliza qualquer desses tetos;
  filtros aplicados após o teto de candidatos podem deixar de encontrar documentos além dele.
- **Significado:** embedding da consulta (`@cf/baai/bge-m3`), `topK = 50` com `returnMetadata: "indexed"` e filtros
  `tipo`, `ano` e `legislatura` nos metadados; documento, autor e demais campos vêm do D1, e vetor sem linha no D1
  é descartado. Com `autor`, `topK = 100` (máximo com esses metadados); o filtro posterior no D1 ainda pode
  omitir documentos do autor que estejam além desses 100 vetores. As ementas de indicações e moções
  (`ementa:doc:<id>`) entram aqui.
- **Híbrida:** RRF com k = 60 sobre os 50 primeiros documentos de cada lista, empate pelo id do documento. Se AI ou
  Vectorize falham, cai para palavras com `aviso` (`no-store`, sem cache); em `semantica`, 503.
- **Resultado:** `documento, tipo, numero, ano, ementa, trecho, arquivo, status, ocr, confianca, url_siscam,
  url_original, sha256, pontuacao, origem`. Só `trecho` é HTML: texto original escapado, com `<mark>` nas palavras
  da consulta; `ementa` é texto puro. `url_original` é relativa (`/api/original/<sha256>`).
- **Filtro por autor:** `autoria` do documento principal ou de qualquer documento que cite o arquivo do trecho
  (`arquivo_documento`, por exemplo o coautor de um substitutivo).

**Remoções.** Trechos e arquivos cuja chave ou SHA-256 esteja em `remocoes` nunca saem na busca nem no documento.
O original consulta `remocoes` no D1 **antes** da Cache API e responde 410; as chaves de cache da busca e do
documento incluem um resumo de `estado_indice` **e da lista ordenada de remoções**, lidos no mesmo lote D1.
Assim, uma remoção invalida as respostas guardadas mesmo numa sincronização parcial que não atualize o estado.
O cliente pode guardar busca e documento por no máximo 60 s; originais sempre usam `no-store` para o cliente.

**Originais.** Do bucket privado `ARQUIVOS`, na `r2_chave` do D1 (conferida contra o SHA-256), com
`Content-Disposition: attachment; filename="siscam-<id>.<ext>"`, `X-Robots-Tag: noindex`,
`X-Content-Type-Options: nosniff`, `Content-Security-Policy: sandbox` e `Cache-Control: no-store` para o cliente.
`/api/original` serve o **original sem mascaramento, tal como publicado pelo SISCAM**, como registro público.
Só os textos extraídos (incluindo ementas de busca) são mascarados; o arquivo original não é reescrito.
Objetos maiores que 10 MiB são transmitidos diretamente, sem clonar o stream para a Cache API; GET e HEAD
informam `Content-Length` do R2. O 410 aponta para `${URL_SITE}/metodologia.html#privacidade`.

**Cabeçalhos comuns.** `X-Radar-Commit` (variável `COMMIT`), `X-Radar-Indice` (`estado_indice.versao`, ou `vazio`),
`X-Radar-Cache` (`HIT`/`MISS`), `Vary: Origin`, `X-Content-Type-Options: nosniff` e, no JSON,
`Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`.

**CORS.** Só as origens de `ORIGENS_CORS` (lista separada por vírgulas de `config/backend.json` → `origens_cors`) e
`http://localhost[:porta]`/`http://127.0.0.1[:porta]`. Outra origem recebe 403 `origem_recusada`; sem `Origin`
(curl, link direto), a resposta não leva cabeçalhos CORS.

**Privacidade e limites.** Nenhuma consulta, IP ou erro é registrado; observabilidade desligada e sem Logpush.
O Rate Limiting (`LIMITE`, 60 por minuto) usa um resumo SHA-256 do IPv4 ou prefixo IPv6 /64 como chave e
responde 429 com `Retry-After: 60`; `METRICAS` recebe só
o modo e a contagem de resultados. Consultas SQL só com parâmetros.

**Cache.** A Cache API não funciona em `*.workers.dev` (as operações viram no-op); com domínio próprio, passa a
valer sem mudança no código. O ranking completo é guardado por 60 s por consulta normalizada, modo, filtros,
estado e remoções, **sem página**; a paginação reaproveita a lista. O embedding normalizado é guardado por uma
hora por consulta/modelo, independente dos filtros e do índice (não contém material dos documentos).
Antes de preencher `config/backend.json` → `api_url`, é obrigatório configurar uma rota em domínio próprio
e publicar a nota de privacidade em `metodologia.html#privacidade`, explicando também os originais sem máscara.

## Desenvolvimento

```powershell
npm ci
npm run typecheck   # tsc --noEmit (src/)
npm test            # vitest no pool dos Workers, com cobertura istanbul (mínimo de 90% das linhas de src/)
```

Os testes (`test/*.test.ts`) usam o D1 e o R2 locais do miniflare com as migrações de `migrations/` e a fixture de
30 documentos de `test/dados.ts`; Vectorize, Workers AI, Rate Limiting e Analytics Engine são simulados no `env`.
Os bindings dos testes vêm de `vitest.config.ts`, não do `wrangler.jsonc`, para não abrir sessões remotas.

Deploy (só o orquestrador): `npx wrangler deploy --env staging --var COMMIT:<sha>`. `ORIGENS_CORS` fica em `vars`
no `wrangler.jsonc` e precisa acompanhar `config/backend.json` → `origens_cors`.

O `wrangler.jsonc` declara o cron `17 7 * * *`. O handler `scheduled` atual só registra uma mensagem fixa e
retorna, sem consultar nem alterar dados; T4.2.3 implementará a verificação por amostragem em `verificacoes`.
