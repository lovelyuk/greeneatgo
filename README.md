# greeneatGo

greeneatGo는 회사 식대 장부, 개인 식권, 지원 식권과 포인트를 하나의 매장 QR로 처리하는 서비스입니다.

## 운영 주소

| 서비스 | 주소 |
|---|---|
| 관리자 웹 | https://greeneatgo.vercel.app |
| API | https://greeneatgo-api.onrender.com/v1 |
| API 상태 확인 | https://greeneatgo-api.onrender.com/v1/health |

## 구성

```text
apps/customer      Flutter 사용자 앱
apps/admin         React/Vite 관리자 웹
services/api       FastAPI API
infra/migrations   Supabase/PostgreSQL 마이그레이션
docs               운영·구조·사용자 문서
```

## 사용자와 역할

- `employee`: 회사 월 한도 장부 결제, 지원 식권과 포인트 사용
- `customer`: Toss로 개인 식권을 구매하고 매장 QR에서 1장씩 사용
- `company_admin`: 직원·가입 승인·한도·포인트·식사시간 관리
- `merchant_admin`: 매장·상품·식권·업체 계약·거래·정산·공지·리뷰 관리
- `platform_admin`: 식당 온보딩과 식당관리자 초대

자세한 구조는 [현재 아키텍처](docs/ARCHITECTURE.md), 역할별 사용법은 [사용자 설명서](docs/user-guides/README.md)를 참고합니다.

## 제품 원칙

- 회사 직원 식대는 선불 충전이 아니라 월 한도 기반 장부입니다.
- 회사는 식당에 직접 정산하고 greeneatGo는 거래·정산 데이터를 제공합니다.
- 일반 사용자는 식당이 등록한 식권 패키지를 Toss Payments로 구매합니다.
- 지원 식권은 회사·식당 보조금과 직원 부담액을 구매 시점에 스냅샷으로 저장합니다.
- 회사관리자가 충전하는 포인트는 복지 포인트이며 변경 내역을 감사 원장에 남깁니다.
- 결제·발급·사용 등 신뢰 쓰기는 FastAPI의 서버 권한을 통해 수행합니다.
- SMS 인증·선불 식대 지급 기능은 사용하지 않습니다.

## 로컬 실행

### API

Python 3.12 환경에서 실행합니다.

```bash
cd services/api
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
cp .env.example .env
bash start.sh
```

실제 비밀값은 `.env`에만 넣고 Git에 커밋하지 않습니다.

### 관리자 웹

```bash
cd apps/admin
npm install
cp .env.example .env
npm run dev
```

로컬 주소는 기본적으로 `http://localhost:5173`입니다.

### Flutter 사용자 앱

Windows 개발 환경의 표준 APK 빌드:

```powershell
powershell -ExecutionPolicy Bypass -File D:\projects\greeneatGo\apps\customer\build_apk_from_admin_env.ps1
```

스크립트는 `apps/admin/.env`의 공개 Supabase/API 설정을 `--dart-define`으로 주입합니다. 자세한 내용은 [사용자 앱 README](apps/customer/README.md)를 참고합니다.

## 검증 명령

```bash
# API
cd services/api
.venv/bin/python -m unittest discover -s tests -v

# 관리자 웹
cd apps/admin
npm run build
```

```powershell
# Flutter
Set-Location D:\projects\greeneatGo\apps\customer
D:\dev\flutter\bin\flutter.bat analyze
D:\dev\flutter\bin\flutter.bat test
```

현재 검증 상태와 출시 전 남은 항목은 [CURRENT_STATUS.md](docs/CURRENT_STATUS.md)에 기록합니다.

## 배포와 데이터베이스

- [배포 가이드](DEPLOYMENT.md)
- [Supabase 설정·마이그레이션](SETUP_SUPABASE_WEB.md)
- [Firebase 푸시 설정](docs/FIREBASE_PUSH_SETUP.md)
- [운영 체크리스트](docs/OPERATIONS_CHECKLIST.md)

## 보안 규칙

- `SUPABASE_SERVICE_ROLE_KEY`, Toss 비밀키, Firebase Admin 서비스 계정, SendGrid 키는 서버에만 둡니다.
- `VITE_` 환경변수와 Flutter `--dart-define`에는 공개 가능한 클라이언트 값만 넣습니다.
- 운영 데이터를 삭제하기 전에 주문 → 발급 → 사용 → 정산 흐름을 먼저 추적합니다.
- DB 마이그레이션은 파일 존재만으로 배포 완료로 간주하지 않고 실제 운영 스키마를 확인합니다.

## 문서 기준

현재 코드와 마이그레이션이 구현의 최종 기준입니다. 확정된 제품 결정은 [DECISIONS.md](DECISIONS.md)에, 문서 전체 목록은 [MASTER_INDEX.md](MASTER_INDEX.md)에 기록합니다.
