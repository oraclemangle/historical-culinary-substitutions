"""
Data sync — upload/download built index files to/from GCS.

The git repo contains only source code. Built artefacts live in GCS:
  gs://old-recipe-intelligence-data/

Usage:
  python sync_data.py upload    # push local data/ → GCS (after a rebuild)
  python sync_data.py download  # pull GCS → local data/ (Railway startup)
  python sync_data.py status    # compare local vs GCS
"""
import json
import os
import sys
from pathlib import Path

DATA_DIR    = Path("data")
BUCKET_NAME = os.getenv("GCS_BUCKET", "old-recipe-intelligence-data")
GCS_PREFIX  = "index/"

# Files to sync (built artefacts, not raw extraction data)
SYNC_FILES = [
    "sub_index.faiss",
    "sub_records.npy",
    "crossref.json",
    "crossref_stats.json",
    "book_meta.json",
    "validation_report.json",
]


def get_client():
    """Return a GCS client using env var credentials or service account file."""
    from google.cloud import storage

    # Railway: set GOOGLE_APPLICATION_CREDENTIALS_JSON env var to the JSON contents
    creds_json = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if creds_json:
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(creds_json)
            tmp_path = f.name
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_file(tmp_path)
        return storage.Client(credentials=creds)

    # Local dev: use service account file
    creds_file = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    if creds_file and Path(creds_file).exists():
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_file(creds_file)
        return storage.Client(credentials=creds)

    # Fallback: application default credentials
    return storage.Client()


def upload():
    client = get_client()
    bucket = client.bucket(BUCKET_NAME)
    uploaded = 0

    for fname in SYNC_FILES:
        local = DATA_DIR / fname
        if not local.exists():
            print(f"  skip  {fname}  (not found locally)")
            continue
        blob = bucket.blob(GCS_PREFIX + fname)
        blob.upload_from_filename(str(local))
        size_mb = local.stat().st_size / 1_048_576
        print(f"  up    {fname}  ({size_mb:.1f} MB)")
        uploaded += 1

    # Write a manifest with file sizes + timestamps for status checks
    manifest = {}
    for fname in SYNC_FILES:
        local = DATA_DIR / fname
        if local.exists():
            manifest[fname] = {
                "size":  local.stat().st_size,
                "mtime": local.stat().st_mtime,
            }
    bucket.blob(GCS_PREFIX + "manifest.json").upload_from_string(
        json.dumps(manifest, indent=2)
    )
    print(f"\nUploaded {uploaded} files → gs://{BUCKET_NAME}/{GCS_PREFIX}")


def download():
    DATA_DIR.mkdir(exist_ok=True)
    client = get_client()
    bucket = client.bucket(BUCKET_NAME)
    downloaded = 0

    for fname in SYNC_FILES:
        dest = DATA_DIR / fname
        blob = bucket.blob(GCS_PREFIX + fname)
        try:
            blob.reload()
        except Exception:
            print(f"  skip  {fname}  (not in GCS)")
            continue
        size_mb = blob.size / 1_048_576
        print(f"  down  {fname}  ({size_mb:.1f} MB)", flush=True)
        blob.download_to_filename(str(dest))
        downloaded += 1

    print(f"\nDownloaded {downloaded} files from gs://{BUCKET_NAME}/{GCS_PREFIX}")
    return downloaded


def status():
    client  = get_client()
    bucket  = client.bucket(BUCKET_NAME)
    print(f"{'File':35s} {'Local':>10s} {'GCS':>10s} {'Match'}")
    print("-" * 65)
    for fname in SYNC_FILES:
        local    = DATA_DIR / fname
        blob     = bucket.blob(GCS_PREFIX + fname)
        local_sz = f"{local.stat().st_size:,}" if local.exists() else "—"
        try:
            blob.reload()
            gcs_sz = f"{blob.size:,}"
            match  = "✓" if local.exists() and local.stat().st_size == blob.size else "≠"
        except Exception:
            gcs_sz = "—"
            match  = "?"
        print(f"  {fname:33s} {local_sz:>10s} {gcs_sz:>10s}  {match}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "upload":
        upload()
    elif cmd == "download":
        download()
    elif cmd == "status":
        status()
    else:
        print(f"Unknown command: {cmd}. Use upload / download / status.")
        sys.exit(1)
