#!/usr/bin/env python3
"""読者目線のナラティブ明瞭度スコア — このページ単体(画像+セリフ)で、背景知識ゼロの
読者にシーン/出来事/意図が伝わるかを採点する。

各ページを描画し、そのページのセリフ書き起こし(読み順)を添えて gemma3:4b vision に
『初見・前情報なしの読者』として読ませ、(1) 理解した内容 (2) 明瞭度 0-10 (3) 分かり
にくい点 を JSON で返させる。さらに manifest の意図(pageTitle/sceneSubject)と突き合わ
せ、意図が伝わったか(intent_match)も採点する。

RUN: python3 scripts/narrative_score_pages.py --in /tmp/m3v2-color.page.json [--pages 7]
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
EP = os.path.join(os.path.dirname(os.path.dirname(HERE)),
                  "data/ghosthacker/resources/episodes/arc0-1-origin")
PROMPT = (
    "You are a FIRST-TIME reader of this Japanese manga page. You have NO prior "
    "knowledge of the story, characters, or what came before. Look ONLY at this "
    "page's panels and read its dialogue (provided as a transcript in reading "
    "order, right-to-left top-to-bottom). Judge whether THIS PAGE ALONE makes its "
    "scene and events clear.\n\nTRANSCRIPT:\n{tx}\n\n"
    "Answer ONLY JSON: {{\"understood\": \"1-2 sentences: what you think is "
    "happening here\", \"clarity\": <0-10 int, 10=who/where/what-is-happening is "
    "instantly clear from images+text, 5=roughly followable, 0=confusing/cannot "
    "tell>, \"confusing\": [\"specific unclear things, e.g. who is speaking, what "
    "this object is, where this is, what just happened, how panels connect\"]}}"
)
INTENT_PROMPT = (
    "A first-time reader looked at a manga page and said it shows: \"{u}\".\n"
    "The page's INTENDED scene is: \"{intent}\".\n"
    "Does the reader's understanding match the intended scene? Answer ONLY JSON: "
    "{{\"intent_match\": <0-10 int, 10=fully conveys the intent, 0=reader got it "
    "wrong/missed it>, \"gap\": \"what the page failed to convey, if any\"}}"
)
SCHEMA = {"type": "object", "properties": {
    "understood": {"type": "string"}, "clarity": {"type": "integer"},
    "confusing": {"type": "array", "items": {"type": "string"}}},
    "required": ["understood", "clarity"]}
ISCHEMA = {"type": "object", "properties": {
    "intent_match": {"type": "integer"}, "gap": {"type": "string"}},
    "required": ["intent_match"]}


def render_page(doc, pg, out_png):
    json.dump({**doc, "pages": [pg]}, open("/tmp/_nr_one.page.json", "w"), ensure_ascii=False)
    subprocess.run([sys.executable, os.path.join(HERE, "komawari_blueprint_pdf.py"),
                    "--in", "/tmp/_nr_one.page.json", "--out", "/tmp/_nr_one.pdf"],
                   env={**os.environ, "KOMA_CLEAN": "1"}, capture_output=True)
    if os.path.exists("/tmp/_nr_one.p1.png"):
        Image.open("/tmp/_nr_one.p1.png").convert("RGB").save(out_png)
        return out_png
    return None


def _gemma(png, prompt, schema, host="http://localhost:11434"):
    im = Image.open(png).convert("RGB")
    w, h = im.size
    im = im.resize((1024, int(1024 * h / w)))            # 文字を読めるよう高めの解像度
    buf = BytesIO()
    im.save(buf, "JPEG", quality=90)
    body = json.dumps({"model": "gemma3:4b", "prompt": prompt, "images": [base64.b64encode(
        buf.getvalue()).decode()], "stream": False, "format": schema,
        "options": {"temperature": 0}}).encode()
    req = urllib.request.Request(host + "/api/generate", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        resp = json.loads(r.read())["response"]
    m = re.search(r"\{.*\}", resp, re.S)
    return json.loads(m.group(0)) if m else {}


def _gemma_text(prompt, schema, host="http://localhost:11434"):
    body = json.dumps({"model": "gemma3:4b", "prompt": prompt, "stream": False,
                       "format": schema, "options": {"temperature": 0}}).encode()
    req = urllib.request.Request(host + "/api/generate", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        resp = json.loads(r.read())["response"]
    m = re.search(r"\{.*\}", resp, re.S)
    return json.loads(m.group(0)) if m else {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="/tmp/m3v2-color.page.json")
    ap.add_argument("--pages", default="")
    ap.add_argument("--out", default="/tmp/narrative-scores.json")
    args = ap.parse_args()
    doc = json.load(open(args.inp))
    man = json.load(open(os.path.join(EP, "image-gen-manifest.json")))
    intents = {}
    for p in man["panels"]:
        intents.setdefault(p["pageNum"], []).append(p.get("sceneSubject") or "")
    pages = doc["pages"]
    if args.pages:
        want = {int(x) for x in args.pages.split(",")}
        pages = [pg for pg in pages if pg["pageNum"] in want]
    os.makedirs("/tmp/nrpages", exist_ok=True)
    results = []
    for pg in pages:
        pn = pg["pageNum"]
        # transcript: bubbles in reading order
        tx = []
        for p in sorted(pg["panels"], key=lambda z: z["order"]):
            for b in p.get("bubbles", []):
                t = "".join(b.get("lines") or [b.get("text", "")])
                if t:
                    tx.append(f"[panel{p['order']}{('/'+b['speaker']) if b.get('speaker') else ''}] {t}")
        transcript = "\n".join(tx) or "(no dialogue)"
        png = render_page(doc, pg, f"/tmp/nrpages/p{pn:02d}.png")
        if not png:
            continue
        try:
            r = _gemma(png, PROMPT.format(tx=transcript), SCHEMA)
            intent = " / ".join(dict.fromkeys(x for x in intents.get(pn, []) if x))
            ir = _gemma_text(INTENT_PROMPT.format(u=r.get("understood", ""), intent=intent), ISCHEMA)
        except Exception as e:
            print(f"p{pn}: error {e}")
            continue
        clar = max(0, min(10, int(r.get("clarity", 0))))
        imatch = max(0, min(10, int(ir.get("intent_match", 0))))
        rec = {"page": pn, "title": pg.get("pageTitle", "").split("[")[0].strip(),
               "clarity": clar, "intent_match": imatch, "intent": intent,
               "understood": r.get("understood", ""), "confusing": r.get("confusing", [])[:4],
               "gap": ir.get("gap", "")}
        results.append(rec)
        print(f"p{pn:02d} clarity {clar:2d} intent {imatch:2d} | {rec['understood'][:70]}")
    json.dump(results, open(args.out, "w"), ensure_ascii=False, indent=2)
    if results:
        avg_c = round(sum(r["clarity"] for r in results) / len(results), 1)
        avg_i = round(sum(r["intent_match"] for r in results) / len(results), 1)
        print(f"\n=== avg clarity {avg_c} / intent_match {avg_i} over {len(results)} pages ===")
        worst = sorted(results, key=lambda r: r["clarity"] + r["intent_match"])[:12]
        print("\n--- 伝わっていないページ(clarity+intent低い順) ---")
        for r in worst:
            print(f"p{r['page']:02d} clr{r['clarity']} int{r['intent_match']} {r['title'][:20]:20s}")
            print(f"     読者理解: {r['understood'][:88]}")
            print(f"     意図:    {r['intent'][:88]}")
            if r["confusing"]:
                print(f"     不明点:  {' / '.join(r['confusing'])[:100]}")
    print(f"\nsaved -> {args.out}")


if __name__ == "__main__":
    main()
