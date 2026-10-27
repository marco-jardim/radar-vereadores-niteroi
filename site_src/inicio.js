/* Página inicial: céu conforme a hora de Niterói, contagem dos números do servidor e busca de vereador
   (combobox com lista, padrão WAI-ARIA APG). Melhoria progressiva: sem as APIs ou sem os elementos, nada muda
   e o HTML do servidor continua valendo, inclusive a lista <details> de vereadores. */
(function () {
  "use strict";

  // Fases do céu pela hora (h23) em America/Sao_Paulo, intervalos [início, fim). O script inline do hero
  // (SCRIPT_CEU em coletor/site/inicio.py) repete esta tabela; tests/test_inicio.py confere as duas.
  //   madrugada  [0, 6)    00:00 e 05:59 → madrugada
  //   manha      [6, 12)   06:00 → manha
  //   tarde      [12, 17)
  //   por-do-sol [17, 19)  17:59 e 18:00 → por-do-sol
  //   noite      [19, 24)  23:59 → noite
  var FASES = [[6, "madrugada"], [12, "manha"], [17, "tarde"], [19, "por-do-sol"], [24, "noite"]];
  var DEZ_MINUTOS = 600000, DURACAO = 1200;

  function fase(hora) {
    for (var i = 0; i < FASES.length; i++) if (hora < FASES[i][0]) return FASES[i][1];
    return "noite";
  }

  // Hora em São Paulo; sem Intl ou sem o fuso, usa UTC−3 (o Brasil não tem horário de verão desde 2019).
  function horaSaoPaulo(ms, intl) {
    try {
      var partes = new intl.DateTimeFormat("pt-BR", { timeZone: "America/Sao_Paulo", hour: "numeric", hourCycle: "h23" })
        .formatToParts(ms);
      for (var i = 0; i < partes.length; i++) {
        if (partes[i].type !== "hour") continue;
        var h = parseInt(partes[i].value, 10);
        if (h >= 0 && h <= 24) return h % 24;
      }
    } catch (e) {}
    return (new Date(ms).getUTCHours() + 21) % 24;
  }

  function faseAgora(ms, intl) { return fase(horaSaoPaulo(ms, intl)); }

  function ehEscape(evento) {
    if (!evento || evento.defaultPrevented || evento.isComposing) return false;
    return evento.key === "Escape" || evento.key === "Esc";
  }

  function evitar(evento) { if (typeof evento.preventDefault === "function") evento.preventDefault(); }

  // ---- céu

  function iniciarCeu(doc, win) {
    var ceu = doc.querySelector(".ceu"), relogio = null;
    if (!ceu || typeof ceu.setAttribute !== "function") return null;
    var intl = typeof Intl !== "undefined" ? Intl : null;
    function atualizar() { ceu.setAttribute("data-ceu", faseAgora(Date.now(), intl)); }
    function visivel() { return doc.visibilityState == null || doc.visibilityState === "visible"; }
    function ligar() {
      if (relogio === null && win && typeof win.setInterval === "function") relogio = win.setInterval(atualizar, DEZ_MINUTOS);
    }
    function desligar() {
      if (relogio !== null && typeof win.clearInterval === "function") win.clearInterval(relogio);
      relogio = null;
    }
    atualizar();
    if (visivel()) ligar();
    // Único ouvinte deste script no documento.
    if (typeof doc.addEventListener === "function") {
      doc.addEventListener("visibilitychange", function () {
        if (visivel()) { atualizar(); ligar(); } else desligar();
      });
    }
    return { atualizar: atualizar };
  }

  // ---- contagem dos números

  // Número pt-BR com prefixo e sufixo preservados: "1.234", "86,5%", "35 de 132", "R$ 1.200", "84 dias".
  var NUMERO = /^(\D*?)(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d+))?([\s\S]*)$/;

  function analisarNumero(texto) {
    var m = NUMERO.exec(String(texto == null ? "" : texto));
    if (!m) return null;
    var valor = parseFloat(m[2].replace(/\./g, "") + (m[3] ? "." + m[3] : ""));
    if (!(valor > 0) || !isFinite(valor)) return null;
    return { prefixo: m[1], valor: valor, casas: m[3] ? m[3].length : 0, milhar: m[2].indexOf(".") >= 0, sufixo: m[4] };
  }

  function formatar(info, v) {
    var partes = Math.max(0, v).toFixed(info.casas).split(".");
    var inteiro = info.milhar ? partes[0].replace(/\B(?=(\d{3})+$)/g, ".") : partes[0];
    return info.prefixo + inteiro + (partes[1] ? "," + partes[1] : "") + info.sufixo;
  }

  // Sem como saber a preferência, não anima.
  function semMovimento(win) {
    try { return !!win.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (e) { return true; }
  }

  // Leitores de tela leem o valor real; a parte animada fica oculta e, no fim, volta o texto original.
  function animar(doc, win, el) {
    var original = el.textContent, info = analisarNumero(original);
    if (!info || el.childElementCount) return false;
    var leitor = doc.createElement("span"), visual = doc.createElement("span"), inicio = null;
    leitor.setAttribute("class", "so-leitor");
    leitor.textContent = original;
    visual.setAttribute("aria-hidden", "true");
    visual.textContent = formatar(info, 0);
    el.textContent = "";
    el.appendChild(leitor);
    el.appendChild(visual);
    function passo(t) {
      try {
        if (inicio === null) inicio = t;
        var p = (t - inicio) / DURACAO;
        if (!(p < 1)) { el.textContent = original; return; }
        visual.textContent = formatar(info, info.valor * (1 - Math.pow(1 - p, 3)));
        win.requestAnimationFrame(passo);
      } catch (e) { el.textContent = original; }
    }
    win.requestAnimationFrame(passo);
    return true;
  }

  function iniciarContagem(doc, win) {
    if (!win || typeof win.IntersectionObserver !== "function" || typeof win.requestAnimationFrame !== "function" ||
        semMovimento(win) || typeof doc.querySelectorAll !== "function" || typeof doc.createElement !== "function") return 0;
    var alvos = [];
    Array.prototype.forEach.call(doc.querySelectorAll(".tiles .tile-valor, .contador"), function (el) {
      if (!el.childElementCount && analisarNumero(el.textContent)) alvos.push(el);
    });
    if (!alvos.length) return 0;
    var observador = new win.IntersectionObserver(function (entradas) {
      for (var i = 0; i < entradas.length; i++) {
        if (!entradas[i].isIntersecting) continue;
        observador.unobserve(entradas[i].target);
        animar(doc, win, entradas[i].target);
      }
    }, { threshold: 0.4 });
    alvos.forEach(function (el) { observador.observe(el); });
    return alvos.length;
  }

  // ---- busca de vereador

  // Mesma normalização de dados.js: sem acentos e em minúsculas.
  function norm(s) {
    return String(s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  }

  function filtrar(nomes, consulta) {
    var q = norm(consulta).replace(/\s+/g, " ").trim(), r = [];
    for (var i = 0; i < nomes.length; i++) if (norm(nomes[i]).replace(/\s+/g, " ").indexOf(q) >= 0) r.push(i);
    return r;
  }

  function anuncio(n) {
    return n === 0 ? "Nenhum vereador encontrado" : n === 1 ? "1 vereador encontrado" : n + " vereadores encontrados";
  }

  function iniciarBusca(doc, win) {
    var secao = doc.querySelector("section.quem-vereador[data-combobox]");
    if (!secao || typeof secao.querySelectorAll !== "function" || typeof doc.createElement !== "function") return null;
    var detalhes = secao.querySelector("details.lista-vereadores");
    if (!detalhes) return null;
    var itens = [];
    function texto(el) { return el ? (el.textContent || "").trim() : ""; }
    Array.prototype.forEach.call(secao.querySelectorAll("#lista-vereadores li"), function (li) {
      var a = li.querySelector("a"), href = a && a.getAttribute("href");
      if (href) itens.push({ nome: texto(a), partido: texto(li.querySelector(".partido")), status: texto(li.querySelector(".status")), href: href });
    });
    if (!itens.length) return null;

    function criar(tag, atributos, conteudo) {
      var el = doc.createElement(tag);
      for (var k in atributos) el.setAttribute(k, atributos[k]);
      if (conteudo) el.textContent = conteudo;
      return el;
    }
    // O servidor já emite o campo (sem deslocar o layout); só sem ele o campo é criado aqui.
    var entrada = secao.querySelector("#cb-vereadores"), lista = secao.querySelector("#cb-vereadores-lista"),
      aviso = secao.querySelector("#cb-vereadores-status");
    if (!entrada && !lista && !aviso) {
      var pai = detalhes.parentNode;
      if (!pai || typeof pai.insertBefore !== "function") return null;
      var campo = criar("div", { "class": "cb-campo" });
      campo.appendChild(criar("label", { "for": "cb-vereadores", id: "cb-vereadores-rotulo" }, "Digite o nome do vereador"));
      entrada = campo.appendChild(criar("input", { type: "text", role: "combobox", "aria-autocomplete": "list", "aria-expanded": "false",
        "aria-controls": "cb-vereadores-lista", id: "cb-vereadores", autocomplete: "off" }));
      lista = campo.appendChild(criar("ul", { role: "listbox", id: "cb-vereadores-lista", "aria-labelledby": "cb-vereadores-rotulo", hidden: "" }));
      aviso = campo.appendChild(criar("p", { "class": "so-leitor", "aria-live": "polite", id: "cb-vereadores-status" }));
      pai.insertBefore(campo, detalhes);
    }
    // Campo incompleto ou já ativado: não mexe.
    if (!entrada || !lista || !aviso || lista.childElementCount || typeof entrada.addEventListener !== "function") return null;
    var nomes = itens.map(function (item) { return item.nome; });
    var opcoes = itens.map(function (item, i) {
      var extras = [];
      if (item.partido) extras.push(["partido", item.partido]);
      if (item.status) extras.push(["status", item.status]);
      var li = criar("li", { role: "option", id: "cb-op-" + i, "aria-selected": "false" }, item.nome + (extras.length ? " " : ""));
      extras.forEach(function (x, j) { li.appendChild(criar("span", { "class": x[0] }, x[1] + (j < extras.length - 1 ? " " : ""))); });
      lista.appendChild(li);
      return li;
    });
    if (typeof detalhes.removeAttribute === "function") detalhes.removeAttribute("open");

    var visiveis = [], ativo = -1, aberta = false;
    function marcar(novo) {
      if (ativo >= 0) opcoes[visiveis[ativo]].setAttribute("aria-selected", "false");
      ativo = novo;
      if (ativo < 0) { entrada.removeAttribute("aria-activedescendant"); return; }
      var op = opcoes[visiveis[ativo]];
      op.setAttribute("aria-selected", "true");
      entrada.setAttribute("aria-activedescendant", op.getAttribute("id"));
      if (typeof op.scrollIntoView === "function") op.scrollIntoView({ block: "nearest" });
    }
    function mostrar(sim) {
      aberta = sim;
      if (sim) lista.removeAttribute("hidden"); else lista.setAttribute("hidden", "");
      entrada.setAttribute("aria-expanded", sim ? "true" : "false");
    }
    function fechar() { marcar(-1); mostrar(false); }
    function abrir() {
      marcar(-1);
      visiveis = filtrar(nomes, entrada.value);
      var ver = {};
      visiveis.forEach(function (i) { ver[i] = true; });
      opcoes.forEach(function (op, i) { if (ver[i]) op.removeAttribute("hidden"); else op.setAttribute("hidden", ""); });
      aviso.textContent = anuncio(visiveis.length);
      mostrar(visiveis.length > 0);
    }
    function ir(href) {
      try { win.location.assign(href); } catch (e) {}
    }

    entrada.addEventListener("input", function () {
      if (norm(entrada.value).trim()) abrir();
      else { fechar(); aviso.textContent = ""; }
    });
    entrada.addEventListener("keydown", function (evento) {
      if (!evento || evento.isComposing) return;
      var tecla = evento.key, n;
      if (tecla === "ArrowDown" || tecla === "ArrowUp") {
        if (!aberta) abrir();
        n = visiveis.length;
        if (n) marcar(tecla === "ArrowDown" ? (ativo + 1) % n : (ativo < 1 ? n - 1 : ativo - 1));
        evitar(evento);
      } else if ((tecla === "Home" || tecla === "End") && aberta && ativo >= 0) {
        // Só com uma opção ativa; sem ela, Home/End (e sempre as setas laterais) ficam com o campo de texto.
        marcar(tecla === "Home" ? 0 : visiveis.length - 1);
        evitar(evento);
      } else if (tecla === "Enter") {
        // Opção ativa ou um único resultado: vai à página do vereador.
        n = ativo >= 0 ? visiveis[ativo] : visiveis.length === 1 ? visiveis[0] : -1;
        if (aberta && n >= 0) { evitar(evento); ir(itens[n].href); }
      } else if (ehEscape(evento)) {
        // Primeiro Esc fecha a lista; o segundo limpa o texto.
        if (aberta) fechar();
        else if (entrada.value) { entrada.value = ""; aviso.textContent = ""; }
        else return;
        evitar(evento);
      }
    });
    entrada.addEventListener("blur", fechar);
    // A pressão na lista não tira o foco do campo, para o clique chegar à opção.
    lista.addEventListener("mousedown", evitar);
    lista.addEventListener("click", function (evento) {
      for (var no = evento && evento.target; no && no !== lista; no = no.parentNode) {
        var i = opcoes.indexOf(no);
        if (i >= 0) { ir(itens[i].href); return; }
      }
    });
    return { entrada: entrada, lista: lista, aviso: aviso, opcoes: opcoes };
  }

  function iniciar(doc, win) {
    if (!doc || typeof doc.querySelector !== "function") return null;
    var r = { ceu: null, contagem: 0, busca: null };
    try { r.ceu = iniciarCeu(doc, win); } catch (e) {}
    try { r.contagem = iniciarContagem(doc, win); } catch (e) {}
    try { r.busca = iniciarBusca(doc, win); } catch (e) {}
    return r;
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { FASES: FASES, DURACAO: DURACAO, fase: fase, faseAgora: faseAgora, analisarNumero: analisarNumero,
      formatar: formatar, norm: norm, filtrar: filtrar, anuncio: anuncio, iniciar: iniciar };
  } else if (typeof document !== "undefined") {
    iniciar(document, typeof window !== "undefined" ? window : null);
  }
})();
