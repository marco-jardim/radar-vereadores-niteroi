# Worker de busca (`radar-niteroi-api`)

API só de leitura sobre D1 (FTS5), Vectorize (`@cf/baai/bge-m3`, 1.024 dimensões) e R2 privado, conforme
`docs/contratos/textos.md` (seção 8) e a Phase 3.2 do plano `docs/plans/2026-10-27-inteiro-teor-busca-cloudflare.md`.
Recursos, credenciais, deploy e rollback: `docs/backend.md`.

## Rotas

Todas aceitam `GET`, `HEAD` e `OPTIONS`; os erros saem como `{"erro": "...", "codigo": "..."}`, sem pilha.

| Rota | Resposta | Cache API |
| --- | --- | --- |
| `GET /api/busca?q=&modo=palavras\|semantica\|hibrida&tipo=&ano=&autor=&legislatura=&pagina=` | `{consulta, modo, filtros, pagina, por_pagina, total, limitado, resultados, aviso?}` | 60 s |
| `GET /api/documento/:id` (`doc:<n>` ou `sessao:<n>`) | `{documento, autoria, arquivos, substitutivos}`; 404 se não existe | 1 dia |
| `GET /api/original/:sha256` | o original, como download; 410 se removido; 404 sem arquivo | 1 dia (interno) |
| `GET /api/versao` | `{ambiente, codigo: {commit, versao, tag, publicado_em}, indice}` | não |
| `GET /api/saude` | `{ok, d1, indice, verificacao}`; 503 sem D1 | não |

**Busca.** `q` tem de 2 a 200 caracteres e ao menos uma letra ou um dígito; `modo` padrão `hibrida`; `tipo` entre
`pl`, `substitutivo`, `requerimento`, `indicacao`, `mocao`, `pdl`, `resolucao` e `ata`; `ano` com 4 dígitos;
`legislatura` `AAAA-AAAA`; `autor` é o slug; `pagina` de 1 a 50, com 10 resultados por página e um resultado por
documento. Parâmetro inválido ou repetido: 400.

- **Palavras:** a consulta é normalizada como `coletor.nuvem.fonte.normalizar_busca`
  (`s.normalize("NFD").replace(/\p{Mn}/gu, "").normalize("NFC").toLowerCase()`), dividida por espaços e cada termo
  vira uma frase FTS5 entre aspas (aspas internas duplicadas): `OR`, `NOT`, `NEAR(`, `*`, `^`, `col:` e parênteses
  são só texto. `trechos_fts` é ligada a `trechos` por `id` (nunca por `rowid`), ordenada por `bm25` e depois pelo id;
  até 500 trechos, o melhor por documento (`limitado: true` quando o teto é atingido).
- **Significado:** embedding da consulta (`@cf/baai/bge-m3`), `topK = 50` com `returnMetadata: "indexed"` e filtros
  `tipo`, `ano` e `legislatura` nos metadados; documento, autor e demais campos vêm do D1, e vetor sem linha no D1
  é descartado. As ementas de indicações e moções (`ementa:doc:<id>`) entram aqui.
- **Híbrida:** RRF com k = 60 sobre os 50 primeiros documentos de cada lista, empate pelo id do documento. Se AI ou
  Vectorize falham, cai para palavras com `aviso` (e a resposta não vai para o cache); em `semantica`, 503.
- **Resultado:** `documento, tipo, numero, ano, ementa, trecho, arquivo, status, ocr, confianca, url_siscam,
  url_original, sha256, pontuacao, origem`. Só `trecho` é HTML: texto original escapado, com `<mark>` nas palavras
  da consulta; `ementa` é texto puro. `url_original` é relativa (`/api/original/<sha256>`).
- **Filtro por autor:** `autoria` do documento principal ou de qualquer documento que cite o arquivo do trecho
  (`arquivo_documento`, por exemplo o coautor de um substitutivo).

**Remoções.** Trechos e arquivos cuja chave ou SHA-256 esteja em `remocoes` nunca saem na busca nem no documento.
O original consulta `remocoes` no D1 **antes** da Cache API e responde 410; as chaves de cache da busca e do
documento incluem um resumo de `estado_indice`, então nenhuma resposta guardada sobrevive a uma sincronização.

**Originais.** Do bucket privado `ARQUIVOS`, na `r2_chave` do D1 (conferida contra o SHA-256), com
`Content-Disposition: attachment; filename="siscam-<id>.<ext>"`, `X-Robots-Tag: noindex`,
`X-Content-Type-Options: nosniff`, `Content-Security-Policy: sandbox` e `Cache-Control: no-store` para o cliente.

**Cabeçalhos comuns.** `X-Radar-Commit` (variável `COMMIT`), `X-Radar-Indice` (`estado_indice.versao`, ou `vazio`),
`X-Radar-Cache` (`HIT`/`MISS`), `Vary: Origin`, `X-Content-Type-Options: nosniff` e, no JSON,
`Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`.

**CORS.** Só as origens de `ORIGENS_CORS` (lista separada por vírgulas de `config/backend.json` → `origens_cors`) e
`http://localhost[:porta]`/`http://127.0.0.1[:porta]`. Outra origem recebe 403 `origem_recusada`; sem `Origin`
(curl, link direto), a resposta não leva cabeçalhos CORS.

**Privacidade e limites.** Sem `console.log`, observabilidade desligada e sem Logpush; o Rate Limiting (`LIMITE`,
60 por minuto) usa um resumo SHA-256 do IP como chave e responde 429 com `Retry-After: 60`; `METRICAS` recebe só
o modo e a contagem de resultados. Consultas SQL só com parâmetros.

**Cache.** A Cache API não funciona em `*.workers.dev` (as operações viram no-op); com domínio próprio, passa a
valer sem mudança no código.

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

O `wrangler.jsonc` declara o cron `17 7 * * *`, mas o handler `scheduled` (verificação por amostragem em
`verificacoes`) é da Phase 4.2.
