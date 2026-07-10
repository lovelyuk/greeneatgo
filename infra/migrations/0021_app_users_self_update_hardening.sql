-- Keep profile and role changes behind the service-role API.
-- Authenticated clients may update only their own push-notification token.
revoke update on table public.app_users from anon, authenticated;
grant update (fcm_token) on table public.app_users to authenticated;

drop policy if exists app_users_update_self_fcm on public.app_users;
create policy app_users_update_self_fcm
on public.app_users
for update
to authenticated
using (auth.uid() = id)
with check (auth.uid() = id);
