from __future__ import annotations

import json
from dataclasses import dataclass
from email.utils import parseaddr
from html import escape
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import get_settings


@dataclass(frozen=True)
class EmailDelivery:
    status: str
    message_id: str | None = None
    error: str | None = None


def invitation_url(token: str) -> str:
    settings = get_settings()
    return f"{settings.admin_app_url}/?invite={token}"


def send_company_invitation(
    *,
    email: str,
    company_name: str,
    token: str,
    sender_name: str | None = None,
    reply_to: str | None = None,
) -> EmailDelivery:
    """Send through SendGrid's v3 Mail Send API without exposing the server key."""
    settings = get_settings()
    if not settings.sendgrid_api_key:
        return EmailDelivery("failed", error="SENDGRID_API_KEY is not configured")

    from_address = parseaddr(settings.invite_email_from)[1].strip().lower()
    if not from_address or "@" not in from_address:
        return EmailDelivery("failed", error="INVITE_EMAIL_FROM is not a valid email address")

    link = invitation_url(token)
    safe_company_name = escape(company_name)
    safe_link = escape(link, quote=True)
    clean_sender_name = (sender_name or "그린잇").replace("\r", " ").replace("\n", " ").strip()
    html = (
        f"<h2>{safe_company_name} 회사관리자 초대</h2>"
        "<p>아래 버튼을 눌러 초대를 수락하고 관리자 계정을 만들어 주세요.</p>"
        f'<p><a href="{safe_link}">초대 수락하기</a></p>'
        "<p>이 링크는 7일 동안 유효합니다.</p>"
    )
    message: dict = {
        "personalizations": [{"to": [{"email": email.strip().lower()}]}],
        "from": {"email": from_address, "name": clean_sender_name},
        "subject": f"[그린잇] {company_name} 회사관리자 초대",
        "content": [{"type": "text/html", "value": html}],
    }
    if reply_to:
        message["reply_to"] = {"email": reply_to.strip().lower()}

    request = Request(
        "https://api.sendgrid.com/v3/mail/send",
        data=json.dumps(message).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {settings.sendgrid_api_key}",
            "Content-Type": "application/json",
            "User-Agent": "greeneatgo-api/1.0",
        },
    )
    try:
        with urlopen(request, timeout=10) as response:
            message_id = response.headers.get("X-Message-Id")
        return EmailDelivery("sent", message_id=message_id)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return EmailDelivery("failed", error=f"SendGrid HTTP {exc.code}: {body[:500]}")
    except (URLError, TimeoutError, ValueError) as exc:
        return EmailDelivery("failed", error=f"SendGrid request failed: {str(exc)[:500]}")
