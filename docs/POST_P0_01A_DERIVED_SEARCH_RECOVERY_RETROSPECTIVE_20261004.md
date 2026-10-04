# POST-P0-01A deterministic recovery retrospective — 2026-10-04

## Result

**PASS — zero new BLOCKER/CRITICAL findings.**

Canonical post-P0 growth-order item 1, **reliability and deterministic recovery**, is qualified for the currently reachable runtime recovery boundary.

This qualification supersedes the abandoned revision-235 candidate from PR #85. That earlier candidate was correctly invalidated after post-integration review found correctness gaps in the first recovery implementation.

## Qualified boundary and provenance

Initial deterministic-search recovery handoff:

- `e40a04def266cd39bf75b60662787909cc2d652b`
- integrated as `e5047c925f2d782d6823e4dc29cbae9b7ec6337c`

That initial integration was **not** sufficient for stage qualification. Subsequent review found recovery correctness defects, so qualification was held back.

Final corrective recovery handoff:

- PR #107
- `e6d7bca917bcbb07f450db5dbfc89d37c9470cb5`
- exact-head GitHub Actions run `37185732213`: validate + Ubuntu 24.04 + Windows 2025 PASS, including dependency lock, all Go tests and Go vet
- exact-head Codex review: clean after the final cancellation/timeout correction
- Sol exact-head diff review: PASS, recorded by integration claim #110
- integrated through the repository conditional-fast-forward protocol as `78e0a7dd4e2382e51561ddf2569e100ad5b6d0dd`

Current authoritative head at qualification preparation:

- `df97c5aade9fc901f033550419a983108a5f4957`
- the only later integration was governance-only rolling-discovery work
- its handoff CI run `37190663978` passed the complete validate + Ubuntu + Windows matrix on top of the integrated recovery product bytes

## Authority boundary

`state.db` remains the non-rebuildable identity/provenance authority.

`search.db`, `search.db.next`, SQLite journal/WAL/SHM members, and `search.lock` remain derived/coordination control state. None is Artifact, Revision, Observation, provider-history, identity, provenance, or result authority.

Search recovery does not repair, reconstruct, replace, downgrade, or silently discard `state.db`.

Before any derived search mutation, the runtime now runs full read-only state verification, including SQLite integrity and foreign-key checks. The same authority/corpus preflight is repeated after acquiring the search mutation lock.

The Luna test-only handoff in PR #105 was intentionally consumed as evidence: it proved on the then-authoritative base that unrelated state foreign-key damage could pass the narrower preflight and allow search recovery to proceed. The final corrective implementation makes that regression pass by failing closed before active/staged search mutation.

## Deterministic derived recovery

The recovery sequence is now:

1. resolve and verify protected control layout;
2. fully verify authoritative `state.db` and current corpus receipt/fingerprint;
3. acquire the OS-held search mutation lock;
4. repeat state/corpus preflight after serialization;
5. discard any prior staging family as interrupted derived work;
6. build a fresh `search.db.next` from current authority/corpus evidence;
7. verify the staged SourceBoundary and standalone SQLite family;
8. attempt active SQLite journal/WAL reconciliation under the original database name;
9. honor caller cancellation before the irreversible promotion boundary;
10. promote by prevalidating and discarding only the exact active derived family, then renaming the verified staging database;
11. verify the committed promoted cache with a context detached from caller cancellation but bounded by an independent five-minute timeout;
12. verify the protected control directory again.

Promotion is the derived-state commit boundary.

Before that boundary, caller cancellation must not be reclassified as corruption and must not authorize destructive disposal. After the boundary commits, caller cancellation must not make the API falsely report an uncommitted cancellation while staging has already been consumed.

## Sidecar and corruption behavior

The implementation deliberately separates SQLite reconciliation from deletion.

Reconciliation may open the active family under its original name so SQLite can perform legitimate hot-journal/WAL recovery. Reconciliation itself does not delete the active family.

If the active main database is corrupt/incompatible, or if SQLite leaves an orphan sidecar such as SHM, the later promotion path may replace the family only after:

- staged replacement verification succeeded;
- the final caller-cancellation gate passed;
- every exact active-family member was path/file validated.

Unsafe symlink/reparse aliases fail closed with zero deletion.

This closes both permanent-retry loops found during review:

- corrupt active database + sidecars;
- valid active database + surviving orphan sidecar.

## Cancellation and interruption semantics

The final design distinguishes **abortable preparation** from **committed promotion**.

Before promotion:

- pre-canceled reconciliation returns cancellation without touching the active family;
- cancellation after actual SQLite reconciliation but before promotion preserves the active cache and verified staging;
- any staging or promotion-preparation failure leaves deterministic retry state.

After the final cancellation gate:

- promotion proceeds as a bounded local commit phase;
- post-promotion verification inherits context values but not caller cancellation/deadline;
- that verification receives an independent five-minute timeout, preventing an unbounded lock hold.

This closes the later P2 review findings around cancellation racing promotion and unbounded detached verification.

## Adversarial proof

The qualified suite covers at least:

1. corrupt active `search.db`;
2. missing active `search.db`;
3. valid prior staging explicitly discarded/rebuilt;
4. valid staging with a foreign SourceBoundary;
5. corrupt/orphan staging;
6. hidden unrelated `state.db` foreign-key/schema damage before derived mutation;
7. missing/corrupt state authority;
8. corpus drift before derived mutation;
9. writer-lock contention;
10. active SQLite journal/WAL reconciliation under original names;
11. corrupt active family with sidecars;
12. orphan active SHM after successful SQLite open/close;
13. unsafe active-family alias with zero deletion;
14. cancellation before reconciliation;
15. cancellation after real reconciliation but before promotion;
16. cancellation during/immediately after committed promotion;
17. bounded cancellation-detached post-promotion verification;
18. injected failure before staged verification;
19. injected failure after staged verification but before promotion;
20. remove-before-rename interruption and deterministic retry;
21. promotion/destination failure;
22. post-promotion verification failure followed by deterministic recovery;
23. unchanged authoritative scan/inventory/revision history;
24. unchanged user corpus bytes/topology;
25. Ubuntu 24.04 and Windows 2025 qualification.

## Security and filesystem boundary

All active/staged search-family operations remain within the protected control directory.

Existing ownership/ACL, symlink/reparse, regular-file and exact-path checks remain authoritative for filesystem safety. The new promotion path broadens only the set of **derived exact SQLite family members** that may be discarded after reconciliation; it does not broaden control-directory path authority.

No public fault-injection switch or recovery bypass was added.

## Reuse and simplification

The stage reuses existing mechanisms:

- protected `controlstorage` layout and filesystem verification;
- authoritative COMPLETE scan/bootstrap receipt;
- local snapshot fingerprint;
- `searchsqlite.SourceBoundary`;
- SQLite integrity/foreign-key verification;
- SQLite-native journal/WAL recovery;
- existing read-only state/search paths;
- OS-native advisory locking via the already-present `golang.org/x/sys`.

No dependency was added.

No second recovery database, durable staging authority, external lock service, queue, vector store, or distributed coordinator was introduced.

## Carried findings

These existing findings remain open but do **not** invalidate this recovery qualification:

- `AUDIT_RELEASE_H1_STATE_DB_ROLLBACK_NOT_IMPLEMENTED` — release/update rollback and backup compatibility; this belongs to release gating / later backup-export-restore work.
- `AUDIT_RELEASE_H2_ANDROID_QUALIFICATION_ABSENT` — Android durable-state substrate and qualification remain a portability gate.
- `AUDIT_P0_36C_TOKENINFO_SCOPE_PREFLIGHT_AVAILABILITY` — live-provider availability hardening, independent of local derived recovery correctness.
- `AUDIT_P0_FINAL_L1_REPOSITORY_DESCRIPTION_STALE` — repository metadata housekeeping.

No open BLOCKER/CRITICAL finding remains for the qualified POST-P0-01 recovery boundary.

## Rolling discovery governance synchronization

After recovery integration, governance work replaced the finite eight-category Luna discovery checklist with a durable rolling `Discovery-Key` backlog and frontier synthesis model.

That governance change is already authoritative at `df97c5aade9fc901f033550419a983108a5f4957`. Revision 237 synchronizes the compact `continuation_protocol.luna_work_mode` summary and records `LUNA_ROLLING_DISCOVERY_BACKLOG_V2_ADOPTED`; it does not change runtime/product bytes.

## Growth-order decision

Canonical post-P0 item 1 is complete for current reachable reliability/recovery boundaries.

The next objective is item 2: **incremental local/provider observation**.

The first write for item 2 must be preceded by a bounded provider-neutral contract/reuse audit. Incremental observation must preserve:

- Artifact/Revision authority;
- provider-history cursor semantics;
- managed-root membership semantics;
- exact source-bound search behavior;
- read-only corpus guarantees.

Watchers or change feeds may provide hints/evidence, but must not become a second identity authority.
