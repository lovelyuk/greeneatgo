begin;

create table if not exists device_tokens (
  id uuid primary key default gen_random_uuid(),
  account_id uuid not null references app_users(id) on delete cascade,
  fcm_token text not null unique check (char_length(fcm_token) between 20 and 4096),
  platform text not null check (platform in ('android', 'ios')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_device_tokens_account_id on device_tokens(account_id);

create table if not exists notifications (
  id uuid primary key default gen_random_uuid(),
  merchant_id uuid not null references merchants(id),
  created_by uuid not null references app_users(id),
  title text not null check (char_length(btrim(title)) between 1 and 120),
  body text not null check (char_length(btrim(body)) between 1 and 1000),
  target_type text not null check (target_type in ('all', 'voucher_only')),
  status text not null default 'sending' check (status in ('sending', 'sent', 'partial', 'failed')),
  idempotency_key text not null,
  target_count int not null check (target_count >= 0),
  device_count int not null default 0 check (device_count >= 0),
  success_count int not null default 0 check (success_count >= 0),
  success_device_count int not null default 0 check (success_device_count >= 0),
  failure_device_count int not null default 0 check (failure_device_count >= 0),
  error_message text,
  sent_at timestamptz not null default now(),
  unique (merchant_id, idempotency_key)
);

create index if not exists idx_notifications_merchant_sent_at
  on notifications(merchant_id, sent_at desc);

alter table device_tokens enable row level security;
alter table notifications enable row level security;

-- All reads and writes are routed through the authenticated FastAPI service-role API.
revoke all on table device_tokens, notifications from anon, authenticated;

create or replace function register_device_token(
  p_account_id uuid,
  p_fcm_token text,
  p_platform text
) returns device_tokens
language plpgsql
security definer
set search_path = public
as $$
declare
  v_token device_tokens;
begin
  if p_platform not in ('android', 'ios')
     or char_length(p_fcm_token) not between 20 and 4096 then
    raise exception 'INVALID_DEVICE_TOKEN' using errcode = 'P0001';
  end if;

  insert into device_tokens(account_id, fcm_token, platform)
  values (p_account_id, p_fcm_token, p_platform)
  on conflict (fcm_token) do update
    set account_id = excluded.account_id,
        platform = excluded.platform,
        updated_at = now()
  returning * into v_token;
  return v_token;
end;
$$;

create or replace function unregister_device_token(
  p_account_id uuid,
  p_fcm_token text
) returns boolean
language plpgsql
security definer
set search_path = public
as $$
begin
  delete from device_tokens
  where account_id = p_account_id and fcm_token = p_fcm_token;
  return found;
end;
$$;

revoke all on function register_device_token(uuid, text, text) from public, anon, authenticated;
revoke all on function unregister_device_token(uuid, text) from public, anon, authenticated;
grant execute on function register_device_token(uuid, text, text) to service_role;
grant execute on function unregister_device_token(uuid, text) to service_role;

-- Preserve any legacy single-device token during the transition to multi-device storage.
insert into device_tokens(account_id, fcm_token, platform)
select id, fcm_token, 'android'
from app_users
where fcm_token is not null and char_length(fcm_token) between 20 and 4096
on conflict (fcm_token) do update
  set account_id = excluded.account_id,
      updated_at = now();

-- New clients use the API and device_tokens table; remove direct legacy column updates.
revoke update (fcm_token) on table app_users from authenticated;
drop policy if exists app_users_update_self_fcm on app_users;

commit;
