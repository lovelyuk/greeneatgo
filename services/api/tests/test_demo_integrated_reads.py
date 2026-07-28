from types import SimpleNamespace
from unittest.mock import patch

from app.routers.merchant_admin import list_transactions


@patch("app.routers.merchant_admin.JoinRepository")
def test_merchant_visible_feed_uses_base_rows_and_demo_snapshot_amount(repo_class):
    repo = repo_class.return_value
    repo.auth_user_from_token.return_value = SimpleNamespace(id="admin", email="admin@example.com")
    repo.get_profile.return_value = SimpleNamespace(
        id="admin", role="merchant_admin", status="active", merchant_id="merchant-1"
    )
    repo.client.rest_get.side_effect = [
        [{"id": "demo", "user_id": "user-1", "company_id": "company-1", "amount": 0,
          "kind": "spend", "pay_type": "ledger", "is_demo": True,
          "settlement_total_amount": 71000, "created_at": "2026-07-22T01:03:00Z"}],
        [],
        [{"id": "user-1", "display_name": "시연직원", "company_id": "company-1"}],
        [{"id": "company-1", "name": "시연업체"}],
    ]
    repo.client.rpc.return_value = 1

    item = list_transactions("bearer")["data"]["items"][0]

    assert repo.client.rest_get.call_args_list[0].args[0] == "meal_transactions"
    repo.client.rpc.assert_called_once_with("merchant_payment_feed_count", {"p_merchant_id": "merchant-1"})
    assert item["amount"] == -71000
    assert item["is_demo"] is True
    assert item["company_name"] == "시연업체"
