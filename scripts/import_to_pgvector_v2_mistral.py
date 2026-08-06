import os
import sys
import json
import time
import sqlite3
import uuid
import hashlib
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from sqlalchemy import create_engine, text

sys.stdout.reconfigure(encoding='utf-8')

KEY_FILE = r"C:\Users\Namdr\Downloads\mistral api key.txt"
CATALOG_DB = r"data/staging/vmec_catalog.sqlite3"
POSTGRES_URL = "postgresql+psycopg://vmec:vmec_dev_password_change_me@127.0.0.1:5432/vmec"
PROGRESS_FILE = r"data/mistral_v2_import_progress.json"
BATCH_SIZE = 200
NUM_WORKERS = 8

def load_keys():
    with open(KEY_FILE, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip()]

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {'last_processed_index': 0, 'total_processed': 0, 'start_time': time.time()}

def save_progress(index, count, start_time):
    os.makedirs('data', exist_ok=True)
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump({
            'last_processed_index': index,
            'total_processed': count,
            'start_time': start_time,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }, f, indent=2)

class MistralV2PgvectorImporter:
    def __init__(self, keys, pg_url):
        self.keys = keys
        self.model_name = 'mistral-embed'
        self.model_id = 'mistral-embed-2312'
        self.engine = create_engine(pg_url, pool_size=20, max_overflow=30, pool_pre_ping=True)

    def embed_batch_with_key(self, texts, key, key_num, max_retries=5):
        for attempt in range(max_retries):
            req = urllib.request.Request(
                'https://api.mistral.ai/v1/embeddings',
                data=json.dumps({'model': self.model_name, 'input': texts}).encode('utf-8'),
                headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key}
            )
            try:
                with urllib.request.urlopen(req) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    embeddings = [item['embedding'] for item in data['data']]
                    return embeddings, key_num
            except Exception as e:
                err_msg = str(e)
                if '429' in err_msg or 'rate' in err_msg.lower():
                    time.sleep(2.0 * (attempt + 1))
                else:
                    time.sleep(1.0)
        raise RuntimeError(f'Failed Mistral batch embedding after retries on key #{key_num}')

    def process_chunk_batch(self, batch_rows, key, key_num):
        texts = []
        metadata_list = []
        for r_key, payload_str, c_hash in batch_rows:
            try:
                payload = json.loads(payload_str)
                s_id = payload.get('specialty_id', 'SP_GENERAL_MEDICINE')
                txt = payload.get('symptom_text') or payload.get('text') or payload.get('content') or payload_str[:500]
            except Exception:
                s_id = 'SP_GENERAL_MEDICINE'
                txt = payload_str[:500]

            texts.append(txt[:1000])
            metadata_list.append((r_key, s_id, txt[:2000], c_hash or hashlib.sha256(txt.encode('utf-8')).hexdigest()))

        embeddings, key_num = self.embed_batch_with_key(texts, key, key_num)

        get_rec_sql = text("""SELECT id FROM knowledge_records WHERE release_id = '9ca746dc-b662-5d1a-87c3-ad214f95dc88'::uuid AND origin_table = 'vmec_catalog' AND origin_row_id = :r_key""")
        ins_rec_sql = text("""INSERT INTO knowledge_records (id, release_id, mode, origin_table, origin_row_id, normalized_text, content_hash, canonical_status) VALUES (CAST(:id AS uuid), '9ca746dc-b662-5d1a-87c3-ad214f95dc88'::uuid, 'development', 'vmec_catalog', :r_key, :txt, :c_hash, 'APPROVED') ON CONFLICT (release_id, origin_table, origin_row_id) DO NOTHING RETURNING id""")

        get_chunk_sql = text("""SELECT id FROM knowledge_chunks WHERE record_id = CAST(:rec_id AS uuid) AND ordinal = 0""")
        ins_chunk_sql = text("""INSERT INTO knowledge_chunks (id, record_id, ordinal, normalized_text, token_count, content_hash) VALUES (CAST(:id AS uuid), CAST(:rec_id AS uuid), 0, :txt, :token_cnt, :c_hash) ON CONFLICT (record_id, ordinal) DO NOTHING RETURNING id""")

        emb_sql = text("""INSERT INTO knowledge_embeddings (chunk_id, model_id, dimensions, embedding, content_hash, status, embedded_at) VALUES (CAST(:chunk_id AS uuid), :model_id, 1024, :embedding, :c_hash, 'ready', NOW()) ON CONFLICT (chunk_id, model_id) DO UPDATE SET embedding = EXCLUDED.embedding, embedded_at = NOW()""")

        with self.engine.begin() as conn:
            for idx_in_batch, (vec, (r_key, s_id, txt, c_hash)) in enumerate(zip(embeddings, metadata_list)):
                row = conn.execute(get_rec_sql, {'r_key': r_key}).fetchone()
                if row:
                    real_rec_id = str(row[0])
                else:
                    rec_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, r_key + ':' + c_hash))
                    res = conn.execute(ins_rec_sql, {'id': rec_id, 'r_key': r_key, 'txt': txt, 'c_hash': c_hash}).fetchone()
                    real_rec_id = str(res[0]) if res else rec_id

                ch_row = conn.execute(get_chunk_sql, {'rec_id': real_rec_id}).fetchone()
                if ch_row:
                    real_chunk_id = str(ch_row[0])
                else:
                    chunk_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, real_rec_id + ':chunk:0'))
                    c_res = conn.execute(ins_chunk_sql, {'id': chunk_id, 'rec_id': real_rec_id, 'txt': txt, 'token_cnt': len(txt.split()), 'c_hash': c_hash}).fetchone()
                    real_chunk_id = str(c_res[0]) if c_res else chunk_id

                conn.execute(emb_sql, {'chunk_id': real_chunk_id, 'model_id': self.model_id, 'embedding': str(vec), 'c_hash': c_hash})

        return len(batch_rows)

    def run(self):
        num_workers = len(self.keys)
        print('=== VERSION 2.0 HIGH-SPEED PARALLEL MISTRAL IMPORTER ===', flush=True)
        print('Active Mistral Keys:', num_workers, '| Parallel Threads:', num_workers, flush=True)
        if not os.path.exists(CATALOG_DB):
            print('Catalog DB not found:', CATALOG_DB, flush=True)
            return

        sq_conn = sqlite3.connect(CATALOG_DB)
        rows = sq_conn.execute('SELECT row_key, payload_json, content_hash FROM dataset_rows WHERE payload_json IS NOT NULL AND length(payload_json) > 10').fetchall()
        sq_conn.close()

        total_rows = len(rows)
        print('Total catalog rows found:', total_rows, flush=True)

        progress = load_progress()
        start_idx = progress['last_processed_index']
        total_processed = progress['total_processed']
        start_time = progress.get('start_time', time.time())

        print('Resuming Version 2 from index:', start_idx, '/', total_rows, flush=True)

        all_batches = []
        for i in range(start_idx, total_rows, BATCH_SIZE):
            all_batches.append((i, min(i + BATCH_SIZE, total_rows), rows[i:i + BATCH_SIZE]))

        for group_idx in range(0, len(all_batches), num_workers):
            group = all_batches[group_idx:group_idx + num_workers]
            
            with ThreadPoolExecutor(max_workers=num_workers) as executor:
                futures = []
                for w_idx, (b_start, b_end, batch_rows) in enumerate(group):
                    key = self.keys[w_idx % len(self.keys)]
                    key_num = (w_idx % len(self.keys)) + 1
                    futures.append(executor.submit(self.process_chunk_batch, batch_rows, key, key_num))

                for future in as_completed(futures):
                    count_done = future.result()
                    total_processed += count_done

            last_end_idx = group[-1][1]
            save_progress(last_end_idx, total_processed, start_time)

            elapsed = time.time() - start_time
            rate = total_processed / elapsed if elapsed > 0 else 0
            pct = round((last_end_idx / total_rows) * 100, 2)

            print(f'[V2 PARALLEL] {last_end_idx:,} / {total_rows:,} ({pct}%) | Speed: {round(rate * 60):,} rec/min', flush=True)
            time.sleep(0.3)

        print('SUCCESS: All records imported into PostgreSQL pgvector for Version 2!', flush=True)

if __name__ == '__main__':
    keys = load_keys()
    importer = MistralV2PgvectorImporter(keys, POSTGRES_URL)
    importer.run()
