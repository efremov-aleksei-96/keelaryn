# POST-P0-02A incremental observation contract

Status: **SOL DECISION — CONTRACT FROZEN**

Qualification rule: this frozen contract becomes authoritative only by exact-head validate + Ubuntu 24.04 + Windows 2025 PASS, exact-head review, and conditional fast-forward integration of revision 240. The document uses durable post-integration terminology so a later session never sees a stale “candidate” label.

Date: 2026-10-04

Authority: `KEELARYN_CANONICAL.md` remains product architecture authority. This contract narrows canonical post-P0 growth-order item 2, **incremental local/provider observation**, before any new product mutation path is enabled.

## 1. Decision

Keelaryn will separate **observation/probe** from **accepted publication**.

A watcher event, provider notification, scheduled probe or filesystem snapshot can say that something may have changed. It does not by itself become current Artifact/Revision/inventory authority.

The default order is:

```text
read-only probe / provider change evidence
→ bind the exact source boundary for one observation attempt
→ keep the attempt non-current while identity/revision decisions are resolved
→ revalidate the exact source boundary
→ guarded accepted publication
→ only then may the new inventory/source boundary become current
```

For LocalFS, a full read-only scan remains the correctness baseline. Incremental/watch sources are optimizations unless their exact source-specific contract proves durable gap detection and continuity.

## 2. Why the current LocalFS path cannot simply be scheduled

Current `ingest.LocalFS` is intentionally a lightweight observation primitive:

1. take a complete LocalFS snapshot;
2. create **UNRESOLVED** Observation inputs;
3. `CommitLocalSnapshot` writes them and marks the scan `COMPLETE` atomically;
4. `Inventory` selects the latest `COMPLETE` scan.

That is safe as isolated observation evidence, but it is not a safe current-product rescan loop after accepted identity already exists.

If it were scheduled directly after bootstrap, the newest inventory would contain unresolved regular files and would silently displace the previously accepted Artifact/Revision assignments.

The identity APIs cannot repair that after publication:

- `AcceptSameObservationInScan` requires the scan to be `OPEN`;
- `AcceptNewObservationInScan` requires the scan to be `OPEN`;
- both record the assigned Observation inside the authority-validated transaction.

Therefore the correct order is **identity/revision acceptance while OPEN, publication last**.

## 3. Interruption requirement

A local observation attempt that performs accepted SAME/NEW mutations can create durable Artifact, Revision and decision provenance before the scan becomes current.

Consequently:

- a crash cannot be recovered by blindly abandoning the attempt and starting a semantically unrelated new scan;
- the intended source snapshot must be durably bound before the first identity mutation;
- exact replay/reconcile must distinguish "same attempt resumed" from "source changed; old attempt cannot continue";
- a later implementation must not duplicate NEW admission after an uncertain result.

The closest existing internal analog is remote materialization:

```text
StartRemoteHistoryScan
→ durable source binding
→ OPEN scan
→ revalidate source
→ identity-aware writes
→ final source revalidation
→ CompleteRemoteHistoryScan
```

LocalFS should reuse this lifecycle shape, not the provider-specific RemoteHistory cursor model.

## 4. Identity authority remains source-specific

Current LocalFS reconciliation deliberately emits only SUPPORTING evidence:

- locator overlap;
- exact content equality;
- `os.SameFile` native-object match.

Supporting evidence cannot authorize Artifact mutation.

The hardened identity boundary already forbids a generic caller from supplying arbitrary `CONCLUSIVE` evidence. A source-specific qualified producer is required. `docs/P0_28A_IDENTITY_ACCEPTANCE_HARDENING_CONTRACT.md` explicitly anticipated a future qualified local filesystem journal/native-identity source.

Therefore POST-P0-02 MUST NOT solve incremental observation by weakening `ResolveContinuity` or exporting a generic authority writer.

Across an unobserved gap, unchanged path/content/native-number coincidence remains insufficient unless the relevant provider contract proves stronger continuity.

## 5. Capability tiers

### Tier 0 — complete snapshot

A full provider snapshot establishes current observed membership/metadata for that point-in-time boundary.

It is the portable LocalFS correctness baseline.

It does not prove uninterrupted Artifact continuity across an unobserved interval.

### Tier 1 — ephemeral notification

Examples:

- fsnotify/inotify/ReadDirectoryChangesW-style events;
- push notifications that only wake a poller;
- non-durable watcher dirty sets.

These are hints only.

Overflow, restart, missed events or watcher replacement require fallback to a complete reconciliation boundary. Tier-1 state never becomes Artifact identity authority.

### Tier 2 — durable gap-aware history/journal

A source may become authority-bearing only through a source-specific qualified adapter that proves at least:

- durable stream/journal identity;
- monotonic committed position;
- explicit gap/overflow/discontinuity detection;
- stable provider-object identity for the qualified lifetime;
- deterministic restart/replay behavior;
- exact scope binding.

This is structurally analogous to RemoteHistory generations/lifetime segments, but LocalFS journal tokens and RemoteHistory cursors MUST NOT be collapsed into one generic token format.

### Tier 3 — provider-native stable IDs

Some non-POSIX local/document providers expose durable provider-scoped IDs.

For Android SAF, document IDs belong behind a dedicated ProviderAdapter. They are provider identity evidence, not Artifact identity and not filesystem paths.

## 6. Search and ContextBundle coupling

The current protected LocalFS runtime is bootstrap-source-specific.

`expectedSearchBoundaryReadOnly`:

1. selects `LatestCompleteScan`;
2. requires an exact bootstrap receipt;
3. places that bootstrap receipt into `search.SourceBoundary`.

`preflightProtectedSearchRecovery`, `BootstrapIndex` replay and ContextBundle source proofs use the same bootstrap-only assumption.

Therefore a later non-bootstrap `COMPLETE` LocalFS scan would break the already-qualified search/context path even if its Artifact/Revision assignments were otherwise correct.

This coupling MUST be removed before post-bootstrap LocalFS publication is enabled.

## 7. Accepted local source

The read-side runtime needs one concept:

**AcceptedLocalSource**

It is the current LocalFS scan boundary that is qualified for Artifact/Revision-bound search/context use.

It binds at least:

- provider ID;
- root;
- scan ID;
- scan start/publication boundary;
- receipt mode;
- fingerprint version;
- fingerprint digest.

Qualification rules are mode/version-specific.

### Existing bootstrap

The current bootstrap receipt remains qualified. Its fingerprint is content-bearing because bootstrap samples regular-file content and binds exact accepted Artifact/Revision creation.

### Existing ordinary SCAN receipt

The current `SCAN` receipt produced by `CommitLocalSnapshot` is **not** automatically an AcceptedLocalSource.

Its v1 scan fingerprint describes unresolved snapshot metadata and membership. It is useful durable observation evidence, but it cannot replace the accepted bootstrap boundary used by search/context.

### Future accepted SCAN

A later source-bound accepted publication may reuse `local_ingest_commits` with `ingest_mode='SCAN'`, but it MUST use a distinct qualified fingerprint version whose contract proves the exact source state required by accepted Artifact/Revision inventory.

Do not overload the existing metadata-only SCAN fingerprint version with stronger semantics.

## 8. Read-side selection rule

Protected search/context must stop assuming:

```text
LatestCompleteScan == current accepted LocalFS source
```

Instead they will select the newest **qualified AcceptedLocalSource**.

A COMPLETE scan that has only the existing unresolved metadata-only SCAN receipt is not eligible to displace an accepted source boundary.

This preserves the prior searchable/accepted inventory while observation/reconciliation work remains unresolved.

The generic historical `LatestCompleteScan` API can continue to represent scan chronology. Product search/context authority should use the narrower accepted-source selector.

## 9. Search SourceBoundary reuse

Do not invent a second search-boundary model.

The existing `searchsqlite.SourceBoundary` already binds:

- ProviderID;
- Root;
- ScanID;
- StartedAt;
- FingerprintVersion;
- FingerprintSHA256.

POST-P0-02B will change how the expected LocalFS boundary is selected and proven, not the shape of search-derived authority.

## 10. First implementation slice — POST-P0-02B

The first product slice is:

**POST_P0_02B_ACCEPTED_LOCAL_SOURCE_BOUNDARY**

It is deliberately read-side/foundation work. It does **not** enable incremental writes yet.

Required behavior:

1. add a read-only accepted-local-source selector/receipt reader;
2. accept the already-qualified bootstrap receipt;
3. reserve a distinct future accepted-SCAN fingerprint contract without treating existing metadata-only SCAN v1 receipts as accepted;
4. migrate protected search recovery, search rebuild and ContextBundle source proof to the accepted-local-source selector;
5. use the same selected accepted inventory for extraction/search/context rather than generic latest COMPLETE inventory;
6. preserve pre/post source revalidation around corpus reads;
7. prove all existing bootstrap behavior remains valid;
8. add an adversarial regression where a later unresolved metadata-only COMPLETE SCAN exists but does not silently become protected search/context authority.

No schema migration is required merely to perform this read-side selection if the existing receipt/scan tables provide sufficient evidence. If implementation proves otherwise, stop and re-audit rather than adding a speculative table.

## 11. Follow-up implementation — POST-P0-02C

Only after POST-P0-02B is qualified may LocalFS gain a new durable publication path.

POST-P0-02C must define:

- durable source binding at OPEN-scan creation, before first identity mutation;
- exact attempt replay/reconcile after crash;
- identity-aware SAME/NEW writes while the scan is OPEN;
- explicit handling of unresolved/ambiguous occurrences without replacing prior accepted current inventory;
- final full source revalidation;
- guarded COMPLETE + qualified accepted-SCAN receipt;
- deterministic handling of partial identity mutations;
- no blind retry after uncertain completion.

A small LocalFS equivalent of `remote_scan_sources` is a plausible reuse pattern, but it is not authorized by this contract until POST-P0-02B evidence clarifies the minimum durable state required.

## 12. Watchers and journals

No watcher dependency is added in POST-P0-02A or POST-P0-02B.

Reuse posture:

- **fsnotify-class watcher:** optional dirty-hint adapter later; not durable authority.
- **Watchman:** optional desktop/server accelerator. Clock/fresh-instance/recrawl semantics are useful for detecting lost continuity, but a separate daemon is not a baseline ordinary-user requirement.
- **Windows USN Change Journal:** potential Windows-specific Tier-2 accelerator because it exposes journal identity/positions and discontinuity information; privilege/filesystem constraints prevent it from being the portable default.
- **Android SAF:** separate provider adapter direction. Durable provider document IDs must stay provider-scoped and must not be translated into POSIX identity assumptions.

The default cross-platform Core must remain useful without any of these optional mechanisms.

## 13. Remote-provider incremental path

Google Drive already has a qualified durable RemoteHistory generation/cursor/lifetime foundation and a coordinator `Advance` path.

That does not eliminate the LocalFS source-boundary work above, because the current live Google Drive product runtime only composes bootstrap metadata materialization; incremental metadata rematerialization is still a separate product slice.

Provider incremental work can proceed after the common observation/publication contract is stable. It must preserve provider-history scope, managed-root topology, lifetime-segment identity and exact materialization-source semantics.

## 14. Invariants

POST-P0-02 implementation must preserve:

- user corpus bytes are never mutated by observation;
- `state.db` remains identity/provenance authority;
- watcher state is never Artifact identity authority;
- RemoteHistory cursor semantics remain provider-specific;
- supporting LocalFS evidence never becomes conclusive by caller assertion;
- unresolved ambiguity never silently merges or remints Artifact identity;
- a non-qualified observation scan never silently replaces an accepted search/context source boundary;
- search remains derived and bound to exact accepted source/revision evidence;
- interruption never permits duplicate NEW admission through blind retry;
- Android/Windows/Linux differences stay behind adapters.

## 15. External analog evidence

Reviewed nearest external mechanisms:

- fsnotify — cross-platform file-notification abstraction; useful for wakeups/dirty hints, not a durable committed history cursor: https://github.com/fsnotify/fsnotify
- Watchman clocks/since/fresh-instance/recrawl semantics — useful optional gap-aware observation source for desktop/server deployments: https://facebook.github.io/watchman/docs/clockspec and https://facebook.github.io/watchman/docs/cmd/since
- Windows USN Change Journal — persistent per-volume journal with journal identity and USN positions, useful as a possible Windows-specific durable change source: https://learn.microsoft.com/en-us/windows/win32/fileio/change-journals
- Android Storage Access Framework / DocumentsProvider — provider-scoped document IDs and URI-based access belong behind an Android provider adapter: https://developer.android.com/guide/topics/providers/document-provider.html

No external mechanism is adopted as mandatory Core infrastructure by this contract.

## 16. Qualification for POST-P0-02A

This contract is qualified only when:

- exact-head CI passes existing validate + Ubuntu 24.04 + Windows 2025;
- exact-head review finds no authority/search/recovery contradiction;
- `DEVELOPMENT_STATE.json` selects POST-P0-02B as the next product slice;
- no product/runtime file changed in this work unit.

After qualification, POST-P0-02B may begin. POST-P0-02C and watcher/provider accelerators remain locked behind the POST-P0-02B evidence boundary.
