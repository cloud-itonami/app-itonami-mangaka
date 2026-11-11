"""Jump-tier manga quality scorer.

Scores each generated arc 0-1 page on 4 axes derived from named
reference manga, then computes a weighted total normalized to 0-100.

Reference axes (each scored 0-100):

  jujutsu      呪術廻戦  ink intensity + dramatic line weight + heavy black
                       fills. PIL proxy: high contrast std + strong-edge
                       fraction + pure-black pixel fraction.

  deathnote    デスノート cinematic composition + clean lines + panel rhythm.
                       PIL proxy: hough-line-style straight edge fraction +
                       low-noise (anti-static) + page composition entropy.

  shirow       攻殻機動隊 (Masamune Shirow / GitS) — dense fine detail in
                       backgrounds, mechanical / environmental precision.
                       PIL proxy: mid-frequency texture energy (FFT band)
                       in non-bubble area + edge pixel density.

  aria         Aria (天野こずえ) — atmospheric tone, gentle gradients,
                       screentone with emotional negative space.
                       PIL proxy: smooth-gradient area fraction + low-edge
                       background ratio + balanced bubble-to-art ratio.

Total = weighted blend tuned for "shonen-jump-class manga":
  jujutsu 0.30 + deathnote 0.30 + shirow 0.20 + aria 0.20

Output: per-page JSON with sub-scores + total + identified weakness axis.
The "weakness" tag drives targeted fix recipes in
qa-improve-loop-jump.py.
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter, ImageStat, ImageChops


def _gray_no_bubble(im: Image.Image) -> Image.Image:
    """Return the L (grayscale) channel with bubble-white regions masked out.
    Bubbles dominate the all-white area; for content scoring we want art only."""
    g = im.convert("L")
    # Threshold near-pure-white = bubbles. Replace with mid-grey so the
    # bubble area doesn't artificially lower scores.
    mask = g.point(lambda v: 0 if v >= 235 else 255)
    grey = Image.new("L", g.size, 128)
    return ImageChops.composite(g, grey, mask)


def _crop_center(im: Image.Image, frac: float = 0.7) -> Image.Image:
    w, h = im.size
    dx = int(w * (1 - frac) / 2)
    dy = int(h * (1 - frac) / 2)
    return im.crop((dx, dy, w - dx, h - dy))


# ── axis 1: Jujutsu — ink intensity ────────────────────────────────────────
def score_jujutsu(im: Image.Image) -> float:
    g = _gray_no_bubble(im)
    c = _crop_center(g)
    stat = ImageStat.Stat(c)
    contrast = stat.stddev[0]
    # Strong-edge ratio
    edges = c.filter(ImageFilter.FIND_EDGES)
    hist_e = edges.histogram()
    total = max(1, sum(hist_e))
    strong = sum(hist_e[80:])
    edge_ratio = strong / total
    # Black-fill fraction (Jujutsu uses heavy black fills for impact)
    hist_g = c.histogram()
    black = sum(hist_g[:30]) / max(1, sum(hist_g))
    # Compose: contrast (0-100), edge (0-0.15→0-100), black (0-0.25→0-100)
    contrast_s = min(100.0, (contrast / 80.0) * 100.0)
    edge_s = min(100.0, (edge_ratio / 0.12) * 100.0)
    black_s = min(100.0, (black / 0.20) * 100.0)
    return contrast_s * 0.4 + edge_s * 0.4 + black_s * 0.2


# ── axis 2: Death Note — cinematic composition ─────────────────────────────
def score_deathnote(im: Image.Image) -> float:
    g = _gray_no_bubble(im)
    c = _crop_center(g)
    # Long-straight-edge proxy: 1-D Sobel sum along H/V (manga's strong
    # vertical / horizontal lines from panel borders + framing)
    edge_h = c.filter(ImageFilter.Kernel((3, 3),
                                          (-1, 0, 1, -2, 0, 2, -1, 0, 1), 1, 0))
    edge_v = c.filter(ImageFilter.Kernel((3, 3),
                                          (-1, -2, -1, 0, 0, 0, 1, 2, 1), 1, 0))
    h_stat = ImageStat.Stat(edge_h)
    v_stat = ImageStat.Stat(edge_v)
    line_energy = (h_stat.stddev[0] + v_stat.stddev[0]) / 2
    line_s = min(100.0, (line_energy / 60.0) * 100.0)
    # Anti-noise: detail variance shouldn't be too uniform (TV-static has
    # high uniform variance). Use ratio of per-tile std to total std.
    w, h = c.size
    tile_stds = []
    for ty in range(6):
        for tx in range(6):
            t = c.crop((tx * w // 6, ty * h // 6,
                        (tx + 1) * w // 6, (ty + 1) * h // 6))
            tile_stds.append(ImageStat.Stat(t).stddev[0])
    tile_mean = sum(tile_stds) / len(tile_stds)
    tile_var = (sum((s - tile_mean) ** 2 for s in tile_stds)
                / len(tile_stds)) ** 0.5
    # High tile variance = compositional rhythm (some tiles flat, some dense)
    rhythm_s = min(100.0, (tile_var / 25.0) * 100.0)
    # Penalize pages with low total brightness range (washed out)
    extrema = c.getextrema()
    dyn_range = (extrema[1] - extrema[0]) / 255 * 100
    return line_s * 0.4 + rhythm_s * 0.4 + dyn_range * 0.2


# ── axis 3: Shirow — dense detail ──────────────────────────────────────────
def score_shirow(im: Image.Image) -> float:
    g = _gray_no_bubble(im)
    # Edge density across the FULL image (not just center — bg matters)
    edges = g.filter(ImageFilter.FIND_EDGES)
    hist = edges.histogram()
    total = max(1, sum(hist))
    mid_edge = sum(hist[40:120]) / total  # mid-strength edges = bg detail
    strong_edge = sum(hist[120:]) / total
    edge_score = min(100.0, ((mid_edge + strong_edge) / 0.20) * 100.0)
    # Texture variance — Shirow's screentone + crosshatch
    g_small = g.resize((g.size[0] // 4, g.size[1] // 4), Image.BICUBIC)
    g_big = g_small.resize(g.size, Image.BICUBIC)
    diff = ImageChops.difference(g, g_big)
    texture_std = ImageStat.Stat(diff).stddev[0]
    texture_s = min(100.0, (texture_std / 20.0) * 100.0)
    return edge_score * 0.6 + texture_s * 0.4


# ── axis 4: Aria — atmospheric tone ────────────────────────────────────────
def score_aria(im: Image.Image) -> float:
    g = _gray_no_bubble(im)
    # Smooth-gradient area: where Sobel is LOW (no strong edges = soft area)
    edges = g.filter(ImageFilter.FIND_EDGES)
    hist = edges.histogram()
    total = max(1, sum(hist))
    low_edge = sum(hist[:30]) / total  # nearly flat regions
    # Aria has 30-50% flat / gentle area — too much (>70%) = empty, too little
    # (<20%) = busy.
    if low_edge < 0.20:
        smooth_s = low_edge / 0.20 * 60
    elif low_edge < 0.50:
        smooth_s = 60 + (low_edge - 0.20) / 0.30 * 40
    elif low_edge < 0.70:
        smooth_s = 100 - (low_edge - 0.50) / 0.20 * 20
    else:
        smooth_s = max(0.0, 80 - (low_edge - 0.70) * 200)
    # Bubble-to-art ratio (Aria is dialogue-light but not zero)
    g_full = im.convert("L")
    hist_full = g_full.histogram()
    white_frac = hist_full[255] / max(1, sum(hist_full))
    if 0.03 <= white_frac <= 0.15:
        bubble_s = 100.0
    elif white_frac < 0.03:
        bubble_s = (white_frac / 0.03) * 100.0
    else:
        bubble_s = max(0.0, 100.0 - (white_frac - 0.15) * 300)
    # B&W purity (Aria is fully grayscale)
    hsv = im.convert("HSV")
    sat = ImageStat.Stat(hsv.split()[1]).mean[0]
    bw_s = max(0.0, 100.0 - (sat / 60.0) * 100.0)
    return smooth_s * 0.4 + bubble_s * 0.3 + bw_s * 0.3


WEIGHTS = {
    "jujutsu":   0.30,
    "deathnote": 0.30,
    "shirow":    0.20,
    "aria":      0.20,
}


def score_page(path: Path) -> dict[str, Any]:
    im = Image.open(path).convert("RGB")
    scores = {
        "jujutsu":   score_jujutsu(im),
        "deathnote": score_deathnote(im),
        "shirow":    score_shirow(im),
        "aria":      score_aria(im),
    }
    total = sum(scores[k] * WEIGHTS[k] for k in scores)
    weakest = min(scores, key=scores.get)
    return {
        "path": str(path),
        "scores": {k: round(v, 1) for k, v in scores.items()},
        "total": round(total, 1),
        "weakest_axis": weakest,
        "weakest_score": round(scores[weakest], 1),
    }


def main() -> int:
    root = Path("/tmp")
    out = []
    for n in range(46):
        f = root / f"gh-arc0-1-p{n:02d}-final.png"
        if not f.exists():
            continue
        r = score_page(f)
        r["page"] = n
        out.append(r)
        s = r["scores"]
        print(
            f"p{n:02d} total={r['total']:5.1f}  "
            f"jujutsu={s['jujutsu']:5.1f} "
            f"deathnote={s['deathnote']:5.1f} "
            f"shirow={s['shirow']:5.1f} "
            f"aria={s['aria']:5.1f} "
            f"weakest={r['weakest_axis']:>9s}({r['weakest_score']:5.1f})"
        )

    sorted_out = sorted(out, key=lambda r: r["total"])
    print("\n=== WORST 10 ===")
    for r in sorted_out[:10]:
        print(f"  p{r['page']:02d} total={r['total']:5.1f} weakest={r['weakest_axis']}({r['weakest_score']:.1f})")
    print("\n=== BEST 5 ===")
    for r in sorted_out[-5:]:
        print(f"  p{r['page']:02d} total={r['total']:5.1f}")

    # Weakness histogram
    from collections import Counter
    weak_hist = Counter(r["weakest_axis"] for r in out)
    print(f"\n=== weakest-axis distribution ===")
    for axis in ("jujutsu", "deathnote", "shirow", "aria"):
        c = weak_hist.get(axis, 0)
        print(f"  {axis:>9s}: {c:2d}")

    # Total histogram
    print("\n=== total-score distribution ===")
    bins = [0, 40, 50, 55, 60, 65, 70, 75, 80, 85, 100]
    for i in range(len(bins) - 1):
        lo, hi = bins[i], bins[i + 1]
        cnt = sum(1 for r in out if lo <= r["total"] < hi)
        bar = "#" * cnt
        print(f"  {lo:3d}-{hi:3d}: {cnt:2d} {bar}")

    Path("/tmp/arc01-qa-jump-report.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False)
    )
    print(f"\nreport saved: /tmp/arc01-qa-jump-report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
