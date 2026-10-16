-- Separate audited operator LOCAL stop. Not a failed-provider-attempt closure,
-- owner consent, provider cancellation, refund, or no-future-charge guarantee.
-- Dependencies: deployed 0064 (locks/quarantine/immutability), 0066, 0067.
begin;
create table public.payment_order_operator_local_stops (
 id uuid primary key default gen_random_uuid(),
 order_id uuid not null unique references public.payment_orders(id),
 user_id uuid not null references public.app_users(id),
 amount integer not null check(amount>0),
 source text not null default 'manual_database_operator' check(source='manual_database_operator'),
 scope text not null default 'local_order' check(scope='local_order'),
 outcome text not null default 'abandoned' check(outcome='abandoned'),
 reason text not null default 'manual_local_stop_unknown_provider' check(reason='manual_local_stop_unknown_provider'),
 actor_kind text not null check(actor_kind='database_operator'),
 actor_session_user text not null check(actor_session_user='postgres'),
 actor_current_user text not null check(actor_current_user='postgres'),
 requested_at timestamptz not null default clock_timestamp(),
 provider_finality text not null default 'unknown' check(provider_finality='unknown'),
 residual_late_approval_possible boolean not null default true check(residual_late_approval_possible),
 evidence jsonb not null,
 canonical_evidence text not null,
 evidence_sha256 text not null check(evidence_sha256 ~ '^[a-f0-9]{64}$'),
 check(canonical_evidence::jsonb=evidence),
 check(encode(sha256(convert_to(canonical_evidence,'UTF8')),'hex')=evidence_sha256),
 check(evidence->>'authority' is not null and evidence->>'authority'='local_stop_adjudication'),
 check(evidence->>'order_id' is not null and evidence->>'order_id'=order_id::text),
 check(evidence->>'user_id' is not null and evidence->>'user_id'=user_id::text),
 check(evidence->'amount' is not null and evidence->'amount'=to_jsonb(amount))
);
create trigger payment_operator_local_stop_immutable before update or delete on public.payment_order_operator_local_stops
 for each row execute function public.reject_payment_review_mutation();
alter table public.payment_order_operator_local_stops enable row level security;
revoke all on public.payment_order_operator_local_stops from public,anon,authenticated,service_role;
grant select on public.payment_order_operator_local_stops to service_role;

create or replace function public.reject_local_abandonment_as_closure() returns trigger
language plpgsql set search_path=pg_catalog,public as $$
begin
 if exists(select 1 from public.payment_order_local_abandonments where order_id=new.order_id)
 or exists(select 1 from public.payment_order_operator_local_stops where order_id=new.order_id)
 then raise exception 'LOCAL_ABANDONMENT_NOT_VERIFIED_CLOSURE'; end if;
 return new;
end $$;
revoke all on function public.reject_local_abandonment_as_closure() from public,anon,authenticated,service_role;

create function public.operator_stop_payment_order(
 p_order_id uuid,p_evidence jsonb,p_evidence_sha256 text,p_canonical_evidence text,
 p_dry_run boolean default true)
returns jsonb language plpgsql security invoker set search_path=pg_catalog,public as $$
declare o public.payment_orders%rowtype; u public.app_users%rowtype; uc public.user_coupons%rowtype;
 r public.payment_order_operator_local_stops%rowtype; other_reserved bigint; observed_discrepancies jsonb;
 contradiction boolean;
begin
 -- Capture actual invoker identities, never a definer's or invented owner UUID.
 if session_user<>'postgres' or current_user<>'postgres' then raise exception 'OPERATOR_STOP_FORBIDDEN'; end if;
 select * into o from public.payment_orders where id=p_order_id for update;
 if not found then raise exception 'ORDER_NOT_FOUND'; end if;
 if p_evidence is null or p_canonical_evidence is null or p_evidence_sha256 is null
   or p_evidence_sha256 !~ '^[a-f0-9]{64}$'
   or p_canonical_evidence::jsonb is distinct from p_evidence
   or encode(sha256(convert_to(p_canonical_evidence,'UTF8')),'hex')<>p_evidence_sha256
   or jsonb_typeof(p_evidence) is distinct from 'object'
   or (p_evidence-array['authority','reason','order_id','merchant_order_id','user_id','amount',
       'source_sha256','authorization_reference','provider_finality','residual_late_approval_possible',
       'observed','observed_discrepancies']::text[])<>'{}'::jsonb
   or p_evidence->>'authority' is distinct from 'local_stop_adjudication'
   or p_evidence->>'reason' is distinct from 'manual_local_stop_unknown_provider'
   or p_evidence->>'order_id' is distinct from o.id::text
   or p_evidence->>'merchant_order_id' is distinct from o.order_id
   or p_evidence->>'user_id' is distinct from o.user_id::text
   or p_evidence->'amount' is distinct from to_jsonb(o.amount)
   or p_evidence->>'provider_finality' is distinct from 'unknown'
   or p_evidence->'residual_late_approval_possible' is distinct from 'true'::jsonb
   or coalesce(p_evidence->>'source_sha256','') !~ '^[a-f0-9]{64}$'
   or jsonb_typeof(p_evidence->'authorization_reference') is distinct from 'string'
   or length(btrim(coalesce(p_evidence->>'authorization_reference','')))<12
 then raise exception 'OPERATOR_EVIDENCE_INVALID'; end if;
 select coalesce(jsonb_agg(to_jsonb(d)-'payload' order by d.id),'[]'::jsonb)
 into observed_discrepancies from public.payment_callback_discrepancies d where d.order_id=o.id;
 select * into r from public.payment_order_operator_local_stops where order_id=o.id;
 if found then
   if r.evidence_sha256<>p_evidence_sha256 or r.canonical_evidence<>p_canonical_evidence
      or r.user_id<>o.user_id or r.amount<>o.amount
   then raise exception 'OPERATOR_EVIDENCE_CONFLICT'; end if;
   contradiction:=o.status<>'canceled' or o.provider_payment_key is not null or o.approved_at is not null or o.fulfilled_at is not null
     or exists(select 1 from public.payment_notification_inbox where order_id=o.id)
     or exists(select 1 from public.payment_callback_discrepancies where order_id=o.id and kind<>'nonapproval');
   return jsonb_build_object('stopped',not contradiction,'receipt_id',r.id,'duplicate',true,
     'recovery_action',case when contradiction then 'reconcile' else 'locally_abandoned' end);
 end if;
 if p_evidence->'observed' is distinct from (to_jsonb(o)-array['checkout_token','provider_response']::text[])
   or p_evidence->'observed_discrepancies' is distinct from observed_discrepancies
 then raise exception 'OPERATOR_EVIDENCE_STALE'; end if;
 if o.status<>'ready' or o.amount<=0 or o.pay_type not in ('direct','voucher','subsidized')
   or o.provider_payment_key is not null or o.provider_response is not null or o.approved_at is not null or o.fulfilled_at is not null
   or exists(select 1 from public.payment_order_reviews where order_id=o.id)
   or exists(select 1 from public.vouchers where order_id=o.id)
   or exists(select 1 from public.refund_requests where order_id=o.id)
   or exists(select 1 from public.point_transactions where related_order_id=o.id)
   or exists(select 1 from public.coupon_redemptions where order_id=o.id)
   or exists(select 1 from public.payment_notification_inbox where order_id=o.id)
   or exists(select 1 from public.payment_order_closures where order_id=o.id)
   or exists(select 1 from public.payment_order_local_abandonments where order_id=o.id)
   or exists(select 1 from public.payment_callback_discrepancies where order_id=o.id and kind<>'nonapproval')
 then raise exception 'ORDER_HAS_PAYMENT_OR_RESOURCE_HISTORY'; end if;
 -- Match existing producers' lock order: order, issued coupon, wallet.
 if exists(select 1 from public.user_coupons where (reserved_order_id=o.id or used_order_id=o.id)
           and id is distinct from o.user_coupon_id)
 then raise exception 'COUPON_RESERVATION_CONFLICT'; end if;
 if o.user_coupon_id is not null then
   select * into uc from public.user_coupons where id=o.user_coupon_id for update;
   if not found or uc.user_id is distinct from o.user_id or uc.merchant_id is distinct from o.merchant_id
     or uc.coupon_id is distinct from o.coupon_id or uc.status='used' or uc.used_order_id is not null
     or (uc.status='reserved' and uc.reserved_order_id is distinct from o.id)
   then raise exception 'COUPON_RESERVATION_CONFLICT'; end if;
 end if;
 select * into u from public.app_users where id=o.user_id for update;
 if not found or u.status<>'active' or u.role not in ('customer','employee') then raise exception 'OWNER_NOT_ELIGIBLE'; end if;
 if o.point_reserved then
   select coalesce(sum(point_amount),0) into other_reserved from public.payment_orders
     where user_id=o.user_id and id<>o.id and point_reserved;
   if o.pay_type<>'subsidized' or o.company_id is distinct from u.company_id
     or o.point_amount<=0 or u.point_balance<u.point_reserved
     or u.point_reserved<o.point_amount+other_reserved
   then raise exception 'RESERVATION_OWNERSHIP_CONFLICT'; end if;
 end if;
 if coalesce(p_dry_run,true) then
   return jsonb_build_object('stopped',false,'eligible',true,'dry_run',true,'recovery_action','reconcile');
 end if;
 insert into public.payment_order_operator_local_stops(order_id,user_id,amount,actor_kind,actor_session_user,actor_current_user,
   evidence,evidence_sha256,canonical_evidence)
 values(o.id,o.user_id,o.amount,'database_operator',session_user,current_user,p_evidence,p_evidence_sha256,p_canonical_evidence)
 returning * into r;
 update public.payment_orders set checkout_revoked_at=coalesce(checkout_revoked_at,clock_timestamp()) where id=o.id;
 if o.point_reserved then update public.app_users set point_reserved=point_reserved-o.point_amount where id=o.user_id; end if;
 if o.user_coupon_id is not null and uc.status='reserved' then
   update public.user_coupons set status=case when valid_until is not null and valid_until<=now() then 'expired' else 'available' end,
     reserved_order_id=null,reserved_at=null,updated_at=clock_timestamp()
     where id=uc.id and reserved_order_id=o.id and status='reserved';
 end if;
 update public.payment_orders set status='canceled',point_reserved=false,updated_at=clock_timestamp() where id=o.id;
 return jsonb_build_object('stopped',true,'eligible',true,'receipt_id',r.id,'recovery_action','locally_abandoned');
end $$;
revoke all on function public.operator_stop_payment_order(uuid,jsonb,text,text,boolean) from public,anon,authenticated,service_role;
-- No API producer grants. Existing 0065 and owner consent routes stay strict.
-- 0064 canceled-order notification quarantine preserves late/second approvals.
notify pgrst,'reload schema';
commit;
