from __future__ import annotations

from typing import Any

from app.repositories.join_repository import JoinRepository
from app.services.join_flow import JoinErrorCode, JoinFlowError, UserProfile


class CompanyUsageRepository:
    """Service-role aggregate access with token-derived company ownership."""

    def __init__(self, join_repo: JoinRepository | None = None):
        self.join_repo = join_repo or JoinRepository()
        self.client = self.join_repo.client

    def actor(self, token: str) -> UserProfile:
        auth = self.join_repo.auth_user_from_token(token)
        actor = self.join_repo.get_profile(auth.id, email=auth.email)
        if (
            actor is None
            or actor.status != "active"
            or actor.role != "company_admin"
            or not actor.company_id
        ):
            raise JoinFlowError(JoinErrorCode.FORBIDDEN, "회사관리자만 이용 내역을 조회할 수 있어요")
        return actor

    def monthly_usage(self, actor_id: str, company_id: str, period_ym: str) -> dict[str, Any]:
        return self.client.rpc(
            "company_monthly_usage",
            {
                "p_actor_id": actor_id,
                "p_company_id": company_id,
                "p_period_ym": period_ym,
            },
        )
