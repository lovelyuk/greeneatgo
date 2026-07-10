# VOUCHER_PRODUCT_SPEC.md
> MEALLEDGER — 식권 상품(패키지/할인) 관리 스펙
> 버전: v1.0 / 대상 에이전트: Codex / Claude Code
> 연관 문서: `QR_PAYMENT_UNIFIED_SPEC.md` (섹션 7.3 구매 API를 이 문서 기준으로 대체), `VENDOR_TRANSACTION_MODAL_SPEC.md`
> 목적: 식당관리자가 "식권 1장", "식권 10장 묶음(할인)" 같은 판매 상품을 등록/관리하고, 일반회원은 이를 구매해 QR로 소모한다.

---

## 0. 핵심 결정 사항

- 상품(`voucher_products`)은 **"낱장 식권 몇 개를 얼마에 파는지"**를 정의하는 단위 — 실제 소모 단위(`vouchers`)와는 분리된 개념
- 할인은 **상품 단위로 설정** (예: 10장 묶음 10% 할인). 낱장 단위 할인은 지원하지 않음 (MVP 범위 밖)
- 구매 시점의 **판매가를 스냅샷으로 저장** — 나중에 관리자가 상품 가격/할인율을 바꿔도 이미 판매된 건에는 영향 없음
- QR 스캔 소모 로직(`QR_PAYMENT_UNIFIED_SPEC.md` 섹션 3)은 **변경 없음** — 묶음으로 사도 결국 낱장 vouchers가 여러 건 생성되는 구조라 기존 FIFO 차감 로직 그대로 사용

---

## 1. 데이터 모델

```
voucher_products                     -- 관리자가 등록하는 판매 상품
  - id
  - restaurant_id        (고정값, 돈토식당)
  - name                 -- 예: "식권 1장", "식권 10장 묶음", "식권 10+1"
  - voucher_count         -- 결제 기준 수량 (예: 10)
  - bonus_count            -- 보너스로 추가 지급되는 수량 (예: 1), 기본값 0
  - unit_price            -- 식권 1장당 정가 (원)
  - discount_rate          -- 0~100 (%), 기본값 0
  - sale_price             -- 서버가 계산: unit_price * voucher_count * (1 - discount_rate/100)
                            --   ⚠️ bonus_count는 가격 계산에 영향 없음 (개수만 늘어남)
  - status: 'active' | 'inactive'
  - display_order          -- 앱에 노출되는 순서 (선택)
  - created_at, updated_at
```

- `total_count`(실제 발급되는 낱장 식권 수) = `voucher_count + bonus_count` — 별도 컬럼 없이 조회 시 계산해서 사용
- 대표적인 두 가지 프로모션 패턴:
  - **할인형**: `voucher_count=10, bonus_count=0, discount_rate=10` → 10장을 10% 할인된 가격에
  - **보너스형**: `voucher_count=10, bonus_count=1, discount_rate=0` → 10장 값으로 11장 지급
  - 이론상 동시 설정도 가능하지만, 관리자 등록 폼에 "할인 또는 보너스 중 하나만 설정하는 걸 권장" 안내 문구 표시 (강제 제한은 아님)

```
vouchers                             -- 기존 테이블에 컬럼 추가
  - ...(QR_PAYMENT_UNIFIED_SPEC.md 기존 필드 동일)
  - product_id            -- 신규: 어떤 상품으로 구매됐는지 (통계/판매실적용)
  - purchase_price         -- 신규: 구매 당시 낱장 1개 환산 가격
                            --   = sale_price / total_count (total_count = voucher_count + bonus_count)
                            --   보너스 포함 총 개수로 나누므로, 보너스 상품일수록 낱장 환산가가 낮게 스냅샷됨 (정상 동작)
```

- `unit_price`, `discount_rate`가 나중에 바뀌어도 과거 `vouchers.purchase_price`는 불변 — 정산/매출 통계 정합성 보장

---

## 2. 관리자 화면 — 상품 관리

### 2.1 상품 리스트

| 컬럼 | 내용 |
|---|---|
| 상품명 | 예: "식권 10장 묶음" |
| 구성 | N장 (+보너스 K장이 있으면 "N+K" 형태로 표시) |
| 정가 | 개당 unit_price × N (할인 전 총액) |
| 할인율 | N% (없으면 "-") |
| 판매가 | sale_price (강조 표시) |
| 지급수량 | total_count (= voucher_count + bonus_count) |
| 상태 | 판매중 / 숨김 |
| 액션 | [수정] [숨김/판매재개] |

- 삭제 버튼 없음 — **비활성화(숨김)만 가능**, 하드 삭제 금지 (과거 판매 데이터 무결성 보호)

### 2.2 상품 등록/수정 폼

```
- 상품명 (텍스트)
- 식권 개수 (숫자, quick 버튼: 1장 / 5장 / 10장 + 직접입력)
- 보너스 수량 (숫자, 기본 0 — "10장 구매 시 1장 더!" 같은 프로모션용)
- 개당 정가 (원)
- 할인율 (%, 0~100, 기본 0)
- ⚠️ 할인율과 보너스 수량을 동시에 0이 아닌 값으로 설정하면 "두 프로모션을 동시 적용하시겠어요?" 확인 안내 표시 (막지는 않음)
- ── 미리보기 (실시간 계산) ──
  정가: {unit_price × voucher_count}원
  할인: -{할인액}원 ({discount_rate}%)
  판매가: {sale_price}원  ← 강조
  실제 지급 수량: {voucher_count}장 + 보너스 {bonus_count}장 = 총 {total_count}장
- 판매 상태 (판매중/숨김) 토글
```

- 할인율 0~100 범위 벗어나는 값 입력 방지 (프론트+백엔드 이중 검증)
- 저장 시 `sale_price`는 서버에서 재계산해서 저장 (클라이언트 계산값 신뢰 안 함 — 결제 금액 조작 방지)

---

## 3. API 스펙

### 3.1 관리자용

```
GET    /admin/voucher-products              -- 전체 목록 (활성+비활성)
POST   /admin/voucher-products               -- 생성 { name, voucher_count, unit_price, discount_rate }
PATCH  /admin/voucher-products/:id            -- 수정 (동일 필드 + status)
```
- `sale_price`는 요청 바디로 받지 않고 서버가 항상 재계산

### 3.2 사용자 앱용

```
GET /vouchers/products
  → status='active'인 상품만, display_order 순 반환
```

### 3.3 구매 API (QR_PAYMENT_UNIFIED_SPEC.md 섹션 7.3 대체)

```
POST /vouchers/purchase
Request: { account_id, product_id }   -- 기존 quantity 방식에서 product_id 방식으로 변경

처리 로직:
1. account.account_type == 'voucher' 확인 (아니면 403)
2. product 조회, status='active' 확인 (숨긴 상품 구매 시도 → 404)
3. 토스페이먼츠 결제위젯 호출 (금액 = product.sale_price)  ※ bonus_count는 결제금액에 영향 없음
4. 결제 성공 웹훅 수신 →
   - total_count = product.voucher_count + product.bonus_count
   - vouchers 레코드를 total_count만큼 생성
     (status='unused', restaurant_id=돈토식당 고정값,
      product_id=product.id, purchase_price=product.sale_price / total_count)
5. 결제 실패/취소 → vouchers 생성 안 함
```

---

## 4. 앱 UI — 구매 화면

```
[식권 1장]
  8,000원
  [구매하기]

[식권 10장 묶음]  🏷️ 10% 할인
  ~~80,000원~~ → 72,000원   (8,000원 절약)
  [구매하기]

[식권 10+1]  🎁 1장 보너스
  10장 값 80,000원 → 총 11장 지급
  [구매하기]
```

- 할인 있는 상품은 정가 취소선 + 판매가 강조 + 할인 뱃지
- `GET /vouchers/products` 결과를 `display_order` 순으로 카드 나열
- 카드 클릭 → 토스페이먼츠 결제위젯 오픈 (기존 QR_PAYMENT_UNIFIED_SPEC.md 섹션 7.2 테스트키/라이브키 프로세스 그대로 적용)

---

## 5. QR 스캔 소모 — 변경 없음 (참고용 재확인)

- `QR_PAYMENT_UNIFIED_SPEC.md` 섹션 3의 `POST /transactions/scan` 로직 그대로 사용
- 상품 종류(1장/10장 묶음)와 무관하게, `vouchers` 테이블에서 `status='unused'` FIFO로 1건씩 차감
- 즉 이 스펙은 **"어떻게 사는지"**만 정의하고, **"어떻게 쓰는지"**는 기존 문서에 위임

---

## 6. 정산/통계 연동

- `VENDOR_TRANSACTION_MODAL_SPEC.md`의 거래내역에는 영향 없음 (여전히 `pay_type='voucher'`는 정산 대상 아님)
- 추후 "상품별 판매 실적" 화면이 필요해지면 `vouchers.product_id` 기준으로 집계 가능하도록 미리 컬럼만 마련해둠 (이번 범위에는 화면 구현 포함 안 함)

---

## 7. 구현 순서 (마일스톤)

1. **M1**: `voucher_products` 스키마 생성 + `vouchers`에 `product_id`, `purchase_price` 컬럼 추가 (마이그레이션)
2. **M2**: 관리자 상품 등록/수정 화면 + `/admin/voucher-products` API
3. **M3**: 사용자 앱 구매 화면을 상품 카드 방식으로 교체, `POST /vouchers/purchase`를 `product_id` 기반으로 변경
4. **M4**: QA — 할인 계산 정확성, 비활성 상품 숨김, 기존 QR 소모 로직과의 연동 확인

## 8. 완료 기준 (Acceptance Criteria)

- [ ] 관리자가 "식권 10장 묶음, 10% 할인"으로 등록하면 판매가가 72,000원으로 정확히 계산됨
- [ ] 관리자가 "식권 10+1"(voucher_count=10, bonus_count=1)로 등록하면, 결제금액은 10장 값(80,000원)이지만 구매 시 vouchers가 총 11건 생성됨
- [ ] 판매가는 클라이언트가 아닌 **서버에서 재계산**되어 저장됨 (요청 조작 방지)
- [ ] 상품을 숨김 처리하면 앱 구매 화면에서 즉시 사라짐 (기존 구매자의 보유 식권엔 영향 없음)
- [ ] 10장 묶음 구매 시 `vouchers` 10건이 생성되고, 각 건의 `purchase_price`가 정확히 스냅샷됨
- [ ] 이후 관리자가 상품 가격/할인율을 변경해도, 과거 구매 건의 `purchase_price`는 그대로 유지됨
- [ ] QR 스캔 시 상품 종류와 무관하게 기존 FIFO 소모 로직이 정상 동작함

## 9. 금지 사항 / 주의

- 상품 하드 삭제(DELETE) 금지 — 반드시 `status='inactive'` 처리만
- `sale_price`를 클라이언트 요청값으로 그대로 신뢰해서 저장하는 로직 금지 — 반드시 서버 재계산
- 할인율 0~100 범위 밖 값 저장 금지 (프론트/백엔드 이중 검증 필수)
- 상품 가격 변경 시 이미 발급된 `vouchers.purchase_price`를 소급 수정하는 로직 금지
