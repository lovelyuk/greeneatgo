#!/usr/bin/env python3
"""Seed or reset the merchant settlement demo through the authenticated API.

Examples:
  SETTLEMENT_DEMO_TOKEN=... python3 scripts/settlement_demo.py seed --company-id UUID --period-ym 2026-06
  SETTLEMENT_DEMO_TOKEN=... SETTLEMENT_DEMO_API_URL=https://api.example python3 scripts/settlement_demo.py reset

No credentials are stored by this script. The token must identify an active
merchant_admin and is sent only to the configured API origin.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


_HTTP_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects so the bearer token is never replayed to another URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _validate_api_url(api_url: str) -> None:
    """Require HTTPS, except for explicitly supported local development hosts."""
    try:
        parsed = urllib.parse.urlsplit(api_url)
        hostname = parsed.hostname
        # Accessing port also validates malformed/non-numeric port values.
        parsed.port
    except ValueError as exc:
        raise ValueError(f"invalid API URL: {exc}") from exc

    if parsed.scheme not in {"http", "https"} or not hostname:
        raise ValueError("API URL must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("API URL must not contain credentials")
    if parsed.scheme == "http" and hostname.lower() not in _HTTP_LOOPBACK_HOSTS:
        raise ValueError("API URL must use HTTPS unless the host is localhost, 127.0.0.1, or [::1]")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("seed", "reset"))
    parser.add_argument("--api-url", default=os.getenv("SETTLEMENT_DEMO_API_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--company-id")
    parser.add_argument("--period-ym")
    args = parser.parse_args()
    token = os.getenv("SETTLEMENT_DEMO_TOKEN")
    if not token:
        parser.error("SETTLEMENT_DEMO_TOKEN must be set in the environment")
    if args.action == "seed" and (not args.company_id or not args.period_ym):
        parser.error("seed requires --company-id and --period-ym")
    try:
        _validate_api_url(args.api_url)
    except ValueError as exc:
        parser.error(str(exc))
    url = f"{args.api_url.rstrip('/')}/v1/admin/merchant/settlement-demo/{args.action}"
    payload = ({"company_id": args.company_id, "period_ym": args.period_ym}
               if args.action == "seed" else {})
    request = urllib.request.Request(
        url, method="POST", data=json.dumps(payload).encode("utf-8"), headers={
            "Authorization": f"Bearer {token}", "Accept": "application/json",
            "Content-Type": "application/json",
            **({"Idempotency-Key": os.environ["SETTLEMENT_DEMO_IDEMPOTENCY_KEY"]}
               if args.action == "reset" and os.getenv("SETTLEMENT_DEMO_IDEMPOTENCY_KEY") else {}),
        }
    )
    try:
        opener = urllib.request.build_opener(_NoRedirectHandler())
        with opener.open(request, timeout=30) as response:
            body = json.load(response)
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8", "replace"), file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"settlement demo API unavailable: {exc.reason}", file=sys.stderr)
        return 1
    print(json.dumps(body, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
