"""Copy calendars saved locally (data/*.json) into Firestore, keeping the same IDs,
so existing links (?c=...) and phone subscriptions keep working.

Usage (FIREBASE_CREDENTIALS must be set):
    python scripts/migrate_to_firestore.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.storage import FirestoreStore  # noqa: E402

store = FirestoreStore()
files = sorted((ROOT / "data").glob("*.json"))
for f in files:
    cal_id = f.stem
    if store.get(cal_id) is not None:
        print(f"skip {cal_id} (already in Firestore)")
        continue
    store.put(cal_id, json.loads(f.read_text(encoding="utf-8")))
    print(f"copied {cal_id}")
print(f"done: {len(files)} local calendar(s) checked")
