import { expect, test } from "@playwright/test";

test("offline SOS survives reload and syncs exactly once", async ({ page, context }) => {
  let posts = 0;
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/api/v1/sync")) posts += 1;
  });
  await page.goto("/");
  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.reload();
  await expect.poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller))).toBe(true);
  await context.setOffline(true);
  await page.getByLabel("Number of people").fill("2");
  await page.getByRole("checkbox", { name: "Medical" }).check();
  await page.getByRole("button", { name: "Save SOS" }).click();
  await expect(page.getByRole("status")).toContainText("Saved on this device");
  await page.reload();
  await expect(page.getByText(/Queued offline · 2/)).toBeVisible();
  await context.setOffline(false);
  await expect.poll(() => posts).toBe(1);
  await expect(page.getByText(/Received · 2/)).toBeVisible();
  await page.getByRole("button", { name: "Still need help" }).click();
  await expect.poll(() => posts).toBe(2);
  await page.getByRole("button", { name: "We are safe" }).click();
  await expect.poll(() => posts).toBe(3);
  await page.reload();
  await expect.poll(() => posts).toBe(3);
});
