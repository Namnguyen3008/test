import Link from "next/link";

export default function Appointments() {
  return (
    <main className="page">
      <p className="eyebrow">Lịch hẹn của tôi</p>
      <h1>Hành trình khám rõ ràng</h1>
      <section className="emptyState">
        <span>⌁</span>
        <h2>Chưa có lịch hẹn</h2>
        <p>Sau khi chọn lịch, bạn sẽ thấy trạng thái giữ chỗ, xác nhận của bạn và phê duyệt từ nhân viên tại đây.</p>
        <Link href="/">Bắt đầu định hướng</Link>
      </section>
    </main>
  );
}
