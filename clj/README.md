# mangaka.gftd.ai — Clojure(Script) edition

A refactor of the former Python/LangGraph `mangaka.gftd.ai` server onto the
in-repo portable Clojure stack. The old `lg_mangaka` runtime has been pruned;
standalone Python render/helper scripts have also been pruned. `../lg/scripts`,
if present, is legacy non-Python sample data only.

| Python concern | Clojure target |
|---|---|
| `storyboard_db.cljc` / `prolly.cljc` / Postgres checkpointer | **kotoba-datomic** over XRPC (`mangaka.store.kotoba`), with an in-memory `langchain.db` backend (`mangaka.store/mem-store`) for dev/tests. The storyboard is stored as a **decomposed datom graph** (doc → panels → bubbles/sfx), not a JSON/blob — so it is Datalog-queryable (e.g. `documents-with-character`). |
| LangGraph graphs (`langgraph.json`) | **langgraph-clj** (`mangaka.graphs.*`) |
| `comfy*.cljc` (ComfyUI) | **comfyui-clj** (`mangaka.comfy`) — pure engine + a gateway host-fn |
| `llm.cljc` (vLLM/OpenAI) | **langchain-clj** `anthropic-model` (`mangaka.llm`) — Claude |
| `server.cljc` (FastAPI) | reitit-ring + http-kit (`mangaka.server`) |
| _(none)_ | **ClojureScript Studio UI** (`mangaka.cljs.*`, shadow-cljs + reagent) |

Core domain + graphs are portable `.cljc` (JVM today, kotoba WASM/SCI later);
`server.clj` and `store/kotoba.clj` are JVM-only.

## Layout

```
src/mangaka/
  domain.cljc            storyboard schema + Lexicon export (from storyboard_db.cljc)
  store.cljc             Store protocol + in-memory backend + repo ops
  store/kotoba.clj        kotoba-datomic XRPC backend (.q / .transact)
  runtime.clj             backend selection + execution-scratch conn
  llm.cljc               Claude via langchain.model (mock fallback offline)
  comfy.cljc             comfyui-clj panel workflow + gateway host-fn
  graphs/
    chat.cljc            agent_chat — ReAct agent: read tools over the store
                         (stats / list_documents / get_document (panels) / cast
                         (relationship graph) / list_scenes /
                         find_documents_by_character|scene) + actions that
                         design, operate, render & QA the app (create_document /
                         duplicate_document; generate_character / generate_scene /
                         generate_panel / generate_page; full panel editing — add_panel /
                         update_panel [rect/shot/focal/tags/scene/dialogue] / remove_panel /
                         reorder_panels; lint_document)
    documents.cljc       save/load/list document graphs
    gen.cljc             shared plan→render→persist scaffold for txt2img graphs
    generate_panel.cljc  panel render — free-form {:prompt …} OR doc-aware
                         {:doc-id … :panel-index n} (prompt composed from the
                         stored storyboard panel: shot/focal/tags + base-tags,
                         plus the prompt of its linked :panel/scene background)
    generate_character.cljc  reusable cast member (supplies :plan + :persist)
    generate_scene.cljc  background / environment (supplies :plan + :persist)
    generate_page.cljc   doc-aware page render — :plan reads the storyboard and
                         composes the prompt from its title, cast, shots, linked
                         scene backgrounds and base tags
    comfy_run.cljc       raw comfyui-clj workflow passthrough (EDN body)
    enrich_characters.cljc  LLM structured enrichment (langchain.model → JSON)
    query_storyboard.cljc   documentsByCharacter — Datalog query over storyboard datoms
    lint_document.cljc      lintDocument — deterministic storyboard QA (missing /
                            out-of-bounds rect, unknown focal character, unknown
                            scene, duplicate index, empty page)
    vision_score.cljc       visionScorePanel — vision-QA a rendered panel → :panel/score datoms
    registry.cljc        NSID → handler map (mirrors server.cljc)
  server.clj              /health /xrpc/{nsid} /runs /runs/stream + Studio UI
  cljs/{api,app}.cljs    Studio UI
```

## Run

```bash
# JVM server (serves the Studio UI + XRPC surface) — :8088 by default
kbb -M:dev:run          # or: bb server

# Studio UI hot-reload (separate terminal) — calls the :8088 API cross-origin;
# the server sends permissive CORS headers (+ OPTIONS preflight) so this works.
amu compile --target wasm32-browser app   # or: bb watch   → http://localhost:8280

# tests
kbb -M:dev:test         # or: bb test
```

Open <http://localhost:8088/> for the Studio: a document list + storyboard
canvas (with **‹ ›** prev/next page navigation, **Render page** for the composed
full-page image, **Lint** for deterministic QA, **Duplicate** and **Delete**), a panel generator
+ assistant chat, a **Cast** panel (design a character by name, browse the
cast, and find documents by character via the `documentsByCharacter` Datalog
query), and a **Scenes** panel (design / browse / delete background scenes, and
click a scene to find the documents set in it via `documentsByScene`).

On boot the server **auto-seeds** the GhostHacker demo (5 characters, 6 scenes,
and the `gh-arc0-1-p1` storyboard page) so the Studio has content immediately —
the canvas renders the seeded page, the Cast panel lists the characters, and
`documentsByCharacter "Nei"` / `kamiRenderFrame` work out of the box. Set
`MANGAKA_NO_SEED` to start empty.

### Endpoints

```bash
curl localhost:8088/health
curl -XPOST localhost:8088/xrpc/ai.gftd.mangaka.saveDocument -H 'content-type: application/json' \
  -d '{"id":"doc1","title":"Arc01","page":{"page/number":1,"page/title":"Arc01","page/panels":[]}}'
curl -XPOST localhost:8088/xrpc/ai.gftd.mangaka.listDocuments -d '{}'
curl -XPOST localhost:8088/xrpc/ai.gftd.mangaka.chat -H 'content-type: application/json' -d '{"message":"hi"}'
curl -N -XPOST localhost:8088/runs/stream -H 'content-type: application/json' \
  -d '{"nsid":"ai.gftd.mangaka.mangakaGeneratePanel","input":{"prompt":"neon city","seed":3}}'
```

`/runs/stream` emits Server-Sent Events. For multi-node graphs (e.g.
`mangakaGeneratePanel`) it streams a `node` frame per superstep via langgraph's
`:on-event` hook, then the final `values` frame:

```
data: {"event":"metadata","data":{"assistant":"…","accepted":true}}
data: {"event":"node","data":{"node":"plan","step":0}}
data: {"event":"node","data":{"node":"render","step":1}}
data: {"event":"node","data":{"node":"persist","step":2}}
data: {"event":"values","data":{…result…}}
data: {"event":"end","data":{}}
```

Single-node graphs fall back to one `values` frame; errors yield an `error` frame.

## Data model — EDN / Datomic native

The stored representation is **EDN datoms**, not JSON / JSON-LD / SQL rows:

- **Storage**: a document is a decomposed entity graph — the `:doc/*` entity
  carries the page attrs and `:page/panels` (component refs) → `:panel/*` →
  `:panel/bubbles` / `:panel/sfx`. `:panel/focal` is cardinality-many, so
  `store/documents-with-character` is a one-line Datalog query. Re-saving
  retracts the prior graph (no orphan panels). See `mangaka.domain`
  (`doc->tx` / `pulled->page`). `:panel/focal` is an unordered set — it is
  normalized (sorted) on load, so multi-character panels round-trip
  deterministically. (Ordered lists like `:page/base-tags` / `:panel/tags`
  are stored as single vector values, preserving order.)
- **Wire**: **EDN is the default** response format; JSON is served only when
  the client asks (`Accept: application/json` or a JSON content-type — e.g.
  the browser Studio). `curl` with no headers gets EDN.
- **Lexicon**: the AT-Proto `ai.gftd.mangaka.storyboard` (camelCase) JSON is a
  *derived view* (`domain/export-lexicon`), not the stored form.

JSON requests still work: string keys with a slash decode to namespaced
keywords (`"page/number"` → `:page/number`), so the storyboard round-trips
over JSON too.

## NSID reference

Every NSID is reachable three ways: `POST /xrpc/{nsid}` (body = input),
`POST /runs` (`{nsid|assistant_id, input, thread_id}`), and `POST /runs/stream`
(SSE; the generation graphs emit a `node` frame per superstep). Inputs in
`(parens)` are optional.

| NSID | input | result |
|---|---|---|
| `…health` | — | `{:status :app :impl :store :nsids}` |
| `…chat` | `{:message}` or `{:messages [...]}` | `{:reply :messages}` |
| `…saveDocument` | `{:id :page (:kind :title)}` | `{:id :ok}` |
| `…loadDocument` | `{:id}` | `{:id :kind :title :page-number :page :lexicon}` or `null` |
| `…listDocuments` | `{(:offset) (:limit)}` | `{:documents [{:id :title :page-number}] :total :offset :limit}` |
| `…deleteDocument` | `{:id}` | `{:id :deleted :renders-removed}` (hard-delete the doc + its render outputs — panels & page render, idempotent) |
| `…duplicateDocument` | `{:id (:new-id :page-number)}` | `{:id :new-id :ok}` — clone a page's layout (won't overwrite) |
| `…updatePanel` | `{:doc-id :panel-index :panel}` (merge patch) | `{:doc-id :panel-index :panel}` |
| `…addPanel` | `{:doc-id (:panel)}` | `{:doc-id :panel-index :total :panel}` |
| `…removePanel` | `{:doc-id :panel-index}` | `{:doc-id :removed :total}` (remaining reindexed) |
| `…reorderPanels` | `{:doc-id :order}` (perm of 0..n-1) | `{:doc-id :order :total}` (reindexed) |
| `…lintDocument` | `{:doc-id}` | `{:doc-id :ok :renderable :issues [{:code :severity :panel? :message}] :count :errors :warnings}` (deterministic QA; `:renderable` = no errors) |
| `…documentsByCharacter` | `{:character}` ("Nei" or ":character/Nei") | `{:character :documents :panels}` |
| `…documentsByScene` | `{:scene}` (a scene id) | `{:scene :documents :panels}` — docs/panels set in that scene |
| `…analyzeCharacterGraph` | — | `{:nodes [{:id :name}] :edges [{:from :to :rel}] :count}` |
| `…mangakaGeneratePanel` | free-form `{:prompt (:tags :seed …)}` **or** doc-aware `{:doc-id :panel-index}` | `{:panel-id :doc-id :index :image-b64 :mime :source :seed :run-id}` |
| `…mangakaGenerateCharacter` | `{:name (:prompt :tags :seed)}` | `{:character-id :name :image-b64 :mime :source :seed :run-id}` |
| `…mangakaGenerateScene` | `{:prompt (:tags :seed)}` | `{:scene-id :name :image-b64 …}` |
| `…mangakaGeneratePage` | `{:doc-id}` | `{:page-render-id :doc-id :image-b64 …}` |
| `…enrichCharacters` | `{:name (:description :tags)}` | `{:character-id :name :enrichment :llm-applied}` |
| `…enrichScene` | `{:id}` (an existing scene) | `{:scene-id :enrichment :llm-applied}` |
| `…visionScorePanel` | `{:panel-id}` or `{:image-b64}` | `{:panel-id :score :critique :llm-applied}` |
| `…listCharacters` / `…listScenes` | `{(:offset) (:limit)}` | `{:characters/:scenes […] :total :offset :limit}` |
| `…loadCharacter` / `…loadScene` | `{:id}` | the `:character/*` / `:scene/*` entity, or `null` |
| `…deleteCharacter` / `…deleteScene` | `{:id}` | `{:id :deleted}` (hard-delete a generated asset, idempotent) |
| `…listRenders` | `{:doc-id}` | `{:doc-id :renders [{:id :index :seed :score :status :image-url}]}` (no inline image) |
| `…loadPageRender` | `{:doc-id}` | the composed page render (`:page-render/*` + `:image-url`) from `mangakaGeneratePage`, or `null` |
| `…importGhosthacker` | `{(:asset-graph)}` (else reads bundled file) | `{:source :characters […] :scenes […]}` |
| `…kamiRenderFrame` | `{:doc-id}` | a KAMI render-IR frame (`{:frame/camera :frame/passes …}`) — feed to `kami.ipc/pack` → wgpu |
| `…stats` | — | `{:documents :characters :scenes :renders :page-renders}` (entity counts) |
| `…previewSvg` | `{:doc-id}` | `{:doc-id :svg}` — a GPU-free SVG preview (thumbnails / vision input) |
| `…comfyRun` | `{:workflow (:opts)}` (send EDN) | `{:results :executed :cached :run-id}` |

NSID prefix: `ai.gftd.mangaka.`. Errors are structured: 400 (bad/missing input),
404 (unknown nsid), 500 (graph error) — `{:error …}` in the negotiated format.

Generated images are **content-addressed blobs** (`mangaka.blob`): the
generation result carries `:image-key` + `:image-url` and the durable datom
stores the *key*, not megabytes of inline base64 (keeping the store and the
kotoba `.transact` payload small; identical images dedup). Fetch the image at
**`GET /blob/{key}`**. (With no blob store wired the inline base64 fallback is
used — fully backward-compatible.)

Plus a plain GET: **`/preview/{doc-id}`** → the storyboard rendered as
`image/svg+xml` (200, or 404), so a page can embed a thumbnail directly with
`<img src="/preview/gh-arc0-1-p1">` — no JSON/EDN unwrapping.

`chat` continuity: pass a stable `thread_id` (on `/runs`) or `:thread-id` (in
the `/xrpc` body) to continue a checkpointed conversation. With no thread-id the
turn is **stateless** (single-turn, isolated) — thread-less requests never share
state.

## Configuration (env)

| var | effect |
|---|---|
| `PORT` | server port (default 8088) |
| `KOTOBA_XRPC_URL` / `KOTOBA_URL` | if set, the durable store is kotoba-datomic; else in-memory |
| `KOTOBA_GRAPH` | kotoba graph label (default `mangaka-storyboard-v1`) |
| `KOTOBA_BEARER` | bearer token for kotoba XRPC |
| `ANTHROPIC_API_KEY` | enable live Claude; absent → deterministic mock |
| `MANGAKA_CHAT_MODEL` / `MANGAKA_CRITIQUE_MODEL` | model overrides (default opus-4-8 / sonnet-4-6) |
| `COMFYUI_URL` + `COMFYUI_API_KEY` | enable live ComfyUI gateway; absent → SVG placeholder |
| `LG_API_KEY` | if set, enforces `x-api-key` on `/runs` paths |
| `MANGAKA_NO_SEED` | if set, skips the startup GhostHacker seed (default: seed) |
| `MANGAKA_BLOB_DIR` | if set, generated images persist to this dir; else in-memory |
| `GHOSTHACKER_ASSET_GRAPH` | override the seed/import asset-graph path |

With no external services configured the whole slice runs offline (mock LLM,
placeholder renders, in-memory store).

## Scope

This is the active CLJ graph runtime (chat · document CRUD · panel,
character, scene & page generation, plus compatibility graph ids for the old
Python assistant surface). Remaining graph gaps are catalogued in
`langgraph.edn` `:backlog`; each is a further `mangaka.graphs.*` namespace plus
a `registry` entry following the established `(make deps) → handler` pattern.
