# 그린잇 관리자 — Windows 설치 프로그램

`https://greeneatgo.vercel.app/` (식당·회사·플랫폼 관리자 웹)을 여는 Electron 데스크톱 앱.
화면·로그인·데이터는 모두 라이브 웹에서 불러오므로 **웹을 배포하면 앱은 다시 설치하지 않아도 최신 화면**이다.
설치 파일을 새로 만들어야 하는 경우는 이 폴더(창 동작, 아이콘, 메뉴)를 바꿨을 때뿐이다.

## 동작
- 메인 창은 `https://greeneatgo.vercel.app` 만 연다. 다른 사이트 링크는 기본 브라우저로 연다.
- 관리자 웹이 여는 영수증·PDF 미리보기(about:blank → blob:)는 앱 안의 새 창으로 연다. `file:`/`javascript:` 등은 막는다.
- 결제 알림음이 클릭 없이 재생되도록 autoplay 허용. 한 번만 실행(두 번째 실행은 기존 창을 앞으로).
- 인터넷이 끊기면 "관리자 화면에 연결하지 못했어요 / 다시 시도" 화면.
- 메뉴(Alt): 새로고침(F5), 확대/축소, 전체 화면(F11), 웹 브라우저로 열기, 버전 정보.
- 보안: contextIsolation + sandbox, nodeIntegration 끔, 카메라/마이크/위치 권한 거부.

## 빌드 (Windows)
Windows 에서 ASCII 경로에 복사한 뒤(한글 사용자 폴더는 electron-builder가 깨질 수 있음):
```
npm ci        # 처음엔 npm install
npm test
npm run dist  # → dist/GreeneatGo-Admin-Setup-<version>.exe
```
`build/icon.ico` 는 앱 아이콘(iOS 1024 아이콘에서 생성). 버전은 `package.json` 의 `version`.

## 알려진 점
- 코드 서명 인증서가 없어 첫 실행 때 Windows SmartScreen "Windows의 PC 보호" 경고가 뜬다 → "추가 정보 → 실행". 없애려면 코드 서명 인증서(OV/EV)가 필요.
- 자동 업데이트 없음(필요 없음: 화면은 웹에서 온다). 셸을 바꾼 새 설치 파일은 덮어 설치하면 된다.
