// Fixture de 30 documentos no D1 local (miniflare), originais no R2 local e Vectorize/AI simulados.
import { createExecutionContext, env, waitOnExecutionContext } from "cloudflare:test";
import type { CorrespondenciaVetor, Env, OpcoesConsultaVetor } from "../src/ambiente";
import worker from "../src/index";
import { chaveR2 } from "../src/original";
import { normalizar } from "../src/texto";

export const sha = (n: number): string => `${"ab".repeat(31)}${n.toString(16).padStart(2, "0")}`;
export const idTrecho = (n: number): string => n.toString(16).padStart(16, "0");
export const URL_SISCAM = "https://consultaniteroi.siscam.com.br/DetalhesDocumentos.aspx?IdDocumento=";
export const GUID_ATA = ["0f0e0d0c-0b0a-4908-8706-050403020100", "1f1e1d1c-1b1a-4918-9716-151413121110"];

interface Documento {
  id: string;
  tipo: string;
  numero: string;
  ano: number;
  ementa: string;
  legislatura: string;
  pl?: string;
  autores: [string, string][];
}

interface Arquivo {
  id: string;
  n: number;
  formato: string;
  status: string;
  ocr: number;
  confianca: number | null;
  documentos: string[];
  /** Trechos (texto) gravados no documento principal. */
  trechos: string[];
  principal: string;
}

const TEMAS = ["leitura", "ciclismo", "xadrez", "música", "teatro", "dança", "vôlei"];

function montar(): { documentos: Documento[]; arquivos: Arquivo[] } {
  const documentos: Documento[] = [];
  const arquivos: Arquivo[] = [];
  const doc = (d: Documento): void => void documentos.push(d);
  const arq = (a: Arquivo): void => void arquivos.push(a);

  doc({ id: "doc:101", tipo: "pl", numero: "1/2021", ano: 2021, legislatura: "2021-2024",
    ementa: "Institui o programa Tratamento Fora de Domicílio no município.", autores: [["ana-souza", "autor"]] });
  arq({ id: "siscam:1001", n: 1, formato: "pdf", status: "ok", ocr: 0, confianca: null, documentos: ["doc:101"],
    principal: "doc:101",
    trechos: ["Fica instituído o Tratamento Fora de Domicílio (TFD) para pacientes da rede municipal de saúde de Niterói."] });
  doc({ id: "doc:102", tipo: "pl", numero: "2/2022", ano: 2022, legislatura: "2021-2024",
    ementa: "Dispõe sobre a licença ambiental simplificada.", autores: [["bruno-lima", "autor"]] });
  arq({ id: "siscam:1002", n: 2, formato: "docx", status: "ok", ocr: 0, confianca: null, documentos: ["doc:102"],
    principal: "doc:102",
    trechos: ["A LICENÇA AMBIENTAL simplificada será concedida pela secretaria competente em até trinta dias."] });
  doc({ id: "doc:103", tipo: "pl", numero: "3/2023", ano: 2023, legislatura: "2021-2024",
    ementa: "Cria a Praça da Juventude.", autores: [["carla-dias", "autor"]] });
  arq({ id: "siscam:1003", n: 3, formato: "pdf", status: "ocr_baixa_confianca", ocr: 1, confianca: 54.5,
    documentos: ["doc:103"], principal: "doc:103",
    trechos: ["Fica criada a Praça da Juventude <script>alert(1)</script> no bairro do Fonseca, com quadra & pista."] });
  TEMAS.forEach((tema, i) => {
    const n = 104 + i;
    const ano = 2021 + (i % 4);
    doc({ id: `doc:${n}`, tipo: "pl", numero: `${n - 100}/${ano}`, ano, legislatura: "2021-2024",
      ementa: `Institui a semana municipal de ${tema}.`, autores: [["bruno-lima", "autor"], ["davi-rocha", "coautor"]] });
    arq({ id: `siscam:${1000 + n - 100}`, n: n - 100, formato: "docx", status: "ok", ocr: 0, confianca: null,
      documentos: [`doc:${n}`], principal: `doc:${n}`,
      trechos: [`Fica incluída no calendário oficial de Niterói a semana municipal de ${tema}.`,
        `A semana de ${tema} será celebrada anualmente.`] });
  });
  // Substitutivos: o 201 tem um arquivo citado só por ele, cujos trechos ficam no PL (principal).
  doc({ id: "doc:201", tipo: "substitutivo", numero: "1", ano: 2021, legislatura: "2021-2024", pl: "doc:101",
    ementa: "Institui o programa Tratamento Fora de Domicílio no município.",
    autores: [["ana-souza", "autor"], ["davi-rocha", "coautor"]] });
  arq({ id: "siscam:1201", n: 21, formato: "doc", status: "ok", ocr: 0, confianca: null, documentos: ["doc:201"],
    principal: "doc:101", trechos: ["Substitutivo: o transporte intermunicipal integra o tratamento."] });
  doc({ id: "doc:202", tipo: "substitutivo", numero: "1", ano: 2022, legislatura: "2021-2024", pl: "doc:102",
    ementa: "Dispõe sobre a licença ambiental simplificada.", autores: [["bruno-lima", "autor"]] });
  for (let i = 0; i < 6; i++) {
    const n = 301 + i;
    doc({ id: `doc:${n}`, tipo: "requerimento", numero: `${i + 1}/2025`, ano: 2025, legislatura: "2025-2028",
      ementa: `Requer informações sobre o calendário de obras do lote ${i + 1}.`,
      autores: [[i % 2 === 0 ? "davi-rocha" : "ana-souza", "autor"]] });
    arq({ id: `siscam:${1301 + i}`, n: 31 + i, formato: "pdf", status: "ok", ocr: 0, confianca: null,
      documentos: [`doc:${n}`], principal: `doc:${n}`,
      trechos: [`Requer à Secretaria o calendário de obras do lote ${i + 1}, com prazos e custos.`] });
  }
  for (let i = 0; i < 4; i++) {
    doc({ id: `doc:${401 + i}`, tipo: "indicacao", numero: `${i + 1}/2025`, ano: 2025, legislatura: "2025-2028",
      ementa: `Indica a poda de árvores na Rua ${["Alfa", "Beta", "Gama", "Delta"][i]}.`, autores: [["carla-dias", "autor"]] });
  }
  for (let i = 0; i < 3; i++) {
    doc({ id: `doc:${501 + i}`, tipo: "mocao", numero: `${i + 1}/2025`, ano: 2025, legislatura: "2025-2028",
      ementa: `Moção de aplauso à escola ${["Norte", "Sul", "Leste"][i]}.`, autores: [["ana-souza", "autor"]] });
  }
  for (let i = 0; i < 2; i++) {
    doc({ id: `doc:${601 + i}`, tipo: "pdl", numero: `${i + 1}/2023`, ano: 2023, legislatura: "2021-2024",
      ementa: `Concede o título de cidadão niteroiense ${i + 1}.`, autores: [["bruno-lima", "autor"]] });
    arq({ id: `siscam:${1601 + i}`, n: 61 + i, formato: "pdf", status: "ok", ocr: 0, confianca: null,
      documentos: [`doc:${601 + i}`], principal: `doc:${601 + i}`,
      trechos: [`Fica concedido o título de cidadão niteroiense ao homenageado número ${i + 1}.`] });
  }
  doc({ id: "doc:701", tipo: "resolucao", numero: "1/2022", ano: 2022, legislatura: "2021-2024",
    ementa: "Altera o regimento interno.", autores: [["carla-dias", "autor"]] });
  arq({ id: "siscam:1701", n: 71, formato: "rtf", status: "ok", ocr: 0, confianca: null, documentos: ["doc:701"],
    principal: "doc:701", trechos: ["O regimento interno passa a vigorar com a seguinte redação."] });
  for (let i = 0; i < 2; i++) {
    doc({ id: `sessao:${9001 + i}`, tipo: "ata", numero: `${i + 1}`, ano: 2024, legislatura: "2021-2024",
      ementa: `Sessão ordinária ${i + 1}`, autores: [] });
    arq({ id: `sessao:${GUID_ATA[i]}`, n: 91 + i, formato: "docx", status: "ok", ocr: 0, confianca: null,
      documentos: [`sessao:${9001 + i}`], principal: `sessao:${9001 + i}`,
      trechos: [`Ata da sessão ordinária ${i + 1}: presentes os vereadores, aprovada a pauta.`] });
  }
  return { documentos, arquivos };
}

export const FIXTURE = montar();

export interface TrechoFixture {
  id: string;
  documento: string;
  arquivo: string;
  texto: string;
  tipo: string;
  ano: number;
  legislatura: string;
}

export const TRECHOS: TrechoFixture[] = (() => {
  const saida: TrechoFixture[] = [];
  let n = 1;
  for (const a of FIXTURE.arquivos) {
    const principal = FIXTURE.documentos.find((d) => d.id === a.principal)!;
    for (const texto of a.trechos) {
      saida.push({ id: idTrecho(n++), documento: a.principal, arquivo: a.id, texto, tipo: principal.tipo,
        ano: principal.ano, legislatura: principal.legislatura });
    }
  }
  return saida;
})();

export const trechoDe = (arquivo: string, posicao = 0): TrechoFixture =>
  TRECHOS.filter((t) => t.arquivo === arquivo)[posicao]!;

let sequencia = 0;

/** Zera e recarrega o D1 local; cada carga tem `estado_indice.data` próprio (chaves de cache novas). */
export async function carregar(opcoes: { semEstado?: boolean } = {}): Promise<void> {
  const db = env.DB;
  const tabelas = ["documentos", "autoria", "pessoas", "arquivos", "arquivo_documento", "trechos", "trechos_fts",
    "trechos_indexados", "remocoes", "estado_indice", "verificacoes"];
  const inst = tabelas.map((t) => db.prepare(`DELETE FROM ${t}`));
  for (const [slug, nome, partido] of [["ana-souza", "Ana Souza", "PA"], ["bruno-lima", "Bruno Lima", "PB"],
    ["carla-dias", "Carla Dias", null], ["davi-rocha", "Davi Rocha", "PA"]] as const) {
    inst.push(db.prepare("INSERT INTO pessoas (slug, nome, partido_atual) VALUES (?, ?, ?)").bind(slug, nome, partido));
  }
  for (const d of FIXTURE.documentos) {
    inst.push(db.prepare(
      "INSERT INTO documentos (id, tipo, numero, ano, data, ementa, url, legislatura, pl) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
    ).bind(d.id, d.tipo, d.numero, d.ano, `${d.ano}-03-01`, d.ementa,
      d.id.startsWith("doc:") ? URL_SISCAM + d.id.slice(4) : "https://consultaniteroi.siscam.com.br/DetalhesSessao.aspx?Id=1",
      d.legislatura, d.pl ?? null));
    for (const [slug, papel] of d.autores) {
      inst.push(db.prepare("INSERT INTO autoria (documento, slug, papel) VALUES (?, ?, ?)").bind(d.id, slug, papel));
    }
  }
  for (const a of FIXTURE.arquivos) {
    inst.push(db.prepare(
      "INSERT INTO arquivos (id, sha256, formato, status, ocr, confianca, r2_chave) VALUES (?, ?, ?, ?, ?, ?, ?)",
    ).bind(a.id, sha(a.n), a.formato, a.status, a.ocr, a.confianca, chaveR2(sha(a.n))));
    for (const d of a.documentos) {
      inst.push(db.prepare("INSERT INTO arquivo_documento (arquivo, documento) VALUES (?, ?)").bind(a.id, d));
    }
  }
  TRECHOS.forEach((t, i) => {
    inst.push(db.prepare("INSERT INTO trechos (id, documento, arquivo, posicao, texto, sha256) VALUES (?, ?, ?, ?, ?, ?)")
      .bind(t.id, t.documento, t.arquivo, 0, t.texto, sha(200 + i)));
    // rowid do FTS propositalmente diferente do rowid de `trechos`: a junção é sempre pelo id.
    inst.push(db.prepare("INSERT INTO trechos_fts (rowid, id, texto_norm) VALUES (?, ?, ?)")
      .bind(100000 - i * 7, t.id, normalizar(t.texto)));
  });
  if (!opcoes.semEstado) {
    sequencia += 1;
    inst.push(db.prepare(
      'INSERT INTO estado_indice (id, versao, "commit", sha256_manifestos, total, sha256_conjunto, modelo, versao_trechos, data) ' +
        "VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)",
    ).bind("2026.10.27", "c0ffee1", "m".repeat(64), TRECHOS.length, "s".repeat(64), "@cf/baai/bge-m3", "2",
      `2026-10-27T00:00:00.${String(sequencia).padStart(6, "0")}Z`));
  }
  await db.batch(inst);
  for (const a of FIXTURE.arquivos.slice(0, 3)) {
    await env.ARQUIVOS.put(chaveR2(sha(a.n)), `conteúdo do original ${a.id}`);
  }
}

// ---- simulações (Vectorize, AI, Rate Limiting, Analytics Engine)

export interface Vetor {
  id: string;
  metadata: Record<string, unknown>;
}

export const VETORES: Vetor[] = [
  ...TRECHOS.map((t) => ({ id: t.id, metadata: { tipo: t.tipo, ano: t.ano, legislatura: t.legislatura, documento: t.documento } })),
  ...FIXTURE.documentos.filter((d) => d.tipo === "indicacao" || d.tipo === "mocao")
    .map((d) => ({ id: `ementa:${d.id}`, metadata: { tipo: d.tipo, ano: d.ano, legislatura: d.legislatura, documento: d.id } })),
];

export class VetoresFalsos {
  chamadas: { vetor: number[]; opcoes: OpcoesConsultaVetor }[] = [];
  constructor(public ordem: string[], public falhar = false) {}

  async query(vetor: number[], opcoes: OpcoesConsultaVetor): Promise<{ matches: CorrespondenciaVetor[] }> {
    this.chamadas.push({ vetor, opcoes });
    if (this.falhar) throw new Error("Vectorize indisponível");
    const filtro = (opcoes.filter ?? {}) as Record<string, { $eq: unknown }>;
    const matches = this.ordem
      // Id desconhecido (vetor sem linha no D1) volta sem metadados: só passa sem filtro.
      .map((id): Vetor => VETORES.find((v) => v.id === id) ?? { id, metadata: {} })
      .filter((v) => Object.entries(filtro).every(([k, f]) => v.metadata[k] === f.$eq))
      .slice(0, opcoes.topK)
      .map((v, i) => ({ id: v.id, score: 0.9 - i * 0.01, metadata: { tipo: v.metadata.tipo } }));
    return { matches };
  }
}

export class AiFalsa {
  chamadas: { modelo: string; entrada: Record<string, unknown> }[] = [];
  constructor(public resposta: unknown = { shape: [1, 1024], data: [Array(1024).fill(0.01)] }) {}

  async run(modelo: string, entrada: Record<string, unknown>): Promise<unknown> {
    this.chamadas.push({ modelo, entrada });
    return this.resposta;
  }
}

export class LimiteFalso {
  chaves: string[] = [];
  constructor(public permitir = true) {}

  async limit(opcoes: { key: string }): Promise<{ success: boolean }> {
    this.chaves.push(opcoes.key);
    return { success: this.permitir };
  }
}

export class MetricasFalsas {
  pontos: unknown[] = [];

  writeDataPoint(ponto: unknown): void {
    this.pontos.push(ponto);
  }
}

export function criarEnv(extra: Partial<Env> = {}): Env {
  return {
    ...(env as unknown as Env),
    AI: new AiFalsa(),
    VETORES: new VetoresFalsos(VETORES.map((v) => v.id)),
    LIMITE: new LimiteFalso(),
    METRICAS: new MetricasFalsas(),
    ...extra,
  };
}

export async function pedir(caminho: string, init: RequestInit = {}, e: Env = criarEnv()): Promise<Response> {
  const ctx = createExecutionContext();
  const r = await worker.fetch(new Request(`https://api.teste${caminho}`, init), e, ctx);
  await waitOnExecutionContext(ctx);
  return r;
}

export async function buscarJson(consulta: Record<string, string>, e: Env = criarEnv(), init: RequestInit = {}) {
  const r = await pedir(`/api/busca?${new URLSearchParams(consulta).toString()}`, init, e);
  return { r, corpo: (await r.json()) as Record<string, any> };
}
