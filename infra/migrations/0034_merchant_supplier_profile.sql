-- Persist merchant supplier-profile fields used for tax invoices.
alter table merchants add column if not exists representative_name text;
alter table merchants add column if not exists business_type text;
alter table merchants add column if not exists business_item text;
alter table merchants add column if not exists tax_invoice_email text;
