#!/usr/bin/env bash
# Arc 0-1 全46ページ ロールアウト: 物語(arc τ)→ネーム(pagelayout)→カット→セリフ→
# 作画(gemini, per-char identity + calm/dynamic + authoritative scene)→層合成→扉タイトル写植。
# Stage A(設計, LLM)→ Stage B(作画, gemini)。Stage B はページ単位 resume(最終PNG存在ならskip)。
set -u
cd "$(dirname "$0")/.."
PY=.venv/bin/python
REFDIR="$(pwd)/../data/ghosthacker/character-refs"
PAGES="$(python3 -c 'print(",".join(str(i) for i in range(46)))')"
LOG=/tmp/rollout.log
: > "$LOG"
say(){ echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

say "=== Stage A: 設計 (arc / cuts / dialogue / pagelayout) — per-page ==="
$PY scripts/design_arc.py --out /tmp/arc.json >>"$LOG" 2>&1 && say "arc ✓"
for pn in $(seq 0 45); do
  $PY scripts/design_cuts.py       --pages "$pn" --out /tmp/cuts                    >>"$LOG" 2>&1
  $PY scripts/polish_dialogue.py   --pages "$pn" --out /tmp/dialogue               >>"$LOG" 2>&1
  $PY scripts/design_pagelayout.py --pages "$pn" --dialogue /tmp/dialogue \
                                   --out /tmp/pagelayout                            >>"$LOG" 2>&1
  c=$([ -f /tmp/cuts/p${pn}.json ] && echo ✓ || echo ✗)
  say "design p${pn}: cuts$c"
done

say "=== Stage B: 作画 (gemini per-page) ==="
mkdir -p /tmp/final-pages
ok=0; skip=0; fail=0
for pn in $(seq 0 45); do
  out=/tmp/final-pages/p${pn}-cut.p1.png
  [ -f /tmp/cuts/p${pn}.json ] || { say "p${pn}: no cuts, skip"; fail=$((fail+1)); continue; }
  if [ -f "$out" ]; then say "p${pn}: exists, skip"; skip=$((skip+1)); continue; fi
  if $PY scripts/render_cut_page.py --page "$pn" \
        --pagelayout /tmp/pagelayout --dialogue /tmp/dialogue \
        --refdir "$REFDIR" --out /tmp/final-pages >>"$LOG" 2>&1; then
    say "p${pn}: ✓"; ok=$((ok+1))
  else
    say "p${pn}: FAIL"; fail=$((fail+1))
  fi
done
say "=== DONE  gen=$ok skip=$skip fail=$fail ==="
