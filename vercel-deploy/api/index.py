"""Vercel serverless entry for DealDesk.

Wraps the FastAPI app as an ASGI function. SQLite lives in /tmp (the only
writable path on Vercel); a pre-seeded demo DB is copied there on cold start.
"""

import os
import shutil
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_TMP_DB = "/tmp/dealdesk.db"
_SEED_DB = os.path.join(_ROOT, "dealdesk-seed.db")

if not os.path.exists(_TMP_DB):
    if os.path.exists(_SEED_DB):
        shutil.copy(_SEED_DB, _TMP_DB)
    # else: db module will create a fresh one via init_db on startup

os.environ["DEALDESK_DB"] = _TMP_DB

from app.main import app  # noqa: E402  (FastAPI ASGI app; Vercel serves it)
from app import db  # noqa: E402

db.init_db()
