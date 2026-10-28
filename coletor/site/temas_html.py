"""Apresentação dos temas de IA; não participa do resumo determinístico."""
from __future__ import annotations

from html import escape

from coletor import mascara
from coletor.site.modelo import URL_DETALHE
from coletor.temas import RAIZ, documentos_da_pessoa, temas_validados, termos_proibidos


def bloco_temas(modelo: dict, pessoa: dict, cache: dict, prefixo: str = "../") -> str:
    """HTML separado, ou vazio se não há temas válidos.

    modelo/pessoa: saída de montar_modelo e um registro de modelo['pessoas'];
    cache: mapa lido por coletor.temas.carregar_cache (sem rede); prefixo: caminho
    relativo até a raiz do site. Recalcula contagens/exemplos e revalida rótulos
    contra os documentos da pessoa; não basta um sinalizador 'validado' no cache.
    """
    if not cache:
        return ""
    from coletor.site.paginas import link_fonte

    blocos = []
    liberados = mascara.liberados(RAIZ)
    proibidos = termos_proibidos(modelo)
    for leg in sorted(modelo.get("legislaturas") or [], key=lambda l: l["inicio"], reverse=True):
        registro = cache.get(f'pessoa:{pessoa["slug"]}:{leg["id"]}') or {}
        if not registro:
            continue
        docs = documentos_da_pessoa(modelo, pessoa, leg["id"], liberados)
        temas, _ = temas_validados(docs, registro, cache, proibidos)
        if not temas:
            continue
        linhas = []
        for t in temas:
            # URL construída do id local: nenhum href gerado pela IA é aceito.
            links = ", ".join(link_fonte(URL_DETALHE.format(id=d["id"]),
                                        f'{str(d["tipo"]).upper()} {d["numero"]}')
                              for d in t["exemplos"])
            linhas.append(f'<li>{escape(t["rotulo"])}: {t["total"]} documentos (ex.: {links})</li>')
        blocos.append(f'<h3>Legislatura {escape(leg["id"])}</h3><ul>' + "".join(linhas) + '</ul>')
    if not blocos:
        return ""
    return ('<section class="temas-ia" aria-labelledby="t-temas-ia">'
            '<h2 id="t-temas-ia">Temas (agrupados por IA)</h2>'
            '<p class="explica"><span class="tag">IA</span> Agrupar não é avaliar. '
            f'<a href="{escape(prefixo, quote=True)}metodologia.html#temas">Como é feito</a>.</p>'
            + "".join(blocos) + '</section>')
