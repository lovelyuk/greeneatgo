import { expect, test } from "@playwright/test";

test("invite acceptance creates the account on the server and never calls public signup", async ({ page }) => {
  let accept, signupCalled = false;
  await page.route("**/api-fixture/invites/tok-1", (route) => route.fulfill({ json: { ok: true, data: {
    id: "inv-1", role: "company_admin", email: "boss@example.invalid", status: "pending",
    expires_at: "2099-01-01T00:00:00+00:00" } } }));
  await page.route("**/api-fixture/invites/tok-1/accept", (route) => {
    accept = route.request().postDataJSON();
    return route.fulfill({ json: { ok: true, data: { email: "boss@example.invalid", invite_status: "accepted" } } });
  });
  await page.route("**/auth-fixture/auth/v1/signup**", (route) => { signupCalled = true; return route.abort(); });
  await page.route("**/auth-fixture/auth/v1/token**", (route) => route.fulfill({ json: {
    access_token: "a.b.c", token_type: "bearer", expires_in: 3600, expires_at: 4102444800, refresh_token: "r",
    user: { id: "u-1", email: "boss@example.invalid", aud: "authenticated", role: "authenticated" } } }));
  await page.route("**/api-fixture/me**", (route) => route.fulfill({ status: 401, json: { detail: { code: "x" } } }));
  await page.goto("/?invite=tok-1");
  await expect(page.getByLabel("이메일")).toHaveValue("boss@example.invalid");
  await page.getByLabel("비밀번호").fill("long-enough-pass");
  await page.getByLabel("이름").fill("대표");
  await page.getByRole("button", { name: "계정 만들고 초대 수락" }).click();
  await expect(page.getByText("가입과 초대 연결이 완료됐어요", { exact: false })).toBeVisible();
  expect(accept).toEqual({ password: "long-enough-pass", display_name: "대표", email: null });
  expect(signupCalled).toBe(false);
});
