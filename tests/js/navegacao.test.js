"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const zlib = require("node:zlib");

const ARQUIVO = path.join(__dirname, "../../site_src/navegacao.js");
const fonte = fs.readFileSync(ARQUIVO, "utf8");

// DOM mínimo: atributos, árvore com contains/querySelector simples (tag e classes) e eventos que sobem até o documento.
function elemento(tag, atributos) {
  return {
    tag, atributos: Object.assign({}, atributos), ouvintes: {}, filhos: [], pai: null,
    setAttribute(nome, valor) { this.atributos[nome] = String(valor); },
    getAttribute(nome) { return Object.prototype.hasOwnProperty.call(this.atributos, nome) ? this.atributos[nome] : null; },
    hasAttribute(nome) { return Object.prototype.hasOwnProperty.call(this.atributos, nome); },
    removeAttribute(nome) { delete this.atributos[nome]; },
    addEventListener(tipo, fn) { (this.ouvintes[tipo] = this.ouvintes[tipo] || []).push(fn); },
    contains(outro) { for (let no = outro; no; no = no.pai) if (no === this) return true; return false; },
    anexar(...filhos) { for (const f of filhos) { f.pai = this; this.filhos.push(f); } return this; },
    querySelector(seletor) {
      const [tagAlvo, ...classes] = seletor.split(".");
      const procurar = (no) => {
        for (const f of no.filhos) {
          const cls = (f.atributos.class || "").split(" ");
          if (f.tag === tagAlvo && classes.every((c) => cls.includes(c))) return f;
          const achado = procurar(f);
          if (achado) return achado;
        }
        return null;
      };
      return procurar(this);
    }
  };
}

function disparar(alvo, tipo, extra) {
  const evento = Object.assign({ type: tipo, target: alvo }, extra);
  for (let no = alvo; no; no = no.pai) for (const fn of no.ouvintes[tipo] || []) fn(evento);
  return evento;
}

function midia(estreita, { legado = false } = {}) {
  const m = { media: "", matches: estreita, ouvintes: [] };
  if (legado) m.addListener = (fn) => m.ouvintes.push(fn);
  else m.addEventListener = (tipo, fn) => { if (tipo === "change") m.ouvintes.push(fn); };
  m.mudar = (valor) => { m.matches = valor; for (const fn of m.ouvintes) fn({ matches: valor, media: m.media }); };
  return m;
}

// Cabeçalho como em paginas.pagina(): marca, botão oculto e nav#menu-principal, com a página ativa marcada.
function montar({ estreita = true, comMatchMedia = true, legado = false, semBotao = false } = {}) {
  const documento = elemento("#document");
  const html = elemento("html", { class: "js" });
  const body = elemento("body");
  const topo = elemento("header", { class: "topo" });
  const marca = elemento("a", { class: "marca", href: "index.html" });
  const botao = elemento("button", { class: "menu-botao", type: "button", "aria-expanded": "false",
    "aria-controls": "menu-principal", hidden: "" });
  const nav = elemento("nav", { id: "menu-principal", "aria-label": "Principal" });
  const links = ["index.html", "sessoes.html", "metodologia.html"].map((href) =>
    elemento("a", href === "sessoes.html" ? { href, "aria-current": "page" } : { href }));
  nav.anexar(...links);
  topo.anexar(marca);
  if (!semBotao) topo.anexar(botao);
  topo.anexar(nav);
  const main = elemento("main", { id: "conteudo" });
  const fora = elemento("p");
  main.anexar(fora);
  body.anexar(topo, main);
  html.anexar(body);
  documento.anexar(html);
  let focado = null;
  for (const el of [botao, marca, fora, ...links]) el.focus = function () { focado = this; };
  const tiposDocumento = [];
  const adicionar = documento.addEventListener;
  documento.addEventListener = function (tipo, fn) { tiposDocumento.push(tipo); adicionar.call(this, tipo, fn); };
  const m = comMatchMedia ? midia(estreita, { legado }) : null;
  const consultas = [];
  const janela = comMatchMedia ? { matchMedia: (q) => { consultas.push(q); m.media = q; return m; } } : {};
  vm.runInNewContext(fonte, { document: documento, window: janela }, { filename: "navegacao.js" });
  return { documento, topo, botao, nav, links, marca, fora, midia: m, consultas, tiposDocumento, focado: () => focado };
}

const expandido = (p) => p.botao.getAttribute("aria-expanded");
const menu = (p) => p.topo.getAttribute("data-menu");

test("sem cabeçalho, botão ou API de documento, não lança nem registra ouvintes", () => {
  assert.doesNotThrow(() => vm.runInNewContext(fonte, { document: {}, window: {} }));
  assert.doesNotThrow(() => vm.runInNewContext(fonte, { document: { querySelector: () => null }, window: {} }));
  assert.doesNotThrow(() => vm.runInNewContext(fonte, {}));
  const p = montar({ semBotao: true });
  assert.deepEqual(p.tiposDocumento, []);
  assert.equal(menu(p), null);
});

test("botão aparece só abaixo do limite, com o menu fechado", () => {
  const estreita = montar({ estreita: true });
  assert.deepEqual(estreita.consultas, ["(max-width: 759.98px)"]);
  assert.equal(estreita.botao.hasAttribute("hidden"), false);
  assert.equal(menu(estreita), "fechado");
  assert.equal(expandido(estreita), "false");
  const larga = montar({ estreita: false });
  assert.equal(larga.botao.hasAttribute("hidden"), true);
  assert.equal(menu(larga), null);
  assert.equal(expandido(larga), "false");
  disparar(larga.botao, "click");
  assert.equal(menu(larga), null);
  assert.equal(expandido(larga), "false");
});

test("um único ouvinte por tipo no documento", () => {
  const p = montar();
  assert.deepEqual([...p.tiposDocumento].sort(), ["click", "keydown"]);
});

test("o botão alterna aria-expanded e data-menu", () => {
  const p = montar();
  disparar(p.botao, "click");
  assert.equal(expandido(p), "true");
  assert.equal(menu(p), "aberto");
  disparar(p.botao, "click");
  assert.equal(expandido(p), "false");
  assert.equal(menu(p), "fechado");
});

test("Esc fecha e devolve o foco ao botão; com o menu fechado, não faz nada", () => {
  const p = montar();
  p.fora.focus();
  disparar(p.fora, "keydown", { key: "Escape" });
  assert.equal(p.focado(), p.fora);
  assert.equal(menu(p), "fechado");
  disparar(p.botao, "click");
  p.links[0].focus();
  disparar(p.links[0], "keydown", { key: "Enter" });
  assert.equal(menu(p), "aberto");
  disparar(p.links[0], "keydown", { key: "Escape" });
  assert.equal(menu(p), "fechado");
  assert.equal(expandido(p), "false");
  assert.equal(p.focado(), p.botao);
  // Navegadores antigos usam "Esc".
  disparar(p.botao, "click");
  disparar(p.botao, "keydown", { key: "Esc" });
  assert.equal(menu(p), "fechado");
});

test("clique fora do cabeçalho fecha; clique dentro não", () => {
  const p = montar();
  disparar(p.botao, "click");
  disparar(p.nav, "click");
  disparar(p.marca, "click");
  assert.equal(menu(p), "aberto");
  disparar(p.fora, "click");
  assert.equal(menu(p), "fechado");
  assert.equal(expandido(p), "false");
});

test("foco que sai do cabeçalho fecha o menu", () => {
  const p = montar();
  disparar(p.botao, "click");
  disparar(p.botao, "focusout", { relatedTarget: p.links[0] });
  assert.equal(menu(p), "aberto");
  disparar(p.links[2], "focusout", { relatedTarget: p.fora });
  assert.equal(menu(p), "fechado");
  assert.equal(expandido(p), "false");
  // Sem destino (foco saiu da página), também fecha.
  disparar(p.botao, "click");
  disparar(p.links[2], "focusout", { relatedTarget: null });
  assert.equal(menu(p), "fechado");
  // Clique num link sem foco (Safari) não fecha antes de o clique chegar ao link.
  disparar(p.botao, "click");
  disparar(p.links[1], "mousedown");
  disparar(p.botao, "focusout", { relatedTarget: null });
  assert.equal(menu(p), "aberto");
  // Depois de uma tecla, o Tab para fora sem destino volta a fechar.
  disparar(p.links[1], "mousedown");
  disparar(p.links[2], "keydown", { key: "Tab" });
  disparar(p.links[2], "focusout", { relatedTarget: null });
  assert.equal(menu(p), "fechado");
});

test("sem matchMedia, não lança, botão segue oculto e a navegação visível", () => {
  let p;
  assert.doesNotThrow(() => { p = montar({ comMatchMedia: false }); });
  assert.equal(p.botao.hasAttribute("hidden"), true);
  assert.equal(menu(p), null);
  disparar(p.botao, "click");
  assert.equal(menu(p), null);
  assert.equal(expandido(p), "false");
});

test("troca de faixa com o menu aberto fecha e esconde o botão, inclusive com addListener", () => {
  for (const legado of [false, true]) {
    const p = montar({ legado });
    disparar(p.botao, "click");
    assert.equal(menu(p), "aberto");
    p.midia.mudar(false);
    assert.equal(p.botao.hasAttribute("hidden"), true);
    assert.equal(menu(p), null);
    assert.equal(expandido(p), "false");
    p.midia.mudar(true);
    assert.equal(p.botao.hasAttribute("hidden"), false);
    assert.equal(menu(p), "fechado");
    assert.equal(expandido(p), "false");
  }
});

test("o link da página atual mantém aria-current com o menu fechado e aberto", () => {
  const p = montar();
  assert.equal(p.links[1].getAttribute("aria-current"), "page");
  disparar(p.botao, "click");
  disparar(p.botao, "click");
  assert.equal(menu(p), "fechado");
  assert.equal(p.links[1].getAttribute("aria-current"), "page");
  assert.equal(p.links[0].getAttribute("aria-current"), null);
});

test("require expõe as funções puras sem tocar no DOM, e o CSS usa o mesmo limite", () => {
  const N = require(ARQUIVO);
  assert.equal(N.CONSULTA, "(max-width: 759.98px)");
  assert.equal(N.ehEscape({ key: "Escape" }), true);
  assert.equal(N.ehEscape({ key: "Esc" }), true);
  assert.equal(N.ehEscape({ key: "Enter" }), false);
  assert.equal(N.ehEscape(null), false);
  assert.equal(N.fora({}, {}), false);
  assert.equal(N.iniciar(null, null), null);
  const css = fs.readFileSync(path.join(__dirname, "../../site_src/estilo.css"), "utf8");
  assert.ok(css.includes(`@media ${N.CONSULTA}`));
  assert.ok(css.includes('.topo[data-menu="fechado"] nav { display: none; }'));
});

test("navegacao.js cabe em 4 KiB com gzip", () => {
  assert.ok(zlib.gzipSync(fs.readFileSync(ARQUIVO)).length <= 4 * 1024);
});
