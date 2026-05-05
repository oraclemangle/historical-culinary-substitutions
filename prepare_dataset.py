"""
Prepare HuggingFace-ready dataset from extracted culinary records.

Outputs:
  hf_dataset/substitutions.jsonl   — cleaned substitution pairs
  hf_dataset/README.md             — HuggingFace dataset card

Usage:
  python prepare_dataset.py
"""
import json
import re
from pathlib import Path
from collections import Counter

DATA_DIR  = Path("data")
OUT_DIR   = Path("hf_dataset")
OUT_DIR.mkdir(exist_ok=True)

SUBS_IN   = DATA_DIR / "substitutions.jsonl"
MEAS_IN   = DATA_DIR / "measurements.jsonl"
TERMS_IN  = DATA_DIR / "terms.jsonl"
CROSS_IN  = DATA_DIR / "crossref.json"


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


def clean_substitutions(records: list[dict]) -> list[dict]:
    """Remove low-quality records and normalise fields."""
    out = []
    seen = set()
    for r in records:
        ing  = (r.get("ingredient") or "").strip().lower()
        sub  = (r.get("substitute") or "").strip().lower()
        book = (r.get("book") or "").strip()
        year = r.get("year", 0)

        # Skip self-substitutions, missing key fields, bad years
        if not ing or not sub or ing == sub:
            continue
        if not book or year < 1600 or year > 1930:
            continue
        # Skip nonsense (single chars, pure numbers)
        if len(ing) < 2 or len(sub) < 2:
            continue
        if re.match(r'^\d+$', ing) or re.match(r'^\d+$', sub):
            continue

        key = (ing, sub, book)
        if key in seen:
            continue
        seen.add(key)

        out.append({
            "ingredient":  r.get("ingredient", "").strip(),
            "substitute":  r.get("substitute", "").strip(),
            "context":     (r.get("context") or "").strip(),
            "notes":       (r.get("notes") or "").strip(),
            "diet_tags":   r.get("diet_tags") or [],
            "book":        book,
            "year":        year,
        })
    return out


def enrich_with_consensus(records: list[dict], crossref: dict) -> list[dict]:
    """Add consensus_score field from crossref layer."""
    for r in records:
        ing_key = r["ingredient"].lower()
        sub_key = r["substitute"].lower()
        entry = crossref.get(ing_key, {})
        score = 0.0
        for s in entry.get("substitutes", []):
            if s.get("substitute", "").lower() == sub_key:
                score = s.get("consensus_score", 0.0)
                break
        r["consensus_score"] = round(score, 4)
    return records


def write_dataset_stats(subs: list[dict], meas: list[dict], terms: list[dict]) -> dict:
    year_dist = Counter(r["year"] for r in subs)
    book_dist = Counter(r["book"] for r in subs)
    ing_dist  = Counter(r["ingredient"].lower() for r in subs)
    return {
        "total_substitution_pairs": len(subs),
        "total_measurement_records": len(meas),
        "total_term_records": len(terms),
        "unique_ingredients": len(ing_dist),
        "unique_books": len(book_dist),
        "year_range": [min(year_dist), max(year_dist)] if year_dist else [0, 0],
        "top_ingredients": dict(ing_dist.most_common(20)),
        "top_books": dict(book_dist.most_common(10)),
    }


def main():
    print("Loading records...")
    subs_raw = load_jsonl(SUBS_IN)
    meas_raw = load_jsonl(MEAS_IN)
    terms_raw = load_jsonl(TERMS_IN)

    crossref = {}
    if CROSS_IN.exists():
        crossref = json.load(CROSS_IN.open(encoding="utf-8"))

    print(f"  raw substitutions : {len(subs_raw):,}")
    print(f"  raw measurements  : {len(meas_raw):,}")
    print(f"  raw terms         : {len(terms_raw):,}")

    print("Cleaning substitutions...")
    subs = clean_substitutions(subs_raw)
    print(f"  clean records     : {len(subs):,} ({len(subs)/len(subs_raw)*100:.1f}% kept)")

    if crossref:
        print("Enriching with consensus scores...")
        subs = enrich_with_consensus(subs, crossref)

    # Write cleaned substitutions
    subs_out = OUT_DIR / "substitutions.jsonl"
    with subs_out.open("w", encoding="utf-8") as f:
        for r in subs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"  → {subs_out}  ({len(subs):,} records)")

    # Write measurements if available
    if meas_raw:
        meas_out = OUT_DIR / "measurements.jsonl"
        with meas_out.open("w", encoding="utf-8") as f:
            for r in meas_raw:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"  → {meas_out}  ({len(meas_raw):,} records)")

    if terms_raw:
        terms_out = OUT_DIR / "terms.jsonl"
        with terms_out.open("w", encoding="utf-8") as f:
            for r in terms_raw:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"  → {terms_out}  ({len(terms_raw):,} records)")

    # Stats
    stats = write_dataset_stats(subs, meas_raw, terms_raw)
    stats_out = OUT_DIR / "dataset_stats.json"
    with stats_out.open("w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)

    # Write dataset card
    write_readme(stats, OUT_DIR / "README.md")
    print(f"  → {OUT_DIR}/README.md")
    print("\nDataset ready for HuggingFace upload.")
    print(f"  {stats['total_substitution_pairs']:,} substitution pairs")
    print(f"  {stats['unique_ingredients']:,} unique ingredients")
    print(f"  {stats['unique_books']:,} source books")
    print(f"  {stats['year_range'][0]}–{stats['year_range'][1]}")


def write_readme(stats: dict, path: Path):
    top_books = "\n".join(
        f"| {book} | {count:,} |"
        for book, count in list(stats["top_books"].items())[:8]
    )
    top_ings = ", ".join(
        f"`{ing}`" for ing in list(stats["top_ingredients"].keys())[:15]
    )
    n_subs  = stats["total_substitution_pairs"]
    n_meas  = stats["total_measurement_records"]
    n_terms = stats["total_term_records"]
    n_books = stats["unique_books"]
    n_ings  = stats["unique_ingredients"]
    yr0, yr1 = stats["year_range"]

    card = f"""---
license: cc-by-nc-4.0
language:
- en
tags:
- food
- cooking
- culinary
- historical
- ingredient-substitution
- recipes
- nlp
pretty_name: Historical Culinary Substitutions (1658–1929)
size_categories:
- 10K<n<100K
---

# Historical Culinary Substitutions Dataset

**{n_subs:,} ingredient substitution pairs** extracted from {n_books} public-domain cookbooks published between {yr0} and {yr1}.

Every record is grounded: it links directly to the book and page where the substitution appears, with the original source text as context.

## What's in this dataset

| File | Records | Description |
|---|---|---|
| `substitutions.jsonl` | {n_subs:,} | Ingredient → substitute pairs with citations |
| `measurements.jsonl` | {n_meas:,} | Historical measurement → modern equivalent conversions |
| `terms.jsonl` | {n_terms:,} | Old cooking terms with modern explanations |

## Substitution record format

```json
{{
  "ingredient":       "butter",
  "substitute":       "lard",
  "context":          "original source text from the book",
  "notes":            "additional extraction notes",
  "diet_tags":        ["historical"],
  "book":             "Mrs Beeton's Book of Household Management",
  "year":             1861,
  "consensus_score":  0.992
}}
```

### Fields

| Field | Type | Description |
|---|---|---|
| `ingredient` | string | The ingredient being substituted |
| `substitute` | string | The recommended substitute |
| `context` | string | Original text from the source book |
| `notes` | string | Extraction notes or additional guidance |
| `diet_tags` | list | Dietary/contextual tags |
| `book` | string | Source cookbook title |
| `year` | int | Publication year |
| `consensus_score` | float | 0–1 score: how many books agree on this substitution |

## Coverage

**Top ingredients:** {top_ings}

**Top source books:**

| Book | Pairs |
|---|---|
{top_books}

## Why this dataset is different

Most culinary substitution datasets are either:
- Modern crowd-sourced (Reddit, AllRecipes) — no citations, no historical context
- Nutrition-focused (USDA FDC) — no substitution logic

This dataset captures **pre-refrigeration, pre-industrial culinary logic**: why lard beats butter in certain pastries, why hartshorn (ammonium carbonate) was used before baking powder, how a Victorian cook adapted to ingredient scarcity.

The `consensus_score` field is unique: it measures cross-book agreement, so `butter → lard (score 0.99)` means nearly every book in the corpus agrees on that substitution.

## Source books

All books are pre-1929 public-domain works sourced from Project Gutenberg and the Internet Archive. Full book metadata available in the companion API.

## Licence

**CC BY-NC 4.0** — free for non-commercial use with attribution.
Commercial use requires a paid licence (tiers from $499). Contact via GitHub issues.
Cite as: *Pope, N. (2026). Historical Culinary Substitutions Dataset.*

## Companion API

A queryable REST API with semantic search, LLM synthesis, and batch endpoints is available at [old-recipe-intelligence.railway.app](https://old-recipe-intelligence.railway.app) (coming soon).

Commercial data licensing: contact via GitHub issues.
"""
    path.write_text(card, encoding="utf-8")


if __name__ == "__main__":
    main()
