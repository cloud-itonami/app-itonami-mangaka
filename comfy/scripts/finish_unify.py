#!/usr/bin/env python3
"""仕上げ統一工程(manga 仕上げの AI 版) — 独立生成で不揃いなパネル群を1作家の手による
統一感へ揃える。3方式を比較できる:

  A page  : 合成済みページを gemini-flash で一括統一(レイアウト保持指示)
  B anchor: 各パネルを共通 style anchor に gemini-flash で揃える(komawari 保持)◎
  C grade : 手続き型カラーグレード調和(anchor の色統計へ per-channel 転写、API不要)

RUN: python3 scripts/finish_unify.py --method b --page 37 \
        --indir /tmp/cleanfinal37 --anchor 2 --out /tmp/unify-b
"""
import argparse
import base64
import glob
import json
import os
import re
import subprocess
import urllib.request
from io import BytesIO

import numpy as np
from PIL import Image

UNIFY_PAGE = (
    "This is one manga page made of multiple panels generated separately, so the panels look "
    "inconsistent. Re-finish it as ONE cohesive page drawn by a single artist: unify the color "
    "grade, line weight, inking, shading and screentone across ALL panels. KEEP the exact panel "
    "layout, panel borders, gutters, speech bubbles and all text EXACTLY as-is — only harmonize "
    "the artwork style. Output the full page.")
UNIFY_PANEL = (
    "The FIRST image is the STYLE REFERENCE. Re-finish the SECOND image so its art style matches "
    "the reference: same color palette/grade, line weight, inking, shading and screentone "
    "treatment. KEEP the second image's composition, characters, poses, framing and content "
    "completely unchanged — only restyle the rendering to match the reference. Output the "
    "restyled second image, same aspect ratio.")


def _key():
    return (subprocess.run(["security", "find-generic-password", "-s", "gftd.openrouter", "-w"],
                           capture_output=True, text=True).stdout.strip()
            or os.environ.get("OPENROUTER_APIKEY"))


def gemini_edit(imgs_b64, prompt, key, model="google/gemini-2.5-flash-image", timeout=200):
    content = [{"type": "text", "text": prompt}] + [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b}} for b in imgs_b64]
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": content}],
                       "modalities": ["image", "text"]}).encode()
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", body,
                                 {"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    r = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    imgs = r["choices"][0]["message"].get("images") or []
    if not imgs:
        raise RuntimeError("no image")
    return base64.b64decode(imgs[0]["image_url"]["url"].split(",", 1)[1])


def color_grade(src, ref):
    """per-channel mean/std を ref の色統計へ転写(Reinhard 風の簡易カラーグレード調和)。"""
    s = np.asarray(src.convert("RGB"), float)
    r = np.asarray(ref.convert("RGB"), float)
    out = np.empty_like(s)
    for c in range(3):
        sm, ss = s[..., c].mean(), s[..., c].std() + 1e-5
        rm, rs = r[..., c].mean(), r[..., c].std() + 1e-5
        out[..., c] = np.clip((s[..., c] - sm) / ss * rs * 0.85 + rm, 0, 255)
    return Image.fromarray(out.astype("uint8"))


def _b64(path):
    return base64.b64encode(open(path, "rb").read()).decode()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--method", choices=["a", "b", "c"], required=True)
    ap.add_argument("--page", type=int, default=37)
    ap.add_argument("--indir", default="/tmp/cleanfinal37")
    ap.add_argument("--anchor", type=int, default=2)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    pn = args.page
    key = _key()
    os.makedirs(args.out, exist_ok=True)

    if args.method == "a":                               # ページ一括
        page = f"{args.indir}/p{pn}-cut.p1.png"
        data = gemini_edit([_b64(page)], UNIFY_PAGE, key)
        open(f"{args.out}/p{pn}-unified-A.png", "wb").write(data)
        print(f"A -> {args.out}/p{pn}-unified-A.png")
        return 0

    # B / C はパネル毎に処理 → {out}/p{pn}-panels/ に出して後で render_cut_page --reuse で合成
    od = f"{args.out}/p{pn}-panels"
    os.makedirs(od, exist_ok=True)
    panels = sorted(glob.glob(f"{args.indir}/p{pn}-panels/p{pn}-panel*.png"),
                    key=lambda f: int(re.search(r"panel(\d+)", f).group(1)))
    anchor = f"{args.indir}/p{pn}-panels/p{pn}-panel{args.anchor}.png"
    ref_im = Image.open(anchor).convert("RGB")
    for f in panels:
        idx = int(re.search(r"panel(\d+)", f).group(1))
        outp = f"{od}/p{pn}-panel{idx}.png"
        if args.method == "c":
            color_grade(Image.open(f), ref_im).save(outp)
        else:                                            # b: gemini anchor restyle
            if idx == args.anchor:
                Image.open(f).convert("RGB").save(outp)  # anchor はそのまま
            else:
                try:
                    open(outp, "wb").write(gemini_edit([_b64(anchor), _b64(f)], UNIFY_PANEL, key))
                except Exception as e:
                    print(f"  panel{idx} ERR {str(e)[:50]}")
                    Image.open(f).convert("RGB").save(outp)
        print(f"  {args.method} panel{idx}")
    print(f"{args.method} panels -> {od} (compose with render_cut_page --reuse --out {args.out})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
