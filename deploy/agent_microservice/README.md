# 🌐 HƯỚNG DẪN DEPLOY CHATBOT AGENT MICROSERVICE LÊN RENDER / RAILWAY VỚI COCKROACHDB CLOUD

Tài liệu này hướng dẫn cách deploy gói ứng dụng Chatbot Agent độc lập kết nối với **CockroachDB Cloud Vector Database (cockroachlabs.cloud)**.

---

## 📋 1. DANH SÁCH BỘ CODE DEPLOY
Mô-đun độc lập nằm tại thư mục `deploy/agent_microservice/`:
- 📄 `main.py`: Mã nguồn FastAPI siêu nhẹ phục vụ UI & API `/api/v1/chat`.
- 🐳 `Dockerfile`: Đóng gói Container Python 3.11.
- 📦 `requirements.txt`: Các phụ thuộc tối giản.
- 🔑 `env.example`: Mẫu cấu hình môi trường Cloud.

---

## ☁️ 2. BƯỚC 1: TẠO COCKROACHDB CLOUD VECTOR DATABASE (MIỄN PHÍ)
1. Đăng ký tài khoản tại **[cockroachlabs.cloud](https://cockroachlabs.cloud/)**.
2. Bấm **Create Cluster** ➔ Chọn **Serverless (Free)**.
3. Chọn khu vực: **Asia-Southeast (Singapore hoặc Tokyo)**.
4. Lấy chuỗi kết nối (Connection String):
   `postgresql://<username>:<password>@<cluster-host>:26257/vmec?sslmode=verify-full`

---

## 🔄 3. BƯỚC 2: MIGRATION VECTOR 1024D LÊN COCKROACHDB CLOUD
Chạy lệnh sau trên máy máy tính của bạn để đẩy dữ liệu Vector 1024d từ local lên Cloud:
```bash
set COCKROACH_DATABASE_URL=postgresql://user:pass@cluster.cockroachlabs.cloud:26257/vmec?sslmode=verify-full
python scripts/migrate_to_cockroach_cloud.py
```

---

## 🚀 4. BƯỚC 3: DEPLOY LÊN RENDER.COM (MIỄN PHÍ 24/7)
1. Đăng nhập **[Render.com](https://render.com/)** ➔ Chọn **New Web Service**.
2. Kết nối với Repository GitHub của bạn.
3. Cấu hình cài đặt:
   - **Root Directory**: `deploy/agent_microservice`
   - **Environment**: `Docker` hoặc `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Khai báo 2 biến môi trường (**Environment Variables**):
   - `GEMINI_API_KEY`: `<khóa-api-gemini-của-bạn>`
   - `COCKROACH_DATABASE_URL`: `<chuỗi-kết-nối-cockroachdb-cloud>`
5. Bấm **Create Web Service**. Sau 1-2 phút, ứng dụng Chatbot Agent y khoa của bạn sẽ chạy trực tuyến 24/7 tại địa chỉ URL công khai!
