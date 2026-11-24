"""0081 replaces two read-only functions: nothing but the count rules may differ from before."""
import difflib
import re
from pathlib import Path

ROOT = Path(__file__).parents[3]
NEW = (ROOT / "supabase" / "migrations" / "0081_dashboard_counts_skip_subsidy_charges.sql").read_text(encoding="utf-8")
MARKERS = ("unit", "is_meal", "subsidy_charge", "0081")


def _function(sql: str, name: str) -> list[str]:
    start = sql.lower().index(f"create or replace function public.{name}(")
    text = sql[start:]
    opener = re.search(r"\bas\s+(\$\w*\$)", text, re.I)
    begin = opener.end()
    end = text.index(opener.group(1), begin)
    lines = [re.sub(r"\s+", " ", line).strip().lower() for line in text[begin:end].splitlines()]
    return [line for line in lines if line and not line.startswith("--")]


def _changed(old: list[str], new: list[str]) -> tuple[list[str], list[str]]:
    diff = list(difflib.unified_diff(old, new, lineterm="", n=0))
    added = [line[1:] for line in diff if line.startswith("+") and not line.startswith("+++")]
    removed = [line[1:] for line in diff if line.startswith("-") and not line.startswith("---")]
    return added, removed


def _check(name: str, previous_file: str, removed_expected: int, rewritten: tuple[str, str] | None = None):
    old = _function((ROOT / "infra" / "migrations" / previous_file).read_text(encoding="utf-8"), name)
    if rewritten:  # a later migration edited the stored body in place
        assert old.count(rewritten[0]) == 1
        old = [rewritten[1] if line == rewritten[0] else line for line in old]
    new = _function(NEW, name)
    added, removed = _changed(old, new)
    assert added and all(any(marker in line for marker in MARKERS) for line in added), added
    # Only amount/count expressions were rewritten: no access check, filter, join or output key was removed.
    assert len(removed) == removed_expected, removed
    assert all(line.startswith(("count(", "sum(", "coalesce(sum(", "coalesce(t.total_amount")) for line in removed), removed
    assert all(("count" in line or "gross_amount" in line) for line in removed), removed


def test_admin_dashboard_summary_differs_only_in_count_rules():
    _check("admin_dashboard_summary", "0057_admin_dashboard_trend_buckets.sql", removed_expected=6)


def test_company_monthly_usage_differs_only_in_count_rules():
    # 0045 pointed this function at normal_settlements (demo settlements excluded).
    _check("company_monthly_usage", "0040_company_monthly_usage.sql", removed_expected=13,
           rewritten=("from public.settlements s", "from public.normal_settlements s"))


def test_functions_stay_service_role_only_and_touch_nothing_else():
    lowered = NEW.lower()
    for signature in ("public.admin_dashboard_summary(uuid, date, date, uuid, uuid, integer)",
                      "public.company_monthly_usage(uuid, uuid, text)"):
        assert f"revoke all on function {signature} from public, anon, authenticated, service_role;" in lowered
        assert f"grant execute on function {signature} to service_role;" in lowered
    for forbidden in ("create table", "alter table", "create trigger", "drop ", "insert into", "update ", "delete from"):
        assert forbidden not in lowered, forbidden
    assert lowered.count("create or replace function") == 2
