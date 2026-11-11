"""Color SFX overlay — gradient-filled kana with motion-line styling.

Reference: JoJo Part 5 / Initial D action manga where SFX is a graphic
element with gradient color fill (purple "ブシャアアア"), tilted angle,
and dramatic stroke variation, breaking into panel borders.

Compared to monochrome sfx_overlay.py (black fill + white outline), this
module produces RGBA SFX with:
  - 3-color gradient fill (per-tone palette)
  - Heavy stroke weight that varies slightly per character
  - Slight per-kana rotation + scale
  - Optional drop-shadow / chromatic edge

Usage:
  overlay_color_sfx(im, "ブシャアアア", panel_x, panel_y, panel_w, panel_h,
                     palette="action_purple", size_pct=0.45)
"""
from __future__ import annotations
import math, random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HIRAGINO_BLACK = "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc"

# Tone → color palette for SFX (3-stop gradient)
SFX_PALETTES = {
    "action_purple":   [(120, 50, 180), (180, 80, 220), (140, 60, 200)],
    "action_red":      [(180, 30, 30), (220, 60, 60), (160, 40, 40)],
    "impact_orange":   [(220, 140, 40), (255, 180, 60), (240, 160, 50)],
    "ominous_dark":    [(50, 30, 80), (80, 50, 110), (60, 40, 90)],
    "comedic_yellow":  [(240, 220, 60), (255, 240, 100), (250, 230, 80)],
    "default_black":   [(20, 20, 20), (50, 50, 50), (30, 30, 30)],
}


def _tone_to_palette(tone: str) -> str:
    t = (tone or "").lower()
    if any(x in t for x in ("shock", "intense", "tense", "dramatic", "action")):
        return "action_purple"
    if any(x in t for x in ("anger", "rage", "battle")):
        return "action_red"
    if any(x in t for x in ("impact", "shout", "yell")):
        return "impact_orange"
    if any(x in t for x in ("ominous", "dark", "fear")):
        return "ominous_dark"
    if any(x in t for x in ("comic", "comedic", "funny", "triumph")):
        return "comedic_yellow"
    return "default_black"


def _draw_gradient_kana(layer: Image.Image, text: str, font: ImageFont.ImageFont,
                         x: int, y: int, palette: list) -> None:
    """Draw kana with vertical gradient fill — top→middle→bottom 3 colors."""
    draw = ImageDraw.Draw(layer)
    bbox = draw.textbbox((x, y), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    if tw <= 0 or th <= 0: return

    # 1) Render text mask in solid white onto a fresh layer
    mask_layer = Image.new("L", layer.size, 0)
    mask_draw = ImageDraw.Draw(mask_layer)
    mask_draw.text((x, y), text, font=font, fill=255)

    # 2) Build gradient strip the size of bbox (vertical RGB gradient)
    grad = Image.new("RGB", (tw, th), palette[1])
    grad_arr = grad.load()
    for py in range(th):
        if py < th * 0.33:
            t = py / max(1, th * 0.33)
            c = tuple(int(palette[0][i] * (1 - t) + palette[1][i] * t) for i in range(3))
        elif py < th * 0.67:
            t = (py - th * 0.33) / max(1, th * 0.34)
            c = tuple(int(palette[1][i] * (1 - t) + palette[2][i] * t) for i in range(3))
        else:
            c = palette[2]
        for px in range(tw):
            grad_arr[px, py] = c

    # 3) Paste gradient where mask is white
    color_layer = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    color_layer.paste(grad, (bbox[0], bbox[1]), mask_layer.crop(bbox))

    # 4) Draw white outline around text on layer first (so gradient sits inside)
    outline_w = max(3, int(font.size * 0.05))
    for ox in range(-outline_w, outline_w + 1, 2):
        for oy in range(-outline_w, outline_w + 1, 2):
            draw.text((x + ox, y + oy), text, fill=(255, 255, 255, 255), font=font)

    # 5) Composite gradient on top of outline
    layer.alpha_composite(color_layer)


def overlay_color_sfx(im: Image.Image, sfx_text: str,
                       panel_x: int, panel_y: int, panel_w: int, panel_h: int,
                       palette: str = "action_purple",
                       size_pct: float = 0.45) -> Image.Image:
    """Overlay color gradient SFX kana on a panel."""
    target_h = int(panel_h * size_pct)
    try:
        font = ImageFont.truetype(HIRAGINO_BLACK, target_h)
    except Exception:
        font = ImageFont.load_default()

    pal_colors = SFX_PALETTES.get(palette, SFX_PALETTES["action_purple"])

    # Position: avoid top-left (bubbles tend to go there). Tilt slightly.
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    bbox = draw.textbbox((0, 0), sfx_text, font=font)
    text_w = bbox[2] - bbox[0]; text_h = bbox[3] - bbox[1]

    if hash(sfx_text) % 2 == 0:
        tx = panel_x + panel_w // 5
    else:
        tx = panel_x + panel_w * 2 // 5
    ty = panel_y + panel_h // 3 - text_h // 2

    _draw_gradient_kana(layer, sfx_text, font, tx, ty, pal_colors)

    # Slight rotation for dynamic JoJo-style feel
    angle = ((hash(sfx_text) % 24) - 12) * 1.2   # -14 to +14 degrees
    layer = layer.rotate(angle, resample=Image.BICUBIC, expand=False)

    # If im is RGB, convert to RGBA for composite
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    im.alpha_composite(layer)
    return im


def overlay_color_sfx_on_composite(composite_path: Path, layout: list,
                                     panels: list, out_path: Path = None,
                                     size_pct: float = 0.45) -> tuple[Path, list]:
    """Apply color gradient SFX to a composited manga page."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "sfx_picker",
        str(Path(__file__).parent / "sfx_overlay.py"))
    if spec and spec.loader:
        sfx_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sfx_mod)
        pick_sfx_for_panel = sfx_mod.pick_sfx_for_panel
    else:
        return composite_path, []

    im = Image.open(composite_path).convert("RGBA")
    panels_by_idx = {p["panelIndex"]: p for p in panels}
    added = []
    for slot in layout:
        idx = slot["idx"]
        if idx not in panels_by_idx: continue
        panel = panels_by_idx[idx]
        sfx = pick_sfx_for_panel(panel)
        if not sfx: continue
        palette = _tone_to_palette(panel.get("tone", ""))
        overlay_color_sfx(im, sfx, slot["x"], slot["y"], slot["w"], slot["h"],
                           palette=palette, size_pct=size_pct)
        added.append((idx, sfx, palette))
    if out_path is None:
        out_path = composite_path
    im.convert("RGB").save(out_path)
    return out_path, added


if __name__ == "__main__":
    # Quick test
    im = Image.new("RGB", (800, 600), (200, 200, 200))
    overlay_color_sfx(im, "ブシャアアア", 0, 0, 800, 600,
                       palette="action_purple", size_pct=0.45)
    out = Path("/tmp/v8-color-sfx-test.png")
    im.convert("RGB").save(out)
    print(f"saved: {out}")
