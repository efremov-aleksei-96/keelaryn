from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .operation_runtime import OperationRuntimeError


REQUEST_SCHEMA = "keelaryn.operation-request.v1"
_REQUEST_ID = re.compile(r"^[0-9a-f]{32}$")
_TOKEN = re.compile(r"^[A-Z][A-Z0-9_:-]{0,63}$")
_OID = re.compile(r"^[0-9a-f]{40}$")
_ALLOWED_APPROVAL = {"NOT_REQUIRED", "REQUIRED"}


@dataclass(frozen=True)
class OperationRequest:
    request_id: str
    operation: str
    source_commit: str
    profile: str
    mutation_capable: bool
    timeout_seconds: int
    approval: str

    def to_json_value(self) -> dict[str, Any]:
        return {
            "schema": REQUEST_SCHEMA,
            "request_id": self.request_id,
            "operation": self.operation,
            "source_commit": self.source_commit,
            "profile": self.profile,
            "mutation_capable": self.mutation_capable,
            "timeout_seconds": self.timeout_seconds,
            "approval": self.approval,
        }


def _token(value: object, label: str) -> str:
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise OperationRuntimeError(f"operation request {label} is invalid")
    return value


def parse_operation_request(raw: bytes) -> OperationRequest:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OperationRuntimeError("operation request is invalid JSON") from exc

    expected = {
        "schema",
        "request_id",
        "operation",
        "source_commit",
        "profile",
        "mutation_capable",
        "timeout_seconds",
        "approval",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise OperationRuntimeError("operation request has invalid keys")
    if value["schema"] != REQUEST_SCHEMA:
        raise OperationRuntimeError("operation request schema mismatch")

    request_id = value["request_id"]
    if not isinstance(request_id, str) or _REQUEST_ID.fullmatch(request_id) is None:
        raise OperationRuntimeError("operation request request_id is invalid")

    source_commit = value["source_commit"]
    if not isinstance(source_commit, str) or _OID.fullmatch(source_commit) is None:
        raise OperationRuntimeError("operation request source_commit is invalid")

    mutation_capable = value["mutation_capable"]
    if not isinstance(mutation_capable, bool):
        raise OperationRuntimeError("operation request mutation_capable is invalid")

    timeout_seconds = value["timeout_seconds"]
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int)
        or timeout_seconds < 1
        or timeout_seconds > 86400
    ):
        raise OperationRuntimeError("operation request timeout_seconds is invalid")

    approval = value["approval"]
    if approval not in _ALLOWED_APPROVAL:
        raise OperationRuntimeError("operation request approval is invalid")

    request = OperationRequest(
        request_id=request_id,
        operation=_token(value["operation"], "operation"),
        source_commit=source_commit,
        profile=_token(value["profile"], "profile"),
        mutation_capable=mutation_capable,
        timeout_seconds=timeout_seconds,
        approval=approval,
    )

    canonical = (
        json.dumps(
            request.to_json_value(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    if raw != canonical:
        raise OperationRuntimeError("operation request is not canonical JSON bytes")
    return request


def read_operation_request(path: str | Path) -> OperationRequest:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise OperationRuntimeError("operation request must be one regular file")
    return parse_operation_request(candidate.read_bytes())


__all__ = [
    "OperationRequest",
    "REQUEST_SCHEMA",
    "parse_operation_request",
    "read_operation_request",
]
