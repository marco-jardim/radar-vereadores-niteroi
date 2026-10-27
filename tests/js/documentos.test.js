"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { hidratarDocs, fatiasDocs, compararDocs, numeroInt, mesclarDocs } = require("../../site_src/dados.js");
const plano = require("./fixtures/plano_docs.json");
const copiar = (x) => JSON.parse(JSON.stringify(x));

const URL_DETALHE = "https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento={id}";
// dic-doc só com enumerações estáveis; autores, situações e bairros vêm em dicionários locais de cada parte.
const dic = {
  esquema: 2, n: 5,
  tipos: [
    ["requerimento", "Requerimento", "Requerimentos", "Requerimento", 1],
    ["indicacao", "Indicação", "Indicações", "Indicação", 0],
    ["mocao", "Moção", "Moções", "Moção", 0],
    ["pdl", "Projeto de decreto legislativo", "Projetos de decreto legislativo", "PDL", 1],
    ["resolucao", "Projeto de resolução", "Projetos de resolução", "Resolução", 1]
  ],
  categorias: [["zeladoria", "Zeladoria"], ["fiscalizacao", "Fiscalização"], ["homenagem", "Homenagem"],
    ["manifestacao", "Manifestação"], ["legislacao", "Legislação"], ["outra", "Outra"]],
  subcategorias: [["requerimento", "informacao", "Pedido de informação"], ["requerimento", "outro", "Outro requerimento"],
    ["indicacao", "poda", "Poda e árvores"], ["pdl", "titulo_cidadao", "Título de cidadão"]],
  url_detalhe: URL_DETALHE
};
const indicacoes = {
  esquema: 2, nome: "doc-indicacao-2026", n: 2, tipo: "indicacao", ano: 2026, parte: 0,
  // O quarto campo (partido na legislatura do documento) só existe quando é conhecido.
  pessoas: [["", "Mesa Diretora 2025/2026", 0], ["ana-maria-teste", "Ana Teste", 1, "PX"], ["dina-so-indicacao", "Diná", 0]],
  situacoes: ["RECEBIDO"], bairros: ["Icaraí"],
  colunas: {
    id: [900002, 900001], tp: [1, 1], n: ["11/2026", "10/2026"], a: [2026, 2026], d: ["2026-03-11", "2026-03-10"],
    e: ["Indica a troca de lâmpadas", "Indica a poda de árvores na Rua Tal, Icaraí."], st: [0, 0], as: [null, "Poda"],
    au: [[2], [1, 0]], c: [0, 0], sc: [2, 2], h: [0, 0], rs: [0, 0], re: [null, null], dr: [null, null], pu: [0, 0],
    pb: [null, null], b: [null, 0], dp: [0, 1]
  }
};
const misto = {
  esquema: 2, nome: "ver/ana-maria-teste", n: 2, slug: "ana-maria-teste", tipo: null, parte: 0,
  pessoas: [["ana-maria-teste", "Ana Teste", 1]], situacoes: ["PUBLICADO", "RESPONDIDO"], bairros: [],
  colunas: {
    id: [900020, 900010], tp: [3, 0], n: ["2/2026", "3/2026"], a: [2026, 2026], d: ["2026-04-01", "2026-02-01"],
    e: ["Concede o título de cidadão niteroiense.", "Requer informações sobre o contrato."], st: [0, 1], as: [null, null],
    au: [[0], [0]], c: [2, 1], sc: [3, 0], h: [1, 0], rs: [0, 1], re: [null, "2026-03-03"], dr: [null, 30], pu: [1, 0],
    pb: [["123", "2026-05-02"], null], b: [null, null], dp: [0, 0]
  }
};

test("hidratação de documentos recupera todos os campos e autores que não são vereadores", () => {
  const antes = JSON.stringify([dic, indicacoes]);
  const docs = hidratarDocs(dic, indicacoes);
  assert.deepEqual(docs, [
    {
      id: 900002, tipo: "indicacao", numero: "11/2026", ano: 2026, data: "2026-03-11", ementa: "Indica a troca de lâmpadas",
      situacao: "RECEBIDO", assunto: null, autores: [["Diná", "dina-so-indicacao", 0, ""]], categoria: "zeladoria", subcategoria: "poda",
      homenagem: false, respondido: false, respondido_em: null, dias_ate_resposta: null, publicado: false, publicacao: null,
      bairro: null, detalhe_pendente: false, url: "https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento=900002"
    },
    {
      id: 900001, tipo: "indicacao", numero: "10/2026", ano: 2026, data: "2026-03-10", ementa: "Indica a poda de árvores na Rua Tal, Icaraí.",
      situacao: "RECEBIDO", assunto: "Poda", autores: [["Ana Teste", "ana-maria-teste", 1, "PX"], ["Mesa Diretora 2025/2026", "", 0, ""]],
      categoria: "zeladoria", subcategoria: "poda", homenagem: false, respondido: false, respondido_em: null, dias_ate_resposta: null,
      publicado: false, publicacao: null, bairro: "Icaraí", detalhe_pendente: true,
      url: "https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento=900001"
    }
  ]);
  assert.equal(JSON.stringify([dic, indicacoes]), antes, "as entradas não podem ser alteradas");
});

test("arquivo por vereador mistura tipos: resposta, publicação e homenagem são reversíveis", () => {
  const [pdl, req] = hidratarDocs(dic, misto);
  assert.equal(pdl.tipo, "pdl");
  assert.equal(pdl.subcategoria, "titulo_cidadao");
  assert.equal(pdl.categoria, "homenagem");
  assert.equal(pdl.homenagem, true);
  assert.equal(pdl.publicado, true);
  assert.deepEqual(pdl.publicacao, { numero: "123", data: "2026-05-02" });
  assert.equal(pdl.situacao, "PUBLICADO");
  assert.equal(req.tipo, "requerimento");
  assert.equal(req.categoria, "fiscalizacao");
  assert.equal(req.respondido, true);
  assert.equal(req.respondido_em, "2026-03-03");
  assert.equal(req.dias_ate_resposta, 30);
  assert.equal(req.publicacao, null);
});

test("rejeita esquema, colunas, dicionários locais e índices incompatíveis", () => {
  assert.throws(() => hidratarDocs({ ...dic, esquema: 1 }, indicacoes), /Esquema/);
  assert.throws(() => hidratarDocs(dic, { ...indicacoes, esquema: 3 }), /Esquema/);
  const curta = copiar(indicacoes);
  curta.colunas.dp.pop();
  assert.throws(() => hidratarDocs(dic, curta), /Coluna inválida: dp/);
  const sem = copiar(indicacoes);
  delete sem.colunas.as;
  assert.throws(() => hidratarDocs(dic, sem), /Coluna inválida: as/);
  const semPessoas = copiar(indicacoes);
  delete semPessoas.pessoas;
  assert.throws(() => hidratarDocs(dic, semPessoas), /Dicionário local inválido/);
  const fora = copiar(indicacoes);
  fora.colunas.au[0] = [99];
  assert.throws(() => hidratarDocs(dic, fora), /Índice inválido/);
  const bairro = copiar(indicacoes);
  bairro.colunas.b[1] = 5;
  assert.throws(() => hidratarDocs(dic, bairro), /Índice inválido/);
  const situacao = copiar(indicacoes);
  situacao.colunas.st[0] = 3;
  assert.throws(() => hidratarDocs(dic, situacao), /Índice inválido/);
});

test("partes sem build hidratam com qualquer dic-doc do mesmo esquema", () => {
  const docs = hidratarDocs({ ...dic, build: "qualquer" }, { ...indicacoes, build: "outro" });
  assert.equal(docs.length, 2);
});

test("ordem dos documentos: data, ano, número e id, do mais recente; sem data por último", () => {
  const docs = [
    { id: 1, ano: 2026, numero: "2/2026", data: "2026-03-10" },
    { id: 2, ano: 2026, numero: "10/2026", data: "2026-03-10" },
    { id: 3, ano: 2026, numero: "1/2026", data: null },
    { id: 4, ano: 2025, numero: "300/2025", data: "2026-01-02" },
    { id: 5, ano: 2026, numero: "10/2026", data: "2026-03-10" }
  ];
  assert.deepEqual(docs.slice().sort(compararDocs).map((d) => d.id), [5, 2, 1, 4, 3]);
  assert.equal(numeroInt("0012/2026"), 12);
  assert.equal(numeroInt(null), 0);
  // A chave numérica calculada na hidratação (_n) vale no lugar do número.
  const comChave = docs.map((d) => ({ ...d, _n: numeroInt(d.numero) }));
  assert.deepEqual(comChave.slice().sort(compararDocs).map((d) => d.id), [5, 2, 1, 4, 3]);
});

test("mescla partes já ordenadas sem reordenar tudo e sem alterar as entradas", () => {
  const doc = (id, data, numero) => ({ id, ano: 2026, numero: numero + "/2026", data, _n: numero });
  const a = [doc(1, "2026-10-20", 9), doc(2, "2026-10-10", 5), doc(3, "2026-09-01", 1)];
  const b = [doc(4, "2026-10-15", 7), doc(5, "2026-10-10", 6), doc(6, null, 2)];
  const c = [doc(7, "2026-10-21", 3)];
  const antes = JSON.stringify([a, b, c]);
  const esperado = a.concat(b, c).sort(compararDocs).map((d) => d.id);
  assert.deepEqual(mesclarDocs([a, b, c]).map((d) => d.id), esperado);
  assert.deepEqual(esperado, [7, 1, 4, 5, 2, 3, 6]);
  assert.equal(JSON.stringify([a, b, c]), antes);
  // Uma parte fora de ordem é ordenada antes de intercalar.
  assert.deepEqual(mesclarDocs([b.slice().reverse(), a]).map((d) => d.id), [1, 4, 5, 2, 3, 6]);
  assert.deepEqual(mesclarDocs([]), []);
  assert.deepEqual(mesclarDocs([a]).map((d) => d.id), [1, 2, 3]);
  assert.notEqual(mesclarDocs([a]), a, "devolve uma lista nova");
});

const parte = (tipo, ano, k, n, ate, de) => ({ url: "dados/x.json?v=1", n, bytes: 1, familia: "doc", tipo, ano, parte: k, ate, de });
const manifesto = {
  esquema: 2, build: "pl", build_doc: "doc0000001", arquivos: {
    "dic-pl": { url: "dados/dic-pl.json?v=1", n: 1, bytes: 1 },
    "pl-lei": { url: "dados/pl-lei.json?v=1", n: 1, bytes: 1 },
    "dic-doc": { url: "dados/dic-doc.json?v=1", n: 3, bytes: 1, familia: "dic-doc" },
    "doc-indicacao-2026": parte("indicacao", 2026, 0, 50, "2026-10-20", "2026-10-01"),
    "doc-indicacao-2026-1": parte("indicacao", 2026, 1, 500, "2026-09-30", "2026-05-01"),
    "doc-indicacao-2026-2": parte("indicacao", 2026, 2, 500, "2026-04-30", "2026-01-02"),
    "doc-mocao-2026": parte("mocao", 2026, 0, 30, "2026-10-21", "2026-08-01"),
    "doc-mocao-2026-1": parte("mocao", 2026, 1, 300, "2026-07-31", "2026-01-05"),
    "doc-requerimento-2026": parte("requerimento", 2026, 0, 120, "2026-10-15", "2026-01-10"),
    "doc-indicacao-2025": parte("indicacao", 2025, 0, 400, "2025-12-20", "2025-06-01"),
    "doc-indicacao-2025-1": parte("indicacao", 2025, 1, 400, "2025-05-31", "2025-01-03"),
    "ver/ana-maria-teste": { url: "dados/ver/a.json?v=1", n: 10, bytes: 1, familia: "ver", slug: "ana-maria-teste", tipo: null, parte: 0 },
    "ver/dina-so-indicacao-mocao": { url: "dados/ver/d3.json?v=1", n: 5, bytes: 1, familia: "ver", slug: "dina-so-indicacao", tipo: "mocao", parte: 0 },
    "ver/dina-so-indicacao-indicacao-1": { url: "dados/ver/d2.json?v=1", n: 100, bytes: 1, familia: "ver", slug: "dina-so-indicacao", tipo: "indicacao", parte: 1 },
    "ver/dina-so-indicacao-indicacao": { url: "dados/ver/d1.json?v=1", n: 800, bytes: 1, familia: "ver", slug: "dina-so-indicacao", tipo: "indicacao", parte: 0 }
  }
};

test("sem filtros de conteúdo, carrega o menor prefixo de partes que garante os itens pedidos em ordem", () => {
  const antes = JSON.stringify(manifesto);
  const plano = fatiasDocs(manifesto, { ano: "2026", alvo: 40 });
  assert.deepEqual(plano.nomes, ["doc-mocao-2026", "doc-indicacao-2026", "doc-requerimento-2026"]);
  assert.equal(plano.fronteira, "2026-09-30");
  assert.equal(plano.completo, false);
  assert.equal(plano.total, 1500, "contagem vem do manifesto, antes de carregar");
  assert.deepEqual(plano.porTipo, { indicacao: 1050, mocao: 330, requerimento: 120 });
  assert.equal(JSON.stringify(manifesto), antes, "o manifesto não pode ser alterado");
});

test("pedir mais itens só acrescenta partes, e o tipo restringe as candidatas", () => {
  const plano = fatiasDocs(manifesto, { ano: "2026", alvo: 100 });
  assert.deepEqual(plano.nomes, ["doc-mocao-2026", "doc-indicacao-2026", "doc-requerimento-2026", "doc-indicacao-2026-1", "doc-mocao-2026-1"]);
  assert.equal(plano.fronteira, "2026-04-30");
  const indicacao = fatiasDocs(manifesto, { tipo: "indicacao", ano: "2026", alvo: 40 });
  assert.deepEqual(indicacao.nomes, ["doc-indicacao-2026"]);
  assert.equal(indicacao.total, 1050);
  const tudo = fatiasDocs(manifesto, { ano: "2026", alvo: 1e9 });
  assert.equal(tudo.completo, true);
  assert.equal(tudo.fronteira, null);
  assert.equal(tudo.nomes.length, 6);
});

test("filtros de conteúdo carregam o recorte inteiro, em qualquer ano", () => {
  assert.deepEqual(fatiasDocs(manifesto, { tipo: "indicacao", ano: "2026", completo: true }), {
    nomes: ["doc-indicacao-2026", "doc-indicacao-2026-1", "doc-indicacao-2026-2"],
    total: 1050, porTipo: { indicacao: 1050 }, completo: true, fronteira: null
  });
  ["todos", "", undefined].forEach((ano) => {
    assert.deepEqual(fatiasDocs(manifesto, { tipo: ["indicacao"], ano, completo: true }).nomes,
      ["doc-indicacao-2026", "doc-indicacao-2026-1", "doc-indicacao-2026-2", "doc-indicacao-2025", "doc-indicacao-2025-1"]);
  });
  assert.deepEqual(fatiasDocs(manifesto, { tipo: ["mocao", "requerimento"], ano: 2026, completo: true }).nomes,
    ["doc-mocao-2026", "doc-requerimento-2026", "doc-mocao-2026-1"]);
});

test("com autor, usa só os arquivos do vereador, inteiros e filtrados pelo tipo quando divididos", () => {
  assert.deepEqual(fatiasDocs(manifesto, { autor: "dina-so-indicacao", alvo: 40 }).nomes,
    ["ver/dina-so-indicacao-indicacao", "ver/dina-so-indicacao-indicacao-1", "ver/dina-so-indicacao-mocao"]);
  const mocao = fatiasDocs(manifesto, { autor: "dina-so-indicacao", tipo: "mocao", ano: "2026" });
  assert.deepEqual(mocao.nomes, ["ver/dina-so-indicacao-mocao"]);
  assert.equal(mocao.completo, true);
  assert.deepEqual(fatiasDocs(manifesto, { autor: "ana-maria-teste", tipo: "pdl" }).nomes, ["ver/ana-maria-teste"]);
  assert.deepEqual(fatiasDocs(manifesto, { autor: "ninguem" }), { nomes: [], total: 0, porTipo: {}, completo: true, fronteira: null });
});

test("paridade com plano_docs (paginas.py): a mesma fixture é conferida em tests/test_documentos_site.py", () => {
  const antes = JSON.stringify(plano);
  [plano, ...plano.refatiamentos].forEach((cenario) => {
    assert.ok(cenario.casos.length > 0);
    cenario.casos.forEach((caso) => {
      assert.deepEqual(fatiasDocs(cenario.manifesto, { tipo: caso.tipo, ano: caso.ano, alvo: caso.alvo }).nomes, caso.nomes, caso.nome);
    });
  });
  assert.equal(JSON.stringify(plano), antes);
});

test("partes menores preservam contagens, fronteira estrita e planos que só acrescentam arquivos", () => {
  const manifesto = plano.refatiamentos[0].manifesto;
  const inicial = fatiasDocs(manifesto, { ano: 2026, alvo: 40 });
  assert.equal(inicial.total, 530);
  assert.deepEqual(inicial.porTipo, { indicacao: 450, mocao: 80 });
  assert.equal(inicial.fronteira, "2026-10-19");
  assert.equal(inicial.completo, false);
  const mais = fatiasDocs(manifesto, { ano: 2026, alvo: 100 });
  assert.deepEqual(mais.nomes.slice(0, inicial.nomes.length), inicial.nomes);
  assert.equal(mais.fronteira, "2026-06-30");
  const inteiro = fatiasDocs(manifesto, { ano: 2026, completo: true });
  assert.deepEqual(inteiro.nomes.slice(0, mais.nomes.length), mais.nomes);
  assert.equal(inteiro.total, inicial.total);
  assert.equal(inteiro.completo, true);
  assert.equal(inteiro.fronteira, null);
});

test("ignora arquivos de PL e tolera manifesto vazio", () => {
  const plano = fatiasDocs(manifesto, { completo: true });
  assert.ok(plano.nomes.every((n) => n.startsWith("doc-")));
  assert.equal(plano.nomes.length, 8);
  assert.deepEqual(fatiasDocs({ arquivos: {} }, {}), { nomes: [], total: 0, porTipo: {}, completo: true, fronteira: null });
  assert.deepEqual(fatiasDocs(null), { nomes: [], total: 0, porTipo: {}, completo: true, fronteira: null });
});
