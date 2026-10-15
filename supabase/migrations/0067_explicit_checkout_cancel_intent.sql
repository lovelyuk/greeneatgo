-- Add explicit cancel and unknown normal-return local-stop authorizations.
-- Neither mode fabricates warning consent or certifies provider finality.
-- Depends only on deployed 0066. Never provider cancellation/refund authority.
begin;
alter table public.payment_order_local_abandonments
 add column explicit_checkout_cancel_intent boolean not null default false,
 add column checkout_return_ended text check (checkout_return_ended in ('sdk_frame_fail','mobile_fail')),
 alter column acknowledge_provider_uncertainty drop not null;
-- Existing CHECK(acknowledge_provider_uncertainty) still rejects false, permits
-- NULL only for the new explicit intent under this additional exact-mode check.
alter table public.payment_order_local_abandonments
 add constraint payment_local_stop_authorization_exactly_one check (
  (acknowledge_provider_uncertainty is true and not explicit_checkout_cancel_intent and checkout_return_ended is null)
  or (acknowledge_provider_uncertainty is null and explicit_checkout_cancel_intent and checkout_return_ended is null)
  or (acknowledge_provider_uncertainty is null and not explicit_checkout_cancel_intent and checkout_return_ended is not null));

create function public.abandon_owned_payment_order_intent(
 p_order_id text,p_user_id uuid,p_amount integer,p_acknowledge_provider_uncertainty boolean,
 p_explicit_checkout_cancel_intent boolean,p_checkout_return_ended text default null)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare o public.payment_orders%rowtype; u public.app_users%rowtype; uc public.user_coupons%rowtype;
 r public.payment_order_local_abandonments%rowtype; other_reserved bigint; contradiction boolean;
begin
 if not ((p_acknowledge_provider_uncertainty is true and p_explicit_checkout_cancel_intent is false and p_checkout_return_ended is null)
         or (p_acknowledge_provider_uncertainty is null and p_explicit_checkout_cancel_intent is true and p_checkout_return_ended is null)
         or (p_acknowledge_provider_uncertainty is null and p_explicit_checkout_cancel_intent is false and p_checkout_return_ended is not null and p_checkout_return_ended in ('sdk_frame_fail','mobile_fail')))
 then raise exception 'EXPLICIT_LOCAL_AUTHORIZATION_REQUIRED'; end if;
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
   insert into public.payment_order_local_abandonments(order_id,user_id,amount,requested_by,acknowledge_provider_uncertainty,explicit_checkout_cancel_intent,checkout_return_ended)
     values(o.id,o.user_id,o.amount,p_user_id,p_acknowledge_provider_uncertainty,p_explicit_checkout_cancel_intent,p_checkout_return_ended) returning * into r;
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
revoke all on function public.abandon_owned_payment_order_intent(text,uuid,integer,boolean,boolean,text) from public,anon,authenticated;
grant execute on function public.abandon_owned_payment_order_intent(text,uuid,integer,boolean,boolean,text) to service_role;
-- Preserve the old signature and its ACL for old API/native callers; shared
-- core retains order/coupon/wallet lock ordering, receipts and late quarantine.
create or replace function public.abandon_owned_payment_order(
 p_order_id text,p_user_id uuid,p_amount integer,p_acknowledge_provider_uncertainty boolean)
returns jsonb language sql security definer set search_path=pg_catalog,public as $$
 select public.abandon_owned_payment_order_intent(
  p_order_id,p_user_id,p_amount,p_acknowledge_provider_uncertainty,false)
$$;
revoke all on function public.abandon_owned_payment_order(text,uuid,integer,boolean) from public,anon,authenticated;
grant execute on function public.abandon_owned_payment_order(text,uuid,integer,boolean) to service_role;
notify pgrst,'reload schema';
commit;
