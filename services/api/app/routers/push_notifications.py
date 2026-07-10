from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from firebase_admin import exceptions as firebase_exceptions

from app.auth import bearer_token
from app.repositories.join_repository import JoinRepository
from app.repositories.supabase_http import SupabaseHttpError
from app.routers.merchant_admin import _merchant_admin
from app.schemas import DeviceTokenDeleteRequest, DeviceTokenRegisterRequest, NotificationCreateRequest
from app.services.join_flow import JoinFlowError
from app.services.push_notifications import PushConfigurationError, PushTarget, ensure_push_configured, send_push_notifications

router = APIRouter(tags=["push-notifications"])


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _is_missing_migration(exc: SupabaseHttpError) -> bool:
    body = exc.body.lower()
    return exc.status in (400, 404) and any(code in body for code in ("42p01", "pgrst202", "pgrst205", "device_tokens", "notifications"))


def _paged_get(repo: JoinRepository, table: str, params: dict[str, str], page_size: int = 1000) -> list[dict]:
    items: list[dict] = []
    offset = 0
    while True:
        page_params = {**params, "limit": str(page_size), "offset": str(offset)}
        page = repo.client.rest_get(table, page_params)
        items.extend(page)
        if len(page) < page_size:
            return items
        offset += page_size


def _audience(repo: JoinRepository, target_type: str) -> dict:
    role_filter = "eq.customer" if target_type == "voucher_only" else "in.(employee,customer)"
    accounts = _paged_get(
        repo,
        "app_users",
        {"select": "id", "role": role_filter, "status": "eq.active", "order": "id.asc"},
    )
    account_ids = [str(row["id"]) for row in accounts]
    token_rows: list[dict] = []
    for start in range(0, len(account_ids), 200):
        ids = account_ids[start:start + 200]
        token_rows.extend(_paged_get(
            repo,
            "device_tokens",
            {
                "select": "account_id,fcm_token",
                "account_id": f"in.({','.join(ids)})",
                "order": "account_id.asc,id.asc",
            },
        ))
    targets = [
        PushTarget(account_id=str(row["account_id"]), token=str(row["fcm_token"]))
        for row in token_rows
        if row.get("account_id") and row.get("fcm_token")
    ]
    return {
        "eligible_count": len(account_ids),
        "target_count": len({target.account_id for target in targets}),
        "device_count": len(targets),
        "targets": targets,
    }


def _push_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, JoinFlowError):
        return _error(403, str(exc.code), exc.message)
    if isinstance(exc, SupabaseHttpError):
        if exc.status in (401, 403):
            return _error(401, "UNAUTHENTICATED", "로그인이 필요해요")
        if _is_missing_migration(exc):
            return _error(409, "PUSH_MIGRATION_REQUIRED", "0022_push_notifications.sql 마이그레이션 적용이 필요해요")
        return _error(502, "SUPABASE_ERROR", "푸시 알림 정보를 처리하는 중 오류가 발생했어요")
    if isinstance(exc, PushConfigurationError):
        return _error(503, "FCM_NOT_CONFIGURED", str(exc))
    if isinstance(exc, (firebase_exceptions.FirebaseError, RuntimeError)):
        return _error(502, "FCM_SEND_FAILED", "FCM 푸시 발송 중 오류가 발생했어요")
    return _error(500, "PUSH_ERROR", "푸시 알림 처리 중 오류가 발생했어요")


@router.post("/device-tokens")
def register_device_token(payload: DeviceTokenRegisterRequest, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        auth = repo.auth_user_from_token(token)
        if payload.account_id != auth.id:
            raise _error(403, "ACCOUNT_MISMATCH", "본인 계정의 기기 토큰만 등록할 수 있어요")
        profile = repo.get_profile(auth.id, email=auth.email)
        if profile is None or profile.status != "active" or profile.role not in {"employee", "customer"}:
            raise _error(403, "FORBIDDEN", "활성 장부직원 또는 일반사용자만 기기 토큰을 등록할 수 있어요")
        repo.client.rpc("register_device_token", {
            "p_account_id": auth.id,
            "p_fcm_token": payload.fcm_token,
            "p_platform": payload.platform,
        })
        return {"ok": True, "data": {"registered": True}, "error": None}
    except Exception as exc:
        raise _push_error(exc) from exc


@router.delete("/device-tokens")
def unregister_device_token(payload: DeviceTokenDeleteRequest, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        auth = repo.auth_user_from_token(token)
        removed = repo.client.rpc("unregister_device_token", {
            "p_account_id": auth.id,
            "p_fcm_token": payload.fcm_token,
        })
        return {"ok": True, "data": {"removed": bool(removed)}, "error": None}
    except Exception as exc:
        raise _push_error(exc) from exc


@router.get("/admin/notifications/audience")
def notification_audience(
    target_type: Literal["all", "voucher_only"] = "all",
    token: str = Depends(bearer_token),
):
    repo = JoinRepository()
    try:
        _merchant_admin(repo, token)
        audience = _audience(repo, target_type)
        return {"ok": True, "data": {key: value for key, value in audience.items() if key != "targets"}, "error": None}
    except Exception as exc:
        raise _push_error(exc) from exc


@router.get("/admin/notifications")
def list_notifications(token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        _, merchant_id = _merchant_admin(repo, token)
        items = repo.client.rest_get(
            "notifications",
            {
                "select": "id,title,body,target_type,status,target_count,device_count,success_count,success_device_count,failure_device_count,sent_at",
                "merchant_id": f"eq.{merchant_id}",
                "order": "sent_at.desc,id.desc",
                "limit": "100",
            },
        )
        return {"ok": True, "data": {"items": items}, "error": None}
    except Exception as exc:
        if isinstance(exc, SupabaseHttpError) and _is_missing_migration(exc):
            return {"ok": True, "data": {"items": [], "migration_required": True}, "error": None}
        raise _push_error(exc) from exc


@router.post("/admin/notifications")
def create_notification(payload: NotificationCreateRequest, token: str = Depends(bearer_token)):
    repo = JoinRepository()
    try:
        actor, merchant_id = _merchant_admin(repo, token)
        audience = _audience(repo, payload.target_type)
        targets = audience["targets"]
        if not targets:
            raise _error(400, "NO_NOTIFICATION_TARGETS", "발송 대상이 없습니다")
        if (
            audience["target_count"] != payload.expected_target_count
            or audience["device_count"] != payload.expected_device_count
        ):
            raise HTTPException(status_code=409, detail={
                "code": "NOTIFICATION_AUDIENCE_CHANGED",
                "message": "발송 대상이 변경됐어요. 최신 인원을 확인하고 다시 발송해 주세요.",
                "target_count": audience["target_count"],
                "device_count": audience["device_count"],
            })

        ensure_push_configured()
        try:
            history = repo.client.rest_post("notifications", {
                "merchant_id": merchant_id,
                "created_by": actor.id,
                "title": payload.title,
                "body": payload.body,
                "target_type": payload.target_type,
                "status": "sending",
                "idempotency_key": payload.idempotency_key,
                "target_count": audience["target_count"],
                "device_count": audience["device_count"],
            })[0]
        except SupabaseHttpError as exc:
            if "23505" in exc.body.lower():
                raise _error(409, "NOTIFICATION_ALREADY_SUBMITTED", "이미 접수된 공지입니다. 발송 이력을 확인해 주세요") from exc
            raise

        try:
            result = send_push_notifications(title=payload.title, body=payload.body, targets=targets)
        except Exception:
            try:
                repo.client.rest_patch("notifications", {"id": f"eq.{history['id']}"}, {
                    "status": "failed",
                    "error_message": "FCM 발송 처리 중 오류",
                })
            except SupabaseHttpError:
                pass
            raise

        delivery_status = (
            "failed" if result.success_device_count == 0
            else "partial" if result.failure_device_count > 0
            else "sent"
        )
        history_update = {
            "status": delivery_status,
            "success_count": result.success_count,
            "success_device_count": result.success_device_count,
            "failure_device_count": result.failure_device_count,
            "error_message": "일부 기기 발송 실패" if delivery_status == "partial" else (
                "모든 기기 발송 실패" if delivery_status == "failed" else None
            ),
        }
        try:
            history = repo.client.rest_patch(
                "notifications", {"id": f"eq.{history['id']}"}, history_update
            )[0]
        except SupabaseHttpError:
            history = {**history, **history_update}

        for invalid_token in result.invalid_tokens:
            try:
                repo.client.rest_delete("device_tokens", {"fcm_token": f"eq.{invalid_token}"})
            except SupabaseHttpError:
                pass

        return {
            "ok": True,
            "data": {
                "notification": history,
                "target_count": result.target_count,
                "device_count": result.device_count,
                "success_count": result.success_count,
                "success_device_count": result.success_device_count,
                "failure_device_count": result.failure_device_count,
            },
            "error": None,
        }
    except Exception as exc:
        raise _push_error(exc) from exc
