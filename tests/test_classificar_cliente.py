"""Contrato congelado antes da extração do cliente OpenCode Go (T4.3.1)."""
from __future__ import annotations

import hashlib
import io
import json
import unittest
from unittest import mock

from coletor import classificar as C


# Literal independente de C.CATEGORIAS/C.ALERTAS: mudar a taxonomia também quebra o contrato.
PROMPT_ANTERIOR = '''Você classifica projetos de lei municipais da Câmara de Niterói (RJ) para um site de transparência
apartidário. Avalie apenas o texto da ementa. Seja conservador: só marque um alerta se a ementa der base clara para ele.
Aplique os mesmos critérios a qualquer autor, partido ou espectro político.

CATEGORIA (escolha exatamente uma):
{
 "simbolica": "Homenagem, nome de rua/logradouro/prédio público, data ou semana comemorativa, título, declaração de patrimônio cultural imaterial, utilidade pública, tombamento de bem específico.",
 "politica_publica": "Cria ou altera programa, política, serviço público, direito ou benefício para a população.",
 "regulacao": "Regras para atividades, comércio, consumo, posturas, trânsito, obras, uso do espaço urbano.",
 "administrativa_fiscal": "Estrutura administrativa, servidores, orçamento, créditos, tributos, fundos, contratos.",
 "outra": "Nenhuma das anteriores."
}

ALERTAS (zero ou mais; a maioria dos projetos não tem nenhum):
{
 "restricao_de_direitos": "Restringe direitos, acesso a espaços/serviços ou expressão de um grupo (ex.: pessoas LGBTQIA+, população em situação de rua, minorias religiosas, mulheres, artistas de periferia).",
 "pauta_de_costumes": "Tema de disputa moral/cultural (gênero, sexualidade, drogas, religião, 'ideologia') cujo efeito principal é simbólico ou de posicionamento, não de gestão.",
 "apelo_populista": "Medida de forte apelo imediato sem indicação de custo, fonte de recurso ou viabilidade, reação a caso midiático, ou que mira pessoa/grupo específico pelo nome.",
 "inconstitucionalidade_provavel": "Provável vício: invade competência da União/Estado, legisla sobre relações privadas fora da competência municipal, ou cria despesa/atribuição ao Executivo por iniciativa parlamentar."
}

IMPACTO (0 a 3), o efeito concreto esperado sobre a vida das pessoas ou sobre a gestão da cidade:
 0 = nenhum efeito prático (homenagem, data, nome, título, utilidade pública, lei meramente autorizativa ou que repete norma existente);
 1 = baixo (efeito pontual, restrito a um local, grupo pequeno ou procedimento menor);
 2 = médio (muda regra ou serviço para um grupo relevante ou para um setor da cidade);
 3 = alto (afeta grande parte da população, cria política ou serviço amplo, ou mexe em orçamento/tributo relevante).
Avalie o efeito pelo que a ementa determina, não pelo tema ser importante.

RESUMO: até 140 caracteres, linguagem simples, começando por um verbo no presente ("Obriga...", "Cria...", "Proíbe...").
PUBLICO: quem é diretamente afetado, em até 4 palavras (ex.: "pessoas com deficiência", "comércio do Centro", "toda a cidade").

TEMA: uma palavra entre saude, educacao, seguranca, mobilidade, meio_ambiente, urbanismo, cultura, esporte,
assistencia_social, direitos_humanos, economia, consumidor, animais, administracao, tributos, homenagem, outro.

Responda SOMENTE com JSON no formato:
{"itens":[{"id":<id>,"categoria":"...","tema":"...","impacto":0-3,"resumo":"...","publico":"...",
"alertas":[{"rotulo":"...","confianca":0.0-1.0}],
"justificativa":"até 200 caracteres, em português, citando o trecho da ementa que motivou os alertas (ou 'sem alertas')"}]}'''


class TestExtracaoCliente(unittest.TestCase):
    def test_prompt_versao_hash_e_cache_preservados(self):
        self.assertEqual(C.PROMPT_SISTEMA, PROMPT_ANTERIOR)
        self.assertEqual(C.VERSAO_PROMPT, "2026-10-v2")
        ementa = "Dispõe sobre a coleta seletiva nas escolas."
        with mock.patch.object(C, "MODELO", "deepseek-v4.1-flash"):
            h = hashlib.sha1(("2026-10-v2|deepseek-v4.1-flash|" + ementa).encode()).hexdigest()[:16]
            self.assertEqual(C._hash(ementa), h)
            antigo = {"1": {"hash": h, "categoria": "regulacao", "impacto": 2,
                            "tema": "educacao", "alertas": [], "resumo": "Cria coleta seletiva."}}
            with mock.patch.object(C, "carregar_proposicoes", return_value=[{"id": 1, "ementa": ementa}]), \
                    mock.patch.object(C, "CACHE_IA") as caminho, \
                    mock.patch.dict("os.environ", {"OPENCODE_API_KEY": "falsa"}), \
                    mock.patch.object(C, "salvar_mapa"), mock.patch.object(C, "chamar_ia") as chamar:
                caminho.exists.return_value = True
                caminho.read_text.return_value = json.dumps(antigo)
                estat = C.classificar(True, None)
            chamar.assert_not_called()
            self.assertEqual((estat["ia_novos"], estat["ia_cache"]), (0, 1))

    def test_requisicao_e_decodificacao_identicas(self):
        itens = [{"id": 123, "ementa": "Dispõe sobre ação."}, {"id": 124, "ementa": None}]
        resposta = '{"itens":[{"id":123,"categoria":"regulacao"},{"id":"124","categoria":"outra"}]}'
        retorno = io.BytesIO(json.dumps({"choices": [{"message": {"content": "```json\n" + resposta + "\n```"}}]}).encode())
        with mock.patch.object(C.urllib.request, "urlopen", return_value=retorno) as transporte:
            dados = C.chamar_ia(itens, "falsa", "sessao-original")
        self.assertEqual(dados, {123: {"id": 123, "categoria": "regulacao"},
                                 124: {"id": "124", "categoria": "outra"}})
        conteudo = '\n'.join(f'{{"id":{p["id"]},"ementa":{json.dumps(p.get("ementa") or "", ensure_ascii=False)}}}' for p in itens)
        corpo = {"model": C.MODELO, "temperature": 0, "response_format": {"type": "json_object"},
                 "messages": [{"role": "system", "content": PROMPT_ANTERIOR},
                              {"role": "user", "content": "Classifique os projetos abaixo (um JSON por linha):\n" + conteudo}]}
        req = transporte.call_args.args[0]
        self.assertEqual(req.data, json.dumps(corpo).encode())
        self.assertEqual(req.full_url, C.BASE_URL.rstrip("/") + "/chat/completions")
        headers = {k.lower(): v for k, v in req.header_items()}
        self.assertEqual(headers["x-opencode-session"], "sessao-original")
        self.assertEqual(headers["user-agent"], C.USER_AGENT)
        self.assertEqual(headers["authorization"], "Bearer falsa")
        self.assertEqual(transporte.call_args.kwargs, {"timeout": 180})
