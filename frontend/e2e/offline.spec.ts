// 失败口径（DES-6/SEC-A6）验收：后端不可达时不白屏、不漏浏览器原生英文异常；
// 已加载数据在失败时保留；后端恢复后点“重试”可达。
import { expect, test } from "@playwright/test";

test("后端不可达：中文错误态＋重试入口，恢复后重试可达", async ({ page }) => {
  await page.route("**/api/**", (r) => r.abort());
  await page.goto("/app/#/");
  const alert = page.getByRole("alert");
  await expect(alert).toContainText("无法连接服务器");
  await expect(alert).not.toContainText("Failed to fetch");
  await expect(page.getByRole("button", { name: "重试" })).toBeVisible();
  await page.unroute("**/api/**");
  await page.getByRole("button", { name: "重试" }).click();
  await expect(page.getByRole("heading", { name: /笔交易/ })).toBeVisible();
});

test("已加载后断后端：报错为中文且已加载数据不清空", async ({ page, request }) => {
  const d = await (await request.post("/api/v2/deals", {
    data: { name: "离线保留样例", track: "commercial", address: "7 Offline St", kill_criteria: [] },
  })).json();
  expect(d.id).toBeTruthy();
  await page.goto("/app/#/");
  await expect(page.getByRole("heading", { name: /笔交易/ })).toBeVisible();
  await expect(page.getByText("离线保留样例").first()).toBeVisible();

  await page.route("**/api/**", (r) => r.abort());
  page.on("dialog", (dlg) => void dlg.accept("离线视图"));
  await page.getByRole("button", { name: "保存当前视图" }).click();
  await expect(page.getByText(/无法连接服务器/)).toBeVisible();
  await expect(page.getByText("Failed to fetch")).toHaveCount(0);
  await expect(page.getByText("离线保留样例").first()).toBeVisible();  // 已加载列表仍在
  await page.unroute("**/api/**");
});
