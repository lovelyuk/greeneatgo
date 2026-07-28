-- GreenEatGo meal vouchers are always taxable.
-- Repair legacy voucher snapshots created before tax classification became mandatory.

update public.voucher_products
set tax_type = 'taxable'
where tax_type is distinct from 'taxable';

update public.merchant_companies
set tax_type = 'taxable'
where tax_type is distinct from 'taxable';

-- The immutable snapshot guard requires same-transaction audit evidence for
-- every legacy voucher classification. Only unused, exactly-priced vouchers
-- can still be consumed, so do not rewrite used/refunded historical facts.
insert into public.tax_classification_audit(
  merchant_id, voucher_id, actor_id, previous_tax_type, selected_tax_type,
  reason, transaction_xid
)
select
  v.merchant_id, v.id, v.user_id, 'unclassified', 'taxable',
  'System invariant: GreenEatGo meal vouchers are always taxable',
  pg_catalog.txid_current()
from public.vouchers v
where v.status = 'unused'
  and v.tax_type = 'unclassified'
  and v.purchase_price_won is not null;

update public.vouchers
set tax_type = 'taxable'
where status = 'unused'
  and tax_type = 'unclassified'
  and purchase_price_won is not null;

create or replace function public.enforce_voucher_taxable() returns trigger
language plpgsql set search_path=pg_catalog,public as $$
begin
  new.tax_type := 'taxable';
  return new;
end $$;

drop trigger if exists trg_enforce_voucher_product_taxable on public.voucher_products;
create trigger trg_enforce_voucher_product_taxable
before insert or update of tax_type on public.voucher_products
for each row execute function public.enforce_voucher_taxable();

drop trigger if exists trg_enforce_merchant_company_taxable on public.merchant_companies;
create trigger trg_enforce_merchant_company_taxable
before insert or update of tax_type on public.merchant_companies
for each row execute function public.enforce_voucher_taxable();

drop trigger if exists trg_enforce_voucher_taxable on public.vouchers;
create trigger trg_enforce_voucher_taxable
before insert or update of tax_type on public.vouchers
for each row execute function public.enforce_voucher_taxable();

revoke all on function public.enforce_voucher_taxable() from public,anon,authenticated;
