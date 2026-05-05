# Old Recipe Intelligence — Project Config

## Google Cloud (GCP)
- **CLI:** `gcloud` installed and authenticated
- **Project:** `<your-gcp-project>`
- **Credits:** GenAI App Builder credits scoped to Discovery Engine / Vertex AI Agent Builder
- **ADC:** application default credentials set, quota project configured

Set project: `gcloud config set project <your-gcp-project>`

## Vertex AI Discovery Engine (live)
- **Data store:** `old-recipe-substitutions` — 36,617 substitution records ingested
- **Search engine:** `old-recipe-search` (standard tier)
- **Search endpoint:**
  `POST https://discoveryengine.googleapis.com/v1/projects/<your-gcp-project>/locations/global/collections/default_collection/engines/old-recipe-search/servingConfigs/default_search:search`
- **Auth:** `gcloud auth print-access-token` + header `X-Goog-User-Project: <your-gcp-project>`

## GCS
- **Bucket:** `gs://old-recipe-intelligence-data`
- **Dataset:** `gs://old-recipe-intelligence-data/data/substitutions_enriched_gcs.jsonl`

## Next Steps
See `TODO.md` for prioritised task list. Demo build is next.
