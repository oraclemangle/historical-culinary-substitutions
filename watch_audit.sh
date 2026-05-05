#!/usr/bin/env bash
# Runs a Groq audit on the enriched output every INTERVAL_RECORDS new records.
# Logs each audit run to logs/audit_<timestamp>.log
# Usage: ./watch_audit.sh [interval_records]

INTERVAL=${1:-2000}
OUTPUT="data/substitutions_enriched.jsonl"
VENV_PYTHON="${VENV_PYTHON:-./venv/bin/python3}"
LAST_AUDIT_AT=0

echo "Audit watcher started — will audit every ${INTERVAL} new records"
echo "Press Ctrl-C to stop."

while true; do
    if [[ ! -f "$OUTPUT" ]]; then
        sleep 30
        continue
    fi

    COUNT=$(wc -l < "$OUTPUT" | tr -d ' ')

    if (( COUNT - LAST_AUDIT_AT >= INTERVAL )); then
        SEED=$RANDOM
        STAMP=$(date +%Y%m%d_%H%M%S)
        LOG="logs/audit_${STAMP}.log"
        echo "[$(date '+%H:%M:%S')] ${COUNT} records enriched — running Groq audit (seed=${SEED})..."
        $VENV_PYTHON audit_enrichment.py --sample 200 --batch-size 30 --seed "$SEED" > "$LOG" 2>&1
        EXIT=$?
        if [[ $EXIT -eq 0 ]]; then
            # Pull the key summary lines into stdout
            grep -E "(Category agreement|Valid agreement|Disagreements|PASS|MARGINAL|FAIL)" "$LOG" | \
                sed "s/^/  /"
        else
            echo "  Audit script failed — check ${LOG}"
        fi
        LAST_AUDIT_AT=$COUNT
    fi

    sleep 60
done
