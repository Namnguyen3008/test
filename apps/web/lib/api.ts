export type Role = "PATIENT" | "STAFF" | "CLINICAL_REVIEWER" | "ADMIN";

export interface User { id: string; email: string; role: Role; active: boolean }
export interface Session { user: User; csrf_token: string; expires_at: string }
export interface Appointment {
  id: string; slot_id: string; proposed_slot_id: string | null; patient_id: string; status: string;
  hold_expires_at: string | null; patient_confirmed_at: string | null; patient_reconfirmed_at: string | null;
  staff_approved_at: string | null; version: number; created_at: string; updated_at: string;
}
export interface Slot { id: string; specialty_id: string | null; facility_id: string | null; practitioner_id: string | null; starts_at: string; ends_at: string }
export interface AuditEvent { id: number; actor_id: string | null; action: string; target_type: string; target_id: string | null; outcome: string; occurred_at: string }

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) { super(message) }
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function csrfToken(): string | undefined {
  if (typeof document === "undefined") return undefined;
  return document.cookie.split("; ").find((part) => part.startsWith("vmec_csrf="))?.split("=").slice(1).join("=");
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  const csrf = csrfToken();
  if (csrf && init.method && init.method !== "GET") headers.set("X-CSRF-Token", decodeURIComponent(csrf));
  const response = await fetch(`${API_URL}/api/v1${path}`, { ...init, headers, credentials: "include" });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new ApiError(response.status, body?.detail ?? "Không thể kết nối dịch vụ VMEC.");
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const mutationHeaders = (): HeadersInit => ({ "Idempotency-Key": crypto.randomUUID() });

export const api = {
  me: () => request<User>("/auth/me"),
  login: (email: string, password: string) => request<Session>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
  appointments: () => request<{ items: Appointment[] }>("/booking/appointments"),
  availability: (from: Date, to: Date) => request<{ items: Slot[] }>(`/booking/availability?${new URLSearchParams({ starts_after: from.toISOString(), ends_before: to.toISOString() })}`),
  hold: (slotId: string) => request<Appointment>("/booking/holds", { method: "POST", headers: mutationHeaders(), body: JSON.stringify({ slot_id: slotId, ttl_seconds: 300 }) }),
  confirm: (id: string) => request<Appointment>(`/booking/appointments/${id}/confirm`, { method: "POST", headers: mutationHeaders() }),
  cancel: (id: string) => request<Appointment>(`/booking/appointments/${id}/cancel`, { method: "POST", headers: mutationHeaders() }),
  staffQueue: () => request<{ items: Appointment[] }>("/booking/staff/queue"),
  staffDecision: (id: string, approve: boolean) => request<Appointment>(`/booking/staff/appointments/${id}/decision`, { method: "POST", headers: mutationHeaders(), body: JSON.stringify({ approve }) }),
  audit: () => request<AuditEvent[]>("/admin/audit?limit=100"),
};

export function friendlyError(error: unknown): string {
  if (error instanceof ApiError && error.status === 401) return "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.";
  if (error instanceof ApiError && error.status === 403) return "Bạn không có quyền truy cập chức năng này.";
  if (error instanceof ApiError && error.status === 409) return "Dữ liệu vừa thay đổi. Vui lòng tải lại và thử lại.";
  return error instanceof Error ? error.message : "Dịch vụ đang gián đoạn. Vui lòng thử lại sau.";
}
