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


## P0-05 — local temporal evidence reuse research

**Decision:** do not add a watcher dependency yet. Prefer `fsnotify/fsnotify` as the future notification substrate, but its current public API is not sufficient to authorize Artifact continuity.

Survey:
- `fsnotify/fsnotify v1.10.1` — BSD-3-Clause, active, Linux inotify + Windows ReadDirectoryChangesW. It detects event overflow on both platforms.
- Upstream merged PR #628 already pairs Linux move cookies and Windows old/new rename records internally.
- The paired old path is stored as an unexported `Event.renamedFrom`; issue #26 remains the public-API tracker. Public callers therefore still see rename-old plus create-new without a reliable exported pairing key.
- `fswatcher/fswatcher` — MIT and active, but its public Event also exposes only Name+Op and discards native rename pairing.
- `radovskyb/watcher` — BSD-3-Clause and exposes OldPath, but it is polling-based and recognizes moves by `sameFile`; this inherits the native-ID reuse limitation already rejected for automatic continuity.

Disposition:
1. Do not write a new generic watcher.
2. Do not parse `fsnotify.Event.String()` or use unsafe/reflection to reach the private rename field.
3. Do not treat rename-old/create-new adjacency as continuity proof.
4. Keep `fsnotify` as the preferred future event transport.
5. If P0/P1 requires conclusive local rename evidence, first attempt an upstream-compatible exported rename-pair API; otherwise maintain the smallest pinned BSD-licensed fork/patch of fsnotify's existing implementation.
6. Any overflow/gap invalidates assumptions based on event-stream completeness and requires read-only rescan/reconcile.

P0 continues with first-class ambiguity instead of waiting for this optional stronger evidence source.


## P0-06 — ambiguity-first Artifact registry

**Decision:** implement directly in the Keelaryn domain layer; add no dependency.

This is product-specific identity policy, not reusable infrastructure.

The registry is intentionally provider-neutral and never receives:
- paths/Locators;
- content hashes;
- native filesystem IDs;
- provider object IDs.

Rules:
- first adoption with no continuity candidate creates a process-local Artifact ID;
- `CONFIRMED_SAME` preserves the existing Artifact;
- `CONFIRMED_DISTINCT` creates a new Artifact;
- `AMBIGUOUS` and `UNRESOLVED` create nothing and return the prior Artifact only as an explicit candidate;
- invalid candidates/decision states fail without mutation.

IDs use a simple session counter in this spike. This is deliberate: UUID/ULID/KSUID format choice belongs to the persistence layer and must not be confused with continuity correctness.


## P0-07 — content evidence and Revision semantics

**Decision:** use Go standard-library `crypto/sha256` for the first correctness spike; add no hashing dependency.

Why SHA-256 now:
- built into the toolchain and available on every target platform;
- sufficient deterministic evidence for semantic tests;
- throughput is not yet a measured P0 bottleneck;
- the model records the algorithm explicitly, so a later benchmark can justify BLAKE3 or another implementation without changing Artifact/Revision semantics.

Alternatives noted for later benchmark:
- `zeebo/blake3` — active pure-Go implementation, license metadata requires explicit review before adoption;
- `lukechampine/blake3` — MIT, optimized BLAKE3 implementation.

Safety:
- digest is content evidence only, never ArtifactID or RevisionID;
- fingerprinting is on-demand, not eager full-corpus hashing;
- local fingerprinting is bound to a prior Snapshot and revalidates `os.SameFile` after opening, so replacement at the same path fails closed;
- first evidence creates Revision 1;
- unchanged evidence reuses current Revision;
- changed evidence creates a new Revision;
- A→B→A creates a third Revision even when its digest equals Revision 1;
- changing evidence algorithm is non-comparable and fails without mutation in this minimal model.


### P0-07 correction after CI

The first implementation attempted to bind an on-demand content read to an older `Snapshot` using `os.SameFile(oldInfo, openedInfo)`.

Ubuntu CI disproved this: deleting a file and immediately creating a replacement at the same path reused the inode, so `os.SameFile` returned true. This is a concrete reproduction of the native-ID reuse risk already identified in P0-03.

Correction:
- remove the unsafe `Snapshot.ContentEvidence` API;
- on-demand hashing now creates a **fresh content observation** anchored to the open file handle;
- pre-open and post-read locator checks occur while the handle is open;
- the result does not claim continuity with any earlier Snapshot or Artifact;
- Artifact assignment still requires the separate continuity decision layer.

This defect is retained as a regression lesson: native identity evidence cannot safely bind a later path lookup to an older observation after an unobserved gap.


## P0-08 — durable state store selection

**Decision:** first spike uses `zombiezen.com/go/sqlite v1.4.2` (ISC).

Why:
- no CGO; compatible with the single-binary/cross-platform direction;
- built on the mature pure-Go `modernc.org/sqlite` substrate;
- already provides `sqlitemigration` with transactional migrations, `PRAGMA application_id` protection, version tracking, and pool lifecycle;
- exposes SQLite online backup API;
- avoids us writing a custom migration framework merely to reach P0 durability.

Alternatives reviewed:
- `github.com/ncruces/go-sqlite3 v0.35.6` — MIT, no-CGO, database/sql and online backup; excellent candidate if zombiezen footprint/API becomes problematic, but migration policy would still be ours and the public version is pre-v1.
- `modernc.org/sqlite` — BSD-3-Clause, no-CGO, selected indirectly as zombiezen's SQLite substrate.
- `github.com/mattn/go-sqlite3` — MIT but requires CGO/GCC, rejected for the base portable binary.

Hard boundary:
- SQLite is **Keelaryn control state**, not corpus storage.
- An open DB must live on local/runtime storage, not in a synchronized/network corpus root.
- First schema contains only non-rebuildable Artifact/Revision identity state and minimal content evidence.
- Extracted text, embeddings, previews, indexes, and file bytes remain outside this durable identity schema and are not introduced by P0-08.


### P0-08 implementation boundary

The first durable schema is intentionally only:

- `artifacts(artifact_id)`;
- `revisions(revision_id, artifact_id, sequence, content_algorithm, content_digest, content_size)`.

No Locator, path, provider-native ID, file bytes, extracted text, preview, embedding, or search index is stored in schema v1.

Durable identity uses `github.com/google/uuid v1.6.0` (BSD-3-Clause):
- `art_<UUIDv4>`;
- `rev_<UUIDv4>`.

UUID generation establishes globally unique durable identifiers; it does **not** establish continuity. Continuity remains governed by the separate evidence/decision model.

The store uses zombiezen's `sqlitemigration` rather than a Keelaryn-specific migration framework, including a fixed SQLite `application_id` (`KLRY`) to fail closed on a foreign database file.


### P0-08 first-CI correction

Exact-head run `36057871299` resolved and printed the canonical dependency lock, but the Ubuntu store tests exposed a strict `zombiezen/sqlitex.Execute` contract: cached single-statement execution rejects trailing bytes after the prepared statement.

The initial multiline SELECT/INSERT strings ended with a semicolon plus newline, so SQLite parsed one statement and `Conn.Prepare` correctly rejected the remaining bytes.

Correction:
- every `sqlitex.Execute` query is one exact statement with no trailing semicolon/newline;
- migration SQL remains a script and keeps normal semicolon delimiters under `sqlitemigration`;
- exact GitHub-hosted `go mod tidy` output from run `36057871299` is committed as `go.mod/go.sum`;
- CI returns to `go mod tidy -diff`, making dependency drift a failure rather than an implicit mutation.


## P0-09 — durable Observation and Locator evidence

**Decision:** reuse the existing SQLite/sqlitemigration stack; add no dependency.

Design borrows two proven ideas without adopting their storage models:
- Perkeep separates a stable object anchor from append-only claims that describe changing state over time.
- DataLad separates dataset/content identity from location/provenance tracking.

Keelaryn applies the same separation to an existing external corpus:
- `Artifact` remains the stable Keelaryn identity;
- a `ProviderObjectOccurrence` is one durable record of the physical object evidenced in one observation and does **not** claim cross-scan continuity;
- `Observation` is append-only evidence;
- `Locator` records where that occurrence was observed and may have multiple rows (for example hard links);
- the same path in two observations is allowed and creates no identity relation;
- unresolved observations persist with NULL Artifact/Revision rather than being guessed.

Schema v2 intentionally does **not** implement a `current_locator` table/view. Without a complete scan/session boundary, "latest historical locator" is not equivalent to "current locator".


## P0-10 — scan/session completeness and derived inventory

**Decision:** reuse SQLite transactions, foreign keys, partial unique indexes, and the existing `sqlitemigration` stack; add no dependency.

A scan is a completeness boundary for one exact `(provider_id, root)` pair:
- `OPEN`: observations may be appended but the scan is not authoritative;
- `COMPLETE`: the full observation set becomes eligible to define current inventory;
- `ABORTED`: retained as provenance but never authoritative.

Rules:
- at most one OPEN scan exists per provider/root;
- an observation can be attached only while its scan is OPEN;
- observation provider/root must match the scan scope;
- only the latest COMPLETE scan is queried for inventory/current locators;
- newer OPEN/ABORTED work cannot hide or replace the last complete authority;
- an empty COMPLETE scan means the root was observed empty;
- a newer COMPLETE unresolved observation at an old path removes the old Artifact's current-locator claim;
- `Inventory` and `CurrentArtifactLocators` are derived queries, not stored authority.

Existing schema-v2 observations migrate with `scan_id=NULL`; they remain historical evidence and cannot accidentally become current inventory.


### P0-10 first-CI correction

Exact-head run `36092529766` reached the complete SQLite test suite. The only Ubuntu failure was the old schema inventory assertion: it still expected the qualified v2 five-table set and therefore rejected the intentionally added v3 `scan_sessions` table.

No schema/runtime logic failed.

Correction:
- update the schema regression expectation to the exact v3 six-table set;
- retain all scan/session implementation unchanged;
- requalify on both Ubuntu and Windows 2025.


## P0-11 — localfs complete-scan ingestion

**Decision:** compose the already-qualified localfs Snapshot and scan-state APIs through a tiny `ScanStore` interface; add no dependency.

Pipeline:
`localfs Snapshot (read-only) → deterministic occurrence grouping → unresolved durable observations → COMPLETE scan → derived inventory`.

Safety:
- filesystem discovery finishes before any new scan is opened;
- regular-file `ObjectGroups` preserve hard-link multiplicity as one occurrence with multiple Locators;
- independent files with identical bytes remain separate occurrences;
- symlinks/non-regular entries remain single unresolved occurrences and are never followed;
- ingestion never allocates Artifact or Revision identity;
- scan publication happens only after every observation write succeeds;
- any persistence error after scan start triggers best-effort `ABORTED`; previous COMPLETE inventory stays authoritative;
- discovery failure happens before `StartScan`, so it cannot create partial authority;
- empty snapshots are valid and can publish empty inventory.

The orchestration depends only on `ScanStore`, not SQLite, preserving the ability to change the control-state adapter later without changing provider semantics.


## P0-12 — explicit first-observation adoption

**Decision:** identity adoption is a separate explicit bootstrap operation, not implicit behavior of every local scan.

Why:
- a later path/native-ID/hash match is insufficient to prove Artifact continuity;
- the first observation of a scope with no prior object history has no continuity candidate and may safely mint a new Artifact;
- once any object history exists — including an ABORTED scan — automatic bootstrap is refused.

Storage guarantees:
- `StartBootstrapScan` performs the no-history check and OPEN-scan creation in one SQLite IMMEDIATE transaction;
- `AdoptObservationInScan` creates Artifact + optional Revision 1 + assigned Observation in one transaction;
- regular files require fresh SHA-256 evidence whose size matches the sampled observation;
- symlink/other entries may get Artifact identity but no content Revision in this slice.

Provider guarantee:
- regular hard-link groups are content-sampled while an open representative file handle anchors object identity;
- every group locator is revalidated before and after hashing while that handle remains open;
- a changed/split group fails closed before the bootstrap scan is opened.

Ordinary `LocalFS` remains ambiguity-first and unresolved. After bootstrap, a repeat scan does **not** reuse Artifact identity from path, hash, or supporting native identity.


### P0-10 post-qualification ordering defect found by P0-12

P0-12 intentionally used scans separated by one nanosecond and exposed a flaw in the P0-10 latest-COMPLETE query.

The database stores timestamps as RFC3339Nano text. RFC3339Nano uses a variable-width fractional component, so lexicographic TEXT order is not chronological across values such as:
- `...00Z`
- `...00.000000001Z`

The previous SQL `ORDER BY finished_at DESC` could therefore select the older scan.

Correction:
- keep the existing schema and durable timestamp representation;
- enumerate COMPLETE scans for the exact provider/root;
- parse `finished_at` with Go `time.Parse(time.RFC3339Nano)`;
- choose the true maximum instant, with `scan_id` only as a deterministic tie-breaker;
- add a 1-nanosecond regression test.

This reopens P0-10 qualification until the corrected exact head passes both platforms.


## P0-13 — continuity candidate reconciliation reuse review

**Decision:** implement the candidate-set accumulator directly; add no matching/deduplication dependency.

Reviewed:

- **rclone/rclone** `--track-renames`: useful precedent for cheap candidate bucketing. Its implementation builds a rename key from size plus configurable hash/leaf components and keeps multiple destination objects under one key. However `popRenameMap` then selects and removes one candidate so the sync operation can perform a rename. Keelaryn must not reuse that assignment behavior: several plausible Artifacts must remain several candidates until stronger evidence resolves them.
- **dedupeio/dedupe**: mature Python fuzzy matching/entity-resolution library using machine learning and human training data. This solves probabilistic record linkage, not durable corpus identity. It would add a Python/ML surface and, more importantly, optimize toward deciding linkage where Keelaryn must preserve uncertainty.
- **oddg/hungarian-algorithm**: MIT Go implementation of the Hungarian assignment algorithm. One-to-one minimum-cost assignment is structurally the wrong abstraction because it selects an optimum matching even when identity evidence is insufficient.

Reuse boundary:

1. Reuse the **idea** of staged candidate generation/bucketing from rclone.
2. Do not reuse rclone's candidate-selection/mutation behavior.
3. Do not introduce fuzzy scores, probabilistic thresholds, or a global assignment solver.
4. Keep every plausible Artifact candidate explicitly.
5. Run each candidate's evidence through the already-qualified `ResolveContinuity`.
6. Candidate-set state is:
   - no plausible candidate -> `UNRESOLVED`;
   - any plausible candidate without one uniquely conclusive same decision -> `AMBIGUOUS`;
   - future providers may produce `CONFIRMED_SAME` only when exactly one candidate has non-conflicting CONCLUSIVE same evidence and no competing plausible candidate remains.
7. P0-13 is read-only reconciliation. It persists no Artifact/Revision assignment.
