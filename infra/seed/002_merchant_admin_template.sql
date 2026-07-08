-- 식당관리자 계정 연결 템플릿
-- 1) Supabase Dashboard > Authentication > Users 에서 식당관리자 이메일 계정을 먼저 만든다.
-- 2) 생성된 User UID를 아래 <AUTH_USER_ID>에 넣고 실행한다.
-- 3) 파일럿 식당 id는 20000000-0000-0000-0000-000000000001 이다.

insert into app_users (id, display_name, role, status)
values ('<AUTH_USER_ID>', '식당관리자', 'merchant_admin', 'active')
on conflict (id) do update set
  display_name = excluded.display_name,
  role = 'merchant_admin',
  status = 'active';

insert into merchant_admins (user_id, merchant_id)
values ('<AUTH_USER_ID>', '20000000-0000-0000-0000-000000000001')
on conflict (user_id) do update set
  merchant_id = excluded.merchant_id;
