import sqlite3
import json
import sys
import os
from collections import Counter

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")

def audit():
    catalog_path = "data/staging/vmec_catalog.sqlite3"
    conn = sqlite3.connect(catalog_path)
    cur = conn.cursor()

    release_id = "vmec-development-v2"

    print("=======================================================")
    print("1. RELEASE STATUS & TABLES IN CATALOG")
    print("=======================================================")
    cur.execute("SELECT release_id, status FROM dataset_releases")
    releases = cur.fetchall()
    for r in releases:
        print(f"Release: {r[0]} | Status: {r[1]}")

    cur.execute("SELECT table_name, COUNT(*) FROM dataset_rows WHERE release_id=? GROUP BY table_name ORDER BY COUNT(*) DESC", (release_id,))
    tables = cur.fetchall()
    print(f"\nTotal tables in release '{release_id}': {len(tables)}")
    for t_name, cnt in tables[:25]:
        print(f"  - {t_name:35}: {cnt:6} rows")
    if len(tables) > 25:
        print(f"  ... and {len(tables) - 25} more tables")

    print("\n=======================================================")
    print("2. GLOBAL SOURCES LEDGER & CITATION MAP")
    print("=======================================================")
    cur.execute("SELECT payload_json FROM global_sources WHERE release_id=?", (release_id,))
    sources_raw = cur.fetchall()
    global_source_ids = set()
    local_to_global_map = {}
    for (raw,) in sources_raw:
        p = json.loads(raw)
        g_id = str(p.get("global_source_id", "")).strip()
        l_id = str(p.get("source_id", "")).strip()
        if g_id:
            global_source_ids.add(g_id)
        if l_id and g_id:
            local_to_global_map[l_id] = g_id
    print(f"Total Global Sources: {len(global_source_ids)}")
    print(f"Total Local-to-Global Aliases: {len(local_to_global_map)}")

    print("\n=======================================================")
    print("3. SPECIALTY CODES AUDIT ACROSS ALL TABLES")
    print("=======================================================")
    cur.execute("SELECT payload_json FROM dataset_rows WHERE release_id=? AND table_name='specialty_reference'", (release_id,))
    canonical_specs = {json.loads(r[0]).get("specialty_code") for r in cur.fetchall()}
    print(f"Canonical Specialty Codes ({len(canonical_specs)}):", sorted(list(canonical_specs)))

    # From routing.py
    from src.services.routing import SPECIALTY_CODE_MAP

    all_raw_specialty_codes = Counter()
    unmapped_specialty_codes = Counter()
    mapped_counts = Counter()

    cur.execute("SELECT table_name, payload_json FROM dataset_rows WHERE release_id=?", (release_id,))
    for t_name, raw in cur.fetchall():
        p = json.loads(raw)
        for key in ("primary_specialty_code", "specialty_code", "secondary_specialty_code", "suggested_specialty_code"):
            val = p.get(key)
            if val and isinstance(val, str) and val.strip():
                code = val.strip()
                all_raw_specialty_codes[code] += 1
                mapped = SPECIALTY_CODE_MAP.get(code, code)
                if mapped in canonical_specs:
                    mapped_counts[mapped] += 1
                else:
                    unmapped_specialty_codes[code] += 1

    print("\nAll Raw Specialty Codes Encountered:")
    for code, cnt in all_raw_specialty_codes.most_common():
        mapped = SPECIALTY_CODE_MAP.get(code, code)
        status = "OK -> " + mapped if mapped in canonical_specs else "UNMAPPED!"
        print(f"  {code:30} : {cnt:6} occurrences | {status}")

    print("\nUnmapped Specialty Codes Summary:")
    if not unmapped_specialty_codes:
        print("  NONE! All specialty codes are 100% mapped to canonical specialties!")
    else:
        for code, cnt in unmapped_specialty_codes.most_common():
            print(f"  [WARNING] {code:30} : {cnt:6} unmapped occurrences")

    print("\n=======================================================")
    print("4. ROUTING_ROWS COVERAGE AUDIT")
    print("=======================================================")
    cur.execute("SELECT row_key, payload_json FROM dataset_rows WHERE release_id=? AND table_name='routing_rows'", (release_id,))
    routing_rows = cur.fetchall()
    total_routing = len(routing_rows)

    routing_by_canonical_spec = Counter()
    missing_text_count = 0
    missing_source_count = 0
    unmapped_citation_count = 0

    text_fields = ("user_utterance_vi", "utterance_vi", "question_text_vi", "response_text_vi")

    for r_key, raw in routing_rows:
        p = json.loads(raw)
        raw_code = str(p.get("primary_specialty_code", "")).strip()
        mapped_spec = SPECIALTY_CODE_MAP.get(raw_code, raw_code)
        
        if mapped_spec in canonical_specs:
            routing_by_canonical_spec[mapped_spec] += 1

        text = next((str(p.get(f, "")).strip() for f in text_fields if p.get(f)), "")
        if not text:
            missing_text_count += 1

        source_values = (p.get("source_id"), p.get("source_ids"), p.get("primary_source_id"), p.get("secondary_source_id"))
        s_ids = [str(v).strip() for v in source_values if v and str(v).strip()]
        if not s_ids:
            missing_source_count += 1
        else:
            resolved = False
            for sid in s_ids:
                if sid in global_source_ids or sid in local_to_global_map:
                    resolved = True
                    break
            if not resolved:
                unmapped_citation_count += 1

    print(f"Total routing_rows: {total_routing}")
    print(f"Rows with valid text: {total_routing - missing_text_count} / {total_routing}")
    print(f"Rows with valid citation source: {total_routing - missing_source_count} / {total_routing}")
    print(f"Unmapped citation rows: {unmapped_citation_count}")
    print("\nBreakdown of Routing Rows per Canonical Specialty:")
    for spec_code in sorted(list(canonical_specs)):
        cnt = routing_by_canonical_spec[spec_code]
        pct = (cnt / total_routing) * 100
        print(f"  - {spec_code:25} : {cnt:6} rows ({pct:5.1f}%)")

    conn.close()

if __name__ == "__main__":
    audit()
