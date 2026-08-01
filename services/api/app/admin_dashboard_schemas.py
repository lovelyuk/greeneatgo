from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _StableModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MealTypeSummary(_StableModel):
    label: str
    amount: int
    count: int
    ratio: float = Field(ge=0, le=100)


class TopCompanyByAmount(_StableModel):
    rank: int
    name: str
    amount: int


class TopCompanyByCount(_StableModel):
    rank: int
    name: str
    count: int


class DashboardSeriesPoint(_StableModel):
    date: date
    amount: int
    count: int


class AdminDashboardSummary(_StableModel):
    total_amount: int
    total_amount_delta_pct: float | None
    total_count: int
    total_count_delta_pct: float | None
    by_meal_type: list[MealTypeSummary]
    top_companies_by_amount: list[TopCompanyByAmount]
    top_companies_by_count: list[TopCompanyByCount]
    unit: Literal["day", "week", "month"]
    series: list[DashboardSeriesPoint]


class AdminDashboardSummaryResponse(_StableModel):
    ok: bool
    data: AdminDashboardSummary
    error: None = None
