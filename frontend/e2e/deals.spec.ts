import { expect, test, type APIRequestContext } from "@playwright/test";

// Accounts and deals, on the auth-off stack. Each run uses its own company domain so reruns never collide.
const API = "http://127.0.0.1:8010";
const RUN = Date.now().toString(36);

test.beforeAll(async ({ request }) => {
  await expect
    .poll(async () => (await (await request.get(`${API}/api/sim/status`)).json()).status, { timeout: 120_000 })
    .toBe("ready");
  await request.post(`${API}/api/sim/pause`);
});

async function newLead(request: APIRequestContext, name: string, email: string, title: string, company: string): Promise<string> {
  const r = await request.post(`${API}/api/events`, { data: { type: "lead_created", source: "website", payload: {
    name, email, title, company, country: "US", form_fill_seconds: 30 } } });
  const res = (await r.json()).results[0];
  expect(res.status).toBe("processed");
  return res.lead_id;
}

test("a demo request opens a deal that shows on the account, the deal page and the board", async ({ page, request }) => {
  const domain = `pilotdeals${RUN}.io`;
  const company = `Pilot Deals ${RUN}`;
  await newLead(request, "Cara Chief", `cara@${domain}`, "CEO", company);
  await newLead(request, "Dev Builder", `dev@${domain}`, "Software Engineer", company);
  const r = await request.post(`${API}/api/events`, { data: { type: "demo_request", lead_ref: { email: `dev@${domain}` } } });
  expect((await r.json()).results[0].status).toBe("processed");

  await page.goto(`/accounts?q=${domain}`);
  await expect(page.locator("main h1")).toHaveText("Accounts");
  await page.getByRole("link", { name: company, exact: true }).click();
  await expect(page.locator("main h1")).toHaveText(company);
  const committee = page.locator("section", { has: page.getByRole("heading", { name: "Buying committee" }) });
  await expect(committee.getByText("Cara Chief")).toBeVisible();                       // CEO → decision maker
  await expect(committee.getByText("Dev Builder")).toBeVisible();                      // engineer → user
  await expect(committee.getByText("Not involved yet")).toHaveCount(1);                // nobody in the manager role

  const deal = page.getByRole("link", { name: new RegExp(`^${company} · New business$`) });
  await expect(deal).toBeVisible();
  await deal.click();
  await expect(page).toHaveURL(/\/deals\/O-/);
  await expect(page.getByRole("heading", { name: "Stage history" })).toBeVisible();
  await expect(page.getByText("O1", { exact: true })).toBeVisible();                   // opened on a buying signal
  await expect(page.getByText("Opened on a buying signal")).toBeVisible();

  await page.goto("/pipeline");                                                        // deal board is the default
  await expect(page.getByRole("button", { name: "Deals" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("link", { name: new RegExp(company) }).first()).toBeVisible();
  await page.getByRole("button", { name: "Leads", exact: true }).click();
  await expect(page).toHaveURL(/view=leads/);
  await expect(page.locator('[data-stage="contacted"]')).toBeVisible();                 // lead stages only exist on this board
});

test("a rep creates a deal from a lead page, edits it and closes it as lost", async ({ page, request }) => {
  const domain = `pilotlost${RUN}.io`;
  const id = await newLead(request, "Lena Lost", `lena@${domain}`, "Head of Operations", `Pilot Lost ${RUN}`);

  await page.goto(`/leads/${id}`);
  const card = page.locator("section#deals");
  await expect(card.getByText(`Part of Pilot Lost ${RUN}`)).toBeVisible();
  await card.getByRole("button", { name: "New deal" }).click();
  await card.getByLabel("Deal name").fill(`Rollout ${RUN}`);
  await card.getByLabel("Amount ($)").fill("42000");
  await card.getByRole("button", { name: "Create deal" }).click();

  await expect(page).toHaveURL(/\/deals\/O-/);
  await expect(page.locator("main h1")).toHaveText(`Rollout ${RUN}`);
  await expect(page.getByText("$42.0k").first()).toBeVisible();
  await expect(page.getByText("O0", { exact: true })).toBeVisible();                   // created by a rep

  const edit = page.locator("section#edit");
  await edit.getByLabel("Expected close").fill("2026-12-15");
  await edit.getByRole("button", { name: "Save changes" }).click();
  await expect(edit.getByRole("status")).toHaveText("Saved");

  await edit.getByRole("button", { name: "Mark lost" }).click();
  await edit.getByLabel("Why was it lost?").fill("went with a competitor");
  await edit.getByRole("button", { name: "Save changes" }).click();
  await expect(page.locator("main section").first().getByText("Lost", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("O8", { exact: true })).toBeVisible();                   // deal lost
  await expect(edit.getByText("went with a competitor")).toBeVisible();

  const saved = await (await request.get(`${API}/api/opportunities?account_id=A-${domain}`)).json();
  const lost = saved.columns.find((c: { stage: string }) => c.stage === "lost").cards;
  expect(lost.map((d: { name: string; close_date: string; lost_reason: string }) => [d.name, d.close_date, d.lost_reason]))
    .toEqual([[`Rollout ${RUN}`, "2026-12-15", "went with a competitor"]]);
});
