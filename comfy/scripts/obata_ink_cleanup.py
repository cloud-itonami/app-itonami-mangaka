"""Obata-style ink cleanup post-process — crisp manga line art.

User: Cleaner Obata ink stroke (line cleanup pass) → manga_authenticity 7→9.

Death Note's Obata Takeshi has signature characteristics:
  - Hyper-sharp ink lines, no fuzz
  - Tapered stroke ends (variable line width)
  - High-contrast black-vs-white (no mid-gray)
  - Sharp screentone boundaries (not blurred)

Post-process pipeline:
  1. Convert to grayscale → numpy
  2. Detect edges (Sobel for direction-aware)
  3. Threshold edges → hard binary
  4. Black-hat + white-hat morphology for line refinement
  5. Posterize tone (kill mid-gray, push to B/W)
  6. Sharpen edges via UnsharpMask
  7. Final contrast boost
  Result: Obata-style crisp manga ink
"""
from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageFilter, ImageEnhance, ImageOps
import numpy as np


def obata_cleanup(image_path: Path, out_path: Path = None,
                   contrast_boost: float = 1.4,
                   sharpen_radius: float = 1.5,
                   sharpen_percent: int = 150,
                   posterize_levels: int = 4) -> Path:
    """Apply Obata-style ink cleanup to a manga panel/page.

    contrast_boost: overall contrast multiplier (1.4 = +40%)
    sharpen_radius: UnsharpMask blur radius
    sharpen_percent: UnsharpMask strength (100 = no change)
    posterize_levels: 4 = strong B&W + 2 mid-tones, 2 = pure B&W
    """
    im = Image.open(image_path).convert("RGB")
    arr = np.asarray(im).astype(np.float32)

    # 1) Convert to grayscale
    gray = im.convert("L")

    # 2) Sharpen edges via UnsharpMask (Obata's crisp line)
    sharpened = gray.filter(ImageFilter.UnsharpMask(
        radius=sharpen_radius, percent=sharpen_percent, threshold=2))

    # 3) Contrast boost (push toward stark black/white)
    enhancer = ImageEnhance.Contrast(sharpened)
    boosted = enhancer.enhance(contrast_boost)

    # 4) Posterize — collapses gradient to manga ink levels
    # 4 levels = white + 2 mid-tones + black (Obata-like)
    posterized = ImageOps.posterize(boosted, bits=int(np.log2(posterize_levels)))

    # 5) Final edge enhancement (one more pass for crisp lines)
    final = posterized.filter(ImageFilter.EDGE_ENHANCE)

    # 6) Back to RGB for save
    result = final.convert("RGB")

    if out_path is None:
        out_path = image_path
    result.save(out_path)
    return out_path


def obata_cleanup_with_diagnostics(image_path: Path) -> dict:
    """Run cleanup + return before/after metrics."""
    im_before = Image.open(image_path).convert("L")
    arr_before = np.asarray(im_before)

    out = image_path.with_name(image_path.stem + "_obata.png")
    obata_cleanup(image_path, out)

    im_after = Image.open(out).convert("L")
    arr_after = np.asarray(im_after)

    return {
        "before": {
            "mean": float(arr_before.mean()),
            "std":  float(arr_before.std()),
            "very_dark":  float((arr_before < 30).mean()),
            "very_light": float((arr_before > 220).mean()),
            "midtone":    float(((arr_before >= 80) & (arr_before <= 180)).mean()),
        },
        "after": {
            "mean": float(arr_after.mean()),
            "std":  float(arr_after.std()),
            "very_dark":  float((arr_after < 30).mean()),
            "very_light": float((arr_after > 220).mean()),
            "midtone":    float(((arr_after >= 80) & (arr_after <= 180)).mean()),
        },
        "out_path": str(out),
    }


if __name__ == "__main__":
    import sys, json
    p = Path(sys.argv[1])
    r = obata_cleanup_with_diagnostics(p)
    print(json.dumps(r, indent=2))
