// Pure helpers for the counter scanner page (unit-tested).

const TOKEN_LENGTH = 81;

// The member QR is 81 digits starting with "81". Scanners may add CR/LF,
// AIM ids or other prefixes/suffixes; Korean IME can't affect digits.
export function extractMemberCode(raw) {
  if (typeof raw !== 'string') return null;
  for (const run of raw.match(/\d+/g) || []) {
    const start = run.indexOf('81');
    if (start !== -1 && run.length - start >= TOKEN_LENGTH) return run.slice(start, start + TOKEN_LENGTH);
  }
  return null;
}

const MESSAGES = {
  NO_VOUCHER: ['남은 식권이 없어요', '손님께 식권 구매를 안내해 주세요.'],
  MEAL_QR_EXPIRED: ['QR 시간이 지났어요', '손님 앱에서 새 QR을 띄워 다시 찍어 주세요.'],
  INVALID_MEAL_QR: ['회원 QR이 아니에요', '앱의 QR 탭 → 내 QR 보여주기 화면을 찍어 주세요.'],
  LEDGER_NOT_SUPPORTED: ['장부 결제 회원이에요', '손님이 앱으로 매장 QR을 찍어 결제해 주세요.'],
  ACCOUNT_INACTIVE: ['사용할 수 없는 회원이에요', '관리자에게 문의해 주세요.'],
  FORBIDDEN: ['식당관리자 계정이 아니에요', '식당관리자 계정으로 다시 로그인해 주세요.'],
  UNAUTHENTICATED: ['로그인이 만료됐어요', '다시 로그인해 주세요.'],
  NETWORK: ['연결 오류', '인터넷 연결을 확인하고 다시 찍어 주세요.'],
};

export function counterResultView(ok, payload) {
  if (ok) {
    const d = payload?.data || {};
    const remaining = Number.isSafeInteger(d.remaining) ? d.remaining : null;
    return {
      kind: 'success',
      duplicate: Boolean(d.duplicate),
      title: d.duplicate ? '이미 사용 처리된 QR이에요' : '식권 1장 사용 완료',
      name: d.member_name ? `${d.member_name}님` : '회원',
      remaining,
      detail: d.duplicate ? '같은 QR이 다시 찍혀 추가 차감하지 않았어요.' : remaining == null ? '' : `남은 식권 ${remaining}장`,
    };
  }
  const detail = payload?.detail;
  const code = (detail && typeof detail === 'object' && detail.code) || 'ERROR';
  const [title, text] = MESSAGES[code] || ['사용 처리 실패', (detail && detail.message) || '잠시 후 다시 찍어 주세요.'];
  return { kind: 'error', code, title, detail: text };
}
