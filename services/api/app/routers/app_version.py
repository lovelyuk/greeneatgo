from fastapi import APIRouter, Query

from app.config import get_settings

router = APIRouter(prefix="/app", tags=["app"])


@router.get("/version")
def app_version(platform: str = Query(default="android"), build: int = Query(default=0, ge=0)):
    """Tell an installed app whether it must or may update.

    Public and side-effect free: the app calls it before sign-in. Thresholds are
    env values so they change without an app release. An unknown platform or a
    missing build never forces an update.
    """
    settings = get_settings()
    key = platform.strip().lower()
    if key == "ios":
        minimum, latest, store_url = settings.app_min_build_ios, settings.app_latest_build_ios, settings.app_store_url_ios
    elif key == "android":
        minimum, latest, store_url = settings.app_min_build_android, settings.app_latest_build_android, settings.app_store_url_android
    else:
        minimum, latest, store_url = 0, 0, ""
    latest = max(latest, minimum)
    known = build > 0
    required = known and build < minimum
    return {
        "ok": True,
        "data": {
            "platform": key,
            "build": build,
            "min_build": minimum,
            "latest_build": latest,
            "update_required": required,
            "update_available": known and build < latest,
            "store_url": store_url,
        },
        "error": None,
    }
