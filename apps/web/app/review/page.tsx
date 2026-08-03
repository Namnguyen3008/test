"use client";
import { useEffect, useState } from "react";
import { api, friendlyError, User } from "../../lib/api";
export default function ReviewPortal() {
  const [user, setUser] = useState<User | null>(null); const [error, setError] = useState("");
  useEffect(() => { api.me().then((value) => value.role === "CLINICAL_REVIEWER" || value.role === "ADMIN" ? setUser(value) : setError("Bạn không có quyền truy cập chức năng này.")).catch((reason) => setError(friendlyError(reason))) }, []);
  return <main className="page"><p className="eyebrow">Cổng duyệt lâm sàng</p><h1>Kiểm duyệt có trách nhiệm</h1>{error ? <section className="stateCard forbidden" role="alert">{error}</section> : !user ? <section className="stateCard">Đang xác minh quyền…</section> : <section className="stateCard degraded"><h2>Hàng đợi chưa khả dụng</h2><p>Phiên đăng nhập đã được xác minh. Backend chưa cung cấp endpoint hàng đợi duyệt lâm sàng; hệ thống không hiển thị dữ liệu mô phỏng.</p></section>}</main>;
}
