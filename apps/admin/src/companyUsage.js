const YM_PATTERN = /^(\d{4})-(0[1-9]|1[0-2])$/;
const DATE_PATTERN = /^\d{4}-(0[1-9]|1[0-2])-([0-2]\d|3[01])$/;

const AMOUNT_KEYS = [
  'gross_spend_amount', 'company_charge_amount', 'employee_paid_amount',
  'transaction_count', 'spend_count', 'reversal_count', 'unique_users',
];
const SUMMARY_KEYS = [
  ...AMOUNT_KEYS, 'used_employee_count', 'total_employee_count', 'active_employee_count',
  'outstanding_settlement_amount', 'confirmed_payment_amount',
];
const EMPLOYEE_KEYS = [
  'user_id', 'display_name', 'employee_no', 'department', 'status',
  'gross_spend_amount', 'company_charge_amount', 'employee_paid_amount',
  'transaction_count', 'spend_count', 'reversal_count', 'usage_days',
];
const SETTLEMENT_KEYS = ['count', 'total_amount', 'confirmed_payment_amount', 'outstanding_amount'];

export class CompanyUsageContractError extends Error {
  constructor(message) {
    super(`회사 이용 현황 응답 형식이 올바르지 않습니다: ${message}`);
    this.name = 'CompanyUsageContractError';
    this.code = 'COMPANY_USAGE_CONTRACT_ERROR';
  }
}

const fail = (path, expected) => { throw new CompanyUsageContractError(`${path} (${expected})`); };
const objectAt = (value, path) => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) fail(path, '객체 필요');
  return value;
};
const exactKeys = (value, keys, path) => {
  const actual = Object.keys(objectAt(value, path)).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    fail(path, `필드 ${expected.join(', ')} 필요`);
  }
};
const integerAt = (value, path) => {
  if (typeof value !== 'number' || !Number.isFinite(value) || !Number.isInteger(value)) fail(path, '유한한 정수 필요');
  return value;
};
const stringAt = (value, path) => {
  if (typeof value !== 'string' || value.length === 0) fail(path, '문자열 필요');
  return value;
};
const nullableStringAt = (value, path) => {
  if (value !== null && typeof value !== 'string') fail(path, '문자열 또는 null 필요');
  return value;
};

export function currentPeriodYm(date = new Date()) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
}

export function shiftPeriodYm(ym, offset) {
  if (!YM_PATTERN.test(ym) || !Number.isInteger(offset)) return currentPeriodYm();
  const [year, month] = ym.split('-').map(Number);
  const monthIndex = year * 12 + month - 1 + offset;
  const shiftedYear = Math.floor(monthIndex / 12);
  const shiftedMonth = ((monthIndex % 12) + 12) % 12 + 1;
  return `${String(shiftedYear).padStart(4, '0')}-${String(shiftedMonth).padStart(2, '0')}`;
}

export function formatPeriodYm(ym) {
  if (!YM_PATTERN.test(ym)) return ym || '-';
  const [year, month] = ym.split('-').map(Number);
  return `${year}년 ${month}월`;
}

export function changePercent(current, previous) {
  if (![current, previous].every((value) => typeof value === 'number' && Number.isFinite(value))) return null;
  if (previous === 0) return current === 0 ? 0 : null;
  return ((current - previous) / previous) * 100;
}

function validateAmounts(value, path) {
  AMOUNT_KEYS.forEach((key) => integerAt(value[key], `${path}.${key}`));
}

export function mapCompanyUsage(payload, requestedYm) {
  exactKeys(payload, ['period', 'summary', 'daily', 'employees', 'settlements'], 'data');

  exactKeys(payload.period, ['ym', 'timezone', 'start_at', 'end_at'], 'data.period');
  const periodYm = stringAt(payload.period.ym, 'data.period.ym');
  if (!YM_PATTERN.test(periodYm)) fail('data.period.ym', 'YYYY-MM 필요');
  if (requestedYm !== undefined && periodYm !== requestedYm) fail('data.period.ym', `요청 월 ${requestedYm} 필요`);
  const timezone = stringAt(payload.period.timezone, 'data.period.timezone');
  stringAt(payload.period.start_at, 'data.period.start_at');
  stringAt(payload.period.end_at, 'data.period.end_at');

  exactKeys(payload.summary, SUMMARY_KEYS, 'data.summary');
  validateAmounts(payload.summary, 'data.summary');
  SUMMARY_KEYS.slice(AMOUNT_KEYS.length).forEach((key) => integerAt(payload.summary[key], `data.summary.${key}`));

  if (!Array.isArray(payload.daily)) fail('data.daily', '배열 필요');
  const daily = payload.daily.map((row, index) => {
    const path = `data.daily[${index}]`;
    exactKeys(row, ['date', ...AMOUNT_KEYS], path);
    const date = stringAt(row.date, `${path}.date`);
    if (!DATE_PATTERN.test(date)) fail(`${path}.date`, 'YYYY-MM-DD 필요');
    validateAmounts(row, path);
    return {
      id: date, date,
      grossSpendAmount: row.gross_spend_amount,
      companyChargeAmount: row.company_charge_amount,
      employeePaidAmount: row.employee_paid_amount,
      transactionCount: row.transaction_count,
      spendCount: row.spend_count,
      reversalCount: row.reversal_count,
      uniqueUsers: row.unique_users,
    };
  });

  if (!Array.isArray(payload.employees)) fail('data.employees', '배열 필요');
  const employees = payload.employees.map((row, index) => {
    const path = `data.employees[${index}]`;
    exactKeys(row, EMPLOYEE_KEYS, path);
    const userId = stringAt(row.user_id, `${path}.user_id`);
    const displayName = stringAt(row.display_name, `${path}.display_name`);
    const status = stringAt(row.status, `${path}.status`);
    nullableStringAt(row.employee_no, `${path}.employee_no`);
    nullableStringAt(row.department, `${path}.department`);
    ['gross_spend_amount', 'company_charge_amount', 'employee_paid_amount', 'transaction_count', 'spend_count', 'reversal_count', 'usage_days']
      .forEach((key) => integerAt(row[key], `${path}.${key}`));
    return {
      id: userId, name: displayName, employeeNo: row.employee_no, department: row.department,
      status, grossSpendAmount: row.gross_spend_amount, companyChargeAmount: row.company_charge_amount,
      employeePaidAmount: row.employee_paid_amount, transactionCount: row.transaction_count,
      spendCount: row.spend_count, reversalCount: row.reversal_count, usageDays: row.usage_days,
    };
  });

  exactKeys(payload.settlements, SETTLEMENT_KEYS, 'data.settlements');
  SETTLEMENT_KEYS.forEach((key) => integerAt(payload.settlements[key], `data.settlements.${key}`));

  return {
    periodYm,
    timezone,
    period: { ...payload.period },
    summary: {
      grossSpendAmount: payload.summary.gross_spend_amount,
      companyChargeAmount: payload.summary.company_charge_amount,
      employeePaidAmount: payload.summary.employee_paid_amount,
      transactionCount: payload.summary.transaction_count,
      spendCount: payload.summary.spend_count,
      reversalCount: payload.summary.reversal_count,
      uniqueUsers: payload.summary.unique_users,
      totalEmployees: payload.summary.total_employee_count,
      activeEmployees: payload.summary.active_employee_count,
      usedEmployees: payload.summary.used_employee_count,
      outstandingSettlementAmount: payload.summary.outstanding_settlement_amount,
      confirmedPaymentAmount: payload.summary.confirmed_payment_amount,
    },
    daily,
    employees,
    settlements: { ...payload.settlements },
  };
}
