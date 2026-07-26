-- Persist company business-profile fields edited by company administrators.
alter table companies add column if not exists representative_name text;
alter table companies add column if not exists business_type text;
alter table companies add column if not exists business_item text;
alter table companies add column if not exists address text;
alter table companies add column if not exists contact_name text;
alter table companies add column if not exists tax_invoice_email text;
