# Supabase Web 연결 세팅 가이드

이 프로젝트는 로컬 Supabase가 아니라 Supabase 웹 프로젝트에 연결한다.

## 1. Supabase 프로젝트 생성

1. https://supabase.com 에 로그인한다.
2. `New project`를 만든다.
3. Region은 파일럿 사용자가 한국이면 가까운 리전(예: Northeast Asia 계열)을 고른다.
4. DB Password는 안전하게 저장한다.

## 2. API Keys 확인

Supabase Dashboard에서:

```text
Project Settings → API
```

아래 값을 확인한다.

| 값 | 사용처 | 보안 |
|---|---|---|
| Project URL | API/앱/웹 공통 | 공개 가능 |
| anon public key | 직원앱/관리자웹 로그인 | 공개 가능 |
| service_role key | FastAPI 서버 전용 | 절대 앱/웹에 넣지 말 것 |
```

## 3. FastAPI 서버 환경변수

`services/api/.env` 파일을 만들고 아래 값을 채운다.

```bash
SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
SUPABASE_ANON_KEY=YOUR_ANON_PUBLIC_KEY
SUPABASE_SERVICE_ROLE_KEY=YOUR_SERVICE_ROLE_KEY
SUPABASE_JWT_SECRET=YOUR_JWT_SECRET
```

`SUPABASE_SERVICE_ROLE_KEY`는 FastAPI 서버에서만 사용한다.
Flutter/React 코드, Git, 클라이언트 번들에 절대 넣지 않는다.

## 4. 관리자 웹 환경변수

`apps/admin/.env` 파일을 만든다.

```bash
VITE_SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
VITE_SUPABASE_ANON_KEY=YOUR_ANON_PUBLIC_KEY
VITE_API_BASE_URL=http://localhost:8000/v1
```

관리자 웹에는 anon key만 넣는다.

## 5. Flutter 직원앱 환경값

M1에서는 `--dart-define`로 주입하는 방식을 사용한다.

```bash
flutter run \
  --dart-define=SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co \
  --dart-define=SUPABASE_ANON_KEY=YOUR_ANON_PUBLIC_KEY \
  --dart-define=API_BASE_URL=http://localhost:8000/v1
```

직원앱에도 service_role key를 넣지 않는다.

## 6. DB 마이그레이션 적용

Supabase Dashboard에서:

```text
SQL Editor → New query
```

아래 파일들을 순서대로 실행한다.

```text
infra/migrations/0001_initial.sql
infra/migrations/0002_rls_policies.sql
infra/migrations/0003_process_meal_pay_stub.sql
infra/migrations/0004_invite_join_approval.sql
infra/seed/001_pilot_seed.sql
```

주의: `0001_initial.sql`은 `auth.users`를 참조하므로 Supabase Auth가 있는 프로젝트에서 실행해야 한다.

## 7. Auth 설정

Supabase Dashboard에서:

```text
Authentication → Providers → Email
```

M1 추천:

- Email provider 활성화
- Confirm email 활성화
- Magic Link 로그인 사용

Redirect URL은 아래 운영 안내 페이지를 추가한다.

```text
https://greeneatgo-api.onrender.com/v1/auth/confirmed
```

Confirm signup 메일 한글 템플릿과 URL 설정은 `docs/SUPABASE_AUTH_EMAIL_KO.md`를 참고한다.

## 8. 오빠가 옥지에게 알려주면 되는 값

보안 때문에 service_role key는 텔레그램에 그대로 보내지 않는 게 제일 좋아.
가능하면 오빠 PC에서 `.env` 파일에 직접 넣어줘.

옥지가 다음 작업을 계속하려면 최소한 아래 중 하나가 필요하다.

### 안전한 방식 추천

오빠가 직접 아래 파일들을 생성:

```text
D:\projects\greeneatGo\services\api\.env
D:\projects\greeneatGo\apps\admin\.env
```

그다음 옥지에게 “넣었어”라고 말해주기.

### 값 공유 방식

공유가 필요하면 다음 값만 알려줘:

```text
SUPABASE_URL
SUPABASE_ANON_KEY
```

`SUPABASE_SERVICE_ROLE_KEY`는 직접 `.env`에 넣는 방식을 추천한다.

## 9. 연결 확인 체크리스트

- [ ] Supabase 프로젝트 생성 완료
- [ ] SQL 마이그레이션 0001~0004 실행 완료
- [ ] seed 실행 완료
- [ ] `services/api/.env` 생성 완료
- [ ] `apps/admin/.env` 생성 완료
- [ ] Email Auth 활성화
- [ ] Redirect URL 임시 등록
