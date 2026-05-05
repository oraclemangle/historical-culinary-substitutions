#!/usr/bin/env bash
# rebuild.sh — run after extraction completes to rebuild the full index + crossref
# Usage: ./rebuild.sh
set -e

VENV="$(dirname "$0")/venv"
if [ -d "$VENV" ]; then
  source "$VENV/bin/activate"
fi

echo "=== Step 1/4: Patching any year=0 records ==="
python3 fix_years.py

echo ""
echo "=== Step 2/4: Building FAISS index ==="
python3 build_index.py

echo ""
echo "=== Step 3/4: Rebuilding cross-reference layer ==="
python3 crossref.py

echo ""
echo "=== Step 4/4: Validating data quality ==="
python3 validate_data.py

echo ""
echo "=== Done. Index, crossref, and validation report are up to date. ==="
echo "Restart the API server to pick up the new index."
