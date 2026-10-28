// Tipos mínimos dos bindings usados pelo Worker (declarados aqui, sem @cloudflare/workers-types).
// Só descrevem o que o código chama; o runtime real e o miniflare dos testes os satisfazem.

export interface D1Resultado<T> {
  results: T[];
  success: boolean;
}

export interface D1Instrucao {
  bind(...valores: unknown[]): D1Instrucao;
  all<T = Record<string, unknown>>(): Promise<D1Resultado<T>>;
  first<T = Record<string, unknown>>(): Promise<T | null>;
}

export interface D1Database {
  prepare(sql: string): D1Instrucao;
  batch<T = Record<string, unknown>>(instrucoes: D1Instrucao[]): Promise<D1Resultado<T>[]>;
}

export interface R2Objeto {
  key: string;
  size: number;
}

export interface R2ObjetoCorpo extends R2Objeto {
  body: ReadableStream;
}

export interface R2Bucket {
  get(chave: string): Promise<R2ObjetoCorpo | null>;
  head(chave: string): Promise<R2Objeto | null>;
}

export interface CorrespondenciaVetor {
  id: string;
  score: number;
  metadata?: Record<string, unknown>;
}

export interface OpcoesConsultaVetor {
  topK: number;
  returnMetadata?: "none" | "indexed" | "all";
  returnValues?: boolean;
  filter?: Record<string, unknown>;
}

export interface VectorizeIndex {
  query(vetor: number[], opcoes: OpcoesConsultaVetor): Promise<{ matches: CorrespondenciaVetor[] }>;
}

export interface Ai {
  run(modelo: string, entrada: Record<string, unknown>): Promise<unknown>;
}

export interface RateLimit {
  limit(opcoes: { key: string }): Promise<{ success: boolean }>;
}

export interface AnalyticsEngineDataset {
  writeDataPoint(ponto: { blobs?: string[]; doubles?: number[]; indexes?: string[] }): void;
}

export interface MetadadosVersao {
  id: string;
  tag: string;
  timestamp: string;
}

export interface ContextoExecucao {
  waitUntil(promessa: Promise<unknown>): void;
  passThroughOnException(): void;
}

export interface Env {
  DB: D1Database;
  ARQUIVOS: R2Bucket;
  VETORES?: VectorizeIndex;
  AI?: Ai;
  LIMITE?: RateLimit;
  METRICAS?: AnalyticsEngineDataset;
  CF_VERSION_METADATA?: MetadadosVersao;
  /** `production`, `staging` ou outro rótulo; só informativo em /api/versao. */
  AMBIENTE?: string;
  /** Origens CORS separadas por vírgula (config/backend.json → origens_cors, injetadas no deploy). */
  ORIGENS_CORS?: string;
  /** Raiz pública do site, usada no link da política de privacidade. */
  URL_SITE: string;
  /** Commit do código publicado (`wrangler deploy --var COMMIT:<sha>`). */
  COMMIT?: string;
}
