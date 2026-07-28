from typing import cast

import pytest

from app.repositories.company_usage import CompanyUsageRepository
from app.repositories.join_repository import JoinRepository
from app.repositories.supabase_http import AuthUser
from app.services.join_flow import JoinFlowError, UserProfile


class FakeClient:
    def __init__(self):
        self.calls = []

    def rpc(self, name, payload):
        self.calls.append((name, payload))
        return {"company_id": payload["p_company_id"]}


class FakeJoinRepository:
    def __init__(self, profile):
        self.profile = profile
        self.client = FakeClient()
        self.calls = []

    def auth_user_from_token(self, token):
        self.calls.append(("auth", token))
        return AuthUser(id="auth-user", email="admin@example.com")

    def get_profile(self, user_id, *, email=None):
        self.calls.append(("profile", user_id, email))
        return self.profile


def profile(**changes):
    values = dict(
        id="auth-user",
        email="admin@example.com",
        display_name="Admin",
        role="company_admin",
        status="active",
        company_id="company-from-profile",
    )
    values.update(changes)
    return UserProfile(**values)


def test_repository_authenticates_token_and_passes_only_profile_company_to_rpc():
    join = FakeJoinRepository(profile())
    repo = CompanyUsageRepository(cast(JoinRepository, join))
    actor = repo.actor("signed-token")
    assert actor.company_id is not None
    result = repo.monthly_usage(actor.id, actor.company_id, "2026-07")
    assert actor.company_id == "company-from-profile"
    assert join.calls == [
        ("auth", "signed-token"),
        ("profile", "auth-user", "admin@example.com"),
    ]
    assert join.client.calls == [(
        "company_monthly_usage",
        {
            "p_actor_id": "auth-user",
            "p_company_id": "company-from-profile",
            "p_period_ym": "2026-07",
        },
    )]
    assert result == {"company_id": "company-from-profile"}


@pytest.mark.parametrize(
    "bad_profile",
    [
        None,
        profile(role="employee"),
        profile(status="paused"),
        profile(company_id=None),
    ],
)
def test_repository_rejects_non_active_company_admin_profiles(bad_profile):
    repo = CompanyUsageRepository(cast(JoinRepository, FakeJoinRepository(bad_profile)))
    with pytest.raises(JoinFlowError):
        repo.actor("signed-token")
