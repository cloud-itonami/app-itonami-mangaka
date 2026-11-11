"""v11 — Jump-style variable panel layout (bleed + angle + irregular).

Augments existing panelLayout with rendering-time hints:
  - gh:bleed: "full"|"top"|"bottom"|"left"|"right"|"none"
        Panel content extends to page edge (overrides MARGIN).
  - gh:angle: float degrees (-15..15)
        Panel rotated. Other panels reflow around the tilted bbox.
  - gh:shape: "rect" (default) | future: "trapezoid"|"diamond"

Auto-augmentation rules (heuristic, deterministic per page):
  - punchline + large       → bleed:"bottom" or "full"
  - establish + Wide + first→ bleed:"top"
  - impact + tense/action   → angle:-8..-12 (action burst)
  - Insert + tense          → angle:+10..+15 (chaos insert)
  - everything else         → no change
"""
from __future__ import annotations
import hashlib
from typing import Optional


def _hash_pick(seed_str: str, choices: list) -> str:
    h = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)
    return choices[h % len(choices)]


def _hash_float(seed_str: str, lo: float, hi: float) -> float:
    h = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)
    return lo + (h % 1000) / 1000.0 * (hi - lo)


def augment_panel(panel: dict, page_idx: int, panel_idx: int,
                   total_panels: int) -> dict:
    """Return augmented panelLayout dict with bleed/angle annotations.
    Idempotent — if explicit fields already set, keep them."""
    layout = dict(panel.get("panelLayout", {}))
    shot = (panel.get("shot") or "").lower()
    tone = (panel.get("tone") or "").lower()
    emphasis = layout.get("gh:emphasis", "").lower()
    size = layout.get("gh:size", "medium").lower()
    seed = f"p{page_idx:02d}_{panel_idx}_{shot}_{tone}"

    # Bleed rules — 2026-05-27 revised: only edge-bleed (1 direction toward
    # page border). NO "full" — that wipes other panels when not single-panel.
    # Bleed direction picked so it extends OUTWARD only (toward nearest edge),
    # not inward over other panels.
    if "gh:bleed" not in layout:
        if emphasis == "punchline" and size in ("large", "spread"):
            # Last panel of page — extend downward to page bottom (most common)
            layout["gh:bleed"] = "bottom"
        elif emphasis == "establish" and "wide" in shot and panel_idx == 1:
            # First panel of page — extend upward to page top
            layout["gh:bleed"] = "top"
        elif emphasis == "impact" and size in ("large", "spread") and tone in ("tense", "action"):
            # Action burst — extend sideways (deterministic, not random)
            layout["gh:bleed"] = "right" if panel_idx % 2 else "left"
        else:
            layout["gh:bleed"] = "none"

    # Angle rules
    if "gh:angle" not in layout:
        angle = 0.0
        if emphasis == "impact" and tone in ("tense", "action", "ominous"):
            # Action burst — tilt
            angle = _hash_float(seed, -12.0, -6.0)
        elif "insert" in shot and tone in ("tense", "action"):
            # Chaos insert
            angle = _hash_float(seed, 6.0, 14.0)
        elif tone == "action" and emphasis != "punchline":
            angle = _hash_float(seed, -8.0, 8.0)
        layout["gh:angle"] = round(angle, 1)

    if "gh:shape" not in layout:
        layout["gh:shape"] = "rect"

    return layout


def augment_page(panels_in_page: list, page_idx: int) -> list:
    """Augment all panels of a page. Returns new list (panels deep-copied)."""
    out = []
    total = len(panels_in_page)
    for p in panels_in_page:
        new_p = dict(p)
        new_p["panelLayout"] = augment_panel(p, page_idx, p["panelIndex"], total)
        out.append(new_p)
    return out


# Rendering helpers --------------------------------------------------------

def expand_slot_for_bleed(slot: dict, page_w: int, page_h: int, margin: int) -> dict:
    """Return modified slot coords for bleed direction.
    Caller pulls gh:bleed from slot['panel']['panelLayout']."""
    bleed = slot.get("panel", {}).get("panelLayout", {}).get("gh:bleed", "none")
    if bleed == "none":
        return slot
    new = dict(slot)
    if bleed == "full":
        new["x"], new["y"] = 0, 0
        new["w"], new["h"] = page_w, page_h
    elif bleed == "top":
        new["y"] = 0
        new["h"] = slot["y"] + slot["h"]
    elif bleed == "bottom":
        new["h"] = page_h - slot["y"]
    elif bleed == "left":
        new["x"] = 0
        new["w"] = slot["x"] + slot["w"]
    elif bleed == "right":
        new["w"] = page_w - slot["x"]
    return new


def apply_angle_to_panel(panel_img, angle: float, slot_w: int, slot_h: int):
    """Rotate panel content by angle degrees, keep slot bbox.
    Edges clipped to bbox. Returns PIL Image of slot_w x slot_h."""
    from PIL import Image
    if abs(angle) < 0.5:
        return panel_img
    # Rotate and crop to original bbox (corners get cropped — intentional
    # Jump-style: panel content overflows / diagonal edges visible).
    rotated = panel_img.rotate(angle, resample=Image.BICUBIC,
                                expand=False, fillcolor=(255, 255, 255))
    return rotated
