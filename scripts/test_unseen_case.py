import urllib.request, json, time, sys
from sqlalchemy import create_engine, text
sys.stdout.reconfigure(encoding='utf-8')

with open(r'C:\Users\Namdr\Downloads\mistral api key.txt', 'r', encoding='utf-8') as f:
    key = [l.strip() for l in f if l.strip()][0]

unseen_query = 'Bệnh nhân nam 45 tuổi bị sốt rét run từng cơn về chiều kèm theo tức ngực trái lan ra sau lưng, vãi mồ hôi hột, đi kèm dấu hiệu tê bì ngón tay trỏ và mắt nhìn đôi (diplopia).'

print('=== DEMO TÌM KIẾM VECTOR VỚI CA BỆNH PHỨC TẠP / CHƯA TỪNG GẶP (UNSEEN CASE) ===')
print(f'📌 Ca bệnh phức tạp chưa từng gặp:\n"{unseen_query}"\n')

t0 = time.time()
req = urllib.request.Request(
    'https://api.mistral.ai/v1/embeddings',
    data=json.dumps({'model': 'mistral-embed', 'input': [unseen_query]}).encode('utf-8'),
    headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'}
)
with urllib.request.urlopen(req) as resp:
    query_vector = json.loads(resp.read().decode('utf-8'))['data'][0]['embedding']

t_embed = time.time() - t0
print(f'-> AI Mistral phân tích ngữ nghĩa & tạo Vector 1024d trong: {round(t_embed*1000, 1)} ms')

t1 = time.time()
engine = create_engine('postgresql+psycopg://vmec:vmec_dev_password_change_me@127.0.0.1:5432/vmec')

sql = text('''
SELECT 
    kc.normalized_text,
    ke.model_id,
    1 - (ke.embedding <=> CAST(:q_vec AS vector(1024))) AS similarity_score
FROM knowledge_embeddings ke
JOIN knowledge_chunks kc ON ke.chunk_id = kc.id
WHERE ke.model_id = 'mistral-embed-2312'
ORDER BY ke.embedding <=> CAST(:q_vec AS vector(1024))
LIMIT 5;
''')

with engine.connect() as conn:
    results = conn.execute(sql, {'q_vec': str(query_vector)}).fetchall()

t_search = time.time() - t1
print(f'-> HNSW Vector Search trong Postgres (trên kho 842k câu) mất: {round(t_search*1000, 1)} ms\n')

print('=== KẾT QUẢ TRIẾT XUẤT CÂU Y KHOA KHỚP NHẤT TRONG KHO TRI THỨC ===')
for idx, (content, m_id, score) in enumerate(results, 1):
    pct = round(score * 100, 2)
    try:
        data = json.loads(content)
        txt = data.get('normalized_text') or data.get('variant_text_vi') or content
        fn = data.get('origin_file')
        row_id = data.get('global_row_id')
        err = data.get('error_type', 'NORMAL')
        print(f'{idx}. [Độ khớp: {pct}%] (ID: {row_id} | Type: {err} | File: {fn})')
        print(f'   👉 Văn bản y khoa: "{txt}"\n')
    except Exception:
        print(f'{idx}. [Độ khớp: {pct}%] Content: "{content[:150]}"\n')
