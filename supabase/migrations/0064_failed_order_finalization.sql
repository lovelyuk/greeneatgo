-- Apply AFTER infra/migrations/0063, before routing checkout to the new guard.
-- Existing orders deliberately retain NULL guard epoch: missing legacy markers
-- never certify that no form was issued. No provider contract is invented here.
begin;
alter table public.payment_orders add column if not exists checkout_guard_epoch timestamptz;
alter table public.payment_orders alter column checkout_guard_epoch set default now();
alter table public.payment_orders add column if not exists checkout_revoked_at timestamptz;

create table if not exists public.payment_order_reviews (
 id uuid primary key default gen_random_uuid(),
 order_id uuid not null references public.payment_orders(id),
 user_id uuid not null references public.app_users(id),
 amount integer not null check(amount>0),
 actor_id uuid not null references public.app_users(id),
 evidence_sha256 text not null check(evidence_sha256 ~ '^[a-f0-9]{64}$'),
 evidence jsonb not null,
 canonical_evidence text not null,
 reviewed_at timestamptz not null default clock_timestamp(),
 unique(order_id,evidence_sha256),
 check(canonical_evidence::jsonb=evidence),
 check(encode(sha256(convert_to(canonical_evidence,'UTF8')),'hex')=evidence_sha256)
);
create table if not exists public.payment_order_closures (
 id uuid primary key default gen_random_uuid(),
 order_id uuid not null unique references public.payment_orders(id),
 user_id uuid not null references public.app_users(id),
 amount integer not null check(amount>0),
 review_id uuid not null unique references public.payment_order_reviews(id),
 evidence_sha256 text not null check(evidence_sha256 ~ '^[a-f0-9]{64}$'),
 outcome text not null check(outcome in ('failed','canceled')),
 closed_at timestamptz not null default clock_timestamp()
);
create or replace function public.reject_payment_review_mutation() returns trigger
language plpgsql set search_path=pg_catalog,public as $$
begin raise exception 'PAYMENT_REVIEW_IMMUTABLE'; end $$;
drop trigger if exists payment_review_immutable on public.payment_order_reviews;
create trigger payment_review_immutable before update or delete on public.payment_order_reviews
 for each row execute function public.reject_payment_review_mutation();
drop trigger if exists payment_closure_immutable on public.payment_order_closures;
create trigger payment_closure_immutable before update or delete on public.payment_order_closures
 for each row execute function public.reject_payment_review_mutation();
alter table public.payment_order_reviews enable row level security;
alter table public.payment_order_closures enable row level security;
revoke all on public.payment_order_reviews, public.payment_order_closures from public,anon,authenticated,service_role;
grant select on public.payment_order_reviews, public.payment_order_closures to service_role;

create or replace function public.review_failed_payment_order(
 p_actor_id uuid,p_order_id uuid,p_evidence jsonb,p_evidence_sha256 text,
 p_canonical_evidence text,p_dry_run boolean default true)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare o public.payment_orders%rowtype; u public.app_users%rowtype; uc public.user_coupons%rowtype;
 r public.payment_order_reviews%rowtype; c public.payment_order_closures%rowtype;
 eligible boolean:=false; other_reserved bigint; authority text; outcome text;
begin
 if not exists(select 1 from public.app_users where id=p_actor_id and role='platform_admin' and status='active')
 then raise exception 'FINALIZATION_FORBIDDEN'; end if;
 select * into o from public.payment_orders where id=p_order_id for update;
 if not found then raise exception 'ORDER_NOT_FOUND'; end if;
 if p_evidence is null or p_canonical_evidence is null or p_evidence_sha256 is null
   or p_evidence_sha256 !~ '^[a-f0-9]{64}$'
   or p_canonical_evidence::jsonb is distinct from p_evidence
   or encode(sha256(convert_to(p_canonical_evidence,'UTF8')),'hex')<>p_evidence_sha256
   or p_evidence->>'order_id' is distinct from o.id::text
   or p_evidence->>'actor_id' is distinct from p_actor_id::text
   or p_evidence->>'user_id' is distinct from o.user_id::text
   or (p_evidence->>'amount')::integer is distinct from o.amount
   or coalesce(p_evidence->>'source_sha256','') !~ '^[a-f0-9]{64}$'
   or length(btrim(coalesce(p_evidence->>'source_reference','')))<12
   or jsonb_typeof(p_evidence->'attempts') is distinct from 'array'
 then raise exception 'EVIDENCE_IDENTITY_INVALID'; end if;
 authority:=p_evidence->>'authority'; outcome:=p_evidence->>'outcome';
 if authority is null or authority not in ('attempt_only','no_issued_form','trusted_provider_irreversible_closure')
   or outcome is null or outcome not in ('failed','canceled')
 then raise exception 'EVIDENCE_AUTHORITY_INVALID'; end if;
 select * into c from public.payment_order_closures where order_id=o.id;
 if found then
   if c.evidence_sha256<>p_evidence_sha256 then raise exception 'CLOSURE_EVIDENCE_CONFLICT'; end if;
   if exists(select 1 from public.payment_callback_discrepancies where order_id=o.id and kind='late_approval') then
     return jsonb_build_object('closed',false,'closure_id',c.id,'duplicate',true,'reconciliation_required',true,'recovery_action','reconcile');
   end if;
   return jsonb_build_object('closed',true,'closure_id',c.id,'duplicate',true);
 end if;
 if o.status not in ('ready','failed','canceled') or o.amount<=0
   or o.provider_payment_key is not null or o.approved_at is not null or o.fulfilled_at is not null
   or exists(select 1 from public.vouchers where order_id=o.id)
   or exists(select 1 from public.refund_requests where order_id=o.id)
   or exists(select 1 from public.point_transactions where related_order_id=o.id)
   or exists(select 1 from public.coupon_redemptions where order_id=o.id)
   or exists(select 1 from public.payment_notification_inbox where order_id=o.id)
 then raise exception 'ORDER_HAS_PAYMENT_OR_RESOURCE_HISTORY'; end if;
 if authority='no_issued_form' then
   eligible:=o.checkout_guard_epoch is not null and o.checkout_started_at is null
     and jsonb_array_length(p_evidence->'attempts')=0
     and not exists(select 1 from public.payment_callback_discrepancies where order_id=o.id);
 elsif authority='trusted_provider_irreversible_closure' then
   eligible:=p_evidence->'complete_attempt_coverage'='true'::jsonb
     and p_evidence->'irreversible_no_future_approval'='true'::jsonb
     and length(btrim(coalesce(p_evidence->>'provider_closure_reference','')))>=12
     and not exists(select 1 from jsonb_array_elements(p_evidence->'attempts') a
       where a->>'outcome' is null or a->>'outcome' not in ('failed','canceled'))
     and not exists(select 1 from public.payment_callback_discrepancies d where d.order_id=o.id
       and (d.kind<>'nonapproval' or not exists(
         select 1 from jsonb_array_elements(p_evidence->'attempts') a where a->>'transaction_id'=d.transaction_id)));
 end if;
 eligible:=coalesce(eligible,false);
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
   return jsonb_build_object('closed',false,'eligible',eligible,'dry_run',true,'recovery_action','reconcile');
 end if;
 insert into public.payment_order_reviews(order_id,user_id,amount,actor_id,evidence_sha256,evidence,canonical_evidence)
 values(o.id,o.user_id,o.amount,p_actor_id,p_evidence_sha256,p_evidence,p_canonical_evidence)
 on conflict(order_id,evidence_sha256) do nothing;
 select * into r from public.payment_order_reviews where order_id=o.id and evidence_sha256=p_evidence_sha256;
 -- Revoke future local admission even when issued old forms remain unresolved.
 update public.payment_orders set checkout_revoked_at=coalesce(checkout_revoked_at,clock_timestamp()) where id=o.id;
 if not eligible then return jsonb_build_object('closed',false,'eligible',false,'review_id',r.id,'recovery_action','reconcile'); end if;
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
revoke all on function public.reject_payment_review_mutation() from public,anon,authenticated,service_role;
revoke all on function public.review_failed_payment_order(uuid,uuid,jsonb,text,text,boolean) from public,anon,authenticated;
grant execute on function public.review_failed_payment_order(uuid,uuid,jsonb,text,text,boolean) to service_role;
-- Every supported order type consumes one durable admission BEFORE a PG hash
-- request. Failed hash/network outcomes remain ambiguous and never reset it.
create or replace function public.admit_payment_checkout(p_order_id uuid)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare o public.payment_orders%rowtype;
begin
 select * into o from public.payment_orders where id=p_order_id for update;
 if not found or o.status<>'ready' or o.amount<=0 or o.checkout_guard_epoch is null or o.checkout_revoked_at is not null
   or o.checkout_started_at is not null or o.pay_type not in ('direct','voucher','subsidized')
   or o.tax_type not in ('taxable','tax_free')
 then raise exception 'CHECKOUT_NOT_ADMISSIBLE'; end if;
 update public.payment_orders set checkout_started_at=clock_timestamp(),updated_at=clock_timestamp() where id=o.id;
 return jsonb_build_object('admitted',true,'order_id',o.order_id);
end $$;
revoke all on function public.admit_payment_checkout(uuid) from public,anon,authenticated;
grant execute on function public.admit_payment_checkout(uuid) to service_role;
create or replace function public.assert_payment_checkout_active(p_order_id uuid)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare o public.payment_orders%rowtype;
begin
 select * into o from public.payment_orders where id=p_order_id for update;
 if not found or o.status<>'ready' or o.checkout_revoked_at is not null or o.checkout_started_at is null
 then raise exception 'CHECKOUT_NOT_ADMISSIBLE'; end if;
 return jsonb_build_object('active',true);
end $$;
revoke all on function public.assert_payment_checkout_active(uuid) from public,anon,authenticated;
grant execute on function public.assert_payment_checkout_active(uuid) to service_role;
-- Retire the repeatable marker; no other caller may bypass single admission.
create or replace function public.mark_subsidized_checkout_started(p_order_id uuid)
returns jsonb language sql security definer set search_path=pg_catalog,public as $$
 select public.admit_payment_checkout(p_order_id)
$$;

create table if not exists public.payment_callback_discrepancies (
 id uuid primary key default gen_random_uuid(),
 order_id uuid references public.payment_orders(id),
 cpid text not null,
 transaction_id text not null,
 amount integer not null check(amount>0),
 payment_method text not null,
 kind text not null,
 payload jsonb not null,
 source_ip inet not null,
 received_at timestamptz not null default clock_timestamp(),
 fingerprint text not null unique
);
create index if not exists payment_callback_discrepancies_order_kind on public.payment_callback_discrepancies(order_id,kind);
alter table public.payment_callback_discrepancies enable row level security;
revoke all on public.payment_callback_discrepancies from public,anon,authenticated,service_role;
grant select on public.payment_callback_discrepancies to service_role;
drop trigger if exists payment_discrepancy_immutable on public.payment_callback_discrepancies;
create trigger payment_discrepancy_immutable before update or delete on public.payment_callback_discrepancies
 for each row execute function public.reject_payment_review_mutation();
-- Keep the audited normal approval implementation intact, behind a wrapper
-- that durably quarantines real late/second transactions instead of losing them.
do $$ begin
 if to_regprocedure('public.complete_kiwoom_payment_notification_original(uuid,text,text,integer,text,text,jsonb,inet)') is null then
  alter function public.complete_kiwoom_payment_notification(uuid,text,text,integer,text,text,jsonb,inet)
   rename to complete_kiwoom_payment_notification_original;
 end if;
end $$;
revoke all on function public.complete_kiwoom_payment_notification_original(uuid,text,text,integer,text,text,jsonb,inet)
 from public,anon,authenticated,service_role;
create or replace function public.complete_kiwoom_payment_notification(
 p_order_id uuid,p_provider_order_id text,p_cpid text,p_amount int,p_payment_method text,
 p_provider_transaction_id text,p_payload jsonb,p_source_ip inet)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare o public.payment_orders%rowtype; k text; event_id uuid; v_fingerprint text;
begin
 if nullif(btrim(p_cpid),'') is null or nullif(btrim(p_provider_transaction_id),'') is null
   or nullif(btrim(p_payment_method),'') is null or p_payload is null or p_source_ip is null
   or p_amount is null or p_amount<=0
 then raise exception 'NOTIFICATION_INPUT_INVALID'; end if;
 select * into o from public.payment_orders where id=p_order_id for update;
 if not found then raise exception 'ORDER_NOT_FOUND'; end if;
 if o.order_id is distinct from p_provider_order_id or o.amount is distinct from p_amount
 then raise exception 'NOTIFICATION_IDENTITY_MISMATCH'; end if;
 if coalesce(o.requested_payment_method,'TOTAL')='BANK' and p_payment_method<>'BANK'
 then raise exception 'PAYMENT_METHOD_MISMATCH'; end if;
 if o.status not in ('ready','done') then k:='late_approval';
 elsif o.provider_payment_key is not null and o.provider_payment_key<>p_provider_transaction_id
   or exists(select 1 from public.payment_notification_inbox where order_id=o.id and provider_transaction_id<>p_provider_transaction_id)
 then k:='second_approval'; end if;
 if k is null then
   return public.complete_kiwoom_payment_notification_original(p_order_id,p_provider_order_id,p_cpid,p_amount,
     p_payment_method,p_provider_transaction_id,p_payload,p_source_ip);
 end if;
 v_fingerprint:=encode(sha256(convert_to(jsonb_build_array(o.id,p_cpid,p_provider_transaction_id,p_amount,p_payment_method,k)::text,'UTF8')),'hex');
 insert into public.payment_callback_discrepancies(order_id,cpid,transaction_id,amount,payment_method,kind,payload,source_ip,fingerprint)
 values(o.id,p_cpid,p_provider_transaction_id,p_amount,p_payment_method,k,p_payload,p_source_ip,v_fingerprint)
 on conflict(fingerprint) do nothing;
 select id into event_id from public.payment_callback_discrepancies where payment_callback_discrepancies.fingerprint=v_fingerprint;
 return jsonb_build_object('durable',true,'discrepancy_id',event_id,'reconciliation_required',true,'fulfilled',false);
end $$;
revoke all on function public.complete_kiwoom_payment_notification(uuid,text,text,int,text,text,jsonb,inet) from public,anon,authenticated;
grant execute on function public.complete_kiwoom_payment_notification(uuid,text,text,int,text,text,jsonb,inet) to service_role;
create or replace function public.record_kiwoom_nonapproval_notification(
 p_cpid text,p_provider_order_id text,p_provider_transaction_id text,p_amount integer,
 p_payment_method text,p_payload jsonb,p_source_ip inet)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare o public.payment_orders%rowtype; matched boolean:=false; v_fingerprint text; event_id uuid;
begin
 if nullif(btrim(p_cpid),'') is null or nullif(btrim(p_provider_transaction_id),'') is null
   or nullif(btrim(p_payment_method),'') is null or p_amount is null or p_amount<=0
   or p_source_ip is null or p_payload is null
   or not (p_payment_method like '%CANCEL' or (p_payload ? 'RESULTCODE' and p_payload->>'RESULTCODE'<>'0000'))
 then raise exception 'NONAPPROVAL_INPUT_INVALID'; end if;
 if nullif(p_provider_order_id,'') is not null then
   select * into o from public.payment_orders where order_id=p_provider_order_id for update;
 else
   -- BANK_CANCEL has no ORDERNO. Bind by original approved transaction + CPID
   -- from the authenticated inbox, never by a client-selected owner.
   select po.* into o from public.payment_orders po join public.payment_notification_inbox ni on ni.order_id=po.id
     where ni.cpid=p_cpid and ni.provider_transaction_id=p_provider_transaction_id for update of po;
 end if;
 if found then
   matched:=o.amount=p_amount and
     (coalesce(o.requested_payment_method,'TOTAL')<>'BANK' or p_payment_method in ('BANK','BANK_CANCEL'));
 end if;
 -- Persist mismatches/unmatched notifications too, but do not release or refund.
 v_fingerprint:=encode(sha256(convert_to(jsonb_build_array(p_cpid,p_provider_order_id,p_provider_transaction_id,
   p_amount,p_payment_method,p_payload-'source_ip')::text,'UTF8')),'hex');
 insert into public.payment_callback_discrepancies(order_id,cpid,transaction_id,amount,payment_method,kind,payload,source_ip,fingerprint)
 values(o.id,p_cpid,p_provider_transaction_id,p_amount,p_payment_method,
   case when matched then 'nonapproval' else 'unmatched_nonapproval' end,p_payload,p_source_ip,v_fingerprint)
 on conflict(fingerprint) do nothing;
 select id into event_id from public.payment_callback_discrepancies where fingerprint=v_fingerprint;
 return jsonb_build_object('durable',true,'discrepancy_id',event_id,'matched',matched,'reconciliation_required',true);
end $$;
revoke all on function public.record_kiwoom_nonapproval_notification(text,text,text,integer,text,jsonb,inet) from public,anon,authenticated;
grant execute on function public.record_kiwoom_nonapproval_notification(text,text,text,integer,text,jsonb,inet) to service_role;
-- Existing native pre-entry abandonment stays available only when the new
-- guard proves no potential form issuance. Legacy NULL and reviewed/revoked
-- orders must not be released by the old missing-marker sweeper.
do $$ declare definition text; begin
 definition:=pg_get_functiondef('public.expire_stale_subsidized_orders(uuid)'::regprocedure);
 if position('and checkout_guard_epoch is not null' in definition)=0 then
   if position('and checkout_started_at is null' in definition)=0 then raise exception 'EXPIRY_GUARD_SOURCE_CHANGED'; end if;
   execute replace(definition,'and checkout_started_at is null',
     'and checkout_started_at is null and checkout_guard_epoch is not null and checkout_revoked_at is null');
 end if;
end $$;
do $$ begin
 if to_regprocedure('public.release_subsidized_order_points_original(uuid,uuid)') is null then
   alter function public.release_subsidized_order_points(uuid,uuid) rename to release_subsidized_order_points_original;
 end if;
end $$;
revoke all on function public.release_subsidized_order_points_original(uuid,uuid) from public,anon,authenticated,service_role;
create or replace function public.release_subsidized_order_points(p_order_id uuid,p_user_id uuid)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare o public.payment_orders%rowtype;
begin
 select * into o from public.payment_orders where id=p_order_id and user_id=p_user_id for update;
 if not found then raise exception 'ORDER_NOT_FOUND'; end if;
 if o.checkout_guard_epoch is null or o.checkout_revoked_at is not null
 then raise exception 'CHECKOUT_RECONCILIATION_REQUIRED'; end if;
 return public.release_subsidized_order_points_original(p_order_id,p_user_id);
end $$;
revoke all on function public.release_subsidized_order_points(uuid,uuid) from public,anon,authenticated;
grant execute on function public.release_subsidized_order_points(uuid,uuid) to service_role;
notify pgrst,'reload schema';
commit;
