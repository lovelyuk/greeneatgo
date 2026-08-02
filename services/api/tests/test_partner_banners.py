from __future__ import annotations

import asyncio
import threading
from datetime import date
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi import HTTPException, Response
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.routers.banners import (BannerPayload, ImpressionPayload, RewardPayload,
                                 ReorderPayload, admin_banners, banner_stats, banners,
                                 click_banner, create_banner, impressions, reorder_banners)
from app.services.banner_images import BannerImageError, convert_banner_image


def image_bytes(size=(900, 300), fmt="PNG"):
    output = BytesIO(); Image.new("RGB", size, "#36a269").save(output, fmt)
    return output.getvalue()


def test_banner_image_converts_valid_home_bottom_to_webp():
    result = convert_banner_image(image_bytes(), "image/png", "home_bottom")
    assert result[:4] == b"RIFF"
    with Image.open(BytesIO(result)) as image:
        assert image.format == "WEBP" and image.size == (900, 300)


@pytest.mark.parametrize("data,mime,placement", [
    (b"not image", "image/png", "home_bottom"),
    (image_bytes(), "image/gif", "home_bottom"),
    (image_bytes((900, 400)), "image/png", "home_bottom"),
    (image_bytes((900, 300)), "image/png", "event_page"),
])
def test_banner_image_rejects_invalid_content_type_or_ratio(data, mime, placement):
    with pytest.raises(BannerImageError):
        convert_banner_image(data, mime, placement)


def test_banner_image_rejects_oversized_dimensions_before_decode():
    with pytest.raises(BannerImageError, match="IMAGE_DIMENSIONS_INVALID"):
        convert_banner_image(image_bytes((6001, 2000)), "image/png", "home_bottom")


def test_impression_contract_is_exact_and_bounded():
    item = {"banner_id": "33333333-3333-3333-3333-333333333333", "placement": "home_bottom"}
    assert ImpressionPayload.model_validate({"items": [item]}).items[0].placement == "home_bottom"
    with pytest.raises(ValueError):
        ImpressionPayload.model_validate({"items": [{**item, "id": item["banner_id"]}]})
    with pytest.raises(ValueError):
        ImpressionPayload.model_validate({"items": [item] * 51})


def test_canonical_payload_names_and_values():
    payload = BannerPayload.model_validate({
        "partner_id": "33333333-3333-3333-3333-333333333333", "title": "banner",
        "image_url": "https://cdn.example/banner.webp", "image_alt": "partner promotion",
        "link_url": "https://partner.example", "open_mode": "external", "placement": "event_page",
        "sort_order": 7, "reward": {"reward_type": "point", "point_amount": 100,
        "grant_policy": "daily", "total_budget": 1000},
    })
    assert payload.placement == "event_page" and payload.reward.grant_policy == "daily"
    with pytest.raises(ValueError):
        BannerPayload.model_validate({**payload.model_dump(), "placement": "home"})


@patch("app.routers.banners.JoinRepository")
def test_admin_banner_create_is_one_transactional_rpc_and_tenant_scoped(repo_class):
    repo = repo_class.return_value
    actor = SimpleNamespace(id="11111111-1111-1111-1111-111111111111")
    with patch("app.routers.banners._merchant_admin", return_value=(actor, "22222222-2222-2222-2222-222222222222")):
        repo.client.rpc.return_value = {"banner": {"id": "b"}, "reward": {"id": "r"}}
        payload = BannerPayload.model_validate({
            "partner_id": "33333333-3333-3333-3333-333333333333", "title": "banner",
            "image_url": "https://cdn.example/banner.webp", "link_url": "https://partner.example",
            "reward": RewardPayload(reward_type="point", point_amount=100),
        })
        result = create_banner(payload, "token")
    assert result["data"]["reward"]["id"] == "r"
    args = repo.client.rpc.call_args.args
    assert args[0] == "save_partner_banner" and args[1]["p_merchant_id"].startswith("2222")
    assert args[1]["p_values"]["placement"] == "home_bottom"
    assert args[1]["p_reward"]["grant_policy"] == "once"
    repo.client.rest_post.assert_not_called()


@patch("app.routers.banners.JoinRepository")
def test_anonymous_click_is_flat_and_logging_failure_is_ignored(repo_class):
    repo = repo_class.return_value
    repo.client.rest_get.side_effect = [[{"id": str(UUID(int=4)), "merchant_id": "m", "partner_id": "p", "link_url": "https://partner.example/landing", "is_active": True, "starts_at": None, "ends_at": None}], [{"id": "p"}]]
    repo.client.rest_post.side_effect = RuntimeError("logging outage")
    data = click_banner(UUID(int=4), None)["data"]
    assert data == {"link_url": "https://partner.example/landing", "reward_granted": False,
                    "reward_type": None, "amount": None, "balance_after": None,
                    "user_coupon_id": None, "reason": "anonymous"}


@patch("app.routers.banners.JoinRepository")
def test_unavailable_direct_click_is_410(repo_class):
    repo_class.return_value.client.rest_get.return_value = [{"is_active": False}]
    with pytest.raises(HTTPException) as exc:
        click_banner(UUID(int=5), None)
    assert exc.value.status_code == 410 and exc.value.detail["code"] == "BANNER_NOT_AVAILABLE"


@patch("app.routers.banners.JoinRepository")
def test_paused_partner_direct_click_is_410(repo_class):
    repo = repo_class.return_value
    repo.client.rest_get.side_effect = [[{"id": str(UUID(int=6)), "merchant_id": "m", "partner_id": "p", "link_url": "https://partner.example", "is_active": True, "starts_at": None, "ends_at": None}], []]
    with pytest.raises(HTTPException) as exc:
        click_banner(UUID(int=6), None)
    assert exc.value.status_code == 410


@patch("app.routers.banners.JoinRepository")
def test_impressions_validate_live_partner_and_placement_then_return_204(repo_class):
    repo = repo_class.return_value
    banner_id = UUID(int=7)
    repo.client.rest_get.side_effect = [[{"id": str(banner_id), "merchant_id": "m", "partner_id": "p", "placement": "home_bottom", "is_active": True, "starts_at": None, "ends_at": None}], [{"id": "p"}]]
    payload = ImpressionPayload.model_validate({"items": [{"banner_id": str(banner_id), "placement": "home_bottom"}]})
    response = impressions(payload, None)
    assert response.status_code == 204 and response.body == b""
    event = repo.client.rest_post.call_args.args[1][0]
    assert event["banner_id"] == str(banner_id) and event["event_type"] == "impression"


@patch("app.routers.banners.JoinRepository")
def test_reorder_is_exactly_one_tenant_authorized_rpc(repo_class):
    repo = repo_class.return_value
    actor = SimpleNamespace(id="11111111-1111-1111-1111-111111111111")
    repo.client.rpc.return_value = {"items": [{"id": str(UUID(int=8)), "sort_order": 3}]}
    with patch("app.routers.banners._merchant_admin", return_value=(actor, "22222222-2222-2222-2222-222222222222")):
        payload = ReorderPayload.model_validate({"items": [{"id": str(UUID(int=8)), "sort_order": 3}]})
        result = reorder_banners(payload, "token")
    assert result == {"ok": True, "data": repo.client.rpc.return_value, "error": None}
    repo.client.rpc.assert_called_once()
    repo.client.rest_get.assert_not_called()
    repo.client.rest_patch.assert_not_called()


@patch("app.routers.banners.JoinRepository")
def test_stats_reads_daily_view_with_inclusive_dates_and_exact_envelope(repo_class):
    repo = repo_class.return_value
    banner_id = UUID(int=9)
    daily = [
        {"day": "2026-08-01", "impressions": 4, "clicks": 2, "grants": 1, "granted_units": 50},
        {"day": "2026-08-02", "impressions": 3, "clicks": 1, "grants": 0, "granted_units": 0},
    ]
    repo.client.rest_get.side_effect = [[{"id": str(banner_id)}], daily]
    with patch("app.routers.banners._merchant_admin", return_value=(SimpleNamespace(id="a"), "merchant")):
        result = banner_stats(banner_id, date(2026, 8, 1), date(2026, 8, 2), "token")
    assert result == {"ok": True, "data": {"banner_id": str(banner_id), "items": [
        {"day": "2026-08-01", "impressions": 4, "clicks": 2, "ctr": 50.0,
         "granted_count": 1, "granted_amount": 50},
        {"day": "2026-08-02", "impressions": 3, "clicks": 1, "ctr": 33.33,
         "granted_count": 0, "granted_amount": 0},
    ], "totals": {"impressions": 7, "clicks": 3, "granted_count": 1,
                    "granted_amount": 50, "ctr": 42.86}}, "error": None}
    name, params = repo.client.rest_get.call_args_list[1].args
    assert name == "v_banner_stats_daily" and params["day"] == "lte.2026-08-02"


@patch("app.routers.banners.JoinRepository")
def test_admin_list_includes_partner_and_bounded_daily_summary(repo_class):
    repo = repo_class.return_value
    repo.client.rest_get.side_effect = [[{
        "id": "banner", "merchant_id": "merchant", "partner_id": "partner", "is_active": True,
        "starts_at": None, "ends_at": None,
    }], [], [{"id": "partner", "name": "Partner", "status": "active"}], [{
        "banner_id": "banner", "impressions": 5, "clicks": 2, "grants": 1, "granted_units": 50,
    }]]
    with patch("app.routers.banners._merchant_admin", return_value=(SimpleNamespace(id="a"), "merchant")):
        result = admin_banners(token="token")
    item = result["data"]["items"][0]
    assert item["partner"] == {"id": "partner", "name": "Partner", "status": "active"}
    assert item["partner_name"] == "Partner"
    assert item["stats"] == {"impressions": 5, "clicks": 2, "ctr": 40.0,
                             "granted_count": 1, "granted_amount": 50}
    stats_params = repo.client.rest_get.call_args_list[3].args[1]
    assert repo.client.rest_get.call_args_list[3].args[0] == "v_banner_stats_daily"
    assert stats_params["day"].startswith("gte.")


@patch("app.routers.banners.get_settings")
@patch("app.routers.banners.JoinRepository")
def test_public_list_withholds_link_and_returns_final_reward_shape(repo_class, settings):
    repo = repo_class.return_value; settings.return_value.pilot_merchant_id = "merchant-1"
    repo.client.rest_get.side_effect = [
        [{"id": "merchant-1", "name": "pilot"}],
        [{"id": "banner-1", "merchant_id": "merchant-1", "partner_id": "partner-1", "title": "T",
          "image_url": "https://cdn/x", "image_alt": "alt", "link_url": "https://secret", "open_mode": "webview",
          "placement": "home_bottom", "sort_order": 0, "starts_at": None, "ends_at": None, "is_active": True}],
        [{"id": "reward-1", "banner_id": "banner-1", "reward_type": "point", "point_amount": 10,
          "grant_policy": "once", "total_budget": None, "granted_total": 0, "is_active": True}],
        [{"id": "partner-1", "name": "Partner", "status": "active"}],
    ]
    response = Response(); result = banners(response, "home_bottom", None)
    item = result["data"]["items"][0]
    assert response.headers["cache-control"] == "private, max-age=60"
    assert "link_url" not in item and item["partner_name"] == "Partner"
    assert item["reward"] == {"type": "point", "amount": 10, "available": False, "label": "10P 받기"}
    assert result == {"ok": True, "data": {"items": [item]}, "error": None}


def test_click_api_twenty_concurrent_calls_for_same_user_surface_one_grant():
    banner_id = UUID("33333333-3333-3333-3333-333333333333")
    repo = SimpleNamespace()
    client_api = SimpleNamespace()
    repo.client = client_api
    repo.auth_user_from_token = lambda _token: SimpleNamespace(
        id="11111111-1111-1111-1111-111111111111"
    )

    def rest_get(table, _params):
        if table == "partner_banners":
            return [{
                "id": str(banner_id), "merchant_id": "merchant-1",
                "partner_id": "partner-1", "link_url": "https://partner.example/go",
                "is_active": True, "starts_at": None, "ends_at": None,
            }]
        if table == "partners":
            return [{"id": "partner-1"}]
        raise AssertionError(table)

    lock = threading.Lock()
    granted = 0

    def rpc(name, _payload):
        nonlocal granted
        assert name == "grant_banner_reward"
        with lock:
            is_first = granted == 0
            if is_first:
                granted += 1
        return {
            "granted": is_first,
            "reason": "ok" if is_first else "already_granted",
            "reward_type": "point",
            "units": 100 if is_first else None,
            "balance_after": 100 if is_first else None,
        }

    client_api.rest_get = rest_get
    client_api.rpc = rpc

    async def issue_twenty(http):
        return await asyncio.gather(*[
            asyncio.to_thread(
                http.post,
                f"/v1/banners/{banner_id}/click",
                headers={"Authorization": "Bearer same-user"},
            )
            for _ in range(20)
        ])

    with patch("app.routers.banners.JoinRepository", return_value=repo):
        with TestClient(app) as http:
            responses = asyncio.run(issue_twenty(http))

    assert all(response.status_code == 200 for response in responses)
    payloads = [response.json()["data"] for response in responses]
    assert all(row["link_url"] == "https://partner.example/go" for row in payloads)
    assert sum(row["reward_granted"] is True for row in payloads) == 1
    assert granted == 1
