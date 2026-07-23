from datetime import date, datetime
from decimal import Decimal
import re

from pydantic import BaseModel, Field, field_validator, model_validator

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
    phone: str = Field(pattern=r"^010\d{8}$")

    @field_validator("display_name", mode="before")
    @classmethod
    def trim_consumer_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("phone", mode="before")
    @classmethod
    def normalize_consumer_phone(cls, value: object) -> object:
        if isinstance(value, str):
            return re.sub(r"[\s-]", "", value.strip())
        return value

    model_config = {"extra": "forbid"}


class ProfileNameUpdateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)

    @field_validator("display_name", mode="before")
    @classmethod
    def trim_display_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    model_config = {"extra": "forbid"}


class MerchantProfileUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name", mode="before")
    @classmethod
    def trim_merchant_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    model_config = {"extra": "forbid"}


class DeviceTokenRegisterRequest(BaseModel):
    account_id: str = Field(min_length=8, max_length=80)
    fcm_token: str = Field(min_length=20, max_length=4096)
    platform: str = Field(pattern="^(android|ios)$")

    @field_validator("account_id", "fcm_token", mode="before")
    @classmethod
    def trim_values(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    model_config = {"extra": "forbid"}


class DeviceTokenDeleteRequest(BaseModel):
    fcm_token: str = Field(min_length=20, max_length=4096)

    @field_validator("fcm_token", mode="before")
    @classmethod
    def trim_token(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    model_config = {"extra": "forbid"}


class NotificationCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=1000)
    target_type: str = Field(pattern="^(all|voucher_only)$")
    idempotency_key: str = Field(min_length=16, max_length=100)
    expected_target_count: int = Field(ge=1)
    expected_device_count: int = Field(ge=1)

    @field_validator("title", "body", "idempotency_key", mode="before")
    @classmethod
    def trim_copy(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    model_config = {"extra": "forbid"}


class PaymentOrderCreateRequest(BaseModel):
    qr_token: str = Field(min_length=1, max_length=120)
    product_id: str = Field(min_length=8, max_length=80)


class PaymentConfirmRequest(BaseModel):
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
    kiwoom_pay_method: str = Field(default="TOTAL", pattern="^(TOTAL|BANK)$")
    image_url: str | None = Field(default=None, max_length=500)
    is_event: bool = False
    event_start_at: datetime | None = None
    event_end_at: datetime | None = None

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_event_period(self):
        if not self.is_event:
            return self
        if self.event_start_at is None or self.event_end_at is None:
            raise ValueError("이벤트 시작일시와 종료일시는 모두 필수예요")
        if self.event_start_at.tzinfo is None or self.event_end_at.tzinfo is None:
            raise ValueError("이벤트 일시는 시간대 정보가 필요해요")
        if self.event_end_at <= self.event_start_at:
            raise ValueError("이벤트 종료일시는 시작일시보다 늦어야 해요")
        return self


class VoucherProductUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    voucher_count: int | None = Field(default=None, gt=0, le=1000)
    bonus_count: int | None = Field(default=None, ge=0, le=1000)
    unit_price: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    discount_rate: Decimal | None = Field(default=None, ge=0, lt=100, max_digits=5, decimal_places=2)
    status: str | None = Field(default=None, pattern="^(active|inactive)$")
    display_order: int | None = Field(default=None, ge=-100000, le=100000)
    kiwoom_pay_method: str | None = Field(default=None, pattern="^(TOTAL|BANK)$")
    image_url: str | None = Field(default=None, max_length=500)
    is_event: bool | None = None
    event_start_at: datetime | None = None
    event_end_at: datetime | None = None

    @field_validator("name", "voucher_count", "bonus_count", "unit_price", "discount_rate", "status", "display_order", "kiwoom_pay_method", "is_event", mode="before")
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


class RefundReceiveAccount(BaseModel):
    bank: str = Field(min_length=2, max_length=20)
    accountNumber: str = Field(min_length=5, max_length=40)
    holderName: str = Field(min_length=1, max_length=60)
    model_config = {"extra": "forbid"}


class MerchantRefundRequest(BaseModel):
    account_id: str = Field(min_length=8, max_length=80)
    order_id: str = Field(min_length=8, max_length=80)
    refund_account: RefundReceiveAccount | None = None
    model_config = {"extra": "forbid"}


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
    phone: str | None = Field(default=None, pattern=r"^010\d{8}$")

    @field_validator("invite_code", "display_name", mode="before")
    @classmethod
    def trim_join_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("phone", mode="before")
    @classmethod
    def normalize_join_phone(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = re.sub(r"[\s-]", "", value.strip())
            return normalized or None
        return value

    model_config = {"extra": "forbid"}


class JoinDecisionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class EmployeeLimitUpdateRequest(BaseModel):
    monthly_limit: int = Field(ge=0, le=10000000)


class EmployeePointChargeRequest(BaseModel):
    amount: int = Field(gt=0, le=100000000)
    model_config = {"extra": "forbid"}


class EmployeePointAdjustRequest(BaseModel):
    target_balance: int = Field(ge=0, le=100000000)
    model_config = {"extra": "forbid"}


class EmployeeProfileUpdateRequest(BaseModel):
    employee_no: str | None = Field(default=None, max_length=40)
    department: str | None = Field(default=None, max_length=120)
    display_name: str = Field(min_length=1, max_length=80)
    phone: str | None = Field(default=None, max_length=40)
    model_config = {"extra": "forbid"}

    @field_validator("employee_no", "department", "display_name", "phone", mode="before")
    @classmethod
    def normalize_profile_field(cls, value: object) -> object:
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


class ImageDeleteRequest(BaseModel):
    image_url: str = Field(min_length=1, max_length=1000)


class PlatformMerchantCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    owner_phone: str | None = Field(default=None, max_length=40)
    category: str | None = Field(default=None, max_length=40)
    avg_price: int | None = Field(default=None, gt=0)


class InviteCreateRequest(BaseModel):
    phone: str = Field(min_length=5, max_length=40)


class InviteClaimRequest(BaseModel):
    # Deprecated compatibility field. Authenticated claims ignore it.
    auth_user_id: str | None = Field(default=None, min_length=8, max_length=80)
    display_name: str | None = Field(default=None, max_length=80)


class MerchantCompanyLinkRequest(BaseModel):
    company_id: str = Field(min_length=8, max_length=80)


class MerchantCompanyCreateAndLinkRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    contact_email: str = Field(min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    contact_phone: str | None = Field(default=None, max_length=40)
    # Legacy clients may continue sending this name.
    owner_phone: str | None = Field(default=None, max_length=40)


class SettlementPaymentConfirmRequest(BaseModel):
    paid_at: str = Field(min_length=8, max_length=40)


class SettlementCreateRequest(BaseModel):
    period_from: str = Field(min_length=10, max_length=10)
    period_to: str = Field(min_length=10, max_length=10)


class MerchantCompanyContractUpdateRequest(BaseModel):
    settlement_cycle: str = Field(pattern='^(month_end|day)$')
    settlement_day: int | None = Field(default=None, ge=1, le=31)
    unit_price: int | None = Field(default=None, ge=0)
