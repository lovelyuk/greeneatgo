import re
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from starlette.requests import Request

from app.config import DEFAULT_CORS_ORIGIN_REGEX
from app.routers import payments
from app.routers.banners import RewardPayload


def _settings(env="production", base="https://api.kiwoompay.co.kr"):
    return SimpleNamespace(env=env, kiwoompay_base_url=base,
                           kiwoompay_notification_ips=("123.140.121.205", "27.102.213.200"))


def test_production_rejects_loopback_and_dev_notifier_on_live_gateway():
    s = _settings()
    assert payments._notification_source_allowed(s, "27.102.213.200")
    assert not payments._notification_source_allowed(s, "127.0.0.1")
    assert not payments._notification_source_allowed(s, "testclient")
    assert not payments._notification_source_allowed(s, "123.140.121.205")


def test_test_gateway_keeps_dev_notifier_and_local_peers_outside_production():
    assert payments._notification_source_allowed(_settings(base="https://apitest.kiwoompay.co.kr"), "123.140.121.205")
    assert payments._notification_source_allowed(_settings(env="development"), "127.0.0.1")


def test_production_never_trusts_forwarded_header_from_loopback_peer():
    request = Request({"type": "http", "client": ("127.0.0.1", 1), "headers": [(b"x-forwarded-for", b"27.102.213.200")]})
    with patch.object(payments, "get_settings", return_value=_settings()):
        assert payments._notification_ip(request) == "127.0.0.1"
    with patch.object(payments, "get_settings", return_value=_settings(env="development")):
        assert payments._notification_ip(request) == "27.102.213.200"


@pytest.mark.parametrize("origin,ok", [
    ("https://greeneatgo-5b676grp1-yonguks-projects.vercel.app", True),
    ("https://greeneatgo-git-feat-2026-11-12-joa-yonguks-projects.vercel.app", True),
    ("https://evil.vercel.app", False),
    ("https://greeneatgo-x-yonguks-projects.vercel.app.evil.com", False),
    ("https://greeneatgo-x-otherteam.vercel.app", False),
])
def test_cors_regex_only_matches_this_project(origin, ok):
    assert bool(re.fullmatch(DEFAULT_CORS_ORIGIN_REGEX, origin)) is ok


def test_banner_point_rewards_are_capped():
    RewardPayload(reward_type="point", point_amount=1000, total_budget=1_000_000)
    for bad in (dict(point_amount=10_001, total_budget=1000), dict(point_amount=100),
                dict(point_amount=100, total_budget=10_000_001),
                dict(point_amount=100, total_budget=1000, grant_policy="unlimited"),
                dict(point_amount=100, total_budget=1000, grant_policy="unlimited", per_user_limit=101)):
        with pytest.raises(ValidationError):
            RewardPayload(reward_type="point", **bad)
    RewardPayload(reward_type="point", point_amount=100, total_budget=1000, grant_policy="unlimited", per_user_limit=100)
