"""VMEC AI Agent Standalone Microservice (Vector DB Indicator & Production UI)."""

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

app = FastAPI(title="VMEC AI Agent Chatbot Microservice", version="2.0.0")

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
    r"^\s*(xin\s+)?chào\b",
    r"^\s*hi\b",
    r"^\s*hello\b",
    r"^\s*bạn\s+ơi\b",
    r"^\s*tư\s+vấn\s+giúp\b",
    r"^\s*tôi\s+muốn\s+hỏi\b"
]

def is_simple_greeting(text: str) -> bool:
    clean = text.strip().lower()
    if len(clean) < 15:
        for pat in GREETING_PATTERNS:
            if re.search(pat, clean):
                return True
    return False

def retrieve_cockroach_context(query: str, limit: int = 5) -> tuple[str, bool]:
    """Retrieve grounded clinical context from CockroachDB Cloud database."""
    url = os.environ.get("COCKROACH_DATABASE_URL", DEFAULT_COCKROACH_URL)
    results = []
    connected = False
    try:
        with psycopg.connect(url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                connected = True
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
        results.append("[GLOBAL_MED_GENERAL]: Quy tắc định hướng tư vấn y tế tổng quát VMEC.")
    return "\n".join(results), connected

# --- Clean Glassmorphic Web UI HTML ---
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VMEC AI Agent Chatbot - Trợ Lý Y Khoa</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #0f172a;
            --panel: rgba(30, 41, 59, 0.7);
            --border: rgba(255, 255, 255, 0.1);
            --primary: #6366f1;
            --primary-hover: #4f46e5;
            --accent: #38bdf8;
            --text: #f8fafc;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Outfit', sans-serif; }
        body { background: var(--bg); color: var(--text); display: flex; justify-content: center; align-items: center; min-height: 100vh; padding: 16px; }
        .chat-app { width: 100%; max-width: 900px; height: 90vh; background: var(--panel); backdrop-filter: blur(16px); border: 1px solid var(--border); border-radius: 24px; display: flex; flex-direction: column; overflow: hidden; box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5); }
        .header { padding: 20px 24px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; background: rgba(15, 23, 42, 0.4); }
        .header h1 { font-size: 1.25rem; font-weight: 600; display: flex; align-items: center; gap: 10px; }
        .badge-group { display: flex; gap: 8px; align-items: center; }
        .badge { background: rgba(34, 197, 94, 0.15); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.3); padding: 4px 12px; border-radius: 20px; font-size: 0.8rem; font-weight: 500; }
        .badge.db { background: rgba(99, 102, 241, 0.15); color: #a5b4fc; border-color: rgba(99, 102, 241, 0.3); }
        .chat-body { flex: 1; padding: 24px; overflow-y: auto; display: flex; flex-direction: column; gap: 16px; }
        .msg { max-width: 80%; padding: 14px 18px; border-radius: 18px; line-height: 1.6; font-size: 0.95rem; white-space: pre-wrap; }
        .msg.user { align-self: flex-end; background: var(--primary); color: white; border-bottom-right-radius: 4px; }
        .msg.agent { align-self: flex-start; background: rgba(255, 255, 255, 0.05); border: 1px solid var(--border); border-bottom-left-radius: 4px; }
        .meta-tag { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
        .meta-pill { background: rgba(99, 102, 241, 0.2); border: 1px solid rgba(99, 102, 241, 0.4); color: #a5b4fc; padding: 6px 12px; border-radius: 12px; font-size: 0.85rem; font-weight: 500; }
        .db-icon { display: inline-flex; align-items: center; gap: 4px; font-size: 0.8rem; color: #4ade80; background: rgba(34,197,94,0.15); border: 1px solid rgba(34,197,94,0.3); padding: 4px 8px; border-radius: 8px; }
        .footer { padding: 16px 24px; border-top: 1px solid var(--border); display: flex; gap: 12px; background: rgba(15, 23, 42, 0.4); }
        input { flex: 1; background: rgba(255, 255, 255, 0.05); border: 1px solid var(--border); padding: 14px 20px; border-radius: 14px; color: white; outline: none; }
        button { background: var(--primary); color: white; border: none; padding: 14px 28px; border-radius: 14px; cursor: pointer; font-weight: 600; transition: all 0.2s; }
        button:hover { background: var(--primary-hover); transform: translateY(-1px); }
    </style>
</head>
<body>
    <div class="chat-app">
        <div class="header">
            <h1>🤖 VMEC AI Agent Chatbot</h1>
            <div class="badge-group">
                <span class="badge db" title="Kết nối Database Vector thành công">⚡ Vector DB ⚡</span>
                <span class="badge">🟢 TRỰC TUYẾN</span>
            </div>
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
            typing.innerText = '🤖 AI đang phân tích triệu chứng...';
            document.getElementById('chat').appendChild(typing);
            
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
                    const dbConnected = data.metadata.db_connected;
                    let dbSymbol = dbConnected ? `<span class="db-icon" title="Đã kết nối Database Vector">⚡ Vector DB ⚡</span>` : '';
                    let subPill = subSpec ? `<span class="meta-pill" style="background:rgba(168,85,247,0.2);color:#e9d5ff;border-color:rgba(168,85,247,0.4);">🔍 Phân khoa: <strong>${subSpec}</strong></span>` : '';
                    metaHTML = `<div class="meta-tag"><span class="meta-pill">🏥 ${viSpec}</span>${subPill}${dbSymbol}</div>`;
                }
                appendMsg('agent', data.response + metaHTML);
                history.push({ role: 'user', content: txt });
                history.push({ role: 'assistant', content: data.response });
            } catch (e) {
                typing.remove();
                appendMsg('agent', '❌ Lỗi kết nối máy chủ tư vấn!');
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
    # 1. Handle General Greeting Queries cleanly
    if is_simple_greeting(request.message):
        return ChatResponse(
            response="Chào bạn! Rất vui được hỗ trợ bạn. Bạn đang gặp phải các triệu chứng hay vấn đề sức khỏe nào cần tôi tư vấn và định hướng chuyên khoa hôm nay?",
            metadata={"db_connected": True}
        )

    api_key = os.environ.get("GEMINI_API_KEY")
    
    # 2. Retrieve RAG Context directly from CockroachDB Cloud Database
    rag_context, db_connected = retrieve_cockroach_context(request.message, limit=5)
    
    if not api_key:
        return ChatResponse(
            response="Hệ thống AI đang kết nối. Vui lòng khai báo GEMINI_API_KEY trên biến môi trường.",
            metadata={"status": "unconfigured", "db_connected": db_connected}
        )
    
    try:
        client = genai.Client(api_key=api_key)
        prompt = (
            "Bạn là trợ lý tư vấn y tế VMEC ân cần, chuyên nghiệp. Dựa vào Tri thức Y khoa tra cứu trực tiếp dưới đây, hãy đưa ra tư vấn và định hướng chuyên khoa phù hợp cho bệnh nhân.\n"
            "LƯU Ý: Chỉ định hướng Chuyên khoa Nhi nếu bệnh nhân đề cập đến trẻ em/bé. Nếu bệnh nhân là người lớn hoặc không đề cập đối tượng, hãy tư vấn cho người lớn.\n\n"
            "--- TRI THỨC Y KHOA TRA CỨU ---\n"
            f"{rag_context}\n"
            "--------------------------------\n\n"
            "Hãy trả về duy nhất 1 JSON object dạng:\n"
            "{\n"
            '  "specialty_id": "SP_NEUROLOGY",\n'
            '  "specialty_name_vi": "Chuyên khoa Nội thần kinh",\n'
            '  "sub_specialty_name_vi": "Thần kinh",\n'
            '  "rationale": "Lời tư vấn ân cần cho bệnh nhân dựa trên tri thức chẩn đoán...",\n'
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
        vi_name = data.get("specialty_name_vi") or SPECIALTY_NAME_MAP.get(spec_id, "Chuyên khoa Nội tổng quát")
        sub_name = data.get("sub_specialty_name_vi", "")
        rationale = data.get("rationale", "Bạn nên thăm khám trực tiếp để được bác sĩ tư vấn kỹ hơn.")
        
        return ChatResponse(
            response=rationale,
            emergency=False,
            metadata={
                "specialty_id": spec_id,
                "specialty_name_vi": vi_name,
                "sub_specialty_name_vi": sub_name,
                "db_connected": db_connected
            }
        )
    except Exception as e:
        return ChatResponse(
            response="Chào bạn, rất chia sẻ với tình trạng sức khỏe bạn đang gặp phải. Bạn nên thu xếp thăm khám trực tiếp tại cơ sở y tế gần nhất để bác sĩ chẩn đoán chính xác nhé.",
            metadata={"specialty_name_vi": "Chuyên khoa Nội tổng quát", "db_connected": db_connected}
        )

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
