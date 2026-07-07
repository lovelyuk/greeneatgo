from fastapi import APIRouter, HTTPException

from app.schemas import JoinDecisionRequest

router = APIRouter(prefix="/admin", tags=["admin"])

@router.get("/join-requests")
def list_join_requests():
    # Supabase service_role repository 연결 전 계약 고정용 엔드포인트.
    raise HTTPException(status_code=501, detail={"code": "NOT_IMPLEMENTED", "message": "가입 요청 목록 DB 연결 전입니다"})

@router.post("/join-requests/{user_id}/approve")
def approve_join_request(user_id: str, _: JoinDecisionRequest | None = None):
    raise HTTPException(status_code=501, detail={"code": "NOT_IMPLEMENTED", "message": f"{user_id} 승인 DB 연결 전입니다"})

@router.post("/join-requests/{user_id}/reject")
def reject_join_request(user_id: str, payload: JoinDecisionRequest):
    if not payload.reason:
        raise HTTPException(status_code=400, detail={"code": "REASON_REQUIRED", "message": "거절 사유를 입력해 주세요"})
    raise HTTPException(status_code=501, detail={"code": "NOT_IMPLEMENTED", "message": f"{user_id} 거절 DB 연결 전입니다"})
