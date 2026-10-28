// Worker de busca do Radar dos Vereadores de Niterói: só leitura para o público.
// Rotas: /api/busca, /api/documento/:id, /api/original/:sha256, /api/versao e /api/saude.
// Privacidade: nenhuma consulta, IP ou erro é registrado (observabilidade desligada no wrangler.jsonc);
// METRICAS recebe só o modo e a contagem de resultados.
import type { ContextoExecucao, Env } from "./ambiente";
import { rotaBusca } from "./busca";
import { verificar } from "./cron";
import { rotaDocumento } from "./documento";
import { chaveIndice, lerEstado } from "./estado";
import { ErroHttp, METODOS, erroInterno, json, origemPermitida, preflight, respostaErro, sha256Hex, valorCabecalho } from "./http";
import { rotaOriginal } from "./original";

interface Contexto {
  cors: string | null;
  indice: string;
}

/** IPv6 usa a rede /64: alternar o identificador de interface não renova a cota. */
export function clienteLimite(ip: string): string {
  if (!ip.includes(":")) return ip;
  try {
    const canonico = new URL(`http://[${ip}]/`).hostname.slice(1, -1);
    const [esquerda = "", direita] = canonico.split("::");
    const inicio = esquerda === "" ? [] : esquerda.split(":");
    const fim = direita ? direita.split(":") : [];
    const partes = direita === undefined ? inicio : [...inicio, ...Array(8 - inicio.length - fim.length).fill("0"), ...fim];
    return `${partes.slice(0, 4).map((p) => p.padStart(4, "0")).join(":")}::/64`;
  } catch {
    return "anonimo";
  }
}

async function limitar(request: Request, env: Env): Promise<void> {
  if (!env.LIMITE) return;
  // A chave é um resumo do IP, que não é guardado nem registrado.
  const ip = clienteLimite(request.headers.get("CF-Connecting-IP") ?? "anonimo");
  const { success } = await env.LIMITE.limit({ key: (await sha256Hex(`radar|${ip}`)).slice(0, 32) });
  if (!success) {
    throw new ErroHttp(429, "limite", "Muitas consultas em pouco tempo; tente de novo em um minuto.", { "Retry-After": "60" });
  }
}

async function saude(env: Env): Promise<Response> {
  try {
    const [estado, verificacao] = await env.DB.batch([
      env.DB.prepare("SELECT versao, data FROM estado_indice WHERE id = 1"),
      env.DB.prepare("SELECT data, amostra, ok FROM verificacoes ORDER BY data DESC LIMIT 1"),
    ]);
    return json(
      { ok: true, d1: "ok", indice: estado!.results[0] ?? null, verificacao: verificacao!.results[0] ?? null },
      200,
      { "Cache-Control": "no-store" },
    );
  } catch {
    return json({ ok: false, erro: "Base de dados indisponível.", codigo: "indisponivel" }, 503, { "Cache-Control": "no-store" });
  }
}

async function rotear(request: Request, url: URL, env: Env, ctx: ContextoExecucao, contexto: Contexto): Promise<Response> {
  const partes = url.pathname.split("/");
  if (partes[1] !== "api" || partes.length < 3) throw new ErroHttp(404, "rota_inexistente", "Rota inexistente.");
  const origem = request.headers.get("Origin");
  if (origem !== null && contexto.cors === null) throw new ErroHttp(403, "origem_recusada", "Origem não permitida.");
  if (request.method === "OPTIONS") return preflight();
  if (request.method !== "GET" && request.method !== "HEAD") {
    throw new ErroHttp(405, "metodo_invalido", "Método não permitido.", { Allow: METODOS });
  }
  await limitar(request, env);

  const [, , rota, argumento, ...resto] = partes;
  const semArgumento = argumento === undefined;
  const comArgumento = argumento !== undefined && argumento !== "" && resto.length === 0;
  if (rota === "saude" && semArgumento) return saude(env);
  // HEAD tem os cabeçalhos da rota, sem FTS, embedding, Vectorize nem hidratação.
  if (rota === "busca" && semArgumento && request.method === "HEAD") {
    return new Response(null, { status: 200, headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" } });
  }

  const { estado, remocoes } = await lerEstado(env);
  contexto.indice = estado?.versao ?? "vazio";
  const indice = await chaveIndice(estado, remocoes);
  if (rota === "busca" && semArgumento) return rotaBusca(url, env, ctx, indice);
  if (rota === "documento" && comArgumento) return rotaDocumento(argumento, url, env, ctx, indice);
  if (rota === "original" && comArgumento) return rotaOriginal(argumento, url, request.method, env, ctx, indice);
  if (rota === "versao" && semArgumento) {
    const meta = env.CF_VERSION_METADATA;
    return json({
      ambiente: env.AMBIENTE ?? null,
      codigo: { commit: env.COMMIT ?? null, versao: meta?.id ?? null, tag: meta?.tag || null, publicado_em: meta?.timestamp ?? null },
      indice: estado,
    }, 200, { "Cache-Control": "no-store" });
  }
  throw new ErroHttp(404, "rota_inexistente", "Rota inexistente.");
}

/** Cabeçalhos comuns: CORS, Vary, versão, segurança; HEAD sem corpo. */
function finalizar(r: Response, request: Request, env: Env, contexto: Contexto): Response {
  const h = new Headers(r.headers);
  h.set("Vary", "Origin");
  if (contexto.cors !== null) {
    h.set("Access-Control-Allow-Origin", contexto.cors);
    h.set("Access-Control-Expose-Headers", "X-Radar-Commit, X-Radar-Indice, X-Radar-Cache, Retry-After");
  }
  h.set("X-Radar-Commit", valorCabecalho(env.COMMIT, "desconhecido"));
  h.set("X-Radar-Indice", valorCabecalho(contexto.indice, "desconhecido"));
  if (!h.has("X-Radar-Cache")) h.set("X-Radar-Cache", "MISS");
  h.set("X-Content-Type-Options", "nosniff");
  h.set("Referrer-Policy", "no-referrer");
  if (!h.has("Content-Security-Policy")) h.set("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'");
  const semCorpo = request.method === "HEAD" || r.status === 204 || r.status === 304;
  return new Response(semCorpo ? null : r.body, { status: r.status, headers: h });
}

export async function tratar(request: Request, env: Env, ctx: ContextoExecucao): Promise<Response> {
  const origem = request.headers.get("Origin");
  const contexto: Contexto = {
    cors: origem !== null && origemPermitida(origem, env.ORIGENS_CORS) ? origem : null,
    indice: "desconhecido",
  };
  let resposta: Response;
  try {
    resposta = await rotear(request, new URL(request.url), env, ctx, contexto);
  } catch (e) {
    // Sem pilha nem mensagem original na resposta, e nada registrado.
    resposta = respostaErro(e instanceof ErroHttp ? e : erroInterno());
  }
  return finalizar(resposta, request, env, contexto);
}

export default {
  scheduled(evento: { scheduledTime: number }, env: Env, ctx: ContextoExecucao): void {
    ctx.waitUntil(verificar(env, new Date(evento.scheduledTime)));
  },
  fetch(request: Request, env: Env, ctx: ContextoExecucao): Promise<Response> {
    return tratar(request, env, ctx);
  },
};
