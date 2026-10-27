/* Menu principal em telas estreitas, como melhoria progressiva do cabeçalho de paginas.pagina().
   Sem o botão, a navegação ou matchMedia, nada muda: os links continuam visíveis (grade do CSS). */
(function () {
  "use strict";

  // Mesmo limite do CSS (estilo.css, seção moldura).
  var CONSULTA = "(max-width: 759.98px)";

  function ehEscape(evento) {
    var tecla = evento && evento.key;
    return tecla === "Escape" || tecla === "Esc";
  }

  // Verdadeiro só quando dá para afirmar que o alvo está fora do elemento.
  function fora(elemento, alvo) {
    return !!(alvo && elemento && typeof elemento.contains === "function" && !elemento.contains(alvo));
  }

  function iniciar(doc, win) {
    if (!doc || typeof doc.querySelector !== "function") return null;
    var topo = doc.querySelector("header.topo");
    if (!topo || typeof topo.querySelector !== "function" || typeof topo.setAttribute !== "function") return null;
    var nav = topo.querySelector("nav"), botao = topo.querySelector("button.menu-botao");
    if (!nav || !botao || typeof botao.setAttribute !== "function" || typeof botao.addEventListener !== "function") return null;
    var midia = win && typeof win.matchMedia === "function" ? win.matchMedia(CONSULTA) : null;
    var estado = { estreito: false, aberto: false };
    // Clique dentro do cabeçalho que tira o foco sem destino (Safari não foca links e botões ao clicar).
    var pressionado = false;

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

    // Toda troca de faixa recomeça com o menu fechado, sem estado anterior.
    function ajustar() {
      estado.estreito = !!(midia && midia.matches);
      estado.aberto = false;
      aplicar();
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
    if (typeof topo.addEventListener === "function") {
      topo.addEventListener("mousedown", function () { pressionado = true; });
      topo.addEventListener("focusout", function (evento) {
        var destino = evento && evento.relatedTarget, clique = pressionado;
        pressionado = false;
        if (!estado.aberto) return;
        if (destino ? fora(topo, destino) : !clique) fechar(false);
      });
    }
    if (typeof doc.addEventListener === "function") {
      doc.addEventListener("click", function (evento) {
        pressionado = false;
        if (estado.aberto && fora(topo, evento && evento.target)) fechar(false);
      });
      doc.addEventListener("keydown", function (evento) {
        pressionado = false;
        if (estado.aberto && ehEscape(evento)) fechar(true);
      });
    }
    if (midia) {
      if (typeof midia.addEventListener === "function") midia.addEventListener("change", ajustar);
      else if (typeof midia.addListener === "function") midia.addListener(ajustar);
    }
    ajustar();
    return { estado: estado, fechar: fechar, ajustar: ajustar };
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = { CONSULTA: CONSULTA, ehEscape: ehEscape, fora: fora, iniciar: iniciar };
  } else if (typeof document !== "undefined") {
    iniciar(document, typeof window !== "undefined" ? window : null);
  }
})();
