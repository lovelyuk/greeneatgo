# DECISIONS.md

스펙과 충돌하거나 사용자 승인이 필요한 결정은 여기에 제안 후 승인받고 구현합니다.

## 확정 결정

| ID | 결정 | 출처 |
|---|---|---|
| D-01 | 개인 현금 충전 미구현 | MEALLEDGER_AGENT_SPEC v2.0 |
| D-02 | 플랫폼 자금 수취/지급 없음 | MEALLEDGER_AGENT_SPEC v2.0 |
| D-03 | 식당 무설치 QR 제시 방식 | MEALLEDGER_AGENT_SPEC v2.0 |
| D-04 | 미사용 포인트 월말 소멸 기본 | MEALLEDGER_AGENT_SPEC v2.0 |
| D-05 | GPS 500m 초과는 차단이 아닌 플래그 | MEALLEDGER_AGENT_SPEC v2.0 |
| D-06 | 결제취소 10분 제한 | MEALLEDGER_AGENT_SPEC v2.0 |
| D-07 | 장부업체 직원 결제는 월 한도 장부를 유지하고, 장부업체 외 일반 사용자는 식당 등록 상품을 토스페이먼츠로 직접 결제 | 2026-07-10 사용자 요청 |
| D-08 | 기존 `test_ck/test_sk` 키에서는 표준 카드 결제창을 사용하고, 결제위젯 키(`gck/gsk`)로 교체하면 v2 결제위젯을 자동 사용 | 토스페이먼츠 v2 키 체계/2026-07-10 구현 |
| D-09 | 식권 구매·통합 QR 결제의 계정 식별은 요청 본문의 `account_id`가 아니라 검증된 Bearer 토큰의 사용자 identity를 사용 | 클라이언트 지정 계정의 IDOR 방지 보안 결정 |
| D-10 | 식권 상품의 100% 할인은 허용하지 않음. Toss Payments 승인 금액은 양의 정수 KRW여야 하므로 할인율은 100% 미만이어야 함 | Toss 결제 제약 및 결제/발급 정합성 |
| D-11 | 직원 관리는 식당 사장님인 `merchant_admin`이 아니라 기존 `company_admin`의 등록된 직원목록에 둔다. `app_users.id`가 `auth.users` FK이므로 인증 전 일괄등록 행은 RLS가 켜진 `employee_bulk_invites`에 보관하고, 직원의 첫 `/join/request`에서만 활성 `app_users`로 원자적으로 전환한다. | 현재 greeneatGo 권한·FK 모델에 맞춘 직원 일괄등록 결정 |
| D-12 | SMS/OTP는 추가하지 않는다. 인증은 Supabase 이메일/비밀번호를 유지하며 Flutter 가입 시 정규화 전화번호를 auth user metadata에 저장한다. 이 전화번호는 SMS 검증값이 아닌 파일럿 매칭 키이므로 API는 유효한 회사 초대코드와 기존 앱 프로필이 전혀 없는 인증 사용자 조건을 함께 요구한다. paused/left/rejected/pending/active 및 고객·관리자 프로필은 일괄초대로 재활성화하거나 덮어쓰지 않는다. | no-SMS 제품 결정 및 계정 탈취/프로필 덮어쓰기 방지 |

## 승인 필요 제안

아직 없음.
