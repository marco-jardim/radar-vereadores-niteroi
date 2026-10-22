"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { hidratar, fatiasPara, norm } = require("../../site_src/dados.js");
const fixture = require("./fixtures/pl.json");
const copiar = (x) => JSON.parse(JSON.stringify(x));

test("hidratação recupera todos os campos e a ordem do JSON legado", () => {
  const antes = JSON.stringify(fixture);
  const linhas = fixture.fatias.flatMap((fatia) => hidratar(fixture.dic, fatia)
    .map((p, i) => ({ p, ordem: fatia.colunas.ord[i] })));
  linhas.sort((a, b) => a.ordem - b.ordem);
  assert.deepEqual(linhas.map((linha) => linha.p), fixture.legado.projetos);
  assert.equal(JSON.stringify(fixture), antes, "as entradas não podem ser alteradas");
});

test("autor fora da lista de pessoas mantém o nome de fallback e o slug", () => {
  const p = hidratar(fixture.dic, fixture.fatias[1])[0];
  assert.equal(fixture.legado.pessoas[p.pr], undefined);
  assert.deepEqual(p.au, [["Fabiano Gonçalves", "fabiano-goncalves"]]);
  assert.equal(p.pt, "");
});

test("coautores mantêm a ordem e o principal não precisa ser o primeiro", () => {
  const p = hidratar(fixture.dic, fixture.fatias[0])[0];
  assert.equal(p.au.length, 2);
  assert.notEqual(p.au[0][1], p.pr);
  assert.equal(p.au[1][1], p.pr);
  assert.equal(p.pt, "PSOL");
});

test("tipo da lei e veto parcial são hidratados sem perder a paridade com o legado", () => {
  const fatia = copiar(fixture.fatias[0]);
  fatia.colunas.lt[0] = "veto_derrubado";
  fatia.colunas.vp[0] = 1;
  const p = hidratar(fixture.dic, fatia)[0];
  assert.deepEqual(p, { ...fixture.legado.projetos[1], lt: "veto_derrubado", vp: 1 });
});

test("substitutivo da lei vira a URL do detalhe, sem mudar a URL do PL original", () => {
  const fatia = copiar(fixture.fatias[0]);
  fatia.colunas.ls[0] = 266596;
  const [p, outro] = hidratar(fixture.dic, fatia);
  assert.deepEqual(p, { ...fixture.legado.projetos[1], ls: "https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento=266596" });
  assert.equal(p.u, fixture.legado.projetos[1].u);
  assert.equal(outro.ls, null);
  delete fatia.colunas.ls;
  assert.throws(() => hidratar(fixture.dic, fatia), /Coluna inválida: ls/);
});

test("partido é o da legislatura do projeto, com fallback vazio", () => {
  const fatia = copiar(fixture.fatias[0]);
  fatia.colunas.lg[1] = 0;
  assert.equal(hidratar(fixture.dic, fatia)[1].pt, "PV");
  fatia.colunas.lg[1] = null;
  const p = hidratar(fixture.dic, fatia)[1];
  assert.equal(p.lg, null);
  assert.equal(p.pt, "");
});

test("executivo preserva nome e slug vazio sem inventar autor principal", () => {
  const dic = copiar(fixture.dic), fatia = copiar(fixture.fatias[1]);
  dic.pessoas.push(["", "Rodrigo Neves", {}]);
  fatia.colunas.au[0] = [dic.pessoas.length - 1];
  fatia.colunas.pr[0] = null;
  fatia.colunas.o[0] = dic.origens.indexOf("executivo");
  const p = hidratar(dic, fatia)[0];
  assert.deepEqual(p.au, [["Rodrigo Neves", ""]]);
  assert.equal(p.pr, null);
  assert.equal(p.pt, "");
  assert.equal(p.o, "executivo");
});

test("alertas, notas, sinais, repetição e flags numéricas são reversíveis", () => {
  const fatia = copiar(fixture.fatias[2]);
  fatia.colunas.al[0] = [[0, 2, "Nota da IA"], [1, 0, "Nota <pública> & verificável"]];
  fatia.colunas.s[0] = [3, 2];
  fatia.colunas.rp[0] = "1/2021";
  fatia.colunas.pol[0] = 1;
  const p = hidratar(fixture.dic, fatia)[0];
  assert.deepEqual(p.al, [["Risco de inconstitucionalidade", "ia", "Nota da IA"], ["Pauta de costumes", "curadoria", "Nota <pública> & verificável"]]);
  assert.deepEqual(p.s, ["veto_total", "repete_projeto"]);
  assert.equal(p.rp, "1/2021");
  assert.equal(p.pol, 1);
  assert.equal(p.ef, 0);
});

test("efeito sem avaliação e sinais autorizativos seguem as regras do modelo", () => {
  const fatia = copiar(fixture.fatias[0]);
  fatia.colunas.i[1] = null;
  let p = hidratar(fixture.dic, fatia)[1];
  assert.equal(p.ef, 1);
  assert.equal(p.se, 0);
  fatia.colunas.s[1] = [0];
  p = hidratar(fixture.dic, fatia)[1];
  assert.equal(p.ef, 0);
  assert.equal(p.se, 1);
  fatia.colunas.i[1] = 2;
  assert.equal(hidratar(fixture.dic, fatia)[1].ef, 1, "impacto avaliado tem precedência, como no modelo");
});

test("rejeita esquema, build e colunas incompatíveis", () => {
  assert.throws(() => hidratar({ ...fixture.dic, esquema: 1 }, fixture.fatias[0]), /Esquema/);
  assert.throws(() => hidratar(fixture.dic, { ...fixture.fatias[0], build: "outro" }), /build/);
  const fatia = copiar(fixture.fatias[0]);
  fatia.colunas.au.pop();
  assert.throws(() => hidratar(fixture.dic, fatia), /Coluna inválida: au/);
});

test("leis só requerem a fatia de leis, independentemente dos demais filtros", () => {
  assert.deepEqual(fatiasPara("leis"), ["pl-lei"]);
  assert.deepEqual(fatiasPara("leis", { desfecho: "sem_exito", autor: "alguem" }), ["pl-lei"]);
});

test("projetos selecionam só o desfecho pedido ou todas as fatias", () => {
  ["lei", "andamento", "sem_exito"].forEach((desfecho) => {
    assert.deepEqual(fatiasPara("projetos", { desfecho }), ["pl-" + desfecho]);
  });
  [undefined, {}, { desfecho: "" }, { desfecho: "invalido" }, { sinal: "alerta_ia", ano: "2025" }].forEach((filtros) => {
    assert.deepEqual(fatiasPara("projetos", filtros), ["pl-lei", "pl-andamento", "pl-sem_exito"]);
  });
});

test("normalização ignora caixa e acentos sem remover números e pontuação", () => {
  assert.equal(norm("AÇÃO, Niterói — SAÚDE 1/2025"), "acao, niteroi — saude 1/2025");
  assert.equal(norm("Gonc\u0327alves"), "goncalves");
  assert.equal(norm(null), "");
  assert.equal(norm(undefined), "");
});
