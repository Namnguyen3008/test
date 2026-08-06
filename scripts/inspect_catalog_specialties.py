import sqlite3
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")

conn = sqlite3.connect("data/staging/vmec_catalog.sqlite3")
cur = conn.cursor()

cur.execute("SELECT payload_json FROM dataset_rows WHERE release_id='vmec-development-v2' AND table_name='routing_rows'")
cardio_rows = []
for (raw,) in cur.fetchall():
    if "tim" in raw.lower() or "mạch" in raw.lower() or "tức ngực" in raw.lower() or "cardio" in raw.lower():
        p = json.loads(raw)
        cardio_rows.append(p)

print(f"Total routing rows related to cardiology terms: {len(cardio_rows)}")
code_counts = {}
for p in cardio_rows:
    c = p.get("primary_specialty_code", "")
    code_counts[c] = code_counts.get(c, 0) + 1

print("Codes used for cardiology terms:", code_counts)
for p in cardio_rows[:3]:
    txt = next((str(p.get(f, "")).strip() for f in ("user_utterance_vi", "utterance_vi", "question_text_vi", "response_text_vi") if p.get(f)), "")
    print(f"  Code [{p.get('primary_specialty_code')}]: {txt[:90]}...")

conn.close()
