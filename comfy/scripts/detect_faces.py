#!/usr/bin/env python3
"""アニメ顔検出 — storyboard の各パネル画像(_imagePath)から顔を検出し、
画像ピクセル座標でキャッシュ(faces-cache.json)に書き出す。

cv2 + lbpcascade_animeface(nagadomi)で SDXL 生成のアニメ顔を検出する。
RUN: /tmp/cvenv/bin/python scripts/detect_faces.py \
        --storyboard <storyboard.komawari.page.json> \
        --cascade /tmp/lbpcascade_animeface.xml --out scripts/faces-cache.json
顔位置は次工程(build_canonical_storyboard)で COVER 変換しパネル局所 permille に
正規化され、吹き出し尻尾/視線の配置設計に使われる。
"""
import argparse
import json
import os

import cv2


def detect(path, cascade):
    img = cv2.imread(path)
    if img is None:
        return None
    h, w = img.shape[:2]
    gray = cv2.equalizeHist(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4,
                                     minSize=(int(min(w, h) * 0.06),) * 2)
    return {"size": [w, h], "faces": [[int(x), int(y), int(fw), int(fh)]
                                      for (x, y, fw, fh) in faces]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--storyboard", required=True)
    ap.add_argument("--cascade", default="/tmp/lbpcascade_animeface.xml")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    cascade = cv2.CascadeClassifier(args.cascade)
    if cascade.empty():
        raise SystemExit(f"failed to load cascade: {args.cascade}")

    doc = json.load(open(args.storyboard))
    paths = {p["_imagePath"] for pg in doc["pages"] for p in pg["panels"]
             if p.get("_imagePath")}
    cache, nfaces = {}, 0
    for i, path in enumerate(sorted(paths)):
        if not os.path.exists(path):
            continue
        r = detect(path, cascade)
        if r is not None:
            cache[path] = r
            nfaces += len(r["faces"])
    json.dump(cache, open(args.out, "w"))
    print(f"{len(cache)} images, {nfaces} faces -> {args.out}")


if __name__ == "__main__":
    main()
