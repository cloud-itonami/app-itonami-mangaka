#!/usr/bin/env python3
"""指定ページを各スタイルの生成画像でフルページ(komawari)合成して比較する。
ARIA コマ割りはそのままに、各パネルの _imagePath をスタイル画像へ差し替えて描画し、
スタイルを横並びにした比較シートを作る。

RUN: python3 scripts/render_style_pages.py --pages 6,39 \
        --styles virtual-prod,pixar,ekonte --model gemini-3.1-flash --out /tmp/style-pages
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EP = os.path.join(os.path.dirname(os.path.dirname(HERE)),
                  "data/ghosthacker/resources/episodes/arc0-1-origin")
ORC = "/tmp/orcmp"


def render(doc, pg, style, model, out_png):
    style_pg = json.loads(json.dumps(pg))               # deep copy
    pn = pg["pageNum"]
    d = f"{ORC}/{style}__{model}" if style != "manga" else f"{ORC}/{model}"
    for p in style_pg["panels"]:
        f = f"{d}/p{pn}-panel{p['order']}.png"
        if os.path.exists(f):
            p["_imagePath"] = f
        else:
            p.pop("_imagePath", None)
    one = {**doc, "pages": [style_pg]}
    tmp = f"/tmp/_styp_{pn}_{style}.page.json"
    json.dump(one, open(tmp, "w"), ensure_ascii=False)
    subprocess.run([sys.executable, os.path.join(HERE, "komawari_blueprint_pdf.py"),
                    "--in", tmp, "--out", f"/tmp/_styp_{pn}_{style}.pdf"],
                   env={**os.environ, "KOMA_CLEAN": "1"}, capture_output=True)
    src = f"/tmp/_styp_{pn}_{style}.p1.png"
    if os.path.exists(src):
        from PIL import Image
        Image.open(src).convert("RGB").save(out_png)
        return out_png
    return None


def main(argv=None):
    from PIL import Image, ImageDraw
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", default="6,39")
    ap.add_argument("--styles", default="virtual-prod,pixar,ekonte")
    ap.add_argument("--model", default="gemini-3.1-flash")
    ap.add_argument("--out", default="/tmp/style-pages")
    args = ap.parse_args(argv)
    doc = json.load(open(os.path.join(EP, "storyboard.komawari.page.json")))
    os.makedirs(args.out, exist_ok=True)
    styles = args.styles.split(",")
    for pn in [int(x) for x in args.pages.split(",")]:
        pg = next((p for p in doc["pages"] if p["pageNum"] == pn), None)
        if not pg:
            continue
        imgs = []
        for st in styles:
            op = os.path.join(args.out, f"p{pn}-{st}.png")
            r = render(doc, pg, st, args.model, op)
            imgs.append((st, r))
            print(f"  p{pn} {st}: {'ok' if r else 'FAILED'}")
        # 横並び比較シート
        thumbs = [(st, Image.open(p).convert("RGB")) for st, p in imgs if p]
        if not thumbs:
            continue
        th = 900
        scaled = [(st, im.resize((int(im.width * th / im.height), th))) for st, im in thumbs]
        W = sum(im.width for _, im in scaled) + 20 * len(scaled)
        sheet = Image.new("RGB", (W, th + 30), (255, 255, 255))
        d = ImageDraw.Draw(sheet)
        x = 10
        for st, im in scaled:
            sheet.paste(im, (x, 26))
            d.text((x, 6), f"p{pn} — {st}", fill=(0, 0, 0))
            x += im.width + 20
        sheet.save(os.path.join(args.out, f"p{pn}-compare.png"))
        print(f"  -> {args.out}/p{pn}-compare.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
