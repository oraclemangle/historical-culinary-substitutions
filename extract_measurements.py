"""
Second extraction pass — pulls two more data types from the cookbook corpus:

  1. Historical measurements → modern equivalents
     e.g. "gill" → "142ml / ½ cup"

  2. Cooking terms / techniques → modern explanation
     e.g. "larding" → "threading strips of fat through lean meat with a larding needle"

Output:
  data/measurements.jsonl
  data/terms.jsonl

Run after extract_substitutions.py. Appends only new books (--append flag).
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

CREDENTIALS_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
PROJECT_ID       = os.getenv("GCP_PROJECT_ID", "")
LOCATION         = "us-central1"
GEMINI_MODEL     = "publishers/google/models/gemini-2.5-flash"

BOOKS_DIR  = Path("books")
DATA_DIR   = Path("data")
DATA_DIR.mkdir(exist_ok=True)
META_PATH  = DATA_DIR / "book_meta.json"

MEAS_PATH  = DATA_DIR / "measurements.jsonl"
TERMS_PATH = DATA_DIR / "terms.jsonl"

CHUNK_CHARS  = 50_000
CHUNK_OVERLAP = 2_000
MAX_WORKERS  = 4

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

MEASUREMENT_PROMPT = """\
You are an expert in historical culinary measurements.

From the cookbook text below, extract every historical measurement unit or quantity term that appears.
For each, provide its modern equivalent.

Return a JSON array. Each item must have:
  "term"        : the historical measurement (e.g. "gill", "wine-glass", "pennyweight")
  "modern_ml"   : equivalent in millilitres as a number, or null if not liquid
  "modern_g"    : equivalent in grams as a number, or null if not weight
  "modern_cups" : equivalent in cups as a string (e.g. "½ cup"), or null
  "context"     : exact quoted phrase showing the term in use (max 120 chars)
  "notes"       : any variation or caveat, or empty string

Return ONLY the JSON array. If none found, return [].

TEXT:
{text}
"""

TERMS_PROMPT = """\
You are a culinary historian.

From the cookbook text below, extract every historical cooking term, technique, or piece of equipment
that a modern reader might not understand.

Return a JSON array. Each item must have:
  "term"        : the historical word or phrase (lowercase)
  "explanation" : clear modern explanation (1-2 sentences)
  "modern_equiv": the modern equivalent tool, technique or ingredient (or empty string)
  "context"     : exact quoted phrase from the text (max 120 chars)

Return ONLY the JSON array. If none found, return [].

TEXT:
{text}
"""


def load_year_map() -> dict[str, int]:
    meta: dict[str, int] = dict(YEAR_MAP)
    if META_PATH.exists():
        try:
            stored = json.loads(META_PATH.read_text(encoding="utf-8"))
            meta.update({k: int(v) for k, v in stored.items() if v})
        except Exception:
            pass
    return meta


def make_client():
    creds = service_account.Credentials.from_service_account_file(
        CREDENTIALS_PATH,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    return genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION, credentials=creds)


def strip_gutenberg(text: str) -> str:
    start = re.search(r"\*\*\* START OF.*?\*\*\*", text, re.IGNORECASE)
    end   = re.search(r"\*\*\* END OF.*?\*\*\*",   text, re.IGNORECASE)
    if start: text = text[start.end():]
    if end:   text = text[:end.start()]
    return text.strip()


def chunks(text: str) -> list[str]:
    step = CHUNK_CHARS - CHUNK_OVERLAP
    return [text[i: i + CHUNK_CHARS] for i in range(0, len(text), step)]


def call_gemini(client, prompt: str) -> list[dict]:
    for attempt in range(3):
        try:
            r = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=8192,
                    response_mime_type="application/json",
                ),
            )
            result = json.loads(r.text.strip())
            return result if isinstance(result, list) else []
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt)
    return []


def dedup(items: list[dict], key_field: str) -> list[dict]:
    seen, out = set(), []
    for item in items:
        k = item.get(key_field, "").lower()
        if k and k not in seen:
            seen.add(k)
            out.append(item)
    return out


def extract_book(path: Path, client, year_map: dict | None = None) -> tuple[list[dict], list[dict]]:
    name       = path.stem
    year       = (year_map or YEAR_MAP).get(name, 0)
    book_label = name.replace("_", " ").title()

    raw    = path.read_text(encoding="utf-8", errors="replace")
    text   = strip_gutenberg(raw)
    cks    = chunks(text)

    all_meas: list[dict] = []
    all_terms: list[dict] = []

    for chunk in cks:
        for item in call_gemini(client, MEASUREMENT_PROMPT.format(text=chunk)):
            if item.get("term"):
                item.update(book=book_label, year=year, source_file=name)
                all_meas.append(item)
        for item in call_gemini(client, TERMS_PROMPT.format(text=chunk)):
            if item.get("term") and item.get("explanation"):
                item.update(book=book_label, year=year, source_file=name)
                all_terms.append(item)

    meas  = dedup(all_meas,  "term")
    terms = dedup(all_terms, "term")
    print(f"  {book_label} ({year}): {len(meas)} measurements, {len(terms)} terms")
    return meas, terms


def already_done(path: Path) -> set[str]:
    done = set()
    if path.exists():
        with path.open() as f:
            for line in f:
                try:
                    done.add(json.loads(line).get("source_file", ""))
                except Exception:
                    pass
    return done


def main():
    import sys
    append = "--append" in sys.argv

    txt_files = sorted(BOOKS_DIR.glob("*.txt"))
    if append:
        done = already_done(MEAS_PATH) | already_done(TERMS_PATH)
        txt_files = [p for p in txt_files if p.stem not in done]
        print(f"Append mode: {len(txt_files)} books to process\n")
    else:
        print(f"Processing {len(txt_files)} books\n")

    if not txt_files:
        print("Nothing new to process.")
        return

    client   = make_client()
    year_map = load_year_map()

    # Ensure output files exist for appending
    for p in (MEAS_PATH, TERMS_PATH):
        if not p.exists():
            p.touch()

    write_lock   = threading.Lock()
    total_meas   = 0
    total_terms  = 0

    def process_and_write(path: Path) -> tuple[int, int]:
        nonlocal total_meas, total_terms
        meas, terms = extract_book(path, client, year_map)
        if meas or terms:
            with write_lock:
                with MEAS_PATH.open("a",  encoding="utf-8") as fm:
                    for m in meas:  fm.write(json.dumps(m,  ensure_ascii=False) + "\n")
                with TERMS_PATH.open("a", encoding="utf-8") as ft:
                    for t in terms: ft.write(json.dumps(t, ensure_ascii=False) + "\n")
                total_meas  += len(meas)
                total_terms += len(terms)
        return len(meas), len(terms)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(process_and_write, p): p for p in txt_files}
        done = 0
        for fut in as_completed(futures):
            done += 1
            nm, nt = fut.result()
            print(f"  [{done}/{len(txt_files)}] +{nm} meas +{nt} terms  (totals: {total_meas}/{total_terms})", flush=True)

    print(f"\nMeasurements: {total_meas} → {MEAS_PATH}")
    print(f"Terms:        {total_terms} → {TERMS_PATH}")


if __name__ == "__main__":
    main()
