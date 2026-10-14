"""Temporary, source-controlled ingress guard for the failed-order cutover.

Keep enabled through the finalize release and process drain / migration 0064.
Disable in a separate reviewed release by changing only the constant below.
This does not drain in-flight requests or replace the migration runbook.
"""
import re

from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

CHECKOUT_MAINTENANCE_ENABLED = True

# Match only the payable routes audited at d9aacd5, including slash redirects.
# ASGI path is already decoded; never unquote again, parse a raw URI, or inspect
# query strings. In particular, checkout tokens are exactly one route segment.
_PAYABLE_PATH = re.compile(
    r"/v1/(?:vouchers/(?:purchase|purchase-subsidized)|payments/checkout/[^/]+)/?"
)


class CheckoutMaintenanceMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            CHECKOUT_MAINTENANCE_ENABLED
            and scope["type"] == "http"
            and scope["method"] != "OPTIONS"
            and _PAYABLE_PATH.fullmatch(scope["path"]) is not None
        ):
            headers = {"Retry-After": "60", "Cache-Control": "no-store"}
            if scope["method"] == "HEAD":
                response = Response(status_code=503, headers=headers)
            else:
                response = JSONResponse(
                    {"detail": {"code": "CHECKOUT_MAINTENANCE",
                                "message": "결제 점검 중이에요. 잠시 후 다시 시도해 주세요."}},
                    status_code=503, headers=headers,
                )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
