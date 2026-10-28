// Normalização da consulta, escape da sintaxe FTS5 e trecho destacado com <mark>.

/**
 * Forma da busca por palavras (contrato, seção 8.1), idêntica a `coletor.nuvem.fonte.normalizar_busca`:
 * NFD, sem marcas Mn, NFC e minúsculas ("Licença" -> "licenca").
 */
export function normalizar(s: string): string {
  return s.normalize("NFD").replace(/\p{Mn}/gu, "").normalize("NFC").toLowerCase();
}

const RE_CONTROLE = /[\p{Cc}\p{Cf}]/gu;
const RE_ALFANUMERICO = /[\p{L}\p{N}]/u;
const RE_PALAVRA = /[\p{L}\p{N}]+/gu;
const PALAVRAS_VAZIAS = new Set("de da do das dos a o as os e em no na nos nas para por com que um uma uns umas ao aos ou se".split(" "));
export const MAX_TERMOS = 10;

/**
 * Termos da consulta: a consulta normalizada dividida por espaços, sem repetição e só os que têm
 * ao menos uma letra ou um dígito (`*`, `(` ou `"` sozinhos não viram termo).
 */
export function termos(consulta: string): string[] {
  const saida: string[] = [];
  for (const parte of normalizar(consulta.replace(RE_CONTROLE, " ")).split(/\s+/u)) {
    if (parte !== "" && RE_ALFANUMERICO.test(parte) && !saida.includes(parte)) saida.push(parte);
  }
  return saida;
}

/**
 * Consulta FTS5 sem operadores do usuário: cada termo vira uma frase entre aspas, com as aspas internas
 * duplicadas; frases separadas por espaço exigem todos os termos (AND implícito). `OR`, `NEAR(`, `*`,
 * `col:` e parênteses ficam dentro das aspas e são só texto para o tokenizer.
 */
export function consultaFts(lista: string[]): string {
  return lista.map((t) => `"${t.replaceAll('"', '""')}"`).join(" ");
}

/** Palavras (só letras e dígitos) que o tokenizer extrai dos termos: são as destacadas no trecho. */
export function palavrasAlvo(lista: string[]): Set<string> {
  const alvos = new Set<string>();
  for (const t of lista) for (const m of t.matchAll(RE_PALAVRA)) alvos.add(m[0]);
  return alvos;
}

/** Mesma consulta para MATCH, embedding e cache: até dez palavras distintas, só uma curta. */
export function termosBusca(lista: string[]): { termos: string[]; truncada: boolean } {
  const saida: string[] = [];
  let curta = false;
  let truncada = false;
  for (const palavra of palavrasAlvo(lista)) {
    if (PALAVRAS_VAZIAS.has(palavra)) continue;
    const pequena = [...palavra].length < 3;
    if (saida.length >= MAX_TERMOS || (pequena && curta)) {
      truncada = true;
      continue;
    }
    saida.push(palavra);
    if (pequena) curta = true;
  }
  return { termos: saida, truncada };
}

const ESCAPES: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

export function escaparHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ESCAPES[c] ?? c);
}

export const TAMANHO_TRECHO = 320;
const CONTEXTO = 60;
const FOLGA = 30;
const RE_TOKEN_TEXTO = /[\p{L}\p{N}\p{M}]+/gu;
const RE_ESPACO = /\s/u;

interface Marca {
  ini: number;
  fim: number;
  palavra: string;
}

function marcas(texto: string, alvos: Set<string>): Marca[] {
  const saida: Marca[] = [];
  if (alvos.size === 0) return saida;
  for (const m of texto.matchAll(RE_TOKEN_TEXTO)) {
    const palavra = (normalizar(m[0]).match(RE_PALAVRA) ?? []).join("");
    const ini = m.index ?? 0;
    if (alvos.has(palavra)) saida.push({ ini, fim: ini + m[0].length, palavra });
  }
  return saida;
}

/** Não corta um par substituto UTF-16. */
function semCortarPar(texto: string, i: number): number {
  const c = texto.charCodeAt(i);
  return c >= 0xdc00 && c <= 0xdfff ? i + 1 : i;
}

function inicioJanela(texto: string, alvo: number): number {
  if (alvo <= 0) return 0;
  const limite = Math.min(texto.length, alvo + FOLGA);
  for (let i = alvo; i < limite; i++) if (RE_ESPACO.test(texto.charAt(i))) return i + 1;
  return semCortarPar(texto, alvo);
}

function fimJanela(texto: string, alvo: number): number {
  if (alvo >= texto.length) return texto.length;
  const limite = Math.max(0, alvo - FOLGA);
  for (let i = alvo; i > limite; i--) if (RE_ESPACO.test(texto.charAt(i))) return i;
  return semCortarPar(texto, alvo);
}

const compactar = (s: string): string => s.replace(/\s+/gu, " ");

/**
 * Trecho de até `tamanho` unidades do texto original (com acentos), em HTML escapado: só `<mark>` é
 * emitido, em volta das palavras cuja forma normalizada coincide com um termo. A janela é a que reúne
 * mais termos distintos (empate: a primeira); sem correspondência, o início do texto.
 */
export function destacar(texto: string, alvos: Set<string>, tamanho = TAMANHO_TRECHO): string {
  const ms = marcas(texto, alvos);
  let ini = 0;
  if (ms.length > 0) {
    let melhor = 0;
    let melhorQtd = -1;
    for (let i = 0; i < ms.length; i++) {
      const limite = ms[i]!.ini + tamanho - CONTEXTO;
      const vistas = new Set<string>();
      for (let j = i; j < ms.length && ms[j]!.fim <= limite; j++) vistas.add(ms[j]!.palavra);
      if (vistas.size > melhorQtd) {
        melhorQtd = vistas.size;
        melhor = i;
      }
    }
    ini = inicioJanela(texto, ms[melhor]!.ini - CONTEXTO);
  }
  const fim = Math.max(ini, fimJanela(texto, ini + tamanho));
  let html = "";
  let pos = ini;
  for (const m of ms) {
    if (m.ini < pos || m.fim > fim) continue;
    html += escaparHtml(compactar(texto.slice(pos, m.ini))) + "<mark>" + escaparHtml(texto.slice(m.ini, m.fim)) + "</mark>";
    pos = m.fim;
  }
  html = (html + escaparHtml(compactar(texto.slice(pos, fim)))).trim();
  if (ini > 0 && texto.slice(0, ini).trim() !== "") html = "… " + html;
  if (texto.slice(fim).trim() !== "") html += " …";
  return html;
}
