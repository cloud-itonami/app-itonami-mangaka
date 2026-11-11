"""Generate striking YouTube thumbnails (1280x720) for SHIRO & PICO episodes.

Cyber key-art: scene bg (boosted+darkened) + on-model シロ/ピコ cutouts (glow) +
glitch SHIRO & PICO logo + white/blue mono GHOST HACKER + EP badge + big hook word.
High-contrast, faces prominent, readable small. Reuses character emotions + ep-scenes.

Usage: python3 shiropico-thumbnail.py <ep> "<HOOK>" <bg_scene_key> [shiro_emo] [pico_emo]
Out: resources/thumbnails/ep<ep>.png
"""
from __future__ import annotations
import math, os, random, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops, ImageEnhance

ROOT = Path(__file__).resolve().parents[2] / "data/ghosthacker-shiropico"
SCN = ROOT / "resources/ep-scenes"; BG = ROOT / "resources/bg2"
EMO = ROOT / "character-refs/emotions"
OUT = ROOT / "resources/thumbnails"; OUT.mkdir(parents=True, exist_ok=True)
W, H = 1280, 720
TEAL = (41, 211, 194); BLUE = (46, 134, 255); GOLD = (255, 209, 102); MAG = (236, 72, 153)
TITLE = next((p for p in ["/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf",
                          "/System/Library/Fonts/Supplemental/Impact.ttf", "/Library/Fonts/Arial Black.ttf"] if os.path.exists(p)), None)
MONO = next((p for p in ["/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/SFNSMono.ttf"] if os.path.exists(p)), TITLE)


def _f(path, sz):
    try: return ImageFont.truetype(path, sz)
    except Exception: return ImageFont.load_default()

def _cover(img, w, h):
    iw, ih = img.size; s = max(w/iw, h/ih)
    img = img.resize((int(iw*s), int(ih*s)), Image.Resampling.LANCZOS)
    x, y = (img.width-w)//2, (img.height-h)//2
    return img.crop((x, y, x+w, y+h))

def _glow(rgba, color, rad=14, grow=10):
    a = rgba.split()[3]
    g = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    sil = Image.new("RGBA", rgba.size, (*color, 255)); sil.putalpha(a)
    base = Image.new("RGBA", (rgba.width+grow*2, rgba.height+grow*2), (0, 0, 0, 0))
    for dx in range(-grow, grow+1, 4):
        for dy in range(-grow, grow+1, 4):
            base.alpha_composite(sil, (grow+dx, grow+dy))
    return base.filter(ImageFilter.GaussianBlur(rad))

def _glitch(draw_img, lines, cy, scale=1.0):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(layer)
    y = cy
    for text, sz, col in lines:
        f = _f(TITLE, int(sz*scale)); bb = d.textbbox((0, 0), text, font=f)
        x = (W-(bb[2]-bb[0]))//2
        d.text((x, y), text, font=f, fill=(*col, 255), stroke_width=4, stroke_fill=(6, 10, 16, 255))
        y += int((bb[3]-bb[1]) + 14)
    r, g, b, a = layer.split()
    out = Image.merge("RGBA", (ImageChops.offset(r, 7, 0), g, ImageChops.offset(b, -7, 0), a))
    # scanlines
    sd = ImageDraw.Draw(out)
    for yy in range(0, H, 4): sd.line([(0, yy), (W, yy)], fill=(0, 0, 0, 40))
    draw_img.alpha_composite(out)

def _ghost_hacker(fr, cx, cy, sz):
    txt = "GHOST HACKER"
    try: f = ImageFont.truetype(MONO, sz, index=1)
    except Exception: f = _f(MONO, sz)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0)); gd = ImageDraw.Draw(glow)
    gd.text((cx, cy), txt, font=f, fill=(*BLUE, 255), anchor="mm", stroke_width=12, stroke_fill=(*BLUE, 255))
    fr.alpha_composite(glow.filter(ImageFilter.GaussianBlur(9)))
    ImageDraw.Draw(fr).text((cx, cy), txt, font=f, fill=(255, 255, 255, 255), anchor="mm", stroke_width=4, stroke_fill=(*BLUE, 255))


def build(ep, hook, bg_key, shiro_emo="surprised", pico_emo="smug"):
    random.seed(int(ep))
    bgf = SCN / f"{bg_key}.png"
    if not bgf.exists(): bgf = BG / "bg-dubai-night.png"
    bg = _cover(Image.open(bgf).convert("RGB"), W, H)
    bg = ImageEnhance.Color(bg).enhance(1.4); bg = ImageEnhance.Contrast(bg).enhance(1.15)
    fr = bg.convert("RGBA")
    fr.alpha_composite(Image.new("RGBA", (W, H), (6, 12, 20, 90)))
    # diagonal speed streaks
    sl = Image.new("RGBA", (W, H), (0, 0, 0, 0)); sd = ImageDraw.Draw(sl)
    for _ in range(22):
        x = random.randint(-100, W); col = random.choice([TEAL, MAG, BLUE])
        sd.line([(x, 0), (x-220, H)], fill=(*col, random.randint(30, 90)), width=random.randint(2, 6))
    fr.alpha_composite(sl.filter(ImageFilter.GaussianBlur(1)))
    # characters (big, facing center, glow)
    def place(side, emo, color):
        p = EMO / side / f"{emo}.png"
        im = Image.open(p if p.exists() else EMO / side / "normal.png").convert("RGBA")
        th = int(H*0.92); s = th/im.height; im = im.resize((int(im.width*s), th), Image.Resampling.LANCZOS)
        if side == "shiro": im = im.transpose(Image.Transpose.FLIP_LEFT_RIGHT); x = -int(im.width*0.12)
        else: x = W-im.width+int(im.width*0.12)
        y = H-im.height+30
        fr.alpha_composite(_glow(im, color), (x-10, y-10))
        fr.alpha_composite(im, (x, y))
    place("shiro", shiro_emo, TEAL); place("pico", pico_emo, (168, 224, 95))
    # HUD frame
    d = ImageDraw.Draw(fr)
    d.rectangle([18, 18, W-18, H-18], outline=(*TEAL, 180), width=4)
    # EP badge
    bf = _f(TITLE, 64); d.text((40, 28), f"EP.{int(ep)}", font=bf, fill=(*GOLD, 255), stroke_width=4, stroke_fill=(6, 10, 16, 255))
    # logo + ghost hacker + hook
    _glitch(fr, [("SHIRO & PICO", 118, TEAL)], 60, 1.0)
    _ghost_hacker(fr, W//2, 196, 40)
    # big hook word (bottom)
    hf = _f(TITLE, 120)
    bb = d.textbbox((0, 0), hook, font=hf)
    while bb[2]-bb[0] > W-120 and hf.size > 50:
        hf = _f(TITLE, hf.size-6); bb = d.textbbox((0, 0), hook, font=hf)
    hx = (W-(bb[2]-bb[0]))//2
    d.text((hx, H-150), hook, font=hf, fill=(255, 255, 255, 255), stroke_width=8, stroke_fill=(*MAG, 255))
    # vignette
    vg = Image.new("L", (W, H), 0); vd = ImageDraw.Draw(vg)
    vd.ellipse([-W//3, -H//3, W+W//3, H+H//3], fill=255); vg = vg.filter(ImageFilter.GaussianBlur(160))
    dark = Image.new("RGBA", (W, H), (0, 0, 0, 130)); dark.putalpha(ImageChops.invert(vg))
    fr.alpha_composite(dark)
    out = OUT / f"ep{int(ep):02d}.png"
    fr.convert("RGB").save(out, quality=92)
    print(f"DONE → {out}")
    return out


if __name__ == "__main__":
    ep = sys.argv[1] if len(sys.argv) > 1 else "1"
    hook = sys.argv[2] if len(sys.argv) > 2 else "CITY ASLEEP"
    bg = sys.argv[3] if len(sys.argv) > 3 else "dubai-aerial-night"
    se = sys.argv[4] if len(sys.argv) > 4 else "surprised"
    pe = sys.argv[5] if len(sys.argv) > 5 else "smug"
    build(ep, hook, bg, se, pe)
