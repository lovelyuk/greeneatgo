import unittest
from datetime import datetime, timedelta, timezone

from app.services.join_flow import (
    InviteCode,
    JoinErrorCode,
    JoinFlowError,
    UserProfile,
    approve_pending_user,
    build_pending_join_request,
    reject_pending_user,
    validate_invite,
)

NOW = datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc)

class JoinFlowTests(unittest.TestCase):
    def test_valid_invite_builds_pending_request(self):
        invite = InviteCode(code="PILOT", company_id="c1", default_group_id="g1", max_uses=10, used_count=2)
        user = UserProfile(id="u1", email="a@example.com", display_name="김민수")
        result = build_pending_join_request(user=user, invite=invite, now=NOW)
        self.assertEqual(result.company_id, "c1")
        self.assertEqual(result.group_id, "g1")
        self.assertEqual(result.status, "pending")

    def test_inactive_invite_rejected(self):
        with self.assertRaises(JoinFlowError) as ctx:
            validate_invite(InviteCode(code="X", company_id="c1", is_active=False), now=NOW)
        self.assertEqual(ctx.exception.code, JoinErrorCode.INVALID_INVITE)

    def test_expired_invite_rejected(self):
        with self.assertRaises(JoinFlowError) as ctx:
            validate_invite(InviteCode(code="X", company_id="c1", expires_at=NOW - timedelta(seconds=1)), now=NOW)
        self.assertEqual(ctx.exception.code, JoinErrorCode.INVITE_EXPIRED)

    def test_max_uses_rejected(self):
        with self.assertRaises(JoinFlowError) as ctx:
            validate_invite(InviteCode(code="X", company_id="c1", max_uses=2, used_count=2), now=NOW)
        self.assertEqual(ctx.exception.code, JoinErrorCode.INVITE_LIMIT)

    def test_already_pending_same_company(self):
        invite = InviteCode(code="PILOT", company_id="c1")
        user = UserProfile(id="u1", email="a@example.com", display_name="김민수", company_id="c1", status="pending")
        with self.assertRaises(JoinFlowError) as ctx:
            build_pending_join_request(user=user, invite=invite, now=NOW)
        self.assertEqual(ctx.exception.code, JoinErrorCode.ALREADY_PENDING)

    def test_active_other_company_rejected(self):
        invite = InviteCode(code="PILOT", company_id="c1")
        user = UserProfile(id="u1", email="a@example.com", display_name="김민수", company_id="c2", status="active")
        with self.assertRaises(JoinFlowError) as ctx:
            build_pending_join_request(user=user, invite=invite, now=NOW)
        self.assertEqual(ctx.exception.code, JoinErrorCode.COMPANY_MISMATCH)

    def test_company_admin_can_approve_pending_same_company(self):
        actor = UserProfile(id="admin", email="admin@example.com", display_name="관리자", company_id="c1", role="company_admin", status="active")
        target = UserProfile(id="u1", email="a@example.com", display_name="김민수", company_id="c1", status="pending")
        self.assertEqual(approve_pending_user(actor=actor, target=target), "active")

    def test_company_admin_can_reject_pending_same_company(self):
        actor = UserProfile(id="admin", email="admin@example.com", display_name="관리자", company_id="c1", role="company_admin", status="active")
        target = UserProfile(id="u1", email="a@example.com", display_name="김민수", company_id="c1", status="pending")
        self.assertEqual(reject_pending_user(actor=actor, target=target), "rejected")

    def test_other_company_admin_forbidden(self):
        actor = UserProfile(id="admin", email="admin@example.com", display_name="관리자", company_id="c2", role="company_admin", status="active")
        target = UserProfile(id="u1", email="a@example.com", display_name="김민수", company_id="c1", status="pending")
        with self.assertRaises(JoinFlowError) as ctx:
            approve_pending_user(actor=actor, target=target)
        self.assertEqual(ctx.exception.code, JoinErrorCode.FORBIDDEN)

    def test_employee_cannot_approve(self):
        actor = UserProfile(id="emp", email="emp@example.com", display_name="직원", company_id="c1", role="employee", status="active")
        target = UserProfile(id="u1", email="a@example.com", display_name="김민수", company_id="c1", status="pending")
        with self.assertRaises(JoinFlowError) as ctx:
            approve_pending_user(actor=actor, target=target)
        self.assertEqual(ctx.exception.code, JoinErrorCode.FORBIDDEN)

if __name__ == "__main__":
    unittest.main()
