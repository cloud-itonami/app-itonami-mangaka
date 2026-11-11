"""v11 — Page-level layout type detection.

User feedback (2026-05-29): p0 should be a 1-panel 扉絵 (chapter opener),
not a multi-panel grid. Current pipeline treats every page as standard grid.

Page types (heuristic detection from manifest):

  - single_dramatic: 1-2 panels, opening / climax / impact moment
      heuristic: total panels ≤ 2 OR (1 panel with emphasis=establish/punchline)
      override: gh:size = "spread" + gh:bleed = "full"

  - action_sequence: 5+ panels, action-heavy emphasis
      heuristic: ≥3 panels with emphasis=impact AND ≥2 with tone=action/tense
      override: tilt + bleed on impact panels, gutter compressed

  - dialogue_heavy: 4-6 panels, all dialogue
      heuristic: 80%+ panels have dialogues field non-empty
      override: bubble cap relaxed, panels arranged for reading flow

  - page_spread: cross-page composition (NOT auto-detected — explicit manifest flag)

  - standard_grid (default): everything else
      no override
"""
from __future__ import annotations


def detect_page_layout_type(panels: list[dict]) -> str:
    """Return one of single_dramatic / action_sequence / dialogue_heavy /
    standard_grid based on heuristics over the page's panel list."""
    n = len(panels)
    if n == 0:
        return "standard_grid"

    # Single dramatic — opening or full-page impact
    if n <= 2:
        # All panels emphasis=establish or punchline → very likely 扉絵 or climax
        emphs = [p.get("panelLayout", {}).get("gh:emphasis", "") for p in panels]
        if all(e in ("establish", "punchline", "impact") for e in emphs):
            return "single_dramatic"
        if n == 1:
            return "single_dramatic"

    # Action sequence
    n_impact = sum(1 for p in panels
                    if p.get("panelLayout", {}).get("gh:emphasis") == "impact")
    n_action = sum(1 for p in panels
                    if (p.get("tone") or "").lower() in ("action", "tense", "ominous"))
    if n >= 5 and n_impact >= 3 and n_action >= 2:
        return "action_sequence"

    # Dialogue heavy
    with_dialogue = sum(1 for p in panels
                         if p.get("dialogues") and any(d.get("text") for d in p["dialogues"]))
    if n >= 4 and with_dialogue >= int(n * 0.75):
        return "dialogue_heavy"

    return "standard_grid"


def apply_page_layout_override(panels: list[dict], layout_type: str) -> list[dict]:
    """Mutate panels' panelLayout to apply the detected page type.
    Returns the modified panel list. Idempotent — explicit overrides preserved."""
    if layout_type == "single_dramatic":
        # Force the single (or two) panels to dominate page
        for p in panels:
            pl = p.setdefault("panelLayout", {})
            pl.setdefault("gh:size", "spread")
            pl.setdefault("gh:bleed", "full")
            # Single panel uses entire page → 1 row + 1 col
            pl.setdefault("gh:row", 1)
            pl.setdefault("gh:colSpan", 6)
            pl.setdefault("gh:rowSpan", 6)
    elif layout_type == "action_sequence":
        # Action panels get tilt + bleed
        for p in panels:
            pl = p.setdefault("panelLayout", {})
            emph = pl.get("gh:emphasis", "")
            tone = (p.get("tone") or "").lower()
            if emph == "impact" and tone in ("action", "tense"):
                pl.setdefault("gh:angle", -8)
                pl.setdefault("gh:bleed", "right")
            elif emph == "punchline":
                pl.setdefault("gh:bleed", "bottom")
    elif layout_type == "dialogue_heavy":
        # Slightly larger panels, more breathing room for bubbles
        for p in panels:
            pl = p.setdefault("panelLayout", {})
            cur = pl.get("gh:size", "medium")
            if cur == "small":
                pl["gh:size"] = "medium"
    # standard_grid: no changes
    return panels


def page_arc_summary(panels: list[dict], layout_type: str) -> str:
    """Build a short narrative summary of the page for prompt injection.
    Returns a one-line summary describing the page's emotional arc."""
    if not panels:
        return ""
    title = panels[0].get("pageTitle", "")
    if layout_type == "single_dramatic":
        prefix = "Single dramatic page"
    elif layout_type == "action_sequence":
        prefix = "Action sequence page"
    elif layout_type == "dialogue_heavy":
        prefix = "Dialogue scene page"
    else:
        prefix = "Story page"
    if title:
        return f"{prefix}: {title}"
    return prefix


if __name__ == "__main__":
    # Self-test
    import json
    m = json.load(open(
        "/Users/junkawasaki/gftdcojp/ai-gftd-apps-gftdcojp/60-apps/ai-gftd-project-mangaka/"
        "data/ghosthacker/resources/episodes/arc0-1-origin/image-gen-manifest.json"))
    pages = {}
    for p in m["panels"]:
        pages.setdefault(p["pageNum"], []).append(p)
    print("Page → detected layout:")
    counts = {}
    for pg in sorted(pages):
        t = detect_page_layout_type(pages[pg])
        counts[t] = counts.get(t, 0) + 1
        print(f"  p{pg:02d}: {t}  ({len(pages[pg])} panels)")
    print()
    print("Layout type distribution:")
    for t, c in counts.items():
        print(f"  {t}: {c}")
