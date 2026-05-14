"""Couche d'accès données Firestore pour le projet."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from firebase_admin import credentials, firestore, get_app, initialize_app
from google.api_core.exceptions import GoogleAPICallError
from google.cloud.firestore import FieldFilter

logger = logging.getLogger(__name__)


def _iso_datetime_to_ts(iso_val: Any) -> Optional[int]:
    """Convertit expiration_date (ISO) en epoch secondes pour requêtes Firestore."""
    if iso_val is None:
        return None
    s = str(iso_val).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        return int(dt.timestamp())
    except Exception:
        return None


def _now_ts() -> int:
    """
    Horloge alignée sur la création des QR dans app.py : expiration_ts utilise
    int(expiration_date.timestamp()) avec expiration_date = datetime.now() + delta (naïf, fuseau serveur).
    Ne pas utiliser utcnow() ici sans avoir migré les timestamps stockés.
    """
    return int(datetime.now().timestamp())


@dataclass
class QueryFilters:
    filter_type: str = "all"
    search: str = ""
    ticket: str = ""
    date_from: str = ""
    date_to: str = ""
    limit: int = 500
    # Filtre auteur : id compte (propriétaire ou caissier) + id propriétaire de la salle (QR sans créateur = propriétaire).
    author_account_id: str = ""
    author_scope_owner_id: str = ""


class FirestoreDataStore:
    """Stockage Firestore centré sur les QR codes, extensible."""

    def __init__(self, app_config):
        self.config = app_config
        self.collection_prefix = app_config.get("FIRESTORE_COLLECTION_PREFIX", "qrprint")
        self._client = None
        self._init_client()

    def _init_client(self):
        try:
            get_app()
        except ValueError:
            cred_json = self.config.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
            cred_path = self.config.get("GOOGLE_APPLICATION_CREDENTIALS")
            project_id = self.config.get("FIRESTORE_PROJECT_ID")

            # Chemin copié depuis une machine locale (ex. Windows) : absent sur Render → ne pas ouvrir.
            if cred_path and str(cred_path).strip():
                p = str(cred_path).strip()
                cred_path = p if os.path.isfile(p) else None
            # Même nettoyage pour la variable standard GCP (évite ADC sur un fichier inexistant).
            gae = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
            if gae and not os.path.isfile(gae):
                os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)

            if cred_json and str(cred_json).strip():
                cred = credentials.Certificate(json.loads(cred_json))
                options = {"projectId": project_id} if project_id else None
                initialize_app(cred, options or {})
            elif cred_path:
                cred = credentials.Certificate(cred_path)
                options = {"projectId": project_id} if project_id else None
                initialize_app(cred, options or {})
            else:
                options = {"projectId": project_id} if project_id else None
                initialize_app(options=options or {})
        self._client = firestore.client()

    def _col(self, name: str):
        return self._client.collection(f"{self.collection_prefix}_{name}")

    # ---------- Users ----------
    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        u = (username or "").strip().lower()
        if not u:
            return None
        docs = self._col("users").where(filter=FieldFilter("username", "==", u)).limit(1).stream()
        for doc in docs:
            data = doc.to_dict() or {}
            data.setdefault("id", doc.id)
            return data
        return None

    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        uid = str(user_id or "").strip()
        if not uid:
            return None
        snap = self._col("users").document(uid).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        data.setdefault("id", uid)
        return data

    def get_user_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        p = (phone or "").strip()
        if not p:
            return None
        docs = self._col("users").where(filter=FieldFilter("phone", "==", p)).limit(1).stream()
        for doc in docs:
            data = doc.to_dict() or {}
            data.setdefault("id", doc.id)
            return data
        return None

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        e = (email or "").strip().lower()
        if not e or "@" not in e:
            return None
        docs = self._col("users").where(filter=FieldFilter("email", "==", e)).limit(1).stream()
        for doc in docs:
            data = doc.to_dict() or {}
            data.setdefault("id", doc.id)
            return data
        return None

    def get_user_by_google_sub(self, google_sub: str) -> Optional[Dict[str, Any]]:
        sub = (google_sub or "").strip()
        if not sub:
            return None
        docs = self._col("users").where(filter=FieldFilter("google_sub", "==", sub)).limit(1).stream()
        for doc in docs:
            data = doc.to_dict() or {}
            data.setdefault("id", doc.id)
            return data
        return None

    def create_user(self, user_record: Dict[str, Any]) -> str:
        record = dict(user_record)
        user_id = str(record.get("id") or "")
        if not user_id:
            raise ValueError("create_user: champ id obligatoire")
        record["username"] = str(record.get("username") or "").strip().lower()
        if not record["username"]:
            raise ValueError("create_user: champ username obligatoire")
        record.setdefault("role", "admin")
        record.setdefault("is_active", True)
        record.setdefault("created_at", datetime.utcnow().isoformat())
        self._col("users").document(user_id).set(record)
        return user_id

    def update_user(self, user_id: str, updates: Dict[str, Any]) -> None:
        if not user_id:
            raise ValueError("update_user: user_id obligatoire")
        payload = dict(updates or {})
        if "username" in payload:
            payload["username"] = str(payload["username"] or "").strip().lower()
        self._col("users").document(user_id).update(payload)

    def list_cashiers_for_owner(self, owner_id: str) -> List[Dict[str, Any]]:
        """Comptes caissiers rattachés à un propriétaire (owner_id)."""
        oid = str(owner_id or "").strip()
        if not oid:
            return []
        docs = (
            self._col("users")
            .where(filter=FieldFilter("owner_id", "==", oid))
            .where(filter=FieldFilter("role", "==", "cashier"))
            .stream()
        )
        rows: List[Dict[str, Any]] = []
        for doc in docs:
            data = doc.to_dict() or {}
            data.setdefault("id", doc.id)
            rows.append(data)
        rows.sort(key=lambda r: str(r.get("username") or "").lower())
        return rows

    def delete_user_document(self, user_id: str) -> None:
        """Supprime un document utilisateur (caissier, etc.)."""
        uid = str(user_id or "").strip()
        if not uid:
            raise ValueError("delete_user_document: user_id obligatoire")
        self._col("users").document(uid).delete()

    def allocate_ticket_number(self, owner_id: str) -> str:
        """Numéro unique 6 chiffres (000001–999999), puis boucle, par propriétaire structure."""
        oid = str(owner_id or "").strip()
        if not oid:
            raise ValueError("allocate_ticket_number: owner_id obligatoire")
        doc_ref = self._col("ticket_seq").document(oid)

        @firestore.transactional
        def _allocate(transaction, ref):
            snap = ref.get(transaction=transaction)
            if snap.exists:
                cur = int((snap.to_dict() or {}).get("next") or 1)
            else:
                cur = 1
            allocated = cur
            nxt = cur + 1
            if nxt > 999999:
                nxt = 1
            transaction.set(ref, {"next": nxt, "updated_at": datetime.utcnow().isoformat()}, merge=True)
            return allocated

        txn = self._client.transaction()
        num = _allocate(txn, doc_ref)
        return f"{num:06d}"

    def attach_owner_to_unowned_qr(self, owner_id: str) -> int:
        """Attache owner_id aux QR historiques qui n'ont pas encore de propriétaire."""
        oid = str(owner_id or "").strip()
        if not oid:
            return 0
        docs = self._col("qr_codes").limit(10000).stream()
        count = 0
        for doc in docs:
            data = doc.to_dict() or {}
            if str(data.get("owner_id") or "").strip():
                continue
            self._col("qr_codes").document(doc.id).update({"owner_id": oid})
            count += 1
        return count

    # ---------- QR codes ----------
    def init_schema(self):
        """Crée les collections logiques de base (lazy dans Firestore)."""
        # Firestore est schema-less. Méthode conservée pour compatibilité.
        return True

    def qr_hash_exists(
        self,
        qr_hash: str,
        owner_id: Optional[str] = None,
        exclude_qr_id: Optional[str] = None,
    ) -> bool:
        q = self._col("qr_codes").where(filter=FieldFilter("qr_hash", "==", qr_hash))
        if owner_id:
            q = q.where(filter=FieldFilter("owner_id", "==", owner_id))
        q = q.limit(5)
        ex = str(exclude_qr_id or "").strip()
        for doc in q.stream():
            if ex and doc.id == ex:
                continue
            return True
        return False

    def create_qr(self, qr_record: Dict[str, Any]):
        record = dict(qr_record)
        record.setdefault("created_at", datetime.utcnow().isoformat())
        record.setdefault("printed_at", None)
        record.setdefault("is_active", True)
        if record.get("expiration_date") is not None and record.get("expiration_ts") is None:
            ts = _iso_datetime_to_ts(record.get("expiration_date"))
            if ts is not None:
                record["expiration_ts"] = ts
        self._col("qr_codes").document(record["id"]).set(record)
        return record["id"]

    def import_qr_document(self, qr_record: Dict[str, Any]) -> None:
        """Écrit un document QR tel quel (migration SQLite). Pas de contrôle d'unicité du hash."""
        record = dict(qr_record)
        if not record.get("id"):
            raise ValueError("import_qr_document: champ id obligatoire")
        ia = record.get("is_active", True)
        if isinstance(ia, int):
            record["is_active"] = bool(ia)
        else:
            record["is_active"] = bool(ia) if ia is not None else True
        if record.get("printed_at") in ("", None):
            record["printed_at"] = None
        if record.get("expiration_date") is not None and record.get("expiration_ts") is None:
            ts = _iso_datetime_to_ts(record.get("expiration_date"))
            if ts is not None:
                record["expiration_ts"] = ts
        self._col("qr_codes").document(str(record["id"])).set(record)

    def get_qr(self, qr_id: str, owner_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        snap = self._col("qr_codes").document(qr_id).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        if owner_id and str(data.get("owner_id") or "") != str(owner_id):
            return None
        data.setdefault("id", qr_id)
        return data

    def update_qr_printed_at(self, qr_id: str, printed_at_iso: str, owner_id: Optional[str] = None):
        if owner_id:
            existing = self.get_qr(qr_id, owner_id=owner_id)
            if not existing:
                raise ValueError("QR introuvable pour ce compte")
        self._col("qr_codes").document(qr_id).update({"printed_at": printed_at_iso})

    def update_qr_fields(self, qr_id: str, updates: Dict[str, Any], owner_id: Optional[str] = None) -> bool:
        """Mise à jour partielle d'un document QR (ex. prolongation : qr_data, expiration, is_active)."""
        qid = str(qr_id or "").strip()
        if not qid or not updates:
            return False
        if owner_id:
            if not self.get_qr(qid, owner_id=owner_id):
                return False
        self._col("qr_codes").document(qid).update(dict(updates))
        return True

    def delete_qr(self, qr_id: str, owner_id: Optional[str] = None) -> bool:
        ref = self._col("qr_codes").document(qr_id)
        if not ref.get().exists:
            return False
        if owner_id:
            data = ref.get().to_dict() or {}
            if str(data.get("owner_id") or "") != str(owner_id):
                return False
        ref.delete()
        return True

    def _sort_rows_by_created_at_desc(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        def sort_key(r: Dict[str, Any]) -> str:
            return str(r.get("created_at") or "")

        return sorted(rows, key=sort_key, reverse=True)

    def _stream_limited(self, query, max_docs: int, label: str) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for i, doc in enumerate(query.stream()):
            if i >= max_docs:
                logger.warning("%s: plafond LIST_QR_FETCH_MAX atteint (%s documents lus)", label, max_docs)
                break
            item = doc.to_dict() or {}
            item.setdefault("id", doc.id)
            rows.append(item)
        return rows

    def _list_qr_legacy_created_window(self, oid: str, cap: int) -> List[Dict[str, Any]]:
        """Repli : N derniers docs par created_at (anciens tickets sans expiration_ts)."""
        query = self._col("qr_codes")
        query = query.where(filter=FieldFilter("owner_id", "==", oid))
        query = query.order_by("created_at", direction=firestore.Query.DESCENDING)
        return self._stream_limited(query, cap, "list_qr legacy created_at")

    def _fetch_rows_active(self, oid: str, cap: int) -> List[Dict[str, Any]]:
        """QR encore valides : index expiration_ts + is_active (tri affichage = created_at)."""
        now_ts = _now_ts()
        q = self._col("qr_codes")
        q = q.where(filter=FieldFilter("owner_id", "==", oid))
        q = q.where(filter=FieldFilter("is_active", "==", True))
        q = q.where(filter=FieldFilter("expiration_ts", ">", now_ts))
        q = q.order_by("expiration_ts", direction=firestore.Query.DESCENDING)
        rows = self._stream_limited(q, cap, "list_qr active")
        return self._sort_rows_by_created_at_desc(rows)

    def _fetch_rows_all(self, oid: str, cap: int) -> List[Dict[str, Any]]:
        q = self._col("qr_codes")
        q = q.where(filter=FieldFilter("owner_id", "==", oid))
        q = q.order_by("created_at", direction=firestore.Query.DESCENDING)
        return self._stream_limited(q, cap, "list_qr tous")

    def _fetch_rows_expired(self, oid: str, cap: int) -> List[Dict[str, Any]]:
        """Réunion : désactivés OU date dépassée (expiration_ts). Dédup par id."""
        now_ts = _now_ts()
        by_id: Dict[str, Dict[str, Any]] = {}

        q_inactive = self._col("qr_codes")
        q_inactive = q_inactive.where(filter=FieldFilter("owner_id", "==", oid))
        q_inactive = q_inactive.where(filter=FieldFilter("is_active", "==", False))
        q_inactive = q_inactive.order_by("created_at", direction=firestore.Query.DESCENDING)
        for row in self._stream_limited(q_inactive, cap, "list_qr expirés (inactifs)"):
            by_id[str(row.get("id"))] = row

        q_date = self._col("qr_codes")
        q_date = q_date.where(filter=FieldFilter("owner_id", "==", oid))
        q_date = q_date.where(filter=FieldFilter("expiration_ts", "<=", now_ts))
        q_date = q_date.order_by("expiration_ts", direction=firestore.Query.DESCENDING)
        for row in self._stream_limited(q_date, cap, "list_qr expirés (date)"):
            by_id[str(row.get("id"))] = row

        rows = list(by_id.values())
        return self._sort_rows_by_created_at_desc(rows)

    def list_qr(self, filters: QueryFilters, owner_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Liste filtrée : requêtes Firestore alignées sur le statut (plus seulement les N derniers créés).
        Nécessite le champ expiration_ts sur les documents (rempli à la création / import).
        """
        cap = max(filters.limit, 1)
        ft = (filters.filter_type or "all").strip().lower()
        if ft not in ("all", "active", "expired"):
            ft = "all"

        oid = str(owner_id or "").strip()
        if not oid:
            query = self._col("qr_codes")
            query = query.order_by("created_at", direction=firestore.Query.DESCENDING)
            rows = self._stream_limited(query, cap, "list_qr sans owner")
            return self._apply_filters(rows, filters)

        rows: List[Dict[str, Any]] = []
        try:
            if ft == "active":
                rows = self._fetch_rows_active(oid, cap)
            elif ft == "expired":
                rows = self._fetch_rows_expired(oid, cap)
            else:
                rows = self._fetch_rows_all(oid, cap)
        except GoogleAPICallError:
            raise
        except Exception as e:
            logger.warning("list_qr requête indexée impossible (%s), repli fenêtre created_at: %s", ft, e)
            rows = self._list_qr_legacy_created_window(oid, cap)

        return self._apply_filters(rows, filters)

    def _apply_filters(self, rows: List[Dict[str, Any]], filters: QueryFilters) -> List[Dict[str, Any]]:
        # Aligné sur expiration_date stockée (datetime.now().isoformat() à la création).
        now = datetime.now()
        out: List[Dict[str, Any]] = []
        search_l = (filters.search or "").strip().lower()
        ticket_l = (filters.ticket or "").strip().lower()
        date_from = (filters.date_from or "").strip()
        date_to = (filters.date_to or "").strip()

        for row in rows:
            expiration_str = str(row.get("expiration_date") or "")
            created_str = str(row.get("created_at") or "")
            is_active = bool(row.get("is_active", True))

            is_expired = False
            try:
                exp_dt = datetime.fromisoformat(expiration_str)
                is_expired = now > exp_dt
            except Exception:
                pass

            if filters.filter_type == "active" and (not is_active or is_expired):
                continue
            if filters.filter_type == "expired" and (is_active and not is_expired):
                continue

            haystack = " ".join(
                [
                    str(row.get("client_name") or ""),
                    str(row.get("client_firstname") or ""),
                    str(row.get("client_email") or ""),
                    str(row.get("client_address") or ""),
                    str(row.get("client_phone") or ""),
                    str(row.get("subscription_type") or ""),
                    str(row.get("payment_mode") or ""),
                ]
            ).lower()
            if search_l and search_l not in haystack:
                continue

            ticket_val = str(row.get("ticket_number") or "").lower()
            if ticket_l and ticket_l not in ticket_val:
                continue

            # Filtre date: compare YYYY-MM-DD sur created_at ISO.
            created_date = created_str[:10] if len(created_str) >= 10 else ""
            if date_from and created_date and created_date < date_from:
                continue
            if date_to and created_date and created_date > date_to:
                continue

            auth = (filters.author_account_id or "").strip()
            owner_scope = (filters.author_scope_owner_id or "").strip()
            if auth:
                raw_creator = str(row.get("created_by_user_id") or "").strip()
                if owner_scope and auth == owner_scope:
                    if raw_creator and raw_creator != owner_scope:
                        continue
                else:
                    if raw_creator != auth:
                        continue

            out.append(row)
        return out

    def cleanup_expired_qr(self) -> int:
        """Désactive les QR dont expiration_ts est dépassé (champ requis pour la requête)."""
        now_ts = _now_ts()
        q = self._col("qr_codes")
        q = q.where(filter=FieldFilter("is_active", "==", True))
        q = q.where(filter=FieldFilter("expiration_ts", "<=", now_ts))
        q = q.order_by("expiration_ts", direction=firestore.Query.DESCENDING)
        count = 0
        for doc in q.stream():
            self._col("qr_codes").document(doc.id).update({"is_active": False})
            count += 1
        return count

