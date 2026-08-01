from pathlib import Path


MIGRATION = Path(__file__).parents[3] / "infra" / "migrations" / "0056_admin_dashboard_summary.sql"
TREND_MIGRATION = Path(__file__).parents[3] / "infra" / "migrations" / "0057_admin_dashboard_trend_buckets.sql"


def test_admin_dashboard_migration_security_and_contract():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    signature = "public.admin_dashboard_summary(uuid, date, date, uuid, uuid, integer)"
    assert "security definer" in sql
    assert "set search_path = pg_catalog, public" in sql
    assert "from public.meal_transactions" in sql
    assert "from public.app_users" in sql
    assert "from public.companies" in sql
    assert "from public.merchants" in sql
    assert "at time zone 'asia/seoul'" in sql
    assert "t.settlement_total_amount" in sql
    assert "when t.pay_type = 'subsidized' then t.company_subsidy_amount else abs(t.amount) end" in sql
    assert "t.pay_type in ('ledger', 'subsidized')" in sql
    assert "t.kind in ('spend', 'refund', 'cancel')" in sql
    assert "generate_series" in sql
    assert "p_period_to - p_period_from + 1 > 366" in sql
    assert "admin_dashboard_scope_not_found" in sql
    assert "p_dinner_start_hour" in sql
    assert f"revoke all on function {signature} from public, anon, authenticated, service_role" in sql
    assert f"grant execute on function {signature} to service_role" in sql


def test_company_scope_skips_company_ranking_work():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "if p_company_id is null then" in sql
    assert "top_companies_by_amount" in sql
    assert "top_companies_by_count" in sql


def test_dashboard_json_builders_use_exact_redesign_contract_keys():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "'label', m.meal_type" in sql
    assert "'meal_type', m.meal_type" not in sql
    assert "'rank', sort_order, 'name', name, 'amount', amount" in sql
    assert "'rank', sort_order, 'name', name, 'count', count" in sql
    assert "select 5, '기타', sum(amount)::bigint" in sql
    assert "select 5, '기타', sum(count)::bigint" in sql
    assert "'company_id', company_id" not in sql
    assert "'company_name', company_name" not in sql


def test_meal_ratio_uses_spend_distribution_not_signed_net_count():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "count(*) filter (where f.direction = 1)::bigint as spend_count" in sql
    assert "round(m.spend_count::numeric * 100.0 / rt.spend_count, 1)" in sql


def test_trend_migration_selects_unit_and_excludes_zero_buckets_server_side():
    sql = TREND_MIGRATION.read_text(encoding="utf-8").lower()
    assert "when v_days <= 31 then 'day'" in sql
    assert "when v_days <= 120 then 'week'" in sql
    assert "else 'month'" in sql
    assert "date_trunc('week'" in sql
    assert "date_trunc('month'" in sql
    assert "where amount <> 0 or count <> 0" in sql
    assert "'unit', v_unit" in sql
    assert "generate_series" not in sql
