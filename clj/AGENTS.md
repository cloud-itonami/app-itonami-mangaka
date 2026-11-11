# mangaka.gftd.ai — clj edition (agent notes)

Active Clojure(Script) graph runtime for mangaka.gftd.ai. The former
`../lg/lg_mangaka` Python runtime and standalone Python helper scripts have been
pruned. `../lg/scripts`, if present, is legacy non-Python sample data only.

## KAMI rendering (clj-unified)
The genko/storyboard rendering unifies on **kami-engine-sdk-clj**
(`etzhayyim/kami-engine`, `:local/root` dep): clj is the brain (scene + ECS +
render-IR as data), Rust/wgpu `kami-render` is the GPU arm. `mangaka.kami`
bridges a storyboard page → KAMI scene → render-IR frame → `kami.ipc/pack`
bytes (the Rust `kami-clj-host` contract); exposed as `kamiRenderFrame`. The
pure path (`kami.scene/render/ipc/ecs/math`) is dependency-free `.cljc` —
testable with no GPU. Don't reintroduce a bespoke SVG/canvas renderer as the
SSoT; the storyboard datoms → KAMI render-IR is the path.

## Stack (kotoba-lang git deps; the com-junkawasaki/*-clj originals this was
forked from are mid-migration out, per repos.edn's `:orgs` taxonomy note)
- **kotoba-lang/langgraph** — graphs (`langgraph.graph` / `prebuilt` / `checkpoint`)
- **kotoba-lang/comfyui** — diffusion node graph (pure engine; heavy work = host-fn)
- **kotoba-lang/langchain** — `langchain.model/anthropic-model` (Claude) + `langchain.db`
  (Datomic-API in-memory store)
- **kotoba-lang/langgraph-store** (now `lib/kotoba.langgraphStore` in `kotoba-lang/kotoba`; the old repository is retired) — shared blob/checkpoint app-scaffolding (also
  used by `ai-gftd-animeka`; see ADR-2607011816 / ADR-2607011900)
- **kotoba-lang/kami-mangaka-expression** (now `lib/kotoba.kamiMangakaExpression` in `kotoba-lang/kotoba`; the old repository is retired) (`:deps/root` into `kotoba-lang/kami-engine`)
  — HUNTER×HUNTER由来の表情パターングラフ (`kami.mangaka.expression` +
  `resources/mangaka_expression_patterns.edn`); a different `kami-mangaka-*`
  family member than `kami-mangaka-page` below (ADR-2607022800 cluster 43),
  used independently.
- **kotoba-lang/kami-mangaka-page** — `kami.mangaka.komawari` here is the
  canonical golden-ratio panel-geometry engine (ADR-2607051520/2607051530,
  ADR-2607141700): `mangaka.layout.komawari` in this repo is now a thin
  re-export of it, not an independent implementation. Historically this
  `kami-mangaka-*` cluster (`page/reader/render/text/scene`) was framed as
  belonging only to `kotoba-lang/kami-app-sip` (Ghost Hacker's "Spirit in
  Physics" game) and unrelated to mangaka.gftd.ai — that framing predates
  ADR-2607141700's consolidation and no longer holds for `kami-mangaka-page`
  specifically; `kami-app-sip`'s own `sip.page` facade is unaffected (still
  wired to `kami.mangaka.page`'s pre-existing `layout-page`/`template-for`
  API, untouched by this change).
- **kotoba-datomic** — durable store over XRPC (`.q` / `.transact`); same datom
  semantics as `langchain.db` (ADR-2605302130 / ADR-0013)

Pins in `deps.edn`; the `:dev` alias overrides to the local checkouts (no git
fetch). Always build/test/run with `-M:dev…`.

## Conventions
- Core domain + graphs are **`.cljc`** (must stay JVM + WASM/SCI clean — no host
  interop outside reader conditionals). `server.cljc`, `store/kotoba.cljc`,
  `runtime.cljc` are JVM-only (`.cljc`).
- LLM I/O goes through injected host-fns (`mangaka.llm`), never direct in `.cljc`
  graph nodes — the langchain-clj WASM premise.
- ComfyUI: the engine does no I/O; only the `MangakaKSampler` host-fn calls the
  gateway. Add new node types the same way (`std/host-fn-node`).
- **Durable** data (documents, panels) → `mangaka.store`. **Ephemeral** execution
  state (checkpoints, comfy cache) → the in-memory scratch conn (`runtime/scratch*`).
  Keep that split — it mirrors the Python storyboard-SSoT vs Postgres-checkpoint split.
- **EDN / Datomic native (CRITICAL)**: storyboards are stored as a decomposed
  datom graph (`domain/doc->tx` → `pulled->page`), never a JSON/EDN blob — so
  they stay Datalog-queryable (`store/documents-with-character`). EDN is the
  default wire format (`server/data-resp`); JSON only on request. The AT-Proto
  lexicon (`export-lexicon`) is a derived view, not the stored form. Don't
  reintroduce blob columns or make JSON the canonical representation.
- NSIDs mirror the former Python `ai.gftd.mangaka.*` surface (no short placeholders).
- Everything degrades offline (mock LLM, stub renders, in-memory store).

## Adding a graph
1. New `src/mangaka/graphs/<name>.cljc` with `(make deps…)` → compiled graph and
   a `(handler compiled)` → `(fn [input thread-id] result)`.
   - **txt2img generation graphs** (panel/character/scene/page) are all the same
     plan→render→persist pipeline — build on `mangaka.graphs.gen`: supply only
     `:plan` (input → comfy spec) and `:persist` (store input spec render →
     result), then `make`/`handler`/`stream-handler` are three one-liners
     delegating to `gen/build`, `gen/handler`, `gen/stream-handler`. See
     `generate_panel.cljc` / `generate_character.cljc`.
   - **query / passthrough graphs** (one node, input → result) use
     `mangaka.graphs.util/single-node` — don't re-inline `state-graph` +
     `add-node` + entry/finish + compile. See `documents.cljc` /
     `query_storyboard.cljc` / `comfy_run.cljc`.
2. Add the NSID → `{:assistant … :handler … :stream …}` entry in
   `graphs/registry.cljc` (add `:stream` for multi-node graphs), **and the
   matching `NSID builder` line in `langgraph.edn`**. The two are kept in lock-step
   by the `manifest-matches-registry` test — a missing manifest entry fails the build.
3. Validate required inputs with `domain/require-input!` (→ HTTP 400). A graph
   that writes storyboard panels should also run `domain/valid-page!` /
   `valid-panel!` at the boundary, so malformed fields (e.g. a string
   `:panel/focal`) are rejected rather than silently decomposed.
4. Add a test in `test/mangaka/core_test.cljc`.
5. To let the **chat agent** operate a new write graph, pass its handler under
   `:actions` to `chat/make` in `registry.cljc` and add a gated tool in
   `chat.cljc` (the `cond->` in `tools`); `chat-tools-reflect-available-actions`
   guards that wiring.
The server picks it up automatically (registry is the single source).

## Verify
`kbb -M:dev:test` · boot `kbb -M:dev:run` and curl `/xrpc/*` (see README) ·
`amu compile --target wasm32-browser app` for the UI.
