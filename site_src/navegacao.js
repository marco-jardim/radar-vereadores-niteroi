/* Menu principal em telas estreitas, como melhoria progressiva do cabeçalho de paginas.pagina().
   O script do head marca <html class="js"> e o CSS já pinta o menu recolhido. Se faltar o botão, a navegação,
   matchMedia ou a API de eventos, ou se algo falhar, a classe sai e os links voltam a aparecer (grade do CSS). */
(function () {
  "use strict";

  // Mesmo limite do CSS (estilo.css, seção moldura).
  var CONSULTA = "(max-width: 759.98px)";

  function ehEscape(evento) {
    if (!evento || evento.defaultPrevented || evento.isComposing) return false;
    return evento.key === "Escape" || evento.key === "Esc";
  }

  // Desfaz o recolhimento feito pelo CSS: sem menu funcional, a navegação fica sempre visível.
  function semJs(doc) {
    try { doc.documentElement.classList.remove("js"); } catch (e) {}
  }

  // Verdadeiro só quando dá para afirmar que o alvo está fora do elemento.
  function fora(elemento, alvo) {
    return !!(alvo && elemento && typeof elemento.contains === "function" && !elemento.contains(alvo));
  }

  function iniciarTema(doc, win) {
    if (!doc || typeof doc.querySelector !== "function") return;
    var grupo = doc.querySelector(".tema"), raiz = doc.documentElement;
    if (!grupo || !raiz || !raiz.dataset || typeof grupo.querySelectorAll !== "function" ||
        typeof grupo.addEventListener !== "function" || typeof grupo.removeAttribute !== "function") return;
    var botoes = grupo.querySelectorAll("button[data-tema]"), tema = "auto";
    var metas = typeof doc.querySelectorAll === "function" ? doc.querySelectorAll('meta[name="theme-color"]') : [];
    var consultas = Array.from(metas, function (meta) { return meta.getAttribute("media"); });
    try { tema = win.localStorage.getItem("radar-tema"); } catch (e) {}
    if (tema !== "claro" && tema !== "escuro") tema = "auto";

    function marcar() {
      for (var i = 0; i < botoes.length; i++) {
        botoes[i].setAttribute("aria-pressed", botoes[i].getAttribute("data-tema") === tema ? "true" : "false");
      }
    }
    function aplicar() {
      if (tema === "auto") delete raiz.dataset.theme;
      else raiz.dataset.theme = tema === "escuro" ? "dark" : "light";
      for (var i = 0; i < metas.length; i++) {
        if (tema === "auto") {
          if (consultas[i] === null) metas[i].removeAttribute("media");
          else metas[i].setAttribute("media", consultas[i]);
        } else {
          var escuro = (consultas[i] || "").indexOf("dark") !== -1;
          metas[i].setAttribute("media", escuro === (tema === "escuro") ? "all" : "not all");
        }
      }
      marcar();
    }
    grupo.addEventListener("click", function (evento) {
      var alvo = evento && evento.target;
      for (var i = 0; i < botoes.length; i++) {
        if (alvo !== botoes[i]) continue;
        var valor = alvo.getAttribute("data-tema");
        if (valor !== "auto" && valor !== "claro" && valor !== "escuro") return;
        tema = valor;
        try { win.localStorage.setItem("radar-tema", tema); } catch (e) {}
        aplicar();
        return;
      }
    });
    var midia = win && typeof win.matchMedia === "function" ? win.matchMedia("(prefers-color-scheme: dark)") : null;
    function sistema() { if (tema === "auto") marcar(); }
    if (midia) {
      if (typeof midia.addEventListener === "function") midia.addEventListener("change", sistema);
      else if (typeof midia.addListener === "function") midia.addListener(sistema);
    }
    aplicar();
    grupo.removeAttribute("hidden");
  }

  function iniciarGlossario(doc, win) {
    if (!win || !win.HTMLElement || typeof win.HTMLElement.prototype.showPopover !== "function" ||
        !doc || typeof doc.getElementById !== "function" || typeof doc.querySelectorAll !== "function" ||
        typeof doc.createElement !== "function") return;
    var modelo = doc.getElementById("glossario-defs");
    if (!modelo || !modelo.content || typeof modelo.content.querySelectorAll !== "function") return;
    var definicoes = Object.create(null), numero = 0, fecharTodos = [];
    if (typeof win.addEventListener === "function") win.addEventListener("scroll", function () {
      fecharTodos.forEach(function (fechar) { fechar(); });
    }, { passive: true });
    modelo.content.querySelectorAll("p[data-termo]").forEach(function (p) {
      definicoes[p.getAttribute("data-termo")] = p.textContent;
    });
    doc.querySelectorAll("a.glossario").forEach(function (link) {
      var texto = definicoes[link.getAttribute("data-termo")];
      if (!texto || typeof link.insertAdjacentElement !== "function" ||
          typeof link.addEventListener !== "function" || typeof link.getBoundingClientRect !== "function") return;
      var pop = doc.createElement("span"), id, abertoNaPressao = false;
      if (typeof pop.togglePopover !== "function") return;
      do { id = "gl-" + (++numero); } while (doc.getElementById(id));
      pop.setAttribute("id", id);
      pop.setAttribute("popover", "auto");
      pop.setAttribute("class", "glossario-pop");
      pop.setAttribute("role", "tooltip");
      pop.textContent = texto;
      link.insertAdjacentElement("afterend", pop);
      link.setAttribute("aria-describedby", id);
      function aberto() { return pop.matches(":popover-open"); }
      function fechar() { if (aberto()) pop.hidePopover(); }
      fecharTodos.push(fechar);
      link.addEventListener("pointerdown", function () { abertoNaPressao = aberto(); });
      link.addEventListener("focusout", fechar);
      link.addEventListener("click", function (evento) {
        var fecharNoClique = abertoNaPressao;
        abertoNaPressao = false;
        if (evento.defaultPrevented || evento.ctrlKey || evento.metaKey || evento.shiftKey || evento.altKey ||
            (evento.button != null && evento.button !== 0)) return;
        var alvo = link.getBoundingClientRect();
        try {
          if (fecharNoClique) fechar();
          else {
            try { pop.togglePopover({ source: link }); }
            catch (e) { pop.togglePopover(); }
          }
        } catch (e) { return; }
        evento.preventDefault();
        var caixa = pop.getBoundingClientRect();
        pop.style.left = Math.max(8, Math.min(alvo.left, win.innerWidth - caixa.width - 8)) + "px";
        pop.style.top = Math.max(8, Math.min(alvo.bottom + 8, win.innerHeight - caixa.height - 8)) + "px";
      });
    });
  }

  // Todo caminho sem menu funcional (retorno antecipado ou exceção) tira a classe js.
  function iniciar(doc, win) {
    var menu = null;
    try { menu = montarMenu(doc, win); } catch (e) { menu = null; }
    if (!menu) semJs(doc);
    return menu;
  }

  function montarMenu(doc, win) {
    if (!doc || typeof doc.querySelector !== "function" || typeof doc.addEventListener !== "function") return null;
    var topo = doc.querySelector("header.topo");
    if (!topo || typeof topo.querySelector !== "function" || typeof topo.setAttribute !== "function" ||
        typeof topo.addEventListener !== "function") return null;
    var nav = topo.querySelector("nav"), botao = topo.querySelector("button.menu-botao");
    if (!nav || !botao || typeof botao.setAttribute !== "function" || typeof botao.addEventListener !== "function") return null;
    var midia = win && typeof win.matchMedia === "function" ? win.matchMedia(CONSULTA) : null;
    if (!midia) return null;
    var estado = { estreito: false, aberto: false };
    // Pressão de ponteiro em curso: o focusout que ela causa não fecha o menu, para o clique chegar ao alvo
    // (Safari nem foca links e botões ao clicar). O clique fora fecha depois, pelo ouvinte de click.
    var ponteiro = false;
    var pressao = typeof win.PointerEvent === "function" ? "pointerdown" : "mousedown";

    function aplicar() {
      botao.setAttribute("aria-expanded", estado.aberto ? "true" : "false");
      if (estado.estreito) {
        botao.removeAttribute("hidden");
        topo.setAttribute("data-menu", estado.aberto ? "aberto" : "fechado");
      } else {
        botao.setAttribute("hidden", "");
        topo.removeAttribute("data-menu");
      }
    }

    // Toda troca de faixa recomeça com o menu fechado, sem estado anterior. Ao estreitar com o foco num link,
    // o foco vai para o botão antes de a navegação sumir. Ao alargar, sai do botão que ficará oculto.
    function ajustar() {
      var estreito = !!midia.matches, ativo = doc.activeElement;
      if (estreito && !estado.estreito && ativo && typeof nav.contains === "function" && nav.contains(ativo) &&
          typeof botao.focus === "function") botao.focus();
      estado.estreito = estreito;
      estado.aberto = false;
      aplicar();
      if (!estreito && ativo === botao && typeof nav.querySelector === "function") {
        var link = nav.querySelector('a[aria-current="page"]') || nav.querySelector("a");
        if (link && typeof link.focus === "function") link.focus();
      }
    }

    function fechar(devolverFoco) {
      if (!estado.aberto) return false;
      estado.aberto = false;
      aplicar();
      if (devolverFoco && typeof botao.focus === "function") botao.focus();
      return true;
    }

    botao.addEventListener("click", function () {
      if (!estado.estreito) return;
      estado.aberto = !estado.aberto;
      aplicar();
    });
    // Foco que sai do cabeçalho por teclado ou programaticamente fecha; sem destino (saiu da página), também.
    topo.addEventListener("focusout", function (evento) {
      if (estado.aberto && !ponteiro) {
        var destino = evento && evento.relatedTarget;
        if (!destino || fora(topo, destino)) fechar(false);
      }
      ponteiro = false;
    });
    // Um único ouvinte por tipo no documento.
    doc.addEventListener(pressao, function () { ponteiro = true; });
    doc.addEventListener("click", function (evento) {
      ponteiro = false;
      if (estado.aberto && fora(topo, evento && evento.target)) fechar(false);
    });
    doc.addEventListener("keydown", function (evento) {
      ponteiro = false;
      if (estado.aberto && ehEscape(evento)) fechar(true);
    });
    if (typeof midia.addEventListener === "function") midia.addEventListener("change", ajustar);
    else if (typeof midia.addListener === "function") midia.addListener(ajustar);
    ajustar();
    return { estado: estado, fechar: fechar, ajustar: ajustar };
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { CONSULTA: CONSULTA, ehEscape: ehEscape, fora: fora, iniciar: iniciar };
  } else if (typeof document !== "undefined") {
    var janela = typeof window !== "undefined" ? window : null;
    // Falha no tema não impede o menu nem deixa a navegação recolhida.
    try { iniciarTema(document, janela); } catch (e) {}
    try { iniciarGlossario(document, janela); } catch (e) {}
    iniciar(document, janela);
  }
})();
