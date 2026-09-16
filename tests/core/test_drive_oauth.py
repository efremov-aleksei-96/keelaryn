from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "core"))

from keelaryn_core.drive_backend import DriveTransportError
from keelaryn_core.drive_oauth import GoogleOAuthRefreshTokenProvider, TOKEN_ENDPOINT
from keelaryn_core.drive_rest import HttpResponse


class Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class TokenHttp:
    def __init__(self, responses=None, error: Exception | None = None) -> None:
        self.responses = list(responses or [])
        self.error = error
        self.calls = []

    def request(self, method, url, *, headers, body=None):
        self.calls.append((method, url, dict(headers), body))
        if self.error is not None:
            raise self.error
        if not self.responses:
            raise AssertionError("unexpected token HTTP request")
        return self.responses.pop(0)


class DriveOAuthTests(unittest.TestCase):
    @staticmethod
    def token_response(token: str, expires_in=3600, *, status=200, token_type="Bearer"):
        import json

        return HttpResponse(
            status,
            {"Content-Type": "application/json"},
            json.dumps(
                {
                    "access_token": token,
                    "expires_in": expires_in,
                    "token_type": token_type,
                },
                separators=(",", ":"),
            ).encode("utf-8"),
        )

    def test_caches_then_refreshes_before_expiry(self) -> None:
        clock = Clock()
        http = TokenHttp([self.token_response("token-one"), self.token_response("token-two")])
        provider = GoogleOAuthRefreshTokenProvider(
            "client-id",
            "client-secret",
            "refresh-token",
            http=http,
            clock=clock,
            refresh_skew_seconds=60,
        )
        self.assertEqual(provider(), "token-one")
        self.assertEqual(len(http.calls), 1)
        clock.value = 3500
        self.assertEqual(provider(), "token-one")
        self.assertEqual(len(http.calls), 1)
        clock.value = 3540
        self.assertEqual(provider(), "token-two")
        self.assertEqual(len(http.calls), 2)
        method, url, headers, body = http.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, TOKEN_ENDPOINT)
        self.assertEqual(headers["Content-Type"], "application/x-www-form-urlencoded")
        text = body.decode("ascii")
        self.assertIn("grant_type=refresh_token", text)
        self.assertIn("client_id=client-id", text)
        self.assertIn("client_secret=client-secret", text)
        self.assertIn("refresh_token=refresh-token", text)

    def test_from_environment_requires_all_refresh_credentials(self) -> None:
        with self.assertRaises(DriveTransportError) as caught:
            GoogleOAuthRefreshTokenProvider.from_environment(
                {
                    "KEELARYN_GOOGLE_CLIENT_ID": "client-id",
                    "KEELARYN_GOOGLE_CLIENT_SECRET": "super-secret-value",
                }
            )
        message = str(caught.exception)
        self.assertIn("KEELARYN_GOOGLE_REFRESH_TOKEN", message)
        self.assertNotIn("super-secret-value", message)

    def test_from_environment_loads_without_exposing_secrets(self) -> None:
        http = TokenHttp([self.token_response("access")])
        provider = GoogleOAuthRefreshTokenProvider.from_environment(
            {
                "KEELARYN_GOOGLE_CLIENT_ID": "id-value",
                "KEELARYN_GOOGLE_CLIENT_SECRET": "secret-value",
                "KEELARYN_GOOGLE_REFRESH_TOKEN": "refresh-value",
            },
            http=http,
        )
        self.assertEqual(provider(), "access")
        self.assertNotIn("secret-value", repr(provider))
        self.assertNotIn("refresh-value", repr(provider))

    def test_network_failure_is_transport_error_without_secret_echo(self) -> None:
        provider = GoogleOAuthRefreshTokenProvider(
            "id-value",
            "secret-value",
            "refresh-value",
            http=TokenHttp(error=ConnectionError("socket down")),
        )
        with self.assertRaises(DriveTransportError) as caught:
            provider()
        message = str(caught.exception)
        self.assertNotIn("secret-value", message)
        self.assertNotIn("refresh-value", message)

    def test_http_error_and_malformed_success_are_rejected(self) -> None:
        bad_http = GoogleOAuthRefreshTokenProvider(
            "id",
            "secret",
            "refresh",
            http=TokenHttp([HttpResponse(400, {}, b'{"error":"invalid_grant"}')]),
        )
        with self.assertRaises(DriveTransportError):
            bad_http()

        malformed = GoogleOAuthRefreshTokenProvider(
            "id",
            "secret",
            "refresh",
            http=TokenHttp([HttpResponse(200, {}, b'{"access_token":"has space","expires_in":3600}')]),
        )
        with self.assertRaises(DriveTransportError):
            malformed()

    def test_invalid_token_type_or_expiry_is_rejected(self) -> None:
        wrong_type = GoogleOAuthRefreshTokenProvider(
            "id",
            "secret",
            "refresh",
            http=TokenHttp([self.token_response("access", token_type="MAC")]),
        )
        with self.assertRaises(DriveTransportError):
            wrong_type()

        bad_expiry = GoogleOAuthRefreshTokenProvider(
            "id",
            "secret",
            "refresh",
            http=TokenHttp([self.token_response("access", expires_in=0)]),
        )
        with self.assertRaises(DriveTransportError):
            bad_expiry()


if __name__ == "__main__":
    unittest.main(verbosity=2)
