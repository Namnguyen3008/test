import sqlite3
import json
import re
import math
import sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8")

_TOKEN = re.compile(r"\w+", re.UNICODE)

SPECIALTY_CODE_MAP = {
    # Direct mappings
    "SP_CARDIOLOGY": "SP_CARDIOLOGY",
    "SP_DERMATOLOGY": "SP_DERMATOLOGY",
    "SP_ENT": "SP_ENT",
    "SP_GASTRO": "SP_GASTRO",
    "SP_GENERAL_MEDICINE": "SP_GENERAL_MEDICINE",
    "SP_INFECTIOUS": "SP_INFECTIOUS",
    "SP_MENTAL_HEALTH": "SP_MENTAL_HEALTH",
    "SP_NEUROLOGY": "SP_NEUROLOGY",
    "SP_OBGYN": "SP_OBGYN",
    "SP_OPHTHALMOLOGY": "SP_OPHTHALMOLOGY",
    "SP_ORTHOPEDICS": "SP_ORTHOPEDICS",
    "SP_PEDIATRICS": "SP_PEDIATRICS",
    "SP_RESPIRATORY": "SP_RESPIRATORY",
    "SP_UROLOGY": "SP_UROLOGY",
    
    # Aliases & abbreviated codes
    "SP_PED": "SP_PEDIATRICS",
    "SP_RESP": "SP_RESPIRATORY",
    "SP_GENERAL_MED": "SP_GENERAL_MEDICINE",
    "SP_GM": "SP_GENERAL_MEDICINE",
    "GENERAL_MEDICINE": "SP_GENERAL_MEDICINE",
    "K17": "SP_GENERAL_MEDICINE",
    "SP_NEURO": "SP_NEUROLOGY",
    "SP_MSK": "SP_ORTHOPEDICS",
    "SP_DERM": "SP_DERMATOLOGY",
    "SP_ALLERGY": "SP_DERMATOLOGY",
    "SPEC_ALLERGY_IMMUNOLOGY": "SP_DERMATOLOGY",
    "K13": "SP_DERMATOLOGY",
    "OTOLARYNGOLOGY": "SP_ENT",
    "OPHTHALMOLOGY": "SP_OPHTHALMOLOGY",
    "UROLOGY": "SP_UROLOGY",
    "NEPHROLOGY": "SP_UROLOGY",
    "ENDOCRINOLOGY": "SP_GENERAL_MEDICINE",
    "HEMATOLOGY": "SP_GENERAL_MEDICINE",
    "SP_INF": "SP_INFECTIOUS",
    "K11": "SP_INFECTIOUS",
    "K27": "SP_OBGYN",
    "K15": "SP_MENTAL_HEALTH",
    "K02.1": "SP_GENERAL_MEDICINE",
    "DENTISTRY_ORAL_MAXILLOFACIAL": "SP_GENERAL_MEDICINE",
}

VI_STOP_WORDS = {
    "tôi", "bị", "có", "từ", "ngày", "nay", "muốn", "cho", "và", "nhưng",
    "rồi", "ở", "trong", "đang", "được", "là", "khi", "lại", "sau", "hơn",
    "mình", "nhà", "ra", "đi", "vào", "thì", "mà", "đã", "các", "những",
    "một", "hai", "ba", "với", "đến", "này", "đó", "hay", "hoặc", "cũng"
}

def extract_ngrams(text: str) -> list[str]:
    tokens = [t.casefold() for t in _TOKEN.findall(text)]
    unigrams = tokens
    bigrams = [" ".join(tokens[i:i+2]) for i in range(len(tokens)-1)]
    trigrams = [" ".join(tokens[i:i+3]) for i in range(len(tokens)-2)]
    return unigrams + bigrams + trigrams

def test_retrieval():
    conn = sqlite3.connect("data/staging/vmec_catalog.sqlite3")
    cur = conn.cursor()
    
    cur.execute("SELECT row_key, payload_json FROM dataset_rows WHERE release_id='vmec-development-v2' AND table_name='routing_rows'")
    records = []
    doc_freq = Counter()
    
    for row_id, raw in cur.fetchall():
        payload = json.loads(raw)
        raw_code = str(payload.get("primary_specialty_code", "")).strip()
        mapped_code = SPECIALTY_CODE_MAP.get(raw_code)
        if not mapped_code:
            continue
            
        text = next((str(payload.get(f, "")).strip() for f in ("user_utterance_vi", "utterance_vi", "question_text_vi", "response_text_vi") if payload.get(f)), "")
        if not text:
            continue
            
        source_id = payload.get("source_id") or payload.get("primary_source_id") or "GLOBAL_SRC_000806"
        all_terms = extract_ngrams(text)
        unique_terms = set(all_terms)
        for t in unique_terms:
            doc_freq[t] += 1
            
        records.append({
            "record_id": row_id,
            "text": text,
            "specialty_id": mapped_code,
            "source_ids": [source_id] if isinstance(source_id, str) else list(source_id),
            "term_counts": Counter(all_terms),
            "term_set": unique_terms
        })
    
    print(f"Total eligible records loaded with mapped specialty: {len(records)}")
    
    N = len(records)
    
    queries = [
        "Trẻ 3 tuổi sốt cao li bì",
        "Tôi bị đau đầu từ sáng nay",
        "Tôi muốn khám răng",
        "Tôi bị đau dạ dày sau khi ăn",
        "Tôi bị ngứa da nổi mề đay",
        "Tôi muốn đặt lịch khám nội tổng quát",
        "Tôi đau mắt đỏ 3 ngày nay",
        "Tôi bị đau khớp gối đi lại khó khăn",
        "Tôi bị đau tức ngực khó thở khi gắng sức"
    ]
    
    for q in queries:
        q_terms = [t for t in extract_ngrams(q) if t not in VI_STOP_WORDS]
        scored = []
        for r in records:
            score = 0.0
            matched_content_terms = 0
            for qt in q_terms:
                if qt in r["term_set"]:
                    tf = r["term_counts"][qt]
                    ngram_len = len(qt.split())
                    mult = 10.0 if ngram_len == 3 else (5.0 if ngram_len == 2 else 1.0)
                    idf = math.log((N - doc_freq[qt] + 0.5) / (doc_freq[qt] + 0.5) + 1.0)
                    score += tf * idf * mult
                    matched_content_terms += 1
            if score > 0 and matched_content_terms > 0:
                scored.append((score, r))
                
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:3]
        print(f"\n=======================================================")
        print(f"QUERY: {q}")
        print(f"Found matches: {len(scored)}")
        for i, (s, r) in enumerate(top):
            print(f"  [{i+1}] Score: {s:.2f} | Specialty: {r['specialty_id']} | Text: {r['text'][:90]}...")
            
    conn.close()

if __name__ == "__main__":
    test_retrieval()
