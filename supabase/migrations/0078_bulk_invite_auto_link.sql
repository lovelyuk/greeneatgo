begin;

-- 0078: staff the company admin registered in bulk join without an invite code.
--
-- The app login proves the phone number by SMS (app_users.phone_verified_at),
-- so a verified number that matches a staged bulk row can be linked safely:
--   * brand-new signup  -> linked at once (p_fresh_only = true)
--   * existing personal member -> the app asks first; a refusal is recorded on
--     the staged row ('declined') so the company admin sees it and can re-invite.
-- People who are not on the list keep the invite-code + approval path.
-- Additive: the old activate_employee_bulk_invite function is left untouched (unused since 0072).

alter table public.employee_bulk_invites
  add column if not exists declined_at timestamptz,
  add column if not exists declined_by uuid references public.app_users(id);

do $$
declare c record;
begin
  for c in select conname from pg_constraint
            where conrelid = 'public.employee_bulk_invites'::regclass and contype = 'c'
              and pg_get_constraintdef(oid) like '%invited%' loop
    execute format('alter table public.employee_bulk_invites drop constraint %I', c.conname);
  end loop;
end $$;

alter table public.employee_bulk_invites
  add constraint employee_bulk_invites_status_check check (status in ('invited', 'active', 'declined')),
  add constraint employee_bulk_invites_state_check check (
       (status = 'invited'  and claimed_by is null and claimed_at is null and declined_at is null and declined_by is null)
    or (status = 'active'   and claimed_by is not null and claimed_at is not null and declined_at is null and declined_by is null)
    or (status = 'declined' and claimed_by is null and claimed_at is null and declined_at is not null));

-- The staged row waiting for this member, if any. Only an active personal
-- account whose phone was proven by SMS is ever offered a company.
create or replace function public.employee_bulk_invite_offer(p_user_id uuid)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare u public.app_users%rowtype; r record;
begin
  select * into u from public.app_users where id = p_user_id;
  if not found or u.role <> 'customer' or u.status <> 'active'
     or u.phone is null or u.phone_verified_at is null then
    return null;
  end if;
  select i.id, i.company_id, i.display_name, i.department, i.employee_no, c.name as company_name
    into r
    from public.employee_bulk_invites i join public.companies c on c.id = i.company_id
   where i.phone = u.phone and i.status = 'invited' and c.status = 'active'
   order by i.created_at desc, i.id limit 1;
  if not found then return null; end if;
  return jsonb_build_object('invite_id', r.id, 'company_id', r.company_id, 'company_name', r.company_name,
                            'display_name', r.display_name, 'department', r.department, 'employee_no', r.employee_no);
end $$;

-- Accept or decline the staged row. p_invite_id null = the row the offer shows.
-- p_fresh_only: called right after signup; links only an account created moments
-- ago that owns nothing yet, otherwise answers 'needs_confirmation' and changes nothing.
create or replace function public.respond_employee_bulk_invite(
  p_user_id uuid, p_invite_id uuid, p_accept boolean, p_fresh_only boolean default false)
returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare n timestamptz := clock_timestamp(); u public.app_users%rowtype; i public.employee_bulk_invites%rowtype;
        v_company_name text; v_group uuid;
begin
  select * into u from public.app_users where id = p_user_id for update;
  if not found or u.role <> 'customer' or u.status <> 'active'
     or u.phone is null or u.phone_verified_at is null then
    return jsonb_build_object('status', 'not_eligible');
  end if;

  select bi.* into i
    from public.employee_bulk_invites bi join public.companies c on c.id = bi.company_id
   where bi.phone = u.phone and bi.status = 'invited' and c.status = 'active'
     and (p_invite_id is null or bi.id = p_invite_id)
   order by bi.created_at desc, bi.id limit 1
   for update of bi;
  if not found then return jsonb_build_object('status', 'not_found'); end if;
  select name into v_company_name from public.companies where id = i.company_id;

  if p_fresh_only and (
       u.created_at is null or u.created_at < n - interval '10 minutes'
       or exists (select 1 from public.vouchers where user_id = u.id)
       or exists (select 1 from public.payment_orders where user_id = u.id)) then
    return jsonb_build_object('status', 'needs_confirmation', 'invite_id', i.id, 'company_name', v_company_name);
  end if;

  if not p_accept then
    update public.employee_bulk_invites
       set status = 'declined', declined_at = n, declined_by = u.id, updated_at = n
     where id = i.id;
    return jsonb_build_object('status', 'declined', 'invite_id', i.id, 'company_name', v_company_name);
  end if;

  select default_group_id into v_group from public.company_invite_codes
   where company_id = i.company_id and is_active order by created_at desc limit 1;
  begin
    update public.app_users
       set role = 'employee', company_id = i.company_id, group_id = v_group,
           display_name = i.display_name, employee_no = i.employee_no, department = i.department,
           status = 'active', approved_at = n, rejected_at = null
     where id = u.id;
  exception when unique_violation then
    -- Another employee of this company already holds the number or 사번.
    return jsonb_build_object('status', 'conflict');
  end;
  update public.employee_bulk_invites
     set status = 'active', claimed_by = u.id, claimed_at = n, updated_at = n
   where id = i.id;
  insert into public.employee_join_audit_logs(user_id, company_id, action)
    values (u.id, i.company_id, 'approved');
  return jsonb_build_object('status', 'accepted', 'invite_id', i.id,
                            'company_id', i.company_id, 'company_name', v_company_name);
end $$;

-- Company admin: offer the company again after the member declined.
create or replace function public.reinvite_employee_bulk_invite(p_company_id uuid, p_invite_id uuid)
returns boolean language plpgsql security definer set search_path = pg_catalog, public as $$
begin
  update public.employee_bulk_invites
     set status = 'invited', declined_at = null, declined_by = null, updated_at = clock_timestamp()
   where id = p_invite_id and company_id = p_company_id and status = 'declined';
  return found;
end $$;

revoke all on function public.employee_bulk_invite_offer(uuid) from public, anon, authenticated;
revoke all on function public.respond_employee_bulk_invite(uuid, uuid, boolean, boolean) from public, anon, authenticated;
revoke all on function public.reinvite_employee_bulk_invite(uuid, uuid) from public, anon, authenticated;
grant execute on function public.employee_bulk_invite_offer(uuid) to service_role;
grant execute on function public.respond_employee_bulk_invite(uuid, uuid, boolean, boolean) to service_role;
grant execute on function public.reinvite_employee_bulk_invite(uuid, uuid) to service_role;

notify pgrst, 'reload schema';

commit;
