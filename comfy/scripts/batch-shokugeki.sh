#!/usr/bin/env bash
# Shokugeki no Soma style — all 46 pages of arc 0-1.
# Outputs to /tmp/v11sk-pNN-scored.png (Witch Watch preserved at v11full).
set -u
cd "$(dirname "$0")/.."

export COMFY_HOST="${COMFY_HOST:-http://192.168.1.23:8188}"
export COMFY_SSH_HOST="${COMFY_SSH_HOST:-gad@192.168.1.23}"
export COMFY_SSH_PASS="${COMFY_SSH_PASS:-230803}"
export OLLAMA_HOST="${OLLAMA_HOST:-http://192.168.1.23:11434}"
export OLLAMA_MODEL="${OLLAMA_MODEL:-gemma4}"
export V11_LAYOUT="${V11_LAYOUT:-1}"
export V11_STYLE="${V11_STYLE:-shokugeki}"
export V11_IPADAPTER="${V11_IPADAPTER:-1}"
export PYTHONUNBUFFERED=1

PY=.venv/bin/python
LOG=/tmp/v11sk-batch.log
: > "$LOG"
echo "[shokugeki] $(date +%H:%M:%S) START — 46 pages" | tee -a "$LOG"

START=${1:-0}
END=${2:-45}

for p in $(seq "$START" "$END"); do
  pp=$(printf "%02d" "$p")
  out="/tmp/v11sk-p${pp}-scored.png"
  if [ -f "$out" ]; then
    echo "[shokugeki] p${pp}: SKIP (exists $(du -h $out | cut -f1))" | tee -a "$LOG"
    continue
  fi
  echo "[shokugeki] p${pp}: START $(date +%H:%M:%S)" | tee -a "$LOG"
  if timeout 3000 "$PY" -u -m lg_mangaka.v10_orchestrator \
       --preset ghosthacker "$p" >> "$LOG" 2>&1; then
    # move to v11sk- prefix
    [ -f "/tmp/v10-p${pp}-scored.png" ] && mv "/tmp/v10-p${pp}-scored.png" "$out"
    [ -f "/tmp/v10-p${pp}-score.json" ] && mv "/tmp/v10-p${pp}-score.json" "/tmp/v11sk-p${pp}-score.json"
    echo "[shokugeki] p${pp}: DONE $(date +%H:%M:%S)" | tee -a "$LOG"
  else
    echo "[shokugeki] p${pp}: FAIL/TIMEOUT $(date +%H:%M:%S)" | tee -a "$LOG"
  fi
done

echo "" | tee -a "$LOG"
echo "[shokugeki] $(date +%H:%M:%S) ALL DONE" | tee -a "$LOG"

# Summary
echo "" | tee -a "$LOG"
echo "=== Summary ===" | tee -a "$LOG"
for p in $(seq "$START" "$END"); do
  pp=$(printf "%02d" "$p")
  sc="/tmp/v11sk-p${pp}-score.json"
  if [ -f "$sc" ]; then
    total=$("$PY" -c "import json; d=json.load(open('$sc')); print(d.get('total',0))" 2>/dev/null || echo "?")
    echo "p${pp}: ${total}/100" | tee -a "$LOG"
  else
    echo "p${pp}: MISSING" | tee -a "$LOG"
  fi
done
