"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const RadarDados = require("../../site_src/dados.js");
const fixture = require("./fixtures/pl.json");
const fonte = fs.readFileSync(path.join(__dirname, "../../site_src/app.js"), "utf8");
const copiar = (x) => JSON.parse(JSON.stringify(x));
const assentar = () => new Promise((resolve) => setImmediate(resolve));
const COLUNAS_PL = ["id", "ord", "n", "a", "d", "e", "r", "pb", "t", "h", "c", "i", "l", "ld", "lt", "vp", "dl", "o", "lg", "pr", "au", "al", "pol", "s", "rp", "ls"];

function manifestoPara(build, conjunto = fixture) {
  const arquivos = {};
  [conjunto.dic, ...conjunto.fatias].forEach((dados) => {
    const nome = dados.nome || "dic-pl";
    arquivos[nome] = { url: "dados/" + nome + ".json?v=" + build, n: dados.n, bytes: 1 };
  });
  return { esquema: 2, build, inicial: ["dic-pl", "pl-lei"], arquivos };
}

function resposta(url, build, conjunto = fixture) {
  const nome = url.split("/").pop().split(".json")[0];
  const dados = nome === "dic-pl" ? conjunto.dic : conjunto.fatias.find((f) => f.nome === nome);
  if (!dados) return { status: 404, ok: false };
  return { status: 200, ok: true, json: async () => ({ ...copiar(dados), build }) };
}

// n projetos sintéticos no formato das fatias, mais a prévia pl-recentes (os 40 primeiros pela ordem padrão),
// como exportar_fatias (gerar_site.py). Índices nos dicionários de fixture.dic.
function conjuntoPL(n, ajustar = () => {}) {
  const vazia = (nome) => ({ esquema: 2, nome, n: 0, colunas: Object.fromEntries(COLUNAS_PL.map((k) => [k, []])) });
  const grupos = { lei: vazia("pl-lei"), andamento: vazia("pl-andamento"), sem_exito: vazia("pl-sem_exito") };
  const recentes = vazia("pl-recentes"), desfecho = { lei: 2, andamento: 0, sem_exito: 1 };
  for (let j = 0; j < n; j++) {
    const g = ["lei", "andamento", "sem_exito"][j % 3];
    const data = new Date(Date.UTC(2026, 9, 21 - j)).toISOString().slice(0, 10);
    const linha = {
      id: 400000 + j, ord: j, n: (n - j) + "/2026", a: 2026, d: data, e: "Ementa do projeto " + j, r: "Resumo " + j, pb: "moradores",
      t: 2, h: desfecho[g], c: 1, i: j % 4, l: g === "lei" ? 5000 + j : null, ld: g === "lei" ? data : null, dl: g === "lei" ? 10 : null,
      lt: g === "lei" ? "sancionada" : null, vp: 0,
      o: 3, lg: 1, pr: 3, au: [3], al: [], pol: j % 5 === 0 ? 1 : 0, s: [], rp: null, ls: null
    };
    ajustar(linha, j);
    [grupos[g]].concat(j < 40 ? [recentes] : []).forEach((f) => {
      f.n += 1;
      COLUNAS_PL.forEach((k) => f.colunas[k].push(linha[k]));
    });
  }
  return { dic: copiar(fixture.dic), fatias: [grupos.lei, grupos.andamento, grupos.sem_exito, recentes] };
}

// DOM mínimo: exercita o script real, sem dependências de navegador ou de terceiros.
function iniciar({ modo = "projetos", query = "", buscar, manifesto = manifestoPara(fixture.dic.build), total, resumoInicial = "" } = {}) {
  const elementos = {}, requisicoes = [], eventosJanela = {}, enderecos = [];
  let exportado = null, nomeCSV = null;
  function elemento(valor = "") {
    return { value: valor, checked: false, hidden: false, disabled: false, dataset: {}, innerHTML: "", textContent: "", eventos: {},
      addEventListener(tipo, fn) { this.eventos[tipo] = fn; },
      setAttribute(nome, valor) { this[nome] = valor; },
      insertAdjacentHTML(_, texto) { this.innerHTML += texto; } };
  }
  ["conteudo", "q", "f-ordem", "f-origem", "f-autor", "f-partido", "f-tema", "f-leg", "f-ano", "f-coautor", "resultados", "resumo-filtro", "mais", "csv", "limpar", "manifesto-dados"].forEach((id) => {
    elementos[id] = elemento();
  });
  if (modo === "projetos") {
    elementos["f-desfecho"] = elemento();
    elementos["f-sinal"] = elemento();
  }
  elementos["f-ordem"].value = "recente";
  elementos["f-coautor"].disabled = true;
  elementos["manifesto-dados"].textContent = JSON.stringify(manifesto);
  // Como em filtros_lista (paginas.py): resumo e números dos chips gerados no build, só em projetos.html.
  if (total !== undefined) elementos["resumo-filtro"].dataset.total = String(total);
  elementos["resumo-filtro"].innerHTML = resumoInicial;
  const contadores = [];
  const impactos = ["3", "2", "1", "0", "x"].map((k) => {
    const cb = elemento(k), contador = elemento();
    if (total !== undefined) { contador.className = "n inicial"; contador.textContent = "99"; }
    contadores.push(contador);
    cb.parentNode = { querySelector: () => contador };
    return cb;
  });
  const form = elemento(), detalhes = { open: true };
  form.dataset.modo = modo;
  form.querySelectorAll = () => impactos;
  form.querySelector = () => detalhes;
  form.reset = () => {
    Object.keys(elementos).filter((k) => k === "q" || k.startsWith("f-")).forEach((k) => { elementos[k].value = ""; elementos[k].checked = false; });
    elementos["f-ordem"].value = "recente";
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
    window: { RadarDados, matchMedia: () => ({ matches: false }), requestIdleCallback: (fn) => fn(),
      addEventListener(tipo, fn) { eventosJanela[tipo] = fn; } },
    location: { pathname: modo + ".html", search: query }, history: { replaceState(_, __, url) { enderecos.push(url); } },
    URLSearchParams, Blob, URL: { createObjectURL(blob) { exportado = blob; return "blob:csv"; } },
    setTimeout, clearTimeout,
    fetch: async (url, opcoes) => {
      requisicoes.push({ url, opcoes });
      return buscar ? buscar(url, opcoes) : resposta(url, fixture.dic.build);
    }
  };
  vm.runInNewContext(fonte, contexto, { filename: "app.js" });
  return { elementos, requisicoes, impactos, contadores, enderecos,
    alterar(id, valor) { elementos[id].value = valor; form.eventos.change({ target: elementos[id] }); },
    limpar() { elementos.limpar.eventos.click(); },
    carregarPagina() { if (eventosJanela.load) eventosJanela.load(); },
    async csv() {
      elementos.csv.eventos.click();
      await assentar();
      return { nome: nomeCSV, texto: exportado ? await exportado.text() : null };
    }
  };
}

const itens = (app) => (app.elementos.resultados.innerHTML.match(/<li class="projeto/g) || []).length;

test("carrega só o desfecho inicial e busca apenas fatias ausentes ao mudar o filtro", async () => {
  const app = iniciar({ query: "?desfecho=lei" });
  await assentar();
  assert.deepEqual(app.requisicoes.map((r) => r.url), ["dados/dic-pl.json?v=fixture-fase1", "dados/pl-lei.json?v=fixture-fase1"]);
  assert.match(app.elementos["resumo-filtro"].innerHTML, /<b>2<\/b> projetos/);
  app.alterar("f-desfecho", "andamento");
  assert.match(app.elementos["resumo-filtro"].innerHTML, /Carregando/);
  assert.equal(app.elementos.csv.disabled, true);
  await assentar();
  assert.equal(app.requisicoes.length, 3);
  assert.equal(app.requisicoes[2].url, "dados/pl-andamento.json?v=fixture-fase1");
  app.alterar("f-desfecho", "");
  await assentar();
  assert.equal(app.requisicoes.length, 4);
  assert.equal(app.requisicoes[3].url, "dados/pl-sem_exito.json?v=fixture-fase1");
  assert.match(app.elementos["resumo-filtro"].innerHTML, /<b>4<\/b> projetos/);
  app.alterar("f-desfecho", "lei");
  await assentar();
  assert.equal(app.requisicoes.length, 4, "arquivos já carregados são reutilizados");
  assert.equal(app.elementos.csv.disabled, false);
});

test("leis não carregam projetos em andamento nem sem êxito; CSV preserva os campos", async () => {
  const app = iniciar({ modo: "leis", query: "?autor=rodrigo-flach-farah&efeito=1&ordem=impacto" });
  await assentar();
  assert.equal(app.requisicoes.length, 2);
  assert.ok(app.requisicoes.every((r) => !/projetos\.json|pl-andamento|pl-sem_exito/.test(r.url)));
  assert.deepEqual(app.impactos.filter((cb) => cb.checked).map((cb) => cb.value), ["3", "2"]);
  assert.match(app.elementos["resumo-filtro"].innerHTML, /<b>1<\/b> lei/);
  const arquivo = await app.csv();
  assert.equal(arquivo.nome, "radar-vereadores-leis.csv");
  assert.match(arquivo.texto, /"numero","data","ementa","resumo","desfecho"/);
  assert.match(arquivo.texto, /"1\/2025","2025-02-06"/);
  assert.match(arquivo.texto, /"Cidadania","Rodrigo Farah"/);
  assert.match(arquivo.texto, /IdDocumento=275545/);
  assert.doesNotMatch(arquivo.texto, /8\/2025/);
});

test("sem filtro as três fatias começam em paralelo e respostas antigas não vencem a seleção atual", async () => {
  const pendentes = [];
  const app = iniciar({ buscar: (url) => new Promise((resolve) => pendentes.push(() => resolve(resposta(url, fixture.dic.build)))) });
  assert.equal(app.requisicoes.length, 4);
  app.alterar("f-desfecho", "sem_exito");
  pendentes.forEach((resolver) => resolver());
  await assentar();
  assert.match(app.elementos["resumo-filtro"].innerHTML, /<b>1<\/b> projeto/);
  assert.match(app.elementos.resultados.innerHTML, /5\/2025/);
  assert.doesNotMatch(app.elementos.resultados.innerHTML, /407\/2026/);
});

test("build incompatível renova o manifesto uma vez e hidrata só o novo build", async () => {
  const novo = manifestoPara("novo-build");
  const app = iniciar({ query: "?desfecho=lei", buscar: (url) => {
    if (url === "dados/manifest.json") return { ok: true, json: async () => novo };
    return resposta(url, "novo-build");
  } });
  await assentar();
  const renovacoes = app.requisicoes.filter((r) => r.url === "dados/manifest.json");
  assert.equal(renovacoes.length, 1);
  assert.equal(renovacoes[0].opcoes.cache, "no-cache");
  assert.ok(app.requisicoes.some((r) => r.url === novo.arquivos["pl-lei"].url));
  assert.match(app.elementos["resumo-filtro"].innerHTML, /<b>2<\/b> projetos/);
  assert.equal(app.elementos.csv.disabled, false);
});

test("404 persistente termina com aviso acessível sem repetir a renovação", async () => {
  const app = iniciar({ query: "?desfecho=lei", buscar: (url) => {
    if (url === "dados/manifest.json") return { ok: true, json: async () => manifestoPara("novo-build") };
    return { status: 404, ok: false };
  } });
  await assentar();
  assert.equal(app.requisicoes.filter((r) => r.url === "dados/manifest.json").length, 1);
  assert.equal(app.elementos["resumo-filtro"].textContent, "Site atualizado, recarregue a página");
  assert.equal(app.elementos.resultados["aria-busy"], "false");
  assert.equal(app.elementos.csv.disabled, true);
});

// ------------------------------------------------------- renovação do manifesto
test("falha de rede na renovação mostra o erro real, e a próxima ação tenta renovar de novo", async () => {
  const novo = manifestoPara("novo-build");
  let tentativas = 0;
  const app = iniciar({ query: "?desfecho=lei", buscar: (url) => {
    if (url === "dados/manifest.json") {
      tentativas += 1;
      if (tentativas === 1) throw new TypeError("rede indisponível");
      return { ok: true, status: 200, json: async () => novo };
    }
    return url.endsWith("?v=novo-build") ? resposta(url, "novo-build") : { status: 404, ok: false };
  } });
  await assentar();
  assert.equal(tentativas, 1);
  assert.equal(app.elementos["resumo-filtro"].textContent, "Não foi possível carregar os dados. Recarregue a página.",
    "um erro de rede não vira 'Site atualizado'");
  app.alterar("f-desfecho", "lei");
  await assentar();
  assert.equal(tentativas, 2, "a renovação rejeitada não fica guardada para sempre");
  assert.match(app.elementos["resumo-filtro"].innerHTML, /<b>2<\/b> projetos/);
});

test("depois da renovação, um erro do servidor segue como erro real", async () => {
  const novo = manifestoPara("novo-build");
  const app = iniciar({ query: "?desfecho=lei", buscar: (url) => {
    if (url === "dados/manifest.json") return { ok: true, status: 200, json: async () => novo };
    if (url === novo.arquivos["pl-lei"].url) return { status: 500, ok: false };
    return url.endsWith("?v=novo-build") ? resposta(url, "novo-build") : { status: 404, ok: false };
  } });
  await assentar();
  assert.equal(app.requisicoes.filter((r) => r.url === "dados/manifest.json").length, 1);
  assert.equal(app.elementos["resumo-filtro"].textContent, "Não foi possível carregar os dados. Recarregue a página.");
});

test("manifesto 500 na renovação não vira 'Site atualizado'", async () => {
  const app = iniciar({ query: "?desfecho=lei", buscar: (url) => {
    if (url === "dados/manifest.json") return { ok: false, status: 500 };
    return { status: 404, ok: false };
  } });
  await assentar();
  assert.equal(app.elementos["resumo-filtro"].textContent, "Não foi possível carregar os dados. Recarregue a página.");
});

// ------------------------------------------------------------ prévia de projetos
const RESUMO = '<p class="contagem inicial"><b>50</b> projetos · <b>9</b> com efeito (viraram lei) · <b>1</b> sem efeito prático · <b>10</b> com alerta</p>';

function iniciarPrevia(opcoes = {}) {
  const conjunto = opcoes.conjunto || conjuntoPL(50);
  const manifesto = manifestoPara("previa-1", conjunto);
  return iniciar({ manifesto, total: 50, resumoInicial: RESUMO, buscar: (url) => resposta(url, "previa-1", conjunto), ...opcoes });
}

test("sem consulta, projetos mostram a prévia com o resumo do build e carregam o resto depois da carga", async () => {
  const app = iniciarPrevia();
  assert.deepEqual(app.requisicoes.map((r) => r.url), ["dados/dic-pl.json?v=previa-1", "dados/pl-recentes.json?v=previa-1"]);
  await assentar();
  assert.equal(itens(app), 40);
  assert.match(app.elementos.resultados.innerHTML, /PL 50\/2026/);
  assert.equal(app.elementos["resumo-filtro"].innerHTML, RESUMO, "o resumo exato do HTML não é recalculado com dados parciais");
  assert.deepEqual(app.contadores.map((c) => c.textContent), ["99", "99", "99", "99", "99"]);
  assert.equal(app.elementos.mais.hidden, false);
  assert.equal(app.elementos.mais.textContent, "Mostrar mais 10");
  assert.equal(app.requisicoes.length, 2, "as fatias completas esperam a carga da página");
  app.carregarPagina();
  await assentar();
  assert.deepEqual(app.requisicoes.slice(2).map((r) => r.url).sort(),
    ["dados/pl-andamento.json?v=previa-1", "dados/pl-lei.json?v=previa-1", "dados/pl-sem_exito.json?v=previa-1"]);
  assert.equal(itens(app), 40, "a carga completa não redesenha a lista");
  assert.equal(app.elementos["resumo-filtro"].innerHTML, RESUMO);
  app.elementos.mais.eventos.click();
  assert.equal(itens(app), 50);
  assert.match(app.elementos.resultados.innerHTML, /PL 1\/2026/);
  assert.equal(app.elementos.mais.hidden, true);
});

test("Mostrar mais na prévia carrega as fatias completas na hora e só acrescenta itens", async () => {
  const app = iniciarPrevia();
  await assentar();
  const antes = app.elementos.resultados.innerHTML;
  app.elementos.mais.eventos.click();
  assert.equal(app.elementos.mais.disabled, true);
  assert.equal(app.requisicoes.length, 5);
  await assentar();
  assert.equal(itens(app), 50);
  assert.ok(app.elementos.resultados.innerHTML.startsWith(antes));
  assert.equal(app.elementos.mais.hidden, true);
  assert.equal(app.elementos.mais.disabled, false);
  app.carregarPagina();
  await assentar();
  assert.equal(app.requisicoes.length, 5, "a carga em segundo plano reaproveita o que já veio");
});

test("filtro na prévia carrega só o que o filtro precisa e recalcula resumo e chips", async () => {
  const app = iniciarPrevia();
  await assentar();
  app.alterar("f-desfecho", "lei");
  assert.match(app.elementos["resumo-filtro"].innerHTML, /Carregando/);
  await assentar();
  assert.deepEqual(app.requisicoes.slice(2).map((r) => r.url), ["dados/pl-lei.json?v=previa-1"]);
  // j % 3 === 0 para j < 50: 17 leis. Impacto i = j % 4: 3 em j = 3, 15, 27, 39; 2 em 6, 18, 30, 42;
  // 1 em 9, 21, 33, 45; 0 em 0, 12, 24, 36, 48. Chips na ordem 3, 2, 1, 0, x.
  assert.match(app.elementos["resumo-filtro"].innerHTML, /<b>17<\/b> projetos/);
  assert.deepEqual(app.contadores.map((c) => String(c.textContent)), ["4", "4", "4", "5", "0"]);
  assert.ok(app.contadores.every((c) => c.className === "n"));
  app.carregarPagina();
  await assentar();
  assert.equal(app.requisicoes.length, 3, "sem prévia, a carga em segundo plano não busca nada");
});

test("CSV na prévia exporta o recorte completo, com fórmulas neutralizadas", async () => {
  const conjunto = conjuntoPL(50, (linha, j) => {
    if (j === 0) Object.assign(linha, { e: "=1+1", r: "@SOMA(A1)" });
    if (j === 1) Object.assign(linha, { e: "+cmd", r: "-2" });
    if (j === 2) linha.e = "\tTabulação";
  });
  const app = iniciarPrevia({ conjunto });
  await assentar();
  const arquivo = await app.csv();
  await assentar();
  assert.equal(arquivo.nome, "radar-vereadores-projetos.csv");
  assert.equal(arquivo.texto.split("\n").length, 51);
  assert.match(arquivo.texto, /"'=1\+1","'@SOMA\(A1\)"/);
  assert.match(arquivo.texto, /"'\+cmd","'-2"/);
  assert.match(arquivo.texto, /"'\tTabulação"/);
  assert.match(arquivo.texto, /"Ementa do projeto 3","Resumo 3"/);
  assert.equal(itens(app), 40, "o CSV não redesenha a lista");
});

test("com consulta, projetos ignoram a prévia e escondem as contagens do build até calcular", async () => {
  const conjunto = conjuntoPL(50);
  const app = iniciar({ query: "?desfecho=lei", manifesto: manifestoPara("previa-1", conjunto), total: 50, resumoInicial: RESUMO,
    buscar: (url) => resposta(url, "previa-1", conjunto) });
  assert.deepEqual(app.requisicoes.map((r) => r.url), ["dados/dic-pl.json?v=previa-1", "dados/pl-lei.json?v=previa-1"]);
  assert.deepEqual(app.contadores.map((c) => c.textContent), ["", "", "", "", ""]);
  assert.match(app.elementos["resumo-filtro"].innerHTML, /Carregando/);
  await assentar();
  assert.match(app.elementos["resumo-filtro"].innerHTML, /<b>17<\/b> projetos/);
});

test("prévia de outro build volta ao caminho normal e conta com os dados completos", async () => {
  const conjunto = conjuntoPL(50), novo = manifestoPara("novo-build", conjunto);
  const app = iniciar({ manifesto: manifestoPara("previa-1", conjunto), total: 50, resumoInicial: RESUMO, buscar: (url) => {
    if (url === "dados/manifest.json") return { ok: true, status: 200, json: async () => novo };
    return url.endsWith("?v=novo-build") ? resposta(url, "novo-build", conjunto) : { status: 404, ok: false };
  } });
  await assentar();
  assert.match(app.elementos["resumo-filtro"].innerHTML, /^<p class="contagem"><b>50<\/b> projetos/);
  assert.ok(app.requisicoes.some((r) => r.url === novo.arquivos["pl-sem_exito"].url));
  assert.equal(itens(app), 40);
});

// -------------------------------------------------------------- autoria
function conjuntoAutoria() {
  const conjunto = copiar(fixture), leis = conjunto.fatias[0].colunas;
  // Rodrigo é principal no PL 8/2025, coautor no PL 1/2025 e não assina os demais.
  leis.pr = [3, 4];
  leis.au = [[3, 4], [3, 4]];
  return conjunto;
}

for (const modo of ["leis", "projetos"]) {
  test(modo + ": autor acrescentado pelo substitutivo recebe crédito só nos modos de coautoria", async () => {
    const conjunto = copiar(fixture), leis = conjunto.fatias[0].colunas;
    const daniel = conjunto.dic.pessoas.findIndex((p) => p[0] === "daniel-marques-frederico");
    const milton = conjunto.dic.pessoas.push(["milton-carlos-da-silva-lopes", "Cal", { "2021-2024": "PY" }]) - 1;
    conjunto.dic.n = conjunto.dic.pessoas.length;
    // Como no modelo: Daniel assina o PL; Milton, só o substitutivo que virou lei.
    Object.assign(leis, { n: ["140/2021", leis.n[1]], pr: [daniel, leis.pr[1]], au: [[daniel, milton], leis.au[1]],
      ls: [266596, null] });
    const app = iniciar({ modo, query: "?autor=milton-carlos-da-silva-lopes" + (modo === "projetos" ? "&desfecho=lei" : ""),
      manifesto: manifestoPara(fixture.dic.build, conjunto),
      buscar: (url) => resposta(url, fixture.dic.build, conjunto) });
    await assentar();
    assert.equal(app.elementos.csv.disabled, false, "o conjunto com o novo coautor deve carregar sem erro de manifesto");
    assert.equal(itens(app), 0, "o coautor do substitutivo não vira autor principal do PL");
    for (const valor of ["1", "so"]) {
      app.alterar("f-coautor", valor);
      await assentar();
      assert.equal(itens(app), 1);
      assert.match(app.elementos.resultados.innerHTML, /PL 140\/2021/);
      assert.match(app.elementos.resultados.innerHTML, /chip-principal[^>]+daniel-marques-frederico/);
      assert.match(app.elementos.resultados.innerHTML, /<div class="autoria">[^]*?<details class="coautores"><summary>e 1 coautor<\/summary><ul><li>Cal<\/li><\/ul><\/details>[^]*?<\/div>/);
      assert.doesNotMatch(app.elementos.resultados.innerHTML, /<p class="autoria">|title="Cal"/);
      assert.match(app.elementos.resultados.innerHTML, /via substitutivo/);
      const arquivo = await app.csv();
      assert.equal(arquivo.texto.split("\n").length, 2);
      assert.match(arquivo.texto, /Daniel Marques; Cal/);
    }
    app.alterar("f-autor", "daniel-marques-frederico");
    app.alterar("f-coautor", "");
    await assentar();
    assert.equal(itens(app), 1, "a autoria principal do PL continua recebendo o crédito");
  });

  test(modo + ": autoria principal, incluir e apenas coautoria filtram lista, totais e CSV", async () => {
    const conjunto = conjuntoAutoria();
    const app = iniciar({ modo, query: "?autor=rodrigo-flach-farah", buscar: (url) => resposta(url, fixture.dic.build, conjunto) });
    await assentar();
    assert.equal(app.elementos["f-coautor"].disabled, false);
    for (const [valor, numeros] of [["", ["8/2025"]], ["1", ["8/2025", "1/2025"]], ["so", ["1/2025"]]]) {
      app.alterar("f-coautor", valor);
      await assentar();
      assert.equal(itens(app), numeros.length);
      assert.match(app.elementos["resumo-filtro"].innerHTML, new RegExp("<b>" + numeros.length + "</b>"));
      const url = new URLSearchParams(app.enderecos.at(-1).split("?")[1]);
      assert.equal(url.get("coautor"), valor || null);
      const arquivo = await app.csv();
      assert.equal(arquivo.texto.split("\n").length, numeros.length + 1);
      for (const numero of ["8/2025", "1/2025"]) {
        assert.equal(app.elementos.resultados.innerHTML.includes("PL " + numero), numeros.includes(numero));
        assert.equal(arquivo.texto.includes('"' + numero + '"'), numeros.includes(numero));
      }
    }
  });

  test(modo + ": URLs antigas coautor=1 funcionam e limpar o vereador desativa e remove coautor", async () => {
    const conjunto = conjuntoAutoria();
    for (const [valor, n] of [["1", 2], ["so", 1]]) {
      const app = iniciar({ modo, query: "?autor=rodrigo-flach-farah&coautor=" + valor,
        buscar: (url) => resposta(url, fixture.dic.build, conjunto) });
      await assentar();
      assert.equal(app.elementos["f-coautor"].value, valor);
      assert.equal(app.elementos["f-coautor"].disabled, false);
      assert.equal(itens(app), n);
      app.alterar("f-autor", "");
      assert.equal(app.elementos["f-coautor"].value, "");
      assert.equal(app.elementos["f-coautor"].disabled, true);
      assert.doesNotMatch(app.enderecos.at(-1), /coautor|autor=/);
      await assentar();
      assert.equal(itens(app), modo === "leis" ? 2 : 4);
      app.alterar("f-autor", "rodrigo-flach-farah");
      assert.equal(app.elementos["f-coautor"].disabled, false);
      assert.equal(app.elementos["f-coautor"].value, "");
      app.alterar("f-coautor", "so");
      app.limpar();
      assert.equal(app.elementos["f-coautor"].disabled, true);
      assert.equal(app.elementos["f-coautor"].value, "");
      assert.doesNotMatch(app.enderecos.at(-1), /coautor|autor=/);
      await assentar();
    }
  });

  test(modo + ": coautor sem vereador é descartado, inclusive ao abrir uma URL", async () => {
    const app = iniciar({ modo, query: "?coautor=so" });
    assert.equal(app.elementos["f-coautor"].disabled, true);
    assert.equal(app.elementos["f-coautor"].value, "");
    assert.equal(app.enderecos[0], modo + ".html");
    await assentar();
  });

  test(modo + ": PLs abrem em nova aba com aviso acessível, situação e data da lei", async () => {
    for (const [tipo, rotulo] of [["sancionada", "Sancionada"], ["promulgada_camara", "Promulgada pela Câmara"], ["veto_derrubado", "Veto derrubado"]]) {
      const conjunto = copiar(fixture);
      conjunto.fatias[0].colunas.lt[0] = tipo;
      conjunto.fatias[0].colunas.vp[0] = 1;
      conjunto.fatias[0].colunas.ld[0] = null;
      const app = iniciar({ modo, buscar: (url) => resposta(url, fixture.dic.build, conjunto) });
      await assentar();
      const html = app.elementos.resultados.innerHTML;
      assert.match(html, /<a href="https:\/\/consultaniteroi\.siscam\.com\.br\/DetalhesDocumentos\.aspx\?IdDocumento=275604" target="_blank" rel="noopener">PL 8\/2025<span class="so-leitor"> \(abre em nova aba\)<\/span><\/a>/);
      assert.ok(html.includes(rotulo + " · Veto parcial"));
      assert.match(html, /data não informada/);
      assert.match(html, /08\/04\/2025/);
      assert.match(html, /<a class="chip chip-principal" href="vereadores\/sylvio-mauricio-de-freitas\.html">/);
      assert.doesNotMatch(html, /href="vereadores\/[^\"]+" target=/);
    }
  });

  test(modo + ": lei via substitutivo leva à página do substitutivo, e o número, ao PL original", async () => {
    const conjunto = copiar(fixture);
    conjunto.fatias[0].colunas.ls[0] = 266596;
    const app = iniciar({ modo, buscar: (url) => resposta(url, fixture.dic.build, conjunto) });
    await assentar();
    const html = app.elementos.resultados.innerHTML;
    assert.match(html, /<a href="https:\/\/consultaniteroi\.siscam\.com\.br\/DetalhesDocumentos\.aspx\?IdDocumento=275604" target="_blank" rel="noopener">PL 8\/2025/);
    assert.ok(html.includes('Sancionada <a class="via-substitutivo" href="https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento=266596" ' +
      'target="_blank" rel="noopener">via substitutivo<span class="so-leitor"> (substitutivo ao PL 8/2025)</span>' +
      '<span class="so-leitor"> (abre em nova aba)</span></a>'));
    assert.equal((html.match(/via substitutivo/g) || []).length, 1, "só a lei com substitutivo recebe a marca");
    assert.ok(html.includes('data-url="https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento=275604"'),
      "os botões do SISCAM continuam no PL original");
  });
}
