-- 0070: per-account admin UI theme (관리자 화면 테마, 계정별 저장)
--
-- Additive only. Existing rows get 'default', which is the current admin design,
-- so nothing changes until an admin picks another theme.
--
-- The allowed theme ids live in the API (app/admin_themes.py) and the admin web
-- (apps/admin/src/themes.js). The database only checks the id format, so adding
-- a new theme later needs no migration.

alter table public.app_users
  add column if not exists admin_ui_theme text not null default 'default';

alter table public.app_users
  drop constraint if exists app_users_admin_ui_theme_format_check;
alter table public.app_users
  add constraint app_users_admin_ui_theme_format_check
  check (admin_ui_theme ~ '^[a-z0-9][a-z0-9-]{0,39}$');

comment on column public.app_users.admin_ui_theme is
  'Admin web UI theme id chosen by this admin account (default = current design).';

notify pgrst, 'reload schema';
