# Vercel API 이전 (Render → Vercel)

브랜치: `feat/2026-10-17-vercel-api`. 운영(Render, 앱/웹이 호출하는 주소)은 아직 바꾸지 않았다.

## 구성

| 항목 | 값 |
|---|---|
| Vercel 프로젝트 | `greeneatgo-api` (yonguks-projects), Root Directory `services/api` |
| 주소 | `https://greeneatgo-api.vercel.app/v1` |
| 리전 | `icn1` (서울, `services/api/vercel.json`) |
| 엔트리 | `pyproject.toml` `[tool.vercel] entrypoint = "app.main:app"` |
| 함수 크기 | 58.85MB (Python 한도 500MB) |

## 바뀐 코드

- 정산서/청구서 PDF: WeasyPrint(OS 라이브러리 Pango/Cairo 필요, Vercel에 없음) → 순수 Python `fpdf2`
  (`app/services/pdf_render.py`, 동봉 NanumGothic). 같은 데이터·색상·A4 가로 레이아웃.
- 런타임 의존성 정리: 미사용 `apscheduler`, `supabase` 제거, `psycopg`는 테스트 전용 `dev` extra로 이동.

## 검증한 것 (실측)

- 키움 결과통지 IP 검사: Vercel에서도 `request.client.host`가 실제 발신 IP. 위조한
  `X-Forwarded-For`/`X-Real-IP`/`X-Vercel-Forwarded-For`(허용 IP, 127.0.0.1)는 모두 403
  (`tests/test_vercel_ingress_live.py`, `VERCEL_API` 지정 시 실행). 코드 변경 불필요.
- 공개 읽기 API 응답 비교 (Render 무료 vs Vercel icn1): Render 첫 요청 41.6초(콜드스타트), 이후 0.6~2.1초 /
  Vercel 0.19~0.9초. 응답 본문 동일.
- PDF: Vercel 함수에서 실제 생성, 한글 정상.
- API 테스트 915 passed.

## 전환 전 남은 일

1. ~~Vercel 환경변수 등록~~ 완료: Render 환경변수 27개를 Production/Preview에 복사, `PUBLIC_API_BASE_URL`만
   `https://greeneatgo-api.vercel.app/v1`로 변경. Render에 없는 `SUPABASE_JWT_SECRET`은 제거(코드 미사용).
   `ENV`는 Render와 같은 기본값(`development`). 값 원본 `services/api/.env.render`는 git 제외 대상.
2. 키움 테스트 결제 E2E: 결제창 → 결과통지(키움 → Vercel) → 식권 발급. 키움 가맹점 설정의 결과통지 URL 변경 필요.
3. 팝빌 테스트 발행: Vercel은 요청마다 나가는 IP가 바뀔 수 있음. 실패하면 `POPBILL_IP_RESTRICT_ON=false`.
4. 전환: 관리자 웹 `VITE_API_BASE_URL`, 앱 `--dart-define` API 주소, Supabase Auth Redirect URL, 키움 결과통지 URL.
5. 안정 확인 후 Render 서비스 종료.
