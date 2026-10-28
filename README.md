# Radar dos Vereadores de Niterói: textos extraídos

Esta branch (`dados-textos`) guarda o **inteiro teor** dos documentos da Câmara Municipal de Niterói coletados pelo SISCAM. Inclui PLs e substitutivos, requerimentos, PDLs, resoluções e atas de sessão. O conteúdo é gerado só por `python -m coletor.textos`, a partir da branch `main` do repositório `marco-jardim/radar-vereadores-niteroi`.

## Conteúdo

- `textos/<tipo>/<ano>/<documento>/<origem>-<id>.txt`: o texto extraído de cada arquivo. É limpo de timbres, cabeçalhos repetidos e ruído, e mascarado. Usa UTF-8, LF e NFC. As páginas ficam separadas por uma linha só com `\f`.
- `trechos/<tipo>/<ano>.jsonl`: os trechos usados na busca, guardados como deslocamentos dentro de cada `.txt`, sem repetir o texto.

O formato, as chaves, os hashes e as regras estão em `docs/contratos/textos.md`, na branch `main`. O manifesto com o hash de cada original e de cada texto fica em `data/textos/manifesto-<ano>.json`, também na `main`.

## Privacidade

Antes de serem gravados, os textos passam pela máscara de `coletor/mascara.py`:
- CPF, RG e números de documentos pessoais saem sempre;
- telefones e e-mails saem, salvo os contatos oficiais de mandatos e órgãos públicos que têm fonte pública.

Uma varredura independente bloqueia o commit se restar alguma ocorrência forte. Os originais não ficam aqui: estão no SISCAM e, como prova, num bucket privado.

**Pedido de remoção:** abra uma issue no repositório. A remoção é registrada em `config/remocoes.json` e propagada para textos, busca e exportações.

## Licença

Os documentos são atos públicos do Poder Legislativo municipal. O código que gera esta branch está sob GPL-3.0.
