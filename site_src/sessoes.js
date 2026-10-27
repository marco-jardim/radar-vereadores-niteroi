(function (raiz) {
  "use strict";

  // Contratos espelhados: fatia_votacoes (gerar_site.py), cartao_votacao e _mapa_votos
  // (pagina_sessoes.py). Notas técnicas só existem no HTML do servidor/Qualidade dos dados.
  var PASSO = 40;
  // Acima deste número de caracteres a ementa recolhida (CSS só com .js) ganha botão.
  var LIMIAR_EMENTA = 180;
  var COLUNAS = ["id", "s", "d", "ts", "m", "doc", "n", "e", "r", "t", "to", "cl", "sx", "mj", "q", "ql", "nt", "v"];
  var SENTIDOS = ["favor_mantem", "favor_derruba", "favor_aprova", "favor_rejeita"];
  var GLIFOS = { maioria: ["■", "com a maioria"], diferente: ["◆", "diferente da maioria"],
    abstencao: ["◐", "abstenção"], ausente: ["·", "ausente"], presidia: ["P", "presidia"], vazio: ["", "fora do mandato/não consta"] };
  var NOVA_ABA = '<span class="so-leitor"> (abre em nova aba)</span>';
  var REPO = "https://github.com/marco-jardim/radar-vereadores-niteroi";
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;" }[c];
  }); }
  function norm(s) { return String(s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase(); }
  function cmp(a, b) { return a < b ? -1 : a > b ? 1 : 0; }
  function dataBr(d) { return d ? d.split("-").reverse().join("/") : "—"; }
  function plural(n, um, varios) { return n + " " + (n === 1 ? um : varios); }
  function determinada(v) { return v.qualidade === "ok" && SENTIDOS.indexOf(v.sentido) >= 0; }

  function padrao(leg) { return { leg: leg, ano: "todos", classe: "dividida", materia: "todas", vereador: "", div: "", q: "", ordem: "recente" }; }
  function validarEstado(st, legs) {
    var leg = legs.find(function (l) { return l.id === st.leg; }) || legs[0];
    var r = padrao(leg.id);
    if ((leg.anos || []).map(String).indexOf(String(st.ano)) >= 0) r.ano = String(st.ano);
    ["classe", "materia", "ordem"].forEach(function (k) {
      var opcoes = { classe: ["dividida", "dissenso", "todas"], materia: ["todas", "veto", "pl", "pdl", "resolucao", "outra"], ordem: ["recente", "antigo", "apertada"] };
      if (opcoes[k].indexOf(st[k]) >= 0) r[k] = st[k];
    });
    if (/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(st.vereador || "") && (!leg.pessoas || leg.pessoas.indexOf(st.vereador) >= 0)) r.vereador = st.vereador;
    r.div = r.vereador && st.div === "1" ? "1" : "";
    r.q = String(st.q || "").trim();
    return r;
  }
  function lerUrl(consulta, legs) {
    var u = new URLSearchParams(consulta), st = {};
    Object.keys(padrao("")).forEach(function (k) { st[k] = u.get(k) || ""; });
    return validarEstado(st, legs);
  }
  function consultaUrl(st, legs) {
    st = validarEstado(st, legs);
    var base = padrao(legs[0].id), u = new URLSearchParams();
    Object.keys(base).forEach(function (k) { if (st[k] !== base[k]) u.set(k, st[k]); });
    return u.toString();
  }

  function hidratar(dic, fatia) {
    if (!dic || !fatia || dic.esquema !== 1 || fatia.esquema !== 1 || !Array.isArray(fatia.pessoas)) throw new Error("Esquema incompatível");
    var c = fatia.colunas || {}, codigos = dic.votos.map(function (v) { return v[0]; });
    COLUNAS.forEach(function (k) { if (!Array.isArray(c[k]) || c[k].length !== fatia.n) throw new Error("Coluna inválida: " + k); });
    return c.id.map(function (id, i) {
      if (typeof c.v[i] !== "string" || c.v[i].length !== fatia.pessoas.length) throw new Error("Votos desalinhados");
      var votos = Object.create(null), pessoas = Object.create(null);
      fatia.pessoas.forEach(function (p, j) {
        var codigo = c.v[i][j];
        if (codigos.indexOf(codigo) < 0) throw new Error("Voto desconhecido");
        pessoas[p[0]] = { slug: p[0], nome: p[1], pagina: !!p[2], condicao: p[3] };
        if (codigo !== ".") votos[p[0]] = dic.votos[codigos.indexOf(codigo)][1];
      });
      return { id: id, sessao: c.s[i], data: c.d[i], ano: fatia.ano, titulo_sessao: c.ts[i], materia: c.m[i],
        documento: c.n[i], numero: c.n[i].replace(/^.*?\s(?=\d)/, ""), ementa: c.e[i], resultado: c.r[i],
        url_documento: c.doc[i] === null ? "" : dic.url_detalhe + c.doc[i], totais: c.t[i], totais_oficiais: c.to[i],
        classe: c.cl[i], sentido: c.sx[i], maioria: c.mj[i] ? dic.votos[codigos.indexOf(c.mj[i])][1] : null,
        quorum: c.q[i], qualidade: c.ql[i], notas: c.nt[i], votos: votos, pessoas: pessoas };
    });
  }
  function rotulo(dic, v, slug) {
    if (v.qualidade === "inconsistente") return "placar inconsistente; sem atribuição nominal";
    var voto = v.votos[slug];
    if (voto === undefined) return "fora do mandato/não consta";
    var i = dic.votos.findIndex(function (p) { return p[1] === voto; });
    var sentido = determinada(v) ? v.sentido : "indeterminado";
    return i >= 0 && i < 7 ? dic.rotulos[v.materia][sentido][i] : "voto não determinado";
  }
  function recente(a, b) { return cmp(b.data || "", a.data || "") || cmp(String(b.id), String(a.id)); }
  function filtrar(lista, st) {
    var busca = norm(st.q);
    return lista.filter(function (v) {
      if (st.ano !== "todos" && String(v.ano) !== st.ano) return false;
      if (st.classe !== "todas" && v.classe !== st.classe) return false;
      if (st.materia !== "todas" && v.materia !== st.materia) return false;
      if (st.vereador && (v.qualidade === "inconsistente" || v.votos[st.vereador] === undefined)) return false;
      if (st.div === "1" && (!st.vereador || !determinada(v) || ["Favor", "Contra"].indexOf(v.maioria) < 0 ||
        ["Favor", "Contra"].indexOf(v.votos[st.vereador]) < 0 || v.votos[st.vereador] === v.maioria)) return false;
      return !busca || norm([v.documento, v.ementa, v.resultado, v.titulo_sessao, v.data,
        Object.keys(v.votos).map(function (s) { return v.pessoas[s].nome; }).join(" ")].join(" ")).indexOf(busca) >= 0;
    }).sort(function (a, b) {
      if (st.ordem === "antigo") return -recente(a, b);
      // Margem absoluta Favor/Contra, sem confundir opção majoritária com quórum legal.
      if (st.ordem === "apertada") {
        var margem = function (v) { return v.qualidade === "inconsistente" ? Infinity : Math.abs(v.totais[0] - v.totais[1]); };
        return cmp(margem(a), margem(b)) || recente(a, b);
      }
      return recente(a, b);
    });
  }
  function paginar(lista, mostrando) { return lista.slice(mostrando, mostrando + PASSO); }
  function contagem(lista) {
    return plural(lista.length, "votação", "votações") + " · " + plural(lista.filter(function (v) { return v.materia === "veto"; }).length, "veto", "vetos") +
      " · " + plural(lista.filter(function (v) { return v.materia === "pl"; }).length, "projeto de lei", "projetos de lei");
  }
  function nome(p, chip) {
    var texto = esc(p.nome), status = p.condicao ? '<span class="status">' + esc(p.condicao) + '</span>' : "";
    if (p.pagina) return '<a' + (chip ? ' class="chip"' : "") + ' href="vereadores/' + esc(p.slug) + '.html">' + texto + '</a>' + (chip ? "" : status);
    return chip ? '<span class="chip">' + texto + status + '</span>' : texto + status;
  }
  function placar(dic, v) {
    var oficial = v.qualidade === "inconsistente", t = (oficial && v.totais_oficiais) || v.totais, partes = [], textos = [];
    var genericos = ["Favor ao parecer", "Contra o parecer", "Abstenção", "Ausentes", "Branco", "Nulo"];
    t.forEach(function (n, i) {
      if (!n) return;
      var classe = ["voto-abstencao", "voto-abstencao", "voto-abstencao", "ausente", "licenca", "licenca"][i], texto;
      if (i < 2) {
        var voto = i === 0 ? "Favor" : "Contra";
        texto = genericos[i];
        if (determinada(v)) {
          texto = rotulo(dic, Object.assign({}, v, { votos: { pessoa: voto } }), "pessoa").replace(/^votou /, "");
          if (v.maioria) classe = voto === v.maioria ? "voto-maioria" : "voto-diferente";
        }
        texto = n + " " + texto;
      } else texto = plural(n, ["", "", "abstenção", "ausente", "voto em branco", "voto nulo"][i], ["", "", "abstenções", "ausentes", "votos em branco", "votos nulos"][i]);
      textos.push(texto);
      partes.push('<i class="s-' + classe + '" style="flex:' + Number(n) + '" aria-hidden="true"></i>');
    });
    var resumo = textos.join(" · "), descricao = (oficial ? "Placar oficial: " : "Placar nominal: ") + resumo;
    if (!oficial && !determinada(v)) descricao += " · sentido não determinado";
    if (determinada(v)) {
      var extras = t.slice(2).map(function (n, i) { return n ? plural(n, ["abstenção", "ausente", "em branco", "nulo"][i], ["abstenções", "ausentes", "em branco", "nulos"][i]) : ""; }).filter(Boolean);
      resumo = (v.quorum ? [v.quorum[2] + " para manter", v.quorum[1] + " para derrubar"] : textos.slice(0, Number(!!t[0]) + Number(!!t[1]))).concat(extras).join(" · ") || "sem votos substantivos";
    }
    return '<div class="mini-barra" role="img" aria-label="' + esc(descricao) + '">' + partes.join("") + '</div><p class="mini-n">' + esc(resumo || "Placar não informado") + '</p>';
  }
  function legivel(t) {
    var letras = t.replace(/[^A-Za-zÀ-ÿ]/g, "");
    if (!letras.length || letras.replace(/[^A-ZÀ-Þ]/g, "").length / letras.length < 0.7) return t;
    var siglas = "sus cras creas caps lgbt lgbtqia+ pcd tea ubs upa iptu iss ccj cmn rj ong oab pm gm eja enem".split(" ");
    var proprios = { "niterói": "Niterói", niteroi: "Niterói", "icaraí": "Icaraí", rio: "Rio", janeiro: "Janeiro", brasil: "Brasil" };
    var s = t.toLowerCase().split(" ").map(function (p) {
      var nucleo = p.replace(/^[“”"'(),.;:]+|[“”"'(),.;:]+$/g, "");
      return siglas.indexOf(nucleo) >= 0 ? p.replace(nucleo, nucleo.toUpperCase()) : proprios[nucleo] ? p.replace(nucleo, proprios[nucleo]) : p;
    }).join(" ").replace(/^ementa:\s*/, "");
    return s.charAt(0).toUpperCase() + s.slice(1);
  }
  function cartao(dic, v, vereador) {
    var url = v.url_documento, documento = v.documento || "Documento não identificado";
    var titulo = url ? '<a href="' + esc(url) + '" target="_blank" rel="noopener">' + esc(documento) + NOVA_ABA + '</a>' : esc(documento);
    var atributos = ["ano", "materia", "classe", "sentido", "qualidade"].map(function (k) { return ' data-' + k + '="' + esc(v[k]) + '"'; }).join("");
    var notas = v.notas.map(function (n) {
      var classe = /^Derrubar o veto exige/.test(n) ? "quorum" : /^Favor ao parecer \/ Contra/.test(n) ? "fonte-sentido sentido-indeterminado" : /^Sentido definido/.test(n) ? "fonte-sentido" : "qualidade-voto";
      return '<p class="nota ' + classe + '">' + (classe === "qualidade-voto" ? "ⓘ " : "") + esc(n) + '</p>';
    }).join("");
    var grupos = new Map();
    if (v.qualidade !== "inconsistente") Object.keys(v.votos).sort(function (a, b) { return cmp(v.pessoas[a].nome, v.pessoas[b].nome) || cmp(a, b); }).forEach(function (s) {
      var r = rotulo(dic, v, s);
      if (!grupos.has(r)) grupos.set(r, []);
      grupos.get(r).push(nome(v.pessoas[s], true));
    });
    var nomes = v.qualidade === "inconsistente" ? "" : '<details class="votos-nomes"><summary>Como votou cada vereador</summary>' + Array.from(grupos.keys()).sort().map(function (r) {
      return '<div class="grupo-votos"><h4>' + esc(r) + ' (' + grupos.get(r).length + ')</h4><p>' + grupos.get(r).join(" ") + '</p></div>';
    }).join("") + '</details>';
    var pessoal = vereador ? '<p class="nota voto-pessoal"><strong>' + esc(v.pessoas[vereador] ? v.pessoas[vereador].nome : vereador) + '</strong>: ' + esc(rotulo(dic, v, vereador)) + '</p>' : "";
    var acoes = url ? '<p class="acoes-item"><button type="button" class="ver-siscam" data-url="' + esc(url) + '" data-rotulo="' + esc(documento) + '">Ver no SISCAM<span class="so-leitor"> (' + esc(documento) + ')</span></button> <a class="abrir-siscam" href="' + esc(url) + '" target="_blank" rel="noopener">abrir no SISCAM<span class="so-leitor"> (' + esc(documento) + ')</span>' + NOVA_ABA + '</a></p>' : '<p class="nota">Sem link do documento no SISCAM.</p>';
    var consulta = new URLSearchParams({ title: "Sessões: " + documento, body: "Sessão: " + v.titulo_sessao + "\nVotação: " + v.id + "\n" + (url || "") });
    return '<li class="projeto votacao" id="v-' + esc(v.id) + '"' + atributos + '><p class="cab">' + titulo + '<span>' + esc(dataBr(v.data)) + '</span><span>' + esc(v.titulo_sessao || "Sessão não identificada") + '</span></p><p class="desfecho">Resultado oficial: ' + esc(v.resultado || "não informado") + '</p><p class="ementa">' + esc(legivel(v.ementa || "Ementa não disponível na base coletada.")) + '</p>' + placar(dic, v) + notas + pessoal + nomes + acoes + '<a class="contestar" href="' + REPO + '/issues/new?' + esc(consulta.toString()) + '">contestar</a></li>';
  }

  // Comportamento, não marcação do cartão: o mesmo .ementa é recolhido/expandido, sem duplicar texto.
  // Também recebe botão a ementa curta que já transborda as duas linhas (telas estreitas).
  function ementas(cartoes) {
    Array.prototype.forEach.call(cartoes, function (li) {
      var e = li.querySelector && li.querySelector(".ementa");
      if (!e || e.id || (e.textContent.trim().length <= LIMIAR_EMENTA && !(e.scrollHeight > e.clientHeight + 1))) return;
      e.id = li.id + "-ementa";
      e.insertAdjacentHTML("afterend", '<button type="button" class="link ver-ementa" aria-expanded="false" aria-controls="' + esc(e.id) + '">Ver ementa completa</button>');
    });
  }
  function alternarEmenta(bt, doc) {
    var e = doc.getElementById(bt.getAttribute("aria-controls")), aberta = bt.getAttribute("aria-expanded") !== "true";
    if (!e) return;
    e.classList.toggle("ementa-aberta", aberta);
    bt.setAttribute("aria-expanded", String(aberta));
    bt.textContent = aberta ? "Ver menos" : "Ver ementa completa";
  }

  function limiteFaixa(v) {
    if (v.qualidade === "inconsistente") return "placar inconsistente; sem atribuição nominal";
    if (!determinada(v)) return "sentido não determinado";
    return ["Favor", "Contra"].indexOf(v.maioria) < 0 ? "sem maioria (empate)" : "";
  }
  function votoFaixa(v, slug) {
    var limite = limiteFaixa(v), voto = v.votos[slug], classe;
    if (v.qualidade === "inconsistente") return ["cru", "—", limite];
    if (voto === undefined) classe = "vazio";
    else if (limite) return ["cru", voto, voto + "; " + limite + "; sem comparação com a maioria"];
    else if (voto === "Favor" || voto === "Contra") classe = voto === v.maioria ? "maioria" : "diferente";
    else classe = { "Abstenção": "abstencao", Ausente: "ausente", Presidente: "presidia" }[voto];
    return classe ? [classe].concat(GLIFOS[classe]) : ["cru", voto, voto];
  }
  function cabecalhoFaixa(v) {
    var numero = String(v.numero || "").split("/")[0], sigla = { pl: "PL", pdl: "PDL", resolucao: "PR", veto: "Veto" }[v.materia];
    var curto = sigla && numero ? sigla + " " + numero : v.documento.replace(/\/\d{4}\b/g, ""), data = dataBr(v.data), limite = limiteFaixa(v);
    return '<th scope="col"' + (limite ? ' class="faixa-sem-comparacao"' : "") + '><a href="#v-' + esc(v.id) + '"><abbr title="' + esc(v.documento + ", " + data) + '">' + esc(data.slice(0, 5)) + '</abbr><br>' + esc(curto) + (limite ? '<span aria-hidden="true"> *</span><span class="so-leitor"> · ' + esc(limite) + '</span>' : "") + '</a></th>';
  }
  // Retorna o conteúdo de .faixa-votos. A composição vem do servidor, não dos nomes brutos dos votos.
  function faixa(lista, membros, leg, ano, vereador) {
    ano = Number(ano);
    var votacoes = lista.filter(function (v) { return v.classe === "dividida" && Number(v.ano) === Number(ano); }).sort(function (a, b) { return -recente(a, b); });
    if (!votacoes.length) return '<p class="vazio">Nenhuma votação dividida disponível para o mapa neste ano.</p>';
    var resumo = [], linhas = membros.slice().sort(function (a, b) { return cmp(a.nome.toLowerCase(), b.nome.toLowerCase()) || cmp(a.slug, b.slug); }).map(function (p) {
      var contagens = { maioria: 0, diferente: 0, abstencao: 0, ausente: 0 }, celulas = votacoes.map(function (v) {
        var c = votoFaixa(v, p.slug);
        if (contagens[c[0]] !== undefined) contagens[c[0]] += 1;
        return '<td class="voto-' + c[0] + (limiteFaixa(v) ? ' faixa-sem-comparacao' : '') + '"><span aria-hidden="true">' + esc(c[1]) + '</span><span class="so-leitor">' + esc(c[2]) + '</span></td>';
      }).join("");
      var inicio = '<tr data-vereador="' + esc(p.slug) + '"' + (p.slug === vereador ? ' class="vereador-destaque"' : '') + '><th scope="row">' + nome(p, false) + '</th>';
      resumo.push('<tr><th scope="row">' + nome(p, false) + '</th>' + Object.keys(contagens).map(function (k) { return '<td>' + contagens[k] + '</td>'; }).join("") + '</tr>');
      return inicio + celulas + '</tr>';
    });
    var legenda = Object.keys(GLIFOS).map(function (c) { var g = GLIFOS[c]; return '<li><span class="glifo-voto voto-' + c + '" aria-hidden="true">' + g[0] + '</span>' + esc(g[0] ? g[1] : "Célula vazia: " + g[1]) + '</li>'; }).join("");
    var titulo = 'Resumo por vereador · votações divididas de ' + ano;
    return '<h3>Votações divididas de ' + ano + '</h3><ul class="leg-graf leg-votos" aria-label="Legenda do mapa de votos">' + legenda + '</ul><p class="nota">Linhas parecidas indicam votos parecidos nas votações divididas deste ano; não indicam grupo político. Nomes em ordem alfabética, sem agrupamento por voto.</p>' +
      '<div class="faixa-rolagem" role="region" tabindex="0" aria-label="Mapa de votos de ' + ano + ', legislatura ' + esc(leg.rotulo) + ': tabela com rolagem horizontal"><table class="faixa"><caption>Vereador × votação dividida de ' + ano + ', em ordem cronológica. A cor compara o voto à opção mais votada entre Favor e Contra, independentemente do sentido do parecer. * Coluna sem comparação: empate, sentido não determinado ou placar inconsistente.</caption><thead><tr><th scope="col">Vereador</th>' + votacoes.map(cabecalhoFaixa).join("") + '</tr></thead><tbody>' + linhas.join("") + '</tbody></table></div>' +
      '<div class="tabela-graf tabela-resumo" role="region" tabindex="0" aria-label="' + titulo + '"><table><caption>' + titulo + '</caption><thead><tr>' + ["Vereador", "Com a maioria", "Diferente da maioria", "Abstenção", "Ausente"].map(function (c) { return '<th scope="col">' + c + '</th>'; }).join("") + '</tr></thead><tbody>' + resumo.join("") + '</tbody></table></div><p class="nota">O resumo conta apenas as colunas com comparação determinada. Presidência, células vazias, votos em branco/nulos e colunas marcadas não entram nessas quatro contagens. <a href="#divididas-' + esc(leg.id) + '">Ver outros anos nas listas de votações</a>.</p>';
  }
  // Mesmo escape de app.js, inclusive neutralização de fórmulas de planilha.
  function celulaCsv(v) {
    var s = String(v == null ? "" : v);
    if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;
    return '"' + s.replace(/"/g, '""') + '"';
  }
  function csv(dic, lista) {
    var linhas = [["data", "sessao", "documento", "resultado", "classe", "vereador", "voto", "rotulo"]];
    lista.forEach(function (v) {
      // Produto pessoa × votação, inclusive "não consta". Inconsistentes nunca atribuem votos.
      Object.keys(v.pessoas).sort().forEach(function (s) {
        var classe = dic.classes.find(function (c) { return c[0] === v.classe; });
        linhas.push([v.data, v.titulo_sessao, v.documento, v.resultado, classe ? classe[1] : v.classe, v.pessoas[s].nome,
          v.qualidade === "inconsistente" ? "" : (v.votos[s] || "não consta"), rotulo(dic, v, s)]);
      });
    });
    return "\ufeff" + linhas.map(function (l) { return l.map(celulaCsv).join(","); }).join("\n");
  }

  var api = { PASSO: PASSO, LIMIAR_EMENTA: LIMIAR_EMENTA, ementas: ementas, alternarEmenta: alternarEmenta, padrao: padrao, lerUrl: lerUrl, consultaUrl: consultaUrl, validarEstado: validarEstado,
    hidratar: hidratar, rotulo: rotulo, filtrar: filtrar, paginar: paginar, contagem: contagem,
    cartao: cartao, faixa: faixa, votoFaixa: votoFaixa, celulaCsv: celulaCsv, csv: csv, iniciar: iniciar };
  if (typeof module !== "undefined") module.exports = api;
  if (raiz) { raiz.RadarSessoes = api; iniciar(raiz); }

  function iniciar(janela) {
    var doc = janela.document, carregador = janela.RadarArquivos, raizHtml = doc.documentElement;
    // Sem .js (navegacao.js falhou) a ementa já aparece inteira: nenhum botão.
    var comJs = !raizHtml || !raizHtml.classList || raizHtml.classList.contains("js");
    function marcar(el) { if (comJs && el.querySelectorAll) ementas(el.querySelectorAll("li.votacao")); }
    marcar(doc);
    // Único listener de click no documento deste script; os cartões do servidor também o usam.
    if (doc.addEventListener) {
      doc.addEventListener("click", function (ev) {
        var bt = ev.target.closest && ev.target.closest(".ver-ementa");
        if (bt) alternarEmenta(bt, doc);
      });
      // toggle não propaga: a captura alcança também os cartões antes sem dimensões.
      doc.addEventListener("toggle", function (ev) {
        if (ev.target.tagName === "DETAILS" && ev.target.open) marcar(ev.target);
      }, true);
    }
    if (typeof janela.addEventListener === "function") {
      var esperaEmentas;
      janela.addEventListener("resize", function () {
        janela.clearTimeout(esperaEmentas);
        esperaEmentas = janela.setTimeout(function () { marcar(doc); }, 160);
      });
    }
    var forms = Array.from(doc.querySelectorAll("form.filtros-sessoes"));
    if (!forms.length || !carregador) return;
    var manifestoInicial = carregador.manifesto();
    // Há sessões sem nenhuma votação: nesse caso o gerador não exporta dic-ses nem vot-*.
    if (manifestoInicial && !manifestoInicial.arquivos["dic-ses"]) return;
    var legs = forms.map(function (f) {
      return { id: f.dataset.leg, rotulo: f.dataset.leg.replace("-", "–"),
        anos: Array.from(f.elements.ano.options).map(function (o) { return o.value; }).filter(function (a) { return a !== "todos"; }),
        pessoas: Array.from(f.elements.vereador.options).map(function (o) { return o.value; }).filter(Boolean) };
    });
    var inicial = lerUrl(janela.location.search, legs);
    forms.forEach(function (form, indice) {
      var leg = legs[indice], bloco = doc.getElementById("sessoes-leg-" + leg.id), secao = doc.getElementById("divididas-" + leg.id);
      var lista = doc.getElementById("lista-votacoes-" + leg.id), contador = doc.getElementById("contagem-votacoes-" + leg.id);
      var mais = secao.querySelector('[data-acao="mais"]'), botaoCsv = form.querySelector('[data-acao="csv"]');
      var mapa = doc.getElementById("faixa-" + leg.id), mapaInicial = mapa.innerHTML, anoMapa = mapa.dataset.ano;
      var membros = Array.from(mapa.querySelectorAll(".faixa tbody tr")).map(function (tr) {
        var th = tr.querySelector("th"), a = th.querySelector("a"), status = th.querySelector(".status");
        return { slug: tr.dataset.vereador, nome: a ? a.textContent : th.textContent.replace(status ? status.textContent : "", ""),
          pagina: !!a, condicao: status ? status.textContent : "" };
      });
      var st = inicial.leg === leg.id ? inicial : padrao(leg.id), dic, filtradas = null, mostrando = 0, pedido = 0;
      var continuacao = secao.querySelector(".mais-votacoes"), vazioServidor = secao.querySelector("p.vazio");
      function preencher() {
        Object.keys(st).forEach(function (k) { if (form.elements[k]) {
          if (k === "div") form.elements[k].checked = st.div === "1";
          else form.elements[k].value = st[k];
        } });
        form.elements.div.disabled = !st.vereador;
      }
      function estado() {
        var r = { leg: leg.id };
        Object.keys(padrao(leg.id)).forEach(function (k) { if (k !== "leg") r[k] = k === "div" ? (form.elements[k].checked ? "1" : "") : form.elements[k].value; });
        return validarEstado(r, legs);
      }
      function gravar() {
        var q = consultaUrl(st, legs);
        janela.history.replaceState(null, "", janela.location.pathname + (q ? "?" + q : "") + janela.location.hash);
      }
      function destacar() {
        mapa.querySelectorAll("tr[data-vereador]").forEach(function (tr) { tr.classList.toggle("vereador-destaque", tr.dataset.vereador === st.vereador); });
      }
      // foco: índice do primeiro cartão novo de "Mostrar mais"; recebe o foco mesmo quando o botão some.
      function renderizar(alvo, foco) {
        var novos = filtradas.slice(mostrando, alvo);
        lista.insertAdjacentHTML("beforeend", novos.map(function (v) { return cartao(dic, v, st.vereador); }).join(""));
        mostrando += novos.length;
        mais.hidden = mostrando >= filtradas.length;
        mais.textContent = "Mostrar mais " + Math.min(PASSO, filtradas.length - mostrando);
        contador.textContent = (foco >= 0 && mostrando > foco ? plural(mostrando - foco, "votação adicionada", "votações adicionadas") + " · " : "") +
          contagem(filtradas) + " · mostrando " + mostrando + " de " + filtradas.length;
        marcar(lista);
        var v = foco >= 0 && filtradas[Math.min(foco, filtradas.length - 1)], alvoFoco = v && doc.getElementById("v-" + v.id);
        if (alvoFoco) { alvoFoco.setAttribute("tabindex", "-1"); alvoFoco.focus(); }
      }
      function carregar(alvo, escreverUrl, destino, foco) {
        st = estado(); preencher();
        if (escreverUrl) gravar();
        var atual = ++pedido, m = carregador.manifesto(), anos = st.ano === "todos" ? leg.anos : [st.ano];
        var nomes = ["dic-ses"].concat(anos.map(function (a) { return "vot-" + a; }).filter(function (n) { return !m || !!m.arquivos[n]; }));
        lista.setAttribute("aria-busy", "true"); botaoCsv.disabled = true; mais.disabled = true;
        contador.textContent = "Carregando votações…";
        return carregador.carregar(nomes).then(function (pacote) {
          if (atual !== pedido) return;
          dic = pacote.arquivos[0];
          var todas = pacote.arquivos.slice(1).flatMap(function (f) { return hidratar(dic, f); });
          filtradas = filtrar(todas, st);
          if (continuacao) { continuacao.remove(); continuacao = null; }
          if (vazioServidor) { vazioServidor.remove(); vazioServidor = null; }
          mostrando = 0; lista.innerHTML = "";
          if (!filtradas.length) lista.innerHTML = '<li class="vazio">Nenhuma votação com esses filtros. <button type="button" class="link" data-acao="limpar">Limpar filtros</button>.</li>';
          if (destino) alvo = Math.max(alvo, filtradas.findIndex(function (v) { return "v-" + v.id === destino; }) + 1);
          renderizar(alvo, foco);
          if (st.ano === "todos") { mapa.innerHTML = mapaInicial; mapa.dataset.ano = anoMapa; }
          else { mapa.innerHTML = faixa(todas, membros, leg, st.ano, st.vereador); mapa.dataset.ano = st.ano; }
          destacar();
          lista.setAttribute("aria-busy", "false"); botaoCsv.disabled = false; mais.disabled = false;
          return true;
        }).catch(function (erro) {
          if (atual !== pedido) return;
          lista.setAttribute("aria-busy", "false"); mais.disabled = true;
          if (continuacao) { continuacao.hidden = false; mais.hidden = true; }
          contador.textContent = erro && erro.atualizado ? "Site atualizado, recarregue a página" : "Não foi possível carregar os dados. Tente mudar um filtro ou recarregue a página.";
        });
      }
      function limpar() { st = padrao(leg.id); preencher(); carregar(PASSO, true); }
      function baixar() {
        var a = doc.createElement("a"), url = janela.URL.createObjectURL(new janela.Blob([csv(dic, filtradas)], { type: "text/csv;charset=utf-8" }));
        a.href = url; a.download = "radar-vereadores-votacoes.csv"; a.click();
        janela.setTimeout(function () { janela.URL.revokeObjectURL(url); }, 1000);
      }
      preencher(); form.hidden = false;
      if (inicial.leg === leg.id) bloco.open = true;
      if (inicial.leg === leg.id && janela.location.search) gravar();
      var alvoHash = /^#v-/.test(janela.location.hash) ? doc.getElementById(janela.location.hash.slice(1)) : null;
      if ((alvoHash && bloco.contains(alvoHash)) || janela.location.hash === "#" + bloco.id) bloco.open = true;
      form.addEventListener("submit", function (ev) { ev.preventDefault(); carregar(PASSO, true); });
      form.addEventListener("change", function () { carregar(PASSO, true); });
      var espera;
      form.elements.q.addEventListener("input", function () { janela.clearTimeout(espera); espera = janela.setTimeout(function () { carregar(PASSO, true); }, 160); });
      secao.addEventListener("click", function (ev) {
        var bt = ev.target.closest && ev.target.closest("button[data-acao]");
        if (!bt) return;
        if (bt.dataset.acao === "limpar") limpar();
        if (bt.dataset.acao === "mais") {
          // Antes da primeira carga a lista do servidor mostrava PASSO cartões.
          if (!filtradas) carregar(PASSO * 2, true, null, PASSO);
          else { renderizar(mostrando + PASSO, mostrando); gravar(); }
        }
        if (bt.dataset.acao === "csv" && filtradas && !botaoCsv.disabled) baixar();
        else if (bt.dataset.acao === "csv" && !filtradas && !botaoCsv.disabled) {
          // O primeiro CSV precisa do recorte completo, não só dos cartões iniciais.
          carregar(PASSO, true).then(function (ok) { if (ok) baixar(); });
        }
      });
      mapa.addEventListener("click", function (ev) {
        var a = ev.target.closest && ev.target.closest('a[href^="#v-"]');
        if (!a) return;
        var destino = a.getAttribute("href").slice(1);
        // A coluna pode apontar para um cartão fora dos filtros ou dos primeiros 40.
        ev.preventDefault();
        st = padrao(leg.id); st.ano = mapa.dataset.ano || "todos"; preencher();
        carregar(PASSO, true, destino).then(function (ok) {
          var cartao = doc.getElementById(destino);
          if (ok && cartao) { cartao.setAttribute("tabindex", "-1"); cartao.focus(); cartao.scrollIntoView(); }
        });
      });
      // Preserva a primeira pintura e as notas técnicas do servidor. Só a consulta/ação
      // carrega o recorte completo; sem consulta a carga inicial é dic-ses + último ano.
      if (inicial.leg === leg.id && consultaUrl(st, [leg])) carregar(PASSO, false);
      else if (inicial.leg === leg.id) {
        var m = carregador.manifesto(), nomeAno = m && leg.anos.map(function (a) { return "vot-" + a; }).find(function (n) { return m.arquivos[n]; });
        if (m && m.arquivos["dic-ses"]) carregador.carregar(["dic-ses"].concat(nomeAno ? [nomeAno] : [])).catch(function () { /* O HTML continua disponível; a próxima ação tenta de novo. */ });
      }
      if (continuacao) {
        // Links das fichas individuais podem apontar para além dos primeiros 40.
        var abrirContinuacao = alvoHash && continuacao.contains(alvoHash);
        continuacao.hidden = !abrirContinuacao; continuacao.open = !!abrirContinuacao; mais.hidden = !!abrirContinuacao;
      }
      if (inicial.leg !== leg.id || !consultaUrl(st, [leg])) {
        var cartoes = Array.from(secao.querySelectorAll("li.votacao"));
        contador.textContent = contagem(cartoes.map(function (c) { return { materia: c.dataset.materia }; }));
      }
    });
  }
})(typeof window !== "undefined" ? window : null);
