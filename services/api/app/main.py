from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings

from app.routers import admin, auth_pages, consumer, health, invites, join, me, merchant_admin, pay, platform, products, push_notifications, toss_payments, transactions, voucher_products

settings = get_settings()

app = FastAPI(title="greeneatGo API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_allowed_origins),
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health.router, prefix="/v1")
app.include_router(auth_pages.router, prefix="/v1")
app.include_router(pay.router, prefix="/v1")
app.include_router(products.router, prefix="/v1")
app.include_router(consumer.router, prefix="/v1")
app.include_router(toss_payments.router, prefix="/v1")
app.include_router(voucher_products.router, prefix="/v1")
app.include_router(transactions.router, prefix="/v1")
app.include_router(push_notifications.router, prefix="/v1")
app.include_router(me.router, prefix="/v1")
app.include_router(join.router, prefix="/v1")
app.include_router(admin.router, prefix="/v1")
app.include_router(platform.router, prefix="/v1")
app.include_router(invites.router, prefix="/v1")
app.include_router(merchant_admin.router, prefix="/v1")
