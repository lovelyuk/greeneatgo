import assert from 'node:assert/strict';
import test from 'node:test';

import { completionLookupRows, receiptAmountLabel, receiptApiPath, receiptLookupRows, receiptRows, receiptTypeLabel, validateReceiptUrl } from '../src/receiptUtils.js';

const card = 'https://agent.kiwoompay.co.kr/common/PayInfoPrintDirectCard.jsp?DAOUTRX=trx-1&STATUS=A';
const bank = 'https://agenttest.kiwoompay.co.kr/common/PayInfoPrintBank.jsp?DAOUTRX=trx-2&STATUS=A';
const cash = 'https://agent.kiwoompay.co.kr/common/CashRecInfoPrint.jsp?DAOUTRX=trx-3';

test('receipt URL validator allows only exact official receipt destinations', () => {
  assert.equal(validateReceiptUrl(card), card);
  assert.equal(validateReceiptUrl(bank), bank);
  assert.equal(validateReceiptUrl(cash), cash);
  // Kiwoom "전표 호출 안내": easy-pay methods have their own slip pages.
  for (const page of ['PayInfoPrintNaverPay.jsp', 'PayInfoPrintKakaoPay.jsp']) {
    const url = `https://agent.kiwoompay.co.kr/common/${page}?DAOUTRX=trx-4&STATUS=A`;
    assert.equal(validateReceiptUrl(url), url);
    assert.equal(validateReceiptUrl(`${url}&next=evil`), '');
  }
});

test('receipt URL validator rejects hostile or malformed destinations', () => {
  for (const value of [
    '',
    'javascript:alert(1)',
    'http://agent.kiwoompay.co.kr/common/PayInfoPrintDirectCard.jsp?DAOUTRX=x&STATUS=A',
    'https://agent.kiwoompay.co.kr.evil.example/common/PayInfoPrintDirectCard.jsp?DAOUTRX=x&STATUS=A',
    'https://user:pass@agent.kiwoompay.co.kr/common/PayInfoPrintDirectCard.jsp?DAOUTRX=x&STATUS=A',
    'https://agent.kiwoompay.co.kr:444/common/PayInfoPrintDirectCard.jsp?DAOUTRX=x&STATUS=A',
    'https://agent.kiwoompay.co.kr/common/Other.jsp?DAOUTRX=x',
    'https://agent.kiwoompay.co.kr/common/PayInfoPrintDirectCard.jsp?DAOUTRX=x&STATUS=R',
    'https://agent.kiwoompay.co.kr/common/CashRecInfoPrint.jsp?DAOUTRX=x&next=evil',
    'https://agent.kiwoompay.co.kr/common/CashRecInfoPrint.jsp?DAOUTRX=x#fragment',
  ]) assert.equal(validateReceiptUrl(value), '', value);
});

test('typed receipt API paths never accept URL or arbitrary receipt type input', () => {
  const descriptor = { entry_kind: 'refund', entry_id: 'refund/id', source: 'original_payment' };
  assert.equal(receiptApiPath(descriptor, 'cash_receipt'), '/admin/merchant/payment-history/receipts/refund/refund%2Fid/cash_receipt');
  assert.equal(receiptApiPath({ entry_kind: 'other', entry_id: '1' }, 'cash_receipt'), '');
  assert.equal(receiptApiPath(descriptor, 'https://evil.example'), '');
  assert.equal(receiptTypeLabel('sales_slip', descriptor.source), '원결제 매출전표');
});

test('receipt rows show our own record in KST and drop empty values', () => {
  const receipt = {
    product_name: '합성 식권', merchant_name: '합성식당', amount: 12000, status: 'done', method_label: '네이버페이',
    issuer_name: null, masked_card_number: '****-****-****-1234', bank_name: null,
    authorization_number: '12345678', order_number: 'GE-1', approved_at: '2026-11-11T07:41:39+00:00',
  };
  assert.deepEqual(receiptRows(receipt), [
    ['상품명', '합성 식권'], ['판매처', '합성식당'], ['결제수단', '네이버페이'], ['카드', '****-****-****-1234'],
    ['승인번호', '12345678'], ['주문번호', 'GE-1'], ['결제일시', '2026.11.11 16:41'], ['거래상태', '승인 완료'],
  ]);
  assert.equal(receiptAmountLabel(receipt), '12,000원');
  assert.deepEqual(receiptRows(null), []);
  assert.equal(receiptAmountLabel({ amount: '12000' }), '');
});

test('receipt lookup rows are the three values the provider slip page asks for', () => {
  assert.deepEqual(receiptLookupRows({ lookup: { date: '2026-11-11', amount: 100, number: '12345678', number_type: 'approval' } }), [
    { label: '결제일자', value: '2026-11-11' }, { label: '결제금액', value: '100' }, { label: '승인번호', value: '12345678' },
  ]);
  assert.equal(receiptLookupRows({ lookup: { date: '2026-11-12', amount: 80000, number: 'GE-2', number_type: 'order' } })[2].label, '주문번호');
  for (const lookup of [null, {}, { date: '11/11', amount: 100, number: '1' }, { date: '2026-11-11', amount: '100', number: '1' }, { date: '2026-11-11', amount: 100, number: '' }]) {
    assert.deepEqual(receiptLookupRows({ lookup }), []);
  }
});

test('buyer completion lookup uses the KST payment date and falls back to the order number', () => {
  const completion = { order_id: 'GE-1', amount: 100, payment: { approved_at: '2026-11-11T15:30:00+00:00', authorization_number: '12345678' } };
  assert.deepEqual(completionLookupRows(completion).map((row) => row.value), ['2026-11-12', '100', '12345678']);
  const bank = { ...completion, payment: { approved_at: completion.payment.approved_at, authorization_number: null } };
  assert.deepEqual(completionLookupRows(bank).at(-1), { label: '주문번호', value: 'GE-1' });
  assert.deepEqual(completionLookupRows({ order_id: 'GE-1', amount: 0, payment: { approved_at: completion.payment.approved_at } }), []);
  assert.deepEqual(completionLookupRows({}), []);
});
