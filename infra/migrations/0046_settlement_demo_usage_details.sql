begin;

-- Preserve the audited state implementation as a private base exactly once.
-- The public signature remains unchanged so stale API deployments continue to
-- pass the enriched RPC JSON through without a new endpoint.
do $preserve_demo_state$
begin
  if to_regprocedure('public.settlement_demo_state_base(uuid,uuid)') is null then
    alter function public.settlement_demo_state(uuid,uuid)
      rename to settlement_demo_state_base;
  end if;
end $preserve_demo_state$;

alter function public.settlement_demo_state_base(uuid,uuid) volatile;
revoke all on function public.settlement_demo_state_base(uuid,uuid)
  from public,anon,authenticated,service_role;

create or replace function public.settlement_demo_state(p_actor_id uuid,p_merchant_id uuid)
returns jsonb language plpgsql volatile security definer set search_path=pg_catalog,public as $$
declare
  result jsonb;
  current_run public.settlement_demo_runs%rowtype;
  details jsonb := '[]'::jsonb;
begin
  -- Actor authorization, options, integrity validation and aggregate state stay
  -- centralized in the preserved implementation.
  result := public.settlement_demo_state_base(p_actor_id,p_merchant_id);

  select * into current_run
  from public.settlement_demo_runs
  where merchant_id=p_merchant_id and is_current;

  if found then
    select coalesce(jsonb_agg(jsonb_build_object(
      'display_sequence', item.display_sequence,
      'user_label', '시연 사용자 ' || item.user_sequence::text,
      -- Deliberately synthetic: do not reveal the underlying transaction time.
      'used_at', ((current_run.period_from + (item.display_sequence-1))::timestamp
                    + time '12:00') at time zone 'Asia/Seoul',
      'description', '시연 식대',
      'kind', item.kind,
      'supply_amount', item.signed_supply,
      'vat_amount', item.signed_vat,
      'total_amount', item.signed_total
    ) order by item.display_sequence),'[]'::jsonb)
    into details
    from (
      select row_number() over(order by t.id)::int as display_sequence,
        dense_rank() over(order by t.user_id)::int as user_sequence,
        t.kind,
        case when t.kind='spend' then t.settlement_supply_amount else -t.settlement_supply_amount end as signed_supply,
        case when t.kind='spend' then t.settlement_vat_amount else -t.settlement_vat_amount end as signed_vat,
        case when t.kind='spend' then t.settlement_total_amount else -t.settlement_total_amount end as signed_total
      from public.settlement_demo_transactions dt
      join public.meal_transactions t on t.id=dt.transaction_id
      where dt.run_id=current_run.id
    ) item;
  end if;

  return result || jsonb_build_object('transactions',details);
end $$;

revoke all on function public.settlement_demo_state(uuid,uuid)
  from public,anon,authenticated;
grant execute on function public.settlement_demo_state(uuid,uuid) to service_role;

-- The idempotent reset shortcut constructs its empty response directly rather
-- than returning state(), so it must explicitly carry the same empty list.
create or replace function public.settlement_demo_reset(
 p_actor_id uuid,p_merchant_id uuid,p_idempotency_key text)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare r public.settlement_demo_runs%rowtype; s public.settlements%rowtype; old_id uuid; removable boolean:=false;
begin
 perform public.settlement_demo_assert_actor(p_actor_id,p_merchant_id);
 if p_idempotency_key is not null and length(p_idempotency_key) not between 1 and 200 then raise exception 'SETTLEMENT_INPUT_INVALID' using errcode='P0001'; end if;
 perform pg_advisory_xact_lock(hashtextextended('settlement-demo:'||p_merchant_id::text,0));
 if p_idempotency_key is not null and exists(select 1 from public.settlement_demo_reset_requests
      where merchant_id=p_merchant_id and idempotency_key=p_idempotency_key) then
   return jsonb_build_object('seeded',false,'stage','empty','options',
     public.settlement_demo_state(p_actor_id,p_merchant_id)->'options','transactions','[]'::jsonb); end if;
 select * into r from public.settlement_demo_runs where merchant_id=p_merchant_id and is_current for update;
 if found then
   old_id:=r.id; perform public.settlement_demo_validate_run(r.id);
   if r.settlement_id is null then removable:=true;
   else
     select * into s from public.settlements where id=r.settlement_id
       and merchant_id=r.merchant_id and company_id=r.company_id for update;
     removable:=found and s.settlement_status='draft' and s.tax_invoice_status='not_requested'
       and not exists(select 1 from public.tax_invoices where settlement_id=s.id)
       and not exists(select 1 from public.settlement_events where settlement_id=s.id)
       and not exists(select 1 from public.settlement_payments where settlement_id=s.id);
   end if;
   if removable then
     if r.settlement_id is not null then
       update public.settlement_demo_runs set settlement_id=null where id=r.id;
       delete from public.settlements where id=r.settlement_id and merchant_id=r.merchant_id and company_id=r.company_id;
     end if;
     delete from public.meal_transactions t using public.settlement_demo_transactions dt
       where dt.run_id=r.id and dt.transaction_id=t.id and t.merchant_id=r.merchant_id and t.company_id=r.company_id
         and t.flags->>'run_id'=r.id::text and t.flags->>'settlement_demo'='true';
     delete from public.settlement_demo_runs where id=r.id;
   else
     update public.settlement_demo_runs set is_current=false,archived_at=clock_timestamp() where id=r.id;
   end if;
 end if;
 if p_idempotency_key is not null then
   insert into public.settlement_demo_reset_requests(merchant_id,idempotency_key,reset_run_id)
   values(p_merchant_id,p_idempotency_key,old_id);
 end if;
 return public.settlement_demo_state(p_actor_id,p_merchant_id);
end $$;

revoke all on function public.settlement_demo_reset(uuid,uuid,text)
  from public,anon,authenticated;
grant execute on function public.settlement_demo_reset(uuid,uuid,text) to service_role;

notify pgrst, 'reload schema';

commit;
