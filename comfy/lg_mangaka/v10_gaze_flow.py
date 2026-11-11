"""v10 gaze-flow: per-panel gaze node + cross-panel sight-line routing.

User (2026-05-25): "sfx のいちが適切ではない、効果線の方向が次のパネルの
視点位置になるように。panel に視線誘導ノードをおいで、そこに絵, sfx が
流れるように"

References:
  - Haikyuu原稿用紙の使い方 (Weekly Shonen Jump #42, Furudate-sensei):
    3 frame lines (基準線 / 断ち切り線 / 外枠線), text inside 基準線
  - Death Note ch1: panels EXTEND beyond page frame when scenes connect
    (panel 1 smartphone bleeds across page; panel 2 character pose spans
    half page; panels connect via gaze flow)

This module provides:
  gaze_node(panel)              → (gx, gy) where reader's eye should focus
                                    (0-1 panel-local)
  sfx_position(panel, sfx_text) → (sx, sy) biased toward gaze_node
                                    SFX flows TOWARD gaze, not at edges
  flow_direction(p_curr, p_next) → angle for speed lines in curr panel
                                    pointing to next panel's gaze
  bleed_axis(panel)              → 'left','right','top','bottom', or None
                                    if panel should break frame
"""
from __future__ import annotations
from typing import Optional


def gaze_node(panel: dict) -> tuple[float, float]:
    """Where reader's eye should focus on this panel (panel-local 0-1)."""
    explicit = panel.get("gaze_node")
    if explicit and isinstance(explicit, (list, tuple)) and len(explicit) == 2:
        return float(explicit[0]), float(explicit[1])

    # Heuristic: derive from shot + focal character position
    shot = (panel.get("shot") or "").lower()
    focal = panel.get("focusedCharacters") or []

    # Single char panels: gaze on character face
    if len(focal) >= 1:
        if any(s in shot for s in ("extreme close", "close")):
            return (0.50, 0.40)   # face center
        if "insert" in shot:
            return (0.50, 0.50)   # object center
        if any(s in shot for s in ("wide", "long")):
            return (0.50, 0.65)   # character body lower-center
        return (0.50, 0.50)        # MS default

    # No focal: scene-driven gaze
    if "wide" in shot or "establish" in shot:
        return (0.50, 0.40)        # upper-center for establishing
    return (0.50, 0.50)


def flow_direction(p_curr: dict, p_next: Optional[dict] = None) -> float:
    """Angle (degrees) for SFX/speed lines pointing FROM curr gaze TO next.

    Returns angle in 0-360 (0=right, 90=down, 180=left, 270=up).
    If p_next is None, defaults to "drift right-down" (reading direction).
    """
    if p_next is None:
        # Default reading flow: right→down (manga is right-to-left BUT
        # the SFX should flow toward next reading position, which is
        # left for manga or right for western — keep right-down as
        # neutral SFX "outward" direction).
        return 135.0

    # Western reading: next panel is RIGHT-OF or BELOW current
    # Manga (Japanese): next panel is LEFT-OF or BELOW current
    # Our pipeline uses western order (left-to-right) — set per-config.
    g_curr = gaze_node(p_curr)
    g_next = gaze_node(p_next)
    # Compute angle from curr gaze to next gaze (approximate, panels
    # roughly side-by-side; +x toward right, +y toward bottom).
    import math
    dx = g_next[0] - g_curr[0] + 1.2   # panel-to-panel offset along x
    dy = g_next[1] - g_curr[1] + 0.6
    return math.degrees(math.atan2(dy, dx))


def sfx_position(panel: dict, sfx_text: str, panel_w: int, panel_h: int,
                  size_pct: float = 0.35) -> tuple[int, int]:
    """Place SFX biased TOWARD gaze node + matching flow direction.

    Returns (x, y) for SFX text top-left, panel-relative.
    """
    gx, gy = gaze_node(panel)
    # Position SFX so its CENTER aligns with gaze_node ± 0.15 in flow direction
    text_h = int(panel_h * size_pct)
    text_w = int(text_h * len(sfx_text) * 0.6)   # rough kana width

    # Place SFX text such that its CENTER is near gaze_node
    cx = int(panel_w * gx)
    cy = int(panel_h * gy)
    # Offset slightly to side of gaze (don't cover the focal point)
    offset_x = int(panel_w * 0.10)
    offset_y = int(panel_h * 0.05)
    x = cx + offset_x - text_w // 2
    y = cy + offset_y - text_h // 2
    # Clamp to panel bounds
    x = max(0, min(panel_w - text_w, x))
    y = max(0, min(panel_h - text_h, y))
    return x, y


def bleed_axis(panel: dict) -> Optional[str]:
    """Should this panel break the page frame? Returns 'left','right',
    'top','bottom', or None.

    Triggered when:
      - manifest has explicit panel.bleed = 'left'/'right'/'top'/'bottom'
      - Wide/Establishing shots with continuous scene flow
      - First/last panel of a page (often bleed top or bottom)
    """
    explicit = panel.get("bleed")
    if explicit in ("left", "right", "top", "bottom"):
        return explicit
    shot = (panel.get("shot") or "").lower()
    is_wide = "wide" in shot or "establish" in shot or "long" in shot
    idx = panel.get("panelIndex", 0)
    # Auto-detect: wide shots get bottom bleed, first panel gets top bleed
    if is_wide and idx > 1:
        return "bottom"
    if idx == 1 and is_wide:
        return "top"
    return None


if __name__ == "__main__":
    # Test gaze decisions
    import json
    from pathlib import Path
    MANIFEST = Path("/Users/junkawasaki/gftdcojp/ai-gftd-apps-gftdcojp/60-apps/ai-gftd-project-mangaka/data/ghosthacker/resources/episodes/arc0-1-origin/image-gen-manifest.json")
    m = json.loads(MANIFEST.read_text())
    p0 = sorted([p for p in m["panels"] if p["pageNum"] == 0], key=lambda x: x["panelIndex"])
    print("=== v10 gaze-flow per panel ===")
    for i, p in enumerate(p0):
        gx, gy = gaze_node(p)
        bleed = bleed_axis(p)
        nxt = p0[i + 1] if i + 1 < len(p0) else None
        flow = flow_direction(p, nxt)
        sx, sy = sfx_position(p, "ドット", 600, 400)
        print(f"  p0.{p['panelIndex']} ({p.get('shot','?'):20s}): "
              f"gaze=({gx:.2f},{gy:.2f})  flow={flow:.0f}°  bleed={bleed or '-':6s}  sfx=({sx},{sy})")
