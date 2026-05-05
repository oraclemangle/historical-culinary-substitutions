"""
Download public-domain cookbooks from Internet Archive by searching the IA API.
Finds real identifiers dynamically — no hardcoded guesses.

Targets items that have a _djvu.txt text layer (IA's OCR output).
Saves to books/ alongside Gutenberg books.

Usage:
  python download_archive.py           # download up to TARGET_COUNT books
  python download_archive.py --search  # preview search results only
"""
import json
import sys
import time
from pathlib import Path

import requests
from tqdm import tqdm

BOOKS_DIR  = Path("books")
DATA_DIR   = Path("data")
BOOKS_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

META_PATH    = DATA_DIR / "book_meta.json"
OCR_LOG      = DATA_DIR / "ocr_needed.txt"
HEADERS      = {"User-Agent": "CookbookOracle/0.1 (educational, local use)"}
IA_BASE      = "https://archive.org"
TARGET_COUNT = 35   # how many to download

# IA search queries — run in sequence until we have enough
SEARCH_QUERIES = [
    'subject:"Cooking" AND mediatype:texts AND language:English AND date:[1700 TO 1929]',
    'subject:"Cookery" AND mediatype:texts AND language:English AND date:[1700 TO 1929]',
    'subject:"recipes" AND mediatype:texts AND language:English AND date:[1800 TO 1929]',
    'title:(cookbook OR cookery OR "cook book") AND mediatype:texts AND language:English AND date:[1800 TO 1929]',
]


def ia_search(query: str, rows: int = 100) -> list[dict]:
    """Search IA and return list of {identifier, title, date} dicts."""
    url = "https://archive.org/advancedsearch.php"
    params = {
        "q":       query,
        "fl[]":    ["identifier", "title", "date"],
        "rows":    rows,
        "page":    1,
        "output":  "json",
        "sort[]":  "downloads desc",
    }
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
        docs = r.json().get("response", {}).get("docs", [])
        return docs
    except Exception as e:
        print(f"  Search error: {e}")
        return []


def has_text_file(identifier: str) -> str | None:
    """
    Check IA file list for a _djvu.txt or .txt file.
    Returns the filename or None.
    """
    url = f"{IA_BASE}/metadata/{identifier}/files"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        files = r.json().get("result", [])
        # Prefer _djvu.txt (IA's structured OCR)
        djvu = [f["name"] for f in files if f["name"].endswith("_djvu.txt")]
        if djvu:
            return djvu[0]
        txts = [f["name"] for f in files
                if f["name"].endswith(".txt") and "meta" not in f["name"].lower()]
        return txts[0] if txts else None
    except Exception:
        return None


NOISE_WORDS = {
    "stove", "range", "appliance", "catalog", "catalogue", "magazine",
    "journal", "advertising", "advertisement", "almanac", "directory",
    "annual", "monthly", "weekly", "gas", "patent", "specification",
    "godey", "peterson", "photoplay", "jewel", "majestic", "excelsior",
    "borden", "milk", "cocoa", "chocolate",  # product promo booklets
}

def is_cookbook(title: str) -> bool:
    """Return False for obvious non-cookbook items."""
    low = title.lower()
    return not any(w in low for w in NOISE_WORDS)


def safe_name(title: str, identifier: str) -> str:
    """Turn a title into a safe filename stem."""
    import re
    name = title.lower()
    name = re.sub(r"[^a-z0-9\s]", "", name)
    name = re.sub(r"\s+", "_", name.strip())
    name = name[:50]
    return name or identifier[:40]


def download_book(identifier: str, text_file: str, name: str) -> bool:
    dest = BOOKS_DIR / f"{name}.txt"
    if dest.exists():
        return True  # already have it
    url = f"{IA_BASE}/download/{identifier}/{text_file}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=60)
        r.raise_for_status()
        dest.write_bytes(r.content)
        return True
    except Exception as e:
        print(f"  download error {name}: {e}")
        return False


def already_downloaded() -> set[str]:
    return {p.stem for p in BOOKS_DIR.glob("*.txt")}


def load_meta() -> dict:
    if META_PATH.exists():
        return json.loads(META_PATH.read_text(encoding="utf-8"))
    return {}


def save_meta(meta: dict):
    META_PATH.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    preview = "--search" in sys.argv

    existing = already_downloaded()
    print(f"Already have {len(existing)} books in books/")
    need = TARGET_COUNT - max(0, len(existing) - 15)  # don't count the 15 Gutenberg ones
    if need <= 0 and not preview:
        print("Already have enough IA books.")
        return

    print(f"Searching Internet Archive for {need} more cookbooks...\n")

    candidates: list[dict] = []
    seen_ids = set()

    for query in SEARCH_QUERIES:
        if len(candidates) >= need * 3:  # gather 3x so we have fallbacks
            break
        results = ia_search(query, rows=100)
        for doc in results:
            iid = doc.get("identifier", "")
            if iid and iid not in seen_ids:
                seen_ids.add(iid)
                candidates.append(doc)
        time.sleep(0.5)

    print(f"Found {len(candidates)} candidate items, checking for text layers...\n")

    meta = load_meta()
    downloaded = 0
    checked    = 0

    for doc in tqdm(candidates, desc="Checking"):
        if downloaded >= need:
            break
        checked += 1

        iid   = doc.get("identifier", "")
        title = doc.get("title", iid)
        year_str = str(doc.get("date", ""))[:4]

        # Skip obvious non-cookbook items
        if not is_cookbook(title):
            continue

        # Skip if we clearly already have this
        name = safe_name(title, iid)
        if name in existing:
            continue

        text_file = has_text_file(iid)
        time.sleep(0.3)

        if not text_file:
            with OCR_LOG.open("a") as f:
                f.write(f"{iid}\t{title}\tno_text_layer\n")
            continue

        if preview:
            print(f"  [{year_str}] {title[:60]}  →  {iid}")
            downloaded += 1
            continue

        ok = download_book(iid, text_file, name)
        if ok:
            kb = (BOOKS_DIR / f"{name}.txt").stat().st_size // 1024
            print(f"  ok  [{year_str}] {title[:55]}  ({kb} KB)")
            # Persist year metadata so extract_substitutions.py can look it up
            try:
                meta[name] = int(year_str)
            except (ValueError, TypeError):
                pass
            downloaded += 1

    if not preview:
        save_meta(meta)
        total = len(list(BOOKS_DIR.glob("*.txt")))
        print(f"\nDone: {downloaded} new IA books downloaded")
        print(f"Total books in corpus: {total}")


if __name__ == "__main__":
    main()
