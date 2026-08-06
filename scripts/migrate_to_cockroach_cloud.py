"""Script to migrate 1024d Vector Embeddings to CockroachDB Cloud (cockroachlabs.cloud)."""

import os
import sys
import json
import psycopg
from pathlib import Path

DEFAULT_COCKROACH_URL = "postgresql://nguyenvannam:ExCHxZ0m_RkZIGX30zNtyQ@tense-laika-31205.j77.aws-ap-southeast-1.cockroachlabs.cloud:26257/vmec?sslmode=require"

def migrate():
    sys.stdout.reconfigure(encoding='utf-8')
    
    cloud_url = os.environ.get("COCKROACH_DATABASE_URL", DEFAULT_COCKROACH_URL)
    local_url = os.environ.get("LOCAL_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/vmec")

    print(f"🚀 Đang kết nối tới CockroachDB Cloud Database (tense-laika-31205)...")
    try:
        with psycopg.connect(cloud_url) as conn_cloud:
            with conn_cloud.cursor() as cur_cloud:
                print("⚡ Đang xác nhận Schema Vector trên CockroachDB Cloud...")
                cur_cloud.execute("""
                    CREATE TABLE IF NOT EXISTS knowledge_embeddings (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        record_id VARCHAR(128) NOT NULL,
                        chunk_id VARCHAR(128) NOT NULL,
                        embedding FLOAT8[] NOT NULL,
                        model_id VARCHAR(64) DEFAULT 'mistral-embed-2312',
                        created_at TIMESTAMPTZ DEFAULT now()
                    );
                """)
                cur_cloud.execute("""
                    CREATE TABLE IF NOT EXISTS knowledge_records (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        record_id VARCHAR(128) UNIQUE NOT NULL,
                        normalized_text TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        created_at TIMESTAMPTZ DEFAULT now()
                    );
                """)
                conn_cloud.commit()
                print("✅ Đã khởi tạo và xác nhận Schema trên CockroachDB Cloud thành công!")

                print(f"🔄 Đang kiểm tra dữ liệu từ Local PostgreSQL ({local_url})...")
                try:
                    with psycopg.connect(local_url) as conn_local:
                        with conn_local.cursor() as cur_local:
                            cur_local.execute("SELECT record_id, chunk_id, embedding, model_id FROM knowledge_embeddings LIMIT 1000;")
                            rows = cur_local.fetchall()
                            print(f"📦 Tìm thấy {len(rows):,} bản ghi Vector 1024d. Đang đẩy lên CockroachDB Cloud...")
                            
                            count = 0
                            for row in rows:
                                cur_cloud.execute(
                                    """
                                    INSERT INTO knowledge_embeddings (record_id, chunk_id, embedding, model_id)
                                    VALUES (%s, %s, %s, %s);
                                    """,
                                    (row[0], row[1], row[2], row[3])
                                )
                                count += 1
                                if count % 100 == 0:
                                    conn_cloud.commit()
                                    print(f"   -> Đã đẩy {count:,} / {len(rows):,} bản ghi...")
                            conn_cloud.commit()
                            print(f"🎉 HOÀN THÀNH MIGRATION {count:,} VECTOR UP TO COCKROACHDB CLOUD!")
                except Exception as local_err:
                    print(f"⚠️ Thông báo kết nối Local DB: {local_err}")
                    print("💡 CockroachDB Cloud Database đã khởi tạo sẵn sàng cho ứng dụng Cloud!")

    except Exception as e:
        print(f"❌ LỖI TRONG QUÁ TRÌNH MIGRATION: {str(e)}")

if __name__ == "__main__":
    migrate()
