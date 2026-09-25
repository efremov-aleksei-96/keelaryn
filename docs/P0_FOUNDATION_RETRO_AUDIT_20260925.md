# P0 Foundation Retrospective Audit — 2026-09-25

Status: **HARDEN BEFORE LIVE PROVIDER WIRING**

Authority: `KEELARYN_CANONICAL.md` remains product architecture authority. This audit narrows what previous P0 qualifications actually proved and records corrections required before runtime/API/live-provider wiring.

Evidence basis:
- authoritative branch: `dev/corpus-first-p0`;
- audited head: `21217a626b328d7de6487555e8ac7d6892a72707`;
- exact-head CI `36109751766`: validate PASS, Ubuntu 24.04 PASS, Windows 2025 PASS;
- read-only exact-head call-site audit: acceptance methods have no non-test runtime call sites yet;
- external analog review: Syncthing delta indexes, rclone bisync recovery, Google Drive Changes, Microsoft Graph delta, Dropbox list_folder cursors, Perkeep permanodes/claims, AWS/Stripe idempotency semantics.

No corpus or live-provider mutation was performed.

## What remains sound

### Artifact identity model

The central model remains correct:
- Artifact identity is independent from path, content hash and provider object ID;
- Revision identity is subordinate to Artifact;
- copy is not move;
- ambiguity is first-class;
- provider-native identity has explicit semantics rather than universal trust.

Perkeep independently supports the value of a random stable logical anchor plus immutable provenance/claims, even though Keelaryn correctly does not adopt Perkeep's CAS-first storage authority.

### Transactional SQLite direction

Atomic Artifact/Revision/Observation/provenance writes are the correct direction.

P0-20 and P0-27 tests prove transaction mechanics and rollback behavior for the inputs they receive.

### RemoteHistory paging/cursor discipline

P0-23/P0-24 correctly separate:
- intermediate pagination/continuation;
- terminal future cursor;
- complete success;
- gap/invalid/scope/insufficient-history failures.

Google Drive, Microsoft Graph and Dropbox independently use the same broad initial-state + cursor + incremental-update pattern.

rclone bisync reinforces the fail-closed recovery principle: retain last-known-good state, use locks/recovery snapshots, and do not let an interrupted/uncertain run silently become new authority.

## Finding F1 — acceptance trusts caller-authored evidence too much

Severity: **BLOCKER BEFORE PRODUCT/RUNTIME WIRING**

Current behavior:
- `AcceptResolvedObservationInScan` recomputes a supplied `CandidateSetResolution`, but `DecisionEvidence.Strength` and `Source` are still caller-provided data.
- `AcceptResolvedNewObservationInScan` validates a supplied `CandidateUniverseProof`, but `COMPLETE` plus `EvidenceRefs` are still caller-provided claims.

Therefore internal consistency is proven, but provenance authority is not.

A caller able to construct these structs can currently manufacture:
- `CONCLUSIVE` evidence;
- a syntactically valid `COMPLETE` universe proof.

This is acceptable only as a deterministic mechanism spike. It MUST NOT become a product trust boundary.

Required correction:
- authority-bearing evidence must be loaded/revalidated from durable qualified state inside the mutation transaction, or represented by a durable authority record that the transaction validates;
- arbitrary strings must not upgrade evidence strength;
- future AI/API callers must never be able to set `CONCLUSIVE` or `COMPLETE` directly.

P0-20/P0-27 remain qualified for transaction mechanics, not for an exposed trust boundary.

## Finding F2 — RESOLVED_SAME lacks replay identity

Severity: **BLOCKER BEFORE RUNTIME WIRING**

P0-27 added caller-supplied `AdmissionRequestID`, but P0-20 `AcceptResolvedObservationInScan` has no stable request/decision key supplied before mutation.

If a commit succeeds and the caller loses the response, blindly replaying the SAME acceptance can create another Observation and accepted decision. Revision creation is largely protected by content idempotence, but duplicate durable observations/provenance remain possible.

Required correction:
- add a stable `ContinuityRequestID` (or a unified identity-decision request ID);
- accepted SAME decisions must be reconcilable by request ID after interruption;
- retry of the same request must not create a second durable observation/decision.

## Finding F3 — idempotency keys must be bound to request meaning

Severity: **HIGH**

P0-27 prevents the same `AdmissionRequestID` from minting twice, but it does not yet compare a replay's semantic parameters with the original request.

AWS and Stripe use the stronger established pattern:
- same idempotency token + same parameters => return/reconcile original result;
- same token + different parameters => explicit parameter-mismatch error.

Required correction:
- persist a canonical request fingerprint or exact immutable request semantics with each accepted identity mutation;
- request-ID reuse with different scope/object/policy/evidence authority must fail as mismatch;
- same request replay should return/reconcile the original accepted result, not merely say "already accepted".

Do not derive Artifact identity from this fingerprint.

## Finding F4 — naked provider-object binding is stronger than the Drive contract

Severity: **BLOCKER BEFORE LIVE DRIVE**

Current P0-27 binding key:
`(identity_domain, provider_id, native_object_id) -> Artifact`.

Google Drive P0-21 intentionally classifies file IDs as `STABLE_FOR_RESOURCE_LIFETIME`, not globally non-reusing forever.

A Drive `REMOVED` change can mean deletion **or loss of access**. Therefore a binding cannot automatically remain conclusive SAME across an arbitrary disappearance and later reappearance of the same ID.

Required correction:
- bindings need continuity/lifetime context, not only the naked provider ID;
- a removal/disappearance must break automatic stable-lifetime SAME unless a qualified provider rule proves continuity;
- historical binding provenance should be retained even when current continuity becomes unknown.

## Finding F5 — stream completeness and object continuity are different facts

Severity: **BLOCKER BEFORE LIVE DRIVE**

Current type `ProviderHistoryCoverage=CONTINUOUS` is used by provider identity evidence, while RemoteHistory cycles also emit that same coverage after a terminal complete cycle.

These are not equivalent.

A stream interval may be completely observed while one object is:
`UPSERT -> REMOVED -> UPSERT`.

The stream is complete, but the object's resource-lifetime continuity is broken/unknown. Passing stream coverage directly into `GoogleDriveFileIDContract` would overstate SAME.

Required correction:
- separate **stream publication completeness** from **per-object unbroken continuity**;
- SAME for a stable-for-resource-lifetime ID requires an object-specific interval with no disappearance/replacement break.

## Finding F6 — introduce history generations/epochs

Severity: **HIGH**

Syncthing's delta-index protocol provides a directly reusable idea:
- each index has a random Index ID;
- sequence numbers advance within that index;
- if the index is reset, a new Index ID is generated;
- `{Index ID, max sequence}` identifies a point in that index history.

Keelaryn should use the analogous local concept for provider history:
- a complete bootstrap creates a durable `HistoryGenerationID` / epoch;
- committed cursors advance only inside that generation;
- GAP / invalid cursor / insufficient history closes the generation;
- rebootstrap creates a new generation;
- equal stable-lifetime provider IDs across generations do not automatically prove SAME.

This is local Keelaryn evidence identity, not a replacement for the opaque provider cursor.

## Finding F7 — provider-object presence needs a lifetime segment

Severity: **HIGH**

Within one valid history generation, each provider object needs derived presence continuity:
- first present;
- continuously present through committed publications;
- removed/out-of-scope;
- possible later reappearance.

For a provider ID whose contract is only stable-for-resource-lifetime:
- uninterrupted presence segment can support conclusive SAME;
- `REMOVED` closes/suspends that segment;
- later same-ID appearance starts a new/unknown segment unless stronger provider semantics prove otherwise.

This avoids silently treating "same string ID after disappearance" as same Artifact.

## Finding F8 — RemoteHistory is not a full Observation

Severity: **HIGH / P0-28 DESIGN**

RemoteHistory currently carries provider object ID + locators, not enough metadata to fabricate a full Keelaryn Observation.

Do not synthesize size/kind/modified time from absence. For example, Google Drive `size` is not a universal property of every Drive item.

Required layering:
```text
RemoteHistory publication
→ durable provider identity/membership evidence
→ provider metadata/content observation
→ SAME/NEW resolution
→ Artifact/Revision acceptance
```

Do not force history events into `ObservationRecordInput`.

## Finding F9 — "first-known" wording is too strong

Severity: **MEDIUM**

An object can have earlier durable unresolved observations and only later receive its first accepted Artifact identity.

Therefore `RESOLVED_NEW` should mean:
> no accepted predecessor Artifact is justified under the qualified policy; allocate the first accepted Artifact identity for this provider-object lifetime/segment.

It does not necessarily mean:
- first physical creation;
- first time Keelaryn ever observed the object.

Documentation/state should stop using "first-known" where that distinction matters.

## Finding F10 — bootstrap crash replay remains a later reliability gap

Severity: **MEDIUM / DEFERRED UNTIL AFTER CURRENT CORRECTNESS HARDENING**

`AdoptObservationInScan` is atomic per occurrence, but bootstrap as a multi-occurrence workflow has no durable per-occurrence idempotency key/resume protocol.

A process crash can leave an OPEN partially populated bootstrap scan that requires reconciliation rather than a blind rerun.

This does not invalidate the current minimal happy-path proof, but it must be addressed before claiming interruption-safe autonomous product ingestion.

## Reuse decisions from the retrospective

### Syncthing — reuse concept directly

Borrow:
- generation/index identity separate from sequence/cursor;
- reset creates a new generation;
- full index vs index update distinction;
- durable local metadata DB rather than path-only state.

Do not copy:
- path-centered file identity semantics into Artifact identity.

### rclone bisync — reuse safety/recovery patterns

Borrow:
- last-known-good snapshot;
- lock/recovery discipline;
- interruption does not automatically advance trusted state;
- explicit resync/recovery when history cannot be trusted.

Do not use bisync as identity authority or mutation engine for P0.

### Google Drive / Graph / Dropbox — reuse provider delta semantics

Borrow:
- complete initial state;
- opaque continuation;
- terminal durable cursor;
- deletions/removals as explicit feed events;
- provider item IDs as provider identities subject to each provider's documented guarantees.

Do not generalize one provider's ID lifetime guarantee to another.

### AWS / Stripe — reuse idempotency semantics

Borrow:
- caller request token;
- persisted original request semantics/fingerprint;
- exact replay returns/reconciles original result;
- same token with different parameters is an explicit mismatch.

### Perkeep — retain design validation

Borrow:
- durable logical identity anchor separated from mutable claims/provenance.

Do not adopt CAS as corpus authority.

## Revised implementation order

Do not continue directly to live RemoteHistory publication.

1. **P0-28A — identity acceptance hardening contract**
   - trusted durable evidence references;
   - unified replay/idempotency semantics;
   - request fingerprint/mismatch;
   - precise NEW wording.

2. **P0-28B — history generation/publication model**
   - stream generation ID;
   - committed publication/cursor;
   - atomic current membership;
   - gap closes generation;
   - no fabricated Observation metadata.

3. **P0-28C — provider-object lifetime segments + binding integration**
   - object-specific uninterrupted continuity;
   - bindings scoped to lifetime segment/evidence;
   - removal/reappearance fail closed;
   - SAME/NEW acceptance revalidates durable authority inside transaction.

4. Only then wire deterministic Google Drive RemoteHistory into the durable pipeline.

5. Live OAuth/read-only Drive qualification comes later.

## Qualification interpretation

Previous green CI remains valid evidence for the mechanics it tested.

The retrospective does **not** claim those commits were useless or incorrect. It narrows their qualification scope:
- mechanics: qualified;
- live/exposed trust boundary: not yet qualified;
- provider-history lifetime integration: not yet qualified.

Because current runtime has no non-test call sites for SAME/NEW acceptance, these corrections can be made before compatibility becomes expensive.
