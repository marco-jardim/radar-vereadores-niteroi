"use strict";

// Partido ao lado do nome nos renderizadores do navegador (espelhos de partido_html em paginas.py).
const test = require("node:test");
const assert = require("node:assert/strict");
const S = require("../../site_src/sessoes.js");
const RadarDados = require("../../site_src/dados.js");
const fixture = require("./fixtures/sessoes.json");

const copiar = (x) => JSON.parse(JSON.stringify(x));

function comPartido() {
  const fatia = copiar(fixture.fatia);
  // Quinto campo das pessoas de vot-<ano>: o partido na legislatura do ano, só quando conhecido.
  fatia.pessoas = fatia.pessoas.map((p) => (p[0] === "ana" ? [...p, "PX"] : p));
  return S.hidratar(fixture.dic, fatia);
}

test("sessões: o partido do quinto campo entra no chip, logo depois do nome", () => {
  const lista = comPartido();
  assert.equal(lista[2].pessoas.ana.partido, "PX");
  assert.equal(lista[2].pessoas.bia.partido, "");
  const html = S.cartao(fixture.dic, lista[2], "");
  assert.match(html, /<a class="chip" href="vereadores\/ana\.html">[^<]+<span class="partido">PX<\/span><\/a>/);
  assert.doesNotMatch(html, /Bia Suplente<span class="partido">/);
});

test("sessões: sem partido conhecido, o cartão continua igual ao do servidor", () => {
  const esperado = S.cartao(fixture.dic, S.hidratar(fixture.dic, copiar(fixture.fatia))[2], "");
  assert.doesNotMatch(esperado, /class="partido"/);
});

test("sessões: a faixa leva o partido uma vez por linha, no cabeçalho da linha", () => {
  const membros = fixture.membros.map((m) => (m.slug === "ana" ? { ...m, partido: "PX" } : m));
  const html = S.faixa(comPartido(), membros, fixture.leg, 2025, "");
  assert.match(html, /<tr role="row" data-vereador="ana"><th scope="row" role="rowheader" data-label="Vereador">[^]*?<span class="partido">PX<\/span>[^]*?<\/th>/);
  assert.equal((html.match(/<span class="partido">PX<\/span>/g) || []).length, 2, "uma vez na faixa e uma no resumo");
});

test("documentos: o partido é o quarto campo da pessoa local", () => {
  const dic = { esquema: 2, tipos: [["indicacao", "Indicação", "Indicações", "Indicação", 0]], categorias: [["zeladoria", "Zeladoria"]],
    subcategorias: [["indicacao", "poda", "Poda e árvores"]], url_detalhe: "https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento={id}" };
  const fatia = { esquema: 2, n: 1, pessoas: [["ana", "Ana", 1, "PX"], ["bia", "Bia", 0]], situacoes: ["RECEBIDO"], bairros: [],
    colunas: { id: [1], tp: [0], n: ["1/2026"], a: [2026], d: ["2026-01-02"], e: ["Indica a poda"], st: [0], as: [null],
      au: [[0, 1]], c: [0], sc: [0], h: [0], rs: [0], re: [null], dr: [null], pu: [0], pb: [null], b: [null], dp: [0] } };
  assert.deepEqual(RadarDados.hidratarDocs(dic, fatia)[0].autores, [["Ana", "ana", 1, "PX"], ["Bia", "bia", 0, ""]]);
});
