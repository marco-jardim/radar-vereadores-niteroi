// Aplica as migrações de worker/migrations ao D1 local antes dos testes (idempotente).
import { applyD1Migrations, env } from "cloudflare:test";
import { beforeEach } from "vitest";
import { isolarCache } from "./dados";

await applyD1Migrations(env.DB, env.TEST_MIGRATIONS);

// Isola também embeddings, cuja chave ignora índice, modo e filtros por contrato.
// Dentro de cada teste a origem fica estável, inclusive se carregar() renovar o índice.
beforeEach(isolarCache);
