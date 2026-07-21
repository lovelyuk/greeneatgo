-- Harden service-owned domain tables before exposing the fresh schema through PostgREST.
-- Customer/admin apps use the API; only the backend service role accesses these tables.

alter table companies enable row level security;
alter table employee_groups enable row level security;
alter table invites enable row level security;
alter table meal_policies enable row level security;
alter table merchant_admins enable row level security;
alter table merchant_companies enable row level security;
alter table merchant_daily_menus enable row level security;
alter table merchant_products enable row level security;
alter table settlements enable row level security;

revoke all on table
  companies,
  employee_groups,
  invites,
  meal_policies,
  merchant_admins,
  merchant_companies,
  merchant_daily_menus,
  merchant_products,
  settlements
from anon, authenticated;

grant all on table
  companies,
  employee_groups,
  invites,
  meal_policies,
  merchant_admins,
  merchant_companies,
  merchant_daily_menus,
  merchant_products,
  settlements
to service_role;
