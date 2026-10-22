# Radar dos Vereadores de Niterói

Site aberto que mostra quais leis de Niterói mudam a cidade e quem as escreveu, e quanto da produção da Câmara desde 2021 é homenagem, lei sem efeito prático, projeto repetido ou pauta polêmica.

Páginas: placar por vereador e leis com efeito mais recentes (início), leis aprovadas com filtros por impacto, tema, vereador e partido, todos os projetos, sem efeito e polêmicas, análises históricas e metodologia.

Os dados vêm do [SISCAM da Câmara Municipal de Niterói](https://consultaniteroi.siscam.com.br/) e são atualizados toda semana por GitHub Actions. O site é estático e fica no GitHub Pages.

## Como funciona

| Etapa | Arquivo | O que faz |
|---|---|---|
| Coleta | `coletor/siscam.py` | Baixa a lista de projetos de lei de cada ano e, para os novos ou com tramitação alterada, a autoria e a tramitação completa. Grava `data/proposicoes/<ano>.json`. |
| Classificação | `coletor/classificar.py` | Combina curadoria (`config/curadoria.json`), regras determinísticas (simbólica, autorizativa, vetos, pareceres, duplicação de lei em vigor) e IA via OpenCode Go, que atribui categoria, tema, impacto (0 a 3), resumo, público afetado e alertas. O resultado fica em cache (`data/classificacao_ia.json`) e só é refeito quando a ementa ou o prompt mudam. |
| Site | `coletor/gerar_site.py` e `coletor/site/` | Monta o modelo e as métricas (`modelo.py`), detecta projetos repetidos, gera gráficos SVG com tabela acessível (`graficos.py`) e as páginas (`paginas.py`). Filtros rodam no navegador (`site_src/app.js`) a partir de `dados/projetos.json`. |

Os workflows estão em `.github/workflows/`:

- **Coleta semanal** (`coleta.yml`): roda toda segunda-feira às 06:17 (Brasília) ou manualmente, coleta, classifica e grava os dados no repositório.
- **Publicar site** (`site.yml`): gera e publica o site no GitHub Pages ao fim de cada coleta e a cada mudança no código ou na configuração.

## Configuração

1. Em **Settings → Pages**, escolha **Source: GitHub Actions**.
2. Em **Settings → Secrets and variables → Actions**, crie o secret `OPENCODE_API_KEY` com sua chave do OpenCode Go. Sem ele, o site funciona só com regras e curadoria.
3. Opcional: crie a variável `OPENCODE_MODEL` para trocar o modelo (padrão: `deepseek-v4.1-flash`). A lista de modelos está em `https://opencode.ai/zen/go/v1/models`.

A chamada à IA usa `POST /chat/completions` em `https://opencode.ai/zen/go/v1`, com os headers `Authorization: Bearer <chave>`, `User-Agent` próprio e `x-opencode-session` estável por execução, como recomenda a [documentação do OpenCode Go](https://opencode.ai/docs/go/).

## Rodar localmente

Só precisa de Python 3.10+ (sem dependências externas).

```bash
python -m coletor.siscam --anos 2025-2026   # coleta
OPENCODE_API_KEY=... python -m coletor.classificar   # ou --sem-ia
python -m coletor.gerar_site
python -m http.server -d site 8000
```

## Contribuir

- **Composição das legislaturas e afastamentos**: `config/vereadores.json`.
- **Curadoria de alertas**: `config/curadoria.json`. Toda entrada precisa de fonte pública. A curadoria prevalece sobre a IA.
- **Classificação errada**: use o link "contestar" no site, que abre uma issue.

Os critérios valem igualmente para qualquer autor, partido ou espectro político. A [metodologia](site_src/) completa é publicada no próprio site.

## Licença

[GNU General Public License v3.0](LICENSE).
