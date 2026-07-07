from fastapi import APIRouter

router = APIRouter(tags=["health"])

@router.get("/health")
def health():
    return {"ok": True, "data": {"service": "mealledger-api"}, "error": None}
