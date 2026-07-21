# greeneatGo 현재 아키텍처

## 서비스 구성

```text
Flutter 사용자 앱
  ├─ Supabase Auth: 가입·로그인·비밀번호
  ├─ FastAPI: 프로필·상품·결제·식권·리뷰·기기 토큰
  └─ Firebase: 푸시 수신

React/Vite 관리자 웹
  ├─ Supabase Auth: 관리자 로그인·초대 계정 생성
  ├─ FastAPI: 역할별 관리 API
  └─ Supabase Realtime: 식당 실시간 결제 알림

FastAPI
  ├─ Bearer 토큰 사용자 확인
  ├─ Supabase service role로 신뢰 쓰기
  ├─ 키움페이 결제창·결과통지 검증
  ├─ SendGrid 업체 초대
  └─ Firebase Admin 공지 발송

Supabase PostgreSQL
  ├─ 사용자·회사·식당·계약
  ├─ 장부·식권·포인트 원장
  ├─ 정산·공지·리뷰·알림 이력
  └─ RLS와 SECURITY DEFINER RPC
```

## 역할 모델

| 역할 | 핵심 권한 |
|---|---|
| `employee` | 회사 한도 내 장부 결제, 지원 식권과 포인트 사용 |
| `customer` | 개인 식권 구매·보유·QR 사용 |
| `company_admin` | 소속 직원, 가입 승인, 한도, 포인트, 식사시간 관리 |
| `merchant_admin` | 자기 식당의 업체 계약, 상품, 식권, 메뉴, 거래, 정산, 알림 관리 |
| `platform_admin` | 식당과 식당관리자 온보딩 |

클라이언트가 보낸 `account_id`, 회사 ID, 식당 ID를 권한의 근거로 사용하지 않습니다. FastAPI가 Bearer 토큰의 사용자와 DB 관계를 해석합니다.

## 결제 모델

### 회사 장부 결제

```text
employee 로그인
→ 매장 QR 스캔
→ API가 회사·식당 계약과 정책 확인
→ 월 한도 장부 거래 기록
→ 회사가 식당에 직접 정산
```

직원 식대는 선불 잔액 차감이 아닙니다. `meal_transactions`를 기반으로 월 이용액과 정산액을 계산합니다.

### 일반 사용자 식권

```text
customer가 식권 상품 선택
→ 서버가 주문번호·금액 생성
→ 키움페이 승인
→ 서버가 승인 금액 재검증
→ 식권을 낱장으로 원자 발급
→ 매장 QR에서 FIFO로 1장 사용
```

구매 주문과 매장 사용 거래는 구분합니다. 식권 구매액은 회사 정산에 포함하지 않습니다.

### 지원 식권과 포인트

```text
merchant_admin이 회사별 지원 계약 설정
→ employee가 지원 가격 조회
→ 포인트 예약 + 필요 시 키움페이 카드 결제
→ 승인 완료 후 지원금 스냅샷과 식권 발급
→ QR 사용 시 회사 부담분만 회사 미수/정산에 반영
```

- 회사 지원금은 식권 사용 시 회사 정산 대상으로 발생합니다.
- 식당 지원금은 할인으로 기록하되 회사에 청구하지 않습니다.
- 회사관리자만 자기 직원의 포인트를 충전·조정합니다.
- 포인트 변경은 `point_transactions` 감사 내역에 기록합니다.

## 관리자 웹 화면 분기

관리자 웹은 로그인 후 `/me`가 반환한 역할이 확인될 때까지 대시보드를 노출하지 않습니다.

- 업체관리자: 직원·가입·한도·포인트·정책
- 식당관리자: 실시간 피드·QR·업체·계약·거래·정산·상품·메뉴·공지·리뷰
- 플랫폼관리자: 식당 등록·관리자 초대

## 데이터와 감사 원칙

- 금액·단가·지원금·상품명은 거래 시점 값으로 스냅샷합니다.
- 키움페이 주문 완료와 식권 발급은 멱등성을 유지해야 합니다.
- 원장·포인트·정산 데이터를 원인 확인 전에 삭제하지 않습니다.
- 이미지 교체는 Storage와 DB가 완전한 단일 트랜잭션이 아니므로 참조 확인 후 이전 파일을 정리합니다.
- 운영 DB의 실제 마이그레이션 적용 상태를 파일 목록만으로 추정하지 않습니다.

## 주요 코드 위치

| 영역 | 위치 |
|---|---|
| Flutter 화면·API 클라이언트 | `apps/customer/lib/main.dart` |
| Flutter FCM | `apps/customer/lib/push_notifications.dart` |
| 관리자 웹 | `apps/admin/src/main.jsx` |
| 관리자 스타일 | `apps/admin/src/style.css` |
| API 라우터 | `services/api/app/routers` |
| API 서비스 | `services/api/app/services` |
| Supabase 접근 | `services/api/app/repositories` |
| DB 변경 | `infra/migrations` |
| API 테스트 | `services/api/tests` |
