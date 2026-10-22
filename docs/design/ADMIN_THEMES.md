# 관리자 화면 테마 (Admin UI themes)

관리자 웹(식당·회사·플랫폼 관리자)은 계정마다 화면 테마를 고를 수 있다.
기본값 `default` = 지금 쓰는 밝은 화면. `calm-dark` = 17-8 Calm Dark (`ADMIN_REDESIGN_17-8.md`).
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
| `apps/admin/src/themes/skins.css` | 모양(티켓 카드, 알약 탭, 점선 표 …). `:root[data-skin="ticket"]` |
| 사이드바 "화면 테마" 선택칸 | 바꾸면 바로 적용 → 서버 저장, 실패하면 이전 테마로 되돌림 |

- 기본 테마는 `style.css` 그대로다. 테마/스킨 CSS는 모든 선택자가 `:root[data-theme=…]` 또는
  `:root[data-skin=…]` 로 시작해야 하고, `test/themes.test.js` 가 이를 검사한다 → 기본 화면은 바뀔 수 없다.
- 로그인 화면은 그 브라우저에서 마지막으로 쓴 테마를 따른다(로컬 저장, 표시용). 로그인 후에는 계정 설정이 우선.
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
화면 문구·역할(버튼 이름, 탭 이름, 제목)은 테마에서 바꾸지 않는다 — 브라우저 테스트가 찾는다.
