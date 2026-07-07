from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.repositories.supabase_http import AuthUser, SupabaseHttpClient, SupabaseHttpError
from app.services.join_flow import (
    InviteCode,
    JoinFlowError,
    UserProfile,
    approve_pending_user,
    build_pending_join_request,
    reject_pending_user,
)


def _one(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    return rows[0] if rows else None


def _profile_from_row(row: dict[str, Any], *, email: str | None = None) -> UserProfile:
    return UserProfile(
        id=row["id"],
        email=email or row.get("email") or "",
        display_name=row.get("display_name") or "",
        company_id=row.get("company_id"),
        group_id=row.get("group_id"),
        role=row.get("role") or "employee",
        status=row.get("status"),
    )


class JoinRepository:
    def __init__(self, client: SupabaseHttpClient | None = None):
        self.client = client or SupabaseHttpClient()

    def auth_user_from_token(self, access_token: str) -> AuthUser:
        return self.client.auth_get_user(access_token)

    def get_profile(self, user_id: str, *, email: str | None = None) -> UserProfile | None:
        row = _one(self.client.rest_get("app_users", {"select": "*", "id": f"eq.{user_id}", "limit": "1"}))
        return _profile_from_row(row, email=email) if row else None

    def get_invite(self, code: str) -> InviteCode | None:
        row = _one(self.client.rest_get("company_invite_codes", {"select": "*", "code": f"eq.{code}", "limit": "1"}))
        if not row:
            return None
        expires_at = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00")) if row.get("expires_at") else None
        return InviteCode(
            code=row["code"],
            company_id=row["company_id"],
            default_group_id=row.get("default_group_id"),
            expires_at=expires_at,
            max_uses=row.get("max_uses"),
            used_count=row.get("used_count") or 0,
            is_active=bool(row.get("is_active")),
        )

    def request_join(self, *, access_token: str, invite_code: str, display_name: str) -> dict[str, Any]:
        auth_user = self.auth_user_from_token(access_token)
        existing = self.get_profile(auth_user.id, email=auth_user.email)
        user = existing or UserProfile(id=auth_user.id, email=auth_user.email or "", display_name=display_name)
        invite = self.get_invite(invite_code)
        result = build_pending_join_request(user=user, invite=invite, now=datetime.now(timezone.utc))

        payload = {
            "id": result.user_id,
            "company_id": result.company_id,
            "group_id": result.group_id,
            "display_name": display_name,
            "role": "employee",
            "status": "pending",
            "rejected_at": None,
        }
        if existing is None:
            self.client.rest_post("app_users", payload)
        else:
            self.client.rest_patch("app_users", {"id": f"eq.{result.user_id}"}, payload)

        # Increment is intentionally simple for M1. Production should replace this with a single RPC transaction.
        current_invite = self.client.rest_get("company_invite_codes", {"select": "used_count", "code": f"eq.{invite_code}", "limit": "1"})[0]
        self.client.rest_patch("company_invite_codes", {"code": f"eq.{invite_code}"}, {"used_count": (current_invite.get("used_count") or 0) + 1})
        self.client.rest_post("employee_join_audit_logs", {
            "user_id": result.user_id,
            "company_id": result.company_id,
            "action": "requested",
        })
        return {"user_id": result.user_id, "company_id": result.company_id, "group_id": result.group_id, "status": "pending"}

    def list_pending_join_requests(self, *, actor_token: str) -> list[dict[str, Any]]:
        actor_auth = self.auth_user_from_token(actor_token)
        actor = self.get_profile(actor_auth.id, email=actor_auth.email)
        if actor is None or actor.role != "company_admin" or actor.status != "active" or not actor.company_id:
            raise JoinFlowError("FORBIDDEN", "회사관리자만 조회할 수 있어요")
        return self.client.rest_get(
            "app_users",
            {
                "select": "id,company_id,group_id,display_name,role,status,created_at",
                "company_id": f"eq.{actor.company_id}",
                "status": "eq.pending",
                "order": "created_at.desc",
            },
        )

    def approve(self, *, actor_token: str, user_id: str) -> dict[str, Any]:
        actor_auth = self.auth_user_from_token(actor_token)
        actor = self.get_profile(actor_auth.id, email=actor_auth.email)
        target = self.get_profile(user_id)
        if actor is None or target is None:
            raise JoinFlowError("NOT_PENDING", "가입 요청을 찾을 수 없어요")
        status = approve_pending_user(actor=actor, target=target)
        updated = self.client.rest_patch("app_users", {"id": f"eq.{user_id}"}, {"status": status, "approved_at": datetime.now(timezone.utc).isoformat(), "rejected_at": None})[0]
        self.client.rest_post("employee_join_audit_logs", {"user_id": user_id, "company_id": target.company_id, "action": "approved", "actor_user_id": actor.id})
        return updated

    def reject(self, *, actor_token: str, user_id: str, reason: str) -> dict[str, Any]:
        actor_auth = self.auth_user_from_token(actor_token)
        actor = self.get_profile(actor_auth.id, email=actor_auth.email)
        target = self.get_profile(user_id)
        if actor is None or target is None:
            raise JoinFlowError("NOT_PENDING", "가입 요청을 찾을 수 없어요")
        status = reject_pending_user(actor=actor, target=target)
        updated = self.client.rest_patch("app_users", {"id": f"eq.{user_id}"}, {"status": status, "rejected_at": datetime.now(timezone.utc).isoformat()})[0]
        self.client.rest_post("employee_join_audit_logs", {"user_id": user_id, "company_id": target.company_id, "action": "rejected", "actor_user_id": actor.id, "reason": reason})
        return updated
