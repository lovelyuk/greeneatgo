-- Customer-owned LOCAL stop only. Apply after 0064 and additive manual 0065.
-- Never certifies external cancellation, never resets the one-shot guard.
begin;
create table public.payment_order_local_abandonments (
 id uuid primary key default gen_random_uuid(),
 order_id uuid not null unique references public.payment_orders(id),
 user_id uuid not null references public.app_users(id),
 amount integer not null check(amount>0),
 source text not null default 'owner_request' check(source='owner_request'),
 scope text not null default 'local_order' check(scope='local_order'),
 outcome text not null default 'abandoned' check(outcome='abandoned'),
 requested_by uuid not null references public.app_users(id),
 requested_at timestamptz not null default clock_timestamp(),
 acknowledge_provider_uncertainty boolean not null check(acknowledge_provider_uncertainty),
 provider_finality text not null default 'unknown' check(provider_finality='unknown'),
 residual_late_approval_possible boolean not null default true check(residual_late_approval_possible),
 check(requested_by=user_id)
);
create trigger payment_local_abandonment_immutable before update or delete on public.payment_order_local_abandonments
 for each row execute function public.reject_payment_review_mutation();
alter table public.payment_order_local_abandonments enable row level security;
revoke all on public.payment_order_local_abandonments from public,anon,authenticated,service_role;
grant select on public.payment_order_local_abandonments to service_role;
-- A local receipt must never be relabeled a verified closure by an old producer.
create function public.reject_local_abandonment_as_closure() returns trigger
language plpgsql set search_path=pg_catalog,public as $$
begin
 if exists(select 1 from public.payment_order_local_abandonments where order_id=new.order_id)
 then raise exception 'LOCAL_ABANDONMENT_NOT_VERIFIED_CLOSURE'; end if;
 return new;
end $$;
create trigger payment_closure_not_local before insert on public.payment_order_closures
 for each row execute function public.reject_local_abandonment_as_closure();
revoke all on function public.reject_local_abandonment_as_closure() from public,anon,authenticated,service_role;

create function public.abandon_owned_payment_order(
 p_order_id text,p_user_id uuid,p_amount integer,p_acknowledge_provider_uncertainty boolean)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare o public.payment_orders%rowtype; u public.app_users%rowtype; uc public.user_coupons%rowtype;
 r public.payment_order_local_abandonments%rowtype; other_reserved bigint; contradiction boolean;
begin
 if p_acknowledge_provider_uncertainty is distinct from true then raise exception 'EXPLICIT_UNCERTAINTY_CONSENT_REQUIRED'; end if;
 select * into o from public.payment_orders where order_id=p_order_id and user_id=p_user_id for update;
 if not found then raise exception 'ORDER_NOT_FOUND'; end if;
 if p_amount is distinct from o.amount or p_amount<=0 then raise exception 'AMOUNT_MISMATCH'; end if;
 -- Repeat API owner authorization inside the service-only transaction.
 select * into u from public.app_users where id=o.user_id;
 if not found or u.status<>'active' or u.role not in ('customer','employee') then raise exception 'OWNER_NOT_ELIGIBLE'; end if;
 select * into r from public.payment_order_local_abandonments where order_id=o.id;
 if not found then
   if o.status<>'ready' or o.pay_type not in ('direct','voucher','subsidized')
     or o.provider_payment_key is not null or o.approved_at is not null or o.fulfilled_at is not null
     or exists(select 1 from public.vouchers where order_id=o.id)
     or exists(select 1 from public.refund_requests where order_id=o.id)
     or exists(select 1 from public.point_transactions where related_order_id=o.id)
     or exists(select 1 from public.coupon_redemptions where order_id=o.id)
     or exists(select 1 from public.payment_notification_inbox where order_id=o.id)
     or exists(select 1 from public.payment_order_closures where order_id=o.id)
     or exists(select 1 from public.payment_callback_discrepancies where order_id=o.id and kind<>'nonapproval')
   then raise exception 'ORDER_HAS_PAYMENT_OR_RESOURCE_HISTORY'; end if;
   -- Same lock ordering as existing approval/finalization: order, coupon, wallet.
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
   insert into public.payment_order_local_abandonments(order_id,user_id,amount,requested_by,acknowledge_provider_uncertainty)
     values(o.id,o.user_id,o.amount,p_user_id,true) returning * into r;
   -- Preserve started_at and legacy NULL epoch; neither proves provider finality.
   update public.payment_orders set checkout_revoked_at=coalesce(checkout_revoked_at,clock_timestamp()) where id=o.id;
   if o.point_reserved then update public.app_users set point_reserved=point_reserved-o.point_amount where id=o.user_id; end if;
   if o.user_coupon_id is not null and uc.status='reserved' then
     update public.user_coupons set status=case when valid_until is not null and valid_until<=now() then 'expired' else 'available' end,
       reserved_order_id=null,reserved_at=null,updated_at=clock_timestamp()
       where id=uc.id and reserved_order_id=o.id and status='reserved';
   end if;
   update public.payment_orders set status='canceled',point_reserved=false,updated_at=clock_timestamp() where id=o.id;
   o.status:='canceled';
 end if;
 contradiction:=o.status<>'canceled' or o.provider_payment_key is not null or o.approved_at is not null or o.fulfilled_at is not null
   or exists(select 1 from public.payment_callback_discrepancies where order_id=o.id and kind<>'nonapproval')
   or exists(select 1 from public.payment_notification_inbox where order_id=o.id);
 return jsonb_build_object('order_id',o.order_id,'user_id',o.user_id,'amount',o.amount,'status',o.status,
   'recovery_action',case when contradiction then 'reconcile' else 'locally_abandoned' end,
   'resumable',false,'checkout_url',null,'completion',null,
   'local_abandonment',jsonb_build_object('id',r.id,'source',r.source,'scope',r.scope,'outcome',r.outcome,
     'requested_by',r.requested_by,'requested_at',r.requested_at,'provider_finality',r.provider_finality,
     'residual_late_approval_possible',r.residual_late_approval_possible));
end $$;
revoke all on function public.abandon_owned_payment_order(text,uuid,integer,boolean) from public,anon,authenticated;
grant execute on function public.abandon_owned_payment_order(text,uuid,integer,boolean) to service_role;
-- Existing 0060 consumes the issued coupon on status=done, then erroneously
-- consumes it again when normal fulfillment sets fulfilled_at. Make only that
-- exact same-order already-consumed transition idempotent; foreign use fails.
create or replace function public.enforce_user_coupon_order_lifecycle() returns trigger
language plpgsql security definer set search_path=pg_catalog,public as $$
declare uc public.user_coupons%rowtype;
begin
 if new.user_coupon_id is null then return new; end if;
 select * into uc from public.user_coupons where id=new.user_coupon_id for update;
 if not found then raise exception 'USER_COUPON_INVALID' using errcode='P0001'; end if;
 if (old.fulfilled_at is null and new.fulfilled_at is not null) or (old.status<>'done' and new.status='done') then
   if uc.status='used' and uc.used_order_id=new.id and uc.user_id=new.user_id
     and uc.merchant_id=new.merchant_id and uc.coupon_id=new.coupon_id
     and (old.status='done' or old.fulfilled_at is not null)
   then return new; end if;
   if uc.status<>'reserved' or uc.reserved_order_id is distinct from new.id
     or uc.user_id is distinct from new.user_id or uc.merchant_id is distinct from new.merchant_id
     or uc.coupon_id is distinct from new.coupon_id or uc.used_order_id is not null
     or (uc.valid_until is not null and uc.valid_until<=now())
   then raise exception 'USER_COUPON_CONSUME_CONFLICT' using errcode='P0001'; end if;
   update public.user_coupons set status='used',reserved_order_id=null,reserved_at=null,
     used_order_id=new.id,used_at=coalesce(new.fulfilled_at,now()) where id=uc.id;
 elsif old.status='ready' and new.status in ('failed','canceled') and uc.status='reserved' and uc.reserved_order_id=new.id then
   update public.user_coupons set status=case when valid_until is not null and valid_until<=now() then 'expired' else 'available' end,
     reserved_order_id=null,reserved_at=null where id=uc.id;
 end if;
 return new;
end $$;
revoke all on function public.enforce_user_coupon_order_lifecycle() from public,anon,authenticated,service_role;

-- 0064 notification wrapper already locks this same order and durably quarantines
-- canceled-order approvals (including additional DAOUTRX), with no issue/refund.
notify pgrst,'reload schema';
commit;
