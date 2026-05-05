"""
Bulk Gutenberg cookbook downloader.
Parses the official Gutenberg catalog CSV to find all cooking/cookery books,
then downloads plain text files for any not already in books/.

Gutenberg catalog: https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv
~70,000 books total; ~600-700 match cooking subjects.

Usage:
  python download_gutenberg_bulk.py           # download all found
  python download_gutenberg_bulk.py --list    # preview only
  python download_gutenberg_bulk.py --limit 50  # download first N
"""
import csv
import io
import json
import re
import sys
import time
from pathlib import Path

import requests
from tqdm import tqdm

BOOKS_DIR    = Path("books")
DATA_DIR     = Path("data")
BOOKS_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

META_PATH    = DATA_DIR / "book_meta.json"
CATALOG_URL  = "https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv"
TEXT_URL     = "https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt"
HEADERS      = {"User-Agent": "CookbookOracle/0.1 (educational, local use)"}

# Subject keywords that indicate a cookbook
COOKING_SUBJECTS = {
    "cooking", "cookery", "recipes", "recipe", "baking",
    "confectionery", "pastry", "bread", "household management",
    "domestic economy", "housekeeping", "gastronomy",
    "food", "nutrition", "diet", "menus",
}

# Subjects to skip even if they match cooking
SKIP_SUBJECTS = {
    "fiction", "novel", "poetry", "drama", "periodicals",
    "biography", "autobiography", "travel", "history",
}

# Title keywords that indicate NOT a cookbook despite matching subjects
SKIP_TITLE_WORDS = {
    "captain cook", "captain james cook", "james cook", "journal", "voyage",
    "fairy", "tales", "grimm", "doctor", "medical", "health", "solar cooler",
    "political", "essays", "philosophy", "domestic problem", "maintaining health",
    "narrative", "biography", "life of", "history of", "death of",
}

# Title must contain at least one of these for title-only matches
# (prevents "cook" in an author's name from triggering a match)
REQUIRE_TITLE_WORDS = {
    "cook book", "cookbook", "cookery", "recipe", "recipes",
    "household", "housewife", "baking", "pastry", "confectionery",
    "culinary", "cuisine", "gastronomy", "domestic cookery", "menu",
}


def is_cooking_book(row: dict) -> bool:
    subjects = row.get("Subjects", "").lower()
    title    = row.get("Title", "").lower()
    language = row.get("Language", "")

    # English only
    if "en" not in language.lower():
        return False

    # Must be text type
    if row.get("Type", "") != "Text":
        return False

    # Check subjects
    has_cooking = any(kw in subjects for kw in COOKING_SUBJECTS)
    has_skip    = any(kw in subjects for kw in SKIP_SUBJECTS)

    # For title-only matches, require stronger cooking keywords (not just "cook")
    title_match = any(kw in title for kw in REQUIRE_TITLE_WORDS)

    skip_title = any(kw in title for kw in SKIP_TITLE_WORDS)
    return (has_cooking or title_match) and not has_skip and not skip_title


def safe_name(title: str, book_id: str) -> str:
    name = re.sub(r"[^a-z0-9\s]", "", title.lower())
    name = re.sub(r"\s+", "_", name.strip())[:50]
    return name or f"gutenberg_{book_id}"


def already_downloaded() -> set[str]:
    return {p.stem for p in BOOKS_DIR.glob("*.txt")}


def load_meta() -> dict:
    if META_PATH.exists():
        return json.loads(META_PATH.read_text(encoding="utf-8"))
    return {}


def save_meta(meta: dict):
    META_PATH.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def fetch_catalog() -> list[dict]:
    print("Fetching Gutenberg catalog CSV...")
    r = requests.get(CATALOG_URL, headers=HEADERS, timeout=60)
    r.raise_for_status()
    reader = csv.DictReader(io.StringIO(r.text))
    return list(reader)


def extract_year_from_text(content: bytes) -> int | None:
    """Parse publication year from the first 8KB of a Gutenberg book text."""
    header = content[:8000].decode("utf-8", errors="replace")
    # Look after the *** START *** marker for years on the title page
    start_match = re.search(r"\*\*\* START OF.*?\*\*\*", header, re.IGNORECASE)
    region = header[start_match.end():start_match.end() + 3000] if start_match else header[500:3500]
    years = re.findall(r"\b(1[6-9]\d{2})\b", region)
    years = [int(y) for y in years if 1600 <= int(y) <= 1929]
    return years[0] if years else None


def download_book(book_id: str, name: str) -> tuple[bool, int | None]:
    """Download a book. Returns (success, publication_year_or_None)."""
    dest = BOOKS_DIR / f"{name}.txt"
    if dest.exists():
        year = extract_year_from_text(dest.read_bytes())
        return True, year
    url = TEXT_URL.format(id=book_id)
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        if len(r.content) < 5000:
            return False, None
        dest.write_bytes(r.content)
        year = extract_year_from_text(r.content)
        return True, year
    except Exception:
        return False, None


def main():
    preview = "--list"  in sys.argv
    limit   = None
    for i, arg in enumerate(sys.argv):
        if arg == "--limit" and i + 1 < len(sys.argv):
            limit = int(sys.argv[i + 1])

    rows = fetch_catalog()
    print(f"Catalog loaded: {len(rows):,} total books")

    cooking = [r for r in rows if is_cooking_book(r)]
    print(f"Cooking/cookery books found: {len(cooking)}")

    existing = already_downloaded()
    print(f"Already downloaded: {len(existing)} books\n")

    new_books = []
    for row in cooking:
        book_id = row.get("Text#", "").strip()
        title   = row.get("Title", "").strip()
        issued  = row.get("Issued", "")[:4]   # e.g. "1896"
        if not book_id or not title:
            continue
        name = safe_name(title, book_id)
        if name not in existing:
            new_books.append((book_id, title, name, issued))

    print(f"New books to download: {len(new_books)}")

    if limit:
        new_books = new_books[:limit]
        print(f"Limited to first {limit}")

    if preview:
        print("\nPreview (first 30):")
        for bid, title, name, yr in new_books[:30]:
            print(f"  [{yr or '?'}] {title[:70]}")
        return

    meta = load_meta()
    print()
    ok = fail = 0
    for book_id, title, name, issued in tqdm(new_books, desc="Downloading"):
        success, year = download_book(book_id, name)
        if success:
            ok += 1
            # Prefer year from book text; fall back to nothing (don't use Issued = upload date)
            if year:
                meta[name] = year
        else:
            fail += 1
        time.sleep(0.5)

    save_meta(meta)
    total = len(list(BOOKS_DIR.glob("*.txt")))
    print(f"\nDone: {ok} downloaded, {fail} failed")
    print(f"Total corpus: {total} books")


if __name__ == "__main__":
    main()
