import test from "node:test";
import assert from "node:assert/strict";
const subject = await import("../src/purchaseSafety.js").catch(() => ({}));
test("purchase blocks missing merchant business and provider disclosures even when legal text is populated", () => {
  assert.equal(typeof subject.purchaseDisclosuresReady, "function");
  assert.equal(
    subject.purchaseDisclosuresReady(
      "이용약관 운영자 연락처만 있음",
      "테스트 식당",
    ),
    false,
  );
  assert.equal(
    subject.purchaseDisclosuresReady(
      "테스트 식당 사업자등록번호 000-00-00000 대표자 테스트 주소 테스트 연락처 fixture@example.invalid 결제대행 키움페이",
      "다른 식당",
    ),
    false,
  );
  assert.equal(
    subject.purchaseDisclosuresReady(
      "MOCK ONLY 테스트 식당 사업자등록번호 000-00-00000 대표자 테스트 주소 테스트 연락처 fixture@example.invalid 결제대행 키움페이",
      "테스트 식당",
    ),
    true,
  );
});
test("checkout accepts only exact configured API form endpoint with server token", () => {
  assert.equal(typeof subject.safeCheckoutUrl, "function");
  const base = "https://api.example.invalid/v1";
  const token = "a".repeat(43);
  const valid = `${base}/payments/checkout/${token}`;
  assert.equal(subject.safeCheckoutUrl(valid, base), valid);
  for (const url of [
    `https://evil.invalid/payments/checkout/${token}`,
    `${valid}?next=x`,
    `${valid}#x`,
    `${base}/payments/checkout/x`,
    `https://user@api.example.invalid/v1/payments/checkout/${token}`,
    `javascript:alert(1)`,
    `${base}/payments/checkout/${token}/extra`,
    `https://api.example.invalid:444/v1/payments/checkout/${token}`,
  ])
    assert.equal(subject.safeCheckoutUrl(url, base), null, url);
  assert.equal(
    subject.safeCheckoutUrl(
      `http://127.0.0.1:4175/api-fixture/payments/checkout/${token}`,
      "http://127.0.0.1:4175/api-fixture",
    ),
    `http://127.0.0.1:4175/api-fixture/payments/checkout/${token}`,
  );
  assert.equal(
    subject.safeCheckoutUrl(
      `http://api.example.invalid/payments/checkout/${token}`,
      "http://api.example.invalid",
    ),
    null,
  );
});

test("unpublished legal/provider disclosures are blocked, existing populated documents accepted", () => {
  assert.equal(typeof subject.legalDocumentsReady, "function");
  assert.equal(
    subject.legalDocumentsReady([
      "이용약관 【YYYY.MM.DD】",
      "개인정보 처리방침",
    ]),
    false,
  );
  assert.equal(
    subject.legalDocumentsReady([
      "이용약관 회사 【사업자등록번호】",
      "개인정보 처리방침",
    ]),
    false,
  );
  assert.equal(
    subject.legalDocumentsReady([
      "이용약관 시행일 2026.01.01 운영자 테스트 법인 사업자 정보",
      "개인정보 처리방침 개인정보 보호책임자 테스트 담당",
    ]),
    true,
  );
  assert.equal(subject.legalDocumentsReady(["", ""]), false);
});
