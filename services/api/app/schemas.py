from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

class GPSPoint(BaseModel):
    lat: float
    lng: float

class PayRequest(BaseModel):
    qr_token: str
    amount: int = Field(gt=0)
    product_id: str | None = Field(default=None, max_length=80)
    gps: GPSPoint | None = None
    idempotency_key: str


class ConsumerRegisterRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)


class TossOrderCreateRequest(BaseModel):
    qr_token: str = Field(min_length=1, max_length=120)
    product_id: str = Field(min_length=8, max_length=80)


class TossPaymentConfirmRequest(BaseModel):
    payment_key: str = Field(min_length=1, max_length=200)
    order_id: str = Field(min_length=6, max_length=64)
    amount: int = Field(gt=0)


class VoucherProductCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    voucher_count: int = Field(gt=0, le=1000)
    bonus_count: int = Field(default=0, ge=0, le=1000)
    unit_price: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    discount_rate: Decimal = Field(default=Decimal("0"), ge=0, lt=100, max_digits=5, decimal_places=2)
    status: str = Field(default="active", pattern="^(active|inactive)$")
    display_order: int = Field(default=0, ge=-100000, le=100000)
    image_url: str | None = Field(default=None, max_length=500)

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class VoucherProductUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    voucher_count: int | None = Field(default=None, gt=0, le=1000)
    bonus_count: int | None = Field(default=None, ge=0, le=1000)
    unit_price: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    discount_rate: Decimal | None = Field(default=None, ge=0, lt=100, max_digits=5, decimal_places=2)
    status: str | None = Field(default=None, pattern="^(active|inactive)$")
    display_order: int | None = Field(default=None, ge=-100000, le=100000)
    image_url: str | None = Field(default=None, max_length=500)

    @field_validator("name", "voucher_count", "bonus_count", "unit_price", "discount_rate", "status", "display_order", mode="before")
    @classmethod
    def reject_explicit_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("필드는 null일 수 없어요")
        return value

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class VoucherPurchaseRequest(BaseModel):
    product_id: str = Field(min_length=8, max_length=80)


class TransactionScanRequest(BaseModel):
    qr_data: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=120)
    product_id: str | None = Field(default=None, min_length=8, max_length=80)
    # Accepted only for old scanner payload compatibility; server contract price always wins.
    amount: int | None = Field(default=None, gt=0)
    gps: GPSPoint | None = None

class ApiError(BaseModel):
    code: str
    message: str

class ApiResponse(BaseModel):
    ok: bool
    data: dict | None = None
    error: ApiError | None = None


class JoinRequest(BaseModel):
    invite_code: str = Field(min_length=4, max_length=64)
    display_name: str = Field(min_length=1, max_length=80)


class JoinDecisionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class EmployeeLimitUpdateRequest(BaseModel):
    monthly_limit: int = Field(ge=0, le=10000000)


class EmployeeProfileUpdateRequest(BaseModel):
    employee_no: str | None = Field(default=None, max_length=40)

    @field_validator("employee_no", mode="before")
    @classmethod
    def normalize_employee_no(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            return value.strip() or None
        return value


class EmployeeBulkRow(BaseModel):
    row: int = Field(ge=2, le=1000000)
    department: str | None = Field(default=None, max_length=120)
    name: str = Field(max_length=80)
    employee_no: str | None = Field(default=None, max_length=40)
    phone: str = Field(max_length=40)
    auto_generated: bool = False

    model_config = {"extra": "forbid"}


class EmployeeBulkConfirmRequest(BaseModel):
    valid_rows: list[EmployeeBulkRow] = Field(min_length=1, max_length=500)

    model_config = {"extra": "forbid"}


class MealPolicyUpdateRequest(BaseModel):
    enabled: bool = False
    lunch_start: str = Field(default='11:00', pattern=r'^\d{2}:\d{2}$')
    lunch_end: str = Field(default='14:00', pattern=r'^\d{2}:\d{2}$')
    dinner_start: str = Field(default='17:30', pattern=r'^\d{2}:\d{2}$')
    dinner_end: str = Field(default='20:30', pattern=r'^\d{2}:\d{2}$')


class ProductCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    price: int = Field(gt=0)
    category: str | None = Field(default=None, max_length=40)
    image_url: str | None = Field(default=None, max_length=500)
    is_active: bool = True
    sort_order: int = 0


class ProductUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    price: int | None = Field(default=None, gt=0)
    category: str | None = Field(default=None, max_length=40)
    image_url: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None
    sort_order: int | None = None


class DailyMenuUpsertRequest(BaseModel):
    service_date: date
    title: str = Field(default='오늘 뷔페 메뉴', min_length=1, max_length=80)
    menu_text: str = Field(min_length=1, max_length=1000)
    image_url: str | None = Field(default=None, max_length=500)
    is_active: bool = True


class ImageUploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=100)
    data_base64: str = Field(min_length=1, max_length=7_100_000)


class PlatformMerchantCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    owner_phone: str | None = Field(default=None, max_length=40)
    category: str | None = Field(default=None, max_length=40)
    avg_price: int | None = Field(default=None, gt=0)


class InviteCreateRequest(BaseModel):
    phone: str = Field(min_length=5, max_length=40)


class InviteClaimRequest(BaseModel):
    auth_user_id: str = Field(min_length=8, max_length=80)
    display_name: str | None = Field(default=None, max_length=80)


class MerchantCompanyLinkRequest(BaseModel):
    company_id: str = Field(min_length=8, max_length=80)


class MerchantCompanyCreateAndLinkRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    owner_phone: str = Field(min_length=5, max_length=40)


class SettlementPaymentConfirmRequest(BaseModel):
    paid_at: str = Field(min_length=8, max_length=40)


class SettlementCreateRequest(BaseModel):
    period_from: str = Field(min_length=10, max_length=10)
    period_to: str = Field(min_length=10, max_length=10)


class MerchantCompanyContractUpdateRequest(BaseModel):
    settlement_cycle: str = Field(pattern='^(month_end|day)$')
    settlement_day: int | None = Field(default=None, ge=1, le=31)
    unit_price: int | None = Field(default=None, ge=0)
