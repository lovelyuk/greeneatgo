from fastapi import FastAPI

from app.routers import health, pay

app = FastAPI(title="greeneatGo API", version="0.1.0")
app.include_router(health.router, prefix="/v1")
app.include_router(pay.router, prefix="/v1")
