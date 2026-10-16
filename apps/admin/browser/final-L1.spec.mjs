import { openRecovery } from './recovery-navigation.mjs';
// Real production UI with deterministic backend-contract I/O; no live payment.
import { test, expect } from "@playwright/test";
// Preserve legacy popup/point-only acceptance under explicit mobile UA.
test.use({ userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148' });
import { setup, submit, purchaseResponse } from "./final-L1-fixture.mjs";

async function expectPendingDiagnostic(page, diagnostic) {
 await openRecovery(page);
 await expect(page.getByRole('alert')).toBeVisible();
 const details=page.locator('details');
 await expect(details).toHaveCount(1);
 if (!(await details.getAttribute('open') !== null)) await details.locator('summary').click();
 await expect(details).toContainText(diagnostic);
 await details.locator('summary').click();
}

for (const actual of [40000, 50000]) {
  test(`FINAL-L1 issued point-only pricing discrepancy discloses actual ${actual} points without retry`, async ({ page, context }) => {
    const state = await setup(page, context, { gross: 42000, points: 42000 });
    await page.route("**/api-fixture/vouchers/purchase-subsidized", route => {
      state.bodies.push(route.request().postDataJSON());
      // 40000 is normal stale-price clamping; 50000 is an anomalous already-issued
      // response ignoring the bound request, not a claim that the backend does this.
      return route.fulfill({ json: { ok: true, data: purchaseResponse(actual, actual) } });
    });
    await submit(page, 50000);
    await expect(page.getByRole("heading", { name: "결제 완료" })).toBeVisible();
    await expect(page.getByText(`실제 사용 포인트 ${actual.toLocaleString("ko-KR")}P`)).toBeVisible();
    await expect(page.getByRole("alert")).toContainText("견적과 서버 확정 가격이 달라요");
    await expect(page.getByRole("alert")).toContainText("이미 발급");
    await expect(page.getByRole("alert")).toContainText("관리자");
    expect(state.bodies).toHaveLength(1);
    expect(state.bodies[0].requested_point_amount).toBe(42000);
    expect(state.confirm).toBe(0);
    expect(state.checkout).toBe(0);
    expect(context.pages()).toHaveLength(1);
    expect(state.errors).toEqual([]);
    await expect(page.getByRole("heading", { name: "주문 상태 확인 필요" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "다른 식권 구매" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "구매하기", exact: true })).toHaveCount(0);
  });
}

test("FINAL-L1 fulfillment points remain authoritative when response pricing disagrees", async ({ page, context }) => {
  const state = await setup(page, context, { gross: 42000, points: 42000 });
  await page.route("**/api-fixture/vouchers/purchase-subsidized", route => {
    state.bodies.push(route.request().postDataJSON());
    const result = purchaseResponse(42000, 42000);
    result.fulfillment.point_amount = 40000; // anomalous metadata; matching done order is authority
    return route.fulfill({ json: { ok: true, data: result } });
  });
  await submit(page, 50000);
  await expect(page.getByRole("heading", { name: "결제 완료" })).toBeVisible();
  await expect(page.getByText("실제 사용 포인트 40,000P")).toBeVisible();
  await expect(page.getByRole("alert")).toContainText("이미 발급");
  await expect(page.getByRole("heading", { name: "주문 상태 확인 필요" })).toHaveCount(0);
  expect(state.confirm).toBe(0);
  expect(state.bodies).toHaveLength(1);
});

test("FINAL-L1 stale balance becomes unpaid card order without opening checkout", async ({ page, context }) => {
  const state = await setup(page, context, { gross: 42000, points: 42000 });
  await page.route("**/api-fixture/vouchers/purchase-subsidized", route => {
    state.bodies.push(route.request().postDataJSON());
    return route.fulfill({ json: { ok: true, data: purchaseResponse(42000, state.bodies.at(-1).requested_point_amount, 10000) } });
  });
  await submit(page, 50000);
  await openRecovery(page);await expect(page.getByRole("heading", { name: /이전.*결과/ })).toBeVisible();
  await openRecovery(page);await page.getByText("상세 보기",{exact:true}).click();
  await expect(page.getByText("서버 주문 금액 32,000원")).toBeVisible();
  await expectPendingDiagnostic(page, "변경");
  expect(state.bodies[0].requested_point_amount).toBe(42000);
  expect(state.checkout).toBe(0);
  expect(state.confirm).toBe(0);
  expect(context.pages()).toHaveLength(1);
});

test("FINAL-L1 unchanged point-only completion shows actual debit without discrepancy", async ({ page, context }) => {
  const state = await setup(page, context, { gross: 42000, points: 42000 });
  await page.route("**/api-fixture/vouchers/purchase-subsidized", route => {
    state.bodies.push(route.request().postDataJSON());
    return route.fulfill({ json: { ok: true, data: purchaseResponse(42000, state.bodies.at(-1).requested_point_amount) } });
  });
  await submit(page, 50000);
  await expect(page.getByRole("heading", { name: "결제 완료" })).toBeVisible();
  await expect(page.getByText("실제 사용 포인트 42,000P")).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "다른 식권 구매" })).toBeVisible();
  expect(state.confirm).toBe(0);
});

for (const changed of ["gross-discount", "points-card"]) {
  test(`FINAL-L1 mixed-card ${changed} mismatch blocks unapproved checkout`, async ({ page, context }) => {
    const state = await setup(page, context, changed === "gross-discount" ? { gross: 43000, points: 2000, discount: 1000 } : { gross: 42000, points: 2000 });
    await page.route("**/api-fixture/vouchers/purchase-subsidized", route => {
      state.bodies.push(route.request().postDataJSON());
      // Both repricings keep the card amount 40000, exposing card-only comparison.
      const result = changed === "gross-discount" ? purchaseResponse(44000, 2000, 50000, 2000) : purchaseResponse(41000, 2000, 1000);
      return route.fulfill({ json: { ok: true, data: result } });
    });
    await submit(page, 2000);
    await openRecovery(page);await expect(page.getByRole("heading", { name: /이전.*결과/ })).toBeVisible();
    await expectPendingDiagnostic(page, "변경");
    expect(state.checkout).toBe(0);
    await expect.poll(() => context.pages().length).toBe(1);
    await openRecovery(page);await page.getByText("상세 보기",{exact:true}).click();
    await expect(page.getByRole("button", { name: "예약 취소 요청" })).toBeVisible();
    expect(state.errors).toEqual([]);
  });
}

test("FINAL-L1 clamps 50000 request to accepted 42000 before stale 50000 reprice", async ({ page, context }) => {
  const state = await setup(page, context, { gross: 42000, points: 42000 });
  await page.route("**/api-fixture/vouchers/purchase-subsidized", route => {
    state.bodies.push(route.request().postDataJSON());
    return route.fulfill({ json: { ok: true, data: purchaseResponse(50000, state.bodies.at(-1).requested_point_amount) } });
  });
  await submit(page, 50000);
  await expect.poll(() => state.bodies.length).toBe(1);
  expect(state.bodies[0].requested_point_amount).toBe(42000);
  await openRecovery(page);await expect(page.getByRole("heading", { name: /이전.*결과/ })).toBeVisible();
  await expectPendingDiagnostic(page, "변경");
  await openRecovery(page);await page.getByText("상세 보기",{exact:true}).click();
  await expect(page.getByText("서버 주문 금액 8,000원")).toBeVisible();
  expect(state.checkout).toBe(0);
  expect(context.pages()).toHaveLength(1);
  await expect(page.getByRole("button", { name: "구매하기", exact: true })).toHaveCount(0);
});
