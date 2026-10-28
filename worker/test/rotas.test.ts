import { env } from "cloudflare:test";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { D1Database, D1Instrucao, Env } from "../src/ambiente";
import { ordemArquivo } from "../src/documento";
import { origemPermitida } from "../src/http";
import worker, { clienteLimite } from "../src/index";
import { MAX_CACHE_ORIGINAL, chaveR2, nomeArquivo } from "../src/original";
import { AiFalsa, LimiteFalso, VetoresFalsos, buscarJson, carregar, criarEnv, pedir, sha, trechoDe } from "./dados";

beforeEach(async () => {
  await carregar();
});

const SITE = "https://marco-jardim.github.io";

describe("CORS", () => {
  it("permite as origens HTTPS configuradas em produção e staging, com Vary: Origin", async () => {
    for (const AMBIENTE of ["production", "staging"]) {
      const r = await pedir("/api/busca?q=calendario&modo=palavras", { headers: { Origin: SITE } }, criarEnv({ AMBIENTE }));
      expect(r.status).toBe(200);
      expect(r.headers.get("Access-Control-Allow-Origin")).toBe(SITE);
      expect(r.headers.get("Vary")).toBe("Origin");
      expect(r.headers.get("Access-Control-Expose-Headers")).toContain("X-Radar-Indice");
    }
  });

  it("localhost e 127.0.0.1 só são permitidos em staging, mesmo se configurados em produção", async () => {
    for (const origem of ["http://localhost:8000", "http://127.0.0.1:5173", "http://localhost", "http://127.0.0.1"]) {
      for (const AMBIENTE of ["production", "staging", undefined]) {
        for (const method of ["GET", "HEAD", "OPTIONS"]) {
          const r = await pedir("/api/busca?q=calendario&modo=palavras", { method, headers: { Origin: origem } },
            criarEnv({ AMBIENTE, ORIGENS_CORS: `${SITE},${origem}` }));
          expect(r.status).toBe(AMBIENTE === "staging" ? (method === "OPTIONS" ? 204 : 200) : 403);
          expect(r.headers.get("Access-Control-Allow-Origin")).toBe(AMBIENTE === "staging" ? origem : null);
          await r.text();
        }
      }
    }
  });

  it("fora dos locais de staging só aceita origens HTTPS exatas, nunca HTTP configurado", () => {
    for (const ambiente of ["production", "staging", undefined]) {
      const lista = `${SITE},http://site.example,https://site.example/caminho,https://localhost:8000`;
      expect(origemPermitida(SITE, lista, ambiente)).toBe(true);
      for (const origem of ["http://site.example", "https://site.example/caminho", "https://localhost:8000", `${SITE}/`,
        "https://marco-jardim.github.io.mal.example", "http://localhost.mal:80", "null"]) {
        expect(origemPermitida(origem, lista, ambiente), origem).toBe(false);
      }
    }
  });

  it("recusa outras origens com 403 e sem Access-Control-Allow-Origin", async () => {
    for (const origem of ["https://mal.example", "null", "https://marco-jardim.github.io.mal.example", "http://localhost.mal:80",
      "https://localhost:8000"]) {
      const r = await pedir("/api/busca?q=calendario", { headers: { Origin: origem } });
      expect(r.status).toBe(403);
      expect(r.headers.get("Access-Control-Allow-Origin")).toBeNull();
      expect(r.headers.get("Vary")).toBe("Origin");
      expect(await r.json()).toEqual({ erro: "Origem não permitida.", codigo: "origem_recusada" });
    }
  });

  it("sem Origin não há cabeçalho CORS; preflight responde 204", async () => {
    const r = await pedir("/api/busca?q=calendario&modo=palavras");
    expect(r.headers.get("Access-Control-Allow-Origin")).toBeNull();
    const p = await pedir("/api/busca", { method: "OPTIONS", headers: { Origin: SITE, "Access-Control-Request-Method": "GET" } });
    expect(p.status).toBe(204);
    expect(p.headers.get("Access-Control-Allow-Origin")).toBe(SITE);
    expect(p.headers.get("Access-Control-Allow-Methods")).toBe("GET, HEAD, OPTIONS");
    expect(await p.text()).toBe("");
  });
});

describe("limites, cabeçalhos e erros", () => {
  it("429 quando o Rate Limiting recusa; a chave não contém o IP", async () => {
    const limite = new LimiteFalso(false);
    const r = await pedir("/api/busca?q=calendario", { headers: { "CF-Connecting-IP": "203.0.113.9", Origin: SITE } },
      criarEnv({ LIMITE: limite }));
    expect(r.status).toBe(429);
    expect(r.headers.get("Retry-After")).toBe("60");
    expect(r.headers.get("Access-Control-Allow-Origin")).toBe(SITE);
    expect(await r.json()).toEqual({ erro: expect.any(String), codigo: "limite" });
    expect(limite.chaves).toHaveLength(1);
    expect(limite.chaves[0]).toMatch(/^[0-9a-f]{32}$/);
    expect(limite.chaves[0]).not.toContain("203");
    const ok = new LimiteFalso(true);
    await pedir("/api/versao", { headers: { "CF-Connecting-IP": "203.0.113.9" } }, criarEnv({ LIMITE: ok }));
    await pedir("/api/versao", { headers: { "CF-Connecting-IP": "203.0.113.10" } }, criarEnv({ LIMITE: ok }));
    expect(ok.chaves[0]).not.toBe(ok.chaves[1]);
    expect((await pedir("/api/versao", {}, criarEnv({ LIMITE: undefined }))).status).toBe(200);
  });

  it("cabeçalhos de versão, Vary e segurança em todas as respostas", async () => {
    for (const caminho of ["/api/busca?q=calendario&modo=palavras", "/api/documento/doc:101", "/api/versao", "/api/inexistente"]) {
      const r = await pedir(caminho);
      expect(r.headers.get("X-Radar-Commit"), caminho).toBe("abc1234");
      expect(r.headers.get("X-Radar-Indice"), caminho).toBe("2026.10.27");
      expect(r.headers.get("Vary")).toBe("Origin");
      expect(r.headers.get("X-Content-Type-Options")).toBe("nosniff");
      expect(r.headers.get("Content-Security-Policy")).toBe("default-src 'none'; frame-ancestors 'none'");
      expect(r.headers.get("Content-Type")).toBe("application/json; charset=utf-8");
    }
    await carregar({ semEstado: true });
    const vazio = await pedir("/api/busca?q=calendario&modo=palavras", {}, criarEnv({ COMMIT: "x y<z>" }));
    expect(vazio.headers.get("X-Radar-Indice")).toBe("vazio");
    expect(vazio.headers.get("X-Radar-Commit")).toBe("xyz");
    expect((await pedir("/api/versao", {}, criarEnv({ COMMIT: undefined }))).headers.get("X-Radar-Commit")).toBe("desconhecido");
  });

  it("rotas e métodos inválidos respondem JSON {erro, codigo}", async () => {
    const casos: [string, RequestInit, number, string][] = [
      ["/", {}, 404, "rota_inexistente"],
      ["/api", {}, 404, "rota_inexistente"],
      ["/api/busca/extra", {}, 404, "rota_inexistente"],
      ["/api/documento/", {}, 404, "rota_inexistente"],
      ["/api/documento/doc:1/x", {}, 404, "rota_inexistente"],
      ["/api/busca?q=ab", { method: "POST" }, 405, "metodo_invalido"],
    ];
    for (const [caminho, init, status, codigo] of casos) {
      const r = await pedir(caminho, init);
      expect(r.status, caminho).toBe(status);
      expect(await r.json()).toEqual({ erro: expect.any(String), codigo });
    }
    expect((await pedir("/api/busca?q=ab", { method: "DELETE" })).headers.get("Allow")).toBe("GET, HEAD, OPTIONS");
  });

  it("falha do D1 não expõe mensagem nem pilha", async () => {
    const quebrado: D1Database = {
      prepare() { throw new Error("segredo interno do banco"); },
      batch() { throw new Error("segredo interno do banco"); },
    };
    for (const caminho of ["/api/busca?q=calendario", "/api/documento/doc:101", "/api/saude"]) {
      const r = await pedir(caminho, {}, criarEnv({ DB: quebrado }));
      expect(r.status).toBe(503);
      const texto = await r.text();
      expect(texto).not.toContain("segredo");
      expect(texto).not.toContain("at ");
      expect(JSON.parse(texto).codigo).toBe("indisponivel");
    }
    const real = env.DB as unknown as D1Database;
    let consultasFts = 0;
    const semFts: D1Database = {
      prepare(sql) {
        if (sql.includes("MATCH")) {
          consultasFts++;
          throw new Error("segredo: fts5 syntax error");
        }
        return real.prepare(sql);
      },
      batch: (i) => real.batch(i),
    };
    for (const modo of ["palavras", "hibrida"]) {
      const r = await pedir(`/api/busca?q=calendario&modo=${modo}`, {}, criarEnv({ DB: semFts }));
      expect(r.status).toBe(500);
      expect(r.headers.get("Cache-Control")).toBe("no-store");
      expect(await r.json()).toEqual({ erro: "Erro interno.", codigo: "interno" });
    }
    expect(consultasFts).toBe(2);
  });

  it("HEAD devolve só os cabeçalhos", async () => {
    const r = await pedir("/api/versao", { method: "HEAD" });
    expect(r.status).toBe(200);
    expect(await r.text()).toBe("");
  });

  it("HEAD /api/busca não consulta o banco, AI nem Vectorize", async () => {
    const ai = new AiFalsa();
    const vetores = new VetoresFalsos([]);
    const db: D1Database = {
      prepare() { throw new Error("HEAD não deve ler D1"); },
      batch() { throw new Error("HEAD não deve ler D1"); },
    };
    const r = await pedir("/api/busca?q=calendario", { method: "HEAD" }, criarEnv({ DB: db, AI: ai, VETORES: vetores }));
    expect(r.status).toBe(200);
    expect(r.headers.get("Cache-Control")).toBe("no-store");
    expect(await r.text()).toBe("");
    expect(ai.chamadas).toHaveLength(0);
    expect(vetores.chamadas).toHaveLength(0);
  });

  it("HEAD /api/busca valida os mesmos parâmetros do GET, sem banco ou busca", async () => {
    const ai = new AiFalsa();
    const vetores = new VetoresFalsos([]);
    const db: D1Database = {
      prepare() { throw new Error("HEAD inválido não deve ler D1"); },
      batch() { throw new Error("HEAD inválido não deve ler D1"); },
    };
    const e = criarEnv({ DB: db, AI: ai, VETORES: vetores });
    const consultas = ["", "q=a", `q=${"x".repeat(201)}`, "q=**", "q=de", "q=ab+xy", "q=calendario&q=licenca",
      ...["modo=outro", "tipo=outro", "ano=1800", "autor=Nome", "legislatura=2025", "pagina=0", "pagina=51", "ano=2025&ano=2026"]
        .map((filtro) => `q=calendario&${filtro}`)];
    for (const consulta of consultas) {
      const caminho = `/api/busca?${consulta}`;
      const get = await pedir(caminho);
      const head = await pedir(caminho, { method: "HEAD" }, e);
      expect(get.status, consulta).toBe(400);
      expect(head.status, consulta).toBe(get.status);
      expect(head.headers.get("Content-Type")).toBe(get.headers.get("Content-Type"));
      expect(head.headers.get("Cache-Control")).toBe("no-store");
      expect(await head.text()).toBe("");
      await get.text();
    }
    expect(ai.chamadas).toHaveLength(0);
    expect(vetores.chamadas).toHaveLength(0);
  });

  it("agrupa IPv6 por /64, inclusive grafias equivalentes", async () => {
    const limite = new LimiteFalso();
    for (const ip of ["2001:db8:abcd:12::1", "2001:0db8:abcd:0012:ffff::2", "2001:db8:abcd:13::1"]) {
      await pedir("/api/versao", { headers: { "CF-Connecting-IP": ip } }, criarEnv({ LIMITE: limite }));
    }
    expect(limite.chaves[0]).toBe(limite.chaves[1]);
    expect(limite.chaves[0]).not.toBe(limite.chaves[2]);
    expect(clienteLimite("::1")).toBe("0000:0000:0000:0000::/64");
    expect(clienteLimite("2001:db8:abcd:12:1:2:3:4")).toBe("2001:0db8:abcd:0012::/64");
    expect(clienteLimite("invalido:ip")).toBe("anonimo");
  });
});

describe("/api/documento/:id", () => {
  it("mantém os metadados, mas não oferece download quando r2_chave é NULL", async () => {
    await env.DB.prepare("UPDATE arquivos SET r2_chave = NULL WHERE id = ?").bind("siscam:1001").run();
    const corpo = await (await pedir("/api/documento/doc:101")).json() as Record<string, any>;
    expect(corpo.arquivos[0]).toMatchObject({ arquivo: "siscam:1001", sha256: sha(1), status: "ok", url_original: null });
    expect(corpo.documento.url_siscam).toBe("https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento=101");
  });

  it("devolve metadados, autoria, arquivos (inclusive do substitutivo) e substitutivos", async () => {
    for (const caminho of ["/api/documento/doc:101", "/api/documento/doc%3A101"]) {
      const r = await pedir(caminho);
      expect(r.status).toBe(200);
      expect(r.headers.get("Cache-Control")).toBe("public, max-age=60");
      const corpo = await r.json() as Record<string, any>;
      expect(corpo.documento).toEqual({
        id: "doc:101", tipo: "pl", numero: "1/2021", ano: 2021, data: "2021-03-01",
        ementa: "Institui o programa Tratamento Fora de Domicílio no município.", legislatura: "2021-2024", pl: null,
        url_siscam: "https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento=101",
      });
      expect(corpo.autoria).toEqual([{ slug: "ana-souza", nome: "Ana Souza", partido: "PA", papel: "autor" }]);
      expect(corpo.arquivos.map((a: { arquivo: string }) => a.arquivo)).toEqual(["siscam:1001", "siscam:1201"]);
      expect(corpo.arquivos[0]).toEqual({ arquivo: "siscam:1001", formato: "pdf", status: "ok", ocr: false, confianca: null,
        sha256: sha(1), url_original: `/api/original/${sha(1)}` });
      expect(corpo.substitutivos).toEqual([{ documento: "doc:201", numero: "1" }]);
    }
    const segunda = await pedir("/api/documento/doc:101");
    expect(segunda.headers.get("X-Radar-Cache")).toBe("HIT");
    const sub = await (await pedir("/api/documento/doc:201")).json() as Record<string, any>;
    expect(sub.documento.pl).toBe("doc:101");
    expect(sub.autoria.map((a: { papel: string }) => a.papel)).toEqual(["autor", "coautor"]);
    const ata = await (await pedir("/api/documento/sessao:9001")).json() as Record<string, any>;
    expect(ata.arquivos[0].arquivo).toBe("sessao:0f0e0d0c-0b0a-4908-8706-050403020100");
    expect(ata.documento.url_siscam).toBe("https://consultaniteroi.siscam.com.br/DetalhesSessao.aspx?Id=1");
  });

  it("omite arquivos removidos", async () => {
    await pedir("/api/documento/doc:101");
    expect((await pedir("/api/documento/doc:101")).headers.get("X-Radar-Cache")).toBe("HIT");
    await env.DB.prepare("INSERT INTO remocoes (chave, sha256, motivo, data) VALUES (?, ?, ?, ?)")
      .bind("siscam:9999", sha(1), "Pedido do titular.", "2026-10-01").run();
    const r = await pedir("/api/documento/doc:101");
    expect(r.headers.get("X-Radar-Cache")).toBe("MISS");
    const corpo = await r.json() as Record<string, any>;
    expect(corpo.arquivos.map((a: { arquivo: string }) => a.arquivo)).toEqual(["siscam:1201"]);
  });

  it("404 para documento inexistente e 400 para id inválido", async () => {
    const r = await pedir("/api/documento/doc:999");
    expect(r.status).toBe(404);
    expect(r.headers.get("Cache-Control")).toBe("no-store");
    expect(await r.json()).toEqual({ erro: "Documento não encontrado.", codigo: "documento_inexistente" });
    for (const id of ["xyz", "doc:0", "doc:01", "doc:1%27%20OR%201=1", "%E0%A4%A", "pl:1"]) {
      const e = await pedir(`/api/documento/${id}`);
      expect(e.status, id).toBe(400);
      expect((await e.json() as { codigo: string }).codigo).toBe("documento_invalido");
    }
  });

  it("ordena chaves de arquivo como o contrato", () => {
    expect(["sessao:b", "siscam:10", "sessao:a", "siscam:9"].sort(ordemArquivo)).toEqual(["siscam:9", "siscam:10", "sessao:a", "sessao:b"]);
    expect(ordemArquivo("siscam:1", "siscam:1")).toBe(0);
    expect(["outra:1", "sessao:a"].sort(ordemArquivo)).toEqual(["outra:1", "sessao:a"]);
  });
});

describe("/api/original/:sha256", () => {
  const caminho = `/api/original/${sha(1)}`;

  it("404 original_indisponivel com link ao SISCAM para r2_chave NULL, mesmo após cache", async () => {
    await (await pedir(caminho)).arrayBuffer();
    await env.DB.prepare("UPDATE arquivos SET r2_chave = NULL WHERE id = ?").bind("siscam:1001").run();
    const r = await pedir(caminho);
    const urlSiscam = "https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento=101";
    expect(r.status).toBe(404);
    expect(r.headers.get("Cache-Control")).toBe("no-store");
    expect(await r.json()).toEqual({ codigo: "original_indisponivel", erro: expect.stringContaining(urlSiscam), url_siscam: urlSiscam });
    const h = await pedir(caminho, { method: "HEAD" });
    expect(h.status).toBe(404);
    expect(await h.text()).toBe("");
    await env.DB.prepare("INSERT INTO remocoes (chave, sha256, motivo, data) VALUES (?, ?, ?, ?)")
      .bind("siscam:1001", sha(1), "Pedido do titular.", "2026-10-01").run();
    expect((await pedir(caminho)).status).toBe(410);
  });

  it("original_indisponivel sem inventar URL quando o D1 não tem link", async () => {
    await env.DB.prepare("UPDATE arquivos SET r2_chave = NULL WHERE id = ?").bind("siscam:1001").run();
    await env.DB.prepare("UPDATE documentos SET url = NULL WHERE id = ?").bind("doc:101").run();
    const r = await pedir(caminho);
    expect(r.status).toBe(404);
    expect(await r.json()).toEqual({ codigo: "original_indisponivel", erro: expect.stringContaining("SISCAM") });
  });

  it("serve o original do R2 com os cabeçalhos de segurança", async () => {
    const r = await pedir(caminho);
    expect(r.status).toBe(200);
    expect(await r.text()).toBe("conteúdo do original siscam:1001");
    expect(r.headers.get("Content-Disposition")).toBe('attachment; filename="siscam-1001.pdf"');
    expect(r.headers.get("Content-Type")).toBe("application/pdf");
    expect(r.headers.get("X-Robots-Tag")).toBe("noindex");
    expect(r.headers.get("X-Content-Type-Options")).toBe("nosniff");
    expect(r.headers.get("Content-Security-Policy")).toBe("sandbox");
    expect(r.headers.get("Cache-Control")).toBe("no-store");
    expect(r.headers.get("ETag")).toBe(`"${sha(1)}"`);
    expect(r.headers.get("Content-Length")).toBe(String(new TextEncoder().encode("conteúdo do original siscam:1001").length));
    const docx = await pedir(`/api/original/${sha(2).toUpperCase()}`);
    expect(docx.headers.get("Content-Disposition")).toBe('attachment; filename="siscam-1002.docx"');
  });

  it("410 depois da remoção, mesmo com o original já na Cache API", async () => {
    await pedir(caminho);
    const guardado = await pedir(caminho);
    expect(guardado.headers.get("X-Radar-Cache")).toBe("HIT");
    expect(guardado.headers.get("Content-Security-Policy")).toBe("sandbox");
    expect(guardado.headers.get("Cache-Control")).toBe("no-store");
    await env.DB.prepare("INSERT INTO remocoes (chave, sha256, motivo, data) VALUES (?, ?, ?, ?)")
      .bind("siscam:1001", sha(1), "Pedido do titular.", "2026-10-01").run();
    const r = await pedir(caminho);
    expect(r.status).toBe(410);
    expect(await r.json()).toEqual({ erro: expect.stringContaining(`${criarEnv().URL_SITE}/metodologia.html#privacidade`), codigo: "removido" });
    expect(r.headers.get("Cache-Control")).toBe("no-store");
  });

  it("410 também quando só a chave do arquivo foi removida", async () => {
    await env.DB.prepare("INSERT INTO remocoes (chave, sha256, motivo, data) VALUES (?, ?, ?, ?)")
      .bind("siscam:1002", sha(251), "Pedido do titular.", "2026-10-01").run();
    expect((await pedir(`/api/original/${sha(2)}`)).status).toBe(410);
  });

  it("404 sem arquivo ou sem objeto no R2; 400 para SHA-256 inválido; HEAD sem corpo", async () => {
    expect((await pedir(`/api/original/${"0".repeat(64)}`)).status).toBe(404);
    expect((await pedir(`/api/original/${sha(4)}`)).status).toBe(404); // linha no D1, objeto ausente no R2
    await env.DB.prepare("UPDATE arquivos SET r2_chave = ? WHERE id = ?").bind("outra/chave", "siscam:1003").run();
    expect((await pedir(`/api/original/${sha(3)}`)).status).toBe(404);
    for (const s of ["abc", `${"g".repeat(64)}`, `${sha(1)}0`]) {
      const r = await pedir(`/api/original/${s}`);
      expect(r.status).toBe(400);
      expect((await r.json() as { codigo: string }).codigo).toBe("sha256_invalido");
    }
    const h = await pedir(`/api/original/${sha(2)}`, { method: "HEAD" });
    expect(h.status).toBe(200);
    expect(h.headers.get("Content-Length")).toBe(String(new TextEncoder().encode("conteúdo do original siscam:1002").length));
    expect(h.headers.get("Content-Disposition")).toContain("siscam-1002.docx");
    expect(await h.text()).toBe("");
  });

  it("nomes de arquivo seguros", () => {
    expect(nomeArquivo("sessao:0f0e0d0c-0b0a-4908-8706-050403020100", "docx")).toBe("sessao-0f0e0d0c-0b0a-4908-8706-050403020100.docx");
    expect(nomeArquivo("siscam:7", null)).toBe("siscam-7.bin");
    expect(nomeArquivo("siscam:7", "html")).toBe("siscam-7.html");
  });

  it("HEAD de um original já guardado mantém tamanho e segurança, sem corpo", async () => {
    await (await pedir(caminho)).arrayBuffer();
    const get = await pedir(caminho);
    expect(get.headers.get("X-Radar-Cache")).toBe("HIT");
    const head = await pedir(caminho, { method: "HEAD" });
    expect(head.status).toBe(200);
    for (const nome of ["Content-Length", "Content-Type", "Content-Disposition", "ETag", "Cache-Control", "Content-Security-Policy"]) {
      expect(head.headers.get(nome), nome).toBe(get.headers.get(nome));
    }
    expect(await head.text()).toBe("");
    await get.arrayBuffer();
  });

  it("transmite originais maiores que 10 MiB sem clonar para a Cache API", async () => {
    const tamanho = MAX_CACHE_ORIGINAL + 1;
    await env.ARQUIVOS.put(chaveR2(sha(1)), new Uint8Array(tamanho));
    for (let i = 0; i < 2; i++) {
      const r = await pedir(caminho);
      expect(r.headers.get("X-Radar-Cache")).toBe("MISS");
      expect(r.headers.get("Content-Length")).toBe(String(tamanho));
      expect(r.headers.get("Cache-Control")).toBe("no-store");
      expect((await r.arrayBuffer()).byteLength).toBe(tamanho);
    }
  });
});

it("a hidratação semântica descarta remoção por SHA-256 ocorrida depois da seleção", async () => {
  const real = env.DB as unknown as D1Database;
  let lotes = 0;
  const db: D1Database = {
    prepare: (sql) => real.prepare(sql),
    async batch<T>(instrucoes: D1Instrucao[]) {
      const linhas = await real.batch<T>(instrucoes);
      // Primeiro lote: estado+remoções; segundo: seleção dos candidatos semânticos.
      if (++lotes === 2) {
        await env.DB.prepare("INSERT INTO remocoes (chave, sha256, motivo, data) VALUES (?, ?, ?, ?)")
          .bind("siscam:9999", sha(2), "Pedido do titular.", "2026-10-01").run();
      }
      return linhas;
    },
  };
  const { corpo } = await buscarJson({ q: "hidratação posterior", modo: "semantica" }, criarEnv({ DB: db,
    VETORES: new VetoresFalsos([trechoDe("siscam:1002").id]) }));
  expect(corpo.resultados).toEqual([]);
  expect(lotes).toBe(3);
});

describe("/api/versao e /api/saude", () => {
  it("versão do código e do índice", async () => {
    const meta = { id: "v-123", tag: "", timestamp: "2026-10-27T12:00:00Z" };
    const r = await pedir("/api/versao", {}, criarEnv({ CF_VERSION_METADATA: meta }));
    expect(r.headers.get("Cache-Control")).toBe("no-store");
    const corpo = await r.json() as Record<string, any>;
    expect(corpo.ambiente).toBe("teste");
    expect(corpo.codigo).toEqual({ commit: "abc1234", versao: "v-123", tag: null, publicado_em: "2026-10-27T12:00:00Z" });
    expect(corpo.indice).toMatchObject({ versao: "2026.10.27", commit: "c0ffee1", modelo: "@cf/baai/bge-m3", versao_trechos: "2" });
    const sem = await (await pedir("/api/versao", {}, criarEnv({ CF_VERSION_METADATA: undefined, AMBIENTE: undefined }))).json() as Record<string, any>;
    expect(sem.codigo.versao).toBeNull();
    expect(sem.ambiente).toBeNull();
  });

  it("saúde com e sem verificação", async () => {
    const a = await (await pedir("/api/saude")).json() as Record<string, any>;
    expect(a).toMatchObject({ ok: true, d1: "ok", indice: { versao: "2026.10.27" }, verificacao: null });
    await env.DB.prepare("INSERT INTO verificacoes (data, amostra, ok, falhas_json) VALUES (?, ?, ?, ?)")
      .bind("2026-10-27T07:17:00Z", 200, 200, "[]").run();
    const b = await (await pedir("/api/saude")).json() as Record<string, any>;
    expect(b.verificacao).toEqual({ data: "2026-10-27T07:17:00Z", amostra: 200, ok: 200 });
  });
});

describe("wrangler.jsonc", () => {
  const config = JSON.parse((env.WRANGLER_JSONC as string).split("\n").filter((l) => !l.trim().startsWith("//")).join("\n"));

  it("ORIGENS_CORS acompanha exatamente config/backend.json nos dois ambientes", () => {
    const backend = JSON.parse(env.BACKEND_JSON as string) as { origens_cors: string[] };
    // Produção: exatamente as origens do site; staging acrescenta só os servidores locais de desenvolvimento.
    const locais = ["http://127.0.0.1:8000", "http://localhost:8000"];
    expect(config.vars.ORIGENS_CORS.split(",").sort()).toEqual([...backend.origens_cors].sort());
    expect(config.env.staging.vars.ORIGENS_CORS.split(",").sort()).toEqual([...backend.origens_cors, ...locais].sort());
    expect(config.vars.AMBIENTE).toBe("production");
    expect(config.env.staging.vars.AMBIENTE).toBe("staging");
    for (const origem of backend.origens_cors) {
      expect(origem.startsWith("https://")).toBe(true);
      expect(origemPermitida(origem, config.vars.ORIGENS_CORS, config.vars.AMBIENTE)).toBe(true);
    }
    for (const origem of locais) {
      expect(origemPermitida(origem, config.vars.ORIGENS_CORS, config.vars.AMBIENTE)).toBe(false);
      expect(origemPermitida(origem, config.env.staging.vars.ORIGENS_CORS, config.env.staging.vars.AMBIENTE)).toBe(true);
    }
    for (const ambiente of [config, config.env.staging]) expect(ambiente.vars.URL_SITE).toBe(criarEnv().URL_SITE);
  });

  it("todo cron declarado tem handler e fontes públicas configuradas", () => {
    expect(config.triggers.crons).toEqual(["17 7 * * *"]);
    expect(config.env.staging.triggers.crons).toEqual([]);
    for (const ambiente of [config, config.env.staging]) {
      expect(worker.scheduled).toBeTypeOf("function");
      expect(ambiente.vars.CRON_RAW_BASE).toBe("https://raw.githubusercontent.com/marco-jardim/radar-vereadores-niteroi");
      expect(ambiente.vars.CRON_MANIFESTOS_BRANCH).toBe("main");
      expect(ambiente.vars.CRON_TEXTOS_BRANCH).toBe("dados-textos");
    }
  });

  it("observabilidade desligada e sem Logpush, na produção e no staging", () => {
    for (const ambiente of [config, config.env.staging]) {
      expect(ambiente.observability).toEqual({ enabled: false });
      expect(ambiente.logpush ?? false).toBe(false);
      expect(ambiente.version_metadata).toEqual({ binding: "CF_VERSION_METADATA" });
      expect(ambiente.limits.cpu_ms).toBeGreaterThan(0);
      expect(ambiente.ratelimits[0]).toMatchObject({ name: "LIMITE", simple: { limit: 60, period: 60 } });
      expect(ambiente.vectorize[0].binding).toBe("VETORES");
      expect(ambiente.ai.binding).toBe("AI");
    }
    expect(config.main).toBe("src/index.ts");
    expect(config.name).toBe("radar-niteroi-api");
    expect(config.env.staging.name).toBe("radar-niteroi-api-staging");
  });
});

// Garante que `Env` e o env dos testes continuem compatíveis.
const _tipo: Env = criarEnv();
void _tipo;
