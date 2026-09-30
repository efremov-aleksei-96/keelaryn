# P0-36B Google live metadata adapter/runtime composition retrospective — 2026-09-30

## Boundary

Qualified product head: `2e92db262c4ab8804531cc509501c3e8f1a6bbc1`.

Exact product tree: `6b3a52f7bcfc348c0d13ba98aa2e76aa48b19788`.

Exact-head qualification: GitHub Actions run `36736005980`.

Result: **PASS — P0-36B qualified; zero new BLOCKER/CRITICAL findings.**

P0-36B is deliberately **bootstrap-only and unauthenticated in tests**. It composes the provider-to-Observation runtime path but does not claim the P0-36C real-provider acceptance gate.

## What was implemented

The existing pinned official `google.golang.org/api/drive/v3` client is reused. No second Drive SDK, sync engine, inventory, identity resolver, or provider-specific durable metadata authority was added.

The existing Drive `files.list` and `changes.list` field masks now request the exact additional provider metadata required by the P0-36 contract:

- `mimeType`;
- `size`;
- `modifiedTime`.

Existing identity/topology fields remain unchanged.

Provider mapping is conservative:

- ordinary content-bearing Drive items map to `REGULAR_FILE`;
- folders, shortcuts, and Drive SDK objects map to `OTHER`;
- POSIX mode is never invented and therefore remains unavailable;
- modified time is recorded only when a valid provider timestamp is supplied;
- size is recorded only when the pinned Drive semantics make it meaningful.

The generated pinned Drive client decodes `File.Size` as scalar `int64`, so absent and explicit zero are not distinguishable solely from that Go field. The mapper therefore never upgrades a zero Google-native value to known merely because the scalar is zero. A zero-byte blob is accepted as known because Drive defines size for blob content; folders/shortcuts remain unavailable. This chooses missing evidence over fabricated evidence.

## One fenced bootstrap boundary

Metadata capture reuses the already-qualified Drive history fence:

`StartPageToken -> files enumeration -> changes catch-up -> terminal cursor`.

`BootstrapWithMetadata` updates RemoteHistory objects, topology, and transient metadata from the same change pages and returns them only after a common terminal cursor is reached. The metadata bundle is not durable by itself.

The durable path remains:

`TopologyCoordinator -> RemoteHistory generation/publication -> managed-root binding/projection -> LIGHTWEIGHT_ALL:v2 generic materializer -> ScanSession / Observation / Inventory -> existing identity acceptance`.

No Google-specific inventory table or second durable snapshot authority exists.

## Interruption / replay behavior

The runtime explicitly limits this P0-36B slice to bootstrap publication sequence 1.

If a history generation already exists after interruption, provider enumeration is not blindly repeated into durable state. The candidate fenced read must match:

- the durable committed terminal cursor;
- the exact current provider-object set;
- the durable provider locators.

Only then may the existing source-bound materializer replay the matching scan.

If the provider boundary changed, the runtime returns `ErrGoogleDriveLiveBootstrapPrestateChanged` and does not mutate current inventory. Incremental metadata advancement after sequence 1 is **not** claimed by this slice; it remains outside the minimal P0-36B happy path.

## Regression evidence

Deterministic fake-service coverage proves:

- the Google client requests `mimeType`, `size`, and `modifiedTime`;
- zero-byte blobs retain a known zero size;
- folders do not acquire fabricated size;
- native Workspace metadata is accepted when supplied;
- metadata changes are caught up from the same history fence;
- folders and shortcuts remain non-regular `OTHER` entries;
- provider mode remains unavailable.

Real SQLite end-to-end tests prove:

- bootstrap commits RemoteHistory/topology and materializes only the managed-root projection;
- outside objects do not enter the managed-root inventory;
- Drive observations do not gain a fabricated mode;
- exact replay returns the existing scan;
- a changed provider terminal cursor fails closed and leaves existing inventory unchanged.

## Qualification

Disposable VPS qualification on the exact candidate tree:

- targeted `internal/remotehistory/gdrive` + `internal/ingest` suites — PASS;
- full `go test -count=1 -timeout=300s ./...` — PASS;
- full `internal/state/sqlite` within that run — PASS in 260.189 s;
- `go vet ./...` — PASS;
- `git diff --check` — PASS.

Exact-head GitHub Actions run `36736005980` on `2e92db262c4ab8804531cc509501c3e8f1a6bbc1`:

- validate — PASS;
- Ubuntu 24.04 dependency lock — PASS;
- Ubuntu Go tests — PASS;
- Ubuntu Go vet — PASS;
- Windows 2025 dependency lock — PASS;
- Windows Go tests — PASS;
- Windows Go vet — PASS.

## Boundary audit

New BLOCKER: none.

New CRITICAL: none.

The audit confirmed:

- no Drive write API call was introduced;
- no Drive write scope was introduced;
- no OAuth/user credential runtime was enabled in P0-36B;
- no live provider was contacted;
- no user corpus content was mutated;
- no new dependency, workflow, release, update, or rollback surface was added;
- the managed-root binding remains idempotent for interruption replay;
- H1 release-state rollback and H2 Android qualification remain open and unchanged outside the current P0-36 gate.

## Next boundary

P0-36C is now the only current P0-36 substage.

It must expose a supported executable/runtime surface for a real authenticated **read-only** Google Drive metadata run using the narrow `drive.metadata.readonly` scope, with OAuth/service construction outside the pure adapter. Credentials/tokens must stay outside Git and the user corpus. Acceptance should use disposable protected control state where possible and must prove both no Drive corpus writes and exact durable runtime results.

Only a qualified P0-36C live evidence checkpoint may clear the outstanding `LIVE_REMOTE_PROVIDER_RUNTIME_QUALIFICATION` P0 closure gate.
