<!-- Integrated from cloud-itonami/mangaka@9f4114b4 (2026-11-11). Original preserved in the archived repository. -->

# ai-gftd-project-mangaka (agent notes)

## Python prune / cljc SSoT (2026-07-07, owner directive)

- **Python is deprecated in this project.** The LangGraph pod trees `lg/` and
  `lg-deployed/`, and the helm chart `50-infra/vultr/lg-mangaka-pool/`, were
  **removed** (all LangGraph Python pods decommissioned — ADR-2607031900 /
  ADR-2606120930; deletion is not a functional regression).
- **SSoT is the Clojure(Script) tree:**
  - `clj/` — JVM server + langgraph-clj graphs + Studio UI (`kbb -M:dev:test`).
  - `clj-edge/` — CF-Worker edge SSoT (`core.cljc` + `worker_api.cljs`;
    `kbb -M:cljs -m shadow.cljs.devtools.cli compile node-test && node target/node-tests.js`).
  - Pure-logic Python modules were ported with golden fixtures generated from
    the originals: `mangaka.metrics` (engagement/reaction fitness ADR-2606181200 +
    v11 tensor score), `mangaka.layout` (v10 pipeline router + v11 page layout),
    `mangaka.recipe` (style fingerprint — byte-compatible with
    `data/recipe-ledger.jsonl` — + ledger helpers), `mangaka.style-registry`
    (over `data/style-registry.edn`). Tests: `clj/test/mangaka/py_port_test.cljk`.
- **ComfyUI/Modal host-boundary assets are NOT ports and were NOT deleted** —
  they were relocated to `comfy/` (structure preserved from `lg/`):
  - `comfy/custom_nodes/MangakaTextOverlay/` — ComfyUI custom node pack
    (NOTE: `MangakaUSDScene` referenced by the root AGENTS.md pointer never
    existed in this tree at prune time).
  - `comfy/usd-scenes/` — USD scene builders (was `lg/scripts/usd-scenes/`).
  - `comfy/scripts/` — render/QA/installer scripts (`install-mangaka-comfy-workflow.py`,
    `install-comfy-quality-pack.ps1`, `modal_*.py`, `render-v5-page.py`,
    `fleet_status.py`, …; was `lg/scripts/`).
  - `comfy/lg_mangaka/` — the Python support modules those scripts import
    (`comfy_workflows.py` SSoT builders, `v10_orchestrator.py`,
    `coscientist_quality.py`, `storyboard_db.py`/`prolly.py`, `first_axes.py`,
    style profiles, …). Import layout mirrors the old `lg/` root, so
    `cd comfy && python -m lg_mangaka.v10_orchestrator …` works as before.
  - Run Python only for these ComfyUI/Modal pipelines:
    `uv run --with <deps> --no-project python …`.
- Do not resurrect `lg/`; new logic lands in `.cljc` (`clj/` or `clj-edge/`).
  Operational runbook: `RUNBOOK.md`.
