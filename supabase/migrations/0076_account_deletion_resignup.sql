begin;

-- 0076: in-app account deletion (store review: App Store 5.1.1(v), Google Play).
-- DELETE /v1/me anonymises the profile (status 'left', no name/phone) and keeps
-- the transaction rows required by law. The phone-signup id is derived from the
-- number, so a returning user would hit that withdrawn row; signup now issues a
-- fresh id instead. Otherwise identical to 0072.

create or replace function public.phone_auth_signup(p_token_hash text,p_display_name text)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare n timestamptz:=clock_timestamp(); t public.phone_verification_tokens%rowtype; u public.app_users%rowtype;
        deterministic_id uuid; user_count integer;
begin
 select * into t from public.phone_verification_tokens where token=p_token_hash for update;
 if not found or t.purpose<>'signup_login' or t.consumed_at is not null or t.expires_at<=n then return jsonb_build_object('status','invalid_token'); end if;
 if btrim(p_display_name)<>p_display_name or char_length(p_display_name)<1 or char_length(p_display_name)>20 then return jsonb_build_object('status','invalid_name'); end if;
 perform pg_advisory_xact_lock(hashtextextended('phone_auth_phone:'||t.phone,0));
 update public.app_users set phone=null where phone=t.phone and role in ('customer','employee') and phone_verified_at is null;
 select count(*) into user_count from public.app_users where phone=t.phone and role in ('customer','employee');
 if user_count>1 then return jsonb_build_object('status','ambiguous'); end if;
 if user_count=1 then
   select * into u from public.app_users where phone=t.phone and role in ('customer','employee') for update;
   if u.status not in ('active','pending','paused') then return jsonb_build_object('status','unavailable'); end if;
 else
   deterministic_id:=public.phone_auth_uuid5_0061('phone_'||t.phone);
   -- 0076: a withdrawn (left) account keeps its id for the retained ledger; the
   -- same number may sign up again under a fresh id (custom token carries it).
   if exists(select 1 from public.app_users where id=deterministic_id and status='left') then
     deterministic_id:=gen_random_uuid();
   elsif exists(select 1 from public.app_users where id=deterministic_id and phone is distinct from t.phone) then
     return jsonb_build_object('status','id_conflict');
   end if;
   begin
     insert into public.app_users(id,display_name,phone,role,status,phone_verified_at)
      values(deterministic_id,p_display_name,t.phone,'customer','active',n) returning * into u;
   exception when unique_violation then
     select count(*) into user_count from public.app_users where phone=t.phone and role in ('customer','employee');
     if user_count>1 then return jsonb_build_object('status','ambiguous'); end if;
     if user_count=0 then return jsonb_build_object('status','id_conflict'); end if;
     select * into u from public.app_users where phone=t.phone and role in ('customer','employee') for update;
     if u.status not in ('active','pending','paused') then return jsonb_build_object('status','unavailable'); end if;
   end;
 end if;
 update public.phone_verification_tokens set consumed_at=n where token=p_token_hash;
 return jsonb_build_object('status','ok','user_id',u.id,'display_name',u.display_name,'phone',u.phone);
end $$;

revoke all on function public.phone_auth_signup(text,text) from public, anon, authenticated, service_role;
grant execute on function public.phone_auth_signup(text,text) to service_role;
notify pgrst, 'reload schema';
commit;
