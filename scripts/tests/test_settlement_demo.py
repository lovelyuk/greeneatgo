from __future__ import annotations

import importlib.util
import io
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading
import unittest
from unittest import mock


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "settlement_demo.py"
SPEC = importlib.util.spec_from_file_location("settlement_demo", SCRIPT_PATH)
assert SPEC and SPEC.loader
settlement_demo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(settlement_demo)


class _RecordingRedirectHandler(BaseHTTPRequestHandler):
    requests: list[tuple[str, str | None]]
    redirect_url: str

    def do_POST(self) -> None:
        self.requests.append((self.path, self.headers.get("Authorization")))
        self.send_response(302)
        self.send_header("Location", self.redirect_url)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass


class _RecordingTargetHandler(BaseHTTPRequestHandler):
    requests: list[tuple[str, str | None]]

    def do_GET(self) -> None:
        self.requests.append((self.path, self.headers.get("Authorization")))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")

    do_POST = do_GET

    def log_message(self, format: str, *args: object) -> None:
        pass


class SettlementDemoTransportTests(unittest.TestCase):
    def test_url_transport_policy(self) -> None:
        for url in (
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://[::1]:8000",
            "https://api.example.com",
        ):
            with self.subTest(url=url):
                settlement_demo._validate_api_url(url)

        for url in (
            "http://api.example.com",
            "http://127.0.0.2:8000",
            "ftp://api.example.com",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    settlement_demo._validate_api_url(url)

    def test_redirects_are_not_followed_or_given_authorization(self) -> None:
        target_requests: list[tuple[str, str | None]] = []
        target_handler = type(
            "TargetHandler",
            (_RecordingTargetHandler,),
            {"requests": target_requests},
        )
        target = ThreadingHTTPServer(("127.0.0.1", 0), target_handler)
        target_thread = threading.Thread(target=target.serve_forever, daemon=True)
        target_thread.start()

        try:
            for destination in ("same-origin", "cross-origin"):
                with self.subTest(destination=destination):
                    source_requests: list[tuple[str, str | None]] = []
                    source_handler = type(
                        "SourceHandler",
                        (_RecordingRedirectHandler,),
                        {"requests": source_requests, "redirect_url": ""},
                    )
                    source = ThreadingHTTPServer(("127.0.0.1", 0), source_handler)
                    source_url = f"http://127.0.0.1:{source.server_port}"
                    source_handler.redirect_url = (
                        f"{source_url}/redirected"
                        if destination == "same-origin"
                        else f"http://127.0.0.1:{target.server_port}/redirected"
                    )
                    source_thread = threading.Thread(target=source.serve_forever, daemon=True)
                    source_thread.start()
                    try:
                        argv = ["settlement_demo.py", "reset", "--api-url", source_url]
                        with mock.patch.object(sys, "argv", argv), mock.patch.dict(
                            os.environ,
                            {"SETTLEMENT_DEMO_TOKEN": "secret-token"},
                            clear=True,
                        ), mock.patch("sys.stderr", new_callable=io.StringIO):
                            self.assertEqual(settlement_demo.main(), 1)

                        self.assertEqual(len(source_requests), 1)
                        self.assertEqual(source_requests[0][1], "Bearer secret-token")
                        self.assertNotEqual(source_requests[0][0], "/redirected")
                        self.assertEqual(target_requests, [])
                    finally:
                        source.shutdown()
                        source.server_close()
                        source_thread.join()
        finally:
            target.shutdown()
            target.server_close()
            target_thread.join()


if __name__ == "__main__":
    unittest.main()