import { env } from "cloudflare:test";
import { beforeEach, describe, expect, it } from "vitest";
import type { D1Database } from "../src/ambiente";
import { AVISO_SEMANTICA, TOPK_AUTOR, compararIds, fundir, lerParametros } from "../src/busca";
import { AiFalsa, MetricasFalsas, VetoresFalsos, buscarJson, carregar, criarEnv, idTrecho, sha, trechoDe } from "./dados";

beforeEach(async () => {
  await carregar();
});

const docs = (corpo: Record<string, any>): string[] => corpo.resultados.map((r: { documento: string }) => r.documento);

describe("busca por palavras (FTS5)", () => {
  it("acha com e sem acento e destaca o texto original", async () => {
    for (const q of ["licenca", "LICENÇA", "Licença ambiental"]) {
      const { r, corpo } = await buscarJson({ q, modo: "palavras" });
      expect(r.status).toBe(200);
      expect(docs(corpo)).toEqual(["doc:102"]);
    }
    const { corpo } = await buscarJson({ q: "praca", modo: "palavras" });
    const res = corpo.resultados[0];
    expect(res).toMatchObject({
      documento: "doc:103", tipo: "pl", numero: "3/2023", ano: 2023, ementa: "Cria a Praça da Juventude.",
      arquivo: "siscam:1003", status: "ocr_baixa_confianca", ocr: true, confianca: 54.5,
      url_siscam: "https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento=103",
      url_original: `/api/original/${sha(3)}`, sha256: sha(3), origem: "palavras",
    });
    expect(res.trecho).toContain("<mark>Praça</mark>");
    expect(res.trecho).toContain("&lt;script&gt;");
    expect(res.trecho).not.toContain("<script>");
    expect(res.pontuacao).toBeGreaterThan(0);
    expect(Object.keys(res).sort()).toEqual(["ano", "arquivo", "confianca", "documento", "ementa", "numero", "ocr",
      "origem", "pontuacao", "sha256", "status", "tipo", "trecho", "url_original", "url_siscam"]);
  });

  it("operadores FTS5 do usuário viram texto", async () => {
    const casos: [string, number][] = [
      ["calendario", 13],
      ['"calendario"', 13],
      ["calendario*", 13],
      ["(calendario", 13],
      ["calendario)", 13],
      ["calend*", 0], // sem prefixo
      ["leitura OR xadrez", 0], // OR exigiria a palavra "or"
      ["semana NOT leitura", 0],
      ["NEAR(semana leitura)", 0],
      ["texto_norm:calendario", 0],
      ["semana ^leitura", 1],
      ['semana "leitura', 1],
    ];
    for (const [q, total] of casos) {
      const { r, corpo } = await buscarJson({ q, modo: "palavras" });
      expect(r.status, q).toBe(200);
      expect(corpo.total, q).toBe(total);
    }
  });

  it("injeção de SQL não passa da consulta parametrizada", async () => {
    const { r, corpo } = await buscarJson({ q: "calendario'; DROP TABLE documentos; --", modo: "palavras" });
    expect(r.status).toBe(200);
    expect(corpo.total).toBe(0);
    const conta = await env.DB.prepare("SELECT COUNT(*) AS n FROM documentos").first<{ n: number }>();
    expect(conta!.n).toBe(30);
    for (const extra of [{ autor: "x' OR 1=1 --" }, { tipo: "pl' OR '1'='1" }, { ano: "2021 OR 1=1" },
      { legislatura: "2021-2024' --" }]) {
      const { r: r2, corpo: c2 } = await buscarJson({ q: "calendario", ...extra });
      expect(r2.status).toBe(400);
      expect(c2).toEqual({ erro: expect.any(String), codigo: "parametro_invalido" });
    }
  });

  it("consulta vazia, curta, longa e sem termos", async () => {
    const casos: [Record<string, string>, string][] = [
      [{}, "consulta_curta"],
      [{ q: "   " }, "consulta_curta"],
      [{ q: "a" }, "consulta_curta"],
      [{ q: "a".repeat(201) }, "consulta_longa"],
      [{ q: "**" }, "consulta_sem_termos"],
      [{ q: '""' }, "consulta_sem_termos"],
      [{ q: "ab", modo: "outro" }, "parametro_invalido"],
    ];
    for (const [consulta, codigo] of casos) {
      const { r, corpo } = await buscarJson(consulta);
      expect(r.status).toBe(400);
      expect(corpo.codigo).toBe(codigo);
    }
    expect((await buscarJson({ q: `${"á".repeat(199)} b`, modo: "palavras" })).r.status).toBe(400);
    expect((await buscarJson({ q: `${"á".repeat(198)} b`, modo: "palavras" })).r.status).toBe(200);
    const repetido = await buscarJson({ q: "ab" }, criarEnv());
    expect(repetido.r.status).toBe(400);
    expect(repetido.corpo.codigo).toBe("consulta_muito_generica");
    const url = new URL("https://x/api/busca?q=ab&q=cd");
    expect(() => lerParametros(url)).toThrow(/repetido/);
  });

  it("filtros combinados, inclusive autor", async () => {
    const casos: [Record<string, string>, string[]][] = [
      [{ tipo: "requerimento" }, ["doc:301", "doc:302", "doc:303", "doc:304", "doc:305", "doc:306"]],
      [{ ano: "2025", autor: "ana-souza" }, ["doc:302", "doc:304", "doc:306"]],
      [{ tipo: "pl", ano: "2021" }, ["doc:104", "doc:108"]],
      [{ legislatura: "2021-2024" }, ["doc:104", "doc:105", "doc:106", "doc:107", "doc:108", "doc:109", "doc:110"]],
      [{ autor: "davi-rocha", tipo: "pl", legislatura: "2021-2024" },
        ["doc:104", "doc:105", "doc:106", "doc:107", "doc:108", "doc:109", "doc:110"]],
      [{ autor: "carla-dias" }, []],
    ];
    for (const [filtros, esperado] of casos) {
      const { corpo } = await buscarJson({ q: "calendario", modo: "palavras", ...filtros });
      expect([...docs(corpo)].sort(), JSON.stringify(filtros)).toEqual(esperado);
      expect(corpo.filtros.tipo ?? null).toBe(filtros.tipo ?? null);
    }
    // O arquivo citado só pelo substitutivo fica no PL; o coautor do substitutivo o encontra.
    const sub = await buscarJson({ q: "transporte intermunicipal", modo: "palavras", autor: "davi-rocha" });
    expect(docs(sub.corpo)).toEqual(["doc:101"]);
    const outro = await buscarJson({ q: "transporte intermunicipal", modo: "palavras", autor: "bruno-lima" });
    expect(docs(outro.corpo)).toEqual([]);
  });

  it("pagina de 10 em 10, um resultado por documento", async () => {
    const p1 = await buscarJson({ q: "calendario", modo: "palavras" });
    const p2 = await buscarJson({ q: "calendario", modo: "palavras", pagina: "2" });
    const p3 = await buscarJson({ q: "calendario", modo: "palavras", pagina: "3" });
    expect(p1.corpo).toMatchObject({ pagina: 1, por_pagina: 10, total: 13, limitado: false });
    expect(p1.corpo.resultados).toHaveLength(10);
    expect(p2.corpo.resultados).toHaveLength(3);
    expect(p3.corpo.resultados).toHaveLength(0);
    const todos = [...docs(p1.corpo), ...docs(p2.corpo)];
    expect(new Set(todos).size).toBe(13);
    const pont = [...p1.corpo.resultados, ...p2.corpo.resultados].map((r: { pontuacao: number }) => r.pontuacao);
    expect(pont).toEqual([...pont].sort((a, b) => b - a));
    // Mesmo pedido, mesma ordem.
    expect(docs((await buscarJson({ q: "calendario", modo: "palavras" }, criarEnv(), { headers: { "X-Nada": "1" } })).corpo))
      .toEqual(docs(p1.corpo));
    for (const pagina of ["0", "51", "abc", "1.5"]) {
      const { r, corpo } = await buscarJson({ q: "calendario", pagina });
      expect(r.status).toBe(400);
      expect(corpo.codigo).toBe("parametro_invalido");
    }
  });

  it("não devolve trechos de arquivos removidos (pela chave ou pelo SHA-256)", async () => {
    await env.DB.prepare("INSERT INTO remocoes (chave, sha256, motivo, data) VALUES (?, ?, ?, ?)")
      .bind("siscam:1002", sha(250), "Pedido do titular.", "2026-10-01").run();
    await env.DB.prepare("INSERT INTO remocoes (chave, sha256, motivo, data) VALUES (?, ?, ?, ?)")
      .bind("siscam:9999", sha(3), "Pedido do titular.", "2026-10-01").run();
    expect((await buscarJson({ q: "licenca", modo: "palavras" })).corpo.total).toBe(0);
    expect((await buscarJson({ q: "praca", modo: "palavras" })).corpo.total).toBe(0);
    const e = criarEnv({ VETORES: new VetoresFalsos([trechoDe("siscam:1002").id, trechoDe("siscam:1003").id, trechoDe("siscam:1001").id]) });
    expect(docs((await buscarJson({ q: "licenca", modo: "semantica" }, e)).corpo)).toEqual(["doc:101"]);
  });

  it("guarda na Cache API por 60 s e troca a chave quando o índice muda", async () => {
    const a = await buscarJson({ q: "calendario", modo: "palavras" });
    expect(a.r.headers.get("X-Radar-Cache")).toBe("MISS");
    expect(a.r.headers.get("Cache-Control")).toBe("public, max-age=60");
    const b = await buscarJson({ q: "calendario", modo: "palavras" });
    expect(b.r.headers.get("X-Radar-Cache")).toBe("HIT");
    expect(b.corpo).toEqual(a.corpo);
    await carregar();
    expect((await buscarJson({ q: "calendario", modo: "palavras" })).r.headers.get("X-Radar-Cache")).toBe("MISS");
  });

  it("METRICAS recebe só o modo e a contagem", async () => {
    const metricas = new MetricasFalsas();
    await buscarJson({ q: "calendario", modo: "palavras" }, criarEnv({ METRICAS: metricas }));
    expect(metricas.pontos).toEqual([{ blobs: ["palavras"], doubles: [13] }]);
    const quebradas = { writeDataPoint: () => { throw new Error("x"); } };
    expect((await buscarJson({ q: "regimento", modo: "palavras" }, criarEnv({ METRICAS: quebradas }))).r.status).toBe(200);
  });
});

describe("busca por significado (Workers AI + Vectorize simulados)", () => {
  it("usa bge-m3, topK 50 com metadados indexados e filtros tipo/ano/legislatura", async () => {
    const ai = new AiFalsa();
    const vetores = new VetoresFalsos([`ementa:doc:403`, `ementa:doc:401`, `ementa:doc:501`, trechoDe("siscam:1001").id]);
    const e = criarEnv({ AI: ai, VETORES: vetores });
    const { r, corpo } = await buscarJson({ q: "poda de árvores", modo: "semantica", tipo: "indicacao", ano: "2025",
      legislatura: "2025-2028" }, e);
    expect(r.status).toBe(200);
    expect(ai.chamadas).toEqual([{ modelo: "@cf/baai/bge-m3", entrada: { text: ["poda de arvores"] } }]);
    expect(vetores.chamadas[0]!.opcoes).toEqual({ topK: 50, returnMetadata: "indexed",
      filter: { tipo: { $eq: "indicacao" }, ano: { $eq: 2025 }, legislatura: { $eq: "2025-2028" } } });
    expect(vetores.chamadas[0]!.vetor).toHaveLength(1024);
    expect(docs(corpo)).toEqual(["doc:403", "doc:401"]);
    expect(corpo.resultados[0]).toMatchObject({ tipo: "indicacao", arquivo: null, url_original: null, sha256: null,
      origem: "semantica", trecho: "Indica a <mark>poda</mark> <mark>de</mark> <mark>árvores</mark> na Rua Gama." });
    expect(corpo.limitado).toBe(false);
  });

  it("sem filtros não envia filter; autor é filtrado no D1; vetor sem linha no D1 é descartado", async () => {
    const vetores = new VetoresFalsos([`ementa:doc:401`, "ffffffffffffffff", "ementa:doc:999", "outro", trechoDe("siscam:1301").id]);
    const e = criarEnv({ VETORES: vetores });
    const { corpo } = await buscarJson({ q: "pedidos", modo: "semantica" }, e);
    expect(vetores.chamadas[0]!.opcoes).toEqual({ topK: 50, returnMetadata: "indexed" });
    expect(docs(corpo)).toEqual(["doc:401", "doc:301"]);
    const autor = await buscarJson({ q: "pedidos", modo: "semantica", autor: "davi-rocha" }, criarEnv({ VETORES: vetores }));
    expect(docs(autor.corpo)).toEqual(["doc:301"]);
    expect(vetores.chamadas[1]!.opcoes.topK).toBe(TOPK_AUTOR);
    // Mesma consulta e mesmo índice dariam a resposta guardada na Cache API (as simulações não fazem parte da
    // chave): outra consulta para um Vectorize sem correspondências.
    const nada = await buscarJson({ q: "pedidos vazios", modo: "semantica" }, criarEnv({ VETORES: new VetoresFalsos([]) }));
    expect(nada.r.headers.get("X-Radar-Cache")).toBe("MISS");
    expect(nada.corpo.total).toBe(0);
  });

  it("híbrida funde por RRF e marca a origem", async () => {
    const t301 = trechoDe("siscam:1301").id;
    const e = criarEnv({ VETORES: new VetoresFalsos(["ementa:doc:402", t301]) });
    const { corpo } = await buscarJson({ q: "calendario" }, e);
    expect(corpo.modo).toBe("hibrida");
    expect(corpo.total).toBe(14);
    const r301 = corpo.resultados.find((r: { documento: string }) => r.documento === "doc:301");
    expect(r301.origem).toBe("ambas");
    expect(corpo.resultados[0].documento).toBe("doc:301");
    const ementa = corpo.resultados.find((r: { documento: string }) => r.documento === "doc:402");
    expect(ementa).toMatchObject({ origem: "semantica", pontuacao: Math.round((1 / 61) * 1e6) / 1e6 });
    const pont = corpo.resultados.map((r: { pontuacao: number }) => r.pontuacao);
    expect(pont).toEqual([...pont].sort((a, b) => b - a));
  });

  it("Vectorize indisponível: híbrida cai para palavras com aviso (sem cache); semântica responde 503", async () => {
    let caso = 0;
    for (const extra of [{ VETORES: new VetoresFalsos([], true) }, { AI: new AiFalsa({ data: [[1, 2]] }) },
      { AI: undefined }, { AI: new AiFalsa(null) }]) {
      const q = `calendario${"?".repeat(++caso)}`;
      const e = criarEnv(extra);
      const { r, corpo } = await buscarJson({ q, modo: "hibrida" }, e);
      expect(r.status).toBe(200);
      expect(r.headers.get("Cache-Control")).toBe("no-store");
      expect(corpo).toMatchObject({ modo: "palavras", aviso: AVISO_SEMANTICA, total: 13 });
      const de_novo = await buscarJson({ q, modo: "hibrida" }, e);
      expect(de_novo.r.headers.get("X-Radar-Cache")).toBe("MISS");
      const s = await buscarJson({ q, modo: "semantica" }, e);
      expect(s.r.status).toBe(503);
      expect(s.corpo).toEqual({ erro: expect.any(String), codigo: "semantica_indisponivel" });
    }
  });
});

describe("regressões da revisão de busca", () => {
  it("recusa consultas genéricas antes de FTS ou AI, sem mudar o escape dos demais termos", async () => {
    const ai = new AiFalsa();
    const vetores = new VetoresFalsos([]);
    for (const q of ["de", "da do das dos", "a o e em no na", "para por com que um uma", '"para"', "ab xy 12"]) {
      const { r, corpo } = await buscarJson({ q }, criarEnv({ AI: ai, VETORES: vetores }));
      expect(r.status, q).toBe(400);
      expect(corpo.codigo).toBe("consulta_muito_generica");
      expect(r.headers.get("Cache-Control")).toBe("no-store");
    }
    expect(ai.chamadas).toHaveLength(0);
    expect(vetores.chamadas).toHaveLength(0);
    for (const q of ["licenca\u00adambiental", "licenca\u200dambiental"]) {
      const { r, corpo } = await buscarJson({ q, modo: "palavras" });
      expect(r.status).toBe(200);
      expect(docs(corpo)).toEqual(["doc:102"]);
    }
  });

  it("conta documentos, não trechos, antes do LIMIT", async () => {
    const instrucoes = [];
    for (let i = 1000; i < 1510; i++) {
      const id = idTrecho(i);
      instrucoes.push(env.DB.prepare("INSERT INTO trechos (id, documento, arquivo, posicao, texto, sha256) VALUES (?, ?, ?, ?, ?, ?)")
        .bind(id, "doc:104", "siscam:1004", i, "Calendário", sha(4)));
      instrucoes.push(env.DB.prepare("INSERT INTO trechos_fts (id, texto_norm) VALUES (?, ?)").bind(id, "calendario"));
    }
    await env.DB.batch(instrucoes);
    const { corpo } = await buscarJson({ q: "calendario", modo: "palavras" });
    expect(corpo.total).toBe(13);
    expect(corpo.limitado).toBe(false);
    expect(new Set(docs(corpo)).size).toBe(10);
  });

  it("remoção sem novo estado invalida a busca guardada, inclusive híbrida e por hash somente", async () => {
    for (const modo of ["palavras", "semantica", "hibrida"]) {
      const e = criarEnv({ VETORES: new VetoresFalsos([trechoDe("siscam:1002").id]) });
      const a = await buscarJson({ q: "licenca", modo }, e);
      expect(docs(a.corpo)).toEqual(["doc:102"]);
      expect((await buscarJson({ q: "licenca", modo }, e)).r.headers.get("X-Radar-Cache")).toBe("HIT");
    }
    await env.DB.prepare("INSERT INTO remocoes (chave, sha256, motivo, data) VALUES (?, ?, ?, ?)")
      .bind("siscam:9999", sha(2), "Pedido do titular.", "2026-10-01").run();
    for (const modo of ["palavras", "semantica", "hibrida"]) {
      const e = criarEnv({ VETORES: new VetoresFalsos([trechoDe("siscam:1002").id]) });
      const b = await buscarJson({ q: "licenca", modo }, e);
      expect(b.r.headers.get("X-Radar-Cache")).toBe("MISS");
      expect(docs(b.corpo)).toEqual([]);
      expect(b.corpo.total).toBe(0);
    }
  });

  it("compartilha o ranking entre páginas e o embedding entre modos e filtros", async () => {
    const ai = new AiFalsa();
    const vetores = new VetoresFalsos([trechoDe("siscam:1301").id]);
    const real = env.DB as unknown as D1Database;
    let consultasFts = 0;
    const db: D1Database = {
      prepare(sql) {
        if (sql.includes("MATCH")) consultasFts++;
        return real.prepare(sql);
      },
      batch: (instrucoes) => real.batch(instrucoes),
    };
    const e = criarEnv({ DB: db, AI: ai, VETORES: vetores });
    await buscarJson({ q: "CALENDÁRIO!!!", modo: "hibrida" }, e);
    await buscarJson({ q: "calendario!!!", modo: "hibrida", pagina: "2" }, e);
    expect(ai.chamadas).toHaveLength(1);
    expect(vetores.chamadas).toHaveLength(1);
    expect(consultasFts).toBe(1);
    await buscarJson({ q: "calendario!!!", modo: "semantica", autor: "davi-rocha" }, e);
    expect(ai.chamadas).toHaveLength(1);
    expect(vetores.chamadas).toHaveLength(2);
    expect(vetores.chamadas[1]!.opcoes.topK).toBe(100);
  });

  it("hidrata 100 vetores com autor sem ultrapassar os parâmetros do D1", async () => {
    const real = env.DB as unknown as D1Database;
    const db: D1Database = {
      prepare(sql) {
        expect((sql.match(/\?/g) ?? []).length).toBeLessThanOrEqual(100);
        return real.prepare(sql);
      },
      batch: (instrucoes) => real.batch(instrucoes),
    };
    const vetores = new VetoresFalsos(Array.from({ length: 100 }, (_, i) => idTrecho(10000 + i)));
    const { r, corpo } = await buscarJson({ q: "cem candidatos", modo: "semantica", autor: "davi-rocha" },
      criarEnv({ DB: db, VETORES: vetores }));
    expect(r.status).toBe(200);
    expect(corpo.total).toBe(0);
    expect(vetores.chamadas[0]!.opcoes.topK).toBe(100);
  });
});

describe("fusão RRF", () => {
  const c = (documento: string) => ({ documento, trecho: `t-${documento}`, pontuacao: 1 });

  it("soma 1/(60 + posição) e resolve empates pelo id", () => {
    const f = fundir([c("doc:1"), c("doc:2")], [c("doc:2"), c("doc:3")]);
    expect(f.map((x) => [x.documento, x.origem])).toEqual([["doc:2", "ambas"], ["doc:1", "palavras"], ["doc:3", "semantica"]]);
    expect(f[0]!.pontuacao).toBeCloseTo(1 / 62 + 1 / 61, 12);
    expect(f[0]!.trecho).toBe("t-doc:2");
    const empate = fundir([c("doc:20"), c("sessao:1")], [c("doc:3")]);
    expect(empate.map((x) => x.documento)).toEqual(["doc:3", "doc:20", "sessao:1"]);
    expect(fundir([c("doc:20")], [c("doc:3")])).toEqual(fundir([c("doc:20")], [c("doc:3")]));
    expect(fundir([], [{ documento: "doc:5", trecho: null, pontuacao: 1 }])[0]!.trecho).toBeNull();
  });

  it("compara ids por prefixo e número", () => {
    expect(["doc:10", "sessao:2", "doc:9", "doc:x"].sort(compararIds)).toEqual(["doc:9", "doc:10", "doc:x", "sessao:2"]);
    expect(compararIds("doc:1", "doc:1")).toBe(0);
  });
});
