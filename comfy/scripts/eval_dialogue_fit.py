#!/usr/bin/env python3
"""評価ノード(LangGraph 的) — セリフ⇔パネル整合性スコア。各吹き出しの内容が、その
パネルのシーン/画面内キャラ(inFrame)に意味的に合っているかを採点し、不整合を flag
する。例: 「また寝てる/変なやつ」(Ren を見る独白)が、Ren のいないスニーカーのコマに
置かれている → 低スコア → 別パネルへ再帰属を提案。

LangGraph node 形:  state(page) -> state(+ fit scores + flags + suggestions)
  グラフ:  compose → [eval_dialogue_fit] → (低スコア) → reassign/replace → re-compose
                                         → (高スコア) → done

RUN: python3 scripts/eval_dialogue_fit.py --page 1 --pagejson /tmp/neme4-pages/p1-cut.page.json
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

RUBRIC = (
    "You are a manga script continuity checker. For each PANEL you get its scene + the "
    "characters visible in it, and the dialogue/thought bubbles currently placed in it. Score "
    "whether EACH bubble belongs in THAT panel.\n"
    "A bubble is a MISMATCH (low score) if it refers to a character/action NOT present in the "
    "panel — e.g. an inner thought about 'Ren sleeping' placed in a panel that shows a sneaker "
    "reveal with other characters and no Ren.\n\n"
    "PAGE PANELS:\n{panels}\n\n"
    "Output ONLY JSON: {{\"panels\":[{{\"order\":int, \"bubbles\":[{{\"text\":str, "
    "\"fit\":<0-10 int, 10=clearly belongs here, 0=belongs to a different panel>, "
    "\"belongsTo\":<int order of the panel it SHOULD be in, or same order if fine>, "
    "\"why\":\"<=10 words\"}}]}}]}}"
)


def _key():
    return (subprocess.run(["security", "find-generic-password", "-s", "gftd.openrouter", "-w"],
                           capture_output=True, text=True).stdout.strip()
            or os.environ.get("OPENROUTER_APIKEY"))


def llm(prompt, model, key, timeout=180):
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", body,
                                 {"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    r = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    mt = re.search(r"\{.*\}", r["choices"][0]["message"]["content"], re.S)
    return json.loads(mt.group(0)) if mt else {}


def eval_node(page, mpanels, model, key):
    """LangGraph node: page state -> {scores, flags, suggestions}。純関数。"""
    lines = []
    for p in sorted(page["panels"], key=lambda z: z["order"]):
        o = p["order"]
        mp = mpanels.get(o, {})
        inframe = mp.get("_inFrame") or [c for c in (mp.get("characters") or [])]
        scene = mp.get("sceneSubject", "") or (p.get("shot", {}).get("scale", ""))
        bubs = [b.get("text", "") for b in p.get("bubbles", [])
                if b.get("shape") not in ("rect",) and b.get("text")]
        if not bubs:
            continue
        lines.append(f"[panel{o}] scene='{scene}' inFrame={inframe} bubbles={bubs}")
    if not lines:
        return {"flags": [], "rows": []}
    res = llm(RUBRIC.format(panels="\n".join(lines)), model, key)
    flags, rows = [], []
    for pe in res.get("panels", []):
        o = pe.get("order")
        for b in pe.get("bubbles", []):
            rows.append({"panel": o, "text": b.get("text"), "fit": b.get("fit", 10),
                         "belongsTo": b.get("belongsTo", o), "why": b.get("why", "")})
            if b.get("fit", 10) <= 4 and b.get("belongsTo") not in (None, o):
                flags.append({"text": b.get("text"), "from": o, "to": b.get("belongsTo"),
                              "why": b.get("why", "")})
    return {"flags": flags, "rows": rows}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--pagejson", required=True)
    ap.add_argument("--model", default="anthropic/claude-opus-4.8")
    ap.add_argument("--out", default="/tmp/dialogue-fit.json")
    args = ap.parse_args(argv)
    key = _key()
    doc = json.load(open(args.pagejson))
    page = next(p for p in doc["pages"] if p["pageNum"] == args.page)
    m = json.load(open(os.path.join(EP, "image-gen-manifest.json")))
    mpanels = {p.get("panelIndex"): p for p in m["panels"] if p["pageNum"] == args.page}
    r = eval_node(page, mpanels, args.model, key)
    json.dump(r, open(args.out, "w"), ensure_ascii=False, indent=2)
    print(f"=== dialogue-fit eval p{args.page} ===")
    for row in r["rows"]:
        mark = "  ⚠ MISMATCH" if row["fit"] <= 4 else ""
        print(f"  panel{row['panel']} fit{row['fit']:2d} 「{row['text']}」 "
              f"{'→ belongs #'+str(row['belongsTo']) if row['belongsTo']!=row['panel'] else ''}"
              f"{mark}  {row['why']}")
    if r["flags"]:
        print("\n--- FLAGS (再帰属提案) ---")
        for f in r["flags"]:
            print(f"  「{f['text']}」 #{f['from']} → #{f['to']}  ({f['why']})")
    else:
        print("  all bubbles fit ✓")
    print(f"\n-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
