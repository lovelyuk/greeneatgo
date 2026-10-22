import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.admin_themes import ADMIN_THEMES, DEFAULT_ADMIN_THEME, normalize_admin_theme
from app.repositories.supabase_http import SupabaseHttpError
from app.routers.me import me, update_admin_preferences
from app.schemas import AdminPreferencesUpdateRequest
from app.services.join_flow import UserProfile


def _profile(role: str, status: str = "active") -> UserProfile:
    return UserProfile(id="user-1", email="a@example.com", display_name="관리자", role=role, status=status,
                       merchant_id="m-1" if role == "merchant_admin" else None,
                       company_id="c-1" if role == "company_admin" else None)


class AdminThemeRegistryTests(unittest.TestCase):
    def test_default_is_current_design_and_calm_dark_is_listed(self):
        self.assertEqual(DEFAULT_ADMIN_THEME, "default")
        self.assertEqual(ADMIN_THEMES[0], "default")
        for theme in ("calm-dark", "forest-stubs", "forest", "compact"):
            self.assertIn(theme, ADMIN_THEMES)

    def test_unknown_or_missing_theme_falls_back_to_default(self):
        for value in (None, "", "neon", 3, "CALM-DARK"):
            self.assertEqual(normalize_admin_theme(value), "default")
        self.assertEqual(normalize_admin_theme("calm-dark"), "calm-dark")

    def test_request_accepts_only_registered_themes(self):
        self.assertEqual(AdminPreferencesUpdateRequest(admin_theme="calm-dark").admin_theme, "calm-dark")
        for bad in ("neon", "", "calm-dark; drop"):
            with self.assertRaises(ValidationError):
                AdminPreferencesUpdateRequest(admin_theme=bad)
        with self.assertRaises(ValidationError):
            AdminPreferencesUpdateRequest(admin_theme="default", user_id="other")


class AdminThemePreferenceRouteTests(unittest.TestCase):
    @patch("app.routers.me.JoinRepository")
    def test_admin_saves_theme_on_own_row_only(self, repo_class):
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(id="user-1", email="a@example.com")
        repo.get_profile.return_value = _profile("merchant_admin")
        repo.client.rest_patch.return_value = [{"admin_ui_theme": "calm-dark"}]

        result = update_admin_preferences(AdminPreferencesUpdateRequest(admin_theme="calm-dark"), "token")

        table, filters, values = repo.client.rest_patch.call_args.args
        self.assertEqual((table, filters, values), ("app_users", {"id": "eq.user-1"}, {"admin_ui_theme": "calm-dark"}))
        self.assertEqual(result["data"], {"admin_theme": "calm-dark"})

    @patch("app.routers.me.JoinRepository")
    def test_buyers_and_inactive_admins_cannot_save_theme(self, repo_class):
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(id="user-1", email="a@example.com")
        for profile in (_profile("customer"), _profile("employee"), _profile("company_admin", "suspended")):
            repo.get_profile.return_value = profile
            with self.assertRaises(HTTPException) as ctx:
                update_admin_preferences(AdminPreferencesUpdateRequest(admin_theme="calm-dark"), "token")
            self.assertEqual(ctx.exception.status_code, 403)
        repo.client.rest_patch.assert_not_called()

    @patch("app.routers.me.JoinRepository")
    def test_missing_column_reports_migration_required(self, repo_class):
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(id="user-1", email="a@example.com")
        repo.get_profile.return_value = _profile("company_admin")
        repo.client.rest_patch.side_effect = SupabaseHttpError(400, '{"code":"PGRST204","message":"admin_ui_theme"}')
        with self.assertRaises(HTTPException) as ctx:
            update_admin_preferences(AdminPreferencesUpdateRequest(admin_theme="calm-dark"), "token")
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail["code"], "MIGRATION_REQUIRED")

    @patch("app.routers.me.JoinRepository")
    def test_me_returns_saved_theme_for_admins(self, repo_class):
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(id="user-1", email="a@example.com")
        repo.get_profile.return_value = _profile("merchant_admin")
        repo.client.rest_get.return_value = [{"admin_ui_theme": "calm-dark"}]
        self.assertEqual(me("token")["data"]["admin_theme"], "calm-dark")

    @patch("app.routers.me.JoinRepository")
    def test_me_defaults_theme_before_migration(self, repo_class):
        repo = repo_class.return_value
        repo.auth_user_from_token.return_value = SimpleNamespace(id="user-1", email="a@example.com")
        repo.get_profile.return_value = _profile("platform_admin")
        repo.client.rest_get.side_effect = SupabaseHttpError(400, '{"code":"42703","message":"column app_users.admin_ui_theme does not exist"}')
        self.assertEqual(me("token")["data"]["admin_theme"], "default")


if __name__ == "__main__":
    unittest.main()
