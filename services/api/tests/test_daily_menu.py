import unittest
from datetime import date, timedelta
from typing import cast
from unittest.mock import patch

from fastapi import HTTPException

from app.routers.admin import get_daily_menu, today_kst, upsert_daily_menu
from app.schemas import DailyMenuUpsertRequest


class DailyMenuScheduleTests(unittest.TestCase):
    @patch("app.routers.admin._admin_merchant", return_value={"id": "merchant-1"})
    @patch("app.routers.admin._active_admin", return_value={"id": "admin-1"})
    @patch("app.routers.admin.JoinRepository")
    def test_get_removes_past_and_returns_today_and_future_menus(
        self, repo_class, _active_admin, _admin_merchant
    ):
        today = today_kst()
        tomorrow = (date.fromisoformat(today) + timedelta(days=1)).isoformat()
        rows = [
            {"id": "today", "service_date": today, "title": "오늘 뷔페 메뉴"},
            {"id": "future", "service_date": tomorrow, "title": "내일 뷔페 메뉴"},
        ]
        client = repo_class.return_value.client
        client.rest_delete.return_value = []
        client.rest_get.return_value = rows

        result = get_daily_menu("token")["data"]

        client.rest_delete.assert_called_once_with(
            "merchant_daily_menus",
            {"merchant_id": "eq.merchant-1", "service_date": f"lt.{today}"},
        )
        self.assertEqual(result["today_menu"]["id"], "today")
        self.assertEqual([item["id"] for item in result["menus"]], ["today", "future"])

    @patch("app.routers.admin._admin_merchant", return_value={"id": "merchant-1"})
    @patch("app.routers.admin._active_admin", return_value={"id": "admin-1"})
    @patch("app.routers.admin.JoinRepository")
    def test_future_menu_can_be_saved(self, repo_class, _active_admin, _admin_merchant):
        service_date = date.fromisoformat(today_kst()) + timedelta(days=3)
        payload = DailyMenuUpsertRequest(
            service_date=service_date,
            title="금요일 뷔페 메뉴",
            menu_text="제육볶음, 샐러드",
        )
        client = repo_class.return_value.client
        client.rest_delete.return_value = []
        client.rest_get.return_value = []
        client.rest_post.return_value = [{
            "id": "future",
            "service_date": service_date.isoformat(),
            "title": payload.title,
            "menu_text": payload.menu_text,
            "image_url": None,
        }]

        result = upsert_daily_menu(payload, "token")["data"]

        self.assertEqual(result["service_date"], service_date.isoformat())
        self.assertEqual(client.rest_post.call_args.args[1]["service_date"], service_date.isoformat())

    @patch("app.routers.admin._admin_merchant", return_value={"id": "merchant-1"})
    @patch("app.routers.admin._active_admin", return_value={"id": "admin-1"})
    @patch("app.routers.admin.JoinRepository")
    def test_past_menu_is_rejected(self, repo_class, _active_admin, _admin_merchant):
        payload = DailyMenuUpsertRequest(
            service_date=date.fromisoformat(today_kst()) - timedelta(days=1),
            title="지난 메뉴",
            menu_text="지난 메뉴",
        )

        with self.assertRaises(HTTPException) as ctx:
            upsert_daily_menu(payload, "token")

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIsInstance(ctx.exception.detail, dict)
        self.assertEqual(cast(dict, ctx.exception.detail).get("code"), "PAST_DATE")
        repo_class.return_value.client.rest_delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
