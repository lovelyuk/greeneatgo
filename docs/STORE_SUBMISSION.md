# 스토어 제출 체크리스트 (고객 앱 apps/customer)

2026-11-12 보안·검수 점검(R-1~R-13) 반영 상태와 사람이 해야 하는 일.

## 코드에 반영됨
| 항목 | 내용 |
|---|---|
| 회원 탈퇴 (App Store 5.1.1(v), Play 계정 삭제 정책) | 앱: 계정 설정 → 맨 아래 「회원 탈퇴」. API `DELETE /v1/me`: 이름·전화·부서·사번·기기토큰 삭제, 로그인 계정(Firebase/Supabase) 삭제, 결제·이용 기록은 익명 프로필로 보관. 같은 번호 재가입 가능(0076). 웹 안내: `https://greeneatgo.vercel.app/account-deletion.html` |
| iOS 결제 앱 복귀 | Info.plist `CFBundleURLTypes` = `greeneatgo` |
| iOS 푸시 | `Runner.entitlements`(aps-environment) + `UIBackgroundModes: remote-notification` |
| iOS 개인정보 매니페스트 | `Runner/PrivacyInfo.xcprivacy` (추적 없음, 이름·전화·구매내역·사용자ID·기기ID·사진·리뷰, UserDefaults CA92.1) |
| 수출 규정 | `ITSAppUsesNonExemptEncryption = false` |
| iPad | iPhone 전용(`TARGETED_DEVICE_FAMILY = 1`), 세로 고정 |
| Android 서명 | `android/key.properties`가 있으면 업로드 키로 release 서명. `build_apk_from_admin_env.ps1 -Bundle` → AAB |
| Android 백업 | `android:allowBackup="false"` |
| 심사용 로그인 | API 환경변수 `REVIEW_LOGIN_PHONE`(예 01000000000) + `REVIEW_LOGIN_CODE`(6자리): 그 번호만 문자 없이 고정 인증번호. 발송·시도 횟수 제한은 그대로 |

## 사람이 해야 하는 일
1. **Android 업로드 키**: `keytool -genkey -v -keystore G:\keys\greeneatgo-upload.jks -keyalg RSA -keysize 2048 -validity 10000 -alias upload` → `android/key.properties.example`을 `key.properties`로 복사해 채움. 키와 비밀번호는 git 밖에 백업(분실 시 앱 업데이트 불가, Play App Signing 사용 권장).
2. **iOS (Mac/Xcode)**: Signing & Capabilities에서 Push Notifications 확인, Firebase 콘솔에 APNs 인증 키(.p8) 업로드, iOS용 Firebase 앱 ID로 `--dart-define` 빌드.
3. **심사 계정**: Vercel API에 `REVIEW_LOGIN_PHONE`/`REVIEW_LOGIN_CODE` 설정 → 그 번호로 한 번 가입해 두고, App Store Connect「App Review Information」과 Play Console「앱 액세스」에 번호·인증번호·이용 방법 기재.
4. **앱 이름 통일**: 현재 iOS `Greeneatgo Customer`, Android `Green eat`. 스토어 등록명으로 맞출 것.
5. **Play Data safety / App Privacy**: 이름, 전화번호, 구매 내역, 사용자 ID, 기기 ID(FCM), 사진(리뷰), 리뷰 내용. 카드정보는 PG(키움)가 처리. 전송 암호화 예. 삭제 요청: 앱 내 경로 + 위 웹 URL.
6. **심사 노트**: 오프라인 매장 식사 이용권(실물 서비스)이라 인앱결제 대상이 아님.
7. **실기기 확인**: 카드사·간편결제 앱 왕복(KB, 신한, 카카오페이 등) iOS/Android 각각.
