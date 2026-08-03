import { expect, test } from "@playwright/test";

test("patient emergency flow short-circuits routine booking", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Bắt đầu đúng chuyên khoa, an tâm hơn." })).toBeVisible();
  await expect(page.getByText("Môi trường phát triển — dữ liệu chưa được phê duyệt lâm sàng.")).toBeVisible();
  await page.getByLabel("Mô tả tình trạng").fill("Toi dang bat tinh va khong danh thuc duoc");
  await page.getByRole("button", { name: "Gửi mô tả" }).click();
  await expect(page.getByText("Cảnh báo khẩn cấp")).toBeVisible();
  await expect(page.locator(".answer p")).toContainText("115");
  await expect(page.getByRole("button", { name: "Xem chuyên khoa và lịch trống" })).toHaveCount(0);
});

test("operations portal denies unauthenticated access without exposing patient identity", async ({ page }) => {
  await page.goto("/operations");
  await expect(page.getByRole("heading", { name: "Điều phối an toàn" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Không thể mở hàng đợi" })).toBeVisible();
  await expect(page.locator("body")).not.toContainText("Nguyễn Văn");
});

test("patient appointment portal renders real API empty states", async ({ page }) => {
  await page.route("**/api/v1/booking/appointments", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [] }) }),
  );
  await page.route("**/api/v1/booking/availability**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [] }) }),
  );
  await page.goto("/appointments");
  await expect(page.getByRole("heading", { name: "Hành trình khám rõ ràng" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Chưa có lịch hẹn" })).toBeVisible();
  await expect(page.getByText("Hiện chưa có lịch trống phù hợp.")).toBeVisible();
});
