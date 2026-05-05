"""
Build the FAISS index from downloaded cookbook text files.
Run after download_books.py.

Output:
  data/cookbook_index.faiss
  data/chunks.npy
  data/meta.npy   (chunk -> (book_name, year) mapping)
"""
import re
import numpy as np
from pathlib import Path
from tqdm import tqdm
from sentence_transformers import SentenceTransformer
import faiss

BOOKS_DIR  = Path("books")
DATA_DIR   = Path("data")
DATA_DIR.mkdir(exist_ok=True)

INDEX_PATH  = DATA_DIR / "cookbook_index.faiss"
CHUNKS_PATH = DATA_DIR / "chunks.npy"
META_PATH   = DATA_DIR / "meta.npy"

CHUNK_SIZE    = 600   # characters
CHUNK_OVERLAP = 100
EMBED_MODEL   = "all-MiniLM-L6-v2"

# Year map matches download_books.py names
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


def clean_gutenberg(text: str) -> str:
    """Strip Gutenberg header/footer boilerplate."""
    start = re.search(r"\*\*\* START OF.*?\*\*\*", text, re.IGNORECASE)
    end   = re.search(r"\*\*\* END OF.*?\*\*\*",   text, re.IGNORECASE)
    if start:
        text = text[start.end():]
    if end:
        text = text[:end.start()]
    return text.strip()


def chunk_text(text: str) -> list[str]:
    """Split into overlapping chunks, skipping near-empty ones."""
    chunks = []
    step = CHUNK_SIZE - CHUNK_OVERLAP
    for i in range(0, len(text), step):
        chunk = text[i : i + CHUNK_SIZE].strip()
        if len(chunk) > 80:          # skip tiny trailing chunks
            chunks.append(chunk)
    return chunks


def build_index():
    txt_files = sorted(BOOKS_DIR.glob("*.txt"))
    if not txt_files:
        print("No books found — run download_books.py first.")
        return

    print(f"Loading embedding model: {EMBED_MODEL}")
    model = SentenceTransformer(EMBED_MODEL)

    all_chunks: list[str] = []
    all_meta:   list[tuple] = []   # (book_name, year)

    print(f"\nChunking {len(txt_files)} books...")
    for path in tqdm(txt_files):
        raw  = path.read_text(encoding="utf-8", errors="replace")
        text = clean_gutenberg(raw)
        name = path.stem
        year = YEAR_MAP.get(name, 0)
        for chunk in chunk_text(text):
            all_chunks.append(chunk)
            all_meta.append((name, year))

    print(f"Total chunks: {len(all_chunks)}")

    print("\nEmbedding chunks (this takes a minute)...")
    embeddings = model.encode(
        all_chunks,
        batch_size=64,
        show_progress_bar=True,
        convert_to_numpy=True,
    ).astype(np.float32)

    print("Building FAISS index...")
    dim   = embeddings.shape[1]
    index = faiss.IndexFlatL2(dim)
    index.add(embeddings)

    faiss.write_index(index, str(INDEX_PATH))
    np.save(str(CHUNKS_PATH), np.array(all_chunks, dtype=object))
    np.save(str(META_PATH),   np.array(all_meta,   dtype=object))

    print(f"\nIndex saved  → {INDEX_PATH}")
    print(f"Chunks saved → {CHUNKS_PATH}  ({len(all_chunks)} entries)")
    print(f"Meta saved   → {META_PATH}")


if __name__ == "__main__":
    build_index()
