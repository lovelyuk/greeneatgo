-- Company-admin employee bulk invitations and atomic first-login activation.
-- Pre-auth employees are staged here because app_users.id references auth.users(id).
-- Apply after 0016.

begin;

-- Fail before changing the schema when legacy manual edits already contain
-- duplicate company employee numbers. This keeps the migration atomic and
-- gives the operator a precise cleanup target instead of a partial install.
do $$
begin
  if exists (
    select 1 from app_users
    where company_id is not null and employee_no is not null
    group by company_id, employee_no having count(*) > 1
  ) then
    raise exception 'DUPLICATE_EXISTING_EMPLOYEE_NO: 회사별 중복 사번을 먼저 정리해 주세요';
  end if;
end $$;

alter table app_users
  add column if not exists phone text,
  add column if not exists department text;

alter table app_users drop constraint if exists app_users_phone_format_check;
alter table app_users add constraint app_users_phone_format_check
  check (phone is null or phone ~ '^010[0-9]{8}$');

create unique index if not exists uq_app_users_company_phone
  on app_users(company_id, phone) where company_id is not null and phone is not null;
create unique index if not exists uq_app_users_company_employee_no
  on app_users(company_id, employee_no) where company_id is not null and employee_no is not null;

create table if not exists employee_bulk_invites (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references companies(id),
  department text,
  display_name text not null check (btrim(display_name) <> ''),
  employee_no text not null check (btrim(employee_no) <> ''),
  phone text not null check (phone ~ '^010[0-9]{8}$'),
  status text not null default 'invited' check (status in ('invited', 'active')),
  claimed_by uuid references auth.users(id),
  claimed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check ((status = 'invited' and claimed_by is null and claimed_at is null)
      or (status = 'active' and claimed_by is not null and claimed_at is not null))
);

create unique index if not exists uq_employee_bulk_invites_company_phone
  on employee_bulk_invites(company_id, phone);
create unique index if not exists uq_employee_bulk_invites_company_employee_no
  on employee_bulk_invites(company_id, employee_no);
create unique index if not exists uq_employee_bulk_invites_claimed_by
  on employee_bulk_invites(claimed_by) where claimed_by is not null;
create index if not exists idx_employee_bulk_invites_company_status
  on employee_bulk_invites(company_id, status, created_at desc);

alter table employee_bulk_invites enable row level security;
-- No client policies: all reads/writes use the service-role API after company-admin authorization.

-- Inserts the already server-validated preview in one database transaction and repeats
-- critical validation under a company-scoped advisory lock to close parse/confirm races.
create or replace function confirm_employee_bulk_invites(p_company_id uuid, p_rows jsonb)
returns integer
language plpgsql security definer set search_path = public as $$
declare
  v_row jsonb;
  v_phone text;
  v_employee_no text;
  v_count integer;
begin
  if p_company_id is null or jsonb_typeof(p_rows) <> 'array' then
    raise exception 'INVALID_BULK_ROWS' using errcode = 'P0001';
  end if;
  v_count := jsonb_array_length(p_rows);
  if v_count < 1 or v_count > 500 then
    raise exception 'INVALID_BULK_ROWS' using errcode = 'P0001';
  end if;

  perform pg_advisory_xact_lock(hashtext(p_company_id::text));
  for v_row in select value from jsonb_array_elements(p_rows)
  loop
    v_phone := v_row->>'phone';
    v_employee_no := nullif(btrim(v_row->>'employee_no'), '');
    if nullif(btrim(v_row->>'display_name'), '') is null
       or v_phone !~ '^010[0-9]{8}$'
       or v_employee_no is null then
      raise exception 'INVALID_BULK_ROW' using errcode = 'P0001';
    end if;
    if exists (select 1 from app_users where company_id = p_company_id and phone = v_phone)
       or exists (select 1 from employee_bulk_invites where company_id = p_company_id and phone = v_phone) then
      raise exception 'DUPLICATE_PHONE' using errcode = 'P0001';
    end if;
    if exists (select 1 from app_users where company_id = p_company_id and employee_no = v_employee_no)
       or exists (select 1 from employee_bulk_invites where company_id = p_company_id and employee_no = v_employee_no) then
      raise exception 'DUPLICATE_EMPLOYEE_NO' using errcode = 'P0001';
    end if;
  end loop;

  if (select count(distinct value->>'phone') from jsonb_array_elements(p_rows)) <> v_count
     or (select count(distinct value->>'employee_no') from jsonb_array_elements(p_rows)) <> v_count then
    raise exception 'DUPLICATE_BULK_VALUE' using errcode = 'P0001';
  end if;

  insert into employee_bulk_invites(company_id, department, display_name, employee_no, phone)
  select p_company_id, nullif(btrim(value->>'department'), ''), btrim(value->>'display_name'),
         btrim(value->>'employee_no'), value->>'phone'
  from jsonb_array_elements(p_rows);
  return v_count;
end $$;
revoke all on function confirm_employee_bulk_invites(uuid, jsonb) from public, anon, authenticated;
grant execute on function confirm_employee_bulk_invites(uuid, jsonb) to service_role;

-- Keeps manual employee-number edits consistent with still-unclaimed bulk rows.
create or replace function update_company_employee_no(
  p_company_id uuid, p_user_id uuid, p_employee_no text
) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  v_number text := nullif(btrim(p_employee_no), '');
  v_user app_users%rowtype;
begin
  perform pg_advisory_xact_lock(hashtext(p_company_id::text));
  select * into v_user from app_users
   where id = p_user_id and company_id = p_company_id and role = 'employee'
   for update;
  if not found then
    raise exception 'EMPLOYEE_NOT_FOUND' using errcode = 'P0001';
  end if;
  if v_number is not null and exists (
    select 1 from employee_bulk_invites
     where company_id = p_company_id and employee_no = v_number
       and claimed_by is distinct from p_user_id
  ) then
    raise exception 'DUPLICATE_EMPLOYEE_NO' using errcode = 'P0001';
  end if;
  begin
    update app_users set employee_no = v_number where id = p_user_id returning * into v_user;
    update employee_bulk_invites set employee_no = v_number, updated_at = now()
     where claimed_by = p_user_id and v_number is not null;
  exception when unique_violation then
    raise exception 'DUPLICATE_EMPLOYEE_NO' using errcode = 'P0001';
  end;
  return to_jsonb(v_user);
end $$;
revoke all on function update_company_employee_no(uuid, uuid, text) from public, anon, authenticated;
grant execute on function update_company_employee_no(uuid, uuid, text) to service_role;

-- Claims a matching staged row only after independently validating and locking the invite code.
-- Existing customer/admin/company profiles are never converted or overwritten.
create or replace function activate_employee_bulk_invite(
  p_user_id uuid, p_company_id uuid, p_phone text, p_invite_code text
) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  v_invite_code company_invite_codes%rowtype;
  v_staged employee_bulk_invites%rowtype;
  v_existing app_users%rowtype;
  v_user app_users%rowtype;
begin
  perform pg_advisory_xact_lock(hashtext(p_company_id::text));
  select * into v_invite_code from company_invite_codes
   where code = p_invite_code and company_id = p_company_id for update;
  if not found or not v_invite_code.is_active
     or (v_invite_code.expires_at is not null and v_invite_code.expires_at < now())
     or (v_invite_code.max_uses is not null and v_invite_code.used_count >= v_invite_code.max_uses) then
    raise exception 'INVALID_INVITE' using errcode = 'P0001';
  end if;

  select * into v_staged from employee_bulk_invites
   where company_id = p_company_id and phone = p_phone and status = 'invited'
   for update;
  if not found then return null; end if;

  select * into v_existing from app_users where id = p_user_id for update;
  -- A bulk invitation may only create a profile for an auth user that has no
  -- app profile yet. Never revive paused/left/rejected users or overwrite a
  -- pending/active profile based on mutable auth metadata.
  if found then
    raise exception 'PROFILE_CONFLICT' using errcode = 'P0001';
  end if;

  insert into app_users(id, company_id, group_id, display_name, employee_no, phone, department,
                        role, status, approved_at, rejected_at)
  values (p_user_id, p_company_id, v_invite_code.default_group_id, v_staged.display_name,
          v_staged.employee_no, v_staged.phone, v_staged.department, 'employee', 'active', now(), null)
  returning * into v_user;

  update employee_bulk_invites set status = 'active', claimed_by = p_user_id,
    claimed_at = now(), updated_at = now() where id = v_staged.id;
  update company_invite_codes set used_count = used_count + 1 where id = v_invite_code.id;
  insert into employee_join_audit_logs(user_id, company_id, action)
    values (p_user_id, p_company_id, 'approved');
  return jsonb_build_object('user_id', v_user.id, 'company_id', v_user.company_id,
                            'group_id', v_user.group_id, 'status', v_user.status,
                            'bulk_invite_claimed', true);
end $$;
revoke all on function activate_employee_bulk_invite(uuid, uuid, text, text) from public, anon, authenticated;
grant execute on function activate_employee_bulk_invite(uuid, uuid, text, text) to service_role;

commit;
