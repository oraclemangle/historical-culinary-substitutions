"""
Old Recipe Intelligence — FastAPI backend

Endpoints:
  POST /v1/substitute        — ingredient substitution
  POST /v1/substitute/batch  — batch substitution for multiple ingredients
  POST /v1/modernise         — rewrite old recipe in modern terms
  POST /v1/convert           — historical measurement conversion
  POST /v1/explain           — cooking term / technique explainer
  GET  /v1/crossref/{ingredient} — full cross-reference entry
  GET  /v1/stats             — corpus statistics
  GET  /v1/health            — status + index stats

Auth: Bearer token via X-API-Key header
Run:
  uvicorn api:app --host 0.0.0.0 --port 8000
"""
import json
import os
import time
from collections import defaultdict
from pathlib import Path
from functools import lru_cache

import numpy as np
import faiss
import requests as http_requests
import google.auth
import google.auth.transport.requests
from fastapi import FastAPI, HTTPException, Security, Depends, Request
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel
from sentence_transformers import SentenceTransformer
from openai import OpenAI

# ── Config ────────────────────────────────────────────────────────────────────
DATA_DIR      = Path("data")
INDEX_PATH    = DATA_DIR / "sub_index.faiss"
RECORDS_PATH  = DATA_DIR / "sub_records.npy"
EMBED_MODEL   = "jonny9f/food_embeddings2"  # 768-dim food-domain model
LM_STUDIO_URL = os.getenv("LLM_BASE_URL",  "http://127.0.0.1:1234/v1")
LLM_MODEL     = os.getenv("LLM_MODEL",     "liquid/lfm2.5-1.2b")
TOP_K         = 6

# ── Vertex AI / Gemini config ─────────────────────────────────────────────────
GCP_PROJECT        = os.getenv("GCP_PROJECT", "")
VERTEX_DATASTORE   = "old-recipe-substitutions"
VERTEX_ENGINE      = "old-recipe-search"
VERTEX_SEARCH_URL  = (
    f"https://discoveryengine.googleapis.com/v1/projects/{GCP_PROJECT}"
    f"/locations/global/collections/default_collection"
    f"/engines/{VERTEX_ENGINE}/servingConfigs/default_search:search"
)
GEMINI_URL         = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
GOOGLE_API_KEY     = os.getenv("GOOGLE_API_KEY", "")

# API_KEYS env var required — comma-separated list of valid keys
_raw_keys = os.getenv("API_KEYS", "")
if not _raw_keys:
    raise RuntimeError("API_KEYS environment variable must be set")
VALID_API_KEYS = set(k.strip() for k in _raw_keys.split(",") if k.strip())

# Rate limiting: requests per minute per API key
RATE_LIMIT_RPM   = int(os.getenv("RATE_LIMIT_RPM", "60"))
_rate_counters: dict[str, list[float]] = defaultdict(list)  # key -> [timestamps]


def check_rate_limit(api_key: str):
    now    = time.time()
    window = 60.0
    calls  = _rate_counters[api_key]
    # Drop timestamps outside the window
    _rate_counters[api_key] = [t for t in calls if now - t < window]
    if len(_rate_counters[api_key]) >= RATE_LIMIT_RPM:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {RATE_LIMIT_RPM} requests/minute.",
            headers={"Retry-After": "60"},
        )
    _rate_counters[api_key].append(now)

# ── System prompts per query type ─────────────────────────────────────────────
PROMPTS = {
    "substitute": (
        "You are a historical cookbook substitution oracle. "
        "Using only the provided context, give practical substitutions for the ingredient asked about. "
        "Cite the book name and year. Be concise."
    ),
    "modernise": (
        "You are a culinary translator. Rewrite the old recipe provided in the question "
        "using modern supermarket ingredients, standard metric/imperial measurements, and "
        "contemporary cooking instructions. Use the context records as reference for "
        "substitutions and measurement equivalents. Be practical and specific."
    ),
    "convert": (
        "You are an expert in historical culinary measurements. "
        "Convert the old measurement(s) in the question to modern equivalents (ml, grams, cups). "
        "Use the context if relevant, otherwise use your knowledge of historical measures. "
        "Give a clear, definitive answer."
    ),
    "explain": (
        "You are a culinary historian. Explain the old cooking term or technique asked about "
        "in clear modern language. Reference the provided context where relevant. "
        "Include what modern equivalent technique or tool to use."
    ),
}

# ── Auth ──────────────────────────────────────────────────────────────────────
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def require_api_key(key: str = Security(api_key_header)):
    if not key or key not in VALID_API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return key

# ── Load index once ───────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def load_resources():
    if not INDEX_PATH.exists():
        raise RuntimeError("Index not found — run build_index.py first.")
    index   = faiss.read_index(str(INDEX_PATH))
    records = np.load(str(RECORDS_PATH), allow_pickle=True)
    embedder = SentenceTransformer(EMBED_MODEL)
    llm      = OpenAI(base_url=LM_STUDIO_URL, api_key="lm-studio")
    return index, records, embedder, llm


# ── Core retrieval + synthesis ────────────────────────────────────────────────
def retrieve(query: str, k: int = TOP_K) -> tuple[list[dict], str]:
    index, records, embedder, _ = load_resources()
    q_emb = embedder.encode([query]).astype("float32")
    _, idx = index.search(q_emb, k)
    hits = [records[i] for i in idx[0]]
    context = "\n\n".join(
        f"[{r.get('book')} ({r.get('year')})]\n"
        f"{r.get('ingredient')} → {r.get('substitute')}\n"
        f"Context: {r.get('context')}\nNotes: {r.get('notes')}"
        for r in hits
    )
    return hits, context


def synthesise(query_type: str, question: str, context: str) -> str:
    _, _, _, llm = load_resources()
    system = PROMPTS[query_type]
    resp = llm.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": f"Context:\n{context}\n\nQuestion: {question}"},
        ],
        temperature=0.2,
        max_tokens=400,
    )
    return resp.choices[0].message.content.strip()


def format_sources(hits: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in hits:
        key = (r.get("ingredient"), r.get("substitute"), r.get("book"))
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "ingredient": r.get("ingredient"),
            "substitute": r.get("substitute"),
            "book":       r.get("book"),
            "year":       r.get("year"),
            "context":    r.get("context"),
            "diet_tags":  r.get("diet_tags", []),
            "notes":      r.get("notes"),
        })
    return out


def get_confidence(ingredient: str) -> float:
    """Return crossref consensus score for an ingredient, or 0.0 if unknown."""
    crossref_path = DATA_DIR / "crossref.json"
    if not crossref_path.exists():
        return 0.0
    try:
        data = json.load(crossref_path.open(encoding="utf-8"))
        key = ingredient.lower().strip()
        entry = data.get(key)
        if not entry:
            matches = [k for k in data if key in k or k in key]
            if matches:
                entry = data[matches[0]]
        if entry and entry.get("substitutes"):
            scores = [s.get("consensus_score", 0.0) for s in entry["substitutes"]]
            return round(max(scores), 3) if scores else 0.0
    except Exception:
        pass
    return 0.0


# ── Vertex AI search + Gemini answer ─────────────────────────────────────────

def _gcp_token() -> str:
    """Get a GCP access token via ADC (local gcloud) or service account (Railway)."""
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


def vertex_search(query: str, page_size: int = 10) -> list[dict]:
    """Query Vertex AI Discovery Engine and return structured hit list."""
    try:
        token = _gcp_token()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"GCP auth failed: {e}")

    resp = http_requests.post(
        VERTEX_SEARCH_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Goog-User-Project": GCP_PROJECT,
        },
        json={"query": query, "pageSize": page_size},
        timeout=15,
    )
    if not resp.ok:
        raise HTTPException(status_code=502, detail=f"Vertex search error: {resp.text[:200]}")

    hits = []
    for r in resp.json().get("results", []):
        doc = r.get("document", {}).get("structData", {})
        if doc:
            hits.append(doc)
    return hits


def gemini_answer(question: str, hits: list[dict]) -> str:
    """Ask Gemini to synthesise a readable answer from Vertex search hits."""
    if not GOOGLE_API_KEY:
        raise HTTPException(status_code=503, detail="GOOGLE_API_KEY not set")

    context = "\n\n".join(
        f"[{h.get('book', 'Unknown')} ({h.get('year', '?')})] "
        f"{h.get('ingredient')} → {h.get('substitute')}"
        + (f"\nContext: {h['context']}" if h.get('context') else "")
        for h in hits
    )

    prompt = (
        "You are a historical cookbook expert. Using only the sources below, "
        "answer the question in 2–4 sentences. Cite each source as (Book, Year). "
        "If the sources don't cover the question, say so.\n\n"
        f"Sources:\n{context}\n\nQuestion: {question}"
    )

    resp = http_requests.post(
        f"{GEMINI_URL}?key={GOOGLE_API_KEY}",
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 512,
                "thinkingConfig": {"thinkingBudget": 0},
            },
        },
        timeout=30,
    )
    if not resp.ok:
        raise HTTPException(status_code=502, detail=f"Gemini error: {resp.text[:200]}")

    return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


# ── Request / response models ─────────────────────────────────────────────────
class QueryRequest(BaseModel):
    question: str
    top_k: int = TOP_K

class QueryResponse(BaseModel):
    answer:       str
    sources:      list[dict]
    query_type:   str
    latency_ms:   int
    confidence:   float = 0.0   # 0–1 consensus score from crossref layer

class BatchRequest(BaseModel):
    ingredients: list[str]
    top_k: int = TOP_K

class BatchResponseItem(BaseModel):
    ingredient:  str
    answer:      str
    sources:     list[dict]
    confidence:  float
    latency_ms:  int

class BatchResponse(BaseModel):
    results:    list[BatchResponseItem]
    total_ms:   int

class AskRequest(BaseModel):
    question:  str
    page_size: int = 10

class AskResponse(BaseModel):
    answer:     str
    sources:    list[dict]
    latency_ms: int


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Old Recipe Intelligence API",
    description="Substitutions, modernisation, measurement conversion and term explanation from historical cookbooks.",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _handle(query_type: str, req: QueryRequest, key: str) -> QueryResponse:
    check_rate_limit(key)
    t0 = time.perf_counter()
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="question cannot be empty")
    hits, context = retrieve(req.question, req.top_k)
    answer        = synthesise(query_type, req.question, context)
    latency       = int((time.perf_counter() - t0) * 1000)
    # Extract the primary ingredient from hits for confidence lookup
    primary_ing   = hits[0].get("ingredient", "") if hits else ""
    return QueryResponse(
        answer=answer,
        sources=format_sources(hits),
        query_type=query_type,
        latency_ms=latency,
        confidence=get_confidence(primary_ing),
    )


@app.post("/v1/substitute", response_model=QueryResponse)
def substitute(req: QueryRequest, key: str = Depends(require_api_key)):
    """What can replace ingredient X in an old recipe?"""
    return _handle("substitute", req, key)


@app.post("/v1/modernise", response_model=QueryResponse)
def modernise(req: QueryRequest, key: str = Depends(require_api_key)):
    """Rewrite an old recipe using modern ingredients and measurements."""
    return _handle("modernise", req, key)


@app.post("/v1/convert", response_model=QueryResponse)
def convert(req: QueryRequest, key: str = Depends(require_api_key)):
    """Convert a historical measurement to modern equivalents."""
    return _handle("convert", req, key)


@app.post("/v1/explain", response_model=QueryResponse)
def explain(req: QueryRequest, key: str = Depends(require_api_key)):
    """Explain an old cooking term or technique."""
    return _handle("explain", req, key)


@app.post("/v1/substitute/batch", response_model=BatchResponse)
def substitute_batch(req: BatchRequest, key: str = Depends(require_api_key)):
    """
    Batch substitution: send up to 20 ingredients, get back substitutions for each.
    Each item is processed independently; rate limit applies per batch call, not per ingredient.
    """
    check_rate_limit(key)
    if not req.ingredients:
        raise HTTPException(status_code=400, detail="ingredients list cannot be empty")
    if len(req.ingredients) > 20:
        raise HTTPException(status_code=400, detail="maximum 20 ingredients per batch")

    t_total = time.perf_counter()
    results = []

    for ingredient in req.ingredients:
        if not ingredient.strip():
            continue
        t0 = time.perf_counter()
        question = f"What can substitute for {ingredient} in old recipes?"
        try:
            hits, context = retrieve(question, req.top_k)
            answer = synthesise("substitute", question, context)
        except Exception as e:
            answer = f"Error: {e}"
            hits = []
        latency = int((time.perf_counter() - t0) * 1000)
        results.append(BatchResponseItem(
            ingredient=ingredient,
            answer=answer,
            sources=format_sources(hits),
            confidence=get_confidence(ingredient),
            latency_ms=latency,
        ))

    return BatchResponse(
        results=results,
        total_ms=int((time.perf_counter() - t_total) * 1000),
    )


@app.get("/v1/crossref/{ingredient}")
def crossref(ingredient: str, key: str = Depends(require_api_key)):
    """
    Return the full cross-referenced knowledge entry for an ingredient:
    all known substitutes, consensus scores, citation counts, earliest year.
    """
    crossref_path = DATA_DIR / "crossref.json"
    if not crossref_path.exists():
        raise HTTPException(status_code=503, detail="Cross-reference index not built. Run crossref.py.")
    data = json.load(crossref_path.open(encoding="utf-8"))
    key_norm = ingredient.lower().strip()
    entry = data.get(key_norm)
    if not entry:
        # fuzzy: find partial matches
        matches = [k for k in data if key_norm in k or k in key_norm]
        if matches:
            entry = data[matches[0]]
        else:
            raise HTTPException(status_code=404, detail=f"No data found for '{ingredient}'")
    return entry


@app.get("/v1/stats")
def stats(key: str = Depends(require_api_key)):
    """Return corpus statistics."""
    stats_path = DATA_DIR / "crossref_stats.json"
    if not stats_path.exists():
        raise HTTPException(status_code=503, detail="Run crossref.py first.")
    return json.load(stats_path.open(encoding="utf-8"))


@app.get("/v1/health")
def health():
    data_files = ["sub_index.faiss", "sub_records.npy", "crossref.json"]
    data_ready = all((DATA_DIR / f).exists() for f in data_files)
    return {
        "status":   "ok",
        "data":     "ready" if data_ready else "missing",
        "endpoints": [
            "/v1/ask",
            "/v1/substitute", "/v1/modernise", "/v1/convert",
            "/v1/explain", "/v1/crossref/{ingredient}", "/v1/stats",
        ],
    }


@app.post("/v1/ask", response_model=AskResponse)
def ask(req: AskRequest, key: str = Depends(require_api_key)):
    """
    Ask a natural language question grounded in 36,000+ historical cookbook records.
    Uses Vertex AI Discovery Engine for retrieval and Gemini for answer generation.
    Example: "What did Victorian cooks use instead of butter?"
    """
    check_rate_limit(key)
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="question cannot be empty")
    t0 = time.perf_counter()
    hits = vertex_search(req.question, req.page_size)
    answer = gemini_answer(req.question, hits)
    sources = [
        {
            "ingredient": h.get("ingredient"),
            "substitute": h.get("substitute"),
            "book":       h.get("book"),
            "year":       h.get("year"),
            "category":   h.get("category"),
        }
        for h in hits
    ]
    return AskResponse(
        answer=answer,
        sources=sources,
        latency_ms=int((time.perf_counter() - t0) * 1000),
    )


# ── Static pages ──────────────────────────────────────────────────────────────
@app.get("/", include_in_schema=False)
def root():
    return {
        "name": "Old Recipe Intelligence API",
        "version": "1.0",
        "endpoints": ["/v1/ask", "/v1/substitute", "/v1/modernise", "/v1/convert", "/v1/explain", "/v1/stats", "/v1/health"],
        "docs": "/docs",
    }
