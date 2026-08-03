"use client";
import { useEffect, useState } from "react";
import { api, AuditEvent, friendlyError } from "../../lib/api";
export default function AdminPortal() {
  const [events, setEvents] = useState<AuditEvent[] | null>(null); const [error, setError] = useState("");
  useEffect(() => { api.audit().then(setEvents).catch((reason) => setError(friendlyError(reason))) }, []);
  return <main className="page"><p className="eyebrow">Cổng quản trị</p><h1>Nhật ký hệ thống</h1>{error ? <section className="stateCard forbidden" role="alert">{error}</section> : events === null ? <section className="stateCard">Đang tải nhật ký…</section> : events.length === 0 ? <section className="emptyState"><h2>Chưa có sự kiện</h2><p>Nhật ký audit hiện đang trống.</p></section> : <section className="tableCard"><div className="tableScroll"><table><thead><tr><th>Thời gian</th><th>Hành động</th><th>Đối tượng</th><th>Kết quả</th></tr></thead><tbody>{events.map((event) => <tr key={event.id}><td>{new Date(event.occurred_at).toLocaleString("vi-VN")}</td><td>{event.action}</td><td>{event.target_type}</td><td><span className="pill">{event.outcome}</span></td></tr>)}</tbody></table></div></section>}</main>;
}
