"use client";
import { useCallback, useEffect, useState } from "react";
import { api, Appointment, friendlyError } from "../../lib/api";

export default function Operations() {
  const [queue, setQueue] = useState<Appointment[]>([]); const [loading, setLoading] = useState(true); const [error, setError] = useState("");
  const load = useCallback(async () => { setLoading(true); setError(""); try { setQueue((await api.staffQueue()).items) } catch (reason) { setError(friendlyError(reason)) } finally { setLoading(false) } }, []);
  useEffect(() => {
    const task = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(task);
  }, [load]);
  async function decide(id: string, approve: boolean) { try { await api.staffDecision(id, approve); await load() } catch (reason) { setError(friendlyError(reason)) } }
  return <main className="page"><p className="eyebrow">Cổng nhân viên · Phân quyền bắt buộc</p><h1>Điều phối an toàn</h1>
    {loading && <section className="stateCard" aria-live="polite">Đang tải hàng đợi…</section>}
    {error && <section className="stateCard forbidden" role="alert"><h2>Không thể mở hàng đợi</h2><p>{error}</p><button onClick={load}>Thử lại</button></section>}
    {!loading && !error && <section className="tableCard"><div className="panelHead"><h2>Hàng đợi lịch hẹn</h2><span>{queue.length} mục chờ xử lý</span></div>
      {queue.length === 0 ? <div className="emptyState"><h3>Hàng đợi trống</h3><p>Không có lịch hẹn nào đang chờ phê duyệt.</p></div> : <div className="tableScroll"><table><thead><tr><th>Mã</th><th>Bệnh nhân</th><th>Trạng thái</th><th>Thao tác</th></tr></thead><tbody>{queue.map((item) => <tr key={item.id}><td>{item.id.slice(0, 8)}</td><td>{item.patient_id}</td><td><span className="pill">{item.status}</span></td><td className="inlineActions"><button onClick={() => decide(item.id, true)}>Phê duyệt</button><button className="secondaryButton" onClick={() => decide(item.id, false)}>Từ chối</button></td></tr>)}</tbody></table></div>}
    </section>}
  </main>;
}
