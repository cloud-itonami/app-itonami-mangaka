// Static build: dist/ is the whole app (HTML, CSS, JS) for the Tauri v3
// shell and for a plain static host. No bundler and no dependency.
// The page is the mangaka reader: a works list plus a work reader that
// talks to the public reader API (https://mangaka.itonami.cloud) from the
// WebView. Identity comes from package.json `itonami` (the single
// definition for this non-series app) checked against blueprint.edn.
import { mkdir, copyFile, readFile, writeFile, rm } from "node:fs/promises";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { resolve, join } from "node:path";
import { createHash } from "node:crypto";
import { readBlueprint, deriveIdentity } from "./identity.mjs";

export const TAURI = "3.0.0-alpha.6";
// The reader fetches the public API and page images from the reader origin
// only (plus the Tauri IPC bridge). No other origin appears here; in
// particular no broker, no murakumo and no image-generation origin yet
// (phase 2 studio work will need its own approval boundary review).
export const CSP = "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data: https://mangaka.itonami.cloud; connect-src ipc: http://ipc.localhost https://mangaka.itonami.cloud; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'";

const sha = (bytes) => createHash("sha256").update(bytes).digest("hex");

export async function build(appRoot = fileURLToPath(new URL("../", import.meta.url))) {
  const repo = resolve(appRoot, "..");
  const out = resolve(appRoot, "dist");
  const meta = JSON.parse(await readFile(resolve(appRoot, "package.json"), "utf8"));

  const sources = {};
  const source = async (path) => {
    const file = resolve(repo, path);
    if (!existsSync(file)) return null;
    const bytes = await readFile(file);
    sources[path] = sha(bytes);
    return bytes.toString("utf8");
  };

  const blueprintText = await source("blueprint.edn");
  if (blueprintText === null) throw new Error("blueprint.edn not found next to app/");
  const blueprint = readBlueprint(blueprintText);
  if (typeof meta.itonami?.source !== "string" || !meta.itonami.source) {
    throw new Error("package.json has no itonami.source; re-run scaffold");
  }
  const identity = deriveIdentity(meta.itonami.source, blueprint);

  // The stamped files must agree with the blueprint they were stamped from.
  const conf = JSON.parse(await readFile(resolve(appRoot, "src-tauri/tauri.conf.json"), "utf8"));
  const expect = (what, got, want) => { if (got !== want) throw new Error(`${what} is ${JSON.stringify(got)}, blueprint.edn gives ${JSON.stringify(want)}; re-run scaffold`); };
  expect("package.json itonami.id", meta.itonami?.id, identity.id);
  expect("package.json itonami.title", meta.itonami?.title, identity.title);
  expect("package.json itonami.source", meta.itonami?.source, identity.source);
  expect("package.json itonami.catalog", meta.itonami?.catalog, identity.catalog);
  expect("package.json itonami.origin", meta.itonami?.origin, identity.origin);
  expect("tauri.conf.json identifier", conf.identifier, identity.id);
  expect("tauri.conf.json productName", conf.productName, identity.productName);
  expect("tauri.conf.json window title", conf.app?.windows?.[0]?.title, identity.title);
  expect("tauri.conf.json version", conf.version, meta.version);
  expect("tauri.conf.json csp", conf.app?.security?.csp, CSP);

  // descriptor.json in dist is a build artifact (never committed). It
  // declares the runtime network need honestly: the WebView fetches the
  // public reader API. There are no broker operations and no writes.
  const descriptor = {
    schema: "kotoba.app.client-runtime.v1",
    target: "browser",
    profile: "restricted-wasm-v1",
    entry: "index.html",
    "local-state": { adapter: "localstorage", schema: identity.stateSchema, version: 1 },
    workers: [],
    operations: [],
    network: { origins: [identity.origin], methods: ["GET"], writes: false },
  };

  await rm(out, { recursive: true, force: true });
  await mkdir(out, { recursive: true });
  const esc = identity.title.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const index = (await readFile(resolve(appRoot, "src/index.html"), "utf8")).replaceAll("{{CSP}}", CSP).replaceAll("{{TITLE}}", esc);
  if (index.includes("{{")) throw new Error("index.html has an unfilled placeholder");
  await writeFile(join(out, "index.html"), index);
  for (const name of ["style.css", "app.js", "view.js"]) await copyFile(resolve(appRoot, "src", name), join(out, name));
  const data = { identity, version: meta.version, blueprint, sources, descriptor };
  await writeFile(join(out, "data.js"), `export default ${JSON.stringify(data, null, 1)};\n`);
  await writeFile(join(out, "descriptor.json"), JSON.stringify(descriptor, null, 2) + "\n");

  const names = ["index.html", "style.css", "app.js", "view.js", "data.js", "descriptor.json"];
  const files = {};
  for (const name of names) files[name] = sha(await readFile(join(out, name)));
  const release = { schema: "awai.app.artifact.v1", id: identity.id, source: identity.source, version: meta.version, tauri: TAURI, sources, files };
  await writeFile(join(out, "release.json"), JSON.stringify(release, null, 2) + "\n");
  return { identity, release, data };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const { identity, release } = await build();
  console.log(`${identity.title} (${identity.id}) static build: ${Object.keys(release.files).length} pinned files from ${Object.keys(release.sources).length} sources`);
}
