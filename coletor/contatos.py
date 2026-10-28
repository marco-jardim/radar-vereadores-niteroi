"""Propõe contatos públicos a partir do cache bruto; só aplica após revisão humana.

python -m coletor.contatos --candidatos --cache DIR [--min-docs 3] [--saida ARQ]
python -m coletor.contatos --aplicar ARQ

A proposta contém valores ainda não aprovados: mantenha-a fora do Git. Remova as
entradas não confirmadas antes de usar --aplicar. Recorrência não prova que um
contato pertence ao mandato; confira o timbre/assinatura na fonte indicada.
Somente biblioteca padrão, sem rede.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from coletor import mascara, validar
from coletor.arquivos import gravar_atomico

RAIZ = Path(__file__).resolve().parent.parent
URL_DOCUMENTO = "https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento={}"
_RE_ARQUIVO = re.compile(r"[a-zA-Z_][a-zA-Z0-9_-]*-([1-9][0-9]*)\.txt")
_RE_ORGAO = re.compile(
    r"\b(?:gabinete do prefeito|prefeitura|secretaria|camara|ouvidoria|procuradoria|"
    r"tribunal|ministerio|defensoria|sic|serpro|anatel|tesouro|pgfn|pge|detran|"
    r"autarquia|fundacao municipal|receita federal|inss|ministerio publico)\b"
)


def _ler(caminho: Path) -> dict:
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    if not isinstance(dados, dict):
        raise ValueError(f"{caminho}: esperado objeto JSON")
    return dados


def _texto(dados: dict) -> str:
    """Formato de configuração: ordem preservada, UTF-8, NFC, LF e quebra final."""
    return unicodedata.normalize("NFC", json.dumps(dados, ensure_ascii=False, indent=1) + "\n")


def _nome(nome: str) -> str:
    return " ".join(mascara._dobrar(nome).split())


def _documentos(raiz: Path, perfis: dict) -> dict[int, dict]:
    """Índice por id SISCAM; só associa nomes conhecidos, sem inferir homônimos."""
    cfg = _ler(raiz / "config/vereadores.json")
    nomes = set(perfis["vereadores"])
    nomes.update(e["siscam"] for leg in cfg.get("legislaturas", []) for e in leg.get("eleitos", []))
    variantes: dict[str, set[str]] = defaultdict(set)
    for nome in sorted(nomes):
        variantes[_nome(nome)].add(nome)
        variantes[_nome(nome.split(" - ", 1)[0])].add(nome)
    indice = {v: next(iter(ns)) for v, ns in variantes.items() if len(ns) == 1}
    nao_vereador = [_nome(n) for n in cfg.get("nao_vereador", [])]
    caminhos = sorted((raiz / "data/proposicoes").glob("*.json"))
    caminhos += sorted((raiz / "data/documentos").glob("*/*.json"))
    documentos = {}
    for caminho in caminhos:
        registros = json.loads(caminho.read_text(encoding="utf-8"))
        if not isinstance(registros, list):
            raise ValueError(f"{caminho}: esperada lista de documentos")
        for registro in registros:
            autores = registro.get("autoria") or registro.get("autores") or []
            # O detalhe explicita o principal; sem papel, a ordem da listagem é a evidência disponível.
            principal = next((a for a in autores if (a.get("papel") or "").lower().startswith("autor")),
                             autores[0] if autores else None)
            nome = _nome(principal.get("nome", "")) if principal else ""
            vereador = bool(principal) and (principal.get("origem") or "").lower() in ("", "vereador", "vereadora")
            vereador = vereador and not any(n in nome for n in nao_vereador)
            documentos[int(registro["id"])] = {
                "siscam": indice.get(nome) if vereador else None,
                "data": registro.get("data") or f"{registro.get('ano', 0):04d}-01-01",
            }
    return documentos


def _encontrar(texto: str):
    """E-mails completos e telefones com rótulo, DDD ou hífen; reusa proteções da máscara."""
    emails = list(mascara._RE_EMAIL.finditer(texto))
    for m in emails:
        yield "email", m.group().lower(), m.start()
    protegidos = mascara._protegidos(texto, mascara._PROTECOES_GERAIS)
    zonas = mascara._zonas(texto, urls=True)
    trechos_email = mascara._Intervalos(m.span() for m in emails)
    for m in mascara._a_partir(mascara._RE_CANDIDATO_TELEFONE, mascara._RE_TELEFONE, texto):
        if (protegidos.sobrepoe(*m.span()) or zonas.sobrepoe(*m.span())
                or trechos_email.sobrepoe(*m.span())):
            continue
        ddd = m.group("ddd1") or m.group("ddd2")
        if ddd is not None and int(ddd) not in mascara.DDDS:
            continue
        rotulado = bool(mascara._RE_ROTULO_TELEFONE.search(mascara._antes(texto, m.start())))
        if not (rotulado or ddd or m.group("pais") or m.group("sep") == "-"):
            continue
        # Como na máscara: dígitos colados (sem espaço, parênteses, + ou hífen) só contam com rótulo.
        if not rotulado and not re.search(r"[\s().+-]", m.group()):
            continue
        if mascara._numero_de_ato(texto, m.start()):
            # "Ouvidoria: 2620-1234" pode ser contato; "Ouvidoria nº ..." não.
            antes = mascara._dobrar(texto[max(0, m.start() - 80):m.start()])
            if not _RE_ORGAO.search(antes) or re.search(r"\bn[º°o]?[.:]?\s*$", antes):
                continue
        valor = mascara.telefone_canonico(m.group())
        if valor:
            yield "telefone", valor, m.start()


def candidatos(raiz: Path, cache: Path, min_docs: int = 3) -> dict:
    """Uma ocorrência por documento, inclusive os sem autor conhecido no denominador."""
    if min_docs < 1:
        raise ValueError("min-docs deve ser positivo")
    if not cache.is_dir():
        raise ValueError(f"cache inexistente: {cache}")
    documentos = _documentos(raiz, _ler(raiz / "config/perfis.json"))
    ocorrencias: dict[tuple[str, str], set[int]] = defaultdict(set)
    orgaos: dict[tuple[str, str], dict[int, str]] = defaultdict(dict)
    lidos = set()
    for arquivo in sorted(cache.glob("*.txt")):
        nome = _RE_ARQUIVO.fullmatch(arquivo.name)
        if nome is None:
            continue
        id_ = int(nome[1])
        lidos.add(id_)
        texto = arquivo.read_text(encoding="utf-8", errors="replace")
        for tipo, valor, inicio in _encontrar(texto):
            chave = (tipo, valor)
            ocorrencias[chave].add(id_)
            if tipo == "telefone":
                contexto = " ".join(texto[max(0, inicio - 80):inicio].split())
                marcas = list(_RE_ORGAO.finditer(mascara._dobrar(contexto)))
                if marcas:
                    # Só o trecho anterior, sem o telefone nem texto posterior potencialmente pessoal.
                    orgaos[chave][id_] = contexto[marcas[-1].start():].strip(" :;,-–")

    def recente(ids: set[int]) -> int:
        return max(ids, key=lambda id_: (documentos.get(id_, {}).get("data", ""), id_))

    def evidencia(ids: set[int], todos: set[int], por_autor: Counter) -> dict:
        return {"documentos": len(ids), "total_documentos": len(todos),
                "proporcao": len(ids) / len(todos), "por_autor": dict(sorted(por_autor.items())),
                "documentos_ids": sorted(ids)}

    proposta = {"versao": 1, "min_docs": min_docs, "documentos_lidos": len(lidos),
                "perfis": [], "contatos_institucionais": []}
    for (tipo, valor), ids in sorted(ocorrencias.items()):
        por_autor = Counter(documentos.get(id_, {}).get("siscam") for id_ in ids)
        desconhecidos = por_autor.pop(None, 0)
        contagens = Counter(por_autor)
        if desconhecidos:
            contagens["(sem autor associado)"] = desconhecidos
        institucionais = set(orgaos.get((tipo, valor), {}))
        if len(institucionais) >= min_docs:
            id_ = recente(institucionais)
            proposta["contatos_institucionais"].append({
                "tipo": tipo, "valor": valor, "descricao": orgaos[(tipo, valor)][id_],
                "fonte": URL_DOCUMENTO.format(id_),
                "evidencias": evidencia(institucionais, ids, contagens),
            })
        for autor, quantidade in sorted(por_autor.items()):
            if quantidade < min_docs or quantidade * 5 < len(ids) * 3:
                continue
            do_autor = {id_ for id_ in ids if documentos.get(id_, {}).get("siscam") == autor}
            proposta["perfis"].append({
                "siscam": autor, "tipo": tipo, "valor": valor,
                "fonte": URL_DOCUMENTO.format(recente(do_autor)),
                "evidencias": evidencia(do_autor, ids, contagens),
            })
    return proposta


def _mesclar(destino: list, contato: dict) -> bool:
    """Não altera metadados de um contato já aprovado; aplicação repetida é idempotente."""
    if any((c.get("tipo"), c.get("valor")) == (contato["tipo"], contato["valor"]) for c in destino):
        return False
    destino.append(contato)
    return True


def aplicar(raiz: Path, arquivo: Path) -> dict:
    """Mescla a proposta revisada, valida antes/depois e restaura em caso de falha."""
    proposta = _ler(arquivo)
    if proposta.get("versao") != 1:
        raise ValueError("versão da proposta inválida")
    perfis = _ler(raiz / "config/perfis.json")
    backend = _ler(raiz / "config/backend.json")
    cfg = _ler(raiz / "config/vereadores.json")
    contagens = {"perfis": 0, "contatos_institucionais": 0}
    for grupo in contagens:
        entradas = proposta.get(grupo, [])
        if not isinstance(entradas, list):
            raise ValueError(f"{grupo}: esperada lista")
        for entrada in entradas:
            permitidos = {"tipo", "valor", "fonte", "descricao", "evidencias"}
            if grupo == "perfis":
                permitidos.add("siscam")
            if (not isinstance(entrada, dict) or set(entrada) - permitidos
                    or not {"tipo", "valor", "fonte"} <= set(entrada)):
                raise ValueError(f"{grupo}: entrada de contato inválida")
            contato = {k: v for k, v in entrada.items() if k in {"tipo", "valor", "fonte", "descricao"}}
            if grupo == "perfis":
                nome = entrada.get("siscam")
                if not isinstance(nome, str) or nome not in perfis["vereadores"]:
                    raise ValueError("perfil SISCAM inexistente na proposta")
                destino = perfis["vereadores"][nome].setdefault("contatos", [])
            else:
                destino = backend["contatos_institucionais"]
            if not isinstance(destino, list):
                raise ValueError(f"{grupo}: destino deveria ser lista")
            contagens[grupo] += _mesclar(destino, contato)

    novos = {"perfis": _texto(perfis), "backend": _texto(backend)}
    # Validação completa dos dois arquivos em isolamento antes de tocar a configuração real.
    with tempfile.TemporaryDirectory(prefix=".contatos-", dir=raiz) as tmp:
        provisoria = Path(tmp)
        for nome, texto in novos.items():
            gravar_atomico(provisoria / "config" / f"{nome}.json", texto)
        problemas = validar.validar_perfis(provisoria / "config/perfis.json", cfg)
        problemas += validar.validar_backend(provisoria)
        if problemas:
            raise ValueError("proposta não aplicada:\n" + "\n".join(problemas))
    anteriores = {nome: (raiz / "config" / f"{nome}.json").read_bytes().decode("utf-8") for nome in novos}
    alterados = []
    try:
        for nome, texto in novos.items():
            if texto != anteriores[nome]:
                gravar_atomico(raiz / "config" / f"{nome}.json", texto)
                alterados.append(nome)
        problemas = validar.validar_perfis(raiz / "config/perfis.json", cfg) + validar.validar_backend(raiz)
        if problemas:
            raise ValueError("validação após aplicação:\n" + "\n".join(problemas))
    except BaseException:
        for nome in alterados:
            gravar_atomico(raiz / "config" / f"{nome}.json", anteriores[nome])
        raise
    return contagens


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    modo = parser.add_mutually_exclusive_group(required=True)
    modo.add_argument("--candidatos", action="store_true")
    modo.add_argument("--aplicar", type=Path, metavar="ARQ")
    parser.add_argument("--cache", type=Path, metavar="DIR")
    parser.add_argument("--min-docs", type=int, default=3)
    parser.add_argument("--saida", type=Path, metavar="ARQ")
    args = parser.parse_args(argv)
    if args.candidatos and args.cache is None:
        parser.error("--candidatos exige --cache")
    if args.min_docs < 1:
        parser.error("--min-docs deve ser positivo")
    if args.aplicar and (args.cache is not None or args.saida is not None or args.min_docs != 3):
        parser.error("--aplicar não combina com opções de geração de candidatos")
    try:
        if args.candidatos:
            saida = args.saida or RAIZ / ".qa/contatos_propostos.json"
            if any(saida.resolve().is_relative_to((RAIZ / p).resolve()) for p in ("config", "data")):
                raise ValueError("a proposta não pode sobrescrever config/ nem data/")
            gravar_atomico(saida, _texto(candidatos(RAIZ, args.cache, args.min_docs)))
            print(f"Proposta para revisão humana: {saida}; configuração não alterada.")
        else:
            print(json.dumps(aplicar(RAIZ, args.aplicar), ensure_ascii=False))
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"::error::{e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
