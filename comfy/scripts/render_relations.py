#!/usr/bin/env python3
"""人物相関図レンダラ — character-relations.json(nodes/edges/groups)を 1 枚の相関図に。
グループごとにクラスタ配置 → グループ外周(hull)→ ラベル付きエッジ → キャラ枠 → 凡例。
データが SSoT、これは可視化。RUN: python3 scripts/render_relations.py [--out /tmp/relations.png]
"""
import argparse
import json
import math
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
REL = os.path.join(os.path.dirname(HERE), "..", "data", "ghosthacker", "character-relations.json")
REL = os.path.normpath(REL)

_HG = "/System/Library/Fonts/Hiragino Sans GB.ttc"
_FB = ["/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc", _HG, "/System/Library/Fonts/Helvetica.ttc"]


def font(sz, bold=False):
    for p in ([_FB[0]] if bold else []) + _FB:
        try:
            return ImageFont.truetype(p, sz)
        except Exception:
            continue
    return ImageFont.load_default()


# side → カラー(キャラ枠)
SIDE_COL = {
    "protagonist": (38, 90, 168), "client": (196, 132, 28), "victim": (176, 56, 96),
    "classmate": (90, 120, 60), "family": (120, 96, 60), "ally": (54, 140, 140),
    "backstory": (110, 110, 120), "antagonist": (180, 36, 44),
    "force": (130, 70, 180), "background-ally": (40, 130, 130),
    "social-pressure": (200, 120, 40),
}
# 関係タイプ → 線色/破線
EDGE_STYLE = {
    "childhood-friend": ((40, 150, 90), False), "best-friend": ((40, 150, 90), False),
    "friend": ((60, 150, 110), False), "classmate": ((150, 150, 150), True),
    "family": ((150, 110, 50), False), "incident-victim": ((200, 50, 70), False),
    "incident-collateral": ((200, 90, 110), True), "turns-on": ((200, 60, 60), True),
    "investigates-for": ((40, 90, 180), False), "discovers": ((120, 70, 170), True),
    "attacks": ((200, 30, 40), False), "causes": ((200, 30, 40), True),
    "pursues": ((40, 90, 180), True), "peer": ((140, 140, 150), True),
    "root-cause": ((140, 20, 30), False), "manifests-to": ((130, 70, 180), True),
}
W, H = 2000, 1440


def _wrap(s, n):
    return [s[i:i + n] for i in range(0, len(s), n)] or [""]


def draw_graph(data, out):
    nodes = {n["id"]: n for n in data["nodes"]}
    groups = data.get("groups", {})

    # 各ノードの主グループ(最初に含むグループ)
    primary = {}
    for gname, g in groups.items():
        for m in g.get("members", []):
            primary.setdefault(m, gname)
    gorder = list(groups.keys())

    img = Image.new("RGB", (W, H), (250, 250, 248))
    d = ImageDraw.Draw(img)
    f_title = font(40, True); f_grp = font(22, True)
    f_name = font(26, True); f_kana = font(17); f_role = font(15); f_leg = font(17); f_edge = font(15)

    d.text((40, 26), f"人物相関図 — {data.get('work','')} / {data.get('arc','')}", font=f_title, fill=(30, 30, 36))
    inc = data.get("incident", {})
    if inc:
        d.text((44, 78), f"事件: {inc.get('name','')} — {inc.get('summary','')[:70]}…",
                font=f_role, fill=(150, 60, 70))

    # 最大グループ(主舞台=教室)を中央に広く配置、残りを外周リングに。
    cx0, cy0 = W / 2, H / 2 + 30
    gcenters, pos = {}, {}
    by_size = sorted(gorder, key=lambda g: -len(groups[g]["members"]))
    center_g, ring = by_size[0], by_size[1:]

    def place(gname, gcx, gcy, rx, ry):
        gcenters[gname] = (gcx, gcy)
        mem = [m for m in groups[gname]["members"] if primary.get(m) == gname]  # 主グループのみ配置
        k = len(mem)
        for mi, m in enumerate(mem):
            if k == 1:
                pos[m] = (gcx, gcy)
            else:
                a2 = -math.pi / 2 + 2 * math.pi * mi / k
                pos[m] = (gcx + rx * math.cos(a2), gcy + ry * math.sin(a2))

    place(center_g, cx0, cy0, 250, 175)                       # 中央クラスタ(広く)
    Rr = 660
    for gi, gname in enumerate(ring):
        ang = -math.pi / 2 + 2 * math.pi * gi / len(ring)
        gcx = cx0 + Rr * math.cos(ang) * 1.18
        gcy = cy0 + Rr * math.sin(ang) * 0.74
        place(gname, gcx, gcy, 150, 90)

    # グループ外周(hull = メンバー外接矩形を角丸で)
    for gname, g in groups.items():
        ms = [pos[m] for m in g["members"] if primary.get(m) == gname and m in pos]
        if not ms:
            continue
        xs = [p[0] for p in ms]; ys = [p[1] for p in ms]
        pad = 92
        box = [min(xs) - pad, min(ys) - pad - 10, max(xs) + pad, max(ys) + pad]
        d.rounded_rectangle(box, radius=26, outline=(205, 205, 212), width=2, fill=(244, 244, 240))
        d.text((box[0] + 12, box[1] + 6), gname, font=f_grp, fill=(120, 120, 132))

    # エッジ(ラベル付き)。先に線→後でノードを上に描く
    NW, NH = 168, 76
    for e in data["edges"]:
        a, b = e["from"], e["to"]
        if a not in pos or b not in pos:
            continue
        col, dash = EDGE_STYLE.get(e["type"], ((150, 150, 150), False))
        ax, ay = pos[a]; bx, by = pos[b]
        if dash:
            seg = 12; dist = math.hypot(bx - ax, by - ay); steps = int(dist / seg)
            for s in range(0, steps, 2):
                t1, t2 = s / steps, min(1, (s + 1) / steps)
                d.line([ax + (bx - ax) * t1, ay + (by - ay) * t1,
                        ax + (bx - ax) * t2, ay + (by - ay) * t2], fill=col, width=3)
        else:
            d.line([ax, ay, bx, by], fill=col, width=3)
        # ラベル(中点)
        mx, my = (ax + bx) / 2, (ay + by) / 2
        lab = e.get("label", e["type"])[:18]
        tw = d.textbbox((0, 0), lab, font=f_edge)[2]
        d.rounded_rectangle([mx - tw / 2 - 5, my - 12, mx + tw / 2 + 5, my + 12],
                            radius=8, fill=(255, 255, 255), outline=col, width=1)
        d.text((mx, my), lab, font=f_edge, fill=col, anchor="mm")

    # ノード枠
    for nid, (x, y) in pos.items():
        n = nodes[nid]
        col = SIDE_COL.get(n.get("side"), (90, 90, 90))
        box = [x - NW / 2, y - NH / 2, x + NW / 2, y + NH / 2]
        d.rounded_rectangle(box, radius=12, fill=(255, 255, 255), outline=col, width=3)
        d.rounded_rectangle([box[0], box[1], box[2], box[1] + 7], radius=3, fill=col)
        d.text((x, y - 22), n["name"], font=f_name, fill=(28, 28, 34), anchor="mm")
        cls = (n.get("class") or n.get("location") or n.get("status") or "")
        d.text((x, y + 4), f"{n.get('kana','')}  {cls}", font=f_kana, fill=(110, 110, 120), anchor="mm")
        d.text((x, y + 26), (n.get("role", "")[:18]), font=f_role, fill=col, anchor="mm")

    # 凡例(関係タイプ)
    lx, ly = 40, H - 150
    d.text((lx, ly - 26), "関係:", font=f_grp, fill=(80, 80, 90))
    items = [("幼馴染/親友", "childhood-friend"), ("友人", "friend"), ("家族", "family"),
             ("同級(席近)", "classmate"), ("被害(乗っ取り)", "incident-victim"),
             ("事件後に責める", "turns-on"), ("依頼で調査", "investigates-for"), ("発見", "discovers")]
    for i, (lab, t) in enumerate(items):
        col, dash = EDGE_STYLE.get(t)
        yy = ly + (i % 4) * 30; xx = lx + (i // 4) * 320
        d.line([xx, yy + 9, xx + 40, yy + 9], fill=col, width=3)
        d.text((xx + 50, yy), lab, font=f_leg, fill=(60, 60, 66))

    img.save(out)
    print(f"wrote {out}  ({len(pos)} chars, {len(data['edges'])} relations)")


# ── 層別 段組み版(過去→背景→前景)──────────────────────────────────────────
# 物語の時間/距離の層でキャラを横帯に段組み。エッジは層をまたぐ『影響の流れ』。
TIER = {  # id → (tier index 0=過去/1=背景/2=前景)
    "shinya": 0, "attackers7": 0,
    "operator": 1, "mob": 1, "shirase": 1, "daemon": 1, "nue": 1,
    "ren": 2, "yuto": 2, "nei": 2, "akira": 2, "saki": 2, "mei": 2, "kazuo": 2, "yuko": 2,
}
TIER_LABEL = {0: "過去 (7年前) — 物語の根", 1: "背景 (黒幕・社会・世界観) — 影響源", 2: "前景 (教室・家庭) — 舞台"}
TIER_ORDER = {  # 各層の左→右並び(交差を減らす)
    0: ["attackers7", "shinya"],
    1: ["mob", "operator", "daemon", "shirase", "nue"],
    2: ["yuko", "kazuo", "yuto", "akira", "saki", "mei", "ren", "nei"],
}


def draw_layered(data, out):
    nodes = {n["id"]: n for n in data["nodes"]}
    LW, LH = 1900, 1180
    img = Image.new("RGB", (LW, LH), (250, 250, 248))
    d = ImageDraw.Draw(img)
    f_title = font(38, True); f_band = font(24, True)
    f_name = font(24, True); f_kana = font(16); f_role = font(14); f_leg = font(16); f_edge = font(14)
    d.text((40, 22), f"人物相関図(層別)— {data.get('work','')} / {data.get('arc','')}", font=f_title, fill=(30, 30, 36))
    d.text((44, 66), "時間軸: 上=過去 → 下=現在。矢印=層をまたぐ影響(緑=支え/赤=加害/灰=中立)", font=f_role, fill=(110, 110, 120))

    bands = [0, 1, 2]
    top, bot = 110, LH - 120
    band_h = (bot - top) / len(bands)
    NW, NH = 176, 74
    pos = {}
    for bi, tier in enumerate(bands):
        by = top + bi * band_h
        d.rectangle([24, by, LW - 24, by + band_h - 14],
                    fill=(245, 245, 241) if bi % 2 == 0 else (240, 241, 244), outline=(220, 220, 226))
        d.text((36, by + 8), TIER_LABEL[tier], font=f_band, fill=(120, 120, 132))
        mem = [m for m in TIER_ORDER[tier] if m in nodes]
        k = len(mem)
        for mi, m in enumerate(mem):
            x = (LW) * (mi + 1) / (k + 1)
            y = by + band_h / 2 + 8
            pos[m] = (x, y)

    for e in data["edges"]:
        a, b = e["from"], e["to"]
        if a not in pos or b not in pos:
            continue
        col, dash = EDGE_STYLE.get(e["type"], ((150, 150, 150), False))
        ax, ay = pos[a]; bx, by = pos[b]
        # 始点/終点をノード枠の縁に寄せる
        if dash:
            seg = 13; dist = math.hypot(bx - ax, by - ay); steps = max(1, int(dist / seg))
            for s in range(0, steps, 2):
                d.line([ax + (bx - ax) * s / steps, ay + (by - ay) * s / steps,
                        ax + (bx - ax) * (s + 1) / steps, ay + (by - ay) * (s + 1) / steps], fill=col, width=3)
        else:
            d.line([ax, ay, bx, by], fill=col, width=3)
        mx, my = (ax + bx) / 2, (ay + by) / 2
        lab = e.get("label", e["type"])[:16]
        tw = d.textbbox((0, 0), lab, font=f_edge)[2]
        d.rectangle([mx - tw / 2 - 4, my - 11, mx + tw / 2 + 4, my + 11], fill=(255, 255, 255), outline=col)
        d.text((mx, my), lab, font=f_edge, fill=col, anchor="mm")

    for nid, (x, y) in pos.items():
        n = nodes[nid]
        col = SIDE_COL.get(n.get("side"), (90, 90, 90))
        box = [x - NW / 2, y - NH / 2, x + NW / 2, y + NH / 2]
        d.rounded_rectangle(box, radius=11, fill=(255, 255, 255), outline=col, width=3)
        d.rounded_rectangle([box[0], box[1], box[2], box[1] + 7], radius=3, fill=col)
        d.text((x, y - 20), n["name"], font=f_name, fill=(28, 28, 34), anchor="mm")
        d.text((x, y + 4), f"{n.get('kana','')}  {n.get('class') or n.get('role','')[:10]}", font=f_kana, fill=(110, 110, 120), anchor="mm")
        d.text((x, y + 24), n.get("role", "")[:16], font=f_role, fill=col, anchor="mm")
    img.save(out)
    print(f"wrote {out}  (layered, {len(pos)} chars)")


# ── tensor チャネル別ヒートマップ ─────────────────────────────────────────────
def draw_heatmap(data, out):
    tn = data.get("tensor", {})
    infl = tn.get("influence", [])
    channels = tn.get("axes", {}).get("channel", ["emotional", "plot-causal", "informational", "thematic"])
    targets = tn.get("axes", {}).get("target", ["ren", "yuto", "nei", "incident"])
    CH_JP = {"emotional": "感情", "plot-causal": "筋(因果)", "informational": "情報", "thematic": "テーマ"}
    TG_JP = {"ren": "Ren", "yuto": "Yuto", "nei": "Nei", "incident": "事件"}
    sources = [r["source"] for r in infl]
    nodes = {n["id"]: n for n in data["nodes"]}

    def sval(r, tgt, ch):
        return (r.get("on", {}).get(tgt, {}) or {}).get(ch, 0)

    cell, pad, top, left = 78, 6, 150, 240
    cols, rows = len(targets), len(sources)
    grid_w = cols * cell
    panel_w = left + grid_w + 40
    panel_h = top + rows * cell + 40
    HW = panel_w * 2 + 40
    HH = panel_h * 2 + 80
    img = Image.new("RGB", (HW, HH), (250, 250, 248))
    d = ImageDraw.Draw(img)
    f_title = font(36, True); f_panel = font(24, True)
    f_lab = font(17); f_val = font(20, True); f_src = font(15); f_note = font(14)
    d.text((34, 22), f"影響テンソル(チャネル別ヒートマップ)— {data.get('work','')}", font=f_title, fill=(30, 30, 36))
    d.text((36, 64), "行=影響源 / 列=対象(Ren/Yuto/Nei/事件)。色=符号付き強度(青=+支え / 赤=−加害、濃さ∝|値|/3)", font=f_note, fill=(110, 110, 120))

    def cellcol(v):
        if v == 0:
            return (242, 242, 240)
        t = min(1.0, abs(v) / 3.0)
        if v > 0:
            return (int(235 - 150 * t), int(240 - 70 * t), int(250 - 20 * t))     # 青
        return (int(250 - 10 * t), int(235 - 150 * t), int(235 - 150 * t))        # 赤

    for ci, ch in enumerate(channels):
        ox = 30 + (ci % 2) * (panel_w + 0)
        oy = 96 + (ci // 2) * (panel_h + 10)
        d.text((ox + left, oy + 14), f"チャネル: {CH_JP.get(ch, ch)}", font=f_panel, fill=(40, 40, 50))
        gx, gy = ox + left, oy + top
        for j, tgt in enumerate(targets):
            d.text((gx + j * cell + cell / 2, gy - 22), TG_JP.get(tgt, tgt), font=f_lab, fill=(70, 70, 80), anchor="mm")
        for i, r in enumerate(infl):
            src = r["source"]
            nm = nodes.get(src, {}).get("name", src)
            d.text((gx - 10, gy + i * cell + cell / 2), nm[:11], font=f_src, fill=(50, 50, 58), anchor="rm")
            for j, tgt in enumerate(targets):
                v = sval(r, tgt, ch)
                x0, y0 = gx + j * cell, gy + i * cell
                d.rectangle([x0 + 1, y0 + 1, x0 + cell - 1, y0 + cell - 1], fill=cellcol(v), outline=(225, 225, 230))
                if v:
                    d.text((x0 + cell / 2, y0 + cell / 2), f"{v:+d}", font=f_val,
                           fill=(20, 40, 120) if v > 0 else (140, 20, 30), anchor="mm")
    img.save(out)
    print(f"wrote {out}  (heatmap, {len(channels)} channels × {len(sources)} sources × {len(targets)} targets)")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=REL)
    ap.add_argument("--out", default="/tmp/ghosthacker-relations.png")
    ap.add_argument("--mode", default="all", choices=["graph", "layered", "heatmap", "all"])
    args = ap.parse_args(argv)
    data = json.load(open(args.inp))
    base = args.out[:-4] if args.out.endswith(".png") else args.out
    if args.mode in ("graph", "all"):
        draw_graph(data, args.out if args.mode == "graph" else base + ".png")
    if args.mode in ("layered", "all"):
        draw_layered(data, args.out if args.mode == "layered" else base + "-layered.png")
    if args.mode in ("heatmap", "all"):
        draw_heatmap(data, args.out if args.mode == "heatmap" else base + "-heatmap.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
