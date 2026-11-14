"""Optional Telegram failure notification for the MCP-owned ArmenianLearning backup.

Triggered ONLY by systemd OnFailure of the backup oneshot. No neural network,
ChatGPT or extra Python libraries. No success messages, canonical data, paths,
Drive IDs, host IPs, bearer URLs or secrets are sent. Without verified root-only
configuration, journal reports UNCONFIGURED and no remote request is made.

Telegram credentials must be installed separately and securely by the owner
at /etc/keelaryn-drive-backup/telegram-notifier.json (root:root, 0600).
The config references a separately secured root-only token file; it does not
duplicate the bot token. Run 'setup' only after the user started the new bot.
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
TOKEN_FILE = Path("/etc/keelaryn-drive-backup/telegram-bot-token")
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


def _private_dir(path):
    st = path.lstat()
    if not (stat.S_ISDIR(st.st_mode) and st.st_uid == 0
            and st.st_gid == 0 and stat.S_IMODE(st.st_mode) == 0o700):
        raise NotifyError("Unsafe notifier directory")


def _secret_token(path=TOKEN_FILE):
    _private_dir(path.parent)
    st = path.lstat()
    if not (stat.S_ISREG(st.st_mode) and st.st_uid == 0 and st.st_gid == 0
            and st.st_nlink == 1 and stat.S_IMODE(st.st_mode) == 0o600
            and 0 < st.st_size < 500):
        raise NotifyError("Unsafe bot token file")
    with path.open("rb") as stream:
        raw = stream.read(500)
    try:
        token = raw.decode("ascii").strip()
    except UnicodeDecodeError:
        raise NotifyError("Invalid bot token format") from None
    if not TOKEN_PATTERN.fullmatch(token):
        raise NotifyError("Invalid bot token format")
    return token


def _secure_config(path=CONFIG, *, token_file=TOKEN_FILE):
    _private_dir(path.parent)
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
    if not isinstance(conf, dict) or set(conf) != {"schema", "token_file", "chat_id"}:
        raise NotifyError("Unexpected notifier configuration fields")
    chat_id = conf.get("chat_id")
    if (conf["schema"] != SCHEMA
            or conf.get("token_file") != str(token_file)
            or type(chat_id) is not int or not (0 < chat_id < 10**17)):
        raise NotifyError("Invalid notifier configuration values")
    return {"token": _secret_token(token_file), "chat_id": chat_id}


def _telegram_read(token, method, *, opener=None):
    """Official read-only Bot API; restrict response and suppress token-bearing errors."""
    if method not in ("getMe", "getUpdates"):
        raise NotifyError("Unsupported Telegram read")
    url = "https://api.telegram.org/bot" + token + "/" + method
    req = urllib.request.Request(url, method="GET")
    opener = opener or urllib.request.build_opener(
        urllib.request.ProxyHandler({}), NoRedirect()
    )
    try:
        with opener.open(req, timeout=15) as response:
            if response.status != 200:
                raise NotifyError("Telegram read failed")
            raw = response.read(65537)
        if len(raw) > 65536:
            raise NotifyError("Telegram response oversized")
        obj = json.loads(raw)
        if not isinstance(obj, dict) or obj.get("ok") is not True:
            raise NotifyError("Telegram response not confirmed")
        return obj.get("result")
    except Exception:
        raise NotifyError("Telegram response unavailable or uncertain") from None


def _private_start_chat(updates):
    """Require exactly one chat with a fresh /start; never guess a recipient."""
    if not isinstance(updates, list) or len(updates) > 100:
        raise NotifyError("Unexpected Telegram update list")
    candidates = set()
    for update in updates:
        if not isinstance(update, dict):
            continue
        msg = update.get("message")
        if not isinstance(msg, dict):
            continue
        chat = msg.get("chat")
        if not isinstance(chat, dict) or chat.get("type") != "private":
            continue
        cid = chat.get("id")
        txt = msg.get("text")
        if (type(cid) is int and 0 < cid < 10**17
                and isinstance(txt, str) and
                (txt == "/start" or txt.startswith("/start "))):
            candidates.add(cid)
    if len(candidates) != 1:
        raise NotifyError("A unique private start message is required")
    return candidates.pop()


def _write_config(chat_id, *, path=CONFIG, token_file=TOKEN_FILE):
    _private_dir(path.parent)
    if path.exists() or path.is_symlink():
        existing = _secure_config(path, token_file=token_file)
        if existing is not None and existing["chat_id"] == chat_id:
            return "already_configured"
        raise NotifyError("Notifier config already exists with different recipient")
    data = (json.dumps({"schema": SCHEMA, "token_file": str(token_file),
                        "chat_id": chat_id}, separators=(",", ":")) + "\n").encode()
    # Hard-link creation is exclusive: cannot overwrite an existing config.
    fd, tempname = tempfile.mkstemp(prefix=".telegram-notifier-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(tempname, path, follow_symlinks=False)
        parentfd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parentfd)
        finally:
            os.close(parentfd)
    finally:
        os.unlink(tempname)
    if _secure_config(path, token_file=token_file)["chat_id"] != chat_id:
        raise NotifyError("Notifier config could not be verified")
    return "configured"


def _setup():
    """Provision only one verified private chat; never print IDs or credentials."""
    token = _secret_token()
    bot = _telegram_read(token, "getMe")
    if not (isinstance(bot, dict) and bot.get("is_bot") is True
            and isinstance(bot.get("username"), str)):
        raise NotifyError("Bot token was not verified by Telegram")
    cid = _private_start_chat(_telegram_read(token, "getUpdates"))
    state = _write_config(cid)
    return {"status": state, "telegram_bot": "verified",
            "private_chat": "unique_start_verified",
            "delivery": "not_tested"}


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
        def __init__(self, response):
            self.response = response
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size): return self.response[:size]
    class FakeOpener:
        def open(self, request, timeout):
            assert request.get_method() == "POST"
            assert request.full_url.startswith("https://api.telegram.org/bot")
            assert "chat_id" in json.loads(request.data)
            assert json.loads(request.data)["text"] in (MESSAGE, TEST_MESSAGE)
            return FakeReply(b'{"ok":true}')
    _send("123456:abcdefghijklmnopqrstuvwxyzABCDEF012345", 123, opener=FakeOpener())
    _send("123456:abcdefghijklmnopqrstuvwxyzABCDEF012345", 123,
          opener=FakeOpener(), message=TEST_MESSAGE)
    starts = [{"message":{"chat":{"id":123,"type":"private"},"text":"/start"}}]
    assert _private_start_chat(starts) == 123
    try:
        _private_start_chat(starts + [{
            "message":{"chat":{"id":456,"type":"private"},"text":"/start"}}])
        raise AssertionError("Ambiguous private recipients accepted")
    except NotifyError:
        pass
    with tempfile.TemporaryDirectory(prefix="keelaryn-notify-mock-") as folder:
        os.chmod(folder, 0o700)
        root = Path(folder)
        path = root / "config.json"
        tokenfile = root / "bot-token"
        tokenfile.write_text("123456:abcdefghijklmnopqrstuvwxyzABCDEF012345\n")
        tokenfile.chmod(0o600)
        assert _secure_config(path, token_file=tokenfile) is None
        assert _write_config(123, path=path, token_file=tokenfile) == "configured"
        assert _secure_config(path, token_file=tokenfile)["chat_id"] == 123
        assert _write_config(123, path=path, token_file=tokenfile) == "already_configured"
        path.chmod(0o644)
        try:
            _secure_config(path, token_file=tokenfile)
            raise AssertionError("Unsafe credentials accepted")
        except NotifyError:
            pass
    return {"status":"selftest_passed",
            "tests":["telegram_post_mocked","test_message_distinct",
                     "unique_private_start","ambiguous_private_start_rejected",
                     "missing_config_no_network","private_config_created",
                     "idempotent_config","unsafe_config_rejected"]}



def main(argv):
    if argv == ["selftest"]:
        try:
            print(json.dumps(_selftest(), sort_keys=True))
            return 0
        except Exception:
            print('{"status":"selftest_failed"}')
            return 1
    if argv not in (["send"], ["test"], ["setup"]):
        print('{"status":"invalid_usage"}')
        return 2
    if os.geteuid() != 0:
        print('{"status":"failed","reason":"requires_root"}')
        return 1
    try:
        if argv == ["setup"]:
            print(json.dumps(_setup(), sort_keys=True))
            return 0
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
