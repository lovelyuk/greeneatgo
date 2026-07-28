from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class _StableModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CompanyUsagePeriod(_StableModel):
    ym: str
    timezone: str
    start_at: datetime
    end_at: datetime


class CompanyUsageAmounts(_StableModel):
    gross_spend_amount: int
    company_charge_amount: int
    employee_paid_amount: int
    transaction_count: int
    spend_count: int
    reversal_count: int
    unique_users: int


class CompanyUsageSummary(CompanyUsageAmounts):
    used_employee_count: int
    total_employee_count: int
    active_employee_count: int
    outstanding_settlement_amount: int
    confirmed_payment_amount: int


class CompanyDailyUsage(CompanyUsageAmounts):
    date: date


class CompanyEmployeeUsage(_StableModel):
    user_id: UUID
    display_name: str
    employee_no: str | None
    department: str | None
    status: str
    gross_spend_amount: int
    company_charge_amount: int
    employee_paid_amount: int
    transaction_count: int
    spend_count: int
    reversal_count: int
    usage_days: int


class CompanyUsageSettlements(_StableModel):
    count: int
    total_amount: int
    confirmed_payment_amount: int
    outstanding_amount: int


class CompanyMonthlyUsage(_StableModel):
    period: CompanyUsagePeriod
    summary: CompanyUsageSummary
    daily: list[CompanyDailyUsage]
    employees: list[CompanyEmployeeUsage]
    settlements: CompanyUsageSettlements


class CompanyMonthlyUsageResponse(_StableModel):
    ok: bool
    data: CompanyMonthlyUsage
    error: None = None
