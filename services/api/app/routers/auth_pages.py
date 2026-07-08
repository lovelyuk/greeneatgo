from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["auth"])


@router.get("/auth/confirmed", response_class=HTMLResponse)
def auth_confirmed() -> str:
    return """
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>그린잇 이메일 인증 완료</title>
  <style>
    :root { color: #14351F; background: #F3FBF4; font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 24px; background: radial-gradient(circle at 10% 10%, rgba(123,216,143,.42), transparent 32%), linear-gradient(135deg, #EAF7EC, #F3FBF4 48%, #D9F0DE); }
    .card { width: min(100%, 520px); background: #FCFEFC; border: 1.5px solid #CDEBD5; border-radius: 30px; padding: 30px; text-align: center; box-shadow: 0 24px 60px rgba(30,86,49,.13); }
    .sprout { width: 96px; height: 96px; margin: 0 auto 14px; display: grid; place-items: center; color: #2FB865; }
    .sprout svg { width: 100%; height: 100%; }
    .pill { display: inline-block; padding: 7px 12px; border-radius: 999px; background: #DDF3E2; color: #2FB865; font-size: 12px; font-weight: 900; letter-spacing: .08em; }
    h1 { margin: 14px 0 10px; font-size: 30px; line-height: 1.16; letter-spacing: -1px; }
    p { margin: 0; color: #5C7A66; font-size: 16px; line-height: 1.65; font-weight: 750; }
    .button { display: block; margin-top: 22px; padding: 15px 18px; border-radius: 18px; background: linear-gradient(135deg, #2FB865, #7BD88F); color: white; font-weight: 900; text-decoration: none; }
    .hint { margin-top: 16px; font-size: 13px; color: #5C7A66; }
  </style>
</head>
<body>
  <main class="card">
    <div class="sprout">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M7 20h10"/>
        <path d="M10 20c5.5-2.5.8-6.4 3-10"/>
        <path d="M9.5 9.4c1.1.8 1.8 2.2 2.3 3.7-2 .4-3.5.4-4.8-.3-1.2-.6-2.3-1.9-3-4.2 2.8-.5 4.4 0 5.5.8z"/>
        <path d="M14.1 6a7 7 0 0 0-1.1 4c1.9-.1 3.3-.6 4.3-1.4 1-1 1.6-2.3 1.7-4.6-2.7.1-4 1-4.9 2z"/>
      </svg>
    </div>
    <span class="pill">EMAIL VERIFIED</span>
    <h1>이메일 인증 완료!</h1>
    <p>이제 앱으로 돌아가 로그인해 주세요.</p>
    <a class="button" href="javascript:window.close()">앱으로 돌아가기</a>
    <p class="hint">창이 닫히지 않으면 브라우저를 닫고 앱으로 돌아가면 됩니다.</p>
  </main>
</body>
</html>
"""
