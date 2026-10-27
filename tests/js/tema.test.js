"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

// Conferido byte a byte por test_cabecalho.py; executa o mesmo código anterior ao CSS.
const SCRIPT_CABECA = '(function(d,r){if(window.matchMedia&&d.addEventListener)r.classList.add("js");try{var t=localStorage.getItem("radar-tema");if(t==="claro"||t==="escuro")r.dataset.theme=t==="escuro"?"dark":"light"}catch(e){}})(document,document.documentElement)';
const fonte = fs.readFileSync(path.join(__dirname, "../../site_src/navegacao.js"), "utf8");

function elemento(atributos = {}) {
  return {
    atributos: { ...atributos }, ouvintes: {},
    getAttribute(nome) { return Object.hasOwn(this.atributos, nome) ? this.atributos[nome] : null; },
    setAttribute(nome, valor) { this.atributos[nome] = String(valor); },
    removeAttribute(nome) { delete this.atributos[nome]; },
    addEventListener(tipo, fn) {
      assert.equal(this.ouvintes[tipo], undefined, `ouvinte duplicado: ${tipo}`);
      this.ouvintes[tipo] = fn;
    }
  };
}

function montar({ salvo = null, falha = false, executar = true, legado = false, semMidia = false } = {}) {
  const botoes = ["auto", "claro", "escuro"].map((tema) => elemento({
    "data-tema": tema, "aria-pressed": tema === "auto" ? "true" : "false"
  }));
  const grupo = elemento({ hidden: "" });
  grupo.querySelectorAll = () => botoes;
  const metas = ["light", "dark"].map((tema) => elemento({ media: `(prefers-color-scheme: ${tema})` }));
  const raiz = { dataset: {}, classList: {
    add(classe) { raiz.classe = classe; },
    remove(classe) { raiz.removida = classe; }
  } };
  const documento = {
    documentElement: raiz,
    addEventListener() {},
    querySelector: (seletor) => seletor === ".tema" ? grupo : null,
    querySelectorAll: () => metas
  };
  const gravados = [];
  const storage = {
    getItem(chave) { assert.equal(chave, "radar-tema"); if (falha) throw Error("bloqueado"); return salvo; },
    setItem(chave, valor) { if (falha) throw Error("bloqueado"); gravados.push([chave, valor]); }
  };
  const midia = { matches: false, ouvintes: [] };
  if (legado) midia.addListener = (fn) => midia.ouvintes.push(fn);
  else midia.addEventListener = (tipo, fn) => { assert.equal(tipo, "change"); midia.ouvintes.push(fn); };
  const janela = { localStorage: storage };
  if (!semMidia) janela.matchMedia = (consulta) => {
    assert.equal(consulta, "(prefers-color-scheme: dark)"); return midia;
  };
  const contexto = { document: documento, window: janela, localStorage: storage };
  if (executar) {
    vm.runInNewContext(SCRIPT_CABECA, contexto);
    vm.runInNewContext(fonte, contexto);
  }
  return {
    raiz, grupo, botoes, metas, gravados,
    clicar(tema) { grupo.ouvintes.click({ target: botoes.find((b) => b.getAttribute("data-tema") === tema) }); },
    mudarSistema(escuro) { midia.matches = escuro; for (const fn of midia.ouvintes) fn({ matches: escuro }); }
  };
}

function conferir(p, tema, atributo) {
  assert.equal(p.raiz.dataset.theme, atributo);
  assert.deepEqual(p.botoes.map((b) => b.getAttribute("aria-pressed")),
    ["auto", "claro", "escuro"].map((t) => String(t === tema)));
}

test("sem executar JS o controle permanece hidden, inclusive no template", () => {
  const p = montar({ executar: false });
  assert.equal(p.grupo.getAttribute("hidden"), "");
  const template = fs.readFileSync(path.join(__dirname, "../../coletor/site/paginas.py"), "utf8");
  assert.match(template, /<div class="tema" role="group" aria-label="Tema" hidden>/);
});

test("o script do head marca js com matchMedia e eventos, aceita apenas claro ou escuro e cabe em 400 bytes", () => {
  assert.ok(Buffer.byteLength(SCRIPT_CABECA) <= 400);
  const capaz = { window: { matchMedia() {} } };
  for (const [salvo, esperado] of [["claro", "light"], ["escuro", "dark"], ["auto", undefined], ["azul", undefined]]) {
    const raiz = { dataset: {}, classList: { add: (classe) => assert.equal(classe, "js") } };
    vm.runInNewContext(SCRIPT_CABECA, { ...capaz, document: { documentElement: raiz, addEventListener() {} },
      localStorage: { getItem: () => salvo } });
    assert.equal(raiz.dataset.theme, esperado);
  }
  let marcou = false;
  assert.doesNotThrow(() => vm.runInNewContext(SCRIPT_CABECA, {
    ...capaz,
    document: { documentElement: { classList: { add() { marcou = true; } } }, addEventListener() {} },
    get localStorage() { throw Error("indisponível"); }
  }));
  assert.equal(marcou, true);
  // Sem matchMedia ou sem addEventListener, o menu não recolhe (sem js), mas o tema salvo ainda vale.
  for (const contexto of [{ window: {}, comEventos: true }, { ...capaz, comEventos: false }]) {
    const raiz = { dataset: {}, classList: { add: () => assert.fail("não deveria marcar js") } };
    const documento = { documentElement: raiz };
    if (contexto.comEventos) documento.addEventListener = () => {};
    vm.runInNewContext(SCRIPT_CABECA, { window: contexto.window, document: documento, localStorage: { getItem: () => "escuro" } });
    assert.equal(raiz.dataset.theme, "dark");
  }
});

test("navegacao.js tira a classe js quando a página não tem o menu", () => {
  const p = montar({ salvo: "claro" });
  assert.equal(p.raiz.classe, "js");
  assert.equal(p.raiz.removida, "js");
});

test("valor inválido vira automático e as três escolhas persistem e atualizam aria-pressed", () => {
  const p = montar({ salvo: "azul" });
  assert.equal(p.grupo.getAttribute("hidden"), null);
  conferir(p, "auto", undefined);
  for (const [tema, atributo] of [["claro", "light"], ["escuro", "dark"], ["auto", undefined]]) {
    p.clicar(tema);
    conferir(p, tema, atributo);
  }
  assert.deepEqual(p.gravados, [["radar-tema", "claro"], ["radar-tema", "escuro"], ["radar-tema", "auto"]]);
});

test("storage que lança em getItem e setItem não impede escolhas durante a sessão", () => {
  let p;
  assert.doesNotThrow(() => { p = montar({ falha: true }); });
  assert.equal(p.raiz.classe, "js");
  assert.equal(p.grupo.getAttribute("hidden"), null);
  for (const [tema, atributo] of [["escuro", "dark"], ["claro", "light"], ["auto", undefined]]) {
    assert.doesNotThrow(() => p.clicar(tema));
    conferir(p, tema, atributo);
  }
});

test("preferência salva inicializa o controle e as metas acompanham a escolha explícita", () => {
  for (const [salvo, atributo] of [["claro", "light"], ["escuro", "dark"]]) {
    const p = montar({ salvo });
    conferir(p, salvo, atributo);
    assert.deepEqual(p.metas.map((m) => m.getAttribute("media")), salvo === "escuro" ? ["not all", "all"] : ["all", "not all"]);
    p.mudarSistema(true);
    conferir(p, salvo, atributo);
    p.clicar("auto");
    assert.deepEqual(p.metas.map((m) => m.getAttribute("media")), ["(prefers-color-scheme: light)", "(prefers-color-scheme: dark)"]);
  }
});

test("mudanças do sistema no modo automático nunca gravam data-theme", () => {
  for (const legado of [false, true]) {
    const p = montar({ legado });
    for (const escuro of [true, false, true]) {
      p.mudarSistema(escuro);
      conferir(p, "auto", undefined);
      assert.equal(Object.hasOwn(p.raiz.dataset, "theme"), false);
    }
    assert.deepEqual(p.gravados, []);
  }
});

test("sem matchMedia o controle ainda permite escolhas explícitas", () => {
  const p = montar({ semMidia: true });
  p.clicar("escuro");
  conferir(p, "escuro", "dark");
});
