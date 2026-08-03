const queue = [{ id: "VM-24081", patient: "BN •••• 291", specialty: "Tim mạch", state: "Chờ duyệt" }, { id: "VM-24082", patient: "BN •••• 734", specialty: "Nhi khoa", state: "Cần xem xét" }];

export default function Operations() {
  return <main className="page"><p className="eyebrow">Cổng nhân viên · Phân quyền bắt buộc</p><h1>Điều phối an toàn</h1><div className="metricGrid"><div><span>Chờ phê duyệt</span><b>12</b></div><div><span>Cần hỗ trợ người thật</span><b>4</b></div><div><span>Sức khỏe model</span><b className="healthy">2 / 2</b></div></div><section className="tableCard"><div className="panelHead"><h2>Hàng đợi lịch hẹn</h2><button>Lọc hàng đợi</button></div><table><thead><tr><th>Mã</th><th>Bệnh nhân</th><th>Chuyên khoa</th><th>Trạng thái</th></tr></thead><tbody>{queue.map((item) => <tr key={item.id}><td>{item.id}</td><td>{item.patient}</td><td>{item.specialty}</td><td><span className="pill">{item.state}</span></td></tr>)}</tbody></table></section></main>;
}
