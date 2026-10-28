-- A busca e a hidratação conferem remoções também pelo hash, independentemente da chave.
CREATE INDEX IF NOT EXISTS remocoes_sha256 ON remocoes(sha256);
