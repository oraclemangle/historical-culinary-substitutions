"""
Self-updating pipeline — run this to keep the corpus fresh.

What it does:
  1. Downloads any new public-domain cookbooks from Internet Archive
  2. Extracts substitutions from new books only (appends, never re-processes)
  3. Rebuilds the FAISS index

Usage:
  python update.py           # full update
  python update.py --check   # just report what's new, don't download
"""
import subprocess
import sys
import json
import time
from pathlib import Path

DATA_DIR  = Path("data")
BOOKS_DIR = Path("books")


def count_books() -> int:
    return len(list(BOOKS_DIR.glob("*.txt")))


def count_substitutions() -> int:
    p = DATA_DIR / "substitutions.jsonl"
    if not p.exists():
        return 0
    return sum(1 for _ in p.open())


def already_extracted() -> set[str]:
    p = DATA_DIR / "substitutions.jsonl"
    done = set()
    if p.exists():
        with p.open() as f:
            for line in f:
                try:
                    done.add(json.loads(line).get("source_file", ""))
                except Exception:
                    pass
    return done


def run(cmd: list[str], label: str) -> bool:
    print(f"\n{'─'*60}")
    print(f"  {label}")
    print(f"{'─'*60}")
    result = subprocess.run([sys.executable] + cmd)
    return result.returncode == 0


def main():
    check_only = "--check" in sys.argv
    start = time.time()

    before_books = count_books()
    before_subs  = count_substitutions()

    print(f"\nCookbook Oracle — Update Pipeline")
    print(f"Books in corpus : {before_books}")
    print(f"Substitutions   : {before_subs:,}")

    if check_only:
        print("\n--check mode: run without --check to apply updates.")
        return

    # ── Step 1: Download new books ────────────────────────────────────────────
    ok = run(["download_archive.py"], "Step 1/3 — Downloading new books from Internet Archive")
    if not ok:
        print("Download step failed — aborting.")
        return

    after_books = count_books()
    new_books   = after_books - before_books
    print(f"\n  +{new_books} new books ({after_books} total)")

    # ── Step 2: Extract substitutions from new books only ─────────────────────
    new_unextracted = [
        p for p in BOOKS_DIR.glob("*.txt")
        if p.stem not in already_extracted()
    ]

    if not new_unextracted:
        print("\nNo new books to extract — index is up to date.")
    else:
        print(f"\n  {len(new_unextracted)} books need extraction")
        ok = run(
            ["extract_substitutions.py", "--append"],
            "Step 2/3 — Extracting substitutions (Gemini 2.5 Flash)",
        )
        if not ok:
            print("Extraction failed — aborting.")
            return

    # ── Step 3: Rebuild index ─────────────────────────────────────────────────
    after_subs = count_substitutions()
    if after_subs > before_subs or new_unextracted:
        run(["build_index.py"],    "Step 3/4 — Rebuilding FAISS index")
        run(["crossref.py"],       "Step 4/4 — Rebuilding cross-reference layer")
        run(["validate_data.py"],  "         — Validating data quality")
    else:
        print("\nIndex already up to date — skipping rebuild.")

    # ── Summary ───────────────────────────────────────────────────────────────
    elapsed = time.time() - start
    after_subs = count_substitutions()

    print(f"\n{'='*60}")
    print(f"  Update complete in {elapsed:.0f}s")
    print(f"  Books        : {before_books} → {count_books()} (+{count_books()-before_books})")
    print(f"  Substitutions: {before_subs:,} → {after_subs:,} (+{after_subs-before_subs:,})")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
