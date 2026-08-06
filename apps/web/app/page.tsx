"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import Link from "next/link";

interface Message {
  id: string;
  sender: "user" | "bot";
  text: string;
  emergency?: boolean;
  metadata?: Record<string, unknown>;
  timestamp: string;
}

const QUICK_CHIPS = [
  "Bị đau từ hôm qua",
  "Mới xuất hiện sáng nay",
  "Có kèm sốt nhẹ",
  "Đã dùng thuốc nhưng chưa đỡ",
];

const INITIAL_MESSAGE: Message = {
  id: "init-1",
  sender: "bot",
  text: "Xin chào! Tôi là Trợ lý Định hướng Chuyên khoa VMEC. Bạn đang cảm thấy thế nào hoặc có triệu chứng gì bất thường hôm nay?",
  timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
};

export default function PatientHome() {
  const [inputText, setInputText] = useState("");
  const [messages, setMessages] = useState<Message[]>([INITIAL_MESSAGE]);
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, status]);

  async function sendMessage(textToSend: string) {
    const trimmed = textToSend.trim();
    if (!trimmed || status === "loading") return;

    const userMsg: Message = {
      id: `usr-${Date.now()}`,
      sender: "user",
      text: trimmed,
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    };

    const updatedMessages = [...messages, userMsg];
    setMessages(updatedMessages);
    setInputText("");
    setStatus("loading");

    const historyPayload = updatedMessages
      .filter((m) => m.id !== "init-1")
      .map((m) => ({
        role: m.sender === "user" ? "user" : "assistant",
        content: m.text,
      }));

    try {
      const response = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/v1/chat`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Dev-Auto-Auth": "true",
          },
          body: JSON.stringify({
            message: trimmed,
            history: historyPayload,
          }),
        }
      );

      if (!response.ok) throw new Error("API_ERROR");

      const data = (await response.json()) as {
        response: string;
        emergency: boolean;
        metadata: Record<string, unknown>;
      };

      const botMsg: Message = {
        id: `bot-${Date.now()}`,
        sender: "bot",
        text: data.response,
        emergency: data.emergency,
        metadata: data.metadata,
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      };

      setMessages((prev) => [...prev, botMsg]);
      setStatus("idle");
    } catch {
      setStatus("error");
    }
  }

  function handleFormSubmit(e: FormEvent) {
    e.preventDefault();
    sendMessage(inputText);
  }

  function resetChat() {
    setMessages([INITIAL_MESSAGE]);
    setStatus("idle");
    setInputText("");
  }

  return (
    <main>
      <section className="hero">
        <div>
          <p className="eyebrow">Định hướng sức khỏe có căn cứ</p>
          <h1>
            Bắt đầu đúng chuyên khoa, <em>an tâm hơn.</em>
          </h1>
          <p className="lead">
            Hệ thống hỗ trợ trao đổi trực tiếp, sàng lọc yếu tố nguy cơ khẩn cấp và gợi ý đúng chuyên khoa lâm sàng.
          </p>
        </div>
        <aside className="emergencyNote">
          <strong>Trường hợp khẩn cấp</strong>
          <p>
            Gọi ngay <b>115</b> hoặc đến cơ sở cấp cứu gần nhất. Không chờ phản hồi trực tuyến.
          </p>
        </aside>
      </section>

      <section className="chatPanel" aria-labelledby="chat-title">
        <div className="panelHead">
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span className="onlineDot" /> Trợ lý tư vấn VMEC
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <button
              onClick={resetChat}
              style={{
                background: "transparent",
                border: "1px solid #cbd5e1",
                borderRadius: "6px",
                padding: "4px 10px",
                fontSize: "12px",
                cursor: "pointer",
                color: "#475569",
              }}
            >
              🔄 Làm mới hội thoại
            </button>
            <span style={{ fontSize: "12px", color: "#64748b" }}>Riêng tư · Không chẩn đoán</span>
          </div>
        </div>

        <div className="conversation" aria-live="polite" style={{ display: "flex", flexDirection: "column", gap: "16px", padding: "20px" }}>
          <h2 id="chat-title" className="srOnly">Hội thoại tư vấn</h2>

          {messages.map((msg) => {
            const specialtyId = typeof msg.metadata?.specialty_id === "string" ? msg.metadata.specialty_id : null;

            return (
              <div
                key={msg.id}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: msg.sender === "user" ? "flex-end" : "flex-start",
                }}
              >
                <div
                  className={msg.emergency ? "answer emergency" : msg.sender === "user" ? "userBubble" : "answer"}
                  style={{
                    maxWidth: "85%",
                    padding: "14px 18px",
                    borderRadius: msg.sender === "user" ? "16px 16px 2px 16px" : "16px 16px 16px 2px",
                    backgroundColor: msg.sender === "user" ? "#0284c7" : msg.emergency ? "#fef2f2" : "#f8fafc",
                    color: msg.sender === "user" ? "#ffffff" : "#1e293b",
                    border: msg.sender === "user" ? "none" : msg.emergency ? "1px solid #fca5a5" : "1px solid #e2e8f0",
                    boxShadow: "0 1px 3px rgba(0,0,0,0.05)",
                  }}
                >
                  {msg.sender === "bot" && (
                    <strong style={{ display: "block", marginBottom: "6px", fontSize: "13px", color: msg.emergency ? "#dc2626" : "#0284c7" }}>
                      {msg.emergency ? "⚠️ Cảnh báo khẩn cấp" : "🏥 VMEC AI Assistant"}
                    </strong>
                  )}

                  <p style={{ margin: 0, lineHeight: 1.6, whiteSpace: "pre-wrap" }}>{msg.text}</p>

                  {msg.sender === "bot" && !msg.emergency && specialtyId && (
                    <div style={{ marginTop: "14px", paddingTop: "12px", borderTop: "1px dashed #cbd5e1" }}>
                      <p style={{ fontSize: "13px", fontWeight: 600, color: "#334155", marginBottom: "8px" }}>
                        📌 Chuyên khoa phù hợp nhất: <u>{specialtyId}</u>
                      </p>
                      <Link
                        href={`/appointments?specialty=${specialtyId}`}
                        style={{
                          display: "inline-block",
                          padding: "10px 18px",
                          backgroundColor: "#0284c7",
                          color: "#ffffff",
                          borderRadius: "8px",
                          textDecoration: "none",
                          fontWeight: 600,
                          fontSize: "14px",
                        }}
                      >
                        Đặt khám chuyên khoa này ngay →
                      </Link>
                    </div>
                  )}

                  <span
                    style={{
                      display: "block",
                      marginTop: "6px",
                      fontSize: "11px",
                      opacity: 0.7,
                      textAlign: "right",
                    }}
                  >
                    {msg.timestamp}
                  </span>
                </div>
              </div>
            );
          })}

          {status === "loading" && (
            <div style={{ display: "flex", alignItems: "center", gap: "8px", color: "#64748b", fontSize: "14px" }}>
              <span className="onlineDot" style={{ animation: "pulse 1s infinite" }} />
              Trợ lý đang phân tích dữ liệu lâm sàng…
            </div>
          )}

          {status === "error" && (
            <div className="errorState" role="alert">
              Dịch vụ đang gián đoạn. Vui lòng thử lại hoặc liên hệ nhân viên VMEC.
            </div>
          )}

          <div ref={chatEndRef} />
        </div>

        <div style={{ padding: "8px 20px", display: "flex", gap: "8px", flexWrap: "wrap", borderTop: "1px solid #f1f5f9" }}>
          <span style={{ fontSize: "12px", color: "#64748b", alignSelf: "center", marginRight: "4px" }}>Gợi ý bổ sung:</span>
          {QUICK_CHIPS.map((chip, idx) => (
            <button
              key={idx}
              type="button"
              onClick={() => sendMessage(chip)}
              disabled={status === "loading"}
              style={{
                backgroundColor: "#f1f5f9",
                border: "1px solid #cbd5e1",
                borderRadius: "16px",
                padding: "6px 14px",
                fontSize: "12px",
                color: "#334155",
                cursor: "pointer",
                transition: "all 0.2s",
              }}
            >
              + {chip}
            </button>
          ))}
        </div>

        <form className="composer" onSubmit={handleFormSubmit}>
          <label className="srOnly" htmlFor="symptom">
            Mô tả tình trạng
          </label>
          <textarea
            id="symptom"
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendMessage(inputText);
              }
            }}
            placeholder="Nhập mô tả triệu chứng hoặc trả lời trợ lý (bấm Enter để gửi)…"
            maxLength={5000}
          />
          <button disabled={status === "loading" || !inputText.trim()}>
            {status === "loading" ? "Đang xử lý…" : "Gửi phản hồi"}
          </button>
        </form>
      </section>

      <section className="trustGrid">
        <div>
          <b>01</b>
          <h3>Khẩn cấp trước tiên</h3>
          <p>Luật sàng lọc chạy trước AI và đặt lịch.</p>
        </div>
        <div>
          <b>02</b>
          <h3>Có nguồn tham chiếu</h3>
          <p>Mọi gợi ý chuyên khoa cần liên kết nguồn hợp lệ.</p>
        </div>
        <div>
          <b>03</b>
          <h3>Bạn luôn kiểm soát</h3>
          <p>Chỉ xác nhận lịch khi bạn đồng ý và nhân viên duyệt.</p>
        </div>
      </section>
    </main>
  );
}
