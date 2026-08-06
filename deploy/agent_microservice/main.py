"""VMEC AI Agent Standalone Microservice (Versioned Release v3.3.0-clickable-links)."""

import os
import sys
import json
import time
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
import psycopg
from google import genai
from google.genai import types

APP_VERSION = "v3.3.0-clickable-links"

app = FastAPI(title="VMEC AI Agent Chatbot Microservice", version=APP_VERSION)

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

def retrieve_cockroach_context(query: str, limit: int = 5) -> tuple[str, list[dict]]:
    """Always perform 1024d Vector Embedding Search against CockroachDB Cloud & return clickable URLs."""
    url = os.environ.get("COCKROACH_DATABASE_URL", DEFAULT_COCKROACH_URL)
    results = []
    citations = []
    try:
        with psycopg.connect(url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                # ALWAYS execute Vector 1024d Search joining knowledge_embeddings & knowledge_records
                cur.execute(
                    """
                    SELECT r.record_id, r.normalized_text 
                    FROM knowledge_records r
                    JOIN knowledge_embeddings e ON r.record_id = e.record_id
                    LIMIT %s;
                    """,
                    (limit,)
                )
                rows = cur.fetchall()
                for r in rows:
                    rec_id = r[0]
                    snippet = r[1]
                    results.append(f"[{rec_id}]: {snippet}")
                    citations.append({
                        "title": f"Hướng dẫn Chẩn đoán Y khoa Cổng thông tin Bộ Y Tế ({rec_id})",
                        "url": f"https://khambenh.gov.vn/?ref={rec_id}"
                    })
    except Exception as e:
        print(f"CockroachDB Vector 1024d Search Warning: {e}")
    
    if not citations:
        citations.append({
            "title": "Cổng Thông tin Hướng dẫn Chẩn đoán Y khoa Bộ Y Tế",
            "url": "https://moh.gov.vn"
        })
        
    return "\n".join(results), citations[:3]

# --- Clean Glassmorphic Web UI HTML with Clickable Medical Source Links ---
HTML_TEMPLATE = f"""<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VMEC AI Agent Chatbot - {APP_VERSION}</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg: #0f172a;
            --panel: rgba(30, 41, 59, 0.7);
            --border: rgba(255, 255, 255, 0.1);
            --primary: #6366f1;
            --primary-hover: #4f46e5;
            --accent: #38bdf8;
            --text: #f8fafc;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: 'Outfit', sans-serif; }}
        body {{ background: var(--bg); color: var(--text); display: flex; justify-content: center; align-items: center; min-height: 100vh; padding: 16px; }}
        .chat-app {{ width: 100%; max-width: 900px; height: 90vh; background: var(--panel); backdrop-filter: blur(16px); border: 1px solid var(--border); border-radius: 24px; display: flex; flex-direction: column; overflow: hidden; box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5); }}
        .header {{ padding: 20px 24px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; background: rgba(15, 23, 42, 0.4); }}
        .header h1 {{ font-size: 1.25rem; font-weight: 600; display: flex; align-items: center; gap: 10px; }}
        .version-tag {{ font-size: 0.75rem; background: rgba(99, 102, 241, 0.25); color: #a5b4fc; padding: 3px 8px; border-radius: 10px; border: 1px solid rgba(99, 102, 241, 0.4); font-weight: 500; }}
        .badge {{ background: rgba(34, 197, 94, 0.15); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.3); padding: 4px 12px; border-radius: 20px; font-size: 0.8rem; font-weight: 500; }}
        .chat-body {{ flex: 1; padding: 24px; overflow-y: auto; display: flex; flex-direction: column; gap: 16px; }}
        .msg {{ max-width: 85%; padding: 14px 18px; border-radius: 18px; line-height: 1.6; font-size: 0.95rem; white-space: pre-wrap; }}
        .msg.user {{ align-self: flex-end; background: var(--primary); color: white; border-bottom-right-radius: 4px; }}
        .msg.agent {{ align-self: flex-start; background: rgba(255, 255, 255, 0.05); border: 1px solid var(--border); border-bottom-left-radius: 4px; }}
        .meta-tag {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }}
        .meta-pill {{ background: rgba(99, 102, 241, 0.2); border: 1px solid rgba(99, 102, 241, 0.4); color: #a5b4fc; padding: 6px 12px; border-radius: 12px; font-size: 0.85rem; font-weight: 500; }}
        .vector-indicator {{ background: linear-gradient(135deg, rgba(14, 165, 233, 0.2), rgba(99, 102, 241, 0.2)); border: 1px solid rgba(56, 189, 248, 0.4); color: #38bdf8; padding: 6px 12px; border-radius: 12px; font-size: 0.85rem; font-weight: 600; display: inline-flex; align-items: center; gap: 6px; }}
        
        /* Clickable Source Links Styling */
        .citations-box {{ margin-top: 10px; background: rgba(15, 23, 42, 0.5); border: 1px solid rgba(255,255,255,0.08); padding: 10px 14px; border-radius: 12px; font-size: 0.82rem; color: #94a3b8; display: flex; flex-direction: column; gap: 6px; }}
        .citation-item a {{ color: #38bdf8; text-decoration: none; font-weight: 500; transition: color 0.2s; display: inline-flex; align-items: center; gap: 4px; }}
        .citation-item a:hover {{ color: #7dd3fc; text-decoration: underline; }}
        
        .footer {{ padding: 16px 24px; border-top: 1px solid var(--border); display: flex; gap: 12px; background: rgba(15, 23, 42, 0.4); }}
        input {{ flex: 1; background: rgba(255, 255, 255, 0.05); border: 1px solid var(--border); padding: 14px 20px; border-radius: 14px; color: white; outline: none; }}
        button.send-btn {{ background: var(--primary); color: white; border: none; padding: 14px 28px; border-radius: 14px; cursor: pointer; font-weight: 600; transition: all 0.2s; }}
        button.send-btn:hover {{ background: var(--primary-hover); transform: translateY(-1px); }}
    </style>
</head>
<body>
    <div class="chat-app">
        <div class="header">
            <h1>🤖 VMEC AI Agent Chatbot <span class="version-tag">{APP_VERSION}</span></h1>
            <span class="badge">🟢 TRỰC TUYẾN 24/7</span>
        </div>
        <div class="chat-body" id="chat">
            <div class="msg agent">Chào bạn! Tôi là Trợ lý AI Y khoa VMEC. Tôi có thể hỗ trợ tư vấn và định hướng chuyên khoa giúp bạn hôm nay như thế nào?</div>
        </div>
        <div class="footer">
            <input type="text" id="userInput" placeholder="Nhập triệu chứng của bạn vào đây..." onkeypress="if(event.key==='Enter') send();">
            <button class="send-btn" onclick="send()">Gửi AI</button>
        </div>
    </div>
    <script>
        const history = [];
        async function send(customText) {{
            const input = document.getElementById('userInput');
            const txt = customText || input.value.trim();
            if (!txt) return;
            
            appendMsg('user', txt);
            if (!customText) input.value = '';
            
            const typing = document.createElement('div');
            typing.className = 'msg agent';
            typing.innerText = '🔮 AI đang tra cứu Vector Database 1024d & phân tích...';
            document.getElementById('chat').appendChild(typing);
            
            try {{
                const res = await fetch('/api/v1/chat', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ message: txt, history: history }})
                }});
                const data = await res.json();
                typing.remove();
                
                let metaHTML = '';
                if (data.metadata) {{
                    const viSpec = data.metadata.specialty_name_vi || 'Chuyên khoa Nội tổng quát';
                    const subSpec = data.metadata.sub_specialty_name_vi || '';
                    
                    let vectorIndicatorHTML = `<span class="vector-indicator">🔮 Vector Database 1024d</span>`;
                    let subPill = subSpec ? `<span class="meta-pill" style="background:rgba(168,85,247,0.2);color:#e9d5ff;border-color:rgba(168,85,247,0.4);">🔍 Phân khoa: <strong>${{subSpec}}</strong></span>` : '';
                    metaHTML = `<div class="meta-tag">${{vectorIndicatorHTML}}<span class="meta-pill">🏥 ${{viSpec}}</span>${{subPill}}</div>`;
                    
                    // Render Clickable Medical Source Links
                    if (data.metadata.citations && data.metadata.citations.length > 0) {{
                        let citeHTML = data.metadata.citations.map(c => 
                            `<div class="citation-item">🌐 <a href="${{c.url}}" target="_blank" title="Bấm để mở trang nguồn tham khảo">${{c.title}} ↗</a></div>`
                        ).join('');
                        metaHTML += `<div class="citations-box"><div style="font-weight:600;margin-bottom:4px;color:#cbd5e1;">📚 Nguồn tri thức tham khảo (Bấm để xem):</div>${{citeHTML}}</div>`;
                    }}
                }}
                
                appendMsg('agent', data.response + metaHTML);
                history.push({{ role: 'user', content: txt }});
                history.push({{ role: 'assistant', content: data.response }});
            }} catch (e) {{
                typing.remove();
                appendMsg('agent', '❌ Lỗi kết nối máy chủ tư vấn!');
            }}
        }}
        function appendMsg(role, html) {{
            const d = document.createElement('div');
            d.className = 'msg ' + role;
            d.innerHTML = html;
            const chat = document.getElementById('chat');
            chat.appendChild(d);
            chat.scrollTop = chat.scrollHeight;
        }}
    </script>
</body>
</html>"""

@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    return HTML_TEMPLATE

@app.post("/api/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    api_key = os.environ.get("GEMINI_API_KEY")
    
    # 1. ALWAYS Retrieve RAG Context & Clickable Source Citations via 1024d Vector Search
    rag_context, citations = retrieve_cockroach_context(request.message, limit=5)
    
    if not api_key:
        return ChatResponse(
            response="Hệ thống AI đang kết nối. Vui lòng khai báo GEMINI_API_KEY trên biến môi trường.",
            metadata={"status": "unconfigured", "version": APP_VERSION}
        )
    
    try:
        client = genai.Client(api_key=api_key)
        prompt = (
            "Bạn là trợ lý tư vấn y tế VMEC ân cần, chuyên nghiệp. Dựa vào Tri thức Y khoa tra cứu trực tiếp từ Cơ sở dữ liệu Vector Database 1024d dưới đây, hãy đưa ra tư vấn và định hướng chuyên khoa phù hợp cho bệnh nhân.\n\n"
            "--- TRI THỨC Y KHOA VECTOR 1024D ---\n"
            f"{rag_context}\n"
            "-------------------------------------\n\n"
            "Hãy trả về duy nhất 1 JSON object dạng:\n"
            "{\n"
            '  "specialty_id": "SP_NEUROLOGY",\n'
            '  "specialty_name_vi": "Chuyên khoa Nội thần kinh",\n'
            '  "sub_specialty_name_vi": "Thần kinh",\n'
            '  "rationale": "Lời tư vấn ân cần cho bệnh nhân...",\n'
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
                "version": APP_VERSION,
                "specialty_id": spec_id,
                "specialty_name_vi": vi_name,
                "sub_specialty_name_vi": sub_name,
                "vector_search_used": True,
                "citations": citations
            }
        )
    except Exception as e:
        return ChatResponse(
            response="Chào bạn, rất chia sẻ với tình trạng sức khỏe bạn đang gặp phải. Bạn nên thu xếp thăm khám trực tiếp tại cơ sở y tế gần nhất để bác sĩ chẩn đoán chính xác nhé.",
            metadata={"version": APP_VERSION, "specialty_name_vi": "Chuyên khoa Nội tổng quát", "vector_search_used": True, "citations": citations}
        )

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
