(function (raiz) {
  "use strict";

  function norm(s) {
    return String(s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  }

  function fatiasPara(modo, filtros) {
    var grupos = ["lei", "andamento", "sem_exito"];
    if (modo === "leis") return ["pl-lei"];
    var grupo = (filtros || {}).desfecho;
    return (grupos.indexOf(grupo) >= 0 ? [grupo] : grupos).map(function (g) { return "pl-" + g; });
  }

  function hidratar(dic, fatia) {
    if (dic.esquema !== 2 || fatia.esquema !== 2 || dic.build !== fatia.build) {
      throw new Error("Esquema ou build incompatível");
    }
    var c = fatia.colunas;
    // ls: id do substitutivo de onde saiu a lei (ou null); vira a URL do detalhe, como u.
    var colunas = ["id", "ord", "n", "a", "d", "e", "r", "pb", "t", "h", "c", "i", "l", "ld", "lt", "vp", "dl", "o", "lg", "pr", "au", "al", "pol", "s", "rp", "ls"];
    colunas.forEach(function (k) {
      if (!Array.isArray(c[k]) || c[k].length !== fatia.n) throw new Error("Coluna inválida: " + k);
    });
    return c.id.map(function (id, j) {
      var desfecho = dic.desfechos[c.h[j]];
      var tema = dic.temas[c.t[j]][0], categoria = dic.categorias[c.c[j]][0];
      var sinais = c.s[j].map(function (s) { return dic.sinais[s][0]; });
      var principal = c.pr[j] === null ? null : dic.pessoas[c.pr[j]];
      var leg = c.lg[j] === null ? null : dic.legislaturas[c.lg[j]];
      var impacto = c.i[j];
      return {
        n: c.n[j], a: c.a[j], d: c.d[j], e: c.e[j], u: dic.url_detalhe.replace("{id}", String(id)),
        r: c.r[j], pb: c.pb[j], t: tema, g: desfecho[2], dx: desfecho[1],
        c: categoria, i: impacto,
        ef: Number(desfecho[0] === "virou_lei" && (impacto !== null ? impacto >= 2 : categoria !== "simbolica" && sinais.indexOf("autorizativa") < 0)),
        se: Number(categoria === "simbolica" || impacto === 0 || sinais.indexOf("autorizativa") >= 0),
        l: c.l[j], ld: c.ld[j], lt: c.lt[j], vp: c.vp[j],
        ls: c.ls[j] === null ? null : dic.url_detalhe.replace("{id}", String(c.ls[j])),
        dl: c.dl[j], o: dic.origens[c.o[j]], lg: leg,
        pt: principal && principal[2][leg] || "", pr: principal ? principal[0] : null,
        au: c.au[j].map(function (a) { var pessoa = dic.pessoas[a]; return [pessoa[1], pessoa[0]]; }),
        al: c.al[j].map(function (a) { return [dic.alertas[a[0]][1], dic.origens[a[1]], a[2]]; }),
        pol: c.pol[j], s: sinais, rp: c.rp[j]
      };
    });
  }

  // ------------------------------------------------- demais documentos (atividades)
  var COLUNAS_DOC = ["id", "tp", "n", "a", "d", "e", "st", "as", "au", "c", "sc", "h", "rs", "re", "dr", "pu", "pb", "b", "dp"];

  // As partes de documentos não levam build: a URL de cada arquivo já traz o hash do conteúdo. tp, c e sc
  // apontam para as enumerações estáveis de dic-doc; au, st e b, para os dicionários locais da própria parte
  // (pessoas: [slug, nome, 1 se há página], situacoes e bairros), como em fatia_documentos (gerar_site.py).
  function hidratarDocs(dic, fatia) {
    if (!dic || !fatia || dic.esquema !== 2 || fatia.esquema !== 2) throw new Error("Esquema incompatível");
    var c = fatia.colunas || {};
    COLUNAS_DOC.forEach(function (k) {
      if (!Array.isArray(c[k]) || c[k].length !== fatia.n) throw new Error("Coluna inválida: " + k);
    });
    var pessoas = fatia.pessoas, situacoes = fatia.situacoes, bairros = fatia.bairros;
    if (!Array.isArray(pessoas) || !Array.isArray(situacoes) || !Array.isArray(bairros)) throw new Error("Dicionário local inválido");
    return c.id.map(function (id, j) {
      var tipo = dic.tipos[c.tp[j]], categoria = dic.categorias[c.c[j]], sub = dic.subcategorias[c.sc[j]];
      var situacao = situacoes[c.st[j]], bairro = c.b[j] === null ? null : bairros[c.b[j]], pb = c.pb[j];
      if (!tipo || !categoria || !sub || situacao === undefined || bairro === undefined) throw new Error("Índice inválido no documento " + id);
      return {
        id: id, tipo: tipo[0], numero: c.n[j], ano: c.a[j], data: c.d[j], ementa: c.e[j],
        situacao: situacao, assunto: c.as[j],
        // [nome de exibição, slug ("" para quem não é vereador), 1 se há página do vereador]
        autores: c.au[j].map(function (i) {
          var p = pessoas[i];
          if (!p) throw new Error("Índice inválido no documento " + id);
          return [p[1], p[0], p[2] ? 1 : 0];
        }),
        categoria: categoria[0], subcategoria: sub[1], homenagem: c.h[j] === 1,
        respondido: c.rs[j] === 1, respondido_em: c.re[j], dias_ate_resposta: c.dr[j],
        publicado: c.pu[j] === 1, publicacao: pb ? { numero: pb[0], data: pb[1] } : null,
        bairro: bairro, detalhe_pendente: c.dp[j] === 1,
        url: dic.url_detalhe.replace("{id}", String(id))
      };
    });
  }

  function numeroInt(numero) {
    var n = parseInt(String(numero == null ? "" : numero).split("/")[0], 10);
    return isNaN(n) ? 0 : n;
  }

  // _n é a chave numérica calculada uma vez na hidratação (app.js); sem ela, vem do número.
  function chaveNumero(d) { return typeof d._n === "number" ? d._n : numeroInt(d.numero); }

  // Do mais recente ao mais antigo; mesma ordem de chave_documento (modelo.py) com reverse=True.
  function compararDocs(a, b) {
    var x = a.data || "", y = b.data || "";
    if (x !== y) return x < y ? 1 : -1;
    return (b.ano - a.ano) || (chaveNumero(b) - chaveNumero(a)) || (b.id - a.id);
  }

  function ordenada(lista) {
    for (var i = 1; i < lista.length; i++) if (compararDocs(lista[i - 1], lista[i]) > 0) return false;
    return true;
  }

  function mesclar2(a, b) {
    var saida = [], i = 0, j = 0;
    while (i < a.length && j < b.length) saida.push(compararDocs(a[i], b[j]) <= 0 ? a[i++] : b[j++]);
    while (i < a.length) saida.push(a[i++]);
    while (j < b.length) saida.push(b[j++]);
    return saida;
  }

  // Junta partes já ordenadas por compararDocs (cada uma sai do gerador nessa ordem) sem reordenar tudo;
  // uma parte fora de ordem é ordenada antes, por segurança. Não altera as listas recebidas.
  function mesclarDocs(listas) {
    var filas = (listas || []).map(function (l) { return ordenada(l) ? l : l.slice().sort(compararDocs); });
    if (!filas.length) return [];
    while (filas.length > 1) {
      var prox = [];
      for (var i = 0; i < filas.length; i += 2) prox.push(i + 1 < filas.length ? mesclar2(filas[i], filas[i + 1]) : filas[i]);
      filas = prox;
    }
    return filas[0].slice();
  }

  function cmp(x, y) { return x < y ? -1 : (x > y ? 1 : 0); }

  // Mesma ordem de _ordem_partes (paginas.py): parte mais recente primeiro.
  function ordemPartes(a, b) {
    return cmp(b.e.ate || "", a.e.ate || "") || cmp(b.e.ano || 0, a.e.ano || 0) || cmp(a.e.tipo || "", b.e.tipo || "") ||
      cmp(a.e.parte || 0, b.e.parte || 0) || cmp(a.nome, b.nome);
  }

  // Planeja quais arquivos de documentos carregar.
  // filtros: { tipo: "" | tipo | [tipos], ano: "" | "todos" | ano, autor: slug, completo: bool, alvo: itens desejados }.
  // Com autor, usa os arquivos ver/<slug>, sempre inteiros. Sem autor e sem `completo`, devolve o menor prefixo
  // das partes (da mais recente) que garante `alvo` itens em ordem: os itens com data maior que `fronteira`
  // já não podem ser precedidos por nada que falte carregar. `total` e `porTipo` vêm só do manifesto.
  function fatiasDocs(manifesto, filtros) {
    filtros = filtros || {};
    var arquivos = (manifesto && manifesto.arquivos) || {};
    var tipos = filtros.tipo ? [].concat(filtros.tipo) : null;
    var ano = filtros.ano && filtros.ano !== "todos" ? Number(filtros.ano) : null;
    var familia = filtros.autor ? "ver" : "doc";
    var candidatos = [];
    Object.keys(arquivos).forEach(function (nome) {
      var e = arquivos[nome];
      if (!e || e.familia !== familia) return;
      if (familia === "ver") {
        if (e.slug !== filtros.autor || (tipos && e.tipo && tipos.indexOf(e.tipo) < 0)) return;
      } else if ((tipos && tipos.indexOf(e.tipo) < 0) || (ano !== null && e.ano !== ano)) return;
      candidatos.push({ nome: nome, e: e });
    });
    candidatos.sort(ordemPartes);
    var total = 0, porTipo = {};
    candidatos.forEach(function (c) {
      total += c.e.n;
      if (c.e.tipo) porTipo[c.e.tipo] = (porTipo[c.e.tipo] || 0) + c.e.n;
    });
    var k = candidatos.length;
    if (familia === "doc" && !filtros.completo) {
      var alvo = Math.max(1, Number(filtros.alvo) || 1);
      for (k = 1; k < candidatos.length; k++) {
        var fronteira = candidatos[k].e.ate || "", seguros = 0;
        for (var i = 0; i < k; i++) if ((candidatos[i].e.de || "") > fronteira) seguros += candidatos[i].e.n;
        if (seguros >= alvo) break;
      }
      k = Math.min(k, candidatos.length);
    }
    return {
      nomes: candidatos.slice(0, k).map(function (c) { return c.nome; }),
      total: total, porTipo: porTipo, completo: k >= candidatos.length,
      fronteira: k < candidatos.length ? (candidatos[k].e.ate || "") : null
    };
  }

  var api = { hidratar: hidratar, fatiasPara: fatiasPara, norm: norm,
    hidratarDocs: hidratarDocs, fatiasDocs: fatiasDocs, compararDocs: compararDocs, numeroInt: numeroInt, mesclarDocs: mesclarDocs };
  if (typeof module !== "undefined") module.exports = api;
  if (raiz) raiz.RadarDados = api;
})(typeof window !== "undefined" ? window : null);
