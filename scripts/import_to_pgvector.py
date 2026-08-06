import os
import sys
import json
import time
import sqlite3
import uuid
import hashlib
from datetime import datetime, timezone
from google import genai
from sqlalchemy import create_engine, text

sys.stdout.reconfigure(encoding='utf-8')

KEY_FILE = r'C:\Users\Namdr\Downloads\LEARN_AI IN ACTION\full api key.txt'
CATALOG_DB = r'data/staging/vmec_catalog.sqlite3'
POSTGRES_URL = 'postgresql+psycopg://vmec:vmec_dev_password_change_me@127.0.0.1:5432/vmec'
PROGRESS_FILE = r'data/pgvector_import_progress.json'
BATCH_SIZE = 35

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

class MultiKeyPgvectorImporter:
    def __init__(self, keys: list[str], pg_url: str):
        self.keys = keys
        self.clients = [genai.Client(api_key=k) for k in keys]
        self.models = ['models/gemini-embedding-2', 'models/gemini-embedding-001']
        self.current_worker = 0
        self.total_workers = len(self.clients) * len(self.models)
        self.engine = create_engine(pg_url, pool_pre_ping=True)

    def get_next_worker(self):
        client_idx = (self.current_worker // len(self.models)) % len(self.clients)
        model_idx = self.current_worker % len(self.models)
        self.current_worker = (self.current_worker + 1) % self.total_workers
        model_id = 'gemini-embedding-2' if 'embedding-2' in self.models[model_idx] else 'gemini-embedding-001'
        return self.clients[client_idx], self.models[model_idx], model_id, client_idx + 1

    def embed_batch_with_retry(self, texts: list[str], max_retries: int = 5):
        for attempt in range(max_retries):
            client, model_name, model_id, key_num = self.get_next_worker()
            try:
                res = client.models.embed_content(
                    model=model_name,
                    contents=texts,
                    config={'output_dimensionality': 768}
                )
                embeddings = [e.values for e in res.embeddings]
                return embeddings, model_id, key_num
            except Exception as e:
                err_msg = str(e)
                if '429' in err_msg or 'quota' in err_msg.lower() or 'resource' in err_msg.lower():
                    time.sleep(3 * (attempt + 1))
                else:
                    time.sleep(1)
        raise RuntimeError('Failed batch embedding after max retries')

    def run(self):
        print('=== VMEC-01 POSTGRESQL + PGVECTOR MULTI-KEY IMPORTER ===', flush=True)
        print('Active Keys:', len(self.keys), '| Workers:', self.total_workers, flush=True)
        if not os.path.exists(CATALOG_DB):
            print('Catalog DB not found:', CATALOG_DB, flush=True)
            return

        sq_conn = sqlite3.connect(CATALOG_DB)
        rows = sq_conn.execute('SELECT row_key, payload_json, content_hash FROM dataset_rows WHERE payload_json IS NOT NULL AND length(payload_json) > 10').fetchall()
        sq_conn.close()

        total_rows = len(rows)
        print('Total rows found:', total_rows, flush=True)

        progress = load_progress()
        start_idx = progress['last_processed_index']
        total_processed = progress['total_processed']
        start_time = progress.get('start_time', time.time())

        print('Resuming from index:', start_idx, '/', total_rows, flush=True)

        rec_sql = text("""INSERT INTO knowledge_records (id, release_id, mode, origin_table, origin_row_id, normalized_text, content_hash, canonical_status) VALUES (:id, '9ca746dc-b662-5d1a-87c3-ad214f95dc88'::uuid, 'development', 'vmec_catalog', :r_key, :txt, :c_hash, 'APPROVED') ON CONFLICT (id) DO NOTHING""")
        chunk_sql = text("""INSERT INTO knowledge_chunks (id, record_id, ordinal, normalized_text, token_count, content_hash) VALUES (:id, :rec_id, 0, :txt, :token_cnt, :c_hash) ON CONFLICT (id) DO NOTHING""")
        emb_sql = text("""INSERT INTO knowledge_embeddings (chunk_id, model_id, dimensions, embedding, content_hash, status, embedded_at) VALUES (:chunk_id, :model_id, 768, :embedding, :c_hash, 'ready', NOW()) ON CONFLICT (chunk_id, model_id) DO NOTHING""")

        for i in range(start_idx, total_rows, BATCH_SIZE):
            batch_rows = rows[i:i + BATCH_SIZE]
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

            embeddings, model_id, key_num = self.embed_batch_with_retry(texts)

            with self.engine.begin() as conn:
                for idx_in_batch, (vec, (r_key, s_id, txt, c_hash)) in enumerate(zip(embeddings, metadata_list)):
                    rec_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, r_key + ':' + c_hash))
                    chunk_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, rec_id + ':chunk:0'))

                    conn.execute(rec_sql, {'id': rec_id, 'r_key': r_key, 'txt': txt, 'c_hash': c_hash})
                    conn.execute(chunk_sql, {'id': chunk_id, 'rec_id': rec_id, 'txt': txt, 'token_cnt': len(txt.split()), 'c_hash': c_hash})
                    conn.execute(emb_sql, {'chunk_id': chunk_id, 'model_id': model_id, 'embedding': str(vec), 'c_hash': c_hash})

            total_processed += len(batch_rows)
            current_end_idx = min(i + BATCH_SIZE, total_rows)
            save_progress(current_end_idx, total_processed, start_time)

            elapsed = time.time() - start_time
            rate = total_processed / elapsed if elapsed > 0 else 0
            pct = round((current_end_idx / total_rows) * 100, 1)

            print('[BATCH]', current_end_idx, '/', total_rows, '(', pct, '%) | Key #', key_num, '| Model:', model_id, '| Rate:', round(rate * 60), 'rec/min', flush=True)
            time.sleep(1.2)

        print('SUCCESS: All records imported into PostgreSQL pgvector!', flush=True)

if __name__ == '__main__':
    keys = load_keys()
    importer = MultiKeyPgvectorImporter(keys, POSTGRES_URL)
    importer.run()
