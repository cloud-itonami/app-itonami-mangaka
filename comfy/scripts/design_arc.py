#!/usr/bin/env python3
"""L0-1 物語アーク設計 — エピソードの緊張曲線 τ(t) と climax 配分を出す。各ページに
chapter 文脈(tension 0-100 / isClimax / parity / 段密度ヒント)を付与し、下位の
pagelayout/cut 設計を条件付ける。manifest の tone/subject から推定(+任意で LLM)。

τ がスケールをまたぐ carrier: 高 τ ページ → 大ゴマ/見開き/めくり、低 τ → 静かな多段。
RUN: python3 scripts/design_arc.py --out /tmp/arc.json
"""
import argparse
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
EP = os.path.join(os.path.dirname(os.path.dirname(HERE)),
                  "data/ghosthacker/resources/episodes/arc0-1-origin")

# tone/subject キーワード → tension 寄与
HOT = {"daemon": 30, "slash": 35, "attack": 30, "覚悟": 25, "battle": 30, "shock": 20,
       "罠": 18, "出現": 20, "消滅": 22, "/dev/null": 30, "覚醒": 22, "幻肢": 15,
       "罵倒": 15, "絶縁": 18, "恐怖": 20, "despair": 20, "絶望": 22}
COOL = {"calm": -15, "昼休み": -18, "warm": -12, "donut": -15, "ドーナツ": -15,
        "和解": -10, "教室": -6, "問い合わせ": -8, "待機": -10, "日常": -15}


def page_tension(panels):
    base = 35
    txt = " ".join((p.get("pageTitle", "") + " " + (p.get("sceneSubject") or "") + " "
                    + (p.get("tone") or "")) for p in panels).lower()
    for k, v in {**HOT, **COOL}.items():
        if k.lower() in txt:
            base += v
    # 印象/tone の menace 系も加点
    if any("tense" in (p.get("tone") or "").lower() or "menace" in (p.get("tone") or "").lower()
           for p in panels):
        base += 10
    return max(5, min(100, base))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=os.path.join(EP, "image-gen-manifest.json"))
    ap.add_argument("--out", default="/tmp/arc.json")
    args = ap.parse_args(argv)
    m = json.load(open(args.manifest))
    from collections import defaultdict
    by = defaultdict(list)
    for p in m["panels"]:
        by[p["pageNum"]].append(p)
    pages = sorted(by)
    tau = {pn: page_tension(by[pn]) for pn in pages}
    # climax = 局所ピーク(前後より高い)かつ閾値以上
    climax = set()
    for i, pn in enumerate(pages):
        lo = tau[pages[i - 1]] if i > 0 else 0
        hi = tau[pages[i + 1]] if i + 1 < len(pages) else 0
        if tau[pn] >= 75 and tau[pn] >= lo and tau[pn] >= hi:
            climax.add(pn)
    arc = {}
    for pn in pages:
        t = tau[pn]
        arc[pn] = {
            "tension": t,
            "isClimax": pn in climax,
            "parity": "recto" if pn % 2 == 1 else "verso",  # RTL: 奇数=右ページ(めくり前)
            "turnHook": pn % 2 == 1,                          # 右ページ下でめくりの引き
            # 段密度ヒント: 高 τ=少段・大ゴマ / 低 τ=多段・速ゴマ
            "tierHint": "splash" if t >= 85 else "sparse" if t >= 65 else
                        "dense" if t <= 35 else "normal",
        }
    json.dump({"episode": m.get("episode", ""), "tau": tau,
               "climaxPages": sorted(climax), "pages": arc},
              open(args.out, "w"), ensure_ascii=False, indent=2)
    print(f"arc τ over {len(pages)} pages. climax={sorted(climax)}")
    for pn in pages[:12]:
        a = arc[pn]
        print(f"  p{pn}: τ={a['tension']:3d} {a['tierHint']:7s} "
              f"{'CLIMAX ' if a['isClimax'] else ''}{a['parity']}")
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
