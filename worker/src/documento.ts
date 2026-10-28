// GET /api/documento/:id: metadados, autoria, arquivos (sem os removidos) e substitutivos.
import type { ContextoExecucao, Env } from "./ambiente";
import { urlOriginal, urlSiscam } from "./busca";
import { ErroHttp, guardarCache, json, lerCache } from "./http";

export const RE_DOCUMENTO = /^(doc|sessao):[1-9][0-9]*$/;
export const CACHE_DOCUMENTO = 60;

interface LinhaDocumento {
  id: string;
  tipo: string;
  numero: string | null;
  ano: number | null;
  data: string | null;
  ementa: string | null;
  url: string | null;
  legislatura: string | null;
  pl: string | null;
}

interface LinhaArquivo {
  id: string;
  sha256: string | null;
  formato: string | null;
  status: string;
  ocr: number;
  confianca: number | null;
  r2_chave: string | null;
}

/** Ordem das chaves de arquivo (contrato, seção 2.1): siscam por id numérico, depois sessao pelo GUID. */
export function ordemArquivo(a: string, b: string): number {
  const [oa, ia = ""] = a.split(":", 2);
  const [ob, ib = ""] = b.split(":", 2);
  if (oa !== ob) return oa === "siscam" ? -1 : ob === "siscam" ? 1 : oa! < ob! ? -1 : 1;
  if (oa === "siscam" && ia !== ib) return Number(ia) - Number(ib);
  return ia < ib ? -1 : ia > ib ? 1 : 0;
}

export async function rotaDocumento(segmento: string, url: URL, env: Env, ctx: ContextoExecucao, indice: string): Promise<Response> {
  let id: string;
  try {
    id = decodeURIComponent(segmento);
  } catch {
    throw new ErroHttp(400, "documento_invalido", "Identificador de documento inválido.");
  }
  if (!RE_DOCUMENTO.test(id)) throw new ErroHttp(400, "documento_invalido", "Identificador de documento inválido.");
  const chave = `${url.origin}/api/documento/${encodeURIComponent(id)}?_indice=${encodeURIComponent(indice)}`;
  const guardada = await lerCache(chave);
  if (guardada) return guardada;

  const [rd, ra, rarq, rs] = await env.DB.batch([
    env.DB.prepare("SELECT id, tipo, numero, ano, data, ementa, url, legislatura, pl FROM documentos WHERE id = ?").bind(id),
    env.DB.prepare(
      "SELECT au.slug AS slug, au.papel AS papel, p.nome AS nome, p.partido_atual AS partido FROM autoria AS au " +
        "LEFT JOIN pessoas AS p ON p.slug = au.slug WHERE au.documento = ? " +
        "ORDER BY CASE au.papel WHEN 'autor' THEN 0 ELSE 1 END, au.slug",
    ).bind(id),
    // Arquivos do documento e, num PL, também os citados só pelos seus substitutivos.
    env.DB.prepare(
      "SELECT DISTINCT a.id AS id, a.sha256 AS sha256, a.formato AS formato, a.status AS status, a.ocr AS ocr, " +
        "a.confianca AS confianca, a.r2_chave AS r2_chave FROM arquivo_documento AS ad JOIN arquivos AS a ON a.id = ad.arquivo " +
        "WHERE (ad.documento = ? OR ad.documento IN (SELECT s.id FROM documentos AS s WHERE s.pl = ?)) " +
        "AND NOT EXISTS (SELECT 1 FROM remocoes AS rm WHERE rm.chave = a.id OR rm.sha256 = a.sha256)",
    ).bind(id, id),
    env.DB.prepare("SELECT id, numero FROM documentos WHERE pl = ?").bind(id),
  ]);
  const doc = (rd!.results as unknown as LinhaDocumento[])[0];
  if (!doc) throw new ErroHttp(404, "documento_inexistente", "Documento não encontrado.");

  const arquivos = (rarq!.results as unknown as LinhaArquivo[])
    .sort((a, b) => ordemArquivo(a.id, b.id))
    .map((a) => ({
      arquivo: a.id,
      formato: a.formato,
      status: a.status,
      ocr: a.ocr === 1,
      confianca: a.confianca,
      sha256: a.sha256,
      url_original: urlOriginal(a.sha256, a.r2_chave),
    }));
  const substitutivos = (rs!.results as unknown as { id: string; numero: string | null }[])
    .sort((a, b) => Number(a.id.slice(4)) - Number(b.id.slice(4)))
    .map((s) => ({ documento: s.id, numero: s.numero }));
  const corpo = {
    documento: {
      id: doc.id,
      tipo: doc.tipo,
      numero: doc.numero,
      ano: doc.ano,
      data: doc.data,
      ementa: doc.ementa,
      legislatura: doc.legislatura,
      pl: doc.pl,
      url_siscam: urlSiscam(doc.url),
    },
    autoria: (ra!.results as unknown as { slug: string; papel: string; nome: string | null; partido: string | null }[])
      .map((a) => ({ slug: a.slug, nome: a.nome, partido: a.partido, papel: a.papel })),
    arquivos,
    substitutivos,
  };
  const resposta = json(corpo, 200, { "Cache-Control": `public, max-age=${CACHE_DOCUMENTO}` });
  guardarCache(ctx, chave, resposta, CACHE_DOCUMENTO);
  return resposta;
}
