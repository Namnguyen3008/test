"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, User } from "../lib/api";

export default function SessionBar() {
  const [user, setUser] = useState<User | null>(null);
  useEffect(() => { api.me().then(setUser).catch(() => setUser(null)) }, []);
  async function logout() { try { await api.logout() } finally { window.location.assign("/login") } }
  if (!user) return <Link className="sessionLink" href="/login">Đăng nhập</Link>;
  return <div className="sessionBar" data-testid="session-bar"><span>{user.email}</span><button type="button" onClick={logout}>Đăng xuất</button></div>;
}
