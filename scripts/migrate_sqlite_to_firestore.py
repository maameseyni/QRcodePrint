"""
Migration des QR codes depuis SQLite (database.db) vers Firestore.

Usage:
  python scripts/migrate_sqlite_to_firestore.py --dry-run
  python scripts/migrate_sqlite_to_firestore.py
  python scripts/migrate_sqlite_to_firestore.py --sqlite C:\\chemin\\database.db --overwrite

Variables d'environnement : identiques à l'app (.env avec FIRESTORE_PROJECT_ID,
GOOGLE_APPLICATION_CREDENTIALS, FIRESTORE_COLLECTION_PREFIX optionnel).
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Racine du projet sur sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from config import Config
from services.datastore import FirestoreDataStore


def _norm_iso(value) -> str | None:
    """Normalise une date SQLite en chaîne ISO (compatible fromisoformat côté app)."""
    if value is None or value == "":
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        if " " in s and "T" not in s.split()[0]:
            s = s.replace(" ", "T", 1)
        return datetime.fromisoformat(s).isoformat()
    except ValueError:
        return s


def _row_to_record(row: sqlite3.Row) -> dict:
    d = dict(row)
    out = {
        "id": (d.get("id") or "").strip(),
        "client_name": d.get("client_name") or "",
        "client_firstname": d.get("client_firstname") or "",
        "client_phone": d.get("client_phone") or "",
        "client_email": d.get("client_email") or "",
        "client_id": d.get("client_id") or "",
        "comment": d.get("comment") or "",
        "service": d.get("service") or "",
        "ticket_number": d.get("ticket_number") or "",
        "qr_data": d.get("qr_data") or "",
        "qr_hash": d.get("qr_hash") or "",
        "expiration_date": _norm_iso(d.get("expiration_date")) or "",
        "created_at": _norm_iso(d.get("created_at")) or datetime.utcnow().isoformat(),
        "printed_at": _norm_iso(d.get("printed_at")),
        "is_active": d.get("is_active", 1),
    }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrer qr_codes (SQLite) vers Firestore.")
    parser.add_argument(
        "--sqlite",
        type=Path,
        default=Path(Config.DATABASE_PATH),
        help="Chemin vers database.db",
    )
    parser.add_argument("--dry-run", action="store_true", help="Ne rien écrire sur Firestore")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Remplacer les documents Firestore dont l'id existe déjà",
    )
    args = parser.parse_args()

    db_path: Path = args.sqlite.resolve()
    if not db_path.is_file():
        print(f"Fichier SQLite introuvable: {db_path}")
        return 1

    cfg = {
        "FIRESTORE_PROJECT_ID": Config.FIRESTORE_PROJECT_ID,
        "FIRESTORE_COLLECTION_PREFIX": Config.FIRESTORE_COLLECTION_PREFIX,
        "GOOGLE_APPLICATION_CREDENTIALS": Config.GOOGLE_APPLICATION_CREDENTIALS,
    }
    if not cfg.get("FIRESTORE_PROJECT_ID"):
        print("FIRESTORE_PROJECT_ID manquant (.env)")
        return 1

    store = FirestoreDataStore(cfg) if not args.dry_run else None

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, client_name, client_firstname, client_phone, client_email, client_id, "
        "comment, service, ticket_number, qr_data, qr_hash, expiration_date, created_at, "
        "printed_at, is_active FROM qr_codes ORDER BY created_at ASC"
    ).fetchall()
    conn.close()

    if not rows:
        print("Aucune ligne dans qr_codes.")
        return 0

    imported = 0
    skipped = 0
    errors = 0

    for row in rows:
        rec = _row_to_record(row)
        if not rec["id"] or not rec["qr_data"] or not rec["qr_hash"]:
            print(f"Ignoré (données incomplètes): id={rec.get('id')!r}")
            skipped += 1
            continue

        if args.dry_run:
            imported += 1
            continue

        assert store is not None
        try:
            if not args.overwrite and store.get_qr(rec["id"]):
                skipped += 1
                continue
            store.import_qr_document(rec)
            imported += 1
        except Exception as e:
            print(f"Erreur id={rec['id']}: {e}")
            errors += 1

    if args.dry_run:
        print(f"[dry-run] {len(rows)} ligne(s) lues depuis {db_path}, prêtes à importer.")
        return 0

    print(f"Import terminé: {imported} écrit(s), {skipped} ignoré(s), {errors} erreur(s).")
    return 0 if errors == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
