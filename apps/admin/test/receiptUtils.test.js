import assert from 'node:assert/strict';
import test from 'node:test';

import { receiptApiPath, receiptTypeLabel, validateReceiptUrl } from '../src/receiptUtils.js';

const card = 'https://agent.kiwoompay.co.kr/common/PayInfoPrintDirectCard.jsp?DAOUTRX=trx-1&STATUS=A';
const bank = 'https://agenttest.kiwoompay.co.kr/common/PayInfoPrintBank.jsp?DAOUTRX=trx-2&STATUS=A';
const cash = 'https://agent.kiwoompay.co.kr/common/CashRecInfoPrint.jsp?DAOUTRX=trx-3';

test('receipt URL validator allows only exact official receipt destinations', () => {
  assert.equal(validateReceiptUrl(card), card);
  assert.equal(validateReceiptUrl(bank), bank);
  assert.equal(validateReceiptUrl(cash), cash);
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
