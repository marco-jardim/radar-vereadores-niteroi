(function () {
  "use strict";
  var raiz = document.getElementById("conteudo");
  var prefixo = raiz ? raiz.dataset.prefixo || "" : "";

  // ------------------------------------------------------------- tooltip
  var tip = document.getElementById("tip");
  function mostrarTip(el, x, y) {
    tip.textContent = el.getAttribute("data-tip");
    tip.hidden = false;
    var r = tip.getBoundingClientRect();
    var left = Math.min(window.innerWidth - r.width - 8, Math.max(8, x - r.width / 2));
    var top = y - r.height - 12;
    if (top < 8) top = y + 16;
    tip.style.left = left + "px";
    tip.style.top = top + "px";
  }
  if (tip) {
    document.addEventListener("mousemove", function (ev) {
      var el = ev.target.closest && ev.target.closest("[data-tip]");
      if (el) mostrarTip(el, ev.clientX, ev.clientY);
      else tip.hidden = true;
    });
    document.addEventListener("focusin", function (ev) {
      var el = ev.target.closest && ev.target.closest("[data-tip]");
      if (el) { var r = el.getBoundingClientRect(); mostrarTip(el, r.left + r.width / 2, r.top); }
    });
    document.addEventListener("focusout", function () { tip.hidden = true; });
    document.addEventListener("scroll", function () { tip.hidden = true; }, { passive: true });
  }

  // ----------------------------------------------- placar da página inicial
  var abas = document.querySelectorAll(".abas button");
  var ordem = document.getElementById("ordem");
  var soEleitos = document.getElementById("so-eleitos");
  var partidoPlacar = document.getElementById("f-partido-placar");
  function camel(s) { return s.replace(/-([a-z])/g, function (_, c) { return c.toUpperCase(); }); }

  function aplicarPlacar() {
    var sec = document.querySelector(".legislatura:not([hidden])");
    if (!sec) return;
    var lista = sec.querySelector(".placar");
    var linhas = Array.prototype.slice.call(lista.children);
    var chave = ordem ? ordem.value : "leis-efeito";
    linhas.sort(function (a, b) {
      if (chave === "nome") return a.dataset.nome.localeCompare(b.dataset.nome, "pt-BR");
      var d = Number(b.dataset[camel(chave)]) - Number(a.dataset[camel(chave)]);
      return d !== 0 ? d : Number(b.dataset.leis) - Number(a.dataset.leis) || a.dataset.nome.localeCompare(b.dataset.nome, "pt-BR");
    });
    linhas.forEach(function (li) {
      var esconder = (soEleitos && soEleitos.checked && li.dataset.eleito !== "1") ||
        (partidoPlacar && partidoPlacar.value && li.dataset.partido !== partidoPlacar.value);
      li.hidden = !!esconder;
      lista.appendChild(li);
    });
  }
  abas.forEach(function (bt) {
    bt.addEventListener("click", function () {
      abas.forEach(function (b) { b.setAttribute("aria-selected", b === bt ? "true" : "false"); });
      document.querySelectorAll(".legislatura").forEach(function (s) { s.hidden = s.id !== bt.dataset.alvo; });
      aplicarPlacar();
    });
  });
  [ordem, soEleitos, partidoPlacar].forEach(function (el) { if (el) el.addEventListener("change", aplicarPlacar); });

  // ------------------------------------------------ listas: leis e projetos
  var form = document.querySelector("form.filtros");
  if (!form) return;
  var modo = form.dataset.modo;
  var $ = function (id) { return document.getElementById(id); };
  var resultados = $("resultados"), resumo = $("resumo-filtro"), mais = $("mais");
  var campos = { q: $("q"), ordem: $("f-ordem"), origem: $("f-origem"), autor: $("f-autor"), partido: $("f-partido"),
    tema: $("f-tema"), leg: $("f-leg"), ano: $("f-ano"), desfecho: $("f-desfecho"), sinal: $("f-sinal"), coautor: $("f-coautor") };
  var impactos = Array.prototype.slice.call(form.querySelectorAll('input[name="imp"]'));
  var DADOS = null, filtrados = [], mostrando = 0, PASSO = 40;
  var NOME_IMP = { 3: "Impacto alto", 2: "Impacto médio", 1: "Impacto baixo", 0: "Sem efeito prático" };

  function norm(s) { return (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  var SIGLAS = { sus: 1, cras: 1, creas: 1, caps: 1, pcd: 1, tea: 1, ubs: 1, upa: 1, iptu: 1, iss: 1, ccj: 1, rj: 1, ong: 1, oab: 1, eja: 1 };
  function legivel(t) {
    var letras = (t || "").replace(/[^A-Za-zÀ-ÿ]/g, "");
    if (!letras.length || letras.replace(/[^A-ZÀ-Þ]/g, "").length / letras.length < 0.7) return t;
    var s = t.toLowerCase().replace(/^ementa:\s*/, "").split(" ").map(function (p) {
      var n = p.replace(/[“”"'(),.;:]/g, "");
      if (SIGLAS[n]) return p.replace(n, n.toUpperCase());
      if (n === "niterói" || n === "niteroi") return p.replace(n, "Niterói");
      return p;
    }).join(" ");
    return s.charAt(0).toUpperCase() + s.slice(1);
  }
  function dataBr(d) { if (!d) return "—"; var p = d.split("-"); return p[2] + "/" + p[1] + "/" + p[0]; }
  function chaveImp(p) { return p.c === "simbolica" || p.s.indexOf("autorizativa") >= 0 ? "0" : (p.i === null || p.i === undefined ? "x" : String(p.i)); }

  function selo(p) {
    if (p.c === "simbolica") return '<span class="selo imp-0">Simbólica</span>';
    if (p.s.indexOf("autorizativa") >= 0) return '<span class="selo imp-0">Autorizativa</span>';
    var k = chaveImp(p);
    return '<span class="selo imp-' + k + '">' + (NOME_IMP[k] || "Não avaliado") + "</span>";
  }
  function autores(p) {
    var princ = p.au.filter(function (a) { return a[1] && a[1] === p.pr; });
    if (!princ.length) princ = p.au.slice(0, 1);
    var html = princ.map(function (a) {
      return a[1] ? '<a class="chip chip-principal" href="' + prefixo + "vereadores/" + esc(a[1]) + '.html">' + esc(a[0]) + "</a>"
        : '<span class="chip chip-exec">' + esc(a[0]) + "</span>";
    }).join("");
    var n = p.au.length - princ.length;
    if (n > 0) html += '<span class="coautores" title="' + esc(p.au.filter(function (a) { return princ.indexOf(a) < 0; }).map(function (a) { return a[0]; }).join(", ")) + '">e ' + n + (n === 1 ? " coautor" : " coautores") + "</span>";
    if (p.pt) html += '<span class="partido">' + esc(p.pt) + "</span>";
    return html;
  }
  function tags(p) {
    var t = p.al.map(function (a) {
      return '<span class="tag alerta" title="' + esc(a[2]) + '">' + esc(a[0]) + "<small>" + (a[1] === "curadoria" ? "curadoria" : "IA") + "</small></span>";
    }).join("");
    t += p.s.filter(function (s) { return s !== "autorizativa" && s !== "repete_projeto"; }).map(function (s) {
      return '<span class="tag sinal">' + esc(DADOS.sinais[s] || s) + "</span>";
    }).join("");
    if (p.rp) t += '<span class="tag sinal">Repete o PL ' + esc(p.rp) + "</span>";
    return t ? '<p class="tags">' + t + "</p>" : "";
  }
  function item(p) {
    var lei = p.l ? " · Lei " + esc(p.l) : "";
    var tema = DADOS.temas[p.t] && p.t !== "outro" && p.t !== "homenagem" ? DADOS.temas[p.t] : "";
    var meta = [];
    if (p.pb) meta.push("Afeta: " + esc(p.pb));
    if (tema) meta.push(esc(tema));
    if (modo === "leis" && p.dl !== null && p.dl !== undefined) meta.push(p.dl + " dias até virar lei");
    return '<li class="projeto d-' + esc(p.g) + " imp-borda-" + chaveImp(p) + '">' +
      '<p class="cab"><a href="' + esc(p.u) + '">PL ' + esc(p.n) + "</a><span>" + dataBr(modo === "leis" ? p.ld : p.d) + '</span><span class="desfecho">' + esc(p.dx) + lei + "</span>" + selo(p) + "</p>" +
      (p.r ? '<p class="resumo-ia">' + esc(p.r) + "</p>" : "") +
      '<p class="ementa">' + esc(legivel(p.e)) + "</p>" +
      (meta.length ? '<p class="publico">' + meta.join(" · ") + "</p>" : "") +
      '<p class="autoria">' + autores(p) + "</p>" + tags(p) + "</li>";
  }

  function estado() {
    return {
      q: campos.q.value.trim(), ordem: campos.ordem.value, origem: campos.origem.value, autor: campos.autor.value,
      partido: campos.partido.value, tema: campos.tema.value, leg: campos.leg.value, ano: campos.ano.value,
      desfecho: campos.desfecho ? campos.desfecho.value : "", sinal: campos.sinal ? campos.sinal.value : "",
      coautor: campos.coautor.checked ? "1" : "",
      imp: impactos.filter(function (c) { return c.checked; }).map(function (c) { return c.value; }).join(",")
    };
  }
  function gravarUrl(st) {
    var u = new URLSearchParams();
    Object.keys(st).forEach(function (k) { if (st[k] && !(k === "ordem" && st[k] === "recente")) u.set(k, st[k]); });
    history.replaceState(null, "", location.pathname + (u.toString() ? "?" + u.toString() : ""));
  }
  function lerUrl() {
    var u = new URLSearchParams(location.search);
    ["q", "ordem", "origem", "autor", "partido", "tema", "leg", "ano", "desfecho", "sinal"].forEach(function (k) {
      if (u.get(k) && campos[k]) campos[k].value = u.get(k);
    });
    if (u.get("coautor")) campos.coautor.checked = true;
    var imp = (u.get("imp") || "").split(",");
    if (u.get("efeito")) imp = ["2", "3"];
    impactos.forEach(function (c) { c.checked = imp.indexOf(c.value) >= 0; });
  }

  function passa(p, st, sem) {
    if (modo === "leis" && p.g !== "lei") return false;
    if (sem !== "origem" && st.origem && p.o !== st.origem) return false;
    if (sem !== "autor" && st.autor) {
      if (st.coautor) { if (!p.au.some(function (a) { return a[1] === st.autor; })) return false; }
      else if (p.pr !== st.autor) return false;
    }
    if (sem !== "partido" && st.partido && p.pt !== st.partido) return false;
    if (sem !== "tema" && st.tema && p.t !== st.tema) return false;
    if (sem !== "leg" && st.leg && p.lg !== st.leg) return false;
    if (sem !== "ano" && st.ano && String(modo === "leis" && p.ld ? p.ld.slice(0, 4) : p.a) !== st.ano) return false;
    if (sem !== "desfecho" && st.desfecho && p.g !== st.desfecho) return false;
    if (sem !== "imp" && st.imp && st.imp.split(",").indexOf(chaveImp(p)) < 0) return false;
    if (st.sinal) {
      if (st.sinal === "alerta") { if (!p.pol) return false; }
      else if (st.sinal === "veto") { if (!p.s.some(function (s) { return s.indexOf("veto") === 0 && s !== "veto_derrubado"; }) && p.dx !== "Vetado") return false; }
      else if (p.s.indexOf(st.sinal) < 0) return false;
    }
    if (st.q && p._b.indexOf(norm(st.q)) < 0) return false;
    return true;
  }

  function contagens(st) {
    var c = {};
    impactos.forEach(function (cb) { c[cb.value] = 0; });
    DADOS.projetos.forEach(function (p) { if (passa(p, st, "imp")) c[chaveImp(p)] += 1; });
    impactos.forEach(function (cb) {
      var lbl = cb.parentNode; var n = lbl.querySelector(".n");
      if (!n) { n = document.createElement("span"); n.className = "n"; lbl.appendChild(n); }
      n.textContent = c[cb.value];
    });
  }

  function quadroAutores(lista) {
    var cont = {};
    lista.forEach(function (p) {
      if (!p.pr) return;
      var k = p.pr; cont[k] = cont[k] || { n: 0, ef: 0 }; cont[k].n += 1; cont[k].ef += p.ef;
    });
    var top = Object.keys(cont).sort(function (a, b) { return cont[b].ef - cont[a].ef || cont[b].n - cont[a].n; }).slice(0, 8);
    if (!top.length) return "";
    var max = cont[top[0]].n || 1;
    return '<div class="quem-mais"><h2 class="h-pequeno">Quem mais aparece neste recorte</h2><ol>' + top.map(function (k) {
      var c = cont[k];
      return '<li><a href="' + prefixo + "vereadores/" + esc(k) + '.html">' + esc(DADOS.pessoas[k] || k) + '</a><span class="mini-barra"><i class="c-efeito" style="width:' + (100 * c.ef / max) + '%"></i><i class="c-sem-efeito" style="width:' + (100 * (c.n - c.ef) / max) + '%"></i></span><span class="mini-n">' +
        c.ef + " com efeito · " + c.n + " no total</span></li>";
    }).join("") + '</ol><p class="mini-leg"><i class="sw c-efeito"></i>com efeito <i class="sw c-sem-efeito"></i>demais</p></div>';
  }

  function filtrar() {
    var st = estado();
    gravarUrl(st);
    filtrados = DADOS.projetos.filter(function (p) { return passa(p, st); });
    if (st.ordem === "impacto") filtrados.sort(function (a, b) { return (b.i === null ? -1 : b.i) - (a.i === null ? -1 : a.i) || (b.ld || b.d || "").localeCompare(a.ld || a.d || ""); });
    else if (st.ordem === "rapida") filtrados.sort(function (a, b) { return (a.dl === null ? 1e9 : a.dl) - (b.dl === null ? 1e9 : b.dl); });
    else if (modo === "leis") filtrados.sort(function (a, b) { return (b.ld || "").localeCompare(a.ld || ""); });
    contagens(st);
    var ef = filtrados.filter(function (p) { return p.ef; }).length;
    var se = filtrados.filter(function (p) { return p.se; }).length;
    var pol = filtrados.filter(function (p) { return p.pol; }).length;
    var nome = modo === "leis" ? ["lei", "leis"] : ["projeto", "projetos"];
    resumo.innerHTML = '<p class="contagem"><b>' + filtrados.length + "</b> " + (filtrados.length === 1 ? nome[0] : nome[1]) +
      (filtrados.length ? " · <b>" + ef + "</b> com efeito" + (modo === "leis" ? "" : " (viraram lei)") + " · <b>" + se + "</b> sem efeito prático · <b>" + pol + "</b> com alerta" : "") + "</p>" +
      (modo === "leis" ? quadroAutores(filtrados) : "");
    mostrando = 0;
    resultados.innerHTML = "";
    if (!filtrados.length) resultados.innerHTML = '<li class="vazio">Nenhum resultado com esses filtros. Tente remover algum, ou <button type="button" class="link" id="limpar2">limpe todos</button>.</li>';
    var l2 = $("limpar2"); if (l2) l2.addEventListener("click", limpar);
    renderizar();
  }
  function renderizar() {
    var fatia = filtrados.slice(mostrando, mostrando + PASSO);
    resultados.insertAdjacentHTML("beforeend", fatia.map(item).join(""));
    mostrando += fatia.length;
    mais.hidden = mostrando >= filtrados.length;
    mais.textContent = "Mostrar mais " + Math.min(PASSO, filtrados.length - mostrando);
  }
  function limpar() {
    form.reset();
    impactos.forEach(function (c) { c.checked = false; });
    filtrar();
  }
  function csv() {
    var linhas = [["numero", "data", "ementa", "resumo", "desfecho", "lei", "data_lei", "impacto", "categoria", "tema", "autor_principal", "partido", "autores", "alertas", "url"]];
    filtrados.forEach(function (p) {
      var princ = p.au.filter(function (a) { return a[1] === p.pr; })[0];
      linhas.push([p.n, p.d, p.e, p.r, p.dx, p.l || "", p.ld || "", p.i === null ? "" : p.i, p.c, p.t, princ ? princ[0] : (p.au[0] ? p.au[0][0] : ""), p.pt,
        p.au.map(function (a) { return a[0]; }).join("; "), p.al.map(function (a) { return a[0]; }).join("; "), p.u]);
    });
    var txt = linhas.map(function (l) { return l.map(function (v) { return '"' + String(v == null ? "" : v).replace(/"/g, '""') + '"'; }).join(","); }).join("\n");
    var a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob(["﻿" + txt], { type: "text/csv;charset=utf-8" }));
    a.download = "radar-vereadores-" + modo + ".csv";
    a.click();
  }

  function opcoes(sel, pares) {
    sel.insertAdjacentHTML("beforeend", pares.map(function (p) { return '<option value="' + esc(p[0]) + '">' + esc(p[1]) + "</option>"; }).join(""));
  }

  var maisFiltros = form.querySelector(".mais-filtros");
  if (maisFiltros && window.matchMedia("(max-width: 760px)").matches) maisFiltros.open = false;
  resumo.innerHTML = '<p class="contagem">Carregando…</p>';
  fetch(prefixo + "dados/projetos.json").then(function (r) { return r.json(); }).then(function (json) {
    DADOS = json;
    var base = DADOS.projetos.filter(function (p) { return modo !== "leis" || p.g === "lei"; });
    base.forEach(function (p) { p._b = norm([p.n, p.e, p.r, p.pb, p.l || "", p.au.map(function (a) { return a[0]; }).join(" ")].join(" ")); });
    DADOS.projetos = base;
    var autoresUsados = {}, partidos = {}, temas = {}, anos = {};
    base.forEach(function (p) {
      p.au.forEach(function (a) { if (a[1]) autoresUsados[a[1]] = a[0]; });
      if (p.pt) partidos[p.pt] = 1;
      temas[p.t] = (temas[p.t] || 0) + 1;
      anos[modo === "leis" && p.ld ? p.ld.slice(0, 4) : p.a] = 1;
    });
    opcoes(campos.autor, Object.keys(autoresUsados).sort(function (a, b) { return (DADOS.pessoas[a] || autoresUsados[a]).localeCompare(DADOS.pessoas[b] || autoresUsados[b], "pt-BR"); })
      .map(function (k) { return [k, DADOS.pessoas[k] || autoresUsados[k]]; }));
    opcoes(campos.partido, Object.keys(partidos).sort().map(function (k) { return [k, k]; }));
    opcoes(campos.tema, Object.keys(temas).sort(function (a, b) { return temas[b] - temas[a]; }).map(function (k) { return [k, (DADOS.temas[k] || k) + " (" + temas[k] + ")"]; }));
    opcoes(campos.leg, DADOS.legislaturas.slice().reverse().map(function (k) { return [k, k]; }));
    opcoes(campos.ano, Object.keys(anos).sort().reverse().map(function (k) { return [k, k]; }));
    lerUrl();
    if (maisFiltros && ["autor", "partido", "tema", "leg", "ano", "origem", "desfecho", "sinal"].some(function (k) { return campos[k] && campos[k].value; })) maisFiltros.open = true;
    filtrar();
  }).catch(function () {
    resumo.innerHTML = '<p class="contagem">Não foi possível carregar os dados. Recarregue a página.</p>';
  });

  var espera;
  campos.q.addEventListener("input", function () { clearTimeout(espera); espera = setTimeout(filtrar, 160); });
  form.addEventListener("change", function (ev) { if (ev.target !== campos.q) filtrar(); });
  mais.addEventListener("click", renderizar);
  $("limpar").addEventListener("click", limpar);
  $("csv").addEventListener("click", csv);
})();
