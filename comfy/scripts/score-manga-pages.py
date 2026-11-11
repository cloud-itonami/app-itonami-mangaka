"""Score each rendered arc 0-1 page on manga-quality dimensions.

Pure-PIL heuristics, no ML inference. Combined with my own vision
judgment on the bottom-scoring pages this drives an auto-improvement
loop:

  1. score_all() -> per-page JSON with dimension scores + total
  2. identify pages below threshold
  3. for each, propose specific fix (lower style weight / new seed /
     bump LoRA strength / different env hint) and re-render
  4. re-score; loop until convergence

Dimensions:
  bw_purity      Lower mean HSV saturation = higher score (B&W manga
                 should be near zero saturation)
  contrast       Std of grayscale luminance — high contrast B&W manga
                 has wide histogram (pure black + pure white screentone)
  edge_density   Ratio of strong-edge pixels (Pillow ImageFilter EDGE_ENHANCE
                 + threshold) — captures detail level
  detail_var     Pixel-block variance over the panel center — penalizes
                 TV-static / flat-tone-only outputs
  bubble_area    Total bubble area fraction (manga pages have 5-25%
                 bubble; too little = no dialogue, too much = wall of text)

  total          Weighted sum normalized to 0-100
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter, ImageStat


def _score_bw_purity(im: Image.Image) -> float:
    """0-100: lower HSV saturation = higher score."""
    hsv = im.convert("HSV")
    w, h = hsv.size
    c = hsv.crop((w // 6, h // 6, 5 * w // 6, 5 * h // 6))
    sat = c.split()[1]
    sat_mean = sum(i * cnt for i, cnt in enumerate(sat.histogram())) / max(
        1, sum(sat.histogram())
    )
    # sat_mean 0-50 = good (0-100 score), 50-100 = bad (100-0 score)
    return max(0.0, min(100.0, 100.0 - (sat_mean / 50.0) * 100.0))


def _score_contrast(im: Image.Image) -> float:
    """0-100: high std of luminance = high contrast = high score."""
    g = im.convert("L")
    std = ImageStat.Stat(g).stddev[0]
    # std 0-80, 0-100 score; clamp 80+ to 100
    return max(0.0, min(100.0, (std / 80.0) * 100.0))


def _score_edge_density(im: Image.Image) -> float:
    """0-100: edge pixel fraction — high detail = high score, but with
    cap so noise/static doesn't inflate."""
    g = im.convert("L")
    edges = g.filter(ImageFilter.FIND_EDGES)
    hist = edges.histogram()
    total = sum(hist)
    strong = sum(hist[60:])  # pixels with edge strength >= 60
    ratio = strong / max(1, total)
    # ratio 0.0-0.15 ideal range. Above 0.30 likely noise.
    if ratio < 0.05:
        return ratio / 0.05 * 50.0
    if ratio <= 0.15:
        return 50.0 + (ratio - 0.05) / 0.10 * 50.0
    if ratio <= 0.30:
        return 100.0 - (ratio - 0.15) / 0.15 * 30.0
    return max(0.0, 70.0 - (ratio - 0.30) * 200.0)


def _score_detail_var(im: Image.Image) -> float:
    """0-100: tile-block variance penalizes flat / pure-static outputs."""
    g = im.convert("L")
    w, h = g.size
    # 8x8 grid of tiles
    var_sum = 0.0
    n = 0
    for ty in range(8):
        for tx in range(8):
            tile = g.crop(
                (tx * w // 8, ty * h // 8, (tx + 1) * w // 8, (ty + 1) * h // 8)
            )
            std = ImageStat.Stat(tile).stddev[0]
            var_sum += std
            n += 1
    avg = var_sum / max(1, n)
    # avg 0-90, want ~40-70 (manga). Too low = flat, too high = static.
    if avg < 20:
        return avg / 20.0 * 30.0
    if avg <= 50:
        return 30.0 + (avg - 20.0) / 30.0 * 70.0
    if avg <= 75:
        return 100.0 - (avg - 50.0) / 25.0 * 20.0
    return max(0.0, 80.0 - (avg - 75.0) * 5.0)


def _score_bubble_area(im: Image.Image) -> float:
    """Estimate bubble area by looking for pure-white roundish regions."""
    g = im.convert("L")
    w, h = g.size
    # Threshold near-pure-white (220+)
    bw = g.point(lambda v: 255 if v >= 230 else 0)
    hist = bw.histogram()
    white = hist[255]
    total = sum(hist)
    ratio = white / max(1, total)
    # ratio 0.05-0.25 ideal
    if ratio < 0.02:
        return ratio / 0.02 * 40.0
    if ratio <= 0.05:
        return 40.0 + (ratio - 0.02) / 0.03 * 30.0
    if ratio <= 0.25:
        return 70.0 + (ratio - 0.05) / 0.20 * 30.0
    return max(0.0, 100.0 - (ratio - 0.25) * 200.0)


WEIGHTS = {
    "bw_purity":    0.30,
    "contrast":     0.20,
    "edge_density": 0.20,
    "detail_var":   0.20,
    "bubble_area":  0.10,
}


def score_page(path: Path) -> dict[str, Any]:
    im = Image.open(path).convert("RGB")
    scores = {
        "bw_purity":    _score_bw_purity(im),
        "contrast":     _score_contrast(im),
        "edge_density": _score_edge_density(im),
        "detail_var":   _score_detail_var(im),
        "bubble_area":  _score_bubble_area(im),
    }
    total = sum(scores[k] * WEIGHTS[k] for k in scores)
    return {"path": str(path), "scores": scores, "total": round(total, 1)}


def main() -> int:
    root = Path("/tmp")
    out: list[dict[str, Any]] = []
    for n in range(46):
        f = root / f"gh-arc0-1-p{n:02d}-final.png"
        if not f.exists():
            print(f"p{n:02d}: MISSING")
            continue
        r = score_page(f)
        r["page"] = n
        out.append(r)
        s = r["scores"]
        print(
            f"p{n:02d} total={r['total']:5.1f}  "
            f"bw={s['bw_purity']:5.1f} contrast={s['contrast']:5.1f} "
            f"edge={s['edge_density']:5.1f} detail={s['detail_var']:5.1f} "
            f"bub={s['bubble_area']:5.1f}"
        )

    # Worst 10 + best 5
    sorted_out = sorted(out, key=lambda r: r["total"])
    print("\n=== WORST 10 ===")
    for r in sorted_out[:10]:
        print(f"  p{r['page']:02d} total={r['total']:5.1f}")
    print("\n=== BEST 5 ===")
    for r in sorted_out[-5:]:
        print(f"  p{r['page']:02d} total={r['total']:5.1f}")

    # Histogram
    print("\n=== distribution ===")
    bins = [0, 40, 50, 55, 60, 65, 70, 75, 80, 85, 100]
    for i in range(len(bins) - 1):
        lo, hi = bins[i], bins[i + 1]
        cnt = sum(1 for r in out if lo <= r["total"] < hi)
        bar = "#" * cnt
        print(f"  {lo:3d}-{hi:3d}: {cnt:2d} {bar}")

    # Save report
    report_path = Path("/tmp/arc01-qa-report.json")
    report_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\nreport saved: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
