# mangaka.gftd.ai (clj) — Architecture

A Clojure(Script) refactor of the former Python/LangGraph `mangaka.gftd.ai`, on the
in-repo portable stack. **EDN/Datomic is the data model; langgraph-clj is the
control flow; the GPU/diffusion/LLM work is reached as injected host services.**
The old `lg_mangaka` runtime has been pruned; only standalone helper assets
were pruned from `../lg/scripts`; only legacy non-Python sample assets may remain there.

## Layers

```
HTTP  mangaka.server          reitit-ring + http-kit. /xrpc/{nsid} · /runs ·
                              /runs/stream (SSE) · /health · serves the Studio.
                              EDN is the default wire format; JSON on request.
                              start! seeds the GhostHacker demo (MANGAKA_NO_SEED).

GRAPHS mangaka.graphs.*        One graph per NSID, registered in graphs/registry
                              (the NSID → {:assistant :handler} map). Two scaffolds:
                                • gen        — txt2img generation (plan→render→persist)
                                • util/single-node + result-handler — query/CRUD
                              Validation lives in the node (throw {:type :bad-input}
                              → HTTP 400). Generation graphs also stream per-node (SSE).

DOMAIN mangaka.domain          Storyboard as a decomposed datom graph (doc → panels
                              → bubbles/sfx) + render-entity schema; doc->tx /
                              pulled->page; export-lexicon (a derived view).
       mangaka.store           Store protocol + repo ops (save/load/list/query/edit).
                              Backends: mem (langchain.db) · kotoba (kotoba-datomic XRPC).
       mangaka.runtime         Backend selection + the chat checkpoint conn.

SERVICES mangaka.llm           Claude via langchain.model (mock fallback offline).
       mangaka.comfy           comfyui-clj engine; sampler = a gateway host-fn;
                              throwaway per-render conn (fresh-scratch).
       mangaka.kami            Storyboard → KAMI scene → render-IR (kami-engine-sdk-clj).
       mangaka.blob            Content-addressed image store (datoms hold keys, not base64).
       mangaka.checkpoint       Latest-only graph checkpointer (bounded chat memory).
       mangaka.seed            Demo seed data (GhostHacker arc0-1 page).

UI     mangaka.cljs.{api,app}   shadow-cljs + reagent Studio (doc list · canvas ·
                              cast/search · panel-gen · chat).
```

## Key decisions

- **Storage = datoms, not blobs.** A storyboard is a connected entity graph, so
  it is Datalog-queryable (`documents-with-character`, `stats`). `:panel/focal`
  is cardinality-many (queryable) and normalized (sorted) on load; tag lists are
  single vector values (order-preserving). Re-save retracts the prior graph in a
  single atomic transaction. The AT-Proto lexicon and JSON are *derived views*.
- **Two store backends, one protocol.** mem (`langchain.db`, dev/tests, default)
  and kotoba-datomic over XRPC (prod) share the same `q`/`transact`/`pull`
  semantics. kotoba uses the verified `.q`/`.transact`/`.pull` endpoints.
- **clj is the brain, native libs are the arms.** GPU (kami-render / ComfyUI),
  diffusion, and LLM inference are injected host capabilities reached over data
  contracts (render-IR, workflow EDN, message maps). The engine code stays pure.
- **Bounded memory.** Generation/comfy graphs are one-shot → throwaway per-call
  conns (no run-history accretion). Chat uses a latest-only checkpointer
  (O(threads), not O(turns²)). Thread-less chat is stateless (no shared-default
  bleed).
- **Offline-first.** No `ANTHROPIC_API_KEY` → deterministic mock LLM; no
  `COMFYUI_URL` → placeholder renders; no `KOTOBA_XRPC_URL` → in-memory store.
  The whole app runs and is fully tested with zero external services.

## NSID surface

~40 NSIDs under `ai.gftd.mangaka.` (see README "NSID reference"): document
CRUD + panel edit (update/add/remove/reorder), generation (panel/character/
scene/page), query (documentsByCharacter), analyzeCharacterGraph, vision QA,
enrichment (characters/scenes plus compatibility org/env ids), comfy
passthrough, GhostHacker import, KAMI render-IR, SVG preview, stats, and
compatibility handlers for old Python assistant ids. Plus plain GETs:
`/preview/:id`, `/blob/:key`.
Generated images are content-addressed blobs (`mangaka.blob`); CORS is enabled
for cross-origin (shadow-cljs :8280) clients.

## Adding a graph

See AGENTS.md "Adding a graph". Generation → build on `mangaka.graphs.gen`;
query/CRUD → `util/single-node` + `util/result-handler`, validate in the node.

## Tests

`kbb -M:dev:test` — store round-trips (incl. rich/multi-focal), the decomposed
graph over the kotoba fake (`.q`/`.transact`/`.pull`), every graph handler, the
HTTP wire (EDN default / JSON / error codes), LLM structured parsing, the KAMI
bridge (scene → render-IR → pack), and the seed/import. All GPU-free.
