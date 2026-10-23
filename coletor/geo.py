"""Converte relações de bairros do Overpass (out geom) em geometria SVG local.

Uso: python -m coletor.geo --entrada bairros-overpass.json
Não acessa a rede. A entrada deve conter os 52 bairros administrativos de Niterói.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
from pathlib import Path

from coletor.arquivos import salvar_mapa, texto_mapa
from coletor.regras_documentos import BAIRROS_NITEROI, VARIANTES_BAIRROS, normalizar

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "data" / "geo" / "bairros.json"
LARGURA = 1000
MARGEM = 8
TOLERANCIA = 25.0  # metros na projeção local; pode aumentar para caber no orçamento
AREA_MINIMA = 400.0  # m²; ilhotas/recortes menores não são legíveis nesta escala
LIMITE_BRUTO = 60 * 1024
Ponto = tuple[float, float]


# ------------------------------------------------------------------ montagem
def nome_oficial(nome: str) -> str | None:
    """Nome completo, sem distinguir acentos, caixa ou pontuação; não busca na ementa."""
    chave = normalizar(nome)
    for bairro in BAIRROS_NITEROI:
        if chave in {normalizar(bairro), *(normalizar(v) for v in VARIANTES_BAIRROS.get(bairro, ()))}:
            return bairro
    return None


def _canonico(pontos: list[Ponto]) -> list[Ponto]:
    """Direção e, nos anéis, origem fixas, independentemente da ordem do Overpass."""
    if pontos[0] != pontos[-1]:
        return list(min(tuple(pontos), tuple(reversed(pontos))))
    abertos = pontos[:-1]
    inicio = min(range(len(abertos)), key=lambda i: abertos[i])
    direto = abertos[inicio:] + abertos[:inicio]
    inverso = [direto[0], *reversed(direto[1:])]
    anel = min(direto, inverso)
    return [*anel, anel[0]]


def montar_aneis(ways: list[list[Ponto]], rotulo: str = "geometria", *, permitir_degenerado: bool = False) -> list[list[Ponto]]:
    """Encadeia pontas exatas, invertendo ways quando preciso; nunca fecha uma lacuna à força."""
    restantes = sorted((_canonico(w) for w in ways), key=tuple)
    aneis = []
    while restantes:
        anel = restantes.pop(0)
        while anel[-1] != anel[0]:
            candidatos = [i for i, w in enumerate(restantes) if anel[-1] in (w[0], w[-1])]
            if len(candidatos) != 1:
                mensagem = f"{rotulo}: anel não fechou ou tem bifurcação na ponta {anel[-1]}"
                print(f"::warning::{mensagem}", file=sys.stderr)
                raise ValueError(mensagem)
            trecho = restantes.pop(candidatos[0])
            if trecho[0] != anel[-1]:
                trecho.reverse()
            anel.extend(trecho[1:])
        if not permitir_degenerado and len(set(anel[:-1])) < 3:
            raise ValueError(f"{rotulo}: anel degenerado")
        aneis.append(_canonico(anel))
    return sorted(aneis, key=tuple)


# -------------------------------------------------------------- simplificação
def _distancia2(p: Ponto, a: Ponto, b: Ponto) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy))) if dx or dy else 0.0
    return (p[0] - a[0] - t * dx) ** 2 + (p[1] - a[1] - t * dy) ** 2


def douglas_peucker(pontos: list[Ponto], tolerancia: float) -> list[Ponto]:
    """Versão iterativa, com desempate pela primeira posição e pontas preservadas."""
    if len(pontos) <= 2:
        return pontos[:]
    manter = {0, len(pontos) - 1}
    pilha = [(0, len(pontos) - 1)]
    while pilha:
        inicio, fim = pilha.pop()
        if fim - inicio <= 1:
            continue
        i = max(range(inicio + 1, fim), key=lambda k: _distancia2(pontos[k], pontos[inicio], pontos[fim]))
        if _distancia2(pontos[i], pontos[inicio], pontos[fim]) > tolerancia ** 2:
            manter.add(i)
            pilha.extend(((inicio, i), (i, fim)))
    return [pontos[i] for i in sorted(manter)]


def _simplificar_way(pontos: list[Ponto], tolerancia: float) -> list[Ponto]:
    pontos = _canonico(pontos)
    if pontos[0] != pontos[-1]:
        # Preserve também o mínimo: ele identifica o mesmo anel antes/depois do DP.
        minimo = min(range(len(pontos)), key=lambda i: pontos[i])
        return douglas_peucker(pontos[:minimo + 1], tolerancia)[:-1] + douglas_peucker(pontos[minimo:], tolerancia)
    # Um anel não pode ser tratado como segmento de comprimento zero. Duas metades
    # com extremos distantes preservam seu contorno e a mesma escolha nas duas direções.
    meio = max(range(1, len(pontos) - 1), key=lambda i: _distancia2(pontos[i], pontos[0], pontos[0]))
    return douglas_peucker(pontos[:meio + 1], tolerancia)[:-1] + douglas_peucker(pontos[meio:], tolerancia)


def _area(anel: list[Ponto]) -> float:
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(anel, anel[1:])) / 2


def _cruzamento(a: Ponto, b: Ponto, c: Ponto, d: Ponto) -> bool:
    def lado(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    return lado(a, b, c) * lado(a, b, d) < 0 and lado(c, d, a) * lado(c, d, b) < 0


def _anel_valido(anel: list[Ponto]) -> bool:
    if len(set(anel[:-1])) < 3 or abs(_area(anel)) < 1:
        return False
    segmentos = list(zip(anel, anel[1:]))
    return not any(_cruzamento(a, b, c, d) for i, (a, b) in enumerate(segmentos)
                   for c, d in segmentos[i + 2:] if d != a)


# ------------------------------------------------------------------ conversão
def converter_overpass(dados: dict, *, bairros_esperados: tuple[str, ...] = BAIRROS_NITEROI,
                       tolerancia: float = TOLERANCIA) -> dict:
    """Projeta em metros, simplifica cada way compartilhado uma vez e monta paths evenodd.

    Equiretangular com cos(latitude média dos extremos): a extensão municipal é pequena,
    dispensando Mercator e seu fator de escala. Não serve para uso cadastral. As pontas
    de todos os ways são preservadas para não abrir frestas entre bairros vizinhos.
    """
    if not math.isfinite(tolerancia) or tolerancia < 0:
        raise ValueError("tolerância deve ser finita e não negativa")
    if not isinstance(dados, dict) or not isinstance(dados.get("elements"), list) or not isinstance(dados.get("osm3s"), dict):
        raise ValueError("esperado objeto Overpass com elements e osm3s")
    base = dados.get("osm3s", {}).get("timestamp_osm_base")
    if not isinstance(base, str) or not base.strip():
        raise ValueError("resposta sem osm3s.timestamp_osm_base")
    relacoes, ways = {}, {}
    for rel in dados.get("elements", []):
        tags = rel.get("tags") or {}
        if rel.get("type") != "relation" or tags.get("boundary") != "administrative" or tags.get("admin_level") != "10":
            continue
        nome = nome_oficial(tags.get("name", ""))
        if nome not in bairros_esperados:
            raise ValueError(f"geometria sem bairro oficial esperado: {tags.get('name')!r} (relação {rel.get('id')})")
        if nome in relacoes:
            raise ValueError(f"relações duplicadas para {nome}")
        if type(rel.get("id")) is not int or rel["id"] <= 0:
            raise ValueError(f"{nome}: id de relação inválido")
        papeis = {"outer": [], "inner": []}
        for membro in rel.get("members", []):
            if membro.get("type") != "way":
                continue  # label/admin_centre não são contornos
            papel = membro.get("role") or "outer"
            if papel not in papeis:
                raise ValueError(f"{nome}: papel de way desconhecido: {papel!r}")
            pontos = []
            for p in membro.get("geometry") or []:
                lon, lat = float(p["lon"]), float(p["lat"])
                if not math.isfinite(lon) or not math.isfinite(lat) or not (-180 <= lon <= 180 and -90 <= lat <= 90):
                    raise ValueError(f"{nome}: coordenada inválida")
                if not pontos or pontos[-1] != (lon, lat):
                    pontos.append((lon, lat))
            if len(pontos) < 2:
                raise ValueError(f"{nome}: way {membro.get('ref')} sem geometria suficiente (use out geom)")
            pontos = _canonico(pontos)
            ref = membro["ref"]
            if type(ref) is not int or ref <= 0:
                raise ValueError(f"{nome}: id de way inválido")
            if ref in ways and ways[ref] != pontos:
                raise ValueError(f"way {ref} com geometrias divergentes")
            ways[ref] = pontos
            if ref in papeis[papel]:
                raise ValueError(f"{nome}: way {ref} repetido")
            papeis[papel].append(ref)
        if not papeis["outer"]:
            raise ValueError(f"{nome}: sem contorno outer")
        relacoes[nome] = (rel["id"], papeis)
    faltam = sorted(set(bairros_esperados) - relacoes.keys())
    if faltam:
        raise ValueError(f"bairros oficiais sem geometria: {', '.join(faltam)}")
    if not ways:
        raise ValueError("nenhum contorno encontrado")

    pontos = [p for w in ways.values() for p in w]
    lon0, lat0 = min(p[0] for p in pontos), min(p[1] for p in pontos)
    lat_media = (lat0 + max(p[1] for p in pontos)) / 2
    fator_x = math.cos(math.radians(lat_media))
    raio = 6371008.8
    projetados = {ref: [(raio * math.radians(lon - lon0) * fator_x, raio * math.radians(lat - lat0))
                        for lon, lat in w] for ref, w in ways.items()}
    xmax = max(p[0] for w in projetados.values() for p in w)
    ymax = max(p[1] for w in projetados.values() for p in w)
    if xmax <= 0 or ymax <= 0:
        raise ValueError("extensão geográfica degenerada")
    escala = (LARGURA - 2 * MARGEM) / xmax
    altura = math.ceil(ymax * escala) + 2 * MARGEM

    def tela(anel):
        saida = []
        for x, y in anel:
            p = (round(MARGEM + x * escala), round(MARGEM + (ymax - y) * escala))
            if not saida or saida[-1] != p:
                saida.append(p)
        if saida and saida[-1] != saida[0]:
            saida.append(saida[0])
        return saida

    originais = {nome: {papel: montar_aneis([projetados[r] for r in refs], f"{nome}/{papel}")
                        for papel, refs in papeis.items()} for nome, (_, papeis) in relacoes.items()}
    # Se a simplificação colapsar ou cruzar um anel relevante, reduza a tolerância
    # globalmente: a mesma fronteira continua idêntica nos dois bairros.
    usada = tolerancia
    for tentativa in range(9):
        simples = {ref: _simplificar_way(w, usada) for ref, w in projetados.items()}
        bairros, invalidos = {}, []
        for nome in sorted(relacoes):
            osm_id, papeis = relacoes[nome]
            contornos, externos = [], []
            for papel, refs in papeis.items():
                aneis = montar_aneis([simples[r] for r in refs], f"{nome}/{papel}", permitir_degenerado=True)
                # A ordem dos anéis pode mudar; a origem original identifica cada um.
                for original in originais[nome][papel]:
                    if abs(_area(original)) < AREA_MINIMA or abs(_area(tela(original))) < 1:
                        continue
                    candidatos = [a for a in aneis if a[0] == original[0]]
                    anel = tela(candidatos[0]) if len(candidatos) == 1 else []
                    if not _anel_valido(anel):
                        invalidos.append(nome)
                        continue
                    contornos.append(anel)
                    if papel == "outer":
                        externos.append(anel)
            if not externos:
                invalidos.append(nome)
                continue
            maior = max(externos, key=lambda a: abs(_area(a)))
            centro = [round(sum(p[i] for p in maior[:-1]) / (len(maior) - 1)) for i in (0, 1)]
            path = "".join("M" + " ".join(f"{x},{y}" for x, y in a[:-1]) + "Z" for a in contornos)
            bairros[nome] = {"path": path, "osm_id": osm_id, "centro": centro}
        if not invalidos:
            return {"fonte": "https://www.openstreetmap.org/relation/2220789", "licenca": "ODbL 1.0",
                    "atribuicao": "© contribuidores do OpenStreetMap", "osm_base": base,
                    "viewbox": [0, 0, LARGURA, altura], "bairros": bairros,
                    "projecao": "equiretangular local", "tolerancia_m": usada, "area_minima_m2": AREA_MINIMA}
        usada = 0.0 if tentativa == 7 else usada / 2
    raise ValueError(f"anéis degenerados ou cruzados após projeção/arredondamento: {', '.join(sorted(set(invalidos)))}")


# -------------------------------------------------------------------- execução
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--entrada", type=Path, required=True, help="JSON local do Overpass com out geom")
    ap.add_argument("--tolerancia", type=float, default=TOLERANCIA, help="tolerância inicial em metros (padrão: 25)")
    args = ap.parse_args()
    try:
        dados = json.loads(args.entrada.read_text(encoding="utf-8"))
        tolerancia = args.tolerancia
        while True:
            geo = converter_overpass(dados, tolerancia=tolerancia)
            bruto = texto_mapa(geo).encode("utf-8")
            if len(bruto) <= LIMITE_BRUTO:
                break
            if tolerancia >= 100 or tolerancia == 0:
                raise ValueError("geometria excede 60 KiB mesmo após simplificação; revise a entrada/tolerância")
            tolerancia = min(100, tolerancia * 1.5)
        salvar_mapa(DESTINO, geo)
    except (OSError, ValueError, TypeError, KeyError) as e:
        ap.exit(1, f"geometria não gravada: {e}\n")
    print(f"data/geo/bairros.json: {len(geo['bairros'])} bairros; tolerância {geo['tolerancia_m']:g} m; "
          f"{len(bruto)} bytes brutos; {len(gzip.compress(bruto, mtime=0))} bytes gzip; base OSM {geo['osm_base']}")


if __name__ == "__main__":
    main()
