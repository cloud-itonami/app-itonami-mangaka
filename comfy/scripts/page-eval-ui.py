#!/usr/bin/env python3
"""Per-page multi-axis human evaluation UI.

For each page, rate 5 axes 0-5:
  - dialogue        (セリフ): bubble placement, text legibility, character match
  - composition     (構図): panel layout, R-to-L flow, dynamic vs static balance
  - scene           (シーン): scene fidelity to manifest, prop/setting accuracy
  - sfx             (SFX): effect text appropriateness, placement, variety
  - overall         (全体): would publish in Jump?

Plus free-text "issues" field. Export to JSON for analysis.

Usage:
  python3 scripts/page-eval-ui.py --prefix v11sk --n 15
  open /tmp/page-eval.html
"""
from __future__ import annotations
import argparse, json, random
from pathlib import Path

HTML = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Page Eval</title>
<style>
  body{background:#0a0a0a;color:#eee;font-family:sans-serif;margin:0;padding:14px;
       display:flex;gap:20px}
  .imgcol{flex:0 0 50%}
  .imgcol img{width:100%;border-radius:6px;display:block}
  .rate{flex:1;background:#1a1a1a;padding:16px;border-radius:8px}
  h1{margin:0 0 10px 0;font-size:18px}
  .progress{color:#9c9;margin-bottom:12px;font-size:13px}
  .axis{margin-bottom:14px}
  .axis-name{font-weight:bold;margin-bottom:6px;font-size:14px}
  .axis-hint{color:#888;font-size:11px;margin-bottom:6px}
  .scale{display:flex;gap:4px}
  .scale label{flex:1;background:#2a2a2a;padding:8px 0;text-align:center;
                cursor:pointer;border-radius:4px;font-size:14px}
  .scale input{display:none}
  .scale label.picked{background:#4af;color:#000;font-weight:bold}
  .scale label:hover{background:#444}
  textarea{width:100%;background:#2a2a2a;color:#eee;border:1px solid #555;
            border-radius:4px;padding:8px;font-family:inherit;font-size:13px;
            box-sizing:border-box;min-height:80px}
  .actions{display:flex;gap:8px;margin-top:14px}
  .btn{background:#333;color:#eee;border:0;padding:10px 18px;
       border-radius:4px;cursor:pointer;font-size:14px}
  .btn:hover{background:#555}
  .btn.next{background:#272;font-weight:bold}
  .btn.export{background:#225}
  .hint{color:#666;font-size:11px;margin-top:6px}
</style></head><body>
<div class="imgcol">
  <img id="pageImg" src="">
</div>
<div class="rate">
  <h1>Page Eval <span class="progress" id="prog">0 / __TOTAL__</span></h1>
  <div id="curPage" style="color:#9c9;font-size:13px;margin-bottom:10px"></div>

  <div class="axis">
    <div class="axis-name">セリフ (Dialogue)</div>
    <div class="axis-hint">吹き出し位置 + 文字読みやすさ + キャラ一致</div>
    <div class="scale" data-axis="dialogue">__SCALE__</div>
  </div>

  <div class="axis">
    <div class="axis-name">構図 (Composition)</div>
    <div class="axis-hint">コマ割り + R-to-L flow + dynamic vs static</div>
    <div class="scale" data-axis="composition">__SCALE__</div>
  </div>

  <div class="axis">
    <div class="axis-name">シーン (Scene)</div>
    <div class="axis-hint">manifest との一致 + prop/設定の正確さ</div>
    <div class="scale" data-axis="scene">__SCALE__</div>
  </div>

  <div class="axis">
    <div class="axis-name">SFX</div>
    <div class="axis-hint">効果音の選択 + 位置 + サイズの多様性</div>
    <div class="scale" data-axis="sfx">__SCALE__</div>
  </div>

  <div style="border-top:1px solid #444;margin:14px 0 8px 0;padding-top:10px;color:#aaa;font-size:11px">— Reader experience (読者体験) —</div>

  <div class="axis">
    <div class="axis-name">感情 (Emotion conveyed)</div>
    <div class="axis-hint">シーンが意図した感情が伝わるか (joy/fear/tension/empathy 等)</div>
    <div class="scale" data-axis="emotion">__SCALE__</div>
  </div>

  <div class="axis">
    <div class="axis-name">状況 (Situation clarity)</div>
    <div class="axis-hint">今何が起こっているか、どこにいるか、誰が何をしているか</div>
    <div class="scale" data-axis="situation">__SCALE__</div>
  </div>

  <div class="axis">
    <div class="axis-name">心理的作用 (Psychological impact on reader)</div>
    <div class="axis-hint">読み手に意図した心理反応を起こすか (緊張/共感/恐怖/期待/没入)</div>
    <div class="scale" data-axis="psychological">__SCALE__</div>
  </div>

  <div class="axis">
    <div class="axis-name">全体 (Overall — Jump publishable?)</div>
    <div class="axis-hint">5 = Jump 掲載可、3 = doujin、1 = AI artifact</div>
    <div class="scale" data-axis="overall">__SCALE__</div>
  </div>

  <div class="axis">
    <div class="axis-name">Issues (free text, 改行区切り)</div>
    <textarea id="issues" placeholder="例: panel 3 の Yuto の手が破綻&#10;吹き出しが Yuto の顔を覆っている"></textarea>
  </div>

  <div class="actions">
    <button class="btn next" onclick="next()">Next →</button>
    <button class="btn" onclick="skip()">Skip</button>
    <button class="btn export" onclick="exportResults()">Export JSON</button>
  </div>
  <div class="hint">Number keys 1-5 set the FOCUSED axis. Tab moves to next axis. Cmd+Enter = Next.</div>
</div>
<script>
const PAGES = __PAGES__;
const KEY = "page_eval_" + "__PREFIX__";
let idx = 0;
let results = JSON.parse(localStorage.getItem(KEY) || "[]");
if (results.length >= PAGES.length) results = [];
idx = results.length;
const axes = ["dialogue","composition","scene","sfx","emotion","situation","psychological","overall"];
let cur = {};

function buildScale(axis) {
  const div = document.querySelector(`.scale[data-axis="${axis}"]`);
  div.innerHTML = "";
  for (let i = 0; i <= 5; i++) {
    const lab = document.createElement("label");
    lab.textContent = i;
    lab.dataset.value = i;
    lab.onclick = () => {
      div.querySelectorAll("label").forEach(l => l.classList.remove("picked"));
      lab.classList.add("picked");
      cur[axis] = i;
    };
    div.appendChild(lab);
  }
}
axes.forEach(buildScale);

function render() {
  if (idx >= PAGES.length) {
    document.body.innerHTML = '<h1>Done! ' + results.length + ' pages rated.</h1>' +
      '<button class="btn export" onclick="exportResults()">Download JSON</button>';
    return;
  }
  const p = PAGES[idx];
  document.getElementById("pageImg").src = "file://" + p.path;
  document.getElementById("curPage").textContent = "Page: " + p.label;
  document.getElementById("prog").textContent = (idx) + " / " + PAGES.length;
  document.getElementById("issues").value = "";
  cur = {};
  document.querySelectorAll(".scale label.picked").forEach(l => l.classList.remove("picked"));
}
function next() {
  const issues = document.getElementById("issues").value.split("\\n").map(s=>s.trim()).filter(s=>s);
  results.push({page_idx: idx, id: PAGES[idx].id, label: PAGES[idx].label,
                 scores: cur, issues});
  localStorage.setItem(KEY, JSON.stringify(results));
  idx++;
  render();
}
function skip() { idx++; render(); }
function exportResults() {
  const blob = new Blob([JSON.stringify(results, null, 2)], {type: "application/json"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "page-eval-__PREFIX__-" + Date.now() + ".json";
  a.click();
}
window.addEventListener("keydown", e => {
  if (e.metaKey && e.key === "Enter") { next(); return; }
  // Number keys 1-5 set last-focused axis... simpler: set OVERALL
  if (e.key >= "0" && e.key <= "5") {
    const overall = document.querySelector('.scale[data-axis="overall"]');
    overall.querySelectorAll("label").forEach(l => l.classList.remove("picked"));
    const target = overall.querySelector(`label[data-value="${e.key}"]`);
    if (target) { target.classList.add("picked"); cur.overall = parseInt(e.key); }
  }
});
render();
</script></body></html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", default="v11sk",
                     help="image prefix in /tmp (v11sk or v11full)")
    ap.add_argument("--n", type=int, default=15)
    ap.add_argument("--out", default="/tmp/page-eval.html")
    args = ap.parse_args()

    files = sorted(Path("/tmp").glob(f"{args.prefix}-p*-scored.png"))
    pages = []
    for f in files:
        pp = f.name.split(f"{args.prefix}-p")[-1].split("-")[0]
        pages.append({"id": f"{args.prefix}-p{pp}", "label": f"p{pp}", "path": str(f)})
    random.seed(13)
    random.shuffle(pages)
    pages = pages[:args.n]

    scale = "".join(f'<label data-value="{i}">{i}</label>' for i in range(6))
    html = (HTML
            .replace("__TOTAL__", str(len(pages)))
            .replace("__PREFIX__", args.prefix)
            .replace("__PAGES__", json.dumps(pages))
            .replace("__SCALE__", scale))
    Path(args.out).write_text(html)
    print(f"saved {args.out}  ({len(pages)} pages, prefix={args.prefix})")


if __name__ == "__main__":
    main()
