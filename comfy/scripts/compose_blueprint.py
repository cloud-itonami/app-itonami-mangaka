#!/usr/bin/env python3
"""シーンごとの構図を再設計する — パネルのメタ(shot / gaze / 人数 / establishing)と
ARIA コマ割りで決まった実アスペクト比から、ControlNet-depth 用の深度マップ(構図設計図)
を生成する。canny で旧スケッチの線をなぞるのをやめ、深度で『人物と地面をどこに置くか』
だけを指定して、モデルには自由に描かせる(= 構図は設計、線は再生成)。

深度規約: 近 = 明(255) / 遠 = 暗(0)。人物前景=明、空=暗、地面=中間グラデ。
構図規約(映画的):
  ECU/CU = 顔を上1/3、ヘッドルーム確保 / MS = 上半身を中央〜三分割線
  LS/WS/establishing = 小さい人物を下1/3、地平線を上1/3、環境主体
  gaze lead room = 視線の先に余白(左視線→人物を右寄せ)
  2人 = 左右に対面配置 / OTS = 手前肩(大・近)+ 対面人物(中)

RUN: python3 scripts/compose_blueprint.py --storyboard <sb.json> --out /tmp/bp [--pages 6]
"""
import argparse
import json
import os

from PIL import Image, ImageDraw, ImageFilter

# shot 文字列 → (figure_scale 0-1=頭が画面高に占める比, head_cy 0-1=頭中心の縦位置, kind)
SHOT_COMP = {
    "ECU":  (0.62, 0.42, "face"),
    "CU":   (0.40, 0.34, "bust"),
    "MCU":  (0.30, 0.30, "bust"),
    "MS":   (0.22, 0.26, "torso"),
    "MLS":  (0.16, 0.30, "figure"),
    "LS":   (0.11, 0.40, "env"),
    "WS":   (0.08, 0.44, "env"),
    "OTS":  (0.34, 0.32, "ots"),
    "insert": (0.20, 0.40, "torso"),
    "POV":  (0.10, 0.42, "env"),
}


def _shot_key(shot: str) -> str:
    s = (shot or "").strip()
    if s.upper() in SHOT_COMP:                 # 既に短縮コード(WS/CU/ECU…)
        return s.upper()
    s = s.lower()
    if "extreme close" in s or "ecu" in s:
        return "ECU"
    if ("over" in s and "shoulder" in s) or "ots" in s:
        return "OTS"
    if "close" in s or "bust" in s:
        return "CU"
    if "medium long" in s or "mls" in s:
        return "MLS"
    if "wide" in s or "establish" in s or "long shot" in s or " ls" in s:
        return "WS"
    if "medium" in s:
        return "MS"
    if "insert" in s:
        return "insert"
    if "pov" in s:
        return "POV"
    return "MS"


def _gen_dims(aspect: float, area=1024 * 1024):
    """アスペクト比を保ったまま ~1MP の SDXL 寸法(8の倍数)を返す。"""
    h = (area / aspect) ** 0.5
    w = aspect * h
    W = max(640, min(1536, int(round(w / 8) * 8)))
    H = max(640, min(1536, int(round(h / 8) * 8)))
    return W, H


def _figure(d, cx, cy_head, head_r, body_bottom, val=235):
    """頭(縦長楕円)+首+なで肩+テーパ胴 の人体プロポーションを深度値 val で。
    肩幅≒頭幅の1.6倍(人間比)。前景=明、僅かに胴を暗くして自然な深度差を作る。"""
    hw = head_r * 0.82                                  # 頭は縦長(顔)
    d.ellipse([cx - hw, cy_head - head_r, cx + hw, cy_head + head_r], fill=val)
    neck_w = hw * 0.42
    sh_y = cy_head + head_r * 0.82
    sh_w = hw * 1.62                                    # なで肩(過広にしない)
    waist_w = sh_w * 0.78
    d.polygon([(cx - neck_w, cy_head + head_r * 0.55), (cx + neck_w, cy_head + head_r * 0.55),
               (cx + sh_w, sh_y), (cx + waist_w, body_bottom),
               (cx - waist_w, body_bottom), (cx - sh_w, sh_y)],
              fill=int(val * 0.92))
    d.ellipse([cx - sh_w * 0.5, sh_y - head_r * 0.3,    # 胸元を少し近く(明)
               cx + sh_w * 0.5, sh_y + head_r * 0.9], fill=val)


def blueprint(W, H, shot, gaze_dir="front", n_chars=1, establishing=False):
    """構図設計図(深度マップ, L)を返す。"""
    key = _shot_key(shot)
    scale, head_cy, kind = SHOT_COMP[key]
    img = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(img)
    # 背景: 上(空=遠=暗) → 下(地面=近=中間)の縦グラデ + 地平線
    horizon = int(H * (0.34 if kind in ("env", "figure") else 0.5))
    for y in range(H):
        if y < horizon:
            v = int(18 + 14 * y / max(1, horizon))            # 空: 18-32
        else:
            v = int(70 + 70 * (y - horizon) / max(1, H - horizon))  # 地面: 70-140
        d.line([(0, y), (W, y)], fill=v)
    # 人物配置: gaze lead room(視線の先に余白)で三分割線へ
    third = {"left": 0.66, "right": 0.34, "front": 0.5}.get(gaze_dir, 0.5)
    head_r = max(8, int(scale * H / 2))
    if kind == "env":                                          # 環境主体: 小さい人物を下1/3に点景
        for k in range(max(1, n_chars)):
            cx = int(W * (0.4 + 0.2 * k))
            _figure(d, cx, int(H * 0.62), max(6, head_r), int(H * 0.92), val=210)
    elif n_chars >= 2:                                         # 2人: 左右対面
        _figure(d, int(W * 0.30), int(H * head_cy), head_r, int(H * 0.98))
        _figure(d, int(W * 0.70), int(H * head_cy), head_r, int(H * 0.98))
    elif kind == "ots":                                        # OTS: 手前肩(大)+対面(中)
        _figure(d, int(W * 0.78), int(H * 0.55), int(head_r * 1.5), H, val=255)
        _figure(d, int(W * 0.36), int(H * head_cy), int(head_r * 0.8), int(H * 0.9), val=205)
    else:                                                      # 単独: lead room 三分割
        cx = int(W * third)
        _figure(d, cx, int(H * head_cy), head_r, int(H * 1.02))
    img = img.filter(ImageFilter.GaussianBlur(max(2, W // 200)))  # 深度を滑らかに
    return img


def _gaze_dir(panel):
    g = panel.get("gaze") or {}
    fx = g.get("focusX")
    if isinstance(fx, (int, float)):
        return "left" if fx < 440 else ("right" if fx > 560 else "front")
    faces = panel.get("faces") or []
    for f in faces:
        if len(f) > 4 and f[4] in ("left", "right"):
            return f[4]
    return "front"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--storyboard", required=True)
    ap.add_argument("--manifest", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--pages", default="")
    args = ap.parse_args(argv)
    doc = json.load(open(args.storyboard))
    os.makedirs(args.out, exist_ok=True)
    want = {int(x) for x in args.pages.split(",")} if args.pages else None
    meta = []
    for pg in doc["pages"]:
        pn = pg["pageNum"]
        if want and pn not in want:
            continue
        for p in pg["panels"]:
            w, h = p.get("w", 500), p.get("h", 500)
            aspect = (w / 1000 * 182) / (h / 1000 * 257)       # board permille → A4 比
            W, H = _gen_dims(max(0.45, min(2.4, aspect)))
            shot = (p.get("shot") or {}).get("scale") or p.get("_shot") or "medium"
            faces = p.get("faces") or []
            bp = blueprint(W, H, shot, _gaze_dir(p), max(1, len(faces) or 1),
                           establishing=(w >= 930))
            fn = f"p{pn}-panel{p['order']}-depth.png"
            bp.save(os.path.join(args.out, fn))
            meta.append({"page": pn, "order": p["order"], "W": W, "H": H,
                         "shot": shot, "file": fn})
    json.dump(meta, open(os.path.join(args.out, "blueprints.json"), "w"),
              ensure_ascii=False, indent=2)
    print(f"wrote {len(meta)} depth blueprints -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
