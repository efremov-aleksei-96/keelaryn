#!/usr/bin/env python3
"""Isolated, opt-in read-only Google Drive OAuth for bulk staging.

Never shares refresh tokens with the existing drive.file backup workflow.
No migration, source mutation, or service activation is performed here.
"""
import json
import os
import stat
import sys
from pathlib import Path

import drive_device_auth as oauth

AUTH_ROOT = Path("/var/lib/keelaryn-drive-bulk-readonly")
READ_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
AUTH_SCHEMA = "keelaryn-drive-oauth-device-bulk-readonly-v1"


def configure():
    if os.geteuid() != 0:
        raise ValueError("Root-only OAuth operation")
    AUTH_ROOT.mkdir(mode=0o700, exist_ok=True)
    info = AUTH_ROOT.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0
            or info.st_gid != 0 or stat.S_IMODE(info.st_mode) != 0o700):
        raise ValueError("Unsafe OAuth state directory")
    oauth.STATE = AUTH_ROOT
    oauth.SCOPE = READ_SCOPE
    oauth.SCHEMA = AUTH_SCHEMA


def fresh_reader():
    """For a separately authorized importer; never return in stdout."""
    configure()
    return oauth.fresh_access_token()


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in (
            "status", "start", "poll", "refresh-check"):
        raise ValueError("Use status, start, poll or refresh-check")
    mode = sys.argv[1]
    configure()
    if mode == "status":
        path = AUTH_ROOT / "refresh-token.json"
        result = {"status": "authorized" if path.exists() else "not_authorized",
                  "scope": READ_SCOPE}
    elif mode == "start":
        result = oauth.start()
    elif mode == "poll":
        result = oauth.poll()
    else:
        token = oauth.fresh_access_token()
        result = {"status": "authorized_refresh_valid" if token else "failed"}
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # No secret, HTTP error, server body, or credential path in output.
        print('{"status":"blocked","message":"Read-only OAuth unavailable; existing backup untouched"}')
        sys.exit(1)
