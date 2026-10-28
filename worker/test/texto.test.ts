import { env } from "cloudflare:test";
import { describe, expect, it } from "vitest";
import { consultaFts, destacar, escaparHtml, normalizar, palavrasAlvo, termos } from "../src/texto";

describe("normalizar", () => {
  it("segue os pares do contrato (tests/fixtures/contratos/normalizacao.json), iguais ao Python", () => {
    const dados = JSON.parse(env.NORMALIZACAO as string) as { funcao_js: string; pares: { entrada: string; saida: string }[] };
    expect(dados.funcao_js).toBe('s.normalize("NFD").replace(/\\p{Mn}/gu, "").normalize("NFC").toLowerCase()');
    expect(dados.pares.length).toBeGreaterThan(10);
    for (const { entrada, saida } of dados.pares) expect(normalizar(entrada)).toBe(saida);
  });

  it("com e sem acento dão a mesma forma", () => {
    expect(normalizar("Licença")).toBe(normalizar("licenca"));
    expect(normalizar("PRAÇA")).toBe("praca");
  });
});

describe("termos e consultaFts", () => {
  it("divide por espaços, normaliza e descarta repetidos e termos sem letra ou dígito", () => {
    expect(termos("  Licença  licenca * ( ) \"  Niterói ")).toEqual(["licenca", "niteroi"]);
    expect(termos("**")).toEqual([]);
    expect(termos("a\u0000b\u200bc")).toEqual(["a", "b", "c"]);
  });

  it("cada termo vira frase entre aspas, com aspas internas duplicadas", () => {
    expect(consultaFts(termos('NEAR( a"b OR c* col:x)'))).toBe('"near(" "a""b" "or" "c*" "col:x)"');
    expect(consultaFts(['"'])).toBe('""""');
  });

  it("palavras-alvo são as partes alfanuméricas dos termos", () => {
    expect([...palavrasAlvo(termos("29/2024 near(calendario"))]).toEqual(["29", "2024", "near", "calendario"]);
  });
});

describe("destacar", () => {
  const alvos = palavrasAlvo(termos("praca juventude"));

  it("escapa o HTML do texto e só emite <mark>", () => {
    const html = destacar("A Praça <script>alert(1)</script> & a Juventude \"x\" 'y'", alvos);
    expect(html).toBe("A <mark>Praça</mark> &lt;script&gt;alert(1)&lt;/script&gt; &amp; a <mark>Juventude</mark> &quot;x&quot; &#39;y&#39;");
    expect(html.replace(/<\/?mark>/g, "")).not.toMatch(/[<>]/);
  });

  it("sem correspondência, mostra o início, com reticências quando corta", () => {
    const texto = `${"palavra ".repeat(60)}fim`;
    const html = destacar(texto, new Set(["inexistente"]));
    expect(html.startsWith("palavra palavra")).toBe(true);
    expect(html.endsWith(" …")).toBe(true);
    expect(html.length).toBeLessThan(340);
    expect(destacar("", alvos)).toBe("");
  });

  it("escolhe a janela com mais termos distintos e compacta espaços", () => {
    const texto = `praca ${"x ".repeat(300)}praca\n\n\fjuventude ${"y ".repeat(300)}`;
    const html = destacar(texto, alvos);
    expect(html.startsWith("… ")).toBe(true);
    expect(html).toContain("<mark>praca</mark> <mark>juventude</mark>");
    expect(html.endsWith(" …")).toBe(true);
  });

  it("não corta pares substitutos nem marcas parciais", () => {
    for (const texto of [`a${"😀".repeat(400)}`, "😀".repeat(400)]) {
      const html = destacar(texto, alvos);
      expect(html.endsWith(" …")).toBe(true);
      expect(html).not.toMatch(/[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/);
    }
    const parcial = `praca ${"-".repeat(310)}juventude${"-".repeat(100)}`;
    const html = destacar(parcial, alvos);
    expect(html).toContain("<mark>praca</mark>");
    expect(html).toContain("juve");
    expect(html).not.toContain("<mark>juv");
  });

  it("escaparHtml cobre os cinco caracteres", () => {
    expect(escaparHtml(`<>&"'`)).toBe("&lt;&gt;&amp;&quot;&#39;");
  });
});
