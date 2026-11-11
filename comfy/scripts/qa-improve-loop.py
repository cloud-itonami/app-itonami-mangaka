"""QA-driven improvement loop for arc 0-1 pages.

  1. Score all 46 rendered pages with score-manga-pages.py heuristic
  2. Pick worst N pages below threshold
  3. Re-render each with new seed offset
  4. Re-score; keep the higher of (original score, new score)
  5. Iterate until convergence or max attempts

Note: this loops *external* to ComfyUI. We invoke
render-arc01-page.py for each re-render, which respects the
seed-offset CLI flag introduced for this loop.
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Import the scoring module
sys.path.insert(0, str(Path(__file__).parent))
import importlib.util
_spec = importlib.util.spec_from_file_location("scorer", "/tmp/score-manga-pages.py")
scorer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scorer)


TMP = Path("/tmp")
RENDERER = "/tmp/render-arc01-page.py"


def score_all() -> list[dict]:
    out = []
    for n in range(46):
        f = TMP / f"gh-arc0-1-p{n:02d}-final.png"
        if not f.exists():
            continue
        r = scorer.score_page(f)
        r["page"] = n
        out.append(r)
    return out


def re_render(page: int, seed_offset: int) -> bool:
    print(f"  re-render p{page} seed-offset={seed_offset}")
    # Move existing to attempt-tagged backup
    src = TMP / f"gh-arc0-1-p{page:02d}-final.png"
    if src.exists():
        bak = TMP / f"gh-arc0-1-p{page:02d}-attempt{seed_offset - 1}.png"
        if not bak.exists():  # don't overwrite prior attempts
            shutil.copy(src, bak)
        src.unlink()
    proc = subprocess.run(
        ["python3", RENDERER, str(page), "--seed-offset", str(seed_offset)],
        capture_output=True, text=True, timeout=900,
    )
    if proc.returncode != 0:
        print(f"    FAIL: rc={proc.returncode}")
        print(f"    stderr: {proc.stderr[-500:]}")
        return False
    if not src.exists():
        print(f"    FAIL: no output file")
        return False
    return True


def main():
    threshold = 65.0   # pages below this get re-rolled
    max_attempts = 2   # per-page max re-render attempts
    target_count = 10  # bottom-N to focus on

    print("=== initial scoring ===")
    initial = score_all()
    initial.sort(key=lambda r: r["total"])
    worst = [r for r in initial if r["total"] < threshold][:target_count]
    if not worst:
        print(f"all {len(initial)} pages >= {threshold}, no work needed")
        return 0

    print(f"\nPages below {threshold} (worst {len(worst)}):")
    for r in worst:
        print(f"  p{r['page']:02d} total={r['total']:5.1f}")

    # Per-page best score tracking
    best = {r["page"]: r["total"] for r in initial}

    for attempt in range(1, max_attempts + 1):
        print(f"\n=== attempt {attempt} — re-rendering with seed-offset={attempt} ===")
        for r in worst:
            p = r["page"]
            if best[p] >= threshold:
                continue  # already improved beyond threshold
            ok = re_render(p, attempt)
            if not ok:
                continue
            # Re-score
            f = TMP / f"gh-arc0-1-p{p:02d}-final.png"
            new = scorer.score_page(f)
            new_total = new["total"]
            print(f"    new total={new_total:5.1f} (was {best[p]:5.1f})")
            if new_total > best[p]:
                best[p] = new_total
                print(f"    KEEP (improved)")
                # Save attempt to mark history
                hist = TMP / f"gh-arc0-1-p{p:02d}-best-attempt.txt"
                hist.write_text(f"attempt={attempt} score={new_total:.1f}\n")
            else:
                # Revert to backup
                bak = TMP / f"gh-arc0-1-p{p:02d}-attempt{attempt - 1}.png"
                if bak.exists():
                    shutil.copy(bak, f)
                    print(f"    REVERT (lower score)")
                else:
                    # No backup, keep new even though worse
                    print(f"    KEEP (no backup to revert to)")

    print("\n=== final scoring ===")
    final = score_all()
    final.sort(key=lambda r: r["total"])
    initial_by_page = {r["page"]: r["total"] for r in initial}
    print(f"{'page':>4s}  {'init':>5s}  {'final':>5s}  {'Δ':>6s}")
    for r in final:
        p = r["page"]
        i_t = initial_by_page[p]
        f_t = r["total"]
        d = f_t - i_t
        marker = " ↑" if d > 1 else ("↓" if d < -1 else "")
        print(f"  p{p:02d}   {i_t:5.1f}  {f_t:5.1f}  {d:+6.1f} {marker}")

    # Summary
    n_improved = sum(1 for r in final if r["total"] - initial_by_page[r["page"]] > 1)
    n_worse = sum(1 for r in final if r["total"] - initial_by_page[r["page"]] < -1)
    above_thresh_init = sum(1 for r in initial if r["total"] >= threshold)
    above_thresh_final = sum(1 for r in final if r["total"] >= threshold)
    print(f"\nimproved: {n_improved}  worse: {n_worse}")
    print(f">= {threshold}: {above_thresh_init} -> {above_thresh_final}")


if __name__ == "__main__":
    sys.exit(main() or 0)
