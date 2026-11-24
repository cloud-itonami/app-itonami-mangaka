// GFTD prune (2026-11): mangaka edge Worker R2 binding removed.
// node --test, no network, no build. Run from the repo root:
//   node --test appview/ai-gftd-wasm-mangaka-mng4k4x1/test/r2-prune.test.mjs
//
// edge-app.ts itself is not importable here: it imports
// @gftd/magatama-host-sdk (absolute-path alias in wrangler.worker.jsonc) and
// ../js/mangaka.js (gitignored shadow-cljs build artifact). So test ③
// executes the blobPut / stubRender function bodies extracted verbatim from
// edge-app.ts and asserts the hGeneratePanel wiring in source. Full Worker
// runtime (createWorkerExport dispatch) remains 未確認 in the PR.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const appDir = join(dirname(fileURLToPath(import.meta.url)), "..");
const read = (f) => readFileSync(join(appDir, f), "utf-8");
const workerCfg = read("wrangler.worker.jsonc");
const mainCfg = read("wrangler.jsonc");
const edgeSrc = read("src/edge-app.ts");

// Extract a top-level `async function NAME(...) { ... }` / `function NAME(...)`
// body by brace counting, so the test executes the real source text.
function extractBody(src, name) {
  const start = src.indexOf(`function ${name}`);
  assert.ok(start >= 0, `${name} found in edge-app.ts`);
  const open = src.indexOf("{", start);
  let depth = 0;
  for (let i = open; i < src.length; i++) {
    if (src[i] === "{") depth++;
    if (src[i] === "}") {
      depth--;
      if (depth === 0) return src.slice(open + 1, i);
    }
  }
  throw new Error(`${name}: unbalanced braces`);
}

// ① wrangler.worker.jsonc declares no r2_buckets (R2 binding removed).
test("① wrangler.worker.jsonc contains no r2_buckets", () => {
  assert.equal(workerCfg.includes("r2_buckets"), false);
});

// ② Both wrangler configs are free of the ai-gftd-cache bucket name.
test("② wrangler.jsonc and wrangler.worker.jsonc contain no ai-gftd-cache", () => {
  assert.equal(workerCfg.includes("ai-gftd-cache"), false);
  assert.equal(mainCfg.includes("ai-gftd-cache"), false);
});

// ③ Without CACHE_R2, panel generation succeeds (no throw / no 500) and
// returns image-key=null / image-url=null. blobPut and stubRender bodies are
// extracted from edge-app.ts and executed; fetch is stubbed so no network.
test("③ panel generation without CACHE_R2 returns image-key=null / image-url=null", async () => {
  // hGeneratePanel wiring (source-level, so a future refactor cannot silently
  // reintroduce an R2 dependency or a throw on the null path).
  assert.match(edgeSrc, /const imageKey = await blobPut\(env, render\.imageB64, render\.mime\)/);
  assert.match(edgeSrc, /"image-key": imageKey, "image-url": imageKey \? `\/blob\/\$\{imageKey\}` : null/);
  // blobPut's no-cache guard comes before any try / bucket access.
  const blobPutBody = extractBody(edgeSrc, "blobPut");
  assert.ok(
    blobPutBody.indexOf("if (!env.CACHE_R2) return null;") < blobPutBody.indexOf("try {"),
    "no-cache guard precedes bucket access"
  );

  const stubRenderBody = extractBody(edgeSrc, "stubRender");
  const blobPut = new Function("toHex", `return async (env, b64, mime) => {${blobPutBody}}`)(
    (b) => Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("")
  );
  const stubRender = new Function(`return (spec) => {${stubRenderBody}}`)();

  // Stubbed fetch: generation must not need the network on this path.
  const realFetch = globalThis.fetch;
  globalThis.fetch = async () => { throw new Error("network must not be used"); };
  try {
    const env = {}; // no CACHE_R2
    assert.equal(await blobPut(env, "aGVsbG8=", "image/png"), null);
    // hGeneratePanel equivalent: render (stub path of comfyRender) → blobPut.
    const render = stubRender({ prompt: "manga panel", width: 832, height: 1216, seed: 0 });
    const imageKey = await blobPut(env, render.imageB64, render.mime);
    const result = {
      "image-key": imageKey,
      "image-url": imageKey ? `/blob/${imageKey}` : null,
      source: render.source,
    };
    assert.deepEqual(result, { "image-key": null, "image-url": null, source: "stub" });
  } finally {
    globalThis.fetch = realFetch;
  }
});
