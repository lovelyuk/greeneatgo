-- Product-scoped KiwoomPay checkout routing.
-- General products use the integrated checkout (TOTAL); selected voucher packages use LINK 3.5 BANK.

alter table voucher_products
  add column if not exists kiwoom_pay_method text not null default 'TOTAL';

alter table voucher_products
  drop constraint if exists voucher_products_kiwoom_pay_method_check;
alter table voucher_products
  add constraint voucher_products_kiwoom_pay_method_check
  check (kiwoom_pay_method in ('TOTAL', 'BANK'));

alter table payment_orders
  add column if not exists requested_payment_method text not null default 'TOTAL';

alter table payment_orders
  drop constraint if exists payment_orders_requested_payment_method_check;
alter table payment_orders
  add constraint payment_orders_requested_payment_method_check
  check (requested_payment_method in ('TOTAL', 'BANK'));

comment on column voucher_products.kiwoom_pay_method is
  'KiwoomPay request policy: TOTAL integrated checkout or BANK-only LINK 3.5.';
comment on column payment_orders.requested_payment_method is
  'Immutable snapshot of the KiwoomPay method requested when the order was created.';

create or replace function prevent_payment_order_method_change()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  if new.requested_payment_method is distinct from old.requested_payment_method then
    raise exception 'PAYMENT_METHOD_SNAPSHOT_IMMUTABLE' using errcode = '23514';
  end if;
  return new;
end;
$$;

drop trigger if exists payment_orders_method_immutable on payment_orders;
create trigger payment_orders_method_immutable
before update of requested_payment_method on payment_orders
for each row execute function prevent_payment_order_method_change();
