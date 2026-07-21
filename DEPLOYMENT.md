# greeneatGo 배포 가이드

## 운영 구성

| 구성 | 서비스 | 운영 주소 |
|---|---|---|
| 관리자 웹 | Vercel | `https://greeneatgo.vercel.app` |
| API | Render | `https://greeneatgo-api.onrender.com/v1` |
| DB/Auth/Storage | Supabase | 프로젝트별 URL |
| Android 앱 | Flutter APK/AAB | 배포 파일 |

## 1. 사전 확인

- 운영 Supabase 프로젝트와 백업 정책
- `infra/migrations` 적용 현황
- GitHub `main` 배포 권한
- Render·Vercel 프로젝트 연결
- 키움페이 테스트/운영 키
- 필요 시 SendGrid와 Firebase 프로젝트

비밀값은 Git, `VITE_` 환경변수, Flutter 클라이언트에 넣지 않습니다.

## 2. FastAPI / Render

### 설정

| 항목 | 값 |
|---|---|
| Root Directory | `services/api` |
| Runtime | Python 3.12 |
| Build Command | `pip install -e .` |
| Start Command | `bash start.sh` |
| Health Check | `/v1/health` |

### 필수 환경변수

```dotenv
SUPABASE_URL=https://PROJECT.supabase.co
SUPABASE_ANON_KEY=...
SUPABASE_SERVICE_ROLE_KEY=...
KIWOOMPAY_CPID=...
KIWOOMPAY_AUTHORIZATION_KEY=...
KIWOOMPAY_BASE_URL=https://apitest.kiwoompay.co.kr
PUBLIC_API_BASE_URL=https://greeneatgo-api.onrender.com/v1
ADMIN_APP_URL=https://greeneatgo.vercel.app
CORS_ALLOWED_ORIGINS=http://localhost:5173,https://greeneatgo.vercel.app
```

선택 환경변수:

```dotenv
SUPABASE_JWT_SECRET=
PILOT_MERCHANT_ID=
SENDGRID_API_KEY=
INVITE_EMAIL_FROM=GreenEatGo <verified-sender@example.com>
FIREBASE_SERVICE_ACCOUNT_JSON=
FIREBASE_SERVICE_ACCOUNT_JSON_BASE64=
```

Firebase Admin 서비스 계정은 JSON 또는 Base64 중 하나만 설정합니다. `services/api/render.yaml`보다 `services/api/.env.example`과 `services/api/app/config.py`의 실제 요구값이 우선입니다.

### 배포 확인

```bash
curl -fsS https://greeneatgo-api.onrender.com/v1/health
```

정상 예:

```json
{"ok":true,"data":{"service":"greeneatgo-api"},"error":null}
```

## 3. 관리자 웹 / Vercel

### 설정

| 항목 | 값 |
|---|---|
| Framework | Vite |
| Root Directory | `apps/admin` |
| Install | `npm install` |
| Build | `npm run build` |
| Output | `dist` |

### 환경변수

```dotenv
VITE_SUPABASE_URL=https://PROJECT.supabase.co
VITE_SUPABASE_ANON_KEY=...
VITE_API_BASE_URL=https://greeneatgo-api.onrender.com/v1
VITE_AUTH_EMAIL_REDIRECT_TO=https://greeneatgo-api.onrender.com/v1/auth/confirmed
```

`SUPABASE_SERVICE_ROLE_KEY`, 키움페이 secret, SendGrid key, Firebase Admin 키는 Vercel에 넣지 않습니다.

### 확인

```bash
curl -I https://greeneatgo.vercel.app
```

로그인 후 `company_admin`, `merchant_admin`, `platform_admin` 각각 자신의 화면만 보이는지 확인합니다.

## 4. Supabase

전체 절차는 [SETUP_SUPABASE_WEB.md](SETUP_SUPABASE_WEB.md)를 따릅니다.

배포 전 최소 확인:

- 마이그레이션 `0001~0029` 실제 적용 상태
- RLS와 RPC 실행권
- Email Auth와 Redirect URL
- 이미지 Storage 버킷과 정책
- `process_meal_pay` 최신 정의
- 포인트 전액 결제의 `amount >= 0` 제약

기존 운영 DB에는 모든 SQL을 무조건 재실행하지 않습니다. 파일별 idempotency와 실제 스키마를 확인한 뒤 필요한 마이그레이션만 적용합니다.

## 5. Android APK

표준 Windows 빌드:

```powershell
powershell -ExecutionPolicy Bypass -File D:\projects\greeneatGo\apps\customer\build_apk_from_admin_env.ps1
```

출력:

```text
apps\customer\build\app\outputs\flutter-apk\app-release.apk
```

배포 전:

1. `apps/customer/pubspec.yaml`의 build number 증가
2. Flutter test/analyze
3. release build
4. `aapt dump badging`으로 package/version 확인
5. SHA-256 기록
6. 기존 앱 위 업데이트 설치

현재 Android release 설정은 debug signing을 사용하므로 내부 테스트 전용입니다. Play Store 또는 정식 외부 배포 전에 운영 keystore를 구성합니다.

## 6. Auth 이메일 확인

Supabase Authentication URL Configuration:

```text
Site URL: https://greeneatgo-api.onrender.com
Redirect URL: https://greeneatgo-api.onrender.com/v1/auth/confirmed
```

한글 템플릿은 [docs/SUPABASE_AUTH_EMAIL_KO.md](docs/SUPABASE_AUTH_EMAIL_KO.md)를 참고합니다.

## 7. 배포 순서

1. DB 백업·마이그레이션 확인
2. API 테스트
3. Supabase 필요한 마이그레이션 적용
4. Render 배포와 health 확인
5. 관리자 웹 build
6. Vercel 배포와 역할별 로그인 확인
7. Flutter test/analyze/build
8. 키움페이·QR·포인트·정산 핵심 E2E
9. FCM 사용 시 실기기 수신 확인

배포 후 점검은 [운영 체크리스트](docs/OPERATIONS_CHECKLIST.md)를 사용합니다.
