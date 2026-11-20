import { test, expect } from '@playwright/test';
import { adminLogin, COMPANY_ID, MERCHANT_ID } from './admin-fixture.mjs';

// The company disputed a settlement. The restaurant must see why, start a
// revision, cancel the wrong meal (amount recalculated) and send it again.
const SID = '44444444-4444-4444-8444-444444444444';
const REASON = '11월 15일 김하늘은 연차라 식사하지 않았습니다.';

function meal(id, day, name) {
  return { id, created_at: `2026-11-${day}T03:10:00+00:00`, employee_name: name, employee_no: `E${id}`, department: '개발팀',
    kind: 'spend', pay_type: 'ledger', meal_window: '중식', item: '중식', tx_code: `TX-${id}`,
    tax_type: 'taxable', supply_amount: 8000, vat_amount: 800, total_amount: 8800, is_demo: false,
    cancelled: false, original_transaction_id: null, cancel_reason: null };
}

async function setup(page, context, { role = 'merchant_admin', status = 'disputed' } = {}) {
  const state = {
    status,
    transactions: [meal(1, '03', '박민수'), meal(2, '15', '김하늘'), meal(3, '28', '박민수')],
    events: [
      { id: 1, event_type: 'merchant_sent', payload: {}, created_at: '2026-12-01T01:00:00+00:00' },
      { id: 2, event_type: 'company_disputed', payload: { reason: REASON }, created_at: '2026-12-02T02:30:00+00:00' },
    ],
    posts: [],
  };
  const detail = () => {
    const total = state.transactions.reduce((sum, row) => sum + row.total_amount, 0);
    return {
      id: SID, company_id: COMPANY_ID, merchant_id: MERCHANT_ID, period_ym: '2026-11', period_from: '2026-11-01', period_to: '2026-11-30',
      total_amount: total, supply_amount: Math.round(total / 1.1), vat_amount: total - Math.round(total / 1.1),
      settlement_status: state.status, tax_invoice_status: 'not_requested', payment_status: 'unpaid', due_date: '2026-12-30', is_demo: false,
      business_information: { id: COMPANY_ID, name: '합성테크', biz_reg_no: '123-45-67890', representative_name: '대표', address: '서울', business_type: '서비스', business_item: '소프트웨어', tax_invoice_email: 'tax@example.invalid', contact_name: '담당', contact_phone: '01000000000' },
      supplier_information: { name: '가산 한식뷔페', biz_reg_no: '999-88-77777', representative_name: '사장', address: '서울', business_type: '음식', business_item: '한식', tax_invoice_email: 's@example.invalid' },
      tax_invoices: [], payments: [], events: state.events, transactions: state.transactions,
    };
  };
  await adminLogin(page, context, { role });
  const root = role === 'merchant_admin' ? 'admin/merchant/settlements' : 'company/settlements';
  await page.route(`**/api-fixture/${root}**`, async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace('/api-fixture', '');
    const method = route.request().method();
    if (method === 'POST') {
      state.posts.push({ path, body: route.request().postDataJSON() });
      if (path.endsWith('/begin-revision')) state.status = 'revising';
      else if (path.endsWith('/send')) state.status = 'sent';
      else if (path.endsWith('/cancel')) {
        const id = Number(path.split('/').at(-2));
        const original = state.transactions.find((row) => row.id === id);
        original.cancelled = true;
        state.transactions.push({ ...original, id: 100 + id, kind: 'cancel', cancelled: false, original_transaction_id: id,
          cancel_reason: route.request().postDataJSON().reason, tx_code: `CX-${id}`,
          supply_amount: -8000, vat_amount: -800, total_amount: -8800 });
      }
      return route.fulfill({ json: { ok: true, data: { settlement: detail(), idempotent: false } } });
    }
    if (path.endsWith('/popbill-readiness')) return route.fulfill({ json: { ok: true, data: {} } });
    if (path.endsWith(`/${SID}`)) return route.fulfill({ json: { ok: true, data: detail() } });
    const { transactions, events, ...summary } = detail();
    return route.fulfill({ json: { ok: true, data: { items: [summary] } } });
  });
  return state;
}

test('restaurant sees the dispute reason, cancels the wrong meal and resends', async ({ page, context }) => {
  const state = await setup(page, context);
  await page.getByRole('navigation', { name: '식당 관리자 메뉴' }).getByRole('button', { name: '매출 정산' }).click();
  await page.getByRole('button', { name: /2026-11 합성테크 정산서 상세 보기/ }).click();

  // 1) Why the company objected is shown before anything is changed.
  const banner = page.getByRole('status').filter({ hasText: '업체가 이의를 제기했습니다' });
  await expect(banner).toContainText(REASON);
  await expect(banner).toContainText('‘정산서 수정 시작’을 누르면');
  // Disputed but not yet revising: nothing can be cancelled.
  await expect(page.getByRole('button', { name: /거래 취소/ })).toHaveCount(0);

  await page.getByRole('button', { name: '정산서 수정 시작' }).click();
  await expect(banner).toContainText('잘못된 거래를 취소하거나 정산 기간을 바꾼 뒤');
  await expect(page.getByText('3건 · 합계 ₩26,400')).toBeVisible();
  await expect(page.getByRole('button', { name: /거래 취소/ })).toHaveCount(3);

  // 2) Cancel the 15th: reason required, the amount is recalculated.
  await page.getByRole('button', { name: '김하늘 2026-11-15 거래 취소' }).click();
  const dialog = page.getByRole('dialog', { name: '거래 취소' });
  await expect(dialog).toContainText('김하늘');
  await expect(dialog.getByRole('button', { name: '이 거래 취소' })).toBeDisabled();
  await dialog.getByLabel('취소 사유').fill('연차로 식사하지 않음');
  await dialog.getByRole('button', { name: '이 거래 취소' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText('거래를 취소하고 정산 금액을 다시 계산했습니다.')).toBeVisible();
  await expect(page.getByText('4건 · 합계 ₩17,600')).toBeVisible();
  expect(state.posts.at(-1)).toEqual({ path: `/admin/merchant/settlements/${SID}/transactions/2/cancel`, body: { reason: '연차로 식사하지 않음' } });
  // The cancelled meal stays listed, marked, and cannot be cancelled twice; the reversal shows the reason.
  await expect(page.getByRole('row', { name: /TX-2/ })).toContainText('장부 (취소됨)');
  await expect(page.getByRole('row', { name: /CX-2/ })).toContainText('사유: 연차로 식사하지 않음');
  await expect(page.getByRole('button', { name: /거래 취소/ })).toHaveCount(2);

  await page.getByRole('button', { name: '업체에 정산서 재발송' }).click();
  await expect(page.getByText('수정 검토한 정산서를 업체에 재발송했습니다.')).toBeVisible();
  // Sent again: read-only, and the old dispute banner is gone.
  await expect(page.getByRole('button', { name: /거래 취소/ })).toHaveCount(0);
  await expect(banner).toHaveCount(0);
  expect(state.posts.map((post) => post.path.split('/').at(-1))).toEqual(['begin-revision', 'cancel', 'send']);
});

test('company sees its own dispute reason but no cancel controls', async ({ page, context }) => {
  await setup(page, context, { role: 'company_admin', status: 'revising' });
  await page.getByRole('navigation', { name: '업체 관리자 메뉴' }).getByRole('button', { name: '청구 내역' }).click();
  await page.getByRole('button', { name: /2026-11 .*정산서 상세 보기/ }).click();
  const banner = page.getByRole('status').filter({ hasText: '이의를 제기한 정산서입니다' });
  await expect(banner).toContainText(REASON);
  await expect(page.getByText('3건 · 합계 ₩26,400')).toBeVisible();
  await expect(page.getByRole('button', { name: /거래 취소/ })).toHaveCount(0);
  await expect(page.getByRole('columnheader', { name: '관리' })).toHaveCount(0);
});
