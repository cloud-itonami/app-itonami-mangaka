"""v8 color orchestrator — full color action manga pipeline.

Reference: JoJo Part 5 / Initial D — color action manga 90/100 target.

Pipeline (vs v7):
  Stage A: pose extract (reuse from v7)
  Stage C: color character render via Pony Diffusion V6 XL
  Stage D: color bg render via Pony Diffusion V6 XL
           (full SDXL, no monochrome filter, photo-real environment)
  Stage E: composite (NO Obata cleanup) + color SFX gradient kana

Score against jump_color_qa (8 axes against JoJo Part 5).

Usage:
  python v8_color_orchestrator.py [--preset NAME] <page_num> [...]
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
POSE_MOD  = _load("pose_designer", str(_PROJ / "lg_mangaka/pose_designer.py"))
V8_COLOR  = _load("v8_color_render", str(_PROJ / "lg_mangaka/v8_color_render.py"))
SFX_COLOR = _load("color_sfx_overlay", str(_PROJ / "scripts/color_sfx_overlay.py"))
JUMP_COLOR_QA = _load("jump_color_qa", str(_PROJ / "lg_mangaka/jump_color_qa.py"))
RENDER_V5 = _load("rv5", str(_PROJ / "scripts/render-v5-page.py"))
FA        = _load("first_axes", str(_PROJ / "lg_mangaka/first_axes.py"))

MANIFEST = Path("/Users/junkawasaki/gftdcojp/ai-gftd-apps-gftdcojp/60-apps/ai-gftd-project-mangaka/data/ghosthacker/resources/episodes/arc0-1-origin/image-gen-manifest.json")

SCENE_MAPPING = {
    0:"yuto-bedroom", 1:"school-hierarchy", 2:"school-hierarchy",
    3:"city-street", 4:"yuto-bedroom", 5:"yuto-bedroom",
}


def render_panel_v8(panel: dict, scene_slug: str, panel_w: int, panel_h: int,
                     page_seed: int, axes=None) -> Path:
    """v8 color panel: bg (color SDXL) + char (color SDXL) composite."""
    idx = panel.get("panelIndex", 0)
    spec = POSE_MOD.design_v7_panel(panel)
    bg_out = Path(f"/tmp/v8-bg-pg-p{idx:02d}.png")

    # Stage D: color bg
    bg = V8_COLOR.render_bg_color(scene_slug, panel_w, panel_h, bg_out, page_seed)
    if not bg or not bg.exists():
        # Fallback: medium grey for color (not pure white — would clash with palette)
        Image.new("RGB", (panel_w, panel_h), (180, 180, 200)).save(bg_out)
        bg = bg_out

    # Stage C: color characters per slot
    focal_chars = panel.get("focusedCharacters") or []
    final = Image.open(bg).convert("RGBA")
    char_count = min(2, len(focal_chars))
    if char_count > 0:
        slot_w = panel_w // char_count
    for ch_idx, ch in enumerate(focal_chars[:2]):
        pose_info = spec["poses"].get(ch)
        if not pose_info: continue
        char_png = V8_COLOR.render_character_color(
            ch, pose_info["pose"], pose_info["emotion"],
            spec["shot_cat"], panel_w, panel_h, page_seed, idx * 10 + ch_idx)
        if not char_png: continue
        char_alpha = char_png.with_name(char_png.stem + "_alpha.png")
        V8_COLOR.extract_character_alpha_color(char_png, char_alpha)
        char_im = Image.open(char_alpha).convert("RGBA")
        ratio = min(slot_w / char_im.width, panel_h / char_im.height)
        new_w = max(1, int(char_im.width * ratio))
        new_h = max(1, int(char_im.height * ratio))
        char_im = char_im.resize((new_w, new_h), Image.LANCZOS)
        slot_x_start = ch_idx * slot_w
        x_offset = slot_x_start + (slot_w - new_w) // 2
        if char_count == 1:
            pos = pose_info.get("position", "center")
            x_offset = {"left":      0,
                         "far-left":  -new_w // 6,
                         "right":     panel_w - new_w,
                         "far-right": panel_w - new_w + new_w // 6,
                         "center":    (panel_w - new_w) // 2}.get(
                pos, (panel_w - new_w) // 2)
        pose_name = pose_info.get("pose", "")
        if pose_name.startswith(("standing", "walking", "leaning", "running")):
            y_offset = panel_h - new_h
        else:
            y_offset = (panel_h - new_h) // 2
        y_offset = max(0, y_offset)
        final.paste(char_im, (x_offset, y_offset), char_im)

    out_path = Path(f"/tmp/v8-pg-panel-{idx:02d}.png")
    final.convert("RGB").save(out_path)
    return out_path


def render_page_v8(page_num: int, axes=None):
    manifest = json.loads(MANIFEST.read_text())
    panels = sorted([p for p in manifest["panels"] if p["pageNum"] == page_num],
                     key=lambda p: p["panelIndex"])
    scene_slug = SCENE_MAPPING.get(page_num, "yuto-bedroom")
    layout = RENDER_V5.compute_layout(panels)
    page_seed = page_num * 7919 + 12345 + int(os.environ.get("KAIZEN_SEED_OFFSET", "0"))

    print(f"=== v8 COLOR Page {page_num} ===")
    print(f"  scene={scene_slug}, {len(panels)} panels, model={V8_COLOR.CKPT}")

    panel_files = {}
    for slot in layout:
        p = slot["panel"]; idx = slot["idx"]
        t0 = time.monotonic()
        out = render_panel_v8(p, scene_slug, slot["w"]*2, slot["h"]*2,
                                page_seed, axes=axes)
        elapsed = time.monotonic() - t0
        if out:
            panel_files[idx] = str(out)
            print(f"    panel {idx} rendered ({elapsed:.1f}s)")

    # Disable Obata for v8 — we want to preserve color
    prev_obata = os.environ.get("V5_OBATA")
    os.environ["V5_OBATA"] = "0"
    # Also disable B&W SFX (we'll use color SFX after)
    prev_sfx = os.environ.get("V5_SFX")
    os.environ["V5_SFX"] = "0"

    RENDER_V5.CURRENT_PAGE_PANELS = panels
    RENDER_V5.CURRENT_SCENE_SLUG = scene_slug
    comp = RENDER_V5.composite_page(page_num, layout, panel_files,
                                      iter_idx=0, add_bubbles=True)

    # Restore env
    if prev_obata is None: os.environ.pop("V5_OBATA", None)
    else: os.environ["V5_OBATA"] = prev_obata
    if prev_sfx is None: os.environ.pop("V5_SFX", None)
    else: os.environ["V5_SFX"] = prev_sfx

    # Color SFX overlay
    try:
        _, added = SFX_COLOR.overlay_color_sfx_on_composite(
            comp, layout, [s["panel"] for s in layout], comp, size_pct=0.45)
        if added:
            print(f"    [Color SFX] {len(added)} overlays: "
                  f"{', '.join(f'p{i}={s} ({p})' for i,s,p in added[:3])}")
    except Exception as e:
        print(f"    [Color SFX] skipped: {e}")

    # Score using color QA
    color_score = JUMP_COLOR_QA.score_color_page(comp)
    print(f"\n  → COLOR QA: {color_score['total']}/100 ({color_score['label']})")
    print(f"     verdict: {color_score.get('verdict','')[:120]}")
    for axis, w in JUMP_COLOR_QA.WEIGHTS.items():
        s = color_score['scores'].get(axis, 0)
        print(f"     {axis:30s} {s:4.1f}")

    # Save
    final = Path(f"/tmp/v8-color-p{page_num:02d}-scored.png")
    # Overlay score text (reuse v5 helper but format for color)
    import shutil
    shutil.copy2(comp, final)
    sidecar = Path(f"/tmp/v8-color-p{page_num:02d}-score.json")
    color_score["version"] = {
        "v8_color": True, "ckpt": "ponyDiffusionV6XL",
        "rendered_at": int(time.time()),
    }
    sidecar.write_text(json.dumps(color_score, indent=2, ensure_ascii=False))
    print(f"  saved: {final}")
    return color_score


if __name__ == "__main__":
    argv = sys.argv[1:]
    preset = None; pages = []
    i = 0
    while i < len(argv):
        if argv[i] == "--preset" and i + 1 < len(argv):
            preset = argv[i + 1]; i += 2; continue
        if argv[i].isdigit():
            pages.append(int(argv[i])); i += 1; continue
        i += 1
    if not pages: pages = [0]
    axes = FA.load_preset(preset) if preset else None
    if axes is not None:
        env = FA.resolve_env(axes)
        for k, v in env.items():
            os.environ[k] = v
    for pg in pages:
        render_page_v8(pg, axes=axes)
