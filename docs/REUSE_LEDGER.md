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


### P0-13 candidate-set model

The provider-neutral core now represents reconciliation as a **set of Artifact candidates**, never a best-match score.

Per-candidate evidence is merged by ArtifactID and resolved through the existing `ResolveContinuity` policy.

Set-level rules:
- zero candidates -> `UNRESOLVED`;
- supporting-only candidate(s), including path/hash/native identity hints -> `AMBIGUOUS`;
- supporting native mismatch cannot eliminate identity by itself;
- pairwise `CONFIRMED_DISTINCT` removes that Artifact from the plausible set, but does not identify the current occurrence;
- exactly one remaining candidate may become `RESOLVED_SAME` only when its pairwise decision is `CONFIRMED_SAME`;
- any competing plausible candidate keeps the set `AMBIGUOUS`;
- two conclusive-same candidates are still `AMBIGUOUS`.

The model sorts candidates deterministically by ArtifactID and performs no persistence mutation.


### P0-13 localfs base candidate generation

Base localfs reconciliation is deliberately cheap and read-only:

1. Read only the latest COMPLETE inventory for the exact provider/root.
2. Ignore prior unresolved rows as Artifact candidates.
3. Index assigned prior inventory by Locator path.
4. For each current regular-file ObjectGroup, union candidates across all current Locators.
5. For symlink/other occurrences, use the single current Locator.
6. Emit one SUPPORTING `LOCATOR_OVERLAP` signal per overlapping path/Artifact.
7. Resolve through the already-qualified provider-neutral `ResolveCandidateSet`.

Consequences:
- same path with one prior Artifact remains `AMBIGUOUS`;
- a current hard-link occurrence can legitimately contain multiple prior Artifact candidates if its two Locators previously belonged to different Artifacts;
- no overlap is `UNRESOLVED`;
- unresolved prior inventory cannot become an Artifact candidate;
- generation is deterministic by current first Locator, ArtifactID, and evidence source.

No content hash or native identity comparison runs automatically. Optional enrichment remains explicit: callers retain `OccurrenceCandidateSet.Inputs`, append deliberately sampled DecisionEvidence, and invoke `ResolveCandidateSet` again.


## P0-14 — selective content candidate enrichment

**Decision:** reuse the already-qualified snapshot group sampler and durable Revision history; add no dependency and no eager hashing.

API boundary:
- input is exactly one already-generated `OccurrenceCandidateSet`;
- zero candidates returns immediately and does not touch the filesystem;
- only regular-file sets can be content-enriched;
- the set Locators must exactly identify one current `localfs.ObjectGroup`;
- current bytes are sampled once through `Snapshot.SampleObjectGroupContent`;
- only the candidate Artifact IDs already present in the set are queried for Revision history.

Signal policy:
- latest candidate Revision with equal algorithm + digest + size adds one SUPPORTING `CONTENT_EQUAL` signal;
- different content adds **no distinct signal** because content modification is allowed within the same Artifact;
- candidate with no Revision adds no signal;
- content equality cannot resolve identity by itself, because all generated content signals remain SUPPORTING.

The function returns enriched inputs and a re-run `ResolveCandidateSet` result but performs no persistence mutation.


## P0-15 — in-process native continuity candidate discovery

**Decision:** reuse the already-qualified `os.SameFile` Snapshot evidence only while previous and current Snapshots coexist in one process. Persist no native identifiers.

Binding checks:
- previous/current Snapshot provider and root must be identical;
- supplied previous latest-COMPLETE inventory must match the previous Snapshot exactly by locator count, provider/root/path, kind, size, and modified time;
- supplied base current candidate sets must exactly match current Snapshot occurrence grouping.

Candidate behavior:
- regular previous/current ObjectGroups are compared with `CompareObjectGroups`;
- only `NATIVE_IDENTITY_MATCH` adds evidence;
- matching previous group Locators are mapped through prior **assigned** inventory to Artifact IDs;
- each mapped Artifact gets `PROVIDER_CONTINUITY_MATCH SUPPORTING`;
- mismatch adds no elimination evidence;
- a rename can therefore discover a prior Artifact despite zero locator overlap, but remains `AMBIGUOUS`;
- a delete/recreate can never become `RESOLVED_SAME` from this native evidence;
- if one previous physical group was mapped to several Artifacts, all remain candidates.

This feature is opportunistic acceleration/evidence, not durable identity authority. It disappears safely across process restart.


## P0-16 — extraction/context reuse review

**Decision:** keep the Keelaryn extraction contract small and provider-neutral, implement only a built-in bounded UTF-8 text/Markdown extractor for the first P0 slice, and reserve broad document conversion for optional adapters.

Reviewed current upstreams (2026-09-25):

### Microsoft MarkItDown

- project: `microsoft/markitdown`;
- license: MIT;
- runtime: Python 3.10–3.14;
- purpose: lightweight conversion to Markdown specifically for LLM/text-analysis use;
- formats include PDF, Word, PowerPoint, Excel, images/OCR, audio/transcription, HTML, CSV/JSON/XML, ZIP, EPUB and more;
- has a plugin architecture and MCP package.

**Keelaryn disposition:** preferred future **lightweight broad-extraction adapter**. Do not make Python or MarkItDown mandatory for the base Go binary.

### Docling

- project: `docling-project/docling`;
- license: MIT;
- runtime: Python;
- production/stable;
- unified document representation plus advanced PDF/layout/table/OCR/chunking workflows;
- current `docling-slim` declares a minimal base around ~50 MB before optional format/model extras; broad Office/PDF/OCR/audio/video capabilities add more runtime/model dependencies.

**Keelaryn disposition:** preferred future **advanced extraction/layout/OCR adapter**, likely optional local sidecar/service. Too heavy for the mandatory P0 runtime.

### Apache Tika

- project: `apache/tika`;
- license: Apache-2.0;
- runtime: Java/JVM;
- detects/extracts metadata and text from over a thousand file types.

**Keelaryn disposition:** optional broad compatibility/server fallback where JVM cost is acceptable. Not a base-binary dependency.

### Go-native MIME detection

- `gabriel-vasile/mimetype` — MIT, active, magic-number MIME detection;
- `h2non/filetype` — MIT, active, dependency-free magic-number binary type detection.

**Keelaryn disposition:** both are viable when content sniffing becomes necessary. Do not add either for the first text-only slice because an explicit supported-extension allow-list plus UTF-8 validation is enough and avoids a dependency that would not improve current correctness.

### First P0 extraction boundary

The first extractor therefore uses only Go stdlib:
- explicit supported extensions: `.txt`, `.md`, `.markdown`;
- bounded on-demand reads;
- UTF-8 validation;
- exact ArtifactID + RevisionID provenance;
- current bytes must match the referenced Revision's content evidence before text is accepted;
- unsupported types and opaque/non-UTF8 content are valid non-error outcomes;
- extraction is derived/non-authoritative and not persisted in the durable identity database.

Architecture keeps a replaceable extractor interface so MarkItDown/Docling/Tika adapters can be added later without changing Artifact/Revision semantics.


### P0-17 built-in revision-bound text extraction

The first extractor is intentionally narrow and derived-only.

Supported:
- `.txt` → `text/plain`;
- `.md`, `.markdown` → `text/markdown`.

Result states:
- `EXTRACTED`;
- `UNSUPPORTED`;
- `OPAQUE`;
- `STALE_REVISION`;
- `LIMIT_EXCEEDED`.

Safety/provenance:
- extraction requires a current inventory row already assigned to both ArtifactID and RevisionID;
- the exact referenced Revision record must exist;
- local bytes and SHA-256 evidence are produced from one bounded, open-handle-anchored read;
- bytes are accepted only when current algorithm/digest/size exactly match the referenced Revision evidence;
- non-UTF8 supported-extension content is `OPAQUE`;
- unsupported extension returns without reading the file;
- over-limit files return without derived text;
- extraction performs no durable write and does not modify Revision history.

The localfs content reader is refactored so both SHA-256-only sampling and byte-retaining extraction share the same path traversal, regular-file, handle identity, stability and post-read locator validation.


## P0-18 — explicit-selection ContextBundle

**Decision:** implement ContextBundle as a derived/rebuildable value layer with no new dependency and no durable persistence.

Selection contract:
- the caller explicitly supplies each assigned `InventoryEntry`;
- each selection carries a non-empty caller reason and its own `maxBytes`;
- selection order is preserved exactly;
- P0-18 performs no search, ranking, embeddings, chunking, or automatic corpus selection.

Construction:
- each selection runs through the already-qualified revision-bound extractor;
- every item preserves reason, extraction status, ArtifactID, RevisionID, Locator, ExtractorID, media type, and observed content evidence;
- text is included only for `EXTRACTED`;
- `UNSUPPORTED`, `OPAQUE`, `STALE_REVISION`, and `LIMIT_EXCEEDED` remain explicit item outcomes with no invented text.

The bundle is ephemeral AI/task context. It performs no Artifact, Revision, Observation, Locator, or scan mutation and is not stored in the durable identity database.


### P0-18 immediate compile correction

The implementation commit's new `builder_test.go` referenced `corpus.InventoryEntry` without importing the `internal/corpus` package.

This is a test-only compile defect detected immediately after publication. Product/context semantics are unchanged.

Correction:
- add the missing test import;
- require the corrected exact head to pass both Ubuntu and Windows before P0-18 qualification.


## P0-19 — formal closure audit

Result: **P0 NOT CLOSED**.

The detailed audit is `docs/P0_CLOSURE_AUDIT_20260925.md`.

Most important finding: P0 currently has bootstrap identity, durable revisions, ambiguity-preserving candidate generation/enrichment, extraction and ContextBundle, but lacks the transactional bridge from a uniquely `RESOLVED_SAME` reconciliation result to the next durable assigned Observation/Revision plus accepted-decision provenance.

This is a more fundamental gap than FTS/MCP/remote-provider work and is therefore sequenced first.

Other confirmed canonical gaps remain:
- SQLite FTS search;
- useful product CLI/MCP/HTTP access;
- one remote/rclone-backed provider spike;
- web status spike;
- a conclusive continuity evidence source sufficient to prove unchanged/move/modify end-to-end.


## P0-20 — atomic acceptance of resolved continuity

**Decision:** reuse the existing SQLite IMMEDIATE transaction, candidate-set resolver and Revision rules. Add no dependency.

Durable schema v4 adds one non-rebuildable provenance table:
`accepted_continuity_decisions`.

Each accepted row binds:
- decision ID;
- resulting Observation;
- selected Artifact;
- exact `RESOLVED_SAME` state;
- policy ID;
- full serialized candidate-set resolution including every candidate's evidence;
- decision timestamp.

Before mutation, `ValidateCandidateSetResolution` recomputes the candidate set from the evidence embedded in the supplied resolution and requires an exact match. A caller therefore cannot fabricate continuity by changing only `State` or `SelectedArtifactID`.

Atomic acceptance:
1. input Observation must still be UNRESOLVED;
2. resolution must self-validate and be uniquely `RESOLVED_SAME`;
3. scan must be OPEN and provider/root scope must match;
4. selected Artifact must already exist;
5. regular content evidence must be valid and size-consistent;
6. unchanged evidence reuses current Revision; changed evidence creates next Revision of the same Artifact;
7. assigned Observation is written;
8. accepted continuity provenance is written;
9. one SQLite transaction commits all of the above.

AMBIGUOUS/UNRESOLVED, missing Artifact, scan-scope error, algorithm mismatch, invalid evidence or forged resolution fail without durable identity mutation.


### P0-20 immediate test compile correction

The implementation commit's `continuity_test.go` uses `filepath.Join` in the reopen-provenance regression but omitted the standard-library `path/filepath` import.

This is test-only. Continuity transaction/schema/product semantics are unchanged.

The implementation head run is superseded; qualification requires the corrected exact head.


## P0-21 — provider-native identity continuity contract

**Reuse research update (2026-09-25):**
- current stable rclone release reviewed: `v1.75.1`, MIT, Go 1.26;
- rclone exposes optional `fs.IDer { ID() string }`;
- the rclone Google Drive backend implements `fs.IDer` and stores the Drive object ID;
- rclone Drive `ChangeNotify` internally consumes Drive change page tokens and `change.fileId`, but its public callback exposes changed **paths**, not identity/change provenance;
- rclone Drive represents shortcuts with a composite `actualID + TAB + shortcutID`, so future adapter code must explicitly choose shortcut-object versus target-object semantics before applying a Drive fileId contract.

**Google Drive documented semantics:**
- Drive describes `fileId` as a unique opaque ID for each file and stable throughout the life of that file, including name changes;
- copy creates a distinct file resource and can be assigned a separately generated unique ID;
- official documentation reviewed does **not** explicitly promise that a permanently deleted file ID is never reused.

Therefore generic `rclone/fs.IDer` is never conclusive by itself.

Provider-neutral semantics implemented:
- `SUPPORTING`: ID equality/difference is only a hint;
- `STABLE_FOR_RESOURCE_LIFETIME`: unequal IDs in one exact provider identity domain are CONCLUSIVE_DISTINCT; equal IDs are CONCLUSIVE_SAME only when a separate provider-history channel proves a continuous no-disappearance interval;
- `GLOBALLY_NON_REUSING`: reserved for an explicit stronger provider guarantee and may confirm equality across an unknown gap.

The Google Drive P0 contract uses `STABLE_FOR_RESOURCE_LIFETIME`, not `GLOBALLY_NON_REUSING`.

This deliberately separates:
1. **object-ID capability** (rclone can expose it),
2. **meaning of that ID** (provider contract),
3. **coverage of the interval between observations** (change/feed/session evidence).

No rclone dependency or OAuth is added by P0-21; this layer only qualifies the semantics before remote-provider integration.


## P0-22 — remote-history reuse research

**Decision:** separate generic provider I/O from durable provider history.

### rclone

Reviewed current rclone source (MIT):
- `fs.IDer` exposes optional native object ID;
- `fs.ListRer` exposes recursive listing;
- public `fs.ChangeNotifier` emits only changed path + entry type;
- Drive/OneDrive/Dropbox backends internally use richer start-page-token / delta-token / cursor APIs, but these tokens and provider object IDs are not part of the public ChangeNotifier callback.

Disposition:
- **reuse rclone for broad provider I/O/auth/list/read where its public semantics fit;**
- **do not use public ChangeNotify as continuity authority;**
- do not depend on unexported backend methods or private fields;
- do not fork rclone solely to expose Drive history for the first adapter.

### First remote-history adapter

Selected implementation candidate:
- provider: Google Drive;
- client: `google.golang.org/api/drive/v3` from `googleapis/google-api-go-client`;
- version reviewed: `v0.299.0`;
- license: BSD-3-Clause;
- architecture role: provider-specific adapter behind a provider-neutral RemoteHistory contract.

Why:
- official generated Go client exposes `changes.getStartPageToken` and `changes.list`;
- Drive change records retain `fileId`, current file state and `removed`;
- terminal `newStartPageToken` is distinct from intermediate `nextPageToken`;
- Google documents Drive page/start tokens as non-expiring;
- Google documents file IDs as stable throughout a file's lifetime;
- shared drives have their own change logs, so history-stream identity must include the relevant user/shared-drive log.

The Drive adapter SHOULD initially use the official client end-to-end for Drive listing/history/read metadata rather than combine two auth/client stacks. rclone remains available for later broad-provider adapters or byte transport if it materially reduces implementation without weakening identity/history semantics.

### Provider-neutral contract

A qualified RemoteHistory adapter must provide:

- complete read-only bootstrap;
- stable native object IDs;
- an opaque durable history-stream identity;
- an opaque committed cursor;
- incremental current-state changes including removal/tombstone identity;
- terminal next cursor only after complete page consumption;
- explicit history-gap / invalid-cursor / scope-mismatch handling;
- replay-safe semantics from the previous committed cursor;
- no silent conversion of removal into physical deletion.

Bootstrap must have no uncovered race:
- native initial-delta snapshot is acceptable; or
- cursor fence → full list → catch-up replay → atomic snapshot+cursor publication.

Cursor advancement is a transaction boundary: intermediate page tokens are transport state, not durable continuity authority.

### Cross-provider validation

The contract is intentionally not Drive-shaped:
- Microsoft Graph `driveItem/delta` provides initial enumeration, `@odata.nextLink`, terminal `@odata.deltaLink`, stable item IDs and deleted facets.
- Dropbox exposes list-folder cursors/continue semantics and deletion entries; rclone internally consumes these but public ChangeNotify hides the cursor/details.

Therefore Google is the first adapter, not the Core architecture.


## P0-23 — provider-neutral RemoteHistory contract model

Implemented with **zero new dependencies** in `internal/remotehistory`.

Domain model:
- `HistoryStreamID`: durable identity of one provider history stream;
- `HistoryCursor`: opaque durable committed cursor;
- `ContinuationToken`: transient pagination token, never durable continuity authority;
- `RemoteObjectState`: current provider-object state keyed by native object ID;
- `RemoteChange`: `UPSERT` or `REMOVED`;
- explicit page failures: `GAP`, `INVALID_CURSOR`, `SCOPE_MISMATCH`, `INSUFFICIENT_HISTORY`;
- cycle states include `INTERRUPTED`.

Core invariant:
- every page in one cycle is read from the **same previous committed cursor**;
- only a terminal page may supply `NextCursor`;
- only a valid terminal cycle produces `ProviderHistoryContinuous`;
- intermediate continuation tokens can never become committed coverage;
- transport interruption or provider gap leaves `NextCursor = PreviousCursor` and coverage `UNKNOWN`.

Removal remains `REMOVED` from the history/scope. The Core does not infer physical deletion.

The fake-adapter contract suite explicitly couples the resulting coverage to the already-qualified P0-21 `GoogleDriveFileIDContract`: equal stable-lifetime IDs become conclusive only after a terminal CONTINUOUS cycle.

## P0-24A — Google Drive RemoteHistory semantic adapter

Implemented with **zero new dependencies** in `internal/remotehistory/gdrive` before binding the official SDK.

The Drive-specific layer now proves:
- exact stream binding for one My Drive root or one shared drive;
- bootstrap as `start-page-token fence -> complete enumeration -> catch-up replay -> terminal cursor`;
- deterministic My Drive bootstrap membership from the parent graph;
- shared-drive scope by exact `driveId`;
- transient pagination tokens never become durable cursors;
- `removed`, trashed, or out-of-stream items become Core `REMOVED` semantics, not claims of physical deletion;
- Drive-level change records are ignored by the file-object adapter rather than fabricated into file identity;
- shortcut resources retain the shortcut file's own `fileId`; the target ID is not substituted as ProviderObject identity;
- provider access locator `file-id/<escaped fileId>` remains a Locator, never Artifact identity;
- client-classified GAP / invalid-cursor / scope-mismatch / insufficient-history conditions fail closed.

The narrow client interface deliberately mirrors only the provider operations needed by the already-qualified RemoteHistory contract: obtain a start token, enumerate files, and list changes. The next layer (P0-24B) is a thin binding to the reviewed official `google.golang.org/api/drive/v3` client. OAuth/live corpus access remains deferred until the deterministic SDK binding itself is qualified.

## P0-24B — official Google Drive Go client binding

P0-24A semantic adapter qualification:
- exact head: `2b1ce1a46a8c553aa630e505fabc3b85091ced11`;
- CI run: `36102156496`;
- validate: PASS;
- Ubuntu 24.04: PASS;
- Windows 2025: PASS.

The provider-specific client interface is now bound to the official generated `google.golang.org/api/drive/v3` client.

Dependency:
- module: `google.golang.org/api`;
- pinned version: `v0.299.0`;
- license: BSD-3-Clause;
- dependency lock generated by Go 1.27.1 `go mod tidy`, not hand-authored.

Binding policy:
- `*drive.Service` construction/authentication remains outside `internal/remotehistory/gdrive`;
- no OAuth flow is embedded in the history adapter;
- no live Drive account or user corpus is used by deterministic tests;
- My Drive change reads use `restrictToMyDrive=true`, `includeRemoved=true`, and `spaces=drive`;
- shared-drive calls bind the exact `driveId` and use the API's shared-drive support flags;
- `nextPageToken` remains transport continuation while `newStartPageToken` remains the terminal cursor passed to the already-qualified RemoteHistory layer;
- file metadata mapping retains Drive file ID, parents, drive ID, trashed state and shortcut target metadata without substituting shortcut target identity.

Disposable verification used exact base `2b1ce1a46a8c553aa630e505fabc3b85091ced11` and a checksum-verified Go 1.27.1 toolchain. `go mod tidy`, `go test ./...` and `go vet ./...` all passed. The temporary workspace was removed automatically after the verification job.

Cross-platform product policy was also made explicit in the canonical architecture: Android and Windows are first-class product targets; Linux is a first-class server/CI target; the Core remains platform-neutral and Android filesystem/SAF behavior belongs behind adapters.

## P0-26 — post-bootstrap new-Artifact admission reuse research

Research conclusion: **reuse provider cursor/delta semantics; implement only the Keelaryn-specific admission decision.**

Cross-provider evidence reviewed:
- Google Drive v3: stable file IDs for file lifetime; start-page token; paginated changes; terminal new-start token; removals; copy produces a new file resource/ID.
- Microsoft Graph `driveItem/delta`: race-safe initial enumeration, intermediate `@odata.nextLink`, terminal `@odata.deltaLink`, deleted facets and ID-based item tracking.
- Dropbox `list_folder` / `list_folder/continue`: cursor-backed local-state maintenance, deletion entries, unique file IDs and file-ID revision history across moves/renames.

Reusable architectural pattern:

```text
complete baseline
+ durable cursor
+ continuous incremental history
+ stable provider-object identity
= candidate-universe completeness evidence
```

This pattern can support **first-known/new-to-Keelaryn** admission. It does not prove physical creation time.

Decision:
- keep existing `CandidateSetResolution`;
- do not model NEW as "continuity with nothing";
- add a higher-level occurrence identity outcome with `RESOLVED_NEW`;
- require an explicit provider-neutral candidate-universe completeness proof before NEW;
- absence of path/hash/candidates is never sufficient;
- keep current localfs post-bootstrap NEW fail-closed until a qualified durable evidence source exists;
- use the already-qualified Google Drive RemoteHistory path as the first planned real completeness-proof producer;
- no new dependency is required for the Core admission model.

Detailed contract: `docs/P0_26_POST_BOOTSTRAP_NEW_ARTIFACT_CONTRACT.md`.

## P0-27 — provider-neutral post-bootstrap Artifact admission implementation

Implemented with **zero new dependencies**.

Core:
- candidate-universe coverage: `UNKNOWN` / `COMPLETE`;
- explicit `OccurrenceIdentityResolution`: `UNRESOLVED`, `AMBIGUOUS`, `RESOLVED_SAME`, `RESOLVED_NEW`;
- existing `CandidateSetResolution` remains unchanged;
- `RESOLVED_NEW` requires a valid COMPLETE universe proof and zero plausible SAME candidates.

SQLite v5:
- `provider_artifact_bindings` stores accepted provider-native identity -> Artifact authority scoped by identity domain;
- `accepted_artifact_admissions` stores non-rebuildable NEW-admission provenance;
- caller-supplied `AdmissionRequestID` is a durable replay/reconciliation key;
- duplicate request IDs cannot mint another Artifact;
- the same provider identity cannot be admitted twice under a different request;
- Artifact + optional Revision 1 + assigned Observation + binding + accepted admission commit atomically.

Tests cover:
- COMPLETE empty universe -> NEW;
- all candidates conclusively distinct -> NEW;
- UNKNOWN completeness -> not NEW;
- plausible SAME -> ambiguity;
- existing RESOLVED_SAME remains SAME;
- forged NEW rejected;
- request replay zero-mutation;
- provider identity double-admission zero-mutation;
- scope mismatch/unknown completeness zero-mutation;
- identical-byte copy with distinct conclusive provider identity -> distinct Artifact;
- admission/binding survive reopen;
- qualified v4 -> v5 migration.

The implementation still uses deterministic fake completeness proofs only. Live Google Drive/OAuth and corpus mutation remain deferred.

## P0 foundation retrospective — reuse corrections before RemoteHistory publication

A read-only retrospective of P0-20 through P0-27 found that the existing mechanics are useful but several trust/replay/lifetime boundaries must be hardened before live provider wiring.

New reuse sources applied:
- **Syncthing BEP delta indexes:** reuse the idea of an index/generation identity plus an advancing sequence; reset creates a new identity. Keelaryn will analogously separate local history generation from opaque provider cursor.
- **rclone bisync:** reuse last-known-good snapshot, recovery/lockout, and fail-closed interruption principles; do not use bisync as Artifact identity authority.
- **AWS/Stripe idempotency:** same request token must be bound to the same semantic parameters; mismatched reuse is an explicit error and exact replay reconciles the original result.
- **Drive/Graph/Dropbox delta APIs:** reinforce complete initial state + continuation + terminal future cursor, but stream completeness must not be confused with one object's uninterrupted resource lifetime.
- **Perkeep:** continues to validate stable logical identity separated from mutable provenance, without importing CAS authority.

Corrections required before product/live-provider wiring:
1. acceptance must revalidate authority-bearing evidence from durable trusted state rather than trust caller-authored CONCLUSIVE/COMPLETE flags;
2. RESOLVED_SAME needs replay/request identity just like NEW;
3. request IDs need parameter fingerprints/mismatch semantics;
4. provider-object bindings need lifetime/continuity context;
5. stream completeness must be distinct from object continuity;
6. history gaps/rebootstrap create a new local history generation;
7. REMOVED breaks stable-lifetime automatic SAME;
8. RemoteHistory identity/membership publication remains distinct from full metadata Observation;
9. RESOLVED_NEW means first accepted Artifact identity under policy, not necessarily first observation or physical creation;
10. bootstrap crash-resume is retained as a later reliability gap.

Detailed audit: `docs/P0_FOUNDATION_RETRO_AUDIT_20260925.md`.

## P0-28A — identity acceptance hardening reuse decisions

Closest implementation patterns reviewed again before coding:

- **AWS EC2 idempotency:** caller client token; same token + same parameters does not repeat the side effect; same token + changed parameters produces an explicit idempotent-parameter-mismatch error.
- **Stripe idempotency:** preserve the first execution result by key, replay it for the same request, and reject the same key when incoming parameters differ.
- **Syncthing delta indexes:** keep index generation identity separate from the advancing sequence; reset means a new index ID. This is reserved for P0-28B/C history generations.
- **rclone bisync:** preserve last-known-good state and block dependent operations when a critical interrupted state cannot be trusted.

Keelaryn-specific remainder:
- durable authority-reference records tied to Corpus-first identity semantics;
- SAME/NEW decisions derived inside the SQLite mutation boundary;
- permanent identity provenance rather than short-lived API retry caching;
- provider lifetime/history-generation scoping.

Detailed contract: `docs/P0_28A_IDENTITY_ACCEPTANCE_HARDENING_CONTRACT.md`.

Regular audit cadence is now mandatory in `docs/ENGINEERING_AUDIT_POLICY.md` and canonical section 17.1.

## P0-28A implementation — hardened identity mutation boundary

Implemented with zero new dependencies.

- Old exported SQLite methods accepting caller-constructed resolved SAME/NEW inputs were removed from the product surface.
- New public mutation boundary: `AcceptSameObservationInScan` / `AcceptNewObservationInScan`.
- Callers pass intent plus one immutable durable `IdentityAuthoritySetID`; they cannot pass raw authority strength or COMPLETE coverage.
- SQLite v6 adds `identity_authority_sets`, `identity_authority_candidates`, and `identity_mutation_requests`.
- There is deliberately no exported generic authority writer. Deterministic tests inject sets through an unexported package helper; later P0-28B/C source-specific producers will write production authority.
- Authority candidates carry no strength field. The transaction loads the entire persisted set and only then converts its trusted facts to conclusive decision evidence.
- SAME/NEW is derived inside the same SQLite transaction that performs the identity mutation.
- Versioned SHA-256 request fingerprints canonicalize locator order and bind request ID to semantic parameters. Request ID and decision timestamp are excluded.
- Same request ID + same fingerprint returns the original durable result with zero mutation.
- Same request ID + changed semantics returns `ErrIdentityMutationParameterMismatch`.
- Replay loads happen only after releasing the transaction connection, avoiding self-deadlock with the current single-connection SQLite pool.
- Schema reserves generation/lifetime-segment fields, but current provider binding is still fail-closed for live providers until P0-28B/C.

