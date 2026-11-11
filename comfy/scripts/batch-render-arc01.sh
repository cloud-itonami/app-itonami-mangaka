#!/usr/bin/env bash
# Batch render arc 0-1 v10 — all 45 remaining pages (p01..p45).
# Uses the same ghosthacker preset + winning post-process recipe that scored
# 90.6/100 on p00 (ADR-2605260100).
#
# Resilience:
#  - SSH auto-restart of ComfyUI on AMD ROCm freeze (built into v10_panel_render)
#  - Per-page timeout 30min — skips and moves on if a page hangs
#  - Resume-safe: pre-existing /tmp/v10-pNN-scored.png is skipped unless --force
#
# Usage:
#   bash batch-render-arc01.sh              # render 1..45, skip existing
#   bash batch-render-arc01.sh --force      # re-render all
#   bash batch-render-arc01.sh 10 20        # render only 10..20
set -u
cd "$(dirname "$0")/.."
PY=.venv/bin/python
LOG=/tmp/v10-batch-arc01.log
: > "$LOG"

# 2026-05-26: new gad (Ubuntu 192.168.1.23) — Gemma 4 26B A4B via llama-server Vulkan
# + ComfyUI SDXL on same Radeon 8060S (64GB unified VRAM).
export COMFY_HOST="${COMFY_HOST:-http://192.168.1.23:8188}"
export COMFY_SSH_HOST="${COMFY_SSH_HOST:-gad@192.168.1.23}"
export COMFY_SSH_PASS="${COMFY_SSH_PASS:-230803}"
export OLLAMA_HOST="${OLLAMA_HOST:-http://192.168.1.23:11434}"
export OLLAMA_MODEL="${OLLAMA_MODEL:-gemma4}"
# v11 full pipeline (2026-05-27): variable layout + Witch Watch style +
# IP-Adapter character anchor + B1-B4 tunes
export V11_LAYOUT="${V11_LAYOUT:-1}"
export V11_STYLE="${V11_STYLE:-witchwatch}"
export V11_IPADAPTER="${V11_IPADAPTER:-1}"
echo "[batch] COMFY=$COMFY_HOST  LLM=$OLLAMA_HOST/$OLLAMA_MODEL  v11=layout+$V11_STYLE+ipa" | tee -a "$LOG"

FORCE=0
START=1
END=45
NUMARGS=()
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    *) [[ "$arg" =~ ^[0-9]+$ ]] && NUMARGS+=("$arg") ;;
  esac
done
[ "${#NUMARGS[@]}" -ge 1 ] && START="${NUMARGS[0]}"
[ "${#NUMARGS[@]}" -ge 2 ] && END="${NUMARGS[1]}"

echo "[batch] pages $START..$END (force=$FORCE)  log=$LOG"
echo "[batch] pages $START..$END (force=$FORCE)" >> "$LOG"

for p in $(seq "$START" "$END"); do
  pp=$(printf "%02d" "$p")
  out="/tmp/v10-p${pp}-scored.png"
  if [ -f "$out" ] && [ "$FORCE" -eq 0 ]; then
    echo "[batch] p${pp}: SKIP (exists)" | tee -a "$LOG"
    continue
  fi
  echo "[batch] p${pp}: START $(date +%H:%M:%S)" | tee -a "$LOG"
  if timeout 1800 "$PY" -m lg_mangaka.v10_orchestrator --preset ghosthacker "$p" \
       >> "$LOG" 2>&1; then
    echo "[batch] p${pp}: DONE $(date +%H:%M:%S)" | tee -a "$LOG"
  else
    echo "[batch] p${pp}: FAIL/TIMEOUT $(date +%H:%M:%S)" | tee -a "$LOG"
  fi
done

# Summary
echo "" | tee -a "$LOG"
echo "=== Summary ===" | tee -a "$LOG"
for p in $(seq "$START" "$END"); do
  pp=$(printf "%02d" "$p")
  out="/tmp/v10-p${pp}-scored.png"
  sc="/tmp/v10-p${pp}-score.json"
  if [ -f "$out" ]; then
    if [ -f "$sc" ]; then
      total=$("$PY" -c "import json; d=json.load(open('$sc')); print(d.get('total',0))" 2>/dev/null || echo "?")
      echo "p${pp}: ${total}/100" | tee -a "$LOG"
    else
      echo "p${pp}: rendered (no score json)" | tee -a "$LOG"
    fi
  else
    echo "p${pp}: MISSING" | tee -a "$LOG"
  fi
done
