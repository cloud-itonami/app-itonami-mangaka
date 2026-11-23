// mangaka-reader — read-only public manga reader (mangaka.itonami.cloud /
// manga.gftd.ai). Plain JS, zero dependencies: wrangler.jsonc deploys this file
// directly (`main: src/worker.js`), no build step, no dist/ artifacts.
// D1 (MANGAKA_DB) holds the work/page rows; page images come from yataverse
// (https://yataverse.com/ipfs/<cid>) — this Worker has no R2 binding and
// never touches R2. The .cljk implementation under src/mangaka_reader/ is
// kept for reference but is no longer the deployed entry point.
//
// Routes:
//   GET /                  → index (works from D1)
//   GET /work/:rkey        → reader (title/author + all pages via /img)
//   GET /img/<key>         → page image from yataverse (key treated as CID)
//   GET /ipfs/<cid>        → passthrough https://yataverse.com/ipfs/<cid>
//   GET /api/works         → JSON list of works
//   GET /api/work/:rkey    → JSON work + pages (+ versions when grouped)
//   POST /api/work/:rkey   → studio meta update (MANGAKA_ADMIN_TOKEN)
//   POST /api/work/:rkey/page/:n → studio blobKey update (same token)
//   GET /health            → {ok:true}

export const YATAVERSE_ORIGIN = "https://yataverse.com";
export const IMAGE_CACHE_CONTROL = "public, max-age=300";

// Migration-period key→CID table. Fresh rows already store CIDs as blobKey,
// so /img/<cid> works without an entry (see resolveImgCid); legacy slug keys
// (e.g. "gh-arc0-1-v11-p01") can be pointed at their CID here. A key that is
// neither a CID nor listed here resolves to null → 404 image-unavailable,
// never a backend 500 and never an upstream fetch.
export const IMG_KEY_MAP = {};

// ── key validation (path-traversal guard for /img and /ipfs) ──────────────
export function isValidKey(key) {
  return (
    typeof key === "string" &&
    key.length > 0 &&
    key.trim().length > 0 &&
    !key.startsWith("/") &&
    !key.includes("/") &&
    !key.includes("\\") &&
    !key.includes("..") &&
    !/[\u0000-\u001f\u007f]/.test(key)
  );
}

const CID_RE = /^(Qm[1-9A-HJ-NP-Za-km-z]{44}|bafy[a-z0-9]{20,}|bafk[a-z0-9]{20,}|baga[a-z0-9]{20,})$/;

export function isCid(s) {
  return typeof s === "string" && CID_RE.test(s);
}

// Map wins; else the key itself is the CID; else null (unavailable).
export function resolveImgCid(key, map = IMG_KEY_MAP) {
  if (map && Object.prototype.hasOwnProperty.call(map, key)) return map[key];
  return isCid(key) ? key : null;
}

function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "access-control-allow-origin": "*",
    },
  });
}

function unavailable(key) {
  return jsonResponse({ error: "image-unavailable", key, source: "yataverse" }, 404);
}

function invalidKey(key) {
  return jsonResponse({ error: "invalid-key", key }, 400);
}

async function fetchImage(cid, key, fetchFn) {
  let res;
  try {
    res = await fetchFn(`${YATAVERSE_ORIGIN}/ipfs/${encodeURIComponent(cid)}`);
  } catch {
    return unavailable(key);
  }
  if (!res || !res.ok) return unavailable(key);
  const headers = new Headers();
  headers.set("content-type", res.headers.get("content-type") || "image/png");
  headers.set("cache-control", IMAGE_CACHE_CONTROL);
  headers.set("access-control-allow-origin", "*");
  return new Response(res.body, { status: 200, headers });
}

// GET /ipfs/<cid> — stream yataverse bytes straight through.
export function handleIpfs(cid, fetchFn = globalThis.fetch) {
  if (!isValidKey(cid)) return Promise.resolve(invalidKey(cid));
  return fetchImage(cid, cid, fetchFn);
}

// GET /img/<key> — key is a CID (or a legacy key listed in IMG_KEY_MAP).
export function handleImg(key, fetchFn = globalThis.fetch, map = IMG_KEY_MAP) {
  if (!isValidKey(key)) return Promise.resolve(invalidKey(key));
  const cid = resolveImgCid(key, map);
  if (!cid) return Promise.resolve(unavailable(key));
  return fetchImage(cid, key, fetchFn);
}

// ── D1 helpers ─────────────────────────────────────────────────────────────
function stmt(env, sql, binds) {
  const p = env.MANGAKA_DB.prepare(sql);
  return binds && binds.length ? p.bind(...binds) : p;
}
async function qAll(env, sql, ...binds) {
  const r = await stmt(env, sql, binds).all();
  return r && r.results ? r.results : [];
}
async function qFirst(env, sql, ...binds) {
  return (await stmt(env, sql, binds).first()) || null;
}
async function qRun(env, sql, ...binds) {
  return stmt(env, sql, binds).run();
}
function parseProps(s) {
  try {
    return JSON.parse(s ?? "{}");
  } catch {
    return {};
  }
}
function withProps(row) {
  return row ? { ...row, props: parseProps(row.props) } : null;
}

const workRows = (env) =>
  qAll(
    env,
    "SELECT rkey, title, name, props FROM vertex_mangaka WHERE kind='work' ORDER BY created_at DESC LIMIT 200"
  );
async function coverKey(env, rkey) {
  const row = await qFirst(
    env,
    "SELECT rkey, props FROM vertex_mangaka WHERE kind='page' AND json_extract(props,'$.workRkey')=? ORDER BY page_number ASC LIMIT 1",
    rkey
  );
  return row ? parseProps(row.props).blobKey || row.rkey : null;
}
async function workRow(env, rkey) {
  const row = await qFirst(
    env,
    "SELECT rkey, title, name, props FROM vertex_mangaka WHERE kind='work' AND rkey=? LIMIT 1",
    rkey
  );
  return withProps(row);
}
async function versionsOf(env, work, currentRkey) {
  const group = work && work.props ? work.props.versionGroup : null;
  if (!group) return [];
  const rows = await qAll(
    env,
    "SELECT rkey, title, props FROM vertex_mangaka WHERE kind='work' AND json_extract(props,'$.versionGroup')=? ORDER BY created_at ASC LIMIT 20",
    group
  );
  return rows.map((r) => {
    const p = parseProps(r.props);
    return { rkey: r.rkey, label: p.versionLabel || r.rkey, "current?": r.rkey === currentRkey };
  });
}
async function pageList(env, rkey) {
  const rows = await qAll(
    env,
    "SELECT rkey, page_number, props FROM vertex_mangaka WHERE kind='page' AND json_extract(props,'$.workRkey')=? ORDER BY page_number ASC LIMIT 1000",
    rkey
  );
  return rows.map((row) => ({
    n: row.page_number,
    src: `/img/${encodeURIComponent(parseProps(row.props).blobKey || row.rkey)}`,
  }));
}

// ── HTML rendering (plain, server-side) ────────────────────────────────────
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
function htmlPage(title, body) {
  return new Response(
    `<!doctype html><html lang="ja"><head><meta charset="utf-8">\n<meta name="viewport" content="width=device-width,initial-scale=1">\n<title>${esc(title)}</title>\n<style>:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#0c0e14;color:#e8eaf0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Hiragino Sans",Meiryo,sans-serif;line-height:1.6}header{padding:20px 24px;border-bottom:1px solid #232838}h1{margin:0;font-size:20px}.sub{color:#9aa3b8;font-size:13px}main{max-width:860px;margin:0 auto;padding:24px}.card{display:block;padding:18px 20px;margin:12px 0;background:#151926;border:1px solid #232838;border-radius:12px;text-decoration:none;color:inherit}.pages{display:flex;flex-direction:column;align-items:center;gap:10px}.pages img{width:100%;max-width:760px;height:auto;background:#000}.versions{display:flex;gap:8px;flex-wrap:wrap;padding:8px 16px;background:#15151a;font-size:13px}footer{color:#6b7488;font-size:12px;text-align:center;padding:32px 16px}</style></head><body>${body}<footer>mangaka.gftd.ai · AI-generated manga · 公開: D1 + yataverse</footer></body></html>`,
    { headers: { "content-type": "text/html; charset=utf-8" } }
  );
}

async function handleIndex(env) {
  const rows = await workRows(env);
  const works = await Promise.all(rows.map((r) => coverKey(env, r.rkey)));
  const cards = rows
    .map((row, i) => {
        const w = { ...withProps(row), cover: works[i] };
        return `<a class="card" href="/work/${encodeURIComponent(w.rkey)}"><h2>${esc(w.title || w.name || w.rkey)}</h2><div class="sub">作者: ${esc(w.props.author || "—")} ・ シリーズ: ${esc(w.props.series || "—")} ・ ${esc(w.props.pageCount ?? "?")}ページ ・ ${esc(w.props.genre || "")}</div>${w.cover ? `<img loading="lazy" src="/img/${encodeURIComponent(w.cover)}" alt="cover">` : ""}</a>`;
      })
    .join("");
  const body = `<header><h1>Mangaka 作品一覧</h1><div class="sub">作者・作品・シリーズごとの公開ビューア</div></header><main>${cards || '<p class="sub">まだ公開作品がありません。</p>'}</main>`;
  return htmlPage("Mangaka — 作品一覧", body);
}

async function handleWork(env, rkey) {
  const work = await workRow(env, rkey);
  if (!work) {
    return htmlPage(
      "404",
      '<header><h1>404</h1></header><main><p class="sub">作品が見つかりません。<a href="/">← 一覧</a></p></main>'
    );
  }
  const [pages, versions] = await Promise.all([pageList(env, rkey), versionsOf(env, work, rkey)]);
  const title = work.title || work.name;
  const bar =
    versions.length >= 2
      ? `<nav class="versions">${versions.map((v) => (v["current?"] ? `<b>${esc(v.label)}</b>` : `<a href="/work/${esc(v.rkey)}">${esc(v.label)}</a>`)).join("")}</nav>`
      : "";
  const imgs = pages
    .map((p) => `<div><img loading="lazy" src="${esc(p.src)}" alt="page ${esc(p.n)}"><div class="sub">${esc(p.n)} / ${pages.length}</div></div>`)
    .join("");
  const body = `${bar}<header><h1>${esc(title)}</h1><div class="sub">作者: ${esc(work.props.author || "—")} ・ シリーズ: ${esc(work.props.series || "—")} ・ ${pages.length}ページ ・ <a href="/">← 作品一覧</a></div></header><main><div class="pages">${imgs || '<p class="sub">ページがありません。</p>'}</div></main>`;
  return htmlPage(`${title} — Mangaka`, body);
}

// ── JSON API ───────────────────────────────────────────────────────────────
const apiCors = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET,POST,OPTIONS",
  "access-control-allow-headers": "authorization,content-type",
};
function apiJson(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...apiCors, "content-type": "application/json; charset=utf-8" },
  });
}
async function handleWorksApi(env) {
  const rows = await workRows(env);
  const covers = await Promise.all(rows.map((r) => coverKey(env, r.rkey)));
  const works = rows.map((row, i) => {
    const w = { ...withProps(row), cover: covers[i] };
    return {
      rkey: w.rkey,
      title: w.title || w.name || w.rkey,
      author: w.props.author || "",
      series: w.props.series || "",
      genre: w.props.genre || "",
      pageCount: w.props.pageCount,
      logline: w.props.logline || "",
      cover: w.cover ? `/img/${encodeURIComponent(w.cover)}` : null,
    };
  });
  return apiJson({ works });
}
async function handleWorkApi(env, rkey) {
  const work = await workRow(env, rkey);
  if (!work) return apiJson({ error: "not found" }, 404);
  const [pages, versions] = await Promise.all([pageList(env, rkey), versionsOf(env, work, rkey)]);
  const out = {
    rkey: work.rkey,
    title: work.title || work.name,
    author: work.props.author || "",
    series: work.props.series || "",
    genre: work.props.genre || "",
    logline: work.props.logline || "",
    pageCount: work.props.pageCount,
    pages,
  };
  if (versions.length) out.versions = versions;
  return apiJson(out);
}
function authorized(env, req) {
  const token = env ? env.MANGAKA_ADMIN_TOKEN : null;
  if (!token) return false;
  return (req.headers.get("authorization") || "") === `Bearer ${token}`;
}
async function handleWorkUpdate(env, req, rkey) {
  if (!authorized(env, req)) return apiJson({ error: "unauthorized" }, 401);
  let body;
  try {
    body = await req.json();
  } catch {
    return apiJson({ error: "invalid json" }, 400);
  }
  const work = await workRow(env, rkey);
  if (!work) return apiJson({ error: "not found" }, 404);
  const props = { ...work.props };
  for (const k of ["author", "series", "genre", "logline"]) {
    if (typeof body[k] === "string") props[k] = body[k];
  }
  const title = typeof body.title === "string" && body.title.trim() ? body.title.trim() : work.title;
  await qRun(env, "UPDATE vertex_mangaka SET title=?, props=? WHERE kind='work' AND rkey=?", title, JSON.stringify(props), rkey);
  return apiJson({ ok: true, rkey, title, props });
}
function parsePagePath(path) {
  const m = path.match(/^\/api\/work\/(.+)\/page\/(\d+)$/);
  return m ? { rkey: m[1], pageNumber: parseInt(m[2], 10) } : null;
}
async function handlePageUpdate(env, req, { rkey, pageNumber }) {
  if (!authorized(env, req)) return apiJson({ error: "unauthorized" }, 401);
  let body;
  try {
    body = await req.json();
  } catch {
    return apiJson({ error: "invalid json" }, 400);
  }
  const row = await qFirst(
    env,
    "SELECT rkey, props FROM vertex_mangaka WHERE kind='page' AND json_extract(props,'$.workRkey')=? AND page_number=? LIMIT 1",
    rkey,
    pageNumber
  );
  if (!row) return apiJson({ error: "not found" }, 404);
  const props = parseProps(row.props);
  if (typeof body.blobKey === "string" && body.blobKey.trim()) {
    props.blobKey = body.blobKey.trim();
  }
  await qRun(env, "UPDATE vertex_mangaka SET props=? WHERE kind='page' AND rkey=?", JSON.stringify(props), row.rkey);
  return apiJson({ ok: true, rkey, page: pageNumber, props });
}

// ── router ─────────────────────────────────────────────────────────────────
async function fetchHandler(req, env) {
  const url = new URL(req.url);
  const path = url.pathname;
  const method = req.method;
  const decode = (s) => {
    try {
      return decodeURIComponent(s);
    } catch {
      return null;
    }
  };
  if (path === "/" || path === "") return handleIndex(env);
  if (path.startsWith("/ipfs/")) {
    const cid = decode(path.slice(6));
    if (cid === null) return invalidKey(path.slice(6));
    return handleIpfs(cid);
  }
  if (path.startsWith("/img/")) {
    const key = decode(path.slice(5));
    if (key === null) return invalidKey(path.slice(5));
    return handleImg(key);
  }
  if (method === "OPTIONS" && path.startsWith("/api/")) {
    return new Response(null, { status: 204, headers: apiCors });
  }
  if (path === "/api/works") return handleWorksApi(env);
  const pagePath = parsePagePath(path);
  if (method === "POST" && pagePath) return handlePageUpdate(env, req, pagePath);
  if (method === "POST" && path.startsWith("/api/work/")) {
    const rkey = decode(path.slice(10));
    if (rkey === null) return apiJson({ error: "not found" }, 404);
    return handleWorkUpdate(env, req, rkey);
  }
  if (path.startsWith("/api/work/")) {
    const rkey = decode(path.slice(10));
    if (rkey === null) return apiJson({ error: "not found" }, 404);
    return handleWorkApi(env, rkey);
  }
  if (path.startsWith("/work/")) {
    const rkey = decode(path.slice(6));
    return handleWork(env, rkey || "");
  }
  if (path === "/health") {
    return new Response(JSON.stringify({ ok: true }), {
      headers: { "content-type": "application/json" },
    });
  }
  return new Response("not found", { status: 404 });
}

export default {
  async fetch(req, env) {
    try {
      return await fetchHandler(req, env);
    } catch (e) {
      return new Response(`error: ${e && e.message}`, { status: 500 });
    }
  },
};
