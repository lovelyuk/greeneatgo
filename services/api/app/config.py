from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_KIWOOMPAY_NOTIFICATION_IPS = (
    "123.140.121.205",
    "27.102.213.200",
    "27.102.213.201",
    "27.102.213.202",
    "27.102.213.203",
)
ALLOWED_ENVIRONMENTS = frozenset({"development", "test", "production"})


def _kiwoompay_notification_ips(raw: str | None) -> tuple[str, ...]:
    """Keep the documented provider IPs even when Render injects a blank secret.

    Blueprint ``sync: false`` variables can exist as an empty string. Treating
    that as an explicit empty allowlist rejects every approved payment callback.
    Configured entries are additive so an incomplete override cannot remove the
    provider's documented production addresses.
    """
    configured = (part.strip() for part in (raw or "").split(","))
    return tuple(dict.fromkeys((*DEFAULT_KIWOOMPAY_NOTIFICATION_IPS, *(part for part in configured if part))))


def parse_env_bool(name: str, default: bool) -> bool:
    """Read an environment boolean without accepting surprising truthy values."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    if raw == "true":
        return True
    if raw == "false":
        return False
    raise RuntimeError(f"{name} must be exactly 'true' or 'false'")


def load_dotenv(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    env: str = "development"
    solapi_api_key: str = ""
    solapi_api_secret: str = ""
    solapi_sender: str = ""
    sms_dry_run: bool = True
    otp_pepper: str = "development-only-phone-otp-pepper"
    otp_bcrypt_rounds: int = 12
    supabase_jwt_secret: str | None = None
    kiwoompay_cpid: str = ""
    kiwoompay_authorization_key: str = ""
    kiwoompay_base_url: str = "https://apitest.kiwoompay.co.kr"
    kiwoompay_notification_ips: tuple[str, ...] = DEFAULT_KIWOOMPAY_NOTIFICATION_IPS
    kiwoompay_app_url: str = "greeneatgo://payment"
    public_api_base_url: str = "http://localhost:8000/v1"
    admin_app_url: str = "http://localhost:5173"
    sendgrid_api_key: str = ""
    invite_email_from: str = "GreenEatGo <verified-sender@example.com>"
    pilot_merchant_id: str | None = None
    cors_allowed_origins: tuple[str, ...] = ("http://localhost:5173", "https://greeneatgo.vercel.app")
    popbill_link_id: str = ""
    popbill_secret_key: str = ""
    popbill_corp_num: str = ""
    popbill_user_id: str = ""
    popbill_is_test: bool = True
    popbill_ip_restrict_on: bool = True
    popbill_use_static_ip: bool = False
    popbill_use_local_time: bool = True

    def __post_init__(self) -> None:
        if self.env not in ALLOWED_ENVIRONMENTS:
            raise RuntimeError(
                "ENV must be exactly one of: development, test, production"
            )
        if self.env == "production" and self.sms_dry_run:
            raise RuntimeError("SMS_DRY_RUN cannot be enabled in production")
        if self.env == "production" and not all(
            (self.solapi_api_key, self.solapi_api_secret, self.solapi_sender)
        ):
            raise RuntimeError("SOLAPI credentials and sender are required in production")
        if self.env == "production" and (
            not self.otp_pepper
            or self.otp_pepper == "development-only-phone-otp-pepper"
        ):
            raise RuntimeError("OTP_PEPPER must be explicitly set to a non-default value in production")
        if not 4 <= self.otp_bcrypt_rounds <= 15:
            raise RuntimeError("OTP_BCRYPT_ROUNDS must be between 4 and 15")

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        missing = [
            key for key in (
                "SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY",
            )
            if not os.environ.get(key)
        ]
        if missing:
            raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")
        return cls(
            supabase_url=os.environ["SUPABASE_URL"].rstrip("/"),
            supabase_anon_key=os.environ["SUPABASE_ANON_KEY"],
            supabase_service_role_key=os.environ["SUPABASE_SERVICE_ROLE_KEY"],
            env=os.environ.get("ENV", "development"),
            solapi_api_key=os.environ.get("SOLAPI_API_KEY", "").strip(),
            solapi_api_secret=os.environ.get("SOLAPI_API_SECRET", "").strip(),
            solapi_sender=os.environ.get("SOLAPI_SENDER", "").strip(),
            sms_dry_run=parse_env_bool("SMS_DRY_RUN", True),
            otp_pepper=os.environ.get("OTP_PEPPER", "development-only-phone-otp-pepper").strip(),
            otp_bcrypt_rounds=int(os.environ.get("OTP_BCRYPT_ROUNDS", "12")),
            supabase_jwt_secret=os.environ.get("SUPABASE_JWT_SECRET") or None,
            kiwoompay_cpid=os.environ.get("KIWOOMPAY_CPID", "").strip(),
            kiwoompay_authorization_key=os.environ.get("KIWOOMPAY_AUTHORIZATION_KEY", "").strip(),
            kiwoompay_base_url=os.environ.get("KIWOOMPAY_BASE_URL", "https://apitest.kiwoompay.co.kr").rstrip("/"),
            kiwoompay_notification_ips=_kiwoompay_notification_ips(
                os.environ.get("KIWOOMPAY_NOTIFICATION_IPS")
            ),
            kiwoompay_app_url=os.environ.get("KIWOOMPAY_APP_URL", "greeneatgo://payment").strip(),
            public_api_base_url=os.environ.get("PUBLIC_API_BASE_URL", "http://localhost:8000/v1").rstrip("/"),
            admin_app_url=os.environ.get("ADMIN_APP_URL", "http://localhost:5173").rstrip("/"),
            sendgrid_api_key=os.environ.get("SENDGRID_API_KEY", "").strip(),
            invite_email_from=os.environ.get("INVITE_EMAIL_FROM", "GreenEatGo <verified-sender@example.com>").strip(),
            pilot_merchant_id=(os.environ.get("PILOT_MERCHANT_ID") or "").strip() or None,
            popbill_link_id=os.environ.get("POPBILL_LINK_ID", "").strip(),
            popbill_secret_key=os.environ.get("POPBILL_SECRET_KEY", "").strip(),
            # Keep the raw value: the SDK boundary accepts only the two documented
            # corporation-number forms and must reject surrounding whitespace.
            popbill_corp_num=os.environ.get("POPBILL_CORP_NUM", ""),
            popbill_user_id=os.environ.get("POPBILL_USER_ID", "").strip(),
            popbill_is_test=parse_env_bool("POPBILL_IS_TEST", True),
            popbill_ip_restrict_on=parse_env_bool("POPBILL_IP_RESTRICT_ON", True),
            popbill_use_static_ip=parse_env_bool("POPBILL_USE_STATIC_IP", False),
            popbill_use_local_time=parse_env_bool("POPBILL_USE_LOCAL_TIME", True),
            cors_allowed_origins=tuple(
                origin.strip()
                for origin in os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:5173,https://greeneatgo.vercel.app").split(",")
                if origin.strip()
            ),
        )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings
