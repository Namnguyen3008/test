import sqlite3
import json
import sys
from collections import Counter

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")

from src.services.routing import SPECIALTY_CODE_MAP

# Canonical Vietnamese Specialty Names
CANONICAL_VI_NAMES = {
    "SP_CARDIOLOGY": "Tim mạch",
    "SP_DERMATOLOGY": "Da liễu",
    "SP_ENT": "Tai Mũi Họng",
    "SP_GASTRO": "Tiêu hóa",
    "SP_GENERAL_MEDICINE": "Nội tổng quát / Y học gia đình",
    "SP_INFECTIOUS": "Truyền nhiễm",
    "SP_MENTAL_HEALTH": "Tâm lý - Tâm thần",
    "SP_NEUROLOGY": "Thần kinh",
    "SP_OBGYN": "Sản - Phụ khoa",
    "SP_OPHTHALMOLOGY": "Mắt",
    "SP_ORTHOPEDICS": "Cơ xương khớp - Chấn thương chỉnh hình",
    "SP_PEDIATRICS": "Nhi khoa",
    "SP_RESPIRATORY": "Hô hấp",
    "SP_UROLOGY": "Tiết niệu",
}

def main():
    conn = sqlite3.connect("data/staging/vmec_catalog.sqlite3")
    cur = conn.cursor()

    cur.execute("SELECT payload_json FROM dataset_rows WHERE release_id='vmec-development-v2'")
    counts = Counter()

    for (raw,) in cur.fetchall():
        p = json.loads(raw)
        for key in ("primary_specialty_code", "specialty_code", "secondary_specialty_code", "suggested_specialty_code"):
            val = p.get(key)
            if val and isinstance(val, str) and val.strip():
                counts[val.strip()] += 1

    conn.close()

    print(f"TOTAL DISTINCT RAW SPECIALTY CODE VARIANTS: {len(counts)}\n")
    print(f"{'STT':<4} | {'MÃ BIẾN THỂ (RAW CODE)':<32} | {'SỐ BẢN GHI':<10} | {'MÃ CHUẨN (CANONICAL)':<22} | {'TÊN CHUYÊN KHOA TIẾNG VIỆT'}")
    print("-" * 110)

    for i, (code, cnt) in enumerate(counts.most_common(), 1):
        canonical_code = SPECIALTY_CODE_MAP.get(code, code)
        vi_name = CANONICAL_VI_NAMES.get(canonical_code, "Khác / Chưa phân loại")
        print(f"{i:<4} | {code:<32} | {cnt:<10} | {canonical_code:<22} | {vi_name}")

if __name__ == "__main__":
    main()
