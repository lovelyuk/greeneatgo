-- Kiosk (Tap&Pick) paper receipt redemption at the restaurant counter.
-- One receipt number can be used exactly once (unique). The kiosk API only
-- answers "is this receipt valid"; usage is recorded here.
-- Additive only: new table, no change to existing data.
create table if not exists public.kiosk_receipt_redemptions (
  id uuid primary key default gen_random_uuid(),
  receipt_id text not null unique check (receipt_id ~ '^[0-9a-f]{24}$'),
  merchant_id uuid not null references public.merchants(id),
  redeemed_by uuid not null references public.app_users(id),
  provider text not null default 'tapandpick' check (provider = 'tapandpick'),
  provider_result integer not null,
  redeemed_at timestamptz not null default now()
);

create index if not exists kiosk_receipt_redemptions_merchant_time
  on public.kiosk_receipt_redemptions (merchant_id, redeemed_at desc);

alter table public.kiosk_receipt_redemptions enable row level security;
revoke all on public.kiosk_receipt_redemptions from public, anon, authenticated;
grant select, insert on public.kiosk_receipt_redemptions to service_role;

-- Let the Supabase REST API see the new table right away.
notify pgrst, 'reload schema';
