
import { expect } from "@playwright/test";
const id = "11111111-1111-4111-8111-111111111111";
export function purchaseResponse(gross, requested, available = 50000, discount = 0) {
  // reserve_subsidized_order_points locks wallet and caps request to burden/balance.
  const points = Math.max(0, Math.min(requested, available, gross - discount));
  const amount = gross - discount - points;
  const order_id = "GE-S-final-L1";
  return { order_id, product_id: "package-fixture", product_name: "테스트 식권", total_count: 11,
    amount, gross_amount: gross, coupon_discount_amount: discount, point_amount: points,
    card_amount: amount, point_only: amount === 0,
    checkout_url: amount === 0 ? null : `http://127.0.0.1:4175/api-fixture/payments/checkout/${"a".repeat(43)}`,
    fulfillment: amount === 0 ? { order_id, status: "done", issued_count: 11, card_amount: 0, point_amount: points } : null };
}
export async function setup(page, context, quote) {
  const state = { bodies: [], checkout: 0, confirm: 0, errors: [] };
  page.on("pageerror", e => state.errors.push(e.message));
  await context.route("**/*", route => new URL(route.request().url()).origin === "http://127.0.0.1:4175" ? route.continue() : route.abort());
  const user = { id, email: "fixture@example.invalid", aud: "authenticated", role: "authenticated" };
  await page.route("**/auth-fixture/auth/v1/**", route => route.fulfill({ json: new URL(route.request().url()).pathname.endsWith("/user") ? user : { access_token: "fixture-access", refresh_token: "fixture-refresh", expires_in: 3600, token_type: "bearer", user } }));
  await page.route("**/terms.html", route => route.fulfill({ contentType: "text/html", body: "<h1>이용약관</h1><p>MOCK FIXTURE ONLY 시행일 2026.01.01 테스트 식당 사업자등록번호 000-00-00000 대표자 테스트 주소 테스트 연락처 fixture@example.invalid 결제대행 키움페이</p>" }));
  await page.route("**/privacy.html", route => route.fulfill({ contentType: "text/html", body: "<h1>개인정보 처리방침</h1><p>MOCK FIXTURE ONLY 개인정보 보호책임자 테스트 담당</p>" }));
  await page.route("**/api-fixture/**", route => {
    const path = new URL(route.request().url()).pathname.replace("/api-fixture", "");
    let data = {};
    if (path === "/me") data = { user_id: id, role: "employee", status: "active", company_id: "company-fixture", display_name: "테스트 구매자", point_balance: 50000, voucher_balance: 0, voucher_use_history: [], point_transactions: [], recent_transactions: [] };
    if (path === "/coupons") data = { merchant: { id: "merchant-fixture", name: "테스트 식당" }, items: quote.discount ? [{ id: "coupon-fixture", name: "테스트 할인", discount_type: "fixed", discount_value: quote.discount }] : [], issued: [] };
    if (path === "/vouchers/products") data = { purchase_mode: "subsidized", items: [{ id: "package-fixture", name: "테스트 식권", voucher_count: 10, bonus_count: 1, unit_price: 8000, sale_price: 72000, employee_pay_amount: 42000, kiwoom_pay_method: "TOTAL" }] };
    if (path === "/vouchers/quote") data = { merchant_id: "merchant-fixture", merchant_name: "테스트 식당", product_id: "package-fixture", purchase_mode: "subsidized", gross_amount: quote.gross, coupon_discount_amount: quote.discount || 0, point_amount: quote.points, payment_amount: quote.gross - (quote.discount || 0) - quote.points };
    if (path === "/payments/confirm") state.confirm++;
    return route.fulfill({ json: { ok: true, data } });
  });
  await context.route("**/api-fixture/payments/checkout/**", route => { state.checkout++; return route.fulfill({ contentType: "text/html", body: "MOCK CHECKOUT ONLY" }); });
  return state;
}
export async function submit(page, points) {
  await page.goto("/shop");
  await page.getByLabel("이메일", { exact: true }).fill("fixture@example.invalid");
  await page.getByLabel("비밀번호", { exact: true }).fill("mocked-password-only");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await page.getByRole("navigation").getByRole("button", { name: "구매", exact: true }).click();
  await page.getByRole("button", { name: "테스트 식권 선택" }).click();
  await page.getByLabel("사용 포인트").fill(String(points));
  if (await page.getByLabel("할인 쿠폰").locator('option[value="public:coupon-fixture"]').count())
    await page.getByLabel("할인 쿠폰").selectOption("public:coupon-fixture");
  await expect(page.locator('.purchase-quote')).toBeVisible();
  await page.getByLabel("구매 조건 확인").check();
  await page.getByRole("button", { name: "구매하기", exact: true }).click();
}
