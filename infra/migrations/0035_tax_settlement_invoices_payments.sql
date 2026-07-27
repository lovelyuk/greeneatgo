-- Tax snapshots, independent settlement workflow states, Popbill invoice history,
-- and auditable multi-payment matching. This migration is additive: legacy
-- transaction/settlement writers may continue omitting every new snapshot field.

-- Existing rows deliberately start unclassified. Never infer taxability from price.
alter table merchant_products
  add column if not exists tax_type text not null default 'unclassified';
alter table voucher_products
  add column if not exists tax_type text not null default 'unclassified';
alter table merchant_companies
  add column if not exists tax_type text not null default 'unclassified';

alter table merchant_products drop constraint if exists merchant_products_tax_type_check;
alter table merchant_products add constraint merchant_products_tax_type_check
  check (tax_type in ('taxable', 'tax_free', 'unclassified'));
alter table voucher_products drop constraint if exists voucher_products_tax_type_check;
alter table voucher_products add constraint voucher_products_tax_type_check
  check (tax_type in ('taxable', 'tax_free', 'unclassified'));
alter table merchant_companies drop constraint if exists merchant_companies_tax_type_check;
alter table merchant_companies add constraint merchant_companies_tax_type_check
  check (tax_type in ('taxable', 'tax_free', 'unclassified'));

-- Transaction-side amounts are immutable calculation snapshots. The first group
-- describes the customer transaction; settlement_* is the company billing target.
-- Null snapshots remain valid for historical/unclassified transactions.
alter table meal_transactions
  add column if not exists tax_type text not null default 'unclassified',
  add column if not exists settlement_tax_type text not null default 'unclassified',
  add column if not exists supply_amount int,
  add column if not exists vat_amount int,
  add column if not exists total_amount int,
  add column if not exists settlement_supply_amount int,
  add column if not exists settlement_vat_amount int,
  add column if not exists settlement_total_amount int,
  add column if not exists original_transaction_id bigint references meal_transactions(id);

alter table meal_transactions drop constraint if exists meal_transactions_tax_type_check;
alter table meal_transactions add constraint meal_transactions_tax_type_check
  check (tax_type in ('taxable', 'tax_free', 'unclassified'));
alter table meal_transactions drop constraint if exists meal_transactions_settlement_tax_type_check;
alter table meal_transactions add constraint meal_transactions_settlement_tax_type_check
  check (settlement_tax_type in ('taxable', 'tax_free', 'unclassified'));
alter table meal_transactions drop constraint if exists meal_transactions_tax_amounts_check;
alter table meal_transactions add constraint meal_transactions_tax_amounts_check check (
  num_nonnulls(supply_amount, vat_amount, total_amount) = 0
  or (num_nonnulls(supply_amount, vat_amount, total_amount) = 3
      and supply_amount >= 0 and vat_amount >= 0 and total_amount >= 0
      and supply_amount + vat_amount = total_amount)
);
alter table meal_transactions drop constraint if exists meal_transactions_settlement_tax_amounts_check;
alter table meal_transactions add constraint meal_transactions_settlement_tax_amounts_check check (
  num_nonnulls(settlement_supply_amount, settlement_vat_amount, settlement_total_amount) = 0
  or (num_nonnulls(settlement_supply_amount, settlement_vat_amount, settlement_total_amount) = 3
      and settlement_supply_amount >= 0 and settlement_vat_amount >= 0 and settlement_total_amount >= 0
      and settlement_supply_amount + settlement_vat_amount = settlement_total_amount)
);
alter table meal_transactions drop constraint if exists meal_transactions_original_not_self_check;
alter table meal_transactions add constraint meal_transactions_original_not_self_check
  check (original_transaction_id is null or original_transaction_id <> id);
-- `cancel` is already understood by ledger aggregation; retain every legacy kind
-- while making that historical/future reversal spelling writable too.
alter table meal_transactions drop constraint if exists meal_transactions_kind_check;
alter table meal_transactions add constraint meal_transactions_kind_check
  check (kind in ('grant', 'spend', 'expire', 'refund', 'cancel', 'adjust'));
create index if not exists idx_meal_transactions_original_transaction
  on meal_transactions(original_transaction_id) where original_transaction_id is not null;

-- Keep legacy status/total_amount for old RPCs and clients. Tax amounts are nullable
-- because migration cannot truthfully split historical totals into supply and VAT.
-- Record this before ALTER: legacy projection must run only on first application.
select set_config(
  'greeneatgo.migration_0035_had_settlement_status',
  (exists (
    select 1 from information_schema.columns
    where table_schema = current_schema()
      and table_name = 'settlements'
      and column_name = 'settlement_status'
  ))::text,
  false
);
alter table settlements
  add column if not exists supply_amount int,
  add column if not exists vat_amount int,
  add column if not exists settlement_status text not null default 'draft',
  add column if not exists tax_invoice_status text not null default 'not_requested',
  add column if not exists payment_status text not null default 'unpaid',
  add column if not exists sent_at timestamptz,
  add column if not exists confirmed_at timestamptz,
  add column if not exists finalized_at timestamptz,
  add column if not exists due_date date,
  add column if not exists created_at timestamptz not null default now(),
  add column if not exists updated_at timestamptz not null default now();

alter table settlements drop constraint if exists settlements_tax_amounts_check;
alter table settlements add constraint settlements_tax_amounts_check check (
  num_nonnulls(supply_amount, vat_amount) = 0
  or (num_nonnulls(supply_amount, vat_amount) = 2
      and supply_amount >= 0 and vat_amount >= 0
      and supply_amount + vat_amount = total_amount)
);
alter table settlements drop constraint if exists settlements_settlement_status_check;
alter table settlements add constraint settlements_settlement_status_check check (
  settlement_status in (
    'calculating', 'draft', 'sent', 'confirmed', 'disputed',
    'revising', 'finalized', 'completed', 'cancelled'
  )
);
alter table settlements drop constraint if exists settlements_tax_invoice_status_check;
alter table settlements add constraint settlements_tax_invoice_status_check check (
  tax_invoice_status in (
    'not_requested', 'requested', 'issuing', 'issued', 'nts_sending',
    'nts_accepted', 'failed', 'cancelled'
  )
);
alter table settlements drop constraint if exists settlements_payment_status_check;
alter table settlements add constraint settlements_payment_status_check
  check (payment_status in (
    'unpaid', 'matching', 'partially_paid', 'paid', 'overpaid', 'unmatched'
  ));

-- Conservative legacy backfill: preserve known workflow facts, but do not claim a
-- tax invoice or synthesize supply/VAT. Unknown historical event times remain null;
-- an existing legacy paid_at is the only safe finalized-time source.
update settlements
set settlement_status = case status
      when 'draft' then 'draft'
      when 'confirmed' then 'confirmed'
      when 'paid' then 'completed'
      else settlement_status
    end,
    payment_status = case when status = 'paid' then 'paid' else 'unpaid' end,
    finalized_at = case
      when status = 'paid' then coalesce(finalized_at, paid_at)
      else finalized_at
    end,
    updated_at = coalesce(updated_at, now())
where current_setting('greeneatgo.migration_0035_had_settlement_status') = 'false';

-- Translate the three old status values for legacy writers, and keep legacy readers
-- useful when new code changes settlement_status. No tax/payment facts are inferred.
create or replace function sync_settlement_legacy_status() returns trigger
language plpgsql
set search_path = public
as $$
declare
  v_projected_status text;
begin
  v_projected_status := case
    when new.payment_status in ('paid', 'overpaid') then 'paid'
    when new.settlement_status in ('confirmed', 'finalized', 'completed') then 'confirmed'
    else 'draft'
  end;

  if tg_op = 'INSERT' then
    -- A row already matching the two-axis projection is a new-ledger write.
    if new.status = v_projected_status then
      null;
    elsif new.status = 'confirmed' and new.settlement_status = 'draft' then
      new.settlement_status := 'confirmed';
      new.confirmed_at := coalesce(new.confirmed_at, now());
    elsif new.status = 'paid' and new.settlement_status = 'draft' then
      new.settlement_status := 'completed';
      new.payment_status := 'paid';
      new.confirmed_at := coalesce(new.confirmed_at, now());
      new.finalized_at := coalesce(new.finalized_at, new.paid_at, now());
      new.paid_at := coalesce(new.paid_at, now());
    end if;
  elsif new.status is distinct from old.status then
    if new.status = v_projected_status then
      -- Recompute changes status and payment_status together. Recognize that as
      -- internal synchronization and never overwrite independent workflow state.
      null;
    elsif new.settlement_status is not distinct from old.settlement_status
          and new.payment_status is not distinct from old.payment_status then
      -- A legacy writer changed status alone: preserve compatibility. The payment
      -- ledger remains authoritative once any payment row exists.
      new.settlement_status := case new.status
        when 'draft' then 'draft'
        when 'confirmed' then 'confirmed'
        when 'paid' then 'completed'
        else new.settlement_status
      end;
      if not exists (
        select 1 from settlement_payments where settlement_id = new.id
      ) then
        new.payment_status := case when new.status = 'paid' then 'paid' else 'unpaid' end;
        new.paid_at := case
          when new.status = 'paid' then coalesce(new.paid_at, now())
          else null
        end;
      end if;
      if new.status in ('confirmed', 'paid') then
        new.confirmed_at := coalesce(new.confirmed_at, now());
      end if;
      if new.status = 'paid' and new.payment_status = 'paid' then
        new.finalized_at := coalesce(new.finalized_at, new.paid_at, now());
      end if;
      new.status := case
        when new.payment_status in ('paid', 'overpaid') then 'paid'
        when new.settlement_status in ('confirmed', 'finalized', 'completed') then 'confirmed'
        else 'draft'
      end;
    end if;
  elsif new.settlement_status is distinct from old.settlement_status then
    new.status := v_projected_status;
  end if;
  new.updated_at := now();
  return new;
end $$;
revoke all on function sync_settlement_legacy_status() from public, anon, authenticated;
drop trigger if exists trg_sync_settlement_legacy_status on settlements;
create trigger trg_sync_settlement_legacy_status
before insert or update of status, settlement_status on settlements
for each row execute function sync_settlement_legacy_status();

-- Every issued document is retained. A settlement has at most one original;
-- corrections and cancellations form an explicit parent-linked history.
create table if not exists tax_invoices (
  id uuid primary key default gen_random_uuid(),
  settlement_id uuid not null references settlements(id),
  company_id uuid not null references companies(id),
  merchant_id uuid not null references merchants(id),
  parent_invoice_id uuid references tax_invoices(id),
  document_type text not null default 'original'
    check (document_type in ('original', 'correction', 'cancellation')),
  provider text not null default 'popbill',
  invoicer_mgt_key text not null unique check (char_length(btrim(invoicer_mgt_key)) > 0),
  issue_type text not null default 'charge',
  tax_type text not null check (tax_type in ('taxable', 'tax_free', 'unclassified')),
  write_date date not null,
  supply_amount int not null check (supply_amount >= 0),
  vat_amount int not null check (vat_amount >= 0),
  total_amount int not null check (total_amount >= 0),
  supplier_snapshot jsonb not null,
  recipient_snapshot jsonb not null,
  popbill_status_code int,
  popbill_status text,
  popbill_status_message text,
  nts_status_code text,
  nts_status text,
  nts_confirm_num text,
  provider_response jsonb,
  requested_at timestamptz,
  issue_requested_by uuid references app_users(id) on delete set null,
  issue_requested_at timestamptz,
  issued_by uuid references app_users(id) on delete set null,
  issued_at timestamptz,
  nts_sent_at timestamptz,
  nts_accepted_at timestamptz,
  cancelled_by uuid references app_users(id) on delete set null,
  cancelled_at timestamptz,
  failure_code text,
  failure_message text,
  failed_at timestamptz,
  created_by uuid references app_users(id) on delete set null,
  updated_by uuid references app_users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint tax_invoices_amounts_check check (supply_amount + vat_amount = total_amount),
  constraint tax_invoices_parent_check check (
    (document_type = 'original' and parent_invoice_id is null)
    or (document_type in ('correction', 'cancellation') and parent_invoice_id is not null)
  )
);
-- Composite keys make tenant/party consistency declarative and concurrency-safe:
-- an invoice must name its settlement's parties, and a child must name its
-- parent's exact settlement/party tuple (not merely an invoice UUID).
alter table tax_invoices drop constraint if exists tax_invoices_parent_parties_fkey;
alter table tax_invoices drop constraint if exists tax_invoices_settlement_parties_fkey;
alter table tax_invoices drop constraint if exists tax_invoices_invoice_parties_key;
alter table settlements drop constraint if exists settlements_invoice_parties_key;
alter table settlements add constraint settlements_invoice_parties_key
  unique (id, company_id, merchant_id);
alter table tax_invoices add constraint tax_invoices_settlement_parties_fkey
  foreign key (settlement_id, company_id, merchant_id)
  references settlements(id, company_id, merchant_id);
alter table tax_invoices add constraint tax_invoices_invoice_parties_key
  unique (id, settlement_id, company_id, merchant_id);
alter table tax_invoices add constraint tax_invoices_parent_parties_fkey
  foreign key (parent_invoice_id, settlement_id, company_id, merchant_id)
  references tax_invoices(id, settlement_id, company_id, merchant_id);

-- Composite FKs reject cross-settlement/cross-tenant parents. This trigger adds
-- graph integrity. The settlement-scoped advisory lock serializes parent changes,
-- preventing concurrent updates from jointly creating a cycle.
create or replace function enforce_tax_invoice_parent_integrity() returns trigger
language plpgsql
set search_path = public
as $$
begin
  perform pg_advisory_xact_lock(hashtextextended('tax_invoice_parent:' || new.settlement_id::text, 0));

  if new.document_type = 'original' and new.parent_invoice_id is not null then
    raise exception 'TAX_INVOICE_ORIGINAL_CANNOT_HAVE_PARENT' using errcode = '23514';
  elsif new.document_type in ('correction', 'cancellation') and new.parent_invoice_id is null then
    raise exception 'TAX_INVOICE_ADJUSTMENT_REQUIRES_PARENT' using errcode = '23514';
  end if;

  if new.parent_invoice_id is not null then
    if new.parent_invoice_id = new.id then
      raise exception 'TAX_INVOICE_SELF_PARENT' using errcode = '23514';
    end if;

    -- Lock the parent while validating. The composite FK remains the authoritative
    -- party/settlement check and also protects the relationship at commit time.
    perform 1 from tax_invoices
      where id = new.parent_invoice_id
        and settlement_id = new.settlement_id
        and company_id = new.company_id
        and merchant_id = new.merchant_id
      for key share;
    if not found then
      raise exception 'TAX_INVOICE_PARENT_PARTIES_MISMATCH' using errcode = '23503';
    end if;

    if exists (
      with recursive ancestors(id, parent_invoice_id) as (
        select id, parent_invoice_id from tax_invoices where id = new.parent_invoice_id
        union all
        select invoice.id, invoice.parent_invoice_id
        from tax_invoices invoice
        join ancestors on invoice.id = ancestors.parent_invoice_id
      )
      select 1 from ancestors where id = new.id
    ) then
      raise exception 'TAX_INVOICE_PARENT_CYCLE' using errcode = '23514';
    end if;
  end if;
  return new;
end $$;
revoke all on function enforce_tax_invoice_parent_integrity() from public, anon, authenticated;
drop trigger if exists trg_tax_invoice_parent_integrity on tax_invoices;
create trigger trg_tax_invoice_parent_integrity
before insert or update of parent_invoice_id, settlement_id, company_id, merchant_id, document_type
on tax_invoices for each row execute function enforce_tax_invoice_parent_integrity();
create unique index if not exists idx_tax_invoices_one_original_per_settlement
  on tax_invoices(settlement_id) where document_type = 'original';
create index if not exists idx_tax_invoices_settlement_history
  on tax_invoices(settlement_id, created_at, id);
create index if not exists idx_tax_invoices_parent
  on tax_invoices(parent_invoice_id) where parent_invoice_id is not null;

-- Provider callbacks and internal lifecycle transitions are append-only. Provider
-- event IDs are optional for internal events and globally de-duplicated when present.
create table if not exists tax_invoice_events (
  id bigint generated always as identity primary key,
  tax_invoice_id uuid not null references tax_invoices(id),
  event_type text not null check (char_length(btrim(event_type)) > 0),
  provider_event_id text,
  payload jsonb not null,
  actor_id uuid constraint tax_invoice_events_actor_id_fkey
    references app_users(id) on delete restrict,
  occurred_at timestamptz,
  received_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  constraint tax_invoice_events_provider_event_id_check
    check (provider_event_id is null or char_length(btrim(provider_event_id)) > 0)
);
-- Also upgrades a previously applied draft whose implicit FK used SET NULL.
alter table tax_invoice_events drop constraint if exists tax_invoice_events_actor_id_fkey;
alter table tax_invoice_events add constraint tax_invoice_events_actor_id_fkey
  foreign key (actor_id) references app_users(id) on delete restrict;
create unique index if not exists idx_tax_invoice_events_provider_event_unique
  on tax_invoice_events(provider_event_id) where provider_event_id is not null;
create index if not exists idx_tax_invoice_events_invoice_created
  on tax_invoice_events(tax_invoice_id, created_at, id);

create or replace function prevent_tax_invoice_event_mutation() returns trigger
language plpgsql
set search_path = public
as $$
begin
  raise exception 'TAX_INVOICE_EVENTS_ARE_IMMUTABLE' using errcode = '55000';
end $$;
revoke all on function prevent_tax_invoice_event_mutation() from public, anon, authenticated;
drop trigger if exists trg_tax_invoice_events_immutable on tax_invoice_events;
create trigger trg_tax_invoice_events_immutable
before update or delete on tax_invoice_events
for each row execute function prevent_tax_invoice_event_mutation();

-- Multiple deposits can match one settlement. Rows count toward payment_status only
-- after confirmed_at is set; idempotency and bank references de-duplicate ingestion.
create table if not exists settlement_payments (
  id uuid primary key default gen_random_uuid(),
  settlement_id uuid not null references settlements(id),
  amount int not null check (amount > 0),
  depositor_name text,
  deposited_at timestamptz not null,
  match_method text not null check (match_method in ('manual', 'automatic')),
  confirmed_by uuid references app_users(id) on delete set null,
  confirmed_at timestamptz,
  idempotency_key text,
  external_reference text,
  memo text,
  audit_metadata jsonb not null default '{}'::jsonb,
  created_by uuid references app_users(id) on delete set null,
  updated_by uuid references app_users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint settlement_payments_idempotency_key_check
    check (idempotency_key is null or char_length(btrim(idempotency_key)) > 0),
  constraint settlement_payments_external_reference_check
    check (external_reference is null or char_length(btrim(external_reference)) > 0)
);
create unique index if not exists idx_settlement_payments_idempotency_unique
  on settlement_payments(idempotency_key) where idempotency_key is not null;
create unique index if not exists idx_settlement_payments_external_reference_unique
  on settlement_payments(external_reference) where external_reference is not null;
create index if not exists idx_settlement_payments_settlement
  on settlement_payments(settlement_id);
create index if not exists idx_settlement_payments_settlement_confirmed
  on settlement_payments(settlement_id, confirmed_at) where confirmed_at is not null;

-- Lock the parent first so concurrent payment confirmations serialize. NO KEY UPDATE
-- still conflicts with another recompute, but coexists with the KEY SHARE lock taken
-- by a payment settlement_id FK check during reciprocal moves. This function never
-- changes a settlement key.
create or replace function recompute_settlement_payment_status(p_settlement_id uuid)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  v_total int;
  v_confirmed_total bigint;
  v_has_unconfirmed boolean;
  v_latest_confirmed_at timestamptz;
  v_status text;
begin
  select total_amount into v_total
  from settlements
  where id = p_settlement_id
  for no key update;

  if not found then
    return;
  end if;

  select coalesce(sum(amount), 0), max(confirmed_at)
    into v_confirmed_total, v_latest_confirmed_at
  from settlement_payments
  where settlement_id = p_settlement_id and confirmed_at is not null;

  select exists (
    select 1 from settlement_payments
    where settlement_id = p_settlement_id and confirmed_at is null
  ) into v_has_unconfirmed;

  v_status := case
    when v_confirmed_total = 0 and v_has_unconfirmed then 'matching'
    when v_confirmed_total = 0 then 'unpaid'
    when v_confirmed_total < v_total then 'partially_paid'
    when v_confirmed_total = v_total then 'paid'
    else 'overpaid'
  end;

  update settlements
  set payment_status = v_status,
      status = case
        when v_status in ('paid', 'overpaid') then 'paid'
        when settlement_status in ('confirmed', 'finalized', 'completed') then 'confirmed'
        else 'draft'
      end,
      paid_at = case
        when v_status in ('paid', 'overpaid') then v_latest_confirmed_at
        else null
      end,
      updated_at = now()
  where id = p_settlement_id;
end $$;
revoke all on function recompute_settlement_payment_status(uuid) from public, anon, authenticated;
grant execute on function recompute_settlement_payment_status(uuid) to service_role;

create or replace function settlement_payments_recompute_parent() returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if tg_op = 'DELETE' then
    perform recompute_settlement_payment_status(old.settlement_id);
  elsif tg_op = 'UPDATE' and old.settlement_id is distinct from new.settlement_id then
    -- Reciprocal moves acquire both settlement row locks in the same UUID order.
    if old.settlement_id < new.settlement_id then
      perform recompute_settlement_payment_status(old.settlement_id);
      perform recompute_settlement_payment_status(new.settlement_id);
    else
      perform recompute_settlement_payment_status(new.settlement_id);
      perform recompute_settlement_payment_status(old.settlement_id);
    end if;
  else
    perform recompute_settlement_payment_status(new.settlement_id);
  end if;
  return null;
end $$;
revoke all on function settlement_payments_recompute_parent() from public, anon, authenticated;
drop trigger if exists trg_settlement_payments_recompute_parent on settlement_payments;
create trigger trg_settlement_payments_recompute_parent
after insert or update or delete on settlement_payments
for each row execute function settlement_payments_recompute_parent();

-- Service-owned financial records are never directly exposed to browser roles.
alter table tax_invoices enable row level security;
alter table tax_invoice_events enable row level security;
alter table settlement_payments enable row level security;
revoke all on table tax_invoices, tax_invoice_events, settlement_payments
  from anon, authenticated, service_role;
grant select, insert, update, delete on table tax_invoices, settlement_payments
  to service_role;
grant select, insert on table tax_invoice_events to service_role;
-- Identity sequences have separate privileges in PostgreSQL/PostgREST.
revoke all on sequence tax_invoice_events_id_seq from anon, authenticated, service_role;
grant usage, select on sequence tax_invoice_events_id_seq to service_role;
