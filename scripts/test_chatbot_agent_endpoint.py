import urllib.request, json, time, sys
sys.stdout.reconfigure(encoding='utf-8')

url = 'http://127.0.0.1:8000/api/v1/chat'
payload = {
    "message": "Tôi bị đau đầu dữ dội từ sáng kèm buồn nôn, cần khám chuyên khoa nào?",
    "history": []
}

print('=== KIỂM TRA LUỒNG CHÁT BOT AGENT DUY NHẤT (/api/v1/chat) ===')
print('Payload gửi đến Agent:\n', json.dumps(payload, ensure_ascii=False, indent=2))

t0 = time.time()
req = urllib.request.Request(
    url,
    data=json.dumps(payload).encode('utf-8'),
    headers={'Content-Type': 'application/json', 'User-Agent': 'Python/3.11'}
)

try:
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        t_elapsed = round((time.time() - t0) * 1000, 1)
        print(f'\n🟢 [PHẢN HỒI THÀNH CÔNG] HTTP {resp.status} (Thời gian phản hồi: {t_elapsed} ms)')
        print('=== KẾT QUẢ TRẢ VỀ TỪ CHATBOT AGENT ===')
        print(json.dumps(data, ensure_ascii=False, indent=2))
except Exception as e:
    print(f'\n🔴 [LỖI KẾT NỐI API]: {str(e)}')
