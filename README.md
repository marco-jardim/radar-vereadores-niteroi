# Radar dos Vereadores de Niterói

Site aberto que mostra quantos projetos de lei cada vereador de Niterói apresentou desde 2021, quantos viraram lei e de que tipo: leis substantivas, simbólicas (homenagens, nomes de rua, datas) e projetos com alerta de polêmica.

Os dados vêm do [SISCAM da Câmara Municipal de Niterói](https://consultaniteroi.siscam.com.br/) e são atualizados toda semana por GitHub Actions. O site é estático e fica no GitHub Pages.

## Como funciona

| Etapa | Arquivo | O que faz |
|---|---|---|
| Coleta | `coletor/siscam.py` | Baixa a lista de projetos de lei de cada ano e, para os novos ou com tramitação alterada, a autoria e a tramitação completa. Grava `data/proposicoes/<ano>.json`. |
| Classificação | `coletor/classificar.py` | Combina curadoria (`config/curadoria.json`), regras sobre a tramitação e a ementa, e IA via OpenCode Go. A IA guarda resultado em cache (`data/classificacao_ia.json`) e só reclassifica o que mudou. |
| Site | `coletor/gerar_site.py` | Gera `site/` com o placar por vereador, página de cada um, busca de projetos, lista de alertas e metodologia. |

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
