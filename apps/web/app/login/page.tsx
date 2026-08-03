"use client";
import { FormEvent, useState } from "react";
import { api, friendlyError } from "../../lib/api";
const destinations = { PATIENT: "/appointments", STAFF: "/operations", CLINICAL_REVIEWER: "/review", ADMIN: "/admin" } as const;

export default function LoginPage() {
  const [email, setEmail] = useState(""); const [password, setPassword] = useState("");
  const [error, setError] = useState(""); const [loading, setLoading] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault(); setLoading(true); setError("");
    try { const session = await api.login(email, password); window.location.assign(destinations[session.user.role]) }
    catch (reason) { setError(friendlyError(reason)); setLoading(false) }
  }
  return <main className="page narrowPage"><p className="eyebrow">Cổng truy cập an toàn</p><h1>Đăng nhập VMEC</h1>
    <form className="formCard" onSubmit={submit} aria-busy={loading}>
      <label htmlFor="email">Email</label><input id="email" type="email" autoComplete="username" required value={email} onChange={(event) => setEmail(event.target.value)} />
      <label htmlFor="password">Mật khẩu</label><input id="password" type="password" autoComplete="current-password" minLength={12} required value={password} onChange={(event) => setPassword(event.target.value)} />
      {error && <div className="errorState" role="alert">{error}</div>}<button type="submit" disabled={loading}>{loading ? "Đang xác thực…" : "Đăng nhập"}</button>
    </form></main>;
}
