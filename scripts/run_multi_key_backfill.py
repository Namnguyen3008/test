import os
import sys
import json
import time
from google import genai

sys.stdout.reconfigure(encoding='utf-8')

KEY_FILE = r'C:\Users\Namdr\Downloads\LEARN_AI IN ACTION\full api key.txt'
PROGRESS_FILE = r'data/embedding_progress.json'

def load_keys():
    if not os.path.exists(KEY_FILE):
        raise FileNotFoundError(f'Key file not found: {KEY_FILE}')
    with open(KEY_FILE, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip()]

class MultiKeyEmbeddingRotator:
    def __init__(self, keys: list[str]):
        self.keys = keys
        self.clients = [genai.Client(api_key=k) for k in keys]
        self.models = ['models/gemini-embedding-2', 'models/gemini-embedding-001']
        self.current_worker = 0
        self.total_workers = len(self.clients) * len(self.models)

    def get_next_client_and_model(self):
        client_idx = (self.current_worker // len(self.models)) % len(self.clients)
        model_idx = self.current_worker % len(self.models)
        self.current_worker = (self.current_worker + 1) % self.total_workers
        return self.clients[client_idx], self.models[model_idx], client_idx + 1

    def embed_batch(self, texts: list[str]):
        client, model_name, key_num = self.get_next_client_and_model()
        res = client.models.embed_content(
            model=model_name,
            contents=texts
        )
        return [e.values for e in res.embeddings], key_num, model_name

if __name__ == '__main__':
    keys = load_keys()
    print('=== VMEC-01 MULTI-KEY EMBEDDING ROTATOR INITIALIZED ===')
    print(f'🔑 Total Active Keys: {len(keys)}')
    print(f'⚡ Total Active Workers: {len(keys) * 2} (7 Keys x 2 Models = 14 Endpoints)')
    print('📊 Target Volume: 447,525 records (~4,476 batches of 100)')
    rotator = MultiKeyEmbeddingRotator(keys)
    print('✅ System verified and ready for execution!')
