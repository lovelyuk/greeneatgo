# greeneatGo 사용자 앱

Flutter 기반 Android/iOS 사용자 앱입니다. 회사 직원과 일반 식권 사용자가 같은 앱과 매장 QR을 사용합니다.

## 주요 기능

- Supabase 이메일 가입·로그인
- 회사 초대코드 가입 요청
- 일반 사용자 등록
- 장부 월 이용액·잔여 한도·포인트
- 일반·지원 식권 Toss 구매
- 매장 QR 장부/식권 통합 결제
- 오늘 메뉴·최근 이용 내역
- 공지사항·구매 인증 리뷰
- 계정 이름·비밀번호 변경
- Firebase 푸시 알림

## 런타임 설정

필수 `--dart-define`:

```text
SUPABASE_URL
SUPABASE_ANON_KEY
API_BASE_URL
AUTH_EMAIL_REDIRECT_TO
```

FCM 선택 설정:

```text
FIREBASE_ENABLED
FIREBASE_API_KEY
FIREBASE_APP_ID
FIREBASE_MESSAGING_SENDER_ID
FIREBASE_PROJECT_ID
```

service role, Toss secret, Firebase Admin 서비스 계정은 앱에 넣지 않습니다.

## Windows 표준 APK 빌드

사전 조건:

- Flutter: `D:\dev\flutter`
- 프로젝트: `D:\projects\greeneatGo`
- 공개 환경값: `apps\admin\.env`

```powershell
powershell -ExecutionPolicy Bypass -File D:\projects\greeneatGo\apps\customer\build_apk_from_admin_env.ps1
```

출력:

```text
D:\projects\greeneatGo\apps\customer\build\app\outputs\flutter-apk\app-release.apk
```

빌드 스크립트는 `flutter clean`, `pub get`, release APK 빌드를 실행하고 각 native command의 exit code를 검사합니다.

## 개발 실행

```powershell
Set-Location D:\projects\greeneatGo\apps\customer
D:\dev\flutter\bin\flutter.bat pub get
D:\dev\flutter\bin\flutter.bat run `
  --dart-define=SUPABASE_URL=... `
  --dart-define=SUPABASE_ANON_KEY=... `
  --dart-define=API_BASE_URL=http://HOST:8000/v1 `
  --dart-define=AUTH_EMAIL_REDIRECT_TO=https://greeneatgo-api.onrender.com/v1/auth/confirmed
```

실기기에서 WSL/Windows localhost는 휴대폰의 localhost가 아닙니다. 같은 네트워크에서 접근 가능한 API 주소를 사용합니다.

## 테스트

```powershell
Set-Location D:\projects\greeneatGo\apps\customer
D:\dev\flutter\bin\flutter.bat analyze
D:\dev\flutter\bin\flutter.bat test
```

현재 자동 테스트는 기본 환경 안내와 식권 모델 계산 중심입니다. 로그인·QR 카메라·Toss WebView·FCM은 실기기 E2E를 병행합니다.

## Android 패키징

현재 package ID:

```text
com.greeneat.greeneatgo
```

배포할 때:

1. `pubspec.yaml` build number 증가
2. 테스트·분석
3. release 빌드
4. `aapt dump badging`으로 package/version 확인
5. APK SHA-256 기록
6. 기존 앱 위 업데이트 설치

현재 `android/app/build.gradle.kts`의 release는 debug signing을 사용합니다. 내부 테스트용이며 정식 배포 전에 운영 keystore로 교체해야 합니다.

## Firebase

자세한 설정과 실기기 QA는 다음 문서를 사용합니다.

```text
docs/FIREBASE_PUSH_SETUP.md
```

## iOS

iOS 소스는 존재하지만 IPA 생성·서명·TestFlight 배포에는 macOS, Xcode, Apple Developer 계정과 실제 Bundle ID 정리가 필요합니다. Android의 Firebase 설정과 iOS APNs 설정은 별도로 검증합니다.
