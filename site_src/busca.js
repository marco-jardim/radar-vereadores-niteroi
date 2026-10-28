(function (raiz) {
  "use strict";
  var CAMPOS = ["q", "modo", "tipo", "ano", "autor", "legislatura"];
  var TIPOS = { pl: "Projeto de lei", substitutivo: "Substitutivo", requerimento: "Requerimento",
    indicacao: "Indicação", mocao: "Moção", pdl: "Projeto de decreto legislativo", resolucao: "Projeto de resolução", ata: "Ata" };
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;" }[c];
  }); }
  function entidades(s) {
    // Uma única decodificação, seguida de escape: entidades nunca viram marcação.
    return s.replace(/&(#x[0-9a-f]+|#\d+|amp|lt|gt|quot|apos);/gi, function (todo, v) {
      var nomes = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'" };
      if (v[0] !== "#") return nomes[v.toLowerCase()];
      var n = v[1].toLowerCase() === "x" ? parseInt(v.slice(2), 16) : Number(v.slice(1));
      return n > 0 && n <= 0x10ffff && !(n >= 0xd800 && n <= 0xdfff) ? String.fromCodePoint(n) : todo;
    });
  }
  function destaque(s) {
    var aberto = false, html = "";
    String(s || "").split(/(<mark>|<\/mark>)/g).forEach(function (parte) {
      if (parte === "<mark>" && !aberto) { html += "<mark>"; aberto = true; }
      else if (parte === "</mark>" && aberto) { html += "</mark>"; aberto = false; }
      else html += esc(entidades(parte));
    });
    return html + (aberto ? "</mark>" : "");
  }
  function lerUrl(consulta) {
    var u = new URLSearchParams(consulta), st = {};
    CAMPOS.forEach(function (k) { st[k] = (u.get(k) || "").trim(); });
    if (["palavras", "semantica", "hibrida"].indexOf(st.modo) < 0) st.modo = "hibrida";
    if (!Object.prototype.hasOwnProperty.call(TIPOS, st.tipo)) st.tipo = "";
    if (!/^(19\d{2}|20\d{2}|2100)$/.test(st.ano)) st.ano = "";
    if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(st.autor) || st.autor.length > 100) st.autor = "";
    if (!/^\d{4}-\d{4}$/.test(st.legislatura)) st.legislatura = "";
    return st;
  }
  function consultaUrl(st) {
    var u = new URLSearchParams();
    CAMPOS.forEach(function (k) {
      var v = String(st[k] || "").trim();
      if (v && !(k === "modo" && v === "hibrida")) u.set(k, v);
    });
    return u.toString();
  }
  function urlBusca(api, st, pagina) {
    var u = new URL(api + "/api/busca");
    u.search = consultaUrl(st);
    u.searchParams.set("pagina", String(pagina));
    return u.href;
  }
  function siscam(url) {
    return /^https:\/\/consultaniteroi\.siscam\.com\.br\/Detalhes(?:Documentos|Sessao)\.aspx\?Id(?:Documento|Sessao)=[1-9]\d*$/.test(url || "") ? url : "";
  }
  function cartao(r, api) {
    var titulo = (Object.prototype.hasOwnProperty.call(TIPOS, r.tipo) ? TIPOS[r.tipo] : "Documento") + (r.numero ? " " + r.numero : "") + (r.ano ? "/" + r.ano : "");
    var fonte = siscam(r.url_siscam), links = fonte ? '<a href="' + esc(fonte) + '" target="_blank" rel="noopener">Ver no SISCAM<span class="so-leitor"> (abre em nova aba)</span></a>' : "";
    var hash = /^[0-9a-f]{64}$/.test(r.sha256 || "") ? r.sha256 : "";
    if (hash && r.url_original === "/api/original/" + hash) {
      links += (links ? " · " : "") + '<a href="' + esc(api + r.url_original) + '">Baixar original (sem máscara)</a>';
    }
    var selo = r.status === "ocr_baixa_confianca" ? "OCR de baixa confiança" : r.ocr ? "OCR" : "";
    if (r.status === "ok_parcial") selo = "Extração parcial" + (selo ? " · " + selo : "");
    var confianca = typeof r.confianca === "number" && r.confianca >= 0 && r.confianca <= 100 ? " · confiança média: " + r.confianca : "";
    var origens = { palavras: "palavras", semantica: "significado", ambas: "palavras e significado" };
    var origem = Object.prototype.hasOwnProperty.call(origens, r.origem) ? origens[r.origem] : "não informada";
    return '<li tabindex="-1"><h3>' + esc(titulo) + '</h3>' + (r.arquivo ? '<p>' + esc(r.ementa) + '</p>' : "") +
      (selo ? '<p class="busca-selo">' + selo + esc(confianca) + '</p>' : "") +
      '<p>' + destaque(r.trecho) + '</p><p>Origem do resultado: ' + origem +
      (r.arquivo ? " · Arquivo: " + esc(r.arquivo) : " · Somente ementa") + '</p><p>' + links + '</p>' +
      (hash ? '<p>SHA-256 do original: <code>' + hash + '</code></p>' : "") + '</li>';
  }
  function mensagemErro(status, dados) {
    if (status === 429) return "Muitas consultas em pouco tempo. Aguarde um minuto e tente novamente.";
    if (status === 503 && dados && dados.codigo === "semantica_indisponivel") return "A busca por significado está indisponível; tente o modo Palavras.";
    if (dados && dados.codigo === "consulta_muito_generica") return "Consulta muito genérica. Use ao menos um termo mais específico.";
    if (status === 400) return dados && typeof dados.erro === "string" ? dados.erro : "Confira a consulta e os filtros.";
    return "A busca está indisponível no momento. Tente novamente ou use as listas e o SISCAM.";
  }
  function iniciar(doc, janela) {
    var form = doc.getElementById("busca-form"), meta = doc.querySelector('meta[name="radar-api"]');
    if (!form || !meta || !janela.fetch || !janela.history || !janela.history.replaceState) return null;
    var api = meta.content;
    try { var u = new URL(api); if (u.protocol !== "https:" || u.username || u.password || u.search || u.hash) return null; }
    catch (_) { return null; }
    var campos = doc.getElementById("busca-campos"), lista = doc.getElementById("busca-resultados");
    var estado = doc.getElementById("busca-estado"), aviso = doc.getElementById("busca-aviso"), mais = doc.getElementById("busca-mais");
    var st = lerUrl(janela.location.search), pagina = 0, pedido = 0, controle = null, ocupado = false;
    CAMPOS.forEach(function (k) { form.elements.namedItem(k).value = st[k]; });
    // Um filtro desconhecido no select não pode ficar silenciosamente ativo na consulta inicial.
    CAMPOS.forEach(function (k) { st[k] = form.elements.namedItem(k).value; });
    campos.disabled = false;
    doc.getElementById("busca-alternativa").textContent = "Busca disponível. As listas e o SISCAM continuam acessíveis abaixo.";
    async function buscar(adicionar, focar) {
      if (adicionar && ocupado) return;
      if (!adicionar && !form.reportValidity()) return;
      var atual = ++pedido;
      if (controle) controle.abort();
      controle = janela.AbortController ? new janela.AbortController() : null;
      if (!adicionar) {
        CAMPOS.forEach(function (k) { st[k] = form.elements.namedItem(k).value.trim(); });
        pagina = 0;
        lista.innerHTML = "";
        mais.hidden = true;
        var consulta = consultaUrl(st);
        janela.history.replaceState(null, "", janela.location.pathname + (consulta ? "?" + consulta : "") + (janela.location.hash || ""));
      }
      var proxima = pagina + 1, antes = lista.children.length;
      ocupado = true;
      mais.disabled = true;
      lista.setAttribute("aria-busy", "true");
      estado.textContent = "Buscando…";
      aviso.textContent = "";
      var prazo = controle ? janela.setTimeout(function () { if (atual === pedido) controle.abort(); }, 20000) : null;
      try {
        var resposta = await janela.fetch(urlBusca(api, st, proxima), { credentials: "omit", referrerPolicy: "no-referrer", signal: controle ? controle.signal : undefined });
        if (atual !== pedido) return;
        var dados;
        if (!resposta.ok) {
          try { dados = await resposta.json(); } catch (_) { dados = null; }
          if (atual === pedido) estado.textContent = mensagemErro(resposta.status, dados);
          return;
        }
        try { dados = await resposta.json(); } catch (_) { throw new Error("Resposta inválida"); }
        if (atual !== pedido) return;
        if (!Array.isArray(dados.resultados) || !Number.isInteger(dados.total) || dados.total < 0 || dados.pagina !== proxima || !Number.isInteger(dados.por_pagina) || dados.por_pagina < 1) throw new Error("Resposta inválida");
        lista.insertAdjacentHTML("beforeend", dados.resultados.map(function (r) { return cartao(r, api); }).join(""));
        pagina = proxima;
        var quantidade = lista.children.length, incluidos = quantidade - antes;
        mais.hidden = incluidos === 0 || pagina >= 50 || quantidade >= dados.total;
        aviso.textContent = (typeof dados.aviso === "string" ? dados.aviso : "") +
          (dados.limitado ? " O limite de candidatos foi atingido; refine a consulta ou os filtros." : "");
        estado.textContent = quantidade ? (adicionar ? incluidos + (incluidos === 1 ? " resultado adicionado. " : " resultados adicionados. ") : "") +
          quantidade + (quantidade === 1 ? " resultado exibido de " : " resultados exibidos de ") + dados.total +
          (dados.limitado ? " candidatos encontrados." : ".") : "Nenhum resultado encontrado. Tente outros termos ou filtros.";
        if (focar && lista.children[antes]) lista.children[antes].focus();
        else if (focar && adicionar && mais.hidden) estado.focus();
      } catch (_) {
        if (atual === pedido) estado.textContent = mensagemErro(503);
      } finally {
        if (prazo !== null) janela.clearTimeout(prazo);
        if (atual === pedido) { ocupado = false; mais.disabled = false; lista.setAttribute("aria-busy", "false"); }
      }
    }
    // Um listener por tipo no documento, inclusive para o último lote que esconde o botão.
    doc.addEventListener("submit", function (ev) { if (ev.target === form) { ev.preventDefault(); buscar(false, true); } });
    doc.addEventListener("click", function (ev) { if (ev.target === mais) { ev.preventDefault(); buscar(true, true); } });
    if (st.q) buscar(false, false);
    return { buscar: buscar };
  }
  var publico = { esc: esc, destaque: destaque, lerUrl: lerUrl, consultaUrl: consultaUrl, urlBusca: urlBusca, cartao: cartao, mensagemErro: mensagemErro, iniciar: iniciar };
  if (typeof module !== "undefined" && module.exports) module.exports = publico;
  if (raiz && raiz.document) iniciar(raiz.document, raiz);
})(typeof window !== "undefined" ? window : null);
