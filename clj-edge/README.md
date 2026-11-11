# mangaka — CF-Worker EDGE edition (clj-edge/, phase 4)

ClojureScript SSoT + lean Worker on the animeka template
(`../../ai-gftd-project-animeka/clj/PHASE4-REPLICATION.md`). CF-Worker only, no k8s.

**Distinct from `../clj`** — that is the JVM langgraph reference (pod-shaped);
this `clj-edge/` is the cljs SSoT the edge Worker ships.

- **SSoT**: `clj-edge/src/mangaka/core.cljk` + `worker_api.cljs`. SINGLE-table D1
  model (`vertex_mangaka`, kind-discriminated, animeka-shaped).
- **Worker**: `../appview/ai-gftd-wasm-mangaka-mng4k4x1/src/edge-app.ts`
  (NOT the project's `src/app.ts`). DUAL-WRITE kotoba (primary) + D1 `MANGAKA_DB`
  (shadow). NSIDs `ai.gftd.mangaka.*`: character / work / environment / chapter /
  page / panel CRUD + `generatePanel` (ComfyUI → R2 `CACHE_R2`). A panel render's
  image-key is kept in the kotoba datom; vertex_mangaka has no image column so the
  D1 shadow row drops it (render lives in kotoba + R2).
- **Build/test**:
  - tests (cljs): `kbb -M:cljs -m shadow.cljs.devtools.cli compile node-test && node target/node-tests.js`
  - worker ESM: `kbb -M:cljs -m shadow.cljs.devtools.cli release worker` → appview `js/mangaka.js` (gitignored)
  - bundle check: `cd ../appview/… && npx wrangler deploy --dry-run -c wrangler.worker.jsonc`
- **Deploy/cutover (gated)**: `wrangler.worker.jsonc` (main `src/edge-app.ts`) is
  isolated from the project's `wrangler.jsonc` and the JVM `clj/`. At cutover set
  `KOTOBA_BEARER` (+ `COMFYUI_URL`/`COMFYUI_API_KEY`).
