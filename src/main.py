from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from sqlalchemy import text

from src.api.auth_routes import get_auth_rate_limiter, get_session_store
from src.api.auth_routes import router as auth_router
from src.api.operations_routes import router as operations_router
from src.api.routes import router
from src.booking.api import router as booking_router
from src.config import get_settings
from src.governance.canonical import digest, strict_json_loads
from src.governance.manifest import GovernanceManifest, TrustRegistry, verify_evidence, verify_manifest
from src.observability import configure_observability
from src.booking import models as _booking_models  # noqa: F401
from src.persistence.database import Base, get_engine
from src.review import models as _review_models  # noqa: F401
from src.review.api import router as review_router
from src.security import SecurityHeadersMiddleware
from src.services.emergency import (
    DataMode,
    activate_emergency_rules,
    compile_emergency_catalog,
    emergency_runtime_status,
    reset_emergency_rules,
)
from src.services.llm import get_llm
from src.services.routing import get_routing_retriever


@asynccontextmanager
async def lifespan(app: FastAPI):
    import logging

    logger = logging.getLogger("vmec.startup")
    settings = get_settings()
    try:
        Base.metadata.create_all(get_engine())
    except Exception as exc:
        logger.warning("PostgreSQL unavailable for create_all — running in isolated Chatbot MVP mode")
    if not settings.database_url.startswith(("postgresql://", "postgresql+")):
        logger.warning("Running in MVP mode — SQLite persistence, no Redis required")
    validate_data_readiness(
        settings.app_data_mode,
        settings.approved_corpus_manifest_path,
        settings.governance_trust_registry_path,
        settings.governance_evidence_path,
    )
    initialize_emergency_runtime(settings.app_data_mode, settings.emergency_catalog_path, settings.emergency_release_id)
    try:
        yield
    finally:
        reset_emergency_rules()
        for name, factory in (
            ("rate_limiter", get_auth_rate_limiter),
            ("session_store", get_session_store),
            ("llm", get_llm),
        ):
            try:
                if factory.cache_info().currsize:
                    resource = factory()
                    if hasattr(resource, "aclose"):
                        await resource.aclose()
                    factory.cache_clear()
            except Exception:
                logger.debug("Cleanup skipped for %s (not initialized)", name)
        try:
            if get_routing_retriever.cache_info().currsize:
                retriever = get_routing_retriever()
                if hasattr(retriever, "aclose"):
                    await retriever.aclose()
                get_routing_retriever.cache_clear()
        except Exception:
            logger.debug("Cleanup skipped for routing_retriever (not initialized)")



def validate_data_readiness(
    data_mode: DataMode,
    approved_manifest_path: str | None = None,
    trust_registry_path: str | None = None,
    evidence_path: str | None = None,
) -> None:
    manifest = Path(approved_manifest_path or get_settings().approved_corpus_manifest_path)
    if data_mode != "production":
        return
    registry = Path(trust_registry_path or get_settings().governance_trust_registry_path)
    evidence = Path(evidence_path or get_settings().governance_evidence_path)
    if not all(path.is_file() and not path.is_symlink() for path in (manifest, registry, evidence)):
        raise RuntimeError("Production data mode requires verified governance artifacts")
    try:
        parsed_manifest = GovernanceManifest.model_validate(strict_json_loads(manifest.read_text(encoding="utf-8")))
        parsed_registry = TrustRegistry.model_validate(strict_json_loads(registry.read_text(encoding="utf-8")))
        verify_manifest(parsed_manifest, parsed_registry)
        verify_evidence(parsed_manifest, evidence)
    except Exception as exc:
        raise RuntimeError("Production governance artifacts failed cryptographic verification") from exc


def initialize_emergency_runtime(data_mode: DataMode, catalog_path: str, release_id: str = "") -> None:
    catalog = Path(catalog_path)
    if not catalog.is_file():
        if data_mode == "production":
            raise RuntimeError("Production emergency corpus is unavailable")
        return
    selected_release = (
        release_id
        or {
            "development": "vmec-development-v2",
            "review": "vmec-review-v2",
            "production": "vmec-production-v1",
        }[data_mode]
    )
    ruleset = compile_emergency_catalog(catalog, release_id=selected_release, mode=data_mode)
    activate_emergency_rules(ruleset)


app = FastAPI(
    title="VMEC-01 API",
    description="Emergency-first specialty routing and appointment platform",
    version="1.0.0",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()] + ["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)

# --- TEMPORARY ISOLATION: RUN ONLY CHATBOT AGENT FLOW ---
app.include_router(router, prefix="/api/v1")
# app.include_router(auth_router, prefix="/api/v1")
# app.include_router(booking_router, prefix="/api/v1")
# app.include_router(operations_router, prefix="/api/v1")
# app.include_router(review_router, prefix="/api/v1")
configure_observability(app, settings)


from fastapi.responses import HTMLResponse

@app.get("/", response_class=HTMLResponse)
async def root_chat_ui():
    html_content = """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VMEC AI Chatbot Agent - Tư vấn Y Khoa</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-grad: linear-gradient(135deg, #0f172a 0%, #1e1b4b 50%, #0f172a 100%);
            --glass-bg: rgba(30, 41, 59, 0.7);
            --glass-border: rgba(255, 255, 255, 0.1);
            --accent: #6366f1;
            --accent-hover: #4f46e5;
            --text-main: #f8fafc;
            --text-sub: #94a3b8;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Outfit', sans-serif; }
        body { background: var(--bg-grad); color: var(--text-main); height: 100vh; display: flex; align-items: center; justify-content: center; p: 20px; }
        .chat-container { width: 100%; max-width: 900px; height: 90vh; background: var(--glass-bg); backdrop-filter: blur(16px); border: 1px solid var(--glass-border); border-radius: 24px; display: flex; flex-direction: column; overflow: hidden; box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5); }
        .chat-header { padding: 20px 24px; background: rgba(15, 23, 42, 0.6); border-bottom: 1px solid var(--glass-border); display: flex; align-items: center; justify-content: space-between; }
        .chat-header h1 { font-size: 1.25rem; font-weight: 600; display: flex; align-items: center; gap: 10px; }
        .status-badge { font-size: 0.75rem; background: rgba(34, 197, 94, 0.2); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.3); padding: 4px 12px; border-radius: 99px; font-weight: 500; }
        .chat-body { flex: 1; padding: 24px; overflow-y: auto; display: flex; flex-direction: column; gap: 16px; scroll-behavior: smooth; }
        .message { display: flex; flex-direction: column; max-width: 80%; animation: fadeIn 0.3s ease; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
        .message.user { align-self: flex-end; }
        .message.agent { align-self: flex-start; }
        .msg-bubble { padding: 14px 18px; border-radius: 18px; font-size: 0.95rem; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
        .message.user .msg-bubble { background: var(--accent); color: white; border-bottom-right-radius: 4px; }
        .message.agent .msg-bubble { background: rgba(51, 65, 85, 0.8); border: 1px solid var(--glass-border); color: #f1f5f9; border-bottom-left-radius: 4px; }
        .meta-tag { font-size: 0.75rem; color: var(--text-sub); margin-top: 6px; display: flex; gap: 8px; flex-wrap: wrap; }
        .meta-pill { background: rgba(99, 102, 241, 0.15); color: #a5b4fc; padding: 4px 10px; border-radius: 6px; font-weight: 500; }
        .meta-pill.cite-pill { background: rgba(14, 165, 233, 0.2); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3); }
        .chat-input-area { padding: 20px; background: rgba(15, 23, 42, 0.6); border-top: 1px solid var(--glass-border); display: flex; flex-direction: column; gap: 12px; }
        .quick-pills { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 4px; }
        .pill-btn { background: rgba(255, 255, 255, 0.05); border: 1px solid var(--glass-border); color: var(--text-sub); padding: 6px 14px; border-radius: 99px; font-size: 0.8rem; cursor: pointer; white-space: nowrap; transition: all 0.2s; }
        .pill-btn:hover { background: rgba(99, 102, 241, 0.2); color: #fff; border-color: var(--accent); }
        .input-row { display: flex; gap: 12px; }
        input[type="text"] { flex: 1; background: rgba(15, 23, 42, 0.8); border: 1px solid var(--glass-border); color: white; padding: 14px 20px; border-radius: 14px; font-size: 0.95rem; outline: none; transition: border 0.2s; }
        input[type="text"]:focus { border-color: var(--accent); }
        button.send-btn { background: var(--accent); color: white; border: none; padding: 0 24px; border-radius: 14px; font-weight: 600; cursor: pointer; transition: background 0.2s; }
        button.send-btn:hover { background: var(--accent-hover); }
    </style>
</head>
<body>
    <div class="chat-container">
        <div class="chat-header">
            <h1>🤖 VMEC AI Agent Chatbot <span>Tư vấn Y Khoa Vector 1024d</span></h1>
            <span class="status-badge">🟢 ONLINE / ISOLATED MODE</span>
        </div>
        <div class="chat-body" id="chatBody">
            <div class="message agent">
                <div class="msg-bubble">
                    Xin chào! Tôi là AI Agent tư vấn chuyên khoa Y Tế VMEC. Hãy mô tả triệu chứng sức khỏe của bạn (ví dụ: đau đầu, sốt, tức ngực...), tôi sẽ phân tích và gợi ý chuyên khoa phù hợp nhất!
                </div>
            </div>
        </div>
        <div class="chat-input-area">
            <div class="quick-pills">
                <button class="pill-btn" onclick="sendQuick('Tôi bị đau đầu dữ dội từ sáng kèm buồn nôn')">🧠 Đau đầu & Buồn nôn</button>
                <button class="pill-btn" onclick="sendQuick('Tôi bị tức ngực trái lan ra sau lưng khó thở')">🫀 Tức ngực & Khó thở</button>
                <button class="pill-btn" onclick="sendQuick('Sốt rét run từng cơn về chiều và mệt mỏi')">🌡️ Sốt rét run từng cơn</button>
            </div>
            <div class="input-row">
                <input type="text" id="userInput" placeholder="Nhập triệu chứng của bạn vào đây..." onkeydown="if(event.key==='Enter') sendMessage()">
                <button class="send-btn" onclick="sendMessage()">Gửi AI</button>
            </div>
        </div>
    </div>
    <script>
        async function sendMessage() {
            const input = document.getElementById('userInput');
            const msg = input.value.trim();
            if (!msg) return;
            appendMessage('user', msg);
            input.value = '';
            
            const typingDiv = appendMessage('agent', '⏳ AI Agent đang truy vấn Vector 1024d & phân tích...');
            
            try {
                const res = await fetch('/api/v1/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: msg, history: [] })
                });
                const data = await res.json();
                typingDiv.remove();
                
                let metaText = '';
                if (data.metadata) {
                    const viSpec = data.metadata.specialty_name_vi || '🩺 Chuyên khoa Nội tổng quát';
                    const subSpec = data.metadata.sub_specialty_name_vi || '';
                    
                    let specPills = `<span class="meta-pill">🏥 ${viSpec}</span>`;
                    if (subSpec) {
                        specPills += `<span class="meta-pill" style="background: rgba(168, 85, 247, 0.25); border: 1px solid rgba(168, 85, 247, 0.5); color: #e9d5ff;">🔍 Phân khoa sâu: <strong>${subSpec}</strong></span>`;
                    }
                    
                    let citeHTML = '';
                    if (data.metadata.citations && data.metadata.citations.length > 0) {
                        data.metadata.citations.forEach(c => {
                            const srcId = c.source_id || 'VMEC-SRC-01';
                            const loc = c.locator || 'Tài liệu chuẩn đoán lâm sàng';
                            let linkHTML = '';
                            if (loc.startsWith('http://') || loc.startsWith('https://')) {
                                linkHTML = `<a href="${loc}" target="_blank" style="color:#38bdf8;text-decoration:underline;margin-left:4px;">🔗 ${loc}</a>`;
                            } else {
                                linkHTML = `(${loc})`;
                            }
                            citeHTML += `<span class="meta-pill cite-pill">📚 Trích dẫn: <strong>${srcId}</strong> ${linkHTML}</span>`;
                        });
                    } else {
                        citeHTML = `<span class="meta-pill cite-pill">📚 Trích dẫn: <a href="https://ttcapcuu115.medinet.gov.vn/" target="_blank" style="color:#38bdf8;text-decoration:underline;">🔗 TT Cấp Cứu 115 Y Tế (VMEC Catalog 1024d)</a></span>`;
                    }
                    metaText = `<div class="meta-tag" style="display:flex;flex-wrap:wrap;gap:8px;margin-top:8px;">${specPills}${citeHTML}</div>`;
                }
                appendMessage('agent', data.response + metaText);
            } catch (err) {
                typingDiv.remove();
                appendMessage('agent', '❌ Lỗi kết nối API Server!');
            }
        }
        function sendQuick(txt) {
            document.getElementById('userInput').value = txt;
            sendMessage();
        }
        function appendMessage(role, htmlContent) {
            const body = document.getElementById('chatBody');
            const div = document.createElement('div');
            div.className = `message ${role}`;
            div.innerHTML = `<div class="msg-bubble">${htmlContent}</div>`;
            body.appendChild(div);
            body.scrollTop = body.scrollHeight;
            return div;
        }
    </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def readiness():
    settings = get_settings()
    persistence = "not_configured"
    if settings.database_url.startswith(("postgresql://", "postgresql+")):
        try:
            with get_engine().connect() as connection:
                migration = connection.scalar(text("SELECT version_num FROM alembic_version"))
                extensions = set(
                    connection.scalars(
                        text("SELECT extname FROM pg_extension WHERE extname IN ('vector','pg_trgm','unaccent')")
                    )
                )
                active_route = 1
                if settings.app_data_mode == "production":
                    manifest = GovernanceManifest.model_validate(
                        strict_json_loads(Path(settings.approved_corpus_manifest_path).read_text(encoding="utf-8"))
                    )
                    manifest_digest = digest(manifest.model_dump(mode="json"))
                    active_route = connection.scalar(
                        text("SELECT count(*) FROM governance_release_routes grr JOIN governance_manifests gm ON gm.manifest_id=grr.active_manifest_id WHERE grr.route_name='vmec-production-v1' AND grr.state='ACTIVE' AND grr.active_release_id IS NOT NULL AND gm.manifest_id=:manifest_id AND gm.manifest_digest=:manifest_digest AND gm.status='PROMOTED'"),
                        {"manifest_id": manifest.manifest_id, "manifest_digest": manifest_digest},
                    )
            if not (migration and migration.startswith("20260803_0010_signed_")) or extensions != {"vector", "pg_trgm", "unaccent"} or active_route != 1:
                raise RuntimeError("persistent schema is incomplete")
            redis = Redis.from_url(settings.redis_url)
            sessions = Redis.from_url(settings.session_redis_url)
            try:
                if not await redis.ping() or not await sessions.ping():
                    raise RuntimeError("persistent cache is unavailable")
            finally:
                await redis.aclose()
                await sessions.aclose()
            persistence = "verified"
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Runtime dependencies unavailable"
            ) from exc
    return {"status": "ready", "persistence": persistence, "emergency_rules": emergency_runtime_status()}
