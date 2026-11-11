"""Stable style fingerprint for a render recipe.

The co-scientist's optimisation UNIT is the render recipe's *style* (the levers it
tunes), so real-world engagement must be aggregated per style — not per seed or
per panel. `fingerprint(recipe)` is a deterministic hash over the style levers
only (style_tags, negative, cfg, sampler), ignoring per-panel composition
(`extra_prompt`) and the random seed. Same style → same fingerprint → engagement
accrues to it across every work it produced (ADR-2606181200).
"""
from __future__ import annotations

import hashlib
import json

# The style levers the co-scientist evolves. extra_prompt (subject/composition)
# and seed are deliberately excluded so the same look fingerprints identically
# regardless of which panel/subject it rendered.
_STYLE_KEYS = ("style_tags", "negative", "cfg", "sampler")


def _norm(key: str, value) -> object:
    if value is None:
        return ""
    if key == "cfg":
        try:
            return round(float(value), 1)
        except (TypeError, ValueError):
            return 0.0
    # normalise tag strings: lowercase, collapse whitespace, sort comma tokens so
    # "a, b" and "b,a" fingerprint the same.
    s = str(value).lower()
    parts = [p.strip() for p in s.split(",") if p.strip()]
    return ",".join(sorted(parts))


def fingerprint(recipe: dict) -> str:
    norm = {k: _norm(k, recipe.get(k)) for k in _STYLE_KEYS}
    blob = json.dumps(norm, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
