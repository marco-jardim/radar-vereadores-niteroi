"""Termos da metodologia e definições usadas em cada página.

Não chame ``termo`` dentro de <summary>, <label>, <th>, <button> ou <a>:
o resultado é um link e não deve aninhar controles nem alterar seus rótulos.
"""
from __future__ import annotations

from html import escape
import unicodedata


TERMOS: dict[str, tuple[str, str]] = {
    "autorizativa": (
        "Autorizativa",
        "Lei que só autoriza o Executivo a fazer algo que ele já pode fazer, sem obrigá-lo.",
    ),
    "sem-efeito": (
        "Sem efeito prático",
        "No site, reúne homenagens, datas, nomes e leis autorizativas. "
        "É uma classificação da proposta, não uma avaliação de resultado comprovado.",
    ),
    "simbolica": (
        "Simbólica",
        "Categoria de projetos como homenagens, nomes de logradouro, datas comemorativas, "
        "títulos e patrimônio imaterial. No site, recebe impacto 0 por regra.",
    ),
    "substitutivo": (
        "Substitutivo",
        "Texto novo que substitui o do projeto. Quando ele vira lei, o site conta a lei "
        "para o projeto original e identifica a origem como via substitutivo.",
    ),
    "indicacao": (
        "Indicação",
        "Pedido ao Executivo de um serviço ou obra, como iluminação, asfalto, poda ou limpeza.",
    ),
    "requerimento": (
        "Requerimento",
        "Pedido formal, como de informações ao Executivo ou de cópia de processos e contratos.",
    ),
    "mocao": (
        "Moção",
        "Manifestação da Câmara: aplauso, pesar, repúdio, apoio e outras.",
    ),
    "pdl": (
        "Projeto de decreto legislativo (PDL)",
        "Ato da Câmara sem sanção do prefeito, como a concessão de títulos e honrarias "
        "ou a sustação de atos.",
    ),
    "projeto-de-resolucao": (
        "Projeto de resolução",
        "Norma interna da Câmara, como mudanças no Regimento, na estrutura administrativa "
        "ou em honrarias.",
    ),
    "veto": (
        "Veto",
        "Recusa do prefeito a todo o projeto aprovado ou a parte dele. "
        "A Câmara pode manter ou derrubar o veto.",
    ),
    "derrubada": (
        "Derrubada de veto",
        "Rejeição do veto pela Câmara. Exige 11 votos, maioria absoluta dos 21 vereadores, "
        "não dos presentes.",
    ),
    "quorum": (
        "Quórum",
        "Número mínimo de presenças ou votos exigido para um ato da Câmara. "
        "Derrubar um veto exige 11 votos dos 21 vereadores, não apenas a opção mais votada.",
    ),
    "parecer": (
        "Parecer",
        "Opinião da comissão sobre a matéria. O voto nominal Favor ou Contra é sobre "
        "o parecer, não necessariamente a favor ou contra a matéria.",
    ),
    "consignado": (
        "Consignado",
        "Registro feito pela Mesa que conta como presença no site.",
    ),
    "votou-ausente": (
        "Votou ausente na abertura",
        "Ausência na abertura com voto nominal substantivo registrado na mesma sessão. "
        "Conta como presença identificada à parte; presidir não é voto substantivo.",
    ),
    "ausencia-justificada": (
        "Ausência justificada",
        "Ausência marcada como justificada pela Câmara. Não conta como presença nem como falta "
        "na base da presença efetiva; permanece na base da presença bruta.",
    ),
    "abono-cargo": (
        "Abonada por outro cargo",
        "Ausência no intervalo documentado de afastamento para exercer outro cargo. "
        "Fica fora da base da presença efetiva, mas permanece na presença bruta.",
    ),
    "presenca-efetiva": (
        "Presença efetiva",
        "Presenças (incluindo consignado e ausência com voto) divididas por presenças mais faltas "
        "não abonadas. Justificadas, abonadas por outro cargo e licenças ficam fora da base. "
        "O percentual só aparece com ao menos 10 sessões na base individual.",
    ),
}


class ColetorGlossario:
    """Reúne os termos de uma página na ordem da primeira utilização."""

    def __init__(self, prefixo: str = ""):
        self.prefixo = prefixo
        self._usados: dict[str, None] = {}
        self._emitido = False

    def termo(self, chave: str, texto: str | None = None) -> str:
        """Cria um link para a metodologia e registra a chave conhecida."""
        try:
            rotulo, _ = TERMOS[chave]
        except KeyError:
            raise KeyError(f"termo de glossário desconhecido: {chave}") from None
        self._usados.setdefault(chave, None)
        href = escape(f"{self.prefixo}metodologia.html#g-{chave}")
        return (f'<a class="glossario" href="{href}" data-termo="{escape(chave)}">'
                f'{escape(rotulo if texto is None else texto)}</a>')

    def definicoes(self) -> str:
        """Emite o template uma única vez; sem termos ou após a emissão, retorna vazio.

        Chame ao final da composição da página, depois de registrar todos os termos.
        """
        if not self._usados or self._emitido:
            return ""
        self._emitido = True
        itens = "".join(
            f'<p data-termo="{escape(chave)}"><b>{escape(TERMOS[chave][0])}</b>: '
            f'{escape(TERMOS[chave][1])}</p>'
            for chave in self._usados
        )
        return f'<template id="glossario-defs">{itens}</template>'


def secao_glossario() -> str:
    """Lista todos os termos por rótulo, sem distinguir acentos ou maiúsculas."""
    def ordem(chave: str) -> tuple[str, str]:
        rotulo = unicodedata.normalize("NFD", TERMOS[chave][0].casefold())
        return "".join(c for c in rotulo if not unicodedata.combining(c)), chave

    itens = "".join(
        f'<dt><dfn id="g-{escape(chave)}">{escape(TERMOS[chave][0])}</dfn></dt>'
        f'<dd>{escape(TERMOS[chave][1])}</dd>'
        for chave in sorted(TERMOS, key=ordem)
    )
    return ('<section id="glossario" aria-labelledby="t-glossario">'
            '<h2 id="t-glossario">Glossário</h2><dl class="defs">'
            f'{itens}</dl></section>')
