# MASTER_INDEX.md

greeneatGo 프로젝트 작업 인덱스입니다. 완료 시 이 파일을 갱신합니다.

## 문서

- `GREENEATGO_AGENT_SPEC.md` — 단일 진실 공급원(SSOT)
- `DECISIONS.md` — 승인 필요 결정/확정 결정 로그
- `README.md` — 프로젝트 개요와 실행 방법

## 컴포넌트

| 컴포넌트 | 경로 | 현재 상태 |
|---|---|---|
| 고객 앱 | `apps/customer` | 장부업체 직원 QR/월한도 결제와 일반 사용자 토스페이먼츠 상품 결제(WebView) 흐름 구현 |
| 관리자 웹 | `apps/admin` | 역할별 회사/식당/플랫폼 관리 화면과 상품·오늘메뉴 관리 구현 |
| API | `services/api` | FastAPI 정책/가입/장부 결제 및 토스 주문 생성·금액 검증·승인 API 구현 |
| 인프라 | `infra` | Supabase 마이그레이션/seed와 일반 사용자·토스 주문 테이블(`0014`) 추가 |

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
- [ ] Supabase에 `0014_toss_consumer_payments.sql` 배포
- [ ] 토스 테스트 결제 E2E(실제 결제 인증→승인→완료)
- [ ] React 관리자 CRUD/API 연결
- [ ] QR 스티커 PDF 실제 렌더링
