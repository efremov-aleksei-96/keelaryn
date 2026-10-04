# POST-P0-01B protected recovery retrospective and item-1 closure — 2026-10-04

## Result

**PASS — POST-P0-01B qualified; zero new BLOCKER/CRITICAL findings; canonical post-P0 item 1 is complete for growth-order purposes.**

This retrospective qualifies the bounded **POST-P0-01B protected recovery single-preflight** slice and closes the current canonical growth-order item 1, **reliability and deterministic recovery**.

It does **not** mean that every future reliability concern is permanently solved. Explicit release, portability, production live-provider credential, and housekeeping gates remain carried under their own scopes.

The top-level development phase is intentionally **not** changed by this retrospective. Advancement to item 2 is a separate state/CI transition mutation.

## Qualified provenance

Frozen implementation handoff:

- PR #121
- `7066fc327c188cd3fd90d4b44e61e52068230e93`
- exact-head GitHub Actions run `37194324271`: validate + Ubuntu 24.04 + Windows 2025 PASS
- dependency lock PASS
- all Go tests PASS
- Go vet PASS
- exact-head Codex review: clean
- Sol exact-head semantic review: PASS

Conditional-fast-forward integration:

- integration claim #122
- authoritative integration head `73966add49b16c56d47b5a2f2d55e20737e7cd52`
- verified tree `f1d67cb1aa242b77c336faf134b619ac4c98c55b`
- integration tree is exactly the frozen handoff tree
- sole parent is acquired base `35c8882a244bd0b992a3c5197afad800e1d41f60`
- ordinary GitHub merge was intentionally not used

## What changed

Before POST-P0-01B, protected derived-search recovery ran the same authority/corpus preflight twice:

1. before acquiring `search.lock`;
2. again after acquiring `search.lock`, immediately before staging mutation.

POST-P0-01B removes the redundant first pass.

The qualified order is now:

```text
resolve/verify protected control layout
→ acquire search mutation lock
→ full read-only state.db verification
→ current COMPLETE-scan / bootstrap receipt proof when applicable
→ current corpus fingerprint proof when applicable
→ first staging-family mutation
→ BootstrapIndex source extraction with receipt replay/revalidation
→ staged verification
→ active SQLite reconciliation
→ final caller-cancellation gate
→ promotion
→ bounded cancellation-detached post-promotion verification
```

## Authority and race analysis

`search.lock` remains coordination-only.

Its persistent file is not evidence that:

- `state.db` exists;
- `state.db` is valid;
- a scan is complete;
- any Artifact/Revision/Observation identity exists;
- a search cache is current.

Creating/acquiring the lock before state verification is already compatible with the recovery model: the lock file may survive a crash before the first state transaction.

The retained preflight is the proof that matters for mutation authorization because it runs **after writer serialization and immediately before the first active/staged search-family mutation**.

Removing the earlier proof does not weaken the mutation boundary. Correctness already depended on the later proof because any earlier proof could become stale before lock acquisition.

## Preserved verification

The slice does **not** replace full verification with `quick_check`.

For existing state, `sqlitestate.VerifyReadOnly` still performs the qualified integrity, foreign-key and historical-authority checks.

When a COMPLETE local bootstrap exists, protected preflight still proves the exact durable bootstrap receipt against a fresh local snapshot fingerprint.

`BootstrapIndex` also continues to replay/revalidate bootstrap evidence around source reads. Therefore corpus changes during extraction still fail before the staged derived cache is accepted.

No state repair path was added.

## Exact performance claim

No representative large-state benchmark was available and no wall-time or percentage speedup is claimed.

The bounded structural saving is:

- completed-scan recovery: one duplicate full state verification **plus** one duplicate corpus-fingerprint traversal removed;
- existing state with no COMPLETE scan: one duplicate full state verification removed;
- fresh missing-state profile: no expensive verification/traversal was previously performed, so no such saving is claimed.

This is a call-count/placement optimization with preserved correctness, not a benchmark result.

## Adversarial proof

The final qualified suite proves at least:

1. lock contention is observed before corrupt-state full verification and changes no active/staged search family;
2. once the lock is available, the same corrupt state fails closed before staging disposal;
3. unrelated state foreign-key/schema damage still blocks derived recovery before search-family mutation;
4. orphan authoritative state sidecars still prevent derived DB creation;
5. coordination-only `search.lock` may exist in that fail-closed state and must itself remain a safe regular protected-control file;
6. all POST-P0-01A corrupt/missing cache, staging, sidecar, alias, cancellation, promotion and failure-window regressions remain green;
7. Ubuntu 24.04 and Windows 2025 both pass the exact candidate.

The first candidate `6d035792…` exposed one stale test expectation that classified creation of `search.lock` as a forbidden derived mutation. That contradicted the already-qualified POST-P0-01A rule that lock-only crash residue is harmless. The test was corrected without weakening the prohibition on `search.db` or `search.db.next` creation when authority is missing.

Codex also found two documentation precision issues on the earlier candidate:

- the optimization claim was too broad across fresh/no-COMPLETE-scan paths;
- the function comment still described the old two-call ordering.

Both were corrected before final qualification.

## Item-1 closure audit

The closure audit considered current and carried reliability/recovery evidence after POST-P0-01A and POST-P0-01B.

### Resolved current reliability/recovery work

POST-P0-01A qualified deterministic recovery for rebuildable derived search state while preserving `state.db` as non-rebuildable authority.

Historical LocalFS interruption/completeness gaps are already resolved by schema v44:

- `AUDIT_C1_B16_LOCALFS_INGEST_INTERRUPTION_BOOTSTRAP_RECOVERY`
- `AUDIT_C1_B17_LOCALFS_COMPLETE_SNAPSHOT_REVALIDATION`

POST-P0-01B resolves the current carried P1:

- `PERFORMANCE_RESOURCE/search/state-db-verification-double-scan`

No current BLOCKER/CRITICAL item-1 finding remains.

### Carried findings with later scopes

`AUDIT_RELEASE_H1_STATE_DB_ROLLBACK_NOT_IMPLEMENTED`

- remains a release/update gate;
- requires explicit pre-upgrade state capture/verification and rollback compatibility before release-update support is enabled;
- it is not silently treated as solved by search recovery.

`AUDIT_RELEASE_H2_ANDROID_QUALIFICATION_ABSENT`

- remains a portability gate;
- Android direct execution cannot be claimed until a durable-state/backend decision and Android qualification exist;
- current exact runtime qualification remains Ubuntu/Windows.

`AUDIT_P0_36C_TOKENINFO_SCOPE_PREFLIGHT_AVAILABILITY`

- remains a production live-provider credential/availability gate;
- current CLI accepts an externally supplied opaque raw access token;
- Google describes tokeninfo introspection as diagnostic;
- safely eliminating that dependency requires Keelaryn to own an OAuth credential lifecycle that binds authenticated granted-scope evidence when obtaining/refreshing credentials;
- caller-supplied scope metadata must not replace introspection because that would weaken exact least-scope enforcement.

`AUDIT_P0_FINAL_L1_REPOSITORY_DESCRIPTION_STALE`

- remains housekeeping;
- it does not affect runtime correctness.

### Discovery evidence belonging to later growth-order items

Watchman clock/fresh-instance/recrawl and durable local cursor publication research belongs to canonical item 2:

- incremental local/provider observation.

MarkItDown/Docling/Tika and optional Android extraction-worker packaging research belongs to canonical item 3:

- broader extraction and its platform qualification.

These findings are useful future evidence, but they are not reasons to keep canonical item 1 artificially open.

## Mandatory full engineering retrospective

This stage was audited read-only on authoritative product head `73966add49b16c56d47b5a2f2d55e20737e7cd52` under `docs/ENGINEERING_AUDIT_POLICY.md` before item-1 completion was accepted.

The audit used a durable work ledger in PR #124 and completed every required dimension before finding synthesis. PR #124 itself changes only development state and this retrospective, so the audited product bytes remained immutable throughout the pass.

### A01 — canonical invariants versus implementation

**PASS.**

The exact POST-P0-01B product delta is limited to protected derived-search recovery ordering, adversarial tests, and its contract. It does not change Artifact, Revision, Observation, ProviderObject, Locator or provider-history identity semantics.

`state.db` remains non-rebuildable authority. `search.db`, `search.db.next` and `search.lock` remain derived/coordination state.

### A02 — durable-authority boundaries

**PASS.**

The recovery gate uses `sqlitestate.VerifyReadOnly` with exact application/schema checks, SQLite integrity, foreign-key validation and historical authority verification.

Search `SourceBoundary` remains derived candidate scope metadata. Read paths re-derive the expected boundary from authoritative state; staging is never query authority.

### A03 — replay, idempotency and interruption

**PASS.**

`BootstrapIndex` retains bootstrap receipt replay/revalidation around source reads. POST-P0-01B changes no durable replay token or ingest receipt.

Existing recovery coverage retains deterministic retry behavior for prior staging, corrupt/missing active cache, cancellation around reconciliation/promotion and injected failure windows.

### A04 — transaction atomicity and mutation-boundary revalidation

**PASS.**

The single full state/corpus recovery preflight runs after search writer serialization and immediately before the first derived-family mutation.

`ReplaceAllBound` continues to replace the complete derived document set and its SourceBoundary in one SQLite IMMEDIATE transaction. Promotion remains the derived commit boundary after staged verification, active-family reconciliation and the final caller-cancellation gate.

### A05 — schema migration and rollback implications

**PASS WITH CARRIED HIGH.**

POST-P0-01B adds no state or search schema migration.

Because `search.db` is rebuildable derived state, this slice adds no authority rollback requirement. Existing `AUDIT_RELEASE_H1_STATE_DB_ROLLBACK_NOT_IMPLEMENTED` remains a HIGH release/update gate for non-rebuildable state and is not claimed resolved.

### A06 — negative and adversarial cases

**PASS.**

Exact handoff `7066fc327c188cd3fd90d4b44e61e52068230e93` passed CI `37194324271` on Ubuntu 24.04 and Windows 2025, including dependency lock, all Go tests and Go vet.

The qualified suite covers corrupt/missing active cache, valid/mismatched/orphan staging, unrelated state corruption, missing authority plus sidecars, corpus drift, lock contention, unsafe aliases, cancellation around reconcile/promotion, active SQLite sidecars and injected failure windows.

### A07 — runtime call-site reachability

**PASS — REACHABLE PRODUCT PATH.**

`cmd/keelaryn` exposes `bootstrap-index`, which directly invokes `localruntime.BootstrapProtectedIndex`.

POST-P0-01B therefore changes reachable product behavior rather than an isolated mechanism spike. This is why exact-head CI was treated only as input to this retrospective, not as stage completion.

### A08 — cross-platform assumptions

**PASS WITH CARRIED ANDROID GATE.**

The exact handoff is qualified on Ubuntu 24.04 and Windows 2025.

Search locking uses non-blocking `flock` on Unix-family builds and `LockFileEx(...LOCKFILE_FAIL_IMMEDIATELY)` on Windows.

Direct Android durable-state execution remains unqualified. `AUDIT_RELEASE_H2_ANDROID_QUALIFICATION_ABSENT` remains HIGH and no Android support is inferred from the Unix lock adapter.

### A09 — security and credential boundaries

**PASS WITH CARRIED LIVE-PROVIDER GATE.**

Protected control storage retains owner-only Unix directory protection and protected Windows ACL validation. Unsafe symlink/reparse/control-family aliases fail closed.

Derived search retains SQLite/FTS secure-delete policy. POST-P0-01B changes no credential handling.

`AUDIT_P0_36C_TOKENINFO_SCOPE_PREFLIGHT_AVAILABILITY` remains a MEDIUM production live-provider credential/availability gate. Current raw-token mode must not replace authenticated scope introspection with caller-supplied scope metadata.

### A10 — lost local state and provider-history gaps

**PASS.**

Missing `state.db` with any state SQLite sidecar or active/staged search family fails closed rather than reminting authority. A persistent `search.lock` alone is explicitly non-authoritative and may survive a pre-state crash.

Corrupt derived search remains recoverable without repairing state. LocalFS interruption/completeness findings B16/B17 were already qualified at schema v44.

RemoteHistory behavior remains unchanged: bootstrap uses fence/enumerate/catch-up semantics, terminal committed cursors advance only with durable publications, interrupted cycles retain the previous cursor, and explicit history-gap states close the generation without pretending continuity.

Metadata-loss reconstruction remains a later canonical capability.

### A11 — stale documentation and state claims

**PASS.**

The POST-P0-01A contract and retrospective remain historical exact-head provenance for the earlier two-proof ordering. The POST-P0-01B contract explicitly states that it refines that ordering.

The revision-238 qualification checkpoint synchronizes the next objective, preflight-visible earliest remaining product gap, audit lock and retrospective selectors. No current runtime claim still requires two recovery preflights.

### A12 — dependency/reuse and nearest analogs

**PASS — NO NEW DEPENDENCY.**

The nearest recovery mechanism is SQLite itself, and Keelaryn reuses it rather than reimplementing journal recovery:

- official SQLite recovery semantics require a hot rollback journal/WAL to remain paired with the original main database; Keelaryn attempts active-family reconciliation under the original name before derived disposal/promotion;
- SQLite `integrity_check` does not validate foreign keys, so the qualified state verifier intentionally retains a separate `foreign_key_check`;
- `quick_check` omits UNIQUE and index-content checks and is therefore not an equivalent replacement for the full authority gate.

Current upstream `zombiezen.com/go/sqlite` tagged release remains v1.4.2, which is already pinned.

For search locking, Keelaryn already depends on `golang.org/x/sys` and uses its direct `flock` / `LockFileEx` primitives. Mature wrapper libraries use the same OS mechanisms; adding one here would duplicate a small existing adapter, add dependency surface, and would not replace Keelaryn-specific protected-path/ACL validation.

Watchman/fsnotify research is deliberately carried into canonical item 2 rather than being made search-recovery authority.

External sources checked during the reuse audit:

- https://www.sqlite.org/atomiccommit.html
- https://www.sqlite.org/howtocorrupt.html
- https://sqlite.org/pragma.html
- https://github.com/zombiezen/go-sqlite/releases
- https://pkg.go.dev/golang.org/x/sys/unix
- https://pkg.go.dev/github.com/dolthub/file-locks

### A13 — synthesis and finding freeze

The complete collection pass reached the end of all mandatory dimensions.

- new CRITICAL: **0**
- new BLOCKER: **0**
- new HIGH: **0**
- new MEDIUM: **0**
- new LOW: **0**
- critical development gate: **CLEAR**
- remediation cycle required: **no**

Existing carried findings remain exactly scoped:

- HIGH `AUDIT_RELEASE_H1_STATE_DB_ROLLBACK_NOT_IMPLEMENTED` — release/update gate;
- HIGH `AUDIT_RELEASE_H2_ANDROID_QUALIFICATION_ABSENT` — portability gate;
- MEDIUM `AUDIT_P0_36C_TOKENINFO_SCOPE_PREFLIGHT_AVAILABILITY` — production live-provider credential/availability gate;
- LOW `AUDIT_P0_FINAL_L1_REPOSITORY_DESCRIPTION_STALE` — housekeeping.

No current reliability/recovery finding remains that requires another substantive item-1 slice before canonical item 2.

## Closure decision

No current bounded reliability/recovery work unit remains that should precede canonical item 2.

Therefore canonical post-P0 item 1 is **complete and qualified for growth-order purposes**.

This closure is intentionally narrow:

- it does not erase later release rollback work;
- it does not claim Android support;
- it does not claim production OAuth credential availability is fully hardened;
- it does not convert future reliability discoveries into non-issues.

It means the next product capability may now be prepared in canonical order.

## Next mutation

Do **not** start item-2 product implementation directly from this retrospective.

First perform a separate state/CI phase transition that:

1. advances the top-level development phase from `POST_P0_RELIABILITY`;
2. selects canonical item 2, incremental local/provider observation;
3. updates the CI phase/product validation allowlist in the same transition;
4. preserves the item-1 closure evidence and all carried later gates;
5. qualifies the exact transition head before any item-2 product write.

Separating qualification from phase transition prevents state selectors and CI validation from drifting out of sync.
