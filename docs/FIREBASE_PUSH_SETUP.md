# Firebase 푸시 알림 설정

코드는 Firebase 설정이 없어도 기존 앱/API가 정상 실행되도록 구성되어 있다. 실제 FCM 발송을 활성화하려면 아래 설정을 완료한다.

## 1. Firebase 프로젝트와 Android 앱

1. [Firebase Console](https://console.firebase.google.com/)에서 프로젝트를 만든다.
2. Android 앱을 추가한다.
3. Android 패키지 이름은 정확히 다음 값을 사용한다.

```text
com.greeneatgo.greeneatgo_customer
```

4. 프로젝트 설정의 Android 앱에서 아래 공개 클라이언트 값을 확인한다.

```text
FIREBASE_API_KEY
FIREBASE_APP_ID
FIREBASE_MESSAGING_SENDER_ID
FIREBASE_PROJECT_ID
```

이 프로젝트는 `google-services.json`을 저장소에 넣는 대신 Flutter `--dart-define`으로 `FirebaseOptions`를 전달한다.

## 2. Flutter APK 설정

로컬 전용 `apps/admin/.env`에 아래 값을 추가한다. Firebase Admin 서비스 계정 키는 이 파일에 넣지 않는다.

```dotenv
FIREBASE_API_KEY=...
FIREBASE_APP_ID=1:...:android:...
FIREBASE_MESSAGING_SENDER_ID=...
FIREBASE_PROJECT_ID=...
```

기존 빌드 스크립트를 실행하면 네 값이 모두 있을 때만 FCM을 활성화한다.

```powershell
powershell -ExecutionPolicy Bypass -File D:\projects\greeneatGo\apps\customer\build_apk_from_admin_env.ps1
```

네 값 중 일부만 있으면 잘못된 APK 생성을 막기 위해 스크립트가 실패한다. 값이 하나도 없으면 FCM만 비활성화한 기존 호환 APK가 생성된다.

## 3. 서버 Firebase Admin 키

Firebase Console → 프로젝트 설정 → 서비스 계정 → 새 비공개 키 생성에서 JSON을 내려받는다.

키 파일을 Git에 추가하지 않는다. Render 등 API 서버 환경변수에 아래 둘 중 정확히 하나만 설정한다.

### JSON 문자열

```text
FIREBASE_SERVICE_ACCOUNT_JSON={"type":"service_account",...}
```

### 또는 JSON 파일 전체를 Base64로 인코딩

```text
FIREBASE_SERVICE_ACCOUNT_JSON_BASE64=...
```

서비스 계정 환경변수가 없거나 잘못되면 공지 발송 API만 `FCM_NOT_CONFIGURED`로 실패하며 결제·로그인 등 다른 API는 계속 동작한다.

## 4. Supabase 마이그레이션

Supabase SQL Editor에서 순서대로 적용한다.

```text
infra/migrations/0021_app_users_self_update_hardening.sql
infra/migrations/0022_push_notifications.sql
```

`0022`는 다음을 생성한다.

- `device_tokens`: 계정별 Android/iOS FCM 토큰
- `notifications`: 식당별 발송 이력
- `register_device_token`, `unregister_device_token`: 서비스 역할 전용 RPC
- RLS 및 클라이언트 직접 접근 차단

## 5. 배포 순서

1. Supabase `0022` 마이그레이션 적용
2. API 서버에 Firebase Admin 환경변수 설정
3. 변경된 FastAPI 배포
4. Firebase 클라이언트 값이 포함된 APK 빌드·설치
5. 앱 로그인 후 알림 권한 허용
6. 식당관리자 웹 → `공지 발송`에서 대상 인원 확인 후 테스트 공지 발송

## 6. 실기기 QA

- 장부직원 계정과 일반사용자 계정으로 각각 로그인한다.
- `전체 사용자` 발송 시 두 기기 모두 수신하는지 확인한다.
- `일반 사용자만` 발송 시 일반사용자만 수신하는지 확인한다.
- 앱 전면 실행 중에는 앱 내부 배너가 보이는지 확인한다.
- 앱이 백그라운드/종료 상태일 때 시스템 알림이 보이는지 확인한다.
- 로그아웃 후 이전 계정 공지를 더 이상 받지 않는지 확인한다.
- 앱 삭제로 무효화된 토큰이 있어도 다른 기기 발송이 계속되는지 확인한다.

> 관리자 화면의 `성공`은 FCM 서버가 메시지를 접수한 수치이며 사용자가 실제로 읽은 수치는 아니다.

## 공식 문서

- [Flutter FCM 시작하기](https://firebase.google.com/docs/cloud-messaging/flutter/get-started)
- [Firebase Admin SDK multicast 발송](https://firebase.google.com/docs/cloud-messaging/send/admin-sdk)
