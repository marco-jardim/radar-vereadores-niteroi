// GET /api/original/:sha256: o original do bucket R2 privado, como download, salvo se removido.
import type { ContextoExecucao, Env } from "./ambiente";
import { ErroHttp, guardarCache, lerCache } from "./http";

export const CACHE_ORIGINAL = 86400;
const RE_SHA256 = /^[0-9a-f]{64}$/;

const FORMATOS: Record<string, [string, string]> = {
  pdf: ["application/pdf", "pdf"],
  docx: ["application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"],
  doc: ["application/msword", "doc"],
  rtf: ["application/rtf", "rtf"],
  jpeg: ["image/jpeg", "jpg"],
  png: ["image/png", "png"],
  tiff: ["image/tiff", "tif"],
  zip: ["application/zip", "zip"],
  texto: ["text/plain; charset=utf-8", "txt"],
  // HTML nunca é servido como página: download opaco, além do sandbox.
  html: ["application/octet-stream", "html"],
};

/** Cabeçalhos de segurança de todo original (também na resposta guardada na Cache API). */
export const CABECALHOS_ORIGINAL: Record<string, string> = {
  "X-Robots-Tag": "noindex",
  "X-Content-Type-Options": "nosniff",
  "Content-Security-Policy": "sandbox",
};

export function chaveR2(sha256: string): string {
  return `sha256/${sha256.slice(0, 2)}/${sha256.slice(2, 4)}/${sha256}`;
}

export function nomeArquivo(chave: string, formato: string | null): string {
  const extensao = FORMATOS[formato ?? ""]?.[1] ?? "bin";
  return `${chave.replace(":", "-").replace(/[^a-z0-9-]/g, "")}.${extensao}`;
}

function removido(): ErroHttp {
  return new ErroHttp(410, "removido", "Arquivo removido a pedido; ver metodologia.html#privacidade.");
}

/** Para o cliente, o original nunca fica em cache compartilhado: uma remoção vale na hora. */
function paraCliente(r: Response): Response {
  const h = new Headers(r.headers);
  h.set("Cache-Control", "no-store");
  return new Response(r.body, { status: r.status, headers: h });
}

export async function rotaOriginal(segmento: string, url: URL, metodo: string, env: Env, ctx: ContextoExecucao): Promise<Response> {
  const sha256 = segmento.toLowerCase();
  if (!RE_SHA256.test(sha256)) throw new ErroHttp(400, "sha256_invalido", "SHA-256 inválido.");

  // 1. Remoções no D1, sempre antes da Cache API (pelo SHA-256 ou pela chave de um arquivo com ele).
  const marca = await env.DB.prepare(
    "SELECT 1 AS removido FROM remocoes WHERE sha256 = ? OR chave IN (SELECT id FROM arquivos WHERE sha256 = ?) LIMIT 1",
  ).bind(sha256, sha256).first();
  if (marca) throw removido();

  // 2. Cache API (só GET; HEAD consulta o R2 para informar o tamanho).
  const chave = `${url.origin}/api/original/${sha256}`;
  const guardada = metodo === "GET" ? await lerCache(chave) : null;
  if (guardada) return paraCliente(guardada);

  // 3. D1 (arquivo publicado) e R2 privado.
  const arquivo = await env.DB.prepare(
    "SELECT id, formato, r2_chave FROM arquivos WHERE sha256 = ? AND r2_chave IS NOT NULL ORDER BY id LIMIT 1",
  ).bind(sha256).first<{ id: string; formato: string | null; r2_chave: string }>();
  if (!arquivo || arquivo.r2_chave !== chaveR2(sha256)) {
    throw new ErroHttp(404, "original_inexistente", "Original não encontrado.");
  }
  const h = new Headers(CABECALHOS_ORIGINAL);
  h.set("Content-Type", FORMATOS[arquivo.formato ?? ""]?.[0] ?? "application/octet-stream");
  h.set("Content-Disposition", `attachment; filename="${nomeArquivo(arquivo.id, arquivo.formato)}"`);
  h.set("ETag", `"${sha256}"`);
  h.set("Cache-Control", "no-store");

  // HEAD: só os metadados do objeto (R2Objeto, sem corpo); GET: o corpo (R2ObjetoCorpo).
  if (metodo === "HEAD") {
    const metadados = await env.ARQUIVOS.head(arquivo.r2_chave);
    if (!metadados) throw new ErroHttp(404, "original_inexistente", "Original não encontrado.");
    h.set("Content-Length", String(metadados.size));
    return new Response(null, { status: 200, headers: h });
  }
  const objeto = await env.ARQUIVOS.get(arquivo.r2_chave);
  if (!objeto) throw new ErroHttp(404, "original_inexistente", "Original não encontrado.");
  const resposta = new Response(objeto.body, { status: 200, headers: h });
  guardarCache(ctx, chave, resposta, CACHE_ORIGINAL);
  return resposta;
}
