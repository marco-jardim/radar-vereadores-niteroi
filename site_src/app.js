(function () {
  "use strict";
  var raiz = document.getElementById("conteudo");
  var prefixo = raiz ? raiz.dataset.prefixo || "" : "";

  // ------------------------------------------------------------- tooltip
  // Abre com o ponteiro por cima e com o foco; no toque, só quando pointerType é "touch" (um toque abre, outro
  // fecha). Fecha com Esc, toque ou clique fora, saída do foco ou rolagem. As marcas dos gráficos não recebem
  // tabindex: só os links que já existem (pontos com página própria) ganham aria-describedby enquanto o tip aparece.
  // Um único listener por tipo de evento no documento.
  var tip = document.getElementById("tip"), tipAlvo = null, tipOrigem = "", tipDescrito = null;
  // dentro: no foco, o link de um ponto do gráfico leva o data-tip na marca dentro dele (só links: painéis e
  // regiões roláveis com tabindex não abrem o tip da primeira marca que contêm).
  function alvoTip(t, dentro) {
    if (!t) return null;
    var el = typeof t.closest === "function" ? t.closest("[data-tip]") : null;
    if (!el && dentro && /^a$/i.test(t.tagName || "") && typeof t.querySelector === "function") el = t.querySelector("[data-tip]");
    return el || null;
  }
  function centro(el) {
    var r = typeof el.getBoundingClientRect === "function" ? el.getBoundingClientRect() : { left: 0, top: 0, width: 0 };
    return [r.left + r.width / 2, r.top];
  }
  function esconderTip() {
    if (tipDescrito) {
      if (typeof tipDescrito.removeAttribute === "function") tipDescrito.removeAttribute("aria-describedby");
      tipDescrito = null;
    }
    tipAlvo = null;
    tipOrigem = "";
    tip.hidden = true;
  }
  function mostrarTip(el, x, y, origem) {
    tip.textContent = el.getAttribute("data-tip");
    tip.hidden = false;
    tipAlvo = el;
    tipOrigem = origem;
    var r = tip.getBoundingClientRect();
    var left = Math.min(window.innerWidth - r.width - 8, Math.max(8, x - r.width / 2));
    var top = y - r.height - 12;
    if (top < 8) top = y + 16;
    tip.style.left = left + "px";
    tip.style.top = top + "px";
  }
  // O alvo saiu da página (lista redesenhada, por exemplo): o tip não fica órfão na tela.
  function alvoRemovido() { return !!tipAlvo && tipAlvo.isConnected === false; }
  if (tip && typeof document.addEventListener === "function") {
    var comPonteiro = typeof window.PointerEvent === "function";
    document.addEventListener(comPonteiro ? "pointermove" : "mousemove", function (ev) {
      if (ev.pointerType === "touch") return;
      var el = alvoTip(ev.target);
      if (el) mostrarTip(el, ev.clientX, ev.clientY, "ponteiro");
      else if (!tip.hidden && (tipOrigem === "ponteiro" || alvoRemovido())) esconderTip();
    });
    document.addEventListener("pointerdown", function (ev) {
      var el = alvoTip(ev.target);
      if (el && ev.pointerType === "touch") {
        if (el === tipAlvo && !tip.hidden) esconderTip();
        else { var c = centro(el); mostrarTip(el, c[0], c[1], "toque"); }
      } else if (!el && !tip.hidden) esconderTip();
    });
    document.addEventListener("focusin", function (ev) {
      var el = alvoTip(ev.target, true);
      if (!el) return;
      var c = centro(el);
      mostrarTip(el, c[0], c[1], "foco");
      var foco = ev.target;
      if (foco && typeof foco.getAttribute === "function" && !foco.getAttribute("aria-describedby")) {
        foco.setAttribute("aria-describedby", "tip");
        tipDescrito = foco;
      }
    });
    document.addEventListener("focusout", function () { if (tipOrigem === "foco" || alvoRemovido()) esconderTip(); });
    document.addEventListener("keydown", function (ev) {
      if ((ev.key === "Escape" || ev.key === "Esc") && !tip.hidden) esconderTip();
    });
    document.addEventListener("scroll", function () { if (!tip.hidden) esconderTip(); }, { passive: true });
  }

  // ----------------------------------------------- placar da página inicial
  // Abas no padrão WAI-ARIA (setas com volta, Home/End, tabindex móvel). Sem JS, o servidor mostra todos os
  // painéis empilhados, cada um com seu título, e a lista de abas fica oculta: aqui ela aparece e só o painel da
  // aba selecionada continua visível.
  var listaAbas = document.querySelector('.abas[role="tablist"]');
  var abas = listaAbas ? Array.prototype.slice.call(listaAbas.querySelectorAll('[role="tab"]')) : [];
  var ordem = document.getElementById("ordem");
  var soEleitos = document.getElementById("so-eleitos");
  var partidoPlacar = document.getElementById("f-partido-placar");
  function camel(s) { return s.replace(/-([a-z])/g, function (_, c) { return c.toUpperCase(); }); }
  function painelDaAba(aba) { return document.getElementById(aba.getAttribute("aria-controls")); }
  function abaSelecionada() {
    return abas.filter(function (b) { return b.getAttribute("aria-selected") === "true"; })[0] || null;
  }
  function selecionarAba(aba, focar, ordenar) {
    abas.forEach(function (b) {
      var ativa = b === aba, painel = painelDaAba(b);
      b.setAttribute("aria-selected", ativa ? "true" : "false");
      b.setAttribute("tabindex", ativa ? "0" : "-1");
      if (painel) painel.hidden = !ativa;
    });
    if (focar && typeof aba.focus === "function") aba.focus();
    if (ordenar) aplicarPlacar();
  }

  function aplicarPlacar() {
    // Sem abas (presença em sessoes.html), vale o primeiro bloco visível.
    var aba = abaSelecionada();
    var sec = aba ? painelDaAba(aba) : document.querySelector(".legislatura:not([hidden])");
    if (!sec) return;
    var lista = sec.querySelector(".placar");
    if (!lista) return;
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
  if (abas.length && typeof listaAbas.addEventListener === "function" && abas.every(function (bt) {
    var painel = painelDaAba(bt);
    return typeof bt.addEventListener === "function" && painel && typeof painel.setAttribute === "function";
  })) {
    abas.forEach(function (bt) {
      var painel = painelDaAba(bt);
      painel.setAttribute("role", "tabpanel");
      painel.setAttribute("tabindex", "0");
      painel.setAttribute("aria-labelledby", bt.id);
    });
    // A ordem do servidor já é a padrão: na abertura só oculta os outros painéis, sem reordenar.
    selecionarAba(abaSelecionada() || abas[0], false, false);
    listaAbas.hidden = false;
    abas.forEach(function (bt) {
      bt.addEventListener("click", function () { selecionarAba(bt, false, true); });
    });
    listaAbas.addEventListener("keydown", function (ev) {
      var i = abas.indexOf(ev.target), n = abas.length, alvo = null;
      if (i < 0) return;
      if (ev.key === "ArrowRight" || ev.key === "Right") alvo = abas[(i + 1) % n];
      else if (ev.key === "ArrowLeft" || ev.key === "Left") alvo = abas[(i - 1 + n) % n];
      else if (ev.key === "Home") alvo = abas[0];
      else if (ev.key === "End") alvo = abas[n - 1];
      if (!alvo) return;
      if (typeof ev.preventDefault === "function") ev.preventDefault();
      selecionarAba(alvo, true, alvo !== abas[i]);
    });
  }
  [ordem, soEleitos, partidoPlacar].forEach(function (el) { if (el) el.addEventListener("change", aplicarPlacar); });

  // ---------------------------------------------- detalhe do SISCAM em diálogo
  // Cada item tem o botão "Ver no SISCAM" (só com JS e <dialog> nativo) e o link comum "abrir no SISCAM",
  // sempre presente, que continua funcionando se o SISCAM passar a bloquear a exibição incorporada.
  var dialogo = document.getElementById("siscam-dialogo");
  if (dialogo && typeof dialogo.showModal === "function") {
    var quadro = document.getElementById("siscam-quadro"), tituloDialogo = document.getElementById("siscam-titulo");
    var abrirSiscam = document.getElementById("siscam-abrir"), gatilho = null;
    // Só a página de detalhe de um documento, com id numérico: nenhum outro caminho, esquema ou domínio.
    var DETALHE_SISCAM = /^https:\/\/consultaniteroi\.siscam\.com\.br\/DetalhesDocumentos\.aspx\?IdDocumento=\d+$/;
    // O SISCAM é de outra origem: allow-same-origin mantém a origem dele (cookies e postbacks do ASP.NET, que
    // dependem de scripts e formulários), não a do Radar, e não lhe dá acesso a esta página. O sandbox ainda
    // impede que ele navegue a aba do Radar (sem allow-top-navigation), baixe arquivos ou abra diálogos
    // modais; janelas novas saem sem as restrições, para os links do próprio SISCAM.
    var SANDBOX = "allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox";
    document.documentElement.classList.add("com-dialogo");
    document.addEventListener("click", function (ev) {
      var bt = ev.target.closest && ev.target.closest("button.ver-siscam");
      if (!bt) return;
      var url = bt.getAttribute("data-url") || "", rotulo = bt.getAttribute("data-rotulo") || "";
      if (!DETALHE_SISCAM.test(url)) return;
      gatilho = bt;
      tituloDialogo.textContent = "Detalhe no SISCAM: " + rotulo;
      abrirSiscam.href = url;
      // O iframe não recebe dados do Radar; referrerpolicy="no-referrer" não envia o endereço da página de origem.
      var iframe = document.createElement("iframe");
      iframe.setAttribute("sandbox", SANDBOX);
      iframe.setAttribute("referrerpolicy", "no-referrer");
      iframe.setAttribute("title", "Detalhe no SISCAM: " + rotulo);
      iframe.setAttribute("src", url);
      quadro.innerHTML = "";
      quadro.appendChild(iframe);
      dialogo.showModal();
    });
    document.getElementById("siscam-fechar").addEventListener("click", function () { dialogo.close(); });
    // Clique no fundo (fora da caixa) fecha; Esc é tratado pelo próprio <dialog>.
    dialogo.addEventListener("click", function (ev) { if (ev.target === dialogo) dialogo.close(); });
    dialogo.addEventListener("close", function () {
      quadro.innerHTML = "";
      if (gatilho && document.body.contains(gatilho)) gatilho.focus();
      gatilho = null;
    });
  }

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
  // Prévia de projetos.html sem consulta: só pl-recentes na tela, com o resumo exato que veio no HTML do build.
  var previa = false, totalPrevia = 0, estadoPrevia = null, buildHtml = null, completando = null, csvPendente = false;

  var norm = window.RadarDados.norm;
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
  var NOVA_ABA = '<span class="so-leitor"> (abre em nova aba)</span>';
  function situacaoLei(p) {
    var nomes = { sancionada: "Sancionada", promulgada_camara: "Promulgada pela Câmara", veto_derrubado: "Veto derrubado" };
    return (nomes[p.lt] || "Situação não informada") + (p.vp ? " · Veto parcial" : "");
  }
  function chaveImp(p) { return p.c === "simbolica" || p.s.indexOf("autorizativa") >= 0 ? "0" : (p.i === null || p.i === undefined ? "x" : String(p.i)); }

  function selo(p) {
    if (p.c === "simbolica") return '<span class="selo imp-0">Simbólica</span>';
    if (p.s.indexOf("autorizativa") >= 0) return '<span class="selo imp-0">Autorizativa</span>';
    var k = chaveImp(p);
    return '<span class="selo imp-' + k + '">' + (NOME_IMP[k] || "Não avaliado") + "</span>";
  }
  // Espelho de lista_coautores (paginas.py): resumo clicável com todos os nomes, dentro de um <div>, nunca de um <p>.
  // Espelho de partido_html (paginas.py): a sigla logo depois do nome, vazia quando o partido não é conhecido.
  function ptHtml(pt) { return pt ? '<span class="partido">' + esc(pt) + "</span>" : ""; }
  // Partido de um vereador na legislatura, pelo mapa {legislatura: partido} de dic-pl.pessoas.
  function ptPl(slug, leg) { var m = slug && DADOS && DADOS.partidos && DADOS.partidos[slug]; return (m && leg && m[leg]) || ""; }
  // Espelho de lista_coautores (paginas.py): resumo clicável com todos os nomes, dentro de um <div>, nunca de um <p>.
  function listaCoautores(resumo, nomes, partidos) {
    return '<details class="coautores"><summary>' + esc(resumo) + "</summary><ul>" +
      nomes.map(function (nome, i) { return "<li>" + esc(nome) + ptHtml(partidos && partidos[i]) + "</li>"; }).join("") + "</ul></details>";
  }
  function autores(p) {
    var princ = p.au.filter(function (a) { return a[1] && a[1] === p.pr; });
    if (!princ.length) princ = p.au.slice(0, 1);
    var html = princ.map(function (a) {
      return a[1] ? '<a class="chip chip-principal" href="' + prefixo + "vereadores/" + esc(a[1]) + '.html">' + esc(a[0]) + ptHtml(a[1] === p.pr ? p.pt : ptPl(a[1], p.lg)) + "</a>"
        : '<span class="chip chip-exec">' + esc(a[0]) + "</span>";
    }).join("");
    var outros = p.au.filter(function (a) { return princ.indexOf(a) < 0; }), n = outros.length;
    if (n > 0) html += listaCoautores("e " + n + (n === 1 ? " coautor" : " coautores"), outros.map(function (a) { return a[0]; }),
      outros.map(function (a) { return ptPl(a[1], p.lg); }));
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
  // Lei aprovada por substitutivo: este link leva à página do substitutivo; o do número continua no PL original.
  function viaSubstitutivo(p) {
    if (!p.ls) return "";
    return ' <a class="via-substitutivo" href="' + esc(p.ls) + '" target="_blank" rel="noopener">via substitutivo' +
      '<span class="so-leitor"> (substitutivo ao PL ' + esc(p.n) + ")</span>" + NOVA_ABA + "</a>";
  }
  function item(p) {
    var lei = p.l ? " · Lei " + esc(p.l) : "";
    if (p.g === "lei") lei += " · " + esc(situacaoLei(p)) + viaSubstitutivo(p);
    var dataLei = p.ld ? dataBr(p.ld) : "data não informada";
    if (p.g === "lei" && modo !== "leis") lei += " · " + esc(dataLei);
    var tema = DADOS.temas[p.t] && p.t !== "outro" && p.t !== "homenagem" ? DADOS.temas[p.t] : "";
    var meta = [];
    if (p.pb) meta.push("Afeta: " + esc(p.pb));
    if (tema) meta.push(esc(tema));
    if (modo === "leis" && p.dl !== null && p.dl !== undefined) meta.push(p.dl + " dias até virar lei");
    return '<li class="projeto d-' + esc(p.g) + " imp-borda-" + chaveImp(p) + '">' +
      '<p class="cab"><a href="' + esc(p.u) + '" target="_blank" rel="noopener">PL ' + esc(p.n) + NOVA_ABA + "</a><span>" + esc(modo === "leis" ? dataLei : dataBr(p.d)) + '</span><span class="desfecho">' + esc(p.dx) + lei + "</span>" + selo(p) + "</p>" +
      (p.r ? '<p class="resumo-ia">' + esc(p.r) + "</p>" : "") +
      '<p class="ementa">' + esc(legivel(p.e)) + "</p>" +
      (meta.length ? '<p class="publico">' + meta.join(" · ") + "</p>" : "") +
      '<div class="autoria">' + autores(p) + "</div>" + tags(p) + botoesSiscam(p.u, "PL " + p.n) + "</li>";
  }
  function botoesSiscam(url, rotulo) {
    return '<p class="acoes-item"><button type="button" class="ver-siscam" data-url="' + esc(url) + '" data-rotulo="' + esc(rotulo) + '">' +
      'Ver no SISCAM<span class="so-leitor"> (' + esc(rotulo) + ")</span></button> " +
      '<a class="abrir-siscam" href="' + esc(url) + '" target="_blank" rel="noopener">abrir no SISCAM' +
      '<span class="so-leitor"> (' + esc(rotulo) + ")</span>" + NOVA_ABA + "</a></p>";
  }

  function atualizarAutoria() {
    campos.coautor.disabled = !campos.autor.value;
    if (campos.coautor.disabled || ["1", "so"].indexOf(campos.coautor.value) < 0) campos.coautor.value = "";
  }
  function estado() {
    atualizarAutoria();
    return {
      q: campos.q.value.trim(), ordem: campos.ordem.value, origem: campos.origem.value, autor: campos.autor.value,
      partido: campos.partido.value, tema: campos.tema.value, leg: campos.leg.value, ano: campos.ano.value,
      desfecho: campos.desfecho ? campos.desfecho.value : "", sinal: campos.sinal ? campos.sinal.value : "",
      coautor: campos.coautor.value,
      imp: impactos.filter(function (c) { return c.checked; }).map(function (c) { return c.value; }).join(",")
    };
  }
  // Sem nada que gravarUrl poria no endereço.
  function semFiltros(st) {
    return Object.keys(st).every(function (k) { return !st[k] || (k === "ordem" && st[k] === "recente"); });
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
    campos.coautor.value = ["1", "so"].indexOf(u.get("coautor")) >= 0 ? u.get("coautor") : "";
    atualizarAutoria();
    var imp = (u.get("imp") || "").split(",");
    if (u.get("efeito")) imp = ["2", "3"];
    impactos.forEach(function (c) { c.checked = imp.indexOf(c.value) >= 0; });
  }

  function revisado(p) {
    return p.al.some(function (a) { return a[1] === "curadoria"; }) || p.s.indexOf("inconstitucionalidade_declarada") >= 0;
  }
  function passa(p, st, busca) {
    if (modo === "leis" && p.g !== "lei") return false;
    if (st.origem && p.o !== st.origem) return false;
    if (st.autor) {
      if (st.coautor === "1" || st.coautor === "so") {
        if (!p.au.some(function (a) { return a[1] === st.autor; }) || (st.coautor === "so" && p.pr === st.autor)) return false;
      }
      else if (p.pr !== st.autor) return false;
    }
    if (st.partido && p.pt !== st.partido) return false;
    if (st.tema && p.t !== st.tema) return false;
    if (st.leg && p.lg !== st.leg) return false;
    if (st.ano && String(modo === "leis" && p.ld ? p.ld.slice(0, 4) : p.a) !== st.ano) return false;
    if (st.desfecho && p.g !== st.desfecho) return false;
    if (st.sinal) {
      if (st.sinal === "alerta") { if (!p.pol) return false; }
      else if (st.sinal === "curadoria") { if (!revisado(p)) return false; }
      else if (st.sinal === "alerta_ia") {
        // O JSON já traz o risco jurídico nos rótulos, sem um campo próprio.
        if (revisado(p) || !(p.pol || p.al.some(function (a) { return a[0] === "Risco de inconstitucionalidade"; }))) return false;
      }
      else if (st.sinal === "veto") { if (!p.s.some(function (s) { return s.indexOf("veto") === 0 && s !== "veto_derrubado"; }) && p.dx !== "Vetado") return false; }
      else if (p.s.indexOf(st.sinal) < 0) return false;
    }
    if (busca && p._b.indexOf(busca) < 0) return false;
    return true;
  }

  // c: contagens por chip; null apaga os números (os do HTML só valem sem filtros).
  function contagens(c) {
    impactos.forEach(function (cb) {
      var lbl = cb.parentNode, n = lbl.querySelector(".n");
      if (!n) {
        if (!c) return;
        n = document.createElement("span");
        lbl.appendChild(n);
      }
      n.className = "n";
      n.textContent = c ? c[cb.value] : "";
    });
  }

  function quadroAutores(lista) {
    var cont = {};
    lista.forEach(function (p) {
      if (!p.pr) return;
      var k = p.pr; cont[k] = cont[k] || { n: 0, ef: 0, lg: "", pt: "" }; cont[k].n += 1; cont[k].ef += p.ef;
      // O recorte pode cruzar legislaturas: vale o partido da mais recente entre os projetos contados.
      if (p.pt && (p.lg || "") >= cont[k].lg) { cont[k].lg = p.lg || ""; cont[k].pt = p.pt; }
    });
    var top = Object.keys(cont).sort(function (a, b) { return cont[b].ef - cont[a].ef || cont[b].n - cont[a].n; }).slice(0, 8);
    if (!top.length) return "";
    var max = cont[top[0]].n || 1;
    return '<div class="quem-mais"><h2 class="h-pequeno">Quem mais aparece neste recorte</h2><ol>' + top.map(function (k) {
      var c = cont[k];
      return '<li><a href="' + prefixo + "vereadores/" + esc(k) + '.html">' + esc(DADOS.pessoas[k] || k) + ptHtml(c.pt) + '</a><span class="mini-barra"><i class="c-efeito" style="width:' + (100 * c.ef / max) + '%"></i><i class="c-sem-efeito" style="width:' + (100 * (c.n - c.ef) / max) + '%"></i></span><span class="mini-n">' +
        c.ef + " com efeito · " + c.n + " no total</span></li>";
    }).join("") + '</ol><p class="mini-leg"><i class="sw c-efeito"></i>com efeito <i class="sw c-sem-efeito"></i>demais</p></div>';
  }

  // Filtra e ordena DADOS para o estado st, sem tocar na página; devolve as contagens.
  function calcular(st) {
    var busca = norm(st.q), imp = st.imp ? st.imp.split(",") : [];
    var r = { c: {}, ef: 0, se: 0, pol: 0 };
    impactos.forEach(function (cb) { r.c[cb.value] = 0; });
    filtrados = [];
    DADOS.projetos.forEach(function (p) {
      if (!passa(p, st, busca)) return;
      var k = chaveImp(p);
      // As contagens dos chips ignoram o impacto selecionado.
      r.c[k] += 1;
      if (imp.length && imp.indexOf(k) < 0) return;
      filtrados.push(p);
      if (p.ef) r.ef += 1;
      if (p.se) r.se += 1;
      if (p.pol) r.pol += 1;
    });
    if (st.ordem === "impacto") filtrados.sort(function (a, b) { return (b.i === null ? -1 : b.i) - (a.i === null ? -1 : a.i) || (b.ld || b.d || "").localeCompare(a.ld || a.d || ""); });
    else if (st.ordem === "rapida") filtrados.sort(function (a, b) { return (a.dl === null ? 1e9 : a.dl) - (b.dl === null ? 1e9 : b.dl); });
    else if (modo === "leis") filtrados.sort(function (a, b) { return (b.ld || "").localeCompare(a.ld || ""); });
    return r;
  }
  function aplicarFiltros() {
    var st = estado();
    gravarUrl(st);
    var r = calcular(st);
    contagens(r.c);
    var nome = modo === "leis" ? ["lei", "leis"] : ["projeto", "projetos"];
    resumo.innerHTML = '<p class="contagem"><b>' + filtrados.length + "</b> " + (filtrados.length === 1 ? nome[0] : nome[1]) +
      (filtrados.length ? " · <b>" + r.ef + "</b> com efeito" + (modo === "leis" ? "" : " (viraram lei)") + " · <b>" + r.se + "</b> sem efeito prático · <b>" + r.pol + "</b> com alerta" : "") + "</p>" +
      (modo === "leis" ? quadroAutores(filtrados) : "");
    mostrando = 0;
    resultados.innerHTML = "";
    if (!filtrados.length) resultados.innerHTML = '<li class="vazio">Nenhum resultado com esses filtros. Tente remover algum, ou <button type="button" class="link" id="limpar2">limpe todos</button>.</li>';
    var l2 = $("limpar2"); if (l2) l2.addEventListener("click", limpar);
    renderizar();
  }
  // Na prévia, o total é o do HTML: filtrados só tem as primeiras linhas.
  function atualizarMais() {
    var restam = Math.max(0, (previa ? totalPrevia : filtrados.length) - mostrando);
    mais.disabled = false;
    mais.hidden = restam <= 0;
    mais.textContent = "Mostrar mais " + Math.min(PASSO, restam);
  }
  // "Mostrar mais": o foco vai ao primeiro item novo (o botão pode sumir quando a lista acaba) e #anuncio
  // diz quantos itens entraram. Sem itens novos, o foco fica onde está.
  function itensNaLista() { return resultados.children ? resultados.children.length : 0; }
  function focarNovo(indice) {
    var novo = resultados.children ? resultados.children[indice] : null;
    if (!novo || typeof novo.focus !== "function") return;
    novo.setAttribute("tabindex", "-1");
    novo.focus();
  }
  function textoAdicionados(n) { return n + (n === 1 ? " item adicionado." : " itens adicionados."); }
  function avisarLista(texto) { var a = $("anuncio"); if (a) a.textContent = texto; }
  function renderizar(doBotao) {
    var fatia = filtrados.slice(mostrando, mostrando + PASSO), antes = itensNaLista();
    resultados.insertAdjacentHTML("beforeend", fatia.map(item).join(""));
    mostrando += fatia.length;
    atualizarMais();
    if (doBotao && fatia.length) {
      focarNovo(antes);
      avisarLista(textoAdicionados(fatia.length));
    }
  }
  function limpar() {
    form.reset();
    impactos.forEach(function (c) { c.checked = false; });
    filtrar();
  }
  function csv() {
    if ($("csv").disabled) return;
    if (previa) {
      // A prévia não basta para o CSV: carrega o recorte completo primeiro.
      if (csvPendente) return;
      csvPendente = true;
      completar().then(function (ok) { csvPendente = false; if (ok) csv(); }, function (erro) { csvPendente = false; erroPrevia(erro); });
      return;
    }
    if (!DADOS) return;
    var linhas = [["numero", "data", "ementa", "resumo", "desfecho", "lei", "data_lei", "impacto", "categoria", "tema", "autor_principal", "partido", "autores", "alertas", "url"]];
    filtrados.forEach(function (p) {
      var princ = p.au.filter(function (a) { return a[1] === p.pr; })[0];
      linhas.push([p.n, p.d, p.e, p.r, p.dx, p.l || "", p.ld || "", p.i === null ? "" : p.i, p.c, p.t, princ ? princ[0] : (p.au[0] ? p.au[0][0] : ""), p.pt,
        p.au.map(function (a) { return a[0]; }).join("; "), p.al.map(function (a) { return a[0]; }).join("; "), p.u]);
    });
    baixarCsv(linhas, "radar-vereadores-" + modo + ".csv");
  }
  // Planilhas tratam como fórmula o texto que começa com = + - @ (ou tab e retorno antes deles):
  // o apóstrofo na frente mantém a célula como texto.
  function celulaCsv(v) {
    var s = String(v == null ? "" : v);
    if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;
    return '"' + s.replace(/"/g, '""') + '"';
  }
  function baixarCsv(linhas, nome) {
    var txt = linhas.map(function (l) { return l.map(celulaCsv).join(","); }).join("\n");
    var a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob(["\ufeff" + txt], { type: "text/csv;charset=utf-8" }));
    a.download = nome;
    a.click();
  }

  // Cache genérico por URL: nenhum nome de arquivo é convertido em caminho aqui.
  var manifesto = null, cache = new Map(), hidratadas = new Map(), renovacao = null;
  var pedido = 0, recorteAtual = "";
  function desatualizado() {
    var erro = new Error("Site atualizado, recarregue a página");
    erro.atualizado = true;
    return erro;
  }
  function validarManifesto(m) {
    if (!m || m.esquema !== 2 || typeof m.build !== "string" || !m.arquivos) throw desatualizado();
    return m;
  }
  try { manifesto = validarManifesto(JSON.parse($("manifesto-dados").textContent)); }
  catch (_) { manifesto = null; }

  function atualizarManifesto() {
    // Todas as requisições concorrentes compartilham a mesma tentativa; se ela falhar, a próxima ação tenta de novo.
    // Só 404 e manifesto de outro esquema viram "Site atualizado"; falhas de rede ou do servidor seguem como são.
    if (!renovacao) {
      var tentativa = fetch(prefixo + "dados/manifest.json", { cache: "no-cache" }).then(function (r) {
        if (r.status === 404) throw desatualizado();
        if (!r.ok) throw new Error("Falha ao carregar o manifesto");
        return r.json();
      }).then(validarManifesto).then(function (m) {
        manifesto = m;
        cache.clear();
        hidratadas.clear();
        return m;
      });
      renovacao = tentativa;
      tentativa.catch(function () { if (renovacao === tentativa) renovacao = null; });
    }
    return renovacao;
  }
  function buscarArquivo(nome, m) {
    var entrada = m.arquivos[nome];
    if (!entrada || !entrada.url) return Promise.reject(desatualizado());
    var url = prefixo + entrada.url;
    if (!cache.has(url)) {
      var promessa = fetch(url).then(function (r) {
        if (r.status === 404) throw desatualizado();
        if (!r.ok) throw new Error("Falha ao carregar os dados");
        return r.json();
      }).then(function (dados) {
        // As famílias de documentos (com "familia" no manifesto) não levam build: a URL já traz o hash do conteúdo.
        var sessao = entrada.familia === "dic-ses" || entrada.familia === "vot";
        var n = entrada.familia === "dic-ses" ? (dados.materias || []).length : dados.n;
        if (dados.esquema !== (sessao ? 1 : m.esquema) || (!entrada.familia && dados.build !== m.build) || n !== entrada.n) throw desatualizado();
        return dados;
      }).catch(function (erro) {
        if (cache.get(url) === promessa) cache.delete(url);
        throw erro;
      });
      cache.set(url, promessa);
    }
    return cache.get(url);
  }
  function carregarArquivos(nomes, repetiu) {
    if (!manifesto) return atualizarManifesto().then(function () { return carregarArquivos(nomes, true); });
    var m = manifesto;
    return Promise.all(nomes.map(function (nome) { return buscarArquivo(nome, m); })).then(function (arquivos) {
      // Uma resposta antiga não pode reintroduzir dados de outro build após a renovação.
      if (m !== manifesto) return carregarArquivos(nomes, repetiu);
      return { manifesto: m, arquivos: arquivos };
    }).catch(function (erro) {
      if (!erro || !erro.atualizado || repetiu) throw erro;
      return atualizarManifesto().then(function () { return carregarArquivos(nomes, true); });
    });
  }
  // Interface mínima compartilhada com sessoes.js: mesmas URLs versionadas, cache e renovação.
  window.RadarArquivos = { carregar: carregarArquivos, manifesto: function () { return manifesto; } };
  // Os formulários de sessões têm controlador próprio; placar e diálogo acima continuam ativos.
  if (document.querySelector("form.filtros-sessoes")) return;

  function prepararDados(pacote, nomes) {
    var dic = pacote.arquivos[0], linhas = [], dados = { pessoas: {}, partidos: {}, temas: {}, sinais: {} };
    dic.pessoas.forEach(function (p) { if (p[0]) { dados.pessoas[p[0]] = p[1]; dados.partidos[p[0]] = p[2] || {}; } });
    dic.temas.forEach(function (p) { dados.temas[p[0]] = p[1]; });
    dic.sinais.forEach(function (p) { dados.sinais[p[0]] = p[1]; });
    dados.legislaturas = dic.legislaturas;
    pacote.arquivos.slice(1).forEach(function (fatia, i) {
      var chave = dic.build + "|" + nomes[i + 1];
      if (!hidratadas.has(chave)) {
        var projetos = window.RadarDados.hidratar(dic, fatia);
        projetos.forEach(function (p) { p._b = norm([p.n, p.e, p.r, p.pb, p.l || "", p.au.map(function (a) { return a[0]; }).join(" ")].join(" ")); });
        hidratadas.set(chave, projetos);
      }
      hidratadas.get(chave).forEach(function (p, j) { linhas.push({ p: p, ordem: fatia.colunas.ord[j] }); });
    });
    // Mantém inclusive os empates da ordenação do antigo JSON único.
    linhas.sort(function (a, b) { return a.ordem - b.ordem; });
    dados.projetos = linhas.map(function (linha) { return linha.p; });
    return dados;
  }
  function carregando(ativo) {
    resultados.setAttribute("aria-busy", ativo ? "true" : "false");
    $("csv").disabled = ativo;
  }
  function filtrar() {
    var st = estado(), atual = ++pedido;
    previa = false;
    gravarUrl(st);
    var nomes = ["dic-pl"].concat(window.RadarDados.fatiasPara(modo, st));
    var chave = (manifesto ? manifesto.build : "") + "|" + nomes.join(",");
    if (DADOS && recorteAtual === chave) {
      carregando(false);
      aplicarFiltros();
      return;
    }
    carregando(true);
    resumo.innerHTML = '<p class="contagem">Carregando…</p>';
    resultados.innerHTML = "";
    mais.hidden = true;
    carregarArquivos(nomes).then(function (pacote) {
      if (atual !== pedido) return;
      DADOS = prepararDados(pacote, nomes);
      recorteAtual = pacote.manifesto.build + "|" + nomes.join(",");
      carregando(false);
      aplicarFiltros();
    }).catch(function (erro) {
      if (atual !== pedido) return;
      resultados.setAttribute("aria-busy", "false");
      resumo.textContent = erro.atualizado ? "Site atualizado, recarregue a página" : "Não foi possível carregar os dados. Recarregue a página.";
    });
  }

  // ---------------------------------------------- prévia de projetos.html
  // Sem consulta, a página desenha as primeiras linhas (pl-recentes) e mostra as contagens geradas no build;
  // as fatias completas vêm depois da carga, ou já no primeiro filtro, "Mostrar mais" ou CSV. Nenhum total
  // sai de dados parciais: se o build mudar no caminho, a lista volta ao caminho normal de filtrar().
  function iniciarPrevia() {
    var atual = ++pedido, nomes = ["dic-pl", "pl-recentes"];
    previa = true;
    estadoPrevia = estado();
    resultados.setAttribute("aria-busy", "true");
    carregarArquivos(nomes).then(function (pacote) {
      if (atual !== pedido || !previa) return;
      if (pacote.manifesto.build !== buildHtml) { filtrar(); return; }
      DADOS = prepararDados(pacote, nomes);
      recorteAtual = "";
      filtrados = DADOS.projetos;
      mostrando = 0;
      resultados.innerHTML = "";
      resultados.setAttribute("aria-busy", "false");
      renderizar();
      depoisDaCarga(completar);
    }).catch(function () {
      if (atual === pedido && previa) filtrar();
    });
  }
  // Carrega as fatias completas sem redesenhar a prévia: as primeiras linhas são as mesmas e o resumo do HTML já
  // é o exato. Resolve com false quando um filtro mudou no caminho (aí filtrar() assumiu a lista).
  function completar() {
    if (!previa) return Promise.resolve(true);
    if (!completando) {
      var atual = pedido, st = estadoPrevia, nomes = ["dic-pl"].concat(window.RadarDados.fatiasPara(modo, st));
      var tentativa = carregarArquivos(nomes).then(function (pacote) {
        if (atual !== pedido || !previa) return false;
        DADOS = prepararDados(pacote, nomes);
        recorteAtual = pacote.manifesto.build + "|" + nomes.join(",");
        previa = false;
        if (pacote.manifesto.build !== buildHtml || !mostrando) aplicarFiltros();
        else { calcular(st); atualizarMais(); }
        return true;
      });
      completando = tentativa;
      tentativa.then(function () { completando = null; }, function () { completando = null; });
    }
    return completando;
  }
  function erroPrevia(erro) {
    mais.disabled = false;
    resumo.textContent = erro && erro.atualizado ? "Site atualizado, recarregue a página" : "Não foi possível carregar os dados. Recarregue a página.";
  }
  function maisLista() {
    if (!previa) { renderizar(true); return; }
    mais.disabled = true;
    completar().then(function (ok) { if (ok) renderizar(true); }, erroPrevia);
  }
  // Depois da primeira pintura: no evento load e, se houver, num momento ocioso do navegador.
  function depoisDaCarga(fn) {
    function ocioso() {
      if (typeof window.requestIdleCallback === "function") window.requestIdleCallback(function () { fn(); }, { timeout: 2000 });
      else setTimeout(function () { fn(); }, 0);
    }
    if (document.readyState === "complete") ocioso();
    else window.addEventListener("load", ocioso);
  }

  if (modo === "atividades") { iniciarAtividades(); return; }

  var maisFiltros = form.querySelector(".mais-filtros");
  if (maisFiltros && window.matchMedia("(max-width: 760px)").matches) maisFiltros.open = false;
  lerUrl();
  if (maisFiltros && ["autor", "partido", "tema", "leg", "ano", "origem", "desfecho", "sinal"].some(function (k) { return campos[k] && campos[k].value; })) maisFiltros.open = true;
  buildHtml = manifesto ? manifesto.build : null;
  if (modo === "projetos" && !location.search && manifesto && manifesto.arquivos["pl-recentes"] && resumo.dataset.total &&
      semFiltros(estado())) {
    totalPrevia = Number(resumo.dataset.total);
    iniciarPrevia();
  } else {
    contagens(null);
    filtrar();
  }

  var espera;
  campos.q.addEventListener("input", function () { clearTimeout(espera); espera = setTimeout(filtrar, 160); });
  form.addEventListener("change", function (ev) { if (ev.target !== campos.q) filtrar(); });
  mais.addEventListener("click", maisLista);
  $("limpar").addEventListener("click", limpar);
  $("csv").addEventListener("click", function () { csv(); });

  // ------------------------------------------------------------ atividades
  // Documentos (indicações, moções, requerimentos, PDLs e resoluções) em partes por tipo e ano, da mais
  // recente; fatiasDocs decide o que carregar e só os itens mais novos que a fronteira são exibidos, de modo
  // que "Mostrar mais" apenas acrescenta itens ao fim da lista. Filtros de conteúdo carregam o recorte inteiro.
  function iniciarAtividades() {
    var RD = window.RadarDados;
    var cDoc = { q: $("q"), ordem: $("f-ordem"), tipo: $("f-tipo"), ano: $("f-ano"), autor: $("f-autor"),
      categoria: $("f-categoria"), subcategoria: $("f-subcategoria"), bairro: $("f-bairro"), situacao: $("f-situacao"),
      respondido: $("f-respondido"), publicado: $("f-publicado") };
    var CHAVES = Object.keys(cDoc), CONTEUDO = ["q", "categoria", "subcategoria", "bairro", "situacao", "respondido", "publicado"];
    var anoPadrao = form.dataset.anoPadrao || "todos", anuncio = $("anuncio");
    var lista = [], filtradosD = [], visiveis = 0, mostrandoD = 0, totalD = 0, alvo = PASSO;
    var plano = null, recorte = "", pedidoD = 0, nomesDic = null, csvOcupado = false;

    function milhar(n) { return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, "."); }
    function situacaoLegivel(s) {
      s = s || "";
      return s === s.toUpperCase() && s !== s.toLowerCase() ? s.charAt(0) + s.slice(1).toLowerCase() : s;
    }
    function avisar(texto) { if (anuncio) anuncio.textContent = texto; }
    function estadoD() {
      var st = {};
      CHAVES.forEach(function (k) { st[k] = cDoc[k] ? String(cDoc[k].value || "").trim() : ""; });
      if (!st.ordem) st.ordem = "recente";
      return st;
    }
    function gravarUrlD(st) {
      var u = new URLSearchParams();
      CHAVES.forEach(function (k) {
        var v = st[k];
        // Com autor, o ano vai sempre no endereço: sem ele, ?autor= abre todos os anos.
        if (!v || (k === "ordem" && v === "recente") || (k === "ano" && v === anoPadrao && !st.autor)) return;
        u.set(k, v);
      });
      history.replaceState(null, "", location.pathname + (u.toString() ? "?" + u.toString() : ""));
    }
    function temOpcao(sel, v) {
      if (!sel.options) return true;
      return Array.prototype.some.call(sel.options, function (o) { return o.value === v; });
    }
    function lerUrlD() {
      var u = new URLSearchParams(location.search);
      CHAVES.forEach(function (k) { if (u.get(k) && cDoc[k]) cDoc[k].value = u.get(k); });
      if (!cDoc.ano) return;
      // Sem ano, ou com um ano que não está entre as opções, vale o padrão: o mais recente, ou todos com ?autor=.
      var ano = u.get("ano");
      if (!ano || !temOpcao(cDoc.ano, ano)) cDoc.ano.value = u.get("autor") ? "todos" : anoPadrao;
    }
    function tiposD(st) {
      if (st.tipo) return [st.tipo];
      if (st.respondido) return ["requerimento"];
      if (st.subcategoria) return [st.subcategoria.split(":")[0]];
      return null;
    }
    function anoD(st) { return st.ano && st.ano !== "todos" ? Number(st.ano) : null; }
    function planejar(st, completo) {
      return RD.fatiasDocs(manifesto, { tipo: tiposD(st), ano: st.ano, autor: st.autor, alvo: alvo,
        completo: !!completo || st.ordem === "antigo" || CONTEUDO.some(function (k) { return st[k]; }) });
    }
    function mapasDic(dic, url) {
      var m = { url: url, tipos: {}, categorias: {}, subcategorias: {} };
      dic.tipos.forEach(function (t) { m.tipos[t[0]] = t; });
      dic.categorias.forEach(function (c) { m.categorias[c[0]] = c[1]; });
      dic.subcategorias.forEach(function (s) { m.subcategorias[s[0] + ":" + s[1]] = s[2]; });
      return m;
    }
    function prepararD(pacote, nomes) {
      var arquivos = pacote.manifesto.arquivos, dic = pacote.arquivos[0], urlDic = arquivos[nomes[0]].url;
      if (!nomesDic || nomesDic.url !== urlDic) nomesDic = mapasDic(dic, urlDic);
      var listas = pacote.arquivos.slice(1).map(function (fatia, i) {
        // As URLs trazem o hash do conteúdo: identificam a hidratação de cada parte com o dic-doc usado.
        var chave = "doc|" + urlDic + "|" + arquivos[nomes[i + 1]].url;
        if (!hidratadas.has(chave)) {
          var docs = RD.hidratarDocs(dic, fatia);
          docs.forEach(function (d) {
            d._n = RD.numeroInt(d.numero);
            d._b = norm([nomesDic.tipos[d.tipo][3], d.numero, d.ementa, d.assunto || "", d.situacao, d.bairro || "",
              d.autores.map(function (a) { return a[0]; }).join(" ")].join(" "));
          });
          hidratadas.set(chave, docs);
        }
        return hidratadas.get(chave);
      });
      // Cada parte já vem ordenada: basta intercalar, sem reordenar a lista inteira.
      var vistos = {}, saida = [];
      RD.mesclarDocs(listas).forEach(function (d) { if (!vistos[d.id]) { vistos[d.id] = 1; saida.push(d); } });
      return saida;
    }
    function passaD(d, st, busca, ano, tipos) {
      if (tipos && tipos.indexOf(d.tipo) < 0) return false;
      if (ano !== null && d.ano !== ano) return false;
      if (st.autor && !d.autores.some(function (a) { return a[1] === st.autor; })) return false;
      if (st.categoria && d.categoria !== st.categoria) return false;
      if (st.subcategoria && d.tipo + ":" + d.subcategoria !== st.subcategoria) return false;
      if (st.bairro && d.bairro !== st.bairro) return false;
      if (st.situacao && d.situacao !== st.situacao) return false;
      if (st.respondido && (d.tipo !== "requerimento" || (d.respondido ? "1" : "0") !== st.respondido)) return false;
      if (st.publicado && (d.publicado ? "1" : "0") !== st.publicado) return false;
      if (busca && d._b.indexOf(busca) < 0) return false;
      return true;
    }
    function rotuloD(d) { return nomesDic.tipos[d.tipo][3] + " " + d.numero; }
    function metaD(d) {
      var meta = [nomesDic.subcategorias[d.tipo + ":" + d.subcategoria] || d.subcategoria];
      if (d.bairro) meta.push("Bairro: " + d.bairro);
      if (d.tipo === "requerimento") {
        if (d.respondido) {
          var t = "Respondido";
          if (d.respondido_em) t += " em " + dataBr(String(d.respondido_em).slice(0, 10));
          if (d.dias_ate_resposta !== null && d.dias_ate_resposta !== undefined) t += " (" + d.dias_ate_resposta + (d.dias_ate_resposta === 1 ? " dia)" : " dias)");
          meta.push(t);
        } else meta.push("Sem resposta registrada");
      }
      if (d.publicacao) {
        meta.push("Publicado" + (d.publicacao.numero ? " nº " + d.publicacao.numero : "") +
          (d.publicacao.data ? " em " + dataBr(String(d.publicacao.data).slice(0, 10)) : ""));
      }
      if (d.detalhe_pendente) meta.push("detalhe ainda não coletado");
      return meta;
    }
    function autoresD(d) {
      // a[3]: partido na legislatura do documento (só vereadores com partido conhecido); espelho de autores_documento_html.
      var html = d.autores.slice(0, 3).map(function (a) {
        if (a[1] && a[2]) return '<a class="chip" href="' + prefixo + "vereadores/" + esc(a[1]) + '.html">' + esc(a[0]) + ptHtml(a[3]) + "</a>";
        return '<span class="chip' + (a[1] ? "" : " chip-exec") + '">' + esc(a[0]) + (a[1] ? ptHtml(a[3]) : "") + "</span>";
      }).join("");
      var resto = d.autores.slice(3);
      if (resto.length) {
        html += listaCoautores("e mais " + resto.length + (resto.length === 1 ? " autor" : " autores"), resto.map(function (a) { return a[0]; }),
          resto.map(function (a) { return a[1] ? a[3] : ""; }));
      }
      return html;
    }
    function itemD(d) {
      var rotulo = rotuloD(d);
      return '<li class="projeto doc t-' + esc(d.tipo) + '">' +
        '<p class="cab"><a href="' + esc(d.url) + '" target="_blank" rel="noopener">' + esc(rotulo) + NOVA_ABA + "</a><span>" + esc(dataBr(d.data)) + '</span><span class="desfecho">' +
        esc(situacaoLegivel(d.situacao)) + '</span><span class="selo cat-' + esc(d.categoria) + '">' + esc(nomesDic.categorias[d.categoria] || d.categoria) + "</span></p>" +
        (d.assunto ? '<p class="assunto">Assunto: ' + esc(d.assunto) + "</p>" : "") +
        '<p class="ementa">' + esc(legivel(d.ementa)) + "</p>" +
        '<p class="publico">' + esc(metaD(d).join(" · ")) + "</p>" +
        '<div class="autoria">' + autoresD(d) + "</div>" + botoesSiscam(d.url, rotulo) + "</li>";
    }
    function resumoD() {
      var porTipo = {};
      if (plano.completo) filtradosD.forEach(function (d) { porTipo[d.tipo] = (porTipo[d.tipo] || 0) + 1; });
      else porTipo = plano.porTipo;
      totalD = plano.completo ? filtradosD.length : plano.total;
      var partes = Object.keys(nomesDic.tipos).filter(function (t) { return porTipo[t]; }).map(function (t) {
        return "<b>" + milhar(porTipo[t]) + "</b> " + esc((porTipo[t] === 1 ? nomesDic.tipos[t][1] : nomesDic.tipos[t][2]).toLowerCase());
      });
      resumo.innerHTML = '<p class="contagem"><b>' + milhar(totalD) + "</b> " + (totalD === 1 ? "documento" : "documentos") +
        (partes.length > 1 ? " · " + partes.join(" · ") : "") + "</p>";
    }
    function aplicarD(st, manter) {
      var busca = norm(st.q), ano = anoD(st), tipos = tiposD(st);
      filtradosD = lista.filter(function (d) { return passaD(d, st, busca, ano, tipos); });
      if (st.ordem === "antigo") filtradosD.reverse();
      visiveis = filtradosD.length;
      if (!plano.completo) {
        visiveis = 0;
        while (visiveis < filtradosD.length && (filtradosD[visiveis].data || "") > plano.fronteira) visiveis += 1;
      }
      resumoD();
      if (!manter) {
        mostrandoD = 0;
        resultados.innerHTML = filtradosD.length ? "" : '<li class="vazio">Nenhum documento com esses filtros. Tente remover algum, ou <button type="button" class="link" id="limpar2">limpe todos</button>.</li>';
        var l2 = $("limpar2"); if (l2) l2.addEventListener("click", limparD);
      }
      renderizarD(manter);
    }
    // anunciar: vem do "Mostrar mais"; o foco vai ao primeiro item novo, como na lista de projetos.
    function renderizarD(anunciar) {
      var fim = Math.min(alvo, visiveis), novos = filtradosD.slice(mostrandoD, fim), antes = itensNaLista();
      if (novos.length) resultados.insertAdjacentHTML("beforeend", novos.map(itemD).join(""));
      mostrandoD = Math.max(mostrandoD, fim);
      var restam = Math.max(0, totalD - mostrandoD);
      mais.disabled = false;
      mais.hidden = restam <= 0;
      mais.textContent = "Mostrar mais " + Math.min(PASSO, restam);
      if (anunciar && novos.length) focarNovo(antes);
      if (anunciar) avisar((novos.length ? textoAdicionados(novos.length) + " " : "") +
        "Mostrando " + milhar(mostrandoD) + " de " + milhar(totalD) + " documentos.");
    }
    function erroD(erro) {
      resultados.setAttribute("aria-busy", "false");
      mais.disabled = false;
      resumo.textContent = erro && erro.atualizado ? "Site atualizado, recarregue a página" : "Não foi possível carregar os dados. Recarregue a página.";
    }
    function filtrarD(manter, repetiu) {
      var st = estadoD(), atual = ++pedidoD;
      if (!manter) alvo = PASSO;
      gravarUrlD(st);
      if (!manifesto || typeof manifesto.build_doc !== "string") {
        if (repetiu) { erroD(desatualizado()); return; }
        atualizarManifesto().then(function () { if (atual === pedidoD) filtrarD(manter, true); },
          function (erro) { if (atual === pedidoD) erroD(erro); });
        return;
      }
      var usado = manifesto, p = planejar(st), nomes = ["dic-doc"].concat(p.nomes);
      var chave = usado.build_doc + "|" + nomes.join(",");
      if (recorte === chave) { plano = p; carregando(false); aplicarD(st, manter); return; }
      carregando(true);
      if (manter) mais.disabled = true;
      else {
        resumo.innerHTML = '<p class="contagem">Carregando ' + milhar(p.total) + (p.total === 1 ? " documento" : " documentos") + "…</p>";
        resultados.innerHTML = "";
        mais.hidden = true;
      }
      carregarArquivos(nomes).then(function (pacote) {
        if (atual !== pedidoD) return;
        // O manifesto foi renovado no caminho: replaneja com as partes do novo build.
        if (pacote.manifesto !== usado && !repetiu) { filtrarD(false, true); return; }
        lista = prepararD(pacote, nomes);
        plano = p;
        recorte = chave;
        carregando(false);
        aplicarD(st, manter);
      }).catch(function (erro) {
        if (atual !== pedidoD) return;
        if (erro.atualizado && !repetiu && manifesto && manifesto !== usado) { filtrarD(false, true); return; }
        erroD(erro);
      });
    }
    function maisD() {
      alvo += PASSO;
      if (plano && !plano.completo && alvo > visiveis) { filtrarD(true); return; }
      renderizarD(true);
    }
    function limparD() {
      form.reset();
      filtrarD(false);
    }
    // O CSV tem estado próprio: não mexe no carregamento da lista nem no resumo, e avisa pelo #anuncio.
    function csvD(repetiu) {
      if (!repetiu && ($("csv").disabled || csvOcupado)) return;
      if (!manifesto || typeof manifesto.build_doc !== "string") { csvOcupado = false; return; }
      var st = estadoD(), usado = manifesto, nomes = ["dic-doc"].concat(planejar(st, true).nomes);
      csvOcupado = true;
      if (!repetiu) avisar("Preparando o CSV…");
      carregarArquivos(nomes).then(function (pacote) {
        // O manifesto foi renovado no caminho: o recorte inteiro pode estar em outras partes.
        if (pacote.manifesto !== usado && !repetiu) { csvD(true); return; }
        var docs = prepararD(pacote, nomes), busca = norm(st.q), ano = anoD(st), tipos = tiposD(st);
        var sel = docs.filter(function (d) { return passaD(d, st, busca, ano, tipos); });
        if (st.ordem === "antigo") sel.reverse();
        var linhas = [["tipo", "numero", "data", "ementa", "situacao", "assunto", "categoria", "subcategoria", "bairro", "respondido",
          "respondido_em", "dias_ate_resposta", "publicado", "publicacao_numero", "publicacao_data", "detalhe_pendente", "autores", "url"]];
        sel.forEach(function (d) {
          linhas.push([d.tipo, d.numero, d.data, d.ementa, d.situacao, d.assunto, d.categoria, d.subcategoria, d.bairro,
            d.respondido ? 1 : 0, d.respondido_em, d.dias_ate_resposta, d.publicado ? 1 : 0,
            d.publicacao ? d.publicacao.numero : "", d.publicacao ? d.publicacao.data : "", d.detalhe_pendente ? 1 : 0,
            d.autores.map(function (a) { return a[0]; }).join("; "), d.url]);
        });
        baixarCsv(linhas, "radar-vereadores-atividades.csv");
        csvOcupado = false;
        avisar("CSV com " + milhar(sel.length) + (sel.length === 1 ? " documento pronto." : " documentos prontos."));
      }).catch(function (erro) {
        csvOcupado = false;
        avisar(erro && erro.atualizado ? "Site atualizado, recarregue a página" : "Não foi possível gerar o CSV. Tente de novo.");
      });
    }

    var maisFiltrosD = form.querySelector(".mais-filtros");
    if (maisFiltrosD && window.matchMedia("(max-width: 760px)").matches) maisFiltrosD.open = false;
    lerUrlD();
    if (maisFiltrosD && CONTEUDO.concat(["tipo", "autor"]).some(function (k) { return cDoc[k] && cDoc[k].value; })) maisFiltrosD.open = true;
    filtrarD(false);
    var esperaD;
    cDoc.q.addEventListener("input", function () { clearTimeout(esperaD); esperaD = setTimeout(function () { filtrarD(false); }, 200); });
    form.addEventListener("change", function (ev) { if (ev.target !== cDoc.q) filtrarD(false); });
    mais.addEventListener("click", maisD);
    $("limpar").addEventListener("click", limparD);
    $("csv").addEventListener("click", function () { csvD(false); });
  }
})();
