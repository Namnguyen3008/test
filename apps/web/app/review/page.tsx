"use client";
import { useEffect, useState } from "react";
import { api, friendlyError, ReviewItem } from "../../lib/api";

export default function ReviewPortal() {
  const [items, setItems] = useState<ReviewItem[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.reviewQueue().then((value) => setItems(value.items)).catch((reason) => setError(friendlyError(reason))) }, []);
  return <main className="page"><p className="eyebrow">Cổng duyệt lâm sàng</p><h1>Kiểm duyệt có trách nhiệm</h1>
    <p className="lede">Hàng đợi chỉ đọc. Không có thao tác nào tự biến dữ liệu thành ACCEPTED hoặc GOLD.</p>
    {error ? <section className="stateCard forbidden" role="alert">{error}</section> : items === null ? <section className="stateCard">Đang tải hàng đợi…</section> : items.length === 0 ? <section className="emptyState"><h2>Không có mục chờ duyệt</h2><p>Catalog hiện không có nội dung REVIEW_REQUIRED phù hợp.</p></section> : <section className="cardGrid">{items.map((item) => <article className="stateCard" key={`${item.table}:${item.row_id}`}><p className="eyebrow">{item.table}</p><h2>{item.row_id}</h2><p>{item.content_preview}</p><p><span className="pill">{item.canonical_status}</span> <span className="pill">{item.review_status}</span></p><small>Nguồn: {item.source_ids.join(", ") || "chưa ánh xạ"}</small></article>)}</section>}
  </main>;
}
