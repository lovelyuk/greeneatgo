// Pure helpers for the counter scanner page (unit-tested).

const TOKEN_LENGTH = 81;

// 81 = one meal, 82 = one personal voucher, 83/84 = the same for several meals.
const VERSIONS = new Set(['81', '82', '83', '84']);

// The member QR is 81 digits starting with a version above. Scanners may add
// CR/LF, AIM ids or other prefixes/suffixes; Korean IME can't affect digits.
export function extractMemberCode(raw) {
  if (typeof raw !== 'string') return null;
  for (const run of raw.match(/\d+/g) || []) {
    for (let start = 0; run.length - start >= TOKEN_LENGTH; start += 1) {
      if (VERSIONS.has(run.slice(start, start + 2))) return run.slice(start, start + TOKEN_LENGTH);
    }
  }
  return null;
}

// Tap&Pick kiosk paper receipt: 24 hex chars (receipt issue number), optional
// AIM prefix like "]Q1". Must not be confused with the 81-digit member QR.
export function extractKioskReceipt(raw) {
  if (typeof raw !== 'string') return null;
  const m = raw.trim().match(/^(?:\][A-Za-z]\d)?([0-9a-fA-F]{24})$/);
  return m ? m[1].toLowerCase() : null;
}

/** Decide what a scan is: member QR, kiosk receipt, or nothing. */
// One scanner keystroke -> the character it stands for ('' = not part of a code).
// With a Korean/Japanese IME active the browser reports key "Process", so fall
// back to the physical key (`code`) for digits and letters.
export function scanKeyChar(event) {
  const key = event?.key ?? '';
  if (key.length === 1) return key === ' ' ? '' : key;
  if (key !== 'Process' && key !== 'Unidentified') return '';
  const code = event?.code ?? '';
  const digit = /^(?:Digit|Numpad)(\d)$/.exec(code);
  if (digit) return digit[1];
  const letter = /^Key([A-Z])$/.exec(code);
  if (letter) return event.shiftKey ? letter[1] : letter[1].toLowerCase();
  return '';
}

// A scanner keeps re-reading a QR that is held in front of it. A code that was
// just used is ignored for this long after it was last seen, so the "used"
// screen is not replaced by an "already used" warning.
export const REPEAT_SCAN_IGNORE_MS = 10000;

/** True when `code` is the code just used and it was last seen within the window. */
export function isRepeatScan(last, code, now, windowMs = REPEAT_SCAN_IGNORE_MS) {
  return Boolean(last) && last.code === code && now - last.at >= 0 && now - last.at < windowMs;
}

export function classifyScan(raw) {
  const member = extractMemberCode(raw);
  if (member) return { kind: 'member', code: member };
  const receipt = extractKioskReceipt(raw);
  if (receipt) return { kind: 'kiosk', code: receipt };
  return null;
}

const MESSAGES = {
  NO_VOUCHER: ['남은 식권이 없어요', '손님께 식권 구매를 안내해 주세요.'],
  NOT_ENOUGH_VOUCHERS: ['식권이 모자라요', '사용 처리하지 않았어요. 손님 앱에서 수량을 줄여 다시 찍어 주세요.'],
  MEAL_QR_EXPIRED: ['QR 시간이 지났어요', '손님 앱에서 새 QR을 띄워 다시 찍어 주세요.'],
  INVALID_MEAL_QR: ['회원 QR이 아니에요', '앱의 QR 탭 → 내 QR 보여주기 화면을 찍어 주세요.'],
  LEDGER_NOT_SUPPORTED: ['장부 결제 회원이에요', '손님이 앱으로 매장 QR을 찍어 결제해 주세요.'],
  MONTHLY_LIMIT: ['회사 식대 월 한도를 넘었어요', '손님 앱에서 내 식권으로 바꿔 다시 찍어 주세요.'],
  DAILY_LIMIT: ['회사 식대 하루 한도를 넘었어요', '손님 앱에서 내 식권으로 바꿔 다시 찍어 주세요.'],
  DAILY_COUNT_LIMIT: ['오늘 회사 식대 횟수를 넘었어요', '손님 앱에서 수량을 줄이거나 내 식권으로 바꿔 다시 찍어 주세요.'],
  INVALID_QUANTITY: ['수량을 확인해 주세요', '한 번에 1~10장까지 사용할 수 있어요.'],
  MIGRATION_REQUIRED: ['여러 장 사용은 준비 중이에요', '손님 앱에서 1장으로 바꿔 다시 찍어 주세요.'],
  MEAL_LIMIT: ['회사 식대 한도를 넘었어요', '손님 앱에서 내 식권으로 바꿔 다시 찍어 주세요.'],
  OUT_OF_WINDOW: ['회사 식대 사용 시간이 아니에요', '손님 앱에서 내 식권으로 바꿔 다시 찍어 주세요.'],
  WEEKEND_BLOCKED: ['주말에는 회사 식대를 쓸 수 없어요', '손님 앱에서 내 식권으로 바꿔 다시 찍어 주세요.'],
  NOT_AFFILIATED: ['제휴 회사 직원이 아니에요', '이 식당과 계약된 회사의 직원만 회사 장부로 결제할 수 있어요.'],
  COMPANY_NOT_ACTIVE: ['회사가 아직 활성화되지 않았어요', '회사 담당자 확인이 필요해요.'],
  ACCOUNT_INACTIVE: ['사용할 수 없는 회원이에요', '관리자에게 문의해 주세요.'],
  FORBIDDEN: ['식당관리자 계정이 아니에요', '식당관리자 계정으로 다시 로그인해 주세요.'],
  UNAUTHENTICATED: ['로그인이 만료됐어요', '다시 로그인해 주세요.'],
  NETWORK: ['연결 오류', '인터넷 연결을 확인하고 다시 찍어 주세요.'],
  KIOSK_RECEIPT_USED: ['이미 사용된 영수증이에요', '영수증 1장은 한 번만 사용할 수 있어요.'],
  KIOSK_RECEIPT_INVALID: ['사용할 수 없는 영수증이에요', '키오스크에서 확인되지 않는 영수증이에요. 손님께 영수증을 확인해 주세요.'],
  KIOSK_UNAVAILABLE: ['영수증을 확인하지 못했어요', '키오스크 서버 연결이 원활하지 않아요. 잠시 후 다시 찍어 주세요.'],
  KIOSK_NOT_CONFIGURED: ['키오스크 영수증 준비 중', '아직 키오스크 영수증 사용이 연결되지 않았어요.'],
  INVALID_KIOSK_RECEIPT: ['키오스크 영수증이 아니에요', '영수증의 QR을 다시 찍어 주세요.'],
};

export function counterResultView(ok, payload) {
  if (ok) {
    const d = payload?.data || {};
    if (d.kind === 'kiosk_receipt') {
      return {
        kind: 'success',
        duplicate: false,
        receipt: true,
        title: '키오스크 식권 사용 완료',
        name: '영수증 식권',
        remaining: null,
        detail: `영수증 …${String(d.receipt_id || '').slice(-6)}`,
      };
    }
    // How many meals this one scan paid for (the diner picks it in the app).
    const quantity = Number.isSafeInteger(d.quantity) && d.quantity >= 1 ? d.quantity : 1;
    if (d.pay_type === 'ledger') {
      // A company-ledger employee showed their QR: the company pays, no voucher count.
      const amount = Number.isSafeInteger(d.amount) ? `${d.amount.toLocaleString('ko-KR')}원` : '';
      return {
        kind: 'success',
        duplicate: Boolean(d.duplicate),
        ledger: true,
        quantity,
        title: d.duplicate ? '이미 사용 처리된 QR이에요' : quantity > 1 ? `회사 장부 ${quantity}끼 결제 완료` : '회사 장부 결제 완료',
        name: d.member_name ? `${d.member_name}님` : '회원',
        remaining: null,
        detail: d.duplicate ? '같은 QR이 다시 찍혀 추가 결제하지 않았어요.' : [d.company_name, amount].filter(Boolean).join(' · '),
      };
    }
    const remaining = Number.isSafeInteger(d.remaining) ? d.remaining : null;
    return {
      kind: 'success',
      duplicate: Boolean(d.duplicate),
      quantity,
      title: d.duplicate ? '이미 사용 처리된 QR이에요' : `식권 ${quantity}장 사용 완료`,
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

/** One line of the counter's recent list. */
export function counterHistoryText(entry) {
  if (entry.receipt) return '키오스크 영수증';
  if (entry.duplicate) return '중복 스캔';
  const count = entry.quantity > 1 ? `${entry.quantity}${entry.ledger ? '끼' : '장'} · ` : '';
  return entry.ledger ? `${count}회사 장부` : `${count}남은 식권 ${entry.remaining ?? '—'}장`;
}
