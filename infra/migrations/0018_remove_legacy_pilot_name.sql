-- Keep the pilot merchant and historical payment snapshots on the current brand name.
update merchants
set name = '돈토'
where id = '20000000-0000-0000-0000-000000000001';

update payment_orders
set merchant_name = '돈토', updated_at = now()
where merchant_id = '20000000-0000-0000-0000-000000000001'
  and merchant_name <> '돈토';