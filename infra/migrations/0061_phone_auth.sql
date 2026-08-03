begin;

-- Normalize existing values before enforcing phone-login invariants. Fail closed
-- when canonicalization would create invalid or duplicate consumer login IDs.
do $$
declare invalid_phone_count bigint; duplicate_login_phone text;
begin
  select count(*) into invalid_phone_count from public.app_users
   where phone is not null and btrim(phone) <> '' and (
     nullif(regexp_replace(phone,'[^0-9]','','g'),'') is null or
     nullif(regexp_replace(phone,'[^0-9]','','g'),'') !~ '^010[0-9]{8}$'
   );
  if invalid_phone_count > 0 then
    raise exception '0061 phone normalization preflight failed: % non-null normalized phone value(s) are not Korean mobile numbers', invalid_phone_count;
  end if;
  select normalized_phone into duplicate_login_phone from (
    select nullif(regexp_replace(phone,'[^0-9]','','g'),'') normalized_phone
      from public.app_users where phone is not null and role in ('customer','employee')
  ) n where normalized_phone is not null group by normalized_phone having count(*) > 1 limit 1;
  if duplicate_login_phone is not null then
    raise exception '0061 phone normalization preflight failed: duplicate login-role phone after normalization (%)', duplicate_login_phone;
  end if;
end $$;

-- 0017 scoped uniqueness by company across every role, which prevents a
-- login customer from sharing an administrative contact number.
drop index public.uq_app_users_company_phone;
update public.app_users set phone = nullif(regexp_replace(phone, '[^0-9]', '', 'g'), '')
 where phone is not null and phone is distinct from nullif(regexp_replace(phone, '[^0-9]', '', 'g'), '');
alter table public.app_users add column phone_verified_at timestamptz;
alter table public.app_users add constraint app_users_phone_login_format_check check (phone is null or phone ~ '^010[0-9]{8}$');
create unique index uq_app_users_phone_login on public.app_users(phone)
 where phone is not null and role in ('customer', 'employee');

create function public.clear_phone_verification_on_phone_change_0061() returns trigger
language plpgsql set search_path = pg_catalog, public as $$
begin
 if new.phone is distinct from old.phone and new.phone_verified_at is not distinct from old.phone_verified_at then new.phone_verified_at := null; end if;
 return new;
end $$;
create trigger app_users_clear_phone_verification_on_phone_change_0061 before update of phone, phone_verified_at on public.app_users
for each row execute function public.clear_phone_verification_on_phone_change_0061();

create table public.phone_verifications (
 id uuid primary key default gen_random_uuid(), phone text not null check(phone ~ '^010[0-9]{8}$'),
 code_hash text not null, purpose text not null check(purpose in ('signup_login', 'change_phone')),
 attempts integer not null default 0 check(attempts >= 0), max_attempts integer not null default 5 check(max_attempts > 0),
 expires_at timestamptz not null, verified_at timestamptz, consumed_at timestamptz,
 request_ip inet, provider_msg_id text, created_at timestamptz not null default now(),
 check(attempts <= max_attempts), unique(id,purpose)
);
create index idx_phone_verifications_lookup on public.phone_verifications(phone,purpose,created_at desc) where consumed_at is null;
create index idx_phone_verifications_created_at on public.phone_verifications(created_at);
create index idx_phone_verifications_ip_created_at on public.phone_verifications(request_ip,created_at) where request_ip is not null;
create table public.phone_verification_tokens (
 token text primary key, verification_id uuid not null, purpose text not null check(purpose in ('signup_login', 'change_phone')),
 phone text not null check(phone ~ '^010[0-9]{8}$'), expires_at timestamptz not null,
 consumed_at timestamptz, created_at timestamptz not null default now(),
 foreign key (verification_id, purpose) references public.phone_verifications(id, purpose) on delete cascade
);
comment on column public.phone_verification_tokens.token is 'One-way hash of the verification bearer token; never plaintext.';
create index idx_phone_verification_tokens_phone on public.phone_verification_tokens(phone,created_at desc);
create index idx_phone_verification_tokens_created_at on public.phone_verification_tokens(created_at);
alter table public.phone_verifications enable row level security;
alter table public.phone_verification_tokens enable row level security;
revoke all on table public.phone_verifications, public.phone_verification_tokens from public, anon, authenticated, service_role;
grant select, insert, update on table public.phone_verifications, public.phone_verification_tokens to service_role;

-- All mutation/cleanup is transactional and available only through these
-- SECURITY DEFINER RPCs. clock_timestamp() is authoritative; failed sends remain
-- consumed and count in rate limits, but can never be verified.
create function public.phone_auth_begin_send(p_phone text,p_purpose text,p_request_ip inet)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare n timestamptz:=clock_timestamp(); last_at timestamptz; c bigint; new_id uuid; retry integer;
begin
 if p_phone !~ '^010[0-9]{8}$' or p_purpose not in ('signup_login','change_phone') then raise exception 'PHONE_AUTH_INVALID' using errcode='P0001'; end if;
 -- Serialize the IP counter before the phone counter. The namespace prevents
 -- unrelated phone locks from colliding and this order is consistent for all sends.
 perform pg_advisory_xact_lock(hashtextextended('phone_auth_ip:'||coalesce(p_request_ip::text,''),0));
 perform pg_advisory_xact_lock(hashtextextended('phone_auth_phone:'||p_phone,0));
 delete from public.phone_verification_tokens where created_at < n-interval '7 days';
 delete from public.phone_verifications where created_at < n-interval '7 days';
 select max(created_at) into last_at from public.phone_verifications where phone=p_phone;
 if last_at is not null and last_at > n-interval '60 seconds' then retry:=greatest(1,ceil(extract(epoch from last_at+interval '60 seconds'-n))::int); return jsonb_build_object('status','cooldown','retry_after',retry); end if;
 select count(*) into c from public.phone_verifications where phone=p_phone and created_at>n-interval '1 hour';
 if c>=5 then return jsonb_build_object('status','phone_hour_limit','retry_after',3600); end if;
 select count(*) into c from public.phone_verifications where phone=p_phone and created_at>n-interval '1 day';
 if c>=10 then return jsonb_build_object('status','phone_day_limit','retry_after',86400); end if;
 select count(*) into c from public.phone_verifications where request_ip=p_request_ip and created_at>n-interval '1 hour';
 if c>=20 then return jsonb_build_object('status','ip_hour_limit','retry_after',3600); end if;
 update public.phone_verifications set consumed_at=n
  where phone=p_phone and purpose=p_purpose and consumed_at is null;
 insert into public.phone_verifications(phone,purpose,request_ip,code_hash,expires_at) values(p_phone,p_purpose,p_request_ip,'$pending$',n+interval '3 minutes') returning id into new_id;
 return jsonb_build_object('status','created','verification_id',new_id,'expires_in',180,'resend_after',60);
end $$;

create function public.phone_auth_set_code_hash(p_verification_id uuid,p_code_hash text)
returns boolean language plpgsql security definer set search_path = pg_catalog, public as $$
declare changed_count integer;
begin
 if p_code_hash !~ '^\$2[aby]\$[0-9]{2}\$[./A-Za-z0-9]{53}$' then return false; end if;
 update public.phone_verifications set code_hash=p_code_hash
  where id=p_verification_id and code_hash='$pending$' and provider_msg_id is null
    and consumed_at is null;
 get diagnostics changed_count = row_count;
 return changed_count = 1;
end $$;

create function public.phone_auth_finish_send(p_verification_id uuid,p_provider_msg_id text,p_delivered boolean)
returns void language plpgsql security definer set search_path = pg_catalog, public as $$
begin
 if p_delivered and nullif(p_provider_msg_id,'') is not null then
   update public.phone_verifications set provider_msg_id=p_provider_msg_id
    where id=p_verification_id and consumed_at is null
      and code_hash ~ '^\$2[aby]\$[0-9]{2}\$[./A-Za-z0-9]{53}$';
   if not found then
     update public.phone_verifications set consumed_at=clock_timestamp()
      where id=p_verification_id and consumed_at is null;
   end if;
 else
   update public.phone_verifications set consumed_at=clock_timestamp()
    where id=p_verification_id and consumed_at is null;
 end if;
end $$;

create function public.phone_auth_verify(p_phone text,p_purpose text,p_code_proof text,p_token_hash text)
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
 select coalesce(jsonb_agg(jsonb_build_object('id',id,'display_name',display_name,'status',status)),'[]'::jsonb),count(*) into users,user_count from public.app_users where phone=p_phone and role in ('customer','employee');
 if user_count>1 then return jsonb_build_object('status','ambiguous'); end if;
 if user_count=1 then
   u:=users->0;
   if u->>'status' in ('left','rejected') then return jsonb_build_object('status','unavailable'); end if;
   update public.app_users set phone_verified_at=n where id=(u->>'id')::uuid;
   return jsonb_build_object('status','existing','user_id',u->>'id','display_name',u->>'display_name');
 end if;
 insert into public.phone_verification_tokens(token,verification_id,purpose,phone,expires_at) values(p_token_hash,v.id,p_purpose,p_phone,n+interval '5 minutes');
 return jsonb_build_object('status','new','expires_in',300);
end $$;

create function public.phone_auth_uuid5_0061(p_name text) returns uuid language plpgsql immutable strict
set search_path = pg_catalog, public as $$
declare d bytea; h text;
begin
 d:=extensions.digest(decode('ad2bd92bc52f4b30bb594f789edbcdb0','hex')||convert_to(p_name,'UTF8'),'sha1');
 d:=set_byte(d,6,(get_byte(d,6)&15)|80);
 d:=set_byte(d,8,(get_byte(d,8)&63)|128);
 h:=encode(substring(d from 1 for 16),'hex');
 return (substring(h,1,8)||'-'||substring(h,9,4)||'-'||substring(h,13,4)||'-'||substring(h,17,4)||'-'||substring(h,21,12))::uuid;
end $$;

create function public.phone_auth_signup(p_token_hash text,p_display_name text)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare n timestamptz:=clock_timestamp(); t public.phone_verification_tokens%rowtype; u public.app_users%rowtype;
        deterministic_id uuid; user_count integer;
begin
 select * into t from public.phone_verification_tokens where token=p_token_hash for update;
 if not found or t.purpose<>'signup_login' or t.consumed_at is not null or t.expires_at<=n then return jsonb_build_object('status','invalid_token'); end if;
 if btrim(p_display_name)<>p_display_name or char_length(p_display_name)<1 or char_length(p_display_name)>20 then return jsonb_build_object('status','invalid_name'); end if;
 perform pg_advisory_xact_lock(hashtextextended('phone_auth_phone:'||t.phone,0));
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

create function public.phone_auth_change(p_token_hash text,p_actor_id uuid)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare n timestamptz:=clock_timestamp(); t public.phone_verification_tokens%rowtype;
begin
 select * into t from public.phone_verification_tokens where token=p_token_hash for update;
 if not found or t.purpose<>'change_phone' or t.consumed_at is not null or t.expires_at<=n then return jsonb_build_object('status','invalid_token'); end if;
 if not exists(select 1 from public.app_users where id=p_actor_id) then return jsonb_build_object('status','not_found'); end if;
 if not exists(select 1 from public.app_users where id=p_actor_id and role in ('customer','employee')) then return jsonb_build_object('status','forbidden'); end if;
 perform pg_advisory_xact_lock(hashtextextended('phone_auth_phone:'||t.phone,0));
 begin update public.app_users set phone=t.phone,phone_verified_at=n where id=p_actor_id and role in ('customer','employee');
 exception when unique_violation then return jsonb_build_object('status','conflict'); end;
 if not found then return jsonb_build_object('status','not_found'); end if;
 update public.phone_verification_tokens set consumed_at=n where token=p_token_hash;
 return jsonb_build_object('status','ok','phone',t.phone);
end $$;

revoke all on function public.phone_auth_uuid5_0061(text), public.phone_auth_begin_send(text,text,inet), public.phone_auth_set_code_hash(uuid,text), public.phone_auth_finish_send(uuid,text,boolean), public.phone_auth_verify(text,text,text,text), public.phone_auth_signup(text,text), public.phone_auth_change(text,uuid) from public, anon, authenticated, service_role;
grant execute on function public.phone_auth_begin_send(text,text,inet), public.phone_auth_set_code_hash(uuid,text), public.phone_auth_finish_send(uuid,text,boolean), public.phone_auth_verify(text,text,text,text), public.phone_auth_signup(text,text), public.phone_auth_change(text,uuid) to service_role;
notify pgrst, 'reload schema';
commit;
