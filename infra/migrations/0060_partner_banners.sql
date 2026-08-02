begin;

-- Tenant-owned advertising partners and banners.
create table if not exists public.partners (
 id uuid primary key default gen_random_uuid(),
 merchant_id uuid not null references public.merchants(id) on delete cascade,
 name text not null check(char_length(btrim(name)) between 1 and 120),
 logo_url text check(logo_url is null or logo_url ~ '^https://'),
 site_url text not null check(site_url ~ '^https://'),
 contact_name text, contact_phone text, contact_email text, memo text,
 status text not null default 'active' check(status in ('active','paused','ended')),
 created_by uuid not null references public.app_users(id) on delete restrict,
 created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
 unique(merchant_id,name), unique(id,merchant_id)
);

create table if not exists public.partner_banners (
 id uuid primary key default gen_random_uuid(),
 merchant_id uuid not null references public.merchants(id) on delete cascade,
 partner_id uuid not null references public.partners(id) on delete restrict,
 title text not null check(char_length(btrim(title)) between 1 and 160),
 image_url text not null check(image_url ~ '^https://'),
 image_alt text not null default '',
 link_url text not null check(link_url ~ '^https://'),
 open_mode text not null default 'webview' check(open_mode in ('webview','external')),
 placement text not null default 'home_bottom' check(placement in ('home_bottom','event_page')),
 starts_at timestamptz, ends_at timestamptz,
 is_active boolean not null default true,
 sort_order integer not null default 0,
 created_by uuid not null references public.app_users(id) on delete restrict,
 created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
 check(ends_at is null or starts_at is null or ends_at>starts_at),
 unique(id,merchant_id)
);
create index if not exists idx_partner_banners_live on public.partner_banners(merchant_id,placement,is_active,sort_order,id);
alter table public.partner_banners drop constraint if exists partner_banners_partner_tenant_fk;
alter table public.partner_banners add constraint partner_banners_partner_tenant_fk
 foreign key(partner_id,merchant_id) references public.partners(id,merchant_id) on delete cascade;

create table if not exists public.banner_rewards (
 id uuid primary key default gen_random_uuid(),
 banner_id uuid not null unique references public.partner_banners(id) on delete cascade,
 merchant_id uuid not null references public.merchants(id) on delete cascade,
 reward_type text not null check(reward_type in ('none','point','coupon')),
 point_amount bigint,
 coupon_id uuid references public.merchant_coupons(id) on delete restrict,
 grant_policy text not null default 'once' check(grant_policy in ('once','daily','unlimited')),
 per_user_limit integer check(per_user_limit is null or per_user_limit>0),
 total_budget bigint check(total_budget is null or total_budget>=0),
 granted_total bigint not null default 0 check(granted_total>=0),
 coupon_valid_days integer check(coupon_valid_days is null or coupon_valid_days between 1 and 3650),
 is_active boolean not null default true,
 created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
 check((reward_type='none' and point_amount is null and coupon_id is null) or
       (reward_type='point' and point_amount>0 and coupon_id is null) or
       (reward_type='coupon' and coupon_id is not null and point_amount is null)),
 check(total_budget is null or granted_total<=total_budget),
 check(grant_policy='unlimited' or per_user_limit is null),
 unique(id,merchant_id)
);
create index if not exists idx_banner_rewards_banner_merchant on public.banner_rewards(banner_id,merchant_id);
alter table public.banner_rewards drop constraint if exists banner_rewards_banner_tenant_fk;
alter table public.banner_rewards add constraint banner_rewards_banner_tenant_fk
 foreign key(banner_id,merchant_id) references public.partner_banners(id,merchant_id) on delete cascade;

create table if not exists public.user_coupons (
 id uuid primary key default gen_random_uuid(),
 user_id uuid not null references public.app_users(id) on delete restrict,
 merchant_id uuid not null references public.merchants(id) on delete restrict,
 coupon_id uuid not null references public.merchant_coupons(id) on delete restrict,
 reward_grant_id uuid,
 coupon_snapshot jsonb not null check(jsonb_typeof(coupon_snapshot)='object'),
 valid_from timestamptz not null default now(), valid_until timestamptz,
 status text not null default 'available' check(status in ('available','reserved','used','expired')),
 reserved_order_id uuid unique references public.payment_orders(id) on delete restrict,
 reserved_at timestamptz, used_order_id uuid unique references public.payment_orders(id) on delete restrict,
 used_at timestamptz, created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
 check(valid_until is null or valid_until>valid_from),
 check((status='available' and reserved_order_id is null and used_order_id is null) or
       (status='reserved' and reserved_order_id is not null and reserved_at is not null and used_order_id is null) or
       (status='used' and reserved_order_id is null and used_order_id is not null and used_at is not null) or
       (status='expired' and reserved_order_id is null and used_order_id is null))
);
do $$ begin
 if not exists(select 1 from pg_constraint where conrelid='public.merchant_coupons'::regclass and conname='merchant_coupons_id_merchant_unique') then
  alter table public.merchant_coupons add constraint merchant_coupons_id_merchant_unique unique(id,merchant_id);
 end if;
end $$;
alter table public.user_coupons drop constraint if exists user_coupons_catalog_tenant_fk;
alter table public.user_coupons add constraint user_coupons_catalog_tenant_fk
 foreign key(coupon_id,merchant_id) references public.merchant_coupons(id,merchant_id) on delete restrict;
create index if not exists idx_user_coupons_wallet on public.user_coupons(user_id,merchant_id,status,valid_until,created_at desc);

create table if not exists public.banner_events (
 id uuid primary key,
 banner_id uuid not null references public.partner_banners(id) on delete cascade,
 merchant_id uuid not null references public.merchants(id) on delete cascade,
 user_id uuid references public.app_users(id) on delete set null,
 event_type text not null check(event_type in ('impression','click')),
 occurred_at timestamptz not null default clock_timestamp(),
 created_at timestamptz not null default now()
);
create index if not exists idx_banner_events_stats on public.banner_events(merchant_id,banner_id,occurred_at desc);

create table if not exists public.banner_reward_grants (
 id uuid primary key default gen_random_uuid(),
 event_id uuid not null unique references public.banner_events(id) on delete cascade,
 reward_id uuid not null references public.banner_rewards(id) on delete cascade,
 banner_id uuid not null references public.partner_banners(id) on delete cascade,
 merchant_id uuid not null references public.merchants(id) on delete restrict,
 user_id uuid not null references public.app_users(id) on delete restrict,
 policy_key text not null,
 units bigint not null check(units>0),
 reward_type text not null check(reward_type in ('point','coupon')),
 point_transaction_id uuid unique references public.point_transactions(id) on delete restrict,
 user_coupon_id uuid unique references public.user_coupons(id) on delete restrict,
 granted_at timestamptz not null default clock_timestamp(),
 unique(reward_id,user_id,policy_key),
 check((reward_type='point' and point_transaction_id is not null and user_coupon_id is null) or
       (reward_type='coupon' and user_coupon_id is not null and point_transaction_id is null))
);
create index if not exists idx_banner_grants_stats on public.banner_reward_grants(merchant_id,banner_id,granted_at desc);
alter table public.banner_reward_grants drop constraint if exists banner_reward_grants_event_id_fkey;
alter table public.banner_reward_grants drop constraint if exists banner_reward_grants_reward_id_fkey;
alter table public.banner_reward_grants drop constraint if exists banner_reward_grants_banner_id_fkey;
alter table public.banner_reward_grants add constraint banner_reward_grants_event_id_fkey foreign key(event_id) references public.banner_events(id) on delete cascade;
alter table public.banner_reward_grants add constraint banner_reward_grants_reward_id_fkey foreign key(reward_id) references public.banner_rewards(id) on delete cascade;
alter table public.banner_reward_grants add constraint banner_reward_grants_banner_id_fkey foreign key(banner_id) references public.partner_banners(id) on delete cascade;
alter table public.user_coupons drop constraint if exists user_coupons_reward_grant_fk;
alter table public.user_coupons add constraint user_coupons_reward_grant_fk foreign key(reward_grant_id) references public.banner_reward_grants(id) on delete set null deferrable initially deferred;

-- Keep the originating UUID as immutable audit evidence even after a forced
-- banner deletion.  A foreign key with ON DELETE SET NULL would issue an
-- UPDATE against the append-only point ledger and is therefore incompatible
-- with reject_point_transaction_mutation().
alter table public.point_transactions add column if not exists related_banner_id uuid;
alter table public.point_transactions drop constraint if exists point_transactions_related_banner_id_fkey;
comment on column public.point_transactions.related_banner_id is 'Immutable originating banner UUID; intentionally retained without a foreign key after forced banner deletion.';
alter table public.merchant_coupons add column if not exists is_public boolean not null default true;
comment on column public.merchant_coupons.is_public is 'Public catalog visibility; false coupons are exposed only through an issued user_coupons instance.';
alter table public.payment_orders add column if not exists user_coupon_id uuid references public.user_coupons(id) on delete restrict;
create index if not exists idx_payment_orders_user_coupon on public.payment_orders(user_coupon_id) where user_coupon_id is not null;

-- Make the issued-instance choice part of the immutable pricing snapshot.
create or replace function public.prevent_payment_pricing_snapshot_change() returns trigger
language plpgsql set search_path=pg_catalog,public as $$
begin
 if (new.gross_amount,new.coupon_id,new.user_coupon_id,new.coupon_discount_amount,new.coupon_snapshot,new.requested_point_amount)
    is distinct from
    (old.gross_amount,old.coupon_id,old.user_coupon_id,old.coupon_discount_amount,old.coupon_snapshot,old.requested_point_amount)
 then raise exception 'PAYMENT_PRICING_SNAPSHOT_IMMUTABLE' using errcode='P0001'; end if;
 return new;
end $$;
drop trigger if exists trg_payment_order_pricing_immutable on public.payment_orders;
create trigger trg_payment_order_pricing_immutable before update of gross_amount,coupon_id,user_coupon_id,coupon_discount_amount,coupon_snapshot,requested_point_amount
 on public.payment_orders for each row execute function public.prevent_payment_pricing_snapshot_change();

create or replace function public.partner_banner_touch_updated_at() returns trigger
language plpgsql set search_path=pg_catalog,public as $$ begin new.updated_at=now(); return new; end $$;
revoke all on function public.partner_banner_touch_updated_at() from public,anon,authenticated,service_role;
do $$ declare t text; begin foreach t in array array['partners','partner_banners','banner_rewards','user_coupons'] loop
 execute format('drop trigger if exists trg_%I_updated_at on public.%I',t,t);
 execute format('create trigger trg_%I_updated_at before update on public.%I for each row execute function public.partner_banner_touch_updated_at()',t,t);
end loop; end $$;

-- Atomically save a banner and its reward. The API has already authenticated the
-- actor; this function independently revalidates merchant authority and ownership.
create or replace function public.save_partner_banner(p_actor_id uuid,p_merchant_id uuid,p_banner_id uuid,p_values jsonb,p_reward jsonb)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare a public.app_users%rowtype; b public.partner_banners%rowtype; r public.banner_rewards%rowtype; c public.merchant_coupons%rowtype; pid uuid;
begin
 select * into a from public.app_users where id=p_actor_id and role='merchant_admin' and status='active';
 if not found or not (a.merchant_id=p_merchant_id or (a.merchant_id is null and exists(select 1 from public.merchant_admins ma where ma.user_id=a.id and ma.merchant_id=p_merchant_id)))
 then raise exception 'FORBIDDEN' using errcode='P0001'; end if;
 pid=(p_values->>'partner_id')::uuid;
 if not exists(select 1 from public.partners where id=pid and merchant_id=p_merchant_id) then raise exception 'PARTNER_NOT_FOUND' using errcode='P0001'; end if;
 if coalesce(p_reward->>'reward_type','none')='coupon' then
  select * into c from public.merchant_coupons where id=(p_reward->>'coupon_id')::uuid and merchant_id=p_merchant_id and is_active for share;
  if not found then raise exception 'COUPON_NOT_ISSUABLE' using errcode='P0001'; end if;
 end if;
 if p_banner_id is null then
  insert into public.partner_banners(merchant_id,partner_id,title,image_url,image_alt,link_url,open_mode,placement,starts_at,ends_at,is_active,sort_order,created_by)
  values(p_merchant_id,pid,btrim(p_values->>'title'),p_values->>'image_url',coalesce(p_values->>'image_alt',''),p_values->>'link_url',coalesce(p_values->>'open_mode','webview'),coalesce(p_values->>'placement','home_bottom'),
   (p_values->>'starts_at')::timestamptz,(p_values->>'ends_at')::timestamptz,coalesce((p_values->>'is_active')::boolean,true),coalesce((p_values->>'sort_order')::int,0),a.id) returning * into b;
 else
  select * into b from public.partner_banners where id=p_banner_id and merchant_id=p_merchant_id for update;
  if not found then raise exception 'BANNER_NOT_FOUND' using errcode='P0001'; end if;
  update public.partner_banners set partner_id=pid,title=btrim(p_values->>'title'),image_url=p_values->>'image_url',image_alt=coalesce(p_values->>'image_alt',''),link_url=p_values->>'link_url',open_mode=coalesce(p_values->>'open_mode','webview'),
   placement=coalesce(p_values->>'placement','home_bottom'),starts_at=(p_values->>'starts_at')::timestamptz,ends_at=(p_values->>'ends_at')::timestamptz,
   is_active=coalesce((p_values->>'is_active')::boolean,true),sort_order=coalesce((p_values->>'sort_order')::int,0)
   where id=b.id returning * into b;
 end if;
 insert into public.banner_rewards(banner_id,merchant_id,reward_type,point_amount,coupon_id,grant_policy,per_user_limit,total_budget,coupon_valid_days,is_active)
 values(b.id,p_merchant_id,coalesce(p_reward->>'reward_type','none'),(p_reward->>'point_amount')::bigint,(p_reward->>'coupon_id')::uuid,
  coalesce(p_reward->>'grant_policy','once'),(p_reward->>'per_user_limit')::int,(p_reward->>'total_budget')::bigint,(p_reward->>'coupon_valid_days')::int,coalesce((p_reward->>'is_active')::boolean,true))
 on conflict(banner_id) do update set reward_type=excluded.reward_type,point_amount=excluded.point_amount,coupon_id=excluded.coupon_id,
  grant_policy=excluded.grant_policy,per_user_limit=excluded.per_user_limit,total_budget=excluded.total_budget,coupon_valid_days=excluded.coupon_valid_days,is_active=excluded.is_active
 returning * into r;
 return jsonb_build_object('banner',to_jsonb(b),'reward',to_jsonb(r));
end $$;
revoke all on function public.save_partner_banner(uuid,uuid,uuid,jsonb,jsonb) from public,anon,authenticated;
grant execute on function public.save_partner_banner(uuid,uuid,uuid,jsonb,jsonb) to service_role;

-- Tenant authorization and all ordering changes share one transaction/RPC.
create or replace function public.reorder_partner_banners(p_actor_id uuid,p_merchant_id uuid,p_items jsonb)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare a public.app_users%rowtype; requested integer; changed integer;
begin
 select * into a from public.app_users where id=p_actor_id and role='merchant_admin' and status='active';
 if not found or not (a.merchant_id=p_merchant_id or (a.merchant_id is null and exists(select 1 from public.merchant_admins ma where ma.user_id=a.id and ma.merchant_id=p_merchant_id)))
 then raise exception 'FORBIDDEN' using errcode='P0001'; end if;
 if jsonb_typeof(p_items) is distinct from 'array'
 then raise exception 'INVALID_REORDER_ITEMS' using errcode='P0001'; end if;
 if jsonb_array_length(p_items) not between 1 and 200
 then raise exception 'INVALID_REORDER_ITEMS' using errcode='P0001'; end if;
 select count(*),count(distinct x.id) into requested,changed from jsonb_to_recordset(p_items) x(id uuid,sort_order integer);
 if requested<>changed or exists(
   select 1 from jsonb_to_recordset(p_items) x(id uuid,sort_order integer)
   left join public.partner_banners b on b.id=x.id and b.merchant_id=p_merchant_id
   where b.id is null or x.sort_order is null or x.sort_order not between -100000 and 100000)
 then raise exception 'BANNER_NOT_FOUND_OR_INVALID' using errcode='P0001'; end if;
 with values_to_apply as (select * from jsonb_to_recordset(p_items) x(id uuid,sort_order integer))
 update public.partner_banners b set sort_order=v.sort_order from values_to_apply v
 where b.id=v.id and b.merchant_id=p_merchant_id;
 get diagnostics changed=row_count;
 if changed<>requested then raise exception 'REORDER_CONFLICT' using errcode='P0001'; end if;
 return jsonb_build_object('items',p_items);
end $$;
revoke all on function public.reorder_partner_banners(uuid,uuid,jsonb) from public,anon,authenticated;
grant execute on function public.reorder_partner_banners(uuid,uuid,jsonb) to service_role;

-- Exactly-once grant. Reward row serialization protects budget and unlimited
-- counters; unique policy keys protect once/daily under concurrent requests.
create or replace function public.grant_banner_reward(p_event_id uuid,p_banner_id uuid,p_user_id uuid,p_now timestamptz default clock_timestamp())
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare b public.partner_banners%rowtype; r public.banner_rewards%rowtype; u public.app_users%rowtype; c public.merchant_coupons%rowtype;
 g public.banner_reward_grants%rowtype; pt public.point_transactions%rowtype; uc public.user_coupons%rowtype;
 k text; units bigint; grant_id uuid:=gen_random_uuid(); existing jsonb; until_at timestamptz;
begin
 select jsonb_build_object('granted',true,'duplicate',true,'reason','ok','grant_id',g0.id,'reward_type',g0.reward_type,'units',g0.units,'user_coupon_id',g0.user_coupon_id,
  'balance_after',pt0.balance_after)
 into existing from public.banner_reward_grants g0 join public.banner_events e0 on e0.id=g0.event_id
 left join public.point_transactions pt0 on pt0.id=g0.point_transaction_id
 where g0.event_id=p_event_id and e0.banner_id=p_banner_id and e0.user_id=p_user_id and e0.event_type='click';
 if existing is not null then return existing; end if;
 select * into b from public.partner_banners where id=p_banner_id for share;
 if not found or not b.is_active or (b.starts_at is not null and p_now<b.starts_at) or (b.ends_at is not null and p_now>=b.ends_at)
 then raise exception 'BANNER_NOT_LIVE' using errcode='P0001'; end if;
 if not exists(select 1 from public.partners p where p.id=b.partner_id and p.merchant_id=b.merchant_id and p.status='active')
 then raise exception 'BANNER_NOT_LIVE' using errcode='P0001'; end if;
 select * into r from public.banner_rewards where banner_id=b.id and merchant_id=b.merchant_id for update;
 -- A concurrent call with this event waited on the reward lock. Re-read only now,
 -- and require the immutable event identity before returning the original grant.
 select jsonb_build_object('granted',true,'duplicate',true,'reason','ok','grant_id',g0.id,'reward_type',g0.reward_type,'units',g0.units,'user_coupon_id',g0.user_coupon_id,
  'balance_after',pt0.balance_after)
 into existing from public.banner_reward_grants g0 join public.banner_events e0 on e0.id=g0.event_id
 left join public.point_transactions pt0 on pt0.id=g0.point_transaction_id
 where g0.event_id=p_event_id and e0.banner_id=p_banner_id and e0.user_id=p_user_id and e0.event_type='click';
 if existing is not null then return existing; end if;
 if exists(select 1 from public.banner_events e0 where e0.id=p_event_id and (e0.banner_id<>p_banner_id or e0.user_id is distinct from p_user_id or e0.event_type<>'click'))
 then raise exception 'EVENT_ID_CONFLICT' using errcode='P0001'; end if;
 if r.id is null or not r.is_active or r.reward_type='none' then
  insert into public.banner_events(id,banner_id,merchant_id,user_id,event_type,occurred_at) values(p_event_id,b.id,b.merchant_id,p_user_id,'click',p_now) on conflict do nothing;
  return jsonb_build_object('granted',false,'reason','no_reward');
 end if;
 select * into u from public.app_users where id=p_user_id and status='active' for update;
 if not found then raise exception 'USER_NOT_FOUND' using errcode='P0001'; end if;
 if r.reward_type='point' and u.company_id is null then
  insert into public.banner_events(id,banner_id,merchant_id,user_id,event_type,occurred_at) values(p_event_id,b.id,b.merchant_id,p_user_id,'click',p_now) on conflict do nothing;
  return jsonb_build_object('granted',false,'reason','no_company');
 end if;
 if r.grant_policy='once' then k='once'; elsif r.grant_policy='daily' then k=to_char(p_now at time zone 'Asia/Seoul','YYYY-MM-DD');
 else k='event:'||p_event_id::text; end if;
 insert into public.banner_events(id,banner_id,merchant_id,user_id,event_type,occurred_at) values(p_event_id,b.id,b.merchant_id,u.id,'click',p_now);
 if exists(select 1 from public.banner_reward_grants where reward_id=r.id and user_id=u.id and policy_key=k) then
  return jsonb_build_object('granted',false,'reason','already_granted');
 end if;
 if r.per_user_limit is not null and (select count(*) from public.banner_reward_grants where reward_id=r.id and user_id=u.id)>=r.per_user_limit then
  return jsonb_build_object('granted',false,'reason','user_limit');
 end if;
 units=case when r.reward_type='point' then r.point_amount else 1 end;
 if r.total_budget is not null and r.granted_total+units>r.total_budget then return jsonb_build_object('granted',false,'reason','budget_exhausted'); end if;
 if r.reward_type='coupon' then
  select * into c from public.merchant_coupons where id=r.coupon_id and merchant_id=b.merchant_id and is_active for share;
  if not found or (c.valid_from is not null and (p_now at time zone 'Asia/Seoul')::date<c.valid_from) or (c.valid_until is not null and (p_now at time zone 'Asia/Seoul')::date>c.valid_until) then raise exception 'COUPON_NOT_ISSUABLE' using errcode='P0001'; end if;
 end if;
 if r.reward_type='point' then
  update public.app_users set point_balance=point_balance+units where id=u.id returning * into u;
  insert into public.point_transactions(user_id,company_id,type,amount,balance_after,reason,processed_by,related_banner_id)
   values(u.id,u.company_id,'charge',units,u.point_balance,'파트너 배너 리워드',null,b.id) returning * into pt;
  insert into public.banner_reward_grants(id,event_id,reward_id,banner_id,merchant_id,user_id,policy_key,units,reward_type,point_transaction_id)
   values(grant_id,p_event_id,r.id,b.id,b.merchant_id,u.id,k,units,'point',pt.id) returning * into g;
 else
  until_at=case when r.coupon_valid_days is null then null else p_now+make_interval(days=>r.coupon_valid_days) end;
  if c.valid_until is not null then until_at=least(coalesce(until_at,(c.valid_until+1)::timestamptz),(c.valid_until+1)::timestamptz); end if;
  insert into public.user_coupons(user_id,merchant_id,coupon_id,reward_grant_id,coupon_snapshot,valid_from,valid_until)
   values(u.id,b.merchant_id,c.id,grant_id,jsonb_build_object('id',c.id,'merchant_id',c.merchant_id,'name',c.name,'discount_type',c.discount_type,'discount_value',c.discount_value,'valid_from',c.valid_from,'valid_until',c.valid_until),p_now,until_at) returning * into uc;
  insert into public.banner_reward_grants(id,event_id,reward_id,banner_id,merchant_id,user_id,policy_key,units,reward_type,user_coupon_id)
   values(grant_id,p_event_id,r.id,b.id,b.merchant_id,u.id,k,1,'coupon',uc.id) returning * into g;
 end if;
 update public.banner_rewards set granted_total=granted_total+units where id=r.id;
 return jsonb_build_object('granted',true,'duplicate',false,'reason','ok','grant_id',g.id,'reward_type',g.reward_type,'units',units,'user_coupon_id',g.user_coupon_id,'balance_after',u.point_balance);
end $$;
revoke all on function public.grant_banner_reward(uuid,uuid,uuid,timestamptz) from public,anon,authenticated;
grant execute on function public.grant_banner_reward(uuid,uuid,uuid,timestamptz) to service_role;

create or replace function public.reserve_user_coupon(p_order_id uuid,p_user_coupon_id uuid,p_user_id uuid,p_merchant_id uuid)
returns jsonb language plpgsql security definer set search_path=pg_catalog,public as $$
declare o public.payment_orders%rowtype; uc public.user_coupons%rowtype;
begin
 select * into o from public.payment_orders where id=p_order_id and user_id=p_user_id and merchant_id=p_merchant_id for update;
 if not found or o.status<>'ready' or o.user_coupon_id is distinct from p_user_coupon_id then raise exception 'ORDER_NOT_RESERVABLE' using errcode='P0001'; end if;
 select * into uc from public.user_coupons where id=p_user_coupon_id for update;
 if not found or uc.user_id<>p_user_id or uc.merchant_id<>p_merchant_id or uc.coupon_id<>o.coupon_id then raise exception 'USER_COUPON_INVALID' using errcode='P0001'; end if;
 if uc.status='reserved' and uc.reserved_order_id=o.id then return jsonb_build_object('reserved',true,'duplicate',true); end if;
 if uc.status<>'available' or uc.valid_from>now() or (uc.valid_until is not null and uc.valid_until<=now()) then raise exception 'USER_COUPON_NOT_AVAILABLE' using errcode='P0001'; end if;
 update public.user_coupons set status='reserved',reserved_order_id=o.id,reserved_at=now() where id=uc.id;
 return jsonb_build_object('reserved',true,'duplicate',false);
end $$;
revoke all on function public.reserve_user_coupon(uuid,uuid,uuid,uuid) from public,anon,authenticated;
grant execute on function public.reserve_user_coupon(uuid,uuid,uuid,uuid) to service_role;

-- Fail closed on fulfillment and release only for authoritative terminal failures.
create or replace function public.enforce_user_coupon_order_lifecycle() returns trigger
language plpgsql security definer set search_path=pg_catalog,public as $$
declare uc public.user_coupons%rowtype;
begin
 if new.user_coupon_id is null then return new; end if;
 select * into uc from public.user_coupons where id=new.user_coupon_id for update;
 if not found then raise exception 'USER_COUPON_INVALID' using errcode='P0001'; end if;
 if (old.fulfilled_at is null and new.fulfilled_at is not null) or (old.status<>'done' and new.status='done') then
  if uc.status<>'reserved' or uc.reserved_order_id<>new.id or uc.user_id<>new.user_id or uc.merchant_id<>new.merchant_id or (uc.valid_until is not null and uc.valid_until<=now())
   then raise exception 'USER_COUPON_CONSUME_CONFLICT' using errcode='P0001'; end if;
  update public.user_coupons set status='used',reserved_order_id=null,reserved_at=null,used_order_id=new.id,used_at=coalesce(new.fulfilled_at,now()) where id=uc.id;
 elsif old.status='ready' and new.status in ('failed','canceled') and uc.status='reserved' and uc.reserved_order_id=new.id then
  update public.user_coupons set status=case when valid_until is not null and valid_until<=now() then 'expired' else 'available' end,reserved_order_id=null,reserved_at=null where id=uc.id;
 end if;
 return new;
end $$;
revoke all on function public.enforce_user_coupon_order_lifecycle() from public,anon,authenticated,service_role;
drop trigger if exists trg_user_coupon_order_lifecycle on public.payment_orders;
create trigger trg_user_coupon_order_lifecycle before update of status,fulfilled_at on public.payment_orders for each row execute function public.enforce_user_coupon_order_lifecycle();

create or replace view public.partner_banner_stats as
select b.merchant_id,b.id banner_id,count(*) filter(where e.event_type='impression') impressions,
 count(*) filter(where e.event_type='click') clicks,count(distinct g.id) grants,coalesce(sum(g.units),0) granted_units
from public.partner_banners b left join public.banner_events e on e.banner_id=b.id
left join public.banner_reward_grants g on g.event_id=e.id group by b.merchant_id,b.id;

create or replace view public.v_banner_stats_daily as
select b.merchant_id,b.id banner_id,(e.occurred_at at time zone 'Asia/Seoul')::date as "day",
 count(*) filter(where e.event_type='impression') impressions,
 count(*) filter(where e.event_type='click') clicks,count(g.id) grants,
 coalesce(sum(g.units),0) granted_units
from public.partner_banners b join public.banner_events e on e.banner_id=b.id
left join public.banner_reward_grants g on g.event_id=e.id
group by b.merchant_id,b.id,(e.occurred_at at time zone 'Asia/Seoul')::date;

insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values('partner-banners','partner-banners',true,2097152,array['image/webp'])
on conflict(id) do update set public=excluded.public,file_size_limit=excluded.file_size_limit,allowed_mime_types=excluded.allowed_mime_types;

alter table public.partners enable row level security; alter table public.partner_banners enable row level security;
alter table public.banner_rewards enable row level security; alter table public.user_coupons enable row level security;
alter table public.banner_events enable row level security; alter table public.banner_reward_grants enable row level security;
revoke all on table public.partners,public.partner_banners,public.banner_rewards,public.user_coupons,public.banner_events,public.banner_reward_grants from public,anon,authenticated,service_role;
grant select,insert,update,delete on table public.partners,public.partner_banners,public.banner_rewards to service_role;
grant select,insert,update on table public.user_coupons to service_role;
grant select,insert on table public.banner_events,public.banner_reward_grants to service_role;
revoke all on public.partner_banner_stats from public,anon,authenticated; grant select on public.partner_banner_stats to service_role;
revoke all on public.v_banner_stats_daily from public,anon,authenticated; grant select on public.v_banner_stats_daily to service_role;
notify pgrst,'reload schema';
commit;
