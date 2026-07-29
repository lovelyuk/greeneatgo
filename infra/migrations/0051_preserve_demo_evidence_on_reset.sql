begin;

-- Demo usage is intentionally eligible for ordinary settlements during
-- development. Once an ordinary settlement snapshots a demo period, resetting
-- the dedicated demo must preserve the source transactions used as its visible
-- evidence. The period guards in settlement_demo_seed already prevent reusing
-- a month that contains a settlement or qualifying transaction.
create or replace function public.settlement_demo_reset(
 p_actor_id uuid,p_merchant_id uuid,p_idempotency_key text)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare
  r public.settlement_demo_runs%rowtype;
  s public.settlements%rowtype;
  old_id uuid;
  removable boolean:=false;
  demo_settlement_found boolean:=false;
  ordinary_reference boolean:=false;
begin
 perform public.settlement_demo_assert_actor(p_actor_id,p_merchant_id);
 if p_idempotency_key is not null and length(p_idempotency_key) not between 1 and 200 then
   raise exception 'SETTLEMENT_INPUT_INVALID' using errcode='P0001';
 end if;
 perform pg_advisory_xact_lock(hashtextextended('settlement-demo:'||p_merchant_id::text,0));
 if p_idempotency_key is not null and exists(
      select 1 from public.settlement_demo_reset_requests
      where merchant_id=p_merchant_id and idempotency_key=p_idempotency_key
 ) then
   return jsonb_build_object(
     'seeded',false,'stage','empty','options',
     public.settlement_demo_state(p_actor_id,p_merchant_id)->'options',
     'transactions','[]'::jsonb
   );
 end if;

 select * into r from public.settlement_demo_runs
 where merchant_id=p_merchant_id and is_current for update;
 if found then
   old_id:=r.id;
   perform public.settlement_demo_validate_run(r.id);
   -- Serialize the existence check and possible deletion with ordinary
   -- settlement creation for this exact merchant/company/period.
   perform pg_advisory_xact_lock(
     pg_catalog.hashtext(r.merchant_id::text),
     pg_catalog.hashtext(r.company_id::text||':'||r.period_ym)
   );

   select exists(
     select 1 from public.settlements ordinary
     where ordinary.merchant_id=r.merchant_id
       and ordinary.company_id=r.company_id
       and ordinary.period_ym=r.period_ym
       and not ordinary.is_demo
   ) into ordinary_reference;

   if r.settlement_id is null then
     removable:=not ordinary_reference;
   else
     select * into s from public.settlements
     where id=r.settlement_id
       and merchant_id=r.merchant_id
       and company_id=r.company_id
       and is_demo
     for update;
     demo_settlement_found:=found;
     removable:=demo_settlement_found
       and not ordinary_reference
       and s.settlement_status='draft'
       and s.tax_invoice_status='not_requested'
       and not exists(select 1 from public.tax_invoices where settlement_id=s.id)
       and not exists(select 1 from public.settlement_events where settlement_id=s.id)
       and not exists(select 1 from public.settlement_payments where settlement_id=s.id);
   end if;

   if removable then
     if r.settlement_id is not null then
       update public.settlement_demo_runs set settlement_id=null where id=r.id;
       delete from public.settlements
       where id=r.settlement_id and merchant_id=r.merchant_id
         and company_id=r.company_id and is_demo;
     end if;
     delete from public.meal_transactions t using public.settlement_demo_transactions dt
       where dt.run_id=r.id and dt.transaction_id=t.id
         and t.merchant_id=r.merchant_id and t.company_id=r.company_id
         and t.flags->>'run_id'=r.id::text
         and t.flags->>'settlement_demo'='true';
     delete from public.settlement_demo_runs where id=r.id;
   else
     update public.settlement_demo_runs
     set is_current=false,archived_at=clock_timestamp()
     where id=r.id;
   end if;
 end if;

 if p_idempotency_key is not null then
   insert into public.settlement_demo_reset_requests(
     merchant_id,idempotency_key,reset_run_id
   ) values(p_merchant_id,p_idempotency_key,old_id);
 end if;
 return public.settlement_demo_state(p_actor_id,p_merchant_id);
end $$;

revoke all on function public.settlement_demo_reset(uuid,uuid,text)
  from public,anon,authenticated;
grant execute on function public.settlement_demo_reset(uuid,uuid,text)
  to service_role;

notify pgrst,'reload schema';
commit;
