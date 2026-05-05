# TODO — Old Recipe Intelligence

## Next Session — Demo Build (Priority)

### 1. Backend — Vertex AI integration
- [ ] Update `api.py` — add `/search` endpoint that calls Discovery Engine `old-recipe-search`
- [ ] Add Gemini conversational layer — takes search results, returns readable answer with citations (book + year)
- [ ] Add `/ask` endpoint — natural language question → grounded answer
- [ ] Keep existing FAISS endpoints working (don't break what's there)

### 2. Frontend
- [ ] Update `app.py` or `index.html` — add a simple "Ask a question" UI backed by `/ask`
- [ ] Display: answer paragraph + collapsible source list (ingredient → substitute, book, year)
- [ ] Keep it simple — no auth, no accounts, just works

### 3. Deploy
- [ ] Update `startup.sh` if needed for new endpoints
- [ ] Push to Railway — verify health check passes
- [ ] Test end-to-end on live URL

### 4. Publish dataset
- [x] Push `substitutions_enriched.jsonl` to HuggingFace dataset repo — live at [cookbook7/historical-culinary-substitutions](https://huggingface.co/datasets/cookbook7/historical-culinary-substitutions)
- [x] Write dataset card — published with CC BY-NC 4.0 licence + paid commercial tier ($499–$3,000+)

---

## Future / Nice to Have

- [ ] Ingest raw cookbook text (unstructured) into a second Discovery Engine data store for full-text RAG
- [ ] Add conversational memory (multi-turn questions)
- [ ] Analytics — track what people search for
- [ ] Landing page with use cases (food tech, game devs, education)
- [ ] Write up the pipeline as a blog post / case study

---

## Infrastructure Notes
- GCP project: `<your-gcp-project>`
- Data store: `old-recipe-substitutions`
- Search engine: `old-recipe-search`
- GCS bucket: `gs://old-recipe-intelligence-data`
- Discovery Engine search endpoint:
  `POST https://discoveryengine.googleapis.com/v1/projects/<your-gcp-project>/locations/global/collections/default_collection/engines/old-recipe-search/servingConfigs/default_search:search`
- Local dataset: `data/substitutions_enriched.jsonl`
- GCS dataset: `gs://old-recipe-intelligence-data/data/substitutions_enriched_gcs.jsonl`
