# 운영 체크리스트

## 배포 전 공통

- [ ] `git status`에서 배포 대상 외 변경이 없는지 확인
- [ ] `main`과 `origin/main` 커밋 일치 확인
- [ ] 비밀키가 diff·로그·클라이언트 번들에 없는지 확인
- [ ] 운영 Supabase 마이그레이션 적용 상태 확인
- [ ] API 78개 이상 테스트 통과
- [ ] 관리자 웹 `npm run build` 성공
- [ ] Flutter `analyze`, `test`, release APK/AAB 빌드 성공

## Supabase

- [ ] 적용 전 DB 백업 또는 PITR 정책 확인
- [ ] `infra/migrations`를 번호순으로 대조
- [ ] 새 개발 DB에 `0001~0029` 전체 적용 및 0원 카드금액 제약 확인
- [ ] RLS 활성화와 anon/authenticated 직접 쓰기 차단 확인
- [ ] service role 전용 RPC 실행권 확인
- [ ] `process_meal_pay`가 최신 함수인지 확인
- [ ] Storage 버킷·정책과 이미지 업로드 확인
- [ ] Auth Email provider와 Redirect URL 확인

## API / Render

- [ ] `SUPABASE_URL`
- [ ] `SUPABASE_ANON_KEY`
- [ ] `SUPABASE_SERVICE_ROLE_KEY`
- [ ] `KIWOOMPAY_CPID`
- [ ] `KIWOOMPAY_AUTHORIZATION_KEY`
- [ ] `KIWOOMPAY_BASE_URL`
- [ ] `KIWOOMPAY_NOTIFICATION_IPS`
- [ ] `PUBLIC_API_BASE_URL=https://greeneatgo-api.onrender.com/v1`
- [ ] `ADMIN_APP_URL=https://greeneatgo.vercel.app`
- [ ] `CORS_ALLOWED_ORIGINS`에 운영 웹 포함
- [ ] SendGrid 사용 시 `SENDGRID_API_KEY`, 검증된 `INVITE_EMAIL_FROM`
- [ ] FCM 사용 시 Firebase Admin 서비스 계정 환경변수 1개만 설정
- [ ] `/v1/health` HTTP 200

## 관리자 웹 / Vercel

- [ ] `VITE_SUPABASE_URL`
- [ ] `VITE_SUPABASE_ANON_KEY`
- [ ] `VITE_API_BASE_URL=https://greeneatgo-api.onrender.com/v1`
- [ ] `VITE_AUTH_EMAIL_REDIRECT_TO`
- [ ] production deployment `success`
- [ ] 로그인 후 역할별 화면만 노출
- [ ] 모바일 로그인 input이 16px 이상이고 자동 확대 없음

## Android 앱

- [ ] `applicationId=com.greeneat.greeneatgo`
- [ ] versionCode 증가
- [ ] 운영 release keystore 사용 여부 확인
- [ ] API/Supabase 공개 설정이 APK에 주입됐는지 확인
- [ ] Firebase를 쓸 경우 네 클라이언트 값과 `FIREBASE_ENABLED=true`
- [ ] `aapt dump badging`으로 package/version/SDK 확인
- [ ] APK SHA-256과 크기 기록
- [ ] 기존 설치본 위 업데이트 설치 확인

## 결제 E2E

### 회사 장부

- [ ] 활성 직원·활성 계약·허용 시간 정상 결제
- [ ] 중지 사용자·미계약 식당·시간 외·월 한도 초과 차단
- [ ] 동일 요청 재시도 중복 거래 방지
- [ ] 병렬 결제 월 한도 초과 방지

### 일반 식권

- [ ] 상품 조회→키움페이 승인→식권 낱장 발급
- [ ] 금액·주문번호 위변조 차단
- [ ] QR 사용 시 FIFO 1장 차감
- [ ] 식권 부족 시 구매 안내
- [ ] 이벤트 시작 전·종료 후 결제 차단

### 지원 식권·포인트

- [ ] 포인트 0원·일부·전액 결제
- [ ] 포인트 예약→승인→확정
- [ ] 결제 취소 시 포인트 예약 해제
- [ ] QR 사용 시 회사 부담분만 정산 포함
- [ ] 식당 지원금이 회사 청구에서 제외

## 정산

- [ ] 기간 중복 정산 차단
- [ ] 장부와 지원 식권 회사 부담분만 포함
- [ ] 일반 식권 구매·사용은 회사 정산 제외
- [ ] 2,000건 초과 거래 집계 검증
- [ ] 환불·취소 후 재정산 정책 확인
- [ ] 입금 확인 감사 이력 확인
- [ ] XLSX/PDF 합계 일치

## FCM

- [ ] 로그인 후 기기 토큰 등록
- [ ] 전체 사용자 대상과 일반 사용자 대상 분리
- [ ] 전면·백그라운드·종료 상태 수신
- [ ] 로그아웃 후 이전 계정 알림 미수신
- [ ] 무효 토큰이 다른 기기 발송을 중단하지 않음

## 배포 후

- [ ] API health 확인
- [ ] 관리자 웹 HTTP 200
- [ ] 운영 로그인 1회
- [ ] 역할별 핵심 API 1회
- [ ] 최근 오류 로그와 브라우저 콘솔 확인
- [ ] 배포 커밋·APK 버전·검증 결과 기록
