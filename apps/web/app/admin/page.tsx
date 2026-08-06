"use client";

import { useEffect, useState } from "react";
import { api, AuditEvent, Diagnostics, friendlyError } from "../../lib/api";

export default function AdminPortal() {
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [diagnostics, setDiagnostics] = useState<Diagnostics | null>(null);
  const [error, setError] = useState("");
  const [copyStatus, setCopyStatus] = useState<"idle" | "copying" | "copied">("idle");

  useEffect(() => {
    Promise.all([api.audit(), api.diagnostics()])
      .then(([audit, status]) => {
        setEvents(audit);
        setDiagnostics(status);
      })
      .catch((reason) => setError(friendlyError(reason)));
  }, []);

  async function copyDebugLog() {
    try {
      setCopyStatus("copying");
      const res = await api.debugReport();
      await navigator.clipboard.writeText(res.report);
      setCopyStatus("copied");
      setTimeout(() => setCopyStatus("idle"), 3000);
    } catch (err) {
      alert("Không thể tạo Debug Log Report: " + friendlyError(err));
      setCopyStatus("idle");
    }
  }

  return (
    <main className="page">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "16px", marginBottom: "20px" }}>
        <div>
          <p className="eyebrow">Cổng quản trị</p>
          <h1 style={{ margin: 0 }}>Vận hành và nhật ký hệ thống</h1>
        </div>
        <button
          onClick={copyDebugLog}
          disabled={copyStatus === "copying"}
          style={{
            backgroundColor: copyStatus === "copied" ? "#16a34a" : "#0284c7",
            color: "#ffffff",
            border: "none",
            borderRadius: "8px",
            padding: "10px 18px",
            fontSize: "14px",
            fontWeight: 600,
            cursor: "pointer",
            display: "inline-flex",
            alignItems: "center",
            gap: "8px",
            boxShadow: "0 2px 4px rgba(0,0,0,0.1)",
            transition: "all 0.2s ease",
          }}
        >
          {copyStatus === "copying"
            ? "⏳ Đang tổng hợp Debug Log…"
            : copyStatus === "copied"
            ? "✅ Đã sao chép 7-step Debug Report!"
            : "📋 Copy Toàn Bộ Debug Log (7 Checklist)"}
        </button>
      </div>

      {error ? (
        <section className="stateCard forbidden" role="alert">
          {error}
        </section>
      ) : events === null || diagnostics === null ? (
        <section className="stateCard">Đang tải trạng thái…</section>
      ) : (
        <>
          <section className="cardGrid" aria-label="Chẩn đoán nền tảng">
            <article className="stateCard">
              <h2>Data runtime</h2>
              <p>Release: {diagnostics.release_id}</p>
              <p>
                Rows: {diagnostics.imported_rows.toLocaleString("vi-VN")} · Sources: {diagnostics.canonical_sources}
              </p>
              <span className="pill">{diagnostics.release_status}</span>
            </article>
            <article className="stateCard">
              <h2>Gemini</h2>
              <p>{diagnostics.gemini_models.join(" ↔ ")}</p>
              <p>
                {diagnostics.embedding_models.join(" + ")} · {diagnostics.embedding_dimensions}d
              </p>
            </article>
            <article className="stateCard degraded">
              <h2>Production gates</h2>
              <p>Data approved: {diagnostics.production_approved ? "Có" : "Không"}</p>
              <p>
                Full embedding backfill: {diagnostics.full_embedding_backfill_permitted ? "Được phép" : "Chưa được phép"}
              </p>
            </article>
          </section>
          {events.length === 0 ? (
            <section className="emptyState">
              <h2>Chưa có sự kiện</h2>
              <p>Nhật ký audit hiện đang trống.</p>
            </section>
          ) : (
            <section className="tableCard">
              <div className="tableScroll">
                <table>
                  <thead>
                    <tr>
                      <th>Thời gian</th>
                      <th>Hành động</th>
                      <th>Đối tượng</th>
                      <th>Kết quả</th>
                    </tr>
                  </thead>
                  <tbody>
                    {events.map((event) => (
                      <tr key={event.id}>
                        <td>{new Date(event.occurred_at).toLocaleString("vi-VN")}</td>
                        <td>{event.action}</td>
                        <td>{event.target_type}</td>
                        <td>
                          <span className="pill">{event.outcome}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>
      )}
    </main>
  );
}
