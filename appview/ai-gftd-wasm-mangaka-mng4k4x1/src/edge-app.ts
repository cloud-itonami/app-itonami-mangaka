// mangaka — CF-Worker-only ClojureScript EDGE edition (phase 4 of the animeka template).
//
// Lean createWorkerExport Worker: TS shell owns all async IO; the pure cljs SSoT
// (../js/mangaka.js, shadow-cljs :esm of mangaka.worker-api → mangaka.core, in
// ../../clj-edge) builds the kotoba tx/query EDN + the single-table D1 rows
// (vertex_mangaka). Domain writes DUAL-WRITE kotoba Datomic (primary) + D1
// MANGAKA_DB (shadow). No k8s pod.
//
// Distinct from the JVM langgraph reference (../../clj). Deploy via
// wrangler.worker.jsonc (main: src/edge-app.ts), isolated from the project's
// existing wrangler.jsonc. NSIDs: ai.gftd.mangaka.*

import {
  asAgentTool, createWorkerExport, nsid, withCapabilityTags,
  type ComAtprotoSyncSubscribeReposCommit,
} from "@gftd/magatama-host-sdk";
import * as M from "../js/mangaka.js";

type Env = {
  MANGAKA_DB?: D1Database;
  MANGAKA_APP_DID?: string;
  KOTOBA_BACKEND_URL?: string;
  KOTOBA_DATOMIC_NSID?: string;
  KOTOBA_GRAPH?: string;
  KOTOBA_BEARER?: string;
  COMFYUI_URL?: string;
  COMFYUI_API_KEY?: string;
  // CACHE_R2 (ai-gftd-cache) binding was removed from wrangler.worker.jsonc
  // (GFTD prune, 2026-11). Kept optional so blobPut's no-cache path stays
  // type-checked if a replacement cache binding is added later.
  CACHE_R2?: R2Bucket;
};

function toHex(b: Uint8Array): string { return Array.from(b, (x) => x.toString(16).padStart(2, "0")).join(""); }
type Render = { imageB64: string; mime: string; source: string; seed: number };
function stubRender(spec: any): Render {
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' width='${spec.width ?? 832}' height='${spec.height ?? 1216}'>` +
    `<rect width='100%' height='100%' fill='#1b1d24'/><text x='16' y='40' fill='#8aa0c0' font-size='14'>mangaka panel (stub)</text>` +
    `<text x='16' y='66' fill='#5e6b82' font-size='11'>${String(spec.prompt ?? "").slice(0, 44)}</text></svg>`;
  return { imageB64: btoa(svg), mime: "image/svg+xml", source: "stub", seed: spec.seed ?? 0 };
}
async function comfyRender(env: Env, spec: any): Promise<Render> {
  const base = env.COMFYUI_URL?.replace(/\/+$/, "");
  if (!base || !env.COMFYUI_API_KEY) return stubRender(spec);
  try {
    const r = await fetch(`${base}/v1/images/generations`, {
      method: "POST", headers: { "content-type": "application/json", authorization: `Bearer ${env.COMFYUI_API_KEY}` },
      body: JSON.stringify({ prompt: spec.prompt, n: 1, size: `${spec.width}x${spec.height}`, response_format: "b64_json", seed: spec.seed }),
    });
    if (!r.ok) return stubRender(spec);
    const j = await r.json().catch(() => ({} as any));
    const b64 = j?.data?.[0]?.b64_json;
    return b64 ? { imageB64: b64, mime: "image/png", source: "gateway", seed: spec.seed ?? 0 } : stubRender(spec);
  } catch (e) { console.warn("[mangaka] comfy failed:", e); return stubRender(spec); }
}
// No-cache path: the CACHE_R2 / ai-gftd-cache R2 binding was removed from
// wrangler.worker.jsonc (GFTD prune, 2026-11), so env.CACHE_R2 is absent in
// production and this returns null. Callers must tolerate image-key /
// image-url = null (hGeneratePanel does). The replacement (yataverse ingest
// vs commit-pin raw) is undecided, so blobPut is kept as a no-op rather than
// deleted. Do not re-add an R2 binding here without a new decision.
async function blobPut(env: Env, b64: string, mime: string): Promise<string | null> {
  if (!env.CACHE_R2) return null;
  try {
    const bin = atob(b64); const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    const key = "sha256-" + toHex(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)));
    await env.CACHE_R2.put(key, bytes, { httpMetadata: { contentType: mime } });
    return key;
  } catch (e) { console.warn("[mangaka] R2 put failed:", e); return null; }
}

const APP_DID = (env: Env) => env.MANGAKA_APP_DID ?? "did:web:mangaka.gftd.ai";
const decode = (b: Uint8Array): any => JSON.parse(new TextDecoder().decode(b) || "{}");
const nowISO = (): string => new Date().toISOString();

async function sha256Bytes(s: string): Promise<Uint8Array> {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s)));
}
const B32 = "abcdefghijklmnopqrstuvwxyz234567";
function base32lower(bytes: Uint8Array): string {
  let bits = 0, value = 0, out = "";
  for (const b of bytes) { value = (value << 8) | b; bits += 8; while (bits >= 5) { out += B32[(value >>> (bits - 5)) & 31]; bits -= 5; } }
  if (bits > 0) out += B32[(value << (5 - bits)) & 31];
  return out;
}
let _cid: string | null = null;
async function graphCid(env: Env): Promise<string> {
  if (_cid) return _cid;
  const label = env.KOTOBA_GRAPH ?? "mangaka-v1";
  if (/^b[a-z2-7]{58,80}$/.test(label)) { _cid = label; return _cid; }
  const d = await sha256Bytes(label);
  const cid = new Uint8Array(4 + d.length); cid.set([0x01, 0x71, 0x12, 0x20], 0); cid.set(d, 4);
  _cid = "b" + base32lower(cid); return _cid;
}

async function kotobaXrpc(env: Env, method: string, body: Record<string, unknown>): Promise<any> {
  const base = (env.KOTOBA_BACKEND_URL ?? "https://kotobase.net").replace(/\/+$/, "");
  const ns = env.KOTOBA_DATOMIC_NSID ?? "ai.gftd.apps.kotobase.datomic";
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (env.KOTOBA_BEARER) headers.authorization = `Bearer ${env.KOTOBA_BEARER}`;
  const r = await fetch(`${base}/xrpc/${ns}.${method}`, { method: "POST", headers, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`kotoba ${method}: ${r.status}`);
  return r.json().catch(() => ({}));
}
async function dmTransact(env: Env, txEdn: string) { return kotobaXrpc(env, "transact", { graph: await graphCid(env), tx_edn: txEdn }); }
async function dmQuery(env: Env, queryEdn: string): Promise<any[]> {
  const res = await kotobaXrpc(env, "q", { graph: await graphCid(env), query_edn: queryEdn });
  return (res?.rows_edn ?? res?.rows ?? []) as any[];
}
async function dmPull(env: Env, entityEdn: string, patternEdn: string): Promise<string | null> {
  const res = await kotobaXrpc(env, "pull", { graph: await graphCid(env), entity: entityEdn, pattern_edn: patternEdn });
  return (res?.entity_edn ?? res?.entity ?? null) as string | null;
}
async function d1Exec(env: Env, row: { sql: string; params: any[] } | null): Promise<void> {
  if (!row || !env.MANGAKA_DB) return;
  try { await env.MANGAKA_DB.prepare(row.sql).bind(...row.params).run(); }
  catch (e) { console.warn("[mangaka] D1 dual-write shadow failed (continuing):", e); }
}
function pageArgs(b: any) { return { offset: Math.max(0, Number(b.offset ?? 0) | 0), limit: Math.min(100, Math.max(1, Number(b.limit ?? 100) | 0)) }; }

async function hCreateCharacter(env: Env, body: Uint8Array): Promise<unknown> {
  const b = decode(body); if (!b.name) return { error: "name is required" };
  const id = (b.id && String(b.id)) || `ch-${M.slug(b.name)}`;
  const input = { id, name: b.name, status: b.status, "created-at": nowISO() };
  await dmTransact(env, M.characterToTxEdn(input));
  await d1Exec(env, M.characterToD1(APP_DID(env), input));
  return { id, uri: M.vertexId("character", id), name: b.name, status: b.status ?? "active" };
}
async function hListCharacters(env: Env, body: Uint8Array): Promise<unknown> {
  const b = decode(body); const { offset, limit } = pageArgs(b);
  return M.paginate(M.shapePullRows(await dmQuery(env, M.qListCharacters())), "characters", offset, limit);
}
async function hGetCharacter(env: Env, body: Uint8Array): Promise<unknown> {
  const b = decode(body); const id = b.id; if (!id) return { error: "id is required" };
  return M.pulledEntity(await dmPull(env, M.lookupRef("character", id), M.entityPullEdn)) ?? { error: "not found" };
}
async function hCreateWork(env: Env, body: Uint8Array): Promise<unknown> {
  const b = decode(body); if (!b.title) return { error: "title is required" };
  const id = (b.id && String(b.id)) || `work-${M.slug(b.title)}`;
  const input = { id, title: b.title, status: b.status, "created-at": nowISO() };
  await dmTransact(env, M.workToTxEdn(input));
  await d1Exec(env, M.workToD1(APP_DID(env), input));
  return { id, uri: M.vertexId("work", id), title: b.title, status: b.status ?? "draft" };
}
async function hListWorks(env: Env, body: Uint8Array): Promise<unknown> {
  const b = decode(body); const { offset, limit } = pageArgs(b);
  return M.paginate(M.shapePullRows(await dmQuery(env, M.qListWorks())), "works", offset, limit);
}

async function hCreateEnvironment(env: Env, body: Uint8Array): Promise<unknown> {
  const b = decode(body); if (!b.name) return { error: "name is required" };
  const id = (b.id && String(b.id)) || `env-${M.slug(b.name)}`;
  const input = { id, name: b.name, status: b.status, "created-at": nowISO() };
  await dmTransact(env, M.environmentToTxEdn(input));
  await d1Exec(env, M.environmentToD1(APP_DID(env), input));
  return { id, uri: M.vertexId("environment", id), name: b.name };
}
async function hListEnvironments(env: Env, body: Uint8Array): Promise<unknown> {
  const b = decode(body); const { offset, limit } = pageArgs(b);
  return M.paginate(M.shapePullRows(await dmQuery(env, M.qListEnvironments())), "environments", offset, limit);
}
async function hAddChapter(env: Env, body: Uint8Array): Promise<unknown> {
  const b = decode(body); const workId = b["work-id"] ?? b.workId; if (!workId) return { error: "work-id is required" };
  const id = (b.id && String(b.id)) || M.genRkey("ch");
  const input = { id, "work-id": workId, title: b.title, status: b.status, "created-at": nowISO() };
  await dmTransact(env, M.chapterToTxEdn(input));
  await d1Exec(env, M.chapterToD1(APP_DID(env), input));
  return { id, uri: M.vertexId("chapter", id), "work-id": workId, title: b.title };
}
async function hListChapters(env: Env, body: Uint8Array): Promise<unknown> {
  const b = decode(body); const workId = b["work-id"] ?? b.workId; if (!workId) return { error: "work-id is required" };
  const { offset, limit } = pageArgs(b);
  return M.paginate(M.shapePullRows(await dmQuery(env, M.qChaptersForWork(workId))), "chapters", offset, limit);
}
async function hAddPage(env: Env, body: Uint8Array): Promise<unknown> {
  const b = decode(body); const chapterId = b["chapter-id"] ?? b.chapterId; if (!chapterId) return { error: "chapter-id is required" };
  const pn = Number(b["page-number"] ?? 0) | 0;
  const id = (b.id && String(b.id)) || `${chapterId}:p${pn}`;
  const input = { id, "chapter-id": chapterId, "page-number": pn, status: b.status, "created-at": nowISO() };
  await dmTransact(env, M.pageToTxEdn(input));
  await d1Exec(env, M.pageToD1(APP_DID(env), input));
  return { id, uri: M.vertexId("page", id), "chapter-id": chapterId, "page-number": pn };
}
async function hListPages(env: Env, body: Uint8Array): Promise<unknown> {
  const b = decode(body); const chapterId = b["chapter-id"] ?? b.chapterId; if (!chapterId) return { error: "chapter-id is required" };
  const { offset, limit } = pageArgs(b);
  return M.paginate(M.shapePullRows(await dmQuery(env, M.qPagesForChapter(chapterId))), "pages", offset, limit);
}
async function hCreatePanel(env: Env, body: Uint8Array): Promise<unknown> {
  const b = decode(body); const pageId = b["page-id"] ?? b.pageId; if (!pageId) return { error: "page-id is required" };
  const pn = Number(b["panel-number"] ?? 0) | 0;
  const id = (b.id && String(b.id)) || `${pageId}:n${pn}`;
  const input = { id, "page-id": pageId, "panel-number": pn, status: b.status, "created-at": nowISO() };
  await dmTransact(env, M.panelToTxEdn(input));
  await d1Exec(env, M.panelToD1(APP_DID(env), input));
  return { id, uri: M.vertexId("panel", id), "page-id": pageId, "panel-number": pn };
}
async function hListPanels(env: Env, body: Uint8Array): Promise<unknown> {
  const b = decode(body); const pageId = b["page-id"] ?? b.pageId; if (!pageId) return { error: "page-id is required" };
  const { offset, limit } = pageArgs(b);
  return M.paginate(M.shapePullRows(await dmQuery(env, M.qPanelsForPage(pageId))), "panels", offset, limit);
}

async function hGeneratePanel(env: Env, body: Uint8Array): Promise<unknown> {
  const b = decode(body); const pageId = b["page-id"] ?? b.pageId; if (!pageId) return { error: "page-id is required" };
  const pn = Number(b["panel-number"] ?? 0) | 0;
  const id = (b.id && String(b.id)) || `${pageId}:n${pn}`;
  const spec = { prompt: b.prompt ?? "manga panel, monochrome, screentone", width: 832, height: 1216, seed: Number(b.seed) || 0 };
  const render = await comfyRender(env, spec);
  const imageKey = await blobPut(env, render.imageB64, render.mime);
  const input = { id, "page-id": pageId, "panel-number": pn, prompt: spec.prompt, seed: render.seed,
                  "image-key": imageKey, status: "rendered", "created-at": nowISO() };
  await dmTransact(env, M.panelToTxEdn(input));
  await d1Exec(env, M.panelToD1(APP_DID(env), input));
  return { id, uri: M.vertexId("panel", id), "page-id": pageId, "panel-number": pn,
           "image-key": imageKey, "image-url": imageKey ? `/blob/${imageKey}` : null, source: render.source };
}

function hOnCommit(_c: ComAtprotoSyncSubscribeReposCommit): void { /* social only (ADR-0036) */ }

export default createWorkerExport((sdk) => {
  const env = sdk.env as unknown as Env;
  const cmd = (n: string, h: (e: Env, b: Uint8Array) => Promise<unknown>, desc: string, ...tags: string[]) =>
    sdk.app.command(nsid(n), (_c, b) => h(env, b), asAgentTool(desc), withCapabilityTags(...tags));
  cmd("ai.gftd.mangaka.createCharacter", hCreateCharacter, "Create a manga character", "write", "character");
  cmd("ai.gftd.mangaka.listCharacters", hListCharacters, "List characters", "query", "character");
  cmd("ai.gftd.mangaka.getCharacter", hGetCharacter, "Get a character by id", "query", "character");
  cmd("ai.gftd.mangaka.createWork", hCreateWork, "Create a manga work", "write", "work");
  cmd("ai.gftd.mangaka.listWorks", hListWorks, "List works", "query", "work");
  cmd("ai.gftd.mangaka.createEnvironment", hCreateEnvironment, "Create an environment/scene", "write", "environment");
  cmd("ai.gftd.mangaka.listEnvironments", hListEnvironments, "List environments", "query", "environment");
  cmd("ai.gftd.mangaka.addChapter", hAddChapter, "Add a chapter to a work", "write", "chapter");
  cmd("ai.gftd.mangaka.listChapters", hListChapters, "List a work's chapters", "query", "chapter");
  cmd("ai.gftd.mangaka.addPage", hAddPage, "Add a page to a chapter", "write", "page");
  cmd("ai.gftd.mangaka.listPages", hListPages, "List a chapter's pages", "query", "page");
  cmd("ai.gftd.mangaka.createPanel", hCreatePanel, "Create a panel on a page", "write", "panel");
  cmd("ai.gftd.mangaka.listPanels", hListPanels, "List a page's panels", "query", "panel");
  cmd("ai.gftd.mangaka.generatePanel", hGeneratePanel, "Render a panel image (ComfyUI → R2)", "write", "panel");
  sdk.app.command(nsid("ai.gftd.mangaka.health"), () => ({ status: "ok", app: "mangaka", impl: "cljs-edge" }),
    asAgentTool("Health"), withCapabilityTags("query"));
  sdk.app.onCommit(hOnCommit);
});
