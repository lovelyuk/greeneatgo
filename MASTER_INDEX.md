# MASTER_INDEX.md

greeneatGo 프로젝트 작업 인덱스입니다. 완료 시 이 파일을 갱신합니다.

## 문서

- `GREENEATGO_AGENT_SPEC.md` — 프로젝트 기본 SSOT
- `QR_PAYMENT_UNIFIED_SPEC.md` — 장부/개인식권 통합 QR 결제 최신 스펙
- `VOUCHER_PRODUCT_SPEC.md` — 식권 패키지·할인 상품 최신 스펙
- `DECISIONS.md` — 승인 필요 결정/확정 결정 로그
- `README.md` — 프로젝트 개요와 실행 방법

## 컴포넌트

| 컴포넌트 | 경로 | 현재 상태 |
|---|---|---|
| 고객 앱 | `apps/customer` | 장부 직원·개인 식권 구매자 공용 QR 스캔, 식권 패키지 토스 구매·잔여 식권·사진 메뉴 구현 |
| 관리자 웹 | `apps/admin` | 식당 상품/식권 패키지/오늘 메뉴 사진 업로드, 기간 지정 정산·거래 상세·실시간 결제 알림 구현 |
| API | `services/api` | 장부/식권 통합 QR 분기, 토스 승인·멱등 식권 발급, 사진 업로드, 기간 정산 API 구현 |
| 인프라 | `infra` | `0014` 토스 주문, `0015` 식권/통합 QR, `0016` 사진·기간 정산·Realtime 마이그레이션 추가 |

## M1 체크리스트 매핑

- [x] 모노레포 디렉토리 생성
- [x] SSOT 스펙 복사
- [x] DB 마이그레이션 초안 생성
- [x] API 레이어드 구조 생성
- [x] 정책 엔진 경계 테스트 20케이스 생성 및 통과
- [x] 초대코드 가입승인 DB 마이그레이션 생성
- [x] 가입승인 순수 도메인 로직 및 테스트 생성
- [x] Supabase 웹 `.env` 연결 확인
- [x] `/me`, `/join/request`, `/admin/join-requests` 라우터를 Supabase repository에 연결
- [x] Supabase 웹 seed 데이터 적용 확인
- [x] Supabase Auth 테스트 사용자 → 가입요청 pending → 관리자 승인 active E2E 확인
- [ ] `process_meal_pay` SQL 함수 실 DB 검증
- [x] Flutter 실제 QR/카메라 연동
- [x] 일반 사용자 역할 및 토스페이먼츠 상품 주문·승인·완료 화면 구현
- [x] 토스 승인 전 서버 주문번호/금액 검증 및 승인 결과 저장
- [ ] Supabase에 `0014_toss_consumer_payments.sql` → `0015_voucher_products_and_unified_scan.sql` → `0016_merchant_images_and_settlement_periods.sql` 순서로 배포
- [ ] 토스 테스트 결제 E2E(식권 패키지 결제→낱장 발급→QR FIFO 1장 사용)
- [x] React 관리자 CRUD/API 연결
- [x] 식당 상품·식권 상품·오늘 뷔페 사진 업로드
- [x] 날짜 범위 지정 정산·거래내역 8개 컬럼·다운로드
- [ ] QR 스티커 PDF 실제 렌더링
