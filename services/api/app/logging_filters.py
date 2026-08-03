from __future__ import annotations

import logging


class PaymentNotificationAccessLogFilter(logging.Filter):
    """Redact Kiwoom callback query strings before Uvicorn formats a log line."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) < 3:
            return True
        path = str(args[2])
        if "/payments/notification?" not in path and "/auth/phone/" not in path:
            return True
        if "?" not in path:
            return True
        redacted = list(args)
        redacted[2] = f"{path.split('?', 1)[0]}?[REDACTED]"
        record.args = tuple(redacted)
        return True


def install_payment_notification_access_log_filter() -> None:
    logger = logging.getLogger("uvicorn.access")
    if any(isinstance(item, PaymentNotificationAccessLogFilter) for item in logger.filters):
        return
    logger.addFilter(PaymentNotificationAccessLogFilter())
