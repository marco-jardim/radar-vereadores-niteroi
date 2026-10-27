"use strict";

// Interações de app.js com harness próprio: tooltip (ponteiro, toque, foco, Esc), abas do placar no padrão
// WAI-ARIA, foco e anúncio do "Mostrar mais" e a lista de coautores em <details>.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const RadarDados = require("../../site_src/dados.js");
const fixture = require("./fixtures/pl.json");
const fonte = fs.readFileSync(path.join(__dirname, "../../site_src/app.js"), "utf8");
const copiar = (x) => JSON.parse(JSON.stringify(x));
const assentar = () => new Promise((resolve) => setImmediate(resolve));

// ------------------------------------------------------------- página sem lista
function no(extra = {}) {
  return Object.assign({ atributos: {}, eventos: {}, hidden: false, isConnected: true, style: {}, textContent: "",
    getAttribute(n) { return Object.prototype.hasOwnProperty.call(this.atributos, n) ? this.atributos[n] : null; },
    setAttribute(n, v) { this.atributos[n] = String(v); },
    removeAttribute(n) { delete this.atributos[n]; },
    addEventListener(tipo, fn) { this.eventos[tipo] = fn; },
    getBoundingClientRect() { return { left: 100, top: 200, width: 20, height: 10 }; } }, extra);
}

function marca(texto) {
  const m = no({ tagName: "rect" });
  m.atributos["data-tip"] = texto;
  m.closest = (sel) => (sel === "[data-tip]" ? m : null);
  return m;
}
const FORA = { tagName: "DIV", closest: () => null, querySelector: () => null };

// abas: [{ id, sel }] na ordem do servidor; ponteiro: false simula navegador sem PointerEvent.
function iniciarPagina({ abas = [], ponteiro = true, semApiPainel = false } = {}) {
  const eventos = {}, elementos = {};
  let focado = null;
  const tip = no({ hidden: true });
  elementos.tip = tip;
  const botoes = abas.map((a) => {
    const painel = no({ id: "leg-" + a.id, querySelector: () => null });
    if (semApiPainel) delete painel.setAttribute;
    elementos["leg-" + a.id] = painel;
    const bt = no({ id: "aba-leg-" + a.id });
    Object.assign(bt.atributos, { role: "tab", id: "aba-leg-" + a.id, "aria-controls": "leg-" + a.id,
      "aria-selected": a.sel ? "true" : "false", tabindex: a.sel ? "0" : "-1" });
    bt.focus = () => { focado = bt; };
    return bt;
  });
  const listaAbas = no({ hidden: true, querySelectorAll: (sel) => (sel === '[role="tab"]' ? botoes : []) });
  const documento = {
    documentElement: { classList: { add() {} } },
    body: { contains: () => true },
    addEventListener(tipo, fn) {
      if (eventos[tipo]) throw new Error("segundo listener de " + tipo + " no documento");
      eventos[tipo] = fn;
    },
    getElementById: (id) => elementos[id] || null,
    querySelector: (sel) => (sel === '.abas[role="tablist"]' && botoes.length ? listaAbas : null),
    querySelectorAll: () => [],
    createElement: () => no()
  };
  const janela = { RadarDados, innerWidth: 1024 };
  if (ponteiro) janela.PointerEvent = function PointerEvent() {};
  vm.runInNewContext(fonte, { document: documento, window: janela }, { filename: "app.js" });
  return {
    tip, eventos, botoes, listaAbas, elementos, focado: () => focado,
    painel: (id) => elementos["leg-" + id],
    disparar(tipo, ev) { eventos[tipo](ev); },
    tecla(bt, key) {
      let impedido = false;
      listaAbas.eventos.keydown({ key, target: bt, preventDefault() { impedido = true; } });
      return impedido;
    }
  };
}

test("tooltip: um listener por tipo no documento, pointermove no lugar de mousemove quando há PointerEvent", () => {
  const pag = iniciarPagina();
  assert.deepEqual(Object.keys(pag.eventos).sort(), ["focusin", "focusout", "keydown", "pointerdown", "pointermove", "scroll"]);
  const antigo = iniciarPagina({ ponteiro: false });
  assert.ok(antigo.eventos.mousemove);
  assert.equal(antigo.eventos.pointermove, undefined);
});

test("tooltip: abre ao passar o mouse e fecha ao sair; toque no mouse não alterna", () => {
  const pag = iniciarPagina(), a = marca("3 leis com efeito");
  pag.disparar("pointerdown", { pointerType: "mouse", target: a });
  assert.equal(pag.tip.hidden, true, "clique do mouse não abre como toque");
  pag.disparar("pointermove", { pointerType: "mouse", target: a, clientX: 50, clientY: 300 });
  assert.equal(pag.tip.hidden, false);
  assert.equal(pag.tip.textContent, "3 leis com efeito");
  pag.disparar("pointermove", { pointerType: "touch", target: FORA });
  assert.equal(pag.tip.hidden, false, "movimento de toque é ignorado");
  pag.disparar("pointermove", { pointerType: "mouse", target: FORA, clientX: 0, clientY: 0 });
  assert.equal(pag.tip.hidden, true);
  assert.equal(a.getAttribute("tabindex"), null, "a marca não recebe tabindex");
});

test("tooltip: toque alterna, dois tooltips em sequência e toque fora fecha", () => {
  const pag = iniciarPagina(), a = marca("A"), b = marca("B");
  pag.disparar("pointerdown", { pointerType: "touch", target: a });
  assert.equal(pag.tip.hidden, false);
  assert.equal(pag.tip.textContent, "A");
  pag.disparar("pointerdown", { pointerType: "touch", target: b });
  assert.equal(pag.tip.hidden, false);
  assert.equal(pag.tip.textContent, "B");
  pag.disparar("pointerdown", { pointerType: "touch", target: b });
  assert.equal(pag.tip.hidden, true, "segundo toque no mesmo alvo fecha");
  pag.disparar("pointerdown", { pointerType: "touch", target: a });
  assert.equal(pag.tip.textContent, "A");
  pag.disparar("focusout", {});
  assert.equal(pag.tip.hidden, false, "a perda de foco de outro elemento não fecha o tip aberto pelo toque");
  pag.disparar("pointerdown", { pointerType: "touch", target: FORA });
  assert.equal(pag.tip.hidden, true);
});

test("tooltip: Esc fecha, e Esc sem tooltip aberto não faz nada", () => {
  const pag = iniciarPagina(), a = marca("A");
  pag.disparar("keydown", { key: "Escape" });
  assert.equal(pag.tip.hidden, true);
  pag.disparar("pointerdown", { pointerType: "touch", target: a });
  pag.disparar("keydown", { key: "Enter" });
  assert.equal(pag.tip.hidden, false);
  pag.disparar("keydown", { key: "Escape" });
  assert.equal(pag.tip.hidden, true);
});

test("tooltip: foco no link de um ponto liga aria-describedby só no link; blur fecha e remove", () => {
  const pag = iniciarPagina(), ponto = marca("Ana: 3 projetos, 1 leis com efeito");
  const link = no({ tagName: "a", closest: () => null, querySelector: (sel) => (sel === "[data-tip]" ? ponto : null) });
  pag.disparar("focusin", { target: link });
  assert.equal(pag.tip.hidden, false);
  assert.equal(pag.tip.textContent, "Ana: 3 projetos, 1 leis com efeito");
  assert.equal(link.getAttribute("aria-describedby"), "tip");
  assert.equal(ponto.getAttribute("aria-describedby"), null);
  assert.equal(ponto.getAttribute("tabindex"), null);
  pag.disparar("focusout", { target: link });
  assert.equal(pag.tip.hidden, true);
  assert.equal(link.getAttribute("aria-describedby"), null);
  // Um painel com tabindex não abre o tip da primeira marca que contém.
  const painel = no({ tagName: "SECTION", closest: () => null, querySelector: () => ponto });
  pag.disparar("focusin", { target: painel });
  assert.equal(pag.tip.hidden, true);
  assert.equal(painel.getAttribute("aria-describedby"), null);
});

test("tooltip: alvo removido da página não deixa o tip órfão", () => {
  const pag = iniciarPagina(), a = marca("A");
  pag.disparar("pointerdown", { pointerType: "touch", target: a });
  a.isConnected = false;
  pag.disparar("pointermove", { pointerType: "mouse", target: FORA });
  assert.equal(pag.tip.hidden, true);
  const b = marca("B");
  pag.disparar("pointerdown", { pointerType: "touch", target: b });
  b.isConnected = false;
  pag.disparar("focusout", {});
  assert.equal(pag.tip.hidden, true);
});

// ------------------------------------------------------------------ abas
function estado(pag) {
  return pag.botoes.map((b) => [b.getAttribute("aria-selected"), b.getAttribute("tabindex"), pag.elementos[b.getAttribute("aria-controls")].hidden]);
}

test("abas: o JS revela a lista, oculta os painéis inativos e mantém o tabindex móvel", () => {
  const pag = iniciarPagina({ abas: [{ id: "2025-2028", sel: true }, { id: "2021-2024" }] });
  assert.equal(pag.listaAbas.hidden, false);
  assert.deepEqual(estado(pag), [["true", "0", false], ["false", "-1", true]]);
  assert.equal(pag.focado(), null, "a abertura não move o foco");
  pag.botoes.forEach((bt) => {
    const painel = pag.elementos[bt.getAttribute("aria-controls")];
    assert.equal(painel.getAttribute("role"), "tabpanel");
    assert.equal(painel.getAttribute("tabindex"), "0");
    assert.equal(painel.getAttribute("aria-labelledby"), bt.id);
  });
  pag.botoes[1].eventos.click();
  assert.deepEqual(estado(pag), [["false", "-1", true], ["true", "0", false]]);
});

test("abas: sem API de painel preserva a lista oculta e todas as seções visíveis", () => {
  const pag = iniciarPagina({ abas: [{ id: "atual", sel: true }, { id: "anterior" }], semApiPainel: true });
  assert.equal(pag.listaAbas.hidden, true);
  pag.botoes.forEach((bt) => {
    const painel = pag.elementos[bt.getAttribute("aria-controls")];
    assert.equal(painel.hidden, false);
    assert.equal(painel.getAttribute("role"), null);
    assert.equal(painel.getAttribute("tabindex"), null);
  });
});

test("abas: setas com volta nas pontas, Home e End movem seleção, foco e painel", () => {
  const pag = iniciarPagina({ abas: [{ id: "c", sel: true }, { id: "b" }, { id: "a" }] });
  const [c, b, a] = pag.botoes;
  assert.equal(pag.tecla(c, "ArrowLeft"), true);
  assert.equal(pag.focado(), a, "da primeira, a seta para a esquerda volta para a última");
  assert.deepEqual(estado(pag), [["false", "-1", true], ["false", "-1", true], ["true", "0", false]]);
  pag.tecla(a, "ArrowRight");
  assert.equal(pag.focado(), c, "da última, a seta para a direita volta para a primeira");
  pag.tecla(c, "ArrowRight");
  assert.equal(pag.focado(), b);
  assert.deepEqual(estado(pag), [["false", "-1", true], ["true", "0", false], ["false", "-1", true]]);
  pag.tecla(b, "End");
  assert.equal(pag.focado(), a);
  pag.tecla(a, "Home");
  assert.equal(pag.focado(), c);
  assert.deepEqual(estado(pag), [["true", "0", false], ["false", "-1", true], ["false", "-1", true]]);
  assert.equal(pag.tecla(c, "Enter"), false, "outras teclas seguem o comportamento padrão");
  assert.deepEqual(estado(pag), [["true", "0", false], ["false", "-1", true], ["false", "-1", true]]);
});

test("abas: com uma só aba, as setas mantêm a seleção e o painel", () => {
  const pag = iniciarPagina({ abas: [{ id: "2025-2028", sel: true }] });
  const [unica] = pag.botoes;
  for (const tecla of ["ArrowRight", "ArrowLeft", "Home", "End"]) {
    pag.tecla(unica, tecla);
    assert.equal(pag.focado(), unica);
    assert.deepEqual(estado(pag), [["true", "0", false]]);
  }
});

// ------------------------------------------------------------- listas de PLs
const COLUNAS_PL = ["id", "ord", "n", "a", "d", "e", "r", "pb", "t", "h", "c", "i", "l", "ld", "lt", "vp", "dl", "o", "lg", "pr", "au", "al", "pol", "s", "rp", "ls"];

// Como conjuntoPL de carregamento.test.js: n projetos, um terço deles leis.
function conjuntoPL(n, ajustar = () => {}) {
  const vazia = (nome) => ({ esquema: 2, nome, n: 0, colunas: Object.fromEntries(COLUNAS_PL.map((k) => [k, []])) });
  const grupos = { lei: vazia("pl-lei"), andamento: vazia("pl-andamento"), sem_exito: vazia("pl-sem_exito") };
  const desfecho = { lei: 2, andamento: 0, sem_exito: 1 };
  for (let j = 0; j < n; j++) {
    const g = ["lei", "andamento", "sem_exito"][j % 3];
    const data = new Date(Date.UTC(2026, 9, 21 - j)).toISOString().slice(0, 10);
    const linha = {
      id: 400000 + j, ord: j, n: (n - j) + "/2026", a: 2026, d: data, e: "Ementa do projeto " + j, r: "Resumo " + j, pb: "moradores",
      t: 2, h: desfecho[g], c: 1, i: j % 4, l: g === "lei" ? 5000 + j : null, ld: g === "lei" ? data : null, dl: g === "lei" ? 10 : null,
      lt: g === "lei" ? "sancionada" : null, vp: 0, o: 3, lg: 1, pr: 3, au: [3], al: [], pol: 0, s: [], rp: null, ls: null
    };
    ajustar(linha, j);
    grupos[g].n += 1;
    COLUNAS_PL.forEach((k) => grupos[g].colunas[k].push(linha[k]));
  }
  return { dic: copiar(fixture.dic), fatias: [grupos.lei, grupos.andamento, grupos.sem_exito] };
}

function manifestoPara(build, conjunto) {
  const arquivos = {};
  [conjunto.dic, ...conjunto.fatias].forEach((dados) => {
    const nome = dados.nome || "dic-pl";
    arquivos[nome] = { url: "dados/" + nome + ".json?v=" + build, n: dados.n, bytes: 1 };
  });
  return { esquema: 2, build, inicial: ["dic-pl", "pl-lei"], arquivos };
}

// leis.html com o script real; resultados conta os <li class="…"> como filhos, com focus() registrado.
function iniciarLista({ conjunto, query = "" }) {
  const elementos = {}, focados = [];
  function elemento(valor = "") {
    return { value: valor, checked: false, hidden: false, disabled: false, dataset: {}, innerHTML: "", textContent: "", eventos: {},
      addEventListener(tipo, fn) { this.eventos[tipo] = fn; },
      setAttribute(nome, v) { this[nome] = v; },
      insertAdjacentHTML(_, texto) { this.innerHTML += texto; } };
  }
  ["conteudo", "q", "f-ordem", "f-origem", "f-autor", "f-partido", "f-tema", "f-leg", "f-ano", "f-coautor", "resultados",
    "resumo-filtro", "anuncio", "mais", "csv", "limpar", "manifesto-dados"].forEach((id) => { elementos[id] = elemento(); });
  elementos["f-ordem"].value = "recente";
  const build = "interacoes";
  elementos["manifesto-dados"].textContent = JSON.stringify(manifestoPara(build, conjunto));
  const resultados = elementos.resultados;
  let html = "", filhos = [];
  const acrescentar = (texto) => (texto.match(/<li class="/g) || []).forEach(() => {
    filhos.push({ atributos: {}, setAttribute(k, v) { this.atributos[k] = String(v); }, focus() { focados.push(this); } });
  });
  Object.defineProperty(resultados, "innerHTML", { get: () => html, set: (v) => { html = v; filhos = []; acrescentar(v); } });
  Object.defineProperty(resultados, "children", { get: () => filhos });
  resultados.insertAdjacentHTML = (_, texto) => { html += texto; acrescentar(texto); };
  const form = elemento();
  form.dataset.modo = "leis";
  form.querySelectorAll = () => [];
  form.querySelector = () => ({ open: true });
  form.reset = () => {};
  const documento = {
    readyState: "complete",
    getElementById: (id) => elementos[id] || null,
    querySelectorAll: () => [],
    querySelector: (sel) => (sel === "form.filtros" ? form : null),
    createElement: () => ({ click() {} })
  };
  const contexto = {
    document: documento,
    window: { RadarDados, matchMedia: () => ({ matches: false }), addEventListener() {} },
    location: { pathname: "leis.html", search: query }, history: { replaceState() {} },
    URLSearchParams, Blob, URL: { createObjectURL: () => "blob:csv" }, setTimeout, clearTimeout,
    fetch: async (url) => {
      const nome = url.split("/").pop().split(".json")[0];
      const dados = nome === "dic-pl" ? conjunto.dic : conjunto.fatias.find((f) => f.nome === nome);
      if (!dados) return { status: 404, ok: false };
      return { status: 200, ok: true, json: async () => ({ ...copiar(dados), build }) };
    }
  };
  vm.runInNewContext(fonte, contexto, { filename: "app.js" });
  return { elementos, resultados, focados, filhos: () => filhos, mais: elementos.mais, anuncio: elementos.anuncio };
}

test("Mostrar mais que esgota a lista põe o foco no primeiro item novo e anuncia quantos entraram", async () => {
  const app = iniciarLista({ conjunto: conjuntoPL(150) });
  await assentar();
  assert.equal(app.filhos().length, 40);
  assert.equal(app.mais.hidden, false);
  assert.equal(app.focados.length, 0, "a primeira pintura não move o foco");
  assert.equal(app.anuncio.textContent, "");
  app.mais.eventos.click();
  assert.equal(app.filhos().length, 50);
  assert.equal(app.mais.hidden, true, "a lista acabou e o botão some");
  assert.deepEqual(app.focados, [app.filhos()[40]], "o foco não se perde com o botão oculto");
  assert.equal(app.filhos()[40].atributos.tabindex, "-1");
  assert.equal(app.anuncio.textContent, "10 itens adicionados.");
});

test("Mostrar mais numa lista vazia não move o foco", async () => {
  const app = iniciarLista({ conjunto: conjuntoPL(150), query: "?q=nenhum-projeto-assim" });
  await assentar();
  assert.match(app.resultados.innerHTML, /<li class="vazio">/);
  assert.equal(app.mais.hidden, true);
  app.mais.eventos.click();
  assert.equal(app.focados.length, 0);
  assert.equal(app.anuncio.textContent, "");
});

// ---------------------------------------------------------------- coautores
function conjuntoCoautores(nomes) {
  const base = fixture.dic.pessoas.length;
  const conjunto = conjuntoPL(3, (linha, j) => {
    if (j === 0) linha.au = [3, ...nomes.map((_, i) => base + i)];
  });
  nomes.forEach((nome, i) => conjunto.dic.pessoas.push(["pessoa-extra-" + i, nome, {}]));
  conjunto.dic.n = conjunto.dic.pessoas.length;
  return conjunto;
}

test("coautores: 1 e 30 nomes num <details> dentro de div.autoria, sem title", async () => {
  const um = iniciarLista({ conjunto: conjuntoCoautores(["Cal"]) });
  await assentar();
  // Mesmo literal de lista_coautores em tests/test_acessibilidade_html.py.
  assert.ok(um.resultados.innerHTML.includes('<details class="coautores"><summary>e 1 coautor</summary><ul><li>Cal</li></ul></details>'));
  // O partido do principal (quando conhecido) fica dentro do chip, antes de fechar o link; nada solto antes do <details>.
  assert.match(um.resultados.innerHTML, /<div class="autoria"><a class="chip chip-principal"[^>]*>[^<]*(?:<span class="partido">[^<]+<\/span>)?<\/a><details class="coautores">/);
  assert.doesNotMatch(um.resultados.innerHTML, /<p class="autoria">|title="Cal"/);
  const nomes = Array.from({ length: 30 }, (_, i) => "Pessoa " + i);
  const trinta = iniciarLista({ conjunto: conjuntoCoautores(nomes) });
  await assentar();
  const html = trinta.resultados.innerHTML;
  assert.ok(html.includes("<summary>e 30 coautores</summary><ul><li>Pessoa 0</li>"));
  assert.equal((html.match(/<li>Pessoa \d+<\/li>/g) || []).length, 30);
  assert.doesNotMatch(html, /<p[^>]*>(?:(?!<\/p>)[^])*<details/, "nenhum <details> dentro de <p>");
});
