// The static build pins identity and sources by digest and serves only
// local files plus the public reader API. These checks run against the
// repository's own files, so they hold here (non-series mangaka app).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import { build, CSP } from "../scripts/build.mjs";

const APP = fileURLToPath(new URL("../", import.meta.url));
const hex = /^[0-9a-f]{64}$/;

test("build pins identity, sources and output files", async () => {
  const { identity, release, data } = await build(APP);
  assert.equal(release.schema, "awai.app.artifact.v1");
  assert.equal(release.id, identity.id);
  assert.equal(release.source, identity.source);
  assert.equal(release.version, data.version);
  assert.ok(hex.test(release.sources["blueprint.edn"]), "blueprint digest is pinned");
  for (const [name, digest] of Object.entries(release.files)) {
    assert.ok(hex.test(digest), `${name} digest is pinned`);
  }
  assert.deepEqual(data.descriptor.operations, []);
  assert.equal(data.descriptor.network.writes, false);
  assert.deepEqual(data.descriptor.network.methods, ["GET"]);
  const index = await readFile(join(APP, "dist/index.html"), "utf8");
  assert.ok(!index.includes("{{"), "no unfilled placeholder ships");
  assert.ok(index.includes(`content="${CSP}"`), "the page carries the exact CSP");
  assert.ok(CSP.includes("https://mangaka.itonami.cloud"), "CSP declares the reader origin");
  for (const tag of index.matchAll(/<script\b[^>]*>/gi)) {
    assert.ok(/src=/.test(tag[0]), `no inline script ships: ${tag[0]}`);
  }
  assert.ok(!/<style[\s>]/i.test(index), "no inline style block ships");
  assert.ok(!/\sstyle\s*=/i.test(index), "no inline style attribute ships");
});

test("the built page is the reader, not a blueprint viewer", async () => {
  const appJs = await readFile(join(APP, "dist/app.js"), "utf8");
  const viewJs = await readFile(join(APP, "dist/view.js"), "utf8");
  assert.ok(viewJs.includes("/api/work/"), "work detail fetch is shipped");
  assert.ok(viewJs.includes("/api/works"), "works list fetch is shipped");
  assert.ok(!appJs.includes("blueprint viewer"), "no viewer-only copy ships");
});

test("runtime is confirmed in app/package.json", async () => {
  const pkg = JSON.parse(await readFile(join(APP, "package.json"), "utf8"));
  // Single definition: package.json `itonami` carries id/title/source.
  assert.equal(pkg.itonami.id, "network.itonami.mangaka");
  assert.equal(pkg.itonami.source, "app-itonami-mangaka");
  assert.ok(typeof pkg.itonami.title === "string" && pkg.itonami.title.length > 0);
});
