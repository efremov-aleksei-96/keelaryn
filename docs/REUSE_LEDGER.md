# Reuse ledger

This file records subsystem-level reuse decisions so later development does not rediscover or silently replace them.

## P0-00 — local read-only discovery

**Decision:** use the Go standard library; add no third-party filesystem dependency.

Reused:
- `path/filepath.WalkDir` for lexical, deterministic tree walking that does not follow symbolic links;
- `os.Lstat` for metadata inspection without resolving symbolic links/reparse-point surrogates;
- `context`, `encoding/json`, `flag`, `os`, `sort` from the standard library.

Why:
- the standard library already supplies the exact minimal read-only traversal semantics required by the spike;
- no third-party dependency improves the current correctness boundary;
- native cross-platform filesystem object identity is intentionally **not** guessed from path/inode abstractions in this slice.

Deferred reuse candidates remain defined in `KEELARYN_CANONICAL.md`: rclone, SQLite/FTS, official MCP Go SDK, fsnotify, MarkItDown, Docling, Tika and later optional components. Each must receive a fresh fit/license/security/API review immediately before adoption.


## P0-01 — local continuity evidence

**Decision:** reuse Go standard-library `os.SameFile`; add no native-ID dependency yet.

The Go runtime already implements the relevant platform semantics:
- Unix: device + inode;
- Windows: volume serial + file index, loaded through a file handle when necessary.

The spike keeps this evidence **ephemeral and pairwise**. It does not serialize OS-native IDs and does not assign Artifact/Revision IDs.

Safety rules:
- materialize `SameFile` evidence while the original locator still exists, so Windows does not need an obsolete path after rename;
- regular files only in this slice;
- symlinks never inherit target identity evidence;
- hard links are expected to compare as one provider object with multiple locators;
- byte-identical copies are expected to compare as different provider objects.

Qualification runs the same tests on GitHub-hosted Ubuntu and Windows 2025. If either platform disproves the stdlib approach, replace only the provider evidence adapter rather than changing the Keelaryn identity model.


## P0-02 — ProviderObject grouping inside one snapshot

**Decision:** no new dependency.

The input relation is already supplied by the qualified Go stdlib `os.SameFile` evidence from P0-01. P0-02 only computes deterministic equivalence groups over a single bounded snapshot.

Implementation deliberately uses a simple O(n²) representative comparison:
- transparent correctness is more valuable than premature indexing in the technology spike;
- actual corpus benchmarks must justify a more complex grouping/index structure;
- the grouping algorithm is replaceable and does not define Keelaryn identity semantics.

A group has multiple Locators but intentionally no durable ProviderObject/Artifact ID yet. Symlinks and other entries without regular-file identity evidence remain outside groups rather than inheriting target identity.


## P0-03 — cross-snapshot continuity evidence, not Artifact auto-merge

Initial plan was to assign stable in-memory Artifact IDs directly from `os.SameFile` matches. Research rejected that plan as unsafe.

Primary platform evidence:
- Microsoft SMB FileId requirements say an ID persists for the lifetime of a file, but **may be reused after the file is deleted**.
- Microsoft filesystem documentation says file reference numbers are not guaranteed unique over time because a filesystem may reuse them.
- Unix inode identity is filesystem-local; after the last link/open reference is gone the object is deleted and its resources are available for reuse.

Therefore a native-ID match across two scans is **continuity evidence**, not proof that no delete/recreate occurred between observations.

P0-03 records:
- `NATIVE_IDENTITY_MATCH`;
- `NATIVE_IDENTITY_MISMATCH`;
- `EVIDENCE_UNAVAILABLE`.

All P0-03 evidence has `automatic_merge_allowed=false`.

Durable Artifact continuity must later combine stronger temporal/provider evidence or remain ambiguous. This preserves the canonical rule that ambiguity is preferable to invented identity.

Durable/global ID libraries surveyed for the later persistence layer:
- `google/uuid` — BSD-3-Clause;
- `oklog/ulid` — Apache-2.0;
- `segmentio/ksuid` — MIT.

None is added now because identifier-format choice is orthogonal to continuity correctness and P0-03 remains non-persistent.


## P0-04 — continuity decision model

**Decision:** implement the tiny domain resolver directly; no external dependency.

This logic is Keelaryn-specific policy, not generic infrastructure:
- `SUPPORTING` evidence informs but cannot mutate Artifact identity;
- `CONCLUSIVE` evidence may confirm same/distinct only when non-conflicting;
- no evidence => `UNRESOLVED`;
- supporting-only or conflicting evidence => `AMBIGUOUS`.

The local filesystem `os.SameFile` adapter always maps to `SUPPORTING`.

This layer intentionally does not allocate Artifact IDs yet. It establishes the safety contract that every later evidence source (fsnotify, provider change feed, direct Keelaryn mutation provenance, user confirmation) must satisfy.
