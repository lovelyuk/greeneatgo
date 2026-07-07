# greeneatGo 배포 가이드

목표 배포 구조:

```text
관리자 웹: Vercel (`apps/admin`)
FastAPI: Render (`services/api`)
DB/Auth: Supabase Web
```

## 0. 사전 준비

- Supabase 프로젝트 생성 완료
- Supabase SQL 마이그레이션/seed 적용 완료
- GitHub 저장소에 `D:\projects\greeneatGo` 프로젝트 push 가능 상태

Render/Vercel은 보통 GitHub 저장소와 연결해서 배포한다.

---

## 1. FastAPI를 Render에 배포

### 1-1. Render Web Service 생성

1. https://render.com 접속
2. 로그인
3. `New +` 클릭
4. `Web Service` 선택
5. GitHub 저장소 연결
6. greeneatGo 저장소 선택

### 1-2. Render 설정값

| 항목 | 값 |
|---|---|
| Name | `greeneatgo-api` |
| Root Directory | `services/api` |
| Runtime | `Python 3` |
| Build Command | `pip install -e .` |
| Start Command | `bash start.sh` |
| Health Check Path | `/v1/health` |
| Instance Type | 처음은 Free 가능 |

`render.yaml`도 만들어두었지만, 초반에는 Render UI에서 직접 넣어도 된다.

### 1-3. Render 환경변수

Render 서비스의 `Environment` 메뉴에 아래 값을 넣는다.

```bash
SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
SUPABASE_ANON_KEY=YOUR_ANON_PUBLIC_KEY
SUPABASE_SERVICE_ROLE_KEY=YOUR_SERVICE_ROLE_KEY
SUPABASE_JWT_SECRET=YOUR_JWT_SECRET
CORS_ALLOWED_ORIGINS=http://localhost:5173,https://YOUR_VERCEL_APP.vercel.app
```

주의:

- `SUPABASE_SERVICE_ROLE_KEY`는 Render API 서버에만 넣는다.
- Vercel/Flutter/브라우저 코드에 넣으면 안 된다.

### 1-4. Render 배포 확인

배포 완료 후 Render가 API URL을 준다.

예:

```text
https://greeneatgo-api.onrender.com
```

브라우저에서 확인:

```text
https://greeneatgo-api.onrender.com/v1/health
```

정상 응답:

```json
{"ok":true,"data":{"service":"greeneatgo-api"},"error":null}
```

---

## 2. 관리자 웹을 Vercel에 배포

### 2-1. Vercel 프로젝트 생성

1. https://vercel.com 접속
2. 로그인
3. `Add New...` → `Project`
4. GitHub 저장소 import
5. greeneatGo 저장소 선택

### 2-2. Vercel 설정값

| 항목 | 값 |
|---|---|
| Framework Preset | `Vite` |
| Root Directory | `apps/admin` |
| Install Command | `npm install` |
| Build Command | `npm run build` |
| Output Directory | `dist` |

### 2-3. Vercel 환경변수

Vercel 프로젝트의 `Settings → Environment Variables`에 추가한다.

```bash
VITE_SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
VITE_SUPABASE_ANON_KEY=YOUR_ANON_PUBLIC_KEY
VITE_API_BASE_URL=https://greeneatgo-api.onrender.com/v1
```

주의:

- Vercel에는 `SUPABASE_SERVICE_ROLE_KEY`를 절대 넣지 않는다.
- `VITE_API_BASE_URL`은 Render API 주소 + `/v1`이다.

### 2-4. Vercel 배포 확인

Vercel이 발급한 주소 예:

```text
https://greeneatgo-admin.vercel.app
```

이 주소를 Render의 `CORS_ALLOWED_ORIGINS`에 추가해야 브라우저 API 호출이 막히지 않는다.

---

## 3. CORS 최종 설정

Vercel 주소가 확정되면 Render 환경변수 `CORS_ALLOWED_ORIGINS`를 이렇게 수정한다.

```bash
CORS_ALLOWED_ORIGINS=http://localhost:5173,https://greeneatgo-admin.vercel.app
```

수정 후 Render에서 `Manual Deploy` 또는 `Restart Service`를 실행한다.

---

## 4. Supabase Auth Redirect URL

Supabase Dashboard:

```text
Authentication → URL Configuration → Redirect URLs
```

아래를 추가한다.

```text
http://localhost:5173/auth/callback
https://greeneatgo-admin.vercel.app/auth/callback
greeneatgo://login-callback
```

Vercel 실제 도메인으로 바꿔 넣는다.

---

## 5. 배포 후 점검 순서

1. Render API health 확인

```text
https://YOUR_RENDER_API/v1/health
```

2. Vercel 관리자 웹 접속
3. 관리자 로그인 구현 후 Supabase Auth 로그인 확인
4. 관리자 웹에서 `VITE_API_BASE_URL`로 API 호출 확인
5. 직원 가입요청 → 관리자 승인 플로우 확인

---

## 6. 현재 테스트 계정 주의

개발 중 생성한 테스트 계정은 운영 전 교체한다.

- `admin@greeneatgo.test`
- `employee1@greeneatgo.test`

운영/파일럿에서는 실제 관리자 이메일을 Supabase Auth에 생성하고 `app_users.role='company_admin'`으로 연결한다.
