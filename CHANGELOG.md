# Changelog — Old Recipe Intelligence

## 2026 — HuggingFace Dataset Published

- Published cleaned dataset to HuggingFace: [cookbook7/historical-culinary-substitutions](https://huggingface.co/datasets/cookbook7/historical-culinary-substitutions)
- 25,251 deduped substitution pairs (from the 36,657 enriched records); companion `book_meta.json` (345 books) and `dataset_stats.json`
- Dual-licensed: **CC BY-NC 4.0** for non-commercial use; paid commercial tiers $499–$3,000+
- Citation: *Pope, N. (2026). Historical Culinary Substitutions Dataset.*

## 2026-04-11 — Vertex AI Ingestion Complete

### Data Pipeline
- Completed full enrichment run: 36,617 substitution records processed by Qwen 3.5 35B (local, Mac Studio)
- Added `category` (12-class) and `valid` fields to every record
- Ran Gemini 2.5 Flash post-processor (`fix_other_categories.py`) — re-classified 3,307 records from `other` to correct category
- Final dataset: `data/substitutions_enriched.jsonl` (15MB, 36,617 records)

### Vertex AI
- Enabled Discovery Engine API on GCP project
- Created data store: `old-recipe-substitutions` (generic, no-content, search)
- Ingested all 36,617 records from GCS — 0 failures
- Created search engine: `old-recipe-search` (standard tier)
- Verified live with test query ("substitute for butter" → 5 results with book provenance)

### Quality Audit
- Switched audit model from Groq (rate-limited) to Gemini 2.5 Flash
- Final audit: 66.5% category agreement, 76.5% valid agreement (marginal — acceptable for RAG)
- Remaining `other` records: ~6,440 (genuine non-food entries)

---

## 2026-04-10 — Enrichment Run + Audit Infrastructure

### Enrichment
- Built `enrich_substitutions.py` — Qwen 3.5 35B via Ollama, batches of 20, checkpoint/resume
- Iterated prompt 3x to reduce `other` over-classification and improve valid/invalid accuracy
- Built `watch_audit.sh` — periodic audit watcher (fires every N records)

### Audit
- Built `audit_enrichment.py` — originally Groq Llama 70B, migrated to Gemini 2.5 Flash
- Fixed: python-dotenv missing, Groq rate limits, Gemini thinking token budget, batch size tuning
- Built `fix_other_categories.py` — Gemini post-processor for `other` category cleanup

---

## Earlier — Corpus + Extraction

- Downloaded 466 public-domain cookbooks (1658–1929) from Project Gutenberg
- Extracted 36,657 ingredient substitution records (`extract_substitutions.py`)
- Built FAISS index (`build_index.py`, `pipeline.py`)
- Added Railway deployment + GCS sync (`startup.sh`, `railway.toml`, `sync_data.py`)
- Added HuggingFace dataset prep (`prepare_dataset.py`)
- Added consumer-facing moderniser page (`modernise.html`)
