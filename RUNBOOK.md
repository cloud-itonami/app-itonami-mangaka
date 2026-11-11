# Mangaka — Render & Publish Runbook

How to generate manga and publish it to **manga.gftd.ai**, entirely on the
**Tailscale fleet (no RunPod)**. Decisions: ADR-2606162100, ADR-2606160200.

## Topology (all over Tailscale)

| Role | Host | Endpoint | Notes |
|---|---|---|---|
| ComfyUI render | `gad` / `dan` | `:8188` | `gad`=Ryzen AI Max APU (ROCm), `dan`=Mac MPS. Both hold `animagine-xl-4.0`. |
| LLM (vision/text) | `asher` / `dan` | `:11434` | native Ollama `gemma4:12b-it-qat` (vision). Use native `/api/chat` + `think:false` (OpenAI `/v1` leaves `content` empty on gemma4 thinking models). |
| Domain data | Cloudflare **D1** `ai-gftd-mangaka` | — | work/chapter/page rows in `vertex_mangaka` (kind discriminator + `props` JSON linkage). |
| Page images | Cloudflare **R2** `ai-gftd-cdn` | — | key `blobs/mng4k4x1.gftd.ai/<blobKey>`. |
| Public reader | Worker `mangaka-reader` | `manga.gftd.ai` | HTML reader + `/api/works`, `/api/work/:rkey` JSON. Separate from the KAMI canvas editor. |

## Runtime

The active graph runtime is the CLJ implementation under `clj/`. The old
`lg_mangaka` Python LangGraph server and standalone Python helper scripts have
been pruned; `lg/scripts` may contain legacy non-Python sample assets only.

```bash
cd orgs/gftdcojp/ai-gftd-mangaka/clj
kbb -M:dev:test
PORT=8000 kbb -M:dev:run
```

## 0. Fleet pre-flight

The former Python `fleet_status.cljc` helper was pruned. Use the CLJ runtime and
fleet inventory/observability surfaces before scheduling heavy renders. Pick a
**FREE** node (avoid BUSY / PRESSURED). On unified-memory nodes the real ceiling
is *free RAM*, not the VRAM carve-out. **Never co-locate a heavy render and the
co-scientist loop on the same node** — it starves and times out.

## 1. Render a work

Use the CLJ graph server for storyboard/document operations and generation:
`mangakaGeneratePanel`, `mangakaGeneratePage`, `comfyRun`, `kamiRenderFrame`,
and the compatibility assistant ids in `clj/langgraph.edn`.

## 2. Theme → style (style-registry.edn)

`data/style-registry.edn` maps `genre` (and per-work override) to a profile
(`positive`/`negative`/`cfg`/`steps`/`sampler`/`mode`) + `shot-modifiers`.
Resolve through `data/style-registry.edn`.
Add a work: append to `:work->style` (or `:genre->style`) and, if new, a
`:profiles` entry. cyber→`cyber-noir-ink`, 和風伝奇→`sumi-e-gritty`,
音楽ドラマ→`soft-watercolor`, グルメ→`bright-clean`.

## 3. Co-scientist quality loop (CLJ graphs — ADR-2607164200)

**LLM 経路は自前 fleet が正 (addendum 2)**: `MURAKUMO_LLM_URL=https://api.murakumo.cloud`
を設定すると chat / critique / vision がすべて fleet の OpenAI 互換
`/v1/chat/completions` (llama.cpp、gemma4 マルチモーダル — vision 実測済み
2026-07-16) を使う。`MURAKUMO_LLM_MODEL` (default "default") /
`MURAKUMO_SERVICE_TOKEN` (optional Bearer)。ANTHROPIC_API_KEY は fleet URL
未設定時の fallback。どちらも無ければ deterministic mock (offline)。

The retired Python loop has been reintroduced as CLJ graphs:

- `ai.gftd.mangaka.mangakaGeneratePanelLoop` — single-candidate
  plan→render→score→revise (attempt budget + score threshold).
- `ai.gftd.mangaka.mangakaGeneratePanelQuality` — multi-candidate fan-out
  (default 3 seeds/round) + composeScene3d's 8-axis rubric vision critique
  (composition / silhouette / characterRecognizability / framing /
  mangaShotGrammar / lightingDrama / actionClarity / emotionAlignment) +
  refine-or-persist gate (`:score-threshold` default 80, `:max-rounds`
  default 2). Full audit trail in `:rounds`; best candidate persisted with
  `:panel/score` + axes in `:panel/critique`. Offline (no vision model) it
  degrades to nil scores and completes on budget.

```bash
curl -s localhost:2024/xrpc/ai.gftd.mangaka.mangakaGeneratePanelQuality \
  -d '{:prompt "shiro sprints across a rooftop" :character "shiro"
       :candidates 3 :max-rounds 2 :score-threshold 80}'
```

- `ai.gftd.mangaka.mangakaCoscientistPanel` — the full co-scientist loop
  (Generate→Reflect→Rank(Elo)→Evolve→Meta; pattern per ADR-2606141500 /
  isekai ADR-0007 / `90-docs/design-quality/coscientist.cljc`). Generate
  proposes a population of shot-grammar directions (LLM when available,
  deterministic library offline); Reflect critiques each render on the
  8-axis rubric; Rank is a deterministic round-robin Elo (K=32, base 1200)
  judged by the measured scores — never an LLM debate; Evolve keeps the
  elite and breeds mutation (fix-hint fold-in) + crossover children; Meta
  persists the best panel and returns an iteration doc (`:doc`) plus the
  full per-generation lineage (`:generations`).

```bash
curl -s localhost:2024/xrpc/ai.gftd.mangaka.mangakaCoscientistPanel \
  -d '{:prompt "shiro sprints across a rooftop" :character "shiro"
       :population 3 :elite 2 :max-generations 2 :score-threshold 80}'
```

**kaizen サイクル（審査→改善→再審査、ADR-2607165100 addendum 2）**:
`jumpBenchmarkQa` の issues を coscientist の Generate 種に接続できる。
`:issues [...]`（明示）か `:kaizen-from-panel "panel-…"`（その panel の
`:panel/jump-qa` datom から読む）で弱点是正指令（`issue->directive` の
決定論変換: "Lack of X"→"strong X" 等）が全候補の spec に畳み込まれ、
`:judge? true` で勝者を jump QA 再審査して `:panel/jump-qa` に永続化 —
その panel がそのまま次イテレーションの `:kaizen-from-panel` 種になる。

```bash
# ① 審査
curl -s …/xrpc/ai.gftd.mangaka.jumpBenchmarkQa -d '{:panel-id "panel-X" :samples 3}'
# ⚠ ステージ整合に注意 (2026-07-17 実測): jump QA はページ基準 — 台詞/SFX/
#   物語進行を要求するため、吹き出し合成前の「素パネル」を審査すると
#   構造的に是正不能な issue (No dialogue or SFX 等) が種に混ざり、
#   kaizen が空振りする (baseline 40.0 → rejudge 36.0、rubric は 54→67 と
#   改善)。素パネル段階は 8 軸 rubric で回し、jump QA は komawari + text
#   合成後のページに当てるか、:issues で actionable なものだけ明示指定する。
# ② 改善 + 再審査（issues は datom から自動で読む）
curl -s …/xrpc/ai.gftd.mangaka.mangakaCoscientistPanel \
  -d '{:doc-id "gh-arc0-1-p1" :panel-index 3
       :kaizen-from-panel "panel-X" :judge? true :population 3 :max-generations 2}'
```

### 3a3. VLM backend の選択（同定精度、ADR-2607165100 addendum 6）

知覚/同定の VLM は `MURAKUMO_LLM_URL` の差し替えだけで任意の OSS モデルに
できる（recover/critique/vision すべて同経路）。gad で serve できる vision
OSS を漫画キャラ同定で実測比較（勝者戦略=外見記述、各3回平均、2026-07-17）:

| モデル | p02 同定精度 | p02 grounding | p03 grounding(汎化) |
|---|---|---|---|
| gemma-4-26b-a4b (現行 :11434) | 0.367 | 6.0 | 0.0 |
| qwen3.6-35b-a3b (:11500) | 0.283 | 6.0 | 4.7 |

- **決定打は無い**: 同定精度の天井は両者 ~0.3（Q4 量子化の限界、共通）。
- **gemma** は複数キャラを混ぜて部分点を稼ぐ（`{Yuto Nei}`）が Ren を認識
  できず、別ページ(p03)では grounding を完全に諦める(0)。
- **qwen3.6** は各コマを単一キャラに正しく分離し(1コマ1人)、**p03 でも
  grounding し続ける(汎化が明確に上)** が、Nei↔Ren/Ren↔Akira を混同する。
- **使い分け**: 45p バッチのように「多数ページで grounding を切らさない」
  用途は qwen 有利。単ページ精度重視は gemma と互角。より上を狙うなら Q8
  量子化 (VRAM 次第) か上位 API (Anthropic fallback は ANTHROPIC_API_KEY で
  そのまま切替可)。
- qwen3.6 の weights+mmproj は gad に resident、serve recipe は murakumo
  `infer.edn` の `qwen3.6-35b-a3b`（`llama-server --mmproj <path>`）。比較後は
  VRAM 解放のため停止済み — 使うときだけ起こす。**本番 :11434 gemma4 backend
  は全 consumer 共有なので勝手に切り替えない**（recover バッチ用途なら
  `MURAKUMO_LLM_URL=http://<gad>:11500` を env で限定的に使う）。

### 3a2. 知覚レイヤ — 顔検出 / パネル検出 / 吹き出しクリアランス (addendum 3)

`mangaka.perception` が VLM (fleet gemma4) ベースの検出と純幾何を提供する:

- `ai.gftd.mangaka.detectFaces` は **実装版になった** (旧 compat の
  cljc-placeholder 固定矩形を置換)。`{:panel-id …}` か `{:doc-id …}` で
  render 画像から顔ボックス [{:cx :cy :w :h}] を検出し、`:panel/faces`
  datom に焼き込む。offline は `:method "no-vision-offline"` で正直に
  degrade (固定矩形を返さない)。
- 品質ループ (PanelQuality / CoscientistPanel) の critique に **:facePresence
  軸**が加わった: storyboard の期待 focal 数 (doc-aware) または `:character`
  指定 (=1人) に対する検出顔数の比。「キャラ不在の背景だけ絵」が rubric
  集約で確実に沈む。検出不能は軸ごと欠落 (罰しない)。
- `perception/detect-panels` (ページ画像のコマ境界検出) と
  `perception/bubble-clearance` (吹き出しが顔を覆っていないかの純幾何 QA、
  authored gaze box にも適用可) はページ合成 QA 用の部品として提供 —
  page-level loop への配線は follow-up。
- 旧 Python 世代の jump QA (`mangaka-data/ghosthacker/resources/v10/`
  v10-p00-score.json の character_visible / bubble_legibility 等 23 軸) は
  未移植のまま backlog `:qa :jumpBenchmarkQa`。

### 3b. Own model — character-consistency LoRA (harness)

`ai.gftd.mangaka.trainCharacterLora` stages/dispatches a training job for a
cast member with a `mangaka.models` LoRA slot (shiro / pico — the shiropico
reference sets, 17/18 imgs @1024²):

```bash
curl -s localhost:2024/xrpc/ai.gftd.mangaka.trainCharacterLora \
  -d '{:character "shiro"}'   # :steps 1200 :rank 16 defaults
```

With `MURAKUMO_DISPATCH_URL` set it POSTs the `:gen.job`-shaped envelope
(`:modality :training`, `:engine :comfy-train`, base `animagine-xl-4.0` =
HF `cagliostrolab/animagine-xl-4.0`) to `/infer/dispatch`; otherwise it
degrades to `staged`. Lifecycle lives in `:model/*` datoms; when training
completes, write the weight's DataLad+B2 CID to `:model/lora-cid` — the
quality loop then passes `:lora {:id :cid}` into generation specs for that
character. Fleet-side runner skeleton: cloud-murakumo `services/lora-train/`
(execution gated by ADR-2607155500 Phase 0 — gad ROCm benchmark; weights
never enter git history, DataLad + B2 only).

### 3c. Panel-from-video — seedance clip → frame sample (additive alt. pipeline)

`ai.gftd.mangaka.mangakaGeneratePanelFromVideo` generates a panel WITHOUT a
txt2img render: it drives cloud-murakumo's `:seedance` engine (Seedance 2.0,
ADR-2607170500, `model "seedance-2.0"`) for a short text-to-video clip, then
samples several candidate stills back out of the clip (ffprobe + ffmpeg via
`kotoba-lang/douga`'s pure argv builders) and picks a winner with the SAME
8-axis rubric critique §3's quality loop uses (`mangaka.critique`, factored
out so scores are comparable across pipelines):

```text
plan → generate-video (seedance) → sample-frames (ffmpeg) → critique (8-axis) → persist
```

`mangaka.video` (`clj/src/mangaka/video.cljk`) owns both host-fn steps and
never throws — with no `SEEDANCE_API_KEY`/`MURAKUMO_BACKEND_TOKEN`, an
unreachable backend, or no ffmpeg/ffprobe on PATH, it degrades to a single
placeholder SVG frame (same discipline as `comfyui.gateway`'s stub-render),
so the graph still completes offline. Persisted panels land in the exact
same `:panel/image-b64` / `:panel/image-key` shape `mangakaGeneratePanel`
uses, plus provenance (`:panel/source "seedance-frame-sample"`,
`:panel/video-model`, `:panel/video-source`, `:panel/video-error`,
`:panel/frame-time-ms`, `:panel/frame-count`) — so §4's page-compose step
(`mangakaGeneratePage` / `composeKomawari`) consumes a video-sourced panel
with **zero changes**.

**Additive, not a replacement**: the existing `mangakaGeneratePanel`/
`*Loop`/`*Quality`/`mangakaCoscientistPanel` txt2img graphs are untouched
and remain the default panel pipeline. This is an explicitly-invoked
alternative, per-panel or via the operator loop below.

```bash
curl -s localhost:2024/xrpc/ai.gftd.mangaka.mangakaGeneratePanelFromVideo \
  -d '{:doc-id "gh-arc0-1-p1" :panel-index 0 :frame-count 5 :duration-sec 4}'
```

Auth for the seedance job is `SEEDANCE_API_KEY` (or the generic
`MURAKUMO_BACKEND_TOKEN`) — same env vars `cloud-murakumo.worker/
backend-token` resolves for any `:seedance`-engine caller. No separate
job/poll state machine is needed here (unlike `ai-gftd-animeka`'s
`api.murakumo.cloud` nbb client): `cloud-murakumo.executor/execute`
submits, polls and downloads synchronously (~30min ceiling for `:mp4`).

**Production loop** — `scripts/production-loop-video.cljk` (nbb) discovers
un-rendered panels across documents (`listDocuments` → `loadDocument`'s
`:lexicon :panels` vs `listRenders`), renders them via this NSID, and
assembles (`mangakaGeneratePage`) any document whose panels are now all
rendered. Talks to a running `kbb -M:dev:run` server over `/xrpc/*`
as JSON (never EDN — parse-free in nbb). Ledger:
`docs/production-loop-video-ledger.edn` (append-only, one EDN line per run
— never hand-edit).

```bash
cd orgs/gftdcojp/ai-gftd-mangaka
MANGAKA_SERVER_URL=http://localhost:2024 \
  kbb --backend sci scripts/production-loop-video.cljk --max-renders 3
# --doc-id <id>   restrict to one document
# --no-assemble   render only, skip mangakaGeneratePage
# --dry-run       discover + print targets only
```

⚠ Known gap (pre-existing, not introduced by this pipeline): fully offline
(no ComfyUI *and* no seedance key) `mangakaGeneratePage` fails on a stub
panel — its placeholder is `image/svg+xml`, but the page-compose step
writes panel files as `.png` and reads them with Java `ImageIO` (no SVG
reader registered), so `compose-page!` NPEs. Reproduces identically via the
plain `mangakaGeneratePanel` → `mangakaGeneratePage` path with no ComfyUI
configured — unrelated to seedance. Doesn't manifest once a real backend
(ComfyUI *or* seedance) produces real PNG/JPEG bytes.

## 3d. バージョン公開と切替（versions.edn — ADR-2607165100 addendum 3）

公開バージョンの正本は repo 直下の **`versions.edn`**（append-only）。各
version は D1 上で独立した work 行（rkey）になり、props に
`{"versionGroup": "<元祖rkey>", "versionLabel": "v11 (clj/edn)"}` を
projection する。reader（worker.cljs `versions-of` / render.cljc
`version-nav`）が同じ versionGroup の work 群から**切替バー**を描く —
`/work/<rkey>` と `/api/work/<rkey>`（`:versions` 配列）の両方に出る。

新バージョン公開の手順: ①CLJ チェーンでページ生成（§3 の品質ループ →
komawari 合成 → page-level jumpBenchmarkQa）②R2 に新 blobKey で put
③D1 に work（versionGroup/versionLabel/pipeline/jumpQa 入り props）+
page 行を INSERT ④元祖 work の props にも versionGroup を `json_set` で
追記（内容不変）⑤`versions.edn` に追記して commit。

## 4. Publish to manga.gftd.ai

```bash
cd orgs/gftdcojp/ai-gftd-mangaka/appview/ai-gftd-wasm-mangaka-mng4k4x1
# 4a. images → R2 (cache-bust with a version suffix on re-renders, e.g. -v2)
for p in $(seq 1 N); do pp=$(printf "%02d" $p)
  npx wrangler r2 object put "ai-gftd-cdn/blobs/mng4k4x1.gftd.ai/<work>-p${pp}" \
    --file=/tmp/<work>/page-${pp}.png --content-type=image/png --remote
done
# 4b. rows → D1 (work + chapter + page; props carries author/genre/series/blobKey/workRkey)
npx wrangler d1 execute ai-gftd-mangaka --remote --file=/tmp/<work>_publish.sql
```
The reader auto-lists new works. Verify: `curl https://manga.gftd.ai/api/works`.
Reader `/img/<key>` sets `immutable` cache — **use new blob keys on re-render**
(then `json_set(props,'$.blobKey',…)` on the page rows).

## 5. Tests / CI

```bash
cd orgs/gftdcojp/ai-gftd-mangaka/clj
kbb -M:dev:test
```
CI should target the CLJ test command above.

## gad (EVO-X2) memory note

96 GB unified APU; ROCm reports a 32 GB dedicated-VRAM carve-out, the GPU also
borrows system RAM via GTT. **Keep BIOS UMA at 32/62** — raising it just
relabels the same 96 GB and shrinks the shared pool. Swap pressure comes from
co-location (ComfyUI + llama-server), not the split → fix by distributing load.
`comfyui.service` / `llama-server` / `tailscaled` / `ssh` are enabled (reboot-safe).
