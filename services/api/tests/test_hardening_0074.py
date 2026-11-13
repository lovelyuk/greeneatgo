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
    ("https://greeneatgo.vercel.app", True),
    ("https://evil.vercel.app", False),
    ("https://greeneatgox.vercel.app", False),
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


def test_new_invite_codes_have_50_bits_and_typing_is_normalized():
    from app.schemas import JoinRequest
    from app.services.invite_codes import ALPHABET, new_company_invite_code
    code = new_company_invite_code()
    assert re.fullmatch(r"GE-[A-Z2-9]{5}-[A-Z2-9]{5}", code) and not set(code[3:].replace("-", "")) - set(ALPHABET)
    assert len({new_company_invite_code() for _ in range(200)}) == 200
    assert JoinRequest(invite_code=" ge-abcde-fghjk ", display_name="x").invite_code == "GE-ABCDE-FGHJK"


def test_restaurant_push_audience_is_its_own_customers_and_employees():
    from app.routers import push_notifications as pn
    users = [{"id": "e1", "role": "employee", "company_id": "c1"}, {"id": "e2", "role": "employee", "company_id": "c2"},
             {"id": "k1", "role": "customer", "company_id": None}, {"id": "k2", "role": "customer", "company_id": None}]
    tables = {"app_users": users, "merchant_companies": [{"company_id": "c1"}], "payment_orders": [{"user_id": "k1"}],
              "device_tokens": []}

    class Client:
        def rest_get(self, table, params):
            if table == "device_tokens":
                ids = params["account_id"][4:-1].split(",")
                return [{"account_id": i, "fcm_token": "t-" + i} for i in ids]
            return tables[table] if params.get("offset") == "0" else []

    repo = SimpleNamespace(client=Client())
    with patch.object(pn, "get_settings", return_value=SimpleNamespace(pilot_merchant_id="pilot")):
        other = pn._audience(repo, "all", "m-other")
        pilot = pn._audience(repo, "all", "pilot")
    assert {t.account_id for t in other["targets"]} == {"e1", "k1"}
    assert {t.account_id for t in pilot["targets"]} == {"e1", "e2", "k1", "k2"}
