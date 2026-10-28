// estado_indice (uma linha, gravada pelo coletor.nuvem no fim de uma sincronização completa).
import type { Env } from "./ambiente";
import { ErroHttp, sha256Hex } from "./http";

export interface Estado {
  versao: string;
  commit: string | null;
  sha256_manifestos: string;
  total: number;
  sha256_conjunto: string;
  modelo: string;
  versao_trechos: string;
  data: string;
}

export async function lerEstado(env: Env): Promise<Estado | null> {
  try {
    return await env.DB.prepare(
      'SELECT versao, "commit", sha256_manifestos, total, sha256_conjunto, modelo, versao_trechos, data ' +
        "FROM estado_indice WHERE id = 1",
    ).first<Estado>();
  } catch {
    throw new ErroHttp(503, "indisponivel", "Base de dados indisponível.");
  }
}

/**
 * Parte das chaves da Cache API: muda a cada sincronização, de modo que nenhuma resposta guardada
 * sobrevive a uma mudança do índice (inclusive uma remoção).
 */
export async function chaveIndice(estado: Estado | null): Promise<string> {
  return estado ? (await sha256Hex(JSON.stringify(estado))).slice(0, 16) : "vazio";
}
