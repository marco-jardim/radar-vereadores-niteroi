-- Esquema inicial do D1 do Radar dos Vereadores de Niterói.
-- Contrato: docs/contratos/textos.md, seção 8.1. As tabelas são projeções do Git,
-- reconstruíveis com `python -m coletor.nuvem --reconstruir`. Só `verificacoes` é
-- escrita pelo Worker. Migrações já aplicadas não são editadas: mudanças vão numa
-- nova migração numerada. (Sem ponto e vírgula nos comentários: o wrangler divide
-- o arquivo em instruções.)

-- Todos os documentos, inclusive indicações e moções (só a ementa, mascarada).
-- id: doc:<IdDocumento> ou sessao:<IdSessao>. O substitutivo tem pl = chave do PL.
CREATE TABLE documentos (
  id TEXT PRIMARY KEY,
  tipo TEXT NOT NULL,
  numero TEXT,
  ano INTEGER,
  data TEXT,
  ementa TEXT,
  url TEXT,
  legislatura TEXT,
  pl TEXT
);
CREATE INDEX documentos_tipo_ano ON documentos (tipo, ano);
CREATE INDEX documentos_pl ON documentos (pl);

-- papel: autor ou coautor. O filtro por autor da busca é feito aqui.
CREATE TABLE autoria (
  documento TEXT NOT NULL,
  slug TEXT NOT NULL,
  papel TEXT NOT NULL,
  PRIMARY KEY (documento, slug, papel)
);
CREATE INDEX autoria_slug ON autoria (slug);

CREATE TABLE pessoas (
  slug TEXT PRIMARY KEY,
  nome TEXT NOT NULL,
  partido_atual TEXT
);

-- Uma linha por entrada do manifesto, exceto removido e duplicata. ocr = 1 se paginas_ocr > 0.
CREATE TABLE arquivos (
  id TEXT PRIMARY KEY,
  sha256 TEXT,
  formato TEXT,
  status TEXT NOT NULL,
  ocr INTEGER NOT NULL DEFAULT 0,
  confianca REAL,
  r2_chave TEXT
);

-- Relação N:N: um arquivo pode servir a vários documentos (na canônica, a união das duplicatas).
CREATE TABLE arquivo_documento (
  arquivo TEXT NOT NULL,
  documento TEXT NOT NULL,
  PRIMARY KEY (arquivo, documento)
);
CREATE INDEX arquivo_documento_documento ON arquivo_documento (documento);

-- Texto lido do .txt de dados-textos pelos offsets e conferido pelo sha256.
CREATE TABLE trechos (
  id TEXT PRIMARY KEY,
  documento TEXT NOT NULL,
  arquivo TEXT NOT NULL,
  posicao INTEGER NOT NULL,
  texto TEXT NOT NULL,
  sha256 TEXT NOT NULL
);
CREATE INDEX trechos_documento ON trechos (documento);

-- Busca por palavras. O suporte do D1 a remove_diacritics não foi confirmado, então o
-- texto entra já normalizado (minúsculas, sem acentos: NFD sem as marcas Mn, como em
-- coletor.nuvem.fonte.normalizar_busca) e a consulta é normalizada do mesmo jeito.
-- rowid = int(id, 16) >> 1. Reconstruível e fora das exportações.
CREATE VIRTUAL TABLE trechos_fts USING fts5(id UNINDEXED, texto_norm, tokenize = 'unicode61');

-- Vetores já enviados ao Vectorize (trechos e ementa:doc:<id>), para a diferença incremental.
CREATE TABLE trechos_indexados (
  id TEXT PRIMARY KEY,
  sha256 TEXT NOT NULL
);

-- Cópia de config/remocoes.json sem a fonte, consultada pelo Worker antes da Cache API.
CREATE TABLE remocoes (
  chave TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  motivo TEXT NOT NULL,
  data TEXT NOT NULL,
  PRIMARY KEY (chave, sha256)
);

-- Uma linha, gravada só no fim de uma sincronização completa.
CREATE TABLE estado_indice (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  versao TEXT NOT NULL,
  "commit" TEXT,
  sha256_manifestos TEXT NOT NULL,
  total INTEGER NOT NULL,
  sha256_conjunto TEXT NOT NULL,
  modelo TEXT NOT NULL,
  versao_trechos TEXT NOT NULL,
  data TEXT NOT NULL
);

-- Única escrita do Worker (cron): conferência dos hashes por amostragem. data = carimbo ISO UTC.
CREATE TABLE verificacoes (
  data TEXT PRIMARY KEY,
  amostra INTEGER NOT NULL,
  ok INTEGER NOT NULL,
  falhas_json TEXT NOT NULL
);
