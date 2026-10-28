// Testes no runtime dos Workers (pool do @cloudflare/vitest-pool-workers), sem rede:
// D1 e R2 locais do miniflare; Vectorize, AI, Rate Limiting e Analytics Engine simulados no `env`
// (test/dados.ts). Os bindings vêm daqui, não do wrangler.jsonc, para não abrir sessões remotas.
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineWorkersConfig, readD1Migrations } from "@cloudflare/vitest-pool-workers/config";

const raiz = path.dirname(fileURLToPath(import.meta.url));

export default defineWorkersConfig(async () => {
  const migracoes = await readD1Migrations(path.join(raiz, "migrations"));
  return {
    test: {
      include: ["test/**/*.test.ts"],
      setupFiles: ["./test/preparar.ts"],
      coverage: {
        provider: "istanbul",
        include: ["src/**/*.ts"],
        exclude: ["src/**/*.d.ts", "src/ambiente.ts"],
        reporter: ["text", "json-summary"],
        thresholds: { lines: 90 },
      },
      poolOptions: {
        workers: {
          singleWorker: true,
          isolatedStorage: false,
          miniflare: {
            compatibilityDate: "2025-03-10",
            d1Databases: ["DB"],
            r2Buckets: ["ARQUIVOS"],
            bindings: {
              TEST_MIGRATIONS: migracoes,
              AMBIENTE: "teste",
              COMMIT: "abc1234",
              ORIGENS_CORS: "https://marco-jardim.github.io",
              NORMALIZACAO: readFileSync(path.join(raiz, "..", "tests", "fixtures", "contratos", "normalizacao.json"), "utf-8"),
              WRANGLER_JSONC: readFileSync(path.join(raiz, "wrangler.jsonc"), "utf-8"),
            },
          },
        },
      },
    },
  };
});
