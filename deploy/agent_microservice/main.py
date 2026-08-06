"""VMEC AI Agent Standalone Microservice (Full 8 UX & Clinical Workflow Solutions)."""

import os
import sys
import json
import time
import re
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
import psycopg
from google import genai
from google.genai import types

app = FastAPI(title="VMEC AI Agent Chatbot Microservice", version="2.5.0")

# --- Schemas ---
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    history: list[ChatMessage] = Field(default_factory=list)

class ChatResponse(BaseModel):
    response: str
    emergency: bool = False
    metadata: dict = Field(default_factory=dict)

# --- Specialty Code Map & Translation ---
SPECIALTY_NAME_MAP = {
    "SP_CARDIOLOGY": "Chuyên khoa Tim mạch",
    "SP_DERMATOLOGY": "Chuyên khoa Da liễu",
    "SP_ENT": "Chuyên khoa Tai Mũi Họng",
    "SP_GASTROENTEROLOGY": "Chuyên khoa Tiêu hóa",
    "SP_GASTRO": "Chuyên khoa Tiêu hóa",
    "SP_GENERAL_MEDICINE": "Chuyên khoa Nội tổng quát",
    "SP_INFECTIOUS": "Chuyên khoa Truyền nhiễm",
    "SP_MENTAL_HEALTH": "Chuyên khoa Sức khỏe tâm thần",
    "SP_NEUROLOGY": "Chuyên khoa Nội thần kinh",
    "SP_OBGYN": "Chuyên khoa Sản phụ khoa",
    "SP_OBSTETRICS_GYNECOLOGY": "Chuyên khoa Sản phụ khoa",
    "SP_OPHTHALMOLOGY": "Chuyên khoa Mắt",
    "SP_ORTHOPEDICS": "Chuyên khoa Cơ xương khớp",
    "SP_PEDIATRICS": "Chuyên khoa Nhi",
    "SP_PULMONOLOGY": "Chuyên khoa Hô hấp",
    "SP_RESPIRATORY": "Chuyên khoa Hô hấp",
    "SP_UROLOGY": "Chuyên khoa Nam học - Tiết niệu",
}

DEFAULT_COCKROACH_URL = "postgresql://nguyenvannam:ExCHxZ0m_RkZIGX30zNtyQ@tense-laika-31205.j77.aws-ap-southeast-1.cockroachlabs.cloud:26257/vmec?sslmode=require"

GREETING_PATTERNS = [
    r"^\s*(xin\s+)?chào\b", r"^\s*hi\b", r"^\s*hello\b", r"^\s*bạn\s+ơi\b", r"^\s*cho\s+hỏi\b"
]

AMBIGUOUS_PATTERNS = [
    r"mệt", r"không\s+khỏe", r"khó\s+chịu", r"bị\s+ốm", r"đau\s+người", r"uể\s+uả"
]

SYMPTOM_KEYWORDS = [
    "đau", "sốt", "ho", "ngứa", "nôn", "nước tiểu", "mắt", "da", "bụng", "đầu", "thở", "tê", "chóng mặt", "sụt kg"
]

def classify_intent(text: str) -> str:
    clean = text.strip().lower()
    has_symptom = any(k in clean for k in SYMPTOM_KEYWORDS)
    
    if len(clean) < 15 and not has_symptom:
        for pat in GREETING_PATTERNS:
            if re.search(pat, clean):
                return "GREETING"
    
    if not has_symptom:
        for pat in AMBIGUOUS_PATTERNS:
            if re.search(pat, clean):
                return "AMBIGUOUS"
                
    return "CLINICAL"

def retrieve_cockroach_context(query: str, limit: int = 5) -> str:
    """Retrieve grounded clinical context from CockroachDB Cloud database."""
    url = os.environ.get("COCKROACH_DATABASE_URL", DEFAULT_COCKROACH_URL)
    results = []
    try:
        with psycopg.connect(url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                words = [w for w in query.strip().split() if len(w) > 2][:3]
                if words:
                    like_pattern = f"%{words[0]}%"
                    cur.execute(
                        "SELECT record_id, normalized_text FROM knowledge_records WHERE normalized_text ILIKE %s LIMIT %s;",
                        (like_pattern, limit)
                    )
                    rows = cur.fetchall()
                    for r in rows:
                        results.append(f"[{r[0]}]: {r[1]}")
    except Exception as e:
        print(f"CockroachDB Retrieval Warning: {e}")
    
    if not results:
        results.append("[GLOBAL_MED_GENERAL]: Hướng dẫn phân loại chẩn đoán y khoa tổng quát VMEC.")
    return "\n".join(results)

# --- Clean Glassmorphic Web UI HTML ---
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VMEC AI Agent Chatbot - Trợ Lý Y Khoa Thông Minh</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #0f172a;
            --panel: rgba(30, 41, 59, 0.75);
            --border: rgba(255, 255, 255, 0.12);
            --primary: #6366f1;
            --primary-hover: #4f46e5;
            --accent: #38bdf8;
            --text: #f8fafc;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Outfit', sans-serif; }
        body { background: var(--bg); color: var(--text); display: flex; justify-content: center; align-items: center; min-height: 100vh; padding: 16px; }
        .chat-app { width: 100%; max-width: 920px; height: 90vh; background: var(--panel); backdrop-filter: blur(16px); border: 1px solid var(--border); border-radius: 24px; display: flex; flex-direction: column; overflow: hidden; box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5); }
        .header { padding: 20px 24px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; background: rgba(15, 23, 42, 0.5); }
        .header h1 { font-size: 1.25rem; font-weight: 600; display: flex; align-items: center; gap: 10px; }
        .badge { background: rgba(34, 197, 94, 0.15); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.3); padding: 4px 12px; border-radius: 20px; font-size: 0.8rem; font-weight: 500; }
        .chat-body { flex: 1; padding: 24px; overflow-y: auto; display: flex; flex-direction: column; gap: 16px; }
        .msg { max-width: 82%; padding: 16px 20px; border-radius: 18px; line-height: 1.65; font-size: 0.95rem; white-space: pre-wrap; }
        .msg.user { align-self: flex-end; background: var(--primary); color: white; border-bottom-right-radius: 4px; }
        .msg.agent { align-self: flex-start; background: rgba(255, 255, 255, 0.05); border: 1px solid var(--border); border-bottom-left-radius: 4px; }
        .meta-tag { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 14px; padding-top: 10px; border-top: 1px solid rgba(255,255,255,0.08); }
        .meta-pill { background: rgba(99, 102, 241, 0.2); border: 1px solid rgba(99, 102, 241, 0.4); color: #a5b4fc; padding: 6px 14px; border-radius: 12px; font-size: 0.85rem; font-weight: 500; }
        .disclaimer { margin-top: 12px; font-size: 0.78rem; color: #94a3b8; font-style: italic; border-top: 1px dashed rgba(255,255,255,0.1); padding-top: 8px; }
        .typing-dots { display: inline-flex; gap: 4px; align-items: center; }
        .dot { width: 6px; height: 6px; background: #38bdf8; border-radius: 50%; animation: bounce 1.4s infinite ease-in-out both; }
        .dot:nth-child(1) { animation-delay: -0.32s; }
        .dot:nth-child(2) { animation-delay: -0.16s; }
        @keyframes bounce { 0%, 80%, 100% { transform: scale(0); } 40% { transform: scale(1); } }
        .footer { padding: 16px 24px; border-top: 1px solid var(--border); display: flex; gap: 12px; background: rgba(15, 23, 42, 0.5); }
        input { flex: 1; background: rgba(255, 255, 255, 0.05); border: 1px solid var(--border); padding: 14px 20px; border-radius: 14px; color: white; outline: none; font-size: 0.95rem; }
        button { background: var(--primary); color: white; border: none; padding: 14px 28px; border-radius: 14px; cursor: pointer; font-weight: 600; transition: all 0.2s; }
        button:hover { background: var(--primary-hover); transform: translateY(-1px); }
    </style>
</head>
<body>
    <div class="chat-app">
        <div class="header">
            <h1>🤖 VMEC AI Agent Chatbot</h1>
            <span class="badge">🟢 TRỰC TUYẾN 24/7</span>
        </div>
        <div class="chat-body" id="chat">
            <div class="msg agent">Chào bạn! Tôi là Trợ lý AI Y khoa VMEC. Tôi có thể hỗ trợ tư vấn và định hướng chuyên khoa giúp bạn hôm nay như thế nào?</div>
        </div>
        <div class="footer">
            <input type="text" id="userInput" placeholder="Nhập triệu chứng của bạn vào đây..." onkeypress="if(event.key==='Enter') send();">
            <button onclick="send()">Gửi AI</button>
        </div>
    </div>
    <script>
        const history = [];
        async function send() {
            const input = document.getElementById('userInput');
            const txt = input.value.trim();
            if (!txt) return;
            
            appendMsg('user', txt);
            input.value = '';
            
            const typing = document.createElement('div');
            typing.className = 'msg agent';
            typing.id = 'typingIndicator';
            typing.innerHTML = '🤖 AI đang tra cứu tri thức y khoa & phân tích triệu chứng <span class="typing-dots"><span class="dot"></span><span class="dot"></span><span class="dot"></span></span>';
            document.getElementById('chat').appendChild(typing);
            document.getElementById('chat').scrollTop = document.getElementById('chat').scrollHeight;
            
            try {
                const res = await fetch('/api/v1/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: txt, history: history })
                });
                const data = await res.json();
                typing.remove();
                
                let metaHTML = '';
                if (data.metadata && data.metadata.specialty_name_vi) {
                    const viSpec = data.metadata.specialty_name_vi;
                    const subSpec = data.metadata.sub_specialty_name_vi || '';
                    let subPill = subSpec ? `<span class="meta-pill" style="background:rgba(168,85,247,0.2);color:#e9d5ff;border-color:rgba(168,85,247,0.4);">🎯 Nhóm bệnh: <strong>${subSpec}</strong></span>` : '';
                    metaHTML = `<div class="meta-tag"><span class="meta-pill">🏥 Chuyên khoa nên khám: <strong>${viSpec}</strong></span>${subPill}</div>`;
                }
                const disclaimerHTML = `<div class="disclaimer">⚠️ <strong>Lưu ý quan trọng:</strong> Nội dung tư vấn của AI chỉ mang tính chất tham khảo định hướng chuyên khoa, không thay thế chẩn đoán trực tiếp từ Bác sĩ chuyên khoa.</div>`;
                
                appendMsg('agent', data.response + metaHTML + disclaimerHTML);
                history.push({ role: 'user', content: txt });
                history.push({ role: 'assistant', content: data.response });
            } catch (e) {
                typing.remove();
                appendMsg('agent', '❌ Lỗi kết nối máy chủ tư vấn! Vui lòng thử lại.');
            }
        }
        function appendMsg(role, html) {
            const d = document.createElement('div');
            d.className = 'msg ' + role;
            d.innerHTML = html;
            const chat = document.getElementById('chat');
            chat.appendChild(d);
            chat.scrollTop = chat.scrollHeight;
        }
    </script>
</body>
</html>"""

@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    return HTML_TEMPLATE

@app.post("/api/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    intent = classify_intent(request.message)
    
    # 1. Handle Pure Greeting Intent
    if intent == "GREETING":
        return ChatResponse(
            response="Chào bạn! Rất vui được hỗ trợ bạn. Bạn đang gặp phải các triệu chứng hay vấn đề sức khỏe nào cần tôi tư vấn và định hướng chuyên khoa hôm nay?",
            metadata={}
        )

    # 2. Handle Ambiguous Symptom Intent (e.g. "tôi thấy không khỏe", "dạo này mệt quá")
    if intent == "AMBIGUOUS":
        return ChatResponse(
            response="Chào bạn, tôi rất chia sẻ với cảm giác mệt mỏi hoặc không khỏe của bạn gần đây. "
                     "Để tôi có thể tư vấn chính xác chuyên khoa phù hợp nhất, xin bạn vui lòng chia sẻ thêm:\n"
                     "• Tình trạng này kéo dài bao lâu rồi?\n"
                     "• Bạn có kèm theo triệu chứng nào khác như sốt, ho, chán ăn, đau ở đâu hoặc ngủ không ngon không?",
            metadata={}
        )

    api_key = os.environ.get("GEMINI_API_KEY")
    
    # 3. Retrieve RAG Context directly from CockroachDB Cloud Database
    rag_context = retrieve_cockroach_context(request.message, limit=5)
    
    if not api_key:
        return ChatResponse(
            response="Hệ thống AI đang kết nối. Vui lòng khai báo GEMINI_API_KEY trên biến môi trường.",
            metadata={"status": "unconfigured"}
        )
    
    try:
        client = genai.Client(api_key=api_key)
        
        # Build multi-turn conversation context
        history_str = ""
        if request.history:
            history_str = "--- LỊCH SỬ TRÒ CHUYỆN TRƯỚC ĐÓ ---\n"
            for h in request.history[-4:]:
                history_str += f"{h.role.upper()}: {h.content}\n"
            history_str += "-------------------------------------\n\n"

        prompt = (
            "Bạn là Trợ lý AI Y tế VMEC ân cần, chuyên nghiệp và thấu hiểu.\n"
            "Nhiệm vụ: Dựa vào Tri thức Y khoa tra cứu và Lịch sử trò chuyện, hãy đưa ra tư vấn theo cấu trúc 3 phần:\n"
            "1. **Tư vấn & Lý giải chi tiết**: Thể hiện sự thấu hiểu, giải thích rõ ràng TẠI SAO triệu chứng của bệnh nhân lại liên quan đến Chuyên khoa được gợi ý.\n"
            "2. **Xác nhận an toàn**: Nếu có các triệu chứng như đau đầu dữ dội hay đau ngực, đưa ra lời khuyên xác nhận mềm ('Nếu bạn có thêm các dấu hiệu như yếu nửa người, méo miệng hay khó thở nặng, hãy liên hệ ngay số Cấp cứu 115').\n"
            "3. **Hỏi gợi mở thêm**: Đặt 1 câu hỏi gợi mở nhẹ nhàng để giúp bệnh nhân mô tả rõ hơn trước khi đi khám.\n\n"
            f"{history_str}"
            "--- TRI THỨC Y KHOA TRA CỨU COCKROACHDB ---\n"
            f"{rag_context}\n"
            "-------------------------------------------\n\n"
            "Hãy trả về duy nhất 1 JSON object dạng:\n"
            "{\n"
            '  "specialty_id": "SP_NEUROLOGY",\n'
            '  "specialty_name_vi": "Nội thần kinh",\n'
            '  "sub_specialty_name_vi": "Thần kinh & Mạch máu não",\n'
            '  "rationale": "Nội dung lời tư vấn 3 phần ân cần, chi tiết cho bệnh nhân...",\n'
            '  "action": "suggest_specialty"\n'
            "}\n\n"
            f"Bệnh nhân hỏi: {request.message}"
        )
        
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(max_output_tokens=1024)
        )
        
        raw_text = response.text or "{}"
        clean_json = raw_text.strip().removeprefix("```json").removesuffix("```").strip()
        data = json.loads(clean_json)
        
        spec_id = data.get("specialty_id", "SP_GENERAL_MEDICINE")
        vi_name = data.get("specialty_name_vi") or SPECIALTY_NAME_MAP.get(spec_id, "Nội tổng quát")
        sub_name = data.get("sub_specialty_name_vi", "")
        rationale = data.get("rationale", "Bạn nên thăm khám trực tiếp để được bác sĩ tư vấn kỹ hơn.")
        
        return ChatResponse(
            response=rationale,
            emergency=False,
            metadata={
                "specialty_id": spec_id,
                "specialty_name_vi": vi_name,
                "sub_specialty_name_vi": sub_name
            }
        )
    except Exception as e:
        return ChatResponse(
            response="Chào bạn, rất chia sẻ với tình trạng sức khỏe bạn đang gặp phải. Bạn nên thu xếp thăm khám trực tiếp tại cơ sở y tế gần nhất để bác sĩ chẩn đoán chính xác nhé.",
            metadata={"specialty_name_vi": "Nội tổng quát"}
        )

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
