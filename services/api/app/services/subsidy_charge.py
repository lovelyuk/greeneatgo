"""Company subsidies billed when the voucher is bought (migration 0080).

A subsidized voucher writes a "charge" row in meal_transactions for the company at
purchase time (and a reversal row if the unused voucher is refunded). Those rows
are billing entries, not meals: settlement screens show them, everything that
lists or counts meals must leave them out. The meal row written when the voucher
is used later carries a settlement amount of 0.
"""


def _flags(row: dict) -> dict:
    flags = row.get("flags")
    return flags if isinstance(flags, dict) else {}


def is_subsidy_charge(row: dict) -> bool:
    """A purchase charge or its reversal (not a meal)."""
    return _flags(row).get("subsidy_charge") is True


def is_charged_at_purchase(row: dict) -> bool:
    """A meal whose company subsidy was already billed when the voucher was bought."""
    return _flags(row).get("charged_at_purchase") is True


def without_subsidy_charges(rows: list[dict]) -> list[dict]:
    return [row for row in rows if not is_subsidy_charge(row)]


def company_charge(row: dict) -> int:
    """Unsigned amount a subsidized row bills the company.

    The settlement amount when present (0 for a meal charged at purchase),
    otherwise the subsidy column (rows older than the settlement snapshot)."""
    if row.get("settlement_total_amount") is not None:
        return int(row.get("settlement_total_amount") or 0)
    return int(row.get("company_subsidy_amount") or 0)
