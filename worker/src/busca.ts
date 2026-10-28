// GET /api/busca: palavras (D1 FTS5), significado (Workers AI + Vectorize) e fusão RRF.
import type { ContextoExecucao, D1Instrucao, Env, OpcoesConsultaVetor } from "./ambiente";
import { ErroHttp, guardarCache, json, lerCache, sha256Hex } from "./http";
import { consultaFts, destacar, palavrasAlvo, termos, termosBusca } from "./texto";

export const MODOS = ["palavras", "semantica", "hibrida"] as const;
export const TIPOS = ["pl", "substitutivo", "requerimento", "indicacao", "mocao", "pdl", "resolucao", "ata"] as const;
export type Modo = (typeof MODOS)[number];

export const MIN_CONSULTA = 2;
export const MAX_CONSULTA = 200;
export const POR_PAGINA = 10;
export const MAX_PAGINA = 50;
/** Documentos por palavras; a seleção de trechos anterior também tem teto próprio. */
export const LIMITE_TRECHOS = 500;
export const LIMITE_CANDIDATOS_FTS = 5000;
export const TOPK = 50;
/** Máximo do Vectorize com returnMetadata: indexed (sem returnValues). */
export const TOPK_AUTOR = 100;
export const K_RRF = 60;
export const MODELO = "@cf/baai/bge-m3";
export const DIMENSOES = 1024;
export const CACHE_BUSCA = 60;
export const CACHE_EMBEDDING = 3600;
export const PREFIXO_SISCAM = "https://consultaniteroi.siscam.com.br/";

const RE_TRECHO = /^[0-9a-f]{16}$/;
const RE_EMENTA = /^ementa:(doc:[1-9][0-9]*)$/;
const RE_AUTOR = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const RE_LEGISLATURA = /^[0-9]{4}-[0-9]{4}$/;

export interface Parametros {
  q: string;
  modo: Modo;
  tipo: string | null;
  ano: number | null;
  autor: string | null;
  legislatura: string | null;
  pagina: number;
  termos: string[];
  consulta_truncada: boolean;
}

function invalido(nome: string): ErroHttp {
  return new ErroHttp(400, "parametro_invalido", `Parâmetro inválido: ${nome}.`);
}

export function lerParametros(url: URL): Parametros {
  const um = (nome: string): string | null => {
    const valores = url.searchParams.getAll(nome);
    if (valores.length > 1) throw new ErroHttp(400, "parametro_repetido", `Parâmetro repetido: ${nome}.`);
    const v = (valores[0] ?? "").trim();
    return v === "" ? null : v;
  };
  const q = um("q") ?? "";
  const tamanho = [...q].length;
  if (tamanho < MIN_CONSULTA) throw new ErroHttp(400, "consulta_curta", `A consulta precisa de ao menos ${MIN_CONSULTA} caracteres.`);
  if (tamanho > MAX_CONSULTA) throw new ErroHttp(400, "consulta_longa", `A consulta pode ter até ${MAX_CONSULTA} caracteres.`);
  const lista = termos(q);
  if (lista.length === 0) throw new ErroHttp(400, "consulta_sem_termos", "A consulta precisa de ao menos uma letra ou um dígito.");

  const modo = um("modo") ?? "hibrida";
  if (!(MODOS as readonly string[]).includes(modo)) throw invalido("modo");
  const tipo = um("tipo");
  if (tipo !== null && !(TIPOS as readonly string[]).includes(tipo)) throw invalido("tipo");
  const anoTexto = um("ano");
  let ano: number | null = null;
  if (anoTexto !== null) {
    if (!/^[0-9]{4}$/.test(anoTexto) || Number(anoTexto) < 1900 || Number(anoTexto) > 2100) throw invalido("ano");
    ano = Number(anoTexto);
  }
  const autor = um("autor");
  if (autor !== null && (autor.length > 100 || !RE_AUTOR.test(autor))) throw invalido("autor");
  const legislatura = um("legislatura");
  if (legislatura !== null && !RE_LEGISLATURA.test(legislatura)) throw invalido("legislatura");
  const paginaTexto = um("pagina") ?? "1";
  if (!/^[0-9]{1,3}$/.test(paginaTexto) || Number(paginaTexto) < 1 || Number(paginaTexto) > MAX_PAGINA) throw invalido("pagina");
  const normalizada = termosBusca(lista);
  if (normalizada.termos.every((t) => [...t].length < 3)) {
    throw new ErroHttp(400, "consulta_muito_generica", "Use ao menos um termo mais específico na consulta.");
  }
  return { q, modo: modo as Modo, tipo, ano, autor, legislatura, pagina: Number(paginaTexto),
    termos: normalizada.termos, consulta_truncada: normalizada.truncada };
}

/** URL canônica da Cache API: parâmetros conhecidos, versão da consulta e versão do índice. */
export function chaveBusca(origem: string, p: Parametros, indice: string, lista = false): string {
  const s = new URLSearchParams();
  s.set("_consulta", "2");
  s.set("q", p.termos.join(" "));
  s.set("modo", p.modo);
  if (p.tipo !== null) s.set("tipo", p.tipo);
  if (p.ano !== null) s.set("ano", String(p.ano));
  if (p.autor !== null) s.set("autor", p.autor);
  if (p.legislatura !== null) s.set("legislatura", p.legislatura);
  if (!lista) s.set("pagina", String(p.pagina));
  s.set("_indice", indice);
  return `${origem}/api/${lista ? "_lista" : "busca"}?${s.toString()}`;
}

// ---- filtros (SQL só com parâmetros; as expressões vêm do código, nunca da consulta)

const SEM_REMOCAO = "NOT EXISTS (SELECT 1 FROM remocoes AS rm WHERE rm.chave = t.arquivo OR rm.sha256 = a.sha256)";

function filtrar(p: Parametros, documento: string, arquivo: string | null, onde: string[], valores: unknown[]): void {
  if (p.tipo !== null) {
    if (arquivo === null) onde.push("d.tipo = ?");
    else {
      // Mantém o tipo principal (PL inclusive) e encontra também os documentos que citam o arquivo.
      onde.push(`(d.tipo = ? OR EXISTS (SELECT 1 FROM arquivo_documento AS ad JOIN documentos AS d2 ON d2.id = ad.documento WHERE ad.arquivo = ${arquivo} AND d2.tipo = ?))`);
      valores.push(p.tipo);
    }
    valores.push(p.tipo);
  }
  if (p.ano !== null) {
    onde.push("d.ano = ?");
    valores.push(p.ano);
  }
  if (p.legislatura !== null) {
    onde.push("d.legislatura = ?");
    valores.push(p.legislatura);
  }
  if (p.autor !== null) {
    // O trecho fica no documento principal; o arquivo pode servir a outros (substitutivo, duplicatas).
    const outros = arquivo === null ? "" :
      ` OR au.documento IN (SELECT ad.documento FROM arquivo_documento AS ad WHERE ad.arquivo = ${arquivo})`;
    onde.push(`EXISTS (SELECT 1 FROM autoria AS au WHERE au.slug = ? AND (au.documento = ${documento}${outros}))`);
    valores.push(p.autor);
  }
}

const marcadores = (n: number): string => Array(n).fill("?").join(", ");
const lotesIds = (ids: string[]): string[][] => {
  const lotes: string[][] = [];
  // D1 aceita até 100 parâmetros por instrução; reservar espaço para os filtros.
  for (let i = 0; i < ids.length; i += 90) lotes.push(ids.slice(i, i + 90));
  return lotes;
};

// ---- candidatos

export interface Candidato {
  documento: string;
  /** Id do trecho; `null` para uma correspondência na ementa. */
  trecho: string | null;
  pontuacao: number;
}

export async function porPalavras(env: Env, p: Parametros): Promise<{ itens: Candidato[]; limitado: boolean }> {
  const onde: string[] = [];
  const consulta = consultaFts(p.termos);
  const valores: unknown[] = [consulta, LIMITE_CANDIDATOS_FTS, consulta, LIMITE_CANDIDATOS_FTS];
  filtrar(p, "t.documento", "t.arquivo", onde, valores);
  onde.push(SEM_REMOCAO);
  const ondeEmentas: string[] = ["1 = 1"];
  // Remoções são de arquivos: a ementa mascarada continua pública, como no site.
  filtrar(p, "d.id", null, ondeEmentas, valores);
  valores.push(LIMITE_TRECHOS);
  const sql =
    "WITH classificados AS MATERIALIZED (" +
    "SELECT id, rank FROM trechos_fts WHERE trechos_fts MATCH ? ORDER BY rank LIMIT ?), " +
    "ementas_classificadas AS MATERIALIZED (" +
    "SELECT documento, rank FROM ementas_fts WHERE ementas_fts MATCH ? ORDER BY rank LIMIT ?), " +
    "filtrados AS MATERIALIZED (SELECT t.id, t.documento, c.rank FROM classificados AS c " +
    "JOIN trechos AS t ON t.id = c.id " +
    "JOIN documentos AS d ON d.id = t.documento LEFT JOIN arquivos AS a ON a.id = t.arquivo " +
    `WHERE ${onde.join(" AND ")} UNION ALL ` +
    "SELECT NULL AS id, d.id AS documento, c.rank FROM ementas_classificadas AS c " +
    `JOIN documentos AS d ON d.id = c.documento WHERE ${ondeEmentas.join(" AND ")}), melhores AS (` +
    "SELECT documento, MIN(rank) AS r FROM filtrados GROUP BY documento) " +
    "SELECT m.documento, m.r, (SELECT f.id FROM filtrados AS f " +
    "WHERE f.documento = m.documento AND f.rank = m.r ORDER BY f.id LIMIT 1) AS trecho, " +
    "(SELECT COUNT(*) FROM classificados) AS candidatos, " +
    "(SELECT COUNT(*) FROM ementas_classificadas) AS candidatos_ementas " +
    "FROM melhores AS m ORDER BY m.r, trecho, m.documento LIMIT ?";
  const { results } = await env.DB.prepare(sql).bind(...valores).all<{
    trecho: string | null; documento: string; r: number; candidatos: number; candidatos_ementas: number;
  }>();
  const itens: Candidato[] = [];
  for (const linha of results) {
    // bm25 é negativo (mais negativo, mais relevante): a pontuação publicada é o oposto.
    itens.push({ documento: linha.documento, trecho: linha.trecho, pontuacao: -linha.r });
  }
  return { itens, limitado: results.length >= LIMITE_TRECHOS ||
    (results[0]?.candidatos ?? 0) >= LIMITE_CANDIDATOS_FTS ||
    (results[0]?.candidatos_ementas ?? 0) >= LIMITE_CANDIDATOS_FTS };
}

function vetorDe(saida: unknown): number[] {
  const dados = (saida as { data?: unknown } | null)?.data;
  const vetor = Array.isArray(dados) ? (dados[0] as unknown) : undefined;
  if (!Array.isArray(vetor) || vetor.length !== DIMENSOES || !vetor.every((n) => typeof n === "number" && Number.isFinite(n))) {
    throw new Error("embedding inválido");
  }
  return vetor as number[];
}

function topK(p: Parametros): number {
  // Autor e substitutivo dependem das associações de arquivos no D1, depois do Vectorize.
  return p.autor !== null || p.tipo === "substitutivo" ? TOPK_AUTOR : TOPK;
}

export async function porSignificado(env: Env, p: Parametros, ctx: ContextoExecucao, origem: string): Promise<Candidato[]> {
  if (!env.AI || !env.VETORES) throw new Error("bindings ausentes");
  const consulta = p.termos.join(" ");
  const chave = `${origem}/api/_embedding/${await sha256Hex(`${MODELO}|${consulta}`)}`;
  const guardado = await lerCache(chave);
  const vetor = guardado ? vetorDe(await guardado.json()) : vetorDe(await env.AI.run(MODELO, { text: [consulta] }));
  if (!guardado) guardarCache(ctx, chave, json({ data: [vetor] }), CACHE_EMBEDDING);
  const filtro: Record<string, unknown> = {};
  if (p.tipo !== null && p.tipo !== "substitutivo") filtro.tipo = { $eq: p.tipo };
  if (p.ano !== null) filtro.ano = { $eq: p.ano };
  if (p.legislatura !== null) filtro.legislatura = { $eq: p.legislatura };
  const opcoes: OpcoesConsultaVetor = { topK: topK(p), returnMetadata: "indexed" };
  if (Object.keys(filtro).length > 0) opcoes.filter = filtro;
  const resposta = await env.VETORES.query(vetor, opcoes);
  const correspondencias = (Array.isArray(resposta?.matches) ? resposta.matches : [])
    .filter((m) => typeof m.id === "string" && Number.isFinite(m.score))
    .sort((a, b) => b.score - a.score || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));

  const idsTrechos: string[] = [];
  const idsEmentas: string[] = [];
  for (const m of correspondencias) {
    const ementa = RE_EMENTA.exec(m.id);
    if (RE_TRECHO.test(m.id)) idsTrechos.push(m.id);
    else if (ementa) idsEmentas.push(ementa[1]!);
  }
  // Os metadados completos (e os filtros de autor) vêm do D1; vetor sem linha no D1 é descartado.
  const instrucoes: D1Instrucao[] = [];
  for (const ids of lotesIds(idsTrechos)) {
    const onde = [`t.id IN (${marcadores(ids.length)})`];
    const valores: unknown[] = [...ids];
    filtrar(p, "t.documento", "t.arquivo", onde, valores);
    onde.push(SEM_REMOCAO);
    instrucoes.push(env.DB.prepare(
      "SELECT t.id AS id, t.documento AS documento FROM trechos AS t " +
        "JOIN documentos AS d ON d.id = t.documento LEFT JOIN arquivos AS a ON a.id = t.arquivo " +
        `WHERE ${onde.join(" AND ")}`,
    ).bind(...valores));
  }
  for (const ids of lotesIds(idsEmentas)) {
    const onde = [`d.id IN (${marcadores(ids.length)})`, "d.tipo IN ('indicacao', 'mocao')"];
    const valores: unknown[] = [...ids];
    filtrar(p, "d.id", null, onde, valores);
    instrucoes.push(env.DB.prepare(
      `SELECT 'ementa:' || d.id AS id, d.id AS documento FROM documentos AS d WHERE ${onde.join(" AND ")}`,
    ).bind(...valores));
  }
  if (instrucoes.length === 0) return [];
  const documentoDe = new Map<string, string>();
  for (const r of await env.DB.batch<{ id: string; documento: string }>(instrucoes)) {
    for (const linha of r.results) documentoDe.set(linha.id, linha.documento);
  }
  const vistos = new Set<string>();
  const itens: Candidato[] = [];
  for (const m of correspondencias) {
    const documento = documentoDe.get(m.id);
    if (documento === undefined || vistos.has(documento)) continue;
    vistos.add(documento);
    itens.push({ documento, trecho: RE_TRECHO.test(m.id) ? m.id : null, pontuacao: m.score });
  }
  return itens;
}

// ---- fusão

export type Origem = "palavras" | "semantica" | "ambas";

export interface Fundido extends Candidato {
  origem: Origem;
}

function partesId(id: string): [string, number] {
  const i = id.indexOf(":");
  const n = Number(id.slice(i + 1));
  return [id.slice(0, i), Number.isSafeInteger(n) ? n : Number.MAX_SAFE_INTEGER];
}

/** Ordem dos ids de documento: prefixo (`doc` antes de `sessao`) e número. */
export function compararIds(a: string, b: string): number {
  const [pa, na] = partesId(a);
  const [pb, nb] = partesId(b);
  if (pa !== pb) return pa < pb ? -1 : 1;
  if (na !== nb) return na - nb;
  return a < b ? -1 : a > b ? 1 : 0;
}

/**
 * Reciprocal Rank Fusion: soma de 1/(k + posição), posição a partir de 1 em cada lista (já com um item
 * por documento). Empate resolvido pelo id do documento. O trecho preferido é o das palavras.
 */
export function fundir(palavras: Candidato[], semantica: Candidato[], k = K_RRF): Fundido[] {
  type Soma = { pontuacao: number; trechoP?: string | null; trechoS?: string | null };
  const mapa = new Map<string, Soma>();
  const somar = (lista: Candidato[], lado: "trechoP" | "trechoS"): void => {
    lista.forEach((c, i) => {
      const e: Soma = mapa.get(c.documento) ?? { pontuacao: 0 };
      e.pontuacao += 1 / (k + i + 1);
      e[lado] = c.trecho;
      mapa.set(c.documento, e);
    });
  };
  somar(palavras, "trechoP");
  somar(semantica, "trechoS");
  const saida: Fundido[] = [];
  for (const [documento, e] of mapa) {
    const p = e.trechoP !== undefined;
    const s = e.trechoS !== undefined;
    saida.push({
      documento,
      trecho: (p ? e.trechoP : e.trechoS) ?? null,
      pontuacao: e.pontuacao,
      origem: p && s ? "ambas" : p ? "palavras" : "semantica",
    });
  }
  return saida.sort((a, b) => b.pontuacao - a.pontuacao || compararIds(a.documento, b.documento));
}

// ---- resultados

export interface Resultado {
  documento: string;
  tipo: string;
  numero: string | null;
  ano: number | null;
  ementa: string | null;
  /** HTML escapado; o único elemento é `<mark>`. */
  trecho: string;
  arquivo: string | null;
  status: string | null;
  ocr: boolean | null;
  confianca: number | null;
  url_siscam: string | null;
  url_original: string | null;
  sha256: string | null;
  pontuacao: number;
  origem: Origem;
}

interface LinhaDocumento {
  id: string;
  tipo: string;
  numero: string | null;
  ano: number | null;
  ementa: string | null;
  url: string | null;
}

interface LinhaTrecho {
  id: string;
  texto: string;
  arquivo: string;
  sha256: string | null;
  status: string | null;
  ocr: number | null;
  confianca: number | null;
  r2_chave: string | null;
  removido: number;
}

export function urlSiscam(url: string | null): string | null {
  return url !== null && url.startsWith(PREFIXO_SISCAM) ? url : null;
}

export function urlOriginal(sha256: string | null, r2Chave: string | null): string | null {
  return sha256 !== null && /^[0-9a-f]{64}$/.test(sha256) && r2Chave !== null ? `/api/original/${sha256}` : null;
}

const arredondar = (x: number): number => Math.round(x * 1e6) / 1e6;

async function hidratar(env: Env, itens: Fundido[], alvos: Set<string>): Promise<Resultado[]> {
  if (itens.length === 0) return [];
  const docs = itens.map((i) => i.documento);
  const trechos = itens.flatMap((i) => (i.trecho === null ? [] : [i.trecho]));
  const instrucoes = [
    env.DB.prepare(`SELECT id, tipo, numero, ano, ementa, url FROM documentos WHERE id IN (${marcadores(docs.length)})`).bind(...docs),
  ];
  if (trechos.length > 0) {
    instrucoes.push(env.DB.prepare(
      "SELECT t.id AS id, t.texto AS texto, t.arquivo AS arquivo, a.sha256 AS sha256, a.status AS status, " +
        "a.ocr AS ocr, a.confianca AS confianca, a.r2_chave AS r2_chave, " +
        "EXISTS (SELECT 1 FROM remocoes AS rm WHERE rm.chave = t.arquivo OR rm.sha256 = a.sha256) AS removido " +
        `FROM trechos AS t LEFT JOIN arquivos AS a ON a.id = t.arquivo WHERE t.id IN (${marcadores(trechos.length)})`,
    ).bind(...trechos));
  }
  const [rd, rt] = await env.DB.batch(instrucoes);
  const porDoc = new Map((rd!.results as unknown as LinhaDocumento[]).map((d) => [d.id, d]));
  const porTrecho = new Map(((rt?.results ?? []) as unknown as LinhaTrecho[]).map((t) => [t.id, t]));
  const saida: Resultado[] = [];
  for (const item of itens) {
    const d = porDoc.get(item.documento);
    if (!d) continue;
    const base = {
      documento: d.id,
      tipo: d.tipo,
      numero: d.numero,
      ano: d.ano,
      ementa: d.ementa,
      url_siscam: urlSiscam(d.url),
      pontuacao: arredondar(item.pontuacao),
      origem: item.origem,
    };
    if (item.trecho === null) {
      saida.push({ ...base, trecho: destacar(d.ementa ?? "", alvos), arquivo: null, status: null, ocr: null,
        confianca: null, url_original: null, sha256: null });
      continue;
    }
    const t = porTrecho.get(item.trecho);
    if (!t || t.removido) continue;
    saida.push({
      ...base,
      trecho: destacar(t.texto, alvos),
      arquivo: t.arquivo,
      status: t.status,
      ocr: t.ocr === null ? null : t.ocr === 1,
      confianca: t.confianca,
      url_original: urlOriginal(t.sha256, t.r2_chave),
      sha256: t.sha256,
    });
  }
  return saida;
}

export interface RespostaBusca {
  consulta: string;
  consulta_truncada: boolean;
  modo: Modo;
  filtros: { tipo: string | null; ano: number | null; autor: string | null; legislatura: string | null };
  pagina: number;
  por_pagina: number;
  total: number;
  limitado: boolean;
  resultados: Resultado[];
  aviso?: string;
}

export const AVISO_SEMANTICA = "A busca por significado está indisponível; os resultados vêm só da busca por palavras.";

interface ListaBusca {
  lista: Fundido[];
  modo: Modo;
  limitado: boolean;
  aviso?: string;
}

async function classificar(env: Env, p: Parametros, ctx: ContextoExecucao, origem: string): Promise<ListaBusca> {
  let modo: Modo = p.modo;
  let aviso: string | undefined;
  const [palavras, semantica] = await Promise.all([
    p.modo === "semantica" ? Promise.resolve<{ itens: Candidato[]; limitado: boolean }>({ itens: [], limitado: false }) : porPalavras(env, p),
    p.modo === "palavras" ? Promise.resolve<Candidato[] | null>([]) : porSignificado(env, p, ctx, origem).catch((): null => null),
  ]);
  if (semantica === null) {
    if (p.modo === "semantica") {
      throw new ErroHttp(503, "semantica_indisponivel", "A busca por significado está indisponível no momento.");
    }
    modo = "palavras";
    aviso = AVISO_SEMANTICA;
  }
  let lista: Fundido[];
  if (p.modo === "hibrida" && semantica !== null) {
    lista = fundir(palavras.itens, semantica);
  } else if (p.modo === "semantica") {
    lista = (semantica ?? []).map((c) => ({ ...c, origem: "semantica" as const }));
  } else {
    lista = palavras.itens.map((c) => ({ ...c, origem: "palavras" as const }));
  }
  const limitado = (modo !== "semantica" && palavras.limitado) ||
    (modo !== "palavras" && semantica !== null && semantica.length >= topK(p));
  return { lista, modo, limitado, ...(aviso === undefined ? {} : { aviso }) };
}

export async function buscar(env: Env, p: Parametros, ctx: ContextoExecucao, origem: string, indice: string): Promise<RespostaBusca> {
  // Ranking caro compartilhado entre páginas; só a hidratação depende da página.
  const chave = chaveBusca(origem, p, indice, true);
  const guardada = await lerCache(chave);
  const ranking: ListaBusca = guardada ? await guardada.json() : await classificar(env, p, ctx, origem);
  if (!guardada && ranking.aviso === undefined) guardarCache(ctx, chave, json(ranking), CACHE_BUSCA);
  const { lista, modo, limitado, aviso } = ranking;
  const pagina = lista.slice((p.pagina - 1) * POR_PAGINA, p.pagina * POR_PAGINA);
  const resultados = await hidratar(env, pagina, palavrasAlvo(p.termos));
  const corpo: RespostaBusca = {
    consulta: p.q,
    consulta_truncada: p.consulta_truncada,
    modo,
    filtros: { tipo: p.tipo, ano: p.ano, autor: p.autor, legislatura: p.legislatura },
    pagina: p.pagina,
    por_pagina: POR_PAGINA,
    total: lista.length,
    limitado,
    resultados,
  };
  if (aviso !== undefined) corpo.aviso = aviso;
  return corpo;
}

/** Rota completa: parâmetros, Cache API (60 s) e METRICAS (só modo e contagem). */
export async function rotaBusca(url: URL, env: Env, ctx: ContextoExecucao, indice: string): Promise<Response> {
  const p = lerParametros(url);
  const chave = chaveBusca(url.origin, p, indice);
  const guardada = await lerCache(chave);
  if (guardada) {
    const corpo: RespostaBusca = await guardada.json();
    const headers = new Headers(guardada.headers);
    headers.delete("Content-Length");
    return new Response(JSON.stringify({ ...corpo, consulta: p.q, consulta_truncada: p.consulta_truncada }), { status: 200, headers });
  }
  const corpo = await buscar(env, p, ctx, url.origin, indice);
  try {
    env.METRICAS?.writeDataPoint({ blobs: [corpo.modo], doubles: [corpo.total] });
  } catch {
    // métricas nunca derrubam a busca
  }
  const resposta = json(corpo, 200, { "Cache-Control": corpo.aviso === undefined ? `public, max-age=${CACHE_BUSCA}` : "no-store" });
  // Resposta degradada (sem a busca por significado) não fica guardada.
  if (corpo.aviso === undefined) guardarCache(ctx, chave, resposta, CACHE_BUSCA);
  return resposta;
}
