"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const zlib = require("node:zlib");

const ARQUIVO = path.join(__dirname, "../../site_src/navegacao.js");
const fonte = fs.readFileSync(ARQUIVO, "utf8");

// DOM mínimo: atributos, árvore com contains/querySelector simples e eventos que sobem até o documento.
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
      const atributo = seletor.match(/\[([^=]+)="([^"]+)"\]$/);
      const [tagAlvo, ...classes] = seletor.replace(/\[.*$/, "").split(".");
      const procurar = (no) => {
        for (const f of no.filhos) {
          const cls = (f.atributos.class || "").split(" ");
          if (f.tag === tagAlvo && classes.every((c) => cls.includes(c)) &&
              (!atributo || f.getAttribute(atributo[1]) === atributo[2])) return f;
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
// <html class="js"> como deixa o script do head; ponteiro=true expõe PointerEvent na janela.
function montar({ estreita = true, comMatchMedia = true, legado = false, semBotao = false, ponteiro = false } = {}) {
  const documento = elemento("#document");
  const html = elemento("html", { class: "js" });
  html.classList = {
    remove(classe) { html.atributos.class = html.atributos.class.split(" ").filter((c) => c && c !== classe).join(" "); },
    contains(classe) { return html.atributos.class.split(" ").includes(classe); }
  };
  documento.documentElement = html;
  documento.activeElement = null;
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
  for (const el of [botao, marca, fora, ...links]) el.focus = function () { focado = this; documento.activeElement = this; };
  const tiposDocumento = [];
  const adicionar = documento.addEventListener;
  documento.addEventListener = function (tipo, fn) { tiposDocumento.push(tipo); adicionar.call(this, tipo, fn); };
  const m = comMatchMedia ? midia(estreita, { legado }) : null;
  const consultas = [];
  const janela = comMatchMedia ? { matchMedia: (q) => { consultas.push(q); m.media = q; return m; } } : {};
  if (ponteiro) janela.PointerEvent = function PointerEvent() {};
  vm.runInNewContext(fonte, { document: documento, window: janela }, { filename: "navegacao.js" });
  return { documento, html, topo, botao, nav, links, marca, fora, midia: m, consultas, tiposDocumento,
    focado: () => focado, js: () => html.classList.contains("js") };
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
  // Sem menu funcional, a classe js sai e o CSS volta a mostrar a navegação.
  assert.equal(p.js(), false);
  assert.equal(montar().js(), true);
});

test("exceção ao montar o menu tira a classe js sem propagar", () => {
  const N = require(ARQUIVO);
  let removida = null;
  const documento = {
    documentElement: { classList: { remove(c) { removida = c; } } },
    addEventListener() {},
    querySelector() { throw Error("falhou"); }
  };
  assert.equal(N.iniciar(documento, { matchMedia() {} }), null);
  assert.equal(removida, "js");
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

test("um único ouvinte por tipo no documento, com pointerdown ou, sem PointerEvent, mousedown", () => {
  assert.deepEqual([...montar().tiposDocumento].sort(), ["click", "keydown", "mousedown"]);
  assert.deepEqual([...montar({ ponteiro: true }).tiposDocumento].sort(), ["click", "keydown", "pointerdown"]);
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
  // Esc já tratado por outro componente ou durante composição (IME) não fecha.
  disparar(p.botao, "click");
  disparar(p.botao, "keydown", { key: "Escape", defaultPrevented: true });
  disparar(p.botao, "keydown", { key: "Escape", isComposing: true });
  assert.equal(menu(p), "aberto");
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

test("pressão de ponteiro fora não fecha no focusout; o clique fora fecha depois", () => {
  for (const ponteiro of [true, false]) {
    const p = montar({ ponteiro });
    const pressao = ponteiro ? "pointerdown" : "mousedown";
    disparar(p.botao, "click");
    p.links[0].focus();
    // O foco sai para um elemento fora do cabeçalho durante a pressão: o menu continua aberto,
    // para não deslocar o conteúdo sob o ponteiro antes do clique.
    disparar(p.fora, pressao);
    disparar(p.links[0], "focusout", { relatedTarget: p.fora });
    assert.equal(menu(p), "aberto");
    assert.equal(expandido(p), "true");
    disparar(p.fora, "click");
    assert.equal(menu(p), "fechado");
    assert.equal(expandido(p), "false");
    // Pressão dentro do menu seguida de clique num link também não fecha antes da hora.
    disparar(p.botao, "click");
    disparar(p.links[1], pressao);
    disparar(p.links[0], "focusout", { relatedTarget: null });
    disparar(p.links[1], "click");
    assert.equal(menu(p), "aberto");
  }
});

test("focusout consome a pressão que não virou clique, sem depender de uma tecla", () => {
  for (const ponteiro of [true, false]) {
    const p = montar({ ponteiro });
    disparar(p.botao, "click");
    disparar(p.links[1], ponteiro ? "pointerdown" : "mousedown");
    disparar(p.botao, "focusout", { relatedTarget: null });
    assert.equal(menu(p), "aberto");
    // Outra saída de foco programática, sem clique nem keydown, não herda a pressão anterior.
    p.links[1].focus();
    disparar(p.links[1], "focusout", { relatedTarget: p.fora });
    assert.equal(menu(p), "fechado");
  }
});

test("Tab para fora pelo teclado, sem ponteiro, fecha o menu", () => {
  for (const ponteiro of [true, false]) {
    const p = montar({ ponteiro });
    disparar(p.botao, "click");
    p.links[2].focus();
    disparar(p.links[2], "keydown", { key: "Tab" });
    disparar(p.links[2], "focusout", { relatedTarget: p.fora });
    assert.equal(menu(p), "fechado");
    assert.equal(expandido(p), "false");
    // A tecla zera uma pressão anterior que não virou clique (ex.: rolagem por toque).
    disparar(p.botao, "click");
    disparar(p.fora, ponteiro ? "pointerdown" : "mousedown");
    disparar(p.links[2], "keydown", { key: "Tab" });
    disparar(p.links[2], "focusout", { relatedTarget: p.fora });
    assert.equal(menu(p), "fechado");
  }
});

test("ao estreitar com o foco num link, o foco vai para o botão Menu", () => {
  const p = montar({ estreita: false });
  p.links[1].focus();
  p.midia.mudar(true);
  assert.equal(p.focado(), p.botao);
  assert.equal(menu(p), "fechado");
  // Foco fora da navegação não é movido.
  const q = montar({ estreita: false });
  q.fora.focus();
  q.midia.mudar(true);
  assert.equal(q.focado(), q.fora);
});

test("ao alargar com foco no Menu, foca a página atual ou o primeiro link", () => {
  for (const legado of [false, true]) {
    for (const atual of [true, false]) {
      const p = montar({ legado });
      if (!atual) p.links[1].removeAttribute("aria-current");
      p.botao.focus();
      p.midia.mudar(false);
      assert.equal(p.botao.hasAttribute("hidden"), true);
      assert.equal(p.focado(), p.links[atual ? 1 : 0]);
    }
  }
  // Não rouba foco de links já visíveis nem de fora do cabeçalho.
  for (const alvo of ["link", "fora"]) {
    const p = montar();
    const foco = alvo === "link" ? p.links[2] : p.fora;
    foco.focus();
    p.midia.mudar(false);
    assert.equal(p.focado(), foco);
  }
});

test("sem matchMedia, não lança, botão segue oculto e a navegação visível", () => {
  let p;
  assert.doesNotThrow(() => { p = montar({ comMatchMedia: false }); });
  assert.equal(p.botao.hasAttribute("hidden"), true);
  assert.equal(menu(p), null);
  assert.equal(p.js(), false);
  assert.deepEqual(p.tiposDocumento, []);
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
  assert.equal(N.ehEscape({ key: "Escape", defaultPrevented: true }), false);
  assert.equal(N.ehEscape({ key: "Escape", isComposing: true }), false);
  assert.equal(N.fora({}, {}), false);
  assert.equal(N.iniciar(null, null), null);
  const css = fs.readFileSync(path.join(__dirname, "../../site_src/estilo.css"), "utf8");
  assert.ok(css.includes(`@media ${N.CONSULTA}`));
  // O CSS recolhe pela classe js do head (primeira pintura) e só mostra a navegação com data-menu="aberto".
  const estreito = css.split(`@media ${N.CONSULTA} {`)[1].split("\n}")[0];
  assert.ok(estreito.includes('.js .topo:not([data-menu="aberto"]) nav { display: none; }'));
  assert.ok(estreito.includes(".js .menu-botao { display: inline-flex;"));
});

test("navegacao.js cabe em 4 KiB com gzip", () => {
  assert.ok(zlib.gzipSync(fs.readFileSync(ARQUIVO)).length <= 4 * 1024);
});
