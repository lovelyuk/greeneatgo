# QR_PAYMENT_UNIFIED_SPEC.md
> MEALLEDGER — QR 스캔 결제 통합 스펙 (장부업체 직원 + 개인 식권 구매자)
> 버전: v1.0 / 대상 에이전트: Codex / Claude Code
> 목적: 식당(돈토식당)이 이미 발급해 보여주는 QR을, 장부 소속 직원과 개인 식권 구매자가 **동일한 방식**으로 스캔해서 결제 처리되도록 백엔드 로직을 통합한다.

---

## 0. 핵심 결정 사항 (Design Decisions)

- QR 코드 자체는 **변경 없음** — 기존 장부업체용 QR(매장 표시용, `restaurant_id` 인코딩)을 그대로 재사용
- 키오스크는 **QR을 보여주기만** 함 — 스캔 로직/카메라 UI 추가 개발 불필요
- 스캔은 **사용자(장부 직원 or 개인 구매자) 앱 카메라**로 수행
- 계정(`account`)은 **결제수단 1개만 보유** — 한 계정이 "장부 소속"이면서 동시에 "개인 식권 구매자"가 될 수 없음 (파일럿 단계 단순화 결정)
- 스캔 처리 API는 **단일 엔드포인트**, 내부에서 계정 타입에 따라 분기
- **파일럿 범위 = 돈토식당 1곳만 처리.** `restaurant_id` 필드는 스키마/API에 그대로 유지(향후 매장 확장 대비, 마이그레이션 부담 최소화)하되, **로직은 다중 매장을 가정하지 않고 단순화**한다 (아래 0.1 참고).

### 0.1 단일 매장 단순화 범위

- QR 파싱: `restaurant:{restaurant_id}` 포맷은 유지하되, 서버는 이 값이 **돈토식당 고정 ID와 일치하는지만** 확인 (여러 매장 중 매칭 로직 불필요)
- `vouchers`/`transactions` 조회 시 `restaurant_id` 필터링 로직은 넣지 않아도 됨 (어차피 값이 하나뿐이므로) — 단, 컬럼 자체는 반드시 채워서 저장 (나중에 매장 추가 시 데이터 마이그레이션 없이 바로 활용 가능하도록)
- 식권 구매 화면에도 매장 선택 UI는 넣지 않음 ("돈토식당 식권 구매"로 고정 문구)
- **향후 매장이 늘어나면**: QR 파싱 매칭 로직 추가 + 구매화면에 매장 선택 UI 추가 + `vouchers`/`transactions` 조회 시 `restaurant_id` 필터 추가 — 스키마 변경 없이 로직 레이어만 확장하면 됨

---

## 1. 계정 모델

```
accounts
  - id
  - phone (로그인 식별자)
  - name
  - account_type: 'ledger' | 'voucher'   -- 장부소속 / 개인식권구매자, 필수, 변경 불가(파일럿 범위)
  - company_id  (account_type='ledger'일 때만 값 존재, FK → companies)
  - status: 'active' | 'inactive'
```

- `account_type`은 **가입 시 1회 결정**, 이후 변경 UI 없음 (MVP 범위 밖)
- 장부 소속 직원은 `company_id`로 소속 회사 연결 → 기존 정산 로직(월말 청구)과 동일하게 동작
- 개인 식권 구매자는 `company_id` 없음, 대신 `vouchers` 테이블에 보유 식권 수량 존재

---

## 2. 데이터 모델

```
vouchers                          -- 개인 사용자가 구매한 식권
  - id
  - account_id       (FK, account_type='voucher'인 계정만)
  - restaurant_id
  - status: 'unused' | 'used' | 'refunded'
  - purchased_at
  - used_at
  - pg_transaction_id  (결제 PG 거래ID, 환불 처리용)

transactions                      -- 모든 결제 기록 (장부 + 개인식권 공용)
  - id
  - account_id
  - restaurant_id
  - pay_type: 'ledger' | 'voucher'   -- 정산 화면 필터링에 사용되는 핵심 필드
  - amount
  - voucher_id        (pay_type='voucher'일 때만 값 존재, FK)
  - status: 'completed' | 'cancelled'
  - created_at
```

- `pay_type`이 곧 [정산 현황 화면]의 "정산 금액" 집계 기준: `pay_type='ledger'`인 건만 정산 대상으로 카운트, `voucher` 건은 이미 PG로 정산 완료된 돈이라 **제외**

---

## 3. API 스펙

### `POST /transactions/scan`

**Request**
```json
{
  "qr_data": "restaurant:{restaurant_id}",
  "account_id": "acc_123"
}
```

**서버 처리 로직 (의사코드)**

```
1. qr_data → restaurant_id 파싱, 유효성 확인 (존재하는 식당인지)
2. account_id → account 조회
3. IF account.status != 'active':
     → 403 에러 "비활성화된 계정입니다"

4. IF account.account_type == 'ledger':
     - 기존 장부 결제 로직 그대로 수행
     - transactions 생성 (pay_type='ledger', amount=계약단가)
     - company의 미수금(unsettled_amount)에 amount 누적
     - RETURN 200 { result: 'success', pay_type: 'ledger', company_name, remaining: null }

5. IF account.account_type == 'voucher':
     - vouchers WHERE account_id=? AND restaurant_id=? AND status='unused'
       ORDER BY purchased_at ASC LIMIT 1  -- 오래된 식권부터 차감(FIFO)
     - IF 없음:
         → 402 에러 { result: 'fail', reason: 'no_voucher', message: '보유 식권이 없습니다' }
         (앱은 이 에러 받으면 자동으로 식권 구매 화면으로 유도)
     - ELSE:
         - voucher.status = 'used', used_at = now()
         - transactions 생성 (pay_type='voucher', amount=voucher 가격, voucher_id 연결)
         - remaining = 해당 restaurant_id 기준 남은 unused voucher 개수
         - RETURN 200 { result: 'success', pay_type: 'voucher', remaining }

6. Supabase Realtime: transactions insert 이벤트 발행
   → 키오스크가 구독 중이면 자동으로 "OOO님 결제완료" 알림 수신
```

### 에러 케이스 정리

| 상황 | 응답 | 앱 동작 |
|---|---|---|
| 정상 (장부) | 200, pay_type=ledger | "결제완료" 화면, 회사명 표시 |
| 정상 (식권) | 200, pay_type=voucher, remaining | "결제완료" 화면, 잔여 식권 수 표시 |
| 식권 잔여 0 | 402, no_voucher | "식권이 없어요" → [식권 구매하기] 버튼으로 전환 |
| 비활성 계정 | 403 | "계정 문의" 안내 |
| 잘못된 QR | 400 | "QR을 다시 스캔해주세요" |

---

## 4. 실시간 알림 (키오스크 화면)

- Supabase Realtime으로 `transactions` 테이블 insert 구독 (restaurant_id 필터)
- 키오스크는 새 카메라/스캔 UI 없이 **아래 화면만 추가**:
  ```
  ┌─────────────────────────────┐
  │   ✅ 홍길동님 결제완료         │
  │   장부 결제 · 8,000원         │
  │                               │
  │          [ 확인 ]             │
  └─────────────────────────────┘
  ```
  - 장부 결제: "OOO님 결제완료 · 장부 결제"
  - 식권 결제: "OOO님 결제완료 · 식권 결제 · 잔여 N장"
  - **[확인] 버튼 클릭 시에만 닫힘** (기존 키오스크 알림 방식과 동일하게 유지 — 자동 소멸 없음). 사장님이 바쁠 때 못 보고 놓치는 것 방지
  - 확인 전에 새 결제 건이 또 들어오면: 큐에 쌓아 순차 표시 or 리스트형으로 누적 표시 (구현 시 기존 키오스크 알림 큐 방식 그대로 따름)

---

## 5. 앱 UI (사용자 측 — 장부/개인식권 공용 스캔 화면)

- 계정 타입에 상관없이 **동일한 "QR 스캔" 버튼 하나**로 통일
- 스캔 성공 시 결과 화면도 공용 컴포넌트 사용, `pay_type`에 따라 표시 문구만 분기
  - `ledger` → "OO식당에서 결제됐어요 (회사 장부로 청구됩니다)"
  - `voucher` → "OO식당에서 식권 1장 사용했어요 (잔여 N장)"
- `no_voucher` 에러 시 → 결과 화면 자체가 "식권이 없어요" + [지금 구매하기] CTA로 전환

---

## 6. 정산 화면 연동 (기존 스펙과의 연결)

- `VENDOR_TRANSACTION_MODAL_SPEC.md`의 "미정산 잔액", "정산 금액" 계산 시 반드시 `WHERE pay_type = 'ledger'` 조건 추가
- 거래내역 리스트(모달)에는 `pay_type` 뱃지 추가 표시 권장 (장부/식권 구분) — 식당 사장님이 한눈에 구분 가능하게
- "정산 현황" 전체 화면의 `결제 건수` 카드는 `ledger` + `voucher` 전체 합산, `정산 금액`/`정산 건수`는 `ledger`만 집계

---

## 7. PG(결제) 연동 — 식권 구매

### 7.1 결정 사항

- **PG사: 토스페이먼츠 직접 연동** (포트원 미경유). 파일럿 규모(돈토식당 1곳)에서는 포트원 이용료도 무료 구간이라 비용 차이가 없고, 구조를 단순화하기 위해 직접 연동으로 결정함. 나중에 거래 규모가 커지거나 멀티 PG 대응이 필요해지면 포트원으로 감싸는 것을 재검토
- **가맹점 계약 주체는 돈토식당** (사업자등록증 기준). 개발자(용욱)는 계약 당사자가 아니라 서류 취합 대행 + 기술 연동만 담당. 발급받은 API 키(클라이언트 키/시크릿 키)만 앱/서버 환경변수에 반영
- 결제된 금액은 **돈토식당 정산계좌로 직접 입금**됨 — 이게 섹션 6의 "voucher 건은 정산 대상(미수금) 아님" 전제의 근거

### 7.2 개발 프로세스 (테스트 키 → 라이브 키, 병행 진행)

```
1. 토스페이먼츠 개발자센터 가입 → 테스트 클라이언트 키/시크릿 키 발급
   (사업자등록/심사 완료와 무관하게 즉시 가능 — 개발 선착수)
2. 테스트 키로 식권 구매 플로우 개발/테스트
   - 카드, 토스페이, 네이버페이 → 테스트 키로 바로 가능
   - ⚠️ 가상계좌 → 계약 완료 전 테스트 불가
   - ⚠️ 카카오페이 → 계약 완료 후 발급되는 전용 테스트키로만 가능 (범용 테스트키 불가)
3. (개발과 병행) 돈토식당 사업자 서류로 실 가맹점 계약 신청 — 개발을 막지 않음
4. 심사 완료 → 라이브 키 발급 → 환경변수만 교체 (코드 변경 없이 키 스왑)
```

- 환경변수 분리 관리: `TOSS_CLIENT_KEY` / `TOSS_SECRET_KEY`를 `.env.test`, `.env.production`으로 분리 보관. 코드에 키 하드코딩 금지

### 7.3 식권 구매 API 플로우

> ⚠️ **업데이트**: 이 섹션은 `VOUCHER_PRODUCT_SPEC.md`로 대체되었습니다. 구매는 `quantity` 직접입력 방식이 아니라, 관리자가 등록한 **상품(product_id)** 선택 방식으로 변경됨. 아래 내용은 참고용으로만 남겨두고, 실제 구현은 반드시 `VOUCHER_PRODUCT_SPEC.md` 섹션 3.3 기준으로 진행할 것.

```
POST /vouchers/purchase
Request: { account_id, quantity }

처리 로직:
1. account.account_type == 'voucher' 확인 (ledger 계정은 구매 불가 → 403)
2. 토스페이먼츠 결제위젯 호출 (quantity × 단가)
3. 결제 성공 웹훅 수신 → vouchers 레코드를 quantity만큼 생성 (status='unused', restaurant_id=돈토식당 고정값)
4. 결제 실패/취소 → vouchers 생성 안 함, 에러 응답만 반환
```

- 1차 지원 결제수단: **카드, 토스페이, 카카오페이, 네이버페이** (계좌이체/가상계좌는 후순위, 필요 시 추가)
- 결제 UI는 토스페이먼츠 결제위젯 그대로 사용 (커스텀 결제창 새로 만들지 않음 — 개발 리소스 절약)

---

## 8. 구현 순서 (마일스톤)

1. **M1**: `accounts.account_type`, `vouchers`, `transactions.pay_type` 스키마 반영 (마이그레이션)
2. **M2**: `POST /transactions/scan` 엔드포인트 구현 (장부/식권 분기 로직)
3. **M3**: 토스페이먼츠 테스트 키로 `POST /vouchers/purchase` 연동 + 앱 — 공용 QR 스캔 화면 + 결과 화면(분기 문구) + no_voucher 시 구매 유도
4. **M4**: 키오스크 — Supabase Realtime 구독 + 결제완료 알림 토스트
5. **M5**: 정산 화면 — `pay_type='ledger'` 필터 반영, 거래내역에 뱃지 표시
6. **M6**: 돈토식당 가맹점 심사 완료 후 라이브 키로 전환, 실 결제 오픈

## 9. 완료 기준 (Acceptance Criteria)

- [ ] 장부 소속 직원 계정으로 QR 스캔 → 기존과 동일하게 회사 미수금에 누적됨
- [ ] 개인 식권 계정으로 QR 스캔 → 보유 식권 1장 차감, 잔여수량 정확히 반환
- [ ] 식권 잔여 0인 상태에서 스캔 → 402 에러 + 앱이 구매 화면으로 자동 전환
- [ ] 키오스크가 스캔 로직 없이도 결제완료를 실시간으로 인지/표시함
- [ ] 정산 현황 화면의 "정산 금액"에 개인식권 결제 건이 섞이지 않음
- [ ] 한 계정으로 두 결제수단을 동시에 쓸 수 없음 (가입 시 account_type 고정)
- [ ] 테스트 키로 카드/토스페이/네이버페이 식권 구매가 정상 동작함
- [ ] 라이브 키 전환이 코드 수정 없이 환경변수 교체만으로 가능함

## 10. 금지 사항 / 주의

- 계정 하나에 `account_type` 두 개 허용하는 로직 추가 금지 (파일럿 범위 밖 — 필요해지면 별도 스펙으로 재설계)
- 키오스크에 QR 스캔/카메라 기능 추가 금지 (이 스펙의 목적 자체가 그걸 없애는 것)
- `voucher` 결제 건을 정산 대상(미수금)에 포함시키는 로직 금지 — 이미 PG로 정산 완료된 돈
- 토스페이먼츠 시크릿 키를 클라이언트(앱) 코드에 노출 금지 — 반드시 서버 환경변수로만 관리
- PG 가맹점 계약을 돈토식당이 아닌 다른 명의로 진행 금지 — 정산 자금 흐름 전제가 깨짐 (섹션 7.1 참고)
