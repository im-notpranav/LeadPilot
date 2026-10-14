import { expect, test, type APIRequestContext } from "@playwright/test";

// Settings console, on the auth-off stack. Changes a rule, activates it (every event is re-run), then rolls back,
// so the shared demo backend ends on the YAML defaults again for the specs that run after this one.
const API = "http://127.0.0.1:8010";
const REPLAY = 180_000;   // activation re-runs the whole event log

test.beforeAll(async ({ request }) => {
  await expect
    .poll(async () => (await (await request.get(`${API}/api/sim/status`)).json()).status, { timeout: 120_000 })
    .toBe("ready");
  await request.post(`${API}/api/sim/pause`);
});

const activeId = async (request: APIRequestContext): Promise<number> =>
  (await (await request.get(`${API}/api/config`)).json()).active.id;
const gradeA = async (request: APIRequestContext): Promise<number> =>
  (await (await request.get(`${API}/api/leads?grade=A&limit=1`)).json()).total;

test("an admin activates a rule change, sees grades move, then rolls back to the YAML rules", async ({ page, request }) => {
  test.setTimeout(2 * REPLAY + 60_000);
  const start = await activeId(request);
  const hotBefore = await gradeA(request);

  await page.goto("/settings");
  const inForce = page.locator("main section").first();
  await expect(page.locator("main h1")).toHaveText("Settings");
  await expect(inForce.getByText(`Version ${start} is in force`, { exact: true })).toBeVisible();
  await expect(inForce.getByText("same as the YAML files")).toBeVisible();

  // Scoring is the first section: lower the grade A threshold from 80 to 70.
  const editor = page.getByLabel("Scoring settings");
  const yaml = await editor.inputValue();
  expect(yaml).toContain("grades: {A: 80,");
  await editor.fill(yaml.replace("grades: {A: 80,", "grades: {A: 70,"));
  await expect(page.getByText("Edited, not saved")).toBeVisible();

  await page.getByRole("button", { name: "Check changes" }).click();
  await expect(page.getByText(/^Checks passed on [\d,]+ events\. 1 setting would change:$/)).toBeVisible({ timeout: 60_000 });
  const row = page.getByRole("row", { name: /grades\.A/ });
  await expect(row.getByRole("cell").nth(1)).toHaveText("80");
  await expect(row.getByRole("cell").nth(2)).toHaveText("70");

  await page.getByPlaceholder("e.g. Faster first touch for A leads").fill("e2e: A from 70");
  await page.getByRole("button", { name: "Save and activate" }).click();
  await expect(page.getByText(/^Version \d+ is in force: [\d,]+ events re-run in [\d.]+s\.$/)).toBeVisible({ timeout: REPLAY });
  const changed = await activeId(request);
  expect(changed).toBe(start + 1);
  await expect(inForce.getByText(`Version ${changed} is in force`, { exact: true })).toBeVisible();
  await expect(inForce.getByText("1 setting differs from the YAML files (scoring)")).toBeVisible();
  expect(await gradeA(request)).toBeGreaterThan(hotBefore);                        // more leads clear the lower bar

  // Roll back to the version that was in force before: it is saved as a new version with the YAML rules.
  const history = page.locator("section", { has: page.getByRole("heading", { name: "Version history" }) });
  const old = history.getByRole("row").filter({ has: page.getByRole("cell", { name: `v${start}`, exact: true }) });
  await expect(old.getByText("Retired")).toBeVisible();
  await old.getByRole("button", { name: "Roll back to this" }).click();
  await expect(history.getByText(`version ${start}'s rules (saved as a new version)`)).toBeVisible();
  await old.getByRole("button", { name: "Yes, roll back" }).click();
  await expect(page.getByText(`Version ${start + 2} is in force: `)).toBeVisible({ timeout: REPLAY });
  expect(await activeId(request)).toBe(start + 2);
  await expect(inForce.getByText(`Version ${start + 2} is in force`, { exact: true })).toBeVisible();
  await expect(inForce.getByText("same as the YAML files")).toBeVisible();
  await expect(history.getByText(`copy of v${start}`)).toBeVisible();
  expect(await gradeA(request)).toBe(hotBefore);                                   // the replay is exact
});

test("what if shows what a rule change would do without switching anything", async ({ page, request }) => {
  const start = await activeId(request);
  await page.goto("/settings");
  const editor = page.getByLabel("Scoring settings");
  const yaml = await editor.inputValue();
  await editor.fill(yaml.replace("grades: {A: 80,", "grades: {A: 60,"));
  await page.getByRole("button", { name: "What if?" }).first().click();

  const panel = page.locator("section#whatif");
  await expect(panel.getByRole("heading", { name: "What if" })).toBeVisible();
  await expect(panel.getByText(`Unsaved edits compared with version ${start} (in force)`)).toBeVisible();
  await expect(panel.getByText(/If these rules were in force, [\d,]+ leads? would change grade/)).toBeVisible({ timeout: REPLAY });
  await expect(panel.getByRole("button", { name: /^Grades \(\d+\)$/ })).toHaveAttribute("aria-pressed", "true");
  const lead = panel.locator("table a[href^='/leads/']").first();
  await expect(lead).toBeVisible();
  await expect(panel.getByText(/▲ \d+ up · ▼ 0 down/)).toBeVisible();
  expect(await activeId(request)).toBe(start);                                     // nothing was switched
  await lead.click();
  await expect(page).toHaveURL(/\/leads\/L-\d+/);
});
