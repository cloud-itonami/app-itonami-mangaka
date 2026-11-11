#!/usr/bin/env python3
"""構図画像生成 model の比較採点 — process『構図画像 → ControlNet → Animagine』の
前段として、各 model が作る構図画像を中立の vision judge(OpenRouter)で盲検採点する。
評価軸は ControlNet 入力としての良さ: shot-framing 一致 / 人物配置 / 透視・奥行き /
解剖学的整合 / コマとしての読みやすさ。

RUN: python3 scripts/score_composition.py --dir /tmp/orcmp --pages 0,1 \
        --judge anthropic/claude-sonnet-4.5 --out /tmp/orcmp-scores.json
"""
import argparse
import base64
import collections
import json
import os
import subprocess
import urllib.request

AXES = ["framing", "placement", "perspective", "anatomy", "readability"]
RUBRIC = (
    "You are judging a single black-and-white manga panel image that will be used as a "
    "COMPOSITION REFERENCE for a ControlNet pipeline (its lines/structure guide a final "
    "render). Score 0-10 each (10=excellent):\n"
    "- framing: does it read as the intended shot type and fill the frame well?\n"
    "- placement: clear, intentional character/subject placement and eye-flow\n"
    "- perspective: believable depth, perspective, environment blocking\n"
    "- anatomy: correct anatomy/hands/proportions (no melting/extra limbs)\n"
    "- readability: instantly readable as a clean manga panel (good control source)\n"
    "Intended shot: {shot}. Scene: {scene}.\n"
    "Answer ONLY JSON: {{\"framing\":int,\"placement\":int,\"perspective\":int,"
    "\"anatomy\":int,\"readability\":int,\"note\":\"<=12 words\"}}"
)


def _key():
    return (subprocess.run(["security", "find-generic-password", "-s", "gftd.openrouter", "-w"],
                           capture_output=True, text=True).stdout.strip()
            or os.environ.get("OPENROUTER_APIKEY"))


def judge(img_path, shot, scene, model, key, timeout=120):
    from io import BytesIO
    from PIL import Image
    im = Image.open(img_path).convert("RGB")          # 大きい PNG は 400 になるため縮小+JPEG
    if max(im.size) > 1024:
        s = 1024 / max(im.size)
        im = im.resize((int(im.width * s), int(im.height * s)))
    buf = BytesIO()
    im.save(buf, "JPEG", quality=88)
    b64 = base64.b64encode(buf.getvalue()).decode()
    content = [{"type": "text", "text": RUBRIC.format(shot=shot, scene=scene)},
               {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}}]
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": content}]}).encode()
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", body,
                                 {"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    r = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    txt = r["choices"][0]["message"]["content"]
    import re
    mt = re.search(r"\{.*\}", txt, re.S)
    d = json.loads(mt.group(0)) if mt else {}
    return {a: max(0, min(10, int(d.get(a, 0)))) for a in AXES}, d.get("note", "")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="/tmp/orcmp")
    ap.add_argument("--pages", default="0,1")
    ap.add_argument("--judge", default="anthropic/claude-opus-4.8")
    ap.add_argument("--manifest", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data/ghosthacker/resources/episodes/arc0-1-origin/image-gen-manifest.json"))
    ap.add_argument("--extra", default="animagine(m4):/tmp/m4-render",
                    help="比較に加える追加モデル label:dir(画像は p{N}-panel{idx}.jpg)")
    ap.add_argument("--out", default="/tmp/orcmp-scores.json")
    args = ap.parse_args(argv)
    key = _key()
    m = json.load(open(args.manifest))
    want = {int(x) for x in args.pages.split(",")}
    meta = {(p["pageNum"], p.get("panelIndex")): p for p in m["panels"] if p["pageNum"] in want}
    models = sorted(d for d in os.listdir(args.dir)
                    if os.path.isdir(os.path.join(args.dir, d)) and "__" not in d)
    extra = dict(x.split(":", 1) for x in args.extra.split(",")) if args.extra else {}
    agg = collections.defaultdict(list)
    rows = []
    for (pn, idx), p in sorted(meta.items()):
        shot, scene = p.get("shot", ""), (p.get("sceneSubject") or "")[:60]
        for label, path in ([(mm, os.path.join(args.dir, mm, f"p{pn}-panel{idx}.png")) for mm in models]
                            + [(k, f"{v}/p{pn}/p{pn}-panel{idx}.jpg") for k, v in extra.items()]):
            if not os.path.exists(path):
                continue
            try:
                sc, note = judge(path, shot, scene, args.judge, key)
            except Exception as e:
                print(f"  ERR {label} p{pn}#{idx}: {str(e)[:70]}")
                continue
            tot = sum(sc.values()) / len(AXES)
            agg[label].append(tot)
            rows.append({"model": label, "page": pn, "panel": idx, "total": round(tot, 2), **sc})
            print(f"  {label:18s} p{pn}#{idx} {tot:4.1f}  ({note[:40]})")
    summary = {k: round(sum(v) / len(v), 2) for k, v in agg.items() if v}
    json.dump({"judge": args.judge, "summary": summary, "rows": rows},
              open(args.out, "w"), ensure_ascii=False, indent=2)
    print("\n=== COMPOSITION SCORE (judge: %s) ===" % args.judge)
    for k, v in sorted(summary.items(), key=lambda z: -z[1]):
        print(f"  {k:20s} {v:.2f}  (n={len(agg[k])})")
    print(f"\nsaved -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
