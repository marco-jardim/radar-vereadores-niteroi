"""Leitura offline da seção de arquivos dos documentos do SISCAM."""
from __future__ import annotations

import datetime as dt
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

RE_LEGENDA = re.compile(r"<legend[^>]*>\s*\[\s*Arquivos\s*\]\s*</legend>", re.I)


class _Arquivos(HTMLParser):
    """Restringe a leitura à grade dentro de trArquivos, inclusive seus trs aninhados."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.secao = False
        self.profundidade = 0
        self.grade = False
        self.tabelas = 0
        self.textos: list[str] = []
        self.linhas: list[dict] = []
        self.linha: dict | None = None
        self.celulas: list[list[str]] = []
        self.na_celula = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        atributos = dict(attrs)
        if tag == "tr":
            if atributos.get("id") == "trArquivos":
                self.secao = True
                self.profundidade = 1
            elif self.profundidade:
                self.profundidade += 1
        if not self.profundidade:
            return
        if tag == "table":
            if atributos.get("id") == "arquivos_gvListagem":
                self.grade = True
                self.tabelas = 1
            elif self.tabelas:
                self.tabelas += 1
        if not self.tabelas:
            return
        if tag == "tr" and any(c.startswith("grid-row-") for c in (atributos.get("class") or "").split()):
            self.linha = {"id": None, "icone": ""}
            self.celulas = []
        if self.linha is None:
            return
        if tag == "td":
            self.celulas.append([])
            self.na_celula = True
        if tag == "a":
            m = re.search(r"(?:^|/)Download\.aspx\?id=(\d+)(?:&|$)", atributos.get("href") or "", re.I)
            if m and self.linha["id"] is None:
                self.linha["id"] = int(m.group(1))
        if tag == "img" and len(self.celulas) == 1:
            self.linha["icone"] = Path(urlsplit(atributos.get("src") or "").path).stem
        if tag == "br" and self.na_celula:
            self.celulas[-1].append(" ")

    def handle_data(self, data: str) -> None:
        if self.profundidade:
            self.textos.append(data)
        if self.linha is not None and self.na_celula:
            self.celulas[-1].append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self.profundidade:
            return
        if tag == "td":
            self.na_celula = False
        if tag == "tr":
            if self.linha is not None:
                if self.linha["id"] is not None:
                    textos = [" ".join("".join(c).split()) for c in self.celulas]
                    textos += [""] * max(0, 4 - len(textos))
                    data = None
                    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", textos[3])
                    if m:
                        try:
                            data = dt.date(int(m[3]), int(m[2]), int(m[1])).isoformat()
                        except ValueError:
                            pass
                    self.linhas.append({**self.linha, "descricao": textos[1], "versao": textos[2], "data": data})
                self.linha = None
            self.profundidade -= 1
        if tag == "table" and self.tabelas:
            self.tabelas -= 1


def extrair_arquivos(html: str) -> list[dict]:
    """Extrai os arquivos na ordem da página.

    Página sem a seção (nem `tr#trArquivos` nem a legenda "[ Arquivos ]") não tem arquivos: [].
    Legenda sem `tr#trArquivos`, ou seção sem a grade e sem "Nenhum Registro", é layout alterado
    (ValueError): o chamador mantém o detalhe anterior.
    """
    parser = _Arquivos()
    parser.feed(html)
    parser.close()
    if not parser.secao and RE_LEGENDA.search(html):
        raise ValueError("layout alterado: legenda de arquivos sem a linha trArquivos")
    if parser.secao and not parser.grade and not re.search(r"Nenhum\s+Registro", " ".join(parser.textos), re.I):
        raise ValueError("layout alterado: tabela de arquivos ausente")
    vistos = set()
    arquivos = []
    for item in parser.linhas:
        if item["id"] not in vistos:
            vistos.add(item["id"])
            arquivos.append(item)
    return arquivos


def preservar_arquivos(anterior: dict | None, novo: dict) -> None:
    """Não apaga uma lista conhecida quando o SISCAM passa a devolver uma lista vazia."""
    if anterior and anterior.get("arquivos") and novo.get("arquivos") == []:
        novo["arquivos"] = anterior["arquivos"]
        print(f"::warning::documento {anterior.get('id')}: arquivos vazios; mantidos da coleta anterior", file=sys.stderr)


def preencher_arquivos_cache(registro: dict, pasta: Path) -> bool:
    """Preenche só arquivos a partir de <id>.html; devolve se o HTML estava disponível."""
    caminho = pasta / f"{registro['id']}.html"
    if not caminho.is_file():
        return False
    novo = {"arquivos": extrair_arquivos(caminho.read_bytes().decode("utf-8", "ignore"))}
    preservar_arquivos(registro, novo)
    registro.update(novo)
    return True
