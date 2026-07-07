# MASTER_INDEX.md

greeneatGo 프로젝트 작업 인덱스입니다. 완료 시 이 파일을 갱신합니다.

## 문서

- `GREENEATGO_AGENT_SPEC.md` — 단일 진실 공급원(SSOT)
- `DECISIONS.md` — 승인 필요 결정/확정 결정 로그
- `README.md` — 프로젝트 개요와 실행 방법

## 컴포넌트

| 컴포넌트 | 경로 | 현재 상태 |
|---|---|---|
| 직원 앱 | `apps/customer` | Flutter 앱 골격/핵심 화면 placeholder 생성 |
| 관리자 웹 | `apps/admin` | React/Vite/Tailwind 앱 골격/주요 라우트 placeholder 생성 |
| API | `services/api` | FastAPI 구조, 정책 엔진/가입승인 순수 함수, 결제 서비스 골격, unittest 생성 |
| 인프라 | `infra` | 초기 DB 마이그레이션, 초대코드/가입승인 테이블, RLS 요약 SQL, 파일럿 seed SQL 생성 |

## M1 체크리스트 매핑

- [x] 모노레포 디렉토리 생성
- [x] SSOT 스펙 복사
- [x] DB 마이그레이션 초안 생성
- [x] API 레이어드 구조 생성
- [x] 정책 엔진 경계 테스트 20케이스 생성 및 통과
- [x] 초대코드 가입승인 DB 마이그레이션 생성
- [x] 가입승인 순수 도메인 로직 및 테스트 생성
- [ ] Supabase self-hosted 연결
- [ ] `process_meal_pay` SQL 함수 실 DB 검증
- [ ] Flutter 실제 QR/카메라 연동
- [ ] React 관리자 CRUD/API 연결
- [ ] QR 스티커 PDF 실제 렌더링
