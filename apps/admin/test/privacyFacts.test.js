import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { legalDocumentsReady } from '../src/purchaseSafety.js';
const privacy = readFileSync(new URL('../public/privacy.html', import.meta.url), 'utf8');
const terms = readFileSync(new URL('../public/terms.html', import.meta.url), 'utf8');
const contains = values => values.forEach(value => assert.ok(privacy.includes(value), `Missing: ${value}`));
test('privacy separates required web credentials and personal/employee profiles', () => {
  contains(['웹 가입·로그인 필수: 이메일, 비밀번호', 'Supabase Authentication', '개인 구매자 프로필: 이름, 휴대전화번호', '임직원 가입·소속 관리: 이름, 휴대전화번호, 소속 회사/부서']);
  assert.ok(!privacy.includes('선택: 이메일'));
});
test('privacy describes SOLAPI OTP then Firebase custom-token, not Phone-provider SMS', () => {
  contains(['SOLAPI', 'OTP', 'Firebase Authentication custom-token', 'Firebase Phone-provider SMS 방식이 아닙니다']);
});
test('privacy distinguishes full callback CARDNO from masked application storage and unknown logs', () => {
  contains(['전체 카드번호(CARDNO)', '마지막 4자리', '마스킹', '인프라 로그의 수집·마스킹·보관 여부는 확인 중']);
  assert.ok(!privacy.includes('카드번호 등 결제수단 정보는 결제대행사(키움페이)가 직접 수집·처리하며 서비스는 저장하지 않습니다'));
});
test('privacy identifies company/merchant access without certifying no third-party disclosure', () => {
  contains(['소속 회사 관리자', '가맹 식당 관리자', '제3자 제공 또는 처리위탁', '계약과 운영 관계']);
  assert.ok(!privacy.includes('서비스는 정보주체의 동의 없이 개인정보를 제3자에게 제공하지 않습니다'));
});
test('privacy publishes bounded Seoul/Oregon/Auth facts with pending additional disclosure', () => {
  contains(['확인된 주 처리지역 / 추가 고지 확인 중', 'Supabase greeneat-go 프로젝트', '대한민국 서울', 'Northeast Asia (Seoul)', 'ap-northeast-2', '운영 호스트와의 정확한 매핑은 추가 확인 중', '백업·로그·지원 접근까지 모두 국내라는 의미는 아닙니다', 'Render API', 'Oregon (US West)', '미국', 'Firebase Authentication', 'href="https://firebase.google.com/support/privacy"', 'FCM의 처리국가 전체는 확인 중', 'Vercel', '실제 계약 당사자', '이전 항목·국가·시기·방법·목적·보유기간', '거부 방법·절차·효과']);
});
test('privacy leaves retention/cloud/log/country TODOs and signup/purchase gate closed', () => {
  contains(['【클라우드/호스팅 사업자】', 'TODO', '로그', '보유기간', '처리국가']);
  assert.equal(legalDocumentsReady([terms, privacy]), false);
});
test('both legal pages use existing system fallback without automatic external fonts/styles', () => {
  for (const html of [privacy, terms]) {
    assert.ok(!/cdn\.jsdelivr\.net|@import|@font-face|rel="stylesheet"|<script\b/i.test(html));
    assert.ok(html.includes('-apple-system,BlinkMacSystemFont,system-ui'));
    assert.ok(html.includes('"Apple SD Gothic Neo","Malgun Gothic",sans-serif'));
  }
});
