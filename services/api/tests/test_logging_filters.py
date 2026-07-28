import logging

from app.logging_filters import PaymentNotificationAccessLogFilter


def _record(path: str) -> logging.LogRecord:
    return logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("123.140.121.205:0", "GET", path, "1.1", 200),
        None,
    )


def test_payment_notification_access_log_filter_redacts_entire_query():
    record = _record(
        "/v1/payments/notification?CARDNO=5107370000008900&USERID=private"
    )

    assert PaymentNotificationAccessLogFilter().filter(record) is True

    rendered = record.getMessage()
    assert rendered == (
        '123.140.121.205:0 - "GET '
        '/v1/payments/notification?[REDACTED] HTTP/1.1" 200'
    )
    assert "CARDNO" not in rendered
    assert "5107370000008900" not in rendered
    assert "USERID" not in rendered


def test_payment_notification_access_log_filter_leaves_other_routes_unchanged():
    record = _record("/v1/health?detail=true")

    PaymentNotificationAccessLogFilter().filter(record)

    assert isinstance(record.args, tuple)
    assert record.args[2] == "/v1/health?detail=true"
