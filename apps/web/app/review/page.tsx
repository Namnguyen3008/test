"use client";

import { useEffect, useState } from "react";
import { api, friendlyError } from "../../lib/api";
import type { WorkflowReviewItem } from "../../lib/api";

type Decision = "APPROVE" | "REJECT" | "REQUEST_CHANGES";

export default function ReviewPortal() {
  const [items, setItems] = useState<WorkflowReviewItem[] | null>(null);
  const [rationales, setRationales] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  function update(next: WorkflowReviewItem) {
    setItems((current) => current?.map((item) => (item.id === next.id ? next : item)) ?? [next]);
  }

  async function claim(item: WorkflowReviewItem) {
    setBusy(item.id);
    setError("");
    try {
      update(await api.claimReview(item.id, item.version));
    } catch (reason) {
      setError(friendlyError(reason));
    } finally {
      setBusy("");
    }
  }

  async function release(item: WorkflowReviewItem) {
    setBusy(item.id);
    setError("");
    try {
      update(await api.releaseReview(item.id, item.version));
    } catch (reason) {
      setError(friendlyError(reason));
    } finally {
      setBusy("");
    }
  }

  async function decide(item: WorkflowReviewItem, decision: Decision) {
    const rationale = rationales[item.id]?.trim() ?? "";
    if (rationale.length < 20) {
      setError("Rationale phải có ít nhất 20 ký tự.");
      return;
    }
    setBusy(item.id);
    setError("");
    try {
      update(await api.decideReview(item.id, item.version, decision, rationale));
      setRationales((value) => ({ ...value, [item.id]: "" }));
    } catch (reason) {
      setError(friendlyError(reason));
    } finally {
      setBusy("");
    }
  }

  useEffect(() => {
    api.workflowReviewQueue().then(setItems).catch((reason) => setError(friendlyError(reason)));
  }, []);

  return (
    <main className="page">
      <p className="eyebrow">Cổng duyệt lâm sàng</p>
      <h1>Kiểm duyệt có trách nhiệm</h1>
      <p className="lede">
        Mọi quyết định cần rationale và audit. Mục safety-critical cần hai reviewer độc lập; workflow không tự đặt
        DATA_APPROVED.
      </p>
      {error && (
        <section className="stateCard forbidden" role="alert">
          {error}
        </section>
      )}
      {items === null ? (
        <section className="stateCard">Đang tải hàng đợi…</section>
      ) : items.length === 0 ? (
        <section className="emptyState">
          <h2>Không có mục trong workflow</h2>
          <p>Admin chưa nhập review package vào persistent database.</p>
        </section>
      ) : (
        <section className="cardGrid">
          {items.map((item) => (
            <article className="stateCard" key={item.id}>
              <p className="eyebrow">{item.origin_table}</p>
              <h2>{item.origin_row_id}</h2>
              <p>{item.evidence_summary}</p>
              <p>
                <span className="pill">{item.status}</span>{" "}
                {item.safety_critical && <span className="pill">2 reviewer bắt buộc</span>}
              </p>
              <small>Nguồn: {item.source_ids.join(", ")}</small>
              {item.status !== "CLAIMED" && !["APPROVED", "REJECTED"].includes(item.status) && (
                <p>
                  <button onClick={() => claim(item)} disabled={busy === item.id}>
                    Claim item
                  </button>
                </p>
              )}
              {item.status === "CLAIMED" && (
                <div className="reviewActions">
                  <label htmlFor={`rationale-${item.id}`}>Rationale bắt buộc</label>
                  <textarea
                    id={`rationale-${item.id}`}
                    value={rationales[item.id] ?? ""}
                    onChange={(event) =>
                      setRationales((value) => ({ ...value, [item.id]: event.target.value }))
                    }
                    minLength={20}
                    maxLength={2000}
                  />
                  <div className="inlineActions">
                    <button onClick={() => decide(item, "APPROVE")} disabled={busy === item.id}>
                      Approve
                    </button>
                    <button onClick={() => decide(item, "REQUEST_CHANGES")} disabled={busy === item.id}>
                      Request change
                    </button>
                    <button onClick={() => decide(item, "REJECT")} disabled={busy === item.id}>
                      Reject
                    </button>
                    <button onClick={() => release(item)} disabled={busy === item.id}>
                      Release
                    </button>
                  </div>
                </div>
              )}
            </article>
          ))}
        </section>
      )}
    </main>
  );
}
