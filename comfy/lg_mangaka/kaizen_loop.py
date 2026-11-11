"""Kaizen loop — best-of-N rendering with per-iteration scoring.

User: kaizen loop を回して — iterate p00 (or any page) with N seed
variations + pick the best total. Reports per-iteration trajectory so
the improvement is visible / auditable.

Each iteration:
  1. Re-render page with fresh page_seed (clears /tmp char/bg/panel files)
  2. Run jump_qa + manifest_qa via existing render-v5 vision_score
  3. Compare against running best
  4. Keep best PNG + score.json + tag with iteration number

Usage:
  python kaizen_loop.py [--preset NAME] <page_num> [--iters N] [--seed-start S]

Output:
  /tmp/kaizen-pNN-iterM-scored.png   (per-iteration)
  /tmp/kaizen-pNN-best-scored.png    (best of N)
  /tmp/kaizen-pNN-summary.json       (full trajectory)
"""
from __future__ import annotations
import json, sys, time, os, importlib.util, shutil
from pathlib import Path

def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); sys.modules[name] = m
    spec.loader.exec_module(m)
    return m

_PROJ = Path(__file__).parent.parent
ORCH = _load("orch", str(_PROJ / "lg_mangaka/v7_orchestrator.py"))
# v6/cinematic/manga paths route through render-v5-page.py react_loop().
RV5 = _load("rv5_main", str(_PROJ / "scripts/render-v5-page.py"))
FA = _load("fa", str(_PROJ / "lg_mangaka/first_axes.py"))


def kaizen(page_num: int, iters: int = 4, preset: str = "ghosthacker",
            seed_start: int = 12345, base: str = "v7"):
    """Kaizen loop. base=v7 (character-first) or v6 (Blender+USD+SDXL).

    Process mining (2026-05-25) showed pre-v7 v5plus runs hit 69.9 with
    v6 path (rich Blender scenes + SDXL stylize via ControlNet). v7
    character-first plateaued at 60-63. To chase 90, kaizen now defaults
    to v7 but can switch via --base v6.
    """
    axes = FA.load_preset(preset) if preset else None
    if axes is not None:
        resolved = FA.resolve_env(axes)
        for k, v in resolved.items():
            os.environ[k] = v
        # Override V5_BASE if explicit base requested (overrides preset default)
        if base in ("v6", "manga", "cinematic"):
            os.environ["V5_BASE"] = base
            print(f"[kaizen] forcing V5_BASE={base} (overrides preset)")

    trajectory = []
    best = None
    out_dir = Path("/tmp")

    for it in range(iters):
        seed = seed_start + it * 1000
        # Override the page_seed by monkey-patching SCENE_MAPPING access:
        # easier — set env that page_seed computation reads.
        os.environ["KAIZEN_SEED_OFFSET"] = str(it * 1000)
        # Clear caches per iteration so re-render really happens
        for pat in (f"v7-bg-pg-p*.png", f"v7-char-pg-p*.png",
                     f"v7-pg-panel-*.png", f"v7-pg-panel-*_alpha.png"):
            for f in out_dir.glob(pat):
                f.unlink(missing_ok=True)

        print(f"\n=== Kaizen iter {it+1}/{iters} (seed={seed}, base={base}) ===")
        t0 = time.monotonic()
        if base in ("v6", "manga", "cinematic"):
            # Route through legacy render-v5-page react_loop (Blender + USD
            # + SDXL ControlNet stylize). Process mining showed this hit 69.9
            # on p05. FIRST_AXES is set in resolver block above.
            RV5.FIRST_AXES = axes
            score = RV5.react_loop(page_num)
        else:
            score = ORCH.render_page_v7(page_num, axes=axes)
        elapsed = time.monotonic() - t0
        if not isinstance(score, dict):
            print(f"  ! render returned no score; skipping iter {it+1}")
            continue

        total = score.get("total", 0)
        jump = score.get("jump_qa", {}).get("total", 0)
        mfst = score.get("scores", {}).get("manifest_qa_total", 0)
        entry = {"iter": it + 1, "seed": seed, "total": total,
                  "jump_qa": jump, "manifest_qa": mfst,
                  "elapsed_s": round(elapsed, 1)}
        trajectory.append(entry)
        print(f"  → total={total} jump={jump} manifest={mfst} ({elapsed:.0f}s)")

        # Snapshot per iteration
        src_png = out_dir / f"gh-arc0-1-v5plus-p{page_num:02d}-scored.png"
        src_json = out_dir / f"gh-arc0-1-v5plus-p{page_num:02d}-score.json"
        snap_png = out_dir / f"kaizen-p{page_num:02d}-iter{it+1}-scored.png"
        snap_json = out_dir / f"kaizen-p{page_num:02d}-iter{it+1}-score.json"
        if src_png.exists():
            shutil.copy2(src_png, snap_png)
        if src_json.exists():
            shutil.copy2(src_json, snap_json)

        # Update best
        if best is None or total > best["total"]:
            best = {"iter": it + 1, "seed": seed, "total": total,
                    "jump_qa": jump, "manifest_qa": mfst,
                    "png": str(src_png), "json": str(src_json)}
            shutil.copy2(src_png, out_dir / f"kaizen-p{page_num:02d}-best-scored.png")
            shutil.copy2(src_json, out_dir / f"kaizen-p{page_num:02d}-best-score.json")
            print(f"  ★ new best")

    summary = {
        "page":       page_num,
        "preset":     preset,
        "iters":      iters,
        "best":       best,
        "trajectory": trajectory,
    }
    summary_path = out_dir / f"kaizen-p{page_num:02d}-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\n=== Kaizen done ===")
    print(f"  best: iter {best['iter']} total {best['total']}")
    print(f"  PNG:  /tmp/kaizen-p{page_num:02d}-best-scored.png")
    print(f"  summary: {summary_path}")
    return summary


if __name__ == "__main__":
    argv = sys.argv[1:]
    preset = "ghosthacker"; iters = 4; seed_start = 12345; page_num = 0
    base = "v7"
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--preset" and i + 1 < len(argv):
            preset = argv[i + 1]; i += 2; continue
        if a == "--iters" and i + 1 < len(argv):
            iters = int(argv[i + 1]); i += 2; continue
        if a == "--seed-start" and i + 1 < len(argv):
            seed_start = int(argv[i + 1]); i += 2; continue
        if a == "--base" and i + 1 < len(argv):
            base = argv[i + 1]; i += 2; continue
        if a.isdigit():
            page_num = int(a); i += 1; continue
        i += 1
    kaizen(page_num, iters=iters, preset=preset, seed_start=seed_start, base=base)
