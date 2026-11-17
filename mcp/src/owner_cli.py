#!/usr/bin/env python3
"""Plain Linux CLI for one allowlisted owner scope. No AI/Drive/MCP tunnel.

Run under the configured owner service UID, with the same *authorized* scope
registry/environment as the MCP unit. Never run as another project's user.
This wrapper does not bypass server-side authorization or SHA-256 CAS.
"""
import json
import sys

from file_scopes import get_scope
from local_ro import operate as owner_read
from owner_fs import mutate as owner_mutate
from owner_large import read_chunk, edit_delta

MAX_INPUT = 65536


def _owned(project):
    scope = get_scope(project)
    if scope["backend"] != "owner-fs":
        raise ValueError("Only registered local owner scopes")
    return scope


def main(argv):
    if len(argv) == 2 and argv[0] == "list":
        project = argv[1]
        return owner_read("list_files", {"path": "", "limit": 100}, _owned(project))
    if len(argv) in (3, 4) and argv[0] == "search":
        project, query = argv[1:3]
        limit = int(argv[3]) if len(argv) == 4 else 20
        return owner_read("search_files", {"query": query, "limit": limit},
                          _owned(project))
    if len(argv) in (3, 4, 5) and argv[0] == "read":
        project, path = argv[1:3]
        offset = int(argv[3]) if len(argv) >= 4 else 0
        maximum = int(argv[4]) if len(argv) == 5 else 12288
        return read_chunk(_owned(project), {
            "project": project, "path": path,
            "offset_bytes": offset, "max_bytes": maximum})
    if len(argv) == 1 and argv[0] in ("delta", "mutate"):
        content = sys.stdin.read(MAX_INPUT + 1)
        if not content or len(content.encode("utf-8")) > MAX_INPUT:
            raise ValueError("Bounded JSON request required on stdin")
        args = json.loads(content)
        if not isinstance(args, dict):
            raise ValueError("Owner request must be a JSON object")
        scope = _owned(args.get("project"))
        return edit_delta(scope, args) if argv[0] == "delta" else owner_mutate(args, scope)
    raise ValueError(
        "Usage: owner_cli.py list PROJECT | search PROJECT QUERY [LIMIT]"
        " | read PROJECT FILE [OFFSET MAX_BYTES]"
        " | delta <request.json | mutate <request.json")


if __name__ == "__main__":
    try:
        result = main(sys.argv[1:])
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    except (ValueError, OSError, UnicodeError, TypeError) as e:
        print(json.dumps({"status": "error", "reason": str(e)[:180]}))
        raise SystemExit(1)
