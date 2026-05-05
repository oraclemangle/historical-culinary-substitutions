"""
Build unified FAISS index from all extracted data:
  data/substitutions.jsonl  — ingredient swaps
  data/measurements.jsonl   — historical measurements (optional)
  data/terms.jsonl          — cooking terms (optional)

Each record becomes a rich embedding string tagged with its type so
the API can retrieve across all data types in one query.

Output:
  data/sub_index.faiss
  data/sub_records.npy
"""
import json
import numpy as np
from pathlib import Path
from sentence_transformers import SentenceTransformer
import faiss

try:
    from ingredient_parser import parse_ingredient as _parse_ing
    _PARSER_AVAILABLE = True
except ImportError:
    _PARSER_AVAILABLE = False

DATA_DIR     = Path("data")
IN_PATHS     = {
    "substitute": DATA_DIR / "substitutions.jsonl",
    "convert":    DATA_DIR / "measurements.jsonl",
    "explain":    DATA_DIR / "terms.jsonl",
}
INDEX_PATH   = DATA_DIR / "sub_index.faiss"
RECORDS_PATH = DATA_DIR / "sub_records.npy"

EMBED_MODEL  = "jonny9f/food_embeddings2"   # 768-dim food-domain model


def enrich_record(r: dict) -> dict:
    """Add parsed ingredient/substitute fields using ingredient-parser-nlp."""
    if not _PARSER_AVAILABLE:
        return r
    for field in ("ingredient", "substitute"):
        val = r.get(field, "")
        if not val or len(val) > 80:
            continue
        try:
            parsed = _parse_ing(val)
            names = [n.text for n in (parsed.name or [])]
            if names:
                r[f"parsed_{field}_name"] = " ".join(names)
            if parsed.amount:
                amt = parsed.amount[0]
                r[f"parsed_{field}_quantity"] = str(amt.quantity)
                r[f"parsed_{field}_unit"] = str(amt.unit)
            if parsed.preparation:
                r[f"parsed_{field}_prep"] = parsed.preparation.text
        except Exception:
            pass
    return r


def record_to_text(r: dict, rtype: str) -> str:
    """Convert any record type to a rich searchable string."""
    year = r.get("year", "")
    if rtype == "substitute":
        parts = [
            f"[{year}] ingredient substitution:",
            f"{r.get('ingredient', '')} substitute: {r.get('substitute', '')}.",
            r.get("context", ""), r.get("notes", ""),
        ]
        tags = r.get("diet_tags", [])
        if tags:
            parts.append("Tags: " + ", ".join(tags))
    elif rtype == "convert":
        parts = [
            f"[{year}] historical measurement:",
            f"{r.get('term', '')} equals {r.get('modern_ml', '')}ml"
            f" / {r.get('modern_cups', '')} cups / {r.get('modern_g', '')}g.",
            r.get("context", ""), r.get("notes", ""),
        ]
    else:  # explain
        parts = [
            f"[{year}] cooking term:",
            f"{r.get('term', '')}: {r.get('explanation', '')}",
            f"Modern equivalent: {r.get('modern_equiv', '')}",
            r.get("context", ""),
        ]
    return " ".join(p for p in parts if p)


def load_jsonl(path: Path, rtype: str) -> list[dict]:
    records = []
    if not path.exists():
        return records
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    r = json.loads(line)
                    r["_type"] = rtype
                    records.append(r)
                except json.JSONDecodeError:
                    pass
    return records


def build():
    all_records: list[dict] = []
    for rtype, path in IN_PATHS.items():
        recs = load_jsonl(path, rtype)
        print(f"  {rtype:12s}: {len(recs):,} records  ({path.name})")
        all_records.extend(recs)

    if _PARSER_AVAILABLE:
        print(f"Enriching records with ingredient-parser-nlp...")
        all_records = [enrich_record(r) for r in all_records]

    if not all_records:
        print("No data found — run extraction scripts first.")
        return

    print(f"\nTotal records: {len(all_records):,}")

    texts = [record_to_text(r, r["_type"]) for r in all_records]

    print(f"Embedding with {EMBED_MODEL}...")
    model = SentenceTransformer(EMBED_MODEL)
    embeddings = model.encode(
        texts,
        batch_size=128,
        show_progress_bar=True,
        convert_to_numpy=True,
    ).astype(np.float32)

    print("Building FAISS index...")
    dim   = embeddings.shape[1]
    index = faiss.IndexFlatL2(dim)
    index.add(embeddings)

    faiss.write_index(index, str(INDEX_PATH))
    np.save(str(RECORDS_PATH), np.array(all_records, dtype=object))

    print(f"\nIndex  → {INDEX_PATH}  ({index.ntotal} vectors)")
    print(f"Records→ {RECORDS_PATH}")

    # Stats by type
    by_type: dict[str, int] = {}
    by_book: dict[str, int] = {}
    for r in all_records:
        by_type[r["_type"]] = by_type.get(r["_type"], 0) + 1
        by_book[r.get("book", "?")] = by_book.get(r.get("book", "?"), 0) + 1
    print("\nRecords by type:")
    for t, n in by_type.items():
        print(f"  {n:5,}  {t}")
    print("\nTop 5 books by record count:")
    for book, count in sorted(by_book.items(), key=lambda x: -x[1])[:5]:
        print(f"  {count:5,}  {book}")


if __name__ == "__main__":
    build()
