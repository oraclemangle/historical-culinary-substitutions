"""
Batch enrichment pass over substitutions.jsonl using local Qwen 3.5 35B.

Adds two fields to each record:
  - category: one of dairy/fat/protein/grain/sweetener/spice/liquid/
               leavening/vegetable/fruit/fish/other
  - valid: true/false (with optional issue string)

Writes to: data/substitutions_enriched.jsonl
Checkpoint: data/enrich_checkpoint.json  (resume on restart)

Usage:
    python enrich_substitutions.py
    python enrich_substitutions.py --batch-size 25 --dry-run
"""

import argparse
import json
import random
import os
import re
import sys
import time
from pathlib import Path

import requests

# ── Config ────────────────────────────────────────────────────────────────────

# Comma-separated list of Ollama hosts, e.g.
#   OLLAMA_HOSTS=http://host-a:11434,http://host-b:11434
OLLAMA_HOSTS = [
    h.strip() for h in os.getenv("OLLAMA_HOSTS", "http://localhost:11434").split(",")
    if h.strip()
]
MODEL_ID     = os.getenv("OLLAMA_MODEL", "qwen3.5:35b-a3b")
TIMEOUT      = 300  # seconds per batch

DATA_DIR     = Path("data")
INPUT_PATH   = DATA_DIR / "substitutions.jsonl"
OUTPUT_PATH  = DATA_DIR / "substitutions_enriched.jsonl"
CHECKPOINT   = DATA_DIR / "enrich_checkpoint.json"

VALID_CATEGORIES = {
    "dairy", "fat", "protein", "grain", "sweetener",
    "spice", "liquid", "leavening", "vegetable", "fruit", "fish", "other"
}

PROMPT_TEMPLATE = """\
You are a data quality reviewer for a historical cookbook dataset (1658–1929).

Review the following {n} ingredient substitution records. For each record output a JSON object with:
  - index: the record's index number (as given)
  - valid: true or false
      Set valid=true for: any plausible food/cooking substitution, even if unusual or archaic.
      Set valid=false ONLY for: non-food items used as ingredients (e.g. sulphur, paint pigments,
      tooth-brush handles), or exact self-substitutions (ingredient == substitute verbatim).
      Historical oddities, vague substitutes ("any rich paste"), and partial substitutions are valid=true.
  - issue: null if valid=true, otherwise a brief reason (max 10 words)
  - category: classify the INGREDIENT field only (ignore the substitute) into exactly one of:
    dairy, fat, protein, grain, sweetener, spice, liquid, leavening, vegetable, fruit, fish, other
    Category guidance — use the MOST SPECIFIC category that fits:
      dairy    — milk, cream, butter, cheese, whey, eggs, buttermilk
      fat      — lard, suet, dripping, tallow, oil, shortening (non-dairy animal/vegetable fats)
      protein  — meat, poultry, game, offal, legumes, nuts, seeds (any flesh or plant protein)
      grain    — flour, bread, starch, oats, rice, pastry, meal, biscuit, crumbs
      sweetener— sugar, honey, treacle, syrup, molasses, jam
      spice    — herbs, spices, flavourings, condiments, mustard, vinegar, sauces, catsup
      liquid   — water, broth, stock, wine, spirits, beer, juice (non-dairy liquids)
      leavening— yeast, baking powder, bicarbonate of soda, hartshorn, pearl ash
      vegetable— any vegetable, root, fungus, or plant not covered above (e.g. carrot, onion, mushroom)
      fruit    — any fruit including citrus, berries, and dried fruit (e.g. raisin, prune)
      fish     — fish, shellfish, seafood
      other    — ONLY for non-food or highly ambiguous items; never use for recognisable food

Records:
{records}

Output ONLY a JSON array of {n} objects. No explanation, no markdown, no trailing text."""


# ── Ollama helpers ─────────────────────────────────────────────────────────────

def find_ollama() -> str:
    for host in OLLAMA_HOSTS:
        try:
            requests.get(f"{host}/api/tags", timeout=5)
            return host
        except (requests.ConnectionError, requests.Timeout):
            continue
    print("ERROR: Mac Studio unreachable on any known host.", file=sys.stderr)
    sys.exit(1)


def test_connection(host: str) -> bool:
    """Quick sanity check — verify think:false works on native endpoint."""
    try:
        resp = requests.post(f"{host}/api/chat", json={
            "model": MODEL_ID,
            "messages": [{"role": "user", "content": 'Reply with exactly: ["ok"] /no_think'}],
            "stream": False, "think": False, "options": {"num_predict": 20},
        }, timeout=30)
        content = resp.json().get("message", {}).get("content", "")
        return bool(content.strip())
    except Exception:
        return False


def call_qwen(host: str, records: list[dict]) -> list[dict] | None:
    """Send a batch to local Qwen. Returns parsed list or None on failure."""
    records_text = "\n".join(json.dumps(r) for r in records)
    prompt = PROMPT_TEMPLATE.format(n=len(records), records=records_text)

    # Use Ollama native /api/chat — the only endpoint that reliably honours think:false
    payload = {
        "model": MODEL_ID,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "options": {"num_predict": 4096},
    }

    try:
        resp = requests.post(
            f"{host}/api/chat",
            json=payload,
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        content = resp.json().get("message", {}).get("content", "")
    except Exception as e:
        print(f"  API error: {e}", file=sys.stderr)
        return None

    return parse_json_array(content, expected_count=len(records))


def parse_json_array(text: str, expected_count: int) -> list[dict] | None:
    """Extract and validate a JSON array from model output. Accepts partial batches."""
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text).strip()

    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        print(f"  No JSON array found in response.", file=sys.stderr)
        return None

    try:
        data = json.loads(match.group())
    except json.JSONDecodeError as e:
        print(f"  JSON parse error: {e}", file=sys.stderr)
        return None

    if len(data) == 0:
        print(f"  Empty array returned.", file=sys.stderr)
        return None

    # Accept partial batches — model occasionally drops 1-2 records
    if len(data) < expected_count:
        print(f"  Partial: {len(data)}/{expected_count} records — accepting. ", end="", flush=True)

    # Validate and coerce structure
    valid_items = []
    for item in data:
        if "index" not in item or "valid" not in item or "category" not in item:
            continue  # skip malformed items silently
        if item.get("category") not in VALID_CATEGORIES:
            item["category"] = "other"
        valid_items.append(item)

    return valid_items if valid_items else None


# ── Checkpoint ─────────────────────────────────────────────────────────────────

def load_checkpoint() -> int:
    if CHECKPOINT.exists():
        with open(CHECKPOINT) as f:
            return json.load(f).get("last_completed_batch", -1)
    return -1


def save_checkpoint(batch_idx: int):
    with open(CHECKPOINT, "w") as f:
        json.dump({"last_completed_batch": batch_idx}, f)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true",
                        help="Process first 2 batches only")
    parser.add_argument("--reset", action="store_true",
                        help="Ignore checkpoint and restart from scratch")
    args = parser.parse_args()

    # Load input
    records = []
    with open(INPUT_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    total = len(records)
    print(f"Loaded {total:,} records from {INPUT_PATH}")

    # Find Mac Studio and verify think:false works
    host = find_ollama()
    print(f"Ollama reachable at {host}")
    print("Testing think:false suppression... ", end="", flush=True)
    if not test_connection(host):
        print("FAILED — model not responding cleanly.")
        sys.exit(1)
    print("OK")

    # Build batches
    batch_size = args.batch_size
    batches = [records[i:i + batch_size] for i in range(0, total, batch_size)]
    print(f"Batches: {len(batches)} × {batch_size} records")

    # Resume from checkpoint
    last_done = -1 if args.reset else load_checkpoint()
    if last_done >= 0:
        print(f"Resuming from batch {last_done + 1} / {len(batches)}")

    # Open output file (append mode for resume)
    mode = "w" if (args.reset or not OUTPUT_PATH.exists()) else "a"
    failed_batches = []

    with open(OUTPUT_PATH, mode) as out_f:
        for batch_idx, batch in enumerate(batches):
            if batch_idx <= last_done:
                continue
            if args.dry_run and batch_idx >= 2:
                print("Dry run: stopping after 2 batches.")
                break

            start_record = batch_idx * batch_size
            print(f"Batch {batch_idx + 1}/{len(batches)}  "
                  f"(records {start_record}–{start_record + len(batch) - 1})  ", end="", flush=True)

            t0 = time.time()
            result = call_qwen(host, batch)
            elapsed = time.time() - t0

            if result is None:
                print(f"FAILED ({elapsed:.0f}s) — will retry at end")
                failed_batches.append(batch_idx)
                continue

            # Build lookup by index returned from model
            result_by_idx = {item["index"]: item for item in result}

            # Merge enrichment back — use position in batch as fallback index
            written = 0
            for pos, record in enumerate(batch):
                # Model may return absolute index or 0-based position
                item = result_by_idx.get(start_record + pos) or result_by_idx.get(pos)
                if item:
                    enriched = {
                        **record,
                        "category": item.get("category", "other"),
                        "valid": item.get("valid", True),
                        "issue": item.get("issue"),
                    }
                else:
                    # Model dropped this record — write original with defaults
                    enriched = {**record, "category": "other", "valid": True, "issue": "not_reviewed"}
                out_f.write(json.dumps(enriched) + "\n")
                written += 1

            out_f.flush()
            save_checkpoint(batch_idx)
            print(f"OK ({elapsed:.0f}s, {len(result)} records)")

    # Retry failed batches once
    if failed_batches:
        print(f"\nRetrying {len(failed_batches)} failed batches...")
        with open(OUTPUT_PATH, "a") as out_f:
            for batch_idx in failed_batches:
                batch = batches[batch_idx]
                start_record = batch_idx * batch_size
                print(f"  Retry batch {batch_idx + 1}... ", end="", flush=True)
                result = call_qwen(host, batch)
                if result is None:
                    print("FAILED again — writing originals with defaults")
                    for record in batch:
                        out_f.write(json.dumps({**record, "category": "other", "valid": True, "issue": "not_reviewed"}) + "\n")
                    continue
                result_by_idx = {item["index"]: item for item in result}
                for pos, record in enumerate(batch):
                    item = result_by_idx.get(start_record + pos) or result_by_idx.get(pos)
                    if item:
                        enriched = {**record, "category": item.get("category", "other"),
                                    "valid": item.get("valid", True), "issue": item.get("issue")}
                    else:
                        enriched = {**record, "category": "other", "valid": True, "issue": "not_reviewed"}
                    out_f.write(json.dumps(enriched) + "\n")
                print("OK")

    print(f"\nDone. Output: {OUTPUT_PATH}")
    if CHECKPOINT.exists():
        CHECKPOINT.unlink()


if __name__ == "__main__":
    main()
