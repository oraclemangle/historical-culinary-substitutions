"""
Audit the enrichment output by sending a random sample to Gemini 2.5 Flash
and comparing its category/valid judgements against Qwen's.

Usage:
    python audit_enrichment.py                  # audit 200 random records
    python audit_enrichment.py --sample 500     # larger sample
    python audit_enrichment.py --batch-size 30  # records per Gemini call
"""

import argparse
import json
import os
import random
import re
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

# ── Config ────────────────────────────────────────────────────────────────────

ENV_PATH    = Path.home() / ".claude" / ".env"
INPUT_PATH  = Path("data") / "substitutions_enriched.jsonl"
REPORT_PATH = Path("data") / "audit_report.json"

GEMINI_MODEL    = "gemini-2.5-flash"
GEMINI_ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

VALID_CATEGORIES = {
    "dairy", "fat", "protein", "grain", "sweetener",
    "spice", "liquid", "leavening", "vegetable", "fruit", "fish", "other"
}

PROMPT_TEMPLATE = """\
You are auditing a historical cookbook dataset for data quality.

For each of the following {n} ingredient substitution records, output a JSON object with:
  - index: the record's index (as given)
  - valid: true if the substitution is plausible, false if nonsensical or a self-substitution
  - issue: null if valid=true, otherwise a brief reason (max 10 words)
  - category: classify the INGREDIENT field (not the substitute) into EXACTLY one of these 12 values:
    dairy, fat, protein, grain, sweetener, spice, liquid, leavening, vegetable, fruit, fish, other
    You MUST use only these exact strings. Never use "nut", "starch", "sauce", or any other value.
    Guidance: nuts/seeds/legumes/meat = protein | flour/bread/starch/arrowroot = grain |
    butter/lard/oil/dripping = fat | milk/cream/cheese/eggs/buttermilk = dairy |
    herbs/spices/vinegar/condiments/catsup = spice | water/broth/wine/spirits = liquid |
    yeast/baking powder/soda/hartshorn = leavening | sugar/honey/treacle/jam = sweetener |
    use "other" ONLY for non-food or truly unclassifiable items

Records:
{records}

Output ONLY a JSON array of {n} objects. No explanation, no markdown."""


# ── Gemini call ───────────────────────────────────────────────────────────────

def call_gemini(api_key: str, records: list[dict], retries: int = 3) -> list[dict] | None:
    records_text = "\n".join(
        json.dumps({"index": r["_audit_idx"], "ingredient": r["ingredient"],
                    "substitute": r["substitute"], "context": r.get("context", ""),
                    "notes": r.get("notes", "")})
        for r in records
    )
    prompt = PROMPT_TEMPLATE.format(n=len(records), records=records_text)

    url = f"{GEMINI_ENDPOINT}?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 8192,
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
    return data if len(data) == expected_count else None


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=200)
    parser.add_argument("--batch-size", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    load_dotenv(ENV_PATH)
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("ERROR: GOOGLE_API_KEY not set in ~/.claude/.env", file=sys.stderr)
        sys.exit(1)

    if not INPUT_PATH.exists():
        print(f"ERROR: {INPUT_PATH} not found. Run enrich_substitutions.py first.", file=sys.stderr)
        sys.exit(1)

    # Load enriched records
    enriched = []
    with open(INPUT_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                enriched.append(json.loads(line))
    print(f"Loaded {len(enriched):,} enriched records")

    # Sample
    random.seed(args.seed)
    sample_size = min(args.sample, len(enriched))
    sample = random.sample(enriched, sample_size)
    for i, rec in enumerate(sample):
        rec["_audit_idx"] = i
    print(f"Auditing {sample_size} records via Gemini {GEMINI_MODEL}...")

    # Call Gemini in batches
    batches = [sample[i:i + args.batch_size] for i in range(0, sample_size, args.batch_size)]
    gemini_results = {}

    for batch_idx, batch in enumerate(batches):
        print(f"  Batch {batch_idx + 1}/{len(batches)}... ", end="", flush=True)
        result = call_gemini(api_key, batch)
        if result is None:
            print("FAILED")
        else:
            for item in result:
                gemini_results[item["index"]] = item
            print(f"OK ({len(result)} records)")
        time.sleep(2)

    # Compare
    disagreements = []
    category_matches = 0
    valid_matches = 0
    total_compared = 0

    for rec in sample:
        idx = rec["_audit_idx"]
        if idx not in gemini_results:
            continue
        gemini = gemini_results[idx]
        total_compared += 1

        qwen_cat    = rec.get("category", "other")
        gemini_cat  = gemini.get("category", "other")
        qwen_valid  = rec.get("valid", True)
        gemini_valid = gemini.get("valid", True)

        cat_match   = qwen_cat == gemini_cat
        valid_match = qwen_valid == gemini_valid

        if cat_match:
            category_matches += 1
        if valid_match:
            valid_matches += 1

        if not cat_match or not valid_match:
            disagreements.append({
                "ingredient":      rec["ingredient"],
                "substitute":      rec["substitute"],
                "book":            rec.get("book", ""),
                "year":            rec.get("year"),
                "qwen_category":   qwen_cat,
                "gemini_category": gemini_cat,
                "category_match":  cat_match,
                "qwen_valid":      qwen_valid,
                "gemini_valid":    gemini_valid,
                "valid_match":     valid_match,
                "gemini_issue":    gemini.get("issue"),
            })

    # Report
    cat_agreement   = category_matches / total_compared * 100 if total_compared else 0
    valid_agreement = valid_matches / total_compared * 100 if total_compared else 0

    print(f"\n{'─' * 50}")
    print(f"Audit complete — {total_compared} records compared")
    print(f"  Category agreement:  {cat_agreement:.1f}%  ({category_matches}/{total_compared})")
    print(f"  Valid agreement:     {valid_agreement:.1f}%  ({valid_matches}/{total_compared})")
    print(f"  Disagreements:       {len(disagreements)}")

    if disagreements:
        print(f"\nFirst 10 disagreements:")
        for d in disagreements[:10]:
            print(f"  [{d['ingredient']} → {d['substitute']}]  "
                  f"cat: {d['qwen_category']} vs {d['gemini_category']}  "
                  f"valid: {d['qwen_valid']} vs {d['gemini_valid']}")

    # Save full report
    report = {
        "auditor":            GEMINI_MODEL,
        "sample_size":        sample_size,
        "total_compared":     total_compared,
        "category_agreement": round(cat_agreement, 2),
        "valid_agreement":    round(valid_agreement, 2),
        "disagreement_count": len(disagreements),
        "disagreements":      disagreements,
    }
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nFull report saved to {REPORT_PATH}")

    if cat_agreement >= 85:
        print("\n✓ PASS — category agreement >=85%. Enriched dataset looks solid.")
    elif cat_agreement >= 70:
        print("\n~ MARGINAL — review disagreements before accepting dataset.")
    else:
        print("\n✗ FAIL — category agreement <70%. Review Qwen output carefully.")


if __name__ == "__main__":
    main()
