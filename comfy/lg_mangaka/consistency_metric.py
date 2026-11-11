"""Quantitative cross-panel consistency metric (CLIP image-embedding cosine).

Replaces the LLM consistency rating, which saturated ~95–98 and could not
discriminate (ADR-2606171200 experiment, 2026-06-17). CLIP image embeddings give
a continuous, discriminating similarity: high for the same character/style across
panels, low for different ones — and it works on stylized manga art (unlike face
detectors trained on photos).

  consistency_b64(list_of_png_base64) -> float 0-100  (mean pairwise cosine)

CPU is fine (~1-2s/image). Model loads lazily and is cached. open_clip ViT-B-32.
"""
from __future__ import annotations

import base64
import io
from functools import lru_cache

import numpy as np
from PIL import Image

_MODEL_NAME = "ViT-B-32"
_PRETRAINED = "laion2b_s34b_b79k"


@lru_cache(maxsize=1)
def _model():
    import open_clip
    import torch
    model, _, preprocess = open_clip.create_model_and_transforms(
        _MODEL_NAME, pretrained=_PRETRAINED)
    model.eval()
    return model, preprocess, torch


def embed_bytes(image_bytes: bytes) -> np.ndarray:
    """L2-normalised CLIP image embedding for one PNG/JPEG."""
    model, preprocess, torch = _model()
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    with torch.no_grad():
        t = preprocess(img).unsqueeze(0)
        f = model.encode_image(t)
        f = f / f.norm(dim=-1, keepdim=True)
    return f[0].cpu().numpy().astype("float32")


def embed_b64(image_b64: str) -> np.ndarray:
    return embed_bytes(base64.b64decode(image_b64))


def _mean_pairwise_cosine(embs: list[np.ndarray]) -> float:
    sims = []
    for i in range(len(embs)):
        for j in range(i + 1, len(embs)):
            sims.append(float(np.dot(embs[i], embs[j])))
    return sum(sims) / len(sims) if sims else 0.0


def consistency_b64(images_b64: list[str]) -> float | None:
    """Mean pairwise CLIP cosine (0-100) across panel images. None if <2."""
    if not images_b64 or len(images_b64) < 2:
        return None
    embs = [embed_b64(b) for b in images_b64]
    return round(100.0 * _mean_pairwise_cosine(embs), 1)


def consistency_bytes(images: list[bytes]) -> float | None:
    if not images or len(images) < 2:
        return None
    return round(100.0 * _mean_pairwise_cosine([embed_bytes(b) for b in images]), 1)


# ── metric-health guard (negative-control discrimination probe) ──────────────
# A fitness axis is only trustworthy if it SEPARATES a pair that should be
# similar (a "good" control: same character across shots) from a pair that
# should differ (a "bad" control: that character vs a totally different
# subject). The gemma4 rating failed exactly here — good 96 vs bad 95, sep 1.
# A healthy metric needs a clear gap; CLIP gives ~76 vs ~33 (sep ~43).

MIN_SEPARATION = 15.0


def metric_separation(good_score: float | None, bad_score: float | None) -> float | None:
    """good = score of a pair that SHOULD be similar; bad = a pair that SHOULD
    differ. Returns good-bad (None if either is missing)."""
    if good_score is None or bad_score is None:
        return None
    return round(good_score - bad_score, 1)


def is_discriminating(good_score: float | None, bad_score: float | None,
                      min_sep: float = MIN_SEPARATION) -> bool:
    """True iff the metric separates the good control from the bad control by at
    least `min_sep`. A saturated metric (good≈bad) returns False → the loop must
    distrust its fitness instead of optimising a broken signal."""
    sep = metric_separation(good_score, bad_score)
    return sep is not None and sep >= min_sep
