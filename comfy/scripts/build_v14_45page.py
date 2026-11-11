#!/usr/bin/env python3
"""Build the v14 45-page edition with redesigned panel pacing (情報設計).

Compose-only (NO ComfyUI): reuses existing source-panels via :panel/src-ref
provenance. 38 pages are reused 1:1 from final-pages/; 7 pages are recomposed
with new layouts (2 dense merges, 1 splash split → 2 pages, 3 splash-led
hero relayouts). Assembles all 45 into a single PDF.

  python -m scripts.build_v14_45page
"""
from __future__ import annotations
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lg_mangaka import v14_storyboard_renderer as R  # noqa: E402
from lg_mangaka.storyboard_db import StoryboardDB     # noqa: E402

V14 = Path(__file__).resolve().parents[2] / "data/ghosthacker/resources/episodes/arc0-1-origin/v14"
EDN = V14 / "storyboard-edn"
SRC = V14 / "source-panels"
FIN = V14 / "final-pages"
OUT = Path("/tmp/v14-45")
OUT.mkdir(parents=True, exist_ok=True)
PDF = V14 / "ghosthacker-arc0-1-origin-v14-45page.pdf"


def canon_edn(origpage: int) -> Path:
    for c in (f"p{origpage:02d}-datomic-v3.edn",
              f"p{origpage:02d}-datomic-v2.edn",
              f"p{origpage:02d}-datomic.edn"):
        fp = EDN / c
        if fp.exists():
            return fp
    raise FileNotFoundError(f"no EDN for p{origpage:02d}")


_PAGE_CACHE: dict[int, dict] = {}


def load_page(origpage: int) -> dict:
    """Export the source page as a Lexicon dict (panels keyed by index)."""
    if origpage in _PAGE_CACHE:
        return _PAGE_CACHE[origpage]
    db = StoryboardDB.load_edn(str(canon_edn(origpage)))
    chars = StoryboardDB.load_edn(str(EDN / "characters.edn"))
    db.merge_db(chars)
    page_eid = next((eid for eid, e in db.entities.items() if ":page/number" in e), None)
    lex = db.export_lexicon(page_eid)
    by_idx = {p["index"]: p for p in lex["panels"]}
    out = {"lex": lex, "by_idx": by_idx}
    _PAGE_CACHE[origpage] = out
    return out


def panel(origpage: int, index: int, rect, bleed=None) -> dict:
    """Clone a source panel, stamp src-ref, override layout (drop polygon/tilt)."""
    src = load_page(origpage)["by_idx"][index]
    p = json.loads(json.dumps(src))  # deep copy
    p["src-ref"] = f"p{origpage:02d}-{index}"
    p["rect"] = [round(v, 4) for v in rect]
    for k in ("polygon", "tilt"):           # tied to old rect → drop
        p.pop(k, None)
    if bleed is not None:
        p["bleed"] = bleed
    else:
        p.pop("bleed", None)
    return p


def tiers_to_rects(tiers, weights=None, m=0.022, g=0.016):
    """tiers = list of column-counts per horizontal row (top→bottom).
    weights = per-row height weights (default equal). Returns story-order rects."""
    if weights is None:
        weights = [1.0] * len(tiers)
    avail_h = 1 - 2 * m - (len(tiers) - 1) * g
    wsum = sum(weights)
    heights = [avail_h * w / wsum for w in weights]
    rects, y = [], m
    for ncol, h in zip(tiers, heights):
        x = m
        colw = (1 - 2 * m - (ncol - 1) * g) / ncol
        for _ in range(ncol):
            rects.append([x, y, colw, h])
            x += colw + g
        y += h + g
    return rects


def make_storyboard(page_num, title, layout, panels):
    base = load_page(panels[0]["src"][0])["lex"]
    return {
        "$type": "ai.gftd.mangaka.storyboard",
        "pageNumber": page_num,
        "pageTitle": title,
        "layout": layout,
        "baseTags": base["baseTags"],
        "negativeTags": base["negativeTags"],
        "panels": [panel(*p["src"], p["rect"], p.get("bleed")) for p in panels],
    }


def P(origpage, index, rect, bleed=None):
    return {"src": (origpage, index), "rect": rect, "bleed": bleed}


# ── 45-page sequence ────────────────────────────────────────────────────────
# Each entry: ("reuse", origpage) | ("recompose", title, layout, [P(...), ...])
def recompose_specs():
    specs = {}

    # np07 — Renの部屋・7年の壁 (splash-led, hero p06.1)
    r = tiers_to_rects([1, 2, 2], weights=[1.45, 1.0, 1.0])
    specs[7] = ("Renの部屋・7年の捜査壁", "jump-introspective-splash", [
        P(6, 1, r[0], bleed=["top"]),
        P(6, 2, r[1]), P(6, 3, r[2]),
        P(6, 4, r[3]), P(6, 5, r[4]),
    ])

    # np18 — 消えたい (splash-led, hero p17.4 big bottom)
    r = tiers_to_rects([3, 1], weights=[1.0, 2.1])
    specs[18] = ("消えたい", "jump-rejection-throw", [
        P(17, 1, r[0]), P(17, 2, r[1]), P(17, 3, r[2]),
        P(17, 4, r[3], bleed=["bottom", "left", "right"]),
    ])

    # np24 — 漏洩とお金 (dense merge p23+p24 → 8)
    r = tiers_to_rects([2, 2, 2, 2])
    specs[24] = ("HIBP・4件の漏洩 / チャージバック", "jump-investigation-dense", [
        P(23, 1, r[0]), P(23, 3, r[1]), P(23, 4, r[2]), P(23, 5, r[3]),
        P(24, 1, r[4]), P(24, 2, r[5]), P(24, 3, r[6]), P(24, 5, r[7]),
    ])

    # np26 — パスワード講座 (dense merge p26+p27 → 8)
    r = tiers_to_rects([2, 2, 2, 2])
    specs[26] = ("パスワードは覚えるな / 全切替", "jump-lesson-dense", [
        P(26, 1, r[0]), P(26, 2, r[1]), P(26, 3, r[2]), P(26, 5, r[3]),
        P(27, 1, r[4]), P(27, 3, r[5]), P(27, 4, r[6]), P(27, 5, r[7]),
    ])

    # np32 — 世界が、反転した (FULL-PAGE SPLASH, p33.1)
    specs[32] = ("世界が、反転した", "jump-reality-inversion-splash", [
        P(33, 1, [0.0, 0.0, 1.0, 1.0], bleed=["top", "bottom", "left", "right"]),
    ])

    # np33 — ゴースト顕現 (p33.2-5, 2×2)
    r = tiers_to_rects([2, 2])
    specs[33] = ("ゴースト顕現", "jump-supernatural-reveal", [
        P(33, 2, r[0]), P(33, 3, r[1]), P(33, 4, r[2]), P(33, 5, r[3]),
    ])

    # np35 — NULL AXE 顕現 (splash-led, hero 35.3 axe + 35.4 slash)
    r = tiers_to_rects([2, 1, 1], weights=[1.0, 1.15, 1.55])
    specs[35] = ("NULL AXE 顕現", "jump-weapon-summon", [
        P(35, 1, r[0]), P(35, 2, r[1]),
        P(35, 3, r[2]),
        P(35, 4, r[3], bleed=["bottom", "left", "right"]),
    ])
    return specs


SEQUENCE = [
    ("reuse", 0), ("reuse", 1), ("reuse", 2), ("reuse", 3), ("reuse", 4),
    ("reuse", 5), ("recompose", 7), ("reuse", 7), ("reuse", 8), ("reuse", 9),
    ("reuse", 10), ("reuse", 11), ("reuse", 12), ("reuse", 13), ("reuse", 14),
    ("reuse", 15), ("reuse", 16), ("recompose", 18), ("reuse", 18), ("reuse", 19),
    ("reuse", 20), ("reuse", 21), ("reuse", 22), ("recompose", 24), ("reuse", 25),
    ("recompose", 26), ("reuse", 28), ("reuse", 29), ("reuse", 30), ("reuse", 31),
    ("reuse", 32), ("recompose", 32), ("recompose", 33), ("reuse", 34),
    ("recompose", 35), ("reuse", 36), ("reuse", 37), ("reuse", 38), ("reuse", 39),
    ("reuse", 40), ("reuse", 41), ("reuse", 42), ("reuse", 43), ("reuse", 44),
    ("reuse", 45),
]


def reuse_final(origpage: int) -> Path:
    cand = FIN / f"v14-p{origpage:02d}-final.png"
    if cand.exists():
        return cand
    raise FileNotFoundError(f"no reuse final for p{origpage:02d}: {cand}")


def main():
    specs = recompose_specs()
    assert len(SEQUENCE) == 45, f"sequence is {len(SEQUENCE)} pages, need 45"
    final_pngs = []
    for np_idx, (kind, ref) in enumerate(SEQUENCE, start=1):
        dst = OUT / f"np{np_idx:02d}-final.png"
        if kind == "reuse":
            shutil.copy(reuse_final(ref), dst)
            print(f"np{np_idx:02d}  REUSE   p{ref:02d}")
        else:
            title, layout, panels = specs[np_idx]
            sb = make_storyboard(np_idx, title, layout, panels)
            sb_path = OUT / f"np{np_idx:02d}.json"
            sb_path.write_text(json.dumps(sb, ensure_ascii=False, indent=2))
            R.render_storyboard(str(sb_path), out_dir=str(OUT),
                                reading_direction="rtl",
                                reletter=True, src_dir=str(SRC))
            rendered = OUT / f"v14-p{np_idx:02d}-final.png"
            shutil.copy(rendered, dst)
            print(f"np{np_idx:02d}  RECOMP  {title}  ({len(panels)} panels)")
        final_pngs.append(dst)

    # ── assemble PDF ─────────────────────────────────────────────────────────
    from PIL import Image
    imgs = [Image.open(p).convert("RGB") for p in final_pngs]
    imgs[0].save(PDF, "PDF", resolution=144.0, save_all=True,
                 append_images=imgs[1:])
    print(f"\n[PDF] {PDF}  ({len(imgs)} pages)")


if __name__ == "__main__":
    main()
