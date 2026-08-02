begin;

drop trigger if exists trg_user_coupon_order_lifecycle on public.payment_orders;
drop function if exists public.enforce_user_coupon_order_lifecycle();
drop function if exists public.reserve_user_coupon(uuid,uuid,uuid,uuid);
drop function if exists public.grant_banner_reward(uuid,uuid,uuid,timestamptz);
drop function if exists public.save_partner_banner(uuid,uuid,uuid,jsonb,jsonb);
drop function if exists public.reorder_partner_banners(uuid,uuid,jsonb);
drop view if exists public.v_banner_stats_daily;
drop view if exists public.partner_banner_stats;
drop trigger if exists trg_partners_updated_at on public.partners;
drop trigger if exists trg_partner_banners_updated_at on public.partner_banners;
drop trigger if exists trg_banner_rewards_updated_at on public.banner_rewards;
drop trigger if exists trg_user_coupons_updated_at on public.user_coupons;
drop function if exists public.partner_banner_touch_updated_at();
alter table if exists public.user_coupons drop constraint if exists user_coupons_reward_grant_fk;
alter table if exists public.banner_reward_grants drop constraint if exists banner_reward_grants_user_coupon_id_fkey;

-- Restore 0059's immutable snapshot trigger before dropping user_coupon_id.
create or replace function public.prevent_payment_pricing_snapshot_change() returns trigger
language plpgsql set search_path=pg_catalog,public as $$
begin
 if (new.gross_amount,new.coupon_id,new.coupon_discount_amount,new.coupon_snapshot,new.requested_point_amount)
    is distinct from
    (old.gross_amount,old.coupon_id,old.coupon_discount_amount,old.coupon_snapshot,old.requested_point_amount)
 then raise exception 'PAYMENT_PRICING_SNAPSHOT_IMMUTABLE' using errcode='P0001'; end if;
 return new;
end $$;
drop trigger if exists trg_payment_order_pricing_immutable on public.payment_orders;
create trigger trg_payment_order_pricing_immutable
 before update of gross_amount,coupon_id,coupon_discount_amount,coupon_snapshot,requested_point_amount
 on public.payment_orders for each row execute function public.prevent_payment_pricing_snapshot_change();

alter table public.payment_orders drop column if exists user_coupon_id;
alter table public.point_transactions drop column if exists related_banner_id;
alter table public.merchant_coupons drop column if exists is_public;
drop table if exists public.banner_reward_grants;
drop table if exists public.banner_events;
drop table if exists public.user_coupons;
drop table if exists public.banner_rewards;
drop table if exists public.partner_banners;
drop table if exists public.partners;
alter table public.merchant_coupons drop constraint if exists merchant_coupons_id_merchant_unique;
do $$ begin
 if to_regclass('storage.objects') is not null then
  execute 'delete from storage.objects where bucket_id=''partner-banners''';
 end if;
end $$;
delete from storage.buckets where id='partner-banners';
notify pgrst,'reload schema';
commit;
