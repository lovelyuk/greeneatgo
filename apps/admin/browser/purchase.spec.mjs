// Deterministic mocked I/O ONLY. No real auth, merchant or Kiwoom calls.
import { test, expect } from "@playwright/test";
import { dirname, join } from "node:path";
const runtimeErrors = new WeakMap();
test.beforeEach(async ({ context, page }) => {
  const errors = [];
  runtimeErrors.set(page, errors);
  page.on("pageerror", error => errors.push(error.message));
  context.on("page", popup => popup.on("pageerror", error => errors.push(error.message)));
  // Every external request is blocked unless a specific mocked route overrides it.
  await context.route("**/*", (route) =>
    new URL(route.request().url()).origin === "http://127.0.0.1:4175"
      ? route.continue()
      : route.abort(),
  );
});
test.afterEach(async ({ page }) => {
  expect(runtimeErrors.get(page), "uncaught browser or checkout runtime errors").toEqual([]);
});
async function fixture(page, profile = { role: "customer", status: "active" }) {
  const calls = [];
  const user = {
    id: "11111111-1111-4111-8111-111111111111",
    email: "fixture@example.invalid",
    aud: "authenticated",
    role: "authenticated",
    email_confirmed_at: "2026-01-01T00:00:00Z",
  };
  await page.route("**/auth-fixture/auth/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/logout")) return route.fulfill({ status: 204 });
    await route.fulfill({
      json: path.endsWith("/user")
        ? user
        : {
            access_token: "fixture-access",
            refresh_token: "fixture-refresh",
            expires_in: 3600,
            token_type: "bearer",
            user,
          },
    });
  });
  await page.route("**/api-fixture/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(
      "/api-fixture",
      "",
    );
    calls.push({ path, body: route.request().postDataJSON() });
    let data = {};
    if (path === "/me")
      data = {
        user_id: user.id,
        display_name: "테스트 구매자",
        voucher_balance: 3,
        point_balance: 2000,
        account_type: profile.role === "employee" ? "ledger" : "voucher",
        voucher_use_history: [],
        point_transactions: [],
        recent_transactions: [],
        ...profile,
      };
    if (path === "/vouchers/products")
      data = { purchase_mode: "voucher", items: [] };
    if (path === "/coupons")
      data = {
        merchant: { id: "merchant-fixture", name: "테스트 식당" },
        items: [],
        issued: [],
      };
    await route.fulfill({ json: { ok: true, data } });
  });
  return calls;
}
async function publishedLegal(page) {
  await page.route("**/terms.html", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: "<h1>이용약관</h1><p>MOCK FIXTURE ONLY 시행일 2026.01.01 테스트 식당 사업자등록번호 000-00-00000 대표자 테스트 주소 테스트 연락처 fixture@example.invalid 결제대행 키움페이</p>",
    }),
  );
  await page.route("**/privacy.html", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: "<h1>개인정보 처리방침</h1><p>MOCK FIXTURE ONLY 개인정보 보호책임자 테스트 담당</p>",
    }),
  );
}
async function login(page, tab = "구매") {
  await page.goto("/shop");
  await page
    .getByLabel("이메일", { exact: true })
    .fill("fixture@example.invalid");
  await page
    .getByLabel("비밀번호", { exact: true })
    .fill("mocked-password-only");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  const nav = page.getByRole("navigation", { name: "구매자 탭" });
  if (await nav.waitFor({ state: "visible", timeout: 1000 }).then(() => true).catch(() => false))
    await nav.getByRole("button", { name: tab, exact: true }).click();
}
const product = {
  id: "package-fixture",
  name: "테스트 10+1 식권",
  voucher_count: 10,
  bonus_count: 1,
  total_count: 11,
  unit_price: 8000,
  discount_rate: 10,
  sale_price: 72000,
  kiwoom_pay_method: "TOTAL",
  is_event: true,
  event_end_at: "2026-12-31T00:00:00Z",
};
async function catalogFixture(page, mode = "voucher") {
  await page.route("**/api-fixture/vouchers/products", (route) =>
    route.fulfill({
      json: {
        ok: true,
        data: {
          purchase_mode: mode,
          items: [
            mode === "subsidized"
              ? {
                  ...product,
                  employee_pay_amount: 42000,
                  per_voucher_company_subsidy_amount: 2000,
                  per_voucher_restaurant_subsidy_amount: 1000,
                  total_company_subsidy_amount: 20000,
                  total_restaurant_subsidy_amount: 10000,
                }
              : product,
          ],
        },
      },
    }),
  );
  await page.route("**/api-fixture/coupons", (route) =>
    route.fulfill({
      json: {
        ok: true,
        data: {
          merchant: { id: "merchant-fixture", name: "테스트 식당" },
          items: [
            {
              id: "coupon-fixture",
              name: "테스트 할인",
              discount_type: "fixed",
              discount_value: 1000,
            },
          ],
          issued: [],
        },
      },
    }),
  );
}
async function quoteFixture(
  page,
  mode = "voucher",
  amount = 72000,
  pointAmount = 0,
  discount = 0,
) {
  await page.route("**/api-fixture/vouchers/quote", (route) =>
    route.fulfill({
      json: {
        ok: true,
        data: {
          merchant_id: "merchant-fixture",
          merchant_name: "테스트 식당",
          product_id: product.id,
          purchase_mode: mode,
          gross_amount: amount + pointAmount + discount,
          coupon_discount_amount: discount,
          point_amount: pointAmount,
          payment_amount: amount,
        },
      },
    }),
  );
}
async function selectQuote(page) {
  await login(page);
  await page.getByRole("button", { name: "테스트 10+1 식권 선택" }).click();
  await page.getByRole("button", { name: "견적 확인" }).click();
}
test("loaded empty purchaser catalog displays explicit empty state", async ({ page }) => {
  await fixture(page);
  await login(page);
  await expect(page.getByText("현재 판매 중인 식권 상품이 없어요.")).toBeVisible();
  await expect(page.getByText("상품 확인 중…")).toHaveCount(0);
});
test("failed catalog read shows recoverable error instead of indefinite loading", async ({ page }) => {
  await fixture(page);
  await page.route("**/api-fixture/vouchers/products", route => route.fulfill({ status: 503, json: { detail: { code: "UNAVAILABLE", message: "fixture catalog unavailable" } } }));
  await login(page);
  await expect(page.getByRole("alert")).toContainText("fixture catalog unavailable");
  await expect(page.getByText("상품 확인 중…")).toHaveCount(0);
  await page.getByRole("navigation").getByRole("button", { name: "홈", exact: true }).click();
  await expect(page.getByRole("button", { name: "새로고침", exact: true })).toBeEnabled();
});
test('admin route retains its login and does not load purchaser bundle until shop navigation', async ({ page }) => {
  await fixture(page); const purchaserRequests = []; page.on('request', request => { if (/\/assets\/PurchaseApp-[^/]+\.js$/.test(new URL(request.url()).pathname)) purchaserRequests.push(request.url()); });
  await page.goto('/'); await expect(page.getByRole('heading', { name: '관리자 로그인' })).toBeVisible(); expect(purchaserRequests).toHaveLength(0);
  await page.goto('/shop'); await expect(page.getByRole('heading', { name: '식권 구매' })).toBeVisible(); expect(purchaserRequests).toHaveLength(1);
});
test("mixed employee issued-coupon purchase follows API form and remains pending on confirm error until server approves", async ({
  page,
  context,
}) => {
  await fixture(page, {
    role: "employee",
    status: "active",
    company_id: "company-fixture",
  });
  await publishedLegal(page);
  await catalogFixture(page, "subsidized");
  await quoteFixture(page, "subsidized", 39000, 2000, 1000);
  await page.route("**/api-fixture/coupons", (route) =>
    route.fulfill({
      json: {
        ok: true,
        data: {
          merchant: { id: "merchant-fixture", name: "테스트 식당" },
          items: [],
          issued: [
            {
              id: "issued-fixture",
              coupon_id: "coupon-fixture",
              coupon_snapshot: { name: "테스트 보유쿠폰" },
              valid_until: "2026-12-31T00:00:00Z",
              status: "available",
            },
          ],
        },
      },
    }),
  );
  let purchased,
    confirmed,
    checkoutEntered = 0;
  const token = "m".repeat(43);
  await page.route(
    "**/api-fixture/vouchers/purchase-subsidized",
    async (route) => {
      purchased = route.request().postDataJSON();
      await route.fulfill({
        json: {
          ok: true,
          data: {
            order_id: "GE-S-mixed-fixture",
            product_id: product.id,
            amount: 39000,
            gross_amount: 42000,
            coupon_discount_amount: 1000,
            point_amount: 2000,
            checkout_url: `http://127.0.0.1:4175/api-fixture/payments/checkout/${token}`,
          },
        },
      });
    },
  );
  await context.route(`**/api-fixture/payments/checkout/${token}`, (route) => {
    checkoutEntered++;
    return route.fulfill({
      contentType: "text/html",
      body: "<h1>MOCK SERVER CHECKOUT ONLY</h1>",
    });
  });
  await page.route("**/api-fixture/payments/confirm", (route) =>
    route.fulfill({
      status: 502,
      json: {
        detail: {
          code: "SUPABASE_ERROR",
          message: "MOCK ONLY confirm failure",
        },
      },
    }),
  );
  await login(page);
  await page.getByRole("button", { name: "테스트 10+1 식권 선택" }).click();
  await page.getByLabel("사용 포인트").fill("2000");
  await page.getByLabel("할인 쿠폰").selectOption("issued:issued-fixture");
  await page.getByRole("button", { name: "견적 확인" }).click();
  await page.getByLabel("구매 조건 확인").check();
  await page.getByRole("button", { name: "구매하기", exact: true }).click();
  await expect.poll(() => checkoutEntered).toBe(1);
  expect(purchased).toEqual({
    product_id: product.id,
    requested_point_amount: 2000,
    user_coupon_id: "issued-fixture",
  });
  await expect(
    page.getByRole("button", { name: "예약 취소 요청" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "승인 상태 확인" }).click();
  await expect(page.getByRole("alert")).toContainText("confirm failure");
  await expect(page.getByRole("heading", { name: "결제 완료" })).toHaveCount(0);
  await page.route("**/api-fixture/payments/confirm", async (route) => {
    confirmed = route.request().postDataJSON();
    await route.fulfill({
      json: {
        ok: true,
        data: {
          order_id: "GE-S-mixed-fixture",
          amount: 39000,
          status: "done",
          issued_count: 11,
          payment: { method: "CARD" },
          receipts: {},
        },
      },
    });
  });
  await page.getByRole("button", { name: "승인 상태 확인" }).click();
  await expect(page.getByRole("heading", { name: "결제 완료" })).toBeVisible();
  expect(confirmed).toEqual({ order_id: "GE-S-mixed-fixture", amount: 39000 });
});
test("cancel refusal preserves pending authority and cannot mark canceled", async ({
  page,
}) => {
  await fixture(page, {
    role: "employee",
    status: "active",
    company_id: "company-fixture",
  });
  await publishedLegal(page);
  await catalogFixture(page, "subsidized");
  await page.addInitScript(() =>
    sessionStorage.setItem(
      "greeneat-purchase-pending:11111111-1111-4111-8111-111111111111",
      JSON.stringify({
        order_id: "GE-S-refused-fixture",
        amount: 40000,
        mode: "subsidized",
        checkout_started: false,
      }),
    ),
  );
  await page.route(
    "**/api-fixture/vouchers/subsidized-orders/GE-S-refused-fixture/cancel",
    (route) =>
      route.fulfill({
        status: 409,
        json: {
          detail: {
            code: "CHECKOUT_ALREADY_STARTED",
            message: "MOCK ONLY checkout already started",
          },
        },
      }),
  );
  await login(page);
  await page.getByRole("button", { name: "예약 취소 요청" }).click();
  await expect(page.getByRole("alert")).toContainText("already started");
  await expect(
    page.getByRole("heading", { name: "결제 취소 확인" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "진행 중인 결제" }),
  ).toBeVisible();
});
test("logout during quote response prevents stale quote and purchaser UI from returning", async ({
  page,
}) => {
  await fixture(page);
  await publishedLegal(page);
  await catalogFixture(page);
  let release, requested;
  const started = new Promise((resolve) => {
    requested = resolve;
  });
  const barrier = new Promise((resolve) => {
    release = resolve;
  });
  await page.route("**/api-fixture/vouchers/quote", async (route) => {
    requested();
    await barrier;
    await route.fulfill({
      json: {
        ok: true,
        data: {
          merchant_id: "merchant-fixture",
          merchant_name: "테스트 식당",
          product_id: product.id,
          purchase_mode: "voucher",
          gross_amount: 72000,
          coupon_discount_amount: 0,
          point_amount: 0,
          payment_amount: 72000,
        },
      },
    });
  });
  await selectQuote(page);
  await started;
  await page.getByRole("navigation").getByRole("button", { name: "내정보", exact: true }).click();
  await page.getByRole("button", { name: "로그아웃", exact: true }).click();
  release();
  await expect(
    page.getByRole("button", { name: "로그인", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("최종 결제 72,000원")).toHaveCount(0);
});
test("rejected employee may convert only via customer registration endpoint", async ({
  page,
}) => {
  const profile = { role: "employee", status: "rejected" };
  const calls = await fixture(page, profile);
  await publishedLegal(page);
  await page.route("**/api-fixture/consumer/register", async (route) => {
    calls.push({
      path: "/consumer/register",
      body: route.request().postDataJSON(),
    });
    Object.assign(profile, { role: "customer", status: "active" });
    await route.fulfill({ json: { ok: true, data: profile } });
  });
  await login(page);
  await page.getByLabel("이름", { exact: true }).fill("전환 고객");
  await page.getByLabel("휴대폰 번호").fill("01012345678");
  await page.getByLabel("약관 및 개인정보 처리방침 확인").check();
  await page.getByRole("button", { name: "일반 구매자로 등록" }).click();
  await expect(page.getByRole("region", { name: "내 지갑" })).toBeVisible();
  expect(calls.filter((c) => c.path === "/consumer/register")).toHaveLength(1);
});
test("negative employee points are rejected before quote API", async ({
  page,
}) => {
  const calls = await fixture(page, {
    role: "employee",
    status: "active",
    company_id: "company-fixture",
  });
  await catalogFixture(page, "subsidized");
  await login(page);
  await page.getByRole("button", { name: "테스트 10+1 식권 선택" }).click();
  await page.getByLabel("사용 포인트").fill("-1");
  await page.getByRole("button", { name: "견적 확인" }).click();
  await expect(page.getByRole("alert")).toContainText("0 이상의 정수");
  expect(calls.some((c) => c.path === "/vouchers/quote")).toBe(false);
});
test("desktop and mobile purchaser browser screenshots have no overflow or oversized checkbox", async ({
  page,
}, testInfo) => {
  await fixture(page);
  await publishedLegal(page);
  await catalogFixture(page);
  await quoteFixture(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await selectQuote(page);
  const out = dirname(testInfo.project.outputDir);
  await page.screenshot({
    path: join(out, "purchaser-desktop-mocked.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: join(out, "purchaser-mobile-mocked.png"),
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  const box = await page.getByLabel("구매 조건 확인").boundingBox();
  expect(box.width).toBeLessThanOrEqual(28);
});
test("logout during order response never opens provider or applies old account result", async ({
  page,
  context,
}) => {
  await fixture(page);
  await publishedLegal(page);
  await catalogFixture(page);
  await quoteFixture(page);
  let release,
    requested,
    providerRequests = 0;
  const started = new Promise((resolve) => {
    requested = resolve;
  });
  const barrier = new Promise((resolve) => {
    release = resolve;
  });
  await page.route("**/api-fixture/vouchers/purchase", async (route) => {
    requested();
    await barrier;
    await route.fulfill({
      json: {
        ok: true,
        data: {
          order_id: "GE-V-stale-fixture",
          product_id: product.id,
          amount: 72000,
          checkout_url: `http://127.0.0.1:4175/api-fixture/payments/checkout/${"a".repeat(43)}`,
        },
      },
    });
  });
  await context.route("**/api-fixture/payments/checkout/**", (route) => {
    providerRequests++;
    return route.fulfill({ body: "MOCK ONLY" });
  });
  await selectQuote(page);
  await page.getByLabel("구매 조건 확인").check();
  await page.getByRole("button", { name: "구매하기", exact: true }).click();
  await started;
  await page.getByRole("navigation").getByRole("button", { name: "내정보", exact: true }).click();
  await page.getByRole("button", { name: "로그아웃", exact: true }).click();
  release();
  await expect(
    page.getByRole("button", { name: "로그인", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "진행 중인 결제" }),
  ).toHaveCount(0);
  await expect.poll(() => context.pages().length).toBe(1);
  expect(providerRequests).toBe(0);
});
test("duplicate submit and refresh cannot create a second order and pending survives reload", async ({
  page,
}) => {
  await fixture(page);
  await publishedLegal(page);
  await catalogFixture(page);
  await quoteFixture(page);
  let purchases = 0;
  await page.route("**/api-fixture/vouchers/purchase", async (route) => {
    purchases++;
    await route.fulfill({
      json: {
        ok: true,
        data: {
          order_id: "GE-V-recover-fixture",
          product_id: product.id,
          amount: 72000,
          checkout_url: "https://evil.invalid/form",
        },
      },
    });
  });
  await selectQuote(page);
  await page.getByLabel("구매 조건 확인").check();
  await page
    .getByRole("button", { name: "구매하기", exact: true })
    .evaluate((button) => {
      button.click();
      button.click();
    });
  await expect(
    page.getByRole("heading", { name: "진행 중인 결제" }),
  ).toBeVisible();
  expect(purchases).toBe(1);
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "진행 중인 결제" }),
  ).toBeVisible();
  await expect(page.getByText("주문 GE-V-recover-fixture")).toBeVisible();
  expect(purchases).toBe(1);
});
test("ambiguous order network error blocks automatic retry and survives reload", async ({
  page,
}) => {
  await fixture(page);
  await publishedLegal(page);
  await catalogFixture(page);
  await quoteFixture(page);
  let purchases = 0;
  await page.route("**/api-fixture/vouchers/purchase", (route) => {
    purchases++;
    return route.abort("failed");
  });
  await selectQuote(page);
  await page.getByLabel("구매 조건 확인").check();
  await page.getByRole("button", { name: "구매하기", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "주문 상태 확인 필요" }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "주문 상태 확인 필요" }),
  ).toBeVisible();
  expect(purchases).toBe(1);
});
test("actual published legal pages allow purchase despite unresolved disclosure", async ({
  page,
}) => {
  const calls = await fixture(page);
  await catalogFixture(page);
  await quoteFixture(page);
  await selectQuote(page);
  await page.getByLabel("구매 조건 확인").check();
  await expect(
    page.getByRole("button", { name: "구매하기", exact: true }),
  ).toBeEnabled();
  await expect(page.getByText("가입·구매를 진행할 수 없어요.", { exact: false })).toHaveCount(0);
  expect(calls.some((c) => c.path.includes("/purchase"))).toBe(false);
});
test("unavailable privacy document still disables purchase", async ({ page }) => {
  const calls = await fixture(page);
  await page.route("**/privacy.html", route => route.fulfill({ status: 503, body: "" }));
  await catalogFixture(page);
  await quoteFixture(page);
  await selectQuote(page);
  await page.getByLabel("구매 조건 확인").check();
  await expect(page.getByRole("button", { name: "구매하기", exact: true })).toBeDisabled();
  await expect(page.getByRole("alert")).toContainText("불러오지 못했어요");
  expect(calls.some(c => c.path.includes("/purchase"))).toBe(false);
});
test("published terms need not contain the selected merchant to allow purchase", async ({
  page,
}) => {
  await fixture(page);
  await publishedLegal(page);
  await page.route("**/terms.html", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: "<h1>이용약관</h1><p>MOCK ONLY 시행일 2026.01.01 운영자와 사용자 계약 내용</p>",
    }),
  );
  await catalogFixture(page);
  await quoteFixture(page);
  await selectQuote(page);
  await page.getByLabel("구매 조건 확인").check();
  await expect(
    page.getByRole("button", { name: "구매하기", exact: true }),
  ).toBeEnabled();
});
for (const status of ["pending", "suspended", "inactive"])
  test(`employee ${status} is read-only and never loads purchaser catalog`, async ({
    page,
  }) => {
    const calls = await fixture(page, { role: "employee", status });
    await login(page);
    await expect(page.getByRole("alert")).toContainText(status);
    expect(calls.some((c) => c.path === "/vouchers/products")).toBe(false);
  });
test("auth rejection displays provider error without rendering wallet", async ({
  page,
}) => {
  await fixture(page);
  await page.route("**/auth-fixture/auth/v1/token**", (route) =>
    route.fulfill({
      status: 400,
      json: {
        error: "invalid_grant",
        error_description: "MOCK ONLY invalid credentials",
      },
    }),
  );
  await login(page);
  await expect(page.getByRole("alert")).toContainText("invalid credentials");
  await expect(page.getByRole("region", { name: "내 지갑" })).toHaveCount(0);
});
test("none purchase mode hides selectable packages for active noneligible employee", async ({
  page,
}) => {
  await fixture(page, {
    role: "employee",
    status: "active",
    company_id: "company-fixture",
  });
  await catalogFixture(page, "none");
  await login(page);
  await expect(
    page.getByText(
      "현재 구매 가능한 식권이 없어요. 회사 계약 및 계정 상태를 확인해 주세요.",
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "테스트 10+1 식권 선택" }),
  ).toHaveCount(0);
});
test("malformed quote amount blocks purchase and never displays a payable quote", async ({
  page,
}) => {
  await fixture(page);
  await publishedLegal(page);
  await catalogFixture(page);
  await quoteFixture(page, "voucher", -1);
  await selectQuote(page);
  await expect(page.getByRole("alert")).toContainText("견적 금액");
  await expect(
    page.getByRole("button", { name: "구매하기", exact: true }),
  ).toHaveCount(0);
});
test("card approval renders only authoritative receipt links and keeps malformed confirm pending", async ({
  page,
}) => {
  await fixture(page);
  await publishedLegal(page);
  await catalogFixture(page);
  await quoteFixture(page);
  let count = 0;
  await page.addInitScript(() =>
    sessionStorage.setItem(
      "greeneat-purchase-pending:11111111-1111-4111-8111-111111111111",
      JSON.stringify({
        order_id: "GE-V-receipt-fixture",
        amount: 72000,
        mode: "voucher",
        checkout_started: true,
      }),
    ),
  );
  await page.route("**/api-fixture/payments/confirm", async (route) => {
    count++;
    await route.fulfill({
      json: {
        ok: true,
        data: {
          order_id: count === 1 ? "wrong-order" : "GE-V-receipt-fixture",
          status: "done",
          amount: 72000,
          product_name: product.name,
          merchant_name: "테스트 식당",
          issued_count: 11,
          payment: {
            method: "CARD",
            method_label: "카드",
            approved_at: "2026-01-01T00:00:00Z",
          },
          receipts: {
            sales_slip_url:
              "https://agenttest.kiwoompay.co.kr/common/PayInfoPrintDirectCard.jsp?DAOUTRX=fixture&STATUS=A",
            cash_receipt_url: "https://evil.invalid/receipt",
          },
        },
      },
    });
  });
  await login(page);
  await page.getByRole("button", { name: "승인 상태 확인" }).click();
  await expect(page.getByRole("heading", { name: "결제 완료" })).toHaveCount(0);
  await page.getByRole("button", { name: "승인 상태 확인" }).click();
  await expect(page.getByRole("heading", { name: "결제 완료" })).toBeVisible();
  await expect(page.getByRole("link", { name: "매출전표" })).toHaveAttribute(
    "href",
    "https://agenttest.kiwoompay.co.kr/common/PayInfoPrintDirectCard.jsp?DAOUTRX=fixture&STATUS=A",
  );
  await expect(page.getByRole("link", { name: "현금영수증" })).toHaveCount(0);
});
test("native history prefers voucher use and does not invent ledger or point tabs", async ({
  page,
}) => {
  await fixture(page, {
    role: "customer",
    status: "active",
    voucher_use_history: [
      {
        id: "used-fixture",
        kind: "voucher_use",
        voucher_id: "synthetic-used-voucher",
        title: "점심 식권",
        merchant_name: "테스트 식당",
        amount: 8000,
        is_bonus: true,
        created_at: "2026-01-02T03:00:00Z",
      },
    ],
    recent_transactions: [
      {
        id: "payment-fixture",
        title: "카드 식사",
        merchant_name: "테스트 식당",
        amount: 9000,
        created_at: "2026-01-03T03:00:00Z",
      },
    ],
    point_transactions: [
      {
        id: "point-fixture",
        reason: "테스트 적립",
        type: "earn",
        amount: 500,
        balance_after: 2000,
        created_at: "2026-01-04T03:00:00Z",
      },
    ],
  });
  await login(page, '내역');
  await expect(page.getByRole('heading', { name: '이용내역' })).toBeVisible();
  await expect(page.locator('.usage-history:visible').getByText('테스트 식당 점심 식권', { exact: true })).toBeVisible();
  await expect(page.locator('.usage-history:visible .usage-row')).toContainText('보너스');
  await expect(page.getByText('카드 식사', { exact: true })).toHaveCount(0);
  await expect(page.getByText('테스트 적립', { exact: false })).toHaveCount(0);
});
test("employee invalid checkout is blocked and only server release confirms cancellation", async ({
  page,
}) => {
  await fixture(page, {
    role: "employee",
    status: "active",
    company_id: "company-fixture",
  });
  await publishedLegal(page);
  await catalogFixture(page, "subsidized");
  await quoteFixture(page, "subsidized", 40000, 2000);
  let canceled = 0;
  await page.route("**/api-fixture/vouchers/purchase-subsidized", (route) =>
    route.fulfill({
      json: {
        ok: true,
        data: {
          order_id: "GE-S-cancel-fixture",
          product_id: product.id,
          amount: 40000,
          checkout_url: "https://evil.invalid/form",
        },
      },
    }),
  );
  await page.route(
    "**/api-fixture/vouchers/subsidized-orders/GE-S-cancel-fixture/cancel",
    async (route) => {
      canceled++;
      await route.fulfill({
        json: { ok: true, data: { released: true, point_amount: 2000 } },
      });
    },
  );
  await selectQuote(page);
  await page.getByLabel("구매 조건 확인").check();
  await page.getByRole("button", { name: "구매하기", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("결제창 URL");
  await expect(
    page.getByRole("heading", { name: "결제 취소 확인" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "예약 취소 요청" }).click();
  await expect(
    page.getByRole("heading", { name: "결제 취소 확인" }),
  ).toBeVisible();
  expect(canceled).toBe(1);
});
test("point-only employee order completes from authoritative issuance without forbidden zero-amount confirm", async ({
  page,
}) => {
  const profile = {
    role: "employee",
    status: "active",
    company_id: "company-fixture",
    point_balance: 42000,
    voucher_balance: 0,
  };
  await fixture(page, profile);
  await publishedLegal(page);
  await catalogFixture(page, "subsidized");
  await quoteFixture(page, "subsidized", 0, 42000);
  let orderBody, confirmBody;
  await page.route(
    "**/api-fixture/vouchers/purchase-subsidized",
    async (route) => {
      orderBody = route.request().postDataJSON();
      Object.assign(profile, { point_balance: 0, voucher_balance: 11 });
      await route.fulfill({
        json: {
          ok: true,
          data: {
            order_id: "GE-S-point-fixture",
            product_id: product.id,
            product_name: product.name,
            total_count: 11,
            amount: 0,
            gross_amount: 42000,
            coupon_discount_amount: 0,
            card_amount: 0,
            point_amount: 42000,
            point_only: true,
            checkout_url: null,
            fulfillment: { order_id: "GE-S-point-fixture", status: "done", issued_count: 11, card_amount: 0, point_amount: 42000 },
          },
        },
      });
    },
  );
  await page.route("**/api-fixture/payments/confirm", async (route) => {
    confirmBody = route.request().postDataJSON();
    await route.fulfill({ status: 422, json: { detail: [{ loc: ["body", "amount"], type: "greater_than", ctx: { gt: 0 } }] } });
  });
  await login(page);
  await page.getByRole("button", { name: "테스트 10+1 식권 선택" }).click();
  await page.getByLabel("사용 포인트").fill("42000");
  await page.getByRole("button", { name: "견적 확인" }).click();
  await page.getByLabel("구매 조건 확인").check();
  await page.getByRole("button", { name: "구매하기", exact: true }).click();
  expect(orderBody).toEqual({
    product_id: product.id,
    requested_point_amount: 42000,
  });
  await expect(page.getByRole("heading", { name: "결제 완료" })).toBeVisible();
  await expect(page.getByText("발급 식권 11장")).toBeVisible();
  expect(confirmBody).toBeUndefined();
  await page.getByRole("navigation").getByRole("button", { name: "홈", exact: true }).click();
  await expect(page.getByText('보유 보조금 식권 11장 · 실제 결제 방식은 서버에서 확인해요.')).toBeVisible();
  await expect(page.locator(".ticket-wallet")).toContainText("0P");
  expect(page.context().pages()).toHaveLength(1);
});
for (const invalid of ["missing", "wrong-order", "wrong-count", "not-done"]) {
  test(`point-only ${invalid} fulfillment never fabricates completion or retries order`, async ({ page }) => {
    const calls = await fixture(page, { role: "employee", status: "active", point_balance: 42000 });
    await publishedLegal(page);
    await catalogFixture(page, "subsidized");
    await quoteFixture(page, "subsidized", 0, 42000);
    let purchases = 0;
    await page.route("**/api-fixture/vouchers/purchase-subsidized", route => {
      purchases++;
      const fulfillment = { order_id: "GE-S-invalid-point", status: "done", issued_count: 11, card_amount: 0, point_amount: 42000 };
      if (invalid === "wrong-order") fulfillment.order_id = "GE-S-another-order";
      if (invalid === "wrong-count") fulfillment.issued_count = 12;
      if (invalid === "not-done") fulfillment.status = "ready";
      return route.fulfill({ json: { ok: true, data: { order_id: "GE-S-invalid-point", product_id: product.id, product_name: product.name, total_count: 11, amount: 0, card_amount: 0, point_amount: 42000, point_only: true, checkout_url: null, fulfillment: invalid === "missing" ? null : fulfillment } } });
    });
    await login(page);
    await page.getByRole("button", { name: "테스트 10+1 식권 선택" }).click();
    await page.getByLabel("사용 포인트").fill("42000");
    await page.getByRole("button", { name: "견적 확인" }).click();
    await page.getByLabel("구매 조건 확인").check();
    await page.getByRole("button", { name: "구매하기", exact: true }).click();
    await expect(page.getByRole("heading", { name: "주문 상태 확인 필요" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "결제 완료" })).toHaveCount(0);
    await page.reload();
    await expect(page.getByRole("heading", { name: "주문 상태 확인 필요" })).toBeVisible();
    expect(purchases).toBe(1);
    expect(calls.some(c => c.path === "/payments/confirm")).toBe(false);
    expect(page.context().pages()).toHaveLength(1);
  });
}
test("restored zero-card order remains unresolved without forbidden confirm or cancel", async ({ page }) => {
  const calls = await fixture(page, { role: "employee", status: "active" });
  await page.addInitScript(() => sessionStorage.setItem("greeneat-purchase-pending:11111111-1111-4111-8111-111111111111", JSON.stringify({ order_id: "GE-S-zero-unresolved", amount: 0, mode: "subsidized", checkout_started: false })));
  await login(page);
  await expect(page.getByRole("heading", { name: "주문 상태 확인 필요" })).toBeVisible();
  await expect(page.getByRole("button", { name: "승인 상태 확인" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "예약 취소 요청" })).toHaveCount(0);
  expect(calls.some(c => c.path === "/payments/confirm")).toBe(false);
});
test("ordinary order opens exact API server form, callback and popup close cannot approve pending", async ({
  page,
  context,
}) => {
  await fixture(page);
  await publishedLegal(page);
  await catalogFixture(page);
  await quoteFixture(page);
  let orderBody,
    formPosted = false,
    confirms = 0;
  const token = "a".repeat(43);
  await page.route("**/api-fixture/vouchers/purchase", async (route) => {
    orderBody = route.request().postDataJSON();
    await route.fulfill({
      json: {
        ok: true,
        data: {
          order_id: "GE-V-fixture",
          amount: 72000,
          gross_amount: 72000,
          coupon_discount_amount: 0,
          point_amount: 0,
          product_id: product.id,
          checkout_url: `http://127.0.0.1:4175/api-fixture/payments/checkout/${token}`,
        },
      },
    });
  });
  await context.route(`**/api-fixture/payments/checkout/${token}`, (route) =>
    route.fulfill({
      contentType: "text/html",
      body: '<h1>MOCK SERVER CHECKOUT FORM</h1><form method="post" action="https://apitest.kiwoompay.co.kr/pay/linkEnc" accept-charset="EUC-KR"><input name="ORDERNO" value="GE-V-fixture"><input name="AMOUNT" value="72000"></form><script>document.querySelector("form").submit()</script>',
    }),
  );
  await context.route(
    "https://apitest.kiwoompay.co.kr/pay/linkEnc",
    async (route) => {
      formPosted =
        route.request().method() === "POST" &&
        route.request().postData().includes("ORDERNO=GE-V-fixture");
      await route.fulfill({
        contentType: "text/html",
        body: "<h1>MOCK PROVIDER ONLY</h1>",
      });
    },
  );
  await page.route("**/api-fixture/payments/confirm", async (route) => {
    confirms++;
    await route.fulfill({
      status: 409,
      json: { detail: { code: "PAYMENT_PENDING", message: "승인 대기 중" } },
    });
  });
  await selectQuote(page);
  await page.getByLabel("구매 조건 확인").check();
  const popupPromise = page.waitForEvent("popup");
  await page.getByRole("button", { name: "구매하기", exact: true }).click();
  const popup = await popupPromise;
  await expect.poll(() => formPosted).toBe(true);
  expect(orderBody).toEqual({
    product_id: product.id,
    requested_point_amount: 0,
  });
  await popup.close();
  await page.evaluate(() =>
    window.postMessage(
      { type: "payment_success", order_id: "GE-V-fixture", status: "done" },
      "*",
    ),
  );
  await page.getByRole("button", { name: "승인 상태 확인" }).click();
  await expect(
    page.getByText("결제 승인 확인 중", { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "결제 완료" })).toHaveCount(0);
  expect(confirms).toBe(1);
  await expect(
    page.getByRole("button", { name: "구매하기", exact: true }),
  ).toHaveCount(0);
});
test("eligible employee point quote preserves server split and invalidates quote on edits", async ({
  page,
}) => {
  await fixture(page, {
    role: "employee",
    status: "active",
    company_id: "company-fixture",
  });
  await publishedLegal(page);
  await catalogFixture(page, "subsidized");
  let quoted;
  await page.route("**/api-fixture/vouchers/quote", async (route) => {
    quoted = route.request().postDataJSON();
    await route.fulfill({
      json: {
        ok: true,
        data: {
          merchant_id: "merchant-fixture",
          merchant_name: "테스트 식당",
          product_id: product.id,
          purchase_mode: "subsidized",
          gross_amount: 42000,
          coupon_discount_amount: 0,
          point_amount: 2000,
          payment_amount: 40000,
        },
      },
    });
  });
  await login(page);
  await page.getByRole("button", { name: "테스트 10+1 식권 선택" }).click();
  await expect(page.getByText("회사 지원 합계 20,000원")).toBeVisible();
  await page.getByLabel("사용 포인트").fill("2000");
  await page.getByRole("button", { name: "견적 확인" }).click();
  expect(quoted).toEqual({
    product_id: product.id,
    requested_point_amount: 2000,
  });
  await expect(page.getByText("포인트 사용 2,000P")).toBeVisible();
  await expect(page.getByText("최종 결제 40,000원")).toBeVisible();
  await page.getByLabel("사용 포인트").fill("1000");
  await expect(page.getByText("최종 결제 40,000원")).toHaveCount(0);
});
test("ordinary package selection shows API terms and coupon quote without client quantity or points", async ({
  page,
}) => {
  await fixture(page);
  await publishedLegal(page);
  await catalogFixture(page);
  let quoted;
  await page.route("**/api-fixture/vouchers/quote", async (route) => {
    quoted = route.request().postDataJSON();
    await route.fulfill({
      json: {
        ok: true,
        data: {
          merchant_id: "merchant-fixture",
          merchant_name: "테스트 식당",
          product_id: product.id,
          purchase_mode: "voucher",
          gross_amount: 72000,
          coupon_discount_amount: 1000,
          point_amount: 0,
          payment_amount: 71000,
        },
      },
    });
  });
  await login(page);
  await page.getByRole("button", { name: "테스트 10+1 식권 선택" }).click();
  await expect(page.locator('.purchase-detail').getByText("유료 10장 + 보너스 1장")).toBeVisible();
  await expect(page.getByText("할인율 10%")).toBeVisible();
  await page.getByLabel("할인 쿠폰").selectOption("public:coupon-fixture");
  await page.getByRole("button", { name: "견적 확인" }).click();
  await expect(page.getByText("최종 결제 71,000원")).toBeVisible();
  expect(quoted).toEqual({
    product_id: product.id,
    requested_point_amount: 0,
    coupon_id: "coupon-fixture",
  });
  await expect(page.getByLabel("사용 포인트")).toHaveCount(0);
  await expect(
    page.locator(".purchase-quote").getByText("테스트 식당", { exact: true }),
  ).toBeVisible();
});
test("employee requests membership then sees pending server state without catalog", async ({
  page,
}) => {
  const profile = { status: "no_profile" };
  const calls = await fixture(page, profile);
  await publishedLegal(page);
  await page.route("**/api-fixture/join/request", async (route) => {
    calls.push({ path: "/join/request", body: route.request().postDataJSON() });
    Object.assign(profile, { role: "employee", status: "pending" });
    await route.fulfill({ json: { ok: true, data: profile } });
  });
  await login(page);
  await page.getByLabel("이름", { exact: true }).fill("직원");
  await page.getByLabel("휴대폰 번호").fill("01012345678");
  await page.getByLabel("회사 초대코드").fill("GE-FIXTURE");
  await page.getByLabel("약관 및 개인정보 처리방침 확인").check();
  await page.getByRole("button", { name: "회사 가입 신청" }).click();
  await expect(page.getByRole("alert")).toContainText("pending");
  expect(calls.find((c) => c.path === "/join/request").body).toEqual({
    invite_code: "GE-FIXTURE",
    display_name: "직원",
    phone: "01012345678",
  });
  expect(calls.some((c) => c.path === "/vouchers/products")).toBe(false);
});
test("signup with actual published documents requires consent and waits for email verification", async ({
  page,
}) => {
  const calls = await fixture(page);
  let signup;
  await page.route("**/auth-fixture/auth/v1/signup**", async (route) => {
    signup = route.request().postDataJSON();
    await route.fulfill({
      json: { user: { id: "new-fixture", email: signup.email }, session: null },
    });
  });
  await page.goto("/shop");
  await page.getByRole("button", { name: "회원가입", exact: true }).click();
  await page.getByLabel("이메일", { exact: true }).fill("new@example.invalid");
  await page
    .getByLabel("비밀번호", { exact: true })
    .fill("mocked-password-only");
  await expect(page.getByRole("button", { name: "가입 신청", exact: true })).toBeDisabled();
  await page.getByLabel("약관 및 개인정보 처리방침 확인").check();
  await page.getByRole("button", { name: "가입 신청", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("이메일 인증");
  expect(signup.email).toBe("new@example.invalid");
  expect(calls).toEqual([]);
});
test("new authenticated purchaser registers with normalized phone and server profile refresh", async ({
  page,
}) => {
  const profile = { status: "no_profile" };
  const calls = await fixture(page, profile);
  await publishedLegal(page);
  await page.route("**/api-fixture/consumer/register", async (route) => {
    calls.push({
      path: "/consumer/register",
      body: route.request().postDataJSON(),
    });
    Object.assign(profile, { role: "customer", status: "active" });
    await route.fulfill({ json: { ok: true, data: profile } });
  });
  await login(page);
  await page.getByLabel("이름", { exact: true }).fill(" 새 고객 ");
  await page.getByLabel("휴대폰 번호").fill("010-1234-5678");
  await page.getByLabel("약관 및 개인정보 처리방침 확인").check();
  await page.getByRole("button", { name: "일반 구매자로 등록" }).click();
  await expect(page.getByRole("region", { name: "내 지갑" })).toBeVisible();
  expect(calls.find((c) => c.path === "/consumer/register").body).toEqual({
    display_name: "새 고객",
    phone: "01012345678",
  });
});
test("purchaser rejects admin and pending employee instead of exposing a wallet", async ({
  page,
}) => {
  await fixture(page, { role: "merchant_admin", status: "active" });
  await login(page);
  await expect(page.getByRole("alert")).toContainText("구매자 계정이 아니에요");
  await expect(page.getByRole("region", { name: "내 지갑" })).toHaveCount(0);
});

test("purchaser sign-in renders its own wallet, refresh and logout", async ({
  page,
}) => {
  const calls = await fixture(page);
  await login(page);
  await expect(page.getByRole("heading", { name: "식권 구매" })).toBeVisible();
  await page.getByRole("navigation").getByRole("button", { name: "홈", exact: true }).click();
  await expect(page.locator(".ticket-balance")).toHaveText("3장");
  await page.getByRole("button", { name: "새로고침", exact: true }).click();
  await expect.poll(() => calls.filter((c) => c.path === "/me").length).toBe(2);
  await page.getByRole("navigation").getByRole("button", { name: "내정보", exact: true }).click();
  await page.getByRole("button", { name: "로그아웃", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "로그인", exact: true }),
  ).toBeVisible();
});
