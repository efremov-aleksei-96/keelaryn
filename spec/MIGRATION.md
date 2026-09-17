# Production Hub Migration Design

This document defines the zero-based MVP migration boundary for moving the existing production Hub into the zero-based Hub model after the limited-real-Hub-subset pilot has succeeded.

This is a design and qualification contract. It does **not** authorize migration, production mutation, Manager replacement, or cutover merely by existing in the repository.

## 1. Goals

Migration must preserve user data, preserve rollback ability, avoid ambiguous mixed ownership between legacy and zero-based systems, and produce one exact zero-based Hub identity whose initial canonical state is independently verifiable.

Migration must be:

- explicit rather than recursive-by-default;
- deterministic from a frozen migration plan and frozen source bytes;
- restart-safe;
- fail-closed on source drift or ambiguous mapping;
- proven first against a disposable target;
- reversible until final cutover acceptance;
- independent from legacy Manager runtime semantics except where a read-only source extractor deliberately consumes legacy Hub files.

## 2. Non-goals

The MVP migration does not:

- rewrite the existing production Hub in place;
- mutate production Manager 4.x during development or dry-run qualification;
- import every legacy technical artifact automatically;
- preserve legacy Manager control/state files as zero-based canonical data;
- infer new canonical ownership from file names alone;
- introduce multi-Hub runtime support;
- perform semantic deduplication automatically without an explicit reviewed migration mapping;
- publish private Hub bytes to GitHub, CI artifacts, SOURCE, DISTRIBUTION, UPDATE or AI_CONTEXT.

## 3. Migration model

Migration is a **copy-and-cutover** process, never an in-place transformation.

The old production Hub remains intact and read-only throughout source capture, mapping, rehearsal and zero-based target construction.

The migration creates a distinct zero-based target Hub. Legacy and zero-based Hubs may coexist physically during qualification, but only one may be declared the active production Hub after cutover.

The old Hub remains rollback material until post-cutover acceptance explicitly retires that rollback path.

## 4. Source freeze boundary

A production migration candidate begins by defining one exact source capture boundary.

Before source capture:

1. identify the exact production Hub root;
2. verify it is not a symlink/reparse redirect or ambiguous mount;
3. define the explicit source allowlist/mapping policy;
4. require no migration write operation against the source root;
5. fingerprint every selected source file by exact SHA-256 and byte length;
6. record a source manifest using only relative logical paths;
7. re-read every selected source file and verify the same fingerprint after capture.

If source bytes change during capture, the migration candidate is invalid and must be rebuilt from a fresh source observation.

The first implementation may require a short human-declared source quiescence window for the final production capture. Automatic writer coordination is not implied by this design.

## 5. Migration mapping

Migration mapping is semantic authority and must be explicit.

Each selected legacy source item is classified as exactly one of:

- `CANONICAL_IMPORT` — becomes one zero-based canonical file;
- `ROUTER_SOURCE` — contributes to a newly prepared INDEX/router document but is not imported verbatim as canonical truth;
- `PROJECT_WORK_IMPORT` — becomes non-canonical Project work material when deliberately preserved;
- `ARCHIVE_ONLY` — retained outside active zero-based canonical/work authority for historical reference;
- `DROP_TECHNICAL` — legacy technical/runtime artifact intentionally not imported.

A migration plan must never silently map one legacy file to multiple canonical owners or multiple legacy truths to one canonical target without an explicitly prepared replacement file.

Canonical target names and contents are frozen in the migration candidate before Core publication.

## 6. Private migration pack

The migration candidate is represented by one immutable private pack stored only in disposable/local private test space.

At minimum the pack binds:

- migration candidate ID;
- source manifest fingerprint;
- exact mapping manifest fingerprint;
- every prepared canonical payload by target name, byte length and SHA-256;
- prepared root `INDEX.md` bytes when the migration changes routing;
- expected initial canonical inventory;
- total selected/imported byte counts.

The private pack itself must never be committed or uploaded to public development infrastructure.

Sanitized evidence may contain only identities, hashes, counts, outcomes and qualification metadata that do not reveal private payload contents, local paths, Drive IDs or account identities.

## 7. Disposable full rehearsal

Before any production cutover is possible, the exact migration candidate must be rehearsed against a fresh disposable zero-based Hub.

The rehearsal must prove:

1. fresh zero-based Hub bootstrap PASS;
2. exact private migration pack verification PASS;
3. canonical publication through the ordinary Ready Change/Core path;
4. deterministic semantic/postcheck receipt for migration inventory;
5. terminal `COMMITTED`;
6. canonical epoch progression exactly as specified;
7. exact target canonical inventory and hashes;
8. clean READY/SAFE completion;
9. Workspace/Project/Reconciliation structural validity after migration;
10. ordinary consistent-reader protocol can read the migrated canonical set;
11. a subsequent no-op service iteration is IDLE;
12. restart recovery remains valid from the migrated state.

The disposable rehearsal target is destroyed or archived as test evidence according to test policy; it is never promoted by renaming or substituting unqualified bytes after the fact.

## 8. Production target construction

Production migration creates a new zero-based Hub target using the same exact qualified Core/product bytes and the exact qualified migration candidate.

The target is distinct from the legacy production Hub and begins as a fresh zero-based Hub at canonical epoch 0.

No canonical payload is written directly. Migration publication must use the ordinary Ready Change/Core transaction path.

The migration-specific postcheck must verify the entire expected migrated canonical inventory rather than only changed targets because the new target begins empty.

## 9. Cutover transaction boundary

Cutover is separate from data publication.

The migration publication may complete successfully while the legacy Hub is still the active production Hub. A successful publication therefore means **new target constructed**, not **production switched**.

Cutover may occur only after all production-target acceptance checks PASS.

The cutover transaction is logically:

1. confirm legacy source identity still matches the frozen migration source boundary or an explicitly accepted final-delta procedure;
2. confirm new zero-based target is READY/SAFE and exact;
3. confirm qualified runtime/Core identity;
4. record the old production Hub identity as rollback target;
5. atomically or unambiguously change the external production pointer/convention to the new zero-based Hub;
6. verify the new pointer resolves to the exact expected Hub;
7. run post-cutover read-only acceptance;
8. declare cutover accepted only after verification PASS.

If durable pointer change succeeds but post-cutover verification fails, evidence must state that the durable cutover occurred and rollback must use the preserved old production Hub identity. It must not pretend cutover never happened.

The exact physical production-pointer mechanism is intentionally not assumed here and must be specified before implementation. It may be a documented Drive location/convention, local sync root, launcher configuration or another single authoritative selector, but ambiguity is forbidden.

## 10. Source drift between rehearsal and cutover

The migration rehearsal does not authorize using stale source bytes if the production Hub changes afterward.

Before final production construction/cutover, one of these must be true:

- the production source was intentionally frozen and fingerprints still match the qualified migration candidate; or
- an explicit final-delta migration candidate is built, rehearsed and qualified against the newer source identity.

Silent delta inference is forbidden.

## 11. Rollback

Rollback exists at two layers.

### Publication rollback

Before cutover, any migration publication failure uses the ordinary zero-based Core rollback rules on the new target. The legacy production Hub remains untouched and active.

### Cutover rollback

After cutover, rollback means restoring the external production pointer/convention to the preserved legacy production Hub identity.

Cutover rollback must not copy zero-based target bytes back into the legacy Hub and must not rewrite the legacy Hub to resemble the new structure.

The failed zero-based target and all qualification evidence are preserved for diagnosis until explicitly cleaned up.

## 12. Acceptance gates

Production migration is not approved until all applicable gates PASS against exact identities:

- migration plan/schema validation;
- source capture/fingerprint verification;
- private pack deterministic verification;
- disposable full rehearsal;
- exact Core/source commit qualification;
- real Google Drive target construction;
- migrated canonical inventory verification;
- Workspace/Project/Reconciliation structural verification;
- restart/recovery verification;
- reader SAFE/epoch verification;
- production-target Doctor/SelfTest equivalent appropriate to zero-based architecture;
- cutover-pointer rollback rehearsal on a disposable selector;
- final production-specific acceptance.

Development CI and disposable rehearsal are necessary evidence but are not production qualification by themselves.

## 13. Evidence and provenance

Migration evidence must bind at minimum:

- exact zero-based source commit/tree;
- migration candidate ID;
- source-manifest digest;
- mapping-manifest digest;
- private migration-pack digest;
- managed/imported canonical inventory digest;
- Core/runtime identity;
- disposable rehearsal run identity;
- production construction evidence identity;
- cutover selector identity/revision when implemented;
- terminal outcomes and canonical epochs.

Private source paths, payload bytes, Google Drive object IDs, account email addresses, OAuth credentials and local workstation paths are excluded from public repository evidence.

## 14. Cleanup policy

Do not clean migration source captures, private packs, disposable rehearsal evidence or failed targets until the corresponding evidence is durably recorded and the migration candidate is no longer needed for diagnosis or rollback.

After successful production cutover and acceptance, cleanup of disposable migration material is a separate explicit action. The legacy production Hub is retained until rollback retirement is separately approved.

## 15. Implementation order

The migration implementation must proceed in this order:

1. define strict migration source/mapping/pack schemas;
2. implement read-only source capture and deterministic pack builder/verifier;
3. add adversarial filesystem/Windows tests for source drift, reparse points, traversal, duplicates and byte-exactness;
4. implement disposable full-rehearsal orchestration using the existing Drive/Core path;
5. add restart/fault-injection coverage for migration preparation and publication;
6. define the exact production selector/cutover mechanism;
7. rehearse selector switch + rollback against disposable targets;
8. freeze a migration candidate only after coherent development PASS;
9. run production-target qualification;
10. request explicit production cutover approval;
11. perform cutover and production acceptance;
12. retain rollback source until separate retirement approval.

No earlier step implies permission to perform a later production step.
