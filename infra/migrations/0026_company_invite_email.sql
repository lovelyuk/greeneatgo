-- Company administrator email invitations (provider-neutral delivery metadata).
-- Employee invite codes and merchant/company links are intentionally unchanged.

alter table companies add column if not exists contact_email text;
alter table companies add column if not exists contact_phone text;
create index if not exists idx_companies_contact_email
  on companies(lower(contact_email)) where contact_email is not null;

alter table invites alter column phone drop not null;
alter table invites add column if not exists email text;
alter table invites add column if not exists email_send_status text not null default 'not_sent';
alter table invites add column if not exists email_sent_at timestamptz;
alter table invites add column if not exists email_error text;
alter table invites add column if not exists email_message_id text;
alter table invites add column if not exists accepted_at timestamptz;

alter table invites drop constraint if exists invites_status_check;
alter table invites add constraint invites_status_check
  check (status in ('pending','claimed','accepted','expired'));
alter table invites drop constraint if exists invites_email_send_status_check;
alter table invites add constraint invites_email_send_status_check
  check (email_send_status in ('not_sent','sent','failed'));
-- Kept nullable at the database level for pre-0026 company/merchant invitations.
-- The create-and-link API requires contact_email for every new company invite.

create index if not exists idx_invites_company_role_created
  on invites(company_id, role, created_at desc);
create index if not exists idx_invites_email on invites(lower(email)) where email is not null;
