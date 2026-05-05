"""
Pre-extraction pass: feed each cookbook to Gemini 2.5 Flash and pull out
every ingredient substitution mentioned, with source citation.

Each book is split into 50K-char chunks to stay within output token limits.
Results are deduplicated and merged.

Output: data/substitutions.jsonl  (one JSON object per substitution)
"""
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from google import genai
from google.genai import types
from google.oauth2 import service_account

# ── Config ────────────────────────────────────────────────────────────────────
CREDENTIALS_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
PROJECT_ID       = os.getenv("GCP_PROJECT_ID", "")
LOCATION         = "us-central1"
GEMINI_MODEL     = "publishers/google/models/gemini-2.5-flash"

BOOKS_DIR    = Path("books")
DATA_DIR     = Path("data")
DATA_DIR.mkdir(exist_ok=True)
OUT_PATH     = DATA_DIR / "substitutions.jsonl"
META_PATH    = DATA_DIR / "book_meta.json"

CHUNK_CHARS  = 50_000   # chars per Gemini call (~12K tokens input)
CHUNK_OVERLAP = 2_000   # overlap so substitutions aren't split across chunks
MAX_WORKERS  = 4        # parallel book workers

YEAR_MAP = {
    "boston_cooking_school":      1896,
    "white_house_cook_book":      1887,
    "mrs_beetons_household":      1861,
    "the_jewish_manual":          1846,
    "directions_for_cookery":     1837,
    "miss_parloas_new_cook_book": 1880,
    "plain_cookery_working":      1852,
    "twenty_five_cent_dinners":   1878,
    "the_cooks_oracle":           1817,
    "mrs_hale_receipts":          1857,
    "marion_harland_complete":    1903,
    "cookery_imperial_rome":      1936,
    "compleat_cook":              1658,
    "housekeeping_old_virginia":  1879,
    "virginia_housewife":         1824,
}

EXTRACTION_PROMPT = """\
You are a culinary historian analysing a section of a public-domain cookbook.

Extract EVERY ingredient substitution, swap, or alternative in the text.
Include explicit ("use X instead of Y") AND implicit ("if you have no cream, milk will do").
Be thorough — include regional, seasonal, and economy substitutions.

Return a JSON array. Each item must have exactly these fields:
  "ingredient"  : original ingredient being replaced (lowercase, singular)
  "substitute"  : what replaces it (lowercase, specific)
  "context"     : exact quoted phrase from the text (max 150 chars)
  "diet_tags"   : array from ["vegan","vegetarian","keto","historical","budget","dairy-free","gluten-free"]
  "notes"       : proportions or caveats, or empty string

Return ONLY the JSON array. No markdown fences. If none found, return [].

TEXT SECTION:
{text}
"""

def load_year_map() -> dict[str, int]:
    """Merge hardcoded YEAR_MAP with book_meta.json (meta takes precedence)."""
    meta: dict[str, int] = dict(YEAR_MAP)
    if META_PATH.exists():
        try:
            stored = json.loads(META_PATH.read_text(encoding="utf-8"))
            meta.update({k: int(v) for k, v in stored.items() if v})
        except Exception:
            pass
    return meta


# ── Auth ──────────────────────────────────────────────────────────────────────
def make_client() -> genai.Client:
    creds = service_account.Credentials.from_service_account_file(
        CREDENTIALS_PATH,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    return genai.Client(
        vertexai=True,
        project=PROJECT_ID,
        location=LOCATION,
        credentials=creds,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────
def strip_gutenberg(text: str) -> str:
    start = re.search(r"\*\*\* START OF.*?\*\*\*", text, re.IGNORECASE)
    end   = re.search(r"\*\*\* END OF.*?\*\*\*",   text, re.IGNORECASE)
    if start:
        text = text[start.end():]
    if end:
        text = text[:end.start()]
    return text.strip()


def text_chunks(text: str) -> list[str]:
    """Split text into overlapping chunks."""
    chunks = []
    step = CHUNK_CHARS - CHUNK_OVERLAP
    for i in range(0, len(text), step):
        chunks.append(text[i : i + CHUNK_CHARS])
    return chunks


def call_gemini(client: genai.Client, text: str) -> list[dict]:
    """Single Gemini call for one chunk. Returns parsed list."""
    for attempt in range(3):
        try:
            r = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=EXTRACTION_PROMPT.format(text=text),
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=16384,
                    response_mime_type="application/json",
                ),
            )
            result = json.loads(r.text.strip())
            return result if isinstance(result, list) else []
        except json.JSONDecodeError:
            # Truncated — return what we can parse from partial JSON
            try:
                partial = r.text.strip()
                # Find last complete object
                last_close = partial.rfind("},")
                if last_close > 0:
                    return json.loads(partial[: last_close + 1] + "]")
            except Exception:
                pass
            return []
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                print(f"    chunk failed after 3 attempts: {e}")
    return []


def dedup(pairs: list[dict]) -> list[dict]:
    """Remove duplicate (ingredient, substitute) pairs, keeping first seen."""
    seen = set()
    out  = []
    for p in pairs:
        key = (p.get("ingredient", "").lower(), p.get("substitute", "").lower())
        if key not in seen and key[0] and key[1]:
            seen.add(key)
            out.append(p)
    return out


# ── Per-book extraction ───────────────────────────────────────────────────────
def extract_book(path: Path, client: genai.Client, year_map: dict[str, int] | None = None) -> list[dict]:
    name       = path.stem
    year       = (year_map or YEAR_MAP).get(name, 0)
    book_label = name.replace("_", " ").title()

    raw    = path.read_text(encoding="utf-8", errors="replace")
    text   = strip_gutenberg(raw)
    chunks = text_chunks(text)

    print(f"  {book_label}: {len(text):,} chars → {len(chunks)} chunks")

    all_pairs: list[dict] = []
    for i, chunk in enumerate(chunks):
        pairs = call_gemini(client, chunk)
        for p in pairs:
            if p.get("ingredient") and p.get("substitute"):
                p["book"]        = book_label
                p["year"]        = year
                p["source_file"] = name
                all_pairs.append(p)

    deduped = dedup(all_pairs)
    print(f"  {book_label} ({year}): {len(deduped)} unique substitutions "
          f"(from {len(all_pairs)} raw across {len(chunks)} chunks)")
    return deduped


# ── Main ──────────────────────────────────────────────────────────────────────
def already_extracted() -> set[str]:
    """Return set of source_file stems already in substitutions.jsonl."""
    done = set()
    if OUT_PATH.exists():
        with OUT_PATH.open(encoding="utf-8") as f:
            for line in f:
                try:
                    done.add(json.loads(line).get("source_file", ""))
                except Exception:
                    pass
    return done


def main():
    import sys
    append_mode = "--append" in sys.argv

    txt_files = sorted(BOOKS_DIR.glob("*.txt"))
    if not txt_files:
        print("No books found — run download_books.py first.")
        return

    if append_mode:
        done = already_extracted()
        txt_files = [p for p in txt_files if p.stem not in done]
        print(f"Append mode: {len(txt_files)} new books to extract\n")
    else:
        print(f"Extracting from {len(txt_files)} books with {GEMINI_MODEL}\n")

    if not txt_files:
        print("Nothing new to extract.")
        return

    client    = make_client()
    year_map  = load_year_map()

    # Write lock for incremental, thread-safe appending
    write_lock = threading.Lock()
    total_new  = 0

    def process_and_write(path: Path) -> int:
        nonlocal total_new
        pairs = extract_book(path, client, year_map)
        if pairs:
            with write_lock:
                with OUT_PATH.open("a", encoding="utf-8") as f:
                    for p in pairs:
                        f.write(json.dumps(p, ensure_ascii=False) + "\n")
                total_new += len(pairs)
        return len(pairs)

    # Ensure file exists for appending
    if not OUT_PATH.exists():
        OUT_PATH.touch()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(process_and_write, p): p for p in txt_files}
        done = 0
        for fut in as_completed(futures):
            done += 1
            count = fut.result()
            print(f"  [{done}/{len(txt_files)}] +{count} substitutions  (total new: {total_new})", flush=True)

    print(f"\nExtracted: {total_new} new substitutions")
    print(f"Appended → {OUT_PATH}")


if __name__ == "__main__":
    main()
