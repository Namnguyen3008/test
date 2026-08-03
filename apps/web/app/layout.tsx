import type { Metadata } from "next";
import Link from "next/link";
import SessionBar from "../components/session-bar";
import "./globals.css";

export const metadata: Metadata = { title: "VMEC — Định hướng chuyên khoa an toàn", description: "Cổng định hướng chuyên khoa và quản lý lịch hẹn VMEC." };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="vi"><body>
    <header className="topbar"><Link className="brand" href="/" aria-label="VMEC trang chủ"><span className="brandMark">V</span><span>VMEC</span></Link>
      <nav aria-label="Điều hướng chính"><Link href="/">Tư vấn</Link><Link href="/appointments">Lịch hẹn</Link><Link href="/operations">Vận hành</Link></nav><SessionBar />
    </header>
    <div className="dataWarning" role="status">Môi trường phát triển — dữ liệu chưa được phê duyệt lâm sàng.</div>{children}
  </body></html>;
}
