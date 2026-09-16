from __future__ import annotations

import os
import time
from typing import Callable, Mapping
from urllib.parse import urlencode

from .drive_backend import DriveTransportError
from .drive_rest import HttpClient, UrllibHttpClient
from .protocol import strict_json_bytes


TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"


class GoogleOAuthRefreshTokenProvider:
    """Callable access-token source backed by a Google OAuth refresh token.

    Secrets are retained only in process memory. The provider performs one token
    request when refresh is required and never logs or exposes credential values.
    Drive mutation retry semantics remain entirely outside this class.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        *,
        http: HttpClient | None = None,
        clock: Callable[[], float] | None = None,
        refresh_skew_seconds: float = 60.0,
    ) -> None:
        self._client_id = self._secret(client_id, "client_id")
        self._client_secret = self._secret(client_secret, "client_secret")
        self._refresh_token = self._secret(refresh_token, "refresh_token")
        if refresh_skew_seconds < 0:
            raise ValueError("refresh_skew_seconds must be non-negative")
        self.http = http or UrllibHttpClient()
        self.clock = clock or time.monotonic
        self.refresh_skew_seconds = float(refresh_skew_seconds)
        self._access_token: str | None = None
        self._expires_at = 0.0

    @staticmethod
    def _secret(value: str, label: str) -> str:
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError(f"{label} must be a non-empty trimmed string")
        if "\x00" in value or "\r" in value or "\n" in value:
            raise ValueError(f"{label} contains invalid control characters")
        return value

    @classmethod
    def from_environment(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        http: HttpClient | None = None,
        clock: Callable[[], float] | None = None,
        refresh_skew_seconds: float = 60.0,
    ) -> "GoogleOAuthRefreshTokenProvider":
        source = os.environ if env is None else env
        names = {
            "client_id": "KEELARYN_GOOGLE_CLIENT_ID",
            "client_secret": "KEELARYN_GOOGLE_CLIENT_SECRET",
            "refresh_token": "KEELARYN_GOOGLE_REFRESH_TOKEN",
        }
        missing = [env_name for env_name in names.values() if not source.get(env_name)]
        if missing:
            raise DriveTransportError(
                "missing Google OAuth environment variables: " + ", ".join(sorted(missing))
            )
        return cls(
            source[names["client_id"]],
            source[names["client_secret"]],
            source[names["refresh_token"]],
            http=http,
            clock=clock,
            refresh_skew_seconds=refresh_skew_seconds,
        )

    def _refresh(self) -> str:
        body = urlencode(
            {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": self._refresh_token,
                "grant_type": "refresh_token",
            }
        ).encode("ascii")
        try:
            response = self.http.request(
                "POST",
                TOKEN_ENDPOINT,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                body=body,
            )
        except Exception as exc:
            raise DriveTransportError("Google OAuth token refresh request failed") from exc
        if not (200 <= response.status < 300):
            raise DriveTransportError(f"Google OAuth token refresh returned HTTP {response.status}")
        try:
            value = strict_json_bytes(response.body, label="GOOGLE_OAUTH_TOKEN")
        except Exception as exc:
            raise DriveTransportError("Google OAuth token response is not valid JSON") from exc
        if not isinstance(value, dict):
            raise DriveTransportError("Google OAuth token response must be an object")
        token = value.get("access_token")
        expires_in = value.get("expires_in")
        token_type = value.get("token_type", "Bearer")
        if not isinstance(token, str) or not token or any(ch.isspace() for ch in token):
            raise DriveTransportError("Google OAuth token response has invalid access_token")
        if not isinstance(expires_in, (int, float)) or isinstance(expires_in, bool) or expires_in <= 0:
            raise DriveTransportError("Google OAuth token response has invalid expires_in")
        if not isinstance(token_type, str) or token_type.lower() != "bearer":
            raise DriveTransportError("Google OAuth token response has unsupported token_type")
        now = self.clock()
        self._access_token = token
        self._expires_at = now + float(expires_in)
        return token

    def __call__(self) -> str:
        now = self.clock()
        if self._access_token is None or now + self.refresh_skew_seconds >= self._expires_at:
            return self._refresh()
        return self._access_token


__all__ = ["GoogleOAuthRefreshTokenProvider", "TOKEN_ENDPOINT"]
