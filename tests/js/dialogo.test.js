"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const RadarDados = require("../../site_src/dados.js");
const fonte = fs.readFileSync(path.join(__dirname, "../../site_src/app.js"), "utf8");

const URL_OK = "https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento=275545";
const SANDBOX = "allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox";

// DOM mínimo do <dialog> de DIALOGO_SISCAM (paginas.py), numa página sem lista (sem form.filtros).
function iniciar() {
  const eventos = {}, classes = [];
  let focado = null;
  function elemento() {
    return { atributos: {}, eventos: {}, textContent: "", href: "",
      addEventListener(tipo, fn) { this.eventos[tipo] = fn; },
      setAttribute(nome, valor) { this.atributos[nome] = String(valor); },
      getAttribute(nome) { return Object.prototype.hasOwnProperty.call(this.atributos, nome) ? this.atributos[nome] : null; } };
  }
  const quadro = elemento();
  let html = "";
  quadro.filhos = [];
  Object.defineProperty(quadro, "innerHTML", { get: () => html, set: (v) => { html = v; if (v === "") quadro.filhos = []; } });
  quadro.appendChild = (filho) => { quadro.filhos.push(filho); return filho; };
  const dialogo = elemento();
  dialogo.open = false;
  dialogo.aberturas = 0;
  dialogo.showModal = () => { dialogo.open = true; dialogo.aberturas += 1; };
  dialogo.close = () => {
    if (!dialogo.open) return;
    dialogo.open = false;
    if (dialogo.eventos.close) dialogo.eventos.close();
  };
  const elementos = { "siscam-dialogo": dialogo, "siscam-quadro": quadro, "siscam-titulo": elemento(),
    "siscam-abrir": elemento(), "siscam-fechar": elemento() };
  const documento = {
    documentElement: { classList: { add: (c) => classes.push(c) } },
    body: { contains: () => true },
    addEventListener(tipo, fn) { eventos[tipo] = fn; },
    getElementById: (id) => elementos[id] || null,
    querySelectorAll: () => [],
    querySelector: () => null,
    createElement: (tag) => Object.assign(elemento(), { tag })
  };
  vm.runInNewContext(fonte, { document: documento, window: { RadarDados } }, { filename: "app.js" });
  return {
    dialogo, quadro, classes, elementos, focado: () => focado,
    botao(url, rotulo) {
      const bt = elemento();
      bt.setAttribute("data-url", url);
      bt.setAttribute("data-rotulo", rotulo);
      bt.focus = () => { focado = bt; };
      return bt;
    },
    clicar(bt) { eventos.click({ target: { closest: (sel) => (sel === "button.ver-siscam" ? bt : null) } }); }
  };
}

test("abre o detalhe num iframe com sandbox, sem lazy nem referrer, e devolve o foco ao fechar", () => {
  const app = iniciar();
  assert.deepEqual(app.classes, ["com-dialogo"]);
  const bt = app.botao(URL_OK, "PL 1/2025");
  app.clicar(bt);
  assert.equal(app.dialogo.aberturas, 1);
  assert.equal(app.quadro.filhos.length, 1);
  const iframe = app.quadro.filhos[0];
  assert.equal(iframe.tag, "iframe");
  assert.deepEqual(iframe.atributos, { sandbox: SANDBOX, referrerpolicy: "no-referrer", title: "Detalhe no SISCAM: PL 1/2025", src: URL_OK });
  assert.doesNotMatch(iframe.atributos.sandbox, /allow-top-navigation/);
  assert.equal(app.elementos["siscam-titulo"].textContent, "Detalhe no SISCAM: PL 1/2025");
  assert.equal(app.elementos["siscam-abrir"].href, URL_OK);
  app.elementos["siscam-fechar"].eventos.click();
  assert.equal(app.dialogo.open, false);
  assert.equal(app.quadro.filhos.length, 0, "fechar descarta o iframe");
  assert.equal(app.focado(), bt, "o foco volta ao botão que abriu o diálogo");
});

test("clique no fundo fecha; clique dentro da caixa não fecha", () => {
  const app = iniciar();
  const bt = app.botao(URL_OK, "Indicação 1/2026");
  app.clicar(bt);
  app.dialogo.eventos.click({ target: {} });
  assert.equal(app.dialogo.open, true);
  app.dialogo.eventos.click({ target: app.dialogo });
  assert.equal(app.dialogo.open, false);
  assert.equal(app.focado(), bt);
});

test("recusa endereços que não são a página de detalhe de um documento do SISCAM", () => {
  const app = iniciar();
  [
    "https://consultaniteroi.siscam.com.br/",
    "https://consultaniteroi.siscam.com.br/Outra.aspx?IdDocumento=1",
    "https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento=1&x=2",
    "https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento=abc",
    "https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento=1\nhttps://exemplo.invalid/",
    "http://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento=1",
    "https://consultaniteroi.siscam.com.br.exemplo.invalid/DetalhesDocumentos.aspx?IdDocumento=1",
    "https://exemplo.invalid/?u=https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento=1",
    "javascript:alert(1)",
    ""
  ].forEach((url) => app.clicar(app.botao(url, "X")));
  assert.equal(app.dialogo.aberturas, 0);
  assert.equal(app.quadro.filhos.length, 0);
  assert.equal(app.elementos["siscam-abrir"].href, "");
  assert.equal(app.focado(), null);
  // Cliques fora de um botão "Ver no SISCAM" são ignorados.
  app.clicar(null);
  assert.equal(app.dialogo.aberturas, 0);
});
