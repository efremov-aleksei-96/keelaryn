# POST-P0-02C source-bound LocalFS observation attempt contract

**Status:** FROZEN CANDIDATE — revision 242  
**Authority:** subordinate to `KEELARYN_CANONICAL.md` and live `DEVELOPMENT_STATE.json`  
**Product mutation in this contract work unit:** none

## 1. Purpose

POST-P0-02B separated generic COMPLETE-scan chronology from the narrower LocalFS source boundary that protected search/context may treat as accepted current authority.

POST-P0-02C is the first future write-side path that may eventually replace the bootstrap accepted source with a post-bootstrap accepted LocalFS scan.

That path is high risk because identity mutation can become durable while a scan is still OPEN. A safe implementation therefore needs durable source provenance **before the first identity mutation**, deterministic interruption recovery, and a distinct accepted-publication contract.

This document freezes those requirements before any 02C schema/runtime mutation.

## 2. Current facts that constrain the design

### 2.1 Existing local_ingest_commits cannot be the OPEN-attempt authority

Schema v44 `local_ingest_commits` is a final receipt.

Its scope guard requires the referenced scan to already be:

- the exact provider/root/start boundary;
- `COMPLETE`;
- equipped with a non-null finish time.

Therefore it cannot prove which source an OPEN scan was created from before SAME/NEW identity mutation starts.

A later receipt cannot retroactively make earlier identity mutations source-bound.

### 2.2 Generic StartScan is not source provenance

`Store.StartScan` creates an OPEN `scan_sessions` row and nothing else that proves:

- the predecessor accepted source used for reconciliation;
- the exact LocalFS snapshot that was observed;
- the fingerprint contract under which that snapshot was obtained;
- whether this scan is eligible for the future accepted LocalFS lifecycle.

An ordinary OPEN scan must therefore remain ineligible for 02C identity/publication behavior.

### 2.3 Current LocalFS has no durable ProviderObject identity

`internal/provider/localfs` intentionally keeps platform file identity ephemeral.

Current observations use:

- `ProviderObject.IdentityState = UNRESOLVED`;
- no durable `ProviderObjectID`.

Go `os.SameFile` data is held only in an in-memory Snapshot and is not serialized.

By contrast, hardened `AcceptSameObservationInScan` / `AcceptNewObservationInScan` require an observed non-empty ProviderObject ID.

POST-P0-02C must not bypass this requirement by fabricating path/hash-derived IDs or by persisting an unstable native ID under stronger semantics than the provider can prove.

### 2.4 Current LocalFS reconciliation evidence is SUPPORTING only

Existing LocalFS candidate evidence deliberately remains non-authoritative:

- locator overlap → SUPPORTING;
- equal content → SUPPORTING;
- `os.SameFile` match → SUPPORTING;
- native mismatch is not durable proof of global distinctness.

`corpus.ResolveContinuity` confirms SAME/DISTINCT only from non-conflicting CONCLUSIVE evidence.

Therefore current LocalFS reconciliation output cannot be inserted into `IdentityAuthoritySet` merely by relabeling it CONCLUSIVE.

The contract explicitly forbids that shortcut.

## 3. Architectural decision: split POST-P0-02C into three bounded slices

POST-P0-02C is not one monolithic mutation.

The safe order is:

```text
02C1 durable OPEN-attempt provenance
→ 02C2 qualified LocalFS identity authority
→ 02C3 guarded accepted LocalFS publication
```

Each later slice depends on the preceding qualification.

This split is intentional: it lets durable attempt/recovery mechanics be proved without simultaneously inventing LocalFS identity semantics.

## 4. POST-P0-02C1 — durable LocalFS OPEN-attempt provenance

02C1 is the first product implementation slice.

It may add the minimum durable schema/API required to bind an OPEN LocalFS scan to its exact source prestate.

The closest internal analogue is `remote_scan_sources`, but LocalFS semantics remain separate from RemoteHistory.

### 4.1 Required source binding

At attempt creation, one durable immutable source record must bind at least:

- exact `scan_id`;
- provider ID;
- canonical root;
- scan start time;
- exact predecessor **accepted** LocalFS source boundary;
- current source fingerprint version;
- current source fingerprint SHA-256;
- source/policy contract identifier if needed to make the meaning unambiguous.

The predecessor is the accepted source selected by the qualified 02B rule, not generic `LatestCompleteScan`.

A later unresolved ordinary COMPLETE scan must not become the predecessor merely because it is chronologically newer.

### 4.2 Content-aware initial source fingerprint

The existing ordinary SCAN `localfs-snapshot:v1` payload is metadata/membership evidence and is not sufficient as the new identity-mutation prestate contract.

02C1 therefore requires a **distinct content-aware source fingerprint contract** for the OPEN attempt.

The exact constant/name may be selected by the bounded implementation, but its semantics must bind:

- provider/root;
- observation time;
- complete membership/grouping;
- relevant filesystem metadata;
- content evidence for regular-file object groups.

The purpose is correctness, not performance. Full scanning/hashing remains an acceptable baseline before any watcher/journal optimization.

Do not overload the existing metadata-only ordinary SCAN v1 meaning with stronger semantics.

### 4.3 Atomic creation

The OPEN scan and its source provenance must be created in one durable transaction.

There must be no committed state where a source-bound 02C attempt exists as a generic OPEN scan without its provenance record.

Raw SQL must not be able to mint qualified attempt provenance without the same narrow application-authority pattern used elsewhere in the state store.

### 4.4 Exact replay and conflict

If the process restarts and the same attempt request is repeated:

- exact provider/root/start/predecessor/source-fingerprint prestate may return the existing OPEN attempt;
- conflicting source fingerprint or predecessor must fail closed;
- a new scan must not be silently created while the prior source-bound attempt remains unresolved.

The durable scan ID is the recovery handle.

### 4.5 Generic terminal operations

A source-bound LocalFS attempt must not be publishable through ordinary `CompleteScan`.

02C1 must add a fail-closed guard analogous in spirit to the remote source-bound completion guard.

02C1 contains **no identity mutations**, so a source-changed attempt with zero identity mutation receipts may be safely terminated through an explicitly qualified abort/retry path.

Later slices must narrow abort semantics once partial SAME/NEW mutations become possible.

## 5. POST-P0-02C1 explicitly does not do identity mutation

02C1 must not:

- create an IdentityAuthoritySet for LocalFS;
- call `AcceptSameObservationInScan`;
- call `AcceptNewObservationInScan`;
- persist a made-up LocalFS ProviderObject ID;
- reinterpret path, hash or `os.SameFile` as CONCLUSIVE evidence;
- publish an accepted SCAN;
- change protected search/context accepted-source selection;
- add fsnotify, Watchman, USN or another watcher/journal dependency.

Its job is provenance and recoverability only.

## 6. POST-P0-02C2 — LocalFS identity authority is a separate Sol gate

Before SAME/NEW becomes reachable from LocalFS, a later Sol-qualified slice must define how LocalFS obtains authority that satisfies the existing hardened identity model.

The authority must answer both questions separately:

1. what durable ProviderObject/lifetime identity is being named;
2. what evidence is sufficient to resolve SAME or NEW against the predecessor universe.

### 6.1 Forbidden shortcuts

The following remain forbidden:

- path as ProviderObject ID;
- content hash as Artifact identity;
- inode/file index persisted as globally stable identity without a qualified lifetime/gap contract;
- caller assertion that SUPPORTING evidence is CONCLUSIVE;
- "no locator-overlap candidate" as proof of NEW;
- "same bytes at same path" as automatic SAME.

### 6.2 Candidate-universe completeness

`RESOLVED_NEW` requires a qualified COMPLETE candidate universe.

A locator-only candidate subset is not a complete predecessor universe because a prior Artifact may have moved.

Any future LocalFS NEW policy must therefore prove completeness under its exact identity/lifetime contract rather than infer it from absence of a cheap candidate.

### 6.3 Portability

Windows/Linux/Android differences remain behind provider adapters.

A Windows USN/File-ID based accelerator may later produce stronger provider-specific evidence only under an explicit journal/lifetime/gap contract.

It must not become the cross-platform baseline by accident.

Android SAF document identity belongs to a distinct provider adapter and is not a reason to serialize POSIX identity into Core.

## 7. POST-P0-02C3 — accepted LocalFS scan publication

Only after 02C2 provides qualified identity authority may a LocalFS attempt become a new accepted current source.

Accepted publication requires, in one guarded terminal transaction:

1. the exact source-bound OPEN attempt is still current and internally valid;
2. every occurrence intended for the accepted inventory has a qualified terminal identity outcome;
3. unresolved/ambiguous occurrences prevent accepted publication;
4. the complete source is re-read and re-fingerprinted under the exact attempt contract;
5. the final physical-source fingerprint exactly matches the attempt fingerprint;
6. the scan transitions to COMPLETE;
7. an immutable accepted-SCAN receipt is written under a **distinct qualified contract**;
8. the resulting accepted boundary is deterministically ordered;
9. failure rolls back the terminal publication rather than leaving an accepted half-state.

An unresolved observation scan may remain useful chronology/evidence, but it must never displace the previous accepted search/context source.

## 8. Accepted versus unaccepted completion

POST-P0 item 2 must preserve two separate concepts:

```text
COMPLETE scan chronology
!=
accepted current LocalFS source
```

A scan may be historically COMPLETE without being accepted.

The 02B selector is the proof boundary that prevents this distinction from being lost.

Future 02C3 work may extend that selector to a qualified accepted-SCAN contract. Existing metadata-only SCAN v1 receipts remain permanently non-accepted unless a deliberate migration with equivalent evidence is separately designed; this contract authorizes no such migration.

## 9. Interruption model

The durable source-bound attempt exists specifically so interruption is not handled by blind retry.

### Before any identity mutation

If source drift is detected and there are no identity mutation receipts for the attempt, a guarded abort/retry may discard the attempt as non-current evidence and create a new attempt from fresh source state.

### After identity mutation becomes possible in later slices

Once any SAME/NEW mutation has committed:

- identity state is durable and is not rolled back by changing the scan status;
- a successor attempt must not blindly rerun NEW with fresh request IDs;
- recovery must reconcile exact mutation receipts and the source-bound attempt first;
- source drift cannot be converted into silent abort-and-restart;
- duplicate NEW admission must remain impossible.

02C1 does not implement this later behavior; it must leave enough durable provenance for 02C2/02C3 to implement it correctly.

## 10. Search/context behavior during an OPEN or unaccepted attempt

Protected search/context continue using the last qualified AcceptedLocalSource.

While an attempt is:

- OPEN;
- ABORTED;
- COMPLETE but unaccepted;
- source-drifted;
- identity-unresolved;
- identity-ambiguous;

it must not replace the prior accepted boundary.

This gives users a stable last-known accepted inventory while observation/reconciliation is in progress.

## 11. Nearest internal reuse

Reuse before invention:

- `remote_scan_sources` — durable immutable source binding attached to OPEN scan;
- remote guarded completion — source revalidation before terminal COMPLETE;
- `identity_mutation_requests` — exact replay fingerprint/idempotency receipts;
- `AcceptSameObservationInScan` / `AcceptNewObservationInScan` — hardened identity transactions, but only after a qualified LocalFS authority producer exists;
- `scan_completion_authorities` — deterministic COMPLETE ordering;
- `local_ingest_commits` — immutable final LocalFS receipt, not OPEN provenance;
- `searchsqlite.SourceBoundary` — existing accepted derived-search binding;
- 02B `InventoryAtScan` — exact accepted historical inventory.

No duplicate generic scan/source/identity subsystem should be introduced.

## 12. External analogue posture

External mechanisms remain optional accelerators:

- fsnotify: dirty/wakeup hints, not durable history authority;
- Watchman: clock/since/fresh-instance/recrawl semantics are useful for gap detection but a daemon is not required by the baseline;
- Windows USN Change Journal: possible Windows-specific durable change source under journal-ID/USN continuity validation;
- Android SAF/DocumentsProvider: separate provider identity/access model.

The first safe 02C path remains full-snapshot correctness-first.

## 13. First implementation slice after this contract

The only product write unlocked by qualification of this contract is:

**POST_P0_02C1_LOCAL_ATTEMPT_PROVENANCE**

Required scope:

- minimum schema and Store APIs for immutable LocalFS OPEN-attempt source provenance;
- atomic OPEN + provenance creation;
- exact predecessor accepted-source binding;
- content-aware exact current-source fingerprint;
- exact replay and conflicting replay rejection;
- generic COMPLETE bypass rejection;
- safe zero-identity-mutation abort/retry behavior;
- recovery/adversarial tests;
- schema migration/open verification as required by Keelaryn policy.

Explicitly out of scope:

- LocalFS SAME/NEW;
- LocalFS identity-authority producer;
- accepted-SCAN receipt/publication;
- accepted-source selector extension;
- watcher/journal integration;
- RemoteHistory changes.

## 14. Qualification

Revision 242 qualifies this contract only when:

- diff contains only `DEVELOPMENT_STATE.json` and this contract;
- temporary work marker is absent from the handoff;
- exact-head validate + Ubuntu 24.04 + Windows 2025 pass;
- exact-head review finds no contradiction with 02A/02B, identity authority, replay/recovery or provider-neutral invariants.

Only then may POST-P0-02C1 product/schema implementation begin.
