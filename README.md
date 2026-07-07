# greeneatGo (밥장부)

회사 주변 식당의 종이 장부를 앱으로 대체하는 B2B 식대 관리 SaaS입니다.

## 핵심 원칙

- 플랫폼은 돈을 만지지 않습니다. 회사가 식당에 직접 송금하고, greeneatGo는 정산 데이터만 제공합니다.
- 개인 현금 충전/실 PG/카드 연동은 구현하지 않습니다.
- 식대 포인트는 append-only 원장(`meal_transactions`)으로만 기록합니다.
- 결제/지급/조정 쓰기는 FastAPI service-role 경유만 허용합니다.

## 모노레포 구조

```text
apps/customer      Flutter 직원 앱
apps/admin         React 관리자/운영자/식당조회 웹
services/api       FastAPI 백엔드
infra/migrations   Supabase/Postgres SQL
infra/seed         파일럿 시드 데이터
```

## 현재 생성 상태

초기 M1 골격과 정책 엔진 테스트를 포함합니다. 실제 Supabase 연결, Flutter/React 의존성 설치, 배포 설정은 다음 작업에서 연결합니다.

## 빠른 검증

```bash
cd /mnt/d/projects/greeneatGo/services/api
python3 -m unittest discover -s tests -v
```


## 가입승인 흐름

M1 기본 가입 방식은 `초대코드 입력 → pending 가입요청 → 회사관리자 승인 → active 직원`입니다.

- 초대코드 테이블: `company_invite_codes`
- 직원 상태: `pending`, `active`, `paused`, `left`, `rejected`
- 감사 로그: `employee_join_audit_logs`

FastAPI는 `services/api/.env`의 Supabase 웹 프로젝트 값으로 service_role repository에 연결합니다.
