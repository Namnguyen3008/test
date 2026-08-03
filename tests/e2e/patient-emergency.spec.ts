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

test("operations page exposes no raw patient identity", async ({ page }) => {
  await page.goto("/operations");
  await expect(page.getByRole("heading", { name: "Điều phối an toàn" })).toBeVisible();
  await expect(page.getByText("BN •••• 291")).toBeVisible();
  await expect(page.locator("body")).not.toContainText("Nguyễn Văn");
});
