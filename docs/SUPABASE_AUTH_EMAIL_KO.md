# Supabase Auth 이메일 인증 설정

## 1. localhost로 열리는 문제 해결

직원 앱 회원가입 메일의 `Confirm email address` 버튼이 `localhost`로 이동하면 Supabase Auth의 기본 Site URL 또는 Redirect URL이 개발용으로 남아 있는 상태다.

Supabase Dashboard에서 아래 값을 설정한다.

```text
Authentication → URL Configuration
```

### Site URL

운영 중인 공개 URL로 설정한다. 현재는 Render API에 인증 완료 안내 페이지를 추가했다.

```text
https://greeneatgo-api.onrender.com
```

### Redirect URLs / Additional Redirect URLs

아래 주소를 추가한다.

```text
https://greeneatgo-api.onrender.com/v1/auth/confirmed
```

직원 앱은 회원가입 요청 시 `emailRedirectTo`로 이 주소를 넘긴다.

```text
https://greeneatgo-api.onrender.com/v1/auth/confirmed
```

인증 완료 후 브라우저에는 “이메일 인증이 완료됐어요. 이제 그린잇 앱으로 돌아가 로그인…” 안내 페이지가 표시된다.

> 인증 완료 안내 페이지 도메인이 바뀌면 `apps/admin/.env`의 `VITE_AUTH_EMAIL_REDIRECT_TO`와 Supabase Redirect URL을 같이 바꾼다.

---

## 2. Confirm email 메일 한글 템플릿

Supabase Dashboard:

```text
Authentication → Email Templates → Confirm signup
```

### Subject

```text
[그린잇] 이메일 인증을 완료해 주세요
```

### Body HTML

```html
<div style="margin:0;padding:0;background:#fff3d9;font-family:Apple SD Gothic Neo,Malgun Gothic,Arial,sans-serif;color:#24180f;">
  <div style="max-width:560px;margin:0 auto;padding:32px 18px;">
    <div style="background:#fffaf0;border:1px solid #ffdfa8;border-radius:28px;padding:28px;box-shadow:0 18px 45px rgba(129,75,23,.10);">
      <div style="font-size:14px;font-weight:900;color:#ff7a1a;letter-spacing:.08em;margin-bottom:14px;">GREENEAT</div>
      <h1 style="margin:0 0 12px;font-size:30px;line-height:1.2;color:#24180f;">이메일 인증을 완료해 주세요</h1>
      <p style="margin:0 0 22px;font-size:16px;line-height:1.65;color:#805a39;font-weight:700;">
        그린잇 회원가입을 진행하려면 아래 버튼을 눌러 이메일 주소를 인증해 주세요.
      </p>
      <a href="{{ .ConfirmationURL }}" style="display:block;text-align:center;text-decoration:none;background:linear-gradient(135deg,#ff7a1a,#ffa629);color:#ffffff;border-radius:18px;padding:16px 18px;font-size:17px;font-weight:900;">
        이메일 인증 완료하기
      </a>
      <p style="margin:22px 0 0;font-size:14px;line-height:1.6;color:#8b6544;">
        버튼이 열리지 않으면 아래 링크를 복사해서 브라우저 주소창에 붙여넣어 주세요.<br>
        <span style="word-break:break-all;color:#4a2a14;">{{ .ConfirmationURL }}</span>
      </p>
    </div>
    <p style="text-align:center;margin:18px 0 0;font-size:12px;color:#9a7656;">
      본인이 요청하지 않았다면 이 메일은 무시해도 됩니다.
    </p>
  </div>
</div>
```

---

## 3. 테스트 순서

1. 앱을 새 APK로 재설치한다.
2. 새 이메일로 회원가입한다.
3. 메일의 “이메일 인증 완료하기”를 누른다.
4. 브라우저가 `localhost`가 아니라 관리자 웹으로 열린다.
5. 인증 완료 안내를 확인하고 앱으로 돌아가 로그인한다.
