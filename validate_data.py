"""
Data validation — flags quality issues in the extracted dataset.

Checks:
  1. Suspiciously generic substitutions (ingredient == substitute, or trivially similar)
  2. Records with empty/missing context (extraction likely hallucinated)
  3. Ingredient or substitute strings that are too long (likely a bad extraction)
  4. Duplicate records within the same book
  5. Records where year is still 0 (missing metadata)
  6. Nonsense substitutions (numbers, single chars, URLs)

Output: data/validation_report.json + prints summary
"""
import json
import re
from collections import defaultdict
from pathlib import Path

DATA_DIR  = Path("data")
SUB_PATH  = DATA_DIR / "substitutions.jsonl"
OUT_PATH  = DATA_DIR / "validation_report.json"

# Thresholds
MAX_FIELD_LEN   = 120   # ingredient/substitute fields shouldn't be sentences
MIN_CONTEXT_LEN = 10    # context under 10 chars is probably empty/garbage


def looks_like_nonsense(s: str) -> bool:
    if not s or len(s) < 2:
        return True
    if re.match(r"^\d+$", s):          # pure number
        return True
    if re.search(r"https?://", s):     # URL crept in
        return True
    if len(s) > MAX_FIELD_LEN:         # full sentence, not an ingredient name
        return True
    return False


def are_too_similar(a: str, b: str) -> bool:
    a, b = a.lower().strip(), b.lower().strip()
    if a == b:
        return True
    # One is a substring of the other (e.g. "cream" vs "cream of tartar" is fine,
    # "butter" vs "butter (unsalted)" is a near-duplicate)
    if (a in b or b in a) and abs(len(a) - len(b)) < 5:
        return True
    return False


def main():
    records = []
    with SUB_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass

    print(f"Validating {len(records):,} records...\n")

    issues: dict[str, list[dict]] = defaultdict(list)

    # Per-book duplicate tracking: (ingredient, substitute) -> book
    book_pairs: dict[str, set] = defaultdict(set)

    for i, r in enumerate(records):
        ing  = r.get("ingredient", "")
        sub  = r.get("substitute", "")
        ctx  = r.get("context", "")
        book = r.get("book", "")
        year = r.get("year", 0)
        rec  = {"idx": i, "book": book, "year": year, "ingredient": ing, "substitute": sub}

        if looks_like_nonsense(ing):
            issues["nonsense_ingredient"].append(rec)

        if looks_like_nonsense(sub):
            issues["nonsense_substitute"].append(rec)

        if are_too_similar(ing, sub):
            issues["self_substitution"].append(rec)

        if not ctx or len(ctx) < MIN_CONTEXT_LEN:
            issues["missing_context"].append(rec)

        if year == 0:
            issues["missing_year"].append(rec)

        pair_key = f"{ing.lower()}||{sub.lower()}"
        if pair_key in book_pairs[book]:
            issues["duplicate_in_book"].append(rec)
        else:
            book_pairs[book].add(pair_key)

    # Compute stats
    total       = len(records)
    total_issues = sum(len(v) for v in issues.values())
    clean       = total - len({r["idx"] for v in issues.values() for r in v})

    print("Issue breakdown:")
    for issue_type, recs in sorted(issues.items(), key=lambda x: -len(x[1])):
        pct = len(recs) / total * 100
        print(f"  {issue_type:30s}: {len(recs):5,}  ({pct:.1f}%)")

    print(f"\nTotal records    : {total:,}")
    print(f"Records with issues: {total_issues:,} ({total_issues/total*100:.1f}%)")
    print(f"Clean records    : {clean:,} ({clean/total*100:.1f}%)")

    # Sample of each issue type
    samples = {}
    for issue_type, recs in issues.items():
        samples[issue_type] = recs[:5]

    report = {
        "total_records":   total,
        "clean_records":   clean,
        "issues_summary":  {k: len(v) for k, v in issues.items()},
        "samples":         samples,
    }
    OUT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nFull report → {OUT_PATH}")


if __name__ == "__main__":
    main()
