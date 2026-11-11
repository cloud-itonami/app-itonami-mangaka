#!/usr/bin/env python3
"""カット設計器 (絵コンテ工程の AI 化)。manifest のページ・ビートを入力に、LLM(監督役)が
各コマを『1カット』として設計する: shot(scale/angle/camPos/lens/move) + cut(intent/
decisiveMoment/duration/vfx/fgElement) + gaze(entry/focus/exit) + transition。

冨樫的ページにするため、リズム制約を明示で課す:
  - shot-scale を ELS〜ECU で振る(同スケール3連禁止、引き⇄寄りの対比)
  - 1ページに見せゴマ1〜2(duration>80 / emphasis>85)を必須・山に配置
  - transition 多様化(subject 連打禁止)
  - camPos を意図的に(煽り=power / 俯瞰=vulnerable / 横顔=対話)
  - eyeFlow 連続(cut[i].exit ≈ cut[i+1].entry)
  - dialogue/characters は manifest を保持(物語は変えずカメラだけ再設計)

RUN: python3 scripts/design_cuts.py --pages 37 --out /tmp/cuts \
        --model anthropic/claude-opus-4.8
"""
import argparse
import base64  # noqa: F401 (compat with shared helpers)
import json
import os
import re
import subprocess
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
EP = os.path.join(os.path.dirname(os.path.dirname(HERE)),
                  "data/ghosthacker/resources/episodes/arc0-1-origin")

DIRECTOR = (
    "You are a manga director storyboarding ONE page in the style of Yoshihiro Togashi "
    "(HUNTER×HUNTER) — cinematic CUT design, NOT a uniform grid. You are given the page's "
    "story beats (subject, visual, dialogue) IN READING ORDER. Redesign the CAMERA for each "
    "beat into a sequence of CUTS with strong cinematic variety and rhythm. KEEP the story and "
    "dialogue; only design the cinematography + cut rhythm.\n\n"
    "HARD RULES (Togashi komawari):\n"
    "1. Use the FULL range of shot scales across the page — include at least one extreme 引き "
    "(WS/LS, tiny figure in space) AND at least one extreme 寄り (ECU, a face/eye/mouth/detail "
    "filling frame). NEVER 3 consecutive panels at the same scale.\n"
    "2. Pick 1–2 HERO cuts (duration>=85, emphasis>=88) = the page's 見せゴマ. Place them at the "
    "emotional peak / reveal / the panel a reader hits when turning the page.\n"
    "3. Vary `transition` (moment/action/subject/scene/aspect) — do NOT use 'subject' for all.\n"
    "4. Choose `camPos` for meaning: front-low/worms-eye = power/threat, birds-eye/high = "
    "vulnerability/isolation, profile = dialogue, over-shoulder = relation, dutch = unease.\n"
    "5. Choose `lens`: wide-24/ultra-wide-14 + foreshortening for impact/action; portrait-85/"
    "tele-135 for intimacy/compression.\n"
    "6. `decisiveMoment`: name the single telling instant the cut freezes (Togashi picks the "
    "MOST expressive frame, e.g. 'the eye an instant before tears', 'the blade just after the "
    "swing').\n"
    "7. eyeFlow: set gaze entry (where eye enters from prev cut) → focus → exit (toward next); "
    "make cut[i].exit roughly meet cut[i+1].entry. Coordinates are panel-local permille 0-1000 "
    "(RTL: eye enters top-right ~ [850,150], exits bottom-left ~ [150,850]).\n"
    "8. For action/battle beats, fill `vfx` with the fantastical effects that MUST stay visible "
    "(e.g. ['energy-slash','glitch','particles']) so a realistic render won't go mundane.\n\n"
    "PAGE TITLE: {title}\nTONE: {tone}\n\nBEATS (reading order):\n{beats}\n\n"
    "Output EXACTLY {n} cuts — one cut per beat, in the SAME order, keeping each beat's "
    "dialogue with its cut (order = the beat's [index]).\n"
    "Output ONLY JSON: {{\"cuts\":[{{\"order\":int, \"beat\":str, \"intent\":one of "
    "[establish,calm,tension,impact,reveal,silence,comedic,transition], "
    "\"shot\":{{\"scale\":one of [ECU,CU,MCU,MS,MLS,LS,WS,OTS,insert,POV], "
    "\"angle\":one of [eye,low,high,birds-eye,worms-eye,dutch,OTS,POV], "
    "\"camPos\":one of [front,front-low,front-high,profile-left,profile-right,three-quarter,"
    "back,over-shoulder,birds-eye,worms-eye,dutch,pov], "
    "\"lens\":one of [ultra-wide-14,wide-24,normal-35,normal-50,portrait-85,tele-135,macro], "
    "\"move\":one of [static,push-in,pull-back,pan-left,pan-right,tilt-up,tilt-down,follow,"
    "rack-focus]}}, \"decisiveMoment\":str, \"duration\":int 0-100, \"emphasis\":int 0-100, "
    "\"vfx\":[str], \"fgElement\":str, "
    "\"transition\":one of [moment,action,subject,scene,aspect,non-sequitur], "
    "\"gaze\":{{\"entryX\":int,\"entryY\":int,\"focusX\":int,\"focusY\":int,\"exitX\":int,"
    "\"exitY\":int,\"impression\":one of [calm,tension,awe,dread,speed,impact,melancholy,"
    "comedic,ominous]}}}}]}}"
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
    txt = r["choices"][0]["message"]["content"]
    mt = re.search(r"\{.*\}", txt, re.S)
    return json.loads(mt.group(0)) if mt else {}


def beats_for(panels):
    out = []
    for p in sorted(panels, key=lambda z: z.get("panelIndex", 0)):
        dl = "; ".join(f"{d.get('speaker','')}: {d.get('text','')}"
                       for d in (p.get("dialogues") or []) if d.get("text"))
        out.append(f"[{p.get('panelIndex')}] subject={p.get('sceneSubject','')} | "
                   f"chars={','.join(p.get('characters') or [])} | "
                   f"visual={(p.get('visual') or '')[:140]} | dialogue={dl or '—'}")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", default="37")
    ap.add_argument("--model", default="anthropic/claude-opus-4.8")
    ap.add_argument("--out", default="/tmp/cuts")
    args = ap.parse_args(argv)
    key = _key()
    m = json.load(open(os.path.join(EP, "image-gen-manifest.json")))
    from collections import defaultdict
    pg = defaultdict(list)
    for p in m["panels"]:
        pg[p["pageNum"]].append(p)
    os.makedirs(args.out, exist_ok=True)
    for pn in [int(x) for x in args.pages.split(",")]:
        panels = pg.get(pn, [])
        if not panels:
            continue
        title = panels[0].get("pageTitle", "").split("[")[0].strip()
        tone = panels[0].get("tone", "")
        prompt = DIRECTOR.format(title=title, tone=tone, beats=beats_for(panels), n=len(panels))
        YORI = {"ECU", "CU", "MCU"}
        HIKI = {"MLS", "LS", "WS"}

        def _weak(cuts):
            """冨樫制約の自動監査: スケール分散不足 / 引き⇄寄り対比なし / 見せゴマ0 を弱いと判定。"""
            sc = [c.get("shot", {}).get("scale") for c in cuts]
            n = len(sc)
            need = max(3, n - 2) if n >= 4 else max(2, n - 1)
            has_contrast = any(s in YORI for s in sc) and any(s in HIKI for s in sc)
            hero = any(c.get("duration", 0) >= 85 or c.get("emphasis", 0) >= 88 for c in cuts)
            reasons = []
            if len(set(sc)) < need:
                reasons.append(f"distinct {len(set(sc))}<{need}")
            if not has_contrast:
                reasons.append("no 引き⇄寄り contrast")
            if not hero:
                reasons.append("no hero koma")
            return reasons

        res, pr = None, prompt
        for attempt in range(4):
            try:
                cand = llm(pr, args.model, key)
            except Exception as e:
                print(f"p{pn}: retry {attempt} ({str(e)[:45]})")
                continue
            if not cand.get("cuts"):
                continue
            weak = _weak(cand["cuts"])
            if not weak:
                res = cand
                break
            res = cand                                 # keep best-so-far
            pr = prompt + ("\n\nYOUR PREVIOUS ATTEMPT WAS TOO MONOTONE (" + "; ".join(weak)
                           + "). REDO with much stronger scale contrast: include an extreme 引き "
                           "(WS/LS) AND an extreme 寄り (ECU), avoid repeating scales, and make "
                           "1-2 panels true 見せゴマ (duration>=88).")
            print(f"p{pn}: variance-retry {attempt} — {weak}")
        if not res or not res.get("cuts"):
            print(f"p{pn}: FAILED")
            continue
        cuts = res.get("cuts", [])
        # 監査: scale 分散 + 見せゴマ
        scales = [c.get("shot", {}).get("scale") for c in cuts]
        heroes = [c for c in cuts if c.get("duration", 0) >= 85 or c.get("emphasis", 0) >= 88]
        json.dump(res, open(os.path.join(args.out, f"p{pn}.json"), "w"), ensure_ascii=False, indent=2)
        print(f"p{pn}: {len(cuts)} cuts | scales={scales} | hero={len(heroes)} "
              f"| distinct-scales={len(set(scales))}")
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
