-- Allow point-only subsidized voucher orders to keep a zero card payment amount.
-- Migration 0024 already models subsidized orders with amount >= 0 in
-- toss_payment_orders_voucher_columns_check, but the original table-level
-- amount constraint from 0014 still rejects zero before that check can pass.
alter table toss_payment_orders
  drop constraint if exists toss_payment_orders_amount_check;

alter table toss_payment_orders
  add constraint toss_payment_orders_amount_check check (amount >= 0);
