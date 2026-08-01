from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.logging_filters import install_payment_notification_access_log_filter

from app.routers import admin, auth_pages, boards, company_usage, consumer, coupons, health, invites, join, me, merchant_admin, pay, payments, platform, products, push_notifications, settlements, transactions, voucher_products

settings = get_settings()
install_payment_notification_access_log_filter()

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
app.include_router(payments.router, prefix="/v1")
app.include_router(payments.short_redirect_router)
app.include_router(voucher_products.router, prefix="/v1")
app.include_router(transactions.router, prefix="/v1")
app.include_router(push_notifications.router, prefix="/v1")
app.include_router(boards.router, prefix="/v1")
app.include_router(coupons.router, prefix="/v1")
app.include_router(me.router, prefix="/v1")
app.include_router(join.router, prefix="/v1")
app.include_router(admin.router, prefix="/v1")
app.include_router(company_usage.router, prefix="/v1")
app.include_router(platform.router, prefix="/v1")
app.include_router(invites.router, prefix="/v1")
app.include_router(merchant_admin.router, prefix="/v1")
app.include_router(settlements.company_router, prefix="/v1")
app.include_router(settlements.company_alias_router, prefix="/v1")
app.include_router(settlements.merchant_router, prefix="/v1")
app.include_router(settlements.generation_router, prefix="/v1")
