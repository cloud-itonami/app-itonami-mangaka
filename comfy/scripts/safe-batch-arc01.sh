#!/bin/bash
PAGES="$1"
RESTART_SCRIPT="C:\Users\gad\restart-comfy.ps1"
COMFY="192.168.1.22"

echo "$PAGES" | tr ',' '\n' > /tmp/safe-pages.txt

# Always restart at start
echo "=== initial restart ==="
ssh -n gad@${COMFY} "powershell -ExecutionPolicy Bypass -File ${RESTART_SCRIPT}" 2>&1 | tail -1
sleep 5

CHUNK=0
PAGES_DONE_IN_CHUNK=0
while read -r p; do
  [ -z "$p" ] && continue

  if [ $PAGES_DONE_IN_CHUNK -eq 0 ] && [ $CHUNK -gt 0 ]; then
    echo "=== restarting ComfyUI (chunk $CHUNK) ==="
    ssh -n gad@${COMFY} "powershell -ExecutionPolicy Bypass -File ${RESTART_SCRIPT}" 2>&1 | tail -1
    sleep 5
  fi

  echo "=== chunk $CHUNK page $p ==="
  python3 /tmp/render-arc01-page.py $p 2>&1 | tee -a /tmp/arc01-safe-batch.log

  PAGES_DONE_IN_CHUNK=$((PAGES_DONE_IN_CHUNK + 1))
  if [ $PAGES_DONE_IN_CHUNK -ge 5 ]; then
    CHUNK=$((CHUNK + 1))
    PAGES_DONE_IN_CHUNK=0
  fi
done < /tmp/safe-pages.txt
echo "=== SAFE-BATCH-DONE ==="
