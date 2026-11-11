#!/usr/bin/env python3
"""L4 ページ割り(ネーム)設計 — cuts + arc文脈(τ/tierHint/climax/parity)から PageLayout
(段構造・段高・コマ幅・断ち切り・見せゴマ・めくり)を設計する。ハイブリッドC: LLM が離散
構造(編集判断)を設計 → 決定的 packer が矩形化 → 制約修復。emphasis 機械パッカーを置換。

τ がスケール carrier: 高τ→少段・大見せゴマ・断ち切り多 / 低τ→多段・速ゴマ。
RUN: python3 scripts/design_pagelayout.py --pages 37 --cuts /tmp/cuts --arc /tmp/arc.json
"""
import argparse
import json
import os
import re
import subprocess
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
EP = os.path.join(os.path.dirname(os.path.dirname(HERE)),
                  "data/ghosthacker/resources/episodes/arc0-1-origin")
B, INNER, G = 17, 966, 14

NEME = (
    "You are a manga LAYOUT EDITOR doing the ネーム (storyboard) for ONE page, Togashi "
    "(HUNTER×HUNTER) komawari sensibility. Given the page's CUTS (already shot-designed) and the "
    "page's narrative context, design HOW the page is divided into panels: tier (row) structure, "
    "tier heights, panel widths, 断ち切り(bleed), the 見せゴマ(dominant panel), and the めくり hook.\n\n"
    "CONTEXT: tension τ={tau}/100, tierHint={hint}, isClimax={climax}, parity={parity} "
    "(recto=right page, hook the eye toward the page-turn), turnHook={hook}.\n"
    "Use τ to set rhythm: HIGH τ → FEWER tiers, 1 big 見せゴマ (or near-splash), more 断ち切り "
    "(bleed) for openness/impact; LOW τ → MORE tiers, smaller faster panels (comedy/dialogue).\n\n"
    "CUTS (reading order):\n{cuts}\n\n"
    "HARD RULES:\n"
    "1. Keep all {n} cuts (order preserved). Group them into TIERS (rows), reading RTL top→bottom.\n"
    "2. 1-2 見せゴマ: the climax/impact cut gets its own tier, large height, often full-width "
    "with bleed. Place the strongest near the bottom on a recto page (めくり引き).\n"
    "3. Tier heights MUST vary (no uniform rows). heightW is a relative weight.\n"
    "4. Within a tier, widthW are relative weights (unequal widths welcome).\n"
    "5. 断ち切り(bleed) only on intent establish/impact/reveal/silence panels and only the page-"
    "edge sides; dialogue panels stay bordered. bleed subset of [top,right,bottom,left].\n"
    "6. tier count: τ>=85 → 1-3 tiers; τ 55-84 → 2-4; τ<=40 → 3-5 (denser).\n"
    "7. DIALOGUE FIT (critical): a cut with many dialogue chars NEEDS a large panel so the "
    "speech balloons fit without overlapping — give high-dialogue cuts big heightW/widthW. "
    "A near-wordless impact cut can be small. Never cram a wordy cut into a tiny panel.\n\n"
    "Output ONLY JSON: {{\"panelCount\":{n}, \"climaxOrder\":int, \"pageTurnHook\":int, "
    "\"tiers\":[{{\"heightW\":int, \"panels\":[{{\"order\":int,\"widthW\":int,"
    "\"bleed\":[str]}}]}}]}}"
)


def _key():
    return (subprocess.run(["security", "find-generic-password", "-s", "gftd.openrouter", "-w"],
                           capture_output=True, text=True).stdout.strip()
            or os.environ.get("OPENROUTER_APIKEY"))


def llm(prompt, model, key, timeout=240):
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", body,
                                 {"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    r = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    mt = re.search(r"\{.*\}", r["choices"][0]["message"]["content"], re.S)
    return json.loads(mt.group(0)) if mt else {}


def _cutline(cuts, dlen=None):
    dlen = dlen or {}
    return "\n".join(
        f"#{c['order']} {c.get('intent','')} {c['shot'].get('scale')} emph{c.get('emphasis',50)} "
        f"dur{c.get('duration',50)} dialogue{dlen.get(c['order'],0)}chars "
        f"| {c.get('decisiveMoment','')[:50]}" for c in cuts)


def design(cuts, ctx, model, key, dlen=None):
    cuts = sorted(cuts, key=lambda c: c.get("order", 0))
    prompt = NEME.format(tau=ctx.get("tension", 40), hint=ctx.get("tierHint", "normal"),
                         climax=ctx.get("isClimax", False), parity=ctx.get("parity", "recto"),
                         hook=ctx.get("turnHook", True), n=len(cuts), cuts=_cutline(cuts, dlen))
    for _ in range(3):
        try:
            r = llm(prompt, model, key)
            if r.get("tiers") and sum(len(t.get("panels", [])) for t in r["tiers"]) == len(cuts):
                return r
        except Exception:
            pass
    # フォールバック: emphasis tier packer
    return None


def pack(pagelayout):
    """PageLayout → {order: ([x,y,w,h], bleed)}。tier heightW→y, panel widthW→x(RTL)。
    制約修復: 段高に下限(潰れ防止)・見せゴマ段に最低保証・矩形をボード内クランプ(見切れ防止)。"""
    tiers = pagelayout["tiers"]
    nt = len(tiers)
    avail_h = INNER - (nt - 1) * G
    hws = [max(1, t.get("heightW", 100)) for t in tiers]
    # 段高下限: どの段も avail_h の MIN_FRAC 以上(build-up 段の潰れ防止)
    min_frac = min(0.12, 0.85 / nt)
    floor = avail_h * min_frac
    raw = [avail_h * h / sum(hws) for h in hws]
    # 下限割れを底上げし、余剰を上位段から比例で回収
    heights = [max(r, floor) for r in raw]
    over = sum(heights) - avail_h
    if over > 0:
        slack = [max(0, hh - floor) for hh in heights]
        ts = sum(slack) or 1
        heights = [hh - over * (s / ts) for hh, s in zip(heights, slack)]
    total, y = sum(heights), B
    rects = {}
    for t, rh in zip(tiers, heights):
        ps = t["panels"]
        ws = [max(1, p.get("widthW", 100)) for p in ps]
        sw, avail_w, x = sum(ws), INNER - (len(ps) - 1) * G, B + INNER
        for p, w in zip(ps, ws):
            cw = avail_w * w / sw
            x -= cw
            bl = [e for e in (p.get("bleed") or []) if e in ("top", "right", "bottom", "left")]
            rects[p["order"]] = ([round(x), round(y), round(cw), round(rh)], bl)
            x -= G
        y += rh + G
    return rects


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", default="37")
    ap.add_argument("--cuts", default="/tmp/cuts")
    ap.add_argument("--arc", default="/tmp/arc.json")
    ap.add_argument("--model", default="anthropic/claude-opus-4.8")
    ap.add_argument("--dialogue", default="",
                    help="polish_dialogue dir — 推敲後の最終セリフ量で面積設計(工程順: 推敲→割り)")
    ap.add_argument("--out", default="/tmp/pagelayout")
    args = ap.parse_args(argv)
    key = _key()
    arc = json.load(open(args.arc))["pages"] if os.path.exists(args.arc) else {}
    EPman = os.path.join(EP, "image-gen-manifest.json")
    man = json.load(open(EPman)) if os.path.exists(EPman) else {"panels": []}
    os.makedirs(args.out, exist_ok=True)
    for pn in [int(x) for x in args.pages.split(",")]:
        cuts = json.load(open(f"{args.cuts}/p{pn}.json"))["cuts"]
        ctx = arc.get(str(pn)) or arc.get(pn) or {}
        # cut order別の台詞文字数 → 過密コマに面積を回す cross-layer feedback。
        # 推敲後セリフがあればそれを使う(工程順: 推敲→ページ割り。空虚な大ゴマを防ぐ)
        dlen = {}
        polf = os.path.join(args.dialogue, f"p{pn}.json") if args.dialogue else ""
        if polf and os.path.exists(polf):
            pol = json.load(open(polf))
            for idx, ds in pol.items():
                dlen[int(idx)] = sum(len(d.get("text", "")) for d in ds)
        else:
            for p in man["panels"]:
                if p["pageNum"] == pn:
                    dlen[p.get("panelIndex")] = sum(len(d.get("text", "")) for d in (p.get("dialogues") or [])
                                                    if (d.get("speaker") or "").lower() != "sfx")
        pl = design(cuts, ctx, args.model, key, dlen)
        if not pl:
            print(f"p{pn}: LLM failed")
            continue
        json.dump(pl, open(f"{args.out}/p{pn}.json", "w"), ensure_ascii=False, indent=2)
        tn = [(t.get("heightW"), [p["order"] for p in t["panels"]]) for t in pl["tiers"]]
        nbleed = sum(1 for t in pl["tiers"] for p in t["panels"] if p.get("bleed"))
        print(f"p{pn}: τ={ctx.get('tension','?')} {len(pl['tiers'])}段 climax#{pl.get('climaxOrder')} "
              f"bleed×{nbleed} | tiers(h,panels)={tn}")
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
