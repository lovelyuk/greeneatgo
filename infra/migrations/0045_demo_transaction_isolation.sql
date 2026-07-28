begin;

-- Durable classification.  The JSON flag remains useful audit evidence, while
-- these indexed columns are the query boundary used by PostgREST and SQL reads.
alter table public.meal_transactions
  add column if not exists is_demo boolean not null default false;
alter table public.settlements
  add column if not exists is_demo boolean not null default false;

update public.meal_transactions t
set is_demo = true
from public.settlement_demo_transactions dt
where dt.transaction_id = t.id and not t.is_demo;

update public.settlements s
set is_demo = true
from public.settlement_demo_runs r
where r.settlement_id = s.id and not s.is_demo;

-- The original schema made period identity globally unique. Demo audit rows are
-- intentionally durable, so those global keys would permanently reserve a real
-- merchant/company period. Uniqueness applies only to ordinary settlements;
-- multiple archived demo audits may use the same period. Backfill above must
-- precede creation of these partial indexes.
alter table public.settlements
  drop constraint if exists settlements_company_id_merchant_id_period_ym_key;
drop index if exists public.idx_settlements_company_merchant_period;
create unique index if not exists settlements_normal_company_merchant_period_ym_key
  on public.settlements(company_id,merchant_id,period_ym) where not is_demo;
create unique index if not exists settlements_normal_company_merchant_period_range_key
  on public.settlements(company_id,merchant_id,period_from,period_to)
  where not is_demo and period_from is not null and period_to is not null;

create index if not exists meal_transactions_normal_merchant_created_idx
  on public.meal_transactions(merchant_id, created_at desc) where not is_demo;
create index if not exists meal_transactions_normal_company_created_idx
  on public.meal_transactions(company_id, created_at desc) where not is_demo;
create index if not exists settlements_normal_merchant_created_idx
  on public.settlements(merchant_id, created_at desc) where not is_demo;
create index if not exists settlements_normal_company_created_idx
  on public.settlements(company_id, created_at desc) where not is_demo;

create or replace function public.enforce_demo_transaction_marker()
returns trigger language plpgsql security definer set search_path=pg_catalog,public as $$
begin
  if tg_op='UPDATE' and old.is_demo and not new.is_demo
     and exists(select 1 from public.settlement_demo_transactions d where d.transaction_id=old.id) then
    raise exception 'DEMO_TRANSACTION_MARKER_IMMUTABLE' using errcode='P0001';
  end if;
  -- Demo seeds carry both immutable DB membership and the pre-existing audit flag.
  if new.flags->>'settlement_demo' = 'true' then new.is_demo := true; end if;
  return new;
end $$;
revoke all on function public.enforce_demo_transaction_marker() from public,anon,authenticated,service_role;
drop trigger if exists enforce_demo_transaction_marker on public.meal_transactions;
create trigger enforce_demo_transaction_marker
before insert or update of flags,is_demo on public.meal_transactions
for each row execute function public.enforce_demo_transaction_marker();

create or replace function public.mark_linked_demo_transaction()
returns trigger language plpgsql security definer set search_path=pg_catalog,public as $$
begin
  update public.meal_transactions set is_demo=true
  where id=new.transaction_id and not is_demo;
  return new;
end $$;
revoke all on function public.mark_linked_demo_transaction() from public,anon,authenticated,service_role;
drop trigger if exists mark_linked_demo_transaction on public.settlement_demo_transactions;
create trigger mark_linked_demo_transaction
before insert or update of transaction_id on public.settlement_demo_transactions
for each row execute function public.mark_linked_demo_transaction();

create or replace function public.mark_demo_settlement()
returns trigger language plpgsql security definer set search_path=pg_catalog,public as $$
begin
  if new.settlement_id is not null then
    update public.settlements set is_demo=true
    where id=new.settlement_id and not is_demo;
  end if;
  return null;
end $$;
revoke all on function public.mark_demo_settlement() from public,anon,authenticated,service_role;
drop trigger if exists mark_demo_settlement on public.settlement_demo_runs;
create trigger mark_demo_settlement
after insert or update of settlement_id on public.settlement_demo_runs
for each row execute function public.mark_demo_settlement();

create or replace function public.enforce_demo_settlement_marker()
returns trigger language plpgsql security definer set search_path=pg_catalog,public as $$
begin
  if old.is_demo and not new.is_demo
     and exists(select 1 from public.settlement_demo_runs r where r.settlement_id=old.id) then
    raise exception 'DEMO_SETTLEMENT_MARKER_IMMUTABLE' using errcode='P0001';
  end if;
  return new;
end $$;
revoke all on function public.enforce_demo_settlement_marker() from public,anon,authenticated,service_role;
drop trigger if exists enforce_demo_settlement_marker on public.settlements;
create trigger enforce_demo_settlement_marker
before update of is_demo on public.settlements
for each row execute function public.enforce_demo_settlement_marker();

-- Service-role bypasses RLS, so ordinary PostgREST reads use fail-closed views
-- rather than relying on caller-supplied filters. Demo RPCs continue to read the
-- base tables through explicit run membership.
create or replace view public.normal_meal_transactions
with (security_invoker=true) as
select * from public.meal_transactions where not is_demo;
create or replace view public.normal_settlements
with (security_invoker=true) as
select * from public.settlements where not is_demo;
create or replace view public.normal_reviews
with (security_invoker=true) as
select r.* from public.reviews r
join public.meal_transactions t on t.id=r.transaction_id
where not t.is_demo;
revoke all on public.normal_meal_transactions,public.normal_settlements,public.normal_reviews
  from public,anon,authenticated;
grant select on public.normal_meal_transactions,public.normal_settlements,public.normal_reviews to service_role;

-- Realtime SELECT authorization evaluates these policies. Excluding demo rows
-- here prevents both the customer and merchant-admin subscriptions from ever
-- receiving demo payloads.
drop policy if exists meal_transactions_select_self on public.meal_transactions;
create policy meal_transactions_select_self on public.meal_transactions for select
using (not is_demo and auth.uid()=user_id);
drop policy if exists merchant_admin_read_own_transactions on public.meal_transactions;
create policy merchant_admin_read_own_transactions on public.meal_transactions for select to authenticated
using (not is_demo and merchant_id in (
  select coalesce(u.merchant_id,ma.merchant_id)
  from public.app_users u left join public.merchant_admins ma on ma.user_id=u.id
  where u.id=auth.uid() and u.role='merchant_admin' and u.status='active'
));

-- Preserve the exact audited 0039 creator for the demo, then make the public
-- compatibility signature aggregate only ordinary transactions.  The internal
-- copy is deliberately not executable by PostgREST roles.
do $isolate_creator$
declare demo_ddl text; normal_ddl text; source_ddl text;
begin
  source_ddl := pg_get_functiondef('public.create_merchant_settlement(uuid,uuid,date,date)'::regprocedure);
  if to_regprocedure('public.settlement_demo_create_merchant_settlement(uuid,uuid,date,date)') is null then
    if (length(source_ddl)-length(replace(source_ddl,'FUNCTION public.create_merchant_settlement(','')))
       / length('FUNCTION public.create_merchant_settlement(') <> 1 then
      raise exception '0045 creator clone header assertion failed';
    end if;
    demo_ddl := replace(source_ddl,'FUNCTION public.create_merchant_settlement(',
      'FUNCTION public.settlement_demo_create_merchant_settlement(');
    execute demo_ddl;
  end if;

  normal_ddl := source_ddl;
  if position('public.normal_meal_transactions t' in normal_ddl)=0 then
    if (length(normal_ddl)-length(replace(normal_ddl,'from public.meal_transactions t where','')))
       / length('from public.meal_transactions t where') <> 1 then
      raise exception '0045 creator transaction source assertion failed';
    end if;
    normal_ddl := replace(normal_ddl,
    'from public.meal_transactions t where',
    'from public.normal_meal_transactions t where');
  end if;
  if position('and not is_demo for update' in normal_ddl)=0 then
    if (length(normal_ddl)-length(replace(normal_ddl,
       'where merchant_id=p_merchant_id and company_id=p_company_id and period_ym=v_period_ym for update','')))
       / length('where merchant_id=p_merchant_id and company_id=p_company_id and period_ym=v_period_ym for update') <> 1 then
      raise exception '0045 creator existing-row assertion failed';
    end if;
    normal_ddl := replace(normal_ddl,
    'where merchant_id=p_merchant_id and company_id=p_company_id and period_ym=v_period_ym for update',
    'where merchant_id=p_merchant_id and company_id=p_company_id and period_ym=v_period_ym and not is_demo for update');
  end if;
  if position('public.normal_meal_transactions' in normal_ddl)=0
     or position('and not is_demo for update' in normal_ddl)=0 then
    raise exception '0045 creator isolation rewrite failed';
  end if;
  execute normal_ddl;
end $isolate_creator$;
revoke all on function public.settlement_demo_create_merchant_settlement(uuid,uuid,date,date)
  from public,anon,authenticated,service_role;

-- The demo orchestration is the sole caller allowed to opt into the cloned
-- creator. It continues to verify exact run transaction membership afterward.
do $isolate_demo_create$
declare ddl text;
  spaced text := 'public.create_merchant_settlement(p_merchant_id, r.company_id, r.period_from, r.period_to)';
  compact text := 'public.create_merchant_settlement(p_merchant_id,r.company_id,r.period_from,r.period_to)';
  occurrences int;
begin
  ddl := pg_get_functiondef('public.settlement_demo_create(uuid,uuid)'::regprocedure);
  if position('public.settlement_demo_create_merchant_settlement(' in ddl)=0 then
    occurrences := (length(ddl)-length(replace(ddl,spaced,'')))/length(spaced)
      + (length(ddl)-length(replace(ddl,compact,'')))/length(compact);
    if occurrences <> 1 then
      raise exception '0045 demo creator call assertion failed';
    end if;
    if position(spaced in ddl)>0 then
      ddl := replace(ddl,spaced,
        'public.settlement_demo_create_merchant_settlement(p_merchant_id, r.company_id, r.period_from, r.period_to)');
    else
      ddl := replace(ddl,compact,
        'public.settlement_demo_create_merchant_settlement(p_merchant_id,r.company_id,r.period_from,r.period_to)');
    end if;
  end if;
  execute ddl;
end $isolate_demo_create$;

-- Existing read-model RPC signatures stay PostgREST-compatible. Their source is
-- rewritten to the fail-closed views without duplicating the large audited SQL.
do $isolate_read_models$
declare ddl text; original text; signature regprocedure; pair text[]; source_count int; qualified_source text;
begin
  foreach pair slice 1 in array array[
    array['public.company_monthly_usage(uuid,uuid,text)','public.meal_transactions','public.normal_meal_transactions'],
    array['public.company_monthly_usage(uuid,uuid,text)','public.settlements','public.normal_settlements'],
    array['public.merchant_ledger_summary(uuid,uuid,date,date)','from meal_transactions','from public.normal_meal_transactions'],
    array['public.merchant_transaction_count(uuid)','from meal_transactions where','from public.normal_meal_transactions where'],
    array['public.company_settlement_month_summary(uuid,text)','public.settlements','public.normal_settlements']
  ] loop
    signature := pair[1]::regprocedure;
    original := pg_get_functiondef(signature);
    if position(pair[3] in original)>0 then continue; end if;
    source_count := (length(original)-length(replace(original,pair[2],'')))/length(pair[2]);
    if source_count < 1 and position('from meal_transactions' in pair[2])=1 then
      qualified_source := replace(pair[2],'from meal_transactions','from public.meal_transactions');
      source_count := (length(original)-length(replace(original,qualified_source,'')))/length(qualified_source);
      if source_count > 0 then pair[2] := qualified_source; end if;
    end if;
    if source_count < 1 then raise exception '0045 read model exact source assertion failed: %',pair[1]; end if;
    ddl := replace(original,pair[2],pair[3]);
    if position(pair[2] in ddl)>0 or position(pair[3] in ddl)=0 then
      raise exception '0045 read model exact rewrite failed: %',pair[1];
    end if;
    execute ddl;
  end loop;
end $isolate_read_models$;

notify pgrst,'reload schema';
commit;
