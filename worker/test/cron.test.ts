// Offline: raw simulado; D1/R2 no runtime Workers, inclusive crypto.DigestStream real.
import { createExecutionContext, env, waitOnExecutionContext } from "cloudflare:test";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { D1Database, Env, R2ObjetoCorpo } from "../src/ambiente";
import { MAX_BYTES_EXECUCAO, MAX_ORIGINAL, amostraDeterministica, candidatosDoDia, hashOriginal, verificar } from "../src/cron";
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
  await env.DB.prepare('UPDATE estado_indice SET "commit" = NULL').run();
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
    expect(escritas).toHaveLength(2);
    expect(escritas[0]).toContain("INTO verificacoes");
    expect(escritas[1]).toContain("UPDATE verificacoes");
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

  it("persiste iniciado antes de qualquer leitura e só conclui por UPDATE", async () => {
    await incluir(1);
    const anterior = fetch;
    let conferiu = false;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (!conferiu) {
        expect(await env.DB.prepare("SELECT * FROM verificacoes").first()).toEqual({
          data: DATA.toISOString(), amostra: 0, ok: 0,
          falhas_json: JSON.stringify([{ etapa: "cron", codigo: "iniciado" }]),
        });
        conferiu = true;
      }
      return anterior(input);
    }));
    const resultado = await verificar(criarEnv({ DB: bancoComFalha((sql) => sql.startsWith("UPDATE verificacoes")) }), DATA);
    expect(conferiu).toBe(true);
    expect(resultado.falhas).toContainEqual({ etapa: "verificacoes", codigo: "gravacao" });
    expect(await env.DB.prepare("SELECT falhas_json FROM verificacoes").first()).toEqual({
      falhas_json: JSON.stringify([{ etapa: "cron", codigo: "iniciado" }]),
    });
  });

  it("fixa manifesto em main e JSONL no commit distinto de dados-textos, sem consultar as branches", async () => {
    await incluir(1);
    const commit = "a".repeat(40);
    const commitDados = "b".repeat(40);
    await env.DB.prepare('UPDATE estado_indice SET "commit" = ?, commit_dados_textos = ?').bind(commit, commitDados).run();
    respostas.set(`${BASE}/${commit}/data/textos/manifesto-2021.json`, JSON.stringify(manifestos.get(2021)));
    respostas.set(`${BASE}/${commitDados}/trechos/pl/2021.jsonl`, trechos.get("trechos/pl/2021.jsonl")!.map((t) => JSON.stringify(t)).join("\n"));
    expect(await verificar(criarEnv(), DATA)).toMatchObject({ amostra: 1, ok: 1, falhas: [] });
    expect(pedidos).toHaveLength(7);
    expect(pedidos.filter((url) => url.endsWith(".json")).every((url) => url.startsWith(`${BASE}/${commit}/`))).toBe(true);
    expect(pedidos.filter((url) => url.endsWith(".jsonl"))).toEqual([`${BASE}/${commitDados}/trechos/pl/2021.jsonl`]);
  });

  it("mantém o commit de main quando a referência de dados-textos ainda é NULL", async () => {
    await incluir(1);
    const commit = "a".repeat(40);
    await env.DB.prepare('UPDATE estado_indice SET "commit" = ?').bind(commit).run();
    respostas.set(`${BASE}/${commit}/data/textos/manifesto-2021.json`, JSON.stringify(manifestos.get(2021)));
    expect(await verificar(criarEnv(), DATA)).toMatchObject({ ok: 1, falhas: [] });
    expect(pedidos).toContain(`${BASE}/${commit}/data/textos/manifesto-2021.json`);
    expect(pedidos).toContain(`${BASE}/dados-textos/trechos/pl/2021.jsonl`);
  });

  it.each(["nulo", "ausente"])("usa branches quando o commit está %s", async (caso) => {
    if (caso === "ausente") await env.DB.prepare("DELETE FROM estado_indice").run();
    await incluir(1);
    expect(await verificar(criarEnv(), DATA)).toMatchObject({ ok: 1, falhas: [] });
    expect(pedidos).toContain(`${BASE}/main/data/textos/manifesto-2021.json`);
    expect(pedidos).toContain(`${BASE}/dados-textos/trechos/pl/2021.jsonl`);
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

  it("rotaciona até três grupos determinísticos e cobre todos em dias consecutivos", async () => {
    const lista = [];
    let n = 0;
    for (const ano of [2021, 2022]) {
      for (const tipo of ["pl", "ata", "pdl", "resolucao", "requerimento"]) {
        await incluir(++n, ano, tipo);
        lista.push({ chave: `siscam:${n}`, ano, tipo });
      }
    }
    const cobertos = new Set<string>();
    for (let dia = 28; dia <= 31; dia++) {
      const data = `2026-10-${dia}`;
      const candidatos = candidatosDoDia(lista, data);
      expect(candidatosDoDia([...lista].reverse(), data)).toEqual(candidatos);
      expect(new Set(candidatos.map((a) => `${a.tipo}/${a.ano}`)).size).toBe(3);
      for (const a of candidatos) cobertos.add(`${a.tipo}/${a.ano}`);
      pedidos.length = 0;
      const resultado = await verificar(criarEnv(), new Date(`${data}T07:17:00Z`));
      expect(resultado).toMatchObject({ amostra: 3, ok: 3, falhas: [] });
      expect(pedidos.filter((url) => url.endsWith(".jsonl"))).toHaveLength(3);
    }
    expect(cobertos.size).toBe(10);
    expect(candidatosDoDia([], "2026-10-28")).toEqual([]);
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

  it("lê JSONL em blocos, ignora hashes alheios e aceita UTF-8 dividido e última linha sem LF", async () => {
    await incluir(1);
    const texto = JSON.stringify({ arquivo: "siscam:999", texto: "ação", id: "inválido" }) + "\r\n" +
      JSON.stringify(trechos.get("trechos/pl/2021.jsonl")![0]);
    const bytes = new TextEncoder().encode(texto);
    const anterior = fetch;
    const text = vi.fn(() => { throw new Error("não deve bufferizar JSONL"); });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (!String(input).endsWith(".jsonl")) return anterior(input);
      let posicao = 0;
      return Object.assign(new Response(new ReadableStream<Uint8Array>({
        pull(controle) {
          if (posicao >= bytes.length) controle.close();
          else { controle.enqueue(bytes.slice(posicao, posicao + 1)); posicao++; }
        },
      })), { text });
    }));
    expect(await verificar(criarEnv(), DATA)).toMatchObject({ amostra: 1, ok: 1, falhas: [] });
    expect(text).not.toHaveBeenCalled();
  });

  it("limita bytes totais, cancela o primeiro original sem saldo e adia os restantes", async () => {
    for (let n = 1; n <= 6; n++) await incluir(n);
    const bytes = new TextEncoder().encode(ORIGINAL);
    const limite = bytes.length * 3;
    expect(MAX_BYTES_EXECUCAO).toBe(300_000_000);
    let gets = 0;
    const cancel = vi.fn();
    const ARQUIVOS: Env["ARQUIVOS"] = {
      head: async () => null,
      get: async (key) => {
        gets++;
        return { key, size: bytes.length, body: new ReadableStream<Uint8Array>({
          start(controle) { controle.enqueue(bytes); },
          pull(controle) { controle.close(); }, cancel,
        }) };
      },
    };
    // Deixa saldo positivo menor que um original para exercitar o cancelamento no GET.
    const resultado = await verificar(criarEnv({ ARQUIVOS }), DATA, { limiteBytesOriginais: limite + 1 });
    expect(resultado.amostra).toBe(6);
    expect(resultado.ok).toBe(3);
    expect(gets).toBe(4);
    expect(resultado.falhas.filter((f) => f.codigo === "adiado")).toHaveLength(3);
    expect(cancel).toHaveBeenCalledOnce();
  });

  it("conta bytes reais no teto mesmo se o tamanho R2 estiver incorreto", async () => {
    await incluir(1);
    await incluir(2);
    const cancel = vi.fn();
    let gets = 0;
    const ARQUIVOS: Env["ARQUIVOS"] = {
      head: async () => null,
      get: async (key) => {
        gets++;
        return { key, size: 1, body: new ReadableStream<Uint8Array>({
          pull(controle) { controle.enqueue(new Uint8Array(10)); }, cancel,
        }) };
      },
    };
    const resultado = await verificar(criarEnv({ ARQUIVOS }), DATA, { limiteBytesOriginais: 15 });
    expect(resultado).toMatchObject({ amostra: 2, ok: 0 });
    expect(resultado.falhas.map((f) => f.codigo)).toEqual(["adiado", "adiado"]);
    expect(gets).toBe(1);
    expect(cancel).toHaveBeenCalledOnce();
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
    let avisar = (): void => {};
    const iniciouLeitura = new Promise<void>((resolve) => { avisar = resolve; });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (!String(input).endsWith("manifesto-2021.json")) return new Response(null, { status: 404 });
      return new Promise<Response>((_, rejeitar) => {
        init?.signal?.addEventListener("abort", () => { abortou = true; rejeitar(new Error("segredo")); });
        avisar();
      });
    }));
    vi.useFakeTimers();
    const promessa = verificar(criarEnv(), DATA);
    await iniciouLeitura;
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
        if (sql.startsWith("INSERT") || sql.startsWith("UPDATE")) { gravacoes++; return real.prepare(sql); }
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
