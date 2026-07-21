# Supabase Web 설정과 마이그레이션

이 프로젝트는 Supabase Auth, PostgreSQL, Realtime, Storage를 사용합니다.

## 1. 키 사용 경계

| 값 | API | 관리자 웹 | Flutter |
|---|---:|---:|---:|
| Project URL | O | O | O |
| anon key | O | O | O |
| service role key | O | X | X |
| JWT secret | 선택 | X | X |

`service_role`은 RLS를 우회할 수 있으므로 서버 환경변수에만 저장합니다.

## 2. 환경변수

### FastAPI

`services/api/.env.example`을 복사합니다.

```bash
cd services/api
cp .env.example .env
```

최소 필수값:

```dotenv
SUPABASE_URL=https://PROJECT.supabase.co
SUPABASE_ANON_KEY=...
SUPABASE_SERVICE_ROLE_KEY=...
KIWOOMPAY_CPID=...
KIWOOMPAY_AUTHORIZATION_KEY=...
KIWOOMPAY_BASE_URL=https://apitest.kiwoompay.co.kr
```

### 관리자 웹

```bash
cd apps/admin
cp .env.example .env
```

```dotenv
VITE_SUPABASE_URL=https://PROJECT.supabase.co
VITE_SUPABASE_ANON_KEY=...
VITE_API_BASE_URL=http://localhost:8000/v1
VITE_AUTH_EMAIL_REDIRECT_TO=https://greeneatgo-api.onrender.com/v1/auth/confirmed
```

Flutter release 스크립트도 이 파일의 공개 설정을 사용합니다.

## 3. 마이그레이션 원칙

- 개발 DB는 기존 프로젝트를 승계하지 않고 새 Supabase 프로젝트에 번호순으로 모두 적용합니다.
- 이전 PG 스키마의 rename/호환 마이그레이션은 사용하지 않습니다.
- SQL Editor에서 중간 실패하면 일부 문장만 반영될 수 있으므로 결과를 반드시 검증합니다.
- `0003_process_meal_pay_stub.sql`은 초기 골격이며 최종 결제 함수가 아닙니다. 반드시 `0029`까지 모두 적용합니다.

## 4. 현재 마이그레이션 순서

```text
0001_initial.sql
0002_rls_policies.sql
0003_process_meal_pay_stub.sql
0004_invite_join_approval.sql
0005_merchant_products.sql
0006_merchant_daily_menus.sql
0007_merchant_admins.sql
0008_mealledger_v23.sql
0009_process_meal_pay.sql
0010_merchant_company_contract.sql
0011_employee_monthly_limit.sql
0012_process_meal_pay_no_balance_check.sql
0013_rename_pilot_merchant_to_donto.sql
0014_consumer_payments.sql
0015_voucher_products_and_unified_scan.sql
0016_merchant_images_and_settlement_periods.sql
0017_employee_bulk_invites.sql
0018_remove_legacy_pilot_name.sql
0019_daily_menu_schedule_cleanup.sql
0020_voucher_product_events.sql
0021_app_users_self_update_hardening.sql
0022_push_notifications.sql
0023_subsidized_ledger.sql
0024_company_point_wallet.sql
0025_announcements_reviews.sql
0026_company_invite_email.sql
0027_allow_point_only_orders.sql
0028_refunds_and_payment_analytics.sql
0029_public_table_rls_hardening.sql
```

`0014`부터 결제 스키마는 `payment_orders`, `provider_payment_key`, `provider_response`를 직접 생성합니다. 이전 PG 전용 테이블이나 호환 마이그레이션은 포함하지 않습니다.

## 5. 신규 프로젝트 적용

Supabase CLI를 사용하는 경우 프로젝트를 연결한 뒤 마이그레이션 체계를 정식으로 관리하는 방법을 권장합니다. 현재 파일이 Supabase CLI 기본 디렉터리 형식과 다르면, 자동 실행 전에 별도 staging 프로젝트에서 검증합니다.

SQL Editor를 사용하는 경우:

1. 파일을 번호순으로 엽니다.
2. 각 파일 적용 결과를 기록합니다.
3. 오류가 나면 다음 파일로 넘어가지 않습니다.
4. 테이블·함수·제약·권한을 확인합니다.
5. 모든 적용 후 API 테스트와 역할별 E2E를 실행합니다.

파일럿 seed가 필요한 경우에만 `infra/seed`를 검토합니다. 운영 프로젝트에 테스트 seed를 자동 적용하지 않습니다.

## 6. Auth 설정

Supabase Dashboard:

```text
Authentication → Providers → Email
```

- 이메일/비밀번호 로그인을 활성화합니다.
- SMS/Phone OTP는 사용하지 않습니다.
- 가입 즉시 세션이 필요한 관리자 초대 흐름은 Email Confirm 정책과 충돌하지 않는지 확인합니다.
- 사용자 앱의 일반 가입 이메일 확인 흐름은 운영 Redirect URL을 사용합니다.

URL Configuration:

```text
Site URL: https://greeneatgo-api.onrender.com
Additional Redirect URL: https://greeneatgo-api.onrender.com/v1/auth/confirmed
```

## 7. Storage

상품·메뉴·리뷰 이미지 기능을 사용하려면 코드가 기대하는 버킷과 정책을 실제 프로젝트에 구성해야 합니다.

확인 항목:

- 허용 MIME과 크기
- 공개 URL 정책
- 식당별 경로 분리
- 교체 전 기존 DB 참조 확인
- 삭제 후 Storage 목록에서 실제 제거 확인

## 8. 배포 후 필수 검증

- [ ] anon 사용자에게 service-role 전용 테이블 직접 쓰기 불가
- [ ] authenticated 사용자가 다른 회사·식당 데이터 변경 불가
- [ ] service role RPC는 API에서 정상 호출
- [ ] 최신 `process_meal_pay` 함수 정의
- [ ] 월 한도와 식사 시간 정책
- [ ] 키움페이 주문 금액 제약
- [ ] `amount=0` 포인트 전액 주문
- [ ] 일반 식권 원자 발급·FIFO 사용
- [ ] 지원 식권과 포인트 예약·확정·해제
- [ ] 기기 토큰과 공지·리뷰 테이블

## 9. 운영 변경 기록

마이그레이션을 적용할 때 다음을 남깁니다.

```text
적용 파일
적용 시각
대상 프로젝트
적용자
백업/PITR 상태
검증 쿼리 결과
관련 Git 커밋
```

파일이 저장소에 있다는 사실만으로 운영 DB에 적용됐다고 기록하지 않습니다.
