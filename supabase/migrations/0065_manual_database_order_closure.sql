-- Additive administrative adjudication; NOT provider irreversible finality.
-- Run explicitly after 0064. Existing application review producer is unchanged.
begin;
alter table public.payment_order_reviews alter column actor_id drop not null;
alter table public.payment_order_reviews add column actor_kind text not null default 'application_platform_admin';
alter table public.payment_order_reviews add column actor_session_user text;
alter table public.payment_order_reviews add column actor_current_user text;
alter table public.payment_order_reviews add constraint payment_review_actor_identity check (
 (actor_kind='application_platform_admin' and actor_id is not null
  and actor_session_user is null and actor_current_user is null)
 or (actor_kind='manual_database_operator' and actor_id is null
  and actor_session_user is not null and actor_session_user='postgres'
  and actor_current_user is not null and actor_current_user='postgres'
  and evidence->>'authority' is not null and evidence->>'authority'='manual_database_operator'
  and evidence->'complete_attempt_coverage' is not null and evidence->'complete_attempt_coverage'='false'::jsonb
  and evidence->'irreversible_no_future_approval' is not null and evidence->'irreversible_no_future_approval'='false'::jsonb
  and evidence->'residual_late_approval_possible' is not null and evidence->'residual_late_approval_possible'='true'::jsonb)
);
-- Bind closure to the exact immutable review identity, not merely any review UUID.
alter table public.payment_order_reviews add constraint payment_review_closure_identity
 unique(id,order_id,user_id,amount,evidence_sha256);
alter table public.payment_order_closures add constraint payment_closure_review_identity
 foreign key(review_id,order_id,user_id,amount,evidence_sha256)
 references public.payment_order_reviews(id,order_id,user_id,amount,evidence_sha256);
create function public.manual_close_failed_payment_order(
 p_order_id uuid,p_evidence jsonb,p_evidence_sha256 text,p_canonical_evidence text,
 p_dry_run boolean default true)
returns jsonb language plpgsql security invoker set search_path=pg_catalog,public as $$
declare o public.payment_orders%rowtype; u public.app_users%rowtype; uc public.user_coupons%rowtype;
 r public.payment_order_reviews%rowtype; c public.payment_order_closures%rowtype;
 other_reserved bigint; outcome text; observed_discrepancies jsonb;
begin
 -- Check BOTH identities: SECURITY INVOKER must never launder a service session.
 if session_user<>'postgres' or current_user<>'postgres' then raise exception 'MANUAL_CLOSURE_FORBIDDEN'; end if;
 select * into o from public.payment_orders where id=p_order_id for update;
 if not found then raise exception 'ORDER_NOT_FOUND'; end if;
 if p_evidence is null or p_canonical_evidence is null or p_evidence_sha256 is null
   or p_evidence_sha256 !~ '^[a-f0-9]{64}$'
   or p_canonical_evidence::jsonb is distinct from p_evidence
   or encode(sha256(convert_to(p_canonical_evidence,'UTF8')),'hex')<>p_evidence_sha256
   or p_evidence->>'order_id' is distinct from o.id::text
   or p_evidence->>'user_id' is distinct from o.user_id::text
   or p_evidence->'amount' is distinct from to_jsonb(o.amount)
   or p_evidence ? 'actor_id' or p_evidence ? 'actor_session_user' or p_evidence ? 'actor_current_user'
   or jsonb_typeof(p_evidence) is distinct from 'object'
   or (p_evidence - array['authority','outcome','order_id','user_id','amount','source_sha256',
       'source_reference','user_authorization_reference','complete_attempt_coverage',
       'irreversible_no_future_approval','residual_late_approval_possible','attempt',
       'observed','observed_discrepancies']::text[]) <> '{}'::jsonb
   or p_evidence->>'authority' is distinct from 'manual_database_operator'
   or p_evidence->>'outcome' is distinct from 'failed'
   or p_evidence->'complete_attempt_coverage' is distinct from 'false'::jsonb
   or p_evidence->'irreversible_no_future_approval' is distinct from 'false'::jsonb
   or p_evidence->'residual_late_approval_possible' is distinct from 'true'::jsonb
   or coalesce(p_evidence->>'source_sha256','') !~ '^[a-f0-9]{64}$'
   or length(btrim(coalesce(p_evidence->>'source_reference','')))<12
   or length(btrim(coalesce(p_evidence->>'user_authorization_reference','')))<12
   or jsonb_typeof(p_evidence->'attempt') is distinct from 'object'
   or p_evidence->'attempt'->>'outcome' is distinct from 'failed'
   or length(btrim(coalesce(p_evidence->'attempt'->>'transaction_id','')))=0
   or jsonb_typeof(p_evidence->'attempt'->'code') is distinct from 'string'
   or length(btrim(coalesce(p_evidence->'attempt'->>'code','')))=0
   or p_evidence->'attempt'->>'code'='0000'
   or length(btrim(coalesce(p_evidence->'attempt'->>'reference','')))<12
   or coalesce(p_evidence->'attempt'->>'occurred_at','') !~ '^\d{4}-\d{2}-\d{2}T.*(Z|[+-]\d{2}:\d{2})$'
 then raise exception 'MANUAL_EVIDENCE_INVALID'; end if;
 -- Timestamp must parse; failed-source evidence is observation, not finality.
 perform (p_evidence->'attempt'->>'occurred_at')::timestamptz;
 outcome:='failed';
 select coalesce(jsonb_agg(jsonb_build_object('id',d.id,'kind',d.kind,'cpid',d.cpid,
   'transaction_id',d.transaction_id,'amount',d.amount,'payment_method',d.payment_method,
   'received_at',d.received_at,'fingerprint',d.fingerprint,'code',d.payload->>'RESULTCODE') order by d.id),'[]'::jsonb)
 into observed_discrepancies from public.payment_callback_discrepancies d where d.order_id=o.id;
 select * into c from public.payment_order_closures where order_id=o.id;
 if found then
   select * into r from public.payment_order_reviews where id=c.review_id;
   if c.evidence_sha256<>p_evidence_sha256 or r.actor_kind<>'manual_database_operator'
     or r.canonical_evidence<>p_canonical_evidence or r.order_id<>o.id
     or r.user_id<>o.user_id or r.amount<>o.amount
   then raise exception 'CLOSURE_EVIDENCE_CONFLICT'; end if;
   if observed_discrepancies is distinct from p_evidence->'observed_discrepancies' then
     return jsonb_build_object('closed',false,'closure_id',c.id,'duplicate',true,'reconciliation_required',true,'recovery_action','reconcile');
   end if;
   return jsonb_build_object('closed',true,'closure_id',c.id,'review_id',r.id,'duplicate',true,'recovery_action','closed');
 end if;
 -- Entire exact observed order identity/status/guards/resources; token never included.
 if p_evidence->'observed' is distinct from (to_jsonb(o)-'checkout_token')
 then raise exception 'MANUAL_EVIDENCE_STALE'; end if;
 if o.status not in ('ready','failed','canceled') or o.amount<=0
   or o.provider_payment_key is not null or o.approved_at is not null or o.fulfilled_at is not null
   or exists(select 1 from public.vouchers where order_id=o.id)
   or exists(select 1 from public.refund_requests where order_id=o.id)
   or exists(select 1 from public.point_transactions where related_order_id=o.id)
   or exists(select 1 from public.coupon_redemptions where order_id=o.id)
   or exists(select 1 from public.payment_notification_inbox where order_id=o.id)
 then raise exception 'ORDER_HAS_PAYMENT_OR_RESOURCE_HISTORY'; end if;
 if p_evidence->'observed_discrepancies' is distinct from observed_discrepancies
   or exists(select 1 from public.payment_callback_discrepancies d where d.order_id=o.id
     and (d.kind<>'nonapproval' or d.amount<>o.amount
       or d.transaction_id is distinct from p_evidence->'attempt'->>'transaction_id'
       or d.cpid is distinct from p_evidence->'attempt'->>'cpid'
       or d.payment_method is distinct from p_evidence->'attempt'->>'payment_method'
       or d.payload->>'RESULTCODE' is distinct from p_evidence->'attempt'->>'code'))
 then raise exception 'MANUAL_DISCREPANCY_CONFLICT'; end if;
 -- Lock the actual issued-coupon instance, never mutate the reusable catalog.
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
 -- Lock the wallet even on dry-run; fail rather than steal another order's reservation.
 select * into u from public.app_users where id=o.user_id for update;
 if not found then raise exception 'ORDER_OWNER_NOT_FOUND'; end if;
 if o.point_reserved then
   select coalesce(sum(point_amount),0) into other_reserved from public.payment_orders
    where user_id=o.user_id and id<>o.id and point_reserved;
   if o.pay_type<>'subsidized' or o.company_id is distinct from u.company_id
     or o.point_amount<=0 or u.point_balance<u.point_reserved
     or u.point_reserved<o.point_amount+other_reserved
   then raise exception 'RESERVATION_OWNERSHIP_CONFLICT'; end if;
 end if;
 if coalesce(p_dry_run,true) then
   return jsonb_build_object('closed',false,'eligible',true,'dry_run',true,'recovery_action','reconcile');
 end if;
 insert into public.payment_order_reviews(order_id,user_id,amount,actor_id,actor_kind,actor_session_user,actor_current_user,
   evidence_sha256,evidence,canonical_evidence)
 values(o.id,o.user_id,o.amount,null,'manual_database_operator',session_user,current_user,
   p_evidence_sha256,p_evidence,p_canonical_evidence) returning * into r;
 update public.payment_orders set checkout_revoked_at=coalesce(checkout_revoked_at,clock_timestamp()) where id=o.id;
 if o.point_reserved then
   update public.app_users set point_reserved=point_reserved-o.point_amount where id=o.user_id;
 end if;
 if o.user_coupon_id is not null and uc.status='reserved' then
   update public.user_coupons set status=case when valid_until is not null and valid_until<=now() then 'expired' else 'available' end,
     reserved_order_id=null,reserved_at=null,updated_at=clock_timestamp()
   where id=uc.id and reserved_order_id=o.id and status='reserved';
 end if;
 update public.payment_orders set status=outcome,point_reserved=false,updated_at=clock_timestamp() where id=o.id;
 insert into public.payment_order_closures(order_id,user_id,amount,review_id,evidence_sha256,outcome)
 values(o.id,o.user_id,o.amount,r.id,p_evidence_sha256,outcome) returning * into c;
 return jsonb_build_object('closed',true,'eligible',true,'closure_id',c.id,'review_id',r.id,'recovery_action','closed');
end $$;
revoke all on function public.manual_close_failed_payment_order(uuid,jsonb,text,text,boolean)
 from public,anon,authenticated,service_role;
-- No API/RPC grants; only direct postgres session + current postgres role.
notify pgrst,'reload schema';
commit;
