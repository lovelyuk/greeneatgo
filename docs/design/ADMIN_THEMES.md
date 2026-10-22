# 관리자 화면 테마 (Admin UI themes)

관리자 웹(식당·회사·플랫폼 관리자)은 계정마다 화면 테마를 고를 수 있다.
| id | 이름 | 모양(skin) | 대시보드 | 비고 |
|---|---|---|---|---|
| `default` | 기본 | – | classic | 지금 쓰는 밝은 화면 |
| `calm-dark` | Calm Dark | ticket | classic | 17-8 (`ADMIN_REDESIGN_17-8.md`). 추가 위젯 있음 |
| `forest-stubs` | Forest Day Stubs | ticket | forest | 06 배치 + 16-2 색. 큰 카드 탭 = 식권 달력 / 기간별 매출 (`admin-dashboard-forest-daystubs.html`) |
| `forest` | Forest | forest | forest | 06 Forest (`admin-dashboard-variants.html` v6). 탭 = 기간별 매출 / 기간별 수량 |
| `compact` | Compact Table | compact | compact | 12 Compact Table (`admin-dashboard-variants-2.html` v12). 숫자 띠 + 짧은 그래프 + 거래처 표 |
구매자 웹 `/shop`, 카운터 `/counter`는 대상이 아니다.

## 구조

| 위치 | 역할 |
|---|---|
| `supabase/migrations/0070_admin_ui_theme.sql` | `app_users.admin_ui_theme` (기본 `'default'`, 형식만 검사) |
| `services/api/app/admin_themes.py` | 서버가 받아주는 테마 id 목록 |
| `GET /v1/me` → `admin_theme` | 관리자 계정의 저장된 테마 (컬럼이 없으면 `default`) |
| `PATCH /v1/me/preferences` `{ "admin_theme": "calm-dark" }` | 본인 계정에만 저장. 활성 관리자만 가능 |
| `apps/admin/src/themes.js` | 테마 목록(라벨·skin·extras·로고) + `<html data-theme data-skin>` 적용 |
| `apps/admin/src/themes/<id>.css` | 그 테마의 **색 토큰만** (`:root[data-theme="<id>"]`) |
| `apps/admin/src/themes/skins.css` | 모양. skin 별 블록: `ticket`(티켓 카드·점선 표), `forest`(숲색 사이드바·크림), `compact`(얇은 선·촘촘한 표) |
| `apps/admin/src/themes/layouts.css` | 대시보드 배치 `:root[data-dashboard="forest" \| "compact"]` (+ 식권 달력) |
| 사이드바 "화면 테마" 선택칸 | 바꾸면 바로 적용 → 서버 저장, 실패하면 이전 테마로 되돌림 |

- 기본 테마는 `style.css` 그대로다. 테마/스킨 CSS는 모든 선택자가 `:root[data-theme=…]` 또는
  `:root[data-skin=…]` 로 시작해야 하고, `test/themes.test.js` 가 이를 검사한다 → 기본 화면은 바뀔 수 없다.
- 로그인 화면은 그 브라우저에서 마지막으로 쓴 테마를 따른다(로컬 저장, 표시용). 로그인 후에는 계정 설정이 우선.
- 테마 항목의 스위치: `dashboard`(classic / forest / compact), `trendTabs`(forest 배치의 큰 카드 탭: `calendar`·`amount`·`count`, 순서대로),
  `navGroups`(사이드바 그룹 제목), `account`(계정 카드), `extras`(아래 위젯), `chart`(그래프 색), `logo`/`sidebarLogo`.
- 식권 달력은 일별 데이터(조회 기간 31일 이하)에서만 그려지고, 더 긴 기간이면 안내 문구를 보여준다. 새 API 없음 — `/admin/dashboard/summary` 의 series 그대로.
- `extras: true` 테마에서만 보이는 추가 위젯: 대시보드 "방금 들어온 결제", 리뷰 "별점 분포",
  오늘 뷔페 메뉴 "앱 미리보기", 사이드바 그룹 제목·계정 카드. 모두 이미 받아온 데이터로 계산한다(새 API 없음).

## 새 테마 추가 (예: 같은 티켓 모양, 다른 색)

1. `apps/admin/src/themes/calm-dark.css` 를 `<새id>.css` 로 복사하고 선택자를 `:root[data-theme="<새id>"]` 로 바꾼 뒤 색만 수정.
2. `apps/admin/src/themes.js` 의 `ADMIN_THEMES` 에 `{ id, label, description, skin: 'ticket', extras, scheme, logo }` 추가.
3. `apps/admin/src/main.jsx` 상단에 `import './themes/<새id>.css';` 추가 (테스트가 확인함).
4. `services/api/app/admin_themes.py` 의 `ADMIN_THEMES` 에 id 추가 (테스트가 웹 목록과 비교함).
5. DB 마이그레이션은 필요 없음.
6. 검증: `npm test`, 빌드, `npx playwright test browser/admin-theme.spec.mjs` (스크래치 복사본에서).

모양까지 다른 테마면 `skins.css` 에 새 skin 블록(`:root[data-skin="<새skin>"]`)을 만들고 `skin` 값을 그 이름으로 둔다.
기본 CSS(`style.css`)에 색이 직접 적힌 곳(쿠폰 카드, 상태 스위치, 이미지 선택칸 …)은 토큰을 안 따르므로, 새 skin 마다
`skins.css` 끝의 "hard-coded default greens" 블록처럼 덮어써야 한다. 놓친 곳은 색상 스캔(밝은 바탕/초록 계열 요소 탐지)으로 찾는다.
대시보드 배치를 새로 만들면 `layouts.css` 에 `:root[data-dashboard="<이름>"]` 블록 + `DashboardView` 에 분기를 추가한다.
화면 문구·역할(버튼 이름, 탭 이름, 제목)은 테마에서 바꾸지 않는다 — 브라우저 테스트가 찾는다.
