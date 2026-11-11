/**
 * mangaka-reader — read-only public manga reader.
 *
 * Routes:
 *   GET /                 → list works (作品) from D1
 *   GET /work/:rkey       → reader: 作品 title + author + 作者/シリーズ + all pages
 *   GET /img/:key         → page image from R2 (ai-gftd-cdn, blobs/mng4k4x1.gftd.ai/<key>)
 *
 * Data: D1 `vertex_mangaka` (kind=work|chapter|page; linkage + blobKey in props JSON).
 * Images: R2 binding (no SigV4). Standalone — independent of the canvas editor worker.
 */

interface Env {
  MANGAKA_DB: D1Database;
  CDN: R2Bucket;
}

const BLOB_PREFIX = "blobs/mng4k4x1.gftd.ai/";

const esc = (s: unknown): string =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c] as string));

function html(body: string, title: string): Response {
  const doc = `<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(title)}</title>
<style>
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:#0c0e14;color:#e8eaf0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Hiragino Sans",Meiryo,sans-serif;line-height:1.6}
header{padding:20px 24px;border-bottom:1px solid #232838;position:sticky;top:0;background:rgba(12,14,20,.92);backdrop-filter:blur(8px);z-index:10}
header a{color:#7fb0ff;text-decoration:none}
h1{margin:0;font-size:20px}
.sub{color:#9aa3b8;font-size:13px;margin-top:4px}
main{max-width:860px;margin:0 auto;padding:24px}
.card{display:block;padding:18px 20px;margin:12px 0;background:#151926;border:1px solid #232838;border-radius:12px;text-decoration:none;color:inherit;transition:border-color .15s}
.card:hover{border-color:#3a64b0}
.card h2{margin:0 0 6px;font-size:17px}
.meta{color:#9aa3b8;font-size:13px}
.pages{display:flex;flex-direction:column;align-items:center;gap:10px;margin-top:16px}
.pages img{width:100%;max-width:760px;height:auto;border-radius:6px;background:#000;box-shadow:0 2px 12px rgba(0,0,0,.4)}
.pageno{color:#6b7488;font-size:12px;margin-top:6px;text-align:center}
footer{color:#6b7488;font-size:12px;text-align:center;padding:32px 16px}
</style></head><body>${body}<footer>mangaka.gftd.ai · AI-generated manga · 公開: D1 + R2 (RunPod不使用 / Tailscale生成)</footer></body></html>`;
  return new Response(doc, { headers: { "content-type": "text/html; charset=utf-8" } });
}

function parseProps(p: unknown): Record<string, any> {
  try { return JSON.parse(String(p ?? "{}")); } catch { return {}; }
}

async function renderIndex(env: Env): Promise<Response> {
  const { results } = await env.MANGAKA_DB.prepare(
    "SELECT rkey, title, name, props FROM vertex_mangaka WHERE kind='work' ORDER BY created_at DESC LIMIT 200"
  ).all();
  const works = (results ?? []) as any[];
  const cards = works.length
    ? works.map((w) => {
        const pr = parseProps(w.props);
        return `<a class="card" href="/work/${encodeURIComponent(w.rkey)}">
          <h2>${esc(w.title || w.name || w.rkey)}</h2>
          <div class="meta">作者: ${esc(pr.author || "—")} ・ シリーズ: ${esc(pr.series || "—")} ・ ${esc(pr.pageCount ?? "?")}ページ ・ ${esc(pr.genre || "")}</div>
        </a>`;
      }).join("")
    : `<p class="meta">まだ公開作品がありません。</p>`;
  return html(`<header><h1>Mangaka 作品一覧</h1><div class="sub">作者・作品・シリーズごとの公開ビューア</div></header><main>${cards}</main>`, "Mangaka — 作品一覧");
}

async function renderWork(env: Env, rkey: string): Promise<Response> {
  const work = (await env.MANGAKA_DB.prepare(
    "SELECT rkey, title, name, props FROM vertex_mangaka WHERE kind='work' AND rkey=? LIMIT 1"
  ).bind(rkey).first()) as any;
  if (!work) return html(`<header><h1>404</h1></header><main><p class="meta">作品が見つかりません。<a href="/">← 一覧</a></p></main>`, "404");
  const pr = parseProps(work.props);
  const { results } = await env.MANGAKA_DB.prepare(
    "SELECT rkey, page_number, props FROM vertex_mangaka WHERE kind='page' AND json_extract(props,'$.workRkey')=? ORDER BY page_number ASC LIMIT 1000"
  ).bind(rkey).all();
  const pages = (results ?? []) as any[];
  const imgs = pages.map((p) => {
    const pp = parseProps(p.props);
    const key = pp.blobKey || p.rkey;
    return `<div><img loading="lazy" src="/img/${encodeURIComponent(key)}" alt="page ${esc(p.page_number)}"><div class="pageno">${esc(p.page_number)} / ${pages.length}</div></div>`;
  }).join("");
  const body = `<header><h1>${esc(work.title || work.name)}</h1>
    <div class="sub">作者: ${esc(pr.author || "—")} ・ シリーズ: ${esc(pr.series || "—")} ・ ${pages.length}ページ ・ <a href="/">← 作品一覧</a></div></header>
    <main><div class="pages">${imgs || '<p class="meta">ページがありません。</p>'}</div></main>`;
  return html(body, `${work.title || work.name} — Mangaka`);
}

async function renderImg(env: Env, key: string): Promise<Response> {
  const obj = await env.CDN.get(BLOB_PREFIX + key);
  if (!obj) return new Response("not found", { status: 404 });
  const headers = new Headers();
  headers.set("content-type", obj.httpMetadata?.contentType || "image/png");
  headers.set("cache-control", "public, max-age=31536000, immutable");
  headers.set("access-control-allow-origin", "*");
  return new Response(obj.body, { headers });
}

// ── JSON API (programmatic access / federation) ─────────────────────────────

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "access-control-allow-origin": "*" },
  });
}

async function apiWorks(env: Env): Promise<Response> {
  const { results } = await env.MANGAKA_DB.prepare(
    "SELECT rkey, title, name, props FROM vertex_mangaka WHERE kind='work' ORDER BY created_at DESC LIMIT 200"
  ).all();
  const works = ((results ?? []) as any[]).map((w) => {
    const pr = parseProps(w.props);
    return {
      rkey: w.rkey, title: w.title || w.name, author: pr.author ?? null,
      genre: pr.genre ?? null, series: pr.series ?? null, pageCount: pr.pageCount ?? null,
      coverUrl: pr.coverBlobKey ? `/img/${encodeURIComponent(pr.coverBlobKey)}` : null,
      url: `/work/${encodeURIComponent(w.rkey)}`,
    };
  });
  return jsonResponse({ works });
}

async function apiWork(env: Env, rkey: string): Promise<Response> {
  const work = (await env.MANGAKA_DB.prepare(
    "SELECT rkey, title, name, props FROM vertex_mangaka WHERE kind='work' AND rkey=? LIMIT 1"
  ).bind(rkey).first()) as any;
  if (!work) return jsonResponse({ error: "not found" }, 404);
  const pr = parseProps(work.props);
  const { results } = await env.MANGAKA_DB.prepare(
    "SELECT rkey, page_number, props FROM vertex_mangaka WHERE kind='page' AND json_extract(props,'$.workRkey')=? ORDER BY page_number ASC LIMIT 1000"
  ).bind(rkey).all();
  const pages = ((results ?? []) as any[]).map((p) => {
    const pp = parseProps(p.props);
    const key = pp.blobKey || p.rkey;
    return { pageNumber: p.page_number, imageUrl: `/img/${encodeURIComponent(key)}` };
  });
  return jsonResponse({
    rkey: work.rkey, title: work.title || work.name,
    author: pr.author ?? null, genre: pr.genre ?? null, series: pr.series ?? null,
    pageCount: pages.length, pages,
  });
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);
    const path = url.pathname;
    try {
      if (path === "/" || path === "") return await renderIndex(env);
      if (path === "/api/works") return await apiWorks(env);
      if (path.startsWith("/api/work/")) return await apiWork(env, decodeURIComponent(path.slice(10)));
      if (path.startsWith("/img/")) return await renderImg(env, decodeURIComponent(path.slice(5)));
      if (path.startsWith("/work/")) return await renderWork(env, decodeURIComponent(path.slice(6)));
      if (path === "/health") return new Response(JSON.stringify({ ok: true }), { headers: { "content-type": "application/json" } });
      return new Response("not found", { status: 404 });
    } catch (e) {
      return new Response("error: " + (e as Error).message, { status: 500 });
    }
  },
};
