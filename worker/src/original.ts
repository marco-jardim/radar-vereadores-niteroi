// GET /api/original/:sha256: o original do bucket R2 privado, como download, salvo se removido.
import type { ContextoExecucao, Env } from "./ambiente";
import { urlSiscam } from "./busca";
import { ErroHttp, guardarCache, json, lerCache } from "./http";

export const CACHE_ORIGINAL = 86400;
/** Clonar streams maiores pode acumular o corpo inteiro na memória do isolate. */
export const MAX_CACHE_ORIGINAL = 10 * 1024 * 1024;
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

function removido(env: Env): ErroHttp {
  return new ErroHttp(410, "removido", `Arquivo removido a pedido; ver ${env.URL_SITE.replace(/\/$/, "")}/metodologia.html#privacidade.`);
}

/** Para o cliente, o original nunca fica em cache compartilhado: uma remoção vale na hora. */
function paraCliente(r: Response): Response {
  const h = new Headers(r.headers);
  h.set("Cache-Control", "no-store");
  return new Response(r.body, { status: r.status, headers: h });
}

export async function rotaOriginal(segmento: string, url: URL, metodo: string, env: Env, ctx: ContextoExecucao, indice: string): Promise<Response> {
  const sha256 = segmento.toLowerCase();
  if (!RE_SHA256.test(sha256)) throw new ErroHttp(400, "sha256_invalido", "SHA-256 inválido.");

  // 1. Remoções no D1, sempre antes da Cache API (pelo SHA-256 ou pela chave de um arquivo com ele).
  const marca = await env.DB.prepare(
    "SELECT 1 AS removido FROM remocoes WHERE sha256 = ? OR chave IN (SELECT id FROM arquivos WHERE sha256 = ?) LIMIT 1",
  ).bind(sha256, sha256).first();
  if (marca) throw removido(env);

  // 2. Disponibilidade no D1, inclusive antes de reutilizar um download em cache.
  const arquivo = await env.DB.prepare(
    "SELECT a.id, a.formato, a.r2_chave, (SELECT d.url FROM arquivo_documento AS ad " +
      "JOIN documentos AS d ON d.id = ad.documento WHERE ad.arquivo = a.id AND d.url IS NOT NULL " +
      "ORDER BY d.id LIMIT 1) AS url_siscam FROM arquivos AS a WHERE a.sha256 = ? " +
      "ORDER BY a.r2_chave IS NULL, a.id LIMIT 1",
  ).bind(sha256).first<{ id: string; formato: string | null; r2_chave: string | null; url_siscam: string | null }>();
  if (arquivo && arquivo.r2_chave === null) {
    const urlSiscamArquivo = urlSiscam(arquivo.url_siscam);
    return json({
      erro: `Original indisponível neste serviço; consulte o documento no SISCAM${urlSiscamArquivo ? `: ${urlSiscamArquivo}` : "."}`,
      codigo: "original_indisponivel",
      ...(urlSiscamArquivo ? { url_siscam: urlSiscamArquivo } : {}),
    }, 404, { "Cache-Control": "no-store" });
  }
  if (!arquivo || !arquivo.r2_chave || arquivo.r2_chave !== chaveR2(sha256)) {
    throw new ErroHttp(404, "original_inexistente", "Original não encontrado.");
  }

  // 3. Cache API (só GET; HEAD consulta o R2 para informar o tamanho).
  const chave = `${url.origin}/api/original/${sha256}?_indice=${encodeURIComponent(indice)}`;
  const guardada = metodo === "GET" ? await lerCache(chave) : null;
  if (guardada) return paraCliente(guardada);

  // 4. R2 privado.
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
  h.set("Content-Length", String(objeto.size));
  const resposta = new Response(objeto.body, { status: 200, headers: h });
  if (objeto.size <= MAX_CACHE_ORIGINAL) guardarCache(ctx, chave, resposta, CACHE_ORIGINAL);
  return resposta;
}
