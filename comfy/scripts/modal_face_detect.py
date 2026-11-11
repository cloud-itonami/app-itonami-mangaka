#!/usr/bin/env python3
"""アニメ顔検出を Modal の GPU 上で並列実行 (ローカル ollama 直列の高速化版)。

gemma-3-4b-it (ローカル ollama gemma3:4b と同等品質, gated) を Modal A10G コンテナに
fan-out し、各パネル画像から顔 bbox + 顔向き(dir) を取る。出力は detect_faces_gemma
と同形式 faces-cache.json: {imagePath: {size:[w,h], faces:[[x,y,w,h px, dir]]}}。

RUN (venv に modal 入り):
  MODAL_PROFILE=jun784 /tmp/modalenv/bin/modal run scripts/modal_face_detect.py \
      --storyboard data/.../storyboard.komawari.page.json \
      --out scripts/faces-cache.modal.json [--limit N]

データは Modal クラウド GPU に送られる (ローカル限定ではない)。
"""
import base64
import io
import json
import os
import re

import modal

# アニメ顔に特化して学習済みの専用検出器 (deepghs anime_face_detection, YOLOv8)。
# VLM(gemma/qwen)と違い背景/物体を顔と誤認しない。顔向きは検出した目の数/位置から導出。
app = modal.App("mangaka-face-detect")
hf_cache = modal.Volume.from_name("mangaka-imgutils-cache", create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("libgl1", "libglib2.0-0")
    .pip_install("dghs-imgutils", "onnxruntime", "opencv-python-headless", "pillow")
    .env({"HF_HOME": "/cache/hf"})
)


@app.cls(image=image, volumes={"/cache/hf": hf_cache},
         cpu=2.0, timeout=1800, scaledown_window=180, max_containers=12)
class Detector:
    @modal.enter()
    def load(self):
        from imgutils.detect import detect_eyes, detect_faces
        from PIL import Image as _I
        self._df, self._de = detect_faces, detect_eyes
        warm = _I.new("RGB", (64, 64))
        self._df(warm)                                # ONNX モデルを取得・warm
        self._de(warm)
        hf_cache.commit()

    @modal.method()
    def detect(self, img_b64: str) -> str:
        from PIL import Image
        im = Image.open(io.BytesIO(base64.b64decode(img_b64))).convert("RGB")
        w, h = im.size
        faces = self._df(im, conf_threshold=0.25, iou_threshold=0.7)
        out = []
        for (x0, y0, x1, y1), _label, _score in faces:
            fw = max(1, x1 - x0)
            d = "front"
            try:                                       # 顔向き: 目の数/位置から推定
                eyes = self._de(im.crop((x0, y0, x1, y1)), conf_threshold=0.3)
                if len(eyes) == 1:                     # 片目=横顔 → 目のある側へ向く
                    (ex0, _, ex1, _), _, _ = eyes[0]
                    d = "left" if ((ex0 + ex1) / 2) / fw < 0.5 else "right"
            except Exception:
                pass
            out.append({"x": round(x0 / w * 1000), "y": round(y0 / h * 1000),
                        "w": round((x1 - x0) / w * 1000), "h": round((y1 - y0) / h * 1000),
                        "dir": d})
        return json.dumps({"faces": out})


def _to_px(resp: str, w: int, h: int):
    """モデル応答(permille想定)→ 元画像px [x,y,fw,fh,dir]。pixel座標で来た場合も吸収。"""
    faces = []
    m = re.search(r"\{.*\}", resp, re.S)
    if m:
        try:
            faces = json.loads(m.group(0)).get("faces", [])
        except Exception:
            faces = []
    if not faces:
        a = re.search(r"\[.*\]", resp, re.S)
        if a:
            try:
                faces = json.loads(a.group(0))
            except Exception:
                faces = []
    # 全 face の最大座標で permille / pixel を判定 (gemma が px を返す場合の吸収)
    raw = []
    for f in faces:
        try:
            raw.append((float(f["x"]), float(f["y"]), float(f["w"]), float(f["h"]),
                        f.get("dir", "front")))
        except Exception:
            continue
    if not raw:
        return []
    span = max(max(x + fw, y + fh) for x, y, fw, fh, _ in raw)
    denom = 1000.0 if span <= 1010 else float(max(w, h))   # permille か px か
    out, seen = [], set()
    for x, y, fw, fh, d in raw:
        # 画像外/退化ボックス(phantom 列)を除去: 原点が画像内、右下が画像内(少しの溢れ可)
        if x < -5 or y < -5 or x + fw > denom * 1.02 or y + fh > denom * 1.02:
            continue
        px, py = x / denom * w, y / denom * h
        pw, ph = fw / denom * w, fh / denom * h
        if pw < 8 or ph < 8 or pw > w * 0.99 or ph > h * 0.99:   # 極小/全画面ボックス除去
            continue
        key = (round(px / 20), round(py / 20), round(pw / 20))   # 近接重複の dedup
        if key in seen:
            continue
        seen.add(key)
        out.append([int(max(0, px)), int(max(0, py)), int(pw), int(ph),
                    d if d in ("front", "left", "right") else "front"])
    return out


@app.local_entrypoint()
def main(storyboard: str, out: str, limit: int = 0):
    from PIL import Image
    doc = json.load(open(storyboard))
    paths = sorted({p["_imagePath"] for pg in doc["pages"] for p in pg["panels"]
                    if p.get("_imagePath") and os.path.exists(p["_imagePath"])})
    if limit:
        paths = paths[:limit]
    sizes, payloads = [], []
    for p in paths:
        im = Image.open(p).convert("RGB")
        w, h = im.size
        sizes.append((w, h))
        # 帯域とトークン削減のためローカルで長辺1024へ縮小→JPEG (permilleは尺度不変)
        s = 1024 / max(w, h) if max(w, h) > 1024 else 1.0
        rim = im.resize((max(1, int(w * s)), max(1, int(h * s)))) if s < 1 else im
        buf = io.BytesIO()
        rim.save(buf, "JPEG", quality=88)
        payloads.append(base64.b64encode(buf.getvalue()).decode())
    print(f"detecting {len(paths)} panels on Modal (anime YOLOv8 face detector)…")
    cache, nf = {}, 0
    det = Detector()
    for (path, (w, h)), resp in zip(zip(paths, sizes), det.detect.map(payloads)):
        faces = _to_px(resp, w, h)
        cache[path] = {"size": [w, h], "faces": faces}
        nf += len(faces)
    json.dump(cache, open(out, "w"))
    print(f"done: {len(cache)} images, {nf} faces -> {out}")
