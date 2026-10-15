import { expect, test } from "@playwright/test";

// Quotes on the auth-off stack (the dev user is an admin, so it can also approve discounts).
const API = "http://127.0.0.1:8010";
const RUN = Date.now().toString(36);

test.beforeAll(async ({ request }) => {
  await expect
    .poll(async () => (await (await request.get(`${API}/api/sim/status`)).json()).status, { timeout: 120_000 })
    .toBe("ready");
  await request.post(`${API}/api/sim/pause`);
});

test("a rep builds a discounted quote, a manager approves it, and the buyer accepts it from the link", async ({ page, browser, request }) => {
  const r = (await (await request.post(`${API}/api/events`, { data: { type: "lead_created", source: "website", payload: {
    name: "Quinn Quote", email: `quinn@quotes${RUN}.io`, title: "CFO", company: `Quotes ${RUN}`, country: "US", form_fill_seconds: 30 } } })).json()).results[0];
  const deal = await (await request.post(`${API}/api/opportunities`, { data: { lead_id: r.lead_id, name: `Quotes ${RUN} rollout` } })).json();

  await page.goto(`/deals/${deal.opp_id}`);
  const card = page.locator("section#quotes");
  await expect(card.getByText("No quotes yet.")).toBeVisible();
  await card.getByRole("button", { name: "New quote" }).click();
  const editor = card.getByRole("form", { name: "Quote editor" });
  await editor.getByLabel("Add from catalog").selectOption("LP-PRO");
  await editor.getByLabel("Add from catalog").selectOption("LP-ONBOARD");
  await editor.getByLabel("Line 1").getByLabel("Quantity").fill("20");
  await expect(editor.getByLabel("Quote total")).toHaveText("$29,000.00");
  await editor.getByLabel("Quote discount %").fill("20");
  await expect(editor.getByLabel("Quote total")).toHaveText("$23,200.00");
  await expect(editor.getByText(/above 15%: a manager approves/)).toBeVisible();
  await editor.getByRole("button", { name: "Save draft" }).click();

  const quote = card.getByRole("article").first();
  await expect(quote.getByText("Needs approval")).toBeVisible();
  await expect(quote.getByText("$23,200.00").first()).toBeVisible();
  await quote.getByRole("button", { name: "Approve discount" }).click();
  await expect(quote.getByText(/discount approved by/)).toBeVisible();
  await quote.getByRole("button", { name: "Mark as sent" }).click();
  await expect(quote.getByRole("button", { name: /Sent \$23,200\.00$/ })).toBeVisible();        // the status tag has a glyph
  await expect(page.getByRole("list", { name: "Deal stages" }).locator("[aria-current=step]")).toContainText("proposal");
  await expect(page.getByText(/from quote Q-/)).toBeVisible();

  const detail = await (await request.get(`${API}/api/opportunities/${deal.opp_id}`)).json();
  const link: string = detail.quotes[0].link;
  const buyer = await (await browser.newContext({ baseURL: "http://127.0.0.1:5180", viewport: { width: 390, height: 844 } })).newPage();   // a phone
  await buyer.goto(link);
  await expect(buyer.getByRole("heading", { level: 1 })).toHaveText(`Quotes ${RUN} rollout quote`);
  await expect(buyer.getByRole("list").getByText("LeadPilot Pro")).toBeVisible();          // phones get a list, not the table
  expect(await buyer.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await buyer.getByRole("button", { name: /Accept quote/ }).click();
  await buyer.getByLabel("Your full name").fill("Quinn Quote");
  await buyer.getByRole("button", { name: "Accept and sign" }).click();
  await expect(buyer.getByRole("status")).toContainText("Accepted");
  await expect(buyer.getByRole("button", { name: /Accept quote/ })).toHaveCount(0);

  await page.reload();
  await expect(page.locator("section#quotes").getByRole("button", { name: /Accepted \$23,200\.00$/ })).toBeVisible();
  await expect(page.getByText("Won", { exact: true }).first()).toBeVisible();
  const after = await (await request.get(`${API}/api/opportunities/${deal.opp_id}`)).json();
  expect([after.status, after.amount, after.quotes[0].views]).toEqual(["won", 23200, 1]);

  await buyer.goto("/q/not-a-real-token-at-all-000000");
  await expect(buyer.getByText("Quote not found")).toBeVisible();
});
