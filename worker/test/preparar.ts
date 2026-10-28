// Aplica as migrações de worker/migrations ao D1 local antes dos testes (idempotente).
import { applyD1Migrations, env } from "cloudflare:test";

await applyD1Migrations(env.DB, env.TEST_MIGRATIONS);
