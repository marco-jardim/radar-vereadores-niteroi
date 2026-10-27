"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const zlib = require("node:zlib");

const ARQUIVO = path.join(__dirname, "../../site_src/inicio.js");
const fonte = fs.readFileSync(ARQUIVO, "utf8");
const I = require(ARQUIVO);

// ---- DOM mínimo: árvore com texto, seletores simples (tag, #id, .classe, [atributo], descendente, vírgula)
// e eventos que sobem pela árvore.

function texto(t) { return { texto: String(t), parentNode: null }; }

function parteSimples(s) {
  const r = { tag: null, id: null, classes: [], attrs: [] };
  const re = /([a-z0-9-]+)|#([\w-]+)|\.([\w-]+)|\[([\w-]+)(?:="([^"]*)")?\]/gi;
  let m;
  while ((m = re.exec(s))) {
    if (m[1]) r.tag = m[1].toLowerCase();
    else if (m[2]) r.id = m[2];
    else if (m[3]) r.classes.push(m[3]);
    else r.attrs.push([m[4], m[5]]);
  }
  return r;
}

function casa(el, p) {
  const cls = (el.getAttribute("class") || "").split(" ");
  return (!p.tag || el.tag === p.tag) && (!p.id || el.getAttribute("id") === p.id) &&
    p.classes.every((c) => cls.includes(c)) &&
    p.attrs.every(([a, v]) => el.hasAttribute(a) && (v === undefined || el.getAttribute(a) === v));
}

function corresponde(el, seletor) {
  return seletor.split(",").some((alt) => {
    const partes = alt.trim().split(/\s+/).map(parteSimples);
    if (!casa(el, partes[partes.length - 1])) return false;
    let i = partes.length - 2;
    for (let no = el.parentNode; no && i >= 0; no = no.parentNode) if (no.atributos && casa(no, partes[i])) i--;
    return i < 0;
  });
}

class No {
  constructor(tag, atributos = {}, filhos = []) {
    this.tag = tag;
    this.atributos = Object.assign({}, atributos);
    this.childNodes = [];
    this.parentNode = null;
    this.ouvintes = {};
    this.classList = {
      add: (nome) => this.setAttribute("class", [...new Set((this.getAttribute("class") || "").split(/\s+/).filter(Boolean).concat(nome))].join(" "))
    };
    if (tag === "input") this.value = "";
    for (const f of filhos) this.appendChild(typeof f === "string" ? texto(f) : f);
  }
  setAttribute(nome, valor) { this.atributos[nome] = String(valor); }
  getAttribute(nome) { return Object.prototype.hasOwnProperty.call(this.atributos, nome) ? this.atributos[nome] : null; }
  hasAttribute(nome) { return Object.prototype.hasOwnProperty.call(this.atributos, nome); }
  removeAttribute(nome) { delete this.atributos[nome]; }
  addEventListener(tipo, fn) { (this.ouvintes[tipo] = this.ouvintes[tipo] || []).push(fn); }
  get textContent() { return this.childNodes.map((n) => (n.tag ? n.textContent : n.texto)).join(""); }
  set textContent(v) {
    for (const n of this.childNodes) n.parentNode = null;
    this.childNodes = [];
    if (String(v) !== "") this.appendChild(texto(v));
  }
  get childElementCount() { return this.childNodes.filter((n) => n.tag).length; }
  get filhos() { return this.childNodes.filter((n) => n.tag); }
  appendChild(n) { return this.insertBefore(n, null); }
  insertBefore(n, ref) {
    if (n.parentNode) n.parentNode.childNodes.splice(n.parentNode.childNodes.indexOf(n), 1);
    const i = ref ? this.childNodes.indexOf(ref) : -1;
    n.parentNode = this;
    this.childNodes.splice(i < 0 ? this.childNodes.length : i, 0, n);
    return n;
  }
  elementos() { return this.filhos.flatMap((f) => [f, ...f.elementos()]); }
  querySelectorAll(s) { return this.elementos().filter((el) => corresponde(el, s)); }
  querySelector(s) { return this.querySelectorAll(s)[0] || null; }
}

function documento() {
  const doc = new No("#document");
  doc.visibilityState = "visible";
  doc.createElement = (tag) => new No(tag);
  doc.getElementById = (id) => doc.elementos().find((el) => el.getAttribute("id") === id) || null;
  doc.tipos = [];
  const adicionar = doc.addEventListener;
  doc.addEventListener = function (tipo, fn) { doc.tipos.push(tipo); adicionar.call(this, tipo, fn); };
  return doc;
}

function disparar(alvo, tipo, extra) {
  const evento = Object.assign({ type: tipo, target: alvo, defaultPrevented: false,
    preventDefault() { this.defaultPrevented = true; } }, extra);
  for (let no = alvo; no; no = no.parentNode) for (const fn of (no.ouvintes && no.ouvintes[tipo]) || []) fn(evento);
  return evento;
}

// Relógio do visitante em UTC+9: getHours() não serve; só o instante (epoch) importa.
function relogio(estado) {
  return class extends Date {
    constructor(...a) { super(...(a.length ? a : [estado.ms])); }
    static now() { return estado.ms; }
    getHours() { return (this.getUTCHours() + 9) % 24; }
  };
}

// Instante UTC de uma hora de São Paulo (UTC−3) em 26/10/2026.
const sp = (h, m) => Date.UTC(2026, 9, 26, h + 3, m);
const CASOS = [[0, 0, "madrugada"], [5, 59, "madrugada"], [6, 0, "manha"], [17, 59, "por-do-sol"],
  [18, 0, "por-do-sol"], [23, 59, "noite"]];

const VEREADORES = [["JOÃO DA SILVA", "PSOL", "vereadores/joao-da-silva.html"], ["Maria José", "PT", "vereadores/maria-jose.html"],
  ["João Pedro", "PL", "vereadores/joao-pedro.html"], ["Ana Lúcia", "PDT", "vereadores/ana-lucia.html", "suplente em exercício"]];
const VALORES = ["12", "58%", "86,5%", "35 de 132", "—", "0", "1.234"];

// Campo do combobox como CAMPO_BUSCA de coletor/site/inicio.py: o servidor já o emite.
function campoServidor() {
  return new No("div", { class: "cb-campo" }, [
    new No("label", { for: "cb-vereadores", id: "cb-vereadores-rotulo" }, ["Digite o nome do vereador"]),
    new No("input", { id: "cb-vereadores", type: "text", role: "combobox", "aria-autocomplete": "list", "aria-expanded": "false",
      "aria-controls": "cb-vereadores-lista", autocomplete: "off" }),
    new No("ul", { role: "listbox", id: "cb-vereadores-lista", "aria-labelledby": "cb-vereadores-rotulo", hidden: "" }),
    new No("p", { class: "so-leitor", "aria-live": "polite", id: "cb-vereadores-status" })]);
}

// Página inicial com céu, números e "Quem é meu vereador?", como gerar_index e P.tile.
function montar({ ceu = true, valores = VALORES, busca = true, campo = true, janela = {}, contexto = {}, visibilidade = "visible", preparar } = {}) {
  const doc = documento();
  doc.visibilityState = visibilidade;
  const main = new No("main");
  const ceuEl = new No("div", { class: "ceu", "data-ceu": "tarde", "aria-hidden": "true" });
  if (ceu) main.appendChild(new No("section", { class: "hero" }, [ceuEl]));
  const tiles = valores.map((v) => new No("p", { class: "tile-valor" }, [v]));
  main.appendChild(new No("div", { class: "tiles" }, tiles.map((p) => new No("div", { class: "tile" }, [p]))));
  let detalhes = null, campoEl = null;
  if (busca) {
    const ul = new No("ul", { id: "lista-vereadores" }, VEREADORES.map(([nome, partido, href, status]) =>
      new No("li", {}, [new No("a", { href }, [nome]), " ", new No("span", { class: "partido" }, [partido]),
        ...(status ? [" ", new No("span", { class: "status" }, [status])] : [])])));
    detalhes = new No("details", { class: "lista-vereadores", open: "" }, [new No("summary", {}, ["Ver todos"]), ul]);
    campoEl = campo ? campoServidor() : null;
    main.appendChild(new No("section", { class: "quem-vereador", "data-combobox": "", "aria-labelledby": "t-quem" },
      [new No("h2", { id: "t-quem" }, ["Quem é meu vereador?"]), ...(campoEl ? [campoEl] : []), detalhes]));
  }
  doc.appendChild(main);
  if (preparar) preparar(doc);
  vm.runInNewContext(fonte, Object.assign({ document: doc, window: janela }, contexto), { filename: "inicio.js" });
  return { doc, ceu: ceuEl, tiles, detalhes, campo: campoEl, janela };
}

// ---- céu

test("tabela de fases nos limites, pela hora de São Paulo", () => {
  assert.deepEqual([0, 5, 6, 11, 12, 16, 17, 18, 19, 23].map(I.fase),
    ["madrugada", "madrugada", "manha", "manha", "tarde", "tarde", "por-do-sol", "por-do-sol", "noite", "noite"]);
  for (const [h, m, esperado] of CASOS) {
    assert.equal(I.faseAgora(sp(h, m), Intl), esperado, `${h}:${m} com Intl`);
    // Intl que lança, sem fuso ou ausente: UTC−3 pelo getUTCHours.
    assert.equal(I.faseAgora(sp(h, m), { DateTimeFormat() { throw new RangeError("fuso"); } }), esperado);
    assert.equal(I.faseAgora(sp(h, m), null), esperado);
  }
});

test("data-ceu segue São Paulo com o relógio do visitante em UTC+9, com e sem Intl", () => {
  for (const [h, m, esperado] of CASOS) {
    const Data = relogio({ ms: sp(h, m) });
    assert.equal(new Data().getHours(), (h + 12) % 24);
    assert.equal(montar({ contexto: { Date: Data } }).ceu.getAttribute("data-ceu"), esperado);
    const quebrado = { DateTimeFormat() { throw new TypeError("sem Intl"); } };
    assert.equal(montar({ contexto: { Date: Data, Intl: quebrado } }).ceu.getAttribute("data-ceu"), esperado);
  }
});

test("reavalia a cada 10 min só com a página visível, com um ouvinte de visibilitychange", () => {
  const estado = { ms: sp(16, 55) }, chamadas = [];
  const janela = {
    setInterval(fn, ms) { chamadas.push(["set", ms]); janela.tique = fn; return 7; },
    clearInterval(id) { chamadas.push(["clear", id]); }
  };
  const p = montar({ janela, contexto: { Date: relogio(estado) }, valores: [], busca: false });
  assert.equal(p.ceu.getAttribute("data-ceu"), "tarde");
  assert.deepEqual(chamadas, [["set", 600000]]);
  assert.deepEqual(p.doc.tipos, ["visibilitychange"]);
  estado.ms = sp(17, 5);
  janela.tique();
  assert.equal(p.ceu.getAttribute("data-ceu"), "por-do-sol");
  p.doc.visibilityState = "hidden";
  disparar(p.doc, "visibilitychange");
  assert.deepEqual(chamadas.at(-1), ["clear", 7]);
  estado.ms = sp(19, 30);
  p.doc.visibilityState = "visible";
  disparar(p.doc, "visibilitychange");
  assert.equal(p.ceu.getAttribute("data-ceu"), "noite");
  assert.deepEqual(chamadas.at(-1), ["set", 600000]);
  // Carregada em segundo plano: atualiza uma vez, sem relógio até ficar visível.
  const oculta = [];
  montar({ visibilidade: "hidden", janela: { setInterval() { oculta.push(1); } }, valores: [], busca: false });
  assert.deepEqual(oculta, []);
});

// ---- números

test("lê números pt-BR preservando prefixo e sufixo; traço e zero não animam", () => {
  const n = (t) => { const r = I.analisarNumero(t); return r && [r.prefixo, r.valor, r.sufixo]; };
  assert.deepEqual(n("1.234"), ["", 1234, ""]);
  assert.deepEqual(n("58%"), ["", 58, "%"]);
  assert.deepEqual(n("86,5%"), ["", 86.5, "%"]);
  assert.deepEqual(n("35 de 132"), ["", 35, " de 132"]);
  assert.deepEqual(n("R$ 1.200"), ["R$ ", 1200, ""]);
  assert.deepEqual(n("84 dias"), ["", 84, " dias"]);
  assert.equal(I.analisarNumero("—"), null);
  assert.equal(I.analisarNumero("0"), null);
  assert.equal(I.analisarNumero(""), null);
  assert.equal(I.analisarNumero(null), null);
  for (const t of ["1.234", "58%", "86,5%", "35 de 132", "R$ 1.200", "1.234.567", "84 dias"]) {
    const info = I.analisarNumero(t);
    assert.equal(I.formatar(info, info.valor), t);
  }
  assert.equal(I.formatar(I.analisarNumero("86,5%"), 0), "0,0%");
  assert.equal(I.formatar(I.analisarNumero("1.234"), 999), "999");
});

function janelaAnimada({ reduzir = false } = {}) {
  const quadros = [], observadores = [];
  class Observador {
    constructor(fn, opcoes) { this.fn = fn; this.opcoes = opcoes; this.alvos = []; observadores.push(this); }
    observe(el) { this.alvos.push(el); }
    unobserve(el) { this.alvos = this.alvos.filter((a) => a !== el); }
  }
  return {
    quadros, observadores, IntersectionObserver: Observador,
    requestAnimationFrame(fn) { quadros.push(fn); return quadros.length; },
    matchMedia(q) { return { media: q, matches: reduzir && q === "(prefers-reduced-motion: reduce)" }; }
  };
}

function rodarQuadro(janela, t) {
  const fila = janela.quadros.splice(0);
  for (const fn of fila) fn(t);
}

test("anima ao entrar na tela e termina com o texto idêntico ao do servidor", () => {
  const janela = janelaAnimada();
  const p = montar({ janela });
  assert.equal(janela.observadores.length, 1);
  const obs = janela.observadores[0];
  assert.equal(obs.opcoes.threshold, 0.4);
  const animaveis = p.tiles.filter((t) => !["—", "0"].includes(t.textContent));
  assert.deepEqual(obs.alvos, animaveis);
  // Antes de entrar na tela, nada muda.
  assert.deepEqual(p.tiles.map((t) => t.textContent), VALORES);
  obs.fn(obs.alvos.map((target) => ({ target, isIntersecting: true, intersectionRatio: 0.5 })));
  assert.deepEqual(obs.alvos, []);
  for (const el of animaveis) {
    const [leitor, visual] = el.filhos;
    assert.equal(leitor.getAttribute("class"), "so-leitor");
    assert.equal(visual.getAttribute("aria-hidden"), "true");
    assert.equal(leitor.textContent, VALORES[p.tiles.indexOf(el)]);
  }
  rodarQuadro(janela, 1000);
  rodarQuadro(janela, 1600);
  const meio = p.tiles[6].filhos[1].textContent;
  assert.match(meio, /^\d{1,3}(\.\d{3})?$/);
  assert.notEqual(meio, "1.234");
  rodarQuadro(janela, 1000 + I.DURACAO);
  assert.equal(janela.quadros.length, 0);
  assert.deepEqual(p.tiles.map((t) => t.textContent), VALORES);
  for (const el of p.tiles) {
    assert.equal(el.childElementCount, 0);
    assert.equal(el.childNodes.length, VALORES[p.tiles.indexOf(el)] === "" ? 0 : 1);
  }
});

test("sem animação com movimento reduzido, sem IntersectionObserver ou sem requestAnimationFrame", () => {
  const reduzida = janelaAnimada({ reduzir: true });
  const p = montar({ janela: reduzida });
  assert.equal(reduzida.observadores.length, 0);
  assert.deepEqual(p.tiles.map((t) => t.textContent), VALORES);
  const semIO = janelaAnimada();
  delete semIO.IntersectionObserver;
  let q;
  assert.doesNotThrow(() => { q = montar({ janela: semIO }); });
  assert.equal(semIO.quadros.length, 0);
  assert.deepEqual(q.tiles.map((t) => t.childElementCount), VALORES.map(() => 0));
  const semRaf = janelaAnimada();
  delete semRaf.requestAnimationFrame;
  montar({ janela: semRaf });
  assert.equal(semRaf.observadores.length, 0);
  const semMidia = janelaAnimada();
  delete semMidia.matchMedia;
  montar({ janela: semMidia });
  assert.equal(semMidia.observadores.length, 0);
});

// ---- busca de vereador

function montarBusca({ campo = true } = {}) {
  const destinos = [];
  const p = montar({ janela: { location: { assign(href) { destinos.push(href); } } }, valores: [], campo });
  const entrada = p.doc.getElementById("cb-vereadores");
  const lista = p.doc.getElementById("cb-vereadores-lista");
  const aviso = p.doc.querySelector("p.so-leitor");
  const digitar = (v) => { entrada.value = v; disparar(entrada, "input"); };
  const tecla = (key) => disparar(entrada, "keydown", { key });
  const visiveis = () => lista.filhos.filter((li) => !li.hasAttribute("hidden")).map((li) => li.getAttribute("id"));
  const ativo = () => entrada.getAttribute("aria-activedescendant");
  const aberta = () => !lista.hasAttribute("hidden") && entrada.getAttribute("aria-expanded") === "true";
  return { ...p, destinos, entrada, lista, aviso, digitar, tecla, visiveis, ativo, aberta };
}

test("reusa o campo do servidor sem inserir nada; a lista original fica no DOM e fechada", () => {
  const b = montarBusca();
  const pai = b.detalhes.parentNode;
  assert.equal(pai.getAttribute("class"), "quem-vereador cb-ativo");
  assert.deepEqual(pai.filhos.map((f) => f.tag), ["h2", "div", "details"]);
  assert.equal(pai.filhos[1], b.campo);
  assert.deepEqual(b.campo.filhos.map((f) => f.tag), ["label", "input", "ul", "p"]);
  assert.equal(b.entrada, b.campo.filhos[1]);
  assert.equal(b.lista, b.campo.filhos[2]);
  assert.equal(b.aviso, b.campo.filhos[3]);
  assert.equal(b.doc.querySelectorAll("#cb-vereadores").length, 1);
  assert.equal(b.detalhes.hasAttribute("open"), false);
  assert.equal(b.doc.querySelectorAll("#lista-vereadores li").length, 4);
  assert.equal(b.lista.hasAttribute("hidden"), true);
  assert.deepEqual(b.lista.filhos.map((li) => [li.getAttribute("role"), li.getAttribute("id"), li.getAttribute("aria-selected")]),
    VEREADORES.map((_, i) => ["option", `cb-op-${i}`, "false"]));
  assert.equal(b.lista.filhos[0].textContent, "JOÃO DA SILVA PSOL");
  assert.equal(b.lista.filhos[0].querySelector(".partido").textContent, "PSOL");
  // Suplente em exercício também aparece na opção.
  assert.equal(b.lista.filhos[3].textContent, "Ana Lúcia PDT suplente em exercício");
  assert.equal(b.lista.filhos[3].querySelector(".status").textContent, "suplente em exercício");
  assert.equal(b.lista.filhos[0].querySelector(".status"), null);
});

test("sem o campo do servidor, cria o mesmo campo antes da lista original", () => {
  const b = montarBusca({ campo: false });
  const pai = b.detalhes.parentNode;
  assert.equal(pai.getAttribute("class"), "quem-vereador cb-ativo");
  assert.deepEqual(pai.filhos.map((f) => f.tag), ["h2", "div", "details"]);
  const campo = pai.filhos[1];
  assert.equal(campo.getAttribute("class"), "cb-campo");
  assert.deepEqual(campo.filhos.map((f) => f.tag), ["label", "input", "ul", "p"]);
  assert.equal(b.detalhes.hasAttribute("open"), false);
  assert.deepEqual(b.entrada.atributos, { type: "text", role: "combobox", "aria-autocomplete": "list",
    "aria-expanded": "false", "aria-controls": "cb-vereadores-lista", id: "cb-vereadores", autocomplete: "off" });
  assert.equal(campo.filhos[0].getAttribute("for"), "cb-vereadores");
  assert.equal(b.lista.getAttribute("role"), "listbox");
  assert.equal(b.lista.hasAttribute("hidden"), true);
  assert.equal(b.aviso.getAttribute("aria-live"), "polite");
  assert.equal(b.aviso.getAttribute("id"), "cb-vereadores-status");
  assert.equal(b.lista.filhos.length, 4);
  b.digitar("maria");
  assert.deepEqual(b.visiveis(), ["cb-op-1"]);
});

test("não ativa duas vezes o mesmo campo", () => {
  const b = montarBusca();
  vm.runInNewContext(fonte, { document: b.doc, window: {} });
  assert.equal(b.lista.filhos.length, 4);
  assert.equal(b.entrada.ouvintes.input.length, 1);
  assert.equal(b.detalhes.parentNode.getAttribute("class"), "quem-vereador cb-ativo");
});

test("campo só é revelado após ligar os eventos; falha preserva a lista alternativa", () => {
  for (const falhar of [
    (doc) => doc.getElementById("cb-vereadores-status").parentNode.childNodes.pop(),
    (doc) => { doc.getElementById("cb-vereadores").addEventListener = null; },
    (doc) => { doc.getElementById("cb-vereadores-lista").addEventListener = () => { throw Error("evento"); }; }
  ]) {
    const p = montar({ preparar: falhar });
    assert.equal(p.detalhes.parentNode.getAttribute("class"), "quem-vereador");
    assert.equal(p.doc.querySelectorAll("#lista-vereadores li").length, VEREADORES.length);
  }
  const css = fs.readFileSync(path.join(__dirname, "../../site_src/inicio.css"), "utf8");
  assert.match(css, /\.quem-vereador:not\(\.cb-ativo\) \.cb-campo\s*\{\s*display:\s*none;/);
});

test("consulta vazia ou só com espaços fica fechada; seta para baixo mostra todos", () => {
  for (const v of ["", "   "]) {
    const b = montarBusca();
    b.digitar(v);
    assert.equal(b.aberta(), false);
    assert.equal(b.aviso.textContent, "");
    b.tecla("ArrowDown");
    assert.equal(b.aberta(), true);
    assert.deepEqual(b.visiveis(), ["cb-op-0", "cb-op-1", "cb-op-2", "cb-op-3"]);
    assert.equal(b.ativo(), "cb-op-0");
    assert.equal(b.aviso.textContent, "4 vereadores encontrados");
  }
});

test("filtro ignora acentos e caixa e anuncia o resultado, inclusive vazio", () => {
  const b = montarBusca();
  for (const q of ["joão", "JOAO", " joao  "]) {
    b.digitar(q);
    assert.equal(b.aberta(), true);
    assert.deepEqual(b.visiveis(), ["cb-op-0", "cb-op-2"]);
    assert.equal(b.aviso.textContent, "2 vereadores encontrados");
  }
  b.digitar("lucia");
  assert.deepEqual(b.visiveis(), ["cb-op-3"]);
  assert.equal(b.aviso.textContent, "1 vereador encontrado");
  b.digitar("xyz");
  assert.equal(b.aberta(), false);
  assert.equal(b.aviso.textContent, "Nenhum vereador encontrado");
  assert.deepEqual(I.filtrar(["JOÃO", "João", "Joana"], "joão"), [0, 1]);
  assert.equal(I.norm("Ação"), "acao");
});

test("setas dão a volta nos limites; Home e End vão às pontas só com uma opção ativa", () => {
  const b = montarBusca();
  b.digitar("jo");
  assert.deepEqual(b.visiveis(), ["cb-op-0", "cb-op-1", "cb-op-2"]);
  assert.equal(b.ativo(), null);
  // Lista aberta sem opção ativa: Home/End movem o cursor do campo.
  assert.equal(b.tecla("Home").defaultPrevented, false);
  assert.equal(b.tecla("End").defaultPrevented, false);
  assert.equal(b.ativo(), null);
  assert.equal(b.aberta(), true);
  b.tecla("ArrowUp");
  assert.equal(b.ativo(), "cb-op-2");
  b.tecla("ArrowDown");
  assert.equal(b.ativo(), "cb-op-0");
  b.tecla("ArrowUp");
  assert.equal(b.ativo(), "cb-op-2");
  b.tecla("ArrowUp");
  assert.equal(b.ativo(), "cb-op-1");
  assert.equal(b.lista.filhos[1].getAttribute("aria-selected"), "true");
  assert.equal(b.lista.filhos.filter((li) => li.getAttribute("aria-selected") === "true").length, 1);
  const fim = b.tecla("End");
  assert.equal(b.ativo(), "cb-op-2");
  assert.equal(fim.defaultPrevented, true);
  b.tecla("Home");
  assert.equal(b.ativo(), "cb-op-0");
  // Setas laterais nunca são interceptadas.
  for (const lateral of ["ArrowLeft", "ArrowRight"]) {
    assert.equal(b.tecla(lateral).defaultPrevented, false);
    assert.equal(b.ativo(), "cb-op-0");
  }
  // Fechada, Home/End ficam com o campo de texto.
  b.tecla("Escape");
  assert.equal(b.tecla("Home").defaultPrevented, false);
  assert.equal(b.ativo(), null);
});

test("Esc fecha a lista mantendo o texto e, na segunda vez, limpa o campo", () => {
  const b = montarBusca();
  b.digitar("maria");
  b.tecla("ArrowDown");
  const primeiro = b.tecla("Escape");
  assert.equal(primeiro.defaultPrevented, true);
  assert.equal(b.aberta(), false);
  assert.equal(b.ativo(), null);
  assert.equal(b.entrada.value, "maria");
  b.tecla("Esc");
  assert.equal(b.entrada.value, "");
  // Campo vazio e fechado: Esc segue para outros componentes.
  assert.equal(b.tecla("Escape").defaultPrevented, false);
});

test("Enter e clique levam ao link da opção; Enter sem opção ativa não navega", () => {
  const b = montarBusca();
  b.digitar("joão");
  b.tecla("Enter");
  assert.deepEqual(b.destinos, []);
  b.tecla("ArrowDown");
  b.tecla("ArrowDown");
  const enter = b.tecla("Enter");
  assert.equal(enter.defaultPrevented, true);
  assert.deepEqual(b.destinos, ["vereadores/joao-pedro.html"]);
  b.digitar("ana");
  assert.equal(disparar(b.lista, "mousedown").defaultPrevented, true);
  disparar(b.lista.filhos[3].querySelector(".partido"), "click");
  assert.deepEqual(b.destinos, ["vereadores/joao-pedro.html", "vereadores/ana-lucia.html"]);
  disparar(b.entrada, "blur");
  assert.equal(b.aberta(), false);
});

test("Enter com um único resultado vai direto a ele", () => {
  const b = montarBusca();
  b.digitar("lucia");
  assert.equal(b.ativo(), null);
  const enter = b.tecla("Enter");
  assert.equal(enter.defaultPrevented, true);
  assert.deepEqual(b.destinos, ["vereadores/ana-lucia.html"]);
  // Fechada com Esc, Enter não navega.
  b.tecla("Escape");
  assert.equal(b.tecla("Enter").defaultPrevented, false);
  assert.deepEqual(b.destinos, ["vereadores/ana-lucia.html"]);
});

// ---- robustez e tamanho

test("sem elementos ou APIs, não lança", () => {
  assert.doesNotThrow(() => vm.runInNewContext(fonte, {}));
  assert.doesNotThrow(() => vm.runInNewContext(fonte, { document: {}, window: {} }));
  assert.doesNotThrow(() => vm.runInNewContext(fonte, { document: { querySelector: () => null } }));
  assert.doesNotThrow(() => vm.runInNewContext(fonte, { document: { querySelector() { throw Error("x"); } }, window: null }));
  let p;
  assert.doesNotThrow(() => { p = montar({ ceu: false, valores: [], busca: false, janela: janelaAnimada() }); });
  assert.deepEqual(p.doc.tipos, []);
  assert.equal(I.iniciar(null, null), null);
  // Seção sem a lista <details>: nada é inserido.
  const doc = documento();
  doc.appendChild(new No("section", { class: "quem-vereador", "data-combobox": "" }));
  assert.doesNotThrow(() => vm.runInNewContext(fonte, { document: doc, window: {} }));
  assert.equal(doc.getElementById("cb-vereadores"), null);
  // Sem location, Enter não lança.
  const b = montar({ janela: {}, valores: [] });
  const entrada = b.doc.getElementById("cb-vereadores");
  entrada.value = "maria";
  disparar(entrada, "input");
  disparar(entrada, "keydown", { key: "ArrowDown" });
  assert.doesNotThrow(() => disparar(entrada, "keydown", { key: "Enter" }));
});

test("inicio.js cabe em 6 KiB com gzip", () => {
  assert.ok(zlib.gzipSync(fs.readFileSync(ARQUIVO), { level: 9 }).length <= 6 * 1024);
});
