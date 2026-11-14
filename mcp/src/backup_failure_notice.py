"""Optional Telegram failure notification for the MCP-owned ArmenianLearning backup.

Triggered ONLY by systemd OnFailure of the backup oneshot. No neural network,
ChatGPT or extra Python libraries. No success messages, canonical data, paths,
Drive IDs, host IPs, bearer URLs or secrets are sent. Without verified root-only
configuration, journal reports UNCONFIGURED and no remote request is made.

Telegram credentials must be installed separately and securely by the owner
at /etc/keelaryn-drive-backup/telegram-notifier.json (root:root, 0600):
 {"schema":"keelaryn-telegram-failure-v1","token":"<bot token>","chat_id":123}
Do not put credentials in GitHub, shell history, ChatGPT, or this source file.
"""
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import urllib.request

CONFIG = Path("/etc/keelaryn-drive-backup/telegram-notifier.json")
SCHEMA = "keelaryn-telegram-failure-v1"
MESSAGE = (
    "KeelarynOS backup FAILED. "
    "Check VPS journal: keelarynos-mcp-armenianlearning-backup.service"
)
TEST_MESSAGE = "KeelarynOS backup alert TEST. No backup failed."
TOKEN_PATTERN = re.compile(r"[0-9]{5,20}:[A-Za-z0-9_-]{30,100}\Z")


class NotifyError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise NotifyError("Telegram redirect refused")


def _secure_config(path=CONFIG):
    parent = path.parent.lstat()
    if not (stat.S_ISDIR(parent.st_mode) and parent.st_uid == 0
            and stat.S_IMODE(parent.st_mode) == 0o700):
        raise NotifyError("Unsafe notifier configuration directory")
    try:
        st = path.lstat()
    except FileNotFoundError:
        return None
    if not (stat.S_ISREG(st.st_mode) and st.st_uid == 0 and st.st_gid == 0
            and st.st_nlink == 1 and stat.S_IMODE(st.st_mode) == 0o600
            and 0 < st.st_size <= 4096):
        raise NotifyError("Unsafe notifier configuration file")
    with path.open("rb") as fd:
        data = fd.read(4097)
    try:
        conf = json.loads(data)
    except (ValueError, UnicodeError):
        raise NotifyError("Invalid notifier configuration") from None
    if not isinstance(conf, dict) or set(conf) != {"schema", "token", "chat_id"}:
        raise NotifyError("Unexpected notifier configuration fields")
    token, chat_id = conf.get("token"), conf.get("chat_id")
    if (conf["schema"] != SCHEMA or not isinstance(token, str)
            or not TOKEN_PATTERN.fullmatch(token)
            or type(chat_id) is not int or not (0 < chat_id < 10**17)):
        raise NotifyError("Invalid notifier configuration values")
    return {"token": token, "chat_id": chat_id}


def _send(token, chat_id, *, opener=None, message=MESSAGE):
    """One bounded HTTPS attempt. No sensitive data in logs or exceptions."""
    url = "https://api.telegram.org/bot" + token + "/sendMessage"
    payload = json.dumps(
        {"chat_id": chat_id, "text": message, "disable_notification": False},
        separators=(",", ":")
    ).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Content-Type": "application/json"}
    )
    opener = opener or urllib.request.build_opener(
        urllib.request.ProxyHandler({}), NoRedirect()
    )
    try:
        with opener.open(req, timeout=15) as response:
            if response.status != 200:
                raise NotifyError("Telegram delivery failed")
            raw = response.read(8193)
        if len(raw) > 8192 or json.loads(raw).get("ok") is not True:
            raise NotifyError("Telegram delivery not acknowledged")
    except Exception:
        # Do not leak the token-bearing request URL, provider payload or
        # exception text to systemd/journald. Unknown outcome means not proven.
        raise NotifyError("Telegram delivery unavailable or uncertain") from None


def _selftest():
    class FakeReply:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size): return b'{"ok":true}'
    class FakeOpener:
        def open(self, request, timeout):
            assert request.get_method() == "POST"
            assert request.full_url.startswith("https://api.telegram.org/bot")
            assert "chat_id" in json.loads(request.data)
            assert json.loads(request.data)["text"] in (MESSAGE, TEST_MESSAGE)
            return FakeReply()
    _send("123456:abcdefghijklmnopqrstuvwxyzABCDEF012345", 123, opener=FakeOpener())
    _send("123456:abcdefghijklmnopqrstuvwxyzABCDEF012345", 123,
          opener=FakeOpener(), message=TEST_MESSAGE)
    with tempfile.TemporaryDirectory(prefix="keelaryn-notify-mock-") as folder:
        os.chmod(folder, 0o700)
        path = Path(folder) / "config.json"
        assert _secure_config(path) is None
        content = json.dumps({"schema": SCHEMA,
                              "token": "123456:abcdefghijklmnopqrstuvwxyzABCDEF012345",
                              "chat_id": 123})
        path.write_text(content, encoding="utf8")
        os.chmod(path, 0o600)
        assert _secure_config(path)["chat_id"] == 123
        os.chmod(path, 0o644)
        try:
            _secure_config(path)
        except NotifyError: pass
        else: raise AssertionError("Unsafe credentials accepted")
    return {"status":"selftest_passed",
            "tests":["telegram_post_mocked","test_message_distinct",
                     "missing_config_no_network",
                     "private_config_accepted","unsafe_config_rejected"]}


def main(argv):
    if argv == ["selftest"]:
        try:
            print(json.dumps(_selftest(), sort_keys=True))
            return 0
        except Exception:
            print('{"status":"selftest_failed"}')
            return 1
    if argv not in (["send"], ["test"]):
        print('{"status":"invalid_usage"}')
        return 2
    if os.geteuid() != 0:
        print('{"status":"failed","reason":"requires_root"}')
        return 1
    try:
        conf = _secure_config()
        if conf is None:
            print('{"status":"not_configured","delivery":"none","channel":"telegram"}')
            return 3
        _send(conf["token"], conf["chat_id"],
              message=TEST_MESSAGE if argv == ["test"] else MESSAGE)
        print(json.dumps({"status":"sent","delivery":"telegram_api_acknowledged",
                          "kind":"test" if argv == ["test"] else "failure"}))
        return 0
    except NotifyError:
        print('{"status":"failed","delivery":"unconfirmed","channel":"telegram"}')
        return 1
    except Exception:
        print('{"status":"failed","delivery":"unconfirmed","channel":"telegram"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
