# greeneatGo 문서 인덱스

현재 코드 기준 문서만 연결합니다. 구현 전 초안 스펙은 삭제했으며, 코드·마이그레이션·확정 결정이 현재 기준입니다.

## 핵심 문서

| 문서 | 용도 |
|---|---|
| [README.md](README.md) | 프로젝트 개요, 로컬 실행, 검증 명령 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 현재 역할·서비스·결제·데이터 구조 |
| [docs/CURRENT_STATUS.md](docs/CURRENT_STATUS.md) | 구현 완료 상태, 실제 검증, 남은 위험 |
| [docs/OPERATIONS_CHECKLIST.md](docs/OPERATIONS_CHECKLIST.md) | 배포 전후 운영 점검표 |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Vercel·Render·Flutter 배포 |
| [SETUP_SUPABASE_WEB.md](SETUP_SUPABASE_WEB.md) | Supabase 환경·마이그레이션 적용 |
| [docs/FIREBASE_PUSH_SETUP.md](docs/FIREBASE_PUSH_SETUP.md) | 앱·서버 FCM 설정과 실기기 QA |
| [DECISIONS.md](DECISIONS.md) | 확정된 제품·권한·결제 결정 |

## 사용자 설명서

- [설명서 목록](docs/user-guides/README.md)
- [업체관리자 웹](docs/user-guides/company-admin-web-guide.md)
- [식당관리자 웹](docs/user-guides/merchant-admin-web-guide.md)
- [사용자 앱](docs/user-guides/customer-app-guide.md)

## 보조 문서

- [Supabase 인증 이메일 한글화](docs/SUPABASE_AUTH_EMAIL_KO.md)
- [사용자 앱 개발·빌드](apps/customer/README.md)
- [브랜드 자산](apps/customer/assets/brand/README.md)

## 구현 컴포넌트

| 컴포넌트 | 경로 | 현재 책임 |
|---|---|---|
| 사용자 앱 | `apps/customer` | 가입·로그인, 장부/식권 QR, 키움페이, 포인트, 공지·리뷰, FCM |
| 관리자 웹 | `apps/admin` | 회사·식당·플랫폼 역할별 관리 화면 |
| API | `services/api` | 인증, 결제, 발급, 사용, 정산, 이미지, 알림, 초대 |
| DB | `infra/migrations` | PostgreSQL 스키마, RLS, RPC, 감사 원장 |

## 현재 릴리스 게이트

- [ ] 새 개발 Supabase에 `0001~0030` 순서대로 적용
- [ ] 새 개발 DB의 포인트 전액 주문(`amount=0`) 검증
- [ ] 키움페이 sandbox 구매→발급→QR 사용→취소/환불 E2E
- [ ] 장부 결제 한도 검사를 DB 잠금 내부에서 원자화
- [ ] 정산 2,000건 상한과 감사 이력 보강
- [ ] Firebase 실기기 전면·백그라운드·종료 수신 검증
- [ ] Android 운영 keystore로 release 서명
- [ ] API·웹·Flutter·DB 마이그레이션 CI 구성

상세 내용은 [현재 상태](docs/CURRENT_STATUS.md)와 [운영 체크리스트](docs/OPERATIONS_CHECKLIST.md)를 사용합니다.
