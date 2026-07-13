from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


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
    supabase_jwt_secret: str | None = None
    toss_client_key: str = ""
    toss_secret_key: str = ""
    public_api_base_url: str = "http://localhost:8000/v1"
    admin_app_url: str = "http://localhost:5173"
    resend_api_key: str = ""
    invite_email_from: str = "GreenEatGo <onboarding@resend.dev>"
    pilot_merchant_id: str | None = None
    cors_allowed_origins: tuple[str, ...] = ("http://localhost:5173", "https://greeneatgo.vercel.app")

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        missing = [
            key for key in (
                "SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY",
                "TOSS_CLIENT_KEY", "TOSS_SECRET_KEY",
            )
            if not os.environ.get(key)
        ]
        if missing:
            raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")
        return cls(
            supabase_url=os.environ["SUPABASE_URL"].rstrip("/"),
            supabase_anon_key=os.environ["SUPABASE_ANON_KEY"],
            supabase_service_role_key=os.environ["SUPABASE_SERVICE_ROLE_KEY"],
            supabase_jwt_secret=os.environ.get("SUPABASE_JWT_SECRET") or None,
            toss_client_key=os.environ["TOSS_CLIENT_KEY"],
            toss_secret_key=os.environ["TOSS_SECRET_KEY"],
            public_api_base_url=os.environ.get("PUBLIC_API_BASE_URL", "http://localhost:8000/v1").rstrip("/"),
            admin_app_url=os.environ.get("ADMIN_APP_URL", "http://localhost:5173").rstrip("/"),
            resend_api_key=os.environ.get("RESEND_API_KEY", "").strip(),
            invite_email_from=os.environ.get("INVITE_EMAIL_FROM", "GreenEatGo <onboarding@resend.dev>").strip(),
            pilot_merchant_id=(os.environ.get("PILOT_MERCHANT_ID") or "").strip() or None,
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
