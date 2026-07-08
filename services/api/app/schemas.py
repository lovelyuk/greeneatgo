from pydantic import BaseModel, Field

class GPSPoint(BaseModel):
    lat: float
    lng: float

class PayRequest(BaseModel):
    qr_token: str
    amount: int = Field(gt=0)
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
