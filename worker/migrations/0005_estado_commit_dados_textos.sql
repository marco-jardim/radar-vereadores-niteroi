-- Referência independente dos JSONL publicados na branch dados-textos.
ALTER TABLE estado_indice ADD COLUMN commit_dados_textos TEXT;
