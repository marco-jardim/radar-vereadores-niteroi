"""Gráficos em SVG gerados no build. Cores vêm de classes CSS (c-*), validadas para claro e escuro.

Cada gráfico traz: legenda (≥ 2 séries), tooltip por marca (data-tip, lido pelo app.js)
e uma tabela com os mesmos números em <details>, para leitores de tela e para quem prefere números.
"""
from __future__ import annotations

import hashlib
import html
import math
from collections import Counter

from coletor.regras_documentos import BAIRROS_POR_REGIAO

LARGURA = 720


def esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


def _passo(maximo: float) -> float:
    if maximo <= 0:
        return 1
    bruto = maximo / 4
    mag = 10 ** math.floor(math.log10(bruto))
    for m in (1, 2, 2.5, 5, 10):
        if bruto <= m * mag:
            return m * mag
    return 10 * mag


def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float) and not v.is_integer():
        return f"{v:.1f}".replace(".", ",")
    return f"{int(v):,}".replace(",", ".")


def _topo_arredondado(x: float, y: float, w: float, h: float, r: float = 4) -> str:
    r = min(r, w / 2, h)
    return (f"M{x:.1f},{y + h:.1f} V{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
            f"H{x + w - r:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} V{y + h:.1f} Z")


def _ponta_direita(x: float, y: float, w: float, h: float, r: float = 4) -> str:
    r = min(r, h / 2, w)
    return (f"M{x:.1f},{y:.1f} H{x + w - r:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} "
            f"V{y + h - r:.1f} Q{x + w:.1f},{y + h:.1f} {x + w - r:.1f},{y + h:.1f} H{x:.1f} Z")


def legenda(series: list[tuple[str, str]]) -> str:
    if len(series) < 2:
        return ""
    itens = "".join(f'<li><i class="sw {esc(c)}"></i>{esc(n)}</li>' for n, c in series)
    return f'<ul class="leg-graf">{itens}</ul>'


def tabela(cabecalho: list[str], linhas: list[list], titulo: str) -> str:
    th = "".join(f"<th scope=\"col\">{esc(c)}</th>" for c in cabecalho)
    trs = "".join("<tr>" + "".join(f"<td>{esc(_fmt(c) if isinstance(c, (int, float)) else c)}</td>" for c in l) + "</tr>" for l in linhas)
    return (f'<details class="tabela-graf"><summary>Ver os números em tabela</summary>'
            f'<div class="tabela-rolavel" role="region" tabindex="0" aria-label="{esc(titulo)}">'
            f'<table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table></div></details>')


def _corte_limpo(inferior: int, superior: int) -> int:
    """Múltiplo de 1, 2 ou 5 × potência de dez, no vão entre dois valores distintos.

    Prefere o passo mais largo e o múltiplo mais próximo do meio do vão. Se não
    houver espaço para arredondar, usa o próprio inteiro, sem mudar os grupos.
    """
    potencia = 10 ** (len(str(superior)) - 1)
    while potencia:
        for fator in (5, 2, 1):
            passo = fator * potencia
            primeiro, ultimo = (inferior + passo - 1) // passo, superior // passo
            if primeiro <= ultimo:
                meio = (inferior + superior + passo) // (2 * passo)
                return min(ultimo, max(primeiro, meio)) * passo
        potencia //= 10
    return inferior


def faixas_quantis(valores: list[int], classes: int = 5) -> list[tuple[int, int, int]]:
    """(mínimo, máximo, bairros) por faixa; zero separado e até cinco quantis positivos.

    Busca os cortes cumulativos mais próximos dos quantis, sem dividir empates e
    reservando ao menos um valor distinto para cada classe restante. Arredondar
    apenas no vão entre observações preserva a classificação e evita faixas vazias.
    """
    if classes < 1 or any(v < 0 for v in valores):
        raise ValueError("classes deve ser positivo e valores não podem ser negativos")
    contagens = Counter(valores)
    faixas = [(0, 0, contagens[0])] if contagens[0] else []
    distintos = sorted(v for v in contagens if v > 0)
    if not distintos:
        return faixas
    acumuladas, total = [], 0
    for valor in distintos:
        total += contagens[valor]
        acumuladas.append(total)
    quantidade = min(classes, 5, len(distintos))
    anterior, inicio, base = -1, distintos[0], 0
    for i in range(1, quantidade):
        # Desempate pelo menor índice; contas inteiras evitam diferenças de ponto flutuante.
        limite = len(distintos) - quantidade + i
        corte = min(range(anterior + 1, limite), key=lambda j: (abs(quantidade * acumuladas[j] - i * total), j))
        fim = _corte_limpo(distintos[corte], distintos[corte + 1] - 1)
        faixas.append((inicio, fim, acumuladas[corte] - base))
        anterior, inicio, base = corte, fim + 1, acumuladas[corte]
    faixas.append((inicio, distintos[-1], total - base))
    return faixas


def mapa_coropletico(valores: dict[str, int], geo: dict, titulo: str, subtitulo: str = "") -> str:
    """Mapa estático de valores absolutos; quantis dos positivos e zeros hachurados.

    A tabela alternativa inclui todos os 52 bairros, usando as mesmas contagens do mapa.
    Nenhum tooltip ou legenda depende de JavaScript.
    """
    identificador = "mapa-" + hashlib.sha1(titulo.encode("utf-8")).hexdigest()[:10]
    numeros = [valores.get(b, 0) for bairros in BAIRROS_POR_REGIAO.values() for b in bairros]
    faixas = faixas_quantis(numeros)
    positivas = sum(inicio > 0 for inicio, _, _ in faixas)
    classes, itens_legenda, ordem = [], [], 0
    for inicio, fim, quantidade in faixas:
        # Com poucas faixas, ainda usa a amplitude da paleta; uma única faixa é neutra.
        cor = 0 if inicio == 0 else 3 if positivas == 1 else 1 + round(4 * ordem / (positivas - 1))
        ordem += inicio > 0
        classes.append((inicio, fim, cor))
        rotulo = "0 (hachurado)" if cor == 0 else _fmt(inicio) if inicio == fim else f"{_fmt(inicio)}–{_fmt(fim)}"
        bairros_txt = f"{quantidade} {'bairro' if quantidade == 1 else 'bairros'}"
        itens_legenda.append(f'<li><i class="sw mapa-{cor}" aria-hidden="true"></i>'
                            f'<span>{esc(rotulo)} indicações · {esc(bairros_txt)}</span></li>')
    leg = ('<ul class="leg-graf leg-mapa" role="list" aria-label="Faixas de indicações e número de bairros">'
           + "".join(itens_legenda) + '</ul>')
    viewbox = " ".join(str(int(v)) for v in geo["viewbox"])
    partes = [f'<svg class="mapa-bairros" viewBox="{esc(viewbox)}" xmlns="http://www.w3.org/2000/svg" '
              f'aria-labelledby="{identificador}-titulo" aria-describedby="{identificador}-desc">',
              f'<title id="{identificador}-titulo">{esc(titulo)}</title>',
              f'<desc id="{identificador}-desc">Indicações nos 52 bairros de Niterói, em valores absolutos, sem ajuste por população. '
              'Até cinco quantis dos valores positivos, sem separar empates. Zero é hachurado. '
              'A legenda mostra os limites das faixas e quantos bairros há em cada uma; '
              'a tabela abaixo traz os nomes e valores exatos de todos os bairros.</desc>',
              f'<defs><pattern id="{identificador}-zero" width="8" height="8" patternUnits="userSpaceOnUse">'
              '<rect class="mapa-fundo-zero" width="8" height="8"/>'
              '<line class="mapa-hachura" x1="0" y1="8" x2="8" y2="0"/></pattern></defs>']
    linhas = []
    for regiao, bairros in BAIRROS_POR_REGIAO.items():
        for bairro in bairros:
            valor = valores.get(bairro, 0)
            faixa = next(cor for inicio, fim, cor in classes if inicio <= valor <= fim)
            geometria = geo["bairros"][bairro]
            preenchimento = f' fill="url(#{identificador}-zero)"' if faixa == 0 else ""
            partes.append(f'<path class="mapa-bairro mapa-{faixa}" d="{esc(geometria["path"])}" '
                          f'fill-rule="evenodd"{preenchimento}><title>{esc(bairro)}: {_fmt(valor)} indicações</title></path>')
            linhas.append([bairro, regiao, valor])
    partes.append("</svg>")
    atribuicao = (f'<p class="nota fonte-mapa">Limites simplificados: {esc(geo["atribuicao"])} · '
                  '<a href="https://www.openstreetmap.org/copyright">ODbL 1.0</a> · '
                  f'base OSM: {esc(geo["osm_base"])}. Não é um mapa cadastral.</p>')
    return figura(titulo, subtitulo, "".join(partes), leg,
                  tabela(["Bairro", "Região", "Indicações"], linhas, titulo) + atribuicao, titulo)


def figura(titulo: str, subtitulo: str, corpo_svg: str, leg: str, tab: str, rotulo: str) -> str:
    # role="img" torna os filhos apresentacionais: com links (pontos e rótulos com página própria), o SVG vira um
    # grupo rotulado, para que eles continuem expostos a leitores de tela. As marcas nunca recebem tabindex.
    papel = "group" if "<a " in corpo_svg else "img"
    return f"""<figure class="grafico">
 <figcaption><h3>{esc(titulo)}</h3>{f'<p>{esc(subtitulo)}</p>' if subtitulo else ''}</figcaption>
 {leg}
 <div class="svg-box">{corpo_svg.replace('<svg ', f'<svg role="{papel}" aria-label="{esc(rotulo)}" ', 1)}</div>
 {tab}
</figure>"""


def colunas_empilhadas(titulo: str, subtitulo: str, rotulos_x: list[str], series: list[tuple[str, str, list[float]]],
                       altura: int = 260, unidade: str = "") -> str:
    m_esq, m_dir, m_top, m_base = 40, 8, 14, 28
    w_plot = LARGURA - m_esq - m_dir
    h_plot = altura - m_top - m_base
    totais = [sum(s[2][i] for s in series) for i in range(len(rotulos_x))]
    passo = _passo(max(totais + [1]))
    topo = passo * math.ceil(max(totais + [1]) / passo)
    banda = w_plot / max(len(rotulos_x), 1)
    larg = min(24 if len(rotulos_x) > 12 else 40, banda * 0.6)
    y = lambda v: m_top + h_plot - h_plot * v / topo
    partes = [f'<svg viewBox="0 0 {LARGURA} {altura}" xmlns="http://www.w3.org/2000/svg">']
    v = 0
    while v <= topo + 1e-9:
        partes.append(f'<line class="grade" x1="{m_esq}" x2="{LARGURA - m_dir}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>'
                      f'<text class="eixo" x="{m_esq - 6}" y="{y(v) + 4:.1f}" text-anchor="end">{_fmt(v)}</text>')
        v += passo
    for i, rot in enumerate(rotulos_x):
        cx = m_esq + banda * i + banda / 2
        base = 0.0
        ativos = [s for s in series if s[2][i] > 0]
        for k, (nome, cor, vals) in enumerate(series):
            val = vals[i]
            if val <= 0:
                continue
            y0, y1 = y(base), y(base + val)
            h = y0 - y1 - (2 if base > 0 else 0)  # 2px de respiro entre segmentos
            if h <= 0:
                base += val
                continue
            ultimo = (nome == ativos[-1][0])
            tip = f"{rot} · {nome}: {_fmt(val)}{unidade} de {_fmt(totais[i])}"
            if ultimo:
                partes.append(f'<path class="marca {cor}" d="{_topo_arredondado(cx - larg / 2, y1, larg, h)}" data-tip="{esc(tip)}"/>')
            else:
                partes.append(f'<rect class="marca {cor}" x="{cx - larg / 2:.1f}" y="{y1:.1f}" width="{larg:.1f}" height="{h:.1f}" data-tip="{esc(tip)}"/>')
            base += val
        partes.append(f'<text class="eixo" x="{cx:.1f}" y="{altura - 8}" text-anchor="middle">{esc(rot)}</text>')
        partes.append(f'<text class="valor" x="{cx:.1f}" y="{y(totais[i]) - 5:.1f}" text-anchor="middle">{_fmt(totais[i])}</text>')
    partes.append(f'<line class="base" x1="{m_esq}" x2="{LARGURA - m_dir}" y1="{y(0):.1f}" y2="{y(0):.1f}"/></svg>')
    leg = legenda([(n, c) for n, c, _ in series])
    tab = tabela(["", *[n for n, _, _ in series], "Total"], [[r, *[s[2][i] for s in series], totais[i]] for i, r in enumerate(rotulos_x)], titulo)
    return figura(titulo, subtitulo, "".join(partes), leg, tab, titulo)


def linhas(titulo: str, subtitulo: str, rotulos_x: list[str], series: list[tuple[str, str, list[float | None]]],
           altura: int = 240, unidade: str = "") -> str:
    m_esq, m_dir, m_top, m_base = 44, 160, 14, 28
    w_plot = LARGURA - m_esq - m_dir
    h_plot = altura - m_top - m_base
    vals = [v for _, _, vs in series for v in vs if v is not None]
    passo = _passo(max(vals + [1]))
    topo = passo * math.ceil(max(vals + [1]) / passo)
    x = lambda i: m_esq + (w_plot * i / max(len(rotulos_x) - 1, 1))
    y = lambda v: m_top + h_plot - h_plot * v / topo
    partes = [f'<svg viewBox="0 0 {LARGURA} {altura}" xmlns="http://www.w3.org/2000/svg">']
    v = 0
    while v <= topo + 1e-9:
        partes.append(f'<line class="grade" x1="{m_esq}" x2="{LARGURA - m_dir}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>'
                      f'<text class="eixo" x="{m_esq - 6}" y="{y(v) + 4:.1f}" text-anchor="end">{_fmt(v)}</text>')
        v += passo
    for i, rot in enumerate(rotulos_x):
        partes.append(f'<text class="eixo" x="{x(i):.1f}" y="{altura - 8}" text-anchor="middle">{esc(rot)}</text>')
    fim_y = []
    for nome, cor, vs in series:
        pts = [(x(i), y(v), v, rotulos_x[i]) for i, v in enumerate(vs) if v is not None]
        if not pts:
            continue
        d = " ".join(("M" if k == 0 else "L") + f"{px:.1f},{py:.1f}" for k, (px, py, _, _) in enumerate(pts))
        partes.append(f'<path class="linha {cor}" d="{d}"/>')
        for px, py, v, r in pts:
            partes.append(f'<circle class="ponto {cor}" cx="{px:.1f}" cy="{py:.1f}" r="4" data-tip="{esc(f"{nome} em {r}: {_fmt(v)}{unidade}")}"/>')
        fim_y.append([pts[-1][1], pts[-1][0], nome, pts[-1][2]])
    fim_y.sort()
    for k in range(1, len(fim_y)):  # rótulos finais sem sobreposição
        if fim_y[k][0] - fim_y[k - 1][0] < 14:
            fim_y[k][0] = fim_y[k - 1][0] + 14
    for ly, lx, nome, v in fim_y:
        partes.append(f'<text class="rotulo-fim" x="{lx + 8:.1f}" y="{ly + 4:.1f}">{esc(nome)} · {_fmt(v)}{esc(unidade)}</text>')
    partes.append(f'<line class="base" x1="{m_esq}" x2="{LARGURA - m_dir}" y1="{y(0):.1f}" y2="{y(0):.1f}"/></svg>')
    tab = tabela(["", *[n for n, _, _ in series]], [[r, *[s[2][i] for s in series]] for i, r in enumerate(rotulos_x)], titulo)
    return figura(titulo, subtitulo, "".join(partes), legenda([(n, c) for n, c, _ in series]), tab, titulo)


def barras_horizontais(titulo: str, subtitulo: str, itens: list[dict], series: list[tuple[str, str, str]],
                       unidade: str = "", max_itens: int = 30) -> str:
    """itens: [{'rotulo', 'link'?, 'nota'?, <chave>: valor, ...}]; series: [(nome, classe_cor, chave)] empilhadas."""
    itens = itens[:max_itens]
    m_esq, m_dir, linha_h, barra_h = 170, 56, 26, 14
    altura = linha_h * len(itens) + 8
    totais = [sum(it.get(k, 0) or 0 for _, _, k in series) for it in itens]
    topo = max(totais + [1])
    w_plot = LARGURA - m_esq - m_dir
    partes = [f'<svg viewBox="0 0 {LARGURA} {altura}" xmlns="http://www.w3.org/2000/svg">']
    for i, it in enumerate(itens):
        yy = 4 + i * linha_h
        rot = esc(it["rotulo"])
        rot_svg = f'<a href="{esc(it["link"])}"><text class="eixo rot" x="{m_esq - 8}" y="{yy + barra_h - 2}" text-anchor="end">{rot}</text></a>' if it.get("link") else \
            f'<text class="eixo rot" x="{m_esq - 8}" y="{yy + barra_h - 2}" text-anchor="end">{rot}</text>'
        partes.append(rot_svg)
        x0 = m_esq
        ativos = [s for s in series if (it.get(s[2]) or 0) > 0]
        for nome, cor, k in series:
            val = it.get(k) or 0
            if val <= 0:
                continue
            w = w_plot * val / topo - (2 if ativos[-1][2] != k else 0)
            tip = f"{it['rotulo']} · {nome}: {_fmt(val)}{unidade}"
            if ativos[-1][2] == k:
                partes.append(f'<path class="marca {cor}" d="{_ponta_direita(x0, yy, max(w, 1), barra_h)}" data-tip="{esc(tip)}"/>')
            else:
                partes.append(f'<rect class="marca {cor}" x="{x0:.1f}" y="{yy}" width="{max(w, 1):.1f}" height="{barra_h}" data-tip="{esc(tip)}"/>')
            x0 += w_plot * val / topo
        partes.append(f'<text class="valor" x="{x0 + 6:.1f}" y="{yy + barra_h - 2}">{_fmt(totais[i])}{esc(unidade)}{esc(it.get("nota", ""))}</text>')
    partes.append("</svg>")
    tab = tabela(["", *[n for n, _, _ in series]] + (["Total"] if len(series) > 1 else []),
                 [[it["rotulo"], *[it.get(k) or 0 for _, _, k in series]] + ([totais[i]] if len(series) > 1 else []) for i, it in enumerate(itens)], titulo)
    return figura(titulo, subtitulo, "".join(partes), legenda([(n, c) for n, c, _ in series]), tab, titulo)


def dispersao(titulo: str, subtitulo: str, pontos: list[dict], rot_x: str, rot_y: str, rotular: int = 8, altura: int = 340) -> str:
    """pontos: [{'x', 'y', 'rotulo', 'cor', 'link'?}]. Rotula só os `rotular` pontos mais distantes da origem."""
    m_esq, m_dir, m_top, m_base = 44, 20, 14, 40
    w_plot, h_plot = LARGURA - m_esq - m_dir, altura - m_top - m_base
    px_, py_ = _passo(max([p["x"] for p in pontos] + [1])), _passo(max([p["y"] for p in pontos] + [1]))
    tx = px_ * math.ceil(max([p["x"] for p in pontos] + [1]) / px_)
    ty = py_ * math.ceil(max([p["y"] for p in pontos] + [1]) / py_)
    X = lambda v: m_esq + w_plot * v / tx
    Y = lambda v: m_top + h_plot - h_plot * v / ty
    partes = [f'<svg viewBox="0 0 {LARGURA} {altura}" xmlns="http://www.w3.org/2000/svg">']
    v = 0
    while v <= ty + 1e-9:
        partes.append(f'<line class="grade" x1="{m_esq}" x2="{LARGURA - m_dir}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/><text class="eixo" x="{m_esq - 6}" y="{Y(v) + 4:.1f}" text-anchor="end">{_fmt(v)}</text>')
        v += py_
    v = 0
    while v <= tx + 1e-9:
        partes.append(f'<text class="eixo" x="{X(v):.1f}" y="{m_top + h_plot + 16}" text-anchor="middle">{_fmt(v)}</text>')
        v += px_
    partes.append(f'<text class="eixo titulo-eixo" x="{m_esq + w_plot / 2:.1f}" y="{altura - 4}" text-anchor="middle">{esc(rot_x)}</text>')
    partes.append(f'<text class="eixo titulo-eixo" x="{m_esq}" y="{m_top - 2}" text-anchor="start">{esc(rot_y)}</text>')
    destaque = {id(p) for p in sorted(pontos, key=lambda p: -(p["y"] / ty + p["x"] / tx))[:rotular]}
    rotulos = []
    for p in pontos:
        cx, cy = X(p["x"]), Y(p["y"])
        circ = f'<circle class="ponto {p.get("cor", "c-efeito")}" cx="{cx:.1f}" cy="{cy:.1f}" r="5" data-tip="{esc(p["rotulo"])}: {_fmt(p["x"])} projetos, {_fmt(p["y"])} leis com efeito"/>'
        partes.append(f'<a href="{esc(p["link"])}" aria-label="{esc(p["rotulo"])}: {_fmt(p["x"])} projetos, {_fmt(p["y"])} leis com efeito">{circ}</a>' if p.get("link") else circ)
        if id(p) in destaque:
            rotulos.append([cy - 8, cx, p["rotulo"]])
    colocados = []  # evita colisão em 2D: largura estimada pelo número de caracteres
    for ly, lx, r in sorted(rotulos):
        larg = 7.2 * len(r) + 8
        anchor_end = lx > LARGURA - 120 - larg / 2
        x0 = lx - larg - 8 if anchor_end else lx + 8
        y = ly
        for _ in range(12):
            if all(not (x0 < cx1 and x0 + larg > cx0 and abs(y - cy) < 14) for cx0, cx1, cy in colocados):
                break
            y += 14
        colocados.append((x0, x0 + larg, y))
        partes.append(f'<text class="rotulo-ponto" x="{x0 if not anchor_end else lx - 8:.1f}" y="{y + 4:.1f}" text-anchor="{'end' if anchor_end else 'start'}">{esc(r)}</text>')
    rotulos = []
    for ly, lx, r in rotulos:
        anchor = "end" if lx > LARGURA - 120 else "start"
        partes.append(f'<text class="rotulo-ponto" x="{lx + (-8 if anchor == "end" else 8):.1f}" y="{ly + 4:.1f}" text-anchor="{anchor}">{esc(r)}</text>')
    partes.append(f'<line class="base" x1="{m_esq}" x2="{LARGURA - m_dir}" y1="{Y(0):.1f}" y2="{Y(0):.1f}"/></svg>')
    tab = tabela(["Vereador", rot_x, rot_y], [[p["rotulo"], p["x"], p["y"]] for p in sorted(pontos, key=lambda p: -p["y"])], titulo)
    return figura(titulo, subtitulo, "".join(partes), "", tab, titulo)
