// 사업자 정보 (전자상거래법 표시사항) shown in the /shop footer.
// Must match the "사업자 정보" table in public/terms.html — test/businessInfo.test.js checks it.
export const BUSINESS_INFO = Object.freeze({
  name: '그린잇',
  representative: '오안식',
  bizRegNo: '601-85-17320',
  mailOrderNo: '2025-서울금천-1242',
  address: '서울특별시 금천구 가산디지털1로 145, 3차동 지하1층 B108~B111호(가산동, 에이스하이엔드타워3차)',
  email: 'greeneat0419@naver.com',
  phone: '1555-5952',
});

export const BUSINESS_INFO_ROWS = Object.freeze([
  ['상호', BUSINESS_INFO.name],
  ['대표자', BUSINESS_INFO.representative],
  ['사업자등록번호', BUSINESS_INFO.bizRegNo],
  ['통신판매업신고', BUSINESS_INFO.mailOrderNo],
  ['주소', BUSINESS_INFO.address],
  ['이메일', BUSINESS_INFO.email],
  ['고객센터', BUSINESS_INFO.phone],
]);
