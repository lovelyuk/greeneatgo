from fastapi import APIRouter, HTTPException

from app.schemas import PayRequest

router = APIRouter(tags=["pay"])

@router.post("/pay")
def pay(_: PayRequest):
    # DB 트랜잭션 구현 전 안전장치: 실제 쓰기는 아직 비활성화.
    # 다음 단계에서 Supabase service_role + process_meal_pay SQL 함수로 연결한다.
    raise HTTPException(status_code=501, detail={"code": "NOT_IMPLEMENTED", "message": "결제 DB 트랜잭션 연결 전입니다"})
