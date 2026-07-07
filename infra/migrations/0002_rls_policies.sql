-- RLS baseline. Writes are intentionally routed through FastAPI service_role.
alter table app_users enable row level security;
alter table meal_transactions enable row level security;
alter table merchants enable row level security;
alter table company_merchants enable row level security;

create policy app_users_select_self on app_users for select using (auth.uid() = id);
create policy app_users_update_self_fcm on app_users for update using (auth.uid() = id) with check (auth.uid() = id);

create policy meal_transactions_select_self on meal_transactions for select using (auth.uid() = user_id);

create policy merchants_authenticated_read on merchants for select to authenticated using (status = 'active');
create policy company_merchants_authenticated_read on company_merchants for select to authenticated using (is_active = true);

-- No client insert/update/delete policies for ledger/payment tables by design.

alter table company_invite_codes enable row level security;
alter table employee_join_audit_logs enable row level security;
-- Join approval writes stay server-only via FastAPI service_role.
