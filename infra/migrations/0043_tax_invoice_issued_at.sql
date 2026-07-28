begin;

-- A successful Popbill issue call does not return the provider's issue timestamp.
-- Preserve a trustworthy local success timestamp immediately; a later provider
-- status refresh may supply the provider timestamp through the existing sync RPC.
create or replace function public.ensure_tax_invoice_issued_at()
returns trigger
language plpgsql
set search_path=pg_catalog,public
as $$
begin
  if new.popbill_status = 'issued' and new.issued_at is null then
    new.issued_at := clock_timestamp();
  end if;
  return new;
end $$;

drop trigger if exists tax_invoices_ensure_issued_at on public.tax_invoices;
create trigger tax_invoices_ensure_issued_at
before insert or update of popbill_status,issued_at on public.tax_invoices
for each row execute function public.ensure_tax_invoice_issued_at();

-- Backfill only provider-confirmed rows. Prefer the immutable issuance event time
-- over a generic row update time when an older success lacks issued_at.
update public.tax_invoices i
set issued_at = coalesce(
      (select min(e.occurred_at)
         from public.tax_invoice_events e
        where e.tax_invoice_id = i.id
          and e.event_type = 'tax_invoice_issue_succeeded'),
      i.updated_at,
      clock_timestamp()
    )
where i.popbill_status = 'issued'
  and i.issued_at is null;

revoke all on function public.ensure_tax_invoice_issued_at() from public,anon,authenticated;

commit;
