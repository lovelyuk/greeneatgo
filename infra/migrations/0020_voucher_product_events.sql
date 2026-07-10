-- Event voucher products are exposed only during their configured period.
alter table voucher_products
  add column if not exists is_event boolean not null default false,
  add column if not exists event_start_at timestamptz,
  add column if not exists event_end_at timestamptz;

alter table voucher_products
  drop constraint if exists voucher_products_event_period_check;
alter table voucher_products
  add constraint voucher_products_event_period_check check (
    not is_event
    or (
      event_start_at is not null
      and event_end_at is not null
      and event_end_at > event_start_at
    )
  );
