import { expect, test, type APIRequestContext } from "@playwright/test";

// Notifications on the auth-off stack (everyone is an admin there, so "sent to me" means manager notifications).
const API = "http://127.0.0.1:8010";
const RUN = Date.now().toString(36);

test.beforeAll(async ({ request }) => {
  await expect
    .poll(async () => (await (await request.get(`${API}/api/sim/status`)).json()).status, { timeout: 120_000 })
    .toBe("ready");
  await request.post(`${API}/api/sim/pause`);
});

async function send(request: APIRequestContext, data: object) {
  const r = (await (await request.post(`${API}/api/events`, { data })).json()).results[0];
  expect(r.status).toBe("processed");
  return r;
}

test("a won deal reaches the bell, opens the deal and is marked read; reps' notifications show on the page", async ({ page, request }) => {
  const email = `wanda@notifywin${RUN}.io`;
  const company = `Notify Win ${RUN}`;
  await send(request, { type: "lead_created", source: "website", payload: { name: "Wanda Winner", email, title: "COO", company, country: "US", form_fill_seconds: 35 } });
  await send(request, { type: "demo_request", lead_ref: { email } });
  await send(request, { type: "deal_won", actor: "rep", rep_id: "R-ANANYA", lead_ref: { email }, payload: { amount: 48000 } });

  await page.goto("/queue");
  const bell = page.getByRole("button", { name: /^Notifications, \d+ unread$/ });
  await expect(bell).toBeVisible();
  await bell.click();
  const panel = page.getByRole("dialog", { name: "Notifications" });
  const won = panel.getByRole("button", { name: new RegExp(`Deal won: ${company}`) });
  await expect(won).toBeVisible();
  await won.click();
  await expect(page).toHaveURL(/\/deals\/O-/);

  await page.goto("/notifications");
  await expect(page.locator("main h1")).toHaveText("Notifications");
  const inbox = page.locator("section", { has: page.getByRole("heading", { name: /^Inbox/ }) });
  await expect(inbox.getByRole("button", { name: new RegExp(`Deal won: ${company}`) }).getByLabel("Unread")).toHaveCount(0);
  await inbox.getByRole("button", { name: "My reps' too" }).click();
  const assigned = inbox.getByRole("button", { name: /New lead for you: Wanda Winner|Hot lead for you: Wanda Winner/ });
  await expect(assigned).toBeVisible();
  await expect(assigned.getByText(/^For /)).toBeVisible();

  await expect(page.getByText("Sign-in is off on this server")).toBeVisible();
  const channels = page.locator("section", { has: page.getByRole("heading", { name: "Channels" }) });
  await expect(channels.getByText("Not set up")).toHaveCount(3);
  await expect(channels.getByText("RESEND_API_KEY")).toBeVisible();
  const rules = page.locator("section", { has: page.getByRole("heading", { name: "Rules" }) });
  await expect(rules.getByText("Hot lead")).toBeVisible();

  const markAll = inbox.getByRole("button", { name: "Mark all read" });
  if (await markAll.isVisible()) await markAll.click();                          // other runs may have left some
  await expect(page.getByRole("button", { name: "Notifications", exact: true })).toBeVisible();   // no unread count
});
