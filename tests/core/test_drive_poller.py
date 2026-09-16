from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / "core"))
sys.path.insert(0, str(TESTS))

from drive_http_model import ModelDriveHttp
from keelaryn_core.drive_model import DriveModel
from keelaryn_core.drive_oauth import GoogleOAuthRefreshTokenProvider
from keelaryn_core.drive_poller import (
    DrivePoller,
    DrivePollerConfigError,
    DrivePollerResult,
    _token_source_from_environment,
)
from keelaryn_core.drive_rest import GoogleDriveBackend


class DrivePollerTests(unittest.TestCase):
    @staticmethod
    def fresh_backend():
        drive = DriveModel()
        hub = drive.create_folder("root", "Hub", label="setup.hub")
        backend = GoogleDriveBackend("test-access-token", http=ModelDriveHttp(drive))
        return drive, hub.file_id, backend

    def test_bootstrap_then_idle_once_uses_same_live_entry_layer(self) -> None:
        drive, hub_id, backend = self.fresh_backend()
        poller = DrivePoller(backend, hub_id)

        first = poller.bootstrap()
        self.assertEqual(first.kind, "bootstrap")
        self.assertEqual(first.phase, "INITIALIZED")
        self.assertTrue(first.ready_clean)

        second = poller.bootstrap()
        self.assertEqual(second.phase, "EXISTING")
        self.assertTrue(second.ready_clean)

        idle = poller.run_once()
        self.assertEqual(idle.kind, "service")
        self.assertEqual(idle.phase, "IDLE")
        self.assertTrue(idle.ready_clean)
        self.assertEqual(len(drive.list_children(hub_id, name="MASTER.json")), 1)

    def test_refresh_credentials_are_selected_for_continuous_service(self) -> None:
        source = _token_source_from_environment(
            "serve",
            {
                "KEELARYN_GOOGLE_CLIENT_ID": "client-id",
                "KEELARYN_GOOGLE_CLIENT_SECRET": "client-secret",
                "KEELARYN_GOOGLE_REFRESH_TOKEN": "refresh-token",
                "KEELARYN_GOOGLE_ACCESS_TOKEN": "static-token-ignored",
            },
        )
        self.assertIsInstance(source, GoogleOAuthRefreshTokenProvider)
        rendered = repr(source)
        self.assertNotIn("client-secret", rendered)
        self.assertNotIn("refresh-token", rendered)
        self.assertNotIn("static-token-ignored", rendered)

    def test_static_access_token_is_allowed_only_for_noncontinuous_commands(self) -> None:
        env = {"KEELARYN_GOOGLE_ACCESS_TOKEN": "static-token"}
        self.assertEqual(_token_source_from_environment("once", env), "static-token")
        self.assertEqual(_token_source_from_environment("bootstrap", env), "static-token")
        with self.assertRaises(DrivePollerConfigError) as caught:
            _token_source_from_environment("serve", env)
        self.assertNotIn("static-token", str(caught.exception))

    def test_missing_auth_reports_names_without_secret_values(self) -> None:
        env = {
            "KEELARYN_GOOGLE_CLIENT_ID": "client-id-value",
            "KEELARYN_GOOGLE_CLIENT_SECRET": "secret-value",
        }
        with self.assertRaises(DrivePollerConfigError) as caught:
            _token_source_from_environment("serve", env)
        message = str(caught.exception)
        self.assertIn("KEELARYN_GOOGLE_REFRESH_TOKEN", message)
        self.assertNotIn("client-id-value", message)
        self.assertNotIn("secret-value", message)

    def test_result_json_contains_status_only_not_hub_or_credentials(self) -> None:
        result = DrivePollerResult("service", "IDLE", "no work", True)
        raw = result.to_json()
        value = json.loads(raw)
        self.assertEqual(
            value,
            {
                "detail": "no work",
                "kind": "service",
                "phase": "IDLE",
                "ready_clean": True,
            },
        )
        self.assertNotIn("hub", raw.lower())
        self.assertNotIn("token", raw.lower())
        self.assertNotIn("credential", raw.lower())

    def test_invalid_hub_root_id_is_rejected_before_drive_access(self) -> None:
        _, _, backend = self.fresh_backend()
        for value in ("", "  ", " root "):
            with self.subTest(value=value):
                with self.assertRaises(DrivePollerConfigError):
                    DrivePoller(backend, value)

    def test_partial_refresh_configuration_does_not_fall_back_to_static_in_serve(self) -> None:
        env = {
            "KEELARYN_GOOGLE_CLIENT_ID": "client-id",
            "KEELARYN_GOOGLE_ACCESS_TOKEN": "static-token",
        }
        with self.assertRaises(DrivePollerConfigError) as caught:
            _token_source_from_environment("serve", env)
        self.assertIn("requires refresh credentials", str(caught.exception))
        self.assertNotIn("static-token", str(caught.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
