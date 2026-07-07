from fastapi import FastAPI

from app.routers import admin, health, join, me, pay

app = FastAPI(title="greeneatGo API", version="0.1.0")
app.include_router(health.router, prefix="/v1")
app.include_router(pay.router, prefix="/v1")
app.include_router(me.router, prefix="/v1")
app.include_router(join.router, prefix="/v1")
app.include_router(admin.router, prefix="/v1")
