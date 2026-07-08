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
    :root { color: #24180f; background: #fff3d9; font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 24px; background: radial-gradient(circle at 10% 10%, rgba(255,183,49,.38), transparent 32%), linear-gradient(135deg, #fff3d9, #fffaf0 48%, #ffe3ae); }
    .card { width: min(100%, 520px); background: #fffaf0; border: 1.5px solid #ffdfa8; border-radius: 30px; padding: 30px; text-align: center; box-shadow: 0 24px 60px rgba(129,75,23,.13); }
    .box { width: 90px; height: 74px; margin: 0 auto 18px; border-radius: 22px; border: 5px solid #4a2a14; background: #ffa629; position: relative; box-shadow: inset 0 14px rgba(255,255,255,.32); }
    .box:before, .box:after { content: ''; position: absolute; top: 36px; width: 8px; height: 8px; border-radius: 50%; background: #4a2a14; }
    .box:before { left: 25px; } .box:after { right: 25px; }
    .mouth { position: absolute; left: 36px; bottom: 15px; width: 18px; height: 6px; border-radius: 999px; background: #4a2a14; }
    .pill { display: inline-block; padding: 7px 12px; border-radius: 999px; background: #ffecd0; color: #ff7a1a; font-size: 12px; font-weight: 900; letter-spacing: .08em; }
    h1 { margin: 14px 0 10px; font-size: 30px; line-height: 1.16; letter-spacing: -1px; }
    p { margin: 0; color: #805a39; font-size: 16px; line-height: 1.65; font-weight: 750; }
    .button { display: block; margin-top: 22px; padding: 15px 18px; border-radius: 18px; background: linear-gradient(135deg, #ff7a1a, #ffa629); color: white; font-weight: 900; text-decoration: none; }
    .hint { margin-top: 16px; font-size: 13px; color: #9a7656; }
  </style>
</head>
<body>
  <main class="card">
    <div class="box"><span class="mouth"></span></div>
    <span class="pill">EMAIL VERIFIED</span>
    <h1>이메일 인증 완료!</h1>
    <p>이제 앱으로 돌아가 로그인해 주세요.</p>
    <a class="button" href="javascript:window.close()">앱으로 돌아가기</a>
    <p class="hint">창이 닫히지 않으면 브라우저를 닫고 앱으로 돌아가면 됩니다.</p>
  </main>
</body>
</html>
"""
