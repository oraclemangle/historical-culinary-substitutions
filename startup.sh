#!/usr/bin/env bash
set -e

echo "=== Old Recipe Intelligence startup ==="

# Download index files from GCS before starting the API
echo "Downloading index from GCS..."
python sync_data.py download

echo "Starting API server on port ${PORT:-8080}..."
exec uvicorn api:app --host 0.0.0.0 --port "${PORT:-8080}"
