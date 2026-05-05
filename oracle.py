"""
Cookbook Substitution Oracle — CLI query tool.

Usage:
  python oracle.py "What can I use instead of buttermilk in a 1900s biscuit?"
  python oracle.py  (interactive mode)

Requires:
  data/cookbook_index.faiss
  data/chunks.npy
  data/meta.npy
  LM Studio running at http://127.0.0.1:1234 with liquid/lfm2.5-1.2b loaded
"""
import sys
import numpy as np
import faiss
from pathlib import Path
from sentence_transformers import SentenceTransformer
from openai import OpenAI

DATA_DIR      = Path("data")
# Substitution index (preferred — built by build_index.py)
SUB_INDEX_PATH   = DATA_DIR / "sub_index.faiss"
SUB_RECORDS_PATH = DATA_DIR / "sub_records.npy"
# Raw text index fallback (built by pipeline.py)
INDEX_PATH    = DATA_DIR / "cookbook_index.faiss"
CHUNKS_PATH   = DATA_DIR / "chunks.npy"
META_PATH     = DATA_DIR / "meta.npy"

EMBED_MODEL  = "all-MiniLM-L6-v2"
LM_STUDIO_URL = "http://127.0.0.1:1234/v1"
LLM_MODEL    = "liquid/lfm2.5-1.2b"
TOP_K        = 5

SYSTEM_PROMPT = (
    "You are a precise historical cookbook substitution oracle. "
    "Answer only from the provided context excerpts. "
    "If a substitution is mentioned, cite the book name and year. "
    "If the context doesn't contain a clear answer, say so honestly. "
    "Keep answers concise and practical."
)

DEMO_QUERIES = [
    "What can replace buttermilk in a biscuit recipe?",
    "What substitutes for lard in pastry?",
    "How do I replace eggs in old cake recipes?",
    "What can I use instead of cream of tartar?",
    "Substitute for molasses in old recipes?",
    "What replaces suet in pudding?",
    "Can I swap cornstarch for flour as a thickener?",
    "What did Victorian cooks use instead of baking powder?",
    "Substitute for salt pork in old American recipes?",
    "What replaces shortening in Depression-era baking?",
]


def load_index():
    # Prefer substitution index; fall back to raw text index
    if SUB_INDEX_PATH.exists() and SUB_RECORDS_PATH.exists():
        index   = faiss.read_index(str(SUB_INDEX_PATH))
        records = np.load(str(SUB_RECORDS_PATH), allow_pickle=True)
        print(f"Using substitution index ({index.ntotal} records)")
        return index, records, "sub"
    elif INDEX_PATH.exists():
        index  = faiss.read_index(str(INDEX_PATH))
        chunks = np.load(str(CHUNKS_PATH), allow_pickle=True)
        meta   = np.load(str(META_PATH),   allow_pickle=True)
        print("Using raw text index (run build_index.py for better results)")
        return index, (chunks, meta), "raw"
    else:
        sys.exit("No index found. Run extract_substitutions.py then build_index.py.")


def retrieve(query: str, model, index, data, mode: str, k: int = TOP_K):
    q_emb = model.encode([query]).astype(np.float32)
    _, idx = index.search(q_emb, k)
    results = []
    if mode == "sub":
        records = data
        for i in idx[0]:
            r = records[i]
            chunk = (
                f"[{r.get('book', '')} ({r.get('year', '')})]\n"
                f"{r.get('ingredient', '')} → {r.get('substitute', '')}\n"
                f"Context: {r.get('context', '')}\n"
                f"Notes: {r.get('notes', '')}"
            )
            results.append(chunk)
    else:
        chunks, meta = data
        for i in idx[0]:
            book, year = meta[i]
            results.append(f"[{book.replace('_', ' ').title()} ({year})]\n{chunks[i]}")
    return results


def ask_llm(client: OpenAI, query: str, context_chunks: list[str]) -> str:
    context = "\n\n---\n\n".join(context_chunks)
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": f"Context:\n{context}\n\nQuestion: {query}"},
        ],
        temperature=0.2,
        max_tokens=300,
    )
    return response.choices[0].message.content.strip()


def query_oracle(query: str, model, index, chunks, meta, client: OpenAI) -> str:
    hits    = retrieve(query, model, index, chunks, meta)
    answer  = ask_llm(client, query, hits)
    return answer


def main():
    print("Loading index and models...")
    index, data, mode = load_index()
    embed_model = SentenceTransformer(EMBED_MODEL)
    client      = OpenAI(base_url=LM_STUDIO_URL, api_key="lm-studio")

    def run_query(q: str) -> str:
        hits   = retrieve(q, embed_model, index, data, mode)
        return ask_llm(client, q, hits)

    # Single query from CLI args
    if len(sys.argv) > 1:
        q = " ".join(sys.argv[1:])
        print(f"\nQ: {q}\nA: {run_query(q)}\n")
        return

    # Demo / interactive mode
    choice = input("Run [d]emo queries or [i]nteractive mode? (d/i): ").strip().lower()
    if choice == "d":
        print(f"\nRunning {len(DEMO_QUERIES)} demo queries...\n{'='*60}")
        for q in DEMO_QUERIES:
            print(f"\nQ: {q}")
            print(f"A: {run_query(q)}")
            print("-" * 60)
        return

    print("\nCookbook Oracle ready. Type your question (or 'quit').\n")
    while True:
        try:
            q = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q or q.lower() in {"quit", "exit", "q"}:
            break
        print(f"Oracle: {run_query(q)}\n")


if __name__ == "__main__":
    main()
