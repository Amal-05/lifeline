import { expect, test } from "@playwright/test";

test("coordinator can view synthetic risk map and encrypted registration", async ({ page }) => {
  await page.goto("/dashboard");
  await page.getByLabel("Email").fill("coordinator@example.com");
  await page.getByLabel("Password").fill("demo-only-change-me");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("img", { name: "Incident locations map" })).toBeVisible();
  await expect(page.getByLabel("teams")).toBeChecked();
  await page.getByLabel("teams").uncheck();
  await page.getByLabel("teams").check();
  await expect(page.getByRole("heading", { name: "Community risk map" })).toBeVisible();
  await expect(page.getByRole("img", { name: "Synthetic community risk map" })).toBeVisible();
  await page.getByLabel("I consent to secure storage of this household registration.").check();
  await page.getByRole("button", { name: "Encrypt and register" }).click();
  await expect(page.getByRole("status")).toContainText("Encrypted registration");
  await page.getByRole("button", { name: "Export household data" }).click();
  await expect(page.getByRole("status")).toContainText("Demo household");
  await page.getByRole("button", { name: "Delete household registration" }).click();
  await expect(page.getByRole("status")).toContainText("Registration deleted");
  await page.context().setOffline(true);
  await page.reload();
  await expect(page.getByRole("img", { name: "Synthetic community risk map" })).toBeVisible();
});
