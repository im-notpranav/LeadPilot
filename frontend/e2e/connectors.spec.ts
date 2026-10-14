import { expect, test, type Page } from "@playwright/test";

// Runs against the auth-off stack, where the local user is an admin.
const API = "http://127.0.0.1:8010";
const RUN = Date.now().toString(36);

test.beforeAll(async ({ request }) => {
  await expect
    .poll(async () => (await (await request.get(`${API}/api/sim/status`)).json()).status, { timeout: 120_000 })
    .toBe("ready");
  await request.post(`${API}/api/sim/pause`);
});

function trackErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  return errors;
}
const fitsWidth = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);

test("an admin creates a form connector, a submission becomes a lead, and the delivery is logged", async ({ page }) => {
  const errors = trackErrors(page);
  await page.goto("/connectors");
  await expect(page.locator("main h1")).toHaveText("Connectors");
  await page.getByLabel("Connector type").selectOption("form");
  await page.getByPlaceholder("e.g. Website demo form").fill(`E2E form ${RUN}`);
  await page.getByRole("button", { name: "Create connector" }).click();

  const setup = page.getByRole("region", { name: "Connector setup" });
  await expect(setup).toContainText(`Set up “E2E form ${RUN}”`);
  const hookUrl = (await setup.locator("pre").filter({ hasText: "?token=whsec_" }).textContent())!.trim();
  expect(hookUrl).toMatch(/\/api\/hooks\/con_[0-9a-f]+\?token=whsec_/);

  const email = `e2e-${RUN}@formco.io`;
  const res = await page.request.post(hookUrl, { data: { email, name: "Eve Twoe", company: "FormCo", form_type: "Book a demo" } });
  expect(res.ok()).toBe(true);
  expect((await res.json()).status).toBe("accepted");

  await setup.getByRole("button", { name: "Done" }).click();
  await expect(page.getByText(/whsec_[A-Za-z0-9_-]{20,}/)).toHaveCount(0);      // full secret gone from the page
  const row = page.getByRole("row", { name: new RegExp(`^E2E form ${RUN} source:`) });
  await expect(row).toContainText("Active");
  await expect(page.getByText("Accepted").first()).toBeVisible({ timeout: 20_000 }); // deliveries poll every 5 s
  await expect.poll(() => fitsWidth(page)).toBe(true);
  await page.locator("main a[href^='/leads/']").first().click();
  await expect(page.getByText("Eve Twoe").first()).toBeVisible();
  expect(errors).toEqual([]);
});

test("a tracker connector shows the script snippet with its site key", async ({ page }) => {
  await page.goto("/connectors");
  await page.getByLabel("Connector type").selectOption("tracker");
  await page.getByPlaceholder("e.g. Website demo form").fill(`E2E site ${RUN}`);
  await page.getByRole("button", { name: "Create connector" }).click();
  const snippet = page.getByRole("region", { name: "Connector setup" }).locator("pre").first();
  await expect(snippet).toContainText('/api/t.js" data-key="lpk_');
  const js = await page.request.get("/api/t.js");
  expect(js.ok()).toBe(true);
  expect(await js.text()).toContain("window.leadpilot");
});

test("a manager imports a CSV after checking the column mapping", async ({ page }) => {
  const errors = trackErrors(page);
  const csv = ["Email Address,Full Name,Company,Notes",
               `ann-${RUN}@csv.io,Ann CSV,Acme,met at expo`,
               `bob-${RUN}@csv.io,Bob CSV,Beta,`,
               ",No Contact,Gamma,"].join("\n");
  await page.goto("/import");
  await expect(page.locator("main h1")).toHaveText("Import leads");
  await page.getByLabel("CSV file").setInputFiles({ name: "leads.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
  await page.getByRole("textbox", { name: "Lead source" }).fill("expo_2026");
  await page.getByRole("button", { name: "Preview" }).click();

  await expect(page.getByText("Ready to import")).toBeVisible();
  await expect(page.getByLabel("Column Email Address")).toHaveValue("email");
  await expect(page.getByLabel("Column Notes")).toHaveValue("message");
  await page.getByLabel("Column Company").selectOption("");                   // ignore a column: preview refreshes
  await expect(page.getByRole("cell", { name: "Acme" })).toHaveCount(0);
  await expect(page.getByText("Line 4:")).toBeVisible();                       // the row without contact details
  await expect.poll(() => fitsWidth(page)).toBe(true);

  await page.getByRole("button", { name: "Import 2 leads" }).click();
  await expect(page.getByText("Import finished")).toBeVisible();
  await expect(page.locator("section", { hasText: "Import finished" }).getByText("New leads")).toBeVisible();
  await page.locator("main a[href^='/leads/']").first().click();
  await expect(page.getByText(/(Ann|Bob) CSV/i).first()).toBeVisible();      // names are title-cased on capture
  await expect(page.getByText("Unknown company").first()).toBeVisible();       // the ignored column was not imported
  expect(errors).toEqual([]);
});
