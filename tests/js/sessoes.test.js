"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const zlib = require("node:zlib");
const S = require("../../site_src/sessoes.js");
const RadarDados = require("../../site_src/dados.js");
const fixture = require("./fixtures/sessoes.json");
const fonte = fs.readFileSync(path.join(__dirname, "../../site_src/sessoes.js"), "utf8");
const app = fs.readFileSync(path.join(__dirname, "../../site_src/app.js"), "utf8");
const copiar = (x) => JSON.parse(JSON.stringify(x));
const legs = [{ ...fixture.leg, pessoas: ["ana", "bia"] }, { id: "2021-2024", anos: [2021, 2022, 2023, 2024], pessoas: ["caio"] }];
const dados = () => S.hidratar(fixture.dic, copiar(fixture.fatia));
const estado = (extra = {}) => ({ ...S.padrao(legs[0].id), ...extra });
const ids = (lista) => lista.map((v) => v.id);
const assentar = () => new Promise((resolve) => setImmediate(resolve));

test("URL valida e faz ida e volta; padrões não entram no endereço", () => {
  const st = S.lerUrl("?leg=2021-2024&ano=2022&classe=dissenso&materia=veto&vereador=caio&div=1&q=Sa%C3%BAde&ordem=apertada", legs);
  assert.deepEqual(st, { leg: "2021-2024", ano: "2022", classe: "dissenso", materia: "veto", vereador: "caio", div: "1", q: "Saúde", ordem: "apertada" });
  assert.deepEqual(S.lerUrl(S.consultaUrl(st, legs), legs), st);
  assert.equal(S.consultaUrl(S.padrao(legs[0].id), legs), "");
  assert.equal(S.consultaUrl(estado({ ano: "todos", classe: "dividida", materia: "todas", ordem: "recente" }), legs), "");
  assert.deepEqual(S.lerUrl("?leg=invalida&ano=2022&classe=x&materia=x&ordem=x&div=1&vereador=desconhecido", legs), estado());
  assert.equal(S.lerUrl("?div=1", legs).div, "");
  assert.equal(S.lerUrl("?vereador=ana&div=1&ano=2025", legs).div, "1");
  assert.equal(S.lerUrl("?ano=2027", legs).ano, "todos");
});

test("hidratação decodifica v pela posição local da pessoa, distinguindo ausência, I e ponto", () => {
  const lista = dados();
  assert.deepEqual(ids(lista), ["12-3", "11-2", "10-1"]);
  assert.equal(lista[0].votos.ana, "Ausente");
  assert.equal(lista[0].votos.bia, undefined);
  assert.equal(S.rotulo(fixture.dic, lista[0], "bia"), "fora do mandato/não consta");
  assert.equal(lista[1].votos.bia, "Presidente");
  assert.equal(lista[2].url_documento, fixture.dic.url_detalhe + "101");
  assert.equal(lista[0].url_documento, "");
  const f = copiar(fixture.fatia);
  f.colunas.v[0] = "IB";
  assert.equal(S.hidratar(fixture.dic, f)[0].votos.ana, "indeterminado");
  assert.equal(S.hidratar(fixture.dic, f)[0].votos.bia, "Branco");
  f.colunas.v[0] = "F";
  assert.throws(() => S.hidratar(fixture.dic, f), /desalinhados/);
  f.colunas.v[0] = "F?";
  assert.throws(() => S.hidratar(fixture.dic, f), /desconhecido/);
  delete f.colunas.nt;
  assert.throws(() => S.hidratar(fixture.dic, f), /Coluna inválida: nt/);
  assert.throws(() => S.hidratar({ ...fixture.dic, esquema: 2 }, fixture.fatia), /Esquema/);
});

test("todos os rótulos vêm de dic-ses, sem reinterpretar Favor e Contra", () => {
  for (const [materia, sentidos] of Object.entries(fixture.dic.rotulos)) {
    for (const [sentido, rotulos] of Object.entries(sentidos)) {
      fixture.dic.votos.slice(0, 7).forEach(([, voto], i) => {
        const v = { ...dados()[2], materia, sentido, qualidade: "ok", votos: { ana: voto } };
        assert.equal(S.rotulo(fixture.dic, v, "ana"), rotulos[i]);
      });
    }
  }
  assert.match(S.rotulo(fixture.dic, { ...dados()[2], qualidade: "inconsistente" }, "ana"), /sem atribuição nominal/);
});

test("filtros de classe, matéria, ano, vereador, divergência e busca sem acento", () => {
  const lista = dados().concat([{ ...dados()[2], id: "20-4", ano: 2026, data: "2026-01-01", classe: "dissenso" }]);
  assert.deepEqual(ids(S.filtrar(lista, estado())), ["12-3", "11-2", "10-1"]);
  assert.deepEqual(ids(S.filtrar(lista, estado({ classe: "dissenso" }))), ["20-4"]);
  assert.equal(S.filtrar(lista, estado({ classe: "todas" })).length, 4);
  assert.deepEqual(ids(S.filtrar(lista, estado({ materia: "veto" }))), ["11-2"]);
  assert.deepEqual(ids(S.filtrar(lista, estado({ ano: "2026", classe: "todas" }))), ["20-4"]);
  assert.deepEqual(ids(S.filtrar(lista, estado({ vereador: "bia" }))), ["11-2", "10-1"]);
  assert.deepEqual(ids(S.filtrar(lista, estado({ vereador: "bia", div: "1" }))), ["10-1"]);
  assert.equal(S.filtrar(lista, estado({ vereador: "ana", div: "1" })).length, 0);
  assert.equal(S.filtrar(lista, estado({ q: "FISCALIZACAO DA SAUDE" })).length, 3);
  assert.deepEqual(ids(S.filtrar(lista, estado({ q: "Veto Mantido" }))), ["11-2"]);
  assert.equal(S.filtrar(lista, estado({ q: "não existe" })).length, 0);
  const incerto = { ...dados()[2], qualidade: "indeterminado" };
  assert.equal(S.filtrar([incerto], estado({ vereador: "bia", div: "1" })).length, 0);
  assert.equal(S.filtrar([{ ...incerto, qualidade: "inconsistente" }], estado({ vereador: "bia" })).length, 0);
});

test("ordenações são estáveis e não alteram a lista; apertada usa margem Favor/Contra", () => {
  const lista = dados(), antes = copiar(lista);
  assert.deepEqual(ids(S.filtrar(lista, estado({ ordem: "antigo" }))), ["10-1", "11-2", "12-3"]);
  assert.deepEqual(ids(S.filtrar(lista, estado({ ordem: "apertada" }))), ["12-3", "11-2", "10-1"]);
  const inc = { ...lista[0], id: "inc", qualidade: "inconsistente" };
  assert.equal(S.filtrar([inc, ...lista], estado({ ordem: "apertada" })).at(-1).id, "inc");
  assert.equal(JSON.stringify(lista), JSON.stringify(antes));
});

test("faixa de outro ano tem paridade byte a byte com a tabela conferida pelo Python", () => {
  const html = S.faixa(dados(), fixture.membros.slice().reverse(), fixture.leg, 2025, "");
  const esperada = fs.readFileSync(path.join(__dirname, "fixtures/faixa_sessoes.html"), "utf8").trim();
  assert.equal(html.match(/<table class="faixa">.*?<\/table>/s)[0], esperada);
  assert.match(html, /role="region" tabindex="0" aria-label="Mapa de votos de 2025/);
  assert.match(html, /Resumo por vereador · votações divididas de 2025/);
  assert.match(S.faixa(dados(), fixture.membros, fixture.leg, 2025, "bia"), /data-vereador="bia" class="vereador-destaque"/);
  assert.match(S.faixa(dados(), fixture.membros, fixture.leg, 2026, ""), /Nenhuma votação dividida/);
});

test("glifos da faixa preservam texto, presidência, branco, nulo e limitação de comparação", () => {
  const v = dados()[2];
  for (const [voto, esperado] of [
    ["Favor", ["maioria", "■", "com a maioria"]], ["Contra", ["diferente", "◆", "diferente da maioria"]],
    ["Abstenção", ["abstencao", "◐", "abstenção"]], ["Ausente", ["ausente", "·", "ausente"]],
    ["Presidente", ["presidia", "P", "presidia"]], ["Branco", ["cru", "Branco", "Branco"]], ["Nulo", ["cru", "Nulo", "Nulo"]]
  ]) assert.deepEqual(S.votoFaixa({ ...v, votos: { ana: voto } }, "ana"), esperado);
  assert.deepEqual(S.votoFaixa(v, "caio"), ["vazio", "", "fora do mandato/não consta"]);
  assert.deepEqual(S.votoFaixa({ ...v, qualidade: "inconsistente" }, "ana"), ["cru", "—", "placar inconsistente; sem atribuição nominal"]);
});

test("cartões espelham classes, rótulos, notas, ações e escape, sem nomes em inconsistentes", () => {
  const v = dados()[2], html = S.cartao(fixture.dic, v, "bia");
  for (const classe of ["cab", "desfecho", "ementa", "mini-barra", "mini-n", "votos-nomes", "grupo-votos", "ver-siscam", "abrir-siscam", "contestar", "voto-pessoal"]) assert.ok(html.includes(classe));
  assert.match(html, /<li class="projeto votacao" id="v-10-1" data-ano="2025" data-materia="pl" data-classe="dividida" data-sentido="favor_aprova" data-qualidade="ok"/);
  assert.match(html, /votou contra o projeto/);
  assert.match(html, /Fiscalização da saúde &amp; educação/);
  assert.match(html, /11 a favor do projeto · 6 contra o projeto/);
  const veto = { ...dados()[1], sentido: "favor_mantem", qualidade: "ok", quorum: [11, 7, 10], notas: ["Derrubar o veto exige 11 votos (maioria absoluta dos 21 vereadores); houve 7.", "Sentido definido pelo texto do parecer na tramitação.", "Quórum <conferir>"] };
  const cartao = S.cartao(fixture.dic, veto, "");
  assert.match(cartao, /class="nota quorum"/);
  assert.match(cartao, /class="nota fonte-sentido"/);
  assert.match(cartao, /ⓘ Quórum &lt;conferir&gt;/);
  assert.match(cartao, /10 para manter · 7 para derrubar · 3 abstenções/);
  const inconsistente = S.cartao(fixture.dic, { ...v, qualidade: "inconsistente", totais_oficiais: [99, 1, 0, 0, 0, 0] }, "");
  assert.match(inconsistente, /Placar oficial: 99 Favor ao parecer/);
  assert.doesNotMatch(inconsistente, /Ana Souza|Bia Suplente|Como votou/);
  const perigoso = S.cartao(fixture.dic, { ...v, documento: '<img onerror="x">', ementa: "<script>texto</script>", notas: ["<b>nota</b>"] }, "");
  assert.doesNotMatch(perigoso, /<img|<script>|<b>nota/);
  assert.match(perigoso, /&lt;script&gt;/);
});

test("CSV tem BOM, pessoa × votação, escape e fórmulas neutralizadas; não atribui inconsistentes", () => {
  assert.equal(S.celulaCsv('Texto, "aspas"\nlinha'), '"Texto, ""aspas""\nlinha"');
  for (const formula of ["=1+1", "+cmd", "-2", "@SOMA(A1)", "\tTabulação", "\rRetorno"]) assert.equal(S.celulaCsv(formula), '"\'' + formula + '"');
  const lista = dados(), txt = S.csv(fixture.dic, lista);
  assert.equal(txt.charCodeAt(0), 0xfeff);
  assert.equal(txt.split("\n").length, 7);
  assert.match(txt, /"data","sessao","documento","resultado","classe","vereador","voto","rotulo"/);
  assert.match(txt, /"Bia Suplente","não consta","fora do mandato\/não consta"/);
  assert.match(txt, /"Favor","votou a favor do projeto"/);
  const malicioso = { ...lista[2], documento: "=1+1", resultado: '@SOMA("A1")' };
  assert.match(S.csv(fixture.dic, [malicioso]), /"'=1\+1"/);
  assert.match(S.csv(fixture.dic, [{ ...lista[2], qualidade: "inconsistente" }]), /"Ana Souza","","placar inconsistente; sem atribuição nominal"/);
});

test("Mostrar mais trabalha em passos de 40 sem duplicar nem alterar a entrada; orçamento gzip", () => {
  const lista = Array.from({ length: 95 }, (_, i) => i);
  assert.equal(S.PASSO, 40);
  assert.deepEqual([...S.paginar(lista, 0), ...S.paginar(lista, 40), ...S.paginar(lista, 80)], lista);
  assert.equal(S.paginar(lista, 95).length, 0);
  assert.ok(zlib.gzipSync(fonte).length <= 12 * 1024);
});

// DOM mínimo para executar os dois scripts reais, sem navegador, rede nem dependências.
function iniciar({ query = "", numero = 3, falhar = false, semVotos = false } = {}) {
  function el(extra = {}) {
    return { value: "", checked: false, hidden: false, disabled: false, dataset: {}, eventos: {}, innerHTML: "", textContent: "",
      addEventListener(k, fn) { this.eventos[k] = fn; }, setAttribute(k, v) { this[k] = v; },
      insertAdjacentHTML(_, html) { this.innerHTML += html; }, ...extra };
  }
  const formulario = el({ dataset: { leg: "2025-2028" }, hidden: true });
  formulario.elements = Object.fromEntries(Object.entries(estado()).filter(([k]) => k !== "leg").map(([k, value]) => [k, el({ value })]));
  formulario.elements.ano.options = ["todos", "2026", "2025"].map((value) => ({ value }));
  formulario.elements.vereador.options = ["", "ana", "bia"].map((value) => ({ value }));
  formulario.querySelectorAll = () => [];
  const botaoCsv = el({ dataset: { acao: "csv" } }), mais = el({ hidden: true, dataset: { acao: "mais" } });
  formulario.querySelector = () => botaoCsv;
  const lista = el({ innerHTML: "Cartões do servidor" }), contador = el(), bloco = el(), mapa = el({ dataset: { ano: "2026" }, innerHTML: "Mapa do servidor" });
  const linhas = fixture.membros.map((p) => {
    const a = p.pagina ? { textContent: p.nome } : null, status = p.condicao ? { textContent: p.condicao } : null;
    const th = { textContent: p.nome + p.condicao, querySelector: (q) => q === "a" ? a : status };
    return { dataset: { vereador: p.slug }, querySelector: () => th, classList: { toggle(_, ativo) { this.destacado = ativo; } } };
  });
  mapa.querySelectorAll = () => linhas;
  const continuacao = el({ remove() { this.removido = true; } });
  const secao = el();
  secao.querySelector = (q) => q === '[data-acao="mais"]' ? mais : q === ".mais-votacoes" && numero > 40 ? continuacao : null;
  secao.querySelectorAll = () => Array.from({ length: numero }, (_, i) => ({ dataset: { materia: i === 1 ? "veto" : "pl" } }));
  const fatia2026 = copiar(fixture.fatia);
  fatia2026.ano = 2026;
  fatia2026.colunas.d = fatia2026.colunas.d.map((d) => d.replace("2025", "2026"));
  const arquivos = { "dic-ses": fixture.dic, "vot-2025": copiar(fixture.fatia), "vot-2026": fatia2026 };
  if (numero > 3) {
    for (const [nome, f] of Object.entries(arquivos)) {
      if (!nome.startsWith("vot-")) continue;
      const base = copiar(f.colunas);
      f.n = numero;
      for (const k of Object.keys(base)) f.colunas[k] = Array.from({ length: numero }, (_, i) => k === "id" ? nome + "-" + i : copiar(base[k][2]));
    }
  }
  const manifesto = { esquema: 2, build: "fixture", arquivos: Object.fromEntries(Object.entries(arquivos).map(([nome, f]) =>
    [nome, { familia: nome === "dic-ses" ? "dic-ses" : "vot", ano: f.ano, n: f.n === undefined ? f.materias.length : f.n, url: "dados/" + nome + ".json?v=fixture" }])) };
  if (semVotos) manifesto.arquivos = {};
  const elementos = { conteudo: el(), "manifesto-dados": el({ textContent: JSON.stringify(manifesto) }),
    "sessoes-leg-2025-2028": bloco, "divididas-2025-2028": secao, "lista-votacoes-2025-2028": lista,
    "contagem-votacoes-2025-2028": contador, "faixa-2025-2028": mapa };
  const requisicoes = [], urls = [];
  let blob, nomeCsv;
  const document = {
    getElementById: (id) => elementos[id] || null,
    querySelector: (q) => q === "form.filtros" || q === "form.filtros-sessoes" ? formulario : null,
    querySelectorAll: (q) => q === "form.filtros-sessoes" ? [formulario] : [],
    createElement: () => ({ click() { nomeCsv = this.download; } })
  };
  const window = { document, RadarDados, location: { pathname: "/sessoes.html", search: query, hash: "" },
    history: { replaceState(_, __, url) { urls.push(url); } }, Blob,
    URL: { createObjectURL(b) { blob = b; return "blob:csv"; }, revokeObjectURL() {} },
    setTimeout: (fn) => setImmediate(fn), clearTimeout: clearImmediate };
  const contexto = { document, window, URLSearchParams, fetch: async (url) => {
    requisicoes.push(url);
    if (falhar) return { ok: false, status: 500 };
    if (url === "dados/manifest.json") return { ok: true, json: async () => manifesto };
    const nome = url.split("/").pop().split(".json")[0];
    return arquivos[nome] ? { ok: true, status: 200, json: async () => copiar(arquivos[nome]) } : { ok: false, status: 404 };
  } };
  vm.runInNewContext(app, contexto, { filename: "app.js" });
  vm.runInNewContext(fonte, contexto, { filename: "sessoes.js" });
  return { formulario, lista, contador, mapa, mais, linhas, continuacao, botaoCsv, requisicoes, urls,
    alterar(k, value) { formulario.elements[k].value = value; formulario.eventos.change(); },
    clicar(acao) { secao.eventos.click({ target: { closest: () => acao === "mais" ? mais : acao === "csv" ? botaoCsv : { dataset: { acao } } } }); },
    async csv() { this.clicar("csv"); await assentar(); return { nome: nomeCsv, texto: blob ? await blob.text() : null }; }
  };
}

test("VM: guarda do app, formulário progressivo, carga padrão só dic + ano recente e HTML preservado", async () => {
  const tela = iniciar();
  await assentar();
  assert.equal(tela.formulario.hidden, false);
  assert.equal(tela.formulario.elements.div.disabled, true);
  assert.deepEqual(tela.requisicoes, ["dados/dic-ses.json?v=fixture", "dados/vot-2026.json?v=fixture"]);
  assert.equal(tela.lista.innerHTML, "Cartões do servidor");
  assert.equal(tela.mapa.innerHTML, "Mapa do servidor");
  assert.equal(tela.contador.textContent, "3 votações · 1 veto · 2 projetos de lei");
});

test("VM: ano redesenha faixa; vereador destaca linha, rotula cartão e div depende da seleção", async () => {
  const tela = iniciar({ query: "?ano=2025&vereador=bia" });
  await assentar();
  assert.equal(tela.mapa.dataset.ano, "2025");
  assert.match(tela.mapa.innerHTML, /<table class="faixa">/);
  assert.match(tela.lista.innerHTML, /voto-pessoal/);
  assert.match(tela.lista.innerHTML, /votou contra o projeto/);
  assert.equal(tela.linhas[1].classList.destacado, true);
  assert.equal(tela.formulario.elements.div.disabled, false);
  tela.formulario.elements.div.checked = true;
  tela.alterar("vereador", "");
  await assentar();
  assert.equal(tela.formulario.elements.div.checked, false);
  assert.equal(tela.formulario.elements.div.disabled, true);
  assert.doesNotMatch(tela.urls.at(-1), /div=1/);
  tela.alterar("ano", "todos");
  await assentar();
  assert.equal(tela.mapa.innerHTML, "Mapa do servidor");
  assert.equal(tela.mapa.dataset.ano, "2026");
  assert.equal(tela.requisicoes.length, 3, "cache compartilhado reutiliza dicionário e anos já carregados");
});

test("VM: Mostrar mais acrescenta 40, CSV inicial baixa no primeiro clique e vazio oferece limpar", async () => {
  const tela = iniciar({ numero: 95, query: "?ano=2025" });
  await assentar();
  const contar = () => (tela.lista.innerHTML.match(/<li class="projeto votacao"/g) || []).length;
  assert.equal(contar(), 40);
  tela.clicar("mais");
  assert.equal(contar(), 80);
  tela.clicar("mais");
  assert.equal(contar(), 95);
  assert.equal(tela.mais.hidden, true);
  assert.match(tela.contador.textContent, /mostrando 95 de 95/);
  tela.alterar("q", "inexistente");
  await assentar();
  assert.match(tela.lista.innerHTML, /Nenhuma votação.*data-acao="limpar"/);
  tela.clicar("limpar");
  await assentar();
  assert.equal(tela.formulario.elements.q.value, "");
  const inicial = iniciar();
  await assentar();
  const csv = await inicial.csv();
  assert.equal(csv.nome, "radar-vereadores-votacoes.csv");
  assert.match(csv.texto, /"data","sessao"/);
  assert.ok(inicial.requisicoes.includes("dados/vot-2025.json?v=fixture"));
});

test("VM: falha de dados preserva servidor e avisa em aria-live; sem forms não inicializa", async () => {
  const tela = iniciar({ query: "?ano=2025", falhar: true });
  await assentar();
  assert.equal(tela.lista.innerHTML, "Cartões do servidor");
  assert.match(tela.contador.textContent, /Não foi possível carregar/);
  assert.equal(tela.lista["aria-busy"], "false");
  assert.equal(tela.botaoCsv.disabled, true);
  const semVotos = iniciar({ semVotos: true });
  assert.equal(semVotos.formulario.hidden, true);
  assert.equal(semVotos.requisicoes.length, 0);
  const contexto = { window: { document: { querySelectorAll: () => [] } } };
  assert.doesNotThrow(() => vm.runInNewContext(fonte, contexto));
});
