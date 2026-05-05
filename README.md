# Historical Culinary Substitutions

Pipeline + API for building, enriching, and serving a dataset of
ingredient substitutions extracted from 466 public-domain cookbooks
published between 1658 and 1929.

## 📚 Dataset on Hugging Face

**[cookbook7/historical-culinary-substitutions](https://huggingface.co/datasets/cookbook7/historical-culinary-substitutions)**

- 25,251 deduped ingredient → substitute pairs
- Sourced from Project Gutenberg + Internet Archive
- Each record cites its source book and publication year
- **Licence:** CC BY-NC 4.0 (free for non-commercial use with attribution)
- **Commercial use:** paid licence tiers from $499 — see Hugging Face page

## What's in this repo

This is the **code** that produced the dataset and serves it via API.
The dataset itself lives on Hugging Face (link above) — it is not
mirrored here.

| Stage | Scripts |
|---|---|
| Corpus download | `download_books.py`, `download_gutenberg_bulk.py`, `download_archive.py` |
| Extraction | `extract_substitutions.py`, `extract_measurements.py` |
| Enrichment | `enrich_substitutions.py`, `fix_other_categories.py` |
| Audit | `audit_enrichment.py` |
| Cleaning + HF prep | `prepare_dataset.py`, `validate_data.py`, `fix_years.py` |
| Cross-reference | `crossref.py` |
| Index + retrieval | `build_index.py`, `pipeline.py`, `oracle.py` |
| API | `api.py` (FastAPI), `app.py` (Gradio) |
| Deployment | `Dockerfile`, `Dockerfile.frontend`, `railway.toml`, `render.yaml` |

## Pipeline

1. Download public-domain cookbooks (Project Gutenberg + Internet Archive)
2. Chunk and extract substitution pairs with Gemini 2.5 Flash
3. Enrich with category labels and validation flags using Qwen 3.5 35B (local)
4. Audit with Gemini 2.5 Flash — final agreement: 66.5% category, 76.5% valid
5. Clean, dedupe, and publish to Hugging Face
6. Ingest into Vertex AI Discovery Engine for grounded search
7. Serve via FastAPI on Cloud Run, Gradio UI on Render

## Running locally

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Set required environment variables
export API_KEYS="your-api-key-here"
export GOOGLE_API_KEY="..."        # for Gemini calls
export GCP_PROJECT="your-project"  # for Vertex AI Discovery Engine

uvicorn api:app --host 0.0.0.0 --port 8000
```

The API expects a FAISS index at `data/sub_index.faiss` and records at
`data/sub_records.npy`. Build these by running the pipeline scripts in
order, or sync from GCS via `sync_data.py`.

## Code licence

**MIT** — see `LICENSE`.

This licence covers only the code in this repository. The **dataset**
has a separate licence (CC BY-NC 4.0 with paid commercial tiers) — see
the [Hugging Face page](https://huggingface.co/datasets/cookbook7/historical-culinary-substitutions).

## Citation

If you use the dataset, please cite:

> Pope, N. (2026). *Historical Culinary Substitutions Dataset.*
> https://huggingface.co/datasets/cookbook7/historical-culinary-substitutions
