import { createHmac } from "node:crypto";
import { expect, test, type Page } from "@playwright/test";
import { AUTH_API_PORT, AUTH_WEB_PORT, TEST_JWT_SECRET, TEST_SUPABASE_URL } from "../playwright.config";

// Runs against the auth-on stack. A browser session is injected exactly as supabase-js stores one, holding a
// token signed with the test-only secret, so no real Supabase project or account is involved.
const API = `http://127.0.0.1:${AUTH_API_PORT}`;
const STORAGE_KEY = `sb-${new URL(TEST_SUPABASE_URL).hostname.split(".")[0]}-auth-token`;
// Fixed ids: Playwright reloads this file in a fresh worker after a failure, and new ids would add a second
// profile for the same email on the still-running server.
const USERS = {
  admin: { id: "00000000-0000-4000-8000-00000000e2a1", email: "admin@e2e.test" },
  rep: { id: "00000000-0000-4000-8000-00000000e2a2", email: "rep@e2e.test" },
  newbie: { id: "00000000-0000-4000-8000-00000000e2a3", email: "new@e2e.test" },
};
type Who = keyof typeof USERS;

test.use({ baseURL: `http://127.0.0.1:${AUTH_WEB_PORT}` });

const b64 = (o: object) => Buffer.from(JSON.stringify(o)).toString("base64url");
function token(who: Who): string {
  const now = Math.floor(Date.now() / 1000);
  const body = b64({ sub: USERS[who].id, email: USERS[who].email, aud: "authenticated", role: "authenticated",
                     iss: `${TEST_SUPABASE_URL}/auth/v1`, iat: now, exp: now + 3600 });
  const head = b64({ alg: "HS256", typ: "JWT" });
  const sig = createHmac("sha256", TEST_JWT_SECRET).update(`${head}.${body}`).digest("base64url");
  return `${head}.${body}.${sig}`;
}
const auth = (who: Who) => ({ Authorization: `Bearer ${token(who)}` });

async function signInAs(page: Page, who: Who) {
  const access = token(who);
  const exp = Math.floor(Date.now() / 1000) + 3600;
  const session = { access_token: access, token_type: "bearer", expires_in: 3600, expires_at: exp,
                    refresh_token: "e2e-refresh", user: { id: USERS[who].id, email: USERS[who].email, aud: "authenticated",
                    role: "authenticated", app_metadata: {}, user_metadata: {}, created_at: new Date().toISOString() } };
  await page.addInitScript(([key, value]) => localStorage.setItem(key, value), [STORAGE_KEY, JSON.stringify(session)]);
}

test.beforeAll(async ({ request }) => {
  await expect.poll(async () => (await (await request.get(`${API}/api/health`)).json()).status, { timeout: 120_000 }).toBe("ready");
  for (const who of Object.keys(USERS) as Who[]) {                     // first sign-in creates each profile
    expect((await request.get(`${API}/api/me`, { headers: auth(who) })).ok()).toBe(true);
  }
  const r = await request.patch(`${API}/api/admin/users/${USERS.rep.id}`, { headers: auth("admin"), data: { role: "rep", rep_id: "R-ANANYA" } });
  expect(r.ok()).toBe(true);
  await request.post(`${API}/api/sim/pause`, { headers: auth("admin") });
});

test("signed-out visitors get the login screen and no data", async ({ page }) => {
  const apiCalls: string[] = [];
  const PUBLIC = ["/api/auth/config", "/api/health"];                     // no lead data in either
  page.on("request", (r) => { if (r.url().includes("/api/") && !PUBLIC.some((p) => r.url().includes(p))) apiCalls.push(r.url()); });
  await page.goto("/queue");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expect(page.getByLabel("Work email")).toBeVisible();
  await page.getByRole("tab", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Create account" })).toBeVisible();
  await expect(page.getByLabel("Full name")).toBeVisible();
  expect(apiCalls).toEqual([]);
});

test("a pending account waits for approval", async ({ page }) => {
  await signInAs(page, "newbie");
  await page.goto("/queue");
  await expect(page.getByRole("heading", { name: "Waiting for access" })).toBeVisible();
  await expect(page.getByText("new@e2e.test")).toBeVisible();
});

test("a rep sees only their own work and no manager pages", async ({ page }) => {
  await signInAs(page, "rep");
  await page.goto("/queue");
  await expect(page.locator("main h1")).toHaveText("Ananya's queue");
  await expect(page.getByText("Ananya Rao").first()).toBeVisible();          // header chip shows their rep
  const nav = page.locator("aside nav");
  for (const hidden of ["Analytics", "Quality", "Simulator", "Access"]) await expect(nav.getByText(hidden)).toHaveCount(0);
  await expect(page.locator("main select")).toHaveCount(0);                  // no rep picker for reps
  const rows = page.locator("main table tbody tr");
  await expect(rows.first()).toBeVisible();
  await page.goto("/analytics");
  await expect(page).toHaveURL(/\/queue$/);
  const mine = (await (await page.request.get(`${API}/api/leads?limit=500`, { headers: auth("rep") })).json()).items;
  expect(mine.every((l: { owner_rep_id: string }) => l.owner_rep_id === "R-ANANYA")).toBe(true);
});

test("an admin approves people and issues an API key shown once", async ({ page }) => {
  await signInAs(page, "admin");
  await page.goto("/access");
  await expect(page.locator("main h1")).toHaveText("Access");
  await expect(page.getByText("new@e2e.test")).toBeVisible();
  await page.getByLabel("Role for new@e2e.test").selectOption("manager");
  await expect(page.getByText("All reps").first()).toBeVisible();          // manager → team picker appears
  await page.getByPlaceholder("e.g. Website forms").fill("E2E website");
  await page.getByRole("button", { name: "Create key" }).click();
  const secret = await page.locator("code").filter({ hasText: /^lp_/ }).first().textContent();
  expect(secret).toMatch(/^lp_/);
  const res = await page.request.post(`${API}/api/events`, { headers: { "X-API-Key": secret! },
    data: { type: "page_view", lead_ref: { email: "nobody@e2e.test" }, payload: { page_category: "pricing" } } });
  expect(res.ok()).toBe(true);
  await page.getByRole("button", { name: "Done" }).click();
  await expect(page.getByText(secret!, { exact: true })).toHaveCount(0);           // full key never shown again
  await expect(page.getByRole("cell", { name: /E2E website/ })).toBeVisible();
});
