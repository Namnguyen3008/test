"""VMEC AI Agent – Hội Thoại Đa Lượt Thông Minh (Multi-Turn Conversational Flow).

Architecture:
    Stage Machine: IDLE → GATHERING (loop) → CONFIRMING → DONE
    7 LLM Roles : classify_intent, quick_emergency, assess_sufficiency,
                   generate_follow_up, summarize_symptoms, deep_red_flag, route_specialty
"""

import os
import json
import time
import uuid
import logging
from enum import Enum
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
import psycopg
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("vmec.agent")

# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------
app = FastAPI(title="VMEC AI Agent Chatbot – Multi-Turn", version="3.0.0")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MAX_FOLLOW_UP_ROUNDS = 3
SESSION_TTL_SECONDS = 1800  # 30 phút

DEFAULT_COCKROACH_URL = (
    "postgresql://nguyenvannam:ExCHxZ0m_RkZIGX30zNtyQ"
    "@tense-laika-31205.j77.aws-ap-southeast-1.cockroachlabs.cloud:26257"
    "/vmec?sslmode=require"
)

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

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class Stage(str, Enum):
    IDLE = "idle"
    GATHERING = "gathering"
    CONFIRMING = "confirming"
    DONE = "done"


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: str = Field(default="")
    history: list[ChatMessage] = Field(default_factory=list)


class ChatResponse(BaseModel):
    response: str
    session_id: str = ""
    stage: str = "idle"
    emergency: bool = False
    metadata: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Session Store (In-Memory – MVP)
# ---------------------------------------------------------------------------

class Session:
    __slots__ = ("session_id", "stage", "history", "follow_up_count",
                 "symptom_summary", "created_at", "updated_at")

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.stage = Stage.IDLE
        self.history: list[dict[str, str]] = []
        self.follow_up_count: int = 0
        self.symptom_summary: str = ""
        self.created_at: float = time.time()
        self.updated_at: float = time.time()

    def touch(self) -> None:
        self.updated_at = time.time()

    def add_message(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})
        self.touch()

    def history_text(self) -> str:
        """Render history thành chuỗi cho LLM prompt."""
        parts = []
        for msg in self.history:
            label = "Bệnh nhân" if msg["role"] == "user" else "Trợ lý"
            parts.append(f"{label}: {msg['content']}")
        return "\n".join(parts)


_sessions: dict[str, Session] = {}


def _gc_sessions() -> None:
    """Dọn dẹp session hết hạn."""
    now = time.time()
    expired = [k for k, v in _sessions.items() if now - v.updated_at > SESSION_TTL_SECONDS]
    for k in expired:
        del _sessions[k]


def get_or_create_session(session_id: str) -> Session:
    _gc_sessions()
    if not session_id or session_id not in _sessions:
        sid = session_id or uuid.uuid4().hex[:16]
        _sessions[sid] = Session(sid)
        return _sessions[sid]
    sess = _sessions[session_id]
    sess.touch()
    return sess


# ---------------------------------------------------------------------------
# RAG Retrieval (CockroachDB Cloud)
# ---------------------------------------------------------------------------

def retrieve_cockroach_context(query: str, limit: int = 5) -> str:
    """Retrieve grounded clinical context from CockroachDB Cloud."""
    url = os.environ.get("COCKROACH_DATABASE_URL", DEFAULT_COCKROACH_URL)
    results = []
    try:
        with psycopg.connect(url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                words = [w for w in query.strip().split() if len(w) > 2][:3]
                if words:
                    like_pattern = f"%{words[0]}%"
                    cur.execute(
                        "SELECT record_id, normalized_text FROM knowledge_records "
                        "WHERE normalized_text ILIKE %s LIMIT %s;",
                        (like_pattern, limit),
                    )
                    for r in cur.fetchall():
                        results.append(f"[{r[0]}]: {r[1]}")
    except Exception as e:
        log.warning("CockroachDB retrieval error: %s", e)

    if not results:
        results.append("[GLOBAL_MED_GENERAL]: Quy tắc định hướng tư vấn y tế tổng quát VMEC.")
    return "\n".join(results)


# ---------------------------------------------------------------------------
# LLM Helper
# ---------------------------------------------------------------------------

def _llm_call(prompt: str, max_tokens: int = 512) -> str:
    """Single LLM call wrapper."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not configured")
    client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model="gemini-2.0-flash-lite",
        contents=prompt,
        config=types.GenerateContentConfig(max_output_tokens=max_tokens),
    )
    return (resp.text or "").strip()


def _llm_json(prompt: str, max_tokens: int = 512) -> dict:
    """LLM call that parses JSON output."""
    raw = _llm_call(prompt, max_tokens)
    clean = raw.removeprefix("```json").removesuffix("```").strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        log.warning("LLM JSON parse failed, raw=%s", raw[:200])
        return {}


# ---------------------------------------------------------------------------
# 🧠 7 LLM PROMPT ROLES
# ---------------------------------------------------------------------------

# 1️⃣ CLASSIFY INTENT
def classify_intent(message: str) -> str:
    """Phân loại mềm ý định: greeting | symptom_related | confirmation_yes | confirmation_no_correction | other."""
    prompt = (
        "Bạn là module phân loại ý định cho chatbot y tế Việt Nam.\n"
        "Phân loại tin nhắn sau vào ĐÚNG 1 nhãn:\n"
        "- greeting: Chào hỏi thuần túy, không chứa nội dung sức khỏe\n"
        "- symptom_related: Có đề cập triệu chứng, bệnh, sức khỏe, hoặc mô tả thêm tình trạng\n"
        "- confirmation_yes: Xác nhận đồng ý (ví dụ: đúng rồi, vâng, ok, chính xác)\n"
        "- confirmation_no_correction: Phủ nhận / chỉnh sửa (ví dụ: không, sai, bên trái chứ không phải bên phải)\n"
        "- other: Không thuộc các nhóm trên\n\n"
        f'Tin nhắn: "{message}"\n\n'
        "Trả về DUY NHẤT 1 từ nhãn, không giải thích."
    )
    result = _llm_call(prompt, max_tokens=20).lower().strip().strip('"').strip("'")
    valid = {"greeting", "symptom_related", "confirmation_yes", "confirmation_no_correction", "other"}
    if result not in valid:
        # Fallback: nếu chứa keywords xác nhận
        low = message.lower()
        if any(w in low for w in ["đúng", "vâng", "ok", "chính xác", "đúng rồi", "ừ"]):
            return "confirmation_yes"
        if any(w in low for w in ["không", "sai", "chưa đúng", "nhầm"]):
            return "confirmation_no_correction"
        return "symptom_related"
    return result


# 2️⃣ QUICK EMERGENCY SCREEN
EMERGENCY_KEYWORDS = [
    "đau ngực", "khó thở", "ngất", "co giật", "xuất huyết", "chảy máu nhiều",
    "đột quỵ", "liệt", "bất tỉnh", "hôn mê", "ngộ độc", "tự tử", "muốn chết",
    "tai nạn giao thông", "gãy xương hở", "bỏng nặng", "sốc phản vệ",
    "nuốt dị vật", "sặc", "trẻ sơ sinh ngưng thở", "đau bụng dữ dội kèm sốt cao",
]

def quick_emergency_screen(message: str) -> bool:
    """Tầm soát nhanh dựa trên từ khóa cấp cứu rõ rệt."""
    low = message.lower()
    return any(kw in low for kw in EMERGENCY_KEYWORDS)


# 3️⃣ ASSESS SUFFICIENCY
def assess_sufficiency(history_text: str) -> dict:
    """Đánh giá triệu chứng đã đủ chưa. Trả JSON: {verdict, missing_aspects}."""
    prompt = (
        "Bạn là bác sĩ sàng lọc. Đánh giá cuộc hội thoại dưới đây và xác định triệu chứng bệnh nhân mô tả đã đủ chưa.\n\n"
        "5 khía cạnh cần kiểm tra:\n"
        "1. Vị trí cơ thể (đau/khó chịu ở đâu?)\n"
        "2. Tính chất (đau nhói, âm ỉ, rát, tê...?)\n"
        "3. Thời gian (kéo dài bao lâu? bắt đầu khi nào?)\n"
        "4. Triệu chứng kèm theo (sốt, buồn nôn, mệt mỏi...?)\n"
        "5. Yếu tố nguy cơ (tiền sử bệnh, dị ứng, thuốc đang dùng...?)\n\n"
        "Quy tắc: Nếu bệnh nhân đã cung cấp ≥3/5 khía cạnh → sufficient.\n"
        "Nếu < 3 khía cạnh → need_more.\n\n"
        f"--- LỊCH SỬ HỘI THOẠI ---\n{history_text}\n---\n\n"
        "Trả về JSON: {\"verdict\": \"sufficient\" hoặc \"need_more\", \"missing_aspects\": [\"danh sách khía cạnh thiếu\"]}"
    )
    result = _llm_json(prompt, max_tokens=256)
    if not result or "verdict" not in result:
        return {"verdict": "sufficient", "missing_aspects": []}
    return result


# 4️⃣ GENERATE FOLLOW-UP QUESTIONS
def generate_follow_up(history_text: str, missing_aspects: list[str]) -> str:
    """Sinh 1-2 câu hỏi gợi mở thân thiện."""
    missing_hint = ", ".join(missing_aspects) if missing_aspects else "chưa rõ"
    prompt = (
        "Bạn là trợ lý y tế VMEC thân thiện, ân cần. Dựa trên cuộc hội thoại dưới đây, "
        "hãy hỏi bệnh nhân 1-2 câu hỏi ngắn gọn, ấm áp để làm rõ triệu chứng.\n\n"
        f"Khía cạnh còn thiếu: {missing_hint}\n\n"
        f"--- LỊCH SỬ HỘI THOẠI ---\n{history_text}\n---\n\n"
        "Quy tắc:\n"
        "- Tối đa 2 câu hỏi, mỗi câu ngắn gọn\n"
        "- Giọng ân cần, dùng 'bạn' hoặc 'mình'\n"
        "- KHÔNG chẩn đoán, KHÔNG đưa tên bệnh\n"
        "- KHÔNG gợi ý chuyên khoa\n"
        "- Trả về DUY NHẤT câu hỏi, không cần tiêu đề hay format đặc biệt"
    )
    return _llm_call(prompt, max_tokens=256)


# 5️⃣ SUMMARIZE SYMPTOMS
def summarize_symptoms(history_text: str) -> str:
    """Tổng hợp triệu chứng mạch lạc từ toàn bộ hội thoại."""
    prompt = (
        "Bạn là bác sĩ tổng hợp bệnh sử. Từ cuộc hội thoại dưới đây, tóm tắt triệu chứng "
        "bệnh nhân thành 1 đoạn văn ngắn gọn, rõ ràng (3-5 câu) theo ngôn ngữ thân thiện.\n\n"
        f"--- LỊCH SỬ HỘI THOẠI ---\n{history_text}\n---\n\n"
        "Quy tắc:\n"
        "- Liệt kê: vị trí, tính chất, thời gian, triệu chứng kèm theo\n"
        "- Viết dạng tường thuật, không dùng bullet points\n"
        "- KHÔNG chẩn đoán, KHÔNG ghi tên bệnh\n"
        "- Trả về DUY NHẤT đoạn tổng hợp"
    )
    return _llm_call(prompt, max_tokens=384)


# 6️⃣ DEEP RED-FLAG SCREEN
def deep_emergency_screen(symptom_summary: str) -> dict:
    """Tầm soát red-flag toàn diện trên bản tổng hợp."""
    prompt = (
        "Bạn là bác sĩ cấp cứu. Dựa trên bản tổng hợp triệu chứng dưới đây, đánh giá có dấu hiệu "
        "cấp cứu (red-flag) cần xử trí khẩn cấp không.\n\n"
        f"Triệu chứng: {symptom_summary}\n\n"
        "Danh sách red-flag:\n"
        "- Đau ngực kèm khó thở, lan tay trái → Nhồi máu cơ tim\n"
        "- Đau đầu đột ngột dữ dội, cứng cổ → Xuất huyết dưới nhện\n"
        "- Liệt nửa người, méo miệng → Đột quỵ\n"
        "- Sốt cao + co giật → Viêm màng não / sốt cao co giật\n"
        "- Xuất huyết ồ ạt không cầm\n"
        "- Ý tưởng / hành vi tự sát\n"
        "- Khó thở nặng, tím tái\n"
        "- Bỏng nặng diện rộng\n\n"
        "Trả về JSON: {\"is_emergency\": true/false, \"reason\": \"lý do nếu cấp cứu\"}"
    )
    result = _llm_json(prompt, max_tokens=256)
    return result if result else {"is_emergency": False, "reason": ""}


# 7️⃣ ROUTE SPECIALTY (RAG + LLM)
def route_specialty(symptom_summary: str, rag_context: str) -> dict:
    """Tra cứu RAG + Suy luận chuyên khoa kèm giải thích."""
    prompt = (
        "Bạn là trợ lý tư vấn y tế VMEC ân cần, chuyên nghiệp.\n"
        "Dựa vào Tri thức Y khoa và bản tổng hợp triệu chứng, hãy đưa ra tư vấn và "
        "định hướng chuyên khoa phù hợp.\n\n"
        "LƯU Ý: Chỉ định hướng Chuyên khoa Nhi nếu bệnh nhân đề cập trẻ em/bé.\n"
        "Nếu bệnh nhân là người lớn hoặc không đề cập đối tượng → tư vấn cho người lớn.\n\n"
        f"--- TRI THỨC Y KHOA ---\n{rag_context}\n---\n\n"
        f"--- TRIỆU CHỨNG TỔNG HỢP ---\n{symptom_summary}\n---\n\n"
        "Trả về DUY NHẤT 1 JSON:\n"
        "{\n"
        '  "specialty_id": "SP_NEUROLOGY",\n'
        '  "specialty_name_vi": "Chuyên khoa Nội thần kinh",\n'
        '  "sub_specialty_name_vi": "Thần kinh",\n'
        '  "rationale": "Lời tư vấn ân cần, chi tiết 3-5 câu...",\n'
        '  "precautions": ["Lưu ý 1", "Lưu ý 2"],\n'
        '  "action": "suggest_specialty"\n'
        "}"
    )
    result = _llm_json(prompt, max_tokens=1024)
    if not result:
        result = {
            "specialty_id": "SP_GENERAL_MEDICINE",
            "specialty_name_vi": "Chuyên khoa Nội tổng quát",
            "rationale": "Bạn nên thăm khám trực tiếp tại cơ sở y tế để bác sĩ đánh giá chính xác hơn.",
            "precautions": [],
        }
    return result


# ---------------------------------------------------------------------------
# Response Builders
# ---------------------------------------------------------------------------

def _greeting_response(session: Session) -> ChatResponse:
    return ChatResponse(
        response=(
            "Chào bạn! 👋 Tôi là Trợ lý AI Y khoa VMEC. "
            "Tôi sẽ giúp bạn tìm hiểu triệu chứng và định hướng chuyên khoa phù hợp.\n\n"
            "Bạn có thể mô tả triệu chứng hoặc vấn đề sức khỏe bạn đang gặp phải không ạ?"
        ),
        session_id=session.session_id,
        stage=session.stage.value,
    )


def _emergency_response(session: Session, reason: str = "") -> ChatResponse:
    msg = (
        "🚨 **CẢNH BÁO CẤP CỨU**\n\n"
        "Triệu chứng bạn mô tả có dấu hiệu cần xử trí **cấp cứu khẩn cấp**.\n\n"
    )
    if reason:
        msg += f"⚠️ {reason}\n\n"
    msg += (
        "👉 **Hãy gọi ngay 115** hoặc đến phòng Cấp cứu gần nhất.\n"
        "👉 Nếu có người bên cạnh, nhờ họ hỗ trợ đưa bạn đi ngay.\n\n"
        "🏥 Khoa tiếp nhận: **Khoa Cấp cứu**\n\n"
        "⏱️ Mỗi phút đều quan trọng. Đừng chần chờ!"
    )
    session.stage = Stage.DONE
    return ChatResponse(
        response=msg,
        session_id=session.session_id,
        stage=session.stage.value,
        emergency=True,
        metadata={"specialty_name_vi": "Khoa Cấp cứu"},
    )


def _specialty_response(session: Session, result: dict) -> ChatResponse:
    spec_id = result.get("specialty_id", "SP_GENERAL_MEDICINE")
    vi_name = result.get("specialty_name_vi") or SPECIALTY_NAME_MAP.get(spec_id, "Chuyên khoa Nội tổng quát")
    sub_name = result.get("sub_specialty_name_vi", "")
    rationale = result.get("rationale", "Bạn nên thăm khám trực tiếp để bác sĩ tư vấn kỹ hơn.")
    precautions = result.get("precautions", [])

    msg = f"{rationale}\n\n"
    if precautions:
        msg += "📋 **Lưu ý trước khi thăm khám:**\n"
        for p in precautions:
            msg += f"  • {p}\n"
        msg += "\n"
    msg += (
        "⚕️ *Lưu ý: Thông tin trên chỉ mang tính chất tham khảo và định hướng. "
        "Vui lòng thăm khám trực tiếp với bác sĩ chuyên khoa để được chẩn đoán và tư vấn chính xác.*"
    )

    session.stage = Stage.DONE
    return ChatResponse(
        response=msg,
        session_id=session.session_id,
        stage=session.stage.value,
        metadata={
            "specialty_id": spec_id,
            "specialty_name_vi": vi_name,
            "sub_specialty_name_vi": sub_name,
        },
    )


# ---------------------------------------------------------------------------
# Web UI HTML
# ---------------------------------------------------------------------------

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VMEC AI Agent – Trợ Lý Y Khoa Thông Minh</title>
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
            --success: #22c55e;
            --danger: #ef4444;
            --warning: #f59e0b;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Outfit', sans-serif; }
        body { background: var(--bg); color: var(--text); display: flex; justify-content: center; align-items: center; min-height: 100vh; padding: 16px; }

        .chat-app {
            width: 100%; max-width: 900px; height: 90vh;
            background: var(--panel); backdrop-filter: blur(16px);
            border: 1px solid var(--border); border-radius: 24px;
            display: flex; flex-direction: column; overflow: hidden;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
        }
        .header {
            padding: 20px 24px; border-bottom: 1px solid var(--border);
            display: flex; justify-content: space-between; align-items: center;
            background: rgba(15, 23, 42, 0.4);
        }
        .header h1 { font-size: 1.25rem; font-weight: 600; display: flex; align-items: center; gap: 10px; }
        .badge { background: rgba(34, 197, 94, 0.15); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.3); padding: 4px 12px; border-radius: 20px; font-size: 0.8rem; font-weight: 500; }

        .chat-body { flex: 1; padding: 24px; overflow-y: auto; display: flex; flex-direction: column; gap: 16px; }
        .chat-body::-webkit-scrollbar { width: 6px; }
        .chat-body::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.15); border-radius: 3px; }

        .msg-wrapper {
            max-width: 80%; position: relative;
            animation: fadeSlide 0.3s ease-out;
        }
        .msg-wrapper.user { align-self: flex-end; }
        .msg-wrapper.agent { align-self: flex-start; }
        .msg {
            padding: 14px 18px; border-radius: 18px;
            line-height: 1.7; font-size: 0.95rem; white-space: pre-wrap;
        }
        @keyframes fadeSlide {
            from { opacity: 0; transform: translateY(8px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .msg-wrapper.user .msg { background: var(--primary); color: white; border-bottom-right-radius: 4px; }
        .msg-wrapper.agent .msg { background: rgba(255, 255, 255, 0.05); border: 1px solid var(--border); border-bottom-left-radius: 4px; }
        .msg-wrapper.emergency .msg { border-color: var(--danger); background: rgba(239, 68, 68, 0.1); }

        .copy-btn {
            position: absolute; top: 8px; right: 8px;
            background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.15);
            color: rgba(255,255,255,0.5); width: 30px; height: 30px;
            border-radius: 8px; cursor: pointer; display: flex;
            align-items: center; justify-content: center;
            opacity: 0; transition: all 0.2s; font-size: 14px;
            backdrop-filter: blur(8px);
        }
        .msg-wrapper:hover .copy-btn { opacity: 1; }
        .copy-btn:hover { background: rgba(255,255,255,0.2); color: #fff; transform: scale(1.1); }
        .copy-btn.copied { background: rgba(34,197,94,0.3); color: #4ade80; border-color: rgba(34,197,94,0.4); }

        .copy-tooltip {
            position: absolute; top: -28px; right: 0;
            background: rgba(34,197,94,0.9); color: #fff; font-size: 0.7rem;
            padding: 3px 10px; border-radius: 6px; pointer-events: none;
            opacity: 0; transition: opacity 0.2s; white-space: nowrap;
        }
        .copy-tooltip.show { opacity: 1; }

        .msg-wrapper.user .copy-btn { right: 8px; }
        .msg-wrapper.agent .copy-btn { right: 8px; }

        .meta-tag { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
        .meta-pill {
            background: rgba(99, 102, 241, 0.2); border: 1px solid rgba(99, 102, 241, 0.4);
            color: #a5b4fc; padding: 6px 14px; border-radius: 12px;
            font-size: 0.85rem; font-weight: 500;
        }
        .meta-pill.sub {
            background: rgba(168, 85, 247, 0.2); color: #e9d5ff;
            border-color: rgba(168, 85, 247, 0.4);
        }

        .typing-indicator {
            align-self: flex-start; padding: 14px 18px; border-radius: 18px;
            background: rgba(255, 255, 255, 0.05); border: 1px solid var(--border);
            border-bottom-left-radius: 4px; display: flex; gap: 6px; align-items: center;
        }
        .typing-dot {
            width: 8px; height: 8px; border-radius: 50%; background: var(--accent);
            animation: bounce 1.4s infinite ease-in-out;
        }
        .typing-dot:nth-child(2) { animation-delay: 0.2s; }
        .typing-dot:nth-child(3) { animation-delay: 0.4s; }
        @keyframes bounce {
            0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
            40% { transform: scale(1); opacity: 1; }
        }

        .stage-label {
            text-align: center; font-size: 0.75rem; color: rgba(255,255,255,0.3);
            padding: 4px 0; letter-spacing: 0.5px;
        }

        .footer { padding: 16px 24px; border-top: 1px solid var(--border); display: flex; gap: 12px; background: rgba(15, 23, 42, 0.4); }
        input {
            flex: 1; background: rgba(255, 255, 255, 0.05); border: 1px solid var(--border);
            padding: 14px 20px; border-radius: 14px; color: white; outline: none;
            transition: border-color 0.2s;
        }
        input:focus { border-color: var(--primary); }
        input::placeholder { color: rgba(255,255,255,0.35); }
        button {
            background: var(--primary); color: white; border: none;
            padding: 14px 28px; border-radius: 14px; cursor: pointer;
            font-weight: 600; transition: all 0.2s;
        }
        button:hover { background: var(--primary-hover); transform: translateY(-1px); }
        button:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }

        .new-chat-btn {
            background: rgba(255,255,255,0.08); border: 1px solid var(--border);
            color: var(--text); padding: 6px 14px; border-radius: 10px; cursor: pointer;
            font-size: 0.8rem; font-weight: 500; transition: all 0.2s;
        }
        .new-chat-btn:hover { background: rgba(255,255,255,0.15); }
    </style>
</head>
<body>
    <div class="chat-app">
        <div class="header">
            <h1>🤖 VMEC AI Agent Chatbot</h1>
            <div style="display:flex;gap:10px;align-items:center;">
                <button class="new-chat-btn" onclick="newChat()">🔄 Cuộc trò chuyện mới</button>
                <span class="badge">🟢 TRỰC TUYẾN 24/7</span>
            </div>
        </div>
        <div class="chat-body" id="chat">
            <div class="msg agent">Chào bạn! 👋 Tôi là Trợ lý AI Y khoa VMEC.

Tôi sẽ giúp bạn tìm hiểu triệu chứng và định hướng chuyên khoa phù hợp thông qua cuộc trò chuyện ngắn.

Bạn có thể mô tả triệu chứng hoặc vấn đề sức khỏe bạn đang gặp phải không ạ?</div>
        </div>
        <div class="footer">
            <input type="text" id="userInput" placeholder="Mô tả triệu chứng của bạn..." onkeypress="if(event.key==='Enter') send();">
            <button id="sendBtn" onclick="send()">Gửi</button>
        </div>
    </div>
    <script>
        let sessionId = crypto.randomUUID ? crypto.randomUUID().replace(/-/g,'').slice(0,16) : Date.now().toString(36);

        function newChat() {
            sessionId = crypto.randomUUID ? crypto.randomUUID().replace(/-/g,'').slice(0,16) : Date.now().toString(36);
            const chat = document.getElementById('chat');
            chat.innerHTML = '<div class="msg agent">Chào bạn! 👋 Tôi là Trợ lý AI Y khoa VMEC.\\n\\nTôi sẽ giúp bạn tìm hiểu triệu chứng và định hướng chuyên khoa phù hợp thông qua cuộc trò chuyện ngắn.\\n\\nBạn có thể mô tả triệu chứng hoặc vấn đề sức khỏe bạn đang gặp phải không ạ?</div>';
        }

        async function send() {
            const input = document.getElementById('userInput');
            const btn = document.getElementById('sendBtn');
            const txt = input.value.trim();
            if (!txt) return;

            appendMsg('user', escapeHtml(txt));
            input.value = '';
            btn.disabled = true;

            // Typing indicator
            const typing = document.createElement('div');
            typing.className = 'typing-indicator';
            typing.innerHTML = '<div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div>';
            document.getElementById('chat').appendChild(typing);
            scrollToBottom();

            try {
                const res = await fetch('/api/v1/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: txt, session_id: sessionId })
                });
                const data = await res.json();
                typing.remove();

                if (data.session_id) sessionId = data.session_id;

                let extraHTML = '';

                // Specialty pills
                if (data.metadata && data.metadata.specialty_name_vi) {
                    const viSpec = data.metadata.specialty_name_vi;
                    const subSpec = data.metadata.sub_specialty_name_vi || '';
                    let subPill = subSpec ? '<span class="meta-pill sub">🔍 Phân khoa: <strong>' + subSpec + '</strong></span>' : '';
                    extraHTML = '<div class="meta-tag"><span class="meta-pill">🏥 ' + viSpec + '</span>' + subPill + '</div>';
                }

                const cssClass = data.emergency ? 'agent emergency' : 'agent';
                appendMsg(cssClass, formatMarkdown(data.response) + extraHTML);

            } catch (e) {
                typing.remove();
                appendMsg('agent', '❌ Lỗi kết nối máy chủ. Vui lòng thử lại.');
            }
            btn.disabled = false;
            document.getElementById('userInput').focus();
        }

        function appendMsg(cls, html) {
            const wrapper = document.createElement('div');
            wrapper.className = 'msg-wrapper ' + cls;

            const msgDiv = document.createElement('div');
            msgDiv.className = 'msg';
            msgDiv.innerHTML = html;
            wrapper.appendChild(msgDiv);

            // Copy button
            const copyBtn = document.createElement('button');
            copyBtn.className = 'copy-btn';
            copyBtn.title = 'Sao chép';
            copyBtn.innerHTML = '📋';
            copyBtn.onclick = function() { copyMsg(this, msgDiv); };
            wrapper.appendChild(copyBtn);

            // Tooltip
            const tooltip = document.createElement('span');
            tooltip.className = 'copy-tooltip';
            tooltip.textContent = 'Đã sao chép!';
            copyBtn.appendChild(tooltip);

            document.getElementById('chat').appendChild(wrapper);
            scrollToBottom();
        }

        function copyMsg(btn, msgDiv) {
            const text = msgDiv.innerText || msgDiv.textContent;
            navigator.clipboard.writeText(text).then(function() {
                btn.classList.add('copied');
                btn.innerHTML = '✅';
                const tip = document.createElement('span');
                tip.className = 'copy-tooltip show';
                tip.textContent = 'Đã sao chép!';
                btn.appendChild(tip);
                setTimeout(function() {
                    btn.classList.remove('copied');
                    btn.innerHTML = '📋';
                }, 1500);
            }).catch(function() {
                // Fallback for older browsers
                const ta = document.createElement('textarea');
                ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
                document.body.appendChild(ta); ta.select();
                document.execCommand('copy'); document.body.removeChild(ta);
                btn.classList.add('copied');
                btn.innerHTML = '✅';
                setTimeout(function() {
                    btn.classList.remove('copied');
                    btn.innerHTML = '📋';
                }, 1500);
            });
        }

        function scrollToBottom() {
            const chat = document.getElementById('chat');
            chat.scrollTop = chat.scrollHeight;
        }

        function escapeHtml(t) {
            return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
        }

        function formatMarkdown(text) {
            // Bold: **text**
            text = text.replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>');
            // Newlines
            text = text.replace(/\\n/g, '<br>');
            return text;
        }
    </script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    return HTML_TEMPLATE


@app.post("/api/v1/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Multi-turn conversational chat endpoint."""
    session = get_or_create_session(request.session_id)
    user_msg = request.message.strip()

    # === STAGE: DONE → Auto-reset for new conversation ===
    if session.stage == Stage.DONE:
        session = Session(session.session_id)
        _sessions[session.session_id] = session

    # === STAGE: IDLE → Classify intent & begin ===
    if session.stage == Stage.IDLE:
        intent = classify_intent(user_msg)
        log.info("session=%s intent=%s msg=%s", session.session_id, intent, user_msg[:60])

        if intent == "greeting":
            return _greeting_response(session)

        # Quick emergency screen on first message
        if quick_emergency_screen(user_msg):
            return _emergency_response(session, reason="Phát hiện từ khóa cấp cứu trong tin nhắn.")

        # Begin gathering symptoms
        session.stage = Stage.GATHERING
        session.add_message("user", user_msg)

        # Assess if this single message already sufficient
        sufficiency = assess_sufficiency(session.history_text())
        if sufficiency.get("verdict") == "sufficient":
            # Jump straight to summarize
            summary = summarize_symptoms(session.history_text())
            session.symptom_summary = summary
            session.stage = Stage.CONFIRMING
            session.add_message("assistant", f"Tôi hiểu bạn đang gặp tình trạng sau:\n\n📋 {summary}\n\nBạn xác nhận thông tin trên có đúng không ạ? (Nếu cần bổ sung hay chỉnh sửa, hãy cho tôi biết nhé!)")
            return ChatResponse(
                response=f"Tôi hiểu bạn đang gặp tình trạng sau:\n\n📋 {summary}\n\nBạn xác nhận thông tin trên có đúng không ạ? (Nếu cần bổ sung hay chỉnh sửa, hãy cho tôi biết nhé!)",
                session_id=session.session_id,
                stage=session.stage.value,
            )

        # Need more info → follow-up
        missing = sufficiency.get("missing_aspects", [])
        follow_up = generate_follow_up(session.history_text(), missing)
        session.follow_up_count += 1
        session.add_message("assistant", follow_up)
        return ChatResponse(
            response=follow_up,
            session_id=session.session_id,
            stage=session.stage.value,
        )

    # === STAGE: GATHERING → Continue collecting symptoms ===
    if session.stage == Stage.GATHERING:
        session.add_message("user", user_msg)

        # Quick emergency check on every message
        if quick_emergency_screen(user_msg):
            return _emergency_response(session, reason="Phát hiện triệu chứng cấp cứu trong mô tả.")

        sufficiency = assess_sufficiency(session.history_text())

        if sufficiency.get("verdict") == "need_more" and session.follow_up_count < MAX_FOLLOW_UP_ROUNDS:
            missing = sufficiency.get("missing_aspects", [])
            follow_up = generate_follow_up(session.history_text(), missing)
            session.follow_up_count += 1
            session.add_message("assistant", follow_up)
            return ChatResponse(
                response=follow_up,
                session_id=session.session_id,
                stage=session.stage.value,
            )

        # Sufficient or max rounds reached → Summarize
        summary = summarize_symptoms(session.history_text())
        session.symptom_summary = summary
        session.stage = Stage.CONFIRMING

        confirm_msg = (
            f"Cảm ơn bạn đã chia sẻ! Theo những gì bạn mô tả, tôi tổng hợp lại như sau:\n\n"
            f"📋 {summary}\n\n"
            f"Bạn xác nhận thông tin trên có đúng không ạ? "
            f"(Nếu cần bổ sung hay chỉnh sửa, hãy cho tôi biết nhé!)"
        )
        session.add_message("assistant", confirm_msg)
        return ChatResponse(
            response=confirm_msg,
            session_id=session.session_id,
            stage=session.stage.value,
        )

    # === STAGE: CONFIRMING → Wait for yes/no ===
    if session.stage == Stage.CONFIRMING:
        intent = classify_intent(user_msg)
        log.info("session=%s confirm_intent=%s", session.session_id, intent)

        if intent == "confirmation_yes":
            # Deep red-flag screen on confirmed summary
            red_flag = deep_emergency_screen(session.symptom_summary)
            if red_flag.get("is_emergency"):
                return _emergency_response(session, reason=red_flag.get("reason", ""))

            # RAG + Route specialty
            rag_context = retrieve_cockroach_context(session.symptom_summary, limit=5)
            result = route_specialty(session.symptom_summary, rag_context)
            return _specialty_response(session, result)

        elif intent == "confirmation_no_correction" or intent == "symptom_related":
            # User wants to correct or add info → back to gathering
            session.stage = Stage.GATHERING
            session.add_message("user", user_msg)

            correction_msg = (
                "Cảm ơn bạn đã bổ sung thông tin! "
                "Bạn có thể mô tả thêm chi tiết để tôi hiểu rõ hơn không ạ?"
            )
            session.add_message("assistant", correction_msg)
            return ChatResponse(
                response=correction_msg,
                session_id=session.session_id,
                stage=session.stage.value,
            )

        else:
            # Ambiguous → treat as symptom info
            session.stage = Stage.GATHERING
            session.add_message("user", user_msg)
            sufficiency = assess_sufficiency(session.history_text())

            if sufficiency.get("verdict") == "need_more" and session.follow_up_count < MAX_FOLLOW_UP_ROUNDS:
                missing = sufficiency.get("missing_aspects", [])
                follow_up = generate_follow_up(session.history_text(), missing)
                session.follow_up_count += 1
                session.add_message("assistant", follow_up)
                return ChatResponse(
                    response=follow_up,
                    session_id=session.session_id,
                    stage=session.stage.value,
                )
            else:
                summary = summarize_symptoms(session.history_text())
                session.symptom_summary = summary
                session.stage = Stage.CONFIRMING
                confirm_msg = (
                    f"Tôi tổng hợp lại thông tin như sau:\n\n📋 {summary}\n\n"
                    f"Bạn xác nhận có đúng không ạ?"
                )
                session.add_message("assistant", confirm_msg)
                return ChatResponse(
                    response=confirm_msg,
                    session_id=session.session_id,
                    stage=session.stage.value,
                )

    # Fallback
    return ChatResponse(
        response="Xin lỗi, tôi chưa hiểu yêu cầu của bạn. Bạn có thể mô tả lại triệu chứng được không ạ?",
        session_id=session.session_id,
        stage=session.stage.value,
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
