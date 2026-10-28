// Offline: raw simulado; D1/R2 no runtime Workers, inclusive crypto.DigestStream real.
import { createExecutionContext, env, waitOnExecutionContext } from "cloudflare:test";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { D1Database, Env, R2ObjetoCorpo } from "../src/ambiente";
import { MAX_ORIGINAL, amostraDeterministica, hashOriginal, verificar } from "../src/cron";
import { sha256Hex } from "../src/http";
import worker from "../src/index";
import { chaveR2 } from "../src/original";
import { carregar, criarEnv, idTrecho } from "./dados";

const DATA = new Date("2026-10-28T07:17:00.000Z");
const BASE = "https://raw.githubusercontent.com/marco-jardim/radar-vereadores-niteroi";
const ORIGINAL = "Original sintético para conferir o SHA-256 por streaming.\n";
interface Entrada {
  tipo: string; status: string; sha256_original: string; r2_chave: string | null;
  bytes: number; trechos: number;
}
interface Trecho { id: string; arquivo: string; sha256: string }
let manifestos: Map<number, Record<string, unknown>>;
let trechos: Map<string, Trecho[]>;
let respostas: Map<string, string | number>;
let pedidos: string[];
let hash: string;

beforeEach(async () => {
  await carregar();
  await env.DB.batch(["arquivos", "trechos", "verificacoes"].map((t) => env.DB.prepare(`DELETE FROM ${t}`)));
  hash = await sha256Hex(ORIGINAL);
  await env.ARQUIVOS.put(chaveR2(hash), ORIGINAL);
  manifestos = new Map();
  trechos = new Map();
  respostas = new Map();
  pedidos = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    pedidos.push(url);
    const resposta = respostas.get(url);
    if (typeof resposta === "number") return new Response(null, { status: resposta });
    if (typeof resposta === "string") return new Response(resposta);
    const ano = /\/main\/data\/textos\/manifesto-(\d+)\.json$/.exec(url);
    if (ano && manifestos.has(Number(ano[1]))) return Response.json(manifestos.get(Number(ano[1])));
    const caminho = url.split("/dados-textos/")[1];
    if (caminho && trechos.has(caminho)) return new Response(trechos.get(caminho)!.map((t) => JSON.stringify(t)).join("\n") + "\n");
    return new Response(null, { status: 404 });
  }));
});

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

async function incluir(n: number, ano = 2021, tipo = "pl"): Promise<Entrada> {
  const chave = `siscam:${n}`;
  const entrada: Entrada = { tipo, status: "ok", sha256_original: hash, r2_chave: chaveR2(hash), bytes: ORIGINAL.length, trechos: 1 };
  const manifesto = manifestos.get(ano) ?? {};
  manifesto[chave] = entrada;
  manifestos.set(ano, manifesto);
  const caminho = `trechos/${tipo}/${ano}.jsonl`;
  const lista = trechos.get(caminho) ?? [];
  const trecho = { id: idTrecho(n), arquivo: chave, sha256: await sha256Hex(`Trecho ${n}`) };
  lista.push(trecho);
  trechos.set(caminho, lista);
  await env.DB.batch([
    env.DB.prepare("INSERT INTO arquivos (id, sha256, status, r2_chave) VALUES (?, ?, 'ok', ?)").bind(chave, hash, chaveR2(hash)),
    env.DB.prepare("INSERT INTO trechos (id, documento, arquivo, posicao, texto, sha256) VALUES (?, 'doc:1', ?, 0, ?, ?)")
      .bind(trecho.id, chave, `Trecho ${n}`, trecho.sha256),
  ]);
  return entrada;
}

function bancoComFalha(teste: (sql: string) => boolean): D1Database {
  const real = criarEnv().DB;
  return {
    prepare(sql) { if (teste(sql)) throw new Error("segredo: não persistir"); return real.prepare(sql); },
    batch: (instrucoes) => real.batch(instrucoes),
  };
}

describe("cron de verificação", () => {
  it("verifica todos os anos, hashes intactos e JSONL compartilhado só uma vez; só escreve verificacoes", async () => {
    await incluir(1);
    await incluir(2);
    await incluir(3, 2024, "ata");
    const escritas: string[] = [];
    const real = criarEnv().DB;
    const DB: D1Database = {
      prepare(sql) { if (!sql.startsWith("SELECT")) escritas.push(sql); return real.prepare(sql); },
      batch: (instrucoes) => real.batch(instrucoes),
    };
    const resultado = await verificar(criarEnv({ DB }), DATA);
    expect(resultado).toEqual({ data: DATA.toISOString(), amostra: 3, ok: 3, falhas: [] });
    expect(escritas).toHaveLength(1);
    expect(escritas[0]).toContain("INTO verificacoes");
    expect(await env.DB.prepare("SELECT * FROM verificacoes").first()).toEqual({
      data: DATA.toISOString(), amostra: 3, ok: 3, falhas_json: "[]",
    });
    expect(pedidos.filter((p) => p.includes("manifesto-"))).toHaveLength(6);
    expect(pedidos.filter((p) => p.endsWith("trechos/pl/2021.jsonl"))).toHaveLength(1);
    expect(pedidos.filter((p) => p.includes("/dados-textos/"))).toHaveLength(2);
  });

  it("scheduled usa o horário UTC do evento e waitUntil", async () => {
    await incluir(1);
    const ctx = createExecutionContext();
    expect(worker.scheduled({ scheduledTime: DATA.getTime() }, criarEnv(), ctx)).toBeUndefined();
    await waitOnExecutionContext(ctx);
    expect(await env.DB.prepare("SELECT data, amostra, ok FROM verificacoes").first())
      .toEqual({ data: DATA.toISOString(), amostra: 1, ok: 1 });
  });

  it("registra objeto R2 ausente, sem mensagem interna nem texto", async () => {
    await incluir(1);
    await env.ARQUIVOS.delete(chaveR2(hash));
    const resultado = await verificar(criarEnv(), DATA);
    expect(resultado).toMatchObject({ amostra: 1, ok: 0, falhas: [{ etapa: "r2", codigo: "ausente", chave: "siscam:1" }] });
    const linha = await env.DB.prepare("SELECT falhas_json FROM verificacoes").first<{ falhas_json: string }>();
    expect(JSON.parse(linha!.falhas_json)).toEqual(resultado.falhas);
    expect(linha!.falhas_json).not.toContain("Trecho");
  });

  it("detecta SHA-256 divergente nos bytes, não confia no nome nem nos metadados R2", async () => {
    await incluir(1);
    await env.ARQUIVOS.put(chaveR2(hash), "bytes alterados");
    expect(await verificar(criarEnv(), DATA)).toMatchObject({ ok: 0, falhas: [{ etapa: "r2", codigo: "hash_divergente", chave: "siscam:1" }] });
  });

  it("404 de ano vazio é normal; amostra vazia também é registrada", async () => {
    expect(await verificar(criarEnv(), DATA)).toEqual({ data: DATA.toISOString(), amostra: 0, ok: 0, falhas: [] });
    expect(pedidos).toContain(`${BASE}/main/data/textos/manifesto-2026.json`);
  });

  it("amostra exatamente 50, sem repetição, reproduzível por dia e independente da ordem", async () => {
    const lista = Array.from({ length: 100 }, (_, i) => ({ chave: `siscam:${i + 1}` }));
    const primeira = amostraDeterministica(lista, "2026-10-28");
    expect(primeira).toHaveLength(50);
    expect(new Set(primeira.map((a) => a.chave)).size).toBe(50);
    expect(amostraDeterministica([...lista].reverse(), "2026-10-28")).toEqual(primeira);
    expect(amostraDeterministica(lista, "2026-10-29")).not.toEqual(primeira);
    for (let i = 1; i <= 55; i++) await incluir(i);
    const resultado = await verificar(criarEnv(), DATA);
    expect(resultado).toMatchObject({ amostra: 50, ok: 50, falhas: [] });
    expect(pedidos.length).toBe(7);
  });

  it("exclui removido, duplicata, pendente, R2 NULL no manifesto/D1 e original grande demais", async () => {
    for (let i = 1; i <= 8; i++) {
      const entrada = await incluir(i);
      if (i <= 3) entrada.status = ["removido", "duplicata", "pendente_download"][i - 1]!;
      if (i === 4) entrada.r2_chave = null;
      if (i === 5) entrada.bytes = MAX_ORIGINAL + 1;
      if (i === 6) await env.DB.prepare("UPDATE arquivos SET r2_chave = NULL WHERE id = 'siscam:6'").run();
      if (i === 7) await env.DB.prepare("UPDATE arquivos SET status = 'removido' WHERE id = 'siscam:7'").run();
    }
    expect(await verificar(criarEnv(), DATA)).toMatchObject({ amostra: 1, ok: 1, falhas: [] });
  });

  it.each(["alterado", "ausente", "extra", "contagem"])("detecta trecho %s no D1/JSONL", async (caso) => {
    const entrada = await incluir(1);
    if (caso === "alterado") await env.DB.prepare("UPDATE trechos SET sha256 = ?").bind("a".repeat(64)).run();
    if (caso === "ausente") await env.DB.prepare("DELETE FROM trechos").run();
    if (caso === "extra") trechos.get("trechos/pl/2021.jsonl")!.push({ id: idTrecho(2), arquivo: "siscam:1", sha256: hash });
    if (caso === "contagem") entrada.trechos = 2;
    expect(await verificar(criarEnv(), DATA)).toMatchObject({ ok: 0, falhas: [{ etapa: "trechos", codigo: "hash_divergente", chave: "siscam:1" }] });
  });

  it.each([404, 500, "não é JSON", '{"arquivo":"siscam:1"}\n'])("registra falha de JSONL: %s", async (resposta) => {
    await incluir(1);
    respostas.set(`${BASE}/dados-textos/trechos/pl/2021.jsonl`, resposta);
    expect(await verificar(criarEnv(), DATA)).toMatchObject({ amostra: 1, ok: 0, falhas: [{ etapa: "trechos", codigo: "leitura", chave: "siscam:1" }] });
  });

  it("arquivo sem trechos permite JSONL 404, mas confere que D1 também está vazio", async () => {
    (await incluir(1)).trechos = 0;
    trechos.clear();
    await env.DB.prepare("DELETE FROM trechos").run();
    expect(await verificar(criarEnv(), DATA)).toMatchObject({ amostra: 1, ok: 1, falhas: [] });
  });

  it("faz streaming de múltiplos blocos sem arrayBuffer() no objeto ou corpo R2", async () => {
    await incluir(1);
    const arrayBuffer = vi.fn(() => { throw new Error("não deve bufferizar"); });
    let blocos = 0;
    const ARQUIVOS: Env["ARQUIVOS"] = {
      head: async () => null,
      get: async (key) => {
        const partes = [ORIGINAL.slice(0, 10), ORIGINAL.slice(10, 25), ORIGINAL.slice(25)];
        const body = Object.assign(new ReadableStream<Uint8Array>({
          pull(controle) {
            const parte = partes.shift();
            if (parte === undefined) controle.close();
            else { blocos++; controle.enqueue(new TextEncoder().encode(parte)); }
          },
        }), { arrayBuffer });
        return { key, size: ORIGINAL.length, body, arrayBuffer };
      },
    };
    expect(await verificar(criarEnv({ ARQUIVOS }), DATA)).toMatchObject({ ok: 1, falhas: [] });
    expect(blocos).toBe(3);
    expect(arrayBuffer).not.toHaveBeenCalled();
  });

  it("cancela objeto maior que o teto mesmo com tamanho incorreto no manifesto", async () => {
    await incluir(1);
    const cancel = vi.fn();
    const ARQUIVOS: Env["ARQUIVOS"] = {
      head: async () => null,
      get: async (key) => ({ key, size: MAX_ORIGINAL + 1, body: new ReadableStream({ cancel }) }),
    };
    expect(await verificar(criarEnv({ ARQUIVOS }), DATA)).toMatchObject({ ok: 0, falhas: [{ etapa: "r2", codigo: "leitura", chave: "siscam:1" }] });
    expect(cancel).toHaveBeenCalledOnce();
  });

  it("aborta stream com erro e não lança exceção do cron", async () => {
    await incluir(1);
    const ARQUIVOS: Env["ARQUIVOS"] = {
      head: async () => null,
      get: async (key) => ({ key, size: 1, body: new ReadableStream({ start(c) { c.error(new Error("segredo")); } }) }),
    };
    expect(await verificar(criarEnv({ ARQUIVOS }), DATA)).toMatchObject({ ok: 0, falhas: [{ etapa: "r2", codigo: "leitura", chave: "siscam:1" }] });
  });

  it.each([false, true])("respeita AbortSignal ao consumir R2 (já abortado: %s)", async (antes) => {
    const controle = new AbortController();
    const cancel = vi.fn();
    const original: R2ObjetoCorpo = { key: "teste", size: 1, body: new ReadableStream({ cancel }) };
    if (antes) controle.abort();
    const promessa = hashOriginal(original, controle.signal);
    controle.abort();
    await expect(promessa).rejects.toThrow();
    expect(cancel).toHaveBeenCalledOnce();
    expect(original.body.locked).toBe(false);
  });

  it("prazo injetado de 50 ms cancela R2 parado e libera a leitura para a próxima verificação", async () => {
    await incluir(1);
    const cancel = vi.fn();
    const body = new ReadableStream<Uint8Array>({ cancel });
    const ARQUIVOS: Env["ARQUIVOS"] = {
      head: async () => null,
      get: async (key) => ({ key, size: 1, body }),
    };
    const resultado = await verificar(criarEnv({ ARQUIVOS }), DATA, { prazoOriginalMs: 50 });
    expect(resultado).toMatchObject({ amostra: 1, ok: 0, falhas: [{ etapa: "r2", codigo: "leitura", chave: "siscam:1" }] });
    expect(cancel).toHaveBeenCalledOnce();
    expect(body.locked).toBe(false);
    expect(await verificar(criarEnv(), DATA)).toMatchObject({ amostra: 1, ok: 1, falhas: [] });
  });

  it("registra falhas de manifesto sem mensagem original e continua nos anos seguintes", async () => {
    respostas.set(`${BASE}/main/data/textos/manifesto-2021.json`, 500);
    respostas.set(`${BASE}/main/data/textos/manifesto-2022.json`, "[]");
    await incluir(1, 2026);
    const resultado = await verificar(criarEnv(), DATA);
    expect(resultado).toMatchObject({ amostra: 1, ok: 1 });
    expect(resultado.falhas).toEqual([2021, 2022].map((ano) => ({ etapa: "manifesto", codigo: "leitura", ano })));
  });

  it("valida entradas e chaves sem guardar conteúdo nem chaves inválidas", async () => {
    const entrada = await incluir(1);
    manifestos.set(2022, { "siscam:1": entrada });
    manifestos.set(2023, { "dado pessoal": {}, "siscam:2": null, "siscam:3": { status: "ok" } });
    const resultado = await verificar(criarEnv(), DATA);
    expect(resultado.ok).toBe(0);
    expect(resultado.falhas.map((f) => f.codigo)).toEqual(["chave_repetida", "chave_invalida", "entrada_invalida", "entrada_invalida"]);
    expect(JSON.stringify(resultado)).not.toContain("dado pessoal");
  });

  it("detecta projeção de chave R2 divergente", async () => {
    await incluir(1);
    await env.DB.prepare("UPDATE arquivos SET r2_chave = 'outra'").run();
    expect(await verificar(criarEnv(), DATA)).toMatchObject({ ok: 0, falhas: [{ etapa: "d1", codigo: "r2_chave_divergente", chave: "siscam:1" }] });
  });

  it.each(["SELECT id, r2_chave", "SELECT id, sha256", "INSERT"])("não propaga erro D1 em %s", async (prefixo) => {
    await incluir(1);
    const resultado = await verificar(criarEnv({ DB: bancoComFalha((sql) => sql.startsWith(prefixo)) }), DATA);
    expect(resultado.falhas).toHaveLength(1);
    expect(JSON.stringify(resultado)).not.toContain("segredo");
  });

  it("fonte/branches podem mudar nos dois ambientes, sem permitir outro host", async () => {
    const fonte = `${BASE}-teste`;
    respostas.set(`${fonte}/revisao/data/textos/manifesto-2021.json`, "{}");
    const resultado = await verificar(criarEnv({ CRON_RAW_BASE: fonte, CRON_MANIFESTOS_BRANCH: "revisao", CRON_TEXTOS_BRANCH: "textos-revisao" }), DATA);
    expect(resultado.falhas).toEqual([]);
    expect(pedidos[0]).toBe(`${fonte}/revisao/data/textos/manifesto-2021.json`);
    pedidos.length = 0;
    expect((await verificar(criarEnv({ CRON_RAW_BASE: "https://outro.example" }), DATA)).falhas).toHaveLength(6);
    expect(pedidos).toEqual([]);
  });

  it("timeout aborta raw, registra a falha e permite concluir a gravação", async () => {
    let abortou = false;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (!String(input).endsWith("manifesto-2021.json")) return new Response(null, { status: 404 });
      return new Promise<Response>((_, rejeitar) => {
        init?.signal?.addEventListener("abort", () => { abortou = true; rejeitar(new Error("segredo")); });
      });
    }));
    vi.useFakeTimers();
    const promessa = verificar(criarEnv(), DATA);
    await vi.advanceTimersByTimeAsync(10_001);
    vi.useRealTimers();
    const resultado = await promessa;
    expect(abortou).toBe(true);
    expect(resultado.falhas).toEqual([{ etapa: "manifesto", codigo: "leitura", ano: 2021 }]);
    expect(await env.DB.prepare("SELECT amostra FROM verificacoes").first()).toEqual({ amostra: 0 });
  });

  it("limita subrequisições mesmo com muitos arquivos sem projeção R2 elegível", async () => {
    const entrada = await incluir(1);
    manifestos.set(2021, Object.fromEntries(Array.from({ length: 20_000 }, (_, i) => [`siscam:${i + 1}`, entrada])));
    const real = criarEnv().DB;
    let consultas = 0;
    let gravacoes = 0;
    const DB: D1Database = {
      prepare(sql) {
        if (sql.startsWith("INSERT")) { gravacoes++; return real.prepare(sql); }
        consultas++;
        return {
          bind() { return this; },
          async all() { return { results: [], success: true }; },
          async first() { return null; },
        };
      },
      batch: (instrucoes) => real.batch(instrucoes),
    };
    const resultado = await verificar(criarEnv({ DB }), DATA);
    expect(resultado).toMatchObject({ amostra: 0, falhas: [{ etapa: "cron", codigo: "leitura_ou_orcamento" }] });
    expect(pedidos.length + consultas + gravacoes).toBe(240);
  });
});
