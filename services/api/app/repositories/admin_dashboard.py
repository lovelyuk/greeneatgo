from __future__ import annotations

from datetime import date
from typing import Any

from app.repositories.join_repository import JoinRepository
from app.services.join_flow import JoinErrorCode, JoinFlowError, UserProfile

DINNER_START_HOUR = 15
ADMIN_ROLES = frozenset(("merchant_admin", "company_admin", "platform_admin"))


class AdminDashboardRepository:
    def __init__(self, join_repo: JoinRepository | None = None):
        self.join_repo = join_repo or JoinRepository()
        self.client = self.join_repo.client

    def actor(self, token: str) -> UserProfile:
        auth = self.join_repo.auth_user_from_token(token)
        actor = self.join_repo.get_profile(auth.id, email=auth.email)
        if actor is None or actor.status != "active" or actor.role not in ADMIN_ROLES:
            raise JoinFlowError(JoinErrorCode.FORBIDDEN, "활성 관리자만 대시보드를 조회할 수 있어요")
        return actor

    def summary(
        self,
        actor_id: str,
        period_from: date,
        period_to: date,
        merchant_id: str | None,
        company_id: str | None,
    ) -> dict[str, Any]:
        return self.client.rpc(
            "admin_dashboard_summary",
            {
                "p_actor_id": actor_id,
                "p_period_from": period_from.isoformat(),
                "p_period_to": period_to.isoformat(),
                "p_merchant_id": merchant_id,
                "p_company_id": company_id,
                "p_dinner_start_hour": DINNER_START_HOUR,
            },
        )
