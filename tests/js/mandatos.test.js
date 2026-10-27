"use strict";

// Melhoria progressiva das tabelas: nenhuma rede, DOM mínimo e eventos locais.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const fonte = fs.readFileSync(require("node:path").join(__dirname, "../../site_src/app.js"), "utf8");

function iniciar() {
  const eventosDocumento = {};
  function elemento(extra = {}) {
    return Object.assign({ eventos: {}, addEventListener(tipo, fn) { this.eventos[tipo] = fn; } }, extra);
  }
  function secao() {
    const corpo = { children: [
      { dataset: { nome: "Ana", cargo: "0", eleicoes: "0", sessoes: "10", presenca: "80", nominais: "", pls: "2", pedidos: "3" } },
      { dataset: { nome: "Bruno", cargo: "1", eleicoes: "3", sessoes: "12", presenca: "90", nominais: "50", pls: "4", pedidos: "3" } },
      { dataset: { nome: "Carlos", cargo: "0", eleicoes: "", sessoes: "1", presenca: "", nominais: "100", pls: "", pedidos: "" } }
    ], appendChild(linha) { this.children.splice(this.children.indexOf(linha), 1); this.children.push(linha); } };
    const controles = { hidden: true }, ordenar = elemento({ value: "nome" }), ocultar = elemento({ checked: false });
    const mapa = { "tbody": corpo, "[data-controles-mandatos]": controles,
      "[data-ordem-mandatos]": ordenar, "[data-ocultar-cargos]": ocultar };
    return { querySelector: (s) => mapa[s], corpo, controles, ordenar, ocultar };
  }
  const secoes = [secao(), secao()];
  const document = {
    getElementById: () => null, querySelector: () => null,
    querySelectorAll: (s) => s === "[data-mandatos]" ? secoes : [],
    addEventListener(tipo, fn) {
      assert.equal(eventosDocumento[tipo], undefined, "um listener por tipo no documento");
      eventosDocumento[tipo] = fn;
    }
  };
  vm.runInNewContext(fonte, { document, window: {} });
  return secoes;
}

test("mandatos: revela controles e preserva ordem alfabética inicial sem ocultar linhas", () => {
  for (const sec of iniciar()) {
    assert.equal(sec.controles.hidden, false);
    assert.deepEqual(sec.corpo.children.map((l) => l.dataset.nome), ["Ana", "Bruno", "Carlos"]);
    assert.ok(sec.corpo.children.every((l) => !l.hidden));
  }
});

test("mandatos: ordena números descendo, zero antes de ausente, desempate por nome e filtro reversível", () => {
  const [sec, outra] = iniciar();
  function ordenar(chave, esperado) {
    sec.ordenar.value = chave;
    sec.ordenar.eventos.change();
    assert.deepEqual(sec.corpo.children.map((l) => l.dataset.nome), esperado);
  }
  for (const chave of ["eleicoes", "sessoes", "presenca", "pls"]) ordenar(chave, ["Bruno", "Ana", "Carlos"]);
  ordenar("nominais", ["Carlos", "Bruno", "Ana"]);
  ordenar("pedidos", ["Ana", "Bruno", "Carlos"]);
  sec.ocultar.checked = true;
  sec.ocultar.eventos.change();
  assert.deepEqual(sec.corpo.children.filter((l) => !l.hidden).map((l) => l.dataset.nome), ["Ana", "Carlos"]);
  ordenar("nome", ["Ana", "Bruno", "Carlos"]);
  assert.equal(sec.corpo.children[1].hidden, true);
  sec.ocultar.checked = false;
  sec.ocultar.eventos.change();
  assert.ok(sec.corpo.children.every((l) => !l.hidden));
  assert.ok(outra.corpo.children.every((l) => !l.hidden), "cada legislatura tem controles independentes");
});
