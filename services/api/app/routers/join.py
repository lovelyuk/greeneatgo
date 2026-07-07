from fastapi import APIRouter, HTTPException

from app.schemas import JoinRequest

router = APIRouter(tags=["join"])

@router.post("/join/request")
def request_join(_: JoinRequest):
    # DB 연결 전 안전장치. 다음 단계에서 service_role 저장소에 연결한다.
    raise HTTPException(status_code=501, detail={"code": "NOT_IMPLEMENTED", "message": "초대코드 가입요청 DB 연결 전입니다"})
