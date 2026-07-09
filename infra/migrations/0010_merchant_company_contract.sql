-- Merchant-company contract settings for restaurant-admin ledger companies.

alter table merchant_companies
  add column if not exists settlement_cycle text not null default 'month_end',
  add column if not exists settlement_day int,
  add column if not exists unit_price int;

alter table merchant_companies drop constraint if exists merchant_companies_settlement_cycle_check;
alter table merchant_companies
  add constraint merchant_companies_settlement_cycle_check
  check (settlement_cycle in ('month_end', 'day'));

alter table merchant_companies drop constraint if exists merchant_companies_settlement_day_check;
alter table merchant_companies
  add constraint merchant_companies_settlement_day_check
  check (
    (settlement_cycle = 'month_end' and settlement_day is null)
    or (settlement_cycle = 'day' and settlement_day between 1 and 31)
  );

alter table merchant_companies drop constraint if exists merchant_companies_unit_price_check;
alter table merchant_companies
  add constraint merchant_companies_unit_price_check
  check (unit_price is null or unit_price >= 0);
