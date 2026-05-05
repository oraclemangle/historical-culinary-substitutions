"""
Cross-reference layer — transforms raw extraction records into a
structured knowledge graph with consensus scores and provenance.

Reads:  data/substitutions.jsonl
Writes: data/crossref.json        — grouped, scored, cited knowledge base
        data/crossref_stats.json  — summary stats for API /stats endpoint

Schema per ingredient entry:
{
  "ingredient": "buttermilk",
  "substitutes": [
    {
      "substitute": "sour milk",
      "consensus_score": 0.87,      // 0-1, based on frequency + book diversity
      "book_count": 12,
      "earliest_year": 1837,
      "latest_year": 1920,
      "diet_tags": ["budget", "historical"],
      "citations": [
        {"book": "Directions For Cookery", "year": 1837, "context": "..."},
        ...
      ]
    }
  ],
  "total_citations": 34,
  "coverage_years": [1837, 1920]
}
"""
import json
import math
from collections import defaultdict
from pathlib import Path

DATA_DIR      = Path("data")
SUB_PATH      = DATA_DIR / "substitutions.jsonl"
CROSSREF_PATH = DATA_DIR / "crossref.json"
STATS_PATH    = DATA_DIR / "crossref_stats.json"

# Normalisation map for common ingredient name variants
INGREDIENT_ALIASES = {
    "butter milk": "buttermilk",
    "sour cream": "sour cream",
    "lard": "lard",
    "dripping": "dripping",
    "drippings": "dripping",
    "beef dripping": "dripping",
    "cream": "cream",
    "double cream": "cream",
    "single cream": "cream",
    "flour": "flour",
    "plain flour": "flour",
    "all-purpose flour": "flour",
    "corn starch": "cornstarch",
    "corn flour": "cornstarch",
    "bi-carbonate of soda": "bicarbonate of soda",
    "bicarb": "bicarbonate of soda",
    "baking soda": "bicarbonate of soda",
    "treacle": "molasses",
    "black treacle": "molasses",
    "suet": "suet",
    "beef suet": "suet",
    "shortening": "shortening",
    "vegetable shortening": "shortening",
    "eggs": "egg",
    "egg yolks": "egg yolk",
    "egg whites": "egg white",
    "milk": "milk",
    "whole milk": "milk",
    "fresh milk": "milk",
    "salt pork": "salt pork",
    "cream of tartar": "cream of tartar",
}


def normalise(name: str) -> str:
    name = name.lower().strip().rstrip("s")  # basic singular
    return INGREDIENT_ALIASES.get(name, INGREDIENT_ALIASES.get(name + "s", name))


def consensus_score(book_count: int, total_citations: int, year_spread: int) -> float:
    """
    Score 0-1 based on:
    - book_count: how many distinct books mention this substitution (diversity)
    - total_citations: raw frequency
    - year_spread: how consistently across time (wider = more reliable)
    Weighted: diversity > frequency > time_spread
    """
    # Normalise each component to 0-1 with soft caps
    diversity  = 1 - math.exp(-book_count / 5)        # saturates ~15 books
    frequency  = 1 - math.exp(-total_citations / 10)  # saturates ~30 citations
    time_score = min(year_spread / 80, 1.0)            # 80 years = max

    return round(0.55 * diversity + 0.30 * frequency + 0.15 * time_score, 3)


def build_crossref():
    if not SUB_PATH.exists():
        print(f"Not found: {SUB_PATH}")
        return

    # Load all records
    records: list[dict] = []
    with SUB_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass

    print(f"Loaded {len(records):,} substitution records")

    # Group by (ingredient, substitute)
    # key: (norm_ingredient, norm_substitute) -> list of records
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in records:
        ing  = normalise(r.get("ingredient", ""))
        sub  = normalise(r.get("substitute", ""))
        if ing and sub and ing != sub:
            groups[(ing, sub)].append(r)

    print(f"Unique (ingredient, substitute) pairs: {len(groups):,}")

    # Build per-ingredient knowledge entries
    by_ingredient: dict[str, list[dict]] = defaultdict(list)

    for (ing, sub), recs in groups.items():
        books      = {r.get("book", "") for r in recs}
        years      = [r.get("year", 0) for r in recs if r.get("year", 0) > 0]
        all_tags   = [tag for r in recs for tag in r.get("diet_tags", [])]
        tag_counts = {}
        for t in all_tags:
            tag_counts[t] = tag_counts.get(t, 0) + 1
        top_tags = [t for t, _ in sorted(tag_counts.items(), key=lambda x: -x[1])[:4]]

        earliest = min(years) if years else 0
        latest   = max(years) if years else 0
        spread   = latest - earliest

        score = consensus_score(len(books), len(recs), spread)

        # Best citations: one per book, prefer those with context
        seen_books = set()
        citations  = []
        for r in sorted(recs, key=lambda x: x.get("year", 9999)):
            b = r.get("book", "")
            if b not in seen_books:
                seen_books.add(b)
                citations.append({
                    "book":    b,
                    "year":    r.get("year", 0),
                    "context": r.get("context", ""),
                    "notes":   r.get("notes", ""),
                })
            if len(citations) >= 5:  # cap at 5 citations per pair
                break

        by_ingredient[ing].append({
            "substitute":       sub,
            "consensus_score":  score,
            "book_count":       len(books),
            "citation_count":   len(recs),
            "earliest_year":    earliest,
            "latest_year":      latest,
            "diet_tags":        top_tags,
            "citations":        citations,
        })

    # Sort each ingredient's substitutes by consensus score desc
    crossref = {}
    for ing, subs in by_ingredient.items():
        subs_sorted = sorted(subs, key=lambda x: -x["consensus_score"])
        all_years   = [s["earliest_year"] for s in subs_sorted if s["earliest_year"] > 0]
        crossref[ing] = {
            "ingredient":     ing,
            "substitutes":    subs_sorted,
            "total_citations": sum(s["citation_count"] for s in subs_sorted),
            "coverage_years": [min(all_years), max(all_years)] if all_years else [],
        }

    # Write crossref.json
    with CROSSREF_PATH.open("w", encoding="utf-8") as f:
        json.dump(crossref, f, ensure_ascii=False, indent=2)

    # Write stats
    all_scores = [s["consensus_score"] for v in crossref.values() for s in v["substitutes"]]
    high_conf  = sum(1 for s in all_scores if s >= 0.7)
    med_conf   = sum(1 for s in all_scores if 0.4 <= s < 0.7)
    low_conf   = sum(1 for s in all_scores if s < 0.4)

    top_ingredients = sorted(
        crossref.items(),
        key=lambda x: -x[1]["total_citations"]
    )[:20]

    stats = {
        "total_ingredients":     len(crossref),
        "total_substitute_pairs": len(groups),
        "total_citations":        len(records),
        "confidence_breakdown":   {"high": high_conf, "medium": med_conf, "low": low_conf},
        "top_ingredients":        [
            {"ingredient": k, "citations": v["total_citations"], "substitutes": len(v["substitutes"])}
            for k, v in top_ingredients
        ],
    }
    with STATS_PATH.open("w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    print(f"\nCross-reference built:")
    print(f"  Ingredients indexed : {len(crossref):,}")
    print(f"  Substitute pairs    : {len(groups):,}")
    print(f"  High confidence (≥0.7): {high_conf}")
    print(f"  Medium (0.4-0.7)       : {med_conf}")
    print(f"  Low (<0.4)             : {low_conf}")
    print(f"\nTop 10 most-cited ingredients:")
    for k, v in top_ingredients[:10]:
        best = v["substitutes"][0] if v["substitutes"] else {}
        print(f"  {k:25s}  {v['total_citations']:4d} citations  "
              f"best: {best.get('substitute','?')} (score {best.get('consensus_score',0)})")
    print(f"\nSaved → {CROSSREF_PATH}")
    print(f"Stats  → {STATS_PATH}")


if __name__ == "__main__":
    build_crossref()
