"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const zlib = require("node:zlib");
const B = require("../../site_src/busca.js");
const fixture = require("./fixtures/busca.json");
const copiar = (x) => JSON.parse(JSON.stringify(x));
const assentar = () => new Promise((resolve) => setImmediate(resolve));

function ambiente(api = "https://api.example.test", consulta = "") {
  const eventos = {}, requisicoes = [], respostas = [], urls = [];
  let foco = null;
  const campo = (value = "") => ({ value });
  const campos = Object.fromEntries(["q", "modo", "tipo", "ano", "autor", "legislatura"].map((k) => [k, campo()]));
  const nos = {
    "busca-form": { elements: { namedItem: (k) => campos[k] }, reportValidity: () => true },
    "busca-campos": { disabled: true }, "busca-alternativa": {},
    "busca-estado": { focus() { foco = "busca-estado"; } }, "busca-aviso": {},
    "busca-mais": { hidden: true, disabled: false },
    "busca-resultados": {
      children: [], html: "", attrs: {},
      set innerHTML(v) { this.html = v; this.children = []; },
      get innerHTML() { return this.html; },
      setAttribute(k, v) { this.attrs[k] = v; },
      insertAdjacentHTML(pos, html) {
        assert.equal(pos, "beforeend");
        this.html += html;
        for (const _ of html.matchAll(/<li tabindex="-1">/g)) {
          const n = this.children.length;
          this.children.push({ focus() { foco = n; } });
        }
      }
    }
  };
  const doc = {
    getElementById: (id) => nos[id], querySelector: () => ({ content: api }),
    addEventListener(tipo, fn) { assert.equal(eventos[tipo], undefined, "um listener por tipo"); eventos[tipo] = fn; }
  };
  const janela = {
    location: { pathname: "/radar/busca.html", search: consulta, hash: "" },
    history: { replaceState(a, b, url) { urls.push(url); } },
    AbortController, setTimeout, clearTimeout,
    async fetch(url, opcoes) {
      requisicoes.push({ url, opcoes });
      const r = respostas.shift();
      if (typeof r === "function") return r();
      if (r instanceof Error) throw r;
      return { ok: (r?.status || 200) === 200, status: r?.status || 200, json: async () => copiar(r?.dados || fixture) };
    }
  };
  const acao = (tipo, id) => eventos[tipo]({ target: nos[id], preventDefault() {} });
  return { doc, janela, nos, campos, eventos, respostas, requisicoes, urls, acao, foco: () => foco };
}

test("consulta preserva filtros e acentos, sem padrões ou parâmetros estranhos", () => {
  const st = B.lerUrl("?q=sa%C3%BAde+%26+educa%C3%A7%C3%A3o&modo=palavras&tipo=pl&ano=2025&autor=ana&legislatura=2025-2028&pagina=8&x=1");
  assert.equal(st.q, "saúde & educação");
  const url = new URL(B.urlBusca("https://api.example.test", st, 2));
  assert.equal(url.pathname, "/api/busca");
  assert.equal(url.searchParams.get("q"), st.q);
  assert.equal(url.searchParams.get("pagina"), "2");
  assert.equal(url.searchParams.get("autor"), "ana");
  assert.equal(url.searchParams.get("legislatura"), "2025-2028");
  assert.equal(url.searchParams.has("x"), false);
  assert.deepEqual(B.lerUrl(B.consultaUrl(st)), st);
  assert.equal(B.consultaUrl(B.lerUrl("?modo=hibrida&tipo=x&ano=1800&autor=../x&legislatura=x")), "");
});

test("somente marcadores mark exatos são permitidos; entidades não viram tags", () => {
  assert.equal(B.destaque(fixture.resultados[0].trecho), "A <mark>saúde</mark> &amp; a educação. &lt;script&gt;texto&lt;/script&gt;");
  for (const trecho of ["<script>alert(1)</script>", '<img src=x onerror="alert(1)">', '<mark onclick="x">teste</mark>',
    "&lt;img src=x onerror=x&gt;", "&#60;script&#62;x&#60;/script&#62;", "<MARK>x</MARK>"]) {
    const html = B.destaque(trecho);
    assert.doesNotMatch(html, /<(?!\/?mark>)/);
  }
  assert.equal(B.destaque("<mark>x"), "<mark>x</mark>");
  assert.equal(B.destaque("&amp;lt;mark&amp;gt;"), "&amp;lt;mark&amp;gt;");
  assert.equal(B.destaque("&#x110000;"), "&amp;#x110000;");
});

test("cartões escapam todos os campos, restringem links e mostram fonte, hash, OCR e origem", () => {
  const r = fixture.resultados[0], html = B.cartao(r, "https://api.example.test");
  for (const texto of ["OCR de baixa confiança", "52.3", "SHA-256", r.sha256, "sem máscara", "palavras e significado", "&lt;teste&gt;"]) assert.ok(html.includes(texto));
  assert.ok(html.includes('href="https://api.example.test' + r.url_original + '"'));
  const ruim = B.cartao({ ...r, tipo: "<img>", numero: '<img onerror="x">', ementa: "<script>x</script>", trecho: '<img onerror="x">',
    arquivo: '<img onerror="x">', url_siscam: "javascript:alert(1)", url_original: "https://evil.test", origem: "<script>" }, "https://api.example.test");
  assert.doesNotMatch(ruim, /<img|<script|javascript:|evil\.test/);
  assert.match(B.cartao({ ...r, status: "ok_ocr" }, "https://api.example.test"), />OCR ·/);
  assert.match(B.cartao({ tipo: "indicacao", trecho: "ementa", origem: "palavras" }, "https://api.example.test"), /Somente ementa/);
  for (const tipo of ["constructor", "toString", "__proto__"]) {
    assert.match(B.cartao({ tipo }, "https://api.example.test"), /<h3>Documento<\/h3>/);
    assert.equal(B.lerUrl("?tipo=" + tipo).tipo, "");
  }
});

test("extração parcial tem selo, inclusive quando também recebeu OCR", () => {
  for (const ocr of [false, true]) {
    const html = B.cartao({ ...fixture.resultados[0], status: "ok_parcial", ocr }, "https://api.example.test");
    assert.match(html, /class="busca-selo">Extração parcial/);
    assert.equal(html.includes(" · OCR"), ocr);
  }
});

test("resultados sem arquivo mostram a ementa apenas no trecho com destaque", () => {
  for (const tipo of ["indicacao", "mocao"]) {
    const html = B.cartao({ tipo, ementa: "ementa única", trecho: "<mark>ementa</mark> única", arquivo: null }, "https://api.example.test");
    assert.match(html, /<p><mark>ementa<\/mark> única<\/p>/);
    assert.doesNotMatch(html, /<p>ementa única<\/p>/);
    assert.match(html, /Somente ementa/);
  }
});

test("ata aceita o link real de sessão do SISCAM com IdDocumento", () => {
  const url = "https://consultaniteroi.siscam.com.br/DetalhesSessao.aspx?IdDocumento=123";
  const html = B.cartao({ ...fixture.resultados[0], tipo: "ata", url_siscam: url }, "https://api.example.test");
  assert.ok(html.includes('href="' + url + '"'));
  for (const ruim of [url.replace("https:", "http:"), url.replace(".com.br/", ".com.br.evil.test/"), url + "&x=1"]) {
    assert.doesNotMatch(B.cartao({ tipo: "ata", url_siscam: ruim }, "https://api.example.test"), /Ver no SISCAM/);
  }
});

test("sem API, API inválida ou fetch não habilita o formulário nem busca", () => {
  for (const api of ["", "http://api.example.test", "javascript:x", "https://user:senha@example.test"]) {
    const a = ambiente(api);
    assert.equal(B.iniciar(a.doc, a.janela), null);
    assert.equal(a.nos["busca-campos"].disabled, true);
    assert.equal(a.requisicoes.length, 0);
  }
  const a = ambiente();
  delete a.janela.fetch;
  assert.equal(B.iniciar(a.doc, a.janela), null);
});

test("submit sincroniza URL, paginação anuncia e foca primeiro item novo, inclusive último lote", async () => {
  const a = ambiente();
  B.iniciar(a.doc, a.janela);
  assert.equal(a.nos["busca-campos"].disabled, false);
  assert.deepEqual(Object.keys(a.eventos).sort(), ["click", "submit"]);
  Object.assign(a.campos.q, { value: "saúde" });
  a.campos.autor.value = "ana";
  a.acao("submit", "busca-form");
  await assentar();
  assert.match(a.urls[0], /busca\.html\?q=sa%C3%BAde&autor=ana$/);
  assert.equal(a.foco(), 0);
  assert.equal(a.nos["busca-mais"].hidden, false);
  assert.equal(a.requisicoes[0].opcoes.credentials, "omit");
  a.respostas.push({ dados: { ...fixture, pagina: 2 } });
  a.acao("click", "busca-mais");
  await assentar();
  assert.equal(new URL(a.requisicoes[1].url).searchParams.get("pagina"), "2");
  assert.equal(a.nos["busca-resultados"].children.length, 2);
  assert.equal(a.nos["busca-mais"].hidden, true);
  assert.equal(a.foco(), 1);
  assert.match(a.nos["busca-estado"].textContent, /1 resultado adicionado.*2 resultados exibidos/);
  assert.equal(a.nos["busca-resultados"].attrs["aria-busy"], "false");
});

test("URL inicial preenche formulário e consulta, sem roubar foco", async () => {
  const a = ambiente("https://api.example.test", "?q=sa%C3%BAde&tipo=pl&ano=2025");
  B.iniciar(a.doc, a.janela);
  await assentar();
  assert.equal(a.campos.q.value, "saúde");
  assert.equal(a.campos.tipo.value, "pl");
  assert.equal(a.foco(), null);
  assert.equal(a.requisicoes.length, 1);
});

test("Mostrar mais vazio esconde botão, anuncia contagem real e foca o estado", async () => {
  const a = ambiente();
  const c = B.iniciar(a.doc, a.janela);
  a.campos.q.value = "saúde";
  await c.buscar(false, true);
  assert.equal(a.nos["busca-mais"].hidden, false);
  a.respostas.push({ dados: { ...fixture, pagina: 2, resultados: [] } });
  await c.buscar(true, true);
  assert.equal(a.nos["busca-resultados"].children.length, 1);
  assert.equal(a.nos["busca-mais"].hidden, true);
  assert.equal(a.foco(), "busca-estado");
  assert.equal(a.nos["busca-estado"].textContent, "0 resultados adicionados. 1 resultado exibido de 2.");
});

test("páginas curtas contam itens renderizados, não tamanho teórico da página", async () => {
  const a = ambiente();
  a.respostas.push({ dados: { ...fixture, por_pagina: 2, total: 3 } });
  const c = B.iniciar(a.doc, a.janela);
  a.campos.q.value = "saúde";
  await c.buscar(false, false);
  a.respostas.push({ dados: { ...fixture, por_pagina: 2, total: 3, pagina: 2 } });
  await c.buscar(true, true);
  assert.equal(a.nos["busca-mais"].hidden, false);
  assert.match(a.nos["busca-estado"].textContent, /2 resultados exibidos de 3/);
});

test("estados vazio, 400 genérico, 429, JSON inválido e rede sem apagar alternativas", async () => {
  for (const [resposta, mensagem] of [
    [{ dados: { ...fixture, resultados: [], total: 0 } }, /Nenhum resultado/],
    [{ status: 400, dados: { erro: "genérica", codigo: "consulta_muito_generica" } }, /mais específico/],
    [{ status: 429, dados: { erro: "limite", codigo: "limite" } }, /Aguarde um minuto/],
    [{ status: 503, dados: { codigo: "semantica_indisponivel" } }, /A busca por significado está indisponível; tente o modo Palavras\./],
    [{ status: 503, dados: {} }, /indisponível/],
    [{ dados: {} }, /indisponível/],
    [new Error("offline"), /indisponível/]
  ]) {
    const a = ambiente();
    a.respostas.push(resposta);
    const cliente = B.iniciar(a.doc, a.janela);
    a.campos.q.value = "saúde";
    await cliente.buscar(false, true);
    assert.match(a.nos["busca-estado"].textContent, mensagem);
    assert.equal(a.nos["busca-mais"].hidden, true);
    assert.match(a.nos["busca-alternativa"].textContent, /listas e o SISCAM/);
  }
  assert.equal(B.mensagemErro(400, { erro: "<img onerror=x>" }), "<img onerror=x>"); // vai a textContent
});

test("erros HTTP preservam mensagem mesmo quando corpo não é JSON", async () => {
  for (const [status, mensagem] of [[429, /Aguarde um minuto/], [500, /indisponível/], [502, /indisponível/], [503, /indisponível/]]) {
    const a = ambiente();
    let statusLido = false;
    a.respostas.push(() => ({
      get ok() { statusLido = true; return false; }, status,
      async json() { assert.equal(statusLido, true); throw new SyntaxError("<html>erro</html>"); }
    }));
    const c = B.iniciar(a.doc, a.janela);
    a.campos.q.value = "saúde";
    await c.buscar(false, true);
    assert.equal(statusLido, true);
    assert.match(a.nos["busca-estado"].textContent, mensagem);
    assert.equal(a.nos["busca-resultados"].children.length, 0);
  }
});

test("aviso de fallback e teto ficam visíveis como texto; erro de página permite tentar de novo", async () => {
  const a = ambiente();
  a.respostas.push({ dados: { ...fixture, aviso: "<img onerror=x> Só palavras.", limitado: true } });
  const c = B.iniciar(a.doc, a.janela);
  a.campos.q.value = "saúde";
  await c.buscar(false, false);
  assert.match(a.nos["busca-aviso"].textContent, /<img onerror=x> Só palavras.*limite/);
  a.respostas.push(new Error("offline"));
  await c.buscar(true, true);
  assert.equal(a.nos["busca-resultados"].children.length, 1);
  assert.equal(a.nos["busca-mais"].disabled, false);
  assert.equal(a.nos["busca-mais"].hidden, false);
  a.respostas.push({ dados: { ...fixture, pagina: 2 } });
  await c.buscar(true, true);
  assert.equal(a.foco(), 1);
});

test("resposta atrasada não substitui consulta mais recente", async () => {
  const a = ambiente();
  let resolver;
  a.respostas.push(() => new Promise((r) => { resolver = r; }));
  const c = B.iniciar(a.doc, a.janela);
  a.campos.q.value = "saúde";
  const primeira = c.buscar(false, true);
  a.campos.q.value = "escola";
  await c.buscar(false, true);
  resolver({ ok: true, json: async () => ({ ...fixture, resultados: [], total: 0 }) });
  await primeira;
  assert.equal(a.nos["busca-resultados"].children.length, 1);
  assert.match(a.urls.at(-1), /q=escola/);
});

test("script cabe em 6 KiB gzip", () => {
  const fonte = fs.readFileSync(path.join(__dirname, "../../site_src/busca.js"));
  assert.ok(zlib.gzipSync(fonte).length <= 6 * 1024);
});
