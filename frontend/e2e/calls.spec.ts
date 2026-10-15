import { expect, test } from "@playwright/test";

// Calls on the auth-off stack, which has no Gemini key: analysis falls back to the phone system or rules.
const API = "http://127.0.0.1:8010";
const RUN = Date.now().toString(36);

test.beforeAll(async ({ request }) => {
  await expect
    .poll(async () => (await (await request.get(`${API}/api/sim/status`)).json()).status, { timeout: 120_000 })
    .toBe("ready");
  await request.post(`${API}/api/sim/pause`);
});

test("a rep logs a call, and a phone-system call for an unknown number is linked from the Calls page", async ({ page, request }) => {
  const r = (await (await request.post(`${API}/api/events`, { data: { type: "lead_created", source: "website", payload: {
    name: "Carla Caller", email: `carla@calls${RUN}.io`, title: "VP Sales", company: `Calls ${RUN}`, country: "US", form_fill_seconds: 30 } } })).json()).results[0];
  const lid: string = r.lead_id;

  await page.goto(`/leads/${lid}`);
  const card = page.locator("section#calls");
  await expect(card.getByText("Gemini is not set up")).toBeVisible();
  await card.getByRole("button", { name: "Log a call" }).click();
  await card.getByLabel("What was said").fill("Customer: What is the pricing for 20 seats? We want to decide this quarter.");
  await card.getByLabel("How it went").selectOption("connected");
  await card.getByLabel("Minutes").fill("7");
  await card.getByRole("button", { name: "Save call" }).click();
  const call = card.getByRole("article").first();
  await expect(call.getByText("Connected")).toBeVisible();
  await expect(call.getByText(/^Customer: What is the pricing/)).toBeVisible();               // the notes are the summary
  await expect(call.getByText("Interested", { exact: true })).toBeVisible();
  await expect(call.getByText(/Analysed by rules/)).toBeVisible();
  await call.getByRole("button", { name: "Notes" }).click();
  await expect(call.locator("pre")).toContainText("pricing for 20 seats");

  const con = await (await request.post(`${API}/api/connectors`, { data: { kind: "call", name: `Phones ${RUN}` } })).json();
  await request.patch(`${API}/api/connectors/${con.id}`, { data: { settings: { provider: "generic" } } });
  const hook = await request.post(`${API}/api/hooks/${con.id}?token=${con.secret}`, { data: {
    call_id: `gen-${RUN}`, direction: "inbound", from: "+14155550142", duration_s: 95,
    transcript: "Agent: Hello\nCustomer: Can you send me a quote?", outcome: "connected" } });
  expect((await hook.json()).status).toBe("accepted");

  await page.goto("/calls");
  await expect(page.locator("main h1")).toHaveText("Calls");
  await page.getByRole("button", { name: "Needs a lead", exact: true }).click();
  const row = page.getByRole("button", { name: /\+14155550142/ });
  await expect(row).toBeVisible();
  await row.click();
  await page.getByPlaceholder("L-…").fill(lid);
  await page.getByRole("button", { name: "Link and analyse" }).click();
  await expect(page.getByText("Nothing here.")).toBeVisible();

  await page.goto(`/leads/${lid}`);
  await expect(page.locator("section#calls").getByRole("article")).toHaveCount(2);
  await expect(page.locator("section#calls").getByText("They called")).toBeVisible();
});
