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
