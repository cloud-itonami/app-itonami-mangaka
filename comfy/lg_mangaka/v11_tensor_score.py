"""v11 D — Tensor network composite scoring.

Goal: capture cross-panel interactions Gemma misses on per-panel score.

Model:
  Per page, build a tensor T[panel, axis] where rows are panels and
  cols are 8 score axes from Witch Watch / Death Note rubric.

  Then compute:
    1. Page mean per axis (already what we do as page total)
    2. Cross-panel coherence: variance of style axes (line, tone) —
       should be LOW for consistent style across panels
    3. Action-vs-quiet contrast: variance of dynamism axes — should be
       HIGH where the narrative beats demand contrast
    4. CP decomposition rank-2: latent factors give "style anchor"
       and "action anchor" — interpretable axes

  Final score = α * mean - β * style_variance + γ * dynamism_variance
                + δ * cp_anchor_strength

Falls back to plain mean if numpy decomposition fails.
"""
from __future__ import annotations
import math


# Style axes — should be CONSISTENT (low variance) across page
STYLE_AXES = {"line_clarity", "tonal_balance", "atmospheric_background",
               "character_anatomy", "manga_authenticity"}

# Dynamism axes — should VARY across page (different intensities)
DYNAMISM_AXES = {"panel_dynamism", "sfx_text", "composition_pose",
                  "character_expression"}


def page_tensor_score(panel_scores: list[dict],
                       alpha: float = 1.0,
                       beta: float = 0.15,
                       gamma: float = 0.2,
                       delta: float = 0.1,
                       panel_importance: list[float] = None) -> dict:
    """Compute tensor-network composite score from per-panel score dicts.
    Each dict should have 'scores' = {axis: value 0-10}.

    2026-05-27 B2 calibration:
      - beta 0.5 → 0.15: don't over-penalize intentional shot-variety
      - gamma 0.3 → 0.2: dynamism variance reward smaller (not the goal)
      - delta 0.2 → 0.1: anchor only mildly considered
      - panel_importance: weight panels by manifest emphasis (impact/punchline
        get full weight, beat/transition 0.8, others 0.6). Atmospheric Insert
        panels with no characters no longer drag the mean down as hard.
    """
    axes_seen = set()
    for ps in panel_scores:
        axes_seen.update(ps.get("scores", {}).keys())
    axes = sorted(axes_seen)
    if not axes or not panel_scores:
        return {"total": 0, "error": "no scores"}

    # Build matrix (panels × axes) — values clipped to [0,10]
    matrix = []
    for ps in panel_scores:
        row = [max(0.0, min(10.0, float(ps.get("scores", {}).get(a, 0))))
               for a in axes]
        matrix.append(row)

    n_panels = len(matrix)
    n_axes = len(axes)

    # Panel importance — default uniform; caller may pass per-panel weights
    if panel_importance is None or len(panel_importance) != n_panels:
        weights = [1.0] * n_panels
    else:
        weights = [max(0.1, float(w)) for w in panel_importance]
    wsum = sum(weights) or 1.0

    # Per-axis WEIGHTED mean across panels
    axis_means = []
    for i in range(n_axes):
        s = sum(weights[p] * matrix[p][i] for p in range(n_panels))
        axis_means.append(s / wsum)
    overall_mean = sum(axis_means) / n_axes

    # Per-axis weighted variance
    axis_vars = []
    for i in range(n_axes):
        m = axis_means[i]
        s = sum(weights[p] * (matrix[p][i] - m) ** 2 for p in range(n_panels))
        axis_vars.append(s / wsum)

    style_var_terms = [v for a, v in zip(axes, axis_vars) if a in STYLE_AXES]
    style_var = sum(style_var_terms) / max(1, len(style_var_terms))
    dyn_var_terms = [v for a, v in zip(axes, axis_vars) if a in DYNAMISM_AXES]
    dyn_var = sum(dyn_var_terms) / max(1, len(dyn_var_terms))

    top_axis_val = max(axis_means) if axis_means else 0
    anchor = top_axis_val - overall_mean

    # Composite — softer penalties, baseline anchored at mean
    raw = (alpha * overall_mean
            - beta * style_var
            + gamma * min(dyn_var, 4.0)
            + delta * anchor)
    total = max(0.0, min(100.0, raw * 10))

    return {
        "total": round(total, 1),
        "mean": round(overall_mean, 2),
        "style_variance": round(style_var, 3),
        "dynamism_variance": round(dyn_var, 3),
        "anchor_strength": round(anchor, 3),
        "n_panels": n_panels,
        "n_axes": n_axes,
        "weighted": panel_importance is not None,
    }


def panel_importance_from_manifest(panels: list[dict]) -> list[float]:
    """Build per-panel importance weights from manifest emphasis field.

    impact/punchline 1.0, beat 0.85, transition 0.75, establish 0.7,
    other 0.6. Insert shots without focal char drop to 0.5.
    """
    weights = []
    for p in panels:
        emph = (p.get("panelLayout", {}).get("gh:emphasis") or "").lower()
        shot = (p.get("shot") or "").lower()
        focal = p.get("focusedCharacters") or []
        if emph in ("impact", "punchline"):
            w = 1.0
        elif emph == "beat":
            w = 0.85
        elif emph == "transition":
            w = 0.75
        elif emph == "establish":
            w = 0.7
        else:
            w = 0.6
        if "insert" in shot and not focal:
            w *= 0.6
        weights.append(round(w, 2))
    return weights


if __name__ == "__main__":
    # Self-test
    fake_panels = [
        {"scores": {"line_clarity": 9, "character_anatomy": 8,
                     "panel_dynamism": 6, "sfx_text": 0, "manga_authenticity": 9}},
        {"scores": {"line_clarity": 9, "character_anatomy": 9,
                     "panel_dynamism": 9, "sfx_text": 10, "manga_authenticity": 9}},
        {"scores": {"line_clarity": 8, "character_anatomy": 9,
                     "panel_dynamism": 7, "sfx_text": 4, "manga_authenticity": 9}},
    ]
    print(page_tensor_score(fake_panels))
