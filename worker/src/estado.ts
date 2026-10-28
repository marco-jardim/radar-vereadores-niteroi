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

export async function lerEstado(env: Env): Promise<{ estado: Estado | null; remocoes: string }> {
  try {
    // O lote observa o estado e as remoções juntos, inclusive numa sincronização parcial.
    // Serialização ordenada de todas as chaves/hashes evita colisões de COUNT/MAX isolados.
    const [re, rr] = await env.DB.batch([
      env.DB.prepare('SELECT versao, "commit", sha256_manifestos, total, sha256_conjunto, modelo, versao_trechos, data ' +
        "FROM estado_indice WHERE id = 1"),
      env.DB.prepare("SELECT json_group_array(json_array(chave, sha256, data)) AS resumo FROM " +
        "(SELECT chave, sha256, data FROM remocoes ORDER BY chave, sha256, data)"),
    ]);
    return {
      estado: (re!.results[0] as unknown as Estado | undefined) ?? null,
      remocoes: String(rr!.results[0]!.resumo),
    };
  } catch {
    throw new ErroHttp(503, "indisponivel", "Base de dados indisponível.");
  }
}

/**
 * Parte das chaves da Cache API: muda a cada sincronização, de modo que nenhuma resposta guardada
 * sobrevive a uma mudança do índice ou das remoções, mesmo sem novo estado_indice.
 */
export async function chaveIndice(estado: Estado | null, remocoes: string): Promise<string> {
  return (await sha256Hex(JSON.stringify([estado, remocoes]))).slice(0, 32);
}
