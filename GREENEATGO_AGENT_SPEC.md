# GREENEATGO_AGENT_SPEC.md (v2.0)

> **모바일 식대 장부 플랫폼 — AI 에이전트 위임용 마스터 스펙**
> 벤치마크: 식권대장(벤디스), 식신e식권 / 전신: SNACKBOX_AGENT_SPEC v1.0 (무인 쇼케이스 — 보류, 본 문서가 우선)
> 작성일: 2026-07-07 / 코드네임: **greeneatGo** (가칭 "밥장부")

---

## 0. 이 문서를 읽는 에이전트에게

- 이 문서가 **단일 진실 공급원(SSOT)** 이다. 스펙과 충돌하는 결정이 필요하면 `DECISIONS.md`에 제안을 기록하고 사용자 승인을 받는다.
- v1(SnackBox)에서 확정된 설계 원칙(원장 방식, 서버 경유 쓰기, RLS)은 그대로 계승한다. 기기/재고 관련 내용은 전부 폐기.
- 커밋 컨벤션: `[컴포넌트] 요약` — 예: `[customer] QR 스캔 결제 플로우`, `[api] 식대 정책 엔진`
- **금지사항**: ① 개인 현금 충전 기능 구현 금지(선불전자지급수단 규제 — D-01) ② 장부업체 직원 결제의 플랫폼 명의 대금 수취/지급 코드 작성 금지(PG 규제 — D-02). 단, 장부업체 외 일반 사용자의 식당 상품 구매는 D-07에 따라 토스페이먼츠 직접 결제를 사용한다.
- 완료 시 `MASTER_INDEX.md` 갱신 후 종료.

---

## 1. 프로젝트 개요

### 1.1 한 줄 정의
회사 주변 식당의 **종이 장부를 앱으로 대체**하는 B2B 식대 관리 SaaS. 직원은 매장 QR을 스캔해 결제하고, 식당은 아무것도 설치하지 않으며, 회사는 월말에 정산 데이터를 받아 식당에 직접 송금한다.

### 1.2 확정된 핵심 설계 (사용자 결정 반영)
| 항목 | 결정 |
|---|---|
| 식당 결제 확인 | **(C) 매장 비치 QR 스캔 → 앱에서 금액 입력 → 결제완료 화면을 직원(사장님)에게 제시** — 식당 무설치 |
| 돈의 흐름 | **(가) 정산 데이터만 제공** — 회사 → 식당 직접 송금. 플랫폼은 자금을 만지지 않는 SaaS. 수수료 대금중개(나)는 백로그 |
| 식대 재원 | 회사가 설정한 직원별 월 식대 한도 기반 장부. 플랫폼 선충전/개인 충전 없음 |

### 1.3 핵심 사용자 시나리오
1. **직원 결제**: 점심시간에 제휴식당 방문 → 테이블/카운터의 QR 스캔 → 금액 입력(예: 9,000원) → 정책 검증(시간대·1식 한도·월 한도) → 결제완료 화면(애니메이션+실시간 시계)을 직원에게 제시 → 식사
2. **회사(총무)**: 직원별 월 식대 한도 설정/조정 → 실시간 사용 현황/부서별 통계 확인 → 월말 식당별 정산서 다운로드 → 각 식당에 계좌이체 → 앱에서 "송금 완료" 체크
3. **식당**: 종이 장부 대신 카운터에 QR 스티커 부착 → (선택) 문자로 받은 매직링크로 오늘 결제 내역 조회 → 월말 정산서 기준 입금 확인
4. **일반 사용자 결제**: 회사 장부에 속하지 않은 사용자는 일반 사용자로 가입 → 식당 등록 상품 선택 → 토스페이먼츠 결제 인증·서버 승인 → 결제완료 화면을 제시하고 식당 이용
5. **함께결제(M2)**: 팀 점심 시 대표 1인이 참석자를 선택 → 참석자 포인트 합산 한도 내 결제

### 1.4 부정사용 방지 설계 (C 방식의 약점 보강)
결제완료 화면 위조가 유일한 공격 벡터이므로 다층 방어:
- **서버 발급 거래**: 완료 화면은 서버 응답 후에만 렌더 (스크린샷 대비 ↓)
- **실시간 요소**: 서버 시각 기반 움직이는 타임스탬프 + 파형 애니메이션 + 결제음 (정지 이미지 판별)
- **매장명·금액 대형 표시** + 6자리 거래번호
- **위치 검증**: QR 스캔 시 GPS와 매장 좌표 거리 체크 (500m 초과 시 경고 플래그, 차단은 안 함 — 오탐 고려)
- **사후 검증**: 식당 매직링크 페이지에서 당일 내역 실시간 확인 가능 → 월말 정산서와 대조. 이상 거래는 회사 관리자 화면에 플래그
- 시간대 외 결제·1식 한도 초과는 정책 엔진이 사전 차단

### 1.5 비(非)목표 (Out of Scope)
- 배달/픽업 주문, 메뉴판·주문 연동 (금액 입력만)
- 장부업체 직원 결제의 플랫폼 대금 수취·지급 (D-02). 일반 사용자 상품 구매의 토스페이먼츠 결제는 D-07 예외
- 사장님 전용 앱 (매직링크 웹으로 대체)
- 구내식당 솔루션, 세금계산서 자동 발행 (M3+ 백로그)

---

## 2. 시스템 아키텍처

```
┌──────────────┐  REST + Realtime   ┌─────────────────────┐
│ 직원 앱       │◄──────────────────►│ FastAPI              │
│ (Flutter)     │                    │  - 결제 트랜잭션      │
│  - QR 스캔    │                    │  - 정책 엔진          │
│  - 결제완료화면│                    │  - 정산 배치          │
└──────────────┘                    └─────────┬───────────┘
┌──────────────┐                              │ supabase-py
│ 회사 관리자 웹 │──── REST ──────────► ┌───────▼────────────┐
│ (React)       │                     │ Supabase (셀프호스팅)│
└──────────────┘                     │  - Postgres          │
┌──────────────┐                     │  - Auth              │
│ 식당 조회 페이지│◄─ 매직링크(읽기전용)─│  - Realtime(사용현황) │
│ (React, 무로그인)│                   └─────────────────────┘
└──────────────┘
┌──────────────┐
│ 플랫폼 운영자 웹│  (회사/식당 온보딩, QR 발급 — 회사 관리자 웹에 role로 통합)
└──────────────┘
```

### 2.1 컴포넌트 목록
| 컴포넌트 | 코드명 | 기술 | 디렉토리 |
|---|---|---|---|
| 직원 앱 | `customer` | Flutter 3.x | `/apps/customer` |
| 관리자 웹 (회사 총무 + 플랫폼 운영자, role 분리) | `admin` | React + Vite + Tailwind + shadcn/ui | `/apps/admin` |
| 식당 조회 페이지 | `merchant-view` | admin 내 라우트로 구현 (`/m/{token}`) | `/apps/admin` |
| API | `api` | FastAPI (Python 3.12), 레이어드 | `/services/api` |
| 인프라 | `infra` | Supabase self-hosted, SQL 마이그레이션 | `/infra` |

### 2.2 설계 원칙 (v1 계승)
1. 포인트/식대는 **append-only 원장** (`meal_transactions`). 잔액 직접 UPDATE 금지.
2. 결제·지급·조정 쓰기는 **FastAPI(service_role) 경유만**. 클라이언트 직접 insert 금지.
3. 정책 검증(시간대/한도/잔액)은 서버에서 최종 판정. 앱의 사전 검증은 UX용.
4. 모든 결제는 `idempotency_key`로 중복 방지 (네트워크 재시도 대비).

---

## 3. 기술 스택 & 모노레포

v1과 동일 스택. 구조:
```
mealledger/
├── GREENEATGO_AGENT_SPEC.md
├── DECISIONS.md
├── MASTER_INDEX.md
├── apps/
│   ├── customer/        # Flutter 직원 앱
│   └── admin/           # React (회사 관리자 + 운영자 + 식당 조회)
├── services/api/        # FastAPI
│   ├── app/routers/  app/services/  app/repositories/
│   └── tests/
└── infra/
    ├── migrations/
    └── seed/            # 회사 1, 식당 5, 직원 10 시드
```

---

## 4. DB 스키마 (Postgres / Supabase)

```sql
-- ============ 조직 ============
create table companies (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  biz_reg_no text,                       -- 사업자번호 (정산서용)
  status text default 'active' check (status in ('active','suspended')),
  created_at timestamptz default now()
);

create table employee_groups (           -- 부서/직급 그룹 (정책·통계 단위)
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references companies(id),
  name text not null,                    -- 예: "개발팀", "임원"
  unique (company_id, name)
);

create table app_users (
  id uuid primary key references auth.users(id),
  company_id uuid references companies(id),
  group_id uuid references employee_groups(id),
  display_name text not null,
  role text not null default 'employee'
    check (role in ('employee','company_admin','platform_admin')),
  status text default 'active' check (status in ('active','paused','left')),
  fcm_token text,
  created_at timestamptz default now()
);

-- ============ 식당 ============
create table merchants (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  biz_reg_no text,
  owner_phone text,                      -- 매직링크 발송용
  bank_account jsonb,                    -- {bank, number, holder} — 정산서 표기용
  address text,
  lat numeric, lng numeric,              -- 위치 검증(§1.4)
  category text,                         -- 한식/중식/분식...
  avg_price int,                         -- 목록 표시용
  qr_token text unique not null,         -- 매장 QR에 인코딩되는 정적 토큰
  view_token text unique not null,       -- 조회 페이지 매직링크 토큰
  status text default 'active' check (status in ('active','paused','terminated')),
  created_at timestamptz default now()
);

create table company_merchants (         -- 회사별 제휴 관계 (다대다)
  company_id uuid references companies(id),
  merchant_id uuid references merchants(id),
  is_active boolean default true,
  primary key (company_id, merchant_id)
);

-- ============ 식대 정책 ============
create table meal_policies (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references companies(id),
  group_id uuid references employee_groups(id),  -- null = 회사 기본 정책
  meal_windows jsonb not null default
    '[{"name":"중식","start":"11:00","end":"14:00","per_meal_limit":10000},
      {"name":"석식","start":"17:30","end":"20:30","per_meal_limit":12000}]',
  daily_limit int,                       -- null = 무제한
  monthly_grant int not null default 200000,  -- 월 지급액
  weekend_allowed boolean default false,
  carry_over boolean default false       -- 미사용분 이월 여부 (false = 월말 소멸)
);

-- ============ 식대 원장 ============
create table meal_transactions (
  id bigint generated always as identity primary key,
  user_id uuid not null references app_users(id),
  company_id uuid not null references companies(id),
  merchant_id uuid references merchants(id),   -- spend에만
  amount int not null,                   -- +grant / -spend / -expire / +refund / ±adjust
  kind text not null check (kind in ('grant','spend','expire','refund','adjust')),
  tx_code text unique,                   -- 완료화면 표시용 6자리 (spend에만)
  meal_window text,                      -- '중식'/'석식' (spend에만)
  group_pay_id uuid,                     -- 함께결제 묶음 (M2)
  flags jsonb default '{}',              -- {gps_far: true, ...} 이상 플래그
  idempotency_key text unique,
  created_at timestamptz default now()
);

create view meal_balances as
select user_id, sum(amount) as balance
from meal_transactions group by user_id;

-- ============ 정산 (데이터 제공 전용 — 자금 이동 없음) ============
create table settlements (               -- 회사 × 식당 × 월
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references companies(id),
  merchant_id uuid not null references merchants(id),
  period_ym text not null,               -- '2026-07'
  tx_count int not null,
  total_amount int not null,
  status text default 'draft'
    check (status in ('draft','confirmed','paid')),  -- paid = 회사가 송금완료 체크
  paid_at timestamptz,
  unique (company_id, merchant_id, period_ym)
);
```

### 4.1 RLS 요약
- `app_users`: 본인 row select/update(fcm_token 등). role 변경은 service_role만
- `meal_transactions`: 본인 것 select만. `company_admin`은 자기 회사 전체 select
- `merchants`, `company_merchants`: 인증 사용자 read (자기 회사 제휴만)
- 쓰기 전부 FastAPI(service_role) 경유. `merchant-view`는 `view_token` 검증 후 서버가 조회해 반환 (Supabase 직접 접근 없음)

---

## 5. 결제 플로우 (핵심 시퀀스)

### 5.1 QR 스캔 결제 (정상 흐름)
```
직원: 앱 [결제] 탭 → 카메라로 매장 QR 스캔
앱: qr_token 파싱 → GET /merchants/by-qr/{token} → 매장명/카테고리 표시
앱: 금액 입력 화면 (숫자패드, 현재 식대창구·1식 한도·잔액 표시)
앱 → 서버: POST /pay {qr_token, amount, gps: {lat,lng}, idempotency_key}
서버(트랜잭션):
  1) qr_token → merchant 확인, company_merchants 제휴 확인
  2) 정책 엔진: 현재 시각이 meal_window 내인가 / per_meal_limit / daily_limit / weekend
  3) 이번 달 사용액 + 결제액 <= 직원 월 한도
  4) GPS-매장 거리 500m 초과 시 flags.gps_far = true (차단 아님)
  5) meal_transactions(spend) insert + tx_code 6자리 발급
서버 → 앱: {ok, tx_code, merchant_name, amount, server_time}
앱: 결제완료 화면 렌더 (§1.4 위조방지 요소 전부 포함) → 직원이 사장님께 제시
```

### 5.2 에러 케이스 (전부 명확한 한국어 안내 필수)
| 코드 | 상황 | 안내 |
|---|---|---|
| `OUT_OF_WINDOW` | 식사시간 외 | "지금은 식대 사용 시간이 아니에요 (중식 11:00~14:00)" |
| `MEAL_LIMIT` | 1식 한도 초과 | "1식 한도는 10,000원이에요. 초과분은 개인 결제해 주세요" |
| `MONTHLY_LIMIT` | 월 한도 초과 | "월 한도 200,000원을 초과해요" |
| `NOT_AFFILIATED` | 제휴 안 된 식당 | "우리 회사 제휴 식당이 아니에요" |
| `DUPLICATE` | 60초 내 동일금액 재요청 | 기존 완료화면 재표시 (idempotency) |

### 5.3 취소 정책
- 결제 후 10분 내 본인 취소 가능 (`refund` 원장 + 완료화면에 "취소됨" 대형 워터마크)
- 10분 경과 후에는 회사 관리자만 조정(`adjust`) 가능 — 사유 필수 입력

---

## 6. REST API 계약

Base `https://api.<domain>/v1` — 응답 `{"ok", "data", "error": {"code","message"}}`

### 6.1 직원 앱
| Method | Path | 설명 |
|---|---|---|
| GET | `/me` | 프로필 + 잔액 + 이번달 사용액 + 적용 정책 요약 |
| GET | `/merchants?near=lat,lng` | 우리 회사 제휴식당 목록 (거리순, 카테고리 필터) |
| GET | `/merchants/by-qr/{qr_token}` | QR 스캔 직후 매장 확인 |
| POST | `/pay` | §5.1 결제 |
| POST | `/pay/{tx_code}/cancel` | 10분 내 취소 |
| GET | `/me/transactions?month=` | 사용 내역 |
| GET | `/me/transactions/{tx_code}` | 완료화면 재표시용 (당일만) |

### 6.2 회사 관리자
| Method | Path | 설명 |
|---|---|---|
| CRUD | `/admin/employees`, `/admin/groups` | 직원/그룹 (CSV 일괄 등록 포함) |
| PUT | `/admin/policies` | 정책 편집 |
| POST | `/admin/grants` | 포인트 지급 (전체/그룹/개인, 즉시/예약) |
| GET | `/admin/dashboard` | 금일 사용액, 시간대별 추이, 부서별/식당별 통계 |
| GET | `/admin/transactions?flag=gps_far` | 이상 거래 필터 조회 |
| POST | `/admin/transactions/{id}/adjust` | 조정 (사유 필수) |
| GET | `/admin/settlements?ym=` | 식당별 월 정산서 (웹 + CSV + PDF) |
| POST | `/admin/settlements/{id}/mark-paid` | 송금 완료 체크 |

### 6.3 플랫폼 운영자 (`platform_admin`)
| Method | Path | 설명 |
|---|---|---|
| CRUD | `/platform/companies`, `/platform/merchants` | 온보딩 |
| POST | `/platform/merchants/{id}/qr` | QR 발급 (인쇄용 PDF: A6 스티커 레이아웃) |
| POST | `/platform/merchants/{id}/send-view-link` | 조회 매직링크 SMS/알림톡 발송 (M2) |
| PUT | `/platform/company-merchants` | 제휴 매핑 |

### 6.4 식당 조회 페이지 (무로그인)
| Method | Path | 설명 |
|---|---|---|
| GET | `/m/{view_token}` | 오늘 결제 내역 (시각/금액/tx_code, 회사별 소계) + 월 누계. 개인정보(직원 실명)는 마스킹 |

### 6.5 배치 (APScheduler)
| 주기 | 작업 |
|---|---|
| 매월 1일 00:10 | 전월 미사용분 `expire` (carry_over=false 그룹) + 당월 `grant` 자동 지급 |
| 매월 1일 00:30 | 전월 settlements draft 생성 (회사×식당) |
| 매일 21:00 | 회사 관리자에게 금일 요약 (M2, 이메일) |

---

## 7. 컴포넌트별 상세

### 7.1 직원 앱 (`apps/customer`, Flutter)
**화면**
1. 로그인 — Supabase Auth (이메일 매직링크). 회사 초대코드로 최초 연결
2. 홈 — 잔액 카드(크게), 오늘 식대창구 상태(중식 진행중/마감), 최근 내역 3건, [QR 결제] 대형 버튼
3. 식당 목록/지도 — 제휴식당 카드(거리, 카테고리, 평균가), 지도 뷰(선택)
4. QR 스캔 — ML Kit, 손전등 토글
5. 금액 입력 — 숫자패드, 한도·잔액 실시간 표시, 최근 결제 금액 프리셋
6. **결제완료 화면** — 본 프로젝트에서 가장 공들일 화면: 매장명·금액 초대형, 움직이는 서버시각, 파형 애니메이션, 결제 사운드, tx_code, 10분 내 [취소] 버튼. 화면 캡처 감지 시 경고 오버레이(Android FLAG_SECURE는 미적용 — 제시 자체가 목적이므로)
7. 내역 — 월별, 식당별 필터
8. 함께결제 (M2) — 참석자 선택 → 합산 한도 결제 → 참석자에게 균등 차감 + 푸시

### 7.2 관리자 웹 (`apps/admin`, React)
- **회사 관리자 뷰**: 대시보드 / 직원·그룹 관리(CSV 업로드) / 정책 편집(식사창구 시각 편집 UI) / 지급 / 내역·이상거래 / 정산서(식당별 카드 → 상세 → CSV·PDF 다운로드 → 송금완료 체크)
- **플랫폼 운영자 뷰**: 회사·식당 온보딩 / QR 스티커 PDF 생성(매장명+QR+사용법 3줄) / 제휴 매핑
- **식당 조회 라우트** `/m/{token}`: 모바일 우선, 무로그인, 오늘 내역 자동 갱신(폴링 30초)

### 7.3 API (`services/api`)
- `services/policy_engine.py` — 정책 판정 순수 함수 (시각 주입 가능하게 설계 → 테스트 용이)
- `services/payment.py` — 결제 트랜잭션. Postgres function `process_meal_pay`로 원자성
- `services/settlement.py` — 정산 draft 생성 + PDF(WeasyPrint) 렌더
- 테스트: 정책 엔진 파라미터라이즈드 테스트(경계시각·한도·주말·이월), 결제 동시성 테스트(같은 유저 동시 2건 → 잔액 음수 방지)

---

## 8. 마일스톤 & DoD

### M1 — 결제 코어 (회사 1곳 파일럿)
- [ ] `infra`: 마이그레이션 + 시드 (회사 1, 그룹 2, 직원 10, 식당 5)
- [ ] `api`: 인증/정책엔진/결제/취소/지급/내역 + process_meal_pay SQL 함수
- [ ] `customer`: 로그인~결제완료 화면 전체 (§7.1 화면 1~7)
- [ ] `admin`: 직원 CSV 등록, 정책 편집, 지급, 내역 조회
- [ ] `admin`: QR 스티커 PDF 생성
- **DoD**: 시드 데이터 기준 "QR 스캔 → 금액 입력 → 완료화면" 3초 내 응답. §5.2 에러 5종 전부 처리. 정책 엔진 테스트 20케이스+ 통과. 동시 결제 시 잔액 음수 불가 검증.

### M2 — 운영/신뢰 기능
- [ ] 함께결제, 식당 조회 매직링크 페이지, 이상거래(gps_far) 관리자 필터
- [ ] 월말 정산서 CSV+PDF, 송금완료 체크, 월초 자동 grant/expire 배치
- [ ] FCM (지급 알림, 소멸 D-3), 대시보드 통계
- **DoD**: 날짜 mocking으로 "월말 정산 → PDF → 송금체크 → 월초 지급/소멸" E2E 통과. 정산서 합계가 원장 합계와 일치(자동 검증 테스트).

### M3 — 확장 (백로그, 착수 전 사용자 승인)
- 다중 회사 셀프 온보딩, 알림톡 연동, 세금계산서 데이터 연동
- (나) 대금 중개 모델 검토 — **PG/전자금융업 법률 검토 선행 필수**
- 구내식당/무인 쇼케이스(SnackBox v1) 연동 — 동일 원장 위에 결제 채널 추가

---

## 9. 규제/정책 결정사항
| # | 결정 | 근거 |
|---|---|---|
| D-01 | 개인 현금 충전 미구현 | 선불전자지급수단 발행업 이슈 회피. 회사 지급 식대만 |
| D-02 | 플랫폼 자금 수취/지급 없음 (SaaS) | 전자지급결제대행(PG) 등록 회피. 회사→식당 직접 송금 |
| D-03 | 식당 무설치 (C 방식) | 제휴 영업 마찰 최소화. 위조 방지는 §1.4 다층 방어 |
| D-04 | 미사용 포인트 월말 소멸 기본 | 벤치마크 동일. carry_over 옵션으로 회사별 선택 |
| D-05 | GPS 이탈은 플래그만, 차단 안 함 | 실내 GPS 오차 오탐 방지. 사후 검증 체계로 커버 |
| D-06 | 결제취소 10분 제한 | 오입력 구제 + 식사 후 취소 악용 차단 균형 |

## 10. 벤치마크 참고 (식권대장/식신e식권 조사, 2026-07)
- 수익 모델: 기업 솔루션 사용료 + 식당 정산 수수료 2~5% (후발주자는 기업 무료도 있음) → 본 프로젝트 (가) 모델에서는 **기업 SaaS 구독료 단일** (예: 직원 1인당 월 1,000~2,000원 수준에서 파일럿 후 결정)
- 도입 효과 소구점: 식대 지출 평균 10~18% 절감(오남용 차단), 총무 정산 업무 제거, 세금계산서 단순화
- 차별 기능 레퍼런스: 함께결제, 차등지급(그룹 정책), 사비 추가 결제(통합포인트 — 우리는 D-01로 미구현, "초과분 개인 현금 결제" 안내로 대체)
- 종이 장부의 페인포인트(영업 멘트 소재): 월말 장부 복사·수기 정산, 팀별 예산 중간집계 불가, 식권 대여·복제 부정사용

---
*End of GREENEATGO_AGENT_SPEC.md v2.0*
