"""v14 Storyboard renderer — Lexicon JSON → Modal H100 → proper A4 page.

Pipeline:
  1. Load ai.gftd.mangaka.storyboard Lexicon JSON
  2. Compute page layout (panel rects) at A4 manga resolution (1456×2064)
  3. Per panel: select SDXL aspect (832×1216 portrait, 1216×832 landscape,
     1024×1024 square) based on rect aspect
  4. Submit panel_clean_workflow to Modal ComfyUI (no IPA/CN — proven cleanest)
  5. Composite panels onto A4 canvas with proper resize
  6. Apply bubble_v2 (5 shape variants + vertical Japanese 句読点-aware)
  7. Apply sfx_overlay (context-aware quadrant placement)
  8. Final SMOOTH + UnsharpMask post-process
  9. Save high-res PNG + storyboard sidecar

Why v14 vs prior:
  - Native SDXL resolution per panel (no downscale destroys detail)
  - Page composite at A4 manga size (1456×2064 portrait)
  - Uses existing bubble_v2.py + sfx_overlay.py (proven utilities)
  - Lexicon JSON storyboard as input (separate from old manifest)

CLI:
  python -m lg_mangaka.v14_storyboard_renderer <storyboard.json>
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import sys
import time
from pathlib import Path

# A4 manga page (Japanese B5 actual but close enough; ratio = 1.42)
PAGE_W = 1456
PAGE_H = 2064

# SDXL aspects we choose between
ASPECTS = {
    "portrait": (832, 1216),
    "landscape": (1216, 832),
    "square": (1024, 1024),
}

# Positive-side monochrome anchor. The negative prompt suppresses color, but
# Animagine XL still leaks color unless the positive prompt also asks for B&W.
# Prepended to every panel's positive so manga output stays monochrome even
# when a storyboard's baseTags omit it (mirrors v10 QUALITY_INK / v11 anchors).
MONO_ANCHOR = "monochrome, greyscale, high contrast black ink lineart"

# Color style anchor for arcs rendered in color (Animagine XL 4.0 stable look).
# Applied only when the page base-tags do NOT declare monochrome intent.
COLOR_ANCHOR = ("modern anime coloring, natural skin shading, soft shadows, "
                "shallow depth of field, consistent clothing")


def pick_aspect(rect_w: int, rect_h: int) -> tuple[int, int]:
    """Pick SDXL render size matching panel aspect.

    Args:
      rect_w, rect_h: panel rect dimensions in page coords
    Returns:
      (sdxl_w, sdxl_h) — one of the 3 SDXL native sizes
    """
    ar = rect_w / rect_h
    if ar > 1.3:
        return ASPECTS["landscape"]
    if ar < 0.77:
        return ASPECTS["portrait"]
    return ASPECTS["square"]


def _overlay_font(size: int):
    """Hiragino (has digits, colon, ★, kana) with default fallback."""
    from PIL import ImageFont
    for path in ("/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc",
                 "/System/Library/Fonts/Hiragino Sans GB.ttc"):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


def draw_screen_overlay(canvas, px_rect, spec):
    """Composite legible UI onto a screen-close-up panel.

    SDXL cannot render coherent UI text/numbers, so the storyboard supplies a
    vector spec [kind, *args] and we draw it cleanly on top of the generated
    glowing-screen art (v14 README guidance). Kinds:
      ["countdown", "00:14:59", label?]   — deadline timer + progress bar
      ["reviews", rows?, stars?]          — star-rating list rows
      ["confirm", label?]                 — green check confirmation
    """
    from PIL import ImageDraw
    if not spec:
        return canvas
    kind = str(spec[0])
    x, y, w, h = px_rect
    cx, cy = x + w // 2, y + h // 2
    d = ImageDraw.Draw(canvas)

    def centered(text, font, ty, fill):
        bb = d.textbbox((0, 0), text, font=font)
        d.text((cx - (bb[2] - bb[0]) // 2, ty), text, font=font, fill=fill)

    if kind == "countdown":
        text = str(spec[1]) if len(spec) > 1 else "00:14:59"
        label = str(spec[2]) if len(spec) > 2 else ""
        pad = int(min(w, h) * 0.12)
        box = [x + pad, y + pad, x + w - pad, y + h - pad]
        d.rectangle(box, fill=(10, 12, 18))
        if label:
            lf = _overlay_font(max(12, int(h * 0.075)))
            centered(label, lf, box[1] + int(h * 0.05), (255, 205, 205))
        df = _overlay_font(max(20, int(h * 0.24)))
        bb = d.textbbox((0, 0), text, font=df)
        centered(text, df, cy - (bb[3] - bb[1]) // 2 - int(h * 0.02), (255, 64, 64))
        bx0, bx1 = box[0] + pad, box[2] - pad
        by = box[3] - int(h * 0.13)
        bh = max(4, int(h * 0.04))
        d.rectangle([bx0, by, bx1, by + bh], fill=(70, 32, 32))
        d.rectangle([bx0, by, bx0 + int((bx1 - bx0) * 0.18), by + bh], fill=(255, 64, 64))
    elif kind == "reviews":
        rows = int(spec[1]) if len(spec) > 1 else 4
        stars = int(spec[2]) if len(spec) > 2 else 5
        pad = int(min(w, h) * 0.1)
        box = [x + pad, y + pad, x + w - pad, y + h - pad]
        d.rectangle(box, fill=(248, 248, 250))
        rh = (box[3] - box[1]) // (rows + 1)
        sf = _overlay_font(max(12, int(rh * 0.5)))
        for i in range(rows):
            ry = box[1] + rh * i + rh // 2
            sx = box[0] + int(w * 0.07)
            d.text((sx, ry), "★" * stars, font=sf, fill=(240, 168, 30))
            ly = ry + int(rh * 0.58)
            d.rectangle([sx, ly, sx + int((box[2] - box[0]) * 0.66), ly + max(3, rh // 10)],
                        fill=(202, 202, 208))
    elif kind == "confirm":
        label = str(spec[1]) if len(spec) > 1 else ""
        pad = int(min(w, h) * 0.1)
        box = [x + pad, y + pad, x + w - pad, y + h - pad]
        d.rectangle(box, fill=(18, 26, 22))
        r = int(min(w, h) * 0.18)
        oy = cy - int(h * 0.04)
        lw = max(4, r // 7)
        d.ellipse([cx - r, oy - r, cx + r, oy + r], outline=(82, 230, 140), width=lw)
        d.line([(cx - r * 0.42, oy), (cx - r * 0.05, oy + r * 0.4),
                (cx + r * 0.5, oy - r * 0.45)], fill=(82, 230, 140), width=lw + 1)
        if label:
            lf = _overlay_font(max(14, int(h * 0.1)))
            centered(label, lf, oy + r + int(h * 0.03), (220, 255, 235))
    return canvas


def paste_panel_with_effects(canvas, panel_img, panel_spec: dict,
                              px_rect, page_w: int, page_h: int):
    """Paste panel with polygon clip + tilt rotation + bleed border control.

    Args:
      canvas: PIL Image (page canvas)
      panel_img: PIL Image (rendered SDXL panel)
      panel_spec: storyboard panel dict (polygon, tilt, bleed, z optional)
      px_rect: [x, y, w, h] in page coords
      page_w, page_h: page dimensions
    """
    from PIL import Image, ImageDraw

    x, y, w, h = px_rect
    polygon = panel_spec.get("polygon")
    tilt = float(panel_spec.get("tilt", 0))
    bleed = set(panel_spec.get("bleed", []))

    # COVER mode (no aspect distortion):
    # Scale SDXL output so the smaller dim matches the rect, preserving aspect,
    # then crop to fit. Crop window position is configurable via EDN field
    # :panel/crop-offset [x_norm, y_norm] where 0.5 0.5 = center (default),
    # 0.5 0.0 = top-aligned, 0.5 1.0 = bottom-aligned, 0.0 0.5 = left, 1.0 0.5 = right.
    src_w, src_h = panel_img.size
    scale = max(w / src_w, h / src_h)
    new_w, new_h = int(src_w * scale + 0.5), int(src_h * scale + 0.5)
    scaled = panel_img.resize((new_w, new_h), Image.LANCZOS).convert("RGBA")
    crop_off = panel_spec.get("crop-offset") or panel_spec.get("crop_offset") or [0.5, 0.5]
    cox = float(crop_off[0]) if len(crop_off) >= 2 else 0.5
    coy = float(crop_off[1]) if len(crop_off) >= 2 else 0.5
    cx0 = max(0, min(new_w - w, int((new_w - w) * cox)))
    cy0 = max(0, min(new_h - h, int((new_h - h) * coy)))
    img = scaled.crop((cx0, cy0, cx0 + w, cy0 + h))

    # Polygon clip — normalized [0-1] page coords → local panel coords
    if polygon and len(polygon) >= 3:
        mask = Image.new("L", (w, h), 0)
        local_poly = []
        for pt in polygon:
            px = pt[0] if isinstance(pt, (list, tuple)) else pt
            py = pt[1] if isinstance(pt, (list, tuple)) else pt
            lx = int(px * page_w) - x
            ly = int(py * page_h) - y
            local_poly.append((lx, ly))
        ImageDraw.Draw(mask).polygon(local_poly, fill=255)
        img.putalpha(mask)

    # Tilt rotation (expand to fit rotated content, transparent fill)
    if abs(tilt) > 0.01:
        img = img.rotate(tilt, expand=True, resample=Image.BICUBIC,
                          fillcolor=(0, 0, 0, 0))
        # Center-paste rotated image at original rect center
        cx, cy = x + w // 2, y + h // 2
        paste_x, paste_y = cx - img.width // 2, cy - img.height // 2
    else:
        paste_x, paste_y = x, y

    canvas.paste(img, (paste_x, paste_y), img)

    # Draw panel border (skip edges marked as bleed)
    draw = ImageDraw.Draw(canvas)
    border_w = 4
    if polygon and len(polygon) >= 3 and abs(tilt) < 0.01:
        # Polygon border at page coords (untilted polygons only)
        page_poly = []
        for pt in polygon:
            page_poly.append((int(pt[0] * page_w), int(pt[1] * page_h)))
        draw.polygon(page_poly, outline="black", width=border_w)
    elif abs(tilt) > 0.01:
        # Tilted rectangle — draw 4 lines individually with rotation
        cx, cy = x + w // 2, y + h // 2
        import math
        rad = math.radians(tilt)
        corners = [
            (-w / 2, -h / 2), (w / 2, -h / 2),
            (w / 2, h / 2),   (-w / 2, h / 2),
        ]
        rotated = [(cx + cx_off * math.cos(rad) - cy_off * math.sin(rad),
                     cy + cx_off * math.sin(rad) + cy_off * math.cos(rad))
                    for cx_off, cy_off in corners]
        for i in range(4):
            draw.line([rotated[i], rotated[(i + 1) % 4]], fill="black", width=border_w)
    else:
        # Plain rect, skip bleed edges
        if "top" not in bleed:
            draw.line([(x, y), (x + w, y)], fill="black", width=border_w)
        if "right" not in bleed:
            draw.line([(x + w, y), (x + w, y + h)], fill="black", width=border_w)
        if "bottom" not in bleed:
            draw.line([(x + w, y + h), (x, y + h)], fill="black", width=border_w)
        if "left" not in bleed:
            draw.line([(x, y + h), (x, y)], fill="black", width=border_w)


def flip_panel_rtl(p: dict) -> dict:
    """Japanese manga R→L flip: mirror panel rect/polygon/bleed horizontally.

    EDN/storyboard data is authored in story-order with natural positions;
    this transform repositions for R→L (Japanese) reading flow.
    """
    out = dict(p)
    # Flip rect x
    rect = p.get("rect")
    if rect and len(rect) >= 4:
        x, y, w, h = rect[0], rect[1], rect[2], rect[3]
        if 0 <= x <= 1 and 0 <= w <= 1:
            out["rect"] = [round(1 - x - w, 4), y, w, h]
        # else: pixel coords — assume page width 1456, flip not applied
    # Flip polygon vertices x
    poly = p.get("polygon")
    if poly:
        out["polygon"] = [[round(1 - pt[0], 4), pt[1]] for pt in poly]
    # Flip bleed sides
    bleed = p.get("bleed")
    if bleed:
        m = {"left": "right", "right": "left", "top": "top", "bottom": "bottom"}
        out["bleed"] = [m.get(b, b) for b in bleed]
    # Flip tilt sign so the visual feel is mirrored too
    tilt = p.get("tilt")
    if tilt is not None:
        out["tilt"] = -float(tilt)
    return out


def render_storyboard(storyboard_path: str, out_dir: str = "/tmp",
                       reading_direction: str = "rtl",
                       reletter: bool = False, src_dir: str | None = None) -> dict:
    """Render a storyboard to a final A4 page PNG.

    Args:
      reading_direction: 'rtl' (Japanese manga default) flips panel positions
                          right-to-left; 'ltr' leaves story-order positions as-is.
      reletter: skip Stage-1 panel generation (no ComfyUI/Modal) and reuse the
                previously saved source panels from disk, re-running only the
                composite + bubble/SFX layers. Use this to re-place bubbles
                without regenerating images.
      src_dir:  directory holding `v14-pNN-src-panel-N.png` source panels for
                reletter mode (defaults to out_dir).
    Returns dict with per-stage paths + timings.
    """
    from lg_mangaka.v14_format_loaders import load_any
    # If storyboard is .edn AND a sibling characters.edn exists, merge characters first
    if storyboard_path.endswith(".edn"):
        from lg_mangaka.storyboard_db import StoryboardDB
        from pathlib import Path as _P
        chars_path = str(_P(storyboard_path).parent / "characters.edn")
        if os.path.exists(chars_path):
            chars = StoryboardDB.load_edn(chars_path)
            db = StoryboardDB.load_edn(storyboard_path)
            db.merge_db(chars)
            # Find first page entity and export
            page_entity = next((eid for eid, ent in db.entities.items()
                                  if ":page/number" in ent), None)
            if not page_entity:
                raise ValueError(f"no page entity in {storyboard_path}")
            sb = db.export_lexicon(page_entity)
            print(f"[v14] loaded {storyboard_path} with characters.edn merge")
        else:
            sb = load_any(storyboard_path)
    else:
        sb = load_any(storyboard_path)
    page_num = sb["pageNumber"]
    if reading_direction == "rtl":
        sb["panels"] = [flip_panel_rtl(p) for p in sb["panels"]]
        print(f"[v14] R→L flip applied to {len(sb['panels'])} panels (Japanese manga reading)")
    print(f"[v14] storyboard page {page_num}, {len(sb['panels'])} panels")

    # Lazy imports
    sys.path.insert(0, str(Path(__file__).parent.parent))
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from lg_mangaka import comfy_workflows as _cw
    import bubble_v2 as _bv2
    from lg_mangaka import bubble_autoplace as _ap

    from PIL import Image, ImageDraw, ImageFont, ImageFilter

    # Reletter mode reuses saved panels — no ComfyUI/Modal needed.
    _src_dir = src_dir or out_dir
    run_wf = None
    if not reletter:
        import modal
        run_wf = modal.Function.from_name("mangaka-comfyui", "run_workflow")

    base_tags = sb["baseTags"]
    neg_tags = sb.get("negativeTags", [])

    # Monochrome intent is opt-in via base-tags. When absent → render in color
    # (Animagine XL 4.0 stable config: euler_a/normal, cfg 7, 20 steps, base seed 251123).
    _mono = any(("monochrome" in t.lower() or "greyscale" in t.lower()
                 or "grayscale" in t.lower()) for t in base_tags)
    _style_anchor = MONO_ANCHOR if _mono else COLOR_ANCHOR
    # 28 steps: 20 under-denoises dense scene panels (golden-hour/street/multi-subject)
    # into euler_a noise; single-subject panels are fine at 20 but pages mix both.
    _steps    = int(sb.get("steps",  28))
    _cfg      = float(sb.get("cfg",   5.0 if _mono else 7.0))
    _sampler  = sb.get("sampler",   "dpmpp_2m_sde" if _mono else "euler_ancestral")
    _scheduler = sb.get("scheduler", "karras" if _mono else "normal")
    _base_seed = int(sb.get("seed",  42 if _mono else 251123))

    # Stage 1: Render each panel at native SDXL aspect
    panel_imgs = []
    timings = {"per_panel": []}
    t_stage1 = time.time()
    for p in sb["panels"]:
        rect = p["rect"]
        # rect is [x_norm, y_norm, w_norm, h_norm] OR pixel coords — try both
        if all(0 <= v <= 1 for v in rect):
            px_rect = [int(rect[0] * PAGE_W), int(rect[1] * PAGE_H),
                        int(rect[2] * PAGE_W), int(rect[3] * PAGE_H)]
        else:
            px_rect = [int(v) for v in rect]
        sdxl_w, sdxl_h = pick_aspect(px_rect[2], px_rect[3])
        prompt = ", ".join([_style_anchor] + base_tags + p["tags"])
        # Monochrome runs suppress color; color runs use Animagine score-negatives.
        _mono_neg = "(color:1.5), colorful, vibrant, saturated, watercolor, sepia, " if _mono else ""
        _score_neg = "" if _mono else "low score, bad score, average score, "
        negative = (
            "lowres, bad anatomy, bad hands, text, error, missing fingers, "
            "extra digit, fewer digits, cropped, worst quality, low quality, "
            "normal quality, jpeg artifacts, signature, watermark, username, "
            "blurry, artist name, " + _mono_neg + _score_neg + "photograph, 3d, "
            + ", ".join(neg_tags)
        )
        seed = _base_seed + p["index"] * 17
        src_path = f"{out_dir}/v14-p{page_num:02d}-src-panel-{p['index']}.png"
        if reletter:
            # Reuse the previously generated panel from disk — no image gen.
            # `src-ref` provenance ("pNN-K") lets a panel keep pulling its
            # ORIGINAL source image after it has been re-paginated onto a
            # different page (compose-only repacing — no ComfyUI re-render).
            src_ref = p.get("src-ref") or p.get("src_ref")
            if src_ref:
                m = re.match(r"p?(\d+)\D+(\d+)", str(src_ref))
                if not m:
                    raise ValueError(f"reletter: bad src-ref '{src_ref}'")
                _op, _oi = int(m.group(1)), int(m.group(2))
                disk_path = f"{_src_dir}/v14-p{_op:02d}-src-panel-{_oi}.png"
            else:
                disk_path = f"{_src_dir}/v14-p{page_num:02d}-src-panel-{p['index']}.png"
            if not os.path.exists(disk_path):
                raise FileNotFoundError(
                    f"reletter: source panel missing: {disk_path}")
            t0 = time.time()
            img = Image.open(disk_path)
            dt = time.time() - t0
            print(f"  [reletter] panel {p['index']} {p['shot']:18s} <- {disk_path}")
        else:
            wf = _cw.panel_clean_workflow(
                panel_rkey=f"v14-p{page_num:02d}-n{p['index']}",
                positive=prompt, negative=negative,
                seed=seed, width=sdxl_w, height=sdxl_h,
                steps=_steps, cfg=_cfg, ckpt="animagine-xl-4.0.safetensors",
                sampler=_sampler, scheduler=_scheduler,
            )
            t0 = time.time()
            png_bytes = run_wf.remote(wf)
            dt = time.time() - t0
            print(f"  [render] panel {p['index']} {p['shot']:18s} @ {sdxl_w}x{sdxl_h}  {dt:5.1f}s")
            img = Image.open(io.BytesIO(png_bytes))
            # Save raw 1024-equiv source so the human-eval editor can re-crop
            # without re-generating. Path: /tmp/v14-pNN-src-panel-N.png
            img.save(src_path)
        timings["per_panel"].append({"idx": p["index"], "shot": p["shot"],
                                       "aspect": f"{sdxl_w}x{sdxl_h}",
                                       "rect": p.get("rect"),
                                       "crop_offset": p.get("crop-offset") or p.get("crop_offset") or [0.5, 0.5],
                                       "seconds": round(dt, 1)})
        so = p.get("screenOverlay") or p.get("screen_overlay")
        if so:
            img = draw_screen_overlay(img.convert("RGB"), [0, 0, img.width, img.height], so)
            print(f"  [screen] overlay {so[0]} on panel {p['index']}")
        panel_imgs.append((p, px_rect, img, (sdxl_w, sdxl_h)))
    timings["stage1_total"] = round(time.time() - t_stage1, 1)

    # Stage 2: Page composite at A4 resolution (z-order: low z first)
    canvas = Image.new("RGB", (PAGE_W, PAGE_H), "white")
    panel_imgs_z = sorted(panel_imgs, key=lambda t: t[0].get("z", 1))
    for p, px_rect, panel_img, (sw, sh) in panel_imgs_z:
        paste_panel_with_effects(canvas, panel_img, p, px_rect, PAGE_W, PAGE_H)

    stage1_path = f"{out_dir}/v14-p{page_num:02d}-stage1-panels.png"
    canvas.save(stage1_path)
    print(f"  [stage1] saved {stage1_path}")

    # Stage 3: Bubble v2 layer
    try:
        font_path = "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc"
        if not Path(font_path).exists():
            font_path = "/System/Library/Fonts/Hiragino Sans GB.ttc"
        bubble_font = ImageFont.truetype(font_path, 36)
    except Exception as e:
        print(f"  [warn] font load: {e}, using default")
        bubble_font = ImageFont.load_default()

    draw = ImageDraw.Draw(canvas)
    # Auto-placement: detect the busiest (face/line-art) regions per panel from
    # the rendered pixels and steer bubbles into the emptiest readable space so
    # they stop covering faces. Set V14_AUTO_PLACE_BUBBLES=0 to disable (fall
    # back to static EDN anchors). Explicit `pos` in the EDN always wins.
    auto_place = os.environ.get("V14_AUTO_PLACE_BUBBLES", "1") != "0"
    for p, px_rect, _, _ in panel_imgs:
        x, y, w, h = px_rect
        bubbles = p.get("bubbles", [])
        reading = reading_direction or "rtl"
        ap_sat = ap_gx = ap_gy = None
        ap_face = None
        placed_rects = []  # normalized (cx,cy,w,h) bubbles already placed in panel
        if auto_place and bubbles:
            try:
                panel_crop = canvas.crop((x, y, x + w, y + h))
                ap_sat, ap_gx, ap_gy = _ap.build_detail_sat(panel_crop)
                ap_face = _ap.face_hint(ap_sat, ap_gx, ap_gy)
            except Exception as e:
                print(f"  [autoplace] panel {p['index']} grid skipped: {e}")
                ap_sat = None
        for i, b in enumerate(bubbles):
            text = b.get("text", "")
            if not text: continue
            # Rich EDN-driven bubble params (all optional)
            anchor = b.get("anchor", "top-right")
            shape = b.get("shape")  # explicit shape override
            tail_target = b.get("tail-target") or b.get("tail_target")
            if tail_target and isinstance(tail_target, (list, tuple)) and len(tail_target) >= 2:
                tail_target = (float(tail_target[0]), float(tail_target[1]))
            else:
                tail_target = None
            pos = b.get("pos")
            if pos and isinstance(pos, (list, tuple)) and len(pos) >= 2:
                pos = (float(pos[0]), float(pos[1]))
            else:
                pos = None
            size = b.get("size")
            if size and isinstance(size, (list, tuple)) and len(size) >= 2:
                size = (float(size[0]), float(size[1]))
            else:
                size = None
            # Per-bubble font size: reload if specified
            bf_size = b.get("font-size") or b.get("font_size")
            this_font = bubble_font
            if bf_size:
                try:
                    this_font = ImageFont.truetype(font_path, int(bf_size))
                except Exception:
                    pass
            mcpc = b.get("max-chars-per-col") or b.get("max_chars_per_col")
            wmode = b.get("writing-mode") or b.get("writing_mode")
            # Anchor-respecting auto-placement when EDN gives no explicit pos:
            # keep the authored anchor unless it covers a face / another bubble,
            # then relocate to the nearest emptier readable spot.
            if pos is None and ap_sat is not None:
                try:
                    sz_n = size if size is not None else _ap.estimate_bubble_size_norm(
                        text, w, h, max_chars_per_col=mcpc,
                        font_size=int(bf_size) if bf_size else None,
                        writing_mode=wmode)
                    new_pos, rect = _ap.refine_anchor(
                        ap_sat, ap_gx, ap_gy, sz_n, anchor, placed_rects,
                        order_index=i, n_bubbles=len(bubbles), reading=reading)
                    placed_rects.append(rect)
                    if new_pos is not None:
                        pos = new_pos
                        print(f"  [autoplace] panel {p['index']} bubble {i} "
                              f"moved off art -> ({pos[0]:.2f},{pos[1]:.2f})")
                except Exception as e:
                    print(f"  [autoplace] panel {p['index']} bubble {i}: {e}")
            elif pos is not None:
                # Reserve the explicit slot so auto-placed siblings avoid it.
                sz_n = size if size is not None else _ap.estimate_bubble_size_norm(
                    text, w, h, max_chars_per_col=mcpc,
                    font_size=int(bf_size) if bf_size else None, writing_mode=wmode)
                placed_rects.append((pos[0], pos[1], sz_n[0], sz_n[1]))
            try:
                _bv2.draw_bubble_v2(
                    draw, this_font, text,
                    x, y, w, h,
                    anchor=anchor,
                    shape=shape,
                    tail_target=tail_target,
                    font_size=bf_size,
                    max_chars_per_col=mcpc,
                    pos=pos, size=size,
                    outline_width=int(b.get("border-width") or b.get("outline_width") or 3),
                    padding=int(b.get("padding") or 22),
                    writing_mode=wmode,
                )
            except Exception as e:
                print(f"  [bubble] panel {p['index']} bubble {i} skipped: {e}")
    stage3_path = f"{out_dir}/v14-p{page_num:02d}-stage3-bubbles.png"
    canvas.save(stage3_path)
    print(f"  [stage3] saved {stage3_path}")

    # Stage 4: SFX overlay
    for p, px_rect, _, _ in panel_imgs:
        x, y, w, h = px_rect
        for s in p.get("sfx", []):
            text = s.get("text", "")
            if not text: continue
            try:
                sfx_font_path = "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc"
                if not Path(sfx_font_path).exists():
                    sfx_font_path = "/System/Library/Fonts/Hiragino Sans GB.ttc"
                sfx_size = int(60 * float(s.get("scale", 1.2)))
                sfx_font = ImageFont.truetype(sfx_font_path, sfx_size)
            except Exception:
                sfx_font = bubble_font
            # Render SFX text at rotated position
            pos = s.get("pos", [w // 4, h // 4])
            # Normalize pos if it's normalized
            if all(0 <= v <= 1 for v in pos):
                sx = x + int(pos[0] * w)
                sy = y + int(pos[1] * h)
            else:
                sx = x + int(pos[0])
                sy = y + int(pos[1])
            rot = float(s.get("rot", -10))
            txt_img = Image.new("RGBA", (600, 200), (255, 255, 255, 0))
            tdraw = ImageDraw.Draw(txt_img)
            tdraw.text((20, 20), text, fill="black",
                        stroke_fill="white", stroke_width=6, font=sfx_font)
            txt_img = txt_img.rotate(rot, expand=True, resample=Image.BICUBIC)
            canvas.paste(txt_img, (sx - 100, sy - 60), txt_img)
    # v15: thoughts (italic, no border, smaller stroke — distinct from SFX)
    for p, px_rect, _, _ in panel_imgs:
        x, y, w, h = px_rect
        for t in p.get("thoughts", []):
            text = t.get("text", "")
            if not text: continue
            try:
                th_font_path = "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"
                if not Path(th_font_path).exists():
                    th_font_path = "/System/Library/Fonts/Hiragino Sans GB.ttc"
                th_size = int(36 * float(t.get("scale", 1.0)))
                th_font = ImageFont.truetype(th_font_path, th_size)
            except Exception:
                th_font = bubble_font
            pos = t.get("pos", [w // 2, h // 2])
            if all(0 <= v <= 1 for v in pos):
                sx = x + int(pos[0] * w); sy = y + int(pos[1] * h)
            else:
                sx = x + int(pos[0]); sy = y + int(pos[1])
            rot = float(t.get("rot", 0))
            txt_img = Image.new("RGBA", (500, 150), (255, 255, 255, 0))
            tdraw = ImageDraw.Draw(txt_img)
            # Thought style: light grey with white halo (no bold stroke)
            tdraw.text((20, 20), text, fill=(60, 60, 60, 230),
                        stroke_fill=(255, 255, 255, 200), stroke_width=2, font=th_font)
            if abs(rot) > 0.5:
                txt_img = txt_img.rotate(rot, expand=True, resample=Image.BICUBIC)
            canvas.paste(txt_img, (sx - 80, sy - 40), txt_img)
    # v15: telops — small character-intro caption boxes anchored to panel corner
    for p, px_rect, _, _ in panel_imgs:
        x, y, w, h = px_rect
        for tl in p.get("telops", []):
            text = tl.get("text", "")
            if not text: continue
            try:
                tl_font_path = "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"
                if not Path(tl_font_path).exists():
                    tl_font_path = "/System/Library/Fonts/Hiragino Sans GB.ttc"
                tl_font = ImageFont.truetype(tl_font_path, int(tl.get("fontSize", 18)))
            except Exception:
                tl_font = bubble_font
            anchor = tl.get("anchor", "bottom-right")
            pad = 10
            # Telop = white rect with black border + 1-2 lines of text
            lines = text.split("\n")
            max_w = 0
            for ln in lines:
                bb = ImageDraw.Draw(canvas).textbbox((0, 0), ln, font=tl_font)
                max_w = max(max_w, bb[2] - bb[0])
            bb = ImageDraw.Draw(canvas).textbbox((0, 0), "A", font=tl_font)
            line_h = (bb[3] - bb[1]) + 4
            box_w = max_w + pad * 2
            box_h = line_h * len(lines) + pad * 2
            if anchor.startswith("top"):
                ty = y + 8
            else:
                ty = y + h - box_h - 8
            if anchor.endswith("right"):
                tx = x + w - box_w - 8
            else:
                tx = x + 8
            draw_t = ImageDraw.Draw(canvas)
            draw_t.rectangle([tx, ty, tx + box_w, ty + box_h], fill="white", outline="black", width=3)
            for i, ln in enumerate(lines):
                draw_t.text((tx + pad, ty + pad + i * line_h), ln, fill="black", font=tl_font)
    stage4_path = f"{out_dir}/v14-p{page_num:02d}-stage4-sfx.png"
    canvas.save(stage4_path)
    print(f"  [stage4] saved {stage4_path}")

    # Stage 5: Final post-process
    canvas = canvas.filter(ImageFilter.SMOOTH)
    canvas = canvas.filter(ImageFilter.UnsharpMask(radius=2, percent=70, threshold=3))
    final_path = f"{out_dir}/v14-p{page_num:02d}-final.png"
    canvas.save(final_path)
    print(f"  [final ] saved {final_path}")

    # Sidecar
    sidecar = {
        "page_number": page_num,
        "storyboard": storyboard_path,
        "stages": {
            "stage1_panels": stage1_path,
            "stage3_bubbles": stage3_path,
            "stage4_sfx": stage4_path,
            "final": final_path,
        },
        "timings": timings,
        "page_size": [PAGE_W, PAGE_H],
    }
    sidecar_path = f"{out_dir}/v14-p{page_num:02d}-sidecar.json"
    with open(sidecar_path, "w") as f:
        json.dump(sidecar, f, ensure_ascii=False, indent=2)
    print(f"  [sidecar] {sidecar_path}")
    return sidecar


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(
        description="Render (or re-letter) a v14 storyboard page.")
    ap.add_argument("storyboard", help="storyboard .edn/.json path")
    ap.add_argument("--out", default="/tmp", help="output dir (default /tmp)")
    ap.add_argument("--reletter", action="store_true",
                    help="reuse saved source panels; redraw bubbles/SFX only "
                         "(no ComfyUI/Modal)")
    ap.add_argument("--src", default=None,
                    help="source-panels dir for --reletter (default: --out)")
    ap.add_argument("--reading", default="rtl", choices=["rtl", "ltr"])
    args = ap.parse_args()
    out = render_storyboard(args.storyboard, out_dir=args.out,
                            reading_direction=args.reading,
                            reletter=args.reletter, src_dir=args.src)
    print(json.dumps(out, ensure_ascii=False, indent=2))
