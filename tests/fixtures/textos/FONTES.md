# Fixtures dos extratores de texto

Todas as fixtures desta pasta são **sintéticas**: o texto foi escrito para os testes, sem
documentos reais do SISCAM e sem dados pessoais. Os CPFs dos testes da máscara
(`tests/test_mascara.py`) são exemplos públicos de dígitos verificadores válidos, sem
relação com pessoas; telefones e e-mails são inventados.

Os bytes são gerados de forma determinística por `gerar_fixtures.py` (somente biblioteca
padrão). Os testes importam o gerador e criam as fixtures em memória; para gravá-las nesta
pasta e inspecioná-las, rode na raiz do repositório:

```text
python tests/fixtures/textos/gerar_fixtures.py
```

O gerador recusa qualquer fixture acima de 50 KB, e `tests/test_extratores.py`
(`TestFixtures`) confere tamanho e determinismo.

| Fixture | Função | Origem e conteúdo |
| --- | --- | --- |
| `docx_simples.docx` | `docx_simples` | Zip montado com `zipfile`: `[Content_Types].xml`, `_rels/.rels` e `word/document.xml` com três parágrafos, tabulação e quebra manual. |
| `docx_completo.docx` | `docx_completo` | Tabela de três linhas, cabeçalho repetido em dois arquivos, rodapé, nota de rodapé (mais o separador, que deve sumir), texto excluído em revisão, código de campo `PAGE` e caixa de texto com `mc:Fallback` duplicado. |
| `docx_sem_documento.docx` | `docx_sem_documento` | Pacote docx sem `word/document.xml`. |
| `doc_curto.doc` | `doc_curto` | Compound File v3 escrito pelo gerador (cabeçalho, FAT, diretório) com stream `WordDocument` (FIB Word 97, `nFib` 0x00C1) e `1Table` com o Clx (um Prc e o Pcdt). Uma peça compactada em cp1252. Streams completados até 4096 bytes, lidos pela FAT. |
| `doc_fragmentado.doc` | `doc_fragmentado` | Seis peças alternando cp1252 (bit 30 do fc) e UTF-16LE, com caracteres fora do cp1252 numa peça Unicode no meio, campo `HYPERLINK` (\x13 código \x14 resultado \x15), tabela (\x07) e quebras \x0b/\x0c. |
| `doc_minifat.doc` | `doc_minifat` | Streams `WordDocument` e `0Table` menores que 4096 bytes, guardados no mini stream e lidos pela MiniFAT. |
| `exemplo.rtf` | `rtf_exemplo` | RTF escrito à mão no gerador: tabelas de fontes/cores, `\info`, `\*\generator`, `\'hh` em cp1252, `\uN` com `\ucN`, campo com `\fldinst`/`\fldrslt`, imagem `\pict`, linha de tabela e `\binN` com bytes que imitam chaves. |
| `exemplo.html` | `html_exemplo` | HTML com `script`, `style`, comentário, entidades, `&nbsp;`, tabela e `<br>`. |
| `pdf_texto.pdf` | `pdf_texto` | PDF 1.4 escrito pelo gerador, uma página com Helvetica/WinAnsiEncoding (texto com acentos e “nº”). |
| `pdf_misto.pdf` | `pdf_misto` | Página 1 com texto; página 2 só com uma imagem cinza (FlateDecode) do texto `CAMARA MUNICIPAL / DE NITEROI / DOCUMENTO DIGITALIZADO` desenhado numa fonte bitmap 5×7 própria, sem camada de texto. |
| `pdf_escaneado.pdf` | `pdf_escaneado` | Uma página só com a imagem acima. |
| `pdf_corrompido.pdf` | `pdf_corrompido` | Cabeçalho `%PDF-1.4` seguido de lixo, sem xref nem trailer. |
| `escaneado.png` | `png_escaneado` | PNG cinza de 8 bits (codificador mínimo com `zlib`) com a mesma imagem. |
| `zip_docx_pdf.zip` | `zip_docx_pdf` | Zip com `documento.docx` (docx simples) e `anexo.pdf` (PDF com texto). |
| `zip_aninhado.zip` | `zip_aninhado` | Zip com um RTF e um zip interno, que contém um docx e um terceiro nível de zip (além do limite de 2 níveis). |
| JPEG | — | Gerado durante `TestOcrReal` com `pdftoppm -jpeg` a partir de `pdf_escaneado`; não é gravado nesta pasta. |

Casos de malformação (CFB com ciclo na FAT, CFB truncado, tamanho declarado maior que o
arquivo, documento criptografado, zip bomb e tamanho descompactado falso) são derivados
dessas fixtures dentro dos próprios testes.
