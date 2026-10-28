"""Cliente de nuvem do Radar: R2 (S3 com SigV4), D1, Vectorize e Workers AI, só com a biblioteca padrão.

D1, Vectorize e R2 são projeções do Git (contrato `docs/contratos/textos.md`, seção 8),
sincronizadas por `python -m coletor.nuvem --ambiente local|staging|production`.
Uso e operação em `docs/backend.md`, seção "Sincronização com a nuvem".
"""
from __future__ import annotations
