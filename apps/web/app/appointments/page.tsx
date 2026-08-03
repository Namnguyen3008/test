"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, Appointment, friendlyError, Slot } from "../../lib/api";

const statusLabels: Record<string, string> = {
  HELD: "Đang giữ chỗ", PENDING_STAFF_APPROVAL: "Chờ nhân viên duyệt", CONFIRMED: "Đã xác nhận",
  RESCHEDULE_PROPOSED: "Cần xác nhận lịch mới", CANCELLED: "Đã hủy", REJECTED: "Không được duyệt", EXPIRED: "Đã hết hạn",
};
const formatDate = (value: string) => new Intl.DateTimeFormat("vi-VN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));

export default function Appointments() {
  const [items, setItems] = useState<Appointment[]>([]); const [slots, setSlots] = useState<Slot[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "forbidden" | "error">("loading"); const [message, setMessage] = useState("");
  const load = useCallback(async () => {
    setState("loading"); setMessage("");
    try {
      const from = new Date(); const to = new Date(from.getTime() + 30 * 24 * 60 * 60 * 1000);
      const [history, available] = await Promise.all([api.appointments(), api.availability(from, to)]);
      setItems(history.items); setSlots(available.items); setState("ready");
    } catch (error) { setMessage(friendlyError(error)); setState(error instanceof Error && "status" in error && error.status === 403 ? "forbidden" : "error") }
  }, []);
  useEffect(() => {
    const task = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(task);
  }, [load]);
  async function mutate(action: () => Promise<Appointment>) {
    setMessage(""); try { await action(); await load() } catch (error) { setMessage(friendlyError(error)) }
  }
  return <main className="page"><p className="eyebrow">Lịch hẹn của tôi</p><h1>Hành trình khám rõ ràng</h1>
    {state === "loading" && <section className="stateCard" aria-live="polite">Đang tải lịch hẹn…</section>}
    {state === "forbidden" && <section className="stateCard forbidden" role="alert"><h2>Không có quyền truy cập</h2><p>Tài khoản này không có quyền bệnh nhân.</p><Link href="/login">Đăng nhập tài khoản khác</Link></section>}
    {state === "error" && <section className="stateCard degraded" role="alert"><h2>Chưa thể tải dữ liệu</h2><p>{message}</p><button type="button" onClick={load}>Thử lại</button></section>}
    {state === "ready" && <>
      {message && <div className="errorState" role="alert">{message}</div>}
      <section aria-labelledby="appointments-title"><h2 id="appointments-title">Lịch đã đặt</h2>
        {items.length === 0 ? <div className="emptyState"><span aria-hidden="true">⌁</span><h3>Chưa có lịch hẹn</h3><p>Chọn một lịch trống bên dưới để giữ chỗ trong 5 phút.</p></div> :
          <div className="cardGrid">{items.map((item) => <article className="appointmentCard" key={item.id} data-testid="appointment-card">
            <div><span className="pill">{statusLabels[item.status] ?? item.status}</span><h3>Mã lịch {item.id.slice(0, 8)}</h3><p>Cập nhật {formatDate(item.updated_at)}</p></div>
            <div className="cardActions">{["HELD", "RESCHEDULE_PROPOSED"].includes(item.status) && <button onClick={() => mutate(() => api.confirm(item.id))}>Xác nhận</button>}
              {!['CANCELLED','REJECTED','EXPIRED'].includes(item.status) && <button className="secondaryButton" onClick={() => mutate(() => api.cancel(item.id))}>Hủy lịch</button>}</div>
          </article>)}</div>}
      </section>
      <section aria-labelledby="slots-title"><h2 id="slots-title">Lịch trống trong 30 ngày</h2>
        {slots.length === 0 ? <div className="stateCard">Hiện chưa có lịch trống phù hợp.</div> : <div className="cardGrid">{slots.map((slot) => <article className="slotCard" key={slot.id}><h3>{slot.specialty_id ?? "Chuyên khoa"}</h3><p>{formatDate(slot.starts_at)}</p><p>Cơ sở: {slot.facility_id ?? "Sẽ cập nhật"}</p><button onClick={() => mutate(() => api.hold(slot.id))}>Giữ chỗ</button></article>)}</div>}
      </section>
    </>}
  </main>;
}
