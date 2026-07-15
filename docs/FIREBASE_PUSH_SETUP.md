# Firebase 푸시 알림 설정

## 현재 식별자

Android 패키지 ID:

```text
com.greeneat.greeneatgo
```

Firebase Android 앱은 반드시 이 패키지 ID로 등록합니다.

## 1. Flutter 클라이언트 설정

현재 표준 빌드 스크립트:

```text
apps/customer/build_apk_from_admin_env.ps1
```

스크립트는 다음 순서로 Firebase 공개 클라이언트 값을 찾습니다.

1. `apps/admin/.env`의 네 값
2. 값이 없으면 `apps/customer/android/app/google-services.json`에서 패키지 ID가 일치하는 Android client

필요 값:

```dotenv
FIREBASE_API_KEY=...
FIREBASE_APP_ID=1:...:android:...
FIREBASE_MESSAGING_SENDER_ID=...
FIREBASE_PROJECT_ID=...
```

네 값이 모두 있으면 빌드에 다음이 자동 추가됩니다.

```text
--dart-define=FIREBASE_ENABLED=true
```

일부 값만 있으면 잘못된 APK 생성을 막기 위해 빌드가 실패합니다. 값이 하나도 없으면 앱의 FCM 기능만 비활성화됩니다.

`google-services.json`은 Firebase Admin 비밀키가 아니지만 Firebase 프로젝트 식별값을 포함합니다. 저장소 정책을 유지하려면 Google API key 제한, 허용 앱 패키지와 SHA 인증서 설정을 검토합니다. Firebase Admin 서비스 계정 JSON은 절대 저장소에 넣지 않습니다.

## 2. APK 빌드

```powershell
powershell -ExecutionPolicy Bypass -File D:\projects\greeneatGo\apps\customer\build_apk_from_admin_env.ps1
```

빌드 후 APK 내부 package가 `com.greeneat.greeneatgo`인지 확인합니다.

## 3. 서버 Firebase Admin

Firebase Console에서 서비스 계정 비공개 키를 생성하고 Render 환경변수에 다음 중 하나만 설정합니다.

### JSON 문자열

```dotenv
FIREBASE_SERVICE_ACCOUNT_JSON={"type":"service_account",...}
```

### Base64

```dotenv
FIREBASE_SERVICE_ACCOUNT_JSON_BASE64=...
```

키가 없거나 잘못되면 공지 발송만 `FCM_NOT_CONFIGURED`로 실패하고 로그인·결제 API는 계속 동작합니다.

## 4. DB 요구사항

최소 다음 마이그레이션이 실제 운영 DB에 적용돼야 합니다.

```text
0021_app_users_self_update_hardening.sql
0022_push_notifications.sql
```

`0022`는 기기 토큰, 발송 이력, 등록·해제 RPC와 접근 정책을 만듭니다.

## 5. 배포 순서

1. 운영 DB의 `0021`, `0022` 적용 확인
2. Firebase Android 앱 package 확인
3. Render에 Firebase Admin 키 설정
4. API 배포
5. Firebase 공개 client 값이 포함된 APK 빌드
6. 앱 설치·로그인·알림 권한 허용
7. 식당관리자 웹에서 대상 인원 확인 후 테스트 공지

## 6. 실기기 QA

- [ ] 장부 직원 로그인 후 device token 등록
- [ ] 일반 사용자 로그인 후 device token 등록
- [ ] 전체 대상은 두 사용자 모두 수신
- [ ] 일반 사용자 대상은 일반 사용자만 수신
- [ ] 앱 전면에서 로컬 알림 표시
- [ ] 백그라운드에서 시스템 알림 표시
- [ ] 앱 종료 상태에서 시스템 알림 표시
- [ ] 토큰 갱신 후 중복 기기 처리
- [ ] 로그아웃 후 이전 계정 토큰 해제
- [ ] 앱 삭제로 무효화된 토큰이 다른 발송을 중단하지 않음

관리자 화면의 성공 수치는 FCM 서버가 접수한 결과이며 사용자가 읽은 수치는 아닙니다.

## 7. 장애 확인 순서

1. 관리자 대상 인원 수
2. 등록된 기기 수
3. 고유 발송 가능 사용자 수
4. APK의 `FIREBASE_ENABLED`
5. package ID와 Firebase Android 앱 일치
6. 로그인 후 token 등록 API 응답
7. Render Firebase Admin 환경변수
8. Android 알림 권한과 배터리 제한

대상 사용자가 있어도 등록 기기가 0이면 audience 쿼리보다 설치→로그인→권한→토큰 등록 흐름을 먼저 확인합니다.
