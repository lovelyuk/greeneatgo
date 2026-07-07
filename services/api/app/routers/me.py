from fastapi import APIRouter, Header, HTTPException

router = APIRouter(tags=["me"])

@router.get("/me")
def me(x_user_id: str | None = Header(default=None)):
    # Supabase JWT 검증 연결 전 임시 계약 엔드포인트.
    # 실제 구현은 Authorization: Bearer <jwt>에서 user_id를 검증하고 app_users.company_id를 조회한다.
    if not x_user_id:
        raise HTTPException(status_code=401, detail={"code": "UNAUTHENTICATED", "message": "로그인이 필요해요"})
    return {
        "ok": True,
        "data": {
            "user_id": x_user_id,
            "status": "stub",
            "message": "Supabase Auth 연결 후 company_id/status/balance를 반환합니다",
        },
        "error": None,
    }
