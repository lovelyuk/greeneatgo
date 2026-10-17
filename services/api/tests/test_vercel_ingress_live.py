"""Vercel-hosted verification of how the notification gate sees callers.

Not a test of production data: it hits only the public Vercel deployment and
asserts the gate rejects forged headers (no DB write happens before the gate).
Run manually: VERCEL_API=https://greeneatgo-api.vercel.app/v1 pytest tests/test_vercel_ingress_live.py
"""
import os
import urllib.error
import urllib.request

import pytest

BASE = os.environ.get("VERCEL_API")
pytestmark = pytest.mark.skipif(not BASE, reason="requires VERCEL_API")


def status(headers: dict[str, str]) -> int:
    req = urllib.request.Request(f"{BASE}/payments/notification?CPID=X", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return res.status
    except urllib.error.HTTPError as exc:
        return exc.code


@pytest.mark.parametrize("headers", [
    {},
    {"X-Forwarded-For": "27.102.213.200"},
    {"X-Real-IP": "27.102.213.200", "X-Vercel-Forwarded-For": "27.102.213.200"},
    {"X-Forwarded-For": "127.0.0.1", "X-Real-IP": "127.0.0.1"},
])
def test_forged_source_headers_never_pass_the_kiwoom_gate(headers):
    assert status(headers) == 403
