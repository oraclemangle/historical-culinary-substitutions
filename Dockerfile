FROM python:3.11-slim

WORKDIR /app

# System deps for faiss-cpu and sentence-transformers
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

# Copy source and pre-built data artefacts
COPY api.py crossref.py build_index.py sync_data.py startup.sh ./

# Download the sentence-transformers model at build time so cold starts are fast
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

RUN chmod +x startup.sh

EXPOSE 8080

CMD ["./startup.sh"]
