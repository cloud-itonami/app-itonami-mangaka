// Mangaka reader (plain-JS Worker) tests — node --test, no network.
// globalThis.fetch is stubbed; no real upstream is touched.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import worker, { handleImg, handleIpfs, isValidKey, resolveImgCid } from "../src/worker.js";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const CID = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi";

function stubFetch(impl) {
  const seen = [];
  globalThis.fetch = async (url) => {
    seen.push(url);
    return impl(url);
  };
  return seen;
}

function fakeDbFetch() {
  return worker.fetch(new Request("http://localhost/health"), {});
}

// ① yataverse passthrough (200, upstream content-type, cache header)
test("GET /ipfs/<cid> streams yataverse 200", async () => {
  const seen = stubFetch(async () =>
    new Response("PNGBYTES", { headers: { "content-type": "image/png" } })
  );
  const res = await worker.fetch(new Request(`http://localhost/ipfs/${CID}`), {});
  assert.equal(res.status, 200);
  assert.equal(res.headers.get("content-type"), "image/png");
  assert.equal(res.headers.get("cache-control"), "public, max-age=300");
  assert.equal(await res.text(), "PNGBYTES");
  assert.deepEqual(seen, [`https://yataverse.com/ipfs/${CID}`]);
});

test("GET /img/<cid> treats key as CID and passes through", async () => {
  const seen = stubFetch(async () =>
    new Response("JPEG", { headers: { "content-type": "image/jpeg" } })
  );
  const res = await worker.fetch(new Request(`http://localhost/img/${CID}`), {});
  assert.equal(res.status, 200);
  assert.equal(res.headers.get("content-type"), "image/jpeg");
  assert.equal(await res.text(), "JPEG");
  assert.deepEqual(seen, [`https://yataverse.com/ipfs/${CID}`]);
});

test("IMG_KEY_MAP entries redirect legacy keys to CIDs", async () => {
  const seen = stubFetch(async () => new Response("IMG", { headers: {} }));
  const res = await handleImg("legacy-slug", globalThis.fetch, { "legacy-slug": CID });
  assert.equal(res.status, 200);
  assert.deepEqual(seen, [`https://yataverse.com/ipfs/${CID}`]);
});

// ② upstream failure is 404 image-unavailable — never 500
test("upstream throw → 404 image-unavailable (never 500)", async () => {
  stubFetch(async () => { throw new Error("network down"); });
  const res = await handleIpfs(CID);
  assert.equal(res.status, 404);
  assert.notEqual(res.status, 500);
  const body = JSON.parse(await res.text());
  assert.equal(body.error, "image-unavailable");
  assert.equal(body.key, CID);
  assert.equal(body.source, "yataverse");
});

test("upstream non-OK → 404 image-unavailable (never 500)", async () => {
  stubFetch(async () => new Response("gone", { status: 404 }));
  const res = await handleImg(CID);
  assert.equal(res.status, 404);
  assert.notEqual(res.status, 500);
  const body = JSON.parse(await res.text());
  assert.equal(body.error, "image-unavailable");
});

test("unmapped non-CID /img key → 404 without fetching upstream", async () => {
  let called = false;
  stubFetch(async () => { called = true; return new Response("x", {}); });
  const res = await handleImg("gh-arc0-1-v11-p01");
  assert.equal(res.status, 404);
  assert.notEqual(res.status, 500);
  assert.equal(called, false);
  const body = JSON.parse(await res.text());
  assert.equal(body.error, "image-unavailable");
  assert.equal(body.key, "gh-arc0-1-v11-p01");
});

// ③ key validation → 400
test("isValidKey rejects traversal / blank / control keys", () => {
  for (const bad of ["", "   ", "/abs", "a/b", "..", "../secret", "a/../b", "a\\b", "a\u0000b", "a\tb", "a\u007fb"]) {
    assert.equal(isValidKey(bad), false, `should reject ${JSON.stringify(bad)}`);
  }
  assert.equal(isValidKey("gh-arc0-1-v11-p01"), true);
  assert.equal(isValidKey(CID), true);
});

test("invalid keys are 400 before any fetch (route level)", async () => {
  let called = false;
  stubFetch(async () => { called = true; return new Response("x", {}); });
  for (const path of ["/img/", "/img/a%5Cb", "/img/%2Fabs", "/img/a%00b"]) {
    const res = await worker.fetch(new Request(`http://localhost${path}`), {});
    assert.equal(res.status, 400, path);
    assert.notEqual(res.status, 500, path);
  }
  assert.equal(called, false);
});

test("resolveImgCid: map wins, else CID, else null", () => {
  assert.equal(resolveImgCid("legacy", { legacy: CID }), CID);
  assert.equal(resolveImgCid(CID, {}), CID);
  assert.equal(resolveImgCid("plain-slug", {}), null);
});

// ④ wrangler.jsonc must not declare r2_buckets (R2 is gone)
test("wrangler.jsonc declares no r2_buckets and deploys src/worker.js", () => {
  const src = readFileSync(join(root, "wrangler.jsonc"), "utf-8");
  assert.equal(src.includes("r2_buckets"), false);
  assert.match(src, /"main":\s*"src\/worker\.js"/);
  const workerSrc = readFileSync(join(root, "src/worker.js"), "utf-8");
  assert.equal(/env\.CDN|R2Bucket|ai-gftd-cdn/.test(workerSrc), false);
});

// /api/works etc. still work (D1 kept)
test("/health and /api/works still respond", async () => {
  const health = await fakeDbFetch();
  assert.equal(health.status, 200);
  assert.deepEqual(JSON.parse(await health.text()), { ok: true });

  const env = {
    MANGAKA_DB: {
      prepare: () => ({
        bind() { return this; },
        all: async () => ({ results: [] }),
        first: async () => null,
        run: async () => ({ success: true }),
      }),
    },
  };
  const works = await worker.fetch(new Request("http://localhost/api/works"), env);
  assert.equal(works.status, 200);
  assert.deepEqual(JSON.parse(await works.text()), { works: [] });
});
