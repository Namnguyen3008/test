# VMEC-01 — Codex Full Implementation Pack v2

Bộ này yêu cầu Codex triển khai **toàn bộ sản phẩm VMEC-01** trong repository local, sử dụng bốn bộ dữ liệu VMEC hiện có và cấu hình Gemini cố định của dự án.

## Cấu hình AI bắt buộc

### Model hội thoại và routing

Chỉ cho phép đúng hai model:

```text
gemini-3.1-flash-lite
gemini-3.5-flash-lite
```

Mỗi logical model request mới phải dùng distributed round-robin:

```text
3.1 → 3.5 → 3.1 → 3.5 → ...
```

- Bộ đếm round-robin đặt trong Redis để nhất quán giữa nhiều API replica.
- Nếu model được chọn lỗi tạm thời, request đó được failover sang model còn lại.
- Không được tự chuyển sang bất kỳ Gemini model nào khác.
- Khi cả hai model lỗi, dùng deterministic safe fallback và human handoff.

### Embedding

```text
Primary:  gemini-embedding-2
Fallback: gemini-embedding-001 — text only
Dimension: 768
Distance: cosine
```

Hai model embedding phải có **hai vector space và hai pgvector index riêng**. Không bao giờ so sánh query vector từ model này với document vector của model kia.

## Dữ liệu nguồn

Đặt bốn file sau trong `data/source/`:

```text
VMEC_FULL_DATA_RESEARCH_MASTER.zip
VMEC_FULL_DATA_DEVELOPMENT_READY.zip
VMEC_GLOBAL_SOURCE_LEDGER.csv.gz
VMEC_FULL_DATA_MASTER_INDEX.xlsx
```

- Development-ready: corpus conflict-free dùng development/testing.
- Research master: review/conflict/audit, không phục vụ trực tiếp cho bệnh nhân.
- Source ledger: citation toàn cục.
- Master index: inventory và QA summary.

## File trong pack

1. `AGENTS.md` — quy tắc project-level cho Codex.
2. `CODEX_MASTER_IMPLEMENTATION_PROMPT.md` — prompt triển khai lần đầu.
3. `CODEX_CONTINUE_IMPLEMENTATION_PROMPT.md` — prompt tiếp tục dự án.
4. `PROJECT_IMPLEMENTATION_SPEC.md` — đặc tả kiến trúc và sản phẩm.
5. `GEMINI_MODEL_ROUTING_POLICY.md` — quy tắc model rotation, failover và embedding.
6. `DATA_INGESTION_SPEC.md` — pipeline nhập dữ liệu lớn.
7. `ACCEPTANCE_CRITERIA.md` — Definition of Done.
8. `.env.vmec.example` — cấu hình chính xác, không chứa secret.
9. `PREPARE_VMEC_PROJECT.ps1` — copy/verify dữ liệu và chuẩn bị repo.
10. `VERIFY_GEMINI_MODELS.ps1` — kiểm tra API key có quyền nhìn thấy đúng bốn model.
11. `RUN_CODEX_FULL.ps1` — chạy Codex lần đầu.
12. `RUN_CODEX_CONTINUE.ps1` — tiếp tục từ trạng thái repo.

## Cách chạy nhanh trên Windows PowerShell

### 1. Giải nén pack vào repository

```text
D:\ALL ABOUT PROJECT\PROJECT\P-208\
```

Các file `AGENTS.md`, prompt và spec phải nằm ở root repo.

### 2. Chuẩn bị dữ liệu

```powershell
Set-ExecutionPolicy -Scope Process Bypass
cd "D:\ALL ABOUT PROJECT\PROJECT\P-208"

.\PREPARE_VMEC_PROJECT.ps1 `
  -RepoPath "D:\ALL ABOUT PROJECT\PROJECT\P-208" `
  -SourceDataDir "C:\DUONG_DAN_DEN_THU_MUC_CHUA_4_FILE"
```

### 3. Kiểm tra Gemini model access

```powershell
.\VERIFY_GEMINI_MODELS.ps1
```

Script chỉ báo model có/không, không in API key.

### 4. Chạy Codex triển khai toàn bộ

```powershell
.\RUN_CODEX_FULL.ps1
```

### 5. Khi một phiên Codex kết thúc nhưng dự án chưa đạt DoD

```powershell
.\RUN_CODEX_CONTINUE.ps1
```

Chạy lặp cho tới khi `docs/IMPLEMENTATION_STATUS.md` cho thấy toàn bộ acceptance criteria đạt và full test suite pass.

## Chế độ interactive

```powershell
codex --profile full-machine --strict-config
```

Sau đó gửi:

```text
Đọc CODEX_MASTER_IMPLEMENTATION_PROMPT.md và triển khai toàn bộ. Không dừng ở kế hoạch hoặc scaffold. Viết code, nhập dữ liệu, chạy test, sửa lỗi và commit theo milestone cho tới khi đạt ACCEPTANCE_CRITERIA.md hoặc gặp external blocker thật sự.
```

## Quy tắc bí mật

- Chỉ kiểm tra `GEMINI_API_KEY` có tồn tại; không in giá trị.
- Không dump environment.
- Không commit `.env`, key, token, cookie hoặc connection string.
- Không đưa Gemini key vào frontend.
- Không ghi raw symptom/PHI vào log.

## Kết quả cuối Codex phải tạo

- Monorepo chạy được bằng `docker compose up --build`.
- Patient portal và staff/reviewer portal.
- FastAPI, worker, PostgreSQL/pgvector, Redis.
- Emergency-first deterministic gate.
- Gemini round-robin 3.1/3.5 đúng quy tắc.
- Dual embedding indexes: Embedding 2 primary, Embedding 1 text fallback.
- Hybrid RAG có citation.
- Booking transactional không double-booking.
- Data importer cho toàn bộ archive.
- Unit/integration/E2E/race/security/evaluation tests.
- CI/CD, Docker, Helm, observability và runbooks.
