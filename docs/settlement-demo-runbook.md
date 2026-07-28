# 정산·세금계산서 시연 런북

> **안전 원칙:** 이 기능은 **Popbill `IsTest=true`인 테스트 환경에서만** 사용한다. 테스트 세금계산서만 생성되며 실제 국세청 신고·실제 돈 이동은 없다. 운영 모드에서는 시연 단계와 문서 열기가 차단된다. 화면의 `테스트 환경: 준비됨`을 확인하지 못하면 진행하지 않는다.

## 1. 사전 준비와 대상 조건

- DB 마이그레이션(특히 `infra/migrations/0042_settlement_demo.sql`), API, 관리자 UI가 같은 버전으로 배포되어 있어야 한다.
- **활성 식당 관리자(`merchant_admin`)**로 로그인한다. 토큰은 환경변수로만 전달하고 셸 기록, 문서, 화면 공유, 로그에 남기지 않는다.
- Popbill 서버 설정은 `IsTest=true`여야 하며, 테스트 계정 설정·인증서가 유효해야 한다.
- 식당 공급자 정보가 완성되어 있고 공급자 사업자번호가 Popbill 테스트 사업자번호와 일치해야 한다.
- 대상 회사는 모두 충족해야 한다.
  - 회사와 식당-회사 계약이 모두 활성
  - 활성 회사 관리자 1명 이상
  - 활성 임직원 또는 고객 1명 이상
  - 세금계산서용 회사 정보(사업자등록번호, 상호, 대표자, 주소, 업태, 종목, 담당 이메일·이름·전화)가 완성
- 대상 월은 **현재 월보다 이전**, 최근 24개월 범위이고, 같은 식당·회사·월에 기존 정산 또는 정산 대상 거래가 없어야 한다. UI는 지난 12개월만 제시한다.

### 데이터 안전성

시드는 회사를 복제하거나 가짜 계정/사업자정보를 만들지 않는다. 선택된 실제 활성 임직원/고객에게 `settlement_demo=true`와 실행 식별자가 표시된 6~12건의 무작위 데모 거래를 연결한다. 거래 금액은 정산 증빙용이며 **사용자 잔액·회사 한도·선구매 잔액은 변경하지 않는다**. 이름, 연락처, 회사 ID, 거래 ID 등 실제 식별정보를 런북·채팅·캡처에 노출하지 않는다.

## 2. CLI로 데이터 심기(선택 사항)

저장소 루트에서 실행한다. 원격 API는 HTTPS만 허용되고, HTTP는 localhost/loopback만 허용된다. 아래 값은 모두 자리표시자이며 실제 토큰이나 ID를 문서에 적지 않는다.

```bash
export SETTLEMENT_DEMO_TOKEN='<현재 활성 식당 관리자 액세스 토큰>'
export SETTLEMENT_DEMO_API_URL='https://<API-호스트>'
python3 scripts/settlement_demo.py seed \
  --company-id '<대상-회사-UUID>' \
  --period-ym '<YYYY-MM>'
```

로컬 API 기본값(`http://127.0.0.1:8000`)을 쓸 때는 `SETTLEMENT_DEMO_API_URL`을 생략할 수 있다. `seed`에는 `--company-id`와 `--period-ym`이 모두 필수다. 현재 실행과 회사·월이 같으면 기존 상태를 반환하고 중복 생성하지 않으며, 다른 선택으로 다시 심으려면 먼저 초기화해야 한다.

## 3. UI 시연 순서와 증거

경로: **식당 관리자 웹 → 왼쪽 메뉴 맨 아래 `공급자 정보` → 페이지 아래쪽 `정산·세금계산서 시연`**.

먼저 `팝빌 설정`, `테스트 환경`, `인증서`, `공급자 정보`, `사업자번호 일치` 배지가 모두 **준비됨**인지 확인한다. 회사 선택 목록에서 `임직원`, `관리자`, `사업자정보`가 준비된 회사와 지난달 이전 월을 고른다.

각 클릭 뒤 자동 새로고침이 끝날 때까지 기다리고, 다음 버튼이 하나만 활성화되는지 확인한다.

| 순서 | 정확한 클릭 | 기대 단계와 화면 증거 |
|---|---|---|
| 1 | `시연 거래 생성 (데이터 심기)` | 타임라인 `시연 거래 생성`; 무작위 거래 건수와 **공급가액 합계·부가세 합계·거래 합계** 표시 |
| 2 | `다음 단계: 정산 생성` | 타임라인 `정산 생성`; 기존 정산 `작성 중`, 정산 워크플로 `작성 중`, 세금계산서 `발행 요청 전`, 입금 `입금 대기` |
| 3 | `다음 단계: 정산 확정` | 타임라인 `정산 확정`; 기존 정산 `확정`, 정산 워크플로 `확정`, 세금계산서 `발행 요청`, 입금 `입금 대기` |
| 4 | `다음 단계: 테스트 세금계산서 발행` | 타임라인 `테스트 세금계산서 발행`; 세금계산서 `테스트 발행 완료`(또는 후속 `국세청 전송 중`/`국세청 승인`)와 `발행 일시` 표시 |
| 5 | `테스트 세금계산서 보기`, 이어서 `테스트 세금계산서 PDF` | 새 창에서 Popbill 테스트 문서 보기/PDF가 열림. 팝업이 차단되면 해당 사이트의 팝업을 허용하고 다시 클릭 |
| 6 | `다음 단계: 입금 완료 처리` | 타임라인 `입금 완료`; 기존 정산과 입금이 `입금 완료`. API 상태의 `payment_status=paid` 및 `paid_at`이 채워짐 |

금액 증거는 1단계의 세 합계가 2단계 이후 상세의 **공급가액·부가세·합계**와 각각 같고, 입금 완료 금액이 정산 합계와 같다는 것이다. 금액과 건수는 매 실행마다 무작위이므로 미리 정한 숫자를 말하지 말고 화면에 나온 값을 읽는다.

### 테스트 문서와 국세청 번호를 설명하는 법

- `테스트 발행 완료`는 Popbill 테스트 문서가 생성됐다는 뜻이지 실제 세금계산서 발행이나 국세청 신고를 뜻하지 않는다.
- 테스트 환경에서는 국세청 승인번호가 없을 수 있다. 이 경우 화면의 **`테스트 발행 완료 / 국세청 승인번호 없음`**을 그대로 설명하며 번호를 만들거나 실제 승인으로 표현하지 않는다.
- `nts_confirm_num`이 실제 응답에 있을 때만 그 값을 증거로 사용한다. 보기/PDF가 열린다는 사실도 실제 국세청 접수의 증거로 과장하지 않는다.
- 발행 전에는 보기/PDF 버튼과 `issued_at`이 없고 승인번호는 `대기`다. 발행 후에만 보기/PDF가 활성화되고 `issued_at` 및 제공된 경우에 한해 `nts_confirm_num`이 표시된다.
- `paid_at`은 6단계 전에는 `null`, 입금 완료 후에는 서버가 기록한 시각이다. 이는 데모 정산의 상태 기록일 뿐 실제 계좌 입금 시각이 아니다.

## 4. 초기화와 반복 시연 복구

UI에서는 `시연 초기화` → 확인창의 확인을 누른다. CLI에서는 재시도에 사용할 멱등 키를 환경변수로 전달한다.

```bash
export SETTLEMENT_DEMO_TOKEN='<현재 활성 식당 관리자 액세스 토큰>'
export SETTLEMENT_DEMO_API_URL='https://<API-호스트>'
export SETTLEMENT_DEMO_IDEMPOTENCY_KEY='reset-<이번-초기화의-고유값>'
python3 scripts/settlement_demo.py reset
```

- 네트워크 타임아웃으로 결과가 불명확하면 **같은 초기화 시도에는 같은 키**로 재실행한다. 새 시연을 초기화할 때는 새 키를 사용한다. 키는 1~200자이며 비밀값이나 개인식별정보를 넣지 않는다.
- 정산 생성 전, 또는 아직 이벤트/발행/입금이 없는 초안이면 데모 거래와 제거 가능한 초안 정산을 삭제한다.
- 정산 확정 이후, 특히 **발행 또는 입금 완료 이후에는 감사 추적을 위해 발행 문서·정산·거래·이벤트·입금 기록을 삭제하지 않고 실행을 보존(보관 처리)**한다. 초기화는 현재 선택만 비우며 발행 기록은 보존된다.
- 반복 발표는 `초기화 → 새로고침 → 같은 조건을 충족하는 다른 미사용 과거 월 선택 → 데이터 심기` 순서로 복구한다. 같은 월에 보존 기록이나 다른 거래가 있으면 재사용할 수 없다.
- POST 성공 뒤 상태 조회만 실패했다는 경고가 나오면 버튼을 다시 누르지 말고 `다시 시도`/`새로고침`으로 먼저 현재 단계를 읽는다. 이미 완료된 단계를 중복 실행하지 않는다.

## 5. 오류 코드별 조치

| 코드/증상 | 의미와 조치 |
|---|---|
| `UNAUTHENTICATED`, `FORBIDDEN` | 토큰 만료 또는 활성 식당 관리자 권한 아님. 다시 로그인하고 올바른 역할을 확인 |
| `SETTLEMENT_DEMO_TEST_MODE_REQUIRED` | `IsTest`가 true가 아님. 즉시 중단하고 서버 Popbill 테스트 설정 확인 |
| `POPBILL_NOT_CONFIGURED`, `POPBILL_TEMPORARILY_UNAVAILABLE` | 서버 설정 누락 또는 Popbill 연결 장애. 설정/네트워크 확인 후 상태 새로고침 |
| `SETTLEMENT_DEMO_SUPPLIER_NOT_READY`, `SUPPLIER_PROFILE_INCOMPLETE` | 공급자 필수정보 누락 또는 Popbill 테스트 사업자번호 불일치. `공급자 정보` 저장 후 배지 확인 |
| `SETTLEMENT_DEMO_CERTIFICATE_NOT_READY` | 테스트 계정 인증서 미등록·만료. 인증서를 정비한 뒤 재시도 |
| `BUSINESS_PROFILE_INCOMPLETE`, `SETTLEMENT_DEMO_COMPANY_INELIGIBLE` | 대상 회사 사업자정보 또는 활성 회사/계약 조건 미충족. 다른 준비 완료 회사 선택 |
| `SETTLEMENT_DEMO_COMPANY_ADMIN_REQUIRED`, `SETTLEMENT_DEMO_EMPLOYEE_REQUIRED` | 활성 회사 관리자 또는 활성 임직원/고객이 없음 |
| `DEMO_PERIOD_TRANSACTION_CONFLICT`, `SETTLEMENT_DEMO_NO_UNUSED_PERIOD` | 해당 월에 기존 정산/거래/보존 실행이 있음. 초기화 후 다른 미사용 과거 월 선택 |
| `SETTLEMENT_DEMO_STATE_CONFLICT`, `SETTLEMENT_DEMO_NOT_SEEDED`, `SETTLEMENT_DEMO_NOT_CREATED` | 클릭 순서가 현재 서버 단계와 다름. 새로고침 후 활성화된 다음 버튼만 사용 |
| `POPBILL_ISSUE_REJECTED` | 입력 또는 공급자 거절. 정보 수정 전 반복 발행 금지 |
| `POPBILL_RECONCILIATION_REQUIRED` | 발행 성공 여부가 불명확. 새 문서를 발행하지 말고 운영자가 기존 발행 상태를 대사 |
| `POPBILL_DOCUMENT_NOT_FOUND` | 발행 전 문서 열기 또는 문서 상태 불일치. 현재 단계와 발행 결과 확인 |
| `IDEMPOTENCY_CONFLICT` | 같은 멱등 키를 다른 요청에 재사용. 요청 결과를 확인하고 새 초기화에는 새 키 사용 |
| `SUPABASE_ERROR` | DB 처리 오류. 반복 클릭하지 말고 API/DB 로그와 현재 상태를 확인 |

## 6. 종료 후 감사/readback

화면을 새로고침한 뒤 다음을 확인한다. 민감 필드는 출력·캡처하지 않는다.

```bash
curl --fail --silent --show-error \
  -H "Authorization: Bearer ${SETTLEMENT_DEMO_TOKEN}" \
  "${SETTLEMENT_DEMO_API_URL%/}/v1/admin/merchant/settlement-demo" \
| jq '{seeded:.data.seeded,stage:.data.stage,period_ym:.data.period_ym,transaction_count:.data.transaction_count,aggregate:.data.aggregate,settlement:(.data.settlement|if . then {status,settlement_status,tax_invoice_status,payment_status,supply_amount,vat_amount,total_amount,issued_at,nts_status,nts_confirm_num,paid_at,can_view_tax_invoice,can_download_tax_invoice_pdf} else null end)}'
```

완료 시 `stage=paid`, `status=paid`, `settlement_status=confirmed`, `payment_status=paid`, 비어 있지 않은 `paid_at`, 발행 상태(`issued`/`nts_sending`/`nts_accepted`), 비어 있지 않은 `issued_at`, 세 금액의 일치를 확인한다. `nts_confirm_num=null`은 테스트에서 정상일 수 있다.

발표 종료 후 `시연 초기화`를 실행하고 다시 readback하여 현재 상태가 `seeded=false`, `stage=empty`인지 확인한다. 이 결과는 **현재 실행이 해제됐다는 뜻**이며, 이미 발행·확정된 감사 기록이 삭제됐다는 뜻이 아니다. 운영 감사 시 보존된 실행, 표시된 데모 거래 플래그, 정산 이벤트, 테스트 발행 기록, 입금 기록을 서버 측 권한으로 대조하되 실제 ID/PII나 공급자 비밀값을 공유하지 않는다.
