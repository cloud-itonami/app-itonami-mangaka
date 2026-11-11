"""v7 orchestrator — character-first manga pipeline end-to-end.

Pipeline:
  Stage A: pose_designer.design_v7_panel(panel) → per-char poses + cameras
  Stage C: v7_character_render.render_character_panel() → transparent char
  Stage D: v7_bg_render.render_bg() → background layer
  Stage E: composite + ink cleanup + SFX + bubbles

Output: page composite per layout, scored via existing vision_score().
"""
from __future__ import annotations
import json, sys, time, os, importlib.util
from pathlib import Path
from typing import Optional
from PIL import Image

# Load modules — register in sys.modules so dataclasses can introspect
def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m

_PROJ = Path(__file__).parent.parent
POSE_MOD   = _load("pose_designer", str(_PROJ / "lg_mangaka/pose_designer.py"))
CHAR_MOD   = _load("v7_character_render", str(_PROJ / "lg_mangaka/v7_character_render.py"))
BG_MOD     = _load("v7_bg_render", str(_PROJ / "lg_mangaka/v7_bg_render.py"))
RENDER_V5  = _load("rv5", str(_PROJ / "scripts/render-v5-page.py"))
FA         = _load("first_axes", str(_PROJ / "lg_mangaka/first_axes.py"))

MANIFEST = Path("/Users/junkawasaki/gftdcojp/ai-gftd-apps-gftdcojp/60-apps/ai-gftd-project-mangaka/data/ghosthacker/resources/episodes/arc0-1-origin/image-gen-manifest.json")

SCENE_MAPPING = {
    0:"yuto-bedroom", 1:"school-hierarchy", 2:"school-hierarchy",
    3:"city-street", 4:"yuto-bedroom", 5:"yuto-bedroom",
}


def render_panel_v7(panel: dict, scene_slug: str, panel_w: int, panel_h: int,
                     page_seed: int,
                     axes: Optional["FA.FirstAxes"] = None) -> Path:
    """v7 panel render: character + background → composite.

    axes: optional first_axes vector. When provided, axes override the
    tone-only bg-mode selection and gate the SDXL realistic bg path.
    """
    idx = panel.get("panelIndex", 0)
    spec = POSE_MOD.design_v7_panel(panel)

    # Stage D: background. Pipeline order driven by FA.pipeline_priority
    # (weight-based per dominant axis):
    #   character-dominant → skip SDXL bg for has_focal, char takes panel
    #   space-dominant     → full SDXL bg, char placed in
    #   mood-dominant      → mood hatching atmosphere
    #   shot-dominant      → SDXL framing-aware
    bg_out = Path(f"/tmp/v7-bg-pg-p{idx:02d}.png")
    tone = panel.get("tone", "quiet")
    shot = (panel.get("shot") or "").lower()
    has_focal = bool(panel.get("focusedCharacters") or [])

    pipeline = FA.pipeline_priority(axes) if axes is not None else None
    action_tone = any(t in (tone or "").lower()
                       for t in ("shock", "intense", "dramatic", "tense", "impact"))

    # ADR-2605241500 weight-based: character-first preset (Jump shonen)
    # SKIPS expensive SDXL bg for character panels and uses solid white
    # → character takes panel focus (the user's screenshot showed this
    # works visually). Saves ~75s per char panel.
    if pipeline and pipeline.get("skip_bg_for_focal") and has_focal:
        force_realistic = False
        force_symbolic  = False
        force_white     = True
    else:
        force_realistic = has_focal or not action_tone
        force_symbolic  = (not has_focal) and action_tone
        force_white     = False

    if axes is not None:
        if force_white:
            # Write white panel directly — skip SDXL bg entirely for
            # character-dominant + focal panels (Jump-style char-on-white).
            Image.new("RGB", (panel_w, panel_h), "white").save(bg_out)
            bg = bg_out
            bg_mode = "white"
            # Skip the BG_MOD.render_bg() call below — bg already written.
            _need_render_bg = False
        else:
            _need_render_bg = True
            if force_symbolic:
                mode = "symbolic"
                os.environ.pop("V7_REALISTIC_BG", None)
            elif force_realistic:
                mode = "realistic"
                os.environ["V7_REALISTIC_BG"] = "1"
            else:
                mode = FA.bg_mode(axes, tone)
                if mode == "realistic" and FA.render_realistic_bg_enabled(axes):
                    os.environ["V7_REALISTIC_BG"] = "1"
                else:
                    os.environ.pop("V7_REALISTIC_BG", None)
        if _need_render_bg:
            _orig_pick = BG_MOD.pick_bg_mode
            BG_MOD.pick_bg_mode = lambda _tone, _m=mode: _m
            try:
                bg, bg_mode = BG_MOD.render_bg(scene_slug, panel_w, panel_h,
                                                tone, bg_out, page_seed,
                                                visual_hint=panel.get("visual", ""))
            finally:
                BG_MOD.pick_bg_mode = _orig_pick
    else:
        if force_realistic:
            os.environ["V7_REALISTIC_BG"] = "1"
        bg, bg_mode = BG_MOD.render_bg(scene_slug, panel_w, panel_h,
                                        tone, bg_out, page_seed,
                                        visual_hint=panel.get("visual", ""))

    # Stage C: render focal character only (panel-local position)
    # Composite math fix (2026-05-25): scale char so the FULL figure fits
    # inside the panel (preserving aspect), don't force-match panel_h
    # because portrait char on wide panel was bleeding horizontally → only
    # legs visible. Use "fit-contain" + multi-char horizontal slicing.
    focal_chars = panel.get("focusedCharacters") or []
    final = Image.open(bg).convert("RGBA")
    char_count = min(2, len(focal_chars))
    if char_count > 0:
        # Slice panel width per character so multiple chars don't overlap
        slot_w = panel_w // char_count
    for ch_idx, ch in enumerate(focal_chars[:2]):
        pose_info = spec["poses"].get(ch)
        if not pose_info: continue
        char_png = CHAR_MOD.render_character_panel(
            ch, pose_info["pose"], pose_info["emotion"],
            spec["shot_cat"], panel_w, panel_h, page_seed, idx * 10 + ch_idx,
            visual_hint=panel.get("visual", ""))
        if not char_png: continue
        char_alpha = char_png.with_name(char_png.stem + "_alpha.png")
        CHAR_MOD.extract_character_alpha(char_png, char_alpha)
        char_im = Image.open(char_alpha).convert("RGBA")
        # FIT-CONTAIN: pick the smaller ratio so figure fully fits in slot.
        ratio = min(slot_w / char_im.width, panel_h / char_im.height)
        new_w = max(1, int(char_im.width * ratio))
        new_h = max(1, int(char_im.height * ratio))
        char_im = char_im.resize((new_w, new_h), Image.LANCZOS)
        # Horizontal: center within character's panel-slot
        slot_x_start = ch_idx * slot_w
        x_offset = slot_x_start + (slot_w - new_w) // 2
        # Override slot center based on pose position when single char
        if char_count == 1:
            pos = pose_info.get("position", "center")
            x_offset = {"left":      0,
                         "far-left":  -new_w // 6,
                         "right":     panel_w - new_w,
                         "far-right": panel_w - new_w + new_w // 6,
                         "center":    (panel_w - new_w) // 2}.get(
                pos, (panel_w - new_w) // 2)
        # Vertical: place feet at panel bottom for standing/walking poses,
        # center for sitting/portrait poses
        pose_name = pose_info.get("pose", "")
        if pose_name.startswith(("standing", "walking", "leaning", "running")):
            y_offset = panel_h - new_h    # feet at bottom
        else:
            y_offset = (panel_h - new_h) // 2  # vertically centered
        y_offset = max(0, y_offset)
        final.paste(char_im, (x_offset, y_offset), char_im)
    out_path = Path(f"/tmp/v7-pg-panel-{idx:02d}.png")
    final.convert("RGB").save(out_path)
    return out_path


def render_page_v7(page_num: int, axes: Optional["FA.FirstAxes"] = None):
    manifest = json.loads(MANIFEST.read_text())
    panels = sorted([p for p in manifest["panels"] if p["pageNum"] == page_num],
                     key=lambda p: p["panelIndex"])
    scene_slug = SCENE_MAPPING.get(page_num, "yuto-bedroom")
    layout = RENDER_V5.compute_layout(panels)
    page_seed = page_num * 7919 + 12345 + int(os.environ.get("KAIZEN_SEED_OFFSET", "0"))

    # Apply resolver env so per-stage code (v7_character_render IPAdapter,
    # img2img-stylize, render-v5 v5/v6 path) sees axes-derived V5_USE_*.
    if axes is not None:
        resolved = FA.resolve_env(axes)
        for k, v in resolved.items():
            os.environ[k] = v
        # Weight-based pipeline budget — character-dominant gets 28 steps
        pipeline = FA.pipeline_priority(axes)
        os.environ["V7_CHAR_STEPS"] = str(pipeline["char_steps"])

    print(f"=== Page {page_num} v7 character-first ===")
    print(f"  scene={scene_slug}, {len(panels)} panels")
    if axes is not None:
        top = ", ".join(f"{a}={w:.2f}" for a, w in axes.top_n(3))
        emph = FA.composite_emphasis(axes)
        print(f"  axes: preset={axes.preset or 'custom'} "
              f"dominant={axes.dominant()} top3=({top})")
        print(f"  composite emphasis: sfx={emph['sfx']:.2f} "
              f"ink={emph['ink']:.2f} hatching={emph['hatching']:.2f}")
        ipa_flag = "ON" if os.environ.get("V5_USE_IPADAPTER") == "1" else "off"
        print(f"  env: V5_USE_IPADAPTER={ipa_flag}  V7_POSE_LIB="
              f"{os.environ.get('V7_POSE_LIB','?')}")
    panel_files = {}
    for slot in layout:
        p = slot["panel"]; idx = slot["idx"]
        t0 = time.monotonic()
        out = render_panel_v7(p, scene_slug, slot["w"]*2, slot["h"]*2,
                                page_seed, axes=axes)
        elapsed = time.monotonic() - t0
        if out:
            panel_files[idx] = str(out)
            print(f"    panel {idx} rendered ({elapsed:.1f}s)")

    # Composite via existing render-v5 composite_page
    # ADR-2605241500: pass composite_emphasis so SFX size + Obata ink
    # cleanup intensity are driven by axes (not just bg_mode).
    RENDER_V5.CURRENT_PAGE_PANELS = panels
    RENDER_V5.CURRENT_SCENE_SLUG = scene_slug
    emph = FA.composite_emphasis(axes) if axes is not None else None
    comp = RENDER_V5.composite_page(page_num, layout, panel_files,
                                      iter_idx=0, add_bubbles=True,
                                      composite_emphasis=emph)
    score = RENDER_V5.vision_score(comp)
    print(f"\n  → {score['total']}/100 ({score['jump_tier_label']})")
    print(f"     jump_qa={score.get('jump_qa',{}).get('total')}  "
          f"manifest_qa={score['scores'].get('manifest_qa_total')}")

    # Save
    final = Path(f"/tmp/gh-arc0-1-v5plus-p{page_num:02d}-scored.png")
    RENDER_V5.overlay_score(comp, score, final)
    sidecar = Path(f"/tmp/gh-arc0-1-v5plus-p{page_num:02d}-score.json")
    score["version"] = {
        "v5_base": "v7", "engine": "EEVEE+SDXL",
        "first_axes": (axes.to_dict() if axes is not None else None),
        "composite_emphasis": (FA.composite_emphasis(axes)
                                 if axes is not None else None),
        "rendered_at": int(time.time()),
    }
    sidecar.write_text(json.dumps(score, indent=2, ensure_ascii=False))
    print(f"  saved: {final}")
    return score


if __name__ == "__main__":
    # CLI: [--preset NAME] [--axes K=V,...] <page_num> [page_num ...]
    axes, rest = FA.resolve_from_argv(sys.argv[1:])
    if axes is None and not rest:
        print("usage: v7_orchestrator.py [--preset NAME] [--axes K=V,...] "
              "<page_num> [page_num ...]")
        sys.exit(1)
    if axes is not None:
        top = ", ".join(f"{a}={w:.2f}" for a, w in axes.top_n(3))
        print(f"[first-axes] preset={axes.preset or 'custom'} "
              f"dominant={axes.dominant()} top3=({top})")
    pages = [int(a) for a in rest] if rest else [1]
    for page in pages:
        render_page_v7(page, axes=axes)
