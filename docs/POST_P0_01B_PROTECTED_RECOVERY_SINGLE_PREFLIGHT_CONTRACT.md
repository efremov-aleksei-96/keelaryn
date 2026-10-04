# POST-P0-01B protected recovery single-preflight contract

Status: **SOL DECISION — IMPLEMENTATION CANDIDATE**

Date: 2026-10-04

Authority: `KEELARYN_CANONICAL.md` remains product architecture authority. This note refines only the protected derived-search recovery ordering qualified by POST-P0-01A.

## 1. Problem

POST-P0-01A correctly added full read-only verification of non-rebuildable `state.db` before any derived search-family mutation. The protected rebuild path, however, invokes the same full recovery preflight twice:

1. before acquiring `search.lock`;
2. again immediately after acquiring `search.lock`.

For an existing `state.db`, each old preflight performs full `sqlitestate.VerifyReadOnly` and current COMPLETE-scan lookup. When a COMPLETE local bootstrap exists, it additionally proves the exact bootstrap receipt and traverses the local corpus to recompute the snapshot fingerprint.

A truly fresh profile with no `state.db` takes the lighter missing-state artifact check and does not run full verification or corpus traversal. An existing state database with no COMPLETE scan runs full state verification but stops before receipt/corpus proof.

The first old pass does not authorize a mutation by itself. The second pass is the proof that actually sits next to the mutation boundary.

## 2. Decision

Protected search rebuild ordering becomes:

```text
resolve/verify protected control layout
→ acquire exclusive search mutation lock
→ full state.db VerifyReadOnly
→ resolve current COMPLETE local scan
→ re-prove exact bootstrap receipt against current corpus
→ discard interrupted search.db.next family
→ build/verify staged replacement
→ reconcile active SQLite family
→ final caller-cancellation gate
→ promote
→ bounded cancellation-detached post-promotion verification
```

There is exactly one full recovery preflight in `bootstrapProtectedIndex`, and it runs **after** writer serialization and immediately before the first active/staged search-family mutation.

## 3. Why lock-first is safe

`search.lock` is coordination state, not Artifact/Revision/Observation/provider-history/provenance authority.

Creating or opening the persistent lock file is explicitly allowed before the first state transaction. The lock file can survive a crash and is never interpreted as evidence that `state.db` exists or is valid.

If non-rebuildable state is missing or corrupt, or the durable bootstrap receipt no longer matches the corpus, the post-lock preflight fails closed before:

- prior staging disposal;
- staging rebuild;
- active-family reconciliation;
- promotion.

If the lock is already held, the operation fails on contention before spending work on full state/corpus verification and performs zero active/staged search-family mutation.

## 4. Race boundary

Removing the first proof does not create a new mutation race.

The previous first proof was stale by definition once execution continued; correctness already depended on the second proof after lock acquisition. The retained proof is therefore the one closest to the first derived mutation.

The search lock does not claim to serialize unrelated state/corpus writers. Existing later guards remain unchanged:

- `BootstrapIndex` retains its exact bootstrap receipt replay/revalidation around source reads;
- staged SourceBoundary verification remains mandatory;
- active reconciliation and the final cancellation gate remain mandatory;
- promotion remains the derived commit boundary;
- post-promotion verification remains bounded and detached only after that commit boundary.

## 5. Preserved invariants

This slice MUST NOT:

- replace full `VerifyReadOnly` with `quick_check`;
- weaken foreign-key verification;
- repair or rebuild `state.db`;
- mutate user corpus bytes;
- change Artifact/Revision/ProviderObject/Locator semantics;
- add schema or public API;
- make `search.lock` authority;
- change staging trust, active-family disposal, cancellation, or promotion semantics.

## 6. Qualification proof

At minimum the exact candidate must prove:

1. writer-lock contention is returned before corrupt-state verification work and changes no active/staged search family;
2. after the lock becomes available, the same corrupt `state.db` still fails before staging disposal;
3. the existing unrelated-state foreign-key regression remains PASS;
4. all POST-P0-01A recovery/cancellation/failure-window regressions remain PASS;
5. validate + Ubuntu 24.04 + Windows 2025 CI pass on the exact candidate.

No representative large-state benchmark is claimed by this optimization. On the common completed-scan recovery path, it removes one duplicate full state verification plus one duplicate corpus-fingerprint traversal. With an existing state database but no COMPLETE scan, it removes one duplicate full state verification. Fresh missing-state profiles never performed those expensive checks, so no such saving is claimed there.
