# PUSH_NOTIFICATION_SPEC.md
> MEALLEDGER — 식당관리자 웹에서 앱으로 푸시 공지 발송 스펙
> 버전: v1.0 / 대상 에이전트: Codex / Claude Code
> 연관 문서: `QR_PAYMENT_UNIFIED_SPEC.md`(accounts 모델), `VOUCHER_PRODUCT_SPEC.md`(이벤트 상품)
> 목적: 식당관리자가 앱 사용자에게 공지/이벤트 알림을 푸시로 발송

---

## 0. 핵심 결정 사항

- 발송 채널: **FCM(Firebase Cloud Messaging)** — Android/iOS 공통 지원, 무료
- 발송 대상 타입 2가지:
  - **전체 공지 (`all`)**: 장부소속 직원(`account_type='ledger'`) + 개인 식권 구매자(`account_type='voucher'`) 전원. 식당 공사/휴무 등 모두가 알아야 할 공지용
  - **일반사용자 전용 (`voucher_only`)**: `account_type='voucher'`인 계정에게만. 이벤트 상품처럼 개인 구매자에게만 해당되는 내용용
- 이번 범위는 **관리자가 직접 작성해서 수동 발송**하는 것까지만. 이벤트 등록 시 자동발송은 다음 단계(범위 밖)

---

## 1. 데이터 모델

```
device_tokens                        -- 앱 기기별 FCM 토큰
  - id
  - account_id           (FK → accounts)
  - fcm_token
  - platform: 'android' | 'ios'
  - updated_at            -- 토큰 갱신될 때마다 upsert

notifications                        -- 발송 이력 로그
  - id
  - title
  - body
  - target_type: 'all' | 'voucher_only'
  - target_count           -- 발송 시도 대상자 수
  - success_count           -- 실제 발송 성공 수
  - sent_at
```

- `device_tokens`는 계정당 1개 기기 이상 가질 수 있음 (기기 변경 시 새 토큰 추가, 기존 토큰은 무효 처리되면 발송 실패로 자연스럽게 걸러짐)

---

## 2. 관리자 화면 — 공지 작성

```
┌───────────────────────────────────┐
│  공지 발송                          │
├───────────────────────────────────┤
│  발송 대상                          │
│  ⦿ 전체 사용자 (장부직원 + 일반사용자)│
│  ○ 일반 사용자만 (개인 식권 구매자)    │
│                                     │
│  제목  [_____________________]     │
│  내용                              │
│  [_____________________________]  │
│  [_____________________________]  │
│                                     │
│         [미리보기]   [발송하기]     │
└───────────────────────────────────┘

발송 이력
┌───────────────────────────────────┐
│ 날짜        대상       제목    발송/성공 │
│ 7/10 14:30  전체       공사안내  152/149 │
│ 7/8  10:00  일반사용자  이벤트   98/97   │
└───────────────────────────────────┘
```

- [발송하기] 클릭 시 확인 다이얼로그: "총 N명에게 발송됩니다. 진행할까요?" (대상 인원수 미리 계산해서 보여줌)
- 발송 후 되돌리기 불가 (푸시 특성상 취소 개념 없음) — 확인 절차를 확실히 거치게 함
- 발송 이력에서 과거 공지 재확인 가능 (재발송 기능은 이번 범위 밖)

---

## 3. API 스펙

### 3.1 앱 — 토큰 등록

```
POST /device-tokens
Request: { account_id, fcm_token, platform }
→ 기존 토큰 있으면 upsert, 없으면 생성
→ 앱 최초 로그인 시 + 토큰 갱신 이벤트 발생 시 호출
```

### 3.2 관리자 — 발송

```
POST /admin/notifications
Request: { title, body, target_type }   -- target_type: 'all' | 'voucher_only'

처리 로직:
1. target_type에 따라 대상 계정 조회
   - all:          accounts WHERE status='active'
   - voucher_only: accounts WHERE account_type='voucher' AND status='active'
2. 대상 계정들의 device_tokens 전체 조회
3. FCM Admin SDK의 multicast 발송 사용 (한 번에 최대 500개씩 배치 처리)
4. 발송 결과(성공/실패 개수) 집계
5. notifications 테이블에 이력 저장 (target_count, success_count)
```

- 실패한 개별 토큰(앱 삭제 등으로 무효화된 토큰)이 있어도 **전체 발송은 중단하지 않고 계속 진행**
- 대상자가 0명이면 발송 자체를 막고 "발송 대상이 없습니다" 에러 반환

### 3.3 GET /admin/notifications — 발송 이력 조회

```
→ 최신순 리스트, { title, target_type, target_count, success_count, sent_at }
```

---

## 4. 발송 대상 계산 기준

| target_type | 대상 |
|---|---|
| `all` | `account_type IN ('ledger', 'voucher')` AND `status='active'` |
| `voucher_only` | `account_type='voucher'` AND `status='active'` |

- `status='invited'`(아직 앱 인증 안 한 계정)는 발송 대상에서 제외 — 어차피 기기 토큰이 없어서 자연스럽게 걸러짐, 명시적으로도 조건에 넣어 명확히 함

---

## 5. 보안/운영 주의

- Firebase 서비스 계정 키(비공개 키)는 **서버 환경변수로만 관리**, 클라이언트/저장소에 노출 금지
- 발송 API는 관리자 인증(로그인 세션) 확인 후에만 호출 가능하도록 보호

---

## 6. 구현 순서 (마일스톤)

1. **M1**: `device_tokens`, `notifications` 스키마 생성 + 앱에 FCM SDK 연동, 토큰 등록 API
2. **M2**: 관리자 공지 작성 화면 + `POST /admin/notifications` API (대상 계산 로직 포함)
3. **M3**: FCM multicast 발송 로직 (firebase-admin SDK) + 발송 이력 저장/조회
4. **M4**: QA — 대상 타입별 필터링 정확성, 무효 토큰 처리, 0명 발송 방지 확인

## 7. 완료 기준 (Acceptance Criteria)

- [ ] "전체" 선택 시 장부직원 + 일반사용자 모두에게 발송됨
- [ ] "일반 사용자만" 선택 시 장부소속 직원에게는 발송되지 않음
- [ ] 발송 이력에 대상자 수(target_count)와 실제 성공 수(success_count)가 정확히 기록됨
- [ ] 무효화된 토큰으로 인한 개별 발송 실패가 전체 발송을 중단시키지 않음
- [ ] 발송 대상이 0명이면 발송 자체가 막히고 안내 메시지가 표시됨
- [ ] `status='invited'` 계정은 발송 대상에서 제외됨

## 8. 금지 사항 / 주의

- Firebase 서비스 계정 키를 클라이언트 코드나 저장소(git)에 노출 금지 — 서버 환경변수로만 관리
- 관리자 인증 없이 발송 API 호출 가능하게 두는 것 금지
- 발송된 공지를 취소/회수하는 기능 구현 시도 금지 (FCM 특성상 불가능, UI에서도 발송 전 확인 절차로만 방지)
