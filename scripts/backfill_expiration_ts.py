"""
Remplit expiration_ts à partir de expiration_date pour les anciens documents QR.
À exécuter une fois après déploiement : python scripts/backfill_expiration_ts.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"))

from config import Config  # noqa: E402
from services.datastore import FirestoreDataStore, _iso_datetime_to_ts  # noqa: E402


def main() -> None:
    store = FirestoreDataStore(Config)
    col = store._col("qr_codes")
    updated = 0
    skipped = 0
    for doc in col.stream():
        data = doc.to_dict() or {}
        if data.get("expiration_ts") is not None:
            skipped += 1
            continue
        ts = _iso_datetime_to_ts(data.get("expiration_date"))
        if ts is None:
            skipped += 1
            continue
        doc.reference.update({"expiration_ts": ts})
        updated += 1
    print(f"expiration_ts ajouté sur {updated} document(s), ignorés {skipped}.")


if __name__ == "__main__":
    main()
