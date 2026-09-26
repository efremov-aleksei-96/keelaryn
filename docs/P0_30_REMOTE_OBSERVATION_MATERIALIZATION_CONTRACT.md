# P0-30 — Remote Observation / Inventory Materialization Contract

**Status:** CONTRACT DECIDED / IMPLEMENTATION NEXT
**Architecture:** reuse existing ScanSession, Observation, Inventory, RemoteHistory, lifetime authority and SAME/NEW acceptance
**Live provider access:** forbidden in P0-30 implementation until later qualification
**Corpus mutation:** none

## 1. Goal

P0-29 qualified durable provider history, lifetime segmentation, Google topology/membership and identity authority. P0-30 closes the remaining bridge:

provider state at one exact durable history boundary
→ existing ScanSession
→ existing Observation rows
→ existing Inventory query
→ existing RemoteHistory identity authority
→ existing SAME / NEW acceptance when evidence permits.

P0-30 MUST NOT create a second remote inventory, second identity resolver, or provider-specific Artifact model.

## 2. Reuse-first decisions

Reuse unchanged:
- ScanSession OPEN / COMPLETE / ABORTED authority;
- Observation and Locator durable records;
- latest COMPLETE Inventory semantics;
- RemoteHistory generation / publication / membership;
- ProviderObjectLifetimeSegment;
- Google topology watermark and IN / OUT / UNKNOWN membership;
- CreateRemoteHistoryIdentityAuthority;
- AcceptNewObservationInScan;
- AcceptSameObservationInScan;
- existing Revision and ContentEvidence rules.

One new durable concept is required: a compact source-provenance sidecar binding a remote ScanSession to the exact RemoteHistory publication and deterministic metadata snapshot from which it was materialized.

This sidecar is provenance for the existing scan. It is NOT another inventory.

## 3. Why exact scan-source provenance is required

Current scan_sessions records provider, root, status and times but not RemoteHistory generation/publication.

Without durable source provenance Keelaryn cannot safely answer after interruption:
- which RemoteHistory publication an OPEN or COMPLETE remote scan represents;
- whether a timeout happened before or after completion;
- whether a retry is the same deterministic materialization or a different provider state;
- whether SAME/NEW content/identity work is being applied to the same source boundary as the Observation metadata.

Therefore P0-30A requires one immutable sidecar row per remote scan attempt.

## 4. Remote scan source binding

Conceptual source binding:

scan_id
generation_id
publication_sequence
source_scope_id
materialization_policy_id
snapshot_fingerprint_version
snapshot_fingerprint_sha256

Requirements:
- scan_id references the existing ScanSession;
- generation_id + publication_sequence references an immutable RemoteHistory publication;
- source_scope_id is provider-specific source scope evidence; for Google managed-root materialization it identifies the managed root binding used for membership;
- materialization_policy_id versions the mapping from provider snapshot facts into Observation facts;
- snapshot fingerprint is replay/provenance evidence only and MUST NOT become Artifact, Revision or ProviderObject identity;
- the sidecar is immutable after insertion;
- the existing ScanSession status remains the authority for OPEN / COMPLETE / ABORTED.

The implementation is expected to require one schema migration after v16, but the new state is a provenance sidecar, not an inventory schema.

## 5. Observation scope versus history universe

P0-29 deliberately separated provider history-universe scope from managed corpus membership. P0-30 preserves that separation.

RemoteHistory generation scope:
- identifies the provider-native change-log universe;
- remains IdentityAuthoritySet.ScopeID for the existing RemoteHistory lifetime authority.

ScanSession.Root:
- identifies the observed corpus root whose COMPLETE scan defines general inventory;
- MUST be a deterministic provider-defined canonical corpus-root locator key;
- MUST include/disambiguate provider identity domain where raw root IDs alone are not globally safe;
- for Google this represents the selected managed root, not the whole My Drive history universe unless the managed root is the universe root.

Therefore RemoteHistory authority scope and ScanSession.Root are not required to be equal.

## 6. Remote identity acceptance scope validation

The current generic acceptance path assumes authority ScopeID equals scan.Root. That remains correct for existing local/generic scans but is not correct for a managed-root scan sourced from a broader RemoteHistory universe.

When a scan has a qualified RemoteHistory source binding, final SAME/NEW mutation-boundary validation MUST instead prove:
- scan provider matches authority provider;
- source generation matches authority GenerationID;
- authority ScopeID matches that generation's provider history-universe root;
- scan.Root matches the materialized corpus-root scope selected by the source binding/provider adapter;
- observation ProviderObject ID matches authority CurrentObjectID;
- locators belong to the scan's corpus-root scope;
- source publication sequence is still the exact allowed boundary for the mutation.

No RemoteHistory authority semantics are redefined.

## 7. Deterministic metadata snapshot

P0-30 materialization consumes a provider-neutral deterministic metadata snapshot prepared for one exact source boundary.

Each in-scope entry supplies only facts actually qualified by that snapshot, sufficient to construct the existing Observation fields:
- ProviderObjectID;
- scan-scoped Locator(s);
- EntryKind;
- Size;
- Mode;
- ModifiedAt.

ObservedAt is the materialization observation time, not provider modified time.

Optional exact ContentEvidence is enrichment and is NOT part of inventory completeness.

If the provider cannot honestly supply required Observation metadata under the selected policy, the scan MUST NOT be published COMPLETE. Missing facts are not replaced by guessed zeroes or fabricated timestamps.

The first implementation uses deterministic/fake metadata snapshots. Live Google metadata mapping remains a later provider-qualification boundary.

## 8. Snapshot fingerprint

The materialization snapshot fingerprint canonically binds:
- generation ID and publication sequence;
- scan provider and corpus-root scope;
- source scope ID;
- materialization policy ID;
- ordered provider object IDs;
- ordered scan-scoped locators;
- Observation metadata facts.

It excludes ArtifactID and RevisionID because identity assignment is downstream of observation.

It also excludes optional ContentEvidence so later enrichment does not redefine inventory snapshot identity.

Same exact source boundary + policy producing a different metadata fingerprint is a reconciliation conflict, not permission to silently create a competing current inventory.

## 9. Membership completeness

For a managed-root materialization at sequence S:
1. require the exact active HistoryGeneration at S;
2. require exact topology watermark/projection verification when provider topology applies;
3. evaluate current provider membership against the selected managed root;
4. include only proven IN objects;
5. ignore proven OUT objects;
6. if any current member is UNKNOWN, do not publish a COMPLETE inventory;
7. require the metadata snapshot object set to equal the proven IN set exactly.

Inventory completeness means every proven in-scope object has an Observation. It does NOT mean every Observation already has Artifact/Revision assignment.

## 10. Locator materialization

RemoteHistory source locators remain immutable provider evidence.

The Observation materializer produces scan-scoped locator(s) suitable for the selected corpus root. A provider adapter owns this projection; Core does not rewrite arbitrary provider paths generically.

For the deterministic Google-shaped path, file-ID addressing can retain file-id/<objectID> while Root is the canonical managed corpus-root locator key.

ProviderObject identity remains the provider object ID, never the scoped locator.

## 11. Identity assignment per Observation

For each materialized IN object, use the active ProviderObjectLifetimeSegment and CreateRemoteHistoryIdentityAuthority.

Reuse existing authority decision logic; do not duplicate SAME/NEW resolution in the materializer. If a shared read-only resolver must be exposed/refactored, it must reuse the existing candidate/universe algorithm exactly.

Outcomes:
- RESOLVED_NEW → AcceptNewObservationInScan;
- RESOLVED_SAME → AcceptSameObservationInScan only when its existing evidence requirements are satisfied;
- AMBIGUOUS / UNRESOLVED → RecordObservationInScan as AssignmentUnresolved.

Exactly one Observation is created for an object in one scan attempt.

## 12. Revision / ContentEvidence boundary

Existing invariants remain unchanged:
- NEW regular file may be accepted without ContentEvidence, yielding Artifact + assigned Observation with no Revision;
- SAME regular file requires exact ContentEvidence;
- if SAME regular file lacks exact ContentEvidence, do not bypass acceptance and do not invent a Revision; persist the scan Observation unresolved/deferred;
- non-regular acceptance follows existing no-content-evidence rules.

Optional content evidence must be qualified for the same object/source state by the supplying provider mechanism. Live provider content-evidence acquisition is not introduced in P0-30A/B.

## 13. Source-bound mutation guard

Because provider history may advance while a scan is being materialized, final SAME/NEW transactions for a remote-source-bound scan MUST revalidate the scan source inside the SQLite mutation boundary.

If generation/current publication no longer equals the scan source publication, identity/revision mutation fails closed.

This prevents stale metadata or ContentEvidence from becoming accepted durable identity/revision provenance after provider history advanced.

## 14. Start / complete protocol

Start:
1. reconcile exact RemoteHistory/topology prestate;
2. validate snapshot completeness/fingerprint before durable scan start where practical;
3. StartRemoteHistoryScan atomically creates OPEN ScanSession + immutable source sidecar.

Materialize:
- deterministic object order;
- write one Observation or accepted SAME/NEW Observation per IN object;
- OPEN scan remains non-authoritative inventory.

Complete:
1. inside the completion boundary reload source binding;
2. revalidate generation is still at the exact bound publication;
3. revalidate required topology watermark/source scope;
4. only then mark ScanSession COMPLETE.

If prestate advanced, completion fails and the attempt is ABORTED/rebuilt. The previous COMPLETE inventory remains authoritative.

## 15. Interruption / replay

After timeout or process loss:
- never blind retry;
- locate OPEN/COMPLETE remote scans through their durable source binding;
- matching COMPLETE source/fingerprint => replay/return existing scan;
- matching OPEN => reconcile external/history authority; P0 may abort and rebuild instead of resuming partial observation writes;
- ABORTED attempts remain historical evidence but never current inventory.

Accepted identity decisions made during an ultimately ABORTED scan remain durable provenance. Retry reuses current lifetime binding/authority rather than rolling identity history back.

For SAME/NEW within one OPEN scan, deterministic request IDs should be derived from scan/source/object/operation semantics so an uncertain local mutation result can use existing identity-mutation replay instead of duplicate writes.

## 16. Existing local behavior remains unchanged

LocalFS StartScan/RecordObservationInScan/CompleteScan semantics remain valid and do not require RemoteHistory source rows.

Remote-source-aware scope validation is conditional on the presence of a remote scan source binding.

## 17. Implementation order

### P0-30A — source-bound remote ScanSession
- one minimal immutable remote scan-source sidecar (expected schema v17);
- StartRemoteHistoryScan;
- exact source lookup/reconcile APIs;
- CompleteRemoteHistoryScan exact publication guard;
- timeout/OPEN/COMPLETE replay tests;
- local ScanSession regression tests unchanged;
- no Observation materializer yet;
- mandatory stage retrospective after qualification.

### P0-30B — deterministic LIGHTWEIGHT_ALL materializer
- provider-neutral deterministic metadata snapshot/fingerprint;
- exact IN set validation;
- provider-specific scan-scoped locator projection boundary;
- unresolved Observation materialization into existing ScanSession/Inventory;
- UNKNOWN/missing metadata aborts COMPLETE;
- no identity assignment yet;
- mandatory stage retrospective.

### P0-30C — existing identity/revision integration
- source-bound RemoteHistory authority scope validation;
- reuse CreateRemoteHistoryIdentityAuthority;
- reuse SAME/NEW acceptance;
- regular SAME without ContentEvidence remains unresolved;
- deterministic identity mutation request IDs;
- history advance during acceptance fails closed;
- end-to-end deterministic remote inventory/identity proof;
- mandatory stage retrospective and P0-30 qualification.

## 18. Qualification matrix

P0-30 must eventually prove:
1. two managed roots in one provider history universe produce distinct current inventories;
2. provider identity domains cannot collide merely because raw managed-root IDs match;
3. every COMPLETE remote scan has immutable exact generation/publication provenance;
4. previous COMPLETE scan remains authoritative while a new scan is OPEN/ABORTED;
5. source history advance before completion prevents COMPLETE;
6. timeout after COMPLETE reconciles to the existing scan instead of blindly duplicating it;
7. exact IN set is fully represented; OUT is absent; UNKNOWN blocks COMPLETE;
8. missing required metadata blocks COMPLETE rather than fabricating Observation facts;
9. source snapshot fingerprint is deterministic and parameter-bound;
10. local ScanSession behavior is unchanged;
11. RemoteHistory authority universe and managed scan root remain separate but correctly bound;
12. NEW without content evidence may create Artifact without Revision;
13. regular SAME without content evidence remains unresolved;
14. regular SAME with exact content evidence preserves/creates Revision according to existing rules;
15. provider/history advance during SAME/NEW mutation is rejected at final transaction boundary;
16. interrupted attempt never replaces last COMPLETE inventory;
17. restart/reopen preserves source provenance and inventory authority;
18. Ubuntu 24.04 and Windows 2025 pass;
19. mandatory stage retrospective finds no open blocker before the next substantive stage.

## 19. Prior-art / reuse findings

Microsoft Graph delta demonstrates full initial enumeration followed by terminal deltaLink and local-state updates; token loss requires resynchronization rather than heuristic continuation.

Dropbox list_folder + cursor explicitly documents ordered application to a local cache and continued updates from the cursor.

Syncthing BEP separates a full Index that supersedes previous folder state from Index Update that amends only supplied entries.

Reuse the pattern:
full exact provider state + durable checkpoint + local materialized view + incremental source + resync on trust loss.

Do NOT import those systems' identity semantics. Keelaryn Artifact/Revision/lifetime authority remains the already-qualified identity layer.

## 20. Explicitly deferred

P0-30 does not authorize:
- live Google OAuth/provider reads;
- Google-specific production metadata mapping;
- content downloading solely to force SAME;
- FTS/search;
- MCP/HTTP/UI;
- Android provider adapter;
- corpus writes/moves/deletes;
- a second inventory or identity schema.
