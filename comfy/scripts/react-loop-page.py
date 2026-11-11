#!/usr/bin/env python3
"""ReAct loop: score-driven page/panel redesign.

For each page:
  1. RENDER the page (v10_orchestrator)
  2. SCORE — quality + placement
  3. REASON: identify weakest axis → form hypothesis
  4. ACT: adjust env params and re-render
  5. Repeat (max 3 iterations) until placement ≥ 80 AND quality ≥ 75

Adjustments by weak axis:
  - bubble_clear_of_faces < 7  → V11_BUBBLE_SHRINK=0.7 (smaller bubbles)
  - sfx_clear_of_characters < 7 → V11_SFX_SIZE_OVERRIDE=0.55 (smaller SFX)
  - sfx_expressiveness < 6      → V11_SEED_SALT bumped (re-roll SFX picker)
  - character_visibility < 7    → both above + retry
  - reading_flow < 7            → V11_LAYOUT=0 (fall back to uniform grid)

Run:
  bash scripts/react-loop-page.py 20 33 39  # ReAct on specific pages
  bash scripts/react-loop-page.py --weak     # all v11full pages where placement<70 or quality<70
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, time
from pathlib import Path

LG = Path(__file__).resolve().parents[1]
EVAL = LG / "scripts/eval-per-page.py"
PROMPT = "ghosthacker"
TIMEOUT = 1500

DEFAULT_ENV = {
    "OLLAMA_HOST":    "http://192.168.1.23:11434",
    "OLLAMA_MODEL":   "gemma4",
    "V11_LAYOUT":     "1",
    "V11_STYLE":      "witchwatch",
    "V11_IPADAPTER":  "1",
}

TARGET_QUALITY   = 75.0
TARGET_PLACEMENT = 80.0
MAX_ITER         = 3


def render(page_num: int, env: dict) -> tuple[float, float, dict]:
    """Render page → return (quality, placement, placement_axes)."""
    pp = f"{page_num:02d}"
    full_env = os.environ.copy()
    full_env.update(DEFAULT_ENV)
    full_env.update(env)
    # Render
    subprocess.run(["rm", "-f", f"/tmp/v10-p{pp}-scored.png",
                     f"/tmp/v10-p{pp}-score.json"], check=False)
    subprocess.run([
        "timeout", str(TIMEOUT),
        str(LG / ".venv/bin/python"),
        "-m", "lg_mangaka.v10_orchestrator",
        "--preset", PROMPT, str(page_num),
    ], env=full_env, cwd=str(LG), capture_output=True, text=True)
    if not Path(f"/tmp/v10-p{pp}-scored.png").exists():
        return 0.0, 0.0, {}
    # Save with v11react prefix
    subprocess.run(["mv", f"/tmp/v10-p{pp}-scored.png",
                     f"/tmp/v11react-p{pp}-scored.png"], check=False)
    subprocess.run(["mv", f"/tmp/v10-p{pp}-score.json",
                     f"/tmp/v11react-p{pp}-score.json"], check=False)

    # Quality from sidecar
    try:
        sc = json.load(open(f"/tmp/v11react-p{pp}-score.json"))
        quality = sc.get("total", 0)
    except Exception:
        quality = 0.0

    # Placement via eval-per-page on single page
    res = subprocess.run([
        str(LG / ".venv/bin/python"), str(EVAL),
        "--prefix", "v11react", "--pages", str(page_num),
    ], env=full_env, cwd=str(LG), capture_output=True, text=True)
    try:
        ps = json.load(open(f"/tmp/v11react-p{pp}-placement.json"))
        placement = ps.get("total", 0)
        axes = ps.get("scores", {})
    except Exception:
        placement, axes = 0.0, {}
    return quality, placement, axes


def reason_and_act(axes: dict, env: dict, iter_idx: int) -> dict:
    """Identify weakest axis and bump corresponding env variable."""
    new_env = dict(env)
    issues = []
    # Bubble overlap
    if axes.get("bubble_clear_of_faces", 10) < 7:
        cur = float(new_env.get("V11_BUBBLE_SHRINK", "1.0"))
        new_env["V11_BUBBLE_SHRINK"] = f"{max(0.5, cur * 0.85):.2f}"
        issues.append(f"bubble face overlap → shrink to {new_env['V11_BUBBLE_SHRINK']}")
    # SFX overlap
    if axes.get("sfx_clear_of_characters", 10) < 7:
        cur = float(new_env.get("V11_SFX_SIZE_OVERRIDE", "1.0"))
        new_env["V11_SFX_SIZE_OVERRIDE"] = f"{max(0.45, cur * 0.8):.2f}"
        issues.append(f"sfx body overlap → size {new_env['V11_SFX_SIZE_OVERRIDE']}")
    # SFX too uniform
    if axes.get("sfx_expressiveness", 10) < 6:
        salt = int(new_env.get("V11_SEED_SALT", "0")) + 997 * (iter_idx + 1)
        new_env["V11_SEED_SALT"] = str(salt)
        issues.append(f"sfx uniform → re-roll picker (salt={salt})")
    # Reading flow broken
    if axes.get("reading_flow", 10) < 7:
        new_env["V11_LAYOUT"] = "0"
        issues.append("reading flow → fall back to uniform grid layout")
    return new_env, issues


def run_react_loop(page_num: int):
    print(f"\n{'='*60}")
    print(f"ReAct loop: page {page_num}")
    print(f"{'='*60}")
    env = {}
    history = []
    for it in range(MAX_ITER):
        t0 = time.monotonic()
        print(f"\n[iter {it}] render... env diff: {env}")
        quality, placement, axes = render(page_num, env)
        dt = time.monotonic() - t0
        history.append({
            "iter": it, "quality": quality, "placement": placement,
            "axes": axes, "env": dict(env), "elapsed_s": round(dt, 1)
        })
        print(f"  → quality={quality:.1f}  placement={placement:.1f}  ({dt:.0f}s)")
        for axis, score in (axes or {}).items():
            sym = "✅" if score >= 7 else "⚠️" if score >= 5 else "❌"
            print(f"      {axis}: {score} {sym}")
        if quality >= TARGET_QUALITY and placement >= TARGET_PLACEMENT:
            print(f"  ✓ targets met (Q≥{TARGET_QUALITY}, P≥{TARGET_PLACEMENT})")
            break
        if it < MAX_ITER - 1:
            env, reasons = reason_and_act(axes, env, it)
            print(f"  REASON+ACT: {reasons}")
    # Save history
    Path(f"/tmp/v11react-p{page_num:02d}-history.json").write_text(
        json.dumps(history, indent=2, ensure_ascii=False))
    best = max(history, key=lambda h: h["quality"] * 0.5 + h["placement"] * 0.5)
    print(f"\n[FINAL] best iter {best['iter']}: Q={best['quality']:.1f} P={best['placement']:.1f}")
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pages", nargs="*", type=int, help="page numbers")
    ap.add_argument("--weak", action="store_true",
                     help="auto-pick weak pages from v11full")
    args = ap.parse_args()

    if args.weak:
        pages = []
        for f in sorted(Path("/tmp").glob("v11full-p*-placement.json")):
            pp = int(f.name.split("v11full-p")[-1].split("-")[0])
            try:
                p = json.load(open(f)).get("total", 0)
                if p < 70:
                    pages.append(pp)
            except: pass
        if not pages:
            print("no weak pages found (all placement ≥ 70)"); return
        print(f"weak pages: {pages}")
    else:
        pages = args.pages
    if not pages:
        print("usage: react-loop-page.py <page#> [<page#> ...] OR --weak"); return

    summary = {}
    for pg in pages:
        summary[pg] = run_react_loop(pg)

    print(f"\n{'='*60}")
    print(f"ReAct loop complete — {len(pages)} pages")
    for pg, best in summary.items():
        print(f"  p{pg:02d}: best Q={best['quality']:.1f} P={best['placement']:.1f} (iter {best['iter']})")


if __name__ == "__main__":
    main()
