#!/usr/bin/env python3
"""m4(構図再設計 depth)で生成したカラー画像 + 再検出した顔で、ARIA コマ割りの
カラー page.json を構成する。build_canonical_storyboard を再利用し、画像解決と顔
キャッシュだけ m4 に差し替える(ARIA_KOMAWARI=1 で ARIA レイアウト採用)。

RUN: ARIA_KOMAWARI=1 python3 scripts/build_m4_color.py \
        --faces /tmp/m4-faces-id.json --out /tmp/m4-color.page.json
"""
import argparse
import collections
import json
import os
import sys

os.environ.setdefault("ARIA_KOMAWARI", "1")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_canonical_storyboard as B  # noqa: E402

EP = os.path.join(os.path.dirname(os.path.dirname(HERE)),
                  "data/ghosthacker/resources/episodes/arc0-1-origin")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--faces", default="/tmp/m4-faces-id.json")
    ap.add_argument("--imgdir", default="/tmp/m4-render")
    ap.add_argument("--manifest", default=os.path.join(EP, "image-gen-manifest.json"))
    ap.add_argument("--out", default="/tmp/m4-color.page.json")
    args = ap.parse_args(argv)

    B._FACES = json.load(open(args.faces))               # 顔キャッシュに差し替え

    def _resolve_img(page_num, panel_idx):
        if panel_idx is None:
            return ""
        f = f"{args.imgdir}/p{page_num}/p{page_num}-panel{panel_idx}.jpg"
        return f if os.path.exists(f) else ""
    B._resolve_image = _resolve_img                       # 画像解決を差し替え

    m = json.load(open(args.manifest))
    by_page = collections.defaultdict(list)
    for p in m["panels"]:
        by_page[p["pageNum"]].append(p)
    pages = [B.build_page(pn, by_page[pn]) for pn in sorted(by_page)]
    doc = {"episode": m.get("episode", "ghosthacker/arc0-1-origin"),
           "source": "m4 depth (構図再設計) + ARIA komawari",
           "schema": "ai.gftd.mangaka.page", "pages": pages}
    json.dump(doc, open(args.out, "w"), ensure_ascii=False, indent=2)
    nb = sum(len(p.get("bubbles", [])) for pg in pages for p in pg["panels"])
    print(f"wrote {args.out}: {len(pages)} pages, "
          f"{sum(len(pg['panels']) for pg in pages)} panels, {nb} bubbles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
