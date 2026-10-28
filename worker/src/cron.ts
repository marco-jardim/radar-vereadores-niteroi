// Auditoria diária: Git é a referência; só verificacoes recebe escritas.
import type { Env, R2ObjetoCorpo } from "./ambiente";

export const TAMANHO_AMOSTRA = 50;
// Mesmo teto da via REST do sincronizador; não tenta originais deliberadamente omitidos.
export const MAX_ORIGINAL = 100_000_000 - 1024 * 1024;
const CHAVE = /^(siscam:[1-9][0-9]*|sessao:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/;
const HASH = /^[0-9a-f]{64}$/;
const TIPOS = new Set(["pl", "requerimento", "pdl", "resolucao", "ata"]);
const SEM_ORIGINAL = new Set(["removido", "duplicata", "pendente_download"]);

interface Arquivo {
  chave: string;
  ano: number;
  tipo: string;
  sha256_original: string;
  r2_chave: string;
  trechos: number;
}
interface Falha { etapa: string; codigo: string; chave?: string; ano?: number }
export interface ResultadoVerificacao { data: string; amostra: number; ok: number; falhas: Falha[] }
export interface OpcoesVerificacao {
  /** Prazo de GET + consumo de cada original; padrão 10 s, limitado pelo prazo global. */
  prazoOriginalMs?: number;
}
interface HashTrecho { id: string; sha256: string }
interface Digestor extends WritableStream<Uint8Array> { digest: Promise<ArrayBuffer> }
// Extensão do runtime Workers, ausente na lib WebWorker padrão do TypeScript.
interface CryptoWorkers extends Crypto { DigestStream: new (algoritmo: string) => Digestor }

function objeto(valor: unknown): valor is Record<string, unknown> {
  return typeof valor === "object" && valor !== null && !Array.isArray(valor);
}

/** Fisher–Yates com semente UTC e ordem inicial por chave, independente da ordem do Git. */
export function amostraDeterministica<T extends { chave: string }>(arquivos: readonly T[], data: string, limite = TAMANHO_AMOSTRA): T[] {
  const lista = [...arquivos].sort((a, b) => a.chave < b.chave ? -1 : a.chave > b.chave ? 1 : 0);
  let semente = 2166136261;
  for (const letra of data) semente = Math.imul(semente ^ letra.charCodeAt(0), 16777619) >>> 0;
  for (let i = lista.length - 1; i > 0; i--) {
    semente = (semente + 0x6d2b79f5) >>> 0;
    let n = Math.imul(semente ^ (semente >>> 15), 1 | semente);
    n ^= n + Math.imul(n ^ (n >>> 7), 61 | n);
    const j = Math.floor(((n ^ (n >>> 14)) >>> 0) / 4294967296 * (i + 1));
    [lista[i], lista[j]] = [lista[j]!, lista[i]!];
  }
  return lista.slice(0, limite);
}

/** O prazo cobre também o consumo do corpo, não apenas a chegada dos cabeçalhos. */
async function comPrazo<T>(acao: (sinal: AbortSignal) => Promise<T>, ms: number): Promise<T> {
  const controle = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([acao(controle.signal), new Promise<never>((_, rejeitar) => {
      timer = setTimeout(() => { controle.abort(); rejeitar(new Error("prazo")); }, ms);
    })]);
  } finally { clearTimeout(timer); }
}

/** Nenhum arrayBuffer/text do objeto R2: os bytes vão diretamente ao DigestStream. */
export async function hashOriginal(original: R2ObjetoCorpo, sinal: AbortSignal): Promise<string> {
  const digestor = new (crypto as CryptoWorkers).DigestStream("SHA-256");
  // Observa a rejeição mesmo se uma leitura falhar antes de aguardarmos o resumo.
  void digestor.digest.catch(() => undefined);
  const leitor = original.body.getReader();
  const escritor = digestor.getWriter();
  let bytes = 0;
  let concluido = false;
  const cancelar = (): void => {
    // Cancela diretamente a leitura pendente: não depende da propagação de abort
    // por pipeThrough/pipeTo, que pode deixar um TransformStream bloqueado.
    void leitor.cancel(sinal.reason).catch(() => undefined);
    void escritor.abort(sinal.reason).catch(() => undefined);
  };
  sinal.addEventListener("abort", cancelar, { once: true });
  try {
    sinal.throwIfAborted();
    while (true) {
      const { done, value: parte } = await leitor.read();
      sinal.throwIfAborted();
      if (done) break;
      bytes += parte.byteLength;
      if (bytes > MAX_ORIGINAL) throw new Error("tamanho");
      await escritor.write(parte);
    }
    await escritor.close();
    const resumo = await digestor.digest;
    sinal.throwIfAborted();
    concluido = true;
    return Array.from(new Uint8Array(resumo), (n) => n.toString(16).padStart(2, "0")).join("");
  } finally {
    sinal.removeEventListener("abort", cancelar);
    if (!concluido) await Promise.allSettled([leitor.cancel(sinal.reason), escritor.abort(sinal.reason)]);
    leitor.releaseLock();
    escritor.releaseLock();
  }
}

export async function verificar(env: Env, agora = new Date(), opcoes: OpcoesVerificacao = {}): Promise<ResultadoVerificacao> {
  const resultado: ResultadoVerificacao = { data: agora.toISOString(), amostra: 0, ok: 0, falhas: [] };
  const fim = Date.now() + 240_000;
  let chamadas = 0;
  // Inclui fetch, R2 e D1. Reserva uma chamada para gravar, sem tentativas automáticas.
  function reservar(): number {
    if (++chamadas > 239 || Date.now() >= fim) throw new Error("orcamento");
    return Math.min(10_000, fim - Date.now());
  }
  const falhar = (etapa: string, codigo: string, chave?: string, ano?: number): void => {
    resultado.falhas.push({ etapa, codigo, ...(chave ? { chave } : {}), ...(ano ? { ano } : {}) });
  };
  async function raw(caminho: string, branch: string, permitir404 = false): Promise<string | null> {
    const prazo = reservar();
    const base = env.CRON_RAW_BASE ?? "https://raw.githubusercontent.com/marco-jardim/radar-vereadores-niteroi";
    const url = new URL(`${base.replace(/\/$/, "")}/${encodeURIComponent(branch)}/${caminho}`);
    if (url.origin !== "https://raw.githubusercontent.com") throw new Error("fonte");
    return comPrazo(async (signal) => {
      const resposta = await fetch(url, { signal, redirect: "error" });
      if (!resposta.ok) {
        await resposta.body?.cancel();
        if (permitir404 && resposta.status === 404) return null;
        throw new Error("http");
      }
      return resposta.text();
    }, prazo);
  }
  try {
    const arquivos: Arquivo[] = [];
    const vistos = new Set<string>();
    for (let ano = 2021; ano <= agora.getUTCFullYear(); ano++) {
      try {
        const texto = await raw(`data/textos/manifesto-${ano}.json`, env.CRON_MANIFESTOS_BRANCH ?? "main", true);
        if (texto === null) continue;
        const manifesto: unknown = JSON.parse(texto);
        if (!objeto(manifesto)) throw new Error("manifesto");
        for (const [chave, entrada] of Object.entries(manifesto)) {
          if (!CHAVE.test(chave)) { falhar("manifesto", "chave_invalida", undefined, ano); continue; }
          if (!objeto(entrada)) { falhar("manifesto", "entrada_invalida", chave, ano); continue; }
          if (SEM_ORIGINAL.has(String(entrada.status)) || entrada.r2_chave === null ||
              (typeof entrada.bytes === "number" && entrada.bytes > MAX_ORIGINAL)) continue;
          if (typeof entrada.sha256_original !== "string" || !HASH.test(entrada.sha256_original) ||
              typeof entrada.r2_chave !== "string" || typeof entrada.tipo !== "string" || !TIPOS.has(entrada.tipo) ||
              typeof entrada.trechos !== "number" || !Number.isSafeInteger(entrada.trechos) || entrada.trechos < 0) {
            falhar("manifesto", "entrada_invalida", chave, ano); continue;
          }
          if (vistos.has(chave)) { falhar("manifesto", "chave_repetida", chave, ano); continue; }
          vistos.add(chave);
          arquivos.push({ chave, ano, tipo: entrada.tipo, sha256_original: entrada.sha256_original,
            r2_chave: entrada.r2_chave, trechos: entrada.trechos });
        }
      } catch { falhar("manifesto", "leitura", undefined, ano); }
      if (chamadas >= 239 || Date.now() >= fim) break;
    }
    const ordem = amostraDeterministica(arquivos, resultado.data.slice(0, 10), arquivos.length);
    const amostra: Arquivo[] = [];
    // Confere a projeção antes de amostrar: NULL também significa envio omitido por tamanho.
    for (let i = 0; i < ordem.length && amostra.length < TAMANHO_AMOSTRA; i += 80) {
      const lote = ordem.slice(i, i + 80);
      const prazo = reservar();
      const linhas = await comPrazo(() => env.DB.prepare(
        `SELECT id, r2_chave FROM arquivos WHERE id IN (${lote.map(() => "?").join(",")}) AND r2_chave IS NOT NULL AND status NOT IN ('removido','duplicata','pendente_download')`,
      ).bind(...lote.map((a) => a.chave)).all<{ id: string; r2_chave: string }>(), prazo);
      const elegiveis = new Map(linhas.results.map((a) => [a.id, a.r2_chave]));
      for (const arquivo of lote) {
        if (elegiveis.has(arquivo.chave) && amostra.length < TAMANHO_AMOSTRA) {
          if (elegiveis.get(arquivo.chave) !== arquivo.r2_chave) falhar("d1", "r2_chave_divergente", arquivo.chave);
          amostra.push(arquivo);
        }
      }
    }
    const porCaminho = new Map<string, Arquivo[]>();
    for (const arquivo of amostra) {
      const caminho = `trechos/${arquivo.tipo}/${arquivo.ano}.jsonl`;
      const grupo = porCaminho.get(caminho) ?? [];
      grupo.push(arquivo);
      porCaminho.set(caminho, grupo);
    }
    for (const [caminho, grupo] of porCaminho) {
      const esperados = new Map<string, HashTrecho[]>(grupo.map((a) => [a.chave, []]));
      let trechosLidos = true;
      try {
        const texto = await raw(caminho, env.CRON_TEXTOS_BRANCH ?? "dados-textos", grupo.every((a) => a.trechos === 0));
        for (const linha of (texto ?? "").split("\n")) {
          if (!linha) continue;
          const trecho: unknown = JSON.parse(linha);
          if (!objeto(trecho) || typeof trecho.arquivo !== "string" || typeof trecho.id !== "string" ||
              !/^[0-9a-f]{16}$/.test(trecho.id) || typeof trecho.sha256 !== "string" || !HASH.test(trecho.sha256)) throw new Error("trecho");
          esperados.get(trecho.arquivo)?.push({ id: trecho.id, sha256: trecho.sha256 });
        }
      } catch { trechosLidos = false; }
      for (const arquivo of grupo) {
        resultado.amostra++;
        const antes = resultado.falhas.length;
        try {
          const prazo = Math.min(reservar(), Math.max(1, opcoes.prazoOriginalMs ?? 10_000));
          const hash = await comPrazo(async (sinal) => {
            const original = await env.ARQUIVOS.get(arquivo.r2_chave);
            if (!original) return null;
            if (sinal.aborted || original.size > MAX_ORIGINAL) {
              await original.body.cancel();
              throw new Error("original");
            }
            return hashOriginal(original, sinal);
          }, prazo);
          if (hash === null) falhar("r2", "ausente", arquivo.chave);
          else if (hash !== arquivo.sha256_original) falhar("r2", "hash_divergente", arquivo.chave);
        } catch { falhar("r2", "leitura", arquivo.chave); }
        if (!trechosLidos) falhar("trechos", "leitura", arquivo.chave);
        else {
          try {
            const prazo = reservar();
            const linhas = await comPrazo(() => env.DB.prepare("SELECT id, sha256 FROM trechos WHERE arquivo = ? ORDER BY id")
              .bind(arquivo.chave).all<HashTrecho>(), prazo);
            const esperado = esperados.get(arquivo.chave)!;
            const hashes = new Map(esperado.map((t) => [t.id, t.sha256]));
            if (esperado.length !== arquivo.trechos || hashes.size !== esperado.length || linhas.results.length !== esperado.length ||
                linhas.results.some((t) => hashes.get(t.id) !== t.sha256)) falhar("trechos", "hash_divergente", arquivo.chave);
          } catch { falhar("d1", "leitura", arquivo.chave); }
        }
        if (resultado.falhas.length === antes && !resultado.falhas.some((f) => f.chave === arquivo.chave)) resultado.ok++;
      }
    }
  } catch { falhar("cron", "leitura_ou_orcamento"); }
  try {
    await comPrazo(() => env.DB.prepare("INSERT OR REPLACE INTO verificacoes (data, amostra, ok, falhas_json) VALUES (?, ?, ?, ?)")
      .bind(resultado.data, resultado.amostra, resultado.ok, JSON.stringify(resultado.falhas)).all(), 10_000);
  } catch {
    // Sem D1 não há onde persistir a falha. Não registra mensagem, pilha ou dados do objeto.
    falhar("verificacoes", "gravacao");
  }
  return resultado;
}
