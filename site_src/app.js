(function () {
  "use strict";

  // ---------- página inicial: abas de legislatura, ordenação, filtro de eleitos
  const abas = document.querySelectorAll(".abas button");
  const ordem = document.getElementById("ordem");
  const soEleitos = document.getElementById("so-eleitos");

  function legislaturaAtiva() {
    return document.querySelector(".legislatura:not([hidden])");
  }

  function aplicar() {
    const sec = legislaturaAtiva();
    if (!sec) return;
    const lista = sec.querySelector(".placar");
    const linhas = Array.from(lista.children);
    const chave = ordem ? ordem.value : "leis-substantivas";
    linhas.sort(function (a, b) {
      if (chave === "nome") return a.dataset.nome.localeCompare(b.dataset.nome, "pt-BR");
      const d = Number(b.dataset[camel(chave)]) - Number(a.dataset[camel(chave)]);
      return d !== 0 ? d : Number(b.dataset.leis) - Number(a.dataset.leis) || a.dataset.nome.localeCompare(b.dataset.nome, "pt-BR");
    });
    linhas.forEach(function (li) {
      li.hidden = !!(soEleitos && soEleitos.checked && li.dataset.eleito !== "1");
      lista.appendChild(li);
    });
  }

  function camel(s) {
    return s.replace(/-([a-z])/g, function (_, c) { return c.toUpperCase(); });
  }

  abas.forEach(function (bt) {
    bt.addEventListener("click", function () {
      abas.forEach(function (b) { b.setAttribute("aria-selected", b === bt ? "true" : "false"); });
      document.querySelectorAll(".legislatura").forEach(function (s) { s.hidden = s.id !== bt.dataset.alvo; });
      aplicar();
    });
  });
  if (ordem) ordem.addEventListener("change", aplicar);
  if (soEleitos) soEleitos.addEventListener("change", aplicar);

  // ---------- página de projetos: busca no cliente
  const resultados = document.getElementById("resultados");
  if (!resultados) return;
  const q = document.getElementById("q");
  const fDesf = document.getElementById("f-desfecho");
  const fCat = document.getElementById("f-categoria");
  const fAno = document.getElementById("f-ano");
  const fAlerta = document.getElementById("f-alerta");
  const contagem = document.getElementById("contagem");
  const mais = document.getElementById("mais");
  let dados = [];
  let filtrados = [];
  let mostrando = 0;
  const PASSO = 50;

  function norm(s) {
    return (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function dataBr(d) {
    if (!d) return "—";
    const p = d.split("-");
    return p[2] + "/" + p[1] + "/" + p[0];
  }

  function itemHtml(p) {
    const autores = p.au.map(function (a) {
      return '<a href="vereadores/' + esc(a[1]) + '.html">' + esc(a[0]) + "</a>" + (a[2] && p.au.length > 1 ? " (autor)" : "");
    }).join(", ");
    const alertas = p.al.map(function (a) {
      const origem = a[1] === "curadoria" ? "curadoria" : "IA " + Math.round((a[2] || 0) * 100) + "%";
      return '<span class="tag alerta" title="' + esc(a[3]) + '">' + esc(a[0]) + "<small>" + origem + "</small></span>";
    }).join("");
    const sinais = p.s.map(function (s) { return '<span class="tag sinal">' + esc(s) + "</span>"; }).join("");
    return '<li class="projeto d-' + esc(p.g) + '"><p class="cab"><a href="' + esc(p.u) + '">PL ' + esc(p.n) + "</a> <span>" + dataBr(p.d) +
      '</span> <span class="desfecho">' + esc(p.dx) + (p.l ? " · Lei " + esc(p.l) : "") + '</span> <span class="cat">' + esc(p.cx) +
      '</span></p><p class="ementa">' + esc(p.e) + '</p><p class="autoria">' + autores + "</p>" +
      (alertas || sinais ? '<p class="tags">' + alertas + sinais + "</p>" : "") + "</li>";
  }

  function filtrar() {
    const termo = norm(q.value.trim());
    filtrados = dados.filter(function (p) {
      if (fDesf.value && p.g !== fDesf.value) return false;
      if (fCat.value && p.c !== fCat.value) return false;
      if (fAno.value && String(p.a) !== fAno.value) return false;
      if (fAlerta.checked && !p.al.length) return false;
      if (!termo) return true;
      return p._busca.indexOf(termo) !== -1;
    });
    mostrando = 0;
    resultados.innerHTML = "";
    renderizar();
  }

  function renderizar() {
    const fatia = filtrados.slice(mostrando, mostrando + PASSO);
    resultados.insertAdjacentHTML("beforeend", fatia.map(itemHtml).join(""));
    mostrando += fatia.length;
    contagem.textContent = filtrados.length + (filtrados.length === 1 ? " projeto encontrado" : " projetos encontrados");
    mais.hidden = mostrando >= filtrados.length;
  }

  fetch("dados/projetos.json").then(function (r) { return r.json(); }).then(function (json) {
    dados = json;
    dados.forEach(function (p) {
      p._busca = norm([p.n, p.e, p.au.map(function (a) { return a[0]; }).join(" "), p.l || ""].join(" "));
    });
    const anos = Array.from(new Set(dados.map(function (p) { return p.a; }))).sort().reverse();
    fAno.insertAdjacentHTML("beforeend", anos.map(function (a) { return '<option value="' + a + '">' + a + "</option>"; }).join(""));
    const params = new URLSearchParams(location.search);
    if (params.get("q")) q.value = params.get("q");
    filtrar();
  }).catch(function () {
    contagem.textContent = "Não foi possível carregar os projetos. Recarregue a página.";
  });

  let espera;
  q.addEventListener("input", function () { clearTimeout(espera); espera = setTimeout(filtrar, 150); });
  [fDesf, fCat, fAno, fAlerta].forEach(function (el) { el.addEventListener("change", filtrar); });
  mais.addEventListener("click", renderizar);
})();
