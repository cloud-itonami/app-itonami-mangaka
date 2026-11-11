"""v10 orchestrator — ComfyUI-first per-panel pipeline.

User (2026-05-25): "v10 の pipeline として、openusd を使わない, comfyui を
中心とした生成プロセスで score 評価。panel ごとに 生成パイプラインを
切り替えられるようにも設計してください."

Architecture:
  For each panel:
    1. Pipeline router selects panel pipeline (cu_color/cu_ink/cu_action/...)
    2. v10_panel_render.render_v10_panel() does single-pass SDXL
    3. Panel scored individually (jump_qa for style + manifest_qa for match)
    4. Optional USD bg composite (only if pipeline = *_usd variant)

  Page composite:
    1. render-v5-page.compute_layout() places panels
    2. composite_page() assembles panels + bubbles + SFX
    3. Page-level vision_score for final total

Per-panel scores saved separately so we can identify weak panels for
targeted re-render.

Usage:
  python v10_orchestrator.py [--preset NAME] [--pipeline-default NAME] <page>
"""
from __future__ import annotations
import json, sys, time, os, importlib.util
from pathlib import Path
from typing import Optional
from PIL import Image


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


_PROJ = Path(__file__).parent.parent
V10_RENDER = _load("v10_panel_render", str(_PROJ / "lg_mangaka/v10_panel_render.py"))
V10_ROUTER = _load("v10_pipeline_router", str(_PROJ / "lg_mangaka/v10_pipeline_router.py"))
RENDER_V5 = _load("rv5", str(_PROJ / "scripts/render-v5-page.py"))
JUMP_QA = _load("jbq", str(_PROJ / "lg_mangaka/jump_benchmark_qa.py"))
MANIFEST_QA = _load("mmq", str(_PROJ / "lg_mangaka/manifest_match_qa.py"))
FA = _load("first_axes", str(_PROJ / "lg_mangaka/first_axes.py"))

# Manifest path is env-overridable (MANGAKA_MANIFEST) so the orchestrator runs
# from any checkout, not just the original hardcoded working copy. The sibling
# story-outline.jsonld is loaded relative to this path (STEP F).
MANIFEST = Path(os.environ.get(
    "MANGAKA_MANIFEST",
    "/Users/junkawasaki/gftdcojp/ai-gftd-apps-gftdcojp/60-apps/ai-gftd-project-mangaka/data/ghosthacker/resources/episodes/arc0-1-origin/image-gen-manifest.json",
))
SCENE_MAPPING = {
    0:"yuto-bedroom", 1:"school-hierarchy", 2:"school-hierarchy",
    3:"city-street", 4:"yuto-bedroom", 5:"yuto-bedroom",
}


def score_panel_image(panel_img: Path, panel: dict, scene_slug: str) -> dict:
    """Score a SINGLE panel image: jump_qa style + manifest_qa match.

    Returns: {jump_qa, manifest_qa, total_panel}
    """
    if not panel_img or not panel_img.exists():
        return {"error": "no image", "total_panel": 0}
    # jump_qa (style — already best-of-5 internal)
    try:
        jr = JUMP_QA.score_page(panel_img, n_samples=3)
        # 2026-05-27: SFX + bubbles are added AT composite stage, not in
        # per-panel rendering. Strip those axes here so they don't drag
        # down per-panel score with structural zeros (D analysis finding).
        PANEL_DROP = {"sfx_text", "bubble_integration"}
        if "scores" in jr:
            jr["scores"] = {k: v for k, v in jr["scores"].items()
                              if k not in PANEL_DROP}
            # Recompute total with renormalized weights
            from lg_mangaka.jump_benchmark_qa import WEIGHTS as _W
            keep_w = {k: v for k, v in _W.items() if k not in PANEL_DROP}
            wsum = sum(keep_w.values()) or 1.0
            jr["total"] = round(
                sum((keep_w.get(k, 0) / wsum) * jr["scores"].get(k, 0) * 10
                    for k in keep_w), 1)
        jump_t = jr.get("total", 0)
    except Exception as e:
        jump_t = 0; jr = {"error": str(e)}

    # manifest_qa (matched against ONLY this panel)
    try:
        mr = MANIFEST_QA.score_page(panel_img, [panel], scene_slug, n_samples=3)
        mfst_t = mr.get("total", 0)
    except Exception as e:
        mfst_t = 0; mr = {"error": str(e)}

    # Combine 50/50 (no heuristic at panel level — too noisy)
    total_panel = round(0.5 * jump_t + 0.5 * mfst_t, 1)
    return {
        "jump_qa": jr,
        "manifest_qa": mr,
        "total_panel": total_panel,
    }


def render_page_v10(page_num: int, preset_name: Optional[str] = None,
                     pipeline_default: Optional[str] = None):
    """Render one page with v10 ComfyUI-first per-panel pipelines."""
    manifest = json.loads(MANIFEST.read_text())
    panels = sorted([p for p in manifest["panels"] if p["pageNum"] == page_num],
                     key=lambda p: p["panelIndex"])
    # 2026-05-30 — STEP F: story-outline.jsonld canonical source injection.
    # User feedback: image-gen-manifest's generic 'visual' fields don't capture
    # scene intent. story-outline.jsonld has rich gh:setting/visualNote/script.
    if os.environ.get("V11_STORY_CANONICAL", "1") == "1":
        try:
            from lg_mangaka import v11_story_canonical as _sc
            outline = _sc.load_story_outline(MANIFEST)
            page_story = _sc.get_page_story(outline, page_num)
            if page_story:
                _sc.attach_story_to_panels(panels, page_story)
                vc = (page_story.get("gh:visualNote") or "")[:80]
                pov = page_story.get("gh:pov", "?")
                act = page_story.get("gh:act", "")
                print(f"  [story-canonical] pov={pov} act={act} visualNote={vc!r}")
        except Exception as e:
            print(f"  [story-canonical] skipped: {e}")
    # 2026-05-29 — STEP B: page layout type detection + override
    page_layout_type = "standard_grid"
    if os.environ.get("V11_PAGE_LAYOUT", "1") == "1":
        try:
            from lg_mangaka import v11_page_layout as _pl
            page_layout_type = _pl.detect_page_layout_type(panels)
            panels = _pl.apply_page_layout_override(panels, page_layout_type)
            # Inject page_arc_summary into each panel for prompt D-step
            arc = _pl.page_arc_summary(panels, page_layout_type)
            for p in panels:
                p["_page_arc"] = arc
                p["_page_layout_type"] = page_layout_type
            print(f"  [page-layout] type={page_layout_type}  arc={arc!r}")
        except Exception as e:
            print(f"  [page-layout] skipped: {e}")

    # 2026-05-30 — STEP E: story comprehension pass (Gemma reads whole page)
    if os.environ.get("V11_STORY", "1") == "1":
        try:
            from lg_mangaka import v11_story_comprehension as _story
            scene_for_story = SCENE_MAPPING.get(page_num, "yuto-bedroom")
            page_story = _story.get_story_for_page(page_num, panels, scene_for_story)
            print(f"  [story] {page_story.get('page_summary','')[:80]!r}")
            print(f"  [story] journey: {page_story.get('reader_journey','')[:80]!r}")
            # Attach per-panel intent to each panel for downstream prompt build
            for p in panels:
                intent = _story.panel_intent_text(page_story, p["panelIndex"])
                p["_story_summary"] = page_story.get("page_summary", "")
                p["_reader_journey"] = page_story.get("reader_journey", "")
                p["_panel_intent"] = intent
        except Exception as e:
            print(f"  [story] skipped: {e}")
    # v11 (2026-05-27): augment with bleed/angle when V11_LAYOUT=1
    if os.environ.get("V11_LAYOUT", "0") == "1":
        try:
            from lg_mangaka import v11_layout as _v11
            panels = _v11.augment_page(panels, page_num)
            print(f"  [v11] augmented {len(panels)} panels with bleed/angle")
        except Exception as e:
            print(f"  [v11] augment skipped: {e}")
    scene_slug = SCENE_MAPPING.get(page_num, "yuto-bedroom")
    layout = RENDER_V5.compute_layout(panels)
    page_seed = page_num * 7919 + 12345 + int(os.environ.get("KAIZEN_SEED_OFFSET", "0"))

    print(f"=== v10 Page {page_num} (ComfyUI-first) ===")
    print(f"  scene={scene_slug}, {len(panels)} panels, preset={preset_name or 'none'}")
    print(f"  pipeline_default={pipeline_default or '(via router)'}")

    panel_files = {}
    panel_scores = {}
    page_start = time.monotonic()

    for slot in layout:
        p = slot["panel"]; idx = slot["idx"]
        panel_w, panel_h = slot["w"] * 2, slot["h"] * 2

        # Pipeline routing
        if preset_name:
            pipeline = V10_ROUTER.select_pipeline_for_preset(p, preset_name)
        elif pipeline_default:
            pipeline = V10_ROUTER.select_pipeline(p, page_default=pipeline_default)
        else:
            pipeline = V10_ROUTER.select_pipeline(p)

        print(f"\n  panel {idx}: pipeline={pipeline}")
        print(f"    shot={p.get('shot','?')} tone={p.get('tone','?')} "
              f"chars={p.get('focusedCharacters',[])}")

        t0 = time.monotonic()
        out = V10_RENDER.render_v10_panel(p, scene_slug, panel_w, panel_h,
                                            pipeline, page_seed)
        render_s = time.monotonic() - t0
        if out:
            panel_files[idx] = str(out)
            # Score this panel (skippable for fast style A/B via SKIP_SCORING=1)
            t0 = time.monotonic()
            if os.environ.get("SKIP_SCORING") == "1":
                ps = {"total_panel": 0.0,
                       "jump_qa": {"total": 0.0, "axes": {}},
                       "manifest_qa": {"total": 0.0, "axes": {}},
                       "axes": {}, "issues": [], "improvement_hints": []}
            else:
                ps = score_panel_image(out, p, scene_slug)
            score_s = time.monotonic() - t0
            panel_scores[idx] = ps
            print(f"    rendered ({render_s:.1f}s) | score {ps['total_panel']:.1f} "
                  f"(j={ps.get('jump_qa',{}).get('total',0):.1f} "
                  f"m={ps.get('manifest_qa',{}).get('total',0):.1f}) | "
                  f"scoring {score_s:.1f}s | pipeline={pipeline}")
        else:
            print(f"    FAILED render ({render_s:.1f}s)")

    # Page composite — SKIP Obata cleanup since v10 SDXL outputs already
    # include Death Note style from prompt. Double-processing causes:
    #   - posterize 4 levels → loses SDXL midtones (creates "boke" feel)
    #   - UnsharpMask 150% → halos around already-sharp ink edges
    #   - contrast 1.4 → squashes fabric/shadow midtones to black/white
    # User (2026-05-25): "なんとなくボケているような違和感がある"
    RENDER_V5.CURRENT_PAGE_PANELS = panels
    RENDER_V5.CURRENT_SCENE_SLUG = scene_slug
    prev_obata = os.environ.get("V5_OBATA")
    os.environ["V5_OBATA"] = "0"   # v10: skip — SDXL already Death Note style
    try:
        # v13.5 page-first eval: save Stage 1 (panels only, no bubble/SFX)
        # for per-stage human eval.
        if os.environ.get("V13_PAGE_FIRST") == "1":
            print(f"\n  [eval] composing Stage 1 (panels only, no bubble/SFX)...")
            stage1 = RENDER_V5.composite_page(page_num, layout, panel_files,
                                                iter_idx=0, add_bubbles=False)
            from shutil import copy as _copy
            _copy(stage1, f"/tmp/v13-p{page_num:02d}-stage1-base.png")
            print(f"  [eval] saved /tmp/v13-p{page_num:02d}-stage1-base.png")
        print(f"\n  composing {len(panel_files)} panels (Obata cleanup skipped for v10)...")
        comp = RENDER_V5.composite_page(page_num, layout, panel_files,
                                          iter_idx=0, add_bubbles=True)
        if os.environ.get("V13_PAGE_FIRST") == "1":
            from shutil import copy as _copy
            _copy(comp, f"/tmp/v13-p{page_num:02d}-stage3-bubbles.png")
            print(f"  [eval] saved /tmp/v13-p{page_num:02d}-stage3-bubbles.png")
    finally:
        if prev_obata is None: os.environ.pop("V5_OBATA", None)
        else: os.environ["V5_OBATA"] = prev_obata
    if os.environ.get("SKIP_SCORING") == "1":
        page_score = {"total": 0, "jump_tier_label": "skipped"}
    else:
        page_score = RENDER_V5.vision_score(comp)
    page_total = page_score.get("total", 0)

    elapsed = time.monotonic() - page_start
    print(f"\n=== Page {page_num} v10 done ({elapsed:.0f}s) ===")
    print(f"  PAGE TOTAL: {page_total}/100  ({page_score.get('jump_tier_label','?')})")
    print(f"  per-panel scores:")
    for idx, ps in sorted(panel_scores.items()):
        print(f"    panel {idx}: {ps['total_panel']:.1f}/100")

    # Save outputs — 2026-05-26: skip overlay_score (user feedback: don't burn
    # the 91/100 badge into the final image; gallery reads the sidecar JSON).
    # Apply the SMOOTH+UnsharpMask recipe (ADR-2605260100 winning kaizen, 90.6/100).
    final = Path(f"/tmp/v10-p{page_num:02d}-scored.png")
    from PIL import Image as _PILImage, ImageFilter as _PILFilter
    _img = _PILImage.open(comp)
    _img = _img.filter(_PILFilter.SMOOTH)
    _img = _img.filter(_PILFilter.UnsharpMask(radius=1.5, percent=80, threshold=2))
    _img.save(final)
    # Re-score the post-processed final (recipe nets ~+8 over raw comp).
    if os.environ.get("SKIP_SCORING") != "1":
        try:
            page_score = RENDER_V5.vision_score(final)
            page_total = page_score.get("total", page_total)
            print(f"  POST-RECIPE TOTAL: {page_total}/100  ({page_score.get('jump_tier_label','?')})")
        except Exception as e:
            print(f"  [recipe rescore] skipped: {e}")
    sidecar = Path(f"/tmp/v10-p{page_num:02d}-score.json")
    # v11 D (2026-05-27): tensor network composite scoring across panels.
    # Builds per-panel × per-axis tensor, decomposes for style/dynamism factors.
    tensor_score = None
    try:
        from lg_mangaka import v11_tensor_score as _ts
        tn_panels = []
        ordered_panels = []
        for idx in sorted(panel_scores.keys()):
            ps = panel_scores[idx]
            jr = ps.get("jump_qa", {})
            scores = jr.get("scores", {})
            if scores:
                tn_panels.append({"scores": scores})
                # find the manifest panel
                mpanel = next((p for p in panels if p["panelIndex"] == idx), None)
                if mpanel:
                    ordered_panels.append(mpanel)
        if tn_panels:
            # 2026-05-27 B2: panel-importance weighted tensor
            importance = _ts.panel_importance_from_manifest(ordered_panels) \
                          if ordered_panels else None
            tensor_score = _ts.page_tensor_score(tn_panels,
                              panel_importance=importance)
            print(f"  TENSOR SCORE: {tensor_score.get('total')}/100  "
                  f"mean={tensor_score.get('mean')} style_var={tensor_score.get('style_variance')} "
                  f"dyn_var={tensor_score.get('dynamism_variance')}")
    except Exception as e:
        print(f"  [tensor] skipped: {e}")
    page_score["version"] = {
        "v5_base": "v10",
        "engine": "ComfyUI-first",
        "preset": preset_name,
        "pipeline_default": pipeline_default,
        "panel_pipelines": {idx: V10_ROUTER.select_pipeline_for_preset(
            next(p for p in panels if p["panelIndex"] == idx),
            preset_name or "ghosthacker")
            for idx in panel_files},
        "panel_scores": {str(k): v["total_panel"] for k, v in panel_scores.items()},
        "panel_axes":   {str(k): v.get("jump_qa", {}).get("scores", {})
                         for k, v in panel_scores.items()},
        "tensor_score": tensor_score,
        "rendered_at": int(time.time()),
    }
    sidecar.write_text(json.dumps(page_score, indent=2, ensure_ascii=False))
    print(f"\n  saved: {final}")
    print(f"  scores: {sidecar}")
    return page_score


if __name__ == "__main__":
    argv = sys.argv[1:]
    preset = None; pipeline_def = None; pages = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--preset" and i + 1 < len(argv):
            preset = argv[i + 1]; i += 2; continue
        if a == "--pipeline-default" and i + 1 < len(argv):
            pipeline_def = argv[i + 1]; i += 2; continue
        if a.isdigit():
            pages.append(int(a)); i += 1; continue
        i += 1
    if not pages: pages = [0]
    for pg in pages:
        render_page_v10(pg, preset_name=preset, pipeline_default=pipeline_def)
