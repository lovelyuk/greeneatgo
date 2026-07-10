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

## 승인 필요 제안

아직 없음.
