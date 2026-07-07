from __future__ import annotations

from fastapi import Header, HTTPException


def bearer_token(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail={"code": "UNAUTHENTICATED", "message": "로그인이 필요해요"})
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail={"code": "UNAUTHENTICATED", "message": "로그인이 필요해요"})
    return token
