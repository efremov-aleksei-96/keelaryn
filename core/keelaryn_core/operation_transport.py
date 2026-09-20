from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .operation_request import OperationRequest, parse_operation_request
from .operation_runtime import OperationRuntimeError


REQUEST_MARKER = "KEELARYN_OPERATION_REQUEST_V1\n"
STATUS_MARKER = "KEELARYN_OPERATION_STATUS_V1\n"
TRANSPORT_STATE_SCHEMA = "keelaryn.github-operation-transport-state.v1"
RELAY_SCHEMA = "keelaryn.operation-relay-status.v1"
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_ACTOR = re.compile(r"^[A-Za-z0-9-]{1,39}$")
_REQUEST_ID = re.compile(r"^[0-9a-f]{32}$")
_OID = re.compile(r"^[0-9a-f]{40}$")


class GitHubTransportError(OperationRuntimeError):
    """GitHub issue transport cannot prove an exact safe operation exchange."""


@dataclass(frozen=True)
class IssueComment:
    comment_id: int
    actor: str
    body: str
    created_at: str
    updated_at: str


class GitHubIssueApi(Protocol):
    def list_comments(self) -> list[IssueComment]: ...
    def create_comment(self, body: str) -> IssueComment: ...
    def update_comment(self, comment_id: int, body: str) -> IssueComment: ...


class GitHubIssueClient:
    API_BASE = "https://api.github.com"

    def __init__(
        self,
        repository: str,
        issue_number: int,
        token: str,
        *,
        timeout_seconds: float = 20.0,
    ) -> None:
        if _REPOSITORY.fullmatch(repository) is None:
            raise GitHubTransportError("GitHub operations repository is invalid")
        if isinstance(issue_number, bool) or not isinstance(issue_number, int) or issue_number < 1:
            raise GitHubTransportError("GitHub operations issue number is invalid")
        if not isinstance(token, str) or not token or token != token.strip():
            raise GitHubTransportError("GitHub operations token is invalid")
        if timeout_seconds <= 0:
            raise GitHubTransportError("GitHub transport timeout must be positive")
        self.repository = repository
        self.issue_number = issue_number
        self.token = token
        self.timeout_seconds = float(timeout_seconds)

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
    ) -> tuple[int, bytes]:
        url = self.API_BASE + path
        raw = None
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": "Bearer " + self.token,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "keelaryn-operation-transport/1",
        }
        if body is not None:
            raw = json.dumps(
                dict(body),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(url, data=raw, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return int(response.status), response.read()
        except HTTPError as exc:
            try:
                exc.read()
            except Exception:
                pass
            raise GitHubTransportError(
                f"GitHub operations API returned HTTP {exc.code}"
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise GitHubTransportError(
                "GitHub operations API request failed before an authoritative response"
            ) from exc

    @staticmethod
    def _comment(value: Any) -> IssueComment:
        if not isinstance(value, dict):
            raise GitHubTransportError("GitHub issue comment is not an object")
        try:
            comment_id = value["id"]
            body = value["body"]
            user = value["user"]
            created_at = value["created_at"]
            updated_at = value["updated_at"]
        except KeyError as exc:
            raise GitHubTransportError(
                "GitHub issue comment is missing required metadata"
            ) from exc
        if (
            isinstance(comment_id, bool)
            or not isinstance(comment_id, int)
            or comment_id < 1
            or not isinstance(body, str)
            or not isinstance(user, dict)
            or not isinstance(user.get("login"), str)
            or not isinstance(created_at, str)
            or not isinstance(updated_at, str)
        ):
            raise GitHubTransportError("GitHub issue comment metadata is invalid")
        actor = user["login"]
        if _ACTOR.fullmatch(actor) is None:
            raise GitHubTransportError("GitHub issue comment actor is invalid")
        return IssueComment(comment_id, actor, body, created_at, updated_at)

    def list_comments(self) -> list[IssueComment]:
        owner_repo = "/".join(quote(part, safe="") for part in self.repository.split("/", 1))
        comments: list[IssueComment] = []
        page = 1
        while True:
            query = urlencode({"per_page": "100", "page": str(page)})
            status, raw = self._request(
                "GET",
                f"/repos/{owner_repo}/issues/{self.issue_number}/comments?{query}",
            )
            if status != 200:
                raise GitHubTransportError("GitHub issue comment listing failed")
            try:
                value = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise GitHubTransportError(
                    "GitHub issue comment listing returned invalid JSON"
                ) from exc
            if not isinstance(value, list):
                raise GitHubTransportError("GitHub issue comment listing is invalid")
            page_comments = [self._comment(item) for item in value]
            comments.extend(page_comments)
            if len(page_comments) < 100:
                break
            page += 1
            if page > 1000:
                raise GitHubTransportError("GitHub issue comment pagination is unbounded")
        comments.sort(key=lambda item: item.comment_id)
        return comments

    def create_comment(self, body: str) -> IssueComment:
        owner_repo = "/".join(quote(part, safe="") for part in self.repository.split("/", 1))
        status, raw = self._request(
            "POST",
            f"/repos/{owner_repo}/issues/{self.issue_number}/comments",
            body={"body": body},
        )
        if status != 201:
            raise GitHubTransportError("GitHub status comment creation failed")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GitHubTransportError("GitHub status comment response is invalid") from exc
        return self._comment(value)

    def update_comment(self, comment_id: int, body: str) -> IssueComment:
        if isinstance(comment_id, bool) or not isinstance(comment_id, int) or comment_id < 1:
            raise GitHubTransportError("GitHub status comment ID is invalid")
        owner_repo = "/".join(quote(part, safe="") for part in self.repository.split("/", 1))
        status, raw = self._request(
            "PATCH",
            f"/repos/{owner_repo}/issues/comments/{comment_id}",
            body={"body": body},
        )
        if status != 200:
            raise GitHubTransportError("GitHub status comment update failed")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GitHubTransportError("GitHub status comment response is invalid") from exc
        return self._comment(value)


def _canonical(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _private_dir(path: Path, label: str, *, create: bool = False) -> Path:
    path = path.absolute()
    if create and not path.exists():
        path.mkdir(parents=True, mode=0o700)
        if os.name == "posix":
            os.chmod(path, 0o700)
    try:
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise GitHubTransportError(f"{label} cannot be inspected") from exc
    if path.is_symlink() or not stat.S_ISDIR(info.st_mode):
        raise GitHubTransportError(f"{label} must be one real directory")
    if os.name == "posix":
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise GitHubTransportError(
                f"{label} must be owner-controlled mode 0700"
            )
    return path


def _regular(path: Path, label: str, mode: int) -> Path:
    try:
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise GitHubTransportError(f"{label} cannot be inspected") from exc
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise GitHubTransportError(f"{label} must be one regular file")
    if stat.S_IMODE(info.st_mode) != mode:
        raise GitHubTransportError(f"{label} must have mode {mode:04o}")
    return path


def _atomic_write(path: Path, raw: bytes, *, mode: int) -> None:
    parent = path.parent
    temp = parent / f".{path.name}.tmp-{os.getpid()}-{time.monotonic_ns()}"
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        try:
            os.fchmod(fd, mode)
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(fd)
        os.replace(temp, path)
        try:
            directory_fd = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        temp.unlink(missing_ok=True)
    _regular(path, "transport file", mode)


def _materialized_source_commit() -> str:
    release = Path(__file__).resolve().parents[2]
    source = release / "SOURCE_COMMIT"
    if source.is_symlink() or not source.is_file():
        raise GitHubTransportError(
            "GitHub operation transport must run from a materialized release "
            "or receive --source-commit"
        )
    try:
        value = source.read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise GitHubTransportError("materialized SOURCE_COMMIT is unreadable") from exc
    if _OID.fullmatch(value) is None:
        raise GitHubTransportError("materialized SOURCE_COMMIT is invalid")
    return value


def _actors(raw: str) -> frozenset[str]:
    values = [item.strip() for item in raw.split(",") if item.strip()]
    if not values or any(_ACTOR.fullmatch(item) is None for item in values):
        raise GitHubTransportError("GitHub operation actor allowlist is invalid")
    return frozenset(values)


def _request_from_comment(body: str) -> tuple[OperationRequest, bytes] | None:
    if not body.startswith(REQUEST_MARKER):
        return None
    payload = body[len(REQUEST_MARKER):]
    if not payload or "\n" in payload or "\r" in payload:
        raise GitHubTransportError("GitHub operation request comment framing is invalid")
    raw = (payload + "\n").encode("utf-8")
    request = parse_operation_request(raw)
    return request, raw


def _relay_status(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GitHubTransportError("operation relay status is invalid JSON") from exc
    expected = {
        "schema",
        "operation_id",
        "operation",
        "source_commit",
        "execution_state",
        "observed_state",
        "mutation_state",
        "phase",
        "event",
        "sequence",
        "timestamp_utc",
        "next_action",
        "terminal",
        "outcome",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise GitHubTransportError("operation relay status has invalid keys")
    if value["schema"] != RELAY_SCHEMA:
        raise GitHubTransportError("operation relay status schema mismatch")
    if _REQUEST_ID.fullmatch(value["operation_id"]) is None:
        raise GitHubTransportError("operation relay request identity is invalid")
    if _OID.fullmatch(value["source_commit"]) is None:
        raise GitHubTransportError("operation relay source identity is invalid")
    for key in (
        "operation",
        "execution_state",
        "observed_state",
        "mutation_state",
        "phase",
        "event",
        "next_action",
    ):
        item = value[key]
        if not isinstance(item, str) or not item or len(item) > 64:
            raise GitHubTransportError(f"operation relay {key} is invalid")
    if (
        isinstance(value["sequence"], bool)
        or not isinstance(value["sequence"], int)
        or value["sequence"] < 0
    ):
        raise GitHubTransportError("operation relay sequence is invalid")
    if not isinstance(value["timestamp_utc"], str) or len(value["timestamp_utc"]) > 64:
        raise GitHubTransportError("operation relay timestamp is invalid")
    if not isinstance(value["terminal"], bool):
        raise GitHubTransportError("operation relay terminal flag is invalid")
    if value["outcome"] is not None and (
        not isinstance(value["outcome"], str) or len(value["outcome"]) > 64
    ):
        raise GitHubTransportError("operation relay outcome is invalid")
    if raw != _canonical(value):
        raise GitHubTransportError("operation relay status is not canonical JSON")
    return value


class GitHubOperationTransport:
    def __init__(
        self,
        root: str | Path,
        api: GitHubIssueApi,
        *,
        source_commit: str,
        allowed_actors: Iterable[str],
        clock=time.time,
        status_refresh_seconds: int = 30,
    ) -> None:
        if _OID.fullmatch(source_commit) is None:
            raise GitHubTransportError("GitHub transport source_commit is invalid")
        actors = frozenset(allowed_actors)
        if not actors or any(_ACTOR.fullmatch(item) is None for item in actors):
            raise GitHubTransportError("GitHub transport actor allowlist is invalid")
        if status_refresh_seconds < 5:
            raise GitHubTransportError("GitHub status refresh interval is too small")
        self.root = _private_dir(
            Path(root),
            "GitHub operation transport root",
            create=True,
        )
        self.inbox = _private_dir(
            self.root / "inbox",
            "GitHub operation transport inbox",
            create=True,
        )
        self.outbox = _private_dir(
            self.root / "outbox",
            "GitHub operation transport outbox",
            create=True,
        )
        self.state_root = _private_dir(
            self.root / "state",
            "GitHub operation transport state",
            create=True,
        )
        self.api = api
        self.source_commit = source_commit
        self.allowed_actors = actors
        self.clock = clock
        self.status_refresh_seconds = int(status_refresh_seconds)

    @property
    def state_path(self) -> Path:
        return self.state_root / "transport.json"

    def _state(self) -> dict[str, Any]:
        if not self.state_path.exists() and not self.state_path.is_symlink():
            return {
                "schema": TRANSPORT_STATE_SCHEMA,
                "last_comment_id": 0,
                "status_comments": {},
            }
        _regular(self.state_path, "GitHub transport state", 0o600)
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GitHubTransportError("GitHub transport state is invalid") from exc
        if (
            not isinstance(value, dict)
            or set(value) != {"schema", "last_comment_id", "status_comments"}
            or value.get("schema") != TRANSPORT_STATE_SCHEMA
        ):
            raise GitHubTransportError("GitHub transport state schema/keys are invalid")
        if (
            isinstance(value["last_comment_id"], bool)
            or not isinstance(value["last_comment_id"], int)
            or value["last_comment_id"] < 0
            or not isinstance(value["status_comments"], dict)
        ):
            raise GitHubTransportError("GitHub transport state values are invalid")
        for request_id, item in value["status_comments"].items():
            if _REQUEST_ID.fullmatch(request_id) is None or not isinstance(item, dict):
                raise GitHubTransportError("GitHub status publication state is invalid")
            if set(item) != {"comment_id", "body_sha256", "published_at"}:
                raise GitHubTransportError("GitHub status publication state keys are invalid")
            if (
                isinstance(item["comment_id"], bool)
                or not isinstance(item["comment_id"], int)
                or item["comment_id"] < 1
                or not isinstance(item["body_sha256"], str)
                or len(item["body_sha256"]) != 64
                or not isinstance(item["published_at"], (int, float))
            ):
                raise GitHubTransportError("GitHub status publication state values are invalid")
        if self.state_path.read_bytes() != _canonical(value):
            raise GitHubTransportError("GitHub transport state is not canonical JSON")
        return value

    def _write_state(self, value: Mapping[str, Any]) -> None:
        _atomic_write(self.state_path, _canonical(value), mode=0o600)

    def _deliver(self, request: OperationRequest, raw: bytes) -> str:
        if request.source_commit != self.source_commit:
            return "SOURCE_MISMATCH"
        target = self.inbox / f"{request.request_id}.json"
        if target.exists() or target.is_symlink():
            _regular(target, "operation inbox request", 0o600)
            if target.read_bytes() != raw:
                raise GitHubTransportError(
                    "operation inbox request identity conflicts with existing request"
                )
            return "EXISTING"
        temp = self.inbox / (
            f".{request.request_id}.tmp-{os.getpid()}-{time.monotonic_ns()}"
        )
        try:
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "wb", closefd=False) as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
            finally:
                os.close(fd)
            os.link(temp, target)
            try:
                directory_fd = os.open(self.inbox, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                pass
        except FileExistsError:
            _regular(target, "operation inbox request", 0o600)
            if target.read_bytes() != raw:
                raise GitHubTransportError(
                    "operation request raced with conflicting identity"
                )
            return "EXISTING"
        finally:
            temp.unlink(missing_ok=True)
        _regular(target, "operation inbox request", 0o600)
        return "DELIVERED"

    @staticmethod
    def _status_body(value: Mapping[str, Any]) -> str:
        return STATUS_MARKER + _canonical(value).decode("utf-8").rstrip("\n")

    @staticmethod
    def _existing_status_comments(
        comments: Iterable[IssueComment],
    ) -> dict[str, list[IssueComment]]:
        result: dict[str, list[IssueComment]] = {}
        for comment in comments:
            if not comment.body.startswith(STATUS_MARKER):
                continue
            payload = comment.body[len(STATUS_MARKER):]
            if not payload or "\n" in payload or "\r" in payload:
                continue
            try:
                value = json.loads(payload)
            except json.JSONDecodeError:
                continue
            request_id = value.get("operation_id") if isinstance(value, dict) else None
            if isinstance(request_id, str) and _REQUEST_ID.fullmatch(request_id):
                result.setdefault(request_id, []).append(comment)
        return result

    def _publish_statuses(
        self,
        state: dict[str, Any],
        comments: list[IssueComment],
    ) -> tuple[int, int]:
        created = 0
        updated = 0
        discovered = self._existing_status_comments(comments)
        now = float(self.clock())

        for path in sorted(self.outbox.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                raise GitHubTransportError("operation outbox contains non-regular status")
            value = _relay_status(path.read_bytes())
            if value["source_commit"] != self.source_commit:
                raise GitHubTransportError("operation relay source_commit mismatch")
            request_id = value["operation_id"]
            body = self._status_body(value)
            digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
            publication = state["status_comments"].get(request_id)

            if publication is None:
                matches = discovered.get(request_id, [])
                if len(matches) > 1:
                    raise GitHubTransportError(
                        "GitHub contains ambiguous status comments for one operation"
                    )
                if len(matches) == 1:
                    publication = {
                        "comment_id": matches[0].comment_id,
                        "body_sha256": hashlib.sha256(
                            matches[0].body.encode("utf-8")
                        ).hexdigest(),
                        "published_at": now,
                    }
                    state["status_comments"][request_id] = publication
                    self._write_state(state)

            if publication is None:
                comment = self.api.create_comment(body)
                state["status_comments"][request_id] = {
                    "comment_id": comment.comment_id,
                    "body_sha256": digest,
                    "published_at": now,
                }
                created += 1
                self._write_state(state)
                continue

            age = now - float(publication["published_at"])
            if (
                publication["body_sha256"] == digest
                and (value["terminal"] or age < self.status_refresh_seconds)
            ):
                continue

            self.api.update_comment(int(publication["comment_id"]), body)
            publication["body_sha256"] = digest
            publication["published_at"] = now
            updated += 1
            self._write_state(state)

        return created, updated

    def poll_once(self) -> dict[str, int | str]:
        state = self._state()
        comments = self.api.list_comments()
        delivered = 0
        ignored = 0
        rejected = 0

        for comment in comments:
            if comment.comment_id <= state["last_comment_id"]:
                continue
            try:
                parsed = _request_from_comment(comment.body)
                if parsed is None:
                    ignored += 1
                elif comment.actor not in self.allowed_actors:
                    rejected += 1
                else:
                    request, raw = parsed
                    disposition = self._deliver(request, raw)
                    if disposition == "DELIVERED":
                        delivered += 1
                    elif disposition == "SOURCE_MISMATCH":
                        rejected += 1
            except OperationRuntimeError:
                rejected += 1

            state["last_comment_id"] = comment.comment_id
            self._write_state(state)

        created, updated = self._publish_statuses(state, comments)
        return {
            "schema": "keelaryn.github-operation-transport-poll.v1",
            "delivered": delivered,
            "ignored": ignored,
            "rejected": rejected,
            "status_created": created,
            "status_updated": updated,
        }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keelaryn-operation-transport")
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--source-commit")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("poll-once")
    serve = sub.add_parser("serve")
    serve.add_argument("--poll-seconds", type=float, default=10.0)
    return parser


def _environment() -> tuple[str, int, str, frozenset[str]]:
    repository = os.environ.get("KEELARYN_GITHUB_OPERATIONS_REPOSITORY", "")
    issue_raw = os.environ.get("KEELARYN_GITHUB_OPERATIONS_ISSUE", "")
    token = os.environ.get("KEELARYN_GITHUB_OPERATIONS_TOKEN", "")
    actors_raw = os.environ.get("KEELARYN_GITHUB_OPERATIONS_ACTORS", "")
    if _REPOSITORY.fullmatch(repository) is None:
        raise GitHubTransportError("GitHub operations repository is missing/invalid")
    try:
        issue = int(issue_raw)
    except ValueError as exc:
        raise GitHubTransportError("GitHub operations issue is missing/invalid") from exc
    if issue < 1:
        raise GitHubTransportError("GitHub operations issue is missing/invalid")
    if not token or token != token.strip():
        raise GitHubTransportError("GitHub operations token is missing/invalid")
    return repository, issue, token, _actors(actors_raw)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        repository, issue, token, actors = _environment()
        source_commit = args.source_commit or _materialized_source_commit()
        transport = GitHubOperationTransport(
            args.root,
            GitHubIssueClient(repository, issue, token),
            source_commit=source_commit,
            allowed_actors=actors,
        )

        if args.command == "poll-once":
            print(
                json.dumps(
                    transport.poll_once(),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            return 0

        if args.poll_seconds <= 0:
            raise GitHubTransportError("poll-seconds must be positive")

        while True:
            result = transport.poll_once()
            print(
                json.dumps(
                    result,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                flush=True,
            )
            time.sleep(args.poll_seconds)
    except (GitHubTransportError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
