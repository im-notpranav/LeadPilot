import { expect, test, type Page } from "@playwright/test";

const API = "http://127.0.0.1:8010";
const ROUTES = ["/queue", "/leads", "/pipeline", "/pipeline?view=leads", "/accounts", "/feed", "/analytics", "/quality", "/simulator", "/settings"];

test.beforeAll(async ({ request }) => {
  // The demo backend generates history + a short warm-up before it serves data.
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

const fitsWidth = (page: Page) =>
  page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);

test("every page renders without runtime errors or horizontal overflow", async ({ page }) => {
  const errors = trackErrors(page);
  for (const route of ROUTES) {
    await page.goto(route);
    await expect(page.locator("main h1").first(), route).toBeVisible();
    await expect.poll(() => fitsWidth(page), { message: `${route} overflows` }).toBe(true);
  }
  expect(errors).toEqual([]);
});

test("queue → lead detail shows the score explanation", async ({ page }) => {
  const errors = trackErrors(page);
  await page.goto("/queue");
  const first = page.locator("main table tbody tr a[href^='/leads/']").first();
  await expect(first).toBeVisible();
  const name = (await first.textContent())?.trim() ?? "";
  await first.click();
  await expect(page).toHaveURL(/\/leads\/L-\d+/);
  await expect(page.locator("main h1").first()).toHaveText(name);
  await expect(page.getByText("Factor breakdown")).toBeVisible();
  await expect(page.getByText("Next best action")).toBeVisible();
  expect(errors).toEqual([]);
});

test("ingested event shows up on the lead", async ({ page, request }) => {
  const lead = (await (await request.get(`${API}/api/leads?limit=1&sort=score`)).json()).items[0];
  const res = await request.post(`${API}/api/events`, {
    data: { event_id: `e2e-${Date.now()}`, type: "page_view", lead_ref: { lead_id: lead.lead_id },
            payload: { url: "/pricing", page_category: "pricing" } },
  });
  expect((await res.json()).results[0].status).toBe("processed");
  await page.goto(`/leads/${lead.lead_id}`);
  await expect(page.getByText("Unified timeline")).toBeVisible();
  await expect(page.getByText(/pricing/i).first()).toBeVisible();
});

test("mobile width has no horizontal page scroll", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  for (const route of ["/queue", "/pipeline", "/accounts", "/analytics"]) {
    await page.goto(route);
    await expect(page.locator("main h1").first()).toBeVisible();
    await expect.poll(() => fitsWidth(page), { message: `${route} overflows on mobile` }).toBe(true);
  }
});
