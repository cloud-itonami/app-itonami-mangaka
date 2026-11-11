#!/usr/bin/env python3
"""セリフ仕上げ — 説明口調(ナレーション的に状況を語る台詞)を、自然な漫画のセリフへ
書き換える。show-don't-tell、口語、思考は短い心の声(モノローグ)。1吹き出しが短くなる
ように各行 ≤ ~14字、長い独白は短い複数ビートへ分割。

例: 「沼野くん今日も寝てた、隣のクラスの白瀬さんが起こしに来る、授業は聞いてないのに
     テストはいつも上位にいる、変な奴だ」
  → [(yuto, "また寝てる…", thought), (yuto, "変なやつ", thought)]

RUN: python3 scripts/polish_dialogue.py --pages 1 --out /tmp/dialogue
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

POLISH = (
    "You are a manga dialogue editor. Rewrite this page's dialogue into NATURAL manga speech. "
    "Each entry has a panel, speaker, and current (often clumsy/expository) line.\n\n"
    "HARD RULES:\n"
    "1. AGGRESSIVELY CUT. Max 2 (rarely 3) bubbles per panel. Drop ALL expository facts — never "
    "list relationships, test scores, or explain the setup. Keep ONLY the emotional core.\n"
    "   e.g. '沼野くん今日も寝てた、隣のクラスの白瀬さんが起こしに来る、授業は聞いてないのに"
    "テストはいつも上位、変な奴だ' → just [thought '…また寝てる', thought '変なやつ'].\n"
    "2. Show, don't tell. Cut anything that sounds like a narrator describing facts.\n"
    "3. Casual spoken Japanese (口語). Thoughts → SHORT inner monologue (心の声), kind=thought.\n"
    "4. Each bubble SHORT: <=12 Japanese characters. Terse beats.\n"
    "5. A wordless panel is fine (omit dialogue entirely).\n"
    "6. kind: 'speech' / 'thought' (心の声) / 'shout' (叫び).\n\n"
    "PANELS:\n{panels}\n\n"
    "Output ONLY JSON: {{\"panels\":[{{\"panel\":int, \"dialogues\":[{{\"speaker\":str,"
    "\"text\":str,\"kind\":str}}]}}]}}"
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


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", default="1")
    ap.add_argument("--model", default="anthropic/claude-opus-4.8")
    ap.add_argument("--out", default="/tmp/dialogue")
    args = ap.parse_args(argv)
    key = _key()
    m = json.load(open(os.path.join(EP, "image-gen-manifest.json")))
    from collections import defaultdict
    by = defaultdict(list)
    for p in m["panels"]:
        by[p["pageNum"]].append(p)
    os.makedirs(args.out, exist_ok=True)
    for pn in [int(x) for x in args.pages.split(",")]:
        lines = []
        for p in sorted(by[pn], key=lambda z: z.get("panelIndex", 0)):
            for d in (p.get("dialogues") or []):
                sp = d.get("speaker", "")
                if sp.lower() == "sfx" or not d.get("text"):
                    continue
                lines.append(f"[panel{p.get('panelIndex')}] {sp}: {d['text']}")
        if not lines:
            continue
        try:
            r = llm(POLISH.format(panels="\n".join(lines)), args.model, key)
        except Exception as e:
            print(f"p{pn}: ERR {str(e)[:60]}")
            continue
        # order(panelIndex) → dialogues
        out = {}
        for pe in r.get("panels", []):
            out[pe["panel"]] = pe.get("dialogues", [])
        json.dump(out, open(f"{args.out}/p{pn}.json", "w"), ensure_ascii=False, indent=2)
        nb = sum(len(v) for v in out.values())
        print(f"p{pn}: polished → {nb} bubbles over {len(out)} panels")
        for pidx, ds in sorted(out.items())[:4]:
            for d in ds:
                print(f"   #{pidx} {d.get('speaker'):5s} [{d.get('kind','speech')}] {d.get('text')}")
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
