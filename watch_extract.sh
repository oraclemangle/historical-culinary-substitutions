#!/usr/bin/env bash
# watch_extract.sh — waits for extraction to complete, then rebuilds the full index.
# Run in a terminal or as a background process: ./watch_extract.sh
set -e

cd "$(dirname "$0")"

VENV="venv"
if [ -d "$VENV" ]; then
  source "$VENV/bin/activate"
fi

# ── Phase 1: Wait for substitutions extraction ────────────────────────────────
echo "Watching for extract_substitutions.py to finish..."
prev=0
while pgrep -f "extract_substitutions.py" > /dev/null 2>&1; do
  count=$(wc -l < data/substitutions.jsonl 2>/dev/null || echo 0)
  if [ "$count" != "$prev" ]; then
    echo "  $(date '+%H:%M') — substitutions: ${count} records"
    prev=$count
  fi
  sleep 60
done
echo "  $(date '+%H:%M') — substitutions extraction finished ($(wc -l < data/substitutions.jsonl) records)"

# ── Phase 2: Also wait for measurements extraction if still running ───────────
if pgrep -f "extract_measurements.py" > /dev/null 2>&1; then
  echo ""
  echo "Waiting for extract_measurements.py to finish too..."
  mprev=0
  while pgrep -f "extract_measurements.py" > /dev/null 2>&1; do
    mcount=0
    [ -f data/measurements.jsonl ] && mcount=$(wc -l < data/measurements.jsonl)
    if [ "$mcount" != "$mprev" ]; then
      echo "  $(date '+%H:%M') — measurements: ${mcount} records"
      mprev=$mcount
    fi
    sleep 60
  done
  echo "  $(date '+%H:%M') — measurements extraction finished"
fi

# ── Phase 3: Full rebuild ─────────────────────────────────────────────────────
echo ""
echo "Both extractions done. Running rebuild..."
bash rebuild.sh

echo ""
echo "All done. Corpus is up to date."
echo "  substitutions : $(wc -l < data/substitutions.jsonl) records"
[ -f data/measurements.jsonl ] && echo "  measurements  : $(wc -l < data/measurements.jsonl) records"
[ -f data/terms.jsonl ]        && echo "  terms         : $(wc -l < data/terms.jsonl) records"
