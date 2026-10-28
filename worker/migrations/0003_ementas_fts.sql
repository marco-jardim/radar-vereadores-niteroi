-- Ementas mascaradas de todos os documentos, inclusive substitutivos e sessões.
-- Normalização idêntica à de trechos_fts (normalizar_busca, antes da indexação).
-- rowid é interno do SQLite, sem significado externo. A sincronização compara,
-- apaga e junta pelo documento completo (doc:<id> ou sessao:<id>), sem colisões
-- entre espaços de ids e sem depender de rowids. Reconstruível, não exportado.
CREATE VIRTUAL TABLE ementas_fts USING fts5(documento UNINDEXED, texto_norm, tokenize = 'unicode61');
