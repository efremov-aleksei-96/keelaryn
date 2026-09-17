from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Mapping

from .migration_freeze import (
    MigrationFreezePostCommitBlocked,
    freeze_migration_candidate,
    verify_migration_candidate_freeze,
)
from .migration_pack import (
    MigrationPackBlocked,
    build_migration_pack,
    capture_migration_source,
    verify_migration_mapping,
    verify_migration_pack,
    verify_migration_source,
)


def _emit(value: Mapping[str, Any], *, stream=None) -> None:
    target = sys.stdout if stream is None else stream
    print(
        json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        file=target,
        flush=True,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="keelaryn-migration")
    sub = parser.add_subparsers(dest="command", required=True)

    capture = sub.add_parser(
        "capture-source",
        help="Capture exact fingerprints for one explicit read-only migration source allowlist",
    )
    capture.add_argument("--source-root", required=True)
    capture.add_argument("--selection-manifest", required=True)
    capture.add_argument("--output-manifest", required=True)

    source_verify = sub.add_parser(
        "source-verify",
        help="Verify one frozen migration source manifest",
    )
    source_verify.add_argument("--source-manifest", required=True)

    mapping_verify = sub.add_parser(
        "mapping-verify",
        help="Verify one migration mapping against one frozen source manifest",
    )
    mapping_verify.add_argument("--source-manifest", required=True)
    mapping_verify.add_argument("--mapping-manifest", required=True)

    build = sub.add_parser(
        "pack-build",
        help="Build one immutable private migration pack",
    )
    build.add_argument("--source-root", required=True)
    build.add_argument("--source-manifest", required=True)
    build.add_argument("--mapping-manifest", required=True)
    build.add_argument("--prepared-root")
    build.add_argument("--output-dir", required=True)

    verify = sub.add_parser(
        "pack-verify",
        help="Verify one immutable private migration pack",
    )
    verify.add_argument("--pack-dir", required=True)

    freeze = sub.add_parser(
        "candidate-freeze",
        help="Issue one immutable sanitized FROZEN_UNQUALIFIED receipt for an exact private candidate",
    )
    freeze.add_argument("--pack-dir", required=True)
    freeze.add_argument("--repo-root", required=True)
    freeze.add_argument("--expected-source-commit", required=True)
    freeze.add_argument("--expected-source-tree", required=True)
    freeze.add_argument("--output-receipt", required=True)

    freeze_verify = sub.add_parser(
        "candidate-freeze-verify",
        help="Verify one frozen candidate receipt against the exact private pack and clean source checkout",
    )
    freeze_verify.add_argument("--pack-dir", required=True)
    freeze_verify.add_argument("--repo-root", required=True)
    freeze_verify.add_argument("--receipt", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "capture-source":
            summary = capture_migration_source(
                args.source_root,
                args.selection_manifest,
                args.output_manifest,
            ).public_summary()
            _emit({"source": summary})
        elif args.command == "source-verify":
            _emit({"source": verify_migration_source(args.source_manifest).public_summary()})
        elif args.command == "mapping-verify":
            mapping = verify_migration_mapping(args.source_manifest, args.mapping_manifest)
            _emit({"mapping": mapping.public_summary()})
        elif args.command == "pack-build":
            pack = build_migration_pack(
                args.source_root,
                args.source_manifest,
                args.mapping_manifest,
                args.output_dir,
                prepared_root=args.prepared_root,
            )
            _emit({"pack": pack.public_summary()})
        elif args.command == "pack-verify":
            _emit({"pack": verify_migration_pack(args.pack_dir).public_summary()})
        elif args.command == "candidate-freeze":
            _emit(
                {
                    "freeze": freeze_migration_candidate(
                        args.pack_dir,
                        args.repo_root,
                        args.expected_source_commit,
                        args.expected_source_tree,
                        args.output_receipt,
                    )
                }
            )
        else:
            _emit(
                {
                    "freeze": verify_migration_candidate_freeze(
                        args.pack_dir,
                        args.receipt,
                        args.repo_root,
                    )
                }
            )
        return 0
    except MigrationFreezePostCommitBlocked as exc:
        _emit({"error": "POST_COMMIT_BLOCKED", "detail": str(exc)}, stream=sys.stderr)
        return 3
    except MigrationPackBlocked as exc:
        _emit({"error": "BLOCKED", "detail": str(exc)}, stream=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
