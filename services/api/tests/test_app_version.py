from dataclasses import replace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app

client = TestClient(app)


def _get(platform, build, **overrides):
    settings = replace(get_settings(), **overrides)
    with patch("app.routers.app_version.get_settings", return_value=settings):
        response = client.get("/v1/app/version", params={"platform": platform, "build": build})
    assert response.status_code == 200
    return response.json()["data"]


def test_no_thresholds_means_no_prompt():
    data = _get("android", 62, app_min_build_android=0, app_latest_build_android=0)
    assert data["update_required"] is False and data["update_available"] is False


def test_below_minimum_is_required_and_below_latest_is_offered():
    limits = dict(app_min_build_android=63, app_latest_build_android=65)
    assert _get("android", 62, **limits)["update_required"] is True
    offered = _get("android", 63, **limits)
    assert offered["update_required"] is False and offered["update_available"] is True
    current = _get("android", 65, **limits)
    assert current["update_required"] is False and current["update_available"] is False
    assert offered["store_url"].endswith("id=com.greeneatfood.babdaeri")


def test_platforms_are_independent_and_unknown_never_forces():
    limits = dict(app_min_build_android=70, app_latest_build_android=70, app_min_build_ios=0, app_latest_build_ios=0)
    assert _get("ios", 10, **limits)["update_required"] is False
    assert _get("windows", 1, **limits) == {
        "platform": "windows", "build": 1, "min_build": 0, "latest_build": 0,
        "update_required": False, "update_available": False, "store_url": "",
    }


def test_missing_build_never_forces_and_minimum_raises_latest():
    data = _get("android", 0, app_min_build_android=70, app_latest_build_android=65)
    assert data["update_required"] is False and data["update_available"] is False
    assert data["latest_build"] == 70


def test_env_build_parsing(monkeypatch):
    from app.config import _env_build
    for raw, expected in [("63", 63), (" 64 ", 64), ("", 0), ("abc", 0), ("-3", 0), ("6.2", 0)]:
        monkeypatch.setenv("APP_MIN_BUILD_ANDROID", raw)
        assert _env_build("APP_MIN_BUILD_ANDROID") == expected
