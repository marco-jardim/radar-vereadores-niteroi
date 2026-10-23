"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const RadarDados = require("../../site_src/dados.js");
const fonte = fs.readFileSync(path.join(__dirname, "../../site_src/app.js"), "utf8");
const copiar = (x) => JSON.parse(JSON.stringify(x));
const assentar = () => new Promise((resolve) => setImmediate(resolve));

const URL_DETALHE = "https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento={id}";
const COLUNAS = ["id", "tp", "n", "a", "d", "e", "st", "as", "au", "c", "sc", "h", "rs", "re", "dr", "pu", "pb", "b", "dp"];
const DIC = {
  esquema: 2, n: 5,
  tipos: [
    ["requerimento", "Requerimento", "Requerimentos", "Requerimento", 1],
    ["indicacao", "Indicação", "Indicações", "Indicação", 0],
    ["mocao", "Moção", "Moções", "Moção", 0],
    ["pdl", "Projeto de decreto legislativo", "Projetos de decreto legislativo", "PDL", 1],
    ["resolucao", "Projeto de resolução", "Projetos de resolução", "Resolução", 1]
  ],
  categorias: [["zeladoria", "Zeladoria"], ["fiscalizacao", "Fiscalização"], ["homenagem", "Homenagem"]],
  subcategorias: [["requerimento", "informacao", "Pedido de informação"], ["indicacao", "poda", "Poda e árvores"], ["mocao", "aplauso", "Aplauso"]],
  url_detalhe: URL_DETALHE
};
const ANA = ["ana-maria-teste", "Ana Teste", 1];
const dia = (i, ano, mes, d) => new Date(Date.UTC(ano, mes - 1, d - i)).toISOString().slice(0, 10);

// 120 indicações, uma por dia de 2026-10-20 para trás; 10 moções, de 2026-08-15 para trás.
const INDICACOES = Array.from({ length: 120 }, (_, i) => ({
  id: 500000 + 120 - i, tp: 1, n: (120 - i) + "/2026", a: 2026, d: dia(i, 2026, 10, 20),
  e: i === 0 ? '=HYPERLINK("http://exemplo.invalid")' : "Indica a poda na rua " + i, st: "RECEBIDO", as: null, au: [ANA],
  c: 0, sc: 1, h: 0, rs: 0, re: null, dr: null, pu: 0, pb: null, b: i % 2 ? "Icaraí" : null, dp: 0
}));
const MOCOES = Array.from({ length: 10 }, (_, i) => ({
  id: 600000 + 10 - i, tp: 2, n: (10 - i) + "/2026", a: 2026, d: dia(i, 2026, 8, 15),
  e: "Moção de aplauso " + i, st: "APROVADA", as: null, au: [ANA], c: 2, sc: 2, h: 1, rs: 0, re: null, dr: null, pu: 0, pb: null, b: null, dp: 0
}));

// Parte no formato de fatia_documentos (gerar_site.py): sem build, com dicionários locais de autores, situações e bairros.
function parte(nome, meta, linhas) {
  const locais = { au: [], st: [], b: [] };
  const indice = (lista, v) => {
    const chave = JSON.stringify(v);
    let i = lista.findIndex((x) => JSON.stringify(x) === chave);
    if (i < 0) { lista.push(v); i = lista.length - 1; }
    return i;
  };
  const colunas = {};
  COLUNAS.forEach((k) => {
    colunas[k] = linhas.map((l) => {
      if (k === "au") return l.au.map((a) => indice(locais.au, a));
      if (k === "st") return indice(locais.st, l.st);
      if (k === "b") return l.b === null ? null : indice(locais.b, l.b);
      return l[k];
    });
  });
  return { esquema: 2, nome, n: linhas.length, ...meta, pessoas: locais.au, situacoes: locais.st, bairros: locais.b, colunas };
}

// Um "build" do servidor: cortes dá onde as indicações se dividem em partes. Só responde às URLs da própria versão.
function servidor(versao, cortes = [50]) {
  const partes = [];
  let ini = 0;
  cortes.concat([INDICACOES.length]).forEach((fim, k) => {
    partes.push(parte(k ? "doc-indicacao-2026-" + k : "doc-indicacao-2026", { tipo: "indicacao", ano: 2026, parte: k }, INDICACOES.slice(ini, fim)));
    ini = fim;
  });
  partes.push(parte("doc-mocao-2026", { tipo: "mocao", ano: 2026, parte: 0 }, MOCOES));
  const arquivos = {
    "dic-pl": { url: "dados/dic-pl.json?v=" + versao, n: 1, bytes: 1 },
    "dic-doc": { url: "dados/dic-doc.json?v=" + versao, n: DIC.n, bytes: 1, familia: "dic-doc" }
  };
  const conteudo = { "dic-doc": DIC };
  partes.forEach((p) => {
    conteudo[p.nome] = p;
    arquivos[p.nome] = { url: "dados/" + p.nome + ".json?v=" + versao, n: p.n, bytes: 1, familia: "doc",
      tipo: p.tipo, ano: p.ano, parte: p.parte, ate: p.colunas.d[0], de: p.colunas.d[p.n - 1] };
  });
  return {
    manifesto: { esquema: 2, build: "pl", build_doc: "doc-" + versao, inicial: ["dic-doc"], arquivos },
    responder(url) {
      const [caminho, v] = url.split("?v=");
      const nome = caminho.replace(/^dados\//, "").replace(/\.json$/, "");
      if (v !== versao || !conteudo[nome]) return { status: 404, ok: false };
      return { status: 200, ok: true, json: async () => copiar(conteudo[nome]) };
    }
  };
}

// DOM mínimo de atividades.html (gerar_atividades em paginas.py), com o script real.
function iniciar({ query = "", manifesto, buscar, anos = ["todos", "2026", "2025"] } = {}) {
  const elementos = {}, requisicoes = [], enderecos = [];
  let exportado = null, nomeCSV = null;
  function elemento(valor = "") {
    return { value: valor, checked: false, hidden: false, disabled: false, dataset: {}, innerHTML: "", textContent: "", eventos: {},
      addEventListener(tipo, fn) { this.eventos[tipo] = fn; },
      setAttribute(nome, v) { this[nome] = v; },
      insertAdjacentHTML(_, texto) { this.innerHTML += texto; } };
  }
  ["conteudo", "q", "f-ordem", "f-tipo", "f-ano", "f-autor", "f-categoria", "f-subcategoria", "f-bairro", "f-situacao",
    "f-respondido", "f-publicado", "resultados", "resumo-filtro", "anuncio", "mais", "csv", "limpar", "manifesto-dados"].forEach((id) => {
    elementos[id] = elemento();
  });
  elementos["f-ordem"].value = "recente";
  elementos["f-ano"].value = "2026";  // <option selected> do ano padrão
  elementos["f-ano"].options = anos.map((value) => ({ value }));
  elementos["manifesto-dados"].textContent = JSON.stringify(manifesto);
  const form = elemento(), detalhes = { open: true };
  form.dataset.modo = "atividades";
  form.dataset.anoPadrao = "2026";
  form.querySelectorAll = () => [];
  form.querySelector = () => detalhes;
  form.reset = () => {
    Object.keys(elementos).filter((k) => k === "q" || k.startsWith("f-")).forEach((k) => { elementos[k].value = ""; });
    elementos["f-ordem"].value = "recente";
    elementos["f-ano"].value = "2026";
  };
  const documento = {
    readyState: "interactive",
    getElementById: (id) => elementos[id] || null,
    querySelectorAll: () => [],
    querySelector: (sel) => sel === "form.filtros" ? form : null,
    createElement: () => ({ click() { nomeCSV = this.download; } })
  };
  const contexto = {
    document: documento,
    window: { RadarDados, matchMedia: () => ({ matches: false }), addEventListener() {} },
    location: { pathname: "atividades.html", search: query },
    history: { replaceState(_, __, url) { enderecos.push(url); } },
    URLSearchParams, Blob, URL: { createObjectURL(blob) { exportado = blob; return "blob:csv"; } },
    setTimeout, clearTimeout,
    fetch: async (url) => {
      requisicoes.push(url);
      return buscar(url);
    }
  };
  vm.runInNewContext(fonte, contexto, { filename: "app.js" });
  return {
    elementos, requisicoes, enderecos,
    resumo: elementos["resumo-filtro"], resultados: elementos.resultados, mais: elementos.mais, anuncio: elementos.anuncio,
    alterar(id, valor) { elementos[id].value = valor; form.eventos.change({ target: elementos[id] }); },
    clicarMais() { elementos.mais.eventos.click(); },
    async csv() {
      elementos.csv.eventos.click();
      await assentar();
      return { nome: nomeCSV, texto: exportado ? (await exportado.text()).replace(/^\ufeff/, "") : null };
    }
  };
}

const itens = (app) => (app.resultados.innerHTML.match(/<li class="projeto doc/g) || []).length;
const RESUMO_2026 = '<p class="contagem"><b>130</b> documentos · <b>120</b> indicações · <b>10</b> moções</p>';

test("a primeira tela carrega só a parte mais recente; Mostrar mais acrescenta itens e busca só o que falta", async () => {
  const s = servidor("v1");
  const app = iniciar({ manifesto: s.manifesto, buscar: (url) => s.responder(url) });
  assert.deepEqual(app.requisicoes, ["dados/dic-doc.json?v=v1", "dados/doc-indicacao-2026.json?v=v1"]);
  assert.equal(app.resumo.innerHTML, '<p class="contagem">Carregando 130 documentos…</p>');
  await assentar();
  assert.equal(itens(app), 40);
  assert.equal(app.resumo.innerHTML, RESUMO_2026, "o total vem do manifesto antes de carregar tudo");
  assert.equal(app.mais.hidden, false);
  assert.equal(app.mais.textContent, "Mostrar mais 40");
  assert.equal(app.resultados["aria-busy"], "false");
  const antes = app.resultados.innerHTML;
  app.clicarMais();
  assert.equal(app.mais.disabled, true);
  assert.deepEqual(app.requisicoes.slice(2).sort(), ["dados/doc-indicacao-2026-1.json?v=v1", "dados/doc-mocao-2026.json?v=v1"]);
  await assentar();
  assert.equal(itens(app), 80);
  assert.ok(app.resultados.innerHTML.startsWith(antes), "Mostrar mais só acrescenta ao fim");
  assert.match(app.resultados.innerHTML, /Moção 10\/2026/);
  assert.equal(app.anuncio.textContent, "Mostrando 80 de 130 documentos.");
  assert.equal(app.resumo.innerHTML, RESUMO_2026);
  assert.equal(app.mais.disabled, false);
  assert.equal(app.mais.textContent, "Mostrar mais 40");
  app.clicarMais();
  assert.equal(app.requisicoes.length, 4, "com o recorte inteiro, Mostrar mais não busca nada");
  assert.equal(itens(app), 120);
  assert.equal(app.mais.textContent, "Mostrar mais 10");
  // A ordem mesclada das partes é a de compararDocs: a indicação de 2026-08-15 (54/2026) vem antes da moção do mesmo dia.
  const html = app.resultados.innerHTML;
  assert.ok(html.indexOf("Indicação 54/2026") < html.indexOf("Moção 10/2026"));
  assert.ok(html.indexOf("Moção 10/2026") < html.indexOf("Indicação 53/2026"));
});

test("número do documento e alternativa SISCAM abrem em nova aba sem alterar os chips internos", async () => {
  const s = servidor("v1");
  const app = iniciar({ manifesto: s.manifesto, buscar: (url) => s.responder(url) });
  await assentar();
  const html = app.resultados.innerHTML;
  assert.match(html, /<a href="https:\/\/consultaniteroi\.siscam\.com\.br\/DetalhesDocumentos\.aspx\?IdDocumento=500120" target="_blank" rel="noopener">Indicação 120\/2026<span class="so-leitor"> \(abre em nova aba\)<\/span><\/a>/);
  assert.equal((html.match(/target="_blank" rel="noopener"/g) || []).length, 80);
  assert.equal((html.match(/\(abre em nova aba\)/g) || []).length, 80);
  assert.match(html, /<a class="chip" href="vereadores\/ana-maria-teste\.html">Ana Teste<\/a>/);
});

test("resposta atrasada de uma seleção antiga é descartada", async () => {
  const s = servidor("v1"), pendentes = new Map();
  const app = iniciar({ manifesto: s.manifesto,
    buscar: (url) => new Promise((resolve) => pendentes.set(url, () => resolve(s.responder(url)))) });
  assert.deepEqual(app.requisicoes, ["dados/dic-doc.json?v=v1", "dados/doc-indicacao-2026.json?v=v1"]);
  app.alterar("f-tipo", "mocao");
  assert.deepEqual(app.requisicoes.slice(2), ["dados/doc-mocao-2026.json?v=v1"], "dic-doc em andamento é reaproveitado");
  pendentes.get("dados/dic-doc.json?v=v1")();
  pendentes.get("dados/doc-mocao-2026.json?v=v1")();
  await assentar();
  assert.equal(itens(app), 10);
  assert.equal(app.resumo.innerHTML, '<p class="contagem"><b>10</b> documentos</p>');
  pendentes.get("dados/doc-indicacao-2026.json?v=v1")();
  await assentar();
  assert.equal(itens(app), 10);
  assert.doesNotMatch(app.resultados.innerHTML, /Indicação/);
  assert.equal(app.resumo.innerHTML, '<p class="contagem"><b>10</b> documentos</p>');
  assert.equal(app.mais.hidden, true);
});

test("depois de renovar o manifesto, filtrarD replaneja com as partes do novo build", async () => {
  const antigo = servidor("v1"), novo = servidor("v2", [30]);
  const app = iniciar({ manifesto: antigo.manifesto, buscar: (url) => url === "dados/manifest.json"
    ? { ok: true, status: 200, json: async () => copiar(novo.manifesto) } : novo.responder(url) });
  await assentar();
  assert.equal(app.requisicoes.filter((u) => u === "dados/manifest.json").length, 1);
  // No build novo, a primeira parte tem só 30 indicações: o plano antigo não bastaria para 40 itens em ordem.
  assert.ok(app.requisicoes.includes("dados/doc-indicacao-2026-1.json?v=v2"));
  assert.ok(app.requisicoes.includes("dados/doc-mocao-2026.json?v=v2"));
  assert.equal(itens(app), 40);
  assert.equal(app.resumo.innerHTML, RESUMO_2026);
  assert.equal(app.mais.textContent, "Mostrar mais 40");
  assert.equal(app.resultados["aria-busy"], "false");
});

test("refatiar em partes menores mantém Mostrar mais incremental e o CSV completo", async () => {
  const s = servidor("menor", [50, 75, 100]);
  const app = iniciar({ manifesto: s.manifesto, buscar: (url) => s.responder(url) });
  await assentar();
  for (const n of [40, 80, 120, 130]) {
    assert.equal(itens(app), n);
    assert.equal(app.resumo.innerHTML, RESUMO_2026);
    if (n < 130) {
      const antes = app.resultados.innerHTML;
      app.clicarMais();
      await assentar();
      assert.ok(app.resultados.innerHTML.startsWith(antes), "nenhum item anterior é reordenado ou repetido");
    }
  }
  assert.equal(app.mais.hidden, true);
  assert.equal(app.requisicoes.length, 6, "dicionário, quatro partes de indicação e uma de moção");
  assert.equal(new Set(app.requisicoes).size, app.requisicoes.length, "cada URL só é buscada uma vez");
  const arquivo = await app.csv();
  assert.equal(arquivo.texto.split("\n").length, 131);
  assert.equal(app.requisicoes.length, 6, "CSV reutiliza todas as partes já carregadas");
});

test("CSV carrega o recorte inteiro, neutraliza fórmulas e não mexe na lista", async () => {
  const s = servidor("v1");
  const app = iniciar({ manifesto: s.manifesto, buscar: (url) => s.responder(url) });
  await assentar();
  const resumoAntes = app.resumo.innerHTML, listaAntes = app.resultados.innerHTML;
  const arquivo = await app.csv();
  assert.equal(arquivo.nome, "radar-vereadores-atividades.csv");
  const linhas = arquivo.texto.split("\n");
  assert.equal(linhas.length, 131);
  assert.match(linhas[0], /^"tipo","numero","data","ementa","situacao"/);
  assert.ok(linhas[1].startsWith('"indicacao","120/2026","2026-10-20","\'=HYPERLINK(""http://exemplo.invalid"")","RECEBIDO"'), linhas[1]);
  assert.match(arquivo.texto, /"mocao","10\/2026","2026-08-15"/);
  assert.equal(app.resumo.innerHTML, resumoAntes);
  assert.equal(app.resultados.innerHTML, listaAntes);
  assert.equal(app.resultados["aria-busy"], "false");
  assert.equal(app.elementos.csv.disabled, false);
  assert.equal(app.anuncio.textContent, "CSV com 130 documentos prontos.");
});

test("erro no CSV é anunciado sem tocar no estado da lista, e o CSV pode ser tentado de novo", async () => {
  const s = servidor("v1");
  let falhar = false;
  const app = iniciar({ manifesto: s.manifesto,
    buscar: (url) => (falhar && url.includes("doc-indicacao-2026-1") ? { status: 500, ok: false } : s.responder(url)) });
  await assentar();
  falhar = true;
  const resumoAntes = app.resumo.innerHTML, listaAntes = app.resultados.innerHTML;
  const arquivo = await app.csv();
  assert.equal(arquivo.texto, null);
  assert.equal(app.anuncio.textContent, "Não foi possível gerar o CSV. Tente de novo.");
  assert.equal(app.resumo.innerHTML, resumoAntes);
  assert.equal(app.resumo.textContent, "");
  assert.equal(app.resultados.innerHTML, listaAntes);
  assert.equal(app.resultados["aria-busy"], "false");
  assert.equal(app.elementos.csv.disabled, false);
  assert.equal(app.mais.hidden, false);
  falhar = false;
  const segundo = await app.csv();
  assert.equal(segundo.texto.split("\n").length, 131);
});

test("?ano= fora das opções volta ao ano padrão, ou a todos os anos com ?autor=", async () => {
  const s = servidor("v1"), buscar = (url) => s.responder(url);
  const app = iniciar({ query: "?ano=1999", manifesto: s.manifesto, buscar });
  assert.equal(app.elementos["f-ano"].value, "2026");
  assert.equal(app.enderecos[0], "atividades.html", "o ano padrão não vai para o endereço");
  await assentar();
  assert.equal(itens(app), 40);
  assert.equal(app.resumo.innerHTML, RESUMO_2026);
  const comAutor = iniciar({ query: "?ano=abc&autor=ana-maria-teste", manifesto: s.manifesto, buscar });
  assert.equal(comAutor.elementos["f-ano"].value, "todos");
  const valido = iniciar({ query: "?ano=2025", manifesto: s.manifesto, buscar });
  assert.equal(valido.elementos["f-ano"].value, "2025");
  assert.equal(valido.enderecos[0], "atividades.html?ano=2025");
  await assentar();
});
