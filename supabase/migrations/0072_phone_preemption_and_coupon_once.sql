begin;

-- 0072: phone-number account pre-emption and coupon reuse.
--
-- 1) Phone pre-emption. Legacy signup paths (/consumer/register, employee join
--    requests, Supabase user_metadata) store a phone number nobody proved. The
--    0061 phone login matched ANY account holding the number and marked it
--    verified, so whoever stored a victim's number first received the victim's
--    later phone login. From now on only accounts with phone_verified_at count:
--    an unverified holder loses the number to the person who proves it (login,
--    signup and phone change). The functions are 0061 verbatim except for the
--    marked detach lines and the removed "verify on first login" update.
--
-- 2) Public coupons are one use per person. Issued coupons (user_coupon_id) keep
--    their own single-use reservation from 0060. A public coupon is "used" once an
--    order with it was paid (provider key, fulfilment, done or refunded). A newer
--    unpaid order replaces an older one: voucher checkouts without reserved
--    points are cancelled, a subsidized checkout holding points must expire
--    (30 minutes) or be cancelled first.

create or replace function public.phone_auth_verify(p_phone text,p_purpose text,p_code_proof text,p_token_hash text)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare n timestamptz:=clock_timestamp(); v public.phone_verifications%rowtype; users jsonb; user_count int; u jsonb;
begin
 perform pg_advisory_xact_lock(hashtextextended('phone_auth_phone:'||p_phone,0));
 select * into v from public.phone_verifications where phone=p_phone and purpose=p_purpose and consumed_at is null and provider_msg_id is not null order by created_at desc limit 1 for update;
 if not found or v.expires_at<=n then if found then update public.phone_verifications set consumed_at=n where id=v.id; end if; return jsonb_build_object('status','expired'); end if;
 if extensions.crypt(p_code_proof,v.code_hash)<>v.code_hash then
   update public.phone_verifications set attempts=attempts+1, consumed_at=case when attempts+1>=max_attempts then n else consumed_at end where id=v.id returning attempts into v.attempts;
   if v.attempts>=v.max_attempts then return jsonb_build_object('status','too_many_attempts'); end if;
   return jsonb_build_object('status','invalid_code','attempts',v.attempts);
 end if;
 update public.phone_verifications set verified_at=n,consumed_at=n where id=v.id;
 if p_purpose='change_phone' then
   insert into public.phone_verification_tokens(token,verification_id,purpose,phone,expires_at)
    values(p_token_hash,v.id,p_purpose,p_phone,n+interval '5 minutes');
   return jsonb_build_object('status','verified','expires_in',300);
 end if;
 -- 0072: an unverified stored number never identifies an account. The proven
 -- owner of the number displaces it instead of signing in to that account.
 update public.app_users set phone=null where phone=p_phone and role in ('customer','employee') and phone_verified_at is null;
 select coalesce(jsonb_agg(jsonb_build_object('id',id,'display_name',display_name,'status',status)),'[]'::jsonb),count(*) into users,user_count from public.app_users where phone=p_phone and role in ('customer','employee');
 if user_count>1 then return jsonb_build_object('status','ambiguous'); end if;
 if user_count=1 then
   u:=users->0;
   if u->>'status' in ('left','rejected') then return jsonb_build_object('status','unavailable'); end if;
   return jsonb_build_object('status','existing','user_id',u->>'id','display_name',u->>'display_name');
 end if;
 insert into public.phone_verification_tokens(token,verification_id,purpose,phone,expires_at) values(p_token_hash,v.id,p_purpose,p_phone,n+interval '5 minutes');
 return jsonb_build_object('status','new','expires_in',300);
end $$;

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
   if exists(select 1 from public.app_users where id=deterministic_id and phone is distinct from t.phone) then
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

create or replace function public.phone_auth_change(p_token_hash text,p_actor_id uuid)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare n timestamptz:=clock_timestamp(); t public.phone_verification_tokens%rowtype;
begin
 select * into t from public.phone_verification_tokens where token=p_token_hash for update;
 if not found or t.purpose<>'change_phone' or t.consumed_at is not null or t.expires_at<=n then return jsonb_build_object('status','invalid_token'); end if;
 if not exists(select 1 from public.app_users where id=p_actor_id) then return jsonb_build_object('status','not_found'); end if;
 if not exists(select 1 from public.app_users where id=p_actor_id and role in ('customer','employee')) then return jsonb_build_object('status','forbidden'); end if;
 perform pg_advisory_xact_lock(hashtextextended('phone_auth_phone:'||t.phone,0));
 update public.app_users set phone=null where phone=t.phone and id<>p_actor_id and role in ('customer','employee') and phone_verified_at is null;
 begin update public.app_users set phone=t.phone,phone_verified_at=n where id=p_actor_id and role in ('customer','employee');
 exception when unique_violation then return jsonb_build_object('status','conflict'); end;
 if not found then return jsonb_build_object('status','not_found'); end if;
 update public.phone_verification_tokens set consumed_at=n where token=p_token_hash;
 return jsonb_build_object('status','ok','phone',t.phone);
end $$;

create or replace function public.enforce_public_coupon_once_0072() returns trigger
language plpgsql security definer set search_path = pg_catalog, public as $$
begin
 if new.coupon_id is null or new.user_coupon_id is not null or new.user_id is null then return new; end if;
 perform pg_advisory_xact_lock(hashtextextended('coupon_once:'||new.user_id::text||':'||new.coupon_id::text,0));
 if exists(select 1 from public.payment_orders o
            where o.user_id=new.user_id and o.coupon_id=new.coupon_id and o.user_coupon_id is null
              and (o.status in ('done','refunded') or o.fulfilled_at is not null or o.provider_payment_key is not null)) then
   raise exception 'COUPON_ALREADY_USED' using errcode='P0001';
 end if;
 if exists(select 1 from public.payment_orders o
            where o.user_id=new.user_id and o.coupon_id=new.coupon_id and o.user_coupon_id is null
              and o.status='ready' and o.point_reserved) then
   raise exception 'COUPON_IN_PROGRESS' using errcode='P0001';
 end if;
 update public.payment_orders set status='canceled',updated_at=clock_timestamp()
  where user_id=new.user_id and coupon_id=new.coupon_id and user_coupon_id is null
    and status='ready' and provider_payment_key is null and not point_reserved;
 return new;
end $$;
revoke all on function public.enforce_public_coupon_once_0072() from public, anon, authenticated, service_role;
drop trigger if exists trg_public_coupon_once on public.payment_orders;
create trigger trg_public_coupon_once before insert on public.payment_orders
 for each row execute function public.enforce_public_coupon_once_0072();

-- Existing data: an unpaid checkout must not be payable after the same person
-- already paid with the same public coupon.
update public.payment_orders r set status='canceled',updated_at=clock_timestamp()
 where r.status='ready' and r.coupon_id is not null and r.user_coupon_id is null
   and r.provider_payment_key is null and not r.point_reserved
   and exists(select 1 from public.payment_orders d
               where d.user_id=r.user_id and d.coupon_id=r.coupon_id and d.user_coupon_id is null and d.id<>r.id
                 and (d.status in ('done','refunded') or d.fulfilled_at is not null or d.provider_payment_key is not null));

notify pgrst, 'reload schema';
commit;
