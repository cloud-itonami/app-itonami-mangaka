#!/usr/bin/env python3
"""ページ単位の Jump-manga quality スコア + 要修正箇所の特定。

各ページを描画し、gemma3:4b vision (local ollama) で Death Note ルーブリック
(jump_benchmark_qa の8軸)を採点しつつ、そのページの『具体的に直すべき箇所』を
列挙させる。重み付け合計・ティア・低スコアページ・課題を一覧出力する。

RUN: python3 scripts/jump_score_pages.py --in /tmp/m3v2-color.page.json [--pages 0,1]
"""
import argparse
import base64
import json
import os
import re
import subprocess
import sys
import urllib.request
from io import BytesIO

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
WEIGHTS = {  # jump_benchmark_qa.WEIGHTS
    "character_anatomy": 0.18, "multi_character_quality": 0.12,
    "background_detail": 0.12, "composition_pose": 0.12,
    "bubble_integration": 0.08, "manga_authenticity": 0.18,
    "sfx_text": 0.10, "environment_detail": 0.10,
}
AXES = list(WEIGHTS)
PROMPT = (
    "You are grading ONE manga page against Death Note (小畑健) = publication-grade "
    "shonen. Rate each axis 0-10 STRICTLY (10=Obata published, 5=competent doujin, "
    "0=AI blob): character_anatomy, multi_character_quality, background_detail, "
    "composition_pose (camera/panel VARIETY — penalize uniform same-size panels & "
    "same shots), bubble_integration (balloons tight to the correct speaker, NOT "
    "covering faces — penalize balloons overlapping a character's face), "
    "manga_authenticity, sfx_text, environment_detail. THEN list 1-3 CONCRETE "
    "fixable issues on THIS page as short phrases naming the panel where possible "
    "(e.g. 'balloon covers face panel 4', 'panels too uniform', 'weak anatomy panel "
    "2', 'static composition', 'character inconsistent'). Output ONLY JSON."
)
SCHEMA = {"type": "object", "properties": {
    **{a: {"type": "integer"} for a in AXES},
    "issues": {"type": "array", "items": {"type": "string"}}},
    "required": AXES}
TIERS = [(85, "看板 (flagship)"), (70, "人気作 (popular)"), (55, "中堅 (mid)"),
         (40, "打切 (cancel-risk)"), (25, "AI artifact"), (0, "block-out")]


def tier(score):
    return next(name for thr, name in TIERS if score >= thr)


def render_page(doc, pg, out_png):
    one = {**doc, "pages": [pg]}
    tmp = "/tmp/_jp_one.page.json"
    json.dump(one, open(tmp, "w"), ensure_ascii=False)
    env = {**os.environ, "KOMA_CLEAN": "1"}
    subprocess.run([sys.executable, os.path.join(HERE, "komawari_blueprint_pdf.py"),
                    "--in", tmp, "--out", "/tmp/_jp_one.pdf"],
                   env=env, capture_output=True)
    src = "/tmp/_jp_one.p1.png"
    if os.path.exists(src):
        Image.open(src).convert("RGB").save(out_png)
        return out_png
    return None


def score_page(png, model="gemma3:4b", host="http://localhost:11434"):
    im = Image.open(png).convert("RGB")
    w, h = im.size
    im = im.resize((768, int(768 * h / w)))
    buf = BytesIO()
    im.save(buf, "JPEG", quality=88)
    b64 = base64.b64encode(buf.getvalue()).decode()
    body = json.dumps({"model": model, "prompt": PROMPT, "images": [b64],
                       "stream": False, "format": SCHEMA,
                       "options": {"temperature": 0}}).encode()
    req = urllib.request.Request(host + "/api/generate", body,
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        resp = json.loads(r.read())["response"]
    m = re.search(r"\{.*\}", resp, re.S)
    d = json.loads(m.group(0)) if m else {}
    scores = {a: max(0, min(10, int(d.get(a, 0)))) for a in AXES}
    total = round(sum(scores[a] / 10 * WEIGHTS[a] for a in AXES) * 100, 1)
    return {"scores": scores, "total": total, "tier": tier(total),
            "issues": [str(x) for x in (d.get("issues") or [])][:3]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="/tmp/m3v2-color.page.json")
    ap.add_argument("--pages", default="")
    ap.add_argument("--out", default="/tmp/jump-scores.json")
    args = ap.parse_args()
    doc = json.load(open(args.inp))
    pages = doc["pages"]
    if args.pages:
        want = {int(x) for x in args.pages.split(",")}
        pages = [pg for pg in pages if pg["pageNum"] in want]
    os.makedirs("/tmp/jpages", exist_ok=True)
    results = []
    for pg in pages:
        pn = pg["pageNum"]
        png = render_page(doc, pg, f"/tmp/jpages/p{pn:02d}.png")
        if not png:
            print(f"p{pn}: render failed")
            continue
        try:
            r = score_page(png)
        except Exception as e:
            print(f"p{pn}: score error {e}")
            continue
        r["page"] = pn
        r["title"] = pg.get("pageTitle", "").split("[")[0].strip()
        results.append(r)
        print(f"p{pn:02d} {r['total']:5.1f} {r['tier']:18s} | "
              + " ".join(f"{a[:4]}{r['scores'][a]}" for a in AXES))
    json.dump(results, open(args.out, "w"), ensure_ascii=False, indent=2)
    if results:
        avg = round(sum(r["total"] for r in results) / len(results), 1)
        print(f"\n=== EPISODE avg {avg} ({tier(avg)}) over {len(results)} pages ===")
        worst = sorted(results, key=lambda r: r["total"])[:12]
        print("\n--- 要修正(低スコア順) ---")
        for r in worst:
            print(f"p{r['page']:02d} {r['total']:5.1f} {r['tier']:14s} {r['title'][:24]:24s} "
                  f":: {' / '.join(r['issues'])}")
    print(f"\nsaved -> {args.out}")


if __name__ == "__main__":
    main()
