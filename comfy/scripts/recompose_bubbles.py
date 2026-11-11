#!/usr/bin/env python3
"""既存の color page.json (色画像+顔は確定済) に対し、bubbles だけを最新の
build_canonical_storyboard ロジック(セリフ・パッキング C / 焦点尻尾 A)で再生成する。

画像・クロップ・顔・shot・gaze は触らず、各パネルの faces(色画像で検出済)を使って
build_bubbles を再実行し、未紐付け吹き出しの尻尾を焦点キャラへ向け直す。

RUN: python3 scripts/recompose_bubbles.py --in /tmp/m3v2-color.page.json --out /tmp/m3v2-color.page.json
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_canonical_storyboard as B  # noqa: E402

EP = os.path.join(os.path.dirname(os.path.dirname(HERE)),
                  "data/ghosthacker/resources/episodes/arc0-1-origin")


def recompose_panel(mp, faces):
    """manifest panel mp + 色画像顔 faces → 新 bubbles(C パッキング + A 焦点尻尾)。"""
    tone = mp.get("tone")
    bubs = B.build_bubbles(mp, tone, faces)
    if faces:
        foc = (mp.get("focusCharacter") or "").lower()
        focf = next((b for b in faces if len(b) > 5 and (b[5] or "").lower() == foc), None)
        for bub in bubs:
            if "linkTo" in bub or bub.get("shape") in ("rect", "whisper"):
                continue
            if "faceIndex" in bub:                  # build_bubbles が話者顔へ紐付け済み
                continue
            if focf is not None:                    # 焦点キャラ=主役=話者の既定
                bub["tailX"], bub["tailY"] = B._mouth(focf)
                continue
            ax, ay = B._ANCHOR_POS.get(bub.get("anchor", "top-right"), (500, 500))
            f = min(faces, key=lambda b: (b[0] + b[2] / 2 - ax) ** 2 + (b[1] + b[3] / 2 - ay) ** 2)
            bub["tailX"], bub["tailY"] = B._mouth(f)
    return bubs


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="/tmp/m3v2-color.page.json")
    ap.add_argument("--out", default="/tmp/m3v2-color.page.json")
    ap.add_argument("--manifest", default=os.path.join(EP, "image-gen-manifest.json"))
    args = ap.parse_args(argv)

    doc = json.load(open(args.inp))
    man = json.load(open(args.manifest))
    by_page = {}
    for p in man["panels"]:
        by_page.setdefault(p["pageNum"], []).append(p)
    for pn in by_page:
        by_page[pn].sort(key=lambda x: x.get("panelIndex", 0))

    before = after = 0
    for pg in doc["pages"]:
        mpanels = by_page.get(pg["pageNum"], [])
        cpanels = sorted(pg["panels"], key=lambda z: z["order"])
        for i, cp in enumerate(cpanels):
            if i >= len(mpanels):
                continue
            faces = cp.get("faces") or []
            before += sum(1 for b in cp.get("bubbles", [])
                          if b.get("shape") not in ("rect", "whisper"))
            cp["bubbles"] = recompose_panel(mpanels[i], faces)
            after += sum(1 for b in cp["bubbles"]
                         if b.get("shape") not in ("rect", "whisper"))

    json.dump(doc, open(args.out, "w"), ensure_ascii=False, indent=2)
    print(f"recomposed bubbles -> {args.out}")
    print(f"  speech bubbles: {before} -> {after} "
          f"({after - before:+d}, パッキングで断片統合)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
