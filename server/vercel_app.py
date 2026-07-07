"""Vercel serverless entry point for the FastAPI backend.

Vercel's @vercel/python runtime serves the module-level `app` (an ASGI app)
as a serverless function. This file lives inside `server/` so `from app.main
import app` resolves against the bundled package.

Two adaptations for the serverless environment:
- SQLite must live on the only writable path, /tmp (the deployment filesystem
  is read-only). This is ephemeral per container — see the deploy notes.
- Sample data is seeded on a cold container if the DB is empty, so the
  dashboard renders fully regardless of which instance serves a read. User-
  created data persists within a warm instance.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("IVD_DB_PATH", "/tmp/ivd.db")

from app.main import app, load_samples, seed_lifecycle  # noqa: E402
from app import db  # noqa: E402

try:
    # Demo data persists across cold starts by re-seeding automatically,
    # unless an admin pressed "Clear demo data" (best-effort: the cleared
    # flag itself lives in ephemeral storage until Postgres lands).
    if not db.dataset_meta():
        load_samples()
    if not db.list_ideas() and db.meta_get("demo_cleared") != "1" and not db.list_users():
        seed_lifecycle(force=True)
except Exception:
    pass
