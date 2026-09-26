"""Where saved calendars live.

- Local dev (default): one JSON file per calendar in data/
- Deployed: Firebase Firestore, used automatically when FIREBASE_CREDENTIALS
  (the service-account JSON, pasted as an env var) or GOOGLE_APPLICATION_CREDENTIALS is set.
  Free-tier servers (e.g. Render) wipe local files on restart, so production needs Firestore.
"""
import json
import os
from pathlib import Path

COLLECTION = os.getenv("FIRESTORE_COLLECTION", "calendars")


class FileStore:
    kind = "file"

    def __init__(self, root: Path):
        self.root = root
        root.mkdir(exist_ok=True)

    def get(self, cal_id: str) -> dict | None:
        p = self.root / f"{cal_id}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def put(self, cal_id: str, data: dict) -> None:
        (self.root / f"{cal_id}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


class FirestoreStore:
    kind = "firestore"

    def __init__(self):
        import firebase_admin
        from firebase_admin import credentials, firestore

        raw = os.getenv("FIREBASE_CREDENTIALS", "").strip()
        if raw:
            cred = credentials.Certificate(json.loads(raw))
        else:  # GOOGLE_APPLICATION_CREDENTIALS points at the JSON file
            cred = credentials.ApplicationDefault()
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
        self.col = firestore.client().collection(COLLECTION)

    def get(self, cal_id: str) -> dict | None:
        snap = self.col.document(cal_id).get()
        if not snap.exists:
            return None
        # stored as a JSON string: avoids Firestore's nested-array rules and keeps it one read
        return json.loads(snap.to_dict()["json"])

    def put(self, cal_id: str, data: dict) -> None:
        self.col.document(cal_id).set({"json": json.dumps(data, ensure_ascii=False),
                                       "updated_at": data.get("updated_at", "")})


def make_store(data_dir: Path):
    if os.getenv("FIREBASE_CREDENTIALS") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        store = FirestoreStore()
    else:
        store = FileStore(data_dir)
    print(f"[storage] using {store.kind}")
    return store
