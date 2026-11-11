#!/usr/bin/env python3
"""Generate HTML for 25-pair side-by-side spot check.

Two modes:
  --mode sk-vs-ww     : v11sk (Shokugeki) vs v11ww (Witch Watch), same page
  --mode sk-tournament : random pairs from v11sk (Elo-style ranking)

Output: /tmp/spot-check.html
Open in browser, vote on each pair. Click EXPORT to download JSON results.
"""
from __future__ import annotations
import argparse, json, random
from pathlib import Path

TMPL_PRELUDE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Manga Spot Check</title>
<style>
  body{background:#0a0a0a;color:#eee;font-family:sans-serif;margin:0;padding:14px}
  h1{margin:0 0 8px 0}
  .progress{color:#9c9;margin-bottom:8px}
  .row{display:flex;gap:10px;align-items:flex-start}
  .col{flex:1;background:#1a1a1a;border-radius:6px;padding:8px;cursor:pointer;
       border:2px solid transparent;transition:border-color 0.1s}
  .col:hover{border-color:#4af}
  .col.picked{border-color:#7f9}
  .col img{width:100%;display:block;border-radius:4px}
  .label{padding:6px 8px;font-size:12px;color:#999}
  .actions{display:flex;gap:8px;margin-top:10px}
  .btn{background:#333;color:#eee;border:0;padding:8px 16px;
       border-radius:4px;cursor:pointer;font-size:13px}
  .btn:hover{background:#555}
  .btn.skip{background:#552}
  .btn.tie{background:#225}
  .btn.export{background:#272;font-weight:bold}
  .hint{color:#666;font-size:11px;margin-top:4px}
</style></head><body>
<h1>Manga Spot Check <span class="progress" id="prog">0 / __TOTAL__</span></h1>
<div class="hint">Press <b>A</b> = left wins · <b>D</b> = right wins · <b>S</b> = tie · <b>X</b> = skip</div>
<div class="row">
  <div class="col" id="left"><img id="leftImg" src=""><div class="label" id="leftLabel"></div></div>
  <div class="col" id="right"><img id="rightImg" src=""><div class="label" id="rightLabel"></div></div>
</div>
<div class="actions">
  <button class="btn" onclick="vote('left')">⬅ Left wins (A)</button>
  <button class="btn tie" onclick="vote('tie')">⚖ Tie (S)</button>
  <button class="btn" onclick="vote('right')">Right wins ➡ (D)</button>
  <button class="btn skip" onclick="vote('skip')">Skip (X)</button>
  <button class="btn export" onclick="exportResults()">Export results JSON</button>
</div>
<script>
const PAIRS = __PAIRS__;
const MODE = "__MODE__";
let idx = 0;
let results = JSON.parse(localStorage.getItem("spot_check_" + MODE) || "[]");
if (results.length >= PAIRS.length) {
  // reset if already complete
  results = [];
}
idx = results.length;
function render() {
  if (idx >= PAIRS.length) {
    document.body.innerHTML = '<h1>Done! ' + results.length + ' votes recorded.</h1>' +
      '<button class="btn export" onclick="exportResults()">Download JSON</button>';
    return;
  }
  const p = PAIRS[idx];
  document.getElementById("leftImg").src = "file://" + p.left.path;
  document.getElementById("rightImg").src = "file://" + p.right.path;
  document.getElementById("leftLabel").textContent = p.left.label;
  document.getElementById("rightLabel").textContent = p.right.label;
  document.getElementById("prog").textContent = (idx) + " / " + PAIRS.length;
}
function vote(choice) {
  const p = PAIRS[idx];
  results.push({pair_idx: idx, left: p.left.id, right: p.right.id, vote: choice});
  localStorage.setItem("spot_check_" + MODE, JSON.stringify(results));
  idx++;
  render();
}
function exportResults() {
  const blob = new Blob([JSON.stringify(results, null, 2)], {type: "application/json"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "spot-check-" + MODE + "-" + Date.now() + ".json";
  a.click();
}
window.addEventListener("keydown", e => {
  if (e.key === "a" || e.key === "A") vote("left");
  else if (e.key === "d" || e.key === "D") vote("right");
  else if (e.key === "s" || e.key === "S") vote("tie");
  else if (e.key === "x" || e.key === "X") vote("skip");
});
render();
</script></body></html>"""


def build_pairs(mode: str, n: int = 25) -> list[dict]:
    pairs = []
    if mode == "sk-vs-ww":
        # Same page, sk vs ww — both in /tmp (v11full prefix = Witch Watch)
        sk_pages = sorted(set(int(p.name.split("v11sk-p")[-1].split("-")[0])
                                for p in Path("/tmp").glob("v11sk-p*-scored.png")))
        ww_pages = sorted(set(int(p.name.split("v11full-p")[-1].split("-")[0])
                                for p in Path("/tmp").glob("v11full-p*-scored.png")))
        common = sorted(set(sk_pages) & set(ww_pages))
        random.shuffle(common)
        for pg in common[:n]:
            sk = {"id": f"sk-p{pg:02d}", "path": f"/tmp/v11sk-p{pg:02d}-scored.png",
                  "label": "[hidden]"}
            ww = {"id": f"ww-p{pg:02d}", "path": f"/tmp/v11full-p{pg:02d}-scored.png",
                  "label": "[hidden]"}
            if random.random() < 0.5:
                pairs.append({"left": sk, "right": ww, "page": pg})
            else:
                pairs.append({"left": ww, "right": sk, "page": pg})
    elif mode == "sk-tournament":
        sk_pages = sorted(set(int(p.name.split("v11sk-p")[-1].split("-")[0])
                                for p in Path("/tmp").glob("v11sk-p*-scored.png")))
        # Random pairings (no page vs itself)
        all_pairs = [(a, b) for a in sk_pages for b in sk_pages if a < b]
        random.shuffle(all_pairs)
        for a, b in all_pairs[:n]:
            pairs.append({
                "left": {"id": f"sk-p{a:02d}", "path": f"/tmp/v11sk-p{a:02d}-scored.png", "label": f"p{a:02d}"},
                "right": {"id": f"sk-p{b:02d}", "path": f"/tmp/v11sk-p{b:02d}-scored.png", "label": f"p{b:02d}"},
            })
    return pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="sk-vs-ww",
                     choices=["sk-vs-ww", "sk-tournament"])
    ap.add_argument("--n", type=int, default=25)
    ap.add_argument("--out", default="/tmp/spot-check.html")
    args = ap.parse_args()

    random.seed(42)
    pairs = build_pairs(args.mode, args.n)
    html = (TMPL_PRELUDE
            .replace("__TOTAL__", str(len(pairs)))
            .replace("__MODE__", args.mode)
            .replace("__PAIRS__", json.dumps(pairs)))
    Path(args.out).write_text(html)
    print(f"saved {args.out}  ({len(pairs)} pairs, mode={args.mode})")


if __name__ == "__main__":
    main()
