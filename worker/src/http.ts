// Respostas JSON, erros, CORS e Cache API.
import type { ContextoExecucao } from "./ambiente";

/** Erro com status HTTP e código estável; vira `{erro, codigo}` sem pilha. */
export class ErroHttp extends Error {
  readonly status: number;
  readonly codigo: string;
  readonly cabecalhos: Record<string, string>;

  constructor(status: number, codigo: string, mensagem: string, cabecalhos: Record<string, string> = {}) {
    super(mensagem);
    this.status = status;
    this.codigo = codigo;
    this.cabecalhos = cabecalhos;
  }
}

const TIPO_JSON = "application/json; charset=utf-8";

export function json(dados: unknown, status = 200, cabecalhos: Record<string, string> = {}): Response {
  const h = new Headers(cabecalhos);
  h.set("Content-Type", TIPO_JSON);
  return new Response(JSON.stringify(dados), { status, headers: h });
}

export function respostaErro(e: ErroHttp): Response {
  return json({ erro: e.message, codigo: e.codigo }, e.status, { ...e.cabecalhos, "Cache-Control": "no-store" });
}

/** Erro inesperado: mensagem genérica, sem a mensagem nem a pilha originais. */
export function erroInterno(): ErroHttp {
  return new ErroHttp(500, "interno", "Erro interno.");
}

// ---- CORS

const RE_LOCAL = /^http:\/\/(localhost|127\.0\.0\.1)(:[0-9]{1,5})?$/;

/** Origens HTTPS exatas de `ORIGENS_CORS`; localhost/127.0.0.1 em HTTP só no staging. */
export function origemPermitida(origem: string, lista: string | undefined, ambiente?: string): boolean {
  if (RE_LOCAL.test(origem)) return ambiente === "staging";
  try {
    const url = new URL(origem);
    if (url.protocol !== "https:" || url.origin !== origem ||
      url.hostname === "localhost" || url.hostname === "127.0.0.1") return false;
  } catch {
    return false;
  }
  for (const item of (lista ?? "").split(",")) {
    if (item.trim() !== "" && item.trim() === origem) return true;
  }
  return false;
}

export const METODOS = "GET, HEAD, OPTIONS";

export function preflight(): Response {
  return new Response(null, {
    status: 204,
    headers: {
      "Access-Control-Allow-Methods": METODOS,
      "Access-Control-Max-Age": "86400",
      "Cache-Control": "no-store",
    },
  });
}

// ---- Cache API (antes de servir um original, a tabela `remocoes` já foi consultada)

function cache(): Cache | null {
  return typeof caches !== "undefined" && caches.default ? caches.default : null;
}

export async function lerCache(chave: string): Promise<Response | null> {
  const c = cache();
  if (!c) return null;
  return (await c.match(new Request(chave))) ?? null;
}

/** Guarda uma cópia da resposta por `segundos`, sem atrasar a resposta ao cliente. */
export function guardarCache(ctx: ContextoExecucao, chave: string, resposta: Response, segundos: number): void {
  const c = cache();
  if (!c || resposta.status !== 200) return;
  const h = new Headers(resposta.headers);
  h.set("Cache-Control", `public, max-age=${segundos}`);
  h.set("X-Radar-Cache", "HIT");
  const copia = new Response(resposta.clone().body, { status: 200, headers: h });
  ctx.waitUntil(c.put(new Request(chave), copia).catch(() => undefined));
}

/** Valor seguro para cabeçalho: só caracteres de identificadores, até 100. */
export function valorCabecalho(valor: string | null | undefined, padrao: string): string {
  const limpo = (valor ?? "").replace(/[^A-Za-z0-9._:+-]/g, "").slice(0, 100);
  return limpo === "" ? padrao : limpo;
}

export async function sha256Hex(texto: string): Promise<string> {
  const dados = new TextEncoder().encode(texto);
  const resumo = await crypto.subtle.digest("SHA-256", dados);
  return [...new Uint8Array(resumo)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
