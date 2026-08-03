import os
import subprocess
import sys

import pytest

from app.config import (
    DEFAULT_KIWOOMPAY_NOTIFICATION_IPS,
    _kiwoompay_notification_ips,
)


def test_kiwoom_notification_ips_keep_defaults_when_render_secret_is_missing_or_blank():
    assert _kiwoompay_notification_ips(None) == DEFAULT_KIWOOMPAY_NOTIFICATION_IPS
    assert _kiwoompay_notification_ips("") == DEFAULT_KIWOOMPAY_NOTIFICATION_IPS
    assert _kiwoompay_notification_ips(" ,  ") == DEFAULT_KIWOOMPAY_NOTIFICATION_IPS


def test_kiwoom_notification_ips_merge_custom_entries_without_duplicates():
    custom = "203.0.113.10, 123.140.121.205,203.0.113.10"

    result = _kiwoompay_notification_ips(custom)

    assert result[: len(DEFAULT_KIWOOMPAY_NOTIFICATION_IPS)] == DEFAULT_KIWOOMPAY_NOTIFICATION_IPS
    assert result.count("123.140.121.205") == 1
    assert result.count("203.0.113.10") == 1


@pytest.mark.parametrize("invalid_env", ["prod", "staging", "Production", " production", ""])
def test_settings_from_env_rejects_unknown_or_inexact_environment(monkeypatch, invalid_env):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "test-anon")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-role")
    monkeypatch.setenv("ENV", invalid_env)
    monkeypatch.setenv("SMS_DRY_RUN", "false")
    monkeypatch.setenv("POPBILL_IS_TEST", "true")
    monkeypatch.setenv("POPBILL_IP_RESTRICT_ON", "true")
    monkeypatch.setenv("POPBILL_USE_STATIC_IP", "false")
    monkeypatch.setenv("POPBILL_USE_LOCAL_TIME", "true")

    from app.config import Settings

    with pytest.raises(
        RuntimeError, match="^ENV must be exactly one of: development, test, production$"
    ):
        Settings.from_env()


def test_real_app_boot_preserves_production_dry_run_guard():
    # Pass only process essentials and explicit placeholders; never forward host secrets.
    env = {
        key: os.environ[key]
        for key in ("PATH", "SYSTEMROOT", "LD_LIBRARY_PATH")
        if key in os.environ
    }
    env.update(
        {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_ANON_KEY": "test-anon",
            "SUPABASE_SERVICE_ROLE_KEY": "test-role",
            "ENV": "production",
            "SMS_DRY_RUN": "true",
            "SOLAPI_API_KEY": "test-api-key",
            "SOLAPI_API_SECRET": "test-api-secret",
            "SOLAPI_SENDER": "021234567",
        }
    )

    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode != 0
    assert "SMS_DRY_RUN cannot be enabled in production" in result.stderr
    assert "test-api-secret" not in result.stderr


def test_real_app_boot_rejects_missing_or_default_production_otp_pepper():
    base = {
        key: os.environ[key]
        for key in ("PATH", "SYSTEMROOT", "LD_LIBRARY_PATH")
        if key in os.environ
    }
    base.update({
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_ANON_KEY": "test-anon",
        "SUPABASE_SERVICE_ROLE_KEY": "test-role",
        "ENV": "production",
        "SMS_DRY_RUN": "false",
        "SOLAPI_API_KEY": "test-api-key",
        "SOLAPI_API_SECRET": "test-api-secret",
        "SOLAPI_SENDER": "021234567",
    })
    for pepper in (None, "development-only-phone-otp-pepper"):
        env = dict(base)
        if pepper is not None:
            env["OTP_PEPPER"] = pepper
        result = subprocess.run(
            [sys.executable, "-c", "import app.main"],
            cwd=os.path.dirname(os.path.dirname(__file__)),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode != 0
        assert "OTP_PEPPER must be explicitly set to a non-default value in production" in result.stderr
        assert "test-api-secret" not in result.stderr
