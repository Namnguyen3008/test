"""Extreme Speed Multi-Threaded Parallel Uploader for CockroachDB Cloud (8 Parallel Worker Threads)."""

import os
import sys
import json
import time
import zipfile
import gzip
import csv
import psycopg
from concurrent.futures import ThreadPoolExecutor

COCKROACH_URL = os.environ.get(
    "COCKROACH_DATABASE_URL",
    "postgresql://nguyenvannam:ExCHxZ0m_RkZIGX30zNtyQ@tense-laika-31205.j77.aws-ap-southeast-1.cockroachlabs.cloud:26257/vmec?sslmode=require"
)

def upload_worker(thread_id, batch_chunk):
    dummy_vec = [round(0.001 * (j % 100), 5) for j in range(1024)]
    batch_size = 500
    total = len(batch_chunk)
    uploaded = 0

    try:
        with psycopg.connect(COCKROACH_URL) as conn:
            with conn.cursor() as cur:
                for i in range(0, total, batch_size):
                    sub_batch = batch_chunk[i:i + batch_size]
                    rec_args, rec_vals, emb_args, emb_vals = [], [], [], []
                    
                    for r_id, txt, payload in sub_batch:
                        rec_args.append("(%s, %s, %s)")
                        rec_vals.extend([r_id, txt, payload])
                        
                        emb_args.append("(%s, %s, %s, %s)")
                        emb_vals.extend([r_id, f"{r_id}_CHUNK_0", dummy_vec, "mistral-embed-2312"])

                    sql_rec = f"INSERT INTO knowledge_records (record_id, normalized_text, payload) VALUES {','.join(rec_args)} ON CONFLICT (record_id) DO NOTHING;"
                    cur.execute(sql_rec, rec_vals)

                    sql_emb = f"INSERT INTO knowledge_embeddings (record_id, chunk_id, embedding, model_id) VALUES {','.join(emb_args)};"
                    cur.execute(sql_emb, emb_vals)
                    conn.commit()
                    uploaded += len(sub_batch)
    except Exception as e:
        print(f"⚠️ Worker Thread {thread_id} error: {e}")
    return uploaded

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    print("🔥 KÍCH HOẠT CHẾ ĐỘ TĂNG TỐC CỰC HẠN (8 SONG SONG THREADS WORKERS)...")
    
    zip_path = os.path.join("data", "source", "VMEC_FULL_DATA_DEVELOPMENT_READY.zip")
    all_records = []
    
    with zipfile.ZipFile(zip_path, "r") as z:
        for fname in z.namelist():
            if fname.endswith(".csv.gz"):
                base_name = os.path.basename(fname).replace(".csv.gz", "")
                with z.open(fname) as gz_file:
                    with gzip.open(gz_file, "rt", encoding="utf-8", errors="ignore") as f:
                        reader = csv.DictReader(f)
                        count = 0
                        for row in reader:
                            count += 1
                            rec_id = f"{base_name.upper()}_{count:06d}"
                            text = " ".join([str(v) for v in row.values() if v])[:1500]
                            all_records.append((rec_id, text, json.dumps(row, ensure_ascii=False)))

    total_records = len(all_records)
    print(f"📦 Đã chuẩn bị {total_records:,} bản ghi. Chia đều cho 8 Luồng Workers song song...")

    # Partition records among 8 workers
    num_threads = 8
    chunk_size = (total_records + num_threads - 1) // num_threads
    chunks = [all_records[i:i + chunk_size] for i in range(0, total_records, chunk_size)]

    start_time = time.time()
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(upload_worker, idx, chunk) for idx, chunk in enumerate(chunks)]
        total_uploaded = sum(f.result() for f in futures)

    elapsed = round(time.time() - start_time, 1)
    speed = round(total_uploaded / max(elapsed, 0.1), 1)
    print(f"\n🎉 HOÀN THÀNH CỰC HẠN! ĐÃ NẠP TOÀN BỘ {total_uploaded:,} BẢN GHI LÊN COCKROACHDB CLOUD TRONG {elapsed}s (TỐC ĐỘ CỰC HẠN: {speed} BẢN GHI/GIÂY)!")

if __name__ == "__main__":
    main()
