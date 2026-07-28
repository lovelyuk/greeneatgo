import test from 'node:test';
import assert from 'node:assert/strict';
import {
  changePercent, CompanyUsageContractError, currentPeriodYm, formatPeriodYm,
  mapCompanyUsage, shiftPeriodYm,
} from '../src/companyUsage.js';

function payload(overrides = {}) {
  return {
    period: { ym: '2025-02', timezone: 'Asia/Seoul', start_at: '2025-01-31T15:00:00Z', end_at: '2025-02-28T15:00:00Z' },
    summary: {
      gross_spend_amount: 123000, company_charge_amount: 113000, employee_paid_amount: 10000,
      transaction_count: 15, spend_count: 14, reversal_count: 1, unique_users: 7,
      used_employee_count: 7, total_employee_count: 12, active_employee_count: 9,
      outstanding_settlement_amount: 33000, confirmed_payment_amount: 80000,
    },
    daily: [{
      date: '2025-02-03', gross_spend_amount: 45000, company_charge_amount: 40000,
      employee_paid_amount: 5000, transaction_count: 6, spend_count: 5, reversal_count: 1, unique_users: 3,
    }],
    employees: [{
      user_id: '22222222-2222-2222-2222-222222222222', display_name: '직원 1', employee_no: 'E-1',
      department: '운영', status: 'active', gross_spend_amount: 45000, company_charge_amount: 40000,
      employee_paid_amount: 5000, transaction_count: 6, spend_count: 5, reversal_count: 1, usage_days: 2,
    }],
    settlements: { count: 2, total_amount: 113000, confirmed_payment_amount: 80000, outstanding_amount: 33000 },
    ...overrides,
  };
}

test('month helpers navigate with integer arithmetic, including years 0-99', () => {
  assert.equal(currentPeriodYm(new Date(2024, 0, 15)), '2024-01');
  assert.equal(shiftPeriodYm('2024-01', -1), '2023-12');
  assert.equal(shiftPeriodYm('2024-12', 1), '2025-01');
  assert.equal(shiftPeriodYm('0099-12', 1), '0100-01');
  assert.equal(formatPeriodYm('2024-09'), '2024년 9월');
});

test('changePercent handles decreases, invalid values, and a zero baseline', () => {
  assert.equal(changePercent(80, 100), -20);
  assert.equal(changePercent(0, 0), 0);
  assert.equal(changePercent(100, 0), null);
  assert.equal(changePercent('80', 100), null);
});

test('strictly maps every documented company usage field and preserves reversals/status', () => {
  const mapped = mapCompanyUsage(payload(), '2025-02');
  assert.equal(mapped.periodYm, '2025-02');
  assert.equal(mapped.summary.grossSpendAmount, 123000);
  assert.equal(mapped.summary.usedEmployees, 7);
  assert.equal(mapped.summary.spendCount, 14);
  assert.equal(mapped.summary.reversalCount, 1);
  assert.deepEqual(mapped.daily[0], {
    id: '2025-02-03', date: '2025-02-03', grossSpendAmount: 45000, companyChargeAmount: 40000,
    employeePaidAmount: 5000, transactionCount: 6, spendCount: 5, reversalCount: 1, uniqueUsers: 3,
  });
  assert.equal(mapped.employees[0].status, 'active');
  assert.equal(mapped.employees[0].reversalCount, 1);
  assert.equal(mapped.employees[0].usageDays, 2);
  assert.deepEqual(mapped.settlements, { count: 2, total_amount: 113000, confirmed_payment_amount: 80000, outstanding_amount: 33000 });
});

test('throws a contract error for missing, aliased, extra, noninteger, or mismatched fields', () => {
  const cases = [
    {},
    payload({ summary: { ...payload().summary, gross_spend_amount: '123000' } }),
    payload({ summary: { ...payload().summary, transaction_count: 1.5 } }),
    payload({ summary: { ...payload().summary, extra_amount: 0 } }),
    payload({ daily: [{ ...payload().daily[0], spend_count: undefined }] }),
    payload({ employees: [{ ...payload().employees[0], status: undefined }] }),
    payload({ settlements: { ...payload().settlements, latest_invoice: null } }),
    payload({ period: { ...payload().period, ym: '2025-03' } }),
  ];
  for (const value of cases) {
    assert.throws(() => mapCompanyUsage(value, '2025-02'), CompanyUsageContractError);
  }
});

test('allows documented nullable employee number and department but not absent arrays', () => {
  const source = payload();
  source.employees[0] = { ...source.employees[0], employee_no: null, department: null };
  assert.equal(mapCompanyUsage(source, '2025-02').employees[0].department, null);
  assert.throws(() => mapCompanyUsage({ ...payload(), daily: undefined }, '2025-02'), CompanyUsageContractError);
});
