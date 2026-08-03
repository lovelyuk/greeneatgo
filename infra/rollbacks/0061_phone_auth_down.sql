begin;
revoke all on function public.phone_auth_uuid5_0061(text), public.phone_auth_begin_send(text,text,inet), public.phone_auth_set_code_hash(uuid,text), public.phone_auth_finish_send(uuid,text,boolean), public.phone_auth_verify(text,text,text,text), public.phone_auth_signup(text,text), public.phone_auth_change(text,uuid) from public, anon, authenticated, service_role;
drop function public.phone_auth_change(text,uuid);
drop function public.phone_auth_signup(text,text);
drop function public.phone_auth_verify(text,text,text,text);
drop function public.phone_auth_finish_send(uuid,text,boolean);
drop function public.phone_auth_set_code_hash(uuid,text);
drop function public.phone_auth_begin_send(text,text,inet);
drop function public.phone_auth_uuid5_0061(text);
drop table public.phone_verification_tokens;
drop table public.phone_verifications;
drop trigger app_users_clear_phone_verification_on_phone_change_0061 on public.app_users;
drop function public.clear_phone_verification_on_phone_change_0061();
drop index public.uq_app_users_phone_login;
do $$
declare duplicate_company uuid; duplicate_phone text;
begin
 select company_id,phone into duplicate_company,duplicate_phone
 from public.app_users where company_id is not null and phone is not null
 group by company_id,phone having count(*) > 1 limit 1;
 if duplicate_phone is not null then
   raise exception '0061 rollback preflight failed: duplicate company phone (%, %)', duplicate_company,duplicate_phone;
 end if;
end $$;
create unique index uq_app_users_company_phone on public.app_users(company_id, phone)
 where company_id is not null and phone is not null;
alter table public.app_users drop constraint app_users_phone_login_format_check;
alter table public.app_users drop column phone_verified_at;
notify pgrst, 'reload schema';
commit;
