#!/usr/bin/env bash
# Waits for extract_measurements.py to finish, then rebuilds index and uploads to GCS.
set -e
cd "$(dirname "$0")"
[ -d venv ] && source venv/bin/activate

echo "Watching extract_measurements.py (PID $(pgrep -f extract_measurements.py 2>/dev/null || echo '?'))..."
prev=0
while pgrep -f "extract_measurements.py" > /dev/null 2>&1; do
  mc=0; tc=0
  [ -f data/measurements.jsonl ] && mc=$(wc -l < data/measurements.jsonl)
  [ -f data/terms.jsonl ]        && tc=$(wc -l < data/terms.jsonl)
  cur="${mc}/${tc}"
  if [ "$cur" != "$prev" ]; then
    echo "  $(date '+%H:%M')  measurements: ${mc}  terms: ${tc}"
    prev=$cur
  fi
  sleep 60
done

mc=0; tc=0
[ -f data/measurements.jsonl ] && mc=$(wc -l < data/measurements.jsonl)
[ -f data/terms.jsonl ]        && tc=$(wc -l < data/terms.jsonl)
echo ""
echo "Extraction done — measurements: ${mc}  terms: ${tc}"
echo ""

echo "=== Rebuilding index ==="
bash rebuild.sh

echo ""
echo "=== Uploading to GCS ==="
python3 sync_data.py upload

echo ""
echo "Done. API is ready — restart uvicorn to pick up new index."
echo "  substitutions : $(wc -l < data/substitutions.jsonl)"
echo "  measurements  : ${mc}"
echo "  terms         : ${tc}"
