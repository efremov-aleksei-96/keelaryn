# P0-26 — Post-bootstrap new-Artifact admission contract

Status: **RESEARCH COMPLETE / CONTRACT DECIDED**

Authority: `KEELARYN_CANONICAL.md` remains the product architecture authority. This document defines the minimum P0 implementation contract for the next identity slice.

Evidence basis:
- repository head before this decision: `952e6d0508e469c094b078ae04fba844bfdeb008`;
- exact-head CI `36108179380`: validate PASS, Ubuntu 24.04 PASS, Windows 2025 PASS;
- current qualified building blocks: P0-20 `RESOLVED_SAME` acceptance, P0-21 provider-ID semantics, P0-23 RemoteHistory, P0-24 Google Drive history/client binding.

## Problem

Bootstrap adoption can create an Artifact only while a provider/root has no observation history.

After bootstrap:
- `AcceptResolvedObservationInScan` can assign an occurrence only when a candidate set is already `RESOLVED_SAME`;
- absence of a path candidate is deliberately not identity evidence;
- content equality is deliberately not Artifact identity;
- therefore a genuinely new occurrence cannot yet become a new Artifact safely.

The missing operation is **identity admission**, not another continuity heuristic.

## Core distinction

`NEW Artifact` does **not** mean "the physical file was created now."

It means:

> Under one explicit, provenance-bearing identity policy, Keelaryn has sufficient evidence that the current occurrence has no acceptable predecessor among the universe of predecessors that policy declares relevant, so allocation of a new Artifact identity is safe.

A file may have existed before entering the managed scope. The accepted fact is only that this occurrence is **first-known / new-to-Keelaryn under the qualified policy**.

## Reuse research

### Google Drive

Current Drive v3 documentation provides the primitives already selected in P0-22/P0-24:
- file IDs are unique per file and stable for the file lifetime;
- `changes.getStartPageToken` supplies a future-change fence;
- `changes.list` exposes `fileId`, current file state and removals;
- `nextPageToken` is pagination state;
- terminal `newStartPageToken` is the future cursor;
- removal may mean deletion **or loss of access**, so it is not a physical-delete proof;
- copy creates a new file resource and may use a separately generated file ID.

Sources reviewed:
- Google Drive "Files and folders overview";
- Drive v3 `changes.list`;
- Drive v3 `changes` resource;
- Drive "Retrieve changes";
- Drive "Create and manage files".

### Microsoft Graph

Graph `driveItem/delta` independently validates the abstraction:
- the initial delta walk enumerates current state;
- `@odata.nextLink` is intermediate pagination;
- terminal `@odata.deltaLink` is used for future changes;
- Microsoft explicitly states that initial `delta` is the guaranteed method for constructing a complete local representation while writes may occur;
- deleted items are represented by a deleted facet;
- drive items are addressed by ID and move/rename updates the same item.

This supports a provider-neutral "complete universe + continuous history" proof rather than a Drive-specific rule.

### Dropbox

Dropbox independently exposes:
- `list_folder` initial entries;
- a cursor consumed by `list_folder/continue`;
- deletion metadata in the ordered update stream;
- unique file IDs;
- file-ID-based revision queries that remain useful across moves/renames.

Again, the reusable idea is cursor-backed local-state completeness, not path absence.

### Decision

No third-party library is needed for this Core decision model.

Reuse:
- provider delta/cursor semantics as evidence sources;
- existing Keelaryn `CandidateSetResolution`, provider identity contracts and RemoteHistory coverage.

Do **not** import a sync engine merely to decide Artifact admission.

## Provider-neutral identity outcome

Do not extend `ContinuityDecision` to mean "continuity with nothing."

Introduce a higher-level occurrence identity result that composes existing candidate continuity with an explicit candidate-universe proof.

Conceptual states:

```text
UNRESOLVED
AMBIGUOUS
RESOLVED_SAME
RESOLVED_NEW
```

- `RESOLVED_SAME` continues to name one existing Artifact.
- `RESOLVED_NEW` authorizes allocation of a new Artifact.
- `AMBIGUOUS` remains first-class.
- `UNRESOLVED` is the fail-closed default.

The existing `CandidateSetResolution` remains unchanged and reusable.

## Candidate-universe completeness

`RESOLVED_NEW` requires an additional proof that the relevant predecessor universe is complete under the exact admission policy.

Conceptual proof:

```text
CandidateUniverseProof
    policy_id
    provider_id
    identity_domain
    scope/history_stream
    coverage:
        UNKNOWN
        COMPLETE
    durable evidence reference(s)
```

`COMPLETE` is a strong claim and MUST come from a qualified evidence source. It cannot be inferred from:
- no path match;
- no content-hash match;
- an empty candidate list;
- a successful directory enumeration without a race-free boundary;
- AI inference;
- user naming conventions.

A policy may resolve `NEW` only when:
1. the current occurrence and proof scopes match exactly;
2. the candidate-universe proof is `COMPLETE`;
3. the candidate resolution contains no plausible `SAME` predecessor;
4. every represented predecessor candidate is conclusively distinct, or the complete universe legitimately contains zero predecessor candidates;
5. no durable accepted binding already associates the current provider-native identity with an existing Artifact in the relevant identity domain;
6. the proof is reproducible from retained provenance.

If completeness is unknown, `NEW` is not authorized.

## Drive P0 admission policy

The first concrete producer of `COMPLETE` may be Google Drive.

A Drive policy can prove candidate-universe completeness only from qualified RemoteHistory state:
- a complete bootstrap/baseline was atomically published with its terminal cursor;
- every subsequent committed cycle from that cursor is `CONTINUOUS`;
- current stream/scope/identity-domain bindings are exact;
- the current file ID is checked against durable accepted bindings in that identity domain.

Expected outcomes:
- same file ID with an existing binding + continuous history -> normal `RESOLVED_SAME` path;
- same file ID with an existing binding but a history gap -> not `NEW`; continuity remains fail-closed/ambiguous;
- a first-known file ID after complete baseline + continuous history, with no accepted prior binding -> eligible for `RESOLVED_NEW`;
- a copied file with identical bytes but a distinct qualified file ID -> eligible for a new Artifact once universe completeness is proven;
- `removed` never by itself proves physical deletion.

The policy records **first-known identity under this stream/policy**, not physical creation time.

## Local filesystem P0 behavior

The current local filesystem provider has no durable native identity/history source strong enough to prove a complete post-bootstrap predecessor universe across arbitrary observation gaps.

Therefore:
- local post-bootstrap absence of candidates MUST remain unresolved;
- a new path MUST NOT automatically mint an Artifact;
- identical/different content MUST NOT decide NEW;
- P0-26 does not weaken this to make the demo easier.

Later options may include:
- qualified filesystem journal/history;
- stronger persistent native identity contracts where the OS/provider genuinely guarantees them;
- explicit user-reviewed admission;
- another provenance-bearing policy.

## Atomic acceptance transaction

The next implementation slice should add a separate new-Artifact admission transaction.

On a valid `RESOLVED_NEW` input it atomically:
1. validates the identity outcome and complete-universe proof;
2. validates open scan and exact provider/root/scope;
3. rechecks that no accepted prior binding now exists at the mutation boundary;
4. creates one new Artifact;
5. creates Revision 1 when valid current content evidence exists;
6. records the assigned Observation;
7. records non-rebuildable accepted admission provenance including policy, proof and decision;
8. commits all outputs together.

On any validation failure it performs zero identity mutation.

The acceptance record must distinguish:
- accepted continuity to an existing Artifact; and
- accepted admission of a new Artifact.

Do not overload `AcceptedContinuityRecord` with a fake predecessor.

## Replay / interruption safety

A post-bootstrap admission creates non-rebuildable identity, so blind replay must not be able to mint a second Artifact.

The implementation MUST provide a durable reconciliation/deduplication boundary for one admission request/decision. A stable caller-supplied decision/request identity is preferred over generating the only decision identifier after entering the transaction.

After interruption, callers reconcile accepted admission provenance before retrying.

## Deferred

P0-26 does not:
- perform live OAuth;
- mutate any corpus/provider;
- implement cross-provider Artifact continuity;
- infer physical creation/deletion time;
- add FTS/MCP/web UI;
- make localfs path absence sufficient for NEW.

Those remain later slices.

## Next implementation target

Implement the provider-neutral identity-admission model and SQLite atomic `RESOLVED_NEW` transaction with deterministic fake completeness proofs first.

Only after that is qualified should Google Drive RemoteHistory be wired end-to-end as the first real completeness-proof producer.
