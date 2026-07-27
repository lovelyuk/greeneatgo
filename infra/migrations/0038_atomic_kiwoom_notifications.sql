-- Authoritative Kiwoom result notifications and settlement resend cycles.
-- A validated result callback is persisted and fulfilled in one database transaction.

create or replace function public.prevent_unaudited_notification_release() returns trigger
language plpgsql set search_path=pg_catalog,public as $$
begin
 if (new.review_status,new.processed_at,new.processed_by) is distinct from
    (old.review_status,old.processed_at,old.processed_by) then
  if old.review_status<>'pending' or new.review_status<>'released'
    or new.processed_at is null or new.processed_by is null
    or not exists (
      select 1 from public.payment_orders o
      where o.id=new.order_id and o.merchant_id=new.merchant_id
        and o.status='done' and not o.tax_review_required
        and o.tax_type in ('taxable','tax_free')
    )
  then raise exception 'COMPLETED_NOTIFICATION_REQUIRED' using errcode='P0001'; end if;
 end if;
 return new;
end $$;
revoke all on function public.prevent_unaudited_notification_release() from public,anon,authenticated,service_role;

-- The operator-selected completion path from migration 0036 is retired. Legacy
-- pending notifications can only continue through the authoritative callback RPC.
do $retire_legacy_notification_paths$
begin
 if pg_catalog.to_regprocedure('public.release_legacy_tax_review(uuid,uuid,uuid,text,text)') is not null then
  revoke all on function public.release_legacy_tax_review(uuid,uuid,uuid,text,text)
   from public,anon,authenticated,service_role;
 end if;
 if pg_catalog.to_regprocedure('public.enqueue_legacy_payment_notification(uuid,text,text,integer,text,text,jsonb,inet)') is not null then
  revoke all on function public.enqueue_legacy_payment_notification(uuid,text,text,integer,text,text,jsonb,inet)
   from public,anon,authenticated,service_role;
 end if;
end $retire_legacy_notification_paths$;
drop function if exists public.release_legacy_tax_review(uuid,uuid,uuid,text,text);
drop function if exists public.enqueue_legacy_payment_notification(uuid,text,text,integer,text,text,jsonb,inet);

create or replace function public.complete_kiwoom_payment_notification(
 p_order_id uuid,p_provider_order_id text,p_cpid text,p_amount int,p_payment_method text,
 p_provider_transaction_id text,p_payload jsonb,p_source_ip inet)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare
 o public.payment_orders%rowtype;
 n public.payment_notification_inbox%rowtype;
 v_tax_type text;
 v_tax_source text;
 v_result jsonb;
 v_now timestamptz:=pg_catalog.clock_timestamp();
 v_approved_at timestamptz;
begin
 if nullif(pg_catalog.btrim(p_provider_order_id),'') is null
   or nullif(pg_catalog.btrim(p_cpid),'') is null
   or p_amount is null or p_amount<=0
   or nullif(pg_catalog.btrim(p_payment_method),'') is null
   or nullif(pg_catalog.btrim(p_provider_transaction_id),'') is null
   or p_payload is null or p_source_ip is null
 then raise exception 'NOTIFICATION_INPUT_INVALID' using errcode='P0001'; end if;

 select * into o from public.payment_orders where id=p_order_id for update;
 if not found then raise exception 'ORDER_NOT_FOUND' using errcode='P0001'; end if;
 if p_provider_order_id is distinct from o.order_id or p_amount is distinct from o.amount
 then raise exception 'NOTIFICATION_IDENTITY_MISMATCH' using errcode='P0001'; end if;
 if coalesce(o.requested_payment_method,'TOTAL')='BANK' and p_payment_method<>'BANK'
 then raise exception 'PAYMENT_METHOD_MISMATCH' using errcode='P0001'; end if;

 -- The order lock serializes callbacks for one order, and the inbox row is also
 -- locked explicitly when resuming rows created by the former enqueue RPC.
 select * into n from public.payment_notification_inbox where order_id=o.id for update;
 if found then
  -- Older enqueue callers did not consistently duplicate source_ip inside the
  -- JSON payload. Treat that redundant key as normalized metadata only after
  -- proving that, when present, it exactly matches the immutable inet column.
  if n.merchant_id is distinct from o.merchant_id
    or n.provider_transaction_id is distinct from p_provider_transaction_id
    or n.provider_order_id is distinct from p_provider_order_id
    or n.cpid is distinct from p_cpid or n.amount is distinct from p_amount
    or n.payment_method is distinct from p_payment_method
    or n.source_ip is distinct from p_source_ip
    or ((n.normalized_payload ? 'source_ip') and
        n.normalized_payload->>'source_ip' is distinct from pg_catalog.host(n.source_ip))
    or ((p_payload ? 'source_ip') and
        p_payload->>'source_ip' is distinct from pg_catalog.host(p_source_ip))
    or (n.normalized_payload-'source_ip') is distinct from (p_payload-'source_ip')
  then raise exception 'NOTIFICATION_IDEMPOTENCY_CONFLICT' using errcode='P0001'; end if;
  if n.review_status='released' and o.status='done' then
   return jsonb_build_object('order_id',o.order_id,'status','done','duplicate',true,
     'provider_transaction_id',n.provider_transaction_id,'tax_type',o.tax_type);
  end if;
  if n.review_status<>'pending' or o.status<>'ready'
  then raise exception 'NOTIFICATION_INCOMPLETE' using errcode='P0001'; end if;
 else
  if exists(select 1 from public.payment_notification_inbox x
            where x.provider_transaction_id=p_provider_transaction_id and x.order_id<>o.id)
  then raise exception 'NOTIFICATION_IDEMPOTENCY_CONFLICT' using errcode='P0001'; end if;
  if o.status<>'ready' then raise exception 'ORDER_NOT_FULFILLABLE' using errcode='P0001'; end if;
  insert into public.payment_notification_inbox(order_id,merchant_id,provider_transaction_id,
   provider_order_id,cpid,amount,payment_method,normalized_payload,source_ip)
  values(o.id,o.merchant_id,p_provider_transaction_id,p_provider_order_id,p_cpid,p_amount,
   p_payment_method,p_payload,p_source_ip) returning * into n;
 end if;
 if o.provider_payment_key is not null and o.provider_payment_key<>p_provider_transaction_id
 then raise exception 'PAYMENT_KEY_MISMATCH' using errcode='P0001'; end if;
 v_approved_at:=n.received_at;

 if o.tax_review_required then
  if o.tax_type<>'unclassified' then raise exception 'INVALID_TAX_REVIEW_STATE' using errcode='P0001'; end if;
  if o.pay_type in ('voucher','subsidized') and o.voucher_product_id is not null then
   select vp.tax_type into v_tax_type from public.voucher_products vp
    where vp.id=o.voucher_product_id and vp.merchant_id=o.merchant_id;
   v_tax_source:='voucher_product:'||o.voucher_product_id::text;
  elsif o.pay_type='direct' and o.product_id is not null then
   select mp.tax_type into v_tax_type from public.merchant_products mp
    where mp.id=o.product_id and mp.merchant_id=o.merchant_id;
   v_tax_source:='merchant_product:'||o.product_id::text;
  elsif o.pay_type='subsidized' and o.voucher_product_id is null and o.company_id is not null
    and o.voucher_count=1 and o.paid_voucher_count=1 and o.bonus_voucher_count=0 then
   select mc.tax_type into v_tax_type from public.merchant_companies mc
    where mc.company_id=o.company_id and mc.merchant_id=o.merchant_id and mc.status='active';
   v_tax_source:='merchant_company:'||o.company_id::text||':'||o.merchant_id::text;
  end if;
  if v_tax_type not in ('taxable','tax_free')
  then raise exception 'TAX_TYPE_UNCLASSIFIED' using errcode='P0001'; end if;
  insert into public.tax_classification_audit(
    merchant_id,order_id,inbox_id,actor_id,previous_tax_type,selected_tax_type,reason,transaction_xid)
  values(o.merchant_id,o.id,n.id,o.user_id,'unclassified',v_tax_type,
    'Authoritative server-owned classification: '||v_tax_source,pg_catalog.txid_current());
  update public.payment_orders set tax_type=v_tax_type,tax_review_required=false where id=o.id
   returning * into o;
 elsif o.tax_type not in ('taxable','tax_free') then
  raise exception 'TAX_TYPE_UNCLASSIFIED' using errcode='P0001';
 end if;

 if o.pay_type='voucher' then
  v_result:=public.fulfill_voucher_order(o.id,p_provider_transaction_id,p_payment_method,p_payload,v_approved_at);
 elsif o.pay_type='subsidized' then
  v_result:=public.fulfill_subsidized_order(o.id,p_provider_transaction_id,p_payment_method,p_payload,v_approved_at);
 elsif o.pay_type='direct' then
  update public.payment_orders set status='done',provider_payment_key=p_provider_transaction_id,
    payment_method=p_payment_method,provider_response=p_payload,approved_at=v_approved_at,updated_at=v_now
   where id=o.id and status='ready' returning * into o;
  if not found then raise exception 'ORDER_NOT_FULFILLABLE' using errcode='P0001'; end if;
  v_result:=jsonb_build_object('order_id',o.order_id,'status','done','tax_type',o.tax_type);
 else
  raise exception 'ORDER_PAY_TYPE_INVALID' using errcode='P0001';
 end if;

 update public.payment_notification_inbox set review_status='released',processed_at=v_now,
   processed_by=o.user_id where id=n.id returning * into n;
 return v_result||jsonb_build_object('duplicate',false,
   'provider_transaction_id',n.provider_transaction_id,'inbox_id',n.id);
end $$;
revoke all on function public.complete_kiwoom_payment_notification(uuid,text,text,int,text,text,jsonb,inet)
 from public,anon,authenticated;
grant execute on function public.complete_kiwoom_payment_notification(uuid,text,text,int,text,text,jsonb,inet)
 to service_role;

-- Every real draft/revision send gets a distinct deterministic cycle key. Calling
-- while already sent remains an idempotent read and does not create a new cycle.
create or replace function public.merchant_send_settlement(
 p_actor_id uuid,p_merchant_id uuid,p_settlement_id uuid
) returns jsonb language plpgsql security definer
set search_path=pg_catalog,public as $$
declare s public.settlements%rowtype; e public.settlement_events%rowtype; v_cycle int; v_now timestamptz:=pg_catalog.clock_timestamp();
begin
 if not exists(select 1 from public.app_users u where u.id=p_actor_id and u.merchant_id=p_merchant_id and u.role='merchant_admin' and u.status='active')
 then raise exception 'SETTLEMENT_FORBIDDEN' using errcode='P0001'; end if;
 select * into s from public.settlements where id=p_settlement_id and merchant_id=p_merchant_id for update;
 if not found then raise exception 'SETTLEMENT_NOT_FOUND' using errcode='P0001'; end if;
 if s.settlement_status='sent' then return jsonb_build_object('settlement',to_jsonb(s),'idempotent',true); end if;
 if s.settlement_status not in ('draft','revising') then raise exception 'SETTLEMENT_STATE_CONFLICT' using errcode='P0001'; end if;
 if s.due_date is null or s.supply_amount is null or s.vat_amount is null or s.total_amount is null
   or s.supply_amount<0 or s.vat_amount<0 or s.supply_amount+s.vat_amount<>s.total_amount
 then raise exception 'SETTLEMENT_AMOUNTS_INVALID' using errcode='P0001'; end if;
 select count(*)+1 into v_cycle from public.settlement_events
  where settlement_id=s.id and event_type='merchant_sent';
 update public.settlements set settlement_status='sent',sent_at=v_now,updated_at=v_now
  where id=s.id returning * into s;
 insert into public.settlement_events(settlement_id,company_id,merchant_id,event_type,payload,idempotency_key,actor_id)
 values(s.id,s.company_id,s.merchant_id,'merchant_sent',
   jsonb_build_object('due_date',s.due_date,'total_amount',s.total_amount,'send_cycle',v_cycle),
   'send-cycle-'||v_cycle::text,p_actor_id) returning * into e;
 return jsonb_build_object('settlement',to_jsonb(s),'event',to_jsonb(e),'idempotent',false);
end $$;
revoke all on function public.merchant_send_settlement(uuid,uuid,uuid) from public,anon,authenticated;
grant execute on function public.merchant_send_settlement(uuid,uuid,uuid) to service_role;

create or replace function public.company_settlement_month_summary(p_company_id uuid,p_period_ym text)
returns jsonb language sql stable security definer set search_path=pg_catalog,public as $$
 select jsonb_build_object(
  'settlement_count',count(*),
  'paid_count',count(*) filter(where s.payment_status in ('paid','overpaid') or s.status='paid'),
  'tx_count',coalesce(sum(s.tx_count),0),
  'total_amount',coalesce(sum(s.total_amount),0)
 ) from public.settlements s
 where s.company_id=p_company_id and s.period_ym=p_period_ym
$$;
revoke all on function public.company_settlement_month_summary(uuid,text) from public,anon,authenticated;
grant execute on function public.company_settlement_month_summary(uuid,text) to service_role;

-- Harden nested definer execution without changing the committed migration that
-- originally defined the exact-money fulfillment routines.
alter function public.fulfill_voucher_order(uuid,text,text,jsonb,timestamptz)
 set search_path=pg_catalog,public;
alter function public.fulfill_subsidized_order(uuid,text,text,jsonb,timestamptz)
 set search_path=pg_catalog,public;

notify pgrst,'reload schema';
