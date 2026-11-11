#!/usr/bin/env bash
# Re-letter v14 arc 0-1 WITHOUT regenerating any images (no ComfyUI/Modal).
# Reuses the saved source panels and redraws only the bubble/SFX layers with the
# new face/detail-aware auto-placement (bubble_autoplace.py). Output goes to a
# scratch dir so the committed final-pages/ + PDF are left untouched for review.
#
# Usage:
#   bash scripts/reletter-v14-arc01.sh                 # all pages with panels
#   bash scripts/reletter-v14-arc01.sh 10 20           # only pages 10..20
#   V14_AUTO_PLACE_BUBBLES=0 bash scripts/...          # keep static anchors
set -u
cd "$(dirname "$0")/.."
PY=$( [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3 )
V14=../data/ghosthacker/resources/episodes/arc0-1-origin/v14
EDN="$V14/storyboard-edn"
SRC="$V14/source-panels"
OUT="${OUT:-/tmp/v14-reletter}"
mkdir -p "$OUT"
LOG="$OUT/reletter.log"; : > "$LOG"

START="${1:-1}"; END="${2:-45}"
echo "[reletter] pages $START..$END -> $OUT (auto_place=${V14_AUTO_PLACE_BUBBLES:-1})"

moved_total=0; pages_done=0
for p in $(seq "$START" "$END"); do
  pp=$(printf "%02d" "$p")
  ls "$SRC"/v14-p${pp}-src-panel-*.png >/dev/null 2>&1 \
    || { echo "  p${pp}: SKIP (no source panels)"; continue; }
  edn=""
  for cand in "$EDN/p${pp}-datomic-v3.edn" "$EDN/p${pp}-datomic-v2.edn" "$EDN/p${pp}-datomic.edn"; do
    [ -f "$cand" ] && { edn="$cand"; break; }
  done
  [ -z "$edn" ] && { echo "  p${pp}: SKIP (no EDN)"; continue; }

  run_log="$OUT/run-p${pp}.log"
  if "$PY" -m lg_mangaka.v14_storyboard_renderer "$edn" \
        --reletter --src "$SRC" --out "$OUT" >"$run_log" 2>&1; then
    moved=$(grep -c "moved off art" "$run_log")
    echo "  p${pp}: $(basename "$edn")  (${moved} bubble(s) moved)"
    moved_total=$((moved_total + moved))
    pages_done=$((pages_done + 1))
  else
    echo "  p${pp}: FAILED (see $run_log)"; tail -3 "$run_log"
  fi
  cat "$run_log" >> "$LOG"
done

echo "[reletter] DONE: $pages_done pages, $moved_total bubble(s) relocated -> $OUT"
echo "[reletter] review finals: $OUT/v14-p*-final.png"
