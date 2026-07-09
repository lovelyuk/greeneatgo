from pydantic import BaseModel, Field

class GPSPoint(BaseModel):
    lat: float
    lng: float

class PayRequest(BaseModel):
    qr_token: str
    amount: int = Field(gt=0)
    product_id: str | None = Field(default=None, max_length=80)
    gps: GPSPoint | None = None
    idempotency_key: str

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
    title: str = Field(default='오늘의 부페 메뉴', min_length=1, max_length=80)
    menu_text: str = Field(min_length=1, max_length=1000)
    is_active: bool = True


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


class MerchantCompanyContractUpdateRequest(BaseModel):
    settlement_cycle: str = Field(pattern='^(month_end|day)$')
    settlement_day: int | None = Field(default=None, ge=1, le=31)
    unit_price: int | None = Field(default=None, ge=0)
