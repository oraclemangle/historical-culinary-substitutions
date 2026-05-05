"""
Post-processing pass: re-classify records where category == "other" using Gemini 2.5 Flash.

Qwen systematically over-used "other" for recognisable food items. This script
sends those records to Gemini for a second opinion and updates the category in-place.

Usage:
    python fix_other_categories.py              # dry-run preview
    python fix_other_categories.py --apply      # write updated file
    python fix_other_categories.py --apply --batch-size 40
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

# ── Config ────────────────────────────────────────────────────────────────────

ENV_PATH    = Path.home() / ".claude" / ".env"
INPUT_PATH  = Path("data") / "substitutions_enriched.jsonl"
OUTPUT_PATH = Path("data") / "substitutions_enriched.jsonl"
BACKUP_PATH = Path("data") / "substitutions_enriched.bak.jsonl"

GEMINI_MODEL    = "gemini-2.5-flash"
GEMINI_ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

VALID_CATEGORIES = {
    "dairy", "fat", "protein", "grain", "sweetener",
    "spice", "liquid", "leavening", "vegetable", "fruit", "fish", "other"
}

PROMPT_TEMPLATE = """\
You are classifying ingredients from a historical cookbook dataset (1658–1929).

For each of the following {n} records, classify the INGREDIENT field into EXACTLY one of:
  dairy, fat, protein, grain, sweetener, spice, liquid, leavening, vegetable, fruit, fish, other

Rules:
  dairy     — milk, cream, butter, cheese, eggs, buttermilk, whey
  fat       — lard, suet, dripping, tallow, oil, shortening (non-dairy fats)
  protein   — meat, poultry, game, offal, fish roe, legumes, nuts, seeds
  grain     — flour, bread, starch, oats, rice, pastry, meal, biscuit, crumbs, arrowroot
  sweetener — sugar, honey, treacle, syrup, molasses, jam, preserve
  spice     — herbs, spices, flavourings, condiments, vinegar, mustard, catsup, sauces
  liquid    — water, broth, stock, wine, spirits, beer, juice, tea, coffee (non-dairy liquids)
  leavening — yeast, baking powder, bicarbonate of soda, hartshorn, pearl ash
  vegetable — any vegetable, root, fungus, or plant (e.g. carrot, onion, mushroom, truffle)
  fruit     — any fruit including citrus, berries, dried fruit (e.g. raisin, prune, rhubarb)
  fish      — fish, shellfish, seafood
  other     — ONLY for non-food items (chemicals, materials) or truly unclassifiable

For each record output: {{"index": <index>, "category": "<category>"}}

Records:
{records}

Output ONLY a JSON array of {n} objects. No explanation, no markdown."""


# ── Gemini call ───────────────────────────────────────────────────────────────

def call_gemini(api_key: str, records: list[dict], retries: int = 3) -> list[dict] | None:
    records_text = "\n".join(
        json.dumps({"index": r["_idx"], "ingredient": r["ingredient"],
                    "substitute": r.get("substitute", ""), "context": r.get("context", "")})
        for r in records
    )
    prompt = PROMPT_TEMPLATE.format(n=len(records), records=records_text)

    url = f"{GEMINI_ENDPOINT}?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 4096,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }

    for attempt in range(retries):
        try:
            resp = requests.post(url, json=payload, timeout=60)
            if resp.status_code == 429:
                wait = 20 * (attempt + 1)
                print(f"  rate limited, waiting {wait}s...", end="", flush=True)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            content = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            return parse_json_array(content, expected_count=len(records))
        except Exception as e:
            print(f"  Gemini error: {e}", file=sys.stderr)
            if attempt < retries - 1:
                time.sleep(5)
    return None


def parse_json_array(text: str, expected_count: int) -> list[dict] | None:
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text).strip()
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return None
    # Accept partial results
    return data if data else None


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Write changes to file")
    parser.add_argument("--batch-size", type=int, default=40)
    args = parser.parse_args()

    load_dotenv(ENV_PATH)
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("ERROR: GOOGLE_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    # Load all records
    all_records = []
    with open(INPUT_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                all_records.append(json.loads(line))
    print(f"Loaded {len(all_records):,} total records")

    # Find "other" records
    other_indices = [i for i, r in enumerate(all_records) if r.get("category") == "other"]
    print(f"Found {len(other_indices):,} records with category='other' ({len(other_indices)/len(all_records)*100:.1f}%)")

    if not other_indices:
        print("Nothing to fix.")
        return

    # Tag with index for matching
    other_records = []
    for i in other_indices:
        rec = dict(all_records[i])
        rec["_idx"] = i
        other_records.append(rec)

    if not args.apply:
        print(f"\nDry run — would send {len(other_records)} records to Gemini in batches of {args.batch_size}.")
        print("Sample 'other' records:")
        for r in other_records[:10]:
            print(f"  [{r['ingredient']} → {r.get('substitute', '')}]")
        print("\nRe-run with --apply to make changes.")
        return

    # Process in batches
    batches = [other_records[i:i + args.batch_size] for i in range(0, len(other_records), args.batch_size)]
    print(f"\nSending {len(other_records)} records to Gemini in {len(batches)} batches...")

    fixes = {}
    for batch_idx, batch in enumerate(batches):
        print(f"  Batch {batch_idx + 1}/{len(batches)}... ", end="", flush=True)
        result = call_gemini(api_key, batch)
        if result is None:
            print("FAILED — keeping 'other' for this batch")
        else:
            for item in result:
                cat = item.get("category", "other")
                if cat not in VALID_CATEGORIES:
                    cat = "other"
                fixes[item["index"]] = cat
            changed = sum(1 for item in result if item.get("category", "other") != "other")
            print(f"OK — {changed}/{len(batch)} re-classified away from 'other'")
        time.sleep(2)

    # Apply fixes
    changed_count = 0
    for idx, new_cat in fixes.items():
        if new_cat != "other":
            all_records[idx]["category"] = new_cat
            changed_count += 1

    print(f"\nRe-classified {changed_count} / {len(other_indices)} 'other' records")

    # Backup then write
    print(f"Backing up to {BACKUP_PATH}...")
    import shutil
    shutil.copy(INPUT_PATH, BACKUP_PATH)

    print(f"Writing updated file to {OUTPUT_PATH}...")
    with open(OUTPUT_PATH, "w") as f:
        for rec in all_records:
            # Remove temp index field if present
            rec.pop("_idx", None)
            f.write(json.dumps(rec) + "\n")

    remaining_other = sum(1 for r in all_records if r.get("category") == "other")
    print(f"Done. Remaining 'other' records: {remaining_other:,}")


if __name__ == "__main__":
    main()
