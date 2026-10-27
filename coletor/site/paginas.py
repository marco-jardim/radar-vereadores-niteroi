"""Páginas HTML do site."""
from __future__ import annotations

import gzip
import hashlib
import html
import json
import re
import statistics
import unicodedata
from collections import Counter, defaultdict
from functools import cmp_to_key
from pathlib import Path

from coletor import novidades as N
from coletor.classificar import ALERTAS, CATEGORIAS, CONFIANCA_MINIMA
from coletor.site import graficos as G
from coletor.site.modelo import (
    DESC_CATEGORIA_DOC, DESC_SINAL, DESFECHO_GRUPO, NOME_ALERTA, NOME_CATEGORIA, NOME_CATEGORIA_DOC, NOME_DESFECHO, NOME_EIXO,
    NOME_IMPACTO, NOME_SINAL, NOME_SUBCATEGORIA_DOC, NOME_TEMA, NOME_TIPO_DOC, TIPOS_DOC, com_efeito, mediana_legislatura,
    sem_efeito, situacao_lei, url_lei,
    anos_documentos, coleta_do_modelo, documentos_por_legislatura, homenagens_do_autor, homenagens_por_ano,
    indicacoes_por_bairro, menos_citados, ranking_orgaos, resumo_bairros, resumo_informacao,
)

REPO = "https://github.com/marco-jardim/radar-vereadores-niteroi"
NAV = [
    ("index.html", "Início"),
    ("novidades.html", "Novidades"),
    ("leis.html", "Leis aprovadas"),
    ("projetos.html", "Projetos"),
    ("atividades.html", "Atividades"),
    ("sessoes.html", "Sessões"),
    ("ruido.html", "Sem efeito e polêmicas"),
    ("analises.html", "Análises"),
    ("metodologia.html", "Metodologia"),
]
CLASSE_IMPACTO = {3: "imp-3", 2: "imp-2", 1: "imp-1", 0: "imp-0", None: "imp-x"}
FONTE_ESTATICA = Path(__file__).resolve().parents[2] / "site_src"
# Antes do CSS: marca "js" (menu móvel já recolhido na primeira pintura) só se navegacao.js puder montar o menu,
# e aplica o tema salvo. navegacao.js tira a classe se não montar o menu; o onerror da sua tag também.
SCRIPT_CABECA = '(function(d,r){if(window.matchMedia&&d.addEventListener)r.classList.add("js");try{var t=localStorage.getItem("radar-tema");if(t==="claro"||t==="escuro")r.dataset.theme=t==="escuro"?"dark":"light"}catch(e){}})(document,document.documentElement)'
ERRO_NAVEGACAO = "document.documentElement.classList.remove('js')"
LIMITE_ITENS_RUIDO = 30
PASSO_LISTA = 40  # itens por "Mostrar mais"; igual a PASSO em site_src/app.js
# Sem filtros, projetos.html carrega só a prévia (pl-recentes, as PASSO_LISTA primeiras linhas) e traz o resumo
# exato no HTML (resumo_projetos); as três fatias completas vêm depois da primeira pintura (app.js).
INICIAIS_PL = {"leis.html": ["dic-pl", "pl-lei"], "projetos.html": ["dic-pl", "pl-recentes"]}
CHIPS_IMPACTO = (("3", "Alto"), ("2", "Médio"), ("1", "Baixo"), ("0", "Sem efeito"), ("x", "Não avaliado"))
SISCAM = "https://consultaniteroi.siscam.com.br/"
NOVA_ABA = '<span class="so-leitor"> (abre em nova aba)</span>'
# O detalhe do SISCAM é aberto num <dialog> nativo (app.js cria o iframe). O link comum fica sempre visível,
# para o caso de o SISCAM passar a bloquear a exibição incorporada.
DIALOGO_SISCAM = f"""<dialog id="siscam-dialogo" class="dialogo-siscam" aria-labelledby="siscam-titulo">
 <div class="dialogo-caixa">
  <div class="dialogo-cab">
   <h2 id="siscam-titulo">Detalhe no SISCAM</h2>
   <a id="siscam-abrir" href="{SISCAM}" target="_blank" rel="noopener">abrir no SISCAM{NOVA_ABA}</a>
   <button type="button" id="siscam-fechar" class="fechar" autofocus>Fechar</button>
  </div>
  <p class="dialogo-nota">Página do SISCAM exibida aqui dentro. Se ela não aparecer, use o link “abrir no SISCAM”.</p>
  <div id="siscam-quadro" class="dialogo-quadro"></div>
 </div>
</dialog>"""


def esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


def data_br(iso: str | None) -> str:
    if not iso:
        return "—"
    a, m, d = iso.split("-")
    return f"{d}/{m}/{a}"


SIGLAS = {"sus", "cras", "creas", "caps", "lgbt", "lgbtqia+", "pcd", "tea", "ubs", "upa", "iptu", "iss", "ccj", "cmn", "rj", "ong", "oab", "pm", "gm", "eja", "enem"}
NOMES_PROPRIOS = {"niterói": "Niterói", "niteroi": "Niterói", "icaraí": "Icaraí", "rio": "Rio", "janeiro": "Janeiro", "brasil": "Brasil"}


def legivel(texto: str) -> str:
    """Converte ementas em caixa alta para frase normal, preservando siglas e nomes conhecidos."""
    letras = [c for c in texto if c.isalpha()]
    if not letras or sum(c.isupper() for c in letras) / len(letras) < 0.7:
        return texto
    palavras = texto.lower().split(" ")
    saida = []
    for i, p in enumerate(palavras):
        nucleo = p.strip("“”\"'(),.;:")
        if nucleo in SIGLAS:
            p = p.replace(nucleo, nucleo.upper())
        elif nucleo in NOMES_PROPRIOS:
            p = p.replace(nucleo, NOMES_PROPRIOS[nucleo])
        saida.append(p)
    t = " ".join(saida)
    t = re.sub(r"^(ementa:\s*)", "", t)
    return t[:1].upper() + t[1:]


def milhar(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def plural(n: int, um: str, varios: str) -> str:
    return f"{n} {um if n == 1 else varios}"


def versao_bytes(conteudo: bytes) -> str:
    return hashlib.sha1(conteudo).hexdigest()[:10]


def publicavel(relativo: Path) -> bool:
    """Regra única de publicação de arquivos da árvore estática."""
    return not any(parte.startswith(".") for parte in relativo.parts) and relativo.suffix.lower() != ".md"


def css_publicado(texto: str, base_dir: Path, *, origem: Path | None = None,
                  raiz: Path | None = None, _pilha: tuple[Path, ...] = ()) -> str:
    """Versiona referências locais em url(), @import e image-set, sem publicar alvos excluídos."""
    raiz = (raiz or FONTE_ESTATICA).resolve()
    string = r'"(?:\\.|[^"\\])*"' + r"|'(?:\\.|[^'\\])*'"
    padrao = r'''(?<![\w-])url\(\s*(?:"(?P<duplas>[^"]*)"|'(?P<simples>[^']*)'|(?P<sem_aspas>(?:\\.|[^\s)'\"])+))\s*\)'''

    def versionar(url: str, sem_aspas: bool = False) -> str:
        if not url or url.startswith(("/", "#")) or "?" in url or re.match(r"[a-z][a-z0-9+.-]*:", url, re.I):
            return url
        if sem_aspas and ("\\" in url or "%" in url):
            raise ValueError(f"CSS {origem or base_dir}: alvo {url!r}: URL com escape não suportada")
        nome, separador, fragmento = url.partition("#")
        alvo = (base_dir / nome).resolve()
        try:
            relativo = alvo.relative_to(raiz)
            if not publicavel(relativo):
                raise ValueError("alvo excluído da publicação")
            versao = versao_bytes(bytes_estaticos(alvo, _pilha, raiz=raiz))
        except (OSError, ValueError) as erro:
            raise ValueError(f"CSS {origem or base_dir}: não foi possível publicar o alvo {url!r} ({alvo}): {erro}") from erro
        return f"{nome}?v={versao}{separador}{fragmento}"

    # A pilha distingue entradas de image-set de strings em funções internas, como type().
    pilha: list[tuple[str, int]] = []

    def reescrever(m: re.Match[str]) -> str:
        token = m.group()
        for grupo in ("duplas", "simples", "sem_aspas", "importacao", "string"):
            if m.group(grupo) is None:
                continue
            inicio, fim = m.span(grupo)
            if grupo == "string":
                if not pilha or pilha[-1][0] not in ("image-set", "-webkit-image-set"):
                    return token
                antes = re.sub(r"/\*.*?\*/", "", texto[pilha[-1][1]:m.start()], flags=re.S)
                if antes.strip():
                    return token
            if grupo in ("importacao", "string"):
                inicio += 1
                fim -= 1
            url = texto[inicio:fim]
            return token[:inicio - m.start()] + versionar(url, grupo == "sem_aspas") + token[fim - m.start():]
        if m.group("funcao") is not None or token == "(":
            pilha.append(((m.group("funcao") or "").lower(), m.end()))
        elif token == ")" and pilha:
            pilha.pop()
        elif token == "," and pilha:
            pilha[-1] = (pilha[-1][0], m.end())
        return token

    tokens = (rf"/\*.*?\*/|{padrao}|(?<![\w-])@import\s+(?P<importacao>{string})|"
              rf"(?P<string>{string})|(?P<funcao>[\w-]+)\(|[(),]")
    return re.sub(tokens, reescrever, texto, flags=re.I | re.S)


def bytes_estaticos(caminho: Path, _pilha: tuple[Path, ...] = (), *, raiz: Path | None = None) -> bytes:
    """Lê os bytes a publicar, reescrevendo dependências CSS sem ciclos."""
    caminho = caminho.resolve()
    if caminho in _pilha:
        raise ValueError(f"Ciclo de recursos CSS: {' -> '.join(map(str, (*_pilha, caminho)))}")
    conteudo = caminho.read_bytes()
    if caminho.suffix.lower() == ".css":
        return css_publicado(conteudo.decode("utf-8"), caminho.parent, origem=caminho,
                             raiz=raiz, _pilha=(*_pilha, caminho)).encode("utf-8")
    return conteudo


def versao_estatica(nome: str) -> str:
    return versao_bytes(bytes_estaticos(FONTE_ESTATICA / nome))


def url_estatica(nome_relativo: str, prefixo: str = "") -> str:
    return f"{prefixo}{nome_relativo}?v={versao_estatica(nome_relativo)}"


def _cmp(x, y) -> int:
    return (x > y) - (x < y)


def _ordem_partes(a: tuple[str, dict], b: tuple[str, dict]) -> int:
    """Mesma ordem de ordemPartes em dados.js: mais recente primeiro; depois ano, tipo, parte e nome."""
    (na, ea), (nb, eb) = a, b
    return (_cmp(eb.get("ate") or "", ea.get("ate") or "") or _cmp(eb.get("ano") or 0, ea.get("ano") or 0)
            or _cmp(ea.get("tipo") or "", eb.get("tipo") or "") or _cmp(ea.get("parte") or 0, eb.get("parte") or 0) or _cmp(na, nb))


def plano_docs(arquivos: dict, tipos: list[str] | None = None, ano: int | None = None, alvo: int = PASSO_LISTA) -> list[str]:
    """Espelho de fatiasDocs (dados.js) sem autor nem filtro de conteúdo: menor prefixo de partes que garante `alvo` itens em ordem."""
    candidatos = sorted(((n, e) for n, e in arquivos.items() if e.get("familia") == "doc"
                         and (tipos is None or e.get("tipo") in tipos) and (ano is None or e.get("ano") == ano)),
                        key=cmp_to_key(_ordem_partes))
    k = len(candidatos)
    for k in range(1, len(candidatos) + 1):
        if k == len(candidatos):
            break
        fronteira = candidatos[k][1].get("ate") or ""
        if sum(e["n"] for _, e in candidatos[:k] if (e.get("de") or "") > fronteira) >= alvo:
            break
    return [n for n, _ in candidatos[:k]]


def ano_padrao_doc(arquivos: dict) -> int | None:
    """Ano mais recente com documentos: o filtro inicial de atividades.html."""
    return max((e["ano"] for e in arquivos.values() if e.get("familia") == "doc"), default=None)


def iniciais_por_pagina(manifesto: dict) -> dict[str, list[str]]:
    """Arquivos JSON que cada página carrega sem filtros; base do orçamento de carga inicial."""
    iniciais = {k: list(v) for k, v in INICIAIS_PL.items()}
    ano = ano_padrao_doc(manifesto["arquivos"])
    if ano is not None and "dic-doc" in manifesto["arquivos"]:
        iniciais["atividades.html"] = ["dic-doc", *plano_docs(manifesto["arquivos"], ano=ano)]
    votacoes = sorted(((n, e) for n, e in manifesto["arquivos"].items() if e.get("familia") == "vot"),
                      key=lambda item: (-item[1]["ano"], item[0]))
    if "dic-ses" in manifesto["arquivos"]:
        iniciais["sessoes.html"] = ["dic-ses", *[n for n, _ in votacoes[:1]]]
    return iniciais


def cabecalho_dados(manifesto: dict | None, ativo: str, prefixo: str) -> str:
    if not manifesto:
        return ""
    iniciais = iniciais_por_pagina(manifesto)
    if ativo not in iniciais:
        return ""
    inicial = iniciais[ativo]
    if ativo == "atividades.html":
        # Só as famílias de documentos; o PL continua com o seu build.
        arquivos = {n: e for n, e in manifesto["arquivos"].items() if e.get("familia") in {"dic-doc", "doc", "ver"}}
        dados = {"esquema": manifesto["esquema"], "build": manifesto["build"], "build_doc": manifesto["build_doc"],
                 "inicial": inicial, "arquivos": arquivos}
    elif ativo == "sessoes.html":
        arquivos = {n: e for n, e in manifesto["arquivos"].items() if e.get("familia") in {"dic-ses", "vot"}}
        dados = {"esquema": manifesto["esquema"], "build": manifesto["build"], "build_ses": manifesto["build_ses"],
                 "inicial": inicial, "arquivos": arquivos}
    else:
        arquivos = {n: e for n, e in manifesto["arquivos"].items() if not e.get("familia")}
        dados = {"esquema": manifesto["esquema"], "build": manifesto["build"], "inicial": inicial, "arquivos": arquivos}
    texto = json.dumps(dados, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    partes = [f'<script type="application/json" id="manifesto-dados">{texto}</script>']
    # Uma página estática não conhece a query: escolha antes de iniciar os preloads.
    estaticos = inicial if ativo == "leis.html" else inicial[:1]
    for nome in estaticos:
        partes.append(f'<link rel="preload" as="fetch" crossorigin href="{esc(prefixo + dados["arquivos"][nome]["url"])}">')
    if ativo == "atividades.html":
        partes.append("""<script>
(function () {
  if (location.search) return;
  var m = JSON.parse(document.getElementById("manifesto-dados").textContent);
  m.inicial.slice(1).forEach(function (n) {
    var link = document.createElement("link");
    link.rel = "preload"; link.as = "fetch"; link.crossOrigin = "anonymous";
    link.href = """ + json.dumps(prefixo) + """ + m.arquivos[n].url;
    document.head.appendChild(link);
  });
})();
</script>""")
    if ativo == "projetos.html":
        # Sem consulta, só a prévia; com consulta, as fatias que filtrar() (app.js) vai pedir, e com-consulta
        # esconde as contagens do HTML (classe "inicial"), que só valem sem filtros.
        partes.append("""<script>
(function () {
  var m = JSON.parse(document.getElementById("manifesto-dados").textContent), grupos = ["lei", "andamento", "sem_exito"];
  var desfecho = new URLSearchParams(location.search).get("desfecho");
  var nomes = !location.search ? ["pl-recentes"] : grupos.indexOf(desfecho) >= 0 ? ["pl-" + desfecho]
    : grupos.map(function (g) { return "pl-" + g; });
  if (location.search) document.documentElement.classList.add("com-consulta");
  nomes.forEach(function (n) {
    if (!m.arquivos[n]) return;
    var link = document.createElement("link");
    link.rel = "preload"; link.as = "fetch"; link.crossOrigin = "anonymous";
    link.href = """ + json.dumps(prefixo) + """ + m.arquivos[n].url;
    document.head.appendChild(link);
  });
})();
</script>""")
    return "\n".join(partes)


def pagina(titulo: str, corpo: str, ativo: str, prefixo: str = "", descricao: str = "", manifesto: dict | None = None,
           dialogo: bool = False, scripts: tuple[str, ...] = (), caminho: str | None = None,
           indexavel: bool = True) -> str:
    desc = esc(descricao or "Quais leis de Niterói mudam a cidade, quem as escreveu, e quanto da produção da Câmara é homenagem, "
               "lei sem efeito ou pauta polêmica. Dados do SISCAM atualizados toda semana.")
    nav = "".join(
        f'<a href="{esc(prefixo + href)}"{" aria-current=\"page\"" if href == ativo else ""}>{esc(nome)}</a>' for href, nome in NAV
    )
    caminho = caminho or ativo
    if indexavel and not caminho:
        raise ValueError("pagina(): informe caminho para a canônica")
    canonica = esc(N.URL_SITE + ("" if caminho == "index.html" else caminho))
    identidade = (f'<link rel="canonical" href="{canonica}">\n<meta property="og:url" content="{canonica}">'
                  if indexavel else '<meta name="robots" content="noindex">')
    extras = "\n".join(f'<script src="{esc(prefixo + nome)}?v={versao_estatica(nome)}" defer></script>'
                       for nome in scripts if (FONTE_ESTATICA / nome).is_file())
    icone = f'<link rel="icon" href="{esc(url_estatica("favicon.svg", prefixo))}" type="image/svg+xml">' if (FONTE_ESTATICA / "favicon.svg").is_file() else ""
    # Fontes críticas auto-hospedadas: a URL do preload é a mesma da url() publicada em estilo.css (com ?v=).
    fontes = "".join(f'<link rel="preload" as="font" type="font/woff2" crossorigin href="{esc(url_estatica(nome, prefixo))}">\n'
                     for nome in ("fontes/public-sans-latin-wght-normal.woff2", "fontes/barlow-condensed-latin-700-normal.woff2")
                     if (FONTE_ESTATICA / nome).is_file())
    # Menu móvel (melhoria progressiva): opcional, como os demais estáticos fora de dados.js/app.js.
    navegacao = (f'<script src="{esc(url_estatica("navegacao.js", prefixo))}" defer onerror="{ERRO_NAVEGACAO}"></script>\n'
                 if (FONTE_ESTATICA / "navegacao.js").is_file() else "")
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<script>{SCRIPT_CABECA}</script>
<title>{esc(titulo)}</title>
<meta name="description" content="{desc}">
<meta property="og:title" content="{esc(titulo)}">
<meta property="og:description" content="{desc}">
{identidade}
<meta property="og:type" content="website">
<meta property="og:site_name" content="Radar dos Vereadores de Niterói">
<meta property="og:locale" content="pt_BR">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#F7F2E9" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0E1B26" media="(prefers-color-scheme: dark)">
{fontes}<link rel="stylesheet" href="{esc(prefixo)}estilo.css?v={versao_estatica('estilo.css')}">
{icone}
<link rel="alternate" type="application/rss+xml" title="Novidades · Radar dos Vereadores de Niterói" href="{esc(prefixo + N.FEED)}">
{cabecalho_dados(manifesto, ativo, prefixo)}
</head>
<body>
<a class="pular" href="#conteudo">Ir para o conteúdo</a>
<header class="topo">
 <a class="marca" href="{esc(prefixo)}index.html">Radar dos Vereadores <span>Niterói</span></a>
 <button class="menu-botao" type="button" aria-expanded="false" aria-controls="menu-principal" hidden>Menu</button>
 <nav id="menu-principal" aria-label="Principal">{nav}<div class="tema" role="group" aria-label="Tema" hidden><button type="button" data-tema="auto" aria-pressed="true">Automático</button><button type="button" data-tema="claro" aria-pressed="false">Claro</button><button type="button" data-tema="escuro" aria-pressed="false">Escuro</button></div></nav>
</header>
<main id="conteudo" data-prefixo="{esc(prefixo)}">
{corpo}
</main>
<footer class="rodape">
 <p>Dados públicos do <a href="https://consultaniteroi.siscam.com.br/">SISCAM da Câmara Municipal de Niterói</a>, coletados toda semana. Classificação por regras, curadoria com fonte e IA, explicada na <a href="{esc(prefixo)}metodologia.html">metodologia</a>. Código aberto sob GPL v3 no <a href="{REPO}">GitHub</a>. Encontrou um erro? <a href="{REPO}/issues/new">Abra uma issue</a>.</p>
</footer>
{(DIALOGO_SISCAM + chr(10)) if dialogo else ''}<div id="tip" role="tooltip" hidden></div>
{navegacao}<script src="{esc(prefixo)}dados.js?v={versao_estatica('dados.js')}" defer></script>
<script src="{esc(prefixo)}app.js?v={versao_estatica('app.js')}" defer></script>
{extras}
</body>
</html>
"""


# --------------------------------------------------------------------- componentes
def chip_autor(a: dict, prefixo: str, principal: bool = False) -> str:
    if not a.get("vereador"):
        return f'<span class="chip chip-exec">{esc(a["exibicao"])}</span>'
    return f'<a class="chip{" chip-principal" if principal else ""}" href="{prefixo}vereadores/{a["slug"]}.html">{esc(a["exibicao"])}</a>'


def autores_html(p: dict, prefixo: str) -> str:
    principal = [a for a in p["autores"] if a["slug"] == p["principal"]] or p["autores"][:1]
    outros = [a for a in p["autores"] if a not in principal]
    base = "".join(chip_autor(a, prefixo, True) for a in principal)
    if outros:
        base += f'<span class="coautores">e {plural(len(outros), "coautor", "coautores")}</span>'
    return base


def selo_impacto(p: dict) -> str:
    imp = p["impacto"]
    if p["categoria"] == "simbolica":
        return '<span class="selo imp-0">Simbólica</span>'
    if "autorizativa" in p["sinais"]:
        return '<span class="selo imp-0">Autorizativa</span>'
    return f'<span class="selo {CLASSE_IMPACTO[imp]}">{esc(NOME_IMPACTO[imp])}</span>'


def tags_html(p: dict, contestar: bool = True) -> str:
    alertas = "".join(
        f'<span class="tag alerta" title="{esc(a.get("nota", ""))}">{esc(NOME_ALERTA.get(a["rotulo"], a["rotulo"]))}'
        f'<small>{"curadoria" if a["origem"] == "curadoria" else "IA"}</small></span>'
        for a in p["alertas"]
    )
    sinais = "".join(f'<span class="tag sinal" title="{esc(DESC_SINAL.get(s, ""))}">{esc(NOME_SINAL.get(s, s))}</span>'
                     for s in p["sinais"] if s != "autorizativa")
    if p.get("repete"):
        sinais += f'<a class="tag sinal" href="{esc(p["repete"]["url"])}" target="_blank" rel="noopener">igual ao PL {esc(p["repete"]["numero"])}{NOVA_ABA}</a>'
    if not (alertas or sinais):
        return ""
    link = ""
    if contestar:
        link = f' <a class="contestar" href="{REPO}/issues/new?title={esc("Classificação do PL " + p["numero"])}&amp;body={esc("Projeto: " + p["url"])}">contestar</a>'
    return f'<p class="tags">{alertas}{sinais}{link}</p>'


def via_substitutivo(p: dict, link: bool) -> str:
    """Marca "via substitutivo" da lei aprovada por substitutivo; espelho de viaSubstitutivo em app.js.

    Com `link`, aponta para a página do substitutivo (o link do número do PL continua no original).
    """
    if not p.get("lei_substitutivo"):
        return ""
    if not link:
        return ' <span class="via-substitutivo">via substitutivo</span>'
    return (f' <a class="via-substitutivo" href="{esc(url_lei(p))}" target="_blank" rel="noopener">via substitutivo'
            f'<span class="so-leitor"> (substitutivo ao PL {esc(p["numero"])})</span>{NOVA_ABA}</a>')


def cartao_lei(p: dict, prefixo: str) -> str:
    lei = p.get("lei") or {}
    resumo = p["resumo"] or legivel(p["ementa"])
    tema = NOME_TEMA.get(p["tema"], "") if p["tema"] not in ("outro", "homenagem") else ""
    # O título leva à página de onde saiu a lei: a do substitutivo aprovado, quando houver.
    return f"""<article class="cartao {CLASSE_IMPACTO[p['impacto']]}">
 <p class="cartao-topo">{selo_impacto(p)}<span>Lei {esc(lei.get('numero') or '')} · {esc(data_br(lei['data'])) if lei.get('data') else 'data não informada'}</span></p>
 <p class="lei-situacao">{esc(situacao_lei(lei))}{via_substitutivo(p, link=False)}</p>
 <h3><a href="{esc(url_lei(p))}" target="_blank" rel="noopener">{esc(resumo)}{NOVA_ABA}</a></h3>
 {f'<p class="publico">Afeta: {esc(p["publico"])}{" · " + esc(tema) if tema else ""}</p>' if p['publico'] or tema else ''}
 <p class="cartao-autor">{autores_html(p, prefixo)}{f'<span class="partido">{esc(p["partido"])}</span>' if p["partido"] else ''}</p>
</article>"""


def item_projeto(p: dict, prefixo: str) -> str:
    lei = p.get("lei") or {}
    lei_txt = esc(f" · Lei {lei['numero']}") if lei.get("numero") else ""
    if p["desfecho"] == "virou_lei":
        lei_txt += (esc(f" · {situacao_lei(lei)}") + via_substitutivo(p, link=True)
                    + esc(f" · {data_br(lei['data']) if lei.get('data') else 'data não informada'}"))
    resumo = f'<p class="resumo-ia">{esc(p["resumo"])}</p>' if p["resumo"] else ""
    return f"""<li class="projeto d-{esc(DESFECHO_GRUPO.get(p['desfecho'], 'andamento'))}">
 <p class="cab"><a href="{esc(p['url'])}" target="_blank" rel="noopener">PL {esc(p['numero'])}{NOVA_ABA}</a><span>{data_br(p['data'])}</span><span class="desfecho">{esc(NOME_DESFECHO.get(p['desfecho'], p['desfecho']))}{lei_txt}</span>{selo_impacto(p)}</p>
 {resumo}<p class="ementa">{esc(legivel(p['ementa']))}</p>
 <p class="autoria">{autores_html(p, prefixo)}</p>
 {tags_html(p)}
</li>"""


def botoes_siscam(url: str, rotulo: str) -> str:
    """Botão que abre o detalhe num diálogo (visível só com JS) e link comum, sempre presente, em nova aba."""
    return (f'<p class="acoes-item"><button type="button" class="ver-siscam" data-url="{esc(url)}" data-rotulo="{esc(rotulo)}">'
            f'Ver no SISCAM<span class="so-leitor"> ({esc(rotulo)})</span></button> '
            f'<a class="abrir-siscam" href="{esc(url)}" target="_blank" rel="noopener">abrir no SISCAM'
            f'<span class="so-leitor"> ({esc(rotulo)})</span>{NOVA_ABA}</a></p>')


def rotulo_documento(d: dict) -> str:
    return f"{NOME_TIPO_DOC[d['tipo']][2]} {d['numero']}"


def situacao_legivel(s: str) -> str:
    return s[:1] + s[1:].lower() if s.isupper() else s


def meta_documento(d: dict) -> list[str]:
    """Subcategoria, bairro, resposta e publicação; mesma ordem de metaD em app.js."""
    meta = [NOME_SUBCATEGORIA_DOC.get((d["tipo"], d["subcategoria"]), d["subcategoria"])]
    if d["bairro"]:
        meta.append(f"Bairro: {d['bairro']}")
    if d["tipo"] == "requerimento":
        if d["respondido"]:
            txt = "Respondido"
            if d["respondido_em"]:
                txt += f" em {data_br(d['respondido_em'][:10])}"
            if d["dias_ate_resposta"] is not None:
                txt += f" ({plural(d['dias_ate_resposta'], 'dia', 'dias')})"
            meta.append(txt)
        else:
            meta.append("Sem resposta registrada")
    pub = d["publicacao"]
    if pub:
        meta.append("Publicado" + (f" nº {pub['numero']}" if pub.get("numero") else "")
                    + (f" em {data_br(str(pub['data'])[:10])}" if pub.get("data") else ""))
    if d["detalhe_pendente"]:
        meta.append("detalhe ainda não coletado")
    return meta


def autores_documento_html(d: dict, prefixo: str, maximo: int = 3) -> str:
    """Autores na ordem do SISCAM, sem destacar principal: a listagem não separa autor de coautor."""
    chips = []
    for a in d["autores"][:maximo]:
        if a["vereador"] and a["pagina"]:
            chips.append(f'<a class="chip" href="{prefixo}vereadores/{esc(a["slug"])}.html">{esc(a["exibicao"])}</a>')
        else:
            chips.append(f'<span class="chip{"" if a["vereador"] else " chip-exec"}">{esc(a["exibicao"])}</span>')
    resto = d["autores"][maximo:]
    if resto:
        chips.append(f'<span class="coautores" title="{esc(", ".join(a["exibicao"] for a in resto))}">'
                     f'e mais {plural(len(resto), "autor", "autores")}</span>')
    return "".join(chips)


def item_documento(d: dict, prefixo: str) -> str:
    rotulo = rotulo_documento(d)
    assunto = f'<p class="assunto">Assunto: {esc(d["assunto"])}</p>' if d.get("assunto") else ""
    return f"""<li class="projeto doc t-{esc(d['tipo'])}">
 <p class="cab"><a href="{esc(d['url'])}" target="_blank" rel="noopener">{esc(rotulo)}{NOVA_ABA}</a><span>{data_br(d['data'])}</span><span class="desfecho">{esc(situacao_legivel(d['situacao']))}</span><span class="selo cat-{esc(d['categoria'])}">{esc(NOME_CATEGORIA_DOC.get(d['categoria'], d['categoria']))}</span></p>
 {assunto}<p class="ementa">{esc(legivel(d['ementa']))}</p>
 <p class="publico">{esc(' · '.join(meta_documento(d)))}</p>
 <p class="autoria">{autores_documento_html(d, prefixo)}</p>
 {botoes_siscam(d['url'], rotulo)}
</li>"""


def tile(valor, rotulo: str, nota: str = "", classe: str = "") -> str:
    return f'<div class="tile {classe}"><p class="tile-valor">{esc(valor)}</p><p class="tile-rotulo">{esc(rotulo)}</p>{f"<p class=tile-nota>{esc(nota)}</p>" if nota else ""}</div>'


def barra_producao(m: dict, maximo: int) -> str:
    total = m["apresentados"]
    if total == 0:
        return '<div class="barra vazia" role="img" aria-label="Nenhum projeto apresentado como autor"><span>nenhum projeto como autor</span></div>'
    seg = [
        ("c-efeito", m["leis_efeito"], "leis com efeito"),
        ("c-baixo", m["leis_outras"], "leis de impacto baixo"),
        ("c-sem-efeito", m["leis_sem_efeito"], "leis sem efeito prático"),
        ("c-andamento", m["andamento"], "em andamento"),
        ("c-sem-exito", m["sem_exito"], "sem êxito"),
    ]
    largura = 100 * total / max(maximo, 1)
    rotulo = ", ".join(f"{n} {t}" for _, n, t in seg if n)
    partes = "".join(f'<i class="{c}" style="flex:{n}" data-tip="{n} {t}"></i>' for c, n, t in seg if n)
    return f'<div class="barra" role="img" aria-label="{total} projetos como autor: {esc(rotulo)}"><div class="trilho" style="width:{largura:.1f}%">{partes}</div></div>'


LEGENDA_BARRA = """<ul class="leg-graf" aria-label="Legenda das barras">
 <li><i class="sw c-efeito"></i>Virou lei com efeito</li>
 <li><i class="sw c-baixo"></i>Virou lei de impacto baixo</li>
 <li><i class="sw c-sem-efeito"></i>Virou lei sem efeito prático</li>
 <li><i class="sw c-andamento"></i>Em andamento</li>
 <li><i class="sw c-sem-exito"></i>Arquivado, vetado ou rejeitado</li>
</ul>"""


# ------------------------------------------------- tabelas de métricas dos documentos
# Tabelas geradas no servidor (sem novas colunas nos JSONs do navegador). Os textos repetem as definições da
# metodologia; as regras estão em coletor/regras_documentos.py e as contagens em coletor/site/modelo.py.
EXPLICA_HOMENAGENS = (
    "Homenagem: moção de aplauso (inclusive congratulação e louvor) ou de pesar, título de cidadão e outras honrarias, "
    "como medalhas e diplomas, em PDLs e resoluções. Moções de repúdio e de apoio não contam. O peso divide as homenagens "
    "pela produção do mesmo período: todos os documentos em que o vereador aparece como autor mais os projetos de lei "
    "como autor principal. Só entram anos com coleta completa (os cinco tipos de documento coletados). Contar documentos "
    "não mede qualidade nem resultado.")
EXPLICA_INFORMACAO = (
    "Requerimentos de informação pedem dados ou cópias de processos e contratos. Por vereador, contam também os pedidos "
    "assinados em conjunto (coautoria). Respondido: o SISCAM registra resposta na "
    "situação ou na tramitação. Os dias até a resposta vão até a data do passo “Respondido” da tramitação, quando a Câmara "
    "registrou a resposta, que não é necessariamente o dia em que o Executivo respondeu, e só existem para os respondidos "
    "cuja página de detalhe, com a tramitação completa, já foi baixada: a mediana usa só esses (a base aparece ao lado). "
    "A taxa de resposta exclui os pedidos retirados pelo autor. Aguardando: sem resposta registrada e sem arquivamento; "
    "pedidos recentes ainda podem ser respondidos. Contar pedidos não mede a qualidade nem a relevância deles.")
EXPLICA_ORGAOS = (
    "Órgão: o primeiro órgão específico citado na ementa (secretaria, fundação, empresa municipal ou concessionária), "
    "mesmo como intermediário ou cópia; órgão estadual, só quando é o destinatário. Sem órgão na ementa, vale o assunto "
    "da listagem do SISCAM. Sem órgão específico, “Prefeito ou Poder Executivo”; sem nenhum, “Não identificado”. Os "
    "nomes de secretarias mudam entre gestões e aparecem como citados. A tramitação não indica o órgão: os pedidos "
    "seguem para a Secretaria Municipal de Governo, que os repassa.")
EXPLICA_BAIRROS = (
    "Bairro: o último dos 52 bairros oficiais citado na ementa da indicação; sub-bairros, comunidades e nomes de rua não "
    "são reconhecidos. Por vereador, contam também as indicações assinadas em conjunto (coautoria). Concentração: parte "
    "das indicações com bairro que vai para o bairro mais citado. Sem dado de "
    "população, não há taxa por habitante. Contar indicações não mede se o serviço foi feito.")
CAB_INFORMACAO = ["Pedidos", "Respondidos", "Taxa de resposta", "Mediana de dias até “Respondido”",
                  "Base da mediana (respondidos com data)", "Aguardando", "Encerrados sem resposta", "Retirados"]
CAB_BAIRROS = ["Indicações", "Com bairro", "Bairros distintos", "Mais citado (concentração)", "5 bairros mais citados"]
TEXTO_BAIRROS = (4, 5)  # colunas de texto da tabela de bairros (índices na linha, com o cabeçalho da linha em 0)


def pct_txt(v: int | None) -> str:
    return "—" if v is None else f"{v}%"


def _celula(v) -> str:
    """Número formatado (None vira "—") ou texto já escapado, que pode trazer um link."""
    if v is None:
        return "—"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return G._fmt(v)
    return str(v)


def tabela_resumo(legenda: str, cabecalho: list[str], linhas: list[list], texto: tuple[int, ...] = ()) -> str:
    """Tabela com legenda, cabeçalhos de coluna e, na primeira célula de cada linha, cabeçalho de linha.

    texto: índices das colunas de texto (classe "txt", alinhadas à esquerda). O contêiner rola na horizontal e
    recebe foco pelo teclado (região rotulada pela legenda).
    """
    cls = lambda i: ' class="txt"' if i in texto else ""
    th = "".join(f'<th scope="col"{cls(i)}>{esc(c)}</th>' for i, c in enumerate(cabecalho))
    corpo = "".join(f'<tr><th scope="row">{_celula(l[0])}</th>'
                    + "".join(f"<td{cls(i)}>{_celula(c)}</td>" for i, c in enumerate(l[1:], start=1)) + "</tr>"
                    for l in linhas)
    return (f'<div class="tabela-graf tabela-resumo" role="region" tabindex="0" aria-label="{esc(legenda)}">'
            f'<table><caption>{esc(legenda)}</caption><thead><tr>{th}</tr></thead><tbody>{corpo}</tbody></table></div>')


def nome_autor(modelo: dict, s: str) -> str:
    """Nome de exibição de um autor vereador: o da página dele ou, sem página, o dos documentos."""
    pessoa = modelo["pessoas"].get(s)
    if pessoa:
        return pessoa["nome"]
    docs = ((modelo.get("atividade") or {}).get(s) or {}).get("documentos") or []
    return next((a["exibicao"] for d in docs for a in d["autores"] if a["slug"] == s), s)


def link_autor(modelo: dict, s: str, prefixo: str) -> str:
    nome = esc(nome_autor(modelo, s))
    return f'<a href="{prefixo}vereadores/{esc(s)}.html">{nome}</a>' if s in modelo["pessoas"] else nome


def celulas_informacao(r: dict) -> list:
    """Células de CAB_INFORMACAO para um resumo_informacao."""
    return [r["pedidos"], r["respondidos"], pct_txt(r["taxa"]), r["mediana_dias"], r["com_dias"], r["aguardando"],
            r["encerrados"], r["retirados"]]


def celulas_bairros(r: dict) -> list:
    """Células de CAB_BAIRROS para um resumo_bairros."""
    return [r["indicacoes"], r["com_bairro"], r["distintos"], mais_citado_txt(r), top_bairros_txt(r)]


def top_bairros_txt(r: dict) -> str:
    return esc(", ".join(f"{b} ({n})" for b, n in r["top"])) or "—"


def mais_citado_txt(r: dict) -> str:
    """Bairro mais citado e a concentração; com empate no topo, "empate: A, B (n% cada)"."""
    nomes = r.get("mais_citados") or [b for b, _ in r["top"][:1]]
    if not nomes:
        return "—"
    if len(nomes) == 1:
        return esc(f"{nomes[0]} ({r['concentracao']}%)")
    lista = ", ".join(nomes[:3]) + (f" e mais {len(nomes) - 3}" if len(nomes) > 3 else "")
    return esc(f"empate: {lista} ({r['concentracao']}% cada)")


def base_mediana_txt(r: dict) -> str:
    """Nota da mediana com a sua base: os respondidos que têm data no detalhe."""
    return f"mediana entre {plural(r['com_dias'], 'respondido com data', 'respondidos com data')}"


def pendentes_txt(r: dict) -> str:
    """Frase com os requerimentos de informação ainda sem detalhe (sem tramitação, não têm dias até a resposta)."""
    n = r["pendentes"]
    if not n:
        return "Nenhum requerimento de informação está com o detalhe pendente."
    return f"{plural(n, 'requerimento de informação ainda está', 'requerimentos de informação ainda estão')} com o detalhe pendente."


def periodo_txt(anos) -> str:
    anos = sorted(anos)
    if not anos:
        return ""
    return str(anos[0]) if len(anos) == 1 else f"{anos[0]} a {anos[-1]}"


def periodo_docs(modelo: dict) -> str:
    """Período de todos os anos com documentos (os resumos de atividades.html usam todos)."""
    return periodo_txt(coleta_do_modelo(modelo)["todos"])


def nota_parciais(modelo: dict) -> str:
    """Nota sobre os anos com coleta parcial, que ficam fora do peso das homenagens; vazia se não houver."""
    parciais = coleta_do_modelo(modelo)["parciais"]
    if not parciais:
        return ""
    return (f'<p class="nota">Anos com coleta parcial (falta algum dos cinco tipos de documento), fora destas contas: '
            f'{esc(", ".join(str(a) for a in parciais))}.</p>')


# ------------------------------------------------------------------------- início
PLACAR_DOCS = (("indicacao", "indicacoes", "indicação", "indicações"), ("mocao", "mocoes", "moção", "moções"),
               ("requerimento", "requerimentos", "requerimento", "requerimentos"))


def linha_placar(pessoa: dict, leg: str, maximo: int, docs: dict | None = None) -> str:
    """docs: contagem por tipo de documento na legislatura; None quando não há documentos coletados."""
    m = pessoa["mandatos"][leg]
    me = m["metricas"]
    status = []
    if not m["eleito"]:
        status.append("suplente em exercício")
    if m["afastamentos"]:
        status.append("afastou-se para o Executivo")
    dados = " ".join(f'data-{k.replace("_", "-")}="{v if v is not None else -1}"' for k, v in me.items())
    alerta = f'<span class="n-alerta">{plural(me["polemicos"], "projeto com alerta", "projetos com alerta")}</span>' if me["polemicos"] else ""
    sem = f'<span>{me["leis_sem_efeito"]} sem efeito</span>' if me["leis_sem_efeito"] else ""
    dados_docs = colunas_docs = ""
    if docs is not None:
        dados_docs = "".join(f' data-{chave}="{docs.get(t, 0)}"' for t, chave, _, _ in PLACAR_DOCS)
        colunas_docs = '<span class="n-docs">' + "".join(
            f'<span><b>{milhar(docs.get(t, 0))}</b> {um if docs.get(t, 0) == 1 else varios}</span>' for t, _, um, varios in PLACAR_DOCS) + "</span>"
    return f"""<li class="linha" {dados}{dados_docs} data-nome="{esc(pessoa['nome'])}" data-eleito="{int(m['eleito'])}" data-partido="{esc(m['partido'])}">
 <a class="quem" href="vereadores/{pessoa['slug']}.html"><strong>{esc(pessoa['nome'])}</strong> <span class="partido">{esc(m['partido'])}</span>{''.join(f'<span class="status">{esc(s)}</span>' for s in status)}</a>
 {barra_producao(me, maximo)}
 <p class="numeros"><span class="n-efeito"><b>{me['leis_efeito']}</b> {'lei com efeito' if me['leis_efeito'] == 1 else 'leis com efeito'}</span><span>{me['leis']} de {plural(me['apresentados'], 'projeto', 'projetos')}{' · ' if sem else ''}{sem}</span>{alerta}{colunas_docs}</p>
</li>"""


def gerar_index(modelo: dict) -> str:
    legs = modelo["legislaturas"]
    atual = legs[-1]["id"]
    projs = modelo["projetos"]
    ver_atual = [p for p in projs if p["legislatura"] == atual and p["origem"] == "vereador"]
    leis_atual = [p for p in ver_atual if p["desfecho"] == "virou_lei"]
    efeito = [p for p in leis_atual if com_efeito(p)]
    sem = [p for p in leis_atual if sem_efeito(p)]
    dias = [p["dias_ate_lei"] for p in leis_atual if p["dias_ate_lei"] is not None]
    alertas = [p for p in ver_atual if p["polemico"]]

    destaques = sorted([p for p in projs if com_efeito(p) and p["origem"] == "vereador"],
                       key=lambda p: ((p.get("lei") or {}).get("data") or "", p["impacto"] or 0), reverse=True)[:6]

    blocos, abas = [], []
    partidos_por_leg = {}
    tem_docs = bool(modelo.get("documentos"))

    def docs_de(p: dict, leg_id: str) -> dict | None:
        if not tem_docs:
            return None
        return (((p.get("atividade") or {}).get("por_leg") or {}).get(leg_id) or {}).get("tipos") or {}

    for leg in reversed(legs):
        pessoas = [p for p in modelo["pessoas"].values() if leg["id"] in p["mandatos"]]
        pessoas.sort(key=lambda p: (-p["mandatos"][leg["id"]]["metricas"]["leis_efeito"], -p["mandatos"][leg["id"]]["metricas"]["leis"], p["nome"]))
        maximo = max([p["mandatos"][leg["id"]]["metricas"]["apresentados"] for p in pessoas] + [1])
        partidos_por_leg[leg["id"]] = sorted({p["mandatos"][leg["id"]]["partido"] for p in pessoas if p["mandatos"][leg["id"]]["partido"]})
        zerados = [p["nome"] for p in pessoas if p["mandatos"][leg["id"]]["eleito"] and p["mandatos"][leg["id"]]["metricas"]["leis"] == 0]
        nota_zero = f'<p class="nota">Eleitos sem nenhuma lei de autoria própria nesta legislatura: {esc(", ".join(zerados))}.</p>' if zerados else ""
        blocos.append(f"""<section class="legislatura" id="leg-{esc(leg['id'])}" data-leg="{esc(leg['id'])}"{'' if leg['id'] == atual else ' hidden'}>
{nota_zero}
<ol class="placar">{''.join(linha_placar(p, leg['id'], maximo, docs_de(p, leg['id'])) for p in pessoas)}</ol>
</section>""")
        abas.append(f'<button type="button" role="tab" aria-selected="{"true" if leg["id"] == atual else "false"}" data-alvo="leg-{esc(leg["id"])}">{esc(leg["id"])}</button>')
    opcoes_partido = "".join(f'<option value="{esc(pt)}">{esc(pt)}</option>' for pt in sorted({x for v in partidos_por_leg.values() for x in v}))
    atualizado = (modelo["meta"].get("coleta") or {}).get("em", "")[:10]
    pct_sem = round(100 * len(sem) / len(leis_atual)) if leis_atual else 0
    ordem_docs = explica_docs = ""
    if tem_docs:
        ordem_docs = "".join(f'\n    <option value="{chave}">{varios.capitalize()}</option>' for _, chave, _, varios in PLACAR_DOCS)
        explica_docs = (' Indicações, moções e requerimentos aparecem à parte, sem entrar na barra: contam todo documento em que o vereador '
                        'aparece como autor, inclusive os assinados em conjunto, porque a listagem do SISCAM não separa autor de coautor. '
                        'Veja todos em <a href="atividades.html">Atividades</a>.')

    corpo = f"""<section class="abertura">
 <h1>Leis que mudam a cidade, e quem as escreveu.</h1>
 <p>Desde 2021, a Câmara de Niterói analisou mais de {milhar(len(projs) // 100 * 100)} projetos de lei. Este site separa as leis com efeito real das homenagens, das leis que só autorizam o prefeito e das pautas polêmicas, e mostra quem fez cada uma.</p>
 <p class="atualizacao">Dados do SISCAM de {data_br(atualizado) if atualizado else '—'} · <a href="metodologia.html">como classificamos</a></p>
</section>

<section aria-labelledby="t-numeros">
 <h2 id="t-numeros" class="h-secao">Legislatura {esc(atual)}, até agora</h2>
 <div class="tiles">
  {tile(len(efeito), "leis de vereadores com efeito real", f"de {len(leis_atual)} leis aprovadas", "tile-efeito")}
  {tile(f"{pct_sem}%", "das leis aprovadas não têm efeito prático", f"{len(sem)} homenagens, datas, nomes e leis autorizativas", "tile-sem")}
  {tile(len(alertas), "projetos com alerta de polêmica", "restrição de direitos, costumes ou apelo populista", "tile-alerta")}
  {tile(f"{int(statistics.median(dias))} dias" if dias else "—", "é o tempo mediano até um projeto virar lei", "")}
 </div>
</section>

<section aria-labelledby="t-destaques">
 <div class="cab-secao"><h2 id="t-destaques" class="h-secao">Leis com efeito aprovadas mais recentemente</h2><a href="leis.html?efeito=1">Ver todas as leis com efeito</a></div>
 <div class="cartoes">{''.join(cartao_lei(p, '') for p in destaques)}</div>
</section>

<section aria-labelledby="t-placar">
 <div class="cab-secao"><h2 id="t-placar" class="h-secao">Produção de cada vereador como autor principal</h2></div>
 <p class="explica">O comprimento da barra é o total de projetos apresentados; as cores mostram o que aconteceu com eles. Projetos assinados como coautor não entram, para que assinaturas em bloco não inflem a conta.{explica_docs}</p>
 <div class="controles">
  <div role="tablist" aria-label="Legislatura" class="abas">{''.join(abas)}</div>
  <label>Ordenar por
   <select id="ordem">
    <option value="leis-efeito">Leis com efeito</option>
    <option value="leis">Total de leis</option>
    <option value="apresentados">Projetos apresentados</option>
    <option value="leis-sem-efeito">Leis sem efeito prático</option>
    <option value="pct-sem-efeito">% de leis sem efeito</option>
    <option value="polemicos">Projetos com alerta</option>
    <option value="taxa-aprovacao">Taxa de aprovação</option>{ordem_docs}
    <option value="nome">Nome</option>
   </select>
  </label>
  <label>Partido <select id="f-partido-placar"><option value="">Todos</option>{opcoes_partido}</select></label>
  <label class="check"><input type="checkbox" id="so-eleitos"> Só eleitos</label>
 </div>
 {LEGENDA_BARRA}
 {''.join(blocos)}
</section>

<section class="convite">
 <a href="ruido.html"><strong>Sem efeito e polêmicas</strong><span>Homenagens, leis que só autorizam o prefeito, projetos repetidos e pautas que restringem direitos.</span></a>
 <a href="analises.html"><strong>Análises históricas</strong><span>Como a produção da Câmara mudou de 2021 a hoje, por tema, partido e tempo de tramitação.</span></a>
</section>"""
    return pagina("Radar dos Vereadores de Niterói", corpo, "index.html", caminho="index.html")


# ------------------------------------------------------------- leis e projetos
def chave_impacto(p: dict) -> str:
    """Chip de impacto de um registro de dados_cliente; mesma regra de chaveImp em app.js."""
    if p["c"] == "simbolica" or "autorizativa" in p["s"]:
        return "0"
    return "x" if p["i"] is None else str(p["i"])


def resumo_projetos(cliente: dict) -> dict:
    """Contagens de projetos.html sem filtros, com as regras de aplicarFiltros (app.js) no modo projetos.

    Vão no HTML para que a página mostre os totais exatos antes de carregar as fatias completas:
    a prévia (pl-recentes) só tem as primeiras linhas e nunca serve para contar.
    """
    projetos = cliente["projetos"]
    chips = Counter(chave_impacto(p) for p in projetos)
    return {"total": len(projetos), "ef": sum(1 for p in projetos if p["ef"]), "se": sum(1 for p in projetos if p["se"]),
            "pol": sum(1 for p in projetos if p["pol"]), "chips": {k: chips[k] for k, _ in CHIPS_IMPACTO}}


def contagem_projetos(r: dict) -> str:
    """O mesmo texto que aplicarFiltros (app.js) escreve no modo projetos; "inicial" marca que vale sem filtros."""
    n = r["total"]
    detalhe = (f' · <b>{r["ef"]}</b> com efeito (viraram lei) · <b>{r["se"]}</b> sem efeito prático'
               f' · <b>{r["pol"]}</b> com alerta') if n else ""
    return f'<p class="contagem inicial"><b>{n}</b> {"projeto" if n == 1 else "projetos"}{detalhe}</p>'


def filtros_lista(modo: str, cliente: dict | None = None) -> str:
    resumo = resumo_projetos(cliente) if modo == "projetos" and cliente is not None else None
    cliente = cliente or {"projetos": [], "pessoas": {}, "temas": {}, "legislaturas": []}
    base = [p for p in cliente["projetos"] if modo != "leis" or p["g"] == "lei"]
    autores, partidos, temas, anos = {}, set(), Counter(), set()
    for p in base:
        autores.update({s: cliente["pessoas"].get(s, nome) for nome, s in p["au"] if s})
        if p["pt"]:
            partidos.add(p["pt"])
        temas[p["t"]] += 1
        anos.add(str(p["ld"][:4] if modo == "leis" and p["ld"] else p["a"]))

    def opcoes(pares) -> str:
        return "".join(f'<option value="{esc(k)}">{esc(v)}</option>' for k, v in pares)

    def chave_nome(par: tuple[str, str]) -> str:
        return "".join(c for c in unicodedata.normalize("NFD", par[1].lower()) if not unicodedata.combining(c))

    op_autores = opcoes(sorted(autores.items(), key=chave_nome))
    op_partidos = opcoes((p, p) for p in sorted(partidos))
    op_temas = opcoes((t, f"{cliente['temas'].get(t, t)} ({n})") for t, n in temas.most_common())
    op_legs = opcoes((l, l) for l in reversed(cliente["legislaturas"]))
    op_anos = opcoes((a, a) for a in sorted(anos, reverse=True))

    def chip(k: str, rotulo: str) -> str:
        n = f'<span class="n inicial">{resumo["chips"][k]}</span>' if resumo else ""
        return f'  <label><input type="checkbox" name="imp" value="{k}"> {rotulo}{n}</label>'

    chips = "\n".join(chip(k, rotulo) for k, rotulo in CHIPS_IMPACTO)
    atributos_resumo = f' data-total="{resumo["total"]}"' if resumo else ""
    texto_resumo = contagem_projetos(resumo) if resumo else ""
    sem_js = {"leis": "A lista de leis precisa de JavaScript. As leis de cada vereador também aparecem na página dele.",
              "projetos": "A lista de projetos precisa de JavaScript. Os projetos de cada vereador também aparecem na página dele."}
    extra = ""
    if modo == "projetos":
        extra = """
  <label>Desfecho <select id="f-desfecho"><option value="">Todos</option><option value="lei">Virou lei</option><option value="andamento">Em andamento</option><option value="sem_exito">Sem êxito</option></select></label>
  <label>Sinal <select id="f-sinal"><option value="">Qualquer</option><option value="alerta">Com alerta de polêmica</option><option value="curadoria">Revisado por curadoria</option><option value="alerta_ia">Alerta de IA (sem curadoria)</option><option value="autorizativa">Lei autorizativa</option><option value="repete_projeto">Repete projeto anterior</option><option value="veto">Vetado ou com veto</option><option value="parecer_contrario_ccj">Parecer contrário da CCJ</option></select></label>"""
    return f"""<form class="filtros" role="search" onsubmit="return false" data-modo="{modo}">
 <div class="linha-busca"><label class="busca-q">Buscar <input type="search" id="q" placeholder="tema, número, nome de vereador…" autocomplete="off"></label>
  <label>Ordenar <select id="f-ordem"><option value="recente">Mais recentes</option><option value="impacto">Maior impacto</option>{'<option value="rapida">Aprovadas mais rápido</option>' if modo == 'leis' else ''}</select></label></div>
 <fieldset class="chips-impacto"><legend>Impacto</legend>
{chips}
 </fieldset>
 <details class="mais-filtros" open><summary>Mais filtros</summary>
 <div class="grade-filtros">
  <label>Origem <select id="f-origem"><option value="">Todas</option><option value="vereador">Vereadores</option><option value="executivo">Prefeitura</option></select></label>
   <label>Vereador <select id="f-autor"><option value="">Todos</option>{op_autores}</select></label>
   <label>Partido <select id="f-partido"><option value="">Todos</option>{op_partidos}</select></label>
   <label>Tema <select id="f-tema"><option value="">Todos</option>{op_temas}</select></label>
   <label>Legislatura <select id="f-leg"><option value="">Todas</option>{op_legs}</select></label>
   <label>Ano <select id="f-ano"><option value="">Todos</option>{op_anos}</select></label>{extra}
  <label>Autoria <select id="f-coautor" disabled><option value="">Só autoria principal</option><option value="1">Incluir coautoria</option><option value="so">Apenas coautoria</option></select></label>
 </div>
 </details>
 <p class="acoes-filtro"><button type="button" id="limpar">Limpar filtros</button> <button type="button" id="csv">Baixar CSV</button></p>
</form>
<div class="resumo-filtro" id="resumo-filtro" aria-live="polite"{atributos_resumo}>{texto_resumo}</div>
<ol id="resultados" class="projetos"></ol>
<button type="button" id="mais" class="mais" hidden>Mostrar mais</button>
<noscript><p class="vazio">{esc(sem_js[modo])}</p></noscript>"""


def gerar_leis(cliente: dict | None = None, manifesto: dict | None = None) -> str:
    corpo = f"""<section class="abertura">
 <h1>Leis aprovadas</h1>
 <p>Todas as leis que saíram de projetos apresentados desde 2021, com o impacto estimado e um resumo em linguagem simples. Filtre por impacto, tema, vereador ou partido; o quadro abaixo dos filtros mostra quem mais aprovou leis no recorte escolhido.</p>
</section>
{filtros_lista('leis', cliente)}"""
    return pagina("Leis aprovadas · Radar dos Vereadores de Niterói", corpo, "leis.html", manifesto=manifesto, dialogo=True, caminho="leis.html")


def gerar_projetos(cliente: dict | None = None, manifesto: dict | None = None) -> str:
    corpo = f"""<section class="abertura">
 <h1>Todos os projetos de lei</h1>
 <p>Os projetos apresentados desde 2021, incluindo os arquivados, vetados e em tramitação. Os filtros ficam no endereço da página, então dá para compartilhar uma busca.</p>
</section>
{filtros_lista('projetos', cliente)}"""
    return pagina("Projetos de lei · Radar dos Vereadores de Niterói", corpo, "projetos.html", manifesto=manifesto, dialogo=True, caminho="projetos.html")


# ------------------------------------------------------------------- novidades
def item_evento(ev: dict, prefixo: str) -> str:
    """Um evento: o número do PL leva ao SISCAM, e os autores vereadores, às suas páginas."""
    p = ev["projeto"]
    sub = ""
    if ev.get("substitutivo"):
        sub = (f' · <a class="via-substitutivo" href="{esc(N.url_detalhe(ev["substitutivo"]))}" target="_blank" rel="noopener">'
               f'substitutivo no SISCAM<span class="so-leitor"> (substitutivo ao PL {esc(p["numero"])})</span>{NOVA_ABA}</a>')
    resumo = f'<p class="resumo-ia">{esc(p["resumo"])}</p>' if p.get("resumo") else ""
    partido = f'<span class="partido">{esc(p["partido"])}</span>' if p.get("partido") else ""
    return f"""<li class="projeto ev-{esc(ev['tipo'])}">
 <p class="cab"><span class="desfecho">{esc(N.ROTULO_EVENTO[ev['tipo']])}</span><time datetime="{esc(ev['data'])}">{data_br(ev['data'])}</time><a href="{esc(p['url'])}" target="_blank" rel="noopener">PL {esc(p['numero'])}{NOVA_ABA}</a></p>
 <p class="titulo-evento">{esc(N.titulo_evento(ev))}{sub}</p>
 {resumo}<p class="ementa">{esc(legivel(p['ementa']))}</p>
 <p class="autoria">{autores_html(p, prefixo)}{partido}</p>
</li>"""


def secao_semana(semana: dict, prefixo: str, mais_recente: bool) -> str:
    ident = f"semana-{semana['inicio']}"
    marca = " <span>mais recente</span>" if mais_recente else ""
    if semana["eventos"]:
        contagem = " · ".join(f"<b>{n}</b> {esc(N.NOME_EVENTO[t][0 if n == 1 else 1])}" for t, n in semana["contagem"].items())
        corpo = (f'<p class="contagem">{contagem}</p>\n'
                 f'<ol class="projetos">{"".join(item_evento(e, prefixo) for e in semana["eventos"])}</ol>')
    else:
        corpo = '<p class="vazio">Nenhum evento com data nesta semana.</p>'
    return f"""<section class="semana" id="{ident}" aria-labelledby="t-{ident}">
<h2 id="t-{ident}">Semana de {data_br(semana['inicio'])} a {data_br(semana['fim'])}{marca}</h2>
{corpo}
</section>"""


def gerar_novidades(eventos: list[dict]) -> str:
    """Últimas N.SEMANAS semanas ISO até a da data mais recente dos eventos (nunca a data de hoje)."""
    semanas = N.semanas_recentes(eventos)
    if semanas:
        referencia = (f"Semana mais recente: {data_br(semanas[0]['inicio'])} a {data_br(semanas[0]['fim'])}, "
                      "a da última data encontrada nos dados")
    else:
        referencia = "Nenhum evento com data encontrado nos dados"
    indice = "".join(f'<a href="#semana-{s["inicio"]}">{data_br(s["inicio"])[:5]} ({sum(s["contagem"].values())})</a>'
                     for s in semanas)
    corpo = f"""<section class="abertura">
 <h1>Novidades</h1>
 <p>Projetos de lei apresentados, leis sancionadas ou promulgadas, vetos do prefeito e vetos derrubados pela Câmara nas últimas {N.SEMANAS} semanas, pelas datas registradas no SISCAM. Cada item leva ao projeto no SISCAM e às páginas dos vereadores autores.</p>
 <p class="atualizacao">{esc(referencia)} · <a href="{N.FEED}" type="application/rss+xml">assinar o feed RSS</a> · <a href="metodologia.html#novidades">de onde vêm as datas</a></p>
</section>
{f'<nav class="indice" aria-label="Semanas, pela segunda-feira, com o número de eventos">{indice}</nav>' if indice else ''}
{''.join(secao_semana(s, '', i == 0) for i, s in enumerate(semanas)) or '<p class="vazio">Nenhum evento encontrado.</p>'}"""
    return pagina("Novidades · Radar dos Vereadores de Niterói", corpo, "novidades.html",
                  caminho="novidades.html",
                  descricao="O que aconteceu nas últimas semanas com os projetos de lei da Câmara de Niterói: projetos apresentados, "
                            "leis, vetos e vetos derrubados, com feed RSS.")


# ------------------------------------------------------------------ atividades
def _chave_nome(nome: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", nome.lower()) if not unicodedata.combining(c))


def mapa_indicacoes(modelo: dict, docs: list[dict], titulo: str, *, limite_gzip: int | None = None) -> str:
    """Reusa os agregados existentes; o orçamento individual inclui SVG, legenda, tabela e atribuição."""
    geo = modelo.get("geo_bairros")
    if not geo:
        return ""
    resumo = resumo_bairros(docs)
    valores = {b["bairro"]: b["indicacoes"] for b in indicacoes_por_bairro(docs)}
    mapa = G.mapa_coropletico(valores, geo, titulo,
                             "Valores absolutos, sem ajuste por população. Bairro inferido da ementa por regras; "
                             f"{pct_txt(resumo['pct_sem_bairro'])} sem bairro identificado "
                             f"({milhar(resumo['sem_bairro'])} de {milhar(resumo['indicacoes'])} indicações), fora do mapa.")
    if limite_gzip is not None and len(gzip.compress(mapa.encode("utf-8"), mtime=0)) > limite_gzip:
        return ""
    return mapa


def gerar_atividades(modelo: dict, manifesto: dict | None = None) -> str:
    docs = modelo.get("documentos") or []
    abertura = """<section class="abertura">
 <h1>Atividades na Câmara</h1>
 <p>Indicações, moções, requerimentos, projetos de decreto legislativo e projetos de resolução apresentados desde 2021, separados dos projetos de lei. Filtre por tipo, ano, vereador, categoria ou bairro; cada item leva ao documento oficial no SISCAM. Os filtros ficam no endereço da página.</p>
 <p class="atualizacao">Classificação por regras sobre a ementa · <a href="metodologia.html#atividades">como classificamos</a></p>
</section>"""
    titulo = "Atividades · Radar dos Vereadores de Niterói"
    descricao = "Indicações, moções, requerimentos, PDLs e resoluções da Câmara de Niterói, por vereador, tipo, categoria e bairro."
    ano_padrao = ano_padrao_doc(manifesto["arquivos"]) if manifesto and manifesto.get("build_doc") else None
    if not docs or ano_padrao is None:
        return pagina(titulo, abertura + '\n<p class="vazio">Nenhum documento coletado ainda.</p>', "atividades.html", descricao=descricao, caminho="atividades.html")

    def opcoes(pares) -> str:
        return "".join(f'<option value="{esc(k)}">{esc(v)}</option>' for k, v in pares)

    por_tipo = Counter(d["tipo"] for d in docs)
    por_ano = Counter(d["ano"] for d in docs)
    autores = {a["slug"]: a["exibicao"] for d in docs for a in d["autores"] if a["vereador"]}
    categorias = Counter(d["categoria"] for d in docs)
    subcategorias = Counter((d["tipo"], d["subcategoria"]) for d in docs)
    bairros = Counter(d["bairro"] for d in docs if d["bairro"])
    situacoes = Counter(d["situacao"] for d in docs if d["situacao"])

    op_tipos = opcoes((t, f"{NOME_TIPO_DOC[t][1]} ({milhar(por_tipo[t])})") for t in TIPOS_DOC if por_tipo[t])
    op_anos = '<option value="todos">Todos os anos</option>' + "".join(
        f'<option value="{a}"{" selected" if a == ano_padrao else ""}>{a} ({milhar(por_ano[a])})</option>' for a in sorted(por_ano, reverse=True))
    op_autores = opcoes(sorted(autores.items(), key=lambda par: (_chave_nome(par[1]), par[0])))
    ordem_cat = [c for c in NOME_CATEGORIA_DOC if categorias[c]] + sorted(c for c in categorias if c not in NOME_CATEGORIA_DOC)
    op_cat = opcoes((c, f"{NOME_CATEGORIA_DOC.get(c, c)} ({milhar(categorias[c])})") for c in ordem_cat)
    op_sub = ""
    for t in TIPOS_DOC:
        subs = sorted(((s, n) for (tt, s), n in subcategorias.items() if tt == t), key=lambda sn: (-sn[1], sn[0]))
        if subs:
            op_sub += (f'<optgroup label="{esc(NOME_TIPO_DOC[t][1])}">'
                       + opcoes((f"{t}:{s}", f"{NOME_SUBCATEGORIA_DOC.get((t, s), s)} ({milhar(n)})") for s, n in subs) + "</optgroup>")
    op_bairros = opcoes((b, f"{b} ({milhar(n)})") for b, n in sorted(bairros.items(), key=lambda bn: (_chave_nome(bn[0]), bn[0])))
    op_sit = opcoes((s, f"{situacao_legivel(s)} ({milhar(n)})") for s, n in sorted(situacoes.items(), key=lambda sn: (-sn[1], sn[0])))
    n_inicial = por_ano[ano_padrao]
    resumos = secao_resumos_atividades(modelo)
    destinos = [(i, t) for i, t in (("pedidos-informacao", "Requerimentos de informação"), ("bairros", "Bairros das indicações"))
                if f'id="{i}"' in resumos]
    indice = ""
    if destinos:
        indice = ('\n<nav class="indice" aria-label="Nesta página"><a href="#resultados">Lista de documentos</a>'
                  + "".join(f'<a href="#{i}">{esc(t)}</a>' for i, t in destinos) + "</nav>")

    corpo = f"""{abertura}{indice}
<form class="filtros" role="search" onsubmit="return false" data-modo="atividades" data-ano-padrao="{ano_padrao}">
 <div class="linha-busca"><label class="busca-q">Buscar <input type="search" id="q" placeholder="rua, bairro, número, assunto, vereador…" autocomplete="off"></label>
  <label>Ordenar <select id="f-ordem"><option value="recente">Mais recentes</option><option value="antigo">Mais antigos</option></select></label></div>
 <details class="mais-filtros" open><summary>Mais filtros</summary>
 <div class="grade-filtros">
  <label>Tipo <select id="f-tipo"><option value="">Todos</option>{op_tipos}</select></label>
  <label>Ano <select id="f-ano">{op_anos}</select></label>
  <label>Vereador <select id="f-autor"><option value="">Todos</option>{op_autores}</select></label>
  <label>Categoria <select id="f-categoria"><option value="">Todas</option>{op_cat}</select></label>
  <label>Subcategoria <select id="f-subcategoria"><option value="">Todas</option>{op_sub}</select></label>
  <label>Bairro <select id="f-bairro"><option value="">Todos</option>{op_bairros}</select></label>
  <label>Situação <select id="f-situacao"><option value="">Todas</option>{op_sit}</select></label>
  <label>Resposta <select id="f-respondido"><option value="">Qualquer</option><option value="1">Requerimentos respondidos</option><option value="0">Requerimentos sem resposta</option></select></label>
  <label>Publicação <select id="f-publicado"><option value="">Qualquer</option><option value="1">Publicados</option><option value="0">Não publicados</option></select></label>
 </div>
 </details>
 <p class="acoes-filtro"><button type="button" id="limpar">Limpar filtros</button> <button type="button" id="csv">Baixar CSV</button></p>
</form>
<div class="resumo-filtro" id="resumo-filtro" aria-live="polite"><p class="contagem"><b>{milhar(n_inicial)}</b> {'documento' if n_inicial == 1 else 'documentos'} em {ano_padrao}</p></div>
<p id="anuncio" class="so-leitor" aria-live="polite"></p>
<ol id="resultados" class="projetos documentos"></ol>
<button type="button" id="mais" class="mais" hidden>Mostrar mais</button>
<noscript><p class="vazio">A lista de documentos precisa de JavaScript. Os documentos mais recentes de cada vereador também aparecem na página dele.</p></noscript>
{resumos}"""
    return pagina(titulo, corpo, "atividades.html", descricao=descricao, manifesto=manifesto, dialogo=True, caminho="atividades.html")


def secao_resumos_atividades(modelo: dict) -> str:
    """Resumos de atividades.html gerados no servidor, sobre todos os anos coletados e sem os filtros da lista.

    Requerimentos de informação por vereador (por legislatura) e por órgão; bairros das indicações nos 52 bairros
    oficiais e por vereador. Só agregados: o volume não cresce com o número de documentos.
    """
    docs = modelo.get("documentos") or []
    if not docs:
        return ""
    por_leg = documentos_por_legislatura(modelo)
    legs = [leg["id"] for leg in reversed(modelo["legislaturas"]) if leg["id"] in por_leg]
    periodo = periodo_docs(modelo)

    def ordem_nome(s: str) -> str:
        return _chave_nome(nome_autor(modelo, s))

    blocos_info, blocos_bairro = [], []
    for leg in legs:
        info = [(s, resumo_informacao(ds)) for s, ds in por_leg[leg].items()]
        info = sorted(((s, r) for s, r in info if r["pedidos"]), key=lambda sr: (-sr[1]["pedidos"], ordem_nome(sr[0])))
        if info:
            tab = tabela_resumo(f"Requerimentos de informação por vereador, legislatura {leg}", ["Vereador", *CAB_INFORMACAO],
                                [[link_autor(modelo, s, ""), *celulas_informacao(r)] for s, r in info])
            blocos_info.append(f'<details class="bloco"{" open" if not blocos_info else ""}><summary>Legislatura {esc(leg)} '
                               f'({plural(len(info), "vereador", "vereadores")})</summary>{tab}</details>')
        bairros = [(s, resumo_bairros(ds)) for s, ds in por_leg[leg].items()]
        bairros = sorted(((s, r) for s, r in bairros if r["indicacoes"]), key=lambda sr: (-sr[1]["indicacoes"], ordem_nome(sr[0])))
        if bairros:
            tab = tabela_resumo(f"Bairros das indicações por vereador, legislatura {leg}", ["Vereador", *CAB_BAIRROS],
                                [[link_autor(modelo, s, ""), *celulas_bairros(r)] for s, r in bairros], texto=TEXTO_BAIRROS)
            blocos_bairro.append(f'<details class="bloco"{" open" if not blocos_bairro else ""}><summary>Legislatura {esc(leg)} '
                                 f'({plural(len(bairros), "vereador", "vereadores")})</summary>{tab}</details>')

    geral = resumo_informacao(docs)
    orgaos = ranking_orgaos(docs)
    secao_info = ""
    if geral["pedidos"]:
        tab_orgaos = tabela_resumo(f"Requerimentos de informação por órgão citado, {periodo}", ["Órgão", *CAB_INFORMACAO],
                                   [[esc(o["orgao"]), *celulas_informacao(o)] for o in orgaos])
        secao_info = f"""<section id="pedidos-informacao" aria-labelledby="t-pedidos-informacao">
 <h2 id="t-pedidos-informacao" class="h-secao">Requerimentos de informação</h2>
 <p class="explica">{esc(EXPLICA_INFORMACAO)} {esc(pendentes_txt(geral))}</p>
 <div class="tiles">
  {tile(milhar(geral['pedidos']), "requerimentos de informação", periodo)}
  {tile(pct_txt(geral['taxa']), "têm resposta registrada", f"{milhar(geral['respondidos'])} respondidos", "tile-efeito")}
  {tile(f"{G._fmt(geral['mediana_dias'])} dias" if geral['mediana_dias'] is not None else "—", "é a mediana até o passo “Respondido”", base_mediana_txt(geral))}
  {tile(milhar(geral['aguardando']), "aguardam resposta", "sem resposta registrada e sem arquivamento")}
 </div>
 {''.join(blocos_info)}
 <h3>Por órgão citado</h3>
 <p class="explica">{esc(EXPLICA_ORGAOS)}</p>
 {tab_orgaos}
</section>"""

    por_bairro = indicacoes_por_bairro(docs)
    rb = resumo_bairros(docs)
    secao_bairros = ""
    if rb["indicacoes"]:
        itens = [{"rotulo": b["bairro"], "v": b["indicacoes"]} for b in sorted(por_bairro, key=lambda b: (-b["indicacoes"], _chave_nome(b["bairro"])))]
        graf = G.barras_horizontais(f"Indicações por bairro, {periodo}",
                                    "Os 52 bairros oficiais de Niterói, inclusive os que não aparecem em nenhuma indicação.",
                                    itens, [("Indicações", "c-t-indicacao", "v")], max_itens=len(itens))
        graf = mapa_indicacoes(modelo, docs, f"Indicações por bairro, {periodo}") or graf
        menos = menos_citados(por_bairro)
        sem_nenhuma = sum(1 for b in por_bairro if not b["indicacoes"])
        secao_bairros = f"""<section id="bairros" aria-labelledby="t-bairros">
 <h2 id="t-bairros" class="h-secao">Bairros das indicações</h2>
 <p class="explica">{esc(EXPLICA_BAIRROS)}</p>
 <div class="tiles">
  {tile(milhar(rb['indicacoes']), "indicações", periodo)}
  {tile(pct_txt(rb['pct_sem_bairro']), "sem bairro identificado", f"{milhar(rb['sem_bairro'])} indicações", "tile-sem")}
  {tile(rb['distintos'], "dos 52 bairros aparecem", plural(sem_nenhuma, "bairro sem indicação", "bairros sem indicação"))}
 </div>
 <p class="nota">Menos citados: {esc(", ".join(f"{b['bairro']} ({b['indicacoes']})" for b in menos))}.</p>
 {graf}
 {''.join(blocos_bairro)}
</section>"""
    if not (secao_info or secao_bairros):
        return ""
    return f"""<section class="resumos-atividades" aria-label="Resumos de todos os anos coletados">
<p class="explica">Os resumos abaixo cobrem todos os documentos coletados ({esc(periodo)}) e não mudam com os filtros da lista. <a href="metodologia.html#metricas-documentos">Como contamos</a>.</p>
{secao_info}
{secao_bairros}
</section>"""


# --------------------------------------------------------------------- ruído
def gerar_ruido(modelo: dict) -> str:
    projs = modelo["projetos"]
    legs = modelo["legislaturas"]
    atual = legs[-1]["id"]
    ver = [p for p in projs if p["origem"] == "vereador"]
    leis_ver = [p for p in ver if p["desfecho"] == "virou_lei"]
    simb = [p for p in leis_ver if p["categoria"] == "simbolica"]
    autoriz = [p for p in ver if "autorizativa" in p["sinais"]]
    autoriz_leis = [p for p in autoriz if p["desfecho"] == "virou_lei"]
    rep = [p for p in ver if "repete_projeto" in p["sinais"]]
    curados = [p for p in projs if any(a["origem"] == "curadoria" for a in p["alertas"]) or "inconstitucionalidade_declarada" in p["sinais"]]
    ia = [p for p in projs if p not in curados and (p["polemico"] or p["risco_juridico"])]
    ia.sort(key=lambda p: p["data"] or "", reverse=True)

    pessoas = [p for p in modelo["pessoas"].values() if atual in p["mandatos"] and p["mandatos"][atual]["metricas"]["leis"]]
    itens = [{"rotulo": p["nome"], "link": f"vereadores/{p['slug']}.html", "efeito": p["mandatos"][atual]["metricas"]["leis_efeito"],
              "baixo": p["mandatos"][atual]["metricas"]["leis_outras"], "sem": p["mandatos"][atual]["metricas"]["leis_sem_efeito"]} for p in pessoas]
    itens.sort(key=lambda i: (-i["sem"], i["efeito"]))
    graf = G.barras_horizontais(
        f"Leis aprovadas por vereador na legislatura {atual}, por efeito",
        "Ordenado pelo número de leis sem efeito prático (homenagens, datas, nomes e leis autorizativas).",
        itens, [("Sem efeito prático", "c-sem-efeito", "sem"), ("Impacto baixo", "c-baixo", "baixo"), ("Com efeito", "c-efeito", "efeito")])

    por_tipo = Counter()
    for p in simb:
        e = p["ementa"].upper()
        if "CALEND" in e or "DIA " in e or "SEMANA" in e or "3.474" in e or "3474" in e:
            por_tipo["Datas e semanas comemorativas"] += 1
        elif "DENOMIN" in e or " NOME" in e:
            por_tipo["Nomes de ruas e prédios"] += 1
        elif "UTILIDADE" in e:
            por_tipo["Declarações de utilidade pública"] += 1
        elif "PATRIM" in e or "TOMBA" in e:
            por_tipo["Patrimônio e tombamento"] += 1
        else:
            por_tipo["Outras homenagens e títulos"] += 1
    graf_tipo = G.barras_horizontais("Leis simbólicas de vereadores desde 2021, por tipo", "",
                                     [{"rotulo": k, "v": v} for k, v in por_tipo.most_common()], [("Leis", "c-sem-efeito", "v")])

    homenagens = secao_homenagens(modelo)
    link_homenagens = '<a href="#homenagens">Homenagens</a>' if homenagens else ""

    def lista(ps: list[dict], vazio: str, consulta: str) -> str:
        itens = "".join(item_projeto(p, "") for p in ps[:LIMITE_ITENS_RUIDO]) or f'<li class="vazio">{esc(vazio)}</li>'
        return (f'<ol class="projetos">{itens}</ol><p>Exibindo {min(len(ps), LIMITE_ITENS_RUIDO)} de {len(ps)}. '
                f'<a href="projetos.html?{esc(consulta)}">Ver lista completa ({len(ps)})</a></p>')

    corpo = f"""<section class="abertura">
 <h1>Sem efeito e polêmicas</h1>
 <p>Uma parte da produção da Câmara não muda nada na vida da cidade: homenagens, datas comemorativas, nomes de rua, leis que só "autorizam" o prefeito a fazer o que ele já pode fazer, e projetos que repetem outros. Outra parte gera conflito: restringe direitos de grupos, explora pauta de costumes ou tem apelo populista. Esta página reúne as duas.</p>
</section>
<div class="tiles">
 {tile(len(simb), "leis simbólicas aprovadas desde 2021", f"{round(100 * len(simb) / max(len(leis_ver), 1))}% das leis de vereadores", "tile-sem")}
 {tile(len(autoriz), "projetos autorizativos", f"{sum(1 for p in autoriz if p['desfecho'] == 'virou_lei')} viraram lei", "tile-sem")}
 {tile(len(rep), "projetos repetem um anterior", "ementa quase idêntica", "")}
 {tile(sum(1 for p in projs if p['polemico']), "projetos com alerta de polêmica", f"{len(curados)} revisados por curadoria", "tile-alerta")}
</div>
<nav class="indice" aria-label="Nesta página"><a href="#por-vereador">Por vereador</a>{link_homenagens}<a href="#polemicas">Polêmicas revisadas</a><a href="#ia">Marcadas por IA</a><a href="#autorizativas">Autorizativas</a><a href="#repetidos">Repetidos</a></nav>
<section id="por-vereador">{graf}{graf_tipo}</section>{homenagens}
<section id="polemicas"><h2 class="h-secao">Polêmicas revisadas por curadoria ({len(curados)})</h2><p class="explica">Cada item tem fonte pública em <a href="{REPO}/blob/main/config/curadoria.json">config/curadoria.json</a>.</p>{lista(curados, "Nenhum projeto revisado.", "sinal=curadoria")}</section>
<section id="ia"><h2 class="h-secao">Marcadas por IA ({len(ia)})</h2><p class="explica">Alertas sugeridos pela IA a partir da ementa, com confiança mínima de {int(CONFIANCA_MINIMA * 100)}%. Podem conter erros; cada um tem link para contestar.</p>{lista(ia, "Nenhum projeto marcado por IA ainda.", "sinal=alerta_ia")}</section>
<section id="autorizativas"><h2 class="h-secao">Leis autorizativas aprovadas ({len(autoriz_leis)})</h2><p class="explica">{esc(DESC_SINAL['autorizativa'])}</p>{lista(autoriz_leis, "Nenhuma.", "origem=vereador&desfecho=lei&sinal=autorizativa")}</section>
<section id="repetidos"><h2 class="h-secao">Projetos que repetem outro ({len(rep)})</h2><p class="explica">{esc(DESC_SINAL['repete_projeto'])} Reapresentar um projeto arquivado é legítimo; o sinal serve para ver o quanto da produção é reaproveitada.</p>{lista(sorted(rep, key=lambda p: p['data'] or '', reverse=True), "Nenhum.", "origem=vereador&sinal=repete_projeto")}</section>"""
    return pagina("Sem efeito e polêmicas · Radar dos Vereadores de Niterói", corpo, "ruido.html", caminho="ruido.html")


def secao_homenagens(modelo: dict) -> str:
    """Homenagens em documentos: evolução por ano na Câmara e, por legislatura, contagem e peso de cada vereador.

    Vazia sem documentos coletados. As tabelas por vereador agregam; o tamanho não cresce com os documentos.
    """
    docs = modelo.get("documentos") or []
    if not docs:
        return ""
    anos = anos_documentos(modelo)
    if not anos:
        return f"""
<section id="homenagens" aria-labelledby="t-homenagens">
 <h2 id="t-homenagens" class="h-secao">Homenagens em moções, PDLs e resoluções</h2>
 <p class="vazio">Sem dados: nenhum ano tem os cinco tipos de documento coletados, e o peso das homenagens só é calculado em anos de coleta completa.</p>
 {nota_parciais(modelo)}
</section>"""
    periodo = periodo_txt(anos)
    por_ano = homenagens_por_ano(docs, modelo["projetos"], anos)
    rotulos = [str(l["ano"]) for l in por_ano]
    tipos = [t for t in TIPOS_DOC if any(l["por_tipo"][t] for l in por_ano)]
    graf = ""
    if tipos:
        graf = G.colunas_empilhadas(
            "Homenagens por ano e tipo de documento",
            "Moções de aplauso e de pesar, títulos de cidadão e honrarias em PDLs e resoluções, de qualquer autor, pelo ano do número.",
            rotulos, [(NOME_TIPO_DOC[t][1], f"c-t-{t}", [l["por_tipo"][t] for l in por_ano]) for t in tipos], altura=220)
    tab_anos = tabela_resumo(
        "Peso das homenagens na produção total da Câmara, por ano",
        ["Ano", "Homenagens", "Documentos", "Projetos de lei", "% da produção"],
        [[str(l["ano"]), l["homenagens"], l["documentos"], l["projetos"], pct_txt(l["pct"])] for l in por_ano])
    slugs = set(modelo.get("atividade") or {}) | set(modelo["pessoas"])
    por_autor = {s: homenagens_do_autor(modelo, s, anos)["por_leg"] for s in slugs}
    blocos = []
    for leg in reversed(modelo["legislaturas"]):
        linhas = [(s, pl[leg["id"]]) for s, pl in por_autor.items() if leg["id"] in pl and pl[leg["id"]]["producao"]]
        if not linhas:
            continue
        linhas.sort(key=lambda sr: (-sr[1]["homenagens"], -(sr[1]["pct"] or 0), _chave_nome(nome_autor(modelo, sr[0]))))
        tab = tabela_resumo(f"Homenagens por vereador, legislatura {leg['id']}",
                            ["Vereador", "Homenagens", "Documentos", "Projetos de lei (autor principal)", "% da produção"],
                            [[link_autor(modelo, s, ""), r["homenagens"], r["documentos"], r["projetos"], pct_txt(r["pct"])]
                             for s, r in linhas])
        blocos.append(f'<details class="bloco"{" open" if not blocos else ""}><summary>Legislatura {esc(leg["id"])} '
                      f'({plural(len(linhas), "vereador", "vereadores")})</summary>{tab}</details>')
    total = sum(l["homenagens"] for l in por_ano)
    producao = sum(l["producao"] for l in por_ano)
    return f"""
<section id="homenagens" aria-labelledby="t-homenagens">
 <h2 id="t-homenagens" class="h-secao">Homenagens em moções, PDLs e resoluções ({milhar(total)})</h2>
 <p class="explica">{esc(EXPLICA_HOMENAGENS)} Na Câmara, a produção total soma documentos e projetos de lei de qualquer autor. Período: {esc(periodo)}. <a href="metodologia.html#metricas-documentos">Como contamos</a>.</p>
 {nota_parciais(modelo)}
 <div class="tiles">
  {tile(milhar(total), "homenagens em documentos", periodo, "tile-sem")}
  {tile(pct_txt(round(100 * total / producao) if producao else None), "da produção total da Câmara", "documentos e projetos de lei de qualquer autor")}
 </div>
 {graf}
 {tab_anos}
 <h3>Por vereador</h3>
 {''.join(blocos) or '<p class="vazio">Nenhum vereador com documentos ou projetos no período.</p>'}
</section>"""


# ------------------------------------------------------------------- análises
def gerar_analises(modelo: dict) -> str:
    projs = modelo["projetos"]
    anos = sorted({p["ano"] for p in projs})
    rot = [str(a) for a in anos]
    ver = [p for p in projs if p["origem"] == "vereador"]

    def conta(filtro, por="ano"):
        c = Counter(p[por] for p in projs if filtro(p))
        return [c.get(a, 0) for a in anos]

    g1 = G.colunas_empilhadas(
        "Projetos de vereadores por ano de apresentação, pelo desfecho", "Projetos recentes ainda estão em tramitação.", rot, [
            ("Virou lei com efeito", "c-efeito", conta(lambda p: p["origem"] == "vereador" and com_efeito(p))),
            ("Virou lei de impacto baixo", "c-baixo", conta(lambda p: p["origem"] == "vereador" and p["desfecho"] == "virou_lei" and not com_efeito(p) and not sem_efeito(p))),
            ("Virou lei sem efeito prático", "c-sem-efeito", conta(lambda p: p["origem"] == "vereador" and p["desfecho"] == "virou_lei" and sem_efeito(p))),
            ("Em andamento", "c-andamento", conta(lambda p: p["origem"] == "vereador" and DESFECHO_GRUPO.get(p["desfecho"]) == "andamento")),
            ("Sem êxito", "c-sem-exito", conta(lambda p: p["origem"] == "vereador" and DESFECHO_GRUPO.get(p["desfecho"]) == "sem_exito")),
        ])

    def ano_lei(p):
        d = (p.get("lei") or {}).get("data")
        return int(d[:4]) if d else p["ano"]
    leis = [p for p in projs if p["desfecho"] == "virou_lei"]
    anos_lei = sorted({ano_lei(p) for p in leis if ano_lei(p) >= anos[0]})
    rot_l = [str(a) for a in anos_lei]

    def conta_l(f):
        c = Counter(ano_lei(p) for p in leis if f(p))
        return [c.get(a, 0) for a in anos_lei]
    g2 = G.colunas_empilhadas("Leis sancionadas ou promulgadas por ano, pela autoria", "Ano em que o projeto virou lei.", rot_l, [
        ("Vereadores, com efeito", "c-efeito", conta_l(lambda p: p["origem"] == "vereador" and com_efeito(p))),
        ("Vereadores, sem efeito ou impacto baixo", "c-sem-efeito", conta_l(lambda p: p["origem"] == "vereador" and not com_efeito(p))),
        ("Prefeitura", "c-exec", conta_l(lambda p: p["origem"] == "executivo")),
    ])

    def med_dias(f):
        out = []
        for a in anos_lei:
            ds = [p["dias_ate_lei"] for p in leis if ano_lei(p) == a and f(p) and p["dias_ate_lei"] is not None]
            out.append(int(statistics.median(ds)) if ds else None)
        return out
    g3 = G.linhas("Tempo mediano entre o protocolo e a lei, em dias", "Por ano em que o projeto virou lei.", rot_l, [
        ("Vereadores", "c-efeito", med_dias(lambda p: p["origem"] == "vereador")),
        ("Prefeitura", "c-exec", med_dias(lambda p: p["origem"] == "executivo")),
    ], unidade=" dias")

    temas = Counter(p["tema"] for p in leis if p["origem"] == "vereador" and com_efeito(p) and p["tema"] not in ("homenagem", "outro"))
    g4 = "" if len(temas) < 3 else G.barras_horizontais("Temas das leis de vereadores com efeito, desde 2021", "Tema atribuído pela IA a partir da ementa.",
                              [{"rotulo": NOME_TEMA.get(t, t), "v": n, "link": f"leis.html?efeito=1&tema={t}"} for t, n in temas.most_common(14)],
                              [("Leis com efeito", "c-efeito", "v")])
    g5 = grafico_producao_por_tipo(modelo)

    blocos_leg = []
    for leg in reversed(modelo["legislaturas"]):
        pessoas = [p for p in modelo["pessoas"].values() if leg["id"] in p["mandatos"] and p["mandatos"][leg["id"]]["metricas"]["apresentados"]]
        pts = [{"x": p["mandatos"][leg["id"]]["metricas"]["apresentados"], "y": p["mandatos"][leg["id"]]["metricas"]["leis_efeito"],
                "rotulo": p["nome"], "link": f"vereadores/{p['slug']}.html",
                "cor": "c-efeito" if p["mandatos"][leg["id"]]["eleito"] else "c-andamento"} for p in pessoas]
        gd = G.dispersao(f"Volume x resultado, legislatura {leg['id']}",
                         "Cada ponto é um vereador. Mais à direita, mais projetos apresentados; mais acima, mais leis com efeito. Suplentes em cinza.",
                         pts, "Projetos apresentados como autor", "Leis com efeito", rotular=10)
        part = defaultdict(lambda: Counter())
        for p in pessoas:
            m = p["mandatos"][leg["id"]]
            if not m["partido"]:
                continue
            part[m["partido"]]["vereadores"] += 1
            part[m["partido"]]["efeito"] += m["metricas"]["leis_efeito"]
            part[m["partido"]]["sem"] += m["metricas"]["leis_sem_efeito"]
            part[m["partido"]]["baixo"] += m["metricas"]["leis_outras"]
        it = [{"rotulo": f"{pt} ({c['vereadores']})", "efeito": c["efeito"], "baixo": c["baixo"], "sem": c["sem"]} for pt, c in part.items()]
        it.sort(key=lambda i: (-i["efeito"], -i["baixo"]))
        gp = G.barras_horizontais(f"Leis aprovadas por partido, legislatura {leg['id']}",
                                  "Partido pelo qual o vereador foi eleito; entre parênteses, quantos eleitos do partido apresentaram projetos.",
                                  it, [("Com efeito", "c-efeito", "efeito"), ("Impacto baixo", "c-baixo", "baixo"), ("Sem efeito prático", "c-sem-efeito", "sem")])
        blocos_leg.append(f'<section class="bloco-leg"><h2 class="h-secao">Legislatura {esc(leg["id"])}</h2>{gd}{gp}</section>')

    corpo = f"""<section class="abertura">
 <h1>Análises históricas</h1>
 <p>Como a produção legislativa de Niterói evoluiu desde 2021: quanto vira lei, quanto disso tem efeito, quanto tempo leva e quais temas dominam. Cada gráfico tem uma tabela com os números.</p>
</section>
<div class="graficos">{g1}{g2}{g3}{g4}{g5}</div>
{''.join(blocos_leg)}"""
    return pagina("Análises · Radar dos Vereadores de Niterói", corpo, "analises.html", caminho="analises.html")


def grafico_producao_por_tipo(modelo: dict) -> str:
    """Produção total da Câmara por tipo de documento e ano, de qualquer autor; vazio sem documentos."""
    docs = modelo.get("documentos") or []
    if not docs:
        return ""
    projs = modelo["projetos"]
    anos = sorted({p["ano"] for p in projs} | {d["ano"] for d in docs})
    pl = Counter(p["ano"] for p in projs)
    cont = Counter((d["tipo"], d["ano"]) for d in docs)
    series = [("Projetos de lei", "c-t-pl", [pl.get(a, 0) for a in anos])]
    series += [(NOME_TIPO_DOC[t][1], f"c-t-{t}", [cont.get((t, a), 0) for a in anos]) for t in TIPOS_DOC
               if any(cont.get((t, a)) for a in anos)]
    return G.colunas_empilhadas(
        "Produção total da Câmara por tipo e ano",
        "Documentos de qualquer autor, pelo ano do número. Contar documentos não mede qualidade nem resultado; detalhes em Atividades.",
        [str(a) for a in anos], series)


# ------------------------------------------------------------------ vereador
def comparacao(valor, mediana, maior_melhor: bool = True, sufixo: str = "") -> str:
    if valor is None or mediana is None:
        return ""
    if valor == mediana:
        return f"igual à mediana dos eleitos ({G._fmt(mediana)}{sufixo})"
    acima = valor > mediana
    return f"{'acima' if acima else 'abaixo'} da mediana dos eleitos ({G._fmt(mediana)}{sufixo})"


def gerar_vereador(modelo: dict, pessoa: dict) -> str:
    from coletor.site import pagina_sessoes

    secoes = []
    for leg in reversed(modelo["legislaturas"]):
        m = pessoa["mandatos"].get(leg["id"])
        if not m:
            continue
        me = m["metricas"]
        afast = "".join(f'<p class="aviso">Afastou-se da Câmara para o cargo de {esc(a["cargo"])} (<a href="{esc(a["fonte"])}">fonte</a>). Nesse período a cadeira foi ocupada por suplente.</p>' for a in m["afastamentos"])
        cond = "Eleito" if m["eleito"] else "Suplente em exercício"
        med = lambda k: mediana_legislatura(modelo, leg["id"], k)
        proj = sorted(m["projetos_autor"], key=lambda p: p["data"] or "", reverse=True)
        leis = [p for p in proj if p["desfecho"] == "virou_lei"]
        efeito = sorted([p for p in leis if com_efeito(p)], key=lambda p: (-(p["impacto"] or 0), (p.get("lei") or {}).get("data") or ""))
        sem = [p for p in leis if sem_efeito(p)]
        polem = [p for p in proj if p["polemico"] or p["risco_juridico"]]

        anos = sorted({p["ano"] for p in proj})
        graf_ano = ""
        if len(anos) > 1:
            c = lambda f: [sum(1 for p in proj if p["ano"] == a and f(p)) for a in anos]
            graf_ano = G.colunas_empilhadas("Projetos por ano de apresentação", "", [str(a) for a in anos], [
                ("Lei com efeito", "c-efeito", c(com_efeito)),
                ("Lei de impacto baixo", "c-baixo", c(lambda p: p["desfecho"] == "virou_lei" and not com_efeito(p) and not sem_efeito(p))),
                ("Lei sem efeito prático", "c-sem-efeito", c(lambda p: p["desfecho"] == "virou_lei" and sem_efeito(p))),
                ("Em andamento", "c-andamento", c(lambda p: DESFECHO_GRUPO.get(p["desfecho"]) == "andamento")),
                ("Sem êxito", "c-sem-exito", c(lambda p: DESFECHO_GRUPO.get(p["desfecho"]) == "sem_exito")),
            ], altura=200)
        temas = Counter(p["tema"] for p in proj if p["tema"] not in ("outro",))
        graf_tema = "" if len(temas) < 2 else G.barras_horizontais("Temas dos projetos apresentados", "", [{"rotulo": NOME_TEMA.get(t, t), "v": n} for t, n in temas.most_common(8)],
                                         [("Projetos", "c-exec", "v")])

        tiles = "".join([
            tile(me["leis_efeito"], "leis com efeito", comparacao(me["leis_efeito"], med("leis_efeito")), "tile-efeito"),
            tile(me["leis"], "leis aprovadas no total", f"de {plural(me['apresentados'], 'projeto apresentado', 'projetos apresentados')}"),
            tile(me["leis_sem_efeito"], "leis sem efeito prático", comparacao(me["leis_sem_efeito"], med("leis_sem_efeito")), "tile-sem"),
            tile(me["polemicos"], "projetos com alerta de polêmica", "", "tile-alerta" if me["polemicos"] else ""),
            tile(f"{me['taxa_aprovacao']}%" if me["taxa_aprovacao"] is not None else "—", "dos projetos concluídos viraram lei",
                 comparacao(me["taxa_aprovacao"], med("taxa_aprovacao"), sufixo="%")),
            tile(me["leis_coautoria"], "leis como coautor", ""),
        ])
        secoes.append(f"""<section class="mandato">
 <h2>{esc(leg['id'])} <span>{esc(cond)}{(' · ' + esc(m['partido'])) if m['partido'] else ''}</span></h2>
 {afast}
 <div class="tiles">{tiles}</div>
 {barra_producao(me, max(me['apresentados'], 1))}
 <div class="graficos duas">{graf_ano}{graf_tema}</div>
 <h3>Leis com efeito</h3>
 {f'<div class="cartoes">{"".join(cartao_lei(p, "../") for p in efeito)}</div>' if efeito else '<p class="vazio">Nenhuma lei com efeito nesta legislatura.</p>'}
 {f'<h3>Projetos com alerta</h3><ol class="projetos">{"".join(item_projeto(p, "../") for p in polem)}</ol>' if polem else ''}
 {f'<details class="bloco"><summary>Leis sem efeito prático ({len(sem)})</summary><ol class="projetos">{"".join(item_projeto(p, "../") for p in sem)}</ol></details>' if sem else ''}
 <details class="bloco"><summary>Todos os projetos como autor principal ({len(proj)})</summary>{'<ol class="projetos">' + ''.join(item_projeto(p, '../') for p in proj) + '</ol>' if proj else '<p class="vazio">Nenhum.</p>'}</details>
 <p><a href="../leis.html?autor={pessoa['slug']}&amp;coautor=1">Ver também as leis em que é coautor</a></p>
</section>""")
    tem_docs = bool(modelo.get("documentos"))
    corpo = f"""<section class="abertura ficha">
 <p><a href="../index.html">Todos os vereadores</a></p>
 <h1>{esc(pessoa['nome'])}</h1>
 <p class="siscam">Nome no SISCAM: {esc(pessoa['nome_siscam'])}</p>
</section>
{LEGENDA_BARRA}
{''.join(secoes)}{pagina_sessoes.secao_sessoes_vereador(modelo, pessoa)}{secao_atividade(modelo, pessoa) if tem_docs else ''}"""
    return pagina(f"{pessoa['nome']} · Radar dos Vereadores de Niterói", corpo, "", "../",
                  f"Leis e projetos de {pessoa['nome']} na Câmara de Niterói: quantas leis com efeito, quantas sem efeito prático e quais pautas polêmicas.",
                  dialogo=tem_docs, caminho=f"vereadores/{pessoa['slug']}.html")


def secao_atividade(modelo: dict, pessoa: dict) -> str:
    """Indicações, moções, requerimentos, PDLs e resoluções da pessoa: gráficos SVG com tabela e os 10 mais recentes."""
    ativ = pessoa.get("atividade") or {"documentos": [], "por_leg": {}}
    docs = ativ["documentos"]
    cab = ('<h2 id="t-atividade">Atividade <span>indicações, moções, requerimentos, PDLs e resoluções</span></h2>'
           '<p class="explica">Conta todo documento em que aparece como autor, inclusive os assinados em conjunto: nas indicações e '
           'moções, o SISCAM não separa autor de coautor. Estes documentos não entram nos números de projetos de lei acima. '
           '<a href="../metodologia.html#atividades">Como classificamos</a>.</p>')
    if not docs:
        return (f'\n<section class="mandato atividade" aria-labelledby="t-atividade">{cab}'
                '<p class="vazio">Nenhum documento encontrado com este nome no SISCAM.</p></section>')
    por_tipo = Counter(d["tipo"] for d in docs)
    tiles = "".join(tile(milhar(por_tipo[t]), (NOME_TIPO_DOC[t][0] if por_tipo[t] == 1 else NOME_TIPO_DOC[t][1]).lower())
                    for t in TIPOS_DOC)
    anos = sorted({d["ano"] for d in docs})
    cont = Counter((d["tipo"], d["ano"]) for d in docs)
    graf_tipos = G.colunas_empilhadas("Documentos por ano e tipo", "Pelo ano do número do documento.", [str(a) for a in anos], [
        (NOME_TIPO_DOC[t][1], f"c-t-{t}", [cont.get((t, a), 0) for a in anos]) for t in TIPOS_DOC if por_tipo[t]
    ], altura=200)
    legs = [leg["id"] for leg in reversed(modelo["legislaturas"]) if leg["id"] in ativ["por_leg"]]
    graf_perfil = "" if not legs else G.barras_horizontais(
        "Perfil de atuação por legislatura",
        "Zeladoria: indicações. Fiscalização: requerimentos de informação. Homenagem: moções de aplauso e pesar, títulos e honrarias. "
        "Legislação: PDLs e resoluções que não são homenagem.",
        [{"rotulo": leg, **ativ["por_leg"][leg]["perfil"]} for leg in legs],
        [(nome, f"c-p-{eixo}", eixo) for eixo, nome in NOME_EIXO.items()])
    info = [d for d in docs if d["tipo"] == "requerimento" and d["subcategoria"] == "informacao"]
    graf_info = ""
    if info:
        anos_i = sorted({d["ano"] for d in info})
        resp = Counter(d["ano"] for d in info if d["respondido"])
        sem_resp = Counter(d["ano"] for d in info if not d["respondido"])
        graf_info = G.colunas_empilhadas(
            "Requerimentos de informação: respondidos ou não",
            "Situação atual no SISCAM; pedidos recentes ainda podem ser respondidos.", [str(a) for a in anos_i], [
                ("Respondidos", "c-efeito", [resp.get(a, 0) for a in anos_i]),
                ("Sem resposta registrada", "c-sem-exito", [sem_resp.get(a, 0) for a in anos_i]),
            ], altura=200)
    metricas = metricas_atividade(modelo, pessoa)
    recentes = "".join(item_documento(d, "../") for d in docs[:10])
    return f"""
<section class="mandato atividade" aria-labelledby="t-atividade">
 {cab}
 <div class="tiles">{tiles}</div>
 <div class="graficos duas">{graf_tipos}{graf_perfil}</div>
 {graf_info}
 {metricas}
 <h3>Documentos mais recentes</h3>
 <ol class="projetos documentos">{recentes}</ol>
 <p><a href="../atividades.html?autor={esc(pessoa['slug'])}">{'Ver o documento' if len(docs) == 1 else f'Ver todos os {milhar(len(docs))} documentos'} de {esc(pessoa['nome'])} em Atividades</a></p>
</section>"""


def metricas_atividade(modelo: dict, pessoa: dict) -> str:
    """Homenagens (contagem e peso), requerimentos de informação e bairros das indicações da pessoa, em tabelas.

    Mesmas definições e funções de ruido.html e atividades.html, restritas aos documentos da pessoa.
    """
    s = pessoa["slug"]
    docs = (pessoa.get("atividade") or {}).get("documentos") or []
    ordem_legs = [leg["id"] for leg in reversed(modelo["legislaturas"])]
    por_leg: dict[str, list[dict]] = defaultdict(list)
    for d in docs:
        if d["legislatura"]:
            por_leg[d["legislatura"]].append(d)
    blocos = []

    hom = homenagens_do_autor(modelo, s)
    legs_h = [leg for leg in ordem_legs if leg in hom["por_leg"] and hom["por_leg"][leg]["producao"]]
    if legs_h:
        colunas = ["Homenagens", "Documentos", "Projetos de lei (autor principal)", "% da produção"]
        celulas = lambda r: [r["homenagens"], r["documentos"], r["projetos"], pct_txt(r["pct"])]
        tab_leg = tabela_resumo("Homenagens por legislatura", ["Legislatura", *colunas],
                                [[esc(leg), *celulas(hom["por_leg"][leg])] for leg in legs_h])
        tab_ano = tabela_resumo("Homenagens por ano", ["Ano", *colunas],
                                [[str(a), *celulas(r)] for a, r in sorted(hom["por_ano"].items(), reverse=True) if r["producao"]])
        recente = hom["por_leg"][legs_h[0]]
        tiles = (tile(milhar(recente["homenagens"]), f"homenagens na legislatura {legs_h[0]}", "moções de aplauso e pesar, títulos e honrarias", "tile-sem")
                 + tile(pct_txt(recente["pct"]), "da produção são homenagens",
                        f"de {plural(recente['producao'], 'documento ou projeto', 'documentos e projetos')}"))
        blocos.append(f"""<h3 id="homenagens">Homenagens</h3>
 <p class="explica">{esc(EXPLICA_HOMENAGENS)}</p>
 {nota_parciais(modelo)}
 <div class="tiles">{tiles}</div>
 {tab_leg}{tab_ano}""")

    info = [(leg, resumo_informacao(por_leg[leg])) for leg in ordem_legs if leg in por_leg]
    info = [(leg, r) for leg, r in info if r["pedidos"]]
    if info:
        tab = tabela_resumo("Requerimentos de informação por legislatura", ["Legislatura", *CAB_INFORMACAO],
                            [[esc(leg), *celulas_informacao(r)] for leg, r in info])
        orgaos = ranking_orgaos(docs)[:5]
        tab_org = tabela_resumo("Órgãos mais citados nos requerimentos de informação", ["Órgão", "Pedidos", "Respondidos", "Taxa de resposta"],
                                [[esc(o["orgao"]), o["pedidos"], o["respondidos"], pct_txt(o["taxa"])] for o in orgaos])
        blocos.append(f"""<h3 id="pedidos-informacao">Requerimentos de informação</h3>
 <p class="explica">{esc(EXPLICA_INFORMACAO)} {esc(EXPLICA_ORGAOS)}</p>
 {tab}{tab_org}""")

    bairros = [(leg, resumo_bairros(por_leg[leg])) for leg in ordem_legs if leg in por_leg]
    bairros = [(leg, r) for leg, r in bairros if r["indicacoes"]]
    if bairros:
        tab = tabela_resumo("Bairros das indicações por legislatura", ["Legislatura", *CAB_BAIRROS],
                            [[esc(leg), *celulas_bairros(r)] for leg, r in bairros], texto=TEXTO_BAIRROS)
        anos = sorted({d["ano"] for d in docs if d["tipo"] == "indicacao"})
        periodo = str(anos[0]) if len(anos) == 1 else f"{anos[0]}–{anos[-1]}"
        mapa = mapa_indicacoes(modelo, docs, f"Indicações de {pessoa['nome']} por bairro, {periodo}", limite_gzip=12 * 1024)
        blocos.append(f"""<h3 id="bairros">Bairros das indicações</h3>
 <p class="explica">{esc(EXPLICA_BAIRROS)}</p>
 {tab}{mapa}""")
    return "\n ".join(blocos)


# -------------------------------------------------------------------- metodologia
def gerar_metodologia(modelo: dict) -> str:
    from coletor.site import pagina_sessoes

    cls = modelo["meta"].get("classificacao") or {}
    defs_cat = "".join(f"<dt>{esc(NOME_CATEGORIA[k])}</dt><dd>{esc(v)}</dd>" for k, v in CATEGORIAS.items())
    defs_al = "".join(f"<dt>{esc(NOME_ALERTA[k])}</dt><dd>{esc(v)}</dd>" for k, v in ALERTAS.items())
    defs_sin = "".join(f"<dt>{esc(v)}</dt><dd>{esc(DESC_SINAL[k])}</dd>" for k, v in NOME_SINAL.items())
    defs_doc = "".join(f"<dt>{esc(v)}</dt><dd>{esc(DESC_CATEGORIA_DOC.get(k, ''))}</dd>" for k, v in NOME_CATEGORIA_DOC.items())
    corpo = f"""<section class="abertura texto">
<h1>Metodologia</h1>
<p>Este site mede a produção de cada vereador em projetos de lei, não seu trabalho inteiro. Indicações, moções, requerimentos, projetos de decreto legislativo e de resolução aparecem à parte, na página <a href="atividades.html">Atividades</a>, e não entram nos números de projetos e leis. A página <a href="sessoes.html">Sessões e votações</a> e a seção "Presença e votos" de cada vereador mostram os registros plenários, com as <a href="#sessoes">regras de contagem e limitações</a>. Comissões, fiscalização fora do SISCAM e atendimento à população não aparecem no site.</p>

<h2>De onde vêm os dados</h2>
<p>Toda semana, uma GitHub Action baixa do <a href="https://consultaniteroi.siscam.com.br/">SISCAM</a> os projetos de lei de cada ano desde 2021 e, para os novos ou com tramitação alterada, a autoria e a tramitação completa. Só a composição das legislaturas e a curadoria são editadas à mão, em arquivos públicos.</p>

<h2 id="novidades">Novidades da semana</h2>
<p>A página <a href="novidades.html">Novidades</a> e o <a href="{N.FEED}">feed RSS</a> não comparam uma coleta com a anterior nem guardam estado entre coletas: cada evento sai de uma data já registrada no SISCAM.</p>
<ul>
 <li><b>Projeto apresentado</b>: a data do documento.</li>
 <li><b>Virou lei</b>: a data da sanção ou promulgação, a mesma de Leis aprovadas, inclusive quando a lei sai de um substitutivo.</li>
 <li><b>Veto</b>: a data de resposta do passo da tramitação em que o SISCAM registra o veto do prefeito, no projeto ou num substitutivo. É total ou parcial pelo texto do passo ou, sem essa informação, pela situação do documento. Uma lei sancionada com veto parcial aparece como lei e, se a tramitação registrar o veto num passo próprio, também como veto.</li>
 <li><b>Veto derrubado</b>: a data do passo de plenário em que a tramitação registra a derrubada ou rejeição do veto, só quando a situação do documento ("veto rejeitado") ou a lei promulgada depois da derrubada confirmam. Votos "pela derrubada" num veto que acabou mantido não contam.</li>
</ul>
<p>As semanas vão de segunda a domingo. A mais recente é a que contém a última data encontrada nos dados, não a data de hoje; datas posteriores ao dia da última coleta, no horário de Brasília, são tratadas como erro de registro e ignoradas. A página mostra as últimas {N.SEMANAS} semanas, e o feed, os {N.MAX_ITENS_RSS} eventos mais recentes. Como a Câmara registra alguns passos com atraso, um evento pode surgir numa semana já passada, e a semana mais recente pode estar incompleta. Alertas de polêmica não entram nas novidades, porque nem a curadoria nem o cache da IA registram a data em que o alerta foi atribuído.</p>

<h2>Como os números são contados</h2>
<ul>
 <li><b>Autor principal</b> é quem o SISCAM registra como "Autor". As barras e os rankings contam só autoria principal, para que projetos assinados em bloco não inflem a produção de cada um.</li>
 <li><b>Virou lei</b>: sancionada, promulgada pela Câmara ou com veto derrubado. Número e data vêm da tramitação, incluindo as corrigendas publicadas.</li>
 <li><b>Substitutivos</b>: quando a Câmara aprova um substitutivo (um texto novo que substitui o do projeto) e é ele que vira lei, a lei conta para o projeto original e seus autores, mas o número, a data e o link da lei, marcados "via substitutivo", vêm da tramitação do substitutivo. Quando a lei vem de um substitutivo, os autores do substitutivo também recebem o crédito, como coautores se não assinaram o PL.</li>
 <li><b>Tempo até virar lei</b>: dias entre o protocolo e a sanção ou promulgação.</li>
 <li><b>Taxa de aprovação</b>: leis divididas por projetos já concluídos (viraram lei, foram arquivados, vetados, rejeitados ou retirados). Projetos em tramitação ficam de fora.</li>
 <li><b>Legislatura</b>: o projeto conta na legislatura em que foi apresentado. Suplentes em exercício e afastamentos para o Executivo aparecem identificados.</li>
</ul>

<h2 id="impacto">Impacto e efeito</h2>
<p>Cada projeto recebe um impacto de 0 a 3, estimado pela IA a partir da ementa:</p>
<dl class="defs">
 <dt>3 · Alto</dt><dd>Afeta grande parte da população, cria política ou serviço amplo, ou mexe em orçamento ou tributo relevante.</dd>
 <dt>2 · Médio</dt><dd>Muda regra ou serviço para um grupo relevante ou um setor da cidade.</dd>
 <dt>1 · Baixo</dt><dd>Efeito pontual, restrito a um local, grupo pequeno ou procedimento menor.</dd>
 <dt>0 · Sem efeito prático</dt><dd>Homenagem, data, nome, título, utilidade pública, lei que só autoriza o Executivo ou repete norma existente.</dd>
</dl>
<p>Duas regras determinísticas se sobrepõem à IA: projetos simbólicos sempre recebem impacto 0, e leis autorizativas recebem no máximo 1. <b>Lei com efeito</b> é a que virou lei com impacto 2 ou 3. Enquanto a IA não avaliou um projeto, conta como lei com efeito a que não é simbólica nem autorizativa.</p>
<p>O resumo em linguagem simples e o público afetado também são gerados pela IA e servem de apoio à leitura; o texto oficial é sempre a ementa, mostrada logo abaixo.</p>

<h2>Categoria</h2>
<p>Ementas que batem com padrões de homenagem, nome de logradouro, data comemorativa (incluindo alterações da Lei 3.474/2020, o calendário oficial), título ou patrimônio imaterial são classificadas como simbólicas por regra; as demais, pela IA.</p>
<dl class="defs">{defs_cat}</dl>

<h2 id="sinais">Sinais objetivos</h2>
<dl class="defs">{defs_sin}</dl>

<h2 id="alertas">Alertas de polêmica</h2>
<p>Os alertas valem igualmente para qualquer autor, partido ou espectro político. Têm duas origens:</p>
<ul>
 <li><b>Curadoria</b>: revisado à mão, com fonte pública, em <a href="{REPO}/blob/main/config/curadoria.json"><code>config/curadoria.json</code></a>. Prevalece sobre a IA.</li>
 <li><b>IA</b>: o modelo <code>{esc(cls.get('modelo', '—'))}</code>, via OpenCode Go, lê só a ementa. Só aparece alerta com confiança de pelo menos {int(CONFIANCA_MINIMA * 100)}%. O prompt completo está em <a href="{REPO}/blob/main/coletor/classificar.py"><code>coletor/classificar.py</code></a> (versão {esc(cls.get('versao_prompt', '—'))}).</li>
</ul>
<dl class="defs">{defs_al}</dl>
<p>"Com alerta de polêmica" soma restrição de direitos, pauta de costumes e apelo populista. Risco de inconstitucionalidade aparece à parte, porque é comum em projetos municipais de todos os campos.</p>

<h2 id="atividades">Indicações, moções, requerimentos, PDLs e resoluções</h2>
<p>Além dos projetos de lei, a coleta semanal traz do SISCAM outros cinco tipos de documento desde 2021. Eles aparecem na página <a href="atividades.html">Atividades</a>, na seção "Atividade" de cada vereador e nas colunas do placar da página inicial, sempre separados dos projetos de lei: não entram em leis aprovadas, impacto, taxa de aprovação nem projetos repetidos.</p>
<dl class="defs">
 <dt>Indicação</dt><dd>Pedido ao Executivo de um serviço ou obra, como iluminação, asfalto, poda ou limpeza.</dd>
 <dt>Moção</dt><dd>Manifestação da Câmara: aplauso, pesar, repúdio, apoio e outras.</dd>
 <dt>Requerimento</dt><dd>Pedido formal, como de informações ao Executivo ou de cópia de processos e contratos.</dd>
 <dt>Projeto de decreto legislativo (PDL)</dt><dd>Ato da Câmara sem sanção do prefeito, como a concessão de títulos e honrarias ou a sustação de atos.</dd>
 <dt>Projeto de resolução</dt><dd>Norma interna da Câmara, como mudanças no Regimento, na estrutura administrativa ou em honrarias.</dd>
</dl>
<h3>Classificação por regras</h3>
<p>Cada documento recebe categoria e subcategoria por regras fixas sobre a ementa, sem IA, em <a href="{REPO}/blob/main/coletor/regras_documentos.py"><code>coletor/regras_documentos.py</code></a>. O mesmo texto recebe sempre a mesma classificação, e as regras valem igualmente para qualquer autor, partido ou espectro político.</p>
<dl class="defs">{defs_doc}</dl>
<p>O perfil de atuação de cada vereador soma, por legislatura, documentos de zeladoria, fiscalização, homenagem e legislação. Todo autor listado conta, inclusive em documentos assinados em conjunto.</p>
<h3>O que vem de cada tipo</h3>
<ul>
 <li>A listagem do SISCAM traz número, data, ementa, situação, autores e o último passo da tramitação. <b>Indicações e moções são coletadas só pela listagem</b>: a autoria aparece na ordem do SISCAM, sem separar autor de coautor, e por isso o site não destaca autor principal nesses documentos.</li>
 <li><b>Requerimentos, PDLs e resoluções</b>, e documentos de qualquer tipo com mais de um autor, têm também a página de detalhe consultada, com o papel de cada autor e a tramitação completa. Enquanto o detalhe não é baixado, o documento aparece como "detalhe ainda não coletado".</li>
 <li><b>Respondido</b> vale só para requerimentos: basta a situação "Respondido", a data de resposta vinda do detalhe ou o último passo da listagem com objetivo ou resultado "Respondido" ("Não respondido" não conta). A data de resposta (<code>respondido_em</code>) é a do passo "Respondido" da tramitação: é quando a Câmara registrou a resposta, não necessariamente o dia em que o Executivo respondeu. Os dias até a resposta também são contados até esse passo.</li>
 <li><b>Publicado</b> vale para documentos com situação "Publicado"; nos PDLs e resoluções, o número e a data da publicação vêm da tramitação.</li>
 <li><b>Bairro</b> é procurado só nas indicações, comparando a ementa com os 52 bairros oficiais de Niterói, sem diferenciar acentos nem maiúsculas, e vale a última menção. Sub-bairros, comunidades e nomes de rua não são reconhecidos, e um nome de bairro usado em outro sentido pode gerar um bairro errado; indicações sem bairro reconhecido ficam sem bairro.</li>
</ul>
<p>Cada item das listas tem o botão "Ver no SISCAM", que abre a página oficial do documento dentro do site, e o link "abrir no SISCAM", que a abre numa nova aba.</p>
<h3 id="metricas-documentos">Homenagens, pedidos de informação e bairros</h3>
<p>Três métricas resumem os documentos, sempre com as mesmas regras para qualquer autor, partido ou espectro político. Aparecem em {'<a href="ruido.html#homenagens">Sem efeito e polêmicas</a>' if modelo.get('documentos') else 'Sem efeito e polêmicas'}, em <a href="atividades.html">Atividades</a> e na seção "Atividade" de cada vereador. Por vereador, contam todos os documentos em que ele aparece como autor, inclusive os assinados em conjunto.</p>
<ul>
 <li><b>Homenagens</b>: documentos da categoria homenagem, a mesma do perfil de atuação. Contam moções de aplauso (inclusive congratulação, louvor e agradecimento) e de pesar, títulos de cidadão e outras honrarias, como medalhas, diplomas e comendas, em PDLs e resoluções; aplauso e congratulação são uma única classe. Moções de repúdio e de apoio e PDLs que sustam uma homenagem não contam. O <b>peso</b> aparece de duas formas: o número de homenagens e a porcentagem da produção do mesmo período (legislatura ou ano), em que a produção soma todos os documentos em que o vereador aparece como autor e os projetos de lei em que é autor principal. Na Câmara, a produção soma documentos e projetos de lei de qualquer autor. Só entram anos de coleta completa, em que os cinco tipos de documento têm ao menos um registro; anos com coleta parcial ficam fora da conta e são citados numa nota.</li>
 <li><b>Requerimentos de informação</b>: por vereador e por órgão, contam os pedidos, os respondidos, a taxa de resposta (respondidos entre os pedidos não retirados pelo autor), a mediana dos dias até o passo "Respondido", com a sua base, e os que aguardam resposta (sem resposta registrada e sem arquivamento; os arquivados, rejeitados ou prejudicados sem resposta aparecem como encerrados). Como <code>respondido_em</code> é a data do passo "Respondido" da tramitação, a mediana mede o tempo até a Câmara registrar a resposta, não necessariamente até o Executivo responder. Os dias só existem para os respondidos cuja página de detalhe, com a tramitação completa, já foi baixada; por isso a mediana usa só esses respondidos com data, e o número deles aparece ao lado. {esc(pendentes_txt(resumo_informacao(modelo.get('documentos') or [])))} Pedidos recentes ainda podem ser respondidos.</li>
 <li><b>Órgão citado</b>: o primeiro órgão específico citado na ementa do requerimento (secretaria, fundação, empresa municipal como NitTrans, Clin ou ION, ou concessionária), mesmo como intermediário ("por intermédio da NitTrans") ou cópia ("ao Prefeito, com cópia à Secretaria de Educação"), com o nome normalizado; sem órgão na ementa, vale o assunto da listagem. Órgão estadual só conta quando é o destinatário ("ao Governo do Estado", "à Secretaria de Estado de Saúde"); citado em outro papel ("baixa junto ao Detran-RJ"), vale o nível municipal. Sem órgão específico, o pedido fica como "Prefeito ou Poder Executivo"; sem nenhum, "Não identificado". Siglas ambíguas não são reconhecidas. Os nomes das secretarias mudam entre gestões e aparecem como citados, sem juntar nomes diferentes: "Secretaria de Mobilidade Urbana" e "Secretaria de Urbanismo e Mobilidade" ficam separadas, porque os dados não dizem se são o mesmo órgão. A tramitação não serve para isso: os pedidos seguem para a Secretaria Municipal de Governo, que os repassa.</li>
 <li><b>Bairros das indicações</b>: para cada vereador, os cinco bairros mais citados, o número de bairros distintos e a concentração (parte das indicações com bairro que vai para o bairro mais citado; com empate no topo, os empatados aparecem juntos); para a cidade, as indicações em cada um dos 52 bairros oficiais, inclusive os sem nenhuma, os menos citados e a parte das indicações sem bairro identificado. Não há dado de população no site, por isso não há taxa por habitante.</li>
</ul>

<h3 id="mapa-bairros">Mapa das indicações por bairro</h3>
<p>O mapa usa valores absolutos, sem ajuste por população: não mede necessidade, atendimento nem qualidade. O bairro é inferido da ementa pelas mesmas regras das tabelas; a porcentagem sem bairro identificado aparece junto ao mapa, e essas indicações ficam fora dele. Os resumos cobrem todos os anos coletados e não mudam com os filtros da lista. Os bairros com indicações são divididos em até cinco faixas por quantis: os cortes buscam grupos de tamanhos semelhantes, sem separar bairros empatados, e há menos faixas quando há poucos valores distintos. Os limites são arredondados para números simples apenas no intervalo entre valores observados, sem alterar os grupos ou criar faixas vazias. Zero tem uma faixa própria hachurada, só quando há bairros sem indicações. A legenda mostra os limites e o número de bairros em cada faixa; a tabela alternativa inclui os 52 bairros, inclusive zeros, com os valores exatos. As faixas dependem dos dados: cores de mapas com limites diferentes não são diretamente comparáveis.</p>
<p>Limites: © contribuidores do OpenStreetMap, sob <a href="https://www.openstreetmap.org/copyright">ODbL 1.0</a>, obtidos pelo Overpass das relações administrativas dos bairros (nível 10) dentro do município de Niterói (<a href="https://www.openstreetmap.org/relation/2220789">relação 2220789</a>). A data da base OSM aparece junto a cada mapa; as tags de origem dos limites indicam IBGE. A geometria é projetada localmente, simplificada e arredondada para exibição: não é um mapa cadastral nem uma confirmação municipal dos limites. Nas páginas dos vereadores, o mapa só pode aparecer se SVG, legenda, tabela e atribuição somarem no máximo 12 KiB gzip. Com a geometria atual (base OSM de 23/10/2026), esse orçamento é excedido: o mapa por vereador não é exibido, e ficam as tabelas por legislatura. O <a href="atividades.html#bairros">mapa geral está em Atividades</a>. Sem o arquivo de geometria, a geração mantém os gráficos e tabelas existentes, sem mapa.</p>

{pagina_sessoes.metodologia_sessoes(modelo)}

<h2>Limitações</h2>
<ul>
 <li>Contar documentos não mede qualidade nem resultado: uma indicação atendida e outra ignorada contam igual.</li>
 <li>A ementa é um resumo. A IA não lê o texto integral nem o contexto político, e pode errar nos dois sentidos.</li>
 <li>Impacto estimado não é avaliação de resultado: uma lei de impacto alto pode nunca ser cumprida.</li>
 <li>A detecção de projetos repetidos compara palavras da ementa e pode juntar projetos parecidos mas diferentes.</li>
 <li>Erros de registro no SISCAM passam para cá.</li>
</ul>

<h2>Contestar ou corrigir</h2>
<p>Projetos com alerta ou sinal têm um link "contestar", que abre uma issue no GitHub. Correções na composição das legislaturas e na curadoria podem ser enviadas como pull request.</p>
</section>"""
    return pagina("Metodologia · Radar dos Vereadores de Niterói", corpo, "metodologia.html", caminho="metodologia.html")


def redirecionar(destino: str) -> str:
    return f'<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0; url={destino}"><link rel="canonical" href="{destino}"><a href="{destino}">Esta página mudou de endereço.</a>'
