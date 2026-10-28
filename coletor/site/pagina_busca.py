"""Busca progressiva no inteiro teor; as listas estáticas independem da API."""
from __future__ import annotations

import json
from pathlib import Path

from coletor.mascara import DOMINIOS_LIBERADOS
from coletor.site import paginas as P
from coletor.site.glossario import ColetorGlossario

TIPOS = (("pl", "Projeto de lei"), ("substitutivo", "Substitutivo"),
         ("requerimento", "Requerimento"), ("indicacao", "Indicação (ementa)"),
         ("mocao", "Moção (ementa)"), ("pdl", "Projeto de decreto legislativo"),
         ("resolucao", "Projeto de resolução"), ("ata", "Ata de sessão"))


def carregar_api(raiz: Path) -> str | None:
    """Lê a configuração versionada, sem rede nem variáveis de ambiente."""
    caminho = raiz / "config" / "backend.json"
    return json.loads(caminho.read_text(encoding="utf-8")).get("api_url") if caminho.exists() else None


def gerar_busca(modelo: dict, api_url: str | None) -> str:
    glossario = ColetorGlossario()
    tipos = "".join(f'<option value="{t}">{P.esc(n)}</option>' for t, n in TIPOS)
    pessoas_busca = {P.slug_autor_busca(modelo, p): p["nome"] for p in modelo["pessoas"].values()}
    autores = "".join(f'<option value="{P.esc(s)}">{P.esc(nome)}</option>'
                      for s, nome in sorted(pessoas_busca.items(), key=lambda item: item[1]))
    legislaturas = "".join(f'<option value="{P.esc(l["id"])}">{P.esc(l["id"])}</option>'
                           for l in modelo["legislaturas"])
    estado = ("A busca precisa de JavaScript para consultar a API. Ative-o ou use as listas abaixo."
              if api_url else "A busca no inteiro teor ainda não está disponível. Use as listas abaixo ou consulte o SISCAM.")
    corpo = f"""<div class="abertura"><h1>Busca no inteiro teor</h1>
<p>Pesquise por palavras ou por significado nos textos extraídos dos documentos e atas.
Indicações e moções entram somente pela ementa. A {glossario.termo('busca')} não gera respostas.</p></div>
<div class="busca">
<p id="busca-alternativa">{estado}</p>
<p><a href="projetos.html">Lista de projetos</a> · <a href="atividades.html">Lista de atividades</a> ·
<a href="sessoes.html">Sessões</a> · <a href="{P.SISCAM}">Consultar o SISCAM</a></p>
<p>Confira os trechos no original: a extração e o OCR podem conter erros.
<a href="metodologia.html#inteiro-teor">Cobertura e limitações</a> ·
<a href="metodologia.html#privacidade">Privacidade e pedidos de remoção</a>.</p>
<form id="busca-form" role="search" aria-label="Busca no inteiro teor">
<fieldset id="busca-campos" disabled><legend>Consulta e filtros</legend>
<div class="busca-filtros">
<label for="busca-q">O que procurar<input id="busca-q" name="q" type="search" required minlength="2" maxlength="200" aria-describedby="busca-dica"></label>
<label for="busca-modo">Modo<select id="busca-modo" name="modo"><option value="hibrida">Palavras e significado</option><option value="palavras">Palavras</option><option value="semantica">Significado</option></select></label>
<label for="busca-tipo">Tipo<select id="busca-tipo" name="tipo"><option value="">Todos</option>{tipos}</select></label>
<label for="busca-ano">Ano<input id="busca-ano" name="ano" type="number" min="1900" max="2100" step="1"></label>
<label for="busca-autor">Autor<select id="busca-autor" name="autor"><option value="">Todos</option>{autores}</select></label>
<label for="busca-legislatura">Legislatura<select id="busca-legislatura" name="legislatura"><option value="">Todas</option>{legislaturas}</select></label>
</div><p id="busca-dica">Use de 2 a 200 caracteres e ao menos um termo específico. Não inclua dados pessoais na consulta.</p>
<button type="submit">Buscar</button></fieldset></form>
<p id="busca-estado" role="status" aria-live="polite" aria-atomic="true" tabindex="-1"></p>
<p id="busca-aviso" aria-live="polite" aria-atomic="true"></p>
<section aria-labelledby="busca-titulo"><h2 id="busca-titulo">Resultados</h2>
<ol id="busca-resultados" class="busca-resultados" role="list"></ol>
<button id="busca-mais" type="button" hidden>Mostrar mais</button></section></div>
"""
    return P.pagina("Busca · Radar dos Vereadores de Niterói", corpo + glossario.definicoes(), "busca.html",
                    caminho="busca.html", estilos=("busca.css",), scripts=("busca.js",), radar_api=api_url or "",
                    scripts_base=False)


def metodologia_busca() -> str:
    """Critérios públicos da extração, consulta e acesso aos originais."""
    dominios = ", ".join(f"<code>{P.esc(d)}</code>" for d in DOMINIOS_LIBERADOS)
    return f"""<section id="inteiro-teor"><h2>Inteiro teor, extração e OCR</h2>
<p>O escopo inclui projetos de lei, substitutivos, requerimentos, projetos de decreto legislativo,
projetos de resolução e atas. Indicações e moções são pesquisadas só pela ementa, não pelo inteiro teor.
A disponibilidade depende do processamento dos arquivos publicados pelo SISCAM.</p>
<p>São extraídos textos de DOC, DOCX, RTF, HTML, PDF e arquivos em ZIP. PDFs escaneados e imagens
recebem reconhecimento óptico de caracteres (OCR) em português. Páginas sem texto suficiente podem
receber OCR mesmo em um PDF misto. O selo OCR identifica esse processo; OCR de baixa confiança
indica confiança média inferior a 60. Essa medida não é garantia de exatidão: nomes, tabelas e números
podem conter erros. O selo Extração parcial indica que apenas parte do arquivo pôde ser extraída.
Cabeçalhos, rodapés repetidos e ruído são removidos por regras. Confira o original.</p>
<p>Páginas com confiança de OCR inferior a 60 são mantidas nos textos publicados, mas não são indexadas para busca.</p></section>
<section id="busca"><h2>Como funciona a busca</h2>
<p>A <a href="busca.html">busca</a> por palavras usa FTS5 e ordenação BM25, sem distinguir acentos,
com até 500 candidatos. A busca por significado compara vetores de trechos com o modelo bge-m3,
com até 50 candidatos. O modo híbrido combina as duas listas e usa
Reciprocal Rank Fusion (RRF), com k = 60, somando posições nas duas listas e desempate pelo id.
Não há resposta ou resumo gerado por IA: os resultados são trechos dos textos extraídos.</p>
<p>A busca semântica pode consultar até 100 candidatos antes do filtro por autor; não é exaustiva.
A busca informa quando alcança o limite de candidatos. Ausência de resultado
não prova ausência de documento. Se o modo combinado perder a busca semântica, mostra palavras e um aviso.</p></section>
<section id="privacidade"><h2>Privacidade e remoção</h2>
<p>Nos textos extraídos pesquisáveis, a mesma regra de mascaramento se aplica a todas as pessoas,
inclusive vereadores e suplentes. CPF com dígitos verificadores válidos ou identificado por rótulo
é substituído por <code>[CPF omitido]</code>; RG identificado por rótulo, por <code>[RG omitido]</code>.
Documentos pessoais rotulados (CNH, título de eleitor, PIS, CNS, entre outros) são substituídos por
<code>[documento omitido]</code>. Telefones e e-mails de qualquer pessoa, inclusive e-mails com erros de OCR,
são mascarados; nas páginas com OCR, números de oito ou mais dígitos também recebem
<code>[número omitido]</code>, com proteções contra falsos positivos como datas e valores monetários.</p>
<p>As exceções são contatos públicos publicados pelos próprios mandatos e contatos institucionais,
listados com fonte em <code>config/perfis.json</code> (<code>contatos</code>) e
<code>config/backend.json</code> (<code>contatos_institucionais</code>), além de e-mails dos domínios
públicos {dominios} e seus subdomínios. Nomes e endereços não são mascarados.
O mascaramento automático pode falhar; comunique ocorrências.</p>
<p>Os originais ficam em armazenamento privado e são servidos para download por <code>/api/original/:sha256</code>,
sem máscara, exatamente como publicados pelo SISCAM, como registro público. O texto pesquisável não substitui esse original.</p>
<p>Para solicitar remoção, <a href="{P.REPO}/issues/new">abra uma issue</a> indicando o documento e o motivo,
sem reproduzir dados pessoais. As remoções são registradas em <code>config/remocoes.json</code>,
com chave de origem, hash, motivo, fonte e data, para impedir sua disponibilização.
A remoção abrange o texto extraído, os trechos, os vetores, o original e as exportações,
inclusive versões antigas, que são reescritas; a ementa mascarada e os metadados do documento
permanecem públicos nas listas e na busca, como no SISCAM; ela passa a valer na próxima
sincronização, acionada automaticamente quando <code>config/remocoes.json</code> muda na branch <code>main</code>.</p>
<p>A aplicação não registra a consulta nem o IP em logs. A borda do Cloudflare processa a URL da
requisição, que contém a consulta e os filtros; o navegador também os mantém no endereço e no histórico.
As métricas da aplicação registram apenas modo e contagem de resultados. A borda do Cloudflare mantém
respostas em cache por consulta normalizada durante 60 segundos e embeddings das consultas por uma hora,
sob uma chave de hash. Evite pesquisar dados pessoais.</p></section>
<section id="auditoria"><h2>Auditoria dos textos</h2>
<p>O Git é a fonte da verdade: os manifestos em <code>data/textos/manifesto-&lt;ano&gt;.json</code>
registram estados, versões e hashes SHA-256 dos originais, textos e trechos. Os textos mascarados
ficam na branch <code>dados-textos</code>. O hash mostrado no resultado identifica o arquivo original,
não atesta a correção da extração. As projeções de busca podem ser reconstruídas a partir desses registros.</p>
<p>O contrato descreve exportações, <code>SHA256SUMS</code> e atestação de proveniência;
consulte os artefatos publicados e suas evidências, quando disponíveis, no
<a href="{P.REPO}">repositório</a>. A verificação local usa
<code>python -m coletor.textos --verificar</code>; com credenciais, também compara o original no armazenamento.</p></section>"""
