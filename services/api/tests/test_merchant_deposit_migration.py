import re
from pathlib import Path


MIGRATION = Path(__file__).resolve().parents[3] / "infra/migrations/0050_merchant_deposit_information.sql"


def test_merchant_deposit_migration_is_additive_nullable_bounded_and_replayable():
    sql = re.sub(r"\s+", " ", MIGRATION.read_text(encoding="utf-8").lower()).strip()
    for column in ("bank_name", "account_number", "account_holder"):
        assert re.search(
            rf"alter table (?:public\.)?merchants add column if not exists {column} varchar\(80\)",
            sql,
        )
    assert "not null" not in sql
    assert "update merchants" not in sql
    assert "default" not in sql
