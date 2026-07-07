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
