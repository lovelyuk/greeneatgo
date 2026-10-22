"""Admin web UI themes (관리자 화면 테마).

Single server-side list of theme ids an admin account may save. The admin web
keeps the matching registry in apps/admin/src/themes.js. To add a theme, add its
id here and there, plus its stylesheet; the database only checks the id format.
"""
from __future__ import annotations

DEFAULT_ADMIN_THEME = "default"
ADMIN_THEMES: tuple[str, ...] = (DEFAULT_ADMIN_THEME, "calm-dark", "forest-stubs", "forest", "compact")
ADMIN_THEME_ROLES = frozenset({"merchant_admin", "company_admin", "platform_admin"})


def normalize_admin_theme(value: object) -> str:
    """Return a known theme id, falling back to the default for anything else."""
    return value if isinstance(value, str) and value in ADMIN_THEMES else DEFAULT_ADMIN_THEME
