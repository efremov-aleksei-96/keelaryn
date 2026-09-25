# P0-28A — Identity Acceptance Hardening Contract

Status: **CONTRACT DECIDED / IMPLEMENTATION NEXT**

Basis:
- foundation retrospective: `docs/P0_FOUNDATION_RETRO_AUDIT_20260925.md`;
- audited exact head: `467b4e810041532ed39e47dd8b5c16a98c3df5dc`;
- exact-head CI `36110946306`: validate PASS, Ubuntu 24.04 PASS, Windows 2025 PASS;
- current SAME/NEW acceptance functions have no non-test runtime call sites, so this boundary can be corrected before compatibility debt exists.

## 1. Goal

Turn P0-20/P0-27 from mechanism-level acceptance APIs into a mutation boundary that cannot be authorized by caller-authored strings or booleans.

The hardened boundary must provide:

```text
stable request identity
+ request semantic fingerprint
+ durable trusted authority references
+ in-transaction authority revalidation
+ in-transaction SAME / NEW derivation
+ atomic mutation/provenance
+ deterministic replay reconciliation
```

## 2. Caller data versus authority

Upper layers may submit:
- the proposed physical/provider occurrence;
- observed metadata/content evidence;
- a stable mutation request ID;
- references to already durable authority records;
- supporting hints that cannot authorize identity mutation.

Upper layers MUST NOT be able to authorize mutation by supplying:
- `EvidenceStrength=CONCLUSIVE`;
- `CandidateUniverseCoverage=COMPLETE`;
- a preselected `RESOLVED_SAME` / `RESOLVED_NEW`;
- an arbitrary policy/source string claiming authority.

The SQLite mutation transaction loads the referenced authority records and derives the result itself.

## 3. Durable authority reference

Introduce an opaque, durable authority identifier concept, for example:

```text
IdentityAuthorityID
```

An authority record is non-rebuildable evidence/provenance that some qualified producer established one narrowly-scoped fact.

The record carries at least:
- authority ID;
- authority kind/version;
- policy ID;
- provider ID;
- identity domain;
- scope/history generation/lifetime segment when applicable;
- subject provider-object ID;
- optional predecessor Artifact/object relation;
- normalized direction/fact;
- source durable reference(s);
- creation timestamp;
- validity/closure state where the authority can expire or be broken.

Production acceptance accepts only authority IDs, not raw authority-bearing strength flags.

### Producers

Each authority kind has a source-specific producer.

Examples planned:
- provider-history generation / object-lifetime segment;
- provider-native identity comparison validated from durable history state;
- future qualified local filesystem journal/native-identity source;
- explicit reviewed human decision if/when a product workflow is defined.

A generic method that accepts arbitrary `CONCLUSIVE` is prohibited.

## 4. SAME acceptance

Replace the current caller-resolved SAME API with an intent similar to:

```text
AcceptSame(request, authorityRefs...)
```

Inside one SQLite transaction:

1. compute/verify the request fingerprint;
2. reconcile request ID;
3. load scan + occurrence scope;
4. load every referenced authority record;
5. validate policy/scope/domain/object/Artifact relations;
6. derive candidate continuity from those durable authorities;
7. require one uniquely justified SAME Artifact;
8. revalidate provider binding/lifetime state at the mutation boundary;
9. apply Revision/Observation/provenance atomically;
10. persist the accepted request fingerprint and result.

The caller does not select an Artifact merely by constructing a `CandidateSetResolution`.

## 5. NEW acceptance

Replace raw caller-supplied COMPLETE proof with durable candidate-universe authority.

Inside one transaction:

1. reconcile request ID/fingerprint;
2. load exact complete-universe authority;
3. require the authority to be current for this provider/domain/scope/history generation;
4. load all relevant predecessor/binding authority required by the policy;
5. prove no acceptable SAME predecessor;
6. only then derive `RESOLVED_NEW`;
7. allocate Artifact + optional Revision 1 + Observation + provider binding + accepted provenance atomically.

Precise meaning:

> `RESOLVED_NEW` authorizes the first **accepted Artifact identity for the current provider-object lifetime/identity segment under the qualified policy**.

It does not mean:
- physical creation time;
- first-ever observation by Keelaryn;
- absence of a matching path/hash.

## 6. Unified request identity

Use one conceptual request identity for identity mutations, e.g.:

```text
IdentityMutationRequestID
```

SAME and NEW share the same replay contract.

The request ID is:
- caller generated before mutation;
- opaque;
- not Artifact identity;
- not derived from content/path/provider ID.

## 7. Request fingerprint

Every accepted identity mutation stores a versioned semantic fingerprint.

The fingerprint must bind at least:
- operation kind/version;
- scan/session ID;
- provider + root/scope;
- provider-native occurrence identity where available;
- normalized locators;
- relevant observed metadata/content evidence;
- referenced authority IDs;
- target Artifact for SAME, if that target is part of the derived accepted result;
- policy/version.

Arrays are sorted/canonicalized before hashing.

Use a versioned canonical encoding and SHA-256 only as an **idempotency fingerprint**, never as Artifact/Revision identity.

## 8. Replay semantics

Borrow the established AWS/Stripe pattern:

### New request ID

Validate and execute normally.

### Existing request ID + same fingerprint

Do not mutate.

Return/reconcile the durable original accepted result.

### Existing request ID + different fingerprint

Return an explicit parameter-mismatch error.

Never:
- silently reuse the old result for different semantics;
- create another Observation/Artifact;
- treat a request-ID collision as a new request.

## 9. Durable result

The stored request record must allow post-timeout reconciliation without replaying mutation.

At minimum it identifies:
- request ID + fingerprint/version;
- operation kind;
- accepted decision/provenance record;
- Observation;
- Artifact;
- Revision if any;
- provider binding if applicable;
- decision timestamp.

After interruption:

```text
lookup request ID
→ fingerprint match?
    yes → return/reconcile durable accepted result
    no  → mismatch error
not found → safe to attempt transaction
```

## 10. Provider binding limitation

P0-28A does **not** yet make the existing naked provider binding safe for live Drive.

Until P0-28B/P0-28C introduce history generation and object-lifetime segments:
- no live provider authority may use that binding as unconditional SAME;
- P0-28A acceptance must be able to consume future segment-scoped authority without redesign.

## 11. Reuse decisions

### AWS EC2

Reuse:
- client token generated by caller;
- exact retry with same token+parameters has no second side effect;
- token reuse with different parameters is an explicit `IdempotentParameterMismatch` class.

### Stripe

Reuse:
- retain first execution result for an idempotency key;
- compare incoming parameters with original;
- same key with differing parameters is an error;
- validation failures before execution need not consume an idempotency result.

Keelaryn differs by retaining identity-mutation provenance durably rather than pruning it after a short API retry window.

### Syncthing

Reuse later in P0-28B/C:
- separate generation/index identity from advancing sequence;
- reset creates a new generation identity.

### rclone bisync

Reuse:
- last-known-good authority;
- critical uncertainty blocks dependent mutation;
- recovery is explicit rather than pretending interrupted state is current.

## 12. Implementation sequence

P0-28A implementation should be split if needed but must remain coherent:

1. add request/fingerprint model and durable request reconciliation;
2. harden SAME replay first;
3. harden NEW replay/fingerprint;
4. introduce durable authority-reference model;
5. make acceptance derive decisions from loaded authorities;
6. retain current raw mechanism helpers only if unexported/test-only, otherwise remove them before product access;
7. exact-head Ubuntu + Windows qualification.

No live OAuth, Drive access or corpus mutation is part of P0-28A.
