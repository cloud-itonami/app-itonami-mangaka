#!/usr/bin/env python3
"""アニメ顔検出 (Gemma 3n E4B, ローカル ollama・データ外部送信なし)。

lbpcascade はリアル寄りで、スタイライズ/隠れたアニメ顔を取りこぼす。Gemma 3n の
vision で各パネル画像から顔の bounding box を取り、cascade と同形式
(faces-cache.json: {imagePath:{size:[w,h], faces:[[x,y,w,h px]]}})で書き出す。

RUN: python3 scripts/detect_faces_gemma.py \
        --storyboard <storyboard.komawari.page.json> \
        --model gemma3n:e4b --out scripts/faces-cache.json [--only-missing] [--limit N]
"""
import argparse
import base64
import json
import os
import re
import urllib.request
from io import BytesIO

from PIL import Image

PROMPT = (
    "You are a precise face detector for MANGA / ANIME artwork. Detect EVERY "
    "visible character face in this panel — be EXHAUSTIVE: include small, distant, "
    "background, group-scene, partially-cropped, and profile faces. For each face "
    "give a tight bounding box AND its orientation 'dir': 'front' (facing viewer), "
    "'left' (face/profile turned to the image LEFT), or 'right'. Coordinates are "
    "PERMILLE (0-1000) of the image: x,y = top-left, w,h = size. Respond with ONLY "
    "JSON: {\"faces\":[{\"x\":0,\"y\":0,\"w\":0,\"h\":0,\"dir\":\"front\"}]}. Empty if none."
)
SCHEMA = {"type": "object", "properties": {"faces": {"type": "array", "items": {
    "type": "object", "properties": {
        **{k: {"type": "integer"} for k in "xywh"},
        "dir": {"type": "string", "enum": ["front", "left", "right"]}},
    "required": list("xywh")}}}, "required": ["faces"]}


def call_gemma(b64, model, host):
    body = json.dumps({"model": model, "prompt": PROMPT, "images": [b64],
                       "stream": False, "format": SCHEMA,
                       "options": {"temperature": 0}}).encode()
    req = urllib.request.Request(host + "/api/generate", body,
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())["response"]


def to_px(faces, w, h):
    out = []
    for f in faces:
        try:
            x, y, fw, fh = (int(f["x"]) / 1000 * w, int(f["y"]) / 1000 * h,
                            int(f["w"]) / 1000 * w, int(f["h"]) / 1000 * h)
        except Exception:
            continue
        if fw < 6 or fh < 6 or fw > w or fh > h:
            continue
        d = f.get("dir", "front")
        out.append([int(max(0, x)), int(max(0, y)), int(fw), int(fh),
                    d if d in ("front", "left", "right") else "front"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--storyboard", required=True)
    ap.add_argument("--model", default="gemma3:4b")   # e4b(gemma3n)はollama vision非対応
    ap.add_argument("--host", default="http://localhost:11434")
    ap.add_argument("--out", required=True)
    ap.add_argument("--only-missing", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    cache = {}
    if os.path.exists(args.out):
        cache = json.load(open(args.out))

    doc = json.load(open(args.storyboard))
    paths = sorted({p["_imagePath"] for pg in doc["pages"] for p in pg["panels"]
                    if p.get("_imagePath") and os.path.exists(p["_imagePath"])})
    if args.only_missing:
        paths = [p for p in paths if not cache.get(p, {}).get("faces")]
    if args.limit:
        paths = paths[:args.limit]

    done = 0
    for i, path in enumerate(paths):
        try:
            im = Image.open(path).convert("RGB")
            w, h = im.size
            buf = BytesIO()
            im.resize((512, int(512 * h / w)) if w >= h else (int(512 * w / h), 512)).save(buf, "JPEG", quality=85)
            b64 = base64.b64encode(buf.getvalue()).decode()
            resp = call_gemma(b64, args.model, args.host)
            faces = []
            m = re.search(r"\{.*\}", resp, re.S)
            if m:
                try:
                    faces = json.loads(m.group(0)).get("faces", [])
                except Exception:
                    pass
            if not faces:                                  # bare array fallback
                a = re.search(r"\[.*\]", resp, re.S)
                if a:
                    try:
                        faces = json.loads(a.group(0))
                    except Exception:
                        pass
            cache[path] = {"size": [w, h], "faces": to_px(faces, w, h)}
            done += 1
        except Exception as e:
            print(f"  [{i}] {os.path.basename(path)}: {e}")
        if (i + 1) % 10 == 0:
            json.dump(cache, open(args.out, "w"))
            print(f"  {i + 1}/{len(paths)} (saved)")
    json.dump(cache, open(args.out, "w"))
    nf = sum(len(v["faces"]) for v in cache.values())
    print(f"done: {done} images this run, {nf} faces total -> {args.out}")


if __name__ == "__main__":
    main()
