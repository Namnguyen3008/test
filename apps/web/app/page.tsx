"use client";

import { FormEvent, useState } from "react";

type ChatResult = { response: string; emergency: boolean; metadata: Record<string, unknown> };

export default function PatientHome() {
  const [message, setMessage] = useState("");
  const [result, setResult] = useState<ChatResult | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!message.trim()) return;
    setStatus("loading");
    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/v1/chat`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message }),
      });
      if (!response.ok) throw new Error("api");
      setResult((await response.json()) as ChatResult);
      setStatus("idle");
    } catch {
      setStatus("error");
    }
  }

  return (
    <main>
      <section className="hero">
        <div>
          <p className="eyebrow">Định hướng sức khỏe có căn cứ</p>
          <h1>Bắt đầu đúng chuyên khoa, <em>an tâm hơn.</em></h1>
          <p className="lead">Mô tả điều bạn đang gặp. VMEC sàng lọc dấu hiệu khẩn cấp trước, sau đó hỗ trợ tìm chuyên khoa và lịch phù hợp.</p>
        </div>
        <aside className="emergencyNote"><strong>Trường hợp khẩn cấp</strong><p>Gọi ngay <b>115</b> hoặc đến cơ sở cấp cứu gần nhất. Không chờ phản hồi trực tuyến.</p></aside>
      </section>
      <section className="chatPanel" aria-labelledby="chat-title">
        <div className="panelHead"><div><span className="onlineDot" /> Trợ lý đang sẵn sàng</div><span>Riêng tư · Không chẩn đoán</span></div>
        <div className="conversation" aria-live="polite">
          <h2 id="chat-title">Bạn cần hỗ trợ điều gì hôm nay?</h2>
          <p>Hãy mô tả triệu chứng, độ tuổi và thời gian xuất hiện. Không nhập số CCCD hoặc thông tin thanh toán.</p>
          {result && <article className={result.emergency ? "answer emergency" : "answer"}><strong>{result.emergency ? "Cảnh báo khẩn cấp" : "Gợi ý an toàn"}</strong><p>{result.response}</p>{!result.emergency && <button type="button">Xem chuyên khoa và lịch trống</button>}</article>}
          {status === "error" && <div className="errorState">Dịch vụ đang gián đoạn. Vui lòng thử lại hoặc liên hệ nhân viên VMEC.</div>}
        </div>
        <form className="composer" onSubmit={submit}>
          <label className="srOnly" htmlFor="symptom">Mô tả tình trạng</label>
          <textarea id="symptom" value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Ví dụ: Tôi đau đầu từ sáng nay..." maxLength={5000} />
          <button disabled={status === "loading" || !message.trim()}>{status === "loading" ? "Đang kiểm tra…" : "Gửi mô tả"}</button>
        </form>
      </section>
      <section className="trustGrid"><div><b>01</b><h3>Khẩn cấp trước tiên</h3><p>Luật sàng lọc chạy trước AI và đặt lịch.</p></div><div><b>02</b><h3>Có nguồn tham chiếu</h3><p>Mọi gợi ý chuyên khoa cần liên kết nguồn hợp lệ.</p></div><div><b>03</b><h3>Bạn luôn kiểm soát</h3><p>Chỉ xác nhận lịch khi bạn đồng ý và nhân viên duyệt.</p></div></section>
    </main>
  );
}
