from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

class JoinErrorCode(StrEnum):
    INVALID_INVITE = "INVALID_INVITE"
    INVITE_EXPIRED = "INVITE_EXPIRED"
    INVITE_LIMIT = "INVITE_LIMIT"
    ALREADY_ACTIVE = "ALREADY_ACTIVE"
    ALREADY_PENDING = "ALREADY_PENDING"
    COMPANY_MISMATCH = "COMPANY_MISMATCH"
    NOT_PENDING = "NOT_PENDING"
    FORBIDDEN = "FORBIDDEN"

class JoinFlowError(Exception):
    def __init__(self, code: JoinErrorCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

@dataclass(frozen=True)
class InviteCode:
    code: str
    company_id: str
    default_group_id: str | None = None
    expires_at: datetime | None = None
    max_uses: int | None = None
    used_count: int = 0
    is_active: bool = True

@dataclass(frozen=True)
class UserProfile:
    id: str
    email: str
    display_name: str
    phone: str | None = None
    company_id: str | None = None
    merchant_id: str | None = None
    group_id: str | None = None
    role: str = "employee"
    status: str | None = None

@dataclass(frozen=True)
class JoinRequestResult:
    user_id: str
    company_id: str
    group_id: str | None
    status: str


def validate_invite(invite: InviteCode | None, *, now: datetime) -> InviteCode:
    if invite is None or not invite.is_active:
        raise JoinFlowError(JoinErrorCode.INVALID_INVITE, "유효하지 않은 초대코드예요")
    current = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    if invite.expires_at is not None:
        expires = invite.expires_at if invite.expires_at.tzinfo else invite.expires_at.replace(tzinfo=timezone.utc)
        if expires < current:
            raise JoinFlowError(JoinErrorCode.INVITE_EXPIRED, "만료된 초대코드예요")
    if invite.max_uses is not None and invite.used_count >= invite.max_uses:
        raise JoinFlowError(JoinErrorCode.INVITE_LIMIT, "초대코드 사용 가능 횟수를 초과했어요")
    return invite


def build_pending_join_request(*, user: UserProfile, invite: InviteCode, now: datetime) -> JoinRequestResult:
    validate_invite(invite, now=now)
    if user.status == "active":
        if user.company_id == invite.company_id:
            raise JoinFlowError(JoinErrorCode.ALREADY_ACTIVE, "이미 승인된 직원이에요")
        raise JoinFlowError(JoinErrorCode.COMPANY_MISMATCH, "이미 다른 회사에 연결된 계정이에요")
    if user.status == "pending" and user.company_id == invite.company_id:
        raise JoinFlowError(JoinErrorCode.ALREADY_PENDING, "이미 가입 승인 대기 중이에요")
    if user.company_id is not None and user.company_id != invite.company_id and user.status not in (None, "rejected"):
        raise JoinFlowError(JoinErrorCode.COMPANY_MISMATCH, "이미 다른 회사에 가입 요청된 계정이에요")
    return JoinRequestResult(user.id, invite.company_id, invite.default_group_id, "pending")


def assert_company_admin(actor: UserProfile, company_id: str) -> None:
    if actor.role != "company_admin" or actor.company_id != company_id or actor.status != "active":
        raise JoinFlowError(JoinErrorCode.FORBIDDEN, "회사관리자만 처리할 수 있어요")


def approve_pending_user(*, actor: UserProfile, target: UserProfile) -> str:
    if target.company_id is None:
        raise JoinFlowError(JoinErrorCode.NOT_PENDING, "가입 요청 회사가 없어요")
    assert_company_admin(actor, target.company_id)
    if target.status != "pending":
        raise JoinFlowError(JoinErrorCode.NOT_PENDING, "승인 대기 상태가 아니에요")
    return "active"


def reject_pending_user(*, actor: UserProfile, target: UserProfile) -> str:
    if target.company_id is None:
        raise JoinFlowError(JoinErrorCode.NOT_PENDING, "가입 요청 회사가 없어요")
    assert_company_admin(actor, target.company_id)
    if target.status != "pending":
        raise JoinFlowError(JoinErrorCode.NOT_PENDING, "승인 대기 상태가 아니에요")
    return "rejected"
